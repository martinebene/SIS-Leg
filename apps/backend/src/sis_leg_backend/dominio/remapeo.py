"""Modelos volátiles de coordinación de remapeo del backend."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EstadoRemapeo(StrEnum):
    """Etapas observables por Moderación mientras la operación está activa."""

    CAPTURANDO = "CAPTURANDO"
    CANDIDATO = "CANDIDATO"
    CONFIRMANDO = "CONFIRMANDO"
    APLICADO = "APLICADO"
    CANCELADO = "CANCELADO"
    FALLIDO = "FALLIDO"


class PersistenciaRemapeo(StrEnum):
    """Decisión humana cerrada para aplicar el mapping."""

    TEMPORAL = "TEMPORAL"
    PERSISTENTE = "PERSISTENTE"


@dataclass(slots=True)
class OperacionRemapeo:
    """Identidad y progreso de una coordinación backend↔bridge.

    Los fingerprints son datos diagnósticos físicos; nunca reemplazan el
    ``dispositivo`` lógico ni se usan para buscar al concejal en el backend.
    """

    remapeo_id: str
    dispositivo: str
    estado: EstadoRemapeo = EstadoRemapeo.CAPTURANDO
    fingerprint_anterior: str | None = None
    candidato: str | None = None
    diagnostico: str | None = None
    persistencia: PersistenciaRemapeo | None = None
    autorizacion_auditada: bool = False
    error: str | None = None


class ErrorDispositivoRemapeoNoExistente(Exception):
    """El devXX no pertenece al padrón congelado vigente."""


class ErrorRemapeoYaActivo(Exception):
    """Existe otra operación global todavía activa."""


class ErrorRemapeoNoCoincide(Exception):
    """El identificador no corresponde a la operación activa o conocida."""


class ErrorRemapeoSinCandidato(Exception):
    """Se intentó confirmar antes de recibir un candidato físico."""


class ErrorCandidatoRemapeoNoCoincide(Exception):
    """Un callback posterior intentó sustituir el primer candidato."""


class ErrorParametrosRemapeoIncompatibles(Exception):
    """Un comando idempotente repitió el ID con otros parámetros."""


class ErrorBridgeNoDisponible(Exception):
    """No fue posible contactar o reconciliar el bridge local."""


class ErrorAplicacionBridgeRechazada(Exception):
    """El bridge rechazó técnica o persistentemente el cambio solicitado."""
