"""Pruebas integradas del lifespan y de la API técnica."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from copy import deepcopy
from typing import Any, cast

import pytest
import sis_leg_backend.aplicacion as modulo_aplicacion
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sis_leg_backend.aplicacion import crear_aplicacion
from sis_leg_backend.dominio.estado import EstadoGlobal
from sis_leg_backend.recursos import (
    NOMBRE_RECURSOS,
    obtener_recursos_aplicacion,
)
from sis_leg_backend.servicios.fronteras_temporales import ServicioFronterasTemporales
from sis_leg_backend.servicios.proyecciones import ServicioProyecciones
from sis_leg_backend.servicios.publicacion import (
    CoordinadorPublicacion,
    SuscripcionProyeccion,
)
from sis_leg_backend.servicios.serializacion import EjecutorMutaciones

pytestmark = pytest.mark.anyio


class ProyeccionesConRetornoRastreado:
    """Ofrece siempre un deadline y avisa si el servicio vuelve a su ciclo.

    El primer cálculo inicia el escenario normal. Un segundo cálculo solo puede
    ocurrir si la cancelación externa del servicio fue absorbida durante el
    cleanup y ``ejecutar()`` regresó indebidamente al ``while True``.
    """

    def __init__(self) -> None:
        self.cantidad_calculos = 0
        self.retorno_al_ciclo = asyncio.Event()

    def demora_hasta_proxima_frontera(self) -> float:
        """Devuelve un deadline fijo y registra cada vuelta del servicio."""

        self.cantidad_calculos += 1
        if self.cantidad_calculos > 1:
            self.retorno_al_ciclo.set()
        return 1.0


class SuscripcionRastreada(SuscripcionProyeccion):
    """Registra sus esperas y cuántas veces el servicio libera la suscripción."""

    def __init__(self, coordinador: CoordinadorPublicacion) -> None:
        super().__init__(coordinador)
        self.tareas_espera: list[asyncio.Task[Any]] = []
        self.cantidad_cancelaciones = 0

    async def esperar_revision_superior(self, revision_conocida: int) -> int:
        """Conserva la tarea hija para comprobar que no quede pendiente."""

        tarea_actual = asyncio.current_task()
        assert tarea_actual is not None
        self.tareas_espera.append(tarea_actual)
        return await super().esperar_revision_superior(revision_conocida)

    def cancelar(self) -> None:
        """Cuenta la liberación antes de delegar en el cleanup idempotente real."""

        self.cantidad_cancelaciones += 1
        super().cancelar()


class CoordinadorRastreado(CoordinadorPublicacion):
    """Crea una suscripción observable sin cambiar su comportamiento productivo."""

    def __init__(self) -> None:
        super().__init__()
        self.suscripcion_creada: SuscripcionRastreada | None = None

    def suscribir(self) -> SuscripcionProyeccion:
        """Registra la única suscripción del servicio de fronteras."""

        suscripcion = SuscripcionRastreada(self)
        self._suscripciones.add(suscripcion)
        self.suscripcion_creada = suscripcion
        return suscripcion


class ServicioFronterasRastreado(ServicioFronterasTemporales):
    """Expone solo a la prueba la tarea de servicio creada por el lifespan."""

    def __init__(
        self,
        servicio_proyecciones: ServicioProyecciones,
        ejecutor_mutaciones: EjecutorMutaciones,
        coordinador: CoordinadorPublicacion,
        *,
        esperar: Callable[[float], Awaitable[None]],
        procesar_efectos_pendientes: Callable[[], Awaitable[None]] | None = None,
        hay_efecto_pendiente: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__(
            servicio_proyecciones,
            ejecutor_mutaciones,
            coordinador,
            esperar=esperar,
            procesar_efectos_pendientes=procesar_efectos_pendientes,
            hay_efecto_pendiente=hay_efecto_pendiente,
        )
        self.tarea_ejecucion: asyncio.Task[None] | None = None

    async def ejecutar(self) -> None:
        """Registra la tarea padre y conserva el ciclo productivo sin alterarlo."""

        tarea_actual = asyncio.current_task()
        assert tarea_actual is not None
        self.tarea_ejecucion = cast(asyncio.Task[None], tarea_actual)
        await super().ejecutar()


async def test_lifespan_crea_una_instancia_y_la_descarta_al_finalizar() -> None:
    """Los recursos solamente están disponibles dentro del ciclo de vida."""

    aplicacion = crear_aplicacion()
    assert not hasattr(aplicacion.state, NOMBRE_RECURSOS)

    async with aplicacion.router.lifespan_context(aplicacion):
        recursos = obtener_recursos_aplicacion(aplicacion)
        assert recursos is obtener_recursos_aplicacion(aplicacion)
        assert recursos.estado_operativo.estado_global is EstadoGlobal.SIN_PREPARAR

    assert not hasattr(aplicacion.state, NOMBRE_RECURSOS)


async def test_lifespan_no_pierde_cancelacion_durante_cleanup_de_frontera(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fuerza la carrera exacta entre cleanup de una hija y cancelación padre.

    La publicación completa primero la espera de revisión. El servicio cancela
    entonces el timer perdedor, que demora deliberadamente su propia
    cancelación y deja al padre aguardándolo. Recién en ese punto se solicita la
    salida del lifespan: esa segunda cancelación dirigida al padre debe
    propagarse, terminar ambas hijas y liberar la suscripción sin volver al
    ciclo principal.
    """

    proyecciones = ProyeccionesConRetornoRastreado()
    coordinador = CoordinadorRastreado()
    ejecutor = EjecutorMutaciones(coordinador.publicar)
    espera_temporal_iniciada = asyncio.Event()
    timer_en_cleanup = asyncio.Event()
    bloqueo_timer = asyncio.Event()
    tareas_timer: list[asyncio.Task[Any]] = []
    servicio_creado: ServicioFronterasRastreado | None = None

    async def esperar_controlado(_demora: float) -> None:
        """Mantiene el primer timer cancelándose hasta recibir la cancelación padre."""

        tarea_actual = asyncio.current_task()
        assert tarea_actual is not None
        tareas_timer.append(tarea_actual)
        espera_temporal_iniciada.set()
        try:
            await bloqueo_timer.wait()
        except asyncio.CancelledError:
            # Solo el primer ciclo se detiene en cleanup. Si el defecto hace que
            # aparezca un segundo ciclo, su timer debe poder limpiarse con una
            # única cancelación para que la propia regresión falle sin colgar.
            if len(tareas_timer) == 1:
                timer_en_cleanup.set()
                await bloqueo_timer.wait()
            raise

    def crear_servicio_controlado(
        _servicio_proyecciones: ServicioProyecciones,
        _ejecutor_mutaciones: EjecutorMutaciones,
        _coordinador: CoordinadorPublicacion,
        *,
        procesar_efectos_pendientes: Callable[[], Awaitable[None]] | None = None,
        hay_efecto_pendiente: Callable[[], bool] | None = None,
    ) -> ServicioFronterasTemporales:
        """Sustituye solo dependencias temporales sin cambiar el lifespan probado.

        El cierre de marcadores de WP-078 y la consulta de efecto pendiente de
        WP-081 se reenvían tal como los arma el lifespan: esta prueba sustituye
        el reloj y las proyecciones, no el cableado que está probando. Acá nunca
        llegan a ejecutarse porque el timer queda bloqueado antes de cruzar
        ninguna frontera.
        """

        nonlocal servicio_creado
        servicio_creado = ServicioFronterasRastreado(
            cast(ServicioProyecciones, proyecciones),
            ejecutor,
            coordinador,
            esperar=esperar_controlado,
            procesar_efectos_pendientes=procesar_efectos_pendientes,
            hay_efecto_pendiente=hay_efecto_pendiente,
        )
        return servicio_creado

    monkeypatch.setattr(
        modulo_aplicacion,
        "ServicioFronterasTemporales",
        crear_servicio_controlado,
    )
    aplicacion = crear_aplicacion()
    lifespan_iniciado = asyncio.Event()
    solicitar_salida = asyncio.Event()

    async def usar_lifespan() -> None:
        """Abre la aplicación y solicita su teardown cuando lo ordena la prueba."""

        async with aplicacion.router.lifespan_context(aplicacion):
            lifespan_iniciado.set()
            await solicitar_salida.wait()

    tarea_lifespan = asyncio.create_task(usar_lifespan())
    await lifespan_iniciado.wait()
    await espera_temporal_iniciada.wait()

    # La revisión gana la carrera y obliga al servicio a cancelar/esperar el
    # timer. ``timer_en_cleanup`` es la barrera exacta, no una aproximación por
    # tiempo o cantidad de repeticiones.
    coordinador.publicar()
    await timer_en_cleanup.wait()
    solicitar_salida.set()

    tarea_retorno = asyncio.create_task(proyecciones.retorno_al_ciclo.wait())
    completadas, _ = await asyncio.wait(
        (tarea_lifespan, tarea_retorno),
        return_when=asyncio.FIRST_COMPLETED,
    )
    termino_sin_retorno = tarea_lifespan in completadas

    # Contra el patrón defectuoso, el evento de retorno gana: limpiamos las
    # tareas antes de afirmar para que la regresión falle de forma acotada.
    if not termino_sin_retorno:
        assert servicio_creado is not None
        assert servicio_creado.tarea_ejecucion is not None
        servicio_creado.tarea_ejecucion.cancel()
        with suppress(asyncio.CancelledError):
            await servicio_creado.tarea_ejecucion
        await tarea_lifespan

    tarea_retorno.cancel()
    await asyncio.gather(tarea_retorno, return_exceptions=True)

    assert termino_sin_retorno
    assert servicio_creado is not None
    assert servicio_creado.tarea_ejecucion is not None
    assert servicio_creado.tarea_ejecucion.cancelled()
    assert not proyecciones.retorno_al_ciclo.is_set()
    assert all(tarea.done() for tarea in tareas_timer)
    assert coordinador.suscripcion_creada is not None
    assert all(tarea.done() for tarea in coordinador.suscripcion_creada.tareas_espera)
    assert coordinador.suscripcion_creada.cantidad_cancelaciones == 1
    assert coordinador.cantidad_suscripciones == 0
    assert not hasattr(aplicacion.state, NOMBRE_RECURSOS)


async def test_reinicio_crea_un_estado_operativo_nuevo() -> None:
    """Dos ciclos de vida no comparten ni reconstruyen el estado en memoria."""

    aplicacion = crear_aplicacion()

    async with aplicacion.router.lifespan_context(aplicacion):
        estado_anterior = obtener_recursos_aplicacion(aplicacion).estado_operativo

    async with aplicacion.router.lifespan_context(aplicacion):
        estado_nuevo = obtener_recursos_aplicacion(aplicacion).estado_operativo

    assert estado_nuevo is not estado_anterior
    assert estado_nuevo.estado_global is EstadoGlobal.SIN_PREPARAR


async def test_health_responde_sin_modificar_estado() -> None:
    """El health check es una consulta técnica y no una operación funcional."""

    aplicacion = crear_aplicacion()

    async with aplicacion.router.lifespan_context(aplicacion):
        recursos = obtener_recursos_aplicacion(aplicacion)
        estado_antes = deepcopy(recursos.estado_operativo)
        transporte = ASGITransport(app=aplicacion)

        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            respuesta = await cliente.get("/api/v1/health")

        assert respuesta.status_code == 200
        assert respuesta.json() == {"estado": "ok"}
        assert recursos.estado_operativo == estado_antes
        assert recursos is obtener_recursos_aplicacion(aplicacion)


async def test_error_inesperado_no_expone_detalles_internos() -> None:
    """La API informa un fallo estable sin filtrar el texto de la excepción."""

    aplicacion = crear_aplicacion()

    async def provocar_error() -> None:
        raise RuntimeError("detalle que no debe llegar al cliente")

    aplicacion.add_api_route("/error-sintetico", provocar_error, methods=["GET"])

    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion, raise_app_exceptions=False)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            respuesta = await cliente.get("/error-sintetico")

    assert respuesta.status_code == 500
    assert respuesta.json() == {
        "codigo": "ERROR_INTERNO",
        "mensaje": "Ocurrió un error interno.",
    }
    assert "detalle" not in respuesta.text


def test_factory_construye_aplicaciones_independientes() -> None:
    """La factory no comparte el almacén de estado entre aplicaciones."""

    primera: FastAPI = crear_aplicacion()
    segunda: FastAPI = crear_aplicacion()

    assert primera is not segunda
    assert primera.state is not segunda.state
