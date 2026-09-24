"""Qué texto ve el operador en el panel de eventos recientes (WP-107 I003).

Por qué existe esta suite
-------------------------

Moderación muestra el ``message`` durable de cada evento L3 tal como quedó
persistido. Desde WP-107 I002 algunas familias escriben sus campos humanos
codificados, así que la proyección tiene que deshacer esa codificación antes de
publicarla: de otro modo el operador leería los escapes en pantalla.

La auditoría pre-merge 002 encontró que esa decodificación se decidía **mirando
el contenido del mensaje**, buscando la marca de formato como subcadena. Eso
repetía, en la capa de presentación, el error de fondo que WP-107 corrige: el
texto que escribe una persona no puede decidir nada estructural. Un aviso de
recinto cuyo cuerpo contuviera ``formato=h1;`` llegaba mutilado al panel.

Desde la iteración 3 la decisión sale del par ``(tag, event_code)``, columnas que
sólo escribe el productor. Estas pruebas recorren la proyección real —no la
función suelta— para dejarlo fijado donde el operador lo ve.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from ayudas_proyecciones import EntornoProyecciones, crear_entorno_proyecciones
from sis_leg_backend.auditoria import NivelAuditoria
from sis_leg_backend.servicios.texto_humano_l3 import (
    MARCA_FORMATO_TEXTO_HUMANO,
    codificar_texto_humano,
)

pytestmark = pytest.mark.anyio

TEXTOS_QUE_IMITAN_EL_FORMATO = (
    pytest.param("Texto literal formato=h1; con \\p y \\n y \\r", id="marca-y-escapes"),
    pytest.param("formato=h1; ", id="solo-la-marca"),
    pytest.param("formato=h2; texto", id="version-futura"),
    pytest.param("\\p\\n\\r", id="solo-escapes"),
    pytest.param("Cuarto intermedio formato=h1; \\p ñ/á", id="mezcla-realista"),
)


async def _mensajes_publicados(entorno: EntornoProyecciones) -> dict[str, str]:
    """Devuelve el mensaje que la proyección publica, indexado por event_code."""

    estado = await entorno.servicio.obtener_estado_moderacion()
    return {evento.codigo_evento: evento.mensaje for evento in estado.eventos_recientes}


@pytest.mark.parametrize("texto", TEXTOS_QUE_IMITAN_EL_FORMATO)
async def test_un_marcador_de_recinto_llega_intacto_al_panel(
    tmp_path: Path,
    texto: str,
) -> None:
    """Regresión C: una familia no codificada conserva su texto exacto.

    ``EVENTO/INICIO`` publica el aviso tal como lo vio el recinto y nunca usó el
    formato codificado. Contenga lo que contenga, el panel debe mostrar
    exactamente lo que se persistió.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    entorno.contexto.escritor_auditoria.registrar_evento(
        NivelAuditoria.L3,
        "EVENTO",
        "INICIO",
        texto,
    )

    publicados = await _mensajes_publicados(entorno)

    assert publicados["INICIO"] == texto


@pytest.mark.parametrize("texto", TEXTOS_QUE_IMITAN_EL_FORMATO)
async def test_una_actualizacion_historica_llega_intacta_al_panel(
    tmp_path: Path,
    texto: str,
) -> None:
    """Regresión C: la familia legacy representativa tampoco se reinterpreta.

    Es el caso más delicado: en estas familias el texto humano empieza justo
    después del prefijo, así que puede reproducir la marca entera.
    """

    mensaje = f"Presidencia actualizado: {texto} -> Autoridad Siguiente"
    entorno = crear_entorno_proyecciones(tmp_path)
    entorno.contexto.escritor_auditoria.registrar_evento(
        NivelAuditoria.L3,
        "SESION",
        "PRESIDENCIA_ACTUALIZADA",
        mensaje,
    )

    publicados = await _mensajes_publicados(entorno)

    assert publicados["PRESIDENCIA_ACTUALIZADA"] == mensaje


async def test_las_familias_codificadas_llegan_legibles_al_panel(tmp_path: Path) -> None:
    """Regresión D: lo que sí está codificado se muestra sin escapes ni marca.

    Se cubren las tres formas del formato vigente: apertura de votación, bloque
    de identidad de palabra y actualización de autoridad versionada.
    """

    humano = 'Ñandú "Peña"; artículo=3\ny Lillo'
    codificado = codificar_texto_humano(humano)
    entorno = crear_entorno_proyecciones(tmp_path)
    escritor = entorno.contexto.escritor_auditoria

    escritor.registrar_evento(
        NivelAuditoria.L3,
        "VOTACION",
        "VOTACION_ABIERTA",
        f"Votación abierta: {MARCA_FORMATO_TEXTO_HUMANO}; número=1"
        f"; tipo={codificado}; tema={codificado}"
        "; tipo_mayoria=SIMPLE; factor=0.0; base=VOTOS_COMPUTABLES",
    )
    escritor.registrar_evento(
        NivelAuditoria.L3,
        "PALABRA",
        "PEDIDO_PALABRA_REGISTRADO",
        f"Pedido de palabra registrado: {MARCA_FORMATO_TEXTO_HUMANO}"
        f"; DNI=30000001; concejal={codificado}; banca=1; posicion=1",
    )
    escritor.registrar_evento(
        NivelAuditoria.L3,
        "SESION",
        "PRESIDENCIA_ACTUALIZADA_H1",
        f"Presidencia actualizado: {MARCA_FORMATO_TEXTO_HUMANO}"
        f"; anterior={codificado}; nuevo={codificado}",
    )

    publicados = await _mensajes_publicados(entorno)

    assert publicados["VOTACION_ABIERTA"] == (
        f"Votación abierta: número=1; tipo={humano}; tema={humano}"
        "; tipo_mayoria=SIMPLE; factor=0.0; base=VOTOS_COMPUTABLES"
    )
    assert publicados["PEDIDO_PALABRA_REGISTRADO"] == (
        f"Pedido de palabra registrado: DNI=30000001; concejal={humano}; banca=1; posicion=1"
    )
    assert publicados["PRESIDENCIA_ACTUALIZADA_H1"] == (
        f"Presidencia actualizado: anterior={humano}; nuevo={humano}"
    )

    # Ningún mensaje publicado conserva la marca técnica en su posición.
    for codigo, mensaje in publicados.items():
        assert f": {MARCA_FORMATO_TEXTO_HUMANO}; " not in mensaje, (
            f"El evento {codigo} llegó al panel con la marca de formato visible"
        )
