<script setup lang="ts">
/**
 * Tarjeta pública de una banca, sin DNI, dispositivo ni interacción mutante.
 *
 * WP-045 unifica su semántica con la tarjeta de Q3 de Moderación: la tarjeta
 * contiene solamente el bitmap real del concejal y, a lo sumo, una única
 * etiqueta textual de estado. Nombre, apellido, bloque y número de banca ya
 * forman parte de la propia imagen institucional, de modo que repetirlos como
 * texto duplicaba información y obligaba a la tarjeta a crecer según el largo
 * del nombre. Esos datos siguen disponibles en el DTO y en `aria-label`.
 *
 * La decisión de qué estado mostrar NO vive acá: la toma la función pura
 * compartida `calcularPresentacionBanca`, así Q3 y Recinto no pueden divergir.
 */

import { computed, ref, watch } from 'vue'
import type { ConcejalPublico } from '@sis-leg/api-client'
import { calcularPresentacionBanca, estilosBanca } from '@sis-leg/frontend-shared'
import { resolverRutaAsset } from '../utils/rutas'

const props = defineProps<{
  concejal: ConcejalPublico
  /** Derivado de `palabra.orador.banca`; nunca se conserva localmente. */
  esOrador: boolean
  /** `estado_recepcion` de la votación relevante; `null` si no hay votación. */
  estadoRecepcion: string | null
  /** La banca figura en `bancas_voto_emitido`: ya votó, sin revelar el sentido. */
  votoEmitido: boolean
  /** Sentido final del voto; el backend solo lo proyecta tras el cierre. */
  valorVotoFinal: string | null
}>()

const imagenFallida = ref(false)
const urlImagen = computed(() => resolverRutaAsset(props.concejal.ruta_imagen))
const claveImagen = computed(
  () =>
    `${props.concejal.nombre}|${props.concejal.apellido}|${props.concejal.banca}|${props.concejal.ruta_imagen}`,
)
const iniciales = computed(() =>
  `${props.concejal.nombre.charAt(0)}${props.concejal.apellido.charAt(0)}`.toUpperCase(),
)

/**
 * Estado visual único de la banca.
 *
 * `calcularPresentacionBanca` descarta internamente cualquier sentido de voto
 * mientras `estadoRecepcion` sea `EN_CURSO`, por lo que el secreto no depende de
 * que este componente recuerde filtrarlo.
 */
const presentacion = computed(() =>
  calcularPresentacionBanca({
    presente: props.concejal.presente,
    testActivo: props.concejal.test_activo,
    esOrador: props.esOrador,
    estadoRecepcion: props.estadoRecepcion,
    votoEmitido: props.votoEmitido,
    valorVotoFinal: props.valorVotoFinal,
  }),
)

const estilos = computed(() => estilosBanca(presentacion.value))

/**
 * Descripción accesible completa.
 *
 * Conserva la identidad y la presencia institucional que ya no se dibujan como
 * texto, y agrega el estado principal solo cuando aporta algo distinto de la
 * presencia (evita leer "ausente, ausente").
 */
const descripcionAccesible = computed(() => {
  const presencia = props.concejal.presente ? 'presente' : 'ausente'
  const estado = presentacion.value.estado
  const detalle =
    estado === 'NORMAL' || estado === 'AUSENTE' ? '' : `, ${presentacion.value.etiquetaAccesible}`
  return `Banca ${props.concejal.banca}, ${props.concejal.nombre} ${props.concejal.apellido}, ${presencia}${detalle}`
})

// Una baseline puede cambiar ruta o persona aun reutilizando la misma banca.
// La clave completa evita conservar un error local que ya no pertenece al snapshot.
watch(claveImagen, () => {
  imagenFallida.value = false
})
</script>

<template>
  <article
    data-testid="banca-publica"
    :data-banca="concejal.banca"
    :data-presente="concejal.presente"
    :data-orador="esOrador"
    :data-estado-banca="presentacion.estado"
    :data-halo-test="presentacion.haloTest"
    :data-halo-palabra="presentacion.haloPalabra"
    class="banca-publica"
    :class="{ 'banca-con-halo': presentacion.haloTest || presentacion.haloPalabra }"
    :style="estilos"
    :aria-label="descripcionAccesible"
  >
    <!--
      Área principal: el bitmap se muestra completo (`contain`) sobre fondo
      blanco para no recortar nombres ni logos incluidos dentro de la imagen.
    -->
    <div class="area-imagen">
      <img
        v-if="urlImagen && !imagenFallida"
        data-testid="imagen-concejal"
        :data-ruta-imagen="concejal.ruta_imagen"
        :src="urlImagen"
        :alt="`${concejal.nombre} ${concejal.apellido}`"
        class="imagen-banca"
        @error="imagenFallida = true"
      />
      <!--
        Fallback: solo aparece cuando el bitmap no cargó. No duplica identidad
        visible porque en ese momento no hay bitmap con el que duplicarse.
      -->
      <div v-else data-testid="imagen-fallback" class="imagen-fallback" aria-hidden="true">
        {{ iniciales || '?' }}
      </div>
    </div>

    <!--
      Franja de estado: se reserva siempre, tenga o no texto, para que ninguna
      tarjeta cambie de tamaño según su estado. Contiene como máximo una etiqueta.
    -->
    <div class="franja-estado">
      <span v-if="presentacion.etiqueta" data-testid="etiqueta-banca" class="etiqueta-banca">
        {{ presentacion.etiqueta }}
      </span>
    </div>
  </article>
</template>

<style scoped>
.banca-publica {
  position: relative;
  min-width: 0;
  min-height: 0;
  height: 100%;
  display: grid;
  grid-template-rows: minmax(0, 1fr) auto;
  gap: 0.3rem;
  padding: clamp(0.3rem, 0.55vw, 0.5rem);
  overflow: hidden;
  border: 2px solid var(--borde-banca);
  border-radius: 14px;
  background: var(--fondo-banca);
  box-shadow: 0 10px 22px rgba(2, 8, 23, 0.28);
}

/* Señal secundaria no textual de test o palabra subordinados a otro estado. */
.banca-con-halo {
  box-shadow:
    0 0 0 3px var(--halo-banca) inset,
    0 10px 22px rgba(2, 8, 23, 0.28);
}

/*
  Contenedor de la foto.

  Es `position: relative` a propósito. Antes era una grilla con
  `place-items: center` y el bitmap pedía `height: 100%`: ese porcentaje se
  resolvía contra una fila implícita `auto`, cuyo alto dependía a su vez del
  propio bitmap. La dependencia circular hacía que el navegador tratara la
  altura como `auto`, la imagen tomaba su relación de aspecto natural a partir
  del ancho y, cuando la tarjeta era más alta que ancha, sobresalía por arriba
  y por abajo: `overflow: hidden` la recortaba en silencio.

  Con un contenedor posicionado y la imagen en `inset: 0` ya no hay porcentaje
  que resolver: la caja del bitmap es exactamente la caja interior de esta
  área, y `object-fit: contain` puede hacer su trabajo sin recortar nada.
*/
.area-imagen {
  position: relative;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  border-radius: 10px;
  /* Fondo blanco fijo: el bitmap institucional se diseñó sobre blanco. */
  background: #ffffff;
}

.imagen-banca,
.imagen-fallback {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  /* `contain` preserva la imagen completa, incluidos nombre y logos internos. */
  object-fit: contain;
}

/*
  Recorte del marco inerte del bitmap institucional (WP-058).

  HUMAN_GATE pidió que la identidad se vea con mayor escala. Nombre, apellido y
  bloque viven *dentro* del bitmap, así que no se pueden agrandar por CSS ni
  duplicar como texto (eso último está explícitamente fuera de alcance). Lo
  único que sí puede recuperarse es el margen que el propio archivo desperdicia.

  Los doce archivos miden 300x300 px y se midió su contenido píxel a píxel,
  contando como inerte únicamente lo totalmente transparente o blanco puro. Con
  ese criterio estricto —que incluye el antialias casi invisible del borde de
  las letras— el marco garantizado sin contenido en *todos* ellos es:

  | borde     | margen inerte mínimo entre los 12 archivos |
  |-----------|--------------------------------------------|
  | superior  | 12 px                                      |
  | inferior  | 3 px                                       |
  | izquierdo | 33 px                                      |
  | derecho   | 34 px                                      |

  `object-view-box` recorta exactamente ese marco —12/33/3/33, todos menores o
  iguales al mínimo medido— y `object-fit: contain` sigue aplicándose después,
  ahora sobre una caja de 234x285 px en lugar de 300x300. Como la tarjeta es más
  ancha que alta, el ajuste lo decide la altura: la identidad pasa a dibujarse
  300/285 = 1,053 veces más grande, es decir +5,3 % lineal y +11 % de superficie,
  sin recortar ni un píxel de nombre, foto o logo.

  La regresión `assets_bancas_wp058.test.ts` vuelve a medir los doce archivos y
  falla si un asset nuevo tuviera contenido dentro de ese marco.

  Queda escrito acá con toda claridad: esta ganancia es la máxima posible sin
  recortar contenido. La tarjeta pública es más ancha que alta y el contenido
  del bitmap es más alto que ancho, así que `contain` siempre ajusta por altura;
  cualquier aumento mayor exigiría recortar foto, nombre o logo. Ese límite se
  elevó al ORCHESTRATOR junto con esta implementación.

  Se declara bajo `@supports` a propósito: donde el motor no conozca la
  propiedad, la tarjeta vuelve exactamente al encuadre anterior en lugar de
  quedar rota. La ganancia es una mejora progresiva, nunca un requisito de
  render.
*/
@supports (object-view-box: inset(0)) {
  .imagen-banca {
    object-view-box: inset(12px 33px 3px 33px);
  }
}

.banca-publica[data-estado-banca='AUSENTE'] .imagen-banca {
  filter: grayscale(1);
  opacity: 0.72;
}

.imagen-fallback {
  display: grid;
  place-items: center;
  color: #334155;
  font-size: clamp(1rem, 2vw, 1.6rem);
  font-weight: 900;
}

.franja-estado {
  /* Altura reservada siempre: la geometría no depende del estado ni del texto. */
  min-height: clamp(0.95rem, 1.9vh, 1.35rem);
  display: grid;
  place-items: center;
  min-width: 0;
}

.etiqueta-banca {
  max-width: 100%;
  padding: 0.1rem 0.4rem;
  overflow: hidden;
  border-radius: 999px;
  color: var(--texto-etiqueta-banca);
  background: var(--fondo-etiqueta-banca);
  font-size: clamp(0.5rem, 0.72vw, 0.7rem);
  font-weight: 900;
  letter-spacing: 0.03em;
  text-overflow: ellipsis;
  text-transform: uppercase;
  /* Un texto largo nunca puede empujar la geometría de la tarjeta. */
  white-space: nowrap;
}
</style>
