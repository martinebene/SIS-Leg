"""Pruebas de la auditoría de identidad legada (WP-077).

La auditoría es la salvaguarda que impide que el nombre anterior del proyecto vuelva a
entrar sin que nadie lo note. Como cualquier salvaguarda, hace falta comprobar dos cosas
distintas:

1. que hoy el repositorio pase, es decir que el renombrado esté realmente completo;
2. que la auditoría detecte una reintroducción, es decir que no esté aprobando por vacía.

Lo segundo es lo que evita el peor escenario posible: un patrón mal escrito que apruebe
siempre y deje al proyecto sin control real sobre su identidad. Por eso `auditar` acepta un
listado de archivos, una allowlist, un contador, los registros vivos y un lector inyectados:
las pruebas de detección se hacen sobre un repositorio sintético, sin ensuciar el real.

WP-079 agregó la segunda política, la de los registros históricos vivos, después de que el
gate se rompiera solo al crecer `PLAN.md`. Esa política es más permisiva en cantidad y más
exigente en forma, así que necesita sus dos pruebas espejo: una mención histórica válida
tiene que pasar y una referencia activa copiada en el mismo archivo tiene que fallar. Si
sólo existiera la primera, la excepción sería indistinguible de excluir el archivo.
"""

from __future__ import annotations

import pytest

from scripts.auditar_identidad_legada import (
    ALLOWLIST,
    MARCADORES_DE_CONTEXTO_HISTORICO,
    PATRON_LEGADO,
    RAIZ_REPOSITORIO,
    REGISTROS_HISTORICOS_VIVOS,
    ReferenciaPermitida,
    RegistroHistoricoVivo,
    auditar,
    contar_ocurrencias,
    leer_lineas,
    linea_tiene_contexto_historico,
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


def test_las_excepciones_solo_cubren_archivos_realmente_versionados() -> None:
    """Permitir una ruta no versionada crearía una excepción imposible de revisar."""

    versionados = set(listar_archivos_versionados())
    for entrada in ALLOWLIST:
        assert entrada.ruta in versionados, f"{entrada.ruta} no está versionado."
    for registro in REGISTROS_HISTORICOS_VIVOS:
        assert registro.ruta in versionados, f"{registro.ruta} no está versionado."


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


def test_cada_registro_historico_vivo_existe_y_justifica_su_politica() -> None:
    """Un registro vivo sin motivo sería una exclusión encubierta de ese archivo."""

    for registro in REGISTROS_HISTORICOS_VIVOS:
        ruta = RAIZ_REPOSITORIO / registro.ruta
        assert ruta.exists(), f"Se declara registro vivo {registro.ruta}, que no existe."
        assert registro.motivo.strip(), f"{registro.ruta} no declara por qué es un registro vivo."


def test_ninguna_ruta_usa_las_dos_politicas_a_la_vez() -> None:
    """Las dos reglas se pisarían: la del conteo ganaría y la de forma nunca correría."""

    rutas_con_conteo = {entrada.ruta for entrada in ALLOWLIST}
    rutas_vivas = {registro.ruta for registro in REGISTROS_HISTORICOS_VIVOS}
    assert not rutas_con_conteo & rutas_vivas, "Hay rutas declaradas en las dos políticas."


@pytest.mark.parametrize(
    "linea",
    [
        "La migración de `/opt/botonera2` a `/opt/sis-leg` sigue fuera de este cierre.",
        "| WP-077 | Renombrar Botonera2 a SIS-Leg en el código vigente | INTEGRADO |",
        "Persiste un registro metadata legado vacío de `/workspace/Botonera2`.",
        "El nombre anterior del proyecto era Botonera2.",
        "Referencia histórica a Botonera2 conservada como evidencia.",
    ],
)
def test_reconoce_una_mencion_enmarcada_en_el_pasado(linea: str) -> None:
    """Las formas que ya usa el PLAN vigente deben seguir siendo aceptables."""

    assert linea_tiene_contexto_historico(linea)


@pytest.mark.parametrize(
    "linea",
    [
        "WorkingDirectory=/opt/botonera2",
        "from botonera2_backend.aplicacion import crear_aplicacion",
        "BOTONERA2_BACKEND_URL=http://127.0.0.1:8000",
        "El backend expone `@botonera2/api-client` en el workspace.",
    ],
)
def test_no_reconoce_una_referencia_activa_como_mencion_historica(linea: str) -> None:
    """Sin marco temporal ni identidad vigente, la línea es indistinguible de un uso real."""

    assert not linea_tiene_contexto_historico(linea)


def test_un_registro_vivo_acepta_menciones_historicas_equivalentes_a_las_existentes() -> None:
    """Criterio central de WP-079: la bitácora puede seguir creciendo sin romper el gate."""

    registro = RegistroHistoricoVivo("docs/implementation/PLAN.md", "Bitácora de prueba.")
    lineas = [
        "WP-077 renombró la identidad técnica anterior y quedó INTEGRADO.",
        "La migración de `/opt/botonera2` a `/opt/sis-leg` queda fuera de esta campaña.",
        "Una línea cualquiera sin ninguna identidad involucrada.",
    ]

    problemas = auditar(
        archivos=[registro.ruta],
        permitidas=(),
        registros_vivos=(registro,),
        lector=lambda _ruta: lineas,
    )

    assert problemas == []


def test_un_registro_vivo_rechaza_una_referencia_activa_nueva() -> None:
    """La excepción es de cantidad, no de contenido: una ruta activa copiada sigue fallando."""

    registro = RegistroHistoricoVivo("docs/implementation/PLAN.md", "Bitácora de prueba.")
    lineas = [
        "La migración de `/opt/botonera2` a `/opt/sis-leg` queda fuera de esta campaña.",
        "WorkingDirectory=/opt/botonera2",
    ]

    problemas = auditar(
        archivos=[registro.ruta],
        permitidas=(),
        registros_vivos=(registro,),
        lector=lambda _ruta: lineas,
    )

    assert len(problemas) == 1
    assert "sin marco histórico" in problemas[0]


def test_el_problema_de_un_registro_vivo_ubica_la_linea_exacta() -> None:
    """Un mensaje sin número de línea obligaría a buscar el literal a mano en la CI."""

    registro = RegistroHistoricoVivo("docs/implementation/PLAN.md", "Bitácora de prueba.")
    lineas = ["Primera línea sin nada.", "Segunda línea sin nada.", "/opt/botonera2"]

    problemas = auditar(
        archivos=[registro.ruta],
        permitidas=(),
        registros_vivos=(registro,),
        lector=lambda _ruta: lineas,
    )

    assert len(problemas) == 1
    assert problemas[0].startswith("docs/implementation/PLAN.md:3:")
    assert "/opt/botonera2" in problemas[0]


def test_rechaza_un_registro_vivo_sin_motivo_declarado() -> None:
    """Igual que en la allowlist, una excepción sin justificación no puede caducar."""

    registro = RegistroHistoricoVivo("docs/ejemplo.md", "  ")

    problemas = auditar(
        archivos=[],
        permitidas=(),
        registros_vivos=(registro,),
        lector=lambda _ruta: [],
    )

    assert any("no declara motivo" in problema for problema in problemas)


def test_rechaza_una_ruta_declarada_en_las_dos_politicas() -> None:
    """Detecta el error de política antes de que una regla anule silenciosamente a la otra."""

    permitida = ReferenciaPermitida("docs/ejemplo.md", 1, "Motivo de prueba.")
    registro = RegistroHistoricoVivo("docs/ejemplo.md", "Motivo de prueba.")

    problemas = auditar(
        archivos=[],
        permitidas=(permitida,),
        registros_vivos=(registro,),
        lector=lambda _ruta: [],
    )

    assert any("elegí una sola política" in problema for problema in problemas)


def test_el_vocabulario_de_marcadores_se_mantiene_acotado() -> None:
    """Cada término agregado debilita el gate; el crecimiento debe ser una decisión visible."""

    assert len(MARCADORES_DE_CONTEXTO_HISTORICO) <= 12
    assert all(marcador == marcador.lower() for marcador in MARCADORES_DE_CONTEXTO_HISTORICO)


def test_leer_lineas_tolera_binarios_y_rutas_inexistentes() -> None:
    """El recorrido por líneas comparte el criterio tolerante del contador."""

    assert leer_lineas("assets/branding/sisleg-logo.png") == []
    assert leer_lineas("archivo/que/no/existe.txt") == []
