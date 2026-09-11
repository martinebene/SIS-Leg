<script setup lang="ts">
/**
 * Zócalo inferior izquierdo para Browser Source de OBS (WP-099).
 *
 * ## Qué muestra
 *
 * Exactamente los tres renglones de la franja superior del Recinto —`Votación`, `Tema` y
 * `Estado`— con la misma redacción institucional. No agrega información nueva, no elige
 * qué mostrar por su cuenta y no guarda nada: recibe el snapshot público, lo pasa por los
 * dos composables compartidos y dibuja el resultado.
 *
 * - `usePresentacionVotacion` decide **qué** votación corresponde mostrar en este instante:
 *   ninguna en `SIN_PREPARAR`, y ninguna cuando el resultado ya dejó de ser visible.
 * - `usePresentacionVotacionPublica` decide **cómo se lee** esa votación.
 *
 * Las dos funciones son las mismas que usa la Pantalla del Recinto, de modo que las dos
 * superficies no pueden discrepar ni en el momento ni en el texto.
 *
 * ## Qué no tiene
 *
 * Ningún control de operador: no hay botones, campos, enlaces ni menús. Una Browser Source
 * no recibe clics del operador de la transmisión y el WP lo prohíbe expresamente.
 *
 * ## Geometría
 *
 * El WP fija proporciones, no píxeles:
 *
 * ```text
 *  ┌───────────────────────────────────────────────────────────┐
 *  │                                                           │
 *  │                    croma verde uniforme                   │
 *  │                                                           │
 *  │  ┌─────────────────────────────────────────┐              │
 *  │  │ VOTACIÓN  N.º 12 · …                    │  ~20 % libre │
 *  │  │ TEMA      Expediente …                  │  a la derecha│
 *  │  │ ESTADO    Aprobada · Positivos 8 …      │              │
 *  │  └─────────────────────────────────────────┘              │
 *  └───────────────────────────────────────────────────────────┘
 *      ↑ margen                ancho ≈ 80 % del viewport
 * ```
 *
 * El bloque se posiciona en coordenadas del viewport (`vw`/`vh`) y no dentro de un flujo,
 * porque su posición es un requisito de encuadre de la transmisión y no debe depender de
 * cuánto texto traiga cada renglón. Los cuerpos tipográficos llevan además un techo en
 * `cqh` —porcentaje del alto real del zócalo— que garantiza que los tres renglones entren
 * siempre, en cualquier resolución, sin que el bloque crezca ni recorte texto.
 */

import { computed, toRef } from 'vue'
import type { EstadoRecinto } from '@sis-leg/api-client'
import {
  etiquetaSentidoVoto,
  usePresentacionVotacion,
  usePresentacionVotacionPublica,
} from '@sis-leg/frontend-shared'

const props = defineProps<{ estado: EstadoRecinto | null }>()

const { votacion: votacionPresentada } = usePresentacionVotacion(toRef(props, 'estado'))

const {
  resumen: resumenVotacion,
  tema,
  estado: estadoPrincipal,
  claseEstado,
  conteosVisibles,
  esperaDesempate,
  votoPresidencial,
} = usePresentacionVotacionPublica(votacionPresentada)

/**
 * Detalle que acompaña al estado, resuelto a un único texto.
 *
 * En el Recinto estos detalles ocupan columnas separadas porque la franja es ancha y alta.
 * Acá hay un solo renglón disponible, así que se concatenan con el mismo separador
 * institucional. Es la divergencia visual mínima que permite el WP: cambia la disposición,
 * no el contenido ni su significado.
 */
const detalleEstado = computed(() => {
  const partes: string[] = []
  const conteos = conteosVisibles.value
  if (conteos) {
    partes.push(
      `Positivos ${conteos.positivos} · Negativos ${conteos.negativos} · ` +
        `Abstenciones ${conteos.abstenciones} · Total ${conteos.total}`,
    )
  }
  if (esperaDesempate.value) partes.push('En espera del desempate de Presidencia')
  const desempate = votoPresidencial.value
  if (desempate) {
    partes.push(`Desempate: ${desempate.presidencia} · ${etiquetaSentidoVoto(desempate.sentido)}`)
  }
  return partes.join(' · ')
})
</script>

<template>
  <div data-testid="lienzo-chroma" class="lienzo-chroma">
    <section
      data-testid="zocalo"
      class="zocalo"
      :class="`estado-${claseEstado}`"
      aria-label="Votación en curso"
    >
      <div class="renglon">
        <strong class="rotulo">Votación</strong>
        <span data-testid="zocalo-votacion" class="valor">{{ resumenVotacion }}</span>
      </div>

      <div class="renglon">
        <strong class="rotulo">Tema</strong>
        <span data-testid="zocalo-tema" class="valor">{{ tema }}</span>
      </div>

      <div class="renglon renglon-estado">
        <strong class="rotulo">Estado</strong>
        <span data-testid="zocalo-estado" class="valor pildora-estado">{{ estadoPrincipal }}</span>
        <span v-if="detalleEstado" data-testid="zocalo-detalle-estado" class="detalle">
          {{ detalleEstado }}
        </span>
      </div>
    </section>
  </div>
</template>

<style scoped>
/*
  Lienzo de croma.

  Cubre el viewport completo y es el único elemento que puede pintar verde. `position:
  fixed` lo desacopla del flujo del documento: pase lo que pase con el contenido, el lienzo
  mide exactamente el frame y nunca puede generar desplazamiento.
*/
.lienzo-chroma {
  position: fixed;
  inset: 0;
  overflow: hidden;
  /* Verde de croma canónico, opaco y sin degradado: un valor plano es lo único que un
     filtro de croma puede recortar sin dejar borde. */
  background-color: #00ff00;
}

/*
  Geometría del bloque, expresada como proporciones del frame.

  - `--margen-lateral` y `--margen-inferior` son el «pequeño margen» que pide el WP para
    que el zócalo no quede pegado al borde del encuadre.
  - el ancho es el 80 % exacto del viewport; sumado al margen izquierdo, deja algo más del
    18 % libre a la derecha, que es la franja donde la producción suele ubicar un logo o el
    testigo de aire.
  - el alto es el 20 % exacto del viewport.

  Se usan `vw`/`vh` y no porcentajes de un contenedor para que la proporción sea siempre
  respecto del frame que captura OBS, con independencia de la jerarquía de elementos.
*/
.zocalo {
  --margen-lateral: 1.5vw;
  --margen-inferior: 1.5vh;

  position: absolute;
  left: var(--margen-lateral);
  bottom: var(--margen-inferior);
  width: 80vw;
  height: 20vh;

  display: grid;
  grid-template-rows: repeat(3, minmax(0, 1fr));
  /* Sin relleno vertical: los tres renglones necesitan el alto completo para poder
     duplicar el cuerpo sin desbordar, igual que resolvió WP-097 en la franja del Recinto. */
  padding: 0 clamp(0.7rem, 1.2vw, 1.4rem);
  overflow: hidden;

  border: 2px solid #1d4e7a;
  border-radius: 14px;
  /*
    Fondo plano y **opaco**. No hay degradado ni transparencia a propósito: cualquier
    canal alfa dejaría pasar el verde por detrás del texto y lo teñiría, y el filtro de
    croma recortaría parte del propio zócalo.
  */
  background-color: #0b213a;
  color: #f1f5f9;

  /* Declara el zócalo como contenedor de tamaño para que `cqh` signifique «porcentaje del
     alto real del bloque». Puede hacerlo sin bucle porque su alto no lo decide su
     contenido: lo fijan las unidades de viewport de arriba. */
  container-type: size;
}

.renglon {
  min-width: 0;
  min-height: 0;
  display: grid;
  grid-template-columns: clamp(5.5rem, 9vw, 9rem) minmax(0, 1fr);
  align-items: center;
  gap: clamp(0.4rem, 0.7vw, 0.8rem);
  overflow: hidden;
  border-bottom: 1px solid #1d3550;
}

.renglon:last-child {
  border-bottom: 0;
}

/*
  Techo tipográfico geométrico.

  Además del `clamp` por viewport, cada cuerpo está limitado a un porcentaje del alto del
  zócalo. Tres renglones de `27 cqh × 1,2` de interlineado ocupan como máximo el 97,2 % del
  alto disponible, así que los tres entran siempre y ninguno puede recortarse en vertical,
  sea cual sea la resolución del frame.
*/
.rotulo {
  overflow: hidden;
  color: #7dd3fc;
  font-size: min(clamp(0.85rem, 1.7vw, 1.8rem), 25cqh);
  line-height: 1.2;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  white-space: nowrap;
}

.valor {
  min-width: 0;
  overflow: hidden;
  font-size: min(clamp(0.9rem, 1.8vw, 1.9rem), 27cqh);
  font-weight: 750;
  line-height: 1.2;
  /* Un tema más largo que el renglón se recorta con puntos suspensivos dentro del bloque:
     nunca ensancha el zócalo ni produce desplazamiento del frame. */
  text-overflow: ellipsis;
  white-space: nowrap;
}

.renglon-estado {
  grid-template-columns: clamp(5.5rem, 9vw, 9rem) auto minmax(0, 1fr);
}

/*
  Píldora del estado.

  Todos los colores son opacos y ninguno pertenece a la familia del verde de croma. Es la
  única divergencia visual deliberada respecto del Recinto, donde «Aprobada» se pinta en
  verde oscuro: sobre un fondo de croma, un verde —aunque sea oscuro— puede caer dentro del
  umbral de similitud del filtro y abrir un agujero en el zócalo. El cian cumple la misma
  función semántica de «resultado favorable» sin ese riesgo.
*/
.pildora-estado {
  padding: 0 0.6rem;
  border-radius: 999px;
  color: #dbeafe;
  background-color: #1e40af;
  font-weight: 900;
  text-transform: uppercase;
}

.estado-aprobada .pildora-estado {
  color: #cffafe;
  background-color: #155e75;
}

.estado-rechazada .pildora-estado {
  color: #fecaca;
  background-color: #991b1b;
}

.estado-empatada .pildora-estado {
  color: #fde68a;
  background-color: #92400e;
}

.estado-inconclusa .pildora-estado {
  color: #ddd6fe;
  background-color: #5b21b6;
}

.detalle {
  min-width: 0;
  overflow: hidden;
  padding-left: clamp(0.4rem, 0.7vw, 0.8rem);
  color: #cbd5e1;
  font-size: min(clamp(0.7rem, 1.2vw, 1.2rem), 18cqh);
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
