"""Carga y validación técnica de ``config/system.toml`` (WP-003).

Flujo principal paso a paso:

1. Se lee el archivo completo desde disco.
2. ``tomllib`` (biblioteca estándar de Python desde 3.11) lo convierte a un
   diccionario: cada sección ``[nombre]`` se vuelve un dict anidado.
3. Se extraen las cinco secciones canónicas y se validan sus claves una por
   una con los validadores privados de este módulo. La sección ``[sonidos]``
   incorporada por WP-065 se delega a ``configuracion.sonidos_recinto``.
4. Con los valores ya validados se construye ``ConfiguracionSistema``, un
   ``dataclass`` congelado: al ser inmutable y no guardar ninguna referencia
   al archivo ni a su contenido, queda congelado para toda la sesión
   (CA-059 y RN-CON-07).

El esquema es el mínimo canónico aprobado en WP-003. Las claves desconocidas
se ignoran deliberadamente: el contrato define qué se debe cargar, no prohíbe
que una instalación futura agregue secciones propias. Los errores de las
claves obligatorias ya son deterministas y cubren cualquier tipeo.
"""

from __future__ import annotations

import math
import tomllib
from pathlib import Path
from typing import Any, cast

from sis_leg_backend.configuracion.errores import (
    ErrorTomlInvalido,
    ErrorValidacionConfiguracion,
)
from sis_leg_backend.configuracion.modelos import ConfiguracionSistema
from sis_leg_backend.configuracion.sonidos_recinto import exigir_sonidos_recinto


def cargar_configuracion_sistema(ruta: Path) -> ConfiguracionSistema:
    """Lee y valida ``system.toml``, y devuelve un snapshot congelado.

    Entradas:
        ruta: ubicación del archivo TOML a cargar.

    Resultado:
        Un ``ConfiguracionSistema`` inmutable e independiente del archivo.

    Errores:
        ``ErrorTomlInvalido`` si el archivo no puede leerse o no es TOML
        válido; ``ErrorValidacionConfiguracion`` si alguna regla técnica del
        esquema canónico se incumple. Ambas fallas son deterministas y
        no dejan estado parcial: la carga nunca confirma una configuración
        inválida.
    """
    try:
        contenido = ruta.read_text(encoding="utf-8")
    except OSError as error:
        # ``FileNotFoundError`` y otros fallos de lectura son subclases de
        # ``OSError``; se reportan como un único error de carga.
        raise ErrorTomlInvalido(
            f"no se pudo leer el archivo de configuración {ruta}: {error}"
        ) from error

    try:
        datos = tomllib.loads(contenido)
    except tomllib.TOMLDecodeError as error:
        raise ErrorTomlInvalido(
            f"el archivo de configuración {ruta} no es TOML válido: {error}"
        ) from error

    session = _exigir_seccion(datos, "session")
    room = _exigir_seccion(datos, "room")
    voting = _exigir_seccion(datos, "voting")
    timers = _exigir_seccion(datos, "timers")
    paths = _exigir_seccion(datos, "paths")

    return ConfiguracionSistema(
        quorum=_exigir_entero_positivo(session, "session.quorum"),
        filas_bancas=_exigir_filas_bancas(room),
        tipos_votacion=_exigir_tipos_votacion(voting),
        device_test_seconds=_exigir_numero_finito_no_negativo(timers, "timers.device_test_seconds"),
        moderacion_revelado_votos_segundos=_exigir_numero_no_negativo(
            timers, "timers.moderation_vote_reveal_seconds"
        ),
        recinto_cuenta_regresiva_inicial_segundos=_exigir_numero_no_negativo(
            timers, "timers.public_initial_countdown_seconds"
        ),
        recinto_resultado_publico_segundos=_exigir_numero_no_negativo(
            timers, "timers.public_result_display_seconds"
        ),
        directorio_registros=_exigir_texto_no_vacio(paths, "paths.logs_dir"),
        # La sección [sonidos] la valida su propio módulo: son quince entradas
        # con reglas propias de ruta y volumen, y ese detalle no pertenece al
        # esquema mínimo de WP-003.
        sonidos_recinto=exigir_sonidos_recinto(datos),
    )


def _exigir_seccion(datos: dict[str, Any], nombre: str) -> dict[str, Any]:
    """Devuelve una sección ``[nombre]`` del TOML o falla si no existe."""
    valor = datos.get(nombre)
    if not isinstance(valor, dict):
        raise ErrorValidacionConfiguracion(f"falta la sección [{nombre}]")
    # ``cast`` aclara a Pyright el tipo exacto del dict proveniente de TOML;
    # el ``isinstance`` anterior ya garantizó que sea un dict real.
    return cast(dict[str, Any], valor)


def _exigir_entero_positivo(seccion: dict[str, Any], clave: str) -> int:
    """Valida una clave entera mayor que cero (regla ``session.quorum``).

    ``clave`` es el nombre canónico completo ("session.quorum") que se usa en
    los mensajes de error; dentro del dict de la sección el campo se llama
    solo "quorum", por eso se toma la parte posterior al punto para buscarlo.

    Se rechazan también los booleanos: en Python ``True`` es una subclase de
    ``int``, y un valor como ``quorum = true`` no debe aceptarse como entero.
    """
    campo = clave.rsplit(".", 1)[1]
    valor = seccion.get(campo)
    if not isinstance(valor, int) or isinstance(valor, bool) or valor <= 0:
        raise ErrorValidacionConfiguracion(f"{clave} debe ser un entero positivo")
    return valor


def _exigir_filas_bancas(room: dict[str, Any]) -> tuple[int, ...]:
    """Valida ``room.rows``: lista no vacía de enteros positivos.

    El resultado se devuelve como ``tuple`` para que el snapshot no contenga
    ninguna colección mutable.
    """
    # Dentro de la sección [room] la clave se llama simplemente "rows"; el
    # nombre completo "room.rows" solo se usa en los mensajes de error.
    valor = room.get("rows")
    if not isinstance(valor, list) or not valor:
        raise ErrorValidacionConfiguracion(
            "room.rows debe ser una lista no vacía de enteros positivos"
        )
    filas: list[int] = []
    for fila in cast(list[Any], valor):
        if not isinstance(fila, int) or isinstance(fila, bool) or fila <= 0:
            raise ErrorValidacionConfiguracion("room.rows debe ser una lista de enteros positivos")
        filas.append(fila)
    return tuple(filas)


def _exigir_tipos_votacion(voting: dict[str, Any]) -> tuple[str, ...]:
    """Valida ``voting.types``: lista no vacía de textos no vacíos.

    Se conserva el texto configurado tal cual (sin recortar espacios), porque
    el contrato solo exige textos no vacíos y preservar el orden; alterar el
    contenido sería una normalización silenciosa no autorizada por el WP.
    """
    # Dentro de la sección [voting] la clave se llama "types".
    valor = voting.get("types")
    if not isinstance(valor, list) or not valor:
        raise ErrorValidacionConfiguracion(
            "voting.types debe ser una lista no vacía de textos no vacíos"
        )
    tipos: list[str] = []
    for tipo in cast(list[Any], valor):
        if not isinstance(tipo, str) or not tipo.strip():
            raise ErrorValidacionConfiguracion(
                "voting.types debe ser una lista de textos no vacíos"
            )
        tipos.append(tipo)
    return tuple(tipos)


def _exigir_numero_no_negativo(seccion: dict[str, Any], clave: str) -> int | float:
    """Valida una clave numérica mayor o igual que cero (temporizadores).

    El WP-003 define los temporizadores como "números no negativos", sin
    restringirlos a enteros: se aceptan tanto ``int`` como ``float`` y se
    conserva el tipo recibido sin conversión silenciosa. Al igual que en
    ``_exigir_entero_positivo``, ``clave`` es el nombre canónico completo
    ("timers.moderation_vote_reveal_seconds") para los mensajes de error, y
    el campo real dentro de la sección es la parte posterior al punto.

    Se rechazan los booleanos (``True`` es subclase de ``int`` en Python y no
    debe aceptarse como número), los negativos y cualquier valor no numérico.
    """
    campo = clave.rsplit(".", 1)[1]
    valor = seccion.get(campo)
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or valor < 0:
        raise ErrorValidacionConfiguracion(f"{clave} debe ser un número no negativo")
    return valor


def _exigir_numero_finito_no_negativo(seccion: dict[str, Any], clave: str) -> int | float:
    """Valida ``device_test_seconds`` sin aceptar ``nan`` ni infinitos.

    Este validador es deliberadamente separado de ``_exigir_numero_no_negativo``.
    Los temporizadores que ya existían en WP-003 conservan su semántica previa;
    la restricción adicional de finitud se aplica únicamente al temporizador de
    test incorporado por WP-006. Los enteros no necesitan pasar por
    ``math.isfinite`` porque todo entero de Python representa un valor finito y
    así también se evita una conversión innecesaria de enteros muy grandes.
    """

    campo = clave.rsplit(".", 1)[1]
    valor = seccion.get(campo)
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise ErrorValidacionConfiguracion(f"{clave} debe ser un número finito no negativo")
    if valor < 0 or (isinstance(valor, float) and not math.isfinite(valor)):
        raise ErrorValidacionConfiguracion(f"{clave} debe ser un número finito no negativo")
    return valor


def _exigir_texto_no_vacio(seccion: dict[str, Any], clave: str) -> str:
    """Valida una clave de texto no vacía (``paths.logs_dir``)."""
    campo = clave.rsplit(".", 1)[1]
    valor = seccion.get(campo)
    if not isinstance(valor, str) or not valor.strip():
        raise ErrorValidacionConfiguracion(f"{clave} debe ser un texto no vacío")
    return valor
