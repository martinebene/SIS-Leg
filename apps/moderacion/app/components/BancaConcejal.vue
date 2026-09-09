<script setup lang="ts">
/**
 * Tarjeta compacta de una banca para el operador de Moderación (Q3).
 *
 * WP-045 unifica su semántica con la tarjeta pública del Recinto: la tarjeta
 * muestra únicamente el bitmap real del concejal y, a lo sumo, una etiqueta
 * textual de estado. Nombre, apellido, bloque, número de banca y dispositivo ya
 * no se dibujan como texto —el bitmap institucional los contiene— pero siguen
 * disponibles en el DTO y en `aria-label` para accesibilidad y pruebas.
 *
 * Q3 es una vista compacta de la MISMA semántica pública: el estado principal,
 * la etiqueta y la familia cromática los decide la función pura compartida
 * `calcularPresentacionBanca`, de modo que ambas superficies no puedan divergir.
 *
 * El componente representa el snapshot recibido: no emite comandos ni modifica
 * presencia o test.
 *
 * WP-083 agrega una única diferencia visual respecto del Recinto: en Q3 la banca
 * `NORMAL` pinta su borde transparente. WP-090 completa esa corrección evitando que el
 * fondo blanco se pinte debajo de ese borde. Ambas decisiones están explicadas junto a
 * la regla CSS, más abajo.
 */

import { computed, ref, watch } from 'vue'
import type { ConcejalModeracion } from '@sis-leg/api-client'
import { calcularPresentacionBanca, estilosBanca } from '@sis-leg/frontend-shared'
import { resolverRutaAsset } from '../utils/rutas'

const props = defineProps<{
  /** Datos completos de la banca y concejal proyectados por el backend. */
  concejal: ConcejalModeracion
  /** Señal derivada de `palabra.orador.banca`; nunca se conserva localmente. */
  esOrador?: boolean
  /** `estado_recepcion` de la votación relevante; `null` si no hay votación. */
  estadoRecepcion?: string | null
  /** La banca figura en `bancas_voto_emitido`: ya votó, sin revelar el sentido. */
  votoEmitido?: boolean
  /**
   * Sentido final del voto de esta banca.
   *
   * El padre solo debe pasarlo cuando la votación dejó de estar `EN_CURSO`. Aun
   * así, la función compartida vuelve a descartarlo si la recepción sigue
   * abierta: el secreto no queda a merced de un único llamador.
   */
  valorVotoFinal?: string | null
}>()

const errorCargaImagen = ref(false)
const urlImagen = computed(() => resolverRutaAsset(props.concejal.ruta_imagen))

/**
 * Identifica la fotografía que corresponde a la baseline vigente.
 *
 * No alcanza con observar solamente la URL: una preparación nueva puede cambiar la
 * persona de una banca y reutilizar una ruta. La clave completa permite olvidar un
 * error local anterior cuando el snapshot cambia la identidad o la imagen.
 */
const claveImagen = computed(
  () =>
    `${props.concejal.dni}|${props.concejal.nombre}|${props.concejal.apellido}|${props.concejal.ruta_imagen}`,
)

const iniciales = computed(() => {
  const inicialNombre = props.concejal.nombre?.charAt(0) || ''
  const inicialApellido = props.concejal.apellido?.charAt(0) || ''
  return `${inicialNombre}${inicialApellido}`.toUpperCase() || '?'
})

/** Estado visual único, calculado con la misma regla que la pantalla pública. */
const presentacion = computed(() =>
  calcularPresentacionBanca({
    presente: props.concejal.presente,
    testActivo: props.concejal.test_activo,
    esOrador: props.esOrador ?? false,
    estadoRecepcion: props.estadoRecepcion ?? null,
    votoEmitido: props.votoEmitido ?? false,
    valorVotoFinal: props.valorVotoFinal ?? null,
  }),
)

const estilos = computed(() => estilosBanca(presentacion.value))

/** Conserva para lectores de pantalla la identidad que ya no se dibuja. */
const descripcionAccesible = computed(() => {
  const presencia = props.concejal.presente ? 'presente' : 'ausente'
  const estado = presentacion.value.estado
  const detalle =
    estado === 'NORMAL' || estado === 'AUSENTE' ? '' : `, ${presentacion.value.etiquetaAccesible}`
  return `Banca ${props.concejal.banca}, ${props.concejal.nombre} ${props.concejal.apellido}, ${presencia}${detalle}`
})

function manejarErrorImagen(): void {
  errorCargaImagen.value = true
}

watch(claveImagen, () => {
  errorCargaImagen.value = false
})
</script>

<template>
  <article
    data-testid="banca-concejal"
    :data-banca="concejal.banca"
    :data-presente="concejal.presente"
    :data-orador="esOrador"
    :data-estado-banca="presentacion.estado"
    :data-halo-test="presentacion.haloTest"
    :data-halo-palabra="presentacion.haloPalabra"
    class="banca-concejal-moderacion"
    :class="{ 'banca-con-halo': presentacion.haloTest || presentacion.haloPalabra }"
    :style="estilos"
    :aria-label="descripcionAccesible"
  >
    <!-- Área principal: bitmap completo sobre blanco, sin recortes. -->
    <div class="area-imagen">
      <img
        v-if="!errorCargaImagen && urlImagen"
        data-testid="imagen-concejal"
        :data-ruta-imagen="concejal.ruta_imagen"
        :src="urlImagen"
        :alt="`${concejal.nombre} ${concejal.apellido}`"
        class="imagen-banca"
        @error="manejarErrorImagen"
      />
      <!-- Fallback: solo cuando el bitmap falla; no duplica identidad visible. -->
      <div
        v-else
        data-testid="fallback-imagen"
        class="imagen-fallback"
        :title="`${concejal.nombre} ${concejal.apellido}`"
      >
        {{ iniciales }}
      </div>
    </div>

    <!-- Franja siempre reservada: el estado nunca cambia el tamaño de la tarjeta. -->
    <div class="franja-estado">
      <span v-if="presentacion.etiqueta" data-testid="etiqueta-banca" class="etiqueta-banca">
        {{ presentacion.etiqueta }}
      </span>
    </div>
  </article>
</template>

<style scoped>
.banca-concejal-moderacion {
  position: relative;
  min-width: 0;
  min-height: 0;
  height: 100%;
  display: grid;
  grid-template-rows: minmax(0, 1fr) auto;
  gap: 0.15rem;
  padding: 0.2rem;
  overflow: hidden;
  border: 2px solid var(--borde-banca);
  border-radius: 8px;
  background: var(--fondo-banca);
  user-select: none;
}

/*
  Borde realmente invisible de la banca presente sin novedad (WP-083 y WP-090).

  La tarjeta NORMAL es blanca sobre el fondo oscuro de Q3, y el bitmap institucional
  también está compuesto sobre blanco. El borde `#c7d2dd` de la familia BLANCA quedaba
  entonces como una línea gris flotando **dentro** del blanco, y en la grilla completa se
  leía como un recuadro superpuesto a la imagen. La revisión de quinta ronda pidió que la
  banca sin novedad no dibuje ese recuadro.

  WP-083 volvió transparente el color del borde, pero el fondo blanco de la tarjeta se
  seguía pintando por debajo de esos 2 px porque el valor inicial de `background-clip` es
  `border-box`. Por eso el contorno continuaba leyéndose blanco contra el fondo oscuro.

  La corrección completa sigue siendo local a NORMAL y a Moderación:

  - se mantiene `border-width: 2px`, así que la caja mide exactamente lo mismo que antes y
    ni la imagen ni la franja de estado se mueven o escalan un píxel;
  - se pinta `transparent` en lugar de tocar `--borde-banca`, porque esa custom property
    sale de la paleta compartida `PALETA_BANCAS` que también consume la Pantalla del
    Recinto: cambiarla ahí habría cambiado el Recinto, que este WP debe dejar intacto;
  - `background-clip: padding-box` hace que el fondo empiece después del borde, de modo
    que el área transparente revela el fondo oscuro de Q3 sin cambiar caja ni contenido;
  - el selector es exactamente `NORMAL`, de modo que AUSENTE, PALABRA, TEST, VOTO_EMITIDO
    y los tres estados de resultado conservan su borde tal como está hoy.

  NORMAL es además el único estado que llega acá sin etiqueta y sin halo: `TEST` tampoco
  dibuja etiqueta pero es un estado propio con su propio color, y los halos sólo existen
  cuando test o palabra quedaron subordinados a un estado de mayor prioridad, cosa que
  por construcción nunca ocurre en NORMAL.
*/
.banca-concejal-moderacion[data-estado-banca='NORMAL'] {
  border-color: transparent;
  background-clip: padding-box;
}

/* Señal secundaria no textual de test o palabra subordinados a otro estado. */
.banca-con-halo {
  box-shadow: 0 0 0 2px var(--halo-banca) inset;
}

.area-imagen {
  min-width: 0;
  min-height: 0;
  display: grid;
  place-items: center;
  overflow: hidden;
  border-radius: 5px;
  /* Fondo blanco fijo: el bitmap institucional se diseñó sobre blanco. */
  background: #ffffff;
}

.imagen-banca,
.imagen-fallback {
  width: 100%;
  height: 100%;
  /* `contain` preserva la imagen completa, incluidos nombre y logos internos. */
  object-fit: contain;
}

.banca-concejal-moderacion[data-estado-banca='AUSENTE'] .imagen-banca {
  filter: grayscale(1);
  opacity: 0.72;
}

.imagen-fallback {
  display: grid;
  place-items: center;
  color: #334155;
  font-size: 0.7rem;
  font-weight: 900;
}

.franja-estado {
  /* Altura reservada siempre: la geometría no depende del estado ni del texto. */
  min-height: 0.85rem;
  display: grid;
  place-items: center;
  min-width: 0;
}

.etiqueta-banca {
  max-width: 100%;
  padding: 0 0.25rem;
  overflow: hidden;
  border-radius: 999px;
  color: var(--texto-etiqueta-banca);
  background: var(--fondo-etiqueta-banca);
  font-size: 0.44rem;
  font-weight: 900;
  letter-spacing: 0.02em;
  line-height: 0.85rem;
  text-overflow: ellipsis;
  text-transform: uppercase;
  /* Un texto largo nunca puede empujar la geometría de la tarjeta. */
  white-space: nowrap;
}
</style>
