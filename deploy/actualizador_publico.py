"""Canal público de releases por SHA, sin credenciales en el host (WP-100).

¿Por qué existe este módulo?
----------------------------

Hasta WP-099 el mecanismo «Actualizar SIS-Leg» necesitaba ``gh`` autenticado
para leer las runs de GitHub Actions y bajar el artifact de la CI. Eso obligaba
a guardar credenciales de GitHub en la máquina institucional sólo para consumir
software que el repositorio ya publica en abierto.

WP-100 reemplaza ese transporte por un canal **público**: cada push a ``main``
cuya CI completa termine en ``success`` publica una GitHub Release inmutable con
tag determinista ``sis-leg-<SHA>``, que contiene el paquete, su sidecar SHA-256
y un archivo de metadatos que ata publicación, commit, árbol Git y run de CI.

Este módulo es el lado **consumidor** de ese canal. Su contrato es estricto:

- nunca envía cabecera de autenticación, ni token, ni cookie;
- sólo habla HTTPS y sólo con hosts de GitHub declarados;
- no sigue redirecciones hacia esquemas distintos de HTTPS;
- aplica timeout y tamaño máximo a cada respuesta;
- descarga siempre a temporales y promueve sólo lo que validó;
- no construye comandos de shell con datos que vienen de GitHub.

Reparto de responsabilidades
----------------------------

Este módulo se ocupa de **transporte y selección**: qué SHA, qué run, qué job,
qué publicación y qué assets. La **validez** de la release sigue decidiéndola la
herramienta canónica: ``verificar_checksum``, ``validar_manifest`` y, más tarde,
``extraer_paquete_seguro`` dentro de ``preparar``. No hay acá un segundo motor de
validación de tar, manifest o checksum; se importan los que ya existen.

Por eso la dependencia va en un solo sentido: este módulo importa
``herramienta_despliegue`` y la herramienta no lo importa a él.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

# Producción invoca este módulo como script suelto desde la release
# (``python3.14 /opt/sis-leg/current/deploy/actualizador_publico.py ...``). En esa
# forma Python agrega ``deploy/`` a ``sys.path`` y no la raíz de la release, así
# que el paquete ``deploy`` todavía no sería importable. Se hace explícita esa raíz
# con el mismo criterio que ``deploy/herramienta_despliegue.py``.
RAIZ_PARA_IMPORTS = Path(__file__).resolve().parents[1]
if str(RAIZ_PARA_IMPORTS) not in sys.path:
    sys.path.insert(0, str(RAIZ_PARA_IMPORTS))

from deploy.herramienta_despliegue import (  # noqa: E402 - raíz preparada arriba
    MAXIMO_BYTES_TAR,
    ErrorDespliegue,
    inspeccionar_manifest_paquete,
    sha256_archivo,
    validar_sha,
    verificar_checksum,
)

# --------------------------------------------------------------------------
# Contrato público del canal. Estas constantes las comparte el publicador
# (`scripts/publicar_release_publica.py`) para que productor y consumidor no
# puedan desincronizarse: hay una sola definición de cada nombre.
# --------------------------------------------------------------------------

REPOSITORIO_PREDETERMINADO = "martinebene/SIS-Leg"
RAMA_PUBLICACION = "main"
NOMBRE_WORKFLOW_CI = "CI"
NOMBRE_JOB_EMPAQUETADO = "Empaquetado · release productiva"
EVENTO_PUBLICABLE = "push"
PREFIJO_TAG = "sis-leg-"

FORMATO_METADATOS = "sis-leg-publicacion"
VERSION_METADATOS = 1

HOST_API = "api.github.com"
# Hosts a los que GitHub redirige la descarga real de un asset público. La lista
# es corta a propósito: una redirección hacia cualquier otro destino se rechaza
# aunque sea HTTPS, porque el contrato dice de dónde se baja una release.
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
# El paquete comparte el techo que la herramienta ya aplica al tar extraído: no
# tiene sentido aceptar una descarga que después sería rechazada al abrirse.
MAXIMO_BYTES_PAQUETE = MAXIMO_BYTES_TAR
# Identificación neutra y sin datos del host. No se envía ninguna otra cabecera.
AGENTE_USUARIO = "sis-leg-actualizador-publico/1.0"


class ErrorActualizadorPublico(RuntimeError):
    """Falla segura y accionable del canal público de releases.

    Cualquiera de estas fallas debe dejar la instalación exactamente como
    estaba: sin ``current`` nuevo, sin servicios reiniciados y sin un artefacto
    parcial que alguien pueda confundir con una release válida.
    """


def nombre_paquete(sha: str) -> str:
    """Nombre exacto del tar para un SHA. No existe un asset ``latest``."""

    return f"sis-leg-{validar_sha(sha)}.tar.gz"


def nombre_sidecar(sha: str) -> str:
    """Nombre exacto del sidecar SHA-256, derivado del nombre del paquete."""

    return f"{nombre_paquete(sha)}.sha256"


def nombre_metadatos(sha: str) -> str:
    """Nombre exacto del archivo que vincula publicación, commit, árbol y CI."""

    return f"sis-leg-{validar_sha(sha)}.metadatos.json"


def tag_publicacion(sha: str) -> str:
    """Tag determinista de la publicación pública de ese SHA."""

    return f"{PREFIJO_TAG}{validar_sha(sha)}"


def assets_esperados(sha: str) -> tuple[str, str, str]:
    """Los tres nombres que una publicación válida debe tener, ni uno más."""

    return (nombre_paquete(sha), nombre_sidecar(sha), nombre_metadatos(sha))


# --------------------------------------------------------------------------
# Frontera HTTP inyectable
# --------------------------------------------------------------------------


class ClienteHttpPublico(Protocol):
    """Frontera de red del actualizador, reemplazable en pruebas.

    Se define como ``Protocol`` y no como clase base para que un doble de
    pruebas no herede nada del cliente real: si el doble implementa estos dos
    métodos, alcanza. Así las pruebas pueden ejercitar todos los caminos de
    error de GitHub sin tocar la red.
    """

    def obtener_json(self, url: str, *, maximo_bytes: int = MAXIMO_BYTES_JSON) -> Any: ...

    def descargar(self, url: str, destino: Path, *, maximo_bytes: int) -> int: ...


def validar_url_publica(url: str, *, hosts_permitidos: Sequence[str]) -> None:
    """Exige HTTPS y un host declarado antes de abrir cualquier conexión.

    Se valida la URL **antes** de usarla y no solamente al final: una URL que
    viene dentro de un JSON de GitHub es un dato externo, y el contrato dice de
    qué hosts se baja una release de SIS-Leg.

    Errores:
        ErrorActualizadorPublico si el esquema no es HTTPS o el host no está en
        la lista declarada.
    """

    partes = urllib.parse.urlsplit(url)
    if partes.scheme != ESQUEMA_PERMITIDO:
        raise ErrorActualizadorPublico(
            f"Sólo se acepta {ESQUEMA_PERMITIDO} para el canal público; se recibió {url!r}."
        )
    if partes.hostname is None or partes.hostname.lower() not in hosts_permitidos:
        raise ErrorActualizadorPublico(f"Host no permitido para el canal público: {url!r}")


class RedireccionSoloHttps(urllib.request.HTTPRedirectHandler):
    """Redirecciones restringidas a HTTPS y a los hosts declarados.

    ``urllib`` sigue redirecciones por su cuenta. Sin este handler, una
    respuesta ``302`` hacia ``http://`` degradaría la descarga a texto plano sin
    que el código llamador se enterara. Acá se valida cada salto y se aborta en
    el momento, antes de que se abra la conexión nueva.
    """

    # ``max_redirections`` es un atributo de clase en ``urllib``: se fija acá y no
    # en el constructor, que es donde Python permite reasignarlo.
    max_redirections = MAXIMO_REDIRECCIONES

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        validar_url_publica(newurl, hosts_permitidos=HOSTS_DESCARGA_PERMITIDOS)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class ClienteHttpPublicoReal:
    """Cliente HTTPS de solo lectura, sin credenciales de ningún tipo.

    Decisiones deliberadas:

    - el ``opener`` se construye a mano y **no** incluye manejo de proxies: el
      contrato exige hablar HTTPS directo con GitHub, y un proxy interpuesto
      podría terminar la TLS antes de tiempo. Si alguna instalación futura
      necesitara proxy, es una decisión de WP-101 y de su HUMAN_GATE, no un
      comportamiento implícito de este módulo;
    - no se instala ningún manejador de cookies ni de autenticación;
    - el tamaño se controla leyendo en bloques, sin confiar en
      ``Content-Length``, que es un dato del servidor.
    """

    def __init__(self, *, tiempo_espera: float = TIEMPO_ESPERA_SEGUNDOS) -> None:
        self.tiempo_espera = tiempo_espera
        # ``abridor`` es público a propósito: las pruebas lo reemplazan para
        # ejercitar respuestas HTTP reales sin salir a la red.
        self.abridor = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(),
            RedireccionSoloHttps(),
        )

    @staticmethod
    def construir_solicitud(url: str) -> urllib.request.Request:
        """Arma la solicitud exacta que viaja a GitHub.

        Es un método aparte y público para que una prueba pueda inspeccionar las
        cabeceras reales y demostrar que no se envía ``Authorization`` ni
        ``Cookie``: la ausencia de credenciales es un requisito del WP, no un
        detalle de implementación.
        """

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
        """Abre la conexión traduciendo los errores de GitHub a mensajes útiles."""

        try:
            return self.abridor.open(self.construir_solicitud(url), timeout=self.tiempo_espera)
        except urllib.error.HTTPError as error:
            if error.code in (403, 429):
                raise ErrorActualizadorPublico(
                    f"GitHub respondió HTTP {error.code} en {url}: probable límite de tasa de la "
                    "API pública. No se modificó nada; reintentar más tarde."
                ) from error
            raise ErrorActualizadorPublico(
                f"GitHub respondió HTTP {error.code} en {url}."
            ) from error
        except (urllib.error.URLError, OSError) as error:
            raise ErrorActualizadorPublico(f"No se pudo consultar {url}: {error}") from error

    def obtener_json(self, url: str, *, maximo_bytes: int = MAXIMO_BYTES_JSON) -> Any:
        """Descarga y parsea un JSON acotado del API público de GitHub."""

        validar_url_publica(url, hosts_permitidos=HOSTS_DESCARGA_PERMITIDOS)
        with self._abrir(url) as respuesta:
            crudo = respuesta.read(maximo_bytes + 1)
        if len(crudo) > maximo_bytes:
            raise ErrorActualizadorPublico(f"La respuesta de {url} supera {maximo_bytes} bytes.")
        try:
            return json.loads(crudo.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ErrorActualizadorPublico(f"{url} no devolvió JSON válido: {error}") from error

    def descargar(self, url: str, destino: Path, *, maximo_bytes: int) -> int:
        """Guarda la respuesta en ``destino`` cortando si excede el límite.

        Resultado: cantidad de bytes escritos.

        Efectos laterales: crea ``destino``. El llamador siempre pasa un archivo
        temporal; promover al nombre definitivo es decisión suya y ocurre recién
        después de validar.
        """

        validar_url_publica(url, hosts_permitidos=HOSTS_DESCARGA_PERMITIDOS)
        escritos = 0
        with self._abrir(url) as respuesta, destino.open("wb") as salida:
            while True:
                bloque = respuesta.read(1024 * 1024)
                if not bloque:
                    break
                escritos += len(bloque)
                if escritos > maximo_bytes:
                    raise ErrorActualizadorPublico(
                        f"La descarga de {url} superó {maximo_bytes} bytes y se abortó."
                    )
                salida.write(bloque)
        return escritos


# --------------------------------------------------------------------------
# Selección determinista: SHA -> run -> job -> publicación -> assets
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunCi:
    """La run de CI exacta que habilitó una publicación."""

    identificador: int
    numero: int
    intento: int
    head_sha: str
    workflow: str


@dataclass(frozen=True, slots=True)
class JobCi:
    """El job de empaquetado exacto dentro de esa run."""

    identificador: int
    nombre: str
    head_sha: str


@dataclass(frozen=True, slots=True)
class AssetPublicado:
    """Un asset público con su nombre exacto y su URL de descarga validada."""

    nombre: str
    url: str
    tamano: int


@dataclass(frozen=True, slots=True)
class PublicacionPublica:
    """La release pública resuelta para un SHA, con sus tres assets."""

    tag: str
    commit_sha: str
    assets: Mapping[str, AssetPublicado]


@dataclass(frozen=True, slots=True)
class ReleaseDescargada:
    """Resultado verificado y listo para entregar a ``preparar``."""

    commit_sha: str
    tree_sha: str
    tag: str
    paquete: Path
    sidecar: Path
    metadatos: Path
    run_ci: RunCi
    job_ci: JobCi


def _texto(datos: Mapping[str, Any], clave: str, contexto: str) -> str:
    """Extrae un campo textual obligatorio de una respuesta de GitHub."""

    valor = datos.get(clave)
    if not isinstance(valor, str):
        raise ErrorActualizadorPublico(f"{contexto} no declara {clave} textual.")
    return valor


def _entero(datos: Mapping[str, Any], clave: str, contexto: str) -> int:
    """Extrae un entero obligatorio rechazando ``bool``, que es subclase de int."""

    valor = datos.get(clave)
    if not isinstance(valor, int) or isinstance(valor, bool):
        raise ErrorActualizadorPublico(f"{contexto} no declara {clave} entero.")
    return valor


def _objeto(datos: Any, contexto: str) -> dict[str, Any]:
    """Exige que una respuesta sea un objeto JSON antes de indexarla."""

    if not isinstance(datos, dict):
        raise ErrorActualizadorPublico(f"{contexto} no devolvió un objeto JSON.")
    return cast(dict[str, Any], datos)


def _lista(datos: Mapping[str, Any], clave: str, contexto: str) -> list[Any]:
    """Exige que un campo de colección sea realmente una lista."""

    valor = datos.get(clave)
    if not isinstance(valor, list):
        raise ErrorActualizadorPublico(f"{contexto} no declara {clave} como lista.")
    return cast(list[Any], valor)


def _validar_repositorio(repositorio: str) -> str:
    """Acepta sólo ``propietario/nombre`` con caracteres seguros para una URL.

    No es una restricción cosmética: el nombre se concatena en la URL del API, y
    permitir barras extra o caracteres codificables abriría la puerta a apuntar
    la consulta a otro recurso.
    """

    partes = repositorio.split("/")
    if len(partes) != 2 or not all(partes):
        raise ErrorActualizadorPublico(f"Repositorio inválido: {repositorio!r}")
    permitidos = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._")
    if any(caracter not in permitidos for parte in partes for caracter in parte):
        raise ErrorActualizadorPublico(f"Repositorio con caracteres no permitidos: {repositorio!r}")
    return repositorio


def resolver_sha_main(
    cliente: ClienteHttpPublico,
    *,
    repositorio: str = REPOSITORIO_PREDETERMINADO,
    rama: str = RAMA_PUBLICACION,
) -> str:
    """Paso 1: resuelve el SHA completo actual de ``main`` por recurso público.

    Se consulta el commit de la rama, no una lista de tags: el contrato dice que
    la versión candidata es la cabeza de ``main``, y el SHA resuelto acá es el
    único que se usará en todos los pasos siguientes.
    """

    _validar_repositorio(repositorio)
    url = f"https://{HOST_API}/repos/{repositorio}/commits/{urllib.parse.quote(rama, safe='')}"
    datos = _objeto(cliente.obtener_json(url), url)
    return validar_sha(_texto(datos, "sha", url))


def seleccionar_run_ci(
    cliente: ClienteHttpPublico,
    sha: str,
    *,
    repositorio: str = REPOSITORIO_PREDETERMINADO,
    rama: str = RAMA_PUBLICACION,
) -> RunCi:
    """Paso 2: exige una run de ``push`` sobre ``main`` para ese SHA exacto.

    Los filtros de la query son una optimización, no una garantía: cada campo se
    vuelve a comprobar en código sobre la respuesta. Una run de ``pull_request``
    se rechaza aunque comparta SHA, porque valida un merge hipotético y no el
    contenido que quedó en ``main``.

    Si hay varias runs válidas para el mismo SHA —por ejemplo, una re-ejecución
    manual— se elige de forma determinista la de mayor ``run_number`` y, ante
    empate, la de mayor identificador. Si la respuesta viene paginada no se puede
    demostrar que se vio el conjunto completo, así que se aborta.
    """

    sha = validar_sha(sha)
    _validar_repositorio(repositorio)
    consulta = urllib.parse.urlencode(
        {
            "head_sha": sha,
            "event": EVENTO_PUBLICABLE,
            "branch": rama,
            "status": "completed",
            "per_page": "100",
        }
    )
    url = f"https://{HOST_API}/repos/{repositorio}/actions/runs?{consulta}"
    datos = _objeto(cliente.obtener_json(url), url)
    runs = _lista(datos, "workflow_runs", url)
    total = _entero(datos, "total_count", url)
    if total > len(runs):
        raise ErrorActualizadorPublico(
            f"{url} devolvió {len(runs)} runs de {total}: no se puede demostrar una elección "
            "única y se aborta."
        )

    candidatas: list[RunCi] = []
    for cruda in runs:
        run = _objeto(cruda, url)
        if (
            _texto(run, "head_sha", url) != sha
            or _texto(run, "event", url) != EVENTO_PUBLICABLE
            or _texto(run, "head_branch", url) != rama
            or _texto(run, "status", url) != "completed"
            or _texto(run, "conclusion", url) != "success"
            or _texto(run, "name", url) != NOMBRE_WORKFLOW_CI
        ):
            continue
        candidatas.append(
            RunCi(
                identificador=_entero(run, "id", url),
                numero=_entero(run, "run_number", url),
                intento=_entero(run, "run_attempt", url),
                head_sha=sha,
                workflow=NOMBRE_WORKFLOW_CI,
            )
        )

    if not candidatas:
        raise ErrorActualizadorPublico(
            f"No hay una run de CI de tipo {EVENTO_PUBLICABLE} sobre {rama} completada con "
            f"éxito para {sha}. No hay release productiva nueva disponible."
        )
    return max(candidatas, key=lambda run: (run.numero, run.identificador))


def verificar_job_empaquetado(
    cliente: ClienteHttpPublico,
    run: RunCi,
    *,
    repositorio: str = REPOSITORIO_PREDETERMINADO,
) -> JobCi:
    """Paso 3: exige el job exacto ``Empaquetado · release productiva`` exitoso.

    La coincidencia de nombre es exacta y sensible a mayúsculas y acentos: un
    job parecido no es el job. Además se comprueba que el job pertenezca al
    mismo ``head_sha``, para que no se mezclen datos de dos SHAs distintos.
    """

    _validar_repositorio(repositorio)
    url = (
        f"https://{HOST_API}/repos/{repositorio}/actions/runs/{run.identificador}/jobs?per_page=100"
    )
    datos = _objeto(cliente.obtener_json(url), url)
    jobs = _lista(datos, "jobs", url)
    total = _entero(datos, "total_count", url)
    if total > len(jobs):
        raise ErrorActualizadorPublico(
            f"{url} devolvió {len(jobs)} jobs de {total}: no se puede demostrar que el job de "
            "empaquetado exista una sola vez y se aborta."
        )

    coincidencias: list[JobCi] = []
    for cruda in jobs:
        job = _objeto(cruda, url)
        if _texto(job, "name", url) != NOMBRE_JOB_EMPAQUETADO:
            continue
        if _texto(job, "conclusion", url) != "success":
            raise ErrorActualizadorPublico(
                f"El job {NOMBRE_JOB_EMPAQUETADO} de la run {run.identificador} no terminó en "
                "success."
            )
        head_sha = _texto(job, "head_sha", url)
        if head_sha != run.head_sha:
            raise ErrorActualizadorPublico(
                f"El job {NOMBRE_JOB_EMPAQUETADO} declara head_sha {head_sha} y la run "
                f"{run.head_sha}: no se mezclan SHAs distintos."
            )
        coincidencias.append(
            JobCi(
                identificador=_entero(job, "id", url),
                nombre=NOMBRE_JOB_EMPAQUETADO,
                head_sha=head_sha,
            )
        )

    if len(coincidencias) != 1:
        raise ErrorActualizadorPublico(
            f"Se esperaba exactamente un job {NOMBRE_JOB_EMPAQUETADO} en la run "
            f"{run.identificador} y se encontraron {len(coincidencias)}."
        )
    return coincidencias[0]


def resolver_publicacion(
    cliente: ClienteHttpPublico,
    sha: str,
    *,
    repositorio: str = REPOSITORIO_PREDETERMINADO,
) -> PublicacionPublica:
    """Paso 4 y 5: resuelve la publicación del SHA y exige nombres exactos.

    Se consulta por tag y no por «última release»: pedir ``latest`` devolvería
    lo que GitHub considere más nuevo, que no tiene por qué ser el SHA que el
    actualizador resolvió al principio.

    La publicación debe declarar exactamente los tres assets derivados del SHA.
    Un asset de más, uno de menos o un nombre repetido invalidan la publicación
    entera: son señales de una publicación parcial o manipulada.
    """

    sha = validar_sha(sha)
    _validar_repositorio(repositorio)
    tag = tag_publicacion(sha)
    url = f"https://{HOST_API}/repos/{repositorio}/releases/tags/{urllib.parse.quote(tag, safe='')}"
    datos = _objeto(cliente.obtener_json(url), url)

    if _texto(datos, "tag_name", url) != tag:
        raise ErrorActualizadorPublico(f"{url} devolvió un tag distinto del solicitado.")
    if datos.get("draft") is not False or datos.get("prerelease") is not False:
        raise ErrorActualizadorPublico(
            f"La publicación {tag} es borrador o prerelease y no es consumible."
        )
    if _texto(datos, "target_commitish", url) != sha:
        raise ErrorActualizadorPublico(
            f"La publicación {tag} no apunta al commit {sha}; no se mezclan publicaciones."
        )

    esperados = assets_esperados(sha)
    encontrados: dict[str, AssetPublicado] = {}
    for cruda in _lista(datos, "assets", url):
        asset = _objeto(cruda, url)
        nombre = _texto(asset, "name", url)
        if nombre not in esperados:
            raise ErrorActualizadorPublico(
                f"La publicación {tag} incluye un asset inesperado: {nombre!r}"
            )
        if nombre in encontrados:
            raise ErrorActualizadorPublico(f"La publicación {tag} duplica el asset {nombre!r}.")
        if _texto(asset, "state", url) != "uploaded":
            raise ErrorActualizadorPublico(
                f"El asset {nombre} de {tag} no está completamente subido."
            )
        destino = _texto(asset, "browser_download_url", url)
        validar_url_publica(destino, hosts_permitidos=HOSTS_DESCARGA_PERMITIDOS)
        encontrados[nombre] = AssetPublicado(
            nombre=nombre, url=destino, tamano=_entero(asset, "size", url)
        )

    faltantes = [nombre for nombre in esperados if nombre not in encontrados]
    if faltantes:
        raise ErrorActualizadorPublico(f"La publicación {tag} no expone los assets {faltantes}.")
    return PublicacionPublica(tag=tag, commit_sha=sha, assets=encontrados)


def validar_metadatos(
    datos: Mapping[str, Any],
    sha: str,
    *,
    repositorio: str,
    run: RunCi,
    job: JobCi,
) -> str:
    """Valida el archivo que ata publicación, commit, árbol y CI.

    Resultado: el ``tree_sha`` declarado, que después debe coincidir con el que
    trae ``release.json`` dentro del paquete. Esa doble comprobación es la que
    impide combinar metadatos de un SHA con el tar de otro.
    """

    contexto = nombre_metadatos(sha)
    if datos.get("formato") != FORMATO_METADATOS:
        raise ErrorActualizadorPublico(f"{contexto} no declara el formato {FORMATO_METADATOS}.")
    if datos.get("version_formato") != VERSION_METADATOS:
        raise ErrorActualizadorPublico(f"{contexto} declara una versión de formato no soportada.")
    if _texto(datos, "repositorio", contexto) != repositorio:
        raise ErrorActualizadorPublico(f"{contexto} corresponde a otro repositorio.")
    if _texto(datos, "commit_sha", contexto) != sha:
        raise ErrorActualizadorPublico(f"{contexto} corresponde a otro commit.")
    if _texto(datos, "tag", contexto) != tag_publicacion(sha):
        raise ErrorActualizadorPublico(f"{contexto} corresponde a otro tag.")
    tree_sha = validar_sha(_texto(datos, "tree_sha", contexto))

    ci = _objeto(datos.get("ci"), f"{contexto}.ci")
    if _entero(ci, "run_id", contexto) != run.identificador:
        raise ErrorActualizadorPublico(f"{contexto} nombra una run de CI distinta de la exigida.")
    if _entero(ci, "job_id", contexto) != job.identificador:
        raise ErrorActualizadorPublico(f"{contexto} nombra un job distinto del exigido.")
    if _texto(ci, "workflow", contexto) != NOMBRE_WORKFLOW_CI:
        raise ErrorActualizadorPublico(f"{contexto} no nombra el workflow {NOMBRE_WORKFLOW_CI}.")
    if _texto(ci, "job", contexto) != NOMBRE_JOB_EMPAQUETADO:
        raise ErrorActualizadorPublico(f"{contexto} no nombra el job de empaquetado.")
    if _texto(ci, "evento", contexto) != EVENTO_PUBLICABLE:
        raise ErrorActualizadorPublico(f"{contexto} no declara el evento {EVENTO_PUBLICABLE}.")
    if _texto(ci, "rama", contexto) != RAMA_PUBLICACION:
        raise ErrorActualizadorPublico(f"{contexto} no declara la rama {RAMA_PUBLICACION}.")

    paquete = _objeto(datos.get("paquete"), f"{contexto}.paquete")
    if _texto(paquete, "nombre", contexto) != nombre_paquete(sha):
        raise ErrorActualizadorPublico(f"{contexto} nombra un paquete distinto del esperado.")
    checksum = _texto(paquete, "sha256", contexto)
    if len(checksum) != 64 or any(caracter not in "0123456789abcdef" for caracter in checksum):
        raise ErrorActualizadorPublico(f"{contexto} no declara un SHA-256 hexadecimal del paquete.")

    sidecar = _objeto(datos.get("sidecar"), f"{contexto}.sidecar")
    if _texto(sidecar, "nombre", contexto) != nombre_sidecar(sha):
        raise ErrorActualizadorPublico(f"{contexto} nombra un sidecar distinto del esperado.")
    return tree_sha


def _descargar_asset(
    cliente: ClienteHttpPublico,
    asset: AssetPublicado,
    destino: Path,
    *,
    maximo_bytes: int,
) -> None:
    """Descarga un asset a un temporal comprobando su tamaño declarado.

    El tamaño que declara GitHub se usa como filtro temprano —no descargar dos
    gigabytes para descubrir después que sobran— y el límite real lo impone el
    propio cliente mientras escribe.
    """

    if asset.tamano < 0 or asset.tamano > maximo_bytes:
        raise ErrorActualizadorPublico(
            f"El asset {asset.nombre} declara {asset.tamano} bytes y supera el máximo aceptado."
        )
    escritos = cliente.descargar(asset.url, destino, maximo_bytes=maximo_bytes)
    if escritos != asset.tamano:
        raise ErrorActualizadorPublico(
            f"El asset {asset.nombre} se descargó incompleto: {escritos} bytes de {asset.tamano}."
        )


def obtener_release_publica(
    destino: Path,
    *,
    cliente: ClienteHttpPublico | None = None,
    sha: str | None = None,
    repositorio: str = REPOSITORIO_PREDETERMINADO,
    rama: str = RAMA_PUBLICACION,
) -> ReleaseDescargada:
    """Ejecuta el flujo completo del canal público y deja la release verificada.

    Entradas:
        destino: directorio donde quedarán paquete, sidecar y metadatos.
        cliente: frontera HTTP; las pruebas inyectan un doble.
        sha: SHA a consumir. Si es ``None`` se resuelve la cabeza de ``main``.
        repositorio: ``propietario/nombre`` del repositorio público.
        rama: rama publicable; sólo ``main`` produce releases.

    Resultado: un :class:`ReleaseDescargada` apto para pasarle a ``preparar``.

    Efectos laterales: crea un subdirectorio temporal dentro de ``destino``,
    descarga allí los tres assets y recién después los promueve con
    ``os.replace``. Ante cualquier error el temporal se borra y ``destino`` queda
    sin artefactos parciales.

    Orden de validación, deliberadamente de lo barato a lo caro:
    SHA, run, job, publicación, nombres, descarga, sidecar, metadatos y, por
    último, ``release.json`` con el motor canónico de la herramienta.
    """

    cliente = cliente or ClienteHttpPublicoReal()
    sha_objetivo = (
        validar_sha(sha)
        if sha is not None
        else resolver_sha_main(cliente, repositorio=repositorio, rama=rama)
    )
    run = seleccionar_run_ci(cliente, sha_objetivo, repositorio=repositorio, rama=rama)
    job = verificar_job_empaquetado(cliente, run, repositorio=repositorio)
    publicacion = resolver_publicacion(cliente, sha_objetivo, repositorio=repositorio)

    destino.mkdir(parents=True, exist_ok=True)
    temporal = destino / f".descarga-{sha_objetivo}-{os.getpid()}"
    if temporal.exists():
        raise ErrorActualizadorPublico(f"Ya existe un directorio temporal de descarga: {temporal}")
    temporal.mkdir()
    try:
        paquete_tmp = temporal / nombre_paquete(sha_objetivo)
        sidecar_tmp = temporal / nombre_sidecar(sha_objetivo)
        metadatos_tmp = temporal / nombre_metadatos(sha_objetivo)

        _descargar_asset(
            cliente,
            publicacion.assets[paquete_tmp.name],
            paquete_tmp,
            maximo_bytes=MAXIMO_BYTES_PAQUETE,
        )
        _descargar_asset(
            cliente,
            publicacion.assets[sidecar_tmp.name],
            sidecar_tmp,
            maximo_bytes=MAXIMO_BYTES_SIDECAR,
        )
        _descargar_asset(
            cliente,
            publicacion.assets[metadatos_tmp.name],
            metadatos_tmp,
            maximo_bytes=MAXIMO_BYTES_METADATOS,
        )

        # Defensa canónica número uno: el sidecar. Se delega en la herramienta
        # de despliegue para que no exista un segundo cálculo de checksum.
        checksum = verificar_checksum(paquete_tmp, sidecar_tmp)

        try:
            crudos = json.loads(metadatos_tmp.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ErrorActualizadorPublico(
                f"Los metadatos de {publicacion.tag} no son JSON válido: {error}"
            ) from error
        metadatos = _objeto(crudos, nombre_metadatos(sha_objetivo))
        tree_sha = validar_metadatos(
            metadatos, sha_objetivo, repositorio=repositorio, run=run, job=job
        )
        checksum_declarado = cast(dict[str, Any], metadatos["paquete"])["sha256"]
        if checksum_declarado != checksum:
            raise ErrorActualizadorPublico(
                "El SHA-256 declarado en los metadatos no coincide con el del paquete descargado."
            )

        # Defensa canónica número dos: release.json, commit, árbol e inventario.
        # ``inspeccionar_manifest_paquete`` es la misma validación que después
        # vuelve a correr ``preparar`` al extraer; acá se adelanta para no
        # entregar un paquete que igual sería rechazado.
        try:
            manifest = inspeccionar_manifest_paquete(paquete_tmp, sha_objetivo)
        except ErrorDespliegue as error:
            raise ErrorActualizadorPublico(
                f"El paquete público de {sha_objetivo} no superó la validación canónica: {error}"
            ) from error
        if manifest.get("tree_sha") != tree_sha:
            raise ErrorActualizadorPublico(
                "El tree SHA del manifest no coincide con el declarado en los metadatos."
            )

        paquete = destino / paquete_tmp.name
        sidecar = destino / sidecar_tmp.name
        archivo_metadatos = destino / metadatos_tmp.name
        os.replace(paquete_tmp, paquete)
        os.replace(sidecar_tmp, sidecar)
        os.replace(metadatos_tmp, archivo_metadatos)
    except Exception:
        # Fail-safe: no se deja nada que otro proceso pueda confundir con una
        # release válida. ``destino`` queda exactamente como estaba.
        for residuo in sorted(temporal.glob("*")):
            residuo.unlink(missing_ok=True)
        temporal.rmdir()
        raise
    else:
        temporal.rmdir()

    return ReleaseDescargada(
        commit_sha=sha_objetivo,
        tree_sha=tree_sha,
        tag=publicacion.tag,
        paquete=paquete,
        sidecar=sidecar,
        metadatos=archivo_metadatos,
        run_ci=run,
        job_ci=job,
    )


def crear_parser() -> argparse.ArgumentParser:
    """CLI mínima: obtener una release pública verificada, nada más.

    No hay subcomando que prepare, active ni reinicie servicios. Este ejecutable
    sólo trae y verifica; la vida de la release sigue siendo competencia de
    ``deploy/herramienta_despliegue.py``.
    """

    parser = argparse.ArgumentParser(
        description="Obtiene una release pública de SIS-Leg por SHA, sin credenciales."
    )
    sub = parser.add_subparsers(dest="comando", required=True)
    obtener = sub.add_parser("obtener", help="Descarga y verifica la release pública de un SHA.")
    obtener.add_argument("--destino", type=Path, required=True)
    obtener.add_argument("--sha", default=None)
    obtener.add_argument("--repositorio", default=REPOSITORIO_PREDETERMINADO)
    return parser


def main(argumentos: Sequence[str] | None = None) -> int:
    """Traduce el resultado a JSON y cualquier falla a exit code 1."""

    opciones = crear_parser().parse_args(argumentos)
    try:
        release = obtener_release_publica(
            opciones.destino,
            sha=opciones.sha,
            repositorio=opciones.repositorio,
        )
    except (ErrorActualizadorPublico, ErrorDespliegue, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "commit_sha": release.commit_sha,
                "tree_sha": release.tree_sha,
                "tag": release.tag,
                "paquete": str(release.paquete),
                "sidecar": str(release.sidecar),
                "metadatos": str(release.metadatos),
                "ci_run_id": release.run_ci.identificador,
                "ci_run_number": release.run_ci.numero,
                "ci_job_id": release.job_ci.identificador,
                "paquete_sha256": sha256_archivo(release.paquete),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
