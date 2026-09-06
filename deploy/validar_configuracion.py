"""Valida configuración productiva con los parsers propietarios instalados."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from sis_leg_backend.configuracion.cargar_configuracion import cargar_configuracion_sistema
from sis_leg_backend.configuracion.cargar_padron import cargar_padron_concejales
from sis_leg_backend.configuracion.sonidos_recinto import validar_assets_sonidos
from sis_leg_device_bridge.configuracion import cargar_dispositivos_json

# Subdirectorio de la release donde queda publicada la Pantalla del Recinto.
# Es la raíz contra la que resuelven las rutas de ``[sonidos]``: dentro del
# repositorio ese mismo rol lo cumple ``apps/recinto/public``.
SUBRUTA_WEB_RECINTO = Path("web/recinto")


def validar(raiz: Path, release: Path) -> None:
    """Carga los contratos y exige auditoría y sonidos resolubles.

    Entradas:
        raiz: raíz de la instalación productiva; contiene ``config/`` y
            ``logs/``.
        release: release concreta que se está activando; contiene la SPA del
            Recinto y, por lo tanto, los assets de sonido versionados.

    Errores:
        Las excepciones propias de cada parser (``ErrorTomlInvalido``,
        ``ErrorValidacionConfiguracion``, ``ErrorPadronInvalido``…) y
        ``ValueError`` si ``logs_dir`` no resuelve al directorio esperado.
        Cualquiera de ellas aborta la activación antes de tocar el servicio.
    """

    configuracion = cargar_configuracion_sistema(raiz / "config/system.toml")
    cargar_padron_concejales(raiz / "config/concejales.csv", configuracion)
    cargar_dispositivos_json(raiz / "config/bridge/devices.json")

    # Los sonidos ya quedaron validados sintácticamente al cargar el TOML. Acá
    # se comprueba lo que sólo el despliegue puede saber: que cada ruta apunte
    # a un archivo realmente publicado por la SPA del Recinto (WP-065).
    validar_assets_sonidos(configuracion.sonidos_recinto, release / SUBRUTA_WEB_RECINTO)

    ruta_configurada = Path(configuracion.directorio_registros)
    if not ruta_configurada.is_absolute():
        ruta_configurada = raiz / ruta_configurada
    esperado = (raiz / "logs").resolve()
    real = ruta_configurada.resolve()
    if real != esperado:
        raise ValueError(f"logs_dir debe resolver a {esperado} y resolvió a {real}")


def main(argumentos: Sequence[str] | None = None) -> int:
    """Expone la validación como subprocess aislado del CLI administrativo."""

    parser = argparse.ArgumentParser()
    parser.add_argument("raiz", type=Path)
    parser.add_argument("release", type=Path)
    opciones = parser.parse_args(argumentos)
    validar(opciones.raiz.resolve(), opciones.release.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
