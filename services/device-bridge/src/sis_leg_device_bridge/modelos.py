"""Modelos de datos y estructuras internas del bridge de dispositivos físicos.

Este módulo define las estructuras de datos que representan:
1. Eventos físicos de pulsación generados por los teclados (`EventoTeclaFisica`).
2. Solicitud lógica enviada al backend (`SolicitudEntradaLogica`).
3. Respuesta del backend ante el envío de una pulsación (`RespuestaEnvioBackend`).

Siguiendo DEC-001 y DEC-015, todas las estructuras bajo control del proyecto
utilizan nombres en español y se encuentran desacopladas de librerías externas
como evdev para facilitar pruebas unitarias deterministas sin hardware real.

Representación textual redactada (WP-088)
-----------------------------------------

Las tres estructuras transportan, en algún campo, el contenido de una tecla. Como el
`repr` automático de una `dataclass` es lo que imprime `logger.debug("%s", objeto)`, una
sola línea de diagnóstico escrita sin pensar bastaría para volcar al journal la banca y su
tecla `1/2/3`, es decir el sentido del voto de una persona identificable.

Por eso cada una define su propio `__repr__`: conserva todos los campos que sirven para
depurar (dispositivo, fingerprint, ruta, código HTTP, motivo estable, clase de resultado) y
sustituye únicamente el contenido sensible por un marcador. La protección deja de depender
de que cada autor recuerde no imprimir el objeto y pasa a estar en el objeto mismo.

Esto no cambia ningún contrato: el cuerpo HTTP se sigue construyendo con
`SolicitudEntradaLogica.a_diccionario()` y los campos siguen siendo legibles por código.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Marcador único con el que las tres estructuras reemplazan contenido sensible en su
# representación textual. Es deliberadamente reconocible para que, si aparece en un log,
# quede claro que hubo una redacción y no un dato faltante.
VALOR_REDACTADO = "<redactado por WP-088>"


@dataclass(frozen=True)
class EventoTeclaFisica:
    """Representación desacoplada de un evento de tecla física detectado.

    El `fingerprint` responde a «qué teclado es» y sirve para el mapping y el remapeo. La
    `ruta_dispositivo` responde a «por qué descriptor entró esta pulsación» y es la única
    respuesta válida a «¿el kernel nos dio la exclusividad de esta fuente?». Son dos
    preguntas distintas y por eso viajan en dos campos distintos: el kernel concede
    `EVIOCGRAB` a un descriptor abierto, no a una identidad lógica, así que dos descriptores
    con el mismo fingerprint pueden diferir en si están capturados o no.

    Atributos:
        fingerprint: Cadena canónica que identifica el dispositivo físico.
        codigo_tecla: Código numérico de scancode o keycode del evento.
        nombre_tecla: Nombre textual del evento (ej: 'KEY_1', 'KEY_KP1', 'ENTER').
        es_bajada: True si corresponde a una pulsación (keydown); False para keyup o repeat.
        descripcion_dispositivo: Nombre o información diagnóstica opcional del hardware.
        ruta_dispositivo: Descriptor de origen del evento (ej: '/dev/input/event3'). Lo
            completa siempre el adaptador, que es el único componente que sabe de qué
            descriptor leyó. Un evento sin esta ruta no puede demostrar su origen y, por la
            política fail-safe del servicio, nunca se despacha al backend.
    """

    fingerprint: str
    codigo_tecla: int
    nombre_tecla: str
    es_bajada: bool
    descripcion_dispositivo: str = ""
    ruta_dispositivo: str = ""

    def __repr__(self) -> str:
        """Representación sin el contenido de la tecla (WP-088).

        Se conserva la identidad del hardware, que es lo que se necesita para diagnosticar
        mapping, exclusividad y remapeo, y se ocultan el nombre y el código de la tecla:
        para un fingerprint mapeado, ese par es el voto de una banca concreta.
        """
        return (
            f"EventoTeclaFisica(fingerprint={self.fingerprint!r}, "
            f"codigo_tecla={VALOR_REDACTADO!r}, nombre_tecla={VALOR_REDACTADO!r}, "
            f"es_bajada={self.es_bajada!r}, "
            f"descripcion_dispositivo={self.descripcion_dispositivo!r}, "
            f"ruta_dispositivo={self.ruta_dispositivo!r})"
        )


@dataclass(frozen=True)
class SolicitudEntradaLogica:
    """Contrato exacto de la carga útil HTTP enviada a FastAPI.

    Atributos:
        dispositivo: Identificador lógico del dispositivo (ej: 'dev01', 'dev02').
        tecla: Valor normalizado de la tecla (ej: '1', '9', 'ENTER').
    """

    dispositivo: str
    tecla: str

    def __repr__(self) -> str:
        """Representación sin la tecla (WP-088).

        `dispositivo` y `tecla` juntos son literalmente el sentido del voto de una banca.
        El dispositivo se conserva porque identifica el flujo que se está depurando; la
        tecla nunca se imprime.
        """
        return (
            f"SolicitudEntradaLogica(dispositivo={self.dispositivo!r}, tecla={VALOR_REDACTADO!r})"
        )

    def a_diccionario(self) -> dict[str, str]:
        """Serializa la solicitud al diccionario JSON exacto esperado por el backend."""
        return {
            "dispositivo": self.dispositivo,
            "tecla": self.tecla,
        }


@dataclass(frozen=True)
class RespuestaEnvioBackend:
    """Resultado de la transmisión de una pulsación al backend.

    Atributos:
        aceptada: True si el backend aceptó funcionalmente la pulsación,
            False si la rechazó por reglas de negocio, o None si ocurrió un fallo
            de transporte/HTTP.
        codigo_http: Código de estado HTTP retornado (ej: 200, 422, 503) o None
            ante error de conexión o timeout.
        motivo: Código de motivo devuelto por el backend o descripción del error.
        cuerpo: Objeto JSON completo devuelto por el backend, si está disponible.
        error_transporte: Detalle del error de red o timeout si no se pudo completar el envío.
    """

    aceptada: bool | None
    codigo_http: int | None
    motivo: str
    cuerpo: dict[str, Any] | None = field(default=None)
    error_transporte: str | None = field(default=None)

    def __repr__(self) -> str:
        """Representación sin el cuerpo de la respuesta (WP-088).

        El cuerpo es contenido de origen externo: un 422 de FastAPI, por ejemplo, devuelve
        en `detail` la propia entrada rechazada, es decir el `{dispositivo, tecla}` recién
        enviado. Se informa cuántas claves trajo, que es el diagnóstico útil, y no qué
        contenían. La clasificación del resultado (`aceptada`, `codigo_http`, `motivo`,
        `error_transporte`) se conserva íntegra porque `motivo` ya llega saneado desde
        `cliente_http`.
        """
        if self.cuerpo is None:
            cuerpo_descrito = "None"
        else:
            cuerpo_descrito = f"<{len(self.cuerpo)} clave(s) redactadas por WP-088>"
        return (
            f"RespuestaEnvioBackend(aceptada={self.aceptada!r}, "
            f"codigo_http={self.codigo_http!r}, motivo={self.motivo!r}, "
            f"cuerpo={cuerpo_descrito}, error_transporte={self.error_transporte!r})"
        )
