<script setup lang="ts">
/**
 * Franja inferior de hechos públicos ya sanitizados por FastAPI.
 *
 * IMPORTANTE (WP-050): **la Pantalla del Recinto ya no lo renderiza.** HUMAN_GATE
 * decidió recuperar esa altura para las bancas, pero decidió también que la
 * proyección `eventos_publicos` del backend, el DTO y el contrato OpenAPI siguen
 * existiendo sin cambios. Por eso el componente se conserva versionado y con su
 * prueba de sanitización: no es código a resucitar por descuido, es la vista que
 * corresponde a un dato del contrato que hoy no se dibuja. Volver a mostrarlo es
 * agregar una sola etiqueta en `PantallaRecinto.vue`, no reescribirlo.
 *
 * No recibe auditoría de Moderación ni implementa selectores de nivel. Cada
 * fila usa exclusivamente el DTO público allowlist; si el backend agregara
 * campos internos a un objeto por error, Vue no los recorre ni los renderiza.
 */

import { nextTick, ref, watch } from 'vue'
import type { EventoPublicoProyectado } from '@sis-leg/api-client'

const props = defineProps<{ eventos: EventoPublicoProyectado[] }>()
const lista = ref<HTMLOListElement | null>(null)

/** Mantiene visible el hecho más nuevo sin conservar una historia local. */
watch(
  () => props.eventos,
  async () => {
    await nextTick()
    if (lista.value) lista.value.scrollTop = lista.value.scrollHeight
  },
  { immediate: true },
)
</script>

<template>
  <section data-testid="panel-eventos-publicos" class="panel-eventos-publicos">
    <header>
      <span>Eventos públicos</span>
      <b>{{ eventos.length }}</b>
    </header>

    <ol
      ref="lista"
      data-testid="lista-eventos-publicos"
      class="lista-eventos-publicos"
      aria-label="Eventos públicos principales en orden cronológico"
    >
      <li
        v-for="evento in eventos"
        :key="evento.seq"
        v-bind="{
          'data-seq': evento.seq,
          'data-codigo-evento': evento.codigo_evento,
        }"
        :title="evento.texto"
      >
        <time>{{ evento.timestamp }}</time>
        <span>{{ evento.categoria }}</span>
        <p>{{ evento.texto }}</p>
      </li>
      <li v-if="eventos.length === 0" class="eventos-vacios">Sin eventos públicos recientes</li>
    </ol>
  </section>
</template>

<style scoped>
.panel-eventos-publicos {
  min-width: 0;
  min-height: 0;
  height: 100%;
  display: grid;
  grid-template-columns: clamp(8.5rem, 13vw, 13rem) minmax(0, 1fr);
  overflow: hidden;
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 14px;
  background: rgba(7, 17, 31, 0.82);
}

.panel-eventos-publicos > header {
  display: grid;
  align-content: center;
  justify-items: center;
  gap: 0.35rem;
  padding: 0.55rem;
  border-right: 1px solid rgba(148, 163, 184, 0.16);
  color: #94a3b8;
  font-size: clamp(0.58rem, 0.8vw, 0.72rem);
  font-weight: 900;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.panel-eventos-publicos > header b {
  min-width: 2rem;
  padding: 0.18rem 0.45rem;
  border-radius: 999px;
  color: #e0f2fe;
  background: rgba(14, 116, 144, 0.45);
  text-align: center;
}

.lista-eventos-publicos {
  min-width: 0;
  min-height: 0;
  margin: 0;
  padding: 0.25rem 0.55rem;
  overflow-y: auto;
  overscroll-behavior: contain;
  list-style: none;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  scrollbar-gutter: stable;
}

.lista-eventos-publicos li {
  min-width: 0;
  display: grid;
  grid-template-columns: clamp(8rem, 12vw, 11.5rem) clamp(5.2rem, 8vw, 8rem) minmax(0, 1fr);
  align-items: center;
  gap: clamp(0.4rem, 0.8vw, 0.8rem);
  padding: 0.25rem 0;
  overflow: hidden;
  border-bottom: 1px solid rgba(148, 163, 184, 0.1);
  font-size: clamp(0.58rem, 0.75vw, 0.7rem);
  line-height: 1.2;
}

.lista-eventos-publicos time,
.lista-eventos-publicos span,
.lista-eventos-publicos p {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.lista-eventos-publicos time {
  color: #94a3b8;
}

.lista-eventos-publicos span {
  color: #7dd3fc;
  font-weight: 900;
  letter-spacing: 0.06em;
}

.lista-eventos-publicos p {
  color: #e2e8f0;
  font-weight: 700;
}

.lista-eventos-publicos .eventos-vacios {
  height: 100%;
  display: grid;
  grid-template-columns: 1fr;
  place-items: center;
  border: 0;
  color: #64748b;
}
</style>
