"""Línea de comandos y punto de entrada ejecutable del bridge de dispositivos.

Este módulo implementa `ejecutar_cli` y el console script `sis-leg-device-bridge`:
1. Parsea opciones de configuración técnica desde argumentos de terminal y variables de entorno.
2. Configura logging estándar a stdout/stderr apto para desarrollo y journal/systemd.
3. Registra manejadores de señales `SIGINT` (Ctrl+C) y `SIGTERM` para parada limpia y segura.
4. Carga y valida rigurosamente `devices.json`.
5. Inicia el `ServicioDeviceBridge` con `AdaptadorEvdevLinux` y `ClienteHttpBackend`.
6. Expone la API HTTP local de control con bind loopback predeterminado.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
from collections.abc import Sequence
from pathlib import Path

from sis_leg_device_bridge.adaptador_linux import AdaptadorEvdevLinux
from sis_leg_device_bridge.cliente_http import ClienteHttpBackend
from sis_leg_device_bridge.configuracion import (
    ConfiguracionBridge,
    ErrorConfiguracionBridge,
    cargar_dispositivos_json,
)
from sis_leg_device_bridge.servicio import ServicioDeviceBridge
from sis_leg_device_bridge.servidor_control import ServidorControlBridge

logger = logging.getLogger("sis_leg_device_bridge")


def construir_parser_argumentos() -> argparse.ArgumentParser:
    """Construye el parseador de argumentos de línea de comandos."""
    parser = argparse.ArgumentParser(
        prog="sis-leg-device-bridge",
        description=(
            "Bridge físico Linux y compatibilidad fingerprint a dispositivo lógico de SIS-Leg"
        ),
    )

    parser.add_argument(
        "--config",
        "-c",
        dest="ruta_config",
        type=Path,
        default=Path(
            os.getenv(
                "SIS_LEG_DEVICES_CONFIG",
                "services/device-bridge/config/devices.json",
            )
        ),
        help="Ruta a devices.json (default: services/device-bridge/config/devices.json)",
    )

    parser.add_argument(
        "--url",
        "-u",
        dest="url_api",
        type=str,
        default=os.getenv("SIS_LEG_BACKEND_URL", "http://127.0.0.1:8000"),
        help="URL base del backend FastAPI (default: http://127.0.0.1:8000)",
    )

    parser.add_argument(
        "--timeout",
        "-t",
        dest="timeout_http",
        type=float,
        default=float(os.getenv("SIS_LEG_HTTP_TIMEOUT", "3.0")),
        help="Timeout en segundos para las peticiones HTTP al backend (default: 3.0)",
    )

    parser.add_argument(
        "--intervalo-escaneo",
        "-i",
        dest="intervalo_escaneo",
        type=float,
        default=float(os.getenv("SIS_LEG_SCAN_INTERVAL", "2.0")),
        help="Intervalo en segundos entre re-descubrimientos de hardware (default: 2.0)",
    )

    parser.add_argument(
        "--log-level",
        "-l",
        dest="nivel_log",
        type=str,
        default=os.getenv("SIS_LEG_LOG_LEVEL", "INFO").upper(),
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Nivel de detalle para los registros en stdout/stderr (default: INFO)",
    )

    parser.add_argument(
        "--control-host",
        dest="host_control",
        default=os.getenv("SIS_LEG_CONTROL_HOST", "127.0.0.1"),
        help="Host de la API local de control (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--control-port",
        dest="puerto_control",
        type=int,
        default=int(os.getenv("SIS_LEG_CONTROL_PORT", "8765")),
        help="Puerto de la API local de control (default: 8765)",
    )

    return parser


def configurar_logging(nivel_nombre: str) -> None:
    """Configura el logging estándar con formato legible para consola o journald."""
    nivel = getattr(logging, nivel_nombre.upper(), logging.INFO)
    formato = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(
        level=nivel,
        format=formato,
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )


def ejecutar_cli(argumentos: Sequence[str] | None = None) -> int:
    """Punto de entrada principal para ejecutar el bridge desde CLI o console script.

    Args:
        argumentos: Lista de argumentos de línea de comandos o None para usar sys.argv.

    Returns:
        0 si la ejecución terminó limpiamente, 1 ante errores de configuración o fatales.
    """
    parser = construir_parser_argumentos()
    opciones = parser.parse_args(argumentos)

    configurar_logging(opciones.nivel_log)
    logger.info("Iniciando SIS-Leg Device Bridge (Linux)")

    # 1. Cargar y validar configuración de dispositivos
    try:
        mapeo = cargar_dispositivos_json(opciones.ruta_config)
        logger.info(
            "Configuración cargada exitosamente desde %s (%d dispositivos mapeados)",
            opciones.ruta_config,
            len(mapeo),
        )
    except ErrorConfiguracionBridge as exc:
        logger.error("Error crítico de configuración: %s", exc)
        return 1
    except Exception as exc:
        logger.error(
            "Fallo inesperado al cargar configuración desde %s: %s",
            opciones.ruta_config,
            exc,
        )
        return 1

    configuracion = ConfiguracionBridge(
        url_base_api=opciones.url_api,
        timeout_http_segundos=opciones.timeout_http,
        ruta_devices_json=opciones.ruta_config,
        intervalo_escaneo_segundos=opciones.intervalo_escaneo,
        host_control=opciones.host_control,
        puerto_control=opciones.puerto_control,
    )

    # 2. Inicializar adaptadores y cliente HTTP
    try:
        adaptador = AdaptadorEvdevLinux()
    except RuntimeError as exc:
        logger.error("No se pudo inicializar el adaptador evdev: %s", exc)
        return 1

    cliente_http = ClienteHttpBackend(
        url_base=configuracion.url_base_api,
        timeout_segundos=configuracion.timeout_http_segundos,
    )

    servicio = ServicioDeviceBridge(
        configuracion=configuracion,
        adaptador=adaptador,
        cliente_http=cliente_http,
        mapeo_dispositivos=mapeo,
    )
    servidor_control = ServidorControlBridge(
        servicio.coordinador_remapeo,
        host=configuracion.host_control,
        puerto=configuracion.puerto_control,
    )

    evento_detencion = threading.Event()

    def _manejador_senial(signum: int, _frame: object) -> None:
        nombre_senial = signal.Signals(signum).name
        logger.info("Señal %s recibida. Deteniendo bridge de forma limpia...", nombre_senial)
        evento_detencion.set()
        servicio.detener()

    # Registrar señales de parada en el hilo principal
    try:
        signal.signal(signal.SIGINT, _manejador_senial)
        signal.signal(signal.SIGTERM, _manejador_senial)
    except ValueError:
        # En hilos secundarios signal.signal puede no estar disponible
        pass

    # 3. Ejecutar el servicio
    try:
        servidor_control.iniciar()
        servicio.ejecutar_servicio(evento_detencion=evento_detencion)
        return 0
    except Exception as exc:
        logger.error("Error fatal durante la ejecución del servicio: %s", exc, exc_info=True)
        return 1
    finally:
        servidor_control.detener()


if __name__ == "__main__":
    sys.exit(ejecutar_cli())
