"""Contrato HTTP y OpenAPI de los comandos de palabra de Moderación (WP-015)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from conftest import (
    LINEA_LOGS,
    LINEA_QUORUM,
    TOML_CANONICO,
    escribir_padron,
    escribir_system_toml,
    filas_padron_valido,
)
from httpx import ASGITransport, AsyncClient
from sis_leg_backend.aplicacion import crear_aplicacion
from sis_leg_backend.recursos import obtener_recursos_aplicacion
from sis_leg_backend.servicios.palabra import ServicioPalabra

pytestmark = pytest.mark.anyio


def preparar_archivos_canonicos(directorio: Path, *, quorum: int = 1) -> None:
    """Crea configuración y padrón ficticios para la aplicación real."""

    carpeta = directorio / "config"
    carpeta.mkdir(parents=True, exist_ok=True)
    escribir_system_toml(
        carpeta / "system.toml",
        TOML_CANONICO.replace(
            LINEA_LOGS,
            f'logs_dir = "{directorio / "logs"}"',
        ).replace(LINEA_QUORUM, f"quorum = {quorum}"),
    )
    escribir_padron(carpeta / "concejales.csv", filas_padron_valido())


async def abrir_sesion(cliente: AsyncClient, *, presentes: int = 3) -> None:
    """Prepara, acredita y abre mediante los contratos HTTP públicos."""

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
    for numero in range(1, presentes + 1):
        respuesta = await cliente.post(
            "/api/v1/entradas/tecla",
            json={"dispositivo": f"D-{numero:02d}", "tecla": "9"},
        )
        assert respuesta.status_code == 200
        assert respuesta.json()["aceptada"] is True
    assert (await cliente.post("/api/v1/sesion")).status_code == 204


async def pedir(cliente: AsyncClient, dispositivo: str) -> dict[str, object]:
    """Envía tecla 7 y devuelve su JSON luego de afirmar HTTP 200."""

    respuesta = await cliente.post(
        "/api/v1/entradas/tecla",
        json={"dispositivo": dispositivo, "tecla": "7"},
    )
    assert respuesta.status_code == 200
    cuerpo: dict[str, object] = respuesta.json()
    return cuerpo


async def test_api_entrada_expone_variante_palabra_y_motivos_exactos(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El bridge recibe alta, retiro y finalización propia con forma estable."""

    preparar_archivos_canonicos(tmp_path)
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()

    async with (
        aplicacion.router.lifespan_context(aplicacion),
        AsyncClient(
            transport=ASGITransport(app=aplicacion),
            base_url="http://pruebas",
        ) as cliente,
    ):
        await abrir_sesion(cliente)
        alta = await pedir(cliente, "D-01")
        retiro = await pedir(cliente, "D-01")
        await pedir(cliente, "D-01")
        assert (await cliente.post("/api/v1/palabra")).status_code == 204
        finalizacion = await pedir(cliente, "D-01")

    assert alta["motivo"] == "PEDIDO_PALABRA_REGISTRADO"
    assert alta["resultado"] == {"tipo": "PALABRA", "accion": "PEDIDO_AGREGADO"}
    assert retiro["motivo"] == "PEDIDO_PALABRA_RETIRADO"
    assert retiro["resultado"] == {"tipo": "PALABRA", "accion": "PEDIDO_RETIRADO"}
    assert finalizacion["motivo"] == "USO_PALABRA_FINALIZADO"
    assert finalizacion["resultado"] == {"tipo": "PALABRA", "accion": "USO_FINALIZADO"}


async def test_post_y_delete_aplican_fifo_y_no_avance_con_204(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Los endpoints sin body implementan exactamente avance deliberado y finalización."""

    preparar_archivos_canonicos(tmp_path)
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()

    async with aplicacion.router.lifespan_context(aplicacion):
        async with AsyncClient(
            transport=ASGITransport(app=aplicacion),
            base_url="http://pruebas",
        ) as cliente:
            await abrir_sesion(cliente)
            for dispositivo in ("D-01", "D-02", "D-03"):
                await pedir(cliente, dispositivo)

            primer_otorgamiento = await cliente.post("/api/v1/palabra")
            reemplazo = await cliente.post("/api/v1/palabra")
            quitar = await cliente.delete("/api/v1/palabra")

        sesion = obtener_recursos_aplicacion(aplicacion).estado_operativo.sesion_activa
        assert sesion is not None
        assert sesion.palabra.orador_dni is None
        assert sesion.palabra.cola_dnis == ("30000003",)

    for respuesta in (primer_otorgamiento, reemplazo, quitar):
        assert respuesta.status_code == 204
        assert respuesta.content == b""


async def test_noops_post_y_delete_responden_204(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin pedidos u orador no aparecen errores SIN_ORADOR/SIN_PEDIDOS."""

    preparar_archivos_canonicos(tmp_path)
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()

    async with (
        aplicacion.router.lifespan_context(aplicacion),
        AsyncClient(
            transport=ASGITransport(app=aplicacion),
            base_url="http://pruebas",
        ) as cliente,
    ):
        await abrir_sesion(cliente)
        otorgar = await cliente.post("/api/v1/palabra")
        quitar = await cliente.delete("/api/v1/palabra")

    assert otorgar.status_code == 204
    assert quitar.status_code == 204


@pytest.mark.parametrize("metodo", ["post", "delete"])
async def test_comando_sin_sesion_devuelve_409_estado_incompatible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    metodo: str,
) -> None:
    """Ambos verbos comparten el error funcional exacto aprobado."""

    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()

    async with (
        aplicacion.router.lifespan_context(aplicacion),
        AsyncClient(
            transport=ASGITransport(app=aplicacion),
            base_url="http://pruebas",
        ) as cliente,
    ):
        respuesta = await cliente.request(metodo.upper(), "/api/v1/palabra")

    assert respuesta.status_code == 409
    assert respuesta.json()["codigo"] == "ESTADO_INCOMPATIBLE"


@pytest.mark.parametrize("metodo", ["post", "delete"])
async def test_auditoria_no_disponible_devuelve_503_incluso_en_noop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    metodo: str,
) -> None:
    """El diagnóstico obligatorio de un no-op tampoco puede simular éxito."""

    preparar_archivos_canonicos(tmp_path)
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()

    async with (
        aplicacion.router.lifespan_context(aplicacion),
        AsyncClient(
            transport=ASGITransport(app=aplicacion),
            base_url="http://pruebas",
        ) as cliente,
    ):
        await abrir_sesion(cliente)
        estado = obtener_recursos_aplicacion(aplicacion).estado_operativo
        contexto = estado.contexto_operativo_activo()
        assert contexto is not None
        contexto.escritor_auditoria.cerrar()

        respuesta = await cliente.request(metodo.upper(), "/api/v1/palabra")

    assert respuesta.status_code == 503
    assert respuesta.json()["codigo"] == "AUDITORIA_NO_DISPONIBLE"


@pytest.mark.parametrize(
    ("metodo_http", "metodo_servicio"),
    [("POST", "otorgar_palabra"), ("DELETE", "quitar_palabra")],
)
async def test_fallo_inesperado_devuelve_500_generico(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    metodo_http: str,
    metodo_servicio: str,
) -> None:
    """La API no filtra detalles internos de ninguna operación de Moderación."""

    async def fallar(_servicio: ServicioPalabra) -> None:
        raise RuntimeError("detalle interno de palabra")

    monkeypatch.setattr(ServicioPalabra, metodo_servicio, fallar)
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()

    async with (
        aplicacion.router.lifespan_context(aplicacion),
        AsyncClient(
            transport=ASGITransport(app=aplicacion, raise_app_exceptions=False),
            base_url="http://pruebas",
        ) as cliente,
    ):
        respuesta = await cliente.request(metodo_http, "/api/v1/palabra")

    assert respuesta.status_code == 500
    assert respuesta.json() == {
        "codigo": "ERROR_INTERNO",
        "mensaje": "Ocurrió un error interno.",
    }
    assert "detalle interno" not in respuesta.text


def test_openapi_expone_endpoints_sin_body_y_respuestas_exactas() -> None:
    """OpenAPI publica POST/DELETE, 204/409/503/500 y ninguna solicitud JSON."""

    especificacion = crear_aplicacion().openapi()
    operaciones: list[dict[str, Any]] = [
        especificacion["paths"]["/api/v1/palabra"]["post"],
        especificacion["paths"]["/api/v1/palabra"]["delete"],
    ]

    for operacion in operaciones:
        assert "requestBody" not in operacion
        respuestas = cast(dict[str, Any], operacion["responses"])
        assert set(respuestas) == {"204", "409", "503", "500"}

    esquema_entrada = especificacion["components"]["schemas"]["RespuestaTecla"]
    referencias = {
        variante["$ref"].rsplit("/", 1)[1]
        for variante in esquema_entrada["properties"]["resultado"]["anyOf"]
        if "$ref" in variante
    }
    assert "ResultadoPalabraRespuesta" in referencias
