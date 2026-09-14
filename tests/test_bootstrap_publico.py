"""Pruebas del bootstrap público transicional (WP-105).

Cada sección nombra el caso obligatorio de ``docs/work-packages/WP-105.md`` que
demuestra. Ninguna prueba usa red, GitHub ni el host productivo:

- los paquetes se construyen con el empaquetador canónico
  (``scripts/empaquetar_produccion.py``) y los metadatos con el publicador
  canónico (``scripts/publicar_release_publica.py``), de modo que el bootstrap
  consume exactamente el formato que produce la CI;
- GitHub se reemplaza por un doble que sirve release, commit, CI y assets;
- la raíz ``/opt/sis-leg`` se simula en ``tmp_path`` con ``current``,
  ``previous``, ``target-release``, configuración y logs, para demostrar que nada
  de eso cambia.

La «herramienta moderna» empaquetada es, según la prueba, un doble mínimo que
emula ``preparar`` o la herramienta real del repositorio.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

import deploy.actualizador_publico as actualizador
import deploy.bootstrap_publico as bootstrap
import deploy.herramienta_despliegue as herramienta
from deploy.actualizador_publico import JobCi, RunCi
from deploy.bootstrap_publico import (
    DESTINO_AUSENTE,
    DESTINO_INCOMPATIBLE,
    DESTINO_PARCIAL,
    DESTINO_YA_PREPARADA,
    MODULOS_DELEGADOS,
    ClienteHttpPublicoReal,
    ErrorBootstrap,
    ErrorPreparacionDelegada,
    ResultadoHerramienta,
    clasificar_destino,
    inspeccionar_paquete,
    materializar_modulos,
    validar_manifest_moderno,
)
from deploy.configuracion_local import RUTA_CONTRATO_EN_RELEASE
from scripts.empaquetar_produccion import construir_paquete
from scripts.publicar_release_publica import construir_metadatos

SHA = "a" * 40
SHA_ARBOL = "c" * 40
SHA_OTRO = "b" * 40
REPOSITORIO = "martinebene/SIS-Leg"
RAIZ_REPOSITORIO = Path(__file__).resolve().parents[1]
RUN_ID = 5150
RUN_NUMERO = 600
JOB_ID = 880088
UV_DISPONIBLE = "/usr/bin/uv"

# Doble de ``herramienta_despliegue.py preparar``. Importa el módulo delegado
# materializado —demuestra que ``-I`` más la raíz agregada por la herramienta
# alcanzan— y deja una release marcada con el árbol de su ``release.json``.
HERRAMIENTA_DOBLE = """\
import json
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy.configuracion_local import MARCA

argumentos = sys.argv[1:]
raiz = Path(argumentos[argumentos.index("--raiz") + 1])
if argumentos[2] != "preparar":
    raise SystemExit("subcomando inesperado")
paquete = Path(argumentos[3])
sha = argumentos[argumentos.index("--sha") + 1]
with tarfile.open(paquete, "r:gz") as tar:
    miembro = tar.extractfile("release.json")
    assert miembro is not None
    manifest = json.loads(miembro.read())
destino = raiz / "releases" / sha
destino.mkdir(parents=True)
(destino / "release.json").write_text(json.dumps(manifest), encoding="utf-8")
(destino / ".sis-leg-preparada.json").write_text(
    json.dumps({"commit_sha": sha, "tree_sha": manifest["tree_sha"], "marca": MARCA}),
    encoding="utf-8",
)
print(destino)
"""

# Doble que falla a mitad de la preparación dejando un directorio parcial, como
# la herramienta real ante un ``uv sync`` fallido.
HERRAMIENTA_FALLIDA = """\
import sys
from pathlib import Path

argumentos = sys.argv[1:]
raiz = Path(argumentos[argumentos.index("--raiz") + 1])
sha = argumentos[argumentos.index("--sha") + 1]
(raiz / "releases" / sha).mkdir(parents=True)
print("diagnostico en stdout")
print("Error: uv sync falló", file=sys.stderr)
raise SystemExit(1)
"""


# ---------------------------------------------------------------------------
# Construcción de paquetes y publicaciones
# ---------------------------------------------------------------------------


def crear_checkout(raiz: Path, deploy_extra: dict[str, str] | None = None) -> None:
    """Materializa la allowlist mínima que consume el empaquetador canónico."""

    archivos = {
        "pyproject.toml": "[project]\nname='raiz'\nversion='0'\n",
        "uv.lock": "version = 1\n",
        ".python-version": "3.14\n",
        "apps/backend/pyproject.toml": "[project]\nname='sis-leg-backend'\nversion='0'\n",
        "apps/backend/src/sis_leg_backend/__init__.py": "",
        "services/device-bridge/pyproject.toml": (
            "[project]\nname='sis-leg-device-bridge'\nversion='0'\n"
        ),
        "services/device-bridge/src/sis_leg_device_bridge/__init__.py": "",
        "apps/moderacion/.output/public/index.html": "<!doctype html>Moderación",
        "apps/moderacion/.output/public/_nuxt/app.js": "m",
        "apps/recinto/.output/public/index.html": "<!doctype html>Recinto",
        "apps/recinto/.output/public/_nuxt/app.js": "r",
        "apps/simulador/.output/public/index.html": "<!doctype html>Simulador",
        "apps/simulador/.output/public/_nuxt/app.js": "s",
        "apps/tecnico/.output/public/index.html": "<!doctype html>Apoyo Técnico",
        "apps/tecnico/.output/public/_nuxt/app.js": "t",
        "apps/zocalo/.output/public/index.html": "<!doctype html>Zócalo",
        "apps/zocalo/.output/public/_nuxt/app.js": "z",
        "manual/index.html": '<!doctype html><html lang="es"><body>SIS-Leg</body></html>',
        "deploy/__init__.py": "",
        "deploy/herramienta_despliegue.py": HERRAMIENTA_DOBLE,
        "deploy/configuracion_local.py": "MARCA = 'modulo-materializado'\n",
        "deploy/validar_configuracion.py": "# validador\n",
        "deploy/systemd/sis-leg-backend.service": "[Service]\n",
        "deploy/systemd/sis-leg-device-bridge.service": "[Service]\n",
        "deploy/nginx/sis-leg.conf": "server {}\n",
        RUTA_CONTRATO_EN_RELEASE: (RAIZ_REPOSITORIO / RUTA_CONTRATO_EN_RELEASE).read_text(
            encoding="utf-8"
        ),
        **(deploy_extra or {}),
    }
    for relativa, contenido in archivos.items():
        ruta = raiz / relativa
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(contenido, encoding="utf-8")


def construir_paquete_valido(tmp_path: Path, deploy_extra: dict[str, str] | None = None) -> Path:
    """Paquete real del empaquetador canónico para ``SHA``/``SHA_ARBOL``."""

    checkout = tmp_path / "checkout"
    crear_checkout(checkout, deploy_extra)
    paquete, _ = construir_paquete(
        raiz=checkout,
        directorio_salida=tmp_path / "artefactos",
        sha_commit=SHA,
        sha_arbol=SHA_ARBOL,
    )
    return paquete


def run_exitosa(**cambios: Any) -> dict[str, Any]:
    """Intento histórico de CI que habilita la publicación."""

    run: dict[str, Any] = {
        "id": RUN_ID,
        "run_number": RUN_NUMERO,
        "run_attempt": 1,
        "name": "CI",
        "event": "push",
        "head_branch": "main",
        "head_sha": SHA,
        "status": "completed",
        "conclusion": "success",
    }
    run.update(cambios)
    return run


def jobs_exitosos(**cambios: Any) -> dict[str, Any]:
    """Jobs de ese intento con el empaquetado exitoso; ``cambios`` lo rompe."""

    comunes: dict[str, Any] = {
        "run_id": RUN_ID,
        "run_attempt": 1,
        "head_sha": SHA,
        "conclusion": "success",
    }
    job: dict[str, Any] = {**comunes, "id": JOB_ID, "name": "Empaquetado · release productiva"}
    job.update(cambios)
    return {"total_count": 2, "jobs": [{**comunes, "id": 1, "name": "Backend · pruebas"}, job]}


@dataclass
class ClientePublicoFalso:
    """Doble del API público de GitHub: sirve JSON por forma de URL y assets por nombre."""

    release: dict[str, Any]
    commit: dict[str, Any]
    run: dict[str, Any]
    jobs: dict[str, Any]
    contenidos: dict[str, bytes]
    urls: list[str] = field(default_factory=lambda: list[str]())
    errores_descarga: dict[str, Exception] = field(default_factory=lambda: dict[str, Exception]())

    def obtener_json(self, url: str, *, maximo_bytes: int = bootstrap.MAXIMO_BYTES_JSON) -> Any:
        del maximo_bytes
        self.urls.append(url)
        if "/releases/tags/" in url:
            return self.release
        if "/commits/" in url:
            return self.commit
        if url.endswith("/jobs?per_page=100"):
            return self.jobs
        if "/attempts/" in url:
            return self.run
        raise AssertionError(f"URL no prevista: {url}")

    def descargar(self, url: str, destino: Path, *, maximo_bytes: int) -> int:
        self.urls.append(url)
        nombre = url.rsplit("/", 1)[1]
        if nombre in self.errores_descarga:
            destino.write_bytes(b"parcial")
            raise self.errores_descarga[nombre]
        contenido = self.contenidos[nombre]
        if len(contenido) > maximo_bytes:
            raise ErrorBootstrap("La descarga superó el máximo aceptado.")
        destino.write_bytes(contenido)
        return len(contenido)


# Manipulaciones de a una propiedad por caso de rechazo.
RomperCliente = Callable[[ClientePublicoFalso], object]
RomperMetadatos = Callable[[dict[str, Any]], object]


def publicar(
    paquete_bytes: bytes,
    *,
    metadatos_extra: RomperMetadatos | None = None,
    sidecar: bytes | None = None,
) -> ClientePublicoFalso:
    """Arma una publicación coherente a partir de los bytes de un paquete.

    Los metadatos salen del publicador canónico: si su formato cambiara, estas
    pruebas romperían en lugar de producción.
    """

    checksum = hashlib.sha256(paquete_bytes).hexdigest()
    metadatos = construir_metadatos(
        repositorio=REPOSITORIO,
        sha=SHA,
        tree_sha=SHA_ARBOL,
        checksum=checksum,
        tamano=len(paquete_bytes),
        run=RunCi(identificador=RUN_ID, numero=RUN_NUMERO, intento=1, head_sha=SHA, workflow="CI"),
        job=JobCi(
            identificador=JOB_ID,
            nombre="Empaquetado · release productiva",
            head_sha=SHA,
            run_id=RUN_ID,
            intento=1,
        ),
    )
    if metadatos_extra is not None:
        metadatos_extra(metadatos)
    nombre = bootstrap.nombre_paquete(SHA)
    contenidos = {
        nombre: paquete_bytes,
        bootstrap.nombre_sidecar(SHA): sidecar
        if sidecar is not None
        else f"{checksum}  {nombre}\n".encode("ascii"),
        bootstrap.nombre_metadatos(SHA): json.dumps(metadatos).encode("utf-8"),
    }
    release = {
        "tag_name": bootstrap.tag_publicacion(SHA),
        "target_commitish": SHA,
        "draft": False,
        "prerelease": False,
        "assets": [
            {
                "name": nombre_asset,
                "state": "uploaded",
                "size": len(datos),
                "browser_download_url": f"https://github.com/{REPOSITORIO}/releases/download/"
                f"{bootstrap.tag_publicacion(SHA)}/{nombre_asset}",
            }
            for nombre_asset, datos in contenidos.items()
        ],
    }
    return ClientePublicoFalso(
        release=release,
        commit={"sha": SHA, "commit": {"tree": {"sha": SHA_ARBOL}}},
        run=run_exitosa(),
        jobs=jobs_exitosos(),
        contenidos=contenidos,
    )


def crear_raiz_productiva(base: Path) -> Path:
    """Simula ``/opt/sis-leg`` con release activa, target, configuración y logs."""

    raiz = base / "opt-sis-leg"
    anterior = raiz / "releases" / SHA_OTRO
    (anterior / "deploy").mkdir(parents=True)
    (anterior / "deploy/herramienta_despliegue.py").write_text("# histórica\n", encoding="utf-8")
    os.symlink(f"releases/{SHA_OTRO}", raiz / "current")
    os.symlink(f"releases/{SHA_OTRO}", raiz / "previous")
    (raiz / "target-release").write_text(f"{SHA_OTRO}\n", encoding="utf-8")
    (raiz / "config/bridge").mkdir(parents=True)
    (raiz / "config/system.toml").write_text("[institucion]\n", encoding="utf-8")
    (raiz / "config/concejales.csv").write_text("id;nombre\n", encoding="utf-8")
    (raiz / "config/bridge/devices.json").write_text("{}\n", encoding="utf-8")
    (raiz / "logs").mkdir()
    (raiz / "logs/2026-09-01.csv").write_text("seq;timestamp\n", encoding="utf-8")
    return raiz


def instantanea(raiz: Path) -> dict[str, tuple[str, str]]:
    """Captura tipo y contenido/destino de cada entrada para comparar antes y después."""

    resultado: dict[str, tuple[str, str]] = {}
    for ruta in sorted(raiz.rglob("*")):
        relativa = ruta.relative_to(raiz).as_posix()
        if ruta.is_symlink():
            resultado[relativa] = ("enlace", os.readlink(ruta))
        elif ruta.is_dir():
            resultado[relativa] = ("dir", oct(ruta.stat().st_mode))
        else:
            resultado[relativa] = ("archivo", hashlib.sha256(ruta.read_bytes()).hexdigest())
    return resultado


class EjecutorEspia:
    """Registra la delegación y comprueba lo materializado en el momento de ejecutar."""

    def __init__(self, real: bool = True) -> None:
        self.llamadas: list[list[str]] = []
        self.real = real
        self.hashes_al_ejecutar: dict[str, str] = {}

    def __call__(self, argumentos: Sequence[str], directorio: Path) -> ResultadoHerramienta:
        self.llamadas.append(list(argumentos))
        herramienta_ruta = Path(argumentos[3])
        raiz_modulos = herramienta_ruta.parents[1]
        for modulo in MODULOS_DELEGADOS:
            ruta = raiz_modulos / modulo
            self.hashes_al_ejecutar[modulo] = hashlib.sha256(ruta.read_bytes()).hexdigest()
        if not self.real:
            return ResultadoHerramienta(0, "", "")
        return bootstrap.ejecutar_herramienta_real(argumentos, directorio)


@dataclass
class Escenario:
    """Todo lo necesario para ejecutar el bootstrap de punta a punta."""

    cliente: ClientePublicoFalso
    raiz: Path
    temporales: Path
    paquete: Path


@pytest.fixture
def escenario(tmp_path: Path) -> Escenario:
    paquete = construir_paquete_valido(tmp_path)
    temporales = tmp_path / "temporales"
    temporales.mkdir()
    return Escenario(
        cliente=publicar(paquete.read_bytes()),
        raiz=crear_raiz_productiva(tmp_path),
        temporales=temporales,
        paquete=paquete,
    )


def preparar_escenario(
    escenario: Escenario, ejecutor: bootstrap.EjecutorHerramienta, **extra: Any
) -> dict[str, Any]:
    return bootstrap.preparar(
        sha=SHA,
        tree_sha=SHA_ARBOL,
        raiz=escenario.raiz,
        directorio_temporal=escenario.temporales,
        cliente=escenario.cliente,
        ejecutor=ejecutor,
        **extra,
    )


def exigir_rechazo_sin_ejecutar(escenario: Escenario, fragmento: str) -> None:
    """Falla cerrada: error esperado, nada ejecutado, raíz intacta, temporal limpio."""

    antes = instantanea(escenario.raiz)
    espia = EjecutorEspia()
    with pytest.raises(ErrorBootstrap, match=fragmento):
        preparar_escenario(escenario, espia)
    assert espia.llamadas == []
    assert instantanea(escenario.raiz) == antes
    assert list(escenario.temporales.iterdir()) == []


def reescribir_tar(
    origen: Path,
    destino: Path,
    *,
    transformar: Callable[[str, bytes], list[tuple[tarfile.TarInfo, bytes | None]]] | None = None,
    agregar: Sequence[tuple[tarfile.TarInfo, bytes | None]] = (),
) -> bytes:
    """Copia un tar miembro a miembro aplicando manipulaciones controladas."""

    buffer = io.BytesIO()
    with (
        tarfile.open(origen, "r:gz") as tar_origen,
        tarfile.open(fileobj=buffer, mode="w:gz", format=tarfile.PAX_FORMAT) as tar_destino,
    ):
        for miembro in tar_origen.getmembers():
            archivo = tar_origen.extractfile(miembro)
            assert archivo is not None
            datos = archivo.read()
            entradas = (
                transformar(miembro.name, datos) if transformar is not None else [(miembro, datos)]
            )
            for info, contenido in entradas:
                if contenido is None:
                    tar_destino.addfile(info)
                else:
                    info.size = len(contenido)
                    tar_destino.addfile(info, io.BytesIO(contenido))
        for info, contenido in agregar:
            if contenido is None:
                tar_destino.addfile(info)
            else:
                info.size = len(contenido)
                tar_destino.addfile(info, io.BytesIO(contenido))
    destino.write_bytes(buffer.getvalue())
    return buffer.getvalue()


def info(nombre: str, tipo: bytes = tarfile.REGTYPE, enlace: str = "") -> tarfile.TarInfo:
    entrada = tarfile.TarInfo(nombre)
    entrada.type = tipo
    entrada.linkname = enlace
    return entrada


def manifest_modificado(
    cambio: Callable[[dict[str, Any]], None],
) -> Callable[[str, bytes], list[tuple[tarfile.TarInfo, bytes | None]]]:
    """Transformación que altera sólo ``release.json``."""

    def transformar(nombre: str, datos: bytes) -> list[tuple[tarfile.TarInfo, bytes | None]]:
        if nombre != "release.json":
            return [(tarfile.TarInfo(nombre), datos)]
        manifest = json.loads(datos)
        cambio(manifest)
        return [(tarfile.TarInfo(nombre), json.dumps(manifest).encode("utf-8"))]

    return transformar


def escenario_con_paquete(escenario: Escenario, paquete_bytes: bytes) -> Escenario:
    """Mismo host, pero publicación coherente para otro paquete (checksum incluido)."""

    return Escenario(
        cliente=publicar(paquete_bytes),
        raiz=escenario.raiz,
        temporales=escenario.temporales,
        paquete=escenario.paquete,
    )


# ---------------------------------------------------------------------------
# Caso 1 - release válida completa: valida y delega en la herramienta moderna
# ---------------------------------------------------------------------------


def test_release_valida_se_verifica_y_delega_en_la_herramienta_moderna(
    escenario: Escenario,
) -> None:
    espia = EjecutorEspia()
    informe = preparar_escenario(escenario, espia)

    assert informe["resultado"] == "PREPARADA"
    assert informe["release_sha"] == SHA
    assert informe["tree_sha"] == SHA_ARBOL
    assert informe["ci_run_id"] == RUN_ID
    assert informe["ci_job_id"] == JOB_ID
    assert informe["paquete_sha256"] == hashlib.sha256(escenario.paquete.read_bytes()).hexdigest()

    # Una única delegación, aislada con -I, al subcomando preparar sobre el paquete verificado.
    assert len(espia.llamadas) == 1
    argumentos = espia.llamadas[0]
    assert argumentos[0] == sys.executable
    assert argumentos[1:3] == ["-I", "-B"]
    assert argumentos[3].endswith("herramienta/deploy/herramienta_despliegue.py")
    assert argumentos[4:7] == ["--raiz", str(escenario.raiz.resolve()), "preparar"]
    assert argumentos[-2:] == ["--sha", SHA]

    # Lo que se ejecutó eran exactamente los bytes inventariados en release.json.
    with tarfile.open(escenario.paquete, "r:gz") as tar:
        miembro = tar.extractfile("release.json")
        assert miembro is not None
        inventario = {
            entrada["ruta"]: entrada["sha256"] for entrada in json.loads(miembro.read())["archivos"]
        }
    assert espia.hashes_al_ejecutar == {modulo: inventario[modulo] for modulo in MODULOS_DELEGADOS}

    marcador = json.loads(
        (escenario.raiz / "releases" / SHA / ".sis-leg-preparada.json").read_text(encoding="utf-8")
    )
    assert marcador["marca"] == "modulo-materializado"
    assert clasificar_destino(escenario.raiz, SHA, SHA_ARBOL)[0] == DESTINO_YA_PREPARADA


def test_la_delegacion_con_la_herramienta_real_preserva_su_diagnostico(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La herramienta real del repositorio corre materializada y su falla se preserva.

    Sin ``uv`` en ``PATH`` la herramienta moderna real no puede completar
    ``preparar``. Lo que importa acá es que realmente arrancó desde el temporal
    —importando su propio ``configuracion_local`` bajo ``-I``— y que su código y
    salida de error vuelven intactos, sin tocar ``current`` ni ``target-release``.
    """

    reales = {
        "deploy/herramienta_despliegue.py": (
            RAIZ_REPOSITORIO / "deploy/herramienta_despliegue.py"
        ).read_text(encoding="utf-8"),
        "deploy/configuracion_local.py": (
            RAIZ_REPOSITORIO / "deploy/configuracion_local.py"
        ).read_text(encoding="utf-8"),
        "deploy/__init__.py": (RAIZ_REPOSITORIO / "deploy/__init__.py").read_text(encoding="utf-8"),
    }
    paquete = construir_paquete_valido(tmp_path, reales)
    raiz = crear_raiz_productiva(tmp_path)
    temporales = tmp_path / "temporales"
    temporales.mkdir()
    sin_uv = tmp_path / "path-vacio"
    sin_uv.mkdir()
    monkeypatch.setenv("PATH", str(sin_uv))
    esperados = {clave: valor for clave, valor in instantanea(raiz).items()}

    with pytest.raises(ErrorPreparacionDelegada) as capturado:
        bootstrap.preparar(
            sha=SHA,
            tree_sha=SHA_ARBOL,
            raiz=raiz,
            directorio_temporal=temporales,
            cliente=publicar(paquete.read_bytes()),
        )

    resultado = capturado.value.resultado
    assert resultado.codigo == 1
    assert "Error:" in resultado.error
    assert "ModuleNotFoundError" not in resultado.error
    assert "Traceback" not in resultado.error
    despues = instantanea(raiz)
    for clave in ("current", "previous", "target-release", "config/system.toml", "logs"):
        assert despues[clave] == esperados[clave]
    assert list(temporales.iterdir()) == []


# ---------------------------------------------------------------------------
# Caso 2 - SHA / tag / target divergentes
# ---------------------------------------------------------------------------


CASOS_IDENTIDAD: list[tuple[RomperCliente, str]] = [
    (lambda c: c.release.update(tag_name=f"sis-leg-{SHA_OTRO}"), "tag distinto"),
    (lambda c: c.release.update(target_commitish=SHA_OTRO), "apunta a"),
    (lambda c: c.release.update(target_commitish="otra-rama"), "apunta a"),
    (lambda c: c.commit.update(sha=SHA_OTRO), "otro commit"),
    (lambda c: c.commit.update(commit={"tree": {"sha": SHA_OTRO}}), "árbol"),
]


@pytest.mark.parametrize(("romper", "fragmento"), CASOS_IDENTIDAD)
def test_identidad_divergente_falla_cerrado(
    escenario: Escenario, romper: RomperCliente, fragmento: str
) -> None:
    romper(escenario.cliente)
    exigir_rechazo_sin_ejecutar(escenario, fragmento)


@pytest.mark.parametrize("sha_pedido", ["a" * 39, "A" * 40, "a" * 7, f"{'a' * 39}g"])
def test_identidades_abreviadas_o_ambiguas_se_rechazan_antes_de_la_red(
    escenario: Escenario, sha_pedido: str
) -> None:
    with pytest.raises(ErrorBootstrap, match="40 hexadecimales"):
        bootstrap.preparar(
            sha=sha_pedido,
            tree_sha=SHA_ARBOL,
            raiz=escenario.raiz,
            directorio_temporal=escenario.temporales,
            cliente=escenario.cliente,
            ejecutor=EjecutorEspia(),
        )
    assert escenario.cliente.urls == []


def test_tree_sha_pedido_distinto_falla_cerrado(escenario: Escenario) -> None:
    espia = EjecutorEspia()
    with pytest.raises(ErrorBootstrap, match="árbol"):
        bootstrap.preparar(
            sha=SHA,
            tree_sha=SHA_OTRO,
            raiz=escenario.raiz,
            directorio_temporal=escenario.temporales,
            cliente=escenario.cliente,
            ejecutor=espia,
        )
    assert espia.llamadas == []


# ---------------------------------------------------------------------------
# Caso 3 - draft/prerelease o assets inesperados
# ---------------------------------------------------------------------------


def _asset_extra(cliente: ClientePublicoFalso) -> None:
    cliente.release["assets"].append(
        {
            "name": "otro.txt",
            "state": "uploaded",
            "size": 1,
            "browser_download_url": "https://github.com/x/otro.txt",
        }
    )


CASOS_PUBLICACION: list[tuple[RomperCliente, str]] = [
    (lambda c: c.release.update(draft=True), "borrador o prerelease"),
    (lambda c: c.release.update(prerelease=True), "borrador o prerelease"),
    (lambda c: c.release.update(draft=None), "borrador o prerelease"),
    (_asset_extra, "asset inesperado"),
    (lambda c: c.release["assets"].pop(), "no expone"),
    (lambda c: c.release["assets"].append(dict(c.release["assets"][0])), "duplica"),
    (lambda c: c.release["assets"][0].update(state="starter"), "completamente subido"),
    (
        lambda c: c.release["assets"][0].update(
            browser_download_url="http://github.com/sis-leg.tar.gz"
        ),
        "HTTPS",
    ),
    (
        lambda c: c.release["assets"][0].update(
            browser_download_url="https://ejemplo.invalido/sis-leg.tar.gz"
        ),
        "Host no permitido",
    ),
]


@pytest.mark.parametrize(("romper", "fragmento"), CASOS_PUBLICACION)
def test_publicacion_no_consumible_falla_cerrado(
    escenario: Escenario, romper: RomperCliente, fragmento: str
) -> None:
    romper(escenario.cliente)
    exigir_rechazo_sin_ejecutar(escenario, fragmento)


# ---------------------------------------------------------------------------
# Caso 4 - CI / job / tree / metadatos inconsistentes
# ---------------------------------------------------------------------------


CASOS_CI: list[tuple[RomperCliente, str]] = [
    (lambda c: c.run.update(conclusion="failure"), "conclusion"),
    (lambda c: c.run.update(status="in_progress"), "status"),
    (lambda c: c.run.update(event="pull_request"), "event"),
    (lambda c: c.run.update(head_branch="wp/otra"), "head_branch"),
    (lambda c: c.run.update(head_sha=SHA_OTRO), "head_sha"),
    (lambda c: c.run.update(name="Otro"), "name"),
    (lambda c: c.run.update(run_attempt=2), "otra ejecución"),
    (lambda c: c.jobs.update(jobs_exitosos(conclusion="failure")), "no es exitoso"),
    (lambda c: c.jobs.update(jobs_exitosos(head_sha=SHA_OTRO)), "no es exitoso"),
    (lambda c: c.jobs.update(jobs_exitosos(run_attempt=2)), "no es exitoso"),
    (lambda c: c.jobs.update(jobs_exitosos(name="Empaquetado")), "exactamente un job"),
    (lambda c: c.jobs.update(total_count=500), "paginado"),
]


@pytest.mark.parametrize(("romper", "fragmento"), CASOS_CI)
def test_evidencia_de_ci_inconsistente_falla_cerrado(
    escenario: Escenario, romper: RomperCliente, fragmento: str
) -> None:
    romper(escenario.cliente)
    exigir_rechazo_sin_ejecutar(escenario, fragmento)


def _cambiar_ci(clave: str, valor: object) -> RomperMetadatos:
    return lambda metadatos: metadatos["ci"].update({clave: valor})


CASOS_METADATOS: list[tuple[RomperMetadatos, str]] = [
    (lambda m: m.update(tree_sha=SHA_OTRO), "tree SHA"),
    (lambda m: m.update(commit_sha=SHA_OTRO), "otro commit"),
    (lambda m: m.update(repositorio="otro/repo"), "otro repositorio"),
    (lambda m: m.update(tag="sis-leg-x"), "otro tag"),
    (lambda m: m.update(version_formato=2), "formato"),
    (_cambiar_ci("job_id", JOB_ID + 1), "ci.job_id"),
    (_cambiar_ci("run_number", RUN_NUMERO + 1), "ci.run_number"),
    (_cambiar_ci("rama", "otra"), "ci.rama"),
    (_cambiar_ci("run_attempt", True), "no declara run_attempt entero"),
    (lambda m: m["paquete"].update(nombre="otro.tar.gz"), "paquete distinto"),
    (lambda m: m["sidecar"].update(nombre="otro.sha256"), "sidecar distinto"),
]


@pytest.mark.parametrize(("romper", "fragmento"), CASOS_METADATOS)
def test_metadatos_inconsistentes_fallan_cerrado(
    escenario: Escenario, romper: RomperMetadatos, fragmento: str
) -> None:
    cliente = publicar(escenario.paquete.read_bytes(), metadatos_extra=romper)
    exigir_rechazo_sin_ejecutar(
        Escenario(cliente, escenario.raiz, escenario.temporales, escenario.paquete), fragmento
    )


def test_metadatos_invalidos_no_descargan_el_paquete(escenario: Escenario) -> None:
    """La evidencia barata se valida antes de bajar el asset caro."""

    cliente = publicar(
        escenario.paquete.read_bytes(), metadatos_extra=lambda m: m.update(tree_sha=SHA_OTRO)
    )
    with pytest.raises(ErrorBootstrap):
        preparar_escenario(
            Escenario(cliente, escenario.raiz, escenario.temporales, escenario.paquete),
            EjecutorEspia(),
        )
    assert not any(url.endswith(".tar.gz") for url in cliente.urls)


# ---------------------------------------------------------------------------
# Caso 5 - checksum incorrecto: fail-closed antes de ejecutar código extraído
# ---------------------------------------------------------------------------


def test_sidecar_con_checksum_distinto_falla_antes_de_ejecutar(escenario: Escenario) -> None:
    nombre = bootstrap.nombre_paquete(SHA)
    cliente = publicar(
        escenario.paquete.read_bytes(), sidecar=f"{'0' * 64}  {nombre}\n".encode("ascii")
    )
    exigir_rechazo_sin_ejecutar(
        Escenario(cliente, escenario.raiz, escenario.temporales, escenario.paquete),
        "Checksum incorrecto",
    )


def test_paquete_alterado_con_mismo_tamano_falla_antes_de_ejecutar(escenario: Escenario) -> None:
    nombre = bootstrap.nombre_paquete(SHA)
    original = escenario.cliente.contenidos[nombre]
    escenario.cliente.contenidos[nombre] = original[:-1] + bytes([original[-1] ^ 0xFF])
    exigir_rechazo_sin_ejecutar(escenario, "Checksum incorrecto")


def test_sidecar_con_otro_nombre_falla(escenario: Escenario) -> None:
    checksum = hashlib.sha256(escenario.paquete.read_bytes()).hexdigest()
    cliente = publicar(
        escenario.paquete.read_bytes(), sidecar=f"{checksum}  otro.tar.gz\n".encode("ascii")
    )
    exigir_rechazo_sin_ejecutar(
        Escenario(cliente, escenario.raiz, escenario.temporales, escenario.paquete),
        "formato o nombre",
    )


def test_fijacion_de_sha256_distinta_falla(escenario: Escenario) -> None:
    espia = EjecutorEspia()
    with pytest.raises(ErrorBootstrap, match="SHA-256 de paquete pedido"):
        preparar_escenario(escenario, espia, paquete_sha256="f" * 64)
    assert espia.llamadas == []
    assert not any(url.endswith(".tar.gz") for url in escenario.cliente.urls)


# ---------------------------------------------------------------------------
# Caso 6 - release.json inválido, traversal, enlaces, especiales o inventario inconsistente
# ---------------------------------------------------------------------------


def _reemplazar_release_json(
    contenido: bytes,
) -> Callable[[str, bytes], list[tuple[tarfile.TarInfo, bytes | None]]]:
    def transformar(nombre: str, datos: bytes) -> list[tuple[tarfile.TarInfo, bytes | None]]:
        return [(tarfile.TarInfo(nombre), contenido if nombre == "release.json" else datos)]

    return transformar


def _alterar_modulo(
    nombre_objetivo: str,
) -> Callable[[str, bytes], list[tuple[tarfile.TarInfo, bytes | None]]]:
    def transformar(nombre: str, datos: bytes) -> list[tuple[tarfile.TarInfo, bytes | None]]:
        if nombre == nombre_objetivo:
            datos = datos + b"\nimport os  # inyectado\n"
        return [(tarfile.TarInfo(nombre), datos)]

    return transformar


def _duplicar(
    nombre_objetivo: str,
) -> Callable[[str, bytes], list[tuple[tarfile.TarInfo, bytes | None]]]:
    def transformar(nombre: str, datos: bytes) -> list[tuple[tarfile.TarInfo, bytes | None]]:
        entradas: list[tuple[tarfile.TarInfo, bytes | None]] = [(tarfile.TarInfo(nombre), datos)]
        if nombre == nombre_objetivo:
            entradas.append((tarfile.TarInfo(nombre), datos))
        return entradas

    return transformar


def _omitir(
    nombre_objetivo: str,
) -> Callable[[str, bytes], list[tuple[tarfile.TarInfo, bytes | None]]]:
    def transformar(nombre: str, datos: bytes) -> list[tuple[tarfile.TarInfo, bytes | None]]:
        return [] if nombre == nombre_objetivo else [(tarfile.TarInfo(nombre), datos)]

    return transformar


CASOS_TAR_MALICIOSO: list[tuple[str, dict[str, Any], str]] = [
    ("json-invalido", {"transformar": _reemplazar_release_json(b"{no json")}, "inválido"),
    ("json-lista", {"transformar": _reemplazar_release_json(b"[]")}, "objeto JSON"),
    (
        "traversal",
        {"agregar": [(info("deploy/../../etc/passwd"), b"x")]},
        "ambigua|traversal",
    ),
    ("absoluta", {"agregar": [(info("/etc/cron.d/x"), b"x")]}, "absoluta"),
    ("fuera-allowlist", {"agregar": [(info("otros/x.py"), b"x")]}, "allowlist"),
    (
        "symlink",
        {"agregar": [(info("deploy/enlace", tarfile.SYMTYPE, "/etc/shadow"), None)]},
        "archivos regulares",
    ),
    (
        "hardlink",
        {"agregar": [(info("deploy/duro", tarfile.LNKTYPE, "deploy/__init__.py"), None)]},
        "archivos regulares",
    ),
    ("fifo", {"agregar": [(info("deploy/fifo", tarfile.FIFOTYPE), None)]}, "archivos regulares"),
    (
        "dispositivo",
        {"agregar": [(info("deploy/dispositivo", tarfile.CHRTYPE), None)]},
        "archivos regulares",
    ),
    ("directorio", {"agregar": [(info("deploy/sub", tarfile.DIRTYPE), None)]}, "regulares"),
    ("extra-no-inventariado", {"agregar": [(info("deploy/extra.py"), b"x")]}, "inventario"),
    ("faltante", {"transformar": _omitir("web/manual/index.html")}, "inventario"),
    ("duplicado", {"transformar": _duplicar("deploy/__init__.py")}, "duplicada"),
    (
        "contenido-distinto",
        {"transformar": _alterar_modulo("web/moderacion/index.html")},
        "tamaño|contenido",
    ),
    (
        "inventario-sin-modulo-delegado",
        {
            "transformar": manifest_modificado(
                lambda m: m.update(
                    archivos=[
                        a for a in m["archivos"] if a["ruta"] != "deploy/configuracion_local.py"
                    ]
                )
            )
        },
        "configuracion_local",
    ),
    (
        "inventario-hash-invalido",
        {"transformar": manifest_modificado(lambda m: m["archivos"][0].update(sha256="Z" * 64))},
        "Checksum inválido",
    ),
]


@pytest.mark.parametrize(
    ("manipulacion", "fragmento"),
    [(caso[1], caso[2]) for caso in CASOS_TAR_MALICIOSO],
    ids=[caso[0] for caso in CASOS_TAR_MALICIOSO],
)
def test_paquete_malicioso_o_inconsistente_falla_cerrado(
    escenario: Escenario, tmp_path: Path, manipulacion: dict[str, Any], fragmento: str
) -> None:
    datos = reescribir_tar(escenario.paquete, tmp_path / "malicioso.tar.gz", **manipulacion)
    exigir_rechazo_sin_ejecutar(escenario_con_paquete(escenario, datos), fragmento)


# ---------------------------------------------------------------------------
# Caso 7 - módulos delegados con hash distinto del inventario: no se ejecutan
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("modulo", MODULOS_DELEGADOS)
def test_modulo_delegado_alterado_en_el_paquete_no_se_ejecuta(
    escenario: Escenario, tmp_path: Path, modulo: str
) -> None:
    datos = reescribir_tar(
        escenario.paquete, tmp_path / "alterado.tar.gz", transformar=_alterar_modulo(modulo)
    )
    exigir_rechazo_sin_ejecutar(escenario_con_paquete(escenario, datos), "tamaño|contenido")


def test_materializacion_con_bytes_distintos_del_inventario_se_niega(tmp_path: Path) -> None:
    paquete = construir_paquete_valido(tmp_path)
    _, inventario = inspeccionar_paquete(paquete, SHA)
    alterado = dict(inventario)
    checksum, tamano = alterado["deploy/configuracion_local.py"]
    alterado["deploy/configuracion_local.py"] = ("0" * 64, tamano)
    assert checksum != "0" * 64

    destino = tmp_path / "materializado"
    destino.mkdir()
    with pytest.raises(ErrorBootstrap, match="no se ejecuta"):
        materializar_modulos(paquete, alterado, destino)


def test_materializacion_valida_escribe_solo_los_modulos_delegados(tmp_path: Path) -> None:
    paquete = construir_paquete_valido(tmp_path)
    _, inventario = inspeccionar_paquete(paquete, SHA)
    destino = tmp_path / "materializado"
    destino.mkdir()

    herramienta_ruta = materializar_modulos(paquete, inventario, destino)

    assert herramienta_ruta == destino / "deploy/herramienta_despliegue.py"
    escritos = sorted(p.relative_to(destino).as_posix() for p in destino.rglob("*") if p.is_file())
    assert escritos == sorted(MODULOS_DELEGADOS)


# ---------------------------------------------------------------------------
# Casos 8 y 9 - contrato moderno de cinco SPA + manual; el histórico no se usa
# ---------------------------------------------------------------------------

SPAS_HISTORICAS = {
    "moderacion": "web/moderacion/index.html",
    "recinto": "web/recinto/index.html",
    "simulador": "web/simulador/index.html",
    "tecnico": "web/tecnico/index.html",
}


def test_el_contrato_historico_de_cuatro_spa_no_valida_el_manifest_moderno(
    escenario: Escenario, tmp_path: Path
) -> None:
    assert bootstrap.SPAS_CANONICAS != SPAS_HISTORICAS
    assert "zocalo" in bootstrap.SPAS_CANONICAS
    datos = reescribir_tar(
        escenario.paquete,
        tmp_path / "cuatro.tar.gz",
        transformar=manifest_modificado(lambda m: m.update(spas=SPAS_HISTORICAS)),
    )
    exigir_rechazo_sin_ejecutar(escenario_con_paquete(escenario, datos), "cinco SPA")


def test_contrato_vigente_de_cinco_spa_y_manual_se_acepta(tmp_path: Path) -> None:
    paquete = construir_paquete_valido(tmp_path)
    manifest, inventario = inspeccionar_paquete(paquete, SHA)

    assert manifest["spas"]["zocalo"] == "web/zocalo/index.html"
    assert manifest["manual"] == "web/manual/index.html"
    assert set(MODULOS_DELEGADOS) <= inventario.keys()
    # La herramienta moderna canónica acepta exactamente el mismo manifest.
    assert herramienta.validar_manifest(manifest, SHA) == inventario


def _variantes_manifest(base: dict[str, Any]) -> list[dict[str, Any]]:
    """Manifests de a una propiedad rota, para comparar ambos validadores."""

    variantes: list[dict[str, Any]] = [base]
    for clave, valor in (
        ("spas", SPAS_HISTORICAS),
        ("manual", "web/manual/otro.html"),
        ("python", "3.13"),
        ("formato", "otro"),
        ("version_formato", 2),
        ("commit_sha", SHA_OTRO),
        ("tree_sha", "corto"),
        ("paquetes_python", ["sis-leg-backend"]),
        ("archivos", {}),
    ):
        variantes.append({**base, clave: valor})
    for ruta in ("web/zocalo/index.html", RUTA_CONTRATO_EN_RELEASE, "deploy/nginx/sis-leg.conf"):
        variantes.append({**base, "archivos": [a for a in base["archivos"] if a["ruta"] != ruta]})
    variantes.append(
        {**base, "archivos": [*base["archivos"], {"ruta": "../x", "sha256": "0" * 64, "tamano": 1}]}
    )
    return variantes


def test_el_validador_del_bootstrap_coincide_con_el_de_la_herramienta_moderna(
    tmp_path: Path,
) -> None:
    """Paridad: ninguna variante acepta uno y rechaza el otro."""

    manifest, _ = inspeccionar_paquete(construir_paquete_valido(tmp_path), SHA)
    for variante in _variantes_manifest(manifest):
        try:
            herramienta.validar_manifest(variante, SHA)
            acepta_herramienta = True
        except herramienta.ErrorDespliegue:
            acepta_herramienta = False
        try:
            validar_manifest_moderno(variante, SHA)
            acepta_bootstrap = True
        except ErrorBootstrap:
            acepta_bootstrap = False
        assert acepta_bootstrap == acepta_herramienta, variante


# ---------------------------------------------------------------------------
# Caso 10 - preparar no modifica current, target-release, servicios, Nginx,
# wrappers ni configuración
# ---------------------------------------------------------------------------


def test_preparar_solo_agrega_la_release_nueva(escenario: Escenario, tmp_path: Path) -> None:
    # Destinos de sistema simulados fuera de la raíz: el bootstrap no recibe
    # ninguna ruta hacia ellos, y la instantánea demuestra que siguen iguales.
    for relativa in (
        "etc/systemd/system/sis-leg-backend.service",
        "etc/nginx/conf.d/sis-leg.conf",
        "usr/local/bin/sis-leg-actualizar",
        "home/concejo/.local/bin/sis-leg-conmutar",
        "home/concejo/Escritorio/SIS-Leg.desktop",
        "etc/sudoers.d/sis-leg",
    ):
        ruta = tmp_path / "sistema" / relativa
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text("original\n", encoding="utf-8")
    sistema_antes = instantanea(tmp_path / "sistema")
    raiz_antes = instantanea(escenario.raiz)

    preparar_escenario(escenario, EjecutorEspia())

    raiz_despues = instantanea(escenario.raiz)
    nuevas = {clave for clave in raiz_despues if clave.startswith(f"releases/{SHA}")}
    assert nuevas
    assert {clave: valor for clave, valor in raiz_despues.items() if clave not in nuevas} == (
        raiz_antes
    )
    assert instantanea(tmp_path / "sistema") == sistema_antes


def test_el_bootstrap_no_contiene_operaciones_de_activacion_ni_sistema() -> None:
    """Revisión estática: sin enlaces, reemplazos, permisos ni comandos de sistema."""

    fuente = Path(bootstrap.__file__).read_text(encoding="utf-8")
    arbol = ast.parse(fuente)
    constantes = {nodo.value for nodo in ast.walk(arbol) if isinstance(nodo, ast.Constant)}
    for prohibida in ("systemctl", "nginx", "sudo", "pkexec", "runuser", "activar", "rollback"):
        assert prohibida not in constantes
    llamadas = {ast.unparse(nodo.func) for nodo in ast.walk(arbol) if isinstance(nodo, ast.Call)}
    for prohibida in (
        "os.symlink",
        "os.replace",
        "os.rename",
        "os.chmod",
        "os.chown",
        "shutil.chown",
        "os.unlink",
        "os.remove",
    ):
        assert prohibida not in llamadas
    assert fuente.count("shutil.rmtree(") == 1  # sólo el temporal privado
    assert bootstrap.SUBCOMANDO_DELEGADO == "preparar"
    # La CLI sólo ofrece diagnosticar y preparar: cualquier otro subcomando es inválido.
    assert "{diagnosticar,preparar}" in bootstrap.crear_parser().format_usage()
    for subcomando in ("activar", "rollback", "conmutar", "instalar"):
        with pytest.raises(SystemExit):
            bootstrap.crear_parser().parse_args([subcomando])


# ---------------------------------------------------------------------------
# Casos 11 y 12 - directorio parcial / release ya preparada
# ---------------------------------------------------------------------------


def test_directorio_parcial_existente_aborta_sin_borrar_ni_consultar_la_red(
    escenario: Escenario,
) -> None:
    parcial = escenario.raiz / "releases" / SHA
    (parcial / "app").mkdir(parents=True)
    (parcial / "app/residuo.txt").write_text("diagnóstico\n", encoding="utf-8")
    antes = instantanea(escenario.raiz)

    with pytest.raises(ErrorBootstrap, match="inspección administrativa"):
        preparar_escenario(escenario, EjecutorEspia())

    assert instantanea(escenario.raiz) == antes
    assert escenario.cliente.urls == []


CASOS_MARCADOR: list[Callable[[Path], object]] = [
    lambda d: (d / ".sis-leg-preparada.json").write_text(
        json.dumps({"commit_sha": SHA, "tree_sha": SHA_OTRO}), encoding="utf-8"
    ),
    lambda d: (d / ".sis-leg-preparada.json").write_text("{roto", encoding="utf-8"),
    lambda d: (d / ".sis-leg-preparada.json").mkdir(),
]


@pytest.mark.parametrize("preparar_destino", CASOS_MARCADOR)
def test_marcador_incompatible_aborta_sin_borrar(
    escenario: Escenario, preparar_destino: Callable[[Path], object]
) -> None:
    destino = escenario.raiz / "releases" / SHA
    destino.mkdir(parents=True)
    preparar_destino(destino)
    antes = instantanea(escenario.raiz)

    assert clasificar_destino(escenario.raiz, SHA, SHA_ARBOL)[0] == DESTINO_INCOMPATIBLE
    with pytest.raises(ErrorBootstrap, match="inspección administrativa"):
        preparar_escenario(escenario, EjecutorEspia())
    assert instantanea(escenario.raiz) == antes


def test_destino_enlace_simbolico_es_incompatible(escenario: Escenario) -> None:
    os.symlink(SHA_OTRO, escenario.raiz / "releases" / SHA)
    assert clasificar_destino(escenario.raiz, SHA, SHA_ARBOL)[0] == DESTINO_INCOMPATIBLE


def test_release_ya_preparada_compatible_es_idempotente(escenario: Escenario) -> None:
    preparar_escenario(escenario, EjecutorEspia())
    antes = instantanea(escenario.raiz)
    espia = EjecutorEspia()

    informe = preparar_escenario(escenario, espia)

    assert informe["resultado"] == "IDEMPOTENTE"
    assert espia.llamadas == []
    assert instantanea(escenario.raiz) == antes
    assert list(escenario.temporales.iterdir()) == []


def test_clasificacion_del_destino(escenario: Escenario) -> None:
    assert clasificar_destino(escenario.raiz, SHA, SHA_ARBOL)[0] == DESTINO_AUSENTE
    (escenario.raiz / "releases" / SHA).mkdir()
    assert clasificar_destino(escenario.raiz, SHA, SHA_ARBOL)[0] == DESTINO_PARCIAL


def test_falla_de_la_herramienta_moderna_preserva_diagnostico_y_parcial(
    escenario: Escenario,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paquete = construir_paquete_valido(
        tmp_path / "fallida", {"deploy/herramienta_despliegue.py": HERRAMIENTA_FALLIDA}
    )
    cliente = publicar(paquete.read_bytes())
    antes = instantanea(escenario.raiz)
    monkeypatch.setattr(bootstrap, "ClienteHttpPublicoReal", lambda: cliente)

    codigo = bootstrap.main(
        [
            "preparar",
            "--sha",
            SHA,
            "--tree-sha",
            SHA_ARBOL,
            "--raiz",
            str(escenario.raiz),
            "--directorio-temporal",
            str(escenario.temporales),
        ]
    )

    salida = capsys.readouterr()
    assert codigo == 1
    assert "Error: uv sync falló" in salida.err
    assert "diagnostico en stdout" in salida.err
    assert "código 1" in salida.err
    despues = instantanea(escenario.raiz)
    assert despues[f"releases/{SHA}"][0] == "dir"  # parcial conservado para inspección
    assert {k: v for k, v in despues.items() if k != f"releases/{SHA}"} == antes
    assert list(escenario.temporales.iterdir()) == []
    assert clasificar_destino(escenario.raiz, SHA, SHA_ARBOL)[0] == DESTINO_PARCIAL


def test_herramienta_exitosa_que_no_deja_release_preparada_es_error(
    escenario: Escenario,
) -> None:
    with pytest.raises(ErrorBootstrap, match="no quedó preparado"):
        preparar_escenario(escenario, EjecutorEspia(real=False))


# ---------------------------------------------------------------------------
# Caso 13 - sin Authorization, Cookie ni token
# ---------------------------------------------------------------------------


def test_la_solicitud_no_lleva_credenciales(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "token-que-no-debe-viajar")
    monkeypatch.setenv("GH_TOKEN", "token-que-no-debe-viajar")
    solicitud = ClienteHttpPublicoReal.construir_solicitud(
        f"https://api.github.com/repos/{REPOSITORIO}/releases/tags/x"
    )
    cabeceras = {clave.lower(): valor for clave, valor in solicitud.header_items()}

    assert set(cabeceras) == {"accept", "user-agent", "x-github-api-version"}
    assert all("token" not in valor for valor in cabeceras.values())


def test_el_cliente_no_instala_cookies_autenticacion_ni_proxies() -> None:
    cliente = ClienteHttpPublicoReal()
    manejadores = cliente.abridor.handlers  # type: ignore[attr-defined]
    for manejador in manejadores:  # pyright: ignore[reportUnknownVariableType]
        assert not isinstance(
            manejador,
            (
                urllib.request.HTTPCookieProcessor,
                urllib.request.HTTPBasicAuthHandler,
                urllib.request.ProxyBasicAuthHandler,
            ),
        )
        if isinstance(manejador, urllib.request.ProxyHandler):
            assert manejador.proxies == {}  # type: ignore[attr-defined]


def test_el_bootstrap_no_usa_git_gh_ni_tokens() -> None:
    fuente = Path(bootstrap.__file__).read_text(encoding="utf-8")
    constantes = {
        nodo.value
        for nodo in ast.walk(ast.parse(fuente))
        if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str)
    }
    for prohibida in ("git", "gh", "Authorization", "Cookie", "GITHUB_TOKEN", "GH_TOKEN"):
        assert prohibida not in constantes
    assert "os.environ" not in fuente


def test_redireccion_a_http_o_a_host_no_declarado_se_rechaza() -> None:
    manejador = bootstrap.RedireccionSoloHttps()
    solicitud = ClienteHttpPublicoReal.construir_solicitud("https://github.com/x")
    for destino in ("http://github.com/x", "https://ejemplo.invalido/x"):
        with pytest.raises(ErrorBootstrap):
            manejador.redirect_request(solicitud, io.BytesIO(), 302, "Found", {}, destino)


# ---------------------------------------------------------------------------
# Caso 14 - temporales limpiados ante falla de transporte o validación
# ---------------------------------------------------------------------------


def test_falla_de_transporte_limpia_el_temporal(escenario: Escenario) -> None:
    escenario.cliente.errores_descarga[bootstrap.nombre_paquete(SHA)] = ErrorBootstrap(
        "conexión interrumpida"
    )
    exigir_rechazo_sin_ejecutar(escenario, "conexión interrumpida")


def test_asset_incompleto_limpia_el_temporal(escenario: Escenario) -> None:
    escenario.cliente.release["assets"][0]["size"] += 10
    exigir_rechazo_sin_ejecutar(escenario, "incompleto")


def test_el_temporal_se_crea_privado_y_fuera_de_la_raiz(escenario: Escenario) -> None:
    temporal = bootstrap.crear_temporal_privado(escenario.temporales, escenario.raiz)
    try:
        assert temporal.stat().st_mode & 0o777 == 0o700
    finally:
        temporal.rmdir()
    with pytest.raises(ErrorBootstrap, match="dentro de"):
        bootstrap.crear_temporal_privado(escenario.raiz / "releases", escenario.raiz)


# ---------------------------------------------------------------------------
# Diagnóstico / readiness sin escritura
# ---------------------------------------------------------------------------


def test_diagnostico_verifica_todo_sin_escribir_bajo_la_raiz(escenario: Escenario) -> None:
    antes = instantanea(escenario.raiz)

    informe = bootstrap.diagnosticar(
        sha=SHA,
        tree_sha=SHA_ARBOL,
        raiz=escenario.raiz,
        directorio_temporal=escenario.temporales,
        cliente=escenario.cliente,
        buscar_ejecutable=lambda _: UV_DISPONIBLE,
    )

    assert informe["listo_para_preparar"] is True
    assert informe["estado_destino"] == DESTINO_AUSENTE
    assert informe["modulos_delegados_verificados"] == list(MODULOS_DELEGADOS)
    assert instantanea(escenario.raiz) == antes
    assert list(escenario.temporales.iterdir()) == []


CASOS_HOST_NO_LISTO: list[tuple[Callable[[Path], object], str | None]] = [
    (lambda raiz: None, None),
    (lambda raiz: (raiz / "releases" / SHA).mkdir(), UV_DISPONIBLE),
]


@pytest.mark.parametrize(("ajustar", "uv"), CASOS_HOST_NO_LISTO)
def test_diagnostico_informa_host_no_listo(
    escenario: Escenario, ajustar: Callable[[Path], object], uv: str | None
) -> None:
    ajustar(escenario.raiz)
    informe = bootstrap.diagnosticar(
        sha=SHA,
        tree_sha=SHA_ARBOL,
        raiz=escenario.raiz,
        directorio_temporal=escenario.temporales,
        cliente=escenario.cliente,
        buscar_ejecutable=lambda _: uv,
    )
    assert informe["listo_para_preparar"] is False


def test_diagnostico_con_release_invalida_falla_y_limpia(escenario: Escenario) -> None:
    escenario.cliente.run["conclusion"] = "failure"
    with pytest.raises(ErrorBootstrap):
        bootstrap.diagnosticar(
            sha=SHA,
            tree_sha=SHA_ARBOL,
            raiz=escenario.raiz,
            directorio_temporal=escenario.temporales,
            cliente=escenario.cliente,
        )
    assert list(escenario.temporales.iterdir()) == []


def test_main_diagnosticar_devuelve_1_si_el_host_no_esta_listo(
    escenario: Escenario, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(bootstrap, "ClienteHttpPublicoReal", lambda: escenario.cliente)
    sin_uv = escenario.temporales.parent / "path-sin-uv"
    sin_uv.mkdir()
    monkeypatch.setenv("PATH", str(sin_uv))
    argumentos = ["diagnosticar", "--sha", SHA, "--tree-sha", SHA_ARBOL]
    argumentos += [
        "--raiz",
        str(escenario.raiz),
        "--directorio-temporal",
        str(escenario.temporales),
    ]

    codigo = bootstrap.main(argumentos)

    informe = json.loads(capsys.readouterr().out)
    assert informe["release_sha"] == SHA
    assert informe["uv"] is None
    assert informe["listo_para_preparar"] is False
    assert codigo == 1


# ---------------------------------------------------------------------------
# Autonomía del archivo suelto y Python 3.14
# ---------------------------------------------------------------------------


def test_se_ejecuta_como_archivo_suelto_sin_el_repositorio(tmp_path: Path) -> None:
    suelto = tmp_path / "descargas" / "bootstrap_publico.py"
    suelto.parent.mkdir()
    shutil.copyfile(bootstrap.__file__, suelto)

    proceso = subprocess.run(
        [sys.executable, "-I", str(suelto), "diagnosticar", "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proceso.returncode == 0, proceso.stderr
    assert "--tree-sha" in proceso.stdout


def test_solo_importa_biblioteca_estandar() -> None:
    arbol = ast.parse(Path(bootstrap.__file__).read_text(encoding="utf-8"))
    modulos: set[str] = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            modulos.update(alias.name.split(".")[0] for alias in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.module is not None:
            modulos.add(nodo.module.split(".")[0])
    assert modulos <= set(sys.stdlib_module_names) | {"__future__"}


def test_exige_python_314() -> None:
    bootstrap.exigir_python_compatible((3, 14))
    with pytest.raises(ErrorBootstrap, match="3.14"):
        bootstrap.exigir_python_compatible((3, 12))


def test_raiz_inexistente_se_rechaza_sin_crearla(tmp_path: Path) -> None:
    ausente = tmp_path / "no-existe"
    with pytest.raises(ErrorBootstrap, match="directorio existente"):
        bootstrap.preparar(sha=SHA, tree_sha=SHA_ARBOL, raiz=ausente)
    assert not ausente.exists()


# ---------------------------------------------------------------------------
# Caso 15 - sin regresión del canal público normal: paridad de contratos
# ---------------------------------------------------------------------------


def test_contrato_del_canal_coincide_con_el_actualizador_publico() -> None:
    assert bootstrap.REPOSITORIO == actualizador.REPOSITORIO_PREDETERMINADO
    assert bootstrap.RAMA_PUBLICACION == actualizador.RAMA_PUBLICACION
    assert bootstrap.NOMBRE_WORKFLOW_CI == actualizador.NOMBRE_WORKFLOW_CI
    assert bootstrap.NOMBRE_JOB_EMPAQUETADO == actualizador.NOMBRE_JOB_EMPAQUETADO
    assert bootstrap.EVENTO_PUBLICABLE == actualizador.EVENTO_PUBLICABLE
    assert bootstrap.PREFIJO_TAG == actualizador.PREFIJO_TAG
    assert bootstrap.FORMATO_METADATOS == actualizador.FORMATO_METADATOS
    assert bootstrap.VERSION_METADATOS == actualizador.VERSION_METADATOS
    assert bootstrap.HOST_API == actualizador.HOST_API
    assert bootstrap.HOSTS_DESCARGA_PERMITIDOS == actualizador.HOSTS_DESCARGA_PERMITIDOS
    assert bootstrap.MAXIMO_BYTES_METADATOS == actualizador.MAXIMO_BYTES_METADATOS
    assert bootstrap.MAXIMO_BYTES_SIDECAR == actualizador.MAXIMO_BYTES_SIDECAR
    assert bootstrap.assets_esperados(SHA) == actualizador.assets_esperados(SHA)
    assert bootstrap.tag_publicacion(SHA) == actualizador.tag_publicacion(SHA)


def test_contrato_del_paquete_coincide_con_la_herramienta_moderna() -> None:
    assert bootstrap.MARCADOR_PREPARADA == herramienta.MARCADOR_PREPARADA
    assert bootstrap.MAXIMO_ARCHIVOS_TAR == herramienta.MAXIMO_ARCHIVOS_TAR
    assert bootstrap.MAXIMO_BYTES_TAR == herramienta.MAXIMO_BYTES_TAR
    assert bootstrap.MAXIMO_LONGITUD_RUTA == herramienta.MAXIMO_LONGITUD_RUTA
    assert bootstrap.RUTA_CONTRATO_CONFIGURACION == RUTA_CONTRATO_EN_RELEASE


def test_los_modulos_delegados_cubren_los_imports_reales_de_la_herramienta() -> None:
    """Si la herramienta moderna importara otro módulo propio, esta prueba lo detecta."""

    pendientes = ["deploy/herramienta_despliegue.py"]
    alcanzados: set[str] = set()
    while pendientes:
        relativa = pendientes.pop()
        if relativa in alcanzados:
            continue
        alcanzados.add(relativa)
        arbol = ast.parse((RAIZ_REPOSITORIO / relativa).read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            nombres: list[str] = []
            if isinstance(nodo, ast.ImportFrom) and nodo.module is not None:
                nombres.append(nodo.module)
            elif isinstance(nodo, ast.Import):
                nombres.extend(alias.name for alias in nodo.names)
            for nombre in nombres:
                if nombre.split(".")[0] == "deploy":
                    pendientes.append(nombre.replace(".", "/") + ".py")
                else:
                    assert nombre.split(".")[0] in sys.stdlib_module_names or nombre == (
                        "__future__"
                    ), nombre
    assert alcanzados | {"deploy/__init__.py"} == set(MODULOS_DELEGADOS)
    for modulo in MODULOS_DELEGADOS:
        assert (RAIZ_REPOSITORIO / modulo).is_file()
