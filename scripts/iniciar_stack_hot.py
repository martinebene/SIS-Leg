"""Lanzador Python del stack interactivo de desarrollo con hot reload.

Este script complementa al lanzador en Node.js (``scripts/iniciar_stack_hot.mjs``)
ofreciendo validaciones directas de entorno, comprobación de la rama ``main``,
verificación de interfaz loopback y ejecución homogénea multiplataforma.
"""

from __future__ import annotations

import argparse
import ipaddress
import socket
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

HOST_PREDETERMINADO = "127.0.0.1"
PUERTO_EXTERNO_PREDETERMINADO = 8000
PUERTO_BACKEND_PREDETERMINADO = 8001
PUERTO_MODERACION_PREDETERMINADO = 8002
PUERTO_RECINTO_PREDETERMINADO = 8003
PUERTO_SIMULADOR_PREDETERMINADO = 8004
PUERTO_TECNICO_PREDETERMINADO = 8005

RAIZ_REPOSITORIO = Path(__file__).resolve().parents[1]
RUTA_SCRIPT_NODE = RAIZ_REPOSITORIO / "scripts" / "iniciar_stack_hot.mjs"


class ErrorStackHot(RuntimeError):
    """Indica un fallo de configuración, de rama Git o de puertos en el stack hot."""


def es_host_loopback(host: str) -> bool:
    """Verifica si una dirección IP o nombre corresponde únicamente a loopback.

    Acepta localhost, ::1 o cualquier dirección del bloque IPv4 127.0.0.0/8.
    """

    host_limpio = host.strip().lower()
    if host_limpio in ("localhost", "::1"):
        return True

    try:
        direccion = ipaddress.ip_address(host_limpio)
        return direccion.is_loopback
    except ValueError:
        return False


def validar_host(host: str) -> None:
    """Arroja ``ErrorStackHot`` si el host no es una interfaz local de loopback.

    Args:
        host: Nombre de host o dirección IP a comprobar.

    Raises:
        ErrorStackHot: Si el host no es loopback.
    """

    if not es_host_loopback(host):
        raise ErrorStackHot(
            f"El host '{host}' no es seguro para el stack de desarrollo. "
            "Debe ser una interfaz loopback local (ej. 127.0.0.1 o localhost) para evitar "
            "exponer servicios internos a la red."
        )


def obtener_rama_actual(raiz: Path = RAIZ_REPOSITORIO) -> str:
    """Obtiene la rama Git activa sin realizar mutaciones.

    Args:
        raiz: Directorio raíz del repositorio.

    Returns:
        Nombre de la rama activa en el checkout actual.

    Raises:
        ErrorStackHot: Si Git no puede determinar la rama.
    """

    try:
        resultado = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=raiz,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        return resultado.stdout.strip()
    except subprocess.CalledProcessError as error:
        raise ErrorStackHot(
            f"No se pudo determinar la rama Git actual: {error.stderr.strip()}"
        ) from error


def verificar_rama_main(
    permitir_no_main: bool = False,
    raiz: Path = RAIZ_REPOSITORIO,
) -> tuple[str, bool]:
    """Comprueba que el checkout esté en la rama 'main' salvo excepción explícita.

    Args:
        permitir_no_main: Si es True, autoriza la ejecución en ramas distintas a main.
        raiz: Directorio raíz del repositorio.

    Returns:
        Tupla con (nombre_rama, es_main).

    Raises:
        ErrorStackHot: Si no está en main y no se habilitó la excepción.
    """

    rama = obtener_rama_actual(raiz)
    es_main = rama == "main"

    if not es_main and not permitir_no_main:
        raise ErrorStackHot(
            "El comando canónico `dev:stack:hot` está destinado exclusivamente al checkout "
            f"coordinador de la rama `main`.\nLa rama actual es '{rama}'.\n\n"
            "Para el flujo habitual de desarrollo interactivo sobre main:\n"
            "  1. Cambiá al checkout de main: git checkout main\n"
            "  2. Actualizá con los últimos cambios: git pull --ff-only origin main\n"
            "  3. Iniciá el stack: pnpm dev:stack:hot\n\n"
            "Si estás validando el candidato mediante pruebas o smoke dentro de una rama "
            "de desarrollo, utilizá:\n  --allow-non-main"
        )

    return rama, es_main


def puerto_en_uso(puerto: int, host: str = HOST_PREDETERMINADO) -> bool:
    """Verifica si un puerto TCP está ocupado intentando abrir una conexión."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        resultado = sock.connect_ex((host, puerto))
        return resultado == 0


def convertir_puerto(valor: str) -> int:
    """Convierte un argumento CLI en un número de puerto TCP válido."""

    try:
        puerto = int(valor)
    except ValueError as error:
        raise argparse.ArgumentTypeError("el puerto debe ser un número entero") from error

    if not 1 <= puerto <= 65535:
        raise argparse.ArgumentTypeError("el puerto debe estar entre 1 y 65535")
    return puerto


def crear_analizador_argumentos() -> argparse.ArgumentParser:
    """Define los argumentos de línea de comandos del stack interactivo."""

    analizador = argparse.ArgumentParser(
        description=("Inicia el stack interactivo de desarrollo de SIS-Leg con HMR y autoreload.")
    )
    analizador.add_argument(
        "--host",
        default=HOST_PREDETERMINADO,
        help=f"interfaz loopback de escucha (predeterminado: {HOST_PREDETERMINADO})",
    )
    analizador.add_argument(
        "-p",
        "--port",
        type=convertir_puerto,
        default=PUERTO_EXTERNO_PREDETERMINADO,
        help=f"puerto HTTP externo de escucha (predeterminado: {PUERTO_EXTERNO_PREDETERMINADO})",
    )
    analizador.add_argument(
        "--backend-port",
        type=convertir_puerto,
        default=PUERTO_BACKEND_PREDETERMINADO,
        help=(
            "puerto interno auxiliar para FastAPI "
            f"(predeterminado: {PUERTO_BACKEND_PREDETERMINADO})"
        ),
    )
    analizador.add_argument(
        "--moderacion-port",
        type=convertir_puerto,
        default=PUERTO_MODERACION_PREDETERMINADO,
        help=(
            "puerto interno auxiliar para Moderación "
            f"(predeterminado: {PUERTO_MODERACION_PREDETERMINADO})"
        ),
    )
    analizador.add_argument(
        "--recinto-port",
        type=convertir_puerto,
        default=PUERTO_RECINTO_PREDETERMINADO,
        help=(
            "puerto interno auxiliar para Recinto "
            f"(predeterminado: {PUERTO_RECINTO_PREDETERMINADO})"
        ),
    )
    analizador.add_argument(
        "--simulador-port",
        type=convertir_puerto,
        default=PUERTO_SIMULADOR_PREDETERMINADO,
        help=(
            "puerto interno auxiliar para Simulador "
            f"(predeterminado: {PUERTO_SIMULADOR_PREDETERMINADO})"
        ),
    )
    analizador.add_argument(
        "--tecnico-port",
        type=convertir_puerto,
        default=PUERTO_TECNICO_PREDETERMINADO,
        help=(
            "puerto interno auxiliar para Apoyo Técnico "
            f"(predeterminado: {PUERTO_TECNICO_PREDETERMINADO})"
        ),
    )
    analizador.add_argument(
        "--allow-non-main",
        "--permitir-rama-no-main",
        action="store_true",
        dest="allow_non_main",
        help="permite ejecutar en ramas distintas de main (solo para tests o smoke del WP)",
    )
    return analizador


def main(argumentos: Sequence[str] | None = None) -> int:
    """Valida los parámetros e invoca el orquestador Node del stack hot."""

    analizador = crear_analizador_argumentos()
    opciones = analizador.parse_args(argumentos)

    try:
        validar_host(opciones.host)
        verificar_rama_main(permitir_no_main=opciones.allow_non_main)
    except ErrorStackHot as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    # Reenviar los argumentos exactos al orquestador en Node.js
    comando_node = ["node", str(RUTA_SCRIPT_NODE)]
    if argumentos is not None:
        comando_node.extend(argumentos)
    else:
        comando_node.extend(sys.argv[1:])

    try:
        resultado = subprocess.run(comando_node, cwd=RAIZ_REPOSITORIO)
        return resultado.returncode
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
