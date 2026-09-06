"""Pruebas de integración HTTP del recurso ``/api/v1/preparacion`` (WP-005).

Cada test trabaja sobre una aplicación real creada por ``crear_aplicacion``
y un directorio temporal como directorio de trabajo (``monkeypatch.chdir``),
de modo que el backend carga sus archivos canónicos ``config/system.toml`` y
``config/concejales.csv`` exactamente como en producción, pero sin tocar el
disco real del repositorio.

Se cubren las pruebas obligatorias de API del WP: éxitos ``204`` sin body,
rechazos ``409``, errores ``503`` por configuración/padrón/auditoría, el
``500`` genérico sin filtrado de detalles y la coherencia del OpenAPI.
"""

from __future__ import annotations

import asyncio
import csv
import json
from pathlib import Path

import pytest
from conftest import (
    LINEA_LOGS,
    TOML_CANONICO,
    escribir_padron,
    escribir_system_toml,
    filas_padron_valido,
)
from httpx import ASGITransport, AsyncClient
from sis_leg_backend.aplicacion import crear_aplicacion
from sis_leg_backend.dominio.estado import EstadoGlobal
from sis_leg_backend.recursos import obtener_recursos_aplicacion

pytestmark = pytest.mark.anyio


def leer_filas(ruta: Path) -> list[list[str]]:
    """Lee un CSV de auditoría con el delimitador y la codificación canónicos."""

    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.reader(archivo, delimiter=";"))


def csv_auditoria(directorio: Path) -> list[Path]:
    """Lista los CSV de auditoría bajo ``logs``, excluyendo el padrón de prueba."""

    return sorted((directorio / "logs").rglob("*.csv"))


def preparar_archivos_canonicos(
    directorio: Path,
    *,
    contenido_toml: str | None = None,
    filas_padron: list[list[str]] | None = None,
) -> None:
    """Escribe ``config/system.toml`` y ``config/concejales.csv`` válidos.

    ``directorio`` es el futuro directorio de trabajo del proceso de prueba;
    los registros se redirigen a ``<directorio>/logs`` para no tocar el repo.
    """

    carpeta_config = directorio / "config"
    carpeta_config.mkdir(parents=True, exist_ok=True)
    escribir_system_toml(
        carpeta_config / "system.toml",
        contenido_toml or TOML_CANONICO.replace(LINEA_LOGS, f'logs_dir = "{directorio}/logs"'),
    )
    escribir_padron(carpeta_config / "concejales.csv", filas_padron or filas_padron_valido())


async def test_post_preparacion_exitoso_devuelve_204_sin_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CA-002: preparar pasa a PREPARANDO, crea tres CSV y responde 204 vacío."""

    preparar_archivos_canonicos(tmp_path)
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()

    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            # El comando se invoca deliberadamente sin body.
            respuesta = await cliente.post("/api/v1/preparacion")

        assert respuesta.status_code == 204
        assert respuesta.content == b""

        recursos = obtener_recursos_aplicacion(aplicacion)
        estado = recursos.estado_operativo
        assert estado.estado_global is EstadoGlobal.PREPARANDO
        assert estado.preparacion_activa is not None
        assert not any(estado.preparacion_activa.presencias.values())

        # Se crearon exactamente tres CSV nuevos con el evento institucional.
        archivos = csv_auditoria(tmp_path)
        assert len(archivos) == 3
        for ruta in archivos:
            filas = leer_filas(ruta)
            assert len(filas) == 2
            assert filas[1][2:] == [
                "L3",
                "PREPARACION",
                "PREPARACION_INICIADA",
                "Preparación del recinto iniciada",
            ]


async def test_delete_preparacion_exitoso_devuelve_204_sin_body_y_conserva_csv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CA-008: cancelar registra, cierra los CSV y vuelve a SIN_PREPARAR."""

    preparar_archivos_canonicos(tmp_path)
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()

    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            await cliente.post("/api/v1/preparacion")
            respuesta = await cliente.delete("/api/v1/preparacion")

        assert respuesta.status_code == 204
        assert respuesta.content == b""

        recursos = obtener_recursos_aplicacion(aplicacion)
        assert recursos.estado_operativo.estado_global is EstadoGlobal.SIN_PREPARAR
        assert recursos.estado_operativo.preparacion_activa is None
        assert recursos.estado_operativo.archivos_auditoria_activos == ()

        # Los CSV generados se conservan con ambos eventos institucionales.
        archivos = csv_auditoria(tmp_path)
        assert len(archivos) == 3
        for ruta in archivos:
            codigos = [fila[4] for fila in leer_filas(ruta)[1:]]
            assert codigos == ["PREPARACION_INICIADA", "PREPARACION_CANCELADA"]


async def test_preparar_en_preparando_devuelve_409_estable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Una segunda preparación se rechaza con 409 ESTADO_INCOMPATIBLE."""

    preparar_archivos_canonicos(tmp_path)
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()

    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            await cliente.post("/api/v1/preparacion")
            respuesta = await cliente.post("/api/v1/preparacion")

        assert respuesta.status_code == 409
        cuerpo = respuesta.json()
        assert cuerpo["codigo"] == "ESTADO_INCOMPATIBLE"
        assert isinstance(cuerpo["mensaje"], str) and cuerpo["mensaje"]

        # El rechazo no creó un nuevo conjunto de auditoría ni alteró el estado.
        assert obtener_recursos_aplicacion(aplicacion).estado_operativo.estado_global is (
            EstadoGlobal.PREPARANDO
        )
        assert len(csv_auditoria(tmp_path)) == 3


async def test_cancelar_sin_preparacion_devuelve_409_estable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancelar desde SIN_PREPARAR se rechaza con 409 ESTADO_INCOMPATIBLE."""

    preparar_archivos_canonicos(tmp_path)
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()

    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            respuesta = await cliente.delete("/api/v1/preparacion")

        assert respuesta.status_code == 409
        assert respuesta.json()["codigo"] == "ESTADO_INCOMPATIBLE"
        assert obtener_recursos_aplicacion(aplicacion).estado_operativo.estado_global is (
            EstadoGlobal.SIN_PREPARAR
        )
        assert not csv_auditoria(tmp_path)


async def test_configuracion_invalida_devuelve_503_estable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CA-003: un TOML inválido bloquea la preparación con CONFIGURACION_INVALIDA."""

    preparar_archivos_canonicos(tmp_path, contenido_toml="no es toml = [")
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()

    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            respuesta = await cliente.post("/api/v1/preparacion")

        assert respuesta.status_code == 503
        cuerpo = respuesta.json()
        assert cuerpo["codigo"] == "CONFIGURACION_INVALIDA"
        assert isinstance(cuerpo["mensaje"], str) and cuerpo["mensaje"]
        assert obtener_recursos_aplicacion(aplicacion).estado_operativo.estado_global is (
            EstadoGlobal.SIN_PREPARAR
        )


async def test_padron_invalido_devuelve_503_estable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CA-003: un padrón inválido bloquea la preparación con PADRON_INVALIDO."""

    filas = filas_padron_valido()
    filas[2][0] = ""  # DNI vacío: bloquea la carga del padrón.
    preparar_archivos_canonicos(tmp_path, filas_padron=filas)
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()

    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            respuesta = await cliente.post("/api/v1/preparacion")

        assert respuesta.status_code == 503
        cuerpo = respuesta.json()
        assert cuerpo["codigo"] == "PADRON_INVALIDO"
        assert isinstance(cuerpo["mensaje"], str) and cuerpo["mensaje"]
        assert obtener_recursos_aplicacion(aplicacion).estado_operativo.estado_global is (
            EstadoGlobal.SIN_PREPARAR
        )


async def test_auditoria_no_disponible_devuelve_503_estable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si no puede garantizarse la auditoría obligatoria, no hay 204.

    El directorio de registros configurado está ocupado por un archivo, de
    modo que la creación del conjunto CSV falla de forma realista.
    """

    ruta_logs = tmp_path / "logs"
    ruta_logs.write_text("no es un directorio", encoding="utf-8")
    preparar_archivos_canonicos(tmp_path)
    # El helper escribe el TOML apuntando a tmp_path/logs (ya ocupado).
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()

    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            respuesta = await cliente.post("/api/v1/preparacion")

        assert respuesta.status_code == 503
        cuerpo = respuesta.json()
        assert cuerpo["codigo"] == "AUDITORIA_NO_DISPONIBLE"
        assert isinstance(cuerpo["mensaje"], str) and cuerpo["mensaje"]
        assert obtener_recursos_aplicacion(aplicacion).estado_operativo.estado_global is (
            EstadoGlobal.SIN_PREPARAR
        )


async def test_error_inesperado_devuelve_500_sin_filtrar_detalles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un fallo no clasificado llega al manejador genérico ERROR_INTERNO."""

    import sis_leg_backend.servicios.preparacion as modulo_preparacion

    def cargar_con_fallo_inesperado(_ruta: Path) -> None:
        raise RuntimeError("detalle interno que no debe exponerse")

    monkeypatch.setattr(
        modulo_preparacion, "cargar_configuracion_sistema", cargar_con_fallo_inesperado
    )
    preparar_archivos_canonicos(tmp_path)
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()

    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion, raise_app_exceptions=False)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            respuesta = await cliente.post("/api/v1/preparacion")

        assert respuesta.status_code == 500
        assert respuesta.json() == {
            "codigo": "ERROR_INTERNO",
            "mensaje": "Ocurrió un error interno.",
        }
        assert "detalle interno" not in respuesta.text


async def test_openapi_expone_el_contrato_de_preparacion() -> None:
    """El OpenAPI refleja métodos, ausencia de body y respuestas documentadas."""

    aplicacion = crear_aplicacion()
    especificacion = aplicacion.openapi()
    ruta = especificacion["paths"]["/api/v1/preparacion"]

    for metodo in ("post", "delete"):
        assert metodo in ruta
        operacion = ruta[metodo]
        # Ninguno de los dos comandos admite body de entrada.
        assert "requestBody" not in operacion
        respuestas = operacion["responses"]
        for codigo in ("204", "409", "503", "500"):
            assert codigo in respuestas

    # El cuerpo de error referencia el esquema estable del contrato.
    esquema_error = ruta["post"]["responses"]["409"]["content"]["application/json"]["schema"]
    assert esquema_error == {"$ref": "#/components/schemas/ErrorRespuesta"}


async def test_reinicio_durante_preparando_vuelve_a_sin_preparar_sin_tocar_csv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CA-057: un lifespan nuevo arranca limpio y no repara archivos previos."""

    preparar_archivos_canonicos(tmp_path)
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()

    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            await cliente.post("/api/v1/preparacion")
        assert obtener_recursos_aplicacion(aplicacion).estado_operativo.estado_global is (
            EstadoGlobal.PREPARANDO
        )

    # Contenido de los CSV de la preparación interrumpida por el "reinicio".
    archivos_previos = csv_auditoria(tmp_path)
    contenidos_previos = {ruta: ruta.read_bytes() for ruta in archivos_previos}

    async with aplicacion.router.lifespan_context(aplicacion):
        estado_nuevo = obtener_recursos_aplicacion(aplicacion).estado_operativo
        assert estado_nuevo.estado_global is EstadoGlobal.SIN_PREPARAR
        assert estado_nuevo.preparacion_activa is None
        assert estado_nuevo.archivos_auditoria_activos == ()

    # Los CSV previos quedaron intactos hasta el último evento persistido.
    assert {ruta: ruta.read_bytes() for ruta in archivos_previos} == contenidos_previos


async def test_comandos_concurrentes_se_serializan_sin_estados_simultaneos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CA-058: dos POST concurrentes producen exactamente un 204 y un 409."""

    preparar_archivos_canonicos(tmp_path)
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()

    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            respuestas = await asyncio.gather(
                cliente.post("/api/v1/preparacion"),
                cliente.post("/api/v1/preparacion"),
            )

        codigos = sorted(respuesta.status_code for respuesta in respuestas)
        assert codigos == [204, 409]
        assert (
            json.loads(next(r for r in respuestas if r.status_code == 409).content)["codigo"]
            == "ESTADO_INCOMPATIBLE"
        )
        # Un único conjunto de auditoría y un único estado final coherente.
        assert len(csv_auditoria(tmp_path)) == 3
        assert obtener_recursos_aplicacion(aplicacion).estado_operativo.estado_global is (
            EstadoGlobal.PREPARANDO
        )
