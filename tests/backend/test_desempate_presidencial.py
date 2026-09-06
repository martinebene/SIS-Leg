"""Pruebas de dominio, auditoría y concurrencia del desempate de WP-014.

Los escenarios integrales usan los servicios reales y el mismo
``EjecutorMutaciones``. Las carreras se ordenan mediante una instrumentación
que controla cuándo cada comando intenta adquirir el lock productivo; de este
modo las afirmaciones no dependen del scheduling casual de ``asyncio``.
"""

from __future__ import annotations

import asyncio
import csv
from collections.abc import Awaitable, Callable
from dataclasses import FrozenInstanceError, dataclass
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import TypeVar

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
from sis_leg_backend.dominio.entrada import Pulsacion
from sis_leg_backend.dominio.errores import (
    ErrorDesempateYaEmitido,
    ErrorEstadoIncompatible,
    ErrorQuorumInsuficiente,
    ErrorVotacionNoCoincide,
    ErrorVotacionNoEmpatada,
)
from sis_leg_backend.dominio.estado import EstadoGlobal, EstadoOperativo
from sis_leg_backend.dominio.sesion import ActualizacionDatosInstitucionales
from sis_leg_backend.dominio.votacion import (
    BaseMayoria,
    DatosAperturaVotacion,
    EstadoVotacion,
    ResultadoVotacion,
    SentidoVotoDesempate,
    TipoMayoria,
    ValorVotoOrdinario,
    Votacion,
    VotoOrdinario,
)
from sis_leg_backend.hechos_operativos import ReferenciaHechoOperativo
from sis_leg_backend.servicios.entrada import ServicioEntradaTecla
from sis_leg_backend.servicios.preparacion import ServicioPreparacion
from sis_leg_backend.servicios.serializacion import EjecutorMutaciones
from sis_leg_backend.servicios.sesion import ServicioSesion
from sis_leg_backend.servicios.votacion import ServicioVotacion

pytestmark = pytest.mark.anyio

HORA_INICIO = datetime(2026, 8, 22, 14, 0, 0)
HORA_SESION = datetime(2026, 8, 22, 14, 5, 0)
HORA_APERTURA = datetime(2026, 8, 22, 14, 10, 0)
HORA_CIERRE = datetime(2026, 8, 22, 14, 11, 0)

ResultadoT = TypeVar("ResultadoT")


class EjecutorMutacionesControlado(EjecutorMutaciones):
    """Permite ordenar solicitudes sin reemplazar el lock productivo real."""

    def __init__(self) -> None:
        super().__init__()
        self._control_activo = False
        self._solicitudes: asyncio.Queue[asyncio.Event] = asyncio.Queue()

    def activar_control(self) -> None:
        """Hace observables las próximas entradas al serializador."""

        self._control_activo = True

    async def siguiente_permiso(self) -> asyncio.Event:
        """Devuelve el permiso asociado a la próxima operación en espera."""

        return await self._solicitudes.get()

    async def ejecutar(
        self,
        mutacion: Callable[[], Awaitable[ResultadoT]],
    ) -> ResultadoT:
        """Espera el permiso de prueba y luego usa la exclusión de producción."""

        if self._control_activo:
            permiso = asyncio.Event()
            await self._solicitudes.put(permiso)
            await permiso.wait()
        return await super().ejecutar(mutacion)


class GeneradorId:
    """Produce identificadores deterministas para el caso de comando obsoleto."""

    def __init__(self) -> None:
        self._numero = 0

    def __call__(self) -> str:
        """Incrementa la secuencia solamente cuando una apertura es aceptada."""

        self._numero += 1
        return f"votacion-{self._numero}"


@dataclass(frozen=True, slots=True)
class EntornoDesempate:
    """Agrupa estado y servicios que comparten el único serializador."""

    estado: EstadoOperativo
    ejecutor: EjecutorMutacionesControlado
    entrada: ServicioEntradaTecla
    sesion: ServicioSesion
    votaciones: ServicioVotacion


def datos_votacion(
    *,
    numero: int = 37,
    tipo_mayoria: TipoMayoria = TipoMayoria.SIMPLE,
) -> DatosAperturaVotacion:
    """Construye datos normalizados para una apertura SIMPLE o ESPECIAL."""

    return DatosAperturaVotacion(
        numero_votacion=numero,
        tipo="Mocion",
        tema=f"Tema de desempate {numero}",
        tipo_mayoria=tipo_mayoria,
        factor=0.0 if tipo_mayoria is TipoMayoria.SIMPLE else 0.5,
        base=BaseMayoria.VOTOS_COMPUTABLES,
    )


def crear_votacion_dominio(
    *,
    tipo_mayoria: TipoMayoria = TipoMayoria.SIMPLE,
) -> Votacion:
    """Crea una entidad aislada sin atajos de servicio ni estado global."""

    return Votacion(
        id="votacion-dominio",
        numero_votacion=37,
        tipo="Mocion",
        tema="Tema de dominio",
        tipo_mayoria=tipo_mayoria,
        factor=0.0 if tipo_mayoria is TipoMayoria.SIMPLE else 0.5,
        base=BaseMayoria.VOTOS_COMPUTABLES,
        fecha_hora_apertura=HORA_APERTURA,
    )


def cerrar_con_resultado(
    votacion: Votacion,
    resultado: ResultadoVotacion,
) -> None:
    """Cierra y aplica un resultado ordinario válido para preparar invariantes."""

    votacion.cerrar_recepcion(HORA_CIERRE)
    votacion.aplicar_resultado_ordinario(resultado)


async def crear_entorno(
    directorio: Path,
    *,
    quorum: int = 2,
    presentes: tuple[str, ...] = ("D-01", "D-02"),
    presidencia: str = "Ana Garcia",
) -> EntornoDesempate:
    """Prepara una sesión real con padrón, auditoría y servicios compartidos."""

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
    ejecutor = EjecutorMutacionesControlado()
    preparacion = ServicioPreparacion(
        estado,
        ejecutor,
        ruta_configuracion=ruta_configuracion,
        ruta_padron=ruta_padron,
        reloj=lambda: HORA_INICIO,
        fabrica_escritor=partial(EscritorAuditoriaCsv, reloj=lambda: HORA_INICIO),
    )
    entrada = ServicioEntradaTecla(
        estado,
        ejecutor,
        reloj_monotono=lambda: 10.0,
        reloj=lambda: HORA_CIERRE,
    )
    sesion = ServicioSesion(estado, ejecutor, reloj=lambda: HORA_SESION)
    votaciones = ServicioVotacion(
        estado,
        ejecutor,
        reloj=lambda: HORA_APERTURA,
        generador_id=GeneradorId(),
    )

    await preparacion.preparar_sala()
    await sesion.actualizar_preparacion(
        ActualizacionDatosInstitucionales(
            incluye_numero_sesion=True,
            numero_sesion=59,
            incluye_presidencia=True,
            presidencia=presidencia,
            incluye_secretaria_legislativa=True,
            secretaria_legislativa="Secretaría",
        )
    )
    for dispositivo in presentes:
        respuesta = await entrada.procesar_pulsacion(Pulsacion(dispositivo, "9"))
        assert respuesta.aceptada is True
    await sesion.abrir_sesion()
    return EntornoDesempate(estado, ejecutor, entrada, sesion, votaciones)


async def crear_empate(entorno: EntornoDesempate, *, numero: int = 37) -> Votacion:
    """Abre una SIMPLE y la autocierra empatada con dos votos opuestos."""

    votacion = await entorno.votaciones.abrir_votacion(datos_votacion(numero=numero))
    positivo = await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "1"))
    negativo = await entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "3"))
    assert positivo.aceptada is True
    assert negativo.aceptada is True
    assert votacion.resultado is ResultadoVotacion.EMPATADA
    return votacion


def leer_filas(ruta: Path) -> list[list[str]]:
    """Lee un CSV incluso después de que el cierre de sesión lo haya cerrado."""

    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.reader(archivo, delimiter=";"))


def ruta_l1(entorno: EntornoDesempate) -> Path:
    """Obtiene la ruta L1 desde el contexto auditable todavía activo."""

    contexto = entorno.estado.contexto_operativo_activo()
    assert contexto is not None
    return contexto.escritor_auditoria.rutas[NivelAuditoria.L1]


def instalar_fallo_en_evento(
    monkeypatch: pytest.MonkeyPatch,
    escritor: EscritorAuditoriaCsv,
    codigo_objetivo: str,
) -> None:
    """Falla exactamente el evento indicado y marca el writer no disponible."""

    registrar_original = escritor.registrar_evento

    def registrar_evento(
        nivel: NivelAuditoria,
        etiqueta: str,
        codigo_evento: str,
        mensaje: str,
        *,
        referencia: ReferenciaHechoOperativo | None = None,
    ) -> int:
        if codigo_evento == codigo_objetivo:
            monkeypatch.setattr(escritor, "_fallado", True)
            raise ErrorAuditoria(f"fallo simulado en {codigo_objetivo}")
        return registrar_original(nivel, etiqueta, codigo_evento, mensaje, referencia=referencia)

    monkeypatch.setattr(escritor, "registrar_evento", registrar_evento)


async def encolar_en_orden(
    ejecutor: EjecutorMutacionesControlado,
    primera: Awaitable[object],
    segunda: Awaitable[object],
) -> tuple[object | BaseException, object | BaseException]:
    """Garantiza que ambas operaciones esperen y libera primero la elegida."""

    ejecutor.activar_control()
    tarea_primera = asyncio.ensure_future(primera)
    permiso_primera = await ejecutor.siguiente_permiso()
    tarea_segunda = asyncio.ensure_future(segunda)
    permiso_segunda = await ejecutor.siguiente_permiso()

    permiso_primera.set()
    resultado_primera = (await asyncio.gather(tarea_primera, return_exceptions=True))[0]
    permiso_segunda.set()
    resultado_segunda = (await asyncio.gather(tarea_segunda, return_exceptions=True))[0]
    return resultado_primera, resultado_segunda


def test_votacion_nace_sin_voto_presidencial() -> None:
    """La nueva entidad opcional no altera el estado inicial de una votación."""

    votacion = crear_votacion_dominio()

    assert votacion.voto_desempate is None
    assert votacion.estado is EstadoVotacion.EN_CURSO
    assert votacion.resultado is None


@pytest.mark.parametrize(
    ("sentido", "resultado_final"),
    [
        (SentidoVotoDesempate.POSITIVO, ResultadoVotacion.APROBADA),
        (SentidoVotoDesempate.NEGATIVO, ResultadoVotacion.RECHAZADA),
    ],
)
def test_dominio_registra_y_consolida_desempate_sin_tocar_cierre_o_votos(
    sentido: SentidoVotoDesempate,
    resultado_final: ResultadoVotacion,
) -> None:
    """El voto presidencial es inmutable, único y ajeno al conteo ordinario."""

    votacion = crear_votacion_dominio()
    voto_positivo = VotoOrdinario("30000001", ValorVotoOrdinario.POSITIVO)
    voto_negativo = VotoOrdinario("30000002", ValorVotoOrdinario.NEGATIVO)
    votacion.registrar_voto(voto_positivo)
    votacion.registrar_voto(voto_negativo)
    cerrar_con_resultado(votacion, ResultadoVotacion.EMPATADA)
    votos_antes = dict(votacion.votos_ordinarios)
    conteos_antes = votacion.contar_votos_ordinarios()

    voto_desempate = votacion.preparar_voto_desempate(sentido, "  Presidencia vigente  ")
    assert votacion.voto_desempate is None
    votacion.registrar_voto_desempate(voto_desempate)

    assert votacion.estado is EstadoVotacion.CERRADA
    assert votacion.resultado is ResultadoVotacion.EMPATADA
    assert votacion.voto_desempate is voto_desempate
    assert voto_desempate.presidencia == "Presidencia vigente"
    assert voto_desempate.sentido is sentido
    with pytest.raises(FrozenInstanceError):
        voto_desempate.sentido = SentidoVotoDesempate.NEGATIVO  # pyright: ignore[reportAttributeAccessIssue]
    with pytest.raises(ValueError, match="ya fue emitido"):
        votacion.preparar_voto_desempate(sentido, "Otra Presidencia")

    votacion.consolidar_resultado_desempate()

    assert votacion.resultado is resultado_final
    assert votacion.fecha_hora_cierre == HORA_CIERRE
    assert dict(votacion.votos_ordinarios) == votos_antes
    assert votacion.votos_ordinarios["30000001"] is voto_positivo
    assert votacion.votos_ordinarios["30000002"] is voto_negativo
    assert votacion.contar_votos_ordinarios() == conteos_antes
    with pytest.raises(ValueError):
        votacion.consolidar_resultado_desempate()
    assert votacion.resultado is resultado_final


@pytest.mark.parametrize(
    "escenario",
    ["en_curso", "cerrada_sin_resultado", "aprobada", "rechazada", "inconclusa", "especial"],
)
def test_dominio_rechaza_estados_y_mayoria_incompatibles(escenario: str) -> None:
    """Solo SIMPLE + CERRADA + EMPATADA puede preparar el primer hecho."""

    tipo = TipoMayoria.ESPECIAL if escenario == "especial" else TipoMayoria.SIMPLE
    votacion = crear_votacion_dominio(tipo_mayoria=tipo)
    if escenario == "cerrada_sin_resultado":
        votacion.cerrar_recepcion(HORA_CIERRE)
    elif escenario in {"aprobada", "rechazada"}:
        resultado = (
            ResultadoVotacion.APROBADA if escenario == "aprobada" else ResultadoVotacion.RECHAZADA
        )
        cerrar_con_resultado(votacion, resultado)
    elif escenario == "inconclusa":
        votacion.finalizar_inconclusa_derivada(HORA_CIERRE)
    elif escenario == "especial":
        # El flujo normal nunca produce este estado; la construcción artificial
        # comprueba que el dominio igualmente mantiene la invariante.
        votacion.cerrar_recepcion(HORA_CIERRE)
        object.__setattr__(votacion, "_Votacion__resultado", ResultadoVotacion.EMPATADA)

    with pytest.raises(ValueError):
        votacion.preparar_voto_desempate(
            SentidoVotoDesempate.POSITIVO,
            "Presidencia",
        )
    assert votacion.voto_desempate is None


async def test_servicio_desempata_misma_instancia_con_presidencia_concejal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Quien ya votó como Concejal conserva además la facultad presidencial."""

    entorno = await crear_entorno(tmp_path)
    votacion = await crear_empate(entorno)
    sesion = entorno.estado.sesion_activa
    assert sesion is not None
    assert sesion.presidencia == "Ana Garcia"
    assert "30000001" in votacion.votos_ordinarios
    fecha_antes = votacion.fecha_hora_cierre
    votos_antes = dict(votacion.votos_ordinarios)
    conteos_antes = votacion.contar_votos_ordinarios()
    escritor = sesion.contexto_operativo.escritor_auditoria
    registrar_original = escritor.registrar_evento
    estados_al_auditar: list[tuple[str, ResultadoVotacion | None, object | None]] = []

    def registrar_evento(
        nivel: NivelAuditoria,
        etiqueta: str,
        codigo_evento: str,
        mensaje: str,
        *,
        referencia: ReferenciaHechoOperativo | None = None,
    ) -> int:
        if codigo_evento in {
            "VOTO_DESEMPATE_PRESIDENCIAL",
            "VOTACION_RESULTADO_DESEMPATE",
        }:
            estados_al_auditar.append((codigo_evento, votacion.resultado, votacion.voto_desempate))
        return registrar_original(nivel, etiqueta, codigo_evento, mensaje, referencia=referencia)

    monkeypatch.setattr(escritor, "registrar_evento", registrar_evento)
    await entorno.votaciones.desempatar_votacion(
        votacion.id,
        SentidoVotoDesempate.POSITIVO,
    )

    assert votacion is sesion.votaciones[0]
    assert votacion.estado is EstadoVotacion.CERRADA
    assert votacion.resultado is ResultadoVotacion.APROBADA
    assert votacion.voto_desempate is not None
    assert votacion.voto_desempate.presidencia == "Ana Garcia"
    assert votacion.voto_desempate.sentido is SentidoVotoDesempate.POSITIVO
    assert entorno.estado.votacion_activa is None
    assert votacion.fecha_hora_cierre == fecha_antes
    assert dict(votacion.votos_ordinarios) == votos_antes
    assert votacion.contar_votos_ordinarios() == conteos_antes
    assert estados_al_auditar[0] == (
        "VOTO_DESEMPATE_PRESIDENCIAL",
        ResultadoVotacion.EMPATADA,
        None,
    )
    assert estados_al_auditar[1][0:2] == (
        "VOTACION_RESULTADO_DESEMPATE",
        ResultadoVotacion.EMPATADA,
    )
    assert estados_al_auditar[1][2] is votacion.voto_desempate

    filas = leer_filas(ruta_l1(entorno))
    codigos = [fila[4] for fila in filas]
    assert [
        codigo
        for codigo in codigos
        if codigo
        in {
            "VOTACION_CERRADA_COMPLETITUD",
            "VOTACION_RESULTADO_EMPATE",
            "VOTO_DESEMPATE_PRESIDENCIAL",
            "VOTACION_RESULTADO_DESEMPATE",
        }
    ] == [
        "VOTACION_CERRADA_COMPLETITUD",
        "VOTACION_RESULTADO_EMPATE",
        "VOTO_DESEMPATE_PRESIDENCIAL",
        "VOTACION_RESULTADO_DESEMPATE",
    ]
    assert codigos.count("VOTO_ORDINARIO_REGISTRADO") == 2
    for fila in filas[-2:]:
        assert fila[2:4] == ["L3", "VOTACION"]
        for fragmento in (
            "numero_votacion=37",
            f"id={votacion.id}",
            "presidencia=Ana Garcia",
            "sentido=POSITIVO",
            "resultado_previo=EMPATADA",
            "votos_ordinarios=2",
            "positivos=1",
            "negativos=1",
            "abstenciones=0",
        ):
            assert fragmento in fila[5]
    assert "estado_previo=CERRADA" in filas[-2][5]
    assert "resultado_final=APROBADA" in filas[-1][5]


async def test_fallo_primer_evento_no_almacena_voto_ni_libera(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin el primer hecho durable no existe ninguna mutación presidencial."""

    entorno = await crear_entorno(tmp_path)
    votacion = await crear_empate(entorno)
    contexto = entorno.estado.contexto_operativo_activo()
    assert contexto is not None
    escritor = contexto.escritor_auditoria
    fecha_antes = votacion.fecha_hora_cierre
    votos_antes = dict(votacion.votos_ordinarios)
    instalar_fallo_en_evento(monkeypatch, escritor, "VOTO_DESEMPATE_PRESIDENCIAL")

    with pytest.raises(ErrorAuditoria):
        await entorno.votaciones.desempatar_votacion(
            votacion.id,
            SentidoVotoDesempate.NEGATIVO,
        )

    assert votacion.estado is EstadoVotacion.CERRADA
    assert votacion.resultado is ResultadoVotacion.EMPATADA
    assert votacion.voto_desempate is None
    assert votacion.fecha_hora_cierre == fecha_antes
    assert dict(votacion.votos_ordinarios) == votos_antes
    assert entorno.estado.votacion_activa is votacion
    assert escritor.fallado is True


async def test_fallo_segundo_evento_conserva_voto_y_estado_tecnico(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El voto durable no se revierte si falta el hecho del resultado final."""

    entorno = await crear_entorno(tmp_path)
    votacion = await crear_empate(entorno)
    contexto = entorno.estado.contexto_operativo_activo()
    assert contexto is not None
    escritor = contexto.escritor_auditoria
    fecha_antes = votacion.fecha_hora_cierre
    votos_antes = dict(votacion.votos_ordinarios)
    instalar_fallo_en_evento(monkeypatch, escritor, "VOTACION_RESULTADO_DESEMPATE")

    with pytest.raises(ErrorAuditoria):
        await entorno.votaciones.desempatar_votacion(
            votacion.id,
            SentidoVotoDesempate.NEGATIVO,
        )

    voto = votacion.voto_desempate
    assert voto is not None
    assert voto.presidencia == "Ana Garcia"
    assert voto.sentido is SentidoVotoDesempate.NEGATIVO
    assert votacion.estado is EstadoVotacion.CERRADA
    assert votacion.resultado is ResultadoVotacion.EMPATADA
    assert votacion.fecha_hora_cierre == fecha_antes
    assert dict(votacion.votos_ordinarios) == votos_antes
    assert entorno.estado.votacion_activa is votacion
    assert escritor.fallado is True

    # El segundo intento detectaría DESEMPATE_YA_EMITIDO, pero al intentar
    # auditar ese rechazo prevalece la indisponibilidad técnica del writer.
    with pytest.raises(ErrorAuditoria):
        await entorno.votaciones.desempatar_votacion(
            votacion.id,
            SentidoVotoDesempate.POSITIVO,
        )
    assert votacion.voto_desempate is voto
    assert votacion.resultado is ResultadoVotacion.EMPATADA


async def test_desempate_completo_usa_una_sola_adquisicion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Los dos hechos L3 no readquieren el serializador entre sí."""

    entorno = await crear_entorno(tmp_path)
    votacion = await crear_empate(entorno)
    ejecutar_original = entorno.ejecutor.ejecutar
    adquisiciones = 0

    async def ejecutar(mutacion: Callable[[], Awaitable[ResultadoT]]) -> ResultadoT:
        nonlocal adquisiciones
        adquisiciones += 1
        return await ejecutar_original(mutacion)

    monkeypatch.setattr(entorno.ejecutor, "ejecutar", ejecutar)
    await entorno.votaciones.desempatar_votacion(
        votacion.id,
        SentidoVotoDesempate.POSITIVO,
    )

    assert adquisiciones == 1
    assert votacion.resultado is ResultadoVotacion.APROBADA


async def test_rechazo_saludable_de_estado_tecnico_distingue_voto_previo(
    tmp_path: Path,
) -> None:
    """Una construcción parcial saludable tampoco permite otro desempate."""

    entorno = await crear_entorno(tmp_path)
    votacion = await crear_empate(entorno)
    voto = votacion.preparar_voto_desempate(
        SentidoVotoDesempate.POSITIVO,
        "Ana Garcia",
    )
    votacion.registrar_voto_desempate(voto)

    with pytest.raises(ErrorDesempateYaEmitido):
        await entorno.votaciones.desempatar_votacion(
            votacion.id,
            SentidoVotoDesempate.NEGATIVO,
        )
    assert entorno.estado.votacion_activa is votacion
    assert votacion.resultado is ResultadoVotacion.EMPATADA
    assert votacion.voto_desempate is voto
    fila = leer_filas(ruta_l1(entorno))[-1]
    assert fila[2:5] == ["L2", "VOTACION", "COMANDO_VOTACION_RECHAZADO"]
    assert "operación=desempatar votación" in fila[5]
    assert "código=DESEMPATE_YA_EMITIDO" in fila[5]


@pytest.mark.parametrize("cierre_primero", [False, True], ids=["desempate", "cierre"])
async def test_carrera_desempate_vs_cierre_sesion(
    tmp_path: Path,
    cierre_primero: bool,
) -> None:
    """El orden real decide entre resultado presidencial e INCONCLUSA."""

    entorno = await crear_entorno(tmp_path)
    votacion = await crear_empate(entorno)
    ruta = ruta_l1(entorno)
    fecha_antes = votacion.fecha_hora_cierre
    votos_antes = dict(votacion.votos_ordinarios)
    desempate = entorno.votaciones.desempatar_votacion(
        votacion.id,
        SentidoVotoDesempate.POSITIVO,
    )
    cierre = entorno.sesion.cerrar_sesion()

    if cierre_primero:
        primero, segundo = await encolar_en_orden(entorno.ejecutor, cierre, desempate)
        assert primero is None
        assert isinstance(segundo, ErrorEstadoIncompatible)
        assert votacion.resultado is ResultadoVotacion.INCONCLUSA
        assert votacion.voto_desempate is None
    else:
        primero, segundo = await encolar_en_orden(entorno.ejecutor, desempate, cierre)
        assert primero is None
        assert segundo is None
        assert votacion.resultado is ResultadoVotacion.APROBADA
        assert votacion.voto_desempate is not None

    assert entorno.estado.estado_global is EstadoGlobal.SIN_PREPARAR
    assert entorno.estado.votacion_activa is None
    assert votacion.fecha_hora_cierre == fecha_antes
    assert dict(votacion.votos_ordinarios) == votos_antes
    codigos = [fila[4] for fila in leer_filas(ruta)]
    if cierre_primero:
        assert "VOTO_DESEMPATE_PRESIDENCIAL" not in codigos
        assert codigos[-2:] == ["VOTACION_FINALIZADA_INCONCLUSA", "SESION_CERRADA"]
    else:
        assert codigos[-3:] == [
            "VOTO_DESEMPATE_PRESIDENCIAL",
            "VOTACION_RESULTADO_DESEMPATE",
            "SESION_CERRADA",
        ]


@pytest.mark.parametrize("cambio_primero", [True, False], ids=["cambio", "desempate"])
async def test_carrera_desempate_vs_cambio_presidencia(
    tmp_path: Path,
    cambio_primero: bool,
) -> None:
    """El voto conserva la autoridad vigente al adquirir el serializador."""

    entorno = await crear_entorno(tmp_path)
    votacion = await crear_empate(entorno)
    cambio = entorno.sesion.actualizar_autoridades(
        ActualizacionDatosInstitucionales(
            incluye_presidencia=True,
            presidencia="Nueva Presidencia",
        )
    )
    desempate = entorno.votaciones.desempatar_votacion(
        votacion.id,
        SentidoVotoDesempate.NEGATIVO,
    )

    if cambio_primero:
        primero, segundo = await encolar_en_orden(entorno.ejecutor, cambio, desempate)
        presidencia_esperada = "Nueva Presidencia"
    else:
        primero, segundo = await encolar_en_orden(entorno.ejecutor, desempate, cambio)
        presidencia_esperada = "Ana Garcia"

    assert primero is None
    assert segundo is None
    assert votacion.resultado is ResultadoVotacion.RECHAZADA
    assert votacion.voto_desempate is not None
    assert votacion.voto_desempate.presidencia == presidencia_esperada
    sesion = entorno.estado.sesion_activa
    assert sesion is not None
    assert sesion.presidencia == "Nueva Presidencia"


async def test_dos_desempates_concurrentes_solo_permiten_un_ganador(
    tmp_path: Path,
) -> None:
    """La segunda adquisición observa la referencia liberada y audita rechazo."""

    entorno = await crear_entorno(tmp_path)
    votacion = await crear_empate(entorno)

    primero, segundo = await encolar_en_orden(
        entorno.ejecutor,
        entorno.votaciones.desempatar_votacion(
            votacion.id,
            SentidoVotoDesempate.POSITIVO,
        ),
        entorno.votaciones.desempatar_votacion(
            votacion.id,
            SentidoVotoDesempate.NEGATIVO,
        ),
    )

    assert primero is None
    assert isinstance(segundo, ErrorVotacionNoEmpatada)
    assert votacion.resultado is ResultadoVotacion.APROBADA
    assert votacion.voto_desempate is not None
    assert votacion.voto_desempate.sentido is SentidoVotoDesempate.POSITIVO
    assert entorno.estado.votacion_activa is None
    codigos = [fila[4] for fila in leer_filas(ruta_l1(entorno))]
    assert codigos.count("VOTO_DESEMPATE_PRESIDENCIAL") == 1
    assert codigos.count("VOTACION_RESULTADO_DESEMPATE") == 1
    assert codigos[-1] == "COMANDO_VOTACION_RECHAZADO"


async def test_comando_obsoleto_para_a_no_afecta_empate_b(
    tmp_path: Path,
) -> None:
    """El id se compara al ejecutar, después de que B ocupó la referencia."""

    entorno = await crear_entorno(tmp_path)
    primera = await crear_empate(entorno)
    entorno.ejecutor.activar_control()
    tarea_obsoleta = asyncio.ensure_future(
        entorno.votaciones.desempatar_votacion(
            primera.id,
            SentidoVotoDesempate.NEGATIVO,
        )
    )
    permiso_obsoleto = await entorno.ejecutor.siguiente_permiso()

    tarea_ganadora = asyncio.ensure_future(
        entorno.votaciones.desempatar_votacion(
            primera.id,
            SentidoVotoDesempate.POSITIVO,
        )
    )
    permiso_ganador = await entorno.ejecutor.siguiente_permiso()
    permiso_ganador.set()
    await tarea_ganadora
    assert primera.resultado is ResultadoVotacion.APROBADA

    tarea_apertura = asyncio.ensure_future(
        entorno.votaciones.abrir_votacion(datos_votacion(numero=38))
    )
    permiso_apertura = await entorno.ejecutor.siguiente_permiso()
    permiso_apertura.set()
    segunda = await tarea_apertura
    # Para reproducir el caso institucional completo, B también llega a empate
    # antes de que el comando viejo de A obtenga el lock.
    tarea_positivo = asyncio.ensure_future(
        entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "1"))
    )
    permiso_positivo = await entorno.ejecutor.siguiente_permiso()
    permiso_positivo.set()
    await tarea_positivo
    tarea_negativo = asyncio.ensure_future(
        entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "3"))
    )
    permiso_negativo = await entorno.ejecutor.siguiente_permiso()
    permiso_negativo.set()
    await tarea_negativo
    assert segunda.resultado is ResultadoVotacion.EMPATADA

    votos_b = dict(segunda.votos_ordinarios)
    fecha_b = segunda.fecha_hora_cierre
    permiso_obsoleto.set()
    resultado_obsoleto = (await asyncio.gather(tarea_obsoleta, return_exceptions=True))[0]

    assert isinstance(resultado_obsoleto, ErrorVotacionNoCoincide)
    assert entorno.estado.votacion_activa is segunda
    assert segunda.resultado is ResultadoVotacion.EMPATADA
    assert segunda.voto_desempate is None
    assert segunda.fecha_hora_cierre == fecha_b
    assert dict(segunda.votos_ordinarios) == votos_b


async def test_perdida_quorum_posterior_no_impide_desempate(
    tmp_path: Path,
) -> None:
    """No se consulta quórum para resolver un empate ya cerrado."""

    entorno = await crear_entorno(tmp_path)
    votacion = await crear_empate(entorno)
    fecha_antes = votacion.fecha_hora_cierre
    votos_antes = dict(votacion.votos_ordinarios)

    retiro = await entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "9"))
    assert retiro.aceptada is True
    contexto = entorno.estado.contexto_operativo_activo()
    assert contexto is not None
    assert contexto.quorum_alcanzado() is False
    assert votacion.resultado is ResultadoVotacion.EMPATADA
    assert entorno.estado.votacion_activa is votacion

    await entorno.votaciones.desempatar_votacion(
        votacion.id,
        SentidoVotoDesempate.NEGATIVO,
    )

    assert votacion.resultado is ResultadoVotacion.RECHAZADA
    assert votacion.fecha_hora_cierre == fecha_antes
    assert dict(votacion.votos_ordinarios) == votos_antes
    assert entorno.estado.votacion_activa is None
    with pytest.raises(ErrorQuorumInsuficiente):
        await entorno.votaciones.abrir_votacion(datos_votacion(numero=38))


async def test_desempate_sin_sesion_usa_error_global_estable() -> None:
    """Fuera de SESION_ABIERTA no existe contexto presidencial autoritativo."""

    servicio = ServicioVotacion(EstadoOperativo(), EjecutorMutaciones())

    with pytest.raises(ErrorEstadoIncompatible):
        await servicio.desempatar_votacion(
            "inexistente",
            SentidoVotoDesempate.POSITIVO,
        )
