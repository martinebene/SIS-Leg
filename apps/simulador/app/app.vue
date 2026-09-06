<script setup lang="ts">
/**
 * Aplicación principal del Simulador Web de Dispositivos Lógicos (SIS-Leg).
 *
 * Responsabilidades (WP-034 y WP-035):
 * 1. Inicializar la sincronización diagnóstica mediante useSimulador().
 * 2. Renderizar la cabecera operacional con aclaración de entradas directas a FastAPI
 *    y el selector interactivo de cantidad de dispositivos (1..20, default 12).
 * 3. Renderizar el panel general de indicadores globales (sin datos por dispositivo).
 * 4. Presentar los dispositivos lógicos dinámicos (dev01..devNN) visibles en grilla
 *    adaptativa (6 columnas en monitores amplios, 2 filas para los 12 por defecto en Full HD).
 * 5. Permitir scroll controlado en el área de dispositivos para cantidades mayores o resoluciones menores.
 * 6. Presentar el log global de pulsaciones autoscrolleable en la parte inferior.
 */

import { useSimulador } from './composables/useSimulador'
import CabeceraSimulador from './components/CabeceraSimulador.vue'
import PanelGeneralSimulador from './components/PanelGeneralSimulador.vue'
import TarjetaDispositivo from './components/TarjetaDispositivo.vue'
import LogPulsaciones from './components/LogPulsaciones.vue'
import IndicadorCargaInicial from '@sis-leg/frontend-shared/componentes/IndicadorCargaInicial.vue'

const {
  estado,
  estadoConexion,
  estadoGlobal,
  revision,
  quorumResumen,
  sesionResumen,
  votacionResumen,
  ultimaLatenciaMs,
  desactualizado,
  ultimoError,
  peticionesEnVuelo,
  entradasLog,
  cantidadDispositivos,
  dispositivosVisibles,
  incrementarCantidad,
  decrementarCantidad,
  enviarPulsacion,
  limpiarLog,
} = useSimulador()

function manejarPulsacion(evento: { dispositivo: string; tecla: string; nombre: string }): void {
  void enviarPulsacion(evento.dispositivo, evento.tecla, evento.nombre)
}
</script>

<template>
  <div
    class="flex h-screen w-screen min-w-0 flex-col overflow-hidden bg-slate-950 text-slate-100 antialiased select-none"
  >
    <!--
      0. Barra indeterminada de carga inicial (WP-061). Releva al indicador previo a la
      hidratación mientras el simulador espera su primer `EstadoModeracion`. Al estar
      posicionada `fixed` no desplaza la cabecera ni la grilla de dispositivos.
    -->
    <IndicadorCargaInicial v-if="!estado" />

    <!-- 1. Cabecera con identidad de simulador, advertencia de entradas directas y selector de cantidad -->
    <CabeceraSimulador
      :cantidad="cantidadDispositivos"
      @incrementar="incrementarCantidad"
      @decrementar="decrementarCantidad"
    />

    <!-- 2. Panel general compacto con métricas e indicadores globales -->
    <PanelGeneralSimulador
      :estado-conexion="estadoConexion"
      :estado-global="estadoGlobal"
      :revision="revision"
      :quorum-resumen="quorumResumen"
      :sesion-resumen="sesionResumen"
      :votacion-resumen="votacionResumen"
      :ultima-latencia-ms="ultimaLatenciaMs"
      :desactualizado="desactualizado"
      :ultimo-error="ultimoError"
    />

    <!-- 3. Grilla principal de dispositivos lógicos dev01..devNN (WP-035) -->
    <main
      data-testid="area-dispositivos"
      class="flex flex-1 min-h-0 min-w-0 flex-col p-2.5 sm:p-3 overflow-y-auto"
    >
      <div
        data-testid="grilla-dispositivos"
        class="grid min-w-0 grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-2.5"
      >
        <TarjetaDispositivo
          v-for="dispositivo in dispositivosVisibles"
          :key="dispositivo"
          :dispositivo="dispositivo"
          :peticiones-en-vuelo="peticionesEnVuelo"
          @pulsar="manejarPulsacion"
        />
      </div>
    </main>

    <!-- 4. Log global autoscrolleable con respuestas de FastAPI -->
    <LogPulsaciones :entradas="entradasLog" @limpiar="limpiarLog" />
  </div>
</template>
