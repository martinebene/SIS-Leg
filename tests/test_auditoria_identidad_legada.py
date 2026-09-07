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
    PALABRAS_DE_CONTEXTO_HISTORICO,
    PATRON_LEGADO,
    PREPOSICIONES_DE_PERTENENCIA,
    RAIZ_REPOSITORIO,
    REGISTROS_HISTORICOS_VIVOS,
    ReferenciaPermitida,
    RegistroHistoricoVivo,
    auditar,
    contar_ocurrencias,
    leer_lineas,
    linea_tiene_contexto_historico,
    listar_archivos_versionados,
    menciones_sin_marco_historico,
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
        "El nombre anterior de Botonera2 quedó documentado.",
        "Referencia histórica de Botonera2 conservada como evidencia.",
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
    assert "no viene enmarcada como historia" in problemas[0]


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
    assert problemas[0].startswith("docs/implementation/PLAN.md:3:1:")
    assert "«/opt/botonera2»" in problemas[0]


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


def test_el_vocabulario_historico_se_mantiene_acotado_y_en_palabras_completas() -> None:
    """Cada término agregado debilita el gate; el crecimiento debe ser una decisión visible."""

    assert len(PALABRAS_DE_CONTEXTO_HISTORICO) <= 32
    assert len(PREPOSICIONES_DE_PERTENENCIA) <= 4
    for palabra in PALABRAS_DE_CONTEXTO_HISTORICO + PREPOSICIONES_DE_PERTENENCIA:
        assert palabra == palabra.lower(), f"{palabra} debería estar en minúsculas."
        assert " " not in palabra, f"{palabra} no es una palabra suelta."


def test_leer_lineas_tolera_binarios_y_rutas_inexistentes() -> None:
    """El recorrido por líneas comparte el criterio tolerante del contador."""

    assert leer_lineas("assets/branding/sisleg-logo.png") == []
    assert leer_lineas("archivo/que/no/existe.txt") == []


# Los nueve contraejemplos que el gate llegó a dejar pasar, en tres tandas. Están escritos
# literalmente, no parafraseados, porque son la regresión exacta que este WP corrige.
#
# Los tres primeros venían de la versión que comparaba subcadenas: una raíz suelta que
# colisiona con lenguaje general (`delegado` contra `legado`), un `anterior` que califica
# cualquier cosa menos la identidad, y la sola presencia del nombre vigente en una
# instrucción activa.
#
# Los tres del medio venían de la versión que ya usaba palabras completas pero preguntaba por
# la línea entera: la palabra histórica está, pero califica otra cosa y la ruta legada es el
# objeto de un verbo en presente.
#
# Los tres últimos venían de la transición desnuda: nombran las dos identidades unidas por
# una preposición, pero describen dos sistemas conviviendo, no uno reemplazado por el otro.
# Son la razón por la que la transición quedó limitada a flechas.
CONTRAEJEMPLOS_QUE_DEBEN_FALLAR = [
    "El concejal delegado solicitó acceso a /opt/botonera2",
    "Como se indicó en la sección anterior, el servicio arranca con /opt/botonera2/bin/start",
    "Para desplegar sis-leg, ejecutar /opt/botonera2/bin/start",
    "Para migrar la base de datos, ejecutar /opt/botonera2/bin/start",
    "El sistema legado de expedientes usa /opt/botonera2/bin/start",
    "Durante la migración de usuarios, ejecutar /opt/botonera2/bin/start",
    "Usar Botonera2 por compatibilidad con SIS-Leg",
    "Conectar Botonera2 a SIS-Leg",
    "Redirigir Botonera2 hacia SIS-Leg",
]


@pytest.mark.parametrize("linea", CONTRAEJEMPLOS_QUE_DEBEN_FALLAR)
def test_no_acepta_los_falsos_negativos_conocidos(linea: str) -> None:
    """Regresión exacta: estas tres líneas son referencias activas, no historia."""

    assert not linea_tiene_contexto_historico(linea)


@pytest.mark.parametrize("linea", CONTRAEJEMPLOS_QUE_DEBEN_FALLAR)
def test_un_registro_vivo_rechaza_los_falsos_negativos_conocidos(linea: str) -> None:
    """La misma regresión, comprobada de punta a punta a través de la auditoría."""

    registro = RegistroHistoricoVivo("docs/implementation/PLAN.md", "Bitácora de prueba.")

    problemas = auditar(
        archivos=[registro.ruta],
        permitidas=(),
        registros_vivos=(registro,),
        lector=lambda _ruta: [linea],
    )

    assert len(problemas) == 1
    assert "no viene enmarcada como historia" in problemas[0]


@pytest.mark.parametrize(
    "linea",
    [
        "Se conserva el nombre anterior de Botonera2 por trazabilidad.",
        "Quedan las rutas anteriores de Botonera2 documentadas en el runbook.",
        "La identidad técnica anterior de Botonera2 se retiró en WP-077.",
    ],
)
def test_acepta_anterior_cuando_queda_ligado_a_la_mencion(linea: str) -> None:
    """`anterior` vale cuando la mención cuelga de él, no cuando sólo comparte la línea."""

    assert linea_tiene_contexto_historico(linea)


@pytest.mark.parametrize(
    "linea",
    [
        "Como se indicó en la sección anterior revisar /opt/botonera2/bin/start",
        "El punto anterior ya fue tratado y el servicio usa /opt/botonera2",
        "La votación anterior quedó INCONCLUSA y el runbook apunta a /opt/botonera2",
    ],
)
def test_rechaza_anterior_cuando_no_llega_hasta_la_mencion(linea: str) -> None:
    """Una sección, un punto o una votación previos no dicen nada sobre esta ruta."""

    assert not linea_tiene_contexto_historico(linea)


@pytest.mark.parametrize(
    "linea",
    [
        "El sistema legado usa /opt/botonera2",
        "El sistema legado arranca con /opt/botonera2",
        "La migración quedó pendiente y el servicio escribe en /opt/botonera2/logs",
    ],
)
def test_rechaza_un_verbo_activo_pegado_a_la_mencion(linea: str) -> None:
    """Aunque la palabra histórica esté cerca, un verbo en presente delata un uso actual."""

    assert not linea_tiene_contexto_historico(linea)


@pytest.mark.parametrize(
    ("linea", "admitida"),
    [
        ("Mover `/opt/botonera2` -> `/opt/sis-leg` en la ventana operativa", True),
        ("Mover `/opt/botonera2` → `/opt/sis-leg` en la ventana operativa", True),
        ("Conectar Botonera2 a SIS-Leg", False),
        ("Redirigir Botonera2 hacia SIS-Leg", False),
        ("Usar Botonera2 por compatibilidad con SIS-Leg", False),
        ("Renombrar Botonera2 a SIS-Leg cerró WP-077", True),
        ("La migración física de /opt/botonera2 a /opt/sis-leg sigue pendiente", True),
    ],
)
def test_la_transicion_desnuda_exige_flecha(linea: str, admitida: bool) -> None:
    """Una preposición no distingue un reemplazo de una conexión entre dos sistemas vivos.

    Las dos últimas filas muestran la salida para el texto narrado: siguen admitidas, pero
    por el calificador ligado (`Renombrar`, `migración`), no por la preposición.
    """

    assert linea_tiene_contexto_historico(linea) is admitida


def test_el_marco_no_cruza_la_puntuacion_de_la_clausula() -> None:
    """Misma frase con y sin coma: la coma separa el marco de la mención y cambia el veredicto."""

    assert linea_tiene_contexto_historico("La migración de Botonera2 quedó pendiente")
    assert not linea_tiene_contexto_historico("La migración terminó, revisar /opt/botonera2")


def test_una_linea_sin_menciones_no_tiene_nada_que_justificar() -> None:
    """La fachada responde sobre las menciones que hay; si no hay ninguna, no hay problema."""

    assert linea_tiene_contexto_historico("SIS-Leg no nombra ninguna identidad retirada acá.")
    assert menciones_sin_marco_historico("Una línea cualquiera del PLAN.") == []


def test_cada_mencion_de_una_linea_se_juzga_por_separado() -> None:
    """Una transición correcta no puede tapar a otra mención activa de la misma línea."""

    linea = "Migrar `/opt/botonera2` a `/opt/sis-leg` mientras el runbook usa /opt/botonera2/bin"
    sin_marco = menciones_sin_marco_historico(linea)

    assert len(sin_marco) == 1
    assert sin_marco[0][1] == "/opt/botonera2/bin"


def test_las_lineas_historicas_reales_del_plan_siguen_aceptadas() -> None:
    """La política tiene que seguir admitiendo la evidencia que hoy vive en el PLAN.

    Este test mira el archivo real, no un fixture: si un endurecimiento futuro de la regla
    dejara afuera una de esas líneas, la tentación sería reescribir la historia para volver
    al verde, que es exactamente lo que WP-079 prohíbe.
    """

    ruta = "docs/implementation/PLAN.md"
    historicas = [
        (numero, linea)
        for numero, linea in enumerate(leer_lineas(ruta), start=1)
        if PATRON_LEGADO.search(linea)
    ]

    assert historicas, "El PLAN dejó de contener menciones históricas; revisá la política."
    for numero, linea in historicas:
        assert linea_tiene_contexto_historico(linea), f"{ruta}:{numero} quedó sin marco: {linea}"
