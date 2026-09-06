"""Integración FastAPI del remapeo coordinado y sus invariantes institucionales."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import (
    LINEA_LOGS,
    TOML_CANONICO,
    escribir_padron,
    escribir_system_toml,
    filas_padron_valido,
)
from httpx import ASGITransport, AsyncClient
from sis_leg_backend.aplicacion import crear_aplicacion
from sis_leg_backend.recursos import obtener_recursos_aplicacion
from sis_leg_backend.servicios.cliente_bridge import (
    ErrorRespuestaBridge,
    ErrorTransporteBridge,
    EstadoControlBridge,
)

pytestmark = pytest.mark.anyio

FP_ANTERIOR = "lin|vendor=1001|product=2001|version=0001|phys=usb-1|uniq=|name=Anterior"
FP_CANDIDATO = "lin|vendor=9001|product=9001|version=0001|phys=usb-9|uniq=|name=Candidato"


def test_openapi_documenta_endpoints_publicos_e_interno() -> None:
    """El snapshot derivable contiene los cuatro paths y modelos cerrados."""

    esquema = crear_aplicacion().openapi()
    paths = esquema["paths"]
    assert "/api/v1/remapeos" in paths
    assert "/api/v1/remapeos/{remapeo_id}/confirmacion" in paths
    assert "/api/v1/remapeos/{remapeo_id}" in paths
    assert "/api/v1/interno/remapeos/{remapeo_id}/candidato" in paths
    esquemas = esquema["components"]["schemas"]
    assert esquemas["SolicitudIniciarRemapeo"]["additionalProperties"] is False
    assert esquemas["SolicitudConfirmarRemapeo"]["additionalProperties"] is False
    assert esquemas["SolicitudCandidatoRemapeo"]["additionalProperties"] is False
    capacidades = esquemas["CapacidadesModeracion"]
    propiedades_capacidades = capacidades["properties"]
    for nombre in ("iniciar_remapeo", "confirmar_remapeo", "cancelar_remapeo"):
        assert nombre in propiedades_capacidades
        assert nombre in capacidades["required"]
    propiedades_recinto = esquemas["EstadoRecinto"]["properties"]
    assert "remapeo" not in propiedades_recinto
    assert "fingerprint" not in str(esquemas["EstadoRecinto"]).lower()


class BridgeFalso:
    """Autoridad física programable para probar orden e idempotencia sin red."""

    def __init__(self) -> None:
        self.estados: dict[str, EstadoControlBridge] = {}
        self.inicios: list[tuple[str, str]] = []
        self.confirmaciones: list[tuple[str, str, str]] = []
        self.cancelaciones: list[str] = []
        self.al_confirmar: Callable[[], None] | None = None
        self.fallar_inicio = False
        self.perder_respuesta_inicio = False
        self.perder_respuesta_apply = False
        self.perder_respuesta_cancelacion = False
        self.rechazar_apply = False

    def iniciar(self, remapeo_id: str, dispositivo: str) -> EstadoControlBridge:
        if self.fallar_inicio:
            raise ErrorTransporteBridge("bridge apagado")
        self.inicios.append((remapeo_id, dispositivo))
        estado = self._estado(remapeo_id, dispositivo, "CAPTURANDO")
        self.estados[remapeo_id] = estado
        if self.perder_respuesta_inicio:
            raise ErrorTransporteBridge("respuesta perdida después del inicio")
        return estado

    def consultar(self, remapeo_id: str) -> EstadoControlBridge:
        return self.estados[remapeo_id]

    def confirmar(
        self, remapeo_id: str, fingerprint: str, persistencia: str
    ) -> EstadoControlBridge:
        self.confirmaciones.append((remapeo_id, fingerprint, persistencia))
        if self.al_confirmar is not None:
            self.al_confirmar()
        if self.rechazar_apply:
            raise ErrorRespuestaBridge("APLICACION_RECHAZADA", "fallo físico")
        estado = self._estado(
            remapeo_id,
            self.estados[remapeo_id].dispositivo,
            "APLICADO",
            candidato=fingerprint,
            persistencia=persistencia,
        )
        self.estados[remapeo_id] = estado
        if self.perder_respuesta_apply:
            raise ErrorTransporteBridge("respuesta perdida después del apply")
        return estado

    def cancelar(self, remapeo_id: str) -> EstadoControlBridge:
        self.cancelaciones.append(remapeo_id)
        anterior = self.estados[remapeo_id]
        estado = self._estado(remapeo_id, anterior.dispositivo, "CANCELADO")
        self.estados[remapeo_id] = estado
        if self.perder_respuesta_cancelacion:
            raise ErrorTransporteBridge("respuesta perdida después de cancelar")
        return estado

    @staticmethod
    def _estado(
        remapeo_id: str,
        dispositivo: str,
        estado: str,
        *,
        candidato: str | None = None,
        persistencia: str | None = None,
    ) -> EstadoControlBridge:
        return EstadoControlBridge(
            remapeo_id=remapeo_id,
            dispositivo=dispositivo,
            estado=estado,
            fingerprint_anterior=FP_ANTERIOR,
            candidato=candidato,
            diagnostico="Teclado de prueba" if candidato else None,
            persistencia=persistencia,
            error=None,
        )


def preparar_archivos(tmp_path: Path) -> None:
    """Instala configuración/padrón ficticio con dispositivos devXX."""

    carpeta = tmp_path / "config"
    carpeta.mkdir()
    escribir_system_toml(
        carpeta / "system.toml",
        TOML_CANONICO.replace(LINEA_LOGS, f'logs_dir = "{tmp_path}/logs"'),
    )
    filas = filas_padron_valido()
    for numero, fila in enumerate(filas, start=1):
        fila[5] = f"dev{numero:02d}"
    escribir_padron(carpeta / "concejales.csv", filas)


async def preparar(cliente: AsyncClient) -> None:
    """Inicia PREPARANDO con el padrón devXX ya instalado."""

    assert (await cliente.post("/api/v1/preparacion")).status_code == 204


async def iniciar_y_capturar(cliente: AsyncClient, dispositivo: str = "dev05") -> str:
    """Recorre inicio y callback hasta CANDIDATO."""

    inicio = await cliente.post("/api/v1/remapeos", json={"dispositivo": dispositivo})
    assert inicio.status_code == 201
    remapeo_id = inicio.json()["remapeo_id"]
    candidato = await cliente.post(
        f"/api/v1/interno/remapeos/{remapeo_id}/candidato",
        json={"fingerprint": FP_CANDIDATO, "diagnostico": "Teclado sustituto"},
    )
    assert candidato.status_code == 200
    return remapeo_id


async def test_sin_preparar_y_bodies_estrictos_rechazados(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Estado, devXX, extras y enum producen códigos/esquemas estables."""

    aplicacion = crear_aplicacion()
    async with aplicacion.router.lifespan_context(aplicacion):
        bridge = BridgeFalso()
        recursos = obtener_recursos_aplicacion(aplicacion)
        monkeypatch.setattr(recursos.cliente_control_bridge, "iniciar", bridge.iniciar)
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            respuesta = await cliente.post("/api/v1/remapeos", json={"dispositivo": "dev05"})
            assert respuesta.status_code == 409
            assert respuesta.json()["codigo"] == "ESTADO_INCOMPATIBLE"
            assert (
                await cliente.post(
                    "/api/v1/remapeos",
                    json={"dispositivo": "dev05", "extra": True},
                )
            ).status_code == 422
            assert (
                await cliente.post(
                    "/api/v1/remapeos/id/confirmacion",
                    json={"persistencia": "TEMPORAL", "extra": True},
                )
            ).status_code == 422
            assert (
                await cliente.post(
                    "/api/v1/interno/remapeos/id/candidato",
                    json={"fingerprint": FP_CANDIDATO, "extra": True},
                )
            ).status_code == 422
            for valor in ("PERMANENTE", 1, True, None):
                invalida = await cliente.post(
                    "/api/v1/remapeos/id/confirmacion",
                    json={"persistencia": valor},
                )
                assert invalida.status_code == 422


async def test_preparando_inicia_uuid_unico_valida_padron_y_operacion_global(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PREPARANDO acepta devXX congelado y bloquea uno simultáneo."""

    preparar_archivos(tmp_path)
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()
    async with aplicacion.router.lifespan_context(aplicacion):
        bridge = BridgeFalso()
        recursos = obtener_recursos_aplicacion(aplicacion)
        monkeypatch.setattr(recursos.cliente_control_bridge, "iniciar", bridge.iniciar)
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            await preparar(cliente)
            inexistente = await cliente.post("/api/v1/remapeos", json={"dispositivo": "dev99"})
            assert inexistente.status_code == 409
            assert inexistente.json()["codigo"] == "DISPOSITIVO_REMAPEO_NO_EXISTENTE"
            primera = await cliente.post("/api/v1/remapeos", json={"dispositivo": "dev05"})
            assert primera.status_code == 201
            remapeo_id = primera.json()["remapeo_id"]
            assert len(remapeo_id) == 36
            assert bridge.inicios == [(remapeo_id, "dev05")]
            segunda = await cliente.post("/api/v1/remapeos", json={"dispositivo": "dev06"})
            assert segunda.status_code == 409
            assert segunda.json()["codigo"] == "REMAPEO_YA_ACTIVO"


async def test_inicio_y_cancelacion_con_respuesta_perdida_reconcilian_mismo_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Los comandos de control inciertos consultan el ID sin crear otra operación."""

    preparar_archivos(tmp_path)
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()
    async with aplicacion.router.lifespan_context(aplicacion):
        bridge = BridgeFalso()
        bridge.perder_respuesta_inicio = True
        bridge.perder_respuesta_cancelacion = True
        recursos = obtener_recursos_aplicacion(aplicacion)
        cliente_bridge = recursos.cliente_control_bridge
        monkeypatch.setattr(cliente_bridge, "iniciar", bridge.iniciar)
        monkeypatch.setattr(cliente_bridge, "consultar", bridge.consultar)
        monkeypatch.setattr(cliente_bridge, "cancelar", bridge.cancelar)
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            await preparar(cliente)
            inicio = await cliente.post("/api/v1/remapeos", json={"dispositivo": "dev05"})
            assert inicio.status_code == 201
            remapeo_id = inicio.json()["remapeo_id"]
            assert bridge.inicios == [(remapeo_id, "dev05")]

            cancelacion = await cliente.delete(f"/api/v1/remapeos/{remapeo_id}")
            assert cancelacion.status_code == 204
            assert bridge.cancelaciones == [remapeo_id]
            assert (await cliente.get("/api/v1/estado/moderacion")).json()["remapeo"] is None


async def test_callback_congela_primero_publica_revision_y_recinto_no_filtra(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Solo Moderación/SSE reciben candidato; Recinto no contiene datos físicos."""

    preparar_archivos(tmp_path)
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()
    async with aplicacion.router.lifespan_context(aplicacion):
        bridge = BridgeFalso()
        recursos = obtener_recursos_aplicacion(aplicacion)
        monkeypatch.setattr(recursos.cliente_control_bridge, "iniciar", bridge.iniciar)
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            await preparar(cliente)
            inicio = await cliente.post("/api/v1/remapeos", json={"dispositivo": "dev05"})
            remapeo_id = inicio.json()["remapeo_id"]
            revision_inicio = (await cliente.get("/api/v1/estado/moderacion")).json()["revision"]
            incorrecto = await cliente.post(
                "/api/v1/interno/remapeos/otro/candidato",
                json={"fingerprint": FP_CANDIDATO},
            )
            assert incorrecto.status_code == 409
            assert incorrecto.json()["codigo"] == "REMAPEO_NO_COINCIDE"
            primero = await cliente.post(
                f"/api/v1/interno/remapeos/{remapeo_id}/candidato",
                json={"fingerprint": FP_CANDIDATO, "diagnostico": "Seguro"},
            )
            assert primero.status_code == 200
            posterior = await cliente.post(
                f"/api/v1/interno/remapeos/{remapeo_id}/candidato",
                json={"fingerprint": FP_CANDIDATO + "-otro", "diagnostico": "Otro"},
            )
            assert posterior.status_code == 409
            assert posterior.json()["codigo"] == "CANDIDATO_YA_REGISTRADO"
            moderacion = (await cliente.get("/api/v1/estado/moderacion")).json()
            recinto = await cliente.get("/api/v1/estado/recinto")
            assert moderacion["revision"] > revision_inicio
            assert moderacion["remapeo"]["candidato"] == FP_CANDIDATO
            assert "remapeo" not in recinto.json()
            assert FP_CANDIDATO not in recinto.text
            assert "fingerprint" not in recinto.text.lower()


async def test_confirmacion_sin_candidato_y_cancelacion_limpia(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No aplica sin candidato; DELETE termina sin tocar otros estados."""

    preparar_archivos(tmp_path)
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()
    async with aplicacion.router.lifespan_context(aplicacion):
        bridge = BridgeFalso()
        recursos = obtener_recursos_aplicacion(aplicacion)
        monkeypatch.setattr(recursos.cliente_control_bridge, "iniciar", bridge.iniciar)
        monkeypatch.setattr(recursos.cliente_control_bridge, "cancelar", bridge.cancelar)
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            await preparar(cliente)
            inicio = await cliente.post("/api/v1/remapeos", json={"dispositivo": "dev05"})
            remapeo_id = inicio.json()["remapeo_id"]
            confirmar = await cliente.post(
                f"/api/v1/remapeos/{remapeo_id}/confirmacion",
                json={"persistencia": "TEMPORAL"},
            )
            assert confirmar.status_code == 409
            assert confirmar.json()["codigo"] == "REMAPEO_SIN_CANDIDATO"
            assert bridge.confirmaciones == []
            assert (await cliente.delete(f"/api/v1/remapeos/{remapeo_id}")).status_code == 204
            assert (await cliente.delete(f"/api/v1/remapeos/{remapeo_id}")).status_code == 204
            assert (await cliente.get("/api/v1/estado/moderacion")).json()["remapeo"] is None


async def test_auditoria_antes_de_apply_y_respuesta_perdida_reconcilia_sin_doble_aplicacion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El query posterior al timeout observa APLICADO y no reenvía confirmación."""

    preparar_archivos(tmp_path)
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()
    async with aplicacion.router.lifespan_context(aplicacion):
        bridge = BridgeFalso()
        bridge.perder_respuesta_apply = True
        recursos = obtener_recursos_aplicacion(aplicacion)
        cliente_bridge = recursos.cliente_control_bridge
        monkeypatch.setattr(cliente_bridge, "iniciar", bridge.iniciar)
        monkeypatch.setattr(cliente_bridge, "confirmar", bridge.confirmar)
        monkeypatch.setattr(cliente_bridge, "cancelar", bridge.cancelar)
        monkeypatch.setattr(cliente_bridge, "consultar", bridge.consultar)
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            await preparar(cliente)
            remapeo_id = await iniciar_y_capturar(cliente)
            contexto = recursos.estado_operativo.contexto_operativo_activo()
            assert contexto is not None

            def comprobar_orden() -> None:
                assert contexto.escritor_auditoria.eventos_recientes[-1].codigo_evento == (
                    "REMAPEO_AUTORIZADO"
                )

            bridge.al_confirmar = comprobar_orden
            confirmacion = await cliente.post(
                f"/api/v1/remapeos/{remapeo_id}/confirmacion",
                json={"persistencia": "PERSISTENTE"},
            )
            assert confirmacion.status_code == 204
            assert len(bridge.confirmaciones) == 1
            # Repetir el comando público compatible usa el resultado final memorizado.
            repetida = await cliente.post(
                f"/api/v1/remapeos/{remapeo_id}/confirmacion",
                json={"persistencia": "PERSISTENTE"},
            )
            assert repetida.status_code == 204
            assert len(bridge.confirmaciones) == 1
            eventos = [
                evento.codigo_evento for evento in contexto.escritor_auditoria.eventos_recientes
            ]
            assert eventos.count("REMAPEO_AUTORIZADO") == 1
            mensaje = contexto.escritor_auditoria.eventos_recientes[-1].mensaje
            assert remapeo_id in mensaje
            assert "dispositivo=dev05" in mensaje
            assert f"fingerprint_anterior={FP_ANTERIOR}" in mensaje
            assert f"fingerprint_candidato={FP_CANDIDATO}" in mensaje
            assert "persistencia=PERSISTENTE" in mensaje


async def test_rechazo_explicito_de_apply_tiene_codigo_estable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un fallo físico/persistente no se confunde con indisponibilidad de red."""

    preparar_archivos(tmp_path)
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()
    async with aplicacion.router.lifespan_context(aplicacion):
        bridge = BridgeFalso()
        bridge.rechazar_apply = True
        recursos = obtener_recursos_aplicacion(aplicacion)
        monkeypatch.setattr(recursos.cliente_control_bridge, "iniciar", bridge.iniciar)
        monkeypatch.setattr(recursos.cliente_control_bridge, "confirmar", bridge.confirmar)
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            await preparar(cliente)
            remapeo_id = await iniciar_y_capturar(cliente)
            respuesta = await cliente.post(
                f"/api/v1/remapeos/{remapeo_id}/confirmacion",
                json={"persistencia": "PERSISTENTE"},
            )
            assert respuesta.status_code == 503
            assert respuesta.json()["codigo"] == "APLICACION_BRIDGE_RECHAZADA"


async def test_auditoria_fallida_impide_apply_y_bridge_inaccesible_se_distingue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fallo cerrado devuelve 503 antes del bridge; inicio inaccesible tiene otro código."""

    preparar_archivos(tmp_path)
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()
    async with aplicacion.router.lifespan_context(aplicacion):
        bridge = BridgeFalso()
        recursos = obtener_recursos_aplicacion(aplicacion)
        cliente_bridge = recursos.cliente_control_bridge
        monkeypatch.setattr(cliente_bridge, "iniciar", bridge.iniciar)
        monkeypatch.setattr(cliente_bridge, "confirmar", bridge.confirmar)
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            await preparar(cliente)
            remapeo_id = await iniciar_y_capturar(cliente)
            contexto = recursos.estado_operativo.contexto_operativo_activo()
            assert contexto is not None
            contexto.escritor_auditoria.cerrar()
            fallida = await cliente.post(
                f"/api/v1/remapeos/{remapeo_id}/confirmacion",
                json={"persistencia": "TEMPORAL"},
            )
            assert fallida.status_code == 503
            assert fallida.json()["codigo"] == "AUDITORIA_NO_DISPONIBLE"
            assert bridge.confirmaciones == []

    # Una aplicación nueva permite demostrar el código técnico independiente.
    aplicacion = crear_aplicacion()
    async with aplicacion.router.lifespan_context(aplicacion):
        bridge = BridgeFalso()
        bridge.fallar_inicio = True
        recursos = obtener_recursos_aplicacion(aplicacion)
        monkeypatch.setattr(recursos.cliente_control_bridge, "iniciar", bridge.iniciar)
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            await preparar(cliente)
            inaccesible = await cliente.post("/api/v1/remapeos", json={"dispositivo": "dev05"})
            assert inaccesible.status_code == 503
            assert inaccesible.json()["codigo"] == "BRIDGE_NO_DISPONIBLE"


async def test_sesion_con_votacion_remapea_sin_alterar_presencia_voto_palabra(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CA-005/020/023/024/048/060 permanecen invariantes durante apply."""

    preparar_archivos(tmp_path)
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()
    async with aplicacion.router.lifespan_context(aplicacion):
        bridge = BridgeFalso()
        recursos = obtener_recursos_aplicacion(aplicacion)
        cliente_bridge = recursos.cliente_control_bridge
        monkeypatch.setattr(cliente_bridge, "iniciar", bridge.iniciar)
        monkeypatch.setattr(cliente_bridge, "confirmar", bridge.confirmar)
        monkeypatch.setattr(cliente_bridge, "cancelar", bridge.cancelar)
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            await preparar(cliente)
            for numero in range(1, 8):
                assert (
                    await cliente.post(
                        "/api/v1/entradas/tecla",
                        json={"dispositivo": f"dev{numero:02d}", "tecla": "9"},
                    )
                ).status_code == 200
            await cliente.patch(
                "/api/v1/preparacion",
                json={
                    "numero_sesion": 20,
                    "presidencia": "Presidencia ficticia",
                    "secretaria_legislativa": "Secretaría ficticia",
                },
            )
            assert (await cliente.post("/api/v1/sesion")).status_code == 204

            # SESION_ABIERTA sin votación también admite la coordinación.
            remapeo_sin_votacion = await iniciar_y_capturar(cliente, "dev06")
            assert (
                await cliente.delete(f"/api/v1/remapeos/{remapeo_sin_votacion}")
            ).status_code == 204

            assert (
                await cliente.post(
                    "/api/v1/entradas/tecla",
                    json={"dispositivo": "dev02", "tecla": "7"},
                )
            ).status_code == 200
            apertura = await cliente.post(
                "/api/v1/votaciones",
                json={
                    "numero_votacion": 1,
                    "tipo": "Otro",
                    "tema": "Tema concurrente",
                    "tipo_mayoria": "SIMPLE",
                    "factor": 0,
                    "base": "VOTOS_COMPUTABLES",
                },
            )
            assert apertura.status_code == 201
            assert (
                await cliente.post(
                    "/api/v1/entradas/tecla",
                    json={"dispositivo": "dev01", "tecla": "1"},
                )
            ).status_code == 200
            antes = (await cliente.get("/api/v1/estado/moderacion")).json()

            remapeo_id = await iniciar_y_capturar(cliente, "dev05")
            confirmar = await cliente.post(
                f"/api/v1/remapeos/{remapeo_id}/confirmacion",
                json={"persistencia": "TEMPORAL"},
            )
            assert confirmar.status_code == 204
            despues = (await cliente.get("/api/v1/estado/moderacion")).json()

            assert despues["estado_global"] == "SESION_ABIERTA"
            assert [dato["presente"] for dato in despues["concejales"]] == [
                dato["presente"] for dato in antes["concejales"]
            ]
            assert despues["votacion"]["id"] == antes["votacion"]["id"]
            assert despues["votacion"]["cantidad_votos_recibidos"] == 1
            assert despues["palabra"] == antes["palabra"]
            assert despues["remapeo"] is None
