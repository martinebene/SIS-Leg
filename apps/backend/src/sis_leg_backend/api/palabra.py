"""Contratos REST de Moderación para ``/api/v1/palabra`` (WP-015)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response, status

from sis_leg_backend.api.errores import ErrorRespuesta
from sis_leg_backend.recursos import obtener_recursos_aplicacion
from sis_leg_backend.servicios.palabra import ServicioPalabra

enrutador_palabra = APIRouter(tags=["palabra"])

RESPUESTAS_ERROR_PALABRA: dict[int | str, dict[str, Any]] = {
    409: {
        "model": ErrorRespuesta,
        "description": "No existe una sesión abierta (ESTADO_INCOMPATIBLE).",
    },
    503: {
        "model": ErrorRespuesta,
        "description": "No puede garantizarse la auditoría obligatoria.",
    },
    500: {
        "model": ErrorRespuesta,
        "description": "Fallo inesperado no clasificado (ERROR_INTERNO).",
    },
}


def _crear_servicio(solicitud: Request) -> ServicioPalabra:
    """Construye el servicio con los recursos únicos creados por el lifespan."""

    recursos = obtener_recursos_aplicacion(solicitud.app)
    return ServicioPalabra(
        estado_operativo=recursos.estado_operativo,
        ejecutor_mutaciones=recursos.ejecutor_mutaciones,
    )


@enrutador_palabra.post(
    "/palabra",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=RESPUESTAS_ERROR_PALABRA,
    summary="Otorgar palabra al primer pedido FIFO",
)
async def otorgar_palabra(solicitud: Request) -> Response:
    """Finaliza al orador actual y otorga el primer pedido, sin body."""

    await _crear_servicio(solicitud).otorgar_palabra()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@enrutador_palabra.delete(
    "/palabra",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=RESPUESTAS_ERROR_PALABRA,
    summary="Finalizar el uso actual sin avanzar la cola",
)
async def quitar_palabra(solicitud: Request) -> Response:
    """Finaliza al orador si existe y conserva toda la cola pendiente."""

    await _crear_servicio(solicitud).quitar_palabra()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
