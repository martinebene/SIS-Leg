"""Contrato REST de entrada lógica ``/api/v1/entradas/tecla``.

Esta capa valida únicamente el transporte con Pydantic y traduce los tipos
internos del servicio a los modelos que FastAPI publica en OpenAPI. Las reglas
de estado, resolución del padrón, auditoría y mutación permanecen en
``ServicioEntradaTecla`` para que la API no se convierta en otra autoridad de
negocio.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from sis_leg_backend.api.errores import ErrorRespuesta
from sis_leg_backend.dominio.entrada import (
    AccionPalabra,
    IdentidadConcejal,
    Pulsacion,
    RespuestaEntrada,
    ResultadoPalabra,
    ResultadoPresencia,
    ResultadoTest,
    ResultadoVoto,
)
from sis_leg_backend.dominio.votacion import EstadoVotacion, ValorVotoOrdinario
from sis_leg_backend.recursos import obtener_recursos_aplicacion
from sis_leg_backend.servicios.entrada import ServicioEntradaTecla

enrutador_entradas = APIRouter(tags=["entradas"])


class SolicitudTecla(BaseModel):
    """Body exacto de la pulsación lógica que recibe el backend.

    ``extra='forbid'`` hace que DNI, banca, fingerprint u otros datos que no
    pertenecen al contrato produzcan ``422`` en vez de ser ignorados. El bridge
    ya debe haber resuelto lo físico a un dispositivo lógico antes de llamar a
    esta ruta.
    """

    model_config = ConfigDict(extra="forbid")

    dispositivo: Annotated[str, Field(min_length=1, strict=True)]
    tecla: Annotated[str, Field(min_length=1, strict=True)]

    @field_validator("dispositivo", "tecla")
    @classmethod
    def validar_texto_no_vacio(cls, valor: str) -> str:
        """Rechaza también textos compuestos solo por espacios."""

        if not valor.strip():
            raise ValueError("el texto no puede estar vacío")
        return valor


class IdentidadConcejalRespuesta(BaseModel):
    """Identidad pública mínima de un concejal asociado al dispositivo."""

    dni: str
    nombre: str
    apellido: str
    banca: int


class ResultadoPresenciaRespuesta(BaseModel):
    """Resultado tipado de una tecla ``9`` aceptada."""

    tipo: Literal["PRESENCIA"]
    presente: bool
    presentes: int
    quorum_alcanzado: bool


class ResultadoTestRespuesta(BaseModel):
    """Resultado tipado de una tecla ``8`` aceptada."""

    tipo: Literal["TEST"]
    activo: bool
    duracion_segundos: int | float


class ResultadoVotoRespuesta(BaseModel):
    """Resultado tipado de una tecla ``1``, ``2`` o ``3`` aceptada."""

    tipo: Literal["VOTO"]
    valor: ValorVotoOrdinario
    estado_recepcion: EstadoVotacion


class ResultadoPalabraRespuesta(BaseModel):
    """Resultado tipado de una tecla ``7`` aceptada."""

    tipo: Literal["PALABRA"]
    accion: AccionPalabra


class RespuestaTecla(BaseModel):
    """Forma estable de éxito o rechazo funcional normal de una pulsación."""

    aceptada: bool
    dispositivo: str
    tecla: str
    motivo: str
    concejal: IdentidadConcejalRespuesta | None
    resultado: (
        ResultadoPresenciaRespuesta
        | ResultadoTestRespuesta
        | ResultadoVotoRespuesta
        | ResultadoPalabraRespuesta
        | None
    )


RESPUESTAS_ERROR_ENTRADA: dict[int | str, dict[str, Any]] = {
    422: {
        "description": "El body no cumple el esquema de transporte de la pulsación.",
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


def _crear_servicio(solicitud: Request) -> ServicioEntradaTecla:
    """Construye el servicio con el estado y el serializador del lifespan."""

    recursos = obtener_recursos_aplicacion(solicitud.app)
    return ServicioEntradaTecla(
        estado_operativo=recursos.estado_operativo,
        ejecutor_mutaciones=recursos.ejecutor_mutaciones,
    )


def _convertir_identidad(
    identidad: IdentidadConcejal | None,
) -> IdentidadConcejalRespuesta | None:
    """Convierte la identidad interna al subconjunto permitido por la API."""

    if identidad is None:
        return None
    return IdentidadConcejalRespuesta(
        dni=identidad.dni,
        nombre=identidad.nombre,
        apellido=identidad.apellido,
        banca=identidad.banca,
    )


def _convertir_respuesta(respuesta: RespuestaEntrada) -> RespuestaTecla:
    """Adapta la unión de resultados del dominio a los modelos OpenAPI."""

    resultado: (
        ResultadoPresenciaRespuesta
        | ResultadoTestRespuesta
        | ResultadoVotoRespuesta
        | ResultadoPalabraRespuesta
        | None
    )
    if isinstance(respuesta.resultado, ResultadoPresencia):
        resultado = ResultadoPresenciaRespuesta(
            tipo="PRESENCIA",
            presente=respuesta.resultado.presente,
            presentes=respuesta.resultado.presentes,
            quorum_alcanzado=respuesta.resultado.quorum_alcanzado,
        )
    elif isinstance(respuesta.resultado, ResultadoTest):
        resultado = ResultadoTestRespuesta(
            tipo="TEST",
            activo=respuesta.resultado.activo,
            duracion_segundos=respuesta.resultado.duracion_segundos,
        )
    elif isinstance(respuesta.resultado, ResultadoVoto):
        resultado = ResultadoVotoRespuesta(
            tipo="VOTO",
            valor=respuesta.resultado.valor,
            estado_recepcion=respuesta.resultado.estado_recepcion,
        )
    elif isinstance(respuesta.resultado, ResultadoPalabra):
        resultado = ResultadoPalabraRespuesta(
            tipo="PALABRA",
            accion=respuesta.resultado.accion,
        )
    else:
        resultado = None

    return RespuestaTecla(
        aceptada=respuesta.aceptada,
        dispositivo=respuesta.dispositivo,
        tecla=respuesta.tecla,
        motivo=respuesta.motivo,
        concejal=_convertir_identidad(respuesta.concejal),
        resultado=resultado,
    )


@enrutador_entradas.post(
    "/entradas/tecla",
    response_model=RespuestaTecla,
    responses=RESPUESTAS_ERROR_ENTRADA,
    summary="Procesar una pulsación lógica de dispositivo",
)
async def procesar_tecla(
    solicitud: Request,
    entrada: SolicitudTecla,
) -> RespuestaTecla:
    """Procesa ``{dispositivo, tecla}`` y devuelve aceptación o rechazo estable.

    FastAPI ejecuta la validación de ``SolicitudTecla`` antes de entrar aquí, de
    modo que un body inválido responde ``422`` sin tocar el estado ni la
    auditoría. Para un body válido, el servicio reutiliza el serializador único;
    si el writer falla, la excepción se transforma en ``503`` por el manejador
    compartido de auditoría.
    """

    respuesta = await _crear_servicio(solicitud).procesar_pulsacion(
        Pulsacion(dispositivo=entrada.dispositivo, tecla=entrada.tecla)
    )
    return _convertir_respuesta(respuesta)
