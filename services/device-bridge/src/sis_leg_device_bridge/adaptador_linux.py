# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportOptionalMemberAccess=false
# pyright: reportInvalidTypeForm=false

"""Adaptador de hardware Linux para captura de eventos físicos mediante evdev.

Este módulo desacopla el acceso a los descriptores de `/dev/input/event*` del
resto del servicio mediante la abstracción `AdaptadorEntradaFisica`.

Responsabilidades:
1. `AdaptadorEvdevLinux`: Implementación concreta basada en `evdev` para Linux Mint / Linux.
   - Enumera dispositivos con `evdev.list_devices()`.
   - Abre únicamente candidatos que posean la capacidad `EV_KEY`.
   - Extrae metadatos y genera el fingerprint canónico.
   - Lee eventos en modo no bloqueante.
   - FILTRO ESTRICTO DE KEYDOWN: Solo emite eventos cuando `event.type == EV_KEY` y
     `event.value == 1`. Ignora `keyup` (`value == 0`) y repeat/hold (`value == 2`).
   - Detecta desconexiones físicas (cuando `dev.read()` lanza `OSError` por `ENODEV`)
     y limpia descriptores.
   - CAPTURA EXCLUSIVA (WP-075): puede tomar un dispositivo en forma exclusiva mediante
     `InputDevice.grab()` (`EVIOCGRAB`). Mientras un dispositivo está tomado así, ninguna
     otra aplicación del sistema (escritorio, navegador, terminal) recibe sus pulsaciones.
     La liberación se hace con `InputDevice.ungrab()`.
2. `AdaptadorFalso`: Implementación simulada en memoria para pruebas unitarias deterministas
   en entornos de CI sin hardware real ni permisos especiales.

Sobre la exclusividad conviene recordar dos reglas del contrato oficial de `python-evdev`:

- solo un proceso puede sostener el `grab()` de un dispositivo; si otro ya lo tomó, la
  llamada falla con `OSError`;
- liberar un dispositivo que no está tomado también falla con `OSError`.

Por eso el adaptador lleva un registro propio de qué rutas están tomadas y expone
operaciones idempotentes desde la perspectiva del bridge: adquirir dos veces no vuelve a
llamar a `grab()` y liberar dos veces no vuelve a llamar a `ungrab()`.

La decisión de *qué* dispositivos merecen exclusividad no pertenece a este módulo: el
servicio solo pide capturar los fingerprints del mapping efectivo, de modo que el teclado
y el mouse del moderador nunca quedan secuestrados.
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass, replace
from typing import Any, Protocol

try:
    import evdev
    from evdev import ecodes
except ImportError:  # pragma: no cover
    # Permite importar y utilizar AdaptadorFalso en entornos donde evdev no estuviera presente
    evdev = None  # type: ignore[assignment]
    ecodes = None  # type: ignore[assignment]

from sis_leg_device_bridge.fingerprint import construir_fingerprint_linux
from sis_leg_device_bridge.modelos import EventoTeclaFisica

logger = logging.getLogger(__name__)


class ErrorDispositivoDesconectado(Exception):
    """Excepción lanzada cuando un dispositivo físico se desconecta o su descriptor se invalida."""


class ErrorExclusividadNoDisponible(Exception):
    """Excepción lanzada cuando no se puede tomar un dispositivo en forma exclusiva.

    Se produce, por ejemplo, cuando otro proceso ya sostiene el `EVIOCGRAB` del mismo
    dispositivo o cuando el descriptor dejó de ser válido. El servicio la trata como una
    condición fail-safe: el dispositivo afectado no despacha pulsaciones funcionales hasta
    conseguir la exclusividad.
    """


@dataclass
class DispositivoFisico:
    """Información y manejador de un dispositivo de entrada abierto.

    Atributos:
        ruta: Ruta en el sistema de archivos (ej: '/dev/input/event1').
        fingerprint: Fingerprint canónico persistente derivado del hardware.
        nombre: Nombre descriptivo del hardware (ej: 'USB Keyboard').
        manejador: Instancia subyacente (ej: InputDevice de evdev o fake).
    """

    ruta: str
    fingerprint: str
    nombre: str
    manejador: Any = None


class AdaptadorEntradaFisica(Protocol):
    """Protocolo que desacopla la lectura de hardware físico del bridge."""

    def descubrir_dispositivos(self) -> list[DispositivoFisico]:
        """Escanea y abre los dispositivos de entrada compatibles disponibles."""
        ...

    def leer_eventos(self, dispositivo: DispositivoFisico) -> list[EventoTeclaFisica]:
        """Lee los eventos pendientes de un dispositivo abierto.

        Raises:
            ErrorDispositivoDesconectado: Si el dispositivo fue desconectado.
        """
        ...

    def descartar_eventos_pendientes(self, dispositivo: DispositivoFisico | None = None) -> int:
        """Drena y descarta eventos pendientes para evitar replay tardío."""
        ...

    def adquirir_exclusividad(self, dispositivo: DispositivoFisico) -> None:
        """Toma el dispositivo en forma exclusiva para este proceso.

        Debe ser idempotente: pedirla dos veces sobre el mismo dispositivo no repite la
        llamada al sistema operativo.

        Raises:
            ErrorExclusividadNoDisponible: Si no puede adquirirse la exclusividad.
        """
        ...

    def liberar_exclusividad(self, dispositivo: DispositivoFisico) -> None:
        """Devuelve el dispositivo al resto del sistema.

        Debe ser idempotente y no debe propagar errores: liberar algo que no estaba tomado
        es una operación válida desde la perspectiva del bridge.
        """
        ...

    def tiene_exclusividad(self, dispositivo: DispositivoFisico) -> bool:
        """Indica si este proceso sostiene actualmente la exclusividad del dispositivo."""
        ...

    def cerrar_dispositivo(self, dispositivo: DispositivoFisico) -> None:
        """Cierra el descriptor asociado al dispositivo, liberando antes su exclusividad."""
        ...

    def cerrar_todo(self) -> None:
        """Cierra todos los descriptores abiertos, liberando antes sus exclusividades."""
        ...


class AdaptadorEvdevLinux:
    """Adaptador real para Linux basado en la librería evdev."""

    def __init__(self) -> None:
        if evdev is None:  # pragma: no cover
            raise RuntimeError(
                "La librería 'evdev' no está disponible. Verifique que esté instalada bajo Linux."
            )
        self._dispositivos_abiertos: dict[str, evdev.InputDevice] = {}
        # Trazabilidad local de la exclusividad: contiene las rutas cuyo `grab()` fue
        # aceptado por el kernel y todavía no fue liberado por este proceso.
        self._dispositivos_exclusivos: set[str] = set()

    def descubrir_dispositivos(self) -> list[DispositivoFisico]:
        """Lista las rutas /dev/input/event* y abre aquellas con capacidad EV_KEY."""
        candidatos: list[DispositivoFisico] = []
        try:
            rutas = evdev.list_devices()
        except PermissionError as exc:
            logger.error(
                "Permiso denegado en /dev/input: %s. "
                "Asegúrese de pertenecer al grupo 'input' o configurar udev.",
                exc,
            )
            return []
        except Exception as exc:
            logger.warning("Error al listar dispositivos /dev/input: %s", exc)
            return []

        for ruta in rutas:
            # Si ya lo tenemos abierto y sigue activo, no lo abrimos de nuevo
            if ruta in self._dispositivos_abiertos:
                continue

            try:
                dev = evdev.InputDevice(ruta)
            except PermissionError as exc:
                logger.warning("Permiso denegado al abrir %s: %s", ruta, exc)
                continue
            except (OSError, FileNotFoundError) as exc:
                logger.debug("No se pudo abrir %s: %s", ruta, exc)
                continue

            # Verificar si el dispositivo admite pulsaciones de teclas (EV_KEY)
            try:
                capacidades = dev.capabilities()
            except Exception as exc:
                logger.debug("No se pudieron leer capacidades de %s: %s", ruta, exc)
                with contextlib.suppress(Exception):
                    dev.close()
                continue

            tiene_teclas = ecodes.EV_KEY in capacidades or 1 in capacidades

            if not tiene_teclas:
                # Ignoramos dispositivos sin teclas (como ratones sin botones, acelerómetros, etc.)
                with contextlib.suppress(Exception):
                    dev.close()
                continue

            # Extraemos metadatos para construir el fingerprint persistente
            info = dev.info
            vendor = info.vendor
            product = info.product
            version = info.version
            phys = dev.phys or ""
            uniq = dev.uniq or ""
            name = dev.name or ""

            fp = construir_fingerprint_linux(
                vendor=vendor,
                product=product,
                version=version,
                phys=phys,
                uniq=uniq,
                name=name,
            )

            self._dispositivos_abiertos[ruta] = dev
            candidatos.append(
                DispositivoFisico(
                    ruta=ruta,
                    fingerprint=fp,
                    nombre=name,
                    manejador=dev,
                )
            )

            logger.info(
                "Dispositivo detectado en %s: '%s' [fingerprint: %s]",
                ruta,
                name,
                fp,
            )

        return candidatos

    def leer_eventos(self, dispositivo: DispositivoFisico) -> list[EventoTeclaFisica]:
        """Lee eventos de evdev en modo no bloqueante y filtra estrictamente keydown."""
        dev = self._dispositivos_abiertos.get(dispositivo.ruta)
        if dev is None:
            return []

        eventos_resultado: list[EventoTeclaFisica] = []

        try:
            # dev.read() devuelve un generador de eventos disponibles en el búfer
            for evento in dev.read():
                # Filtrar solo eventos de tipo tecla
                if evento.type != ecodes.EV_KEY:
                    continue

                # REGLA CRÍTICA DE KEYDOWN:
                # evento.value == 1 -> bajada (keydown)
                # evento.value == 0 -> subida (keyup)
                # evento.value == 2 -> repetición/autorepeat (hold)
                if evento.value != 1:
                    continue

                # Resolver nombre textual de la tecla
                nombre_tecla = ""
                codigo_o_lista = ecodes.KEY.get(evento.code)
                if isinstance(codigo_o_lista, list):
                    nombre_tecla = str(codigo_o_lista[0])
                elif isinstance(codigo_o_lista, str):
                    nombre_tecla = codigo_o_lista
                else:
                    nombre_tecla = str(evento.code)

                eventos_resultado.append(
                    EventoTeclaFisica(
                        fingerprint=dispositivo.fingerprint,
                        codigo_tecla=evento.code,
                        nombre_tecla=nombre_tecla,
                        es_bajada=True,
                        descripcion_dispositivo=dispositivo.nombre,
                        # El descriptor de origen viaja con el evento porque la
                        # exclusividad la concede el kernel a esta ruta concreta y no al
                        # fingerprint: el servicio necesita saber por dónde entró la
                        # pulsación para decidir si está autorizada (WP-082).
                        ruta_dispositivo=dispositivo.ruta,
                    )
                )

        except BlockingIOError:
            # No hay eventos disponibles en este momento
            return []
        except OSError as exc:
            # Desconexión física del hardware o fallo del descriptor (ej: ENODEV)
            logger.warning(
                "Dispositivo en %s desconectado o error de lectura: %s",
                dispositivo.ruta,
                exc,
            )
            self.cerrar_dispositivo(dispositivo)
            raise ErrorDispositivoDesconectado(
                f"Dispositivo {dispositivo.ruta} ({dispositivo.nombre}) desconectado: {exc}"
            ) from exc

        return eventos_resultado

    def descartar_eventos_pendientes(self, dispositivo: DispositivoFisico | None = None) -> int:
        """Drena y descarta todos los eventos pendientes en los descriptores evdev.

        Se utiliza tras un fallo de transporte o timeout para evitar que los eventos
        físicos acumulados en los búferes del kernel durante el bloqueo se transmitan
        tardíamente en ráfaga cuando el backend vuelva a responder.

        Args:
            dispositivo: Dispositivo específico a purgar o None para purgar todos.

        Returns:
            Cantidad total de eventos físicos leídos y descartados.
        """
        if dispositivo is not None:
            dev = self._dispositivos_abiertos.get(dispositivo.ruta)
            dispositivos = [dev] if dev is not None else []
        else:
            dispositivos = list(self._dispositivos_abiertos.values())

        total_descartados = 0
        for dev in dispositivos:
            try:
                for _ in dev.read():
                    total_descartados += 1
            except BlockingIOError:
                # Búfer vacío, comportamiento normal cuando no hay eventos pendientes
                continue
            except OSError as exc:
                logger.debug(
                    "Error drenando búfer de %s: %s",
                    getattr(dev, "path", "desconocido"),
                    exc,
                )
                continue

        return total_descartados

    def adquirir_exclusividad(self, dispositivo: DispositivoFisico) -> None:
        """Toma el dispositivo con `EVIOCGRAB` para que nadie más reciba sus pulsaciones.

        Es la operación que impide que un numpad de banca escriba en el escritorio o en el
        navegador de Moderación. Solo un proceso puede sostener el grab de un dispositivo,
        así que un segundo intento externo fallará mientras el bridge lo conserve.

        Args:
            dispositivo: Dispositivo ya descubierto y abierto por este adaptador.

        Raises:
            ErrorExclusividadNoDisponible: Si el descriptor no existe o el kernel rechaza
                la adquisición (por ejemplo, si otro proceso ya lo tomó).
        """
        if dispositivo.ruta in self._dispositivos_exclusivos:
            # Idempotencia: ya la tenemos, no repetimos la llamada al sistema operativo.
            return

        dev = self._dispositivos_abiertos.get(dispositivo.ruta)
        if dev is None:
            raise ErrorExclusividadNoDisponible(
                f"No hay descriptor abierto para {dispositivo.ruta}; "
                "no puede adquirirse la captura exclusiva."
            )

        try:
            dev.grab()
        except Exception as exc:
            raise ErrorExclusividadNoDisponible(
                f"No se pudo adquirir la captura exclusiva de {dispositivo.ruta} "
                f"('{dispositivo.nombre}'): {exc}"
            ) from exc

        self._dispositivos_exclusivos.add(dispositivo.ruta)
        logger.info(
            "Captura exclusiva adquirida en %s ('%s'). "
            "El dispositivo queda dedicado a SIS-Leg mientras el bridge esté activo.",
            dispositivo.ruta,
            dispositivo.nombre,
        )

    def liberar_exclusividad(self, dispositivo: DispositivoFisico) -> None:
        """Devuelve el dispositivo al resto del sistema con `ungrab()`.

        Es idempotente desde la perspectiva del bridge: si la ruta no figura en el registro
        local, no se llama a `ungrab()` (hacerlo sobre un dispositivo no tomado provocaría
        un `OSError` espurio). Un fallo del kernel se registra y no se propaga, porque el
        cierre del descriptor sigue siendo la última garantía de liberación del recurso.
        """
        if dispositivo.ruta not in self._dispositivos_exclusivos:
            return

        # Retiramos la marca antes de intentar: aunque `ungrab()` falle, el bridge deja de
        # considerar suyo ese dispositivo y no volverá a intentar liberarlo dos veces.
        self._dispositivos_exclusivos.discard(dispositivo.ruta)

        dev = self._dispositivos_abiertos.get(dispositivo.ruta)
        if dev is None:
            return

        try:
            dev.ungrab()
        except Exception as exc:
            logger.debug(
                "Error liberando la captura exclusiva de %s: %s",
                dispositivo.ruta,
                exc,
            )
            return

        logger.info(
            "Captura exclusiva liberada en %s ('%s').",
            dispositivo.ruta,
            dispositivo.nombre,
        )

    def tiene_exclusividad(self, dispositivo: DispositivoFisico) -> bool:
        """Informa si este proceso sostiene la exclusividad del dispositivo indicado."""
        return dispositivo.ruta in self._dispositivos_exclusivos

    def cerrar_dispositivo(self, dispositivo: DispositivoFisico) -> None:
        """Libera la exclusividad, cierra el descriptor evdev y lo remueve del registro."""
        self.liberar_exclusividad(dispositivo)
        dev = self._dispositivos_abiertos.pop(dispositivo.ruta, None)
        if dev is not None:
            try:
                dev.close()
            except Exception as exc:
                logger.debug("Error cerrando descriptor %s: %s", dispositivo.ruta, exc)

    def cerrar_todo(self) -> None:
        """Libera toda exclusividad pendiente y cierra los descriptores evdev abiertos."""
        for ruta, dev in list(self._dispositivos_abiertos.items()):
            if ruta in self._dispositivos_exclusivos:
                self._dispositivos_exclusivos.discard(ruta)
                try:
                    dev.ungrab()
                except Exception as exc:
                    logger.debug("Error liberando exclusividad de %s: %s", ruta, exc)
            try:
                dev.close()
            except Exception as exc:
                logger.debug("Error cerrando %s: %s", ruta, exc)
        self._dispositivos_abiertos.clear()
        self._dispositivos_exclusivos.clear()


class AdaptadorFalso:
    """Adaptador de pruebas puramente en memoria para CI y tests sin hardware real."""

    def __init__(self) -> None:
        self.dispositivos_disponibles: list[DispositivoFisico] = []
        self.eventos_pendientes: dict[str, list[EventoTeclaFisica]] = {}
        self.dispositivos_cerrados: list[str] = []
        self.dispositivos_a_desconectar: set[str] = set()
        # Estado de exclusividad simulada. `rutas_que_fallan_exclusividad` permite probar la
        # política fail-safe sin hardware ni privilegios, y los contadores permiten
        # demostrar que no hay doble grab ni doble ungrab.
        self.dispositivos_exclusivos: set[str] = set()
        self.rutas_que_fallan_exclusividad: set[str] = set()
        self.conteo_adquisiciones: dict[str, int] = {}
        self.conteo_liberaciones: dict[str, int] = {}

    def agregar_dispositivo(
        self,
        ruta: str,
        fingerprint: str,
        nombre: str = "Teclado Falso",
    ) -> DispositivoFisico:
        """Registra un dispositivo simulado para ser descubierto."""
        disp = DispositivoFisico(ruta=ruta, fingerprint=fingerprint, nombre=nombre)
        self.dispositivos_disponibles.append(disp)
        self.eventos_pendientes[ruta] = []
        return disp

    def simular_evento(self, ruta: str, evento: EventoTeclaFisica) -> None:
        """Encola un evento de tecla física en la cola de lectura del dispositivo simulado.

        El adaptador falso sella `ruta_dispositivo` igual que el adaptador real: en una
        prueba, encolar un evento en `ruta` equivale a que el kernel lo haya entregado por
        ese descriptor. Así una prueba puede simular dos descriptores con el mismo
        fingerprint y comprobar que sólo el capturado autoriza el despacho.
        """
        if ruta not in self.eventos_pendientes:
            self.eventos_pendientes[ruta] = []
        self.eventos_pendientes[ruta].append(replace(evento, ruta_dispositivo=ruta))

    def simular_desconexion(self, ruta: str) -> None:
        """Marca un dispositivo para fallar con ErrorDispositivoDesconectado al leer."""
        self.dispositivos_a_desconectar.add(ruta)

    def descubrir_dispositivos(self) -> list[DispositivoFisico]:
        """Devuelve los dispositivos disponibles que no hayan sido cerrados."""
        return [
            d for d in self.dispositivos_disponibles if d.ruta not in self.dispositivos_cerrados
        ]

    def leer_eventos(self, dispositivo: DispositivoFisico) -> list[EventoTeclaFisica]:
        """Devuelve los eventos encolados o simula la desconexión."""
        if dispositivo.ruta in self.dispositivos_a_desconectar:
            self.dispositivos_a_desconectar.remove(dispositivo.ruta)
            self.cerrar_dispositivo(dispositivo)
            raise ErrorDispositivoDesconectado(
                f"Dispositivo falso desconectado en {dispositivo.ruta}"
            )

        cola = self.eventos_pendientes.get(dispositivo.ruta, [])
        # Vaciamos la cola y devolvemos los eventos
        self.eventos_pendientes[dispositivo.ruta] = []
        return cola

    def simular_fallo_exclusividad(self, ruta: str, falla: bool = True) -> None:
        """Marca (o desmarca) una ruta para que su adquisición exclusiva falle."""
        if falla:
            self.rutas_que_fallan_exclusividad.add(ruta)
        else:
            self.rutas_que_fallan_exclusividad.discard(ruta)

    def adquirir_exclusividad(self, dispositivo: DispositivoFisico) -> None:
        """Simula `grab()` respetando idempotencia y fallos configurados."""
        if dispositivo.ruta in self.dispositivos_exclusivos:
            return
        if dispositivo.ruta in self.rutas_que_fallan_exclusividad:
            raise ErrorExclusividadNoDisponible(
                f"Exclusividad simulada no disponible en {dispositivo.ruta}"
            )
        self.dispositivos_exclusivos.add(dispositivo.ruta)
        self.conteo_adquisiciones[dispositivo.ruta] = (
            self.conteo_adquisiciones.get(dispositivo.ruta, 0) + 1
        )

    def liberar_exclusividad(self, dispositivo: DispositivoFisico) -> None:
        """Simula `ungrab()` sin fallar cuando el dispositivo no estaba tomado."""
        if dispositivo.ruta not in self.dispositivos_exclusivos:
            return
        self.dispositivos_exclusivos.discard(dispositivo.ruta)
        self.conteo_liberaciones[dispositivo.ruta] = (
            self.conteo_liberaciones.get(dispositivo.ruta, 0) + 1
        )

    def tiene_exclusividad(self, dispositivo: DispositivoFisico) -> bool:
        """Indica si el dispositivo simulado está tomado en exclusiva."""
        return dispositivo.ruta in self.dispositivos_exclusivos

    def descartar_eventos_pendientes(self, dispositivo: DispositivoFisico | None = None) -> int:
        """Drena y descarta los eventos acumulados en memoria."""
        total = 0
        if dispositivo is not None:
            total = len(self.eventos_pendientes.get(dispositivo.ruta, []))
            self.eventos_pendientes[dispositivo.ruta] = []
        else:
            for ruta in list(self.eventos_pendientes.keys()):
                total += len(self.eventos_pendientes[ruta])
                self.eventos_pendientes[ruta] = []
        return total

    def cerrar_dispositivo(self, dispositivo: DispositivoFisico) -> None:
        """Libera la exclusividad simulada y marca el dispositivo como cerrado."""
        self.liberar_exclusividad(dispositivo)
        if dispositivo.ruta not in self.dispositivos_cerrados:
            self.dispositivos_cerrados.append(dispositivo.ruta)
        self.eventos_pendientes.pop(dispositivo.ruta, None)

    def cerrar_todo(self) -> None:
        """Cierra todos los dispositivos simulados."""
        for d in self.dispositivos_disponibles:
            self.cerrar_dispositivo(d)
