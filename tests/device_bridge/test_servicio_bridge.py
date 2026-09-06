"""Pruebas de integración del ServicioDeviceBridge.

Verifica:
1. Evento físico reconocido + fingerprint mapeado -> Único POST exacto {dispositivo, tecla}.
2. DECISIÓN HUMANA 4.B: Teclas reconocidas no funcionales actualmente (4, 5, 6, 0, ENTER, etc.)
   también se transmiten al backend cuando provienen de un dispositivo mapeado.
3. Tecla física no reconocida en el catálogo -> Cero POST.
4. Fingerprint físico no mapeado en devices.json -> Cero POST, no asigna devXX automáticamente.
5. Eventos no-keydown (keyup, hold) -> Cero POST.
6. Múltiples pulsaciones -> Despacho independiente de cada una.
7. Tolerancia a inicio con cero hardware.
8. Descubrimiento dinámico de hardware conectado posteriormente.
9. Manejo de desconexión en caliente y limpieza de recursos.
10. Parada limpia del servicio.
11. Política de captura exclusiva (WP-075): un dispositivo mapeado toma exclusividad antes
    de despachar, uno no mapeado nunca la recibe, un fallo de exclusividad no despacha,
    la reconexión vuelve a adquirirla, el remapeo la reconcilia y la parada la libera.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest
from botonera2_device_bridge.adaptador_linux import AdaptadorFalso
from botonera2_device_bridge.cliente_http import ClienteHttpBackend
from botonera2_device_bridge.configuracion import ConfiguracionBridge
from botonera2_device_bridge.modelos import EventoTeclaFisica
from botonera2_device_bridge.remapeo import PersistenciaRemapeo
from botonera2_device_bridge.servicio import ServicioDeviceBridge

FINGERPRINT_DEV01 = "lin|vendor=1111|product=2222|version=0001|phys=usb-1|uniq=|name=Teclado 1"
FINGERPRINT_DEV02 = "lin|vendor=3333|product=4444|version=0001|phys=usb-2|uniq=|name=Teclado 2"
FINGERPRINT_DESCONOCIDO = "lin|vendor=9999|product=9999|version=0001|phys=usb-9|uniq=|name=Ajeno"


class FakeClienteHttp(ClienteHttpBackend):
    """Cliente HTTP falso que registra las peticiones sin realizar llamadas de red."""

    def __init__(self) -> None:
        super().__init__(url_base="http://fake:8000", timeout_segundos=1.0)
        self.peticiones_enviadas: list[dict[str, str]] = []
        self.proxima_respuesta_aceptada: bool = True
        self.proximo_motivo: str = "PRESENCIA_ACTUALIZADA"
        self.proximo_error_transporte: str | None = None
        self.proximo_codigo_http: int | None = 200

    def enviar_pulsacion(self, solicitud: Any) -> Any:
        from botonera2_device_bridge.modelos import RespuestaEnvioBackend

        self.peticiones_enviadas.append(
            {
                "dispositivo": solicitud.dispositivo,
                "tecla": solicitud.tecla,
            }
        )

        if self.proximo_error_transporte is not None or self.proximo_codigo_http is None:
            return RespuestaEnvioBackend(
                aceptada=None,
                codigo_http=self.proximo_codigo_http,
                motivo=self.proximo_motivo,
                cuerpo=None,
                error_transporte=self.proximo_error_transporte or "Error simulado",
            )

        return RespuestaEnvioBackend(
            aceptada=self.proxima_respuesta_aceptada,
            codigo_http=self.proximo_codigo_http or 200,
            motivo=self.proximo_motivo,
            cuerpo={"aceptada": self.proxima_respuesta_aceptada, "motivo": self.proximo_motivo},
        )


@pytest.fixture
def entorno_bridge() -> tuple[ServicioDeviceBridge, AdaptadorFalso, FakeClienteHttp]:
    """Crea una instancia de ServicioDeviceBridge con dependencias simuladas."""
    mapeo = {
        FINGERPRINT_DEV01: "dev01",
        FINGERPRINT_DEV02: "dev02",
    }
    configuracion = ConfiguracionBridge(
        url_base_api="http://fake:8000",
        timeout_http_segundos=1.0,
        ruta_devices_json=Path("fake/devices.json"),
        intervalo_escaneo_segundos=0.1,
    )
    adaptador = AdaptadorFalso()
    cliente_http = FakeClienteHttp()

    servicio = ServicioDeviceBridge(
        configuracion=configuracion,
        adaptador=adaptador,
        cliente_http=cliente_http,
        mapeo_dispositivos=mapeo,
    )
    return servicio, adaptador, cliente_http


def test_pulsacion_reconocida_y_mapeada_envia_un_post(
    entorno_bridge: tuple[ServicioDeviceBridge, AdaptadorFalso, FakeClienteHttp],
) -> None:
    """Demuestra que una tecla válida de dispositivo mapeado emite un POST con devXX."""
    servicio, adaptador, cliente_http = entorno_bridge

    adaptador.agregar_dispositivo("/dev/input/event0", FINGERPRINT_DEV01)
    servicio.ejecutar_ciclo_descubrimiento()

    evento = EventoTeclaFisica(
        fingerprint=FINGERPRINT_DEV01,
        codigo_tecla=2,
        nombre_tecla="KEY_1",
        es_bajada=True,
    )
    adaptador.simular_evento("/dev/input/event0", evento)

    respuestas = servicio.ejecutar_paso()
    assert len(respuestas) == 1
    assert len(cliente_http.peticiones_enviadas) == 1
    assert cliente_http.peticiones_enviadas[0] == {"dispositivo": "dev01", "tecla": "1"}


def test_decision_4b_teclas_no_funcionales_reconocidas_se_transmiten(
    entorno_bridge: tuple[ServicioDeviceBridge, AdaptadorFalso, FakeClienteHttp],
) -> None:
    """Demuestra la Decisión Humana 4.B: teclas como '4', '0', 'ENTER', '+' se envían al backend."""
    servicio, adaptador, cliente_http = entorno_bridge

    adaptador.agregar_dispositivo("/dev/input/event0", FINGERPRINT_DEV01)
    servicio.ejecutar_ciclo_descubrimiento()

    teclas_a_probar = [
        ("KEY_4", "4"),
        ("KEY_5", "5"),
        ("KEY_6", "6"),
        ("KEY_0", "0"),
        ("KEY_ENTER", "ENTER"),
        ("KEY_KPPLUS", "+"),
        ("KEY_KPMINUS", "-"),
    ]

    for ev_nombre, _tecla_esperada in teclas_a_probar:
        evento = EventoTeclaFisica(
            fingerprint=FINGERPRINT_DEV01,
            codigo_tecla=10,
            nombre_tecla=ev_nombre,
            es_bajada=True,
        )
        adaptador.simular_evento("/dev/input/event0", evento)

    respuestas = servicio.ejecutar_paso()
    assert len(respuestas) == len(teclas_a_probar)
    assert len(cliente_http.peticiones_enviadas) == len(teclas_a_probar)

    for i, (_, tecla_esperada) in enumerate(teclas_a_probar):
        assert cliente_http.peticiones_enviadas[i] == {
            "dispositivo": "dev01",
            "tecla": tecla_esperada,
        }


def test_fingerprint_no_mapeado_no_envia_post(
    entorno_bridge: tuple[ServicioDeviceBridge, AdaptadorFalso, FakeClienteHttp],
) -> None:
    """Demuestra que un dispositivo no registrado en devices.json nunca emite POST."""
    servicio, adaptador, cliente_http = entorno_bridge

    adaptador.agregar_dispositivo("/dev/input/event9", FINGERPRINT_DESCONOCIDO)
    servicio.ejecutar_ciclo_descubrimiento()

    evento = EventoTeclaFisica(
        fingerprint=FINGERPRINT_DESCONOCIDO,
        codigo_tecla=2,
        nombre_tecla="KEY_1",
        es_bajada=True,
    )
    adaptador.simular_evento("/dev/input/event9", evento)

    respuestas = servicio.ejecutar_paso()
    assert len(respuestas) == 0
    assert len(cliente_http.peticiones_enviadas) == 0


def test_tecla_desconocida_no_envia_post(
    entorno_bridge: tuple[ServicioDeviceBridge, AdaptadorFalso, FakeClienteHttp],
) -> None:
    """Demuestra que una tecla no catalogada (ej: KEY_F1) no genera POST."""
    servicio, adaptador, cliente_http = entorno_bridge

    adaptador.agregar_dispositivo("/dev/input/event0", FINGERPRINT_DEV01)
    servicio.ejecutar_ciclo_descubrimiento()

    evento = EventoTeclaFisica(
        fingerprint=FINGERPRINT_DEV01,
        codigo_tecla=59,
        nombre_tecla="KEY_F1",
        es_bajada=True,
    )
    adaptador.simular_evento("/dev/input/event0", evento)

    respuestas = servicio.ejecutar_paso()
    assert len(respuestas) == 0
    assert len(cliente_http.peticiones_enviadas) == 0


def test_eventos_no_keydown_se_ignoran(
    entorno_bridge: tuple[ServicioDeviceBridge, AdaptadorFalso, FakeClienteHttp],
) -> None:
    """Demuestra que keyup o autorepeat (es_bajada=False) son ignorados."""
    servicio, adaptador, cliente_http = entorno_bridge

    adaptador.agregar_dispositivo("/dev/input/event0", FINGERPRINT_DEV01)
    servicio.ejecutar_ciclo_descubrimiento()

    evento_keyup = EventoTeclaFisica(
        fingerprint=FINGERPRINT_DEV01,
        codigo_tecla=2,
        nombre_tecla="KEY_1",
        es_bajada=False,
    )
    adaptador.simular_evento("/dev/input/event0", evento_keyup)

    respuestas = servicio.ejecutar_paso()
    assert len(respuestas) == 0
    assert len(cliente_http.peticiones_enviadas) == 0


def test_tolerancia_cero_hardware_inicial_y_redescubrimiento(
    entorno_bridge: tuple[ServicioDeviceBridge, AdaptadorFalso, FakeClienteHttp],
) -> None:
    """Demuestra que el servicio puede iniciar sin dispositivos y detectarlos cuando se conectan."""
    servicio, adaptador, cliente_http = entorno_bridge

    # Inicio con 0 dispositivos
    servicio.ejecutar_ciclo_descubrimiento()
    assert len(servicio.dispositivos_activos) == 0

    respuestas = servicio.ejecutar_paso()
    assert len(respuestas) == 0

    # Conexión posterior
    adaptador.agregar_dispositivo("/dev/input/event0", FINGERPRINT_DEV01)
    nuevos = servicio.ejecutar_ciclo_descubrimiento()
    assert len(nuevos) == 1
    assert len(servicio.dispositivos_activos) == 1

    # Emisión de evento en el hardware recién conectado
    adaptador.simular_evento(
        "/dev/input/event0",
        EventoTeclaFisica(
            fingerprint=FINGERPRINT_DEV01,
            codigo_tecla=2,
            nombre_tecla="KEY_9",
            es_bajada=True,
        ),
    )
    respuestas = servicio.ejecutar_paso()
    assert len(respuestas) == 1
    assert len(cliente_http.peticiones_enviadas) == 1
    assert cliente_http.peticiones_enviadas[0] == {"dispositivo": "dev01", "tecla": "9"}


def test_recuperacion_desconexion_hardware(
    entorno_bridge: tuple[ServicioDeviceBridge, AdaptadorFalso, FakeClienteHttp],
) -> None:
    """Demuestra que cuando un hardware se desconecta, se remueve de activos limpiamente."""
    servicio, adaptador, _cliente_http = entorno_bridge

    adaptador.agregar_dispositivo("/dev/input/event0", FINGERPRINT_DEV01)
    servicio.ejecutar_ciclo_descubrimiento()
    assert len(servicio.dispositivos_activos) == 1

    # Simulamos desconexión física
    adaptador.simular_desconexion("/dev/input/event0")

    # Al ejecutar el paso, la excepción de desconexión es capturada y el dispositivo es removido
    respuestas = servicio.ejecutar_paso()
    assert len(respuestas) == 0
    assert len(servicio.dispositivos_activos) == 0
    assert "/dev/input/event0" in adaptador.dispositivos_cerrados


def test_ejecucion_servicio_bucle_y_parada_limpia(
    entorno_bridge: tuple[ServicioDeviceBridge, AdaptadorFalso, FakeClienteHttp],
) -> None:
    """Demuestra la ejecución acotada del bucle de servicio y parada limpia."""
    servicio, adaptador, _cliente_http = entorno_bridge

    adaptador.agregar_dispositivo("/dev/input/event0", FINGERPRINT_DEV01)

    evento_parar = threading.Event()

    # Ejecutar con límite de 3 iteraciones
    servicio.ejecutar_servicio(
        evento_detencion=evento_parar,
        limite_iteraciones=3,
        pausa_paso_segundos=0.001,
    )

    # Verifica que al terminar se hayan cerrado todos los recursos
    assert len(servicio.dispositivos_activos) == 0
    assert "/dev/input/event0" in adaptador.dispositivos_cerrados


def test_prevencion_replay_tardio_tras_fallo_transporte_o_timeout(
    entorno_bridge: tuple[ServicioDeviceBridge, AdaptadorFalso, FakeClienteHttp],
) -> None:
    """Demuestra que los eventos acumulados durante un fallo de transporte NO se reenvían.

    Escenario exacto (I-1):
    1. Bridge operativo con dos dispositivos activos ('dev01' y 'dev02').
    2. Primer evento en 'dev01' inicia un envío.
    3. El backend/transporte falla por TIMEOUT.
    4. Mientras ese envío falla, aparecen pulsaciones adicionales en 'dev01' y 'dev02'.
    5. Termina el fallo y el lote actual es interrumpido, purgando los eventos acumulados.
    6. El backend se recupera.
    7. Al ejecutarse el siguiente ciclo, las pulsaciones acumuladas NO se envían en ráfaga.
    8. Una pulsación NUEVA posterior ('dev01', tecla 9) se envía normalmente.
    """
    servicio, adaptador, cliente_http = entorno_bridge

    # 1. Bridge operativo con dev01 y dev02
    adaptador.agregar_dispositivo("/dev/input/event0", FINGERPRINT_DEV01)
    adaptador.agregar_dispositivo("/dev/input/event1", FINGERPRINT_DEV02)
    servicio.ejecutar_ciclo_descubrimiento()
    assert len(servicio.dispositivos_activos) == 2

    # 2. Primer evento en dev01
    adaptador.simular_evento(
        "/dev/input/event0",
        EventoTeclaFisica(
            fingerprint=FINGERPRINT_DEV01,
            codigo_tecla=2,
            nombre_tecla="KEY_1",
            es_bajada=True,
        ),
    )

    # 3. Backend falla por TIMEOUT en el primer intento
    cliente_http.proximo_codigo_http = None
    cliente_http.proximo_motivo = "TIMEOUT"
    cliente_http.proximo_error_transporte = "The read operation timed out"

    # 4. Durante el bloqueo se acumulan pulsaciones adicionales en el hardware
    adaptador.simular_evento(
        "/dev/input/event0",
        EventoTeclaFisica(
            fingerprint=FINGERPRINT_DEV01,
            codigo_tecla=3,
            nombre_tecla="KEY_2",
            es_bajada=True,
        ),
    )
    adaptador.simular_evento(
        "/dev/input/event1",
        EventoTeclaFisica(
            fingerprint=FINGERPRINT_DEV02,
            codigo_tecla=4,
            nombre_tecla="KEY_3",
            es_bajada=True,
        ),
    )

    # 5. Ejecutamos el paso: se intenta enviar el primer evento, falla y purga el backlog
    respuestas = servicio.ejecutar_paso()
    assert len(respuestas) == 1
    assert respuestas[0].motivo == "TIMEOUT"
    assert len(cliente_http.peticiones_enviadas) == 1
    assert cliente_http.peticiones_enviadas[0] == {"dispositivo": "dev01", "tecla": "1"}

    # 6. El backend se recupera
    cliente_http.proximo_codigo_http = 200
    cliente_http.proximo_motivo = "OK"
    cliente_http.proximo_error_transporte = None
    cliente_http.proxima_respuesta_aceptada = True

    # 7. Siguiente ciclo del servicio: los eventos viejos acumulados NO se reenvían
    respuestas_vacias = servicio.ejecutar_paso()
    assert len(respuestas_vacias) == 0
    # Sigue en 1, no se enviaron las teclas acumuladas 2 ni 3
    assert len(cliente_http.peticiones_enviadas) == 1

    # 8. Llega una pulsación NUEVA tras la recuperación
    adaptador.simular_evento(
        "/dev/input/event0",
        EventoTeclaFisica(
            fingerprint=FINGERPRINT_DEV01,
            codigo_tecla=10,
            nombre_tecla="KEY_9",
            es_bajada=True,
        ),
    )
    respuestas_nuevas = servicio.ejecutar_paso()
    assert len(respuestas_nuevas) == 1
    assert respuestas_nuevas[0].aceptada is True
    assert len(cliente_http.peticiones_enviadas) == 2
    assert cliente_http.peticiones_enviadas[1] == {"dispositivo": "dev01", "tecla": "9"}


def test_prevencion_replay_interrupcion_lote_python_en_memoria(
    entorno_bridge: tuple[ServicioDeviceBridge, AdaptadorFalso, FakeClienteHttp],
) -> None:
    """Demuestra que ante un fallo de transporte se interrumpe inmediatamente el lote ya leído."""
    servicio, adaptador, cliente_http = entorno_bridge

    adaptador.agregar_dispositivo("/dev/input/event0", FINGERPRINT_DEV01)
    servicio.ejecutar_ciclo_descubrimiento()

    # Encolamos 3 eventos en el mismo dispositivo para que leer_eventos devuelva un lote de 3
    for k in ("KEY_1", "KEY_2", "KEY_3"):
        adaptador.simular_evento(
            "/dev/input/event0",
            EventoTeclaFisica(
                fingerprint=FINGERPRINT_DEV01,
                codigo_tecla=2,
                nombre_tecla=k,
                es_bajada=True,
            ),
        )

    # Configuramos fallo de conexión en el envío
    cliente_http.proximo_codigo_http = None
    cliente_http.proximo_motivo = "ERROR_CONEXION"
    cliente_http.proximo_error_transporte = "Connection refused"

    # Se ejecuta el paso: solo el primer evento se intenta; el lote restante se aborta
    respuestas = servicio.ejecutar_paso()
    assert len(respuestas) == 1
    assert respuestas[0].motivo == "ERROR_CONEXION"
    assert len(cliente_http.peticiones_enviadas) == 1
    assert cliente_http.peticiones_enviadas[0] == {"dispositivo": "dev01", "tecla": "1"}

    # Recuperación del backend
    cliente_http.proximo_codigo_http = 200
    cliente_http.proximo_motivo = "OK"
    cliente_http.proximo_error_transporte = None

    # El siguiente paso no tiene eventos residuales
    assert len(servicio.ejecutar_paso()) == 0
    assert len(cliente_http.peticiones_enviadas) == 1


# ---------------------------------------------------------------------------
# Captura exclusiva de los numpads de banca (WP-075)
#
# La exclusividad se aplica exclusivamente a los fingerprints del mapping
# efectivo y es requisito previo al despacho funcional: mientras un dispositivo
# mapeado no esté tomado en exclusiva, sus pulsaciones también las estaría
# recibiendo el escritorio, así que no se envían al backend.
# ---------------------------------------------------------------------------


def _pulsacion(fingerprint: str, nombre_tecla: str = "KEY_1") -> EventoTeclaFisica:
    """Construye un keydown mínimo para las pruebas de exclusividad."""
    return EventoTeclaFisica(
        fingerprint=fingerprint,
        codigo_tecla=2,
        nombre_tecla=nombre_tecla,
        es_bajada=True,
    )


def test_dispositivo_mapeado_adquiere_exclusividad_antes_de_despachar(
    entorno_bridge: tuple[ServicioDeviceBridge, AdaptadorFalso, FakeClienteHttp],
) -> None:
    """Demuestra que el numpad mapeado queda tomado en exclusiva y luego sí despacha."""
    servicio, adaptador, cliente_http = entorno_bridge

    disp = adaptador.agregar_dispositivo("/dev/input/event0", FINGERPRINT_DEV01)
    servicio.ejecutar_ciclo_descubrimiento()

    assert adaptador.tiene_exclusividad(disp) is True
    assert FINGERPRINT_DEV01 in servicio.fingerprints_exclusivos

    adaptador.simular_evento("/dev/input/event0", _pulsacion(FINGERPRINT_DEV01))
    servicio.ejecutar_paso()

    assert cliente_http.peticiones_enviadas == [{"dispositivo": "dev01", "tecla": "1"}]
    # La reconciliación repetida de cada paso no vuelve a llamar al grab del sistema.
    assert adaptador.conteo_adquisiciones["/dev/input/event0"] == 1


def test_dispositivo_no_mapeado_nunca_recibe_captura_exclusiva(
    entorno_bridge: tuple[ServicioDeviceBridge, AdaptadorFalso, FakeClienteHttp],
) -> None:
    """Demuestra que el teclado del moderador no es secuestrado por ser un teclado."""
    servicio, adaptador, _cliente_http = entorno_bridge

    teclado_moderador = adaptador.agregar_dispositivo(
        "/dev/input/event9",
        FINGERPRINT_DESCONOCIDO,
        nombre="Teclado del moderador",
    )
    servicio.ejecutar_ciclo_descubrimiento()
    servicio.ejecutar_paso()

    assert adaptador.tiene_exclusividad(teclado_moderador) is False
    assert servicio.fingerprints_exclusivos == set()
    assert "/dev/input/event9" not in adaptador.conteo_adquisiciones


def test_fallo_de_exclusividad_impide_todo_post_funcional(
    entorno_bridge: tuple[ServicioDeviceBridge, AdaptadorFalso, FakeClienteHttp],
) -> None:
    """Demuestra la política fail-safe: sin exclusividad no hay despacho, ni degradación."""
    servicio, adaptador, cliente_http = entorno_bridge

    disp = adaptador.agregar_dispositivo("/dev/input/event0", FINGERPRINT_DEV01)
    adaptador.simular_fallo_exclusividad("/dev/input/event0")
    servicio.ejecutar_ciclo_descubrimiento()

    assert adaptador.tiene_exclusividad(disp) is False
    assert FINGERPRINT_DEV01 not in servicio.fingerprints_exclusivos

    adaptador.simular_evento("/dev/input/event0", _pulsacion(FINGERPRINT_DEV01))
    respuestas = servicio.ejecutar_paso()

    assert respuestas == []
    assert cliente_http.peticiones_enviadas == []


def test_recuperar_exclusividad_habilita_nuevamente_el_despacho(
    entorno_bridge: tuple[ServicioDeviceBridge, AdaptadorFalso, FakeClienteHttp],
) -> None:
    """Demuestra que al conseguirse la exclusividad el dispositivo vuelve a despachar."""
    servicio, adaptador, cliente_http = entorno_bridge

    adaptador.agregar_dispositivo("/dev/input/event0", FINGERPRINT_DEV01)
    adaptador.simular_fallo_exclusividad("/dev/input/event0")
    servicio.ejecutar_ciclo_descubrimiento()

    adaptador.simular_evento("/dev/input/event0", _pulsacion(FINGERPRINT_DEV01))
    assert servicio.ejecutar_paso() == []

    # Desaparece la causa del fallo (por ejemplo, se cerró el proceso que lo capturaba).
    adaptador.simular_fallo_exclusividad("/dev/input/event0", falla=False)
    adaptador.simular_evento("/dev/input/event0", _pulsacion(FINGERPRINT_DEV01, "KEY_9"))
    respuestas = servicio.ejecutar_paso()

    assert len(respuestas) == 1
    assert cliente_http.peticiones_enviadas == [{"dispositivo": "dev01", "tecla": "9"}]


def test_reconexion_de_numpad_mapeado_vuelve_a_adquirir_exclusividad(
    entorno_bridge: tuple[ServicioDeviceBridge, AdaptadorFalso, FakeClienteHttp],
) -> None:
    """Demuestra que tras un desconectar/reconectar físico se vuelve a tomar el dispositivo."""
    servicio, adaptador, cliente_http = entorno_bridge

    adaptador.agregar_dispositivo("/dev/input/event0", FINGERPRINT_DEV01)
    servicio.ejecutar_ciclo_descubrimiento()
    assert FINGERPRINT_DEV01 in servicio.fingerprints_exclusivos

    # Desconexión física: el servicio cierra el descriptor y olvida la exclusividad.
    adaptador.simular_desconexion("/dev/input/event0")
    servicio.ejecutar_paso()
    assert servicio.fingerprints_exclusivos == set()

    # Reconexión: el kernel puede asignar otro nodo, pero el fingerprint es el mismo.
    reconectado = adaptador.agregar_dispositivo("/dev/input/event7", FINGERPRINT_DEV01)
    servicio.ejecutar_ciclo_descubrimiento()

    assert adaptador.tiene_exclusividad(reconectado) is True
    assert FINGERPRINT_DEV01 in servicio.fingerprints_exclusivos

    adaptador.simular_evento("/dev/input/event7", _pulsacion(FINGERPRINT_DEV01))
    servicio.ejecutar_paso()
    assert cliente_http.peticiones_enviadas == [{"dispositivo": "dev01", "tecla": "1"}]


def test_remapeo_temporal_reconcilia_quien_queda_capturado(
    entorno_bridge: tuple[ServicioDeviceBridge, AdaptadorFalso, FakeClienteHttp],
) -> None:
    """Demuestra que un remapeo libera el teclado reemplazado y toma el nuevo.

    Escenario: 'dev01' se rompe y se reemplaza por un teclado de repuesto. Después de
    confirmar el remapeo, el repuesto queda dedicado a SISLeg y el teclado anterior deja de
    estar capturado, sin que dos dispositivos se apropien del mismo 'dev01'.
    """
    servicio, adaptador, cliente_http = entorno_bridge

    original = adaptador.agregar_dispositivo("/dev/input/event0", FINGERPRINT_DEV01)
    repuesto = adaptador.agregar_dispositivo("/dev/input/event5", FINGERPRINT_DESCONOCIDO)
    servicio.ejecutar_ciclo_descubrimiento()

    assert adaptador.tiene_exclusividad(original) is True
    assert adaptador.tiene_exclusividad(repuesto) is False

    # Coordinación completa del remapeo TEMPORAL sobre el mismo identificador lógico.
    servicio.coordinador_remapeo.iniciar_captura("remapeo-dev01", "dev01")
    assert (
        servicio.coordinador_remapeo.considerar_candidato(_pulsacion(FINGERPRINT_DESCONOCIDO))
        is not None
    )
    servicio.coordinador_remapeo.confirmar(
        "remapeo-dev01",
        FINGERPRINT_DESCONOCIDO,
        PersistenciaRemapeo.TEMPORAL,
    )

    servicio.ejecutar_paso()

    assert adaptador.tiene_exclusividad(repuesto) is True
    assert adaptador.tiene_exclusividad(original) is False
    assert servicio.fingerprints_exclusivos == {FINGERPRINT_DESCONOCIDO}
    assert adaptador.conteo_liberaciones["/dev/input/event0"] == 1

    # El repuesto despacha como 'dev01' y el teclado anterior ya no despacha nada.
    adaptador.simular_evento("/dev/input/event5", _pulsacion(FINGERPRINT_DESCONOCIDO))
    adaptador.simular_evento("/dev/input/event0", _pulsacion(FINGERPRINT_DEV01, "KEY_9"))
    servicio.ejecutar_paso()

    assert cliente_http.peticiones_enviadas == [{"dispositivo": "dev01", "tecla": "1"}]


def test_detener_libera_la_exclusividad_de_todos_los_dispositivos(
    entorno_bridge: tuple[ServicioDeviceBridge, AdaptadorFalso, FakeClienteHttp],
) -> None:
    """Demuestra que la parada del bridge devuelve los numpads al sistema operativo."""
    servicio, adaptador, _cliente_http = entorno_bridge

    disp_01 = adaptador.agregar_dispositivo("/dev/input/event0", FINGERPRINT_DEV01)
    disp_02 = adaptador.agregar_dispositivo("/dev/input/event1", FINGERPRINT_DEV02)
    servicio.ejecutar_ciclo_descubrimiento()
    assert servicio.fingerprints_exclusivos == {FINGERPRINT_DEV01, FINGERPRINT_DEV02}

    servicio.detener()

    assert adaptador.tiene_exclusividad(disp_01) is False
    assert adaptador.tiene_exclusividad(disp_02) is False
    assert adaptador.dispositivos_exclusivos == set()
    assert servicio.fingerprints_exclusivos == set()
