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
        # Temporizadores: números no negativos; los negativos (enteros o
        # decimales), los booleanos y los no numéricos se rechazan para las
        # tres claves.
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
            "device_test_seconds = true",
            "timers.device_test_seconds",
        ),
        (
            LINEA_TIMER_TEST_DISPOSITIVO,
            'device_test_seconds = "0.6"',
            "timers.device_test_seconds",
        ),
        # Los literales especiales de TOML producen floats no finitos y no
        # pueden convertirse en expiraciones válidas del test visual.
        (
            LINEA_TIMER_TEST_DISPOSITIVO,
            "device_test_seconds = nan",
            "timers.device_test_seconds",
        ),
        (
            LINEA_TIMER_TEST_DISPOSITIVO,
            "device_test_seconds = inf",
            "timers.device_test_seconds",
        ),
        (
            LINEA_TIMER_TEST_DISPOSITIVO,
            "device_test_seconds = +inf",
            "timers.device_test_seconds",
        ),
        (
            LINEA_TIMER_TEST_DISPOSITIVO,
            "device_test_seconds = -inf",
            "timers.device_test_seconds",
        ),
        (
            LINEA_TIMER_REVELADO,
            "moderation_vote_reveal_seconds = -0.5",
            "timers.moderation_vote_reveal_seconds",
        ),
        (
            LINEA_TIMER_REVELADO,
            "moderation_vote_reveal_seconds = true",
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


def test_acepta_temporizador_en_cero(tmp_path: Path) -> None:
    """Cero es un valor permitido para los temporizadores (no negativo)."""
    ruta = escribir_system_toml(
        tmp_path / "system.toml",
        TOML_CANONICO.replace(LINEA_TIMER_CUENTA_REGRESIVA, "public_initial_countdown_seconds = 0"),
    )

    configuracion = cargar_configuracion_sistema(ruta)

    assert configuracion.recinto_cuenta_regresiva_inicial_segundos == 0


@pytest.mark.parametrize(
    ("texto_timer", "valor_esperado", "tipo_esperado"),
    [("device_test_seconds = 0", 0, int), ("device_test_seconds = 1.25", 1.25, float)],
    ids=["cero", "decimal-positivo"],
)
def test_acepta_device_test_seconds_no_negativo(
    tmp_path: Path,
    texto_timer: str,
    valor_esperado: int | float,
    tipo_esperado: type[int] | type[float],
) -> None:
    """El temporizador de test admite cero y decimales sin convertir el tipo."""

    ruta = escribir_system_toml(
        tmp_path / "system.toml", TOML_CANONICO.replace(LINEA_TIMER_TEST_DISPOSITIVO, texto_timer)
    )

    configuracion = cargar_configuracion_sistema(ruta)

    assert configuracion.device_test_seconds == valor_esperado
    assert type(configuracion.device_test_seconds) is tipo_esperado


@pytest.mark.parametrize(
    ("texto_timer", "valor_esperado", "tipo_esperado"),
    [
        ("moderation_vote_reveal_seconds = 0", 0, int),
        ("moderation_vote_reveal_seconds = 4", 4, int),
        ("moderation_vote_reveal_seconds = 0.5", 0.5, float),
        ("moderation_vote_reveal_seconds = 1.5", 1.5, float),
    ],
    ids=["cero", "entero-positivo", "decimal-medio", "decimal-positivo"],
)
def test_acepta_temporizadores_no_negativos(
    tmp_path: Path,
    texto_timer: str,
    valor_esperado: int | float,
    tipo_esperado: type[int] | type[float],
) -> None:
    """Los temporizadores aceptan enteros y decimales no negativos.

    El tipo recibido se conserva sin conversión silenciosa: un ``4`` sigue
    siendo ``int`` y un ``0.5`` sigue siendo ``float`` en el snapshot.
    """
    ruta = escribir_system_toml(
        tmp_path / "system.toml", TOML_CANONICO.replace(LINEA_TIMER_REVELADO, texto_timer)
    )

    configuracion = cargar_configuracion_sistema(ruta)

    obtenido = configuracion.moderacion_revelado_votos_segundos
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
