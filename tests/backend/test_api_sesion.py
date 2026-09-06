"""Pruebas HTTP del ciclo institucional y autoridades de WP-008.

Los escenarios atraviesan FastAPI y Pydantic reales. Además de los códigos
HTTP, inspeccionan el estado y el CSV activo para demostrar que la validación
de transporte sucede antes de la auditoría y que el servicio conserva el
orden institucional AUDITAR -> MUTAR.
"""

from __future__ import annotations

import csv
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
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
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sis_leg_backend.aplicacion import crear_aplicacion
from sis_leg_backend.auditoria import NivelAuditoria
from sis_leg_backend.dominio.estado import EstadoGlobal
from sis_leg_backend.dominio.votacion import BaseMayoria, TipoMayoria, Votacion
from sis_leg_backend.recursos import obtener_recursos_aplicacion

pytestmark = pytest.mark.anyio


def preparar_archivos_canonicos(directorio: Path, *, quorum: int = 1) -> None:
    """Crea configuración y padrón ficticios para una aplicación aislada."""

    carpeta = directorio / "config"
    carpeta.mkdir(parents=True, exist_ok=True)
    contenido = TOML_CANONICO.replace(
        LINEA_LOGS,
        f'logs_dir = "{directorio / "logs"}"',
    ).replace(LINEA_QUORUM, f"quorum = {quorum}")
    escribir_system_toml(carpeta / "system.toml", contenido)
    escribir_padron(carpeta / "concejales.csv", filas_padron_valido())


@asynccontextmanager
async def cliente_de_prueba(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    quorum: int = 1,
) -> AsyncGenerator[tuple[AsyncClient, FastAPI]]:
    """Entrega cliente y aplicación con lifespan y archivos canónicos reales."""

    preparar_archivos_canonicos(tmp_path, quorum=quorum)
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()
    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(
            transport=transporte,
            base_url="http://pruebas",
        ) as cliente:
            yield cliente, aplicacion


async def preparar_y_abrir(cliente: AsyncClient) -> None:
    """Completa las precondiciones mínimas y abre una sesión válida."""

    assert (await cliente.post("/api/v1/preparacion")).status_code == 204
    assert (
        await cliente.post(
            "/api/v1/entradas/tecla",
            json={"dispositivo": "D-01", "tecla": "9"},
        )
    ).status_code == 200
    assert (
        await cliente.patch(
            "/api/v1/preparacion",
            json={
                "numero_sesion": 59,
                "presidencia": "Presidencia Inicial",
                "secretaria_legislativa": "Secretaría Inicial",
            },
        )
    ).status_code == 204
    respuesta = await cliente.post("/api/v1/sesion")
    assert respuesta.status_code == 204
    assert respuesta.content == b""


def filas_auditoria(aplicacion: FastAPI) -> list[list[str]]:
    """Lee L1, que contiene todos los eventos institucionales del contexto."""

    estado = obtener_recursos_aplicacion(aplicacion).estado_operativo
    contexto = estado.contexto_operativo_activo()
    assert contexto is not None
    ruta = contexto.escritor_auditoria.rutas[NivelAuditoria.L1]
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.reader(archivo, delimiter=";"))


async def test_patch_preparacion_admite_campos_individuales_multiples_y_limpieza(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Normaliza autoridades, evita eventos no-op y respeta el orden aprobado."""

    async with cliente_de_prueba(tmp_path, monkeypatch) as (cliente, aplicacion):
        assert (await cliente.post("/api/v1/preparacion")).status_code == 204
        assert (
            await cliente.patch("/api/v1/preparacion", json={"numero_sesion": 59})
        ).status_code == 204
        cantidad_tras_numero = len(filas_auditoria(aplicacion))
        assert (
            await cliente.patch("/api/v1/preparacion", json={"numero_sesion": 59})
        ).status_code == 204
        assert len(filas_auditoria(aplicacion)) == cantidad_tras_numero

        assert (
            await cliente.patch(
                "/api/v1/preparacion",
                json={"presidencia": "  Presidencia Uno  "},
            )
        ).status_code == 204
        assert (
            await cliente.patch(
                "/api/v1/preparacion",
                json={"secretaria_legislativa": "  Secretaría Uno  "},
            )
        ).status_code == 204
        assert (
            await cliente.patch(
                "/api/v1/preparacion",
                json={
                    "secretaria_legislativa": "Secretaría Dos",
                    "presidencia": "Presidencia Dos",
                    "numero_sesion": 7,
                },
            )
        ).status_code == 204
        codigos = [fila[4] for fila in filas_auditoria(aplicacion)]
        assert codigos[-3:] == [
            "NUMERO_SESION_ACTUALIZADO",
            "PRESIDENCIA_ACTUALIZADA",
            "SECRETARIA_LEGISLATIVA_ACTUALIZADA",
        ]

        assert (
            await cliente.patch(
                "/api/v1/preparacion",
                json={"presidencia": "   ", "secretaria_legislativa": ""},
            )
        ).status_code == 204
        preparacion = obtener_recursos_aplicacion(aplicacion).estado_operativo.preparacion_activa
        assert preparacion is not None
        assert preparacion.numero_sesion == 7
        assert preparacion.presidencia is None
        assert preparacion.secretaria_legislativa is None


@pytest.mark.parametrize("numero", [1, 2, 59, 10_000])
async def test_numero_positivo_estricto_es_valido(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    numero: int,
) -> None:
    """No se imponen secuencia, unicidad ni límite superior arbitrario."""

    async with cliente_de_prueba(tmp_path, monkeypatch) as (cliente, aplicacion):
        await cliente.post("/api/v1/preparacion")
        respuesta = await cliente.patch(
            "/api/v1/preparacion",
            json={"numero_sesion": numero},
        )
        assert respuesta.status_code == 204
        preparacion = obtener_recursos_aplicacion(aplicacion).estado_operativo.preparacion_activa
        assert preparacion is not None
        assert preparacion.numero_sesion == numero


@pytest.mark.parametrize(
    "numero",
    [0, -1, True, False, 1.0, "1", None],
    ids=["cero", "negativo", "true", "false", "float", "string", "null"],
)
async def test_numero_no_entero_positivo_devuelve_422_sin_evento(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    numero: Any,
) -> None:
    """Pydantic no coerciona bool, decimal, string ni valores fuera de rango."""

    async with cliente_de_prueba(tmp_path, monkeypatch) as (cliente, aplicacion):
        await cliente.post("/api/v1/preparacion")
        cantidad_inicial = len(filas_auditoria(aplicacion))
        respuesta = await cliente.patch(
            "/api/v1/preparacion",
            json={"numero_sesion": numero},
        )
        assert respuesta.status_code == 422
        assert len(filas_auditoria(aplicacion)) == cantidad_inicial


@pytest.mark.parametrize(
    "cuerpo",
    [{}, {"campo_extra": "x"}, {"presidencia": None}],
    ids=["sin-campos", "campo-extra", "null"],
)
async def test_patch_preparacion_invalido_devuelve_422(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cuerpo: dict[str, Any],
) -> None:
    """Un body inválido se rechaza antes de entrar al dominio."""

    async with cliente_de_prueba(tmp_path, monkeypatch) as (cliente, aplicacion):
        await cliente.post("/api/v1/preparacion")
        cantidad_inicial = len(filas_auditoria(aplicacion))
        respuesta = await cliente.patch("/api/v1/preparacion", json=cuerpo)
        assert respuesta.status_code == 422
        assert len(filas_auditoria(aplicacion)) == cantidad_inicial


async def test_apertura_evalua_precondiciones_en_orden_y_abre(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cada falta devuelve su código estable antes de considerar la siguiente."""

    async with cliente_de_prueba(tmp_path, monkeypatch) as (cliente, aplicacion):
        respuesta = await cliente.post("/api/v1/sesion")
        assert respuesta.status_code == 409
        assert respuesta.json()["codigo"] == "ESTADO_INCOMPATIBLE"

        await cliente.post("/api/v1/preparacion")
        respuesta = await cliente.post("/api/v1/sesion")
        assert respuesta.json()["codigo"] == "QUORUM_INSUFICIENTE"
        await cliente.post(
            "/api/v1/entradas/tecla",
            json={"dispositivo": "D-01", "tecla": "9"},
        )
        respuesta = await cliente.post("/api/v1/sesion")
        assert respuesta.json()["codigo"] == "NUMERO_SESION_REQUERIDO"

        await cliente.patch("/api/v1/preparacion", json={"numero_sesion": 59})
        respuesta = await cliente.post("/api/v1/sesion")
        assert respuesta.json()["codigo"] == "PRESIDENCIA_REQUERIDA"
        await cliente.patch(
            "/api/v1/preparacion",
            json={"presidencia": "Presidencia"},
        )
        respuesta = await cliente.post("/api/v1/sesion")
        assert respuesta.json()["codigo"] == "SECRETARIA_LEGISLATIVA_REQUERIDA"
        await cliente.patch(
            "/api/v1/preparacion",
            json={"secretaria_legislativa": "Secretaría"},
        )
        respuesta = await cliente.post("/api/v1/sesion")
        assert respuesta.status_code == 204
        assert respuesta.content == b""

        estado = obtener_recursos_aplicacion(aplicacion).estado_operativo
        assert estado.estado_global is EstadoGlobal.SESION_ABIERTA
        assert estado.preparacion_activa is None
        assert estado.sesion_activa is not None
        assert filas_auditoria(aplicacion)[-1][4] == "SESION_ABIERTA"
        assert "59" in filas_auditoria(aplicacion)[-1][5]
        repetida = await cliente.post("/api/v1/sesion")
        assert repetida.status_code == 409
        assert repetida.json()["codigo"] == "ESTADO_INCOMPATIBLE"


async def test_patch_sesion_actualiza_autoridades_y_numero_es_inmutable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Las autoridades cambian con strip, pero el número no integra el modelo."""

    async with cliente_de_prueba(tmp_path, monkeypatch) as (cliente, aplicacion):
        await preparar_y_abrir(cliente)
        assert (
            await cliente.patch(
                "/api/v1/sesion",
                json={"presidencia": "  Presidencia Nueva  "},
            )
        ).status_code == 204
        assert (
            await cliente.patch(
                "/api/v1/sesion",
                json={"secretaria_legislativa": "  Secretaría Nueva  "},
            )
        ).status_code == 204

        sesion = obtener_recursos_aplicacion(aplicacion).estado_operativo.sesion_activa
        assert sesion is not None
        assert sesion.numero_sesion == 59
        assert sesion.presidencia == "Presidencia Nueva"
        assert sesion.secretaria_legislativa == "Secretaría Nueva"
        cantidad = len(filas_auditoria(aplicacion))
        no_op = await cliente.patch(
            "/api/v1/sesion",
            json={
                "presidencia": "Presidencia Nueva",
                "secretaria_legislativa": "Secretaría Nueva",
            },
        )
        assert no_op.status_code == 204
        assert len(filas_auditoria(aplicacion)) == cantidad

        for cuerpo in (
            {},
            {"presidencia": "   "},
            {"secretaria_legislativa": ""},
            {"presidencia": None},
            {"numero_sesion": 60},
        ):
            respuesta = await cliente.patch("/api/v1/sesion", json=cuerpo)
            assert respuesta.status_code == 422
        assert sesion.numero_sesion == 59


async def test_entradas_y_quorum_continuan_durante_sesion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Las teclas 8/9 siguen activas y perder quórum no cierra la sesión."""

    async with cliente_de_prueba(tmp_path, monkeypatch) as (cliente, aplicacion):
        await preparar_y_abrir(cliente)
        retiro = await cliente.post(
            "/api/v1/entradas/tecla",
            json={"dispositivo": "D-01", "tecla": "9"},
        )
        assert retiro.json()["motivo"] == "PRESENCIA_ACTUALIZADA"
        assert retiro.json()["resultado"]["quorum_alcanzado"] is False
        estado = obtener_recursos_aplicacion(aplicacion).estado_operativo
        assert estado.estado_global is EstadoGlobal.SESION_ABIERTA

        recuperacion = await cliente.post(
            "/api/v1/entradas/tecla",
            json={"dispositivo": "D-01", "tecla": "9"},
        )
        assert recuperacion.json()["resultado"]["quorum_alcanzado"] is True
        prueba = await cliente.post(
            "/api/v1/entradas/tecla",
            json={"dispositivo": "D-02", "tecla": "8"},
        )
        assert prueba.json()["motivo"] == "TEST_ACTIVADO"
        for tecla in ("1", "2", "3"):
            rechazo = await cliente.post(
                "/api/v1/entradas/tecla",
                json={"dispositivo": "D-01", "tecla": tecla},
            )
            assert rechazo.json()["motivo"] == "VOTACION_NO_EN_CURSO"
        palabra = await cliente.post(
            "/api/v1/entradas/tecla",
            json={"dispositivo": "D-01", "tecla": "7"},
        )
        assert palabra.json()["motivo"] == "PEDIDO_PALABRA_REGISTRADO"
        assert palabra.json()["resultado"] == {
            "tipo": "PALABRA",
            "accion": "PEDIDO_AGREGADO",
        }
        desconocido = await cliente.post(
            "/api/v1/entradas/tecla",
            json={"dispositivo": "NO-ASIGNADO", "tecla": "9"},
        )
        assert desconocido.json()["motivo"] == "DISPOSITIVO_NO_ASIGNADO"
        assert estado.estado_global is EstadoGlobal.SESION_ABIERTA


async def test_cierre_normal_limpia_contexto_y_conserva_csv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DELETE audita/cierra y recién después vuelve completamente al inicio."""

    async with cliente_de_prueba(tmp_path, monkeypatch) as (cliente, aplicacion):
        await preparar_y_abrir(cliente)
        estado = obtener_recursos_aplicacion(aplicacion).estado_operativo
        sesion = estado.sesion_activa
        assert sesion is not None
        ruta_l1 = sesion.contexto_operativo.escritor_auditoria.rutas[NivelAuditoria.L1]
        respuesta = await cliente.delete("/api/v1/sesion")
        assert respuesta.status_code == 204
        assert respuesta.content == b""
        assert estado.estado_global is EstadoGlobal.SIN_PREPARAR
        assert estado.preparacion_activa is None
        assert estado.sesion_activa is None
        assert estado.votacion_activa is None
        assert estado.archivos_auditoria_activos == ()
        with ruta_l1.open(encoding="utf-8-sig", newline="") as archivo:
            filas = list(csv.reader(archivo, delimiter=";"))
        assert filas[-1][4] == "SESION_CERRADA"
        assert "59" in filas[-1][5]

        repetido = await cliente.delete("/api/v1/sesion")
        assert repetido.status_code == 409
        assert repetido.json()["codigo"] == "ESTADO_INCOMPATIBLE"


async def test_votacion_cerrada_sin_resultado_devuelve_409_sin_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El guard conserva el caso técnico CERRADA + None fuera de WP-013."""

    async with cliente_de_prueba(tmp_path, monkeypatch) as (cliente, aplicacion):
        await preparar_y_abrir(cliente)
        estado = obtener_recursos_aplicacion(aplicacion).estado_operativo
        sesion = estado.sesion_activa
        assert sesion is not None
        marcador = Votacion(
            id="votacion-pendiente",
            numero_votacion=37,
            tipo="Mocion",
            tema="Tema pendiente",
            tipo_mayoria=TipoMayoria.SIMPLE,
            factor=0.0,
            base=BaseMayoria.VOTOS_COMPUTABLES,
            fecha_hora_apertura=sesion.fecha_hora_apertura,
        )
        marcador.cerrar_recepcion(sesion.fecha_hora_apertura)
        estado.votacion_activa = marcador
        respuesta = await cliente.delete("/api/v1/sesion")
        assert respuesta.status_code == 409
        assert respuesta.json()["codigo"] == "VOTACION_PENDIENTE"
        assert estado.estado_global is EstadoGlobal.SESION_ABIERTA
        assert estado.sesion_activa is sesion
        assert estado.votacion_activa is marcador


async def test_auditoria_indisponible_devuelve_503_sin_mutar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El manejador compartido expone el fallo cerrado con código estable."""

    async with cliente_de_prueba(tmp_path, monkeypatch) as (cliente, aplicacion):
        await preparar_y_abrir(cliente)
        sesion = obtener_recursos_aplicacion(aplicacion).estado_operativo.sesion_activa
        assert sesion is not None
        sesion.contexto_operativo.escritor_auditoria.cerrar()
        respuesta = await cliente.patch(
            "/api/v1/sesion",
            json={"presidencia": "No debe aplicarse"},
        )
        assert respuesta.status_code == 503
        assert respuesta.json()["codigo"] == "AUDITORIA_NO_DISPONIBLE"
        assert sesion.presidencia == "Presidencia Inicial"


async def test_openapi_expone_los_cuatro_contratos_de_wp008() -> None:
    """Métodos, bodies y respuestas quedan publicados con tipos estrictos."""

    especificacion = crear_aplicacion().openapi()
    preparacion = especificacion["paths"]["/api/v1/preparacion"]["patch"]
    sesion = especificacion["paths"]["/api/v1/sesion"]
    for operacion in (preparacion, sesion["post"], sesion["patch"], sesion["delete"]):
        for codigo in ("204", "409", "422", "503", "500"):
            assert codigo in operacion["responses"]

    assert "requestBody" not in sesion["post"]
    assert "requestBody" not in sesion["delete"]
    esquemas = especificacion["components"]["schemas"]
    esquema_preparacion = esquemas["SolicitudActualizarPreparacion"]
    esquema_sesion = esquemas["SolicitudActualizarSesion"]
    propiedad_numero = esquema_preparacion["properties"]["numero_sesion"]
    referencia_numero = propiedad_numero["$ref"].rsplit("/", maxsplit=1)[-1]
    esquema_numero = esquemas[referencia_numero]
    assert esquema_numero["type"] == "integer"
    assert esquema_numero["minimum"] == 1
    assert "anyOf" not in propiedad_numero
    assert "numero_sesion" not in esquema_sesion["properties"]
