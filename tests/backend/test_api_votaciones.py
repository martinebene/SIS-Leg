"""Pruebas HTTP y OpenAPI de ``POST /api/v1/votaciones`` (WP-009)."""

from __future__ import annotations

import csv
import json
import math
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from conftest import (
    LINEA_LOGS,
    LINEA_QUORUM,
    LINEA_TYPES,
    TOML_CANONICO,
    escribir_padron,
    escribir_system_toml,
    filas_padron_valido,
)
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sis_leg_backend.aplicacion import crear_aplicacion
from sis_leg_backend.auditoria import ErrorAuditoria, NivelAuditoria
from sis_leg_backend.dominio.estado import EstadoGlobal
from sis_leg_backend.dominio.votacion import (
    BaseMayoria,
    EstadoVotacion,
    ResultadoVotacion,
    SentidoVotoDesempate,
    TipoMayoria,
)
from sis_leg_backend.recursos import obtener_recursos_aplicacion
from sis_leg_backend.servicios.votacion import ServicioVotacion

pytestmark = pytest.mark.anyio


def preparar_archivos(directorio: Path, *, quorum: int = 1) -> Path:
    """Escribe configuración/padrón canónicos y devuelve la ruta del TOML."""

    carpeta = directorio / "config"
    carpeta.mkdir(parents=True, exist_ok=True)
    contenido = TOML_CANONICO.replace(
        LINEA_LOGS,
        f'logs_dir = "{directorio / "logs"}"',
    ).replace(LINEA_QUORUM, f"quorum = {quorum}")
    ruta_toml = escribir_system_toml(carpeta / "system.toml", contenido)
    escribir_padron(carpeta / "concejales.csv", filas_padron_valido())
    return ruta_toml


@asynccontextmanager
async def cliente_abierto(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    quorum: int = 1,
) -> AsyncGenerator[tuple[AsyncClient, FastAPI, Path]]:
    """Entrega una aplicación real con sesión abierta y quórum configurado."""

    ruta_toml = preparar_archivos(tmp_path, quorum=quorum)
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()
    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            assert (await cliente.post("/api/v1/preparacion")).status_code == 204
            assert (
                await cliente.patch(
                    "/api/v1/preparacion",
                    json={
                        "numero_sesion": 59,
                        "presidencia": "Presidencia",
                        "secretaria_legislativa": "Secretaría",
                    },
                )
            ).status_code == 204
            if quorum == 1:
                assert (
                    await cliente.post(
                        "/api/v1/entradas/tecla",
                        json={"dispositivo": "D-01", "tecla": "9"},
                    )
                ).status_code == 200
            assert (await cliente.post("/api/v1/sesion")).status_code == (
                204 if quorum == 1 else 409
            )
            yield cliente, aplicacion, ruta_toml


def cuerpo_simple(**cambios: Any) -> dict[str, Any]:
    """Devuelve el body SIMPLE mínimo con cambios puntuales para parametrizar."""

    cuerpo: dict[str, Any] = {
        "numero_votacion": 37,
        "tipo": "Mocion",
        "tema": "Tratamiento del proyecto X",
        "tipo_mayoria": "SIMPLE",
    }
    cuerpo.update(cambios)
    return cuerpo


def cuerpo_especial(**cambios: Any) -> dict[str, Any]:
    """Devuelve un body ESPECIAL válido sobre CUERPO."""

    cuerpo: dict[str, Any] = {
        "numero_votacion": 38,
        "tipo": "Despacho HA",
        "tema": "Tratamiento del proyecto Y",
        "tipo_mayoria": "ESPECIAL",
        "factor": 0.6666666667,
        "base": "CUERPO",
    }
    cuerpo.update(cambios)
    return cuerpo


async def crear_empate_http(cliente: AsyncClient) -> str:
    """Abre una SIMPLE y la empata con una abstención de la única presente."""

    apertura = await cliente.post("/api/v1/votaciones", json=cuerpo_simple())
    assert apertura.status_code == 201
    voto = await cliente.post(
        "/api/v1/entradas/tecla",
        json={"dispositivo": "D-01", "tecla": "2"},
    )
    assert voto.status_code == 200
    return str(apertura.json()["id"])


@pytest.mark.parametrize(
    "campos_adicionales",
    [
        {},
        {"factor": None},
        {"factor": 0},
        {"base": "VOTOS_COMPUTABLES"},
    ],
    ids=["minima-factor-omitido", "factor-null", "factor-cero", "base-explicita"],
)
async def test_simple_valida_y_responde_representacion_normalizada(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    campos_adicionales: dict[str, Any],
) -> None:
    """SIMPLE siempre publica factor cero y base VOTOS_COMPUTABLES."""

    async with cliente_abierto(tmp_path, monkeypatch) as (cliente, aplicacion, _ruta):
        respuesta = await cliente.post(
            "/api/v1/votaciones",
            json=cuerpo_simple(**campos_adicionales),
        )

        assert respuesta.status_code == 201
        cuerpo = respuesta.json()
        assert cuerpo["id"]
        assert cuerpo["numero_votacion"] == 37
        assert cuerpo["tipo"] == "Mocion"
        assert cuerpo["tema"] == "Tratamiento del proyecto X"
        assert cuerpo["tipo_mayoria"] == TipoMayoria.SIMPLE
        assert cuerpo["factor"] == 0
        assert cuerpo["base"] == BaseMayoria.VOTOS_COMPUTABLES
        assert cuerpo["estado"] == EstadoVotacion.EN_CURSO
        datetime.fromisoformat(cuerpo["fecha_hora_apertura"])

        estado = obtener_recursos_aplicacion(aplicacion).estado_operativo
        sesion = estado.sesion_activa
        assert sesion is not None
        assert sesion.votaciones == [estado.votacion_activa]
        assert sesion.votaciones[0] is estado.votacion_activa


@pytest.mark.parametrize(
    "cambios",
    [
        {"factor": 0.1},
        {"factor": ""},
        {"factor": True},
        {"factor": "0"},
        {"factor": -0.1},
        {"base": "PRESENTES"},
        {"base": "CUERPO"},
    ],
    ids=[
        "factor-positivo",
        "factor-vacio",
        "factor-bool",
        "factor-texto",
        "factor-negativo",
        "presentes",
        "cuerpo",
    ],
)
async def test_simple_rechaza_combinaciones_incoherentes_sin_auditar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cambios: dict[str, Any],
) -> None:
    """Los 422 de Pydantic ocurren antes del servicio y no crean evento institucional."""

    async with cliente_abierto(tmp_path, monkeypatch) as (cliente, aplicacion, _ruta):
        cantidad = len(filas_auditoria(aplicacion))
        respuesta = await cliente.post("/api/v1/votaciones", json=cuerpo_simple(**cambios))

        assert respuesta.status_code == 422
        assert len(filas_auditoria(aplicacion)) == cantidad
        assert obtener_recursos_aplicacion(aplicacion).estado_operativo.votacion_activa is None


@pytest.mark.parametrize(
    ("base", "factor"),
    [
        ("VOTOS_COMPUTABLES", 0.5),
        ("PRESENTES", 0.75),
        ("CUERPO", 1),
    ],
)
async def test_especial_acepta_las_tres_bases_y_factor_uno(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    base: str,
    factor: float,
) -> None:
    """ESPECIAL conserva factor finito y cualquiera de las bases canónicas."""

    async with cliente_abierto(tmp_path, monkeypatch) as (cliente, _aplicacion, _ruta):
        respuesta = await cliente.post(
            "/api/v1/votaciones",
            json=cuerpo_especial(base=base, factor=factor),
        )

        assert respuesta.status_code == 201
        assert respuesta.json()["tipo_mayoria"] == "ESPECIAL"
        assert respuesta.json()["factor"] == factor
        assert respuesta.json()["base"] == base


@pytest.mark.parametrize(
    "factor",
    [None, 0, -0.1, 1.0001, True, "0.5"],
    ids=["null", "cero", "negativo", "mayor-uno", "bool", "texto"],
)
async def test_especial_rechaza_factores_invalidos(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    factor: Any,
) -> None:
    """ESPECIAL exige un real estricto dentro de ``0 < factor <= 1``."""

    async with cliente_abierto(tmp_path, monkeypatch) as (cliente, _aplicacion, _ruta):
        respuesta = await cliente.post(
            "/api/v1/votaciones",
            json=cuerpo_especial(factor=factor),
        )
        assert respuesta.status_code == 422


async def test_especial_rechaza_factor_y_base_omitidos(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Los dos campos condicionales son obligatorios para ESPECIAL."""

    async with cliente_abierto(tmp_path, monkeypatch) as (cliente, _aplicacion, _ruta):
        sin_factor = cuerpo_especial()
        sin_factor.pop("factor")
        sin_base = cuerpo_especial()
        sin_base.pop("base")
        assert (await cliente.post("/api/v1/votaciones", json=sin_factor)).status_code == 422
        assert (await cliente.post("/api/v1/votaciones", json=sin_base)).status_code == 422


@pytest.mark.parametrize("representacion", ["NaN", "Infinity", "-Infinity"])
async def test_especial_rechaza_numeros_no_finitos(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    representacion: str,
) -> None:
    """Incluso si el parser JSON admite extensiones no estándar, Pydantic las rechaza."""

    contenido = (
        '{"numero_votacion":38,"tipo":"Despacho HA","tema":"Tema",'
        f'"tipo_mayoria":"ESPECIAL","factor":{representacion},"base":"CUERPO"'
        "}"
    )
    cuerpo_parseado = json.loads(contenido)
    assert not math.isfinite(cuerpo_parseado["factor"])

    async with cliente_abierto(tmp_path, monkeypatch) as (cliente, _aplicacion, _ruta):
        respuesta = await cliente.post(
            "/api/v1/votaciones",
            content=contenido,
            headers={"content-type": "application/json"},
        )
        assert respuesta.status_code == 422
        detalle = respuesta.json()["detail"]
        assert any(
            error["loc"][-1] == "factor" and error["type"] == "float_type" for error in detalle
        )
        assert all(error["type"] != "json_invalid" for error in detalle)


async def test_simple_rechaza_numero_no_finito_con_422_serializable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El saneamiento técnico también conserva el rechazo normal para SIMPLE."""

    contenido = (
        '{"numero_votacion":37,"tipo":"Mocion","tema":"Tema","tipo_mayoria":"SIMPLE","factor":NaN}'
    )
    async with cliente_abierto(tmp_path, monkeypatch) as (cliente, _aplicacion, _ruta):
        respuesta = await cliente.post(
            "/api/v1/votaciones",
            content=contenido,
            headers={"content-type": "application/json"},
        )
        assert respuesta.status_code == 422


@pytest.mark.parametrize(
    "numero",
    [0, -1, True, False, 1.5, "1"],
    ids=["cero", "negativo", "true", "false", "decimal", "texto"],
)
async def test_numero_votacion_es_entero_positivo_estricto(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    numero: Any,
) -> None:
    """No se coercionan booleanos, decimales ni texto a número institucional."""

    async with cliente_abierto(tmp_path, monkeypatch) as (cliente, _aplicacion, _ruta):
        respuesta = await cliente.post(
            "/api/v1/votaciones",
            json=cuerpo_simple(numero_votacion=numero),
        )
        assert respuesta.status_code == 422


@pytest.mark.parametrize(
    "cambios",
    [
        {"tipo": ""},
        {"tipo": "   "},
        {"tema": ""},
        {"tema": "   "},
        {"campo_extra": "no permitido"},
    ],
    ids=["tipo-vacio", "tipo-blanco", "tema-vacio", "tema-blanco", "extra"],
)
async def test_textos_obligatorios_y_campos_extra_devuelven_422(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cambios: dict[str, Any],
) -> None:
    """El body se normaliza con strip y no admite datos fuera del contrato."""

    async with cliente_abierto(tmp_path, monkeypatch) as (cliente, _aplicacion, _ruta):
        respuesta = await cliente.post("/api/v1/votaciones", json=cuerpo_simple(**cambios))
        assert respuesta.status_code == 422


@pytest.mark.parametrize("campo", ["numero_votacion", "tipo", "tema", "tipo_mayoria"])
async def test_campos_principales_omitidos_devuelven_422(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    campo: str,
) -> None:
    """Número, tipo, tema y tipo de mayoría forman parte obligatoria del body."""

    cuerpo = cuerpo_simple()
    cuerpo.pop(campo)
    async with cliente_abierto(tmp_path, monkeypatch) as (cliente, _aplicacion, _ruta):
        assert (await cliente.post("/api/v1/votaciones", json=cuerpo)).status_code == 422


async def test_tipo_se_normaliza_y_valida_contra_snapshot_sin_releer_toml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Espacios exteriores son válidos y cambios en disco no afectan la sesión."""

    async with cliente_abierto(tmp_path, monkeypatch) as (cliente, aplicacion, ruta_toml):
        ruta_toml.write_text(
            TOML_CANONICO.replace(LINEA_TYPES, 'types = ["Tipo Nuevo"]'),
            encoding="utf-8",
        )
        respuesta = await cliente.post(
            "/api/v1/votaciones",
            json=cuerpo_simple(tipo="  Mocion  ", tema="  Tema normalizado  "),
        )
        assert respuesta.status_code == 201
        assert respuesta.json()["tipo"] == "Mocion"
        assert respuesta.json()["tema"] == "Tema normalizado"
        estado = obtener_recursos_aplicacion(aplicacion).estado_operativo
        assert estado.votacion_activa is not None


async def test_tipo_no_permitido_devuelve_error_estable_y_audita_rechazo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un texto técnicamente válido pero ajeno al snapshot es un 422 funcional."""

    async with cliente_abierto(tmp_path, monkeypatch) as (cliente, aplicacion, _ruta):
        respuesta = await cliente.post(
            "/api/v1/votaciones",
            json=cuerpo_simple(tipo="mocion"),
        )
        assert respuesta.status_code == 422
        assert respuesta.json()["codigo"] == "TIPO_VOTACION_NO_PERMITIDO"
        assert filas_auditoria(aplicacion)[-1][2:5] == [
            "L2",
            "VOTACION",
            "COMANDO_VOTACION_RECHAZADO",
        ]


async def test_estados_y_quorum_se_traducen_a_conflictos_estables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La API expone ESTADO_INCOMPATIBLE y QUORUM_INSUFICIENTE sin mutar."""

    preparar_archivos(tmp_path, quorum=2)
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()
    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            sin_preparar = await cliente.post("/api/v1/votaciones", json=cuerpo_simple())
            assert sin_preparar.status_code == 409
            assert sin_preparar.json()["codigo"] == "ESTADO_INCOMPATIBLE"

            await cliente.post("/api/v1/preparacion")
            preparando = await cliente.post("/api/v1/votaciones", json=cuerpo_simple())
            assert preparando.status_code == 409
            assert preparando.json()["codigo"] == "ESTADO_INCOMPATIBLE"
            await cliente.patch(
                "/api/v1/preparacion",
                json={
                    "numero_sesion": 59,
                    "presidencia": "Presidencia",
                    "secretaria_legislativa": "Secretaría",
                },
            )
            await cliente.post(
                "/api/v1/entradas/tecla",
                json={"dispositivo": "D-01", "tecla": "9"},
            )
            assert (await cliente.post("/api/v1/sesion")).status_code == 409
            await cliente.post(
                "/api/v1/entradas/tecla",
                json={"dispositivo": "D-02", "tecla": "9"},
            )
            assert (await cliente.post("/api/v1/sesion")).status_code == 204

            await cliente.post(
                "/api/v1/entradas/tecla",
                json={"dispositivo": "D-02", "tecla": "9"},
            )
            sin_quorum = await cliente.post("/api/v1/votaciones", json=cuerpo_simple())
            assert sin_quorum.status_code == 409
            assert sin_quorum.json()["codigo"] == "QUORUM_INSUFICIENTE"
            await cliente.post(
                "/api/v1/entradas/tecla",
                json={"dispositivo": "D-02", "tecla": "9"},
            )
            assert (
                await cliente.post("/api/v1/votaciones", json=cuerpo_simple())
            ).status_code == 201


async def test_segunda_apertura_guard_cierre_y_ausencia_de_edicion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La votación bloquea otra apertura y DELETE la resuelve antes de cerrar."""

    async with cliente_abierto(tmp_path, monkeypatch) as (cliente, aplicacion, _ruta):
        primera = await cliente.post("/api/v1/votaciones", json=cuerpo_simple())
        estado = obtener_recursos_aplicacion(aplicacion).estado_operativo
        votacion = estado.votacion_activa
        assert votacion is not None
        segunda = await cliente.post("/api/v1/votaciones", json=cuerpo_simple(numero_votacion=99))
        cierre = await cliente.delete("/api/v1/sesion")
        edicion_coleccion = await cliente.patch("/api/v1/votaciones", json={"tema": "Otro"})
        edicion_entidad = await cliente.patch(
            f"/api/v1/votaciones/{primera.json()['id']}",
            json={"tema": "Otro"},
        )

        assert primera.status_code == 201
        assert segunda.status_code == 409
        assert segunda.json()["codigo"] == "VOTACION_PENDIENTE"
        assert cierre.status_code == 200
        assert votacion.resultado is ResultadoVotacion.INCONCLUSA
        assert edicion_coleccion.status_code == 405
        assert edicion_entidad.status_code == 404
        assert estado.estado_global is EstadoGlobal.SIN_PREPARAR
        assert estado.sesion_activa is None


async def test_auditoria_indisponible_devuelve_503_sin_publicar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La API conserva fallo cerrado y no responde 201 ante writer cerrado."""

    async with cliente_abierto(tmp_path, monkeypatch) as (cliente, aplicacion, _ruta):
        estado = obtener_recursos_aplicacion(aplicacion).estado_operativo
        sesion = estado.sesion_activa
        assert sesion is not None
        sesion.contexto_operativo.escritor_auditoria.cerrar()
        respuesta = await cliente.post("/api/v1/votaciones", json=cuerpo_simple())

        assert respuesta.status_code == 503
        assert respuesta.json()["codigo"] == "AUDITORIA_NO_DISPONIBLE"
        assert sesion.votaciones == []
        assert estado.votacion_activa is None


async def test_api_finalizacion_manual_normaliza_preserva_voto_y_responde_204(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El endpoint exacto finaliza la misma instancia sin calcular mayoría."""

    async with cliente_abierto(tmp_path, monkeypatch) as (cliente, aplicacion, _ruta):
        await cliente.post(
            "/api/v1/entradas/tecla",
            json={"dispositivo": "D-02", "tecla": "9"},
        )
        apertura = await cliente.post("/api/v1/votaciones", json=cuerpo_simple())
        id_votacion = apertura.json()["id"]
        voto = await cliente.post(
            "/api/v1/entradas/tecla",
            json={"dispositivo": "D-01", "tecla": "1"},
        )
        assert voto.status_code == 200

        respuesta = await cliente.post(
            f"/api/v1/votaciones/{id_votacion}/finalizacion",
            json={"motivo": "  decisión de Moderación  "},
        )

        assert respuesta.status_code == 204
        assert respuesta.content == b""
        estado = obtener_recursos_aplicacion(aplicacion).estado_operativo
        sesion = estado.sesion_activa
        assert sesion is not None
        votacion = sesion.votaciones[0]
        assert votacion.id == id_votacion
        assert votacion.estado is EstadoVotacion.CERRADA
        assert votacion.resultado is ResultadoVotacion.INCONCLUSA
        assert votacion.motivo_finalizacion_manual == "decisión de Moderación"
        assert set(votacion.votos_ordinarios) == {"30000001"}
        assert estado.votacion_activa is None
        assert filas_auditoria(aplicacion)[-1][4] == "VOTACION_FINALIZADA_INCONCLUSA"


@pytest.mark.parametrize(
    "cuerpo",
    [
        {},
        {"motivo": ""},
        {"motivo": "   "},
        {"motivo": None},
        {"motivo": True},
        {"motivo": 123},
        {"motivo": ["texto"]},
        {"motivo": {"texto": "motivo"}},
        {"motivo": "válido", "extra": "prohibido"},
    ],
    ids=[
        "faltante",
        "vacio",
        "blancos",
        "null",
        "booleano",
        "numero",
        "lista",
        "objeto",
        "campo-extra",
    ],
)
async def test_api_finalizacion_rechaza_body_invalido_antes_del_dominio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cuerpo: dict[str, Any],
) -> None:
    """Todos los cuerpos ajenos al string estricto obligatorio producen 422."""

    async with cliente_abierto(tmp_path, monkeypatch) as (cliente, aplicacion, _ruta):
        apertura = await cliente.post("/api/v1/votaciones", json=cuerpo_simple())
        estado = obtener_recursos_aplicacion(aplicacion).estado_operativo
        votacion = estado.votacion_activa
        assert votacion is not None
        cantidad_eventos = len(filas_auditoria(aplicacion))

        respuesta = await cliente.post(
            f"/api/v1/votaciones/{apertura.json()['id']}/finalizacion",
            json=cuerpo,
        )

        assert respuesta.status_code == 422
        assert votacion.estado is EstadoVotacion.EN_CURSO
        assert votacion.resultado is None
        assert votacion.motivo_finalizacion_manual is None
        assert estado.votacion_activa is votacion
        assert len(filas_auditoria(aplicacion)) == cantidad_eventos


async def test_api_finalizacion_expone_conflictos_estables_y_rechazo_l2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Distingue estado, ausencia, id obsoleto y etapa no finalizable."""

    preparar_archivos(tmp_path / "sin-sesion")
    monkeypatch.chdir(tmp_path / "sin-sesion")
    aplicacion_vacia = crear_aplicacion()
    async with aplicacion_vacia.router.lifespan_context(aplicacion_vacia):
        transporte = ASGITransport(app=aplicacion_vacia)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            respuesta = await cliente.post(
                "/api/v1/votaciones/inexistente/finalizacion",
                json={"motivo": "motivo"},
            )
            assert respuesta.status_code == 409
            assert respuesta.json()["codigo"] == "ESTADO_INCOMPATIBLE"

    async with cliente_abierto(tmp_path / "sesion", monkeypatch) as (
        cliente,
        aplicacion,
        _ruta,
    ):
        sin_activa = await cliente.post(
            "/api/v1/votaciones/inexistente/finalizacion",
            json={"motivo": "motivo"},
        )
        assert sin_activa.status_code == 409
        assert sin_activa.json()["codigo"] == "VOTACION_NO_EN_CURSO"

        apertura = await cliente.post("/api/v1/votaciones", json=cuerpo_simple())
        id_votacion = apertura.json()["id"]
        id_incorrecto = await cliente.post(
            "/api/v1/votaciones/otra-votacion/finalizacion",
            json={"motivo": "motivo"},
        )
        assert id_incorrecto.status_code == 409
        assert id_incorrecto.json()["codigo"] == "VOTACION_NO_COINCIDE"
        fila = filas_auditoria(aplicacion)[-1]
        assert fila[2:5] == ["L2", "VOTACION", "COMANDO_VOTACION_RECHAZADO"]
        assert "id_solicitado=otra-votacion" in fila[5]

        estado = obtener_recursos_aplicacion(aplicacion).estado_operativo
        votacion = estado.votacion_activa
        assert votacion is not None
        votacion.cerrar_recepcion(datetime(2026, 8, 22, 12, 0, 0))
        cerrada_tecnica = await cliente.post(
            f"/api/v1/votaciones/{id_votacion}/finalizacion",
            json={"motivo": "motivo"},
        )
        assert cerrada_tecnica.status_code == 409
        assert cerrada_tecnica.json()["codigo"] == "VOTACION_NO_EN_CURSO"
        assert votacion.resultado is None


async def test_api_finalizacion_no_convierte_empate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EMPATADA queda reservada para cierre de sesión, no para POST manual."""

    async with cliente_abierto(tmp_path, monkeypatch) as (cliente, aplicacion, _ruta):
        await cliente.post(
            "/api/v1/entradas/tecla",
            json={"dispositivo": "D-02", "tecla": "9"},
        )
        apertura = await cliente.post("/api/v1/votaciones", json=cuerpo_simple())
        await cliente.post(
            "/api/v1/entradas/tecla",
            json={"dispositivo": "D-01", "tecla": "1"},
        )
        await cliente.post(
            "/api/v1/entradas/tecla",
            json={"dispositivo": "D-02", "tecla": "3"},
        )
        estado = obtener_recursos_aplicacion(aplicacion).estado_operativo
        votacion = estado.votacion_activa
        assert votacion is not None
        assert votacion.resultado is ResultadoVotacion.EMPATADA

        respuesta = await cliente.post(
            f"/api/v1/votaciones/{apertura.json()['id']}/finalizacion",
            json={"motivo": "motivo"},
        )

        assert respuesta.status_code == 409
        assert respuesta.json()["codigo"] == "VOTACION_NO_EN_CURSO"
        assert votacion.resultado is ResultadoVotacion.EMPATADA
        assert estado.votacion_activa is votacion


async def test_api_fallo_auditoria_finalizacion_devuelve_503_sin_mutar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La frontera L3 fallida conserva fecha, motivo, votos y referencia."""

    async with cliente_abierto(tmp_path, monkeypatch) as (cliente, aplicacion, _ruta):
        apertura = await cliente.post("/api/v1/votaciones", json=cuerpo_simple())
        estado = obtener_recursos_aplicacion(aplicacion).estado_operativo
        votacion = estado.votacion_activa
        sesion = estado.sesion_activa
        assert votacion is not None
        assert sesion is not None
        escritor = sesion.contexto_operativo.escritor_auditoria
        registrar_original = escritor.registrar_evento

        def fallar_finalizacion(
            nivel: NivelAuditoria,
            etiqueta: str,
            codigo_evento: str,
            mensaje: str,
        ) -> int:
            if codigo_evento == "VOTACION_FINALIZADA_INCONCLUSA":
                monkeypatch.setattr(escritor, "_fallado", True)
                raise ErrorAuditoria("fallo simulado")
            return registrar_original(nivel, etiqueta, codigo_evento, mensaje)

        monkeypatch.setattr(escritor, "registrar_evento", fallar_finalizacion)
        respuesta = await cliente.post(
            f"/api/v1/votaciones/{apertura.json()['id']}/finalizacion",
            json={"motivo": "motivo"},
        )

        assert respuesta.status_code == 503
        assert respuesta.json()["codigo"] == "AUDITORIA_NO_DISPONIBLE"
        assert votacion.estado is EstadoVotacion.EN_CURSO
        assert votacion.resultado is None
        assert votacion.fecha_hora_cierre is None
        assert votacion.motivo_finalizacion_manual is None
        assert estado.votacion_activa is votacion
        assert escritor.fallado is True


async def test_api_fallo_auditoria_de_rechazo_prevalece_sobre_409(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un rechazo no se presenta como normal si su evento L2 no es durable."""

    async with cliente_abierto(tmp_path, monkeypatch) as (cliente, aplicacion, _ruta):
        await cliente.post("/api/v1/votaciones", json=cuerpo_simple())
        estado = obtener_recursos_aplicacion(aplicacion).estado_operativo
        votacion = estado.votacion_activa
        sesion = estado.sesion_activa
        assert votacion is not None
        assert sesion is not None
        escritor = sesion.contexto_operativo.escritor_auditoria
        escritor.cerrar()

        respuesta = await cliente.post(
            "/api/v1/votaciones/id-obsoleto/finalizacion",
            json={"motivo": "motivo"},
        )

        assert respuesta.status_code == 503
        assert respuesta.json()["codigo"] == "AUDITORIA_NO_DISPONIBLE"
        assert votacion.estado is EstadoVotacion.EN_CURSO
        assert votacion.resultado is None
        assert votacion.fecha_hora_cierre is None
        assert estado.votacion_activa is votacion


@pytest.mark.parametrize(
    ("sentido", "resultado"),
    [
        ("POSITIVO", ResultadoVotacion.APROBADA),
        ("NEGATIVO", ResultadoVotacion.RECHAZADA),
    ],
)
async def test_api_desempate_responde_204_y_aplica_resultado(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sentido: str,
    resultado: ResultadoVotacion,
) -> None:
    """El endpoint exacto completa ambos sentidos sin devolver contenido."""

    async with cliente_abierto(tmp_path, monkeypatch) as (cliente, aplicacion, _ruta):
        id_votacion = await crear_empate_http(cliente)
        estado = obtener_recursos_aplicacion(aplicacion).estado_operativo
        votacion = estado.votacion_activa
        assert votacion is not None
        fecha_antes = votacion.fecha_hora_cierre
        votos_antes = dict(votacion.votos_ordinarios)

        respuesta = await cliente.post(
            f"/api/v1/votaciones/{id_votacion}/desempate",
            json={"sentido": sentido},
        )

        assert respuesta.status_code == 204
        assert respuesta.content == b""
        assert votacion.resultado is resultado
        assert votacion.voto_desempate is not None
        assert votacion.voto_desempate.sentido.value == sentido
        assert votacion.voto_desempate.presidencia == "Presidencia"
        assert votacion.fecha_hora_cierre == fecha_antes
        assert dict(votacion.votos_ordinarios) == votos_antes
        assert estado.votacion_activa is None


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"sentido": "ABSTENCION"},
        {"sentido": None},
        {"sentido": True},
        {"sentido": 1},
        {"sentido": ["POSITIVO"]},
        {"sentido": {"valor": "POSITIVO"}},
        {"sentido": "OTRO"},
        {},
        {"sentido": "POSITIVO", "extra": "prohibido"},
        {"sentido": "POSITIVO", "presidencia": "Inyectada"},
    ],
    ids=[
        "abstencion",
        "null",
        "booleano",
        "numero",
        "lista",
        "objeto",
        "string-arbitrario",
        "omitido",
        "extra",
        "presidencia-inyectada",
    ],
)
async def test_api_desempate_rechaza_body_estricto_antes_del_servicio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cuerpo: dict[str, Any],
) -> None:
    """Todo valor ajeno a los dos literales exactos produce 422 sin auditar."""

    async with cliente_abierto(tmp_path, monkeypatch) as (cliente, aplicacion, _ruta):
        id_votacion = await crear_empate_http(cliente)
        estado = obtener_recursos_aplicacion(aplicacion).estado_operativo
        votacion = estado.votacion_activa
        assert votacion is not None
        cantidad_eventos = len(filas_auditoria(aplicacion))

        respuesta = await cliente.post(
            f"/api/v1/votaciones/{id_votacion}/desempate",
            json=cuerpo,
        )

        assert respuesta.status_code == 422
        assert votacion.resultado is ResultadoVotacion.EMPATADA
        assert votacion.voto_desempate is None
        assert estado.votacion_activa is votacion
        assert len(filas_auditoria(aplicacion)) == cantidad_eventos


async def test_api_desempate_expone_conflictos_estables_y_auditables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Distingue estado, ausencia, id, etapa y voto presidencial previo."""

    preparar_archivos(tmp_path / "sin-sesion")
    monkeypatch.chdir(tmp_path / "sin-sesion")
    aplicacion_vacia = crear_aplicacion()
    async with aplicacion_vacia.router.lifespan_context(aplicacion_vacia):
        transporte = ASGITransport(app=aplicacion_vacia)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            respuesta = await cliente.post(
                "/api/v1/votaciones/inexistente/desempate",
                json={"sentido": "POSITIVO"},
            )
            assert respuesta.status_code == 409
            assert respuesta.json()["codigo"] == "ESTADO_INCOMPATIBLE"

    async with cliente_abierto(tmp_path / "sesion", monkeypatch) as (
        cliente,
        aplicacion,
        _ruta,
    ):
        sin_activa = await cliente.post(
            "/api/v1/votaciones/inexistente/desempate",
            json={"sentido": "POSITIVO"},
        )
        assert sin_activa.status_code == 409
        assert sin_activa.json()["codigo"] == "VOTACION_NO_EMPATADA"

        apertura = await cliente.post("/api/v1/votaciones", json=cuerpo_simple())
        id_votacion = str(apertura.json()["id"])
        no_empatada = await cliente.post(
            f"/api/v1/votaciones/{id_votacion}/desempate",
            json={"sentido": "POSITIVO"},
        )
        assert no_empatada.status_code == 409
        assert no_empatada.json()["codigo"] == "VOTACION_NO_EMPATADA"

        await cliente.post(
            "/api/v1/entradas/tecla",
            json={"dispositivo": "D-01", "tecla": "2"},
        )
        id_incorrecto = await cliente.post(
            "/api/v1/votaciones/otra-votacion/desempate",
            json={"sentido": "NEGATIVO"},
        )
        assert id_incorrecto.status_code == 409
        assert id_incorrecto.json()["codigo"] == "VOTACION_NO_COINCIDE"
        assert "id_solicitado=otra-votacion" in filas_auditoria(aplicacion)[-1][5]

        estado = obtener_recursos_aplicacion(aplicacion).estado_operativo
        votacion = estado.votacion_activa
        assert votacion is not None
        voto = votacion.preparar_voto_desempate(
            SentidoVotoDesempate.POSITIVO,
            "Presidencia",
        )
        votacion.registrar_voto_desempate(voto)
        repetido = await cliente.post(
            f"/api/v1/votaciones/{id_votacion}/desempate",
            json={"sentido": "NEGATIVO"},
        )
        assert repetido.status_code == 409
        assert repetido.json()["codigo"] == "DESEMPATE_YA_EMITIDO"
        assert votacion.resultado is ResultadoVotacion.EMPATADA
        assert votacion.voto_desempate is voto


@pytest.mark.parametrize(
    "codigo_fallado",
    ["VOTO_DESEMPATE_PRESIDENCIAL", "VOTACION_RESULTADO_DESEMPATE"],
)
async def test_api_desempate_mapea_fallo_cerrado_a_503(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    codigo_fallado: str,
) -> None:
    """Ambas fronteras de auditoría conservan el último hecho durable."""

    async with cliente_abierto(tmp_path, monkeypatch) as (cliente, aplicacion, _ruta):
        id_votacion = await crear_empate_http(cliente)
        estado = obtener_recursos_aplicacion(aplicacion).estado_operativo
        votacion = estado.votacion_activa
        sesion = estado.sesion_activa
        assert votacion is not None
        assert sesion is not None
        escritor = sesion.contexto_operativo.escritor_auditoria
        registrar_original = escritor.registrar_evento

        def fallar_evento(
            nivel: NivelAuditoria,
            etiqueta: str,
            codigo_evento: str,
            mensaje: str,
        ) -> int:
            if codigo_evento == codigo_fallado:
                monkeypatch.setattr(escritor, "_fallado", True)
                raise ErrorAuditoria("fallo simulado de desempate")
            return registrar_original(nivel, etiqueta, codigo_evento, mensaje)

        monkeypatch.setattr(escritor, "registrar_evento", fallar_evento)
        respuesta = await cliente.post(
            f"/api/v1/votaciones/{id_votacion}/desempate",
            json={"sentido": "POSITIVO"},
        )

        assert respuesta.status_code == 503
        assert respuesta.json()["codigo"] == "AUDITORIA_NO_DISPONIBLE"
        assert votacion.resultado is ResultadoVotacion.EMPATADA
        assert estado.votacion_activa is votacion
        assert escritor.fallado is True
        if codigo_fallado == "VOTO_DESEMPATE_PRESIDENCIAL":
            assert votacion.voto_desempate is None
        else:
            assert votacion.voto_desempate is not None
            assert votacion.voto_desempate.sentido is SentidoVotoDesempate.POSITIVO


async def test_api_desempate_fallo_al_auditar_rechazo_prevalece_sobre_409(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un id obsoleto no se informa como conflicto saludable con writer fallado."""

    async with cliente_abierto(tmp_path, monkeypatch) as (cliente, aplicacion, _ruta):
        await crear_empate_http(cliente)
        estado = obtener_recursos_aplicacion(aplicacion).estado_operativo
        votacion = estado.votacion_activa
        sesion = estado.sesion_activa
        assert votacion is not None
        assert sesion is not None
        sesion.contexto_operativo.escritor_auditoria.cerrar()

        respuesta = await cliente.post(
            "/api/v1/votaciones/id-obsoleto/desempate",
            json={"sentido": "POSITIVO"},
        )

        assert respuesta.status_code == 503
        assert respuesta.json()["codigo"] == "AUDITORIA_NO_DISPONIBLE"
        assert votacion.resultado is ResultadoVotacion.EMPATADA
        assert votacion.voto_desempate is None
        assert estado.votacion_activa is votacion


async def test_api_desempate_fallo_inesperado_devuelve_error_interno(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Una excepción no clasificada conserva el mapeo transversal a 500."""

    async with cliente_abierto(tmp_path, monkeypatch) as (cliente, aplicacion, _ruta):
        id_votacion = await crear_empate_http(cliente)

        async def fallar_desempate(
            _servicio: ServicioVotacion,
            _id_votacion: str,
            _sentido: SentidoVotoDesempate,
        ) -> None:
            raise RuntimeError("detalle privado inesperado")

        monkeypatch.setattr(ServicioVotacion, "desempatar_votacion", fallar_desempate)
        transporte = ASGITransport(app=aplicacion, raise_app_exceptions=False)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente_error:
            respuesta = await cliente_error.post(
                f"/api/v1/votaciones/{id_votacion}/desempate",
                json={"sentido": "POSITIVO"},
            )

        assert respuesta.status_code == 500
        assert respuesta.json() == {
            "codigo": "ERROR_INTERNO",
            "mensaje": "Ocurrió un error interno.",
        }


def filas_auditoria(aplicacion: FastAPI) -> list[list[str]]:
    """Lee el CSV L1 del contexto activo para comprobar efectos institucionales."""

    estado = obtener_recursos_aplicacion(aplicacion).estado_operativo
    contexto = estado.contexto_operativo_activo()
    assert contexto is not None
    ruta = contexto.escritor_auditoria.rutas[NivelAuditoria.L1]
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.reader(archivo, delimiter=";"))


def test_openapi_expone_union_discriminada_respuesta_y_errores() -> None:
    """El contrato canónico publica POST plural, enums, 201 y errores aplicables."""

    especificacion = crear_aplicacion().openapi()
    ruta = especificacion["paths"]["/api/v1/votaciones"]
    assert set(ruta) == {"post"}
    operacion = ruta["post"]
    assert set(("201", "409", "422", "503", "500")) <= set(operacion["responses"])
    esquema_body = operacion["requestBody"]["content"]["application/json"]["schema"]
    assert len(esquema_body["oneOf"]) == 2
    assert esquema_body["discriminator"]["propertyName"] == "tipo_mayoria"
    assert set(esquema_body["discriminator"]["mapping"]) == {"SIMPLE", "ESPECIAL"}

    esquemas = especificacion["components"]["schemas"]
    respuesta = esquemas["RespuestaVotacion"]
    assert set(respuesta["properties"]) == {
        "id",
        "numero_votacion",
        "tipo",
        "tema",
        "tipo_mayoria",
        "factor",
        "base",
        "estado",
        "fecha_hora_apertura",
    }
    assert set(esquemas["BaseMayoria"]["enum"]) == {
        "VOTOS_COMPUTABLES",
        "PRESENTES",
        "CUERPO",
    }
    assert set(esquemas["TipoMayoria"]["enum"]) == {"SIMPLE", "ESPECIAL"}
    ruta_finalizacion = especificacion["paths"]["/api/v1/votaciones/{id}/finalizacion"]
    assert set(ruta_finalizacion) == {"post"}
    operacion_finalizacion = ruta_finalizacion["post"]
    assert set(("204", "409", "422", "503", "500")) <= set(operacion_finalizacion["responses"])
    esquema_finalizacion = esquemas["SolicitudFinalizarVotacion"]
    assert esquema_finalizacion["required"] == ["motivo"]
    assert esquema_finalizacion["additionalProperties"] is False
    assert esquema_finalizacion["properties"]["motivo"]["type"] == "string"
    ruta_desempate = especificacion["paths"]["/api/v1/votaciones/{id}/desempate"]
    assert set(ruta_desempate) == {"post"}
    operacion_desempate = ruta_desempate["post"]
    assert set(("204", "409", "422", "503", "500")) <= set(operacion_desempate["responses"])
    esquema_desempate = esquemas["SolicitudDesempate"]
    assert esquema_desempate["required"] == ["sentido"]
    assert esquema_desempate["additionalProperties"] is False
    assert esquema_desempate["properties"]["sentido"]["enum"] == ["POSITIVO", "NEGATIVO"]
    assert set(esquema_desempate["properties"]) == {"sentido"}
    assert "/api/v1/votaciones/{id}" not in especificacion["paths"]
