<script setup lang="ts">
/**
 * Panel operativo del Orden del Día (Cuadrante 2).
 *
 * El archivo seleccionado es un dato visual transitorio. Se envía sin parsearlo al
 * backend y la lista renderizada siempre proviene de `EstadoModeracion`. Así un error
 * de carga no borra una colección válida ni instala una respuesta optimista local.
 *
 * La existencia de puntos define dos vistas mutuamente excluyentes: carga compacta o
 * colección confirmada. Al quitar, los puntos permanecen visibles hasta que un snapshot
 * vacío llegue desde backend. Seleccionar un punto solo emite una copia para precargar Q1:
 * no muta la colección autoritativa ni marca nada por su cuenta.
 *
 * WP-053 agrega la única ayuda de seguimiento del cuadrante. El backend informa por punto
 * el campo `tratado`, verdadero cuando ya se abrió una votación con ese mismo
 * `nro_votacion` durante la sesión. Este componente se limita a atenuarlo: no lo calcula,
 * no lo recuerda entre snapshots y no lo deshabilita. Un punto atenuado conserva hover,
 * click, toast y precarga exactamente igual que cualquier otro, porque la marca es
 * asistencial y SIS-Leg permite reutilizar un número. Como el dato llega en cada
 * snapshot, una reconexión o un reload reconstruyen la atenuación sin estado local.
 *
 * WP-044 concentra en este cuadrante el único acuse visual de la copia asistencial:
 * un toast flotante de ~1 segundo. El toast se dibuja superpuesto (position absolute)
 * para no reservar altura ni desplazar la lista, se reemplaza a sí mismo cuando el
 * operador elige otro punto y cancela su temporizador al desmontar el componente. Es
 * feedback puramente presentacional: no confirma ninguna mutación institucional, porque
 * la copia solo precarga un borrador local de Q1.
 *
 * WP-048 retira el acuse persistente de una carga exitosa: la colección proyectada es por
 * sí misma la confirmación y el renglón informativo solo restaba alto útil.
 *
 * WP-051 completa esa política sobre el descarte. El acuse "Descarte enviado…" describía un
 * tránsito HTTP y quedaba fijo en el cuadrante; el hecho institucional ya lo audita el
 * backend (`ORDEN_DEL_DIA_DESCARTADO`) y lo confirma el snapshot vacío que reemplaza la
 * colección. Se conserva sólo una confirmación humana breve, con la misma caducidad que el
 * acuse de copia, para que el operador perciba que el comando fue aceptado incluso si el
 * snapshot todavía no llegó. Los errores reales siguen siendo siempre visibles.
 */

import { computed, ref } from 'vue'
import type {
  ClienteModeracion,
  EstadoModeracion,
  PuntoOrdenDelDiaProyectado,
} from '@sis-leg/api-client'
// WP-063: el factor del punto se muestra con dos decimales truncados. El punto proyectado
// conserva su valor real: acá sólo se cambia cómo se escribe en el rótulo.
import { formatearFactorMayoria } from '@sis-leg/frontend-shared'
import { useEstadoModeracion } from '../composables/useEstadoModeracion'
import { useAvisoEfimero } from '../composables/useAvisoEfimero'
import { traducirMotivos } from '../utils/motivos'
import PanelContenedor from './PanelContenedor.vue'

const props = defineProps<{
  estado: EstadoModeracion | null
  /** Frontera inyectable que permite pruebas DOM sin red real. */
  clienteInyectado?: ClienteModeracion
}>()

const emit = defineEmits<{
  seleccionar: [punto: PuntoOrdenDelDiaProyectado]
}>()

const sincronizacion = useEstadoModeracion(props.clienteInyectado)
const cliente = computed(() => props.clienteInyectado ?? sincronizacion.cliente)
const conectado = computed(() => sincronizacion.conectado.value)
const archivoSeleccionado = ref<File | null>(null)
const inputArchivo = ref<HTMLInputElement | null>(null)
const cargando = ref(false)
const descartando = ref(false)
const mensajeError = ref<string | null>(null)

/** Duración objetivo del acuse, fijada por WP-044. */
const DURACION_TOAST_MS = 1000

/**
 * Los dos acuses efímeros del cuadrante comparten la mecánica de caducidad (WP-051 la
 * concentra en `useAvisoEfimero`) pero se mantienen separados porque hablan de cosas
 * distintas: uno acusa una copia asistencial puramente local y el otro la aceptación de
 * una mutación institucional. En la práctica no conviven, porque después de descartar ya
 * no queda ningún punto para copiar.
 */
const avisoCopia = useAvisoEfimero(DURACION_TOAST_MS)
const toastCopia = avisoCopia.mensaje
const avisoDescarte = useAvisoEfimero(DURACION_TOAST_MS)
const mensajeDescarte = avisoDescarte.mensaje

const capacidadCargar = computed(() => props.estado?.capacidades.cargar_orden_del_dia)
const capacidadDescartar = computed(() => props.estado?.capacidades.descartar_orden_del_dia)
// Las fixtures heredadas de WP-022 todavía no incluían esta proyección opcional.
const puntosOrdenDelDia = computed(() => props.estado?.orden_del_dia ?? [])
const tieneOrdenDelDia = computed(() => puntosOrdenDelDia.value.length > 0)
const solicitudEnCurso = computed(() => cargando.value || descartando.value)
const puedeCargar = computed(
  () =>
    conectado.value &&
    (capacidadCargar.value?.habilitada ?? false) &&
    archivoSeleccionado.value !== null &&
    !solicitudEnCurso.value,
)
const puedeDescartar = computed(
  () =>
    tieneOrdenDelDia.value &&
    conectado.value &&
    (capacidadDescartar.value?.habilitada ?? false) &&
    !solicitudEnCurso.value,
)
/*
  WP-070: la carga se lee con su propio contexto.

  El backend rechaza la carga fuera de PREPARANDO/SESION_ABIERTA con el código genérico
  `ESTADO_INCOMPATIBLE`, cuya redacción general no le dice al operador qué le falta hacer.
  Pasando el contexto `cargar_orden_del_dia`, la traducción compartida devuelve el texto
  exacto aprobado por HUMAN_GATE. El descarte conserva a propósito la redacción general:
  es otra capacidad y su impedimento no siempre es "todavía no preparó el recinto".
*/
const motivosCargar = computed(() =>
  traducirMotivos(capacidadCargar.value?.motivos, 'cargar_orden_del_dia'),
)
const motivosDescartar = computed(() => traducirMotivos(capacidadDescartar.value?.motivos))

function extraerMensajeError(error: unknown, mensajePorDefecto: string): string {
  if (typeof error === 'object' && error !== null) {
    if (
      'mensajeBackend' in error &&
      typeof (error as { mensajeBackend: unknown }).mensajeBackend === 'string'
    ) {
      return (error as { mensajeBackend: string }).mensajeBackend
    }
    if ('mensaje' in error && typeof (error as { mensaje: unknown }).mensaje === 'string') {
      return (error as { mensaje: string }).mensaje
    }
    if ('message' in error && typeof (error as { message: unknown }).message === 'string') {
      return (error as { message: string }).message
    }
  }
  return mensajePorDefecto
}

/** Borra el error visible antes de emitir un comando nuevo o cambiar el archivo elegido. */
function limpiarMensajes(): void {
  mensajeError.value = null
}

function manejarSeleccionArchivo(evento: Event): void {
  const entrada = evento.target as HTMLInputElement | null
  const archivo = entrada?.files?.[0] ?? null
  archivoSeleccionado.value = archivo
  limpiarMensajes()
}

async function cargarOrdenDelDia(): Promise<void> {
  const archivo = archivoSeleccionado.value
  if (!puedeCargar.value || !archivo) return
  limpiarMensajes()
  cargando.value = true
  try {
    await cliente.value.cargarOrdenDelDia(archivo)
    archivoSeleccionado.value = null
    if (inputArchivo.value) inputArchivo.value.value = ''
    // WP-048: una carga exitosa no deja acuse propio. La confirmación autoritativa es la
    // aparición de la colección proyectada por el snapshot, que reemplaza esta misma vista
    // de carga. Un renglón adicional de éxito solo restaba alto a la lista recién cargada.
    // Los errores reales sí siguen mostrándose: son la única información que el snapshot
    // no puede dar por sí mismo.
  } catch (error: unknown) {
    mensajeError.value = extraerMensajeError(error, 'No se pudo cargar el Orden del Día.')
  } finally {
    cargando.value = false
  }
}

async function descartarOrdenDelDia(): Promise<void> {
  if (!puedeDescartar.value) return
  limpiarMensajes()
  descartando.value = true
  try {
    await cliente.value.descartarOrdenDelDia()
    // WP-051: confirmación breve en vez de acuse fijo. La lista sigue visible hasta que
    // llegue el snapshot vacío, así que el aviso le dice al operador que su comando fue
    // aceptado sin ocupar el cuadrante de forma permanente.
    avisoDescarte.mostrar('Orden del Día descartado.')
  } catch (error: unknown) {
    mensajeError.value = extraerMensajeError(error, 'No se pudo descartar el Orden del Día.')
  } finally {
    descartando.value = false
  }
}

/**
 * Copiar un punto es una acción asistencial local: emite la copia y muestra el toast.
 *
 * Deliberadamente no limpia los mensajes de carga o error ya visibles. Hacerlo cambiaba
 * el alto del cuadrante justo cuando el operador hace clic y desplazaba la lista bajo el
 * cursor, que es exactamente lo que WP-044 pide evitar.
 */
function seleccionarPunto(punto: PuntoOrdenDelDiaProyectado): void {
  emit('seleccionar', { ...punto })
  avisoCopia.mostrar(`Punto Nº ${punto.nro_votacion} copiado al borrador`)
}
</script>

<template>
  <PanelContenedor
    titulo="Orden del Día"
    data-testid="panel-orden-del-dia"
    :badge="puntosOrdenDelDia.length ? `${puntosOrdenDelDia.length} puntos` : 'Sin cargar'"
    :contenido-con-scroll-propio="true"
  >
    <div class="relative flex h-full min-h-0 flex-col gap-2 text-sm text-slate-300">
      <!--
        Acuse flotante de la copia asistencial. Al estar superpuesto y sin participar del
        flujo normal, aparecer o desaparecer no cambia el alto de la lista ni su scroll.
      -->
      <div
        v-if="toastCopia"
        data-testid="toast-punto-copiado"
        role="status"
        class="pointer-events-none absolute inset-x-2 top-2 z-30 rounded-lg border border-cyan-700 bg-cyan-950/95 px-3 py-1.5 text-center text-xs font-semibold text-cyan-100 shadow-xl"
      >
        {{ toastCopia }}
      </div>
      <!--
        La carga solo existe con colección vacía. No se ofrece reemplazo directo:
        para elegir otro CSV el operador debe quitar primero el estado confirmado.
      -->
      <div
        v-if="!tieneOrdenDelDia"
        data-testid="carga-orden-dia"
        class="shrink-0 rounded-lg border border-slate-800 bg-slate-950/60 p-2.5"
      >
        <div class="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-end">
          <div class="min-w-0 flex-1">
            <label for="archivo-orden-dia" class="block text-xs font-semibold text-slate-300">
              Archivo CSV canónico
            </label>
            <input
              id="archivo-orden-dia"
              ref="inputArchivo"
              data-testid="input-archivo-orden-dia"
              type="file"
              accept=".csv,text/csv"
              class="mt-1 block w-full text-xs text-slate-300 file:mr-2 file:rounded file:border-0 file:bg-slate-700 file:px-3 file:py-1.5 file:text-slate-100"
              :disabled="solicitudEnCurso"
              @change="manejarSeleccionArchivo"
            />
          </div>
          <button
            type="button"
            data-testid="btn-cargar-orden-dia"
            class="shrink-0 rounded-lg bg-cyan-600 px-3 py-2 text-xs font-bold text-slate-950 disabled:opacity-40"
            :disabled="!puedeCargar"
            @click="cargarOrdenDelDia"
          >
            {{ cargando ? 'Cargando...' : 'Cargar' }}
          </button>
        </div>
        <p v-if="!conectado" class="text-[11px] text-amber-300">
          Los comandos quedan deshabilitados hasta recuperar la conexión confirmada.
        </p>
        <p
          v-for="motivo in motivosCargar"
          :key="`cargar-${motivo}`"
          class="text-[11px] text-amber-300"
        >
          {{ motivo }}
        </p>
      </div>

      <div
        v-if="mensajeError"
        data-testid="alerta-error-orden-dia"
        role="alert"
        class="rounded border border-rose-700 bg-rose-950/70 p-2 text-xs text-rose-200"
      >
        {{ mensajeError }}
      </div>
      <!--
        WP-051: confirmación breve del descarte. Antes era un renglón fijo que describía el
        envío HTTP; ahora caduca sola, igual que el acuse de copia.
      -->
      <div
        v-if="mensajeDescarte"
        data-testid="aviso-orden-dia"
        role="status"
        class="rounded border border-cyan-800 bg-cyan-950/50 p-2 text-xs text-cyan-200"
      >
        {{ mensajeDescarte }}
      </div>

      <!--
        La acción queda fuera del listado scrolleable. Durante el request no se oculta
        nada: solo un snapshot vacío puede reemplazar esta vista por la carga compacta.
      -->
      <div v-if="tieneOrdenDelDia" class="flex min-h-0 flex-1 flex-col gap-2">
        <div class="flex shrink-0 items-start justify-between gap-3">
          <div class="min-w-0">
            <p v-if="!conectado" class="text-[11px] text-amber-300">
              Los comandos quedan deshabilitados hasta recuperar la conexión confirmada.
            </p>
            <p
              v-for="motivo in motivosDescartar"
              :key="`descartar-${motivo}`"
              class="text-[11px] text-amber-300"
            >
              {{ motivo }}
            </p>
          </div>
          <button
            type="button"
            data-testid="btn-quitar-orden-dia"
            class="shrink-0 rounded-lg border border-rose-700 bg-rose-950 px-3 py-1.5 text-xs font-semibold text-rose-200 disabled:opacity-40"
            :disabled="!puedeDescartar"
            @click="descartarOrdenDelDia"
          >
            {{ descartando ? 'Quitando...' : 'Quitar Orden del Día' }}
          </button>
        </div>

        <div data-testid="lista-orden-dia" class="min-h-0 flex-1 space-y-1.5 overflow-y-auto pr-1">
          <!-- La clave incluye el índice porque el contrato permite números repetidos. -->
          <button
            v-for="(punto, indice) in puntosOrdenDelDia"
            :key="`${punto.nro_votacion}-${indice}`"
            type="button"
            data-testid="punto-orden-dia"
            :data-tratado="punto.tratado ? 'true' : 'false'"
            class="block w-full rounded border px-2.5 py-2 text-left text-xs hover:border-cyan-700 hover:bg-cyan-950/20"
            :class="
              punto.tratado
                ? 'border-slate-900 bg-slate-950/30 opacity-50'
                : 'border-slate-800 bg-slate-950/60'
            "
            @click="seleccionarPunto(punto)"
          >
            <span class="flex items-center justify-between gap-2">
              <strong class="text-slate-200">
                #{{ punto.nro_votacion }} · {{ punto.tipo }}
                <!--
                  La atenuación es una señal visual; sola no llega a un lector de pantalla.
                  Este texto oculto da el mismo dato sin ocupar alto ni cambiar el diseño.
                -->
                <span v-if="punto.tratado" class="sr-only">(número ya tratado en esta sesión)</span>
              </strong>
              <span class="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-300">
                {{ punto.tipo_mayoria }}
              </span>
            </span>
            <span class="mt-0.5 block text-slate-400">{{ punto.tema }}</span>
            <span
              v-if="punto.tipo_mayoria === 'ESPECIAL'"
              class="mt-0.5 block text-[10px] text-slate-500"
            >
              Factor {{ formatearFactorMayoria(punto.factor) }} · Base {{ punto.base }}
            </span>
          </button>
        </div>
      </div>
    </div>
  </PanelContenedor>
</template>
