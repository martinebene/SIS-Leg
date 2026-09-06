<script setup lang="ts">
/**
 * Panel General de Estado y Diagnóstico del Simulador.
 *
 * Responsabilidades:
 * 1. Mostrar el estado de sincronización SSE en tiempo real (CONECTADO, RECONECTANDO, DESCONECTADO).
 * 2. Visualizar los indicadores globales institucionales (estado_global, revisión, quórum, sesión, votación).
 * 3. Mostrar métricas de transporte (última latencia observada) y errores técnicos.
 * 4. Concentrar toda la información global sin incluir datos por dispositivo en este panel.
 */

import type { EstadoConexion } from '../types/simulador'
import type { EstadoGlobal } from '@sis-leg/api-client'

defineProps<{
  estadoConexion: EstadoConexion
  estadoGlobal: EstadoGlobal | null
  revision: number | null
  quorumResumen: string
  sesionResumen: string
  votacionResumen: string
  ultimaLatenciaMs: number | null
  desactualizado: boolean
  ultimoError: unknown | null
}>()
</script>

<template>
  <section
    data-testid="panel-general"
    class="border-b border-slate-800 bg-slate-900/60 px-4 py-2 text-xs text-slate-300 shrink-0"
  >
    <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2 items-center">
      <!-- 1. Conexión SSE / Backend -->
      <div class="flex items-center gap-2">
        <span class="text-slate-400 font-medium">Conexión:</span>
        <span
          v-if="estadoConexion === 'CONECTADO'"
          data-testid="indicador-conexion-conectado"
          class="inline-flex items-center gap-1 rounded bg-emerald-500/20 px-2 py-0.5 font-semibold text-emerald-400 border border-emerald-500/30"
        >
          <span class="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
          Conectado
        </span>
        <span
          v-else-if="estadoConexion === 'RECONECTANDO'"
          data-testid="indicador-conexion-reconectando"
          class="inline-flex items-center gap-1 rounded bg-amber-500/20 px-2 py-0.5 font-semibold text-amber-400 border border-amber-500/30"
        >
          <span class="h-1.5 w-1.5 rounded-full bg-amber-400 animate-ping" />
          Reconectando
        </span>
        <span
          v-else
          data-testid="indicador-conexion-desconectado"
          class="inline-flex items-center gap-1 rounded bg-rose-500/20 px-2 py-0.5 font-semibold text-rose-400 border border-rose-500/30"
        >
          <span class="h-1.5 w-1.5 rounded-full bg-rose-400" />
          Desconectado
        </span>
      </div>

      <!-- 2. Estado Global -->
      <div class="flex items-center gap-2">
        <span class="text-slate-400 font-medium">Estado global:</span>
        <span
          data-testid="indicador-estado-global"
          class="font-mono font-semibold text-sky-300 bg-slate-950 px-1.5 py-0.5 rounded border border-slate-800"
        >
          {{ estadoGlobal ?? 'SIN_CONEXION' }}
        </span>
        <span
          v-if="revision !== null"
          data-testid="indicador-revision"
          class="text-slate-500 font-mono text-[11px]"
          title="Revisión monotónica del backend"
        >
          r{{ revision }}
        </span>
      </div>

      <!-- 3. Quórum y Presentes -->
      <div class="flex items-center gap-2 truncate">
        <span class="text-slate-400 font-medium">Quórum:</span>
        <span data-testid="indicador-quorum" class="font-medium text-slate-200 truncate">
          {{ quorumResumen }}
        </span>
      </div>

      <!-- 4. Etapa / Sesión -->
      <div class="flex items-center gap-2 truncate">
        <span class="text-slate-400 font-medium">Etapa:</span>
        <span data-testid="indicador-sesion" class="font-medium text-slate-200 truncate">
          {{ sesionResumen }}
        </span>
      </div>

      <!-- 5. Resumen de Votación -->
      <div class="flex items-center gap-2 truncate">
        <span class="text-slate-400 font-medium">Votación:</span>
        <span
          data-testid="indicador-votacion"
          class="font-medium text-amber-200 truncate"
          :title="votacionResumen"
        >
          {{ votacionResumen }}
        </span>
      </div>

      <!-- 6. Latencia HTTP de pulsaciones -->
      <div class="flex items-center gap-2 justify-start lg:justify-end">
        <span class="text-slate-400 font-medium">Latencia HTTP:</span>
        <span
          data-testid="indicador-latencia"
          class="font-mono text-emerald-300 bg-slate-950 px-1.5 py-0.5 rounded border border-slate-800"
        >
          {{ ultimaLatenciaMs !== null ? `${ultimaLatenciaMs} ms` : '—' }}
        </span>
      </div>
    </div>

    <!-- Banner opcional si hay advertencia de desactualización o error técnico -->
    <div
      v-if="desactualizado"
      data-testid="aviso-desactualizado"
      class="mt-1 text-xs text-amber-300 bg-amber-950/40 border border-amber-800/60 rounded px-2 py-0.5 flex items-center gap-1.5"
    >
      <span>⚠️</span>
      <span
        >Conexión interrumpida: el estado visible puede estar temporalmente desactualizado.</span
      >
    </div>
    <div
      v-else-if="ultimoError"
      data-testid="aviso-error-tecnico"
      class="mt-1 text-xs text-rose-300 bg-rose-950/40 border border-rose-800/60 rounded px-2 py-0.5 truncate"
    >
      <span class="font-bold">Error técnico:</span>
      {{ String(ultimoError) }}
    </div>
  </section>
</template>
