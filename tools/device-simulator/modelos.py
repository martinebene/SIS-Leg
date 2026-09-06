"""Modelos de datos del simulador de dispositivos y escenarios (WP-007).

Este modulo define las estructuras de datos inmutables y tipadas utilizadas
por el simulador para representar:

1. Pulsaciones logicas enviadas al backend (`dispositivo` y `tecla`).
2. Respuestas crudas HTTP recibidas del servidor, preservando el cuerpo literal.
3. Resultados consolidados de envio con diagnostico de red.
4. Expectativas declaradas sobre la respuesta (status HTTP, aceptada, motivo).
5. Pasos de un escenario declarativo (pulsacion, pausa, grupo concurrente).
6. Resultados y estadisticas de ejecucion de escenarios.

Pedagogia y convenciones:
- Todos los identificadores estan en espanol sin tildes ni eñes (DEC-001).
- Se utilizan dataclasses para claridad, tipado estricto y legibilidad.
- El cuerpo de la respuesta se mantiene como texto literal sin transformar,
  garantizando que la salida para diagnostico sea 100% fiel a lo que envio el backend.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PulsacionLogica:
    """Representa una pulsacion de tecla emitida por un dispositivo logico.

    En SIS-Leg, el simulador y el device-bridge se comunican con el backend
    utilizando identificadores logicos (por ejemplo 'dev01', 'dev12'), nunca
    identificadores fisicos o numeros de serie de hardware.

    Atributos:
        dispositivo: Identificador logico normalizado (ejemplo: 'dev05').
        tecla: Texto que identifica la tecla pulsada (ejemplo: '9', '8', '+', 'enter').
    """

    dispositivo: str
    tecla: str

    def a_diccionario(self) -> dict[str, str]:
        """Convierte la pulsacion al formato JSON esperado por el endpoint del backend.

        El endpoint `POST /api/v1/entradas/tecla` espera exactamente el cuerpo:
        `{"dispositivo": "devXX", "tecla": "..."}`.
        """
        return {
            "dispositivo": self.dispositivo,
            "tecla": self.tecla,
        }


@dataclass(frozen=True)
class RespuestaServidor:
    """Representa la respuesta cruda devuelta por el servidor HTTP.

    Regla critica de WP-007:
    El simulador debe conservar y mostrar el cuerpo literal (`cuerpo_literal`)
    tal como fue devuelto por el servidor, sin formatear JSON, sin reordenar
    claves y sin suprimir campos desconocidos o mensajes de error.

    Atributos:
        status_http: Codigo de estado HTTP recibido (ejemplo: 200, 422, 503).
        cuerpo_literal: Texto exacto recibido en el body de la respuesta.
        tiempo_respuesta_ms: Duracion del viaje ida y vuelta en milisegundos (opcional).
    """

    status_http: int
    cuerpo_literal: str
    tiempo_respuesta_ms: float | None = None


@dataclass(frozen=True)
class ResultadoEnvio:
    """Resultado del envio de una pulsacion logica a traves de HTTP.

    Distingue claramente entre:
    - Una respuesta HTTP valida obtenida del servidor (incluso si representa un error 4xx o 5xx).
    - Un fallo a nivel de red (conexion rechazada, timeout, DNS no resuelto).

    Atributos:
        pulsacion: La pulsacion logica que se intento enviar.
        respuesta: La respuesta del servidor si se logro comunicacion HTTP; None si fallo la red.
        error_red: Mensaje descriptivo ante problemas de conexion/red; None si hubo respuesta.
        exito_comunicacion: True si se recibio respuesta HTTP; False si hubo error de red.
    """

    pulsacion: PulsacionLogica
    respuesta: RespuestaServidor | None = None
    error_red: str | None = None
    exito_comunicacion: bool = True

    @property
    def es_exitoso_para_cli(self) -> bool:
        """Determina si la pulsacion se considera exitosa para el codigo de salida de la CLI.

        En modo pulsacion unica desde shell:
        - Codigo 0: Se obtuvo una respuesta HTTP 2xx (incluso si funcionalmente `aceptada=false`).
        - Codigo distinto de 0: Fallo de red, timeout o respuesta HTTP 4xx / 5xx.
        """
        if not self.exito_comunicacion or self.respuesta is None:
            return False
        return 200 <= self.respuesta.status_http < 300


@dataclass(frozen=True)
class ExpectativaRespuesta:
    """Expectativas opcionales que un escenario puede declarar sobre una respuesta.

    Cada campo es opcional. Omitir un campo significa que no se valida ese aspecto
    de la respuesta (por ejemplo, si solo se especifica `status_http=200`, no se
    evaluan `aceptada` ni `motivo`).

    Atributos:
        status_http: Codigo HTTP esperado (ejemplo: 200).
        aceptada: Booleano esperado en el campo `aceptada` del DTO JSON de respuesta.
        motivo: Identificador estable esperado en el campo `motivo` del DTO JSON de respuesta.
    """

    status_http: int | None = None
    aceptada: bool | None = None
    motivo: str | None = None

    @property
    def tiene_expectativas(self) -> bool:
        """Indica si al menos un criterio de verificacion fue configurado."""
        return self.status_http is not None or self.aceptada is not None or self.motivo is not None


@dataclass(frozen=True)
class PasoPulsacion:
    """Paso de escenario que envia una pulsacion individual y opcionalmente valida su respuesta.

    Atributos:
        pulsacion: La pulsacion logica a emitir.
        esperado: Expectativas opcionales sobre la respuesta.
    """

    pulsacion: PulsacionLogica
    esperado: ExpectativaRespuesta | None = None


@dataclass(frozen=True)
class PasoPausa:
    """Paso de escenario que introduce una espera temporal antes del siguiente paso.

    Permite simular intervalos realistas entre pulsaciones y probar temporizadores.

    Atributos:
        milisegundos: Cantidad de milisegundos a esperar (debe ser mayor o igual a cero).
    """

    milisegundos: int


@dataclass(frozen=True)
class PasoConcurrente:
    """Paso de escenario que emite multiples pulsaciones de forma simultanea.

    Utiliza primitivas asincronas para disparar todos los envios en paralelo real.
    El simulador no decide el orden en que el backend procesara las pulsaciones;
    el orden oficial es el que el backend serialice de forma determinista.

    Atributos:
        pulsaciones: Lista de pulsaciones individuales con sus expectativas opcionales.
    """

    pulsaciones: list[PasoPulsacion]


# Tipo union que engloba los tres tipos posibles de pasos en un escenario
TipoPaso = PasoPulsacion | PasoPausa | PasoConcurrente


@dataclass(frozen=True)
class EscenarioDeclarativo:
    """Representa un escenario completo leido desde un archivo JSON versionable.

    Atributos:
        nombre: Identificador legible del escenario (ejemplo: 'presencia-y-rechazos').
        precondicion: Descripcion informativa del estado previo requerido en el backend
            (ejemplo: 'backend en PREPARANDO con configuracion/padron de referencia').
        pasos: Secuencia ordenada de pasos a ejecutar.
    """

    nombre: str
    precondicion: str
    pasos: list[TipoPaso]


@dataclass(frozen=True)
class DiscrepanciaExpectativa:
    """Detalle de una expectativa que no se cumplio al evaluar una respuesta.

    Atributos:
        campo: Nombre del campo evaluado ('status_http', 'aceptada', 'motivo', 'json_invalido').
        esperado: Valor que se esperaba recibir.
        obtenido: Valor que realmente devolvio el servidor o descripcion del error.
        detalle: Explicacion clara de la discrepancia.
    """

    campo: str
    esperado: Any
    obtenido: Any
    detalle: str


@dataclass
class ResultadoPasoIndividual:
    """Resultado consolidado de ejecutar un paso individual de pulsacion.

    Atributos:
        resultado_envio: El resultado del envio HTTP.
        discrepancias: Lista de discrepancias encontradas respecto a las expectativas declaradas.
    """

    resultado_envio: ResultadoEnvio
    discrepancias: list[DiscrepanciaExpectativa] = field(
        default_factory=list[DiscrepanciaExpectativa]
    )

    @property
    def es_valido(self) -> bool:
        """Indica si el paso no tuvo errores de red y cumplio todas sus expectativas."""
        return self.resultado_envio.exito_comunicacion and len(self.discrepancias) == 0


@dataclass
class ResumenEjecucionEscenario:
    """Resumen final y estadisticas de la ejecucion de un escenario.

    Atributos:
        nombre_escenario: Nombre del escenario ejecutado.
        total_pulsaciones: Cantidad total de pulsaciones enviadas.
        total_pausas: Cantidad de pausas ejecutadas.
        total_fallos_red: Cantidad de pulsaciones que fallaron por error de red o timeout.
        total_discrepancias: Cantidad total de expectativas no cumplidas.
        resultados_pasos: Detalle de cada paso de pulsacion ejecutado.
    """

    nombre_escenario: str
    total_pulsaciones: int = 0
    total_pausas: int = 0
    total_fallos_red: int = 0
    total_discrepancias: int = 0
    resultados_pasos: list[ResultadoPasoIndividual] = field(
        default_factory=list[ResultadoPasoIndividual]
    )

    @property
    def es_exitoso(self) -> bool:
        """Determina si el escenario completo paso sin ningun error ni discrepancia."""
        return self.total_fallos_red == 0 and self.total_discrepancias == 0
