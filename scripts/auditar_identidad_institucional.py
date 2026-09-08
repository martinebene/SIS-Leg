"""Auditoría de referencias activas a la institución de origen.

WP-084 desacopló SIS-Leg del cuerpo legislativo concreto para el que nació: el
nombre institucional pasó a `config/system.toml`, la plantilla del padrón dejó de
traer personas y bloques reales, y la documentación activa habla de «cuerpo
legislativo» cuando describe la institución en abstracto.

El riesgo permanente después de un cambio así no es el estado del día del corte
sino la reintroducción silenciosa: alguien copia un fragmento viejo, restaura un
archivo de una rama anterior o escribe de memoria el nombre que conocía, y el
producto vuelve a quedar atado a una única instalación.

Esta auditoría recorre todos los archivos de texto versionados y falla si alguno
de los términos locales aparece fuera de una excepción explícita.

## Qué se busca y por qué

Tres familias de términos, cada una con su motivo:

- **`Madryn`** cubre la ciudad y cualquier nombre derivado, incluido el de un
  bloque político local. Es la referencia geográfica directa.
- **`Chubut`** cubre la provincia y los bloques que la nombran. No estaba en la
  lista original del WP, pero `tests/test_manual_usuario.py` ya la prohibía en el
  manual por exactamente el mismo motivo, y la plantilla del padrón la traía en
  dos bloques reales.
- **`Concejo Deliberante`** es el caso distinto: no es un error escribirlo, es un
  error escribirlo **cuando el texto describe la institución en abstracto**. Ahí
  corresponde «cuerpo legislativo», que es el término que deja la documentación
  reutilizable. La palabra suelta `concejal` no se audita: es vocabulario de
  dominio del padrón, de los contratos y de los CSV, y renombrarla estaba
  explícitamente fuera del alcance del WP.

## Las dos clases de excepción

**Allowlist por ruta y conteo exacto.** Es la única política, y cubre archivos
cuyo contenido histórico ya está congelado: contratos de Work Packages cerrados,
pruebas de regresión que usan el literal como valor bajo prueba, y esta misma
herramienta. Cada entrada declara la ruta, cuántas ocurrencias se esperan y por
qué son legítimas. El conteo es parte del contrato: si un archivo permitido gana
una ocurrencia nueva, la auditoría falla igual que si el término apareciera en un
archivo prohibido; y si pierde ocurrencias, también falla, porque significa que la
allowlist quedó desactualizada y está tapando más de lo que hoy necesita cubrir.

Deliberadamente **no** existe una política de «excluir un directorio». Excluir
`docs/work-packages/` entero convertiría el gate en decorativo: cualquier
documento nuevo podría reintroducir el acoplamiento sin que nadie se enterara.

Ninguna excepción autoriza borrar o reescribir un hecho histórico para conseguir
verde: los Work Packages cerrados y las decisiones son evidencia inmutable, y el
gate existe para protegerlos, no para empujarlos afuera.

Uso:

    uv run python scripts/auditar_identidad_institucional.py

Devuelve 0 si la identidad activa está limpia y 1 con un informe accionable si no
lo está. `tests/test_auditoria_identidad_institucional.py` ejecuta lo mismo dentro
de la suite.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

RAIZ_REPOSITORIO = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class TerminoAuditado:
    """Un término local que no debe reaparecer en material activo.

    `patron` se compila sin distinguir mayúsculas porque la reintroducción
    tampoco las distingue: `madryn` en una ruta y `Madryn` en un título son el
    mismo problema. `explicacion` es lo que se le muestra a quien recibe el fallo
    en la CI, y por eso dice qué escribir en su lugar y no sólo qué está mal.
    """

    nombre: str
    patron: re.Pattern[str]
    explicacion: str


TERMINOS: tuple[TerminoAuditado, ...] = (
    TerminoAuditado(
        "Madryn",
        re.compile(r"madryn", re.IGNORECASE),
        "Nombra la ciudad de la instalación de origen. En material activo, el nombre "
        "institucional se configura en [institucion] de config/system.toml y los datos de "
        "ejemplo deben ser ficticios.",
    ),
    TerminoAuditado(
        "Chubut",
        re.compile(r"chubut", re.IGNORECASE),
        "Nombra la provincia de la instalación de origen, normalmente dentro de un bloque "
        "político real. Los bloques de ejemplo deben ser ficticios.",
    ),
    TerminoAuditado(
        "Concejo Deliberante",
        re.compile(r"concejo\s+deliberante", re.IGNORECASE),
        "Describe una institución concreta. Cuando el texto habla de la institución en "
        "abstracto corresponde «cuerpo legislativo», que es lo que permite reutilizar la "
        "documentación en otra instalación.",
    ),
)


@dataclass(frozen=True, slots=True)
class ReferenciaPermitida:
    """Una ruta que puede nombrar un término local, y bajo qué condiciones.

    `ocurrencias` mapea el nombre de cada término a la cantidad exacta que se
    espera encontrar hoy en ese archivo. Un término que no figura en el mapa debe
    tener cero ocurrencias, así que una entrada nunca abre el archivo entero.
    `motivo` explica por qué reescribirlas sería incorrecto; sin ese motivo la
    entrada no debería existir.
    """

    ruta: str
    ocurrencias: dict[str, int]
    motivo: str


# Categoría A - contratos de Work Packages cerrados. Describen decisiones ya
# tomadas y el estado del sistema en el momento en que se tomaron. Cambiarles el
# texto convertiría una afirmación verdadera sobre el pasado en una falsa.
CONTRATOS_CERRADOS: tuple[ReferenciaPermitida, ...] = (
    ReferenciaPermitida(
        "docs/work-packages/WP-039.md",
        {"Madryn": 2, "Concejo Deliberante": 2},
        "Contrato cerrado que fijó la cabecera pública con el nombre entonces hardcodeado.",
    ),
    ReferenciaPermitida(
        "docs/work-packages/WP-043.md",
        {"Madryn": 4, "Chubut": 7},
        "Contrato cerrado que incorporó el padrón recuperado de producción; el bloque de "
        "datos es la evidencia de esa recuperación.",
    ),
    ReferenciaPermitida(
        "docs/work-packages/WP-050.md",
        {"Madryn": 1, "Concejo Deliberante": 1},
        "Contrato cerrado que condensó la cabecera; enumera el texto central de entonces.",
    ),
    ReferenciaPermitida(
        "docs/work-packages/WP-058.md",
        {"Madryn": 1, "Concejo Deliberante": 1},
        "Contrato cerrado de legibilidad; midió la frase central tal como existía.",
    ),
    ReferenciaPermitida(
        "docs/work-packages/WP-067.md",
        {"Madryn": 3, "Concejo Deliberante": 1},
        "Contrato cerrado del manual; declara qué institución no debía particularizar.",
    ),
    ReferenciaPermitida(
        "docs/work-packages/WP-084.md",
        {"Madryn": 6, "Concejo Deliberante": 3},
        "Contrato versionado de esta misma generalización; nombra los términos que deben "
        "dejar de aparecer.",
    ),
)

# Categoría B - pruebas y herramientas que usan el literal como valor bajo
# prueba. Sustituirlo dejaría el test comprobando otra cosa.
PRUEBAS_Y_HERRAMIENTAS: tuple[ReferenciaPermitida, ...] = (
    ReferenciaPermitida(
        "tests/test_manual_usuario.py",
        {"Madryn": 1, "Chubut": 1, "Concejo Deliberante": 1},
        "Lista de términos prohibidos del manual: el literal es el valor bajo prueba.",
    ),
    ReferenciaPermitida(
        "scripts/auditar_identidad_institucional.py",
        {"Madryn": 14, "Chubut": 7, "Concejo Deliberante": 10},
        "Patrones de búsqueda, allowlist y mensajes de esta misma auditoría.",
    ),
    ReferenciaPermitida(
        "tests/test_auditoria_identidad_institucional.py",
        {"Madryn": 15, "Chubut": 4, "Concejo Deliberante": 3},
        "Prueba que la auditoría detecte una reintroducción de cada término.",
    ),
)

ALLOWLIST: tuple[ReferenciaPermitida, ...] = CONTRATOS_CERRADOS + PRUEBAS_Y_HERRAMIENTAS


def listar_archivos_versionados() -> list[str]:
    """Devuelve las rutas versionadas, que son el universo auditable.

    Se usa `git ls-files` en lugar de recorrer el disco para no auditar
    artefactos de build, dependencias instaladas ni la configuración runtime
    local ignorada: `config/system.toml` y `config/concejales.csv` contienen
    justamente los datos reales de cada instalación y no se versionan.
    """

    salida = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=RAIZ_REPOSITORIO,
        capture_output=True,
        text=True,
        check=True,
    )
    return [ruta for ruta in salida.stdout.split("\0") if ruta]


def contar_ocurrencias(ruta_relativa: str) -> dict[str, int]:
    """Cuenta apariciones de cada término auditado en un archivo de texto.

    Los archivos binarios (imágenes, sonidos) se saltean devolviendo un conteo
    vacío: no contienen texto auditable y decodificarlos sólo produciría ruido.
    """

    ruta = RAIZ_REPOSITORIO / ruta_relativa
    try:
        contenido = ruta.read_text(encoding="utf-8")
    except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
        return {}
    return {
        termino.nombre: len(termino.patron.findall(contenido))
        for termino in TERMINOS
        if termino.patron.search(contenido) is not None
    }


def _explicacion(nombre: str) -> str:
    """Devuelve el texto de ayuda del término, para no repetirlo en cada mensaje."""

    for termino in TERMINOS:
        if termino.nombre == nombre:
            return termino.explicacion
    return ""


def auditar(
    *,
    archivos: Sequence[str] | None = None,
    permitidas: Sequence[ReferenciaPermitida] | None = None,
    contador: Callable[[str], dict[str, int]] | None = None,
) -> list[str]:
    """Compara el estado real del repositorio contra la allowlist declarada.

    Todos los parámetros existen para poder probar la auditoría con un
    repositorio sintético: por omisión mira los archivos versionados reales, la
    allowlist real y el contador real. Devuelve la lista de problemas
    encontrados, vacía si el material activo está limpio.

    Se informan tres clases de problema, y las tres importan por igual:

    - una ocurrencia en un archivo que no está en la allowlist;
    - más ocurrencias de las declaradas en un archivo permitido, que es una
      reintroducción escondida detrás de una excepción legítima;
    - menos ocurrencias de las declaradas, que significa que la excepción cubre
      más de lo que hoy hace falta y hay que ajustar el conteo.
    """

    entradas = tuple(ALLOWLIST if permitidas is None else permitidas)
    rutas = listar_archivos_versionados() if archivos is None else list(archivos)
    contar = contar_ocurrencias if contador is None else contador

    esperado = {entrada.ruta: entrada for entrada in entradas}
    problemas: list[str] = []

    nombres_validos = {termino.nombre for termino in TERMINOS}
    for entrada in entradas:
        if archivos is None and not (RAIZ_REPOSITORIO / entrada.ruta).exists():
            problemas.append(
                f"{entrada.ruta}: la allowlist declara un archivo que ya no existe; "
                "quitá la entrada."
            )
        if not entrada.motivo.strip():
            problemas.append(f"{entrada.ruta}: la entrada de allowlist no declara motivo.")
        for nombre in entrada.ocurrencias:
            if nombre not in nombres_validos:
                problemas.append(
                    f"{entrada.ruta}: la allowlist declara «{nombre}», que no es un término "
                    "auditado. Corregí el nombre o agregá el término."
                )

    for ruta_relativa in rutas:
        encontradas = contar(ruta_relativa)
        entrada = esperado.get(ruta_relativa)
        declaradas = entrada.ocurrencias if entrada is not None else {}

        for nombre in sorted(set(encontradas) | set(declaradas)):
            cantidad = encontradas.get(nombre, 0)
            permitidas_aqui = declaradas.get(nombre, 0)
            if cantidad == permitidas_aqui:
                continue
            if permitidas_aqui == 0:
                problemas.append(
                    f"{ruta_relativa}: {cantidad} referencia(s) a «{nombre}» en un archivo "
                    f"no permitido. {_explicacion(nombre)}"
                )
            elif cantidad > permitidas_aqui:
                problemas.append(
                    f"{ruta_relativa}: {cantidad} referencia(s) a «{nombre}», se esperaban "
                    f"{permitidas_aqui}. Motivo declarado: {entrada.motivo}"
                    if entrada is not None
                    else ""
                )
            else:
                problemas.append(
                    f"{ruta_relativa}: quedan {cantidad} referencia(s) a «{nombre}» pero la "
                    f"allowlist declara {permitidas_aqui}. Actualizá el conteo."
                )

    return problemas


def main() -> int:
    """Punto de entrada de línea de comandos."""

    problemas = auditar()
    if problemas:
        print("Auditoría de identidad institucional: FALLA", file=sys.stderr)
        for problema in problemas:
            print(f"  - {problema}", file=sys.stderr)
        return 1

    total = sum(sum(entrada.ocurrencias.values()) for entrada in ALLOWLIST)
    print(
        "Auditoría de identidad institucional OK: ninguna referencia activa a la institución "
        f"de origen. {total} ocurrencia(s) históricas permitidas en {len(ALLOWLIST)} "
        "archivo(s) con conteo exacto."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
