"""Pruebas unitarias de las invariantes estructurales de palabra (WP-015)."""

import pytest
from sis_leg_backend.dominio.sesion import EstadoPalabra


def test_cola_fifo_sin_duplicados_y_excluye_al_orador() -> None:
    """La estructura solo permite avanzar desde el primer pedido auditado."""

    palabra = EstadoPalabra()

    palabra.agregar_pedido("dni-1")
    palabra.agregar_pedido("dni-2")

    assert palabra.cola_dnis == ("dni-1", "dni-2")
    assert palabra.primer_pedido_dni == "dni-1"
    with pytest.raises(ValueError, match="ya espera"):
        palabra.agregar_pedido("dni-1")

    palabra.otorgar_primer_pedido("dni-1")

    assert palabra.orador_dni == "dni-1"
    assert palabra.cola_dnis == ("dni-2",)
    with pytest.raises(ValueError, match="ya espera o usa"):
        palabra.agregar_pedido("dni-1")


def test_finalizar_y_ausentar_no_promueven_ni_reordenan() -> None:
    """Finalizar un uso o limpiar una ausencia conserva al siguiente esperando."""

    palabra = EstadoPalabra()
    for dni in ("dni-1", "dni-2", "dni-3"):
        palabra.agregar_pedido(dni)
    palabra.otorgar_primer_pedido("dni-1")

    palabra.finalizar_uso("dni-1")

    assert palabra.orador_dni is None
    assert palabra.cola_dnis == ("dni-2", "dni-3")

    palabra.limpiar_por_ausencia("dni-2")

    assert palabra.orador_dni is None
    assert palabra.cola_dnis == ("dni-3",)


def test_no_se_puede_saltar_el_primer_pedido() -> None:
    """El dominio rechaza una selección arbitraria distinta del primero FIFO."""

    palabra = EstadoPalabra()
    palabra.agregar_pedido("dni-1")
    palabra.agregar_pedido("dni-2")

    with pytest.raises(ValueError, match="no es el primer pedido"):
        palabra.otorgar_primer_pedido("dni-2")

    assert palabra.cola_dnis == ("dni-1", "dni-2")
    assert palabra.orador_dni is None
