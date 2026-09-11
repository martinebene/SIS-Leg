"""Publica la release pública e inmutable de un SHA de ``main`` (WP-100).

Este script corre **del lado servidor**, dentro de GitHub Actions, después de que
la CI completa de un ``push`` sobre ``main`` haya terminado en ``success``. Usa
el ``GITHUB_TOKEN`` efímero que Actions inyecta en el job; esa credencial nunca
sale del runner y nunca se escribe en la salida.

La prohibición de credenciales del WP aplica al **consumidor** —el actualizador
del host institucional—, que consume el resultado de este script sin ninguna
autenticación. Ver ``deploy/actualizador_publico.py``.

Qué exige antes de publicar
---------------------------

1. el **intento exacto** de CI indicado por ``--run-id`` y ``--run-attempt``
   existe, es del workflow ``CI``, del evento ``push``, sobre ``main``, para el
   SHA exacto, ``completed`` y ``success``;
2. dentro de ese intento, el job ``Empaquetado · release productiva`` terminó en
   ``success`` y declara el mismo ``head_sha``;
3. el paquete local se llama ``sis-leg-<SHA>.tar.gz``, su sidecar valida y su
   ``release.json`` supera la validación canónica de la herramienta de
   despliegue.

Se trabaja siempre sobre el intento exacto y nunca sobre «la run» a secas,
porque GitHub permite re-ejecutar una run conservando ``run_id`` y SHA: la
consulta genérica devolvería entonces los jobs del intento más reciente y no los
del que realmente produjo este paquete.

Idempotencia y colisiones
-------------------------

Si el tag ya existe, el script **no** reemplaza nada. Exige que el paquete y el
sidecar publicados sean exactamente los mismos bytes que los locales, y que los
metadatos publicados sigan siendo coherentes y sigan apoyándose en un intento de
CI históricamente válido de este mismo SHA. Si eso se cumple, la publicación ya
estaba hecha y el script termina con éxito sin escribir nada; si algo difiere,
aborta y exige intervención humana. Una release publicada es inmutable.

Por eso los metadatos **no** se comparan byte a byte: una re-ejecución legítima
de la misma run vuelve a invocar este script con otro ``run_attempt`` y otro
``job_id``, y esa diferencia no puede convertir una release válida en una
colisión divergente.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol, cast

# ``uv run python scripts/publicar_release_publica.py`` deja ``scripts/`` en
# ``sys.path`` y no la raíz. Se hace explícita antes de importar el contrato
# compartido, igual que en ``scripts/validar_release_produccion.py``.
RAIZ_REPOSITORIO = Path(__file__).resolve().parents[1]
if str(RAIZ_REPOSITORIO) not in sys.path:
    sys.path.insert(0, str(RAIZ_REPOSITORIO))

from deploy.actualizador_publico import (  # noqa: E402 - raíz preparada arriba
    EVENTO_PUBLICABLE,
    FORMATO_METADATOS,
    HOST_API,
    NOMBRE_JOB_EMPAQUETADO,
    NOMBRE_WORKFLOW_CI,
    RAMA_PUBLICACION,
    VERSION_METADATOS,
    ErrorActualizadorPublico,
    JobCi,
    RunCi,
    assets_esperados,
    leer_intento_declarado,
    nombre_metadatos,
    nombre_paquete,
    nombre_sidecar,
    tag_publicacion,
    validar_metadatos,
    validar_url_publica,
    verificar_intento_historico,
)
from deploy.herramienta_despliegue import (  # noqa: E402 - raíz preparada arriba
    ErrorDespliegue,
    inspeccionar_manifest_paquete,
    validar_sha,
    verificar_checksum,
)

HOST_SUBIDA = "uploads.github.com"
HOSTS_PERMITIDOS = (HOST_API, HOST_SUBIDA, "github.com", "objects.githubusercontent.com")
TIEMPO_ESPERA_SEGUNDOS = 60.0
MAXIMO_BYTES_JSON = 8 * 1024 * 1024
VARIABLE_TOKEN = "GITHUB_TOKEN"


class ErrorPublicacion(RuntimeError):
    """Impide publicar una release que no está inequívocamente habilitada."""


@contextmanager
def _como_error_publicacion() -> Generator[None]:
    """Traduce las fallas del módulo compartido al vocabulario del publicador.

    Las comprobaciones de intento, job y metadatos viven una sola vez, en
    ``deploy/actualizador_publico.py``, y levantan ``ErrorActualizadorPublico``.
    Este publicador expone ``ErrorPublicacion`` en toda su superficie, así que la
    frontera se traduce acá en lugar de duplicar la lógica o de obligar a cada
    llamador a conocer los dos tipos.
    """

    try:
        yield
    except ErrorActualizadorPublico as error:
        raise ErrorPublicacion(str(error)) from error


class ClienteApiGitHub(Protocol):
    """Frontera HTTP del publicador, inyectable para probar sin red ni token."""

    def obtener(self, url: str) -> Any | None: ...

    def crear(self, url: str, cuerpo: Mapping[str, Any]) -> Any: ...

    def subir_asset(self, url: str, ruta: Path, tipo_contenido: str) -> Any: ...

    def descargar(self, url: str, destino: Path) -> None: ...


class ClienteApiGitHubReal:
    """Cliente autenticado con el token efímero del runner.

    El token se recibe por parámetro y sólo se usa para armar la cabecera
    ``Authorization``. No se imprime, no se registra y no se incluye en ningún
    mensaje de error: los mensajes nombran la URL y el código HTTP, nada más.
    """

    def __init__(self, token: str, *, tiempo_espera: float = TIEMPO_ESPERA_SEGUNDOS) -> None:
        if not token:
            raise ErrorPublicacion(
                f"Falta {VARIABLE_TOKEN}. El job de publicación debe recibir el token efímero "
                "de GitHub Actions."
            )
        self._token = token
        self.tiempo_espera = tiempo_espera

    def _cabeceras(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "User-Agent": "sis-leg-publicador/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _ejecutar(
        self,
        url: str,
        *,
        metodo: str,
        datos: bytes | None = None,
        tipo_contenido: str | None = None,
        aceptar_404: bool = False,
    ) -> Any | None:
        validar_url_publica(url, hosts_permitidos=HOSTS_PERMITIDOS)
        cabeceras = self._cabeceras()
        if tipo_contenido is not None:
            cabeceras["Content-Type"] = tipo_contenido
        solicitud = urllib.request.Request(url, data=datos, method=metodo, headers=cabeceras)
        try:
            with urllib.request.urlopen(solicitud, timeout=self.tiempo_espera) as respuesta:
                crudo = respuesta.read(MAXIMO_BYTES_JSON + 1)
        except urllib.error.HTTPError as error:
            if error.code == 404 and aceptar_404:
                return None
            raise ErrorPublicacion(f"GitHub respondió HTTP {error.code} en {url}.") from error
        except (urllib.error.URLError, OSError) as error:
            raise ErrorPublicacion(f"No se pudo contactar {url}: {error}") from error
        if not crudo:
            return None
        if len(crudo) > MAXIMO_BYTES_JSON:
            raise ErrorPublicacion(f"La respuesta de {url} supera {MAXIMO_BYTES_JSON} bytes.")
        try:
            return json.loads(crudo.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ErrorPublicacion(f"{url} no devolvió JSON válido: {error}") from error

    def obtener(self, url: str) -> Any | None:
        """GET que devuelve ``None`` ante 404, para distinguir ausencia de falla."""

        return self._ejecutar(url, metodo="GET", aceptar_404=True)

    def crear(self, url: str, cuerpo: Mapping[str, Any]) -> Any:
        """POST con cuerpo JSON, usado para crear la release."""

        datos = json.dumps(cuerpo).encode("utf-8")
        return self._ejecutar(url, metodo="POST", datos=datos, tipo_contenido="application/json")

    def subir_asset(self, url: str, ruta: Path, tipo_contenido: str) -> Any:
        """POST binario al endpoint de subida de assets de la release."""

        return self._ejecutar(
            url, metodo="POST", datos=ruta.read_bytes(), tipo_contenido=tipo_contenido
        )

    def descargar(self, url: str, destino: Path) -> None:
        """Baja un asset ya publicado para compararlo byte a byte."""

        validar_url_publica(url, hosts_permitidos=HOSTS_PERMITIDOS)
        solicitud = urllib.request.Request(url, method="GET", headers=self._cabeceras())
        try:
            with urllib.request.urlopen(solicitud, timeout=self.tiempo_espera) as respuesta:
                destino.write_bytes(respuesta.read())
        except (urllib.error.HTTPError, urllib.error.URLError, OSError) as error:
            raise ErrorPublicacion(f"No se pudo descargar {url}: {error}") from error


def _texto(datos: Mapping[str, Any], clave: str, contexto: str) -> str:
    """Extrae un campo textual obligatorio de una respuesta del API."""

    valor = datos.get(clave)
    if not isinstance(valor, str):
        raise ErrorPublicacion(f"{contexto} no declara {clave} textual.")
    return valor


def _objeto(datos: Any, contexto: str) -> dict[str, Any]:
    """Exige un objeto JSON antes de indexarlo."""

    if not isinstance(datos, dict):
        raise ErrorPublicacion(f"{contexto} no devolvió un objeto JSON.")
    return cast(dict[str, Any], datos)


def localizar_artefactos(directorio: Path, sha: str) -> tuple[Path, Path]:
    """Encuentra el paquete y el sidecar exactos del SHA dentro del directorio.

    La búsqueda es recursiva porque el artifact de Actions conserva su jerarquía
    original, pero los nombres son exactos y debe haber **una sola** coincidencia
    de cada uno: dos paquetes con el mismo nombre significan que el directorio
    mezcla descargas y no se puede decidir cuál publicar.
    """

    if not directorio.is_dir():
        raise ErrorPublicacion(f"No existe el directorio de artefactos: {directorio}")

    def unico(nombre: str) -> Path:
        candidatos = sorted(ruta for ruta in directorio.rglob(nombre) if ruta.is_file())
        if len(candidatos) != 1:
            raise ErrorPublicacion(
                f"Se esperaba exactamente un {nombre} bajo {directorio} y se encontraron "
                f"{len(candidatos)}."
            )
        return candidatos[0]

    return unico(nombre_paquete(sha)), unico(nombre_sidecar(sha))


def construir_metadatos(
    *,
    repositorio: str,
    sha: str,
    tree_sha: str,
    checksum: str,
    tamano: int,
    run: RunCi,
    job: JobCi,
) -> dict[str, Any]:
    """Arma el documento que ata publicación, commit, árbol Git y CI.

    Es el tercer asset de la publicación. El consumidor lo valida campo por
    campo y compara su ``tree_sha`` con el de ``release.json``: esa doble
    verificación es lo que impide combinar los metadatos de un SHA con el tar de
    otro.

    El bloque ``ci`` guarda el par ``run_id`` + ``run_attempt`` **del intento que
    está publicando**, junto con el identificador de su job de empaquetado. Ese
    par es la identidad estable de la evidencia: una re-ejecución posterior de la
    misma run creará otro intento con otros jobs, y el consumidor debe seguir
    verificando el que figura acá.
    """

    return {
        "formato": FORMATO_METADATOS,
        "version_formato": VERSION_METADATOS,
        "repositorio": repositorio,
        "commit_sha": sha,
        "tree_sha": tree_sha,
        "tag": tag_publicacion(sha),
        "ci": {
            "workflow": NOMBRE_WORKFLOW_CI,
            "evento": EVENTO_PUBLICABLE,
            "rama": RAMA_PUBLICACION,
            "run_id": run.identificador,
            "run_number": run.numero,
            "run_attempt": run.intento,
            "job": NOMBRE_JOB_EMPAQUETADO,
            "job_id": job.identificador,
        },
        "paquete": {"nombre": nombre_paquete(sha), "sha256": checksum, "tamano": tamano},
        "sidecar": {"nombre": nombre_sidecar(sha)},
    }


def _sha256_bytes(datos: bytes) -> str:
    """Checksum de un contenido ya en memoria, para comparar assets chicos."""

    return hashlib.sha256(datos).hexdigest()


def _inventario_publicado(release: Mapping[str, Any], sha: str) -> dict[str, str]:
    """Mapea nombre de asset a URL de descarga exigiendo los tres exactos.

    Errores:
        ErrorPublicacion si la release existente duplica un asset o si su
        conjunto no es exactamente el de :func:`assets_esperados`. Una release
        publicada a medias no se completa: se aborta y decide una persona.
    """

    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ErrorPublicacion("La release existente no expone una lista de assets.")

    publicados: dict[str, str] = {}
    for cruda in cast(list[Any], assets):
        asset = _objeto(cruda, "asset publicado")
        nombre = _texto(asset, "name", "asset publicado")
        if nombre in publicados:
            raise ErrorPublicacion(f"La release existente duplica el asset {nombre}.")
        publicados[nombre] = _texto(asset, "browser_download_url", "asset publicado")

    esperados = set(assets_esperados(sha))
    if set(publicados) != esperados:
        raise ErrorPublicacion(
            "La release ya existe con un conjunto de assets distinto "
            f"({sorted(publicados)} frente a {sorted(esperados)}). No se reemplaza nada; "
            "se requiere intervención humana."
        )
    return publicados


def confirmar_idempotencia(
    cliente: ClienteApiGitHub,
    release: Mapping[str, Any],
    *,
    repositorio: str,
    sha: str,
    paquete: Path,
    sidecar: Path,
    tree_sha: str,
    checksum: str,
    directorio_temporal: Path,
) -> RunCi:
    """Acepta una publicación ya existente sin tocarla, o aborta fail-safe.

    ¿Por qué no se comparan los tres assets byte a byte?
    ----------------------------------------------------

    Porque el asset de metadatos nombra el intento de CI que publicó la release,
    y ese intento es historia: si la misma run se re-ejecuta, este publicador
    vuelve a correr con un ``run_attempt`` y un ``job_id`` nuevos. Comparar los
    metadatos byte a byte interpretaría esa re-ejecución legítima como una
    colisión divergente y dejaría inutilizable una release válida e inmutable.

    Lo que sí se exige, y es más fuerte que una comparación de bytes:

    - el paquete y el sidecar publicados son **exactamente** los mismos bytes
      que los locales;
    - los metadatos publicados son coherentes con este mismo commit, tag,
      repositorio, árbol Git y checksum;
    - el intento de CI que declaran existió de verdad, fue del mismo SHA, del
      workflow y evento correctos y terminó en ``success``, igual que su job de
      empaquetado.

    Resultado: la :class:`RunCi` del intento que publicó originalmente la
    release, para poder informarlo.

    Errores:
        ErrorPublicacion ante cualquier divergencia. Nunca se reemplaza un asset
        ni se reescriben los metadatos de una release publicada.
    """

    publicados = _inventario_publicado(release, sha)

    # 1. Los bytes del paquete y del sidecar deben ser idénticos. Acá sí la
    #    comparación es byte a byte: son el contenido inmutable de la release.
    for ruta in (paquete, sidecar):
        destino = directorio_temporal / f"publicado-{ruta.name}"
        cliente.descargar(publicados[ruta.name], destino)
        if _sha256_bytes(destino.read_bytes()) != _sha256_bytes(ruta.read_bytes()):
            raise ErrorPublicacion(
                f"El asset {ruta.name} ya publicado difiere byte a byte del local. Una release "
                "publicada es inmutable: se aborta sin reemplazarla."
            )

    # 2. Los metadatos publicados se validan por significado, no por bytes.
    nombre = nombre_metadatos(sha)
    destino_metadatos = directorio_temporal / f"publicado-{nombre}"
    cliente.descargar(publicados[nombre], destino_metadatos)
    try:
        crudos = json.loads(destino_metadatos.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ErrorPublicacion(
            f"Los metadatos ya publicados no son JSON válido: {error}"
        ) from error
    metadatos = _objeto(crudos, nombre)

    with _como_error_publicacion():
        run_declarada, intento_declarado = leer_intento_declarado(metadatos, sha)
        run, job = verificar_intento_historico(
            cliente.obtener,
            repositorio=repositorio,
            run_id=run_declarada,
            intento=intento_declarado,
            sha=sha,
        )
        tree_publicado = validar_metadatos(
            metadatos, sha, repositorio=repositorio, run=run, job=job
        )

    if tree_publicado != tree_sha:
        raise ErrorPublicacion(
            "Los metadatos ya publicados declaran otro árbol Git que el paquete local; se aborta "
            "sin reemplazar nada."
        )
    if _texto(_objeto(metadatos.get("paquete"), f"{nombre}.paquete"), "sha256", nombre) != checksum:
        raise ErrorPublicacion(
            "Los metadatos ya publicados declaran otro SHA-256 que el paquete local; se aborta "
            "sin reemplazar nada."
        )
    return run


def publicar_release(
    cliente: ClienteApiGitHub,
    *,
    repositorio: str,
    sha: str,
    run_id: int,
    run_attempt: int,
    directorio: Path,
) -> dict[str, Any]:
    """Ejecuta la publicación completa y devuelve un resumen serializable.

    Entradas:
        run_id, run_attempt: el intento exacto de CI que está habilitando esta
            publicación. Los provee el evento ``workflow_run`` y se vuelven a
            demostrar contra la API antes de escribir nada.

    Resultado: diccionario con el tag, el estado (``creada`` o ``idempotente``),
    el commit, el árbol y el intento de CI habilitante.

    Efectos laterales: crea la GitHub Release y sube tres assets, o no escribe
    nada si ya estaba publicada de forma válida.
    """

    sha = validar_sha(sha)
    with _como_error_publicacion():
        run, job = verificar_intento_historico(
            cliente.obtener, repositorio=repositorio, run_id=run_id, intento=run_attempt, sha=sha
        )

    paquete, sidecar = localizar_artefactos(directorio, sha)
    checksum = verificar_checksum(paquete, sidecar)
    manifest = inspeccionar_manifest_paquete(paquete, sha)
    tree_sha = validar_sha(str(manifest["tree_sha"]))

    tag = tag_publicacion(sha)
    url_tag = (
        f"https://{HOST_API}/repos/{repositorio}/releases/tags/{urllib.parse.quote(tag, safe='')}"
    )
    existente = cliente.obtener(url_tag)
    if existente is not None:
        publicante = confirmar_idempotencia(
            cliente,
            _objeto(existente, url_tag),
            repositorio=repositorio,
            sha=sha,
            paquete=paquete,
            sidecar=sidecar,
            tree_sha=tree_sha,
            checksum=checksum,
            directorio_temporal=directorio,
        )
        return {
            "tag": tag,
            "estado": "idempotente",
            "commit_sha": sha,
            "tree_sha": tree_sha,
            "ci_run_id": publicante.identificador,
            "ci_run_attempt": publicante.intento,
        }

    metadatos = construir_metadatos(
        repositorio=repositorio,
        sha=sha,
        tree_sha=tree_sha,
        checksum=checksum,
        tamano=paquete.stat().st_size,
        run=run,
        job=job,
    )
    contenido_metadatos = (
        json.dumps(metadatos, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    ruta_metadatos = directorio / nombre_metadatos(sha)
    ruta_metadatos.write_bytes(contenido_metadatos)

    creada = _objeto(
        cliente.crear(
            f"https://{HOST_API}/repos/{repositorio}/releases",
            {
                "tag_name": tag,
                "target_commitish": sha,
                "name": tag,
                "body": (
                    f"Release productiva de SIS-Leg para el commit `{sha}`.\n\n"
                    f"- Árbol Git: `{tree_sha}`\n"
                    f"- CI habilitante: run `{run.identificador}` intento `{run.intento}` del "
                    f"workflow `{NOMBRE_WORKFLOW_CI}` sobre `{RAMA_PUBLICACION}`\n"
                    f"- SHA-256 del paquete: `{checksum}`\n\n"
                    "Los tres assets se consumen sin credenciales mediante "
                    "`deploy/actualizador_publico.py`."
                ),
                "draft": False,
                "prerelease": False,
                "generate_release_notes": False,
            },
        ),
        "creación de release",
    )

    plantilla_subida = _texto(creada, "upload_url", "creación de release")
    base_subida = plantilla_subida.split("{", 1)[0]
    for ruta, tipo in (
        (paquete, "application/gzip"),
        (sidecar, "text/plain"),
        (ruta_metadatos, "application/json"),
    ):
        consulta = urllib.parse.urlencode({"name": ruta.name})
        cliente.subir_asset(f"{base_subida}?{consulta}", ruta, tipo)

    return {
        "tag": tag,
        "estado": "creada",
        "commit_sha": sha,
        "tree_sha": tree_sha,
        "ci_run_id": run.identificador,
        "ci_run_attempt": run.intento,
    }


def crear_parser() -> argparse.ArgumentParser:
    """CLI invocada por el workflow de publicación."""

    parser = argparse.ArgumentParser(
        description="Publica la release pública inmutable de un SHA de main."
    )
    parser.add_argument("--repositorio", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    # El intento es obligatorio y no se deduce releyendo la run: la API
    # devolvería el intento más reciente, que ante una re-ejecución ya no es el
    # que está publicando.
    parser.add_argument("--run-attempt", required=True, type=int)
    parser.add_argument("--directorio", required=True, type=Path)
    return parser


def main(argumentos: Sequence[str] | None = None) -> int:
    """Traduce el resultado a JSON y cualquier falla a exit code 1."""

    opciones = crear_parser().parse_args(argumentos)
    try:
        cliente = ClienteApiGitHubReal(os.environ.get(VARIABLE_TOKEN, ""))
        resumen = publicar_release(
            cliente,
            repositorio=opciones.repositorio,
            sha=opciones.sha,
            run_id=opciones.run_id,
            run_attempt=opciones.run_attempt,
            directorio=opciones.directorio.resolve(),
        )
    except (ErrorPublicacion, ErrorDespliegue, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(resumen, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
