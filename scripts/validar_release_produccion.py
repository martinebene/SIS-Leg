"""Smoke real ejecutado exclusivamente desde el contenido del artefacto."""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Sequence
from pathlib import Path

# Cuando Python ejecuta ``scripts/validar_release_produccion.py`` directamente,
# agrega ``scripts/`` y no la raíz del repositorio a ``sys.path``. CI usa
# deliberadamente esa forma pública, por lo que hacemos explícita la raíz antes
# de importar la herramienta compartida con producción.
RAIZ_REPOSITORIO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ_REPOSITORIO))

from deploy.herramienta_despliegue import (  # noqa: E402 - raíz preparada arriba
    extraer_paquete_seguro,
    verificar_checksum,
)


class ErrorSmoke(RuntimeError):
    """Indica que el artefacto no puede ejecutar su runtime productivo."""


def elegir_puerto_loopback() -> int:
    """Reserva brevemente un puerto libre que luego utilizará Uvicorn."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as socket_prueba:
        socket_prueba.bind(("127.0.0.1", 0))
        return int(socket_prueba.getsockname()[1])


def esperar_health(url: str, proceso: subprocess.Popen[str], timeout: float = 20.0) -> None:
    """Espera readiness acotado y corta antes si Uvicorn termina."""

    limite = time.monotonic() + timeout
    ultimo: Exception | None = None
    while time.monotonic() < limite:
        if proceso.poll() is not None:
            salida, error = proceso.communicate()
            raise ErrorSmoke(f"Uvicorn terminó antes del health: {salida}\n{error}")
        try:
            with urllib.request.urlopen(url, timeout=1.0) as respuesta:
                if respuesta.status == 200 and b'"estado":"ok"' in respuesta.read():
                    return
        except OSError as error:
            ultimo = error
        time.sleep(0.2)
    raise ErrorSmoke(f"Health no estuvo disponible dentro del plazo: {ultimo}")


def ejecutar_smoke(paquete: Path, sidecar: Path, sha: str) -> None:
    """Extrae seguro, instala ``--no-dev`` y prueba backend/bridge/SPAs."""

    verificar_checksum(paquete, sidecar)
    with tempfile.TemporaryDirectory(prefix="sis-leg-smoke-") as temporal:
        release = Path(temporal) / sha
        extraer_paquete_seguro(paquete, release, sha)
        ambiente = os.environ.copy()
        ambiente["UV_PROJECT_ENVIRONMENT"] = str(release / ".venv")
        subprocess.run(
            ["uv", "sync", "--frozen", "--no-dev", "--all-packages"],
            cwd=release / "app",
            env=ambiente,
            check=True,
        )
        subprocess.run(
            [str(release / ".venv/bin/sis-leg-device-bridge"), "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        for spa in ("moderacion", "recinto", "simulador", "tecnico", "zocalo"):
            indice = release / "web" / spa / "index.html"
            assets = release / "web" / spa / "_nuxt"
            if not indice.is_file() or not any(ruta.is_file() for ruta in assets.iterdir()):
                raise ErrorSmoke(f"La SPA {spa} está incompleta dentro del artefacto.")

        # Manual de usuario (WP-067). Se comprueba desde el artefacto extraído, y no desde
        # el checkout, porque lo que debe quedar publicado en `/manual/` es exactamente el
        # archivo que viajó dentro de la release.
        manual = release / "web/manual/index.html"
        if not manual.is_file():
            raise ErrorSmoke("El manual de usuario no está incluido en el artefacto.")
        contenido_manual = manual.read_text(encoding="utf-8")
        if "SIS-Leg" not in contenido_manual or "cap-01-vision-general" not in contenido_manual:
            raise ErrorSmoke("El manual incluido en el artefacto no tiene el contenido esperado.")

        puerto = elegir_puerto_loopback()
        proceso = subprocess.Popen(
            [
                str(release / ".venv/bin/uvicorn"),
                "sis_leg_backend.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(puerto),
                "--workers",
                "1",
            ],
            cwd=release / "app",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            esperar_health(f"http://127.0.0.1:{puerto}/api/v1/health", proceso)
        finally:
            proceso.terminate()
            try:
                proceso.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proceso.kill()
                proceso.wait(timeout=5)


def crear_parser() -> argparse.ArgumentParser:
    """Define los tres datos inmutables requeridos por el smoke."""

    parser = argparse.ArgumentParser(description="Valida una release desde su tar extraído.")
    parser.add_argument("paquete", type=Path)
    parser.add_argument("--checksum", type=Path, required=True)
    parser.add_argument("--sha", required=True)
    return parser


def main(argumentos: Sequence[str] | None = None) -> int:
    """Ejecuta el smoke y propaga errores como salida no cero."""

    opciones = crear_parser().parse_args(argumentos)
    ejecutar_smoke(opciones.paquete, opciones.checksum, opciones.sha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
