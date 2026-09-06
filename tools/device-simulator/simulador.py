"""Punto de entrada CLI principal del simulador de dispositivos y escenarios (WP-007).

Este script permite ejecutar el simulador de tres formas distintas:
1. Modo interactivo persistente:
   `uv run python tools/device-simulator/simulador.py`
2. Modo de pulsacion unica desde terminal shell:
   `uv run python tools/device-simulator/simulador.py 5-9`
3. Modo de ejecucion de escenario declarativo:
   `uv run python tools/device-simulator/simulador.py --escenario ruta/al/escenario.json`

Pedagogia y convenciones:
- Todo identificador propio en espanol sin tildes ni eñes (DEC-001).
- El codigo de salida es determinista:
  * 0 para ejecucion exitosa (respuesta HTTP 2xx o escenario sin discrepancias).
  * 1 para errores de sintaxis, fallos de red, respuestas HTTP 4xx/5xx o expectativas no cumplidas.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Asegurar que el directorio de este modulo este disponible en sys.path para importacion directa
DIRECTORIO_ACTUAL = Path(__file__).resolve().parent
if str(DIRECTORIO_ACTUAL) not in sys.path:
    sys.path.insert(0, str(DIRECTORIO_ACTUAL))

from cliente import URL_BASE_DEFECTO, ClienteBackend  # noqa: E402
from ejecutor_escenarios import (  # noqa: E402
    EjecutorEscenarios,
    imprimir_resultado_envio,
)
from interactivo import ejecutar_consola_interactiva  # noqa: E402
from parseador import (  # noqa: E402
    ErrorFormatoEscenario,
    ErrorSintaxisEntrada,
    parsear_escenario_json,
    parsear_sintaxis_manual,
)


def construir_argumentos_cli() -> argparse.ArgumentParser:
    """Construye el parser de argumentos de linea de comandos para el simulador."""
    parser = argparse.ArgumentParser(
        prog="simulador.py",
        description=(
            "SIS-Leg - Simulador CLI reproducible de dispositivos y escenarios.\n"
            "Permite enviar pulsaciones logicas reales al endpoint POST /api/v1/entradas/tecla."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "pulsacion",
        nargs="?",
        default=None,
        help=(
            "Pulsacion unica a enviar en formato compacto <dispositivo>-<tecla> "
            "(ejemplos: '5-9', '12-8', '3-+', '5--', '4-enter'). "
            "Si no se especifica pulsacion ni escenario, se abre el modo interactivo."
        ),
    )

    parser.add_argument(
        "-e",
        "--escenario",
        dest="ruta_escenario",
        default=None,
        help="Ruta al archivo JSON de escenario declarativo a ejecutar.",
    )

    parser.add_argument(
        "-u",
        "--url",
        "--url-base",
        dest="url_base",
        default=URL_BASE_DEFECTO,
        help=f"URL base del backend FastAPI (por defecto: '{URL_BASE_DEFECTO}').",
    )

    parser.add_argument(
        "-t",
        "--timeout",
        dest="timeout_segundos",
        type=float,
        default=10.0,
        help="Tiempo limite de espera en segundos para cada peticion HTTP (por defecto: 10.0).",
    )

    return parser


async def ejecutar_simulador_async(argumentos: argparse.Namespace) -> int:
    """Orquesta la ejecucion asincrona del simulador segun los argumentos provistos.

    Args:
        argumentos: Argumentos parseados de la linea de comandos.

    Returns:
        Codigo de salida entero para el proceso (0 = exito, 1 = fallo).
    """
    cliente = ClienteBackend(
        url_base=argumentos.url_base,
        timeout_segundos=argumentos.timeout_segundos,
    )

    try:
        # Caso 1: Se especifico tanto pulsacion como escenario (incompatibles)
        if argumentos.pulsacion is not None and argumentos.ruta_escenario is not None:
            sys.stderr.write(
                "Error: No se puede especificar simultaneamente una pulsacion directa "
                "y un archivo de escenario. Elija una sola opcion.\n"
            )
            return 1

        # Caso 2: Pulsacion unica desde shell
        if argumentos.pulsacion is not None:
            try:
                pulsacion = parsear_sintaxis_manual(argumentos.pulsacion)
            except ErrorSintaxisEntrada as err:
                sys.stderr.write(f"Error de sintaxis en la pulsacion: {err}\n")
                return 1

            resultado = await cliente.enviar_pulsacion(pulsacion)
            imprimir_resultado_envio(resultado, salida=sys.stdout)

            # Codigo 0 solo si se obtuvo respuesta HTTP 2xx
            return 0 if resultado.es_exitoso_para_cli else 1

        # Caso 3: Ejecucion de escenario declarativo
        if argumentos.ruta_escenario is not None:
            ruta_archivo = Path(argumentos.ruta_escenario)
            if not ruta_archivo.exists() or not ruta_archivo.is_file():
                sys.stderr.write(
                    f"Error: El archivo de escenario '{argumentos.ruta_escenario}' no existe.\n"
                )
                return 1

            try:
                contenido_texto = ruta_archivo.read_text(encoding="utf-8")
                escenario = parsear_escenario_json(contenido_texto)
            except (OSError, ErrorFormatoEscenario) as err:
                sys.stderr.write(f"Error al cargar el escenario JSON: {err}\n")
                return 1

            ejecutor = EjecutorEscenarios(cliente=cliente, flujo_salida=sys.stdout)
            resumen = await ejecutor.ejecutar_escenario(escenario)

            return 0 if resumen.es_exitoso else 1

        # Caso 4: Modo interactivo persistente (sin argumentos de pulsacion ni escenario)
        await ejecutar_consola_interactiva(cliente=cliente, flujo_salida=sys.stdout)
        return 0

    finally:
        await cliente.cerrar()


def main() -> int:
    """Punto de entrada sincrono principal."""
    parser = construir_argumentos_cli()
    argumentos = parser.parse_args()
    return asyncio.run(ejecutar_simulador_async(argumentos))


if __name__ == "__main__":
    sys.exit(main())
