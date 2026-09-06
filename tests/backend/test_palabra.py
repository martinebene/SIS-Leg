"""Integración de cola, tecla 7, Moderación, ausencia y concurrencia (WP-015)."""

from __future__ import annotations

import asyncio
import csv
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
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
from sis_leg_backend.auditoria import ErrorAuditoria, EscritorAuditoriaCsv, NivelAuditoria
from sis_leg_backend.dominio.entrada import (
    AccionPalabra,
    Pulsacion,
    RespuestaEntrada,
    ResultadoPalabra,
)
from sis_leg_backend.dominio.errores import ErrorEstadoIncompatible
from sis_leg_backend.dominio.estado import EstadoGlobal, EstadoOperativo
from sis_leg_backend.dominio.sesion import ActualizacionDatosInstitucionales, Sesion
from sis_leg_backend.dominio.votacion import (
    BaseMayoria,
    DatosAperturaVotacion,
    EstadoVotacion,
    TipoMayoria,
)
from sis_leg_backend.hechos_operativos import ReferenciaHechoOperativo
from sis_leg_backend.servicios.entrada import ServicioEntradaTecla
from sis_leg_backend.servicios.palabra import ServicioPalabra
from sis_leg_backend.servicios.preparacion import ServicioPreparacion
from sis_leg_backend.servicios.serializacion import EjecutorMutaciones
from sis_leg_backend.servicios.sesion import ServicioSesion
from sis_leg_backend.servicios.votacion import ServicioVotacion

pytestmark = pytest.mark.anyio

HORA_INICIO = datetime(2026, 8, 23, 9, 0, 0)
HORA_SESION = datetime(2026, 8, 23, 9, 10, 0)
HORA_VOTACION = datetime(2026, 8, 23, 9, 20, 0)


@dataclass(frozen=True, slots=True)
class EntornoPalabra:
    """Agrupa servicios reales que comparten estado y serializador global."""

    estado: EstadoOperativo
    ejecutor: EjecutorMutaciones
    entrada: ServicioEntradaTecla
    palabra: ServicioPalabra
    sesion: ServicioSesion
    votaciones: ServicioVotacion


async def crear_entorno(
    tmp_path: Path,
    *,
    quorum: int = 1,
    presentes: tuple[str, ...] = ("D-01", "D-02", "D-03"),
    abrir: bool = True,
    fabrica_escritor: Callable[[Path, datetime], EscritorAuditoriaCsv] | None = None,
) -> EntornoPalabra:
    """Prepara y opcionalmente abre una sesión usando solo servicios públicos."""

    tmp_path.mkdir(parents=True, exist_ok=True)
    ruta_configuracion = escribir_system_toml(
        tmp_path / "system.toml",
        TOML_CANONICO.replace(
            LINEA_LOGS,
            f'logs_dir = "{tmp_path / "logs"}"',
        ).replace(LINEA_QUORUM, f"quorum = {quorum}"),
    )
    ruta_padron = escribir_padron(tmp_path / "concejales.csv", filas_padron_valido())
    estado = EstadoOperativo()
    ejecutor = EjecutorMutaciones()
    preparacion = ServicioPreparacion(
        estado,
        ejecutor,
        ruta_configuracion=ruta_configuracion,
        ruta_padron=ruta_padron,
        reloj=lambda: HORA_INICIO,
        fabrica_escritor=fabrica_escritor
        or partial(EscritorAuditoriaCsv, reloj=lambda: HORA_INICIO),
    )
    entrada = ServicioEntradaTecla(
        estado,
        ejecutor,
        reloj_monotono=lambda: 0.0,
        reloj=lambda: HORA_VOTACION,
    )
    sesion = ServicioSesion(estado, ejecutor, reloj=lambda: HORA_SESION)
    entorno = EntornoPalabra(
        estado=estado,
        ejecutor=ejecutor,
        entrada=entrada,
        palabra=ServicioPalabra(estado, ejecutor),
        sesion=sesion,
        votaciones=ServicioVotacion(
            estado,
            ejecutor,
            reloj=lambda: HORA_VOTACION,
            generador_id=lambda: "votacion-palabra",
        ),
    )
    await preparacion.preparar_sala()
    if not abrir:
        return entorno

    await sesion.actualizar_preparacion(
        ActualizacionDatosInstitucionales(
            incluye_numero_sesion=True,
            numero_sesion=59,
            incluye_presidencia=True,
            presidencia="Presidencia",
            incluye_secretaria_legislativa=True,
            secretaria_legislativa="Secretaría",
        )
    )
    for dispositivo in presentes:
        respuesta = await entrada.procesar_pulsacion(Pulsacion(dispositivo, "9"))
        assert respuesta.aceptada is True
    await sesion.abrir_sesion()
    return entorno


def sesion_abierta(entorno: EntornoPalabra) -> Sesion:
    """Afirma el estado requerido y devuelve la única sesión autoritativa."""

    sesion = entorno.estado.sesion_activa
    assert sesion is not None
    return sesion


def resultado_palabra(respuesta: RespuestaEntrada) -> ResultadoPalabra:
    """Afirma la variante PALABRA para ayudar a Pyright y a las pruebas."""

    assert isinstance(respuesta.resultado, ResultadoPalabra)
    return respuesta.resultado


def filas_l1(entorno: EntornoPalabra) -> list[list[str]]:
    """Lee el CSV acumulativo para observar el orden institucional durable."""

    contexto = entorno.estado.contexto_operativo_activo()
    assert contexto is not None
    ruta = contexto.escritor_auditoria.rutas[NivelAuditoria.L1]
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.reader(archivo, delimiter=";"))


def codigos_desde(entorno: EntornoPalabra, indice: int) -> list[str]:
    """Devuelve los códigos persistidos desde una frontera conocida."""

    return [fila[4] for fila in filas_l1(entorno)[indice:]]


def datos_votacion() -> DatosAperturaVotacion:
    """Construye una votación simple mínima para probar convivencia normal."""

    return DatosAperturaVotacion(
        numero_votacion=37,
        tipo="Mocion",
        tema="Tratamiento con palabra",
        tipo_mayoria=TipoMayoria.SIMPLE,
        factor=0.0,
        base=BaseMayoria.VOTOS_COMPUTABLES,
    )


def instalar_fallo_en_codigo(
    entorno: EntornoPalabra,
    monkeypatch: pytest.MonkeyPatch,
    codigo_objetivo: str,
) -> None:
    """Hace fallar una frontera exacta sin sustituir el writer ni su lock."""

    contexto = entorno.estado.contexto_operativo_activo()
    assert contexto is not None
    escritor = contexto.escritor_auditoria
    registrar_original = escritor.registrar_evento

    def registrar(
        nivel: NivelAuditoria,
        etiqueta: str,
        codigo_evento: str,
        mensaje: str,
        *,
        referencia: ReferenciaHechoOperativo | None = None,
    ) -> int:
        if codigo_evento == codigo_objetivo:
            monkeypatch.setattr(escritor, "_fallado", True)
            raise ErrorAuditoria(f"fallo controlado en {codigo_objetivo}")
        return registrar_original(nivel, etiqueta, codigo_evento, mensaje, referencia=referencia)

    monkeypatch.setattr(escritor, "registrar_evento", registrar)


async def test_tecla_siete_en_preparando_y_concejal_ausente_se_rechazan(
    tmp_path: Path,
) -> None:
    """RN-INP-02 y RN-PAL-01 conservan motivos exactos sin mutar palabra."""

    entorno_preparando = await crear_entorno(tmp_path / "preparando", abrir=False)
    rechazo_preparando = await entorno_preparando.entrada.procesar_pulsacion(Pulsacion("D-01", "7"))

    assert rechazo_preparando.motivo == "TECLA_NO_HABILITADA"
    assert rechazo_preparando.resultado is None

    entorno = await crear_entorno(tmp_path / "sesion", presentes=("D-01",))
    rechazo_ausente = await entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "7"))

    assert rechazo_ausente.aceptada is False
    assert rechazo_ausente.motivo == "CONCEJAL_AUSENTE"
    assert sesion_abierta(entorno).palabra.cola_dnis == ()


async def test_tecla_siete_agrega_retira_y_finaliza_uso_propio_sin_avance(
    tmp_path: Path,
) -> None:
    """CA-044/045/061: alterna pedido y prioriza finalizar al orador."""

    entorno = await crear_entorno(tmp_path)
    alta = await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "7"))
    retiro = await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "7"))

    assert alta.motivo == "PEDIDO_PALABRA_REGISTRADO"
    assert resultado_palabra(alta).accion is AccionPalabra.PEDIDO_AGREGADO
    assert retiro.motivo == "PEDIDO_PALABRA_RETIRADO"
    assert resultado_palabra(retiro).accion is AccionPalabra.PEDIDO_RETIRADO

    for dispositivo in ("D-01", "D-02", "D-03"):
        await entorno.entrada.procesar_pulsacion(Pulsacion(dispositivo, "7"))
    await entorno.palabra.otorgar_palabra()

    finalizacion = await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "7"))
    estado_palabra = sesion_abierta(entorno).palabra

    assert resultado_palabra(finalizacion).accion is AccionPalabra.USO_FINALIZADO
    assert finalizacion.motivo == "USO_PALABRA_FINALIZADO"
    assert estado_palabra.orador_dni is None
    assert estado_palabra.cola_dnis == ("30000002", "30000003")
    fila_final = next(
        fila for fila in reversed(filas_l1(entorno)) if fila[4] == "USO_PALABRA_FINALIZADO"
    )
    assert "DNI=30000001" in fila_final[5]
    assert "concejal=Ana Garcia" in fila_final[5]
    assert "banca=1" in fila_final[5]
    assert "causa=PROPIO" in fila_final[5]


async def test_otorgar_reemplaza_en_orden_y_quitar_no_avanza(tmp_path: Path) -> None:
    """CA-046/061: solo POST avanza y DELETE conserva los pedidos."""

    entorno = await crear_entorno(tmp_path)
    for dispositivo in ("D-01", "D-02", "D-03"):
        await entorno.entrada.procesar_pulsacion(Pulsacion(dispositivo, "7"))

    await entorno.palabra.otorgar_palabra()
    assert sesion_abierta(entorno).palabra.orador_dni == "30000001"

    await entorno.palabra.quitar_palabra()

    palabra = sesion_abierta(entorno).palabra
    assert palabra.orador_dni is None
    assert palabra.cola_dnis == ("30000002", "30000003")

    await entorno.palabra.otorgar_palabra()
    assert palabra.orador_dni == "30000002"
    assert palabra.cola_dnis == ("30000003",)

    frontera = len(filas_l1(entorno))
    await entorno.palabra.otorgar_palabra()

    assert palabra.orador_dni == "30000003"
    assert palabra.cola_dnis == ()
    assert codigos_desde(entorno, frontera) == [
        "USO_PALABRA_FINALIZADO",
        "USO_PALABRA_OTORGADO",
    ]


async def test_noops_de_moderacion_son_204_logicos_y_solo_diagnostico_l2(
    tmp_path: Path,
) -> None:
    """Sin destinatario no se inventa un hecho L3 ni un error funcional."""

    entorno = await crear_entorno(tmp_path)
    frontera = len(filas_l1(entorno))

    await entorno.palabra.otorgar_palabra()
    await entorno.palabra.quitar_palabra()

    nuevas = filas_l1(entorno)[frontera:]
    assert [fila[2:5] for fila in nuevas] == [
        ["L2", "PALABRA", "COMANDO_PALABRA_SIN_EFECTO"],
        ["L2", "PALABRA", "COMANDO_PALABRA_SIN_EFECTO"],
    ]


async def test_comandos_exigen_sesion_abierta(tmp_path: Path) -> None:
    """POST y DELETE comparten el conflicto ESTADO_INCOMPATIBLE del dominio."""

    entorno = await crear_entorno(tmp_path, abrir=False)

    with pytest.raises(ErrorEstadoIncompatible):
        await entorno.palabra.otorgar_palabra()
    with pytest.raises(ErrorEstadoIncompatible):
        await entorno.palabra.quitar_palabra()


async def test_ausencia_limpia_primero_intermedio_y_orador_sin_promover(
    tmp_path: Path,
) -> None:
    """CA-047/061: cada ausencia pierde posición/uso y el regreso no restaura."""

    entorno = await crear_entorno(tmp_path)
    for dispositivo in ("D-01", "D-02", "D-03"):
        await entorno.entrada.procesar_pulsacion(Pulsacion(dispositivo, "7"))

    await entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "9"))
    assert sesion_abierta(entorno).palabra.cola_dnis == ("30000001", "30000003")

    await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "9"))
    assert sesion_abierta(entorno).palabra.cola_dnis == ("30000003",)

    await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "9"))
    assert sesion_abierta(entorno).palabra.cola_dnis == ("30000003",)

    await entorno.palabra.otorgar_palabra()
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-03", "9"))

    palabra = sesion_abierta(entorno).palabra
    assert palabra.orador_dni is None
    assert palabra.cola_dnis == ()
    ausencias = [fila for fila in filas_l1(entorno) if fila[4] == "CONCEJAL_AUSENTE"]
    assert "pedido_palabra_retirado=true" in ausencias[0][5]
    assert "uso_palabra_finalizado=true" in ausencias[-1][5]


async def test_ausencia_del_orador_conserva_dos_pedidos_sin_avance(tmp_path: Path) -> None:
    """La prueba no trivial de CA-061 deja dos pedidos esperando tras la ausencia."""

    entorno = await crear_entorno(tmp_path)
    for dispositivo in ("D-01", "D-02", "D-03"):
        await entorno.entrada.procesar_pulsacion(Pulsacion(dispositivo, "7"))
    await entorno.palabra.otorgar_palabra()

    await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "9"))

    palabra = sesion_abierta(entorno).palabra
    assert palabra.orador_dni is None
    assert palabra.cola_dnis == ("30000002", "30000003")


async def test_palabra_convive_con_votacion_y_no_bloquea_apertura_ni_cierre(
    tmp_path: Path,
) -> None:
    """CA-048/049: palabra no pausa votos ni agrega precondiciones backend."""

    entorno = await crear_entorno(tmp_path, quorum=2)
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "7"))
    await entorno.palabra.otorgar_palabra()
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "7"))

    votacion = await entorno.votaciones.abrir_votacion(datos_votacion())
    palabra = sesion_abierta(entorno).palabra
    assert palabra.orador_dni == "30000001"
    assert palabra.cola_dnis == ("30000002",)

    voto = await entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "1"))
    retiro = await entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "7"))

    assert voto.aceptada is True
    assert resultado_palabra(retiro).accion is AccionPalabra.PEDIDO_RETIRADO
    assert votacion.estado is EstadoVotacion.EN_CURSO
    assert votacion.votos_ordinarios["30000002"].valor.value == "POSITIVO"

    await entorno.sesion.cerrar_sesion()

    assert entorno.estado.estado_global is EstadoGlobal.SIN_PREPARAR
    assert entorno.estado.sesion_activa is None


async def test_fallo_de_pedido_directo_no_muta_y_cierra_operaciones_siguientes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La frontera del L3 de pedido falla después de PULSACION_RECIBIDA."""

    entorno = await crear_entorno(tmp_path)
    instalar_fallo_en_codigo(entorno, monkeypatch, "PEDIDO_PALABRA_REGISTRADO")

    with pytest.raises(ErrorAuditoria):
        await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "7"))

    assert sesion_abierta(entorno).palabra.cola_dnis == ()


async def test_fallo_de_pulsacion_recibida_impide_resolver_tecla_siete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin el L2 de entrada durable ni siquiera se evalúa el pedido de palabra."""

    entorno = await crear_entorno(tmp_path)
    instalar_fallo_en_codigo(entorno, monkeypatch, "PULSACION_RECIBIDA")

    with pytest.raises(ErrorAuditoria):
        await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "7"))

    assert sesion_abierta(entorno).palabra.cola_dnis == ()


async def test_fallo_de_retiro_conserva_el_pedido(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PEDIDO_PALABRA_RETIRADO debe ser durable antes de perder la posición."""

    entorno = await crear_entorno(tmp_path)
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "7"))
    instalar_fallo_en_codigo(entorno, monkeypatch, "PEDIDO_PALABRA_RETIRADO")

    with pytest.raises(ErrorAuditoria):
        await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "7"))

    assert sesion_abierta(entorno).palabra.cola_dnis == ("30000001",)


@pytest.mark.parametrize("finalizador", ["PROPIO", "MODERACION"])
async def test_fallo_de_finalizacion_conserva_al_orador(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    finalizador: str,
) -> None:
    """Ninguna causa limpia al orador sin USO_PALABRA_FINALIZADO durable."""

    entorno = await crear_entorno(tmp_path)
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "7"))
    await entorno.palabra.otorgar_palabra()
    instalar_fallo_en_codigo(entorno, monkeypatch, "USO_PALABRA_FINALIZADO")

    with pytest.raises(ErrorAuditoria):
        if finalizador == "PROPIO":
            await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "7"))
        else:
            await entorno.palabra.quitar_palabra()

    assert sesion_abierta(entorno).palabra.orador_dni == "30000001"


async def test_fallo_de_primer_otorgamiento_conserva_la_cola(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin USO_PALABRA_OTORGADO durable no se retira el primer pedido."""

    entorno = await crear_entorno(tmp_path)
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "7"))
    instalar_fallo_en_codigo(entorno, monkeypatch, "USO_PALABRA_OTORGADO")

    with pytest.raises(ErrorAuditoria):
        await entorno.palabra.otorgar_palabra()

    palabra = sesion_abierta(entorno).palabra
    assert palabra.orador_dni is None
    assert palabra.cola_dnis == ("30000001",)


async def test_fallo_de_ausencia_conserva_presencia_y_palabra(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin CONCEJAL_AUSENTE durable no cambia presencia ni se limpia la cola."""

    entorno = await crear_entorno(tmp_path)
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "7"))
    instalar_fallo_en_codigo(entorno, monkeypatch, "CONCEJAL_AUSENTE")

    with pytest.raises(ErrorAuditoria):
        await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "9"))

    sesion = sesion_abierta(entorno)
    assert sesion.contexto_operativo.presencias["30000001"] is True
    assert sesion.palabra.cola_dnis == ("30000001",)


async def test_fallo_del_segundo_evento_de_otorgar_conserva_ultimo_hecho_durable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Finaliza al actual pero conserva primero en cola si falla el otorgamiento."""

    entorno = await crear_entorno(tmp_path)
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "7"))
    await entorno.palabra.otorgar_palabra()
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "7"))
    instalar_fallo_en_codigo(entorno, monkeypatch, "USO_PALABRA_OTORGADO")

    with pytest.raises(ErrorAuditoria):
        await entorno.palabra.otorgar_palabra()

    palabra = sesion_abierta(entorno).palabra
    assert palabra.orador_dni is None
    assert palabra.cola_dnis == ("30000002",)


async def test_ausencia_con_palabra_prioriza_perdida_de_quorum_en_votacion(
    tmp_path: Path,
) -> None:
    """La limpieza de palabra convive con la finalización INCONCLUSA derivada."""

    entorno = await crear_entorno(tmp_path, quorum=3)
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-03", "7"))
    await entorno.palabra.otorgar_palabra()
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "7"))
    votacion = await entorno.votaciones.abrir_votacion(datos_votacion())

    await entorno.entrada.procesar_pulsacion(Pulsacion("D-03", "9"))

    palabra = sesion_abierta(entorno).palabra
    assert palabra.orador_dni is None
    assert palabra.cola_dnis == ("30000001",)
    assert votacion.estado is EstadoVotacion.CERRADA
    assert votacion.resultado is not None
    assert votacion.resultado.value == "INCONCLUSA"


async def test_fallo_derivado_de_quorum_no_revierte_ausencia_ni_limpieza_de_palabra(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El estado queda en el último hecho durable aunque falle la votación derivada."""

    entorno = await crear_entorno(tmp_path, quorum=3)
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-03", "7"))
    await entorno.palabra.otorgar_palabra()
    votacion = await entorno.votaciones.abrir_votacion(datos_votacion())
    instalar_fallo_en_codigo(entorno, monkeypatch, "VOTACION_FINALIZADA_INCONCLUSA")

    with pytest.raises(ErrorAuditoria):
        await entorno.entrada.procesar_pulsacion(Pulsacion("D-03", "9"))

    sesion = sesion_abierta(entorno)
    assert sesion.contexto_operativo.presencias["30000003"] is False
    assert sesion.palabra.orador_dni is None
    assert votacion.estado is EstadoVotacion.EN_CURSO
    assert votacion.resultado is None


async def test_dos_concejales_pidiendo_concurrentemente_siguen_orden_durable(
    tmp_path: Path,
) -> None:
    """La cola coincide con el orden efectivo de los L3, no con una suposición."""

    entorno = await crear_entorno(tmp_path)
    await asyncio.gather(
        entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "7")),
        entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "7")),
    )

    mensajes = [fila[5] for fila in filas_l1(entorno) if fila[4] == "PEDIDO_PALABRA_REGISTRADO"]
    dnis_durables = tuple(mensaje.split("DNI=", 1)[1].split(";", 1)[0] for mensaje in mensajes)
    assert sesion_abierta(entorno).palabra.cola_dnis == dnis_durables


async def test_doble_pedido_concurrente_del_mismo_concejal_no_duplica(tmp_path: Path) -> None:
    """Una adquisición agrega y la siguiente retira el mismo DNI."""

    entorno = await crear_entorno(tmp_path)
    respuestas = await asyncio.gather(
        entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "7")),
        entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "7")),
    )

    assert {resultado_palabra(respuesta).accion for respuesta in respuestas} == {
        AccionPalabra.PEDIDO_AGREGADO,
        AccionPalabra.PEDIDO_RETIRADO,
    }
    assert sesion_abierta(entorno).palabra.cola_dnis == ()


async def test_otorgar_concurrente_con_solicitud_refleja_el_orden_serializado(
    tmp_path: Path,
) -> None:
    """Ambos resultados admitidos se explican solo por el orden durable observado."""

    entorno = await crear_entorno(tmp_path)
    frontera = len(filas_l1(entorno))
    await asyncio.gather(
        entorno.palabra.otorgar_palabra(),
        entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "7")),
    )

    codigos = codigos_desde(entorno, frontera)
    palabra = sesion_abierta(entorno).palabra
    if codigos[0] == "COMANDO_PALABRA_SIN_EFECTO":
        assert palabra.orador_dni is None
        assert palabra.cola_dnis == ("30000001",)
    else:
        assert codigos[:2] == ["PULSACION_RECIBIDA", "PEDIDO_PALABRA_REGISTRADO"]
        assert palabra.orador_dni == "30000001"
        assert palabra.cola_dnis == ()


async def test_quitar_concurrente_con_tecla_del_orador_es_serializable(tmp_path: Path) -> None:
    """Quitar y tecla 7 nunca dejan al mismo DNI hablando y esperando."""

    entorno = await crear_entorno(tmp_path)
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "7"))
    await entorno.palabra.otorgar_palabra()

    await asyncio.gather(
        entorno.palabra.quitar_palabra(),
        entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "7")),
    )

    palabra = sesion_abierta(entorno).palabra
    assert palabra.orador_dni is None
    assert palabra.cola_dnis in ((), ("30000001",))


async def test_ausencia_concurrente_con_otorgar_nunca_deja_ausente_en_palabra(
    tmp_path: Path,
) -> None:
    """El primero ausentado se limpia cualquiera sea su turno frente a POST."""

    entorno = await crear_entorno(tmp_path, quorum=1)
    for dispositivo in ("D-01", "D-02"):
        await entorno.entrada.procesar_pulsacion(Pulsacion(dispositivo, "7"))

    await asyncio.gather(
        entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "9")),
        entorno.palabra.otorgar_palabra(),
    )

    sesion = sesion_abierta(entorno)
    assert sesion.contexto_operativo.presencias["30000001"] is False
    assert not sesion.palabra.esta_esperando("30000001")
    assert not sesion.palabra.es_orador("30000001")
    assert (sesion.palabra.orador_dni, sesion.palabra.cola_dnis) in (
        ("30000002", ()),
        (None, ("30000002",)),
    )


async def test_ausencia_concurrente_con_finalizacion_propia_es_coherente(
    tmp_path: Path,
) -> None:
    """La ausencia o la tecla propia finalizan una sola vez según el orden real."""

    entorno = await crear_entorno(tmp_path)
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "7"))
    await entorno.palabra.otorgar_palabra()

    await asyncio.gather(
        entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "9")),
        entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "7")),
    )

    sesion = sesion_abierta(entorno)
    assert sesion.contexto_operativo.presencias["30000001"] is False
    assert sesion.palabra.orador_dni is None
    assert not sesion.palabra.esta_esperando("30000001")


async def test_palabra_voto_y_presencia_concurrentes_comparten_un_orden(
    tmp_path: Path,
) -> None:
    """Durante EN_CURSO las tres mutaciones sobreviven sin segundo lock ni corrupción."""

    entorno = await crear_entorno(tmp_path, quorum=2)
    votacion = await entorno.votaciones.abrir_votacion(datos_votacion())

    respuestas = await asyncio.gather(
        entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "7")),
        entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "1")),
        entorno.entrada.procesar_pulsacion(Pulsacion("D-03", "9")),
    )

    sesion = sesion_abierta(entorno)
    assert all(respuesta.aceptada for respuesta in respuestas)
    assert sesion.palabra.cola_dnis == ("30000001",)
    assert sesion.contexto_operativo.presencias["30000003"] is False
    assert "30000002" in votacion.votos_ordinarios
    assert votacion.estado is EstadoVotacion.EN_CURSO
