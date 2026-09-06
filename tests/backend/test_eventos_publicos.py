"""Regresiones de la allowlist y sanitización de eventos del Recinto.

Estas pruebas trabajan sobre el buffer confirmado del escritor real. El
objetivo no es volver a probar el CSV, sino demostrar que la proyección pública
solo acepta hechos L3 enumerados y nunca transporta el mensaje humano crudo.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sis_leg_backend.auditoria import NivelAuditoria
from sis_leg_backend.dominio.estado import EstadoGlobal

from tests.backend.ayudas_proyecciones import crear_entorno_proyecciones

pytestmark = pytest.mark.anyio

EVENTOS_PERMITIDOS = (
    ("SESION_ABIERTA", "SESION", "Sesión abierta"),
    ("SESION_CERRADA", "SESION", "Sesión cerrada"),
    ("CONCEJAL_PRESENTE", "PRESENCIA", "Concejal presente"),
    ("CONCEJAL_AUSENTE", "PRESENCIA", "Concejal ausente"),
    ("PEDIDO_PALABRA_REGISTRADO", "PALABRA", "Pedido de palabra registrado"),
    ("PEDIDO_PALABRA_RETIRADO", "PALABRA", "Pedido de palabra retirado"),
    ("USO_PALABRA_OTORGADO", "PALABRA", "Uso de palabra otorgado"),
    ("USO_PALABRA_FINALIZADO", "PALABRA", "Uso de palabra finalizado"),
    ("VOTACION_ABIERTA", "VOTACION", "Votación abierta"),
    ("VOTACION_CERRADA_COMPLETITUD", "VOTACION", "Votación cerrada"),
    (
        "VOTACION_FINALIZADA_INCONCLUSA",
        "VOTACION",
        "Votación finalizada inconclusa",
    ),
    ("VOTACION_RESULTADO_FINAL", "VOTACION", "Resultado de votación disponible"),
    ("VOTACION_RESULTADO_EMPATE", "VOTACION", "Resultado de votación empatado"),
    (
        "VOTACION_RESULTADO_DESEMPATE",
        "VOTACION",
        "Resultado de desempate disponible",
    ),
)


@pytest.mark.parametrize(("codigo", "categoria", "texto"), EVENTOS_PERMITIDOS)
async def test_cada_codigo_allowlist_se_proyecta_con_texto_fijo(
    tmp_path: Path,
    codigo: str,
    categoria: str,
    texto: str,
) -> None:
    """Cada familia autorizada usa una traducción estable, nunca ``mensaje``."""

    entorno = crear_entorno_proyecciones(tmp_path)
    entorno.contexto.escritor_auditoria.registrar_evento(
        NivelAuditoria.L3,
        "ETIQUETA_INTERNA",
        codigo,
        "DNI=99999999; dispositivo=USB-SECRETO; tecla=1; sentido=POSITIVO",
    )

    estado = await entorno.servicio.obtener_estado_recinto()

    assert len(estado.eventos_publicos) == 1
    evento = estado.eventos_publicos[0]
    assert evento.categoria == categoria
    assert evento.codigo_evento == codigo
    assert evento.texto == texto
    assert evento.model_dump().keys() == {
        "seq",
        "timestamp",
        "categoria",
        "codigo_evento",
        "texto",
    }
    serializado = estado.model_dump_json()
    for secreto in ("99999999", "USB-SECRETO", "tecla=1", "POSITIVO", "mensaje", "nivel"):
        assert secreto not in serializado


async def test_deny_by_default_omite_votos_codigos_futuros_y_evento_l2(
    tmp_path: Path,
) -> None:
    """Ni un código desconocido ni un hecho técnico atraviesan la frontera."""

    entorno = crear_entorno_proyecciones(tmp_path)
    escritor = entorno.contexto.escritor_auditoria
    for nivel, codigo in (
        (NivelAuditoria.L3, "CODIGO_FUTURO"),
        (NivelAuditoria.L3, "VOTO_ORDINARIO_REGISTRADO"),
        (NivelAuditoria.L3, "VOTO_DESEMPATE_PRESIDENCIAL"),
        # Incluso un código allowlisteado queda fuera si no representa un hecho
        # institucional L3 confirmado con su nivel canónico.
        (NivelAuditoria.L2, "SESION_ABIERTA"),
        (NivelAuditoria.L2, "PULSACION_RECIBIDA"),
    ):
        escritor.registrar_evento(nivel, "TECNICO", codigo, "mensaje interno")

    estado = await entorno.servicio.obtener_estado_recinto()

    assert estado.eventos_publicos == ()


async def test_conserva_orden_ascendente_y_los_veinte_permitidos_mas_recientes(
    tmp_path: Path,
) -> None:
    """El recorte ocurre después de filtrar y deja el evento más nuevo al final."""

    entorno = crear_entorno_proyecciones(tmp_path)
    escritor = entorno.contexto.escritor_auditoria
    for numero in range(25):
        escritor.registrar_evento(
            NivelAuditoria.L3,
            "SESION",
            "SESION_ABIERTA",
            f"mensaje crudo {numero}",
        )

    estado = await entorno.servicio.obtener_estado_recinto()

    assert [evento.seq for evento in estado.eventos_publicos] == list(range(6, 26))
    assert all(evento.texto == "Sesión abierta" for evento in estado.eventos_publicos)


async def test_sin_contexto_y_preparacion_nueva_no_heredan_eventos(tmp_path: Path) -> None:
    """La colección sigue el ciclo de vida del escritor de la preparación."""

    anterior = crear_entorno_proyecciones(tmp_path / "anterior")
    anterior.contexto.escritor_auditoria.registrar_evento(
        NivelAuditoria.L3,
        "SESION",
        "SESION_ABIERTA",
        "mensaje anterior",
    )
    assert len((await anterior.servicio.obtener_estado_recinto()).eventos_publicos) == 1

    anterior.estado.preparacion_activa = None
    anterior.estado.sesion_activa = None
    anterior.estado.estado_global = EstadoGlobal.SIN_PREPARAR
    assert (await anterior.servicio.obtener_estado_recinto()).eventos_publicos == ()

    nueva = crear_entorno_proyecciones(tmp_path / "nueva")
    assert (await nueva.servicio.obtener_estado_recinto()).eventos_publicos == ()
