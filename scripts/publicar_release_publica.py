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

1. la run indicada existe, es del workflow ``CI``, del evento ``push``, sobre
   ``main``, para el SHA exacto, ``completed`` y ``success``;
2. dentro de esa run, el job ``Empaquetado · release productiva`` terminó en
   ``success`` y declara el mismo ``head_sha``;
3. el paquete local se llama ``sis-leg-<SHA>.tar.gz``, su sidecar valida y su
   ``release.json`` supera la validación canónica de la herramienta de
   despliegue.

Idempotencia y colisiones
-------------------------

Si el tag ya existe, el script **no** reemplaza nada. Compara byte a byte los
tres assets publicados contra los locales: si son idénticos, la publicación ya
estaba hecha y termina con éxito sin escribir; si difieren o falta alguno,
aborta y exige intervención humana. Una release publicada es inmutable.
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
from collections.abc import Mapping, Sequence
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
    nombre_metadatos,
    nombre_paquete,
    nombre_sidecar,
    tag_publicacion,
    validar_url_publica,
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


def verificar_run_habilitante(
    cliente: ClienteApiGitHub, repositorio: str, run_id: int, sha: str
) -> dict[str, Any]:
    """Exige que la run indicada sea la CI completa y verde del push a ``main``.

    No alcanza con que el job de empaquetado esté verde: se comprueba la
    conclusión de la **run entera**, que es lo que el WP exige para que nunca se
    publique una release candidata parcial o fallida.
    """

    url = f"https://{HOST_API}/repos/{repositorio}/actions/runs/{run_id}"
    datos = _objeto(cliente.obtener(url), url)
    if _texto(datos, "name", url) != NOMBRE_WORKFLOW_CI:
        raise ErrorPublicacion(f"La run {run_id} no pertenece al workflow {NOMBRE_WORKFLOW_CI}.")
    if _texto(datos, "event", url) != EVENTO_PUBLICABLE:
        raise ErrorPublicacion(f"La run {run_id} no corresponde a un evento {EVENTO_PUBLICABLE}.")
    if _texto(datos, "head_branch", url) != RAMA_PUBLICACION:
        raise ErrorPublicacion(f"La run {run_id} no corresponde a {RAMA_PUBLICACION}.")
    if _texto(datos, "head_sha", url) != sha:
        raise ErrorPublicacion(f"La run {run_id} no corresponde al SHA {sha}.")
    if _texto(datos, "status", url) != "completed":
        raise ErrorPublicacion(f"La run {run_id} todavía no terminó.")
    if _texto(datos, "conclusion", url) != "success":
        raise ErrorPublicacion(f"La run {run_id} no terminó en success; no se publica nada.")
    return datos


def verificar_job_empaquetado(
    cliente: ClienteApiGitHub, repositorio: str, run_id: int, sha: str
) -> dict[str, Any]:
    """Exige el job exacto de empaquetado, exitoso y del mismo ``head_sha``."""

    url = f"https://{HOST_API}/repos/{repositorio}/actions/runs/{run_id}/jobs?per_page=100"
    datos = _objeto(cliente.obtener(url), url)
    crudos = datos.get("jobs")
    total = datos.get("total_count")
    if not isinstance(crudos, list) or not isinstance(total, int) or isinstance(total, bool):
        raise ErrorPublicacion(f"{url} no devolvió una lista de jobs utilizable.")
    jobs: list[Any] = cast(list[Any], crudos)
    if total > len(jobs):
        raise ErrorPublicacion(f"{url} vino paginado; no se puede demostrar unicidad del job.")

    coincidencias: list[dict[str, Any]] = [
        _objeto(job, url) for job in jobs if _objeto(job, url).get("name") == NOMBRE_JOB_EMPAQUETADO
    ]
    if len(coincidencias) != 1:
        raise ErrorPublicacion(
            f"Se esperaba exactamente un job {NOMBRE_JOB_EMPAQUETADO} en la run {run_id} y se "
            f"encontraron {len(coincidencias)}."
        )
    job = coincidencias[0]
    if _texto(job, "conclusion", url) != "success":
        raise ErrorPublicacion(f"El job {NOMBRE_JOB_EMPAQUETADO} no terminó en success.")
    if _texto(job, "head_sha", url) != sha:
        raise ErrorPublicacion(f"El job {NOMBRE_JOB_EMPAQUETADO} no corresponde al SHA {sha}.")
    return job


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
    run: Mapping[str, Any],
    job: Mapping[str, Any],
) -> dict[str, Any]:
    """Arma el documento que ata publicación, commit, árbol Git y CI.

    Es el tercer asset de la publicación. El consumidor lo valida campo por
    campo y compara su ``tree_sha`` con el de ``release.json``: esa doble
    verificación es lo que impide combinar los metadatos de un SHA con el tar de
    otro.
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
            "run_id": run["id"],
            "run_number": run["run_number"],
            "run_attempt": run["run_attempt"],
            "job": NOMBRE_JOB_EMPAQUETADO,
            "job_id": job["id"],
        },
        "paquete": {"nombre": nombre_paquete(sha), "sha256": checksum, "tamano": tamano},
        "sidecar": {"nombre": nombre_sidecar(sha)},
    }


def _sha256_bytes(datos: bytes) -> str:
    """Checksum de un contenido ya en memoria, para comparar assets chicos."""

    return hashlib.sha256(datos).hexdigest()


def _comparar_publicacion_existente(
    cliente: ClienteApiGitHub,
    release: Mapping[str, Any],
    esperados: Mapping[str, bytes],
    directorio_temporal: Path,
) -> None:
    """Confirma idempotencia o aborta: nunca reemplaza bytes ya publicados.

    Entradas:
        release: objeto de la release existente devuelto por el API.
        esperados: contenido local de cada asset, indexado por nombre.
        directorio_temporal: dónde bajar los assets publicados para compararlos.

    Errores:
        ErrorPublicacion si falta un asset, sobra uno o difiere el contenido.
        Cualquiera de esos casos exige intervención humana, porque una release
        publicada es inmutable y divergir de ella indica un problema real.
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

    if set(publicados) != set(esperados):
        raise ErrorPublicacion(
            "La release ya existe con un conjunto de assets distinto "
            f"({sorted(publicados)} frente a {sorted(esperados)}). No se reemplaza nada; "
            "se requiere intervención humana."
        )

    for nombre, contenido in esperados.items():
        destino = directorio_temporal / f"publicado-{nombre}"
        cliente.descargar(publicados[nombre], destino)
        if _sha256_bytes(destino.read_bytes()) != _sha256_bytes(contenido):
            raise ErrorPublicacion(
                f"El asset {nombre} ya publicado difiere byte a byte del local. Una release "
                "publicada es inmutable: se aborta sin reemplazarla."
            )


def publicar_release(
    cliente: ClienteApiGitHub,
    *,
    repositorio: str,
    sha: str,
    run_id: int,
    directorio: Path,
) -> dict[str, Any]:
    """Ejecuta la publicación completa y devuelve un resumen serializable.

    Resultado: diccionario con el tag, el estado (``creada`` o ``idempotente``),
    el commit, el árbol y la run de CI habilitante.

    Efectos laterales: crea la GitHub Release y sube tres assets, o no escribe
    nada si ya estaba publicada de forma idéntica.
    """

    sha = validar_sha(sha)
    run = verificar_run_habilitante(cliente, repositorio, run_id, sha)
    job = verificar_job_empaquetado(cliente, repositorio, run_id, sha)

    paquete, sidecar = localizar_artefactos(directorio, sha)
    checksum = verificar_checksum(paquete, sidecar)
    manifest = inspeccionar_manifest_paquete(paquete, sha)
    tree_sha = validar_sha(str(manifest["tree_sha"]))

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

    esperados: dict[str, bytes] = {
        paquete.name: paquete.read_bytes(),
        sidecar.name: sidecar.read_bytes(),
        ruta_metadatos.name: contenido_metadatos,
    }

    tag = tag_publicacion(sha)
    url_tag = (
        f"https://{HOST_API}/repos/{repositorio}/releases/tags/{urllib.parse.quote(tag, safe='')}"
    )
    existente = cliente.obtener(url_tag)
    if existente is not None:
        _comparar_publicacion_existente(cliente, _objeto(existente, url_tag), esperados, directorio)
        return {
            "tag": tag,
            "estado": "idempotente",
            "commit_sha": sha,
            "tree_sha": tree_sha,
            "ci_run_id": run_id,
        }

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
                    f"- CI habilitante: run `{run_id}` del workflow `{NOMBRE_WORKFLOW_CI}` "
                    f"sobre `{RAMA_PUBLICACION}`\n"
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
        "ci_run_id": run_id,
    }


def crear_parser() -> argparse.ArgumentParser:
    """CLI invocada por el workflow de publicación."""

    parser = argparse.ArgumentParser(
        description="Publica la release pública inmutable de un SHA de main."
    )
    parser.add_argument("--repositorio", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--run-id", required=True, type=int)
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
            directorio=opciones.directorio.resolve(),
        )
    except (ErrorPublicacion, ErrorDespliegue, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(resumen, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
