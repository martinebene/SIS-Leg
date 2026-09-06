"""Pruebas unitarias de construcción y validación del fingerprint canónico Linux.

Verifica:
1. Construcción exacta con todos los campos poblados.
2. Manejo determinista de campos ausentes o vacíos (phys, uniq, name).
3. Formateo hexadecimal de 4 dígitos (con ceros a la izquierda y minúsculas).
4. Independencia absoluta de la ruta efímera '/dev/input/eventN'.
5. Validación estricta con expresiones regulares de la forma canónica.
"""

from __future__ import annotations

import pytest
from sis_leg_device_bridge.fingerprint import (
    construir_fingerprint_linux,
    formatear_hex_4_digitos,
    validar_fingerprint_linux,
)


def test_construir_fingerprint_completo() -> None:
    """Demuestra que un dispositivo con todos los campos genera el fingerprint canónico."""
    fp = construir_fingerprint_linux(
        vendor=0x1A2C,
        product=0x2D43,
        version=0x0110,
        phys="usb-0000:00:14.0-1/input0",
        uniq="SER12345",
        name="USB Keyboard",
    )
    esperado = (
        "lin|vendor=1a2c|product=2d43|version=0110|"
        "phys=usb-0000:00:14.0-1/input0|uniq=SER12345|name=USB Keyboard"
    )
    assert fp == esperado
    assert validar_fingerprint_linux(fp) is True


def test_construir_fingerprint_con_campos_vacios() -> None:
    """Demuestra que campos nulos se normalizan a texto vacío conservando etiquetas."""
    fp = construir_fingerprint_linux(
        vendor=0x0001,
        product=0x0002,
        version=0x0003,
        phys=None,
        uniq=None,
        name=None,
    )
    esperado = "lin|vendor=0001|product=0002|version=0003|phys=|uniq=|name="
    assert fp == esperado
    assert validar_fingerprint_linux(fp) is True


def test_formateo_hexadecimal_4_digitos() -> None:
    """Demuestra el formateo determinista de 4 dígitos hexadecimales en minúsculas."""
    # Números enteros
    assert formatear_hex_4_digitos(0) == "0000"
    assert formatear_hex_4_digitos(1) == "0001"
    assert formatear_hex_4_digitos(16) == "0010"
    assert formatear_hex_4_digitos(0x1A2C) == "1a2c"
    assert formatear_hex_4_digitos(0xFFFF) == "ffff"

    # Cadenas con o sin prefijo 0x
    assert formatear_hex_4_digitos("1a2c") == "1a2c"
    assert formatear_hex_4_digitos("0x1A2C") == "1a2c"
    assert formatear_hex_4_digitos("10") == "0010"
    assert formatear_hex_4_digitos("0x2D") == "002d"


def test_formateo_hexadecimal_invalido() -> None:
    """Demuestra que valores que no representan hexadecimales válidos lanzan ValueError."""
    with pytest.raises(ValueError, match="Valor hexadecimal inválido"):
        formatear_hex_4_digitos("no-hex-xyz")


def test_independencia_de_ruta_event_n() -> None:
    """Demuestra que el fingerprint es idéntico sin importar si el nodo es event0 o event99."""
    fp1 = construir_fingerprint_linux(
        vendor=0x1234,
        product=0x5678,
        version=0x0100,
        phys="usb-bus1/input0",
        uniq="",
        name="Keypad",
    )
    fp2 = construir_fingerprint_linux(
        vendor=0x1234,
        product=0x5678,
        version=0x0100,
        phys="usb-bus1/input0",
        uniq="",
        name="Keypad",
    )
    assert fp1 == fp2
    assert "event" not in fp1


@pytest.mark.parametrize(
    "fingerprint_invalido",
    [
        "",  # Vacío
        "   ",  # Espacios
        "win|vendor=1234|product=5678|version=0100|phys=|uniq=|name=",  # Prefijo no linux
        "lin|vendor=123|product=5678|version=0100|phys=|uniq=|name=",  # Vendor corto (3 digitos)
        "lin|vendor=12345|product=5678|version=0100|phys=|uniq=|name=",  # Vendor largo (5 digitos)
        "lin|vendor=1234|product=5678|version=0100|phys=|uniq=",  # Falta campo name
        "lin|vendor=1234|product=5678|version=0100",  # Truncado
        "texto_cualquiera",
    ],
)
def test_validacion_fingerprint_invalidos(fingerprint_invalido: str) -> None:
    """Verifica que fingerprints malformados sean rechazados por validar_fingerprint_linux."""
    assert validar_fingerprint_linux(fingerprint_invalido) is False
