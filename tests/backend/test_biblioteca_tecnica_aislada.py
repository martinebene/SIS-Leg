"""Aislamiento de la biblioteca de Apoyo Técnico en pruebas y harness (WP-073).

WP-073 convierte `config/apoyo-tecnico/mensajes.csv` en dato operativo local: deja
de estar versionado y puede contener mensajes que alguien cargó a mano. Su
criterio 15 exige que ese archivo **nunca** sea sobrescrito por el bootstrap, por
los tests ni por la migración.

El E2E integrado necesita, sin embargo, demostrar persistencia real a disco del
CRUD de la biblioteca. La solución es un único punto de inyección: el parámetro
`ruta_mensajes_tecnicos` de `crear_aplicacion`. Estas pruebas fijan su contrato:

1. omitirlo deja exactamente la ruta productiva `config/apoyo-tecnico/mensajes.csv`;
2. pasarlo hace que el proceso **lea y escriba** ese archivo y ningún otro;
3. la ruta que usa la escritura es la misma que usó la lectura de arranque, de
   modo que un proceso no pueda leer un archivo y sobrescribir otro;
4. el parámetro sólo alcanza a la biblioteca: configuración, padrón y mapeo
   físico siguen resolviendo a sus rutas canónicas y ninguna prueba las desvía.

Ninguna prueba de este archivo escribe en la ruta productiva. La cuarta se
comprueba leyendo la ruta resuelta, sin ejecutar ningún comando de escritura.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sis_leg_backend.aplicacion import crear_aplicacion
from sis_leg_backend.recursos import obtener_recursos_aplicacion
from sis_leg_backend.servicios.apoyo_tecnico import RUTA_MENSAJES_TECNICOS_POR_DEFECTO
from sis_leg_backend.servicios.preparacion import (
    RUTA_CONFIGURACION_POR_DEFECTO,
    RUTA_PADRON_POR_DEFECTO,
)

pytestmark = pytest.mark.anyio

ENCABEZADO_BIBLIOTECA = "id,texto,destino\n"


def preparar_configuracion(directorio: Path) -> None:
    """Escribe la configuración canónica mínima dentro del directorio temporal.

    Repite deliberadamente el mismo armado que usan las demás pruebas HTTP: el
    backend debe resolver sus rutas exactamente como en producción, sólo que con
    el directorio de trabajo apuntado a `tmp_path`.
    """

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


async def test_sin_argumento_la_ruta_es_la_productiva(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El arranque productivo no cambia: `config/apoyo-tecnico/mensajes.csv`.

    Se comprueba la ruta **resuelta** por el proceso, sin ejecutar ningún
    comando de escritura, justamente para no tocar la biblioteca real de quien
    ejecuta las pruebas. El `chdir` a un directorio temporal hace además que la
    ruta relativa no pueda alcanzar el archivo del repositorio.
    """

    monkeypatch.chdir(tmp_path)
    preparar_configuracion(tmp_path)
    aplicacion = crear_aplicacion()

    async with aplicacion.router.lifespan_context(aplicacion):
        recursos = obtener_recursos_aplicacion(aplicacion)
        assert recursos.ruta_mensajes_tecnicos == RUTA_MENSAJES_TECNICOS_POR_DEFECTO
        assert recursos.ruta_mensajes_tecnicos == Path("config/apoyo-tecnico/mensajes.csv")


async def test_la_ruta_inyectada_recibe_lectura_y_escritura(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El CRUD real persiste en el archivo inyectado y en ninguno más.

    Es el escenario exacto del E2E integrado: la biblioteca vive fuera del
    árbol de trabajo del backend, se lee al arrancar y se reescribe en cada
    comando. Se comprueba además que el archivo de la ruta canónica ni siquiera
    llega a existir.
    """

    monkeypatch.chdir(tmp_path)
    preparar_configuracion(tmp_path)

    aislada = tmp_path / "biblioteca-aislada" / "mensajes.csv"
    aislada.parent.mkdir()
    aislada.write_text(f"{ENCABEZADO_BIBLIOTECA}previo,Mensaje previo,RECINTO\n", encoding="utf-8")

    aplicacion = crear_aplicacion(ruta_mensajes_tecnicos=aislada)

    async with aplicacion.router.lifespan_context(aplicacion):
        # 1. Lectura de arranque: el mensaje previo del archivo inyectado ya
        #    está publicado en la proyección técnica.
        recursos = obtener_recursos_aplicacion(aplicacion)
        assert recursos.ruta_mensajes_tecnicos == aislada
        biblioteca = recursos.estado_operativo.biblioteca_mensajes_tecnicos
        assert [mensaje.texto for mensaje in biblioteca.mensajes] == ["Mensaje previo"]

        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            # 2. Escritura: el alta tiene que aterrizar en el mismo archivo.
            alta = await cliente.post(
                "/api/v1/apoyo-tecnico/mensajes",
                json={"texto": "Mensaje nuevo", "destino": "AMBOS"},
            )
            assert alta.status_code == 201, alta.text
            identificador = alta.json()["mensaje_id"]

            contenido = aislada.read_text(encoding="utf-8")
            assert "Mensaje nuevo" in contenido
            assert "Mensaje previo" in contenido

            # 3. La baja también: escritura y lectura comparten ruta.
            baja = await cliente.delete(f"/api/v1/apoyo-tecnico/mensajes/{identificador}")
            assert baja.status_code == 204
            assert "Mensaje nuevo" not in aislada.read_text(encoding="utf-8")

    # 4. La ruta canónica relativa nunca se creó dentro del directorio de
    #    trabajo: ninguna escritura se escapó del archivo inyectado.
    assert not (tmp_path / RUTA_MENSAJES_TECNICOS_POR_DEFECTO).exists()


async def test_la_inyeccion_no_alcanza_a_configuracion_ni_padron(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La biblioteca es el único runtime reubicable por el harness de pruebas.

    Importa para el criterio 15 y para su contracara: la corrección no puede
    abrir una puerta por la que un test termine escribiendo sobre el
    `system.toml`, el padrón o el mapeo físico locales de alguien.
    """

    monkeypatch.chdir(tmp_path)
    preparar_configuracion(tmp_path)
    aislada = tmp_path / "otra" / "mensajes.csv"
    aislada.parent.mkdir()
    aislada.write_text(ENCABEZADO_BIBLIOTECA, encoding="utf-8")

    aplicacion = crear_aplicacion(ruta_mensajes_tecnicos=aislada)

    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            # Preparar el recinto es lo que carga configuración y padrón. Que
            # funcione demuestra que siguieron resolviendo a sus rutas canónicas
            # relativas al directorio de trabajo, ajenas a la inyección.
            preparacion = await cliente.post("/api/v1/preparacion", json={})
            assert preparacion.status_code == 204, preparacion.text

    assert Path("config/system.toml") == RUTA_CONFIGURACION_POR_DEFECTO
    assert Path("config/concejales.csv") == RUTA_PADRON_POR_DEFECTO
    assert (tmp_path / RUTA_CONFIGURACION_POR_DEFECTO).is_file()
    assert (tmp_path / RUTA_PADRON_POR_DEFECTO).is_file()
