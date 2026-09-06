"""Regresión integral del remapeo físico thread-safe de WP-020."""

from __future__ import annotations

import json
import os
import threading
import urllib.request
from pathlib import Path
from unittest.mock import patch

import pytest
from sis_leg_device_bridge.adaptador_linux import AdaptadorFalso
from sis_leg_device_bridge.cliente_http import ClienteHttpBackend
from sis_leg_device_bridge.configuracion import ConfiguracionBridge, cargar_dispositivos_json
from sis_leg_device_bridge.modelos import (
    EventoTeclaFisica,
    RespuestaEnvioBackend,
    SolicitudEntradaLogica,
)
from sis_leg_device_bridge.remapeo import (
    CoordinadorRemapeoBridge,
    ErrorControlRemapeo,
    PersistenciaRemapeo,
)
from sis_leg_device_bridge.servicio import ServicioDeviceBridge
from sis_leg_device_bridge.servidor_control import ServidorControlBridge

FP_BASE_01 = "lin|vendor=1001|product=2001|version=0001|phys=usb-1|uniq=|name=Base 1"
FP_BASE_02 = "lin|vendor=1002|product=2002|version=0001|phys=usb-2|uniq=|name=Base 2"
FP_NUEVO_A = "lin|vendor=9001|product=9001|version=0001|phys=usb-a|uniq=|name=Nuevo A"
FP_NUEVO_B = "lin|vendor=9002|product=9002|version=0001|phys=usb-b|uniq=|name=Nuevo B"


class ClienteFisicoFalso(ClienteHttpBackend):
    """Registra pulsaciones y callbacks sin red real."""

    def __init__(self) -> None:
        super().__init__("http://backend-falso")
        self.pulsaciones: list[dict[str, str]] = []
        self.candidatos: list[dict[str, str]] = []

    def enviar_pulsacion(self, solicitud: SolicitudEntradaLogica) -> RespuestaEnvioBackend:
        dispositivo = solicitud.dispositivo
        tecla = solicitud.tecla
        self.pulsaciones.append({"dispositivo": dispositivo, "tecla": tecla})
        return RespuestaEnvioBackend(True, 200, "ACEPTADA", {"aceptada": True})

    def informar_candidato(self, remapeo_id: str, fingerprint: str, diagnostico: str) -> bool:
        self.candidatos.append(
            {
                "remapeo_id": remapeo_id,
                "fingerprint": fingerprint,
                "diagnostico": diagnostico,
            }
        )
        return True


def escribir_devices(ruta: Path) -> dict[str, str]:
    """Crea un archivo base pequeño y válido dentro del tmp del test."""

    mapeo = {FP_BASE_01: "dev01", FP_BASE_02: "dev02"}
    ruta.write_text(json.dumps(mapeo, indent=2) + "\n", encoding="utf-8")
    return mapeo


def evento(fingerprint: str, *, bajada: bool = True) -> EventoTeclaFisica:
    """Construye un evento físico legible para los escenarios de captura."""

    return EventoTeclaFisica(
        fingerprint=fingerprint,
        codigo_tecla=2,
        nombre_tecla="KEY_1",
        es_bajada=bajada,
        descripcion_dispositivo="Teclado de prueba",
    )


def coordinador_preparado(tmp_path: Path) -> tuple[CoordinadorRemapeoBridge, Path]:
    """Devuelve un coordinador cuya persistencia nunca toca el repo."""

    ruta = tmp_path / "devices.json"
    mapeo = escribir_devices(ruta)
    return CoordinadorRemapeoBridge(ruta, mapeo), ruta


def congelar_candidato(
    coordinador: CoordinadorRemapeoBridge,
    remapeo_id: str,
    dispositivo: str,
    fingerprint: str,
) -> None:
    """Avanza una operación hasta CANDIDATO para reducir ruido de tests."""

    coordinador.iniciar_captura(remapeo_id, dispositivo)
    assert coordinador.considerar_candidato(evento(fingerprint)) is not None


def test_inicio_idempotente_y_parametros_incompatibles(tmp_path: Path) -> None:
    """Mismo ID/devXX no duplica; mismo ID con otro devXX se rechaza."""

    coordinador, _ = coordinador_preparado(tmp_path)
    primera = coordinador.iniciar_captura("id-1", "dev01")
    repetida = coordinador.iniciar_captura("id-1", "dev01")
    assert primera == repetida

    with pytest.raises(ErrorControlRemapeo) as error:
        coordinador.iniciar_captura("id-1", "dev02")
    assert error.value.codigo == "PARAMETROS_INCOMPATIBLES"


def test_mapeados_siguen_operativos_y_nunca_son_candidato(tmp_path: Path) -> None:
    """Durante captura, dev02 vota normalmente y no se convierte en dev01."""

    ruta = tmp_path / "devices.json"
    mapeo = escribir_devices(ruta)
    adaptador = AdaptadorFalso()
    cliente = ClienteFisicoFalso()
    servicio = ServicioDeviceBridge(
        ConfiguracionBridge(ruta_devices_json=ruta), adaptador, cliente, mapeo
    )
    adaptador.agregar_dispositivo("/dev/event1", FP_BASE_01)
    adaptador.agregar_dispositivo("/dev/event2", FP_BASE_02)
    servicio.ejecutar_ciclo_descubrimiento()
    servicio.coordinador_remapeo.iniciar_captura("id-normal", "dev01")

    adaptador.simular_evento("/dev/event2", evento(FP_BASE_02))
    adaptador.simular_evento("/dev/event1", evento(FP_BASE_01))
    respuestas = servicio.ejecutar_paso()

    assert len(respuestas) == 2
    assert cliente.pulsaciones == [
        {"dispositivo": "dev01", "tecla": "1"},
        {"dispositivo": "dev02", "tecla": "1"},
    ]
    assert cliente.candidatos == []
    assert servicio.coordinador_remapeo.consultar("id-normal")["estado"] == "CAPTURANDO"


def test_primer_elegible_se_congela_y_no_se_envia_como_pulsacion(tmp_path: Path) -> None:
    """El primer desconocido queda candidato; el segundo no lo sustituye."""

    ruta = tmp_path / "devices.json"
    mapeo = escribir_devices(ruta)
    adaptador = AdaptadorFalso()
    cliente = ClienteFisicoFalso()
    servicio = ServicioDeviceBridge(
        ConfiguracionBridge(ruta_devices_json=ruta), adaptador, cliente, mapeo
    )
    adaptador.agregar_dispositivo("/dev/nuevo-a", FP_NUEVO_A)
    adaptador.agregar_dispositivo("/dev/nuevo-b", FP_NUEVO_B)
    servicio.ejecutar_ciclo_descubrimiento()
    servicio.coordinador_remapeo.iniciar_captura("id-candidato", "dev01")
    adaptador.simular_evento("/dev/nuevo-a", evento(FP_NUEVO_A))
    adaptador.simular_evento("/dev/nuevo-b", evento(FP_NUEVO_B))

    assert servicio.ejecutar_paso() == []
    estado = servicio.coordinador_remapeo.consultar("id-candidato")
    assert estado["candidato"] == FP_NUEVO_A
    assert cliente.pulsaciones == []
    assert [dato["fingerprint"] for dato in cliente.candidatos] == [FP_NUEVO_A]


def test_elegibilidad_base_mismo_objetivo_y_rechazo_base_ajena(tmp_path: Path) -> None:
    """Permite volver a base propia tras TEMPORAL, pero no robar base de dev02."""

    coordinador, _ = coordinador_preparado(tmp_path)
    congelar_candidato(coordinador, "temporal", "dev01", FP_NUEVO_A)
    coordinador.confirmar("temporal", FP_NUEVO_A, PersistenciaRemapeo.TEMPORAL)

    coordinador.iniciar_captura("volver", "dev01")
    assert coordinador.considerar_candidato(evento(FP_BASE_02)) is None
    candidato = coordinador.considerar_candidato(evento(FP_BASE_01))
    assert candidato is not None
    assert candidato["fingerprint"] == FP_BASE_01


def test_keyup_no_es_candidato_y_cancelar_no_cambia_mapping(tmp_path: Path) -> None:
    """Eventos no-keydown y cancelación conservan exactamente el mapping."""

    coordinador, ruta = coordinador_preparado(tmp_path)
    original = ruta.read_bytes()
    coordinador.iniciar_captura("cancelar", "dev01")
    assert coordinador.considerar_candidato(evento(FP_NUEVO_A, bajada=False)) is None
    assert coordinador.cancelar("cancelar")["estado"] == "CANCELADO"
    assert coordinador.cancelar("cancelar")["estado"] == "CANCELADO"
    assert coordinador.instantanea_mapeo_efectivo() == {
        FP_BASE_01: "dev01",
        FP_BASE_02: "dev02",
    }
    assert ruta.read_bytes() == original


def test_temporal_solo_memoria_y_reinicio_recupera_base(tmp_path: Path) -> None:
    """TEMPORAL vive hasta reiniciar el proceso, no hasta cerrar backend."""

    coordinador, ruta = coordinador_preparado(tmp_path)
    original = ruta.read_bytes()
    congelar_candidato(coordinador, "tmp", "dev01", FP_NUEVO_A)
    coordinador.confirmar("tmp", FP_NUEVO_A, PersistenciaRemapeo.TEMPORAL)
    assert coordinador.resolver_dispositivo(FP_NUEVO_A) == "dev01"
    assert coordinador.resolver_dispositivo(FP_BASE_01) is None
    assert ruta.read_bytes() == original

    recreado = CoordinadorRemapeoBridge(ruta, cargar_dispositivos_json(ruta))
    assert recreado.resolver_dispositivo(FP_BASE_01) == "dev01"
    assert recreado.resolver_dispositivo(FP_NUEVO_A) is None


def test_persistente_reemplaza_solo_objetivo_con_fsync_y_replace(tmp_path: Path) -> None:
    """PERSISTENTE valida/escribe completo y recién entonces instala efectivo."""

    coordinador, ruta = coordinador_preparado(tmp_path)
    congelar_candidato(coordinador, "persistir", "dev01", FP_NUEVO_A)
    fsync_real = os.fsync
    replace_real = os.replace
    llamadas_fsync: list[int] = []
    reemplazos: list[tuple[Path, Path]] = []

    def registrar_fsync(descriptor: int) -> None:
        llamadas_fsync.append(descriptor)
        fsync_real(descriptor)

    def registrar_replace(origen: str | Path, destino: str | Path) -> None:
        reemplazos.append((Path(origen), Path(destino)))
        replace_real(origen, destino)

    with (
        patch("sis_leg_device_bridge.remapeo.os.fsync", side_effect=registrar_fsync),
        patch("sis_leg_device_bridge.remapeo.os.replace", side_effect=registrar_replace),
    ):
        coordinador.confirmar("persistir", FP_NUEVO_A, PersistenciaRemapeo.PERSISTENTE)
        # Repetir confirma idempotencia: no duplica write/fsync/replace.
        coordinador.confirmar("persistir", FP_NUEVO_A, PersistenciaRemapeo.PERSISTENTE)

    assert len(llamadas_fsync) == 1
    assert len(reemplazos) == 1
    assert reemplazos[0][0].parent == ruta.parent
    assert reemplazos[0][1] == ruta
    assert cargar_dispositivos_json(ruta) == {FP_BASE_02: "dev02", FP_NUEVO_A: "dev01"}
    recreado = CoordinadorRemapeoBridge(ruta, cargar_dispositivos_json(ruta))
    assert recreado.resolver_dispositivo(FP_NUEVO_A) == "dev01"


@pytest.mark.parametrize("etapa", ["validacion", "write", "fsync", "replace"])
def test_fallo_persistencia_conserva_archivo_y_efectivo(tmp_path: Path, etapa: str) -> None:
    """Ningún fallo degrada silenciosamente PERSISTENTE a TEMPORAL."""

    coordinador, ruta = coordinador_preparado(tmp_path)
    original = ruta.read_bytes()
    congelar_candidato(coordinador, f"fallo-{etapa}", "dev01", FP_NUEVO_A)
    objetivo = {
        "validacion": "sis_leg_device_bridge.remapeo.validar_mapeo_dispositivos",
        "write": "sis_leg_device_bridge.remapeo.json.dump",
        "fsync": "sis_leg_device_bridge.remapeo.os.fsync",
        "replace": "sis_leg_device_bridge.remapeo.os.replace",
    }[etapa]
    with (
        patch(objetivo, side_effect=OSError(f"fallo {etapa}")),
        pytest.raises(ErrorControlRemapeo) as error,
    ):
        coordinador.confirmar(f"fallo-{etapa}", FP_NUEVO_A, PersistenciaRemapeo.PERSISTENTE)
    assert error.value.codigo == "APLICACION_RECHAZADA"
    assert ruta.read_bytes() == original
    assert coordinador.resolver_dispositivo(FP_BASE_01) == "dev01"
    assert coordinador.resolver_dispositivo(FP_NUEVO_A) is None


def test_api_control_loopback_paths_y_configuracion(tmp_path: Path) -> None:
    """El servidor real usa loopback por default y puerto efímero configurable."""

    coordinador, _ = coordinador_preparado(tmp_path)
    servidor = ServidorControlBridge(coordinador, puerto=0)
    servidor.iniciar()
    host, puerto = servidor.direccion
    assert host == "127.0.0.1"
    assert puerto > 0
    base = f"http://{host}:{puerto}"
    try:
        cuerpo = json.dumps({"remapeo_id": "http-1", "dispositivo": "dev01"}).encode()
        peticion = urllib.request.Request(
            f"{base}/control/v1/remapeos",
            data=cuerpo,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(peticion, timeout=2) as respuesta:
            iniciado = json.loads(respuesta.read())
        assert iniciado["estado"] == "CAPTURANDO"
        with urllib.request.urlopen(f"{base}/control/v1/remapeos/http-1", timeout=2) as respuesta:
            consultado = json.loads(respuesta.read())
        assert consultado == iniciado

        # El candidato proviene del loop físico, no de una ruta administrativa.
        assert coordinador.considerar_candidato(evento(FP_NUEVO_A)) is not None
        confirmar = urllib.request.Request(
            f"{base}/control/v1/remapeos/http-1/confirmacion",
            data=json.dumps({"fingerprint": FP_NUEVO_A, "persistencia": "TEMPORAL"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(confirmar, timeout=2) as respuesta:
            aplicado = json.loads(respuesta.read())
        assert aplicado["estado"] == "APLICADO"
        with urllib.request.urlopen(confirmar, timeout=2) as respuesta:
            assert json.loads(respuesta.read())["estado"] == "APLICADO"

        iniciar_otro = urllib.request.Request(
            f"{base}/control/v1/remapeos",
            data=json.dumps({"remapeo_id": "http-2", "dispositivo": "dev02"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(iniciar_otro, timeout=2).close()
        cancelar = urllib.request.Request(f"{base}/control/v1/remapeos/http-2", method="DELETE")
        with urllib.request.urlopen(cancelar, timeout=2) as respuesta:
            assert json.loads(respuesta.read())["estado"] == "CANCELADO"
    finally:
        servidor.detener()


def test_carrera_de_candidatos_congela_exactamente_uno(tmp_path: Path) -> None:
    """Dos hilos físicos simultáneos no pueden reemplazar el primer ganador."""

    coordinador, _ = coordinador_preparado(tmp_path)
    coordinador.iniciar_captura("carrera", "dev01")
    barrera = threading.Barrier(3)
    resultados: list[dict[str, str] | None] = []

    def competir(fingerprint: str) -> None:
        barrera.wait()
        resultados.append(coordinador.considerar_candidato(evento(fingerprint)))

    hilos = [
        threading.Thread(target=competir, args=(FP_NUEVO_A,)),
        threading.Thread(target=competir, args=(FP_NUEVO_B,)),
    ]
    for hilo in hilos:
        hilo.start()
    barrera.wait()
    for hilo in hilos:
        hilo.join(timeout=2)

    assert sum(resultado is not None for resultado in resultados) == 1
    assert coordinador.consultar("carrera")["candidato"] in (FP_NUEVO_A, FP_NUEVO_B)
