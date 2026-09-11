"""Pruebas de la fuente única de fotografías de banca (WP-098).

Qué se demuestra acá
--------------------

1. una ``ruta_imagen`` válida se acepta y devuelve su nombre de archivo;
2. se rechazan **path traversal**, rutas absolutas y URLs externas, que son las
   tres familias que el WP nombra explícitamente;
3. se rechaza todo lo que no viva directamente bajo ``assets/bancas/``;
4. la resolución en disco encuentra el archivo dentro del directorio de
   configuración y nunca fuera de él, ni siquiera a través de un enlace
   simbólico;
5. un archivo ausente se reporta como recurso no disponible y no como una
   falla técnica.

La importancia de estas reglas es concreta: ``ruta_imagen`` la escribe una
persona en un CSV y termina convertida en una ruta del sistema de archivos del
servidor, que además se publica por HTTP.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sis_leg_backend.configuracion.imagenes_concejales import (
    DIRECTORIO_IMAGENES_CONCEJALES,
    DIRECTORIO_IMAGENES_CONCEJALES_EJEMPLO,
    PREFIJO_RUTA_IMAGEN,
    ErrorRutaImagenInvalida,
    resolver_archivo_imagen_concejal,
    tipo_contenido_imagen,
    validar_nombre_archivo_imagen,
    validar_ruta_imagen_concejal,
)

# Contenido mínimo e irrelevante: estas pruebas verifican rutas, no píxeles.
BYTES_IMAGEN_DE_PRUEBA = b"\x89PNG\r\n\x1a\n-contenido-de-prueba"


# =============================================================================
# 1. Contrato de la ruta declarada en el padrón
# =============================================================================


def test_una_ruta_canonica_es_valida_y_devuelve_su_nombre_de_archivo() -> None:
    """El formato histórico del padrón sigue siendo exactamente el válido."""

    assert validar_ruta_imagen_concejal("assets/bancas/banca-01.png") == "banca-01.png"


@pytest.mark.parametrize(
    "extension",
    [".png", ".jpg", ".jpeg", ".webp", ".PNG"],
)
def test_se_admiten_las_extensiones_de_imagen_declaradas(extension: str) -> None:
    """La comparación de extensión ignora mayúsculas; la lista es cerrada."""

    assert validar_ruta_imagen_concejal(f"{PREFIJO_RUTA_IMAGEN}retrato{extension}")


@pytest.mark.parametrize(
    "ruta_invalida",
    [
        # --- Path traversal en todas sus formas ---
        "assets/bancas/../../../etc/passwd",
        "assets/bancas/..",
        "assets/bancas/../secreto.png",
        "../../etc/passwd",
        "assets/bancas/subdirectorio/banca-01.png",
        # --- Rutas absolutas ---
        "/etc/passwd",
        "/assets/bancas/banca-01.png",
        "//servidor/recurso.png",
        # --- URLs externas ---
        "http://ejemplo.invalid/banca-01.png",
        "https://ejemplo.invalid/banca-01.png",
        "ftp://ejemplo.invalid/banca-01.png",
        "data:image/png;base64,AAAA",
        # --- Separadores de Windows ---
        "assets\\bancas\\banca-01.png",
        "assets/bancas/..\\..\\secreto.png",
        # --- Fuera del prefijo canónico o sin archivo ---
        "assets/sonidos/sesion-abierta.wav",
        "banca-01.png",
        "assets/bancas/",
        "",
        # --- Archivos ocultos y extensiones no admitidas ---
        "assets/bancas/.oculto.png",
        "assets/bancas/banca-01.svg",
        "assets/bancas/banca-01",
    ],
)
def test_se_rechaza_toda_ruta_que_no_cumpla_el_contrato_seguro(ruta_invalida: str) -> None:
    """Cada caso representa una forma real de salirse del directorio o de la API."""

    with pytest.raises(ErrorRutaImagenInvalida):
        validar_ruta_imagen_concejal(ruta_invalida)


def test_se_rechazan_los_caracteres_de_control() -> None:
    """Un NUL puede truncar una ruta a nivel del sistema operativo."""

    with pytest.raises(ErrorRutaImagenInvalida):
        validar_ruta_imagen_concejal("assets/bancas/banca\x0001.png")


def test_el_mensaje_de_error_nombra_la_regla_incumplida() -> None:
    """El diagnóstico tiene que servirle a quien corrige el CSV."""

    with pytest.raises(ErrorRutaImagenInvalida) as excepcion:
        validar_ruta_imagen_concejal("https://ejemplo.invalid/foto.png")
    assert "URL externa" in str(excepcion.value)

    with pytest.raises(ErrorRutaImagenInvalida) as excepcion:
        validar_ruta_imagen_concejal("/opt/fotos/banca-01.png")
    assert "absoluta" in str(excepcion.value)


# =============================================================================
# 2. El nombre suelto que llega por la URL usa exactamente las mismas reglas
# =============================================================================


def test_el_nombre_recibido_por_http_aplica_las_mismas_reglas() -> None:
    """La URL no puede pedir nada que un padrón válido no pudiera declarar."""

    assert validar_nombre_archivo_imagen("banca-01.png") == "banca-01.png"

    for nombre_invalido in ("..", ".oculto.png", "sub/banca-01.png", "banca-01.svg", ""):
        with pytest.raises(ErrorRutaImagenInvalida):
            validar_nombre_archivo_imagen(nombre_invalido)


def test_el_tipo_de_contenido_corresponde_a_la_extension() -> None:
    """El backend devuelve el archivo tal cual, así que debe rotularlo bien."""

    assert tipo_contenido_imagen("banca-01.png") == "image/png"
    assert tipo_contenido_imagen("banca-01.JPG") == "image/jpeg"
    assert tipo_contenido_imagen("banca-01.jpeg") == "image/jpeg"
    assert tipo_contenido_imagen("banca-01.webp") == "image/webp"


# =============================================================================
# 3. Resolución en disco
# =============================================================================


def test_resuelve_el_archivo_dentro_del_directorio_de_configuracion(tmp_path: Path) -> None:
    """El caso normal: la foto existe y se encuentra donde corresponde."""

    directorio = tmp_path / "bancas"
    directorio.mkdir()
    (directorio / "banca-01.png").write_bytes(BYTES_IMAGEN_DE_PRUEBA)

    archivo = resolver_archivo_imagen_concejal("banca-01.png", directorio)

    assert archivo.read_bytes() == BYTES_IMAGEN_DE_PRUEBA


def test_un_archivo_ausente_se_reporta_como_recurso_no_disponible(tmp_path: Path) -> None:
    """Falta la foto: se informa con claridad y sin inventar un archivo vacío."""

    directorio = tmp_path / "bancas"
    directorio.mkdir()

    with pytest.raises(ErrorRutaImagenInvalida) as excepcion:
        resolver_archivo_imagen_concejal("banca-01.png", directorio)
    assert "no existe la fotografía configurada" in str(excepcion.value)


def test_un_directorio_no_se_confunde_con_una_imagen(tmp_path: Path) -> None:
    """``is_file`` descarta directorios: servir uno rompería la respuesta HTTP."""

    directorio = tmp_path / "bancas"
    (directorio / "banca-01.png").mkdir(parents=True)

    with pytest.raises(ErrorRutaImagenInvalida):
        resolver_archivo_imagen_concejal("banca-01.png", directorio)


def test_un_enlace_simbolico_fuera_del_directorio_queda_descartado(tmp_path: Path) -> None:
    """La comprobación de contención se hace sobre rutas ya resueltas.

    Un enlace con nombre válido podría apuntar a cualquier archivo legible por
    el backend. Resolver ambos extremos antes de compararlos es lo que cierra
    esa puerta.
    """

    secreto = tmp_path / "secreto.png"
    secreto.write_bytes(b"contenido que no debe publicarse")
    directorio = tmp_path / "bancas"
    directorio.mkdir()
    try:
        (directorio / "banca-01.png").symlink_to(secreto)
    except OSError:  # pragma: no cover - sistemas sin permiso para enlazar
        pytest.skip("El entorno no permite crear enlaces simbólicos.")

    with pytest.raises(ErrorRutaImagenInvalida) as excepcion:
        resolver_archivo_imagen_concejal("banca-01.png", directorio)
    assert "fuera del directorio de configuración" in str(excepcion.value)


# =============================================================================
# 4. Ubicaciones canónicas declaradas
# =============================================================================


def test_el_directorio_runtime_vive_bajo_config_y_su_plantilla_esta_versionada() -> None:
    """La fuente única es de configuración, no un asset del build de una SPA.

    La plantilla sí está versionada: es el punto de partida reproducible que
    usan desarrollo y las pruebas, y lo que `preparar_config_local` copia a la
    ruta runtime cuando falta un archivo.
    """

    assert Path("config/assets/bancas") == DIRECTORIO_IMAGENES_CONCEJALES
    assert Path("config/assets.example/bancas") == DIRECTORIO_IMAGENES_CONCEJALES_EJEMPLO

    raiz_repositorio = Path(__file__).resolve().parents[1]
    plantilla = raiz_repositorio / DIRECTORIO_IMAGENES_CONCEJALES_EJEMPLO
    assert plantilla.is_dir()
    assert sorted(archivo.name for archivo in plantilla.glob("*.png")) == [
        f"banca-{numero:02d}.png" for numero in range(1, 13)
    ]


def test_ninguna_aplicacion_conserva_una_copia_funcional_de_las_fotos() -> None:
    """El objetivo central de WP-098: una sola ubicación física, no cinco.

    Se comprueba sobre el checkout real porque el defecto que se quiere impedir
    es exactamente que alguien vuelva a dejar un `public/assets/bancas/` dentro
    de una aplicación.
    """

    raiz_repositorio = Path(__file__).resolve().parents[1]
    copias = sorted(
        str(ruta.relative_to(raiz_repositorio))
        for ruta in (raiz_repositorio / "apps").glob("*/public/assets/bancas")
    )
    assert copias == []
