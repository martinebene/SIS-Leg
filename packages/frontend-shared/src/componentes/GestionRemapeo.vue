<script setup lang="ts">
/**
 * Gestiona la interfaz del remapeo físico coordinado por FastAPI.
 *
 * WP-056 lo trasladó desde `apps/moderacion` a `packages/frontend-shared` porque el
 * puesto de Apoyo Técnico debe ofrecer exactamente el mismo remapeo que Moderación.
 * Compartir el componente —en lugar de copiarlo— es lo que garantiza que las dos
 * pantallas usen las mismas capacidades, los mismos comandos y los mismos textos: una
 * corrección futura no puede quedar aplicada en una sola interfaz. Sigue siendo la
 * única superficie de remapeo del proyecto y no incorpora reglas propias.
 *
 * WP-074 reemplaza sus dos dependencias concretas por contratos mínimos: en lugar de exigir
 * un `EstadoModeracion` y un `ClienteModeracion`, pide sólo lo que lee y lo que ejecuta.
 * El motivo es que Apoyo Técnico dejó de observar la proyección de Moderación —esa
 * suscripción de más agotaba las conexiones HTTP/1.1 del navegador— y ahora recibe la misma
 * información dentro de su propio estado. El comportamiento no cambió: mismos campos,
 * mismos comandos, mismas capacidades.
 *
 * La selección de banca y del modo de persistencia son borradores locales del
 * operador. La operación activa, sus fingerprints y su etapa se reconstruyen
 * siempre desde `estado.remapeo`; ningún 201/204 modifica ese estado
 * de forma optimista ni conecta al navegador con el device-bridge.
 *
 * WP-051 retira los tres acuses de tránsito que este panel dejaba fijos en pantalla
 * ("Inicio enviado…", "Confirmación enviada…", "Cancelación enviada…"). Eran acuses
 * puramente técnicos: describían que la petición había salido, mientras que el hecho real
 * ya lo confirma la propia operación proyectada en `estado.remapeo` (aparece esperando
 * pulsación, pasa a candidato o desaparece) y queda registrado por la auditoría del
 * backend. Los errores del remapeo siguen mostrándose sin caducidad porque exigen una
 * decisión del operador.
 */

import { computed, ref, watch } from 'vue'
import type { ClienteRemapeo } from '@botonera2/api-client'
import { extraerMensajeError } from '../errores'
import { traducirMotivos } from '../motivos'
import type { EstadoRemapeoCompartido } from '../contrato_remapeo'

const props = defineProps<{
  /**
   * Estado autoritativo mínimo del remapeo (WP-074).
   *
   * Moderación pasa acá su `EstadoModeracion` completo y Apoyo Técnico pasa la allowlist
   * `EstadoTecnico.remapeo`: las dos satisfacen el mismo contrato, así que el componente no
   * distingue de qué pantalla viene ni necesita una segunda suscripción para funcionar.
   */
  estado: EstadoRemapeoCompartido | null
  /** Comandos REST de remapeo; el browser solo conoce esta frontera y nunca al bridge. */
  cliente: ClienteRemapeo
  /** Estado técnico confirmado del stream SSE de la pantalla que lo aloja. */
  conectado: boolean
}>()

type PersistenciaSeleccionada = 'TEMPORAL' | 'PERSISTENTE'
type AccionRemapeo = 'INICIAR' | 'CONFIRMAR' | 'CANCELAR'

const dispositivoSeleccionado = ref('')
const persistenciaSeleccionada = ref<PersistenciaSeleccionada | null>(null)
const accionEnVuelo = ref<AccionRemapeo | null>(null)
const mensajeError = ref<string | null>(null)

const remapeo = computed(() => props.estado?.remapeo ?? null)
const concejales = computed(() => props.estado?.concejales ?? [])
const concejalSeleccionado = computed(
  () =>
    concejales.value.find(
      (concejal) => concejal.dispositivo_votacion === dispositivoSeleccionado.value,
    ) ?? null,
)
const concejalObjetivo = computed(() => {
  const dispositivo = remapeo.value?.dispositivo
  if (!dispositivo) return null
  return concejales.value.find((concejal) => concejal.dispositivo_votacion === dispositivo) ?? null
})

const capacidadIniciar = computed(() => props.estado?.capacidades.iniciar_remapeo)
const capacidadConfirmar = computed(() => props.estado?.capacidades.confirmar_remapeo)
const capacidadCancelar = computed(() => props.estado?.capacidades.cancelar_remapeo)

const puedeIniciar = computed(
  () =>
    props.conectado &&
    remapeo.value === null &&
    concejalSeleccionado.value !== null &&
    (capacidadIniciar.value?.habilitada ?? false) &&
    accionEnVuelo.value === null,
)
const puedeConfirmar = computed(
  () =>
    props.conectado &&
    remapeo.value?.estado === 'CANDIDATO' &&
    remapeo.value.candidato !== null &&
    concejalObjetivo.value !== null &&
    persistenciaSeleccionada.value !== null &&
    (capacidadConfirmar.value?.habilitada ?? false) &&
    accionEnVuelo.value === null,
)
const puedeCancelar = computed(
  () =>
    props.conectado &&
    remapeo.value !== null &&
    remapeo.value.estado !== 'CONFIRMANDO' &&
    (capacidadCancelar.value?.habilitada ?? false) &&
    accionEnVuelo.value === null,
)

const motivosIniciar = computed(() => traducirMotivos(capacidadIniciar.value?.motivos))
const motivosConfirmar = computed(() => traducirMotivos(capacidadConfirmar.value?.motivos))
const motivosCancelar = computed(() => traducirMotivos(capacidadCancelar.value?.motivos))

/**
 * Una baseline nueva puede reemplazar completamente la operación. Al cambiar
 * su identidad se descarta únicamente el modo local todavía no enviado; nunca
 * se conserva una elección humana para otro remapeo.
 */
watch(
  () => remapeo.value?.remapeo_id ?? null,
  (nuevoId, idAnterior) => {
    persistenciaSeleccionada.value = null
    if (idAnterior !== null && nuevoId === null) {
      dispositivoSeleccionado.value = ''
    }
  },
)

/**
 * Borra el error anterior antes de emitir un comando nuevo, para que un fallo viejo no
 * quede acusando a la operación que el operador acaba de reintentar.
 */
function limpiarMensajes(): void {
  mensajeError.value = null
}

/** Inicia captura para el devXX elegido desde una opción de banca proyectada. */
async function iniciarRemapeo(): Promise<void> {
  const concejal = concejalSeleccionado.value
  if (!puedeIniciar.value || concejal === null) return
  limpiarMensajes()
  accionEnVuelo.value = 'INICIAR'
  try {
    await props.cliente.iniciarRemapeo(concejal.dispositivo_votacion)
  } catch (error: unknown) {
    mensajeError.value = extraerMensajeError(error, 'No se pudo iniciar el remapeo.')
  } finally {
    accionEnVuelo.value = null
  }
}

/**
 * Confirma exactamente el ID proyectado y el modo elegido. El 204 no limpia
 * la operación: se espera el snapshot que la quite o muestre su nueva etapa.
 */
async function confirmarRemapeo(): Promise<void> {
  const operacion = remapeo.value
  const persistencia = persistenciaSeleccionada.value
  if (!puedeConfirmar.value || operacion === null || persistencia === null) return
  limpiarMensajes()
  accionEnVuelo.value = 'CONFIRMAR'
  try {
    await props.cliente.confirmarRemapeo(operacion.remapeo_id, persistencia)
  } catch (error: unknown) {
    mensajeError.value = extraerMensajeError(error, 'No se pudo confirmar el remapeo.')
  } finally {
    accionEnVuelo.value = null
  }
}

/** Cancela el mismo ID autoritativo sin borrar localmente la operación. */
async function cancelarRemapeo(): Promise<void> {
  const operacion = remapeo.value
  if (!puedeCancelar.value || operacion === null) return
  limpiarMensajes()
  accionEnVuelo.value = 'CANCELAR'
  try {
    await props.cliente.cancelarRemapeo(operacion.remapeo_id)
  } catch (error: unknown) {
    mensajeError.value = extraerMensajeError(error, 'No se pudo cancelar el remapeo.')
  } finally {
    accionEnVuelo.value = null
  }
}
</script>

<template>
  <section
    data-testid="gestion-remapeo"
    class="space-y-3 rounded-lg border border-violet-900/80 bg-violet-950/20 p-3 text-xs"
  >
    <div class="flex flex-wrap items-start justify-between gap-2">
      <div>
        <h3 class="font-bold uppercase tracking-wider text-violet-200">Remapeo de dispositivo</h3>
        <p class="mt-0.5 text-[10px] text-slate-400">
          Conserva el mismo devXX, banca, persona y hechos institucionales.
        </p>
      </div>
      <span
        v-if="remapeo"
        data-testid="estado-remapeo"
        class="rounded border border-violet-700 bg-violet-950 px-2 py-1 font-bold text-violet-200"
      >
        {{ remapeo.estado }}
      </span>
    </div>

    <div v-if="!remapeo" data-testid="inicio-remapeo" class="space-y-2">
      <label for="selector-banca-remapeo" class="block font-semibold text-slate-300">
        Banca y dispositivo a reemplazar
      </label>
      <div class="flex flex-col gap-2 sm:flex-row">
        <select
          id="selector-banca-remapeo"
          v-model="dispositivoSeleccionado"
          data-testid="selector-banca-remapeo"
          class="min-w-0 flex-1 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 disabled:opacity-50"
          :disabled="accionEnVuelo !== null || !conectado || !capacidadIniciar?.habilitada"
        >
          <option value="">Elegí una banca</option>
          <option
            v-for="concejal in concejales"
            :key="concejal.dni"
            :value="concejal.dispositivo_votacion"
          >
            Banca {{ concejal.banca }} · {{ concejal.nombre }} {{ concejal.apellido }} ·
            {{ concejal.dispositivo_votacion }}
          </option>
        </select>
        <button
          type="button"
          data-testid="btn-iniciar-remapeo"
          class="rounded-lg border border-violet-700 bg-violet-950 px-3 py-2 font-bold text-violet-200 disabled:cursor-not-allowed disabled:opacity-40"
          :disabled="!puedeIniciar"
          @click="iniciarRemapeo"
        >
          {{ accionEnVuelo === 'INICIAR' ? 'Iniciando...' : 'Iniciar remapeo' }}
        </button>
      </div>
      <p
        v-if="concejalSeleccionado"
        data-testid="resumen-inicio-remapeo"
        class="rounded border border-slate-800 bg-slate-950/70 p-2 text-slate-300"
      >
        Banca {{ concejalSeleccionado.banca }} · {{ concejalSeleccionado.nombre }}
        {{ concejalSeleccionado.apellido }} ·
        <strong class="font-mono text-violet-300">{{
          concejalSeleccionado.dispositivo_votacion
        }}</strong>
      </p>
      <ul
        v-if="conectado && !capacidadIniciar?.habilitada"
        data-testid="motivos-iniciar-remapeo"
        class="space-y-1 text-slate-400"
      >
        <li v-for="motivo in motivosIniciar" :key="motivo">{{ motivo }}</li>
      </ul>
    </div>

    <div v-else data-testid="remapeo-activo" class="space-y-3">
      <dl class="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <div class="rounded border border-slate-800 bg-slate-950/70 p-2">
          <dt class="text-[10px] uppercase tracking-wider text-slate-500">Persona objetivo</dt>
          <dd v-if="concejalObjetivo" data-testid="persona-remapeo" class="mt-1 text-slate-200">
            Banca {{ concejalObjetivo.banca }} · {{ concejalObjetivo.nombre }}
            {{ concejalObjetivo.apellido }}
          </dd>
          <dd v-else class="mt-1 text-rose-300">La banca objetivo no está en este snapshot.</dd>
        </div>
        <div class="rounded border border-slate-800 bg-slate-950/70 p-2">
          <dt class="text-[10px] uppercase tracking-wider text-slate-500">Dispositivo lógico</dt>
          <dd data-testid="dispositivo-remapeo" class="mt-1 font-mono font-bold text-violet-300">
            {{ remapeo.dispositivo }}
          </dd>
        </div>
        <div class="rounded border border-slate-800 bg-slate-950/70 p-2">
          <dt class="text-[10px] uppercase tracking-wider text-slate-500">Fingerprint anterior</dt>
          <dd data-testid="fingerprint-anterior" class="mt-1 break-all font-mono text-slate-300">
            {{ remapeo.fingerprint_anterior ?? 'No informado' }}
          </dd>
        </div>
        <div v-if="remapeo.candidato" class="rounded border border-cyan-900 bg-cyan-950/30 p-2">
          <dt class="text-[10px] uppercase tracking-wider text-cyan-500">Fingerprint candidato</dt>
          <dd data-testid="fingerprint-candidato" class="mt-1 break-all font-mono text-cyan-200">
            {{ remapeo.candidato }}
          </dd>
        </div>
      </dl>

      <p
        v-if="remapeo.estado === 'CAPTURANDO'"
        data-testid="espera-captura-remapeo"
        class="rounded border border-amber-800 bg-amber-950/40 p-2 text-amber-200"
      >
        Esperando la primera pulsación de un teclado físico elegible. Los dispositivos ya mapeados
        continúan funcionando normalmente.
      </p>

      <p
        v-if="remapeo.diagnostico"
        data-testid="diagnostico-remapeo"
        class="rounded border border-slate-700 bg-slate-900 p-2 text-slate-300"
      >
        Diagnóstico: {{ remapeo.diagnostico }}
      </p>

      <fieldset
        v-if="remapeo.estado === 'CANDIDATO'"
        data-testid="seleccion-persistencia"
        class="space-y-2 rounded border border-slate-700 bg-slate-900/70 p-3"
        :disabled="accionEnVuelo !== null"
      >
        <legend class="px-1 font-bold text-slate-200">Elegí cómo aplicar el cambio</legend>
        <label class="flex cursor-pointer items-start gap-2 rounded border border-slate-700 p-2">
          <input
            v-model="persistenciaSeleccionada"
            data-testid="persistencia-temporal"
            type="radio"
            name="persistencia-remapeo"
            value="TEMPORAL"
            class="mt-0.5"
          />
          <span>
            <strong class="text-slate-100">TEMPORAL</strong>
            <span class="block text-slate-400"
              >Solo en memoria; se pierde al reiniciar el bridge.</span
            >
          </span>
        </label>
        <label class="flex cursor-pointer items-start gap-2 rounded border border-slate-700 p-2">
          <input
            v-model="persistenciaSeleccionada"
            data-testid="persistencia-persistente"
            type="radio"
            name="persistencia-remapeo"
            value="PERSISTENTE"
            class="mt-0.5"
          />
          <span>
            <strong class="text-slate-100">PERSISTENTE</strong>
            <span class="block text-slate-400"
              >Reemplaza el mapping base y sobrevive reinicios.</span
            >
          </span>
        </label>
      </fieldset>

      <div
        v-if="remapeo.estado === 'CANDIDATO' && persistenciaSeleccionada"
        data-testid="resumen-confirmacion-remapeo"
        class="rounded border border-violet-700 bg-violet-950/50 p-3 text-slate-200"
      >
        Confirmarás: Banca {{ concejalObjetivo?.banca ?? '—' }} ·
        {{ concejalObjetivo?.nombre ?? 'Persona no proyectada' }}
        {{ concejalObjetivo?.apellido ?? '' }} ·
        <span class="font-mono">{{ remapeo.dispositivo }}</span> · anterior
        <span class="break-all font-mono">{{
          remapeo.fingerprint_anterior ?? 'no informado'
        }}</span>
        · candidato <span class="break-all font-mono">{{ remapeo.candidato }}</span> · modo
        <strong>{{ persistenciaSeleccionada }}</strong
        >.
      </div>

      <p
        v-if="remapeo.estado === 'CONFIRMANDO'"
        data-testid="confirmando-remapeo"
        class="rounded border border-cyan-800 bg-cyan-950/40 p-2 text-cyan-200"
      >
        El backend está reconciliando la aplicación física. Los controles permanecen bloqueados.
      </p>

      <div class="flex flex-col gap-2 sm:flex-row sm:justify-end">
        <button
          type="button"
          data-testid="btn-cancelar-remapeo"
          class="rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 font-bold text-slate-200 disabled:cursor-not-allowed disabled:opacity-40"
          :disabled="!puedeCancelar"
          @click="cancelarRemapeo"
        >
          {{ accionEnVuelo === 'CANCELAR' ? 'Cancelando...' : 'Cancelar remapeo' }}
        </button>
        <button
          v-if="remapeo.estado === 'CANDIDATO'"
          type="button"
          data-testid="btn-confirmar-remapeo"
          class="rounded-lg border border-violet-600 bg-violet-900 px-3 py-2 font-bold text-violet-100 disabled:cursor-not-allowed disabled:opacity-40"
          :disabled="!puedeConfirmar"
          @click="confirmarRemapeo"
        >
          {{ accionEnVuelo === 'CONFIRMAR' ? 'Confirmando...' : 'Confirmar remapeo' }}
        </button>
      </div>

      <ul
        v-if="remapeo.estado === 'CANDIDATO' && !capacidadConfirmar?.habilitada"
        data-testid="motivos-confirmar-remapeo"
        class="space-y-1 text-slate-400"
      >
        <li v-for="motivo in motivosConfirmar" :key="motivo">{{ motivo }}</li>
      </ul>
      <ul
        v-if="!capacidadCancelar?.habilitada"
        data-testid="motivos-cancelar-remapeo"
        class="space-y-1 text-slate-400"
      >
        <li v-for="motivo in motivosCancelar" :key="motivo">{{ motivo }}</li>
      </ul>
    </div>

    <p
      v-if="!conectado"
      data-testid="remapeo-sin-conexion"
      class="rounded border border-amber-800 bg-amber-950/40 p-2 text-amber-200"
    >
      El remapeo requiere conexión confirmada con FastAPI.
    </p>
    <p
      v-if="mensajeError"
      data-testid="error-remapeo"
      class="rounded border border-rose-700 bg-rose-950/60 p-2 text-rose-200"
      role="alert"
    >
      {{ mensajeError }}
    </p>
  </section>
</template>
