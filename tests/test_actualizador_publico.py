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
import re
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

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
    tag_publicacion,
    validar_url_publica,
    verificar_intento_ci,
    verificar_intento_historico,
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
from scripts.publicar_release_publica import ErrorPublicacion, crear_parser, publicar_release

SHA = "a" * 40
SHA_ARBOL = "c" * 40
SHA_OTRO = "b" * 40
REPOSITORIO = "martinebene/SIS-Leg"
RAIZ_REPOSITORIO = Path(__file__).resolve().parents[1]
RUN_ID = 4242
RUN_NUMERO = 17
JOB_ID = 990099
# Identificador del job de empaquetado que produciría una re-ejecución de la
# misma run: distinto del original, igual que en GitHub Actions.
JOB_ID_REEJECUCION = 991177


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


def run_exitosa(sha: str = SHA, *, intento: int = 1, **cambios: Any) -> dict[str, Any]:
    """Devuelve el intento de CI canónico que habilita una publicación.

    Es la respuesta de ``/actions/runs/{run_id}/attempts/{intento}``: una run de
    ``push`` sobre ``main``, del workflow ``CI``, completada con éxito para ese
    SHA. ``cambios`` permite romper un campo por vez en las pruebas de rechazo.
    """

    run: dict[str, Any] = {
        "id": RUN_ID,
        "run_number": RUN_NUMERO,
        "run_attempt": intento,
        "name": NOMBRE_WORKFLOW_CI,
        "event": "push",
        "head_branch": "main",
        "head_sha": sha,
        "status": "completed",
        "conclusion": "success",
    }
    run.update(cambios)
    return run


def jobs_exitosos(
    sha: str = SHA,
    *,
    intento: int = 1,
    job_id: int = JOB_ID,
    run_id: int = RUN_ID,
    **cambios: Any,
) -> dict[str, Any]:
    """Devuelve los jobs de un intento exacto, con el de empaquetado exitoso.

    Cada job declara ``run_id`` y ``run_attempt`` como lo hace la API real: eso
    es lo que permite detectar metadatos que mezclen la ejecución de un intento
    con el identificador de otro. ``cambios`` altera solamente el job de
    empaquetado, que es el que las pruebas de rechazo quieren romper.
    """

    comunes: dict[str, Any] = {
        "run_id": run_id,
        "run_attempt": intento,
        "head_sha": sha,
        "conclusion": "success",
    }
    job: dict[str, Any] = {**comunes, "id": job_id, "name": NOMBRE_JOB_EMPAQUETADO}
    job.update(cambios)
    otros = [
        {**comunes, "id": job_id + 1, "name": "Backend · pruebas"},
        {**comunes, "id": job_id + 2, "name": "Frontend · build estático"},
    ]
    return {"total_count": 3, "jobs": [*otros, job]}


def numero_de_intento(url: str) -> int:
    """Extrae el intento de una URL ``/attempts/<n>`` o ``/attempts/<n>/jobs``."""

    cola = url.split("/attempts/", 1)[1]
    return int(cola.split("/", 1)[0].split("?", 1)[0])


class ClienteApiFalso:
    """Emula el lado escritura del API de GitHub para el publicador.

    Guarda las releases creadas y los bytes de cada asset subido, de modo que la
    misma instancia sirve después como origen de datos del consumidor. Así una
    incompatibilidad entre lo que se publica y lo que se consume rompe la prueba.

    Los intentos de CI se guardan indexados por número para poder simular una
    re-ejecución: registrar el intento 2 no borra el 1, igual que en GitHub.
    """

    def __init__(self, *, run: dict[str, Any], jobs: dict[str, Any], intento: int = 1) -> None:
        self.intentos: dict[int, dict[str, Any]] = {}
        self.jobs: dict[int, dict[str, Any]] = {}
        self.registrar_intento(intento, run, jobs)
        self.releases: dict[str, dict[str, Any]] = {}
        self.contenidos: dict[str, bytes] = {}
        self.creaciones = 0
        self.subidas: list[str] = []
        self.urls: list[str] = []

    def registrar_intento(self, numero: int, run: dict[str, Any], jobs: dict[str, Any]) -> None:
        """Agrega un intento histórico consultable, sin quitar los anteriores."""

        self.intentos[numero] = run
        self.jobs[numero] = jobs

    def obtener(self, url: str) -> Any | None:
        self.urls.append(url)
        if "/attempts/" in url:
            numero = numero_de_intento(url)
            if url.endswith("/jobs?per_page=100"):
                return self.jobs.get(numero)
            return self.intentos.get(numero)
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
    las pruebas no dependan del orden de los parámetros de la query. Un intento
    no registrado se comporta como el cliente real ante un 404: levanta el error
    del canal, que es lo que obliga al consumidor a fallar cerrado.
    """

    def __init__(
        self,
        *,
        sha: str = SHA,
        intentos: dict[int, dict[str, Any]] | None = None,
        jobs: dict[int, dict[str, Any]] | None = None,
        release: dict[str, Any] | None = None,
        contenidos: dict[str, bytes] | None = None,
    ) -> None:
        self.sha = sha
        self.intentos = intentos if intentos is not None else {1: run_exitosa(sha)}
        self.jobs = jobs if jobs is not None else {1: jobs_exitosos(sha)}
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
        if "/attempts/" in url:
            numero = numero_de_intento(url)
            fuente = self.jobs if url.endswith("/jobs?per_page=100") else self.intentos
            if numero not in fuente:
                raise ErrorActualizadorPublico(f"GitHub respondió HTTP 404 en {url}.")
            return fuente[numero]
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
        cliente,
        repositorio=REPOSITORIO,
        sha=sha,
        run_id=RUN_ID,
        run_attempt=1,
        directorio=directorio,
    )
    return cliente, resumen, directorio


def registrar_reejecucion(publicador: ClienteApiFalso, *, sha: str = SHA) -> None:
    """Simula una re-ejecución: mismo ``run_id`` y SHA, intento y jobs nuevos.

    El intento 1 sigue existiendo, como en GitHub. Lo que cambia es qué devuelve
    la consulta genérica por «los jobs de la run», que ya no sirve como prueba
    del job histórico.
    """

    publicador.registrar_intento(
        2,
        run_exitosa(sha, intento=2),
        jobs_exitosos(sha, intento=2, job_id=JOB_ID_REEJECUCION),
    )


def consumidor_desde_publicacion(
    publicador: ClienteApiFalso, *, sha: str = SHA
) -> ClienteHttpFalso:
    """Arma el cliente público del consumidor con lo que el publicador dejó."""

    return ClienteHttpFalso(
        sha=sha,
        intentos=dict(publicador.intentos),
        jobs=dict(publicador.jobs),
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
        "ci_run_attempt": 1,
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
            run_attempt=1,
            directorio=paquete.parent,
        )
    assert cliente.releases == {}


def test_publicacion_rechaza_job_de_empaquetado_fallido(tmp_path: Path) -> None:
    """Una CI verde con el job de empaquetado no exitoso no puede publicarse."""

    paquete, _ = construir_artefactos(tmp_path)
    cliente = ClienteApiFalso(run=run_exitosa(), jobs=jobs_exitosos(conclusion="failure"))

    with pytest.raises(ErrorPublicacion, match="no terminó en success"):
        publicar_release(
            cliente,
            repositorio=REPOSITORIO,
            sha=SHA,
            run_id=RUN_ID,
            run_attempt=1,
            directorio=paquete.parent,
        )
    assert cliente.releases == {}


def test_publicacion_rechaza_job_de_otro_sha(tmp_path: Path) -> None:
    """El job debe pertenecer al mismo head_sha; no se mezclan dos SHAs."""

    paquete, _ = construir_artefactos(tmp_path)
    cliente = ClienteApiFalso(run=run_exitosa(), jobs=jobs_exitosos(head_sha=SHA_OTRO))

    with pytest.raises(ErrorPublicacion, match="no se mezclan SHAs"):
        publicar_release(
            cliente,
            repositorio=REPOSITORIO,
            sha=SHA,
            run_id=RUN_ID,
            run_attempt=1,
            directorio=paquete.parent,
        )


def test_publicacion_rechaza_jobs_paginados(tmp_path: Path) -> None:
    """Si la respuesta vino paginada no se puede demostrar unicidad y se aborta."""

    paquete, _ = construir_artefactos(tmp_path)
    jobs = jobs_exitosos()
    jobs["total_count"] = 99
    cliente = ClienteApiFalso(run=run_exitosa(), jobs=jobs)

    with pytest.raises(ErrorPublicacion, match="jobs de 99"):
        publicar_release(
            cliente,
            repositorio=REPOSITORIO,
            sha=SHA,
            run_id=RUN_ID,
            run_attempt=1,
            directorio=paquete.parent,
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
        publicador,
        repositorio=REPOSITORIO,
        sha=SHA,
        run_id=RUN_ID,
        run_attempt=1,
        directorio=directorio,
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
            publicador,
            repositorio=REPOSITORIO,
            sha=SHA,
            run_id=RUN_ID,
            run_attempt=1,
            directorio=directorio,
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
            publicador,
            repositorio=REPOSITORIO,
            sha=SHA,
            run_id=RUN_ID,
            run_attempt=1,
            directorio=directorio,
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
            cliente,
            repositorio=REPOSITORIO,
            sha=SHA,
            run_id=RUN_ID,
            run_attempt=1,
            directorio=paquete.parent,
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
# 5. Evidencia determinista del intento de CI y de su job
# ---------------------------------------------------------------------------


def test_el_intento_historico_habilitante_se_demuestra_contra_la_api() -> None:
    """El par run + intento se resuelve sin heurísticas ni ``latest``."""

    cliente = ClienteHttpFalso()

    run, job = verificar_intento_historico(
        cliente.obtener_json, repositorio=REPOSITORIO, run_id=RUN_ID, intento=1, sha=SHA
    )

    assert (run.identificador, run.intento, run.numero) == (RUN_ID, 1, RUN_NUMERO)
    assert (job.identificador, job.run_id, job.intento) == (JOB_ID, RUN_ID, 1)
    # Nunca se usa la consulta genérica de jobs de la run: devolvería el intento
    # más reciente y no serviría como prueba del histórico.
    assert all("/attempts/" in url for url in cliente.urls)


@pytest.mark.parametrize(
    "cambio",
    [
        {"event": "pull_request"},
        {"head_branch": "wp/100"},
        {"conclusion": "failure"},
        {"status": "in_progress"},
        {"head_sha": SHA_OTRO},
        {"name": "Otro workflow"},
        {"id": 7777},
        {"run_attempt": 5},
    ],
    ids=[
        "pull-request",
        "otra-rama",
        "fallida",
        "en-curso",
        "otro-sha",
        "otro-workflow",
        "otra-run",
        "otro-intento",
    ],
)
def test_no_se_acepta_un_intento_de_otro_origen(cambio: dict[str, Any]) -> None:
    """Un intento de otro evento, rama, SHA, workflow o ejecución no habilita nada."""

    cliente = ClienteHttpFalso(intentos={1: run_exitosa(**cambio)})

    with pytest.raises(ErrorActualizadorPublico):
        verificar_intento_ci(
            cliente.obtener_json, repositorio=REPOSITORIO, run_id=RUN_ID, intento=1, sha=SHA
        )


def test_un_intento_inexistente_no_puede_demostrarse() -> None:
    """Si el intento que los metadatos nombran no existe, se falla cerrado."""

    cliente = ClienteHttpFalso(intentos={2: run_exitosa(intento=2)})

    with pytest.raises(ErrorActualizadorPublico, match="intento 1"):
        verificar_intento_ci(
            cliente.obtener_json, repositorio=REPOSITORIO, run_id=RUN_ID, intento=1, sha=SHA
        )


@pytest.mark.parametrize("intento", [0, -3], ids=["cero", "negativo"])
def test_un_intento_no_positivo_se_rechaza_antes_de_consultar(intento: int) -> None:
    """Los identificadores se validan antes de concatenarlos en una URL."""

    cliente = ClienteHttpFalso()

    with pytest.raises(ErrorActualizadorPublico, match="entero positivo"):
        verificar_intento_ci(
            cliente.obtener_json, repositorio=REPOSITORIO, run_id=RUN_ID, intento=intento, sha=SHA
        )
    assert cliente.urls == []


def test_jobs_del_intento_paginados_abortan_en_lugar_de_elegir_a_ciegas() -> None:
    """Si no se vio el conjunto completo no se puede demostrar unicidad."""

    jobs = jobs_exitosos()
    jobs["total_count"] = 50
    cliente = ClienteHttpFalso(jobs={1: jobs})

    with pytest.raises(ErrorActualizadorPublico, match="jobs de 50"):
        verificar_intento_historico(
            cliente.obtener_json, repositorio=REPOSITORIO, run_id=RUN_ID, intento=1, sha=SHA
        )


def test_el_job_de_empaquetado_debe_existir_una_sola_vez() -> None:
    """Dos jobs con el nombre exacto impiden demostrar cuál validó el paquete."""

    jobs = jobs_exitosos()
    jobs["jobs"].append(dict(jobs["jobs"][-1]))
    jobs["total_count"] = 4
    cliente = ClienteHttpFalso(jobs={1: jobs})

    with pytest.raises(ErrorActualizadorPublico, match="exactamente un job"):
        verificar_intento_historico(
            cliente.obtener_json, repositorio=REPOSITORIO, run_id=RUN_ID, intento=1, sha=SHA
        )


@pytest.mark.parametrize(
    ("cambio", "mensaje"),
    [
        ({"head_sha": SHA_OTRO}, "no se mezclan SHAs"),
        ({"conclusion": "failure"}, "no terminó en success"),
        ({"conclusion": "cancelled"}, "no terminó en success"),
        ({"run_id": 909090}, "otra run"),
        ({"run_attempt": 9}, "otro intento"),
    ],
    ids=["otro-sha", "fallido", "cancelado", "otra-run", "otro-intento"],
)
def test_el_job_historico_invalido_se_rechaza(cambio: dict[str, Any], mensaje: str) -> None:
    """El job del intento debe ser exitoso y de esa misma ejecución y SHA."""

    cliente = ClienteHttpFalso(jobs={1: jobs_exitosos(**cambio)})

    with pytest.raises(ErrorActualizadorPublico, match=mensaje):
        verificar_intento_historico(
            cliente.obtener_json, repositorio=REPOSITORIO, run_id=RUN_ID, intento=1, sha=SHA
        )


# ---------------------------------------------------------------------------
# 2 y 9. Identidad exacta de la publicación y de sus assets
# ---------------------------------------------------------------------------


def test_se_acepta_target_commitish_normalizado_a_la_rama(tmp_path: Path) -> None:
    """GitHub puede devolver la rama en lugar del SHA; la atadura no depende de eso.

    La identidad con el commit la garantizan el nombre del tag, el ``commit_sha``
    de los metadatos y el de ``release.json``. Aceptar ``main`` en ese campo no
    afloja ninguna de esas tres comprobaciones.
    """

    publicador, _, _ = publicar_para_pruebas(tmp_path)
    release = dict(publicador.releases[tag_publicacion(SHA)])
    release["target_commitish"] = "main"
    cliente = ClienteHttpFalso(release=release, contenidos=dict(publicador.contenidos))

    publicacion = resolver_publicacion(cliente, SHA, repositorio=REPOSITORIO)

    assert publicacion.commit_sha == SHA


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
        ("target_commitish", SHA_OTRO, "no al commit"),
        ("target_commitish", "wp/100", "no al commit"),
        ("tag_name", "sis-leg-otro", "tag distinto"),
    ],
    ids=["borrador", "prerelease", "otro-commit", "otra-rama", "otro-tag"],
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
        ("/attempts/", ErrorActualizadorPublico("límite de tasa")),
        ("/jobs", ErrorActualizadorPublico("timed out")),
        ("/releases/tags/", ErrorActualizadorPublico("JSON")),
        ("objects.githubusercontent.com", ErrorActualizadorPublico("conexión interrumpida")),
    ],
    ids=["commit", "intento", "jobs", "release", "descarga"],
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
# 18. Re-ejecuciones de CI: la release inmutable sobrevive (WP-100 I002)
#
# GitHub permite re-ejecutar una run conservando `run_id` y SHA, creando un
# intento nuevo con jobs nuevos. La release ya publicada no cambia —es inmutable—
# así que la evidencia que hay que demostrar es siempre la del intento que la
# habilitó. Estas pruebas fijan ese comportamiento en los dos extremos del canal.
# ---------------------------------------------------------------------------


def metadatos_publicados(publicador: ClienteApiFalso, *, sha: str = SHA) -> dict[str, Any]:
    """Lee el asset de metadatos tal como quedó publicado."""

    return cast(
        dict[str, Any], json.loads(publicador.contenidos[nombre_metadatos(sha)].decode("utf-8"))
    )


def consumidor_con_metadatos_mutados(
    publicador: ClienteApiFalso,
    mutar: Callable[[dict[str, Any]], None],
    *,
    sha: str = SHA,
) -> ClienteHttpFalso:
    """Publica, altera los metadatos ya publicados y arma el consumidor.

    Sirve para simular una release manipulada o incoherente sin tocar el
    publicador: el consumidor debe rechazarla por sí mismo.
    """

    contenidos = dict(publicador.contenidos)
    metadatos = metadatos_publicados(publicador, sha=sha)
    mutar(metadatos)
    contenidos[nombre_metadatos(sha)] = (json.dumps(metadatos, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )
    release = dict(publicador.releases[tag_publicacion(sha)])
    release["assets"] = [
        {**asset, "size": len(contenidos[asset["name"]])} for asset in release["assets"]
    ]
    cliente = consumidor_desde_publicacion(publicador, sha=sha)
    cliente.release = release
    cliente.contenidos = contenidos
    return cliente


def test_la_publicacion_del_primer_intento_registra_ese_intento_exacto(tmp_path: Path) -> None:
    """El intento 1 publica y sus metadatos nombran run, intento y job reales."""

    publicador, resumen, _ = publicar_para_pruebas(tmp_path)

    assert resumen["estado"] == "creada"
    assert resumen["ci_run_attempt"] == 1
    ci = metadatos_publicados(publicador)["ci"]
    assert (ci["run_id"], ci["run_attempt"], ci["job_id"]) == (RUN_ID, 1, JOB_ID)


def test_una_reejecucion_reconoce_idempotencia_sin_sustituir_assets(tmp_path: Path) -> None:
    """Re-ejecutar la CI del mismo SHA no reescribe ni invalida la release.

    El publicador vuelve a correr con `run_attempt=2` y jobs nuevos. La release
    del intento 1 sigue siendo válida, así que la operación es idempotente: no
    crea, no sube y no toca los metadatos ya publicados.
    """

    publicador, _, directorio = publicar_para_pruebas(tmp_path)
    registrar_reejecucion(publicador)
    creaciones = publicador.creaciones
    subidas = list(publicador.subidas)
    antes = dict(publicador.contenidos)

    segundo = publicar_release(
        publicador,
        repositorio=REPOSITORIO,
        sha=SHA,
        run_id=RUN_ID,
        run_attempt=2,
        directorio=directorio,
    )

    assert segundo["estado"] == "idempotente"
    # Se informa el intento que realmente publicó, no el que está re-ejecutando.
    assert segundo["ci_run_attempt"] == 1
    assert segundo["ci_run_id"] == RUN_ID
    assert publicador.creaciones == creaciones
    assert publicador.subidas == subidas
    assert publicador.contenidos == antes
    assert metadatos_publicados(publicador)["ci"]["job_id"] == JOB_ID


def test_el_consumidor_consume_la_publicacion_del_intento_uno_tras_la_reejecucion(
    tmp_path: Path,
) -> None:
    """Existiendo un intento 2, se sigue verificando y consumiendo el intento 1."""

    publicador, _, _ = publicar_para_pruebas(tmp_path)
    registrar_reejecucion(publicador)
    cliente = consumidor_desde_publicacion(publicador)
    destino = tmp_path / "descarga"

    release = obtener_release_publica(destino, cliente=cliente, repositorio=REPOSITORIO)

    assert release.commit_sha == SHA
    assert (release.run_ci.identificador, release.run_ci.intento) == (RUN_ID, 1)
    assert release.job_ci.identificador == JOB_ID
    # La prueba del job histórico se pide por intento exacto; jamás se consulta
    # `/actions/runs/<id>/jobs`, que respondería con los jobs del intento 2.
    assert f"/actions/runs/{RUN_ID}/attempts/1/jobs?per_page=100" in " ".join(cliente.urls)
    assert not re.search(rf"/actions/runs/{RUN_ID}/jobs", " ".join(cliente.urls))
    assert sorted(ruta.name for ruta in destino.iterdir()) == sorted(assets_esperados(SHA))


def test_el_consumidor_rechaza_un_intento_historico_inexistente(tmp_path: Path) -> None:
    """Si el intento que los metadatos declaran no existe, no se consume nada."""

    publicador, _, _ = publicar_para_pruebas(tmp_path)
    cliente = consumidor_desde_publicacion(publicador)
    # Sólo sobrevive un intento 2: el que la release nombra ya no está.
    registrar_reejecucion(publicador)
    cliente.intentos = {2: publicador.intentos[2]}
    cliente.jobs = {2: publicador.jobs[2]}
    destino = tmp_path / "descarga"

    with pytest.raises(ErrorActualizadorPublico, match="intento 1"):
        obtener_release_publica(destino, cliente=cliente, repositorio=REPOSITORIO)
    assert not destino.exists() or list(destino.iterdir()) == []


@pytest.mark.parametrize("conclusion", ["failure", "cancelled"], ids=["fallido", "cancelado"])
def test_el_consumidor_rechaza_un_job_historico_no_exitoso(tmp_path: Path, conclusion: str) -> None:
    """Un empaquetado histórico que no terminó en success invalida la release."""

    publicador, _, _ = publicar_para_pruebas(tmp_path)
    cliente = consumidor_desde_publicacion(publicador)
    cliente.jobs = {1: jobs_exitosos(conclusion=conclusion)}
    destino = tmp_path / "descarga"

    with pytest.raises(ErrorActualizadorPublico, match="no terminó en success"):
        obtener_release_publica(destino, cliente=cliente, repositorio=REPOSITORIO)
    assert not destino.exists() or list(destino.iterdir()) == []


def test_el_consumidor_rechaza_un_job_historico_de_otro_sha(tmp_path: Path) -> None:
    """El job del intento debe declarar el mismo commit que se está instalando."""

    publicador, _, _ = publicar_para_pruebas(tmp_path)
    cliente = consumidor_desde_publicacion(publicador)
    cliente.jobs = {1: jobs_exitosos(head_sha=SHA_OTRO)}

    with pytest.raises(ErrorActualizadorPublico, match="no se mezclan SHAs"):
        obtener_release_publica(tmp_path / "descarga", cliente=cliente, repositorio=REPOSITORIO)


@pytest.mark.parametrize(
    ("campo", "valor", "mensaje"),
    [
        ("run_id", 606060, "intento"),
        ("run_attempt", 2, "job distinto"),
        ("run_number", 99, "número de run"),
        ("job_id", 111222, "job distinto"),
    ],
    ids=["otra-run", "otro-intento", "otro-numero", "otro-job"],
)
def test_el_consumidor_rechaza_metadatos_con_ci_cruzada(
    tmp_path: Path, campo: str, valor: Any, mensaje: str
) -> None:
    """Unos metadatos que mezclen run, intento o job de otra ejecución no sirven.

    El caso ``run_attempt`` es el interesante después de una re-ejecución: el
    intento 2 existe y es válido en sí mismo, pero su job de empaquetado tiene un
    identificador nuevo que no es el que los metadatos declaran.
    """

    publicador, _, _ = publicar_para_pruebas(tmp_path)
    registrar_reejecucion(publicador)

    def mutar(metadatos: dict[str, Any]) -> None:
        cast(dict[str, Any], metadatos["ci"])[campo] = valor

    cliente = consumidor_con_metadatos_mutados(publicador, mutar)

    with pytest.raises(ErrorActualizadorPublico, match=mensaje):
        obtener_release_publica(tmp_path / "descarga", cliente=cliente, repositorio=REPOSITORIO)


def test_el_publicador_aborta_si_la_evidencia_historica_ya_no_se_sostiene(
    tmp_path: Path,
) -> None:
    """Sin intento histórico demostrable no se confirma idempotencia ni se muta.

    Es el caso simétrico del anterior: la release existe y sus bytes coinciden,
    pero la evidencia de CI que declara dejó de ser verificable. Fallar cerrado
    es preferible a dar por buena una publicación que ya no puede demostrarse.
    """

    publicador, _, directorio = publicar_para_pruebas(tmp_path)
    registrar_reejecucion(publicador)
    antes = dict(publicador.contenidos)
    publicador.jobs[1] = jobs_exitosos(conclusion="failure")

    with pytest.raises(ErrorPublicacion, match="no terminó en success"):
        publicar_release(
            publicador,
            repositorio=REPOSITORIO,
            sha=SHA,
            run_id=RUN_ID,
            run_attempt=2,
            directorio=directorio,
        )
    assert publicador.creaciones == 1
    assert publicador.contenidos == antes


def test_el_publicador_aborta_si_los_metadatos_publicados_declaran_otro_arbol(
    tmp_path: Path,
) -> None:
    """Paquete idéntico pero metadatos divergentes siguen exigiendo una persona."""

    publicador, _, directorio = publicar_para_pruebas(tmp_path)
    metadatos = metadatos_publicados(publicador)
    metadatos["tree_sha"] = "d" * 40
    publicador.contenidos[nombre_metadatos(SHA)] = (
        json.dumps(metadatos, ensure_ascii=False) + "\n"
    ).encode("utf-8")

    with pytest.raises(ErrorPublicacion, match="árbol Git"):
        publicar_release(
            publicador,
            repositorio=REPOSITORIO,
            sha=SHA,
            run_id=RUN_ID,
            run_attempt=1,
            directorio=directorio,
        )
    assert publicador.creaciones == 1


def test_el_workflow_le_pasa_al_publicador_el_intento_del_evento() -> None:
    """El workflow y la CLI del publicador no pueden desincronizarse.

    El intento habilitante llega desde el evento `workflow_run` y no se deduce
    releyendo la run, así que si el workflow dejara de pasarlo —o la CLI dejara
    de exigirlo— el publicador volvería a trabajar sobre «el intento actual».
    Esa regresión sólo se vería en producción, y por eso se fija acá.
    """

    workflow = (RAIZ_REPOSITORIO / ".github/workflows/publicar-release.yml").read_text(
        encoding="utf-8"
    )
    assert "SISLEG_RUN_ATTEMPT: ${{ github.event.workflow_run.run_attempt }}" in workflow
    assert '--run-attempt "${SISLEG_RUN_ATTEMPT}"' in workflow
    assert '--run-id "${SISLEG_RUN_ID}"' in workflow

    # La CLI exige ambos: sin `--run-attempt` no se publica nada.
    with pytest.raises(SystemExit):
        crear_parser().parse_args(
            [
                "--repositorio",
                REPOSITORIO,
                "--sha",
                SHA,
                "--run-id",
                str(RUN_ID),
                "--directorio",
                ".",
            ]
        )
    opciones = crear_parser().parse_args(
        [
            "--repositorio",
            REPOSITORIO,
            "--sha",
            SHA,
            "--run-id",
            str(RUN_ID),
            "--run-attempt",
            "2",
            "--directorio",
            ".",
        ]
    )
    assert (opciones.run_id, opciones.run_attempt) == (RUN_ID, 2)


# ---------------------------------------------------------------------------
# 19. Identidad del artifact interno por SHA + intento (WP-100 I003)
#
# `actions/download-artifact` sólo sabe elegir por `name` (o por `artifact-ids`)
# dentro de una `run-id`: no existe un input de intento. Como una re-ejecución
# conserva `run_id` y SHA, dos intentos que suban artifacts homónimos quedan
# ambos en la misma run y la búsqueda por nombre resuelve el más reciente.
#
# El publicador del intento 1 podría entonces descargar los bytes del intento 2
# mientras sus metadatos siguen atribuyendo la release al intento 1 y a su job
# histórico. Los bytes son reproducibles y normalmente coincidirían, pero la
# procedencia declarada dejaría de ser demostrable, que es justamente lo que el
# canal público promete.
#
# La corrección es que el nombre interno identifique SHA **e** intento en los
# dos extremos. Estas pruebas leen los workflows reales y resuelven sus
# expresiones `${{ ... }}` contra un contexto sintético, para que cualquier
# desincronización futura entre productor y consumidor rompa acá.
# ---------------------------------------------------------------------------


# Nombres exactos de los dos pasos que tienen que hablar del mismo artifact.
PASO_SUBIDA_DEL_ARTIFACT = "Publicar paquete y checksum"
PASO_DESCARGA_DEL_ARTIFACT = "Descargar el artefacto validado por la CI"


def bloque_del_paso(texto_workflow: str, nombre_del_paso: str) -> str:
    """Devuelve el texto YAML de un paso, delimitado por el paso siguiente.

    No se usa un parser YAML a propósito: incorporarlo obligaría a agregar una
    dependencia nueva, que está fuera del alcance del WP. Recortar el bloque por
    indentación alcanza porque los pasos de estos workflows viven todos al mismo
    nivel (seis espacios) y el corte se valida encontrando el `name:` esperado.
    """

    marca = f"      - name: {nombre_del_paso}\n"
    inicio = texto_workflow.find(marca)
    assert inicio != -1, f"El workflow ya no declara el paso «{nombre_del_paso}»."
    resto = texto_workflow[inicio + len(marca) :]
    fin = resto.find("\n      - ")
    return resto if fin == -1 else resto[:fin]


def plantilla_de_nombre_del_artifact(ruta: Path, nombre_del_paso: str) -> str:
    """Extrae el `name:` que ese paso le pasa a la acción de artifacts.

    Devuelve la plantilla sin resolver, es decir con sus expresiones
    `${{ ... }}` intactas, porque la prueba necesita resolverlas después contra
    contextos distintos para comparar intentos.
    """

    bloque = bloque_del_paso(ruta.read_text(encoding="utf-8"), nombre_del_paso)
    coincidencia = re.search(r"^          name: (.+)$", bloque, re.MULTILINE)
    assert coincidencia is not None, f"El paso «{nombre_del_paso}» no declara `with.name`."
    return coincidencia.group(1).strip()


def resolver_expresiones(plantilla: str, contexto: Mapping[str, str | None]) -> str:
    """Sustituye cada `${{ ... }}` por su valor en un contexto sintético.

    Implementa sólo lo que estos workflows usan: lectura de un campo del contexto
    y el operador `||`, que en GitHub Actions devuelve el primer operando no
    vacío. Un `None` representa un campo ausente —por ejemplo
    `github.event.pull_request.head.sha` en un `push`—.

    Un campo desconocido es un error deliberado: si alguien cambia el nombre del
    artifact por una expresión que esta prueba no modela, conviene que la prueba
    falle en lugar de aprobar una identidad que no entiende.
    """

    def resolver_una(coincidencia: re.Match[str]) -> str:
        for operando in coincidencia.group(1).split("||"):
            clave = operando.strip()
            assert clave in contexto, f"Expresión no modelada por la prueba: «{clave}»."
            valor = contexto[clave]
            if valor:
                return valor
        return ""

    return re.sub(r"\$\{\{(.+?)\}\}", resolver_una, plantilla)


def contexto_de_ci(*, sha: str = SHA, intento: int) -> dict[str, str | None]:
    """Contexto de un `push` a `main` corriendo el intento indicado."""

    return {
        "github.sha": sha,
        # En `push` no hay pull request: el fallback del workflow debe usar `github.sha`.
        "github.event.pull_request.head.sha": None,
        "github.run_attempt": str(intento),
    }


def contexto_de_publicacion(*, sha: str = SHA, intento: int) -> dict[str, str | None]:
    """Contexto del evento `workflow_run` que dispara la publicación."""

    return {
        "github.event.workflow_run.head_sha": sha,
        "github.event.workflow_run.run_attempt": str(intento),
    }


def nombre_subido_por_ci(*, sha: str = SHA, intento: int) -> str:
    """Nombre interno que `ci.yml` le daría al artifact en ese intento."""

    plantilla = plantilla_de_nombre_del_artifact(
        RAIZ_REPOSITORIO / ".github/workflows/ci.yml", PASO_SUBIDA_DEL_ARTIFACT
    )
    return resolver_expresiones(plantilla, contexto_de_ci(sha=sha, intento=intento))


def nombre_pedido_por_el_publicador(*, sha: str = SHA, intento: int) -> str:
    """Nombre interno que `publicar-release.yml` pediría para ese intento."""

    plantilla = plantilla_de_nombre_del_artifact(
        RAIZ_REPOSITORIO / ".github/workflows/publicar-release.yml",
        PASO_DESCARGA_DEL_ARTIFACT,
    )
    return resolver_expresiones(plantilla, contexto_de_publicacion(sha=sha, intento=intento))


def test_el_artifact_de_empaquetado_identifica_el_intento_que_lo_produjo() -> None:
    """`ci.yml` nombra el artifact con el SHA y con `github.run_attempt`."""

    plantilla = plantilla_de_nombre_del_artifact(
        RAIZ_REPOSITORIO / ".github/workflows/ci.yml", PASO_SUBIDA_DEL_ARTIFACT
    )
    assert "${{ github.run_attempt }}" in plantilla
    # El SHA sigue presente por su vía habitual: cabeza de la PR o SHA del push.
    assert "github.event.pull_request.head.sha || github.sha" in plantilla

    nombre = nombre_subido_por_ci(intento=1)
    assert SHA in nombre
    assert nombre.endswith("-intento-1")


def test_el_publicador_pide_el_artifact_del_intento_que_declara() -> None:
    """`publicar-release.yml` arma el nombre con `head_sha` y `run_attempt`."""

    plantilla = plantilla_de_nombre_del_artifact(
        RAIZ_REPOSITORIO / ".github/workflows/publicar-release.yml",
        PASO_DESCARGA_DEL_ARTIFACT,
    )
    assert "${{ github.event.workflow_run.head_sha }}" in plantilla
    assert "${{ github.event.workflow_run.run_attempt }}" in plantilla

    # `run-id` acota la run y el nombre acota el intento: hacen falta los dos.
    bloque = bloque_del_paso(
        (RAIZ_REPOSITORIO / ".github/workflows/publicar-release.yml").read_text(encoding="utf-8"),
        PASO_DESCARGA_DEL_ARTIFACT,
    )
    assert "run-id: ${{ github.event.workflow_run.id }}" in bloque


def test_los_dos_workflows_construyen_el_mismo_nombre_para_el_mismo_intento() -> None:
    """Productor y consumidor no pueden desincronizarse en la identidad.

    Es la prueba que convierte a las dos anteriores en un contrato: da igual cómo
    se escriba el nombre mientras ambos extremos lo escriban igual para el mismo
    SHA y el mismo intento.
    """

    for intento in (1, 2, 7):
        assert nombre_subido_por_ci(intento=intento) == nombre_pedido_por_el_publicador(
            intento=intento
        )


def test_dos_intentos_del_mismo_sha_no_comparten_nombre_de_artifact() -> None:
    """Una re-ejecución del mismo SHA produce un nombre interno distinto.

    Sin esto, los dos intentos convivirían como artifacts homónimos dentro de la
    misma run y la selección por nombre devolvería el más reciente.
    """

    primero = nombre_subido_por_ci(intento=1)
    segundo = nombre_subido_por_ci(intento=2)
    assert primero != segundo
    # Ambos siguen declarando el mismo SHA: lo único que los separa es el intento.
    assert SHA in primero and SHA in segundo


def test_la_publicacion_del_intento_uno_no_puede_nombrar_el_artifact_del_intento_dos() -> None:
    """El escenario de carrera de la auditoría queda cerrado por construcción.

    El publicador disparado por el intento 1 sólo sabe pedir el nombre del
    intento 1. Aunque el intento 2 ya haya subido su artifact a la misma run,
    ese nombre no coincide, así que no puede ser el que se descargue y publique.
    """

    pedido_por_el_intento_uno = nombre_pedido_por_el_publicador(intento=1)
    subido_por_el_intento_dos = nombre_subido_por_ci(intento=2)
    assert pedido_por_el_intento_uno != subido_por_el_intento_dos
    assert pedido_por_el_intento_uno == nombre_subido_por_ci(intento=1)


def test_la_identidad_por_intento_no_altera_los_nombres_publicos(tmp_path: Path) -> None:
    """Los tres assets públicos y el tag siguen dependiendo sólo del SHA.

    La identidad por intento es interna al canal de CI. Un consumidor externo
    resuelve la release por SHA y no sabe —ni tiene por qué saber— cuántos
    intentos hubo.
    """

    publicador, _, _ = publicar_para_pruebas(tmp_path)
    assert set(publicador.contenidos) == {
        nombre_paquete(SHA),
        nombre_sidecar(SHA),
        nombre_metadatos(SHA),
    }
    assert tag_publicacion(SHA) in publicador.releases
    for nombre_publico in publicador.contenidos:
        assert "intento" not in nombre_publico


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
