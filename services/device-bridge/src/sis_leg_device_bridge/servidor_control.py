"""Servidor HTTP local y versionado para controlar remapeos del bridge."""

from __future__ import annotations

import json
import logging
import re
import threading
from collections.abc import Mapping
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast

from sis_leg_device_bridge.remapeo import (
    CoordinadorRemapeoBridge,
    ErrorControlRemapeo,
    PersistenciaRemapeo,
)

REGISTRO = logging.getLogger(__name__)
PATRON_RECURSO = re.compile(r"^/control/v1/remapeos/([^/]+)$")
PATRON_CONFIRMACION = re.compile(r"^/control/v1/remapeos/([^/]+)/confirmacion$")


class ServidorControlBridge:
    """Encapsula ``ThreadingHTTPServer`` con loopback como bind predeterminado."""

    def __init__(
        self,
        coordinador: CoordinadorRemapeoBridge,
        host: str = "127.0.0.1",
        puerto: int = 8765,
    ) -> None:
        manejador = self._crear_manejador(coordinador)
        self._servidor = ThreadingHTTPServer((host, puerto), manejador)
        self._servidor.daemon_threads = True
        self._hilo: threading.Thread | None = None

    @property
    def direccion(self) -> tuple[str, int]:
        """Devuelve host/puerto reales; puerto puede haber sido ``0`` en tests."""

        host, puerto = self._servidor.server_address[:2]
        return str(host), int(puerto)

    def iniciar(self) -> None:
        """Inicia la atención concurrente en un hilo daemon único."""

        if self._hilo is not None:
            return
        self._hilo = threading.Thread(
            target=self._servidor.serve_forever,
            name="control-remapeo-bridge",
            daemon=True,
        )
        self._hilo.start()
        REGISTRO.info("API local de control escuchando en http://%s:%d", *self.direccion)

    def detener(self) -> None:
        """Detiene, cierra el socket y espera brevemente el hilo servidor."""

        if self._hilo is None:
            self._servidor.server_close()
            return
        self._servidor.shutdown()
        self._servidor.server_close()
        self._hilo.join(timeout=2)
        self._hilo = None

    @staticmethod
    def _crear_manejador(
        coordinador: CoordinadorRemapeoBridge,
    ) -> type[BaseHTTPRequestHandler]:
        class ManejadorControl(BaseHTTPRequestHandler):
            """Traduce HTTP/JSON a comandos thread-safe del coordinador."""

            server_version = "SIS-LegDeviceBridge/1"

            def do_POST(self) -> None:  # noqa: N802 - nombre impuesto por stdlib
                try:
                    if self.path == "/control/v1/remapeos":
                        cuerpo = self._leer_json_cerrado({"remapeo_id", "dispositivo"})
                        remapeo_id = self._texto_estricto(cuerpo, "remapeo_id")
                        dispositivo = self._texto_estricto(cuerpo, "dispositivo")
                        self._responder_json(
                            HTTPStatus.OK,
                            coordinador.iniciar_captura(remapeo_id, dispositivo),
                        )
                        return
                    coincidencia = PATRON_CONFIRMACION.fullmatch(self.path)
                    if coincidencia is not None:
                        cuerpo = self._leer_json_cerrado({"fingerprint", "persistencia"})
                        fingerprint = self._texto_estricto(cuerpo, "fingerprint")
                        valor_persistencia = self._texto_estricto(cuerpo, "persistencia")
                        try:
                            persistencia = PersistenciaRemapeo(valor_persistencia)
                        except ValueError as error:
                            raise ErrorControlRemapeo(
                                "PERSISTENCIA_INVALIDA",
                                "persistencia debe ser TEMPORAL o PERSISTENTE.",
                                422,
                            ) from error
                        self._responder_json(
                            HTTPStatus.OK,
                            coordinador.confirmar(coincidencia.group(1), fingerprint, persistencia),
                        )
                        return
                    self._responder_error(404, "RUTA_NO_EXISTENTE", "Ruta de control inexistente.")
                except ErrorControlRemapeo as error:
                    self._responder_error(error.estado_http, error.codigo, str(error))
                except Exception:
                    REGISTRO.exception("Fallo inesperado atendiendo POST %s", self.path)
                    self._responder_error(500, "ERROR_INTERNO", "Fallo interno del bridge.")

            def do_GET(self) -> None:  # noqa: N802 - nombre impuesto por stdlib
                try:
                    coincidencia = PATRON_RECURSO.fullmatch(self.path)
                    if coincidencia is None:
                        self._responder_error(
                            404, "RUTA_NO_EXISTENTE", "Ruta de control inexistente."
                        )
                        return
                    self._responder_json(
                        HTTPStatus.OK,
                        coordinador.consultar(coincidencia.group(1)),
                    )
                except ErrorControlRemapeo as error:
                    self._responder_error(error.estado_http, error.codigo, str(error))

            def do_DELETE(self) -> None:  # noqa: N802 - nombre impuesto por stdlib
                try:
                    coincidencia = PATRON_RECURSO.fullmatch(self.path)
                    if coincidencia is None:
                        self._responder_error(
                            404, "RUTA_NO_EXISTENTE", "Ruta de control inexistente."
                        )
                        return
                    self._responder_json(HTTPStatus.OK, coordinador.cancelar(coincidencia.group(1)))
                except ErrorControlRemapeo as error:
                    self._responder_error(error.estado_http, error.codigo, str(error))

            def log_message(self, format: str, *args: object) -> None:
                """Redirige el hook impuesto por stdlib al registro técnico."""

                REGISTRO.debug("Control HTTP: " + format, *args)

            def _leer_json_cerrado(self, campos: set[str]) -> dict[str, Any]:
                tipo = self.headers.get("Content-Type", "").split(";", 1)[0].strip()
                if tipo != "application/json":
                    raise ErrorControlRemapeo(
                        "BODY_INVALIDO", "Content-Type debe ser application/json.", 422
                    )
                try:
                    longitud = int(self.headers.get("Content-Length", "0"))
                    valor = json.loads(self.rfile.read(longitud).decode("utf-8"))
                except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise ErrorControlRemapeo("BODY_INVALIDO", "JSON inválido.", 422) from error
                if not isinstance(valor, dict):
                    raise ErrorControlRemapeo(
                        "BODY_INVALIDO",
                        f"El body debe contener exactamente {sorted(campos)}.",
                        422,
                    )
                cuerpo = cast(dict[str, Any], valor)
                if set(cuerpo) != campos:
                    raise ErrorControlRemapeo(
                        "BODY_INVALIDO",
                        f"El body debe contener exactamente {sorted(campos)}.",
                        422,
                    )
                return cuerpo

            @staticmethod
            def _texto_estricto(cuerpo: dict[str, Any], campo: str) -> str:
                valor = cuerpo.get(campo)
                if not isinstance(valor, str) or not valor.strip():
                    raise ErrorControlRemapeo(
                        "BODY_INVALIDO", f"{campo} debe ser texto no vacío.", 422
                    )
                return valor

            def _responder_error(self, estado: int, codigo: str, mensaje: str) -> None:
                self._responder_json(estado, {"codigo": codigo, "mensaje": mensaje})

            def _responder_json(self, estado: int, cuerpo: Mapping[str, object]) -> None:
                datos = json.dumps(cuerpo, ensure_ascii=False).encode("utf-8")
                self.send_response(estado)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(datos)))
                self.end_headers()
                self.wfile.write(datos)

        return ManejadorControl
