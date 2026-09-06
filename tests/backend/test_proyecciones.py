"""Pruebas deterministas de DTOs, secreto, capacidades y temporizadores."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from sis_leg_backend.auditoria import NivelAuditoria
from sis_leg_backend.dominio.estado import EstadoGlobal
from sis_leg_backend.dominio.remapeo import EstadoRemapeo, OperacionRemapeo
from sis_leg_backend.dominio.votacion import (
    EstadoVotacion,
    ResultadoVotacion,
    SentidoVotoDesempate,
    ValorVotoOrdinario,
    VotoOrdinario,
)

from tests.backend.ayudas_proyecciones import (
    abrir_sesion_prueba,
    abrir_votacion_prueba,
    crear_entorno_proyecciones,
)

pytestmark = pytest.mark.anyio


async def test_snapshots_sin_preparar_son_completos_y_sin_contexto(tmp_path: Path) -> None:
    """Ambos consumidores reciben 200-modelable aun sin preparación activa."""

    entorno = crear_entorno_proyecciones(tmp_path)
    entorno.estado.preparacion_activa = None
    entorno.estado.estado_global = EstadoGlobal.SIN_PREPARAR

    moderacion = await entorno.servicio.obtener_estado_moderacion()
    recinto = await entorno.servicio.obtener_estado_recinto()

    assert moderacion.estado_global is EstadoGlobal.SIN_PREPARAR
    assert moderacion.preparacion is None
    assert moderacion.concejales == ()
    assert moderacion.capacidades.preparar_sala.habilitada
    assert recinto.estado_global is EstadoGlobal.SIN_PREPARAR
    assert recinto.filas_bancas is None
    assert recinto.model_dump().keys() == {
        "revision",
        "generado_en",
        "estado_global",
        "preparacion",
        "sesion",
        "filas_bancas",
        "concejales",
        "quorum",
        "votacion",
        "palabra",
        "eventos_publicos",
        # WP-055 agrega la porción técnica del Recinto: transmisión más el
        # aviso de SU destino. Sigue sin existir ninguna clave privada de
        # Moderación en la allowlist pública.
        "tecnico",
        # WP-065 agrega la configuración de audio, que viaja también en
        # SIN_PREPARAR porque la pantalla suena fuera de una sesión.
        "sonidos",
    }


async def test_preparacion_proyecta_presencia_test_autoridades_y_quorum(tmp_path: Path) -> None:
    """PREPARANDO conserva datos parciales y un deadline absoluto de test."""

    entorno = crear_entorno_proyecciones(tmp_path)
    entorno.contexto.numero_sesion = 17
    entorno.contexto.presidencia = "Presidencia"
    primer_dni = entorno.contexto.padron.concejales[0].dni
    entorno.contexto.presencias[primer_dni] = True
    entorno.contexto.activar_test_dispositivo(primer_dni, entorno.reloj.monotono())

    estado = await entorno.servicio.obtener_estado_moderacion()

    assert estado.preparacion is not None
    assert estado.preparacion.secretaria_legislativa is None
    assert estado.concejales[0].presente
    assert estado.concejales[0].test_activo
    assert estado.concejales[0].test_expira_en == estado.generado_en + timedelta(seconds=0.6)
    assert estado.quorum is not None and not estado.quorum.alcanzado
    assert estado.capacidades.abrir_sesion.motivos == (
        "QUORUM_INSUFICIENTE",
        "SECRETARIA_LEGISLATIVA_REQUERIDA",
    )


@pytest.mark.parametrize("filas_bancas", ((5, 7), (3, 4, 5)))
async def test_recinto_preserva_filas_de_distinta_longitud_en_preparacion_y_sesion(
    tmp_path: Path,
    filas_bancas: tuple[int, ...],
) -> None:
    """DP-025-01 copia cada fila física sin fabricar columnas globales."""

    entorno = crear_entorno_proyecciones(tmp_path, filas_bancas=filas_bancas)

    preparando = await entorno.servicio.obtener_estado_recinto()
    assert preparando.filas_bancas == filas_bancas

    abrir_sesion_prueba(entorno)
    sesion = await entorno.servicio.obtener_estado_recinto()
    assert sesion.filas_bancas == filas_bancas


async def test_sesion_proyecta_palabra_y_orden_del_dia_solo_a_moderacion(
    tmp_path: Path,
) -> None:
    """La sesión copia cola/orador y omite asistencia institucional pública."""

    entorno = crear_entorno_proyecciones(tmp_path)
    sesion = abrir_sesion_prueba(entorno)
    primer_dni = entorno.contexto.padron.concejales[0].dni
    segundo_dni = entorno.contexto.padron.concejales[1].dni
    sesion.palabra.agregar_pedido(primer_dni)
    sesion.palabra.otorgar_primer_pedido(primer_dni)
    sesion.palabra.agregar_pedido(segundo_dni)

    moderacion = await entorno.servicio.obtener_estado_moderacion()
    recinto = await entorno.servicio.obtener_estado_recinto()

    assert moderacion.sesion is not None and moderacion.sesion.numero_sesion == 17
    assert moderacion.palabra is not None
    assert moderacion.palabra.orador is not None
    assert moderacion.palabra.orador.dni == primer_dni
    assert [persona.dni for persona in moderacion.palabra.cola] == [segundo_dni]
    assert recinto.palabra is not None and recinto.palabra.orador is not None
    assert "dni" not in recinto.palabra.orador.model_dump()
    assert "orden_del_dia" not in recinto.model_dump()


async def test_moderacion_oculta_valores_hasta_deadline_global_y_luego_revela(
    tmp_path: Path,
) -> None:
    """El plazo nace al abrir y un voto posterior no recibe demora individual."""

    entorno = crear_entorno_proyecciones(tmp_path, revelado_moderacion=4)
    votacion = abrir_votacion_prueba(entorno)
    primer_dni, segundo_dni = (concejal.dni for concejal in entorno.contexto.padron.concejales[:2])
    votacion.registrar_voto(VotoOrdinario(primer_dni, ValorVotoOrdinario.POSITIVO))

    antes = await entorno.servicio.obtener_estado_moderacion()
    assert antes.votacion is not None
    assert antes.votacion.cantidad_votos_recibidos == 1
    assert antes.votacion.votos_individuales is None
    deadline_original = antes.votacion.revelado_individual_desde

    entorno.reloj.avanzar(4)
    despues = await entorno.servicio.obtener_estado_moderacion()
    assert despues.votacion is not None
    assert despues.votacion.revelado_individual_desde == deadline_original
    assert despues.votacion.votos_individuales is not None
    assert despues.votacion.votos_individuales[0].valor == "POSITIVO"

    votacion.registrar_voto(VotoOrdinario(segundo_dni, ValorVotoOrdinario.NEGATIVO))
    posterior = await entorno.servicio.obtener_estado_moderacion()
    assert posterior.votacion is not None and posterior.votacion.votos_individuales is not None
    assert [voto.valor for voto in posterior.votacion.votos_individuales] == [
        "POSITIVO",
        "NEGATIVO",
    ]


async def test_publico_en_curso_no_contiene_votos_dni_eventos_ni_mensajes(
    tmp_path: Path,
) -> None:
    """Prueba negativa sobre el JSON real producido por el modelo público."""

    entorno = crear_entorno_proyecciones(tmp_path)
    votacion = abrir_votacion_prueba(entorno)
    dni = entorno.contexto.padron.concejales[0].dni
    votacion.registrar_voto(VotoOrdinario(dni, ValorVotoOrdinario.POSITIVO))
    entorno.contexto.escritor_auditoria.registrar_evento(
        NivelAuditoria.L3,
        "VOTACION",
        "VOTO_ORDINARIO_REGISTRADO",
        f"DNI={dni}; banca=1; votó POSITIVO",
    )

    estado = await entorno.servicio.obtener_estado_recinto()
    texto = estado.model_dump_json()

    assert estado.votacion is not None
    assert estado.votacion.estado_recepcion == "EN_CURSO"
    assert estado.votacion.votos_individuales is None
    assert dni not in texto
    assert "POSITIVO" not in texto
    assert "VOTO_ORDINARIO_REGISTRADO" not in texto
    assert "votó" not in texto
    assert estado.eventos_publicos == ()
    assert "eventos_recientes" not in texto
    assert "mensaje" not in texto


async def test_countdown_publico_deriva_de_apertura_y_no_de_reconexion(tmp_path: Path) -> None:
    """Dos snapshots conservan el mismo deadline aunque avance el reloj."""

    entorno = crear_entorno_proyecciones(tmp_path, cuenta_regresiva=4)
    votacion = abrir_votacion_prueba(entorno)
    primero = await entorno.servicio.obtener_estado_recinto()
    entorno.reloj.avanzar(3)
    reconectado = await entorno.servicio.obtener_estado_recinto()

    assert primero.votacion is not None and reconectado.votacion is not None
    esperado = votacion.fecha_hora_apertura + timedelta(seconds=4)
    assert primero.votacion.cuenta_regresiva_hasta == esperado
    assert reconectado.votacion.cuenta_regresiva_hasta == esperado


@pytest.mark.parametrize(
    "resultado",
    (ResultadoVotacion.APROBADA, ResultadoVotacion.RECHAZADA),
)
async def test_resultado_final_publico_expira_desde_su_disponibilidad(
    tmp_path: Path,
    resultado: ResultadoVotacion,
) -> None:
    """Aprobada/rechazada viven exactamente la ventana configurada."""

    entorno = crear_entorno_proyecciones(
        tmp_path,
        resultado_publico=6,
        revelado_moderacion=0,
    )
    votacion = abrir_votacion_prueba(entorno)
    dni = entorno.contexto.padron.concejales[0].dni
    votacion.registrar_voto(VotoOrdinario(dni, ValorVotoOrdinario.POSITIVO))
    votacion.cerrar_recepcion(entorno.reloj.ahora())
    votacion.aplicar_resultado_ordinario(resultado, entorno.reloj.ahora())
    entorno.estado.votacion_activa = None

    moderacion_visible = await entorno.servicio.obtener_estado_moderacion()
    recinto_visible = await entorno.servicio.obtener_estado_recinto()
    assert moderacion_visible.votacion is not None
    assert recinto_visible.votacion is not None
    assert recinto_visible.votacion.resultado == resultado.value
    assert recinto_visible.votacion.votos_individuales is not None
    frontera = entorno.reloj.ahora() + timedelta(seconds=6)
    assert moderacion_visible.votacion.resultado_visible_hasta == frontera
    assert recinto_visible.votacion.resultado_visible_hasta == frontera

    entorno.reloj.avanzar(6)
    moderacion_expirada = await entorno.servicio.obtener_estado_moderacion()
    recinto_expirado = await entorno.servicio.obtener_estado_recinto()
    # La frontera retira solamente la presentación Q3/Recinto. Q1 conserva el
    # resultado institucional completo en EstadoModeracion.
    assert moderacion_expirada.votacion is not None
    assert moderacion_expirada.votacion.resultado == resultado.value
    assert moderacion_expirada.votacion.votos_individuales is not None
    assert moderacion_expirada.votacion.resultado_visible_hasta == frontera
    assert recinto_expirado.votacion is None
    assert recinto_expirado.sesion is not None


async def test_inconclusa_inicia_ventana_y_conserva_votos(tmp_path: Path) -> None:
    """La finalización manual se presenta como resultado final transitorio."""

    entorno = crear_entorno_proyecciones(tmp_path, resultado_publico=6)
    votacion = abrir_votacion_prueba(entorno)
    dni = entorno.contexto.padron.concejales[0].dni
    votacion.registrar_voto(VotoOrdinario(dni, ValorVotoOrdinario.ABSTENCION))
    votacion.finalizar_inconclusa_manual(entorno.reloj.ahora(), "Moción de prueba")
    entorno.estado.votacion_activa = None

    estado = await entorno.servicio.obtener_estado_recinto()
    assert estado.votacion is not None
    assert estado.votacion.resultado == "INCONCLUSA"
    assert estado.votacion.votos_individuales is not None
    assert estado.votacion.votos_individuales[0].valor == "ABSTENCION"


async def test_cerrada_sin_resultado_de_fallo_cerrado_sigue_proyectable(tmp_path: Path) -> None:
    """El estado técnico real no se completa ni se oculta artificialmente."""

    entorno = crear_entorno_proyecciones(tmp_path, revelado_moderacion=0)
    votacion = abrir_votacion_prueba(entorno)
    votacion.cerrar_recepcion(entorno.reloj.ahora())

    moderacion = await entorno.servicio.obtener_estado_moderacion()
    recinto = await entorno.servicio.obtener_estado_recinto()

    assert moderacion.votacion is not None
    assert moderacion.votacion.estado_recepcion == "CERRADA"
    assert moderacion.votacion.resultado is None
    assert recinto.votacion is not None
    assert recinto.votacion.estado_recepcion == "CERRADA"
    assert recinto.votacion.resultado is None


async def test_empate_no_expira_y_desempate_tardio_inicia_ventana_completa(
    tmp_path: Path,
) -> None:
    """La fecha de cierre antigua no acorta el resultado presidencial tardío."""

    entorno = crear_entorno_proyecciones(tmp_path, resultado_publico=6)
    votacion = abrir_votacion_prueba(entorno)
    votacion.cerrar_recepcion(entorno.reloj.ahora())
    votacion.aplicar_resultado_ordinario(ResultadoVotacion.EMPATADA, entorno.reloj.ahora())

    entorno.reloj.avanzar(60)
    empate = await entorno.servicio.obtener_estado_recinto()
    empate_moderacion = await entorno.servicio.obtener_estado_moderacion()
    assert empate.votacion is not None and empate.votacion.resultado == "EMPATADA"
    assert empate.votacion.resultado_visible_hasta is None
    assert empate_moderacion.votacion is not None
    assert empate_moderacion.votacion.resultado_visible_hasta is None

    voto = votacion.preparar_voto_desempate(
        SentidoVotoDesempate.POSITIVO,
        "Presidencia de prueba",
    )
    votacion.registrar_voto_desempate(voto)
    votacion.consolidar_resultado_desempate(entorno.reloj.ahora())
    entorno.estado.votacion_activa = None
    resuelto = await entorno.servicio.obtener_estado_recinto()
    resuelto_moderacion = await entorno.servicio.obtener_estado_moderacion()
    assert resuelto.votacion is not None
    assert resuelto.votacion.resultado == "APROBADA"
    assert resuelto.votacion.resultado_visible_hasta == entorno.reloj.ahora() + timedelta(seconds=6)
    assert resuelto_moderacion.votacion is not None
    assert (
        resuelto_moderacion.votacion.resultado_visible_hasta
        == resuelto.votacion.resultado_visible_hasta
    )
    assert resuelto.votacion.voto_presidencial is not None


async def test_fallo_parcial_desempate_no_publica_resultado_inferible(tmp_path: Path) -> None:
    """EMPATADA + voto durable es visible solo con detalle técnico en Moderación."""

    entorno = crear_entorno_proyecciones(tmp_path)
    votacion = abrir_votacion_prueba(entorno)
    votacion.cerrar_recepcion(entorno.reloj.ahora())
    votacion.aplicar_resultado_ordinario(ResultadoVotacion.EMPATADA, entorno.reloj.ahora())
    voto = votacion.preparar_voto_desempate(
        SentidoVotoDesempate.NEGATIVO,
        "Presidencia de prueba",
    )
    votacion.registrar_voto_desempate(voto)

    moderacion = await entorno.servicio.obtener_estado_moderacion()
    recinto = await entorno.servicio.obtener_estado_recinto()

    assert moderacion.votacion is not None and moderacion.votacion.voto_presidencial is not None
    assert moderacion.votacion.resultado == "EMPATADA"
    assert recinto.votacion is not None and recinto.votacion.resultado == "EMPATADA"
    assert recinto.votacion.voto_presidencial is None
    assert "NEGATIVO" not in recinto.model_dump_json()


async def test_nueva_votacion_sustituye_presentacion_anterior(tmp_path: Path) -> None:
    """La EN_CURSO más reciente aplica secreto aunque el resultado previo siga en plazo."""

    entorno = crear_entorno_proyecciones(tmp_path, resultado_publico=6)
    primera = abrir_votacion_prueba(entorno, id_votacion="primera")
    primera.cerrar_recepcion(entorno.reloj.ahora())
    primera.aplicar_resultado_ordinario(ResultadoVotacion.APROBADA, entorno.reloj.ahora())
    entorno.estado.votacion_activa = None
    segunda = abrir_votacion_prueba(entorno, id_votacion="segunda")
    dni = entorno.contexto.padron.concejales[0].dni
    segunda.registrar_voto(VotoOrdinario(dni, ValorVotoOrdinario.NEGATIVO))

    estado = await entorno.servicio.obtener_estado_recinto()
    assert estado.votacion is not None and estado.votacion.id == "segunda"
    assert estado.votacion.estado_recepcion == EstadoVotacion.EN_CURSO.value
    assert estado.votacion.votos_individuales is None
    assert "NEGATIVO" not in estado.model_dump_json()


async def test_auditoria_cerrada_desactiva_capacidades_pero_no_lectura(tmp_path: Path) -> None:
    """El fallo técnico se proyecta sin cerrar el canal de solo lectura."""

    entorno = crear_entorno_proyecciones(tmp_path)
    abrir_sesion_prueba(entorno)
    entorno.contexto.escritor_auditoria.cerrar()

    estado = await entorno.servicio.obtener_estado_moderacion()

    assert estado.auditoria.cerrado
    assert estado.auditoria.motivo == "AUDITORIA_CERRADA"
    assert not estado.capacidades.abrir_votacion.habilitada
    assert "AUDITORIA_NO_DISPONIBLE" in estado.capacidades.abrir_votacion.motivos
    assert estado.sesion is not None


async def test_capacidades_remapeo_siguen_estado_y_auditoria_autoritativos(
    tmp_path: Path,
) -> None:
    """DP-024-01 proyecta inicio, confirmación y cancelación sin validar bodies futuros."""

    entorno = crear_entorno_proyecciones(tmp_path)

    sin_operacion = await entorno.servicio.obtener_estado_moderacion()
    assert sin_operacion.capacidades.iniciar_remapeo.habilitada
    assert not sin_operacion.capacidades.confirmar_remapeo.habilitada
    assert sin_operacion.capacidades.confirmar_remapeo.motivos == ("REMAPEO_NO_COINCIDE",)
    assert not sin_operacion.capacidades.cancelar_remapeo.habilitada

    operacion = OperacionRemapeo(remapeo_id="remapeo-prueba", dispositivo="P-01")
    entorno.estado.remapeo_activo = operacion
    capturando = await entorno.servicio.obtener_estado_moderacion()
    assert not capturando.capacidades.iniciar_remapeo.habilitada
    assert capturando.capacidades.iniciar_remapeo.motivos == ("REMAPEO_YA_ACTIVO",)
    assert not capturando.capacidades.confirmar_remapeo.habilitada
    assert capturando.capacidades.confirmar_remapeo.motivos == ("REMAPEO_SIN_CANDIDATO",)
    assert capturando.capacidades.cancelar_remapeo.habilitada

    operacion.candidato = "fingerprint-candidato"
    operacion.estado = EstadoRemapeo.CANDIDATO
    candidato = await entorno.servicio.obtener_estado_moderacion()
    assert candidato.capacidades.confirmar_remapeo.habilitada
    assert candidato.capacidades.cancelar_remapeo.habilitada

    operacion.estado = EstadoRemapeo.CONFIRMANDO
    confirmando = await entorno.servicio.obtener_estado_moderacion()
    assert not confirmando.capacidades.confirmar_remapeo.habilitada
    assert confirmando.capacidades.confirmar_remapeo.motivos == ("REMAPEO_NO_COINCIDE",)

    operacion.estado = EstadoRemapeo.CANDIDATO

    entorno.contexto.escritor_auditoria.cerrar()
    sin_auditoria = await entorno.servicio.obtener_estado_moderacion()
    assert not sin_auditoria.capacidades.confirmar_remapeo.habilitada
    assert sin_auditoria.capacidades.confirmar_remapeo.motivos == ("AUDITORIA_NO_DISPONIBLE",)
    # Cancelar no escribe un hecho institucional y debe seguir permitiendo
    # abandonar de forma segura la coordinación física ya iniciada.
    assert sin_auditoria.capacidades.cancelar_remapeo.habilitada


async def test_moderacion_proyecta_solo_los_ultimos_doscientos_eventos(tmp_path: Path) -> None:
    """El evento 201 desplaza al primero también en el DTO final."""

    entorno = crear_entorno_proyecciones(tmp_path)
    for numero in range(1, 202):
        entorno.contexto.escritor_auditoria.registrar_evento(
            NivelAuditoria.L1,
            "PRUEBA",
            f"EVENTO_{numero}",
            f"Mensaje {numero}",
        )

    estado = await entorno.servicio.obtener_estado_moderacion()
    assert len(estado.eventos_recientes) == 200
    assert estado.eventos_recientes[0].seq == 2
    assert estado.eventos_recientes[-1].seq == 201
    assert [evento.seq for evento in estado.eventos_recientes] == list(range(2, 202))
