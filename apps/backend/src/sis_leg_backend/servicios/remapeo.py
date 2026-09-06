"""Servicio coordinador del remapeo rápido backend↔device-bridge."""

from __future__ import annotations

import asyncio
from typing import Protocol
from uuid import uuid4

from sis_leg_backend.auditoria import NivelAuditoria
from sis_leg_backend.dominio.errores import ErrorEstadoIncompatible
from sis_leg_backend.dominio.estado import EstadoGlobal, EstadoOperativo
from sis_leg_backend.dominio.remapeo import (
    ErrorAplicacionBridgeRechazada,
    ErrorBridgeNoDisponible,
    ErrorCandidatoRemapeoNoCoincide,
    ErrorDispositivoRemapeoNoExistente,
    ErrorParametrosRemapeoIncompatibles,
    ErrorRemapeoNoCoincide,
    ErrorRemapeoSinCandidato,
    ErrorRemapeoYaActivo,
    EstadoRemapeo,
    OperacionRemapeo,
    PersistenciaRemapeo,
)
from sis_leg_backend.servicios.cliente_bridge import (
    ErrorRespuestaBridge,
    ErrorTransporteBridge,
    EstadoControlBridge,
)
from sis_leg_backend.servicios.serializacion import EjecutorMutaciones


class ControlBridge(Protocol):
    """Frontera inyectable del HTTP local para pruebas sin red."""

    def iniciar(self, remapeo_id: str, dispositivo: str) -> EstadoControlBridge: ...
    def consultar(self, remapeo_id: str) -> EstadoControlBridge: ...
    def confirmar(
        self, remapeo_id: str, fingerprint: str, persistencia: str
    ) -> EstadoControlBridge: ...
    def cancelar(self, remapeo_id: str) -> EstadoControlBridge: ...


class ServicioRemapeo:
    """Valida negocio, audita autorización y coordina la autoridad física.

    Las secciones que leen o modifican ``EstadoOperativo`` pasan por el único
    ``EjecutorMutaciones``. El HTTP bloqueante de stdlib se ejecuta con
    ``asyncio.to_thread`` *fuera* de ese lock: durante un timeout, los votos y
    demás entradas pueden seguir adquiriendo el serializador normalmente.
    """

    def __init__(
        self,
        estado_operativo: EstadoOperativo,
        ejecutor_mutaciones: EjecutorMutaciones,
        cliente_bridge: ControlBridge,
    ) -> None:
        self._estado = estado_operativo
        self._ejecutor = ejecutor_mutaciones
        self._bridge = cliente_bridge

    async def iniciar(self, dispositivo: str) -> OperacionRemapeo:
        """Reserva un UUID bajo lock y luego ordena captura al bridge."""

        async def reservar() -> OperacionRemapeo:
            if self._estado.estado_global not in (
                EstadoGlobal.PREPARANDO,
                EstadoGlobal.SESION_ABIERTA,
            ):
                raise ErrorEstadoIncompatible(
                    "El remapeo solo puede iniciarse durante preparación o sesión abierta"
                )
            contexto = self._estado.contexto_operativo_activo()
            if contexto is None:
                raise RuntimeError("Estado auditable sin contexto operativo")
            if not any(
                concejal.dispositivo_votacion == dispositivo
                for concejal in contexto.padron.concejales
            ):
                raise ErrorDispositivoRemapeoNoExistente(
                    f"El dispositivo lógico {dispositivo} no pertenece al padrón activo"
                )
            if self._estado.remapeo_activo is not None:
                raise ErrorRemapeoYaActivo("Ya existe un remapeo activo")
            operacion = OperacionRemapeo(
                remapeo_id=str(uuid4()),
                dispositivo=dispositivo,
            )
            self._estado.remapeo_activo = operacion
            return operacion

        operacion = await self._ejecutor.ejecutar(reservar)
        try:
            estado_bridge = await asyncio.to_thread(
                self._bridge.iniciar,
                operacion.remapeo_id,
                operacion.dispositivo,
            )
        except ErrorTransporteBridge as error:
            try:
                estado_bridge = await asyncio.to_thread(
                    self._bridge.consultar, operacion.remapeo_id
                )
            except (ErrorTransporteBridge, ErrorRespuestaBridge):
                await self._marcar_fallo(operacion.remapeo_id, str(error))
                raise ErrorBridgeNoDisponible(
                    "El inicio tuvo resultado incierto y no pudo reconciliarse"
                ) from error
        except ErrorRespuestaBridge as error:
            await self._marcar_fallo(operacion.remapeo_id, error.codigo)
            raise ErrorAplicacionBridgeRechazada(
                f"El bridge rechazó iniciar la captura: {error.codigo}"
            ) from error

        if (
            estado_bridge.remapeo_id != operacion.remapeo_id
            or estado_bridge.dispositivo != operacion.dispositivo
            or estado_bridge.estado not in ("CAPTURANDO", "CANDIDATO")
        ):
            await self._marcar_fallo(operacion.remapeo_id, "RESPUESTA_INCOMPATIBLE")
            raise ErrorAplicacionBridgeRechazada(
                "El bridge devolvió identidad o estado incompatible al iniciar"
            )

        async def completar_inicio() -> OperacionRemapeo:
            activa = self._exigir_activa(operacion.remapeo_id)
            activa.fingerprint_anterior = estado_bridge.fingerprint_anterior
            if estado_bridge.estado == "CANDIDATO" and estado_bridge.candidato is not None:
                activa.candidato = estado_bridge.candidato
                activa.diagnostico = estado_bridge.diagnostico
                activa.estado = EstadoRemapeo.CANDIDATO
            return activa

        return await self._ejecutor.ejecutar(completar_inicio)

    async def registrar_candidato(
        self,
        remapeo_id: str,
        fingerprint: str,
        diagnostico: str | None,
    ) -> OperacionRemapeo:
        """Congela el primer candidato informado por el callback interno."""

        async def registrar() -> OperacionRemapeo:
            operacion = self._exigir_activa(remapeo_id)
            if operacion.candidato is not None:
                if operacion.candidato == fingerprint and operacion.diagnostico == diagnostico:
                    return operacion
                raise ErrorCandidatoRemapeoNoCoincide(
                    "La operación ya posee otro candidato físico congelado"
                )
            if operacion.estado is not EstadoRemapeo.CAPTURANDO:
                raise ErrorRemapeoNoCoincide("La operación ya no está capturando")
            operacion.candidato = fingerprint
            operacion.diagnostico = diagnostico
            operacion.estado = EstadoRemapeo.CANDIDATO
            return operacion

        return await self._ejecutor.ejecutar(registrar)

    async def confirmar(
        self,
        remapeo_id: str,
        persistencia: PersistenciaRemapeo,
    ) -> None:
        """Audita autorización antes de emitir una única orden física.

        Si otro request compatible encuentra ``CONFIRMANDO``, consulta primero
        al bridge en vez de volver a ordenar a ciegas. Una autorización ya
        auditada tampoco genera una segunda fila institucional.
        """

        async def autorizar() -> tuple[OperacionRemapeo, bool]:
            finalizada = self._estado.remapeos_finalizados.get(remapeo_id)
            if finalizada is not None:
                if (
                    finalizada.estado is EstadoRemapeo.APLICADO
                    and finalizada.persistencia is persistencia
                ):
                    return finalizada, False
                raise ErrorParametrosRemapeoIncompatibles(
                    "El remapeo_id ya terminó con otros parámetros o resultado"
                )

            operacion = self._exigir_activa(remapeo_id)
            if operacion.candidato is None:
                raise ErrorRemapeoSinCandidato("No existe candidato para confirmar")
            if operacion.persistencia is not None and operacion.persistencia is not persistencia:
                raise ErrorParametrosRemapeoIncompatibles(
                    "El remapeo_id ya fue autorizado con otra persistencia"
                )
            if operacion.estado is EstadoRemapeo.CONFIRMANDO:
                return operacion, False
            if operacion.estado is not EstadoRemapeo.CANDIDATO:
                raise ErrorRemapeoNoCoincide("El remapeo no está en estado confirmable")

            if not operacion.autorizacion_auditada:
                contexto = self._estado.contexto_operativo_activo()
                if contexto is None:
                    raise ErrorEstadoIncompatible(
                        "No existe una preparación/sesión activa para auditar la confirmación"
                    )
                contexto.escritor_auditoria.registrar_evento(
                    NivelAuditoria.L3,
                    "REMAPEO",
                    "REMAPEO_AUTORIZADO",
                    (
                        "Autorización humana de remapeo "
                        f"remapeo_id={operacion.remapeo_id}; "
                        f"dispositivo={operacion.dispositivo}; "
                        f"fingerprint_anterior={operacion.fingerprint_anterior}; "
                        f"fingerprint_candidato={operacion.candidato}; "
                        f"persistencia={persistencia.value}"
                    ),
                )
                operacion.autorizacion_auditada = True
            operacion.persistencia = persistencia
            operacion.estado = EstadoRemapeo.CONFIRMANDO
            return operacion, True

        operacion, debe_enviar = await self._ejecutor.ejecutar(autorizar)
        if operacion.estado is EstadoRemapeo.APLICADO:
            return

        try:
            if debe_enviar:
                estado_bridge = await asyncio.to_thread(
                    self._bridge.confirmar,
                    remapeo_id,
                    operacion.candidato or "",
                    persistencia.value,
                )
            else:
                estado_bridge = await asyncio.to_thread(self._bridge.consultar, remapeo_id)
        except ErrorTransporteBridge as error:
            estado_bridge = await self._reconciliar_o_fallar(remapeo_id, error)
        except ErrorRespuestaBridge as error:
            await self._marcar_fallo(remapeo_id, error.codigo)
            raise ErrorAplicacionBridgeRechazada(
                f"El bridge rechazó la aplicación/persistencia: {error.codigo}"
            ) from error

        await self._resolver_estado_confirmacion(remapeo_id, estado_bridge)

    async def cancelar(self, remapeo_id: str) -> None:
        """Cancela por el mismo ID y limpia el estado activo al confirmarse."""

        async def validar() -> bool:
            finalizada = self._estado.remapeos_finalizados.get(remapeo_id)
            if finalizada is not None:
                if finalizada.estado is EstadoRemapeo.CANCELADO:
                    return False
                raise ErrorParametrosRemapeoIncompatibles(
                    "El remapeo_id ya terminó y no puede cancelarse"
                )
            self._exigir_activa(remapeo_id)
            return True

        debe_enviar = await self._ejecutor.ejecutar(validar)
        if not debe_enviar:
            return
        try:
            estado_bridge = await asyncio.to_thread(self._bridge.cancelar, remapeo_id)
        except ErrorTransporteBridge as error:
            try:
                estado_bridge = await asyncio.to_thread(self._bridge.consultar, remapeo_id)
            except (ErrorTransporteBridge, ErrorRespuestaBridge):
                raise ErrorBridgeNoDisponible(
                    "La cancelación tuvo resultado incierto y no pudo reconciliarse"
                ) from error
        except ErrorRespuestaBridge as error:
            raise ErrorAplicacionBridgeRechazada(
                f"El bridge rechazó la cancelación: {error.codigo}"
            ) from error
        if estado_bridge.estado != "CANCELADO":
            raise ErrorAplicacionBridgeRechazada(
                f"El bridge respondió estado {estado_bridge.estado} al cancelar"
            )
        await self._finalizar(remapeo_id, EstadoRemapeo.CANCELADO)

    async def _reconciliar_o_fallar(
        self, remapeo_id: str, error_original: Exception
    ) -> EstadoControlBridge:
        """Consulta el estado tras timeout sin repetir el apply."""

        try:
            return await asyncio.to_thread(self._bridge.consultar, remapeo_id)
        except (ErrorTransporteBridge, ErrorRespuestaBridge):
            raise ErrorBridgeNoDisponible(
                "La confirmación tuvo resultado incierto y no pudo reconciliarse"
            ) from error_original

    async def _resolver_estado_confirmacion(
        self, remapeo_id: str, estado_bridge: EstadoControlBridge
    ) -> None:
        if estado_bridge.estado == "APLICADO":
            await self._finalizar(remapeo_id, EstadoRemapeo.APLICADO)
            return
        if estado_bridge.estado == "FALLIDO":
            await self._marcar_fallo(remapeo_id, estado_bridge.error or "FALLO_BRIDGE")
            raise ErrorAplicacionBridgeRechazada(
                "El bridge informó fallo de aplicación/persistencia"
            )
        if estado_bridge.estado in ("CAPTURANDO", "CANDIDATO"):

            async def restaurar_candidato() -> None:
                operacion = self._exigir_activa(remapeo_id)
                operacion.estado = EstadoRemapeo.CANDIDATO

            await self._ejecutor.ejecutar(restaurar_candidato)
            raise ErrorAplicacionBridgeRechazada(
                "La consulta confirmó que el bridge todavía no aplicó el remapeo"
            )
        raise ErrorAplicacionBridgeRechazada(
            f"Estado inesperado del bridge: {estado_bridge.estado}"
        )

    async def _finalizar(self, remapeo_id: str, estado: EstadoRemapeo) -> None:
        async def finalizar() -> None:
            operacion = self._exigir_activa(remapeo_id)
            operacion.estado = estado
            self._estado.remapeos_finalizados[remapeo_id] = operacion
            self._estado.remapeo_activo = None

        await self._ejecutor.ejecutar(finalizar)

    async def _marcar_fallo(self, remapeo_id: str, detalle: str) -> None:
        async def marcar() -> None:
            operacion = self._estado.remapeo_activo
            if operacion is None or operacion.remapeo_id != remapeo_id:
                return
            operacion.estado = EstadoRemapeo.FALLIDO
            operacion.error = detalle
            self._estado.remapeos_finalizados[remapeo_id] = operacion
            self._estado.remapeo_activo = None

        await self._ejecutor.ejecutar(marcar)

    def _exigir_activa(self, remapeo_id: str) -> OperacionRemapeo:
        operacion = self._estado.remapeo_activo
        if operacion is None or operacion.remapeo_id != remapeo_id:
            raise ErrorRemapeoNoCoincide("El remapeo_id no coincide con la operación activa")
        return operacion
