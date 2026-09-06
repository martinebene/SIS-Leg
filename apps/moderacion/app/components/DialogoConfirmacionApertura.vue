<script setup lang="ts">
/**
 * Advertencia accesible de CA-062 antes de abrir una votación con palabra pendiente.
 *
 * El diálogo no modifica el orador ni la cola. Solo devuelve la decisión visual del
 * operador al componente que conserva el body de apertura ya validado. El foco inicial
 * queda en Cancelar para que la alternativa segura sea también la primera al navegar
 * con teclado, y Escape equivale a cancelar.
 */

import { computed, nextTick, ref, watch } from 'vue'
import type { EstadoPalabraModeracion } from '@sis-leg/api-client'

const props = defineProps<{
  palabra: EstadoPalabraModeracion | null
  abierto: boolean
  enviando: boolean
}>()

const emit = defineEmits<{
  confirmar: []
  cancelar: []
}>()

const botonCancelar = ref<HTMLButtonElement | null>(null)
const elementoOrigen = ref<HTMLElement | null>(null)

const nombreOrador = computed(() => {
  const orador = props.palabra?.orador
  return orador ? `${orador.nombre} ${orador.apellido}` : null
})

const cantidadEnCola = computed(() => props.palabra?.cola.length ?? 0)

watch(
  () => props.abierto,
  async (abierto) => {
    if (abierto) {
      elementoOrigen.value =
        typeof document === 'undefined' ? null : (document.activeElement as HTMLElement | null)
      await nextTick()
      botonCancelar.value?.focus()
      return
    }

    await nextTick()
    elementoOrigen.value?.focus()
    elementoOrigen.value = null
  },
)

function cancelar(): void {
  if (!props.enviando) emit('cancelar')
}

function confirmar(): void {
  if (!props.enviando) emit('confirmar')
}

function manejarTeclado(evento: KeyboardEvent): void {
  if (evento.key !== 'Escape') return
  evento.preventDefault()
  cancelar()
}
</script>

<template>
  <div
    v-if="abierto"
    data-testid="dialogo-confirmacion-apertura"
    class="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm"
    role="dialog"
    aria-modal="true"
    aria-labelledby="titulo-dialogo-apertura"
    aria-describedby="descripcion-dialogo-apertura"
    @keydown="manejarTeclado"
  >
    <div class="w-full max-w-md space-y-4 rounded-xl border border-amber-600 bg-slate-900 p-5">
      <div class="border-b border-slate-800 pb-3">
        <h3 id="titulo-dialogo-apertura" class="font-bold text-slate-100">
          Hay uso de la palabra pendiente
        </h3>
        <p class="mt-1 text-xs text-amber-300">
          Confirmá si querés abrir la votación sin alterar esa actividad.
        </p>
      </div>

      <div id="descripcion-dialogo-apertura" class="space-y-2 text-xs text-slate-300">
        <p v-if="nombreOrador" data-testid="apertura-orador-pendiente">
          Orador actual: <strong class="text-slate-100">{{ nombreOrador }}</strong>
        </p>
        <p v-if="cantidadEnCola > 0" data-testid="apertura-cola-pendiente">
          Pedidos en cola: <strong class="text-slate-100">{{ cantidadEnCola }}</strong>
        </p>
        <p class="rounded border border-slate-800 bg-slate-950/60 p-2 text-slate-400">
          La votación y el uso de la palabra continuarán en paralelo. Esta confirmación no quita
          pedidos ni finaliza al orador.
        </p>
      </div>

      <div class="flex flex-wrap justify-end gap-2 border-t border-slate-800 pt-3">
        <button
          ref="botonCancelar"
          type="button"
          data-testid="btn-cancelar-apertura"
          class="rounded-lg border border-slate-700 bg-slate-800 px-4 py-2 text-xs font-semibold text-slate-200 disabled:opacity-40"
          :disabled="enviando"
          @click="cancelar"
        >
          Cancelar
        </button>
        <button
          type="button"
          data-testid="btn-confirmar-apertura"
          class="rounded-lg bg-amber-500 px-4 py-2 text-xs font-bold text-slate-950 disabled:opacity-40"
          :disabled="enviando"
          @click="confirmar"
        >
          {{ enviando ? 'Abriendo votación...' : 'Confirmar apertura' }}
        </button>
      </div>
    </div>
  </div>
</template>
