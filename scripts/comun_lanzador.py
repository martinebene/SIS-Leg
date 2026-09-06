"""Lógica y validaciones comunes para los lanzadores de Work Packages.

Este módulo centraliza las puertas de seguridad compartidas entre el lanzador
genérico (scripts/iniciar_wp.py) y el lanzador específico para Orca
(scripts/iniciar_wp_orca.py), asegurando que ambos apliquen estrictamente
las mismas validaciones documentales, de estado Git y de dependencias.
"""

from __future__ import annotations

import re
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path


class ErrorInicioWP(RuntimeError):
    """Representa una precondición incumplida para iniciar un Work Package."""


@dataclass(frozen=True)
class FilaPlan:
    """Resume la autorización operativa de un WP extraída de la tabla de PLAN.md.

    Atributos:
        estado: Estado del WP en el plan (por ejemplo 'EN_CURSO', 'INTEGRADO').
        agente: Nombre del agente asignado al WP (por ejemplo 'codex', 'antigravity').
    """

    estado: str
    agente: str


@dataclass(frozen=True)
class WorktreeGit:
    """Describe una entrada relevante de ``git worktree list --porcelain``.

    Atributos:
        ruta: Ruta absoluta del directorio de trabajo en disco.
        rama: Nombre corto de la rama asociada (o None si es detached).
    """

    ruta: Path
    rama: str | None


def ejecutar_git(
    raiz: Path,
    *argumentos: str,
    verificar: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Ejecuta un comando de Git en ``raiz`` y devuelve el resultado textual.

    Parámetros:
        raiz: Directorio sobre el cual se ejecuta el comando de Git.
        *argumentos: Lista de argumentos que se pasarán a 'git'.
        verificar: Si es True y el código de retorno no es 0, lanza ErrorInicioWP.

    Retorna:
        CompletedProcess con la salida capturada en modo texto.
    """
    resultado = subprocess.run(
        ["git", *argumentos],
        cwd=raiz,
        check=False,
        capture_output=True,
        text=True,
    )
    if verificar and resultado.returncode != 0:
        detalle = resultado.stderr.strip() or resultado.stdout.strip() or "sin detalle"
        raise ErrorInicioWP(f"Git no pudo ejecutar {' '.join(argumentos)}: {detalle}")
    return resultado


def normalizar_numero_wp(valor: str) -> str:
    """Convierte un identificador como '1', '30' o '030' a tres dígitos ('001', '030').

    Parámetros:
        valor: Cadena con el número de WP ingresado por el operador.

    Retorna:
        Identificador normalizado de tres dígitos.
    """
    if not valor.isdecimal() or not 1 <= int(valor) <= 999:
        raise ErrorInicioWP("El WP debe indicarse con un número entre 001 y 999.")
    return f"{int(valor):03d}"


def validar_checkout_coordinador(raiz_esperada: Path) -> None:
    """Exige que el comando se ejecute desde la raíz del checkout coordinador en main y limpio.

    Comprueba que:
    1. El directorio actual sea la raíz de un repositorio Git.
    2. La rama activa sea exactamente 'main'.
    3. No existan cambios locales sin confirmar ni archivos untracked.

    Parámetros:
        raiz_esperada: Ruta esperada del checkout coordinador.
    """
    resultado_raiz = ejecutar_git(raiz_esperada, "rev-parse", "--show-toplevel")
    raiz_git = Path(resultado_raiz.stdout.strip()).resolve()
    if raiz_git != raiz_esperada.resolve():
        raise ErrorInicioWP(
            "Ejecutá el lanzador desde la raíz del checkout coordinador de SIS-Leg."
        )

    rama = ejecutar_git(raiz_esperada, "branch", "--show-current").stdout.strip()
    if rama != "main":
        raise ErrorInicioWP(f"El checkout coordinador debe estar en main; rama actual: {rama!r}.")

    if ejecutar_git(raiz_esperada, "status", "--porcelain").stdout.strip():
        raise ErrorInicioWP(
            "main tiene cambios locales; confirmalos o retiralos antes de iniciar un WP."
        )


def actualizar_main(raiz: Path) -> str:
    """Actualiza referencias remotas y adelanta ``main`` únicamente por fast-forward.

    Parámetros:
        raiz: Raíz del repositorio coordinador.

    Retorna:
        El SHA de 40 caracteres correspondiente a 'origin/main'.
    """
    ejecutar_git(raiz, "remote", "get-url", "origin")
    ejecutar_git(raiz, "fetch", "--prune", "origin")
    ejecutar_git(raiz, "merge", "--ff-only", "origin/main")

    actual = ejecutar_git(raiz, "rev-parse", "HEAD").stdout.strip()
    remoto = ejecutar_git(raiz, "rev-parse", "origin/main").stdout.strip()
    if actual != remoto:
        raise ErrorInicioWP(
            "main no coincide con origin/main después del fast-forward; revisá los commits locales."
        )
    return remoto


def extraer_seccion(texto: str, titulo: str) -> str:
    """Obtiene el contenido textual de una sección Markdown de segundo nivel (## Título).

    Parámetros:
        texto: Documento Markdown completo.
        titulo: Título exacto de la sección buscada.

    Retorna:
        Texto contenido dentro de esa sección hasta el próximo encabezado ##.
    """
    patron = re.compile(
        rf"^## {re.escape(titulo)}\s*$\n(?P<contenido>.*?)(?=^##\s|\Z)",
        flags=re.MULTILINE | re.DOTALL,
    )
    coincidencia = patron.search(texto)
    if coincidencia is None:
        raise ErrorInicioWP(f"El documento no contiene la sección obligatoria {titulo!r}.")
    return coincidencia.group("contenido")


def leer_wp(raiz: Path, numero_wp: str) -> tuple[Path, str, list[str]]:
    """Valida aprobación documental, obtiene el título y extrae dependencias del WP.

    Parámetros:
        raiz: Raíz del repositorio coordinador.
        numero_wp: Identificador normalizado de tres dígitos (ej. '030').

    Retorna:
        Tupla con (ruta_al_archivo, titulo_del_wp, lista_de_dependencias).
    """
    ruta_wp = raiz / "docs" / "work-packages" / f"WP-{numero_wp}.md"
    if not ruta_wp.is_file():
        raise ErrorInicioWP(f"No existe {ruta_wp.relative_to(raiz)}.")

    texto = ruta_wp.read_text(encoding="utf-8")
    estado = extraer_seccion(texto, "Estado documental")
    if not re.search(r"`APROBADO`", estado):
        raise ErrorInicioWP(f"WP-{numero_wp} no tiene estado documental APROBADO.")

    encabezado = re.search(rf"^# WP-{numero_wp} - (?P<titulo>.+)$", texto, re.MULTILINE)
    if encabezado is None:
        raise ErrorInicioWP(f"WP-{numero_wp} no tiene el encabezado canónico esperado.")

    seccion_dependencias = extraer_seccion(texto, "Dependencias")
    dependencias = sorted(
        {
            dependencia
            for dependencia in re.findall(r"\bWP-(\d{3})\b", seccion_dependencias)
            if dependencia != numero_wp
        }
    )
    return ruta_wp, encabezado.group("titulo").strip(), dependencias


def leer_plan(raiz: Path) -> dict[str, FilaPlan]:
    """Interpreta las filas de Work Packages en docs/implementation/PLAN.md.

    Parámetros:
        raiz: Raíz del repositorio coordinador.

    Retorna:
        Diccionario asociando número de WP ('001', '030') con su FilaPlan.
    """
    ruta_plan = raiz / "docs" / "implementation" / "PLAN.md"
    if not ruta_plan.is_file():
        raise ErrorInicioWP("No existe docs/implementation/PLAN.md.")

    filas: dict[str, FilaPlan] = {}
    for linea in ruta_plan.read_text(encoding="utf-8").splitlines():
        columnas = [columna.strip() for columna in linea.strip().strip("|").split("|")]
        if len(columnas) < 5 or re.fullmatch(r"WP-\d{3}", columnas[0]) is None:
            continue
        numero = columnas[0].removeprefix("WP-")
        filas[numero] = FilaPlan(estado=columnas[2], agente=columnas[4])
    return filas


def validar_autorizacion(
    numero_wp: str,
    agente_solicitado: str,
    dependencias: list[str],
    filas_plan: dict[str, FilaPlan],
) -> None:
    """Comprueba que el WP figure EN_CURSO, con el agente asignado y dependencias integradas.

    Parámetros:
        numero_wp: Número de tres dígitos del WP.
        agente_solicitado: Nombre del agente que se desea lanzar.
        dependencias: Lista de números de WP que deben estar INTEGRADO.
        filas_plan: Tabla de filas leída desde PLAN.md.
    """
    fila = filas_plan.get(numero_wp)
    if fila is None:
        raise ErrorInicioWP(f"WP-{numero_wp} no figura en PLAN.md.")
    if fila.estado != "EN_CURSO":
        raise ErrorInicioWP(
            f"WP-{numero_wp} debe figurar EN_CURSO en PLAN.md; figura {fila.estado!r}."
        )
    if fila.agente.casefold() != agente_solicitado.casefold():
        raise ErrorInicioWP(
            f"WP-{numero_wp} está asignado a {fila.agente!r}, no a {agente_solicitado!r}."
        )

    no_integradas = [
        f"WP-{dependencia}"
        for dependencia in dependencias
        if filas_plan.get(dependencia) is None or filas_plan[dependencia].estado != "INTEGRADO"
    ]
    if no_integradas:
        raise ErrorInicioWP(
            "Dependencias todavía no integradas en PLAN.md: " + ", ".join(no_integradas) + "."
        )


def crear_slug(titulo: str) -> str:
    """Deriva un segmento de texto seguro para ramas Git a partir del título del WP.

    Elimina acentos y caracteres especiales, convirtiendo espacios y símbolos a guiones.

    Parámetros:
        titulo: Título descriptivo del WP.

    Retorna:
        Slug en minúsculas de hasta 56 caracteres.
    """
    sin_marcas = "".join(
        caracter
        for caracter in unicodedata.normalize("NFKD", titulo)
        if not unicodedata.combining(caracter)
    )
    slug = re.sub(r"[^a-z0-9]+", "-", sin_marcas.casefold()).strip("-")
    slug = slug[:56].rstrip("-")
    if not slug:
        raise ErrorInicioWP("El título del WP no permite construir un nombre de rama válido.")
    return slug


def listar_worktrees(raiz: Path) -> list[WorktreeGit]:
    """Lista todos los worktrees de Git registrados en el repositorio local.

    Parámetros:
        raiz: Raíz del repositorio coordinador.

    Retorna:
        Lista de objetos WorktreeGit con la ruta y la rama asociada.
    """
    salida = ejecutar_git(raiz, "worktree", "list", "--porcelain").stdout
    worktrees: list[WorktreeGit] = []
    for bloque in salida.strip().split("\n\n"):
        if not bloque.strip():
            continue
        valores: dict[str, str] = {}
        for linea in bloque.splitlines():
            clave, _, valor = linea.partition(" ")
            valores[clave] = valor
        rama_completa = valores.get("branch")
        rama = rama_completa.removeprefix("refs/heads/") if rama_completa else None
        worktrees.append(WorktreeGit(ruta=Path(valores["worktree"]).resolve(), rama=rama))
    return worktrees
