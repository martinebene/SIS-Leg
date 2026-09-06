"""Pruebas de dominio/servicio del ciclo institucional de WP-008.

Los escenarios usan el escritor CSV y el serializador reales. Esto permite
demostrar no solo el estado final, sino también identidad de objetos, orden de
eventos y fallo cerrado sin introducir dobles que oculten el flujo productivo.
"""

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
from sis_leg_backend.auditoria import (
    ErrorAuditoria,
    ErrorEscritorNoDisponible,
    EscritorAuditoriaCsv,
    NivelAuditoria,
)
from sis_leg_backend.dominio.entrada import Pulsacion, ResultadoPalabra, ResultadoPresencia
from sis_leg_backend.dominio.errores import (
    ErrorEstadoIncompatible,
    ErrorNumeroSesionRequerido,
    ErrorPresidenciaRequerida,
    ErrorQuorumInsuficiente,
    ErrorSecretariaLegislativaRequerida,
    ErrorVotacionPendiente,
)
from sis_leg_backend.dominio.estado import EstadoGlobal, EstadoOperativo
from sis_leg_backend.dominio.sesion import ActualizacionDatosInstitucionales
from sis_leg_backend.dominio.votacion import BaseMayoria, TipoMayoria, Votacion
from sis_leg_backend.hechos_operativos import ReferenciaHechoOperativo
from sis_leg_backend.servicios.entrada import ServicioEntradaTecla
from sis_leg_backend.servicios.preparacion import ServicioPreparacion
from sis_leg_backend.servicios.serializacion import EjecutorMutaciones
from sis_leg_backend.servicios.sesion import ServicioSesion

pytestmark = pytest.mark.anyio

HORA_INICIO = datetime(2026, 8, 21, 9, 0, 0)
HORA_APERTURA = datetime(2026, 8, 21, 9, 15, 0)


def leer_filas(ruta: Path) -> list[list[str]]:
    """Lee un CSV institucional con su codificación y separador canónicos."""

    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.reader(archivo, delimiter=";"))


def filas_l1(estado: EstadoOperativo) -> list[list[str]]:
    """Devuelve el nivel que contiene todos los eventos del contexto activo."""

    contexto = estado.contexto_operativo_activo()
    assert contexto is not None
    return leer_filas(contexto.escritor_auditoria.rutas[NivelAuditoria.L1])


async def crear_contexto(
    tmp_path: Path,
    *,
    quorum: int = 1,
    reloj_monotono: Callable[[], float] = lambda: 10.0,
    fabrica_escritor: Callable[[Path, datetime], EscritorAuditoriaCsv] | None = None,
) -> tuple[
    EstadoOperativo,
    ServicioSesion,
    ServicioEntradaTecla,
]:
    """Prepara un recinto ficticio y comparte estado/ejecutor entre servicios."""

    ruta_configuracion = escribir_system_toml(
        tmp_path / "system.toml",
        TOML_CANONICO.replace(LINEA_LOGS, f'logs_dir = "{tmp_path / "logs"}"').replace(
            LINEA_QUORUM,
            f"quorum = {quorum}",
        ),
    )
    ruta_padron = escribir_padron(
        tmp_path / "concejales.csv",
        filas_padron_valido(),
    )
    estado = EstadoOperativo()
    ejecutor = EjecutorMutaciones()
    servicio_preparacion = ServicioPreparacion(
        estado,
        ejecutor,
        ruta_configuracion=ruta_configuracion,
        ruta_padron=ruta_padron,
        reloj=lambda: HORA_INICIO,
        fabrica_escritor=fabrica_escritor
        or partial(EscritorAuditoriaCsv, reloj=lambda: HORA_INICIO),
    )
    await servicio_preparacion.preparar_sala()
    return (
        estado,
        ServicioSesion(estado, ejecutor, reloj=lambda: HORA_APERTURA),
        ServicioEntradaTecla(
            estado,
            ejecutor,
            reloj_monotono=reloj_monotono,
        ),
    )


def datos_completos(
    *,
    numero: int = 59,
    presidencia: str = "Presidencia Inicial",
    secretaria: str = "Secretaría Inicial",
) -> ActualizacionDatosInstitucionales:
    """Construye la actualización completa usada para abrir escenarios válidos."""

    return ActualizacionDatosInstitucionales(
        incluye_numero_sesion=True,
        numero_sesion=numero,
        incluye_presidencia=True,
        presidencia=presidencia,
        incluye_secretaria_legislativa=True,
        secretaria_legislativa=secretaria,
    )


async def abrir_contexto_valido(
    servicio_sesion: ServicioSesion,
    servicio_entrada: ServicioEntradaTecla,
) -> None:
    """Completa datos/quórum y abre mediante las interfaces públicas."""

    await servicio_sesion.actualizar_preparacion(datos_completos())
    await servicio_entrada.procesar_pulsacion(Pulsacion("D-01", "9"))
    await servicio_sesion.abrir_sesion()


@pytest.mark.parametrize(
    ("actualizacion", "atributo", "esperado", "codigo"),
    [
        (
            ActualizacionDatosInstitucionales(
                incluye_numero_sesion=True,
                numero_sesion=59,
            ),
            "numero_sesion",
            59,
            "NUMERO_SESION_ACTUALIZADO",
        ),
        (
            ActualizacionDatosInstitucionales(
                incluye_presidencia=True,
                presidencia="  Presidencia  ",
            ),
            "presidencia",
            "Presidencia",
            "PRESIDENCIA_ACTUALIZADA",
        ),
        (
            ActualizacionDatosInstitucionales(
                incluye_secretaria_legislativa=True,
                secretaria_legislativa="  Secretaría  ",
            ),
            "secretaria_legislativa",
            "Secretaría",
            "SECRETARIA_LEGISLATIVA_ACTUALIZADA",
        ),
    ],
)
async def test_actualizacion_preparatoria_individual_normaliza_y_audita(
    tmp_path: Path,
    actualizacion: ActualizacionDatosInstitucionales,
    atributo: str,
    esperado: int | str,
    codigo: str,
) -> None:
    """Cada campo puede actualizarse solo y registra ausencia -> valor."""

    estado, servicio, _entrada = await crear_contexto(tmp_path)
    await servicio.actualizar_preparacion(actualizacion)

    preparacion = estado.preparacion_activa
    assert preparacion is not None
    assert getattr(preparacion, atributo) == esperado
    assert filas_l1(estado)[-1][4] == codigo
    assert "sin informar ->" in filas_l1(estado)[-1][5]


async def test_actualizacion_multiple_respeta_orden_y_permite_limpiar(
    tmp_path: Path,
) -> None:
    """Número, Presidencia y Secretaría se auditan en el orden aprobado."""

    estado, servicio, _entrada = await crear_contexto(tmp_path)
    await servicio.actualizar_preparacion(datos_completos())
    await servicio.actualizar_preparacion(
        ActualizacionDatosInstitucionales(
            incluye_presidencia=True,
            presidencia="   ",
            incluye_secretaria_legislativa=True,
            secretaria_legislativa="",
        )
    )

    preparacion = estado.preparacion_activa
    assert preparacion is not None
    assert preparacion.numero_sesion == 59
    assert preparacion.presidencia is None
    assert preparacion.secretaria_legislativa is None
    assert [fila[4] for fila in filas_l1(estado)[-5:]] == [
        "NUMERO_SESION_ACTUALIZADO",
        "PRESIDENCIA_ACTUALIZADA",
        "SECRETARIA_LEGISLATIVA_ACTUALIZADA",
        "PRESIDENCIA_ACTUALIZADA",
        "SECRETARIA_LEGISLATIVA_ACTUALIZADA",
    ]
    assert filas_l1(estado)[-1][5].endswith("Secretaría Inicial -> sin informar")


async def test_repeticion_y_noop_no_generan_eventos_ficticios(tmp_path: Path) -> None:
    """Un número repetido/fuera de secuencia es válido y repetir estado es no-op."""

    estado, servicio, _entrada = await crear_contexto(tmp_path)
    await servicio.actualizar_preparacion(
        ActualizacionDatosInstitucionales(
            incluye_numero_sesion=True,
            numero_sesion=999,
            incluye_presidencia=True,
            presidencia="Presidencia",
        )
    )
    cantidad_eventos = len(filas_l1(estado))

    await servicio.actualizar_preparacion(
        ActualizacionDatosInstitucionales(
            incluye_numero_sesion=True,
            numero_sesion=999,
            incluye_presidencia=True,
            presidencia="  Presidencia  ",
        )
    )

    assert len(filas_l1(estado)) == cantidad_eventos


async def test_apertura_evalua_precondiciones_en_orden_y_audita_rechazos(
    tmp_path: Path,
) -> None:
    """Cada requisito faltante produce su excepción estable antes del siguiente."""

    estado, servicio, entrada = await crear_contexto(tmp_path)

    with pytest.raises(ErrorQuorumInsuficiente):
        await servicio.abrir_sesion()
    await entrada.procesar_pulsacion(Pulsacion("D-01", "9"))

    with pytest.raises(ErrorNumeroSesionRequerido):
        await servicio.abrir_sesion()
    await servicio.actualizar_preparacion(
        ActualizacionDatosInstitucionales(
            incluye_numero_sesion=True,
            numero_sesion=59,
        )
    )

    with pytest.raises(ErrorPresidenciaRequerida):
        await servicio.abrir_sesion()
    await servicio.actualizar_preparacion(
        ActualizacionDatosInstitucionales(
            incluye_presidencia=True,
            presidencia="Presidencia",
        )
    )

    with pytest.raises(ErrorSecretariaLegislativaRequerida):
        await servicio.abrir_sesion()

    rechazos = [fila[5] for fila in filas_l1(estado) if fila[4] == "COMANDO_SESION_RECHAZADO"]
    assert [mensaje.rsplit("=", 1)[1] for mensaje in rechazos] == [
        "QUORUM_INSUFICIENTE",
        "NUMERO_SESION_REQUERIDO",
        "PRESIDENCIA_REQUERIDA",
        "SECRETARIA_LEGISLATIVA_REQUERIDA",
    ]


async def test_abrir_fuera_de_preparando_rechaza_sin_estado_parcial() -> None:
    """SIN_PREPARAR no tiene writer, pero conserva el 409 de dominio."""

    estado = EstadoOperativo()
    servicio = ServicioSesion(estado, EjecutorMutaciones())

    with pytest.raises(ErrorEstadoIncompatible):
        await servicio.abrir_sesion()

    assert estado.estado_global is EstadoGlobal.SIN_PREPARAR
    assert estado.sesion_activa is None


async def test_apertura_conserva_identidades_y_expiracion_exacta(
    tmp_path: Path,
) -> None:
    """La transición mueve la referencia sin reconstruir ningún dato operativo."""

    estado, servicio, entrada = await crear_contexto(
        tmp_path,
        reloj_monotono=lambda: 10.0,
    )
    await servicio.actualizar_preparacion(datos_completos())
    await entrada.procesar_pulsacion(Pulsacion("D-01", "9"))
    await entrada.procesar_pulsacion(Pulsacion("D-02", "8"))

    preparacion = estado.preparacion_activa
    assert preparacion is not None
    configuracion = preparacion.configuracion
    padron = preparacion.padron
    presencias = preparacion.presencias
    expiraciones = preparacion.expiraciones_test
    escritor = preparacion.escritor_auditoria
    rutas = estado.archivos_auditoria_activos
    expiracion = expiraciones["30000002"]

    await servicio.abrir_sesion()

    sesion = estado.sesion_activa
    assert sesion is not None
    contexto = sesion.contexto_operativo
    assert estado.estado_global is EstadoGlobal.SESION_ABIERTA
    assert estado.preparacion_activa is None
    assert contexto is preparacion
    assert contexto.configuracion is configuracion
    assert contexto.padron is padron
    assert contexto.presencias is presencias
    assert contexto.expiraciones_test is expiraciones
    assert contexto.escritor_auditoria is escritor
    assert estado.archivos_auditoria_activos is rutas
    assert contexto.expiraciones_test["30000002"] == expiracion == 10.6
    assert contexto.test_dispositivo_activo("30000002", 10.59)
    assert sesion.numero_sesion == 59
    assert sesion.fecha_hora_apertura == HORA_APERTURA
    assert filas_l1(estado)[-1][4] == "SESION_ABIERTA"
    assert "59" in filas_l1(estado)[-1][5]


async def test_cambios_de_autoridades_en_sesion_son_normalizados_y_noop(
    tmp_path: Path,
) -> None:
    """Las autoridades cambian, el número permanece y no-op no audita."""

    estado, servicio, entrada = await crear_contexto(tmp_path)
    await abrir_contexto_valido(servicio, entrada)
    sesion = estado.sesion_activa
    assert sesion is not None
    numero = sesion.numero_sesion

    await servicio.actualizar_autoridades(
        ActualizacionDatosInstitucionales(
            incluye_presidencia=True,
            presidencia="  Nueva Presidencia ",
            incluye_secretaria_legislativa=True,
            secretaria_legislativa=" Nueva Secretaría ",
        )
    )
    cantidad_eventos = len(filas_l1(estado))
    await servicio.actualizar_autoridades(
        ActualizacionDatosInstitucionales(
            incluye_presidencia=True,
            presidencia="Nueva Presidencia",
            incluye_secretaria_legislativa=True,
            secretaria_legislativa="Nueva Secretaría",
        )
    )

    assert sesion.numero_sesion == numero
    assert sesion.presidencia == "Nueva Presidencia"
    assert sesion.secretaria_legislativa == "Nueva Secretaría"
    assert len(filas_l1(estado)) == cantidad_eventos
    assert [fila[4] for fila in filas_l1(estado)[-2:]] == [
        "PRESIDENCIA_ACTUALIZADA",
        "SECRETARIA_LEGISLATIVA_ACTUALIZADA",
    ]


@pytest.mark.parametrize("tecla", ["1", "2", "3"])
async def test_votos_sin_votacion_siguen_rechazados_en_sesion(
    tmp_path: Path,
    tecla: str,
) -> None:
    """WP-010 distingue una tecla de voto cuando no hay recepción abierta."""

    _estado, servicio, entrada = await crear_contexto(tmp_path)
    await abrir_contexto_valido(servicio, entrada)

    respuesta = await entrada.procesar_pulsacion(Pulsacion("D-01", tecla))

    assert respuesta.aceptada is False
    assert respuesta.motivo == "VOTACION_NO_EN_CURSO"


async def test_tecla_de_palabra_usa_el_contexto_de_sesion(tmp_path: Path) -> None:
    """WP-015 incorpora tecla 7 sin crear un contexto operativo paralelo."""

    _estado, servicio, entrada = await crear_contexto(tmp_path)
    await abrir_contexto_valido(servicio, entrada)

    respuesta = await entrada.procesar_pulsacion(Pulsacion("D-01", "7"))

    assert respuesta.aceptada is True
    assert respuesta.motivo == "PEDIDO_PALABRA_REGISTRADO"
    assert isinstance(respuesta.resultado, ResultadoPalabra)


async def test_entradas_ocho_nueve_y_dispositivo_inexistente_en_sesion(
    tmp_path: Path,
) -> None:
    """La misma lógica WP-006 opera sobre el contexto compuesto por sesión."""

    estado, servicio, entrada = await crear_contexto(tmp_path)
    await abrir_contexto_valido(servicio, entrada)
    sesion = estado.sesion_activa
    assert sesion is not None

    retiro = await entrada.procesar_pulsacion(Pulsacion("D-01", "9"))
    prueba = await entrada.procesar_pulsacion(Pulsacion("D-02", "8"))
    desconocido = await entrada.procesar_pulsacion(Pulsacion("NO-ASIGNADO", "9"))

    assert retiro.motivo == "PRESENCIA_ACTUALIZADA"
    assert isinstance(retiro.resultado, ResultadoPresencia)
    assert retiro.resultado.quorum_alcanzado is False
    assert prueba.motivo == "TEST_ACTIVADO"
    assert sesion.contexto_operativo.expiraciones_test["30000002"] == 10.6
    assert desconocido.motivo == "DISPOSITIVO_NO_ASIGNADO"


async def test_perdida_y_recuperacion_de_quorum_no_cierran_sesion(
    tmp_path: Path,
) -> None:
    """Fuera de votación el quórum es derivado y la sesión conserva identidad."""

    estado, servicio, entrada = await crear_contexto(tmp_path)
    await abrir_contexto_valido(servicio, entrada)
    sesion = estado.sesion_activa
    assert sesion is not None

    perdida = await entrada.procesar_pulsacion(Pulsacion("D-01", "9"))
    recuperacion = await entrada.procesar_pulsacion(Pulsacion("D-01", "9"))

    assert isinstance(perdida.resultado, ResultadoPresencia)
    assert perdida.resultado.quorum_alcanzado is False
    assert isinstance(recuperacion.resultado, ResultadoPresencia)
    assert recuperacion.resultado.quorum_alcanzado is True
    assert estado.estado_global is EstadoGlobal.SESION_ABIERTA
    assert estado.sesion_activa is sesion


class EscritorOrdenCierre(EscritorAuditoriaCsv):
    """Writer real que registra el orden observable del evento y ``cerrar``."""

    acciones: list[str] = []

    def registrar_evento(
        self,
        nivel: NivelAuditoria,
        etiqueta: str,
        codigo_evento: str,
        mensaje: str,
        *,
        referencia: ReferenciaHechoOperativo | None = None,
    ) -> int:
        if codigo_evento == "SESION_CERRADA":
            self.acciones.append("evento")
        return super().registrar_evento(
            nivel, etiqueta, codigo_evento, mensaje, referencia=referencia
        )

    def cerrar(self) -> None:
        self.acciones.append("cerrar")
        super().cerrar()


async def test_cierre_normal_evento_antes_de_writer_y_limpieza_total(
    tmp_path: Path,
) -> None:
    """El éxito solo limpia luego de persistir y cerrar los tres CSV."""

    EscritorOrdenCierre.acciones = []
    estado, servicio, entrada = await crear_contexto(
        tmp_path,
        fabrica_escritor=EscritorOrdenCierre,
    )
    await abrir_contexto_valido(servicio, entrada)
    sesion = estado.sesion_activa
    assert sesion is not None
    escritor = sesion.contexto_operativo.escritor_auditoria
    rutas = estado.archivos_auditoria_activos

    await servicio.cerrar_sesion()

    assert EscritorOrdenCierre.acciones == ["evento", "cerrar"]
    assert estado.estado_global is EstadoGlobal.SIN_PREPARAR
    assert estado.preparacion_activa is None
    assert estado.sesion_activa is None
    assert estado.votacion_activa is None
    assert estado.archivos_auditoria_activos == ()
    assert escritor.cerrado
    for ruta in rutas:
        assert leer_filas(ruta)[-1][4] == "SESION_CERRADA"
        assert "59" in leer_filas(ruta)[-1][5]
    with pytest.raises(ErrorEscritorNoDisponible):
        escritor.registrar_evento(NivelAuditoria.L3, "SESION", "OTRO", "No escribir")


async def test_fallo_al_escribir_cierre_conserva_sesion_y_rutas(
    tmp_path: Path,
) -> None:
    """Un writer ya cerrado impide confirmar cualquier parte del cierre."""

    estado, servicio, entrada = await crear_contexto(tmp_path)
    await abrir_contexto_valido(servicio, entrada)
    sesion = estado.sesion_activa
    assert sesion is not None
    rutas = estado.archivos_auditoria_activos
    sesion.contexto_operativo.escritor_auditoria.cerrar()

    with pytest.raises(ErrorAuditoria):
        await servicio.cerrar_sesion()

    assert estado.estado_global is EstadoGlobal.SESION_ABIERTA
    assert estado.sesion_activa is sesion
    assert estado.archivos_auditoria_activos == rutas


class EscritorCierreFallido(EscritorAuditoriaCsv):
    """Writer que persiste el evento pero informa fallo al cerrar."""

    def cerrar(self) -> None:
        super().cerrar()
        raise ErrorAuditoria("fallo simulado al cerrar")


async def test_evento_persistido_y_cierre_writer_fallido_mantiene_contexto(
    tmp_path: Path,
) -> None:
    """No se borra evidencia ni se vuelve a SIN_PREPARAR tras fallo físico."""

    estado, servicio, entrada = await crear_contexto(
        tmp_path,
        fabrica_escritor=EscritorCierreFallido,
    )
    await abrir_contexto_valido(servicio, entrada)
    sesion = estado.sesion_activa
    assert sesion is not None
    rutas = estado.archivos_auditoria_activos

    with pytest.raises(ErrorAuditoria, match="cerrar"):
        await servicio.cerrar_sesion()

    assert estado.estado_global is EstadoGlobal.SESION_ABIERTA
    assert estado.sesion_activa is sesion
    assert estado.archivos_auditoria_activos == rutas
    assert leer_filas(rutas[0])[-1][4] == "SESION_CERRADA"


async def test_votacion_cerrada_sin_resultado_rechaza_sin_recovery(
    tmp_path: Path,
) -> None:
    """El caso técnico CERRADA + None no se repara al cerrar sesión."""

    estado, servicio, entrada = await crear_contexto(tmp_path)
    await abrir_contexto_valido(servicio, entrada)
    sesion = estado.sesion_activa
    marcador_votacion = Votacion(
        id="votacion-pendiente",
        numero_votacion=37,
        tipo="Mocion",
        tema="Tema pendiente",
        tipo_mayoria=TipoMayoria.SIMPLE,
        factor=0.0,
        base=BaseMayoria.VOTOS_COMPUTABLES,
        fecha_hora_apertura=HORA_APERTURA,
    )
    marcador_votacion.cerrar_recepcion(HORA_APERTURA)
    estado.votacion_activa = marcador_votacion

    with pytest.raises(ErrorVotacionPendiente):
        await servicio.cerrar_sesion()

    assert estado.estado_global is EstadoGlobal.SESION_ABIERTA
    assert estado.sesion_activa is sesion
    assert estado.votacion_activa is marcador_votacion
    assert filas_l1(estado)[-1][4] == "COMANDO_SESION_RECHAZADO"
    assert "VOTACION_PENDIENTE" in filas_l1(estado)[-1][5]


async def test_auditoria_indisponible_impide_actualizacion_y_apertura(
    tmp_path: Path,
) -> None:
    """Una auditoría ya cerrada bloquea cambios y conserva la preparación."""

    estado, servicio, entrada = await crear_contexto(tmp_path)
    await servicio.actualizar_preparacion(
        ActualizacionDatosInstitucionales(
            incluye_numero_sesion=True,
            numero_sesion=59,
            incluye_presidencia=True,
            presidencia="Presidencia inicial",
            incluye_secretaria_legislativa=True,
            secretaria_legislativa="Secretaría inicial",
        )
    )
    await entrada.procesar_pulsacion(Pulsacion("D-01", "9"))
    preparacion = estado.preparacion_activa
    assert preparacion is not None
    escritor = preparacion.escritor_auditoria
    escritor.cerrar()

    with pytest.raises(ErrorAuditoria):
        await servicio.actualizar_preparacion(
            ActualizacionDatosInstitucionales(
                incluye_presidencia=True,
                presidencia="Presidencia nueva",
            )
        )

    with pytest.raises(ErrorAuditoria):
        await servicio.abrir_sesion()

    assert preparacion.presidencia == "Presidencia inicial"
    assert estado.estado_global is EstadoGlobal.PREPARANDO
    assert estado.preparacion_activa is preparacion
    assert preparacion.escritor_auditoria is escritor


async def test_actualizaciones_concurrentes_comparten_serializador_y_writer(
    tmp_path: Path,
) -> None:
    """Dos comandos concurrentes quedan ordenados por el ejecutor único."""

    estado, servicio, entrada = await crear_contexto(tmp_path)
    await abrir_contexto_valido(servicio, entrada)

    await asyncio.gather(
        servicio.actualizar_autoridades(
            ActualizacionDatosInstitucionales(
                incluye_presidencia=True,
                presidencia="Presidencia A",
            )
        ),
        servicio.actualizar_autoridades(
            ActualizacionDatosInstitucionales(
                incluye_presidencia=True,
                presidencia="Presidencia B",
            )
        ),
    )

    sesion = estado.sesion_activa
    assert sesion is not None
    eventos = [fila for fila in filas_l1(estado) if fila[4] == "PRESIDENCIA_ACTUALIZADA"]
    assert len(eventos) == 3
    secuencias = [int(fila[0]) for fila in eventos]
    assert secuencias == sorted(secuencias)
    assert sesion.presidencia in {"Presidencia A", "Presidencia B"}
    assert eventos[-1][5].endswith(sesion.presidencia)
