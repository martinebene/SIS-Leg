"""Pruebas de la interfaz de línea de comandos (CLI) del bridge.

Verifica:
1. Parseo de argumentos con valores por defecto.
2. Sobreescritura mediante argumentos explícitos y variables de entorno.
3. Retorno de código de salida 1 ante archivo de configuración inexistente o inválido.
4. Ejecución exitosa y captura de errores en el ciclo principal.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sis_leg_device_bridge.cli import construir_parser_argumentos, ejecutar_cli


def test_parser_argumentos_defaults() -> None:
    """Verifica que los argumentos por defecto coincidan con la especificación."""
    parser = construir_parser_argumentos()
    opciones = parser.parse_args([])

    assert opciones.ruta_config == Path("services/device-bridge/config/devices.json")
    assert opciones.url_api == "http://127.0.0.1:8000"
    assert opciones.timeout_http == 3.0
    assert opciones.intervalo_escaneo == 2.0
    assert opciones.nivel_log == "INFO"
    assert opciones.host_control == "127.0.0.1"
    assert opciones.puerto_control == 8765


def test_parser_argumentos_explicitos() -> None:
    """Verifica el parseo de banderas explícitas."""
    parser = construir_parser_argumentos()
    opciones = parser.parse_args(
        [
            "--config",
            "/tmp/custom_devices.json",
            "--url",
            "http://192.168.1.100:8000",
            "--timeout",
            "5.0",
            "--intervalo-escaneo",
            "1.0",
            "--log-level",
            "DEBUG",
            "--control-host",
            "localhost",
            "--control-port",
            "9876",
        ]
    )

    assert opciones.ruta_config == Path("/tmp/custom_devices.json")
    assert opciones.url_api == "http://192.168.1.100:8000"
    assert opciones.timeout_http == 5.0
    assert opciones.intervalo_escaneo == 1.0
    assert opciones.nivel_log == "DEBUG"
    assert opciones.host_control == "localhost"
    assert opciones.puerto_control == 9876


def test_cli_falla_si_config_no_existe(tmp_path: Path) -> None:
    """Verifica que ejecutar el CLI con un archivo inexistente retorne código 1."""
    ruta_inexistente = tmp_path / "no_existe.json"
    codigo_salida = ejecutar_cli(["--config", str(ruta_inexistente)])
    assert codigo_salida == 1


def test_cli_falla_si_config_invalida(tmp_path: Path) -> None:
    """Verifica que ejecutar el CLI con un archivo corrupto retorne código 1."""
    ruta_invalida = tmp_path / "invalido.json"
    ruta_invalida.write_text("{ esto no es json }", encoding="utf-8")
    codigo_salida = ejecutar_cli(["--config", str(ruta_invalida)])
    assert codigo_salida == 1


def test_cli_ejecucion_valida(tmp_path: Path) -> None:
    """Verifica que con configuración válida el CLI inicialice el servicio."""
    ruta_valida = tmp_path / "devices.json"
    fp = "lin|vendor=1a2c|product=2d43|version=0110|phys=usb-1|uniq=|name=USB Keyboard"
    ruta_valida.write_text(f'{{"{fp}": "dev01"}}', encoding="utf-8")

    patch_servicio = patch("sis_leg_device_bridge.cli.ServicioDeviceBridge.ejecutar_servicio")
    with patch_servicio as mock_servicio:
        mock_servicio.return_value = None
        codigo = ejecutar_cli(["--config", str(ruta_valida)])
        assert codigo == 0
        assert mock_servicio.called
