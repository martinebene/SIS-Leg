<script setup lang="ts">
/** Presenta el DTO público sin recalcular mayoría, conteos ni resultado. */

import { computed } from 'vue'
import type { VotacionPublica } from '@sis-leg/api-client'
// WP-063: el factor se escribe siempre con dos decimales truncados. La regla vive en
// frontend-shared para que Recinto y Moderación muestren el mismo texto del mismo dato.
import { formatearFactorMayoria } from '@sis-leg/frontend-shared'

const props = defineProps<{ votacion: VotacionPublica | null }>()

const etiquetasResultado: Record<string, string> = {
  APROBADA: 'Aprobada',
  RECHAZADA: 'Rechazada',
  EMPATADA: 'Empatada',
  INCONCLUSA: 'Inconclusa',
}

const etiquetasBase: Record<string, string> = {
  VOTOS_COMPUTABLES: 'votos computables',
  PRESENTES: 'presentes',
  CUERPO: 'cuerpo completo',
}

const enCurso = computed(() => props.votacion?.estado_recepcion === 'EN_CURSO')
const resultadoHumano = computed(() =>
  props.votacion?.resultado ? etiquetasResultado[props.votacion.resultado] : null,
)
const mayoriaHumana = computed(() => {
  if (!props.votacion) return ''
  if (props.votacion.tipo_mayoria === 'SIMPLE') return 'Mayoría simple'
  const base = etiquetasBase[props.votacion.base] ?? props.votacion.base
  return `Mayoría especial · factor ${formatearFactorMayoria(props.votacion.factor)} · base ${base}`
})
const conteosVisibles = computed(() => (enCurso.value ? null : (props.votacion?.conteos ?? null)))
const resumenVotacion = computed(() => {
  if (!props.votacion) return 'Sin votación activa'
  return `N.º ${props.votacion.numero_votacion} · ${props.votacion.tipo} · ${mayoriaHumana.value}`
})
const estadoPrincipal = computed(() => {
  if (!props.votacion) return 'Sin votación'
  return enCurso.value ? 'En curso' : (resultadoHumano.value ?? 'Recepción cerrada')
})
const claseEstado = computed(() =>
  (props.votacion?.resultado ?? props.votacion?.estado_recepcion ?? 'SIN_VOTACION').toLowerCase(),
)

function etiquetaSentido(sentido: string): string {
  return sentido === 'POSITIVO' ? 'Positivo' : sentido === 'NEGATIVO' ? 'Negativo' : sentido
}
</script>

<template>
  <article data-testid="votacion-publica" class="panel-votacion" :class="`estado-${claseEstado}`">
    <div class="renglon-votacion">
      <strong>Votación</strong>
      <span data-testid="resumen-votacion" :title="resumenVotacion">{{ resumenVotacion }}</span>
    </div>

    <div class="renglon-votacion">
      <strong>Tema</strong>
      <span data-testid="tema-votacion" class="tema-votacion" :title="votacion?.tema ?? '—'">
        {{ votacion?.tema ?? '—' }}
      </span>
    </div>

    <div class="renglon-votacion renglon-estado">
      <strong>Estado</strong>
      <span data-testid="estado-votacion" class="estado-votacion">{{ estadoPrincipal }}</span>
      <!--
        Una votación empatada ya está cerrada: sus conteos son autoritativos y
        deben seguir visibles mientras se espera el desempate. Por eso ambos
        detalles conviven en el renglón en lugar de excluirse entre sí.
      -->
      <span v-if="conteosVisibles" data-testid="conteos-votacion" class="detalle-estado">
        Positivos {{ conteosVisibles.positivos }} · Negativos {{ conteosVisibles.negativos }} ·
        Abstenciones {{ conteosVisibles.abstenciones }} · Total {{ conteosVisibles.total }}
      </span>
      <span
        v-if="votacion?.resultado === 'EMPATADA'"
        data-testid="espera-desempate"
        class="detalle-estado"
      >
        En espera del desempate de Presidencia
      </span>
      <span
        v-if="votacion?.voto_presidencial"
        data-testid="voto-presidencial"
        class="detalle-estado detalle-presidencial"
      >
        Desempate: {{ votacion.voto_presidencial.presidencia }} ·
        {{ etiquetaSentido(votacion.voto_presidencial.sentido) }}
      </span>
    </div>
  </article>
</template>

<style scoped>
.panel-votacion {
  min-width: 0;
  min-height: 0;
  height: 100%;
  display: grid;
  grid-template-rows: repeat(3, minmax(0, 1fr));
  margin: 0;
  padding: clamp(0.45rem, 0.7vw, 0.75rem) clamp(0.65rem, 1vw, 1rem);
  overflow: hidden;
  border: 1px solid rgba(56, 189, 248, 0.36);
  border-radius: 14px;
  background: linear-gradient(135deg, rgba(8, 47, 73, 0.82), rgba(15, 23, 42, 0.92));
}

.renglon-votacion {
  min-width: 0;
  min-height: 0;
  display: grid;
  grid-template-columns: clamp(5.2rem, 8.5vw, 8rem) minmax(0, 1fr);
  align-items: center;
  gap: clamp(0.45rem, 0.8vw, 0.8rem);
  overflow: hidden;
  border-bottom: 1px solid rgba(148, 163, 184, 0.12);
}

.renglon-votacion:last-child {
  border-bottom: 0;
}

.renglon-votacion > strong {
  color: #7dd3fc;
  font-size: clamp(0.72rem, 1.2vw, 1.12rem);
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.renglon-votacion > span {
  min-width: 0;
  overflow: hidden;
  color: #e2e8f0;
  font-size: clamp(0.76rem, 1.25vw, 1.16rem);
  font-weight: 750;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tema-votacion {
  display: block;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.renglon-estado {
  grid-template-columns: clamp(5.2rem, 8.5vw, 8rem) auto minmax(0, 1fr) auto;
}

.estado-votacion {
  padding: 0.25rem 0.58rem;
  border-radius: 999px;
  color: #dbeafe !important;
  background: rgba(30, 64, 175, 0.72);
  font-weight: 900 !important;
  text-transform: uppercase;
}

.estado-aprobada .estado-votacion {
  color: #a7f3d0 !important;
  background: rgba(6, 95, 70, 0.82);
}
.estado-rechazada .estado-votacion {
  color: #fecaca !important;
  background: rgba(153, 27, 27, 0.82);
}
.estado-empatada .estado-votacion {
  color: #fde68a !important;
  background: rgba(146, 64, 14, 0.82);
}
.estado-inconclusa .estado-votacion {
  color: #ddd6fe !important;
  background: rgba(91, 33, 182, 0.78);
}

.detalle-estado {
  padding-left: clamp(0.45rem, 0.8vw, 0.8rem);
  color: #cbd5e1 !important;
  font-size: clamp(0.62rem, 0.9vw, 0.86rem) !important;
}

.detalle-presidencial {
  max-width: clamp(12rem, 24vw, 28rem);
  color: #e9d5ff !important;
}

@media (max-width: 1100px) {
  .renglon-estado {
    grid-template-columns: clamp(5.2rem, 8.5vw, 8rem) auto minmax(0, 1fr);
  }

  .detalle-presidencial {
    display: none;
  }
}
</style>
