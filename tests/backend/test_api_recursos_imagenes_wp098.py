"""Integración HTTP de la fuente única de fotografías de banca (WP-098).

Qué se demuestra acá
--------------------

1. el backend publica la foto que está en ``config/assets/bancas/`` con el
   ``Content-Type`` correcto;
2. **sustituir el archivo en disco cambia lo que responde el backend sin
   reconstruir nada**: es el criterio central del WP y por eso se prueba
   pidiendo la misma URL dos veces alrededor de una escritura;
3. las tres familias de ruta peligrosa —traversal, ruta absoluta y URL
   externa— no pueden llegar al disco a través de la URL;
4. una foto ausente responde 404 con el cuerpo de error canónico, no 500: una
   banca sin foto no puede tumbar la superficie ni el backend;
5. el endpoint no lista el directorio.

Las pruebas se ejecutan con el directorio de trabajo movido a un temporal
(``monkeypatch.chdir``). Ésa es la única forma de desviar la configuración sin
inventar un parámetro reubicable: el backend resuelve ``config/`` contra su
directorio de trabajo, exactamente igual que en producción, donde la unidad
systemd lo fija en ``/opt/sis-leg``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sis_leg_backend.aplicacion import crear_aplicacion

pytestmark = pytest.mark.anyio

RUTA_BASE = "/api/v1/recursos/imagenes-concejales"

# Cabecera PNG real seguida de contenido arbitrario: alcanza para distinguir
# dos versiones del archivo byte a byte, que es lo que estas pruebas comparan.
PNG_ORIGINAL = b"\x89PNG\r\n\x1a\n" + b"version-original" * 4
PNG_SUSTITUTO = b"\x89PNG\r\n\x1a\n" + b"version-sustituta" * 4


def preparar_directorio_fotos(directorio_trabajo: Path) -> Path:
    """Crea ``config/assets/bancas`` dentro del directorio de trabajo dado."""

    directorio = directorio_trabajo / "config" / "assets" / "bancas"
    directorio.mkdir(parents=True)
    return directorio


async def test_publica_la_foto_configurada_con_su_tipo_de_contenido(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El caso normal: la foto de la configuración local llega por HTTP."""

    directorio = preparar_directorio_fotos(tmp_path)
    (directorio / "banca-01.png").write_bytes(PNG_ORIGINAL)
    monkeypatch.chdir(tmp_path)

    aplicacion = crear_aplicacion()
    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            respuesta = await cliente.get(f"{RUTA_BASE}/banca-01.png")

    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"] == "image/png"
    assert respuesta.content == PNG_ORIGINAL


async def test_sustituir_el_archivo_se_refleja_sin_reconstruir_el_frontend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Criterio central de WP-098: cambiar la foto no exige rebuild ni reinicio.

    El mismo proceso de backend, sin reiniciarse y sin que se toque ningún
    artefacto de frontend, responde bytes distintos después de que el operador
    reemplaza el archivo en la configuración local. Es exactamente lo que antes
    era imposible, porque la foto viajaba dentro del build de cada SPA.
    """

    directorio = preparar_directorio_fotos(tmp_path)
    ruta_foto = directorio / "banca-01.png"
    ruta_foto.write_bytes(PNG_ORIGINAL)
    monkeypatch.chdir(tmp_path)

    aplicacion = crear_aplicacion()
    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            antes = await cliente.get(f"{RUTA_BASE}/banca-01.png")

            # El operador reemplaza la fotografía en la configuración local.
            ruta_foto.write_bytes(PNG_SUSTITUTO)

            despues = await cliente.get(f"{RUTA_BASE}/banca-01.png")

    assert antes.content == PNG_ORIGINAL
    assert despues.content == PNG_SUSTITUTO
    # `no-cache` es lo que impide que el navegador siga mostrando la anterior.
    assert despues.headers["cache-control"] == "no-cache"


async def test_las_cuatro_superficies_resuelven_exactamente_la_misma_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No existe una URL por aplicación: el recurso es uno y está bajo `/api/v1`.

    Se comprueba pidiendo la foto con los cuatro prefijos públicos de las SPA
    como `Referer`: la respuesta es idéntica porque el recurso no depende de
    quién lo pide. Antes de WP-098 cada SPA servía su propia copia bajo su
    propio prefijo y nada garantizaba que fueran el mismo archivo.
    """

    directorio = preparar_directorio_fotos(tmp_path)
    (directorio / "banca-01.png").write_bytes(PNG_ORIGINAL)
    monkeypatch.chdir(tmp_path)

    aplicacion = crear_aplicacion()
    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            respuestas = [
                await cliente.get(
                    f"{RUTA_BASE}/banca-01.png",
                    headers={"Referer": f"http://pruebas/{prefijo}/"},
                )
                for prefijo in ("moderacion", "recinto", "tecnico", "simulador")
            ]

    assert {respuesta.status_code for respuesta in respuestas} == {200}
    assert {respuesta.content for respuesta in respuestas} == {PNG_ORIGINAL}


@pytest.mark.parametrize(
    "ruta_pedida",
    [
        # Traversal: Starlette ni siquiera hace coincidir la ruta, porque el
        # convertidor por defecto no admite `/`. El resultado observable es el
        # mismo que se quiere garantizar: no se lee nada fuera del directorio.
        f"{RUTA_BASE}/../../../etc/passwd",
        f"{RUTA_BASE}/..%2F..%2Fetc%2Fpasswd",
        f"{RUTA_BASE}/%2e%2e%2fsecreto.png",
        # Ruta absoluta y URL externa camufladas como nombre de archivo.
        f"{RUTA_BASE}//etc/passwd",
        f"{RUTA_BASE}/https:%2F%2Fejemplo.invalid%2Ffoto.png",
        # Archivo oculto y extensión no admitida.
        f"{RUTA_BASE}/.env",
        f"{RUTA_BASE}/banca-01.svg",
    ],
)
async def test_ninguna_ruta_peligrosa_devuelve_contenido(
    ruta_pedida: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Traversal, rutas absolutas y URLs externas nunca producen un 200.

    Se comprueba únicamente que no haya contenido servido: el código concreto
    puede ser 404 (el endpoint rechazó el nombre) o 404 de ruta no encontrada
    (Starlette ni siquiera hizo coincidir la ruta). Fijar cuál de los dos sería
    atar la prueba al ruteo interno en vez de a la garantía de seguridad.
    """

    directorio = preparar_directorio_fotos(tmp_path)
    (directorio / "banca-01.png").write_bytes(PNG_ORIGINAL)
    (tmp_path / "secreto.png").write_bytes(b"contenido que no debe publicarse")
    (tmp_path / "config" / ".env").write_bytes(b"CLAVE=no-debe-publicarse")
    monkeypatch.chdir(tmp_path)

    aplicacion = crear_aplicacion()
    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            respuesta = await cliente.get(ruta_pedida)

    assert respuesta.status_code != 200
    assert b"no debe publicarse" not in respuesta.content


async def test_una_foto_ausente_responde_404_con_el_error_canonico(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fallback explícito: falta la foto, no falla el backend.

    El 404 y el código estable permiten que la tarjeta muestre las iniciales
    sin que nadie interprete la ausencia como una caída del servicio.
    """

    preparar_directorio_fotos(tmp_path)
    monkeypatch.chdir(tmp_path)

    aplicacion = crear_aplicacion()
    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            respuesta = await cliente.get(f"{RUTA_BASE}/banca-07.png")

    assert respuesta.status_code == 404
    assert respuesta.json()["codigo"] == "IMAGEN_CONCEJAL_NO_DISPONIBLE"


async def test_un_directorio_de_configuracion_inexistente_no_rompe_el_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin ninguna foto configurada, el sistema sigue arrancando y respondiendo."""

    monkeypatch.chdir(tmp_path)

    aplicacion = crear_aplicacion()
    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            foto = await cliente.get(f"{RUTA_BASE}/banca-01.png")
            salud = await cliente.get("/api/v1/health")

    assert foto.status_code == 404
    assert salud.status_code == 200


async def test_el_endpoint_no_enumera_el_directorio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pedir la colección sin nombrar un archivo no lista lo que hay dentro."""

    directorio = preparar_directorio_fotos(tmp_path)
    (directorio / "banca-01.png").write_bytes(PNG_ORIGINAL)
    monkeypatch.chdir(tmp_path)

    aplicacion = crear_aplicacion()
    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            respuesta = await cliente.get(f"{RUTA_BASE}/")

    assert respuesta.status_code != 200
    assert b"banca-01.png" not in respuesta.content
