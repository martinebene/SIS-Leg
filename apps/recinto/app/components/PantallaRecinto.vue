<script setup lang="ts">
/**
 * Vista pública compacta; representa sus props y nunca emite comandos.
 *
 * WP-056 suma el plano técnico sin alterar la geometría validada en WP-054:
 *
 * - la columna derecha se divide verticalmente en 1/5 para el indicador de transmisión
 *   y 4/5 para los pedidos de palabra. Las dos porciones son fracciones de grilla, no
 *   alturas en píxeles, así que la proporción se conserva en cualquier resolución;
 * - un aviso dirigido al Recinto reemplaza **toda** la franja superior de
 *   votación/tema/estado, sin tocar la cabecera, las bancas ni la columna derecha;
 * - al vencer o cancelarse el aviso, el backend republica y la franja original vuelve
 *   sola. La pantalla no guarda ni restaura nada por su cuenta.
 */

import { computed, toRefs } from 'vue'
import type { EstadoRecinto } from '@sis-leg/api-client'
import { usePresentacionTecnica, useSonidosRecinto } from '@sis-leg/frontend-shared'
import AvisoSuperficie from '@sis-leg/frontend-shared/componentes/AvisoSuperficie.vue'
import IndicadorCargaInicial from '@sis-leg/frontend-shared/componentes/IndicadorCargaInicial.vue'
import type { EstadoConexionRecinto } from '../composables/useEstadoRecinto'
import { usePresentacionVotacion } from '../composables/usePresentacionVotacion'
import { resolverRutaAsset } from '../utils/rutas'
import BloqueTransmisionPublico from './BloqueTransmisionPublico.vue'
import CabeceraRecinto from './CabeceraRecinto.vue'
import GrillaBancas from './GrillaBancas.vue'
import IndicadorQuorumPublico from './IndicadorQuorumPublico.vue'
import PanelPalabraPublico from './PanelPalabraPublico.vue'
import PanelVotacionPublica from './PanelVotacionPublica.vue'

const props = defineProps<{
  estado: EstadoRecinto | null
  estadoConexion: EstadoConexionRecinto
  desactualizado: boolean
}>()
const { estado, estadoConexion, desactualizado } = toRefs(props)

/**
 * URL pública del logo institucional usado en `SIN_PREPARAR` (WP-062).
 *
 * Se resuelve con el mismo helper que las fotos de banca porque el problema es idéntico:
 * el archivo vive en `public/` y la aplicación se sirve bajo el prefijo `/recinto/`, así
 * que la ruta final depende del `baseURL` configurado y no puede escribirse a mano.
 */
const urlLogoInstitucional = resolverRutaAsset('assets/marca/sisleg-logo.png')

const sesionAbierta = computed(() => estado.value?.estado_global === 'SESION_ABIERTA')
const bancaOrador = computed(() => estado.value?.palabra?.orador?.banca ?? null)
const { votacion: votacionPresentada, segundosCuentaRegresiva } = usePresentacionVotacion(estado)
const estadoRecepcionVotacion = computed(() => votacionPresentada.value?.estado_recepcion ?? null)
/**
 * Participación sin sentido (WP-045).
 *
 * El backend garantiza que solo viene poblada mientras la recepción está
 * `EN_CURSO`; la pantalla se limita a transportarla hasta cada banca.
 */
const bancasVotoEmitido = computed(() => votacionPresentada.value?.bancas_voto_emitido ?? null)

/**
 * Total de bancas del padrón activo, denominador del indicador de quórum.
 *
 * Sale del propio snapshot público: `concejales` ya contiene exactamente las
 * bancas de la preparación vigente. No hizo falta agregar un campo al contrato
 * ni consultar otra fuente para mostrar `presentes/total` (WP-054).
 */
const totalConcejales = computed(() => estado.value?.concejales.length ?? 0)
const votosIndividualesVisibles = computed(() => {
  const votacion = votacionPresentada.value
  if (votacion?.estado_recepcion === 'EN_CURSO') return null
  return votacion?.votos_individuales ?? null
})

/**
 * Porción técnica del snapshot público.
 *
 * `EstadoRecinto.tecnico.aviso` sólo puede traer un aviso dirigido a RECINTO o a AMBOS:
 * el backend separa las ranuras por destino, de modo que un aviso publicado únicamente
 * hacia Moderación jamás viaja en este payload. La pantalla pública no vuelve a filtrar.
 */
const transmision = computed(() => estado.value?.tecnico?.transmision ?? null)
const avisoTecnico = computed(() => estado.value?.tecnico?.aviso ?? null)

const { segundosTransmision } = usePresentacionTecnica(
  computed(() => ({
    transmision: transmision.value,
    // El Recinto no cronometra el aviso: su desaparición la publica el backend. Pasar la
    // lista vacía mantiene el reloj local apagado cuando no hay transmisión en cuenta.
    avisos: [],
    generadoEn: estado.value?.generado_en ?? null,
  })),
)

/**
 * Sonidos del Recinto (WP-066; motor compartido desde WP-071).
 *
 * El motor vive acá y no en `app.vue` por una razón concreta: necesita los dos insumos que
 * esta pantalla ya tiene juntos. Uno es el estado público con su conexión, que separa un
 * hecho nuevo de una baseline que no debe reproducir historia. El otro es
 * `segundosTransmision`, el mismo número que el público ve bajar, que es el que debe
 * acompañar el tic de la cuenta regresiva sin pedirle al backend una revisión por segundo.
 *
 * Desde WP-071 el composable es el mismo que usa el puesto de Apoyo Técnico, que debe
 * sonar igual para poder alimentar la amplificación del salón. El comportamiento de esta
 * pantalla no cambia: sigue entregando sus mismos insumos y su propio resolutor de rutas,
 * que arma la URL contra el `baseURL` del Recinto.
 *
 * No agrega ningún elemento visible: no hay botón de activación ni control de volumen. Si
 * el navegador rechaza el autoplay, la pantalla sigue funcionando igual y el problema se
 * resuelve en la configuración del equipo del recinto, documentada en
 * `docs/13-despliegue-y-operacion.md`.
 */
useSonidosRecinto({
  estado,
  estadoConexion,
  segundosCuentaRegresiva: segundosTransmision,
  resolverUrl: resolverRutaAsset,
})
</script>

<template>
  <div class="aplicacion-recinto">
    <!--
      Barra indeterminada de carga inicial (WP-061). El Recinto ya mostraba «Conectando con
      el recinto», pero ese estado sólo existe **después** de que Vue montó: la barra
      continúa el indicador previo a la hidratación y unifica la señal con las otras tres
      pantallas. Posicionada `fixed`, no ocupa lugar en la columna ni genera scroll.
    -->
    <IndicadorCargaInicial v-if="!estado" />

    <CabeceraRecinto
      :estado="estado"
      :estado-conexion="estadoConexion"
      :desactualizado="desactualizado"
    />

    <main v-if="!estado" class="estado-inicial" data-testid="estado-inicial">
      <div class="pulso-carga" aria-hidden="true" />
      <h2>
        {{
          estadoConexion === 'DESCONECTADO' ? 'Recinto sin conexión' : 'Conectando con el recinto'
        }}
      </h2>
      <p>Esperando el primer estado público confirmado.</p>
    </main>

    <main
      v-else-if="estado.estado_global === 'SIN_PREPARAR'"
      class="estado-sin-preparar"
      data-testid="estado-sin-preparar"
    >
      <!--
        Identidad institucional en reposo (WP-062).

        HUMAN_GATE decidió que el estado público sin sesión muestre el logo completo de
        SIS-Leg. Reemplaza al monograma «CD» dibujado con CSS que ocupaba este lugar: era un
        marcador provisional, no una marca aprobada. Donde está el logo no se repite
        «SIS-Leg» como texto, así que el `alt` describe la marca para lectores de pantalla y
        los dos renglones de abajo siguen explicando qué pantalla es y por qué está vacía.
      -->
      <img
        class="logo-institucional"
        data-testid="logo-sin-preparar"
        :src="urlLogoInstitucional"
        alt="SIS-Leg"
        width="1536"
        height="1024"
      />
      <p class="sobrelinea">Pantalla del Recinto</p>
      <h2>Recinto sin preparar</h2>
      <p>La próxima sesión todavía no fue preparada.</p>
    </main>

    <main v-else class="contenido-recinto" :class="{ 'contenido-preparando': !sesionAbierta }">
      <!--
        Primera franja de la grilla. Su alto lo fija `grid-template-rows` y está
        reservado incluso sin votación, por lo que ningún texto variable puede desplazar
        las bancas. Mientras hay un aviso de Apoyo Técnico dirigido al Recinto, esa misma
        celda la ocupa el aviso: es un reemplazo real (`v-if`/`v-else`) y no una capa
        superpuesta, de modo que la franja original no queda por detrás ocupando espacio.
      -->
      <AvisoSuperficie
        v-if="avisoTecnico"
        :texto="avisoTecnico.texto"
        data-testid="aviso-tecnico-recinto"
        rotulo="Aviso de Apoyo Técnico"
      />
      <!--
        Franja normal: tres renglones de votación a la izquierda y quórum grande a la
        derecha, con la relación espacial probada en producción.
      -->
      <section v-else data-testid="franja-votacion-quorum" class="franja-votacion-quorum">
        <PanelVotacionPublica :votacion="votacionPresentada" />
        <IndicadorQuorumPublico :quorum="estado.quorum" :total="totalConcejales" />
      </section>

      <div data-testid="zona-principal-recinto" class="zona-principal-recinto">
        <section data-testid="area-bancas-publica" class="escenario-bancas">
          <div class="envoltura-grilla">
            <GrillaBancas
              :filas-bancas="estado.filas_bancas"
              :concejales="estado.concejales"
              :banca-orador="bancaOrador"
              :estado-recepcion="estadoRecepcionVotacion"
              :bancas-voto-emitido="bancasVotoEmitido"
              :votos-individuales="votosIndividualesVisibles"
            />
            <div
              v-if="segundosCuentaRegresiva !== null"
              data-testid="countdown-votacion"
              class="countdown-votacion"
              role="status"
              aria-live="polite"
            >
              <!--
                La cuenta regresiva acompaña a una votación que ya está
                `EN_CURSO`: es el tiempo que resta para votar, no una espera
                previa. El rótulo anterior (`Comienza en`) sugería lo contrario
                y HUMAN_GATE lo corrigió en WP-054.
              -->
              <span>Votación en curso</span>
              <strong>{{ segundosCuentaRegresiva }}</strong>
            </div>
          </div>
        </section>

        <aside data-testid="columna-palabra-publica" class="columna-palabra-publica">
          <BloqueTransmisionPublico
            :transmision="transmision"
            :segundos-restantes="segundosTransmision"
          />
          <PanelPalabraPublico :palabra="estado.palabra" />
        </aside>
      </div>
    </main>
  </div>
</template>

<style scoped>
.aplicacion-recinto {
  height: 100dvh;
  min-height: 100dvh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background:
    radial-gradient(circle at 48% 105%, rgba(14, 116, 144, 0.2), transparent 38%),
    linear-gradient(155deg, #07111f 0%, #0b1729 48%, #07101d 100%);
}

.estado-inicial,
.estado-sin-preparar {
  min-height: 0;
  display: grid;
  flex: 1;
  place-content: center;
  justify-items: center;
  padding: 2rem;
  text-align: center;
}

.estado-inicial h2,
.estado-sin-preparar h2 {
  margin: 0.65rem 0 0.35rem;
  font-size: clamp(1.6rem, 4vw, 3.2rem);
}

.estado-inicial p,
.estado-sin-preparar > p:last-child {
  margin: 0;
  color: #94a3b8;
}

.pulso-carga {
  width: 5rem;
  height: 5rem;
  border: 1px solid rgba(125, 211, 252, 0.55);
  border-radius: 50%;
  box-shadow: 0 0 0 0 rgba(56, 189, 248, 0.35);
  animation: pulso 1.6s infinite;
}

/*
  Logo institucional del estado `SIN_PREPARAR` (WP-062).

  El ancho se expresa en `vw` acotado por `clamp` en lugar de fijarse en píxeles: la
  pantalla del recinto se proyecta en monitores de tamaños distintos y el logo debe
  conservar la misma presencia relativa. Los límites se eligieron para que a 1366×768
  ocupe ~300 px y a 1920×1080 llegue al tope de 384 px, proporción equivalente a la de la
  ventana de carga. `height: auto` conserva la relación 1536×1024 del archivo aprobado en
  WP-069, de modo que la marca nunca se deforma.

  Ese lienzo trae márgenes transparentes propios del archivo humano —el dibujo no llega a
  los bordes—, y WP-069 prohíbe recortarlos. Por eso la caja reservada es más alta que el
  dibujo visible: el ancho mostrado se mantuvo igual que antes para no alterar la
  presencia de la marca, y el aire sobrante queda dentro de la propia imagen.

  El bloque contenedor es un `place-content: center` sin altura fija, así que esta imagen
  no puede empujar geometría ajena: `SIN_PREPARAR` no dibuja bancas ni franjas.
*/
.logo-institucional {
  width: clamp(200px, 22vw, 384px);
  height: auto;
  margin-bottom: 0.75rem;
}

.sobrelinea {
  margin: 0 0 0.16rem;
  color: #38bdf8;
  font-size: clamp(0.52rem, 0.68vw, 0.65rem);
  font-weight: 900;
  letter-spacing: 0.13em;
  text-transform: uppercase;
}

/*
  Dos filas, no tres (WP-050).

  La franja inferior de eventos dejó de dibujarse, así que su altura completa
  —hasta 144 px en Full HD— pasa a la zona principal. La primera fila conserva
  su alto reservado incluso sin votación: es lo que impide que un tema largo o
  un cambio de estado desplacen las bancas.
*/
.contenido-recinto {
  min-height: 0;
  display: grid;
  grid-template-rows:
    clamp(118px, 16vh, 172px)
    minmax(0, 1fr);
  flex: 1;
  gap: clamp(0.45rem, 0.75vw, 0.75rem);
  padding: clamp(0.45rem, 0.75vw, 0.75rem);
  overflow: hidden;
}

/*
  Ancho de quórum calibrado contra producción: allí la caja mide 220 px en
  1920×1080 y 164 px en 1366×768 (≈12 % del ancho).

  WP-097 lo ensancha porque el bloque cambió de contenido: perdió los dos textos
  secundarios y ganó un número un 50 % más grande y un título al doble. Con el
  ancho anterior la fracción rozaba los bordes de la caja; el nuevo `clamp` le da
  el aire que pidió HUMAN_GATE («aprovechar mejor el ancho») sin dejar de ser una
  fracción del viewport. El renglón del tema cede unos 30 px, que sigue siendo
  holgado porque ese texto se recorta con elipsis desde WP-054.
*/
.franja-votacion-quorum {
  min-width: 0;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) clamp(184px, 13.5vw, 248px);
  gap: clamp(0.45rem, 0.7vw, 0.7rem);
  overflow: hidden;
}

/*
  Palabra a la derecha con el mismo ancho relativo que producción
  (`flex: 0 0 20vw`): 384 px en 1920×1080 y 273 px en 1366×768. El resto del
  ancho queda para las bancas, que siguen siendo la superficie dominante.

  WP-097 ensancha esa franja porque HUMAN_GATE exige que un nombre de 18 caracteres
  entre completo en la cola de pedidos. Con la columna anterior —256 px a 1280×720,
  273 px a 1366×768 y 384 px en Full HD— no entraba ni redistribuyendo el renglón:
  el ancho que necesita un nombre de 18 caracteres al cuerpo que fijó WP-064 es de
  ~313 px a 1280×720 y ~372 px a 1920×1080, más el marco del panel.

  Los tres términos del `clamp` se recalcularon contra esas medidas dejando margen
  para la barra de desplazamiento de la lista —que la propia lista reserva siempre—
  y para tipografías más anchas que Inter. Las bancas ceden ancho —de 995 px a
  888 px a 1280×720 y de 1499 px a 1401 px en Full HD— y siguen siendo la superficie
  dominante: son seis columnas por fila y su límite real es el alto, no el ancho.
*/
.zona-principal-recinto {
  min-height: 0;
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) clamp(365px, 25vw, 480px);
  gap: clamp(0.5rem, 0.8vw, 0.8rem);
  overflow: hidden;
}

.escenario-bancas {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: clamp(0.55rem, 0.8vw, 0.8rem);
  overflow: hidden;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 18px;
  background: rgba(7, 17, 31, 0.58);
}

.contenido-preparando .escenario-bancas {
  border-color: rgba(251, 191, 36, 0.32);
}

.envoltura-grilla {
  position: relative;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex: 1;
  overflow: hidden;
}

.countdown-votacion {
  position: absolute;
  inset: 0;
  z-index: 4;
  display: grid;
  place-content: center;
  justify-items: center;
  border: 1px solid rgba(125, 211, 252, 0.5);
  border-radius: 16px;
  color: #f8fafc;
  background: rgba(2, 8, 23, 0.78);
  backdrop-filter: blur(3px);
  pointer-events: none;
}

.countdown-votacion span {
  color: #bae6fd;
  font-size: clamp(0.8rem, 1.4vw, 1.2rem);
  font-weight: 900;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

.countdown-votacion strong {
  margin-top: 0.2rem;
  font-size: clamp(4rem, 12vw, 9rem);
  line-height: 0.9;
  text-shadow: 0 0 32px rgba(56, 189, 248, 0.45);
}

/*
  División vertical acordada por HUMAN_GATE (WP-056): un quinto superior para el
  indicador de transmisión y cuatro quintos inferiores para los pedidos de palabra.

  Se expresa con fracciones (`1fr` sobre `4fr`) y no con alturas fijas para que la
  proporción se mantenga igual a 1366×768 y a 1920×1080. `minmax(0, …)` es lo que
  permite que ambos hijos recorten su propio contenido en lugar de crecer y empujar la
  columna, que es la condición para que la lista de pedidos no gane scroll horizontal.
*/
.columna-palabra-publica {
  min-height: 0;
  min-width: 0;
  display: grid;
  grid-template-rows: minmax(0, 1fr) minmax(0, 4fr);
  gap: clamp(0.35rem, 0.6vw, 0.6rem);
  overflow: hidden;
}

@keyframes pulso {
  70% {
    box-shadow: 0 0 0 1.2rem rgba(56, 189, 248, 0);
  }
}

@media (max-width: 900px) {
  .contenido-recinto {
    display: flex;
    flex-direction: column;
    overflow-y: auto;
  }

  .franja-votacion-quorum {
    min-height: 250px;
    grid-template-columns: 1fr;
  }

  .zona-principal-recinto {
    min-height: 620px;
    grid-template-columns: 1fr;
    overflow: visible;
  }

  .columna-palabra-publica {
    min-height: 260px;
    /* Debajo de 900 px la columna se apila y la proporción 1/5 dejaría el indicador
       ilegible, así que el bloque de transmisión toma el alto que necesita. */
    grid-template-rows: auto minmax(0, 1fr);
  }
}
</style>
