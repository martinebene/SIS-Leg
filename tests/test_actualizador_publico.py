"""Pruebas del canal público de releases y del contrato de configuración (WP-100).

Cubren el contrato completo del WP en dos frentes:

- **canal público**: publicación sólo tras CI completa verde, identidad exacta
  SHA/tag/assets, idempotencia, rechazo de colisión divergente, selección
  determinista de run y job, descarga sin credenciales, checksum, manifest y
  todos los modos de falla de red;
- **configuración local**: preservación byte a byte, incorporación add-only de
  un recurso ausente, no sobrescritura de uno existente y aborto ante cambio de
  schema antes de mutar nada.

Ninguna prueba toca la red, el host productivo ni GitHub: las fronteras HTTP y
de filesystem se inyectan. El publicador y el consumidor se ejercitan encadenados
—lo que publica uno es exactamente lo que consume el otro— para que un cambio en
el formato de los metadatos rompa acá y no en producción.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

import deploy.actualizador_publico as modulo_publico
from deploy.actualizador_publico import (
    NOMBRE_JOB_EMPAQUETADO,
    NOMBRE_WORKFLOW_CI,
    ClienteHttpPublicoReal,
    ErrorActualizadorPublico,
    assets_esperados,
    nombre_metadatos,
    nombre_paquete,
    nombre_sidecar,
    obtener_release_publica,
    resolver_publicacion,
    resolver_sha_main,
    seleccionar_run_ci,
    tag_publicacion,
    validar_url_publica,
    verificar_job_empaquetado,
)
from deploy.configuracion_local import (
    ACCION_CREAR,
    ACCION_MIGRACION_REQUERIDA,
    ACCION_PRESERVAR,
    RUTA_CONTRATO_EN_RELEASE,
    ErrorConfiguracionLocal,
    aplicar_plan_configuracion,
    leer_contrato_de_release,
    planificar_configuracion,
)
from deploy.herramienta_despliegue import (
    ErrorDespliegue,
    inspeccionar_manifest_paquete,
    validar_manifest,
)
from scripts.empaquetar_produccion import construir_paquete
from scripts.publicar_release_publica import ErrorPublicacion, publicar_release

SHA = "a" * 40
SHA_ARBOL = "c" * 40
SHA_OTRO = "b" * 40
REPOSITORIO = "martinebene/SIS-Leg"
RAIZ_REPOSITORIO = Path(__file__).resolve().parents[1]
RUN_ID = 4242
RUN_NUMERO = 17
JOB_ID = 990099


# ---------------------------------------------------------------------------
# Construcción de un paquete productivo real
# ---------------------------------------------------------------------------


def crear_checkout_minimo(raiz: Path) -> None:
    """Materializa la allowlist mínima que consume el empaquetador canónico.

    Se construye acá y no se importa del otro archivo de pruebas porque pytest
    carga cada módulo de test por separado: importar entre módulos de prueba los
    registraría dos veces. El contenido es de fantasía salvo el contrato de
    configuración, que se copia del repositorio real.
    """

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
        "deploy/herramienta_despliegue.py": "# herramienta",
        "deploy/validar_configuracion.py": "# validador",
        "deploy/configuracion_local.py": "# contrato",
        "deploy/actualizador_publico.py": "# canal publico",
        "deploy/systemd/sis-leg-backend.service": "[Service]\n",
        "deploy/systemd/sis-leg-device-bridge.service": "[Service]\n",
        "deploy/nginx/sis-leg.conf": "server {}\n",
    }
    for relativa, contenido in archivos.items():
        ruta = raiz / relativa
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(contenido, encoding="utf-8")

    contrato = raiz / RUTA_CONTRATO_EN_RELEASE
    contrato.parent.mkdir(parents=True, exist_ok=True)
    contrato.write_text(
        (RAIZ_REPOSITORIO / RUTA_CONTRATO_EN_RELEASE).read_text(encoding="utf-8"),
        encoding="utf-8",
    )


def construir_artefactos(tmp_path: Path, sha: str = SHA) -> tuple[Path, Path]:
    """Genera paquete y sidecar reales para el SHA indicado."""

    checkout = tmp_path / f"checkout-{sha[:6]}"
    crear_checkout_minimo(checkout)
    return construir_paquete(
        raiz=checkout,
        directorio_salida=tmp_path / f"artefactos-{sha[:6]}",
        sha_commit=sha,
        sha_arbol=SHA_ARBOL,
    )


# ---------------------------------------------------------------------------
# Dobles de las dos fronteras HTTP
# ---------------------------------------------------------------------------


def run_exitosa(sha: str = SHA, **cambios: Any) -> dict[str, Any]:
    """Devuelve la run de CI canónica que habilita una publicación."""

    run: dict[str, Any] = {
        "id": RUN_ID,
        "run_number": RUN_NUMERO,
        "run_attempt": 1,
        "name": NOMBRE_WORKFLOW_CI,
        "event": "push",
        "head_branch": "main",
        "head_sha": sha,
        "status": "completed",
        "conclusion": "success",
    }
    run.update(cambios)
    return run


def jobs_exitosos(sha: str = SHA, **cambios: Any) -> dict[str, Any]:
    """Devuelve la lista de jobs con el de empaquetado exitoso."""

    job: dict[str, Any] = {
        "id": JOB_ID,
        "name": NOMBRE_JOB_EMPAQUETADO,
        "conclusion": "success",
        "head_sha": sha,
    }
    job.update(cambios)
    otros = [
        {"id": 1, "name": "Backend · pruebas", "conclusion": "success", "head_sha": sha},
        {"id": 2, "name": "Frontend · build estático", "conclusion": "success", "head_sha": sha},
    ]
    return {"total_count": 3, "jobs": [*otros, job]}


class ClienteApiFalso:
    """Emula el lado escritura del API de GitHub para el publicador.

    Guarda las releases creadas y los bytes de cada asset subido, de modo que la
    misma instancia sirve después como origen de datos del consumidor. Así una
    incompatibilidad entre lo que se publica y lo que se consume rompe la prueba.
    """

    def __init__(self, *, run: dict[str, Any], jobs: dict[str, Any]) -> None:
        self.run = run
        self.jobs = jobs
        self.releases: dict[str, dict[str, Any]] = {}
        self.contenidos: dict[str, bytes] = {}
        self.creaciones = 0
        self.subidas: list[str] = []

    def obtener(self, url: str) -> Any | None:
        if "/actions/runs/" in url and url.endswith("/jobs?per_page=100"):
            return self.jobs
        if "/actions/runs/" in url:
            return self.run
        if "/releases/tags/" in url:
            tag = url.rsplit("/", 1)[1]
            return self.releases.get(tag)
        raise AssertionError(f"URL no prevista en el publicador: {url}")

    def crear(self, url: str, cuerpo: Mapping[str, Any]) -> Any:
        assert url.endswith("/releases")
        tag = str(cuerpo["tag_name"])
        self.creaciones += 1
        release: dict[str, Any] = {
            "tag_name": tag,
            "target_commitish": cuerpo["target_commitish"],
            "draft": cuerpo["draft"],
            "prerelease": cuerpo["prerelease"],
            "assets": [],
            "upload_url": f"https://uploads.github.com/repos/{REPOSITORIO}/releases/1/assets"
            "{?name,label}",
        }
        self.releases[tag] = release
        return release

    def subir_asset(self, url: str, ruta: Path, tipo_contenido: str) -> Any:
        del tipo_contenido
        nombre = url.rsplit("name=", 1)[1]
        contenido = ruta.read_bytes()
        self.contenidos[nombre] = contenido
        release = next(iter(self.releases.values()))
        release["assets"].append(
            {
                "name": nombre,
                "state": "uploaded",
                "size": len(contenido),
                "browser_download_url": (f"https://objects.githubusercontent.com/sis-leg/{nombre}"),
            }
        )
        self.subidas.append(nombre)
        return {"name": nombre}

    def descargar(self, url: str, destino: Path) -> None:
        nombre = url.rsplit("/", 1)[1]
        destino.write_bytes(self.contenidos[nombre])


class ClienteHttpFalso:
    """Emula el lado lectura público del API de GitHub para el consumidor.

    El ruteo se hace por forma de la URL y no por coincidencia exacta para que
    las pruebas no dependan del orden de los parámetros de la query.
    """

    def __init__(
        self,
        *,
        sha: str = SHA,
        runs: dict[str, Any] | None = None,
        jobs: dict[str, Any] | None = None,
        release: dict[str, Any] | None = None,
        contenidos: dict[str, bytes] | None = None,
    ) -> None:
        self.sha = sha
        self.runs = (
            runs if runs is not None else {"total_count": 1, "workflow_runs": [run_exitosa(sha)]}
        )
        self.jobs = jobs if jobs is not None else jobs_exitosos(sha)
        self.release = release
        self.contenidos = contenidos or {}
        self.urls: list[str] = []
        self.errores: dict[str, Exception] = {}

    def obtener_json(
        self, url: str, *, maximo_bytes: int = modulo_publico.MAXIMO_BYTES_JSON
    ) -> Any:
        del maximo_bytes
        self.urls.append(url)
        for fragmento, error in self.errores.items():
            if fragmento in url:
                raise error
        if "/commits/" in url:
            return {"sha": self.sha}
        if "/actions/runs?" in url:
            return self.runs
        if url.endswith("/jobs?per_page=100"):
            return self.jobs
        if "/releases/tags/" in url:
            if self.release is None:
                raise ErrorActualizadorPublico("GitHub respondió HTTP 404.")
            return self.release
        raise AssertionError(f"URL no prevista en el consumidor: {url}")

    def descargar(self, url: str, destino: Path, *, maximo_bytes: int) -> int:
        self.urls.append(url)
        for fragmento, error in self.errores.items():
            if fragmento in url:
                raise error
        contenido = self.contenidos[url.rsplit("/", 1)[1]]
        if len(contenido) > maximo_bytes:
            raise ErrorActualizadorPublico("La descarga superó el máximo aceptado.")
        destino.write_bytes(contenido)
        return len(contenido)


def publicar_para_pruebas(
    tmp_path: Path, *, sha: str = SHA
) -> tuple[ClienteApiFalso, dict[str, Any], Path]:
    """Publica una release con el publicador real y devuelve su estado.

    Resultado: el cliente falso con las releases/assets creados, el resumen de la
    publicación y el directorio de artefactos locales.
    """

    paquete, _ = construir_artefactos(tmp_path, sha)
    directorio = paquete.parent
    cliente = ClienteApiFalso(run=run_exitosa(sha), jobs=jobs_exitosos(sha))
    resumen = publicar_release(
        cliente, repositorio=REPOSITORIO, sha=sha, run_id=RUN_ID, directorio=directorio
    )
    return cliente, resumen, directorio


def consumidor_desde_publicacion(
    publicador: ClienteApiFalso, *, sha: str = SHA
) -> ClienteHttpFalso:
    """Arma el cliente público del consumidor con lo que el publicador dejó."""

    return ClienteHttpFalso(
        sha=sha,
        release=publicador.releases[tag_publicacion(sha)],
        contenidos=dict(publicador.contenidos),
    )


# ---------------------------------------------------------------------------
# 1. Publicación sólo para push main con CI completa verde
# ---------------------------------------------------------------------------


def test_publicacion_exige_push_main_ci_completa_y_job_exacto(tmp_path: Path) -> None:
    """El camino feliz publica tag, paquete, sidecar y metadatos del mismo SHA."""

    publicador, resumen, _ = publicar_para_pruebas(tmp_path)

    assert resumen == {
        "tag": tag_publicacion(SHA),
        "estado": "creada",
        "commit_sha": SHA,
        "tree_sha": SHA_ARBOL,
        "ci_run_id": RUN_ID,
    }
    assert sorted(publicador.subidas) == sorted(assets_esperados(SHA))
    release = publicador.releases[tag_publicacion(SHA)]
    assert release["target_commitish"] == SHA
    assert release["draft"] is False and release["prerelease"] is False


@pytest.mark.parametrize(
    ("cambio", "mensaje"),
    [
        ({"event": "pull_request"}, "evento push"),
        ({"head_branch": "wp/100"}, "no corresponde a main"),
        ({"conclusion": "failure"}, "no terminó en success"),
        ({"status": "in_progress"}, "todavía no terminó"),
        ({"head_sha": SHA_OTRO}, "no corresponde al SHA"),
        ({"name": "Otro workflow"}, "no pertenece al workflow"),
    ],
    ids=["pull-request", "otra-rama", "ci-fallida", "ci-en-curso", "otro-sha", "otro-workflow"],
)
def test_publicacion_rechaza_runs_no_habilitantes(
    tmp_path: Path, cambio: dict[str, Any], mensaje: str
) -> None:
    """Ninguna run que no sea la CI completa verde de push a main publica nada."""

    paquete, _ = construir_artefactos(tmp_path)
    cliente = ClienteApiFalso(run=run_exitosa(**cambio), jobs=jobs_exitosos())

    with pytest.raises(ErrorPublicacion, match=mensaje):
        publicar_release(
            cliente,
            repositorio=REPOSITORIO,
            sha=SHA,
            run_id=RUN_ID,
            directorio=paquete.parent,
        )
    assert cliente.releases == {}


def test_publicacion_rechaza_job_de_empaquetado_fallido(tmp_path: Path) -> None:
    """Una CI verde con el job de empaquetado no exitoso no puede publicarse."""

    paquete, _ = construir_artefactos(tmp_path)
    cliente = ClienteApiFalso(run=run_exitosa(), jobs=jobs_exitosos(**{"conclusion": "failure"}))

    with pytest.raises(ErrorPublicacion, match="no terminó en success"):
        publicar_release(
            cliente, repositorio=REPOSITORIO, sha=SHA, run_id=RUN_ID, directorio=paquete.parent
        )
    assert cliente.releases == {}


def test_publicacion_rechaza_job_de_otro_sha(tmp_path: Path) -> None:
    """El job debe pertenecer al mismo head_sha; no se mezclan dos SHAs."""

    paquete, _ = construir_artefactos(tmp_path)
    cliente = ClienteApiFalso(run=run_exitosa(), jobs=jobs_exitosos(**{"head_sha": SHA_OTRO}))

    with pytest.raises(ErrorPublicacion, match="no corresponde al SHA"):
        publicar_release(
            cliente, repositorio=REPOSITORIO, sha=SHA, run_id=RUN_ID, directorio=paquete.parent
        )


def test_publicacion_rechaza_jobs_paginados(tmp_path: Path) -> None:
    """Si la respuesta vino paginada no se puede demostrar unicidad y se aborta."""

    paquete, _ = construir_artefactos(tmp_path)
    jobs = jobs_exitosos()
    jobs["total_count"] = 99
    cliente = ClienteApiFalso(run=run_exitosa(), jobs=jobs)

    with pytest.raises(ErrorPublicacion, match="paginado"):
        publicar_release(
            cliente, repositorio=REPOSITORIO, sha=SHA, run_id=RUN_ID, directorio=paquete.parent
        )


# ---------------------------------------------------------------------------
# 3. Idempotencia y colisión divergente
# ---------------------------------------------------------------------------


def test_republicar_los_mismos_bytes_es_idempotente(tmp_path: Path) -> None:
    """Reintentar la publicación del mismo SHA no crea ni reemplaza nada."""

    publicador, _, directorio = publicar_para_pruebas(tmp_path)
    creaciones = publicador.creaciones
    subidas = list(publicador.subidas)

    segundo = publicar_release(
        publicador, repositorio=REPOSITORIO, sha=SHA, run_id=RUN_ID, directorio=directorio
    )

    assert segundo["estado"] == "idempotente"
    assert publicador.creaciones == creaciones
    assert publicador.subidas == subidas


def test_colision_con_bytes_distintos_aborta_sin_reemplazar(tmp_path: Path) -> None:
    """Una publicación existente es inmutable: divergir aborta la operación."""

    publicador, _, directorio = publicar_para_pruebas(tmp_path)
    # Se altera el contenido ya publicado para simular una release previa que no
    # coincide con el artefacto local recién construido.
    publicador.contenidos[nombre_paquete(SHA)] = b"otros bytes"

    with pytest.raises(ErrorPublicacion, match="difiere byte a byte"):
        publicar_release(
            publicador, repositorio=REPOSITORIO, sha=SHA, run_id=RUN_ID, directorio=directorio
        )
    assert publicador.creaciones == 1


def test_publicacion_existente_incompleta_aborta(tmp_path: Path) -> None:
    """Faltar un asset en la release existente exige intervención humana."""

    publicador, _, directorio = publicar_para_pruebas(tmp_path)
    release = publicador.releases[tag_publicacion(SHA)]
    release["assets"] = [
        asset for asset in release["assets"] if asset["name"] != nombre_sidecar(SHA)
    ]

    with pytest.raises(ErrorPublicacion, match="conjunto de assets distinto"):
        publicar_release(
            publicador, repositorio=REPOSITORIO, sha=SHA, run_id=RUN_ID, directorio=directorio
        )


def test_publicacion_rechaza_paquete_ambiguo_en_el_directorio(tmp_path: Path) -> None:
    """Dos paquetes con el mismo nombre bajo el directorio impiden elegir."""

    paquete, sidecar = construir_artefactos(tmp_path)
    duplicado = paquete.parent / "copia" / paquete.name
    duplicado.parent.mkdir()
    duplicado.write_bytes(paquete.read_bytes())
    (duplicado.parent / sidecar.name).write_bytes(sidecar.read_bytes())
    cliente = ClienteApiFalso(run=run_exitosa(), jobs=jobs_exitosos())

    with pytest.raises(ErrorPublicacion, match="exactamente un"):
        publicar_release(
            cliente, repositorio=REPOSITORIO, sha=SHA, run_id=RUN_ID, directorio=paquete.parent
        )


# ---------------------------------------------------------------------------
# 4 y 17. Consumo público sin credenciales
# ---------------------------------------------------------------------------


def test_la_solicitud_publica_no_lleva_ninguna_credencial() -> None:
    """La solicitud real no envía Authorization, Cookie ni token alguno."""

    solicitud = ClienteHttpPublicoReal.construir_solicitud(
        "https://api.github.com/repos/martinebene/SIS-Leg/commits/main"
    )

    claves = {clave.lower() for clave in solicitud.headers}
    assert "authorization" not in claves
    assert "cookie" not in claves
    assert claves == {"Accept".lower(), "User-agent".lower(), "X-github-api-version".lower()}


def test_el_consumidor_no_menciona_gh_pat_ni_tokens() -> None:
    """El módulo del host no puede depender de gh, PAT ni archivos de token."""

    fuente = (RAIZ_REPOSITORIO / "deploy/actualizador_publico.py").read_text(encoding="utf-8")

    # Se buscan las formas concretas en que una credencial entraría al proceso:
    # una variable de entorno, un archivo de token, el CLI `gh`, el keyring del
    # sistema o un `.netrc`. La ausencia de cabecera `Authorization` la demuestra
    # `test_la_solicitud_publica_no_lleva_ninguna_credencial` inspeccionando la
    # solicitud real, que es evidencia más fuerte que una búsqueda textual.
    for prohibido in ("GITHUB_TOKEN", ".github_token", "gh auth", "subprocess", "keyring", "netrc"):
        assert prohibido not in fuente, f"El consumidor no debe depender de {prohibido}."


def test_resolver_sha_main_usa_recurso_publico(tmp_path: Path) -> None:
    """El SHA sale del commit público de la rama, no de un asset ``latest``."""

    del tmp_path
    cliente = ClienteHttpFalso()

    assert resolver_sha_main(cliente, repositorio=REPOSITORIO) == SHA
    assert cliente.urls == [f"https://api.github.com/repos/{REPOSITORIO}/commits/main"]


def test_solo_se_acepta_https_y_hosts_declarados() -> None:
    """Ni HTTP ni un host ajeno son aceptables para el canal público."""

    with pytest.raises(ErrorActualizadorPublico, match="Sólo se acepta https"):
        validar_url_publica("http://api.github.com/x", hosts_permitidos=("api.github.com",))
    with pytest.raises(ErrorActualizadorPublico, match="Host no permitido"):
        validar_url_publica("https://ejemplo.invalido/x", hosts_permitidos=("api.github.com",))


def test_la_redireccion_a_http_se_rechaza() -> None:
    """Un 302 hacia http no puede degradar silenciosamente la descarga."""

    manejador = modulo_publico.RedireccionSoloHttps()
    solicitud = urllib.request.Request("https://api.github.com/x")

    with pytest.raises(ErrorActualizadorPublico, match="Sólo se acepta https"):
        manejador.redirect_request(
            solicitud, None, 302, "Found", {}, "http://objects.githubusercontent.com/y"
        )


# ---------------------------------------------------------------------------
# 5. Selección determinista de run y job
# ---------------------------------------------------------------------------


def test_se_elige_la_run_mas_reciente_de_forma_determinista() -> None:
    """Con dos runs válidas gana la de mayor número, siempre la misma."""

    runs = {
        "total_count": 2,
        "workflow_runs": [
            run_exitosa(id=1, run_number=5),
            run_exitosa(id=2, run_number=9),
        ],
    }
    cliente = ClienteHttpFalso(runs=runs)

    elegida = seleccionar_run_ci(cliente, SHA, repositorio=REPOSITORIO)

    assert (elegida.identificador, elegida.numero) == (2, 9)


@pytest.mark.parametrize(
    "cambio",
    [
        {"event": "pull_request"},
        {"head_branch": "wp/100"},
        {"conclusion": "failure"},
        {"head_sha": SHA_OTRO},
        {"name": "Otro workflow"},
    ],
    ids=["pull-request", "otra-rama", "fallida", "otro-sha", "otro-workflow"],
)
def test_no_se_acepta_una_run_de_otro_origen(cambio: dict[str, Any]) -> None:
    """Una run de otro evento, rama, SHA o workflow no habilita la descarga."""

    cliente = ClienteHttpFalso(runs={"total_count": 1, "workflow_runs": [run_exitosa(**cambio)]})

    with pytest.raises(ErrorActualizadorPublico, match="No hay una run de CI"):
        seleccionar_run_ci(cliente, SHA, repositorio=REPOSITORIO)


def test_runs_paginadas_abortan_en_lugar_de_elegir_a_ciegas() -> None:
    """Si no se vio el conjunto completo no se puede demostrar la elección."""

    cliente = ClienteHttpFalso(runs={"total_count": 50, "workflow_runs": [run_exitosa()]})

    with pytest.raises(ErrorActualizadorPublico, match="elección"):
        seleccionar_run_ci(cliente, SHA, repositorio=REPOSITORIO)


def test_el_job_de_empaquetado_debe_existir_una_sola_vez() -> None:
    """Dos jobs con el nombre exacto impiden demostrar cuál validó el paquete."""

    jobs = jobs_exitosos()
    jobs["jobs"].append(dict(jobs["jobs"][-1]))
    jobs["total_count"] = 4
    cliente = ClienteHttpFalso(jobs=jobs)
    run = seleccionar_run_ci(cliente, SHA, repositorio=REPOSITORIO)

    with pytest.raises(ErrorActualizadorPublico, match="exactamente un job"):
        verificar_job_empaquetado(cliente, run, repositorio=REPOSITORIO)


def test_el_job_de_otro_sha_se_rechaza() -> None:
    """No se combinan datos de runs o jobs pertenecientes a SHAs distintos."""

    cliente = ClienteHttpFalso(jobs=jobs_exitosos(**{"head_sha": SHA_OTRO}))
    run = seleccionar_run_ci(cliente, SHA, repositorio=REPOSITORIO)

    with pytest.raises(ErrorActualizadorPublico, match="no se mezclan SHAs"):
        verificar_job_empaquetado(cliente, run, repositorio=REPOSITORIO)


# ---------------------------------------------------------------------------
# 2 y 9. Identidad exacta de la publicación y de sus assets
# ---------------------------------------------------------------------------


def test_la_publicacion_resuelta_declara_los_tres_assets_exactos(tmp_path: Path) -> None:
    """El tag y los tres nombres derivan del SHA, sin ningún ``latest``."""

    publicador, _, _ = publicar_para_pruebas(tmp_path)
    cliente = consumidor_desde_publicacion(publicador)

    publicacion = resolver_publicacion(cliente, SHA, repositorio=REPOSITORIO)

    assert publicacion.tag == f"sis-leg-{SHA}"
    assert set(publicacion.assets) == set(assets_esperados(SHA))


@pytest.mark.parametrize(
    ("mutacion", "mensaje"),
    [
        ("ausente", "no expone los assets"),
        ("duplicado", "duplica el asset"),
        ("inesperado", "asset inesperado"),
        ("incompleto", "no está completamente subido"),
    ],
    ids=["ausente", "duplicado", "nombre-inesperado", "subida-incompleta"],
)
def test_publicacion_con_assets_invalidos_se_rechaza(
    tmp_path: Path, mutacion: str, mensaje: str
) -> None:
    """Falta, sobra, se repite o está a medio subir: la publicación no sirve."""

    publicador, _, _ = publicar_para_pruebas(tmp_path)
    release = dict(publicador.releases[tag_publicacion(SHA)])
    assets = [dict(asset) for asset in release["assets"]]
    if mutacion == "ausente":
        assets = [asset for asset in assets if asset["name"] != nombre_sidecar(SHA)]
    elif mutacion == "duplicado":
        assets.append(dict(assets[0]))
    elif mutacion == "inesperado":
        assets.append({**assets[0], "name": "sis-leg-latest.tar.gz"})
    else:
        assets[0] = {**assets[0], "state": "starter"}
    release["assets"] = assets
    cliente = ClienteHttpFalso(release=release, contenidos=dict(publicador.contenidos))

    with pytest.raises(ErrorActualizadorPublico, match=mensaje):
        resolver_publicacion(cliente, SHA, repositorio=REPOSITORIO)


@pytest.mark.parametrize(
    ("campo", "valor", "mensaje"),
    [
        ("draft", True, "borrador o prerelease"),
        ("prerelease", True, "borrador o prerelease"),
        ("target_commitish", SHA_OTRO, "no apunta al commit"),
        ("tag_name", "sis-leg-otro", "tag distinto"),
    ],
    ids=["borrador", "prerelease", "otro-commit", "otro-tag"],
)
def test_publicacion_con_identidad_incorrecta_se_rechaza(
    tmp_path: Path, campo: str, valor: Any, mensaje: str
) -> None:
    """La publicación debe estar atada al commit y al tag exactos."""

    publicador, _, _ = publicar_para_pruebas(tmp_path)
    release = dict(publicador.releases[tag_publicacion(SHA)])
    release[campo] = valor
    cliente = ClienteHttpFalso(release=release, contenidos=dict(publicador.contenidos))

    with pytest.raises(ErrorActualizadorPublico, match=mensaje):
        resolver_publicacion(cliente, SHA, repositorio=REPOSITORIO)


# ---------------------------------------------------------------------------
# 6, 7 y 8. Descarga, checksum y manifest
# ---------------------------------------------------------------------------


def test_descarga_publica_completa_entrega_release_verificada(tmp_path: Path) -> None:
    """Camino feliz completo: SHA, run, job, publicación, descarga y validación."""

    publicador, _, _ = publicar_para_pruebas(tmp_path)
    cliente = consumidor_desde_publicacion(publicador)
    destino = tmp_path / "descarga"

    release = obtener_release_publica(destino, cliente=cliente, repositorio=REPOSITORIO)

    assert release.commit_sha == SHA
    assert release.tree_sha == SHA_ARBOL
    assert release.tag == tag_publicacion(SHA)
    assert release.paquete == destino / nombre_paquete(SHA)
    assert release.sidecar == destino / nombre_sidecar(SHA)
    assert release.metadatos == destino / nombre_metadatos(SHA)
    assert release.run_ci.identificador == RUN_ID
    assert release.job_ci.identificador == JOB_ID
    # No queda ningún temporal de descarga en el destino.
    assert sorted(ruta.name for ruta in destino.iterdir()) == sorted(assets_esperados(SHA))


def test_checksum_incorrecto_aborta_y_no_deja_artefactos(tmp_path: Path) -> None:
    """Un sidecar que no corresponde impide entregar el paquete."""

    publicador, _, _ = publicar_para_pruebas(tmp_path)
    contenidos = dict(publicador.contenidos)
    contenidos[nombre_sidecar(SHA)] = f"{'0' * 64}  {nombre_paquete(SHA)}\n".encode("ascii")
    release = dict(publicador.releases[tag_publicacion(SHA)])
    release["assets"] = [
        {**asset, "size": len(contenidos[asset["name"]])} for asset in release["assets"]
    ]
    cliente = ClienteHttpFalso(release=release, contenidos=contenidos)
    destino = tmp_path / "descarga"

    with pytest.raises(ErrorDespliegue, match="Checksum incorrecto"):
        obtener_release_publica(destino, cliente=cliente, repositorio=REPOSITORIO)
    assert list(destino.iterdir()) == []


def test_paquete_truncado_falla_en_la_validacion_canonica(tmp_path: Path) -> None:
    """Un tar cortado no llega a preparar: lo rechaza el motor canónico."""

    publicador, _, _ = publicar_para_pruebas(tmp_path)
    contenidos = dict(publicador.contenidos)
    truncado = contenidos[nombre_paquete(SHA)][: len(contenidos[nombre_paquete(SHA)]) // 2]
    contenidos[nombre_paquete(SHA)] = truncado
    # Sidecar y metadatos se recalculan para que la falla sea la del tar abierto
    # por el motor canónico y no la de un checksum que ya no corresponde.
    digest = hashlib.sha256(truncado).hexdigest()
    contenidos[nombre_sidecar(SHA)] = f"{digest}  {nombre_paquete(SHA)}\n".encode("ascii")
    metadatos = json.loads(contenidos[nombre_metadatos(SHA)].decode("utf-8"))
    metadatos["paquete"]["sha256"] = digest
    metadatos["paquete"]["tamano"] = len(truncado)
    contenidos[nombre_metadatos(SHA)] = (json.dumps(metadatos, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )
    release = dict(publicador.releases[tag_publicacion(SHA)])
    release["assets"] = [
        {**asset, "size": len(contenidos[asset["name"]])} for asset in release["assets"]
    ]
    cliente = ClienteHttpFalso(release=release, contenidos=contenidos)
    destino = tmp_path / "descarga"

    with pytest.raises(ErrorActualizadorPublico, match="validación canónica"):
        obtener_release_publica(destino, cliente=cliente, repositorio=REPOSITORIO)
    assert list(destino.iterdir()) == []


def test_manifest_de_otro_commit_es_rechazado(tmp_path: Path) -> None:
    """``release.json`` debe declarar el mismo commit que se pidió."""

    paquete, _ = construir_artefactos(tmp_path, SHA)

    with pytest.raises(ErrorDespliegue, match="no coincide con release.json"):
        inspeccionar_manifest_paquete(paquete, SHA_OTRO)


def test_metadatos_con_tree_distinto_del_manifest_se_rechazan(tmp_path: Path) -> None:
    """Metadatos y manifest deben coincidir en el árbol Git; si no, se aborta."""

    publicador, _, _ = publicar_para_pruebas(tmp_path)
    contenidos = dict(publicador.contenidos)
    metadatos = json.loads(contenidos[nombre_metadatos(SHA)].decode("utf-8"))
    metadatos["tree_sha"] = "d" * 40
    contenidos[nombre_metadatos(SHA)] = (json.dumps(metadatos, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )
    release = dict(publicador.releases[tag_publicacion(SHA)])
    release["assets"] = [
        {**asset, "size": len(contenidos[asset["name"]])} for asset in release["assets"]
    ]
    cliente = ClienteHttpFalso(release=release, contenidos=contenidos)

    with pytest.raises(ErrorActualizadorPublico, match="tree SHA del manifest"):
        obtener_release_publica(tmp_path / "descarga", cliente=cliente, repositorio=REPOSITORIO)


@pytest.mark.parametrize(
    ("campo", "valor", "mensaje"),
    [
        ("commit_sha", SHA_OTRO, "otro commit"),
        ("tag", "sis-leg-otro", "otro tag"),
        ("repositorio", "otro/repo", "otro repositorio"),
        ("formato", "inventado", "formato"),
        ("version_formato", 99, "versión de formato"),
    ],
    ids=["commit", "tag", "repositorio", "formato", "version"],
)
def test_metadatos_incoherentes_se_rechazan(
    tmp_path: Path, campo: str, valor: Any, mensaje: str
) -> None:
    """Los metadatos atan publicación, commit, árbol y CI: no se aceptan sueltos."""

    publicador, _, _ = publicar_para_pruebas(tmp_path)
    contenidos = dict(publicador.contenidos)
    metadatos = json.loads(contenidos[nombre_metadatos(SHA)].decode("utf-8"))
    metadatos[campo] = valor
    contenidos[nombre_metadatos(SHA)] = (json.dumps(metadatos, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )
    release = dict(publicador.releases[tag_publicacion(SHA)])
    release["assets"] = [
        {**asset, "size": len(contenidos[asset["name"]])} for asset in release["assets"]
    ]
    cliente = ClienteHttpFalso(release=release, contenidos=contenidos)

    with pytest.raises(ErrorActualizadorPublico, match=mensaje):
        obtener_release_publica(tmp_path / "descarga", cliente=cliente, repositorio=REPOSITORIO)


def test_asset_con_tamano_distinto_del_declarado_aborta(tmp_path: Path) -> None:
    """Una descarga incompleta respecto del tamaño declarado no se promueve."""

    publicador, _, _ = publicar_para_pruebas(tmp_path)
    release = dict(publicador.releases[tag_publicacion(SHA)])
    release["assets"] = [
        {**asset, "size": asset["size"] + 1} if asset["name"] == nombre_paquete(SHA) else asset
        for asset in release["assets"]
    ]
    cliente = ClienteHttpFalso(release=release, contenidos=dict(publicador.contenidos))

    with pytest.raises(ErrorActualizadorPublico, match="incompleto"):
        obtener_release_publica(tmp_path / "descarga", cliente=cliente, repositorio=REPOSITORIO)


# ---------------------------------------------------------------------------
# 10. Fallas de red, rate limit y JSON inválido
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fragmento", "error"),
    [
        ("/commits/", ErrorActualizadorPublico("HTTP 500")),
        ("/actions/runs?", ErrorActualizadorPublico("límite de tasa")),
        ("/jobs", ErrorActualizadorPublico("timed out")),
        ("/releases/tags/", ErrorActualizadorPublico("JSON")),
        ("objects.githubusercontent.com", ErrorActualizadorPublico("conexión interrumpida")),
    ],
    ids=["commit", "runs", "jobs", "release", "descarga"],
)
def test_cualquier_falla_de_red_es_fail_safe(
    tmp_path: Path, fragmento: str, error: Exception
) -> None:
    """Ante cualquier falla no queda nada descargado ni a medio promover."""

    publicador, _, _ = publicar_para_pruebas(tmp_path)
    cliente = consumidor_desde_publicacion(publicador)
    cliente.errores[fragmento] = error
    destino = tmp_path / "descarga"

    with pytest.raises(ErrorActualizadorPublico):
        obtener_release_publica(destino, cliente=cliente, repositorio=REPOSITORIO)
    assert not destino.exists() or list(destino.iterdir()) == []


def test_rate_limit_del_cliente_real_se_traduce_en_mensaje_accionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un 403 de la API pública se explica como límite de tasa, no como bug."""

    cliente = ClienteHttpPublicoReal()

    def fallar(*_argumentos: Any, **_nombrados: Any) -> Any:
        raise urllib.error.HTTPError("https://api.github.com/x", 403, "rate", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(cliente.abridor, "open", fallar)

    with pytest.raises(ErrorActualizadorPublico, match="límite de tasa"):
        cliente.obtener_json("https://api.github.com/repos/x/y/commits/main")


def test_json_invalido_del_cliente_real_falla_cerrado(monkeypatch: pytest.MonkeyPatch) -> None:
    """Una respuesta que no es JSON no se interpreta a medias."""

    cliente = ClienteHttpPublicoReal()

    class RespuestaFalsa:
        def read(self, _limite: int) -> bytes:
            return b"<html>no soy json</html>"

        def __enter__(self) -> RespuestaFalsa:
            return self

        def __exit__(self, *_argumentos: Any) -> None:
            return None

    def responder(*_argumentos: Any, **_nombrados: Any) -> RespuestaFalsa:
        return RespuestaFalsa()

    monkeypatch.setattr(cliente.abridor, "open", responder)

    with pytest.raises(ErrorActualizadorPublico, match="JSON válido"):
        cliente.obtener_json("https://api.github.com/repos/x/y/commits/main")


# ---------------------------------------------------------------------------
# 11 a 14. Contrato de configuración local
# ---------------------------------------------------------------------------


def escribir_contrato(release: Path, recursos: list[dict[str, Any]]) -> None:
    """Materializa un contrato sintético dentro de una release de prueba."""

    ruta = release / RUTA_CONTRATO_EN_RELEASE
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(
        json.dumps(
            {"formato": "sis-leg-configuracion", "version_contrato": 1, "recursos": recursos},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def recurso(ruta_local: str, **cambios: Any) -> dict[str, Any]:
    """Entrada de contrato con valores por defecto seguros."""

    base: dict[str, Any] = {
        "ruta_local": ruta_local,
        "tipo": "archivo",
        "schema": "v1",
        "bootstrap": None,
        "descripcion": "recurso de prueba",
    }
    base.update(cambios)
    return base


def test_el_contrato_real_declara_los_recursos_institucionales(tmp_path: Path) -> None:
    """El contrato versionado cubre los cuatro archivos locales y las fotos."""

    del tmp_path
    recursos = leer_contrato_de_release(RAIZ_REPOSITORIO)

    rutas = {entrada.ruta_local for entrada in recursos}
    assert rutas == {
        "config/system.toml",
        "config/concejales.csv",
        "config/apoyo-tecnico/mensajes.csv",
        "config/bridge/devices.json",
        "config/assets/bancas",
    }
    # Ninguno declara bootstrap: hoy todos los provisiona el operador y una
    # actualización jamás puede crearlos ni reemplazarlos.
    assert all(entrada.bootstrap is None for entrada in recursos)


def test_configuracion_existente_se_preserva_byte_a_byte(tmp_path: Path) -> None:
    """Un archivo local existente no se toca aunque la release traiga otro."""

    raiz = tmp_path / "opt"
    destino = raiz / "config/system.toml"
    destino.parent.mkdir(parents=True)
    destino.write_text("valor institucional real", encoding="utf-8")
    release = tmp_path / "release"
    bootstrap = release / "deploy/defaults/system.toml"
    bootstrap.parent.mkdir(parents=True)
    bootstrap.write_text("plantilla nueva", encoding="utf-8")
    escribir_contrato(
        release,
        [
            recurso(
                "config/system.toml",
                bootstrap="deploy/defaults/system.toml",
                usuario="root",
                grupo="sis-leg-backend",
                modo="0640",
            )
        ],
    )

    plan = planificar_configuracion(raiz, leer_contrato_de_release(release), None)
    creados = aplicar_plan_configuracion(raiz, release, plan)

    assert [entrada.accion for entrada in plan] == [ACCION_PRESERVAR]
    assert creados == ()
    assert destino.read_text(encoding="utf-8") == "valor institucional real"


def test_recurso_nuevo_ausente_se_crea_add_only_con_permisos(tmp_path: Path) -> None:
    """Un recurso que la release declara y no existe se incorpora una sola vez."""

    raiz = tmp_path / "opt"
    raiz.mkdir()
    release = tmp_path / "release"
    bootstrap = release / "deploy/defaults/nuevo.json"
    bootstrap.parent.mkdir(parents=True)
    bootstrap.write_text('{"clave": "valor"}', encoding="utf-8")
    escribir_contrato(
        release,
        [
            recurso(
                "config/nuevo.json",
                bootstrap="deploy/defaults/nuevo.json",
                usuario="root",
                grupo="sis-leg-backend",
                modo="0640",
            )
        ],
    )

    plan = planificar_configuracion(raiz, leer_contrato_de_release(release), None)
    creados = aplicar_plan_configuracion(raiz, release, plan)

    assert [entrada.accion for entrada in plan] == [ACCION_CREAR]
    assert creados == ("config/nuevo.json",)
    creado = raiz / "config/nuevo.json"
    assert creado.read_text(encoding="utf-8") == '{"clave": "valor"}'
    assert creado.stat().st_mode & 0o777 == 0o640
    # No queda ningún temporal de la escritura atómica.
    assert sorted(ruta.name for ruta in creado.parent.iterdir()) == ["nuevo.json"]


def test_recurso_existente_nunca_se_sobrescribe_al_repetir(tmp_path: Path) -> None:
    """Repetir la incorporación es idempotente y conserva el contenido local."""

    raiz = tmp_path / "opt"
    raiz.mkdir()
    release = tmp_path / "release"
    bootstrap = release / "deploy/defaults/nuevo.json"
    bootstrap.parent.mkdir(parents=True)
    bootstrap.write_text('{"clave": "valor"}', encoding="utf-8")
    escribir_contrato(
        release,
        [
            recurso(
                "config/nuevo.json",
                bootstrap="deploy/defaults/nuevo.json",
                usuario="root",
                grupo="sis-leg-backend",
                modo="0640",
            )
        ],
    )
    contrato = leer_contrato_de_release(release)
    aplicar_plan_configuracion(raiz, release, planificar_configuracion(raiz, contrato, None))
    (raiz / "config/nuevo.json").write_text("editado por el operador", encoding="utf-8")

    plan = planificar_configuracion(raiz, contrato, None)
    creados = aplicar_plan_configuracion(raiz, release, plan)

    assert [entrada.accion for entrada in plan] == [ACCION_PRESERVAR]
    assert creados == ()
    assert (raiz / "config/nuevo.json").read_text(encoding="utf-8") == "editado por el operador"


def test_directorio_nuevo_completa_solo_lo_que_falta(tmp_path: Path) -> None:
    """Un recurso de tipo directorio se completa archivo por archivo."""

    raiz = tmp_path / "opt"
    destino = raiz / "config/assets/bancas"
    destino.mkdir(parents=True)
    (destino / "banca-01.png").write_bytes(b"foto real del operador")
    release = tmp_path / "release"
    origen = release / "deploy/defaults/bancas"
    origen.mkdir(parents=True)
    (origen / "banca-01.png").write_bytes(b"plantilla 1")
    (origen / "banca-02.png").write_bytes(b"plantilla 2")
    escribir_contrato(
        release,
        [
            recurso(
                "config/assets/bancas",
                tipo="directorio",
                bootstrap="deploy/defaults/bancas",
                usuario="root",
                grupo="sis-leg-backend",
                modo="0640",
            )
        ],
    )

    # El directorio ya existe, así que el plan lo preserva entero: la
    # incorporación parcial sólo ocurre cuando el recurso está ausente.
    plan = planificar_configuracion(raiz, leer_contrato_de_release(release), None)
    assert [entrada.accion for entrada in plan] == [ACCION_PRESERVAR]

    # Con el directorio ausente sí se crea, y se crean todas sus entradas.
    raiz_limpia = tmp_path / "opt-limpio"
    raiz_limpia.mkdir()
    plan_limpio = planificar_configuracion(raiz_limpia, leer_contrato_de_release(release), None)
    creados = aplicar_plan_configuracion(raiz_limpia, release, plan_limpio)

    assert creados == ("config/assets/bancas",)
    assert (raiz_limpia / "config/assets/bancas/banca-01.png").read_bytes() == b"plantilla 1"
    assert (raiz_limpia / "config/assets/bancas/banca-02.png").read_bytes() == b"plantilla 2"
    assert (destino / "banca-01.png").read_bytes() == b"foto real del operador"


def test_cambio_de_schema_aborta_antes_de_mutar(tmp_path: Path) -> None:
    """Una migración real detiene la actualización y exige HUMAN_GATE."""

    raiz = tmp_path / "opt"
    destino = raiz / "config/system.toml"
    destino.parent.mkdir(parents=True)
    destino.write_text("valor institucional real", encoding="utf-8")

    release_vieja = tmp_path / "vieja"
    escribir_contrato(release_vieja, [recurso("config/system.toml", schema="system-toml-v1")])
    release_nueva = tmp_path / "nueva"
    bootstrap = release_nueva / "deploy/defaults/nuevo.json"
    bootstrap.parent.mkdir(parents=True)
    bootstrap.write_text("{}", encoding="utf-8")
    escribir_contrato(
        release_nueva,
        [
            recurso("config/system.toml", schema="system-toml-v2"),
            recurso(
                "config/nuevo.json",
                bootstrap="deploy/defaults/nuevo.json",
                usuario="root",
                grupo="sis-leg-backend",
                modo="0640",
            ),
        ],
    )

    plan = planificar_configuracion(
        raiz,
        leer_contrato_de_release(release_nueva),
        leer_contrato_de_release(release_vieja),
    )

    assert [entrada.accion for entrada in plan] == [ACCION_MIGRACION_REQUERIDA, ACCION_CREAR]
    with pytest.raises(ErrorConfiguracionLocal, match="HUMAN_GATE"):
        aplicar_plan_configuracion(raiz, release_nueva, plan)
    # Nada mutó: ni el archivo existente ni el recurso que se iba a incorporar.
    assert destino.read_text(encoding="utf-8") == "valor institucional real"
    assert not (raiz / "config/nuevo.json").exists()


def test_version_de_contrato_desconocida_aborta(tmp_path: Path) -> None:
    """Un contrato de una versión futura no se interpreta a medias."""

    release = tmp_path / "release"
    ruta = release / RUTA_CONTRATO_EN_RELEASE
    ruta.parent.mkdir(parents=True)
    ruta.write_text(
        json.dumps(
            {"formato": "sis-leg-configuracion", "version_contrato": 99, "recursos": []},
        ),
        encoding="utf-8",
    )

    with pytest.raises(ErrorConfiguracionLocal, match="HUMAN_GATE"):
        leer_contrato_de_release(release)


@pytest.mark.parametrize(
    ("ruta_local", "mensaje"),
    [
        ("/etc/passwd", "inválida"),
        ("config/../../fuera", "traversal"),
        ("logs/auditoria.csv", "sólo puede administrar rutas"),
    ],
    ids=["absoluta", "traversal", "fuera-de-config"],
)
def test_el_contrato_rechaza_rutas_peligrosas(
    tmp_path: Path, ruta_local: str, mensaje: str
) -> None:
    """El contrato sólo administra configuración, nunca rutas arbitrarias."""

    release = tmp_path / "release"
    escribir_contrato(release, [recurso(ruta_local)])

    with pytest.raises(ErrorConfiguracionLocal, match=mensaje):
        leer_contrato_de_release(release)


def test_release_sin_contrato_no_puede_evaluarse(tmp_path: Path) -> None:
    """Sin contrato no hay forma de decidir si hace falta una migración."""

    release = tmp_path / "release"
    release.mkdir()

    with pytest.raises(ErrorConfiguracionLocal, match="no incluye"):
        leer_contrato_de_release(release)


# ---------------------------------------------------------------------------
# 15. El zócalo sigue siendo obligatorio
# ---------------------------------------------------------------------------


def test_la_release_publica_debe_declarar_y_contener_el_zocalo(tmp_path: Path) -> None:
    """El canal nuevo no puede publicar una release sin la SPA del Zócalo."""

    paquete, _ = construir_artefactos(tmp_path)
    manifest = inspeccionar_manifest_paquete(paquete, SHA)

    assert manifest["spas"]["zocalo"] == "web/zocalo/index.html"
    rutas = {entrada["ruta"] for entrada in manifest["archivos"]}
    assert "web/zocalo/index.html" in rutas
    assert RUTA_CONTRATO_EN_RELEASE in rutas


def test_un_manifest_sin_zocalo_es_rechazado(tmp_path: Path) -> None:
    """Degradar la validación de WP-099 no es una opción para WP-100."""

    paquete, _ = construir_artefactos(tmp_path)
    manifest = inspeccionar_manifest_paquete(paquete, SHA)
    manifest["spas"] = {
        clave: valor for clave, valor in manifest["spas"].items() if clave != "zocalo"
    }

    with pytest.raises(ErrorDespliegue, match="SPA canónicas"):
        validar_manifest(manifest, SHA)


@pytest.mark.parametrize(
    ("script", "argumentos", "esperado"),
    [
        ("deploy/actualizador_publico.py", ["obtener", "--help"], "--destino"),
        ("deploy/herramienta_despliegue.py", ["--help"], "plan-configuracion"),
    ],
    ids=["actualizador", "herramienta"],
)
def test_los_ejecutables_resuelven_sus_imports_desde_la_release(
    tmp_path: Path, script: str, argumentos: list[str], esperado: str
) -> None:
    """Producción los invoca como script suelto, no como módulo del paquete.

    En esa forma Python deja ``deploy/`` en ``sys.path`` y no la raíz de la
    release, así que ambos ejecutables preparan la raíz antes de importar. Se
    corren desde un directorio ajeno para que el éxito no dependa del cwd.
    """

    resultado = subprocess.run(
        [sys.executable, str(RAIZ_REPOSITORIO / script), *argumentos],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert resultado.returncode == 0, resultado.stderr
    assert esperado in resultado.stdout
