"""Bootstrap público **transicional** desde releases anteriores a WP-101A (WP-105).

¿Qué problema resuelve?
-----------------------

El host productivo puede tener activa una release histórica que es anterior al
mecanismo versionado moderno. Esa release no trae ``actualizador_publico.py`` ni
``instalador_host.py``, y su ``herramienta_despliegue.py`` valida ``release.json``
con un contrato de **cuatro** SPA. Una release moderna declara **cinco** SPA
(incluye Zócalo) y por eso la herramienta residente la rechaza: no puede
preparar, de forma canónica, la release que la reemplazaría.

Relajar o editar a mano esa herramienta histórica en producción no es una
opción. Este archivo es el puente mínimo para cruzar ese salto una sola vez.

Qué hace, en orden estricto
---------------------------

1. Resuelve por HTTPS público la publicación ``sis-leg-<SHA>`` de un commit y un
   árbol Git **exactos**, pedidos explícitamente por quien lo ejecuta.
2. Demuestra identidad y evidencia: tag, ``target_commitish``, exactamente tres
   assets, commit y tree contra la API Git, metadatos, intento histórico exacto
   de CI y su job ``Empaquetado · release productiva``.
3. Descarga paquete y sidecar a un temporal **privado**, comprueba SHA-256 y
   recorre el tar entero: allowlist, tipos de entrada, inventario de
   ``release.json`` y hash de cada archivo.
4. Recién entonces materializa en ese temporal los módulos mínimos de la
   **herramienta moderna de la propia release objetivo**, vuelve a verificar sus
   bytes contra el inventario y la ejecuta con el subcomando ``preparar``.

Ningún byte del paquete se ejecuta antes de terminar los pasos 1 a 3.

Qué **no** hace, por diseño
---------------------------

- no reimplementa la preparación: la hace la herramienta moderna verificada;
- no activa releases ni toca ``current``, ``previous`` o ``target-release``;
- no instala wrappers, unidades systemd, Nginx, sudoers, PolicyKit ni ``.desktop``;
- no reinicia servicios ni modifica configuración institucional o logs;
- no borra ni repara directorios parciales: los informa y se detiene;
- no usa ``git``, ``gh``, tokens, cookies ni cabeceras de autenticación.

Por qué no importa nada del repositorio
---------------------------------------

Tiene que poder copiarse como **archivo suelto** a un host cuya release activa es
histórica. Importar ``deploy.actualizador_publico`` o ``deploy.herramienta_despliegue``
significaría importar la versión vieja residente, que es justamente la que no
sirve. Por eso usa sólo biblioteca estándar de Python 3.14 y repite, de forma
deliberada y acotada, el contrato del canal público y del manifest moderno. Las
pruebas (``tests/test_bootstrap_publico.py``) comparan esas copias contra las
fuentes canónicas para que no puedan divergir sin romper la CI.

Transicional
------------

Una vez preparada una release moderna, las operaciones normales vuelven a usar
exclusivamente ``actualizador_publico.py``, ``herramienta_despliegue.py``,
``instalador_host.py`` y ``operaciones_host.py``. Este bootstrap no reemplaza al
actualizador normal y no debe incorporarse a ningún wrapper.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import IO, Any, Protocol, cast

# --------------------------------------------------------------------------
# Contrato del canal público. Copia deliberada de ``deploy/actualizador_publico.py``:
# las pruebas exigen igualdad exacta con esas constantes.
# --------------------------------------------------------------------------

REPOSITORIO = "martinebene/SIS-Leg"
RAMA_PUBLICACION = "main"
NOMBRE_WORKFLOW_CI = "CI"
NOMBRE_JOB_EMPAQUETADO = "Empaquetado · release productiva"
EVENTO_PUBLICABLE = "push"
PREFIJO_TAG = "sis-leg-"
FORMATO_METADATOS = "sis-leg-publicacion"
VERSION_METADATOS = 1

HOST_API = "api.github.com"
HOSTS_DESCARGA_PERMITIDOS = (
    "api.github.com",
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
)
ESQUEMA_PERMITIDO = "https"
TIEMPO_ESPERA_SEGUNDOS = 30.0
MAXIMO_REDIRECCIONES = 5
MAXIMO_BYTES_JSON = 8 * 1024 * 1024
MAXIMO_BYTES_METADATOS = 64 * 1024
MAXIMO_BYTES_SIDECAR = 4096
# Identificación neutra: distinta del actualizador para que un registro del lado
# de GitHub permita distinguir un uso del bootstrap. No incluye datos del host.
AGENTE_USUARIO = "sis-leg-bootstrap-publico/1.0"

# --------------------------------------------------------------------------
# Contrato del paquete moderno. Copia deliberada de ``validar_manifest`` y de
# ``extraer_paquete_seguro`` en ``deploy/herramienta_despliegue.py``. **No** es
# el contrato histórico de cuatro SPA: las pruebas lo verifican.
# --------------------------------------------------------------------------

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAXIMO_ARCHIVOS_TAR = 20_000
MAXIMO_BYTES_TAR = 2 * 1024 * 1024 * 1024
MAXIMO_BYTES_PAQUETE = MAXIMO_BYTES_TAR
MAXIMO_BYTES_MANIFEST = 10 * 1024 * 1024
MAXIMO_LONGITUD_RUTA = 512
RAICES_PERMITIDAS = frozenset({"app", "web", "deploy", "release.json"})
SPAS_CANONICAS = {
    "moderacion": "web/moderacion/index.html",
    "recinto": "web/recinto/index.html",
    "simulador": "web/simulador/index.html",
    "tecnico": "web/tecnico/index.html",
    "zocalo": "web/zocalo/index.html",
}
MANUAL_CANONICO = "web/manual/index.html"
PAQUETES_PYTHON_CANONICOS = ["sis-leg-backend", "sis-leg-device-bridge"]
RUTA_CONTRATO_CONFIGURACION = "deploy/contrato_configuracion.json"
ENTRADAS_OBLIGATORIAS = frozenset(
    {
        "app/pyproject.toml",
        "app/uv.lock",
        "app/apps/backend/pyproject.toml",
        "app/services/device-bridge/pyproject.toml",
        "web/moderacion/index.html",
        "web/recinto/index.html",
        "web/simulador/index.html",
        "web/tecnico/index.html",
        "web/zocalo/index.html",
        "web/manual/index.html",
        "deploy/systemd/sis-leg-backend.service",
        "deploy/systemd/sis-leg-device-bridge.service",
        "deploy/nginx/sis-leg.conf",
        "deploy/herramienta_despliegue.py",
        "deploy/validar_configuracion.py",
        RUTA_CONTRATO_CONFIGURACION,
    }
)

# --------------------------------------------------------------------------
# Delegación a la herramienta moderna
# --------------------------------------------------------------------------

# Módulos que necesita ``herramienta_despliegue.py preparar`` para arrancar: la
# herramienta importa ``deploy.configuracion_local`` y éste sólo biblioteca
# estándar. ``deploy/__init__.py`` hace de ``deploy`` un paquete regular. Una
# prueba recorre los imports reales para detectar si aparece otra dependencia.
HERRAMIENTA_DELEGADA = "deploy/herramienta_despliegue.py"
MODULOS_DELEGADOS = (
    "deploy/__init__.py",
    "deploy/configuracion_local.py",
    HERRAMIENTA_DELEGADA,
)
# Único subcomando que este bootstrap puede pedirle a la herramienta moderna.
SUBCOMANDO_DELEGADO = "preparar"
MARCADOR_PREPARADA = ".sis-leg-preparada.json"
RAIZ_PREDETERMINADA = Path("/opt/sis-leg")

# Clasificación read-only de ``releases/<SHA>`` antes y después de preparar.
DESTINO_AUSENTE = "AUSENTE"
DESTINO_YA_PREPARADA = "YA_PREPARADA"
DESTINO_PARCIAL = "PARCIAL"
DESTINO_INCOMPATIBLE = "INCOMPATIBLE"


class ErrorBootstrap(RuntimeError):
    """Falla segura del bootstrap.

    Toda falla deja el host como estaba antes de invocarlo, con una única
    excepción documentada: si la herramienta moderna ya empezó a preparar y falla,
    el directorio ``releases/<SHA>`` que ella haya dejado se conserva para
    diagnóstico, exactamente con la semántica de esa herramienta.
    """


def validar_sha(valor: str, nombre: str = "SHA") -> str:
    """Exige 40 hexadecimales en minúsculas: nunca prefijos ni nombres mutables."""

    if SHA_RE.fullmatch(valor) is None:
        raise ErrorBootstrap(f"{nombre} debe tener exactamente 40 hexadecimales minúsculos.")
    return valor


def validar_sha256(valor: str, nombre: str) -> str:
    """Exige un SHA-256 hexadecimal completo en minúsculas."""

    if SHA256_RE.fullmatch(valor) is None:
        raise ErrorBootstrap(f"{nombre} debe tener exactamente 64 hexadecimales minúsculos.")
    return valor


def sha256_archivo(ruta: Path) -> str:
    """Calcula el SHA-256 de un archivo leyendo en bloques."""

    calculador = hashlib.sha256()
    with ruta.open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
            calculador.update(bloque)
    return calculador.hexdigest()


def tag_publicacion(sha: str) -> str:
    """Tag determinista de la publicación de un commit."""

    return f"{PREFIJO_TAG}{validar_sha(sha)}"


def nombre_paquete(sha: str) -> str:
    """Nombre exacto del tar publicado para un commit."""

    return f"sis-leg-{validar_sha(sha)}.tar.gz"


def nombre_sidecar(sha: str) -> str:
    """Nombre exacto del sidecar SHA-256 del paquete."""

    return f"{nombre_paquete(sha)}.sha256"


def nombre_metadatos(sha: str) -> str:
    """Nombre exacto del asset que ata publicación, commit, árbol y CI."""

    return f"sis-leg-{validar_sha(sha)}.metadatos.json"


def assets_esperados(sha: str) -> tuple[str, str, str]:
    """Los tres assets canónicos de una publicación: ni uno más ni uno menos."""

    return (nombre_paquete(sha), nombre_sidecar(sha), nombre_metadatos(sha))


# --------------------------------------------------------------------------
# Frontera HTTP pública, sin credenciales
# --------------------------------------------------------------------------


class ClienteHttpPublico(Protocol):
    """Frontera de red reemplazable en pruebas por un doble sin red."""

    def obtener_json(self, url: str, *, maximo_bytes: int = MAXIMO_BYTES_JSON) -> Any: ...

    def descargar(self, url: str, destino: Path, *, maximo_bytes: int) -> int: ...


def validar_url_publica(url: str) -> None:
    """Exige HTTPS y un host de GitHub declarado **antes** de abrir la conexión.

    Las URL de descarga llegan dentro de JSON externo; validarlas acá impide que
    una respuesta manipulada desvíe la descarga a otro destino.
    """

    partes = urllib.parse.urlsplit(url)
    if partes.scheme != ESQUEMA_PERMITIDO:
        raise ErrorBootstrap(f"Sólo se acepta HTTPS para el canal público; se recibió {url!r}.")
    if partes.hostname is None or partes.hostname.lower() not in HOSTS_DESCARGA_PERMITIDOS:
        raise ErrorBootstrap(f"Host no permitido para el canal público: {url!r}")


class RedireccionSoloHttps(urllib.request.HTTPRedirectHandler):
    """Valida cada salto de redirección antes de seguirlo.

    Sin este handler ``urllib`` seguiría por su cuenta un ``302`` hacia ``http://``
    o hacia un host no declarado.
    """

    max_redirections = MAXIMO_REDIRECCIONES

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        validar_url_publica(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class ClienteHttpPublicoReal:
    """Cliente HTTPS de sólo lectura sin proxies implícitos, cookies ni autenticación.

    El ``opener`` se arma a mano: ``ProxyHandler({})`` anula los proxies tomados
    del entorno y no se agrega ningún manejador de cookies ni de credenciales.
    Los tamaños se controlan leyendo en bloques, sin confiar en ``Content-Length``.
    """

    def __init__(self, *, tiempo_espera: float = TIEMPO_ESPERA_SEGUNDOS) -> None:
        self.tiempo_espera = tiempo_espera
        self.abridor = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(),
            RedireccionSoloHttps(),
        )

    @staticmethod
    def construir_solicitud(url: str) -> urllib.request.Request:
        """Arma la solicitud exacta; es pública para probar que no lleva credenciales."""

        return urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": AGENTE_USUARIO,
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    def _abrir(self, url: str) -> Any:
        """Abre la conexión traduciendo errores de red a ``ErrorBootstrap``."""

        try:
            return self.abridor.open(self.construir_solicitud(url), timeout=self.tiempo_espera)
        except urllib.error.HTTPError as error:
            if error.code in (403, 429):
                raise ErrorBootstrap(
                    f"GitHub respondió HTTP {error.code} en {url}: probable límite de tasa de la "
                    "API pública. No se modificó nada; reintentar más tarde."
                ) from error
            raise ErrorBootstrap(f"GitHub respondió HTTP {error.code} en {url}.") from error
        except (urllib.error.URLError, OSError) as error:
            raise ErrorBootstrap(f"No se pudo consultar {url}: {error}") from error

    def obtener_json(self, url: str, *, maximo_bytes: int = MAXIMO_BYTES_JSON) -> Any:
        """Descarga y parsea un JSON acotado."""

        validar_url_publica(url)
        with self._abrir(url) as respuesta:
            crudo = respuesta.read(maximo_bytes + 1)
        if len(crudo) > maximo_bytes:
            raise ErrorBootstrap(f"La respuesta de {url} supera {maximo_bytes} bytes.")
        try:
            return json.loads(crudo.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ErrorBootstrap(f"{url} no devolvió JSON válido: {error}") from error

    def descargar(self, url: str, destino: Path, *, maximo_bytes: int) -> int:
        """Guarda la respuesta en ``destino`` cortando si excede el límite.

        Resultado: bytes escritos. ``destino`` siempre está dentro del temporal
        privado del bootstrap, nunca bajo la raíz de SIS-Leg.
        """

        validar_url_publica(url)
        escritos = 0
        with self._abrir(url) as respuesta, destino.open("xb") as salida:
            while True:
                bloque = respuesta.read(1024 * 1024)
                if not bloque:
                    break
                escritos += len(bloque)
                if escritos > maximo_bytes:
                    raise ErrorBootstrap(f"La descarga de {url} superó {maximo_bytes} bytes.")
                salida.write(bloque)
        return escritos


# --------------------------------------------------------------------------
# Lectura estricta de JSON externo
# --------------------------------------------------------------------------


def _objeto(datos: Any, contexto: str) -> dict[str, Any]:
    """Exige un objeto JSON antes de indexarlo."""

    if not isinstance(datos, dict):
        raise ErrorBootstrap(f"{contexto} no es un objeto JSON.")
    return cast(dict[str, Any], datos)


def _texto(datos: Mapping[str, Any], clave: str, contexto: str) -> str:
    """Extrae un campo textual obligatorio."""

    valor = datos.get(clave)
    if not isinstance(valor, str):
        raise ErrorBootstrap(f"{contexto} no declara {clave} textual.")
    return valor


def _entero(datos: Mapping[str, Any], clave: str, contexto: str) -> int:
    """Extrae un entero obligatorio rechazando ``bool`` (subclase de ``int``)."""

    valor = datos.get(clave)
    if not isinstance(valor, int) or isinstance(valor, bool):
        raise ErrorBootstrap(f"{contexto} no declara {clave} entero.")
    return valor


def _entero_positivo(datos: Mapping[str, Any], clave: str, contexto: str) -> int:
    """Entero positivo: se usa antes de concatenar identificadores en una URL."""

    valor = _entero(datos, clave, contexto)
    if valor <= 0:
        raise ErrorBootstrap(f"{contexto} declara {clave} no positivo: {valor}.")
    return valor


def _lista(datos: Mapping[str, Any], clave: str, contexto: str) -> list[Any]:
    """Exige que un campo sea una lista."""

    valor = datos.get(clave)
    if not isinstance(valor, list):
        raise ErrorBootstrap(f"{contexto} no declara {clave} como lista.")
    return cast(list[Any], valor)


# --------------------------------------------------------------------------
# Identidad de la publicación, del commit y de la CI
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AssetPublicado:
    """Un asset con nombre exacto, URL ya validada y tamaño declarado."""

    nombre: str
    url: str
    tamano: int


@dataclass(frozen=True, slots=True)
class EvidenciaCi:
    """Intento histórico exacto de CI y su job de empaquetado, ya demostrados."""

    run_id: int
    run_numero: int
    intento: int
    job_id: int


def validar_publicacion(datos: Mapping[str, Any], sha: str, url: str) -> dict[str, AssetPublicado]:
    """Valida la release pública del commit y devuelve sus tres assets.

    Errores: tag distinto, borrador o prerelease, ``target_commitish`` que no sea
    el SHA ni la rama publicable, asset inesperado, duplicado, incompleto,
    faltante o con URL fuera de los hosts declarados.

    ``target_commitish`` acepta también ``main`` porque GitHub puede normalizarlo
    al crear el tag (igual que el actualizador). La atadura fuerte al commit la dan
    el tag, la API Git, los metadatos, la CI y ``release.json``.
    """

    tag = tag_publicacion(sha)
    if _texto(datos, "tag_name", url) != tag:
        raise ErrorBootstrap(f"{url} devolvió un tag distinto de {tag}.")
    if datos.get("draft") is not False or datos.get("prerelease") is not False:
        raise ErrorBootstrap(f"La publicación {tag} es borrador o prerelease y no es consumible.")
    objetivo = _texto(datos, "target_commitish", url)
    if objetivo not in (sha, RAMA_PUBLICACION):
        raise ErrorBootstrap(f"La publicación {tag} apunta a {objetivo!r} y no al commit {sha}.")

    esperados = assets_esperados(sha)
    encontrados: dict[str, AssetPublicado] = {}
    for crudo in _lista(datos, "assets", url):
        asset = _objeto(crudo, url)
        nombre = _texto(asset, "name", url)
        if nombre not in esperados:
            raise ErrorBootstrap(f"La publicación {tag} incluye un asset inesperado: {nombre!r}")
        if nombre in encontrados:
            raise ErrorBootstrap(f"La publicación {tag} duplica el asset {nombre!r}.")
        if _texto(asset, "state", url) != "uploaded":
            raise ErrorBootstrap(f"El asset {nombre} de {tag} no está completamente subido.")
        destino = _texto(asset, "browser_download_url", url)
        validar_url_publica(destino)
        tamano = _entero(asset, "size", url)
        if tamano < 0:
            raise ErrorBootstrap(f"El asset {nombre} de {tag} declara un tamaño negativo.")
        encontrados[nombre] = AssetPublicado(nombre=nombre, url=destino, tamano=tamano)

    faltantes = [nombre for nombre in esperados if nombre not in encontrados]
    if faltantes:
        raise ErrorBootstrap(f"La publicación {tag} no expone los assets {faltantes}.")
    return encontrados


def verificar_commit_y_arbol(
    cliente: ClienteHttpPublico, *, sha: str, tree_sha: str, repositorio: str = REPOSITORIO
) -> None:
    """Demuestra con la API Git pública que el commit existe y tiene ese árbol.

    El tree SHA pedido es una identidad independiente del commit: se contrasta
    contra Git mismo, y no sólo contra archivos que viajan dentro de la release.
    """

    url = f"https://{HOST_API}/repos/{repositorio}/commits/{sha}"
    datos = _objeto(cliente.obtener_json(url), url)
    if _texto(datos, "sha", url) != sha:
        raise ErrorBootstrap(f"La API Git resolvió otro commit para {sha}.")
    commit = _objeto(datos.get("commit"), f"{url}.commit")
    arbol = _texto(_objeto(commit.get("tree"), f"{url}.commit.tree"), "sha", url)
    if arbol != tree_sha:
        raise ErrorBootstrap(
            f"El commit {sha} tiene el árbol {arbol} según Git y no el tree SHA pedido {tree_sha}."
        )


def verificar_evidencia_ci(
    cliente: ClienteHttpPublico,
    *,
    sha: str,
    run_id: int,
    intento: int,
    repositorio: str = REPOSITORIO,
) -> EvidenciaCi:
    """Demuestra el intento histórico exacto de CI y su único job de empaquetado.

    Se consulta ``/attempts/{intento}`` y no «la run»: una re-ejecución crea un
    intento nuevo, y la release inmutable nombra el intento que la publicó.

    Errores: el intento no es del workflow ``CI``, de un ``push`` a ``main``, de
    este SHA, no terminó en ``success``, o no tiene exactamente un job de
    empaquetado exitoso del mismo SHA, run e intento.
    """

    base = f"https://{HOST_API}/repos/{repositorio}/actions/runs/{run_id}/attempts/{intento}"
    run = _objeto(cliente.obtener_json(base), base)
    descripcion = f"el intento {intento} de la run {run_id}"
    comprobaciones = (
        ("name", NOMBRE_WORKFLOW_CI),
        ("event", EVENTO_PUBLICABLE),
        ("head_branch", RAMA_PUBLICACION),
        ("head_sha", sha),
        ("status", "completed"),
        ("conclusion", "success"),
    )
    for clave, esperado in comprobaciones:
        if _texto(run, clave, base) != esperado:
            raise ErrorBootstrap(f"{descripcion} no cumple {clave}={esperado!r}.")
    if _entero(run, "id", base) != run_id or _entero(run, "run_attempt", base) != intento:
        raise ErrorBootstrap(f"{descripcion} devolvió otra ejecución; no se mezclan evidencias.")
    run_numero = _entero(run, "run_number", base)

    url_jobs = f"{base}/jobs?per_page=100"
    datos_jobs = _objeto(cliente.obtener_json(url_jobs), url_jobs)
    jobs = _lista(datos_jobs, "jobs", url_jobs)
    if _entero(datos_jobs, "total_count", url_jobs) > len(jobs):
        raise ErrorBootstrap(f"{url_jobs} está paginado: no se puede demostrar un job único.")

    coincidencias: list[int] = []
    for crudo in jobs:
        job = _objeto(crudo, url_jobs)
        if _texto(job, "name", url_jobs) != NOMBRE_JOB_EMPAQUETADO:
            continue
        if (
            _texto(job, "conclusion", url_jobs) != "success"
            or _texto(job, "head_sha", url_jobs) != sha
            or _entero(job, "run_id", url_jobs) != run_id
            or _entero(job, "run_attempt", url_jobs) != intento
        ):
            raise ErrorBootstrap(
                f"El job {NOMBRE_JOB_EMPAQUETADO} de {descripcion} no es exitoso o pertenece a "
                "otra ejecución."
            )
        coincidencias.append(_entero(job, "id", url_jobs))
    if len(coincidencias) != 1:
        raise ErrorBootstrap(
            f"Se esperaba exactamente un job {NOMBRE_JOB_EMPAQUETADO} en {descripcion} y hay "
            f"{len(coincidencias)}."
        )
    return EvidenciaCi(
        run_id=run_id, run_numero=run_numero, intento=intento, job_id=coincidencias[0]
    )


def validar_metadatos(
    datos: Mapping[str, Any],
    *,
    sha: str,
    tree_sha: str,
    evidencia: EvidenciaCi,
    repositorio: str = REPOSITORIO,
) -> str:
    """Valida los metadatos contra el pedido y la CI ya demostrada.

    Resultado: el SHA-256 del paquete declarado, que después se compara con el
    sidecar y con el cálculo real sobre los bytes descargados.
    """

    contexto = nombre_metadatos(sha)
    if datos.get("formato") != FORMATO_METADATOS or datos.get("version_formato") != (
        VERSION_METADATOS
    ):
        raise ErrorBootstrap(f"{contexto} no declara el formato {FORMATO_METADATOS} soportado.")
    if _texto(datos, "repositorio", contexto) != repositorio:
        raise ErrorBootstrap(f"{contexto} corresponde a otro repositorio.")
    if _texto(datos, "commit_sha", contexto) != sha:
        raise ErrorBootstrap(f"{contexto} corresponde a otro commit.")
    if _texto(datos, "tag", contexto) != tag_publicacion(sha):
        raise ErrorBootstrap(f"{contexto} corresponde a otro tag.")
    if _texto(datos, "tree_sha", contexto) != tree_sha:
        raise ErrorBootstrap(f"{contexto} declara un tree SHA distinto del pedido.")

    ci = _objeto(datos.get("ci"), f"{contexto}.ci")
    esperados_ci: tuple[tuple[str, object], ...] = (
        ("run_id", evidencia.run_id),
        ("run_attempt", evidencia.intento),
        ("run_number", evidencia.run_numero),
        ("job_id", evidencia.job_id),
        ("workflow", NOMBRE_WORKFLOW_CI),
        ("job", NOMBRE_JOB_EMPAQUETADO),
        ("evento", EVENTO_PUBLICABLE),
        ("rama", RAMA_PUBLICACION),
    )
    for clave, esperado in esperados_ci:
        valor = ci.get(clave)
        if isinstance(valor, bool) or valor != esperado:
            raise ErrorBootstrap(f"{contexto}.ci.{clave} no coincide con la CI demostrada.")

    paquete = _objeto(datos.get("paquete"), f"{contexto}.paquete")
    if _texto(paquete, "nombre", contexto) != nombre_paquete(sha):
        raise ErrorBootstrap(f"{contexto} nombra un paquete distinto del esperado.")
    checksum = validar_sha256(_texto(paquete, "sha256", contexto), f"{contexto}.paquete.sha256")
    sidecar = _objeto(datos.get("sidecar"), f"{contexto}.sidecar")
    if _texto(sidecar, "nombre", contexto) != nombre_sidecar(sha):
        raise ErrorBootstrap(f"{contexto} nombra un sidecar distinto del esperado.")
    return checksum


def leer_sidecar(sidecar: Path, sha: str) -> str:
    """Lee el sidecar ``<sha256>  <nombre>`` exigiendo formato y nombre exactos."""

    try:
        linea = sidecar.read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError) as error:
        raise ErrorBootstrap(f"No se pudo leer el sidecar {sidecar.name}: {error}") from error
    partes = linea.split()
    if len(partes) != 2 or partes[1].lstrip("*") != nombre_paquete(sha):
        raise ErrorBootstrap("El sidecar SHA-256 no tiene el formato o nombre esperado.")
    return validar_sha256(partes[0], "El sidecar")


# --------------------------------------------------------------------------
# Paquete: allowlist, manifest moderno e inventario completo
# --------------------------------------------------------------------------


def validar_nombre_tar(nombre: str) -> PurePosixPath:
    """Rechaza rutas absolutas, traversal, ambiguas o fuera de la allowlist productiva."""

    ruta = PurePosixPath(nombre)
    if not nombre or nombre.startswith("/") or ruta.is_absolute():
        raise ErrorBootstrap(f"El tar contiene una ruta absoluta o vacía: {nombre!r}")
    if ruta.as_posix() != nombre:
        raise ErrorBootstrap(f"El tar contiene una ruta ambigua o no normalizada: {nombre!r}")
    if len(nombre) > MAXIMO_LONGITUD_RUTA or any(ord(caracter) < 32 for caracter in nombre):
        raise ErrorBootstrap(f"El tar contiene una ruta no permitida: {nombre!r}")
    if any(parte in {"", ".", ".."} for parte in ruta.parts):
        raise ErrorBootstrap(f"El tar contiene traversal o componentes ambiguos: {nombre!r}")
    if ruta.parts[0] not in RAICES_PERMITIDAS:
        raise ErrorBootstrap(f"La entrada no pertenece a la allowlist productiva: {nombre!r}")
    if ruta.parts[0] == "release.json" and len(ruta.parts) != 1:
        raise ErrorBootstrap("release.json debe ser un único archivo en la raíz del paquete.")
    return ruta


def validar_manifest_moderno(manifest: Mapping[str, Any], sha: str) -> dict[str, tuple[str, int]]:
    """Valida ``release.json`` con el contrato moderno de cinco SPA más manual.

    Resultado: inventario ``ruta -> (sha256, tamaño)``.

    Además de las entradas que exige la herramienta moderna, exige los módulos
    que el bootstrap va a ejecutar: si faltaran, no hay nada verificable que
    delegar y se falla antes de extraer.
    """

    if manifest.get("formato") != "sis-leg-release" or manifest.get("version_formato") != 1:
        raise ErrorBootstrap("Formato o versión de release no soportados.")
    if manifest.get("commit_sha") != sha:
        raise ErrorBootstrap("El SHA pedido no coincide con release.json.")
    arbol = manifest.get("tree_sha")
    if not isinstance(arbol, str) or SHA_RE.fullmatch(arbol) is None:
        raise ErrorBootstrap("release.json no declara un tree SHA Git completo y válido.")
    if manifest.get("python") != "3.14":
        raise ErrorBootstrap("La release no declara Python 3.14.")
    if manifest.get("spas") != SPAS_CANONICAS:
        raise ErrorBootstrap("release.json no declara las cinco SPA canónicas.")
    if manifest.get("manual") != MANUAL_CANONICO:
        raise ErrorBootstrap("release.json no declara el manual de usuario canónico.")
    if manifest.get("paquetes_python") != PAQUETES_PYTHON_CANONICOS:
        raise ErrorBootstrap("release.json no declara los paquetes Python canónicos.")
    archivos = manifest.get("archivos")
    if not isinstance(archivos, list):
        raise ErrorBootstrap("release.json no contiene un inventario de archivos.")

    inventario: dict[str, tuple[str, int]] = {}
    for crudo in cast(list[Any], archivos):
        entrada = _objeto(crudo, "Una entrada del inventario")
        ruta = entrada.get("ruta")
        checksum = entrada.get("sha256")
        tamano = entrada.get("tamano")
        if not isinstance(ruta, str) or ruta == "release.json":
            raise ErrorBootstrap("Ruta inválida en el inventario de release.")
        validar_nombre_tar(ruta)
        if ruta in inventario:
            raise ErrorBootstrap(f"Ruta duplicada en el inventario: {ruta}")
        if not isinstance(checksum, str) or SHA256_RE.fullmatch(checksum) is None:
            raise ErrorBootstrap(f"Checksum inválido en el inventario: {ruta}")
        if not isinstance(tamano, int) or isinstance(tamano, bool) or tamano < 0:
            raise ErrorBootstrap(f"Tamaño inválido en el inventario: {ruta}")
        inventario[ruta] = (checksum, tamano)

    faltantes = sorted((ENTRADAS_OBLIGATORIAS | set(MODULOS_DELEGADOS)) - inventario.keys())
    if faltantes:
        raise ErrorBootstrap(f"La release omite entradas obligatorias: {faltantes}")
    return inventario


def _leer_manifest(tar: tarfile.TarFile, miembro: tarfile.TarInfo) -> dict[str, Any]:
    """Lee ``release.json`` desde el tar, en memoria y con límite de tamaño."""

    if miembro.size > MAXIMO_BYTES_MANIFEST:
        raise ErrorBootstrap("release.json supera el tamaño máximo razonable.")
    archivo = tar.extractfile(miembro)
    if archivo is None:
        raise ErrorBootstrap("No se pudo leer release.json.")
    try:
        datos = json.loads(archivo.read().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ErrorBootstrap(f"release.json es inválido: {error}") from error
    return _objeto(datos, "release.json")


def _sha256_flujo(origen: IO[bytes]) -> tuple[str, int]:
    """Calcula SHA-256 y tamaño de un flujo sin escribirlo a disco."""

    calculador = hashlib.sha256()
    total = 0
    for bloque in iter(lambda: origen.read(1024 * 1024), b""):
        calculador.update(bloque)
        total += len(bloque)
    return calculador.hexdigest(), total


def inspeccionar_paquete(
    paquete: Path, sha: str
) -> tuple[dict[str, Any], dict[str, tuple[str, int]]]:
    """Recorre el tar completo sin extraerlo y exige coincidencia exacta con su inventario.

    Resultado: ``(manifest, inventario)``.

    Comprueba, en este orden: límites de cantidad y tamaño; cada nombre contra la
    allowlist; que cada entrada sea un archivo regular (se rechazan directorios,
    symlinks, hardlinks, dispositivos y FIFOs); duplicados; manifest moderno;
    igualdad exacta entre entradas del tar e inventario; y, por último, tamaño y
    SHA-256 de **cada** archivo leído desde el propio tar.

    Nada se escribe a disco: los hashes se calculan sobre el flujo descomprimido.
    """

    try:
        with tarfile.open(paquete, mode="r:gz") as tar:
            miembros = tar.getmembers()
            if len(miembros) > MAXIMO_ARCHIVOS_TAR:
                raise ErrorBootstrap("El tar supera la cantidad máxima de archivos permitida.")
            if sum(miembro.size for miembro in miembros) > MAXIMO_BYTES_TAR:
                raise ErrorBootstrap("El tar supera el tamaño total máximo permitido.")
            por_nombre: dict[str, tarfile.TarInfo] = {}
            for miembro in miembros:
                validar_nombre_tar(miembro.name)
                if miembro.name in por_nombre:
                    raise ErrorBootstrap(f"Entrada duplicada en el tar: {miembro.name}")
                if not miembro.isreg():
                    raise ErrorBootstrap(
                        f"Sólo se aceptan archivos regulares; entrada rechazada: {miembro.name}"
                    )
                por_nombre[miembro.name] = miembro

            if "release.json" not in por_nombre:
                raise ErrorBootstrap("El paquete no contiene release.json.")
            manifest = _leer_manifest(tar, por_nombre["release.json"])
            inventario = validar_manifest_moderno(manifest, sha)

            esperados = set(inventario) | {"release.json"}
            if set(por_nombre) != esperados:
                extras = sorted(set(por_nombre) - esperados)
                faltantes = sorted(esperados - set(por_nombre))
                raise ErrorBootstrap(
                    f"El tar no coincide con su inventario; extras={extras}, faltantes={faltantes}."
                )

            # Se recorre en el orden físico del tar y no en el del inventario: un
            # ``.tar.gz`` sólo se lee eficientemente hacia adelante, y volver atrás
            # obligaría a descomprimir otra vez desde el principio.
            for miembro in miembros:
                nombre = miembro.name
                if nombre == "release.json":
                    continue
                checksum, tamano = inventario[nombre]
                if miembro.size != tamano:
                    raise ErrorBootstrap(
                        f"El tamaño en el tar no coincide con el manifest: {nombre}"
                    )
                origen = tar.extractfile(miembro)
                if origen is None:
                    raise ErrorBootstrap(f"No se pudo leer {nombre} dentro del tar.")
                calculado, leidos = _sha256_flujo(origen)
                if leidos != tamano or calculado != checksum:
                    raise ErrorBootstrap(f"El contenido no coincide con el inventario: {nombre}")
    except (tarfile.TarError, OSError, EOFError) as error:
        raise ErrorBootstrap(f"No se pudo leer el paquete {paquete.name}: {error}") from error
    return manifest, inventario


def materializar_modulos(
    paquete: Path, inventario: Mapping[str, tuple[str, int]], destino: Path
) -> Path:
    """Escribe sólo los módulos delegados en ``destino`` y verifica sus bytes.

    Entradas:
        paquete: tar ya inspeccionado por :func:`inspeccionar_paquete`.
        inventario: el inventario de ``release.json`` de ese mismo paquete.
        destino: directorio vacío dentro del temporal privado.

    Resultado: ruta de la herramienta moderna lista para ejecutar.

    Aunque el tar ya fue verificado, se vuelve a comprobar tamaño y SHA-256 de
    cada archivo **tal como quedó escrito**: lo que se ejecuta es el archivo en
    disco, y ésa es la última oportunidad de negarse a ejecutarlo.
    """

    faltantes = [modulo for modulo in MODULOS_DELEGADOS if modulo not in inventario]
    if faltantes:
        raise ErrorBootstrap(f"El inventario no declara los módulos delegados {faltantes}.")
    try:
        with tarfile.open(paquete, mode="r:gz") as tar:
            for modulo in MODULOS_DELEGADOS:
                miembro = tar.getmember(modulo)
                if not miembro.isreg():
                    raise ErrorBootstrap(f"El módulo delegado no es un archivo regular: {modulo}")
                origen = tar.extractfile(miembro)
                if origen is None:
                    raise ErrorBootstrap(f"No se pudo leer el módulo delegado {modulo}.")
                ruta = destino.joinpath(*PurePosixPath(modulo).parts)
                ruta.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                with ruta.open("xb") as salida:
                    shutil.copyfileobj(origen, salida)
    except (tarfile.TarError, KeyError, OSError, EOFError) as error:
        raise ErrorBootstrap(
            f"No se pudieron materializar los módulos delegados: {error}"
        ) from error

    for modulo in MODULOS_DELEGADOS:
        ruta = destino.joinpath(*PurePosixPath(modulo).parts)
        checksum, tamano = inventario[modulo]
        if ruta.is_symlink() or not ruta.is_file():
            raise ErrorBootstrap(f"El módulo delegado no quedó como archivo regular: {modulo}")
        if ruta.stat().st_size != tamano or sha256_archivo(ruta) != checksum:
            raise ErrorBootstrap(
                f"El módulo delegado {modulo} no coincide con el inventario; no se ejecuta."
            )
    return destino.joinpath(*PurePosixPath(HERRAMIENTA_DELEGADA).parts)


# --------------------------------------------------------------------------
# Obtención y verificación completa
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReleaseVerificada:
    """Release pública totalmente verificada dentro del temporal privado."""

    sha: str
    tree_sha: str
    tag: str
    paquete: Path
    sidecar: Path
    paquete_sha256: str
    evidencia: EvidenciaCi
    inventario: Mapping[str, tuple[str, int]]


def _descargar_asset(
    cliente: ClienteHttpPublico, asset: AssetPublicado, destino: Path, *, maximo_bytes: int
) -> None:
    """Descarga un asset al temporal privado exigiendo el tamaño declarado."""

    if asset.tamano > maximo_bytes:
        raise ErrorBootstrap(
            f"El asset {asset.nombre} declara {asset.tamano} bytes y supera el máximo aceptado."
        )
    escritos = cliente.descargar(asset.url, destino, maximo_bytes=maximo_bytes)
    if escritos != asset.tamano:
        raise ErrorBootstrap(
            f"El asset {asset.nombre} se descargó incompleto: {escritos} bytes de {asset.tamano}."
        )


def obtener_release_verificada(
    cliente: ClienteHttpPublico,
    *,
    sha: str,
    tree_sha: str,
    temporal: Path,
    paquete_sha256: str | None = None,
    repositorio: str = REPOSITORIO,
) -> ReleaseVerificada:
    """Resuelve, descarga y verifica íntegramente la release pedida.

    Entradas:
        cliente: frontera HTTP pública.
        sha, tree_sha: identidades exactas pedidas por quien opera.
        temporal: directorio privado ya creado; aquí quedan paquete y sidecar.
        paquete_sha256: fijación opcional adicional del hash del paquete.

    Orden: de lo barato a lo caro. Publicación y assets; commit y árbol contra
    Git; metadatos; intento de CI y job; recién después paquete y sidecar; hash;
    inspección completa del tar. No ejecuta nada.
    """

    sha = validar_sha(sha, "El SHA pedido")
    tree_sha = validar_sha(tree_sha, "El tree SHA pedido")
    if paquete_sha256 is not None:
        validar_sha256(paquete_sha256, "El SHA-256 de paquete pedido")

    tag = tag_publicacion(sha)
    url = f"https://{HOST_API}/repos/{repositorio}/releases/tags/{urllib.parse.quote(tag, safe='')}"
    assets = validar_publicacion(_objeto(cliente.obtener_json(url), url), sha, url)
    verificar_commit_y_arbol(cliente, sha=sha, tree_sha=tree_sha, repositorio=repositorio)

    ruta_metadatos = temporal / nombre_metadatos(sha)
    _descargar_asset(
        cliente, assets[ruta_metadatos.name], ruta_metadatos, maximo_bytes=MAXIMO_BYTES_METADATOS
    )
    try:
        metadatos = _objeto(
            json.loads(ruta_metadatos.read_text(encoding="utf-8")), ruta_metadatos.name
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ErrorBootstrap(f"Los metadatos de {tag} no son JSON válido: {error}") from error
    ci_declarada = _objeto(metadatos.get("ci"), f"{ruta_metadatos.name}.ci")
    evidencia = verificar_evidencia_ci(
        cliente,
        sha=sha,
        run_id=_entero_positivo(ci_declarada, "run_id", ruta_metadatos.name),
        intento=_entero_positivo(ci_declarada, "run_attempt", ruta_metadatos.name),
        repositorio=repositorio,
    )
    checksum_declarado = validar_metadatos(
        metadatos, sha=sha, tree_sha=tree_sha, evidencia=evidencia, repositorio=repositorio
    )
    if paquete_sha256 is not None and checksum_declarado != paquete_sha256:
        raise ErrorBootstrap("El SHA-256 de paquete pedido no coincide con los metadatos.")

    paquete = temporal / nombre_paquete(sha)
    sidecar = temporal / nombre_sidecar(sha)
    _descargar_asset(cliente, assets[paquete.name], paquete, maximo_bytes=MAXIMO_BYTES_PAQUETE)
    _descargar_asset(cliente, assets[sidecar.name], sidecar, maximo_bytes=MAXIMO_BYTES_SIDECAR)
    checksum_sidecar = leer_sidecar(sidecar, sha)
    checksum_real = sha256_archivo(paquete)
    if not checksum_real == checksum_sidecar == checksum_declarado:
        raise ErrorBootstrap(
            f"Checksum incorrecto: calculado {checksum_real}, sidecar {checksum_sidecar}, "
            f"metadatos {checksum_declarado}. No se ejecuta nada del paquete."
        )

    manifest, inventario = inspeccionar_paquete(paquete, sha)
    if manifest.get("tree_sha") != tree_sha:
        raise ErrorBootstrap("El tree SHA de release.json no coincide con el pedido.")

    return ReleaseVerificada(
        sha=sha,
        tree_sha=tree_sha,
        tag=tag,
        paquete=paquete,
        sidecar=sidecar,
        paquete_sha256=checksum_real,
        evidencia=evidencia,
        inventario=inventario,
    )


# --------------------------------------------------------------------------
# Estado read-only del destino y temporal privado
# --------------------------------------------------------------------------


def exigir_python_compatible(version: tuple[int, int] | None = None) -> None:
    """Exige Python 3.14: la herramienta delegada usa este intérprete como base.

    ``version`` sólo se inyecta en pruebas; por omisión se usa el intérprete actual.
    """

    actual = (sys.version_info.major, sys.version_info.minor) if version is None else version
    if actual != (3, 14):
        raise ErrorBootstrap("El bootstrap requiere ejecutarse con Python 3.14.")


def validar_raiz(raiz: Path) -> Path:
    """Exige una raíz existente, real y distinta de ``/``; nunca la crea."""

    if raiz.is_symlink() or not raiz.is_dir():
        raise ErrorBootstrap(f"La raíz {raiz} no es un directorio existente y real.")
    resuelta = raiz.resolve()
    if resuelta == Path("/"):
        raise ErrorBootstrap("La raíz de SIS-Leg no puede ser /.")
    releases = resuelta / "releases"
    if releases.is_symlink() or (releases.exists() and not releases.is_dir()):
        raise ErrorBootstrap(f"{releases} existe pero no es un directorio real.")
    return resuelta


def clasificar_destino(raiz: Path, sha: str, tree_sha: str) -> tuple[str, str]:
    """Clasifica ``releases/<SHA>`` sin escribir nada.

    Resultado: ``(estado, detalle)`` con estado ``AUSENTE``, ``YA_PREPARADA``,
    ``PARCIAL`` o ``INCOMPATIBLE``.

    ``YA_PREPARADA`` exige marcador regular del mismo commit **y** árbol, y un
    ``release.json`` regular que supere el contrato moderno con ese mismo árbol.
    Cualquier otra combinación existente es ``PARCIAL`` (sin marcador) o
    ``INCOMPATIBLE``: nunca se borra ni se repara.
    """

    destino = raiz / "releases" / sha
    if not destino.exists() and not destino.is_symlink():
        return DESTINO_AUSENTE, f"{destino} no existe."
    if destino.is_symlink() or not destino.is_dir():
        return DESTINO_INCOMPATIBLE, f"{destino} existe pero no es un directorio real."
    marcador = destino / MARCADOR_PREPARADA
    if not marcador.exists() and not marcador.is_symlink():
        return DESTINO_PARCIAL, f"{destino} existe sin marcador de preparación."
    try:
        if marcador.is_symlink() or not marcador.is_file():
            raise ErrorBootstrap("el marcador no es un archivo regular")
        datos = _objeto(json.loads(marcador.read_text(encoding="utf-8")), "marcador")
        if datos.get("commit_sha") != sha or datos.get("tree_sha") != tree_sha:
            raise ErrorBootstrap("el marcador declara otro commit o árbol")
        manifest_ruta = destino / "release.json"
        if manifest_ruta.is_symlink() or not manifest_ruta.is_file():
            raise ErrorBootstrap("release.json no es un archivo regular")
        manifest = _objeto(json.loads(manifest_ruta.read_text(encoding="utf-8")), "release.json")
        validar_manifest_moderno(manifest, sha)
        if manifest.get("tree_sha") != tree_sha:
            raise ErrorBootstrap("release.json declara otro árbol")
    except (ErrorBootstrap, OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return DESTINO_INCOMPATIBLE, f"{destino} tiene un marcador incompatible: {error}"
    return DESTINO_YA_PREPARADA, f"{destino} ya está preparada para ese commit y árbol."


def crear_temporal_privado(directorio_base: Path | None, raiz: Path) -> Path:
    """Crea un temporal ``0700`` fuera de la raíz de SIS-Leg.

    ``tempfile.mkdtemp`` crea el directorio de forma atómica y sólo accesible por
    el usuario actual. Se rechaza una base dentro de la raíz: el bootstrap no
    escribe nada propio bajo ``/opt/sis-leg``.
    """

    base = (directorio_base or Path(tempfile.gettempdir())).resolve()
    if base.is_relative_to(raiz.resolve()):
        raise ErrorBootstrap(f"El directorio temporal {base} no puede estar dentro de {raiz}.")
    return Path(tempfile.mkdtemp(prefix="sis-leg-bootstrap-", dir=base))


def limpiar_temporal(temporal: Path) -> None:
    """Borra el temporal privado; si no puede, lo informa sin ocultarlo."""

    try:
        shutil.rmtree(temporal)
    except OSError as error:
        print(
            f"Advertencia: no se pudo borrar el temporal {temporal}: {error}",
            file=sys.stderr,
        )


# --------------------------------------------------------------------------
# Delegación y comandos
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResultadoHerramienta:
    """Código y salidas de la herramienta moderna, preservados para diagnóstico."""

    codigo: int
    salida: str
    error: str


EjecutorHerramienta = Callable[[Sequence[str], Path], ResultadoHerramienta]


def ejecutar_herramienta_real(argumentos: Sequence[str], directorio: Path) -> ResultadoHerramienta:
    """Ejecuta la herramienta como lista de argumentos, nunca mediante shell."""

    proceso = subprocess.run(
        list(argumentos), cwd=directorio, capture_output=True, text=True, check=False
    )
    return ResultadoHerramienta(proceso.returncode, proceso.stdout, proceso.stderr)


def argumentos_preparacion(
    *, python: Path, herramienta: Path, raiz: Path, release: ReleaseVerificada
) -> list[str]:
    """Arma el único comando delegado: ``herramienta_despliegue.py preparar``.

    ``-I`` aísla el intérprete: ignora ``PYTHONPATH`` y el site del usuario y no
    agrega el directorio del script a ``sys.path``; la herramienta agrega su
    propia raíz y así importa su ``deploy.configuracion_local`` materializado,
    nunca uno residente. ``-B`` evita escribir bytecode.
    """

    return [
        str(python),
        "-I",
        "-B",
        str(herramienta),
        "--raiz",
        str(raiz),
        SUBCOMANDO_DELEGADO,
        str(release.paquete),
        "--checksum",
        str(release.sidecar),
        "--sha",
        release.sha,
    ]


def _identidad_informe(release: ReleaseVerificada) -> dict[str, Any]:
    """Campos de identidad comunes a los informes JSON."""

    return {
        "release_sha": release.sha,
        "tree_sha": release.tree_sha,
        "tag": release.tag,
        "paquete_sha256": release.paquete_sha256,
        "ci_run_id": release.evidencia.run_id,
        "ci_run_number": release.evidencia.run_numero,
        "ci_run_attempt": release.evidencia.intento,
        "ci_job_id": release.evidencia.job_id,
    }


def diagnosticar(
    *,
    sha: str,
    tree_sha: str,
    raiz: Path = RAIZ_PREDETERMINADA,
    paquete_sha256: str | None = None,
    directorio_temporal: Path | None = None,
    cliente: ClienteHttpPublico | None = None,
    buscar_ejecutable: Callable[[str], str | None] = shutil.which,
) -> dict[str, Any]:
    """Readiness read-only: verifica todo sin preparar ni escribir bajo ``raiz``.

    Descarga y verifica la release completa en un temporal privado, materializa y
    verifica los módulos delegados **sin ejecutarlos**, y clasifica el destino.
    El temporal se borra siempre.

    Resultado: informe con ``listo_para_preparar`` verdadero sólo si la raíz es
    válida, ``uv`` está disponible (la herramienta moderna lo necesita) y el
    destino está ``AUSENTE`` o ``YA_PREPARADA``.

    Errores: ``ErrorBootstrap`` si la identidad de la release no se sostiene.
    """

    exigir_python_compatible()
    cliente = cliente or ClienteHttpPublicoReal()
    try:
        raiz_valida: Path | None = validar_raiz(raiz)
        detalle_raiz = f"{raiz} es un directorio válido."
    except ErrorBootstrap as error:
        raiz_valida = None
        detalle_raiz = str(error)

    temporal = crear_temporal_privado(directorio_temporal, raiz)
    try:
        release = obtener_release_verificada(
            cliente, sha=sha, tree_sha=tree_sha, temporal=temporal, paquete_sha256=paquete_sha256
        )
        materializar_modulos(release.paquete, release.inventario, temporal / "herramienta")
    finally:
        limpiar_temporal(temporal)

    if raiz_valida is None:
        estado, detalle_estado = DESTINO_INCOMPATIBLE, "Sin raíz válida no se evalúa el destino."
    else:
        estado, detalle_estado = clasificar_destino(raiz_valida, release.sha, release.tree_sha)
    uv = buscar_ejecutable("uv")
    listo = (
        raiz_valida is not None
        and uv is not None
        and estado in (DESTINO_AUSENTE, DESTINO_YA_PREPARADA)
    )
    return {
        "comando": "diagnosticar",
        **_identidad_informe(release),
        "modulos_delegados_verificados": list(MODULOS_DELEGADOS),
        "raiz": str(raiz),
        "raiz_valida": raiz_valida is not None,
        "detalle_raiz": detalle_raiz,
        "uv": uv,
        "estado_destino": estado,
        "detalle_destino": detalle_estado,
        "listo_para_preparar": listo,
    }


class ErrorPreparacionDelegada(ErrorBootstrap):
    """La herramienta moderna verificada falló; conserva su código y salidas."""

    def __init__(self, resultado: ResultadoHerramienta) -> None:
        super().__init__(
            f"La herramienta moderna falló al preparar (código {resultado.codigo}). "
            "No se tocó current ni target-release; un directorio parcial queda para inspección."
        )
        self.resultado = resultado


def preparar(
    *,
    sha: str,
    tree_sha: str,
    raiz: Path = RAIZ_PREDETERMINADA,
    paquete_sha256: str | None = None,
    directorio_temporal: Path | None = None,
    cliente: ClienteHttpPublico | None = None,
    ejecutor: EjecutorHerramienta = ejecutar_herramienta_real,
    python: Path | None = None,
) -> dict[str, Any]:
    """Prepara la release moderna delegando en su propia herramienta verificada.

    Pasos:

    1. Python 3.14, raíz válida y destino no ``PARCIAL``/``INCOMPATIBLE`` (antes
       de tocar la red);
    2. obtención y verificación íntegra en el temporal privado;
    3. si el destino ya está preparado y es compatible: informe idempotente, sin
       ejecutar nada ni reescribir;
    4. materialización y verificación de los módulos delegados;
    5. última clasificación del destino y ejecución de ``preparar``;
    6. comprobación final de que quedó ``YA_PREPARADA`` para ese commit y árbol.

    El temporal se borra siempre. Errores: ``ErrorBootstrap`` o
    ``ErrorPreparacionDelegada`` con la salida de la herramienta.
    """

    exigir_python_compatible()
    raiz_valida = validar_raiz(raiz)
    sha = validar_sha(sha, "El SHA pedido")
    tree_sha = validar_sha(tree_sha, "El tree SHA pedido")
    estado, detalle = clasificar_destino(raiz_valida, sha, tree_sha)
    if estado in (DESTINO_PARCIAL, DESTINO_INCOMPATIBLE):
        raise ErrorBootstrap(f"{detalle} Se requiere inspección administrativa; no se borra nada.")

    cliente = cliente or ClienteHttpPublicoReal()
    interprete = python or Path(sys.executable)
    temporal = crear_temporal_privado(directorio_temporal, raiz_valida)
    try:
        release = obtener_release_verificada(
            cliente, sha=sha, tree_sha=tree_sha, temporal=temporal, paquete_sha256=paquete_sha256
        )
        estado, detalle = clasificar_destino(raiz_valida, sha, tree_sha)
        if estado == DESTINO_YA_PREPARADA:
            return {
                "comando": "preparar",
                **_identidad_informe(release),
                "resultado": "IDEMPOTENTE",
                "release": str(raiz_valida / "releases" / sha),
                "detalle": detalle,
            }
        herramienta = materializar_modulos(
            release.paquete, release.inventario, temporal / "herramienta"
        )
        # Última lectura antes de ejecutar: si alguien creó el directorio entre
        # la primera clasificación y ahora, se aborta en lugar de competir.
        estado, detalle = clasificar_destino(raiz_valida, sha, tree_sha)
        if estado != DESTINO_AUSENTE:
            raise ErrorBootstrap(f"{detalle} El destino cambió durante la verificación; se aborta.")
        resultado = ejecutor(
            argumentos_preparacion(
                python=interprete, herramienta=herramienta, raiz=raiz_valida, release=release
            ),
            temporal,
        )
        if resultado.codigo != 0:
            raise ErrorPreparacionDelegada(resultado)
    finally:
        limpiar_temporal(temporal)

    estado, detalle = clasificar_destino(raiz_valida, sha, tree_sha)
    if estado != DESTINO_YA_PREPARADA:
        raise ErrorBootstrap(
            "La herramienta moderna terminó sin error pero el destino no quedó preparado: "
            f"{detalle}"
        )
    return {
        "comando": "preparar",
        **_identidad_informe(release),
        "resultado": "PREPARADA",
        "release": str(raiz_valida / "releases" / sha),
        "salida_herramienta": resultado.salida.strip(),
    }


def crear_parser() -> argparse.ArgumentParser:
    """CLI con sólo dos subcomandos: ``diagnosticar`` (read-only) y ``preparar``.

    No existe ningún subcomando para activar, fijar ``target-release``, instalar
    wrappers ni conmutar.
    """

    parser = argparse.ArgumentParser(
        description=(
            "Bootstrap transicional de SIS-Leg: verifica una release pública exacta y la "
            "prepara con su propia herramienta moderna. No activa ni conmuta."
        )
    )
    sub = parser.add_subparsers(dest="comando", required=True)
    for nombre, ayuda in (
        ("diagnosticar", "Verifica release y host sin escribir bajo la raíz."),
        ("preparar", "Verifica y prepara releases/<SHA> delegando en la herramienta moderna."),
    ):
        comando = sub.add_parser(nombre, help=ayuda)
        comando.add_argument("--sha", required=True, help="Commit exacto de la release.")
        comando.add_argument("--tree-sha", required=True, help="Árbol Git exacto del commit.")
        comando.add_argument("--paquete-sha256", default=None, help="Fijación opcional del hash.")
        comando.add_argument("--raiz", type=Path, default=RAIZ_PREDETERMINADA)
        comando.add_argument("--directorio-temporal", type=Path, default=None)
    return parser


def main(argumentos: Sequence[str] | None = None) -> int:
    """Imprime un informe JSON; cualquier falla sale con código 1 por stderr."""

    opciones = crear_parser().parse_args(argumentos)
    comunes: dict[str, Any] = {
        "sha": opciones.sha,
        "tree_sha": opciones.tree_sha,
        "raiz": opciones.raiz,
        "paquete_sha256": opciones.paquete_sha256,
        "directorio_temporal": opciones.directorio_temporal,
    }
    try:
        if opciones.comando == "diagnosticar":
            informe = diagnosticar(**comunes)
        else:
            informe = preparar(**comunes)
    except ErrorPreparacionDelegada as error:
        # Se reproduce la salida de la herramienta moderna tal cual: su
        # diagnóstico es la información útil para decidir qué inspeccionar.
        if error.resultado.salida:
            print(error.resultado.salida, file=sys.stderr, end="")
        if error.resultado.error:
            print(error.resultado.error, file=sys.stderr, end="")
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except (ErrorBootstrap, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(informe, ensure_ascii=False, indent=2))
    if opciones.comando == "diagnosticar" and not informe["listo_para_preparar"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
