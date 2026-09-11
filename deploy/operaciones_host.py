"""Las tres operaciones de usuario del host institucional, versionadas (WP-101A).

Qué resuelve este módulo
------------------------

En el host institucional existen hoy tres botones: «Actualizar SIS-Leg»,
«Cambiar a SIS-Leg» y «Cambiar a Legacy». Hasta WP-100 esos tres botones
ejecutaban scripts que **sólo vivían en esa máquina**: sin versionado, sin
revisión independiente y sin pruebas. Cualquier corrección exigía volver a
programar sobre el host.

WP-101A convierte esas tres operaciones en código del producto. La regla de
diseño es que este módulo **orquesta** y no reimplementa:

- la validación de una release pública (SHA, publicación, evidencia de CI,
  assets, checksum, manifest, árbol) es de ``deploy/actualizador_publico.py``;
- la preparación, la activación, el health, la convergencia de Nginx, el
  rollback y el contrato add-only de configuración son de
  ``deploy/herramienta_despliegue.py`` y ``deploy/configuracion_local.py``;
- la clasificación del estado formal, el lock global y ``target-release`` son de
  ``deploy/estado_host.py``.

Lo único que agrega este módulo es lo que ninguno de ellos podía saber: que en
esta máquina conviven **dos** sistemas, y que retirar uno antes de instalar el
otro tiene un orden seguro que no se puede improvisar.

La invariante que gobierna todo
-------------------------------

Nunca pueden estar activos los dos device bridges a la vez. Los dos toman los
mismos numpads con ``EVIOCGRAB``; si convivieran, las pulsaciones quedarían
capturadas por un proceso impredecible y el registro institucional dejaría de
ser confiable. Por eso toda conmutación deshabilita el sistema saliente **antes**
de detenerlo (*disable-first*), arranca el bridge entrante **después** de que su
backend respondió health, y comprueba la exclusión en cada transición.

Nada de esto se prueba contra systemd, Nginx o ``/opt/sis-leg`` reales: todas las
fronteras privilegiadas son inyectables y la suite las ejercita sobre raíces
temporales.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Producción invoca este módulo como script suelto desde la release preparada
# (``python3.14 /opt/sis-leg/releases/<SHA>/deploy/operaciones_host.py ...``), con
# lo cual Python sólo agrega ``deploy/`` a ``sys.path``. Se hace explícita la raíz
# igual que en el resto de los módulos de despliegue.
RAIZ_PARA_IMPORTS = Path(__file__).resolve().parents[1]
if str(RAIZ_PARA_IMPORTS) not in sys.path:
    sys.path.insert(0, str(RAIZ_PARA_IMPORTS))

from deploy.actualizador_publico import (  # noqa: E402 - raíz preparada arriba
    REPOSITORIO_PREDETERMINADO,
    ClienteHttpPublicoReal,
    ErrorActualizadorPublico,
    ReleaseDescargada,
    obtener_release_publica,
    resolver_sha_main,
)
from deploy.configuracion_local import (  # noqa: E402 - raíz preparada arriba
    ACCION_CREAR,
    ErrorConfiguracionLocal,
    exigir_plan_sin_migraciones,
)
from deploy.estado_host import (  # noqa: E402 - raíz preparada arriba
    ESTABLE_LEGACY,
    ESTABLE_SISLEG,
    ESTADOS_OPERATIVOS,
    PUERTO_BACKEND,
    RUTA_LOCK_OPERACION,
    RUTA_VHOST_LEGACY,
    RUTA_VHOST_LEGACY_DISPONIBLE,
    RUTA_VHOST_SISLEG,
    SERVICIO_BACKEND_LEGACY,
    SERVICIO_BRIDGE_LEGACY,
    SUFIJO_VHOST_DESHABILITADO,
    ErrorEstadoHost,
    InspectorEstadoHost,
    escribir_target_release,
    leer_target_release,
    leer_target_release_tolerante,
    lock_operacion_global,
    validar_release_objetivo,
)
from deploy.herramienta_despliegue import (  # noqa: E402 - raíz preparada arriba
    SERVICIO_BACKEND,
    SERVICIO_BRIDGE,
    EjecutorComandos,
    EjecutorSubprocess,
    ErrorDespliegue,
    GestorDespliegue,
    cambiar_enlace_atomico,
    resolver_enlace_release,
)

OPERACION_ACTUALIZAR = "actualizar"
OPERACION_CAMBIAR_A_SISLEG = "cambiar-a-sis-leg"
OPERACION_CAMBIAR_A_LEGACY = "cambiar-a-legacy"

# Desenlaces posibles de una operación. El historial del host los registra
# siempre: «no hice nada porque la persona canceló» y «fallé y revertí» son tan
# relevantes para el soporte como un éxito.
ESTADO_EXITO = "EXITO"
ESTADO_CANCELADA = "CANCELADA"
ESTADO_FALLA = "FALLA"

# Desenlace del rollback, cuando la operación llegó a mutar algo.
ROLLBACK_NO_APLICA = "NO_APLICA"
ROLLBACK_EXITOSO = "EXITOSO"
ROLLBACK_FALLIDO = "FALLIDO"


class ErrorOperacionHost(RuntimeError):
    """Falla de una operación de usuario, siempre con el host en estado conocido.

    Cuando esta excepción sale, o bien no se mutó nada, o bien el rollback ya
    restauró el sistema anterior. El caso en que ni siquiera el rollback pudo
    completarse se señala explícitamente en el mensaje y exige intervención
    humana: nunca se reintenta en silencio.
    """


@dataclass(frozen=True, slots=True)
class PlanOperacion:
    """Lo que la operación haría, calculado antes de mutar nada.

    Existe para que la persona que pulsa el botón vea, en la misma terminal y
    antes de cualquier cambio, de dónde sale y hacia dónde va la operación. Los
    wrappers del escritorio muestran este plan y piden confirmación.
    """

    operacion: str
    estado_inicial: str
    release_actual: str | None
    target_actual: str | None
    sha_objetivo: str | None
    acciones_previstas: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvidenciaPublica:
    """Trazabilidad del canal público de WP-100, sin ningún dato sensible.

    Todo lo que contiene es información ya publicada: el commit y el árbol de la
    release, su etiqueta, el nombre del paquete con su checksum SHA-256 y el run
    y el job de CI que la produjeron. No hay tokens, credenciales, URLs firmadas
    ni encabezados de autenticación, porque el consumidor no usa ninguno: la
    actualización se hace sin autenticarse.

    Existe para que el historial del host permita responder, meses después y sin
    acceso a la máquina, de dónde salió exactamente la versión instalada.
    """

    commit_sha: str
    tree_sha: str
    tag: str
    paquete: str
    paquete_sha256: str | None
    ci_run_id: int
    ci_run_numero: int
    ci_run_intento: int
    ci_workflow: str
    ci_job_id: int
    ci_job_nombre: str


@dataclass(slots=True)
class ResultadoOperacion:
    """Qué ocurrió realmente, apto para registrar en el historial del host.

    ``muto`` distingue el caso idempotente —no había nada que hacer— del caso en
    que el host efectivamente cambió. Los historiales del host registran ambos,
    porque «no hice nada y por qué» también es evidencia.

    Atributos que existen específicamente para el historial:
        estado: desenlace (``EXITO``, ``CANCELADA`` o ``FALLA``).
        exit_code: el mismo código que devuelve el proceso, para poder cruzar el
            historial con los registros del escritorio.
        timestamp: hora local de inicio de la operación, con precisión de
            segundos, igual que la auditoría institucional.
        rollback: desenlace de la reversión cuando la hubo.
        error: diagnóstico de la falla, si la hubo.
        diagnostico_target: por qué no se pudo leer ``target-release``, cuando la
            operación pudo continuar igual por ser version-agnóstica.
        evidencia_publica: :class:`EvidenciaPublica` serializada, cuando la
            operación consumió el canal público.
    """

    operacion: str
    estado_inicial: str
    estado_final: str
    sha_objetivo: str | None
    target_previo: str | None
    target_final: str | None
    muto: bool
    mensaje: str
    estado: str = ESTADO_EXITO
    exit_code: int = 0
    timestamp: str | None = None
    rollback: str = ROLLBACK_NO_APLICA
    error: str | None = None
    diagnostico_target: str | None = None
    evidencia_publica: dict[str, Any] | None = None
    acciones: list[str] = field(default_factory=lambda: [])
    configuracion_incorporada: list[str] = field(default_factory=lambda: [])


@dataclass(frozen=True, slots=True)
class SnapshotLegacy:
    """Lo mínimo para devolver el sistema anterior exactamente a donde estaba.

    ``destino_symlink`` guarda el destino literal del vhost publicado, no su
    ruta resuelta: restaurar el enlace con otro destino sería restaurar otra
    configuración.
    """

    destino_symlink: str | None
    backend_habilitado: bool
    bridge_habilitado: bool


@dataclass(frozen=True, slots=True)
class SnapshotSisLeg:
    """Lo mínimo para devolver SIS-Leg exactamente a donde estaba.

    Se captura **antes** de retirar SIS-Leg para volver al sistema anterior. Si
    esa vuelta falla a mitad de camino, este snapshot es lo único que permite
    reconstruir el sistema que estaba sano: qué release estaba en servicio y si
    sus unidades arrancaban solas.

    ``release`` es ``None`` cuando no había una release identificable; en ese
    caso no hay nada que restaurar y el rollback no puede intentarse.
    """

    release: str | None
    backend_habilitado: bool
    bridge_habilitado: bool


# ``Callable`` para pedir confirmación humana. Devuelve ``True`` para continuar.
Confirmador = Callable[[PlanOperacion], bool]


def marca_temporal_local() -> str:
    """Hora local con precisión de segundos, igual que la auditoría institucional.

    Se usa hora local y no UTC porque el historial lo lee la misma persona que
    operó el host, y tiene que poder cruzarlo con lo que recuerda de la sesión.
    El desplazamiento horario queda incluido en la cadena ISO, así que el dato
    sigue siendo interpretable sin ambigüedad desde cualquier otro lugar.
    """

    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


class OperadorHost:
    """Ejecuta las tres operaciones de usuario sobre el host en transición.

    Todas las dependencias privilegiadas se inyectan:

    - ``gestor``: motor canónico de releases (preparar/activar/rollback/config);
    - ``inspector``: clasificación del estado formal y guards;
    - ``ejecutor``: frontera única hacia ``systemctl`` y ``nginx``;
    - ``resolver_sha_publico`` y ``obtener_release``: canal público de WP-100;
    - ``preflight``: comprobación de prerequisitos del host;
    - ``durmiente``: espera entre reintentos, para pruebas deterministas.

    Ninguna de estas dependencias se construye a mano acá: los valores por
    defecto son exactamente las funciones canónicas ya revisadas, de modo que no
    existe una segunda implementación de validación de releases ni de despliegue.
    """

    def __init__(
        self,
        raiz: Path = Path("/opt/sis-leg"),
        *,
        gestor: GestorDespliegue | None = None,
        inspector: InspectorEstadoHost | None = None,
        ejecutor: EjecutorComandos | None = None,
        resolver_sha_publico: Callable[[], str] | None = None,
        obtener_release: Callable[[Path], ReleaseDescargada] | None = None,
        preflight: Callable[[], None] | None = None,
        durmiente: Callable[[float], None] | None = None,
        reloj: Callable[[], str] = marca_temporal_local,
        ruta_lock: Path = RUTA_LOCK_OPERACION,
        ruta_vhost_legacy: Path = RUTA_VHOST_LEGACY,
        ruta_vhost_legacy_disponible: Path = RUTA_VHOST_LEGACY_DISPONIBLE,
        ruta_vhost_sisleg: Path = RUTA_VHOST_SISLEG,
        directorio_descargas: Path | None = None,
        repositorio: str = REPOSITORIO_PREDETERMINADO,
    ) -> None:
        self.raiz = raiz.resolve()
        self.ejecutor = ejecutor or EjecutorSubprocess()
        self.gestor = gestor or GestorDespliegue(self.raiz, ejecutor=self.ejecutor)
        self.inspector = inspector or InspectorEstadoHost(
            self.raiz,
            ejecutor=self.ejecutor,
            ruta_vhost_legacy=ruta_vhost_legacy,
            ruta_vhost_sisleg=ruta_vhost_sisleg,
        )
        self.repositorio = repositorio
        self._resolver_sha_publico = resolver_sha_publico or self._resolver_sha_publico_real
        self._obtener_release = obtener_release or self._obtener_release_real
        # ``preflight`` sondea binarios del host con ``shutil.which``; en una
        # máquina de desarrollo no hay Nginx ni systemd, así que la suite inyecta
        # una comprobación que sólo registra haber sido llamada. El preflight
        # real ya tiene sus propias pruebas en el motor canónico.
        self.preflight = preflight or self.gestor.preflight
        self.durmiente = durmiente or time.sleep
        self.reloj = reloj
        self.ruta_lock = ruta_lock
        self.ruta_vhost_legacy = ruta_vhost_legacy
        self.ruta_vhost_legacy_disponible = ruta_vhost_legacy_disponible
        self.ruta_vhost_sisleg = ruta_vhost_sisleg
        self.directorio_descargas = directorio_descargas or (self.raiz / "descargas")
        # SHA autorizado para la descarga en curso. Se fija al comenzar
        # ``actualizar`` y lo consume la frontera real del canal público, de modo
        # que nunca se descargue un SHA distinto del que la operación resolvió.
        self._sha_en_curso: str | None = None
        # Último resultado construido, incluso si la operación después falló. Es
        # lo que permite que la CLI registre en el historial una falla o una
        # cancelación con el mismo detalle que un éxito: sin esta referencia, una
        # excepción se llevaría consigo todo lo que ya se sabía de la operación.
        self.ultimo_resultado: ResultadoOperacion | None = None

    # ------------------------------------------------------------------
    # Fronteras hacia el canal público
    # ------------------------------------------------------------------

    def _resolver_sha_publico_real(self) -> str:
        """Resuelve la cabeza de ``main`` sin ninguna credencial del host."""

        return resolver_sha_main(ClienteHttpPublicoReal(), repositorio=self.repositorio)

    def _obtener_release_real(self, destino: Path) -> ReleaseDescargada:
        """Descarga y valida la release pública del SHA que se está actualizando.

        No se pasa ``sha=None``: el SHA ya fue resuelto al principio de la
        operación y es el único autorizado. Si ``main`` avanzó mientras corría la
        actualización, el canal público fallará al no encontrar esa publicación,
        que es exactamente la conducta esperada.
        """

        return obtener_release_publica(
            destino,
            cliente=ClienteHttpPublicoReal(),
            sha=self._sha_en_curso,
            repositorio=self.repositorio,
        )

    # ------------------------------------------------------------------
    # Utilidades comunes
    # ------------------------------------------------------------------

    def _nuevo_resultado(
        self,
        operacion: str,
        estado: str,
        *,
        target_previo: str | None,
        diagnostico_target: str | None = None,
    ) -> ResultadoOperacion:
        """Crea el resultado de la operación y lo deja accesible para el historial.

        Se registra en ``ultimo_resultado`` en el mismo momento en que se crea,
        y no al terminar: si la operación falla a mitad de camino, la CLI todavía
        tiene que poder anexar al historial el estado inicial, lo que ya se hizo
        y por qué se cortó.
        """

        resultado = ResultadoOperacion(
            operacion=operacion,
            estado_inicial=estado,
            estado_final=estado,
            sha_objetivo=None,
            target_previo=target_previo,
            target_final=target_previo,
            muto=False,
            mensaje="",
            timestamp=self.reloj(),
            diagnostico_target=diagnostico_target,
        )
        self.ultimo_resultado = resultado
        return resultado

    def _systemctl(self, *argumentos: str, comprobar: bool = True) -> None:
        """Única puerta hacia systemd. Nunca se arma una línea de shell."""

        self.ejecutor.ejecutar(["systemctl", *argumentos], comprobar=comprobar)

    def _deshabilitar_verificando(
        self, unidades: Sequence[str], resultado: ResultadoOperacion, descripcion: str
    ) -> None:
        """Deshabilita las unidades de un sistema y **demuestra** que quedaron así.

        Entradas:
            unidades: unidades del sistema que sale de servicio.
            resultado: se anota la acción realizada.
            descripcion: cómo nombrar al sistema saliente en los mensajes.

        Errores:
            ErrorOperacionHost si alguna unidad sigue habilitada después del
            ``disable``.

        Éste es el corazón verificable de *disable-first*. Se deshabilita antes
        de detener para que un reinicio en el peor momento no reviva el sistema
        saliente, pero un ``disable`` que falla en silencio dejaría exactamente
        el riesgo que la regla pretende eliminar. Por eso se comprueba el efecto
        y se aborta **antes** de detener nada: en ese punto el host todavía está
        entero y no hace falta ningún rollback.

        Si la comprobación falla se vuelven a habilitar las unidades que sí
        habían quedado deshabilitadas. Un aborto por precondición no debería
        dejar el host peor de como estaba: lo que se pretendía era una
        conmutación completa, no deshabilitar media unidad y abandonar.
        """

        habilitadas_previamente = [
            unidad for unidad in unidades if self.inspector.esta_habilitada(unidad)
        ]
        for unidad in unidades:
            self._systemctl("disable", unidad, comprobar=False)
        try:
            self.inspector.exigir_unidades_deshabilitadas(unidades)
        except ErrorEstadoHost as error:
            for unidad in habilitadas_previamente:
                self._systemctl("enable", unidad, comprobar=False)
            raise ErrorOperacionHost(
                f"No se pudo demostrar el disable-first de {descripcion}: {error} "
                "Se restauró la habilitación previa de las unidades y no se detuvo ningún "
                "servicio."
            ) from error
        resultado.acciones.append(f"disable-first verificado de {descripcion}")

    def _esperar(
        self,
        descripcion: str,
        comprobacion: Callable[[], bool],
        *,
        intentos: int = 20,
        pausa: float = 0.5,
    ) -> None:
        """Espera acotadamente una condición observable y falla cerrado si no llega.

        Se prefiere esperar una condición real —un puerto liberado, un servicio
        inactivo— antes que dormir un tiempo fijo: un ``sleep`` ciego convierte
        un host lento en una falla intermitente y un host rápido en tiempo
        perdido.
        """

        for numero in range(intentos):
            if comprobacion():
                return
            if numero + 1 < intentos:
                self.durmiente(pausa)
        raise ErrorOperacionHost(f"No se alcanzó la condición esperada: {descripcion}.")

    def _unidad_inactiva(self, unidad: str) -> bool:
        """``True`` cuando systemd ya no reporta la unidad como activa."""

        resultado = self.ejecutor.ejecutar(["systemctl", "is-active", unidad], comprobar=False)
        return resultado.salida.strip() != "active"

    def _release_actual(self) -> str | None:
        """SHA al que apunta ``current``, o ``None`` si SIS-Leg no está activo."""

        try:
            actual = resolver_enlace_release(self.gestor.current, self.gestor.releases)
        except ErrorDespliegue:
            return None
        return actual.name if actual is not None else None

    def _guard_institucional(self, estado: str) -> None:
        """Aplica el guard de «ni sesión ni preparación» del sistema que manda.

        Cada sistema responde su propio estado: Legacy por ``hay_sesion`` y
        SIS-Leg por el estado global de Moderación. Se delega en el guard
        canónico de la herramienta de despliegue para el lado SIS-Leg en lugar de
        reimplementarlo.
        """

        if estado == ESTABLE_LEGACY:
            self.inspector.guard_institucional_legacy()
            return
        self.gestor.guard_institucional()

    def _exigir_estado_operativo(self, estado: str, operacion: str) -> None:
        """Rechaza partir de un estado inerte o inconsistente.

        No hay recuperación automática: reparar un host inconsistente es una
        decisión humana con evidencia a la vista, no un reintento silencioso.
        """

        if estado not in ESTADOS_OPERATIVOS:
            raise ErrorOperacionHost(
                f"La operación {operacion} no puede partir del estado formal {estado}. "
                "Se requiere diagnóstico humano; no se modificó nada."
            )

    # ------------------------------------------------------------------
    # Manejo de vhosts
    # ------------------------------------------------------------------

    def _retirar_vhost_legacy(self) -> str | None:
        """Quita el vhost del sistema anterior conservando su destino literal."""

        if not self.ruta_vhost_legacy.exists() and not self.ruta_vhost_legacy.is_symlink():
            return None
        destino = (
            os.readlink(self.ruta_vhost_legacy)
            if self.ruta_vhost_legacy.is_symlink()
            else str(self.ruta_vhost_legacy_disponible)
        )
        self.ruta_vhost_legacy.unlink()
        return destino

    def _restaurar_vhost_legacy(self, destino: str | None) -> None:
        """Vuelve a publicar exactamente el vhost anterior, si lo había."""

        if destino is None:
            return
        if self.ruta_vhost_legacy.exists() or self.ruta_vhost_legacy.is_symlink():
            return
        self.ruta_vhost_legacy.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(destino, self.ruta_vhost_legacy)

    def _deshabilitar_vhost_sisleg(self) -> None:
        """Saca el vhost de SIS-Leg del glob ``*.conf`` sin borrarlo.

        Renombrarlo a ``.conf.disabled`` conserva el archivo para diagnóstico y
        deja de incluirlo en Nginx. Nunca se crea ``sites-enabled/sis-leg.conf``:
        mezclar los dos mecanismos de configuración haría ambiguo cuál vhost gana.
        """

        if not self.ruta_vhost_sisleg.is_file():
            return
        destino = self.ruta_vhost_sisleg.with_name(
            self.ruta_vhost_sisleg.name + SUFIJO_VHOST_DESHABILITADO
        )
        os.replace(self.ruta_vhost_sisleg, destino)

    def _rehabilitar_vhost_sisleg(self) -> None:
        """Deshace :meth:`_deshabilitar_vhost_sisleg` durante un rollback.

        Se usa sólo al restaurar SIS-Leg después de una vuelta fallida al sistema
        anterior. Si la activación posterior vuelve a escribir el vhost desde la
        release, este paso resulta redundante pero inofensivo; si por cualquier
        motivo no lo hiciera, deja el archivo exactamente como estaba.
        """

        deshabilitado = self.ruta_vhost_sisleg.with_name(
            self.ruta_vhost_sisleg.name + SUFIJO_VHOST_DESHABILITADO
        )
        if not deshabilitado.is_file():
            return
        if self.ruta_vhost_sisleg.exists():
            deshabilitado.unlink()
            return
        os.replace(deshabilitado, self.ruta_vhost_sisleg)

    # ------------------------------------------------------------------
    # Retiradas ordenadas
    # ------------------------------------------------------------------

    def _retirar_legacy(self, resultado: ResultadoOperacion) -> SnapshotLegacy:
        """Retira el sistema anterior en el único orden seguro conocido.

        1. ``disable`` de las dos unidades **antes** de detenerlas, comprobando
           que realmente quedaron deshabilitadas, para que un reinicio no las
           devuelva a la vida;
        2. detener el bridge y comprobar que quedó inactivo;
        3. detener el backend y comprobar que liberó ``:8000``;
        4. retirar el vhost publicado.

        El bridge se detiene primero porque es el que tiene tomado el hardware:
        dejarlo vivo mientras arranca otro backend es justamente la mezcla que
        la invariante de exclusión prohíbe.
        """

        backend_habilitado = self.inspector.esta_habilitada(SERVICIO_BACKEND_LEGACY)
        bridge_habilitado = self.inspector.esta_habilitada(SERVICIO_BRIDGE_LEGACY)
        self._deshabilitar_verificando(
            (SERVICIO_BRIDGE_LEGACY, SERVICIO_BACKEND_LEGACY),
            resultado,
            "las unidades del sistema anterior",
        )

        self._systemctl("stop", SERVICIO_BRIDGE_LEGACY)
        self._esperar(
            f"{SERVICIO_BRIDGE_LEGACY} debía quedar inactivo",
            lambda: self._unidad_inactiva(SERVICIO_BRIDGE_LEGACY),
        )
        self.inspector.exigir_maximo_un_bridge()
        resultado.acciones.append("bridge del sistema anterior detenido")

        self._systemctl("stop", SERVICIO_BACKEND_LEGACY)
        self._esperar(
            f"{SERVICIO_BACKEND_LEGACY} debía quedar inactivo",
            lambda: self._unidad_inactiva(SERVICIO_BACKEND_LEGACY),
        )
        self._esperar(
            f"el puerto {PUERTO_BACKEND} debía quedar libre",
            lambda: not self.inspector.sonda_puerto(PUERTO_BACKEND),
        )
        resultado.acciones.append("backend del sistema anterior detenido y puerto liberado")

        destino = self._retirar_vhost_legacy()
        resultado.acciones.append("vhost del sistema anterior retirado")
        return SnapshotLegacy(
            destino_symlink=destino,
            backend_habilitado=backend_habilitado,
            bridge_habilitado=bridge_habilitado,
        )

    def _retirar_sisleg(self, resultado: ResultadoOperacion) -> None:
        """Retira SIS-Leg con el mismo criterio *disable-first*.

        ``current`` se deja sin apuntar a nada a propósito: si quedara apuntando
        al mismo SHA con las unidades y el vhost ya retirados, la próxima llamada
        a ``activar`` retornaría temprano creyendo que no hay nada que hacer, y
        una reactivación futura fallaría en silencio.
        """

        self._deshabilitar_verificando(
            (SERVICIO_BRIDGE, SERVICIO_BACKEND), resultado, "las unidades de SIS-Leg"
        )

        self._systemctl("stop", SERVICIO_BRIDGE, comprobar=False)
        self._esperar(
            f"{SERVICIO_BRIDGE} debía quedar inactivo",
            lambda: self._unidad_inactiva(SERVICIO_BRIDGE),
        )
        self.inspector.exigir_maximo_un_bridge()
        self._systemctl("stop", SERVICIO_BACKEND, comprobar=False)
        self._esperar(
            f"{SERVICIO_BACKEND} debía quedar inactivo",
            lambda: self._unidad_inactiva(SERVICIO_BACKEND),
        )
        resultado.acciones.append("servicios de SIS-Leg detenidos")

        self._deshabilitar_vhost_sisleg()
        cambiar_enlace_atomico(self.gestor.current, None)
        resultado.acciones.append("vhost de SIS-Leg deshabilitado y current liberado")

    def _levantar_legacy(self, snapshot: SnapshotLegacy, resultado: ResultadoOperacion) -> None:
        """Devuelve el sistema anterior a servicio, backend antes que bridge."""

        self._restaurar_vhost_legacy(snapshot.destino_symlink)
        if snapshot.backend_habilitado:
            self._systemctl("enable", SERVICIO_BACKEND_LEGACY, comprobar=False)
        if snapshot.bridge_habilitado:
            self._systemctl("enable", SERVICIO_BRIDGE_LEGACY, comprobar=False)
        self._systemctl("start", SERVICIO_BACKEND_LEGACY)
        self._esperar(
            f"el backend anterior debía volver a ocupar el puerto {PUERTO_BACKEND}",
            lambda: self.inspector.sonda_puerto(PUERTO_BACKEND),
        )
        self.inspector.exigir_maximo_un_bridge()
        self._systemctl("start", SERVICIO_BRIDGE_LEGACY)
        self.inspector.exigir_maximo_un_bridge()
        self.ejecutor.ejecutar(["nginx", "-t"])
        self._systemctl("reload", "nginx.service")
        resultado.acciones.append("sistema anterior restaurado y Nginx recargado")

    # ------------------------------------------------------------------
    # Operación 1: actualizar
    # ------------------------------------------------------------------

    def actualizar(self, *, confirmador: Confirmador | None = None) -> ResultadoOperacion:
        """Trae la release pública de ``main`` y la deja utilizable, sin conmutar.

        Resultado: :class:`ResultadoOperacion` con el detalle de lo ocurrido.

        Efectos laterales: descarga a un temporal, prepara la release nueva,
        incorpora recursos de configuración ausentes de forma add-only y, según
        el sistema activo, fija ``target-release`` o actualiza SIS-Leg en caliente.

        Errores:
            ErrorOperacionHost ante cualquier precondición no demostrable, con el
            host en el estado en que estaba o ya restaurado.

        El orden es el del contrato de WP-101: lock, guard institucional,
        resolución del SHA público, idempotencia, descarga verificada, preflight,
        preparación, compuerta de configuración y recién entonces la acción que
        corresponda al sistema activo.

        Actualizar y conmutar son decisiones distintas: que exista una versión
        nueva no es motivo para cambiar el sistema que está atendiendo el recinto.
        """

        with lock_operacion_global(self.ruta_lock):
            estado = self.inspector.clasificar()
            resultado = self._nuevo_resultado(OPERACION_ACTUALIZAR, estado, target_previo=None)
            self._exigir_estado_operativo(estado, OPERACION_ACTUALIZAR)
            self._guard_institucional(estado)
            resultado.acciones.append(f"guard institucional superado en estado {estado}")

            try:
                sha_objetivo = self._resolver_sha_publico()
            except (ErrorActualizadorPublico, ErrorDespliegue, OSError) as error:
                raise ErrorOperacionHost(
                    f"No se pudo resolver la versión pública de main: {error}"
                ) from error
            self._sha_en_curso = sha_objetivo
            resultado.sha_objetivo = sha_objetivo

            target_previo = leer_target_release(self.raiz)
            release_actual = self._release_actual()
            resultado.target_previo = target_previo
            resultado.target_final = target_previo

            self._exigir_estado_resoluble(estado, release_actual, target_previo)

            # Idempotencia. La divergencia entre ``current`` y ``target-release`` ya
            # fue rechazada arriba, así que llegar acá con el target igual al SHA
            # público significa que no hay absolutamente nada que hacer.
            if target_previo == sha_objetivo and self._release_preparada(sha_objetivo):
                resultado.mensaje = (
                    "SIS-Leg ya está actualizado; no se descargó, preparó ni reinició nada."
                )
                resultado.estado_final = estado
                return resultado

            plan = PlanOperacion(
                operacion=OPERACION_ACTUALIZAR,
                estado_inicial=estado,
                release_actual=release_actual,
                target_actual=target_previo,
                sha_objetivo=sha_objetivo,
                acciones_previstas=self._acciones_previstas_actualizar(estado),
            )
            if confirmador is not None and not confirmador(plan):
                resultado.estado = ESTADO_CANCELADA
                resultado.mensaje = "Actualización cancelada por la persona operadora."
                return resultado

            release_descargada = self._descargar_release(sha_objetivo, resultado)
            self.preflight()
            resultado.acciones.append("preflight de prerequisitos ejecutado")
            try:
                release = self.gestor.preparar(
                    release_descargada.paquete,
                    release_descargada.sidecar,
                    sha_objetivo,
                )
            except (ErrorDespliegue, OSError) as error:
                raise ErrorOperacionHost(
                    f"No se pudo preparar la release {sha_objetivo}: {error}"
                ) from error
            resultado.acciones.append(f"release {sha_objetivo} preparada")
            resultado.muto = True
            self._descartar_descarga(release_descargada, resultado)

            # Última compuerta antes de cualquier mutación que decida qué versión
            # usa el host. Desde acá hasta el final ya no se consulta la red.
            self._revalidar_sha_publico(sha_objetivo, resultado)

            self._aplicar_contrato_configuracion(release, resultado)

            if estado == ESTABLE_LEGACY:
                escribir_target_release(self.raiz, sha_objetivo)
                resultado.target_final = sha_objetivo
                resultado.acciones.append("target-release actualizado atómicamente")
                resultado.mensaje = (
                    "SIS-Leg actualizado y preparado. Se activará al pulsar «Cambiar a SIS-Leg»; "
                    "el sistema anterior sigue operativo."
                )
            else:
                self._actualizar_sisleg_en_caliente(sha_objetivo, target_previo, resultado)

            resultado.estado_final = self.inspector.clasificar()
            if resultado.estado_final != estado:
                raise ErrorOperacionHost(
                    f"La actualización terminó en estado {resultado.estado_final} y no en "
                    f"{estado}. Se requiere diagnóstico humano."
                )
            return resultado

    def _revalidar_sha_publico(self, sha_congelado: str, resultado: ResultadoOperacion) -> None:
        """Vuelve a resolver ``main`` y aborta si avanzó durante la operación.

        Entradas:
            sha_congelado: el SHA que la operación resolvió al empezar y que
                autorizó toda la descarga y la preparación.
            resultado: se anota la revalidación superada.

        Errores:
            ErrorOperacionHost si ``main`` avanzó o si no se puede volver a
            resolver.

        ¿Por qué hace falta? Las releases públicas son inmutables: la del SHA
        anterior sigue existiendo y descargándose con normalidad aunque ``main``
        haya avanzado. Sin esta revalidación, una actualización lenta podría
        terminar instalando y declarando como objetivo una versión que ya dejó de
        ser la vigente, con una autorización tomada minutos antes.

        Qué queda cuando se detecta la carrera: la release nueva ya preparada se
        conserva en ``releases/`` porque preparar es aditivo y no toca lo que
        está en servicio; sirve de diagnóstico y de caché para el próximo
        intento. Lo que **no** ocurre es activarla ni declararla como objetivo:
        el host sigue exactamente en la versión en la que estaba.
        """

        try:
            sha_vigente = self._resolver_sha_publico()
        except (ErrorActualizadorPublico, ErrorDespliegue, OSError) as error:
            raise ErrorOperacionHost(
                "No se pudo revalidar la versión pública de main antes de aplicar el cambio; "
                f"no se activó ni se fijó ninguna release: {error}"
            ) from error
        if sha_vigente != sha_congelado:
            raise ErrorOperacionHost(
                f"main avanzó de {sha_congelado} a {sha_vigente} mientras corría la "
                "actualización. La release preparada queda disponible para el próximo intento, "
                "pero no se activó ni se declaró como objetivo con una autorización vencida."
            )
        resultado.acciones.append(f"main revalidado: sigue en {sha_congelado}")

    def _exigir_estado_resoluble(
        self, estado: str, release_actual: str | None, target_previo: str | None
    ) -> None:
        """Aborta fail-safe cuando ``current`` y ``target-release`` divergen.

        Con SIS-Leg activo, que la release en uso no sea la declarada como
        objetivo significa que alguien intervino a mano o que una operación
        anterior quedó a medias. Suponer cuál de las dos manda sería exactamente
        el atajo que este guard existe para impedir.
        """

        if estado != ESTABLE_SISLEG or target_previo is None:
            return
        if release_actual != target_previo:
            raise ErrorOperacionHost(
                f"SIS-Leg está activo con current={release_actual} pero target-release declara "
                f"{target_previo}. El estado es ambiguo: se aborta sin mutar."
            )

    def _release_preparada(self, sha: str) -> bool:
        """``True`` si esa release ya existe, validada, en ``releases/``."""

        try:
            validar_release_objetivo(self.raiz, sha)
        except ErrorEstadoHost:
            return False
        return True

    def _acciones_previstas_actualizar(self, estado: str) -> tuple[str, ...]:
        """Describe en castellano llano qué haría la actualización."""

        comunes = (
            "descargar y verificar la release pública sin credenciales",
            "preparar la release nueva sin tocar la activa",
            "incorporar sólo los recursos de configuración que falten",
        )
        if estado == ESTABLE_LEGACY:
            return (*comunes, "fijar target-release", "dejar el sistema anterior operativo")
        return (
            *comunes,
            "activar la release nueva con health completo",
            "revertir automáticamente a la release anterior si algo falla",
        )

    def _descargar_release(self, sha: str, resultado: ResultadoOperacion) -> ReleaseDescargada:
        """Delega en el canal público y traduce sus fallas a esta operación.

        No se vuelve a validar nada acá: el canal público ya demostró la
        publicación, el intento histórico de CI, el job de empaquetado, los tres
        assets, el checksum del sidecar y el manifest contra el motor canónico.
        Repetir esas comprobaciones sería crear una segunda implementación.
        """

        self.directorio_descargas.mkdir(parents=True, exist_ok=True)
        try:
            release = self._obtener_release(self.directorio_descargas)
        except (ErrorActualizadorPublico, ErrorDespliegue, OSError) as error:
            raise ErrorOperacionHost(
                f"No se pudo obtener la release pública {sha}: {error}"
            ) from error
        if release.commit_sha != sha:
            raise ErrorOperacionHost(
                f"El canal público devolvió {release.commit_sha} en lugar de {sha}."
            )
        resultado.evidencia_publica = asdict(self._evidencia_publica(release))
        resultado.acciones.append(f"release pública {sha} descargada y verificada sin credenciales")
        return release

    def _evidencia_publica(self, release: ReleaseDescargada) -> EvidenciaPublica:
        """Extrae del canal público lo que el historial debe conservar.

        Se toma el checksum del sidecar y no se recalcula: es el mismo valor que
        el motor canónico ya verificó contra el paquete, y leerlo acá no repite
        ninguna validación. Si el sidecar no se pudiera leer, el campo queda en
        ``None`` en lugar de romper la operación: la evidencia es importante,
        pero no es la razón por la que se está actualizando el host.
        """

        return EvidenciaPublica(
            commit_sha=release.commit_sha,
            tree_sha=release.tree_sha,
            tag=release.tag,
            paquete=release.paquete.name,
            paquete_sha256=self._checksum_declarado(release.sidecar),
            ci_run_id=release.run_ci.identificador,
            ci_run_numero=release.run_ci.numero,
            ci_run_intento=release.run_ci.intento,
            ci_workflow=release.run_ci.workflow,
            ci_job_id=release.job_ci.identificador,
            ci_job_nombre=release.job_ci.nombre,
        )

    @staticmethod
    def _checksum_declarado(sidecar: Path) -> str | None:
        """Primer campo del sidecar SHA-256, o ``None`` si no se puede leer."""

        try:
            primera_palabra = sidecar.read_text(encoding="ascii").split()
        except (OSError, UnicodeDecodeError):
            return None
        return primera_palabra[0] if primera_palabra else None

    def _descartar_descarga(
        self, release: ReleaseDescargada, resultado: ResultadoOperacion
    ) -> None:
        """Borra el paquete descargado una vez que la release quedó preparada.

        El tar pesa cientos de megabytes y, preparada la release, es redundante:
        lo que el host necesita es el directorio bajo ``releases/``, y el canal
        público puede volver a traer cualquier SHA cuando haga falta. Acumular
        una descarga por actualización llenaría el disco de la máquina
        institucional sin aportar nada.

        Sólo se borra lo que esta misma operación descargó. Si ``preparar``
        hubiera fallado, este método no se ejecuta y los artefactos quedan para
        diagnóstico. Nunca se tocan releases, registros ni respaldos.
        """

        for artefacto in (release.paquete, release.sidecar, release.metadatos):
            try:
                artefacto.unlink(missing_ok=True)
            except OSError as error:  # noqa: PERF203 - se informa y se sigue
                resultado.acciones.append(f"no se pudo borrar la descarga {artefacto}: {error}")
        resultado.acciones.append("descarga temporal descartada tras preparar la release")

    def _aplicar_contrato_configuracion(self, release: Path, resultado: ResultadoOperacion) -> None:
        """Compuerta de configuración: migración prohibida, altas sólo si faltan.

        Se ejecuta después de ``preparar`` —que sólo agrega un directorio nuevo
        bajo ``releases/`` y no toca la instalación activa— y **antes** de
        cualquier escritura sobre ``config/``, ``target-release`` o los servicios.
        Ese es el sentido de «abortar antes de mutar»: si la release nueva exige
        migrar un archivo institucional existente, la operación se detiene con la
        configuración intacta y el sistema activo sin alterar.
        """

        try:
            plan = self.gestor.planificar_configuracion_local(release)
            exigir_plan_sin_migraciones(plan)
        except (ErrorConfiguracionLocal, ErrorDespliegue, OSError) as error:
            raise ErrorOperacionHost(
                "La release nueva exige una migración de configuración local que requiere "
                f"aprobación humana (HUMAN_GATE). No se modificó ninguna configuración: {error}"
            ) from error
        previstos = [
            entrada.recurso.ruta_local for entrada in plan if entrada.accion == ACCION_CREAR
        ]
        try:
            creados = self.gestor.incorporar_configuracion_local(release)
        except (ErrorConfiguracionLocal, ErrorDespliegue, OSError) as error:
            raise ErrorOperacionHost(
                f"No se pudieron incorporar los recursos de configuración nuevos: {error}"
            ) from error
        resultado.configuracion_incorporada = list(creados)
        resultado.acciones.append(
            "configuración local preservada; recursos nuevos previstos: "
            f"{previstos or 'ninguno'}; incorporados: {list(creados) or 'ninguno'}"
        )

    def _actualizar_sisleg_en_caliente(
        self, sha_objetivo: str, target_previo: str | None, resultado: ResultadoOperacion
    ) -> None:
        """Actualiza SIS-Leg -> SIS-Leg sin pasar por el sistema anterior.

        La activación es version-agnóstica: no hay ningún SHA escrito en el
        código, sólo el que resolvió el canal público. El motor canónico ya
        implementa el switch atómico de ``current``, el health, la convergencia
        de Nginx y el rollback a la release anterior; acá sólo se encadena y se
        restaura ``target-release`` si algo falló.

        ``target-release`` se escribe **después** del éxito, nunca antes: si se
        escribiera primero, una activación fallida dejaría el host declarando
        como objetivo una release que no está en servicio.
        """

        try:
            self.gestor.activar(sha_objetivo)
        except (ErrorDespliegue, ErrorConfiguracionLocal, OSError) as error:
            actual = leer_target_release(self.raiz)
            if actual != target_previo and target_previo is not None:
                escribir_target_release(self.raiz, target_previo)
                resultado.acciones.append("target-release anterior restaurado")
            resultado.target_final = target_previo
            resultado.rollback = self._desenlace_rollback_en_caliente(target_previo)
            resultado.estado_final = self.inspector.clasificar()
            raise ErrorOperacionHost(
                "Falló la actualización en caliente de SIS-Leg; el motor canónico restauró la "
                f"release anterior y se conservó el target previo: {error}"
            ) from error
        escribir_target_release(self.raiz, sha_objetivo)
        resultado.target_final = sha_objetivo
        resultado.acciones.append(
            "release nueva activada con health completo y target-release actualizado"
        )
        resultado.mensaje = f"SIS-Leg actualizado y en servicio en la release {sha_objetivo}."

    def _desenlace_rollback_en_caliente(self, target_previo: str | None) -> str:
        """Observa si el motor canónico realmente devolvió la release anterior.

        No se confía en que el rollback haya funcionado sólo porque se ejecutó:
        se mira el host. Queda ``EXITOSO`` si SIS-Leg volvió a quedar estable en
        la release previa, y ``FALLIDO`` en cualquier otro caso, incluido el de
        no poder observarlo. El historial guarda ese dato porque es lo primero
        que necesita saber quien atiende el host después de una falla.
        """

        try:
            estable = self.inspector.clasificar() == ESTABLE_SISLEG
            volvio = self._release_actual() == target_previo
        except (ErrorEstadoHost, ErrorDespliegue, OSError):
            return ROLLBACK_FALLIDO
        return ROLLBACK_EXITOSO if estable and volvio else ROLLBACK_FALLIDO

    # ------------------------------------------------------------------
    # Operación 2: cambiar a SIS-Leg
    # ------------------------------------------------------------------

    def cambiar_a_sis_leg(self, *, confirmador: Confirmador | None = None) -> ResultadoOperacion:
        """Conmuta del sistema anterior a SIS-Leg leyendo ``target-release``.

        Nunca contiene un SHA: la release a activar sale de ``target-release`` y
        se valida con las ocho comprobaciones antes de tocar nada. Si ya está
        activo SIS-Leg, la operación es idempotente y no muta.

        Ante cualquier falla posterior al inicio de la retirada del sistema
        anterior se ejecuta el rollback externo completo, que lo devuelve a
        servicio y no borra releases, configuración ni registros.
        """

        with lock_operacion_global(self.ruta_lock):
            estado = self.inspector.clasificar()
            # Lectura estricta a propósito: esta operación **consume** el
            # objetivo, así que un archivo corrupto tiene que detenerla.
            resultado = self._nuevo_resultado(
                OPERACION_CAMBIAR_A_SISLEG, estado, target_previo=leer_target_release(self.raiz)
            )
            if estado == ESTABLE_SISLEG:
                resultado.sha_objetivo = self._release_actual()
                resultado.mensaje = "SIS-Leg ya estaba activo; no se modificó nada."
                return resultado
            self._exigir_estado_operativo(estado, OPERACION_CAMBIAR_A_SISLEG)

            objetivo = leer_target_release(self.raiz)
            if objetivo is None:
                raise ErrorOperacionHost(
                    "No hay target-release declarado: primero hay que ejecutar «Actualizar "
                    "SIS-Leg». No se modificó nada."
                )
            validar_release_objetivo(self.raiz, objetivo)
            resultado.sha_objetivo = objetivo
            resultado.acciones.append(f"target-release {objetivo} validado")

            self._guard_institucional(estado)
            resultado.acciones.append("guard institucional del sistema anterior superado")

            plan = PlanOperacion(
                operacion=OPERACION_CAMBIAR_A_SISLEG,
                estado_inicial=estado,
                release_actual=None,
                target_actual=objetivo,
                sha_objetivo=objetivo,
                acciones_previstas=(
                    "retirar el sistema anterior en orden seguro",
                    "activar la release declarada con health completo",
                    "restaurar el sistema anterior automáticamente si algo falla",
                ),
            )
            if confirmador is not None and not confirmador(plan):
                resultado.estado = ESTADO_CANCELADA
                resultado.mensaje = "Conmutación cancelada por la persona operadora."
                return resultado

            snapshot = self._retirar_legacy(resultado)
            resultado.muto = True
            try:
                self.gestor.activar(objetivo)
                self.inspector.exigir_maximo_un_bridge()
                self._systemctl("enable", SERVICIO_BACKEND, comprobar=False)
                self._systemctl("enable", SERVICIO_BRIDGE, comprobar=False)
                resultado.acciones.append("unidades de SIS-Leg habilitadas tras el health exitoso")
                estado_final = self.inspector.clasificar()
                if estado_final != ESTABLE_SISLEG:
                    raise ErrorOperacionHost(
                        f"La conmutación terminó en {estado_final} y no en {ESTABLE_SISLEG}."
                    )
            except Exception as error_original:  # noqa: BLE001 - se contiene y se restaura
                self._rollback_a_legacy(snapshot, resultado, error_original)
            resultado.estado_final = ESTABLE_SISLEG
            resultado.mensaje = f"SIS-Leg activo en la release {objetivo}."
            return resultado

    def _rollback_a_legacy(
        self, snapshot: SnapshotLegacy, resultado: ResultadoOperacion, error_original: Exception
    ) -> None:
        """Rollback externo: devuelve el sistema anterior a servicio y falla.

        Tiene que tolerar que el motor canónico haya fallado en cualquier punto,
        incluso a mitad de su propio rollback. Por eso retira SIS-Leg de forma
        defensiva antes de restaurar, y nunca borra releases, configuración ni
        registros: un rollback destructivo sería peor que la falla que intenta
        contener.
        """

        try:
            self._retirar_sisleg(resultado)
            self._levantar_legacy(snapshot, resultado)
            estado = self.inspector.clasificar()
            if estado != ESTABLE_LEGACY:
                raise ErrorOperacionHost(
                    f"El rollback dejó el host en {estado} y no en {ESTABLE_LEGACY}."
                )
        except Exception as error_rollback:  # noqa: BLE001 - se reportan ambos errores
            resultado.rollback = ROLLBACK_FALLIDO
            raise ErrorOperacionHost(
                f"Falló la conmutación ({error_original}) y también el rollback al sistema "
                f"anterior ({error_rollback}). Se requiere intervención humana."
            ) from error_rollback
        resultado.rollback = ROLLBACK_EXITOSO
        resultado.estado_final = ESTABLE_LEGACY
        raise ErrorOperacionHost(
            f"Falló la conmutación a SIS-Leg y se restauró el sistema anterior: {error_original}"
        ) from error_original

    # ------------------------------------------------------------------
    # Operación 3: cambiar a Legacy
    # ------------------------------------------------------------------

    def cambiar_a_legacy(self, *, confirmador: Confirmador | None = None) -> ResultadoOperacion:
        """Devuelve el recinto al sistema anterior, sin depender de la versión.

        Es idempotente: si el sistema anterior ya está activo no se muta nada. No
        existe recuperación automática desde estados ambiguos, y no se borra
        ninguna release ni configuración de SIS-Leg: el sistema nuevo queda listo
        para volver a activarse.

        Es además la operación de **salida segura** del host, y eso gobierna dos
        decisiones de diseño:

        - no depende de ``target-release``. Volver al sistema anterior es
          version-agnóstico, así que un objetivo corrupto se diagnostica y se
          informa, pero no puede bloquear la vuelta atrás;
        - si el sistema anterior no logra volver a servicio después de haber
          retirado SIS-Leg, se intenta restaurar el SIS-Leg que estaba sano en
          lugar de dejar el host inerte.
        """

        with lock_operacion_global(self.ruta_lock):
            estado = self.inspector.clasificar()
            # Lectura tolerante a propósito: esta operación **no consume** el
            # objetivo, sólo lo informa. Ver la explicación en el docstring.
            objetivo, diagnostico_objetivo = leer_target_release_tolerante(self.raiz)
            resultado = self._nuevo_resultado(
                OPERACION_CAMBIAR_A_LEGACY,
                estado,
                target_previo=objetivo,
                diagnostico_target=diagnostico_objetivo,
            )
            if diagnostico_objetivo is not None:
                resultado.acciones.append(
                    "target-release ilegible; se continúa porque volver al sistema anterior "
                    f"no depende de él: {diagnostico_objetivo}"
                )
            if estado == ESTABLE_LEGACY:
                resultado.mensaje = "El sistema anterior ya estaba activo; no se modificó nada."
                return resultado
            self._exigir_estado_operativo(estado, OPERACION_CAMBIAR_A_LEGACY)

            resultado.sha_objetivo = self._release_actual()
            self._guard_institucional(estado)
            resultado.acciones.append("guard institucional de SIS-Leg superado")

            plan = PlanOperacion(
                operacion=OPERACION_CAMBIAR_A_LEGACY,
                estado_inicial=estado,
                release_actual=resultado.sha_objetivo,
                target_actual=resultado.target_previo,
                sha_objetivo=None,
                acciones_previstas=(
                    "retirar SIS-Leg en orden seguro, bridge primero",
                    "restaurar el vhost y los servicios del sistema anterior",
                    "conservar releases, configuración y registros",
                ),
            )
            if confirmador is not None and not confirmador(plan):
                resultado.estado = ESTADO_CANCELADA
                resultado.mensaje = "Conmutación cancelada por la persona operadora."
                return resultado

            snapshot = SnapshotLegacy(
                destino_symlink=str(self.ruta_vhost_legacy_disponible),
                backend_habilitado=True,
                bridge_habilitado=True,
            )
            # Se captura la identidad restaurable de SIS-Leg **antes** de tocarlo:
            # después de retirarlo ya no hay de dónde leer qué release estaba en
            # servicio ni si sus unidades arrancaban solas.
            snapshot_sisleg = SnapshotSisLeg(
                release=resultado.sha_objetivo,
                backend_habilitado=self.inspector.esta_habilitada(SERVICIO_BACKEND),
                bridge_habilitado=self.inspector.esta_habilitada(SERVICIO_BRIDGE),
            )
            # La retirada de SIS-Leg queda fuera del bloque protegido a
            # propósito: su propio disable-first aborta antes de detener nada, y
            # si fallara más adelante el host quedaría a medio retirar, que es un
            # estado que exige diagnóstico humano y no una restauración a ciegas.
            # Lo que sí se protege es la vuelta del sistema anterior, porque ahí
            # SIS-Leg ya salió de servicio y hay algo concreto que restaurar.
            self._retirar_sisleg(resultado)
            resultado.muto = True
            try:
                self._levantar_legacy(snapshot, resultado)
                estado_final = self.inspector.clasificar()
                if estado_final != ESTABLE_LEGACY:
                    raise ErrorOperacionHost(
                        f"La conmutación terminó en {estado_final} y no en {ESTABLE_LEGACY}."
                    )
            except Exception as error_original:  # noqa: BLE001 - se contiene y se restaura
                self._rollback_a_sisleg(snapshot_sisleg, resultado, error_original)
            resultado.estado_final = ESTABLE_LEGACY
            resultado.mensaje = "Sistema anterior activo; SIS-Leg queda preparado para volver."
            return resultado

    def _rollback_a_sisleg(
        self,
        snapshot: SnapshotSisLeg,
        resultado: ResultadoOperacion,
        error_original: Exception,
    ) -> None:
        """Devuelve SIS-Leg a servicio cuando el sistema anterior no pudo volver.

        Entradas:
            snapshot: identidad y habilitación del SIS-Leg que estaba sano.
            resultado: se anotan las acciones y el desenlace del rollback.
            error_original: la falla que obligó a revertir.

        Errores:
            ErrorOperacionHost siempre. Si el rollback funcionó, informa la falla
            original y que el host volvió a SIS-Leg; si además falló el rollback,
            informa los dos errores y exige intervención humana.

        ¿Por qué existe? Porque pasar de un sistema sano a un host inerte sería
        el peor desenlace posible de una operación que existe para dar seguridad.
        Si el sistema anterior no arranca o no supera su health, lo correcto no
        es quedarse a mitad de camino, sino devolver el recinto al sistema que
        hasta hace un minuto estaba atendiendo.

        El orden respeta la invariante de exclusión: primero se retira el sistema
        anterior a medio levantar —con su disable-first verificado— y recién
        entonces se reactiva SIS-Leg, de modo que nunca haya dos bridges vivos.
        """

        if snapshot.release is None:
            resultado.rollback = ROLLBACK_FALLIDO
            raise ErrorOperacionHost(
                f"Falló la vuelta al sistema anterior ({error_original}) y no había una "
                "release de SIS-Leg identificable para restaurar. Se requiere intervención "
                "humana; no se ejecuta ninguna recuperación automática a ciegas."
            ) from error_original

        try:
            self._retirar_legacy(resultado)
            self._rehabilitar_vhost_sisleg()
            self.gestor.activar(snapshot.release)
            self.inspector.exigir_maximo_un_bridge()
            if snapshot.backend_habilitado:
                self._systemctl("enable", SERVICIO_BACKEND, comprobar=False)
            if snapshot.bridge_habilitado:
                self._systemctl("enable", SERVICIO_BRIDGE, comprobar=False)
            resultado.acciones.append(f"SIS-Leg restaurado en la release {snapshot.release}")
            estado = self.inspector.clasificar()
            if estado != ESTABLE_SISLEG:
                raise ErrorOperacionHost(
                    f"El rollback dejó el host en {estado} y no en {ESTABLE_SISLEG}."
                )
        except Exception as error_rollback:  # noqa: BLE001 - se reportan ambos errores
            resultado.rollback = ROLLBACK_FALLIDO
            raise ErrorOperacionHost(
                f"Falló la vuelta al sistema anterior ({error_original}) y también la "
                f"restauración de SIS-Leg ({error_rollback}). El host quedó en un estado que "
                "exige intervención humana inmediata: ningún sistema puede darse por activo "
                "y no se intenta ninguna recuperación automática adicional."
            ) from error_rollback
        resultado.rollback = ROLLBACK_EXITOSO
        resultado.estado_final = ESTABLE_SISLEG
        raise ErrorOperacionHost(
            "Falló la vuelta al sistema anterior y se restauró SIS-Leg en la release "
            f"{snapshot.release}: {error_original}"
        ) from error_original


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def confirmador_interactivo(plan: PlanOperacion) -> bool:
    """Muestra el plan completo y exige una confirmación explícita por teclado.

    Se pide ``si`` escrito entero y no una tecla suelta: una conmutación del
    recinto no debería poder dispararse por un enter distraído.
    """

    print(f"Operación: {plan.operacion}")
    print(f"Estado formal actual: {plan.estado_inicial}")
    print(f"Release en uso: {plan.release_actual or 'ninguna'}")
    print(f"target-release actual: {plan.target_actual or 'ninguno'}")
    print(f"Release objetivo: {plan.sha_objetivo or 'no aplica'}")
    print("Se hará:")
    for accion in plan.acciones_previstas:
        print(f"  - {accion}")
    return input("¿Continuar? Escribí «si» para confirmar: ").strip().lower() == "si"


def crear_parser() -> argparse.ArgumentParser:
    """Expone las tres operaciones con nombres estables para los wrappers."""

    parser = argparse.ArgumentParser(
        description="Operaciones de usuario del host institucional de SIS-Leg."
    )
    parser.add_argument("--raiz", type=Path, default=Path("/opt/sis-leg"))
    parser.add_argument(
        "--sin-confirmacion",
        action="store_true",
        help="Omite la confirmación interactiva; pensado para operación desatendida.",
    )
    parser.add_argument(
        "--registro",
        type=Path,
        default=None,
        help="Archivo de historial donde anexar el resultado. Nunca contiene secretos.",
    )
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser(OPERACION_ACTUALIZAR, help="Trae la release pública de main y la prepara.")
    sub.add_parser(
        OPERACION_CAMBIAR_A_SISLEG, help="Activa la release declarada en target-release."
    )
    sub.add_parser(OPERACION_CAMBIAR_A_LEGACY, help="Devuelve el recinto al sistema anterior.")
    return parser


def _anexar_registro(ruta: Path, resultado: ResultadoOperacion) -> None:
    """Anexa una línea JSON al historial del host, sin datos sensibles.

    Se escribe una línea por operación, en formato JSON Lines, con ``flush`` y
    ``fsync`` antes de cerrar. El criterio es el mismo de la auditoría
    institucional: un historial que sólo llega al buffer del sistema operativo
    no es evidencia, porque una caída se lleva justamente el registro de lo que
    estaba pasando cuando el host se cayó.
    """

    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("a", encoding="utf-8") as archivo:
        archivo.write(json.dumps(asdict(resultado), ensure_ascii=False, sort_keys=True) + "\n")
        archivo.flush()
        os.fsync(archivo.fileno())


def registrar_en_historial(ruta: Path | None, resultado: ResultadoOperacion) -> bool:
    """Anexa el resultado al historial sin dejar que su falla altere la operación.

    Resultado: ``True`` si el historial se persistió; ``False`` si no se pudo.

    ¿Por qué no propaga el error? Porque falsearía el desenlace: una conmutación
    que dejó el recinto funcionando no se convierte en un fracaso porque el
    archivo de historial esté en un disco lleno, y una que falló no se convierte
    en un éxito porque su registro sí se haya escrito. La falla del registro se
    informa por separado y de forma explícita —nunca se silencia— y el resultado
    impreso deja constancia de que ese registro no quedó persistido.
    """

    if ruta is None:
        return True
    try:
        _anexar_registro(ruta, resultado)
    except OSError as error:
        print(
            f"Advertencia: no se pudo anexar el historial en {ruta}: {error}. "
            "El resultado de la operación se informa igual y no se altera.",
            file=sys.stderr,
        )
        return False
    return True


def main(argumentos: Sequence[str] | None = None) -> int:
    """Ejecuta una operación, registra su desenlace y devuelve el exit code.

    El historial se anexa en los cuatro desenlaces —éxito, cancelación, falla y
    falla con rollback— y no sólo cuando todo salió bien. Un historial que
    únicamente conserva los éxitos es exactamente el que no sirve el día que hay
    que reconstruir qué pasó.
    """

    opciones = crear_parser().parse_args(argumentos)
    operador = OperadorHost(opciones.raiz)
    confirmador = None if opciones.sin_confirmacion else confirmador_interactivo
    operaciones: dict[str, Callable[..., ResultadoOperacion]] = {
        OPERACION_ACTUALIZAR: operador.actualizar,
        OPERACION_CAMBIAR_A_SISLEG: operador.cambiar_a_sis_leg,
        OPERACION_CAMBIAR_A_LEGACY: operador.cambiar_a_legacy,
    }
    try:
        resultado = operaciones[opciones.comando](confirmador=confirmador)
    except (
        ErrorOperacionHost,
        ErrorEstadoHost,
        ErrorDespliegue,
        ErrorConfiguracionLocal,
        ErrorActualizadorPublico,
        OSError,
    ) as error:
        resultado = resultado_de_falla(operador, opciones.comando, error)
        persistido = registrar_en_historial(opciones.registro, resultado)
        print(f"Error: {error}", file=sys.stderr)
        if not persistido:
            print("Error: además, el historial no pudo persistirse.", file=sys.stderr)
        return resultado.exit_code
    salida = asdict(resultado)
    if opciones.registro is not None:
        # Se informa junto al resultado si el historial quedó realmente escrito:
        # quien lea la salida no debería tener que suponerlo.
        salida["registro_persistido"] = registrar_en_historial(opciones.registro, resultado)
    print(json.dumps(salida, ensure_ascii=False, indent=2, sort_keys=True))
    return resultado.exit_code


def resultado_de_falla(
    operador: OperadorHost, comando: str, error: Exception
) -> ResultadoOperacion:
    """Completa el resultado que hay que registrar cuando la operación falló.

    Si la operación llegó a construir su resultado, se lo reutiliza: conserva el
    estado inicial, las acciones ya ejecutadas, la evidencia pública y el
    desenlace del rollback. Si falló antes de llegar a construirlo —por ejemplo
    porque otra operación tenía el lock— se arma uno mínimo, porque incluso ese
    intento fallido merece quedar en el historial.
    """

    resultado = operador.ultimo_resultado
    if resultado is None:
        resultado = ResultadoOperacion(
            operacion=comando,
            estado_inicial="DESCONOCIDO",
            estado_final="DESCONOCIDO",
            sha_objetivo=None,
            target_previo=None,
            target_final=None,
            muto=False,
            mensaje="",
            timestamp=marca_temporal_local(),
        )
    resultado.estado = ESTADO_FALLA
    resultado.exit_code = 1
    resultado.error = str(error)
    if not resultado.mensaje:
        resultado.mensaje = f"La operación {resultado.operacion} falló y no se completó."
    return resultado


if __name__ == "__main__":
    raise SystemExit(main())
