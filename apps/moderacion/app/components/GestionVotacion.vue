<script setup lang="ts">
/**
 * Gestiona el ciclo visual de una votación dentro de una sesión abierta.
 *
 * El componente conserva solamente datos de interfaz: borrador editable, motivo de
 * finalización, advertencia CA-062 y comandos en vuelo. La votación visible, sus votos,
 * conteos y resultado siempre se leen desde `EstadoModeracion`; por eso una recarga o
 * reconexión reconstruye la pantalla sin timers ni cálculos institucionales locales.
 * WP-037 decide además que Q1 nunca renderice la lista individual, aunque el DTO la
 * incluya: este componente presenta solamente resultado y conteos agregados.
 *
 * WP-048 compacta esa presentación. El cuerpo normal ya no informa de forma permanente
 * quién tiene la palabra ni cuántos pedidos hay en cola: esa información es continua, vive
 * en Q3 (banca resaltada del orador y badge/lista de la cola) y repetirla acá gastaba una
 * fila de Q1 en cada votación. La advertencia que aparece al intentar abrir una votación
 * con palabra pendiente (CA-062, `DialogoConfirmacionApertura`) se conserva intacta:
 * es una salvaguarda del momento del comando, no un indicador permanente.
 *
 * WP-051 aplica acá la política de feedback aprobada:
 *
 * - Los tres acuses de tránsito HTTP que existían ("Apertura enviada…", "Finalización
 *   enviada…", "Desempate enviado…") desaparecen. Eran puramente técnicos: describían que
 *   una petición había salido, no un hecho institucional. Cada una de esas tres mutaciones
 *   ya queda registrada por el backend en la auditoría CSV (`VOTACION_ABIERTA`,
 *   `VOTACION_FINALIZADA_*`, `VOTO_DESEMPATE_PRESIDENCIAL`) y su efecto real se ve en el
 *   propio snapshot: la votación aparece EN_CURSO, aparece el resultado, cambia el
 *   resultado tras el desempate. Nada de eso necesitaba un cartel superpuesto que además
 *   quedaba visible indefinidamente sobre la pantalla de trabajo.
 * - Los errores sí siguen mostrándose: son la única información que el snapshot no puede
 *   dar por sí mismo.
 * - El motivo de finalización se vacía únicamente después de una finalización aceptada.
 *   Si el backend rechaza el comando, el texto tipeado se conserva para reintentar.
 *
 * WP-057 compacta la estructura del formulario. Número, Tipo, Mayoría, Factor y Base
 * pasan a compartir una única fila en desktop, de modo que elegir mayoría ESPECIAL ya no
 * agrega una segunda fila de campos. Ese renglón adicional era la causa medida de que,
 * con el resultado de la votación anterior todavía visible, los controles de apertura
 * quedaran fuera del área visible de Q1 a 1366×768. El formulario no cambia de reglas ni
 * de validaciones: sólo deja de crecer a lo alto cuando la mayoría es especial.
 *
 * WP-090 limita a tres líneas únicamente el tema de la votación proyectada. Si el texto
 * necesita más espacio, ese encabezado conserva el contenido completo y ofrece scroll
 * vertical propio, sin agrandar la tarjeta ni desplazar el formulario siguiente.
 */

import { computed, ref, watch } from 'vue'
import type {
  BaseMayoria,
  Capacidad,
  ClienteModeracion,
  EstadoModeracion,
  PuntoOrdenDelDiaProyectado,
  SolicitudAperturaVotacion,
} from '@sis-leg/api-client'
// WP-063: sólo el rótulo de la regla vigente usa el formato truncado. El campo editable
// del formulario sigue trabajando con el texto real que tipeó el operador o que copió el
// Orden del Día, porque ese es el valor que después se envía al backend.
import { formatearFactorMayoria } from '@sis-leg/frontend-shared'
import { traducirMotivos } from '../utils/motivos'
import DialogoConfirmacionApertura from './DialogoConfirmacionApertura.vue'

const props = defineProps<{
  estado: EstadoModeracion
  cliente: ClienteModeracion
  conectado: boolean
  puntoPreseleccionado: PuntoOrdenDelDiaProyectado | null
}>()

type TipoMayoriaFormulario = 'SIMPLE' | 'ESPECIAL'

interface BorradorVotacion {
  numero: string
  tipo: string
  tema: string
  tipoMayoria: TipoMayoriaFormulario
  factor: string
  base: BaseMayoria
}

const borrador = ref<BorradorVotacion>({
  numero: '',
  tipo: '',
  tema: '',
  tipoMayoria: 'SIMPLE',
  factor: '',
  base: 'VOTOS_COMPUTABLES',
})

const motivoFinalizacion = ref('')
const mensajeError = ref<string | null>(null)
const abriendo = ref(false)
const finalizando = ref(false)
const desempatando = ref(false)
const aperturaPendiente = ref<SolicitudAperturaVotacion | null>(null)
const idAperturaSolicitada = ref<string | null>(null)

const tiposConfigurados = computed(() => props.estado.configuracion?.tipos_votacion ?? [])
const votacion = computed(() => props.estado.votacion)
const capacidadNoProyectada: Capacidad = {
  habilitada: false,
  motivos: ['ESTADO_INCOMPATIBLE'],
}

/**
 * Una votación final ya no bloquea una apertura nueva aunque siga siendo la última
 * proyectada. En cambio EN_CURSO, EMPATADA y el estado técnico CERRADA sin resultado
 * continúan siendo incompatibles según las capacidades del backend.
 */
const existeVotacionIncompatible = computed(() => {
  const actual = votacion.value
  if (!actual) return false
  return (
    actual.estado_recepcion === 'EN_CURSO' ||
    actual.resultado === 'EMPATADA' ||
    (actual.estado_recepcion === 'CERRADA' && actual.resultado === null)
  )
})

const mostrarFormulario = computed(
  () => props.estado.estado_global === 'SESION_ABIERTA' && !existeVotacionIncompatible.value,
)

const capacidadAbrir = computed(
  () => props.estado.capacidades.abrir_votacion ?? capacidadNoProyectada,
)
const capacidadFinalizar = computed(
  () => props.estado.capacidades.finalizar_votacion ?? capacidadNoProyectada,
)
const capacidadDesempatar = computed(
  () => props.estado.capacidades.desempatar ?? capacidadNoProyectada,
)

const puedeEnviarApertura = computed(
  () => props.conectado && capacidadAbrir.value.habilitada && !abriendo.value,
)
const puedeFinalizar = computed(
  () => props.conectado && capacidadFinalizar.value.habilitada && !finalizando.value,
)
const puedeDesempatar = computed(
  () => props.conectado && capacidadDesempatar.value.habilitada && !desempatando.value,
)

// WP-051: los motivos de `abrir_votacion` se traducen con su contexto propio. Durante una
// sesión abierta, `QUORUM_INSUFICIENTE` impide poner una votación en marcha, no "abrir la
// sesión": esa era la lectura equivocada que reportó la prueba humana del 01/09/2026.
const motivosAbrir = computed(() => traducirMotivos(capacidadAbrir.value.motivos, 'abrir_votacion'))
const motivosFinalizar = computed(() => traducirMotivos(capacidadFinalizar.value.motivos))
const motivosDesempatar = computed(() => traducirMotivos(capacidadDesempatar.value.motivos))

const resultadoClase = computed(() => {
  switch (votacion.value?.resultado) {
    case 'APROBADA':
      return 'border-emerald-600 bg-emerald-950/60 text-emerald-200'
    case 'RECHAZADA':
      return 'border-rose-600 bg-rose-950/60 text-rose-200'
    case 'INCONCLUSA':
      return 'border-slate-500 bg-slate-800/80 text-slate-200'
    case 'EMPATADA':
      return 'border-amber-500 bg-amber-950/60 text-amber-200'
    default:
      return 'border-cyan-700 bg-cyan-950/40 text-cyan-200'
  }
})

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

/**
 * Borra el único feedback persistente del componente antes de emitir un comando nuevo.
 *
 * WP-051: acá ya no hay avisos informativos que limpiar. El error anterior sí debe
 * desaparecer, porque de lo contrario un fallo viejo seguiría acusando a un comando que
 * el operador acaba de reintentar.
 */
function limpiarMensajes(): void {
  mensajeError.value = null
}

function reiniciarBorradorManual(): void {
  borrador.value = {
    numero: '',
    tipo: tiposConfigurados.value[0] ?? '',
    tema: '',
    tipoMayoria: 'SIMPLE',
    factor: '',
    base: 'VOTOS_COMPUTABLES',
  }
}

/**
 * Copia los seis campos normalizados de Q2. Como el Orden del Día no valida el tipo
 * contra la configuración, un tipo no permitido queda visible en el select como opción
 * deshabilitada hasta que el operador elija uno vigente.
 */
watch(
  () => props.puntoPreseleccionado,
  (punto) => {
    if (!punto) return
    const tipoMayoria: TipoMayoriaFormulario =
      punto.tipo_mayoria === 'ESPECIAL' ? 'ESPECIAL' : 'SIMPLE'
    const basesPermitidas: BaseMayoria[] = ['VOTOS_COMPUTABLES', 'PRESENTES', 'CUERPO']
    const base = basesPermitidas.includes(punto.base as BaseMayoria)
      ? (punto.base as BaseMayoria)
      : 'VOTOS_COMPUTABLES'

    borrador.value = {
      numero: String(punto.nro_votacion),
      tipo: punto.tipo,
      tema: punto.tema,
      tipoMayoria,
      factor: tipoMayoria === 'ESPECIAL' ? String(punto.factor) : '',
      base: tipoMayoria === 'ESPECIAL' ? base : 'VOTOS_COMPUTABLES',
    }
    // WP-044: el acuse de la copia vive exclusivamente en el toast de Q2. Repetirlo acá
    // producía dos avisos simultáneos para un mismo gesto del operador.
    limpiarMensajes()
  },
)

watch(
  tiposConfigurados,
  (tipos) => {
    if (!borrador.value.tipo && tipos[0]) borrador.value.tipo = tipos[0]
  },
  { immediate: true },
)

/**
 * La respuesta 201 permite recordar qué apertura está esperando proyección, pero no se
 * usa para dibujar una votación optimista. El borrador se limpia recién cuando un snapshot
 * confirma la misma id en EN_CURSO.
 */
watch(
  () => props.estado.votacion,
  (actual) => {
    if (
      actual &&
      actual.id === idAperturaSolicitada.value &&
      actual.estado_recepcion === 'EN_CURSO'
    ) {
      idAperturaSolicitada.value = null
      reiniciarBorradorManual()
    }
  },
)

function manejarCambioTipoMayoria(): void {
  if (borrador.value.tipoMayoria === 'SIMPLE') {
    borrador.value.factor = ''
    borrador.value.base = 'VOTOS_COMPUTABLES'
  }
}

function construirSolicitud(): SolicitudAperturaVotacion | null {
  const numeroTexto = borrador.value.numero.trim()
  if (!/^\d+$/.test(numeroTexto)) {
    mensajeError.value = 'El número de votación debe ser un entero estricto mayor o igual a 1.'
    return null
  }

  const numero = Number(numeroTexto)
  if (!Number.isSafeInteger(numero) || numero < 1) {
    mensajeError.value = 'El número de votación debe ser un entero estricto mayor o igual a 1.'
    return null
  }

  const tipo = borrador.value.tipo.trim()
  if (!tiposConfigurados.value.includes(tipo)) {
    mensajeError.value = 'Elegí un tipo de votación de la configuración vigente.'
    return null
  }

  const tema = borrador.value.tema.trim()
  if (!tema) {
    mensajeError.value = 'El tema de la votación no puede quedar vacío.'
    return null
  }

  if (borrador.value.tipoMayoria === 'SIMPLE') {
    return {
      numero_votacion: numero,
      tipo,
      tema,
      tipo_mayoria: 'SIMPLE',
      base: 'VOTOS_COMPUTABLES',
    }
  }

  const factorTexto = borrador.value.factor.trim()
  const patronNumeroDecimal = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/
  const factor = Number(factorTexto)
  if (
    !patronNumeroDecimal.test(factorTexto) ||
    !Number.isFinite(factor) ||
    factor <= 0 ||
    factor > 1
  ) {
    mensajeError.value =
      'El factor especial debe ser un número finito mayor que 0 y menor o igual a 1.'
    return null
  }

  return {
    numero_votacion: numero,
    tipo,
    tema,
    tipo_mayoria: 'ESPECIAL',
    factor,
    base: borrador.value.base,
  }
}

async function enviarApertura(solicitud: SolicitudAperturaVotacion): Promise<void> {
  if (!puedeEnviarApertura.value) {
    mensajeError.value = props.conectado
      ? 'El backend no habilita la apertura en el estado vigente.'
      : 'No se puede abrir una votación sin conexión confirmada.'
    return
  }

  abriendo.value = true
  aperturaPendiente.value = null
  try {
    const respuesta = await props.cliente.abrirVotacion(solicitud)
    // Recordamos la id aceptada para poder limpiar el borrador recién cuando el snapshot
    // confirme esa misma votación EN_CURSO. WP-051: no se muestra ningún acuse propio,
    // porque la aparición de la votación proyectada ya es la confirmación visible.
    idAperturaSolicitada.value = respuesta.id
  } catch (error: unknown) {
    mensajeError.value = extraerMensajeError(error, 'No se pudo abrir la votación.')
  } finally {
    abriendo.value = false
  }
}

function solicitarApertura(): void {
  if (!puedeEnviarApertura.value) return
  limpiarMensajes()
  const solicitud = construirSolicitud()
  if (!solicitud) return

  const hayPalabraPendiente =
    (props.estado.palabra?.orador ?? null) !== null || (props.estado.palabra?.cola.length ?? 0) > 0
  if (hayPalabraPendiente) {
    aperturaPendiente.value = { ...solicitud }
    return
  }
  void enviarApertura(solicitud)
}

function cancelarAdvertenciaApertura(): void {
  if (abriendo.value) return
  aperturaPendiente.value = null
}

function confirmarAdvertenciaApertura(): void {
  const solicitud = aperturaPendiente.value
  if (!solicitud || abriendo.value) return
  void enviarApertura(solicitud)
}

async function finalizarVotacion(): Promise<void> {
  const actual = votacion.value
  if (!actual || actual.estado_recepcion !== 'EN_CURSO' || !puedeFinalizar.value) return
  limpiarMensajes()
  const motivo = motivoFinalizacion.value.trim()
  if (!motivo) {
    mensajeError.value = 'Ingresá un motivo antes de finalizar la votación.'
    return
  }

  finalizando.value = true
  try {
    await props.cliente.finalizarVotacion(actual.id, motivo)
    // WP-051: el motivo se vacía únicamente acá, después de que el backend aceptó la
    // finalización. Si el comando falla, el texto tipeado sobrevive para reintentarlo sin
    // obligar al operador a volver a escribirlo.
    motivoFinalizacion.value = ''
  } catch (error: unknown) {
    mensajeError.value = extraerMensajeError(error, 'No se pudo finalizar la votación.')
  } finally {
    finalizando.value = false
  }
}

async function desempatar(sentido: 'POSITIVO' | 'NEGATIVO'): Promise<void> {
  const actual = votacion.value
  if (
    !actual ||
    actual.estado_recepcion !== 'CERRADA' ||
    actual.resultado !== 'EMPATADA' ||
    actual.tipo_mayoria !== 'SIMPLE' ||
    !puedeDesempatar.value
  ) {
    return
  }

  limpiarMensajes()
  desempatando.value = true
  try {
    await props.cliente.desempatar(actual.id, sentido)
  } catch (error: unknown) {
    mensajeError.value = extraerMensajeError(error, 'No se pudo registrar el desempate.')
  } finally {
    desempatando.value = false
  }
}
</script>

<template>
  <section data-testid="gestion-votacion" class="min-h-0 space-y-2">
    <div
      v-if="mensajeError"
      data-testid="alerta-error-votacion"
      class="fixed top-16 right-4 z-40 max-w-md rounded-lg border border-rose-700 bg-rose-950/95 p-2 text-xs text-rose-200 shadow-xl"
      role="alert"
    >
      {{ mensajeError }}
    </div>

    <!-- Vista de la votación relevante, construida exclusivamente desde el snapshot. -->
    <article
      v-if="votacion"
      data-testid="vista-votacion-proyectada"
      class="space-y-2 rounded-lg border border-slate-700 bg-slate-950/70 p-2"
    >
      <div class="flex flex-wrap items-start justify-between gap-2">
        <div class="min-w-0 flex-1">
          <p class="text-[10px] font-bold uppercase tracking-wider text-slate-400">
            Votación Nº {{ votacion.numero_votacion }} · {{ votacion.tipo }}
          </p>
          <!--
            WP-090: el tema conserva todo su texto, pero sólo este bloque puede crecer hasta
            tres líneas. `tabindex` permite recorrer con teclado el excedente que habilita
            `overflow-y: auto`; el formulario y la tarjeta completa no reciben scroll.
          -->
          <h4
            data-testid="tema-votacion-proyectada"
            class="tema-votacion-proyectada font-semibold text-slate-100"
            tabindex="0"
          >
            {{ votacion.tema }}
          </h4>
        </div>
        <!--
          WP-044: con la votación cerrada, el resultado deja de ser un badge más y pasa a
          ser la señal dominante del cuadrante. `data-jerarquia` expresa esa decisión de
          forma verificable, sin depender de comparar clases de Tailwind en las pruebas.
          Mientras la recepción sigue EN_CURSO conserva el tamaño compacto: allí el dato
          relevante son los controles, no un estado todavía provisorio.
        -->
        <span
          data-testid="estado-votacion"
          :data-jerarquia="votacion.resultado ? 'principal' : 'secundaria'"
          class="rounded border text-center leading-none"
          :class="[
            resultadoClase,
            votacion.resultado
              ? 'px-3 py-1.5 text-2xl font-black uppercase tracking-wide xl:text-3xl'
              : 'px-2 py-0.5 text-[11px] font-bold',
          ]"
        >
          {{ votacion.resultado ?? votacion.estado_recepcion }}
        </span>
      </div>

      <!--
        WP-048: el contexto de la regla vigente ocupa un solo renglón. Antes eran tres
        tarjetas apiladas de etiqueta sobre valor: la misma información pedía casi el doble
        de alto sin agregar nada, y esa altura le faltaba al formulario de la votación
        siguiente. `cantidad-votos-recibidos` conserva su identificador y sigue conteniendo
        únicamente el número, porque las pruebas integradas comparan ese valor exacto.
      -->
      <dl
        v-if="votacion.estado_recepcion === 'EN_CURSO'"
        class="flex flex-wrap items-center gap-x-3 gap-y-0.5 rounded bg-slate-900 px-2 py-0.5 text-[11px] leading-tight"
      >
        <div class="flex items-center gap-1">
          <dt class="text-slate-500">Mayoría</dt>
          <dd class="font-semibold text-slate-200">{{ votacion.tipo_mayoria }}</dd>
        </div>
        <div class="flex items-center gap-1">
          <dt class="text-slate-500">Regla</dt>
          <dd class="font-semibold text-slate-200">
            <template v-if="votacion.tipo_mayoria === 'ESPECIAL'">
              {{ formatearFactorMayoria(votacion.factor) }} · {{ votacion.base }}
            </template>
            <template v-else>Positivos &gt; negativos</template>
          </dd>
        </div>
        <div class="flex items-center gap-1">
          <dt class="text-slate-500">Votos recibidos</dt>
          <dd data-testid="cantidad-votos-recibidos" class="font-semibold text-slate-200">
            {{ votacion.cantidad_votos_recibidos }}
          </dd>
        </div>
      </dl>

      <!--
        WP-048: los conteos agregados son información secundaria y se leen en una única
        fila. Las cuatro tarjetas altas anteriores competían visualmente con el cartel de
        resultado, que es el dato dominante del cuadrante, y empujaban el formulario fuera
        del área visible. Se conservan la familia de color de cada valor (convención de
        producción verificada en WP-044) y los identificadores de prueba.
      -->
      <dl
        v-if="votacion.conteos"
        data-testid="conteos-votacion"
        class="flex flex-wrap items-center gap-1 text-[11px] leading-tight"
      >
        <div
          data-testid="conteo-positivos"
          class="flex items-center gap-1 rounded bg-emerald-950/60 px-1.5 py-0.5 text-emerald-200"
        >
          <dt>Positivos</dt>
          <dd class="font-bold">{{ votacion.conteos.positivos }}</dd>
        </div>
        <div
          data-testid="conteo-negativos"
          class="flex items-center gap-1 rounded bg-rose-950/60 px-1.5 py-0.5 text-rose-200"
        >
          <dt>Negativos</dt>
          <dd class="font-bold">{{ votacion.conteos.negativos }}</dd>
        </div>
        <div
          data-testid="conteo-abstenciones"
          class="flex items-center gap-1 rounded bg-amber-950/60 px-1.5 py-0.5 text-amber-200"
        >
          <dt>Abstenciones</dt>
          <dd class="font-bold">{{ votacion.conteos.abstenciones }}</dd>
        </div>
        <div
          data-testid="conteo-total"
          class="flex items-center gap-1 rounded bg-cyan-950/60 px-1.5 py-0.5 text-cyan-200"
        >
          <dt>Total</dt>
          <dd class="font-bold">{{ votacion.conteos.total }}</dd>
        </div>
      </dl>

      <p
        v-if="votacion.estado_recepcion === 'EN_CURSO'"
        data-testid="votos-ocultos"
        class="text-[11px] italic leading-tight text-slate-400"
      >
        Los votos individuales permanecen ocultos en este cuadrante.
      </p>

      <div v-if="votacion.estado_recepcion === 'EN_CURSO'" class="border-t border-slate-800 pt-2">
        <div class="flex flex-col gap-2 sm:flex-row">
          <input
            id="motivo-finalizacion"
            v-model="motivoFinalizacion"
            data-testid="input-motivo-finalizacion"
            type="text"
            class="min-w-0 flex-1 rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-xs text-slate-100"
            placeholder="Motivo obligatorio para finalizar"
            aria-label="Motivo para finalizar manualmente"
            :disabled="finalizando"
          />
          <button
            type="button"
            data-testid="btn-finalizar-votacion"
            class="rounded border border-rose-700 bg-rose-950 px-3 py-1.5 text-[11px] font-bold text-rose-200 disabled:opacity-40"
            :disabled="!puedeFinalizar"
            @click="finalizarVotacion"
          >
            {{ finalizando ? 'Finalizando...' : 'Finalizar votación' }}
          </button>
        </div>
        <p v-for="motivo in motivosFinalizar" :key="motivo" class="text-[11px] text-amber-300">
          {{ motivo }}
        </p>
      </div>

      <div
        v-if="
          votacion.estado_recepcion === 'CERRADA' &&
          votacion.resultado === 'EMPATADA' &&
          votacion.tipo_mayoria === 'SIMPLE'
        "
        data-testid="controles-desempate"
        class="flex flex-wrap items-center gap-2 rounded border border-amber-700 bg-amber-950/30 p-2"
      >
        <!--
          WP-051: el empate deja de comunicarse sólo con un badge y dos botones sueltos.
          La instrucción explícita precede siempre a POSITIVO/NEGATIVO para que el operador
          entienda de quién es la acción pendiente. El texto es el aprobado por HUMAN_GATE y
          no altera `puedeDesempatar`: la autoridad sobre si el desempate está habilitado
          sigue siendo exclusivamente la capacidad publicada por el backend.
        -->
        <p
          data-testid="instruccion-desempate"
          class="w-full text-xs font-semibold leading-tight text-amber-100"
        >
          Votación empatada. La Presidencia debe emitir el voto de desempate:
        </p>
        <p class="min-w-0 flex-1 text-[11px] text-amber-200">
          Presidencia vigente: <strong>{{ estado.sesion?.presidencia }}</strong>
        </p>
        <div class="flex gap-1.5">
          <button
            type="button"
            data-testid="btn-desempate-positivo"
            class="rounded bg-emerald-600 px-3 py-1.5 text-[11px] font-bold text-slate-950 disabled:opacity-40"
            :disabled="!puedeDesempatar"
            @click="desempatar('POSITIVO')"
          >
            POSITIVO
          </button>
          <button
            type="button"
            data-testid="btn-desempate-negativo"
            class="rounded bg-rose-600 px-3 py-1.5 text-[11px] font-bold text-white disabled:opacity-40"
            :disabled="!puedeDesempatar"
            @click="desempatar('NEGATIVO')"
          >
            NEGATIVO
          </button>
        </div>
        <p
          v-for="motivo in motivosDesempatar"
          :key="motivo"
          class="w-full text-[11px] text-amber-300"
        >
          {{ motivo }}
        </p>
      </div>
    </article>

    <!-- Formulario manual o precargado. Una votación final anterior puede convivir con este borrador. -->
    <form
      v-if="mostrarFormulario"
      data-testid="formulario-votacion"
      class="space-y-2 rounded-lg border border-cyan-900/60 bg-slate-950/60 p-2"
      @submit.prevent="solicitarApertura"
    >
      <div class="flex items-center justify-between">
        <h4 class="text-xs font-bold uppercase tracking-wider text-cyan-300">Nueva votación</h4>
        <button
          type="button"
          data-testid="btn-limpiar-borrador"
          class="text-[11px] text-slate-400 underline"
          @click="reiniciarBorradorManual"
        >
          Limpiar borrador
        </button>
      </div>

      <!--
        WP-057: fila única de la regla de mayoría.

        Antes había dos filas: `Número | Tipo | Mayoría` y, sólo con ESPECIAL, una
        segunda con `Factor | Base`. Esa segunda fila costaba ~52 px (44 px de campos
        más el espacio entre filas) y era exactamente la altura que expulsaba los
        controles de apertura fuera del área visible de Q1 cuando todavía se estaba
        leyendo el resultado de la votación anterior a 1366×768.

        Ahora los cinco campos comparten un único renglón en desktop (`sm:flex-nowrap`).
        Factor y Base entran en el hueco que ya sobraba a la derecha, así que elegir
        ESPECIAL no agrega alto estructural: el formulario mide lo mismo con SIMPLE y
        con ESPECIAL. Por debajo del breakpoint `sm` la fila se apila en columna, que
        es el comportamiento razonable cuando no hay ancho para cinco controles.

        Reparto del ancho: Número y Factor son numéricos cortos y llevan ancho fijo;
        Tipo y Base son selects de texto variable y absorben el sobrante. El grupo de
        mayoría especial pesa 2 contra 1 de Tipo porque adentro carga además el ancho
        fijo de Factor: sin esa compensación Base quedaba angosta y recortaba la opción
        más larga (`VOTOS_COMPUTABLES`). `items-end` alinea todos los controles por su
        base aunque los rótulos tengan distinta altura, de modo que la fila se lee como
        una sola línea.

        `fila-regla-mayoria` identifica el renglón para poder medir su rectángulo real en
        las pruebas de geometría, que es la evidencia que exige el WP.
      -->
      <div
        data-testid="fila-regla-mayoria"
        class="flex flex-col gap-2 sm:flex-row sm:flex-nowrap sm:items-end"
      >
        <label class="text-xs text-slate-300 sm:w-16 sm:shrink-0">
          Número
          <input
            v-model="borrador.numero"
            data-testid="input-numero-votacion"
            type="text"
            inputmode="numeric"
            class="mt-0.5 w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-slate-100"
          />
        </label>
        <label class="min-w-0 text-xs text-slate-300 sm:flex-1">
          Tipo
          <select
            v-model="borrador.tipo"
            data-testid="select-tipo-votacion"
            class="mt-0.5 w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-slate-100"
          >
            <option
              v-if="borrador.tipo && !tiposConfigurados.includes(borrador.tipo)"
              :value="borrador.tipo"
              disabled
            >
              {{ borrador.tipo }} (no permitido en esta sesión)
            </option>
            <option v-for="tipo in tiposConfigurados" :key="tipo" :value="tipo">{{ tipo }}</option>
          </select>
        </label>
        <fieldset class="sm:shrink-0">
          <legend class="text-xs text-slate-300">Mayoría</legend>
          <div class="mt-1 flex gap-2 text-xs">
            <label class="flex items-center gap-1">
              <input
                v-model="borrador.tipoMayoria"
                data-testid="radio-mayoria-simple"
                type="radio"
                value="SIMPLE"
                @change="manejarCambioTipoMayoria"
              />
              SIMPLE
            </label>
            <label class="flex items-center gap-1">
              <input
                v-model="borrador.tipoMayoria"
                data-testid="radio-mayoria-especial"
                type="radio"
                value="ESPECIAL"
                @change="manejarCambioTipoMayoria"
              />
              ESPECIAL
            </label>
          </div>
        </fieldset>

        <!--
          Factor y Base siguen siendo un grupo condicional propio y conservan su
          identificador de prueba, pero ya no forman una fila aparte: este contenedor
          es un tramo más de la misma línea. Se mantiene como elemento real (y no
          como `display: contents`) para que siga teniendo caja medible.
        -->
        <div
          v-if="borrador.tipoMayoria === 'ESPECIAL'"
          data-testid="campos-mayoria-especial"
          class="flex min-w-0 flex-col gap-2 sm:flex-[2] sm:flex-row sm:items-end"
        >
          <!--
            El rango admitido dejó de ocupar el rótulo (`Factor (0 < factor ≤ 1)`), que en
            una columna angosta se partía en tres renglones y volvía a agrandar la fila. No
            se perdió: se muestra como texto de ayuda dentro del campo vacío, que es
            justamente cuando el operador lo necesita, y se conserva completo en el texto
            emergente y en el nombre accesible del control.
          -->
          <label
            class="text-xs text-slate-300 sm:w-24 sm:shrink-0"
            title="Factor de mayoría especial: mayor que 0 y menor o igual que 1"
          >
            Factor
            <input
              v-model="borrador.factor"
              data-testid="input-factor-mayoria"
              type="text"
              inputmode="decimal"
              placeholder="0 &lt; f ≤ 1"
              aria-label="Factor de mayoría especial, mayor que 0 y menor o igual que 1"
              class="mt-0.5 w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-slate-100"
            />
          </label>
          <label class="min-w-0 text-xs text-slate-300 sm:flex-1">
            Base
            <select
              v-model="borrador.base"
              data-testid="select-base-mayoria"
              class="mt-0.5 w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-slate-100"
            >
              <option value="VOTOS_COMPUTABLES">VOTOS_COMPUTABLES</option>
              <option value="PRESENTES">PRESENTES</option>
              <option value="CUERPO">CUERPO</option>
            </select>
          </label>
        </div>
      </div>

      <div class="flex flex-col gap-2 sm:flex-row">
        <label class="min-w-0 flex-1 text-xs text-slate-300">
          Tema
          <input
            v-model="borrador.tema"
            data-testid="input-tema-votacion"
            type="text"
            class="mt-0.5 w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-slate-100"
          />
        </label>
        <button
          type="button"
          data-testid="btn-abrir-votacion"
          class="self-end rounded bg-cyan-600 px-4 py-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-950 disabled:opacity-40"
          :disabled="!puedeEnviarApertura"
          @click="solicitarApertura"
        >
          {{ abriendo ? 'Abriendo...' : 'Abrir votación' }}
        </button>
      </div>
      <p v-if="!conectado" class="text-[11px] text-amber-300">
        Reconectá el estado en tiempo real para habilitar comandos.
      </p>
      <p v-for="motivo in motivosAbrir" :key="motivo" class="text-[11px] text-amber-300">
        {{ motivo }}
      </p>
    </form>

    <DialogoConfirmacionApertura
      :palabra="estado.palabra"
      :abierto="aperturaPendiente !== null"
      :enviando="abriendo"
      @cancelar="cancelarAdvertenciaApertura"
      @confirmar="confirmarAdvertenciaApertura"
    />
  </section>
</template>

<style scoped>
/*
  Tres renglones de 1,25 rem producen una cota estable en las dos resoluciones operativas.
  `auto` no dibuja scroll cuando el tema entra y mantiene accesible todo el texto cuando
  desborda; no se usa `line-clamp` porque ocultaría el contenido restante.
*/
.tema-votacion-proyectada {
  max-height: calc(3 * 1.25rem);
  overflow-y: auto;
  line-height: 1.25rem;
  overflow-wrap: anywhere;
}
</style>
