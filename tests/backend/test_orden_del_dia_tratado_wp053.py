"""Pruebas de la ayuda asistencial "número ya tratado" del Orden del Día (WP-053).

WP-053 no agrega ninguna regla institucional: sólo pide que Moderación pueda
reconocer de un vistazo qué números del Orden del Día ya se trataron. La marca
la calcula el backend porque el frontend nunca decide reglas y porque así una
reconexión reconstruye la ayuda desde el snapshot, sin estado local.

Estas pruebas fijan las cuatro decisiones humanas cerradas del WP:

1. un número queda tratado desde que se **abre** una votación con ese número;
2. la comparación usa exclusivamente ``nro_votacion``;
3. si el CSV repite el número, se marcan todas las filas que lo comparten;
4. marcar es ayuda visual y nunca consume, bloquea ni altera la colección.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sis_leg_backend.dominio.orden_del_dia import PuntoOrdenDelDia
from sis_leg_backend.dominio.votacion import BaseMayoria, TipoMayoria

from tests.backend.ayudas_proyecciones import (
    EntornoProyecciones,
    abrir_sesion_prueba,
    abrir_votacion_prueba,
    crear_entorno_proyecciones,
)

pytestmark = pytest.mark.anyio


def _punto(
    nro_votacion: int,
    *,
    tema: str = "Tema del punto",
    tipo: str = "Despacho",
) -> PuntoOrdenDelDia:
    """Construye un punto SIMPLE mínimo con el número externo pedido.

    El tema y el tipo son variables para poder demostrar que dos filas distintas
    que comparten número se marcan igual: la comparación mira sólo el número.
    """

    return PuntoOrdenDelDia(
        nro_votacion=nro_votacion,
        tipo=tipo,
        tema=tema,
        tipo_mayoria=TipoMayoria.SIMPLE,
        factor=0.0,
        base=BaseMayoria.VOTOS_COMPUTABLES,
    )


def _instalar_orden_del_dia(
    entorno: EntornoProyecciones,
    *puntos: PuntoOrdenDelDia,
) -> None:
    """Instala la colección directamente en el contexto congelado de la preparación.

    Se evita pasar por el servicio de carga porque este archivo prueba la
    proyección, no el parseo del CSV, que ya tiene sus propias pruebas.
    """

    entorno.contexto.orden_del_dia = puntos


async def test_sin_votaciones_ningun_punto_aparece_tratado(tmp_path: Path) -> None:
    """Historial vacío: la ayuda no marca nada, ni siquiera con sesión abierta."""

    entorno = crear_entorno_proyecciones(tmp_path)
    _instalar_orden_del_dia(entorno, _punto(1), _punto(2))
    abrir_sesion_prueba(entorno)

    moderacion = await entorno.servicio.obtener_estado_moderacion()

    assert [punto.tratado for punto in moderacion.orden_del_dia] == [False, False]


async def test_orden_del_dia_en_preparacion_nunca_esta_tratado(tmp_path: Path) -> None:
    """Durante ``PREPARANDO`` no existe historial y la marca es siempre falsa."""

    entorno = crear_entorno_proyecciones(tmp_path)
    _instalar_orden_del_dia(entorno, _punto(1))

    moderacion = await entorno.servicio.obtener_estado_moderacion()

    assert moderacion.orden_del_dia[0].tratado is False


async def test_votacion_abierta_sin_finalizar_ya_marca_el_numero(tmp_path: Path) -> None:
    """Decisión 1: no hace falta cerrar la votación para considerarla tratada."""

    entorno = crear_entorno_proyecciones(tmp_path)
    _instalar_orden_del_dia(entorno, _punto(4), _punto(5))
    abrir_sesion_prueba(entorno)
    votacion = abrir_votacion_prueba(entorno, numero_votacion=4)

    moderacion = await entorno.servicio.obtener_estado_moderacion()

    # La votación sigue recibiendo votos: la ayuda ya está activa igualmente.
    assert votacion.fecha_hora_cierre is None
    assert moderacion.orden_del_dia[0].nro_votacion == 4
    assert moderacion.orden_del_dia[0].tratado is True
    assert moderacion.orden_del_dia[1].tratado is False


async def test_votacion_finalizada_conserva_el_numero_tratado(tmp_path: Path) -> None:
    """Cerrar la votación no revierte la ayuda: el número siguió tratándose."""

    entorno = crear_entorno_proyecciones(tmp_path)
    _instalar_orden_del_dia(entorno, _punto(4))
    abrir_sesion_prueba(entorno)
    votacion = abrir_votacion_prueba(entorno, numero_votacion=4)
    votacion.finalizar_inconclusa_manual(entorno.reloj.ahora(), "Cierre de prueba")
    entorno.estado.votacion_activa = None

    moderacion = await entorno.servicio.obtener_estado_moderacion()

    assert moderacion.orden_del_dia[0].tratado is True


async def test_numeros_repetidos_en_el_csv_se_marcan_todos(tmp_path: Path) -> None:
    """Decisiones 2 y 3: se compara sólo el número, así que caen todas las filas."""

    entorno = crear_entorno_proyecciones(tmp_path)
    _instalar_orden_del_dia(
        entorno,
        _punto(7, tema="Primera lectura", tipo="Despacho"),
        _punto(8, tema="Otro asunto"),
        _punto(7, tema="Segunda lectura", tipo="Moción"),
    )
    abrir_sesion_prueba(entorno)
    # El tema y el tipo de la votación abierta no coinciden con ningún punto:
    # la ayuda no debe intentar emparejarlos.
    abrir_votacion_prueba(entorno, numero_votacion=7)

    moderacion = await entorno.servicio.obtener_estado_moderacion()

    assert [(punto.nro_votacion, punto.tratado) for punto in moderacion.orden_del_dia] == [
        (7, True),
        (8, False),
        (7, True),
    ]


async def test_varias_votaciones_acumulan_los_numeros_tratados(tmp_path: Path) -> None:
    """El historial completo aporta la ayuda, no sólo la última votación."""

    entorno = crear_entorno_proyecciones(tmp_path)
    _instalar_orden_del_dia(entorno, _punto(1), _punto(2), _punto(3))
    abrir_sesion_prueba(entorno)
    primera = abrir_votacion_prueba(entorno, id_votacion="votacion-1", numero_votacion=3)
    primera.finalizar_inconclusa_manual(entorno.reloj.ahora(), "Cierre de prueba")
    abrir_votacion_prueba(entorno, id_votacion="votacion-2", numero_votacion=1)

    moderacion = await entorno.servicio.obtener_estado_moderacion()

    assert [punto.tratado for punto in moderacion.orden_del_dia] == [True, False, True]


async def test_la_ayuda_no_altera_el_resto_del_punto_ni_la_coleccion(tmp_path: Path) -> None:
    """Decisión 4: marcar no consume el punto ni toca los datos del CSV."""

    entorno = crear_entorno_proyecciones(tmp_path)
    _instalar_orden_del_dia(entorno, _punto(2, tema="Ordenanza fiscal", tipo="Despacho"))
    abrir_sesion_prueba(entorno)
    abrir_votacion_prueba(entorno, numero_votacion=2)

    moderacion = await entorno.servicio.obtener_estado_moderacion()
    punto = moderacion.orden_del_dia[0]

    assert punto.tratado is True
    assert (punto.nro_votacion, punto.tipo, punto.tema) == (2, "Despacho", "Ordenanza fiscal")
    assert (punto.tipo_mayoria, punto.factor, punto.base) == (
        "SIMPLE",
        0.0,
        "VOTOS_COMPUTABLES",
    )
    # La colección del dominio sigue intacta: la marca vive sólo en el DTO.
    assert entorno.contexto.orden_del_dia is not None
    assert len(entorno.contexto.orden_del_dia) == 1
    assert entorno.contexto.orden_del_dia[0].nro_votacion == 2
    assert moderacion.capacidades.abrir_votacion is not None


async def test_snapshot_posterior_reconstruye_la_ayuda_sin_estado_previo(tmp_path: Path) -> None:
    """Reconexión/reload: cada snapshot vuelve a derivar la marca del historial.

    Es exactamente lo que hace un cliente que se reconecta: pide el snapshot de
    nuevo y recibe la misma verdad, sin depender de lo que hubiera visto antes.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    _instalar_orden_del_dia(entorno, _punto(5), _punto(6))
    abrir_sesion_prueba(entorno)

    antes = await entorno.servicio.obtener_estado_moderacion()
    assert [punto.tratado for punto in antes.orden_del_dia] == [False, False]

    abrir_votacion_prueba(entorno, numero_votacion=6)

    despues = await entorno.servicio.obtener_estado_moderacion()
    assert [punto.tratado for punto in despues.orden_del_dia] == [False, True]

    # Un tercer snapshot idéntico prueba que la derivación es estable y no
    # consume el historial ni depende del snapshot anterior.
    repetido = await entorno.servicio.obtener_estado_moderacion()
    assert [punto.tratado for punto in repetido.orden_del_dia] == [False, True]


async def test_recinto_sigue_sin_recibir_el_orden_del_dia(tmp_path: Path) -> None:
    """La ayuda es de Moderación: la proyección pública no gana ningún campo.

    Es la regresión que protege la frontera de secreto reforzada por WP-052: el
    Orden del Día completo, y ahora también qué números se trataron, no salen
    por la proyección de Recinto.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    _instalar_orden_del_dia(entorno, _punto(9))
    abrir_sesion_prueba(entorno)
    abrir_votacion_prueba(entorno, numero_votacion=9)

    recinto = await entorno.servicio.obtener_estado_recinto()
    volcado = recinto.model_dump()

    assert "orden_del_dia" not in volcado
    assert "tratado" not in str(volcado)
