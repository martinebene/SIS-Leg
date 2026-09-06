"""Generación y validación del fingerprint canónico Linux de dispositivos.

Conforme a DEC-015, el identificador físico único de un teclado en Linux tiene
la forma:
    lin|vendor=<hex4>|product=<hex4>|version=<hex4>|phys=<texto>|uniq=<texto>|name=<texto>

Donde:
- vendor, product y version son números hexadecimales de exactamente 4 dígitos en minúsculas.
- phys, uniq y name son textos informativos provistos por el kernel; si están ausentes
  se normalizan a texto vacío conservando las claves (ej: 'uniq=').
- No se incluye la ruta efímera '/dev/input/eventN' para que el fingerprint sea persistente
  ante reinicios o reconexiones en distintos puertos USB.
"""

from __future__ import annotations

import re

# Expresión regular canónica para validar la estructura exacta de un fingerprint Linux.
PATRON_FINGERPRINT_LINUX = re.compile(
    r"^lin\|vendor=[0-9a-fA-F]{4}\|product=[0-9a-fA-F]{4}\|version=[0-9a-fA-F]{4}\|"
    r"phys=.*\|uniq=.*\|name=.*$"
)


def formatear_hex_4_digitos(valor: int | str) -> str:
    """Convierte un valor entero o cadena hexadecimal a 4 dígitos hexadecimales en minúsculas.

    Ejemplos:
        0x1a2c -> '1a2c'
        '1a2c' -> '1a2c'
        16     -> '0010'
        '0x2D' -> '002d'
    """
    if isinstance(valor, int):
        return f"{valor:04x}"

    texto = str(valor).strip()
    if texto.lower().startswith("0x"):
        texto = texto[2:]

    # Parseamos como entero base 16 para asegurar formato y longitud determinista de 4 caracteres
    try:
        val_int = int(texto, 16)
        return f"{val_int:04x}"
    except ValueError:
        # Si no se puede interpretar como entero, formateamos la cadena limpia si tiene 4 chars
        if len(texto) <= 4 and all(c in "0123456789abcdefABCDEF" for c in texto):
            return texto.lower().zfill(4)
        raise ValueError(f"Valor hexadecimal inválido para fingerprint: {valor!r}") from None


def construir_fingerprint_linux(
    vendor: int | str,
    product: int | str,
    version: int | str,
    phys: str | None = None,
    uniq: str | None = None,
    name: str | None = None,
) -> str:
    """Construye el fingerprint persistente canónico para un dispositivo Linux.

    Args:
        vendor: Identificador del fabricante (vendor ID) numérico o hexadecimal.
        product: Identificador del producto (product ID) numérico o hexadecimal.
        version: Versión del hardware o firmware numérica o hexadecimal.
        phys: Ruta física del bus (ej: 'usb-0000:00:14.0-1/input0') o None.
        uniq: Número de serie o identificador único provisto por el dispositivo o None.
        name: Nombre descriptivo del dispositivo asignado por el fabricante o None.

    Returns:
        Cadena con la forma canónica 'lin|vendor=...|product=...|version=...|...'
    """
    v_hex = formatear_hex_4_digitos(vendor)
    p_hex = formatear_hex_4_digitos(product)
    ver_hex = formatear_hex_4_digitos(version)

    phys_texto = "" if phys is None else str(phys)
    uniq_texto = "" if uniq is None else str(uniq)
    name_texto = "" if name is None else str(name)

    return (
        f"lin|vendor={v_hex}|product={p_hex}|version={ver_hex}|"
        f"phys={phys_texto}|uniq={uniq_texto}|name={name_texto}"
    )


def validar_fingerprint_linux(fingerprint: str) -> bool:
    """Verifica si una cadena cumple con el formato exacto del fingerprint Linux canónico."""
    if not fingerprint.strip():
        return False
    return bool(PATRON_FINGERPRINT_LINUX.match(fingerprint))
