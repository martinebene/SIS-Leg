"""Pruebas del motor CSV seguro definido por WP-004."""

from __future__ import annotations

import csv
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TextIO, cast

import pytest
from sis_leg_backend import auditoria
from sis_leg_backend.auditoria import (
    ENCABEZADO_CSV,
    ErrorAuditoria,
    ErrorEscritorNoDisponible,
    EscritorAuditoriaCsv,
    NivelAuditoria,
)


def leer_filas(ruta: Path) -> list[list[str]]:
    """Lee un CSV como lo haría una herramienta común compatible con UTF-8 BOM."""

    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.reader(archivo, delimiter=";"))


def test_crea_carpeta_archivos_y_encabezados_canonicos(tmp_path: Path) -> None:
    escritor = EscritorAuditoriaCsv(tmp_path, datetime(2026, 8, 13, 10, 20, 30))

    assert set(escritor.rutas) == set(NivelAuditoria)
    for nivel, ruta in escritor.rutas.items():
        assert ruta == tmp_path / "2026-08-13" / f"2026-08-13_10-20-30-{nivel}.csv"
        assert ruta.read_bytes().startswith(b"\xef\xbb\xbf")
        assert leer_filas(ruta) == [list(ENCABEZADO_CSV)]

    escritor.cerrar()


def test_distribuye_cada_nivel_de_forma_acumulativa(tmp_path: Path) -> None:
    escritor = EscritorAuditoriaCsv(
        tmp_path,
        datetime(2026, 8, 13, 10, 20, 30),
        reloj=lambda: datetime(2026, 8, 13, 10, 21, 0),
    )

    escritor.registrar_evento(NivelAuditoria.L1, "TECNICO", "PULSACION", "Detalle")
    escritor.registrar_evento(NivelAuditoria.L2, "OPERACION", "RECHAZO", "Aviso")
    escritor.registrar_evento(NivelAuditoria.L3, "SESION", "APERTURA", "Hecho")

    codigos_por_nivel = {
        nivel: [fila[4] for fila in leer_filas(ruta)[1:]] for nivel, ruta in escritor.rutas.items()
    }
    assert codigos_por_nivel == {
        NivelAuditoria.L1: ["PULSACION", "RECHAZO", "APERTURA"],
        NivelAuditoria.L2: ["RECHAZO", "APERTURA"],
        NivelAuditoria.L3: ["APERTURA"],
    }

    escritor.cerrar()


def test_comparte_secuencia_y_columnas_entre_archivos(tmp_path: Path) -> None:
    escritor = EscritorAuditoriaCsv(
        tmp_path,
        datetime(2026, 8, 13, 10, 20, 30),
        reloj=lambda: datetime(2026, 8, 13, 10, 22, 5),
    )

    primera = escritor.registrar_evento(NivelAuditoria.L3, "SESION", "INICIO", "Inicio")
    segunda = escritor.registrar_evento(NivelAuditoria.L2, "ENTRADA", "PRESENCIA", "Presente")

    assert (primera, segunda) == (1, 2)
    for nivel, ruta in escritor.rutas.items():
        filas = leer_filas(ruta)[1:]
        assert all(len(fila) == 6 for fila in filas)
        assert filas[0] == ["1", "2026-08-13 10:22:05", "L3", "SESION", "INICIO", "Inicio"]
        if nivel is not NivelAuditoria.L3:
            assert filas[1][0] == "2"

    escritor.cerrar()


def test_preserva_bom_acentos_delimitador_y_mensaje_humano(tmp_path: Path) -> None:
    escritor = EscritorAuditoriaCsv(
        tmp_path,
        datetime(2026, 8, 13, 10, 20, 30),
        reloj=lambda: datetime(2026, 8, 13, 10, 23, 0),
    )
    mensaje = "María emitió señal; revisión técnica"

    escritor.registrar_evento(NivelAuditoria.L1, "DISPOSITIVO", "SENAL_RECIBIDA", mensaje)

    ruta = escritor.rutas[NivelAuditoria.L1]
    contenido = ruta.read_bytes()
    assert contenido.startswith(b"\xef\xbb\xbf")
    assert mensaje.encode() in contenido
    assert leer_filas(ruta)[1][5] == mensaje
    escritor.cerrar()


def test_resuelve_varias_colisiones_sin_sufijos_ni_sobrescritura(tmp_path: Path) -> None:
    inicio = datetime(2026, 8, 13, 10, 20, 30)
    primero = EscritorAuditoriaCsv(tmp_path, inicio)
    segundo = EscritorAuditoriaCsv(tmp_path, inicio)
    tercero = EscritorAuditoriaCsv(tmp_path, inicio)

    nombres_l1 = (escritor.rutas[NivelAuditoria.L1] for escritor in (primero, segundo, tercero))
    assert {ruta.stem.removesuffix("-L1") for ruta in nombres_l1} == {
        "2026-08-13_10-20-30",
        "2026-08-13_10-20-31",
        "2026-08-13_10-20-32",
    }
    assert len(list((tmp_path / "2026-08-13").glob("*.csv"))) == 9
    assert not list((tmp_path / "2026-08-13").glob("*-02-*.csv"))

    for escritor in (primero, segundo, tercero):
        escritor.cerrar()


def test_colision_nominal_no_cambia_timestamp_real_del_evento(tmp_path: Path) -> None:
    inicio = datetime(2026, 8, 13, 10, 20, 30)
    primero = EscritorAuditoriaCsv(tmp_path, inicio)
    segundo = EscritorAuditoriaCsv(tmp_path, inicio, reloj=lambda: inicio)

    segundo.registrar_evento(NivelAuditoria.L1, "SALA", "PREPARACION", "Preparacion")

    assert "10-20-31" in segundo.rutas[NivelAuditoria.L1].name
    assert leer_filas(segundo.rutas[NivelAuditoria.L1])[1][1] == "2026-08-13 10:20:30"
    primero.cerrar()
    segundo.cerrar()


def test_colision_en_ultimo_segundo_cambia_nombre_y_carpeta_nominal(tmp_path: Path) -> None:
    inicio = datetime(2026, 8, 13, 23, 59, 59)
    primero = EscritorAuditoriaCsv(tmp_path, inicio)
    segundo = EscritorAuditoriaCsv(tmp_path, inicio, reloj=lambda: inicio)

    assert segundo.rutas[NivelAuditoria.L1] == (
        tmp_path / "2026-08-14" / "2026-08-14_00-00-00-L1.csv"
    )
    segundo.registrar_evento(NivelAuditoria.L1, "SALA", "INICIO", "Inicio real")
    assert leer_filas(segundo.rutas[NivelAuditoria.L1])[1][1] == "2026-08-13 23:59:59"
    primero.cerrar()
    segundo.cerrar()


class ArchivoObservado:
    """Delega en un archivo real y registra el orden de durabilidad para la prueba."""

    def __init__(self, archivo: TextIO, operaciones: list[tuple[str, int]]) -> None:
        self._archivo = archivo
        self._operaciones = operaciones

    def write(self, texto: str) -> int:
        self._operaciones.append(("write", self.fileno()))
        return self._archivo.write(texto)

    def flush(self) -> None:
        self._operaciones.append(("flush", self.fileno()))
        self._archivo.flush()

    def fileno(self) -> int:
        return self._archivo.fileno()

    def close(self) -> None:
        self._archivo.close()


def test_write_flush_y_fsync_ocurren_antes_del_retorno(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    operaciones: list[tuple[str, int]] = []
    abrir_real = cast(Callable[[Path], TextIO], vars(auditoria)["_abrir_archivo_exclusivo"])

    def abrir_observado(ruta: Path) -> TextIO:
        return cast(TextIO, ArchivoObservado(abrir_real(ruta), operaciones))

    def sincronizar_observado(descriptor: int) -> None:
        operaciones.append(("fsync", descriptor))

    monkeypatch.setattr(auditoria, "_abrir_archivo_exclusivo", abrir_observado)
    escritor = EscritorAuditoriaCsv(
        tmp_path,
        datetime(2026, 8, 13, 10, 20, 30),
        sincronizar=sincronizar_observado,
    )
    operaciones.clear()  # La apertura también sincroniza los encabezados.

    escritor.registrar_evento(NivelAuditoria.L3, "SESION", "APERTURA", "Abierta")

    descriptores = {descriptor for operacion, descriptor in operaciones if operacion == "fsync"}
    assert len(descriptores) == 3
    for descriptor in descriptores:
        operaciones_descriptor = [nombre for nombre, fd in operaciones if fd == descriptor]
        assert operaciones_descriptor[-3:] == ["write", "flush", "fsync"]
    escritor.cerrar()


def test_fallo_de_fsync_no_retorna_exito_y_activa_fallo_cerrado(tmp_path: Path) -> None:
    llamadas = 0

    def sincronizar_con_fallo(_descriptor: int) -> None:
        nonlocal llamadas
        llamadas += 1
        if llamadas == 4:  # Las tres primeras corresponden a los encabezados.
            raise OSError("disco no disponible")

    escritor = EscritorAuditoriaCsv(
        tmp_path,
        datetime(2026, 8, 13, 10, 20, 30),
        sincronizar=sincronizar_con_fallo,
    )

    with pytest.raises(ErrorAuditoria, match="seq=1"):
        escritor.registrar_evento(NivelAuditoria.L3, "SESION", "APERTURA", "Abierta")

    assert escritor.fallado
    with pytest.raises(ErrorEscritorNoDisponible, match="fallo cerrado"):
        escritor.registrar_evento(NivelAuditoria.L1, "TECNICO", "REINTENTO", "No permitido")
    escritor.cerrar()


def test_cierre_es_irreversible_y_no_modifica_archivos(tmp_path: Path) -> None:
    escritor = EscritorAuditoriaCsv(tmp_path, datetime(2026, 8, 13, 10, 20, 30))
    escritor.registrar_evento(NivelAuditoria.L1, "SALA", "INICIO", "Inicio")
    escritor.cerrar()
    contenidos_antes = {nivel: ruta.read_bytes() for nivel, ruta in escritor.rutas.items()}

    with pytest.raises(ErrorEscritorNoDisponible, match="cerrado"):
        escritor.registrar_evento(NivelAuditoria.L1, "SALA", "OTRO", "No escribir")
    escritor.cerrar()  # El segundo cierre es inocuo pero tampoco reabre el conjunto.

    assert escritor.cerrado
    assert {nivel: ruta.read_bytes() for nivel, ruta in escritor.rutas.items()} == contenidos_antes
