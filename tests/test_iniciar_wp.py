"""Pruebas de regresión del lanzador genérico definido por DEC-002.

Cada escenario crea repositorios Git temporales reales. Así se ejercitan los
comandos de rama y worktree sin tocar el repositorio de desarrollo ni simular
la parte más delicada del flujo.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

DIRECTORIO_SCRIPTS = Path(__file__).parents[1] / "scripts"
RUTA_LANZADOR = DIRECTORIO_SCRIPTS / "iniciar_wp.py"


@dataclass(frozen=True)
class RepositorioPrueba:
    """Agrupa las rutas aisladas que necesita cada escenario del lanzador."""

    coordinador: Path
    remoto: Path
    registro_cli: Path
    entorno: dict[str, str]


def ejecutar(
    *argumentos: str,
    cwd: Path,
    entorno: dict[str, str] | None = None,
    verificar: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Ejecuta un comando de prueba y muestra su salida al fallar inesperadamente."""
    resultado = subprocess.run(
        list(argumentos),
        cwd=cwd,
        env=entorno,
        check=False,
        capture_output=True,
        text=True,
    )
    if verificar and resultado.returncode != 0:
        detalle = (
            f"Falló {' '.join(argumentos)}\n"
            f"stdout:\n{resultado.stdout}\n"
            f"stderr:\n{resultado.stderr}"
        )
        raise AssertionError(detalle)
    return resultado


def contenido_wp(*, aprobado: bool = True, dependencia: bool = True) -> str:
    """Construye el contrato mínimo que el parser debe reconocer."""
    estado = "APROBADO" if aprobado else "BORRADOR"
    dependencias = "- WP-001 integrado.\n" if dependencia else "- Ninguna.\n"
    return f"""# WP-002 - Runtime base de prueba

## Estado documental

`{estado}`

## Dependencias

{dependencias}
## Alcance

- Contenido de prueba.
"""


def contenido_plan(
    *, estado_wp: str = "EN_CURSO", agente: str = "Codex", integrado: bool = True
) -> str:
    """Construye filas equivalentes a las del PLAN canónico."""
    estado_dependencia = "INTEGRADO" if integrado else "EN_CURSO"
    return f"""# Plan de prueba

| WP | Objetivo | Estado | Depende de | Agente |
|---|---|---|---|---|
| WP-001 | Base | {estado_dependencia} | - | Codex |
| WP-002 | Runtime | {estado_wp} | WP-001 | {agente} |
"""


def crear_repositorio(
    tmp_path: Path,
    *,
    aprobado: bool = True,
    estado_wp: str = "EN_CURSO",
    agente: str = "Codex",
    dependencia_integrada: bool = True,
) -> RepositorioPrueba:
    """Crea un remoto local, un clon coordinador y una CLI inofensiva.

    La CLI falsa solo registra su directorio actual. Esto demuestra que el
    lanzador abre el agente dentro del worktree sin iniciar un agente real.
    """
    semilla = tmp_path / "semilla"
    semilla.mkdir()
    ejecutar("git", "init", "--initial-branch=main", cwd=semilla)
    ejecutar("git", "config", "user.name", "Pruebas SIS-Leg", cwd=semilla)
    ejecutar("git", "config", "user.email", "pruebas@example.invalid", cwd=semilla)

    (semilla / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")
    (semilla / "docs" / "work-packages").mkdir(parents=True)
    (semilla / "docs" / "implementation").mkdir(parents=True)
    (semilla / "scripts").mkdir()

    # Copiar todos los scripts auxiliares del repositorio para mantener el paquete
    for archivo_script in DIRECTORIO_SCRIPTS.glob("*.py"):
        shutil.copy2(archivo_script, semilla / "scripts" / archivo_script.name)

    (semilla / "docs" / "work-packages" / "WP-002.md").write_text(
        contenido_wp(aprobado=aprobado), encoding="utf-8"
    )
    (semilla / "docs" / "implementation" / "PLAN.md").write_text(
        contenido_plan(
            estado_wp=estado_wp,
            agente=agente,
            integrado=dependencia_integrada,
        ),
        encoding="utf-8",
    )
    ejecutar("git", "add", ".", cwd=semilla)
    ejecutar("git", "commit", "-m", "test: escenario inicial", cwd=semilla)

    remoto = tmp_path / "remoto.git"
    ejecutar("git", "clone", "--bare", str(semilla), str(remoto), cwd=tmp_path)
    coordinador = tmp_path / "coordinador"
    ejecutar("git", "clone", str(remoto), str(coordinador), cwd=tmp_path)

    directorio_cli = tmp_path / "bin"
    directorio_cli.mkdir()
    registro_cli = tmp_path / "registro-cli.txt"
    cli = directorio_cli / "codex"
    cli.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        "from pathlib import Path\n"
        "Path(os.environ['REGISTRO_CLI']).write_text(str(Path.cwd()), encoding='utf-8')\n",
        encoding="utf-8",
    )
    cli.chmod(cli.stat().st_mode | stat.S_IXUSR)

    ruta_git = shutil.which("git")
    if ruta_git is not None:
        (directorio_cli / "git").symlink_to(ruta_git)
    (directorio_cli / "python3").symlink_to(sys.executable)

    entorno = os.environ.copy()
    entorno["PATH"] = os.pathsep.join((str(directorio_cli), entorno.get("PATH", "")))
    entorno["REGISTRO_CLI"] = str(registro_cli)
    entorno["PYTHONDONTWRITEBYTECODE"] = "1"
    return RepositorioPrueba(coordinador, remoto, registro_cli, entorno)


def lanzar(
    repositorio: RepositorioPrueba,
    *,
    agente: str = "codex",
    entorno: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoca el script exactamente como lo haría el operador."""
    return ejecutar(
        sys.executable,
        "scripts/iniciar_wp.py",
        "002",
        agente,
        cwd=repositorio.coordinador,
        entorno=entorno or repositorio.entorno,
        verificar=False,
    )


def test_rechaza_rama_distinta_de_main(tmp_path: Path) -> None:
    repositorio = crear_repositorio(tmp_path)
    ejecutar("git", "switch", "-c", "otra-rama", cwd=repositorio.coordinador)

    resultado = lanzar(repositorio)

    assert resultado.returncode == 1
    assert "debe estar en main" in resultado.stderr


def test_rechaza_working_tree_sucio(tmp_path: Path) -> None:
    repositorio = crear_repositorio(tmp_path)
    (repositorio.coordinador / "cambio-local.txt").write_text("sin confirmar", encoding="utf-8")

    resultado = lanzar(repositorio)

    assert resultado.returncode == 1
    assert "cambios locales" in resultado.stderr


def test_rechaza_wp_no_aprobado(tmp_path: Path) -> None:
    repositorio = crear_repositorio(tmp_path, aprobado=False)

    resultado = lanzar(repositorio)

    assert resultado.returncode == 1
    assert "no tiene estado documental APROBADO" in resultado.stderr


def test_rechaza_wp_no_marcado_en_curso(tmp_path: Path) -> None:
    repositorio = crear_repositorio(tmp_path, estado_wp="PENDIENTE")

    resultado = lanzar(repositorio)

    assert resultado.returncode == 1
    assert "debe figurar EN_CURSO" in resultado.stderr


def test_rechaza_agente_distinto_del_asignado(tmp_path: Path) -> None:
    repositorio = crear_repositorio(tmp_path, agente="Claude")

    resultado = lanzar(repositorio)

    assert resultado.returncode == 1
    assert "está asignado a 'Claude'" in resultado.stderr


def test_rechaza_dependencia_no_integrada(tmp_path: Path) -> None:
    repositorio = crear_repositorio(tmp_path, dependencia_integrada=False)

    resultado = lanzar(repositorio)

    assert resultado.returncode == 1
    assert "Dependencias todavía no integradas" in resultado.stderr


def test_crea_rama_worktree_y_abre_cli_en_destino(tmp_path: Path) -> None:
    repositorio = crear_repositorio(tmp_path)
    ruta_plan = repositorio.coordinador / "docs" / "implementation" / "PLAN.md"
    plan_original = ruta_plan.read_text(encoding="utf-8")
    commit_main_original = ejecutar(
        "git", "rev-parse", "main", cwd=repositorio.coordinador
    ).stdout.strip()

    resultado = lanzar(repositorio)

    destino = repositorio.coordinador.parent / "coordinador-wp002"
    assert resultado.returncode == 0, resultado.stderr
    assert destino.is_dir()
    assert repositorio.registro_cli.read_text(encoding="utf-8") == str(destino)
    rama = ejecutar("git", "branch", "--show-current", cwd=destino).stdout.strip()
    assert rama == "wp/002-runtime-base-de-prueba"
    assert ruta_plan.read_text(encoding="utf-8") == plan_original
    commit_main_final = ejecutar(
        "git", "rev-parse", "main", cwd=repositorio.coordinador
    ).stdout.strip()
    assert commit_main_final == commit_main_original


def test_reentrada_reutiliza_el_mismo_worktree(tmp_path: Path) -> None:
    repositorio = crear_repositorio(tmp_path)
    assert lanzar(repositorio).returncode == 0

    segundo_resultado = lanzar(repositorio)

    assert segundo_resultado.returncode == 0, segundo_resultado.stderr
    assert "Reutilizando" in segundo_resultado.stdout
    salida = ejecutar("git", "worktree", "list", "--porcelain", cwd=repositorio.coordinador).stdout
    assert salida.count("worktree ") == 2


def test_rechaza_conflicto_de_ruta_sin_borrarla(tmp_path: Path) -> None:
    repositorio = crear_repositorio(tmp_path)
    destino = repositorio.coordinador.parent / "coordinador-wp002"
    destino.mkdir()
    testigo = destino / "trabajo-ajeno.txt"
    testigo.write_text("preservar", encoding="utf-8")

    resultado = lanzar(repositorio)

    assert resultado.returncode == 1
    assert "ya existe y Git no la administra" in resultado.stderr
    assert testigo.read_text(encoding="utf-8") == "preservar"


def test_cli_ausente_no_crea_rama_ni_worktree(tmp_path: Path) -> None:
    repositorio = crear_repositorio(tmp_path)
    directorio_minimo = tmp_path / "solo-git"
    directorio_minimo.mkdir()
    ruta_git = shutil.which("git")
    if ruta_git is None:
        pytest.skip("Git no está disponible en el entorno de pruebas")
    (directorio_minimo / "git").symlink_to(ruta_git)
    (directorio_minimo / "python3").symlink_to(sys.executable)
    entorno = repositorio.entorno.copy()
    entorno["PATH"] = str(directorio_minimo)

    resultado = lanzar(repositorio, entorno=entorno)

    assert resultado.returncode == 1
    assert "no está instalada" in resultado.stderr
    destino = repositorio.coordinador.parent / "coordinador-wp002"
    assert not destino.exists()
    ramas = ejecutar("git", "branch", "--list", cwd=repositorio.coordinador).stdout
    assert "wp/002-" not in ramas


def test_mapeo_antigravity_ejecuta_cli_agy(tmp_path: Path) -> None:
    repositorio = crear_repositorio(tmp_path, agente="antigravity")
    directorio_bin = tmp_path / "bin"
    cli_agy = directorio_bin / "agy"
    cli_agy.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        "from pathlib import Path\n"
        "Path(os.environ['REGISTRO_CLI']).write_text('agy:' + str(Path.cwd()), encoding='utf-8')\n",
        encoding="utf-8",
    )
    cli_agy.chmod(cli_agy.stat().st_mode | stat.S_IXUSR)

    entorno = repositorio.entorno.copy()
    entorno["PATH"] = str(directorio_bin)

    resultado = lanzar(repositorio, agente="antigravity", entorno=entorno)

    destino = repositorio.coordinador.parent / "coordinador-wp002"
    assert resultado.returncode == 0, resultado.stderr
    assert destino.is_dir()
    assert repositorio.registro_cli.read_text(encoding="utf-8") == f"agy:{destino}"


def test_mapeo_antigravity_fallback_a_antigravity(tmp_path: Path) -> None:
    repositorio = crear_repositorio(tmp_path, agente="antigravity")
    directorio_bin = tmp_path / "bin"
    cli_antigravity = directorio_bin / "antigravity"
    cli_antigravity.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        "from pathlib import Path\n"
        "salida = 'antigravity:' + str(Path.cwd())\n"
        "Path(os.environ['REGISTRO_CLI']).write_text(salida, encoding='utf-8')\n",
        encoding="utf-8",
    )
    cli_antigravity.chmod(cli_antigravity.stat().st_mode | stat.S_IXUSR)

    entorno = repositorio.entorno.copy()
    entorno["PATH"] = str(directorio_bin)

    resultado = lanzar(repositorio, agente="antigravity", entorno=entorno)

    destino = repositorio.coordinador.parent / "coordinador-wp002"
    assert resultado.returncode == 0, resultado.stderr
    assert destino.is_dir()
    assert repositorio.registro_cli.read_text(encoding="utf-8") == f"antigravity:{destino}"
