"""Publicación HTTP de los recursos de configuración local (WP-098).

Por qué el backend publica una imagen
-------------------------------------

Las fotografías de banca son **configuración de la instalación**, no parte del
producto: cambian cuando cambia el cuerpo legislativo y viven fuera de las
releases, junto a ``system.toml`` y ``concejales.csv``. Las cuatro SPA, en
cambio, son archivos estáticos construidos y congelados en cada release.

Si la foto viviera dentro de la SPA habría que reconstruir el frontend para
cambiarla, y cada aplicación tendría su propia copia —exactamente el problema
que WP-098 viene a eliminar—. Publicarla desde el backend resuelve las dos
cosas de una sola vez:

- hay **una** ubicación física: ``config/assets/bancas/``;
- el archivo se lee **en cada pedido**, así que reemplazarlo en disco cambia lo
  que muestran todas las superficies sin reconstruir ni redesplegar nada.

El endpoint vive bajo ``/api/v1`` porque es la ruta que Nginx ya reenvía al
backend y que las SPA ya consumen bajo mismo origen; no hace falta ninguna
regla de servidor nueva.

Qué NO hace este módulo
-----------------------

No lista el directorio, no acepta subrutas y no escribe nada. Sólo devuelve un
archivo concreto cuyo nombre pasó por la validación estricta de
``configuracion.imagenes_concejales``.
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from fastapi.responses import FileResponse

from sis_leg_backend.configuracion.errores import ErrorImagenConcejalNoDisponible
from sis_leg_backend.configuracion.imagenes_concejales import (
    DIRECTORIO_IMAGENES_CONCEJALES,
    ErrorRutaImagenInvalida,
    resolver_archivo_imagen_concejal,
    tipo_contenido_imagen,
)

enrutador_recursos = APIRouter(tags=["recursos"])

# Ruta pública del recurso. El nombre en plural describe la colección y el
# parámetro final es un nombre de archivo simple: el convertidor de ruta por
# defecto de Starlette no admite ``/``, de modo que un intento de travesía como
# ``../../etc/passwd`` ni siquiera llega a esta función, no coincide con la ruta.
RUTA_IMAGENES_CONCEJALES = "/recursos/imagenes-concejales/{nombre_archivo}"


@enrutador_recursos.get(
    RUTA_IMAGENES_CONCEJALES,
    response_class=FileResponse,
    responses={
        200: {
            "content": {"image/png": {}, "image/jpeg": {}, "image/webp": {}},
            "description": "Fotografía de banca tal como está en la configuración local.",
        },
        404: {"description": "La fotografía no está configurada o su nombre es inválido."},
    },
)
async def obtener_imagen_concejal(nombre_archivo: str) -> Response:
    """Devuelve la fotografía de banca guardada en la configuración local.

    Entradas:
        nombre_archivo: último segmento de la ``ruta_imagen`` declarada en el
            padrón, por ejemplo ``banca-01.png``. Es el **único** dato que el
            cliente controla: el directorio no es parametrizable desde la
            petición, igual que ``system.toml`` o el padrón, para que nadie
            pueda pedir la lectura de otra carpeta del servidor.

    Resultado:
        El archivo tal cual está en disco, con el ``Content-Type`` que
        corresponde a su extensión.

    Errores:
        ``ErrorImagenConcejalNoDisponible`` (HTTP 404) tanto si el nombre incumple el
        contrato como si el archivo no existe. La respuesta es deliberadamente
        la misma en los dos casos: distinguirlas permitiría averiguar qué
        archivos existen en el servidor probando nombres.

    Nota sobre caché: se responde ``no-cache`` para que el navegador revalide
    siempre. Es justamente lo que exige el criterio «sustituir el archivo se ve
    sin rebuild»: con una caché larga, la pantalla del recinto seguiría
    mostrando la foto anterior durante horas después de reemplazarla.
    """

    try:
        archivo = resolver_archivo_imagen_concejal(nombre_archivo, DIRECTORIO_IMAGENES_CONCEJALES)
    except ErrorRutaImagenInvalida as error:
        raise ErrorImagenConcejalNoDisponible(
            "La fotografía solicitada no está disponible en la configuración."
        ) from error

    return FileResponse(
        archivo,
        media_type=tipo_contenido_imagen(archivo.name),
        headers={"Cache-Control": "no-cache"},
    )
