<script setup lang="ts">
/**
 * Diálogo modal de advertencia confirmatoria para el cierre de sesión con palabra pendiente.
 *
 * Responsabilidades:
 * 1. Presentar una advertencia clara al operador cuando intenta cerrar la sesión existiendo
 *    un concejal en uso de la palabra (orador) o pedidos registrados en la cola de espera.
 * 2. Si el operador cancela: no ejecuta ninguna acción técnica ni modifica el estado (cero mutaciones).
 * 3. Si el operador confirma: emite el evento de confirmación para que el panel envíe
 *    el comando normal de cierre de sesión al backend.
 * 4. Gestión completa y accesible del foco y modalidad nativa (H4):
 *    - Captura el elemento previamente enfocado al abrirse.
 *    - Mueve el foco inicial al control seguro ("Cancelar y conservar sesión").
 *    - Trampa de foco (focus trap) para Tab y Shift+Tab dentro del modal sin dependencias externas.
 *    - Atajo de teclado Escape para cancelar de forma segura.
 *    - Restaura el foco al elemento de origen al cerrarse.
 *    - Atributos semánticos accesibles (role="dialog", aria-modal="true", aria-labelledby, aria-describedby).
 *
 * Invariantes respetados:
 * - NO ejecuta comandos de otorgar/quitar palabra antes de cerrar.
 * - NO altera localmente la cola ni el orador.
 * - Es una salvaguarda ergonómica de UI y no una precondición obligatoria del backend.
 */

import { ref, computed, watch, nextTick } from 'vue'
import type { EstadoPalabraModeracion } from '@sis-leg/api-client'

const props = defineProps<{
  /** Estado del uso de la palabra proyectado por el backend */
  palabra: EstadoPalabraModeracion | null
  /** Indica si el diálogo se encuentra actualmente visible */
  abierto: boolean
  /** Indica si una operación de comando se encuentra en vuelo */
  enviando?: boolean
}>()

const emit = defineEmits<{
  confirmar: []
  cancelar: []
}>()

// Referencias a elementos del DOM para control de foco y focus trap
const contenedorDialogoRef = ref<HTMLDivElement | null>(null)
const botonCancelarRef = ref<HTMLButtonElement | null>(null)
const elementoPrevio = ref<HTMLElement | null>(null)

// Identidad del orador actual si existe
const oradorActual = computed(() => {
  if (!props.palabra?.orador) return null
  return `${props.palabra.orador.nombre} ${props.palabra.orador.apellido}`
})

// Cantidad de pedidos pendientes en la cola de palabra
const cantidadEnCola = computed(() => props.palabra?.cola?.length ?? 0)

function manejarConfirmar(): void {
  if (props.enviando) return
  emit('confirmar')
}

function manejarCancelar(): void {
  if (props.enviando) return
  emit('cancelar')
}

/**
 * Gestiona el ciclo de vida del foco al abrirse y cerrarse el modal (H4).
 */
watch(
  () => props.abierto,
  async (nuevoAbierto) => {
    if (nuevoAbierto) {
      // Guardamos el elemento activo en el momento de la apertura
      if (typeof document !== 'undefined') {
        elementoPrevio.value = document.activeElement as HTMLElement | null
      }
      await nextTick()
      // Movemos el foco al botón seguro de cancelación
      botonCancelarRef.value?.focus()
    } else {
      // Al cerrarse el modal, restauramos el foco al elemento que originó la apertura
      await nextTick()
      if (elementoPrevio.value && typeof elementoPrevio.value.focus === 'function') {
        elementoPrevio.value.focus()
      }
      elementoPrevio.value = null
    }
  },
  { immediate: true },
)

/**
 * Maneja eventos de teclado en el diálogo (Escape y trampa de foco Tab / Shift+Tab) (H4).
 */
function manejarKeyDown(evento: KeyboardEvent): void {
  if (!props.abierto) return

  // Atajo Escape: cancela el cierre si no hay una operación en vuelo
  if (evento.key === 'Escape') {
    evento.preventDefault()
    evento.stopPropagation()
    manejarCancelar()
    return
  }

  // Focus trap para navegación con teclado
  if (evento.key === 'Tab') {
    if (!contenedorDialogoRef.value) return

    const selectoresEnfocables = 'button:not([disabled]), [tabindex]:not([tabindex="-1"])'
    const elementos = Array.from(
      contenedorDialogoRef.value.querySelectorAll<HTMLElement>(selectoresEnfocables),
    )

    if (elementos.length === 0) {
      evento.preventDefault()
      return
    }

    const primerElemento = elementos[0]
    const ultimoElemento = elementos[elementos.length - 1]

    if (!primerElemento || !ultimoElemento) {
      evento.preventDefault()
      return
    }

    if (evento.shiftKey) {
      // Shift + Tab: si estamos en el primer elemento, ciclar al último
      if (document.activeElement === primerElemento) {
        evento.preventDefault()
        ultimoElemento.focus()
      }
    } else {
      // Tab: si estamos en el último elemento, ciclar al primero
      if (document.activeElement === ultimoElemento) {
        evento.preventDefault()
        primerElemento.focus()
      }
    }
  }
}
</script>

<template>
  <div
    v-if="abierto"
    ref="contenedorDialogoRef"
    data-testid="dialogo-confirmacion-cierre"
    class="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm select-none"
    role="dialog"
    aria-modal="true"
    aria-labelledby="titulo-dialogo-cierre"
    aria-describedby="descripcion-dialogo-cierre"
    tabindex="-1"
    @keydown="manejarKeyDown"
  >
    <div
      class="w-full max-w-md rounded-xl border border-amber-600/80 bg-slate-900 p-5 shadow-2xl text-slate-100 flex flex-col gap-4 animate-in fade-in zoom-in-95 duration-150"
    >
      <!-- Cabecera del diálogo -->
      <div class="flex items-center gap-3 border-b border-slate-800 pb-3">
        <div
          class="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-amber-950 text-amber-400 border border-amber-600"
        >
          <span class="text-xl font-bold">⚠</span>
        </div>
        <div>
          <h3 id="titulo-dialogo-cierre" class="text-base font-bold text-slate-100">
            Advertencia: Uso de la palabra activo
          </h3>
          <p class="text-xs text-amber-300">
            Existen concejales con intervención o pedido pendiente
          </p>
        </div>
      </div>

      <!-- Cuerpo explicativo -->
      <div id="descripcion-dialogo-cierre" class="space-y-3 text-xs text-slate-300">
        <p>
          Está a punto de cerrar la sesión formal mientras aún hay actividad registrada en el uso de
          la palabra:
        </p>

        <!-- Detalle de orador activo si existe -->
        <div
          v-if="oradorActual"
          data-testid="detalle-orador-pendiente"
          class="rounded-lg border border-amber-800/60 bg-amber-950/40 p-2.5"
        >
          <span class="font-bold text-amber-200 uppercase tracking-wider text-[10px]"
            >Orador en uso de palabra:</span
          >
          <p class="text-sm font-semibold text-slate-100 mt-0.5">{{ oradorActual }}</p>
        </div>

        <!-- Detalle de pedidos en cola si existen -->
        <div
          v-if="cantidadEnCola > 0"
          data-testid="detalle-cola-pendiente"
          class="rounded-lg border border-slate-800 bg-slate-950/60 p-2.5"
        >
          <span class="font-bold text-slate-400 uppercase tracking-wider text-[10px]"
            >Pedidos en espera:</span
          >
          <p class="text-sm font-semibold text-slate-200 mt-0.5">
            {{ cantidadEnCola }}
            {{ cantidadEnCola === 1 ? 'solicitud pendiente' : 'solicitudes pendientes' }} en la cola
          </p>
        </div>

        <p class="text-slate-400 italic">
          Al confirmar el cierre, la sesión se dará por concluida formalmente en el backend sin
          requerir acciones previas sobre la palabra.
        </p>
      </div>

      <!-- Botones de acción -->
      <div class="flex items-center justify-end gap-3 border-t border-slate-800 pt-3">
        <button
          ref="botonCancelarRef"
          type="button"
          data-testid="btn-cancelar-cierre"
          class="rounded-lg border border-slate-700 bg-slate-800 px-4 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-700 active:bg-slate-900 transition-colors disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-slate-400"
          :disabled="enviando"
          @click="manejarCancelar"
        >
          Cancelar y conservar sesión
        </button>

        <button
          type="button"
          data-testid="btn-confirmar-cierre"
          class="rounded-lg border border-amber-600 bg-amber-600 hover:bg-amber-500 active:bg-amber-700 px-4 py-2 text-xs font-bold text-slate-950 shadow-md transition-colors disabled:opacity-50 flex items-center gap-1.5 focus:outline-none focus:ring-2 focus:ring-amber-400"
          :disabled="enviando"
          @click="manejarConfirmar"
        >
          <span
            v-if="enviando"
            class="inline-block h-3 w-3 animate-spin rounded-full border-2 border-slate-950 border-t-transparent"
          />
          <span>{{ enviando ? 'Cerrando sesión...' : 'Confirmar cierre de sesión' }}</span>
        </button>
      </div>
    </div>
  </div>
</template>
