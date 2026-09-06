"""Carga y validación estricta de la configuración del bridge y de devices.json.

Este módulo implementa:
1. `ConfiguracionBridge`: Parámetros operacionales del servicio (URL base de FastAPI,
   timeout HTTP, ruta de devices.json, intervalo de escaneo de dispositivos).
2. `cargar_dispositivos_json`: Lector y validador estricto del archivo canónico
   `services/device-bridge/config/devices.json`.

Conforme a DEC-015 y DT-010:
- El archivo mapea exclusivamente `fingerprint -> devXX`.
- `devXX` son exactamente dos dígitos (ej: 'dev01', 'dev12').
- Se detectan y rechazan explícitamente claves JSON duplicadas mediante
  `object_pairs_hook` en `json.loads` (evitando el comportamiento estándar de
  'last value wins').
- Se valida la unicidad de los identificadores lógicos (no pueden existir dos
  fingerprints apuntando al mismo `devXX`).
- Un fallo de configuración nunca degrada silenciosamente a un mapeo vacío.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from sis_leg_device_bridge.fingerprint import validar_fingerprint_linux

# Patrón canónico del identificador lógico de dispositivo (dev01, dev02, ..., dev99).
PATRON_DISPOSITIVO_LOGICO = re.compile(r"^dev\d{2}$")


class ErrorConfiguracionBridge(Exception):
    """Excepción lanzada cuando la configuración o el archivo devices.json es inválido."""


@dataclass(frozen=True)
class ConfiguracionBridge:
    """Parámetros de configuración técnica del bridge de dispositivos.

    Atributos:
        url_base_api: URL base del backend FastAPI (por defecto http://127.0.0.1:8000).
        timeout_http_segundos: Tiempo límite para cada intento HTTP (por defecto 3.0 s).
        ruta_devices_json: Ruta al archivo de mapeo físico devices.json.
        intervalo_escaneo_segundos: Intervalo para redescubrir dispositivos (default 2.0 s).
        host_control: Interfaz de la API local; usa loopback de forma predeterminada.
        puerto_control: Puerto configurable de la API local de control.
    """

    url_base_api: str = "http://127.0.0.1:8000"
    timeout_http_segundos: float = 3.0
    ruta_devices_json: Path = Path("services/device-bridge/config/devices.json")
    intervalo_escaneo_segundos: float = 2.0
    host_control: str = "127.0.0.1"
    puerto_control: int = 8765


def _analizar_pares_json_sin_duplicados(pares: list[tuple[Any, Any]]) -> dict[str, Any]:
    """Hook para json.loads que detecta claves repetidas en lugar de sobreescribirlas."""
    resultado: dict[str, Any] = {}
    for clave, valor in pares:
        if not isinstance(clave, str):
            raise ErrorConfiguracionBridge(f"Clave en JSON no es de tipo string: {clave!r}")
        if clave in resultado:
            raise ErrorConfiguracionBridge(f"Clave JSON duplicada en devices.json: '{clave}'")
        resultado[clave] = valor
    return resultado


def validar_mapeo_dispositivos(
    datos: dict[str, Any], ruta: Path | str = "devices.json"
) -> dict[str, str]:
    """Valida un mapping completo ya parseado y devuelve una copia tipada.

    La persistencia PERSISTENTE reutiliza exactamente estas invariantes antes
    de escribir, evitando que el camino de remapeo acepte una configuración que
    el arranque posterior rechazaría.
    """

    path_archivo = Path(ruta)
    mapeo_resultado: dict[str, str] = {}
    dispositivos_logicos_vistos: set[str] = set()

    for fp_obj, dev_obj in datos.items():
        if not fp_obj.strip():
            raise ErrorConfiguracionBridge(f"Fingerprint vacío en {path_archivo}: {fp_obj!r}")
        if not validar_fingerprint_linux(fp_obj):
            raise ErrorConfiguracionBridge(
                f"Fingerprint con formato Linux inválido en {path_archivo}: '{fp_obj}'"
            )
        if not isinstance(dev_obj, str):
            raise ErrorConfiguracionBridge(
                f"Valor para fingerprint '{fp_obj}' debe ser string, no {type(dev_obj).__name__}"
            )
        if not PATRON_DISPOSITIVO_LOGICO.fullmatch(dev_obj):
            raise ErrorConfiguracionBridge(
                f"Identificador lógico '{dev_obj}' inválido para fingerprint '{fp_obj}'. "
                "Debe cumplir formato 'devXX' (ej: dev01)."
            )
        if dev_obj in dispositivos_logicos_vistos:
            raise ErrorConfiguracionBridge(
                f"Identificador lógico duplicado '{dev_obj}' en {path_archivo} "
                f"para fingerprint '{fp_obj}'"
            )
        dispositivos_logicos_vistos.add(dev_obj)
        mapeo_resultado[fp_obj] = dev_obj
    return mapeo_resultado


def cargar_dispositivos_json(ruta: Path | str) -> dict[str, str]:
    """Carga y valida rigurosamente el archivo devices.json.

    Args:
        ruta: Ruta al archivo devices.json.

    Returns:
        Diccionario asociando cada fingerprint canónico con su identificador lógico 'devXX'.

    Raises:
        ErrorConfiguracionBridge: Si el archivo no existe, el JSON está malformado,
            contiene claves duplicadas, fingerprints inválidos, identificadores
            lógicos inválidos o identificadores lógicos duplicados.
    """
    path_archivo = Path(ruta)
    if not path_archivo.exists():
        raise ErrorConfiguracionBridge(f"El archivo de dispositivos no existe: {path_archivo}")
    if not path_archivo.is_file():
        raise ErrorConfiguracionBridge(
            f"La ruta de dispositivos no es un archivo regular: {path_archivo}"
        )

    try:
        contenido = path_archivo.read_text(encoding="utf-8")
    except Exception as exc:
        raise ErrorConfiguracionBridge(
            f"Error al leer el archivo de dispositivos {path_archivo}: {exc}"
        ) from exc

    if not contenido.strip():
        raise ErrorConfiguracionBridge(f"El archivo de dispositivos está vacío: {path_archivo}")

    try:
        datos = json.loads(
            contenido,
            object_pairs_hook=_analizar_pares_json_sin_duplicados,
        )
    except json.JSONDecodeError as exc:
        raise ErrorConfiguracionBridge(f"Error de sintaxis JSON en {path_archivo}: {exc}") from exc

    if not isinstance(datos, dict):
        raise ErrorConfiguracionBridge(
            f"La raíz de devices.json en {path_archivo} debe ser un objeto JSON plano, "
            f"no {type(datos).__name__}"
        )

    return validar_mapeo_dispositivos(cast(dict[str, Any], datos), path_archivo)
