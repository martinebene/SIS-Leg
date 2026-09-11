"""Fixtures y ayudas compartidas para las pruebas de configuración y padrón (WP-003).

Desde WP-101A centraliza además la construcción de ``release.json`` de fantasía,
que varias suites de despliegue necesitan para materializar releases preparadas
capaces de demostrar su identidad de árbol.

Este archivo centraliza tres cosas que los dos archivos de prueba repiten:

- el texto del ``system.toml`` canónico y las líneas que los tests reemplazan
  para fabricar variantes inválidas;
- la construcción del padrón de fantasía de 12 concejales;
- ``configuracion_de_prueba``, que arma una ``ConfiguracionSistema`` directa
  (sin pasar por el TOML) cuando el test solo se ocupa de validar el padrón.

Los datos son ficticios: ningún nombre, DNI, bloque o ruta corresponde a una
persona real (restricción del WP-003 sobre fixtures versionados).
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from sis_leg_backend.configuracion.cargar_configuracion import cargar_configuracion_sistema
from sis_leg_backend.configuracion.modelos import (
    ConfiguracionSistema,
    ConfiguracionSonidosRecinto,
    IdentidadInstitucional,
    SonidoRecinto,
)
from sis_leg_backend.configuracion.sonidos_recinto import EVENTOS_SONIDO_RECINTO

# Encabezado canónico exacto del padrón aprobado en WP-003.
ENCABEZADO_CANONICO = "dni,nombre,apellido,bloque,banca,dispositivo_votacion,ruta_imagen"

# Líneas del system.toml canónico. Se exponen como constantes para que los
# tests armen variantes inválidas con ``replace`` sin duplicar el TOML entero.
LINEA_QUORUM = "quorum = 7"
LINEA_ROWS = "rows = [3, 4, 5]"
LINEA_TYPES = (
    'types = ["Ratificación", "Despacho OP", "Despacho Gob", "Despacho AS", '
    '"Despacho HA", "Despacho Eco", "Mocion", "P. Sobre Tabla", "Otro"]'
)
LINEA_TIMER_TEST_DISPOSITIVO = "device_test_seconds = 0.6"
LINEA_TIMER_REVELADO = "moderation_vote_reveal_seconds = 4"
LINEA_TIMER_CUENTA_REGRESIVA = "public_initial_countdown_seconds = 4"
LINEA_TIMER_RESULTADO = "public_result_display_seconds = 6"
LINEA_LOGS = 'logs_dir = "logs"'
# Sección [institucion] de WP-084. El nombre es de fantasía y suficientemente
# largo como para que una prueba que lo confundiera con otro texto se note.
LINEA_INSTITUCION = 'nombre = "Cuerpo Legislativo de Prueba"'
NOMBRE_INSTITUCIONAL_DE_PRUEBA = "Cuerpo Legislativo de Prueba"

# Sección [sonidos] de WP-065. Se construye a partir del contrato real
# ``EVENTOS_SONIDO_RECINTO`` para que agregar o quitar un evento obligatorio
# rompa las pruebas en lugar de pasar inadvertido. El volumen de cada evento se
# elige determinísticamente dentro de 0..100 y varía entre eventos, de modo que
# una proyección que confundiera dos sonidos sea detectable.
SONIDOS_DE_PRUEBA: tuple[SonidoRecinto, ...] = tuple(
    SonidoRecinto(
        evento=evento,
        ruta=f"assets/sonidos/{evento.replace('_', '-')}.wav",
        volumen=(indice * 7) % 101,
    )
    for indice, evento in enumerate(EVENTOS_SONIDO_RECINTO)
)

LINEAS_SONIDOS = "\n".join(
    f'[sonidos.{sonido.evento}]\nruta = "{sonido.ruta}"\nvolumen = {sonido.volumen}\n'
    for sonido in SONIDOS_DE_PRUEBA
)

TOML_CANONICO = f"""[institucion]
{LINEA_INSTITUCION}

[session]
{LINEA_QUORUM}

[room]
{LINEA_ROWS}

[voting]
{LINEA_TYPES}

[timers]
{LINEA_TIMER_TEST_DISPOSITIVO}
{LINEA_TIMER_REVELADO}
{LINEA_TIMER_CUENTA_REGRESIVA}
{LINEA_TIMER_RESULTADO}

[paths]
{LINEA_LOGS}

{LINEAS_SONIDOS}"""

# Nombres de fantasía para el padrón de prueba. Dos filas dejan el bloque
# vacío (fila 5 y 9) para demostrar que el bloque vacío es válido (CA-003).
NOMBRES_FANTASIA: tuple[tuple[str, str], ...] = (
    ("Ana", "Garcia"),
    ("Bruno", "Martinez"),
    ("Carla", "Rodriguez"),
    ("Diego", "Fernandez"),
    ("Elsa", "Moreno"),
    ("Facundo", "Silva"),
    ("Gisela", "Lopez"),
    ("Hugo", "Alvarez"),
    ("Irene", "Suarez"),
    ("Javier", "Ortiz"),
    ("Laura", "Pereyra"),
    ("Marcos", "Torres"),
)


def manifest_release_de_prueba(sha_commit: str, sha_arbol: str) -> dict[str, Any]:
    """Arma un ``release.json`` canónico para una release de fantasía (WP-101A).

    Entradas:
        sha_commit: commit que la release dice representar; debe coincidir con
            el nombre del directorio ``releases/<SHA>``.
        sha_arbol: árbol Git que la release dice representar.

    Resultado: el manifest completo, con la forma exacta que exige
    ``deploy.herramienta_despliegue.validar_manifest``.

    ¿Por qué vive acá? Porque desde WP-101A la identidad de una release
    preparada se demuestra comparando el marcador contra su ``release.json``, y
    varias suites necesitan materializar releases de fantasía que superen esa
    comprobación. Tenerlo en un solo lugar evita que tres copias del mismo
    manifest se desincronicen del validador canónico.

    Los checksums del inventario son deterministas y **deliberadamente
    ficticios**: se derivan del nombre de cada ruta. El validador canónico no
    mira el filesystem al leer un manifest, así que no hace falta fabricar
    archivos reales para las rutas inventariadas.
    """

    rutas_inventariadas = (
        "app/pyproject.toml",
        "app/uv.lock",
        "app/apps/backend/pyproject.toml",
        "app/services/device-bridge/pyproject.toml",
        "web/moderacion/index.html",
        "web/recinto/index.html",
        "web/simulador/index.html",
        "web/tecnico/index.html",
        "web/zocalo/index.html",
        "web/manual/index.html",
        "deploy/systemd/sis-leg-backend.service",
        "deploy/systemd/sis-leg-device-bridge.service",
        "deploy/nginx/sis-leg.conf",
        "deploy/herramienta_despliegue.py",
        "deploy/validar_configuracion.py",
        "deploy/contrato_configuracion.json",
    )
    return {
        "formato": "sis-leg-release",
        "version_formato": 1,
        "commit_sha": sha_commit,
        "tree_sha": sha_arbol,
        "python": "3.14",
        "spas": {
            "moderacion": "web/moderacion/index.html",
            "recinto": "web/recinto/index.html",
            "simulador": "web/simulador/index.html",
            "tecnico": "web/tecnico/index.html",
            "zocalo": "web/zocalo/index.html",
        },
        "manual": "web/manual/index.html",
        "paquetes_python": ["sis-leg-backend", "sis-leg-device-bridge"],
        "archivos": [
            {
                "ruta": ruta,
                "sha256": hashlib.sha256(ruta.encode("utf-8")).hexdigest(),
                "tamano": len(ruta),
            }
            for ruta in rutas_inventariadas
        ],
    }


def escribir_release_json_de_prueba(release: Path, sha_commit: str, sha_arbol: str) -> Path:
    """Deja el ``release.json`` canónico en la raíz de una release de fantasía."""

    destino = release / "release.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        json.dumps(manifest_release_de_prueba(sha_commit, sha_arbol), sort_keys=True),
        encoding="utf-8",
    )
    return destino


@pytest.fixture
def anyio_backend() -> str:
    """Ejecuta AnyIO sobre asyncio, el loop usado por el runtime de WP-002.

    La fixture vive en el ``conftest.py`` raíz para que las pruebas asíncronas
    del backend y las ayudas de WP-003 compartan un único módulo de pytest. Su
    nombre está impuesto por el plugin externo AnyIO.
    """

    return "asyncio"


def escribir_system_toml(ruta: Path, contenido: str) -> Path:
    """Escribe un ``system.toml`` en ``ruta`` y la devuelve para encadenar."""
    ruta.write_text(contenido, encoding="utf-8")
    return ruta


def escribir_padron(
    ruta: Path,
    filas: list[list[str]],
    *,
    encabezado: list[str] | None = None,
) -> Path:
    """Escribe un CSV de padrón usando ``csv.writer`` (respeta comillas).

    Por defecto usa el encabezado canónico; pasar ``encabezado`` permite
    fabricar archivos con el formato histórico (con ``presente``) o con
    columnas reordenadas para probar su rechazo.
    """
    with ruta.open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.writer(archivo)
        escritor.writerow(encabezado or ENCABEZADO_CANONICO.split(","))
        escritor.writerows(filas)
    return ruta


def filas_padron_valido() -> list[list[str]]:
    """Devuelve 12 filas ficticias válidas para la capacidad canónica (12).

    Cada llamada construye una lista nueva: los tests pueden modificarla sin
    contaminar los demás escenarios.
    """
    filas: list[list[str]] = []
    for numero, (nombre, apellido) in enumerate(NOMBRES_FANTASIA, start=1):
        # El bloque queda vacío en las filas 5 y 9 para probar que es válido.
        bloque = "" if numero in (5, 9) else f"Bloque {((numero - 1) % 3) + 1}"
        filas.append(
            [
                f"3000000{numero}",
                nombre,
                apellido,
                bloque,
                str(numero),
                f"D-{numero:02d}",
                f"assets/bancas/banca-{numero:02d}.png",
            ]
        )
    return filas


def sonidos_de_prueba() -> ConfiguracionSonidosRecinto:
    """Devuelve los quince sonidos de prueba ya envueltos y disponibles."""

    return ConfiguracionSonidosRecinto(sonidos=SONIDOS_DE_PRUEBA)


def configuracion_de_prueba(*, filas_bancas: tuple[int, ...] = (3, 4, 5)) -> ConfiguracionSistema:
    """Construye una configuración válida directamente, sin leer TOML.

    Los tests de padrón no necesitan pasar por ``system.toml``: les alcanza
    esta configuración para conocer la capacidad del recinto.
    """
    return ConfiguracionSistema(
        quorum=7,
        filas_bancas=filas_bancas,
        tipos_votacion=("Ratificación", "Otro"),
        device_test_seconds=0.6,
        moderacion_revelado_votos_segundos=4,
        recinto_cuenta_regresiva_inicial_segundos=4,
        recinto_resultado_publico_segundos=6,
        directorio_registros="logs",
        sonidos_recinto=sonidos_de_prueba(),
        identidad_institucional=IdentidadInstitucional(nombre=NOMBRE_INSTITUCIONAL_DE_PRUEBA),
    )


@pytest.fixture
def ruta_system_toml_valido(tmp_path: Path) -> Path:
    """Escribe el TOML canónico y devuelve su ruta."""
    return escribir_system_toml(tmp_path / "system.toml", TOML_CANONICO)


@pytest.fixture
def configuracion_valida(ruta_system_toml_valido: Path) -> ConfiguracionSistema:
    """Configuración cargada desde el TOML canónico, tal como operaría WP-005."""
    return cargar_configuracion_sistema(ruta_system_toml_valido)


@pytest.fixture
def ruta_padron_valido(tmp_path: Path) -> Path:
    """Escribe el padrón de fantasía completo y devuelve su ruta."""
    return escribir_padron(tmp_path / "concejales.csv", filas_padron_valido())
