"""Temporizador único que publica solamente en deadlines relevantes."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from sis_leg_backend.auditoria import ErrorAuditoria
from sis_leg_backend.servicios.proyecciones import ServicioProyecciones
from sis_leg_backend.servicios.publicacion import CoordinadorPublicacion
from sis_leg_backend.servicios.serializacion import EjecutorMutaciones

REGISTRO = logging.getLogger(__name__)


class ServicioFronterasTemporales:
    """Espera test, revelado y expiración pública sin realizar polling.

    Existe una sola instancia/tarea por lifespan. Cada cambio funcional la
    despierta para recalcular la frontera más cercana; cada deadline completado
    publica una revisión bajo el lock compartido. ``esperar`` es inyectable
    para que las pruebas controlen el tiempo sin aguardar segundos reales.

    Desde WP-078 el cruce de una frontera puede además **registrar un hecho**:
    el aviso que vence en la Pantalla del Recinto cierra su período con un
    evento principal ``FIN``. Ese trabajo no vive acá sino en
    ``cerrar_marcadores_vencidos``, una corrutina inyectada por el lifespan, de
    modo que el temporizador siga sin conocer reglas del plano técnico.
    """

    def __init__(
        self,
        servicio_proyecciones: ServicioProyecciones,
        ejecutor_mutaciones: EjecutorMutaciones,
        coordinador: CoordinadorPublicacion,
        *,
        esperar: Callable[[float], Awaitable[None]] = asyncio.sleep,
        cerrar_marcadores_vencidos: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._proyecciones = servicio_proyecciones
        self._ejecutor = ejecutor_mutaciones
        self._coordinador = coordinador
        self._esperar = esperar
        self._cerrar_marcadores_vencidos = cerrar_marcadores_vencidos

    async def ejecutar(self) -> None:
        """Mantiene el ciclo hasta que el lifespan cancela esta tarea."""

        suscripcion = self._coordinador.suscribir()
        try:
            while True:
                revision, demora = await self._ejecutor.leer_coherente(
                    lambda: (
                        self._coordinador.revision,
                        self._proyecciones.demora_hasta_proxima_frontera(),
                    )
                )
                if demora is None:
                    await suscripcion.esperar_revision_superior(revision)
                    continue

                cambio = asyncio.create_task(suscripcion.esperar_revision_superior(revision))
                tiempo = asyncio.create_task(self._esperar_demora(demora))
                try:
                    completadas, _ = await asyncio.wait(
                        (cambio, tiempo),
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    # Si simultáneamente llegó una mutación, esa publicación ya
                    # reconstruirá el payload con el reloj vigente. Solo se crea
                    # una revisión temporal adicional cuando el timer fue la
                    # única causa del despertar.
                    if tiempo in completadas and cambio not in completadas:
                        await self._cruzar_frontera()
                finally:
                    for tarea in (cambio, tiempo):
                        if not tarea.done():
                            tarea.cancel()

                    # ``return_exceptions`` convierte la cancelación interna de
                    # una hija en un resultado que podemos reconocer. En cambio,
                    # si el lifespan cancela esta tarea padre mientras espera el
                    # ``gather``, asyncio cancela el propio gather y propaga su
                    # ``CancelledError``. Así el cleanup de las hijas nunca puede
                    # consumir por accidente la cancelación externa del servicio.
                    resultados = await asyncio.gather(
                        cambio,
                        tiempo,
                        return_exceptions=True,
                    )
                    for resultado in resultados:
                        if isinstance(resultado, BaseException) and not isinstance(
                            resultado,
                            asyncio.CancelledError,
                        ):
                            # Las cancelaciones esperadas son parte del cleanup;
                            # cualquier otro fallo de una hija sigue siendo un
                            # error real y conserva la propagación previa.
                            raise resultado
        finally:
            suscripcion.cancelar()

    async def _cruzar_frontera(self) -> None:
        """Publica el cruce y, si corresponde, cierra los períodos vencidos.

        Sin la corrutina de cierre inyectada el comportamiento es el histórico:
        publicar una revisión para que REST/SSE reconstruyan el DTO con el reloj
        vigente. Con ella, el cierre corre bajo el mismo ``EjecutorMutaciones``,
        que ya publica la revisión al salir del lock, así que un cruce sigue
        produciendo una sola publicación.

        Un fallo de auditoría no puede matar el temporizador. Si lo hiciera, el
        proceso dejaría además de publicar todas las demás fronteras (cuenta
        regresiva, revelado, resultado público) por un escritor que de todos
        modos ya quedó en fallo cerrado permanente. El error se registra, el
        período queda abierto —no se anuncia una transición que no se persistió—
        y el ciclo continúa; el ``finally`` del ejecutor ya publicó la revisión.
        """

        if self._cerrar_marcadores_vencidos is None:
            await self._ejecutor.publicar_frontera_temporal()
            return
        try:
            await self._cerrar_marcadores_vencidos()
        except ErrorAuditoria:
            REGISTRO.exception(
                "No se pudo registrar el FIN automático de un aviso de la Pantalla del Recinto"
            )

    async def _esperar_demora(self, demora: float) -> None:
        """Convierte el ``Awaitable`` inyectable en una coroutine tipada."""

        await self._esperar(demora)
