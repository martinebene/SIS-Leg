"""Marcadores de sesión INICIO/FIN de los mensajes al Recinto (WP-078).

Un aviso que Apoyo Técnico publica hacia la Pantalla del Recinto no es sólo un
mensaje técnico: sirve para marcar un momento de la sesión ("acá empezó el
cuarto intermedio"). Por eso cada período en que ese texto está a la vista queda
delimitado por dos eventos principales ``L3`` con etiqueta general ``EVENTO``:
``INICIO`` al aparecer y ``FIN`` al dejar de mostrarse, siempre con el texto
exacto y el horario del escritor institucional.

Las pruebas están agrupadas por la pregunta que responden:

1. **Semántica**: qué destinos generan marcador y con qué contenido exacto.
2. **Cierre**: los cuatro caminos por los que un período termina, y la
   idempotencia que impide un segundo ``FIN``.
3. **Persistencia**: seis columnas y jerarquía acumulativa intactas.
4. **Proyección**: visible como principal en Moderación y Técnico, invisible
   como evento público del Recinto.
5. **Fronteras y fallos**: el temporizador cierra sin polling y la política de
   fallo cerrado de la auditoría se conserva.

Como el resto de la suite del plano técnico, el tiempo se controla con el
``RelojManual`` compartido: ninguna prueba espera segundos reales.
"""

from __future__ import annotations

import asyncio
import csv
from datetime import datetime
from pathlib import Path

import pytest
from botonera2_backend.auditoria import (
    ENCABEZADO_CSV,
    ErrorAuditoria,
    EscritorAuditoriaCsv,
    NivelAuditoria,
)
from botonera2_backend.dominio.apoyo_tecnico import DestinoAvisoTecnico
from botonera2_backend.dominio.estado import EstadoGlobal
from botonera2_backend.servicios.apoyo_tecnico import (
    CODIGO_MARCADOR_FIN,
    CODIGO_MARCADOR_INICIO,
    ETIQUETA_EVENTO_PRINCIPAL,
    ServicioApoyoTecnico,
)
from botonera2_backend.servicios.fronteras_temporales import ServicioFronterasTemporales

from tests.backend.ayudas_proyecciones import (
    EntornoProyecciones,
    abrir_sesion_prueba,
    crear_entorno_proyecciones,
    crear_servicio_apoyo_tecnico,
)

pytestmark = pytest.mark.anyio


def marcadores(entorno: EntornoProyecciones) -> list[tuple[str, str, str, str]]:
    """Extrae sólo los marcadores de sesión ya confirmados por la auditoría.

    Devuelve ``(nivel, etiqueta, codigo, mensaje)`` para poder afirmar de una
    sola vez las cuatro dimensiones que el WP fija, sin depender del ``seq`` ni
    del timestamp, que varían con el orden de la prueba.
    """

    return [
        (evento.nivel.value, evento.etiqueta, evento.codigo_evento, evento.mensaje)
        for evento in entorno.contexto.escritor_auditoria.eventos_recientes
        if evento.codigo_evento in (CODIGO_MARCADOR_INICIO, CODIGO_MARCADOR_FIN)
    ]


def transiciones(entorno: EntornoProyecciones) -> list[tuple[str, str]]:
    """Reduce los marcadores a ``(codigo, texto)`` para verificar el orden."""

    return [(codigo, mensaje) for _nivel, _etiqueta, codigo, mensaje in marcadores(entorno)]


# =============================================================================
# 1. Semántica del marcador
# =============================================================================


async def test_destino_recinto_registra_un_unico_inicio_exacto(tmp_path: Path) -> None:
    """CA: publicar ``RECINTO`` con texto ``X`` deja un ``L3 [EVENTO] INICIO X``.

    Es el criterio central del WP: nivel principal, etiqueta general y mensaje
    idéntico al que ve el recinto, sin prefijos, destino ni duración.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.publicar_aviso("Cuarto intermedio", DestinoAvisoTecnico.RECINTO, None)

    assert marcadores(entorno) == [("L3", "EVENTO", "INICIO", "Cuarto intermedio")]


async def test_destino_ambos_registra_un_solo_inicio_y_no_dos(tmp_path: Path) -> None:
    """CA: ``AMBOS`` alcanza dos ranuras pero una sola presencia en Recinto.

    La ranura de Moderación no es una pantalla pública, así que no delimita un
    momento de la sesión: duplicar el marcador convertiría un mismo hecho en dos.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.publicar_aviso("Se reanuda la sesión", DestinoAvisoTecnico.AMBOS, None)

    assert transiciones(entorno) == [("INICIO", "Se reanuda la sesión")]


async def test_destino_moderacion_no_registra_marcador(tmp_path: Path) -> None:
    """CA: un mensaje interno para Moderación no es un momento de la sesión."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.publicar_aviso("Revisar micrófono 3", DestinoAvisoTecnico.MODERACION, 60)
    await servicio.cancelar_aviso(DestinoAvisoTecnico.MODERACION)

    assert transiciones(entorno) == []
    assert entorno.estado.marcador_recinto_abierto is None


async def test_la_etiqueta_no_identifica_al_puesto_tecnico(tmp_path: Path) -> None:
    """CA: el marcador se presenta como evento general, no como apoyo técnico.

    La decisión humana es normativa: quien lee el registro institucional debe
    ver un momento de la sesión, no la mensajería del operador. La fila técnica
    ``L2`` sigue existiendo aparte para diagnóstico.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.publicar_aviso("Inicia el homenaje", DestinoAvisoTecnico.RECINTO, None)

    etiquetas = {
        evento.etiqueta
        for evento in entorno.contexto.escritor_auditoria.eventos_recientes
        if evento.nivel is NivelAuditoria.L3
    }
    assert etiquetas == {ETIQUETA_EVENTO_PRINCIPAL}
    assert "APOYO_TECNICO" not in etiquetas


async def test_sin_preparar_no_registra_ni_deja_periodo_abierto(tmp_path: Path) -> None:
    """Se preserva el invariante: sin auditoría abierta no se inventan eventos.

    Y, sobre todo, tampoco queda un período abierto que una preparación futura
    pudiera cerrar con un ``FIN`` huérfano en archivos que nunca vieron su
    ``INICIO``.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    entorno.estado.preparacion_activa = None
    entorno.estado.estado_global = EstadoGlobal.SIN_PREPARAR
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.publicar_aviso("Prueba previa", DestinoAvisoTecnico.RECINTO, None)

    assert entorno.estado.marcador_recinto_abierto is None
    assert entorno.contexto.escritor_auditoria.eventos_recientes == ()

    # Con la preparación ya activa, cancelar ese aviso no puede fabricar un FIN.
    entorno.estado.preparacion_activa = entorno.contexto
    entorno.estado.estado_global = EstadoGlobal.PREPARANDO
    await servicio.cancelar_aviso(DestinoAvisoTecnico.RECINTO)

    assert transiciones(entorno) == []


# =============================================================================
# 2. Cierre del período e idempotencia
# =============================================================================


async def test_cancelar_recinto_cierra_con_el_mismo_texto(tmp_path: Path) -> None:
    """CA: cancelar la ranura Recinto produce exactamente un ``FIN`` idéntico."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.publicar_aviso("Cuarto intermedio", DestinoAvisoTecnico.RECINTO, None)
    await servicio.cancelar_aviso(DestinoAvisoTecnico.RECINTO)

    assert transiciones(entorno) == [
        ("INICIO", "Cuarto intermedio"),
        ("FIN", "Cuarto intermedio"),
    ]
    assert entorno.estado.marcador_recinto_abierto is None


async def test_cancelar_solo_moderacion_de_un_ambos_no_cierra_recinto(tmp_path: Path) -> None:
    """CA: mientras el texto siga visible en Recinto, el período sigue abierto.

    Es el caso que obliga a razonar con la ranura autoritativa y no con el
    aviso: el mismo ``aviso_id`` vive en las dos ranuras y una de ellas se
    vació, pero la pantalla pública sigue mostrando el texto.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.publicar_aviso("Sesión suspendida", DestinoAvisoTecnico.AMBOS, None)
    await servicio.cancelar_aviso(DestinoAvisoTecnico.MODERACION)

    assert transiciones(entorno) == [("INICIO", "Sesión suspendida")]
    assert entorno.estado.aviso_tecnico_moderacion is None
    assert entorno.estado.aviso_tecnico_recinto is not None
    assert entorno.estado.marcador_recinto_abierto is not None

    # Recién cuando se retira de la pantalla pública se cierra el período.
    await servicio.cancelar_aviso(DestinoAvisoTecnico.RECINTO)
    assert transiciones(entorno) == [
        ("INICIO", "Sesión suspendida"),
        ("FIN", "Sesión suspendida"),
    ]


async def test_reemplazo_cierra_el_anterior_antes_de_abrir_el_nuevo(tmp_path: Path) -> None:
    """CA: ``FIN`` de A precede al ``INICIO`` de B dentro de la misma mutación.

    El orden importa institucionalmente: un lector del CSV no debe encontrar dos
    períodos solapados para una única ranura física.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.publicar_aviso("Texto A", DestinoAvisoTecnico.RECINTO, None)
    await servicio.publicar_aviso("Texto B", DestinoAvisoTecnico.AMBOS, None)

    assert transiciones(entorno) == [
        ("INICIO", "Texto A"),
        ("FIN", "Texto A"),
        ("INICIO", "Texto B"),
    ]
    marcador = entorno.estado.marcador_recinto_abierto
    assert marcador is not None
    assert marcador.texto == "Texto B"


async def test_expiracion_automatica_cierra_una_sola_vez(tmp_path: Path) -> None:
    """CA: el vencimiento por duración produce ``FIN`` sin acción del operador.

    Y repetir el barrido del temporizador no puede agregar un segundo cierre:
    el período ya no está abierto.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.publicar_aviso("Aviso breve", DestinoAvisoTecnico.RECINTO, 30)

    # Un segundo antes de la frontera todavía no hay nada que cerrar.
    entorno.reloj.avanzar(29)
    await servicio.cerrar_marcadores_recinto_vencidos()
    assert transiciones(entorno) == [("INICIO", "Aviso breve")]

    entorno.reloj.avanzar(1)
    await servicio.cerrar_marcadores_recinto_vencidos()
    await servicio.cerrar_marcadores_recinto_vencidos()

    assert transiciones(entorno) == [
        ("INICIO", "Aviso breve"),
        ("FIN", "Aviso breve"),
    ]


async def test_carrera_entre_expiracion_y_cancelacion_no_duplica_el_fin(tmp_path: Path) -> None:
    """CA: timer y cancelación manual coincidiendo producen un único ``FIN``.

    Ambos caminos pasan por el mismo helper de cierre y ambos corren bajo el
    ejecutor único, así que el segundo en obtener el lock ya no encuentra
    período abierto. Se prueban los dos órdenes posibles.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.publicar_aviso("Primero", DestinoAvisoTecnico.RECINTO, 10)
    entorno.reloj.avanzar(10)
    await asyncio.gather(
        servicio.cerrar_marcadores_recinto_vencidos(),
        servicio.cancelar_aviso(DestinoAvisoTecnico.RECINTO),
    )

    await servicio.publicar_aviso("Segundo", DestinoAvisoTecnico.RECINTO, 10)
    entorno.reloj.avanzar(10)
    await asyncio.gather(
        servicio.cancelar_aviso(DestinoAvisoTecnico.RECINTO),
        servicio.cerrar_marcadores_recinto_vencidos(),
    )

    assert transiciones(entorno) == [
        ("INICIO", "Primero"),
        ("FIN", "Primero"),
        ("INICIO", "Segundo"),
        ("FIN", "Segundo"),
    ]


async def test_cancelacion_posterior_al_vencimiento_es_idempotente(tmp_path: Path) -> None:
    """CA: cancelar algo ya cerrado no agrega un segundo ``FIN``.

    Sigue registrando la fila técnica ``L2`` de la orden, porque el operador
    efectivamente ejecutó un comando sobre una ranura ocupada.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.publicar_aviso("Ya vencido", DestinoAvisoTecnico.RECINTO, 5)
    entorno.reloj.avanzar(5)
    await servicio.cerrar_marcadores_recinto_vencidos()

    await servicio.cancelar_aviso(DestinoAvisoTecnico.RECINTO)
    await servicio.cancelar_aviso(DestinoAvisoTecnico.RECINTO)

    assert transiciones(entorno) == [
        ("INICIO", "Ya vencido"),
        ("FIN", "Ya vencido"),
    ]


async def test_un_periodo_de_otra_sesion_no_se_cierra_en_el_conjunto_nuevo(
    tmp_path: Path,
) -> None:
    """El ``FIN`` nunca se escribe en archivos que no vieron su ``INICIO``.

    Si la preparación/sesión terminó, su conjunto de CSV quedó cerrado. El
    marcador huérfano se descarta en silencio en vez de contaminar el conjunto
    siguiente con una transición que allí no ocurrió.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")
    await servicio.publicar_aviso("De la sesión anterior", DestinoAvisoTecnico.RECINTO, None)

    escritor_anterior = entorno.contexto.escritor_auditoria
    escritor_nuevo = EscritorAuditoriaCsv(
        tmp_path / "logs-nuevos",
        entorno.reloj.ahora(),
        reloj=entorno.reloj.ahora,
        sincronizar=lambda _descriptor: None,
    )
    entorno.contexto.escritor_auditoria = escritor_nuevo

    await servicio.cancelar_aviso(DestinoAvisoTecnico.RECINTO)

    assert entorno.estado.marcador_recinto_abierto is None
    assert [evento.codigo_evento for evento in escritor_nuevo.eventos_recientes] == [
        "AVISO_TECNICO_CANCELADO"
    ]
    assert [evento.codigo_evento for evento in escritor_anterior.eventos_recientes] == [
        "AVISO_TECNICO_PUBLICADO",
        "INICIO",
    ]
    escritor_nuevo.cerrar()


# =============================================================================
# 3. Persistencia institucional
# =============================================================================


async def test_los_marcadores_conservan_las_seis_columnas_y_la_jerarquia(
    tmp_path: Path,
) -> None:
    """CA: el CSV no cambia de forma y ``L3`` aparece en los tres archivos.

    La jerarquía es acumulativa, así que un evento principal debe estar en L1,
    L2 y L3. Se verifica leyendo los archivos reales, no el buffer en memoria.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.publicar_aviso("Homenaje en curso", DestinoAvisoTecnico.RECINTO, None)
    await servicio.cancelar_aviso(DestinoAvisoTecnico.RECINTO)

    for ruta in entorno.contexto.rutas_auditoria():
        with ruta.open(encoding="utf-8-sig", newline="") as archivo:
            filas = list(csv.reader(archivo, delimiter=";"))
        assert filas[0] == list(ENCABEZADO_CSV)
        assert all(len(fila) == 6 for fila in filas)
        principales = [fila for fila in filas[1:] if fila[2] == "L3"]
        assert [(fila[3], fila[4], fila[5]) for fila in principales] == [
            ("EVENTO", "INICIO", "Homenaje en curso"),
            ("EVENTO", "FIN", "Homenaje en curso"),
        ]
        # El timestamp lo genera el escritor institucional con su formato canónico.
        for fila in principales:
            datetime.strptime(fila[1], "%Y-%m-%d %H:%M:%S")  # noqa: DTZ007


# =============================================================================
# 4. Proyecciones
# =============================================================================


async def test_los_marcadores_son_principales_en_moderacion_y_tecnico(
    tmp_path: Path,
) -> None:
    """CA: aparecen bajo el filtro ``Principales (L3)`` de las dos interfaces.

    Ambos frontends filtran por nivel, así que basta con que el evento llegue
    proyectado como ``L3`` con su texto original para que el operador pueda
    reconstruir el momento de la sesión.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    abrir_sesion_prueba(entorno)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.publicar_aviso("Se pasa a cuarto intermedio", DestinoAvisoTecnico.AMBOS, None)
    await servicio.cancelar_aviso(DestinoAvisoTecnico.AMBOS)

    moderacion = await entorno.servicio.obtener_estado_moderacion()
    tecnico = await entorno.servicio.obtener_estado_tecnico()

    esperado = [
        ("L3", "EVENTO", "INICIO", "Se pasa a cuarto intermedio"),
        ("L3", "EVENTO", "FIN", "Se pasa a cuarto intermedio"),
    ]
    for proyeccion in (moderacion, tecnico):
        principales = [
            (evento.nivel, evento.etiqueta, evento.codigo_evento, evento.mensaje)
            for evento in proyeccion.eventos_recientes
            if evento.nivel == "L3"
        ]
        assert principales == esperado


async def test_los_marcadores_no_llegan_a_la_franja_publica_del_recinto(
    tmp_path: Path,
) -> None:
    """CA: la allowlist pública no incorpora estos códigos.

    El Recinto ya está mostrando el texto en su propia ranura de aviso; volver a
    publicarlo como tarjeta de evento sería una segunda aparición del mismo
    hecho, expresamente fuera de alcance.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    abrir_sesion_prueba(entorno)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.publicar_aviso("Vuelve la transmisión", DestinoAvisoTecnico.RECINTO, None)
    await servicio.cancelar_aviso(DestinoAvisoTecnico.RECINTO)

    recinto = await entorno.servicio.obtener_estado_recinto()
    assert recinto.eventos_publicos == ()


# =============================================================================
# 5. Frontera temporal y fallo cerrado
# =============================================================================


async def test_el_temporizador_registra_el_fin_al_cruzar_la_frontera(tmp_path: Path) -> None:
    """El cierre automático llega por el temporizador único, sin polling.

    La prueba ejecuta el servicio real de fronteras con una espera inyectada que
    se limita a adelantar el reloj manual. Así se demuestra el camino completo:
    el temporizador calcula la frontera del aviso, la cruza y convierte el
    vencimiento en un hecho institucional durable.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")
    await servicio.publicar_aviso("Intervalo técnico", DestinoAvisoTecnico.RECINTO, 45)

    async def esperar(demora: float) -> None:
        entorno.reloj.avanzar(demora)

    fronteras = ServicioFronterasTemporales(
        entorno.servicio,
        entorno.ejecutor,
        entorno.coordinador,
        esperar=esperar,
        cerrar_marcadores_vencidos=servicio.cerrar_marcadores_recinto_vencidos,
    )
    tarea = asyncio.create_task(fronteras.ejecutar())
    try:
        # El temporizador queda esperando una revisión nueva en cuanto no hay
        # más fronteras pendientes; ceder el control unas pocas veces alcanza.
        for _ in range(20):
            await asyncio.sleep(0)
            if ("FIN", "Intervalo técnico") in transiciones(entorno):
                break
    finally:
        tarea.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarea

    assert transiciones(entorno) == [
        ("INICIO", "Intervalo técnico"),
        ("FIN", "Intervalo técnico"),
    ]


async def test_sin_cierre_inyectado_el_temporizador_conserva_su_conducta(
    tmp_path: Path,
) -> None:
    """Sin la corrutina de cierre el temporizador sólo publica, como antes.

    Es la regresión que protege a los despliegues y pruebas que construyen el
    servicio de fronteras sin plano técnico: cruzar una frontera debe seguir
    generando una revisión nueva y ninguna escritura de auditoría.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")
    await servicio.publicar_aviso("Sin cierre automático", DestinoAvisoTecnico.RECINTO, 15)
    revision_inicial = entorno.coordinador.revision

    async def esperar(demora: float) -> None:
        entorno.reloj.avanzar(demora)

    fronteras = ServicioFronterasTemporales(
        entorno.servicio,
        entorno.ejecutor,
        entorno.coordinador,
        esperar=esperar,
    )
    tarea = asyncio.create_task(fronteras.ejecutar())
    try:
        for _ in range(20):
            await asyncio.sleep(0)
            if entorno.coordinador.revision > revision_inicial:
                break
    finally:
        tarea.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarea

    assert entorno.coordinador.revision > revision_inicial
    assert transiciones(entorno) == [("INICIO", "Sin cierre automático")]


async def test_un_fallo_de_auditoria_no_anuncia_el_inicio_ni_publica_el_aviso(
    tmp_path: Path,
) -> None:
    """CA: se conserva la política de fallo cerrado ya vigente.

    Si el ``INICIO`` no pudo persistirse, la mutación completa se aborta: no se
    instala el marcador y el texto tampoco llega a la ranura del Recinto. Nunca
    se anuncia como aplicada una transición que la auditoría no registró.
    """

    llamadas = 0

    def sincronizar_con_fallo(_descriptor: int) -> None:
        nonlocal llamadas
        llamadas += 1
        # Las tres primeras corresponden a los encabezados y las tres siguientes
        # a la fila técnica L2; el fallo cae sobre el primer destino del INICIO.
        if llamadas == 7:
            raise OSError("disco no disponible")

    entorno = crear_entorno_proyecciones(tmp_path)
    entorno.contexto.escritor_auditoria = EscritorAuditoriaCsv(
        tmp_path / "logs-fallo",
        entorno.reloj.ahora(),
        reloj=entorno.reloj.ahora,
        sincronizar=sincronizar_con_fallo,
    )
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    with pytest.raises(ErrorAuditoria):
        await servicio.publicar_aviso("No debe publicarse", DestinoAvisoTecnico.RECINTO, None)

    assert entorno.estado.marcador_recinto_abierto is None
    assert entorno.estado.aviso_tecnico_recinto is None


async def test_el_temporizador_sobrevive_a_un_fallo_de_auditoria(tmp_path: Path) -> None:
    """Un escritor en fallo cerrado no puede matar al temporizador único.

    Si lo hiciera, el proceso dejaría de publicar además la cuenta regresiva, el
    revelado y el resultado público. El período queda abierto —no se anuncia un
    cierre que no se persistió— y el ciclo continúa.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")
    await servicio.publicar_aviso("Queda abierto", DestinoAvisoTecnico.RECINTO, 12)

    async def cerrar_fallando() -> None:
        raise ErrorAuditoria("no se pudo sincronizar")

    async def esperar(demora: float) -> None:
        entorno.reloj.avanzar(demora)

    fronteras = ServicioFronterasTemporales(
        entorno.servicio,
        entorno.ejecutor,
        entorno.coordinador,
        esperar=esperar,
        cerrar_marcadores_vencidos=cerrar_fallando,
    )
    tarea = asyncio.create_task(fronteras.ejecutar())
    try:
        for _ in range(20):
            await asyncio.sleep(0)
        # Lo que se demuestra es justamente esto: después de cruzar la frontera
        # fallida la tarea sigue viva, en vez de haber muerto con la excepción.
        seguia_viva = not tarea.done()
    finally:
        tarea.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarea

    assert seguia_viva
    assert entorno.estado.marcador_recinto_abierto is not None
    assert transiciones(entorno) == [("INICIO", "Queda abierto")]


async def test_el_ciclo_de_vida_inyecta_el_cierre_automatico() -> None:
    """El lifespan debe cablear el cierre; sin eso el ``FIN`` nunca ocurriría.

    Es la única costura del WP que no se puede observar desde el servicio, así
    que se verifica que la aplicación construya el temporizador con la corrutina
    de cierre atada al servicio técnico real.
    """

    from botonera2_backend import aplicacion as modulo_aplicacion

    capturado: dict[str, object] = {}
    original = modulo_aplicacion.ServicioFronterasTemporales

    class FronterasEspia(ServicioFronterasTemporales):
        def __init__(self, *args: object, **kwargs: object) -> None:
            capturado.update(kwargs)
            super().__init__(*args, **kwargs)  # type: ignore[arg-type]

    modulo_aplicacion.ServicioFronterasTemporales = FronterasEspia  # type: ignore[misc]
    try:
        async with modulo_aplicacion.ciclo_vida(modulo_aplicacion.crear_aplicacion()):
            pass
    finally:
        modulo_aplicacion.ServicioFronterasTemporales = original  # type: ignore[misc]

    cierre = capturado.get("cerrar_marcadores_vencidos")
    assert cierre is not None
    assert getattr(cierre, "__self__", None).__class__ is ServicioApoyoTecnico
    assert getattr(cierre, "__name__", "") == "cerrar_marcadores_recinto_vencidos"
