"""Pruebas unitarias de normalización amplia de teclas físicas y numpad.

Verifica:
1. Normalización de dígitos de teclado principal y numpad (0..9, KP0..KP9,
   KEY_0..KEY_9, KEY_KP0..KEY_KP9).
2. Normalización de operadores aritméticos (+, -, *, /) y punto decimal.
3. Normalización de teclas de control aprobadas (ENTER, ESC, TAB, SPACE, BACKSPACE).
4. Rechazo (retorno None) para cualquier tecla no catalogada.
"""

from __future__ import annotations

import pytest
from sis_leg_device_bridge.normalizador import normalizar_tecla


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        # Dígitos principales
        ("0", "0"),
        ("1", "1"),
        ("2", "2"),
        ("3", "3"),
        ("4", "4"),
        ("5", "5"),
        ("6", "6"),
        ("7", "7"),
        ("8", "8"),
        ("9", "9"),
        ("KEY_0", "0"),
        ("KEY_1", "1"),
        ("KEY_2", "2"),
        ("KEY_3", "3"),
        ("KEY_4", "4"),
        ("KEY_5", "5"),
        ("KEY_6", "6"),
        ("KEY_7", "7"),
        ("KEY_8", "8"),
        ("KEY_9", "9"),
        # Keypad / Numpad
        ("KP0", "0"),
        ("KP1", "1"),
        ("KP2", "2"),
        ("KP3", "3"),
        ("KP4", "4"),
        ("KP5", "5"),
        ("KP6", "6"),
        ("KP7", "7"),
        ("KP8", "8"),
        ("KP9", "9"),
        ("KEY_KP0", "0"),
        ("KEY_KP1", "1"),
        ("KEY_KP2", "2"),
        ("KEY_KP3", "3"),
        ("KEY_KP4", "4"),
        ("KEY_KP5", "5"),
        ("KEY_KP6", "6"),
        ("KEY_KP7", "7"),
        ("KEY_KP8", "8"),
        ("KEY_KP9", "9"),
        # Punto decimal
        (".", "."),
        ("DOT", "."),
        ("KEY_DOT", "."),
        ("KPDOT", "."),
        ("KEY_KPDOT", "."),
        # Operadores
        ("+", "+"),
        ("KEY_KPPLUS", "+"),
        ("KPPLUS", "+"),
        ("-", "-"),
        ("KEY_MINUS", "-"),
        ("KEY_KPMINUS", "-"),
        ("KPMINUS", "-"),
        ("*", "*"),
        ("KEY_KPASTERISK", "*"),
        ("KPASTERISK", "*"),
        ("/", "/"),
        ("KEY_SLASH", "/"),
        ("KEY_KPSLASH", "/"),
        ("KPSLASH", "/"),
        # Acciones y control
        ("ENTER", "ENTER"),
        ("KEY_ENTER", "ENTER"),
        ("KPENTER", "ENTER"),
        ("KEY_KPENTER", "ENTER"),
        ("ESC", "ESC"),
        ("KEY_ESC", "ESC"),
        ("TAB", "TAB"),
        ("KEY_TAB", "TAB"),
        ("SPACE", "SPACE"),
        ("KEY_SPACE", "SPACE"),
        ("BACKSPACE", "BACKSPACE"),
        ("KEY_BACKSPACE", "BACKSPACE"),
    ],
)
def test_normalizacion_teclas_validas(entrada: str, esperado: str) -> None:
    """Demuestra que todas las variantes reconocidas se normalizan al valor canónico."""
    assert normalizar_tecla(entrada) == esperado
    # Insensibilidad a mayúsculas/minúsculas y espacios
    assert normalizar_tecla(f"  {entrada.lower()}  ") == esperado


@pytest.mark.parametrize(
    "tecla_desconocida",
    [
        "KEY_A",
        "KEY_B",
        "KEY_F1",
        "KEY_F12",
        "KEY_VOLUMEUP",
        "KEY_MUTE",
        "KEY_LEFTCTRL",
        "KEY_CAPSLOCK",
        "DESCONOCIDA",
        "",
        "   ",
    ],
)
def test_teclas_desconocidas_retornan_none(tecla_desconocida: str) -> None:
    """Verifica que teclas fuera del catálogo amplio devuelvan None (para ser ignoradas)."""
    assert normalizar_tecla(tecla_desconocida) is None
