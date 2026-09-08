"""Proyección del nombre institucional en los tres estados globales (WP-084).

El criterio de aceptación 2 exige que la Pantalla del Recinto muestre
*exactamente* el nombre configurado, y el WP añade que debe verse **también en
``SIN_PREPARAR``**. Esa disponibilidad permanente es la razón por la que la
identidad vive en el estado operativo y no dentro del contexto de preparación:
la cabecera pública existe desde que la pantalla se enciende, mucho antes de que
alguien prepare una sesión.

Estas pruebas demuestran además tres cosas que la revisión no puede dar por
supuestas: que la proyección es una copia fiel y no una reinterpretación, que el
plano privado de Moderación no recibe este bloque —no lo necesita— y que una
preparación refresca la copia leída al arrancar, de modo que durante la sesión
el Recinto muestre el nombre congelado y no una lectura vieja.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import LINEA_INSTITUCION, TOML_CANONICO
from sis_leg_backend.configuracion.identidad_institucional import MOTIVO_IDENTIDAD_INVALIDA
from sis_leg_backend.configuracion.modelos import (
    NOMBRE_INSTITUCIONAL_NEUTRO,
    IdentidadInstitucional,
)
from sis_leg_backend.dominio.estado import EstadoGlobal
from sis_leg_backend.recursos import crear_recursos_aplicacion

from tests.backend.ayudas_proyecciones import (
    NOMBRE_INSTITUCIONAL_DE_PRUEBA,
    abrir_sesion_prueba,
    crear_entorno_proyecciones,
)

pytestmark = pytest.mark.anyio


async def test_sin_preparar_el_recinto_recibe_el_nombre_configurado(tmp_path: Path) -> None:
    """Sin preparación activa no hay bancas ni quórum, pero sí identidad."""

    entorno = crear_entorno_proyecciones(tmp_path)
    entorno.estado.preparacion_activa = None
    entorno.estado.estado_global = EstadoGlobal.SIN_PREPARAR

    recinto = await entorno.servicio.obtener_estado_recinto()

    assert recinto.estado_global is EstadoGlobal.SIN_PREPARAR
    assert recinto.filas_bancas is None
    assert recinto.institucion.nombre == NOMBRE_INSTITUCIONAL_DE_PRUEBA


async def test_los_tres_estados_publican_exactamente_el_mismo_nombre(tmp_path: Path) -> None:
    """La identidad no depende del ciclo preparación/sesión."""

    entorno = crear_entorno_proyecciones(tmp_path)

    preparando = await entorno.servicio.obtener_estado_recinto()
    abrir_sesion_prueba(entorno)
    con_sesion = await entorno.servicio.obtener_estado_recinto()

    entorno.estado.preparacion_activa = None
    entorno.estado.sesion_activa = None
    entorno.estado.estado_global = EstadoGlobal.SIN_PREPARAR
    sin_preparar = await entorno.servicio.obtener_estado_recinto()

    assert preparando.estado_global is EstadoGlobal.PREPARANDO
    assert con_sesion.estado_global is EstadoGlobal.SESION_ABIERTA
    assert (
        preparando.institucion.model_dump()
        == con_sesion.institucion.model_dump()
        == sin_preparar.institucion.model_dump()
    )


async def test_publica_el_texto_configurado_sin_transformarlo(tmp_path: Path) -> None:
    """La proyección copia el nombre; no recorta, no acorta y no capitaliza."""

    entorno = crear_entorno_proyecciones(tmp_path)
    entorno.estado.identidad_institucional = IdentidadInstitucional(
        nombre="  Honorable Legislatura de la Región Continental  "
    )

    recinto = await entorno.servicio.obtener_estado_recinto()

    assert recinto.institucion.nombre == "  Honorable Legislatura de la Región Continental  "


async def test_el_bloque_publicado_es_minimo(tmp_path: Path) -> None:
    """Sólo viaja el nombre: el diagnóstico interno no llega a la sala.

    ``disponible``, ``motivo`` y ``detalle`` existen dentro del backend para que
    quien opera entienda por qué apareció el rótulo genérico, pero no son
    información que la pantalla del salón deba mostrar ni transportar.
    """

    entorno = crear_entorno_proyecciones(tmp_path)

    recinto = await entorno.servicio.obtener_estado_recinto()

    assert recinto.institucion.model_dump().keys() == {"nombre"}


async def test_moderacion_no_recibe_el_bloque_institucional(tmp_path: Path) -> None:
    """El nombre se muestra en la cabecera pública, no en el plano privado."""

    entorno = crear_entorno_proyecciones(tmp_path)

    moderacion = await entorno.servicio.obtener_estado_moderacion()

    assert "institucion" not in moderacion.model_dump()


async def test_una_identidad_degradada_publica_el_rotulo_neutro(tmp_path: Path) -> None:
    """Si el arranque no pudo leer la sección, la pantalla igual dice algo.

    Es la contracara del arranque tolerante: la degradación tiene que ser
    visible y legible, no un hueco en la cabecera.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    entorno.estado.identidad_institucional = IdentidadInstitucional(
        nombre=NOMBRE_INSTITUCIONAL_NEUTRO,
        disponible=False,
        motivo=MOTIVO_IDENTIDAD_INVALIDA,
        detalle="no se pudo leer la identidad institucional",
    )

    recinto = await entorno.servicio.obtener_estado_recinto()

    assert recinto.institucion.nombre == NOMBRE_INSTITUCIONAL_NEUTRO


async def test_el_arranque_carga_la_identidad_en_el_estado_operativo(tmp_path: Path) -> None:
    """``crear_recursos_aplicacion`` deja el nombre listo antes de preparar.

    Es la pieza que hace posible verlo en ``SIN_PREPARAR``: al arrancar, el
    proceso ya tiene la identidad en memoria, así que el primer snapshot del
    Recinto la incluye.
    """

    ruta = tmp_path / "system.toml"
    ruta.write_text(TOML_CANONICO, encoding="utf-8")

    recursos = crear_recursos_aplicacion(ruta_configuracion=ruta)

    assert recursos.estado_operativo.estado_global is EstadoGlobal.SIN_PREPARAR
    identidad = recursos.estado_operativo.identidad_institucional
    assert identidad.disponible is True
    assert identidad.nombre == NOMBRE_INSTITUCIONAL_DE_PRUEBA


async def test_un_toml_ilegible_no_impide_arrancar(tmp_path: Path) -> None:
    """Un archivo roto degrada el rótulo y nada más: el backend sigue operativo."""

    recursos = crear_recursos_aplicacion(ruta_configuracion=tmp_path / "no-existe.toml")

    identidad = recursos.estado_operativo.identidad_institucional
    assert identidad.disponible is False
    assert identidad.motivo == MOTIVO_IDENTIDAD_INVALIDA
    assert identidad.nombre == NOMBRE_INSTITUCIONAL_NEUTRO
    # El resto de los recursos existe igual: el arranque no quedó a medias.
    assert recursos.servicio_proyecciones is not None


async def test_preparar_refresca_la_identidad_leida_al_arrancar(tmp_path: Path) -> None:
    """Durante la sesión se ve el nombre congelado, no el leído al arrancar.

    El escenario es real: alguien corrige ``[institucion]`` con el backend ya
    encendido y después prepara. Si la preparación no refrescara la copia, la
    pantalla mostraría durante toda la sesión un nombre que ya no está en el
    archivo congelado, y el snapshot de la preparación diría otra cosa.
    """

    from sis_leg_backend.servicios.preparacion import ServicioPreparacion

    ruta = tmp_path / "system.toml"
    ruta.write_text(
        TOML_CANONICO.replace(LINEA_INSTITUCION, 'nombre = "Nombre viejo del cuerpo"'),
        encoding="utf-8",
    )
    ruta_padron = tmp_path / "concejales.csv"

    recursos = crear_recursos_aplicacion(ruta_configuracion=ruta)
    assert recursos.estado_operativo.identidad_institucional.nombre == "Nombre viejo del cuerpo"

    # El archivo cambia con el proceso ya encendido.
    ruta.write_text(
        TOML_CANONICO.replace(LINEA_INSTITUCION, 'nombre = "Nombre nuevo del cuerpo"')
        .replace('logs_dir = "logs"', f'logs_dir = "{tmp_path / "logs"}"')
        .replace("rows = [3, 4, 5]", "rows = [2]")
        .replace("quorum = 7", "quorum = 1"),
        encoding="utf-8",
    )
    _escribir_padron_minimo(ruta_padron)

    servicio = ServicioPreparacion(
        estado_operativo=recursos.estado_operativo,
        ejecutor_mutaciones=recursos.ejecutor_mutaciones,
        ruta_configuracion=ruta,
        ruta_padron=ruta_padron,
    )
    await servicio.preparar_sala()

    assert recursos.estado_operativo.estado_global is EstadoGlobal.PREPARANDO
    assert recursos.estado_operativo.identidad_institucional.nombre == "Nombre nuevo del cuerpo"

    recinto = await recursos.servicio_proyecciones.obtener_estado_recinto()
    assert recinto.institucion.nombre == "Nombre nuevo del cuerpo"


def _escribir_padron_minimo(ruta: Path) -> None:
    """Escribe un padrón ficticio de dos bancas, suficiente para preparar."""

    ruta.write_text(
        "dni,nombre,apellido,bloque,banca,dispositivo_votacion,ruta_imagen\n"
        "30000001,Amparo,Bermudez,Bloque Ejemplo A,1,dev01,assets/bancas/banca-01.png\n"
        "30000002,Bautista,Calvete,Bloque Ejemplo B,2,dev02,assets/bancas/banca-02.png\n",
        encoding="utf-8-sig",
    )
