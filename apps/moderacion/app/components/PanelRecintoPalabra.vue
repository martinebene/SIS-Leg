<script setup lang="ts">
/**
 * Panel de Recinto y Palabra (Cuadrante 3 de Moderación).
 *
 * Responsabilidades:
 * 1. Disponer las bancas del recinto según la configuración de filas (filas_bancas) y padrón activo.
 * 2. Reflejar presencia física y test temporal de teclado en modo solo lectura.
 * 3. Integrar los controles autoritativos de palabra y el flujo de remapeo físico.
 *
 * Quórum (WP-036): este cuadrante ya no presenta el resumen global de quórum ni el conteo
 * de presentes. Ese dato es único y global, y vive exclusivamente en la cabecera compacta,
 * de modo que no se repita en dos lugares que podrían llegar a divergir visualmente.
 * La presencia individual de cada concejal se sigue viendo en su propia banca.
 *
 * WP-044 mueve `Remapear dispositivo` al área de acciones del encabezado del panel y
 * elimina el subencabezado interior `Distribución de bancas`. La altura recuperada
 * queda disponible para la grilla, que es el contenido con valor operativo real. El
 * botón sigue viviendo en este componente: `PanelContenedor` solo presta el slot y no
 * conoce nada del flujo de remapeo.
 *
 * Invariantes respetados:
 * - NO incluye controles de presencia manual ni atajos de teclado para marcar presencia.
 * - NO modifica localmente quórum ni presencia ante tests de teclado.
 * - Resuelve imágenes exclusivamente desde ruta_imagen sin hardcodeo de nombres de archivo.
 */

import { computed, ref, toRef, watch } from 'vue'
import {
  crearClienteModeracion,
  type ClienteModeracion,
  type EstadoModeracion,
} from '@sis-leg/api-client'
import PanelContenedor from './PanelContenedor.vue'
import GrillaRecinto from './GrillaRecinto.vue'
import GestionPalabra from './GestionPalabra.vue'
import GestionRemapeo from '@sis-leg/frontend-shared/componentes/GestionRemapeo.vue'
import { usePresentacionBancas } from '../composables/usePresentacionBancas'

const props = defineProps<{
  /** Estado autoritativo de moderación recibido desde el backend */
  estado: EstadoModeracion | null
  /** Cliente compartido por la aplicación; la inyección mantiene tests deterministas. */
  cliente?: ClienteModeracion
  /** Solo una conexión confirmada habilita los comandos del cuadrante. */
  conectado?: boolean
}>()

// El fallback permite renderizar el componente aislado en SSR sin abrir una
// suscripción ni duplicar la frontera de sincronización de la aplicación.
const clienteEfectivo = props.cliente ?? crearClienteModeracion()
const { votosIndividuales: votosIndividualesPresentados } = usePresentacionBancas(
  toRef(props, 'estado'),
)

/**
 * Controla únicamente si el operador abrió el cajón visual de remapeo.
 *
 * La operación física no se representa con esta referencia: cuando el backend
 * proyecta `estado.remapeo`, el flujo completo se vuelve visible aunque el
 * operador nunca haya abierto el cajón local.
 */
const remapeoDesplegado = ref(false)
const remapeoActivo = computed(
  () => props.estado?.remapeo !== null && props.estado?.remapeo !== undefined,
)
const mostrarRemapeo = computed(() => remapeoActivo.value || remapeoDesplegado.value)

/** Al terminar una operación autoritativa se recupera automáticamente el modo compacto. */
watch(
  () => props.estado?.remapeo ?? null,
  (remapeoNuevo, remapeoAnterior) => {
    if (remapeoAnterior !== null && remapeoNuevo === null) remapeoDesplegado.value = false
  },
)

function abrirRemapeo(): void {
  remapeoDesplegado.value = true
}

/** Cerrar el cajón nunca cancela ni modifica una operación de backend. */
function cerrarRemapeo(): void {
  if (!remapeoActivo.value) remapeoDesplegado.value = false
}
</script>

<template>
  <PanelContenedor
    titulo="Recinto y palabra"
    data-testid="panel-recinto-palabra"
    contenido-con-scroll-propio
  >
    <!--
      La acción vive en el encabezado, alineada a la derecha del título. Solo se ofrece
      cuando el estado admite iniciar el flujo y todavía no hay un cajón abierto ni una
      operación autoritativa en curso: en ese caso el flujo completo ya está visible.
    -->
    <template #acciones>
      <button
        v-if="estado && estado.estado_global !== 'SIN_PREPARAR' && !mostrarRemapeo"
        type="button"
        data-testid="btn-desplegar-remapeo"
        class="rounded border border-violet-700 bg-violet-950/70 px-2 py-1 text-[10px] font-bold text-violet-200"
        @click="abrirRemapeo"
      >
        Remapear dispositivo
      </button>
    </template>

    <div
      v-if="estado"
      data-testid="composicion-recinto-palabra"
      class="flex h-full min-h-0 min-w-0 gap-2 text-sm text-slate-300"
    >
      <!-- Las bancas conservan el área flexible principal y nunca generan scroll normal. -->
      <div
        data-testid="area-bancas-moderacion"
        class="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-xl border border-slate-800 bg-slate-950/50 p-2"
      >
        <GrillaRecinto
          v-if="estado.concejales && estado.concejales.length > 0"
          :concejales="estado.concejales"
          :filas-bancas="estado.configuracion?.filas_bancas"
          :banca-orador="estado.palabra?.orador?.banca ?? null"
          :estado-recepcion="estado.votacion?.estado_recepcion ?? null"
          :bancas-voto-emitido="estado.votacion?.bancas_voto_emitido ?? null"
          :votos-individuales="votosIndividualesPresentados"
        />

        <div
          v-else
          class="grid min-h-0 flex-1 place-items-center rounded-lg border border-dashed border-slate-800 p-4 text-center text-xs text-slate-400"
        >
          No hay bancas proyectadas en el contexto actual.
        </div>

        <!--
          El flujo completo se superpone dentro del área izquierda. Así no empuja
          la cola ni altera la geometría normal de bancas; si su contenido crece,
          el scroll queda confinado a este cajón excepcional de operación.
        -->
        <div
          v-if="estado.estado_global !== 'SIN_PREPARAR' && mostrarRemapeo"
          data-testid="panel-remapeo-desplegado"
          class="absolute inset-1.5 z-20 flex min-h-0 flex-col overflow-hidden rounded-lg border border-violet-700 bg-slate-950/98 shadow-2xl"
        >
          <div
            class="flex shrink-0 items-center justify-between border-b border-violet-900 px-2 py-1"
          >
            <span class="text-[10px] font-bold uppercase tracking-wider text-violet-300">
              {{ remapeoActivo ? 'Remapeo activo' : 'Remapear dispositivo' }}
            </span>
            <button
              v-if="!remapeoActivo"
              type="button"
              data-testid="btn-cerrar-remapeo"
              class="rounded border border-slate-700 px-2 py-0.5 text-[10px] text-slate-300"
              @click="cerrarRemapeo"
            >
              Cerrar
            </button>
          </div>
          <div class="min-h-0 flex-1 overflow-y-auto p-1.5">
            <GestionRemapeo
              :estado="estado"
              :cliente="clienteEfectivo"
              :conectado="conectado ?? false"
            />
          </div>
        </div>
      </div>

      <!-- Cola/orador y comandos: toda transición llega luego desde REST/SSE. -->
      <div
        data-testid="columna-palabra-moderacion"
        class="h-full min-h-0 w-[clamp(15rem,31%,21rem)] shrink-0"
      >
        <GestionPalabra
          :estado="estado"
          :cliente="clienteEfectivo"
          :conectado="conectado ?? false"
        />
      </div>
    </div>

    <!-- Estado inicial mientras no hay datos -->
    <div
      v-else
      class="grid h-full place-items-center rounded-lg border border-dashed border-slate-800 p-6 text-center text-xs text-slate-400"
    >
      Conectando y esperando estado autoritativo del backend...
    </div>
  </PanelContenedor>
</template>
