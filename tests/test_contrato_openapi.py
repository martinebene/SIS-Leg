"""Pruebas del contrato OpenAPI y detección de drift."""

from pathlib import Path

from scripts.exportar_openapi import (
    RUTA_OPENAPI_PREDETERMINADA,
    exportar_openapi,
    generar_esquema_openapi,
    verificar_drift_openapi,
)


def test_generacion_esquema_openapi_valida() -> None:
    """Verifica que el esquema generado contenga la estructura y metadatos esperados."""
    esquema = generar_esquema_openapi()
    assert esquema["openapi"] == "3.1.0"
    assert esquema["info"]["title"] == "SIS-Leg Backend"
    assert "/api/v1/estado/moderacion" in esquema["paths"]
    assert "/api/v1/estado/recinto" in esquema["paths"]
    assert "/api/v1/votaciones" in esquema["paths"]
    propiedades_recinto = esquema["components"]["schemas"]["EstadoRecinto"]["properties"]
    assert "filas_bancas" in propiedades_recinto


def test_punto_orden_del_dia_publica_la_marca_de_tratado() -> None:
    """WP-053: la ayuda viaja en el contrato como booleano obligatorio.

    Que sea obligatorio importa: el frontend recibe siempre un valor explícito y
    nunca tiene que interpretar la ausencia del campo como "no tratado".
    """
    esquema = generar_esquema_openapi()
    punto = esquema["components"]["schemas"]["PuntoOrdenDelDiaProyectado"]
    assert punto["properties"]["tratado"]["type"] == "boolean"
    assert "tratado" in punto["required"]

    # La ayuda es exclusiva de Moderación: el punto proyectado sólo aparece allí
    # y el DTO de la respuesta de carga no gana ningún campo derivado de sesión.
    respuesta_carga = esquema["components"]["schemas"]["PuntoOrdenDelDiaRespuesta"]
    assert "tratado" not in respuesta_carga["properties"]


def test_snapshot_versionado_coincide_con_backend() -> None:
    """Demuestra que el snapshot versionado en packages/api-client coincide con FastAPI."""
    assert RUTA_OPENAPI_PREDETERMINADA.exists()
    assert verificar_drift_openapi(RUTA_OPENAPI_PREDETERMINADA) is True


def test_serializacion_esquema_determinista(tmp_path: Path) -> None:
    """Verifica que la exportación sea determinista y termine en salto de línea."""
    archivo_temporal = tmp_path / "openapi_test.json"
    exportar_openapi(archivo_temporal)

    contenido_1 = archivo_temporal.read_text(encoding="utf-8")
    assert contenido_1.endswith("\n")

    # Segunda exportación idéntica
    exportar_openapi(archivo_temporal)
    contenido_2 = archivo_temporal.read_text(encoding="utf-8")
    assert contenido_1 == contenido_2


def test_deteccion_drift_backend_openapi(tmp_path: Path) -> None:
    """Demuestra que el detector de drift falla si el snapshot difiere del backend."""
    archivo_drift = tmp_path / "openapi_drift.json"
    # Guardamos un snapshot deliberadamente modificado
    archivo_drift.write_text('{\n  "openapi": "3.1.0",\n  "paths": {}\n}\n', encoding="utf-8")

    assert verificar_drift_openapi(archivo_drift) is False


def test_deteccion_drift_archivo_inexistente(tmp_path: Path) -> None:
    """Verifica que un snapshot inexistente reporte error de drift."""
    archivo_inexistente = tmp_path / "no_existe.json"
    assert verificar_drift_openapi(archivo_inexistente) is False
