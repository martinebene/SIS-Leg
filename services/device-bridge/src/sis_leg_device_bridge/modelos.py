"""Modelos de datos y estructuras internas del bridge de dispositivos físicos.

Este módulo define las estructuras de datos que representan:
1. Eventos físicos de pulsación generados por los teclados (`EventoTeclaFisica`).
2. Solicitud lógica enviada al backend (`SolicitudEntradaLogica`).
3. Respuesta del backend ante el envío de una pulsación (`RespuestaEnvioBackend`).

Siguiendo DEC-001 y DEC-015, todas las estructuras bajo control del proyecto
utilizan nombres en español y se encuentran desacopladas de librerías externas
como evdev para facilitar pruebas unitarias deterministas sin hardware real.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EventoTeclaFisica:
    """Representación desacoplada de un evento de tecla física detectado.

    Atributos:
        fingerprint: Cadena canónica que identifica el dispositivo físico.
        codigo_tecla: Código numérico de scancode o keycode del evento.
        nombre_tecla: Nombre textual del evento (ej: 'KEY_1', 'KEY_KP1', 'ENTER').
        es_bajada: True si corresponde a una pulsación (keydown); False para keyup o repeat.
        descripcion_dispositivo: Nombre o información diagnóstica opcional del hardware.
    """

    fingerprint: str
    codigo_tecla: int
    nombre_tecla: str
    es_bajada: bool
    descripcion_dispositivo: str = ""


@dataclass(frozen=True)
class SolicitudEntradaLogica:
    """Contrato exacto de la carga útil HTTP enviada a FastAPI.

    Atributos:
        dispositivo: Identificador lógico del dispositivo (ej: 'dev01', 'dev02').
        tecla: Valor normalizado de la tecla (ej: '1', '9', 'ENTER').
    """

    dispositivo: str
    tecla: str

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
