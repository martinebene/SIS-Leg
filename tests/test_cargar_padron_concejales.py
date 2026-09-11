"""Pruebas unitarias de carga y validación de ``config/concejales.csv`` (WP-003).

Cubren el padrón válido, cada condición bloqueante de CA-003 (campos vacíos,
duplicados, bancas inválidas, ``ruta_imagen`` insegura), el rechazo del
encabezado histórico con ``presente``, la correspondencia exacta
padrón/disposición (RN-CON-04) y el congelamiento del snapshot.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import (
    ENCABEZADO_CANONICO,
    configuracion_de_prueba,
    escribir_padron,
    filas_padron_valido,
)
from sis_leg_backend.configuracion.cargar_padron import cargar_padron_concejales
from sis_leg_backend.configuracion.errores import ErrorPadronInvalido

# Plantillas versionadas que deben permanecer coherentes entre sí. Desde
# WP-073 los archivos operativos (`config/system.toml`, `config/concejales.csv`
# y `services/device-bridge/config/devices.json`) están ignorados por Git y
# pueden no existir en un clon nuevo, así que las pruebas de coherencia se
# ejercen sobre los `*.example.*`, que son el contenido que la revisión ve.
# Se resuelven desde la raíz del repositorio para que los tests no dependan
# del directorio desde el que se invoca pytest.
RAIZ_REPOSITORIO = Path(__file__).parents[1]
RUTA_PADRON_REPO = RAIZ_REPOSITORIO / "config" / "concejales.example.csv"
RUTA_TOML_REPO = RAIZ_REPOSITORIO / "config" / "system.example.toml"
RUTA_DISPOSITIVOS_REPO = (
    RAIZ_REPOSITORIO / "services" / "device-bridge" / "config" / "devices.example.json"
)


def test_carga_el_padron_valido_con_sus_asociaciones(ruta_padron_valido: Path) -> None:
    """El padrón canónico de 12 concejales carga completo y congelado."""
    padron = cargar_padron_concejales(ruta_padron_valido, configuracion_de_prueba())

    assert len(padron.concejales) == 12
    assert isinstance(padron.concejales, tuple)

    # El DNI es identidad textual (RN-CON-01): se conserva como texto.
    primero = padron.concejales[0]
    assert primero.dni == "30000001"
    assert primero.nombre == "Ana"
    assert primero.apellido == "Garcia"
    assert primero.bloque == "Bloque 1"
    assert primero.banca == 1
    assert primero.dispositivo_votacion == "D-01"
    assert primero.ruta_imagen == "assets/bancas/banca-01.png"

    # El orden de las filas se preserva (RN-CON-04 y disposición).
    assert [concejal.banca for concejal in padron.concejales] == list(range(1, 13))
    assert [concejal.dispositivo_votacion for concejal in padron.concejales] == [
        f"D-{numero:02d}" for numero in range(1, 13)
    ]

    # La ruta de imagen queda disponible por concejal, sin hardcode por banca.
    assert padron.concejales[11].ruta_imagen == "assets/bancas/banca-12.png"


def test_acepta_bloque_vacio(ruta_padron_valido: Path) -> None:
    """El bloque vacío es válido (CA-003): las filas 5 y 9 no tienen bloque."""
    padron = cargar_padron_concejales(ruta_padron_valido, configuracion_de_prueba())

    assert padron.concejales[4].bloque == ""
    assert padron.concejales[8].bloque == ""


@pytest.mark.parametrize(
    "encabezado",
    [
        ENCABEZADO_CANONICO.split(",") + ["presente"],
        ENCABEZADO_CANONICO.split(",")[:-1],
        ["dni", "nombre", "apellido", "bloque", "banca", "ruta_imagen", "dispositivo_votacion"],
        ["DNI", "Nombre", "Apellido", "Bloque", "Banca", "Dispositivo", "Ruta"],
    ],
    ids=[
        "con-presente-historico",
        "columna-faltante",
        "columnas-reordenadas",
        "mayusculas-distintas",
    ],
)
def test_rechaza_encabezado_distinto_del_canonico(tmp_path: Path, encabezado: list[str]) -> None:
    """El encabezado debe ser exactamente el canónico.

    El formato histórico con ``presente`` no se acepta silenciosamente como
    el nuevo contrato: tampoco columnas faltantes, reordenadas o renombradas.
    """
    ruta = escribir_padron(tmp_path / "padron.csv", filas_padron_valido(), encabezado=encabezado)

    with pytest.raises(ErrorPadronInvalido, match="encabezado"):
        cargar_padron_concejales(ruta, configuracion_de_prueba())


def test_rechaza_fila_con_cantidad_incorrecta_de_columnas(tmp_path: Path) -> None:
    """Una fila con más columnas que el encabezado se rechaza por integridad."""
    filas = filas_padron_valido()
    filas[3].append("columna-extra")
    ruta = escribir_padron(tmp_path / "padron.csv", filas)

    with pytest.raises(ErrorPadronInvalido, match="columnas"):
        cargar_padron_concejales(ruta, configuracion_de_prueba())


@pytest.mark.parametrize(
    ("indice_columna", "valor_invalido", "fragmento"),
    [
        (0, "", "dni"),
        (1, "", "nombre"),
        (2, "", "apellido"),
        (4, "", "banca"),
        (4, "abc", "banca"),
        (4, "0", "entero positivo"),
        (4, "-2", "entero positivo"),
        (5, "", "dispositivo"),
        (6, "", "ruta_imagen"),
        # URLs externas de todos los esquemas (WP-003, endurecido por WP-098).
        (6, "https://servidor-ejemplo.com/logo.png", "URL externa"),
        (6, "http://servidor-ejemplo.com/logo.png", "URL externa"),
        (6, "ftp://servidor-ejemplo.com/logo.png", "URL externa"),
        (6, "//servidor-ejemplo.com/logo.png", "URL externa"),
        (6, "data:image/png;base64,AAAA", "URL externa"),
        # Rutas absolutas: apuntarían fuera de la configuración de la instalación.
        (6, "/etc/passwd", "absoluta"),
        (6, "/assets/bancas/banca-01.png", "absoluta"),
        # Path traversal en sus formas POSIX y de Windows.
        (6, "assets/bancas/../../../etc/passwd", "sin subdirectorios"),
        (6, "assets/bancas/..", "directorio relativo"),
        (6, "..\\..\\secreto.png", "barras invertidas"),
        # Fuera del único directorio admitido, o sin extensión de imagen.
        (6, "assets/sonidos/sesion-abierta.wav", "assets/bancas/"),
        (6, "banca-01.png", "assets/bancas/"),
        (6, "assets/bancas/banca-01.svg", "extensión"),
    ],
    ids=[
        "dni-vacio",
        "nombre-vacio",
        "apellido-vacio",
        "banca-vacia",
        "banca-no-numerica",
        "banca-cero",
        "banca-negativa",
        "dispositivo-vacio",
        "ruta-imagen-vacia",
        "ruta-https",
        "ruta-http",
        "ruta-ftp",
        "ruta-protocolo-relativo",
        "ruta-data-uri",
        "ruta-absoluta-sistema",
        "ruta-absoluta-interna",
        "ruta-traversal",
        "ruta-directorio-relativo",
        "ruta-barra-invertida",
        "ruta-fuera-del-directorio",
        "ruta-sin-prefijo",
        "ruta-extension-no-admitida",
    ],
)
def test_rechaza_fila_con_campo_bloqueante(
    tmp_path: Path, indice_columna: int, valor_invalido: str, fragmento: str
) -> None:
    """Cada condición bloqueante de CA-003 rechaza la carga con mensaje claro.

    El error es determinista e incluye el número de fila para corregir el
    archivo; aquí solo se verifica el fragmento del mensaje.
    """
    filas = filas_padron_valido()
    filas[3][indice_columna] = valor_invalido
    ruta = escribir_padron(tmp_path / "padron.csv", filas)

    with pytest.raises(ErrorPadronInvalido, match=fragmento):
        cargar_padron_concejales(ruta, configuracion_de_prueba())


@pytest.mark.parametrize(
    "indice_columna",
    [0, 4, 5],
    ids=["dni-duplicado", "banca-duplicada", "dispositivo-duplicado"],
)
def test_rechaza_campos_duplicados(tmp_path: Path, indice_columna: int) -> None:
    """DNI, banca y dispositivo de votación deben ser únicos (RN-CON-03).

    La fila 5 (índice 4) adopta el DNI/banca/dispositivo de la fila 4
    (índice 3): el duplicado aparece en orden de filas y se rechaza.
    """
    filas = filas_padron_valido()
    filas[4][indice_columna] = filas[3][indice_columna]
    ruta = escribir_padron(tmp_path / "padron.csv", filas)

    with pytest.raises(ErrorPadronInvalido, match="duplicad"):
        cargar_padron_concejales(ruta, configuracion_de_prueba())


def test_rechaza_cantidad_menor_que_la_capacidad(tmp_path: Path) -> None:
    """Menos concejales que la capacidad rompe la correspondencia exacta."""
    ruta = escribir_padron(tmp_path / "padron.csv", filas_padron_valido()[:11])

    with pytest.raises(ErrorPadronInvalido, match="cantidad de concejales"):
        cargar_padron_concejales(ruta, configuracion_de_prueba())


def test_rechaza_cantidad_mayor_que_la_capacidad(tmp_path: Path) -> None:
    """Con más filas que bancas el padrón siempre es rechazado.

    Con capacidad 12 y 13 filas no existe una combinación de bancas válida:
    o una banca supera la capacidad o se repite. La validación por fila
    alcanza primero y el padrón se rechaza; la regla de cantidad exacta
    (RN-CON-04) queda cubierta junto con unicidad y rango.
    """
    filas = filas_padron_valido()
    filas.append(["30000013", "Nuevo", "Concejal", "", "13", "D-13", "assets/bancas/banca-13.png"])
    ruta = escribir_padron(tmp_path / "padron.csv", filas)

    with pytest.raises(ErrorPadronInvalido):
        cargar_padron_concejales(ruta, configuracion_de_prueba())


def test_rechaza_banca_fuera_de_la_capacidad(tmp_path: Path) -> None:
    """Una banca mayor que la capacidad configurada se rechaza por fila."""
    filas = filas_padron_valido()
    filas[11][4] = "13"
    ruta = escribir_padron(tmp_path / "padron.csv", filas)

    with pytest.raises(ErrorPadronInvalido, match="excede la capacidad"):
        cargar_padron_concejales(ruta, configuracion_de_prueba())


def test_rechaza_hueco_en_la_cobertura_de_bancas(tmp_path: Path) -> None:
    """Un padrón que no cubre todas las bancas se rechaza.

    Con capacidad 3 y bancas 1, 2 y 4 falta la banca 3 y sobra la 4: el hueco
    siempre se observa como fuera de rango (o duplicado), porque con cantidad
    exacta y unicidad la cobertura completa queda garantizada.
    """
    configuracion = configuracion_de_prueba(filas_bancas=(3,))
    filas = filas_padron_valido()[:3]
    filas[2][4] = "4"
    ruta = escribir_padron(tmp_path / "padron.csv", filas)

    with pytest.raises(ErrorPadronInvalido, match="excede la capacidad"):
        cargar_padron_concejales(ruta, configuracion)


def test_rechaza_archivo_inexistente(tmp_path: Path) -> None:
    """Un padrón que no existe se reporta como error de carga."""
    with pytest.raises(ErrorPadronInvalido, match="no se pudo leer"):
        cargar_padron_concejales(tmp_path / "no-existe.csv", configuracion_de_prueba())


def test_cambiar_el_padron_en_disco_no_modifica_el_snapshot_cargado(tmp_path: Path) -> None:
    """Congelamiento del padrón (RN-CON-07 y CA-059).

    Se carga el padrón, se reescribe el archivo con otro DNI en la primera
    fila y el snapshot conserva sus valores originales; una recarga nueva
    obtiene los valores actualizados.
    """
    ruta = escribir_padron(tmp_path / "padron.csv", filas_padron_valido())
    padron = cargar_padron_concejales(ruta, configuracion_de_prueba())

    filas_nuevas = filas_padron_valido()
    filas_nuevas[0][0] = "99999999"
    escribir_padron(ruta, filas_nuevas)

    assert padron.concejales[0].dni == "30000001"
    padron_recargado = cargar_padron_concejales(ruta, configuracion_de_prueba())
    assert padron_recargado.concejales[0].dni == "99999999"
    assert padron.concejales[0].dni == "30000001"


def test_los_archivos_canonicos_del_repositorio_cargan_juntos() -> None:
    """La configuración y el padrón de instalación cumplen su contrato.

    Este test integra las dos cargas: la plantilla versionada
    ``config/system.example.toml`` y el padrón de ``config/concejales.example.csv``
    deben ser compatibles entre sí y conservar exactamente las identidades,
    bancas y asociaciones lógicas que la plantilla declara.

    Desde WP-084 esas identidades son **ficticias**. Hasta entonces la plantilla
    reproducía el padrón real recuperado de producción para WP-043, con nombres
    de personas y bloques políticos de una localidad concreta. Eso ataba la
    plantilla versionada a una única institución y publicaba datos personales
    reales en el repositorio; el contrato del archivo no cambió, sólo su
    contenido de ejemplo. El padrón operativo de cada instalación sigue viviendo
    en ``config/concejales.csv``, que no se versiona.
    """
    from sis_leg_backend.configuracion.cargar_configuracion import cargar_configuracion_sistema

    configuracion = cargar_configuracion_sistema(RUTA_TOML_REPO)
    padron = cargar_padron_concejales(RUTA_PADRON_REPO, configuracion)

    assert configuracion.capacidad_total == 12
    assert len(padron.concejales) == 12
    assert [
        (
            concejal.dni,
            concejal.nombre,
            concejal.apellido,
            concejal.bloque,
            concejal.banca,
            concejal.dispositivo_votacion,
            concejal.ruta_imagen,
        )
        for concejal in padron.concejales
    ] == [
        (
            "30000001",
            "Amparo",
            "Bermudez",
            "Bloque Ejemplo A",
            1,
            "dev01",
            "assets/bancas/banca-01.png",
        ),
        (
            "30000002",
            "Bautista",
            "Calvete",
            "Bloque Ejemplo B",
            2,
            "dev02",
            "assets/bancas/banca-02.png",
        ),
        (
            "30000003",
            "Celeste",
            "Dorrego",
            "Bloque Ejemplo C",
            3,
            "dev03",
            "assets/bancas/banca-03.png",
        ),
        (
            "30000004",
            "Damian",
            "Escalante",
            "Bloque Ejemplo A",
            4,
            "dev04",
            "assets/bancas/banca-04.png",
        ),
        (
            "30000005",
            "Emilia",
            "Ferreyra",
            "Bloque Ejemplo A",
            5,
            "dev05",
            "assets/bancas/banca-05.png",
        ),
        (
            "30000006",
            "Fabricio",
            "Gaitan",
            "Bloque Ejemplo A",
            6,
            "dev06",
            "assets/bancas/banca-06.png",
        ),
        (
            "30000007",
            "Graciela",
            "Hernandez",
            "Bloque Ejemplo B",
            7,
            "dev07",
            "assets/bancas/banca-07.png",
        ),
        (
            "30000008",
            "Horacio",
            "Iriarte",
            "Bloque Ejemplo B",
            8,
            "dev08",
            "assets/bancas/banca-08.png",
        ),
        (
            "30000009",
            "Isabel",
            "Jauregui",
            "Bloque Ejemplo B",
            9,
            "dev09",
            "assets/bancas/banca-09.png",
        ),
        (
            "30000010",
            "Joaquin",
            "Larrosa",
            "Bloque Ejemplo B",
            10,
            "dev10",
            "assets/bancas/banca-10.png",
        ),
        (
            "30000011",
            "Leandro",
            "Miranda",
            "Bloque Ejemplo C",
            11,
            "dev11",
            "assets/bancas/banca-11.png",
        ),
        (
            "30000012",
            "Mariela",
            "Novoa",
            "Bloque Ejemplo C",
            12,
            "dev12",
            "assets/bancas/banca-12.png",
        ),
    ]


def test_las_imagenes_del_padron_existen_en_la_plantilla_de_configuracion() -> None:
    """Cada ruta del padrón de ejemplo tiene su PNG en la única fuente versionada.

    ``ruta_imagen`` es autoritativa: el test usa literalmente el valor del
    CSV en vez de reconstruir un nombre de archivo a partir de la banca.

    Hasta WP-097 este test miraba `apps/moderacion/public` y `apps/recinto/public`
    porque cada aplicación llevaba su propia copia. WP-098 eliminó esas copias:
    la plantilla versionada es ahora `config/assets.example/bancas/`, y de ahí
    sale —sin sobrescribir nada— el directorio runtime `config/assets/bancas/`
    que el backend publica para las cuatro superficies.
    """
    from sis_leg_backend.configuracion.cargar_configuracion import cargar_configuracion_sistema
    from sis_leg_backend.configuracion.imagenes_concejales import (
        DIRECTORIO_IMAGENES_CONCEJALES_EJEMPLO,
        validar_ruta_imagen_concejal,
    )

    configuracion = cargar_configuracion_sistema(RUTA_TOML_REPO)
    padron = cargar_padron_concejales(RUTA_PADRON_REPO, configuracion)
    plantilla = RAIZ_REPOSITORIO / DIRECTORIO_IMAGENES_CONCEJALES_EJEMPLO

    for concejal in padron.concejales:
        nombre_archivo = validar_ruta_imagen_concejal(concejal.ruta_imagen)
        ruta_plantilla = plantilla / nombre_archivo
        assert ruta_plantilla.is_file(), f"Falta la foto de referencia: {ruta_plantilla}"


def test_los_dispositivos_logicos_del_padron_coinciden_con_el_bridge() -> None:
    """El padrón y el bridge exponen exactamente los mismos ``dev01..dev12``.

    La comparación solo verifica la frontera lógica: los fingerprints físicos
    continúan siendo responsabilidad exclusiva de ``devices.json``.
    """
    from sis_leg_backend.configuracion.cargar_configuracion import cargar_configuracion_sistema

    configuracion = cargar_configuracion_sistema(RUTA_TOML_REPO)
    padron = cargar_padron_concejales(RUTA_PADRON_REPO, configuracion)
    dispositivos_bridge = json.loads(RUTA_DISPOSITIVOS_REPO.read_text(encoding="utf-8"))

    assert set(dispositivos_bridge.values()) == {
        concejal.dispositivo_votacion for concejal in padron.concejales
    }
