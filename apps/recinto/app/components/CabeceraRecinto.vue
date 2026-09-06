<script setup lang="ts">
/**
 * Cabecera pública de tres zonas (WP-050, refinada por WP-054).
 *
 * Mantiene las tres zonas probadas en producción —fecha/hora a la izquierda,
 * información institucional al centro y estado técnico a la derecha— y condensa
 * el contexto central en un único renglón. Antes de WP-050 ocupaba tres
 * renglones (título, sesión + duración y autoridades), lo que robaba altura a
 * las bancas y dejaba un renglón vacío cuando no había autoridades cargadas.
 *
 * WP-054 introduce dos cambios de jerarquía decididos por HUMAN_GATE:
 *
 * 1. El centro contiene exactamente tres datos —institución, sesión y duración—
 *    con el *mismo tamaño tipográfico*. Antes el título era notoriamente mayor
 *    que la sesión y que la duración, lo que leía como un encabezado con
 *    apostillas en vez de como una sola frase institucional.
 * 2. Las autoridades se mudan al sector derecho, en dos renglones (Presidencia
 *    arriba, Secretaría abajo) junto al indicador de conexión. Al salir del
 *    centro, la columna central queda ocupada sólo por datos de longitud
 *    acotada y puede quedar *realmente centrada* respecto de la pantalla.
 *
 * Cómo se consigue el centrado real: la cabecera es una grilla de tres columnas
 * `1fr auto 1fr`. Dos columnas `1fr` iguales reparten el espacio libre por
 * partes iguales, de modo que la columna `auto` del medio cae exactamente sobre
 * el centro del viewport. Eso sólo se sostiene mientras ninguna columna lateral
 * necesite más ancho del que le tocó: por eso el sector derecho está acotado con
 * `max-width` y sus textos variables se recortan con elipsis en lugar de crecer.
 *
 * El reloj y la duración siguen siendo presentación local. La apertura formal y
 * el contexto de sesión continúan llegando exclusivamente en EstadoRecinto.
 */

import { computed, toRef } from 'vue'
import type { EstadoRecinto } from '@sis-leg/api-client'
import type { EstadoConexionRecinto } from '../composables/useEstadoRecinto'
import { useRelojLocal } from '../composables/useRelojLocal'
import { formatearFechaHoraLocal } from '../utils/tiempo'

const props = defineProps<{
  /** Snapshot público vigente, usado solo para el contexto central. */
  estado: EstadoRecinto | null
  estadoConexion: EstadoConexionRecinto
  desactualizado: boolean
}>()

const { ahora, tiempoSesion } = useRelojLocal(toRef(props, 'estado'))
const fechaHoraLocal = computed(() => formatearFechaHoraLocal(ahora.value))
const sesionAbierta = computed(() => props.estado?.estado_global === 'SESION_ABIERTA')
const contextoInstitucional = computed(
  () => props.estado?.sesion ?? props.estado?.preparacion ?? null,
)

const contextoCentral = computed(() => {
  if (sesionAbierta.value && props.estado?.sesion) {
    return `Sesión N.º ${props.estado.sesion.numero_sesion}`
  }
  if (props.estado?.estado_global === 'PREPARANDO') {
    return props.estado.preparacion?.numero_sesion
      ? `Preparando sesión N.º ${props.estado.preparacion.numero_sesion}`
      : 'Recinto en preparación'
  }
  return 'Recinto sin preparar'
})

/**
 * Autoridades como renglones independientes (WP-054).
 *
 * Antes las dos autoridades formaban un único texto unido por `·` porque
 * compartían una sola línea con el resto del centro. Ahora cada una ocupa su
 * propio renglón del sector derecho, así que se exponen por separado y el
 * componente sólo renderiza las que el backend ya proyectó: una preparación sin
 * Secretaría cargada no reserva un renglón vacío.
 */
const renglonesAutoridades = computed(() => {
  const contexto = contextoInstitucional.value
  if (!contexto) return [] as Array<{ rotulo: string; nombre: string }>
  const renglones: Array<{ rotulo: string; nombre: string }> = []
  if (contexto.presidencia) {
    renglones.push({ rotulo: 'Presidencia', nombre: contexto.presidencia })
  }
  if (contexto.secretaria_legislativa) {
    renglones.push({ rotulo: 'Secretaría', nombre: contexto.secretaria_legislativa })
  }
  return renglones
})

/**
 * Texto completo de las autoridades, usado sólo como `title`.
 * En pantalla cada renglón se recorta con elipsis; el emergente conserva la
 * lectura íntegra para el operador que se acerque al monitor.
 */
const textoAutoridades = computed(() =>
  renglonesAutoridades.value.map((renglon) => `${renglon.rotulo}: ${renglon.nombre}`).join(' · '),
)

const textoConexion = computed(() => {
  /*
    WP-070: aviso breve de vista desactualizada.

    Antes decía "Reconectando · vista desactualizada". Era el texto más largo que podía
    aparecer en el sector derecho, justo cuando la cabecera ya está bajo presión de ancho
    por las autoridades, y describía el diagnóstico técnico en vez del hecho que le
    importa al recinto: la pantalla dejó de recibir novedades. HUMAN_GATE fijó
    literalmente "(Sin conexion)" —con paréntesis, sin tilde— y prohibió corregirle la
    ortografía sin una decisión nueva. No se toca la lógica: `desactualizado` sigue
    llegando del composable de sincronización y sigue teniendo prioridad sobre el estado
    de conexión, porque una vista vieja es peor noticia que un socket reconectando.
  */
  if (props.desactualizado) return '(Sin conexion)'
  const textos: Record<EstadoConexionRecinto, string> = {
    INICIAL: 'Conectando',
    CONECTADO: 'En línea',
    RECONECTANDO: 'Reconectando',
    DESCONECTADO: 'Sin conexión',
  }
  return textos[props.estadoConexion]
})
</script>

<template>
  <header data-testid="cabecera-recinto" class="cabecera-recinto">
    <time data-testid="cabecera-fecha-hora" class="fecha-hora-local">
      {{ fechaHoraLocal }}
    </time>

    <!--
      Renglón único centrado: cada dato es un elemento en línea del mismo flex.
      Los separadores `·` los dibuja CSS (`::before`), no el texto, para que las
      pruebas y los lectores de pantalla sigan leyendo cada dato limpio.

      Desde WP-054 el centro contiene sólo institución, sesión y duración, y los
      tres comparten tamaño tipográfico (`dato-cabecera`). El `h1` conserva su
      rol semántico de encabezado; lo que cambia es su escala visual.
    -->
    <div data-testid="cabecera-contexto" class="marca-institucional">
      <h1 class="titulo-institucional dato-cabecera">Concejo Deliberante de Puerto Madryn</h1>
      <span data-testid="cabecera-sesion" class="dato-cabecera">{{ contextoCentral }}</span>
      <span
        v-if="tiempoSesion"
        data-testid="cabecera-tiempo-sesion"
        class="dato-cabecera tiempo-sesion"
      >
        {{ tiempoSesion }}
      </span>
    </div>

    <!--
      Sector derecho (WP-054): autoridades en dos renglones + estado técnico.

      Las autoridades quedan a la izquierda del indicador de conexión, que es el
      elemento de ancho más estable del bloque. Todo el sector está acotado por
      `max-width` para no invadir la columna central.
    -->
    <div class="sector-derecho">
      <div
        v-if="renglonesAutoridades.length > 0"
        data-testid="cabecera-autoridades"
        class="autoridades-cabecera"
        :title="textoAutoridades"
      >
        <span
          v-for="renglon in renglonesAutoridades"
          :key="renglon.rotulo"
          class="renglon-autoridad"
        >
          <span class="rotulo-autoridad">{{ renglon.rotulo }}:</span>
          {{ renglon.nombre }}
        </span>
      </div>

      <div
        data-testid="estado-conexion"
        class="estado-conexion"
        :class="`conexion-${estadoConexion.toLowerCase()}`"
        role="status"
      >
        <span class="punto-conexion" aria-hidden="true" />
        {{ textoConexion }}
      </div>
    </div>
  </header>
</template>

<style scoped>
/*
  Altura fija y baja, calibrada contra la `topbar` histórica medida en Chromium:
  59 px en 1920×1080 y 47 px en 1366×768. Al ser fija, ningún texto variable
  puede empujar hacia abajo la franja de votación ni el escenario de bancas.
*/
.cabecera-recinto {
  /*
    Cuerpo tipografico unico de la cabecera (WP-058).

    HUMAN_GATE pidio que la frase central llegue aproximadamente al doble del
    alto tipografico anterior y que la fecha/hora alcance ese mismo alto, todo
    sin tocar la altura fisica de la franja. Ambas cosas dependen del *ancho*
    disponible, no del alto: la cabecera es una grilla `1fr auto 1fr` y el
    bloque central solo puede crecer mientras las dos columnas laterales sigan
    entrando en el ancho que les queda.

    El presupuesto horizontal se midio en Chromium sobre la base de este WP:

    | resolucion | ancho util | centro por px de fuente | reloj por px de fuente |
    |------------|-----------|--------------------------|------------------------|
    | 1920x1080  | 1843,2 px | 36,95 px                 | 11,43 px               |
    | 1366x768   | 1295,8 px | 36,92 px                 | 11,47 px               |

    Como el reloj tambien crece (debe igualar el cuerpo central), el limite es
    `centro + 2 x reloj <= ancho util`, es decir ~59,9 px de ancho por cada px
    de cuerpo. Eso da un maximo real de ~30,8 px en 1920x1080 y de ~21,6 px en
    1366x768. La recta `1.7vw - 3.2px` deja 29,4 px y 20,0 px: cerca del doble
    en Full HD y en el maximo que realmente entra en una sola linea en
    1366x768, con margen para que las autoridades no colisionen.

    El piso conserva el cuerpo minimo anterior para pantallas angostas y el
    techo evita que en monitores muy anchos el renglon supere la altura fija.
  */
  --cuerpo-cabecera: clamp(0.78rem, calc(1.7vw - 3.2px), 2.25rem);
  /*
    Interlineado unico de las dos zonas tipograficas.

    1,15 em es el primer valor que contiene la caja de tinta completa del cuerpo
    ampliado. Se midio en Chromium barriendo el interlineado a las dos
    resoluciones canonicas, comparando `scrollHeight` contra `clientHeight` de
    cada renglon:

    | interlineado | 1920x1080     | 1366x768      |
    |--------------|---------------|---------------|
    | 1,05         | 32 vs 31 (mal)| 22 vs 21 (mal)|
    | 1,10         | 33 vs 32 (mal)| 23 vs 22 (mal)|
    | 1,15         | 34 vs 34 (ok) | 23 vs 23 (ok) |

    Con 1,05 —el valor previo a WP-058— la tinta quedaba 1 px fuera del renglon.
    No producia scroll visible, pero es exactamente el recorte silencioso que
    este WP debe descartar de forma medible.

    El renglon resultante mide 33,8 px en Full HD y 23,0 px en 1366x768, muy por
    debajo de la altura fija de la franja (59,4 px y 47 px), que no cambia.
  */
  --interlineado-cabecera: 1.15;
  height: clamp(47px, 5.5vh, 60px);
  display: grid;
  flex: 0 0 auto;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  align-items: center;
  gap: 1rem;
  padding: 0.35rem clamp(0.75rem, 1.4vw, 1.4rem);
  overflow: hidden;
  border-bottom: 1px solid rgba(148, 163, 184, 0.2);
  background: rgba(7, 17, 31, 0.94);
}

/*
  Fecha/hora: mismo cuerpo tipografico que el centro (WP-058), conservando
  fuente monoespaciada, color y posicion. El `line-height` se iguala al del
  centro para que ambos renglones ocupen exactamente el mismo alto de linea y
  la igualdad sea comprobable con estilos calculados, no solo a ojo.

  Ese valor comun es `--interlineado-cabecera`. Al duplicar el cuerpo dejo de
  ser suficiente el 1,05 anterior: la caja de tinta de estas tipografias mide
  algo mas de 1,05 em, asi que el renglon quedaba con `scrollHeight` un pixel
  mayor que su `clientHeight`. No producia scroll visible, pero era exactamente
  el tipo de recorte silencioso que este WP tiene que demostrar que no existe.
*/
.fecha-hora-local {
  justify-self: start;
  color: #cbd5e1;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: var(--cuerpo-cabecera);
  font-weight: 700;
  line-height: var(--interlineado-cabecera);
  white-space: nowrap;
}

/*
  `min-width: 0` es lo que permite que esta columna `auto` se achique en vez de
  aplastar el reloj o la conexión cuando el texto central es largo.
*/
.marca-institucional {
  min-width: 0;
  display: flex;
  align-items: baseline;
  justify-content: center;
  overflow: hidden;
  white-space: nowrap;
}

/* Separador tipográfico entre datos, idéntico al de producción. */
.marca-institucional > :not(:first-child)::before {
  margin: 0 0.42em;
  color: #475569;
  content: '·';
}

/*
  El título ya no compite en escala con el resto del centro (WP-054): comparte
  la clase `dato-cabecera`, así que sólo conserva aquí lo que lo distingue —el
  reseteo del margen del `h1`, el color institucional y el recorte por elipsis,
  porque es el único texto central que puede quedarse sin ancho.
*/
.titulo-institucional {
  min-width: 0;
  flex: 0 1 auto;
  margin: 0;
  overflow: hidden;
  color: #e2e8f0;
  text-overflow: ellipsis;
}

/*
  Tamaño tipográfico único del centro. Institución, sesión y duración lo
  comparten: HUMAN_GATE pidió explícitamente una sola jerarquía en esa zona.

  Desde WP-058 ese cuerpo sale de `--cuerpo-cabecera`, la misma variable que usa
  la fecha/hora: así "el mismo alto tipográfico visual" deja de ser una
  coincidencia entre dos `clamp` distintos y pasa a ser una única fuente.
*/
.dato-cabecera {
  flex: 0 0 auto;
  color: #7dd3fc;
  font-size: var(--cuerpo-cabecera);
  font-weight: 800;
  line-height: var(--interlineado-cabecera);
}

.tiempo-sesion {
  color: #e2e8f0;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

/*
  Sector derecho: autoridades y conexión (WP-054).

  `max-width` acotado es lo que protege el centrado real de la columna central:
  mientras este bloque no supere el ancho que le toca a su columna `1fr`, la
  columna `auto` del medio queda exactamente sobre el centro del viewport.
*/
.sector-derecho {
  min-width: 0;
  display: flex;
  align-items: center;
  justify-self: end;
  gap: 0.6rem;
  max-width: min(34vw, 30rem);
  overflow: hidden;
}

/*
  Dos renglones apilados, uno por autoridad. La altura resultante (dos líneas de
  ~0.72rem con `line-height` ajustado) sigue entrando en la altura fija de la
  cabecera, de modo que la franja de votación y las bancas no se mueven.
*/
.autoridades-cabecera {
  min-width: 0;
  display: flex;
  flex: 0 1 auto;
  flex-direction: column;
  gap: 0.1rem;
  overflow: hidden;
  text-align: right;
}

/* Cada autoridad se recorta por separado: nunca envuelve a una tercera línea. */
.renglon-autoridad {
  min-width: 0;
  overflow: hidden;
  color: #cbd5e1;
  font-size: clamp(0.58rem, 0.74vw, 0.74rem);
  font-weight: 700;
  line-height: 1.25;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rotulo-autoridad {
  color: #94a3b8;
  font-weight: 600;
}

.estado-conexion {
  display: inline-flex;
  align-items: center;
  flex: 0 0 auto;
  gap: 0.5rem;
  max-width: 45vw;
  padding: 0.28rem 0.6rem;
  overflow: hidden;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 999px;
  color: #cbd5e1;
  background: rgba(15, 23, 42, 0.7);
  font-size: clamp(0.64rem, 0.85vw, 0.76rem);
  font-weight: 700;
  white-space: nowrap;
}

.punto-conexion {
  width: 0.5rem;
  height: 0.5rem;
  flex: 0 0 auto;
  border-radius: 50%;
  background: #64748b;
}

.conexion-conectado .punto-conexion {
  background: #34d399;
  box-shadow: 0 0 0 4px rgba(52, 211, 153, 0.13);
}

.conexion-reconectando .punto-conexion,
.conexion-desconectado .punto-conexion {
  background: #fbbf24;
}

/*
  Adaptación defensiva fuera de las resoluciones canónicas: por debajo de
  720 px el renglón único no entra, así que la marca pasa a su propia fila y la
  cabecera deja de tener altura fija para no recortar información.
*/
@media (max-width: 720px) {
  .cabecera-recinto {
    height: auto;
    grid-template-columns: 1fr auto;
    row-gap: 0.25rem;
    padding-block: 0.4rem;
  }

  .marca-institucional {
    grid-column: 1 / -1;
    grid-row: 1;
  }

  .fecha-hora-local,
  .sector-derecho {
    grid-row: 2;
  }
}
</style>
