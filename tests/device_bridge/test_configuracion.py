"""Pruebas unitarias de carga y validación estricta de devices.json y configuración.

Verifica:
1. Carga exitosa de un archivo devices.json válido con múltiples mapeos.
2. Rechazo explícito de archivo inexistente.
3. Rechazo de archivo vacío o JSON malformado.
4. Rechazo de raíz que no sea un objeto JSON.
5. DETECCIÓN Y RECHAZO OBLIGATORIO DE CLAVES JSON DUPLICADAS (DEC-015).
6. Rechazo de fingerprints vacíos o con formato no canónico.
7. Rechazo de identificadores lógicos inválidos (distintos de devXX con 2 dígitos).
8. Rechazo de identificadores lógicos duplicados asignados a distintos fingerprints.
9. Garantía de que un error nunca devuelve silenciosamente un diccionario vacío.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sis_leg_device_bridge.configuracion import (
    ErrorConfiguracionBridge,
    cargar_dispositivos_json,
)

FINGERPRINT_1 = "lin|vendor=1a2c|product=2d43|version=0110|phys=usb-1|uniq=|name=Teclado 1"
FINGERPRINT_2 = "lin|vendor=1a2c|product=2d43|version=0110|phys=usb-2|uniq=|name=Teclado 2"
FINGERPRINT_3 = "lin|vendor=1a2c|product=2d43|version=0110|phys=usb-3|uniq=|name=Teclado 3"


def test_cargar_devices_json_valido(tmp_path: Path) -> None:
    """Demuestra que un archivo devices.json válido se carga como un diccionario plano."""
    archivo = tmp_path / "devices.json"
    contenido = f"""{{
        "{FINGERPRINT_1}": "dev01",
        "{FINGERPRINT_2}": "dev02"
    }}"""
    archivo.write_text(contenido, encoding="utf-8")

    mapeo = cargar_dispositivos_json(archivo)
    assert len(mapeo) == 2
    assert mapeo[FINGERPRINT_1] == "dev01"
    assert mapeo[FINGERPRINT_2] == "dev02"


def test_archivo_inexistente(tmp_path: Path) -> None:
    """Verifica que intentar cargar una ruta que no existe lanza ErrorConfiguracionBridge."""
    archivo = tmp_path / "inexistente.json"
    with pytest.raises(ErrorConfiguracionBridge, match="El archivo de dispositivos no existe"):
        cargar_dispositivos_json(archivo)


def test_archivo_vacio(tmp_path: Path) -> None:
    """Verifica que un archivo vacío lanza ErrorConfiguracionBridge."""
    archivo = tmp_path / "vacio.json"
    archivo.write_text("   \n", encoding="utf-8")
    with pytest.raises(ErrorConfiguracionBridge, match="está vacío"):
        cargar_dispositivos_json(archivo)


def test_json_sintaxis_invalida(tmp_path: Path) -> None:
    """Verifica que sintaxis JSON inválida lanza ErrorConfiguracionBridge con detalle."""
    archivo = tmp_path / "invalido.json"
    archivo.write_text("{ clave_sin_comillas: 123 }", encoding="utf-8")
    with pytest.raises(ErrorConfiguracionBridge, match="Error de sintaxis JSON"):
        cargar_dispositivos_json(archivo)


def test_raiz_no_objeto(tmp_path: Path) -> None:
    """Verifica que un JSON cuya raíz sea una lista lance ErrorConfiguracionBridge."""
    archivo = tmp_path / "lista.json"
    archivo.write_text('["dev01", "dev02"]', encoding="utf-8")
    with pytest.raises(ErrorConfiguracionBridge, match="debe ser un objeto JSON plano"):
        cargar_dispositivos_json(archivo)


def test_deteccion_claves_duplicadas_en_json(tmp_path: Path) -> None:
    """Demuestra el cumplimiento de DEC-015: detectar y rechazar claves JSON repetidas."""
    archivo = tmp_path / "duplicados.json"
    # Misma clave repetida dos veces con distintos valores
    contenido = f"""{{
        "{FINGERPRINT_1}": "dev01",
        "{FINGERPRINT_1}": "dev02"
    }}"""
    archivo.write_text(contenido, encoding="utf-8")

    with pytest.raises(ErrorConfiguracionBridge, match="Clave JSON duplicada"):
        cargar_dispositivos_json(archivo)


def test_fingerprint_invalido_en_json(tmp_path: Path) -> None:
    """Verifica que un fingerprint malformado sea detectado y rechazado."""
    archivo = tmp_path / "fp_invalido.json"
    contenido = '{"fingerprint_invalido_sin_formato": "dev01"}'
    archivo.write_text(contenido, encoding="utf-8")

    with pytest.raises(ErrorConfiguracionBridge, match="Fingerprint con formato Linux inválido"):
        cargar_dispositivos_json(archivo)


def test_valor_no_string(tmp_path: Path) -> None:
    """Verifica que un valor numérico o no string lance ErrorConfiguracionBridge."""
    archivo = tmp_path / "valor_no_str.json"
    contenido = f'{{"{FINGERPRINT_1}": 1}}'
    archivo.write_text(contenido, encoding="utf-8")

    with pytest.raises(ErrorConfiguracionBridge, match="debe ser string"):
        cargar_dispositivos_json(archivo)


@pytest.mark.parametrize(
    "dev_invalido",
    [
        "dev1",  # Solo 1 dígito
        "dev001",  # 3 dígitos
        "dev",  # Sin dígitos
        "devXX",  # Letras en lugar de números
        "DEV01",  # Mayúsculas
        "1",  # Solo número
        "banca-01",  # Prefijo no dev
    ],
)
def test_identificador_logico_malformado(tmp_path: Path, dev_invalido: str) -> None:
    """Verifica que valores que no cumplan '^dev\\d{2}$' sean rechazados."""
    archivo = tmp_path / "dev_invalido.json"
    contenido = f'{{"{FINGERPRINT_1}": "{dev_invalido}"}}'
    archivo.write_text(contenido, encoding="utf-8")

    with pytest.raises(ErrorConfiguracionBridge, match="Identificador lógico .* inválido"):
        cargar_dispositivos_json(archivo)


def test_identificador_logico_duplicado(tmp_path: Path) -> None:
    """Demuestra que dos fingerprints distintos asociados al mismo devXX son rechazados."""
    archivo = tmp_path / "logico_duplicado.json"
    contenido = f"""{{
        "{FINGERPRINT_1}": "dev01",
        "{FINGERPRINT_2}": "dev01"
    }}"""
    archivo.write_text(contenido, encoding="utf-8")

    with pytest.raises(ErrorConfiguracionBridge, match="Identificador lógico duplicado 'dev01'"):
        cargar_dispositivos_json(archivo)
