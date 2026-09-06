"""Construcción y ciclo de vida de la aplicación FastAPI."""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from sis_leg_backend.api.apoyo_tecnico import enrutador_apoyo_tecnico
from sis_leg_backend.api.entradas import enrutador_entradas
from sis_leg_backend.api.errores import registrar_manejadores_errores
from sis_leg_backend.api.estado import enrutador_estado
from sis_leg_backend.api.orden_del_dia import enrutador_orden_del_dia
from sis_leg_backend.api.palabra import enrutador_palabra
from sis_leg_backend.api.preparacion import enrutador_preparacion
from sis_leg_backend.api.remapeos import enrutador_remapeos
from sis_leg_backend.api.salud import enrutador_salud
from sis_leg_backend.api.sesion import enrutador_sesion
from sis_leg_backend.api.votaciones import enrutador_votaciones
from sis_leg_backend.recursos import (
    crear_recursos_aplicacion,
    descartar_recursos_aplicacion,
    guardar_recursos_aplicacion,
)
from sis_leg_backend.servicios.apoyo_tecnico import (
    RUTA_MENSAJES_TECNICOS_POR_DEFECTO,
    ServicioApoyoTecnico,
)
from sis_leg_backend.servicios.fronteras_temporales import ServicioFronterasTemporales

REGISTRO = logging.getLogger(__name__)

# Clave bajo la que ``crear_aplicacion`` deja la ruta de la biblioteca técnica
# para que el lifespan la lea. Vive en ``app.state`` y no en una variable de
# módulo para que dos aplicaciones creadas en el mismo proceso —habitual en las
# pruebas— no se pisen entre sí.
NOMBRE_RUTA_MENSAJES_TECNICOS = "ruta_mensajes_tecnicos_sis-leg"


@asynccontextmanager
async def ciclo_vida(aplicacion: FastAPI) -> AsyncGenerator[None]:
    """Crea al arrancar y descarta al detener los recursos únicos del proceso.

    No se recupera estado operativo de ningún almacenamiento: cada entrada al
    contexto representa un arranque limpio en ``SIN_PREPARAR``. La ruta de la
    biblioteca de Apoyo Técnico se toma de ``aplicacion.state`` cuando quien
    creó la aplicación la fijó explícitamente; si no, rige el valor productivo.
    """

    recursos = crear_recursos_aplicacion(
        ruta_mensajes_tecnicos=getattr(
            aplicacion.state,
            NOMBRE_RUTA_MENSAJES_TECNICOS,
            RUTA_MENSAJES_TECNICOS_POR_DEFECTO,
        )
    )
    guardar_recursos_aplicacion(aplicacion, recursos)
    # El servicio técnico no guarda estado propio, así que esta instancia del
    # lifespan y la que construye cada request comparten exactamente el mismo
    # estado operativo y el mismo ejecutor. Se crea acá únicamente para que el
    # temporizador pueda cerrar con un ``FIN`` durable el aviso de Recinto que
    # vence solo (WP-078), sin que el temporizador conozca el plano técnico.
    servicio_apoyo_tecnico = ServicioApoyoTecnico(
        recursos.estado_operativo,
        recursos.ejecutor_mutaciones,
        ruta_mensajes=recursos.ruta_mensajes_tecnicos,
    )
    fronteras = ServicioFronterasTemporales(
        recursos.servicio_proyecciones,
        recursos.ejecutor_mutaciones,
        recursos.coordinador_publicacion,
        cerrar_marcadores_vencidos=servicio_apoyo_tecnico.cerrar_marcadores_recinto_vencidos,
    )
    tarea_fronteras = asyncio.create_task(fronteras.ejecutar())
    try:
        yield
    finally:
        tarea_fronteras.cancel()
        with suppress(asyncio.CancelledError):
            await tarea_fronteras
        recursos.coordinador_publicacion.cerrar()
        descartar_recursos_aplicacion(aplicacion)


async def manejar_error_interno(solicitud: Request, error: Exception) -> JSONResponse:
    """Convierte una excepción inesperada en un fallo HTTP estable y discreto.

    El detalle completo queda en el registro técnico para diagnóstico, pero no
    se devuelve al cliente porque podría revelar información interna. Mantener
    la excepción como error impide que una futura mutación fallida sea comunicada
    como exitosa.
    """

    REGISTRO.exception(
        "Error interno no controlado durante %s %s",
        solicitud.method,
        solicitud.url.path,
        exc_info=error,
    )
    return JSONResponse(
        status_code=500,
        content={
            "codigo": "ERROR_INTERNO",
            "mensaje": "Ocurrió un error interno.",
        },
    )


def crear_aplicacion(*, ruta_mensajes_tecnicos: Path | None = None) -> FastAPI:
    """Construye una aplicación aislada y testeable con su API versionada.

    Entradas:
        ruta_mensajes_tecnicos: ubicación del CSV de mensajes precargados de
            Apoyo Técnico para este proceso. Omitirla —lo que hace siempre el
            arranque productivo de ``sis_leg_backend.main``— deja el valor
            canónico ``config/apoyo-tecnico/mensajes.csv``.

            Existe únicamente para que el harness integrado de desarrollo pueda
            ejercitar el CRUD real contra un archivo temporal, sin escribir
            jamás sobre la biblioteca operativa de quien ejecuta las pruebas
            (WP-073, criterio 15). Es deliberadamente el único archivo runtime
            reubicable: configuración, padrón y mapeo físico siguen resolviendo
            a sus rutas canónicas y ninguna prueba puede desviarlas.

    Resultado:
        Aplicación FastAPI con REST, SSE, OpenAPI y su ciclo de vida propio.
    """

    aplicacion = FastAPI(
        title="SIS-Leg Backend",
        lifespan=ciclo_vida,
    )
    if ruta_mensajes_tecnicos is not None:
        # Se guarda en ``state`` porque el lifespan recibe la aplicación y no
        # los argumentos de esta función: es la vía que FastAPI ofrece para que
        # quien construye la aplicación le pase datos a su ciclo de vida.
        setattr(aplicacion.state, NOMBRE_RUTA_MENSAJES_TECNICOS, ruta_mensajes_tecnicos)
    aplicacion.add_exception_handler(Exception, manejar_error_interno)
    # Los manejadores por tipo traducen los errores de dominio/técnicos a las
    # respuestas estables del contrato antes de llegar al genérico anterior.
    registrar_manejadores_errores(aplicacion)
    aplicacion.include_router(enrutador_salud, prefix="/api/v1")
    aplicacion.include_router(enrutador_preparacion, prefix="/api/v1")
    aplicacion.include_router(enrutador_sesion, prefix="/api/v1")
    aplicacion.include_router(enrutador_votaciones, prefix="/api/v1")
    aplicacion.include_router(enrutador_entradas, prefix="/api/v1")
    aplicacion.include_router(enrutador_orden_del_dia, prefix="/api/v1")
    aplicacion.include_router(enrutador_palabra, prefix="/api/v1")
    aplicacion.include_router(enrutador_estado, prefix="/api/v1")
    aplicacion.include_router(enrutador_remapeos, prefix="/api/v1")
    aplicacion.include_router(enrutador_apoyo_tecnico, prefix="/api/v1")
    return aplicacion
