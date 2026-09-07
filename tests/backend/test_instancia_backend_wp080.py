"""Identidad de instancia del backend y continuidad de sincronización (WP-080).

## Qué problema fija esta suite

``revision`` sólo es monotónica **dentro de una vida del proceso**: al reiniciar
el backend vuelve a ``0``. Un frontend que hubiera adoptado la revisión 142 del
proceso anterior descartaría, por menores, todas las revisiones del proceso
nuevo, y quedaría congelado mostrando un estado que ya no existe.

La corrección es que cada estado publicado diga **de qué proceso viene**. Estas
pruebas verifican el lado servidor de ese contrato: que el identificador exista
en las tres proyecciones, que sea estable durante toda la vida del proceso, que
cambie al reiniciar y que la secuencia "REST con revisión alta seguido de SSE
con revisión baja" sea distinguible sin depender del reloj ni de un error de
red.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from httpx import ASGITransport, AsyncClient
from sis_leg_backend.api.estado import codificar_evento_sse, generar_stream_estado
from sis_leg_backend.aplicacion import crear_aplicacion
from sis_leg_backend.servicios.publicacion import CoordinadorPublicacion

from tests.backend.ayudas_proyecciones import crear_entorno_proyecciones

pytestmark = pytest.mark.anyio


def datos_de_evento(contenido: str) -> tuple[int, dict[str, Any]]:
    """Extrae el ``id`` y el payload JSON de un mensaje SSE."""

    lineas = contenido.rstrip("\n").splitlines()
    revision = int(lineas[0].removeprefix("id: "))
    return revision, cast(dict[str, Any], json.loads(lineas[2].removeprefix("data: ")))


async def test_las_tres_proyecciones_declaran_la_misma_instancia(tmp_path: Path) -> None:
    """Un mismo proceso identifica igual a Moderación, Recinto y Apoyo Técnico.

    Es la condición que hace que las tres pantallas apliquen la misma regla de
    continuidad: si cada proyección inventara su propio identificador, un mismo
    reinicio se vería distinto en cada puesto.
    """

    entorno = crear_entorno_proyecciones(tmp_path)

    moderacion = await entorno.servicio.obtener_estado_moderacion()
    recinto = await entorno.servicio.obtener_estado_recinto()
    tecnico = await entorno.servicio.obtener_estado_tecnico()

    assert moderacion.instancia == entorno.coordinador.instancia
    assert recinto.instancia == entorno.coordinador.instancia
    assert tecnico.instancia == entorno.coordinador.instancia
    # La subproyección sonora del puesto técnico también la transporta: su
    # detector de transiciones necesita reconocer un cambio de proceso.
    assert tecnico.sonorizacion.instancia == entorno.coordinador.instancia


async def test_la_instancia_no_cambia_aunque_avance_la_revision(tmp_path: Path) -> None:
    """La identidad acompaña al proceso, no al estado observable.

    Si cambiara con cada mutación, el cliente rebaselinaría permanentemente y
    perdería la deduplicación por revisión que WP-080 debe preservar intacta.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    dni = entorno.contexto.padron.concejales[0].dni

    inicial = await entorno.servicio.obtener_estado_moderacion()

    async def marcar_presente() -> None:
        entorno.contexto.presencias[dni] = True

    await entorno.ejecutor.ejecutar(marcar_presente)
    posterior = await entorno.servicio.obtener_estado_moderacion()

    assert posterior.revision > inicial.revision
    assert posterior.instancia == inicial.instancia


def test_dos_procesos_distintos_reciben_identidades_distintas() -> None:
    """Cada arranque genera su propia identidad, sin persistirla ni derivarla del reloj."""

    primero = CoordinadorPublicacion()
    segundo = CoordinadorPublicacion()

    assert primero.instancia != segundo.instancia
    # Es opaca: ni vacía ni con estructura que invite a interpretarla.
    assert primero.instancia
    assert isinstance(primero.instancia, str)


async def test_reinicio_produce_revision_menor_con_instancia_nueva(tmp_path: Path) -> None:
    """Reproduce del lado servidor la secuencia REST alto -> reinicio -> SSE bajo.

    El proceso A avanza varias revisiones y entrega su snapshot REST. El proceso
    B, recién arrancado, entrega por SSE una revisión numéricamente menor. Lo
    único que distingue ambos estados es la instancia: sin ella el cliente no
    tendría forma de saber que el segundo es más nuevo que el primero.
    """

    proceso_a = crear_entorno_proyecciones(tmp_path / "a")
    dni = proceso_a.contexto.padron.concejales[0].dni

    async def alternar_presencia() -> None:
        entrada = proceso_a.contexto.presencias
        entrada[dni] = not entrada[dni]

    for _ in range(5):
        await proceso_a.ejecutor.ejecutar(alternar_presencia)

    snapshot_rest_a = await proceso_a.servicio.obtener_estado_moderacion()
    assert snapshot_rest_a.revision >= 5

    # "Reinicio": un proceso nuevo, con estado en memoria nuevo y contador en 0.
    proceso_b = crear_entorno_proyecciones(tmp_path / "b")
    flujo = generar_stream_estado(
        proceso_b.servicio.obtener_estado_moderacion,
        proceso_b.coordinador,
    )
    revision_sse, datos_sse = datos_de_evento(await anext(flujo))
    await flujo.aclose()

    assert revision_sse < snapshot_rest_a.revision
    assert datos_sse["instancia"] != snapshot_rest_a.instancia
    # El ``id`` del evento sigue siendo la revisión: WP-080 no cambió el cursor
    # del protocolo, sólo agregó la mitad que lo hace comparable.
    assert datos_sse["revision"] == revision_sse


async def test_snapshot_rest_y_evento_sse_del_mismo_proceso_coinciden(tmp_path: Path) -> None:
    """REST y SSE comparten constructor, así que no pueden divergir en la identidad."""

    entorno = crear_entorno_proyecciones(tmp_path)

    snapshot = await entorno.servicio.obtener_estado_recinto()
    _, datos = datos_de_evento(codificar_evento_sse(snapshot))

    assert datos["instancia"] == snapshot.instancia


async def test_los_tres_endpoints_rest_publican_la_instancia() -> None:
    """Verifica el contrato sobre HTTP real, no sólo sobre el servicio interno."""

    aplicacion = crear_aplicacion()
    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            respuestas = [
                await cliente.get("/api/v1/estado/moderacion"),
                await cliente.get("/api/v1/estado/recinto"),
                await cliente.get("/api/v1/estado/tecnico"),
            ]

    instancias = {respuesta.json()["instancia"] for respuesta in respuestas}
    assert all(respuesta.status_code == 200 for respuesta in respuestas)
    assert len(instancias) == 1
    assert next(iter(instancias))
