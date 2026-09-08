"""Cliente HTTP liviano para el bridge de dispositivos usando biblioteca estándar.

Conforme a DEC-015 y WP-019:
1. Utiliza exclusivamente la biblioteca estándar de Python (`urllib.request`).
   No agrega `requests`, `httpx` ni frameworks de transporte.
2. Endpoint canónico exacto: `POST /api/v1/entradas/tecla`.
3. Cabecera exacta: `Content-Type: application/json`.
4. Cuerpo exacto: `{"dispositivo": "devXX", "tecla": "<tecla_normalizada>"}`.
5. REGLA CRÍTICA DE CERO REINTENTOS:
   Cada evento físico de pulsación genera como máximo UN intento HTTP. Ante cualquier
   fallo (timeout, conexión rechazada, reset, 4xx, 5xx, cuerpo inválido), NUNCA se
   reintenta automáticamente.
   Motivo institucional: El backend puede haber procesado la acción aunque la respuesta
   se haya perdido. Un reintento podría duplicar votos, revertir estados de presencia o
   alterar turnos de palabra de forma no idempotente.
6. Diferencia claramente en el resultado:
   - 2xx con `aceptada=true`
   - 2xx con `aceptada=false`
   - 4xx (ej: 422 contrato de esquema inválido)
   - 5xx (ej: 503 auditoría no disponible, 500 error interno)
   - Error de transporte / conexión
   - Timeout
   - Respuesta no JSON o inesperada
7. REGLA DE NO RECONSTRUCTIBILIDAD DEL VOTO (WP-088):
   Ningún registro de este cliente contiene `solicitud.tecla`, el payload serializado ni
   el cuerpo crudo de la respuesta. El par `{dispositivo, tecla}` que viaja al backend es
   exactamente la combinación que permitiría deducir el sentido del voto de una banca
   identificable desde el journal, antes de la frontera autoritativa de revelado.
   Se conserva todo el diagnóstico que no reconstruye ese sentido: endpoint, dispositivo
   lógico, código HTTP, clase de resultado, motivo estable y forma del cuerpo recibido.
   Ver `redaccion.py`.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, cast

from sis_leg_device_bridge.modelos import RespuestaEnvioBackend, SolicitudEntradaLogica
from sis_leg_device_bridge.redaccion import (
    describir_cuerpo_crudo,
    describir_cuerpo_json,
    sanear_motivo,
)

logger = logging.getLogger(__name__)
REGISTRO = logger


class ClienteHttpBackend:
    """Cliente HTTP síncrono y determinista para enviar pulsaciones a FastAPI."""

    def __init__(
        self,
        url_base: str = "http://127.0.0.1:8000",
        timeout_segundos: float = 3.0,
    ) -> None:
        """Inicializa el cliente con la URL base del backend y timeout estricto.

        Args:
            url_base: URL base donde escucha FastAPI (ej: 'http://127.0.0.1:8000').
            timeout_segundos: Tiempo límite máximo en segundos para la conexión y lectura.
        """
        self.url_base = url_base.rstrip("/")
        self.timeout_segundos = timeout_segundos
        self.url_endpoint = f"{self.url_base}/api/v1/entradas/tecla"

    def informar_candidato(
        self,
        remapeo_id: str,
        fingerprint: str,
        diagnostico: str,
    ) -> bool:
        """Informa una vez el candidato al callback interno de FastAPI.

        Este envío no es una pulsación funcional y tampoco aplica el mapping.
        El candidato ya queda congelado localmente antes de llamar; si el
        backend no está disponible, el estado continúa consultable por la API
        de control con el mismo ``remapeo_id``.
        """

        url = f"{self.url_base}/api/v1/interno/remapeos/{remapeo_id}/candidato"
        cuerpo = json.dumps({"fingerprint": fingerprint, "diagnostico": diagnostico}).encode(
            "utf-8"
        )
        peticion = urllib.request.Request(
            url=url,
            data=cuerpo,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(peticion, timeout=self.timeout_segundos) as respuesta:
                respuesta.read()
                return 200 <= respuesta.getcode() < 300
        except Exception as error:
            REGISTRO.error(
                "No se pudo informar candidato de remapeo_id=%s: %s",
                remapeo_id,
                error,
            )
            return False

    def enviar_pulsacion(self, solicitud: SolicitudEntradaLogica) -> RespuestaEnvioBackend:
        """Envía una única pulsación al backend mediante POST.

        REGLA CRÍTICA: No efectúa ningún reintento ante fallos.

        Args:
            solicitud: Contenedor con 'dispositivo' ('devXX') y 'tecla' ('1'..'9', etc.).

        Returns:
            RespuestaEnvioBackend con la clasificación detallada del resultado.
        """
        cuerpo_bytes = json.dumps(solicitud.a_diccionario()).encode("utf-8")
        peticion = urllib.request.Request(
            url=self.url_endpoint,
            data=cuerpo_bytes,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        # WP-088: se registra a qué endpoint y para qué dispositivo lógico sale la
        # petición, nunca qué tecla lleva. Saber que `dev07` despachó una pulsación no
        # revela su voto; saber que despachó la tecla `1` sí lo revelaría.
        logger.debug(
            "Enviando POST a %s para %s",
            self.url_endpoint,
            solicitud.dispositivo,
        )

        try:
            with urllib.request.urlopen(peticion, timeout=self.timeout_segundos) as respuesta:
                codigo_http = respuesta.getcode()
                cuerpo_crudo = respuesta.read().decode("utf-8")

                cuerpo_json: Any = None
                try:
                    cuerpo_json = json.loads(cuerpo_crudo) if cuerpo_crudo.strip() else {}
                except json.JSONDecodeError:
                    # WP-088: se describe la forma del cuerpo, nunca su texto. Un
                    # cuerpo que el bridge no pudo parsear es contenido desconocido y
                    # puede arrastrar la tecla enviada o la identidad de la banca.
                    logger.warning(
                        "Backend respondió HTTP %d con cuerpo no JSON para %s (cuerpo %s)",
                        codigo_http,
                        solicitud.dispositivo,
                        describir_cuerpo_crudo(cuerpo_crudo),
                    )
                    return RespuestaEnvioBackend(
                        aceptada=None,
                        codigo_http=codigo_http,
                        motivo="RESPUESTA_NO_JSON",
                        cuerpo=None,
                        error_transporte="El cuerpo de respuesta no es JSON válido",
                    )

                if not isinstance(cuerpo_json, dict):
                    logger.warning(
                        "Backend respondió HTTP %d con estructura JSON inesperada para %s (%s)",
                        codigo_http,
                        solicitud.dispositivo,
                        describir_cuerpo_json(cuerpo_json),
                    )
                    return RespuestaEnvioBackend(
                        aceptada=None,
                        codigo_http=codigo_http,
                        motivo="ESTRUCTURA_RESPUESTA_INVALIDA",
                        cuerpo=None,
                        error_transporte="La raíz de la respuesta JSON debe ser un objeto",
                    )

                cuerpo_dict = cast(dict[str, Any], cuerpo_json)

                # Validación estricta del contrato funcional (I-2):
                # 'aceptada' DEBE existir y ser de tipo bool nativo
                # (no coerción bool("false") ni enteros 1/0).
                # 'motivo' DEBE existir y ser de tipo str.
                valor_aceptada = cuerpo_dict.get("aceptada")
                valor_motivo = cuerpo_dict.get("motivo")

                if type(valor_aceptada) is not bool or not isinstance(valor_motivo, str):
                    logger.warning(
                        "Backend respondió HTTP %d con esquema o tipos inválidos para %s (%s)",
                        codigo_http,
                        solicitud.dispositivo,
                        describir_cuerpo_json(cuerpo_dict),
                    )
                    return RespuestaEnvioBackend(
                        aceptada=None,
                        codigo_http=codigo_http,
                        motivo="RESPUESTA_INVALIDA",
                        cuerpo=cuerpo_dict,
                        error_transporte=(
                            "El cuerpo JSON 2xx no cumple el contrato "
                            "('aceptada': bool, 'motivo': str)"
                        ),
                    )

                aceptada = valor_aceptada
                # WP-088: el motivo llega dentro del cuerpo del backend, así que es texto
                # externo. Se sanea acá, en el ingreso, para que el valor que guarda
                # `RespuestaEnvioBackend` ya sea seguro para cualquier consumidor posterior.
                motivo = sanear_motivo(valor_motivo)

                # WP-088: aceptación y rechazo siguen siendo distinguibles por el mensaje,
                # el dispositivo y el motivo estable. Lo único que desaparece es la tecla,
                # que es lo que convertía estas dos líneas en el sentido del voto.
                if aceptada:
                    logger.info(
                        "Pulsación ACEPTADA: dispositivo=%s, motivo=%s",
                        solicitud.dispositivo,
                        motivo,
                    )
                else:
                    logger.info(
                        "Pulsación RECHAZADA: dispositivo=%s, motivo=%s",
                        solicitud.dispositivo,
                        motivo,
                    )

                return RespuestaEnvioBackend(
                    aceptada=aceptada,
                    codigo_http=codigo_http,
                    motivo=motivo,
                    cuerpo=cuerpo_dict,
                )

        except urllib.error.HTTPError as error_http:
            codigo_http = error_http.code
            cuerpo_error_crudo = ""
            cuerpo_error_json: dict[str, Any] | None = None
            try:
                cuerpo_error_crudo = error_http.read().decode("utf-8")
                cuerpo_error_json = json.loads(cuerpo_error_crudo)
            except Exception:
                cuerpo_error_json = None

            motivo_error = f"HTTP_{codigo_http}"
            if isinstance(cuerpo_error_json, dict):
                if "codigo" in cuerpo_error_json and isinstance(cuerpo_error_json["codigo"], str):
                    motivo_error = sanear_motivo(cuerpo_error_json["codigo"])
                elif "motivo" in cuerpo_error_json and isinstance(cuerpo_error_json["motivo"], str):
                    motivo_error = sanear_motivo(cuerpo_error_json["motivo"])

            # WP-088: este era el peor volcado del cliente. El cuerpo de un 422 de FastAPI
            # incluye en `detail` la entrada rechazada, es decir el propio
            # `{"dispositivo": ..., "tecla": ...}` recién enviado: el camino de error dejaba
            # el voto completo en el journal. Ahora sólo se describe su forma.
            logger.warning(
                "Backend respondió error HTTP %d para %s: motivo=%s (cuerpo %s)",
                codigo_http,
                solicitud.dispositivo,
                motivo_error,
                describir_cuerpo_crudo(cuerpo_error_crudo),
            )

            # En HTTP 4xx/5xx (incluido 422, 500, 503), NO es una decisión de dominio
            # por lo que se reporta con aceptada=None conforme a I-2.
            return RespuestaEnvioBackend(
                aceptada=None,
                codigo_http=codigo_http,
                motivo=motivo_error,
                cuerpo=cuerpo_error_json,
                error_transporte=f"Error HTTP {codigo_http}",
            )

        except (TimeoutError, urllib.error.URLError) as error_red:
            # En urllib, un timeout se manifiesta a menudo como URLError(reason=TimeoutError())
            if isinstance(error_red, urllib.error.URLError):
                detalle = str(error_red.reason)
            else:
                detalle = str(error_red)

            es_timeout = isinstance(error_red, TimeoutError) or "timed out" in detalle.lower()
            motivo = "TIMEOUT" if es_timeout else "ERROR_CONEXION"

            # WP-088: `detalle` viene del sistema operativo o de urllib (por ejemplo
            # «Connection refused» o «timed out»), no del cuerpo del backend, así que se
            # conserva completo: es el diagnóstico de red que soporte necesita.
            logger.error(
                "Fallo de transporte al enviar pulsación (%s): motivo=%s, detalle=%s",
                solicitud.dispositivo,
                motivo,
                detalle,
            )

            return RespuestaEnvioBackend(
                aceptada=None,
                codigo_http=None,
                motivo=motivo,
                cuerpo=None,
                error_transporte=detalle,
            )

        except Exception as error_inesperado:
            # WP-088: se registra el tipo de excepción y no su texto. Este `except` atrapa,
            # entre otras, la decodificación del cuerpo de respuesta, y varios errores de
            # ese tipo citan literalmente el fragmento que no pudieron procesar. El nombre
            # de la clase alcanza para orientar el diagnóstico sin arrastrar contenido.
            logger.error(
                "Excepción inesperada al enviar pulsación (%s): tipo=%s",
                solicitud.dispositivo,
                type(error_inesperado).__name__,
            )
            # El campo tampoco guarda `str(error_inesperado)`. Si lo guardara, el texto de
            # la excepción quedaría dentro de la estructura y volvería a estar a un
            # `print` de distancia del journal. Se conserva el tipo, que es la misma
            # información que se registra, y así el campo sólo contiene texto que el
            # bridge construye o que proviene del sistema operativo.
            return RespuestaEnvioBackend(
                aceptada=None,
                codigo_http=None,
                motivo="ERROR_INESPERADO",
                cuerpo=None,
                error_transporte=(
                    f"Excepción inesperada de tipo {type(error_inesperado).__name__}"
                ),
            )
