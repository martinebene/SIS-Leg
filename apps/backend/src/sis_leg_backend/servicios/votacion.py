"""Servicio serializado para abrir, finalizar y desempatar una votación.

Cada transición completa ocurre dentro del ``EjecutorMutaciones`` compartido.
El orden es deliberado: validar precondiciones, persistir auditoría y recién
después publicar la mutación institucional correspondiente.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import NoReturn
from uuid import uuid4

from sis_leg_backend.auditoria import NivelAuditoria
from sis_leg_backend.dominio.errores import (
    ErrorDesempateYaEmitido,
    ErrorEstadoIncompatible,
    ErrorQuorumInsuficiente,
    ErrorTipoVotacionNoPermitido,
    ErrorVotacionNoCoincide,
    ErrorVotacionNoEmpatada,
    ErrorVotacionNoEnCurso,
    ErrorVotacionPendiente,
)
from sis_leg_backend.dominio.estado import EstadoGlobal, EstadoOperativo
from sis_leg_backend.dominio.sesion import Sesion
from sis_leg_backend.dominio.votacion import (
    CausaFinalizacionInconclusa,
    ConteosVotosOrdinarios,
    DatosAperturaVotacion,
    EstadoVotacion,
    ResultadoVotacion,
    SentidoVotoDesempate,
    TipoMayoria,
    Votacion,
    VotoDesempate,
)
from sis_leg_backend.servicios.finalizacion_votacion import (
    finalizar_votacion_inconclusa_bajo_lock,
)
from sis_leg_backend.servicios.serializacion import EjecutorMutaciones

ETIQUETA_VOTACION = "VOTACION"
CODIGO_VOTACION_ABIERTA = "VOTACION_ABIERTA"
CODIGO_COMANDO_VOTACION_RECHAZADO = "COMANDO_VOTACION_RECHAZADO"
CODIGO_VOTO_DESEMPATE_PRESIDENCIAL = "VOTO_DESEMPATE_PRESIDENCIAL"
CODIGO_VOTACION_RESULTADO_DESEMPATE = "VOTACION_RESULTADO_DESEMPATE"


def _generar_id_votacion() -> str:
    """Genera un identificador opaco sin estado persistente ni dependencia nueva."""

    return uuid4().hex


class ServicioVotacion:
    """Valida, audita y muta votaciones sobre el estado único del proceso.

    El servicio no conserva una copia de la votación. Recibe el estado y el
    serializador creados por el lifespan; el reloj y el generador de id se
    inyectan únicamente para obtener pruebas deterministas.
    """

    def __init__(
        self,
        estado_operativo: EstadoOperativo,
        ejecutor_mutaciones: EjecutorMutaciones,
        *,
        reloj: Callable[[], datetime] = datetime.now,
        generador_id: Callable[[], str] = _generar_id_votacion,
    ) -> None:
        self._estado = estado_operativo
        self._ejecutor = ejecutor_mutaciones
        self._reloj = reloj
        self._generador_id = generador_id

    async def abrir_votacion(self, datos: DatosAperturaVotacion) -> Votacion:
        """Abre una votación o propaga el rechazo funcional correspondiente.

        Todo el flujo se serializa, incluida la auditoría. Así dos pedidos
        concurrentes no pueden observar simultáneamente un estado sin votación:
        el segundo entra después y encuentra la instancia publicada por el
        primero.

        Raises:
            ErrorEstadoIncompatible: si no existe una sesión abierta.
            ErrorQuorumInsuficiente: si la presencia actual no alcanza quórum.
            ErrorVotacionPendiente: si otra votación continúa publicada.
            ErrorTipoVotacionNoPermitido: si ``tipo`` no integra el snapshot.
            ErrorAuditoria: si no puede persistirse un evento obligatorio.
        """

        return await self._ejecutor.ejecutar(lambda: self._abrir_votacion_bajo_lock(datos))

    async def finalizar_votacion_manualmente(self, id_votacion: str, motivo: str) -> None:
        """Finaliza como ``INCONCLUSA`` la instancia exacta identificada.

        La coincidencia del id se valida dentro del serializador, no antes. Por
        eso una orden tardía para A no puede terminar B aunque B haya ocupado
        ``votacion_activa`` mientras el comando esperaba su turno.
        """

        await self._ejecutor.ejecutar(
            lambda: self._finalizar_votacion_manualmente_bajo_lock(id_votacion, motivo)
        )

    async def desempatar_votacion(
        self,
        id_votacion: str,
        sentido: SentidoVotoDesempate,
    ) -> None:
        """Registra el voto presidencial y consolida su resultado bajo un lock.

        La Presidencia no se recibe como argumento: se consulta desde la sesión
        una vez adquirida la exclusión. Esto hace que una carrera con un cambio
        de autoridad conserve exactamente la identidad vigente en el orden real
        de ejecución.
        """

        await self._ejecutor.ejecutar(
            lambda: self._desempatar_votacion_bajo_lock(id_votacion, sentido)
        )

    async def _abrir_votacion_bajo_lock(
        self,
        datos: DatosAperturaVotacion,
    ) -> Votacion:
        """Ejecuta VALIDAR -> AUDITAR -> MUTAR con exclusión ya adquirida."""

        if self._estado.estado_global is not EstadoGlobal.SESION_ABIERTA:
            self._rechazar(
                "abrir votación",
                "ESTADO_INCOMPATIBLE",
                ErrorEstadoIncompatible(
                    "Solo puede abrirse una votación durante SESION_ABIERTA "
                    f"(estado actual: {self._estado.estado_global.value})."
                ),
            )

        sesion = self._sesion_requerida()
        if not sesion.contexto_operativo.quorum_alcanzado():
            self._rechazar(
                "abrir votación",
                "QUORUM_INSUFICIENTE",
                ErrorQuorumInsuficiente("No puede abrirse una votación sin quórum."),
            )
        if self._estado.votacion_activa is not None:
            self._rechazar(
                "abrir votación",
                "VOTACION_PENDIENTE",
                ErrorVotacionPendiente(
                    "No puede abrirse otra votación mientras exista una pendiente."
                ),
            )
        if datos.tipo not in sesion.contexto_operativo.configuracion.tipos_votacion:
            self._rechazar(
                "abrir votación",
                "TIPO_VOTACION_NO_PERMITIDO",
                ErrorTipoVotacionNoPermitido(
                    f"El tipo de votación '{datos.tipo}' no está permitido en esta sesión."
                ),
            )

        votacion = Votacion(
            id=self._generador_id(),
            numero_votacion=datos.numero_votacion,
            tipo=datos.tipo,
            tema=datos.tema,
            tipo_mayoria=datos.tipo_mayoria,
            factor=datos.factor,
            base=datos.base,
            fecha_hora_apertura=self._reloj(),
        )
        sesion.contexto_operativo.escritor_auditoria.registrar_evento(
            NivelAuditoria.L3,
            ETIQUETA_VOTACION,
            CODIGO_VOTACION_ABIERTA,
            self._mensaje_apertura(votacion),
        )

        # Ambas publicaciones ocurren únicamente después de fsync y usan la
        # misma identidad. El historial es dueño duradero dentro de la sesión;
        # ``votacion_activa`` solo señala cuál bloquea una nueva apertura.
        sesion.votaciones.append(votacion)
        self._estado.votacion_activa = votacion
        return votacion

    async def _finalizar_votacion_manualmente_bajo_lock(
        self,
        id_votacion: str,
        motivo: str,
    ) -> None:
        """Valida id/etapa, audita y recién entonces aplica la finalización."""

        if self._estado.estado_global is not EstadoGlobal.SESION_ABIERTA:
            self._rechazar(
                "finalizar votación manualmente",
                "ESTADO_INCOMPATIBLE",
                ErrorEstadoIncompatible(
                    "Solo puede finalizarse una votación durante SESION_ABIERTA "
                    f"(estado actual: {self._estado.estado_global.value})."
                ),
                id_solicitado=id_votacion,
            )

        votacion = self._estado.votacion_activa
        if votacion is None:
            self._rechazar(
                "finalizar votación manualmente",
                "VOTACION_NO_EN_CURSO",
                ErrorVotacionNoEnCurso("No existe una votación activa finalizable."),
                id_solicitado=id_votacion,
            )
        if votacion.id != id_votacion:
            self._rechazar(
                "finalizar votación manualmente",
                "VOTACION_NO_COINCIDE",
                ErrorVotacionNoCoincide("El id solicitado no corresponde a la votación activa."),
                id_solicitado=id_votacion,
            )
        if votacion.estado is not EstadoVotacion.EN_CURSO or votacion.resultado is not None:
            self._rechazar(
                "finalizar votación manualmente",
                "VOTACION_NO_EN_CURSO",
                ErrorVotacionNoEnCurso("La votación identificada no está EN_CURSO sin resultado."),
                id_solicitado=id_votacion,
            )

        sesion = self._sesion_requerida()
        finalizar_votacion_inconclusa_bajo_lock(
            estado_operativo=self._estado,
            contexto=sesion.contexto_operativo,
            votacion=votacion,
            causa=CausaFinalizacionInconclusa.MANUAL,
            fecha_hora_cierre=self._reloj(),
            reloj_resultado=self._reloj,
            motivo_manual=motivo,
        )

    async def _desempatar_votacion_bajo_lock(
        self,
        id_votacion: str,
        sentido: SentidoVotoDesempate,
    ) -> None:
        """Ejecuta los dos hechos institucionales sin abandonar la exclusión.

        El orden es deliberadamente ``VALIDAR -> AUDITAR VOTO -> ALMACENAR
        VOTO -> AUDITAR RESULTADO -> APLICAR RESULTADO -> LIBERAR``. Si falla
        el segundo evento, no se revierte el voto presidencial que ya quedó
        durable y almacenado; ese estado técnico permanece en fallo cerrado.
        """

        if self._estado.estado_global is not EstadoGlobal.SESION_ABIERTA:
            self._rechazar(
                "desempatar votación",
                "ESTADO_INCOMPATIBLE",
                ErrorEstadoIncompatible(
                    "Solo puede desempatarse una votación durante SESION_ABIERTA "
                    f"(estado actual: {self._estado.estado_global.value})."
                ),
                id_solicitado=id_votacion,
            )

        votacion = self._estado.votacion_activa
        if votacion is None:
            self._rechazar(
                "desempatar votación",
                "VOTACION_NO_EMPATADA",
                ErrorVotacionNoEmpatada("No existe una votación empatada activa."),
                id_solicitado=id_votacion,
            )
        if votacion.id != id_votacion:
            self._rechazar(
                "desempatar votación",
                "VOTACION_NO_COINCIDE",
                ErrorVotacionNoCoincide("El id solicitado no corresponde a la votación activa."),
                id_solicitado=id_votacion,
            )
        if (
            votacion.estado is not EstadoVotacion.CERRADA
            or votacion.resultado is not ResultadoVotacion.EMPATADA
            or votacion.tipo_mayoria is not TipoMayoria.SIMPLE
        ):
            self._rechazar(
                "desempatar votación",
                "VOTACION_NO_EMPATADA",
                ErrorVotacionNoEmpatada(
                    "La votación identificada no está CERRADA + EMPATADA con mayoría SIMPLE."
                ),
                id_solicitado=id_votacion,
            )
        if votacion.voto_desempate is not None:
            self._rechazar(
                "desempatar votación",
                "DESEMPATE_YA_EMITIDO",
                ErrorDesempateYaEmitido("La votación ya posee un voto presidencial."),
                id_solicitado=id_votacion,
            )

        sesion = self._sesion_requerida()
        # La identidad se captura aquí, bajo el mismo lock que los cambios de
        # autoridades. Nunca se enlaza con el padrón ni con un voto ordinario.
        voto_desempate = votacion.preparar_voto_desempate(sentido, sesion.presidencia)
        conteos = votacion.contar_votos_ordinarios()
        escritor = sesion.contexto_operativo.escritor_auditoria

        escritor.registrar_evento(
            NivelAuditoria.L3,
            ETIQUETA_VOTACION,
            CODIGO_VOTO_DESEMPATE_PRESIDENCIAL,
            self._mensaje_voto_desempate(votacion, voto_desempate, conteos),
        )

        # El voto presidencial es un dato propio: no se agrega al mapa por DNI
        # ni modifica positivos, negativos, abstenciones o denominadores.
        votacion.registrar_voto_desempate(voto_desempate)

        escritor.registrar_evento(
            NivelAuditoria.L3,
            ETIQUETA_VOTACION,
            CODIGO_VOTACION_RESULTADO_DESEMPATE,
            self._mensaje_resultado_desempate(votacion, voto_desempate, conteos),
        )

        # No se recalcula SIMPLE. El sentido ya auditado determina el resultado
        # directamente y la referencia se libera recién después de aplicarlo.
        votacion.consolidar_resultado_desempate(self._reloj())
        self._estado.votacion_activa = None

    def _rechazar(
        self,
        operacion: str,
        codigo: str,
        error: Exception,
        *,
        id_solicitado: str | None = None,
    ) -> NoReturn:
        """Persiste el rechazo L2 cuando existe auditoría activa y lo lanza.

        Si escribir el rechazo falla, la excepción de auditoría prevalece. El
        cliente recibe 503 y el estado funcional permanece intacto.
        """

        contexto = self._estado.contexto_operativo_activo()
        if contexto is not None:
            detalle_id = "" if id_solicitado is None else f"; id_solicitado={id_solicitado}"
            contexto.escritor_auditoria.registrar_evento(
                NivelAuditoria.L2,
                ETIQUETA_VOTACION,
                CODIGO_COMANDO_VOTACION_RECHAZADO,
                f"Comando de votación rechazado: operación={operacion}; "
                f"código={codigo}{detalle_id}",
            )
        raise error

    def _sesion_requerida(self) -> Sesion:
        """Devuelve la sesión o denuncia una incoherencia técnica interna."""

        sesion = self._estado.sesion_activa
        if sesion is None:
            raise RuntimeError("Estado SESION_ABIERTA sin sesión activa")
        return sesion

    @staticmethod
    def _mensaje_apertura(votacion: Votacion) -> str:
        """Construye el texto humano con todos los datos exigidos por DEC-009."""

        return (
            f"Votación abierta: número={votacion.numero_votacion}; "
            f"tipo={votacion.tipo}; tema={votacion.tema}; "
            f"tipo_mayoria={votacion.tipo_mayoria.value}; factor={votacion.factor}; "
            f"base={votacion.base.value}"
        )

    @staticmethod
    def _mensaje_voto_desempate(
        votacion: Votacion,
        voto: VotoDesempate,
        conteos: ConteosVotosOrdinarios,
    ) -> str:
        """Construye el primer hecho L3 antes de almacenar el voto."""

        return (
            "Voto presidencial de desempate: "
            f"numero_votacion={votacion.numero_votacion}; id={votacion.id}; "
            f"presidencia={voto.presidencia}; sentido={voto.sentido.value}; "
            f"estado_previo={EstadoVotacion.CERRADA.value}; "
            f"resultado_previo={ResultadoVotacion.EMPATADA.value}; "
            f"votos_ordinarios={conteos.votos_emitidos}; "
            f"positivos={conteos.positivos}; negativos={conteos.negativos}; "
            f"abstenciones={conteos.abstenciones}"
        )

    @staticmethod
    def _mensaje_resultado_desempate(
        votacion: Votacion,
        voto: VotoDesempate,
        conteos: ConteosVotosOrdinarios,
    ) -> str:
        """Construye el segundo hecho L3 desde el voto ya almacenado."""

        return (
            "Resultado por desempate presidencial: "
            f"numero_votacion={votacion.numero_votacion}; id={votacion.id}; "
            f"presidencia={voto.presidencia}; sentido={voto.sentido.value}; "
            f"resultado_previo={ResultadoVotacion.EMPATADA.value}; "
            f"resultado_final={voto.resultado_final.value}; "
            f"votos_ordinarios={conteos.votos_emitidos}; "
            f"positivos={conteos.positivos}; negativos={conteos.negativos}; "
            f"abstenciones={conteos.abstenciones}"
        )
