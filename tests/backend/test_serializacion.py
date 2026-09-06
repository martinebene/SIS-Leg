"""Pruebas de exclusión para la puerta única de futuras mutaciones."""

import asyncio

import pytest
from sis_leg_backend.servicios.serializacion import EjecutorMutaciones

pytestmark = pytest.mark.anyio


async def test_mutaciones_concurrentes_se_ejecutan_en_orden_exclusivo() -> None:
    """La segunda tarea no entra mientras la primera conserva la sección crítica."""

    ejecutor = EjecutorMutaciones()
    primera_en_ejecucion = asyncio.Event()
    liberar_primera = asyncio.Event()
    pasos: list[str] = []

    async def primera_mutacion() -> None:
        pasos.append("primera_inicio")
        primera_en_ejecucion.set()
        await liberar_primera.wait()
        pasos.append("primera_fin")

    async def segunda_mutacion() -> None:
        pasos.append("segunda_inicio")
        pasos.append("segunda_fin")

    tarea_primera = asyncio.create_task(ejecutor.ejecutar(primera_mutacion))
    await primera_en_ejecucion.wait()
    tarea_segunda = asyncio.create_task(ejecutor.ejecutar(segunda_mutacion))

    # Ceder el control permite que la segunda tarea intente tomar el lock. Si la
    # exclusión funciona, todavía no puede agregar ningún paso a la lista.
    await asyncio.sleep(0)
    assert pasos == ["primera_inicio"]

    liberar_primera.set()
    await asyncio.gather(tarea_primera, tarea_segunda)

    assert pasos == [
        "primera_inicio",
        "primera_fin",
        "segunda_inicio",
        "segunda_fin",
    ]


async def test_error_de_mutacion_se_propaga_y_libera_la_exclusion() -> None:
    """Un fallo no se comunica como éxito ni bloquea las operaciones siguientes."""

    ejecutor = EjecutorMutaciones()

    async def mutacion_fallida() -> None:
        raise ValueError("fallo sintético")

    async def mutacion_posterior() -> str:
        return "completada"

    try:
        await ejecutor.ejecutar(mutacion_fallida)
    except ValueError as error:
        assert str(error) == "fallo sintético"
    else:
        raise AssertionError("La excepción de la mutación debía propagarse")

    assert await ejecutor.ejecutar(mutacion_posterior) == "completada"
