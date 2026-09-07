"""Auditoría de referencias al nombre legado del proyecto.

WP-077 renombró la identidad técnica de `Botonera2` a `SIS-Leg`. El riesgo permanente
después de un cambio así no es el estado del día del corte, sino la reintroducción
silenciosa del nombre viejo: alguien copia un fragmento antiguo, restaura un archivo de
una rama vieja o escribe una ruta de memoria, y la identidad vuelve a quedar mezclada.

Esta auditoría recorre todos los archivos de texto versionados y falla si el nombre legado
aparece fuera de una excepción explícita. Hay exactamente dos clases de excepción, y ninguna
de las dos es «excluir un directorio».

**Allowlist por ruta y conteo exacto.** Es la política por defecto y cubre archivos cuyo
contenido histórico ya está congelado: contratos de WP cerrados, pruebas de regresión que
usan el literal como valor bajo prueba, el manual y esta misma herramienta. Cada entrada
declara la ruta, cuántas ocurrencias se esperan allí y por qué son legítimas. El conteo es
parte del contrato: si un archivo permitido gana una ocurrencia nueva, la auditoría falla
igual que si el nombre apareciera en un archivo prohibido; y si pierde ocurrencias, también
falla, porque significa que la allowlist quedó desactualizada y está tapando más de lo que
hoy necesita cubrir.

**Registros históricos vivos.** Unos pocos documentos existen justamente para acumular
trazabilidad y siguen creciendo después del corte de identidad. `docs/implementation/PLAN.md`
es el caso claro: cada cierre de Work Package puede necesitar contar qué pasó con el nombre
o las rutas anteriores. Exigirles un conteo exacto convierte el gate en un obstáculo que se
rompe solo, y fue exactamente lo que ocurrió (hallazgo ASTRA-010, WP-079). Para esas rutas
--declaradas una por una, nunca por directorio-- la regla no es cuántas veces aparece el
nombre legado sino **cómo** aparece: cada línea que lo mencione debe mencionar además la
identidad vigente o una palabra que enmarque el pasado. Una línea que copie una referencia
activa, como una ruta de instalación o un módulo, no cumple esa condición y sigue fallando.

Ninguna de las dos políticas autoriza borrar o reescribir un hecho histórico para conseguir
verde: la historia es evidencia y el gate existe para protegerla, no para empujarla afuera.

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

# Categoría D - la auditoría misma y su contrato: necesitan el literal para poder buscarlo
# y para poder describir qué se sigue prohibiendo.
HERRAMIENTAS_DE_AUDITORIA = (
    ReferenciaPermitida(
        "scripts/auditar_identidad_legada.py",
        11,
        "Patrón de búsqueda, allowlist y mensajes de esta misma auditoría.",
    ),
    ReferenciaPermitida(
        "docs/work-packages/WP-079.md",
        1,
        "Contrato versionado de esta política; nombra el literal que debe seguir fallando.",
    ),
    ReferenciaPermitida(
        "tests/test_auditoria_identidad_legada.py",
        19,
        "Prueba que la auditoría detecte una reintroducción del nombre legado.",
    ),
)

ALLOWLIST: tuple[ReferenciaPermitida, ...] = (
    DOCUMENTACION_DE_MIGRACION
    + ENUNCIADOS_HISTORICOS
    + PRUEBAS_DE_AUSENCIA
    + HERRAMIENTAS_DE_AUDITORIA
)


@dataclass(frozen=True, slots=True)
class RegistroHistoricoVivo:
    """Una ruta documental que sigue acumulando trazabilidad sobre el pasado.

    A diferencia de `ReferenciaPermitida`, aquí no se declara un conteo: el documento está
    vivo y su cantidad de menciones cambia de forma legítima cada vez que se cierra un Work
    Package. Lo que sí se exige es la forma de cada mención, según la regla que implementa
    `linea_tiene_contexto_historico`. `motivo` explica por qué esta ruta concreta necesita
    esa política y no la del conteo exacto.
    """

    ruta: str
    motivo: str


# Vocabulario cerrado que marca una línea como enunciado sobre el pasado y no como uso
# activo de la identidad legada. Dos familias:
#
# 1. la identidad vigente en la misma línea (`SIS-Leg`, `sis-leg`, `sis_leg`, `sisleg`), que
#    aparece cuando la frase contrasta el nombre viejo con el nuevo o describe una migración
#    de una ruta a la otra;
# 2. palabras que enmarcan temporalmente la mención (`legado`, `histórico`, `anterior`,
#    `migración`, `renombrar`), que aparecen cuando la frase habla del estado previo.
#
# La comparación es en minúsculas y por subcadena, por eso alcanza con la raíz de cada
# palabra. `histor`/`histór` están las dos porque el acento cambia la subcadena real.
# Es un vocabulario deliberadamente corto: cada término agregado debilita el gate, así que
# ampliarlo exige la misma justificación que agregar una entrada a la allowlist.
MARCADORES_DE_CONTEXTO_HISTORICO: tuple[str, ...] = (
    "sis-leg",
    "sis_leg",
    "sisleg",
    "legad",
    "histor",
    "histór",
    "anterior",
    "migrac",
    "renombr",
)

# Registros históricos vivos declarados. La lista es corta a propósito: no es un mecanismo
# para excluir documentación, es una excepción por ruta con una regla de contenido propia.
REGISTROS_HISTORICOS_VIVOS: tuple[RegistroHistoricoVivo, ...] = (
    RegistroHistoricoVivo(
        "docs/implementation/PLAN.md",
        "Bitácora viva del plan: cada cierre de WP puede narrar qué pasó con el nombre o "
        "las rutas anteriores, así que su cantidad de menciones crece de forma legítima.",
    ),
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


def leer_lineas(ruta_relativa: str) -> list[str]:
    """Devuelve las líneas de un archivo de texto, o ninguna si no se puede leer.

    Comparte el criterio de `contar_ocurrencias`: un binario o una ruta inexistente no son
    un error de auditoría, simplemente no aportan texto que revisar.
    """

    ruta = RAIZ_REPOSITORIO / ruta_relativa
    try:
        return ruta.read_text(encoding="utf-8").splitlines()
    except (UnicodeDecodeError, FileNotFoundError):
        return []


def linea_tiene_contexto_historico(linea: str) -> bool:
    """Decide si una línea menciona el nombre legado *hablando del pasado*.

    La regla, deliberadamente simple para que sea auditable a ojo: la línea debe contener
    alguno de los `MARCADORES_DE_CONTEXTO_HISTORICO`. Así, «la migración de `/opt/botonera2`
    a `/opt/sis-leg` sigue pendiente» pasa, porque nombra la ruta nueva y la palabra
    «migración»; en cambio una línea que sólo dijera `WorkingDirectory=/opt/botonera2` no
    pasa, porque es indistinguible de una configuración activa copiada por error.

    No pretende entender el idioma: pretende obligar a que la mención venga acompañada de
    su marco. Es una condición necesaria, no una prueba de que el texto sea correcto.
    """

    minuscula = linea.lower()
    return any(marcador in minuscula for marcador in MARCADORES_DE_CONTEXTO_HISTORICO)


def _revisar_registro_vivo(
    registro: RegistroHistoricoVivo,
    leer: Callable[[str], list[str]],
) -> list[str]:
    """Revisa un registro histórico vivo línea por línea y describe lo que no encaja.

    Devuelve un problema por cada línea que nombre la identidad legada sin ningún marcador
    de contexto histórico. El mensaje incluye el número de línea y un recorte del texto para
    que quien lea la CI pueda ir directo al lugar sin tener que buscar el literal a mano.
    """

    problemas: list[str] = []
    for numero, linea in enumerate(leer(registro.ruta), start=1):
        if not PATRON_LEGADO.search(linea):
            continue
        if linea_tiene_contexto_historico(linea):
            continue
        recorte = linea.strip()
        if len(recorte) > 120:
            recorte = recorte[:117] + "..."
        problemas.append(
            f"{registro.ruta}:{numero}: nombra la identidad legada sin marco histórico. "
            "Una mención permitida en este registro debe nombrar además la identidad "
            "vigente o encuadrar el pasado (legado, histórico, anterior, migración, "
            f"renombrar). Línea: {recorte}"
        )
    return problemas


def auditar(
    *,
    archivos: Sequence[str] | None = None,
    permitidas: Sequence[ReferenciaPermitida] | None = None,
    contador: Callable[[str], int] | None = None,
    registros_vivos: Sequence[RegistroHistoricoVivo] | None = None,
    lector: Callable[[str], list[str]] | None = None,
) -> list[str]:
    """Compara el estado real del repositorio contra las dos políticas declaradas.

    Todos los parámetros existen para poder probar la auditoría con un repositorio
    sintético: por omisión mira los archivos versionados reales, la allowlist real, los
    registros vivos reales, el contador real y el lector real. Devuelve la lista de
    problemas encontrados, vacía si la identidad está limpia.

    Una ruta se clasifica en un único régimen. Si es registro histórico vivo se revisa línea
    por línea y no se le exige conteo; si está en la allowlist se le exige el conteo exacto;
    si no está en ninguna de las dos, cualquier ocurrencia es un problema.
    """

    entradas = tuple(ALLOWLIST if permitidas is None else permitidas)
    vivos = tuple(REGISTROS_HISTORICOS_VIVOS if registros_vivos is None else registros_vivos)
    rutas = listar_archivos_versionados() if archivos is None else list(archivos)
    contar = contar_ocurrencias if contador is None else contador
    leer = leer_lineas if lector is None else lector

    esperado = {entrada.ruta: entrada for entrada in entradas}
    vivos_por_ruta = {registro.ruta: registro for registro in vivos}
    problemas: list[str] = []

    for entrada in entradas:
        if archivos is None and not (RAIZ_REPOSITORIO / entrada.ruta).exists():
            problemas.append(
                f"{entrada.ruta}: la allowlist declara un archivo que ya no existe; "
                "quitá la entrada."
            )
        if not entrada.motivo.strip():
            problemas.append(f"{entrada.ruta}: la entrada de allowlist no declara motivo.")

    # Un registro vivo con conteo exacto sería contradictorio: las dos reglas se aplicarían
    # a la misma ruta y la primera anularía a la otra. Se detecta como error de política.
    for registro in vivos:
        if archivos is None and not (RAIZ_REPOSITORIO / registro.ruta).exists():
            problemas.append(
                f"{registro.ruta}: se declara registro histórico vivo un archivo que ya no "
                "existe; quitá la entrada."
            )
        if not registro.motivo.strip():
            problemas.append(f"{registro.ruta}: el registro histórico vivo no declara motivo.")
        if registro.ruta in esperado:
            problemas.append(
                f"{registro.ruta}: está declarada a la vez en la allowlist por conteo y "
                "como registro histórico vivo; elegí una sola política."
            )

    for ruta_relativa in rutas:
        registro = vivos_por_ruta.get(ruta_relativa)
        if registro is not None:
            problemas.extend(_revisar_registro_vivo(registro, leer))
            continue

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
        f"{permitidas} ocurrencia(s) históricas permitidas en {len(ALLOWLIST)} archivo(s) "
        f"con conteo exacto y {len(REGISTROS_HISTORICOS_VIVOS)} registro(s) histórico(s) "
        "vivo(s) revisado(s) línea por línea."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
