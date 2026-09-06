"""Servicio de dominio para preparar el recinto y cancelar la preparación (WP-005).

Implementa las dos primeras transiciones del ciclo de vida:

- ``SIN_PREPARAR -> PREPARANDO`` (``Preparar recinto``, CU-01);
- ``PREPARANDO -> SIN_PREPARAR`` (cancelar preparación, CU-02).

Ambas operaciones se ejecutan por completo dentro del ``EjecutorMutaciones``
único del proceso (DT-004, DT-014 del documento 04), de modo que dos comandos
concurrentes se ordenan uno detrás del otro y nunca producen estados
simultáneos (CA-058).

Las operaciones son síncronas aunque viajen por un ejecutor ``async``: la
escritura de auditoría es deliberadamente bloqueante (DT-012 exige
``write`` + ``flush`` + ``fsync`` antes de confirmar) y el volumen de trabajo
es ínfimo (leer dos archivos chicos y escribir pocas filas). Mantener todo en
el hilo del loop evita introducir hilos adicionales que complicarían el orden
oficial de eventos.

Semántica de fallo cerrado:

- Si falla la carga de configuración o padrón, no se crea preparación activa
  y el sistema permanece en ``SIN_PREPARAR``.
- Si la creación del conjunto CSV o el registro de ``PREPARACION_INICIADA``
  fallan, los archivos alcanzados a crear se conservan como evidencia técnica
  (nunca se borran para simular que no existieron), el escritor se cierra en
  la medida segura posible sin ocultar el error original y el sistema
  permanece en ``SIN_PREPARAR``.
- Si la cancelación no puede persistir ``PREPARACION_CANCELADA`` o no puede
  cerrar el conjunto, la operación no se confirma: el estado permanece
  ``PREPARANDO`` y el escritor queda en fallo cerrado (WP-004), por lo que
  las mutaciones dependientes de auditoría siguen rechazándose. La
  recuperación práctica es el reinicio del backend, que vuelve a
  ``SIN_PREPARAR`` sin reconstruir la preparación anterior (RN-GLOBAL-03).
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from datetime import datetime
from pathlib import Path

from sis_leg_backend.auditoria import EscritorAuditoriaCsv, NivelAuditoria
from sis_leg_backend.configuracion.cargar_configuracion import cargar_configuracion_sistema
from sis_leg_backend.configuracion.cargar_padron import cargar_padron_concejales
from sis_leg_backend.dominio.errores import ErrorEstadoIncompatible
from sis_leg_backend.dominio.estado import EstadoGlobal, EstadoOperativo
from sis_leg_backend.dominio.preparacion import Preparacion
from sis_leg_backend.servicios.serializacion import EjecutorMutaciones

# Rutas canónicas de los archivos que carga ``Preparar recinto``. El cliente no
# las suministra: el contrato REST fija que el backend carga siempre estos
# archivos propios, resueltos contra el directorio de trabajo del proceso.
RUTA_CONFIGURACION_POR_DEFECTO = Path("config/system.toml")
RUTA_PADRON_POR_DEFECTO = Path("config/concejales.csv")

# Datos canónicos del evento institucional de inicio de preparación.
ETIQUETA_PREPARACION = "PREPARACION"
CODIGO_PREPARACION_INICIADA = "PREPARACION_INICIADA"
MENSAJE_PREPARACION_INICIADA = "Preparación del recinto iniciada"
CODIGO_PREPARACION_CANCELADA = "PREPARACION_CANCELADA"
MENSAJE_PREPARACION_CANCELADA = "Preparación del recinto cancelada"


class ServicioPreparacion:
    """Orquesta las mutaciones del ciclo preparar/cancelar sobre el estado único.

    El servicio no guarda estado propio: recibe el ``EstadoOperativo`` y el
    ``EjecutorMutaciones`` compartidos del proceso, de modo que todas las
    instancias (una por request, típicamente) operan sobre la misma fuente de
    verdad y la misma puerta de serialización.

    Los parámetros de rutas, reloj y fábrica de escritor existen para que las
    pruebas puedan aislar el disco y el tiempo; en producción se usan siempre
    los valores por defecto.
    """

    def __init__(
        self,
        estado_operativo: EstadoOperativo,
        ejecutor_mutaciones: EjecutorMutaciones,
        *,
        ruta_configuracion: Path = RUTA_CONFIGURACION_POR_DEFECTO,
        ruta_padron: Path = RUTA_PADRON_POR_DEFECTO,
        reloj: Callable[[], datetime] = datetime.now,
        fabrica_escritor: Callable[[Path, datetime], EscritorAuditoriaCsv] = EscritorAuditoriaCsv,
    ) -> None:
        self._estado = estado_operativo
        self._ejecutor = ejecutor_mutaciones
        self._ruta_configuracion = ruta_configuracion
        self._ruta_padron = ruta_padron
        self._reloj = reloj
        self._fabrica_escritor = fabrica_escritor

    async def preparar_sala(self) -> None:
        """Ejecuta ``Preparar recinto`` completo bajo el serializador único.

        Errores:
            ErrorEstadoIncompatible: si el sistema no está en ``SIN_PREPARAR``.
            ErrorTomlInvalido / ErrorValidacionConfiguracion: si la
                configuración no puede cargarse o validarse (WP-003).
            ErrorPadronInvalido: si el padrón no cumple el contrato (WP-003).
            ErrorAuditoria: si no puede garantizarse la auditoría obligatoria
                (creación del conjunto o persistencia del evento inicial).
        """

        await self._ejecutor.ejecutar(self._preparar_bajo_lock)

    async def cancelar_preparacion(self) -> None:
        """Ejecuta la cancelación completa bajo el serializador único.

        No recibe ni exige motivo (CU-02). Solo confirma éxito cuando el
        evento final quedó persistido y el conjunto CSV quedó cerrado.

        Errores:
            ErrorEstadoIncompatible: si el sistema no está en ``PREPARANDO``.
            ErrorAuditoria: si el evento de cancelación no pudo persistirse o
                el conjunto no pudo cerrarse. En ese caso el estado permanece
                ``PREPARANDO`` y la preparación queda en fallo cerrado.
        """

        await self._ejecutor.ejecutar(self._cancelar_bajo_lock)

    async def _preparar_bajo_lock(self) -> None:
        """Cuerpo síncrono de la preparación; corre con el lock ya tomado.

        El orden de los pasos es parte del contrato: solo se cambia
        ``estado_global`` a ``PREPARANDO`` cuando configuración, padrón,
        auditoría y contexto ya completaron correctamente (WP-005, paso 10).
        Como todo ocurre dentro del lock, ningún observador puede ver un
        estado intermedio.
        """

        if self._estado.estado_global is not EstadoGlobal.SIN_PREPARAR:
            raise ErrorEstadoIncompatible(
                "Solo puede prepararse el recinto desde SIN_PREPARAR "
                f"(estado actual: {self._estado.estado_global.value})"
            )

        # Paso 1: hora local real de inicio. Los nombres de archivo pueden
        # desplazarse por colisiones, pero esta marca conserva la hora real.
        fecha_hora_inicio = self._reloj()

        # Pasos 2 a 4: cargar y congelar configuración y padrón mediante las
        # interfaces públicas de WP-003. Si fallan, la excepción se propaga y
        # no se creó nada: el sistema sigue en SIN_PREPARAR sin estado parcial.
        configuracion = cargar_configuracion_sistema(self._ruta_configuracion)
        padron = cargar_padron_concejales(self._ruta_padron, configuracion)

        # Paso 5: crear el conjunto L1/L2/L3 en el directorio que define la
        # configuración recién cargada. Si falla, el constructor del escritor
        # ya cerró en lo seguro posible los archivos alcanzados a crear, que
        # se conservan en disco como evidencia técnica (WP-005).
        escritor = self._fabrica_escritor(
            Path(configuracion.directorio_registros), fecha_hora_inicio
        )

        # Paso 6: el evento institucional de inicio debe quedar durablemente
        # persistido (escritura + flush + fsync, garantizados por WP-004)
        # antes de confirmar cualquier éxito.
        try:
            escritor.registrar_evento(
                NivelAuditoria.L3,
                ETIQUETA_PREPARACION,
                CODIGO_PREPARACION_INICIADA,
                MENSAJE_PREPARACION_INICIADA,
            )
        except Exception:
            # Los archivos creados no se eliminan. Se intenta cerrar el
            # escritor sin ocultar el error original: si el cierre también
            # falla, la excepción que importa es la del registro del evento.
            with suppress(Exception):
                escritor.cerrar()
            raise

        # Pasos 7 a 10: con todo lo obligatorio ya garantizado, se instala el
        # contexto limpio (todos ausentes, RN-PRE-01) y recién entonces se
        # cambia el estado global.
        preparacion = Preparacion(
            fecha_hora_inicio=fecha_hora_inicio,
            configuracion=configuracion,
            padron=padron,
            presencias={concejal.dni: False for concejal in padron.concejales},
            escritor_auditoria=escritor,
        )
        self._estado.preparacion_activa = preparacion
        self._estado.archivos_auditoria_activos = preparacion.rutas_auditoria()
        # Los sonidos del Recinto (WP-065) viven fuera del ciclo
        # preparación/sesión porque la Pantalla del Recinto también suena en
        # SIN_PREPARAR. Aun así se refrescan aquí desde la configuración recién
        # congelada: si el archivo cambió entre el arranque del proceso y esta
        # preparación, lo que ve el Recinto durante la sesión es exactamente el
        # snapshot congelado y no una copia vieja. No puede fallar ni revertir
        # nada, porque la configuración ya se validó unas líneas más arriba.
        self._estado.sonidos_recinto = configuracion.sonidos_recinto
        self._estado.estado_global = EstadoGlobal.PREPARANDO

    async def _cancelar_bajo_lock(self) -> None:
        """Cuerpo síncrono de la cancelación; corre con el lock ya tomado.

        La cancelación solo se confirma cuando el evento final quedó
        persistido y el conjunto CSV quedó cerrado definitivamente. Si alguno
        de los dos pasos falla, la excepción se propaga sin tocar el estado:
        el sistema permanece en ``PREPARANDO`` y el escritor en fallo cerrado
        (o cerrado) rechaza las mutaciones auditables posteriores.
        """

        if self._estado.estado_global is not EstadoGlobal.PREPARANDO:
            raise ErrorEstadoIncompatible(
                "Solo puede cancelarse una preparación activa en PREPARANDO "
                f"(estado actual: {self._estado.estado_global.value})"
            )

        preparacion = self._estado.preparacion_activa
        if preparacion is None:
            # Invariante interno: PREPARANDO siempre implica preparación
            # activa. Si se rompe, es un error de programación, no de negocio.
            raise RuntimeError("Estado PREPARANDO sin preparación activa")

        escritor = preparacion.escritor_auditoria
        escritor.registrar_evento(
            NivelAuditoria.L3,
            ETIQUETA_PREPARACION,
            CODIGO_PREPARACION_CANCELADA,
            MENSAJE_PREPARACION_CANCELADA,
        )
        escritor.cerrar()

        # Con el evento persistido y el conjunto cerrado, se descarta todo el
        # contexto operativo y el sistema vuelve limpio a SIN_PREPARAR
        # (RN-GLOBAL-02). Los CSV ya escritos quedan intactos en disco.
        self._estado.preparacion_activa = None
        self._estado.archivos_auditoria_activos = ()
        self._estado.estado_global = EstadoGlobal.SIN_PREPARAR
