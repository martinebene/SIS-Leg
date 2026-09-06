"""Pruebas de la auditoría de identidad legada (WP-077).

La auditoría es la salvaguarda que impide que el nombre anterior del proyecto vuelva a
entrar sin que nadie lo note. Como cualquier salvaguarda, hace falta comprobar dos cosas
distintas:

1. que hoy el repositorio pase, es decir que el renombrado esté realmente completo;
2. que la auditoría detecte una reintroducción, es decir que no esté aprobando por vacía.

Lo segundo es lo que evita el peor escenario posible: un patrón mal escrito que apruebe
siempre y deje al proyecto sin control real sobre su identidad. Por eso `auditar` acepta un
listado de archivos, una allowlist y un contador inyectados: las pruebas de detección se
hacen sobre un repositorio sintético, sin ensuciar el real.
"""

from __future__ import annotations

import pytest

from scripts.auditar_identidad_legada import (
    ALLOWLIST,
    PATRON_LEGADO,
    RAIZ_REPOSITORIO,
    ReferenciaPermitida,
    auditar,
    contar_ocurrencias,
    listar_archivos_versionados,
)


def test_el_repositorio_no_tiene_referencias_activas_al_nombre_legado() -> None:
    """El estado versionado actual debe pasar la auditoría sin excepciones nuevas."""

    problemas = auditar()
    assert not problemas, "Referencias al nombre legado fuera de la allowlist:\n" + "\n".join(
        problemas
    )


def test_cada_entrada_de_la_allowlist_existe_y_justifica_su_excepcion() -> None:
    """Una allowlist sin motivo o con rutas fantasma deja de ser auditable."""

    for entrada in ALLOWLIST:
        ruta = RAIZ_REPOSITORIO / entrada.ruta
        assert ruta.exists(), f"La allowlist declara {entrada.ruta}, que no existe."
        assert entrada.motivo.strip(), f"{entrada.ruta} no declara por qué es una excepción."
        assert entrada.ocurrencias > 0, f"{entrada.ruta} declara cero ocurrencias esperadas."


def test_no_hay_rutas_repetidas_en_la_allowlist() -> None:
    """Dos entradas para la misma ruta harían que una de las dos nunca se aplique."""

    rutas = [entrada.ruta for entrada in ALLOWLIST]
    assert len(rutas) == len(set(rutas)), "Hay rutas duplicadas en la allowlist."


def test_la_allowlist_solo_cubre_archivos_realmente_versionados() -> None:
    """Permitir una ruta no versionada crearía una excepción imposible de revisar."""

    versionados = set(listar_archivos_versionados())
    for entrada in ALLOWLIST:
        assert entrada.ruta in versionados, f"{entrada.ruta} no está versionado."


@pytest.mark.parametrize(
    "texto",
    [
        "from botonera2_backend.aplicacion import crear_aplicacion",
        "import '@botonera2/api-client'",
        "WorkingDirectory=/opt/botonera2",
        "BOTONERA2_BACKEND_URL",
        "martinebene/Botonera2-Control",
    ],
)
def test_el_patron_reconoce_todas_las_formas_del_nombre_legado(texto: str) -> None:
    """Módulo, scope npm, ruta, variable y repositorio deben detectarse por igual."""

    assert PATRON_LEGADO.search(texto) is not None


@pytest.mark.parametrize(
    "texto",
    [
        "martinebene/Botonera",
        "server_name botonera;",
        "Las botoneras acreditan presencia",
        "sis_leg_backend",
    ],
)
def test_el_patron_no_confunde_nombres_que_deben_conservarse(texto: str) -> None:
    """El repositorio histórico y el dispositivo físico no forman parte del renombrado."""

    assert PATRON_LEGADO.search(texto) is None


def test_detecta_una_reintroduccion_en_un_archivo_no_permitido() -> None:
    """El caso que da sentido a la auditoría: identidad vieja donde no corresponde."""

    problemas = auditar(
        archivos=["apps/backend/src/sis_leg_backend/aplicacion.py"],
        permitidas=(),
        contador=lambda _ruta: 1,
    )

    assert len(problemas) == 1
    assert "archivo no permitido" in problemas[0]


def test_detecta_una_ocurrencia_nueva_dentro_de_un_archivo_permitido() -> None:
    """Una allowlist por archivo sin conteo dejaría entrar referencias nuevas gratis."""

    permitida = ReferenciaPermitida("docs/ejemplo.md", 2, "Motivo de prueba.")
    problemas = auditar(
        archivos=["docs/ejemplo.md"],
        permitidas=(permitida,),
        contador=lambda _ruta: 3,
    )

    assert len(problemas) == 1
    assert "se esperaban 2" in problemas[0]


def test_avisa_cuando_la_allowlist_quedo_desactualizada() -> None:
    """Si ya no hacen falta tantas excepciones, la allowlist debe reducirse."""

    permitida = ReferenciaPermitida("docs/ejemplo.md", 2, "Motivo de prueba.")
    problemas = auditar(
        archivos=["docs/ejemplo.md"],
        permitidas=(permitida,),
        contador=lambda _ruta: 1,
    )

    assert len(problemas) == 1
    assert "Actualizá el conteo" in problemas[0]


def test_rechaza_una_excepcion_sin_motivo_declarado() -> None:
    """Una excepción sin justificación no puede revisarse ni caducar."""

    permitida = ReferenciaPermitida("docs/ejemplo.md", 1, "   ")
    problemas = auditar(
        archivos=["docs/ejemplo.md"],
        permitidas=(permitida,),
        contador=lambda _ruta: 1,
    )

    assert any("no declara motivo" in problema for problema in problemas)


def test_contar_ocurrencias_tolera_binarios_y_rutas_inexistentes() -> None:
    """El recorrido no debe romperse por un asset versionado ni por una ruta vieja."""

    assert contar_ocurrencias("assets/branding/sisleg-logo.png") == 0
    assert contar_ocurrencias("archivo/que/no/existe.txt") == 0
