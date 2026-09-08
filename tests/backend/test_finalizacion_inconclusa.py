"""Regresiones integrales de finalización inconclusa de WP-013.

Los escenarios usan estado, writer y servicios reales. Las carreras incorporan
un ``EjecutorMutaciones`` instrumentado que permite encolar dos operaciones y
liberarlas en un orden explícito; no dependen del orden accidental de
``asyncio.gather``.
"""

from __future__ import annotations

import asyncio
import csv
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
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
from sis_leg_backend.dominio.entrada import Pulsacion, RespuestaEntrada
from sis_leg_backend.dominio.errores import (
    ErrorEstadoIncompatible,
    ErrorQuorumInsuficiente,
    ErrorVotacionNoCoincide,
    ErrorVotacionNoEnCurso,
    ErrorVotacionPendiente,
)
from sis_leg_backend.dominio.estado import EstadoGlobal, EstadoOperativo
from sis_leg_backend.dominio.sesion import ActualizacionDatosInstitucionales
from sis_leg_backend.dominio.votacion import (
    BaseMayoria,
    DatosAperturaVotacion,
    EstadoVotacion,
    ResultadoVotacion,
    TipoMayoria,
    ValorVotoOrdinario,
    Votacion,
    VotoOrdinario,
)
from sis_leg_backend.hechos_operativos import ReferenciaHechoOperativo
from sis_leg_backend.servicios.acta_institucional import (
    EstadoCopiaExterna,
    ResultadoCierreInstitucional,
)
from sis_leg_backend.servicios.entrada import ServicioEntradaTecla
from sis_leg_backend.servicios.preparacion import ServicioPreparacion
from sis_leg_backend.servicios.serializacion import EjecutorMutaciones
from sis_leg_backend.servicios.sesion import ServicioSesion
from sis_leg_backend.servicios.votacion import ServicioVotacion

pytestmark = pytest.mark.anyio

HORA_INICIO = datetime(2026, 8, 22, 10, 0, 0)
HORA_SESION = datetime(2026, 8, 22, 10, 5, 0)
HORA_APERTURA = datetime(2026, 8, 22, 10, 10, 0)
HORA_FINALIZACION = datetime(2026, 8, 22, 10, 15, 0)

ResultadoT = TypeVar("ResultadoT")


class RelojSecuencial:
    """Entrega instantes previstos y luego conserva el último para simplificar tests."""

    def __init__(self, *instantes: datetime) -> None:
        self._instantes = instantes
        self._indice = 0

    def __call__(self) -> datetime:
        """Devuelve el siguiente instante sin depender del reloj del proceso."""

        indice = min(self._indice, len(self._instantes) - 1)
        self._indice += 1
        return self._instantes[indice]


class EjecutorMutacionesControlado(EjecutorMutaciones):
    """Instrumenta la entrada al ejecutor real para ordenar carreras.

    Mientras el control está inactivo se comporta exactamente como la clase
    productiva y permite preparar el escenario. Al activarlo, cada operación
    publica un permiso y espera. El test libera primero una, espera que complete
    bajo el lock real, y recién entonces libera la segunda.
    """

    def __init__(self) -> None:
        super().__init__()
        self._control_activo = False
        self._solicitudes: asyncio.Queue[asyncio.Event] = asyncio.Queue()

    def activar_control(self) -> None:
        """Hace observables las próximas adquisiciones sin cambiar su lógica."""

        self._control_activo = True

    async def siguiente_permiso(self) -> asyncio.Event:
        """Espera hasta que una operación real haya solicitado entrar al lock."""

        return await self._solicitudes.get()

    async def ejecutar(
        self,
        mutacion: Callable[[], Awaitable[ResultadoT]],
    ) -> ResultadoT:
        """Espera el permiso de prueba y luego delega al lock productivo."""

        if self._control_activo:
            permiso = asyncio.Event()
            await self._solicitudes.put(permiso)
            await permiso.wait()
        return await super().ejecutar(mutacion)


@dataclass(frozen=True, slots=True)
class EntornoInconclusa:
    """Agrupa una única fuente de estado, ejecutor y servicios reales."""

    estado: EstadoOperativo
    ejecutor: EjecutorMutacionesControlado
    entrada: ServicioEntradaTecla
    sesion: ServicioSesion
    votaciones: ServicioVotacion


def datos_votacion(*, numero: int = 37, tema: str = "Tema WP-013") -> DatosAperturaVotacion:
    """Crea datos SIMPLE válidos; la finalización no debe calcularlos."""

    return DatosAperturaVotacion(
        numero_votacion=numero,
        tipo="Mocion",
        tema=tema,
        tipo_mayoria=TipoMayoria.SIMPLE,
        factor=0.0,
        base=BaseMayoria.VOTOS_COMPUTABLES,
    )


def crear_votacion_dominio() -> Votacion:
    """Construye una entidad aislada para probar sus guardas internas."""

    return Votacion(
        id="votacion-dominio",
        numero_votacion=37,
        tipo="Mocion",
        tema="Tema de dominio",
        tipo_mayoria=TipoMayoria.SIMPLE,
        factor=0.0,
        base=BaseMayoria.VOTOS_COMPUTABLES,
        fecha_hora_apertura=HORA_APERTURA,
    )


async def crear_entorno(
    directorio: Path,
    *,
    quorum: int = 2,
    presentes: tuple[str, ...] = ("D-01", "D-02"),
    abrir_votacion: bool = True,
) -> tuple[EntornoInconclusa, Votacion | None]:
    """Prepara y abre una sesión real con los dispositivos indicados."""

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
        reloj=lambda: HORA_FINALIZACION,
    )
    sesion = ServicioSesion(
        estado,
        ejecutor,
        reloj=RelojSecuencial(HORA_SESION, HORA_FINALIZACION),
    )
    votaciones = ServicioVotacion(
        estado,
        ejecutor,
        reloj=RelojSecuencial(
            HORA_APERTURA,
            HORA_FINALIZACION,
            HORA_APERTURA + timedelta(minutes=1),
            HORA_FINALIZACION + timedelta(minutes=1),
        ),
        generador_id=_GeneradorId(),
    )
    await preparacion.preparar_sala()
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
    entorno = EntornoInconclusa(estado, ejecutor, entrada, sesion, votaciones)
    votacion = await votaciones.abrir_votacion(datos_votacion()) if abrir_votacion else None
    return entorno, votacion


class _GeneradorId:
    """Produce ids distintos y deterministas para probar comandos obsoletos."""

    def __init__(self) -> None:
        self._numero = 0

    def __call__(self) -> str:
        """Incrementa la secuencia solo cuando una apertura válida crea entidad."""

        self._numero += 1
        return f"votacion-{self._numero}"


def filas_l1(estado: EstadoOperativo) -> list[list[str]]:
    """Lee el CSV de máximo detalle mientras el contexto continúa activo."""

    contexto = estado.contexto_operativo_activo()
    assert contexto is not None
    return leer_filas(contexto.escritor_auditoria.rutas[NivelAuditoria.L1])


def leer_filas(ruta: Path) -> list[list[str]]:
    """Lee un CSV canónico aunque el writer ya haya sido cerrado."""

    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.reader(archivo, delimiter=";"))


def instalar_fallo_en_evento(
    monkeypatch: pytest.MonkeyPatch,
    escritor: EscritorAuditoriaCsv,
    codigo_objetivo: str,
) -> None:
    """Falla exactamente un hecho y deja el writer en fallo cerrado."""

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


def afirmar_cierre_completado(resultado: object) -> None:
    """Comprueba que la operación observada sea el cierre de sesión ya completado.

    Desde WP-085 ``cerrar_sesion`` ya no devuelve ``None``: entrega el resultado
    del informe de acta y de la copia externa. En estas carreras la configuración
    de prueba no declara ``paths.logs_copy_dir``, así que el desenlace esperado es
    siempre acta generada y copia omitida. Comprobarlo acá mantiene las pruebas
    afirmando lo mismo que antes —"el cierre se completó sin error"— con el
    contrato nuevo.
    """

    assert isinstance(resultado, ResultadoCierreInstitucional)
    assert resultado.acta_generada is True
    assert resultado.copia_externa is EstadoCopiaExterna.OMITIDA


async def encolar_en_orden(
    ejecutor: EjecutorMutacionesControlado,
    primera: Awaitable[object],
    segunda: Awaitable[object],
) -> tuple[object | BaseException, object | BaseException]:
    """Encola dos operaciones y garantiza cuál completa primero bajo el lock."""

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


def test_dominio_finaliza_manual_una_vez_y_preserva_datos_y_votos() -> None:
    """EN_CURSO + None pasa a CERRADA + INCONCLUSA sin reemplazar datos."""

    votacion = crear_votacion_dominio()
    voto = VotoOrdinario(dni="30000001", valor=ValorVotoOrdinario.POSITIVO)
    votacion.registrar_voto(voto)
    datos_antes = (
        votacion.id,
        votacion.numero_votacion,
        votacion.tipo,
        votacion.tema,
        votacion.tipo_mayoria,
        votacion.factor,
        votacion.base,
        votacion.fecha_hora_apertura,
    )

    votacion.finalizar_inconclusa_manual(HORA_FINALIZACION, "  decisión operativa  ")

    assert votacion.estado is EstadoVotacion.CERRADA
    assert votacion.resultado is ResultadoVotacion.INCONCLUSA
    assert votacion.fecha_hora_cierre == HORA_FINALIZACION
    assert votacion.motivo_finalizacion_manual == "decisión operativa"
    assert votacion.votos_ordinarios["30000001"] is voto
    assert datos_antes == (
        votacion.id,
        votacion.numero_votacion,
        votacion.tipo,
        votacion.tema,
        votacion.tipo_mayoria,
        votacion.factor,
        votacion.base,
        votacion.fecha_hora_apertura,
    )
    with pytest.raises(ValueError):
        votacion.finalizar_inconclusa_manual(
            HORA_FINALIZACION + timedelta(seconds=1),
            "otro motivo",
        )
    with pytest.raises(ValueError):
        votacion.registrar_voto(VotoOrdinario(dni="30000002", valor=ValorVotoOrdinario.NEGATIVO))
    with pytest.raises(ValueError):
        votacion.calcular_resultado_ordinario(cantidad_total_cuerpo=12)
    assert votacion.fecha_hora_cierre == HORA_FINALIZACION
    assert votacion.motivo_finalizacion_manual == "decisión operativa"


def test_dominio_causas_derivadas_no_crean_motivo_y_empate_conserva_fecha() -> None:
    """Las primitivas derivadas son finales y la especial de sesión preserva cierre."""

    derivada = crear_votacion_dominio()
    derivada.finalizar_inconclusa_derivada(HORA_FINALIZACION)
    assert derivada.motivo_finalizacion_manual is None
    assert derivada.resultado is ResultadoVotacion.INCONCLUSA

    empate = crear_votacion_dominio()
    empate.cerrar_recepcion(HORA_FINALIZACION)
    empate.aplicar_resultado_ordinario(ResultadoVotacion.EMPATADA)
    empate.finalizar_empate_inconcluso_por_cierre_sesion()
    assert empate.estado is EstadoVotacion.CERRADA
    assert empate.resultado is ResultadoVotacion.INCONCLUSA
    assert empate.fecha_hora_cierre == HORA_FINALIZACION
    assert empate.motivo_finalizacion_manual is None

    aprobada = crear_votacion_dominio()
    aprobada.cerrar_recepcion(HORA_FINALIZACION)
    aprobada.aplicar_resultado_ordinario(ResultadoVotacion.APROBADA)
    with pytest.raises(ValueError):
        aprobada.finalizar_empate_inconcluso_por_cierre_sesion()
    with pytest.raises(ValueError):
        aprobada.finalizar_inconclusa_derivada(HORA_FINALIZACION)
    assert aprobada.resultado is ResultadoVotacion.APROBADA


async def test_manual_cero_votos_normaliza_audita_y_conserva_instancia(
    tmp_path: Path,
) -> None:
    """El comando manual no calcula mayoría y libera solo tras el evento L3."""

    entorno, votacion = await crear_entorno(tmp_path)
    assert votacion is not None
    sesion = entorno.estado.sesion_activa
    assert sesion is not None

    await entorno.votaciones.finalizar_votacion_manualmente(
        votacion.id,
        "  decisión de Moderación  ",
    )

    assert votacion is sesion.votaciones[0]
    assert votacion.estado is EstadoVotacion.CERRADA
    assert votacion.resultado is ResultadoVotacion.INCONCLUSA
    assert votacion.fecha_hora_cierre == HORA_FINALIZACION
    assert votacion.motivo_finalizacion_manual == "decisión de Moderación"
    assert votacion.votos_ordinarios == {}
    assert entorno.estado.votacion_activa is None
    fila = filas_l1(entorno.estado)[-1]
    assert fila[2:5] == ["L3", "VOTACION", "VOTACION_FINALIZADA_INCONCLUSA"]
    for fragmento in (
        "numero_votacion=37",
        f"id={votacion.id}",
        "causa=MANUAL",
        "estado_previo=EN_CURSO",
        "resultado_previo=None",
        "votos_conservados=0",
        "resultado_nuevo=INCONCLUSA",
        "motivo_manual=decisión de Moderación",
    ):
        assert fragmento in fila[5]


async def test_manual_preserva_votos_parciales_y_rechaza_id_obsoleto(
    tmp_path: Path,
) -> None:
    """Los votos sobreviven y una orden para A nunca alcanza a la nueva B."""

    entorno, primera = await crear_entorno(tmp_path)
    assert primera is not None
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "1"))
    voto = primera.votos_ordinarios["30000001"]
    await entorno.votaciones.finalizar_votacion_manualmente(primera.id, "Cambio de tema")
    segunda = await entorno.votaciones.abrir_votacion(datos_votacion(numero=38, tema="Tema B"))

    with pytest.raises(ErrorVotacionNoCoincide):
        await entorno.votaciones.finalizar_votacion_manualmente(primera.id, "Comando viejo")

    assert primera.votos_ordinarios["30000001"] is voto
    assert primera.resultado is ResultadoVotacion.INCONCLUSA
    assert segunda.estado is EstadoVotacion.EN_CURSO
    assert segunda.resultado is None
    assert segunda.fecha_hora_cierre is None
    assert segunda.motivo_finalizacion_manual is None
    assert entorno.estado.votacion_activa is segunda
    fila = filas_l1(entorno.estado)[-1]
    assert fila[2:5] == ["L2", "VOTACION", "COMANDO_VOTACION_RECHAZADO"]
    assert "VOTACION_NO_COINCIDE" in fila[5]
    assert f"id_solicitado={primera.id}" in fila[5]


async def test_rechazos_manuales_estables_no_mutan(
    tmp_path: Path,
) -> None:
    """Estado, ausencia de activa y etapa cerrada se distinguen sin setters libres."""

    estado = EstadoOperativo()
    servicio_vacio = ServicioVotacion(estado, EjecutorMutaciones())
    with pytest.raises(ErrorEstadoIncompatible):
        await servicio_vacio.finalizar_votacion_manualmente("inexistente", "motivo")

    entorno, votacion = await crear_entorno(tmp_path)
    assert votacion is not None
    entorno.estado.votacion_activa = None
    with pytest.raises(ErrorVotacionNoEnCurso):
        await entorno.votaciones.finalizar_votacion_manualmente(votacion.id, "motivo")

    entorno.estado.votacion_activa = votacion
    votacion.cerrar_recepcion(HORA_FINALIZACION)
    with pytest.raises(ErrorVotacionNoEnCurso):
        await entorno.votaciones.finalizar_votacion_manualmente(votacion.id, "motivo")
    assert votacion.resultado is None
    assert votacion.motivo_finalizacion_manual is None


async def test_fallo_manual_no_muta_y_deja_writer_fallado(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El evento L3 es frontera previa a fecha, motivo, resultado y liberación."""

    entorno, votacion = await crear_entorno(tmp_path)
    assert votacion is not None
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "1"))
    contexto = entorno.estado.contexto_operativo_activo()
    assert contexto is not None
    instalar_fallo_en_evento(
        monkeypatch,
        contexto.escritor_auditoria,
        "VOTACION_FINALIZADA_INCONCLUSA",
    )

    with pytest.raises(ErrorAuditoria):
        await entorno.votaciones.finalizar_votacion_manualmente(votacion.id, "motivo")

    assert votacion.estado is EstadoVotacion.EN_CURSO
    assert votacion.resultado is None
    assert votacion.fecha_hora_cierre is None
    assert votacion.motivo_finalizacion_manual is None
    assert set(votacion.votos_ordinarios) == {"30000001"}
    assert entorno.estado.votacion_activa is votacion
    assert contexto.escritor_auditoria.fallado is True


async def test_perdida_quorum_prevalece_sobre_completitud_y_conserva_votos(
    tmp_path: Path,
) -> None:
    """La retirada crítica debe dar INCONCLUSA, nunca resultado ordinario."""

    entorno, votacion = await crear_entorno(tmp_path)
    assert votacion is not None
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "1"))

    respuesta = await entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "9"))

    assert respuesta.aceptada is True
    assert votacion.estado is EstadoVotacion.CERRADA
    assert votacion.resultado is ResultadoVotacion.INCONCLUSA
    assert votacion.fecha_hora_cierre == HORA_FINALIZACION
    assert votacion.motivo_finalizacion_manual is None
    assert set(votacion.votos_ordinarios) == {"30000001"}
    assert entorno.estado.votacion_activa is None
    codigos = [fila[4] for fila in filas_l1(entorno.estado)]
    assert "VOTACION_CERRADA_COMPLETITUD" not in codigos
    assert "VOTACION_RESULTADO_FINAL" not in codigos
    fila = filas_l1(entorno.estado)[-1]
    assert fila[4] == "VOTACION_FINALIZADA_INCONCLUSA"
    for fragmento in (
        "causa=PERDIDA_QUORUM",
        "votos_conservados=1",
        "presentes=1",
        "quorum_requerido=2",
    ):
        assert fragmento in fila[5]


async def test_presencia_completa_normalmente_si_conserva_quorum(
    tmp_path: Path,
) -> None:
    """La nueva prioridad no rompe el autocierre ordinario con quórum."""

    entorno, votacion = await crear_entorno(
        tmp_path,
        quorum=2,
        presentes=("D-01", "D-02", "D-03"),
    )
    assert votacion is not None
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "1"))
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "1"))

    await entorno.entrada.procesar_pulsacion(Pulsacion("D-03", "9"))

    assert votacion.resultado is ResultadoVotacion.APROBADA
    assert entorno.estado.votacion_activa is None
    codigos = [fila[4] for fila in filas_l1(entorno.estado)]
    assert codigos[-2:] == ["VOTACION_CERRADA_COMPLETITUD", "VOTACION_RESULTADO_FINAL"]


async def test_perdida_sin_votacion_mantiene_sesion_y_recuperacion_habilita_apertura(
    tmp_path: Path,
) -> None:
    """No existe una 'sesión inconclusa': solo cambia la precondición de apertura."""

    entorno, votacion = await crear_entorno(tmp_path, abrir_votacion=False)
    assert votacion is None
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "9"))
    assert entorno.estado.estado_global is EstadoGlobal.SESION_ABIERTA
    assert entorno.estado.votacion_activa is None
    with pytest.raises(ErrorQuorumInsuficiente):
        await entorno.votaciones.abrir_votacion(datos_votacion())

    await entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "9"))
    nueva = await entorno.votaciones.abrir_votacion(datos_votacion())
    assert nueva is entorno.estado.votacion_activa


async def test_perdida_posterior_a_empate_no_lo_modifica(
    tmp_path: Path,
) -> None:
    """EMPATADA solo se vuelve INCONCLUSA por cierre explícito de sesión."""

    entorno, votacion = await crear_entorno(tmp_path)
    assert votacion is not None
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "1"))
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "3"))
    fecha_empate = votacion.fecha_hora_cierre
    votos = dict(votacion.votos_ordinarios)

    await entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "9"))

    assert votacion.resultado is ResultadoVotacion.EMPATADA
    assert votacion.fecha_hora_cierre == fecha_empate
    assert dict(votacion.votos_ordinarios) == votos
    assert entorno.estado.votacion_activa is votacion


async def test_fallo_inconclusa_por_quorum_no_revierte_presencia(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La memoria queda exactamente en el último hecho durable de presencia."""

    entorno, votacion = await crear_entorno(tmp_path)
    assert votacion is not None
    contexto = entorno.estado.contexto_operativo_activo()
    assert contexto is not None
    instalar_fallo_en_evento(
        monkeypatch,
        contexto.escritor_auditoria,
        "VOTACION_FINALIZADA_INCONCLUSA",
    )

    with pytest.raises(ErrorAuditoria):
        await entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "9"))

    assert contexto.presencias["30000002"] is False
    assert votacion.estado is EstadoVotacion.EN_CURSO
    assert votacion.resultado is None
    assert votacion.fecha_hora_cierre is None
    assert entorno.estado.votacion_activa is votacion
    assert contexto.escritor_auditoria.fallado is True


@pytest.mark.parametrize("con_voto", [False, True], ids=["cero-votos", "voto-parcial"])
async def test_cierre_sesion_resuelve_en_curso_y_ordena_eventos(
    tmp_path: Path,
    con_voto: bool,
) -> None:
    """INCONCLUSA se persiste/aplica antes de SESION_CERRADA y la limpieza."""

    entorno, votacion = await crear_entorno(tmp_path)
    assert votacion is not None
    if con_voto:
        await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "1"))
    sesion = entorno.estado.sesion_activa
    assert sesion is not None
    ruta = sesion.contexto_operativo.escritor_auditoria.rutas[NivelAuditoria.L1]

    await entorno.sesion.cerrar_sesion()

    assert votacion is sesion.votaciones[0]
    assert votacion.resultado is ResultadoVotacion.INCONCLUSA
    assert votacion.estado is EstadoVotacion.CERRADA
    assert len(votacion.votos_ordinarios) == int(con_voto)
    assert votacion.motivo_finalizacion_manual is None
    assert entorno.estado.estado_global is EstadoGlobal.SIN_PREPARAR
    assert entorno.estado.sesion_activa is None
    assert entorno.estado.votacion_activa is None
    codigos = [fila[4] for fila in leer_filas(ruta)]
    assert codigos[-2:] == ["VOTACION_FINALIZADA_INCONCLUSA", "SESION_CERRADA"]
    fila_inconclusa = leer_filas(ruta)[-2]
    assert "causa=CIERRE_SESION" in fila_inconclusa[5]
    assert "resultado_previo=None" in fila_inconclusa[5]


async def test_cierre_sesion_convierte_empate_sin_tocar_fecha_votos_o_evento(
    tmp_path: Path,
) -> None:
    """La auditoría conserva el empate previo y no aparece voto presidencial."""

    entorno, votacion = await crear_entorno(tmp_path)
    assert votacion is not None
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "1"))
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "3"))
    fecha_empate = votacion.fecha_hora_cierre
    votos = dict(votacion.votos_ordinarios)
    sesion = entorno.estado.sesion_activa
    assert sesion is not None
    ruta = sesion.contexto_operativo.escritor_auditoria.rutas[NivelAuditoria.L1]

    await entorno.sesion.cerrar_sesion()

    filas = leer_filas(ruta)
    codigos = [fila[4] for fila in filas]
    assert "VOTACION_RESULTADO_EMPATE" in codigos
    assert codigos[-2:] == ["VOTACION_FINALIZADA_INCONCLUSA", "SESION_CERRADA"]
    assert all("PRESIDENCIAL" not in codigo for codigo in codigos)
    assert "resultado_previo=EMPATADA" in filas[-2][5]
    assert votacion.resultado is ResultadoVotacion.INCONCLUSA
    assert votacion.fecha_hora_cierre == fecha_empate
    assert dict(votacion.votos_ordinarios) == votos


async def test_fallo_finalizacion_durante_cierre_deja_todo_previo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caso A: sin evento de votación no se intenta institucionalizar sesión."""

    entorno, votacion = await crear_entorno(tmp_path)
    assert votacion is not None
    sesion = entorno.estado.sesion_activa
    assert sesion is not None
    escritor = sesion.contexto_operativo.escritor_auditoria
    instalar_fallo_en_evento(monkeypatch, escritor, "VOTACION_FINALIZADA_INCONCLUSA")

    with pytest.raises(ErrorAuditoria):
        await entorno.sesion.cerrar_sesion()

    assert votacion.estado is EstadoVotacion.EN_CURSO
    assert votacion.resultado is None
    assert votacion.fecha_hora_cierre is None
    assert entorno.estado.votacion_activa is votacion
    assert entorno.estado.sesion_activa is sesion
    assert entorno.estado.estado_global is EstadoGlobal.SESION_ABIERTA


async def test_fallo_sesion_cerrada_conserva_inconclusa_sin_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caso B: la votación durable permanece final aunque la sesión siga abierta."""

    entorno, votacion = await crear_entorno(tmp_path)
    assert votacion is not None
    sesion = entorno.estado.sesion_activa
    assert sesion is not None
    escritor = sesion.contexto_operativo.escritor_auditoria
    instalar_fallo_en_evento(monkeypatch, escritor, "SESION_CERRADA")

    with pytest.raises(ErrorAuditoria):
        await entorno.sesion.cerrar_sesion()

    assert votacion.resultado is ResultadoVotacion.INCONCLUSA
    assert votacion.estado is EstadoVotacion.CERRADA
    assert entorno.estado.votacion_activa is None
    assert entorno.estado.sesion_activa is sesion
    assert entorno.estado.estado_global is EstadoGlobal.SESION_ABIERTA
    assert escritor.fallado is True


async def test_fallo_fisico_al_cerrar_writer_conserva_sesion_e_inconclusa(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caso C: los dos hechos quedan durables, pero no se limpia el contexto."""

    entorno, votacion = await crear_entorno(tmp_path)
    assert votacion is not None
    sesion = entorno.estado.sesion_activa
    assert sesion is not None
    escritor = sesion.contexto_operativo.escritor_auditoria
    cerrar_original = escritor.cerrar

    def cerrar_con_fallo() -> None:
        """Simula la frontera física luego de cerrar irreversiblemente archivos."""

        cerrar_original()
        monkeypatch.setattr(escritor, "_fallado", True)
        raise ErrorAuditoria("fallo físico simulado al cerrar")

    monkeypatch.setattr(escritor, "cerrar", cerrar_con_fallo)

    with pytest.raises(ErrorAuditoria, match="cerrar"):
        await entorno.sesion.cerrar_sesion()

    assert votacion.resultado is ResultadoVotacion.INCONCLUSA
    assert entorno.estado.votacion_activa is None
    assert entorno.estado.sesion_activa is sesion
    assert entorno.estado.estado_global is EstadoGlobal.SESION_ABIERTA
    assert escritor.cerrado is True
    assert escritor.fallado is True


async def test_cerrada_sin_resultado_tecnica_no_se_repara_al_cerrar(
    tmp_path: Path,
) -> None:
    """El estado técnico conserva VOTACION_PENDIENTE y no gana recovery."""

    entorno, votacion = await crear_entorno(tmp_path)
    assert votacion is not None
    votacion.cerrar_recepcion(HORA_FINALIZACION)

    with pytest.raises(ErrorVotacionPendiente):
        await entorno.sesion.cerrar_sesion()

    assert votacion.estado is EstadoVotacion.CERRADA
    assert votacion.resultado is None
    assert entorno.estado.votacion_activa is votacion
    assert entorno.estado.estado_global is EstadoGlobal.SESION_ABIERTA


@pytest.mark.parametrize("manual_primero", [True, False], ids=["manual", "ultimo-voto"])
async def test_carrera_manual_vs_ultimo_voto(
    tmp_path: Path,
    manual_primero: bool,
) -> None:
    """Ambos órdenes reales observan el estado que dejó la primera adquisición."""

    entorno, votacion = await crear_entorno(tmp_path)
    assert votacion is not None
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "1"))
    manual = entorno.votaciones.finalizar_votacion_manualmente(votacion.id, "fin anticipado")
    ultimo_voto = entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "1"))

    if manual_primero:
        primero, segundo = await encolar_en_orden(entorno.ejecutor, manual, ultimo_voto)
        assert primero is None
        assert isinstance(segundo, RespuestaEntrada)
        assert segundo.aceptada is False
        assert segundo.motivo == "VOTACION_NO_EN_CURSO"
        assert votacion.resultado is ResultadoVotacion.INCONCLUSA
        assert set(votacion.votos_ordinarios) == {"30000001"}
    else:
        primero, segundo = await encolar_en_orden(entorno.ejecutor, ultimo_voto, manual)
        assert isinstance(primero, RespuestaEntrada)
        assert primero.aceptada is True
        assert isinstance(segundo, ErrorVotacionNoEnCurso)
        assert votacion.resultado is ResultadoVotacion.APROBADA
        assert set(votacion.votos_ordinarios) == {"30000001", "30000002"}
    assert votacion.estado is EstadoVotacion.CERRADA
    assert entorno.estado.votacion_activa is None


@pytest.mark.parametrize("manual_primero", [True, False], ids=["manual", "presencia"])
async def test_carrera_manual_vs_presencia_que_pierde_quorum(
    tmp_path: Path,
    manual_primero: bool,
) -> None:
    """La segunda operación nunca vuelve a finalizar la misma entidad."""

    entorno, votacion = await crear_entorno(tmp_path)
    assert votacion is not None
    manual = entorno.votaciones.finalizar_votacion_manualmente(votacion.id, "fin")
    presencia = entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "9"))

    if manual_primero:
        primero, segundo = await encolar_en_orden(entorno.ejecutor, manual, presencia)
        assert primero is None
        assert isinstance(segundo, RespuestaEntrada)
        assert segundo.aceptada is True
    else:
        primero, segundo = await encolar_en_orden(entorno.ejecutor, presencia, manual)
        assert isinstance(primero, RespuestaEntrada)
        assert isinstance(segundo, ErrorVotacionNoEnCurso)
    assert votacion.resultado is ResultadoVotacion.INCONCLUSA
    assert entorno.estado.votacion_activa is None
    codigos = [fila[4] for fila in filas_l1(entorno.estado)]
    assert codigos.count("VOTACION_FINALIZADA_INCONCLUSA") == 1


@pytest.mark.parametrize("cierre_primero", [True, False], ids=["cierre", "ultimo-voto"])
async def test_carrera_cierre_sesion_vs_ultimo_voto(
    tmp_path: Path,
    cierre_primero: bool,
) -> None:
    """El cierre primero descarta contexto; el voto primero consolida mayoría."""

    entorno, votacion = await crear_entorno(tmp_path)
    assert votacion is not None
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "1"))
    cierre = entorno.sesion.cerrar_sesion()
    ultimo_voto = entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "1"))

    if cierre_primero:
        primero, segundo = await encolar_en_orden(entorno.ejecutor, cierre, ultimo_voto)
        afirmar_cierre_completado(primero)
        assert isinstance(segundo, RespuestaEntrada)
        assert segundo.motivo == "SIN_PREPARAR"
        assert votacion.resultado is ResultadoVotacion.INCONCLUSA
        assert set(votacion.votos_ordinarios) == {"30000001"}
    else:
        primero, segundo = await encolar_en_orden(entorno.ejecutor, ultimo_voto, cierre)
        assert isinstance(primero, RespuestaEntrada)
        afirmar_cierre_completado(segundo)
        assert votacion.resultado is ResultadoVotacion.APROBADA
        assert set(votacion.votos_ordinarios) == {"30000001", "30000002"}
    assert entorno.estado.estado_global is EstadoGlobal.SIN_PREPARAR
    assert entorno.estado.votacion_activa is None


@pytest.mark.parametrize("cierre_primero", [True, False], ids=["cierre", "presencia"])
async def test_carrera_cierre_sesion_vs_presencia(
    tmp_path: Path,
    cierre_primero: bool,
) -> None:
    """Cierre y presencia comparten el ejecutor y no intercalan sus hechos."""

    entorno, votacion = await crear_entorno(tmp_path)
    assert votacion is not None
    cierre = entorno.sesion.cerrar_sesion()
    presencia = entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "9"))

    if cierre_primero:
        primero, segundo = await encolar_en_orden(entorno.ejecutor, cierre, presencia)
        afirmar_cierre_completado(primero)
        assert isinstance(segundo, RespuestaEntrada)
        assert segundo.motivo == "SIN_PREPARAR"
    else:
        primero, segundo = await encolar_en_orden(entorno.ejecutor, presencia, cierre)
        assert isinstance(primero, RespuestaEntrada)
        assert primero.aceptada is True
        afirmar_cierre_completado(segundo)
    assert votacion.resultado is ResultadoVotacion.INCONCLUSA
    assert entorno.estado.estado_global is EstadoGlobal.SIN_PREPARAR


@pytest.mark.parametrize("cierre_primero", [True, False], ids=["cierre", "manual"])
async def test_carrera_cierre_sesion_vs_finalizacion_manual(
    tmp_path: Path,
    cierre_primero: bool,
) -> None:
    """Solo una operación finaliza; la otra observa contexto cerrado o sin activa."""

    entorno, votacion = await crear_entorno(tmp_path)
    assert votacion is not None
    cierre = entorno.sesion.cerrar_sesion()
    manual = entorno.votaciones.finalizar_votacion_manualmente(votacion.id, "fin")

    if cierre_primero:
        primero, segundo = await encolar_en_orden(entorno.ejecutor, cierre, manual)
        afirmar_cierre_completado(primero)
        assert isinstance(segundo, ErrorEstadoIncompatible)
    else:
        primero, segundo = await encolar_en_orden(entorno.ejecutor, manual, cierre)
        assert primero is None
        afirmar_cierre_completado(segundo)
    assert votacion.resultado is ResultadoVotacion.INCONCLUSA
    assert entorno.estado.estado_global is EstadoGlobal.SIN_PREPARAR
    assert entorno.estado.votacion_activa is None


async def test_comando_obsoleto_encolado_para_a_no_finaliza_nueva_b(
    tmp_path: Path,
) -> None:
    """La validación del id ocurre al adquirir el lock, no al recibir intención."""

    entorno, primera = await crear_entorno(tmp_path)
    assert primera is not None
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "1"))
    entorno.ejecutor.activar_control()

    manual_obsoleto = asyncio.ensure_future(
        entorno.votaciones.finalizar_votacion_manualmente(primera.id, "comando tardío")
    )
    permiso_manual = await entorno.ejecutor.siguiente_permiso()
    ultimo_voto = asyncio.ensure_future(entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "1")))
    permiso_voto = await entorno.ejecutor.siguiente_permiso()

    # Aunque el comando manual llegó primero, el test permite que el último
    # voto adquiera el lock real, cierre A y libere la referencia.
    permiso_voto.set()
    respuesta_voto = await ultimo_voto
    assert respuesta_voto.aceptada is True
    assert primera.resultado is ResultadoVotacion.APROBADA

    apertura_b = asyncio.ensure_future(
        entorno.votaciones.abrir_votacion(datos_votacion(numero=38, tema="Tema B"))
    )
    permiso_apertura = await entorno.ejecutor.siguiente_permiso()
    permiso_apertura.set()
    segunda = await apertura_b
    assert entorno.estado.votacion_activa is segunda

    permiso_manual.set()
    resultado_manual = (await asyncio.gather(manual_obsoleto, return_exceptions=True))[0]

    assert isinstance(resultado_manual, ErrorVotacionNoCoincide)
    assert primera.resultado is ResultadoVotacion.APROBADA
    assert segunda.estado is EstadoVotacion.EN_CURSO
    assert segunda.resultado is None
    assert segunda.fecha_hora_cierre is None
    assert entorno.estado.votacion_activa is segunda
