"""Pruebas del cliente HTTP del bridge hacia el backend FastAPI.

Verifica:
1. Envío mediante POST a la ruta exacta `/api/v1/entradas/tecla`.
2. Cabecera `Content-Type: application/json`.
3. Cuerpo JSON exacto `{"dispositivo": "devXX", "tecla": "..."}`.
4. Procesamiento de respuesta 200 con `aceptada=true`.
5. Procesamiento de respuesta 200 con `aceptada=false` (rechazo funcional).
6. Procesamiento de errores HTTP 422, 503 y 500.
7. Manejo de conexión rechazada y servidor caído.
8. Manejo de timeout configurado.
9. Manejo de cuerpo no JSON o corrupto.
10. REGLA CRÍTICA DE CERO REINTENTOS: Demostración de que cada fallo genera
    exactamente un intento HTTP.
"""

from __future__ import annotations

import http.server
import json
import threading
from collections.abc import Generator
from typing import Any

import pytest
from sis_leg_device_bridge.cliente_http import ClienteHttpBackend
from sis_leg_device_bridge.modelos import SolicitudEntradaLogica


class ServidorPruebaHandler(http.server.BaseHTTPRequestHandler):
    """Manejador HTTP simulado y determinista para las pruebas del cliente."""

    # Contador global de peticiones recibidas
    peticiones_recibidas: list[dict[str, Any]] = []
    codigo_respuesta: int = 200
    cuerpo_respuesta: str = '{"aceptada": true, "motivo": "OK"}'
    demora_segundos: float = 0.0

    def do_POST(self) -> None:  # noqa: N802
        import time

        longitud = int(self.headers.get("Content-Length", 0))
        cuerpo_bytes = self.rfile.read(longitud)
        cuerpo_texto = cuerpo_bytes.decode("utf-8")

        peticion_info = {
            "path": self.path,
            "content_type": self.headers.get("Content-Type"),
            "cuerpo_texto": cuerpo_texto,
        }
        self.peticiones_recibidas.append(peticion_info)

        if self.demora_segundos > 0:
            time.sleep(self.demora_segundos)

        try:
            self.send_response(self.codigo_respuesta)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(self.cuerpo_respuesta.encode("utf-8"))
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # Silenciar logs del servidor HTTP interno durante los tests
        pass


@pytest.fixture
def servidor_local_http() -> Generator[tuple[str, type[ServidorPruebaHandler]]]:
    """Levanta un servidor HTTP local en un hilo de fondo y devuelve (url_base, Handler)."""
    ServidorPruebaHandler.peticiones_recibidas = []
    ServidorPruebaHandler.codigo_respuesta = 200
    ServidorPruebaHandler.cuerpo_respuesta = '{"aceptada": true, "motivo": "PRESENCIA_ACTUALIZADA"}'
    ServidorPruebaHandler.demora_segundos = 0.0

    servidor = http.server.HTTPServer(("127.0.0.1", 0), ServidorPruebaHandler)
    puerto = servidor.server_address[1]
    url_base = f"http://127.0.0.1:{puerto}"

    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()

    yield url_base, ServidorPruebaHandler

    servidor.shutdown()
    servidor.server_close()


def test_envio_exitoso_aceptada_true(
    servidor_local_http: tuple[str, type[ServidorPruebaHandler]],
) -> None:
    """Demuestra el envío correcto de una pulsación aceptada por el backend."""
    url_base, handler = servidor_local_http
    handler.codigo_respuesta = 200
    handler.cuerpo_respuesta = json.dumps(
        {
            "aceptada": True,
            "motivo": "PRESENCIA_ACTUALIZADA",
            "dispositivo": "dev01",
            "tecla": "9",
        }
    )

    cliente = ClienteHttpBackend(url_base=url_base, timeout_segundos=2.0)
    solicitud = SolicitudEntradaLogica(dispositivo="dev01", tecla="9")
    respuesta = cliente.enviar_pulsacion(solicitud)

    # Validar solicitud recibida por el servidor
    assert len(handler.peticiones_recibidas) == 1
    peticion = handler.peticiones_recibidas[0]
    assert peticion["path"] == "/api/v1/entradas/tecla"
    assert peticion["content_type"] == "application/json"
    assert json.loads(peticion["cuerpo_texto"]) == {"dispositivo": "dev01", "tecla": "9"}

    # Validar resultado
    assert respuesta.aceptada is True
    assert respuesta.codigo_http == 200
    assert respuesta.motivo == "PRESENCIA_ACTUALIZADA"
    assert respuesta.error_transporte is None


def test_envio_rechazo_funcional_aceptada_false(
    servidor_local_http: tuple[str, type[ServidorPruebaHandler]],
) -> None:
    """Demuestra que una pulsación rechazada funcionalmente (200 aceptada=false) se registra."""
    url_base, handler = servidor_local_http
    handler.codigo_respuesta = 200
    handler.cuerpo_respuesta = json.dumps(
        {
            "aceptada": False,
            "motivo": "TECLA_NO_HABILITADA",
            "dispositivo": "dev01",
            "tecla": "1",
        }
    )

    cliente = ClienteHttpBackend(url_base=url_base, timeout_segundos=2.0)
    solicitud = SolicitudEntradaLogica(dispositivo="dev01", tecla="1")
    respuesta = cliente.enviar_pulsacion(solicitud)

    assert len(handler.peticiones_recibidas) == 1
    assert respuesta.aceptada is False
    assert respuesta.codigo_http == 200
    assert respuesta.motivo == "TECLA_NO_HABILITADA"


def test_error_http_422(servidor_local_http: tuple[str, type[ServidorPruebaHandler]]) -> None:
    """Demuestra el manejo de error HTTP 422 (Unprocessable Entity).

    Conforme a I-2, un error HTTP no es un rechazo de dominio (aceptada=None).
    """
    url_base, handler = servidor_local_http
    handler.codigo_respuesta = 422
    handler.cuerpo_respuesta = json.dumps({"detail": [{"msg": "Field required"}]})

    cliente = ClienteHttpBackend(url_base=url_base, timeout_segundos=2.0)
    respuesta = cliente.enviar_pulsacion(SolicitudEntradaLogica(dispositivo="dev01", tecla="1"))

    assert len(handler.peticiones_recibidas) == 1
    assert respuesta.aceptada is None
    assert respuesta.codigo_http == 422
    assert "422" in respuesta.motivo


def test_error_http_503_auditoria_no_disponible(
    servidor_local_http: tuple[str, type[ServidorPruebaHandler]],
) -> None:
    """Demuestra el manejo de error HTTP 503 cuando la auditoría no está disponible.

    Conforme a I-2, HTTP 503 es un fallo de servicio, no un rechazo funcional (aceptada=None).
    """
    url_base, handler = servidor_local_http
    handler.codigo_respuesta = 503
    handler.cuerpo_respuesta = json.dumps(
        {
            "codigo": "AUDITORIA_NO_DISPONIBLE",
            "mensaje": "Fallo en persistencia de logs",
        }
    )

    cliente = ClienteHttpBackend(url_base=url_base, timeout_segundos=2.0)
    respuesta = cliente.enviar_pulsacion(SolicitudEntradaLogica(dispositivo="dev01", tecla="9"))

    assert len(handler.peticiones_recibidas) == 1
    assert respuesta.aceptada is None
    assert respuesta.codigo_http == 503
    assert respuesta.motivo == "AUDITORIA_NO_DISPONIBLE"


def test_error_http_500_error_interno(
    servidor_local_http: tuple[str, type[ServidorPruebaHandler]],
) -> None:
    """Demuestra el manejo de error HTTP 500 (aceptada=None)."""
    url_base, handler = servidor_local_http
    handler.codigo_respuesta = 500
    handler.cuerpo_respuesta = json.dumps(
        {
            "codigo": "ERROR_INTERNO",
            "mensaje": "Fallo inesperado",
        }
    )

    cliente = ClienteHttpBackend(url_base=url_base, timeout_segundos=2.0)
    respuesta = cliente.enviar_pulsacion(SolicitudEntradaLogica(dispositivo="dev01", tecla="1"))

    assert len(handler.peticiones_recibidas) == 1
    assert respuesta.aceptada is None
    assert respuesta.codigo_http == 500
    assert respuesta.motivo == "ERROR_INTERNO"


@pytest.mark.parametrize(
    ("cuerpo_invalido", "motivo_esperado"),
    [
        ('{"motivo": "OK"}', "RESPUESTA_INVALIDA"),  # Falta 'aceptada'
        ('{"aceptada": "false", "motivo": "OK"}', "RESPUESTA_INVALIDA"),  # 'aceptada' es string
        ('{"aceptada": 1, "motivo": "OK"}', "RESPUESTA_INVALIDA"),  # 'aceptada' es entero
        ('{"aceptada": 0, "motivo": "OK"}', "RESPUESTA_INVALIDA"),  # 'aceptada' es entero 0
        ('{"aceptada": true}', "RESPUESTA_INVALIDA"),  # Falta 'motivo'
        ('{"aceptada": true, "motivo": 123}', "RESPUESTA_INVALIDA"),  # 'motivo' no es string
        ('["elemento1", "elemento2"]', "ESTRUCTURA_RESPUESTA_INVALIDA"),  # Raíz no objeto
        ("esto no es un json", "RESPUESTA_NO_JSON"),  # JSON inválido
    ],
)
def test_respuestas_2xx_protocolo_invalido(
    servidor_local_http: tuple[str, type[ServidorPruebaHandler]],
    cuerpo_invalido: str,
    motivo_esperado: str,
) -> None:
    """Demuestra que 2xx malformados se clasifican como error de protocolo con aceptada=None."""
    url_base, handler = servidor_local_http
    handler.codigo_respuesta = 200
    handler.cuerpo_respuesta = cuerpo_invalido

    cliente = ClienteHttpBackend(url_base=url_base, timeout_segundos=2.0)
    respuesta = cliente.enviar_pulsacion(SolicitudEntradaLogica(dispositivo="dev01", tecla="1"))

    assert len(handler.peticiones_recibidas) == 1
    assert respuesta.aceptada is None
    assert respuesta.codigo_http == 200
    assert respuesta.motivo == motivo_esperado
    assert respuesta.error_transporte is not None


def test_error_conexion_servidor_caido() -> None:
    """Demuestra que la indisponibilidad de conexión se diagnostica con un único intento."""
    # Usamos un puerto donde no haya ningún servidor escuchando
    cliente = ClienteHttpBackend(url_base="http://127.0.0.1:59999", timeout_segundos=0.5)
    respuesta = cliente.enviar_pulsacion(SolicitudEntradaLogica(dispositivo="dev01", tecla="1"))

    assert respuesta.aceptada is None
    assert respuesta.codigo_http is None
    assert respuesta.motivo == "ERROR_CONEXION"
    assert respuesta.error_transporte is not None


def test_timeout_configurado(servidor_local_http: tuple[str, type[ServidorPruebaHandler]]) -> None:
    """Demuestra que si el servidor excede el timeout se diagnostica y NO se reintenta."""
    url_base, handler = servidor_local_http
    handler.demora_segundos = 0.5  # Demora mayor que el timeout de 0.1 s

    cliente = ClienteHttpBackend(url_base=url_base, timeout_segundos=0.1)
    respuesta = cliente.enviar_pulsacion(SolicitudEntradaLogica(dispositivo="dev01", tecla="1"))

    assert len(handler.peticiones_recibidas) == 1  # EXACTAMENTE 1 intento
    assert respuesta.aceptada is None
    assert respuesta.codigo_http is None
    assert respuesta.motivo == "TIMEOUT"
