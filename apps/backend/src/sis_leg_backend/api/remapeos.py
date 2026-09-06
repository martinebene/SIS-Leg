"""Contratos REST públicos e interno del remapeo coordinado WP-020."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from sis_leg_backend.api.errores import ErrorRespuesta
from sis_leg_backend.dominio.remapeo import OperacionRemapeo, PersistenciaRemapeo
from sis_leg_backend.recursos import obtener_recursos_aplicacion
from sis_leg_backend.servicios.remapeo import ServicioRemapeo

enrutador_remapeos = APIRouter(tags=["remapeos"])


class SolicitudIniciarRemapeo(BaseModel):
    """Body cerrado para seleccionar un devXX existente del padrón activo."""

    model_config = ConfigDict(extra="forbid")
    dispositivo: Annotated[str, Field(strict=True, pattern=r"^dev\d{2}$")]


class SolicitudConfirmarRemapeo(BaseModel):
    """Decisión humana cerrada; no admite coerciones ni otros modos."""

    model_config = ConfigDict(extra="forbid")
    persistencia: Literal["TEMPORAL", "PERSISTENTE"]


class SolicitudCandidatoRemapeo(BaseModel):
    """Callback interno del bridge; nunca se expone en ClienteModeracion."""

    model_config = ConfigDict(extra="forbid")
    fingerprint: Annotated[str, Field(strict=True, min_length=1, max_length=2000)]
    diagnostico: Annotated[str | None, Field(strict=True, max_length=500)] = None

    @field_validator("fingerprint")
    @classmethod
    def validar_fingerprint_no_vacio(cls, valor: str) -> str:
        """Rechaza espacios sin reinterpretar ni normalizar la identidad física."""

        if not valor.strip():
            raise ValueError("fingerprint no puede estar vacío")
        return valor

    @field_validator("diagnostico")
    @classmethod
    def normalizar_diagnostico(cls, valor: str | None) -> str | None:
        """Convierte el texto diagnóstico vacío en ausencia explícita."""

        if valor is None:
            return None
        limpio = valor.strip()
        return limpio or None


class EstadoRemapeoRespuesta(BaseModel):
    """Estado físico seguro que la futura UI obtiene por snapshot/SSE."""

    remapeo_id: str
    dispositivo: str
    estado: str
    fingerprint_anterior: str | None
    candidato: str | None
    diagnostico: str | None


RESPUESTAS_REMAPEO: dict[int | str, dict[str, Any]] = {
    409: {
        "model": ErrorRespuesta,
        "description": (
            "Conflicto funcional: ESTADO_INCOMPATIBLE, DISPOSITIVO_REMAPEO_NO_EXISTENTE, "
            "REMAPEO_YA_ACTIVO, REMAPEO_NO_COINCIDE, REMAPEO_SIN_CANDIDATO, "
            "CANDIDATO_YA_REGISTRADO o PARAMETROS_REMAPEO_INCOMPATIBLES."
        ),
    },
    503: {
        "model": ErrorRespuesta,
        "description": (
            "Indisponibilidad: BRIDGE_NO_DISPONIBLE, APLICACION_BRIDGE_RECHAZADA "
            "o AUDITORIA_NO_DISPONIBLE."
        ),
    },
    500: {"model": ErrorRespuesta, "description": "Fallo inesperado (ERROR_INTERNO)."},
}


def _crear_servicio(solicitud: Request) -> ServicioRemapeo:
    """Usa el estado, ejecutor y cliente bridge únicos del lifespan."""

    recursos = obtener_recursos_aplicacion(solicitud.app)
    return ServicioRemapeo(
        recursos.estado_operativo,
        recursos.ejecutor_mutaciones,
        recursos.cliente_control_bridge,
    )


def _respuesta(operacion: OperacionRemapeo) -> EstadoRemapeoRespuesta:
    """Copia solamente los datos seguros del registro mutable interno."""

    return EstadoRemapeoRespuesta(
        remapeo_id=operacion.remapeo_id,
        dispositivo=operacion.dispositivo,
        estado=operacion.estado.value,
        fingerprint_anterior=operacion.fingerprint_anterior,
        candidato=operacion.candidato,
        diagnostico=operacion.diagnostico,
    )


@enrutador_remapeos.post(
    "/remapeos",
    status_code=status.HTTP_201_CREATED,
    response_model=EstadoRemapeoRespuesta,
    responses=RESPUESTAS_REMAPEO,
    summary="Iniciar captura física para un dispositivo lógico existente",
)
async def iniciar_remapeo(
    solicitud: Request,
    cuerpo: SolicitudIniciarRemapeo,
) -> EstadoRemapeoRespuesta:
    """Valida estado/padrón, genera UUID y ordena captura al bridge."""

    return _respuesta(await _crear_servicio(solicitud).iniciar(cuerpo.dispositivo))


@enrutador_remapeos.post(
    "/interno/remapeos/{remapeo_id}/candidato",
    response_model=EstadoRemapeoRespuesta,
    responses=RESPUESTAS_REMAPEO,
    summary="Informar candidato físico desde el device-bridge (interno)",
)
async def informar_candidato(
    solicitud: Request,
    remapeo_id: str,
    cuerpo: SolicitudCandidatoRemapeo,
) -> EstadoRemapeoRespuesta:
    """Congela el primer candidato sin aplicar el mapping."""

    operacion = await _crear_servicio(solicitud).registrar_candidato(
        remapeo_id,
        cuerpo.fingerprint,
        cuerpo.diagnostico,
    )
    return _respuesta(operacion)


@enrutador_remapeos.post(
    "/remapeos/{remapeo_id}/confirmacion",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=RESPUESTAS_REMAPEO,
    summary="Autorizar y aplicar el candidato temporal o persistentemente",
)
async def confirmar_remapeo(
    solicitud: Request,
    remapeo_id: str,
    cuerpo: SolicitudConfirmarRemapeo,
) -> Response:
    """Persiste L3 de autorización antes de ordenar el apply físico."""

    await _crear_servicio(solicitud).confirmar(
        remapeo_id,
        PersistenciaRemapeo(cuerpo.persistencia),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@enrutador_remapeos.delete(
    "/remapeos/{remapeo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=RESPUESTAS_REMAPEO,
    summary="Cancelar la captura sin modificar el mapping",
)
async def cancelar_remapeo(solicitud: Request, remapeo_id: str) -> Response:
    """Cancela idempotentemente el mismo ID en backend y bridge."""

    await _crear_servicio(solicitud).cancelar(remapeo_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
