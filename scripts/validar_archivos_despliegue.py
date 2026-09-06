"""Valida con binarios reales las plantillas Nginx y systemd versionadas."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def validar_systemd() -> None:
    """Pide al parser oficial de systemd verificar ambas unidades juntas."""

    subprocess.run(
        [
            "systemd-analyze",
            "verify",
            str(RAIZ / "deploy/systemd/sis-leg-backend.service"),
            str(RAIZ / "deploy/systemd/sis-leg-device-bridge.service"),
        ],
        check=True,
    )


def validar_nginx() -> None:
    """Envuelve el sitio en una configuración efímera y ejecuta ``nginx -t``."""

    sitio = RAIZ / "deploy/nginx/sis-leg.conf"
    with tempfile.TemporaryDirectory(prefix="sis-leg-nginx-") as temporal:
        prefijo = Path(temporal)
        configuracion = prefijo / "nginx.conf"
        configuracion.write_text(
            "\n".join(
                (
                    "worker_processes 1;",
                    f"pid {prefijo / 'nginx.pid'};",
                    "error_log stderr;",
                    "events { worker_connections 32; }",
                    "http {",
                    "  access_log off;",
                    "  include /etc/nginx/mime.types;",
                    f"  include {sitio};",
                    "}",
                    "",
                )
            ),
            encoding="utf-8",
        )
        subprocess.run(
            ["nginx", "-t", "-p", str(prefijo), "-c", str(configuracion)],
            check=True,
        )


def main() -> int:
    """Ejecuta ambas validaciones y deja que cualquier fallo corte CI."""

    validar_systemd()
    validar_nginx()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
