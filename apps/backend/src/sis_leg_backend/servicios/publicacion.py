"""Revisiones volátiles y suscripciones coalescentes de las proyecciones.

Este módulo no conoce reglas de negocio ni guarda snapshots. Su única tarea es
avisar que el estado observable puede haber cambiado. Cada consumidor vuelve a
construir entonces un DTO completo y coherente desde ``EstadoOperativo``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass(eq=False, slots=True)
class SuscripcionProyeccion:
    """Espera cambios sin acumular una cola de versiones intermedias.

    El ``Event`` ocupa memoria constante. Varias publicaciones mientras un
    cliente está ocupado solo lo dejan encendido una vez; al despertar, el
    cliente toma la revisión actual y puede saltar, por ejemplo, de 100 a 107.
    """

    _coordinador: CoordinadorPublicacion
    _evento: asyncio.Event = field(default_factory=asyncio.Event)
    _cancelada: bool = False

    async def esperar_revision_superior(self, revision_conocida: int) -> int:
        """Espera hasta que exista una revisión posterior a la conocida.

        Se limpia el evento antes de comprobar nuevamente la revisión. Como no
        hay un ``await`` entre ambas instrucciones, una publicación no puede
        perderse en la clásica carrera "clear -> wait" del mismo event loop.
        """

        while not self._cancelada:
            if self._coordinador.revision > revision_conocida:
                return self._coordinador.revision
            self._evento.clear()
            if self._coordinador.revision > revision_conocida:
                return self._coordinador.revision
            await self._evento.wait()
        raise asyncio.CancelledError

    def avisar(self) -> None:
        """Despierta al suscriptor; varias llamadas se coalescen en una."""

        self._evento.set()

    def cancelar(self) -> None:
        """Libera la referencia del coordinador y cualquier espera pendiente."""

        if self._cancelada:
            return
        self._cancelada = True
        self._coordinador.eliminar_suscripcion(self)
        self._evento.set()


class CoordinadorPublicacion:
    """Mantiene la revisión de proceso y el conjunto acotado de suscriptores.

    ``revision`` no se persiste ni se confunde con el ``seq`` institucional.
    Publicar es síncrono y no realiza E/S, por lo que puede ejecutarse dentro
    del mismo lock funcional al terminar una mutación sin agregar una segunda
    frontera de concurrencia.
    """

    def __init__(self) -> None:
        self._revision = 0
        self._suscripciones: set[SuscripcionProyeccion] = set()

    @property
    def revision(self) -> int:
        """Devuelve la última revisión observable de esta vida del proceso."""

        return self._revision

    @property
    def cantidad_suscripciones(self) -> int:
        """Expone un conteo diagnóstico para verificar cleanup en pruebas."""

        return len(self._suscripciones)

    def publicar(self) -> int:
        """Avanza una revisión y despierta a todos sin construir payloads."""

        self._revision += 1
        for suscripcion in tuple(self._suscripciones):
            suscripcion.avisar()
        return self._revision

    def suscribir(self) -> SuscripcionProyeccion:
        """Registra un consumidor con memoria constante y devuelve su handle."""

        suscripcion = SuscripcionProyeccion(self)
        self._suscripciones.add(suscripcion)
        return suscripcion

    def cerrar(self) -> None:
        """Cancela todas las esperas al finalizar el lifespan del backend."""

        for suscripcion in tuple(self._suscripciones):
            suscripcion.cancelar()

    def eliminar_suscripcion(self, suscripcion: SuscripcionProyeccion) -> None:
        """Quita idempotentemente una suscripción desconectada."""

        self._suscripciones.discard(suscripcion)
