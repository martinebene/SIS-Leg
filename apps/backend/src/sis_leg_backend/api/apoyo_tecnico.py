"""Recursos REST ``/api/v1/apoyo-tecnico`` del plano técnico (WP-055).

Comandos publicados:

- ``POST   /api/v1/apoyo-tecnico/transmision``            iniciar (inmediato o con countdown);
- ``DELETE /api/v1/apoyo-tecnico/transmision``            detener;
- ``POST   /api/v1/apoyo-tecnico/avisos``                 publicar aviso;
- ``DELETE /api/v1/apoyo-tecnico/avisos/{destino}``       cancelar aviso;
- ``GET    /api/v1/apoyo-tecnico/mensajes``               listar biblioteca;
- ``POST   /api/v1/apoyo-tecnico/mensajes``               crear mensaje precargado;
- ``PUT    /api/v1/apoyo-tecnico/mensajes/{mensaje_id}``  editar mensaje precargado;
- ``DELETE /api/v1/apoyo-tecnico/mensajes/{mensaje_id}``  eliminar mensaje precargado.

Los comandos de transmisión y aviso responden ``204`` sin cuerpo: el estado
resultante llega por ``GET /api/v1/estado/tecnico`` y por el stream SSE, de
modo que no existan dos fuentes de verdad que puedan desincronizarse. Los
comandos de biblioteca sí devuelven el recurso afectado, porque el
identificador lo genera el backend y el cliente necesita conocerlo.

La traducción de errores vive en ``api/errores.py``: acá solo se declaran las
respuestas para que OpenAPI las documente.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from sis_leg_backend.api.errores import ErrorRespuesta
from sis_leg_backend.configuracion.mensajes_tecnicos import LARGO_MAXIMO_TEXTO
from sis_leg_backend.dominio.apoyo_tecnico import DestinoAvisoTecnico, MensajeTecnico
from sis_leg_backend.recursos import obtener_recursos_aplicacion
from sis_leg_backend.servicios.apoyo_tecnico import ServicioApoyoTecnico
from sis_leg_backend.servicios.proyecciones import (
    BibliotecaMensajesProyectada,
    MensajeTecnicoProyectado,
    ServicioProyecciones,
)

enrutador_apoyo_tecnico = APIRouter(prefix="/apoyo-tecnico", tags=["apoyo-tecnico"])

# Cotas superiores del contrato. No son reglas de negocio: acotan el tamaño de
# lo que puede entrar al estado en memoria y viajar en cada payload SSE.
# Una hora de cuenta regresiva y un día de aviso cubren holgadamente cualquier
# uso real del puesto técnico.
MAXIMO_CUENTA_REGRESIVA_SEGUNDOS = 3600
MAXIMO_DURACION_AVISO_SEGUNDOS = 86400

# El largo máximo del texto se reutiliza del contrato CSV en lugar de repetirlo:
# si la API aceptara textos más largos que la biblioteca, un mensaje válido en
# el body podría después no poder persistirse.

RESPUESTAS_APOYO_TECNICO: dict[int | str, dict[str, Any]] = {
    422: {
        "description": "Body inválido: texto vacío, destino desconocido o duración fuera de rango.",
    },
    503: {
        "model": ErrorRespuesta,
        "description": (
            "Indisponibilidad técnica: AUDITORIA_NO_DISPONIBLE cuando hay una "
            "preparación/sesión activa cuyo escritor está en fallo cerrado."
        ),
    },
    500: {"model": ErrorRespuesta, "description": "Fallo inesperado (ERROR_INTERNO)."},
}

RESPUESTAS_MENSAJES: dict[int | str, dict[str, Any]] = {
    422: {"description": "Body inválido: texto vacío/demasiado largo o destino desconocido."},
    404: {
        "model": ErrorRespuesta,
        "description": (
            "El identificador no pertenece a la biblioteca (MENSAJE_TECNICO_NO_EXISTENTE)."
        ),
    },
    503: {
        "model": ErrorRespuesta,
        "description": (
            "Indisponibilidad de la biblioteca: BIBLIOTECA_MENSAJES_INVALIDA cuando el CSV "
            "existe pero no pudo interpretarse, o PERSISTENCIA_MENSAJES_FALLIDA cuando la "
            "escritura atómica no pudo confirmarse."
        ),
    },
    500: {"model": ErrorRespuesta, "description": "Fallo inesperado (ERROR_INTERNO)."},
}


def _validar_texto(valor: str) -> str:
    """Normaliza y valida el texto de un aviso o mensaje precargado.

    Recorta espacios de los extremos (un texto de solo espacios es vacío) y
    rechaza saltos de línea y caracteres de control: el destino es un cartel de
    una sola línea y, además, un salto de línea rompería la legibilidad del CSV
    de la biblioteca.
    """

    limpio = valor.strip()
    if not limpio:
        raise ValueError("el texto no puede estar vacío")
    if any(caracter in limpio for caracter in "\r\n"):
        raise ValueError("el texto no puede contener saltos de línea")
    if any(ord(caracter) < 32 for caracter in limpio):
        raise ValueError("el texto no puede contener caracteres de control")
    return limpio


class SolicitudIniciarTransmision(BaseModel):
    """Body del inicio de transmisión.

    ``cuenta_regresiva_segundos`` ausente o ``null`` significa inicio
    inmediato. Es ``strict`` para que un ``"10"`` textual no se acepte por
    coerción silenciosa: el contrato exige un entero.
    """

    model_config = ConfigDict(extra="forbid")
    cuenta_regresiva_segundos: Annotated[
        int | None,
        Field(strict=True, gt=0, le=MAXIMO_CUENTA_REGRESIVA_SEGUNDOS),
    ] = None


class SolicitudPublicarAviso(BaseModel):
    """Body de la publicación de un aviso técnico.

    ``duracion_segundos`` ausente o ``null`` significa que el aviso permanece
    hasta la cancelación manual.
    """

    model_config = ConfigDict(extra="forbid")
    texto: Annotated[str, Field(strict=True, min_length=1, max_length=LARGO_MAXIMO_TEXTO)]
    destino: Literal["MODERACION", "RECINTO", "AMBOS"]
    duracion_segundos: Annotated[
        int | None,
        Field(strict=True, gt=0, le=MAXIMO_DURACION_AVISO_SEGUNDOS),
    ] = None

    @field_validator("texto")
    @classmethod
    def normalizar_texto(cls, valor: str) -> str:
        """Aplica la misma validación de texto que la biblioteca."""

        return _validar_texto(valor)


class SolicitudMensajeTecnico(BaseModel):
    """Body de alta y edición de un mensaje precargado.

    El identificador nunca viaja en el body: lo genera el backend al crear y se
    toma de la ruta al editar, de modo que un cliente no pueda reasignarlo.
    """

    model_config = ConfigDict(extra="forbid")
    texto: Annotated[str, Field(strict=True, min_length=1, max_length=LARGO_MAXIMO_TEXTO)]
    destino: Literal["MODERACION", "RECINTO", "AMBOS"]

    @field_validator("texto")
    @classmethod
    def normalizar_texto(cls, valor: str) -> str:
        """Aplica la misma validación de texto que los avisos."""

        return _validar_texto(valor)


def _crear_servicio(solicitud: Request) -> ServicioApoyoTecnico:
    """Construye el servicio sobre el estado y ejecutor únicos del proceso.

    La ruta del CSV se toma de los recursos del proceso y no de la constante
    global, para que la biblioteca que se reescribe sea siempre exactamente la
    misma que se leyó al arrancar. En producción ambas son
    ``config/apoyo-tecnico/mensajes.csv``; el harness integrado de desarrollo
    puede apuntar el proceso a un archivo aislado sin que lectura y escritura
    se separen.
    """

    recursos = obtener_recursos_aplicacion(solicitud.app)
    return ServicioApoyoTecnico(
        recursos.estado_operativo,
        recursos.ejecutor_mutaciones,
        ruta_mensajes=recursos.ruta_mensajes_tecnicos,
    )


def _mensaje_proyectado(mensaje: MensajeTecnico) -> MensajeTecnicoProyectado:
    """Copia un mensaje del dominio al DTO publicado por el contrato."""

    return MensajeTecnicoProyectado(
        mensaje_id=mensaje.mensaje_id,
        texto=mensaje.texto,
        destino=mensaje.destino,
    )


@enrutador_apoyo_tecnico.post(
    "/transmision",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=RESPUESTAS_APOYO_TECNICO,
    summary="Iniciar la transmisión de inmediato o con cuenta regresiva",
)
async def iniciar_transmision(
    solicitud: Request,
    cuerpo: SolicitudIniciarTransmision,
) -> Response:
    """Instala la intención de transmitir; el estado observable lo deriva el backend."""

    await _crear_servicio(solicitud).iniciar_transmision(cuerpo.cuenta_regresiva_segundos)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@enrutador_apoyo_tecnico.delete(
    "/transmision",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=RESPUESTAS_APOYO_TECNICO,
    summary="Detener la transmisión y volver a APAGADO",
)
async def detener_transmision(solicitud: Request) -> Response:
    """Apaga el indicador. Es idempotente si ya estaba apagado."""

    await _crear_servicio(solicitud).detener_transmision()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@enrutador_apoyo_tecnico.post(
    "/avisos",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=RESPUESTAS_APOYO_TECNICO,
    summary="Publicar un aviso técnico hacia Moderación, Recinto o ambos",
)
async def publicar_aviso(solicitud: Request, cuerpo: SolicitudPublicarAviso) -> Response:
    """Reemplaza el aviso vigente de cada destino alcanzado."""

    await _crear_servicio(solicitud).publicar_aviso(
        cuerpo.texto,
        DestinoAvisoTecnico(cuerpo.destino),
        cuerpo.duracion_segundos,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@enrutador_apoyo_tecnico.delete(
    "/avisos/{destino}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=RESPUESTAS_APOYO_TECNICO,
    summary="Cancelar el aviso vigente de un destino antes de su vencimiento",
)
async def cancelar_aviso(
    solicitud: Request,
    destino: Literal["MODERACION", "RECINTO", "AMBOS"],
) -> Response:
    """Retira el aviso de las ranuras alcanzadas. Es idempotente."""

    await _crear_servicio(solicitud).cancelar_aviso(DestinoAvisoTecnico(destino))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@enrutador_apoyo_tecnico.get(
    "/mensajes",
    response_model=BibliotecaMensajesProyectada,
    responses=RESPUESTAS_MENSAJES,
    summary="Listar la biblioteca de mensajes precargados",
)
async def listar_mensajes(solicitud: Request) -> BibliotecaMensajesProyectada:
    """Devuelve la misma biblioteca que publica ``GET /api/v1/estado/tecnico``."""

    biblioteca = await _crear_servicio(solicitud).obtener_biblioteca()
    return ServicioProyecciones.proyectar_biblioteca(biblioteca)


@enrutador_apoyo_tecnico.post(
    "/mensajes",
    status_code=status.HTTP_201_CREATED,
    response_model=MensajeTecnicoProyectado,
    responses=RESPUESTAS_MENSAJES,
    summary="Crear un mensaje precargado y persistirlo en el CSV",
)
async def crear_mensaje(
    solicitud: Request,
    cuerpo: SolicitudMensajeTecnico,
) -> MensajeTecnicoProyectado:
    """Persiste primero en disco y devuelve el identificador estable generado."""

    mensaje = await _crear_servicio(solicitud).crear_mensaje(
        cuerpo.texto,
        DestinoAvisoTecnico(cuerpo.destino),
    )
    return _mensaje_proyectado(mensaje)


@enrutador_apoyo_tecnico.put(
    "/mensajes/{mensaje_id}",
    response_model=MensajeTecnicoProyectado,
    responses=RESPUESTAS_MENSAJES,
    summary="Editar el texto y el destino de un mensaje precargado",
)
async def actualizar_mensaje(
    solicitud: Request,
    mensaje_id: str,
    cuerpo: SolicitudMensajeTecnico,
) -> MensajeTecnicoProyectado:
    """Conserva el identificador y la posición del mensaje editado."""

    mensaje = await _crear_servicio(solicitud).actualizar_mensaje(
        mensaje_id,
        cuerpo.texto,
        DestinoAvisoTecnico(cuerpo.destino),
    )
    return _mensaje_proyectado(mensaje)


@enrutador_apoyo_tecnico.delete(
    "/mensajes/{mensaje_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=RESPUESTAS_MENSAJES,
    summary="Eliminar un mensaje precargado de la biblioteca",
)
async def eliminar_mensaje(solicitud: Request, mensaje_id: str) -> Response:
    """Rechaza un identificador desconocido en lugar de simular un borrado."""

    await _crear_servicio(solicitud).eliminar_mensaje(mensaje_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
