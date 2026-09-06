"""Paquete de configuración y padrón del backend (WP-003).

Expone públicamente la carga, validación y congelamiento de
``config/system.toml`` y ``config/concejales.csv``:

- ``cargar_configuracion_sistema`` y ``cargar_padron_concejales`` son las dos
  operaciones que usará la futura preparación (WP-005);
- ``cargar_mensajes_tecnicos`` y ``guardar_mensajes_tecnicos`` administran la
  biblioteca CSV de Apoyo Técnico incorporada por WP-055, único archivo de
  ``config`` que el backend escribe;
- ``leer_sonidos_recinto`` relee al arrancar la sección ``[sonidos]`` de
  WP-065, porque la Pantalla del Recinto necesita esa configuración incluso en
  ``SIN_PREPARAR``;
- los modelos y errores se reexportan aquí para que el resto del sistema
  importe desde este paquete sin conocer su estructura interna.
"""

from __future__ import annotations

from sis_leg_backend.configuracion.cargar_configuracion import cargar_configuracion_sistema
from sis_leg_backend.configuracion.cargar_padron import cargar_padron_concejales
from sis_leg_backend.configuracion.errores import (
    ErrorConfiguracion,
    ErrorMensajesTecnicosInvalido,
    ErrorPadronInvalido,
    ErrorTomlInvalido,
    ErrorValidacionConfiguracion,
)
from sis_leg_backend.configuracion.mensajes_tecnicos import (
    cargar_mensajes_tecnicos,
    guardar_mensajes_tecnicos,
)
from sis_leg_backend.configuracion.modelos import (
    Concejal,
    ConfiguracionSistema,
    ConfiguracionSonidosRecinto,
    Padron,
    SonidoRecinto,
)
from sis_leg_backend.configuracion.sonidos_recinto import (
    EVENTOS_SONIDO_RECINTO,
    exigir_sonidos_recinto,
    leer_sonidos_recinto,
    validar_assets_sonidos,
)

__all__ = [
    "cargar_configuracion_sistema",
    "cargar_mensajes_tecnicos",
    "cargar_padron_concejales",
    "exigir_sonidos_recinto",
    "guardar_mensajes_tecnicos",
    "leer_sonidos_recinto",
    "validar_assets_sonidos",
    "EVENTOS_SONIDO_RECINTO",
    "ErrorConfiguracion",
    "ErrorMensajesTecnicosInvalido",
    "ErrorPadronInvalido",
    "ErrorTomlInvalido",
    "ErrorValidacionConfiguracion",
    "Concejal",
    "ConfiguracionSistema",
    "ConfiguracionSonidosRecinto",
    "Padron",
    "SonidoRecinto",
]
