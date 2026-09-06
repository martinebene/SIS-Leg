"""Integración HTTP de los snapshots REST completos de WP-017."""

from __future__ import annotations

import json
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
from sis_leg_backend.api.estado import generar_stream_estado
from sis_leg_backend.aplicacion import crear_aplicacion
from sis_leg_backend.recursos import obtener_recursos_aplicacion

pytestmark = pytest.mark.anyio


def preparar_archivos(directorio: Path) -> None:
    """Instala configuración/padrón ficticios y redirige los CSV al tmp."""

    carpeta = directorio / "config"
    carpeta.mkdir(parents=True)
    escribir_system_toml(
        carpeta / "system.toml",
        TOML_CANONICO.replace(LINEA_LOGS, f'logs_dir = "{directorio}/logs"'),
    )
    escribir_padron(carpeta / "concejales.csv", filas_padron_valido())


async def test_rest_moderacion_y_recinto_responden_en_sin_preparar() -> None:
    """Los dos snapshots son válidos desde el arranque limpio."""

    aplicacion = crear_aplicacion()
    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            moderacion = await cliente.get("/api/v1/estado/moderacion")
            recinto = await cliente.get("/api/v1/estado/recinto")

    assert moderacion.status_code == recinto.status_code == 200
    assert moderacion.json()["estado_global"] == "SIN_PREPARAR"
    assert recinto.json()["estado_global"] == "SIN_PREPARAR"
    assert moderacion.json()["capacidades"]["preparar_sala"] == {
        "habilitada": True,
        "motivos": [],
    }
    assert "capacidades" not in recinto.json()


async def test_rest_preparando_y_sesion_abierta_reconstruyen_todo_el_contexto(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recorre preparación, autoridades, test, quórum, Orden, palabra y voto."""

    preparar_archivos(tmp_path)
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
                        "numero_sesion": 17,
                        "presidencia": "Presidencia ficticia",
                        "secretaria_legislativa": "Secretaría ficticia",
                    },
                )
            ).status_code == 204
            # Test en banca 1 y siete presencias para alcanzar el quórum.
            assert (
                await cliente.post(
                    "/api/v1/entradas/tecla",
                    json={"dispositivo": "D-01", "tecla": "8"},
                )
            ).status_code == 200
            # El test visual dura deliberadamente pocos milisegundos. Lo observamos
            # inmediatamente después del comando que lo activa, antes de ejecutar las
            # siete mutaciones de presencia que no forman parte de esta aserción.
            moderacion_con_test = await cliente.get("/api/v1/estado/moderacion")
            assert moderacion_con_test.status_code == 200
            assert moderacion_con_test.json()["concejales"][0]["test_activo"]
            for numero in range(1, 8):
                respuesta = await cliente.post(
                    "/api/v1/entradas/tecla",
                    json={"dispositivo": f"D-{numero:02d}", "tecla": "9"},
                )
                assert respuesta.status_code == 200

            preparacion_moderacion = await cliente.get("/api/v1/estado/moderacion")
            preparacion_recinto = await cliente.get("/api/v1/estado/recinto")
            assert preparacion_moderacion.status_code == preparacion_recinto.status_code == 200
            assert preparacion_moderacion.json()["estado_global"] == "PREPARANDO"
            assert preparacion_moderacion.json()["quorum"] == {
                "cantidad_presentes": 7,
                "requerido": 7,
                "alcanzado": True,
            }
            assert preparacion_recinto.json()["preparacion"]["numero_sesion"] == 17
            assert preparacion_recinto.json()["filas_bancas"] == [3, 4, 5]
            assert [
                evento["codigo_evento"] for evento in preparacion_recinto.json()["eventos_publicos"]
            ] == ["CONCEJAL_PRESENTE"] * 7

            orden = (
                b"nro_votacion,tipo,tema,tipo_mayoria,factor,base\n"
                b"1,Otro,Tema asistencial,SIMPLE,0,VOTOS_COMPUTABLES\n"
            )
            carga = await cliente.post(
                "/api/v1/orden-del-dia",
                files={"archivo": ("orden.csv", orden, "text/csv")},
            )
            assert carga.status_code == 200
            assert (await cliente.post("/api/v1/sesion")).status_code == 204
            pedido = await cliente.post(
                "/api/v1/entradas/tecla",
                json={"dispositivo": "D-01", "tecla": "7"},
            )
            assert pedido.status_code == 200

            sesion_moderacion = await cliente.get("/api/v1/estado/moderacion")
            sesion_recinto = await cliente.get("/api/v1/estado/recinto")
            cuerpo_moderacion = sesion_moderacion.json()
            cuerpo_recinto = sesion_recinto.json()
            assert cuerpo_moderacion["estado_global"] == "SESION_ABIERTA"
            assert cuerpo_moderacion["sesion"]["presidencia"] == "Presidencia ficticia"
            assert cuerpo_moderacion["orden_del_dia"][0]["tema"] == "Tema asistencial"
            assert cuerpo_moderacion["palabra"]["cola"][0]["banca"] == 1
            assert "dni" not in cuerpo_recinto["palabra"]["cola"][0]
            assert cuerpo_recinto["filas_bancas"] == [3, 4, 5]

            apertura = await cliente.post(
                "/api/v1/votaciones",
                json={
                    "numero_votacion": 1,
                    "tipo": "Otro",
                    "tema": "Tema sometido a votación",
                    "tipo_mayoria": "SIMPLE",
                    "factor": 0,
                    "base": "VOTOS_COMPUTABLES",
                },
            )
            assert apertura.status_code == 201
            voto = await cliente.post(
                "/api/v1/entradas/tecla",
                json={"dispositivo": "D-01", "tecla": "1"},
            )
            assert voto.status_code == 200

            moderacion_votando = await cliente.get("/api/v1/estado/moderacion")
            recinto_votando = await cliente.get("/api/v1/estado/recinto")
            datos_moderacion = moderacion_votando.json()["votacion"]
            texto_publico = recinto_votando.text
            assert datos_moderacion["cantidad_votos_recibidos"] == 1
            assert datos_moderacion["votos_individuales"] is None
            assert recinto_votando.json()["votacion"]["votos_individuales"] is None
            assert "POSITIVO" not in texto_publico
            assert filas_padron_valido()[0][0] not in texto_publico
            assert "VOTO_ORDINARIO_REGISTRADO" not in texto_publico
            codigos_publicos = [
                evento["codigo_evento"] for evento in recinto_votando.json()["eventos_publicos"]
            ]
            assert codigos_publicos[-3:] == [
                "SESION_ABIERTA",
                "PEDIDO_PALABRA_REGISTRADO",
                "VOTACION_ABIERTA",
            ]

            # El generador usado por el endpoint SSE serializa la misma colección
            # del mismo contexto real. No se comparan dos llamadas aisladas al
            # constructor: arriba se ejercitó GET y acá el frame `data:` real.
            recursos = obtener_recursos_aplicacion(aplicacion)
            flujo = generar_stream_estado(
                recursos.servicio_proyecciones.obtener_estado_recinto,
                recursos.coordinador_publicacion,
            )
            frame = await anext(flujo)
            linea_datos = next(linea for linea in frame.splitlines() if linea.startswith("data: "))
            cuerpo_sse = json.loads(linea_datos.removeprefix("data: "))
            assert cuerpo_sse["eventos_publicos"] == recinto_votando.json()["eventos_publicos"]
            await flujo.aclose()


def test_openapi_rest_referencia_esquemas_pydantic_completos() -> None:
    """WP-018 puede derivar ambos tipos desde componentes de OpenAPI."""

    esquema = crear_aplicacion().openapi()
    respuestas_moderacion = esquema["paths"]["/api/v1/estado/moderacion"]["get"]["responses"]
    respuestas_recinto = esquema["paths"]["/api/v1/estado/recinto"]["get"]["responses"]
    referencia_moderacion = respuestas_moderacion["200"]["content"]["application/json"]["schema"][
        "$ref"
    ]
    referencia_recinto = respuestas_recinto["200"]["content"]["application/json"]["schema"]["$ref"]

    assert referencia_moderacion.endswith("/EstadoModeracion")
    assert referencia_recinto.endswith("/EstadoRecinto")
    assert "EstadoModeracion" in esquema["components"]["schemas"]
    assert "EstadoRecinto" in esquema["components"]["schemas"]
