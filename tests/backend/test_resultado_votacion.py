"""Pruebas del cálculo y aplicación automática de resultados de WP-011.

Los escenarios integrados usan los servicios reales y un único
``EjecutorMutaciones``. De ese modo no solo prueban fórmulas: también demuestran
el orden cierre -> auditoría de resultado -> mutación y qué referencia activa
observa una operación que estaba esperando el serializador compartido.
"""

from __future__ import annotations

import asyncio
import csv
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any

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
from sis_leg_backend.dominio.errores import ErrorVotacionPendiente
from sis_leg_backend.dominio.estado import EstadoOperativo
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
from sis_leg_backend.servicios.entrada import ServicioEntradaTecla
from sis_leg_backend.servicios.preparacion import ServicioPreparacion
from sis_leg_backend.servicios.serializacion import EjecutorMutaciones
from sis_leg_backend.servicios.sesion import ServicioSesion
from sis_leg_backend.servicios.votacion import ServicioVotacion

pytestmark = pytest.mark.anyio

HORA_INICIO = datetime(2026, 8, 22, 12, 0, 0)
HORA_SESION = datetime(2026, 8, 22, 12, 10, 0)
HORA_APERTURA = datetime(2026, 8, 22, 12, 20, 0)
HORA_CIERRE = datetime(2026, 8, 22, 12, 21, 0)

TECLA_POR_VOTO = {
    ValorVotoOrdinario.POSITIVO: "1",
    ValorVotoOrdinario.ABSTENCION: "2",
    ValorVotoOrdinario.NEGATIVO: "3",
}


@dataclass(frozen=True, slots=True)
class EntornoResultado:
    """Agrupa estado y servicios que comparten el serializador bajo prueba."""

    estado: EstadoOperativo
    ejecutor: EjecutorMutaciones
    entrada: ServicioEntradaTecla
    sesion: ServicioSesion
    votaciones: ServicioVotacion


def datos_votacion(
    *,
    numero: int = 37,
    tipo_mayoria: TipoMayoria = TipoMayoria.SIMPLE,
    factor: float = 0.0,
    base: BaseMayoria = BaseMayoria.VOTOS_COMPUTABLES,
) -> DatosAperturaVotacion:
    """Construye datos normalizados equivalentes a los entregados por la API."""

    return DatosAperturaVotacion(
        numero_votacion=numero,
        tipo="Mocion",
        tema=f"Tratamiento de prueba {numero}",
        tipo_mayoria=tipo_mayoria,
        factor=factor,
        base=base,
    )


async def crear_entorno(
    tmp_path: Path,
    *,
    quorum: int,
) -> EntornoResultado:
    """Prepara el recinto real con padrón de doce concejales y auditoría durable."""

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
        fabrica_escritor=partial(EscritorAuditoriaCsv, reloj=lambda: HORA_INICIO),
    )
    await preparacion.preparar_sala()
    return EntornoResultado(
        estado=estado,
        ejecutor=ejecutor,
        entrada=ServicioEntradaTecla(
            estado,
            ejecutor,
            reloj_monotono=lambda: 10.0,
            reloj=lambda: HORA_CIERRE,
        ),
        sesion=ServicioSesion(estado, ejecutor, reloj=lambda: HORA_SESION),
        votaciones=ServicioVotacion(
            estado,
            ejecutor,
            reloj=lambda: HORA_APERTURA,
            generador_id=lambda: "votacion-wp011",
        ),
    )


async def abrir_sesion(
    entorno: EntornoResultado,
    *,
    cantidad_presentes: int,
    presidencia: str = "Presidencia",
) -> None:
    """Completa datos, acredita las primeras bancas y abre la sesión."""

    await entorno.sesion.actualizar_preparacion(
        ActualizacionDatosInstitucionales(
            incluye_numero_sesion=True,
            numero_sesion=59,
            incluye_presidencia=True,
            presidencia=presidencia,
            incluye_secretaria_legislativa=True,
            secretaria_legislativa="Secretaría",
        )
    )
    for numero in range(1, cantidad_presentes + 1):
        await entorno.entrada.procesar_pulsacion(Pulsacion(f"D-{numero:02d}", "9"))
    await entorno.sesion.abrir_sesion()


async def preparar_votacion(
    tmp_path: Path,
    valores: list[ValorVotoOrdinario],
    *,
    tipo_mayoria: TipoMayoria = TipoMayoria.SIMPLE,
    factor: float = 0.0,
    base: BaseMayoria = BaseMayoria.VOTOS_COMPUTABLES,
    presidencia: str = "Presidencia",
) -> tuple[EntornoResultado, Votacion]:
    """Abre una votación con tantos presentes como votos se emitirán."""

    entorno = await crear_entorno(tmp_path, quorum=len(valores))
    await abrir_sesion(
        entorno,
        cantidad_presentes=len(valores),
        presidencia=presidencia,
    )
    votacion = await entorno.votaciones.abrir_votacion(
        datos_votacion(tipo_mayoria=tipo_mayoria, factor=factor, base=base)
    )
    return entorno, votacion


async def emitir_votos(
    entorno: EntornoResultado,
    valores: list[ValorVotoOrdinario],
    *,
    primer_dispositivo: int = 1,
) -> None:
    """Emite en orden los votos indicados usando dispositivos consecutivos."""

    for desplazamiento, valor in enumerate(valores):
        dispositivo = primer_dispositivo + desplazamiento
        respuesta = await entorno.entrada.procesar_pulsacion(
            Pulsacion(f"D-{dispositivo:02d}", TECLA_POR_VOTO[valor])
        )
        assert respuesta.aceptada is True


def valores(
    positivos: int,
    negativos: int,
    abstenciones: int,
) -> list[ValorVotoOrdinario]:
    """Expande conteos legibles a la secuencia de votos usada por los tests."""

    return (
        [ValorVotoOrdinario.POSITIVO] * positivos
        + [ValorVotoOrdinario.NEGATIVO] * negativos
        + [ValorVotoOrdinario.ABSTENCION] * abstenciones
    )


def filas_l1(entorno: EntornoResultado) -> list[list[str]]:
    """Lee los eventos persistidos en el nivel acumulativo de máximo detalle."""

    contexto = entorno.estado.contexto_operativo_activo()
    assert contexto is not None
    ruta = contexto.escritor_auditoria.rutas[NivelAuditoria.L1]
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.reader(archivo, delimiter=";"))


@pytest.mark.parametrize(
    ("conteos", "esperado"),
    [
        ((4, 3, 3), ResultadoVotacion.APROBADA),
        ((3, 4, 3), ResultadoVotacion.RECHAZADA),
        ((3, 3, 4), ResultadoVotacion.EMPATADA),
        ((0, 0, 7), ResultadoVotacion.EMPATADA),
    ],
    ids=["positiva", "negativa", "empate-con-abstenciones", "solo-abstenciones"],
)
async def test_mayoria_simple_aplica_resultado_y_conserva_entidad(
    tmp_path: Path,
    conteos: tuple[int, int, int],
    esperado: ResultadoVotacion,
) -> None:
    """SIMPLE compara positivos/negativos y conserva votos y cierre."""

    votos = valores(*conteos)
    entorno, votacion = await preparar_votacion(tmp_path, votos)
    sesion = entorno.estado.sesion_activa
    assert sesion is not None

    await emitir_votos(entorno, votos)

    assert votacion is sesion.votaciones[0]
    assert votacion.estado is EstadoVotacion.CERRADA
    assert votacion.resultado is esperado
    assert votacion.fecha_hora_cierre == HORA_CIERRE
    assert len(votacion.votos_ordinarios) == len(votos)
    if esperado is ResultadoVotacion.EMPATADA:
        assert entorno.estado.votacion_activa is votacion
    else:
        assert entorno.estado.votacion_activa is None


@pytest.mark.parametrize(
    ("conteos", "factor", "esperado", "denominador"),
    [
        ((4, 2, 2), 0.6, ResultadoVotacion.APROBADA, 6),
        ((3, 2, 2), 0.6, ResultadoVotacion.APROBADA, 5),
        ((2, 3, 2), 0.6, ResultadoVotacion.RECHAZADA, 5),
        ((0, 0, 7), 0.6, ResultadoVotacion.RECHAZADA, 0),
    ],
    ids=["encima", "igual", "debajo", "solo-abstenciones"],
)
async def test_especial_votos_computables_excluye_abstenciones(
    tmp_path: Path,
    conteos: tuple[int, int, int],
    factor: float,
    esperado: ResultadoVotacion,
    denominador: int,
) -> None:
    """La base computable usa positivos+negativos y resuelve su caso cero."""

    votos = valores(*conteos)
    entorno, votacion = await preparar_votacion(
        tmp_path,
        votos,
        tipo_mayoria=TipoMayoria.ESPECIAL,
        factor=factor,
        base=BaseMayoria.VOTOS_COMPUTABLES,
    )

    await emitir_votos(entorno, votos)

    assert votacion.resultado is esperado
    assert esperado is not ResultadoVotacion.EMPATADA
    fila_resultado = filas_l1(entorno)[-1]
    assert fila_resultado[4] == "VOTACION_RESULTADO_FINAL"
    for fragmento in (
        "tipo_mayoria=ESPECIAL",
        "base=VOTOS_COMPUTABLES",
        f"positivos={conteos[0]}",
        f"negativos={conteos[1]}",
        f"abstenciones={conteos[2]}",
        f"denominador={denominador}",
        f"factor={factor}",
        f"resultado={esperado.value}",
    ):
        assert fragmento in fila_resultado[5]
    if denominador == 0:
        assert "cociente=no_calculado" in fila_resultado[5]
        assert "caso_sin_division=true" in fila_resultado[5]
    else:
        assert "cociente=" in fila_resultado[5]
        assert "caso_sin_division=false" in fila_resultado[5]


@pytest.mark.parametrize(
    ("conteos", "factor", "esperado"),
    [
        ((6, 3, 1), 0.6, ResultadoVotacion.APROBADA),
        ((7, 2, 1), 0.7, ResultadoVotacion.APROBADA),
        ((5, 4, 1), 0.6, ResultadoVotacion.RECHAZADA),
    ],
    ids=["canonico", "igual", "debajo"],
)
async def test_especial_presentes_incluye_abstenciones(
    tmp_path: Path,
    conteos: tuple[int, int, int],
    factor: float,
    esperado: ResultadoVotacion,
) -> None:
    """PRESENTES usa todos los votos emitidos como denominador técnico."""

    votos = valores(*conteos)
    entorno, votacion = await preparar_votacion(
        tmp_path,
        votos,
        tipo_mayoria=TipoMayoria.ESPECIAL,
        factor=factor,
        base=BaseMayoria.PRESENTES,
    )

    await emitir_votos(entorno, votos)

    assert votacion.resultado is esperado
    assert "denominador=10" in filas_l1(entorno)[-1][5]


async def test_presentes_conserva_quien_voto_y_se_ausento(
    tmp_path: Path,
) -> None:
    """Retirarse después del voto no quita a la persona del denominador."""

    votos = valores(6, 3, 1)
    entorno = await crear_entorno(tmp_path, quorum=9)
    await abrir_sesion(entorno, cantidad_presentes=10)
    votacion = await entorno.votaciones.abrir_votacion(
        datos_votacion(
            tipo_mayoria=TipoMayoria.ESPECIAL,
            factor=0.6,
            base=BaseMayoria.PRESENTES,
        )
    )
    await emitir_votos(entorno, votos[:1])
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "9"))
    await emitir_votos(entorno, votos[1:], primer_dispositivo=2)

    assert votacion.resultado is ResultadoVotacion.APROBADA
    assert "denominador=10" in filas_l1(entorno)[-1][5]

    # Un cambio dinámico posterior tampoco recalcula el resultado ya aplicado.
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-11", "9"))
    assert votacion.resultado is ResultadoVotacion.APROBADA
    assert len(votacion.votos_ordinarios) == 10


async def test_presentes_incluye_quien_ingreso_y_voto_durante_recepcion(
    tmp_path: Path,
) -> None:
    """Una banca incorporada durante EN_CURSO integra los votos emitidos."""

    votos = valores(6, 3, 1)
    entorno = await crear_entorno(tmp_path, quorum=9)
    await abrir_sesion(entorno, cantidad_presentes=9)
    votacion = await entorno.votaciones.abrir_votacion(
        datos_votacion(
            tipo_mayoria=TipoMayoria.ESPECIAL,
            factor=0.6,
            base=BaseMayoria.PRESENTES,
        )
    )
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-10", "9"))

    await emitir_votos(entorno, votos)

    assert votacion.resultado is ResultadoVotacion.APROBADA
    assert "denominador=10" in filas_l1(entorno)[-1][5]


@pytest.mark.parametrize(
    ("factor", "positivos", "negativos", "esperado"),
    [
        (2 / 3, 8, 0, ResultadoVotacion.APROBADA),
        (0.6666666667, 8, 0, ResultadoVotacion.RECHAZADA),
        (2 / 3, 7, 1, ResultadoVotacion.RECHAZADA),
    ],
    ids=["dos-tercios-exacto", "decimal-mayor", "debajo"],
)
async def test_especial_cuerpo_usa_padron_congelado_y_factor_exacto(
    tmp_path: Path,
    factor: float,
    positivos: int,
    negativos: int,
    esperado: ResultadoVotacion,
) -> None:
    """CUERPO conserva doce bancas aunque haya ocho presentes y Presidencia."""

    votos = valores(positivos, negativos, 0)
    entorno, votacion = await preparar_votacion(
        tmp_path,
        votos,
        tipo_mayoria=TipoMayoria.ESPECIAL,
        factor=factor,
        base=BaseMayoria.CUERPO,
        # El nombre coincide con la primera concejal para demostrar que ejercer
        # Presidencia no agrega una persona al padrón ni al denominador.
        presidencia="Ana Garcia",
    )

    await emitir_votos(entorno, votos)

    assert votacion.resultado is esperado
    fila_resultado = filas_l1(entorno)[-1]
    assert "base=CUERPO" in fila_resultado[5]
    assert "denominador=12" in fila_resultado[5]
    assert f"factor={factor}" in fila_resultado[5]


def votacion_de_dominio(
    *,
    tipo_mayoria: TipoMayoria = TipoMayoria.SIMPLE,
    factor: float = 0.0,
    base: BaseMayoria = BaseMayoria.VOTOS_COMPUTABLES,
) -> Votacion:
    """Crea una entidad aislada para probar sus defensas internas."""

    return Votacion(
        id="dominio",
        numero_votacion=1,
        tipo="Mocion",
        tema="Prueba de invariantes",
        tipo_mayoria=tipo_mayoria,
        factor=factor,
        base=base,
        fecha_hora_apertura=HORA_APERTURA,
    )


def test_entidad_restringe_aplicacion_y_recalculo_ordinarios() -> None:
    """La entidad exige CERRADA+None y nunca permite INCONCLUSA o recálculo."""

    votacion = votacion_de_dominio()
    votacion.registrar_voto(VotoOrdinario(dni="1", valor=ValorVotoOrdinario.POSITIVO))
    with pytest.raises(ValueError, match="cerrada"):
        votacion.calcular_resultado_ordinario(cantidad_total_cuerpo=12)
    with pytest.raises(ValueError, match="cerrada"):
        votacion.aplicar_resultado_ordinario(ResultadoVotacion.APROBADA)

    votacion.cerrar_recepcion(HORA_CIERRE)
    votos_antes = dict(votacion.votos_ordinarios)
    calculo = votacion.calcular_resultado_ordinario(cantidad_total_cuerpo=12)
    assert votacion.resultado is None
    votacion.aplicar_resultado_ordinario(calculo.resultado)

    assert votacion.resultado is ResultadoVotacion.APROBADA
    assert votacion.fecha_hora_cierre == HORA_CIERRE
    assert dict(votacion.votos_ordinarios) == votos_antes
    assert votacion.factor == 0
    assert votacion.base is BaseMayoria.VOTOS_COMPUTABLES
    with pytest.raises(ValueError, match="irreversible"):
        votacion.calcular_resultado_ordinario(cantidad_total_cuerpo=12)
    with pytest.raises(ValueError, match="irreversible"):
        votacion.aplicar_resultado_ordinario(ResultadoVotacion.RECHAZADA)

    inconclusa = votacion_de_dominio()
    inconclusa.cerrar_recepcion(HORA_CIERRE)
    with pytest.raises(ValueError, match="no admite"):
        inconclusa.aplicar_resultado_ordinario(ResultadoVotacion.INCONCLUSA)

    especial = votacion_de_dominio(
        tipo_mayoria=TipoMayoria.ESPECIAL,
        factor=0.6,
        base=BaseMayoria.PRESENTES,
    )
    especial.cerrar_recepcion(HORA_CIERRE)
    with pytest.raises(ValueError, match="especial"):
        especial.aplicar_resultado_ordinario(ResultadoVotacion.EMPATADA)


async def test_auditoria_cierre_precede_resultado_y_resultado_precede_mutacion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cada hecho L3 se persiste antes de su transición funcional propia."""

    votos = valores(2, 1, 1)
    entorno, votacion = await preparar_votacion(tmp_path, votos)
    contexto = entorno.estado.contexto_operativo_activo()
    assert contexto is not None
    escritor = contexto.escritor_auditoria
    registrar_original = escritor.registrar_evento
    resultados_al_persistir: list[ResultadoVotacion | None] = []

    def registrar_evento(
        nivel: NivelAuditoria,
        etiqueta: str,
        codigo_evento: str,
        mensaje: str,
        *,
        referencia: ReferenciaHechoOperativo | None = None,
    ) -> int:
        if codigo_evento == "VOTACION_RESULTADO_FINAL":
            resultados_al_persistir.append(votacion.resultado)
        return registrar_original(nivel, etiqueta, codigo_evento, mensaje, referencia=referencia)

    monkeypatch.setattr(escritor, "registrar_evento", registrar_evento)
    await emitir_votos(entorno, votos)

    codigos = [fila[4] for fila in filas_l1(entorno)]
    assert codigos.index("VOTACION_CERRADA_COMPLETITUD") < codigos.index("VOTACION_RESULTADO_FINAL")
    assert resultados_al_persistir == [None]
    mensaje = filas_l1(entorno)[-1][5]
    for fragmento in (
        "número=37",
        "id=votacion-wp011",
        "tipo_mayoria=SIMPLE",
        "positivos=2",
        "negativos=1",
        "abstenciones=1",
        "abstenciones_excluidas=true",
        "resultado=APROBADA",
    ):
        assert fragmento in mensaje


async def test_empate_tiene_evento_institucional_distinguible(
    tmp_path: Path,
) -> None:
    """EMPATADA no comparte el código estable de un resultado final."""

    votos = valores(1, 1, 1)
    entorno, votacion = await preparar_votacion(tmp_path, votos)
    await emitir_votos(entorno, votos)

    assert votacion.resultado is ResultadoVotacion.EMPATADA
    assert filas_l1(entorno)[-1][4] == "VOTACION_RESULTADO_EMPATE"
    assert "resultado=EMPATADA" in filas_l1(entorno)[-1][5]


async def test_fallo_auditoria_resultado_conserva_ultimo_hecho_persistido(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tras cerrar, un fallo del resultado deja CERRADA+None y fallo cerrado."""

    votos = valores(2, 0, 0)
    entorno, votacion = await preparar_votacion(tmp_path, votos)
    await emitir_votos(entorno, votos[:1])
    contexto = entorno.estado.contexto_operativo_activo()
    assert contexto is not None
    escritor = contexto.escritor_auditoria
    registrar_original = escritor.registrar_evento

    def registrar_evento(
        nivel: NivelAuditoria,
        etiqueta: str,
        codigo_evento: str,
        mensaje: str,
        *,
        referencia: ReferenciaHechoOperativo | None = None,
    ) -> int:
        if codigo_evento == "VOTACION_RESULTADO_FINAL":
            monkeypatch.setattr(escritor, "_fallado", True)
            raise ErrorAuditoria("fallo simulado en resultado")
        return registrar_original(nivel, etiqueta, codigo_evento, mensaje, referencia=referencia)

    monkeypatch.setattr(escritor, "registrar_evento", registrar_evento)
    with pytest.raises(ErrorAuditoria, match="resultado"):
        await emitir_votos(entorno, votos[1:], primer_dispositivo=2)

    assert votacion.estado is EstadoVotacion.CERRADA
    assert votacion.fecha_hora_cierre == HORA_CIERRE
    assert votacion.resultado is None
    assert entorno.estado.votacion_activa is votacion
    assert escritor.fallado is True
    assert filas_l1(entorno)[-1][4] == "VOTACION_CERRADA_COMPLETITUD"
    with pytest.raises(ErrorAuditoria):
        await entorno.entrada.procesar_pulsacion(Pulsacion("D-03", "8"))
    assert votacion.resultado is None


async def ejecutar_operaciones_encoladas[ResultadoPrimera, ResultadoSegunda](
    ejecutor: EjecutorMutaciones,
    primera: Callable[[], Coroutine[Any, Any, ResultadoPrimera]],
    segunda: Callable[[], Coroutine[Any, Any, ResultadoSegunda]],
) -> tuple[ResultadoPrimera | BaseException, ResultadoSegunda | BaseException]:
    """Encola dos operaciones detrás de un bloqueo real del mismo ejecutor.

    El bloqueo controlado garantiza que ambas tareas estén esperando el lock.
    Al liberarlo, ``primera`` adquiere antes y debe completar toda su sección
    crítica antes de que ``segunda`` pueda observar el estado.
    """

    bloqueo_adquirido = asyncio.Event()
    liberar_bloqueo = asyncio.Event()

    async def bloquear() -> None:
        bloqueo_adquirido.set()
        await liberar_bloqueo.wait()

    tarea_bloqueo = asyncio.create_task(ejecutor.ejecutar(bloquear))
    await bloqueo_adquirido.wait()
    tarea_primera = asyncio.create_task(primera())
    await asyncio.sleep(0)
    tarea_segunda = asyncio.create_task(segunda())
    await asyncio.sleep(0)
    liberar_bloqueo.set()
    await tarea_bloqueo
    return await asyncio.gather(tarea_primera, tarea_segunda, return_exceptions=True)


async def test_apertura_encolada_despues_de_resultado_final_observa_liberacion(
    tmp_path: Path,
) -> None:
    """La apertura que espera ve ``None`` solo después del resultado final."""

    votos = valores(1, 0, 1)
    entorno, votacion = await preparar_votacion(tmp_path, votos)
    await emitir_votos(entorno, votos[:1])

    voto_final, nueva = await ejecutar_operaciones_encoladas(
        entorno.ejecutor,
        lambda: entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "2")),
        lambda: entorno.votaciones.abrir_votacion(datos_votacion(numero=38)),
    )

    assert not isinstance(voto_final, Exception)
    assert isinstance(nueva, Votacion)
    assert votacion.resultado is ResultadoVotacion.APROBADA
    assert entorno.estado.votacion_activa is nueva
    codigos = [fila[4] for fila in filas_l1(entorno)]
    assert codigos.index("VOTACION_RESULTADO_FINAL") < len(codigos) - 1
    assert codigos[-1] == "VOTACION_ABIERTA"


async def test_apertura_encolada_despues_de_empate_observa_pendiente(
    tmp_path: Path,
) -> None:
    """La apertura que espera al empate encuentra la misma instancia activa."""

    votos = valores(1, 1, 0)
    entorno, votacion = await preparar_votacion(tmp_path, votos)
    await emitir_votos(entorno, votos[:1])

    voto_final, apertura = await ejecutar_operaciones_encoladas(
        entorno.ejecutor,
        lambda: entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "3")),
        lambda: entorno.votaciones.abrir_votacion(datos_votacion(numero=38)),
    )

    assert not isinstance(voto_final, Exception)
    assert isinstance(apertura, ErrorVotacionPendiente)
    assert votacion.resultado is ResultadoVotacion.EMPATADA
    assert entorno.estado.votacion_activa is votacion
    codigos = [fila[4] for fila in filas_l1(entorno)]
    assert codigos.index("VOTACION_RESULTADO_EMPATE") < codigos.index("COMANDO_VOTACION_RECHAZADO")


async def test_ultimo_voto_usa_una_sola_adquisicion_logica(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El cierre y el resultado no readquieren el ejecutor durante el voto."""

    votos = valores(2, 0, 0)
    entorno, votacion = await preparar_votacion(tmp_path, votos)
    await emitir_votos(entorno, votos[:1])
    ejecutar_original = entorno.ejecutor.ejecutar
    adquisiciones = 0

    async def ejecutar(mutacion: Callable[[], Awaitable[Any]]) -> Any:
        nonlocal adquisiciones
        adquisiciones += 1
        return await ejecutar_original(mutacion)

    monkeypatch.setattr(entorno.ejecutor, "ejecutar", ejecutar)
    await emitir_votos(entorno, votos[1:], primer_dispositivo=2)

    assert adquisiciones == 1
    assert votacion.resultado is ResultadoVotacion.APROBADA


async def test_presencia_que_completa_encadena_cierre_y_resultado(
    tmp_path: Path,
) -> None:
    """Retirar al único pendiente resuelve dentro de la pulsación de presencia."""

    entorno = await crear_entorno(tmp_path, quorum=2)
    await abrir_sesion(entorno, cantidad_presentes=3)
    votacion = await entorno.votaciones.abrir_votacion(datos_votacion())
    await emitir_votos(entorno, valores(1, 0, 1)[:2])

    respuesta = await entorno.entrada.procesar_pulsacion(Pulsacion("D-03", "9"))

    assert respuesta.aceptada is True
    assert votacion.estado is EstadoVotacion.CERRADA
    assert votacion.resultado is ResultadoVotacion.APROBADA
    assert entorno.estado.votacion_activa is None
    codigos = [fila[4] for fila in filas_l1(entorno)]
    assert codigos[-2:] == [
        "VOTACION_CERRADA_COMPLETITUD",
        "VOTACION_RESULTADO_FINAL",
    ]


def test_no_hay_api_publica_de_calculo_ni_resultado_editable() -> None:
    """La entidad ofrece dominio interno, no comandos de Moderación nuevos."""

    nombres_publicos = {nombre for nombre in dir(Votacion) if not nombre.startswith("_")}
    assert "recalcular_resultado" not in nombres_publicos
    assert "editar_resultado" not in nombres_publicos
    assert "eliminar_resultado" not in nombres_publicos
