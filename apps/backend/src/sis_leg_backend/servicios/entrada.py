"""Servicio serializado para pulsaciones lógicas durante preparación/sesión.

La ruta recibe un dispositivo lógico, nunca un fingerprint físico, y resuelve
la identidad únicamente contra el padrón congelado del contexto operativo.
WP-008 amplía la misma lógica de WP-006 a ``SESION_ABIERTA`` para teclas 8/9;
WP-010 incorpora 1/2/3, voto irreversible y autocierre; WP-011 encadena el
resultado ordinario y WP-015 agrega palabra y sus efectos de ausencia en ese
mismo flujo, sin crear otro mapa, escritor ni mecanismo de serialización.

La parte más importante del flujo es el orden: cada operación válida en
un contexto auditable registra primero la pulsación, luego el resultado
obligatorio y recién entonces muta presencia, test, voto o recepción. Todo el
método se ejecuta mediante el ``EjecutorMutaciones`` existente; el servicio no
crea otro lock.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime

from sis_leg_backend.auditoria import NivelAuditoria
from sis_leg_backend.configuracion.modelos import Concejal
from sis_leg_backend.dominio.entrada import (
    AccionPalabra,
    IdentidadConcejal,
    Pulsacion,
    RespuestaEntrada,
    ResultadoPalabra,
    ResultadoPresencia,
    ResultadoTest,
    ResultadoVoto,
)
from sis_leg_backend.dominio.estado import EstadoGlobal, EstadoOperativo
from sis_leg_backend.dominio.preparacion import Preparacion
from sis_leg_backend.dominio.votacion import (
    CalculoResultadoVotacion,
    CausaFinalizacionInconclusa,
    EstadoVotacion,
    ResultadoVotacion,
    TipoMayoria,
    ValorVotoOrdinario,
    Votacion,
    VotoOrdinario,
)
from sis_leg_backend.hechos_operativos import (
    ReferenciaHechoOperativo,
    TipoHechoOperativo,
)
from sis_leg_backend.servicios.finalizacion_votacion import (
    finalizar_votacion_inconclusa_bajo_lock,
)
from sis_leg_backend.servicios.serializacion import EjecutorMutaciones

VALOR_VOTO_POR_TECLA = {
    "1": ValorVotoOrdinario.POSITIVO,
    "2": ValorVotoOrdinario.ABSTENCION,
    "3": ValorVotoOrdinario.NEGATIVO,
}
TECLA_TEST = "8"
TECLA_PRESENCIA = "9"
TECLA_PALABRA = "7"

MOTIVO_VOTO_REGISTRADO = "VOTO_REGISTRADO"
MOTIVO_PRESENCIA_ACTUALIZADA = "PRESENCIA_ACTUALIZADA"
MOTIVO_TEST_ACTIVADO = "TEST_ACTIVADO"
MOTIVO_SIN_PREPARAR = "SIN_PREPARAR"
MOTIVO_DISPOSITIVO_NO_ASIGNADO = "DISPOSITIVO_NO_ASIGNADO"
MOTIVO_TECLA_NO_HABILITADA = "TECLA_NO_HABILITADA"
MOTIVO_VOTACION_NO_EN_CURSO = "VOTACION_NO_EN_CURSO"
MOTIVO_CONCEJAL_AUSENTE = "CONCEJAL_AUSENTE"
MOTIVO_VOTO_YA_EMITIDO = "VOTO_YA_EMITIDO"
MOTIVO_PEDIDO_PALABRA_REGISTRADO = "PEDIDO_PALABRA_REGISTRADO"
MOTIVO_PEDIDO_PALABRA_RETIRADO = "PEDIDO_PALABRA_RETIRADO"
MOTIVO_USO_PALABRA_FINALIZADO = "USO_PALABRA_FINALIZADO"

ETIQUETA_INPUT = "INPUT"
ETIQUETA_PRESENCIA = "PRESENCIA"
ETIQUETA_VOTACION = "VOTACION"
ETIQUETA_PALABRA = "PALABRA"
CODIGO_PULSACION_RECIBIDA = "PULSACION_RECIBIDA"
CODIGO_PULSACION_RECHAZADA = "PULSACION_RECHAZADA"
CODIGO_CONCEJAL_PRESENTE = "CONCEJAL_PRESENTE"
CODIGO_CONCEJAL_AUSENTE = "CONCEJAL_AUSENTE"
CODIGO_TEST_DISPOSITIVO_ACTIVADO = "TEST_DISPOSITIVO_ACTIVADO"
CODIGO_VOTO_ORDINARIO_REGISTRADO = "VOTO_ORDINARIO_REGISTRADO"
CODIGO_VOTACION_CERRADA_COMPLETITUD = "VOTACION_CERRADA_COMPLETITUD"
CODIGO_VOTACION_RESULTADO_FINAL = "VOTACION_RESULTADO_FINAL"
CODIGO_VOTACION_RESULTADO_EMPATE = "VOTACION_RESULTADO_EMPATE"
CODIGO_PEDIDO_PALABRA_REGISTRADO = "PEDIDO_PALABRA_REGISTRADO"
CODIGO_PEDIDO_PALABRA_RETIRADO = "PEDIDO_PALABRA_RETIRADO"
CODIGO_USO_PALABRA_FINALIZADO = "USO_PALABRA_FINALIZADO"

CAUSA_FINALIZACION_PROPIO = "PROPIO"

# Texto con el que se reemplaza la tecla 1/2/3 en la proyección de eventos
# mientras el sentido individual del voto todavía es secreto. El CSV durable
# sigue registrando la tecla real: acá solo se protege lo que ve Moderación.
TECLA_OCULTA = "oculta"


class ServicioEntradaTecla:
    """Procesa pulsaciones lógicas sobre el estado operativo único.

    El servicio no conserva estado funcional propio. Recibe por constructor el
    ``EstadoOperativo`` y el ``EjecutorMutaciones`` compartidos, igual que el
    servicio de preparación. Los relojes son dependencias inyectables para
    probar expiraciones de test y fecha de autocierre de forma determinista; en
    producción se usan ``time.monotonic`` y ``datetime.now``.
    """

    def __init__(
        self,
        estado_operativo: EstadoOperativo,
        ejecutor_mutaciones: EjecutorMutaciones,
        *,
        reloj_monotono: Callable[[], float] = time.monotonic,
        reloj: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._estado = estado_operativo
        self._ejecutor = ejecutor_mutaciones
        self._reloj_monotono = reloj_monotono
        self._reloj = reloj

    async def procesar_pulsacion(self, pulsacion: Pulsacion) -> RespuestaEntrada:
        """Procesa una pulsación en el mismo serializador que el resto del backend.

        Incluso la respuesta sin efecto de ``SIN_PREPARAR`` pasa por el ejecutor:
        así una preparación concurrente no puede quedar intercalada a mitad de
        la decisión. El método bajo lock tampoco espera tareas externas, por lo
        que el orden de adquisición del lock es el orden oficial de entradas y
        de sus secuencias de auditoría.

        Raises:
            ErrorAuditoria: si algún evento obligatorio no puede persistirse. La
                excepción conserva el fallo cerrado del writer y la API la
                traduce a ``503 AUDITORIA_NO_DISPONIBLE``.
            RuntimeError: si se rompe la invariante interna de ``PREPARANDO``.
        """

        return await self._ejecutor.ejecutar(lambda: self._procesar_pulsacion_bajo_lock(pulsacion))

    async def _procesar_pulsacion_bajo_lock(self, pulsacion: Pulsacion) -> RespuestaEntrada:
        """Ejecuta la decisión completa con la exclusión ya tomada."""

        if self._estado.estado_global is EstadoGlobal.SIN_PREPARAR:
            # No existe preparación ni writer en este estado. Por contrato, una
            # pulsación válida se rechaza normalmente sin crear ni buscar CSV.
            return RespuestaEntrada(
                aceptada=False,
                dispositivo=pulsacion.dispositivo,
                tecla=pulsacion.tecla,
                motivo=MOTIVO_SIN_PREPARAR,
                concejal=None,
                resultado=None,
            )

        if self._estado.estado_global not in (
            EstadoGlobal.PREPARANDO,
            EstadoGlobal.SESION_ABIERTA,
        ):
            raise RuntimeError("Estado global desconocido para la entrada lógica")

        preparacion = self._estado.contexto_operativo_activo()
        if preparacion is None:
            raise RuntimeError("Estado auditable sin contexto operativo activo")

        # Toda pulsación de transporte válida durante preparación o sesión queda
        # registrada antes de consultar el padrón o decidir si la tecla sirve.
        self._registrar_pulsacion_recibida(preparacion, pulsacion)

        concejal = self._buscar_concejal(preparacion, pulsacion.dispositivo)
        if concejal is None:
            self._registrar_pulsacion_rechazada(
                preparacion, pulsacion, MOTIVO_DISPOSITIVO_NO_ASIGNADO
            )
            return self._respuesta_rechazo(pulsacion, MOTIVO_DISPOSITIVO_NO_ASIGNADO, concejal=None)

        identidad = self._crear_identidad(concejal)
        if pulsacion.tecla in VALOR_VOTO_POR_TECLA:
            if self._estado.estado_global is not EstadoGlobal.SESION_ABIERTA:
                self._registrar_pulsacion_rechazada(
                    preparacion, pulsacion, MOTIVO_TECLA_NO_HABILITADA
                )
                return self._respuesta_rechazo(
                    pulsacion,
                    MOTIVO_TECLA_NO_HABILITADA,
                    concejal=identidad,
                )
            return self._procesar_voto(
                preparacion,
                pulsacion,
                concejal.dni,
                identidad,
                VALOR_VOTO_POR_TECLA[pulsacion.tecla],
            )

        if pulsacion.tecla == TECLA_PALABRA:
            if self._estado.estado_global is not EstadoGlobal.SESION_ABIERTA:
                self._registrar_pulsacion_rechazada(
                    preparacion, pulsacion, MOTIVO_TECLA_NO_HABILITADA
                )
                return self._respuesta_rechazo(
                    pulsacion,
                    MOTIVO_TECLA_NO_HABILITADA,
                    concejal=identidad,
                )
            return self._procesar_palabra(
                preparacion,
                pulsacion,
                concejal,
                identidad,
            )

        if pulsacion.tecla not in (TECLA_TEST, TECLA_PRESENCIA):
            self._registrar_pulsacion_rechazada(preparacion, pulsacion, MOTIVO_TECLA_NO_HABILITADA)
            return self._respuesta_rechazo(
                pulsacion, MOTIVO_TECLA_NO_HABILITADA, concejal=identidad
            )

        if pulsacion.tecla == TECLA_PRESENCIA:
            return self._procesar_presencia(preparacion, pulsacion, concejal.dni, identidad)

        return self._procesar_test(preparacion, pulsacion, concejal.dni, identidad)

    def _procesar_presencia(
        self,
        preparacion: Preparacion,
        pulsacion: Pulsacion,
        dni: str,
        identidad: IdentidadConcejal,
    ) -> RespuestaEntrada:
        """Audita y alterna presencia, derivando presentes y quórum al final."""

        nuevo_valor = not preparacion.presencias[dni]
        codigo_evento = CODIGO_CONCEJAL_PRESENTE if nuevo_valor else CODIGO_CONCEJAL_AUSENTE
        pedido_palabra_retirado = False
        uso_palabra_finalizado = False
        incluir_efectos_palabra = False
        if not nuevo_valor:
            sesion = self._estado.sesion_activa
            if self._estado.estado_global is EstadoGlobal.SESION_ABIERTA and sesion is not None:
                incluir_efectos_palabra = True
                pedido_palabra_retirado = sesion.palabra.esta_esperando(dni)
                uso_palabra_finalizado = sesion.palabra.es_orador(dni)
        mensaje = self._mensaje_presencia(
            identidad,
            nuevo_valor,
            incluir_efectos_palabra=incluir_efectos_palabra,
            pedido_palabra_retirado=pedido_palabra_retirado,
            uso_palabra_finalizado=uso_palabra_finalizado,
        )

        # Si esta escritura falla, el writer queda en fallo cerrado y la
        # asignación siguiente no se ejecuta. La presencia anterior permanece.
        preparacion.escritor_auditoria.registrar_evento(
            NivelAuditoria.L3,
            ETIQUETA_PRESENCIA,
            codigo_evento,
            mensaje,
        )

        # La mutación funcional es deliberadamente posterior a ambos eventos
        # obligatorios: PULSACION_RECIBIDA (ya escrita por el llamador) y el
        # evento institucional de presencia que acabamos de persistir.
        preparacion.presencias[dni] = nuevo_valor
        if not nuevo_valor:
            sesion = self._estado.sesion_activa
            if self._estado.estado_global is EstadoGlobal.SESION_ABIERTA and sesion is not None:
                # El mismo evento CONCEJAL_AUSENTE ya documentó y autorizó
                # estos efectos. No se crea un segundo hecho de palabra para la
                # consecuencia automática y nunca se promueve al siguiente.
                sesion.palabra.limpiar_por_ausencia(dni)

        # La presencia ya es un hecho auditado y aplicado. La operación derivada
        # evalúa primero quórum y recién luego completitud. Si su evento falla,
        # no se revierte retrospectivamente esta presencia confirmada.
        self._resolver_votacion_tras_presencia(preparacion)
        return RespuestaEntrada(
            aceptada=True,
            dispositivo=pulsacion.dispositivo,
            tecla=pulsacion.tecla,
            motivo=MOTIVO_PRESENCIA_ACTUALIZADA,
            concejal=identidad,
            resultado=ResultadoPresencia(
                tipo="PRESENCIA",
                presente=nuevo_valor,
                presentes=preparacion.cantidad_presentes(),
                quorum_alcanzado=preparacion.quorum_alcanzado(),
            ),
        )

    def _procesar_palabra(
        self,
        preparacion: Preparacion,
        pulsacion: Pulsacion,
        concejal: Concejal,
        identidad: IdentidadConcejal,
    ) -> RespuestaEntrada:
        """Resuelve tecla 7 con la prioridad aprobada y auditoría previa.

        La votación activa no interviene en esta decisión. La presencia se
        valida primero; luego se prioriza finalizar el uso propio, retirar un
        pedido existente y, por último, agregar un nuevo pedido al final FIFO.
        """

        if not preparacion.presencias[concejal.dni]:
            self._registrar_pulsacion_rechazada(
                preparacion,
                pulsacion,
                MOTIVO_CONCEJAL_AUSENTE,
            )
            return self._respuesta_rechazo(
                pulsacion,
                MOTIVO_CONCEJAL_AUSENTE,
                concejal=identidad,
            )

        sesion = self._estado.sesion_activa
        if sesion is None:
            raise RuntimeError("Estado SESION_ABIERTA sin sesión para palabra")
        estado_palabra = sesion.palabra
        identidad_mensaje = self._mensaje_identidad(identidad)

        if estado_palabra.es_orador(concejal.dni):
            preparacion.escritor_auditoria.registrar_evento(
                NivelAuditoria.L3,
                ETIQUETA_PALABRA,
                CODIGO_USO_PALABRA_FINALIZADO,
                (
                    f"Uso de palabra finalizado: {identidad_mensaje}; "
                    f"causa={CAUSA_FINALIZACION_PROPIO}"
                ),
            )
            estado_palabra.finalizar_uso(concejal.dni)
            return self._respuesta_palabra(
                pulsacion,
                identidad,
                MOTIVO_USO_PALABRA_FINALIZADO,
                AccionPalabra.USO_FINALIZADO,
            )

        if estado_palabra.esta_esperando(concejal.dni):
            posicion = estado_palabra.cola_dnis.index(concejal.dni) + 1
            preparacion.escritor_auditoria.registrar_evento(
                NivelAuditoria.L3,
                ETIQUETA_PALABRA,
                CODIGO_PEDIDO_PALABRA_RETIRADO,
                f"Pedido de palabra retirado: {identidad_mensaje}; posicion_previa={posicion}",
                referencia=ReferenciaHechoOperativo(
                    tipo=TipoHechoOperativo.RETIRO_PALABRA,
                    dni=concejal.dni,
                ),
            )
            estado_palabra.retirar_pedido(concejal.dni)
            return self._respuesta_palabra(
                pulsacion,
                identidad,
                MOTIVO_PEDIDO_PALABRA_RETIRADO,
                AccionPalabra.PEDIDO_RETIRADO,
            )

        posicion = len(estado_palabra.cola_dnis) + 1
        preparacion.escritor_auditoria.registrar_evento(
            NivelAuditoria.L3,
            ETIQUETA_PALABRA,
            CODIGO_PEDIDO_PALABRA_REGISTRADO,
            f"Pedido de palabra registrado: {identidad_mensaje}; posicion={posicion}",
            referencia=ReferenciaHechoOperativo(
                tipo=TipoHechoOperativo.PEDIDO_PALABRA,
                dni=concejal.dni,
            ),
        )
        estado_palabra.agregar_pedido(concejal.dni)
        return self._respuesta_palabra(
            pulsacion,
            identidad,
            MOTIVO_PEDIDO_PALABRA_REGISTRADO,
            AccionPalabra.PEDIDO_AGREGADO,
        )

    def _procesar_voto(
        self,
        preparacion: Preparacion,
        pulsacion: Pulsacion,
        dni: str,
        identidad: IdentidadConcejal,
        valor: ValorVotoOrdinario,
    ) -> RespuestaEntrada:
        """Valida, audita e incorpora el único voto ordinario de un concejal.

        La identidad y presencia provienen del snapshot operativo, nunca del
        cliente. Cada rechazo conserva HTTP 200 funcional y se registra como
        ``PULSACION_RECHAZADA`` L2. Un voto aceptado se persiste L3 antes de
        entrar al mapa irreversible de la misma instancia ``Votacion``.
        """

        votacion = self._estado.votacion_activa
        if votacion is None or votacion.estado is not EstadoVotacion.EN_CURSO:
            self._registrar_pulsacion_rechazada(preparacion, pulsacion, MOTIVO_VOTACION_NO_EN_CURSO)
            return self._respuesta_rechazo(
                pulsacion,
                MOTIVO_VOTACION_NO_EN_CURSO,
                concejal=identidad,
            )
        if not preparacion.presencias[dni]:
            self._registrar_pulsacion_rechazada(preparacion, pulsacion, MOTIVO_CONCEJAL_AUSENTE)
            return self._respuesta_rechazo(
                pulsacion,
                MOTIVO_CONCEJAL_AUSENTE,
                concejal=identidad,
            )
        if votacion.ya_emitio_voto(dni):
            self._registrar_pulsacion_rechazada(preparacion, pulsacion, MOTIVO_VOTO_YA_EMITIDO)
            return self._respuesta_rechazo(
                pulsacion,
                MOTIVO_VOTO_YA_EMITIDO,
                concejal=identidad,
            )

        voto = VotoOrdinario(dni=dni, valor=valor)
        # El CSV recibe el mensaje completo con el sentido: es el hecho durable
        # y no se reescribe nunca. La referencia adjunta viaja solo en memoria y
        # le da a la proyección de Moderación una redacción alternativa sin
        # sentido, más los datos estructurados para enriquecer el mismo ``seq``
        # cuando la frontera autoritativa de esta votación habilite el revelado.
        preparacion.escritor_auditoria.registrar_evento(
            NivelAuditoria.L3,
            ETIQUETA_VOTACION,
            CODIGO_VOTO_ORDINARIO_REGISTRADO,
            self._mensaje_voto(votacion, identidad, valor),
            referencia=ReferenciaHechoOperativo(
                tipo=TipoHechoOperativo.VOTO_ORDINARIO,
                dni=dni,
                votacion_id=votacion.id,
                mensaje_seguro=self._mensaje_voto_sin_sentido(votacion, identidad),
            ),
        )

        # El voto se incorpora únicamente después del fsync de su evento. Si el
        # autocierre derivado falla después, este hecho ya confirmado permanece.
        votacion.registrar_voto(voto)
        self._autocerrar_si_corresponde(preparacion)
        return RespuestaEntrada(
            aceptada=True,
            dispositivo=pulsacion.dispositivo,
            tecla=pulsacion.tecla,
            motivo=MOTIVO_VOTO_REGISTRADO,
            concejal=identidad,
            resultado=ResultadoVoto(
                tipo="VOTO",
                valor=valor,
                estado_recepcion=votacion.estado,
            ),
        )

    def _autocerrar_si_corresponde(self, preparacion: Preparacion) -> None:
        """Cierra y resuelve por completitud con recepción abierta y quórum.

        La completitud se deriva de la presencia actual: cada DNI presente debe
        existir en el mapa de votos. No se congela una lista al abrir y los
        votos de quienes se retiraron permanecen. Cierre, cálculo, auditoría de
        resultado, aplicación y liberación/retención ocurren dentro de esta
        misma llamada, que ya posee la única sección crítica del backend.
        """

        if self._estado.estado_global is not EstadoGlobal.SESION_ABIERTA:
            return
        votacion = self._estado.votacion_activa
        if votacion is None or votacion.estado is not EstadoVotacion.EN_CURSO:
            return
        if not preparacion.quorum_alcanzado():
            # Los votos llaman también este helper. En el flujo de presencia,
            # la pérdida ya se resolvió antes; esta defensa impide que una etapa
            # técnica sin quórum sea confundida con completitud normal.
            return

        dnis_presentes = {dni for dni, presente in preparacion.presencias.items() if presente}
        if not dnis_presentes.issubset(votacion.votos_ordinarios):
            return

        fecha_hora_cierre = self._reloj()
        preparacion.escritor_auditoria.registrar_evento(
            NivelAuditoria.L3,
            ETIQUETA_VOTACION,
            CODIGO_VOTACION_CERRADA_COMPLETITUD,
            (
                f"Votación cerrada: número={votacion.numero_votacion}; id={votacion.id}; "
                "motivo=COMPLETITUD; todos_los_presentes_votaron=true; "
                "quorum_alcanzado=true"
            ),
        )
        votacion.cerrar_recepcion(fecha_hora_cierre)

        # El cierre ya es un hecho persistido y aplicado. El resultado es otro
        # hecho institucional: se calcula sin mutar, se persiste y solo entonces
        # se aplica. Si esa segunda escritura falla, no se revierte el cierre y
        # la referencia activa continúa apuntando a CERRADA + resultado=None.
        self._calcular_auditar_y_aplicar_resultado(preparacion, votacion)

    def _resolver_votacion_tras_presencia(self, preparacion: Preparacion) -> None:
        """Prioriza pérdida de quórum y solo después evalúa completitud.

        La retirada de una persona puede hacer verdaderas ambas condiciones a
        la vez: dejar sin quórum y dejar a todos los restantes con voto. DEC-011
        ordena que el primer hecho domine, por lo que no se llama al cálculo
        ordinario si el nuevo mapa de presencia ya quedó bajo el umbral.
        """

        if self._estado.estado_global is not EstadoGlobal.SESION_ABIERTA:
            return
        votacion = self._estado.votacion_activa
        if (
            votacion is None
            or votacion.estado is not EstadoVotacion.EN_CURSO
            or votacion.resultado is not None
        ):
            # Una EMPATADA está CERRADA y permanece pendiente aunque cambie el
            # quórum. Solo el cierre explícito de sesión puede transformarla.
            return

        if not preparacion.quorum_alcanzado():
            finalizar_votacion_inconclusa_bajo_lock(
                estado_operativo=self._estado,
                contexto=preparacion,
                votacion=votacion,
                causa=CausaFinalizacionInconclusa.PERDIDA_QUORUM,
                fecha_hora_cierre=self._reloj(),
                reloj_resultado=self._reloj,
            )
            return

        self._autocerrar_si_corresponde(preparacion)

    def _calcular_auditar_y_aplicar_resultado(
        self,
        preparacion: Preparacion,
        votacion: Votacion,
    ) -> None:
        """Completa el resultado sin abandonar la adquisición del serializador.

        El padrón ya está congelado en ``preparacion`` y aporta únicamente el
        denominador CUERPO. Todos los demás conteos se derivan de los votos de
        la propia entidad. No hay ``await`` ni readquisición del ejecutor entre
        el cierre y la publicación final.
        """

        if self._estado.votacion_activa is not votacion:
            raise RuntimeError("La votación cerrada no coincide con la referencia activa")

        calculo = votacion.calcular_resultado_ordinario(
            cantidad_total_cuerpo=len(preparacion.padron.concejales)
        )
        codigo_evento = (
            CODIGO_VOTACION_RESULTADO_EMPATE
            if calculo.resultado is ResultadoVotacion.EMPATADA
            else CODIGO_VOTACION_RESULTADO_FINAL
        )
        preparacion.escritor_auditoria.registrar_evento(
            NivelAuditoria.L3,
            ETIQUETA_VOTACION,
            codigo_evento,
            self._mensaje_resultado(votacion, calculo),
        )

        # La marca se toma después de persistir el hecho de resultado. Es
        # metadata volátil de presentación, no una nueva fila institucional.
        votacion.aplicar_resultado_ordinario(calculo.resultado, self._reloj())
        if calculo.resultado in (
            ResultadoVotacion.APROBADA,
            ResultadoVotacion.RECHAZADA,
        ):
            self._estado.votacion_activa = None

    @staticmethod
    def _mensaje_resultado(
        votacion: Votacion,
        calculo: CalculoResultadoVotacion,
    ) -> str:
        """Explica con datos humanos cómo se obtuvo el resultado institucional."""

        conteos = calculo.conteos
        comun = (
            f"Resultado ordinario: número={votacion.numero_votacion}; id={votacion.id}; "
            f"tipo_mayoria={votacion.tipo_mayoria.value}; positivos={conteos.positivos}; "
            f"negativos={conteos.negativos}; abstenciones={conteos.abstenciones}; "
        )
        if votacion.tipo_mayoria is TipoMayoria.SIMPLE:
            return (
                f"{comun}comparación=positivos_vs_negativos; "
                "abstenciones_excluidas=true; "
                f"resultado={calculo.resultado.value}"
            )

        detalle_cociente = (
            "cociente=no_calculado; caso_sin_division=true"
            if calculo.cociente is None
            else f"cociente={calculo.cociente}; caso_sin_division=false"
        )
        return (
            f"{comun}base={votacion.base.value}; denominador={calculo.denominador}; "
            f"factor={votacion.factor}; {detalle_cociente}; "
            f"resultado={calculo.resultado.value}"
        )

    def _procesar_test(
        self,
        preparacion: Preparacion,
        pulsacion: Pulsacion,
        dni: str,
        identidad: IdentidadConcejal,
    ) -> RespuestaEntrada:
        """Audita y activa/renueva el test sin modificar presencia ni quórum."""

        mensaje = (
            f"Test de dispositivo activado: {identidad.nombre} {identidad.apellido} "
            f"(banca Nro:{identidad.banca}); dispositivo=[{pulsacion.dispositivo}]"
        )
        preparacion.escritor_auditoria.registrar_evento(
            NivelAuditoria.L2,
            ETIQUETA_INPUT,
            CODIGO_TEST_DISPOSITIVO_ACTIVADO,
            mensaje,
        )

        # El reloj se consulta después de persistir el evento: la ventana
        # completa empieza cuando la activación queda confirmada, no antes.
        preparacion.activar_test_dispositivo(dni, self._reloj_monotono())
        return RespuestaEntrada(
            aceptada=True,
            dispositivo=pulsacion.dispositivo,
            tecla=pulsacion.tecla,
            motivo=MOTIVO_TEST_ACTIVADO,
            concejal=identidad,
            resultado=ResultadoTest(
                tipo="TEST",
                activo=True,
                duracion_segundos=preparacion.configuracion.device_test_seconds,
            ),
        )

    @staticmethod
    def _buscar_concejal(preparacion: Preparacion, dispositivo: str) -> Concejal | None:
        """Busca el dispositivo lógico en el padrón congelado, sin cachearlo."""

        return next(
            (
                concejal
                for concejal in preparacion.padron.concejales
                if concejal.dispositivo_votacion == dispositivo
            ),
            None,
        )

    @staticmethod
    def _crear_identidad(concejal: Concejal) -> IdentidadConcejal:
        """Limita la identidad de respuesta al DTO aprobado por DEC-006."""

        return IdentidadConcejal(
            dni=concejal.dni,
            nombre=concejal.nombre,
            apellido=concejal.apellido,
            banca=concejal.banca,
        )

    def _registrar_pulsacion_recibida(self, preparacion: Preparacion, pulsacion: Pulsacion) -> None:
        """Persiste el evento de entrada antes de cualquier resolución funcional."""

        preparacion.escritor_auditoria.registrar_evento(
            NivelAuditoria.L2,
            ETIQUETA_INPUT,
            CODIGO_PULSACION_RECIBIDA,
            self._mensaje_pulsacion_recibida(pulsacion, pulsacion.tecla),
            referencia=self._referencia_pulsacion_de_voto(
                pulsacion,
                self._mensaje_pulsacion_recibida(pulsacion, TECLA_OCULTA),
            ),
        )

    def _registrar_pulsacion_rechazada(
        self, preparacion: Preparacion, pulsacion: Pulsacion, motivo: str
    ) -> None:
        """Persiste el motivo estable de un rechazo funcional normal."""

        preparacion.escritor_auditoria.registrar_evento(
            NivelAuditoria.L2,
            ETIQUETA_INPUT,
            CODIGO_PULSACION_RECHAZADA,
            self._mensaje_pulsacion_rechazada(pulsacion, pulsacion.tecla, motivo),
            referencia=self._referencia_pulsacion_de_voto(
                pulsacion,
                self._mensaje_pulsacion_rechazada(pulsacion, TECLA_OCULTA, motivo),
            ),
        )

    @staticmethod
    def _mensaje_pulsacion_recibida(pulsacion: Pulsacion, tecla: str) -> str:
        """Redacta el evento de entrada con la tecla real o con su reemplazo.

        Recibir la tecla como parámetro permite construir con una única
        redacción tanto la fila durable como la variante segura que ve
        Moderación mientras el sentido del voto es secreto.
        """

        return f"Pulsación recibida: tecla [{tecla}] del dispositivo [{pulsacion.dispositivo}]"

    @staticmethod
    def _mensaje_pulsacion_rechazada(pulsacion: Pulsacion, tecla: str, motivo: str) -> str:
        """Redacta el rechazo con la tecla real o con su reemplazo seguro."""

        return (
            f"Pulsación rechazada: tecla [{tecla}] del dispositivo "
            f"[{pulsacion.dispositivo}]; motivo={motivo}"
        )

    def _referencia_pulsacion_de_voto(
        self,
        pulsacion: Pulsacion,
        mensaje_seguro: str,
    ) -> ReferenciaHechoOperativo | None:
        """Marca como sensible una pulsación 1/2/3 hecha con recepción abierta.

        La tecla física y el dispositivo bastan para deducir el sentido del voto
        de una banca concreta: ``1`` es POSITIVO, ``2`` ABSTENCIÓN y ``3``
        NEGATIVO, y el dispositivo lógico ya identifica al concejal en la propia
        pantalla de Moderación. Por eso el mismo secreto que protege al evento
        L3 del voto debe proteger también a estos eventos L2 de entrada.

        La decisión se toma en el momento del registro, que es cuando se conoce
        la recepción vigente. La votación referida queda anotada para que el
        revelado posterior use su frontera y no la de otra votación.

        Returns:
            La referencia que habilita el texto seguro, o ``None`` cuando la
            pulsación no puede revelar ningún sentido: teclas no vinculadas al
            voto o ausencia de una recepción abierta.
        """

        if pulsacion.tecla not in VALOR_VOTO_POR_TECLA:
            return None
        votacion = self._estado.votacion_activa
        if votacion is None or votacion.estado is not EstadoVotacion.EN_CURSO:
            return None
        return ReferenciaHechoOperativo(
            tipo=TipoHechoOperativo.PULSACION_DE_VOTO,
            votacion_id=votacion.id,
            mensaje_seguro=mensaje_seguro,
        )

    @staticmethod
    def _respuesta_rechazo(
        pulsacion: Pulsacion,
        motivo: str,
        *,
        concejal: IdentidadConcejal | None,
    ) -> RespuestaEntrada:
        """Construye el formato común de los rechazos normales con HTTP 200."""

        return RespuestaEntrada(
            aceptada=False,
            dispositivo=pulsacion.dispositivo,
            tecla=pulsacion.tecla,
            motivo=motivo,
            concejal=concejal,
            resultado=None,
        )

    @staticmethod
    def _respuesta_palabra(
        pulsacion: Pulsacion,
        identidad: IdentidadConcejal,
        motivo: str,
        accion: AccionPalabra,
    ) -> RespuestaEntrada:
        """Construye la variante funcional estable de una tecla 7 aceptada."""

        return RespuestaEntrada(
            aceptada=True,
            dispositivo=pulsacion.dispositivo,
            tecla=pulsacion.tecla,
            motivo=motivo,
            concejal=identidad,
            resultado=ResultadoPalabra(tipo="PALABRA", accion=accion),
        )

    @staticmethod
    def _mensaje_presencia(
        identidad: IdentidadConcejal,
        presente: bool,
        *,
        incluir_efectos_palabra: bool = False,
        pedido_palabra_retirado: bool = False,
        uso_palabra_finalizado: bool = False,
    ) -> str:
        """Describe presencia e incluye los efectos de palabra de una ausencia."""

        estado = "PRESENTÓ" if presente else "AUSENTÓ"
        mensaje = (
            f"{identidad.nombre} {identidad.apellido} (banca Nro:{identidad.banca}) se {estado}"
        )
        if presente or not incluir_efectos_palabra:
            return mensaje
        return (
            f"{mensaje}; pedido_palabra_retirado="
            f"{str(pedido_palabra_retirado).lower()}; uso_palabra_finalizado="
            f"{str(uso_palabra_finalizado).lower()}"
        )

    @staticmethod
    def _mensaje_identidad(identidad: IdentidadConcejal) -> str:
        """Representa DNI, nombre y banca en los hechos directos de palabra."""

        return (
            f"DNI={identidad.dni}; concejal={identidad.nombre} {identidad.apellido}; "
            f"banca={identidad.banca}"
        )

    @staticmethod
    def _mensaje_voto(
        votacion: Votacion,
        identidad: IdentidadConcejal,
        valor: ValorVotoOrdinario,
    ) -> str:
        """Describe el voto con identidad, banca, valor y votación asociada."""

        return (
            f"Voto ordinario: {identidad.nombre} {identidad.apellido} "
            f"(banca Nro:{identidad.banca}) votó {valor.value}; "
            f"votación número={votacion.numero_votacion}; id={votacion.id}"
        )

    @staticmethod
    def _mensaje_voto_sin_sentido(votacion: Votacion, identidad: IdentidadConcejal) -> str:
        """Redacta el mismo hecho conservando identidad pero ocultando el sentido.

        Es la variante que Moderación puede leer mientras el secreto sigue
        vigente. Conserva deliberadamente concejal, banca y votación, porque el
        WP autoriza mostrar quién ya emitió su voto; lo único que desaparece es
        POSITIVO/NEGATIVO/ABSTENCION.
        """

        return (
            f"Voto ordinario: {identidad.nombre} {identidad.apellido} "
            f"(banca Nro:{identidad.banca}) emitió su voto; "
            f"votación número={votacion.numero_votacion}; id={votacion.id}"
        )
