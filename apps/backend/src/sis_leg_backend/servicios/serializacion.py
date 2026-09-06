"""Punto único de serialización para las futuras mutaciones del backend."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

ResultadoMutacion = TypeVar("ResultadoMutacion")
ResultadoLectura = TypeVar("ResultadoLectura")
REGISTRO = logging.getLogger(__name__)


class EjecutorMutaciones:
    """Ejecuta de a una las operaciones que puedan cambiar estado.

    Cada instancia posee un único ``asyncio.Lock``. El ``lifespan`` crea un solo
    ejecutor junto con el estado operativo, de modo que todos los servicios del
    proceso compartirán la misma puerta de entrada a las secciones críticas.

    La exclusión abarca toda la espera de la operación recibida. Si esa operación
    lanza una excepción, ``async with`` libera igualmente el lock y la excepción
    se propaga: el llamador nunca recibe un éxito falso ni un resultado parcial
    presentado como confirmado.
    """

    def __init__(self, notificar_cambio: Callable[[], object] | None = None) -> None:
        self._exclusion = asyncio.Lock()
        self._notificar_cambio = notificar_cambio

    async def ejecutar(
        self,
        mutacion: Callable[[], Awaitable[ResultadoMutacion]],
    ) -> ResultadoMutacion:
        """Espera el turno exclusivo, ejecuta la mutación y devuelve su resultado.

        La función no decide reglas de negocio ni captura errores. Esto permite
        que servicios futuros validen y auditen dentro de la misma sección
        crítica, mientras el nivel de API transforma cualquier fallo en una
        respuesta HTTP apropiada.
        """

        async with self._exclusion:
            try:
                return await mutacion()
            finally:
                # Se publica también cuando la operación lanza. Algunos flujos
                # de fallo cerrado auditan y aplican un primer hecho antes de
                # fallar en otro posterior; ocultarlos hasta un futuro 2xx
                # dejaría REST/SSE desfasados respecto del estado real.
                if self._notificar_cambio is not None:
                    try:
                        self._notificar_cambio()
                    except Exception:
                        # La notificación no es un hecho institucional y jamás
                        # puede transformar éxito en error ni tapar la excepción
                        # original de dominio/auditoría.
                        REGISTRO.exception("Falló la notificación de proyecciones")

    async def leer_coherente(self, lectura: Callable[[], ResultadoLectura]) -> ResultadoLectura:
        """Construye una copia de lectura bajo el mismo lock funcional.

        ``lectura`` debe ser síncrona y no mutar el dominio. Mantenerla bajo la
        misma exclusión impide observar presencia, votación, palabra o
        desempate a mitad de la sección crítica que los está actualizando.
        """

        async with self._exclusion:
            return lectura()

    async def publicar_frontera_temporal(self) -> None:
        """Publica un vencimiento bajo la misma frontera que las mutaciones.

        No cambia dominio ni auditoría. El objetivo es que un stream reconstruya
        el DTO cuando el mero paso del tiempo cambia qué datos puede contener.
        """

        async with self._exclusion:
            if self._notificar_cambio is not None:
                try:
                    self._notificar_cambio()
                except Exception:
                    REGISTRO.exception("Falló la notificación de una frontera temporal")
