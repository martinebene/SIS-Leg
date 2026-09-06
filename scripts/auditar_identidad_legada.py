"""Auditoría de referencias al nombre legado del proyecto.

WP-077 renombró la identidad técnica de `Botonera2` a `SIS-Leg`. El riesgo permanente
después de un cambio así no es el estado del día del corte, sino la reintroducción
silenciosa del nombre viejo: alguien copia un fragmento antiguo, restaura un archivo de
una rama vieja o escribe una ruta de memoria, y la identidad vuelve a quedar mezclada.

Esta auditoría recorre todos los archivos de texto versionados y falla si el nombre legado
aparece fuera de una allowlist explícita. Cada entrada de la allowlist declara:

- la ruta exacta;
- cuántas ocurrencias se esperan allí;
- por qué esas ocurrencias son legítimas.

El conteo es parte del contrato. Si un archivo permitido gana una ocurrencia nueva, la
auditoría falla igual que si el nombre apareciera en un archivo prohibido; y si pierde
ocurrencias, también falla, porque significa que la allowlist quedó desactualizada y está
tapando más de lo que hoy necesita cubrir.

Uso:

    uv run python scripts/auditar_identidad_legada.py

Devuelve 0 si la identidad está limpia y 1 con un informe accionable si no lo está.
`tests/test_auditoria_identidad_legada.py` ejecuta lo mismo dentro de la suite.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

RAIZ_REPOSITORIO = Path(__file__).resolve().parents[1]

# El nombre legado se busca sin distinguir mayúsculas y sin frontera final, para que
# `botonera2`, `Botonera2`, `BOTONERA2_SHA`, `@botonera2/api-client`, `botonera2_backend` y
# `/opt/botonera2` cuenten igual. Importa que el `2` sea obligatorio: `martinebene/Botonera`
# es otro repositorio, el sistema histórico en producción, y `botonera` a secas es el nombre
# común del dispositivo físico que usan los concejales. Ninguno de los dos se renombra.
PATRON_LEGADO = re.compile(r"botonera2", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ReferenciaPermitida:
    """Una ruta que puede nombrar la identidad legada, y bajo qué condiciones.

    `ocurrencias` es la cantidad exacta que se espera encontrar hoy. `motivo` explica por
    qué reescribirlas sería incorrecto; sin ese motivo la entrada no debería existir.
    """

    ruta: str
    ocurrencias: int
    motivo: str


# Categoría A - documentación que existe para explicar la migración. Sin el nombre viejo
# estos archivos no cumplirían su función.
DOCUMENTACION_DE_MIGRACION = (
    ReferenciaPermitida(
        "docs/NOTA-LEGADO-BOTONERA2.md",
        26,
        "Nota canónica de legado: traduce el nombre histórico al vigente.",
    ),
    ReferenciaPermitida(
        "docs/MIGRACION-A-SIS-LEG.md",
        38,
        "Runbook de migración: opera sobre rutas, unidades y usuarios anteriores.",
    ),
    ReferenciaPermitida(
        "docs/work-packages/WP-077.md",
        29,
        "Contrato versionado del propio renombrado; define qué se sustituye por qué.",
    ),
    ReferenciaPermitida(
        "manual/index.html",
        2,
        "Apartado 12.7: explica a quien opera cómo migrar la instalación anterior.",
    ),
    ReferenciaPermitida(
        "README.md",
        2,
        "Presentación del proyecto: nombra el nombre histórico y remite a la nota de legado.",
    ),
    ReferenciaPermitida(
        "docs/07-configuracion-datos-y-assets.md",
        2,
        "Reglas de marca: distingue identidad vigente de nombre histórico.",
    ),
    ReferenciaPermitida(
        "AGENTS.md",
        2,
        "Autoridad documental: remite a la nota de legado y a esta auditoría.",
    ),
)

# Categoría B - enunciados históricos. Documentan que la marca vieja fue retirada; cambiar
# el nombre convertiría una afirmación verdadera sobre el pasado en una falsa.
ENUNCIADOS_HISTORICOS = (
    ReferenciaPermitida(
        "docs/work-packages/WP-036.md",
        2,
        "Criterio cerrado: la cabecera de Moderación dejó de mostrar el distintivo legado.",
    ),
    ReferenciaPermitida(
        "docs/work-packages/WP-059.md",
        2,
        "Criterio cerrado: la cabecera de Apoyo Técnico dejó de mostrar la marca legada.",
    ),
    ReferenciaPermitida(
        "docs/work-packages/WP-062.md",
        5,
        "Contrato que sustituyó la marca visible legada; describe el estado previo.",
    ),
    ReferenciaPermitida(
        "packages/frontend-shared/src/carga_inicial.html",
        1,
        "Comentario que explica qué palabra reemplazó el logo en la carga inicial.",
    ),
)

# Categoría C - pruebas de regresión que verifican la ausencia de la marca legada. El
# literal es el valor bajo prueba: sustituirlo dejaría el test comprobando otra cosa.
PRUEBAS_DE_AUSENCIA = (
    ReferenciaPermitida(
        "apps/recinto/tests/identidad_sisleg_wp062.test.ts",
        1,
        "Comprueba que la Pantalla del Recinto no muestre la marca legada.",
    ),
    ReferenciaPermitida(
        "apps/tecnico/tests/tecnico_wp059.test.ts",
        4,
        "Comprueba que la cabecera de Apoyo Técnico no muestre la marca legada.",
    ),
    ReferenciaPermitida(
        "packages/frontend-shared/tests/identidad_sisleg_wp062.test.ts",
        3,
        "Comprueba que la carga inicial no muestre la marca legada.",
    ),
    ReferenciaPermitida(
        "tests/playwright/apoyo_tecnico_wp059.spec.ts",
        1,
        "Comprobación en navegador de la cabecera de Apoyo Técnico.",
    ),
    ReferenciaPermitida(
        "tests/playwright/identidad_sisleg_wp062.spec.ts",
        1,
        "Comprobación en navegador del indicador de carga inicial.",
    ),
    ReferenciaPermitida(
        "tests/playwright/shell_moderacion.spec.ts",
        3,
        "Comprobación en navegador de la cabecera de Moderación.",
    ),
    ReferenciaPermitida(
        "tests/test_manual_usuario.py",
        1,
        "Acota el nombre legado del manual al apartado de migración.",
    ),
)

# Categoría D - la auditoría misma, que necesita el literal para poder buscarlo.
HERRAMIENTAS_DE_AUDITORIA = (
    ReferenciaPermitida(
        "scripts/auditar_identidad_legada.py",
        9,
        "Patrón de búsqueda, allowlist y mensajes de esta misma auditoría.",
    ),
    ReferenciaPermitida(
        "tests/test_auditoria_identidad_legada.py",
        5,
        "Prueba que la auditoría detecte una reintroducción del nombre legado.",
    ),
)

ALLOWLIST: tuple[ReferenciaPermitida, ...] = (
    DOCUMENTACION_DE_MIGRACION
    + ENUNCIADOS_HISTORICOS
    + PRUEBAS_DE_AUSENCIA
    + HERRAMIENTAS_DE_AUDITORIA
)


def listar_archivos_versionados() -> list[str]:
    """Devuelve las rutas versionadas, que son el universo auditable.

    Se usa `git ls-files` en lugar de recorrer el disco para no auditar artefactos de
    build, dependencias instaladas ni configuración runtime local ignorada.
    """

    salida = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=RAIZ_REPOSITORIO,
        capture_output=True,
        text=True,
        check=True,
    )
    return [ruta for ruta in salida.stdout.split("\0") if ruta]


def contar_ocurrencias(ruta_relativa: str) -> int:
    """Cuenta apariciones del nombre legado en un archivo de texto.

    Los archivos binarios (imágenes, sonidos) se saltean devolviendo 0: no contienen texto
    auditable y decodificarlos sólo produciría ruido.
    """

    ruta = RAIZ_REPOSITORIO / ruta_relativa
    try:
        contenido = ruta.read_text(encoding="utf-8")
    except (UnicodeDecodeError, FileNotFoundError):
        return 0
    return len(PATRON_LEGADO.findall(contenido))


def auditar(
    *,
    archivos: Sequence[str] | None = None,
    permitidas: Sequence[ReferenciaPermitida] | None = None,
    contador: Callable[[str], int] | None = None,
) -> list[str]:
    """Compara el estado real del repositorio contra la allowlist declarada.

    Los tres parámetros existen para poder probar la auditoría con un repositorio
    sintético: por omisión mira los archivos versionados reales, la allowlist real y el
    contador real. Devuelve la lista de problemas encontrados, vacía si la identidad está
    limpia.
    """

    entradas = tuple(ALLOWLIST if permitidas is None else permitidas)
    rutas = listar_archivos_versionados() if archivos is None else list(archivos)
    contar = contar_ocurrencias if contador is None else contador

    esperado = {entrada.ruta: entrada for entrada in entradas}
    problemas: list[str] = []

    for entrada in entradas:
        if archivos is None and not (RAIZ_REPOSITORIO / entrada.ruta).exists():
            problemas.append(
                f"{entrada.ruta}: la allowlist declara un archivo que ya no existe; "
                "quitá la entrada."
            )
        if not entrada.motivo.strip():
            problemas.append(f"{entrada.ruta}: la entrada de allowlist no declara motivo.")

    for ruta_relativa in rutas:
        encontradas = contar(ruta_relativa)
        entrada = esperado.get(ruta_relativa)

        if entrada is None:
            if encontradas:
                problemas.append(
                    f"{ruta_relativa}: {encontradas} referencia(s) al nombre legado en un "
                    "archivo no permitido. Usá la identidad SIS-Leg o justificá la "
                    "excepción en la allowlist de esta auditoría."
                )
            continue

        if encontradas > entrada.ocurrencias:
            problemas.append(
                f"{ruta_relativa}: {encontradas} referencia(s) al nombre legado, se esperaban "
                f"{entrada.ocurrencias}. Motivo declarado: {entrada.motivo}"
            )
        elif encontradas < entrada.ocurrencias:
            problemas.append(
                f"{ruta_relativa}: quedan {encontradas} referencia(s) al nombre legado pero la "
                f"allowlist declara {entrada.ocurrencias}. Actualizá el conteo."
            )

    return problemas


def main() -> int:
    """Punto de entrada de línea de comandos."""

    problemas = auditar()
    if problemas:
        print("Auditoría de identidad legada: FALLA", file=sys.stderr)
        for problema in problemas:
            print(f"  - {problema}", file=sys.stderr)
        return 1

    permitidas = sum(entrada.ocurrencias for entrada in ALLOWLIST)
    print(
        "Auditoría de identidad legada OK: ninguna referencia activa al nombre anterior. "
        f"{permitidas} ocurrencia(s) históricas permitidas en {len(ALLOWLIST)} archivo(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
