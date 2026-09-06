"""Pruebas de dominio y servicio para la entrada lógica de WP-006.

Los escenarios usan el writer real y un ``EjecutorMutaciones`` real. Así las
pruebas no solo comprueban el resultado en memoria: también verifican el orden
de auditoría, la persistencia acumulativa y el fallo cerrado que protege la
regla ``auditar antes de mutar``.
"""

from __future__ import annotations

import asyncio
import csv
from collections.abc import Callable
from datetime import datetime
from functools import partial
from pathlib import Path

import pytest
from conftest import (
    LINEA_LOGS,
    LINEA_QUORUM,
    LINEA_TIMER_TEST_DISPOSITIVO,
    TOML_CANONICO,
    escribir_padron,
    escribir_system_toml,
    filas_padron_valido,
)
from sis_leg_backend.auditoria import (
    ErrorAuditoria,
    ErrorEscritorNoDisponible,
    EscritorAuditoriaCsv,
    NivelAuditoria,
)
from sis_leg_backend.dominio.entrada import (
    Pulsacion,
    RespuestaEntrada,
    ResultadoPresencia,
    ResultadoTest,
)
from sis_leg_backend.dominio.estado import EstadoGlobal, EstadoOperativo
from sis_leg_backend.servicios.entrada import ServicioEntradaTecla
from sis_leg_backend.servicios.preparacion import ServicioPreparacion
from sis_leg_backend.servicios.serializacion import EjecutorMutaciones

pytestmark = pytest.mark.anyio

HORA_INICIO = datetime(2026, 8, 20, 15, 30, 45)


def leer_filas(ruta: Path) -> list[list[str]]:
    """Lee un archivo de auditoría respetando el formato institucional."""

    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.reader(archivo, delimiter=";"))


def contenido_toml_entrada(
    directorio_logs: Path,
    *,
    quorum: int = 7,
    duracion_test: int | float = 0.6,
) -> str:
    """Arma una configuración válida con los dos valores relevantes del WP."""

    return (
        TOML_CANONICO.replace(LINEA_LOGS, f'logs_dir = "{directorio_logs}"')
        .replace(LINEA_QUORUM, f"quorum = {quorum}")
        .replace(LINEA_TIMER_TEST_DISPOSITIVO, f"device_test_seconds = {duracion_test}")
    )


async def crear_contexto_entrada(
    tmp_path: Path,
    *,
    quorum: int = 7,
    duracion_test: int | float = 0.6,
    reloj_monotono: Callable[[], float] | None = None,
    fabrica_escritor: Callable[[Path, datetime], EscritorAuditoriaCsv] | None = None,
) -> tuple[EstadoOperativo, ServicioEntradaTecla]:
    """Prepara un recinto ficticio y devuelve estado/servicio ya listos.

    La preparación usa exactamente las interfaces públicas de WP-003 y WP-005.
    La fábrica opcional permite provocar fallos de ``fsync`` sin reemplazar el
    writer real ni introducir una vía de auditoría paralela.
    """

    ruta_configuracion = escribir_system_toml(
        tmp_path / "system.toml",
        contenido_toml_entrada(tmp_path / "logs", quorum=quorum, duracion_test=duracion_test),
    )
    ruta_padron = escribir_padron(tmp_path / "concejales.csv", filas_padron_valido())
    estado = EstadoOperativo()
    ejecutor = EjecutorMutaciones()
    fabrica = fabrica_escritor or partial(EscritorAuditoriaCsv, reloj=lambda: HORA_INICIO)
    servicio_preparacion = ServicioPreparacion(
        estado_operativo=estado,
        ejecutor_mutaciones=ejecutor,
        ruta_configuracion=ruta_configuracion,
        ruta_padron=ruta_padron,
        reloj=lambda: HORA_INICIO,
        fabrica_escritor=fabrica,
    )
    await servicio_preparacion.preparar_sala()

    servicio_entrada = ServicioEntradaTecla(
        estado_operativo=estado,
        ejecutor_mutaciones=ejecutor,
        reloj_monotono=reloj_monotono or (lambda: 0.0),
    )
    return estado, servicio_entrada


def filas_nivel_uno(estado: EstadoOperativo) -> list[list[str]]:
    """Devuelve filas del CSV L1, que contiene todos los niveles acumulados."""

    preparacion = estado.preparacion_activa
    assert preparacion is not None
    ruta = preparacion.escritor_auditoria.rutas[NivelAuditoria.L1]
    return leer_filas(ruta)


def resultado_presencia(respuesta: RespuestaEntrada) -> ResultadoPresencia:
    """Afirma y devuelve el resultado de una pulsación 9 para Pyright/tests."""

    assert isinstance(respuesta.resultado, ResultadoPresencia)
    return respuesta.resultado


def resultado_test(respuesta: RespuestaEntrada) -> ResultadoTest:
    """Afirma y devuelve el resultado de una pulsación 8 para Pyright/tests."""

    assert isinstance(respuesta.resultado, ResultadoTest)
    return respuesta.resultado


async def test_sin_preparar_rechaza_sin_crear_auditoria() -> None:
    """CA-007: SIN_PREPARAR no busca padrón ni escribe eventos."""

    estado = EstadoOperativo()
    servicio = ServicioEntradaTecla(estado, EjecutorMutaciones())

    respuesta = await servicio.procesar_pulsacion(Pulsacion("D-01", "9"))

    assert estado.estado_global is EstadoGlobal.SIN_PREPARAR
    assert respuesta.aceptada is False
    assert respuesta.motivo == "SIN_PREPARAR"
    assert respuesta.concejal is None
    assert respuesta.resultado is None


async def test_dispositivo_no_asignado_registra_rechazo_sin_mutar(
    tmp_path: Path,
) -> None:
    """Un identificador lógico ausente del padrón se rechaza con HTTP 200 lógico."""

    estado, servicio = await crear_contexto_entrada(tmp_path)

    respuesta = await servicio.procesar_pulsacion(Pulsacion("NO-ASIGNADO", "9"))

    assert respuesta.aceptada is False
    assert respuesta.motivo == "DISPOSITIVO_NO_ASIGNADO"
    assert respuesta.concejal is None
    assert respuesta.resultado is None
    assert filas_nivel_uno(estado)[-1][2:] == [
        "L2",
        "INPUT",
        "PULSACION_RECHAZADA",
        "Pulsación rechazada: tecla [9] del dispositivo [NO-ASIGNADO]; "
        "motivo=DISPOSITIVO_NO_ASIGNADO",
    ]
    preparacion = estado.preparacion_activa
    assert preparacion is not None
    assert not any(preparacion.presencias.values())


async def test_tecla_no_habilitada_identifica_concejal_sin_mutar(
    tmp_path: Path,
) -> None:
    """Durante PREPARANDO solo 8 y 9 tienen efecto funcional."""

    estado, servicio = await crear_contexto_entrada(tmp_path)

    respuesta = await servicio.procesar_pulsacion(Pulsacion("D-01", "1"))

    assert respuesta.aceptada is False
    assert respuesta.motivo == "TECLA_NO_HABILITADA"
    assert respuesta.concejal is not None
    assert respuesta.concejal.dni == "30000001"
    assert respuesta.resultado is None
    preparacion = estado.preparacion_activa
    assert preparacion is not None
    assert preparacion.presencias["30000001"] is False
    assert filas_nivel_uno(estado)[-1][4] == "PULSACION_RECHAZADA"


async def test_presencia_deriva_conteo_y_quorum_al_cruzar_el_umbral(
    tmp_path: Path,
) -> None:
    """CA-005: presencia y quórum se calculan desde el mapa actual."""

    estado, servicio = await crear_contexto_entrada(tmp_path, quorum=2)

    primera = await servicio.procesar_pulsacion(Pulsacion("D-01", "9"))
    segunda = await servicio.procesar_pulsacion(Pulsacion("D-02", "9"))
    tercera = await servicio.procesar_pulsacion(Pulsacion("D-03", "9"))
    retiro = await servicio.procesar_pulsacion(Pulsacion("D-03", "9"))
    retiro_final = await servicio.procesar_pulsacion(Pulsacion("D-02", "9"))

    resultado_primera = resultado_presencia(primera)
    resultado_segunda = resultado_presencia(segunda)
    resultado_tercera = resultado_presencia(tercera)
    resultado_retiro = resultado_presencia(retiro)
    resultado_retiro_final = resultado_presencia(retiro_final)
    assert resultado_primera.presentes == 1
    assert resultado_primera.quorum_alcanzado is False
    assert resultado_segunda.presentes == 2
    assert resultado_segunda.quorum_alcanzado is True
    assert resultado_tercera.presentes == 3
    assert resultado_tercera.quorum_alcanzado is True
    assert resultado_retiro.presentes == 2
    assert resultado_retiro.quorum_alcanzado is True
    assert resultado_retiro_final.presentes == 1
    assert resultado_retiro_final.quorum_alcanzado is False

    preparacion = estado.preparacion_activa
    assert preparacion is not None
    assert preparacion.cantidad_presentes() == 1
    assert preparacion.quorum_alcanzado() is False


async def test_test_visual_no_cambia_presencia_quorum_y_expira_por_reloj_controlado(
    tmp_path: Path,
) -> None:
    """CA-006: el test es temporal y no participa del estado de negocio."""

    tiempo = 10.0
    estado, servicio = await crear_contexto_entrada(
        tmp_path, quorum=1, reloj_monotono=lambda: tiempo
    )
    preparacion = estado.preparacion_activa
    assert preparacion is not None

    respuesta = await servicio.procesar_pulsacion(Pulsacion("D-01", "8"))

    assert respuesta.aceptada is True
    assert respuesta.motivo == "TEST_ACTIVADO"
    resultado = resultado_test(respuesta)
    assert resultado.activo is True
    assert resultado.duracion_segundos == 0.6
    assert preparacion.presencias["30000001"] is False
    assert preparacion.cantidad_presentes() == 0
    assert preparacion.quorum_alcanzado() is False
    assert preparacion.test_dispositivo_activo("30000001", 10.59) is True
    assert preparacion.test_dispositivo_activo("30000001", 10.6) is False


async def test_repetir_test_conserva_la_expiracion_mas_lejana(
    tmp_path: Path,
) -> None:
    """Una renovación no puede acortar una expiración ya posterior."""

    tiempo = 10.0
    estado, servicio = await crear_contexto_entrada(tmp_path, reloj_monotono=lambda: tiempo)
    preparacion = estado.preparacion_activa
    assert preparacion is not None

    await servicio.procesar_pulsacion(Pulsacion("D-01", "8"))
    expiracion_inicial = preparacion.expiraciones_test["30000001"]

    # Un reloj monotónico real no retrocede, pero esta llamada directa protege
    # la invariante del método frente a un valor posterior ya almacenado.
    preparacion.activar_test_dispositivo("30000001", 9.0)

    assert preparacion.expiraciones_test["30000001"] == expiracion_inicial


async def test_test_visual_es_independiente_por_concejal(tmp_path: Path) -> None:
    """Activar un test no crea indicadores compartidos entre bancas."""

    estado, servicio = await crear_contexto_entrada(tmp_path)
    preparacion = estado.preparacion_activa
    assert preparacion is not None

    await servicio.procesar_pulsacion(Pulsacion("D-01", "8"))

    assert preparacion.test_dispositivo_activo("30000001", 0.1) is True
    assert preparacion.test_dispositivo_activo("30000002", 0.1) is False


async def test_eventos_y_mensajes_de_entrada_respetan_orden_canonico(
    tmp_path: Path,
) -> None:
    """DEC-006: recibida precede al resultado en aceptación y rechazo."""

    estado, servicio = await crear_contexto_entrada(tmp_path)

    await servicio.procesar_pulsacion(Pulsacion("D-01", "9"))
    await servicio.procesar_pulsacion(Pulsacion("D-01", "8"))
    await servicio.procesar_pulsacion(Pulsacion("D-01", "1"))

    filas = filas_nivel_uno(estado)
    assert [fila[4] for fila in filas[1:]] == [
        "PREPARACION_INICIADA",
        "PULSACION_RECIBIDA",
        "CONCEJAL_PRESENTE",
        "PULSACION_RECIBIDA",
        "TEST_DISPOSITIVO_ACTIVADO",
        "PULSACION_RECIBIDA",
        "PULSACION_RECHAZADA",
    ]
    assert filas[2][2:] == [
        "L2",
        "INPUT",
        "PULSACION_RECIBIDA",
        "Pulsación recibida: tecla [9] del dispositivo [D-01]",
    ]
    assert filas[3][2:] == [
        "L3",
        "PRESENCIA",
        "CONCEJAL_PRESENTE",
        "Ana Garcia (banca Nro:1) se PRESENTÓ",
    ]
    assert filas[5][2:] == [
        "L2",
        "INPUT",
        "TEST_DISPOSITIVO_ACTIVADO",
        "Test de dispositivo activado: Ana Garcia (banca Nro:1); dispositivo=[D-01]",
    ]
    assert filas[7][5].endswith("motivo=TECLA_NO_HABILITADA")


def fabrica_con_fallo_en_fsync(
    numero_llamada: int,
) -> Callable[[Path, datetime], EscritorAuditoriaCsv]:
    """Devuelve un writer real cuyo fsync falla en una llamada elegida."""

    llamadas = 0

    def sincronizar(_descriptor: int) -> None:
        nonlocal llamadas
        llamadas += 1
        if llamadas == numero_llamada:
            raise OSError("fallo de disco simulado")

    return partial(EscritorAuditoriaCsv, reloj=lambda: HORA_INICIO, sincronizar=sincronizar)


async def test_fallo_al_persistir_pulsacion_recibida_no_muta(
    tmp_path: Path,
) -> None:
    """CA-055/DEC-006: si falla el primer evento no cambia presencia ni test."""

    estado, servicio = await crear_contexto_entrada(
        tmp_path, fabrica_escritor=fabrica_con_fallo_en_fsync(7)
    )

    with pytest.raises(ErrorAuditoria):
        await servicio.procesar_pulsacion(Pulsacion("D-01", "9"))

    preparacion = estado.preparacion_activa
    assert preparacion is not None
    assert preparacion.presencias["30000001"] is False
    assert preparacion.expiraciones_test == {}
    assert preparacion.escritor_auditoria.fallado is True


async def test_fallo_del_evento_funcional_conserva_la_primera_fila_y_no_muta(
    tmp_path: Path,
) -> None:
    """CA-055: un fallo posterior deja evidencia parcial sin confirmar el efecto."""

    estado, servicio = await crear_contexto_entrada(
        tmp_path, fabrica_escritor=fabrica_con_fallo_en_fsync(9)
    )

    with pytest.raises(ErrorAuditoria):
        await servicio.procesar_pulsacion(Pulsacion("D-01", "9"))

    preparacion = estado.preparacion_activa
    assert preparacion is not None
    assert preparacion.presencias["30000001"] is False
    filas = filas_nivel_uno(estado)
    # El writer puede haber alcanzado a escribir parcialmente el segundo evento
    # antes de que fsync falle; esa evidencia no se borra, pero el efecto no se
    # confirma en el estado operativo.
    assert any(fila[4] == "PULSACION_RECIBIDA" for fila in filas)

    with pytest.raises(ErrorEscritorNoDisponible):
        await servicio.procesar_pulsacion(Pulsacion("D-02", "9"))
    assert preparacion.presencias["30000002"] is False


async def test_pulsaciones_concurrentes_mismo_dispositivo_se_serializan(
    tmp_path: Path,
) -> None:
    """CA-058: dos teclas 9 producen dos resultados ordenados y estado final estable."""

    estado, servicio = await crear_contexto_entrada(tmp_path)

    respuestas = await asyncio.gather(
        servicio.procesar_pulsacion(Pulsacion("D-01", "9")),
        servicio.procesar_pulsacion(Pulsacion("D-01", "9")),
    )

    assert sorted(resultado_presencia(respuesta).presentes for respuesta in respuestas) == [0, 1]
    preparacion = estado.preparacion_activa
    assert preparacion is not None
    assert preparacion.presencias["30000001"] is False
    assert [fila[0] for fila in filas_nivel_uno(estado)[1:]] == [
        str(numero) for numero in range(1, 6)
    ]


async def test_pulsaciones_concurrentes_dispositivos_distintos_conservan_ambas(
    tmp_path: Path,
) -> None:
    """La exclusión única también mantiene coherente el conteo entre bancas."""

    estado, servicio = await crear_contexto_entrada(tmp_path)

    respuestas = await asyncio.gather(
        servicio.procesar_pulsacion(Pulsacion("D-01", "9")),
        servicio.procesar_pulsacion(Pulsacion("D-02", "9")),
    )

    assert all(respuesta.aceptada for respuesta in respuestas)
    assert sorted(resultado_presencia(respuesta).presentes for respuesta in respuestas) == [1, 2]
    preparacion = estado.preparacion_activa
    assert preparacion is not None
    assert preparacion.cantidad_presentes() == 2
