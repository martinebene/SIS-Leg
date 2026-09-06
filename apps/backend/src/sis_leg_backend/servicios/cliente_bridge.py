"""Cliente stdlib para la API local de control del device-bridge."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, cast


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
        timeout_segundos: float = 3.0,
    ) -> None:
        self._url_base = url_base.rstrip("/")
        self._timeout = timeout_segundos

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
