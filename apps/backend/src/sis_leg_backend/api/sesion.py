"""Contratos REST del recurso ``/api/v1/sesion`` (WP-008).

Pydantic valida únicamente el transporte. El servicio conserva las reglas de
estado, auditoría y transición para que OpenAPI no se transforme en una segunda
fuente de verdad del dominio.
"""

from __future__ import annotations

from typing import Annotated, Any, Self

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.json_schema import SkipJsonSchema

from sis_leg_backend.api.errores import ErrorRespuesta
from sis_leg_backend.dominio.sesion import ActualizacionDatosInstitucionales
from sis_leg_backend.recursos import obtener_recursos_aplicacion
from sis_leg_backend.servicios.sesion import ServicioSesion

enrutador_sesion = APIRouter(tags=["sesion"])

# ``None`` representa omisión dentro del modelo y ``model_fields_set``
# distingue si el cliente envió explícitamente el campo. ``SkipJsonSchema``
# evita publicar ``null`` como valor válido en OpenAPI: el validador lo rechaza
# cuando fue suministrado. Esta anotación se verificó en la documentación
# oficial de Pydantic 2.13 conforme a DEC-003.
type NumeroSesionOmitible = Annotated[int, Field(strict=True, ge=1)] | SkipJsonSchema[None]
type TextoOmitible = Annotated[str, Field(strict=True)] | SkipJsonSchema[None]


class SolicitudActualizarPreparacion(BaseModel):
    """Body parcial para número y autoridades durante ``PREPARANDO``.

    Cada propiedad puede omitirse, pero el body debe contener al menos una.
    Los textos vacíos son válidos aquí porque significan limpiar la autoridad.
    El entero estricto evita la coerción de booleanos, floats y strings.
    """

    model_config = ConfigDict(extra="forbid")

    numero_sesion: NumeroSesionOmitible = None
    presidencia: TextoOmitible = None
    secretaria_legislativa: TextoOmitible = None

    @model_validator(mode="after")
    def validar_al_menos_un_campo(self) -> Self:
        """Rechaza ``{}`` antes de invocar cualquier servicio de dominio."""

        campos = self.model_fields_set
        if not campos:
            raise ValueError("debe incluirse al menos un campo")
        if "numero_sesion" in campos and self.numero_sesion is None:
            raise ValueError("numero_sesion no admite null")
        if "presidencia" in campos and self.presidencia is None:
            raise ValueError("presidencia no admite null")
        if "secretaria_legislativa" in campos and self.secretaria_legislativa is None:
            raise ValueError("secretaria_legislativa no admite null")
        return self

    def convertir(self) -> ActualizacionDatosInstitucionales:
        """Convierte los campos presentes en banderas explícitas del dominio."""

        campos = self.model_fields_set
        return ActualizacionDatosInstitucionales(
            incluye_numero_sesion="numero_sesion" in campos,
            numero_sesion=self.numero_sesion,
            incluye_presidencia="presidencia" in campos,
            presidencia=self.presidencia,
            incluye_secretaria_legislativa="secretaria_legislativa" in campos,
            secretaria_legislativa=self.secretaria_legislativa,
        )


class SolicitudActualizarSesion(BaseModel):
    """Body parcial para autoridades de una sesión abierta.

    El modelo no declara ``numero_sesion`` y prohíbe extras, de modo que todo
    intento de editarlo produce 422. Una autoridad suministrada se normaliza en
    el servicio, pero debe contener algo distinto de espacios.
    """

    model_config = ConfigDict(extra="forbid")

    presidencia: TextoOmitible = None
    secretaria_legislativa: TextoOmitible = None

    @model_validator(mode="after")
    def validar_autoridades(self) -> Self:
        """Exige al menos una autoridad y prohíbe limpiarla durante sesión."""

        campos = self.model_fields_set
        if not campos:
            raise ValueError("debe incluirse al menos una autoridad")
        if "presidencia" in campos and (self.presidencia is None or not self.presidencia.strip()):
            raise ValueError("Presidencia debe permanecer informada")
        if "secretaria_legislativa" in campos and (
            self.secretaria_legislativa is None or not self.secretaria_legislativa.strip()
        ):
            raise ValueError("Secretaría Legislativa debe permanecer informada")
        return self

    def convertir(self) -> ActualizacionDatosInstitucionales:
        """Convierte los campos presentes al DTO interno compartido."""

        campos = self.model_fields_set
        return ActualizacionDatosInstitucionales(
            incluye_presidencia="presidencia" in campos,
            presidencia=self.presidencia,
            incluye_secretaria_legislativa="secretaria_legislativa" in campos,
            secretaria_legislativa=self.secretaria_legislativa,
        )


RESPUESTAS_ERROR_SESION: dict[int | str, dict[str, Any]] = {
    409: {
        "model": ErrorRespuesta,
        "description": "Rechazo funcional con código estable según la precondición.",
    },
    503: {
        "model": ErrorRespuesta,
        "description": "No puede garantizarse la auditoría obligatoria.",
    },
    500: {
        "model": ErrorRespuesta,
        "description": "Fallo inesperado no clasificado (ERROR_INTERNO).",
    },
    422: {
        "description": "La solicitud no cumple el contrato de transporte.",
    },
}

RESPUESTAS_ERROR_PATCH_SESION: dict[int | str, dict[str, Any]] = {
    **RESPUESTAS_ERROR_SESION,
}


def _crear_servicio(solicitud: Request) -> ServicioSesion:
    """Construye el servicio sobre estado y serializador únicos del lifespan."""

    recursos = obtener_recursos_aplicacion(solicitud.app)
    return ServicioSesion(
        estado_operativo=recursos.estado_operativo,
        ejecutor_mutaciones=recursos.ejecutor_mutaciones,
    )


@enrutador_sesion.post(
    "/sesion",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=RESPUESTAS_ERROR_SESION,
    summary="Abrir la sesión preparada",
)
async def abrir_sesion(solicitud: Request) -> Response:
    """Abre sin body y solo después de auditar todas sus precondiciones."""

    await _crear_servicio(solicitud).abrir_sesion()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@enrutador_sesion.patch(
    "/sesion",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=RESPUESTAS_ERROR_PATCH_SESION,
    summary="Actualizar autoridades de la sesión",
)
async def actualizar_sesion(
    solicitud: Request,
    actualizacion: SolicitudActualizarSesion,
) -> Response:
    """Cambia una o ambas autoridades; el número no integra este modelo."""

    await _crear_servicio(solicitud).actualizar_autoridades(actualizacion.convertir())
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@enrutador_sesion.delete(
    "/sesion",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=RESPUESTAS_ERROR_SESION,
    summary="Cerrar normalmente la sesión",
)
async def cerrar_sesion(solicitud: Request) -> Response:
    """Cierra sin body y resuelve antes una EN_CURSO o EMPATADA pendiente."""

    await _crear_servicio(solicitud).cerrar_sesion()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
