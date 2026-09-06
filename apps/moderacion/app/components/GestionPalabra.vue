<script setup lang="ts">
/**
 * Presenta y opera el uso de la palabra sin crear una cola paralela en Vue.
 *
 * El orador y la cola se leen siempre del snapshot recibido. El único dato local
 * es el comando en vuelo; después de un 204 se espera la siguiente proyección
 * REST/SSE antes de mostrar cualquier cambio institucional.
 *
 * WP-044 elimina dos textos que ocupaban altura sin agregar decisión operativa:
 * la repetición del orador (su señal vive en la banca resaltada del recinto) y el
 * acuse `Comando enviado. Esperando...`. Ese acuse describía un tránsito HTTP que el
 * operador no puede accionar y que, además, nunca debe confundirse con el estado
 * institucional. Los errores reales sí se conservan: son los únicos mensajes que
 * habilitan una decisión (reintentar, corregir o escalar).
 */

import { computed, ref } from 'vue'
import type { ClienteModeracion, EstadoModeracion } from '@sis-leg/api-client'
import { traducirMotivos } from '../utils/motivos'

const props = defineProps<{
  /** Snapshot completo y autoritativo de Moderación. */
  estado: EstadoModeracion | null
  /** Cliente compartido; concentra los contratos REST aprobados. */
  cliente: ClienteModeracion
  /** Solo una conexión SSE confirmada habilita mutaciones desde la UI. */
  conectado: boolean
}>()

type AccionPalabra = 'OTORGAR' | 'QUITAR'

const accionEnVuelo = ref<AccionPalabra | null>(null)
const mensajeError = ref<string | null>(null)

const palabra = computed(() => props.estado?.palabra ?? null)
// El orador ya no se replica como texto acá: WP-044 deja esa señal en la banca del recinto.
const cola = computed(() => palabra.value?.cola ?? [])

const capacidadOtorgar = computed(() => props.estado?.capacidades.otorgar_palabra)
const capacidadQuitar = computed(() => props.estado?.capacidades.quitar_palabra)

const puedeOtorgar = computed(
  () =>
    props.conectado &&
    (capacidadOtorgar.value?.habilitada ?? false) &&
    accionEnVuelo.value === null,
)
const puedeQuitar = computed(
  () =>
    props.conectado && (capacidadQuitar.value?.habilitada ?? false) && accionEnVuelo.value === null,
)

const motivosOtorgar = computed(() => traducirMotivos(capacidadOtorgar.value?.motivos))
const motivosQuitar = computed(() => traducirMotivos(capacidadQuitar.value?.motivos))
const motivosPalabra = computed(() => [
  ...new Set([...motivosOtorgar.value, ...motivosQuitar.value]),
])

/** Extrae el mensaje preservado por la jerarquía de errores de api-client. */
function extraerMensajeError(error: unknown, mensajePredeterminado: string): string {
  if (typeof error === 'object' && error !== null) {
    if (
      'mensajeBackend' in error &&
      typeof (error as { mensajeBackend: unknown }).mensajeBackend === 'string'
    ) {
      return (error as { mensajeBackend: string }).mensajeBackend
    }
    if ('mensaje' in error && typeof (error as { mensaje: unknown }).mensaje === 'string') {
      return (error as { mensaje: string }).mensaje
    }
    if ('message' in error && typeof (error as { message: unknown }).message === 'string') {
      return (error as { message: string }).message
    }
  }
  return mensajePredeterminado
}

function limpiarMensajes(): void {
  mensajeError.value = null
}

/**
 * Solicita el avance deliberado de la cola. No retira ni promueve personas
 * localmente: la semántica exacta de CA-061 queda bajo autoridad del backend.
 */
async function otorgarPalabra(): Promise<void> {
  if (!puedeOtorgar.value) return
  limpiarMensajes()
  accionEnVuelo.value = 'OTORGAR'
  try {
    // Sin acuse de éxito: la transición se hace visible cuando el snapshot la confirma.
    await props.cliente.otorgarPalabra()
  } catch (error: unknown) {
    mensajeError.value = extraerMensajeError(error, 'No se pudo otorgar la palabra.')
  } finally {
    accionEnVuelo.value = null
  }
}

/**
 * Solicita finalizar al orador actual. La cola visible permanece idéntica
 * hasta que un snapshot posterior confirme la transición sin avance implícito.
 */
async function quitarPalabra(): Promise<void> {
  if (!puedeQuitar.value) return
  limpiarMensajes()
  accionEnVuelo.value = 'QUITAR'
  try {
    // Sin acuse de éxito: la cola visible solo cambia por proyección autoritativa.
    await props.cliente.quitarPalabra()
  } catch (error: unknown) {
    mensajeError.value = extraerMensajeError(error, 'No se pudo quitar la palabra.')
  } finally {
    accionEnVuelo.value = null
  }
}
</script>

<template>
  <section
    data-testid="gestion-palabra"
    class="flex h-full min-h-0 flex-col gap-2 overflow-hidden rounded-lg border border-slate-800 bg-slate-950/60 p-2.5"
  >
    <div class="flex shrink-0 items-center justify-between gap-2 border-b border-slate-800 pb-1.5">
      <h3 class="text-xs font-bold uppercase tracking-wider text-slate-300">Uso de la palabra</h3>
      <span
        data-testid="badge-cola-palabra"
        class="rounded border px-2 py-0.5 text-[10px] font-bold"
        :class="
          cola.length > 0
            ? 'border-cyan-700 bg-cyan-950 text-cyan-300'
            : 'border-slate-800 bg-slate-900 text-slate-400'
        "
      >
        {{ cola.length }} en cola
      </span>
    </div>

    <!-- Esta lista es la única frontera de scroll de la columna de palabra. -->
    <div
      data-testid="contenedor-scroll-cola-palabra"
      class="min-h-0 flex-1 overflow-y-auto rounded border border-slate-800/80 bg-slate-900/50 p-1.5 text-xs"
    >
      <ol v-if="cola.length > 0" data-testid="cola-palabra" class="space-y-1 pr-1">
        <li
          v-for="(persona, indice) in cola"
          :key="persona.dni"
          :data-testid="`pedido-palabra-${indice + 1}`"
          class="rounded bg-slate-950/70 px-2 py-1 text-slate-200"
        >
          <span class="font-mono text-cyan-400">{{ indice + 1 }}.</span>
          Banca {{ persona.banca }} · {{ persona.nombre }} {{ persona.apellido }}
        </li>
      </ol>
      <p v-else class="m-0 italic text-slate-400">Sin pedidos en espera</p>
    </div>

    <div data-testid="controles-palabra" class="grid shrink-0 grid-cols-2 gap-2">
      <button
        type="button"
        data-testid="btn-otorgar-palabra"
        class="rounded-lg border border-cyan-700 bg-cyan-950 px-2 py-1.5 text-[11px] font-bold text-cyan-200 disabled:cursor-not-allowed disabled:opacity-40"
        :disabled="!puedeOtorgar"
        @click="otorgarPalabra"
      >
        {{ accionEnVuelo === 'OTORGAR' ? 'Otorgando...' : 'Otorgar palabra' }}
      </button>
      <button
        type="button"
        data-testid="btn-quitar-palabra"
        class="rounded-lg border border-amber-700 bg-amber-950 px-2 py-1.5 text-[11px] font-bold text-amber-200 disabled:cursor-not-allowed disabled:opacity-40"
        :disabled="!puedeQuitar"
        @click="quitarPalabra"
      >
        {{ accionEnVuelo === 'QUITAR' ? 'Quitando...' : 'Quitar palabra' }}
      </button>
    </div>

    <div
      v-if="!conectado"
      data-testid="motivo-palabra-sin-conexion"
      class="shrink-0 rounded border border-amber-800 bg-amber-950/40 px-2 py-1 text-[10px] text-amber-200"
    >
      Los comandos de palabra requieren conexión confirmada.
    </div>
    <ul
      v-else-if="!capacidadOtorgar?.habilitada || !capacidadQuitar?.habilitada"
      data-testid="motivos-palabra"
      class="max-h-12 shrink-0 space-y-0.5 overflow-y-auto text-[9px] text-slate-400"
    >
      <li v-for="motivo in motivosPalabra" :key="motivo">
        {{ motivo }}
      </li>
    </ul>

    <p
      v-if="mensajeError"
      data-testid="error-palabra"
      class="max-h-12 shrink-0 overflow-y-auto rounded border border-rose-700 bg-rose-950/60 px-2 py-1 text-[10px] text-rose-200"
      role="alert"
    >
      {{ mensajeError }}
    </p>
  </section>
</template>
