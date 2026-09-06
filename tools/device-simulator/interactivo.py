"""Modo interactivo manual persistente para el simulador de dispositivos (WP-007).

Este modulo implementa una consola interactiva que permite a una persona enviar
pulsaciones sucesivas de forma manual, diagnosticar respuestas y consultar informacion
sin reiniciar el proceso.

Pedagogia y convenciones:
- Todo identificador propio en espanol sin tildes ni eñes (DEC-001).
- Un error de sintaxis local o de conexion no detiene la sesion interactiva:
  se informa el problema de forma amigable y se solicita el siguiente comando.
"""

from __future__ import annotations

import sys
from typing import TextIO

from cliente import ClienteBackend
from ejecutor_escenarios import imprimir_resultado_envio
from parseador import ErrorSintaxisEntrada, parsear_sintaxis_manual

MENSAJE_AYUDA = """
Comandos disponibles en la consola interactiva:
  <dispositivo>-<tecla> : Envia pulsacion logica (ejemplos: '5-9', '12-8', '3-+', '5--', '4-enter').
  ayuda / help / ?      : Muestra este mensaje de ayuda y sintaxis.
  url                   : Muestra la URL base activa y el endpoint canonico.
  salir / exit / q      : Cierra la sesion interactiva y finaliza el simulador.

Reglas de sintaxis:
  - El separador es el primer guion '-'.
  - La parte izquierda es el numero entero del dispositivo (se normaliza a 'devNN').
  - La parte derecha es la tecla (ejemplo: '9', '8', '1', '2', '3', '7', '+', 'enter').
  - No se valida si el dispositivo esta en el padron ni si la tecla esta habilitada;
    el simulador envia la peticion para observar la respuesta real del backend.
"""


async def ejecutar_consola_interactiva(
    cliente: ClienteBackend,
    flujo_entrada: TextIO | None = None,
    flujo_salida: TextIO = sys.stdout,
) -> None:
    """Ejecuta el bucle de la consola interactiva persistente.

    Args:
        cliente: ClienteBackend configurado con la URL base activa.
        flujo_entrada: Flujo de donde leer lineas (None para input interactivo normal).
        flujo_salida: Flujo donde escribir los mensajes y respuestas.
    """
    flujo_salida.write("=" * 60 + "\n")
    flujo_salida.write("SIS-Leg - Simulador CLI de Dispositivos (Modo Interactivo)\n")
    flujo_salida.write(f"Conectado a URL base: {cliente.url_base}\n")
    flujo_salida.write(f"Endpoint: {cliente.url_endpoint}\n")
    flujo_salida.write("Escriba 'ayuda' para ver instrucciones o 'salir' para terminar.\n")
    flujo_salida.write("=" * 60 + "\n\n")
    flujo_salida.flush()

    while True:
        try:
            if flujo_entrada is not None:
                linea = flujo_entrada.readline()
                if not linea:  # Fin de archivo (EOF)
                    break
                linea_limpia = linea.strip()
            else:
                linea_limpia = input("> ").strip()

        except (EOFError, KeyboardInterrupt):
            flujo_salida.write("\nCerrando simulador interactivo.\n")
            flujo_salida.flush()
            break

        if not linea_limpia:
            continue

        comando_normalizado = linea_limpia.lower()

        # Comandos internos
        if comando_normalizado in ("salir", "exit", "quit", "q"):
            flujo_salida.write("Sesion finalizada.\n")
            flujo_salida.flush()
            break

        if comando_normalizado in ("ayuda", "help", "?"):
            flujo_salida.write(MENSAJE_AYUDA + "\n")
            flujo_salida.flush()
            continue

        if comando_normalizado == "url":
            flujo_salida.write(f"URL base: {cliente.url_base}\n")
            flujo_salida.write(f"Endpoint: {cliente.url_endpoint}\n\n")
            flujo_salida.flush()
            continue

        # Intentar parsear como pulsacion manual
        try:
            pulsacion = parsear_sintaxis_manual(linea_limpia)
        except ErrorSintaxisEntrada as err:
            flujo_salida.write(f"[error de formato] {err}\n\n")
            flujo_salida.flush()
            continue

        # Enviar pulsacion al backend
        resultado_envio = await cliente.enviar_pulsacion(pulsacion)
        imprimir_resultado_envio(resultado_envio, salida=flujo_salida)
        flujo_salida.write("\n")
        flujo_salida.flush()
