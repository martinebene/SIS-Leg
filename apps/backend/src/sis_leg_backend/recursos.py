"""Recursos compartidos que existen exactamente durante el lifespan."""

import os
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI

from sis_leg_backend.configuracion.identidad_institucional import (
    leer_identidad_institucional,
)
from sis_leg_backend.configuracion.sonidos_recinto import leer_sonidos_recinto
from sis_leg_backend.dominio.estado import EstadoOperativo
from sis_leg_backend.servicios.apoyo_tecnico import (
    RUTA_MENSAJES_TECNICOS_POR_DEFECTO,
    leer_biblioteca_mensajes_tecnicos,
)
from sis_leg_backend.servicios.cliente_bridge import (
    TIMEOUT_CONTROL_POR_DEFECTO,
    ClienteControlBridge,
    error_timeout_control_invalido,
    exigir_timeout_control_valido,
)
from sis_leg_backend.servicios.preparacion import RUTA_CONFIGURACION_POR_DEFECTO
from sis_leg_backend.servicios.proyecciones import ServicioProyecciones
from sis_leg_backend.servicios.publicacion import CoordinadorPublicacion
from sis_leg_backend.servicios.serializacion import EjecutorMutaciones

NOMBRE_RECURSOS = "recursos_sis-leg"

# Variables de entorno que configuran el canal de control hacia el
# device-bridge. Se declaran como constantes porque el mensaje de error de
# WP-089 debe nombrar literalmente la variable: si el nombre viviera suelto en
# la llamada a ``os.getenv`` y en el texto del error, ambos podrían divergir.
NOMBRE_ENTORNO_URL_CONTROL_BRIDGE = "SIS_LEG_BRIDGE_CONTROL_URL"
NOMBRE_ENTORNO_TIMEOUT_CONTROL_BRIDGE = "SIS_LEG_BRIDGE_CONTROL_TIMEOUT"
URL_CONTROL_BRIDGE_POR_DEFECTO = "http://127.0.0.1:8765"


def _leer_timeout_control_bridge() -> float:
    """Traduce ``SIS_LEG_BRIDGE_CONTROL_TIMEOUT`` a una duración utilizable.

    Reglas (WP-089):

    - variable ausente: rige exactamente el default histórico de 3.0 segundos;
    - variable presente: debe ser un número finito y estrictamente mayor que
      cero, sea entero o decimal;
    - cualquier otra cosa —texto no numérico, cadena vacía, ``nan``, ``inf``,
      ``-inf``, cero o negativos— aborta el arranque.

    El punto importante es el **fail-fast**: una variable inválida no puede
    caer silenciosamente al default ni diferirse hasta el primer remapeo, que
    es justamente la operación urgente donde nadie quiere descubrir que el
    timeout del socket era ``nan``. El error se produce mientras se construyen
    los recursos, es decir durante el arranque del proceso.

    Errores:
        ``ErrorConfiguracionBridge`` nombrando la variable y el valor recibido.
    """

    valor_crudo = os.getenv(NOMBRE_ENTORNO_TIMEOUT_CONTROL_BRIDGE)
    if valor_crudo is None:
        return TIMEOUT_CONTROL_POR_DEFECTO
    try:
        # ``float`` acepta enteros y decimales, y también los literales
        # ``nan``/``inf``; por eso el resultado todavía debe pasar por la
        # validación compartida antes de considerarse una duración.
        numero = float(valor_crudo)
    except ValueError as error:
        raise error_timeout_control_invalido(
            valor_crudo,
            origen=NOMBRE_ENTORNO_TIMEOUT_CONTROL_BRIDGE,
        ) from error
    return exigir_timeout_control_valido(
        numero,
        origen=NOMBRE_ENTORNO_TIMEOUT_CONTROL_BRIDGE,
    )


@dataclass(frozen=True, slots=True)
class RecursosAplicacion:
    """Agrupa el estado único y la puerta única para modificarlo.

    El contenedor es inmutable para impedir que una ruta reemplace por accidente
    alguno de esos recursos. El estado contenido sí podrá evolucionar, pero las
    futuras mutaciones deberán hacerlo mediante ``ejecutor_mutaciones``.
    """

    estado_operativo: EstadoOperativo
    ejecutor_mutaciones: EjecutorMutaciones
    coordinador_publicacion: CoordinadorPublicacion
    servicio_proyecciones: ServicioProyecciones
    cliente_control_bridge: ClienteControlBridge
    # Ruta de la biblioteca de Apoyo Técnico vigente para *este* proceso. Se
    # conserva acá porque el CSV se lee una vez al arrancar y se reescribe en
    # cada comando REST: si la lectura y la escritura tomaran la ruta de dos
    # lugares distintos, un proceso podría leer un archivo y sobrescribir otro.
    ruta_mensajes_tecnicos: Path


def crear_recursos_aplicacion(
    *,
    ruta_mensajes_tecnicos: Path = RUTA_MENSAJES_TECNICOS_POR_DEFECTO,
    ruta_configuracion: Path = RUTA_CONFIGURACION_POR_DEFECTO,
) -> RecursosAplicacion:
    """Construye recursos nuevos y sin recuperación del estado operativo.

    Las únicas lecturas de disco son de **configuración persistente**, no de
    estado de sesión: RN-GLOBAL-03 prohíbe restaurar presencia, votaciones o
    sesión después de una caída, no impide releer un archivo de configuración.
    Son tres:

    - la biblioteca de mensajes precargados de Apoyo Técnico (WP-055);
    - los sonidos de la Pantalla del Recinto (WP-065), que deben estar
      disponibles ya en ``SIN_PREPARAR`` porque transmisión y avisos técnicos
      operan fuera de una sesión;
    - la identidad institucional (WP-084), porque la cabecera de esa misma
      pantalla muestra el nombre del cuerpo legislativo también en
      ``SIN_PREPARAR``.

    Ninguna de las tres puede impedir el arranque: un archivo inválido deja esa
    porción marcada como no disponible y degrada solamente su funcionalidad. En
    el caso de la identidad, «degradar» significa mostrar un rótulo genérico en
    lugar del nombre real; la carga estricta del momento de preparar sigue
    exigiendo la sección.
    """

    # La configuración del canal de control se valida antes que nada: si el
    # entorno está mal, conviene fallar sin haber leído archivos ni construido
    # a medias el estado del proceso.
    timeout_control_bridge = _leer_timeout_control_bridge()
    estado_operativo = EstadoOperativo()
    estado_operativo.biblioteca_mensajes_tecnicos = leer_biblioteca_mensajes_tecnicos(
        ruta_mensajes_tecnicos
    )
    estado_operativo.sonidos_recinto = leer_sonidos_recinto(ruta_configuracion)
    estado_operativo.identidad_institucional = leer_identidad_institucional(ruta_configuracion)
    coordinador = CoordinadorPublicacion()
    # La llamada ocurre todavía dentro del lock del ejecutor. Por eso el número
    # de revisión y la memoria proyectada pertenecen a la misma frontera.
    ejecutor = EjecutorMutaciones(coordinador.publicar)
    servicio_proyecciones = ServicioProyecciones(
        estado_operativo,
        ejecutor,
        coordinador,
    )
    cliente_control_bridge = ClienteControlBridge(
        url_base=os.getenv(NOMBRE_ENTORNO_URL_CONTROL_BRIDGE, URL_CONTROL_BRIDGE_POR_DEFECTO),
        timeout_segundos=timeout_control_bridge,
    )
    return RecursosAplicacion(
        estado_operativo=estado_operativo,
        ejecutor_mutaciones=ejecutor,
        coordinador_publicacion=coordinador,
        servicio_proyecciones=servicio_proyecciones,
        cliente_control_bridge=cliente_control_bridge,
        ruta_mensajes_tecnicos=ruta_mensajes_tecnicos,
    )


def guardar_recursos_aplicacion(
    aplicacion: FastAPI,
    recursos: RecursosAplicacion,
) -> None:
    """Asocia los recursos compartidos con una aplicación durante su vida útil."""

    setattr(aplicacion.state, NOMBRE_RECURSOS, recursos)


def obtener_recursos_aplicacion(aplicacion: FastAPI) -> RecursosAplicacion:
    """Devuelve el contenedor único asociado por el lifespan.

    FastAPI expone ``app.state`` como un almacén dinámico, por eso se valida el
    tipo al recuperarlo. Un acceso fuera del lifespan es un error de programación
    y se informa inmediatamente en lugar de fabricar una segunda instancia.
    """

    recursos = getattr(aplicacion.state, NOMBRE_RECURSOS, None)
    if not isinstance(recursos, RecursosAplicacion):
        raise RuntimeError("Los recursos de la aplicación no están disponibles")
    return recursos


def descartar_recursos_aplicacion(aplicacion: FastAPI) -> None:
    """Elimina la referencia a los recursos al finalizar el proceso simulado."""

    delattr(aplicacion.state, NOMBRE_RECURSOS)
