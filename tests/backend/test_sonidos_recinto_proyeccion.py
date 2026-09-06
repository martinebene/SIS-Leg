"""Proyección de la configuración de audio del Recinto en los tres estados (WP-065).

El criterio de aceptación 3 de WP-065 exige que la Pantalla del Recinto reciba
la configuración de sonidos en ``SIN_PREPARAR``, ``PREPARANDO`` y
``SESION_ABIERTA``. Esa disponibilidad permanente es la razón por la que los
sonidos viven en el estado operativo y no dentro del contexto de preparación:
la transmisión en vivo y los avisos de Apoyo Técnico se operan también fuera de
una sesión, y deben sonar igual.

Estas pruebas demuestran además que la proyección es una copia y no una vía de
fuga: publica exactamente los quince eventos configurados, en su orden
canónico, y no aparece en la proyección de Moderación, que no reproduce audio.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import TOML_CANONICO
from sis_leg_backend.configuracion.modelos import ConfiguracionSonidosRecinto
from sis_leg_backend.configuracion.sonidos_recinto import (
    EVENTOS_SONIDO_RECINTO,
    MOTIVO_SONIDOS_INVALIDOS,
)
from sis_leg_backend.dominio.estado import EstadoGlobal
from sis_leg_backend.recursos import crear_recursos_aplicacion

from tests.backend.ayudas_proyecciones import (
    abrir_sesion_prueba,
    crear_entorno_proyecciones,
    sonidos_de_prueba,
)

pytestmark = pytest.mark.anyio


async def test_sin_preparar_el_recinto_recibe_los_quince_sonidos(tmp_path: Path) -> None:
    """Sin preparación activa no hay bancas ni quórum, pero sí audio."""

    entorno = crear_entorno_proyecciones(tmp_path)
    entorno.estado.preparacion_activa = None
    entorno.estado.estado_global = EstadoGlobal.SIN_PREPARAR

    recinto = await entorno.servicio.obtener_estado_recinto()

    assert recinto.estado_global is EstadoGlobal.SIN_PREPARAR
    assert recinto.filas_bancas is None
    assert recinto.sonidos.disponible is True
    assert tuple(sonido.evento for sonido in recinto.sonidos.sonidos) == EVENTOS_SONIDO_RECINTO


async def test_preparando_proyecta_los_mismos_sonidos(tmp_path: Path) -> None:
    """Preparar el recinto no cambia la configuración de audio publicada."""

    entorno = crear_entorno_proyecciones(tmp_path)

    recinto = await entorno.servicio.obtener_estado_recinto()

    assert recinto.estado_global is EstadoGlobal.PREPARANDO
    assert len(recinto.sonidos.sonidos) == len(EVENTOS_SONIDO_RECINTO)


async def test_sesion_abierta_proyecta_los_mismos_sonidos(tmp_path: Path) -> None:
    """Abrir la sesión tampoco altera el audio configurado."""

    entorno = crear_entorno_proyecciones(tmp_path)
    abrir_sesion_prueba(entorno)

    recinto = await entorno.servicio.obtener_estado_recinto()

    assert recinto.estado_global is EstadoGlobal.SESION_ABIERTA
    assert len(recinto.sonidos.sonidos) == len(EVENTOS_SONIDO_RECINTO)


async def test_los_tres_estados_publican_exactamente_la_misma_configuracion(
    tmp_path: Path,
) -> None:
    """El audio no depende del ciclo preparación/sesión: es idéntico siempre."""

    entorno = crear_entorno_proyecciones(tmp_path)

    entorno.estado.preparacion_activa = None
    entorno.estado.estado_global = EstadoGlobal.SIN_PREPARAR
    sin_preparar = (await entorno.servicio.obtener_estado_recinto()).sonidos

    entorno.estado.preparacion_activa = entorno.contexto
    entorno.estado.estado_global = EstadoGlobal.PREPARANDO
    preparando = (await entorno.servicio.obtener_estado_recinto()).sonidos

    abrir_sesion_prueba(entorno)
    con_sesion = (await entorno.servicio.obtener_estado_recinto()).sonidos

    assert sin_preparar == preparando == con_sesion


async def test_la_proyeccion_copia_ruta_y_volumen_de_cada_evento(tmp_path: Path) -> None:
    """Cada entrada viaja completa y sin mezclarse con la de otro evento."""

    entorno = crear_entorno_proyecciones(tmp_path)
    esperados = sonidos_de_prueba().sonidos

    recinto = await entorno.servicio.obtener_estado_recinto()

    proyectados = recinto.sonidos.sonidos
    assert len(proyectados) == len(esperados)
    for proyectado, esperado in zip(proyectados, esperados, strict=True):
        assert proyectado.evento == esperado.evento
        assert proyectado.ruta == esperado.ruta
        assert proyectado.volumen == esperado.volumen


async def test_una_configuracion_no_disponible_viaja_con_su_motivo(tmp_path: Path) -> None:
    """Si el TOML estaba roto al arrancar, la pantalla recibe la explicación."""

    entorno = crear_entorno_proyecciones(tmp_path)
    entorno.estado.sonidos_recinto = ConfiguracionSonidosRecinto(
        sonidos=(),
        disponible=False,
        motivo=MOTIVO_SONIDOS_INVALIDOS,
        detalle="sonidos.sesion_abierta.volumen debe estar entre 0 y 100",
    )

    recinto = await entorno.servicio.obtener_estado_recinto()

    assert recinto.sonidos.disponible is False
    assert recinto.sonidos.motivo == MOTIVO_SONIDOS_INVALIDOS
    assert recinto.sonidos.sonidos == ()


async def test_moderacion_no_recibe_la_configuracion_de_audio(tmp_path: Path) -> None:
    """Sólo la Pantalla del Recinto reproduce sonidos, así que sólo ella los ve."""

    entorno = crear_entorno_proyecciones(tmp_path)

    moderacion = await entorno.servicio.obtener_estado_moderacion()

    assert "sonidos" not in moderacion.model_dump()


async def test_el_arranque_carga_los_sonidos_en_el_estado_operativo(tmp_path: Path) -> None:
    """``crear_recursos_aplicacion`` deja el audio listo antes de cualquier preparación.

    Es la pieza que hace posible el criterio de aceptación 3: al arrancar, el
    proceso ya tiene los quince sonidos en memoria, así que el primer snapshot
    del Recinto —en ``SIN_PREPARAR``— los incluye.
    """

    ruta = tmp_path / "system.toml"
    ruta.write_text(TOML_CANONICO, encoding="utf-8")

    recursos = crear_recursos_aplicacion(ruta_configuracion=ruta)

    assert recursos.estado_operativo.estado_global is EstadoGlobal.SIN_PREPARAR
    sonidos = recursos.estado_operativo.sonidos_recinto
    assert sonidos.disponible is True
    assert tuple(sonido.evento for sonido in sonidos.sonidos) == EVENTOS_SONIDO_RECINTO


async def test_un_toml_ilegible_no_impide_arrancar(tmp_path: Path) -> None:
    """Un archivo roto degrada el audio y nada más: el backend sigue operativo."""

    recursos = crear_recursos_aplicacion(ruta_configuracion=tmp_path / "no-existe.toml")

    assert recursos.estado_operativo.sonidos_recinto.disponible is False
    assert recursos.estado_operativo.sonidos_recinto.motivo == MOTIVO_SONIDOS_INVALIDOS
    # El resto de los recursos existe igual: el arranque no quedó a medias.
    assert recursos.servicio_proyecciones is not None
