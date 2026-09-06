<script setup lang="ts">
/**
 * Franja de eventos operativos del puesto de Apoyo Técnico (WP-056).
 *
 * Consume `EstadoTecnico.eventos_recientes`, que el backend construye con **el mismo
 * método** que la proyección de Moderación. Eso significa que la frontera de secreto de
 * WP-052 se aplica una sola vez, en el servidor, y no puede divergir entre puestos:
 * mientras el sentido individual de un voto siga siendo secreto, tampoco lo ve Apoyo
 * Técnico.
 *
 * Este componente, por lo tanto, **no interpreta nada**:
 *
 * - no lee `mensaje` para deducir identidad, tecla ni sentido de voto. Ese campo es la
 *   redacción humana de la auditoría; convertirlo en contrato de UI permitiría que un
 *   cambio de texto filtrara información protegida;
 * - no elige el emoji: llega decidido por el backend en `hecho.icono` y vale `null`
 *   mientras el sentido sea secreto. Acá no existe ninguna regla capaz de "adivinarlo".
 *
 * El filtro por nivel y el orden descendente por `seq` se derivan con las funciones puras
 * compartidas, de modo que este puesto y Moderación no puedan mostrar franjas distintas.
 */

import { computed, nextTick, ref, watch } from 'vue'
import type { EventoRecienteProyectado } from '@sis-leg/api-client'
import {
  filtrarEventosPorNivel,
  hayActividadNueva,
  seqMaximoEventos,
  type FiltroNivelEventos,
} from '@sis-leg/frontend-shared'

const props = defineProps<{
  /** Colección segura tal como la proyecta el backend. */
  eventos: readonly EventoRecienteProyectado[]
}>()

const filtroSeleccionado = ref<FiltroNivelEventos>('L3')
const contenedorLista = ref<HTMLElement | null>(null)

const eventosVisibles = computed(() =>
  filtrarEventosPorNivel(props.eventos, filtroSeleccionado.value),
)
const seqMaximoSnapshot = computed(() => seqMaximoEventos(props.eventos))
const seqMaximoObservado = ref<number | null>(seqMaximoSnapshot.value)

/**
 * Devuelve la lista al inicio cuando llega actividad nueva, para que el evento recién
 * ocurrido quede visible sin que el operador tenga que desplazarse.
 */
watch(seqMaximoSnapshot, async (maximoActual) => {
  const maximoPrevio = seqMaximoObservado.value
  seqMaximoObservado.value = maximoActual
  if (!hayActividadNueva(maximoActual, maximoPrevio)) return
  await nextTick()
  if (contenedorLista.value) contenedorLista.value.scrollTop = 0
})

function claseNivel(nivel: string): string {
  switch (nivel) {
    case 'L3':
      return 'border-violet-700 bg-violet-950 text-violet-200'
    case 'L2':
      return 'border-cyan-800 bg-cyan-950 text-cyan-300'
    case 'L1':
      return 'border-slate-700 bg-slate-900 text-slate-300'
    default:
      return 'border-rose-800 bg-rose-950 text-rose-200'
  }
}

defineExpose({ filtroSeleccionado })
</script>

<template>
  <div class="flex h-full min-h-0 flex-col gap-1.5">
    <div class="flex shrink-0 items-center gap-2">
      <label
        for="filtro-eventos-tecnico"
        class="text-[11px] font-semibold text-slate-400"
        data-testid="etiqueta-filtro-eventos-tecnico"
      >
        Nivel visible
      </label>
      <select
        id="filtro-eventos-tecnico"
        v-model="filtroSeleccionado"
        data-testid="filtro-eventos-tecnico"
        class="rounded border border-slate-700 bg-slate-950 px-2 py-0.5 text-[11px] text-slate-100"
      >
        <option value="L3">Principales (L3)</option>
        <option value="L2">Intermedios (L2+L3)</option>
        <option value="L1">Sistema (L1+L2+L3)</option>
      </select>
      <span class="ml-auto text-[11px] text-slate-500">
        {{ eventosVisibles.length }} de {{ eventos.length }}
      </span>
    </div>

    <!-- Único contenedor con scroll de este panel. -->
    <div
      ref="contenedorLista"
      data-testid="lista-eventos-tecnico"
      class="min-h-0 flex-1 overflow-y-auto"
    >
      <div v-if="eventosVisibles.length" class="space-y-1 font-mono text-[11px]">
        <div
          v-for="evento in eventosVisibles"
          :key="evento.seq"
          data-testid="evento-tecnico"
          class="rounded border border-slate-800 bg-slate-950/70 px-2 py-1 text-slate-300"
        >
          <div class="flex items-center gap-2">
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-x-2 gap-y-0.5 leading-tight">
                <span class="font-semibold text-cyan-400">#{{ evento.seq }}</span>
                <span
                  data-testid="nivel-evento-tecnico"
                  class="rounded border px-1 text-[10px] font-bold leading-tight"
                  :class="claseNivel(evento.nivel)"
                >
                  {{ evento.nivel }}
                </span>
                <span class="text-slate-400">[{{ evento.etiqueta }}]</span>
                <span data-testid="codigo-evento-tecnico" class="font-semibold text-slate-200">
                  {{ evento.codigo_evento }}
                </span>
                <span class="ml-auto text-[10px] text-slate-500">{{ evento.timestamp }}</span>
              </div>

              <p
                v-if="evento.hecho"
                data-testid="hecho-evento-tecnico"
                class="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 leading-tight"
              >
                <span class="text-slate-200">
                  {{ evento.hecho.concejal.nombre }} {{ evento.hecho.concejal.apellido }} · Banca
                  {{ evento.hecho.concejal.banca }}
                </span>
                <span data-testid="detalle-evento-tecnico" class="font-semibold text-slate-300">
                  {{ evento.hecho.detalle }}
                </span>
              </p>
              <p
                v-else
                data-testid="mensaje-evento-tecnico"
                class="mt-0.5 leading-tight break-words whitespace-pre-wrap text-slate-300"
              >
                {{ evento.mensaje }}
              </p>
            </div>

            <!-- Sólo existe cuando el backend lo envía: durante el secreto llega `null`. -->
            <span
              v-if="evento.hecho?.icono"
              data-testid="icono-evento-tecnico"
              role="img"
              :aria-label="evento.hecho.detalle"
              class="flex h-7 w-7 shrink-0 items-center justify-center text-[22px] leading-none"
            >
              {{ evento.hecho.icono }}
            </span>
          </div>
        </div>
      </div>

      <p
        v-else
        data-testid="eventos-tecnico-vacio"
        class="rounded border border-dashed border-slate-800 px-2 py-2 text-center text-xs text-slate-400"
      >
        {{
          eventos.length
            ? 'No hay eventos para el nivel seleccionado'
            : 'Sin eventos en la sesión activa'
        }}
      </p>
    </div>
  </div>
</template>
