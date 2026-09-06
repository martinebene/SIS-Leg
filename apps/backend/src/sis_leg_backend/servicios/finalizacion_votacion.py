"""Operación interna compartida para finalizar una votación como inconclusa.

Este módulo no crea ni adquiere locks. Sus llamadores ya entraron al único
``EjecutorMutaciones`` y necesitan componer varios hechos bajo esa misma
sección crítica. Centralizar aquí el orden ``VALIDAR -> CONSTRUIR -> AUDITAR ->
MUTAR -> LIBERAR`` evita que los tres flujos de WP-013 diverjan.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sis_leg_backend.auditoria import NivelAuditoria
from sis_leg_backend.dominio.estado import EstadoOperativo
from sis_leg_backend.dominio.preparacion import Preparacion
from sis_leg_backend.dominio.votacion import (
    CausaFinalizacionInconclusa,
    EstadoVotacion,
    ResultadoVotacion,
    Votacion,
)

ETIQUETA_VOTACION = "VOTACION"
CODIGO_VOTACION_FINALIZADA_INCONCLUSA = "VOTACION_FINALIZADA_INCONCLUSA"


def finalizar_votacion_inconclusa_bajo_lock(
    *,
    estado_operativo: EstadoOperativo,
    contexto: Preparacion,
    votacion: Votacion,
    causa: CausaFinalizacionInconclusa,
    fecha_hora_cierre: datetime,
    reloj_resultado: Callable[[], datetime],
    motivo_manual: str | None = None,
) -> None:
    """Audita y aplica una finalización inconclusa con el lock ya adquirido.

    Args:
        estado_operativo: fuente global que debe señalar a ``votacion``.
        contexto: dueño del writer y del snapshot de quórum/presencia.
        votacion: la misma instancia publicada en el historial de la sesión.
        causa: una de las tres causas institucionales autorizadas por WP-013.
        fecha_hora_cierre: instante a usar solo si la recepción sigue abierta.
        reloj_resultado: reloj inyectado que se consulta después del ``fsync``
            para marcar cuándo el resultado quedó realmente publicable.
        motivo_manual: texto humano obligatorio exclusivamente para ``MANUAL``.

    Raises:
        ValueError: si causa, motivo o transición no son compatibles.
        RuntimeError: si la referencia activa no es la misma entidad.
        ErrorAuditoria: si el hecho no puede persistirse; en ese caso no se
            muta la votación ni se libera la referencia.

    El helper no llama ``EjecutorMutaciones.ejecutar``. Esto es esencial para
    que cierre de sesión, presencia y comando manual compongan sus hechos bajo
    una sola adquisición y sin riesgo de readquirir el mismo lock.
    """

    if estado_operativo.votacion_activa is not votacion:
        raise RuntimeError("La votación a finalizar no coincide con la referencia activa")

    resultado_previo = votacion.resultado
    estado_previo = votacion.estado
    motivo_normalizado: str | None = None

    if causa is CausaFinalizacionInconclusa.MANUAL:
        if motivo_manual is None:
            raise ValueError("La finalización manual exige motivo")
        motivo_normalizado = votacion.validar_finalizacion_inconclusa_manual(motivo_manual)
    elif causa is CausaFinalizacionInconclusa.PERDIDA_QUORUM:
        if motivo_manual is not None:
            raise ValueError("La pérdida de quórum no admite motivo manual")
        votacion.validar_finalizacion_inconclusa_derivada()
        if contexto.quorum_alcanzado():
            raise ValueError("No puede finalizarse por pérdida si todavía existe quórum")
    elif causa is CausaFinalizacionInconclusa.CIERRE_SESION:
        if motivo_manual is not None:
            raise ValueError("El cierre de sesión no admite motivo manual")
        if (
            votacion.estado is EstadoVotacion.CERRADA
            and votacion.resultado is ResultadoVotacion.EMPATADA
        ):
            votacion.validar_empate_inconcluso_por_cierre_sesion()
        else:
            votacion.validar_finalizacion_inconclusa_derivada()
    else:  # pragma: no cover - el enum cerrado deja esta defensa interna.
        raise ValueError("Causa de finalización inconclusa desconocida")

    # El texto completo se construye antes de escribir. Así la auditoría nunca
    # queda a mitad de una mutación ni depende de valores ya cambiados.
    mensaje = _construir_mensaje_finalizacion(
        votacion=votacion,
        causa=causa,
        estado_previo=estado_previo,
        resultado_previo=resultado_previo,
        contexto=contexto,
        motivo_manual=motivo_normalizado,
    )
    contexto.escritor_auditoria.registrar_evento(
        NivelAuditoria.L3,
        ETIQUETA_VOTACION,
        CODIGO_VOTACION_FINALIZADA_INCONCLUSA,
        mensaje,
    )
    fecha_hora_resultado = reloj_resultado()

    # Recién después del fsync se modifica la misma entidad. Si el writer falla
    # antes, ninguna de estas líneas corre y permanece el último hecho durable.
    if causa is CausaFinalizacionInconclusa.MANUAL:
        assert motivo_normalizado is not None
        votacion.finalizar_inconclusa_manual(
            fecha_hora_cierre,
            motivo_normalizado,
            fecha_hora_resultado,
        )
    elif (
        causa is CausaFinalizacionInconclusa.CIERRE_SESION
        and resultado_previo is ResultadoVotacion.EMPATADA
    ):
        # Esta es la única llamada autorizada del WP para EMPATADA ->
        # INCONCLUSA. La primitiva conserva la fecha del cierre normal.
        votacion.finalizar_empate_inconcluso_por_cierre_sesion(fecha_hora_resultado)
    else:
        votacion.finalizar_inconclusa_derivada(fecha_hora_cierre, fecha_hora_resultado)

    estado_operativo.votacion_activa = None


def _construir_mensaje_finalizacion(
    *,
    votacion: Votacion,
    causa: CausaFinalizacionInconclusa,
    estado_previo: EstadoVotacion,
    resultado_previo: ResultadoVotacion | None,
    contexto: Preparacion,
    motivo_manual: str | None,
) -> str:
    """Construye el hecho durable con datos suficientes para reconstruirlo."""

    resultado_previo_texto = "None" if resultado_previo is None else resultado_previo.value
    partes = [
        "Votación finalizada inconclusa",
        f"numero_votacion={votacion.numero_votacion}",
        f"id={votacion.id}",
        f"causa={causa.value}",
        f"estado_previo={estado_previo.value}",
        f"resultado_previo={resultado_previo_texto}",
        f"votos_conservados={len(votacion.votos_ordinarios)}",
        f"resultado_nuevo={ResultadoVotacion.INCONCLUSA.value}",
    ]
    if causa is CausaFinalizacionInconclusa.MANUAL:
        partes.append(f"motivo_manual={motivo_manual}")
    elif causa is CausaFinalizacionInconclusa.PERDIDA_QUORUM:
        partes.extend(
            (
                f"presentes={contexto.cantidad_presentes()}",
                f"quorum_requerido={contexto.configuracion.quorum}",
            )
        )
    else:
        partes.append("resuelta_por_cierre_sesion=true")
    return "; ".join(partes)
