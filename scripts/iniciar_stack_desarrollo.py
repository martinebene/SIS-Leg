"""Servidor efímero que integra FastAPI con las tres SPA estáticas.

Este módulo pertenece exclusivamente al tooling de desarrollo. La aplicación
productiva continúa siendo ``sis_leg_backend.main:app`` y, por lo tanto, no
adquiere mounts de archivos estáticos ni responsabilidades de Nginx.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from sis_leg_backend.aplicacion import crear_aplicacion
from starlette.staticfiles import StaticFiles

HOST_PREDETERMINADO = "127.0.0.1"
PUERTO_PREDETERMINADO = 8000
ESPERA_APAGADO_SEGUNDOS = 3

RAIZ_REPOSITORIO = Path(__file__).resolve().parents[1]
SALIDA_MODERACION = RAIZ_REPOSITORIO / "apps" / "moderacion" / ".output" / "public"
SALIDA_RECINTO = RAIZ_REPOSITORIO / "apps" / "recinto" / ".output" / "public"
SALIDA_SIMULADOR = RAIZ_REPOSITORIO / "apps" / "simulador" / ".output" / "public"
SALIDA_TECNICO = RAIZ_REPOSITORIO / "apps" / "tecnico" / ".output" / "public"
SALIDA_ZOCALO = RAIZ_REPOSITORIO / "apps" / "zocalo" / ".output" / "public"
# El manual de usuario (WP-067) no se construye: es un HTML estático versionado que en
# producción sirve Nginx desde `web/manual/`. Acá se monta desde su directorio fuente para
# que `/manual/` exista también bajo el origen único de desarrollo.
DIRECTORIO_MANUAL = RAIZ_REPOSITORIO / "manual"


class ErrorSalidaSpa(RuntimeError):
    """Indica que un build estático requerido no existe o está incompleto.

    Separar este error de los fallos de FastAPI/Uvicorn permite mostrar una
    explicación accionable: normalmente basta volver a ejecutar ``pnpm build``
    o, de forma canónica, iniciar otra vez ``pnpm dev:stack``.
    """


def validar_salida_spa(ruta: Path, nombre: str) -> None:
    """Comprueba la estructura mínima producida por ``nuxt generate``.

    Args:
        ruta: Directorio ``.output/public`` que se montará en el servidor.
        nombre: Nombre humano de la SPA utilizado en los diagnósticos.

    Raises:
        ErrorSalidaSpa: Si falta el directorio, ``index.html`` o la carpeta
            ``_nuxt`` que contiene los assets compilados.
    """

    if not ruta.is_dir():
        raise ErrorSalidaSpa(
            f"No existe la salida estática de {nombre}: {ruta}. "
            "Ejecutá `pnpm build` antes de iniciar el servidor."
        )

    indice = ruta / "index.html"
    if not indice.is_file():
        raise ErrorSalidaSpa(
            f"La salida estática de {nombre} no contiene un index.html válido: {indice}."
        )

    directorio_assets = ruta / "_nuxt"
    if not directorio_assets.is_dir():
        raise ErrorSalidaSpa(
            f"La salida estática de {nombre} no contiene los assets compilados: "
            f"{directorio_assets}."
        )


def validar_manual(ruta: Path) -> None:
    """Comprueba que el manual de usuario estático exista antes de montarlo.

    Args:
        ruta: Directorio fuente del manual (`manual/` en la raíz del repositorio).

    Raises:
        ErrorSalidaSpa: Si falta el directorio o su `index.html`. Se reutiliza esa
            excepción porque el diagnóstico para la persona que ejecuta el stack es el
            mismo: falta un artefacto estático que el servidor integrado debe publicar.
    """

    if not ruta.is_dir() or not (ruta / "index.html").is_file():
        raise ErrorSalidaSpa(
            f"No se encontró el manual de usuario estático en {ruta}. "
            "Debe existir `manual/index.html` en el repositorio."
        )


def crear_aplicacion_integrada(
    salida_moderacion: Path = SALIDA_MODERACION,
    salida_recinto: Path = SALIDA_RECINTO,
    salida_simulador: Path = SALIDA_SIMULADOR,
    salida_tecnico: Path = SALIDA_TECNICO,
    salida_zocalo: Path = SALIDA_ZOCALO,
    directorio_manual: Path = DIRECTORIO_MANUAL,
    ruta_mensajes_tecnicos: Path | None = None,
) -> FastAPI:
    """Crea una instancia real de FastAPI y monta las cinco SPA para desarrollo.

    Cada invocación parte de ``crear_aplicacion()``, por lo que conserva REST,
    SSE, OpenAPI y el ciclo de vida que inicia en ``SIN_PREPARAR``. Los mounts
    se agregan solo sobre esta instancia efímera: importar la aplicación
    productiva no sirve archivos frontend como efecto colateral.

    Args:
        salida_moderacion: Build estático de la aplicación de Moderación.
        salida_recinto: Build estático de la Pantalla del Recinto.
        salida_simulador: Build estático del Simulador de dispositivos lógicos.
        salida_tecnico: Build estático del puesto de Apoyo Técnico.
        salida_zocalo: Build estático del Zócalo para OBS (WP-099).
        directorio_manual: Directorio fuente del manual de usuario estático.
        ruta_mensajes_tecnicos: CSV de mensajes precargados de Apoyo Técnico
            para este proceso. Omitirlo deja la ruta canónica
            ``config/apoyo-tecnico/mensajes.csv``. El E2E integrado lo apunta a
            un archivo temporal para ejercitar el CRUD real sin escribir sobre
            la biblioteca operativa de quien ejecuta las pruebas (WP-073).

    Returns:
        Aplicación FastAPI lista para ejecutarse en un único proceso ASGI.

    Raises:
        ErrorSalidaSpa: Si alguno de los artefactos está ausente o incompleto.
    """

    validar_salida_spa(salida_moderacion, "Moderación")
    validar_salida_spa(salida_recinto, "Recinto")
    validar_salida_spa(salida_simulador, "Simulador")
    validar_salida_spa(salida_tecnico, "Apoyo Técnico")
    validar_salida_spa(salida_zocalo, "Zócalo")
    validar_manual(directorio_manual)

    aplicacion = crear_aplicacion(ruta_mensajes_tecnicos=ruta_mensajes_tecnicos)

    async def mostrar_indice_desarrollo() -> str:
        """Ofrece accesos mínimos sin agregar una pantalla institucional."""

        return """<!doctype html>
<html lang="es">
  <head><meta charset="utf-8"><title>SIS-Leg · desarrollo</title></head>
  <body>
    <h1>SIS-Leg · entorno de desarrollo</h1>
    <ul>
      <li><a href="/moderacion/">Moderación</a></li>
      <li><a href="/recinto/">Pantalla del Recinto</a></li>
      <li><a href="/tecnico/">Apoyo Técnico</a></li>
      <li><a href="/simulador/">Simulador</a></li>
      <li><a href="/zocalo/">Zócalo para OBS</a></li>
      <li><a href="/manual/">Manual de usuario</a></li>
      <li><a href="/docs">API (Swagger)</a></li>
    </ul>
  </body>
</html>"""

    # Registrar la función de forma explícita también deja visible para el
    # analizador estático que FastAPI conserva y utiliza este callback.
    aplicacion.add_api_route(
        "/",
        mostrar_indice_desarrollo,
        response_class=HTMLResponse,
        include_in_schema=False,
    )

    # Starlette quita el prefijo antes de buscar el archivo. Así, una URL como
    # /moderacion/_nuxt/entrada.js se resuelve dentro de public/_nuxt sin copiar
    # ni mover los outputs generados por Nuxt.
    aplicacion.mount(
        "/moderacion",
        StaticFiles(directory=salida_moderacion, html=True),
        name="moderacion",
    )
    aplicacion.mount(
        "/recinto",
        StaticFiles(directory=salida_recinto, html=True),
        name="recinto",
    )
    aplicacion.mount(
        "/simulador",
        StaticFiles(directory=salida_simulador, html=True),
        name="simulador",
    )
    aplicacion.mount(
        "/tecnico",
        StaticFiles(directory=salida_tecnico, html=True),
        name="tecnico",
    )
    # Zócalo para OBS (WP-099). Se monta igual que las demás superficies públicas para que
    # `/zocalo/` exista también bajo el origen único de desarrollo, que es el mismo
    # contrato de mismo origen que aplica Nginx en producción.
    aplicacion.mount(
        "/zocalo",
        StaticFiles(directory=salida_zocalo, html=True),
        name="zocalo",
    )
    # `html=True` hace que /manual/ resuelva a index.html, igual que el `try_files` de la
    # plantilla Nginx productiva. Así la misma URL funciona en desarrollo y en producción.
    aplicacion.mount(
        "/manual",
        StaticFiles(directory=directorio_manual, html=True),
        name="manual",
    )
    return aplicacion


def convertir_puerto(valor: str) -> int:
    """Convierte un argumento CLI en un puerto TCP válido."""

    try:
        puerto = int(valor)
    except ValueError as error:
        raise argparse.ArgumentTypeError("el puerto debe ser un número entero") from error

    if not 1 <= puerto <= 65535:
        raise argparse.ArgumentTypeError("el puerto debe estar entre 1 y 65535")
    return puerto


def crear_analizador_argumentos() -> argparse.ArgumentParser:
    """Define opciones explícitas conservando loopback como valor seguro."""

    analizador = argparse.ArgumentParser(
        description="Sirve FastAPI, Moderación y Recinto bajo un único origen de desarrollo."
    )
    analizador.add_argument(
        "--host",
        default=HOST_PREDETERMINADO,
        help=f"interfaz de escucha (predeterminado: {HOST_PREDETERMINADO})",
    )
    analizador.add_argument(
        "--port",
        type=convertir_puerto,
        default=PUERTO_PREDETERMINADO,
        help=f"puerto HTTP (predeterminado: {PUERTO_PREDETERMINADO})",
    )
    analizador.add_argument(
        "--ruta-mensajes-tecnicos",
        type=Path,
        default=None,
        help=(
            "CSV de mensajes precargados de Apoyo Técnico para este proceso. "
            "Sólo para el harness de pruebas: omitirlo deja la ruta canónica "
            "config/apoyo-tecnico/mensajes.csv."
        ),
    )
    return analizador


def ejecutar_servidor(aplicacion: FastAPI, host: str, puerto: int) -> None:
    """Ejecuta Uvicorn en foreground y con el único worker permitido.

    Uvicorn instala los manejadores de señales y completa el lifespan de
    FastAPI al recibir ``Ctrl+C``. El límite breve de apagado evita que las
    conexiones SSE abiertas por los navegadores retengan indefinidamente el
    único proceso visible. No se crean procesos hijos, daemons ni un servidor
    Node persistente que requieran una limpieza adicional.
    """

    uvicorn.run(
        aplicacion,
        host=host,
        port=puerto,
        workers=1,
        timeout_graceful_shutdown=ESPERA_APAGADO_SEGUNDOS,
    )


def main(argumentos: Sequence[str] | None = None) -> int:
    """Valida los builds y mantiene el servidor integrado en primer plano."""

    opciones = crear_analizador_argumentos().parse_args(argumentos)
    try:
        aplicacion = crear_aplicacion_integrada(
            ruta_mensajes_tecnicos=opciones.ruta_mensajes_tecnicos
        )
    except ErrorSalidaSpa as error:
        print(f"Error al iniciar el stack: {error}", file=sys.stderr)
        return 1

    ejecutar_servidor(aplicacion, opciones.host, opciones.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
