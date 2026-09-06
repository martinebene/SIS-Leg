"""Pruebas de los contratos HTTP y OpenAPI para Orden del Día (WP-016).

Verifica:
- POST /api/v1/orden-del-dia con multipart/form-data válido (200 OK con DTO normalizado).
- Rechazo de archivo faltante o campo con nombre incorrecto (422 FastAPI).
- Rechazo de archivo técnicamente inválido (422 ORDEN_DEL_DIA_INVALIDO).
- Rechazo de caracteres Unicode no-ASCII en nro_votacion (422 ORDEN_DEL_DIA_INVALIDO).
- Rechazo del formato histórico de 5 columnas (422 ORDEN_DEL_DIA_INVALIDO).
- Intento de carga o descarte en SIN_PREPARAR (409 ESTADO_INCOMPATIBLE).
- DELETE /api/v1/orden-del-dia efectivo y no-op (204 No Content).
- Fallo de auditoría durante carga o descarte (503 AUDITORIA_NO_DISPONIBLE).
- Fallo inesperado no controlado durante carga o descarte (500 ERROR_INTERNO).
- Esquema OpenAPI canónico (existencia de POST multipart y DELETE, ausencia de GET).
"""

from __future__ import annotations

import csv
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
import sis_leg_backend.servicios.orden_del_dia as modulo_servicio_od
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
from sis_leg_backend.recursos import obtener_recursos_aplicacion

pytestmark = pytest.mark.anyio

CSV_VALIDO = (
    b"nro_votacion,tipo,tema,tipo_mayoria,factor,base\n"
    b"1,Despacho,Tema 1,SIMPLE,0,VOTOS_COMPUTABLES\n"
    b"2,Mocion,Tema 2,ESPECIAL,0.6666666667,PRESENTES\n"
)

# WP-053: dos filas comparten el número 1 para demostrar que la ayuda visual se
# apoya sólo en ``nro_votacion`` y marca todas las coincidencias a la vez.
CSV_CON_NUMERO_REPETIDO = (
    b"nro_votacion,tipo,tema,tipo_mayoria,factor,base\n"
    b"1,Despacho OP,Primera lectura,SIMPLE,0,VOTOS_COMPUTABLES\n"
    b"2,Mocion,Otro asunto,SIMPLE,0,VOTOS_COMPUTABLES\n"
    b"1,Otro,Segunda lectura,SIMPLE,0,VOTOS_COMPUTABLES\n"
)

CSV_HISTORICO_CINCO_COLUMNAS = (
    b"nro_votacion,tipo,tema,factor_de_mayoria,respecto\n1,Despacho,Tema 1,0,votos_computables\n"
)


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
    raise_app_exceptions: bool = True,
) -> AsyncGenerator[tuple[AsyncClient, FastAPI]]:
    """Entrega cliente y aplicación con lifespan y archivos canónicos reales."""
    preparar_archivos_canonicos(tmp_path, quorum=quorum)
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()
    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(
            app=aplicacion,
            raise_app_exceptions=raise_app_exceptions,
        )
        async with AsyncClient(
            transport=transporte,
            base_url="http://pruebas",
        ) as cliente:
            yield cliente, aplicacion


async def preparar_sala_valida(cliente: AsyncClient) -> None:
    """Inicia la preparación del recinto."""
    respuesta = await cliente.post("/api/v1/preparacion")
    assert respuesta.status_code == 204


async def preparar_y_abrir(cliente: AsyncClient) -> None:
    """Completa las precondiciones y abre sesión formal."""
    await preparar_sala_valida(cliente)
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
                "presidencia": "Presidencia",
                "secretaria_legislativa": "Secretaría",
            },
        )
    ).status_code == 204
    assert (await cliente.post("/api/v1/sesion")).status_code == 204


def filas_auditoria(aplicacion: FastAPI) -> list[list[str]]:
    """Lee el CSV L1 del contexto activo."""
    estado = obtener_recursos_aplicacion(aplicacion).estado_operativo
    contexto = estado.contexto_operativo_activo()
    if contexto is None:
        return []
    ruta_l1 = contexto.rutas_auditoria()[0]
    with ruta_l1.open("r", encoding="utf-8-sig", newline="") as archivo:
        return list(csv.reader(archivo, delimiter=";"))


# ==============================================================================
# PRUEBAS POST /api/v1/orden-del-dia
# ==============================================================================


async def test_post_orden_del_dia_valido_en_preparando(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Demuestra la subida exitosa de un archivo CSV válido en PREPARANDO (200 OK)."""
    async with cliente_de_prueba(tmp_path, monkeypatch) as (cliente, aplicacion):
        await preparar_sala_valida(cliente)

        archivos = {"archivo": ("orden.csv", CSV_VALIDO, "text/csv")}
        respuesta = await cliente.post("/api/v1/orden-del-dia", files=archivos)
        assert respuesta.status_code == 200
        cuerpo = respuesta.json()
        assert "puntos" in cuerpo
        puntos = cuerpo["puntos"]
        assert len(puntos) == 2
        assert puntos[0] == {
            "nro_votacion": 1,
            "tipo": "Despacho",
            "tema": "Tema 1",
            "tipo_mayoria": "SIMPLE",
            "factor": 0,
            "base": "VOTOS_COMPUTABLES",
        }
        assert puntos[1] == {
            "nro_votacion": 2,
            "tipo": "Mocion",
            "tema": "Tema 2",
            "tipo_mayoria": "ESPECIAL",
            "factor": 0.6666666667,
            "base": "PRESENTES",
        }

        # Verificamos auditoría L2
        filas = filas_auditoria(aplicacion)
        eventos_od = [f for f in filas if f[4] == "ORDEN_DEL_DIA_CARGADO"]
        assert len(eventos_od) == 1
        assert eventos_od[0][2] == NivelAuditoria.L2.value


async def test_post_orden_del_dia_valido_en_sesion_abierta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Demuestra la subida exitosa de Orden del Día en SESION_ABIERTA (200 OK)."""
    async with cliente_de_prueba(tmp_path, monkeypatch) as (cliente, _aplicacion):
        await preparar_y_abrir(cliente)

        archivos = {"archivo": ("orden.csv", CSV_VALIDO, "text/csv")}
        respuesta = await cliente.post("/api/v1/orden-del-dia", files=archivos)
        assert respuesta.status_code == 200
        assert len(respuesta.json()["puntos"]) == 2


async def test_post_orden_del_dia_en_sin_preparar_devuelve_409(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Demuestra que intentar cargar en SIN_PREPARAR responde 409 ESTADO_INCOMPATIBLE."""
    async with cliente_de_prueba(tmp_path, monkeypatch) as (cliente, _aplicacion):
        archivos = {"archivo": ("orden.csv", CSV_VALIDO, "text/csv")}
        respuesta = await cliente.post("/api/v1/orden-del-dia", files=archivos)
        assert respuesta.status_code == 409
        cuerpo = respuesta.json()
        assert cuerpo["codigo"] == "ESTADO_INCOMPATIBLE"


async def test_post_orden_del_dia_sin_campo_archivo_devuelve_422(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Demuestra que la falta del campo 'archivo' responde 422 de validación FastAPI."""
    async with cliente_de_prueba(tmp_path, monkeypatch) as (cliente, _aplicacion):
        await preparar_sala_valida(cliente)
        # Enviamos un campo con nombre equivocado
        archivos = {"documento": ("orden.csv", CSV_VALIDO, "text/csv")}
        respuesta = await cliente.post("/api/v1/orden-del-dia", files=archivos)
        assert respuesta.status_code == 422


async def test_post_orden_del_dia_invalido_devuelve_422_orden_del_dia_invalido(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Demuestra que un archivo con errores técnicos responde 422 ORDEN_DEL_DIA_INVALIDO."""
    async with cliente_de_prueba(tmp_path, monkeypatch) as (cliente, _aplicacion):
        await preparar_sala_valida(cliente)
        csv_invalido = (
            b"nro_votacion,tipo,tema,tipo_mayoria,factor,base\n"
            b"1,Despacho,Tema,ESPECIAL,-5,PRESENTES\n"
        )
        archivos = {"archivo": ("orden.csv", csv_invalido, "text/csv")}
        respuesta = await cliente.post("/api/v1/orden-del-dia", files=archivos)
        assert respuesta.status_code == 422
        cuerpo = respuesta.json()
        assert cuerpo["codigo"] == "ORDEN_DEL_DIA_INVALIDO"


async def test_post_orden_del_dia_unicode_no_ascii_en_nro_votacion_devuelve_422(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Demuestra que caracteres Unicode como '²' en nro_votacion responden 422 y no 500."""
    async with cliente_de_prueba(tmp_path, monkeypatch) as (cliente, _aplicacion):
        await preparar_sala_valida(cliente)
        csv_unicode = (
            b"nro_votacion,tipo,tema,tipo_mayoria,factor,base\n\xc2\xb2,Despacho,Tema,SIMPLE,,\n"
        )
        archivos = {"archivo": ("orden.csv", csv_unicode, "text/csv")}
        respuesta = await cliente.post("/api/v1/orden-del-dia", files=archivos)
        assert respuesta.status_code == 422
        cuerpo = respuesta.json()
        assert cuerpo["codigo"] == "ORDEN_DEL_DIA_INVALIDO"


async def test_post_orden_del_dia_formato_historico_cinco_columnas_devuelve_422(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Demuestra que el formato de 5 columnas es rechazado con 422 ORDEN_DEL_DIA_INVALIDO."""
    async with cliente_de_prueba(tmp_path, monkeypatch) as (cliente, _aplicacion):
        await preparar_sala_valida(cliente)
        archivos = {"archivo": ("historico.csv", CSV_HISTORICO_CINCO_COLUMNAS, "text/csv")}
        respuesta = await cliente.post("/api/v1/orden-del-dia", files=archivos)
        assert respuesta.status_code == 422
        assert respuesta.json()["codigo"] == "ORDEN_DEL_DIA_INVALIDO"


async def test_post_orden_del_dia_encabezado_sin_filas_devuelve_puntos_vacio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Demuestra que un encabezado canónico con 0 filas devuelve 200 con puntos=[]."""
    async with cliente_de_prueba(tmp_path, monkeypatch) as (cliente, _aplicacion):
        await preparar_sala_valida(cliente)
        csv_vacio = b"nro_votacion,tipo,tema,tipo_mayoria,factor,base\n"
        archivos = {"archivo": ("vacio.csv", csv_vacio, "text/csv")}
        respuesta = await cliente.post("/api/v1/orden-del-dia", files=archivos)
        assert respuesta.status_code == 200
        assert respuesta.json() == {"puntos": []}


async def test_post_orden_del_dia_fallo_auditoria_devuelve_503(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Demuestra que si la auditoría obligatoria falla, responde 503 AUDITORIA_NO_DISPONIBLE."""
    async with cliente_de_prueba(tmp_path, monkeypatch) as (cliente, aplicacion):
        await preparar_sala_valida(cliente)

        # Cerramos el escritor para forzar ErrorAuditoria
        contexto = obtener_recursos_aplicacion(aplicacion).estado_operativo.preparacion_activa
        assert contexto is not None
        contexto.escritor_auditoria.cerrar()

        archivos = {"archivo": ("orden.csv", CSV_VALIDO, "text/csv")}
        respuesta = await cliente.post("/api/v1/orden-del-dia", files=archivos)
        assert respuesta.status_code == 503
        assert respuesta.json()["codigo"] == "AUDITORIA_NO_DISPONIBLE"
        # Fallo cerrado: no se instaló la colección
        assert contexto.orden_del_dia is None


async def test_post_orden_del_dia_error_inesperado_devuelve_500_sin_filtrar_detalles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Demuestra que un fallo no clasificado responde 500 ERROR_INTERNO sin filtrar trazas."""

    async def _fallar_inesperadamente(_self: Any, _bytes: bytes) -> Any:
        raise RuntimeError("detalle_interno_confidencial_post")

    monkeypatch.setattr(
        modulo_servicio_od.ServicioOrdenDelDia,
        "cargar_orden_del_dia",
        _fallar_inesperadamente,
    )

    async with cliente_de_prueba(tmp_path, monkeypatch, raise_app_exceptions=False) as (
        cliente,
        _aplicacion,
    ):
        await preparar_sala_valida(cliente)

        archivos = {"archivo": ("orden.csv", CSV_VALIDO, "text/csv")}
        respuesta = await cliente.post("/api/v1/orden-del-dia", files=archivos)
        assert respuesta.status_code == 500
        assert respuesta.json() == {
            "codigo": "ERROR_INTERNO",
            "mensaje": "Ocurrió un error interno.",
        }
        assert "detalle_interno_confidencial_post" not in respuesta.text


# ==============================================================================
# PRUEBAS DELETE /api/v1/orden-del-dia
# ==============================================================================


async def test_delete_orden_del_dia_efectivo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Demuestra que DELETE responde 204 No Content y audita ORDEN_DEL_DIA_DESCARTADO."""
    async with cliente_de_prueba(tmp_path, monkeypatch) as (cliente, aplicacion):
        await preparar_sala_valida(cliente)

        # Cargamos primero
        archivos = {"archivo": ("orden.csv", CSV_VALIDO, "text/csv")}
        assert (await cliente.post("/api/v1/orden-del-dia", files=archivos)).status_code == 200

        # Descartamos
        respuesta = await cliente.delete("/api/v1/orden-del-dia")
        assert respuesta.status_code == 204
        assert respuesta.content == b""

        # Verificamos auditoría de descarte
        filas = filas_auditoria(aplicacion)
        eventos_descarte = [f for f in filas if f[4] == "ORDEN_DEL_DIA_DESCARTADO"]
        assert len(eventos_descarte) == 1


async def test_delete_orden_del_dia_noop_sin_coleccion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Demuestra que DELETE sin colección previa responde 204 y no genera evento ficticio."""
    async with cliente_de_prueba(tmp_path, monkeypatch) as (cliente, aplicacion):
        await preparar_sala_valida(cliente)

        respuesta = await cliente.delete("/api/v1/orden-del-dia")
        assert respuesta.status_code == 204

        # No debe existir evento ORDEN_DEL_DIA_DESCARTADO
        filas = filas_auditoria(aplicacion)
        eventos_descarte = [f for f in filas if f[4] == "ORDEN_DEL_DIA_DESCARTADO"]
        assert len(eventos_descarte) == 0


async def test_delete_orden_del_dia_en_sin_preparar_devuelve_409(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Demuestra que intentar descartar en SIN_PREPARAR responde 409 ESTADO_INCOMPATIBLE."""
    async with cliente_de_prueba(tmp_path, monkeypatch) as (cliente, _aplicacion):
        respuesta = await cliente.delete("/api/v1/orden-del-dia")
        assert respuesta.status_code == 409
        assert respuesta.json()["codigo"] == "ESTADO_INCOMPATIBLE"


async def test_delete_orden_del_dia_fallo_auditoria_devuelve_503(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Demuestra que si la auditoría falla al descartar, responde 503 AUDITORIA_NO_DISPONIBLE."""
    async with cliente_de_prueba(tmp_path, monkeypatch) as (cliente, aplicacion):
        await preparar_sala_valida(cliente)

        archivos = {"archivo": ("orden.csv", CSV_VALIDO, "text/csv")}
        assert (await cliente.post("/api/v1/orden-del-dia", files=archivos)).status_code == 200

        # Cerramos el escritor para forzar ErrorAuditoria
        contexto = obtener_recursos_aplicacion(aplicacion).estado_operativo.preparacion_activa
        assert contexto is not None
        assert contexto.orden_del_dia is not None
        contexto.escritor_auditoria.cerrar()

        respuesta = await cliente.delete("/api/v1/orden-del-dia")
        assert respuesta.status_code == 503
        assert respuesta.json()["codigo"] == "AUDITORIA_NO_DISPONIBLE"
        # Fallo cerrado: la colección sigue intacta
        assert contexto.orden_del_dia is not None


async def test_delete_orden_del_dia_error_inesperado_devuelve_500_sin_filtrar_detalles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Demuestra que un fallo no clasificado en DELETE responde 500 ERROR_INTERNO."""

    async def _fallar_inesperadamente(_self: Any) -> None:
        raise RuntimeError("detalle_interno_confidencial_delete")

    monkeypatch.setattr(
        modulo_servicio_od.ServicioOrdenDelDia,
        "descartar_orden_del_dia",
        _fallar_inesperadamente,
    )

    async with cliente_de_prueba(tmp_path, monkeypatch, raise_app_exceptions=False) as (
        cliente,
        _aplicacion,
    ):
        await preparar_sala_valida(cliente)

        respuesta = await cliente.delete("/api/v1/orden-del-dia")
        assert respuesta.status_code == 500
        assert respuesta.json() == {
            "codigo": "ERROR_INTERNO",
            "mensaje": "Ocurrió un error interno.",
        }
        assert "detalle_interno_confidencial_delete" not in respuesta.text


# ==============================================================================
# PRUEBAS DE ESQUEMA OPENAPI
# ==============================================================================


async def test_esquema_openapi_orden_del_dia(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verifica que OpenAPI exponga correctamente POST multipart y DELETE, y no incluya GET."""
    async with cliente_de_prueba(tmp_path, monkeypatch) as (cliente, _aplicacion):
        respuesta = await cliente.get("/openapi.json")
        assert respuesta.status_code == 200
        esquema = respuesta.json()
        paths = esquema["paths"]

        ruta_od = "/api/v1/orden-del-dia"
        assert ruta_od in paths, "La ruta /api/v1/orden-del-dia debe existir en OpenAPI"
        operaciones = paths[ruta_od]

        # 1. POST existe y es multipart/form-data
        assert "post" in operaciones, "POST /api/v1/orden-del-dia debe estar documentado"
        post_op = operaciones["post"]
        content_type_post = post_op["requestBody"]["content"]
        assert "multipart/form-data" in content_type_post
        assert "200" in post_op["responses"]

        # 2. DELETE existe y responde 204
        assert "delete" in operaciones, "DELETE /api/v1/orden-del-dia debe estar documentado"
        delete_op = operaciones["delete"]
        assert "204" in delete_op["responses"]

        # 3. GET NO existe
        assert "get" not in operaciones, "GET /api/v1/orden-del-dia NO debe existir"


# ==============================================================================
# PRUEBAS DE LA AYUDA "NÚMERO YA TRATADO" (WP-053)
# ==============================================================================


async def test_estado_moderacion_marca_tratados_desde_la_apertura_real(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recorre por HTTP el camino completo que verá el operador.

    Se carga un Orden del Día con un número repetido, se abre la sesión y se
    abre una votación Nº 1 sin finalizarla. El snapshot de Moderación debe
    devolver ``tratado`` verdadero en las dos filas Nº 1 y falso en la Nº 2, y
    debe seguir haciéndolo en una segunda lectura del mismo endpoint, que es lo
    que ocurre cuando el frontend se reconecta o el operador recarga.
    """
    async with cliente_de_prueba(tmp_path, monkeypatch) as (cliente, _aplicacion):
        await preparar_sala_valida(cliente)
        archivos = {"archivo": ("orden.csv", CSV_CON_NUMERO_REPETIDO, "text/csv")}
        assert (await cliente.post("/api/v1/orden-del-dia", files=archivos)).status_code == 200

        # Antes de abrir cualquier votación no puede haber ningún punto tratado.
        antes = await cliente.get("/api/v1/estado/moderacion")
        assert antes.status_code == 200
        assert [punto["tratado"] for punto in antes.json()["orden_del_dia"]] == [
            False,
            False,
            False,
        ]

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
                    "presidencia": "Presidencia",
                    "secretaria_legislativa": "Secretaría",
                },
            )
        ).status_code == 204
        assert (await cliente.post("/api/v1/sesion")).status_code == 204

        apertura = await cliente.post(
            "/api/v1/votaciones",
            json={
                "numero_votacion": 1,
                "tipo": "Otro",
                "tema": "Tema decidido en el recinto",
                "tipo_mayoria": "SIMPLE",
            },
        )
        assert apertura.status_code == 201

        despues = await cliente.get("/api/v1/estado/moderacion")
        assert despues.status_code == 200
        puntos = despues.json()["orden_del_dia"]
        assert [(punto["nro_votacion"], punto["tratado"]) for punto in puntos] == [
            (1, True),
            (2, False),
            (1, True),
        ]

        # La votación sigue abierta y la lectura es reproducible: ningún snapshot
        # consume la marca ni depende del anterior.
        repetido = await cliente.get("/api/v1/estado/moderacion")
        assert [punto["tratado"] for punto in repetido.json()["orden_del_dia"]] == [
            True,
            False,
            True,
        ]
        assert repetido.json()["votacion"]["estado_recepcion"] == "EN_CURSO"

        # La proyección pública no gana la ayuda asistencial en ningún momento.
        recinto = await cliente.get("/api/v1/estado/recinto")
        assert recinto.status_code == 200
        assert "orden_del_dia" not in recinto.json()
