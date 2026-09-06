"""Pruebas de dominio e integración del voto ordinario de WP-010.

Los escenarios utilizan los servicios reales de preparación, sesión, entrada y
votación con un único ``EjecutorMutaciones``. Además de observar la memoria,
leen el CSV L1 para demostrar el orden institucional y el fallo cerrado.
"""

from __future__ import annotations

import asyncio
import csv
from collections.abc import Callable
from dataclasses import FrozenInstanceError, dataclass
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import cast

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
from sis_leg_backend.dominio.entrada import Pulsacion, RespuestaEntrada, ResultadoVoto
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
from sis_leg_backend.servicios.entrada import ServicioEntradaTecla
from sis_leg_backend.servicios.preparacion import ServicioPreparacion
from sis_leg_backend.servicios.serializacion import EjecutorMutaciones
from sis_leg_backend.servicios.sesion import ServicioSesion
from sis_leg_backend.servicios.votacion import ServicioVotacion

pytestmark = pytest.mark.anyio

HORA_INICIO = datetime(2026, 8, 22, 9, 0, 0)
HORA_SESION = datetime(2026, 8, 22, 9, 10, 0)
HORA_APERTURA = datetime(2026, 8, 22, 9, 20, 0)
HORA_CIERRE = datetime(2026, 8, 22, 9, 21, 30)


@dataclass(frozen=True, slots=True)
class EntornoVoto:
    """Agrupa los servicios que comparten estado y serializador en cada prueba."""

    estado: EstadoOperativo
    entrada: ServicioEntradaTecla
    sesion: ServicioSesion
    votaciones: ServicioVotacion


def datos_votacion() -> DatosAperturaVotacion:
    """Devuelve una apertura mínima sin incorporar lógica de mayoría."""

    return DatosAperturaVotacion(
        numero_votacion=37,
        tipo="Mocion",
        tema="Tratamiento de prueba",
        tipo_mayoria=TipoMayoria.SIMPLE,
        factor=0.0,
        base=BaseMayoria.VOTOS_COMPUTABLES,
    )


async def crear_preparacion(
    directorio: Path,
    *,
    quorum: int,
    fabrica_escritor: Callable[[Path, datetime], EscritorAuditoriaCsv] | None = None,
) -> EntornoVoto:
    """Prepara el contexto real y construye todos los servicios compartidos."""

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
    await preparacion.preparar_sala()
    return EntornoVoto(
        estado=estado,
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
            generador_id=lambda: "votacion-wp010",
        ),
    )


async def abrir_sesion(
    entorno: EntornoVoto,
    dispositivos_presentes: tuple[str, ...],
) -> None:
    """Completa autoridades, acredita las bancas indicadas y abre la sesión."""

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


async def crear_votacion(
    tmp_path: Path,
    *,
    quorum: int = 2,
    dispositivos_presentes: tuple[str, ...] = ("D-01", "D-02"),
) -> tuple[EntornoVoto, Votacion]:
    """Crea una sesión y abre una votación real para el escenario solicitado."""

    entorno = await crear_preparacion(tmp_path, quorum=quorum)
    await abrir_sesion(entorno, dispositivos_presentes)
    votacion = await entorno.votaciones.abrir_votacion(datos_votacion())
    return entorno, votacion


def resultado_voto(respuesta: RespuestaEntrada) -> ResultadoVoto:
    """Afirma y devuelve la variante tipada VOTO para ayudar a Pyright."""

    assert isinstance(respuesta.resultado, ResultadoVoto)
    return respuesta.resultado


def filas_l1(entorno: EntornoVoto) -> list[list[str]]:
    """Lee todos los eventos acumulados del contexto auditable activo."""

    contexto = entorno.estado.contexto_operativo_activo()
    assert contexto is not None
    ruta = contexto.escritor_auditoria.rutas[NivelAuditoria.L1]
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.reader(archivo, delimiter=";"))


@pytest.mark.parametrize(
    ("tecla", "valor"),
    [
        ("1", ValorVotoOrdinario.POSITIVO),
        ("2", ValorVotoOrdinario.ABSTENCION),
        ("3", ValorVotoOrdinario.NEGATIVO),
    ],
    ids=["positivo", "abstencion", "negativo"],
)
async def test_tres_valores_se_guardan_inmutables_y_auditados(
    tmp_path: Path,
    tecla: str,
    valor: ValorVotoOrdinario,
) -> None:
    """Teclas 1/2/3 crean un único hecho L3 con la identidad del padrón."""

    entorno, votacion = await crear_votacion(tmp_path)

    respuesta = await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", tecla))

    assert respuesta.aceptada is True
    assert respuesta.motivo == "VOTO_REGISTRADO"
    assert respuesta.concejal is not None
    assert respuesta.concejal.dni == "30000001"
    assert resultado_voto(respuesta).valor is valor
    assert resultado_voto(respuesta).estado_recepcion is EstadoVotacion.EN_CURSO
    voto = votacion.votos_ordinarios["30000001"]
    assert voto == VotoOrdinario(dni="30000001", valor=valor)
    fila = filas_l1(entorno)[-1]
    assert fila[2:5] == ["L3", "VOTACION", "VOTO_ORDINARIO_REGISTRADO"]
    for fragmento in ("Ana", "Garcia", "banca Nro:1", valor.value, "número=37"):
        assert fragmento in fila[5]


@pytest.mark.parametrize("tecla", ["1", "2", "3"])
async def test_teclas_de_voto_respetan_estados_y_dispositivo(
    tmp_path: Path,
    tecla: str,
) -> None:
    """SIN_PREPARAR, PREPARANDO, sesión sin votación y dispositivo ajeno rechazan."""

    estado_vacio = EstadoOperativo()
    entrada_vacia = ServicioEntradaTecla(estado_vacio, EjecutorMutaciones())
    sin_preparar = await entrada_vacia.procesar_pulsacion(Pulsacion("D-01", tecla))
    assert sin_preparar.motivo == "SIN_PREPARAR"

    entorno = await crear_preparacion(tmp_path / "preparando", quorum=2)
    preparando = await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", tecla))
    assert preparando.motivo == "TECLA_NO_HABILITADA"

    await abrir_sesion(entorno, ("D-01", "D-02"))
    sin_votacion = await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", tecla))
    assert sin_votacion.motivo == "VOTACION_NO_EN_CURSO"

    no_asignado = await entorno.entrada.procesar_pulsacion(Pulsacion("AJENO", tecla))
    assert no_asignado.motivo == "DISPOSITIVO_NO_ASIGNADO"
    assert entorno.estado.votacion_activa is None


async def test_ausente_y_segundos_intentos_se_rechazan_sin_alterar_el_primero(
    tmp_path: Path,
) -> None:
    """Ausencia, repetición igual y cambio de valor nunca fabrican otro voto."""

    entorno, votacion = await crear_votacion(tmp_path)
    ausente = await entorno.entrada.procesar_pulsacion(Pulsacion("D-03", "1"))
    assert ausente.motivo == "CONCEJAL_AUSENTE"
    assert votacion.votos_ordinarios == {}

    primera = await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "1"))
    voto_original = votacion.votos_ordinarios["30000001"]
    repetida = await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "1"))
    diferente = await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "3"))

    assert primera.aceptada is True
    assert repetida.motivo == diferente.motivo == "VOTO_YA_EMITIDO"
    assert votacion.votos_ordinarios == {"30000001": voto_original}
    assert votacion.votos_ordinarios["30000001"] is voto_original
    assert voto_original.valor is ValorVotoOrdinario.POSITIVO
    rechazos = [fila for fila in filas_l1(entorno) if fila[4] == "PULSACION_RECHAZADA"]
    assert all(fila[2] == "L2" for fila in rechazos[-3:])
    assert not any(
        fila[4] == "VOTO_ORDINARIO_REGISTRADO" and "NEGATIVO" in fila[5]
        for fila in filas_l1(entorno)
    )


async def test_voto_sobrevive_ausencia_regreso_y_bloquea_nuevo_intento(
    tmp_path: Path,
) -> None:
    """La presencia dinámica no se usa como almacenamiento indirecto del voto."""

    entorno, votacion = await crear_votacion(
        tmp_path,
        quorum=2,
        dispositivos_presentes=("D-01", "D-02", "D-03"),
    )
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "2"))
    voto = votacion.votos_ordinarios["30000001"]

    ausencia = await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "9"))
    regreso = await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "9"))
    segundo = await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "3"))

    assert ausencia.aceptada is regreso.aceptada is True
    assert votacion.votos_ordinarios["30000001"] is voto
    assert voto.valor is ValorVotoOrdinario.ABSTENCION
    assert segundo.motivo == "VOTO_YA_EMITIDO"


async def test_ausente_que_se_presenta_puede_emitir_su_primer_voto(
    tmp_path: Path,
) -> None:
    """La completitud usa presencia actual, pero el padrón sigue siendo congelado."""

    entorno, votacion = await crear_votacion(tmp_path)

    await entorno.entrada.procesar_pulsacion(Pulsacion("D-03", "9"))
    respuesta = await entorno.entrada.procesar_pulsacion(Pulsacion("D-03", "3"))

    assert respuesta.aceptada is True
    assert votacion.votos_ordinarios["30000003"].valor is ValorVotoOrdinario.NEGATIVO
    assert votacion.estado is EstadoVotacion.EN_CURSO


async def test_autocierre_por_ultimo_voto_conserva_instancia_y_aplica_empate(
    tmp_path: Path,
) -> None:
    """El último presente cierra, fija fecha y aplica el empate en la instancia."""

    entorno, votacion = await crear_votacion(tmp_path)
    sesion = entorno.estado.sesion_activa
    assert sesion is not None

    primera = await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "1"))
    segunda = await entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "3"))

    assert resultado_voto(primera).estado_recepcion is EstadoVotacion.EN_CURSO
    assert resultado_voto(segunda).estado_recepcion is EstadoVotacion.CERRADA
    assert votacion.estado is EstadoVotacion.CERRADA
    assert votacion.fecha_hora_cierre == HORA_CIERRE
    assert votacion.resultado is ResultadoVotacion.EMPATADA
    assert entorno.estado.votacion_activa is votacion is sesion.votaciones[0]
    assert filas_l1(entorno)[-1][2:5] == [
        "L3",
        "VOTACION",
        "VOTACION_RESULTADO_EMPATE",
    ]
    codigos = [fila[4] for fila in filas_l1(entorno)]
    assert codigos.index("VOTACION_CERRADA_COMPLETITUD") < codigos.index(
        "VOTACION_RESULTADO_EMPATE"
    )


async def test_presencia_puede_autocerrar_solo_si_se_mantiene_quorum(
    tmp_path: Path,
) -> None:
    """Retirar al único pendiente cierra normal o inconclusa según quórum."""

    entorno, votacion = await crear_votacion(
        tmp_path / "mantiene-quorum",
        quorum=2,
        dispositivos_presentes=("D-01", "D-02", "D-03"),
    )
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "1"))
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "2"))
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-03", "9"))
    assert votacion.estado is EstadoVotacion.CERRADA
    assert votacion.resultado is ResultadoVotacion.APROBADA
    assert entorno.estado.votacion_activa is None

    entorno_sin_quorum, votacion_sin_quorum = await crear_votacion(
        tmp_path / "pierde-quorum",
        quorum=2,
    )
    await entorno_sin_quorum.entrada.procesar_pulsacion(Pulsacion("D-01", "1"))
    await entorno_sin_quorum.entrada.procesar_pulsacion(Pulsacion("D-02", "9"))
    contexto = entorno_sin_quorum.estado.contexto_operativo_activo()
    assert contexto is not None
    assert contexto.quorum_alcanzado() is False
    assert votacion_sin_quorum.estado is EstadoVotacion.CERRADA
    assert votacion_sin_quorum.resultado is ResultadoVotacion.INCONCLUSA
    assert votacion_sin_quorum.fecha_hora_cierre == HORA_CIERRE
    assert entorno_sin_quorum.estado.votacion_activa is None


async def test_cerrada_rechaza_votos_no_reabre_y_resultado_final_libera(
    tmp_path: Path,
) -> None:
    """Presencia posterior no recalcula y un resultado final habilita otra apertura."""

    entorno, votacion = await crear_votacion(tmp_path)
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "1"))
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "2"))
    fecha = votacion.fecha_hora_cierre
    votos = dict(votacion.votos_ordinarios)

    voto_tardio = await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "3"))
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-03", "9"))

    assert voto_tardio.motivo == "VOTACION_NO_EN_CURSO"
    assert votacion.estado is EstadoVotacion.CERRADA
    assert votacion.fecha_hora_cierre == fecha == HORA_CIERRE
    assert dict(votacion.votos_ordinarios) == votos
    assert votacion.resultado is ResultadoVotacion.APROBADA
    assert entorno.estado.votacion_activa is None
    nueva = await entorno.votaciones.abrir_votacion(datos_votacion())
    assert nueva is entorno.estado.votacion_activa
    await entorno.sesion.cerrar_sesion()
    assert nueva.resultado is ResultadoVotacion.INCONCLUSA
    assert entorno.estado.estado_global is EstadoGlobal.SIN_PREPARAR


async def test_regresion_test_presencia_y_tecla_siete(
    tmp_path: Path,
) -> None:
    """WP-010 conserva 8/9 y no habilita anticipadamente el uso de palabra."""

    entorno, votacion = await crear_votacion(
        tmp_path,
        quorum=2,
        dispositivos_presentes=("D-01", "D-02", "D-03"),
    )
    prueba = await entorno.entrada.procesar_pulsacion(Pulsacion("D-04", "8"))
    presencia = await entorno.entrada.procesar_pulsacion(Pulsacion("D-03", "9"))
    palabra = await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "7"))

    assert prueba.aceptada is True
    assert prueba.motivo == "TEST_ACTIVADO"
    assert presencia.aceptada is True
    assert palabra.aceptada is True
    assert palabra.motivo == "PEDIDO_PALABRA_REGISTRADO"
    assert votacion.estado is EstadoVotacion.EN_CURSO


def instalar_fallo_en_evento(
    monkeypatch: pytest.MonkeyPatch,
    escritor: EscritorAuditoriaCsv,
    codigo_objetivo: str,
) -> None:
    """Hace fallar un único código y marca el writer como no disponible."""

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


async def test_fallo_de_auditoria_del_voto_impide_guardarlo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """VALIDAR -> AUDITAR -> MUTAR deja el mapa vacío si falla el evento L3."""

    entorno, votacion = await crear_votacion(tmp_path)
    contexto = entorno.estado.contexto_operativo_activo()
    assert contexto is not None
    instalar_fallo_en_evento(
        monkeypatch,
        contexto.escritor_auditoria,
        "VOTO_ORDINARIO_REGISTRADO",
    )

    with pytest.raises(ErrorAuditoria):
        await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "1"))

    assert votacion.votos_ordinarios == {}
    assert votacion.estado is EstadoVotacion.EN_CURSO
    assert votacion.fecha_hora_cierre is None


async def test_fallo_del_autocierre_conserva_el_ultimo_voto_y_no_cierra(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El voto persistido/aplicado no se revierte si falla el cierre derivado."""

    entorno, votacion = await crear_votacion(tmp_path)
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "1"))
    contexto = entorno.estado.contexto_operativo_activo()
    assert contexto is not None
    instalar_fallo_en_evento(
        monkeypatch,
        contexto.escritor_auditoria,
        "VOTACION_CERRADA_COMPLETITUD",
    )

    with pytest.raises(ErrorAuditoria):
        await entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "3"))

    assert set(votacion.votos_ordinarios) == {"30000001", "30000002"}
    assert votacion.votos_ordinarios["30000002"].valor is ValorVotoOrdinario.NEGATIVO
    assert votacion.estado is EstadoVotacion.EN_CURSO
    assert votacion.fecha_hora_cierre is None
    assert votacion.resultado is None
    assert contexto.escritor_auditoria.fallado is True


async def test_fallo_del_autocierre_conserva_la_presencia_ya_aplicada(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un retiro auditado tampoco se revierte si falla su cierre derivado."""

    entorno, votacion = await crear_votacion(
        tmp_path,
        quorum=2,
        dispositivos_presentes=("D-01", "D-02", "D-03"),
    )
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "1"))
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "2"))
    contexto = entorno.estado.contexto_operativo_activo()
    assert contexto is not None
    instalar_fallo_en_evento(
        monkeypatch,
        contexto.escritor_auditoria,
        "VOTACION_CERRADA_COMPLETITUD",
    )

    with pytest.raises(ErrorAuditoria):
        await entorno.entrada.procesar_pulsacion(Pulsacion("D-03", "9"))

    assert contexto.presencias["30000003"] is False
    assert set(votacion.votos_ordinarios) == {"30000001", "30000002"}
    assert votacion.estado is EstadoVotacion.EN_CURSO
    assert votacion.fecha_hora_cierre is None
    assert contexto.escritor_auditoria.fallado is True


async def test_dos_votos_concurrentes_del_mismo_concejal_aceptan_uno(
    tmp_path: Path,
) -> None:
    """El lock global hace atómica la verificación de unicidad y la inserción."""

    entorno, votacion = await crear_votacion(tmp_path)

    respuestas = await asyncio.gather(
        entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "1")),
        entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "3")),
    )

    assert sum(respuesta.aceptada for respuesta in respuestas) == 1
    assert {respuesta.motivo for respuesta in respuestas} == {
        "VOTO_REGISTRADO",
        "VOTO_YA_EMITIDO",
    }
    assert len(votacion.votos_ordinarios) == 1


async def test_votos_concurrentes_distintos_se_ordenan_y_completan(
    tmp_path: Path,
) -> None:
    """Dos bancas conservan ambos votos y solo el segundo serializado cierra."""

    entorno, votacion = await crear_votacion(tmp_path)

    respuestas = await asyncio.gather(
        entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "1")),
        entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "2")),
    )

    assert all(respuesta.aceptada for respuesta in respuestas)
    assert set(votacion.votos_ordinarios) == {"30000001", "30000002"}
    assert votacion.estado is EstadoVotacion.CERRADA
    assert votacion.resultado is ResultadoVotacion.APROBADA
    codigos = [
        fila[4]
        for fila in filas_l1(entorno)
        if fila[4]
        in {
            "VOTO_ORDINARIO_REGISTRADO",
            "VOTACION_CERRADA_COMPLETITUD",
            "VOTACION_RESULTADO_FINAL",
        }
    ]
    assert codigos == [
        "VOTO_ORDINARIO_REGISTRADO",
        "VOTO_ORDINARIO_REGISTRADO",
        "VOTACION_CERRADA_COMPLETITUD",
        "VOTACION_RESULTADO_FINAL",
    ]


async def test_voto_concurrente_con_presencia_deja_un_estado_serializable(
    tmp_path: Path,
) -> None:
    """El orden del ejecutor decide si la última banca vota o queda ausente."""

    entorno, votacion = await crear_votacion(tmp_path)
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "1"))

    voto, presencia = await asyncio.gather(
        entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "3")),
        entorno.entrada.procesar_pulsacion(Pulsacion("D-02", "9")),
    )

    contexto = entorno.estado.contexto_operativo_activo()
    assert contexto is not None
    assert presencia.aceptada is True
    if voto.aceptada:
        assert votacion.estado is EstadoVotacion.CERRADA
        assert votacion.resultado is ResultadoVotacion.EMPATADA
        assert "30000002" in votacion.votos_ordinarios
        assert contexto.presencias["30000002"] is False
    else:
        assert voto.motivo == "CONCEJAL_AUSENTE"
        assert votacion.estado is EstadoVotacion.EN_CURSO
        assert "30000002" not in votacion.votos_ordinarios
        assert contexto.presencias["30000002"] is False


async def test_no_existe_mecanismo_para_corregir_o_eliminar_votos(
    tmp_path: Path,
) -> None:
    """La vista es de solo lectura y el valor aceptado es un dataclass frozen."""

    entorno, votacion = await crear_votacion(tmp_path)
    await entorno.entrada.procesar_pulsacion(Pulsacion("D-01", "1"))
    voto = votacion.votos_ordinarios["30000001"]
    vista_como_diccionario = cast(dict[str, VotoOrdinario], votacion.votos_ordinarios)

    with pytest.raises(TypeError):
        vista_como_diccionario["30000001"] = VotoOrdinario(
            dni="30000001",
            valor=ValorVotoOrdinario.NEGATIVO,
        )
    with pytest.raises(TypeError):
        del vista_como_diccionario["30000001"]
    campo_inmutable = "valor"
    with pytest.raises(FrozenInstanceError):
        setattr(voto, campo_inmutable, ValorVotoOrdinario.NEGATIVO)

    nombres_publicos = {nombre for nombre in dir(votacion) if not nombre.startswith("_")}
    assert nombres_publicos.isdisjoint(
        {"corregir_voto", "editar_voto", "eliminar_voto", "resetear_votos"}
    )
    assert entorno.estado.estado_global is EstadoGlobal.SESION_ABIERTA
