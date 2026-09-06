"""Endpoint técnico que permite comprobar que el proceso responde."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

enrutador_salud = APIRouter(tags=["salud"])


class RespuestaSalud(BaseModel):
    """Respuesta pública mínima, sin datos funcionales ni institucionales."""

    estado: Literal["ok"] = "ok"


@enrutador_salud.get("/health", response_model=RespuestaSalud)
async def consultar_salud() -> RespuestaSalud:
    """Confirma disponibilidad técnica sin leer ni modificar estado operativo."""

    return RespuestaSalud()
