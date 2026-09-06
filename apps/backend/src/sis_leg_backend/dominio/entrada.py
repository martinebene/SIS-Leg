"""Tipos internos del flujo de entrada lógica de dispositivos (WP-006/WP-010).

El endpoint HTTP utiliza modelos Pydantic en su frontera, pero el servicio de
dominio no necesita conocer ``Request`` ni ``APIRouter``. Estas dataclasses
representan el resultado funcional que el servicio entrega a la API y permiten
probar presencia, test y voto sin levantar FastAPI.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sis_leg_backend.dominio.votacion import EstadoVotacion, ValorVotoOrdinario


@dataclass(frozen=True, slots=True)
class Pulsacion:
    """Pulsación lógica ya validada por la frontera de transporte.

    ``dispositivo`` es el identificador lógico que entrega el bridge y ``tecla``
    es el texto recibido. No se almacena fingerprint, DNI ni banca aquí: la
    resolución de identidad ocurre exclusivamente contra el padrón congelado.
    """

    dispositivo: str
    tecla: str


@dataclass(frozen=True, slots=True)
class IdentidadConcejal:
    """Subset de identidad que el contrato de entrada permite devolver."""

    dni: str
    nombre: str
    apellido: str
    banca: int


@dataclass(frozen=True, slots=True)
class ResultadoPresencia:
    """Resultado derivado de alternar la presencia de un concejal."""

    tipo: str
    presente: bool
    presentes: int
    quorum_alcanzado: bool


@dataclass(frozen=True, slots=True)
class ResultadoTest:
    """Resultado de activar o renovar un test visual temporal."""

    tipo: str
    activo: bool
    duracion_segundos: int | float


@dataclass(frozen=True, slots=True)
class ResultadoVoto:
    """Resultado funcional de aceptar una tecla de voto ordinario.

    El concejal asociado continúa en el campo común de ``RespuestaEntrada``.
    Aquí se informa el valor persistido y si esa misma operación dejó la
    recepción abierta o produjo su autocierre.
    """

    tipo: str
    valor: ValorVotoOrdinario
    estado_recepcion: EstadoVotacion


class AccionPalabra(StrEnum):
    """Acciones estables que puede producir una tecla física ``7``."""

    PEDIDO_AGREGADO = "PEDIDO_AGREGADO"
    PEDIDO_RETIRADO = "PEDIDO_RETIRADO"
    USO_FINALIZADO = "USO_FINALIZADO"


@dataclass(frozen=True, slots=True)
class ResultadoPalabra:
    """Resultado funcional de pedir, retirar o finalizar el uso propio."""

    tipo: str
    accion: AccionPalabra


type ResultadoEntrada = ResultadoPresencia | ResultadoTest | ResultadoVoto | ResultadoPalabra


@dataclass(frozen=True, slots=True)
class RespuestaEntrada:
    """Respuesta interna estable para una pulsación procesada.

    Los rechazos normales conservan ``concejal`` solo cuando el dispositivo se
    pudo asociar al padrón, y siempre dejan ``resultado`` en ``None``. Los
    errores técnicos de auditoría no se convierten aquí en una respuesta: la
    excepción llega al manejador HTTP para producir ``503``.
    """

    aceptada: bool
    dispositivo: str
    tecla: str
    motivo: str
    concejal: IdentidadConcejal | None
    resultado: ResultadoEntrada | None
