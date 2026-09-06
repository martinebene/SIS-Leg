"""Coordinación thread-safe del remapeo físico dentro del device-bridge.

Este módulo mantiene separadas las dos relaciones del sistema:

``fingerprint físico -> devXX`` pertenece al bridge y puede cambiar aquí;
``devXX -> concejal`` pertenece al backend y nunca aparece en este módulo.

El mismo candado reentrante protege el mapping base, el mapping efectivo y el
estado idempotente de las operaciones. Las llamadas HTTP se realizan fuera del
candado para que un backend lento no impida procesar otros teclados mapeados.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from sis_leg_device_bridge.configuracion import validar_mapeo_dispositivos
from sis_leg_device_bridge.modelos import EventoTeclaFisica

REGISTRO = logging.getLogger(__name__)


class EstadoRemapeoBridge(StrEnum):
    """Estados consultables de una operación de control del bridge."""

    CAPTURANDO = "CAPTURANDO"
    CANDIDATO = "CANDIDATO"
    APLICADO = "APLICADO"
    CANCELADO = "CANCELADO"
    FALLIDO = "FALLIDO"


class PersistenciaRemapeo(StrEnum):
    """Modos de aplicación elegidos explícitamente por el operador."""

    TEMPORAL = "TEMPORAL"
    PERSISTENTE = "PERSISTENTE"


class ErrorControlRemapeo(Exception):
    """Rechazo estable de un comando de control local."""

    def __init__(self, codigo: str, mensaje: str, estado_http: int = 409) -> None:
        super().__init__(mensaje)
        self.codigo = codigo
        self.estado_http = estado_http


@dataclass(slots=True)
class OperacionRemapeoBridge:
    """Registro idempotente de una coordinación identificada por UUID."""

    remapeo_id: str
    dispositivo: str
    fingerprint_anterior: str
    estado: EstadoRemapeoBridge = EstadoRemapeoBridge.CAPTURANDO
    candidato: str | None = None
    diagnostico: str | None = None
    persistencia: PersistenciaRemapeo | None = None
    error: str | None = None

    def a_diccionario(self) -> dict[str, str | None]:
        """Devuelve el estado completo que usa la API local para reconciliar."""

        return {
            "remapeo_id": self.remapeo_id,
            "dispositivo": self.dispositivo,
            "estado": self.estado.value,
            "fingerprint_anterior": self.fingerprint_anterior,
            "candidato": self.candidato,
            "diagnostico": self.diagnostico,
            "persistencia": self.persistencia.value if self.persistencia is not None else None,
            "error": self.error,
        }


class CoordinadorRemapeoBridge:
    """Administra captura, elegibilidad, aplicación e idempotencia física.

    ``mapeo_base`` es una copia de ``devices.json``. ``mapeo_efectivo`` empieza
    igual, pero puede recibir overrides temporales. Las operaciones terminadas
    se conservan en memoria para que una respuesta HTTP perdida pueda
    consultarse por el mismo identificador sin repetir una escritura.
    """

    def __init__(self, ruta_devices_json: Path, mapeo_base: dict[str, str]) -> None:
        self._ruta_devices_json = ruta_devices_json
        self._mapeo_base = dict(mapeo_base)
        self._mapeo_efectivo = dict(mapeo_base)
        self._operaciones: dict[str, OperacionRemapeoBridge] = {}
        self._remapeo_activo_id: str | None = None
        self._exclusion = threading.RLock()

    def resolver_dispositivo(self, fingerprint: str) -> str | None:
        """Resuelve el mapping efectivo vigente mediante una lectura protegida."""

        with self._exclusion:
            return self._mapeo_efectivo.get(fingerprint)

    def iniciar_captura(self, remapeo_id: str, dispositivo: str) -> dict[str, str | None]:
        """Inicia una captura o devuelve idempotentemente la ya conocida.

        Un mismo ID con otro dispositivo se rechaza. Un ID nuevo tampoco puede
        desplazar una operación todavía activa.
        """

        with self._exclusion:
            conocida = self._operaciones.get(remapeo_id)
            if conocida is not None:
                if conocida.dispositivo != dispositivo:
                    raise ErrorControlRemapeo(
                        "PARAMETROS_INCOMPATIBLES",
                        "El remapeo_id ya fue usado con otro dispositivo lógico.",
                    )
                REGISTRO.info("Inicio idempotente reconciliado para remapeo_id=%s", remapeo_id)
                return conocida.a_diccionario()

            if self._remapeo_activo_id is not None:
                raise ErrorControlRemapeo(
                    "REMAPEO_YA_ACTIVO",
                    "Ya existe una captura de remapeo activa.",
                )

            fingerprint_anterior = self._fingerprint_de_dispositivo(
                self._mapeo_efectivo, dispositivo
            )
            if fingerprint_anterior is None:
                raise ErrorControlRemapeo(
                    "DISPOSITIVO_NO_EXISTENTE",
                    "El dispositivo lógico no existe en el mapping efectivo.",
                )

            operacion = OperacionRemapeoBridge(
                remapeo_id=remapeo_id,
                dispositivo=dispositivo,
                fingerprint_anterior=fingerprint_anterior,
            )
            self._operaciones[remapeo_id] = operacion
            self._remapeo_activo_id = remapeo_id
            REGISTRO.info(
                "Captura iniciada: remapeo_id=%s dispositivo=%s fingerprint_anterior=%s",
                remapeo_id,
                dispositivo,
                fingerprint_anterior,
            )
            return operacion.a_diccionario()

    def considerar_candidato(self, evento: EventoTeclaFisica) -> dict[str, str] | None:
        """Congela el primer keydown elegible sin interceptar fingerprints mapeados.

        El llamador ya resolvió primero el mapping efectivo. Esta segunda
        comprobación bajo el mismo candado cierra la carrera con una aplicación
        concurrente: si el fingerprint pasó a estar mapeado, no será candidato.
        """

        if not evento.es_bajada:
            return None

        with self._exclusion:
            if evento.fingerprint in self._mapeo_efectivo:
                return None
            if self._remapeo_activo_id is None:
                return None
            operacion = self._operaciones[self._remapeo_activo_id]
            if operacion.estado is EstadoRemapeoBridge.CANDIDATO:
                return None
            if operacion.estado is not EstadoRemapeoBridge.CAPTURANDO:
                return None

            dispositivo_base = self._mapeo_base.get(evento.fingerprint)
            if dispositivo_base is not None and dispositivo_base != operacion.dispositivo:
                REGISTRO.warning(
                    "Candidato rechazado por pertenecer en base a %s: fp=%s objetivo=%s",
                    dispositivo_base,
                    evento.fingerprint,
                    operacion.dispositivo,
                )
                return None

            operacion.candidato = evento.fingerprint
            operacion.diagnostico = evento.descripcion_dispositivo or None
            operacion.estado = EstadoRemapeoBridge.CANDIDATO
            REGISTRO.info(
                "Candidato congelado: remapeo_id=%s dispositivo=%s fp=%s",
                operacion.remapeo_id,
                operacion.dispositivo,
                evento.fingerprint,
            )
            return {
                "remapeo_id": operacion.remapeo_id,
                "fingerprint": evento.fingerprint,
                "diagnostico": operacion.diagnostico or "",
            }

    def consultar(self, remapeo_id: str) -> dict[str, str | None]:
        """Consulta estado activo o terminal para reconciliación."""

        with self._exclusion:
            operacion = self._operaciones.get(remapeo_id)
            if operacion is None:
                raise ErrorControlRemapeo(
                    "REMAPEO_NO_EXISTENTE",
                    "El remapeo_id no es conocido por este proceso del bridge.",
                    404,
                )
            return operacion.a_diccionario()

    def confirmar(
        self,
        remapeo_id: str,
        fingerprint: str,
        persistencia: PersistenciaRemapeo,
    ) -> dict[str, str | None]:
        """Aplica exactamente una vez el candidato esperado.

        La persistencia se ejecuta mientras se conserva el candado. Así el loop
        físico nunca observa un mapping intermedio y dos confirmaciones
        concurrentes no pueden duplicar la escritura.
        """

        with self._exclusion:
            operacion = self._obtener_operacion(remapeo_id)
            if operacion.estado is EstadoRemapeoBridge.APLICADO:
                if operacion.candidato != fingerprint or operacion.persistencia is not persistencia:
                    raise ErrorControlRemapeo(
                        "PARAMETROS_INCOMPATIBLES",
                        "La confirmación no coincide con la aplicación ya realizada.",
                    )
                REGISTRO.info("Confirmación idempotente reconciliada: remapeo_id=%s", remapeo_id)
                return operacion.a_diccionario()
            if operacion.estado in (EstadoRemapeoBridge.CANCELADO, EstadoRemapeoBridge.FALLIDO):
                raise ErrorControlRemapeo(
                    "REMAPEO_FINALIZADO",
                    "La operación ya terminó sin una aplicación exitosa.",
                )
            if operacion.estado is not EstadoRemapeoBridge.CANDIDATO or operacion.candidato is None:
                raise ErrorControlRemapeo(
                    "REMAPEO_SIN_CANDIDATO",
                    "La captura todavía no posee un candidato confirmable.",
                )
            if operacion.candidato != fingerprint:
                raise ErrorControlRemapeo(
                    "CANDIDATO_NO_COINCIDE",
                    "El fingerprint esperado no coincide con el candidato congelado.",
                )

            mapeo_nuevo = self._reemplazar_fingerprint(
                self._mapeo_efectivo,
                operacion.dispositivo,
                fingerprint,
            )
            try:
                if persistencia is PersistenciaRemapeo.PERSISTENTE:
                    base_nueva = self._reemplazar_fingerprint(
                        self._mapeo_base,
                        operacion.dispositivo,
                        fingerprint,
                    )
                    validar_mapeo_dispositivos(base_nueva, self._ruta_devices_json)
                    self._persistir_atomico(base_nueva)
                    self._mapeo_base = base_nueva
                    # Un persistente reemplaza el efectivo completo: conserva
                    # overrides temporales de otros devXX y reemplaza solo el objetivo.
                    mapeo_nuevo = self._reemplazar_fingerprint(
                        self._mapeo_efectivo,
                        operacion.dispositivo,
                        fingerprint,
                    )
                self._mapeo_efectivo = mapeo_nuevo
            except Exception as error:
                operacion.estado = EstadoRemapeoBridge.FALLIDO
                operacion.persistencia = persistencia
                operacion.error = str(error)
                self._remapeo_activo_id = None
                REGISTRO.exception(
                    "Falló la aplicación %s de remapeo_id=%s",
                    persistencia,
                    remapeo_id,
                )
                raise ErrorControlRemapeo(
                    "APLICACION_RECHAZADA",
                    "El bridge no pudo aplicar o persistir el remapeo.",
                    503,
                ) from error

            operacion.persistencia = persistencia
            operacion.estado = EstadoRemapeoBridge.APLICADO
            self._remapeo_activo_id = None
            REGISTRO.info(
                "Remapeo aplicado: remapeo_id=%s dispositivo=%s persistencia=%s",
                remapeo_id,
                operacion.dispositivo,
                persistencia.value,
            )
            return operacion.a_diccionario()

    def cancelar(self, remapeo_id: str) -> dict[str, str | None]:
        """Cancela idempotentemente sin cambiar archivo ni mapping efectivo."""

        with self._exclusion:
            operacion = self._obtener_operacion(remapeo_id)
            if operacion.estado is EstadoRemapeoBridge.CANCELADO:
                return operacion.a_diccionario()
            if operacion.estado is EstadoRemapeoBridge.APLICADO:
                raise ErrorControlRemapeo(
                    "REMAPEO_YA_APLICADO",
                    "No se puede cancelar una operación ya aplicada.",
                )
            if operacion.estado is EstadoRemapeoBridge.FALLIDO:
                return operacion.a_diccionario()
            operacion.estado = EstadoRemapeoBridge.CANCELADO
            self._remapeo_activo_id = None
            REGISTRO.info("Remapeo cancelado: remapeo_id=%s", remapeo_id)
            return operacion.a_diccionario()

    def instantanea_mapeo_efectivo(self) -> dict[str, str]:
        """Entrega una copia para pruebas/diagnóstico sin exponer mutabilidad."""

        with self._exclusion:
            return dict(self._mapeo_efectivo)

    def _obtener_operacion(self, remapeo_id: str) -> OperacionRemapeoBridge:
        operacion = self._operaciones.get(remapeo_id)
        if operacion is None:
            raise ErrorControlRemapeo(
                "REMAPEO_NO_EXISTENTE",
                "El remapeo_id no es conocido por este proceso del bridge.",
                404,
            )
        return operacion

    @staticmethod
    def _fingerprint_de_dispositivo(mapeo: dict[str, str], dispositivo: str) -> str | None:
        return next((fp for fp, dev in mapeo.items() if dev == dispositivo), None)

    @classmethod
    def _reemplazar_fingerprint(
        cls,
        mapeo: dict[str, str],
        dispositivo: str,
        fingerprint_nuevo: str,
    ) -> dict[str, str]:
        anterior = cls._fingerprint_de_dispositivo(mapeo, dispositivo)
        if anterior is None:
            raise ValueError(f"No existe {dispositivo} en el mapping")
        resultado = dict(mapeo)
        del resultado[anterior]
        if fingerprint_nuevo in resultado:
            raise ValueError("El fingerprint candidato ya pertenece a otro dispositivo")
        resultado[fingerprint_nuevo] = dispositivo
        return resultado

    def _persistir_atomico(self, mapeo: dict[str, str]) -> None:
        """Escribe completo, sincroniza y reemplaza en el mismo directorio.

        El mapping efectivo se instala recién después de que ``os.replace``
        retorna. Si write/flush/fsync/replace falla, el llamador conserva las
        copias anteriores y este método intenta retirar solo su temporal.
        """

        ruta = self._ruta_devices_json
        ruta_temporal: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                prefix=f".{ruta.name}.",
                suffix=".tmp",
                dir=ruta.parent,
                delete=False,
            ) as archivo:
                ruta_temporal = Path(archivo.name)
                json.dump(mapeo, archivo, ensure_ascii=False, indent=2, sort_keys=True)
                archivo.write("\n")
                archivo.flush()
                os.fsync(archivo.fileno())
            os.replace(ruta_temporal, ruta)
            ruta_temporal = None
        finally:
            if ruta_temporal is not None:
                try:
                    ruta_temporal.unlink(missing_ok=True)
                except OSError:
                    REGISTRO.warning("No se pudo retirar el temporal fallido %s", ruta_temporal)
