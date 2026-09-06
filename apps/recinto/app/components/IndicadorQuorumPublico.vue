<script setup lang="ts">
/**
 * Quórum grande de la franja superior pública.
 *
 * El componente **no** recalcula el quórum: el backend es la única autoridad y
 * ya envía presentes, mínimo requerido y condición alcanzada. Acá solamente se
 * decide cómo se muestran esos tres números.
 *
 * WP-054 introduce dos decisiones humanas:
 *
 * 1. El número principal deja de ser sólo la cantidad de presentes y pasa a ser
 *    `presentes/total`. Sin el total, `8` no dice nada a quien mira desde el
 *    recinto; `8/12` sí. El total es la cantidad de bancas del padrón activo y
 *    lo aporta la pantalla contenedora a partir del propio snapshot público
 *    (`concejales.length`): no hizo falta ningún campo nuevo del backend.
 * 2. La semántica cromática pasa a tener tres estados en lugar de dos, porque
 *    estar *exactamente* en el mínimo reglamentario no es lo mismo que estar por
 *    encima: cualquier ausencia deja la sesión sin quórum.
 *
 *    - presentes > requerido  → verde   (holgura)
 *    - presentes == requerido → amarillo (al límite)
 *    - presentes < requerido  → rojo    (sin quórum)
 *
 * WP-058 completa esa decisión llevando los tres estados también al texto:
 * `Sin quórum`, `Quórum límite` y `Quórum alcanzado`. El color y la palabra
 * pasan a decir lo mismo. Sigue sin haber regla nueva: el backend es la única
 * autoridad sobre la condición reglamentaria y en el nivel `limite` el quórum
 * está alcanzado; el texto sólo aclara que está justo en el mínimo.
 */

import { computed } from 'vue'
import type { EstadoQuorum } from '@sis-leg/api-client'

const props = defineProps<{
  /** Proyección de quórum del backend, o null mientras no hay contexto preparado. */
  quorum: EstadoQuorum | null
  /** Cantidad de bancas del padrón activo, usada como denominador del indicador. */
  total: number
}>()

/**
 * Nivel cromático del indicador.
 *
 * Se calcula comparando dos números que ya vienen decididos por el backend; no
 * introduce ninguna regla de negocio propia. Devuelve `null` cuando todavía no
 * hay quórum proyectado, para que la vista muestre su estado neutro.
 */
const nivelQuorum = computed<'holgado' | 'limite' | 'insuficiente' | null>(() => {
  if (!props.quorum) return null
  if (props.quorum.cantidad_presentes > props.quorum.requerido) return 'holgado'
  if (props.quorum.cantidad_presentes === props.quorum.requerido) return 'limite'
  return 'insuficiente'
})

/**
 * Texto institucional del quórum, con los tres estados de WP-058.
 *
 * Hasta WP-054 el rótulo derivaba de `alcanzado` y sólo tenía dos redacciones:
 * estar exactamente en el mínimo se leía igual que estar holgado. HUMAN_GATE
 * decidió que esos dos casos deben distinguirse también con palabras, no sólo
 * con el color introducido por WP-054.
 *
 * Es importante notar qué **no** cambia: la condición reglamentaria la sigue
 * decidiendo el backend y acá no se recalcula nada. `nivelQuorum` sólo compara
 * dos números que ya vienen proyectados —presentes y requerido— para elegir la
 * redacción. En el nivel `limite` el quórum sigue estando alcanzado; lo que el
 * texto agrega es que no hay margen: una sola ausencia lo pierde.
 */
const textoQuorum = computed(() => {
  if (nivelQuorum.value === 'insuficiente') return 'Sin quórum'
  if (nivelQuorum.value === 'limite') return 'Quórum límite'
  return 'Quórum alcanzado'
})
</script>

<template>
  <div
    data-testid="panel-quorum"
    class="panel-quorum"
    :class="nivelQuorum ? `nivel-${nivelQuorum}` : null"
    :data-nivel-quorum="nivelQuorum"
  >
    <template v-if="quorum">
      <span class="rotulo-panel">Quórum</span>
      <!--
        El testid conserva el nombre histórico, pero su texto ahora es la
        fracción completa. El denominador se dibuja más chico para que la
        fracción entre en el mismo ancho de caja que ocupaba un solo número.
      -->
      <strong data-testid="cantidad-presentes" class="fraccion-quorum">
        {{ quorum.cantidad_presentes }}<span class="denominador-quorum">/{{ total }}</span>
      </strong>
      <span class="detalle-quorum">Presentes · requiere {{ quorum.requerido }}</span>
      <b data-testid="estado-quorum">
        {{ textoQuorum }}
      </b>
    </template>
    <span v-else class="estado-neutro">Quórum sin información</span>
  </div>
</template>

<style scoped>
.panel-quorum {
  min-width: 0;
  min-height: 0;
  height: 100%;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto auto;
  align-items: center;
  justify-items: center;
  gap: 0.1rem;
  padding: clamp(0.42rem, 0.7vw, 0.7rem);
  overflow: hidden;
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 14px;
  color: #cbd5e1;
  background: rgba(15, 23, 42, 0.78);
  text-align: center;
  white-space: nowrap;
}

.rotulo-panel {
  color: #94a3b8;
  font-size: clamp(0.58rem, 0.85vw, 0.78rem);
  font-weight: 900;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

/*
  Tamaño calibrado para la fracción, no para un número suelto: `8/12` ocupa
  aproximadamente el triple de ancho que `8`, así que el cuerpo baja respecto de
  la baseline (2,8–5,2 rem) y el denominador se dibuja a media escala. El ancho
  de la caja —≈12 % del viewport, calibrado contra producción— no cambia.
*/
.fraccion-quorum {
  max-width: 100%;
  overflow: hidden;
  color: #fbbf24;
  font-size: clamp(1.9rem, 5vh, 3.4rem);
  line-height: 0.95;
}

.denominador-quorum {
  color: #94a3b8;
  font-size: 0.52em;
  font-weight: 700;
}

.panel-quorum > b {
  max-width: 100%;
  padding: 0.18rem 0.42rem;
  overflow: hidden;
  border-radius: 999px;
  color: #fde68a;
  background: rgba(120, 53, 15, 0.62);
  font-size: 0.58rem;
  font-weight: 900;
  text-transform: uppercase;
}

.detalle-quorum {
  max-width: 100%;
  overflow: hidden;
  color: #cbd5e1;
  font-size: clamp(0.56rem, 0.78vw, 0.72rem);
  font-weight: 700;
  text-overflow: ellipsis;
}

/*
  Tres niveles cromáticos (WP-054). El nivel `limite` conserva el ámbar de la
  baseline; los otros dos son los que aportan la señal nueva.
*/
.nivel-holgado > .fraccion-quorum {
  color: #34d399;
}

.nivel-holgado > b {
  color: #a7f3d0;
  background: rgba(6, 78, 59, 0.7);
}

.nivel-insuficiente > .fraccion-quorum {
  color: #f87171;
}

.nivel-insuficiente > b {
  color: #fecaca;
  background: rgba(127, 29, 29, 0.7);
}

.estado-neutro {
  align-self: center;
  grid-row: 1 / -1;
  color: #64748b;
}
</style>
