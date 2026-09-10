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
 * WP-058 completó esa decisión llevando los tres estados también al texto:
 * `Sin quórum`, `Quórum límite` y `Quórum alcanzado`. El color y la palabra
 * pasaban a decir lo mismo.
 *
 * WP-097 revisa esa forma por pedido explícito de HUMAN_GATE tras la prueba de
 * campo: el bloque de quórum debe quedar **únicamente con título y número**, con
 * el título al doble de cuerpo y el número un 50 % más grande, para que se lea
 * desde el fondo del recinto. En consecuencia desaparecen los dos textos
 * secundarios que se dibujaban debajo del número: el detalle
 * `Presentes · requiere N` y la píldora con la palabra del nivel.
 *
 * Lo que **no** cambia es la semántica: el nivel de quórum sigue calculándose
 * igual, sigue pintando el número con los tres colores de WP-054 y sigue
 * publicándose en el atributo `data-nivel-quorum`, que es donde las pruebas leen
 * la condición. Se pierde la redundancia textual de WP-058, no la información:
 * el requerido continúa siendo autoridad del backend y sigue visible en la
 * pantalla de Moderación, que es la superficie de quien opera.
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

        Desde WP-097 estos dos elementos son el contenido completo del bloque: no
        hay detalle debajo del número ni píldora con la palabra del nivel.
      -->
      <strong data-testid="cantidad-presentes" class="fraccion-quorum">
        {{ quorum.cantidad_presentes }}<span class="denominador-quorum">/{{ total }}</span>
      </strong>
    </template>
    <span v-else class="estado-neutro">Quórum sin información</span>
  </div>
</template>

<style scoped>
/*
  Dos filas, no cuatro (WP-097).

  Al quedar sólo título y número, la caja reparte todo su alto entre esos dos
  elementos: el rótulo toma el alto que necesita y la fracción se queda con el
  resto. El alto total del bloque sigue siendo el de la franja, que no cambia.
*/
.panel-quorum {
  min-width: 0;
  min-height: 0;
  height: 100%;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
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

/*
  Título al doble: los tres términos del `clamp` anterior —`0,58rem / 0,85vw /
  0,78rem`— multiplicados por 2, de modo que el aumento sea exactamente del doble
  en cualquier resolución gane el término que gane.
*/
.rotulo-panel {
  max-width: 100%;
  overflow: hidden;
  color: #94a3b8;
  font-size: clamp(1.16rem, 1.7vw, 1.56rem);
  font-weight: 900;
  /* Interlineado holgado a propósito: con menos, el recorte del contenedor se come la
     tilde de `QUÓRUM`. El bloque perdió dos renglones, así que hay alto de sobra. */
  line-height: 1.25;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

/*
  Fracción un 50 % más grande (WP-097): los tres términos del `clamp` anterior
  —`1,9rem / 5vh / 3,4rem`— multiplicados por 1,5. El denominador sigue a media
  escala del numerador, así que la fracción crece entera sin desbalancearse.

  El ancho de la caja lo fija `PantallaRecinto`, que en el mismo WP lo ensancha
  para que la fracción más grande respire y aproveche el ancho disponible.
*/
.fraccion-quorum {
  max-width: 100%;
  overflow: hidden;
  color: #fbbf24;
  font-size: clamp(2.85rem, 7.5vh, 5.1rem);
  /* Mismo motivo que el rótulo: el interlineado debe alcanzar para la altura real de los
     dígitos, que con `line-height: 1` quedaban recortados arriba y abajo. */
  line-height: 1.15;
}

.denominador-quorum {
  color: #94a3b8;
  font-size: 0.52em;
  font-weight: 700;
}

/*
  Tres niveles cromáticos (WP-054). El nivel `limite` conserva el ámbar de la
  baseline; los otros dos son los que aportan la señal nueva. Desde WP-097 el
  color vive solamente en el número: es el único lugar donde queda el nivel, así
  que se conserva tal cual estaba.
*/
.nivel-holgado > .fraccion-quorum {
  color: #34d399;
}

.nivel-insuficiente > .fraccion-quorum {
  color: #f87171;
}

.estado-neutro {
  align-self: center;
  grid-row: 1 / -1;
  color: #64748b;
}
</style>
