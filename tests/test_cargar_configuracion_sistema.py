"""Pruebas unitarias de carga y validación de ``config/system.toml`` (WP-003).

Cubren cada regla técnica del esquema aprobado (quórum, filas, tipos,
temporizadores y directorio de registros), los errores deterministas de
parseo/lectura y el congelamiento del snapshot frente a cambios del disco.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import (
    LINEA_LOGS,
    LINEA_QUORUM,
    LINEA_ROWS,
    LINEA_TIMER_CUENTA_REGRESIVA,
    LINEA_TIMER_RESULTADO,
    LINEA_TIMER_REVELADO,
    LINEA_TIMER_TEST_DISPOSITIVO,
    LINEA_TYPES,
    TOML_CANONICO,
    escribir_system_toml,
)
from sis_leg_backend.configuracion.cargar_configuracion import cargar_configuracion_sistema
from sis_leg_backend.configuracion.errores import ErrorTomlInvalido, ErrorValidacionConfiguracion

# Los cuatro temporizadores configurables de la sección [timers] (WP-086).
# Cada entrada describe, en este orden:
#
#   1. la línea exacta que el TOML canónico de ``conftest`` trae para esa clave
#      y que las pruebas reemplazan para inyectar el valor a ensayar;
#   2. el nombre de la clave dentro de la sección (lo que se escribe en el TOML);
#   3. el nombre canónico completo que debe aparecer en el mensaje de error, de
#      modo que el operador sepa exactamente qué clave corregir;
#   4. el atributo del snapshot ``ConfiguracionSistema`` donde queda el valor.
#
# Tener la lista en un solo lugar permite parametrizar cada regla contra los
# cuatro temporizadores sin repetir casos a mano, y hace que agregar un
# temporizador nuevo obligue a cubrirlo con todas estas pruebas.
TEMPORIZADORES_CONFIGURABLES = (
    (
        LINEA_TIMER_TEST_DISPOSITIVO,
        "device_test_seconds",
        "timers.device_test_seconds",
        "device_test_seconds",
    ),
    (
        LINEA_TIMER_REVELADO,
        "moderation_vote_reveal_seconds",
        "timers.moderation_vote_reveal_seconds",
        "moderacion_revelado_votos_segundos",
    ),
    (
        LINEA_TIMER_CUENTA_REGRESIVA,
        "public_initial_countdown_seconds",
        "timers.public_initial_countdown_seconds",
        "recinto_cuenta_regresiva_inicial_segundos",
    ),
    (
        LINEA_TIMER_RESULTADO,
        "public_result_display_seconds",
        "timers.public_result_display_seconds",
        "recinto_resultado_publico_segundos",
    ),
)

# Literales TOML que producen un ``float`` no finito. TOML los admite como
# sintaxis válida, pero ninguno puede convertirse en una duración real: ``nan``
# hace falsa cualquier comparación y los infinitos describen un temporizador
# que nunca vence.
LITERALES_NO_FINITOS = ("nan", "inf", "+inf", "-inf")

# Valores finitos que deben seguir aceptándose sin conversión silenciosa: el
# cero (temporizador desactivado), un entero y dos decimales.
VALORES_FINITOS_VALIDOS: tuple[tuple[str, int | float, type[int] | type[float]], ...] = (
    ("0", 0, int),
    ("4", 4, int),
    ("0.5", 0.5, float),
    ("1.25", 1.25, float),
)


def test_carga_el_toml_canonico_con_sus_valores_y_tipos(ruta_system_toml_valido: Path) -> None:
    """El TOML canónico carga con todos sus valores y en tipos inmutables."""
    configuracion = cargar_configuracion_sistema(ruta_system_toml_valido)

    assert configuracion.quorum == 7
    assert configuracion.filas_bancas == (3, 4, 5)
    assert configuracion.tipos_votacion == (
        "Ratificación",
        "Despacho OP",
        "Despacho Gob",
        "Despacho AS",
        "Despacho HA",
        "Despacho Eco",
        "Mocion",
        "P. Sobre Tabla",
        "Otro",
    )
    assert configuracion.device_test_seconds == 0.6
    assert type(configuracion.device_test_seconds) is float
    assert configuracion.moderacion_revelado_votos_segundos == 4
    assert configuracion.recinto_cuenta_regresiva_inicial_segundos == 4
    assert configuracion.recinto_resultado_publico_segundos == 6
    assert configuracion.directorio_registros == "logs"
    # ``paths.logs_copy_dir`` no está en el TOML canónico: la copia externa
    # de WP-085 es opcional y no se activa sola.
    assert configuracion.directorio_copia_registros is None
    assert configuracion.capacidad_total == 12

    # Los snapshots no contienen colecciones mutables: nada externo puede
    # alterar el objeto cargado.
    assert isinstance(configuracion.filas_bancas, tuple)
    assert isinstance(configuracion.tipos_votacion, tuple)


@pytest.mark.parametrize(
    ("texto_original", "texto_nuevo", "fragmento"),
    [
        # session.quorum debe ser un entero positivo: cero, negativo, texto
        # y booleano se rechazan (``true`` es ``int`` en Python y debe caer).
        (LINEA_QUORUM, "quorum = 0", "session.quorum"),
        (LINEA_QUORUM, "quorum = -3", "session.quorum"),
        (LINEA_QUORUM, 'quorum = "siete"', "session.quorum"),
        (LINEA_QUORUM, "quorum = true", "session.quorum"),
        # room.rows: lista no vacía de enteros positivos.
        (LINEA_ROWS, "rows = []", "room.rows"),
        (LINEA_ROWS, "rows = [3, 0, 5]", "room.rows"),
        (LINEA_ROWS, 'rows = ["3", 4, 5]', "room.rows"),
        # voting.types: lista no vacía de textos no vacíos.
        (LINEA_TYPES, "types = []", "voting.types"),
        (LINEA_TYPES, 'types = [""]', "voting.types"),
        # Temporizadores: los negativos (enteros o decimales) y los valores no
        # numéricos se rechazan. Los booleanos y los literales no finitos se
        # prueban aparte, clave por clave, en las pruebas de WP-086.
        (
            LINEA_TIMER_REVELADO,
            "moderation_vote_reveal_seconds = -1",
            "timers.moderation_vote_reveal_seconds",
        ),
        (
            LINEA_TIMER_TEST_DISPOSITIVO,
            "device_test_seconds = -1",
            "timers.device_test_seconds",
        ),
        (
            LINEA_TIMER_TEST_DISPOSITIVO,
            'device_test_seconds = "0.6"',
            "timers.device_test_seconds",
        ),
        (
            LINEA_TIMER_REVELADO,
            "moderation_vote_reveal_seconds = -0.5",
            "timers.moderation_vote_reveal_seconds",
        ),
        (
            LINEA_TIMER_CUENTA_REGRESIVA,
            'public_initial_countdown_seconds = "4"',
            "timers.public_initial_countdown_seconds",
        ),
        (
            LINEA_TIMER_RESULTADO,
            "public_result_display_seconds = -6",
            "timers.public_result_display_seconds",
        ),
        # paths.logs_dir: texto no vacío (solo espacios es vacío).
        (LINEA_LOGS, 'logs_dir = "   "', "paths.logs_dir"),
        # paths.logs_copy_dir es opcional (WP-085), pero declararla vacía es una
        # configuración a medio escribir y debe fallar en vez de leerse como
        # "no copiar": el operador creía haber activado la copia externa.
        (LINEA_LOGS, LINEA_LOGS + '\nlogs_copy_dir = ""', "paths.logs_copy_dir"),
        (LINEA_LOGS, LINEA_LOGS + '\nlogs_copy_dir = "   "', "paths.logs_copy_dir"),
        (LINEA_LOGS, LINEA_LOGS + "\nlogs_copy_dir = 7", "paths.logs_copy_dir"),
        # Clave ausente dentro de la sección presente.
        (LINEA_QUORUM, "", "session.quorum"),
        (LINEA_TIMER_TEST_DISPOSITIVO, "", "timers.device_test_seconds"),
        # Sección completa ausente.
        ("[session]\n" + LINEA_QUORUM + "\n", "", "session"),
    ],
)
def test_rechaza_configuracion_invalida(
    tmp_path: Path, texto_original: str, texto_nuevo: str, fragmento: str
) -> None:
    """Cada variante inválida del TOML se rechaza con un error determinista."""
    ruta = escribir_system_toml(
        tmp_path / "system.toml", TOML_CANONICO.replace(texto_original, texto_nuevo)
    )

    with pytest.raises(ErrorValidacionConfiguracion, match=fragmento):
        cargar_configuracion_sistema(ruta)


def test_rechaza_toml_con_sintaxis_invalida(tmp_path: Path) -> None:
    """Un archivo que no es TOML válido lanza ErrorTomlInvalido."""
    ruta = escribir_system_toml(tmp_path / "system.toml", "[session\nquorum = 7")

    with pytest.raises(ErrorTomlInvalido, match="TOML"):
        cargar_configuracion_sistema(ruta)


def test_rechaza_archivo_inexistente(tmp_path: Path) -> None:
    """Un archivo que no existe se reporta como error de carga, no de reglas."""
    with pytest.raises(ErrorTomlInvalido, match="no se pudo leer"):
        cargar_configuracion_sistema(tmp_path / "no-existe.toml")


def _toml_con_temporizador(linea_original: str, campo: str, literal: str) -> str:
    """Devuelve el TOML canónico con un temporizador reemplazado por ``literal``.

    Aísla el reemplazo textual que comparten todas las pruebas parametrizadas de
    temporizadores: cambia la línea completa de esa clave (``campo = literal``) y
    deja intacto el resto del archivo, de modo que cada caso ejercite una única
    clave inválida o válida por vez.
    """

    return TOML_CANONICO.replace(linea_original, f"{campo} = {literal}")


@pytest.mark.parametrize(
    ("linea_original", "campo", "clave_canonica"),
    [(linea, campo, clave) for linea, campo, clave, _atributo in TEMPORIZADORES_CONFIGURABLES],
    ids=[clave for _linea, _campo, clave, _atributo in TEMPORIZADORES_CONFIGURABLES],
)
@pytest.mark.parametrize("literal", LITERALES_NO_FINITOS)
def test_rechaza_no_finitos_en_todos_los_temporizadores(
    tmp_path: Path, linea_original: str, campo: str, clave_canonica: str, literal: str
) -> None:
    """WP-086: ningún temporizador acepta ``nan``, ``inf``, ``+inf`` ni ``-inf``.

    TOML admite esos literales y ``tomllib`` los entrega como ``float`` no
    finitos. Antes de WP-086 sólo ``device_test_seconds`` los rechazaba, y los
    tres temporizadores de pantalla podían quedar con una duración que nunca
    vence. La prueba recorre las cuatro claves contra los cuatro literales y
    exige además que el mensaje identifique exactamente la clave inválida
    (criterio de aceptación 4).
    """

    ruta = escribir_system_toml(
        tmp_path / "system.toml", _toml_con_temporizador(linea_original, campo, literal)
    )

    with pytest.raises(ErrorValidacionConfiguracion, match=clave_canonica):
        cargar_configuracion_sistema(ruta)


@pytest.mark.parametrize(
    ("linea_original", "campo", "clave_canonica"),
    [(linea, campo, clave) for linea, campo, clave, _atributo in TEMPORIZADORES_CONFIGURABLES],
    ids=[clave for _linea, _campo, clave, _atributo in TEMPORIZADORES_CONFIGURABLES],
)
@pytest.mark.parametrize("literal", ["true", "false"])
def test_rechaza_booleanos_en_todos_los_temporizadores(
    tmp_path: Path, linea_original: str, campo: str, clave_canonica: str, literal: str
) -> None:
    """Los booleanos siguen rechazados en los cuatro temporizadores.

    En Python ``bool`` es subclase de ``int``, así que ``true`` pasaría un
    ``isinstance(valor, int)`` ingenuo. Endurecer la finitud no debía relajar
    esta regla previa, por eso se fija explícitamente para cada clave.
    """

    ruta = escribir_system_toml(
        tmp_path / "system.toml", _toml_con_temporizador(linea_original, campo, literal)
    )

    with pytest.raises(ErrorValidacionConfiguracion, match=clave_canonica):
        cargar_configuracion_sistema(ruta)


@pytest.mark.parametrize(
    ("linea_original", "campo", "atributo"),
    [(linea, campo, atributo) for linea, campo, _clave, atributo in TEMPORIZADORES_CONFIGURABLES],
    ids=[clave for _linea, _campo, clave, _atributo in TEMPORIZADORES_CONFIGURABLES],
)
@pytest.mark.parametrize(
    ("literal", "valor_esperado", "tipo_esperado"),
    VALORES_FINITOS_VALIDOS,
    ids=["cero", "entero-positivo", "decimal-medio", "decimal-positivo"],
)
def test_acepta_cero_y_finitos_en_todos_los_temporizadores(
    tmp_path: Path,
    linea_original: str,
    campo: str,
    atributo: str,
    literal: str,
    valor_esperado: int | float,
    tipo_esperado: type[int] | type[float],
) -> None:
    """El endurecimiento no cambia la semántica de los valores válidos.

    Cero (temporizador desactivado), enteros y decimales finitos siguen
    aceptándose en las cuatro claves, y el snapshot conserva el tipo recibido:
    un ``4`` sigue siendo ``int`` y un ``0.5`` sigue siendo ``float``, sin
    conversión silenciosa (criterio de aceptación 2).
    """

    ruta = escribir_system_toml(
        tmp_path / "system.toml", _toml_con_temporizador(linea_original, campo, literal)
    )

    configuracion = cargar_configuracion_sistema(ruta)

    obtenido = getattr(configuracion, atributo)
    assert obtenido == valor_esperado
    assert type(obtenido) is tipo_esperado


def test_conserva_literal_el_texto_de_los_tipos(tmp_path: Path) -> None:
    """El texto de voting.types se conserva tal cual, sin recortar espacios.

    Fija la decisión de no normalizar silenciosamente valores que el WP solo
    exige como textos no vacíos, preservando el orden configurado.
    """
    ruta = escribir_system_toml(
        tmp_path / "system.toml",
        TOML_CANONICO.replace(LINEA_TYPES, 'types = ["Ratificación ", "Otro"]'),
    )

    configuracion = cargar_configuracion_sistema(ruta)

    assert configuracion.tipos_votacion == ("Ratificación ", "Otro")


def test_cambiar_el_archivo_no_modifica_el_snapshot_ya_cargado(tmp_path: Path) -> None:
    """Congelamiento (CA-059): el disco puede cambiar; el snapshot, no.

    Primero se carga la configuración canónica. Después se reescribe el
    archivo con otro quórum. El objeto ya cargado conserva el valor original
    y una recarga nueva obtiene el nuevo valor: quién carga y cuándo será
    decisión de WP-005.
    """
    ruta = escribir_system_toml(tmp_path / "system.toml", TOML_CANONICO)
    configuracion = cargar_configuracion_sistema(ruta)

    escribir_system_toml(
        ruta,
        TOML_CANONICO.replace(LINEA_QUORUM, "quorum = 11").replace(
            LINEA_TIMER_TEST_DISPOSITIVO, "device_test_seconds = 2.5"
        ),
    )

    assert configuracion.quorum == 7
    assert configuracion.device_test_seconds == 0.6
    recargada = cargar_configuracion_sistema(ruta)
    assert recargada.quorum == 11
    assert recargada.device_test_seconds == 2.5
    assert configuracion.quorum == 7


def test_logs_copy_dir_declarado_se_conserva_tal_cual(tmp_path: Path) -> None:
    """La ruta de copia externa opcional viaja sin normalizar (WP-085).

    No se recortan espacios ni se resuelve la ruta: un destino puede ser
    cualquier cosa que el sistema de archivos acepte, y "corregirlo" sería
    decidir por el operador dónde deja su segunda copia.
    """

    contenido = TOML_CANONICO.replace(
        LINEA_LOGS,
        LINEA_LOGS + '\nlogs_copy_dir = "/mnt/copia-actas"',
    )
    ruta = escribir_system_toml(tmp_path / "system.toml", contenido)

    configuracion = cargar_configuracion_sistema(ruta)

    assert configuracion.directorio_copia_registros == "/mnt/copia-actas"
    # La clave opcional no altera ninguna otra parte del snapshot.
    assert configuracion.directorio_registros == "logs"
