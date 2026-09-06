"""Pruebas del buffer de 200 eventos confirmado después de ``fsync``."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from sis_leg_backend.auditoria import (
    ErrorAuditoria,
    EscritorAuditoriaCsv,
    NivelAuditoria,
)

FECHA = datetime(2026, 8, 24, 11, 0, 0)


def crear_escritor(tmp_path: Path, nombre: str) -> EscritorAuditoriaCsv:
    """Crea un conjunto aislado sin costo real de ``fsync`` en la prueba."""

    return EscritorAuditoriaCsv(
        tmp_path / nombre,
        FECHA,
        reloj=lambda: FECHA,
        sincronizar=lambda _descriptor: None,
    )


def registrar_eventos(escritor: EscritorAuditoriaCsv, cantidad: int) -> None:
    """Registra una secuencia L1 fácil de reconocer y ordenar."""

    for numero in range(1, cantidad + 1):
        escritor.registrar_evento(
            NivelAuditoria.L1,
            "PRUEBA",
            f"EVENTO_{numero:03d}",
            f"Mensaje {numero}",
        )


@pytest.mark.parametrize("cantidad", (0, 17, 200))
def test_buffer_conserva_cero_menos_de_doscientos_y_exactamente_doscientos(
    tmp_path: Path,
    cantidad: int,
) -> None:
    """El límite no rellena ni recorta antes de alcanzar 200 hechos."""

    escritor = crear_escritor(tmp_path, f"caso-{cantidad}")
    registrar_eventos(escritor, cantidad)

    eventos = escritor.eventos_recientes
    assert len(eventos) == cantidad
    assert [evento.secuencia for evento in eventos] == list(range(1, cantidad + 1))


def test_evento_201_desplaza_al_primero_y_mantiene_orden_ascendente(tmp_path: Path) -> None:
    """``deque(maxlen=200)`` conserva exactamente las secuencias 2..201."""

    escritor = crear_escritor(tmp_path, "mas-de-200")
    registrar_eventos(escritor, 201)

    eventos = escritor.eventos_recientes
    assert len(eventos) == 200
    assert eventos[0].secuencia == 2
    assert eventos[-1].secuencia == 201
    assert [evento.secuencia for evento in eventos] == list(range(2, 202))


def test_nueva_preparacion_no_hereda_buffer_anterior(tmp_path: Path) -> None:
    """Cada escritor/contexto comienza con su propio deque vacío."""

    anterior = crear_escritor(tmp_path, "anterior")
    registrar_eventos(anterior, 3)
    nueva = crear_escritor(tmp_path, "nueva")

    assert len(anterior.eventos_recientes) == 3
    assert nueva.eventos_recientes == ()


def test_evento_entra_al_buffer_solo_despues_del_ultimo_fsync(tmp_path: Path) -> None:
    """Durante la sincronización del archivo el evento aún no fue publicado."""

    referencia: dict[str, EscritorAuditoriaCsv] = {}
    tamanos_observados: list[int] = []

    def sincronizar(_descriptor: int) -> None:
        escritor_existente = referencia.get("escritor")
        if escritor_existente is not None:
            tamanos_observados.append(len(escritor_existente.eventos_recientes))

    escritor = EscritorAuditoriaCsv(
        tmp_path / "orden-fsync",
        FECHA,
        reloj=lambda: FECHA,
        sincronizar=sincronizar,
    )
    referencia["escritor"] = escritor
    escritor.registrar_evento(NivelAuditoria.L3, "PRUEBA", "CONFIRMADO", "Mensaje")

    assert tamanos_observados == [0, 0, 0]
    assert [evento.codigo_evento for evento in escritor.eventos_recientes] == ["CONFIRMADO"]


def test_fallo_de_fsync_no_confirma_evento_inexistente(tmp_path: Path) -> None:
    """Una persistencia fallida deja el writer cerrado a cambios y deque vacío."""

    referencia: dict[str, EscritorAuditoriaCsv] = {}

    def sincronizar(_descriptor: int) -> None:
        if "escritor" in referencia:
            raise OSError("fallo sintético de fsync")

    escritor = EscritorAuditoriaCsv(
        tmp_path / "fallo-fsync",
        FECHA,
        reloj=lambda: FECHA,
        sincronizar=sincronizar,
    )
    referencia["escritor"] = escritor

    with pytest.raises(ErrorAuditoria):
        escritor.registrar_evento(NivelAuditoria.L3, "PRUEBA", "NO_CONFIRMADO", "Mensaje")

    assert escritor.fallado
    assert escritor.eventos_recientes == ()
