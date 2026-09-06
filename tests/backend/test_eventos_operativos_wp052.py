"""Pruebas de la proyección operativa segura de eventos (WP-052).

Estas pruebas usan los servicios reales de preparación, sesión, votación,
entrada y proyecciones sobre un único ``EjecutorMutaciones``, igual que la
operación real. Eso importa: la fuga que WP-052 corrige no se puede demostrar
con objetos de mentira, porque nace justamente de que el evento durable de
auditoría —correcto y completo— viajaba tal cual hacia la pantalla de
Moderación mientras la votación seguía ``EN_CURSO``.

Las pruebas cubren tres frentes:

1. **No filtración**: durante el secreto, ni un solo campo del snapshot de
   Moderación contiene el sentido individual del voto, ni el emoji que lo
   representa, ni la tecla física que permitiría deducirlo.
2. **Enriquecimiento por el mismo ``seq``**: cuando la frontera autoritativa
   de esa votación vence, el mismo hecho gana sentido e icono sin cambiar de
   identidad ni de número de secuencia.
3. **Auditoría intacta**: el CSV institucional conserva siempre el mensaje
   completo, porque nunca se reescribe hacia atrás.
"""

from __future__ import annotations

import csv
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path

import pytest
from conftest import (
    LINEA_LOGS,
    LINEA_QUORUM,
    TOML_CANONICO,
    escribir_padron,
    escribir_system_toml,
    filas_padron_valido,
)
from sis_leg_backend.auditoria import EscritorAuditoriaCsv, NivelAuditoria
from sis_leg_backend.dominio.entrada import Pulsacion
from sis_leg_backend.dominio.estado import EstadoOperativo
from sis_leg_backend.dominio.sesion import ActualizacionDatosInstitucionales
from sis_leg_backend.dominio.votacion import (
    BaseMayoria,
    DatosAperturaVotacion,
    TipoMayoria,
)
from sis_leg_backend.servicios.entrada import ServicioEntradaTecla
from sis_leg_backend.servicios.preparacion import ServicioPreparacion
from sis_leg_backend.servicios.proyecciones import (
    EventoRecienteProyectado,
    ServicioProyecciones,
)
from sis_leg_backend.servicios.publicacion import CoordinadorPublicacion
from sis_leg_backend.servicios.serializacion import EjecutorMutaciones
from sis_leg_backend.servicios.sesion import ServicioSesion
from sis_leg_backend.servicios.votacion import ServicioVotacion

pytestmark = pytest.mark.anyio

HORA_INICIO = datetime(2026, 9, 1, 9, 0, 0)
HORA_SESION = datetime(2026, 9, 1, 9, 10, 0)
HORA_APERTURA = datetime(2026, 9, 1, 9, 20, 0)

# El TOML canónico de pruebas fija `moderation_vote_reveal_seconds = 4`. La
# constante evita repetir ese número mágico en cada escenario temporal.
SEGUNDOS_REVELADO = 4

CODIGO_VOTO = "VOTO_ORDINARIO_REGISTRADO"
CODIGO_PULSACION_RECIBIDA = "PULSACION_RECIBIDA"
CODIGO_PEDIDO_PALABRA = "PEDIDO_PALABRA_REGISTRADO"
CODIGO_RETIRO_PALABRA = "PEDIDO_PALABRA_RETIRADO"

# Cadenas que jamás pueden aparecer en el snapshot de Moderación mientras el
# sentido individual siga siendo secreto. Se comprueban sobre el JSON completo
# y no solo sobre el campo nuevo: si otro campo filtrara el secreto, la prueba
# también debería fallar.
SENTIDOS_PROHIBIDOS = ("POSITIVO", "NEGATIVO", "ABSTENCION", "ABSTENCIÓN")
ICONOS_DE_SENTIDO = ("✅", "❌", "\U0001f7e1")


@dataclass(slots=True)
class RelojMutable:
    """Reloj civil controlado que comparten votaciones y proyecciones.

    Compartirlo es intencional: permite abrir una votación en un instante y
    después "esperar" a que su frontera de revelado venza sin depender del
    reloj real de la máquina ni de esperas activas.
    """

    fecha: datetime

    def ahora(self) -> datetime:
        """Devuelve el instante civil vigente para la prueba."""

        return self.fecha

    def avanzar(self, segundos: float) -> None:
        """Adelanta el tiempo simulado la cantidad de segundos indicada."""

        self.fecha += timedelta(seconds=segundos)


@dataclass(slots=True)
class EntornoEventos:
    """Agrupa los servicios reales que comparten estado y serializador."""

    estado: EstadoOperativo
    entrada: ServicioEntradaTecla
    sesion: ServicioSesion
    votaciones: ServicioVotacion
    proyecciones: ServicioProyecciones
    reloj: RelojMutable = field(default_factory=lambda: RelojMutable(HORA_APERTURA))


def datos_votacion(numero: int = 37) -> DatosAperturaVotacion:
    """Construye una apertura simple mínima, sin ejercitar reglas de mayoría."""

    return DatosAperturaVotacion(
        numero_votacion=numero,
        tipo="Mocion",
        tema="Tratamiento de prueba",
        tipo_mayoria=TipoMayoria.SIMPLE,
        factor=0.0,
        base=BaseMayoria.VOTOS_COMPUTABLES,
    )


async def crear_entorno(
    directorio: Path,
    *,
    quorum: int = 2,
    fabrica_escritor: Callable[[Path, datetime], EscritorAuditoriaCsv] | None = None,
) -> EntornoEventos:
    """Prepara el recinto real y construye todos los servicios compartidos."""

    directorio.mkdir(parents=True, exist_ok=True)
    ruta_configuracion = escribir_system_toml(
        directorio / "system.toml",
        TOML_CANONICO.replace(
            LINEA_LOGS,
            f'logs_dir = "{directorio / "logs"}"',
        ).replace(LINEA_QUORUM, f"quorum = {quorum}"),
    )
    ruta_padron = escribir_padron(directorio / "concejales.csv", filas_padron_valido())
    estado = EstadoOperativo()
    coordinador = CoordinadorPublicacion()
    ejecutor = EjecutorMutaciones(coordinador.publicar)
    reloj = RelojMutable(HORA_APERTURA)
    preparacion = ServicioPreparacion(
        estado,
        ejecutor,
        ruta_configuracion=ruta_configuracion,
        ruta_padron=ruta_padron,
        reloj=lambda: HORA_INICIO,
        fabrica_escritor=fabrica_escritor
        or partial(EscritorAuditoriaCsv, reloj=lambda: HORA_INICIO),
    )
    await preparacion.preparar_sala()
    return EntornoEventos(
        estado=estado,
        entrada=ServicioEntradaTecla(
            estado,
            ejecutor,
            reloj_monotono=lambda: 10.0,
            reloj=reloj.ahora,
        ),
        sesion=ServicioSesion(estado, ejecutor, reloj=lambda: HORA_SESION),
        votaciones=ServicioVotacion(
            estado,
            ejecutor,
            reloj=reloj.ahora,
            generador_id=lambda: f"votacion-{reloj.ahora().isoformat()}",
        ),
        proyecciones=ServicioProyecciones(
            estado,
            ejecutor,
            coordinador,
            reloj=reloj.ahora,
            reloj_monotono=lambda: 10.0,
        ),
        reloj=reloj,
    )


async def abrir_sesion(
    entorno: EntornoEventos,
    dispositivos_presentes: tuple[str, ...] = ("D-01", "D-02"),
) -> None:
    """Completa autoridades, acredita bancas y abre la sesión formal."""

    await entorno.sesion.actualizar_preparacion(
        ActualizacionDatosInstitucionales(
            incluye_numero_sesion=True,
            numero_sesion=59,
            incluye_presidencia=True,
            presidencia="Presidencia",
            incluye_secretaria_legislativa=True,
            secretaria_legislativa="Secretaría",
        )
    )
    for dispositivo in dispositivos_presentes:
        respuesta = await entorno.entrada.procesar_pulsacion(Pulsacion(dispositivo, "9"))
        assert respuesta.aceptada is True
    await entorno.sesion.abrir_sesion()


async def preparar_votacion_con_voto(
    tmp_path: Path,
    tecla: str,
) -> EntornoEventos:
    """Deja una votación ``EN_CURSO`` con exactamente un voto ya auditado."""

    entorno = await crear_entorno(tmp_path)
    await abrir_sesion(entorno)
    await entorno.votaciones.abrir_votacion(datos_votacion())
    respuesta = await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", tecla))
    assert respuesta.aceptada is True
    return entorno


async def eventos_de(
    entorno: EntornoEventos,
    codigo: str,
) -> list[EventoRecienteProyectado]:
    """Proyecta el estado y devuelve los eventos del código pedido."""

    estado = await entorno.proyecciones.obtener_estado_moderacion()
    return [evento for evento in estado.eventos_recientes if evento.codigo_evento == codigo]


async def unico_evento(entorno: EntornoEventos, codigo: str) -> EventoRecienteProyectado:
    """Afirma que el escenario produjo exactamente un evento de ese código."""

    eventos = await eventos_de(entorno, codigo)
    assert len(eventos) == 1, f"Se esperaba un único {codigo}, hay {len(eventos)}"
    return eventos[0]


def filas_csv(entorno: EntornoEventos, nivel: NivelAuditoria) -> list[list[str]]:
    """Lee el CSV durable para comprobar que la auditoría no se recortó."""

    contexto = entorno.estado.contexto_operativo_activo()
    assert contexto is not None
    ruta = contexto.escritor_auditoria.rutas[nivel]
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.reader(archivo, delimiter=";"))


async def test_voto_en_curso_identifica_la_banca_sin_revelar_el_sentido(
    tmp_path: Path,
) -> None:
    """CA-1/2/3: identidad y ``Voto emitido``, jamás el sentido ni su emoji."""

    entorno = await preparar_votacion_con_voto(tmp_path, "1")

    evento = await unico_evento(entorno, CODIGO_VOTO)

    assert evento.nivel == "L3"
    assert evento.hecho is not None
    assert evento.hecho.tipo == "VOTO_ORDINARIO"
    assert evento.hecho.concejal.banca == 1
    assert evento.hecho.concejal.nombre == "Ana"
    assert evento.hecho.concejal.apellido == "Garcia"
    assert evento.hecho.detalle == "Voto emitido"
    assert evento.hecho.icono is None
    assert evento.hecho.sentido is None
    # El mensaje publicado conserva identidad y votación pero pierde el sentido.
    assert "emitió su voto" in evento.mensaje
    assert "votó" not in evento.mensaje


async def test_el_payload_completo_de_moderacion_no_contiene_el_sentido(
    tmp_path: Path,
) -> None:
    """Prueba negativa de fuga sobre el JSON efectivamente serializado.

    Es el gate más importante del WP: no alcanza con que el campo nuevo esté
    limpio. Se inspecciona todo el snapshot, de modo que cualquier otro campo
    que empezara a transportar el sentido individual haría fallar esta prueba.
    """

    entorno = await preparar_votacion_con_voto(tmp_path, "3")

    estado = await entorno.proyecciones.obtener_estado_moderacion()
    payload = estado.model_dump_json()

    assert estado.votacion is not None
    assert estado.votacion.votos_individuales_revelados is False
    for prohibido in SENTIDOS_PROHIBIDOS:
        assert prohibido not in payload
    for icono in ICONOS_DE_SENTIDO:
        assert icono not in payload
    # La tecla física es equivalente al sentido: 1 POSITIVO, 2 ABSTENCIÓN y
    # 3 NEGATIVO. Con el dispositivo lógico ya visible en la grilla de bancas,
    # publicarla sería exactamente la misma fuga por otro camino.
    assert "tecla [3]" not in payload
    assert "tecla [oculta]" in payload
    # La banca que ya participó sí puede conocerse: es el contrato de WP-045.
    assert estado.votacion.bancas_voto_emitido == (1,)


@pytest.mark.parametrize(
    ("tecla", "sentido", "icono", "detalle"),
    [
        ("1", "POSITIVO", "✅", "Voto POSITIVO"),
        ("3", "NEGATIVO", "❌", "Voto NEGATIVO"),
        ("2", "ABSTENCION", "\U0001f7e1", "Voto ABSTENCIÓN"),
    ],
    ids=["positivo", "negativo", "abstencion"],
)
async def test_al_vencer_la_frontera_el_mismo_seq_se_enriquece(
    tmp_path: Path,
    tecla: str,
    sentido: str,
    icono: str,
    detalle: str,
) -> None:
    """CA-4: el hecho no se duplica ni cambia de ``seq``, solo se enriquece."""

    entorno = await preparar_votacion_con_voto(tmp_path, tecla)

    antes = await unico_evento(entorno, CODIGO_VOTO)
    assert antes.hecho is not None and antes.hecho.sentido is None

    entorno.reloj.avanzar(SEGUNDOS_REVELADO)
    despues = await unico_evento(entorno, CODIGO_VOTO)

    assert despues.seq == antes.seq
    assert despues.timestamp == antes.timestamp
    assert despues.hecho is not None
    assert despues.hecho.concejal == antes.hecho.concejal
    assert despues.hecho.sentido == sentido
    assert despues.hecho.icono == icono
    assert despues.hecho.detalle == detalle
    # Vencida la frontera vuelve el mensaje durable completo de auditoría.
    assert f"votó {sentido}" in despues.mensaje


async def test_la_pulsacion_de_voto_recupera_su_tecla_al_vencer_la_frontera(
    tmp_path: Path,
) -> None:
    """La protección del evento L2 de entrada es temporal, no una mutilación."""

    entorno = await preparar_votacion_con_voto(tmp_path, "1")

    pulsaciones_secretas = await eventos_de(entorno, CODIGO_PULSACION_RECIBIDA)
    pulsacion_del_voto = pulsaciones_secretas[-1]
    assert pulsacion_del_voto.nivel == "L2"
    assert "tecla [oculta]" in pulsacion_del_voto.mensaje
    # Una pulsación no es un hecho institucional con identidad e icono: se
    # protege ocultando la tecla, no convirtiéndola en una tarjeta enriquecida.
    assert pulsacion_del_voto.hecho is None

    entorno.reloj.avanzar(SEGUNDOS_REVELADO)
    pulsaciones_reveladas = await eventos_de(entorno, CODIGO_PULSACION_RECIBIDA)

    assert pulsaciones_reveladas[-1].seq == pulsacion_del_voto.seq
    assert "tecla [1]" in pulsaciones_reveladas[-1].mensaje


async def test_las_pulsaciones_sin_votacion_abierta_conservan_su_tecla(
    tmp_path: Path,
) -> None:
    """No se censura donde no hay secreto: presencia y palabra no se ocultan."""

    entorno = await crear_entorno(tmp_path)
    await abrir_sesion(entorno)

    pulsaciones = await eventos_de(entorno, CODIGO_PULSACION_RECIBIDA)

    assert pulsaciones, "La acreditación de presencia debe haber dejado eventos"
    assert all("tecla [9]" in evento.mensaje for evento in pulsaciones)
    assert all(evento.hecho is None for evento in pulsaciones)


async def test_pedido_y_retiro_de_palabra_llevan_iconos_propios(
    tmp_path: Path,
) -> None:
    """CA-5: ✋ para el pedido y ✊ para el retiro, con identidad de banca."""

    entorno = await crear_entorno(tmp_path)
    await abrir_sesion(entorno)
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "7"))
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "7"))

    pedido = await unico_evento(entorno, CODIGO_PEDIDO_PALABRA)
    retiro = await unico_evento(entorno, CODIGO_RETIRO_PALABRA)

    assert pedido.hecho is not None
    assert pedido.hecho.tipo == "PEDIDO_PALABRA"
    assert pedido.hecho.icono == "✋"
    assert pedido.hecho.detalle == "Pedido de palabra"
    assert pedido.hecho.concejal.banca == 2
    assert pedido.hecho.sentido is None

    assert retiro.hecho is not None
    assert retiro.hecho.tipo == "RETIRO_PALABRA"
    assert retiro.hecho.icono == "✊"
    assert retiro.hecho.detalle == "Pedido de palabra retirado"
    assert retiro.hecho.concejal.banca == 2
    assert retiro.hecho.sentido is None


async def test_cada_votacion_aplica_su_propia_frontera_de_revelado(
    tmp_path: Path,
) -> None:
    """Un voto viejo ya revelado no arrastra al voto nuevo todavía secreto.

    Es la razón por la que la referencia del hecho guarda ``votacion_id``: si
    la proyección usara siempre la votación activa, abrir una votación nueva
    volvería a ocultar los votos ya públicos de la anterior o, peor, revelaría
    los de la nueva por la frontera vencida de la anterior.
    """

    entorno = await crear_entorno(tmp_path)
    await abrir_sesion(entorno)
    primera = await entorno.votaciones.abrir_votacion(datos_votacion(numero=1))
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "1"))

    # La primera votación termina inconclusa: falta el voto de la otra banca
    # presente, así que no hubo autocierre.
    entorno.reloj.avanzar(SEGUNDOS_REVELADO + 1)
    await entorno.votaciones.finalizar_votacion_manualmente(primera.id, "Se levanta el tratamiento")
    await entorno.votaciones.abrir_votacion(datos_votacion(numero=2))
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "3"))

    votos = await eventos_de(entorno, CODIGO_VOTO)

    assert len(votos) == 2
    voto_viejo, voto_nuevo = votos
    assert voto_viejo.hecho is not None and voto_viejo.hecho.sentido == "POSITIVO"
    assert voto_viejo.hecho.icono == "✅"
    assert voto_nuevo.hecho is not None and voto_nuevo.hecho.sentido is None
    assert voto_nuevo.hecho.detalle == "Voto emitido"


async def test_el_csv_institucional_conserva_el_sentido_completo(
    tmp_path: Path,
) -> None:
    """CA-8: la protección vive en la proyección, nunca en el archivo durable."""

    entorno = await preparar_votacion_con_voto(tmp_path, "2")

    filas_l3 = filas_csv(entorno, NivelAuditoria.L3)
    fila_voto = next(fila for fila in filas_l3 if fila[4] == CODIGO_VOTO)
    filas_l1 = filas_csv(entorno, NivelAuditoria.L1)
    fila_pulsacion = [fila for fila in filas_l1 if fila[4] == CODIGO_PULSACION_RECIBIDA][-1]

    assert "votó ABSTENCION" in fila_voto[5]
    assert "tecla [2]" in fila_pulsacion[5]
    assert "oculta" not in fila_pulsacion[5]


async def test_el_recinto_no_recibe_hechos_ni_sentido_individual(
    tmp_path: Path,
) -> None:
    """CA-9: la pantalla pública no gana ningún campo sensible nuevo."""

    entorno = await preparar_votacion_con_voto(tmp_path, "1")

    recinto = await entorno.proyecciones.obtener_estado_recinto()
    payload = recinto.model_dump_json()

    assert "hecho" not in payload
    assert "eventos_recientes" not in payload
    for prohibido in SENTIDOS_PROHIBIDOS:
        assert prohibido not in payload
    for icono in ICONOS_DE_SENTIDO:
        assert icono not in payload
    # Incluso después del revelado para Moderación, el Recinto sigue sin
    # recibir la proyección de eventos operativos.
    entorno.reloj.avanzar(SEGUNDOS_REVELADO)
    revelado = await entorno.proyecciones.obtener_estado_recinto()
    assert "hecho" not in revelado.model_dump_json()


async def test_apoyo_tecnico_hereda_la_misma_frontera_de_secreto(
    tmp_path: Path,
) -> None:
    """WP-055: el puesto técnico ve los mismos eventos seguros que Moderación.

    La decisión humana 7 de WP-055 le concede a Apoyo Técnico "los mismos
    niveles L1/L2/L3 seguros que Moderación". Reutilizar el constructor de
    eventos, en lugar de escribir una variante propia, es lo que impide que ese
    puesto se convierta en una vía alternativa para conocer el sentido de un
    voto todavía secreto.
    """

    entorno = await preparar_votacion_con_voto(tmp_path, "1")

    tecnico = await entorno.proyecciones.obtener_estado_tecnico()
    moderacion = await entorno.proyecciones.obtener_estado_moderacion()
    payload = tecnico.model_dump_json()

    assert tecnico.eventos_recientes == moderacion.eventos_recientes
    for prohibido in SENTIDOS_PROHIBIDOS:
        assert prohibido not in payload
    for icono in ICONOS_DE_SENTIDO:
        assert icono not in payload

    # Vencida la frontera, ambos puestos se enriquecen a la vez y con el mismo
    # ``seq``: nunca uno antes que el otro.
    entorno.reloj.avanzar(SEGUNDOS_REVELADO)
    tecnico_revelado = await entorno.proyecciones.obtener_estado_tecnico()
    moderacion_revelada = await entorno.proyecciones.obtener_estado_moderacion()
    assert tecnico_revelado.eventos_recientes == moderacion_revelada.eventos_recientes
    assert "POSITIVO" in tecnico_revelado.model_dump_json()


async def test_el_recinto_no_recibe_biblioteca_ni_aviso_ajeno(
    tmp_path: Path,
) -> None:
    """WP-055: la porción técnica del Recinto no amplía su allowlist pública.

    El Recinto recibe transmisión y su propio aviso, nada más: ni la biblioteca
    de mensajes precargados, ni el aviso dirigido a Moderación, ni los eventos
    operativos que ese puesto sí puede leer.
    """

    entorno = await preparar_votacion_con_voto(tmp_path, "1")

    recinto = await entorno.proyecciones.obtener_estado_recinto()
    claves_tecnico = set(recinto.tecnico.model_dump().keys())

    assert claves_tecnico == {"transmision", "aviso"}
    assert "biblioteca" not in recinto.model_dump_json()
    assert "aviso_moderacion" not in recinto.model_dump_json()


async def test_los_niveles_y_el_orden_ascendente_se_conservan(
    tmp_path: Path,
) -> None:
    """CA-7: la proyección no reordena ni reclasifica lo que filtra la UI."""

    entorno = await preparar_votacion_con_voto(tmp_path, "1")

    estado = await entorno.proyecciones.obtener_estado_moderacion()
    eventos = estado.eventos_recientes

    assert [evento.seq for evento in eventos] == sorted(evento.seq for evento in eventos)
    assert {evento.nivel for evento in eventos} <= {"L1", "L2", "L3"}
    # El filtro acumulativo de la UI necesita que convivan varios niveles.
    assert {"L2", "L3"} <= {evento.nivel for evento in eventos}


async def test_la_frontera_de_revelado_programa_una_republicacion(
    tmp_path: Path,
) -> None:
    """El enriquecimiento no depende de que ocurra otra mutación en el recinto.

    ``demora_hasta_proxima_frontera`` es lo que hace que el stream vuelva a
    publicar exactamente cuando vence el secreto. Sin esa demora, la tarjeta
    del voto quedaría mostrando ``Voto emitido`` hasta la próxima pulsación.
    """

    entorno = await preparar_votacion_con_voto(tmp_path, "1")

    demora = entorno.proyecciones.demora_hasta_proxima_frontera()

    assert demora is not None
    assert 0 < demora <= SEGUNDOS_REVELADO
