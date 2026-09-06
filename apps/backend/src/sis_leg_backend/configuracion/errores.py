"""Errores deterministas de la carga de configuración y padrón (WP-003).

Toda falla de lectura, parseo o validación de ``config/system.toml`` y
``config/concejales.csv`` se reporta con una de estas excepciones. Los
mensajes son estables y en español, de modo que puedan verificarse en las
pruebas y leerse con claridad en un registro de errores. No agregan reglas
institucionales: solo reflejan incumplimientos del contrato técnico aprobado.
"""

from __future__ import annotations


class ErrorConfiguracion(Exception):
    """Error base de todos los fallos de configuración y padrón (WP-003).

    Permite capturar cualquier problema de carga con un único tipo cuando la
    causa concreta no importa, y a la vez distinguir subtipos cuando sí.
    """


class ErrorTomlInvalido(ErrorConfiguracion):
    """El archivo ``system.toml`` no pudo leerse o no es TOML válido.

    Cubre tanto la sintaxis inválida (el parser de TOML falla) como la
    imposibilidad de leer el archivo (por ejemplo, que no exista).
    """


class ErrorValidacionConfiguracion(ErrorConfiguracion):
    """El TOML se leyó bien pero no cumple las reglas técnicas del esquema.

    Por ejemplo: ``quorum`` no es un entero positivo, ``rows`` está vacía o
    un temporizador es negativo. Cada mensaje indica qué clave canónica falla
    y qué se esperaba, usando el mismo nombre que aparece en el archivo.
    """


class ErrorPadronInvalido(ErrorConfiguracion):
    """El archivo ``concejales.csv`` no cumple el contrato canónico del padrón.

    Cubre el encabezado no exacto (incluido el formato histórico con
    ``presente``), campos vacíos o duplicados, bancas inválidas, rutas de
    imagen externas y la correspondencia exacta padrón/disposición.
    """


class ErrorMensajesTecnicosInvalido(ErrorConfiguracion):
    """El CSV de mensajes técnicos precargados no cumple su contrato (WP-055).

    Cubre el encabezado no exacto, la cantidad de columnas, identificadores
    vacíos/duplicados/con caracteres no permitidos, textos vacíos o con saltos
    de línea y destinos fuera de ``MODERACION``/``RECINTO``/``AMBOS``.

    A diferencia del padrón, este archivo lo escribe el propio backend: por eso
    un archivo inválido nunca se sobrescribe, solamente se rechaza.
    """
