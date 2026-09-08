"""Contrato, validación y lectura del nombre institucional configurable (WP-084).

Qué resuelve este módulo
------------------------
Hasta WP-084 la Pantalla del Recinto mostraba el nombre del cuerpo legislativo
escrito directamente en el componente Vue. Eso ataba el producto a una única
institución: instalarlo en otro concejo o legislatura obligaba a editar código.

``config/system.toml`` incorpora por eso una sección ``[institucion]`` con una
única clave obligatoria:

.. code-block:: toml

    [institucion]
    nombre = "Cuerpo Legislativo de Ciudad Ejemplo"

Este módulo es el único lugar donde se interpreta esa sección. Ofrece las dos
operaciones que ya usaba la sección ``[sonidos]`` de WP-065, y por el mismo
motivo:

- :func:`exigir_identidad_institucional` valida la sección dentro de un TOML ya
  parseado. La usa ``cargar_configuracion_sistema``, de modo que una sección
  ausente o inválida impide **preparar el recinto**, igual que un ``quorum``
  inválido. Esa es la semántica histórica: la configuración funcional se valida
  al preparar y queda congelada (RN-CON-07 y DT-010).
- :func:`leer_identidad_institucional` lee el archivo por su cuenta al
  **arrancar** el backend y nunca propaga un error.

Por qué hay una lectura tolerante al arrancar
---------------------------------------------
El Recinto debe mostrar el nombre institucional también en ``SIN_PREPARAR``,
que es el estado en el que arranca el proceso y en el que todavía no hubo
ninguna preparación que cargue la configuración completa. Si esa lectura
temprana pudiera fallar, un ``system.toml`` a medio editar convertiría una
pantalla en reposo en un error, justo cuando nadie está operando el sistema y
nadie puede corregirlo.

Por eso, cuando el archivo no existe, no es TOML válido o la sección no cumple
el contrato, se devuelve :data:`NOMBRE_INSTITUCIONAL_NEUTRO` —un rótulo
genérico que no nombra ninguna institución concreta— junto con el motivo y el
detalle del problema. La degradación es visible en la pantalla (aparece el
rótulo neutro en lugar del nombre real) pero no rompe nada, y la carga estricta
del momento de preparar sigue exigiendo la sección.

Es exactamente el criterio que ya aplican la biblioteca de mensajes de Apoyo
Técnico (WP-055) y los sonidos del Recinto (WP-065).

Por qué la sección está en español
----------------------------------
Las secciones aprobadas por WP-003 (``session``, ``room``, ``timers``…) están
en inglés y renombrarlas rompería instalaciones. Esta sección es nueva y no
arrastra compatibilidad, así que aplica la regla general de DEC-001:
identificadores propios en español.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, cast

from sis_leg_backend.configuracion.errores import (
    ErrorConfiguracion,
    ErrorValidacionConfiguracion,
)
from sis_leg_backend.configuracion.modelos import (
    NOMBRE_INSTITUCIONAL_NEUTRO,
    IdentidadInstitucional,
)

NOMBRE_SECCION = "institucion"
"""Nombre de la sección del TOML que declara la identidad institucional."""

CLAVE_NOMBRE = "nombre"
"""Única clave obligatoria de la sección."""

MOTIVO_IDENTIDAD_INVALIDA = "IDENTIDAD_INSTITUCIONAL_INVALIDA"
"""Código estable publicado cuando la identidad no pudo leerse al arrancar.

Es un código y no un texto libre para que quien preste soporte pueda
reconocer la situación sin depender de la redacción del mensaje.
"""


def exigir_identidad_institucional(datos: dict[str, Any]) -> IdentidadInstitucional:
    """Valida la sección ``[institucion]`` de un TOML ya parseado.

    Entradas:
        datos: diccionario completo devuelto por ``tomllib``.

    Resultado:
        Una :class:`IdentidadInstitucional` disponible, con el ``nombre``
        exactamente como fue configurado. No se recortan espacios ni se
        normaliza el texto: el Recinto debe mostrar el valor configurado tal
        cual, y una normalización silenciosa sería un cambio de contenido que
        nadie pidió.

    Errores:
        ``ErrorValidacionConfiguracion`` si falta la sección, si falta la clave
        ``nombre``, si su valor no es texto o si es un texto vacío o compuesto
        sólo por espacios. El mensaje nombra la clave canónica completa
        (``institucion.nombre``) para que corregir el archivo sea inmediato.
    """

    seccion = datos.get(NOMBRE_SECCION)
    if not isinstance(seccion, dict):
        raise ErrorValidacionConfiguracion(f"falta la sección [{NOMBRE_SECCION}]")
    seccion_tipada = cast(dict[str, Any], seccion)

    clave = f"{NOMBRE_SECCION}.{CLAVE_NOMBRE}"
    valor = seccion_tipada.get(CLAVE_NOMBRE)
    # ``isinstance(valor, str)`` descarta también el booleano y el entero que
    # TOML admite en esa posición: `nombre = true` no es un nombre de
    # institución, y aceptarlo dejaría un rótulo absurdo en la pantalla pública.
    if not isinstance(valor, str) or not valor.strip():
        raise ErrorValidacionConfiguracion(f"{clave} debe ser un texto no vacío")

    return IdentidadInstitucional(nombre=valor)


def leer_identidad_institucional(ruta: Path) -> IdentidadInstitucional:
    """Lee la identidad al arrancar el backend sin poder impedir el arranque.

    Entradas:
        ruta: ubicación de ``system.toml``.

    Resultado:
        La identidad vigente. Si el archivo no existe, no es TOML válido o la
        sección no cumple el contrato, devuelve
        :data:`NOMBRE_INSTITUCIONAL_NEUTRO` con ``disponible=False`` y el
        detalle del problema, de modo que la Pantalla del Recinto siga
        mostrando un rótulo institucional legible en ``SIN_PREPARAR``.

    Efectos:
        Ninguno fuera de la lectura del archivo. Nunca escribe ni corrige el
        TOML: un archivo inválido lo corrige una persona.
    """

    try:
        contenido = ruta.read_text(encoding="utf-8")
        datos = tomllib.loads(contenido)
        return exigir_identidad_institucional(datos)
    except (OSError, tomllib.TOMLDecodeError, ErrorConfiguracion) as error:
        return IdentidadInstitucional(
            nombre=NOMBRE_INSTITUCIONAL_NEUTRO,
            disponible=False,
            motivo=MOTIVO_IDENTIDAD_INVALIDA,
            detalle=f"no se pudo leer la identidad institucional de {ruta}: {error}",
        )
