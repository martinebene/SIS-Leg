"""Pruebas del harness HTTP integrado y separado del runtime productivo."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sis_leg_backend.aplicacion import crear_aplicacion

import scripts.iniciar_stack_desarrollo as modulo_stack
from scripts.iniciar_stack_desarrollo import (
    ESPERA_APAGADO_SEGUNDOS,
    HOST_PREDETERMINADO,
    PUERTO_PREDETERMINADO,
    ErrorSalidaSpa,
    crear_analizador_argumentos,
    crear_aplicacion_integrada,
    ejecutar_servidor,
)

pytestmark = pytest.mark.anyio


def crear_salida_spa(ruta: Path, titulo: str) -> Path:
    """Fabrica el mínimo equivalente a un output Nuxt para tests rápidos."""

    ruta.mkdir(parents=True)
    (ruta / "index.html").write_text(
        f"<!doctype html><html><body>{titulo}</body></html>",
        encoding="utf-8",
    )
    directorio_assets = ruta / "_nuxt"
    directorio_assets.mkdir()
    (directorio_assets / "entrada.js").write_text(
        f"console.log('{titulo}')",
        encoding="utf-8",
    )
    return ruta


async def test_aplicacion_integrada_conserva_fastapi_y_sirve_las_cinco_spa(
    tmp_path: Path,
) -> None:
    """REST, OpenAPI y los assets conviven realmente bajo un único origen."""

    moderacion = crear_salida_spa(tmp_path / "moderacion", "Moderación real")
    recinto = crear_salida_spa(tmp_path / "recinto", "Recinto real")
    simulador = crear_salida_spa(tmp_path / "simulador", "Simulador real")
    tecnico = crear_salida_spa(tmp_path / "tecnico", "Apoyo Técnico real")
    zocalo = crear_salida_spa(tmp_path / "zocalo", "Zócalo real")
    aplicacion = crear_aplicacion_integrada(moderacion, recinto, simulador, tecnico, zocalo)

    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            salud = await cliente.get("/api/v1/health")
            documentacion = await cliente.get("/docs")
            indice = await cliente.get("/")
            pagina_moderacion = await cliente.get("/moderacion/")
            asset_moderacion = await cliente.get("/moderacion/_nuxt/entrada.js")
            pagina_recinto = await cliente.get("/recinto/")
            asset_recinto = await cliente.get("/recinto/_nuxt/entrada.js")
            pagina_simulador = await cliente.get("/simulador/")
            asset_simulador = await cliente.get("/simulador/_nuxt/entrada.js")
            pagina_tecnico = await cliente.get("/tecnico/")
            asset_tecnico = await cliente.get("/tecnico/_nuxt/entrada.js")
            pagina_zocalo = await cliente.get("/zocalo/")
            asset_zocalo = await cliente.get("/zocalo/_nuxt/entrada.js")
            pagina_manual = await cliente.get("/manual/")

    assert salud.status_code == 200
    assert salud.json() == {"estado": "ok"}
    assert documentacion.status_code == 200
    assert "/moderacion/" in indice.text
    assert "/recinto/" in indice.text
    assert "/simulador/" in indice.text
    assert "/tecnico/" in indice.text
    assert "/zocalo/" in indice.text
    assert "/manual/" in indice.text
    assert pagina_moderacion.status_code == 200
    assert "Moderación real" in pagina_moderacion.text
    assert asset_moderacion.text == "console.log('Moderación real')"
    assert pagina_recinto.status_code == 200
    assert "Recinto real" in pagina_recinto.text
    assert asset_recinto.text == "console.log('Recinto real')"
    assert pagina_simulador.status_code == 200
    assert "Simulador real" in pagina_simulador.text
    assert asset_simulador.text == "console.log('Simulador real')"
    assert pagina_tecnico.status_code == 200
    assert "Apoyo Técnico real" in pagina_tecnico.text
    assert asset_tecnico.text == "console.log('Apoyo Técnico real')"
    # Zócalo para OBS (WP-099): se sirve bajo el mismo origen que el resto, que es el
    # contrato que después reproduce Nginx en producción.
    assert pagina_zocalo.status_code == 200
    assert "Zócalo real" in pagina_zocalo.text
    assert asset_zocalo.text == "console.log('Zócalo real')"
    # El manual (WP-067) se monta desde su directorio versionado, no desde un build: acá se
    # comprueba que `/manual/` resuelva al documento real bajo el mismo origen, igual que
    # hará Nginx en producción.
    assert pagina_manual.status_code == 200
    assert "cap-01-vision-general" in pagina_manual.text


async def test_aplicacion_productiva_no_adquiere_los_mounts_del_harness(tmp_path: Path) -> None:
    """Crear el harness no contamina futuras instancias del backend normal."""

    integrada = crear_aplicacion_integrada(
        crear_salida_spa(tmp_path / "moderacion", "Moderación"),
        crear_salida_spa(tmp_path / "recinto", "Recinto"),
        crear_salida_spa(tmp_path / "simulador", "Simulador"),
        crear_salida_spa(tmp_path / "tecnico", "Apoyo Técnico"),
        crear_salida_spa(tmp_path / "zocalo", "Zócalo"),
    )
    productiva = crear_aplicacion()

    transporte = ASGITransport(app=productiva)
    async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
        respuesta_moderacion = await cliente.get("/moderacion/")
        respuesta_simulador = await cliente.get("/simulador/")
        respuesta_tecnico = await cliente.get("/tecnico/")
        respuesta_zocalo = await cliente.get("/zocalo/")

    assert respuesta_moderacion.status_code == 404
    assert respuesta_simulador.status_code == 404
    assert respuesta_tecnico.status_code == 404
    assert respuesta_zocalo.status_code == 404
    # Los mounts y el índice del tooling están fuera de OpenAPI, por lo que el
    # contrato técnico canónico sigue siendo exactamente el del backend.
    assert integrada.openapi() == productiva.openapi()


@pytest.mark.parametrize(
    ("estado_salida", "fragmento"),
    [
        ("AUSENTE", "No existe la salida estática de Moderación"),
        ("SIN_INDICE", "no contiene un index.html válido"),
        ("SIN_ASSETS", "no contiene los assets compilados"),
    ],
    ids=["directorio-ausente", "indice-ausente", "assets-ausentes"],
)
def test_rechaza_salidas_estaticas_ausentes_o_incompletas(
    tmp_path: Path,
    estado_salida: str,
    fragmento: str,
) -> None:
    """Un artefacto inválido falla antes de abrir un listener HTTP."""

    moderacion = tmp_path / "moderacion"
    if estado_salida == "SIN_INDICE":
        moderacion.mkdir()
    elif estado_salida == "SIN_ASSETS":
        moderacion.mkdir()
        (moderacion / "index.html").write_text("ok", encoding="utf-8")
    recinto = crear_salida_spa(tmp_path / "recinto", "Recinto")
    simulador = crear_salida_spa(tmp_path / "simulador", "Simulador")
    tecnico = crear_salida_spa(tmp_path / "tecnico", "Apoyo Técnico")
    zocalo = crear_salida_spa(tmp_path / "zocalo", "Zócalo")

    with pytest.raises(ErrorSalidaSpa, match=fragmento):
        crear_aplicacion_integrada(moderacion, recinto, simulador, tecnico, zocalo)


def test_rechaza_un_manual_ausente_antes_de_abrir_el_servidor(tmp_path: Path) -> None:
    """El manual es parte de la superficie servida: si falta, el stack no debe arrancar.

    Sin esta comprobación el servidor levantaría igual y el icono de ayuda de Moderación y
    de Apoyo Técnico devolvería 404 sin que nada lo advirtiera.
    """

    with pytest.raises(ErrorSalidaSpa, match="manual de usuario"):
        crear_aplicacion_integrada(
            crear_salida_spa(tmp_path / "moderacion", "Moderación"),
            crear_salida_spa(tmp_path / "recinto", "Recinto"),
            crear_salida_spa(tmp_path / "simulador", "Simulador"),
            crear_salida_spa(tmp_path / "tecnico", "Apoyo Técnico"),
            crear_salida_spa(tmp_path / "zocalo", "Zócalo"),
            tmp_path / "manual-inexistente",
        )


def test_configuracion_predeterminada_usa_loopback_y_puerto_8000() -> None:
    """La CLI no expone accidentalmente el harness a otras interfaces."""

    opciones = crear_analizador_argumentos().parse_args([])

    assert opciones.host == HOST_PREDETERMINADO == "127.0.0.1"
    assert opciones.port == PUERTO_PREDETERMINADO == 8000


def test_servidor_usa_un_worker_y_no_crea_procesos_hijos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Uvicorn recibe la aplicación directa y un único worker en foreground."""

    llamadas: list[tuple[FastAPI, str, int, int, int]] = []

    def ejecutar_uvicorn_falso(
        aplicacion: FastAPI,
        *,
        host: str,
        port: int,
        workers: int,
        timeout_graceful_shutdown: int,
    ) -> None:
        llamadas.append((aplicacion, host, port, workers, timeout_graceful_shutdown))

    monkeypatch.setattr(modulo_stack.uvicorn, "run", ejecutar_uvicorn_falso)
    aplicacion = FastAPI()

    ejecutar_servidor(aplicacion, "127.0.0.1", 8000)

    assert llamadas == [(aplicacion, "127.0.0.1", 8000, 1, ESPERA_APAGADO_SEGUNDOS)]
