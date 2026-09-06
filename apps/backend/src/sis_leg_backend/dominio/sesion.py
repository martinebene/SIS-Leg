"""Contexto autoritativo de una sesión formal abierta (WP-008)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sis_leg_backend.dominio.preparacion import Preparacion
from sis_leg_backend.dominio.votacion import Votacion


def _crear_historial_votaciones() -> list[Votacion]:
    """Crea una lista independiente y correctamente tipada para cada sesión."""

    return []


def _crear_cola_dnis() -> list[str]:
    """Crea la lista tipada e independiente de pedidos de una sesión."""

    return []


@dataclass(slots=True)
class EstadoPalabra:
    """Conserva la cola FIFO y el único orador de una sesión.

    Los DNI son referencias al padrón congelado que vive en
    :class:`Preparacion`; no se copian concejales ni datos personales. La clase
    concentra las invariantes estructurales de palabra, mientras los servicios
    deciden presencia, auditoría y autorización bajo el serializador global.

    La cola se expone como tupla para que un consumidor pueda observarla sin
    modificarla por fuera de los métodos que preservan FIFO, unicidad y la
    exclusión entre ``esperando`` y ``en uso``.
    """

    _cola_dnis: list[str] = field(default_factory=_crear_cola_dnis)
    _orador_dni: str | None = None

    @property
    def cola_dnis(self) -> tuple[str, ...]:
        """Devuelve una vista inmutable del orden actual de pedidos."""

        return tuple(self._cola_dnis)

    @property
    def orador_dni(self) -> str | None:
        """Devuelve el DNI del orador actual, o ``None`` si no hay uno."""

        return self._orador_dni

    @property
    def primer_pedido_dni(self) -> str | None:
        """Permite auditar al próximo orador antes de retirar su pedido."""

        return self._cola_dnis[0] if self._cola_dnis else None

    def esta_esperando(self, dni: str) -> bool:
        """Indica si el DNI ya ocupa una posición en la cola."""

        return dni in self._cola_dnis

    def es_orador(self, dni: str) -> bool:
        """Indica si el DNI identifica al único orador actual."""

        return self._orador_dni == dni

    def agregar_pedido(self, dni: str) -> None:
        """Agrega al final un DNI que no espera ni usa la palabra.

        La presencia se valida en el servicio porque pertenece al contexto de
        sesión y debe resolverse antes de auditar. Llegar aquí con un DNI
        repetido representa, en cambio, un error interno de programación.
        """

        if self.es_orador(dni) or self.esta_esperando(dni):
            raise ValueError("El concejal ya espera o usa la palabra")
        self._cola_dnis.append(dni)

    def retirar_pedido(self, dni: str) -> None:
        """Retira un pedido existente sin alterar las otras posiciones."""

        try:
            self._cola_dnis.remove(dni)
        except ValueError as error:
            raise ValueError("El concejal no tiene un pedido de palabra") from error

    def otorgar_primer_pedido(self, dni_esperado: str) -> None:
        """Convierte exactamente el primer pedido auditado en orador.

        ``ServicioPalabra`` obtiene primero ``primer_pedido_dni``, persiste el
        evento correspondiente y recién entonces llama a este método. Validar
        nuevamente el DNI documenta que nunca se puede seleccionar otra banca
        ni saltar una posición FIFO por error de código.
        """

        if self._orador_dni is not None:
            raise ValueError("Debe finalizarse al orador antes de otorgar otro uso")
        if not self._cola_dnis or self._cola_dnis[0] != dni_esperado:
            raise ValueError("El DNI auditado ya no es el primer pedido")
        self._cola_dnis.pop(0)
        self._orador_dni = dni_esperado

    def finalizar_uso(self, dni_esperado: str) -> None:
        """Elimina al orador indicado sin promover a nadie de la cola."""

        if self._orador_dni != dni_esperado:
            raise ValueError("El DNI indicado no es el orador actual")
        self._orador_dni = None

    def limpiar_por_ausencia(self, dni: str) -> None:
        """Descarta pedido o uso luego de auditar la ausencia que los autoriza.

        No promueve al siguiente. Aunque las invariantes impiden que el mismo
        DNI esté en ambos lugares, limpiar defensivamente ambos estados hace
        que la consecuencia del evento de ausencia sea inequívoca.
        """

        if dni in self._cola_dnis:
            self._cola_dnis.remove(dni)
        if self._orador_dni == dni:
            self._orador_dni = None


@dataclass(frozen=True, slots=True)
class ActualizacionDatosInstitucionales:
    """Describe exactamente qué campos incluyó un PATCH institucional.

    Un texto vacío durante preparación se normaliza a ``None``, por lo que el
    valor por sí solo no alcanza para distinguir "limpiar" de "campo omitido".
    Las banderas conservan esa diferencia sin trasladar modelos Pydantic al
    dominio. El número no aparece en ``PATCH /sesion``; por eso la misma
    estructura puede reutilizarse dejando ``incluye_numero_sesion=False``.
    """

    incluye_numero_sesion: bool = False
    numero_sesion: int | None = None
    incluye_presidencia: bool = False
    presidencia: str | None = None
    incluye_secretaria_legislativa: bool = False
    secretaria_legislativa: str | None = None


@dataclass(frozen=True, slots=True)
class Sesion:
    """Representa la sesión abierta sin copiar el estado vivo de preparación.

    ``contexto_operativo`` es exactamente el objeto que existía como
    ``preparacion_activa``. La composición permite cambiar el significado
    reglamentario del ciclo sin recrear configuración, padrón, presencias,
    expiraciones ni escritor. Una vez instalada esta entidad, el estado global
    borra la referencia de preparación y esta sesión queda como único camino
    autoritativo hacia esos datos.

    ``fecha_hora_apertura`` registra cuándo se confirmó la transición formal.
    No reemplaza ``fecha_hora_inicio``, que sigue identificando el comienzo del
    conjunto de auditoría.

    ``votaciones`` conserva, en orden de apertura, las entidades creadas durante
    esta sesión. La lista puede incorporar nuevos elementos aunque la referencia
    de la sesión sea congelada; no se reemplaza ni se duplica como otra fuente
    de verdad global.

    ``palabra`` nace siempre vacío con cada nueva sesión y se descarta junto con
    esta entidad al cerrar. Allí vive la única cola y el único orador del
    proceso; ni la API ni los servicios mantienen copias paralelas.
    """

    contexto_operativo: Preparacion
    fecha_hora_apertura: datetime
    votaciones: list[Votacion] = field(default_factory=_crear_historial_votaciones)
    palabra: EstadoPalabra = field(default_factory=EstadoPalabra)

    @property
    def numero_sesion(self) -> int:
        """Devuelve el número obligatorio e inmutable de la sesión abierta."""

        numero = self.contexto_operativo.numero_sesion
        if numero is None:
            raise RuntimeError("Sesión abierta sin número de sesión")
        return numero

    @property
    def presidencia(self) -> str:
        """Devuelve la Presidencia vigente, siempre informada en sesión."""

        presidencia = self.contexto_operativo.presidencia
        if presidencia is None:
            raise RuntimeError("Sesión abierta sin Presidencia")
        return presidencia

    @property
    def secretaria_legislativa(self) -> str:
        """Devuelve la Secretaría Legislativa vigente, siempre informada."""

        secretaria = self.contexto_operativo.secretaria_legislativa
        if secretaria is None:
            raise RuntimeError("Sesión abierta sin Secretaría Legislativa")
        return secretaria
