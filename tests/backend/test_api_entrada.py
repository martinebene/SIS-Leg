"""Pruebas HTTP del endpoint ``POST /api/v1/entradas/tecla`` (WP-006/WP-010).

Se usa la aplicación FastAPI real con su lifespan, el router versionado y los
manejadores de errores compartidos. Los cuerpos ficticios solo contienen la
identidad lógica del dispositivo y la tecla; nunca se envía identidad del
concejal desde el cliente.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from conftest import (
    LINEA_LOGS,
    LINEA_QUORUM,
    LINEA_TIMER_TEST_DISPOSITIVO,
    TOML_CANONICO,
    escribir_padron,
    escribir_system_toml,
    filas_padron_valido,
)
from httpx import ASGITransport, AsyncClient
from sis_leg_backend.aplicacion import crear_aplicacion
from sis_leg_backend.auditoria import ErrorAuditoria, NivelAuditoria
from sis_leg_backend.dominio.votacion import ResultadoVotacion
from sis_leg_backend.hechos_operativos import ReferenciaHechoOperativo
from sis_leg_backend.recursos import obtener_recursos_aplicacion
from sis_leg_backend.servicios.entrada import ServicioEntradaTecla

pytestmark = pytest.mark.anyio


def preparar_archivos_canonicos(directorio: Path, *, quorum: int = 7) -> None:
    """Crea los archivos que ``POST /preparacion`` carga por contrato."""

    carpeta_configuracion = directorio / "config"
    carpeta_configuracion.mkdir(parents=True, exist_ok=True)
    escribir_system_toml(
        carpeta_configuracion / "system.toml",
        TOML_CANONICO.replace(
            LINEA_LOGS,
            f'logs_dir = "{directorio / "logs"}"',
        ).replace(LINEA_QUORUM, f"quorum = {quorum}"),
    )
    escribir_padron(carpeta_configuracion / "concejales.csv", filas_padron_valido())


async def preparar_sala(cliente: AsyncClient) -> None:
    """Ejecuta el comando previo común a los escenarios auditables."""

    respuesta = await cliente.post("/api/v1/preparacion")
    assert respuesta.status_code == 204


async def preparar_sesion_y_votacion(cliente: AsyncClient) -> None:
    """Abre una votación con dos presentes usando exclusivamente la API real."""

    await preparar_sala(cliente)
    actualizacion = await cliente.patch(
        "/api/v1/preparacion",
        json={
            "numero_sesion": 59,
            "presidencia": "Presidencia",
            "secretaria_legislativa": "Secretaría",
        },
    )
    assert actualizacion.status_code == 204
    for dispositivo in ("D-01", "D-02"):
        presencia = await cliente.post(
            "/api/v1/entradas/tecla",
            json={"dispositivo": dispositivo, "tecla": "9"},
        )
        assert presencia.status_code == 200
    assert (await cliente.post("/api/v1/sesion")).status_code == 204
    apertura = await cliente.post(
        "/api/v1/votaciones",
        json={
            "numero_votacion": 37,
            "tipo": "Mocion",
            "tema": "Tratamiento API",
            "tipo_mayoria": "SIMPLE",
        },
    )
    assert apertura.status_code == 201


async def test_sin_preparar_devuelve_rechazo_normal_sin_csv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CA-007: un body válido en SIN_PREPARAR no requiere archivos de configuración."""

    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()

    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            respuesta = await cliente.post(
                "/api/v1/entradas/tecla",
                json={"dispositivo": "D-01", "tecla": "9"},
            )

        assert respuesta.status_code == 200
        assert respuesta.json() == {
            "aceptada": False,
            "dispositivo": "D-01",
            "tecla": "9",
            "motivo": "SIN_PREPARAR",
            "concejal": None,
            "resultado": None,
        }
        assert not list(tmp_path.rglob("*.csv"))


async def test_api_devuelve_presencia_y_test_con_forma_canonica(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Las teclas 9 y 8 exponen los dos resultados tipados de DEC-006."""

    preparar_archivos_canonicos(tmp_path)
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()

    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            await preparar_sala(cliente)
            respuesta_presencia = await cliente.post(
                "/api/v1/entradas/tecla",
                json={"dispositivo": "D-01", "tecla": "9"},
            )
            respuesta_test = await cliente.post(
                "/api/v1/entradas/tecla",
                json={"dispositivo": "D-01", "tecla": "8"},
            )

        assert respuesta_presencia.status_code == 200
        assert respuesta_presencia.json() == {
            "aceptada": True,
            "dispositivo": "D-01",
            "tecla": "9",
            "motivo": "PRESENCIA_ACTUALIZADA",
            "concejal": {
                "dni": "30000001",
                "nombre": "Ana",
                "apellido": "Garcia",
                "banca": 1,
            },
            "resultado": {
                "tipo": "PRESENCIA",
                "presente": True,
                "presentes": 1,
                "quorum_alcanzado": False,
            },
        }
        assert respuesta_test.status_code == 200
        assert respuesta_test.json() == {
            "aceptada": True,
            "dispositivo": "D-01",
            "tecla": "8",
            "motivo": "TEST_ACTIVADO",
            "concejal": {
                "dni": "30000001",
                "nombre": "Ana",
                "apellido": "Garcia",
                "banca": 1,
            },
            "resultado": {
                "tipo": "TEST",
                "activo": True,
                "duracion_segundos": 0.6,
            },
        }

        estado = obtener_recursos_aplicacion(aplicacion).estado_operativo
        preparacion = estado.preparacion_activa
        assert preparacion is not None
        assert preparacion.presencias["30000001"] is True


async def test_api_rechaza_dispositivo_y_tecla_con_http_200(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Los rechazos funcionales no se modelan como errores HTTP."""

    preparar_archivos_canonicos(tmp_path)
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()

    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            await preparar_sala(cliente)
            no_asignado = await cliente.post(
                "/api/v1/entradas/tecla",
                json={"dispositivo": "NO-ASIGNADO", "tecla": "9"},
            )
            no_habilitada = await cliente.post(
                "/api/v1/entradas/tecla",
                json={"dispositivo": "D-01", "tecla": "1"},
            )

        assert no_asignado.status_code == 200
        assert no_asignado.json()["motivo"] == "DISPOSITIVO_NO_ASIGNADO"
        assert no_asignado.json()["concejal"] is None
        assert no_asignado.json()["resultado"] is None
        assert no_habilitada.status_code == 200
        assert no_habilitada.json()["motivo"] == "TECLA_NO_HABILITADA"
        assert no_habilitada.json()["concejal"]["banca"] == 1
        assert no_habilitada.json()["resultado"] is None


@pytest.mark.parametrize(
    "cuerpo",
    [
        {},
        {"dispositivo": "D-01"},
        {"dispositivo": "", "tecla": "9"},
        {"dispositivo": "   ", "tecla": "9"},
        {"dispositivo": "D-01", "tecla": ""},
        {"dispositivo": "D-01", "tecla": "9", "dni": "30000001"},
    ],
    ids=["vacio", "campo-faltante", "dispositivo-vacio", "espacios", "tecla-vacia", "campo-extra"],
)
async def test_body_invalido_devuelve_422_sin_procesar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cuerpo: dict[str, str],
) -> None:
    """CA-006 del contrato HTTP: la validación de transporte precede a la mutación."""

    preparar_archivos_canonicos(tmp_path)
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()

    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            await preparar_sala(cliente)
            respuesta = await cliente.post("/api/v1/entradas/tecla", json=cuerpo)

        assert respuesta.status_code == 422
        estado = obtener_recursos_aplicacion(aplicacion).estado_operativo
        preparacion = estado.preparacion_activa
        assert preparacion is not None
        ruta_l1 = preparacion.escritor_auditoria.rutas[
            next(iter(preparacion.escritor_auditoria.rutas))
        ]
        with ruta_l1.open(encoding="utf-8-sig", newline="") as archivo:
            filas = list(csv.reader(archivo, delimiter=";"))
        assert [fila[4] for fila in filas[1:]] == ["PREPARACION_INICIADA"]


async def test_device_test_seconds_queda_congelado_en_la_preparacion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CA-059: cambiar el TOML después de preparar no altera el test activo."""

    preparar_archivos_canonicos(tmp_path)
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()

    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            await preparar_sala(cliente)
            ruta_configuracion = tmp_path / "config" / "system.toml"
            escribir_system_toml(
                ruta_configuracion,
                TOML_CANONICO.replace(LINEA_LOGS, f'logs_dir = "{tmp_path / "logs"}"').replace(
                    LINEA_TIMER_TEST_DISPOSITIVO, "device_test_seconds = 9"
                ),
            )
            respuesta = await cliente.post(
                "/api/v1/entradas/tecla",
                json={"dispositivo": "D-01", "tecla": "8"},
            )

        assert respuesta.status_code == 200
        assert respuesta.json()["resultado"]["duracion_segundos"] == 0.6


async def test_auditoria_no_disponible_devuelve_503_sin_mutar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El writer fallado activa el manejador estable y bloquea la presencia."""

    preparar_archivos_canonicos(tmp_path)
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()

    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            await preparar_sala(cliente)
            estado = obtener_recursos_aplicacion(aplicacion).estado_operativo
            preparacion = estado.preparacion_activa
            assert preparacion is not None
            monkeypatch.setattr(preparacion.escritor_auditoria, "_fallado", True)
            respuesta = await cliente.post(
                "/api/v1/entradas/tecla",
                json={"dispositivo": "D-01", "tecla": "9"},
            )

        assert respuesta.status_code == 503
        assert respuesta.json()["codigo"] == "AUDITORIA_NO_DISPONIBLE"
        assert "traceback" not in respuesta.text.lower()
        assert preparacion.presencias["30000001"] is False


async def test_api_devuelve_variante_voto_abierta_y_cerrada(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La unión HTTP informa valor y estado de recepción después de cada voto."""

    preparar_archivos_canonicos(tmp_path, quorum=2)
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()

    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            await preparar_sesion_y_votacion(cliente)
            positiva = await cliente.post(
                "/api/v1/entradas/tecla",
                json={"dispositivo": "D-01", "tecla": "1"},
            )
            negativa = await cliente.post(
                "/api/v1/entradas/tecla",
                json={"dispositivo": "D-02", "tecla": "3"},
            )

        assert positiva.status_code == negativa.status_code == 200
        assert positiva.json() == {
            "aceptada": True,
            "dispositivo": "D-01",
            "tecla": "1",
            "motivo": "VOTO_REGISTRADO",
            "concejal": {
                "dni": "30000001",
                "nombre": "Ana",
                "apellido": "Garcia",
                "banca": 1,
            },
            "resultado": {
                "tipo": "VOTO",
                "valor": "POSITIVO",
                "estado_recepcion": "EN_CURSO",
            },
        }
        assert negativa.json()["resultado"] == {
            "tipo": "VOTO",
            "valor": "NEGATIVO",
            "estado_recepcion": "CERRADA",
        }
        estado = obtener_recursos_aplicacion(aplicacion).estado_operativo
        assert estado.votacion_activa is not None
        assert estado.votacion_activa.resultado is ResultadoVotacion.EMPATADA


async def test_api_no_informa_exito_si_falla_auditoria_del_resultado(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El último voto responde 503 y conserva CERRADA+None si falla su resultado."""

    preparar_archivos_canonicos(tmp_path, quorum=2)
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()

    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            await preparar_sesion_y_votacion(cliente)
            primera = await cliente.post(
                "/api/v1/entradas/tecla",
                json={"dispositivo": "D-01", "tecla": "1"},
            )
            assert primera.status_code == 200

            estado = obtener_recursos_aplicacion(aplicacion).estado_operativo
            votacion = estado.votacion_activa
            contexto = estado.contexto_operativo_activo()
            assert votacion is not None
            assert contexto is not None
            escritor = contexto.escritor_auditoria
            registrar_original = escritor.registrar_evento

            def registrar_evento(
                nivel: NivelAuditoria,
                etiqueta: str,
                codigo_evento: str,
                mensaje: str,
                *,
                referencia: ReferenciaHechoOperativo | None = None,
            ) -> int:
                if codigo_evento == "VOTACION_RESULTADO_FINAL":
                    monkeypatch.setattr(escritor, "_fallado", True)
                    raise ErrorAuditoria("fallo simulado en resultado")
                return registrar_original(
                    nivel, etiqueta, codigo_evento, mensaje, referencia=referencia
                )

            monkeypatch.setattr(escritor, "registrar_evento", registrar_evento)
            respuesta = await cliente.post(
                "/api/v1/entradas/tecla",
                json={"dispositivo": "D-02", "tecla": "2"},
            )

        assert respuesta.status_code == 503
        assert respuesta.json()["codigo"] == "AUDITORIA_NO_DISPONIBLE"
        assert votacion.estado.value == "CERRADA"
        assert votacion.fecha_hora_cierre is not None
        assert votacion.resultado is None
        assert estado.votacion_activa is votacion
        assert escritor.fallado is True


async def test_fallo_inesperado_devuelve_500_generico(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un error no clasificado no filtra detalles ni simula un 200."""

    async def fallar(_servicio: ServicioEntradaTecla, _pulsacion: object) -> object:
        raise RuntimeError("detalle interno que no debe salir")

    monkeypatch.setattr(ServicioEntradaTecla, "procesar_pulsacion", fallar)
    preparar_archivos_canonicos(tmp_path)
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()

    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion, raise_app_exceptions=False)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            await preparar_sala(cliente)
            respuesta = await cliente.post(
                "/api/v1/entradas/tecla",
                json={"dispositivo": "D-01", "tecla": "9"},
            )

        assert respuesta.status_code == 500
        assert respuesta.json() == {
            "codigo": "ERROR_INTERNO",
            "mensaje": "Ocurrió un error interno.",
        }
        assert "detalle interno" not in respuesta.text


def test_openapi_expone_request_y_respuestas_de_entrada() -> None:
    """El contrato generado declara body, 200, 422, 503 y 500."""

    especificacion = crear_aplicacion().openapi()
    operacion = especificacion["paths"]["/api/v1/entradas/tecla"]["post"]

    assert set(("200", "422", "503", "500")) <= set(operacion["responses"])
    esquema_body = operacion["requestBody"]["content"]["application/json"]["schema"]
    nombre_esquema = esquema_body["$ref"].rsplit("/", 1)[1]
    propiedades = especificacion["components"]["schemas"][nombre_esquema]["properties"]
    assert set(propiedades) == {"dispositivo", "tecla"}
    assert "dni" not in propiedades
    assert "fingerprint" not in propiedades

    esquema_respuesta = operacion["responses"]["200"]["content"]["application/json"]["schema"]
    assert esquema_respuesta["$ref"] == "#/components/schemas/RespuestaTecla"

    esquemas = especificacion["components"]["schemas"]
    esquema_resultado = esquemas["RespuestaTecla"]["properties"]["resultado"]
    referencias = {
        variante["$ref"].rsplit("/", 1)[1]
        for variante in esquema_resultado["anyOf"]
        if "$ref" in variante
    }
    assert referencias == {
        "ResultadoPalabraRespuesta",
        "ResultadoPresenciaRespuesta",
        "ResultadoTestRespuesta",
        "ResultadoVotoRespuesta",
    }
    assert set(esquemas["AccionPalabra"]["enum"]) == {
        "PEDIDO_AGREGADO",
        "PEDIDO_RETIRADO",
        "USO_FINALIZADO",
    }
    assert set(esquemas["ResultadoVotoRespuesta"]["properties"]) == {
        "tipo",
        "valor",
        "estado_recepcion",
    }
    assert set(esquemas["ValorVotoOrdinario"]["enum"]) == {
        "POSITIVO",
        "ABSTENCION",
        "NEGATIVO",
    }
    assert set(esquemas["EstadoVotacion"]["enum"]) == {"EN_CURSO", "CERRADA"}
    assert not any("correg" in ruta or "eliminar" in ruta for ruta in especificacion["paths"])
    assert not any("calcular" in ruta or "resultado" in ruta for ruta in especificacion["paths"])
