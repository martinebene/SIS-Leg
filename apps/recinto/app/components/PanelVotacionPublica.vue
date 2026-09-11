<script setup lang="ts">
/**
 * Presenta el DTO público sin recalcular mayoría, conteos ni resultado.
 *
 * Desde WP-099 la redacción de los tres renglones no se escribe acá: la aporta
 * `usePresentacionVotacionPublica`, en `@sis-leg/frontend-shared`. El motivo es que el
 * Zócalo para OBS muestra el mismo contenido con otra geometría, y dos copias de las
 * mismas etiquetas podrían corregirse en una sola pantalla. Este componente conserva
 * exactamente su marcado y su hoja de estilos: lo único que cambió es de dónde salen los
 * textos.
 */

import { computed, toRef } from 'vue'
import type { VotacionPublica } from '@sis-leg/api-client'
import { etiquetaSentidoVoto, usePresentacionVotacionPublica } from '@sis-leg/frontend-shared'

const props = defineProps<{ votacion: VotacionPublica | null }>()

const {
  resumen: resumenVotacion,
  estado: estadoPrincipal,
  claseEstado,
  conteosVisibles,
  esperaDesempate,
  votoPresidencial,
} = usePresentacionVotacionPublica(toRef(props, 'votacion'))

// El tema se sigue leyendo directo del DTO porque la plantilla necesita distinguir el
// valor ausente para el `title` del tooltip, que muestra el texto completo al pasar el
// cursor cuando el renglón quedó recortado con elipsis.
const tema = computed(() => props.votacion?.tema ?? null)
</script>

<template>
  <article data-testid="votacion-publica" class="panel-votacion" :class="`estado-${claseEstado}`">
    <div class="renglon-votacion">
      <strong>Votación</strong>
      <span data-testid="resumen-votacion" :title="resumenVotacion">{{ resumenVotacion }}</span>
    </div>

    <div class="renglon-votacion">
      <strong>Tema</strong>
      <span data-testid="tema-votacion" class="tema-votacion" :title="tema ?? '—'">
        {{ tema ?? '—' }}
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
      <span v-if="esperaDesempate" data-testid="espera-desempate" class="detalle-estado">
        En espera del desempate de Presidencia
      </span>
      <span
        v-if="votoPresidencial"
        data-testid="voto-presidencial"
        class="detalle-estado detalle-presidencial"
      >
        Desempate: {{ votoPresidencial.presidencia }} ·
        {{ etiquetaSentidoVoto(votoPresidencial.sentido) }}
      </span>
    </div>
  </article>
</template>

<style scoped>
/*
  Alto del contenedor congelado, tipografía al doble (WP-097).

  El pedido humano fue duplicar el cuerpo de `Votación`, `Tema` y `Estado` **sin** que la
  franja crezca. La franja mide 118 px a 1280×720 y 172 px a 1920×1080: son las filas que
  `PantallaRecinto` reserva, y este panel las llena al 100 %. Con tres renglones, cada uno
  dispone de aproximadamente un tercio de ese alto.

  Duplicar la tipografía dentro de un alto fijo obliga a devolver al texto el espacio que
  antes gastaban los rellenos verticales, así que:

  - el relleno vertical del panel desaparece y el interlineado baja a 1,2, que es el mínimo
    con el que las mayúsculas acentuadas —`VOTACIÓN`, `SIN VOTACIÓN`— siguen dibujando la
    tilde completa dentro de su renglón;
  - la píldora del estado pierde su relleno vertical para no ser el renglón que desborde;
  - además del `clamp` por viewport, cada cuerpo lleva un **techo geométrico** expresado en
    `cqh`, es decir en porcentaje del alto real de la franja. Ese techo es lo que garantiza
    que los tres renglones entren siempre: pase lo que pase con el viewport, tres renglones
    de `27,2 cqh × 1,2` ocupan como máximo el 98 % del alto disponible.

  Para que `cqh` signifique «alto de la franja», el propio panel se declara contenedor de
  tamaño. Puede hacerlo sin riesgo de bucle porque su alto no lo decide su contenido: lo fija
  la fila de grilla de `PantallaRecinto`, que este WP no toca.

  Medición real en Chromium sobre el commit base y sobre este cambio, con raíz de 16 px:

  | resolución | franja | antes    | ahora    | factor |
  |------------|--------|----------|----------|--------|
  | 1280×720   | 118 px | 16,00 px | 32,00 px | 2,00   |
  | 1366×768   | 123 px | 17,08 px | 33,43 px | 1,96   |
  | 1920×1080  | 172 px | 18,56 px | 37,12 px | 2,00   |
*/
.panel-votacion {
  min-width: 0;
  min-height: 0;
  height: 100%;
  display: grid;
  grid-template-rows: repeat(3, minmax(0, 1fr));
  margin: 0;
  padding: 0 clamp(0.65rem, 1vw, 1rem);
  overflow: hidden;
  border: 1px solid rgba(56, 189, 248, 0.36);
  border-radius: 14px;
  background: linear-gradient(135deg, rgba(8, 47, 73, 0.82), rgba(15, 23, 42, 0.92));
  container-type: size;
}

/*
  La columna del rótulo también se duplica: con `VOTACIÓN` al doble de cuerpo, el ancho
  anterior (8,5vw) recortaba la propia palabra. El ancho nuevo se calibró midiendo el
  rótulo más largo en las tres resoluciones objetivo y sigue siendo una fracción del
  viewport, no un valor fijo en píxeles.
*/
.renglon-votacion {
  min-width: 0;
  min-height: 0;
  display: grid;
  grid-template-columns: clamp(9.4rem, 14.6vw, 13.6rem) minmax(0, 1fr);
  align-items: center;
  gap: clamp(0.45rem, 0.8vw, 0.8rem);
  overflow: hidden;
  border-bottom: 1px solid rgba(148, 163, 184, 0.12);
}

.renglon-votacion:last-child {
  border-bottom: 0;
}

/*
  Rótulos y valores multiplican por 2 los tres términos de sus `clamp` anteriores
  —`0,72rem / 1,2vw / 1,12rem` y `0,76rem / 1,25vw / 1,16rem`—. Multiplicar los tres por el
  mismo factor, en vez de elegir números nuevos a ojo, hace que el aumento sea exactamente
  del doble en cualquier resolución, gane el término que gane: es la misma técnica que
  WP-064 usó para el nombre de la cola de palabra.
*/
.renglon-votacion > strong {
  overflow: hidden;
  color: #7dd3fc;
  font-size: min(clamp(1.44rem, 2.4vw, 2.24rem), 26.1cqh);
  line-height: 1.2;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  white-space: nowrap;
}

.renglon-votacion > span {
  min-width: 0;
  overflow: hidden;
  color: #e2e8f0;
  font-size: min(clamp(1.52rem, 2.5vw, 2.32rem), 27.2cqh);
  font-weight: 750;
  line-height: 1.2;
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
  grid-template-columns: clamp(9.4rem, 14.6vw, 13.6rem) auto minmax(0, 1fr) auto;
}

.estado-votacion {
  /* Sin relleno vertical: la píldora es el elemento más alto de los tres renglones y no
     puede ser la que haga desbordar la franja de alto congelado. El aire visual se lo da
     el propio interlineado de 1,2. */
  padding: 0 0.58rem;
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
    grid-template-columns: clamp(9.4rem, 14.6vw, 13.6rem) auto minmax(0, 1fr);
  }

  .detalle-presidencial {
    display: none;
  }
}
</style>
