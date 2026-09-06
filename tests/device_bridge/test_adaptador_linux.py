# pyright: reportPrivateUsage=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false

"""Pruebas unitarias de los adaptadores de hardware (evdev y fake en memoria).

Verifica:
1. Filtrado estricto de keydown (solo propaga pulsaciones reales, no keyup ni repeat/hold).
2. Detección de desconexión física mediante ErrorDispositivoDesconectado.
3. Cierre y liberación limpia de descriptores de hardware.
4. Capacidad de redescubrimiento dinámico de dispositivos agregados en caliente.
5. Tolerancia a iniciar con cero hardware disponible sin fallar el proceso.
6. Pruebas directas de AdaptadorEvdevLinux con mocks deterministas (I-3).
7. Captura exclusiva (WP-075): grab() una sola vez, ungrab() una sola vez, manejo de error
   al adquirir, cierre sin doble liberación y estado de exclusividad del adaptador falso.
"""

from __future__ import annotations

import pytest
from sis_leg_device_bridge.adaptador_linux import (
    AdaptadorEvdevLinux,
    AdaptadorFalso,
    DispositivoFisico,
    ErrorDispositivoDesconectado,
    ErrorExclusividadNoDisponible,
)
from sis_leg_device_bridge.modelos import EventoTeclaFisica

try:
    from evdev import ecodes
except ImportError:  # pragma: no cover
    ecodes = None  # type: ignore[assignment]

FINGERPRINT_A = "lin|vendor=1111|product=2222|version=0001|phys=usb-1|uniq=|name=Teclado A"
FINGERPRINT_B = "lin|vendor=3333|product=4444|version=0001|phys=usb-2|uniq=|name=Teclado B"


def test_adaptador_falso_descubrimiento_inicial() -> None:
    """Demuestra que el adaptador enumera los dispositivos registrados."""
    adaptador = AdaptadorFalso()
    assert adaptador.descubrir_dispositivos() == []

    adaptador.agregar_dispositivo(
        ruta="/dev/input/event0",
        fingerprint=FINGERPRINT_A,
        nombre="Teclado A",
    )
    candidatos = adaptador.descubrir_dispositivos()
    assert len(candidatos) == 1
    assert candidatos[0].ruta == "/dev/input/event0"
    assert candidatos[0].fingerprint == FINGERPRINT_A
    assert candidatos[0].nombre == "Teclado A"


def test_adaptador_falso_lectura_eventos() -> None:
    """Demuestra la lectura y vaciado de eventos encolados en un dispositivo simulado."""
    adaptador = AdaptadorFalso()
    disp = adaptador.agregar_dispositivo(
        ruta="/dev/input/event0",
        fingerprint=FINGERPRINT_A,
    )

    ev1 = EventoTeclaFisica(
        fingerprint=FINGERPRINT_A,
        codigo_tecla=2,
        nombre_tecla="KEY_1",
        es_bajada=True,
    )
    ev2 = EventoTeclaFisica(
        fingerprint=FINGERPRINT_A,
        codigo_tecla=3,
        nombre_tecla="KEY_2",
        es_bajada=True,
    )

    adaptador.simular_evento("/dev/input/event0", ev1)
    adaptador.simular_evento("/dev/input/event0", ev2)

    leidos = adaptador.leer_eventos(disp)
    assert len(leidos) == 2
    assert leidos[0] == ev1
    assert leidos[1] == ev2

    # Segunda lectura debe estar vacía
    assert adaptador.leer_eventos(disp) == []


def test_adaptador_falso_simular_desconexion() -> None:
    """Demuestra que una desconexión lanza ErrorDispositivoDesconectado y cierra."""
    adaptador = AdaptadorFalso()
    disp = adaptador.agregar_dispositivo(
        ruta="/dev/input/event0",
        fingerprint=FINGERPRINT_A,
    )

    adaptador.simular_desconexion("/dev/input/event0")

    with pytest.raises(ErrorDispositivoDesconectado, match="desconectado"):
        adaptador.leer_eventos(disp)

    # El dispositivo desconectado ya no aparece en el descubrimiento
    assert adaptador.descubrir_dispositivos() == []


def test_adaptador_falso_redescubrimiento_en_caliente() -> None:
    """Demuestra que nuevos dispositivos conectados posteriormente son descubiertos."""
    adaptador = AdaptadorFalso()
    adaptador.agregar_dispositivo(
        ruta="/dev/input/event0",
        fingerprint=FINGERPRINT_A,
    )
    assert len(adaptador.descubrir_dispositivos()) == 1

    # Agregamos un segundo dispositivo simulando conexión USB en caliente
    disp_b = adaptador.agregar_dispositivo(
        ruta="/dev/input/event1",
        fingerprint=FINGERPRINT_B,
        nombre="Teclado B",
    )
    dispositivos = adaptador.descubrir_dispositivos()
    assert len(dispositivos) == 2
    assert disp_b in dispositivos


def test_adaptador_falso_cerrar_todo() -> None:
    """Demuestra que cerrar_todo limpia y cierra todos los dispositivos simulados."""
    adaptador = AdaptadorFalso()
    adaptador.agregar_dispositivo("/dev/input/event0", FINGERPRINT_A)
    adaptador.agregar_dispositivo("/dev/input/event1", FINGERPRINT_B)

    assert len(adaptador.descubrir_dispositivos()) == 2
    adaptador.cerrar_todo()
    assert len(adaptador.descubrir_dispositivos()) == 0


class MockInputEvent:
    """Evento evdev simulado en memoria para probar la lógica de AdaptadorEvdevLinux."""

    def __init__(self, type: int, code: int, value: int) -> None:  # noqa: A002
        self.type = type
        self.code = code
        self.value = value


class MockInputDevice:
    """Dispositivo evdev simulado en memoria para probar la lectura de descriptores."""

    def __init__(
        self,
        path: str = "/dev/input/event0",
        events: list[MockInputEvent] | None = None,
        raise_on_read: Exception | None = None,
        raise_on_grab: Exception | None = None,
    ) -> None:
        self.path = path
        self.eventos = events or []
        self._raise_on_read = raise_on_read
        self._raise_on_grab = raise_on_grab
        self.closed = False
        # Contadores que permiten demostrar que el adaptador no repite las llamadas
        # EVIOCGRAB/EVIOCGRAB(0) del contrato oficial de python-evdev.
        self.llamadas_grab = 0
        self.llamadas_ungrab = 0

    def read(self) -> list[MockInputEvent]:
        if self.closed:
            raise OSError(19, "No such device")
        if self._raise_on_read is not None:
            raise self._raise_on_read
        res = self.eventos
        self.eventos = []
        return res

    def grab(self) -> None:
        if self._raise_on_grab is not None:
            raise self._raise_on_grab
        self.llamadas_grab += 1

    def ungrab(self) -> None:
        self.llamadas_ungrab += 1

    def close(self) -> None:
        self.closed = True


def test_adaptador_evdev_leer_eventos_filtra_estrictamente_keydown_value_1() -> None:
    """Demuestra que EV_KEY con value=1 produce un EventoTeclaFisica con es_bajada=True."""
    assert ecodes is not None
    adaptador = AdaptadorEvdevLinux()
    disp = DispositivoFisico(
        ruta="/dev/input/event0",
        fingerprint=FINGERPRINT_A,
        nombre="Teclado A",
    )
    mock_dev = MockInputDevice(
        path="/dev/input/event0",
        events=[MockInputEvent(type=ecodes.EV_KEY, code=ecodes.KEY_1, value=1)],
    )
    adaptador._dispositivos_abiertos[disp.ruta] = mock_dev  # type: ignore[assignment]

    eventos = adaptador.leer_eventos(disp)
    assert len(eventos) == 1
    ev = eventos[0]
    assert ev.fingerprint == FINGERPRINT_A
    assert ev.codigo_tecla == ecodes.KEY_1
    assert ev.nombre_tecla == "KEY_1"
    assert ev.es_bajada is True
    assert ev.descripcion_dispositivo == "Teclado A"


def test_adaptador_evdev_leer_eventos_descarta_keyup_value_0() -> None:
    """Demuestra que EV_KEY con value=0 (soltar tecla) es descartado (cero eventos)."""
    assert ecodes is not None
    adaptador = AdaptadorEvdevLinux()
    disp = DispositivoFisico(
        ruta="/dev/input/event0",
        fingerprint=FINGERPRINT_A,
        nombre="Teclado A",
    )
    mock_dev = MockInputDevice(
        path="/dev/input/event0",
        events=[MockInputEvent(type=ecodes.EV_KEY, code=ecodes.KEY_1, value=0)],
    )
    adaptador._dispositivos_abiertos[disp.ruta] = mock_dev  # type: ignore[assignment]

    eventos = adaptador.leer_eventos(disp)
    assert len(eventos) == 0


def test_adaptador_evdev_leer_eventos_descarta_repeat_hold_value_2() -> None:
    """Demuestra que EV_KEY con value=2 (autorepetición) es descartado (cero eventos)."""
    assert ecodes is not None
    adaptador = AdaptadorEvdevLinux()
    disp = DispositivoFisico(
        ruta="/dev/input/event0",
        fingerprint=FINGERPRINT_A,
        nombre="Teclado A",
    )
    mock_dev = MockInputDevice(
        path="/dev/input/event0",
        events=[MockInputEvent(type=ecodes.EV_KEY, code=ecodes.KEY_1, value=2)],
    )
    adaptador._dispositivos_abiertos[disp.ruta] = mock_dev  # type: ignore[assignment]

    eventos = adaptador.leer_eventos(disp)
    assert len(eventos) == 0


def test_adaptador_evdev_leer_eventos_descarta_no_ev_key() -> None:
    """Demuestra que eventos que no sean EV_KEY (ej: EV_SYN, EV_REL, EV_ABS) se descartan."""
    assert ecodes is not None
    adaptador = AdaptadorEvdevLinux()
    disp = DispositivoFisico(
        ruta="/dev/input/event0",
        fingerprint=FINGERPRINT_A,
        nombre="Teclado A",
    )
    mock_dev = MockInputDevice(
        path="/dev/input/event0",
        events=[
            MockInputEvent(type=ecodes.EV_SYN, code=0, value=0),
            MockInputEvent(type=ecodes.EV_REL, code=0, value=1),
            MockInputEvent(type=ecodes.EV_ABS, code=0, value=1),
        ],
    )
    adaptador._dispositivos_abiertos[disp.ruta] = mock_dev  # type: ignore[assignment]

    eventos = adaptador.leer_eventos(disp)
    assert len(eventos) == 0


def test_adaptador_evdev_leer_eventos_buffer_mixto_solo_propaga_keydowns() -> None:
    """Demuestra que en un buffer con eventos mezclados solo sobreviven los keydowns en orden."""
    assert ecodes is not None
    adaptador = AdaptadorEvdevLinux()
    disp = DispositivoFisico(
        ruta="/dev/input/event0",
        fingerprint=FINGERPRINT_A,
        nombre="Teclado A",
    )
    mock_dev = MockInputDevice(
        path="/dev/input/event0",
        events=[
            MockInputEvent(type=ecodes.EV_SYN, code=0, value=0),
            MockInputEvent(type=ecodes.EV_KEY, code=ecodes.KEY_1, value=0),  # keyup
            MockInputEvent(type=ecodes.EV_KEY, code=ecodes.KEY_KP1, value=1),  # keydown KP1
            MockInputEvent(type=ecodes.EV_KEY, code=ecodes.KEY_1, value=2),  # repeat
            MockInputEvent(type=ecodes.EV_KEY, code=ecodes.KEY_KP9, value=1),  # keydown KP9
            MockInputEvent(type=ecodes.EV_REL, code=1, value=1),  # non-key
            MockInputEvent(type=ecodes.EV_KEY, code=ecodes.KEY_KP9, value=0),  # keyup
        ],
    )
    adaptador._dispositivos_abiertos[disp.ruta] = mock_dev  # type: ignore[assignment]

    eventos = adaptador.leer_eventos(disp)
    assert len(eventos) == 2
    assert eventos[0].nombre_tecla == "KEY_KP1"
    assert eventos[0].es_bajada is True
    assert eventos[1].nombre_tecla == "KEY_KP9"
    assert eventos[1].es_bajada is True


def test_adaptador_evdev_desconexion_cierra_descriptor_y_lanza_error() -> None:
    """Demuestra que si dev.read() lanza OSError (ENODEV), se cierra y lanza desconexión."""
    adaptador = AdaptadorEvdevLinux()
    disp = DispositivoFisico(
        ruta="/dev/input/event0",
        fingerprint=FINGERPRINT_A,
        nombre="Teclado A",
    )
    mock_dev = MockInputDevice(
        path="/dev/input/event0",
        raise_on_read=OSError(19, "No such device"),
    )
    adaptador._dispositivos_abiertos[disp.ruta] = mock_dev  # type: ignore[assignment]

    with pytest.raises(ErrorDispositivoDesconectado, match="desconectado"):
        adaptador.leer_eventos(disp)

    assert mock_dev.closed is True
    assert disp.ruta not in adaptador._dispositivos_abiertos


def test_adaptador_evdev_blocking_io_error_retorna_vacio() -> None:
    """Demuestra que BlockingIOError durante la lectura retorna lista vacía sin error."""
    adaptador = AdaptadorEvdevLinux()
    disp = DispositivoFisico(
        ruta="/dev/input/event0",
        fingerprint=FINGERPRINT_A,
        nombre="Teclado A",
    )
    mock_dev = MockInputDevice(
        path="/dev/input/event0",
        raise_on_read=BlockingIOError(),
    )
    adaptador._dispositivos_abiertos[disp.ruta] = mock_dev  # type: ignore[assignment]

    assert adaptador.leer_eventos(disp) == []


def test_adaptador_evdev_descartar_eventos_pendientes() -> None:
    """Demuestra que descartar_eventos_pendientes drena todos los eventos del descriptor."""
    assert ecodes is not None
    adaptador = AdaptadorEvdevLinux()
    disp = DispositivoFisico(
        ruta="/dev/input/event0",
        fingerprint=FINGERPRINT_A,
        nombre="Teclado A",
    )
    mock_dev = MockInputDevice(
        path="/dev/input/event0",
        events=[
            MockInputEvent(type=ecodes.EV_KEY, code=ecodes.KEY_1, value=1),
            MockInputEvent(type=ecodes.EV_KEY, code=ecodes.KEY_2, value=1),
        ],
    )
    adaptador._dispositivos_abiertos[disp.ruta] = mock_dev  # type: ignore[assignment]

    descartados = adaptador.descartar_eventos_pendientes(disp)
    assert descartados == 2
    assert len(mock_dev.eventos) == 0


def test_adaptador_falso_descartar_eventos_pendientes() -> None:
    """Demuestra que AdaptadorFalso purga eventos encolados correctamente."""
    adaptador = AdaptadorFalso()
    disp = adaptador.agregar_dispositivo("/dev/input/event0", FINGERPRINT_A)

    adaptador.simular_evento(
        "/dev/input/event0",
        EventoTeclaFisica(
            fingerprint=FINGERPRINT_A,
            codigo_tecla=2,
            nombre_tecla="KEY_1",
            es_bajada=True,
        ),
    )
    assert len(adaptador.eventos_pendientes["/dev/input/event0"]) == 1

    descartados = adaptador.descartar_eventos_pendientes(disp)
    assert descartados == 1
    assert len(adaptador.eventos_pendientes["/dev/input/event0"]) == 0


# ---------------------------------------------------------------------------
# Captura exclusiva (WP-075)
#
# El contrato oficial de python-evdev indica que solo un proceso puede sostener
# el grab() de un dispositivo y que liberar uno no tomado provoca un OSError.
# Por eso el adaptador mantiene su propio registro y estas pruebas verifican que
# ni el grab ni el ungrab se repiten.
# ---------------------------------------------------------------------------


def _preparar_adaptador_con_mock(
    raise_on_grab: Exception | None = None,
) -> tuple[AdaptadorEvdevLinux, DispositivoFisico, MockInputDevice]:
    """Arma un AdaptadorEvdevLinux con un descriptor simulado ya registrado."""
    adaptador = AdaptadorEvdevLinux()
    disp = DispositivoFisico(
        ruta="/dev/input/event0",
        fingerprint=FINGERPRINT_A,
        nombre="Numpad banca 1",
    )
    mock_dev = MockInputDevice(path="/dev/input/event0", raise_on_grab=raise_on_grab)
    adaptador._dispositivos_abiertos[disp.ruta] = mock_dev  # type: ignore[assignment]
    return adaptador, disp, mock_dev


def test_adaptador_evdev_adquiere_exclusividad_una_sola_vez() -> None:
    """Demuestra que adquirir dos veces llama a grab() una sola vez (idempotencia)."""
    adaptador, disp, mock_dev = _preparar_adaptador_con_mock()

    adaptador.adquirir_exclusividad(disp)
    adaptador.adquirir_exclusividad(disp)

    assert mock_dev.llamadas_grab == 1
    assert adaptador.tiene_exclusividad(disp) is True


def test_adaptador_evdev_libera_exclusividad_una_sola_vez() -> None:
    """Demuestra que liberar dos veces llama a ungrab() una sola vez y no lanza error."""
    adaptador, disp, mock_dev = _preparar_adaptador_con_mock()

    adaptador.adquirir_exclusividad(disp)
    adaptador.liberar_exclusividad(disp)
    adaptador.liberar_exclusividad(disp)

    assert mock_dev.llamadas_ungrab == 1
    assert adaptador.tiene_exclusividad(disp) is False


def test_adaptador_evdev_liberar_sin_haber_adquirido_no_llama_ungrab() -> None:
    """Demuestra que nunca se invoca ungrab() sobre un dispositivo que no fue tomado."""
    adaptador, disp, mock_dev = _preparar_adaptador_con_mock()

    adaptador.liberar_exclusividad(disp)

    assert mock_dev.llamadas_ungrab == 0
    assert adaptador.tiene_exclusividad(disp) is False


def test_adaptador_evdev_error_al_adquirir_no_marca_exclusividad() -> None:
    """Demuestra que un grab() rechazado por el kernel produce ErrorExclusividadNoDisponible."""
    adaptador, disp, _mock_dev = _preparar_adaptador_con_mock(
        raise_on_grab=OSError(16, "Device or resource busy")
    )

    with pytest.raises(ErrorExclusividadNoDisponible, match="captura exclusiva"):
        adaptador.adquirir_exclusividad(disp)

    assert adaptador.tiene_exclusividad(disp) is False


def test_adaptador_evdev_adquirir_sin_descriptor_abierto_falla() -> None:
    """Demuestra que sin descriptor abierto no se simula una exclusividad inexistente."""
    adaptador = AdaptadorEvdevLinux()
    disp = DispositivoFisico(
        ruta="/dev/input/event0",
        fingerprint=FINGERPRINT_A,
        nombre="Numpad banca 1",
    )

    with pytest.raises(ErrorExclusividadNoDisponible, match="descriptor"):
        adaptador.adquirir_exclusividad(disp)

    assert adaptador.tiene_exclusividad(disp) is False


def test_adaptador_evdev_cerrar_dispositivo_libera_sin_doble_ungrab() -> None:
    """Demuestra que el cierre libera la exclusividad exactamente una vez antes de close()."""
    adaptador, disp, mock_dev = _preparar_adaptador_con_mock()

    adaptador.adquirir_exclusividad(disp)
    adaptador.cerrar_dispositivo(disp)
    # Un segundo cierre (por ejemplo tras una desconexión ya procesada) no repite ungrab().
    adaptador.cerrar_dispositivo(disp)

    assert mock_dev.llamadas_ungrab == 1
    assert mock_dev.closed is True
    assert adaptador.tiene_exclusividad(disp) is False


def test_adaptador_evdev_cerrar_todo_libera_exclusividad_de_cada_dispositivo() -> None:
    """Demuestra que la parada del bridge devuelve todos los numpads al sistema."""
    adaptador = AdaptadorEvdevLinux()
    disp_a = DispositivoFisico(
        ruta="/dev/input/event0", fingerprint=FINGERPRINT_A, nombre="Numpad 1"
    )
    disp_b = DispositivoFisico(
        ruta="/dev/input/event1", fingerprint=FINGERPRINT_B, nombre="Numpad 2"
    )
    mock_a = MockInputDevice(path=disp_a.ruta)
    mock_b = MockInputDevice(path=disp_b.ruta)
    adaptador._dispositivos_abiertos[disp_a.ruta] = mock_a  # type: ignore[assignment]
    adaptador._dispositivos_abiertos[disp_b.ruta] = mock_b  # type: ignore[assignment]

    adaptador.adquirir_exclusividad(disp_a)
    # disp_b queda deliberadamente sin exclusividad: representa un teclado no mapeado.
    adaptador.cerrar_todo()

    assert mock_a.llamadas_ungrab == 1
    assert mock_b.llamadas_ungrab == 0
    assert mock_a.closed is True
    assert mock_b.closed is True
    assert adaptador.tiene_exclusividad(disp_a) is False


def test_adaptador_falso_exclusividad_idempotente() -> None:
    """Demuestra que el adaptador falso replica la idempotencia del adaptador real."""
    adaptador = AdaptadorFalso()
    disp = adaptador.agregar_dispositivo("/dev/input/event0", FINGERPRINT_A)

    adaptador.adquirir_exclusividad(disp)
    adaptador.adquirir_exclusividad(disp)
    assert adaptador.tiene_exclusividad(disp) is True
    assert adaptador.conteo_adquisiciones["/dev/input/event0"] == 1

    adaptador.liberar_exclusividad(disp)
    adaptador.liberar_exclusividad(disp)
    assert adaptador.tiene_exclusividad(disp) is False
    assert adaptador.conteo_liberaciones["/dev/input/event0"] == 1


def test_adaptador_falso_puede_simular_fallo_de_exclusividad() -> None:
    """Demuestra que el fake permite probar la política fail-safe sin hardware real."""
    adaptador = AdaptadorFalso()
    disp = adaptador.agregar_dispositivo("/dev/input/event0", FINGERPRINT_A)
    adaptador.simular_fallo_exclusividad("/dev/input/event0")

    with pytest.raises(ErrorExclusividadNoDisponible):
        adaptador.adquirir_exclusividad(disp)
    assert adaptador.tiene_exclusividad(disp) is False

    # Al desaparecer la causa del fallo, la adquisición vuelve a ser posible.
    adaptador.simular_fallo_exclusividad("/dev/input/event0", falla=False)
    adaptador.adquirir_exclusividad(disp)
    assert adaptador.tiene_exclusividad(disp) is True


def test_adaptador_falso_cerrar_dispositivo_libera_exclusividad() -> None:
    """Demuestra que cerrar un dispositivo simulado también libera su exclusividad."""
    adaptador = AdaptadorFalso()
    disp = adaptador.agregar_dispositivo("/dev/input/event0", FINGERPRINT_A)

    adaptador.adquirir_exclusividad(disp)
    adaptador.cerrar_dispositivo(disp)

    assert adaptador.tiene_exclusividad(disp) is False
    assert adaptador.conteo_liberaciones["/dev/input/event0"] == 1
