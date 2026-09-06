"""Comandos serializados de Moderación para el uso de la palabra (WP-015).

Este servicio no mantiene cola, orador, lock ni escritor propios. Compone el
estado ``Sesion.palabra`` con los recursos únicos del proceso y aplica siempre
la secuencia institucional ``AUDITAR -> MUTAR``. En especial, reemplazar un
orador requiere dos hechos durables independientes: si el segundo falla, el
primero no se revierte y el pedido FIFO permanece intacto.
"""

from __future__ import annotations

from sis_leg_backend.auditoria import NivelAuditoria
from sis_leg_backend.configuracion.modelos import Concejal
from sis_leg_backend.dominio.errores import ErrorEstadoIncompatible
from sis_leg_backend.dominio.estado import EstadoGlobal, EstadoOperativo
from sis_leg_backend.dominio.sesion import Sesion
from sis_leg_backend.servicios.serializacion import EjecutorMutaciones

ETIQUETA_PALABRA = "PALABRA"
CODIGO_USO_PALABRA_OTORGADO = "USO_PALABRA_OTORGADO"
CODIGO_USO_PALABRA_FINALIZADO = "USO_PALABRA_FINALIZADO"
CODIGO_COMANDO_PALABRA_SIN_EFECTO = "COMANDO_PALABRA_SIN_EFECTO"

CAUSA_FINALIZACION_MODERACION = "MODERACION"


class ServicioPalabra:
    """Otorga o quita palabra sobre la sesión autoritativa.

    Ambos comandos adquieren una sola vez el ``EjecutorMutaciones`` compartido.
    Los helpers ``*_bajo_lock`` no vuelven a adquirirlo, por lo que palabra se
    ordena con presencia, votos, votaciones y cierre de sesión mediante la misma
    secuencia oficial.
    """

    def __init__(
        self,
        estado_operativo: EstadoOperativo,
        ejecutor_mutaciones: EjecutorMutaciones,
    ) -> None:
        self._estado = estado_operativo
        self._ejecutor = ejecutor_mutaciones

    async def otorgar_palabra(self) -> None:
        """Finaliza al orador actual y luego otorga el primer pedido FIFO.

        La ausencia total de orador y pedidos es un no-op exitoso, aunque se
        registra como diagnóstico L2 mientras la auditoría siga saludable.

        Raises:
            ErrorEstadoIncompatible: si no existe una sesión abierta.
            ErrorAuditoria: si no puede persistirse un evento obligatorio.
        """

        await self._ejecutor.ejecutar(self._otorgar_palabra_bajo_lock)

    async def quitar_palabra(self) -> None:
        """Finaliza al orador sin promover automáticamente al siguiente."""

        await self._ejecutor.ejecutar(self._quitar_palabra_bajo_lock)

    async def _otorgar_palabra_bajo_lock(self) -> None:
        """Compone finalización y otorgamiento con exclusión ya adquirida."""

        sesion = self._sesion_abierta_requerida()
        estado_palabra = sesion.palabra
        hubo_mutacion = False

        orador_actual = estado_palabra.orador_dni
        if orador_actual is not None:
            concejal_actual = self._buscar_concejal_requerido(sesion, orador_actual)
            self._registrar_finalizacion(sesion, concejal_actual)
            # Este hecho ya quedó durable. Si un evento posterior falla, no se
            # reinstala al orador porque eso contradiría la auditoría confirmada.
            estado_palabra.finalizar_uso(orador_actual)
            hubo_mutacion = True

        primer_pedido = estado_palabra.primer_pedido_dni
        if primer_pedido is not None:
            siguiente = self._buscar_concejal_requerido(sesion, primer_pedido)
            sesion.contexto_operativo.escritor_auditoria.registrar_evento(
                NivelAuditoria.L3,
                ETIQUETA_PALABRA,
                CODIGO_USO_PALABRA_OTORGADO,
                self.mensaje_uso_otorgado(siguiente),
            )
            # El pedido se retira recién después de fsync. Ante fallo conserva
            # su primera posición y la operación externa informa 503.
            estado_palabra.otorgar_primer_pedido(primer_pedido)
            return

        if not hubo_mutacion:
            self._registrar_noop(sesion, "OTORGAR", "SIN_ORADOR_NI_PEDIDOS")

    async def _quitar_palabra_bajo_lock(self) -> None:
        """Finaliza solo al orador actual con exclusión ya adquirida."""

        sesion = self._sesion_abierta_requerida()
        orador_actual = sesion.palabra.orador_dni
        if orador_actual is None:
            self._registrar_noop(sesion, "QUITAR", "SIN_ORADOR")
            return

        concejal = self._buscar_concejal_requerido(sesion, orador_actual)
        self._registrar_finalizacion(sesion, concejal)
        sesion.palabra.finalizar_uso(orador_actual)

    def _sesion_abierta_requerida(self) -> Sesion:
        """Devuelve la sesión o produce el conflicto HTTP estable de WP-015."""

        if (
            self._estado.estado_global is not EstadoGlobal.SESION_ABIERTA
            or self._estado.sesion_activa is None
        ):
            raise ErrorEstadoIncompatible(
                "El comando de palabra exige una sesión abierta "
                f"(estado actual: {self._estado.estado_global.value})."
            )
        return self._estado.sesion_activa

    @staticmethod
    def _buscar_concejal_requerido(sesion: Sesion, dni: str) -> Concejal:
        """Resuelve el DNI exclusivamente contra el padrón congelado."""

        concejal = next(
            (
                integrante
                for integrante in sesion.contexto_operativo.padron.concejales
                if integrante.dni == dni
            ),
            None,
        )
        if concejal is None:
            raise RuntimeError("Estado de palabra con DNI ajeno al padrón congelado")
        return concejal

    @staticmethod
    def mensaje_identidad(concejal: Concejal) -> str:
        """Representa identidad humana y técnica suficiente para auditoría."""

        return (
            f"DNI={concejal.dni}; concejal={concejal.nombre} {concejal.apellido}; "
            f"banca={concejal.banca}"
        )

    @classmethod
    def mensaje_uso_otorgado(cls, concejal: Concejal) -> str:
        """Describe que el primer pedido FIFO se convirtió en orador."""

        return f"Uso de palabra otorgado: {cls.mensaje_identidad(concejal)}; posicion_origen=1"

    def _registrar_finalizacion(self, sesion: Sesion, concejal: Concejal) -> None:
        """Persiste una finalización de Moderación antes de limpiar el orador."""

        sesion.contexto_operativo.escritor_auditoria.registrar_evento(
            NivelAuditoria.L3,
            ETIQUETA_PALABRA,
            CODIGO_USO_PALABRA_FINALIZADO,
            (
                f"Uso de palabra finalizado: {self.mensaje_identidad(concejal)}; "
                f"causa={CAUSA_FINALIZACION_MODERACION}"
            ),
        )

    @staticmethod
    def _registrar_noop(sesion: Sesion, operacion: str, motivo: str) -> None:
        """Registra un diagnóstico L2 sin inventar un hecho institucional L3."""

        sesion.contexto_operativo.escritor_auditoria.registrar_evento(
            NivelAuditoria.L2,
            ETIQUETA_PALABRA,
            CODIGO_COMANDO_PALABRA_SIN_EFECTO,
            f"Comando de palabra sin efecto: operacion={operacion}; motivo={motivo}",
        )
