"""Ejecutor de escenarios declarativos y grupos concurrentes de pulsaciones (WP-007).

Este modulo contiene la logica para:
1. Ejecutar secuencialmente los pasos de un escenario JSON.
2. Ejecutar pausas temporales asincronas reales con `anyio.sleep`.
3. Disparar grupos concurrentes de pulsaciones en paralelo real mediante `anyio.create_task_group`.
4. Evaluar las expectativas opcionales (`status_http`, `aceptada`, `motivo`) sobre cada respuesta.
5. Imprimir la salida visible obligatoria: envio, status HTTP, cuerpo literal y discrepancias.
6. Consolidar el resumen final de ejecucion y determinar el estado de exito o fallo.

Pedagogia y convenciones:
- Todo identificador propio en espanol sin tildes ni eñes (DEC-001).
- El simulador no fuerza un orden artificial en los grupos concurrentes: el orden oficial
  de ejecucion y persistencia es exclusivamente el que impone el backend mediante su serializador.
"""

from __future__ import annotations

import sys
from typing import TextIO

import anyio
from cliente import ClienteBackend
from modelos import (
    EscenarioDeclarativo,
    PasoConcurrente,
    PasoPausa,
    PasoPulsacion,
    ResultadoEnvio,
    ResultadoPasoIndividual,
    ResumenEjecucionEscenario,
)
from parseador import evaluar_expectativas, formatear_resumen_respuesta


def imprimir_resultado_envio(
    resultado_envio: ResultadoEnvio,
    salida: TextIO = sys.stdout,
    prefijo_paso: str = "",
) -> None:
    """Imprime en la salida estandar la informacion visible obligatoria de un envio.

    Regla de oro de WP-007:
    - Muestra la pulsacion logica enviada (`dispositivo` y `tecla`).
    - Muestra el codigo de estado HTTP recibido (`HTTP <status>`).
    - Muestra el cuerpo literal exacto devuelto por el servidor (`response.text`), sin
      re-serializar, sin pretty-print y sin suprimir campos de error.
    - Si el cuerpo esta vacio, lo indica explicitamente con `(cuerpo vacio)`.
    - Imprime adicionalmente una linea resumen si el JSON corresponde al DTO conocido.

    Args:
        resultado_envio: El resultado del envio HTTP con su respuesta o error.
        salida: Flujo de texto donde escribir (por defecto sys.stdout).
        prefijo_paso: Prefijo opcional para distinguir pasos (ejemplo: '[concurrente]').
    """
    pulsacion = resultado_envio.pulsacion
    prefijo = f"{prefijo_paso} " if prefijo_paso else ""

    # 1. Linea de envio
    salida.write(f"{prefijo}[envio] dispositivo={pulsacion.dispositivo} tecla={pulsacion.tecla}\n")

    # 2. Caso error de red
    if not resultado_envio.exito_comunicacion or resultado_envio.respuesta is None:
        salida.write(
            f"{prefijo}[error de conexion] {resultado_envio.error_red or 'Sin respuesta'}\n"
        )
        salida.flush()
        return

    # 3. Caso respuesta HTTP recibida
    respuesta = resultado_envio.respuesta
    salida.write(f"{prefijo}[respuesta] HTTP {respuesta.status_http}\n")

    # 4. Cuerpo literal intacto
    cuerpo = respuesta.cuerpo_literal
    if cuerpo == "" or cuerpo.isspace():
        salida.write(f"{prefijo}(cuerpo vacio)\n")
    else:
        # Imprimir cuerpo literal tal cual fue recibido
        salida.write(f"{cuerpo}\n")

    # 5. Resumen DTO opcional
    resumen = formatear_resumen_respuesta(cuerpo)
    if resumen:
        salida.write(f"{prefijo}{resumen}\n")

    salida.flush()


class EjecutorEscenarios:
    """Ejecutor de escenarios declarativos de pulsaciones para SIS-Leg.

    Coordina el envio secuencial, las pausas temporales y los grupos concurrentes,
    contrastando cada respuesta con las expectativas declaradas en el escenario.
    """

    def __init__(
        self,
        cliente: ClienteBackend,
        flujo_salida: TextIO = sys.stdout,
    ) -> None:
        """Inicializa el ejecutor de escenarios.

        Args:
            cliente: Instancia de ClienteBackend para enviar peticiones HTTP.
            flujo_salida: Flujo de texto donde se escribira la salida de diagnostico.
        """
        self._cliente = cliente
        self._salida = flujo_salida

    async def ejecutar_paso_pulsacion(
        self,
        paso: PasoPulsacion,
        prefijo: str = "",
    ) -> ResultadoPasoIndividual:
        """Ejecuta una pulsacion individual, imprime su resultado y evalua expectativas.

        Args:
            paso: Paso con la pulsacion y sus expectativas opcionales.
            prefijo: Prefijo para los mensajes de consola.

        Returns:
            Resultado consolidado del paso con discrepancias si hubo.
        """
        resultado_envio = await self._cliente.enviar_pulsacion(paso.pulsacion)
        imprimir_resultado_envio(resultado_envio, salida=self._salida, prefijo_paso=prefijo)

        discrepancias = evaluar_expectativas(resultado_envio.respuesta, paso.esperado)

        if discrepancias:
            for d in discrepancias:
                self._salida.write(
                    f"{prefijo}[FALLO EXPECTATIVA] Campo '{d.campo}': "
                    f"esperado={d.esperado!r}, obtenido={d.obtenido!r} -> {d.detalle}\n"
                )
            self._salida.flush()

        return ResultadoPasoIndividual(
            resultado_envio=resultado_envio,
            discrepancias=discrepancias,
        )

    async def ejecutar_paso_concurrente(
        self,
        paso: PasoConcurrente,
    ) -> list[ResultadoPasoIndividual]:
        """Ejecuta un grupo de pulsaciones de forma concurrente real utilizando un task group.

        Todos los envios se inician en paralelo sin imponer un orden en el cliente.
        Cada respuesta es procesada y evaluada a medida que se completa.

        Args:
            paso: Paso con la lista de pulsaciones concurrentes.

        Returns:
            Lista con los resultados individuales de cada pulsacion del grupo.
        """
        resultados: list[ResultadoPasoIndividual] = []

        async def _tarea_pulsacion(
            sub_paso: PasoPulsacion,
            indice: int,
            acumulador: list[ResultadoPasoIndividual],
        ) -> None:
            prefijo = f"[concurrente #{indice}]"
            res = await self.ejecutar_paso_pulsacion(sub_paso, prefijo=prefijo)
            acumulador.append(res)

        async with anyio.create_task_group() as grupo_tareas:
            for idx, sub_paso in enumerate(paso.pulsaciones, start=1):
                grupo_tareas.start_soon(_tarea_pulsacion, sub_paso, idx, resultados)

        return resultados

    async def ejecutar_escenario(
        self,
        escenario: EscenarioDeclarativo,
    ) -> ResumenEjecucionEscenario:
        """Ejecuta un escenario declarativo completo y devuelve su resumen consolidado.

        Paso a paso:
        1. Imprime el nombre del escenario y la precondicion requerida.
        2. Recorre ordenadamente cada paso:
           - Si es pausa: espera asincronamente con `anyio.sleep`.
           - Si es pulsacion individual: emite, muestra y evalua expectativas.
           - Si es grupo concurrente: dispara en paralelo real todas las pulsaciones.
        3. Imprime el balance final de la ejecucion.

        Args:
            escenario: El escenario validado a ejecutar.

        Returns:
            Instancia de ResumenEjecucionEscenario con estadisticas y resultados.
        """
        resumen = ResumenEjecucionEscenario(nombre_escenario=escenario.nombre)

        self._salida.write("=" * 70 + "\n")
        self._salida.write(f"EJECUTANDO ESCENARIO: {escenario.nombre}\n")
        if escenario.precondicion:
            self._salida.write(f"Precondicion informativa: {escenario.precondicion}\n")
        self._salida.write(f"Total de pasos definidos: {len(escenario.pasos)}\n")
        self._salida.write("=" * 70 + "\n\n")
        self._salida.flush()

        for indice_paso, paso in enumerate(escenario.pasos, start=1):
            self._salida.write(f"--- Paso #{indice_paso} ---\n")

            if isinstance(paso, PasoPausa):
                resumen.total_pausas += 1
                segundos = paso.milisegundos / 1000.0
                self._salida.write(
                    f"[pausa] Esperando {paso.milisegundos}ms ({segundos:.3f}s)...\n"
                )
                self._salida.flush()
                await anyio.sleep(segundos)

            elif isinstance(paso, PasoPulsacion):
                resumen.total_pulsaciones += 1
                res_individual = await self.ejecutar_paso_pulsacion(paso)
                resumen.resultados_pasos.append(res_individual)

                if not res_individual.resultado_envio.exito_comunicacion:
                    resumen.total_fallos_red += 1
                resumen.total_discrepancias += len(res_individual.discrepancias)

            else:
                cantidad = len(paso.pulsaciones)
                resumen.total_pulsaciones += cantidad
                self._salida.write(
                    f"[grupo concurrente] Disparando {cantidad} pulsaciones simultaneas...\n"
                )
                self._salida.flush()

                resultados_concurrentes = await self.ejecutar_paso_concurrente(paso)
                for res_individual in resultados_concurrentes:
                    resumen.resultados_pasos.append(res_individual)
                    if not res_individual.resultado_envio.exito_comunicacion:
                        resumen.total_fallos_red += 1
                    resumen.total_discrepancias += len(res_individual.discrepancias)

            self._salida.write("\n")
            self._salida.flush()

        # Balance final
        self._salida.write("=" * 70 + "\n")
        self._salida.write(f"RESUMEN DEL ESCENARIO: {escenario.nombre}\n")
        self._salida.write(f"Pulsaciones enviadas: {resumen.total_pulsaciones}\n")
        self._salida.write(f"Pausas ejecutadas:    {resumen.total_pausas}\n")
        self._salida.write(f"Fallos de red:        {resumen.total_fallos_red}\n")
        self._salida.write(f"Discrepancias:        {resumen.total_discrepancias}\n")

        if resumen.es_exitoso:
            self._salida.write("ESTADO FINAL: [EXITO] Todas las expectativas fueron satisfechas.\n")
        else:
            self._salida.write(
                "ESTADO FINAL: [FALLO] Errores de comunicacion o expectativas incumplidas.\n"
            )
        self._salida.write("=" * 70 + "\n")
        self._salida.flush()

        return resumen
