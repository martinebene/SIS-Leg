"""Pruebas del nombre institucional configurable (WP-084).

Hasta este Work Package el nombre del cuerpo legislativo estaba escrito dentro
del componente Vue de la cabecera pública. Eso ataba el producto a una única
institución: instalarlo en otro concejo o legislatura obligaba a editar código.

Este archivo cubre las cuatro fronteras del contrato nuevo:

1. la sección ``[institucion]`` válida se carga completa y queda congelada;
2. cada forma inválida —sección ausente, clave ausente, valor vacío y valor no
   textual— produce un error de configuración claro y determinista **al
   preparar**;
3. la lectura de arranque nunca propaga un error y degrada a un rótulo neutro,
   de modo que la Pantalla del Recinto siga siendo legible en ``SIN_PREPARAR``;
4. la plantilla versionada trae un nombre genérico y no el de ninguna
   institución real.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import (
    LINEA_INSTITUCION,
    NOMBRE_INSTITUCIONAL_DE_PRUEBA,
    TOML_CANONICO,
    escribir_system_toml,
)
from sis_leg_backend.configuracion.cargar_configuracion import cargar_configuracion_sistema
from sis_leg_backend.configuracion.errores import ErrorValidacionConfiguracion
from sis_leg_backend.configuracion.identidad_institucional import (
    MOTIVO_IDENTIDAD_INVALIDA,
    exigir_identidad_institucional,
    leer_identidad_institucional,
)
from sis_leg_backend.configuracion.modelos import NOMBRE_INSTITUCIONAL_NEUTRO

RAIZ_REPOSITORIO = Path(__file__).resolve().parents[1]
RUTA_PLANTILLA_TOML = RAIZ_REPOSITORIO / "config/system.example.toml"
RUTA_CABECERA_RECINTO = RAIZ_REPOSITORIO / "apps/recinto/app/components/CabeceraRecinto.vue"


def _toml_sin_seccion_institucion() -> str:
    """Devuelve el TOML canónico sin la sección ``[institucion]``.

    Se recorta el bloque completo —encabezado y clave— en lugar de vaciar la
    clave, porque «falta la sección» y «falta el nombre» son dos fallos
    distintos y el contrato exige un mensaje distinto para cada uno.
    """

    return TOML_CANONICO.replace(f"[institucion]\n{LINEA_INSTITUCION}\n\n", "", 1)


# =============================================================================
# 1. Carga válida y congelamiento
# =============================================================================


def test_carga_el_nombre_institucional_configurado(ruta_system_toml_valido: Path) -> None:
    """El snapshot expone exactamente el nombre escrito en el archivo."""

    configuracion = cargar_configuracion_sistema(ruta_system_toml_valido)

    identidad = configuracion.identidad_institucional
    assert identidad.nombre == NOMBRE_INSTITUCIONAL_DE_PRUEBA
    assert identidad.disponible is True
    assert identidad.motivo is None


@pytest.mark.parametrize(
    "nombre",
    [
        "Concejo de Villa Sur",
        "Honorable Legislatura Provincial de la Región Continental de Nuevos Territorios",
    ],
    ids=["nombre-corto", "nombre-largo"],
)
def test_acepta_nombres_de_longitud_muy_distinta(tmp_path: Path, nombre: str) -> None:
    """El contrato no impone longitud: sólo exige texto no vacío.

    Los dos nombres son los mismos que la prueba de geometría usa en el
    navegador, de modo que el par corto/largo se ejercite en las dos capas.
    """

    ruta = escribir_system_toml(
        tmp_path / "system.toml",
        TOML_CANONICO.replace(LINEA_INSTITUCION, f'nombre = "{nombre}"'),
    )

    assert cargar_configuracion_sistema(ruta).identidad_institucional.nombre == nombre


def test_conserva_el_texto_configurado_sin_recortarlo(tmp_path: Path) -> None:
    """No hay normalización silenciosa: el valor viaja tal cual se escribió.

    Recortar espacios parecería inofensivo, pero el criterio del WP es que el
    Recinto muestre *exactamente* el valor configurado. Una normalización
    convertiría al cargador en un editor de contenido que nadie pidió.
    """

    ruta = escribir_system_toml(
        tmp_path / "system.toml",
        TOML_CANONICO.replace(LINEA_INSTITUCION, 'nombre = "  Concejo del Valle  "'),
    )

    assert cargar_configuracion_sistema(ruta).identidad_institucional.nombre == (
        "  Concejo del Valle  "
    )


def test_cambiar_el_archivo_no_altera_la_identidad_ya_cargada(tmp_path: Path) -> None:
    """El snapshot está congelado: RN-CON-07 vale también para esta sección."""

    ruta = escribir_system_toml(tmp_path / "system.toml", TOML_CANONICO)
    configuracion = cargar_configuracion_sistema(ruta)

    escribir_system_toml(
        ruta,
        TOML_CANONICO.replace(LINEA_INSTITUCION, 'nombre = "Otro Cuerpo Legislativo"'),
    )

    assert configuracion.identidad_institucional.nombre == NOMBRE_INSTITUCIONAL_DE_PRUEBA
    recargada = cargar_configuracion_sistema(ruta)
    assert recargada.identidad_institucional.nombre == "Otro Cuerpo Legislativo"
    assert configuracion.identidad_institucional.nombre == NOMBRE_INSTITUCIONAL_DE_PRUEBA


# =============================================================================
# 2. Formas inválidas: la carga estricta las rechaza
# =============================================================================


def test_falta_la_seccion_institucion(tmp_path: Path) -> None:
    """Sin sección no se puede preparar: el mensaje nombra la sección."""

    ruta = escribir_system_toml(tmp_path / "system.toml", _toml_sin_seccion_institucion())

    with pytest.raises(ErrorValidacionConfiguracion) as error:
        cargar_configuracion_sistema(ruta)
    assert "[institucion]" in str(error.value)


@pytest.mark.parametrize(
    ("literal", "descripcion"),
    [
        ("", "clave ausente"),
        ('nombre = ""', "texto vacío"),
        ('nombre = "   "', "sólo espacios"),
        ("nombre = 42", "entero"),
        ("nombre = true", "booleano"),
        ('nombre = ["Concejo"]', "lista"),
    ],
)
def test_rechaza_nombres_invalidos(tmp_path: Path, literal: str, descripcion: str) -> None:
    """Cada forma inválida falla con la clave canónica en el mensaje.

    El booleano se prueba explícitamente porque TOML lo admite en esa posición y
    porque ``nombre = true`` dejaría en la pantalla pública un rótulo absurdo si
    alguien lo aceptara por descuido.
    """

    ruta = escribir_system_toml(
        tmp_path / "system.toml",
        TOML_CANONICO.replace(LINEA_INSTITUCION, literal),
    )

    with pytest.raises(ErrorValidacionConfiguracion) as error:
        cargar_configuracion_sistema(ruta)
    assert "institucion.nombre" in str(error.value), descripcion


def test_exigir_rechaza_una_seccion_que_no_sea_tabla() -> None:
    """``institucion = "algo"`` no es una sección y se rechaza como tal."""

    with pytest.raises(ErrorValidacionConfiguracion):
        exigir_identidad_institucional({"institucion": "Concejo"})


# =============================================================================
# 3. Arranque tolerante
# =============================================================================


def test_arranque_con_archivo_inexistente_degrada_sin_excepcion(tmp_path: Path) -> None:
    """Un backend sin ``system.toml`` arranca y muestra el rótulo neutro."""

    identidad = leer_identidad_institucional(tmp_path / "no-existe.toml")

    assert identidad.disponible is False
    assert identidad.motivo == MOTIVO_IDENTIDAD_INVALIDA
    assert identidad.nombre == NOMBRE_INSTITUCIONAL_NEUTRO
    assert identidad.detalle is not None


def test_arranque_con_toml_invalido_degrada_sin_excepcion(tmp_path: Path) -> None:
    """Un archivo a medio editar no puede impedir encender la pantalla."""

    ruta = escribir_system_toml(tmp_path / "system.toml", "[institucion")

    identidad = leer_identidad_institucional(ruta)

    assert identidad.disponible is False
    assert identidad.nombre == NOMBRE_INSTITUCIONAL_NEUTRO


def test_arranque_con_seccion_invalida_degrada_sin_excepcion(tmp_path: Path) -> None:
    """La sección presente pero vacía degrada igual que un archivo roto."""

    ruta = escribir_system_toml(
        tmp_path / "system.toml",
        TOML_CANONICO.replace(LINEA_INSTITUCION, 'nombre = ""'),
    )

    identidad = leer_identidad_institucional(ruta)

    assert identidad.disponible is False
    assert identidad.nombre == NOMBRE_INSTITUCIONAL_NEUTRO


def test_arranque_con_archivo_valido_lee_el_nombre_real(ruta_system_toml_valido: Path) -> None:
    """La lectura tolerante entrega el mismo valor que la carga estricta."""

    identidad = leer_identidad_institucional(ruta_system_toml_valido)

    assert identidad.disponible is True
    assert identidad.nombre == NOMBRE_INSTITUCIONAL_DE_PRUEBA


# =============================================================================
# 4. Plantilla versionada y respaldo compartido con el frontend
# =============================================================================


def test_la_plantilla_versionada_declara_un_nombre_generico() -> None:
    """``system.example.toml`` no puede traer el nombre de una institución real.

    La plantilla es el contenido que ve la revisión en cada Pull Request y el
    punto de partida de cualquier instalación nueva. Un nombre real ahí volvería
    a acoplar el producto a un único cliente, que es justamente lo que este WP
    elimina.
    """

    configuracion = cargar_configuracion_sistema(RUTA_PLANTILLA_TOML)

    nombre = configuracion.identidad_institucional.nombre
    assert nombre == "Cuerpo Legislativo de Ciudad Ejemplo"
    assert configuracion.identidad_institucional.disponible is True


def test_la_cabecera_del_recinto_repite_el_mismo_rotulo_neutro() -> None:
    """Las dos copias del respaldo neutro dicen exactamente lo mismo.

    El backend y la Pantalla del Recinto necesitan el mismo literal —uno para
    degradar la lectura de arranque, la otra para el instante previo al primer
    snapshot— y están escritos en lenguajes distintos, así que no hay forma de
    compartir la constante sin inventar un contrato que este WP no pide. Lo que
    sí se puede evitar es que se separen en silencio: si alguien cambia una y
    olvida la otra, esta prueba lo dice.
    """

    fuente = RUTA_CABECERA_RECINTO.read_text(encoding="utf-8")

    esperado = f"const NOMBRE_INSTITUCIONAL_NEUTRO = '{NOMBRE_INSTITUCIONAL_NEUTRO}'"
    assert esperado in fuente
