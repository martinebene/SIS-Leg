"""Auditoría de los períodos efectivos EN VIVO incorporada por WP-092.

Estas pruebas separan la orden humana de la transición real. Una cuenta
regresiva puede recibir ``TRANSMISION_INICIADA`` varios segundos antes de que
el reloj autoritativo habilite ``TRANSMISION_EN_VIVO_INICIO``; del mismo modo,
un stop de una cuenta regresiva no debe inventar un período que nunca existió.

Las carreras usan el temporizador real con un reloj manual. La espera inyectada
adelanta el reloj y ejecuta el comando competidor antes de quedar suspendida:
así se reproduce de forma determinista el caso de WP-081 en el que una mutación
despierta al ciclo mientras el callback temporal todavía no terminó.
"""

from __future__ import annotations

import asyncio
import csv
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from sis_leg_backend.auditoria import ErrorAuditoria, EscritorAuditoriaCsv, NivelAuditoria
from sis_leg_backend.dominio.estado import EstadoGlobal
from sis_leg_backend.servicios.acta_institucional import componer_acta
from sis_leg_backend.servicios.apoyo_tecnico import (
    CODIGO_TRANSMISION_DETENIDA,
    CODIGO_TRANSMISION_EN_VIVO_FIN,
    CODIGO_TRANSMISION_EN_VIVO_INICIO,
    CODIGO_TRANSMISION_INICIADA,
    ServicioApoyoTecnico,
)
from sis_leg_backend.servicios.fronteras_temporales import ServicioFronterasTemporales

from tests.backend.ayudas_proyecciones import (
    EntornoProyecciones,
    crear_entorno_proyecciones,
    crear_servicio_apoyo_tecnico,
)

pytestmark = pytest.mark.anyio


def codigos(entorno: EntornoProyecciones) -> list[str]:
    """Devuelve los códigos confirmados por el escritor de la preparación."""

    return [
        evento.codigo_evento for evento in entorno.contexto.escritor_auditoria.eventos_recientes
    ]


def cantidad(entorno: EntornoProyecciones, codigo: str) -> int:
    """Cuenta un código estable sin depender de timestamps o mensajes humanos."""

    return codigos(entorno).count(codigo)


async def ejecutar_carrera_en_deadline(
    entorno: EntornoProyecciones,
    servicio: ServicioApoyoTecnico,
    accion: Callable[[], Awaitable[None]],
) -> None:
    """Cruza una frontera mientras ``accion`` publica una revisión competidora.

    La primera espera adelanta exactamente hasta el deadline, ejecuta el comando
    y queda pendiente. Las siguientes esperas no adelantan tiempo: esto permite
    inspeccionar la intención de reemplazo sin cruzar también su futura frontera.
    """

    llamadas = 0

    async def esperar(demora: float) -> None:
        nonlocal llamadas
        llamadas += 1
        if llamadas == 1:
            entorno.reloj.avanzar(demora)
            await accion()
        await asyncio.Event().wait()

    fronteras = ServicioFronterasTemporales(
        entorno.servicio,
        entorno.ejecutor,
        entorno.coordinador,
        esperar=esperar,
        procesar_efectos_pendientes=servicio.procesar_efectos_temporales_pendientes,
        hay_efecto_pendiente=servicio.hay_efecto_temporal_pendiente,
    )
    tarea = asyncio.create_task(fronteras.ejecutar())
    try:
        for _ in range(30):
            await asyncio.sleep(0)
            if cantidad(entorno, CODIGO_TRANSMISION_EN_VIVO_FIN) == 1:
                break
    finally:
        tarea.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarea


async def test_inicio_inmediato_y_stop_auditan_hechos_l2_sin_tocar_l3_ni_acta(
    tmp_path: Path,
) -> None:
    """Los comandos se conservan y los dos hechos nuevos quedan sólo en L1/L2."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.iniciar_transmision(None)
    await servicio.detener_transmision()

    assert codigos(entorno) == [
        CODIGO_TRANSMISION_INICIADA,
        CODIGO_TRANSMISION_EN_VIVO_INICIO,
        CODIGO_TRANSMISION_DETENIDA,
        CODIGO_TRANSMISION_EN_VIVO_FIN,
    ]
    assert all(
        evento.nivel is NivelAuditoria.L2
        for evento in entorno.contexto.escritor_auditoria.eventos_recientes
    )

    rutas = entorno.contexto.escritor_auditoria.rutas
    for nivel in (NivelAuditoria.L1, NivelAuditoria.L2):
        with rutas[nivel].open(encoding="utf-8-sig", newline="") as archivo:
            codigos_csv = [fila["event_code"] for fila in csv.DictReader(archivo, delimiter=";")]
        assert CODIGO_TRANSMISION_EN_VIVO_INICIO in codigos_csv
        assert CODIGO_TRANSMISION_EN_VIVO_FIN in codigos_csv

    with rutas[NivelAuditoria.L3].open(encoding="utf-8-sig", newline="") as archivo:
        codigos_l3 = [fila["event_code"] for fila in csv.DictReader(archivo, delimiter=";")]
    assert CODIGO_TRANSMISION_EN_VIVO_INICIO not in codigos_l3
    assert CODIGO_TRANSMISION_EN_VIVO_FIN not in codigos_l3

    entorno.contexto.escritor_auditoria.cerrar()
    acta = componer_acta(rutas[NivelAuditoria.L3])
    assert CODIGO_TRANSMISION_EN_VIVO_INICIO not in acta
    assert CODIGO_TRANSMISION_EN_VIVO_FIN not in acta


async def test_countdown_audita_inicio_exactamente_al_cruzar_la_frontera(
    tmp_path: Path,
) -> None:
    """Antes del deadline no hay hecho; al cruzarlo el temporizador escribe uno."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")
    await servicio.iniciar_transmision(10)

    assert cantidad(entorno, CODIGO_TRANSMISION_EN_VIVO_INICIO) == 0

    async def esperar(demora: float) -> None:
        entorno.reloj.avanzar(demora)

    fronteras = ServicioFronterasTemporales(
        entorno.servicio,
        entorno.ejecutor,
        entorno.coordinador,
        esperar=esperar,
        procesar_efectos_pendientes=servicio.procesar_efectos_temporales_pendientes,
        hay_efecto_pendiente=servicio.hay_efecto_temporal_pendiente,
    )
    tarea = asyncio.create_task(fronteras.ejecutar())
    try:
        for _ in range(30):
            await asyncio.sleep(0)
            if cantidad(entorno, CODIGO_TRANSMISION_EN_VIVO_INICIO) == 1:
                break
    finally:
        tarea.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarea

    assert cantidad(entorno, CODIGO_TRANSMISION_EN_VIVO_INICIO) == 1
    assert entorno.estado.transmision_tecnica is not None
    assert entorno.estado.transmision_tecnica.inicio_en_vivo_procesado


async def test_stop_de_countdown_y_doble_stop_no_inventan_fin(tmp_path: Path) -> None:
    """Una intención que nunca llegó a EN VIVO no abre ni cierra un período."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")
    await servicio.iniciar_transmision(30)

    await servicio.detener_transmision()
    await servicio.detener_transmision()

    assert cantidad(entorno, CODIGO_TRANSMISION_DETENIDA) == 1
    assert cantidad(entorno, CODIGO_TRANSMISION_EN_VIVO_INICIO) == 0
    assert cantidad(entorno, CODIGO_TRANSMISION_EN_VIVO_FIN) == 0


async def test_deadline_y_stop_producen_un_solo_inicio_y_fin(tmp_path: Path) -> None:
    """Si stop gana la carrera, procesa el deadline bajo el mismo serializador."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")
    await servicio.iniciar_transmision(10)

    await ejecutar_carrera_en_deadline(entorno, servicio, servicio.detener_transmision)

    assert cantidad(entorno, CODIGO_TRANSMISION_EN_VIVO_INICIO) == 1
    assert cantidad(entorno, CODIGO_TRANSMISION_EN_VIVO_FIN) == 1
    assert entorno.estado.transmision_tecnica is None


async def test_deadline_y_reemplazo_por_countdown_cierran_solo_el_periodo_anterior(
    tmp_path: Path,
) -> None:
    """El nuevo countdown queda pendiente y no hereda la marca del anterior."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")
    await servicio.iniciar_transmision(10)

    await ejecutar_carrera_en_deadline(
        entorno,
        servicio,
        lambda: servicio.iniciar_transmision(20),
    )

    assert cantidad(entorno, CODIGO_TRANSMISION_EN_VIVO_INICIO) == 1
    assert cantidad(entorno, CODIGO_TRANSMISION_EN_VIVO_FIN) == 1
    assert entorno.estado.transmision_tecnica is not None
    assert not entorno.estado.transmision_tecnica.inicio_en_vivo_procesado


async def test_deadline_y_reemplazo_inmediato_ordenan_fin_antes_del_nuevo_inicio(
    tmp_path: Path,
) -> None:
    """El período anterior termina antes de abrir el inicio inmediato nuevo."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")
    await servicio.iniciar_transmision(10)

    await ejecutar_carrera_en_deadline(
        entorno,
        servicio,
        lambda: servicio.iniciar_transmision(None),
    )

    efectivos = [
        codigo
        for codigo in codigos(entorno)
        if codigo in (CODIGO_TRANSMISION_EN_VIVO_INICIO, CODIGO_TRANSMISION_EN_VIVO_FIN)
    ]
    assert efectivos == [
        CODIGO_TRANSMISION_EN_VIVO_INICIO,
        CODIGO_TRANSMISION_EN_VIVO_FIN,
        CODIGO_TRANSMISION_EN_VIVO_INICIO,
    ]


async def test_wakeups_repetidos_no_duplican_el_inicio(tmp_path: Path) -> None:
    """Una frontera ya procesada tolera publicaciones ajenas repetidas."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")
    await servicio.iniciar_transmision(5)
    entorno.reloj.avanzar(5)

    fronteras = ServicioFronterasTemporales(
        entorno.servicio,
        entorno.ejecutor,
        entorno.coordinador,
        procesar_efectos_pendientes=servicio.procesar_efectos_temporales_pendientes,
        hay_efecto_pendiente=servicio.hay_efecto_temporal_pendiente,
    )
    tarea = asyncio.create_task(fronteras.ejecutar())
    try:
        for _ in range(30):
            await asyncio.sleep(0)
            if cantidad(entorno, CODIGO_TRANSMISION_EN_VIVO_INICIO) == 1:
                break
        for _ in range(5):
            entorno.coordinador.publicar()
            await asyncio.sleep(0)
    finally:
        tarea.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarea

    assert cantidad(entorno, CODIGO_TRANSMISION_EN_VIVO_INICIO) == 1


async def test_fallo_de_auditoria_en_deadline_no_marca_inicio_ni_hace_busy_loop(
    tmp_path: Path,
) -> None:
    """El timer sobrevive al fallo y espera un cambio externo antes de reintentar."""

    fallo_activo = False

    def sincronizar(_descriptor: int) -> None:
        if fallo_activo:
            raise OSError("disco no disponible")

    entorno = crear_entorno_proyecciones(tmp_path)
    entorno.contexto.escritor_auditoria = EscritorAuditoriaCsv(
        tmp_path / "logs-fallo-transmision",
        entorno.reloj.ahora(),
        reloj=entorno.reloj.ahora,
        sincronizar=sincronizar,
    )
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")
    await servicio.iniciar_transmision(10)
    entorno.reloj.avanzar(10)
    fallo_activo = True
    intentos = 0

    async def procesar() -> None:
        nonlocal intentos
        intentos += 1
        if intentos > 4:
            raise RuntimeError("ciclo ocupado: se reintentó sin cambio externo")
        await servicio.procesar_efectos_temporales_pendientes()

    fronteras = ServicioFronterasTemporales(
        entorno.servicio,
        entorno.ejecutor,
        entorno.coordinador,
        procesar_efectos_pendientes=procesar,
        hay_efecto_pendiente=servicio.hay_efecto_temporal_pendiente,
    )
    tarea = asyncio.create_task(fronteras.ejecutar())
    try:
        for _ in range(50):
            await asyncio.sleep(0)
        seguia_viva = not tarea.done()
    finally:
        tarea.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarea

    assert seguia_viva
    assert intentos == 1
    assert cantidad(entorno, CODIGO_TRANSMISION_EN_VIVO_INICIO) == 0
    assert entorno.estado.transmision_tecnica is not None
    assert not entorno.estado.transmision_tecnica.inicio_en_vivo_procesado


async def test_deadline_sin_contexto_no_escribe_en_el_escritor_cerrado(
    tmp_path: Path,
) -> None:
    """Cerrar el contexto alrededor del deadline no genera replay ni escritura tardía."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")
    await servicio.iniciar_transmision(10)
    escritor_cerrado = entorno.contexto.escritor_auditoria
    escritor_cerrado.cerrar()
    entorno.estado.preparacion_activa = None
    entorno.estado.archivos_auditoria_activos = ()
    entorno.estado.estado_global = EstadoGlobal.SIN_PREPARAR
    entorno.reloj.avanzar(10)

    await servicio.procesar_efectos_temporales_pendientes()

    assert cantidad(entorno, CODIGO_TRANSMISION_EN_VIVO_INICIO) == 0
    assert escritor_cerrado.cerrado
    assert entorno.estado.transmision_tecnica is not None
    assert entorno.estado.transmision_tecnica.inicio_en_vivo_procesado
    assert not servicio.hay_efecto_temporal_pendiente()


async def test_fallo_directo_del_inicio_efectivo_deja_el_cruce_pendiente(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El servicio no marca un hecho que el escritor activo rechazó."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")
    await servicio.iniciar_transmision(10)
    entorno.reloj.avanzar(10)
    monkeypatch.setattr(entorno.contexto.escritor_auditoria, "_fallado", True)

    with pytest.raises(ErrorAuditoria):
        await servicio.procesar_efectos_temporales_pendientes()

    assert entorno.estado.transmision_tecnica is not None
    assert not entorno.estado.transmision_tecnica.inicio_en_vivo_procesado


async def test_fallo_del_hecho_inmediato_no_proyecta_en_vivo(tmp_path: Path) -> None:
    """AUDITAR -> MUTAR también rige cuando no existe cuenta regresiva."""

    llamadas = 0

    def sincronizar(_descriptor: int) -> None:
        nonlocal llamadas
        llamadas += 1
        # Tres encabezados, dos destinos L2 del comando y luego el primer
        # destino del INICIO efectivo, que es el punto que se fuerza a fallar.
        if llamadas == 6:
            raise OSError("disco no disponible")

    entorno = crear_entorno_proyecciones(tmp_path)
    entorno.contexto.escritor_auditoria = EscritorAuditoriaCsv(
        tmp_path / "logs-fallo-inmediato",
        entorno.reloj.ahora(),
        reloj=entorno.reloj.ahora,
        sincronizar=sincronizar,
    )
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    with pytest.raises(ErrorAuditoria):
        await servicio.iniciar_transmision(None)

    assert entorno.estado.transmision_tecnica is None
    assert codigos(entorno) == [CODIGO_TRANSMISION_INICIADA]
