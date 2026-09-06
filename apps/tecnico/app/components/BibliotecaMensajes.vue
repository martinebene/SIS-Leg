<script setup lang="ts">
/**
 * Administración visual de la biblioteca de mensajes precargados (WP-056).
 *
 * La biblioteca la persiste el backend en `config/apoyo-tecnico/mensajes.csv`; esta
 * pantalla sólo emite el CRUD REST y representa `EstadoTecnico.biblioteca`, que vuelve
 * por SSE después de cada escritura. Por eso no hay ninguna lista local: recargar la
 * página o abrir un segundo puesto muestra exactamente lo mismo.
 *
 * Dos comportamientos deliberados:
 *
 * - **Seleccionar un mensaje no publica nada.** Emite `cargar`, que precarga el
 *   formulario de avisos para que el operador revise texto, destino y duración antes de
 *   emitirlo. Es una decisión humana cerrada del WP.
 * - **Si el CSV no pudo interpretarse**, el backend publica `disponible: false` y rechaza
 *   toda escritura para no destruir su contenido. Acá se muestra ese motivo y se
 *   deshabilitan las acciones, en lugar de dejar que el operador choque contra un 409.
 */

import { computed, ref } from 'vue'
import type {
  BibliotecaMensajesProyectada,
  ClienteApoyoTecnico,
  DestinoAvisoTecnico,
  MensajeTecnicoProyectado,
} from '@botonera2/api-client'
import { extraerMensajeError } from '@botonera2/frontend-shared'

const props = defineProps<{
  /** Biblioteca proyectada por el backend, o `null` antes del primer snapshot. */
  biblioteca: BibliotecaMensajesProyectada | null
  /** Cliente de comandos del plano técnico. */
  cliente: ClienteApoyoTecnico
  /** Sólo una conexión confirmada habilita el CRUD. */
  conectado: boolean
}>()

const emit = defineEmits<{
  /** Pide precargar el formulario de avisos con este mensaje, sin publicarlo. */
  (evento: 'cargar', mensaje: { texto: string; destino: DestinoAvisoTecnico }): void
}>()

const LARGO_MAXIMO_TEXTO = 500

const DESTINOS: readonly DestinoAvisoTecnico[] = ['MODERACION', 'RECINTO', 'AMBOS']

/** Borrador del alta. Se limpia sólo cuando el backend confirmó la creación. */
const textoNuevo = ref('')
const destinoNuevo = ref<DestinoAvisoTecnico>('AMBOS')

/** Identificador en edición, o `null` si no se está editando ninguno. */
const editandoId = ref<string | null>(null)
const textoEditado = ref('')
const destinoEditado = ref<DestinoAvisoTecnico>('AMBOS')

const accionEnVuelo = ref<string | null>(null)
const mensajeError = ref<string | null>(null)

const mensajes = computed(() => props.biblioteca?.mensajes ?? [])
const disponible = computed(() => props.biblioteca?.disponible ?? false)
const operable = computed(() => props.conectado && disponible.value && accionEnVuelo.value === null)
const puedeCrear = computed(() => operable.value && textoNuevo.value.trim().length > 0)
const puedeGuardarEdicion = computed(() => operable.value && textoEditado.value.trim().length > 0)

async function ejecutar(
  accion: string,
  comando: () => Promise<void>,
  mensajePredeterminado: string,
): Promise<void> {
  mensajeError.value = null
  accionEnVuelo.value = accion
  try {
    await comando()
  } catch (error: unknown) {
    mensajeError.value = extraerMensajeError(error, mensajePredeterminado)
  } finally {
    accionEnVuelo.value = null
  }
}

function crear(): void {
  if (!puedeCrear.value) return
  const texto = textoNuevo.value.trim()
  const destino = destinoNuevo.value
  void ejecutar(
    'CREAR',
    async () => {
      await props.cliente.crearMensaje(texto, destino)
      // El borrador se limpia recién con la confirmación del backend: si la creación
      // falla, el operador conserva lo que escribió y puede reintentar.
      textoNuevo.value = ''
    },
    'No se pudo crear el mensaje precargado.',
  )
}

function comenzarEdicion(mensaje: MensajeTecnicoProyectado): void {
  editandoId.value = mensaje.mensaje_id
  textoEditado.value = mensaje.texto
  destinoEditado.value = mensaje.destino
  mensajeError.value = null
}

function cancelarEdicion(): void {
  editandoId.value = null
  textoEditado.value = ''
}

function guardarEdicion(): void {
  const id = editandoId.value
  if (!puedeGuardarEdicion.value || id === null) return
  const texto = textoEditado.value.trim()
  const destino = destinoEditado.value
  void ejecutar(
    'EDITAR',
    async () => {
      await props.cliente.actualizarMensaje(id, texto, destino)
      cancelarEdicion()
    },
    'No se pudo editar el mensaje precargado.',
  )
}

function eliminar(mensaje: MensajeTecnicoProyectado): void {
  if (!operable.value) return
  void ejecutar(
    'ELIMINAR',
    async () => {
      await props.cliente.eliminarMensaje(mensaje.mensaje_id)
      if (editandoId.value === mensaje.mensaje_id) cancelarEdicion()
    },
    'No se pudo eliminar el mensaje precargado.',
  )
}

function cargar(mensaje: MensajeTecnicoProyectado): void {
  emit('cargar', { texto: mensaje.texto, destino: mensaje.destino })
}
</script>

<template>
  <div data-testid="biblioteca-mensajes" class="space-y-3 text-xs">
    <p
      v-if="biblioteca && !disponible"
      data-testid="biblioteca-no-disponible"
      class="rounded border border-rose-700 bg-rose-950/60 px-2 py-1 text-rose-200"
      role="alert"
    >
      La biblioteca no pudo interpretarse y no admite cambios.
      <span v-if="biblioteca.detalle" data-testid="detalle-biblioteca" class="block text-rose-300">
        {{ biblioteca.detalle }}
      </span>
    </p>

    <!-- Alta -->
    <div class="space-y-1 rounded border border-slate-800 bg-slate-950/70 p-2">
      <label for="texto-mensaje-nuevo" class="block font-semibold text-slate-300">
        Nuevo mensaje precargado
      </label>
      <input
        id="texto-mensaje-nuevo"
        v-model="textoNuevo"
        data-testid="input-mensaje-nuevo"
        type="text"
        :maxlength="LARGO_MAXIMO_TEXTO"
        class="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-slate-100 disabled:opacity-50"
        placeholder="Texto que quedará guardado para reutilizar"
        :disabled="!operable"
      />
      <div class="flex items-center gap-2">
        <select
          v-model="destinoNuevo"
          data-testid="select-destino-nuevo"
          aria-label="Destino del nuevo mensaje precargado"
          class="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-slate-100 disabled:opacity-50"
          :disabled="!operable"
        >
          <option v-for="valor in DESTINOS" :key="valor" :value="valor">{{ valor }}</option>
        </select>
        <button
          type="button"
          data-testid="btn-crear-mensaje"
          class="rounded-lg border border-emerald-700 bg-emerald-950 px-3 py-1.5 font-bold text-emerald-200 disabled:cursor-not-allowed disabled:opacity-40"
          :disabled="!puedeCrear"
          @click="crear"
        >
          {{ accionEnVuelo === 'CREAR' ? 'Creando...' : 'Crear' }}
        </button>
      </div>
    </div>

    <!-- Listado con acciones por mensaje -->
    <ul v-if="mensajes.length" data-testid="lista-mensajes" class="space-y-1.5">
      <li
        v-for="mensaje in mensajes"
        :key="mensaje.mensaje_id"
        data-testid="mensaje-precargado"
        :data-mensaje-id="mensaje.mensaje_id"
        class="rounded border border-slate-800 bg-slate-950/70 p-2"
      >
        <template v-if="editandoId === mensaje.mensaje_id">
          <input
            v-model="textoEditado"
            data-testid="input-mensaje-editado"
            type="text"
            :maxlength="LARGO_MAXIMO_TEXTO"
            aria-label="Texto del mensaje precargado en edición"
            class="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-slate-100"
          />
          <div class="mt-1 flex flex-wrap items-center gap-2">
            <select
              v-model="destinoEditado"
              data-testid="select-destino-editado"
              aria-label="Destino del mensaje precargado en edición"
              class="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-slate-100"
            >
              <option v-for="valor in DESTINOS" :key="valor" :value="valor">{{ valor }}</option>
            </select>
            <button
              type="button"
              data-testid="btn-guardar-mensaje"
              class="rounded border border-emerald-700 bg-emerald-950 px-2 py-1 font-bold text-emerald-200 disabled:cursor-not-allowed disabled:opacity-40"
              :disabled="!puedeGuardarEdicion"
              @click="guardarEdicion"
            >
              Guardar
            </button>
            <button
              type="button"
              data-testid="btn-cancelar-edicion"
              class="rounded border border-slate-600 bg-slate-900 px-2 py-1 font-bold text-slate-200"
              @click="cancelarEdicion"
            >
              Cancelar
            </button>
          </div>
        </template>

        <template v-else>
          <p data-testid="texto-mensaje" class="break-words text-slate-200">{{ mensaje.texto }}</p>
          <!--
            WP-070 + WP-076: destino + las tres acciones entran en un solo renglón, con el
            destino pegado a la izquierda y las acciones agrupadas contra la derecha.

            La fila tiene exactamente dos hijos: la etiqueta de destino y un subcontenedor
            con los tres botones. Ese par es lo que permite usar `justify-between`, que es
            la forma declarativa de decir "uno a cada extremo del ancho disponible" sin
            inventar anchos fijos ni separadores elásticos: el espacio sobrante se reparte
            entre los dos bloques, no entre los cuatro controles. Antes los cuatro
            elementos eran hermanos directos y quedaban todos apelmazados a la izquierda.

            La fila conserva `flex-wrap` a propósito. El envoltorio es la salida
            defensiva por debajo de las resoluciones canónicas —donde la grilla ya se
            apila en una columna— y no la disposición normal: a 1366×768 y 1920×1080 el
            ancho alcanza y nada envuelve. Lo que cambia es el presupuesto de ancho: los
            botones bajan a 10 px (el mismo cuerpo que la etiqueta de destino) con menos
            relleno horizontal, y la separación pasa de 8 px a 6 px. El alto no se mueve,
            porque el interlineado lo sigue fijando el `text-xs` del contenedor.

            `whitespace-nowrap` es lo que garantiza el criterio "no se recorta su texto":
            un botón sin ancho suficiente desborda de forma medible en lugar de partir su
            rótulo en dos líneas, así que la prueba de geometría lo detecta.
          -->
          <div
            data-testid="acciones-mensaje"
            class="mt-1 flex flex-wrap items-center justify-between gap-1.5"
          >
            <span
              data-testid="destino-mensaje"
              class="shrink-0 whitespace-nowrap rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 text-[10px] font-bold text-slate-400"
            >
              {{ mensaje.destino }}
            </span>
            <!--
              Grupo derecho de acciones (WP-076).

              `ml-auto` es lo que sostiene la alineación derecha también cuando la fila
              envuelve por debajo de las resoluciones canónicas: ahí el grupo queda solo en
              su renglón, `justify-between` ya no tiene contra qué separarlo y el margen
              automático se come el espacio sobrante. A las resoluciones canónicas es
              inocuo, porque `justify-between` ya lo había llevado al extremo.

              `flex-wrap` acá adentro es el último recurso adaptable: si ni siquiera el
              grupo entra en un renglón, se apila entre sus propios botones —alineados a la
              derecha por `justify-end`— en lugar de desbordar el panel.
            -->
            <div
              data-testid="grupo-acciones-mensaje"
              class="ml-auto flex flex-wrap items-center justify-end gap-1.5"
            >
              <button
                type="button"
                data-testid="btn-cargar-mensaje"
                class="shrink-0 whitespace-nowrap rounded border border-sky-700 bg-sky-950 px-1.5 py-1 text-[10px] font-bold text-sky-200"
                @click="cargar(mensaje)"
              >
                Usar en el formulario
              </button>
              <button
                type="button"
                data-testid="btn-editar-mensaje"
                class="shrink-0 whitespace-nowrap rounded border border-slate-600 bg-slate-900 px-1.5 py-1 text-[10px] font-bold text-slate-200 disabled:cursor-not-allowed disabled:opacity-40"
                :disabled="!operable"
                @click="comenzarEdicion(mensaje)"
              >
                Editar
              </button>
              <button
                type="button"
                data-testid="btn-eliminar-mensaje"
                class="shrink-0 whitespace-nowrap rounded border border-rose-700 bg-rose-950 px-1.5 py-1 text-[10px] font-bold text-rose-200 disabled:cursor-not-allowed disabled:opacity-40"
                :disabled="!operable"
                @click="eliminar(mensaje)"
              >
                Eliminar
              </button>
            </div>
          </div>
        </template>
      </li>
    </ul>

    <p
      v-else
      data-testid="biblioteca-vacia"
      class="rounded border border-dashed border-slate-800 px-2 py-2 text-center text-slate-400"
    >
      No hay mensajes precargados
    </p>

    <p
      v-if="mensajeError"
      data-testid="error-biblioteca"
      class="rounded border border-rose-700 bg-rose-950/60 px-2 py-1 text-rose-200"
      role="alert"
    >
      {{ mensajeError }}
    </p>
  </div>
</template>
