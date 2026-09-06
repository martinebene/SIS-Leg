<script setup lang="ts">
/**
 * Vista principal y Shell de la aplicación de Moderación de SIS-Leg.
 *
 * Responsabilidades:
 * 1. Inicializar y consumir la frontera reactiva de sincronización (useEstadoModeracion).
 * 2. Alimentar la cabecera compacta con todos los datos globales de la pantalla:
 *    número de sesión, conexión, quórum, autoridades y ancla temporal backend.
 * 3. Disponer los cuatro cuadrantes funcionales en una grilla 2×2 que entra completa
 *    en el viewport a 1366×768 y a 1920×1080, sin scroll de página.
 * 4. Garantizar que el crecimiento interno de cualquier panel quede confinado a su propio
 *    scroll sin deformar ni empujar la altura de los demás paneles.
 * 5. Sustituir por completo el cuadrante 4 cuando Apoyo Técnico publica un aviso dirigido
 *    a Moderación, y devolver el panel de Eventos intacto cuando ese aviso expira o se
 *    cancela (WP-056).
 *
 * Sobre la sustitución de Q4 (WP-056): se usa `v-if`/`v-else`, no una superposición. Un
 * overlay dejaría el panel original ocupando su celda por detrás y podría seguir
 * generando scroll o capturando el cursor; el reemplazo real garantiza que la superficie
 * sea exactamente una de las dos: mientras hay aviso, el panel de Eventos no existe en el
 * árbol y por lo tanto no puede ocupar espacio, capturar el cursor ni generar scroll.
 *
 * Para que el panel vuelva "sin perder su estado anterior", el shell recuerda el único
 * dato local que el operador había elegido —el nivel visible— y se lo devuelve al
 * remontarlo. Todo lo demás (los eventos) vuelve del snapshot autoritativo del backend,
 * que es donde debe vivir.
 *
 * Sobre el dimensionado (WP-036): el shell no fija alturas ni anchos absolutos en píxeles.
 * La altura total la aporta `h-dvh`, el reparto vertical lo resuelve Flexbox con `flex-1`
 * y `min-h-0`, y los cuadrantes se reparten el espacio restante con filas y columnas
 * fraccionarias de CSS Grid. Así la grilla escala con el viewport en lugar de depender
 * de una resolución concreta.
 */

import { computed, ref, shallowRef } from 'vue'
import type { PuntoOrdenDelDiaProyectado } from '@sis-leg/api-client'
import type { FiltroNivelEventos } from '@sis-leg/frontend-shared'
import { useEstadoModeracion } from './composables/useEstadoModeracion'
import CabeceraModeracion from './components/CabeceraModeracion.vue'
import PanelSesionVotacion from './components/PanelSesionVotacion.vue'
import PanelOrdenDelDia from './components/PanelOrdenDelDia.vue'
import PanelRecintoPalabra from './components/PanelRecintoPalabra.vue'
import PanelEventos from './components/PanelEventos.vue'
import AvisoSuperficie from '@sis-leg/frontend-shared/componentes/AvisoSuperficie.vue'
import IndicadorCargaInicial from '@sis-leg/frontend-shared/componentes/IndicadorCargaInicial.vue'

// Conectamos con el composable reactivo de moderación
const { estado, estadoConexion, estadoGlobal, revision, desactualizado, conectado, cliente } =
  useEstadoModeracion()

/** Cantidad de bancas del padrón activo; sirve de total de referencia del quórum en cabecera. */
const totalConcejales = computed(() => estado.value?.concejales?.length ?? 0)

/**
 * Presidencia vigente, tomada de la sesión abierta o, si todavía no hay sesión,
 * de la preparación en curso. De este modo la autoridad aparece en cabecera desde
 * el mismo momento en que fue cargada, incluso durante PREPARANDO.
 */
const presidencia = computed(
  () => estado.value?.sesion?.presidencia ?? estado.value?.preparacion?.presidencia ?? null,
)

/** Secretaría Legislativa vigente, con el mismo criterio que la Presidencia. */
const secretariaLegislativa = computed(
  () =>
    estado.value?.sesion?.secretaria_legislativa ??
    estado.value?.preparacion?.secretaria_legislativa ??
    null,
)

/**
 * Marca autoritativa de apertura formal de la sesión.
 * Sólo existe con sesión abierta; la cabecera deriva de ella el tiempo transcurrido.
 */
const fechaHoraApertura = computed(() => estado.value?.sesion?.fecha_hora_apertura ?? null)

/**
 * Momento de generación del snapshot. Se entrega junto con la apertura para que la
 * cabecera reste dos marcas del mismo reloj backend y no dependa de la zona del navegador.
 */
const generadoEn = computed(() => estado.value?.generado_en ?? null)

/**
 * Número institucional visible en la cabecera. Durante PREPARANDO puede ser nulo;
 * una sesión abierta siempre aporta el número definitivo desde `sesion`.
 */
const numeroSesion = computed(
  () => estado.value?.sesion?.numero_sesion ?? estado.value?.preparacion?.numero_sesion ?? null,
)

/**
 * Conserva únicamente el punto elegido como borrador visual entre los cuadrantes.
 * Se crea una copia nueva en cada selección para que volver a elegir el mismo punto
 * también vuelva a precargar el formulario. La colección autoritativa continúa en
 * `estado.orden_del_dia`; esta referencia nunca marca ni consume el punto original.
 */
const puntoSeleccionado = shallowRef<PuntoOrdenDelDiaProyectado | null>(null)

/**
 * Aviso técnico vigente para esta pantalla, o `null` si no hay ninguno.
 *
 * El backend ya separó los destinos: en `EstadoModeracion.tecnico.aviso` sólo puede
 * llegar un aviso dirigido a MODERACION o a AMBOS. Un aviso publicado sólo hacia el
 * Recinto jamás viaja en este snapshot, así que acá no hace falta —ni sería correcto—
 * volver a filtrar por destino. También desaparece solo al vencer: la vigencia la
 * decide el reloj del backend, que republica una revisión nueva al cruzar la frontera.
 */
const avisoTecnico = computed(() => estado.value?.tecnico?.aviso ?? null)

/**
 * Estado autoritativo de transmisión para el indicador binario de la cabecera (WP-057).
 *
 * Viaja en el mismo snapshot que todo lo demás (`EstadoModeracion.tecnico.transmision`),
 * así que no hace falta ninguna consulta adicional ni ningún polling: cuando el backend
 * cruza la frontera de la cuenta regresiva publica una revisión nueva por SSE y este
 * valor cambia solo. Vale `null` únicamente mientras no llegó el primer snapshot.
 */
const estadoTransmision = computed(() => estado.value?.tecnico?.transmision?.estado ?? null)

/**
 * Nivel visible elegido por el operador en el panel de Eventos.
 *
 * Vive en el shell y no en el panel porque el panel se desmonta mientras hay un aviso.
 * Es una preferencia de presentación, nunca un filtro sobre lo que el backend publica.
 */
const nivelEventos = ref<FiltroNivelEventos>('L3')

function seleccionarPuntoOrdenDelDia(punto: PuntoOrdenDelDiaProyectado): void {
  puntoSeleccionado.value = { ...punto }
}

/** Recuerda el nivel elegido para devolverlo al panel cuando se remonta. */
function recordarNivelEventos(nivel: FiltroNivelEventos): void {
  nivelEventos.value = nivel
}
</script>

<template>
  <div
    class="flex h-dvh w-full min-w-0 flex-col overflow-hidden bg-slate-950 text-slate-100 antialiased select-none"
  >
    <!--
      Barra indeterminada de carga inicial (WP-061). Toma el relevo del indicador previo a
      la hidratación, que Nuxt elimina al montar el árbol de Vue, y acompaña la espera del
      primer snapshot. Está posicionada `fixed`, así que no ocupa lugar en la grilla: al
      llegar el estado desaparece sin dejar hueco ni mover ningún cuadrante.
    -->
    <IndicadorCargaInicial v-if="!estado" />

    <!-- Cabecera compacta: única sede de los datos globales de la pantalla -->
    <CabeceraModeracion
      :estado-conexion="estadoConexion"
      :estado-global="estadoGlobal"
      :revision="revision"
      :desactualizado="desactualizado"
      :quorum="estado?.quorum ?? null"
      :total-concejales="totalConcejales"
      :presidencia="presidencia"
      :secretaria-legislativa="secretariaLegislativa"
      :fecha-hora-apertura="fechaHoraApertura"
      :generado-en="generadoEn"
      :numero-sesion="numeroSesion"
      :estado-transmision="estadoTransmision"
    />

    <!-- Área de trabajo principal con grilla 2×2 en desktop (1366×768 y 1920×1080) -->
    <main class="flex flex-1 min-h-0 min-w-0 flex-col overflow-hidden p-2">
      <div
        data-testid="grilla-paneles"
        class="grid flex-1 min-h-0 min-w-0 grid-cols-1 auto-rows-[minmax(45dvh,auto)] gap-2 overflow-y-auto lg:grid-cols-2 lg:grid-rows-2 lg:overflow-hidden"
      >
        <!-- Cuadrante 1 (arriba izquierda): Sesión y votación -->
        <PanelSesionVotacion :estado="estado" :punto-preseleccionado="puntoSeleccionado" />

        <!-- Cuadrante 2 (arriba derecha): Orden del Día -->
        <PanelOrdenDelDia :estado="estado" @seleccionar="seleccionarPuntoOrdenDelDia" />

        <!-- Cuadrante 3 (abajo izquierda): Recinto y palabra -->
        <PanelRecintoPalabra :estado="estado" :cliente="cliente" :conectado="conectado" />

        <!--
          Cuadrante 4 (abajo derecha): Eventos, o el aviso de Apoyo Técnico que lo
          reemplaza por completo mientras está vigente (WP-056).
        -->
        <PanelEventos
          v-if="!avisoTecnico"
          :estado="estado"
          :nivel-inicial="nivelEventos"
          @cambiar-nivel="recordarNivelEventos"
        />
        <AvisoSuperficie
          v-if="avisoTecnico"
          :texto="avisoTecnico.texto"
          data-testid="aviso-tecnico-moderacion"
          rotulo="Aviso de Apoyo Técnico para Moderación"
        />
      </div>
    </main>
  </div>
</template>
