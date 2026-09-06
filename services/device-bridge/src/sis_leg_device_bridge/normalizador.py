"""Normalización amplia de nombres de teclas físicas a valores de la API.

Conforme a DEC-015 y la Decisión Humana 4.B:
1. Se normalizan los nombres y códigos de teclas físicas provenientes de evdev
   hacia el catálogo amplio aprobado por la API:
   - Dígitos: '0', '1', '2', '3', '4', '5', '6', '7', '8', '9'
   - Operadores/Signos: '.', '+', '-', '*', '/'
   - Teclas de control: 'ENTER', 'ESC', 'TAB', 'SPACE', 'BACKSPACE'
2. Se mapean las teclas numéricas del teclado auxiliar (numpad):
   - KP0..KP9 -> '0'..'9'
   - KPDOT -> '.'
   - KPPLUS -> '+'
   - KPMINUS -> '-'
   - KPASTERISK -> '*'
   - KPSLASH -> '/'
   - KPENTER -> 'ENTER'
3. Por decisión de diseño institucional, las teclas reconocidas sin semántica
   funcional activa (como '4', '5', '6', '0', 'ENTER', etc.) TAMBIÉN se transmiten
   al backend cuando provienen de un dispositivo mapeado. El bridge NO aplica
   una allowlist de negocio restrictiva (1, 2, 3, 7, 8, 9).
4. Cualquier tecla física desconocida devuelve None, lo que indica que debe ser
   ignorada localmente con registro diagnóstico y sin emitir peticiones HTTP.
"""

from __future__ import annotations

# Tabla canónica de correspondencia entre nombres de tecla de evdev/Linux y valores de API.
MAPEO_NORMALIZACION_TECLAS: dict[str, str] = {
    # Dígitos principales
    "0": "0",
    "1": "1",
    "2": "2",
    "3": "3",
    "4": "4",
    "5": "5",
    "6": "6",
    "7": "7",
    "8": "8",
    "9": "9",
    "KEY_0": "0",
    "KEY_1": "1",
    "KEY_2": "2",
    "KEY_3": "3",
    "KEY_4": "4",
    "KEY_5": "5",
    "KEY_6": "6",
    "KEY_7": "7",
    "KEY_8": "8",
    "KEY_9": "9",
    # Teclado numérico (Keypad / Numpad)
    "KP0": "0",
    "KP1": "1",
    "KP2": "2",
    "KP3": "3",
    "KP4": "4",
    "KP5": "5",
    "KP6": "6",
    "KP7": "7",
    "KP8": "8",
    "KP9": "9",
    "KEY_KP0": "0",
    "KEY_KP1": "1",
    "KEY_KP2": "2",
    "KEY_KP3": "3",
    "KEY_KP4": "4",
    "KEY_KP5": "5",
    "KEY_KP6": "6",
    "KEY_KP7": "7",
    "KEY_KP8": "8",
    "KEY_KP9": "9",
    # Punto y separador decimal
    ".": ".",
    "DOT": ".",
    "KEY_DOT": ".",
    "KPDOT": ".",
    "KEY_KPDOT": ".",
    # Suma / Más
    "+": "+",
    "PLUS": "+",
    "KEY_KPPLUS": "+",
    "KPPLUS": "+",
    # Resta / Menos
    "-": "-",
    "MINUS": "-",
    "KEY_MINUS": "-",
    "KEY_KPMINUS": "-",
    "KPMINUS": "-",
    # Multiplicación / Asterisco
    "*": "*",
    "ASTERISK": "*",
    "KEY_KPASTERISK": "*",
    "KPASTERISK": "*",
    # División / Barra
    "/": "/",
    "SLASH": "/",
    "KEY_SLASH": "/",
    "KEY_KPSLASH": "/",
    "KPSLASH": "/",
    # Teclas de acción y control
    "ENTER": "ENTER",
    "KEY_ENTER": "ENTER",
    "KPENTER": "ENTER",
    "KEY_KPENTER": "ENTER",
    "ESC": "ESC",
    "KEY_ESC": "ESC",
    "TAB": "TAB",
    "KEY_TAB": "TAB",
    "SPACE": "SPACE",
    "KEY_SPACE": "SPACE",
    "BACKSPACE": "BACKSPACE",
    "KEY_BACKSPACE": "BACKSPACE",
}


def normalizar_tecla(tecla: str) -> str | None:
    """Normaliza una cadena representativa de tecla física a su valor canónico.

    Args:
        tecla: Texto o código recibido desde el hardware o driver (ej: 'KEY_KP1', '9', 'enter').

    Returns:
        Cadena normalizada canónica ('1'..'9', '0', 'ENTER', etc.) o None si no es reconocida.
    """
    if not tecla.strip():
        return None

    texto = tecla.strip().upper()
    return MAPEO_NORMALIZACION_TECLAS.get(texto)
