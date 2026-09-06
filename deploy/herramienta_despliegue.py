"""CLI productiva para releases inmutables, activación y rollback.

La herramienta usa únicamente biblioteca estándar. Toda ejecución externa se
arma como una lista de argumentos (nunca ``shell=True``), lo que mantiene
auditables los límites privilegiados y permite probarlos con un ejecutor
inyectado sin tocar systemd ni Nginx del host de desarrollo.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol, cast

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
MARCADOR_PREPARADA = ".sis-leg-preparada.json"
SERVICIO_BACKEND = "sis-leg-backend.service"
SERVICIO_BRIDGE = "sis-leg-device-bridge.service"
URL_ESTADO = "http://127.0.0.1:8000/api/v1/estado/moderacion"
URL_HEALTH = "http://127.0.0.1:8000/api/v1/health"
URL_NGINX_HEALTH = "http://127.0.0.1/api/v1/health"
URL_NGINX_MODERACION = "http://127.0.0.1/moderacion/"
URL_NGINX_RECINTO = "http://127.0.0.1/recinto/"
URL_NGINX_SIMULADOR = "http://127.0.0.1/simulador/"
URL_NGINX_TECNICO = "http://127.0.0.1/tecnico/"
# El manual de usuario (WP-067) se publica en su propia ruta estática. Se comprueba junto
# a las SPA porque el icono de ayuda de Moderación y el de Apoyo Técnico dependen de él.
URL_NGINX_MANUAL = "http://127.0.0.1/manual/"
MAXIMO_ARCHIVOS_TAR = 20_000
MAXIMO_BYTES_TAR = 2 * 1024 * 1024 * 1024
MAXIMO_LONGITUD_RUTA = 512


class ErrorDespliegue(RuntimeError):
    """Falla segura y accionable de una operación productiva."""


@dataclass(frozen=True, slots=True)
class ResultadoComando:
    """Resultado mínimo que la herramienta necesita de un proceso externo."""

    codigo: int
    salida: str = ""
    error: str = ""


class EjecutorComandos(Protocol):
    """Frontera inyectable para systemctl, systemd-analyze, Nginx y uv."""

    def ejecutar(
        self,
        argumentos: Sequence[str],
        *,
        directorio: Path | None = None,
        entorno: Mapping[str, str] | None = None,
        comprobar: bool = True,
    ) -> ResultadoComando: ...


class EjecutorSubprocess:
    """Ejecutor real que delega en subprocess sin construir comandos shell."""

    def ejecutar(
        self,
        argumentos: Sequence[str],
        *,
        directorio: Path | None = None,
        entorno: Mapping[str, str] | None = None,
        comprobar: bool = True,
    ) -> ResultadoComando:
        ambiente = os.environ.copy()
        if entorno is not None:
            ambiente.update(entorno)
        proceso = subprocess.run(
            list(argumentos),
            cwd=directorio,
            env=ambiente,
            capture_output=True,
            text=True,
            check=False,
        )
        resultado = ResultadoComando(proceso.returncode, proceso.stdout, proceso.stderr)
        if comprobar and proceso.returncode != 0:
            diagnostico = proceso.stderr.strip() or proceso.stdout.strip()
            raise ErrorDespliegue(
                f"Falló el comando {list(argumentos)!r} (código {proceso.returncode}): "
                f"{diagnostico}"
            )
        return resultado


def sha256_archivo(ruta: Path) -> str:
    """Calcula el checksum del artefacto o de un miembro extraído."""

    calculador = hashlib.sha256()
    with ruta.open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
            calculador.update(bloque)
    return calculador.hexdigest()


def validar_sha(sha: str) -> str:
    """Rechaza abreviaturas y caracteres ambiguos antes de resolver rutas."""

    if SHA_RE.fullmatch(sha) is None:
        raise ErrorDespliegue("El SHA debe contener exactamente 40 hexadecimales minúsculos.")
    return sha


def verificar_checksum(paquete: Path, sidecar: Path) -> str:
    """Comprueba que el sidecar nombra el paquete y coincide byte a byte."""

    try:
        linea = sidecar.read_text(encoding="ascii").strip()
    except OSError as error:
        raise ErrorDespliegue(f"No se pudo leer el sidecar {sidecar}: {error}") from error
    partes = linea.split()
    if len(partes) != 2 or partes[1].lstrip("*") != paquete.name:
        raise ErrorDespliegue("El sidecar SHA-256 no tiene el formato o nombre esperado.")
    esperado = partes[0]
    if len(esperado) != 64 or any(c not in "0123456789abcdef" for c in esperado):
        raise ErrorDespliegue("El sidecar no contiene un SHA-256 hexadecimal válido.")
    real = sha256_archivo(paquete)
    if real != esperado:
        raise ErrorDespliegue(f"Checksum incorrecto: esperado {esperado}, calculado {real}.")
    return real


def _validar_nombre_tar(nombre: str) -> PurePosixPath:
    """Valida sintácticamente una ruta de tar antes de mirar el filesystem."""

    ruta = PurePosixPath(nombre)
    if not nombre or nombre.startswith("/") or ruta.is_absolute():
        raise ErrorDespliegue(f"El tar contiene una ruta absoluta o vacía: {nombre!r}")
    if ruta.as_posix() != nombre:
        raise ErrorDespliegue(f"El tar contiene una ruta ambigua o no normalizada: {nombre!r}")
    if len(nombre) > MAXIMO_LONGITUD_RUTA or any(ord(caracter) < 32 for caracter in nombre):
        raise ErrorDespliegue(f"El tar contiene una ruta no permitida: {nombre!r}")
    if any(parte in {"", ".", ".."} for parte in ruta.parts):
        raise ErrorDespliegue(f"El tar contiene traversal o componentes ambiguos: {nombre!r}")
    if ruta.parts[0] not in {"app", "web", "deploy", "release.json"}:
        raise ErrorDespliegue(f"La entrada no pertenece a la allowlist productiva: {nombre}")
    if ruta.parts[0] == "release.json" and len(ruta.parts) != 1:
        raise ErrorDespliegue("release.json debe ser un único archivo en la raíz del paquete.")
    return ruta


def _leer_manifest_desde_tar(tar: tarfile.TarFile) -> dict[str, Any]:
    """Lee primero el manifest con un límite pequeño y sin extraer al disco."""

    try:
        miembro = tar.getmember("release.json")
    except KeyError as error:
        raise ErrorDespliegue("El paquete no contiene release.json.") from error
    if not miembro.isfile() or miembro.size > 10 * 1024 * 1024:
        raise ErrorDespliegue("release.json no es un archivo regular de tamaño razonable.")
    archivo = tar.extractfile(miembro)
    if archivo is None:
        raise ErrorDespliegue("No se pudo leer release.json.")
    try:
        datos = json.loads(archivo.read().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ErrorDespliegue(f"release.json es inválido: {error}") from error
    if not isinstance(datos, dict):
        raise ErrorDespliegue("release.json debe ser un objeto JSON.")
    return cast(dict[str, Any], datos)


def validar_manifest(
    manifest: Mapping[str, Any], sha_solicitado: str
) -> dict[str, tuple[str, int]]:
    """Valida identidad y convierte el inventario en una allowlist exacta."""

    if manifest.get("formato") != "sis-leg-release" or manifest.get("version_formato") != 1:
        raise ErrorDespliegue("Formato o versión de release no soportados.")
    if manifest.get("commit_sha") != sha_solicitado:
        raise ErrorDespliegue("El SHA solicitado no coincide con release.json.")
    sha_arbol = manifest.get("tree_sha")
    if not isinstance(sha_arbol, str) or SHA_RE.fullmatch(sha_arbol) is None:
        raise ErrorDespliegue("release.json no declara un tree SHA Git completo y válido.")
    if manifest.get("python") != "3.14":
        raise ErrorDespliegue("La release no declara Python 3.14.")
    if manifest.get("spas") != {
        "moderacion": "web/moderacion/index.html",
        "recinto": "web/recinto/index.html",
        "simulador": "web/simulador/index.html",
        "tecnico": "web/tecnico/index.html",
    }:
        raise ErrorDespliegue("release.json no declara las cuatro SPA canónicas.")
    if manifest.get("manual") != "web/manual/index.html":
        raise ErrorDespliegue("release.json no declara el manual de usuario canónico.")
    if manifest.get("paquetes_python") != [
        "sis-leg-backend",
        "sis-leg-device-bridge",
    ]:
        raise ErrorDespliegue("release.json no declara los paquetes Python canónicos.")
    archivos = manifest.get("archivos")
    if not isinstance(archivos, list):
        raise ErrorDespliegue("release.json no contiene un inventario de archivos.")

    inventario: dict[str, tuple[str, int]] = {}
    for entrada in cast(list[Any], archivos):
        if not isinstance(entrada, dict):
            raise ErrorDespliegue("Una entrada del inventario no es un objeto.")
        entrada_tipada = cast(dict[str, Any], entrada)
        ruta = entrada_tipada.get("ruta")
        checksum = entrada_tipada.get("sha256")
        tamano = entrada_tipada.get("tamano")
        if not isinstance(ruta, str) or ruta == "release.json":
            raise ErrorDespliegue("Ruta inválida en el inventario de release.")
        _validar_nombre_tar(ruta)
        if ruta in inventario:
            raise ErrorDespliegue(f"Ruta duplicada en el inventario: {ruta}")
        if (
            not isinstance(checksum, str)
            or len(checksum) != 64
            or any(caracter not in "0123456789abcdef" for caracter in checksum)
        ):
            raise ErrorDespliegue(f"Checksum inválido en el inventario: {ruta}")
        if not isinstance(tamano, int) or isinstance(tamano, bool) or tamano < 0:
            raise ErrorDespliegue(f"Tamaño inválido en el inventario: {ruta}")
        inventario[ruta] = (checksum, tamano)

    requeridas = {
        "app/pyproject.toml",
        "app/uv.lock",
        "app/apps/backend/pyproject.toml",
        "app/services/device-bridge/pyproject.toml",
        "web/moderacion/index.html",
        "web/recinto/index.html",
        "web/simulador/index.html",
        "web/tecnico/index.html",
        "web/manual/index.html",
        "deploy/systemd/sis-leg-backend.service",
        "deploy/systemd/sis-leg-device-bridge.service",
        "deploy/nginx/sis-leg.conf",
        "deploy/herramienta_despliegue.py",
        "deploy/validar_configuracion.py",
    }
    faltantes = sorted(requeridas - inventario.keys())
    if faltantes:
        raise ErrorDespliegue(f"La release omite entradas obligatorias: {faltantes}")
    return inventario


def extraer_paquete_seguro(paquete: Path, destino: Path, sha_solicitado: str) -> dict[str, Any]:
    """Extrae solo archivos regulares exactos y comprueba su contenido.

    No se usa ``extractall``: incluso el filtro ``data`` de Python advierte
    que no sustituye una inspección de allowlist. Cada archivo se escribe con
    modo exclusivo después de validar el manifest completo.
    """

    validar_sha(sha_solicitado)
    destino.mkdir(parents=True, exist_ok=False)
    try:
        with tarfile.open(paquete, mode="r:gz") as tar:
            miembros = tar.getmembers()
            if len(miembros) > MAXIMO_ARCHIVOS_TAR:
                raise ErrorDespliegue("El tar supera la cantidad máxima de archivos permitida.")
            if sum(miembro.size for miembro in miembros) > MAXIMO_BYTES_TAR:
                raise ErrorDespliegue("El tar supera el tamaño total máximo permitido.")
            nombres: set[str] = set()
            for miembro in miembros:
                _validar_nombre_tar(miembro.name)
                if miembro.name in nombres:
                    raise ErrorDespliegue(f"Entrada duplicada en el tar: {miembro.name}")
                nombres.add(miembro.name)
                if not miembro.isfile():
                    raise ErrorDespliegue(
                        f"Solo se aceptan archivos regulares; entrada rechazada: {miembro.name}"
                    )

            manifest = _leer_manifest_desde_tar(tar)
            inventario = validar_manifest(manifest, sha_solicitado)
            esperados = set(inventario) | {"release.json"}
            if nombres != esperados:
                extras = sorted(nombres - esperados)
                faltantes = sorted(esperados - nombres)
                raise ErrorDespliegue(
                    f"El tar no coincide con su allowlist; extras={extras}, faltantes={faltantes}."
                )

            for miembro in miembros:
                origen = tar.extractfile(miembro)
                if origen is None:
                    raise ErrorDespliegue(f"No se pudo abrir {miembro.name} dentro del tar.")
                ruta_destino = destino.joinpath(*PurePosixPath(miembro.name).parts)
                if miembro.name != "release.json":
                    _, tamano_manifest = inventario[miembro.name]
                    if miembro.size != tamano_manifest:
                        raise ErrorDespliegue(
                            f"El tamaño tar no coincide con el manifest: {miembro.name}"
                        )
                ruta_destino.parent.mkdir(parents=True, exist_ok=True)
                with ruta_destino.open("xb") as salida:
                    shutil.copyfileobj(origen, salida)
                if miembro.name != "release.json":
                    checksum, tamano = inventario[miembro.name]
                    if (
                        ruta_destino.stat().st_size != tamano
                        or sha256_archivo(ruta_destino) != checksum
                    ):
                        raise ErrorDespliegue(
                            f"El contenido extraído no coincide con el manifest: {miembro.name}"
                        )
        return manifest
    except Exception:
        shutil.rmtree(destino, ignore_errors=True)
        raise


def cambiar_enlace_atomico(enlace: Path, destino: Path | None) -> None:
    """Reemplaza un symlink mediante ``os.replace`` en su mismo directorio."""

    enlace.parent.mkdir(parents=True, exist_ok=True)
    temporal = enlace.with_name(f".{enlace.name}.nuevo-{os.getpid()}")
    temporal.unlink(missing_ok=True)
    try:
        if destino is None:
            enlace.unlink(missing_ok=True)
            return
        os.symlink(os.path.relpath(destino, enlace.parent), temporal)
        os.replace(temporal, enlace)
    finally:
        temporal.unlink(missing_ok=True)


def resolver_enlace_release(enlace: Path, raiz_releases: Path) -> Path | None:
    """Obtiene un target existente y comprueba que permanezca bajo releases."""

    if not enlace.is_symlink():
        return None
    destino = (enlace.parent / os.readlink(enlace)).resolve()
    try:
        destino.relative_to(raiz_releases.resolve())
    except ValueError as error:
        raise ErrorDespliegue(f"{enlace} apunta fuera de releases: {destino}") from error
    return destino


def consultar_json(url: str, timeout: float = 3.0) -> dict[str, Any]:
    """Consulta HTTP GET con timeout y exige un objeto JSON 2xx."""

    solicitud = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(solicitud, timeout=timeout) as respuesta:
            datos = json.loads(respuesta.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ErrorDespliegue(f"No se pudo consultar {url}: {error}") from error
    if not isinstance(datos, dict):
        raise ErrorDespliegue(f"{url} no devolvió un objeto JSON.")
    return cast(dict[str, Any], datos)


def consultar_texto(url: str, timeout: float = 3.0) -> str:
    """Comprueba una URL HTTP y devuelve una porción textual diagnóstica."""

    solicitud = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(solicitud, timeout=timeout) as respuesta:
            if respuesta.status < 200 or respuesta.status >= 300:
                raise ErrorDespliegue(f"{url} respondió HTTP {respuesta.status}.")
            return respuesta.read(4096).decode("utf-8", errors="replace")
    except (OSError, urllib.error.URLError) as error:
        raise ErrorDespliegue(f"No se pudo consultar {url}: {error}") from error


@dataclass(frozen=True, slots=True)
class PlanPermiso:
    """Entrada declarativa de ownership/modo para bootstrap y documentación."""

    ruta_relativa: str
    usuario: str
    grupo: str
    modo: int


@dataclass(frozen=True, slots=True)
class RespaldoArchivo:
    """Snapshot suficiente para restaurar exactamente un archivo de sistema.

    ``contenido=None`` representa un destino que no existía antes de iniciar
    la transacción. Para archivos existentes también conservamos el modo, de
    modo que un rollback no cambie silenciosamente sus permisos.
    """

    contenido: bytes | None
    modo: int | None


def plan_permisos() -> tuple[PlanPermiso, ...]:
    """Declara la separación mínima aprobada entre backend y bridge.

    ``config`` conserva lectura/listado para el grupo del backend, mientras el
    bit de ejecución de ``other`` permite que el bridge atraviese ese directorio
    padre sin poder enumerarlo. La separación más estricta reaparece en cada
    hijo: sólo backend lee los archivos institucionales y sólo bridge administra
    su subdirectorio, requisito necesario para reemplazar ``devices.json`` de
    manera atómica.

    ``config/apoyo-tecnico`` aplica exactamente ese mismo patrón para el
    backend: la biblioteca de mensajes técnicos de WP-055 es el único archivo
    de configuración que el backend escribe, y reemplazarlo con ``os.replace``
    exige permiso de escritura sobre el **directorio** que lo contiene, no
    solamente sobre el archivo. Por eso vive en un subdirectorio propio en
    lugar de junto a ``system.toml``, que debe seguir siendo de solo lectura.
    """

    return (
        PlanPermiso(".", "root", "root", 0o755),
        PlanPermiso("releases", "root", "root", 0o755),
        PlanPermiso("config", "root", "sis-leg-backend", 0o751),
        PlanPermiso("config/system.toml", "root", "sis-leg-backend", 0o640),
        PlanPermiso("config/concejales.csv", "root", "sis-leg-backend", 0o640),
        PlanPermiso("config/bridge", "sis-leg-bridge", "sis-leg-bridge", 0o750),
        PlanPermiso("config/bridge/devices.json", "sis-leg-bridge", "sis-leg-bridge", 0o640),
        PlanPermiso("config/apoyo-tecnico", "sis-leg-backend", "sis-leg-backend", 0o750),
        PlanPermiso(
            "config/apoyo-tecnico/mensajes.csv",
            "sis-leg-backend",
            "sis-leg-backend",
            0o640,
        ),
        PlanPermiso("logs", "sis-leg-backend", "sis-leg-backend", 0o750),
    )


class GestorDespliegue:
    """Coordina filesystem, configuración, servicios y verificaciones HTTP."""

    def __init__(
        self,
        raiz: Path = Path("/opt/sis-leg"),
        *,
        ejecutor: EjecutorComandos | None = None,
        consultor_json: Callable[[str, float], dict[str, Any]] = consultar_json,
        consultor_texto: Callable[[str, float], str] = consultar_texto,
        directorio_systemd: Path = Path("/etc/systemd/system"),
        ruta_nginx: Path = Path("/etc/nginx/conf.d/sis-leg.conf"),
        python_base: Path | None = None,
    ) -> None:
        raiz_absoluta = raiz.resolve()
        if raiz_absoluta == Path("/"):
            raise ErrorDespliegue("La raíz de SIS-Leg no puede ser /.")
        self.raiz = raiz_absoluta
        self.releases = self.raiz / "releases"
        self.current = self.raiz / "current"
        self.previous = self.raiz / "previous"
        self.config = self.raiz / "config"
        self.logs = self.raiz / "logs"
        self.ejecutor = ejecutor or EjecutorSubprocess()
        self.consultor_json = consultor_json
        self.consultor_texto = consultor_texto
        self.directorio_systemd = directorio_systemd
        self.ruta_nginx = ruta_nginx
        # La herramienta productiva se invoca con ``python3.14``. Guardamos
        # ese ejecutable como entrada explícita para uv, evitando que uv elija
        # por preferencia un Python administrado dentro del home de root.
        self.python_base = Path(sys.executable) if python_base is None else python_base

    def bootstrap(self, *, aplicar_usuarios: bool = False) -> tuple[PlanPermiso, ...]:
        """Crea estructura externa idempotente y opcionalmente usuarios/permisos.

        Los archivos institucionales nunca se inventan. El comando crea solo
        sus directorios; el operador debe provisionar los tres archivos y volver
        a ejecutar el bootstrap para aplicarles ownership y modo antes de activar.
        """

        if aplicar_usuarios:
            for usuario in ("sis-leg-backend", "sis-leg-bridge"):
                existe_grupo = (
                    self.ejecutor.ejecutar(["getent", "group", usuario], comprobar=False).codigo
                    == 0
                )
                if not existe_grupo:
                    self.ejecutor.ejecutar(["groupadd", "--system", usuario])
                existe_usuario = (
                    self.ejecutor.ejecutar(["getent", "passwd", usuario], comprobar=False).codigo
                    == 0
                )
                if not existe_usuario:
                    self.ejecutor.ejecutar(
                        [
                            "useradd",
                            "--system",
                            "--gid",
                            usuario,
                            "--home-dir",
                            "/nonexistent",
                            "--shell",
                            "/usr/sbin/nologin",
                            usuario,
                        ]
                    )
                else:
                    self.ejecutor.ejecutar(["usermod", "--gid", usuario, usuario])
            self.ejecutor.ejecutar(["usermod", "--append", "--groups", "input", "sis-leg-bridge"])

        self.releases.mkdir(parents=True, exist_ok=True)
        (self.config / "bridge").mkdir(parents=True, exist_ok=True)
        # El backend crea el CSV de mensajes técnicos la primera vez que se
        # da de alta un mensaje; el directorio, en cambio, debe existir antes
        # con el dueño correcto para que la escritura atómica sea posible.
        (self.config / "apoyo-tecnico").mkdir(parents=True, exist_ok=True)
        self.logs.mkdir(parents=True, exist_ok=True)
        plan = plan_permisos()
        if aplicar_usuarios:
            self._aplicar_plan_permisos(plan)
        return plan

    def _aplicar_plan_permisos(self, plan: Sequence[PlanPermiso]) -> None:
        """Aplica ownership y modos declarados únicamente a entradas existentes.

        La primera ejecución configura los directorios vacíos; una segunda,
        posterior al aprovisionamiento institucional, alcanza también los tres
        archivos sin crearlos ni alterar su contenido. Se rechazan enlaces
        simbólicos para no aplicar privilegios fuera del árbol administrado.
        """

        for entrada in plan:
            ruta = self.raiz / entrada.ruta_relativa
            if ruta.is_symlink():
                raise ErrorDespliegue(f"El plan de permisos rechaza el enlace simbólico: {ruta}")
            if not ruta.exists():
                continue
            self.ejecutor.ejecutar(
                ["chown", "--no-dereference", f"{entrada.usuario}:{entrada.grupo}", str(ruta)]
            )
            self.ejecutor.ejecutar(["chmod", f"{entrada.modo:04o}", str(ruta)])

    def preparar(self, paquete: Path, sidecar: Path, sha: str) -> Path:
        """Verifica, extrae e instala runtime sin modificar la release activa."""

        sha = validar_sha(sha)
        verificar_checksum(paquete, sidecar)
        self.releases.mkdir(parents=True, exist_ok=True)
        destino = self.releases / sha
        marcador = destino / MARCADOR_PREPARADA
        if marcador.is_file():
            datos = json.loads(marcador.read_text(encoding="utf-8"))
            if datos.get("commit_sha") == sha:
                return destino
            raise ErrorDespliegue("La release existente tiene un marcador incompatible.")
        if destino.exists():
            raise ErrorDespliegue(
                "La release ya existe pero no está preparada; "
                "se requiere inspección administrativa."
            )

        # Se valida antes de extraer para que un prerequisito administrativo
        # incorrecto no deje siquiera una release parcial para diagnosticar.
        python_base = self._validar_python_base()
        manifest = extraer_paquete_seguro(paquete, destino, sha)
        try:
            entorno = {"UV_PROJECT_ENVIRONMENT": str(destino / ".venv")}
            self.ejecutor.ejecutar(
                [
                    "uv",
                    "sync",
                    "--frozen",
                    "--no-dev",
                    "--all-packages",
                    "--python",
                    str(python_base),
                    "--no-python-downloads",
                ],
                directorio=destino / "app",
                entorno=entorno,
            )
            python = destino / ".venv/bin/python"
            self.ejecutor.ejecutar(
                [
                    python.as_posix(),
                    "-c",
                    "import sis_leg_backend.main, sis_leg_device_bridge.cli, uvicorn",
                ]
            )
            self.ejecutor.ejecutar(
                [destino.joinpath(".venv/bin/sis-leg-device-bridge").as_posix(), "--help"]
            )
            self._validar_estructura_release(destino)
            marcador.write_text(
                json.dumps(
                    {
                        "commit_sha": sha,
                        "tree_sha": manifest.get("tree_sha"),
                        "python_base": str(python_base),
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            self._hacer_release_solo_lectura(destino)
        except Exception:
            # Una preparación fallida nunca toca current. Se conserva el
            # directorio parcial para diagnóstico y no se lo reutiliza a ciegas.
            raise
        return destino

    def _validar_estructura_release(self, release: Path) -> None:
        """Comprueba imports/archivos que el runtime productivo consumirá."""

        requeridas = (
            release / ".venv/bin/uvicorn",
            release / ".venv/bin/sis-leg-device-bridge",
            release / "web/moderacion/index.html",
            release / "web/recinto/index.html",
            release / "web/simulador/index.html",
            release / "web/tecnico/index.html",
            release / "web/manual/index.html",
            release / "deploy/systemd/sis-leg-backend.service",
            release / "deploy/systemd/sis-leg-device-bridge.service",
            release / "deploy/nginx/sis-leg.conf",
            release / "deploy/validar_configuracion.py",
        )
        faltantes = [str(ruta) for ruta in requeridas if not ruta.is_file()]
        if faltantes:
            raise ErrorDespliegue(f"La release preparada está incompleta: {faltantes}")

    @staticmethod
    def _hacer_release_solo_lectura(release: Path) -> None:
        """Retira escritura sin seguir enlaces simbólicos fuera de la release.

        Una venv POSIX contiene normalmente symlinks hacia su intérprete base.
        ``os.walk(..., followlinks=False)`` evita recorrer symlinks de
        directorio; ``lstat`` y ``follow_symlinks=False`` garantizan además
        que una carrera o un enlace de archivo nunca termine aplicando chmod
        sobre el inode externo apuntado.
        """

        mascara_escritura = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
        entradas: list[Path] = []
        for directorio, nombres_directorio, nombres_archivo in os.walk(
            release, topdown=False, followlinks=False
        ):
            base = Path(directorio)
            entradas.extend(base / nombre for nombre in nombres_archivo)
            entradas.extend(base / nombre for nombre in nombres_directorio)

        for ruta in entradas:
            modo = ruta.lstat().st_mode
            if stat.S_ISLNK(modo):
                # Los permisos de un symlink no gobiernan el acceso POSIX y
                # modificarlo podría seguir el target en algunas plataformas.
                continue
            if not (stat.S_ISREG(modo) or stat.S_ISDIR(modo)):
                raise ErrorDespliegue(f"La release contiene una entrada especial: {ruta}")
            ruta.chmod(modo & ~mascara_escritura, follow_symlinks=False)

        modo_raiz = release.lstat().st_mode
        release.chmod(modo_raiz & ~mascara_escritura, follow_symlinks=False)

    def _validar_python_base(self) -> Path:
        """Exige un Python 3.14 estable y accesible a cualquier runtime.

        La ruta se resuelve antes de pasarla a uv. Cada directorio padre debe
        ser atravesable por ``other`` y el ejecutable debe ser legible y
        ejecutable por ``other``; esta condición fuerte evita depender del
        home privado del administrador o de grupos particulares.
        """

        try:
            python_base = self.python_base.resolve(strict=True)
        except OSError as error:
            raise ErrorDespliegue(
                f"No se pudo resolver el Python base {self.python_base}: {error}"
            ) from error

        modo_python = python_base.stat().st_mode
        if not stat.S_ISREG(modo_python) or modo_python & (stat.S_IROTH | stat.S_IXOTH) != (
            stat.S_IROTH | stat.S_IXOTH
        ):
            raise ErrorDespliegue(
                f"El Python base no es legible/ejecutable por los runtimes: {python_base}"
            )
        for directorio in python_base.parents:
            if directorio.stat().st_mode & stat.S_IXOTH == 0:
                raise ErrorDespliegue(
                    "El Python base depende de un directorio no atravesable por los "
                    f"usuarios runtime: {directorio}"
                )

        resultado = self.ejecutor.ejecutar(
            [
                str(python_base),
                "-c",
                "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
            ],
            comprobar=False,
        )
        if resultado.codigo != 0 or resultado.salida.strip() != "3.14":
            diagnostico = resultado.error.strip() or resultado.salida.strip() or "sin salida"
            raise ErrorDespliegue(
                f"El Python base {python_base} no es Python 3.14 utilizable: {diagnostico}"
            )
        return python_base

    def validar_configuracion(self, release: Path) -> None:
        """Usa parsers propietarios instalados y exige logs y sonidos exactos.

        La release se pasa como segundo argumento porque las rutas de la
        sección ``[sonidos]`` (WP-065) resuelven contra la SPA del Recinto que
        esa release publica, no contra la raíz de la instalación.
        """

        rutas = (
            self.config / "system.toml",
            self.config / "concejales.csv",
            self.config / "bridge/devices.json",
        )
        faltantes = [str(ruta) for ruta in rutas if not ruta.is_file()]
        if faltantes:
            raise ErrorDespliegue(f"Falta configuración productiva: {faltantes}")

        self.ejecutor.ejecutar(
            [
                release.joinpath(".venv/bin/python").as_posix(),
                str(release / "deploy/validar_configuracion.py"),
                str(self.raiz),
                str(release),
            ],
            directorio=self.raiz,
        )

    def _exigir_acceso_runtime(
        self, usuario: str, argumentos_test: Sequence[str], descripcion: str
    ) -> None:
        """Ejecuta una prueba POSIX con la identidad real del servicio.

        ``runuser`` permite verificar usuarios y permisos efectivos sin
        arrancar servicios ni crear datos institucionales. Se usa ``test``
        como comando directo, nunca mediante un shell.
        """

        resultado = self.ejecutor.ejecutar(
            ["runuser", "--user", usuario, "--", "test", *argumentos_test],
            comprobar=False,
        )
        if resultado.codigo != 0:
            diagnostico = resultado.error.strip() or resultado.salida.strip()
            detalle = f": {diagnostico}" if diagnostico else ""
            raise ErrorDespliegue(f"Permisos incompatibles para {usuario}: {descripcion}{detalle}")

    def _validar_permisos_runtime(self, release: Path) -> None:
        """Demuestra accesos mínimos y separación antes de cambiar ``current``."""

        pruebas = (
            (
                "sis-leg-backend",
                ("-x", str(self.config)),
                "config debe ser atravesable",
            ),
            (
                "sis-leg-backend",
                ("-r", str(self.config / "system.toml")),
                "system.toml debe ser legible",
            ),
            (
                "sis-leg-backend",
                ("-r", str(self.config / "concejales.csv")),
                "concejales.csv debe ser legible",
            ),
            (
                "sis-leg-backend",
                ("!", "-w", str(self.config)),
                "config no debe ser escribible",
            ),
            (
                "sis-leg-backend",
                ("!", "-w", str(self.config / "system.toml")),
                "system.toml no debe ser escribible",
            ),
            (
                "sis-leg-backend",
                ("!", "-w", str(self.config / "concejales.csv")),
                "concejales.csv no debe ser escribible",
            ),
            (
                "sis-leg-backend",
                ("!", "-r", str(self.config / "bridge/devices.json")),
                "devices.json no debe ser legible",
            ),
            (
                "sis-leg-backend",
                ("-w", str(self.logs)),
                "logs debe ser escribible",
            ),
            (
                "sis-leg-backend",
                ("-x", str(self.logs)),
                "logs debe ser atravesable",
            ),
            (
                "sis-leg-backend",
                ("-x", str(release / ".venv/bin/uvicorn")),
                "Uvicorn debe ser ejecutable",
            ),
            (
                "sis-leg-bridge",
                ("-x", str(self.config)),
                "config debe ser atravesable",
            ),
            (
                "sis-leg-bridge",
                ("!", "-r", str(self.config)),
                "config no debe poder enumerarse",
            ),
            (
                "sis-leg-bridge",
                ("!", "-w", str(self.config)),
                "config no debe ser escribible",
            ),
            (
                "sis-leg-bridge",
                ("!", "-r", str(self.config / "system.toml")),
                "system.toml no debe ser legible",
            ),
            (
                "sis-leg-bridge",
                ("!", "-r", str(self.config / "concejales.csv")),
                "concejales.csv no debe ser legible",
            ),
            (
                "sis-leg-bridge",
                ("-r", str(self.config / "bridge/devices.json")),
                "devices.json debe ser legible",
            ),
            (
                "sis-leg-bridge",
                ("-w", str(self.config / "bridge/devices.json")),
                "devices.json debe ser escribible",
            ),
            (
                "sis-leg-bridge",
                ("-w", str(self.config / "bridge")),
                "config/bridge debe ser escribible para reemplazos atómicos",
            ),
            (
                "sis-leg-bridge",
                ("-x", str(self.config / "bridge")),
                "config/bridge debe ser atravesable",
            ),
            (
                "sis-leg-bridge",
                ("-x", str(release / ".venv/bin/sis-leg-device-bridge")),
                "device-bridge debe ser ejecutable",
            ),
        )
        for usuario, argumentos, descripcion in pruebas:
            self._exigir_acceso_runtime(usuario, argumentos, descripcion)

        # Probar sólo la raíz no alcanzaría: una ACL o un modo accidental en
        # un archivo interno podría dejar una porción de la release escribible.
        # ``find -writable -quit`` evalúa cada entrada con la identidad real y
        # entrega como máximo una ruta diagnóstica.
        for usuario in ("sis-leg-backend", "sis-leg-bridge"):
            resultado = self.ejecutor.ejecutar(
                [
                    "runuser",
                    "--user",
                    usuario,
                    "--",
                    "find",
                    str(release),
                    "-writable",
                    "-print",
                    "-quit",
                ],
                comprobar=False,
            )
            if resultado.codigo != 0 or resultado.salida.strip():
                ruta = resultado.salida.strip() or resultado.error.strip() or "sin diagnóstico"
                raise ErrorDespliegue(
                    f"La release no es íntegramente de solo lectura para {usuario}: {ruta}"
                )

        grupos_backend = self.ejecutor.ejecutar(
            ["id", "--groups", "--name", "sis-leg-backend"], comprobar=False
        )
        grupos_bridge = self.ejecutor.ejecutar(
            ["id", "--groups", "--name", "sis-leg-bridge"], comprobar=False
        )
        if grupos_backend.codigo != 0 or grupos_bridge.codigo != 0:
            raise ErrorDespliegue("No se pudieron verificar los grupos de los usuarios runtime.")
        if "input" in grupos_backend.salida.split() or "input" not in grupos_bridge.salida.split():
            raise ErrorDespliegue("El grupo input debe pertenecer únicamente a sis-leg-bridge.")

    def guard_institucional(self) -> None:
        """Permite solo SIN_PREPARAR y falla cerrado ante runtime inconsistente."""

        if resolver_enlace_release(self.current, self.releases) is None:
            return
        estado_servicio = self.ejecutor.ejecutar(
            ["systemctl", "is-active", SERVICIO_BACKEND], comprobar=False
        )
        estado = estado_servicio.salida.strip()
        if estado_servicio.codigo != 0 and estado in {"inactive", "failed"}:
            print(
                f"Advertencia: backend {estado or 'no activo'}; "
                "no hay runtime institucional en ejecución.",
                file=sys.stderr,
            )
            return
        if estado != "active":
            raise ErrorDespliegue(f"Estado systemd del backend inconsistente: {estado!r}")
        datos = self.consultor_json(URL_ESTADO, 3.0)
        global_actual = datos.get("estado_global")
        if global_actual != "SIN_PREPARAR":
            raise ErrorDespliegue(
                f"Despliegue rechazado: el backend vigente está en {global_actual!r}."
            )

    def _validar_archivos_sistema(self, release: Path) -> None:
        """Valida unidades con systemd y la configuración Nginx candidata."""

        unidades = release / "deploy/systemd"
        self.ejecutor.ejecutar(
            [
                "systemd-analyze",
                "verify",
                str(unidades / SERVICIO_BACKEND),
                str(unidades / SERVICIO_BRIDGE),
            ]
        )
        # Nginx valida el archivo ya instalado; la copia se hace antes del
        # switch de current y puede restaurarse si algo posterior falla.

    @staticmethod
    def _copiar_atomico(origen: Path, destino: Path) -> None:
        """Instala un archivo regular mediante reemplazo en el mismo directorio."""

        destino.parent.mkdir(parents=True, exist_ok=True)
        temporal = destino.with_name(f".{destino.name}.nuevo-{os.getpid()}")
        temporal.unlink(missing_ok=True)
        try:
            shutil.copyfile(origen, temporal)
            os.chmod(temporal, 0o644)
            os.replace(temporal, destino)
        finally:
            temporal.unlink(missing_ok=True)

    @staticmethod
    def _respaldar_archivo(destino: Path) -> RespaldoArchivo:
        """Captura bytes y modo sin aceptar destinos especiales o symlinks."""

        if destino.is_symlink():
            raise ErrorDespliegue(f"El destino de sistema no puede ser symlink: {destino}")
        if not destino.exists():
            return RespaldoArchivo(None, None)
        modo = destino.lstat().st_mode
        if not stat.S_ISREG(modo):
            raise ErrorDespliegue(f"El destino de sistema no es un archivo regular: {destino}")
        return RespaldoArchivo(destino.read_bytes(), stat.S_IMODE(modo))

    @staticmethod
    def _restaurar_archivo(destino: Path, respaldo: RespaldoArchivo) -> None:
        """Restaura bytes anteriores o retira un archivo creado por la operación."""

        if respaldo.contenido is None:
            destino.unlink(missing_ok=True)
            return
        temporal = destino.with_name(f".{destino.name}.restaurar-{os.getpid()}")
        temporal.unlink(missing_ok=True)
        try:
            temporal.write_bytes(respaldo.contenido)
            os.chmod(temporal, respaldo.modo if respaldo.modo is not None else 0o644)
            os.replace(temporal, destino)
        finally:
            temporal.unlink(missing_ok=True)

    def _instalar_archivos_sistema(self, release: Path) -> dict[Path, RespaldoArchivo]:
        """Instala el conjunto o restaura todos los destinos ante fallo parcial."""

        destinos = (
            (
                self.directorio_systemd / SERVICIO_BACKEND,
                release / "deploy/systemd" / SERVICIO_BACKEND,
            ),
            (
                self.directorio_systemd / SERVICIO_BRIDGE,
                release / "deploy/systemd" / SERVICIO_BRIDGE,
            ),
            (self.ruta_nginx, release / "deploy/nginx/sis-leg.conf"),
        )
        respaldos: dict[Path, RespaldoArchivo] = {}
        try:
            for destino, origen in destinos:
                # El snapshot se registra antes de cada mutación. Así también
                # podemos restaurar un destino si una falla aparece después
                # de su os.replace pero antes de completar el conjunto.
                respaldos[destino] = self._respaldar_archivo(destino)
                self._copiar_atomico(origen, destino)
        except Exception as error_original:
            errores_restauracion: list[str] = []
            for destino, respaldo in reversed(tuple(respaldos.items())):
                try:
                    self._restaurar_archivo(destino, respaldo)
                except Exception as error_restauracion:  # noqa: BLE001 - diagnóstico acumulado
                    errores_restauracion.append(f"{destino}: {error_restauracion}")
            if errores_restauracion:
                raise ErrorDespliegue(
                    "Falló la instalación parcial de archivos de sistema y también su "
                    f"restauración ({'; '.join(errores_restauracion)}): {error_original}"
                ) from error_original
            raise ErrorDespliegue(
                "Falló la instalación de archivos de sistema; todos los destinos "
                f"modificados fueron restaurados: {error_original}"
            ) from error_original
        return respaldos

    def _esperar_health(self, *, intentos: int = 20, pausa: float = 0.5) -> None:
        """Espera acotadamente el backend nuevo y conserva el último diagnóstico."""

        ultimo: Exception | None = None
        for _ in range(intentos):
            try:
                if self.consultor_json(URL_HEALTH, 2.0).get("estado") == "ok":
                    return
            except Exception as error:  # noqa: BLE001 - se conserva diagnóstico de frontera
                ultimo = error
            time.sleep(pausa)
        raise ErrorDespliegue(f"El backend no alcanzó health a tiempo: {ultimo}")

    def _verificar_servicios_y_nginx(self) -> None:
        """Confirma servicios, recarga Nginx y prueba mismo origen completo."""

        for servicio in (SERVICIO_BACKEND, SERVICIO_BRIDGE):
            resultado = self.ejecutor.ejecutar(
                ["systemctl", "is-active", servicio], comprobar=False
            )
            if resultado.codigo != 0 or resultado.salida.strip() != "active":
                raise ErrorDespliegue(f"{servicio} no quedó activo: {resultado.error}")
        self.ejecutor.ejecutar(["nginx", "-t"])
        self.ejecutor.ejecutar(["systemctl", "reload", "nginx.service"])
        if self.consultor_json(URL_NGINX_HEALTH, 3.0).get("estado") != "ok":
            raise ErrorDespliegue("El health vía Nginx no devolvió estado=ok.")
        for url in (
            URL_NGINX_MODERACION,
            URL_NGINX_RECINTO,
            URL_NGINX_SIMULADOR,
            URL_NGINX_TECNICO,
            URL_NGINX_MANUAL,
        ):
            if "<!doctype html" not in self.consultor_texto(url, 3.0).lower():
                raise ErrorDespliegue(f"La ruta no respondió HTML válido por Nginx: {url}")

    def activar(self, sha: str) -> None:
        """Activa una release y restaura automáticamente la anterior si falla."""

        objetivo = self.releases / validar_sha(sha)
        self._validar_release_preparada(objetivo)
        self.validar_configuracion(objetivo)
        self._validar_permisos_runtime(objetivo)
        self.guard_institucional()
        self._validar_archivos_sistema(objetivo)
        anterior = resolver_enlace_release(self.current, self.releases)
        if anterior == objetivo:
            return
        respaldo_archivos = self._instalar_archivos_sistema(objetivo)
        hubo_switch = False
        try:
            self.ejecutor.ejecutar(["nginx", "-t"])
            cambiar_enlace_atomico(self.current, objetivo)
            hubo_switch = True
            self.ejecutor.ejecutar(["systemctl", "daemon-reload"])
            self.ejecutor.ejecutar(["systemctl", "restart", SERVICIO_BACKEND])
            self._esperar_health()
            self.ejecutor.ejecutar(["systemctl", "restart", SERVICIO_BRIDGE])
            self._verificar_servicios_y_nginx()
            cambiar_enlace_atomico(self.previous, anterior)
        except Exception as error_original:
            if not hubo_switch:
                for ruta, respaldo in respaldo_archivos.items():
                    self._restaurar_archivo(ruta, respaldo)
                raise
            try:
                cambiar_enlace_atomico(self.current, anterior)
                for ruta, respaldo in respaldo_archivos.items():
                    self._restaurar_archivo(ruta, respaldo)
                self.ejecutor.ejecutar(["systemctl", "daemon-reload"])
                if anterior is not None:
                    self.ejecutor.ejecutar(["systemctl", "restart", SERVICIO_BACKEND])
                    self._esperar_health()
                    self.ejecutor.ejecutar(["systemctl", "restart", SERVICIO_BRIDGE])
                    self._verificar_servicios_y_nginx()
                else:
                    self.ejecutor.ejecutar(["systemctl", "stop", SERVICIO_BRIDGE], comprobar=False)
                    self.ejecutor.ejecutar(["systemctl", "stop", SERVICIO_BACKEND], comprobar=False)
                    self.ejecutor.ejecutar(["nginx", "-t"])
                    self.ejecutor.ejecutar(["systemctl", "reload", "nginx.service"])
            except Exception as error_rollback:
                raise ErrorDespliegue(
                    f"Falló la activación ({error_original}) y también el rollback "
                    f"automático ({error_rollback}). Se requiere intervención humana."
                ) from error_rollback
            raise ErrorDespliegue(
                f"Falló la activación y se restauró la release anterior: {error_original}"
            ) from error_original

    def rollback(self, sha: str | None = None) -> None:
        """Activa ``previous`` o una release preparada mediante el mismo flujo."""

        if sha is None:
            objetivo = resolver_enlace_release(self.previous, self.releases)
            if objetivo is None:
                raise ErrorDespliegue("No existe previous para rollback.")
            sha = objetivo.name
        self.activar(sha)

    def _validar_release_preparada(self, release: Path) -> None:
        """Exige directorio canónico, marcador y estructura antes de activar."""

        try:
            release.resolve().relative_to(self.releases.resolve())
        except ValueError as error:
            raise ErrorDespliegue("La release objetivo queda fuera de releases.") from error
        marcador = release / MARCADOR_PREPARADA
        if not marcador.is_file():
            raise ErrorDespliegue(f"La release {release.name} no está marcada como preparada.")
        datos = json.loads(marcador.read_text(encoding="utf-8"))
        if datos.get("commit_sha") != release.name:
            raise ErrorDespliegue("El marcador preparado no coincide con el directorio SHA.")
        self._validar_estructura_release(release)

    def estado(self) -> dict[str, Any]:
        """Entrega estado de enlaces y releases sin mutar el host."""

        actual = resolver_enlace_release(self.current, self.releases)
        anterior = resolver_enlace_release(self.previous, self.releases)
        preparadas = (
            sorted(
                ruta.name
                for ruta in self.releases.iterdir()
                if ruta.is_dir() and (ruta / MARCADOR_PREPARADA).is_file()
            )
            if self.releases.is_dir()
            else []
        )
        return {
            "raiz": str(self.raiz),
            "current": actual.name if actual else None,
            "previous": anterior.name if anterior else None,
            "preparadas": preparadas,
        }

    def preflight(self) -> None:
        """Verifica prerequisitos sin instalarlos ni modificar el sistema."""

        for comando in (
            "uv",
            "systemctl",
            "systemd-analyze",
            "nginx",
            "runuser",
            "find",
            "chown",
            "chmod",
        ):
            if shutil.which(comando) is None:
                raise ErrorDespliegue(f"Falta el prerequisito administrativo: {comando}")
        if sys.version_info[:2] != (3, 14):
            raise ErrorDespliegue("La herramienta productiva requiere Python 3.14.")
        self._validar_python_base()


def crear_parser() -> argparse.ArgumentParser:
    """Construye la CLI pública sin ofrecer bypass del guard institucional."""

    parser = argparse.ArgumentParser(description="Administra releases productivas de SIS-Leg.")
    parser.add_argument("--raiz", type=Path, default=Path("/opt/sis-leg"))
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("preflight")
    bootstrap = sub.add_parser("bootstrap")
    bootstrap.add_argument("--aplicar-usuarios", action="store_true")
    preparar = sub.add_parser("preparar")
    preparar.add_argument("paquete", type=Path)
    preparar.add_argument("--checksum", type=Path, required=True)
    preparar.add_argument("--sha", required=True)
    activar = sub.add_parser("activar")
    activar.add_argument("sha")
    rollback = sub.add_parser("rollback")
    rollback.add_argument("--sha")
    sub.add_parser("estado")
    return parser


def main(argumentos: Sequence[str] | None = None) -> int:
    """Despacha un único comando y traduce errores a exit code estable 1."""

    opciones = crear_parser().parse_args(argumentos)
    gestor = GestorDespliegue(opciones.raiz)
    try:
        if opciones.comando == "preflight":
            gestor.preflight()
        elif opciones.comando == "bootstrap":
            plan = gestor.bootstrap(aplicar_usuarios=opciones.aplicar_usuarios)
            print(json.dumps([asdict(entrada) for entrada in plan], indent=2))
        elif opciones.comando == "preparar":
            print(gestor.preparar(opciones.paquete, opciones.checksum, opciones.sha))
        elif opciones.comando == "activar":
            gestor.activar(opciones.sha)
        elif opciones.comando == "rollback":
            gestor.rollback(opciones.sha)
        elif opciones.comando == "estado":
            print(json.dumps(gestor.estado(), ensure_ascii=False, indent=2))
    except (ErrorDespliegue, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
