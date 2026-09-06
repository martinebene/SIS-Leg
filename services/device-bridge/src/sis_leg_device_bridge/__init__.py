"""Paquete del bridge de dispositivos físicos de SIS-Leg.

Este servicio captura eventos de teclados físicos en Linux mediante `evdev`,
deriva el fingerprint canónico de cada hardware, resuelve su identificador lógico
`devXX` a través de `devices.json`, normaliza las teclas físicas reconocidas
y las transmite al backend FastAPI (`POST /api/v1/entradas/tecla`) con cero
reintentos automáticos.
"""

from __future__ import annotations

from sis_leg_device_bridge.adaptador_linux import (
    AdaptadorEntradaFisica,
    AdaptadorEvdevLinux,
    AdaptadorFalso,
    DispositivoFisico,
    ErrorDispositivoDesconectado,
)
from sis_leg_device_bridge.cliente_http import ClienteHttpBackend
from sis_leg_device_bridge.configuracion import (
    ConfiguracionBridge,
    ErrorConfiguracionBridge,
    cargar_dispositivos_json,
)
from sis_leg_device_bridge.fingerprint import (
    construir_fingerprint_linux,
    validar_fingerprint_linux,
)
from sis_leg_device_bridge.modelos import (
    EventoTeclaFisica,
    RespuestaEnvioBackend,
    SolicitudEntradaLogica,
)
from sis_leg_device_bridge.normalizador import normalizar_tecla
from sis_leg_device_bridge.remapeo import (
    CoordinadorRemapeoBridge,
    EstadoRemapeoBridge,
    PersistenciaRemapeo,
)
from sis_leg_device_bridge.servicio import ServicioDeviceBridge
from sis_leg_device_bridge.servidor_control import ServidorControlBridge

__all__ = [
    "AdaptadorEntradaFisica",
    "AdaptadorEvdevLinux",
    "AdaptadorFalso",
    "ClienteHttpBackend",
    "CoordinadorRemapeoBridge",
    "ConfiguracionBridge",
    "DispositivoFisico",
    "ErrorConfiguracionBridge",
    "ErrorDispositivoDesconectado",
    "EventoTeclaFisica",
    "EstadoRemapeoBridge",
    "PersistenciaRemapeo",
    "RespuestaEnvioBackend",
    "ServicioDeviceBridge",
    "ServidorControlBridge",
    "SolicitudEntradaLogica",
    "cargar_dispositivos_json",
    "construir_fingerprint_linux",
    "normalizar_tecla",
    "validar_fingerprint_linux",
]
