"""Gate de reproducibilidad de punta a punta del paquete productivo.

El verificador ejecuta dos veces el comando canónico completo, incluida la
generación Nuxt, y compara tanto el tar como su sidecar. La segunda ejecución
queda en ``dist/produccion`` para que CI continúe con smoke y publicación.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Al ejecutar ``python scripts/verificar_reproducibilidad_produccion.py``, Python
# agrega ``scripts/`` en vez de la raíz del checkout a su ruta de imports. Esa
# es precisamente la invocación pública de CI, por lo que preparamos la raíz de
# forma explícita antes de reutilizar el empaquetador.
RAIZ_CODIGO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ_CODIGO))

from scripts.empaquetar_produccion import (  # noqa: E402 - raíz preparada arriba
    RAIZ_REPOSITORIO,
    ejecutar_git,
    sha256_archivo,
)


class ErrorReproducibilidad(RuntimeError):
    """Indica que el mismo SHA produjo artefactos productivos diferentes."""


def _ejecutar_empaquetado(raiz: Path) -> None:
    """Ejecuta el comando público sin shell para incluir build y empaquetado."""

    subprocess.run(
        ["pnpm", "empaquetar:produccion"],
        cwd=raiz,
        check=True,
    )


def verificar_reproducibilidad(raiz: Path = RAIZ_REPOSITORIO) -> str:
    """Construye dos veces y devuelve el SHA-256 común o falla con diagnóstico.

    La primera pareja se preserva en un temporal fuera del checkout. Después de
    la segunda construcción se comparan bytes, no sólo nombres o manifests, de
    modo que cualquier metadata volátil dentro del tar provoque un error.
    """

    sha_commit = ejecutar_git("rev-parse", "HEAD", raiz=raiz)
    nombre_paquete = f"sis-leg-{sha_commit}.tar.gz"
    paquete = raiz / "dist/produccion" / nombre_paquete
    sidecar = paquete.with_name(f"{nombre_paquete}.sha256")

    with tempfile.TemporaryDirectory(prefix="sis-leg-reproducibilidad-") as temporal:
        temporal_path = Path(temporal)
        paquete_primero = temporal_path / nombre_paquete
        sidecar_primero = temporal_path / sidecar.name

        _ejecutar_empaquetado(raiz)
        shutil.copyfile(paquete, paquete_primero)
        shutil.copyfile(sidecar, sidecar_primero)

        _ejecutar_empaquetado(raiz)

        if paquete_primero.read_bytes() != paquete.read_bytes():
            raise ErrorReproducibilidad(
                "Dos ejecuciones completas produjeron paquetes tar diferentes para "
                f"el mismo SHA {sha_commit}."
            )
        if sidecar_primero.read_bytes() != sidecar.read_bytes():
            raise ErrorReproducibilidad(
                "Dos ejecuciones completas produjeron sidecars diferentes para "
                f"el mismo SHA {sha_commit}."
            )

    checksum = sha256_archivo(paquete)
    print(f"Reproducibilidad verificada para {sha_commit}: {checksum}")
    return checksum


def main() -> int:
    """Ejecuta el gate y conserva un exit code no cero ante cualquier diferencia."""

    verificar_reproducibilidad()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
