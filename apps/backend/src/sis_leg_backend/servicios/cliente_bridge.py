"""Cliente stdlib para la API local de control del device-bridge."""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, cast

# Duración por defecto del canal de control cuando nadie configura otra cosa.
# Vive acá, junto a la validación, para que la clase y quien lea la variable de
# entorno usen literalmente el mismo número y no puedan divergir (WP-089).
TIMEOUT_CONTROL_POR_DEFECTO = 3.0


class ErrorConfiguracionBridge(ValueError):
    """La duración configurada para el canal de control no es utilizable.

    Se distingue de los errores de transporte porque no describe una falla al
    hablar con el bridge: describe una configuración que jamás debería llegar a
    ``urllib``. ``urlopen`` interpreta ``timeout=0`` como "sin espera",
    ``timeout=nan`` produce comparaciones siempre falsas y un negativo tiene
    semántica de socket indefinida. Por eso WP-089 exige rechazar esos valores
    en el momento de construir el cliente, no cuando alguien pide un remapeo.

    Hereda de ``ValueError`` porque sigue siendo un valor inválido recibido por
    un constructor; el tipo propio permite distinguirlo cuando importa.
    """


def exigir_timeout_control_valido(valor: float, *, origen: str) -> float:
    """Devuelve la duración si es finita y estrictamente positiva; si no, falla.

    Es la **única** frontera que define qué es una duración aceptable para el
    canal de control. La usan tanto el constructor de ``ClienteControlBridge``
    como la lectura de ``SIS_LEG_BRIDGE_CONTROL_TIMEOUT`` en ``recursos.py``:
    así una llamada directa desde código y un despliegue mal configurado quedan
    sujetos exactamente a la misma invariante, sin repetir la comprobación en
    dos lugares que puedan desincronizarse.

    Parámetros:
        valor: duración candidata, en segundos.
        origen: nombre que el mensaje de error debe mencionar para que quien
            lee el fallo sepa qué corregir. Puede ser el nombre de la variable
            de entorno (``SIS_LEG_BRIDGE_CONTROL_TIMEOUT``) o el del parámetro
            del constructor, según quién llame.

    Resultado:
        El mismo valor convertido a ``float``, para que un ``int`` como ``30``
        llegue a ``urllib`` con el tipo esperado.

    Errores:
        ``ErrorConfiguracionBridge`` ante ``nan``, ``inf``, ``-inf``, cero o
        cualquier número negativo. El mensaje siempre nombra ``origen``.

    Los booleanos no se comprueban explícitamente: el tipado estricto ya impide
    pasarlos, y ``float(True)`` sería ``1.0``, una duración válida y no una
    semántica indefinida como las que este WP debe cerrar.
    """

    numero = float(valor)
    if not math.isfinite(numero) or numero <= 0.0:
        raise error_timeout_control_invalido(valor, origen=origen)
    return numero


def error_timeout_control_invalido(valor: object, *, origen: str) -> ErrorConfiguracionBridge:
    """Construye el error único que describe una duración de control inválida.

    Existe para que haya **un solo texto** posible. Quien lee la variable de
    entorno debe rechazar además valores que ni siquiera son números (``abc``,
    cadena vacía), un caso que esta función no puede detectar porque recibe ya
    un ``float``; si cada frontera redactara su propio mensaje, un operador
    vería explicaciones distintas para el mismo problema.

    Parámetros:
        valor: lo que se recibió, tal cual, para citarlo en el mensaje. Se
            acepta ``object`` porque puede ser el texto crudo del entorno.
        origen: nombre de la variable o parámetro que hay que corregir.
    """

    return ErrorConfiguracionBridge(
        f"{origen} debe ser una duración en segundos finita y mayor que cero; se recibió {valor!r}"
    )


class ErrorTransporteBridge(Exception):
    """La respuesta puede haberse perdido y requiere consulta de estado."""


class ErrorRespuestaBridge(Exception):
    """Respuesta HTTP explícita no exitosa del bridge."""

    def __init__(self, codigo: str, mensaje: str) -> None:
        super().__init__(mensaje)
        self.codigo = codigo


@dataclass(frozen=True, slots=True)
class EstadoControlBridge:
    """Respuesta validada suficiente para coordinación/reconciliación."""

    remapeo_id: str
    dispositivo: str
    estado: str
    fingerprint_anterior: str | None
    candidato: str | None
    diagnostico: str | None
    persistencia: str | None
    error: str | None


class ClienteControlBridge:
    """Emite comandos de control; las pulsaciones normales no usan esta clase."""

    def __init__(
        self,
        url_base: str = "http://127.0.0.1:8765",
        timeout_segundos: float = TIMEOUT_CONTROL_POR_DEFECTO,
    ) -> None:
        """Fija destino y duración máxima de espera de cada comando de control.

        El timeout se valida acá y no en cada solicitud porque el cliente vive
        todo el proceso: si la duración fuese inválida, conviene enterarse al
        construirlo —durante el arranque— y no en medio de un remapeo urgente.
        """

        self._url_base = url_base.rstrip("/")
        self._timeout = exigir_timeout_control_valido(
            timeout_segundos,
            origen="timeout_segundos",
        )

    def iniciar(self, remapeo_id: str, dispositivo: str) -> EstadoControlBridge:
        """Ordena captura idempotente para un devXX."""

        return self._solicitar(
            "POST",
            "/control/v1/remapeos",
            {"remapeo_id": remapeo_id, "dispositivo": dispositivo},
        )

    def consultar(self, remapeo_id: str) -> EstadoControlBridge:
        """Obtiene estado terminal o activo después de una respuesta incierta."""

        return self._solicitar("GET", f"/control/v1/remapeos/{remapeo_id}", None)

    def confirmar(
        self,
        remapeo_id: str,
        fingerprint: str,
        persistencia: str,
    ) -> EstadoControlBridge:
        """Ordena aplicar una vez el candidato esperado."""

        return self._solicitar(
            "POST",
            f"/control/v1/remapeos/{remapeo_id}/confirmacion",
            {"fingerprint": fingerprint, "persistencia": persistencia},
        )

    def cancelar(self, remapeo_id: str) -> EstadoControlBridge:
        """Cancela captura/candidato sin alterar mapping."""

        return self._solicitar("DELETE", f"/control/v1/remapeos/{remapeo_id}", None)

    def _solicitar(
        self,
        metodo: str,
        ruta: str,
        cuerpo: dict[str, str] | None,
    ) -> EstadoControlBridge:
        datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
        cabeceras = {"Accept": "application/json"}
        if datos is not None:
            cabeceras["Content-Type"] = "application/json"
        peticion = urllib.request.Request(
            f"{self._url_base}{ruta}",
            data=datos,
            headers=cabeceras,
            method=metodo,
        )
        try:
            with urllib.request.urlopen(peticion, timeout=self._timeout) as respuesta:
                return self._convertir_estado(json.loads(respuesta.read().decode("utf-8")))
        except urllib.error.HTTPError as error_http:
            try:
                valor_error = json.loads(error_http.read().decode("utf-8"))
            except Exception:
                valor_error = {}
            cuerpo_error = (
                cast(dict[str, Any], valor_error) if isinstance(valor_error, dict) else {}
            )
            codigo = cuerpo_error.get("codigo", f"HTTP_{error_http.code}")
            mensaje = cuerpo_error.get("mensaje", "El bridge rechazó el comando.")
            raise ErrorRespuestaBridge(str(codigo), str(mensaje)) from error_http
        except (TimeoutError, urllib.error.URLError, OSError) as error:
            raise ErrorTransporteBridge(str(error)) from error
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError) as error:
            raise ErrorTransporteBridge("Respuesta inválida del bridge") from error

    @staticmethod
    def _convertir_estado(valor: Any) -> EstadoControlBridge:
        if not isinstance(valor, dict):
            raise ValueError("La respuesta del bridge no es un objeto")
        cuerpo = cast(dict[str, Any], valor)
        obligatorios = ("remapeo_id", "dispositivo", "estado")
        if any(not isinstance(cuerpo.get(campo), str) for campo in obligatorios):
            raise ValueError("La respuesta del bridge no contiene identidad/estado válidos")

        def opcional(campo: str) -> str | None:
            dato = cuerpo.get(campo)
            if dato is not None and not isinstance(dato, str):
                raise ValueError(f"{campo} no es texto opcional")
            return dato

        return EstadoControlBridge(
            remapeo_id=cuerpo["remapeo_id"],
            dispositivo=cuerpo["dispositivo"],
            estado=cuerpo["estado"],
            fingerprint_anterior=opcional("fingerprint_anterior"),
            candidato=opcional("candidato"),
            diagnostico=opcional("diagnostico"),
            persistencia=opcional("persistencia"),
            error=opcional("error"),
        )
