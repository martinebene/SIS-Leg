"""Servicio serializado para datos institucionales y ciclo de sesión.

Cada operación entra por el ``EjecutorMutaciones`` único. Dentro de esa
sección crítica se mantiene la regla institucional ``AUDITAR -> MUTAR``: un
cambio no toca memoria hasta que su evento obligatorio quedó persistido con la
durabilidad del escritor de WP-004. WP-013 extiende el cierre para resolver
una votación ``EN_CURSO`` o ``EMPATADA`` dentro de esa misma adquisición.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import NoReturn

from sis_leg_backend.auditoria import NivelAuditoria
from sis_leg_backend.dominio.errores import (
    ErrorEstadoIncompatible,
    ErrorNumeroSesionRequerido,
    ErrorPresidenciaRequerida,
    ErrorQuorumInsuficiente,
    ErrorSecretariaLegislativaRequerida,
    ErrorVotacionPendiente,
)
from sis_leg_backend.dominio.estado import EstadoGlobal, EstadoOperativo
from sis_leg_backend.dominio.preparacion import Preparacion
from sis_leg_backend.dominio.sesion import (
    ActualizacionDatosInstitucionales,
    Sesion,
)
from sis_leg_backend.dominio.votacion import (
    CausaFinalizacionInconclusa,
    EstadoVotacion,
    ResultadoVotacion,
)
from sis_leg_backend.servicios.finalizacion_votacion import (
    finalizar_votacion_inconclusa_bajo_lock,
)
from sis_leg_backend.servicios.serializacion import EjecutorMutaciones

ETIQUETA_SESION = "SESION"
CODIGO_NUMERO_SESION_ACTUALIZADO = "NUMERO_SESION_ACTUALIZADO"
CODIGO_PRESIDENCIA_ACTUALIZADA = "PRESIDENCIA_ACTUALIZADA"
CODIGO_SECRETARIA_LEGISLATIVA_ACTUALIZADA = "SECRETARIA_LEGISLATIVA_ACTUALIZADA"
CODIGO_SESION_ABIERTA = "SESION_ABIERTA"
CODIGO_SESION_CERRADA = "SESION_CERRADA"
CODIGO_COMANDO_SESION_RECHAZADO = "COMANDO_SESION_RECHAZADO"


class ServicioSesion:
    """Orquesta el ciclo y las autoridades sobre el estado operativo único.

    El servicio no conserva estado propio. Recibe las mismas instancias de
    ``EstadoOperativo`` y ``EjecutorMutaciones`` que preparación y entradas.
    El reloj civil se inyecta para que las pruebas puedan afirmar la fecha de
    apertura sin depender del tiempo real.
    """

    def __init__(
        self,
        estado_operativo: EstadoOperativo,
        ejecutor_mutaciones: EjecutorMutaciones,
        *,
        reloj: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._estado = estado_operativo
        self._ejecutor = ejecutor_mutaciones
        self._reloj = reloj

    async def actualizar_preparacion(
        self,
        actualizacion: ActualizacionDatosInstitucionales,
    ) -> None:
        """Actualiza número/autoridades durante ``PREPARANDO``.

        Los campos efectivos se procesan siempre en el orden número,
        Presidencia y Secretaría. Cada uno se audita antes de su propia
        asignación; un no-op no inventa eventos.
        """

        await self._ejecutor.ejecutar(lambda: self._actualizar_preparacion_bajo_lock(actualizacion))

    async def abrir_sesion(self) -> None:
        """Valida precondiciones, audita y abre conservando el contexto."""

        await self._ejecutor.ejecutar(self._abrir_sesion_bajo_lock)

    async def actualizar_autoridades(
        self,
        actualizacion: ActualizacionDatosInstitucionales,
    ) -> None:
        """Cambia autoridades informadas de una sesión abierta."""

        await self._ejecutor.ejecutar(lambda: self._actualizar_autoridades_bajo_lock(actualizacion))

    async def cerrar_sesion(self) -> None:
        """Resuelve la votación pendiente autorizada y cierra el contexto."""

        await self._ejecutor.ejecutar(self._cerrar_sesion_bajo_lock)

    async def _actualizar_preparacion_bajo_lock(
        self,
        actualizacion: ActualizacionDatosInstitucionales,
    ) -> None:
        """Ejecuta el PATCH preparatorio con el lock global ya adquirido."""

        if self._estado.estado_global is not EstadoGlobal.PREPARANDO:
            self._rechazar(
                "actualizar preparación",
                "ESTADO_INCOMPATIBLE",
                ErrorEstadoIncompatible(
                    "Los datos preparatorios solo pueden actualizarse en PREPARANDO "
                    f"(estado actual: {self._estado.estado_global.value})"
                ),
            )

        preparacion = self._preparacion_requerida()
        if not any(
            (
                actualizacion.incluye_numero_sesion,
                actualizacion.incluye_presidencia,
                actualizacion.incluye_secretaria_legislativa,
            )
        ):
            raise ValueError("La actualización debe incluir al menos un campo")

        if actualizacion.incluye_numero_sesion:
            numero = actualizacion.numero_sesion
            if isinstance(numero, bool) or not isinstance(numero, int) or numero < 1:
                raise ValueError("El número de sesión debe ser un entero estricto positivo")
            if numero != preparacion.numero_sesion:
                self._registrar_actualizacion(
                    preparacion,
                    CODIGO_NUMERO_SESION_ACTUALIZADO,
                    "Número de sesión",
                    preparacion.numero_sesion,
                    numero,
                )
                preparacion.numero_sesion = numero

        if actualizacion.incluye_presidencia:
            presidencia = self._normalizar_autoridad_preparacion(actualizacion.presidencia)
            if presidencia != preparacion.presidencia:
                self._registrar_actualizacion(
                    preparacion,
                    CODIGO_PRESIDENCIA_ACTUALIZADA,
                    "Presidencia",
                    preparacion.presidencia,
                    presidencia,
                )
                preparacion.presidencia = presidencia

        if actualizacion.incluye_secretaria_legislativa:
            secretaria = self._normalizar_autoridad_preparacion(
                actualizacion.secretaria_legislativa
            )
            if secretaria != preparacion.secretaria_legislativa:
                self._registrar_actualizacion(
                    preparacion,
                    CODIGO_SECRETARIA_LEGISLATIVA_ACTUALIZADA,
                    "Secretaría Legislativa",
                    preparacion.secretaria_legislativa,
                    secretaria,
                )
                preparacion.secretaria_legislativa = secretaria

    async def _abrir_sesion_bajo_lock(self) -> None:
        """Evalúa las precondiciones en el orden aprobado y realiza la transición."""

        if self._estado.estado_global is not EstadoGlobal.PREPARANDO:
            self._rechazar(
                "abrir sesión",
                "ESTADO_INCOMPATIBLE",
                ErrorEstadoIncompatible(
                    "Solo puede abrirse una sesión desde PREPARANDO "
                    f"(estado actual: {self._estado.estado_global.value})"
                ),
            )

        preparacion = self._preparacion_requerida()
        if not preparacion.quorum_alcanzado():
            self._rechazar(
                "abrir sesión",
                "QUORUM_INSUFICIENTE",
                ErrorQuorumInsuficiente("No puede abrirse la sesión sin quórum."),
            )
        if preparacion.numero_sesion is None:
            self._rechazar(
                "abrir sesión",
                "NUMERO_SESION_REQUERIDO",
                ErrorNumeroSesionRequerido("Debe informarse el número de sesión."),
            )
        if preparacion.presidencia is None:
            self._rechazar(
                "abrir sesión",
                "PRESIDENCIA_REQUERIDA",
                ErrorPresidenciaRequerida("Debe informarse Presidencia."),
            )
        if preparacion.secretaria_legislativa is None:
            self._rechazar(
                "abrir sesión",
                "SECRETARIA_LEGISLATIVA_REQUERIDA",
                ErrorSecretariaLegislativaRequerida("Debe informarse Secretaría Legislativa."),
            )

        numero = preparacion.numero_sesion
        preparacion.escritor_auditoria.registrar_evento(
            NivelAuditoria.L3,
            ETIQUETA_SESION,
            CODIGO_SESION_ABIERTA,
            f"Apertura de sesión Nº{numero}",
        )

        # La sesión compone exactamente el objeto existente. Recién después de
        # persistir el evento se cambia cuál referencia publica el estado.
        sesion = Sesion(
            contexto_operativo=preparacion,
            fecha_hora_apertura=self._reloj(),
        )
        self._estado.preparacion_activa = None
        self._estado.sesion_activa = sesion
        self._estado.estado_global = EstadoGlobal.SESION_ABIERTA

    async def _actualizar_autoridades_bajo_lock(
        self,
        actualizacion: ActualizacionDatosInstitucionales,
    ) -> None:
        """Ejecuta el PATCH de sesión sin habilitar cambios de número."""

        if self._estado.estado_global is not EstadoGlobal.SESION_ABIERTA:
            self._rechazar(
                "actualizar autoridades",
                "ESTADO_INCOMPATIBLE",
                ErrorEstadoIncompatible(
                    "Las autoridades de sesión solo pueden actualizarse en "
                    f"SESION_ABIERTA (estado actual: {self._estado.estado_global.value})"
                ),
            )
        if actualizacion.incluye_numero_sesion:
            raise ValueError("El número de sesión es inmutable después de abrir")
        if not (actualizacion.incluye_presidencia or actualizacion.incluye_secretaria_legislativa):
            raise ValueError("La actualización debe incluir al menos una autoridad")

        sesion = self._sesion_requerida()
        contexto = sesion.contexto_operativo
        if actualizacion.incluye_presidencia:
            presidencia = self._normalizar_autoridad_sesion(
                actualizacion.presidencia,
                "Presidencia",
            )
            if presidencia != contexto.presidencia:
                self._registrar_actualizacion(
                    contexto,
                    CODIGO_PRESIDENCIA_ACTUALIZADA,
                    "Presidencia",
                    contexto.presidencia,
                    presidencia,
                )
                contexto.presidencia = presidencia

        if actualizacion.incluye_secretaria_legislativa:
            secretaria = self._normalizar_autoridad_sesion(
                actualizacion.secretaria_legislativa,
                "Secretaría Legislativa",
            )
            if secretaria != contexto.secretaria_legislativa:
                self._registrar_actualizacion(
                    contexto,
                    CODIGO_SECRETARIA_LEGISLATIVA_ACTUALIZADA,
                    "Secretaría Legislativa",
                    contexto.secretaria_legislativa,
                    secretaria,
                )
                contexto.secretaria_legislativa = secretaria

    async def _cerrar_sesion_bajo_lock(self) -> None:
        """Compone votación y sesión bajo una sola adquisición del lock.

        Cada hecho se audita antes de su mutación. Si la votación ya quedó
        ``INCONCLUSA`` y luego falla ``SESION_CERRADA``, no se hace rollback:
        la memoria refleja el último evento institucional durable.
        """

        if self._estado.estado_global is not EstadoGlobal.SESION_ABIERTA:
            self._rechazar(
                "cerrar sesión",
                "ESTADO_INCOMPATIBLE",
                ErrorEstadoIncompatible(
                    "Solo puede cerrarse una sesión desde SESION_ABIERTA "
                    f"(estado actual: {self._estado.estado_global.value})"
                ),
            )

        sesion = self._sesion_requerida()
        votacion = self._estado.votacion_activa
        if (
            votacion is not None
            and votacion.estado is EstadoVotacion.EN_CURSO
            and votacion.resultado is None
        ):
            finalizar_votacion_inconclusa_bajo_lock(
                estado_operativo=self._estado,
                contexto=sesion.contexto_operativo,
                votacion=votacion,
                causa=CausaFinalizacionInconclusa.CIERRE_SESION,
                fecha_hora_cierre=self._reloj(),
                reloj_resultado=self._reloj,
            )
        elif (
            votacion is not None
            and votacion.estado is EstadoVotacion.CERRADA
            and votacion.resultado is ResultadoVotacion.EMPATADA
        ):
            fecha_existente = votacion.fecha_hora_cierre
            if fecha_existente is None:
                raise RuntimeError("Votación EMPATADA sin fecha de cierre")
            finalizar_votacion_inconclusa_bajo_lock(
                estado_operativo=self._estado,
                contexto=sesion.contexto_operativo,
                votacion=votacion,
                causa=CausaFinalizacionInconclusa.CIERRE_SESION,
                fecha_hora_cierre=fecha_existente,
                reloj_resultado=self._reloj,
            )
        elif votacion is not None:
            # ``CERRADA + None`` solo puede representar el fallo cerrado entre
            # cierre y resultado de WP-011. Este WP no lo calcula ni lo repara;
            # con el writer realmente fallado prevalecerá el 503 al auditar el
            # rechazo, y una construcción artificial saludable seguirá siendo
            # un conflicto funcional sin mutar la entidad.
            self._rechazar(
                "cerrar sesión",
                "VOTACION_PENDIENTE",
                ErrorVotacionPendiente(
                    "La votación pendiente no admite resolución por este flujo."
                ),
            )

        escritor = sesion.contexto_operativo.escritor_auditoria
        escritor.registrar_evento(
            NivelAuditoria.L3,
            ETIQUETA_SESION,
            CODIGO_SESION_CERRADA,
            f"Cierre de sesión Nº{sesion.numero_sesion}",
        )
        escritor.cerrar()

        # Si ``cerrar()`` falla, la excepción corta el flujo antes de estas
        # asignaciones. Se conserva la sesión y sus rutas en fallo cerrado.
        self._estado.preparacion_activa = None
        self._estado.sesion_activa = None
        self._estado.votacion_activa = None
        self._estado.archivos_auditoria_activos = ()
        self._estado.estado_global = EstadoGlobal.SIN_PREPARAR

    def _rechazar(
        self,
        operacion: str,
        codigo: str,
        error: Exception,
    ) -> NoReturn:
        """Audita un rechazo funcional cuando existe contexto y luego lo lanza.

        Si este evento L2 no puede persistirse, la excepción de auditoría
        prevalece y la API responde 503. Eso evita informar un rechazo normal
        como si el sistema siguiera pudiendo garantizar su registro.
        """

        contexto = self._estado.contexto_operativo_activo()
        if contexto is not None:
            contexto.escritor_auditoria.registrar_evento(
                NivelAuditoria.L2,
                ETIQUETA_SESION,
                CODIGO_COMANDO_SESION_RECHAZADO,
                f"Comando de sesión rechazado: operación={operacion}; código={codigo}",
            )
        raise error

    @staticmethod
    def _registrar_actualizacion(
        preparacion: Preparacion,
        codigo: str,
        campo: str,
        anterior: int | str | None,
        nuevo: int | str | None,
    ) -> None:
        """Persiste un cambio institucional con representación humana estable."""

        preparacion.escritor_auditoria.registrar_evento(
            NivelAuditoria.L3,
            ETIQUETA_SESION,
            codigo,
            f"{campo} actualizado: "
            f"{ServicioSesion._valor_humano(anterior)} -> "
            f"{ServicioSesion._valor_humano(nuevo)}",
        )

    @staticmethod
    def _valor_humano(valor: int | str | None) -> str:
        """Representa de forma legible un valor institucional opcional."""

        return "sin informar" if valor is None else str(valor)

    @staticmethod
    def _normalizar_autoridad_preparacion(valor: str | None) -> str | None:
        """Retira espacios y convierte vacío/blancos en ausencia."""

        if valor is None:
            return None
        normalizado = valor.strip()
        return normalizado or None

    @staticmethod
    def _normalizar_autoridad_sesion(valor: str | None, nombre: str) -> str:
        """Normaliza una autoridad que no puede quedar vacía en sesión."""

        if valor is None or not valor.strip():
            raise ValueError(f"{nombre} debe permanecer informada")
        return valor.strip()

    def _preparacion_requerida(self) -> Preparacion:
        """Recupera la preparación o señala una invariante interna rota."""

        preparacion = self._estado.preparacion_activa
        if preparacion is None:
            raise RuntimeError("Estado PREPARANDO sin preparación activa")
        return preparacion

    def _sesion_requerida(self) -> Sesion:
        """Recupera la sesión o señala una invariante interna rota."""

        sesion = self._estado.sesion_activa
        if sesion is None:
            raise RuntimeError("Estado SESION_ABIERTA sin sesión activa")
        return sesion
