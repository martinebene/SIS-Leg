"""Construye el artefacto productivo reproducible de SIS-Leg.

El script copia únicamente entradas declaradas, calcula un inventario SHA-256
de cada archivo y genera un tar sin metadatos variables. La configuración
institucional queda deliberadamente afuera: producción la provisiona en
``/opt/sis-leg/config`` y una release nunca debe reemplazarla.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

RAIZ_REPOSITORIO = Path(__file__).resolve().parents[1]
DIRECTORIO_SALIDA_PREDETERMINADO = RAIZ_REPOSITORIO / "dist" / "produccion"
FORMATO_RELEASE = "sis-leg-release"
VERSION_FORMATO = 1
VERSION_PYTHON = "3.14"


class ErrorEmpaquetado(RuntimeError):
    """Explica un incumplimiento que impide producir un artefacto trazable."""


def ejecutar_git(*argumentos: str, raiz: Path = RAIZ_REPOSITORIO) -> str:
    """Ejecuta una consulta Git sin shell y devuelve su salida normalizada."""

    resultado = subprocess.run(
        ["git", *argumentos],
        cwd=raiz,
        check=True,
        capture_output=True,
        text=True,
    )
    return resultado.stdout.strip()


def exigir_checkout_limpio(raiz: Path = RAIZ_REPOSITORIO) -> None:
    """Impide atribuir al SHA archivos locales que Git todavía no identifica."""

    estado = ejecutar_git("status", "--porcelain", "--untracked-files=normal", raiz=raiz)
    if estado:
        raise ErrorEmpaquetado(
            "El checkout contiene cambios versionables. Creá el commit candidato antes de "
            "empaquetar para que el artefacto corresponda exactamente a su SHA."
        )


def sha256_archivo(ruta: Path) -> str:
    """Calcula SHA-256 en bloques para no cargar archivos grandes en memoria."""

    calculador = hashlib.sha256()
    with ruta.open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
            calculador.update(bloque)
    return calculador.hexdigest()


def copiar_archivo(origen: Path, destino: Path) -> None:
    """Copia un archivo regular y crea antes su directorio de destino."""

    if not origen.is_file() or origen.is_symlink():
        raise ErrorEmpaquetado(f"La entrada requerida no es un archivo regular: {origen}")
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(origen, destino)


def copiar_arbol_runtime(origen: Path, destino: Path) -> None:
    """Copia fuentes runtime rechazando enlaces y residuos de desarrollo."""

    if not origen.is_dir():
        raise ErrorEmpaquetado(f"No existe el directorio runtime requerido: {origen}")
    for ruta in sorted(origen.rglob("*")):
        relativa = ruta.relative_to(origen)
        if any(parte in {"__pycache__", ".pytest_cache", ".venv"} for parte in relativa.parts):
            continue
        if ruta.is_symlink():
            raise ErrorEmpaquetado(f"No se permiten enlaces en las fuentes runtime: {ruta}")
        if ruta.is_file():
            copiar_archivo(ruta, destino / relativa)


def copiar_salida_spa(origen: Path, destino: Path, nombre: str) -> None:
    """Copia una SPA compilada después de comprobar su estructura mínima."""

    if not (origen / "index.html").is_file() or not (origen / "_nuxt").is_dir():
        raise ErrorEmpaquetado(
            f"La salida estática de {nombre} está incompleta en {origen}; ejecutá pnpm build."
        )
    copiar_arbol_runtime(origen, destino)


def poblar_release(raiz: Path, destino: Path) -> None:
    """Materializa en staging la allowlist canónica del paquete productivo."""

    for nombre in ("pyproject.toml", "uv.lock", ".python-version"):
        copiar_archivo(raiz / nombre, destino / "app" / nombre)

    for componente in (Path("apps/backend"), Path("services/device-bridge")):
        copiar_archivo(
            raiz / componente / "pyproject.toml", destino / "app" / componente / "pyproject.toml"
        )
        copiar_arbol_runtime(
            raiz / componente / "src",
            destino / "app" / componente / "src",
        )

    copiar_salida_spa(
        raiz / "apps/moderacion/.output/public",
        destino / "web/moderacion",
        "Moderación",
    )
    copiar_salida_spa(
        raiz / "apps/recinto/.output/public",
        destino / "web/recinto",
        "Recinto",
    )
    copiar_salida_spa(
        raiz / "apps/simulador/.output/public",
        destino / "web/simulador",
        "Simulador",
    )
    copiar_salida_spa(
        raiz / "apps/tecnico/.output/public",
        destino / "web/tecnico",
        "Apoyo Técnico",
    )
    # Zócalo para OBS (WP-099). Es una SPA estática igual que las otras cuatro y viaja en
    # la misma allowlist, de modo que el manifiesto inventaría sus archivos y la release
    # queda completa sin ningún paso manual adicional.
    copiar_salida_spa(
        raiz / "apps/zocalo/.output/public",
        destino / "web/zocalo",
        "Zócalo",
    )
    # Manual de usuario (WP-067). Es un HTML estático versionado, no la salida de un
    # build: se copia tal cual desde `manual/` a `web/manual/`, la misma raíz que sirve
    # Nginx para las SPA. Al viajar como una entrada más de la allowlist, queda incluido
    # en el inventario SHA-256 del manifest y en la comprobación de reproducibilidad.
    copiar_arbol_runtime(raiz / "manual", destino / "web/manual")
    copiar_arbol_runtime(raiz / "deploy", destino / "deploy")


def inventariar_archivos(raiz_release: Path) -> list[dict[str, Any]]:
    """Describe todos los archivos permitidos para validar contenido y tamaño."""

    inventario: list[dict[str, Any]] = []
    for ruta in sorted(raiz_release.rglob("*")):
        if ruta.is_symlink():
            raise ErrorEmpaquetado(f"Una release no puede contener enlaces: {ruta}")
        if ruta.is_file():
            relativa = ruta.relative_to(raiz_release).as_posix()
            inventario.append(
                {
                    "ruta": relativa,
                    "sha256": sha256_archivo(ruta),
                    "tamano": ruta.stat().st_size,
                }
            )
    return inventario


def escribir_manifest(
    raiz_release: Path,
    *,
    sha_commit: str,
    sha_arbol: str,
) -> Path:
    """Escribe el contrato autocontenido que vincula release, Git y archivos."""

    manifest = {
        "formato": FORMATO_RELEASE,
        "version_formato": VERSION_FORMATO,
        "commit_sha": sha_commit,
        "tree_sha": sha_arbol,
        "python": VERSION_PYTHON,
        "spas": {
            "moderacion": "web/moderacion/index.html",
            "recinto": "web/recinto/index.html",
            "simulador": "web/simulador/index.html",
            "tecnico": "web/tecnico/index.html",
            "zocalo": "web/zocalo/index.html",
        },
        # El manual no es una SPA: se declara aparte para que la herramienta de despliegue
        # pueda exigirlo sin ampliar el contrato cerrado de las cinco aplicaciones.
        "manual": "web/manual/index.html",
        "paquetes_python": ["sis-leg-backend", "sis-leg-device-bridge"],
        "archivos": inventariar_archivos(raiz_release),
    }
    ruta = raiz_release / "release.json"
    ruta.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return ruta


def _informacion_tar(ruta: Path, nombre: str) -> tarfile.TarInfo:
    """Crea metadatos deterministas y sin identidad del equipo constructor."""

    informacion = tarfile.TarInfo(nombre)
    informacion.size = ruta.stat().st_size
    informacion.mode = 0o755 if ruta.name.endswith(".py") else 0o644
    informacion.mtime = 0
    informacion.uid = 0
    informacion.gid = 0
    informacion.uname = "root"
    informacion.gname = "root"
    return informacion


def crear_tar_reproducible(raiz_release: Path, destino: Path) -> None:
    """Comprime solo archivos regulares con orden y timestamps estables."""

    destino.parent.mkdir(parents=True, exist_ok=True)
    with (
        destino.open("wb") as archivo_salida,
        gzip.GzipFile(filename="", mode="wb", fileobj=archivo_salida, mtime=0) as gzip_salida,
        tarfile.open(fileobj=gzip_salida, mode="w", format=tarfile.PAX_FORMAT) as tar,
    ):
        for ruta in sorted(r for r in raiz_release.rglob("*") if r.is_file()):
            nombre = ruta.relative_to(raiz_release).as_posix()
            with ruta.open("rb") as archivo:
                tar.addfile(_informacion_tar(ruta, nombre), archivo)


def escribir_sidecar(paquete: Path) -> Path:
    """Guarda el checksum con el formato convencional de sha256sum."""

    sidecar = paquete.with_name(f"{paquete.name}.sha256")
    sidecar.write_text(
        f"{sha256_archivo(paquete)}  {paquete.name}\n",
        encoding="ascii",
        newline="\n",
    )
    return sidecar


def construir_paquete(
    *,
    raiz: Path,
    directorio_salida: Path,
    sha_commit: str,
    sha_arbol: str,
) -> tuple[Path, Path]:
    """Construye paquete y sidecar a partir de fuentes/builds ya validados."""

    if len(sha_commit) != 40 or any(c not in "0123456789abcdef" for c in sha_commit):
        raise ErrorEmpaquetado("El SHA de commit debe contener 40 caracteres hexadecimales.")
    nombre = f"sis-leg-{sha_commit}.tar.gz"
    paquete = directorio_salida / nombre
    with tempfile.TemporaryDirectory(prefix="sis-leg-release-") as temporal:
        staging = Path(temporal)
        poblar_release(raiz, staging)
        escribir_manifest(staging, sha_commit=sha_commit, sha_arbol=sha_arbol)
        crear_tar_reproducible(staging, paquete)
    return paquete, escribir_sidecar(paquete)


def crear_parser() -> argparse.ArgumentParser:
    """Define la CLI mínima del comando canónico de empaquetado."""

    parser = argparse.ArgumentParser(description="Construye una release productiva por SHA Git.")
    parser.add_argument("--salida", type=Path, default=DIRECTORIO_SALIDA_PREDETERMINADO)
    return parser


def main(argumentos: Sequence[str] | None = None) -> int:
    """Valida Git, construye el artefacto y muestra las dos rutas resultantes."""

    opciones = crear_parser().parse_args(argumentos)
    exigir_checkout_limpio()
    sha_commit = ejecutar_git("rev-parse", "HEAD")
    sha_arbol = ejecutar_git("rev-parse", "HEAD^{tree}")
    paquete, sidecar = construir_paquete(
        raiz=RAIZ_REPOSITORIO,
        directorio_salida=opciones.salida.resolve(),
        sha_commit=sha_commit,
        sha_arbol=sha_arbol,
    )
    print(paquete)
    print(sidecar)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
