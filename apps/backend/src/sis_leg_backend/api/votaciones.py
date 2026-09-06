"""Contratos REST para abrir, finalizar y desempatar votaciones.

Pydantic valida el transporte y las combinaciones SIMPLE/ESPECIAL antes de
entrar al servicio. Las precondiciones que dependen del estado, el snapshot y
la auditoría permanecen en ``ServicioVotacion`` bajo el serializador común.
"""

from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Annotated, Any, Literal, Self

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sis_leg_backend.api.errores import ErrorRespuesta
from sis_leg_backend.dominio.votacion import (
    BaseMayoria,
    DatosAperturaVotacion,
    EstadoVotacion,
    SentidoVotoDesempate,
    TipoMayoria,
)
from sis_leg_backend.recursos import obtener_recursos_aplicacion
from sis_leg_backend.servicios.votacion import ServicioVotacion

enrutador_votaciones = APIRouter(tags=["votaciones"])

# ``strict=True`` impide aceptar strings o booleanos. Pydantic conserva la
# conversión válida de un entero JSON a ``float`` (por ejemplo factor=1), y
# ``allow_inf_nan=False`` expresa que una mayoría especial exige un real finito.
type NumeroVotacion = Annotated[int, Field(strict=True, ge=1)]
type FactorNumerico = Annotated[float, Field(strict=True, allow_inf_nan=False)]
type FactorEspecial = Annotated[
    float,
    Field(strict=True, gt=0, le=1, allow_inf_nan=False),
]


def _sanear_numero_no_finito(valor: object) -> object:
    """Convierte NaN/inf en un valor inválido que FastAPI pueda serializar.

    Pydantic rechaza por sí mismo los no finitos, pero FastAPI 0.141.1 incluye
    el valor original en el detalle de validación y luego no puede serializarlo
    como JSON. Transformarlo a un texto deliberadamente inválido conserva el
    422 genérico previo al servicio y evita que ese detalle produzca un 500.
    """

    if isinstance(valor, float) and not isfinite(valor):
        return "número no finito"
    return valor


class _SolicitudBaseVotacion(BaseModel):
    """Campos comunes y normalización textual de toda apertura.

    Los campos extra se prohíben para que una falta de ortografía no parezca
    aceptada. ``strip`` solo retira espacios exteriores; no modifica contenido
    ni mayúsculas/minúsculas del tipo configurado.
    """

    model_config = ConfigDict(extra="forbid")

    numero_votacion: NumeroVotacion
    tipo: Annotated[str, Field(strict=True)]
    tema: Annotated[str, Field(strict=True)]

    @field_validator("tipo", "tema")
    @classmethod
    def normalizar_texto_obligatorio(cls, valor: str) -> str:
        """Retira espacios exteriores y rechaza textos vacíos o blancos."""

        normalizado = valor.strip()
        if not normalizado:
            raise ValueError("el texto no puede quedar vacío")
        return normalizado


class SolicitudVotacionSimple(_SolicitudBaseVotacion):
    """Variante SIMPLE con factor/base opcionales y salida normalizada.

    Un factor omitido, nulo o numéricamente cero es equivalente. Toda base
    distinta de ``VOTOS_COMPUTABLES`` queda fuera del propio esquema de esta
    variante y por eso FastAPI responde 422 antes de invocar el servicio.
    """

    tipo_mayoria: Literal[TipoMayoria.SIMPLE]
    factor: FactorNumerico | None = None
    base: Literal[BaseMayoria.VOTOS_COMPUTABLES] = BaseMayoria.VOTOS_COMPUTABLES

    @model_validator(mode="after")
    def validar_factor_simple(self) -> Self:
        """Admite solamente ausencia, nulo o cero para la mayoría simple."""

        if self.factor is not None and self.factor != 0:
            raise ValueError("SIMPLE solo admite factor omitido, null o cero")
        return self

    @field_validator("factor", mode="before")
    @classmethod
    def sanear_numero_no_finito(cls, valor: object) -> object:
        """Evita que un número no finito contamine el detalle JSON del 422."""

        return _sanear_numero_no_finito(valor)

    def convertir(self) -> DatosAperturaVotacion:
        """Produce el DTO interno con factor y base canónicos explícitos."""

        return DatosAperturaVotacion(
            numero_votacion=self.numero_votacion,
            tipo=self.tipo,
            tema=self.tema,
            tipo_mayoria=TipoMayoria.SIMPLE,
            factor=0.0,
            base=BaseMayoria.VOTOS_COMPUTABLES,
        )


class SolicitudVotacionEspecial(_SolicitudBaseVotacion):
    """Variante ESPECIAL con factor finito y una base canónica obligatoria."""

    tipo_mayoria: Literal[TipoMayoria.ESPECIAL]
    factor: FactorEspecial
    base: BaseMayoria

    @field_validator("factor", mode="before")
    @classmethod
    def sanear_numero_no_finito(cls, valor: object) -> object:
        """Evita que un número no finito contamine el detalle JSON del 422."""

        return _sanear_numero_no_finito(valor)

    def convertir(self) -> DatosAperturaVotacion:
        """Copia la variante ya validada al DTO independiente de FastAPI."""

        return DatosAperturaVotacion(
            numero_votacion=self.numero_votacion,
            tipo=self.tipo,
            tema=self.tema,
            tipo_mayoria=TipoMayoria.ESPECIAL,
            factor=self.factor,
            base=self.base,
        )


# La unión etiquetada genera ``oneOf`` y ``discriminator`` en JSON Schema. El
# valor explícito de ``tipo_mayoria`` selecciona una sola variante y evita
# inferir la regla a partir del factor, tal como exige DEC-009.
type SolicitudAbrirVotacion = Annotated[
    SolicitudVotacionSimple | SolicitudVotacionEspecial,
    Field(discriminator="tipo_mayoria"),
]


class RespuestaVotacion(BaseModel):
    """Representación HTTP mínima y normalizada de la votación creada."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    numero_votacion: int
    tipo: str
    tema: str
    tipo_mayoria: TipoMayoria
    factor: float
    base: BaseMayoria
    estado: EstadoVotacion
    fecha_hora_apertura: datetime


class SolicitudFinalizarVotacion(BaseModel):
    """Body exacto de la finalización manual anticipada de DEC-011.

    ``strict=True`` evita convertir booleanos, números u otras estructuras en
    texto. El validador normaliza antes de llegar al dominio y rechaza tanto la
    cadena vacía como la compuesta únicamente por espacios.
    """

    model_config = ConfigDict(extra="forbid")

    motivo: Annotated[str, Field(strict=True)]

    @field_validator("motivo")
    @classmethod
    def normalizar_motivo(cls, valor: str) -> str:
        """Retira espacios exteriores y exige contenido humano obligatorio."""

        normalizado = valor.strip()
        if not normalizado:
            raise ValueError("el motivo no puede quedar vacío")
        return normalizado


class SolicitudDesempate(BaseModel):
    """Body cerrado del único comando presidencial definido por DEC-012.

    El cliente solo elige el sentido. La identidad de Presidencia se obtiene
    de la sesión activa dentro del serializador y no puede inyectarse mediante
    campos adicionales.
    """

    model_config = ConfigDict(extra="forbid")

    sentido: Literal["POSITIVO", "NEGATIVO"]

    def convertir_sentido(self) -> SentidoVotoDesempate:
        """Convierte el literal HTTP al vocabulario cerrado del dominio."""

        return SentidoVotoDesempate(self.sentido)


RESPUESTAS_ERROR_VOTACION: dict[int | str, dict[str, Any]] = {
    409: {
        "model": ErrorRespuesta,
        "description": "Estado, quórum o votación pendiente impiden la apertura.",
    },
    422: {
        "description": (
            "Body inválido o tipo descriptivo no permitido por la configuración congelada."
        ),
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

RESPUESTAS_ERROR_FINALIZACION: dict[int | str, dict[str, Any]] = {
    409: {
        "model": ErrorRespuesta,
        "description": (
            "Rechazo funcional: ESTADO_INCOMPATIBLE, VOTACION_NO_COINCIDE o VOTACION_NO_EN_CURSO."
        ),
    },
    422: {
        "description": "El path o body no cumple el contrato estricto de transporte.",
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

RESPUESTAS_ERROR_DESEMPATE: dict[int | str, dict[str, Any]] = {
    409: {
        "model": ErrorRespuesta,
        "description": (
            "Rechazo funcional: ESTADO_INCOMPATIBLE, VOTACION_NO_COINCIDE, "
            "VOTACION_NO_EMPATADA o DESEMPATE_YA_EMITIDO."
        ),
    },
    422: {
        "description": "El path o body no cumple el contrato estricto de transporte.",
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


def _crear_servicio(solicitud: Request) -> ServicioVotacion:
    """Construye el servicio con el estado y serializador únicos del lifespan."""

    recursos = obtener_recursos_aplicacion(solicitud.app)
    return ServicioVotacion(
        estado_operativo=recursos.estado_operativo,
        ejecutor_mutaciones=recursos.ejecutor_mutaciones,
    )


@enrutador_votaciones.post(
    "/votaciones",
    response_model=RespuestaVotacion,
    status_code=status.HTTP_201_CREATED,
    responses=RESPUESTAS_ERROR_VOTACION,
    summary="Abrir una votación",
)
async def abrir_votacion(
    solicitud: Request,
    apertura: SolicitudAbrirVotacion,
) -> RespuestaVotacion:
    """Valida el body, abre bajo exclusión y devuelve la entidad normalizada."""

    votacion = await _crear_servicio(solicitud).abrir_votacion(apertura.convertir())
    return RespuestaVotacion.model_validate(votacion)


@enrutador_votaciones.post(
    "/votaciones/{id}/finalizacion",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=RESPUESTAS_ERROR_FINALIZACION,
    summary="Finalizar manualmente una votación como inconclusa",
)
async def finalizar_votacion(
    id: str,
    solicitud: Request,
    finalizacion: SolicitudFinalizarVotacion,
) -> Response:
    """Aplica el motivo validado sobre la votación exacta bajo exclusión."""

    await _crear_servicio(solicitud).finalizar_votacion_manualmente(
        id,
        finalizacion.motivo,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@enrutador_votaciones.post(
    "/votaciones/{id}/desempate",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=RESPUESTAS_ERROR_DESEMPATE,
    summary="Emitir el desempate presidencial",
)
async def desempatar_votacion(
    id: str,
    solicitud: Request,
    desempate: SolicitudDesempate,
) -> Response:
    """Desempata la votación exacta con la Presidencia vigente del backend."""

    await _crear_servicio(solicitud).desempatar_votacion(
        id,
        desempate.convertir_sentido(),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
