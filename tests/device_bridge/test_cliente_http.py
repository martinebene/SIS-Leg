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
11. NO RECONSTRUCTIBILIDAD DEL SENTIDO DEL VOTO (WP-088): pruebas adversariales que
    demuestran que ningún camino de este cliente deja en el registro la tecla enviada ni
    el cuerpo crudo de la respuesta, en ningún nivel.
12. MOTIVOS CANÓNICOS PERO SENSIBLES (WP-088 I002): regresión de la corrección que
    reemplazó la comprobación de forma por un catálogo explícito, más la redacción de
    `error_transporte` en la estructura y en su representación textual.
"""

from __future__ import annotations

import http.server
import json
import logging
import threading
import urllib.request
from collections.abc import Generator
from typing import Any

import pytest
from sis_leg_device_bridge.cliente_http import ClienteHttpBackend
from sis_leg_device_bridge.modelos import RespuestaEnvioBackend, SolicitudEntradaLogica

# Banca deliberadamente identificable: los tests de WP-088 comprueban que su identidad
# puede aparecer en el registro pero nunca junto al sentido de lo que votó.
DISPOSITIVO_SENSIBLE = "dev07"

# Las tres teclas con semántica de voto. Son el material adversarial del WP: si el
# registro las distingue, el sentido del voto es reconstruible desde el journal.
TECLAS_DE_VOTO = ("1", "2", "3")

# Traducción que usa el servidor de pruebas para fabricar un cuerpo «malicioso» que ecoa el
# sentido del voto en texto claro, como podría hacerlo un backend mal configurado o un
# intermediario. Ninguno de estos textos puede terminar en el registro del bridge.
SENTIDO_POR_TECLA = {"1": "POSITIVO", "2": "ABSTENCION", "3": "NEGATIVO"}

# Nombre del logger del cliente, para acotar la captura y no mezclar otros módulos.
LOGGER_CLIENTE = "sis_leg_device_bridge.cliente_http"


class ServidorPruebaHandler(http.server.BaseHTTPRequestHandler):
    """Manejador HTTP simulado y determinista para las pruebas del cliente."""

    # Contador global de peticiones recibidas
    peticiones_recibidas: list[dict[str, Any]] = []
    codigo_respuesta: int = 200
    cuerpo_respuesta: str = '{"aceptada": true, "motivo": "OK"}'
    demora_segundos: float = 0.0
    # Plantilla opcional usada por las pruebas de WP-088. Cuando está definida, el servidor
    # responde ecoando los datos de la petición (`{dispositivo}`, `{tecla}`, `{valor}`), de
    # modo que el cuerpo de respuesta varía con el voto emitido. Es el escenario adversarial
    # exigido por el WP: si el bridge reprodujera cualquier parte de ese cuerpo, el sentido
    # del voto quedaría en el journal aunque el bridge nunca lo escribiera por su cuenta.
    plantilla_eco: str | None = None

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

        cuerpo_efectivo = self.cuerpo_respuesta
        if self.plantilla_eco is not None:
            solicitud = json.loads(cuerpo_texto)
            tecla_recibida = str(solicitud["tecla"])
            cuerpo_efectivo = self.plantilla_eco.format(
                dispositivo=str(solicitud["dispositivo"]),
                tecla=tecla_recibida,
                valor=SENTIDO_POR_TECLA.get(tecla_recibida, "DESCONOCIDO"),
            )

        try:
            self.send_response(self.codigo_respuesta)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(cuerpo_efectivo.encode("utf-8"))
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
    ServidorPruebaHandler.plantilla_eco = None

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


# ---------------------------------------------------------------------------
# No reconstructibilidad del sentido del voto (WP-088)
#
# La suite anterior comprobaba el resultado funcional de cada camino, no lo que
# quedaba escrito en el registro. Estas pruebas atacan el problema desde la
# propiedad que realmente importa: el journal del bridge no puede distinguir un
# voto POSITIVO de uno NEGATIVO emitido por la misma banca.
#
# Por eso casi todas ejecutan el mismo escenario con las teclas 1, 2 y 3 y exigen
# que la secuencia de mensajes resultante sea **idéntica**. Es una comprobación
# más fuerte que buscar subcadenas prohibidas: no depende de acertar qué formato
# usa el mensaje, y por eso tampoco se rompe cuando el texto cambia. Si dos votos
# distintos producen exactamente el mismo registro, no hay nada que reconstruir.
# ---------------------------------------------------------------------------


def _registrar_envio(
    caplog: pytest.LogCaptureFixture,
    cliente: ClienteHttpBackend,
    tecla: str,
) -> list[tuple[int, str]]:
    """Ejecuta un envío capturando el registro completo del cliente desde DEBUG.

    Args:
        caplog: Fixture de captura de pytest.
        cliente: Cliente bajo prueba.
        tecla: Tecla normalizada a enviar (el material sensible del escenario).

    Returns:
        Lista de pares (nivel, mensaje ya formateado) en el orden en que se emitieron.
    """
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger=LOGGER_CLIENTE):
        cliente.enviar_pulsacion(
            SolicitudEntradaLogica(dispositivo=DISPOSITIVO_SENSIBLE, tecla=tecla)
        )
    return [(registro.levelno, registro.getMessage()) for registro in caplog.records]


def _afirmar_registro_indistinguible(
    cliente: ClienteHttpBackend,
    caplog: pytest.LogCaptureFixture,
    teclas: tuple[str, ...] = TECLAS_DE_VOTO,
) -> list[tuple[int, str]]:
    """Exige que votar 1, 2 o 3 produzca exactamente el mismo registro.

    Es la formulación operativa del criterio de WP-088: si el registro es idéntico para los
    tres sentidos de voto, ninguna combinación de líneas permite deducir cuál se emitió.

    Returns:
        El registro (común a las tres teclas) para que cada prueba verifique además qué
        diagnóstico se conservó.
    """
    registros_por_tecla = {tecla: _registrar_envio(caplog, cliente, tecla) for tecla in teclas}

    referencia = registros_por_tecla[teclas[0]]
    for tecla in teclas[1:]:
        assert registros_por_tecla[tecla] == referencia, (
            f"El registro difiere entre la tecla {teclas[0]!r} y la tecla {tecla!r}: "
            f"el sentido del voto sería reconstruible desde el journal."
        )

    # El registro tampoco puede publicar el valor del campo sensible ni el sentido en texto
    # claro, aunque lo hiciera de forma constante entre teclas. Se buscan las formas en las
    # que un valor queda asignado y no la palabra suelta: el endpoint canónico se llama
    # `/api/v1/entradas/tecla`, así que su nombre aparece legítimamente en el registro.
    texto = "\n".join(mensaje for _nivel, mensaje in referencia)
    for prohibido in ("tecla=", "tecla '", '"tecla"', "POSITIVO", "NEGATIVO", "ABSTENCION"):
        assert prohibido not in texto, f"El registro contiene {prohibido!r}: {texto!r}"

    return referencia


def test_wp088_despacho_debug_no_distingue_el_sentido_del_voto(
    servidor_local_http: tuple[str, type[ServidorPruebaHandler]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """El DEBUG previo al POST identificaba banca y tecla en la misma línea."""
    url_base, handler = servidor_local_http
    handler.codigo_respuesta = 200
    handler.cuerpo_respuesta = json.dumps({"aceptada": True, "motivo": "VOTO_REGISTRADO"})

    cliente = ClienteHttpBackend(url_base=url_base, timeout_segundos=2.0)
    registro = _afirmar_registro_indistinguible(cliente, caplog)

    depuracion = [mensaje for nivel, mensaje in registro if nivel == logging.DEBUG]
    assert len(depuracion) == 1
    # El diagnóstico útil sobrevive: a qué endpoint salió y de qué banca.
    assert "/api/v1/entradas/tecla" in depuracion[0]
    assert DISPOSITIVO_SENSIBLE in depuracion[0]


def test_wp088_aceptacion_no_revela_el_sentido_pese_al_eco_del_backend(
    servidor_local_http: tuple[str, type[ServidorPruebaHandler]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Criterio 7: un backend que ecoa dispositivo, tecla y valor no contamina el registro.

    El servidor responde 200 con un cuerpo que repite literalmente la banca, la tecla y el
    sentido del voto. El cliente debe clasificar la aceptación sin reproducir nada de eso.
    """
    url_base, handler = servidor_local_http
    handler.codigo_respuesta = 200
    handler.plantilla_eco = (
        '{{"aceptada": true, "motivo": "VOTO_REGISTRADO", '
        '"dispositivo": "{dispositivo}", "tecla": "{tecla}", "valor": "{valor}"}}'
    )

    cliente = ClienteHttpBackend(url_base=url_base, timeout_segundos=2.0)
    registro = _afirmar_registro_indistinguible(cliente, caplog)

    informativos = [mensaje for nivel, mensaje in registro if nivel == logging.INFO]
    assert len(informativos) == 1
    # Sigue siendo posible saber que la pulsación fue aceptada, de qué banca y con qué
    # motivo estable: eso es lo que WP-088 exige preservar.
    assert "ACEPTADA" in informativos[0]
    assert DISPOSITIVO_SENSIBLE in informativos[0]
    assert "VOTO_REGISTRADO" in informativos[0]


def test_wp088_rechazo_funcional_conserva_motivo_sin_revelar_sentido(
    servidor_local_http: tuple[str, type[ServidorPruebaHandler]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Un rechazo funcional (200 con aceptada=false) se sigue distinguiendo de una aceptación."""
    url_base, handler = servidor_local_http
    handler.codigo_respuesta = 200
    handler.plantilla_eco = (
        '{{"aceptada": false, "motivo": "VOTO_YA_EMITIDO", '
        '"dispositivo": "{dispositivo}", "tecla": "{tecla}", "valor": "{valor}"}}'
    )

    cliente = ClienteHttpBackend(url_base=url_base, timeout_segundos=2.0)
    registro = _afirmar_registro_indistinguible(cliente, caplog)

    informativos = [mensaje for nivel, mensaje in registro if nivel == logging.INFO]
    assert len(informativos) == 1
    assert "RECHAZADA" in informativos[0]
    assert "VOTO_YA_EMITIDO" in informativos[0]


def test_wp088_respuesta_no_json_no_vuelca_el_cuerpo_crudo(
    servidor_local_http: tuple[str, type[ServidorPruebaHandler]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Un cuerpo que no es JSON es contenido desconocido y no puede registrarse literalmente."""
    url_base, handler = servidor_local_http
    handler.codigo_respuesta = 200
    handler.plantilla_eco = "ERROR: la banca {dispositivo} envio la tecla {tecla} ({valor})"

    cliente = ClienteHttpBackend(url_base=url_base, timeout_segundos=2.0)
    registro = _afirmar_registro_indistinguible(cliente, caplog)

    avisos = [mensaje for nivel, mensaje in registro if nivel == logging.WARNING]
    assert len(avisos) == 1
    assert "no JSON" in avisos[0]
    # Se conserva lo único que no depende de los valores ecoados: que el backend contestó
    # algo. La longitud exacta se omite deliberadamente porque varía con el sentido del
    # voto ecoado y sería un canal lateral suficiente para distinguirlo.
    assert "cuerpo no vacío" in avisos[0]
    assert "la banca" not in avisos[0]


def test_wp088_estructura_json_inesperada_no_vuelca_el_contenido(
    servidor_local_http: tuple[str, type[ServidorPruebaHandler]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Una raíz JSON que no es objeto tampoco se imprime con `%r`."""
    url_base, handler = servidor_local_http
    handler.codigo_respuesta = 200
    handler.plantilla_eco = '["{dispositivo}", "{tecla}", "{valor}"]'

    cliente = ClienteHttpBackend(url_base=url_base, timeout_segundos=2.0)
    registro = _afirmar_registro_indistinguible(cliente, caplog)

    avisos = [mensaje for nivel, mensaje in registro if nivel == logging.WARNING]
    assert len(avisos) == 1
    assert "arreglo JSON con 3 elemento(s)" in avisos[0]


def test_wp088_esquema_invalido_no_vuelca_el_diccionario_recibido(
    servidor_local_http: tuple[str, type[ServidorPruebaHandler]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Un 2xx que incumple el contrato se diagnostica por forma, no por contenido."""
    url_base, handler = servidor_local_http
    handler.codigo_respuesta = 200
    handler.plantilla_eco = (
        '{{"aceptada": "si", "dispositivo": "{dispositivo}", '
        '"tecla": "{tecla}", "valor": "{valor}"}}'
    )

    cliente = ClienteHttpBackend(url_base=url_base, timeout_segundos=2.0)
    registro = _afirmar_registro_indistinguible(cliente, caplog)

    avisos = [mensaje for nivel, mensaje in registro if nivel == logging.WARNING]
    assert len(avisos) == 1
    assert "esquema o tipos inválidos" in avisos[0]
    assert "objeto JSON con 4 clave(s)" in avisos[0]


def test_wp088_error_http_no_vuelca_el_cuerpo_de_error(
    servidor_local_http: tuple[str, type[ServidorPruebaHandler]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Camino más grave del cliente: el 422 de FastAPI ecoa la entrada que rechazó.

    Ese cuerpo contiene el propio `{dispositivo, tecla}` recién enviado, así que volcarlo
    dejaba el voto completo en el registro justamente cuando algo salía mal.
    """
    url_base, handler = servidor_local_http
    handler.codigo_respuesta = 422
    # Forma real de un 422 de validación de FastAPI: sin campo `codigo`, con la entrada
    # rechazada repetida dentro de `detail`.
    handler.plantilla_eco = (
        '{{"detail": [{{"loc": ["body", "tecla"], '
        '"input": {{"dispositivo": "{dispositivo}", "tecla": "{tecla}", "valor": "{valor}"}}}}]}}'
    )

    cliente = ClienteHttpBackend(url_base=url_base, timeout_segundos=2.0)
    registro = _afirmar_registro_indistinguible(cliente, caplog)

    avisos = [mensaje for nivel, mensaje in registro if nivel == logging.WARNING]
    assert len(avisos) == 1
    # El diagnóstico conserva código HTTP, banca y la clasificación del fallo.
    assert "422" in avisos[0]
    assert DISPOSITIVO_SENSIBLE in avisos[0]
    assert "HTTP_422" in avisos[0]


def test_wp088_motivo_de_texto_libre_del_backend_se_redacta(
    servidor_local_http: tuple[str, type[ServidorPruebaHandler]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """El `motivo` es texto de origen externo y podría traer el voto en texto libre.

    Se sanea en el ingreso, así que ni el registro ni el objeto devuelto lo reproducen.
    """
    url_base, handler = servidor_local_http
    handler.codigo_respuesta = 200
    handler.plantilla_eco = (
        '{{"aceptada": true, "motivo": "la banca {dispositivo} voto {valor} con {tecla}"}}'
    )

    cliente = ClienteHttpBackend(url_base=url_base, timeout_segundos=2.0)
    registro = _afirmar_registro_indistinguible(cliente, caplog)

    informativos = [mensaje for nivel, mensaje in registro if nivel == logging.INFO]
    assert len(informativos) == 1
    assert "MOTIVO_DESCONOCIDO" in informativos[0]

    respuesta = cliente.enviar_pulsacion(
        SolicitudEntradaLogica(dispositivo=DISPOSITIVO_SENSIBLE, tecla="1")
    )
    assert respuesta.aceptada is True
    assert respuesta.motivo == "MOTIVO_DESCONOCIDO"


def test_wp088_timeout_no_revela_el_sentido_del_voto(
    servidor_local_http: tuple[str, type[ServidorPruebaHandler]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """El fallo de transporte conserva el detalle de red, que no proviene del backend."""
    url_base, handler = servidor_local_http
    handler.demora_segundos = 0.5

    cliente = ClienteHttpBackend(url_base=url_base, timeout_segundos=0.1)
    registro = _afirmar_registro_indistinguible(cliente, caplog, teclas=("1", "3"))

    errores = [mensaje for nivel, mensaje in registro if nivel == logging.ERROR]
    assert len(errores) == 1
    assert "TIMEOUT" in errores[0]
    assert DISPOSITIVO_SENSIBLE in errores[0]


def test_wp088_error_de_conexion_no_revela_el_sentido_del_voto(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Sin servidor escuchando, el diagnóstico de red se conserva íntegro y sin tecla."""
    cliente = ClienteHttpBackend(url_base="http://127.0.0.1:59999", timeout_segundos=0.5)
    registro = _afirmar_registro_indistinguible(cliente, caplog)

    errores = [mensaje for nivel, mensaje in registro if nivel == logging.ERROR]
    assert len(errores) == 1
    assert "ERROR_CONEXION" in errores[0]
    assert "detalle=" in errores[0]


def test_wp088_excepcion_inesperada_registra_el_tipo_y_no_su_texto(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """El `except Exception` general no puede confiar en el texto de la excepción.

    Varias excepciones de ese camino citan literalmente el fragmento que no pudieron
    procesar, así que registrar `str(error)` reabriría la filtración por una vía indirecta.
    Se conserva el tipo, que es lo que orienta el diagnóstico.
    """

    def urlopen_que_falla(*_args: Any, **_kwargs: Any) -> Any:
        raise ValueError(f"la banca {DISPOSITIVO_SENSIBLE} envio la tecla 1 (POSITIVO)")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen_que_falla)

    cliente = ClienteHttpBackend(url_base="http://127.0.0.1:59999", timeout_segundos=0.5)
    registro = _afirmar_registro_indistinguible(cliente, caplog)

    errores = [mensaje for nivel, mensaje in registro if nivel == logging.ERROR]
    assert len(errores) == 1
    assert "tipo=ValueError" in errores[0]
    assert "la banca" not in errores[0]


def test_wp088_ningun_camino_del_cliente_serializa_el_payload(
    servidor_local_http: tuple[str, type[ServidorPruebaHandler]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Criterio 2, comprobado de forma transversal sobre todos los códigos de respuesta.

    Se recorre una batería de respuestas distintas y se exige, para cada una, que el
    registro completo sea el mismo para las tres teclas de voto. Es la red de seguridad que
    detecta una filtración nueva introducida en cualquier rama futura de este cliente.
    """
    url_base, handler = servidor_local_http

    escenarios: list[tuple[int, str]] = [
        (200, '{{"aceptada": true, "motivo": "VOTO_REGISTRADO", "eco": "{tecla}/{valor}"}}'),
        (200, '{{"aceptada": false, "motivo": "CONCEJAL_AUSENTE", "eco": "{tecla}/{valor}"}}'),
        (200, "texto plano {dispositivo} {tecla} {valor}"),
        (422, '{{"detail": [{{"input": {{"tecla": "{tecla}", "valor": "{valor}"}}}}]}}'),
        (500, '{{"codigo": "ERROR_INTERNO", "eco": "{tecla}/{valor}"}}'),
        (503, '{{"codigo": "AUDITORIA_NO_DISPONIBLE", "eco": "{tecla}/{valor}"}}'),
    ]

    cliente = ClienteHttpBackend(url_base=url_base, timeout_segundos=2.0)
    for codigo, plantilla in escenarios:
        handler.codigo_respuesta = codigo
        handler.plantilla_eco = plantilla
        _afirmar_registro_indistinguible(cliente, caplog)


# ---------------------------------------------------------------------------
# Regresión de la corrección I002: motivos canónicos pero sensibles
#
# La primera versión de `sanear_motivo` aceptaba cualquier texto con forma de
# código estable. Las pruebas de I001 sólo la atacaban con texto libre en
# minúsculas, así que no cubrían la clase de valores que la regex sí aceptaba:
# `DEV07_VOTO_1` respeta MAYUSCULAS_CON_GUION_BAJO y reconstruye el voto.
#
# Estas pruebas fijan la propiedad correcta: el bridge sólo reproduce motivos
# que figuran en un catálogo explícito, y todo lo demás queda clasificado.
# ---------------------------------------------------------------------------


def test_i002_motivo_canonico_pero_sensible_no_llega_al_registro(
    servidor_local_http: tuple[str, type[ServidorPruebaHandler]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Escenario exacto señalado por la auditoría: 2xx con `motivo="DEV07_VOTO_1"`.

    El valor respeta la sintaxis de un código estable, así que la comprobación de forma lo
    dejaba pasar intacto al registro junto al dispositivo lógico.
    """
    url_base, handler = servidor_local_http
    handler.codigo_respuesta = 200
    handler.cuerpo_respuesta = json.dumps({"aceptada": True, "motivo": "DEV07_VOTO_1"})

    cliente = ClienteHttpBackend(url_base=url_base, timeout_segundos=2.0)
    registro = _afirmar_registro_indistinguible(cliente, caplog)

    texto = "\n".join(mensaje for _nivel, mensaje in registro)
    assert "DEV07_VOTO_1" not in texto
    assert "MOTIVO_DESCONOCIDO" in texto

    respuesta = cliente.enviar_pulsacion(
        SolicitudEntradaLogica(dispositivo=DISPOSITIVO_SENSIBLE, tecla="1")
    )
    assert respuesta.aceptada is True
    assert respuesta.motivo == "MOTIVO_DESCONOCIDO"


def test_i002_motivos_sensibles_distintos_por_sentido_producen_el_mismo_registro(
    servidor_local_http: tuple[str, type[ServidorPruebaHandler]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """El caso más agresivo: el backend nombra el sentido del voto en el propio motivo.

    Cada tecla recibe un motivo distinto y con forma canónica: `VOTO_POSITIVO_DEV07`,
    `VOTO_ABSTENCION_DEV07` y `VOTO_NEGATIVO_DEV07`. Con la comprobación de forma, las tres
    líneas de INFO eran distintas entre sí y decían literalmente cómo votó `dev07`.
    """
    url_base, handler = servidor_local_http
    handler.codigo_respuesta = 200
    handler.plantilla_eco = '{{"aceptada": true, "motivo": "VOTO_{valor}_DEV07"}}'

    cliente = ClienteHttpBackend(url_base=url_base, timeout_segundos=2.0)
    registro = _afirmar_registro_indistinguible(cliente, caplog)

    texto = "\n".join(mensaje for _nivel, mensaje in registro)
    for prohibido in ("VOTO_POSITIVO_DEV07", "VOTO_ABSTENCION_DEV07", "VOTO_NEGATIVO_DEV07"):
        assert prohibido not in texto
    assert "MOTIVO_DESCONOCIDO" in texto


def test_i002_codigo_de_error_canonico_pero_sensible_no_llega_al_registro(
    servidor_local_http: tuple[str, type[ServidorPruebaHandler]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """La misma clase de valor podía entrar por el campo `codigo` de una respuesta de error.

    Ese camino toma el código del cuerpo como motivo del fallo, así que compartía el
    defecto con el camino 2xx.
    """
    url_base, handler = servidor_local_http
    handler.codigo_respuesta = 503
    handler.plantilla_eco = '{{"codigo": "DEV07_TECLA_{tecla}", "mensaje": "rechazo"}}'

    cliente = ClienteHttpBackend(url_base=url_base, timeout_segundos=2.0)
    registro = _afirmar_registro_indistinguible(cliente, caplog)

    texto = "\n".join(mensaje for _nivel, mensaje in registro)
    for tecla in TECLAS_DE_VOTO:
        assert f"DEV07_TECLA_{tecla}" not in texto
    # El diagnóstico técnico sobrevive: se sabe que hubo un 503 en esa banca.
    assert "503" in texto
    assert DISPOSITIVO_SENSIBLE in texto
    assert "MOTIVO_DESCONOCIDO" in texto


def test_i002_el_campo_motivo_de_un_error_tambien_se_clasifica(
    servidor_local_http: tuple[str, type[ServidorPruebaHandler]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Variante por el campo `motivo` de la respuesta de error, no por `codigo`."""
    url_base, handler = servidor_local_http
    handler.codigo_respuesta = 500
    handler.plantilla_eco = '{{"motivo": "ABSTENCION_BANCA_7_TECLA_{tecla}"}}'

    cliente = ClienteHttpBackend(url_base=url_base, timeout_segundos=2.0)
    registro = _afirmar_registro_indistinguible(cliente, caplog)

    texto = "\n".join(mensaje for _nivel, mensaje in registro)
    assert "ABSTENCION_BANCA_7" not in texto
    assert "500" in texto
    assert "MOTIVO_DESCONOCIDO" in texto


def test_i002_un_motivo_conocido_sigue_llegando_intacto(
    servidor_local_http: tuple[str, type[ServidorPruebaHandler]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """La corrección no puede convertirse en silencio de diagnóstico.

    Un motivo real del backend tiene que seguir apareciendo tal cual: si todo terminara
    clasificado, soporte perdería la única etiqueta que distingue por qué se rechazó una
    pulsación.
    """
    url_base, handler = servidor_local_http
    handler.codigo_respuesta = 200
    handler.cuerpo_respuesta = json.dumps({"aceptada": False, "motivo": "CONCEJAL_AUSENTE"})

    cliente = ClienteHttpBackend(url_base=url_base, timeout_segundos=2.0)
    registro = _afirmar_registro_indistinguible(cliente, caplog)

    informativos = [mensaje for nivel, mensaje in registro if nivel == logging.INFO]
    assert len(informativos) == 1
    assert "RECHAZADA" in informativos[0]
    assert "CONCEJAL_AUSENTE" in informativos[0]
    assert "MOTIVO_DESCONOCIDO" not in informativos[0]


def test_i002_el_repr_de_la_respuesta_no_reproduce_error_transporte(
    servidor_local_http: tuple[str, type[ServidorPruebaHandler]],
) -> None:
    """El `repr` se presentó en I001 como defensa ante logging accidental, así que debe serlo.

    `error_transporte` era el único campo que seguía imprimiéndose crudo. Hoy `cliente_http`
    sólo le asigna texto propio o detalle del sistema operativo, pero una red que depende de
    la disciplina de quien llena el campo no protege de un cambio futuro.
    """
    respuesta = RespuestaEnvioBackend(
        aceptada=None,
        codigo_http=None,
        motivo="ERROR_INESPERADO",
        cuerpo=None,
        error_transporte="dev07 tecla 1 POSITIVO",
    )

    for texto in (repr(respuesta), f"{respuesta}", str(respuesta)):
        assert "dev07" not in texto
        assert "POSITIVO" not in texto
        assert "tecla 1" not in texto

    # Sigue siendo posible distinguir un fallo de transporte de un resultado limpio.
    assert "ERROR_INESPERADO" in repr(respuesta)
    assert "error_transporte=None" not in repr(respuesta)
    assert "error_transporte=None" in repr(
        RespuestaEnvioBackend(aceptada=True, codigo_http=200, motivo="VOTO_REGISTRADO")
    )


def test_i002_la_excepcion_inesperada_no_guarda_su_texto_en_la_estructura(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La otra mitad de la corrección: el campo tampoco debe recibir el texto.

    Redactar sólo en el `repr` dejaría el dato guardado dentro del objeto, a un `print` de
    distancia del journal. Se guarda el tipo, que es la misma información que se registra.
    """

    def urlopen_que_falla(*_args: Any, **_kwargs: Any) -> Any:
        raise ValueError("la banca dev07 envio la tecla 1 (POSITIVO)")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen_que_falla)

    cliente = ClienteHttpBackend(url_base="http://127.0.0.1:59999", timeout_segundos=0.5)
    respuesta = cliente.enviar_pulsacion(
        SolicitudEntradaLogica(dispositivo=DISPOSITIVO_SENSIBLE, tecla="1")
    )

    assert respuesta.motivo == "ERROR_INESPERADO"
    assert respuesta.error_transporte == "Excepción inesperada de tipo ValueError"
    assert "la banca" not in str(respuesta.error_transporte)
