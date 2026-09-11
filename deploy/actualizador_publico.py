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
y un archivo de metadatos que ata publicación, commit, árbol Git y el intento
exacto de CI que la habilitó.

Este módulo es el lado **consumidor** de ese canal. Su contrato es estricto:

- nunca envía cabecera de autenticación, ni token, ni cookie;
- sólo habla HTTPS y sólo con hosts de GitHub declarados;
- no sigue redirecciones hacia esquemas distintos de HTTPS;
- aplica timeout y tamaño máximo a cada respuesta;
- descarga siempre a temporales y promueve sólo lo que validó;
- no construye comandos de shell con datos que vienen de GitHub.

Reparto de responsabilidades
----------------------------

Este módulo se ocupa de **transporte y selección**: qué SHA, qué publicación,
qué intento de CI la habilitó y qué assets. La **validez** de la release sigue decidiéndola la
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
from collections.abc import Callable, Mapping, Sequence
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


# Frontera mínima para consultar evidencia de CI: recibe una URL y devuelve el
# JSON ya parseado, o ``None`` si el recurso no existe. La cumplen tanto el
# cliente público de este módulo como el cliente autenticado del publicador, y
# por eso las dos mitades del canal comparten una sola implementación de las
# comprobaciones sobre runs, intentos y jobs.
ConsultaJson = Callable[[str], Any]


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
# Selección determinista:
# SHA -> publicación -> metadatos -> intento histórico de CI -> assets
#
# El orden importa. Hasta la corrección de WP-100 I002 el actualizador elegía
# primero «la run más reciente» del SHA y exigía que los metadatos de la release
# coincidieran con ella. Eso rompía ante una re-ejecución: la release inmutable
# seguía nombrando el intento que la publicó, pero la comparación se hacía
# contra el intento más nuevo. Ahora la release manda: sus metadatos declaran el
# intento habilitante y ese intento exacto es el que se va a demostrar contra la
# API.
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunCi:
    """El intento exacto de la run de CI que habilitó una publicación.

    ``identificador`` e ``intento`` se leen juntos: una misma run puede tener
    varios intentos y sólo uno de ellos publicó la release. Ese par es la
    identidad estable de la evidencia de CI.
    """

    identificador: int
    numero: int
    intento: int
    head_sha: str
    workflow: str


@dataclass(frozen=True, slots=True)
class JobCi:
    """El job de empaquetado exacto dentro de ese intento.

    Conserva ``run_id`` e ``intento`` porque una re-ejecución crea jobs nuevos:
    saber a qué ejecución pertenece el job es lo que impide mezclar el
    identificador de un intento con la evidencia de otro.
    """

    identificador: int
    nombre: str
    head_sha: str
    run_id: int
    intento: int


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
    """Resultado verificado y listo para entregar a ``preparar``.

    ``run_ci`` y ``job_ci`` son la evidencia **histórica**: el intento de CI que
    publicó esta release y su job de empaquetado, no la ejecución más reciente
    de esa run.
    """

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


# --------------------------------------------------------------------------
# Evidencia histórica: el intento de CI que habilitó una publicación
# --------------------------------------------------------------------------
#
# ¿Por qué «el intento histórico» y no «el último intento»?
# ---------------------------------------------------------
#
# GitHub Actions permite **re-ejecutar** una run conservando el mismo ``run_id``
# y el mismo SHA, pero creando un intento nuevo (``run_attempt``) con jobs
# nuevos y, por lo tanto, con identificadores nuevos. La release pública, en
# cambio, es inmutable: la habilitó un intento concreto y sus metadatos nombran
# ese intento para siempre.
#
# Si el consumidor preguntara por «los jobs de la run» —``/actions/runs/{id}/jobs``,
# que responde con ``filter=latest`` de forma predeterminada— después de una
# re-ejecución recibiría los jobs del intento más reciente y rechazaría una
# release que sigue siendo íntegra. Por eso acá se consulta el endpoint por
# intento exacto, que GitHub conserva para siempre:
#
#     /repos/{owner}/{repo}/actions/runs/{run_id}/attempts/{run_attempt}
#     /repos/{owner}/{repo}/actions/runs/{run_id}/attempts/{run_attempt}/jobs
#
# Los metadatos de la release dicen qué intento hay que demostrar; la API dice
# si ese intento existió, si fue del mismo SHA, del mismo workflow, del mismo
# evento y rama, y si terminó en ``success``. Una re-ejecución posterior no
# cambia ninguna de esas respuestas, así que no puede invalidar ni volver
# falsamente divergente una publicación previa.
#
# Los identificadores salen de un asset público y por lo tanto son un dato
# externo. No se confía en ellos: sólo se usan como enteros para armar una URL
# del repositorio ya validado, y el intento que nombren debe demostrar por sí
# mismo que corresponde a este SHA exacto. Unos metadatos falsificados no
# pueden apuntar a una CI que no sea, realmente, una CI verde de este commit.


def url_intento_ci(repositorio: str, run_id: int, intento: int) -> str:
    """URL pública del intento histórico exacto de una run de CI."""

    return f"https://{HOST_API}/repos/{repositorio}/actions/runs/{run_id}/attempts/{intento}"


def url_jobs_intento_ci(repositorio: str, run_id: int, intento: int) -> str:
    """URL pública de los jobs de ese intento histórico, no los del más reciente."""

    return f"{url_intento_ci(repositorio, run_id, intento)}/jobs?per_page=100"


def _identificador_positivo(valor: object, nombre: str) -> int:
    """Exige un entero positivo antes de concatenarlo en una URL del API."""

    if not isinstance(valor, int) or isinstance(valor, bool) or valor <= 0:
        raise ErrorActualizadorPublico(
            f"{nombre} debe ser un entero positivo y se recibió {valor!r}."
        )
    return valor


def _consultar_evidencia(consultar: ConsultaJson, url: str, descripcion: str) -> dict[str, Any]:
    """Pide una evidencia de CI traduciendo ausencia y falla a un mensaje claro.

    Las dos fronteras HTTP del proyecto señalan «no existe» de forma distinta: el
    consumidor público levanta ``ErrorActualizadorPublico`` con el código HTTP y
    el publicador autenticado devuelve ``None`` ante un 404. Las dos formas se
    traducen acá al mismo resultado: fallar cerrado nombrando qué evidencia no
    pudo demostrarse.
    """

    try:
        datos = consultar(url)
    except ErrorActualizadorPublico as error:
        raise ErrorActualizadorPublico(f"No se pudo demostrar {descripcion}: {error}") from error
    if datos is None:
        raise ErrorActualizadorPublico(f"No existe {descripcion}: {url}")
    return _objeto(datos, url)


def verificar_intento_ci(
    consultar: ConsultaJson,
    *,
    repositorio: str,
    run_id: int,
    intento: int,
    sha: str,
    rama: str = RAMA_PUBLICACION,
) -> RunCi:
    """Exige que ese intento histórico haya sido la CI completa y verde del SHA.

    Entradas:
        consultar: frontera HTTP que devuelve el JSON de una URL del API.
        repositorio: ``propietario/nombre`` ya conocido y validado.
        run_id, intento: el par exacto que se quiere demostrar.
        sha: el commit que la publicación dice haber empaquetado.
        rama: la única rama publicable.

    Resultado: la :class:`RunCi` correspondiente a ese intento.

    Errores:
        ErrorActualizadorPublico si el intento no existe, pertenece a otro
        workflow, evento, rama o SHA, no terminó, o no terminó en ``success``.
        No alcanza con que el job de empaquetado esté verde: se exige la
        conclusión de la **run entera** de ese intento, que es lo que el WP pide
        para no publicar ni consumir una CI parcial o fallida.
    """

    sha = validar_sha(sha)
    _validar_repositorio(repositorio)
    run_id = _identificador_positivo(run_id, "run_id")
    intento = _identificador_positivo(intento, "run_attempt")

    url = url_intento_ci(repositorio, run_id, intento)
    descripcion = f"el intento {intento} de la run de CI {run_id}"
    datos = _consultar_evidencia(consultar, url, descripcion)

    if _texto(datos, "name", url) != NOMBRE_WORKFLOW_CI:
        raise ErrorActualizadorPublico(
            f"{descripcion} no pertenece al workflow {NOMBRE_WORKFLOW_CI}."
        )
    if _texto(datos, "event", url) != EVENTO_PUBLICABLE:
        raise ErrorActualizadorPublico(
            f"{descripcion} no corresponde a un evento {EVENTO_PUBLICABLE}."
        )
    if _texto(datos, "head_branch", url) != rama:
        raise ErrorActualizadorPublico(f"{descripcion} no corresponde a {rama}.")
    if _texto(datos, "head_sha", url) != sha:
        raise ErrorActualizadorPublico(f"{descripcion} no corresponde al SHA {sha}.")
    if _texto(datos, "status", url) != "completed":
        raise ErrorActualizadorPublico(f"{descripcion} todavía no terminó.")
    if _texto(datos, "conclusion", url) != "success":
        raise ErrorActualizadorPublico(f"{descripcion} no terminó en success.")
    if _entero(datos, "id", url) != run_id:
        raise ErrorActualizadorPublico(
            f"{descripcion} devolvió otra run; no se mezclan ejecuciones."
        )
    if _entero(datos, "run_attempt", url) != intento:
        raise ErrorActualizadorPublico(
            f"{descripcion} devolvió otro intento; no se mezclan ejecuciones."
        )

    return RunCi(
        identificador=run_id,
        numero=_entero(datos, "run_number", url),
        intento=intento,
        head_sha=sha,
        workflow=NOMBRE_WORKFLOW_CI,
    )


def verificar_job_empaquetado(
    consultar: ConsultaJson,
    run: RunCi,
    *,
    repositorio: str = REPOSITORIO_PREDETERMINADO,
) -> JobCi:
    """Exige el job ``Empaquetado · release productiva`` exacto de ese intento.

    La coincidencia de nombre es exacta y sensible a mayúsculas y acentos: un
    job parecido no es el job. Además el job debe declarar el mismo ``head_sha``
    que la run y pertenecer a esa run y a ese intento, para que no puedan
    combinarse datos de dos ejecuciones distintas.
    """

    _validar_repositorio(repositorio)
    url = url_jobs_intento_ci(repositorio, run.identificador, run.intento)
    descripcion = f"los jobs del intento {run.intento} de la run {run.identificador}"
    datos = _consultar_evidencia(consultar, url, descripcion)

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
                f"El job {NOMBRE_JOB_EMPAQUETADO} del intento {run.intento} de la run "
                f"{run.identificador} no terminó en success."
            )
        head_sha = _texto(job, "head_sha", url)
        if head_sha != run.head_sha:
            raise ErrorActualizadorPublico(
                f"El job {NOMBRE_JOB_EMPAQUETADO} declara head_sha {head_sha} y la run "
                f"{run.head_sha}: no se mezclan SHAs distintos."
            )
        if _entero(job, "run_id", url) != run.identificador:
            raise ErrorActualizadorPublico(
                f"El job {NOMBRE_JOB_EMPAQUETADO} pertenece a otra run; no se mezclan ejecuciones."
            )
        if _entero(job, "run_attempt", url) != run.intento:
            raise ErrorActualizadorPublico(
                f"El job {NOMBRE_JOB_EMPAQUETADO} pertenece a otro intento; no se mezclan "
                "ejecuciones."
            )
        coincidencias.append(
            JobCi(
                identificador=_entero(job, "id", url),
                nombre=NOMBRE_JOB_EMPAQUETADO,
                head_sha=head_sha,
                run_id=run.identificador,
                intento=run.intento,
            )
        )

    if len(coincidencias) != 1:
        raise ErrorActualizadorPublico(
            f"Se esperaba exactamente un job {NOMBRE_JOB_EMPAQUETADO} en el intento "
            f"{run.intento} de la run {run.identificador} y se encontraron "
            f"{len(coincidencias)}."
        )
    return coincidencias[0]


def verificar_intento_historico(
    consultar: ConsultaJson,
    *,
    repositorio: str,
    run_id: int,
    intento: int,
    sha: str,
    rama: str = RAMA_PUBLICACION,
) -> tuple[RunCi, JobCi]:
    """Demuestra de una vez el intento habilitante y su job de empaquetado.

    Es el único punto donde se prueba «hubo CI verde de push a main para este
    SHA y su empaquetado fue exitoso». Lo usan los dos lados del canal: el
    publicador sobre el intento que está publicando y el consumidor sobre el
    intento que los metadatos de la release declaran como habilitante.
    """

    run = verificar_intento_ci(
        consultar, repositorio=repositorio, run_id=run_id, intento=intento, sha=sha, rama=rama
    )
    return run, verificar_job_empaquetado(consultar, run, repositorio=repositorio)


def leer_intento_declarado(datos: Mapping[str, Any], sha: str) -> tuple[int, int]:
    """Lee qué intento dicen los metadatos, sin darlo todavía por bueno.

    Se separa de :func:`validar_metadatos` porque hay un orden obligatorio: para
    validar los metadatos hace falta la run y el job reales, y para pedirlos hace
    falta saber primero qué intento declaran. Acá sólo se comprueba la forma
    —dos enteros positivos— y la prueba de fondo la da
    :func:`verificar_intento_historico`.
    """

    contexto = nombre_metadatos(sha)
    ci = _objeto(datos.get("ci"), f"{contexto}.ci")
    return (
        _identificador_positivo(_entero(ci, "run_id", contexto), f"{contexto}.ci.run_id"),
        _identificador_positivo(_entero(ci, "run_attempt", contexto), f"{contexto}.ci.run_attempt"),
    )


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
    # ``target_commitish`` se acepta como el SHA exacto o como la rama publicable
    # porque GitHub puede normalizarlo al crear el tag. La atadura fuerte al SHA
    # no depende de este campo: la dan el nombre del tag, el ``commit_sha`` de los
    # metadatos y el de ``release.json``, que se comparan todos más abajo.
    # Cualquier otro valor indica una publicación que apunta a otro lado.
    objetivo = _texto(datos, "target_commitish", url)
    if objetivo not in (sha, RAMA_PUBLICACION):
        raise ErrorActualizadorPublico(
            f"La publicación {tag} apunta a {objetivo!r} y no al commit {sha}; no se mezclan "
            "publicaciones."
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

    Entradas:
        datos: el JSON de metadatos ya parseado.
        sha: el commit que se está consumiendo o publicando.
        repositorio: ``propietario/nombre`` esperado.
        run, job: el intento habilitante y su job de empaquetado, **ya
            demostrados contra la API** por :func:`verificar_intento_historico`.

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
    # El intento y el número de la run se comprueban además del identificador
    # porque son lo que ata la publicación a una ejecución concreta: unos
    # metadatos que mezclaran el ``run_id`` de una ejecución con el intento o el
    # job de otra quedarían descartados acá.
    if _entero(ci, "run_attempt", contexto) != run.intento:
        raise ErrorActualizadorPublico(f"{contexto} nombra un intento distinto del demostrado.")
    if _entero(ci, "run_number", contexto) != run.numero:
        raise ErrorActualizadorPublico(f"{contexto} nombra otro número de run de CI.")
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

    Orden de validación, deliberadamente de lo barato a lo caro y de lo que
    decide a lo que se deriva:

    1. SHA de ``main``;
    2. publicación por tag y nombres exactos de los tres assets;
    3. descarga del asset de metadatos, que es chico y dice qué intento de CI
       habilitó esta release;
    4. demostración de ese intento histórico exacto y de su job de empaquetado
       contra la API pública;
    5. validación completa de los metadatos contra esa evidencia;
    6. recién entonces descarga del paquete y del sidecar, que son los caros;
    7. checksum, y por último ``release.json`` con el motor canónico.

    Los pasos 3 a 5 son los que sobreviven a una re-ejecución de CI: se demuestra
    el intento que publicó esta release, no el intento más reciente de la run.
    """

    cliente = cliente or ClienteHttpPublicoReal()
    sha_objetivo = (
        validar_sha(sha)
        if sha is not None
        else resolver_sha_main(cliente, repositorio=repositorio, rama=rama)
    )
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

        # Primero el asset chico: dice qué intento de CI hay que demostrar y
        # evita bajar un tar entero cuando la evidencia no se sostiene.
        _descargar_asset(
            cliente,
            publicacion.assets[metadatos_tmp.name],
            metadatos_tmp,
            maximo_bytes=MAXIMO_BYTES_METADATOS,
        )
        try:
            crudos = json.loads(metadatos_tmp.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ErrorActualizadorPublico(
                f"Los metadatos de {publicacion.tag} no son JSON válido: {error}"
            ) from error
        metadatos = _objeto(crudos, nombre_metadatos(sha_objetivo))

        # La release es inmutable y nombra el intento que la habilitó. Ese es el
        # que se demuestra, aunque después haya habido re-ejecuciones con
        # identificadores nuevos.
        run_declarada, intento_declarado = leer_intento_declarado(metadatos, sha_objetivo)
        run, job = verificar_intento_historico(
            cliente.obtener_json,
            repositorio=repositorio,
            run_id=run_declarada,
            intento=intento_declarado,
            sha=sha_objetivo,
            rama=rama,
        )
        tree_sha = validar_metadatos(
            metadatos, sha_objetivo, repositorio=repositorio, run=run, job=job
        )

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

        # Defensa canónica número uno: el sidecar. Se delega en la herramienta
        # de despliegue para que no exista un segundo cálculo de checksum.
        checksum = verificar_checksum(paquete_tmp, sidecar_tmp)
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
                "ci_run_attempt": release.run_ci.intento,
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
