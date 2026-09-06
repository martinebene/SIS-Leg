"""Recurso REST ``/api/v1/preparacion`` (WP-005 y WP-008).

Expone los comandos del ciclo de preparación definidos por el contrato
(documento 04, sección 6):

- ``POST /api/v1/preparacion``: ``Preparar recinto`` desde ``SIN_PREPARAR``;
- ``PATCH /api/v1/preparacion``: actualizar número y autoridades desde
  ``PREPARANDO``;
- ``DELETE /api/v1/preparacion``: cancelar la preparación desde
  ``PREPARANDO``.

``POST`` y ``DELETE`` se invocan sin body; los tres responden ``204`` sin
cuerpo cuando completan. Ninguno recibe rutas, configuración, padrón ni
motivo desde el cliente: el backend carga siempre sus archivos canónicos.

La traducción de errores no vive aquí: las excepciones de dominio/técnicas se
propagan y los manejadores registrados en ``api/errores.py`` producen las
respuestas estables ``409 ESTADO_INCOMPATIBLE``, ``503
CONFIGURACION_INVALIDA``, ``503 PADRON_INVALIDO``, ``503
AUDITORIA_NO_DISPONIBLE`` y ``500 ERROR_INTERNO``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response, status

from sis_leg_backend.api.errores import ErrorRespuesta
from sis_leg_backend.api.sesion import SolicitudActualizarPreparacion
from sis_leg_backend.recursos import obtener_recursos_aplicacion
from sis_leg_backend.servicios.preparacion import ServicioPreparacion
from sis_leg_backend.servicios.sesion import ServicioSesion

enrutador_preparacion = APIRouter(tags=["preparacion"])

# Documentación OpenAPI de las respuestas de error del contrato. El modelo
# ``ErrorRespuesta`` hace visible la forma estable del cuerpo; el código 500
# lo produce el manejador genérico de ``aplicacion.py``.
RESPUESTAS_ERROR_PREPARACION: dict[int | str, dict[str, Any]] = {
    409: {
        "model": ErrorRespuesta,
        "description": "El comando no es válido para el estado global actual "
        "(ESTADO_INCOMPATIBLE).",
    },
    503: {
        "model": ErrorRespuesta,
        "description": "Indisponibilidad técnica: CONFIGURACION_INVALIDA, "
        "PADRON_INVALIDO o AUDITORIA_NO_DISPONIBLE según el caso.",
    },
    500: {
        "model": ErrorRespuesta,
        "description": "Fallo inesperado no clasificado (ERROR_INTERNO).",
    },
}
RESPUESTAS_ERROR_PATCH_PREPARACION: dict[int | str, dict[str, Any]] = {
    **RESPUESTAS_ERROR_PREPARACION,
    422: {
        "description": "Body vacío/inválido o número que no es entero estricto positivo.",
    },
}


def _crear_servicio(solicitud: Request) -> ServicioPreparacion:
    """Construye el servicio sobre los recursos únicos del proceso.

    El servicio no guarda estado propio, por lo que crearlo por request es
    seguro: siempre opera sobre el ``EstadoOperativo`` y el
    ``EjecutorMutaciones`` que el lifespan instaló en ``app.state``. Las rutas
    de configuración/padrón y el reloj son los canónicos por defecto.
    """

    recursos = obtener_recursos_aplicacion(solicitud.app)
    return ServicioPreparacion(
        estado_operativo=recursos.estado_operativo,
        ejecutor_mutaciones=recursos.ejecutor_mutaciones,
    )


def _crear_servicio_sesion(solicitud: Request) -> ServicioSesion:
    """Construye el servicio institucional sobre los mismos recursos únicos."""

    recursos = obtener_recursos_aplicacion(solicitud.app)
    return ServicioSesion(
        estado_operativo=recursos.estado_operativo,
        ejecutor_mutaciones=recursos.ejecutor_mutaciones,
    )


@enrutador_preparacion.post(
    "/preparacion",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=RESPUESTAS_ERROR_PREPARACION,
)
async def preparar_sala(solicitud: Request) -> Response:
    """Inicia una nueva preparación del recinto (CU-01).

    Carga y congela ``config/system.toml`` y ``config/concejales.csv``, crea
    el conjunto de auditoría L1/L2/L3, persiste ``PREPARACION_INICIADA`` y
    recién entonces deja el sistema en ``PREPARANDO`` con todos los
    concejales ausentes. Si algún paso obligatorio falla, no se confirma
    éxito y el sistema permanece en ``SIN_PREPARAR``.
    """

    await _crear_servicio(solicitud).preparar_sala()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@enrutador_preparacion.patch(
    "/preparacion",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=RESPUESTAS_ERROR_PATCH_PREPARACION,
    summary="Actualizar número y autoridades de la preparación",
)
async def actualizar_preparacion(
    solicitud: Request,
    actualizacion: SolicitudActualizarPreparacion,
) -> Response:
    """Aplica uno o más cambios efectivos con auditoría previa y ordenada."""

    await _crear_servicio_sesion(solicitud).actualizar_preparacion(actualizacion.convertir())
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@enrutador_preparacion.delete(
    "/preparacion",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=RESPUESTAS_ERROR_PREPARACION,
)
async def cancelar_preparacion(solicitud: Request) -> Response:
    """Cancela la preparación activa (CU-02), sin recibir ni exigir motivo.

    Persiste ``PREPARACION_CANCELADA``, cierra definitivamente los tres CSV
    (que se conservan en disco) y devuelve el sistema a ``SIN_PREPARAR`` con
    el contexto operativo completamente descartado. Si la auditoría no puede
    garantizar esos pasos, no se confirma la cancelación y el estado
    permanece en ``PREPARANDO`` en fallo cerrado.
    """

    await _crear_servicio(solicitud).cancelar_preparacion()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
