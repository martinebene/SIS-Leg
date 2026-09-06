"""Exportación y verificación determinista del esquema OpenAPI de FastAPI.

Este script obtiene la definición técnica canónica de la API REST directamente
de la aplicación FastAPI del backend (sin requerir servidor HTTP ni red) y la
exporta como JSON formateado de manera estable.

Modos de uso:
- Exportar (sobrescribe el snapshot):
    uv run python scripts/exportar_openapi.py
- Verificar drift (falla con código 1 si el backend difiere del snapshot):
    uv run python scripts/exportar_openapi.py --check
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sis_leg_backend.aplicacion import crear_aplicacion

# Ruta predeterminada del snapshot OpenAPI versionado dentro de packages/api-client
RUTA_OPENAPI_PREDETERMINADA = (
    Path(__file__).resolve().parent.parent / "packages" / "api-client" / "openapi" / "openapi.json"
)


def generar_esquema_openapi() -> dict[str, Any]:
    """Construye una instancia de la aplicación FastAPI y obtiene su esquema OpenAPI.

    Returns:
        Diccionario con la especificación OpenAPI 3.1 generada por FastAPI.
    """
    aplicacion = crear_aplicacion()
    return aplicacion.openapi()


def serializar_esquema_determinista(esquema: dict[str, Any]) -> str:
    """Serializa el diccionario OpenAPI a formato JSON determinista.

    Se asegura un formato uniforme con sangría de 2 espacios, codificación UTF-8
    sin escapes ASCII innecesarios y salto de línea final para consistencia en Git.

    Args:
        esquema: Diccionario con la especificación OpenAPI.

    Returns:
        Cadena de texto JSON determinista con salto de línea final.
    """
    return json.dumps(esquema, indent=2, ensure_ascii=False) + "\n"


def exportar_openapi(ruta_destino: Path = RUTA_OPENAPI_PREDETERMINADA) -> None:
    """Genera y guarda el snapshot OpenAPI en el archivo destino especificado.

    Args:
        ruta_destino: Ruta del archivo JSON donde se guardará el snapshot.
    """
    esquema = generar_esquema_openapi()
    contenido = serializar_esquema_determinista(esquema)
    ruta_destino.parent.mkdir(parents=True, exist_ok=True)
    ruta_destino.write_text(contenido, encoding="utf-8")
    print(f"Esquema OpenAPI exportado exitosamente a: {ruta_destino}")


def verificar_drift_openapi(ruta_snapshot: Path = RUTA_OPENAPI_PREDETERMINADA) -> bool:
    """Comprueba si el snapshot versionado coincide exactamente con el OpenAPI del backend actual.

    Args:
        ruta_snapshot: Ruta del archivo JSON del snapshot a contrastar.

    Returns:
        True si coinciden exactamente (sin drift); False si hay discrepancias.
    """
    if not ruta_snapshot.exists():
        print(
            f"ERROR: No se encontró el archivo de snapshot OpenAPI en: {ruta_snapshot}",
            file=sys.stderr,
        )
        return False

    contenido_actual = serializar_esquema_determinista(generar_esquema_openapi())
    contenido_snapshot = ruta_snapshot.read_text(encoding="utf-8")

    if contenido_actual != contenido_snapshot:
        print(
            "ERROR: Se detectó DRIFT entre el backend FastAPI y el snapshot OpenAPI versionado.",
            file=sys.stderr,
        )
        print(
            f"El archivo {ruta_snapshot} está desactualizado respecto a apps/backend.",
            file=sys.stderr,
        )
        print(
            "Ejecutá 'pnpm generate:openapi' o 'uv run python scripts/exportar_openapi.py' "
            "para actualizar el snapshot y luego regenerá los tipos TypeScript.",
            file=sys.stderr,
        )
        return False

    print("Verificación OpenAPI OK: el snapshot coincide exactamente con el backend FastAPI.")
    return True


def main() -> None:
    """Punto de entrada CLI para exportación y verificación de OpenAPI."""
    parser = argparse.ArgumentParser(
        description="Exportación y verificación determinista del esquema OpenAPI de SIS-Leg."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verifica si el snapshot coincide con el backend sin modificar archivos.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=RUTA_OPENAPI_PREDETERMINADA,
        help="Ruta alternativa de salida para el archivo OpenAPI JSON.",
    )

    argumentos = parser.parse_args()

    if argumentos.check:
        coincide = verificar_drift_openapi(argumentos.output)
        sys.exit(0 if coincide else 1)
    else:
        exportar_openapi(argumentos.output)


if __name__ == "__main__":
    main()
