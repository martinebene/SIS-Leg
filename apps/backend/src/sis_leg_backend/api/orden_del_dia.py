"""Contrato REST para la carga y descarte del Orden del Día (WP-016).

Implementa los endpoints canónicos definidos en DT-039 y WP-016:
- POST /api/v1/orden-del-dia: subida de archivo multipart/form-data en el campo 'archivo'.
  Devuelve 200 OK con los puntos normalizados.
- DELETE /api/v1/orden-del-dia: descarte del Orden del Día activo.
  Devuelve 204 No Content.

Pydantic valida el esquema de respuesta y los tipos de transporte, mientras
que el servicio :class:`ServicioOrdenDelDia` y la función pura
:func:`parsear_orden_del_dia` aplican las reglas de validación técnica,
atomicidad, serialización y auditoría institucional.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, File, Request, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field

from sis_leg_backend.api.errores import ErrorRespuesta
from sis_leg_backend.dominio.orden_del_dia import PuntoOrdenDelDia
from sis_leg_backend.dominio.votacion import BaseMayoria, TipoMayoria
from sis_leg_backend.recursos import obtener_recursos_aplicacion
from sis_leg_backend.servicios.orden_del_dia import ServicioOrdenDelDia

enrutador_orden_del_dia = APIRouter(tags=["orden-del-dia"])


class PuntoOrdenDelDiaRespuesta(BaseModel):
    """Representación normalizada de un punto del Orden del Día en la API.

    Expone los campos exactos de DT-039. Para mayoría SIMPLE, factor se expone
    como 0 y base como VOTOS_COMPUTABLES.
    """

    model_config = ConfigDict(extra="forbid")

    nro_votacion: int = Field(
        ...,
        description="Número externo sugerido para la votación (entero >= 1).",
        ge=1,
    )
    tipo: str = Field(..., description="Tipo descriptivo de votación.")
    tema: str = Field(..., description="Tema o asunto a tratar.")
    tipo_mayoria: TipoMayoria = Field(
        ...,
        description="Regla de mayoría: SIMPLE o ESPECIAL.",
    )
    factor: int | float = Field(
        ...,
        description="Factor numérico normalizado (0 para SIMPLE, > 0 y <= 1 para ESPECIAL).",
    )
    base: BaseMayoria = Field(
        ...,
        description="Denominador institucional normalizado: VOTOS_COMPUTABLES, PRESENTES o CUERPO.",
    )

    @classmethod
    def desde_dominio(cls, punto: PuntoOrdenDelDia) -> PuntoOrdenDelDiaRespuesta:
        """Construye el DTO de respuesta asegurando factor 0 entero para SIMPLE."""
        factor_serializado: int | float = (
            0 if punto.tipo_mayoria is TipoMayoria.SIMPLE else punto.factor
        )
        return cls(
            nro_votacion=punto.nro_votacion,
            tipo=punto.tipo,
            tema=punto.tema,
            tipo_mayoria=punto.tipo_mayoria,
            factor=factor_serializado,
            base=punto.base,
        )


class CargaOrdenDelDiaRespuesta(BaseModel):
    """Respuesta exitosa de carga con la lista de puntos normalizados."""

    model_config = ConfigDict(extra="forbid")

    puntos: list[PuntoOrdenDelDiaRespuesta] = Field(
        ...,
        description="Colección de puntos normalizados del Orden del Día.",
    )


RESPUESTAS_ERROR_CARGA_ORDEN_DEL_DIA: dict[int | str, dict[str, Any]] = {
    409: {
        "model": ErrorRespuesta,
        "description": "Estado incompatible (intento de carga en SIN_PREPARAR).",
    },
    422: {
        "model": ErrorRespuesta,
        "description": "Archivo recibido pero técnicamente inválido (ORDEN_DEL_DIA_INVALIDO).",
    },
    503: {
        "model": ErrorRespuesta,
        "description": "Auditoría obligatoria no disponible (AUDITORIA_NO_DISPONIBLE).",
    },
    500: {
        "model": ErrorRespuesta,
        "description": "Error interno inesperado (ERROR_INTERNO).",
    },
}

RESPUESTAS_ERROR_DESCARTE_ORDEN_DEL_DIA: dict[int | str, dict[str, Any]] = {
    409: {
        "model": ErrorRespuesta,
        "description": "Estado incompatible (intento de descarte en SIN_PREPARAR).",
    },
    503: {
        "model": ErrorRespuesta,
        "description": "Auditoría obligatoria no disponible (AUDITORIA_NO_DISPONIBLE).",
    },
    500: {
        "model": ErrorRespuesta,
        "description": "Error interno inesperado (ERROR_INTERNO).",
    },
}


def _crear_servicio(solicitud: Request) -> ServicioOrdenDelDia:
    """Construye el servicio sobre el estado y serializador únicos del lifespan."""
    recursos = obtener_recursos_aplicacion(solicitud.app)
    return ServicioOrdenDelDia(
        estado_operativo=recursos.estado_operativo,
        ejecutor_mutaciones=recursos.ejecutor_mutaciones,
    )


@enrutador_orden_del_dia.post(
    "/orden-del-dia",
    response_model=CargaOrdenDelDiaRespuesta,
    status_code=status.HTTP_200_OK,
    responses=RESPUESTAS_ERROR_CARGA_ORDEN_DEL_DIA,
    summary="Cargar y normalizar archivo de Orden del Día",
)
async def cargar_orden_del_dia(
    solicitud: Request,
    archivo: Annotated[
        UploadFile,
        File(description="Archivo CSV canónico de seis columnas del Orden del Día."),
    ],
) -> CargaOrdenDelDiaRespuesta:
    """Recibe un archivo CSV, lo valida atómicamente y lo instala en el contexto activo."""
    contenido = await archivo.read()
    puntos_dominio = await _crear_servicio(solicitud).cargar_orden_del_dia(contenido)
    return CargaOrdenDelDiaRespuesta(
        puntos=[PuntoOrdenDelDiaRespuesta.desde_dominio(p) for p in puntos_dominio]
    )


@enrutador_orden_del_dia.delete(
    "/orden-del-dia",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=RESPUESTAS_ERROR_DESCARTE_ORDEN_DEL_DIA,
    summary="Descartar el Orden del Día activo",
)
async def descartar_orden_del_dia(solicitud: Request) -> Response:
    """Descarta la colección activa. Si no existía colección, es un no-op exitoso."""
    await _crear_servicio(solicitud).descartar_orden_del_dia()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
