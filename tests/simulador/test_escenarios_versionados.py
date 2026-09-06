"""Pruebas de validacion e integracion de los escenarios versionados del simulador (WP-007).

Verifica:
1. Que todos los archivos JSON bajo `tools/device-simulator/escenarios/` sean sintacticamente
   validos y cumplan con el modelo declarativo de `EscenarioDeclarativo`.
2. Que cada escenario versionado se ejecute con exito (resumen.es_exitoso == True) contra
   la aplicacion FastAPI real in-process con su padron y configuracion canonicos en `PREPARANDO`.
"""

from __future__ import annotations

import io
from pathlib import Path

import httpx
import pytest
from cliente import ClienteBackend
from conftest import (
    LINEA_LOGS,
    NOMBRES_FANTASIA,
    TOML_CANONICO,
    escribir_padron,
    escribir_system_toml,
)
from ejecutor_escenarios import EjecutorEscenarios
from parseador import parsear_escenario_json
from sis_leg_backend.aplicacion import crear_aplicacion

pytestmark = pytest.mark.anyio

DIRECTORIO_ESCENARIOS = (
    Path(__file__).resolve().parent.parent.parent / "tools" / "device-simulator" / "escenarios"
)


def filas_padron_dispositivos_dev() -> list[list[str]]:
    """Devuelve 12 filas ficticias con dispositivos dev01..dev12 coincidentes con el simulador."""
    filas: list[list[str]] = []
    for numero, (nombre, apellido) in enumerate(NOMBRES_FANTASIA, start=1):
        bloque = "" if numero in (5, 9) else f"Bloque {((numero - 1) % 3) + 1}"
        filas.append(
            [
                f"3000000{numero}",
                nombre,
                apellido,
                bloque,
                str(numero),
                f"dev{numero:02d}",
                f"assets/bancas/banca-{numero:02d}.png",
            ]
        )
    return filas


def preparar_entorno_backend(directorio: Path) -> None:
    """Genera los archivos canonicos necesarios para preparar el recinto."""
    carpeta_configuracion = directorio / "config"
    carpeta_configuracion.mkdir(parents=True, exist_ok=True)
    escribir_system_toml(
        carpeta_configuracion / "system.toml",
        TOML_CANONICO.replace(LINEA_LOGS, f'logs_dir = "{directorio / "logs"}"'),
    )
    escribir_padron(carpeta_configuracion / "concejales.csv", filas_padron_dispositivos_dev())


def test_todos_los_escenarios_versionados_son_validos() -> None:
    """Verifica que todos los archivos JSON de escenarios se parseen correctamente."""
    archivos_json = list(DIRECTORIO_ESCENARIOS.glob("*.json"))
    assert len(archivos_json) >= 6, (
        f"Se esperaban al menos 6 escenarios versionados, encontrados: {len(archivos_json)}"
    )

    nombres_esperados = {
        "presencia_tecla_9.json",
        "test_tecla_8.json",
        "dispositivo_no_asignado.json",
        "tecla_no_habilitada.json",
        "tecla_sin_semantica.json",
        "grupo_concurrente.json",
    }
    nombres_encontrados = {archivo.name for archivo in archivos_json}
    assert nombres_esperados.issubset(nombres_encontrados)

    for archivo in archivos_json:
        contenido = archivo.read_text(encoding="utf-8")
        escenario = parsear_escenario_json(contenido)
        assert escenario.nombre, f"El escenario en {archivo.name} no tiene nombre."
        assert len(escenario.pasos) > 0, f"El escenario en {archivo.name} no tiene pasos."


@pytest.mark.parametrize(
    "nombre_archivo",
    [
        "presencia_tecla_9.json",
        "test_tecla_8.json",
        "dispositivo_no_asignado.json",
        "tecla_no_habilitada.json",
        "tecla_sin_semantica.json",
        "grupo_concurrente.json",
    ],
)
async def test_ejecucion_escenario_versionado_contra_backend_real(
    nombre_archivo: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ejecuta cada escenario versionado contra la aplicacion FastAPI real en PREPARANDO."""
    preparar_entorno_backend(tmp_path)
    monkeypatch.chdir(tmp_path)

    aplicacion = crear_aplicacion()

    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = httpx.ASGITransport(app=aplicacion)
        async with httpx.AsyncClient(
            transport=transporte,
            base_url="http://testserver",
        ) as cliente_httpx:
            # 1. Preparar el recinto para satisfacer la precondicion de PREPARANDO
            respuesta_prep = await cliente_httpx.post("/api/v1/preparacion")
            assert respuesta_prep.status_code == 204

            # 2. Cargar el escenario desde tools/device-simulator/escenarios/
            ruta_escenario = DIRECTORIO_ESCENARIOS / nombre_archivo
            contenido = ruta_escenario.read_text(encoding="utf-8")
            escenario = parsear_escenario_json(contenido)

            # 3. Ejecutar el escenario mediante el EjecutorEscenarios del simulador
            cliente_simulador = ClienteBackend(
                url_base="http://testserver",
                cliente_httpx=cliente_httpx,
            )
            salida = io.StringIO()
            ejecutor = EjecutorEscenarios(cliente=cliente_simulador, flujo_salida=salida)

            resumen = await ejecutor.ejecutar_escenario(escenario)

            # 4. Verificar que todas las expectativas se hayan cumplido
            assert resumen.es_exitoso is True, (
                f"El escenario {nombre_archivo} fallo.\nSalida:\n{salida.getvalue()}"
            )
            assert resumen.total_discrepancias == 0
            assert resumen.total_fallos_red == 0
