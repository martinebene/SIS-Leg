"""Integración HTTP y SSE del plano técnico de Apoyo Técnico (WP-055).

Trabaja sobre una aplicación real creada por ``crear_aplicacion`` y un
directorio temporal como directorio de trabajo (``monkeypatch.chdir``), de modo
que el backend resuelve sus rutas canónicas —incluido
``config/apoyo-tecnico/mensajes.csv``— exactamente como en producción pero sin
tocar el disco del repositorio.

Cubre el contrato completo: comandos, validaciones, códigos de error estables,
la separación por destino en los tres snapshots y la notificación por SSE al
cruzar una frontera temporal, sin ningún sondeo periódico.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from pathlib import Path
from typing import Any, cast

import pytest
from httpx import ASGITransport, AsyncClient
from sis_leg_backend.aplicacion import crear_aplicacion
from sis_leg_backend.recursos import obtener_recursos_aplicacion

pytestmark = pytest.mark.anyio

RUTA_MENSAJES = Path("config/apoyo-tecnico/mensajes.csv")


def test_openapi_documenta_el_contrato_tecnico() -> None:
    """El contrato derivable declara rutas, bodies cerrados y separación."""

    esquema = crear_aplicacion().openapi()
    paths = esquema["paths"]
    for ruta in (
        "/api/v1/estado/tecnico",
        "/api/v1/estado/tecnico/stream",
        "/api/v1/apoyo-tecnico/transmision",
        "/api/v1/apoyo-tecnico/avisos",
        "/api/v1/apoyo-tecnico/avisos/{destino}",
        "/api/v1/apoyo-tecnico/mensajes",
        "/api/v1/apoyo-tecnico/mensajes/{mensaje_id}",
    ):
        assert ruta in paths

    esquemas = esquema["components"]["schemas"]
    for modelo in (
        "SolicitudIniciarTransmision",
        "SolicitudPublicarAviso",
        "SolicitudMensajeTecnico",
    ):
        assert esquemas[modelo]["additionalProperties"] is False

    assert esquemas["EstadoTransmision"]["enum"] == ["APAGADO", "CUENTA_REGRESIVA", "EN_VIVO"]
    assert esquemas["DestinoAvisoTecnico"]["enum"] == ["MODERACION", "RECINTO", "AMBOS"]

    # El submodelo que reciben Moderación y Recinto expone un único aviso: el
    # de su propio destino. La separación es parte del contrato, no del
    # frontend.
    apoyo = esquemas["ApoyoTecnicoProyectado"]["properties"]
    assert set(apoyo) == {"transmision", "aviso"}
    assert "biblioteca" not in str(esquemas["EstadoRecinto"])
    tecnico = esquemas["EstadoTecnico"]["properties"]
    assert {"aviso_moderacion", "aviso_recinto", "biblioteca", "eventos_recientes"} <= set(tecnico)


def preparar_configuracion(directorio: Path) -> None:
    """Escribe la configuración canónica mínima dentro del directorio temporal."""

    from conftest import (
        LINEA_LOGS,
        TOML_CANONICO,
        escribir_padron,
        escribir_system_toml,
        filas_padron_valido,
    )

    carpeta = directorio / "config"
    carpeta.mkdir(parents=True, exist_ok=True)
    escribir_system_toml(
        carpeta / "system.toml",
        TOML_CANONICO.replace(LINEA_LOGS, f'logs_dir = "{directorio}/logs"'),
    )
    escribir_padron(carpeta / "concejales.csv", filas_padron_valido())


async def test_ciclo_completo_de_transmision_por_http(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Iniciar con countdown, observar el snapshot y detener manualmente."""

    monkeypatch.chdir(tmp_path)
    preparar_configuracion(tmp_path)
    aplicacion = crear_aplicacion()

    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            inicial = await cliente.get("/api/v1/estado/tecnico")
            assert inicial.status_code == 200
            assert inicial.json()["transmision"]["estado"] == "APAGADO"

            respuesta = await cliente.post(
                "/api/v1/apoyo-tecnico/transmision",
                json={"cuenta_regresiva_segundos": 30},
            )
            assert respuesta.status_code == 204
            cuerpo = (await cliente.get("/api/v1/estado/tecnico")).json()
            assert cuerpo["transmision"]["estado"] == "CUENTA_REGRESIVA"
            assert cuerpo["transmision"]["cuenta_regresiva_segundos"] == 30
            assert cuerpo["transmision"]["en_vivo_desde"] is not None

            inmediato = await cliente.post("/api/v1/apoyo-tecnico/transmision", json={})
            assert inmediato.status_code == 204
            assert (await cliente.get("/api/v1/estado/tecnico")).json()["transmision"][
                "estado"
            ] == "EN_VIVO"

            detencion = await cliente.delete("/api/v1/apoyo-tecnico/transmision")
            assert detencion.status_code == 204
            assert (await cliente.get("/api/v1/estado/tecnico")).json()["transmision"][
                "estado"
            ] == "APAGADO"


async def test_avisos_por_destino_llegan_solo_a_su_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prueba 27: el Recinto no recibe datos técnicos que no le correspondan."""

    monkeypatch.chdir(tmp_path)
    preparar_configuracion(tmp_path)
    aplicacion = crear_aplicacion()

    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            publicacion = await cliente.post(
                "/api/v1/apoyo-tecnico/avisos",
                json={"texto": "Revisar consola", "destino": "MODERACION"},
            )
            assert publicacion.status_code == 204

            moderacion = (await cliente.get("/api/v1/estado/moderacion")).json()
            recinto = (await cliente.get("/api/v1/estado/recinto")).json()
            tecnico = (await cliente.get("/api/v1/estado/tecnico")).json()

            assert moderacion["tecnico"]["aviso"]["texto"] == "Revisar consola"
            assert recinto["tecnico"]["aviso"] is None
            assert tecnico["aviso_moderacion"]["texto"] == "Revisar consola"
            assert tecnico["aviso_recinto"] is None
            # La allowlist pública no gana ni la biblioteca ni el aviso ajeno.
            assert "biblioteca" not in json.dumps(recinto)
            assert "Revisar consola" not in json.dumps(recinto)

            cancelacion = await cliente.delete("/api/v1/apoyo-tecnico/avisos/MODERACION")
            assert cancelacion.status_code == 204
            assert (await cliente.get("/api/v1/estado/moderacion")).json()["tecnico"][
                "aviso"
            ] is None


async def test_crud_de_mensajes_por_http_persiste_en_el_csv_canonico(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prueba 19 sobre HTTP: el archivo canónico refleja cada comando."""

    monkeypatch.chdir(tmp_path)
    preparar_configuracion(tmp_path)
    aplicacion = crear_aplicacion()

    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            vacia = await cliente.get("/api/v1/apoyo-tecnico/mensajes")
            assert vacia.status_code == 200
            assert vacia.json() == {
                "disponible": True,
                "motivo": None,
                "detalle": None,
                "mensajes": [],
            }

            creacion = await cliente.post(
                "/api/v1/apoyo-tecnico/mensajes",
                json={"texto": "Volvemos en cinco minutos", "destino": "RECINTO"},
            )
            assert creacion.status_code == 201
            identificador = cast(str, creacion.json()["mensaje_id"])
            assert (tmp_path / RUTA_MENSAJES).exists()

            edicion = await cliente.put(
                f"/api/v1/apoyo-tecnico/mensajes/{identificador}",
                json={"texto": "Volvemos en diez minutos", "destino": "AMBOS"},
            )
            assert edicion.status_code == 200
            assert edicion.json() == {
                "mensaje_id": identificador,
                "texto": "Volvemos en diez minutos",
                "destino": "AMBOS",
            }

            estado = (await cliente.get("/api/v1/estado/tecnico")).json()
            assert estado["biblioteca"]["mensajes"] == [edicion.json()]

            baja = await cliente.delete(f"/api/v1/apoyo-tecnico/mensajes/{identificador}")
            assert baja.status_code == 204
            contenido = (tmp_path / RUTA_MENSAJES).read_text(encoding="utf-8")
            assert contenido == "id,texto,destino\n"


async def test_identificador_desconocido_responde_404_estable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prueba 29: los errores del contrato tienen código estable, no texto libre."""

    monkeypatch.chdir(tmp_path)
    preparar_configuracion(tmp_path)
    aplicacion = crear_aplicacion()

    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            edicion = await cliente.put(
                "/api/v1/apoyo-tecnico/mensajes/inexistente",
                json={"texto": "Cualquiera", "destino": "RECINTO"},
            )
            baja = await cliente.delete("/api/v1/apoyo-tecnico/mensajes/inexistente")

    assert edicion.status_code == 404
    assert edicion.json()["codigo"] == "MENSAJE_TECNICO_NO_EXISTENTE"
    assert baja.status_code == 404
    assert baja.json()["codigo"] == "MENSAJE_TECNICO_NO_EXISTENTE"


@pytest.mark.parametrize(
    ("ruta", "cuerpo"),
    [
        ("/api/v1/apoyo-tecnico/transmision", {"cuenta_regresiva_segundos": 0}),
        ("/api/v1/apoyo-tecnico/transmision", {"cuenta_regresiva_segundos": -5}),
        ("/api/v1/apoyo-tecnico/transmision", {"cuenta_regresiva_segundos": "30"}),
        ("/api/v1/apoyo-tecnico/transmision", {"cuenta_regresiva_segundos": 999999}),
        ("/api/v1/apoyo-tecnico/transmision", {"desconocido": 1}),
        ("/api/v1/apoyo-tecnico/avisos", {"texto": "   ", "destino": "RECINTO"}),
        ("/api/v1/apoyo-tecnico/avisos", {"texto": "Hola", "destino": "PANTALLA"}),
        ("/api/v1/apoyo-tecnico/avisos", {"texto": "Hola"}),
        (
            "/api/v1/apoyo-tecnico/avisos",
            {"texto": "Hola", "destino": "RECINTO", "duracion_segundos": 0},
        ),
        ("/api/v1/apoyo-tecnico/mensajes", {"texto": "", "destino": "RECINTO"}),
        ("/api/v1/apoyo-tecnico/mensajes", {"texto": "x" * 501, "destino": "RECINTO"}),
        (
            "/api/v1/apoyo-tecnico/mensajes",
            {"texto": "Hola", "destino": "RECINTO", "mensaje_id": "propio"},
        ),
    ],
    ids=[
        "countdown-cero",
        "countdown-negativo",
        "countdown-texto",
        "countdown-excesivo",
        "transmision-campo-extra",
        "aviso-texto-en-blanco",
        "aviso-destino-desconocido",
        "aviso-sin-destino",
        "aviso-duracion-cero",
        "mensaje-texto-vacio",
        "mensaje-texto-excesivo",
        "mensaje-id-impuesto",
    ],
)
async def test_bodies_invalidos_se_rechazan_con_422(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ruta: str,
    cuerpo: dict[str, Any],
) -> None:
    """El contrato es cerrado: ni coerciones silenciosas ni campos inventados."""

    monkeypatch.chdir(tmp_path)
    preparar_configuracion(tmp_path)
    aplicacion = crear_aplicacion()

    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            respuesta = await cliente.post(ruta, json=cuerpo)

    assert respuesta.status_code == 422


async def test_destino_desconocido_en_la_ruta_de_cancelacion_se_rechaza(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El parámetro de ruta también es un ``Literal`` cerrado."""

    monkeypatch.chdir(tmp_path)
    preparar_configuracion(tmp_path)
    aplicacion = crear_aplicacion()

    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            respuesta = await cliente.delete("/api/v1/apoyo-tecnico/avisos/PANTALLA")

    assert respuesta.status_code == 422


async def test_biblioteca_invalida_responde_503_y_no_pisa_el_archivo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prueba 23 sobre HTTP: se degrada la funcionalidad, no el arranque."""

    monkeypatch.chdir(tmp_path)
    preparar_configuracion(tmp_path)
    ruta = tmp_path / RUTA_MENSAJES
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("columna_unica\nvalor\n", encoding="utf-8")
    contenido_previo = ruta.read_bytes()
    aplicacion = crear_aplicacion()

    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            listado = await cliente.get("/api/v1/apoyo-tecnico/mensajes")
            creacion = await cliente.post(
                "/api/v1/apoyo-tecnico/mensajes",
                json={"texto": "Nuevo", "destino": "RECINTO"},
            )

    assert listado.status_code == 200
    assert listado.json()["disponible"] is False
    assert listado.json()["motivo"] == "BIBLIOTECA_MENSAJES_INVALIDA"
    assert creacion.status_code == 503
    assert creacion.json()["codigo"] == "BIBLIOTECA_MENSAJES_INVALIDA"
    assert ruta.read_bytes() == contenido_previo


async def test_biblioteca_persistida_se_relee_en_un_arranque_nuevo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prueba 20 sobre HTTP: un segundo lifespan recupera lo escrito por el primero."""

    monkeypatch.chdir(tmp_path)
    preparar_configuracion(tmp_path)

    primera = crear_aplicacion()
    async with primera.router.lifespan_context(primera):
        transporte = ASGITransport(app=primera)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            creacion = await cliente.post(
                "/api/v1/apoyo-tecnico/mensajes",
                json={"texto": "Sobrevive al reinicio", "destino": "AMBOS"},
            )
            identificador = cast(str, creacion.json()["mensaje_id"])

    segunda = crear_aplicacion()
    async with segunda.router.lifespan_context(segunda):
        transporte = ASGITransport(app=segunda)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            estado = (await cliente.get("/api/v1/estado/tecnico")).json()

    assert estado["biblioteca"]["mensajes"] == [
        {
            "mensaje_id": identificador,
            "texto": "Sobrevive al reinicio",
            "destino": "AMBOS",
        }
    ]
    # El estado operativo, en cambio, no se restaura: la transmisión vuelve a
    # APAGADO tal como exige RN-GLOBAL-03.
    assert estado["transmision"]["estado"] == "APAGADO"


def decodificar_evento(contenido: str) -> tuple[int, dict[str, Any]]:
    """Extrae ``id`` y JSON de un mensaje SSE del stream técnico."""

    lineas = contenido.rstrip("\n").splitlines()
    assert lineas[1] == "event: estado"
    revision = int(lineas[0].removeprefix("id: "))
    datos = cast(dict[str, Any], json.loads(lineas[2].removeprefix("data: ")))
    return revision, datos


async def test_stream_tecnico_publica_snapshot_inicial_y_cada_comando(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prueba 30: el stream notifica los cambios sin que el cliente pregunte."""

    monkeypatch.chdir(tmp_path)
    preparar_configuracion(tmp_path)
    aplicacion = crear_aplicacion()

    async with aplicacion.router.lifespan_context(aplicacion):
        recursos = obtener_recursos_aplicacion(aplicacion)
        from sis_leg_backend.api.estado import generar_stream_estado

        flujo = generar_stream_estado(
            recursos.servicio_proyecciones.obtener_estado_tecnico,
            recursos.coordinador_publicacion,
        )
        revision_inicial, inicial = decodificar_evento(await anext(flujo))
        assert revision_inicial == 0
        assert inicial["transmision"]["estado"] == "APAGADO"

        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            await cliente.post(
                "/api/v1/apoyo-tecnico/avisos",
                json={"texto": "Aviso por stream", "destino": "AMBOS"},
            )

        revision, datos = decodificar_evento(await anext(flujo))
        assert revision > revision_inicial
        assert datos["aviso_moderacion"]["texto"] == "Aviso por stream"
        assert datos["aviso_recinto"]["aviso_id"] == datos["aviso_moderacion"]["aviso_id"]
        await flujo.aclose()


async def test_la_frontera_temporal_republica_sin_ningun_comando(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prueba 17 de punta a punta: el vencimiento despierta al temporizador.

    Se usa el ``ServicioFronterasTemporales`` real con una espera inyectada, de
    modo que la prueba no aguarde segundos reales pero sí demuestre el camino
    completo: el vencimiento del aviso quedó registrado como frontera pendiente
    (la demora que el temporizador pidió esperar) y su cumplimiento produjo una
    revisión nueva sin que ningún cliente preguntara nada.

    Que el aviso efectivamente desaparezca del payload al cruzar la frontera se
    verifica de forma determinista, con reloj controlado, en
    ``test_aviso_con_duracion_expira_en_la_frontera``.
    """

    monkeypatch.chdir(tmp_path)
    preparar_configuracion(tmp_path)
    aplicacion = crear_aplicacion()

    async with aplicacion.router.lifespan_context(aplicacion):
        recursos = obtener_recursos_aplicacion(aplicacion)
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            await cliente.post(
                "/api/v1/apoyo-tecnico/avisos",
                json={"texto": "Aviso efímero", "destino": "RECINTO", "duracion_segundos": 1},
            )

        vigente = await recursos.servicio_proyecciones.obtener_estado_tecnico()
        assert vigente.aviso_recinto is not None
        revision_previa = vigente.revision

        demora_observada: list[float] = []

        async def esperar_instantaneo(demora: float) -> None:
            """Sustituye la espera real conservando la demora que se pidió."""

            demora_observada.append(demora)
            await asyncio.sleep(0)

        from sis_leg_backend.servicios.fronteras_temporales import (
            ServicioFronterasTemporales,
        )

        fronteras = ServicioFronterasTemporales(
            recursos.servicio_proyecciones,
            recursos.ejecutor_mutaciones,
            recursos.coordinador_publicacion,
            esperar=esperar_instantaneo,
        )
        tarea = asyncio.create_task(fronteras.ejecutar())
        for _ in range(50):
            await asyncio.sleep(0)
            if recursos.coordinador_publicacion.revision > revision_previa:
                break
        tarea.cancel()
        with suppress(asyncio.CancelledError):
            await tarea

    assert demora_observada
    assert 0 < demora_observada[0] <= 1
    assert recursos.coordinador_publicacion.revision > revision_previa
