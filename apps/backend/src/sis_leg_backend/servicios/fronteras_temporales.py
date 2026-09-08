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
    ``procesar_efectos_pendientes``, una corrutina inyectada por el lifespan, de
    modo que el temporizador siga sin conocer reglas del plano técnico. WP-092
    incorpora por esa misma costura el inicio efectivo de una transmisión.

    Desde WP-081 ese hecho tampoco se decide observando qué tarea de espera
    quedó ``done``. El lifespan inyecta además ``hay_efecto_pendiente``, una
    consulta síncrona que responde si una frontera ya alcanzada dejó un efecto
    institucional sin ejecutar. Preguntarlo al comienzo de cada vuelta es lo
    que vuelve al cierre independiente del orden en que el planificador de
    asyncio despachó los callbacks del ciclo anterior.
    """

    def __init__(
        self,
        servicio_proyecciones: ServicioProyecciones,
        ejecutor_mutaciones: EjecutorMutaciones,
        coordinador: CoordinadorPublicacion,
        *,
        esperar: Callable[[float], Awaitable[None]] = asyncio.sleep,
        procesar_efectos_pendientes: Callable[[], Awaitable[None]] | None = None,
        hay_efecto_pendiente: Callable[[], bool] | None = None,
    ) -> None:
        self._proyecciones = servicio_proyecciones
        self._ejecutor = ejecutor_mutaciones
        self._coordinador = coordinador
        self._esperar = esperar
        self._procesar_efectos_pendientes = procesar_efectos_pendientes
        self._hay_efecto_pendiente = hay_efecto_pendiente

    async def ejecutar(self) -> None:
        """Mantiene el ciclo hasta que el lifespan cancela esta tarea."""

        suscripcion = self._coordinador.suscribir()
        try:
            while True:
                revision, demora, pendiente = await self._ejecutor.leer_coherente(
                    lambda: (
                        self._coordinador.revision,
                        self._proyecciones.demora_hasta_proxima_frontera(),
                        self._hay_efecto_pendiente is not None and self._hay_efecto_pendiente(),
                    )
                )

                # Autoridad de tiempo, no estado de tarea (WP-081).
                #
                # Una frontera ya alcanzada deja de aportar demora: el cálculo
                # sólo devuelve vencimientos futuros. Si el efecto institucional
                # de esa frontera todavía no se ejecutó, nadie más va a
                # ejecutarlo, y esperar una frontera nueva sería perderlo para
                # siempre. Por eso el cruce se decide acá, comparando el estado
                # real contra el reloj, y no por si la tarea de espera del ciclo
                # anterior alcanzó a marcarse ``done`` antes de ser cancelada.
                if pendiente:
                    if not await self._cruzar_frontera():
                        # El escritor institucional está en fallo cerrado. El
                        # efecto sigue pendiente, así que reintentar de
                        # inmediato sería un ciclo ocupado que no puede auditar
                        # nada. Se espera un cambio real antes de volver a
                        # intentarlo.
                        #
                        # La espera se ancla en la revisión observada **después**
                        # del intento, no en la de antes. El intento fallido
                        # publica su propia revisión: ``EjecutorMutaciones``
                        # notifica en su ``finally`` incluso cuando la mutación
                        # lanza, política deliberada que mantiene a REST/SSE
                        # alineados con los flujos de fallo cerrado parcial.
                        # Anclarla antes haría que esa publicación propia contara
                        # como cambio externo y el ciclo reintentaría sin pausa,
                        # publicando una revisión por vuelta.
                        #
                        # Leer la revisión acá es exacto: entre el retorno del
                        # cruce y esta línea no hay ningún ``await``, así que
                        # ninguna otra corrutina pudo intercalarse. El valor
                        # incluye todo lo publicado hasta este instante —el
                        # propio fallo y cualquier mutación que haya corrido
                        # mientras tanto—, de modo que sólo un cambio realmente
                        # posterior vuelve a habilitar el reintento.
                        await suscripcion.esperar_revision_superior(self._coordinador.revision)
                    continue

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
                    # Este cruce cubre únicamente la parte *publicable* del
                    # despertar: reconstruir el payload cuando el mero paso del
                    # tiempo cambió qué datos puede contener. Si simultáneamente
                    # llegó una mutación, su propia publicación ya hace ese
                    # trabajo y repetirla sería una revisión de más.
                    #
                    # Los efectos institucionales de una frontera **no** dependen
                    # de esta condición: los resuelve la comprobación de efecto
                    # pendiente al comienzo de la vuelta siguiente, que mira el
                    # reloj y no el estado de estas dos tareas (WP-081).
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

    async def _cruzar_frontera(self) -> bool:
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

        Devuelve:
            ``True`` cuando el cruce quedó resuelto y ``False`` cuando la
            auditoría impidió ejecutar su efecto institucional. Quien cruza por
            un efecto pendiente usa ese valor para no reintentarlo en un ciclo
            ocupado: un escritor en fallo cerrado no se recupera solo, así que
            volver a intentar sin esperar un cambio real sólo quemaría CPU.
        """

        if self._procesar_efectos_pendientes is None:
            await self._ejecutor.publicar_frontera_temporal()
            return True
        try:
            await self._procesar_efectos_pendientes()
        except ErrorAuditoria:
            REGISTRO.exception("No se pudo registrar un efecto automático de una frontera temporal")
            return False
        return True

    async def _esperar_demora(self, demora: float) -> None:
        """Convierte el ``Awaitable`` inyectable en una coroutine tipada."""

        await self._esperar(demora)
