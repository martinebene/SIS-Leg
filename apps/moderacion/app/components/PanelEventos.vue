<script setup lang="ts">
/**
 * Panel de Eventos Recientes (Cuadrante 4).
 *
 * Consume directamente la baseline autoritativa `eventos_recientes` y aplica
 * únicamente presentación local: un filtro visual por nivel acumulativo
 * L1/L2/L3 y un orden descendente por `seq`.
 *
 * WP-041 introduce tres comportamientos de presentación:
 *
 * 1. El evento más nuevo (mayor `seq`) se muestra primero. El backend sigue
 *    siendo la única autoridad y puede proyectar el arreglo en cualquier
 *    orden: el orden visual se deriva sobre una copia, nunca mutando props.
 * 2. El selector `Nivel visible` vive en la cabecera del panel (slot
 *    `acciones` de `PanelContenedor`), fuera del área scrolleable, para que
 *    siga accesible aunque la lista esté desplazada.
 * 3. Cuando llega un snapshot con un `seq` mayor al máximo observado hasta
 *    ese momento, la lista vuelve al inicio de su scroll para que el evento
 *    recién ocurrido quede visible sin intervención del operador.
 *
 * WP-052 agrega la lectura enriquecida y segura de los hechos sensibles:
 *
 * - Cuando el backend adjunta `evento.hecho`, el cuerpo de la tarjeta muestra
 *   identidad/banca y un detalle ya resuelto en lugar del mensaje humano de
 *   auditoría. Este componente **no interpreta** `mensaje`: si lo hiciera,
 *   una redacción de auditoría se convertiría en un contrato de UI encubierto
 *   y cualquier cambio de texto podría filtrar el sentido de un voto.
 * - El emoji también llega decidido por el backend (`hecho.icono`). Mientras
 *   el sentido individual sea secreto ese campo vale `null` y aquí no hay
 *   ninguna regla que pueda “adivinarlo”: el secreto se protege en servidor.
 * - El icono se dibuja a la derecha del registro y ocupa aproximadamente la
 *   altura de las dos filas de texto existentes.
 *
 * CRÍTICO: el crecimiento del listado no debe aumentar la altura de los demás
 * paneles. Por eso el listado tiene scroll interno propio y ocupa exactamente
 * la altura disponible del cuerpo del panel.
 */

import { computed, nextTick, ref, watch } from 'vue'
import type { EstadoModeracion } from '@sis-leg/api-client'
import {
  filtrarEventosPorNivel,
  hayActividadNueva,
  seqMaximoEventos,
  type FiltroNivelEventos,
} from '@sis-leg/frontend-shared'
import PanelContenedor from './PanelContenedor.vue'

const props = withDefaults(
  defineProps<{
    /** Estado de moderación recibido desde el backend */
    estado: EstadoModeracion | null
    /**
     * Nivel con el que abre el panel.
     *
     * Existe por WP-056: cuando un aviso de Apoyo Técnico reemplaza el cuadrante 4, este
     * componente se desmonta por completo —no queda oculto detrás— y al volver debe
     * reaparecer con el nivel que el operador había elegido. El shell recuerda ese valor
     * y lo devuelve por acá. Sigue siendo un dato puramente visual: no altera la
     * colección autoritativa ni lo que el backend decide publicar.
     */
    nivelInicial?: FiltroNivelEventos
  }>(),
  { nivelInicial: 'L3' },
)

const emit = defineEmits<{
  /** Informa al shell el nivel elegido, para poder restaurarlo tras un aviso. */
  (evento: 'cambiar-nivel', nivel: FiltroNivelEventos): void
}>()

// El filtro es deliberadamente local: no acumula eventos ni modifica la
// auditoría. L3 es la vista inicial acordada para la operación cotidiana.
//
// WP-056: la tabla de niveles acumulativos y las derivaciones sobre la colección
// viven en `@sis-leg/frontend-shared` porque el puesto de Apoyo Técnico muestra
// exactamente la misma franja segura. Compartir las funciones puras evita que las
// dos pantallas puedan divergir en qué considera visible cada nivel.
const filtroSeleccionado = ref<FiltroNivelEventos>(props.nivelInicial)

watch(filtroSeleccionado, (nivel) => emit('cambiar-nivel', nivel))

/**
 * Referencia DOM al único contenedor con scroll del panel.
 *
 * Se necesita explícitamente porque, ante la llegada de un evento nuevo, hay
 * que reposicionar el scroll al inicio (`scrollTop = 0`) sin recurrir a
 * selectores globales ni a temporizadores.
 */
const contenedorLista = ref<HTMLElement | null>(null)

/**
 * Colección visual derivada: filtra por nivel acumulativo y ordena por `seq`
 * descendente. La derivación completa vive en la función compartida, que trabaja
 * siempre sobre una copia y jamás reordena `props.estado.eventos_recientes`.
 *
 * Eso mantiene la invariante de WP-041: el frontend no muta ni acumula la
 * baseline autoritativa, solo la proyecta. Al derivarse siempre del snapshot
 * vigente, el resultado es determinista aunque el backend envíe los eventos en
 * orden ascendente, descendente o reemplace por completo la colección tras una
 * reconexión.
 */
const eventosVisibles = computed(() =>
  filtrarEventosPorNivel(props.estado?.eventos_recientes, filtroSeleccionado.value),
)

/**
 * Mayor `seq` presente en el snapshot completo, sin aplicar el filtro visual.
 *
 * Se calcula sobre la colección sin filtrar a propósito: cambiar el nivel
 * visible no debe interpretarse como la llegada de un evento nuevo, porque
 * eso movería el scroll del operador sin que haya ocurrido nada en el recinto.
 */
const seqMaximoSnapshot = computed(() => seqMaximoEventos(props.estado?.eventos_recientes))

/**
 * Último `seq` máximo efectivamente observado por este panel.
 *
 * No es historia local de eventos (eso está prohibido): es un único número
 * que permite distinguir "llegó actividad nueva" de "el snapshot cambió por
 * otro motivo", por ejemplo un reinicio de contexto donde la secuencia vuelve
 * a valores menores.
 */
// Se inicializa con el snapshot de montaje porque en ese momento la lista ya
// está arriba: el primer render no es "actividad nueva" y no debe mover nada.
const seqMaximoObservado = ref<number | null>(seqMaximoSnapshot.value)

watch(seqMaximoSnapshot, async (maximoActual) => {
  const maximoPrevio = seqMaximoObservado.value
  // Se adopta siempre el snapshot vigente, incluso si la secuencia se reinició
  // hacia valores menores: nunca se mezcla con el anterior.
  seqMaximoObservado.value = maximoActual

  if (!hayActividadNueva(maximoActual, maximoPrevio)) return

  // `nextTick` espera a que Vue haya renderizado la colección derivada; solo
  // entonces el contenedor contiene ya el evento nuevo en su primera fila.
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
</script>

<template>
  <PanelContenedor
    titulo="Eventos"
    data-testid="panel-eventos"
    :badge="`${eventosVisibles.length} de ${estado?.eventos_recientes?.length ?? 0}`"
  >
    <!--
      Selector de nivel en la cabecera del panel: al vivir en el slot de
      acciones queda fuera del cuerpo scrolleable y permanece visible aunque
      el operador desplace la lista.
    -->
    <template #acciones>
      <label
        for="filtro-eventos"
        data-testid="etiqueta-filtro-eventos"
        class="text-[11px] font-semibold text-slate-400"
      >
        Nivel visible
      </label>
      <select
        id="filtro-eventos"
        v-model="filtroSeleccionado"
        data-testid="filtro-eventos"
        class="rounded border border-slate-700 bg-slate-950 px-2 py-0.5 text-[11px] text-slate-100"
      >
        <option value="L3">Principales (L3)</option>
        <option value="L2">Intermedios (L2+L3)</option>
        <option value="L1">Sistema (L1+L2+L3)</option>
      </select>
    </template>

    <!--
      Único contenedor con scroll del panel. `h-full` lo ajusta exactamente a
      la altura disponible del cuerpo, de modo que el desborde se resuelve acá
      dentro y el cuadrante nunca crece ni provoca scroll de página.
    -->
    <div ref="contenedorLista" data-testid="lista-eventos" class="h-full overflow-y-auto">
      <div v-if="eventosVisibles.length" class="space-y-1 font-mono text-[11px]">
        <div
          v-for="evento in eventosVisibles"
          :key="evento.seq"
          data-testid="evento-reciente"
          class="rounded border border-slate-800 bg-slate-950/70 px-2 py-1 text-slate-300 transition-colors hover:border-slate-700"
        >
          <!--
            Fila horizontal: a la izquierda las dos filas de texto existentes y
            a la derecha el icono del hecho, que las abarca en altura.
          -->
          <div data-testid="fila-evento" class="flex items-center gap-2">
            <div data-testid="cuerpo-evento" class="min-w-0 flex-1">
              <!--
                Cabecera compacta de la tarjeta: mantiene visibles seq, nivel,
                etiqueta, código y timestamp en una sola línea que puede envolver.
              -->
              <div class="flex flex-wrap items-center gap-x-2 gap-y-0.5 leading-tight">
                <span class="font-semibold text-cyan-400">#{{ evento.seq }}</span>
                <span
                  data-testid="nivel-evento"
                  class="rounded border px-1 text-[10px] font-bold leading-tight"
                  :class="claseNivel(evento.nivel)"
                >
                  {{ evento.nivel }}
                </span>
                <span data-testid="etiqueta-evento" class="text-slate-400"
                  >[{{ evento.etiqueta }}]</span
                >
                <span data-testid="codigo-evento" class="font-semibold text-slate-200">
                  {{ evento.codigo_evento }}
                </span>
                <span class="ml-auto text-[10px] text-slate-500">{{ evento.timestamp }}</span>
              </div>

              <!--
                Segunda fila. Con hecho estructurado se muestran identidad y
                detalle ya resueltos por el backend; sin él se conserva el
                mensaje humano de auditoría tal como venía de WP-041.
              -->
              <p
                v-if="evento.hecho"
                data-testid="hecho-evento"
                class="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 leading-tight"
              >
                <span data-testid="hecho-concejal" class="text-slate-200">
                  {{ evento.hecho.concejal.nombre }} {{ evento.hecho.concejal.apellido }} · Banca
                  {{ evento.hecho.concejal.banca }}
                </span>
                <span data-testid="hecho-detalle" class="font-semibold text-slate-300">
                  {{ evento.hecho.detalle }}
                </span>
              </p>
              <p
                v-else
                data-testid="mensaje-evento"
                class="mt-0.5 whitespace-pre-wrap break-words leading-tight text-slate-300"
              >
                {{ evento.mensaje }}
              </p>
            </div>

            <!--
              Icono del hecho. Solo existe cuando el backend lo envía: durante
              el secreto del voto llega `null` y la tarjeta queda sin emoji.
              La altura fija de 1.75rem equivale aproximadamente a las dos
              filas de texto de 11px con interlineado ajustado.
            -->
            <span
              v-if="evento.hecho?.icono"
              data-testid="icono-evento"
              role="img"
              :aria-label="evento.hecho.detalle"
              class="flex h-7 w-7 shrink-0 items-center justify-center text-[22px] leading-none"
            >
              {{ evento.hecho.icono }}
            </span>
          </div>
        </div>
      </div>

      <!--
        Estados vacíos compactos: no reservan altura innecesaria y distinguen
        "todavía no hay eventos" de "el filtro vigente no coincide con ninguno".
      -->
      <p
        v-else
        data-testid="eventos-vacio"
        class="rounded border border-dashed border-slate-800 px-2 py-2 text-center text-xs text-slate-400"
      >
        {{
          estado?.eventos_recientes?.length
            ? 'No hay eventos para el nivel seleccionado'
            : 'Sin eventos en la sesión activa'
        }}
      </p>
    </div>
  </PanelContenedor>
</template>
