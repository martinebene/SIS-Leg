"""Log principal INICIO/FIN de la transmisión EN VIVO (WP-096).

WP-092 ya dejaba en los archivos L1/L2 dos hechos técnicos por cada período de
transmisión. Estas pruebas cubren la capa que agrega WP-096: el panel de eventos
muestra por omisión el nivel "Principales (L3)", y allí la operación necesita ver
cuándo empezó y cuándo terminó realmente la transmisión.

La regla que se verifica una y otra vez es semántica, no estructural:

    exactamente una entrada principal por transición real del indicador.

"Real" significa observable por el público. Programar una cuenta regresiva no
enciende nada; cancelarla no apaga nada; reemplazar un EN VIVO por otro inicio
inmediato deja el indicador encendido todo el tiempo. Ninguno de esos casos debe
producir eventos principales, aunque sí muevan hechos técnicos L2.

Las carreras usan el temporizador real de fronteras con un reloj manual, igual
que ``test_transmision_auditoria_wp092.py``: la espera inyectada adelanta el
reloj y ejecuta el comando competidor antes de quedar suspendida.
"""

from __future__ import annotations

import asyncio
import csv
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from sis_leg_backend.auditoria import EscritorAuditoriaCsv, NivelAuditoria
from sis_leg_backend.dominio.estado import EstadoGlobal
from sis_leg_backend.servicios.acta_institucional import componer_acta
from sis_leg_backend.servicios.apoyo_tecnico import (
    CODIGO_TRANSMISION_DETENIDA,
    CODIGO_TRANSMISION_EN_VIVO_FIN,
    CODIGO_TRANSMISION_EN_VIVO_INICIO,
    CODIGO_TRANSMISION_INICIADA,
    CODIGO_TRANSMISION_PRINCIPAL_FIN,
    CODIGO_TRANSMISION_PRINCIPAL_INICIO,
    ETIQUETA_EVENTO_PRINCIPAL,
    MENSAJE_TRANSMISION_PRINCIPAL_FIN,
    MENSAJE_TRANSMISION_PRINCIPAL_INICIO,
    ServicioApoyoTecnico,
)
from sis_leg_backend.servicios.fronteras_temporales import ServicioFronterasTemporales

from tests.backend.ayudas_proyecciones import (
    EntornoProyecciones,
    crear_entorno_proyecciones,
    crear_servicio_apoyo_tecnico,
)

pytestmark = pytest.mark.anyio

CODIGOS_PRINCIPALES = (
    CODIGO_TRANSMISION_PRINCIPAL_INICIO,
    CODIGO_TRANSMISION_PRINCIPAL_FIN,
)


def codigos(entorno: EntornoProyecciones) -> list[str]:
    """Devuelve los códigos confirmados por el escritor de la preparación."""

    return [
        evento.codigo_evento for evento in entorno.contexto.escritor_auditoria.eventos_recientes
    ]


def principales(entorno: EntornoProyecciones) -> list[str]:
    """Aísla la secuencia de eventos principales de transmisión.

    Filtrar por código, y no por posición, es lo que permite afirmar el orden
    institucional exacto sin acoplarse a cuántos hechos técnicos haya en el medio.
    """

    return [codigo for codigo in codigos(entorno) if codigo in CODIGOS_PRINCIPALES]


def cantidad(entorno: EntornoProyecciones, codigo: str) -> int:
    """Cuenta un código estable sin depender de timestamps o mensajes humanos."""

    return codigos(entorno).count(codigo)


async def cruzar_frontera(
    entorno: EntornoProyecciones,
    servicio: ServicioApoyoTecnico,
    codigo_esperado: str,
    *,
    apariciones_esperadas: int = 1,
) -> None:
    """Deja que el temporizador único procese un deadline ya alcanzado.

    No se llama directamente a ``procesar_efectos_temporales_pendientes``: el
    objetivo es demostrar que el camino real de producción —el ciclo de fronteras
    temporales— produce el evento principal, y no sólo una ayuda de prueba.

    ``apariciones_esperadas`` es la cantidad total que debe haber en el registro
    al terminar. Contar el total, y no "al menos una", evita que una prueba con
    eventos previos crea haber cruzado la frontera sin haberlo hecho.
    """

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
            if cantidad(entorno, codigo_esperado) >= apariciones_esperadas:
                break
    finally:
        tarea.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarea


async def ejecutar_carrera_en_deadline(
    entorno: EntornoProyecciones,
    servicio: ServicioApoyoTecnico,
    accion: Callable[[], Awaitable[None]],
) -> None:
    """Cruza una frontera mientras ``accion`` publica una revisión competidora.

    La primera espera adelanta exactamente hasta el deadline, ejecuta el comando
    competidor y queda pendiente. Es el escenario determinista que WP-096 exige
    para la carrera countdown vs stop/reemplazo: sin él, el resultado dependería
    del orden en que asyncio despachara los callbacks.
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


# ===========================================================================
# 1. Transiciones simples
# ===========================================================================


async def test_inicio_inmediato_registra_exactamente_un_inicio_principal(
    tmp_path: Path,
) -> None:
    """Caso 1 del contrato: de apagado a EN VIVO, un único INICIO principal."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.iniciar_transmision(None)

    assert principales(entorno) == [CODIGO_TRANSMISION_PRINCIPAL_INICIO]
    principal = next(
        evento
        for evento in entorno.contexto.escritor_auditoria.eventos_recientes
        if evento.codigo_evento == CODIGO_TRANSMISION_PRINCIPAL_INICIO
    )
    # El evento pertenece al log principal y usa el lenguaje institucional del
    # resto de los hechos L3: sin banderas, identificadores ni horas internas.
    assert principal.nivel is NivelAuditoria.L3
    assert principal.etiqueta == ETIQUETA_EVENTO_PRINCIPAL
    assert principal.mensaje == MENSAJE_TRANSMISION_PRINCIPAL_INICIO
    assert entorno.estado.marcador_transmision_principal is not None


async def test_stop_desde_en_vivo_registra_exactamente_un_fin_principal(
    tmp_path: Path,
) -> None:
    """Caso 4 del contrato: de EN VIVO a apagado, un único FIN principal."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.iniciar_transmision(None)
    await servicio.detener_transmision()

    assert principales(entorno) == [
        CODIGO_TRANSMISION_PRINCIPAL_INICIO,
        CODIGO_TRANSMISION_PRINCIPAL_FIN,
    ]
    final = entorno.contexto.escritor_auditoria.eventos_recientes[-1]
    assert final.nivel is NivelAuditoria.L3
    assert final.etiqueta == ETIQUETA_EVENTO_PRINCIPAL
    assert final.mensaje == MENSAJE_TRANSMISION_PRINCIPAL_FIN
    assert entorno.estado.marcador_transmision_principal is None


async def test_countdown_registra_el_inicio_principal_recien_al_llegar_a_cero(
    tmp_path: Path,
) -> None:
    """Caso 2 del contrato: programar no anuncia; cruzar el deadline sí."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.iniciar_transmision(10)

    # La orden humana ya quedó registrada, pero el indicador todavía no encendió.
    assert cantidad(entorno, CODIGO_TRANSMISION_INICIADA) == 1
    assert principales(entorno) == []

    await cruzar_frontera(entorno, servicio, CODIGO_TRANSMISION_PRINCIPAL_INICIO)

    assert principales(entorno) == [CODIGO_TRANSMISION_PRINCIPAL_INICIO]


async def test_countdown_cancelado_no_registra_ningun_evento_principal(
    tmp_path: Path,
) -> None:
    """Caso 3 del contrato: una intención que nunca encendió no deja rastro principal."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.iniciar_transmision(30)
    await servicio.detener_transmision()

    assert cantidad(entorno, CODIGO_TRANSMISION_DETENIDA) == 1
    assert principales(entorno) == []
    assert entorno.estado.marcador_transmision_principal is None


# ===========================================================================
# 2. Idempotencia y reemplazos
# ===========================================================================


async def test_start_repetido_en_vivo_no_duplica_el_inicio_principal(
    tmp_path: Path,
) -> None:
    """Caso 5 del contrato: el indicador nunca se apagó, así que no hay transición.

    Cada reemplazo sí produce sus hechos técnicos L2 —esa intención terminó y otra
    empezó—, pero para el público la transmisión estuvo EN VIVO de forma continua.
    Un par FIN/INICIO principal acá sería exactamente el par espurio que el WP
    prohíbe.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.iniciar_transmision(None)
    await servicio.iniciar_transmision(None)
    await servicio.iniciar_transmision(None)

    assert principales(entorno) == [CODIGO_TRANSMISION_PRINCIPAL_INICIO]
    # La auditoría técnica de WP-092 conserva íntegro su propio contrato.
    assert cantidad(entorno, CODIGO_TRANSMISION_EN_VIVO_INICIO) == 3
    assert cantidad(entorno, CODIGO_TRANSMISION_EN_VIVO_FIN) == 2


async def test_stop_repetido_no_duplica_el_fin_principal(tmp_path: Path) -> None:
    """Caso 6 del contrato: detener lo ya detenido no vuelve a cerrar el período."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.iniciar_transmision(None)
    await servicio.detener_transmision()
    await servicio.detener_transmision()
    await servicio.detener_transmision()

    assert principales(entorno) == [
        CODIGO_TRANSMISION_PRINCIPAL_INICIO,
        CODIGO_TRANSMISION_PRINCIPAL_FIN,
    ]


async def test_reemplazo_de_countdown_por_countdown_no_produce_pares_espurios(
    tmp_path: Path,
) -> None:
    """Caso 7 del contrato: reprogramar antes de encender no anuncia nada."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.iniciar_transmision(30)
    await servicio.iniciar_transmision(45)
    await servicio.iniciar_transmision(20)

    assert principales(entorno) == []

    # Recién el countdown que efectivamente sobrevive hasta cero anuncia el inicio.
    await cruzar_frontera(entorno, servicio, CODIGO_TRANSMISION_PRINCIPAL_INICIO)

    assert principales(entorno) == [CODIGO_TRANSMISION_PRINCIPAL_INICIO]


async def test_reemplazar_una_transmision_en_vivo_por_countdown_cierra_el_periodo(
    tmp_path: Path,
) -> None:
    """Volver a una cuenta regresiva sí apaga el indicador y cierra el período.

    Es la contracara del reemplazo con continuidad: acá el público deja de ver
    EN VIVO mientras corre la nueva cuenta regresiva, y el log principal debe
    reflejar ese apagado y el encendido posterior por separado.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.iniciar_transmision(None)
    await servicio.iniciar_transmision(15)

    assert principales(entorno) == [
        CODIGO_TRANSMISION_PRINCIPAL_INICIO,
        CODIGO_TRANSMISION_PRINCIPAL_FIN,
    ]

    await cruzar_frontera(
        entorno,
        servicio,
        CODIGO_TRANSMISION_PRINCIPAL_INICIO,
        apariciones_esperadas=2,
    )

    assert principales(entorno) == [
        CODIGO_TRANSMISION_PRINCIPAL_INICIO,
        CODIGO_TRANSMISION_PRINCIPAL_FIN,
        CODIGO_TRANSMISION_PRINCIPAL_INICIO,
    ]


# ===========================================================================
# 3. Carreras temporales deterministas
# ===========================================================================


async def test_carrera_countdown_contra_stop_registra_un_inicio_y_un_fin(
    tmp_path: Path,
) -> None:
    """Caso 8 del contrato: el período existió realmente, aunque durase un instante.

    El stop llega en el mismo instante en que vence la cuenta regresiva. El
    serializador procesa primero el INICIO pendiente y después el cierre, de modo
    que el log principal muestra el par completo y no un FIN huérfano.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")
    await servicio.iniciar_transmision(10)

    await ejecutar_carrera_en_deadline(entorno, servicio, servicio.detener_transmision)

    assert principales(entorno) == [
        CODIGO_TRANSMISION_PRINCIPAL_INICIO,
        CODIGO_TRANSMISION_PRINCIPAL_FIN,
    ]
    assert entorno.estado.transmision_tecnica is None


async def test_carrera_countdown_contra_reemplazo_inmediato_no_duplica_el_inicio(
    tmp_path: Path,
) -> None:
    """Caso 8 del contrato en su variante con continuidad.

    El deadline y un inicio inmediato coinciden: el indicador se enciende y no
    vuelve a apagarse. Debe quedar un único INICIO principal y ningún FIN, aunque
    la auditoría técnica registre el cierre de la intención reemplazada.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")
    await servicio.iniciar_transmision(10)

    await ejecutar_carrera_en_deadline(
        entorno,
        servicio,
        lambda: servicio.iniciar_transmision(None),
    )

    assert principales(entorno) == [CODIGO_TRANSMISION_PRINCIPAL_INICIO]
    assert cantidad(entorno, CODIGO_TRANSMISION_EN_VIVO_FIN) == 1


async def test_carrera_countdown_contra_reemplazo_por_countdown_cierra_una_sola_vez(
    tmp_path: Path,
) -> None:
    """El período que alcanzó a existir se cierra exactamente una vez."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")
    await servicio.iniciar_transmision(10)

    await ejecutar_carrera_en_deadline(
        entorno,
        servicio,
        lambda: servicio.iniciar_transmision(20),
    )

    assert principales(entorno) == [
        CODIGO_TRANSMISION_PRINCIPAL_INICIO,
        CODIGO_TRANSMISION_PRINCIPAL_FIN,
    ]
    assert entorno.estado.marcador_transmision_principal is None


async def test_wakeups_repetidos_del_temporizador_no_reemiten_el_inicio(
    tmp_path: Path,
) -> None:
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
            if cantidad(entorno, CODIGO_TRANSMISION_PRINCIPAL_INICIO) == 1:
                break
        for _ in range(5):
            entorno.coordinador.publicar()
            await asyncio.sleep(0)
    finally:
        tarea.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarea

    assert principales(entorno) == [CODIGO_TRANSMISION_PRINCIPAL_INICIO]


# ===========================================================================
# 4. Proyección, reconstrucción y frontera de conjuntos
# ===========================================================================


async def test_el_evento_principal_es_visible_en_la_proyeccion_que_consume_moderacion(
    tmp_path: Path,
) -> None:
    """Caso 11 del contrato: el hecho llega a la API/SSE con el nivel L3.

    El panel de eventos filtra por nivel acumulativo y arranca en "Principales
    (L3)". Verificar el nivel proyectado es lo que demuestra que el operador va a
    ver el hecho sin cambiar de filtro.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.iniciar_transmision(None)
    await servicio.detener_transmision()

    estado = await entorno.servicio.obtener_estado_moderacion()
    proyectados = [
        (evento.nivel, evento.etiqueta, evento.codigo_evento, evento.mensaje)
        for evento in estado.eventos_recientes
        if evento.codigo_evento in CODIGOS_PRINCIPALES
    ]
    assert proyectados == [
        (
            "L3",
            ETIQUETA_EVENTO_PRINCIPAL,
            CODIGO_TRANSMISION_PRINCIPAL_INICIO,
            MENSAJE_TRANSMISION_PRINCIPAL_INICIO,
        ),
        (
            "L3",
            ETIQUETA_EVENTO_PRINCIPAL,
            CODIGO_TRANSMISION_PRINCIPAL_FIN,
            MENSAJE_TRANSMISION_PRINCIPAL_FIN,
        ),
    ]

    # Apoyo Técnico consume la misma franja de eventos, sin variante propia.
    estado_tecnico = await entorno.servicio.obtener_estado_tecnico()
    assert [evento.codigo_evento for evento in estado_tecnico.eventos_recientes] == [
        evento.codigo_evento for evento in estado.eventos_recientes
    ]


async def test_reconstruir_la_proyeccion_no_reemite_eventos_historicos(
    tmp_path: Path,
) -> None:
    """Caso 9 del contrato: proyectar es leer, nunca volver a auditar.

    Se reconstruyen los tres DTO varias veces y se publica el coordinador como lo
    haría cualquier mutación ajena. La cantidad de filas durables no puede moverse.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.iniciar_transmision(None)
    filas_antes = len(entorno.contexto.escritor_auditoria.eventos_recientes)

    for _ in range(5):
        await entorno.servicio.obtener_estado_moderacion()
        await entorno.servicio.obtener_estado_recinto()
        await entorno.servicio.obtener_estado_tecnico()
        entorno.coordinador.publicar()

    assert len(entorno.contexto.escritor_auditoria.eventos_recientes) == filas_antes
    assert principales(entorno) == [CODIGO_TRANSMISION_PRINCIPAL_INICIO]


async def test_el_evento_principal_no_se_publica_en_la_pantalla_del_recinto(
    tmp_path: Path,
) -> None:
    """La franja pública sigue siendo una allowlist explícita.

    WP-096 pide visibilidad en el log principal de operación, no una tarjeta más
    en la pantalla que ve el público. La proyección pública sólo publica los
    códigos que declara ``MAPEO_EVENTOS_PUBLICOS``, así que este hecho nuevo no
    aparece por arrastre.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.iniciar_transmision(None)
    await servicio.detener_transmision()

    estado = await entorno.servicio.obtener_estado_recinto()
    publicados = [evento.codigo_evento for evento in estado.eventos_publicos]
    assert CODIGO_TRANSMISION_PRINCIPAL_INICIO not in publicados
    assert CODIGO_TRANSMISION_PRINCIPAL_FIN not in publicados


async def test_sin_preparar_no_registra_ni_reconstruye_el_inicio_mas_tarde(
    tmp_path: Path,
) -> None:
    """Un encendido sin auditoría abierta no pertenece a ninguna sesión.

    El indicador funciona igual en ``SIN_PREPARAR``, pero sin conjunto de CSV no
    hay hecho institucional. Abrir una preparación después no puede inventar un
    INICIO histórico, y el stop posterior tampoco puede escribir un FIN huérfano
    en archivos que nunca vieron empezar esa transmisión.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    escritor_original = entorno.contexto.escritor_auditoria
    entorno.estado.preparacion_activa = None
    entorno.estado.archivos_auditoria_activos = ()
    entorno.estado.estado_global = EstadoGlobal.SIN_PREPARAR
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.iniciar_transmision(None)

    assert entorno.estado.marcador_transmision_principal is None

    # La preparación vuelve a abrirse con el mismo conjunto de archivos.
    entorno.estado.preparacion_activa = entorno.contexto
    entorno.estado.estado_global = EstadoGlobal.PREPARANDO
    entorno.estado.archivos_auditoria_activos = entorno.contexto.rutas_auditoria()

    await servicio.detener_transmision()

    assert principales(entorno) == []
    # El conjunto reabierto sí conserva la auditoría técnica del stop: lo que no
    # puede aparecer es el par institucional de un encendido que nunca registró.
    assert codigos(entorno) == [
        CODIGO_TRANSMISION_DETENIDA,
        CODIGO_TRANSMISION_EN_VIVO_FIN,
    ]
    assert escritor_original is entorno.contexto.escritor_auditoria


async def test_un_conjunto_cerrado_no_recibe_el_fin_de_un_periodo_ajeno(
    tmp_path: Path,
) -> None:
    """El FIN pertenece al conjunto de CSV que vio el INICIO.

    La transmisión es independiente del ciclo preparación/sesión y puede seguir
    encendida cuando ese ciclo termina. Escribir su cierre en el conjunto
    siguiente sería un registro falso: ese conjunto nunca vio el encendido.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")
    await servicio.iniciar_transmision(None)
    assert principales(entorno) == [CODIGO_TRANSMISION_PRINCIPAL_INICIO]

    # Termina la preparación original y arranca otra, con su propio escritor.
    entorno.contexto.escritor_auditoria.cerrar()
    entorno.contexto.escritor_auditoria = EscritorAuditoriaCsv(
        tmp_path / "logs-siguiente",
        entorno.reloj.ahora(),
        reloj=entorno.reloj.ahora,
        sincronizar=lambda _descriptor: None,
    )

    await servicio.detener_transmision()

    assert principales(entorno) == []
    assert entorno.estado.marcador_transmision_principal is None


# ===========================================================================
# 5. Registro durable y acta institucional
# ===========================================================================


async def test_los_eventos_principales_llegan_a_los_tres_csv_y_conservan_los_l2(
    tmp_path: Path,
) -> None:
    """Caso 10 del contrato: la auditoría técnica L2 sigue intacta.

    Los niveles son acumulativos: un hecho L3 aparece en L1, L2 y L3, mientras
    que los hechos técnicos de WP-092 siguen apareciendo sólo en L1 y L2.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.iniciar_transmision(None)
    await servicio.detener_transmision()

    rutas = entorno.contexto.escritor_auditoria.rutas
    por_nivel: dict[NivelAuditoria, list[str]] = {}
    for nivel, ruta in rutas.items():
        with ruta.open(encoding="utf-8-sig", newline="") as archivo:
            por_nivel[nivel] = [
                fila["event_code"] for fila in csv.DictReader(archivo, delimiter=";")
            ]

    for nivel in (NivelAuditoria.L1, NivelAuditoria.L2, NivelAuditoria.L3):
        assert por_nivel[nivel].count(CODIGO_TRANSMISION_PRINCIPAL_INICIO) == 1
        assert por_nivel[nivel].count(CODIGO_TRANSMISION_PRINCIPAL_FIN) == 1

    for nivel in (NivelAuditoria.L1, NivelAuditoria.L2):
        assert por_nivel[nivel].count(CODIGO_TRANSMISION_INICIADA) == 1
        assert por_nivel[nivel].count(CODIGO_TRANSMISION_DETENIDA) == 1
        assert por_nivel[nivel].count(CODIGO_TRANSMISION_EN_VIVO_INICIO) == 1
        assert por_nivel[nivel].count(CODIGO_TRANSMISION_EN_VIVO_FIN) == 1

    assert CODIGO_TRANSMISION_EN_VIVO_INICIO not in por_nivel[NivelAuditoria.L3]
    assert CODIGO_TRANSMISION_EN_VIVO_FIN not in por_nivel[NivelAuditoria.L3]


async def test_el_acta_institucional_redacta_las_dos_frases_sin_metadata(
    tmp_path: Path,
) -> None:
    """El acta deriva del L3, así que ahora incluye la transmisión.

    Se verifica que las líneas sean exactamente las frases institucionales: sin
    códigos, sin etiquetas y sin la causa técnica del cierre.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.iniciar_transmision(None)
    await servicio.detener_transmision()

    rutas = entorno.contexto.escritor_auditoria.rutas
    entorno.contexto.escritor_auditoria.cerrar()
    acta = componer_acta(rutas[NivelAuditoria.L3])

    assert MENSAJE_TRANSMISION_PRINCIPAL_INICIO in acta
    assert MENSAJE_TRANSMISION_PRINCIPAL_FIN in acta
    for metadato in (
        CODIGO_TRANSMISION_PRINCIPAL_INICIO,
        CODIGO_TRANSMISION_PRINCIPAL_FIN,
        ETIQUETA_EVENTO_PRINCIPAL,
        "causa=",
        "L3",
    ):
        assert metadato not in acta


async def test_los_eventos_principales_no_registran_votos_ni_datos_de_dispositivo(
    tmp_path: Path,
) -> None:
    """Invariante de seguridad del WP: el hecho institucional no lleva datos sensibles.

    El mensaje es una frase fija, así que la comprobación es directa: ningún
    fragmento del mensaje puede contener identidad, DNI, banca, tecla ni
    fingerprint del dispositivo.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.iniciar_transmision(None)
    await servicio.detener_transmision()

    mensajes = [
        evento.mensaje
        for evento in entorno.contexto.escritor_auditoria.eventos_recientes
        if evento.codigo_evento in CODIGOS_PRINCIPALES
    ]
    assert mensajes == [
        MENSAJE_TRANSMISION_PRINCIPAL_INICIO,
        MENSAJE_TRANSMISION_PRINCIPAL_FIN,
    ]
    for concejal in entorno.contexto.padron.concejales:
        for mensaje in mensajes:
            assert concejal.dni not in mensaje
            assert concejal.apellido not in mensaje
            assert concejal.dispositivo_votacion not in mensaje
