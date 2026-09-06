"""Pruebas de SSE completo, revisiones, backpressure y cleanup."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import suppress
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import Request
from sis_leg_backend.api.estado import (
    generar_stream_estado,
    transmitir_estado_moderacion,
    transmitir_estado_recinto,
)
from sis_leg_backend.aplicacion import crear_aplicacion
from sis_leg_backend.dominio.votacion import (
    ResultadoVotacion,
    ValorVotoOrdinario,
    VotoOrdinario,
)
from sis_leg_backend.servicios.fronteras_temporales import ServicioFronterasTemporales

from tests.backend.ayudas_proyecciones import (
    abrir_sesion_prueba,
    abrir_votacion_prueba,
    crear_entorno_proyecciones,
)

pytestmark = pytest.mark.anyio


def decodificar_evento(contenido: str) -> tuple[int, dict[str, Any]]:
    """Extrae ``id`` y JSON de un mensaje SSE funcional completo."""

    lineas = contenido.rstrip("\n").splitlines()
    assert lineas[1] == "event: estado"
    revision = int(lineas[0].removeprefix("id: "))
    datos = cast(dict[str, Any], json.loads(lineas[2].removeprefix("data: ")))
    assert isinstance(datos, dict)
    return revision, datos


async def cerrar_flujo(
    flujo: AsyncGenerator[str],
) -> None:
    """Cierra el generador y ejecuta su ``finally`` de desuscripción."""

    await flujo.aclose()


async def test_primer_payload_es_inmediato_completo_y_con_revision(tmp_path: Path) -> None:
    """El stream no espera una mutación inicial para reconstruir la vista."""

    entorno = crear_entorno_proyecciones(tmp_path)
    flujo = generar_stream_estado(
        entorno.servicio.obtener_estado_moderacion,
        entorno.coordinador,
    )

    contenido = await anext(flujo)
    revision, datos = decodificar_evento(contenido)

    assert revision == 0
    assert datos["revision"] == revision
    assert datos["estado_global"] == "PREPARANDO"
    assert len(datos["concejales"]) == 3
    assert "capacidades" in datos
    await cerrar_flujo(flujo)
    assert entorno.coordinador.cantidad_suscripciones == 0


async def test_revision_avanza_tambien_si_operacion_falla_despues_de_mutar(
    tmp_path: Path,
) -> None:
    """El ``finally`` publica el estado parcial sin convertir el error en éxito."""

    entorno = crear_entorno_proyecciones(tmp_path)
    dni = entorno.contexto.padron.concejales[0].dni

    async def mutacion_parcial() -> None:
        entorno.contexto.presencias[dni] = True
        raise RuntimeError("fallo posterior")

    with pytest.raises(RuntimeError, match="fallo posterior"):
        await entorno.ejecutor.ejecutar(mutacion_parcial)

    estado = await entorno.servicio.obtener_estado_moderacion()
    assert estado.revision == 1
    assert estado.concejales[0].presente


async def test_cliente_lento_salta_revisiones_sin_cola_intermedia(tmp_path: Path) -> None:
    """Tres publicaciones coalescen y el siguiente DTO llega directamente en 3."""

    entorno = crear_entorno_proyecciones(tmp_path)
    flujo = generar_stream_estado(entorno.servicio.obtener_estado_moderacion, entorno.coordinador)
    primera_revision, _ = decodificar_evento(await anext(flujo))
    assert primera_revision == 0

    for indice in range(3):

        async def mutacion(indice_actual: int = indice) -> None:
            entorno.contexto.numero_sesion = indice_actual + 1

        await entorno.ejecutor.ejecutar(mutacion)

    revision_actual, datos = decodificar_evento(await anext(flujo))
    assert revision_actual == 3
    assert datos["preparacion"]["numero_sesion"] == 3
    await cerrar_flujo(flujo)


async def test_cambios_de_presencia_palabra_votacion_voto_y_autoridad_emiten(
    tmp_path: Path,
) -> None:
    """Las fronteras funcionales exigidas producen DTOs completos sucesivos."""

    entorno = crear_entorno_proyecciones(tmp_path, revelado_moderacion=0)
    sesion = abrir_sesion_prueba(entorno)
    flujo = generar_stream_estado(entorno.servicio.obtener_estado_moderacion, entorno.coordinador)
    await anext(flujo)
    dni = entorno.contexto.padron.concejales[0].dni

    async def cambiar_presencia() -> None:
        entorno.contexto.presencias[dni] = True

    await entorno.ejecutor.ejecutar(cambiar_presencia)
    revision_1, presencia = decodificar_evento(await anext(flujo))
    assert presencia["concejales"][0]["presente"]

    async def pedir_palabra() -> None:
        sesion.palabra.agregar_pedido(dni)

    await entorno.ejecutor.ejecutar(pedir_palabra)
    revision_2, palabra = decodificar_evento(await anext(flujo))
    assert palabra["palabra"]["cola"][0]["dni"] == dni

    async def abrir_votacion() -> None:
        abrir_votacion_prueba(entorno)

    await entorno.ejecutor.ejecutar(abrir_votacion)
    revision_3, votacion = decodificar_evento(await anext(flujo))
    assert votacion["votacion"]["estado_recepcion"] == "EN_CURSO"

    async def votar() -> None:
        activa = entorno.estado.votacion_activa
        assert activa is not None
        activa.registrar_voto(VotoOrdinario(dni, ValorVotoOrdinario.POSITIVO))

    await entorno.ejecutor.ejecutar(votar)
    revision_4, voto = decodificar_evento(await anext(flujo))
    assert voto["votacion"]["votos_individuales"][0]["valor"] == "POSITIVO"

    async def cambiar_autoridad() -> None:
        entorno.contexto.presidencia = "Nueva Presidencia"

    await entorno.ejecutor.ejecutar(cambiar_autoridad)
    revision_5, autoridad = decodificar_evento(await anext(flujo))
    assert autoridad["sesion"]["presidencia"] == "Nueva Presidencia"
    assert [revision_1, revision_2, revision_3, revision_4, revision_5] == [1, 2, 3, 4, 5]
    await cerrar_flujo(flujo)


async def test_varias_conexiones_reciben_la_misma_revision_y_limpian_recursos(
    tmp_path: Path,
) -> None:
    """Desconectar una conexión no afecta a la otra ni deja referencias."""

    entorno = crear_entorno_proyecciones(tmp_path)
    primero = generar_stream_estado(entorno.servicio.obtener_estado_moderacion, entorno.coordinador)
    segundo = generar_stream_estado(entorno.servicio.obtener_estado_moderacion, entorno.coordinador)
    await anext(primero)
    await anext(segundo)
    assert entorno.coordinador.cantidad_suscripciones == 2

    async def cambiar() -> None:
        entorno.contexto.numero_sesion = 22

    await entorno.ejecutor.ejecutar(cambiar)
    revision_primera, _ = decodificar_evento(await anext(primero))
    revision_segunda, _ = decodificar_evento(await anext(segundo))
    assert revision_primera == revision_segunda == 1

    await cerrar_flujo(primero)
    assert entorno.coordinador.cantidad_suscripciones == 1
    await cerrar_flujo(segundo)
    assert entorno.coordinador.cantidad_suscripciones == 0


async def test_stream_publico_no_mezcla_dto_ni_filtra_voto(tmp_path: Path) -> None:
    """La prueba inspecciona el ``data:`` real y no solo el modelo previo."""

    entorno = crear_entorno_proyecciones(tmp_path)
    votacion = abrir_votacion_prueba(entorno)
    dni = entorno.contexto.padron.concejales[0].dni
    votacion.registrar_voto(VotoOrdinario(dni, ValorVotoOrdinario.NEGATIVO))
    flujo = generar_stream_estado(entorno.servicio.obtener_estado_recinto, entorno.coordinador)

    contenido = await anext(flujo)
    _, datos = decodificar_evento(contenido)

    assert datos["votacion"]["votos_individuales"] is None
    assert dni not in contenido
    assert "NEGATIVO" not in contenido
    assert "capacidades" not in datos
    assert "eventos_recientes" not in datos
    assert datos["eventos_publicos"] == []
    await cerrar_flujo(flujo)


async def test_carrera_snapshot_mutacion_apertura_stream_entrega_estado_vigente(
    tmp_path: Path,
) -> None:
    """El primer SSE posterior a una mutación no depende del snapshot anterior."""

    entorno = crear_entorno_proyecciones(tmp_path)
    anterior = await entorno.servicio.obtener_estado_moderacion()
    dni = entorno.contexto.padron.concejales[0].dni

    async def cambiar() -> None:
        entorno.contexto.presencias[dni] = True

    await entorno.ejecutor.ejecutar(cambiar)
    flujo = generar_stream_estado(entorno.servicio.obtener_estado_moderacion, entorno.coordinador)
    revision, datos = decodificar_evento(await anext(flujo))

    assert revision > anterior.revision
    assert datos["concejales"][0]["presente"]
    await cerrar_flujo(flujo)


@pytest.mark.parametrize("frontera", ("test", "revelado", "resultado"))
async def test_temporizador_controlado_publica_vencimientos_sin_sleep_real(
    tmp_path: Path,
    frontera: str,
) -> None:
    """La tarea única despierta exactamente en la frontera inyectada."""

    entorno = crear_entorno_proyecciones(
        tmp_path,
        revelado_moderacion=0 if frontera == "resultado" else 4,
        resultado_publico=6,
        duracion_test=2,
    )
    if frontera == "test":
        dni = entorno.contexto.padron.concejales[0].dni
        entorno.contexto.activar_test_dispositivo(dni, entorno.reloj.monotono())
    else:
        votacion = abrir_votacion_prueba(entorno)
        if frontera == "resultado":
            votacion.cerrar_recepcion(entorno.reloj.ahora())
            votacion.aplicar_resultado_ordinario(
                resultado=ResultadoVotacion.APROBADA,
                fecha_hora_resultado=entorno.reloj.ahora(),
            )
            entorno.estado.votacion_activa = None

    espera_iniciada = asyncio.Event()
    liberar_espera = asyncio.Event()
    demora_programada: list[float] = []

    async def esperar_controlado(demora: float) -> None:
        demora_programada.append(demora)
        espera_iniciada.set()
        await liberar_espera.wait()
        entorno.reloj.avanzar(demora)

    fronteras = ServicioFronterasTemporales(
        entorno.servicio,
        entorno.ejecutor,
        entorno.coordinador,
        esperar=esperar_controlado,
    )
    observador = entorno.coordinador.suscribir()
    tarea = asyncio.create_task(fronteras.ejecutar())
    await espera_iniciada.wait()
    revision_anterior = entorno.coordinador.revision
    liberar_espera.set()
    revision_nueva = await observador.esperar_revision_superior(revision_anterior)

    assert revision_nueva == revision_anterior + 1
    assert demora_programada == [2 if frontera == "test" else 4 if frontera == "revelado" else 6]

    tarea.cancel()
    with suppress(asyncio.CancelledError):
        await tarea
    observador.cancelar()
    assert entorno.coordinador.cantidad_suscripciones == 0


async def test_endpoints_stream_declaran_content_type_y_openapi_sin_aliases() -> None:
    """Los cuatro paths canónicos son los únicos contratos de estado nuevos."""

    aplicacion = crear_aplicacion()
    async with aplicacion.router.lifespan_context(aplicacion):
        alcance: dict[str, Any] = {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/v1/estado/moderacion/stream",
            "raw_path": b"/api/v1/estado/moderacion/stream",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "server": ("pruebas", 80),
            "app": aplicacion,
        }
        solicitud = Request(alcance)
        respuesta_moderacion = await transmitir_estado_moderacion(solicitud)
        respuesta_recinto = await transmitir_estado_recinto(solicitud)
        assert respuesta_moderacion.media_type == "text/event-stream"
        assert respuesta_recinto.media_type == "text/event-stream"
        assert respuesta_moderacion.headers["content-type"].startswith("text/event-stream")
        assert respuesta_recinto.headers["content-type"].startswith("text/event-stream")
        assert respuesta_moderacion.headers["cache-control"] == "no-cache"

        esquema = aplicacion.openapi()
        paths = esquema["paths"]
        canonicos = {
            "/api/v1/estado/moderacion",
            "/api/v1/estado/recinto",
            "/api/v1/estado/moderacion/stream",
            "/api/v1/estado/recinto/stream",
        }
        assert canonicos <= paths.keys()
        assert not any(
            alias in path for path in paths for alias in ("/proyecciones", "/eventos", "/ws")
        )
        for path in canonicos & {
            "/api/v1/estado/moderacion/stream",
            "/api/v1/estado/recinto/stream",
        }:
            contenido = paths[path]["get"]["responses"]["200"]["content"]
            assert "text/event-stream" in contenido
