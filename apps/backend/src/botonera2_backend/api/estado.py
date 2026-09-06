"""Snapshots REST y streams SSE completos de Moderación, Recinto y Apoyo Técnico."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from botonera2_backend.recursos import obtener_recursos_aplicacion
from botonera2_backend.servicios.proyecciones import (
    EstadoModeracion,
    EstadoRecinto,
    EstadoTecnico,
)
from botonera2_backend.servicios.publicacion import CoordinadorPublicacion

enrutador_estado = APIRouter(prefix="/estado", tags=["estado"])

DESCRIPCION_SSE_MODERACION = (
    "Stream Server-Sent Events. Cada evento `estado` contiene un EstadoModeracion "
    "completo; `id` coincide con su revision. No transporta deltas ni ofrece replay durable."
)
DESCRIPCION_SSE_RECINTO = (
    "Stream Server-Sent Events. Cada evento `estado` contiene un EstadoRecinto completo "
    "con el secreto público aplicado en servidor; `id` coincide con su revision."
)
DESCRIPCION_SSE_TECNICO = (
    "Stream Server-Sent Events. Cada evento `estado` contiene un EstadoTecnico completo "
    "con transmisión, avisos de ambos destinos, biblioteca, eventos seguros, la allowlist "
    "de remapeo y la subproyección de sonorización; `id` coincide con su revision. Es el "
    "único stream persistente que necesita el puesto de Apoyo Técnico."
)


def _documentacion_stream(descripcion: str) -> dict[int | str, dict[str, object]]:
    """Declara ``text/event-stream`` de forma inequívoca en OpenAPI."""

    return {
        200: {
            "description": descripcion,
            "content": {
                "text/event-stream": {
                    "schema": {
                        "type": "string",
                        "description": descripcion,
                    }
                }
            },
        }
    }


@enrutador_estado.get(
    "/moderacion",
    response_model=EstadoModeracion,
    summary="Obtener snapshot completo de Moderación",
)
async def obtener_estado_moderacion(solicitud: Request) -> EstadoModeracion:
    """Responde en cualquiera de los tres estados globales sin mutar dominio."""

    recursos = obtener_recursos_aplicacion(solicitud.app)
    return await recursos.servicio_proyecciones.obtener_estado_moderacion()


@enrutador_estado.get(
    "/recinto",
    response_model=EstadoRecinto,
    summary="Obtener snapshot público completo del Recinto",
)
async def obtener_estado_recinto(solicitud: Request) -> EstadoRecinto:
    """Responde el DTO restrictivo que nunca incluye votos durante EN_CURSO."""

    recursos = obtener_recursos_aplicacion(solicitud.app)
    return await recursos.servicio_proyecciones.obtener_estado_recinto()


@enrutador_estado.get(
    "/tecnico",
    response_model=EstadoTecnico,
    summary="Obtener snapshot completo del puesto de Apoyo Técnico",
)
async def obtener_estado_tecnico(solicitud: Request) -> EstadoTecnico:
    """Responde en cualquiera de los tres estados globales sin mutar dominio."""

    recursos = obtener_recursos_aplicacion(solicitud.app)
    return await recursos.servicio_proyecciones.obtener_estado_tecnico()


@enrutador_estado.get(
    "/moderacion/stream",
    response_class=StreamingResponse,
    responses=_documentacion_stream(DESCRIPCION_SSE_MODERACION),
    summary="Seguir estados completos de Moderación por SSE",
)
async def transmitir_estado_moderacion(solicitud: Request) -> StreamingResponse:
    """Envía un primer snapshot inmediato y luego revisiones completas."""

    recursos = obtener_recursos_aplicacion(solicitud.app)
    flujo = generar_stream_estado(
        recursos.servicio_proyecciones.obtener_estado_moderacion,
        recursos.coordinador_publicacion,
    )
    return _respuesta_sse(flujo)


@enrutador_estado.get(
    "/recinto/stream",
    response_class=StreamingResponse,
    responses=_documentacion_stream(DESCRIPCION_SSE_RECINTO),
    summary="Seguir estados públicos completos del Recinto por SSE",
)
async def transmitir_estado_recinto(solicitud: Request) -> StreamingResponse:
    """Usa exactamente el mismo constructor público restrictivo que REST."""

    recursos = obtener_recursos_aplicacion(solicitud.app)
    flujo = generar_stream_estado(
        recursos.servicio_proyecciones.obtener_estado_recinto,
        recursos.coordinador_publicacion,
    )
    return _respuesta_sse(flujo)


@enrutador_estado.get(
    "/tecnico/stream",
    response_class=StreamingResponse,
    responses=_documentacion_stream(DESCRIPCION_SSE_TECNICO),
    summary="Seguir estados completos de Apoyo Técnico por SSE",
)
async def transmitir_estado_tecnico(solicitud: Request) -> StreamingResponse:
    """Comparte coordinador y revisiones con los otros dos streams.

    Que las tres proyecciones usen el mismo ``CoordinadorPublicacion`` es lo
    que garantiza que una cuenta regresiva que vence, o un aviso que expira,
    despierte a la vez a Moderación, al Recinto y al puesto técnico sin que
    ninguno pregunte periódicamente.

    Desde WP-074 éste es además el **único** stream que abre la SPA técnica.
    Antes abría también los de Moderación y Recinto, y con las cuatro
    superficies de SISLeg abiertas bajo el mismo origen HTTP/1.1 las seis
    conexiones persistentes resultantes dejaban sin cupo a los comandos REST.
    """

    recursos = obtener_recursos_aplicacion(solicitud.app)
    flujo = generar_stream_estado(
        recursos.servicio_proyecciones.obtener_estado_tecnico,
        recursos.coordinador_publicacion,
    )
    return _respuesta_sse(flujo)


def _respuesta_sse(flujo: AsyncGenerator[str]) -> StreamingResponse:
    """Configura headers que evitan cache/buffering del stream de estado."""

    return StreamingResponse(
        flujo,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def generar_stream_estado(
    obtener_estado: Callable[[], Awaitable[EstadoModeracion | EstadoRecinto | EstadoTecnico]],
    coordinador: CoordinadorPublicacion,
) -> AsyncGenerator[str]:
    """Produce estados completos con backpressure coalescente y cleanup.

    La suscripción se crea *antes* del primer snapshot. Si una mutación ocurre
    entre ambos pasos, o bien el snapshot ya la ve bajo el lock, o bien el
    ``Event`` queda encendido y provoca inmediatamente la siguiente lectura.
    Así no existe una ventana snapshot->stream que dependa de un evento perdido.
    """

    suscripcion = coordinador.suscribir()
    revision_enviada = -1
    try:
        while True:
            estado = await obtener_estado()
            if estado.revision > revision_enviada:
                revision_enviada = estado.revision
                yield codificar_evento_sse(estado)
            await suscripcion.esperar_revision_superior(revision_enviada)
    finally:
        # Starlette cancela el iterador cuando se desconecta el cliente. Este
        # ``finally`` elimina la única referencia/evento de esa conexión sin
        # tocar estado funcional, auditoría ni otros consumidores.
        suscripcion.cancelar()


def codificar_evento_sse(estado: EstadoModeracion | EstadoRecinto | EstadoTecnico) -> str:
    """Serializa un DTO Pydantic completo como un evento SSE estable."""

    return f"id: {estado.revision}\nevent: estado\ndata: {estado.model_dump_json()}\n\n"
