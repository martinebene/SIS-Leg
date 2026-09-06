"""Pruebas de dominio y servicio para la apertura de votaciones de WP-009."""

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
    TOML_CANONICO,
    escribir_padron,
    escribir_system_toml,
    filas_padron_valido,
)
from sis_leg_backend.auditoria import ErrorAuditoria, EscritorAuditoriaCsv, NivelAuditoria
from sis_leg_backend.dominio.entrada import Pulsacion
from sis_leg_backend.dominio.errores import (
    ErrorEstadoIncompatible,
    ErrorQuorumInsuficiente,
    ErrorTipoVotacionNoPermitido,
    ErrorVotacionPendiente,
)
from sis_leg_backend.dominio.estado import EstadoGlobal, EstadoOperativo
from sis_leg_backend.dominio.sesion import ActualizacionDatosInstitucionales
from sis_leg_backend.dominio.votacion import (
    BaseMayoria,
    DatosAperturaVotacion,
    EstadoVotacion,
    TipoMayoria,
    Votacion,
)
from sis_leg_backend.servicios.entrada import ServicioEntradaTecla
from sis_leg_backend.servicios.preparacion import ServicioPreparacion
from sis_leg_backend.servicios.serializacion import EjecutorMutaciones
from sis_leg_backend.servicios.sesion import ServicioSesion
from sis_leg_backend.servicios.votacion import ServicioVotacion

pytestmark = pytest.mark.anyio

HORA_INICIO = datetime(2026, 8, 21, 10, 0, 0)
HORA_SESION = datetime(2026, 8, 21, 10, 10, 0)
HORA_VOTACION = datetime(2026, 8, 21, 10, 20, 0)


def datos_simple(
    *,
    numero: int = 37,
    tipo: str = "Mocion",
    tema: str = "Tratamiento del proyecto X",
) -> DatosAperturaVotacion:
    """Construye una apertura SIMPLE ya normalizada, como la entregaría la API."""

    return DatosAperturaVotacion(
        numero_votacion=numero,
        tipo=tipo,
        tema=tema,
        tipo_mayoria=TipoMayoria.SIMPLE,
        factor=0.0,
        base=BaseMayoria.VOTOS_COMPUTABLES,
    )


def leer_filas_l1(estado: EstadoOperativo) -> list[list[str]]:
    """Lee todos los eventos del contexto auditable activo."""

    contexto = estado.contexto_operativo_activo()
    assert contexto is not None
    ruta = contexto.escritor_auditoria.rutas[NivelAuditoria.L1]
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.reader(archivo, delimiter=";"))


async def crear_servicios(
    tmp_path: Path,
    *,
    quorum: int = 1,
    generador_id: Callable[[], str] = lambda: "votacion-opaca-1",
) -> tuple[
    EstadoOperativo,
    ServicioSesion,
    ServicioEntradaTecla,
    ServicioVotacion,
]:
    """Prepara un recinto real y comparte un único serializador entre servicios."""

    ruta_configuracion = escribir_system_toml(
        tmp_path / "system.toml",
        TOML_CANONICO.replace(LINEA_LOGS, f'logs_dir = "{tmp_path / "logs"}"').replace(
            LINEA_QUORUM,
            f"quorum = {quorum}",
        ),
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
    return (
        estado,
        ServicioSesion(estado, ejecutor, reloj=lambda: HORA_SESION),
        ServicioEntradaTecla(estado, ejecutor, reloj_monotono=lambda: 10.0),
        ServicioVotacion(
            estado,
            ejecutor,
            reloj=lambda: HORA_VOTACION,
            generador_id=generador_id,
        ),
    )


async def abrir_sesion(
    servicio_sesion: ServicioSesion,
    servicio_entrada: ServicioEntradaTecla,
) -> None:
    """Completa autoridades, acredita quórum y abre la sesión de prueba."""

    await servicio_sesion.actualizar_preparacion(
        ActualizacionDatosInstitucionales(
            incluye_numero_sesion=True,
            numero_sesion=59,
            incluye_presidencia=True,
            presidencia="Presidencia Inicial",
            incluye_secretaria_legislativa=True,
            secretaria_legislativa="Secretaría Inicial",
        )
    )
    await servicio_entrada.procesar_pulsacion(Pulsacion("D-01", "9"))
    await servicio_sesion.abrir_sesion()


async def test_apertura_publica_una_sola_instancia_normalizada_y_auditada(
    tmp_path: Path,
) -> None:
    """La entidad del historial es idéntica a la activa y nace EN_CURSO."""

    estado, servicio_sesion, entrada, servicio = await crear_servicios(tmp_path)
    await abrir_sesion(servicio_sesion, entrada)

    votacion = await servicio.abrir_votacion(datos_simple())

    sesion = estado.sesion_activa
    assert sesion is not None
    assert votacion is estado.votacion_activa
    assert votacion is sesion.votaciones[0]
    assert len(sesion.votaciones) == 1
    assert votacion.id == "votacion-opaca-1"
    assert votacion.estado is EstadoVotacion.EN_CURSO
    assert votacion.resultado is None
    assert votacion.fecha_hora_cierre is None
    assert votacion.votos_ordinarios == {}
    assert votacion.factor == 0
    assert votacion.base is BaseMayoria.VOTOS_COMPUTABLES
    assert votacion.fecha_hora_apertura == HORA_VOTACION

    fila = leer_filas_l1(estado)[-1]
    assert fila[2:5] == ["L3", "VOTACION", "VOTACION_ABIERTA"]
    for fragmento in (
        "número=37",
        "tipo=Mocion",
        "tema=Tratamiento del proyecto X",
        "tipo_mayoria=SIMPLE",
        "factor=0.0",
        "base=VOTOS_COMPUTABLES",
    ):
        assert fragmento in fila[5]


async def test_precondiciones_estado_quorum_y_recuperacion(
    tmp_path: Path,
) -> None:
    """SIN_PREPARAR/PREPARANDO se rechazan y recuperar quórum habilita abrir."""

    estado_vacio = EstadoOperativo()
    servicio_vacio = ServicioVotacion(estado_vacio, EjecutorMutaciones())
    with pytest.raises(ErrorEstadoIncompatible):
        await servicio_vacio.abrir_votacion(datos_simple())

    estado, servicio_sesion, entrada, servicio = await crear_servicios(tmp_path)
    with pytest.raises(ErrorEstadoIncompatible):
        await servicio.abrir_votacion(datos_simple())
    assert leer_filas_l1(estado)[-1][4] == "COMANDO_VOTACION_RECHAZADO"

    await abrir_sesion(servicio_sesion, entrada)
    await entrada.procesar_pulsacion(Pulsacion("D-01", "9"))
    with pytest.raises(ErrorQuorumInsuficiente):
        await servicio.abrir_votacion(datos_simple())
    assert estado.votacion_activa is None

    await entrada.procesar_pulsacion(Pulsacion("D-01", "9"))
    votacion = await servicio.abrir_votacion(datos_simple())
    assert votacion is estado.votacion_activa


async def test_tipo_usa_snapshot_exacto_y_rechazo_se_audita(
    tmp_path: Path,
) -> None:
    """El servicio compara case-sensitive contra la configuración congelada."""

    estado, servicio_sesion, entrada, servicio = await crear_servicios(tmp_path)
    await abrir_sesion(servicio_sesion, entrada)

    with pytest.raises(ErrorTipoVotacionNoPermitido):
        await servicio.abrir_votacion(datos_simple(tipo="mocion"))

    assert estado.votacion_activa is None
    fila = leer_filas_l1(estado)[-1]
    assert fila[2:5] == ["L2", "VOTACION", "COMANDO_VOTACION_RECHAZADO"]
    assert "TIPO_VOTACION_NO_PERMITIDO" in fila[5]

    aceptada = await servicio.abrir_votacion(datos_simple(tipo="Mocion"))
    assert aceptada.tipo == "Mocion"


async def test_segunda_apertura_y_dos_aperturas_concurrentes_se_bloquean(
    tmp_path: Path,
) -> None:
    """El lock global permite una sola creación y ordena apertura antes de rechazo."""

    contador = iter(("id-primera", "id-que-no-debe-usarse"))
    estado, servicio_sesion, entrada, servicio = await crear_servicios(
        tmp_path,
        generador_id=lambda: next(contador),
    )
    await abrir_sesion(servicio_sesion, entrada)

    resultados = await asyncio.gather(
        servicio.abrir_votacion(datos_simple(numero=37)),
        servicio.abrir_votacion(datos_simple(numero=37, tema="Tema concurrente")),
        return_exceptions=True,
    )

    creadas = [resultado for resultado in resultados if isinstance(resultado, Votacion)]
    rechazos = [
        resultado for resultado in resultados if isinstance(resultado, ErrorVotacionPendiente)
    ]
    sesion = estado.sesion_activa
    assert sesion is not None
    assert len(creadas) == 1
    assert len(rechazos) == 1
    assert len(sesion.votaciones) == 1
    assert sesion.votaciones[0] is estado.votacion_activa is creadas[0]
    assert creadas[0].id == "id-primera"
    codigos = [
        fila[4]
        for fila in leer_filas_l1(estado)
        if fila[4] in {"VOTACION_ABIERTA", "COMANDO_VOTACION_RECHAZADO"}
    ]
    assert codigos[-2:] == ["VOTACION_ABIERTA", "COMANDO_VOTACION_RECHAZADO"]


@pytest.mark.parametrize(
    ("numero_historico", "numero_nuevo"),
    [(37, 37), (999, 1)],
    ids=["numero-repetido", "fuera-de-secuencia"],
)
async def test_historial_no_impone_unicidad_ni_secuencia_institucional(
    tmp_path: Path,
    numero_historico: int,
    numero_nuevo: int,
) -> None:
    """Una votación final futura no condicionará el número de la siguiente."""

    identificadores = iter(("id-historica", "id-nueva"))
    estado, servicio_sesion, entrada, servicio = await crear_servicios(
        tmp_path,
        generador_id=lambda: next(identificadores),
    )
    await abrir_sesion(servicio_sesion, entrada)
    historica = await servicio.abrir_votacion(datos_simple(numero=numero_historico))

    # WP-009 no implementa la finalización. Esta asignación representa la
    # condición que dejará un WP posterior: la entidad sigue en historial,
    # pero ya no bloquea una nueva apertura.
    estado.votacion_activa = None
    nueva = await servicio.abrir_votacion(datos_simple(numero=numero_nuevo))

    sesion = estado.sesion_activa
    assert sesion is not None
    assert sesion.votaciones == [historica, nueva]
    assert [votacion.numero_votacion for votacion in sesion.votaciones] == [
        numero_historico,
        numero_nuevo,
    ]
    assert historica.id != nueva.id


async def test_datos_constitutivos_no_admiten_reasignacion(tmp_path: Path) -> None:
    """Cada propiedad constitutiva carece de setter, aunque el estado sea evolutivo."""

    _estado, servicio_sesion, entrada, servicio = await crear_servicios(tmp_path)
    await abrir_sesion(servicio_sesion, entrada)
    votacion = await servicio.abrir_votacion(datos_simple())

    cambios: dict[str, object] = {
        "id": "otro",
        "numero_votacion": 99,
        "tipo": "Otro",
        "tema": "Otro tema",
        "tipo_mayoria": TipoMayoria.ESPECIAL,
        "factor": 0.5,
        "base": BaseMayoria.CUERPO,
        "fecha_hora_apertura": datetime(2026, 8, 21, 11, 0, 0),
    }
    for campo, valor in cambios.items():
        with pytest.raises(AttributeError):
            setattr(votacion, campo, valor)

    assert votacion.numero_votacion == 37
    assert votacion.tema == "Tratamiento del proyecto X"


async def test_fallo_de_auditoria_no_publica_mutacion_parcial(tmp_path: Path) -> None:
    """Un writer no disponible corta antes de historial y referencia activa."""

    estado, servicio_sesion, entrada, servicio = await crear_servicios(tmp_path)
    await abrir_sesion(servicio_sesion, entrada)
    sesion = estado.sesion_activa
    assert sesion is not None
    sesion.contexto_operativo.escritor_auditoria.cerrar()

    with pytest.raises(ErrorAuditoria):
        await servicio.abrir_votacion(datos_simple())

    assert sesion.votaciones == []
    assert estado.votacion_activa is None


async def test_capacidades_de_sesion_conviven_con_votacion_activa(tmp_path: Path) -> None:
    """Autoridades, 8/9 y palabra conviven; voto y palabra exigen presencia."""

    estado, servicio_sesion, entrada, servicio = await crear_servicios(tmp_path)
    await abrir_sesion(servicio_sesion, entrada)
    # D-02 conserva el quórum cuando D-01 se retira. Así esta regresión sigue
    # aislando la convivencia de capacidades sin activar el nuevo cierre por
    # pérdida de quórum, que WP-013 prueba en escenarios específicos.
    await entrada.procesar_pulsacion(Pulsacion("D-02", "9"))
    votacion = await servicio.abrir_votacion(datos_simple())

    await servicio_sesion.actualizar_autoridades(
        ActualizacionDatosInstitucionales(
            incluye_presidencia=True,
            presidencia="Nueva Presidencia",
            incluye_secretaria_legislativa=True,
            secretaria_legislativa="Nueva Secretaría",
        )
    )
    prueba = await entrada.procesar_pulsacion(Pulsacion("D-02", "8"))
    retiro = await entrada.procesar_pulsacion(Pulsacion("D-01", "9"))
    assert prueba.aceptada is True
    assert retiro.aceptada is True
    for tecla in ("1", "2", "3"):
        respuesta = await entrada.procesar_pulsacion(Pulsacion("D-01", tecla))
        assert respuesta.aceptada is False
        assert respuesta.motivo == "CONCEJAL_AUSENTE"
    palabra = await entrada.procesar_pulsacion(Pulsacion("D-01", "7"))
    assert palabra.aceptada is False
    assert palabra.motivo == "CONCEJAL_AUSENTE"

    sesion = estado.sesion_activa
    assert sesion is not None
    assert sesion.presidencia == "Nueva Presidencia"
    assert sesion.secretaria_legislativa == "Nueva Secretaría"
    await servicio_sesion.cerrar_sesion()
    assert votacion.resultado is not None
    assert votacion.resultado.value == "INCONCLUSA"
    assert estado.votacion_activa is None
    assert estado.estado_global is EstadoGlobal.SIN_PREPARAR
