"""Estado formal del host institucional, lock global y contrato ``target-release`` (WP-101A).

¿Por qué existe este módulo?
----------------------------

Durante la transición Legacy -> SIS-Leg el host institucional tiene **dos**
sistemas instalados y alternables. Antes de actualizar o conmutar hay que poder
responder, con evidencia y sin adivinar, tres preguntas:

1. ¿en qué estado formal está el host ahora mismo?
2. ¿hay una operación mutante ya en curso?
3. ¿qué release debería activarse cuando alguien pulse «Cambiar a SIS-Leg»?

Hasta WP-100 esas tres respuestas vivían en scripts que sólo existían dentro del
host institucional (``/usr/local/bin/sisleg-estado`` y compañía), sin pruebas ni
revisión. WP-101A las convierte en código versionado del producto: lo mismo que
el host ejecuta es lo que la CI revisa y prueba.

Qué **no** hace este módulo
---------------------------

No muta nada. Clasificar, leer el target y tomar el lock son operaciones de
diagnóstico y de exclusión mutua; las mutaciones reales viven en
``deploy/operaciones_host.py`` y siguen delegando en los motores canónicos
``deploy/herramienta_despliegue.py`` y ``deploy/actualizador_publico.py``.

La única excepción es :func:`escribir_target_release`, que sí escribe un archivo
—pero sólo después de demostrar, con ocho comprobaciones, que el SHA que va a
escribir corresponde a una release realmente preparada y validada.

Todas las fronteras privilegiadas (systemd, sockets, filesystem del host) son
inyectables, de modo que la suite de pruebas ejercita el módulo completo sobre
raíces temporales, sin systemd, sin Nginx y sin tocar ``/opt/sis-leg``.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import socket
import sys
from collections.abc import Callable, Generator, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

# Producción invoca estos módulos como scripts sueltos desde la release
# (``python3.14 /opt/sis-leg/releases/<SHA>/deploy/estado_host.py ...``). En esa
# forma Python agrega ``deploy/`` a ``sys.path`` y no la raíz de la release, así
# que el paquete ``deploy`` todavía no sería importable. Se hace explícita esa
# raíz con el mismo criterio que los módulos canónicos anteriores.
RAIZ_PARA_IMPORTS = Path(__file__).resolve().parents[1]
if str(RAIZ_PARA_IMPORTS) not in sys.path:
    sys.path.insert(0, str(RAIZ_PARA_IMPORTS))

from deploy.herramienta_despliegue import (  # noqa: E402 - raíz preparada arriba
    MARCADOR_PREPARADA,
    SERVICIO_BACKEND,
    SERVICIO_BRIDGE,
    EjecutorComandos,
    EjecutorSubprocess,
    ErrorDespliegue,
    resolver_enlace_release,
    validar_identidad_arbol,
    validar_sha,
)

# --------------------------------------------------------------------------
# Constantes del host en transición
# --------------------------------------------------------------------------

# Unidades del sistema anterior. El nombre no se traduce: es el identificador
# real de systemd en el host institucional y renombrarlo rompería la operación.
SERVICIO_BACKEND_LEGACY = "botonera-backend.service"
SERVICIO_BRIDGE_LEGACY = "botonera-teclados.service"

# Vhosts mutuamente excluyentes. Legacy publica un symlink bajo ``sites-enabled``
# y SIS-Leg un archivo bajo ``conf.d``; nunca se mezclan los dos mecanismos,
# porque entonces sería ambiguo cuál gana.
RUTA_VHOST_LEGACY = Path("/etc/nginx/sites-enabled/botonera")
RUTA_VHOST_LEGACY_DISPONIBLE = Path("/etc/nginx/sites-available/botonera")
RUTA_VHOST_SISLEG = Path("/etc/nginx/conf.d/sis-leg.conf")
SUFIJO_VHOST_DESHABILITADO = ".disabled"

# Puertos que sirven como evidencia adicional del estado real: :8000 lo ocupa
# exactamente un backend (Legacy o SIS-Leg, nunca los dos) y :8765 sólo existe
# cuando el device bridge de SIS-Leg está tomando el hardware.
PUERTO_BACKEND = 8000
PUERTO_BRIDGE_SISLEG = 8765

# Guard institucional del lado Legacy. El backend anterior expone su propio
# estado global y el campo ``hay_sesion``; se consulta directamente al backend
# y no a través de Nginx para no depender de qué vhost esté publicado.
URL_ESTADO_LEGACY = f"http://127.0.0.1:{PUERTO_BACKEND}/estados/estado_global"

# Lock global compartido por conmutación y actualización. Es el mismo archivo
# para las tres operaciones: nunca pueden correr dos a la vez.
RUTA_LOCK_OPERACION = Path("/run/lock/sis-leg-operacion.lock")

# Nombre del archivo que responde «qué release hay que activar». Vive en la raíz
# de la instalación y no dentro de una release, justamente porque debe poder
# leerse cuando SIS-Leg no está activo y no existe ``current``.
NOMBRE_TARGET_RELEASE = "target-release"

# Estados formales reconocidos. Cualquier mezcla que no encaje exactamente en
# uno de los tres primeros es inconsistente, y ninguna operación mutante puede
# partir de ahí.
ESTABLE_LEGACY = "ESTABLE_LEGACY"
ESTABLE_SISLEG = "ESTABLE_SISLEG"
INERTE_SEGURO = "INERTE_SEGURO"
ESTADO_INCONSISTENTE = "ESTADO_INCONSISTENTE"

ESTADOS_OPERATIVOS = (ESTABLE_LEGACY, ESTABLE_SISLEG)


class ErrorEstadoHost(RuntimeError):
    """Falla segura al inspeccionar el host o al escribir ``target-release``.

    Que esta excepción llegue al llamador significa siempre lo mismo: no se pudo
    demostrar una precondición, así que no se mutó nada y la operación tiene que
    abortar en lugar de suponer.
    """


# --------------------------------------------------------------------------
# Lock global de operación
# --------------------------------------------------------------------------


@contextlib.contextmanager
def lock_operacion_global(ruta: Path = RUTA_LOCK_OPERACION) -> Generator[Path]:
    """Toma el lock exclusivo compartido por actualización y conmutación.

    Entradas:
        ruta: archivo de lock. En producción es ``/run/lock/sis-leg-operacion.lock``;
            las pruebas inyectan una ruta temporal.

    Resultado: context manager que entrega la ruta del lock efectivamente tomado.

    Efectos laterales: crea el archivo de lock si no existe y mantiene un
    descriptor abierto mientras dure el bloque.

    Errores:
        ErrorEstadoHost si otro proceso ya tiene el lock. Es deliberadamente no
        bloqueante: si hay otra operación en curso, la conducta correcta es
        informar y salir, no quedarse esperando detrás de una conmutación que
        puede tardar minutos.

    Se usa ``flock`` y no un archivo PID porque el kernel libera un ``flock``
    automáticamente cuando el proceso muere, incluso si muere de forma abrupta.
    Un lock por archivo PID puede quedar huérfano y bloquear el host hasta que
    alguien lo borre a mano.
    """

    ruta.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(ruta, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ErrorEstadoHost(
                f"Ya hay una operación de SIS-Leg en curso (lock {ruta} tomado): {error}"
            ) from error
        try:
            yield ruta
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


# --------------------------------------------------------------------------
# Evidencia y clasificación del estado formal
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EvidenciaEstado:
    """Hechos observados del host, antes de interpretarlos.

    Se separa la **evidencia** de la **clasificación** a propósito: cuando un
    host queda en ``ESTADO_INCONSISTENTE`` lo primero que necesita una persona
    es ver qué se observó exactamente, no solamente la etiqueta final.

    Atributos:
        legacy_backend_activo, legacy_bridge_activo: ``systemctl is-active`` de
            las unidades del sistema anterior.
        legacy_backend_habilitado, legacy_bridge_habilitado: ``is-enabled`` de
            las mismas unidades. Importa porque la conmutación segura
            deshabilita antes de detener (*disable-first*).
        sisleg_backend_activo, sisleg_bridge_activo: lo mismo para SIS-Leg.
        sisleg_backend_habilitado, sisleg_bridge_habilitado: ídem.
        nginx_activo: si el único punto de entrada HTTP está corriendo.
        vhost_legacy_publicado, vhost_sisleg_publicado: qué configuración de
            Nginx está efectivamente incluida.
        puerto_backend_ocupado: alguien escucha en ``:8000``.
        puerto_bridge_ocupado: alguien escucha en ``:8765``.
        release_actual: SHA al que apunta ``current``, o ``None``.
        target_release: contenido validado de ``target-release``, o ``None``
            cuando no existe **o** cuando existe pero está corrupto.
        target_release_diagnostico: por qué no se pudo leer el objetivo, cuando
            el archivo existe pero es inválido. Es ``None`` en el caso normal.

    ¿Por qué el target corrupto no rompe la evidencia? Porque identificar qué
    sistema está atendiendo el recinto no depende de qué release debería
    activarse en el futuro. Si un ``target-release`` ilegible impidiera
    clasificar el host, también impediría la salida segura hacia el sistema
    anterior, que es justamente la operación que nunca puede quedar bloqueada.
    El diagnóstico se conserva y se muestra; simplemente no se confunde con un
    hecho del estado actual.
    """

    legacy_backend_activo: bool
    legacy_bridge_activo: bool
    legacy_backend_habilitado: bool
    legacy_bridge_habilitado: bool
    sisleg_backend_activo: bool
    sisleg_bridge_activo: bool
    sisleg_backend_habilitado: bool
    sisleg_bridge_habilitado: bool
    nginx_activo: bool
    vhost_legacy_publicado: bool
    vhost_sisleg_publicado: bool
    puerto_backend_ocupado: bool
    puerto_bridge_ocupado: bool
    release_actual: str | None
    target_release: str | None
    target_release_diagnostico: str | None = None


def puerto_ocupado(puerto: int, *, tiempo_espera: float = 0.5) -> bool:
    """Comprueba si alguien escucha en loopback sin abrir una conexión larga.

    Se usa como evidencia complementaria de systemd: un servicio puede figurar
    ``active`` mientras su proceso real ya murió, y al revés, un proceso suelto
    lanzado a mano puede ocupar el puerto sin unidad asociada. Las dos
    situaciones son inconsistentes y conviene detectarlas.
    """

    try:
        with socket.create_connection(("127.0.0.1", puerto), timeout=tiempo_espera):
            return True
    except OSError:
        return False


class InspectorEstadoHost:
    """Clasifica el host institucional sin modificarlo jamás.

    Todas las fronteras son inyectables:

    - ``ejecutor`` habla con systemd (``is-active`` / ``is-enabled``);
    - ``sonda_puerto`` dice si un puerto de loopback está ocupado;
    - ``consultor_json`` consulta el guard institucional por HTTP;
    - las rutas de vhosts y la raíz de la instalación son parámetros.

    Por eso las pruebas pueden reproducir Legacy activo, SIS-Leg activo, estados
    inertes y mezclas inconsistentes sobre un ``tmp_path``, sin systemd real.
    """

    def __init__(
        self,
        raiz: Path = Path("/opt/sis-leg"),
        *,
        ejecutor: EjecutorComandos | None = None,
        sonda_puerto: Callable[[int], bool] = puerto_ocupado,
        consultor_json: Callable[[str, float], dict[str, Any]] | None = None,
        ruta_vhost_legacy: Path = RUTA_VHOST_LEGACY,
        ruta_vhost_sisleg: Path = RUTA_VHOST_SISLEG,
    ) -> None:
        self.raiz = raiz.resolve()
        self.releases = self.raiz / "releases"
        self.current = self.raiz / "current"
        self.ejecutor = ejecutor or EjecutorSubprocess()
        self.sonda_puerto = sonda_puerto
        # Se importa perezosamente el consultor canónico para no duplicar la
        # política de timeouts y de validación de respuesta JSON.
        if consultor_json is None:
            from deploy.herramienta_despliegue import consultar_json

            consultor_json = consultar_json
        self.consultor_json = consultor_json
        self.ruta_vhost_legacy = ruta_vhost_legacy
        self.ruta_vhost_sisleg = ruta_vhost_sisleg

    # -- fronteras elementales -------------------------------------------------

    def _es_activo(self, unidad: str) -> bool:
        """``systemctl is-active`` traducido a un booleano estricto."""

        resultado = self.ejecutor.ejecutar(["systemctl", "is-active", unidad], comprobar=False)
        return resultado.salida.strip() == "active"

    def _es_habilitado(self, unidad: str) -> bool:
        """``systemctl is-enabled`` traducido a un booleano estricto.

        ``enabled-runtime`` no cuenta como habilitado: sobrevive hasta el
        próximo reinicio y no es lo que la conmutación *disable-first* pretende
        garantizar.
        """

        resultado = self.ejecutor.ejecutar(["systemctl", "is-enabled", unidad], comprobar=False)
        return resultado.salida.strip() == "enabled"

    def esta_activa(self, unidad: str) -> bool:
        """Frontera pública hacia ``is-active``, reutilizable por las operaciones."""

        return self._es_activo(unidad)

    def esta_habilitada(self, unidad: str) -> bool:
        """Frontera pública hacia ``is-enabled``, reutilizable por las operaciones.

        Las conmutaciones necesitan conocer el estado de habilitación **antes**
        de deshabilitar, para poder restaurarlo exactamente si tienen que hacer
        rollback. Sin este dato, un rollback dejaría el sistema anterior vivo
        pero sin volver a arrancar en el próximo reinicio.
        """

        return self._es_habilitado(unidad)

    def evidencia(self) -> EvidenciaEstado:
        """Observa el host completo y devuelve los hechos, sin interpretarlos."""

        try:
            actual = resolver_enlace_release(self.current, self.releases)
        except ErrorDespliegue:
            # ``current`` apuntando fuera de releases es en sí mismo una
            # inconsistencia; se registra como «sin release actual» y la
            # clasificación la tratará como estado no operativo.
            actual = None
        objetivo, diagnostico_objetivo = leer_target_release_tolerante(self.raiz)
        return EvidenciaEstado(
            legacy_backend_activo=self._es_activo(SERVICIO_BACKEND_LEGACY),
            legacy_bridge_activo=self._es_activo(SERVICIO_BRIDGE_LEGACY),
            legacy_backend_habilitado=self._es_habilitado(SERVICIO_BACKEND_LEGACY),
            legacy_bridge_habilitado=self._es_habilitado(SERVICIO_BRIDGE_LEGACY),
            sisleg_backend_activo=self._es_activo(SERVICIO_BACKEND),
            sisleg_bridge_activo=self._es_activo(SERVICIO_BRIDGE),
            sisleg_backend_habilitado=self._es_habilitado(SERVICIO_BACKEND),
            sisleg_bridge_habilitado=self._es_habilitado(SERVICIO_BRIDGE),
            nginx_activo=self._es_activo("nginx.service"),
            vhost_legacy_publicado=self.ruta_vhost_legacy.exists(),
            vhost_sisleg_publicado=self.ruta_vhost_sisleg.is_file(),
            puerto_backend_ocupado=self.sonda_puerto(PUERTO_BACKEND),
            puerto_bridge_ocupado=self.sonda_puerto(PUERTO_BRIDGE_SISLEG),
            release_actual=actual.name if actual is not None else None,
            target_release=objetivo,
            target_release_diagnostico=diagnostico_objetivo,
        )

    # -- clasificación ---------------------------------------------------------

    def clasificar(self, evidencia: EvidenciaEstado | None = None) -> str:
        """Traduce la evidencia a uno de los cuatro estados formales.

        Las tres formas reconocidas son deliberadamente estrictas: cada una
        exige que **todo** el conjunto sea coherente, no sólo que el sistema
        esperado esté vivo. Cualquier otra combinación es
        ``ESTADO_INCONSISTENTE``, que no habilita ninguna mutación.

        Un estado estable exige además que el sistema que **no** manda esté
        deshabilitado, y no solamente apagado. Un host con Legacy en servicio
        pero con las unidades de SIS-Leg todavía ``enabled`` está a un reinicio
        de tener los dos sistemas peleando por el mismo puerto y por los mismos
        numpads: eso es exactamente lo que la regla *disable-first* existe para
        impedir, así que no puede declararse estable.
        """

        datos = evidencia if evidencia is not None else self.evidencia()

        sisleg_apagado = not datos.sisleg_backend_activo and not datos.sisleg_bridge_activo
        legacy_apagado = not datos.legacy_backend_activo and not datos.legacy_bridge_activo
        sisleg_deshabilitado = (
            not datos.sisleg_backend_habilitado and not datos.sisleg_bridge_habilitado
        )
        legacy_deshabilitado = (
            not datos.legacy_backend_habilitado and not datos.legacy_bridge_habilitado
        )

        if (
            datos.legacy_backend_activo
            and datos.legacy_bridge_activo
            and datos.legacy_backend_habilitado
            and datos.legacy_bridge_habilitado
            and sisleg_apagado
            and sisleg_deshabilitado
            and datos.vhost_legacy_publicado
            and not datos.vhost_sisleg_publicado
            and datos.nginx_activo
            and datos.puerto_backend_ocupado
            and not datos.puerto_bridge_ocupado
        ):
            return ESTABLE_LEGACY

        if (
            datos.sisleg_backend_activo
            and datos.sisleg_bridge_activo
            and datos.sisleg_backend_habilitado
            and datos.sisleg_bridge_habilitado
            and legacy_apagado
            and legacy_deshabilitado
            and datos.vhost_sisleg_publicado
            and not datos.vhost_legacy_publicado
            and datos.nginx_activo
            and datos.puerto_backend_ocupado
            and datos.puerto_bridge_ocupado
            and datos.release_actual is not None
        ):
            return ESTABLE_SISLEG

        if (
            legacy_apagado
            and sisleg_apagado
            and not datos.puerto_backend_ocupado
            and not datos.puerto_bridge_ocupado
        ):
            return INERTE_SEGURO

        return ESTADO_INCONSISTENTE

    def exigir_unidades_deshabilitadas(self, unidades: Sequence[str]) -> None:
        """Demuestra que un ``disable`` previo fue realmente efectivo.

        Entradas:
            unidades: nombres de unidades de systemd que deberían haber quedado
                deshabilitadas.

        Efectos laterales: ninguno; sólo consulta ``is-enabled``.

        Errores:
            ErrorEstadoHost si alguna sigue habilitada.

        Las retiradas ejecutan ``systemctl disable`` sin exigir código de salida
        cero, porque una unidad enmascarada o ya deshabilitada devuelve códigos
        distintos según la versión de systemd. Tolerar el código de salida sólo
        es aceptable si después se comprueba el efecto: sin esta comprobación,
        un ``disable`` que falló en silencio dejaría el sistema saliente listo
        para volver a arrancar en el próximo reinicio.
        """

        habilitadas = [unidad for unidad in unidades if self._es_habilitado(unidad)]
        if habilitadas:
            raise ErrorEstadoHost(
                "Estas unidades debían quedar deshabilitadas y siguen habilitadas: "
                f"{', '.join(habilitadas)}. Se detiene la operación antes de continuar."
            )

    def exigir_maximo_un_bridge(self) -> None:
        """Falla cerrado si los dos device bridges están activos a la vez.

        Es la invariante más rígida de toda la instalación: los dos bridges
        toman los mismos numpads con ``EVIOCGRAB``. Si convivieran, las
        pulsaciones quedarían capturadas por un proceso impredecible y el
        registro institucional dejaría de ser confiable.

        Se comprueba después de **cada** transición de servicios, no sólo al
        principio y al final, para que una secuencia mal ordenada se detecte en
        el paso exacto que la introdujo.
        """

        if self._es_activo(SERVICIO_BRIDGE_LEGACY) and self._es_activo(SERVICIO_BRIDGE):
            raise ErrorEstadoHost(
                "Los dos device bridges quedaron activos simultáneamente; "
                "se detiene la operación para no dejar el hardware en un estado ambiguo."
            )

    def guard_institucional_legacy(self) -> None:
        """Exige que el sistema anterior no tenga una sesión en curso.

        El backend Legacy expone ``hay_sesion``. Se falla cerrado en tres casos:
        la consulta no se puede resolver, la respuesta no declara el campo, o el
        campo dice que hay sesión. Actualizar o conmutar con el cuerpo sesionando
        sería exactamente el accidente que este guard existe para impedir.
        """

        try:
            datos = self.consultor_json(URL_ESTADO_LEGACY, 3.0)
        except Exception as error:  # noqa: BLE001 - cualquier falla de frontera es bloqueante
            raise ErrorEstadoHost(
                f"No se pudo consultar el estado del sistema anterior en {URL_ESTADO_LEGACY}: "
                f"{error}"
            ) from error
        hay_sesion = datos.get("hay_sesion")
        if not isinstance(hay_sesion, bool):
            raise ErrorEstadoHost(
                "El sistema anterior no declaró hay_sesion como booleano; se aborta sin mutar."
            )
        if hay_sesion:
            raise ErrorEstadoHost(
                "El sistema anterior declara una sesión en curso; ninguna operación puede mutar."
            )


# --------------------------------------------------------------------------
# Contrato de ``target-release``
# --------------------------------------------------------------------------


def ruta_target_release(raiz: Path) -> Path:
    """Ruta canónica del archivo ``target-release`` dentro de la instalación."""

    return raiz / NOMBRE_TARGET_RELEASE


def leer_target_release(raiz: Path) -> str | None:
    """Lee el SHA declarado como objetivo, o ``None`` si no hay uno legible.

    Resultado: el SHA de 40 caracteres si el archivo existe y tiene exactamente
    la forma canónica; ``None`` si el archivo no existe.

    Errores:
        ErrorEstadoHost si el archivo existe pero no es un archivo regular, es
        un enlace, no se puede leer o su contenido no es un SHA válido. Un
        ``target-release`` corrupto no se interpreta con tolerancia: es una
        condición que exige intervención humana.
    """

    ruta = ruta_target_release(raiz)
    if not ruta.exists():
        return None
    if ruta.is_symlink() or not ruta.is_file():
        raise ErrorEstadoHost(f"{ruta} debe ser un archivo regular y no un enlace.")
    try:
        contenido = ruta.read_text(encoding="utf-8")
    except OSError as error:
        raise ErrorEstadoHost(f"No se pudo leer {ruta}: {error}") from error
    try:
        return validar_sha(contenido.strip())
    except ErrorDespliegue as error:
        raise ErrorEstadoHost(f"{ruta} no contiene un SHA de release válido: {error}") from error


def leer_target_release_tolerante(raiz: Path) -> tuple[str | None, str | None]:
    """Lee el objetivo sin convertir un archivo corrupto en un bloqueo.

    Resultado: una tupla ``(sha, diagnostico)``. En el caso normal el
    diagnóstico es ``None``; si el archivo existe pero es inválido, el SHA es
    ``None`` y el diagnóstico explica por qué.

    ¿Cuándo usar esta lectura y cuándo la estricta? La estricta
    (:func:`leer_target_release`) gobierna todo lo que **usa** el objetivo:
    actualizar y cambiar a SIS-Leg fallan cerrado si no pueden confiar en él.
    Esta versión tolerante gobierna lo que sólo **informa** sobre él: la
    evidencia del estado y el regreso al sistema anterior, que son
    version-agnósticos y no deben depender de un archivo que ni siquiera van a
    consumir.
    """

    try:
        return leer_target_release(raiz), None
    except ErrorEstadoHost as error:
        return None, str(error)


def eliminar_target_release(raiz: Path) -> bool:
    """Deja la instalación sin ningún objetivo declarado.

    Resultado: ``True`` si había un archivo y se borró; ``False`` si ya no había
    nada que borrar.

    Efectos laterales: elimina ``<raiz>/target-release``.

    Errores:
        ErrorEstadoHost si el archivo existe y no se puede borrar.

    Existe únicamente para poder **restaurar la ausencia**. Un host puede tener
    SIS-Leg en servicio sin haber declarado nunca un objetivo, y si una
    actualización falla después de escribir uno, dejarlo escrito sería inventar
    un estado que el host no tenía. Restaurar exactamente lo anterior incluye
    restaurar el hecho de que no había nada.

    No valida nada porque no hay nada que validar: borrar el objetivo nunca
    puede activar contenido arbitrario. La comprobación estricta vive en
    :func:`escribir_target_release`, que es la operación peligrosa.
    """

    ruta = ruta_target_release(raiz)
    try:
        existia = ruta.exists() or ruta.is_symlink()
        ruta.unlink(missing_ok=True)
    except OSError as error:
        raise ErrorEstadoHost(f"No se pudo eliminar {ruta}: {error}") from error
    return existia


def validar_release_objetivo(raiz: Path, sha: str) -> Path:
    """Aplica las ocho comprobaciones exigidas antes de confiar en un SHA.

    Entradas:
        raiz: raíz de la instalación (``/opt/sis-leg`` en producción).
        sha: SHA candidato, tal como vendría de ``target-release`` o del canal
            público.

    Resultado: la ruta de la release validada.

    Efectos laterales: ninguno.

    Las ocho comprobaciones, en orden y sin atajos:

    1. formato: 40 hexadecimales en minúscula;
    2. ``releases/<SHA>`` existe;
    3. no es un enlace simbólico;
    4. resuelve exactamente a esa ruta, sin traversal;
    5. el marcador de release preparada existe y es un archivo regular;
    6. el marcador parsea como JSON;
    7. ``marcador.commit_sha == <SHA>``;
    8. ``marcador.tree_sha`` es un árbol Git válido y coincide con el que
       declara el ``release.json`` que viajó dentro del paquete público.

    Ninguna es decorativa: un ``target-release`` manipulado sería una vía
    directa para activar contenido arbitrario, y la implementación original en
    el host llegó a producción sin varias de ellas. Ese fue uno de los hallazgos
    que la auditoría de WP-029 obligó a corregir.

    La octava se delega en :func:`validar_identidad_arbol`, del motor canónico,
    en lugar de releerse acá: la identidad de una release se valida en un único
    lugar del producto, no en dos implementaciones que podrían divergir.
    """

    try:
        sha_validado = validar_sha(sha)
    except ErrorDespliegue as error:
        raise ErrorEstadoHost(f"SHA de release inválido: {error}") from error

    releases = (raiz / "releases").resolve()
    release = releases / sha_validado
    if not release.exists():
        raise ErrorEstadoHost(f"La release {sha_validado} no existe en {releases}.")
    if release.is_symlink():
        raise ErrorEstadoHost(f"La release {sha_validado} no puede ser un enlace simbólico.")
    if release.resolve() != release:
        raise ErrorEstadoHost(
            f"La release {sha_validado} no resuelve exactamente a {release}; hay traversal."
        )
    marcador = release / MARCADOR_PREPARADA
    if marcador.is_symlink() or not marcador.is_file():
        raise ErrorEstadoHost(
            f"La release {sha_validado} no tiene un marcador de preparación regular."
        )
    try:
        datos: Any = json.loads(marcador.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ErrorEstadoHost(
            f"El marcador de la release {sha_validado} no es JSON legible: {error}"
        ) from error
    if not isinstance(datos, dict) or cast(dict[str, Any], datos).get("commit_sha") != (
        sha_validado
    ):
        raise ErrorEstadoHost(
            f"El marcador de la release {sha_validado} no declara ese mismo commit_sha."
        )
    try:
        validar_identidad_arbol(release, cast(dict[str, Any], datos))
    except ErrorDespliegue as error:
        raise ErrorEstadoHost(
            f"La release {sha_validado} no demuestra su identidad de árbol: {error}"
        ) from error
    return release


def escribir_target_release(raiz: Path, sha: str) -> Path:
    """Fija atómicamente qué release debe activar «Cambiar a SIS-Leg».

    Entradas:
        raiz: raíz de la instalación.
        sha: SHA de una release **ya preparada y validada**.

    Resultado: la ruta del archivo escrito.

    Efectos laterales: crea o reemplaza ``<raiz>/target-release`` con el SHA y un
    salto de línea, modo ``0644``.

    Errores:
        ErrorEstadoHost si el SHA no supera :func:`validar_release_objetivo`.

    El reemplazo es atómico —temporal en el mismo directorio más ``os.replace``—
    porque un lector concurrente nunca debe poder ver medio SHA. Y la validación
    va **antes** de escribir: el archivo jamás puede quedar apuntando a una
    release incompleta.
    """

    validar_release_objetivo(raiz, sha)
    destino = ruta_target_release(raiz)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_name(f".{destino.name}.nuevo-{os.getpid()}")
    temporal.unlink(missing_ok=True)
    try:
        temporal.write_text(f"{sha}\n", encoding="utf-8")
        os.chmod(temporal, 0o644)
        os.replace(temporal, destino)
    except OSError as error:
        raise ErrorEstadoHost(f"No se pudo fijar {destino}: {error}") from error
    finally:
        temporal.unlink(missing_ok=True)
    return destino


# --------------------------------------------------------------------------
# CLI de diagnóstico
# --------------------------------------------------------------------------


def crear_parser() -> argparse.ArgumentParser:
    """CLI exclusivamente de lectura: clasificar y mostrar evidencia.

    No existe ningún subcomando que mute el host. Escribir ``target-release`` es
    una consecuencia de una operación completa, no un comando suelto que alguien
    pueda invocar para «arreglar» un estado a mano.
    """

    parser = argparse.ArgumentParser(
        description="Clasifica el estado formal del host institucional sin modificarlo."
    )
    parser.add_argument("--raiz", type=Path, default=Path("/opt/sis-leg"))
    parser.add_argument(
        "--tag",
        action="store_true",
        help="Imprime solamente la etiqueta del estado formal.",
    )
    return parser


def main(argumentos: Sequence[str] | None = None) -> int:
    """Imprime la etiqueta o el informe completo y traduce fallas a código 1."""

    opciones = crear_parser().parse_args(argumentos)
    inspector = InspectorEstadoHost(opciones.raiz)
    try:
        evidencia = inspector.evidencia()
        estado = inspector.clasificar(evidencia)
    except (ErrorEstadoHost, ErrorDespliegue, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    if opciones.tag:
        print(estado)
        return 0
    print(
        json.dumps(
            {"estado": estado, "evidencia": asdict(evidencia)},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
