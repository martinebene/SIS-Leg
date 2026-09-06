"""Cliente HTTP asincrono para la comunicacion con el backend de SIS-Leg (WP-007).

Este modulo implementa el `ClienteBackend`, encargado de:
1. Construir la URL canonica del endpoint de entrada (`/api/v1/entradas/tecla`).
2. Enviar pulsaciones logicas mediante `POST` con cuerpo JSON `{dispositivo, tecla}`.
3. Capturar la respuesta literal completa sin alteraciones.
4. Manejar de forma robusta los errores de conexion, timeouts y caidas de red sin lanzar
   tracebacks incontrolados hacia el usuario.

Pedagogia y convenciones:
- Todo identificador propio en espanol sin tildes ni eñes (DEC-001).
- El cliente no asume ni filtra las respuestas del backend: cualquier codigo HTTP
  (200, 422, 503, etc.) es registrado con su status y cuerpo de texto crudo intacto.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from modelos import PulsacionLogica, RespuestaServidor, ResultadoEnvio

# Ruta canonica definida en DEC-006 / WP-006
RUTA_CANONICA_ENTRADAS = "/api/v1/entradas/tecla"

# URL base por defecto para desarrollo local
URL_BASE_DEFECTO = "http://127.0.0.1:8000"


def componer_url_entradas(url_base: str) -> str:
    """Compone de forma segura la URL completa del endpoint de pulsaciones.

    Garantiza que no haya barras duplicadas entre la URL base y la ruta `/api/v1/entradas/tecla`.

    Ejemplos:
        'http://127.0.0.1:8000' -> 'http://127.0.0.1:8000/api/v1/entradas/tecla'
        'http://localhost:8000/' -> 'http://localhost:8000/api/v1/entradas/tecla'

    Args:
        url_base: URL base del backend especificada por argumento o por defecto.

    Returns:
        URL absoluta completa del endpoint.
    """
    base_limpia = url_base.strip().rstrip("/")
    return f"{base_limpia}{RUTA_CANONICA_ENTRADAS}"


class ClienteBackend:
    """Cliente HTTP asincrono para enviar pulsaciones logicas al backend.

    Utiliza `httpx.AsyncClient` para soportar tanto envios secuenciales como
    grupos concurrentes de pulsaciones en paralelo real.
    """

    def __init__(
        self,
        url_base: str = URL_BASE_DEFECTO,
        timeout_segundos: float = 10.0,
        cliente_httpx: httpx.AsyncClient | None = None,
    ) -> None:
        """Inicializa el cliente del simulador.

        Args:
            url_base: URL base del backend (ejemplo: 'http://127.0.0.1:8000').
            timeout_segundos: Tiempo limite maximo de espera para cada peticion.
            cliente_httpx: Cliente httpx inyectable (util para pruebas con ASGITransport).
        """
        self._url_base = url_base.strip()
        self._url_endpoint = componer_url_entradas(self._url_base)
        self._timeout = timeout_segundos
        self._cliente_inyectado = cliente_httpx
        self._cliente_propio: httpx.AsyncClient | None = None

    @property
    def url_base(self) -> str:
        """Devuelve la URL base configurada."""
        return self._url_base

    @property
    def url_endpoint(self) -> str:
        """Devuelve la URL completa del endpoint de entradas."""
        return self._url_endpoint

    async def _obtener_cliente_httpx(self) -> httpx.AsyncClient:
        """Devuelve una sesion de cliente HTTP activa."""
        if self._cliente_inyectado is not None:
            return self._cliente_inyectado

        if self._cliente_propio is None or self._cliente_propio.is_closed:
            self._cliente_propio = httpx.AsyncClient(timeout=self._timeout)

        return self._cliente_propio

    async def cerrar(self) -> None:
        """Cierra la sesion del cliente HTTP si fue creada internamente."""
        if self._cliente_propio is not None and not self._cliente_propio.is_closed:
            await self._cliente_propio.aclose()
            self._cliente_propio = None

    async def enviar_pulsacion(self, pulsacion: PulsacionLogica) -> ResultadoEnvio:
        """Envia una pulsacion logica al backend y devuelve el resultado detallado.

        Paso a paso:
        1. Prepara el cuerpo JSON `{"dispositivo": "devXX", "tecla": "..."}`.
        2. Mide el tiempo de respuesta ida y vuelta.
        3. Realiza la peticion `POST /api/v1/entradas/tecla`.
        4. Si el servidor responde (incluso con codigos de error 4xx o 5xx),
           extrae el `status_code` y el texto literal crudo (`response.text`).
        5. Si la peticion no puede completarse debido a un fallo de red o timeout,
           captura la excepcion y devuelve un `ResultadoEnvio` con `exito_comunicacion=False`
           y un mensaje claro de diagnostico.

        Args:
            pulsacion: La pulsacion logica a emitir.

        Returns:
            Instancia de ResultadoEnvio con la respuesta recibida o el diagnostico del error.
        """
        cliente = await self._obtener_cliente_httpx()
        cuerpo_json = pulsacion.a_diccionario()
        tiempo_inicio = time.perf_counter()

        try:
            respuesta = await cliente.post(
                self._url_endpoint,
                json=cuerpo_json,
            )
            tiempo_total_ms = (time.perf_counter() - tiempo_inicio) * 1000.0

            # Preservar el texto literal tal como vino del socket
            cuerpo_literal = respuesta.text

            return ResultadoEnvio(
                pulsacion=pulsacion,
                respuesta=RespuestaServidor(
                    status_http=respuesta.status_code,
                    cuerpo_literal=cuerpo_literal,
                    tiempo_respuesta_ms=tiempo_total_ms,
                ),
                error_red=None,
                exito_comunicacion=True,
            )

        except httpx.ConnectError as err:
            return ResultadoEnvio(
                pulsacion=pulsacion,
                respuesta=None,
                error_red=(
                    f"No se pudo establecer conexion con el backend en '{self._url_endpoint}'. "
                    f"Verifique que el servidor FastAPI este corriendo. Detalle: {err}"
                ),
                exito_comunicacion=False,
            )

        except httpx.TimeoutException as err:
            return ResultadoEnvio(
                pulsacion=pulsacion,
                respuesta=None,
                error_red=(
                    f"Tiempo de espera agotado ({self._timeout}s) al comunicarse "
                    f"con '{self._url_endpoint}'. Detalle: {err}"
                ),
                exito_comunicacion=False,
            )

        except httpx.HTTPError as err:
            return ResultadoEnvio(
                pulsacion=pulsacion,
                respuesta=None,
                error_red=f"Error HTTP de transporte al contactar '{self._url_endpoint}': {err}",
                exito_comunicacion=False,
            )

        except Exception as err:  # noqa: BLE001
            return ResultadoEnvio(
                pulsacion=pulsacion,
                respuesta=None,
                error_red=f"Error inesperado al contactar '{self._url_endpoint}': {err}",
                exito_comunicacion=False,
            )

    async def __aenter__(self) -> ClienteBackend:
        """Soporte para uso mediante context manager asincrono."""
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Cierre ordenado de recursos al salir del context manager."""
        await self.cerrar()
