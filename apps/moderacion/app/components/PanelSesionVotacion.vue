<script setup lang="ts">
/**
 * Panel de Sesión y Votación (Cuadrante 1 de Moderación).
 *
 * Responsabilidades:
 * 1. Presentar el ciclo de vida institucional completo:
 *    - SIN_PREPARAR: Preparación del recinto como acción principal.
 *    - PREPARANDO: Carga y edición de número de sesión, Presidencia y Secretaría Legislativa,
 *      apertura formal de sesión cuando se cumplan las capacidades, o cancelación de la preparación.
 *    - SESION_ABIERTA: votación como único contenido del cuerpo, autoridades mediante modal
 *      y cierre con advertencia de palabra pendiente.
 * 2. Gestión robusta de borradores locales (H1): Los campos en edición activa (dirty) no son
 *    sobrescritos por snapshots SSE no relacionados (ej. pulsaciones de presencia o test de teclado).
 *    Al cambiar de estado global, los borradores se resincronizan con el nuevo estado institucional.
 * 3. Validación estricta del número de sesión (M3): Solo se envían enteros positivos (> 0);
 *    los valores inválidos no se transforman silenciosamente y muestran error claro conservando el input.
 * 4. Quórum (WP-036): este cuadrante ya no repite el resumen global de quórum. Ese dato es único
 *    y se presenta exclusivamente en la cabecera compacta del shell. Aquí se conservan sólo los
 *    controles institucionales (número de sesión y autoridades), que no son información redundante
 *    sino comandos.
 * 5. Gate de comandos mutantes: Solo permite emitir mutaciones cuando existe conexión plena (CONECTADO),
 *    la capacidad correspondiente está habilitada por el backend y no hay solicitudes en vuelo.
 * 6. Feedback de errores legibles sin optimismo ficticio ni alteración del estado confirmado.
 * 7. Integrar los diálogos de autoridades y cierre sin reservar altura cuando están cerrados.
 * 8. El cuerpo de Q1 no tiene scroll en desktop: cada estado reduce tarjetas, espacios y
 *    textos secundarios para caber completo en la celda asignada por el shell.
 * 9. Feedback operativo (WP-051): las confirmaciones humanas no críticas de este cuadrante
 *    (guardar datos de preparación, actualizar autoridades) se muestran como aviso efímero
 *    con caducidad automática en vez de quedar fijas sobre la pantalla. La mutación real ya
 *    queda registrada por la auditoría del backend y confirmada por el snapshot; el aviso
 *    sólo sirve para que el operador perciba que su comando fue aceptado. Los errores, en
 *    cambio, siguen siendo persistentes y con cierre manual: son accionables.
 * 10. Compactación operativa (WP-048): las dos acciones institucionales de la sesión
 *    (`Editar autoridades` y `Cerrar sesión`) viven en el área de acciones del encabezado
 *    del cuadrante, no en una franja propia del cuerpo. El número de sesión ya se publica
 *    una sola vez en la cabecera global del shell, así que Q1 deja de reservar altura para
 *    repetirlo. El badge de estado del recinto sí permanece acá: tras WP-047 este cuadrante es
 *    su única sede visible. El cuerpo queda íntegramente disponible para la votación, que
 *    es el trabajo real del operador durante una sesión abierta.
 * 11. Desenlace del cierre institucional (WP-085): cerrar la sesión produce además un informe
 *    de acta y, si la instalación lo configuró, una copia externa del conjunto. Ninguno de los
 *    dos es visible desde acá, así que este cuadrante los informa con un aviso efímero. El
 *    aviso de fallo usa un canal propio, distinto del error persistente, y su texto empieza
 *    afirmando que la sesión sí cerró: son hechos posteriores a un cierre ya irreversible y
 *    presentarlos como un error de cierre llevaría al operador a intentarlo otra vez.
 */

import { ref, computed, watch } from 'vue'
import type {
  EstadoModeracion,
  ClienteModeracion,
  PuntoOrdenDelDiaProyectado,
  RespuestaCierreSesion,
} from '@sis-leg/api-client'
import { useEstadoModeracion } from '../composables/useEstadoModeracion'
import { useAvisoEfimero } from '../composables/useAvisoEfimero'
import PanelContenedor from './PanelContenedor.vue'
import DialogoConfirmacionCierre from './DialogoConfirmacionCierre.vue'
import DialogoEdicionAutoridades from './DialogoEdicionAutoridades.vue'
import GestionVotacion from './GestionVotacion.vue'
import { traducirMotivos } from '../utils/motivos'

const props = defineProps<{
  /** Estado autoritativo de moderación recibido desde el backend */
  estado: EstadoModeracion | null
  /** Cliente de API inyectable para pruebas unitarias */
  clienteInyectado?: ClienteModeracion
  /** Copia asistencial elegida en Q2 para precargar el borrador de votación */
  puntoPreseleccionado?: PuntoOrdenDelDiaProyectado | null
}>()

// Consumimos la sincronización compartida de Moderación
const sincronizacion = useEstadoModeracion(props.clienteInyectado)
const cliente = computed(() => props.clienteInyectado ?? sincronizacion.cliente)
const conectado = computed(() => sincronizacion.conectado.value)

// Variables locales para borradores de edición (drafts)
const numeroSesionInput = ref<string>('')
const presidenciaInput = ref<string>('')
const secretariaInput = ref<string>('')

// Banderas de edición local (dirty tracking) por campo (H1)
const numeroSesionDirty = ref(false)
const presidenciaDirty = ref(false)
const secretariaDirty = ref(false)

// Seguimiento del último estado global para detectar transiciones institucionales reales
const ultimoEstadoGlobal = ref<string | null>(null)

// Estado local de operaciones en vuelo y errores
const enviando = ref(false)
const mensajeError = ref<string | null>(null)
// Confirmación humana no crítica: aparece un instante y se apaga sola (WP-051).
const avisoExito = useAvisoEfimero()
const mensajeExito = avisoExito.mensaje
// Advertencia posterior a un cierre ya consumado (WP-085): el informe de acta o la copia
// externa fallaron, pero la sesión cerró igual. Es efímera y no usa `mensajeError` porque
// ese canal es persistente y accionable, y acá no hay nada que el operador pueda reintentar
// desde Moderación: el cierre institucional ya es irreversible.
const avisoAdvertencia = useAvisoEfimero()
const mensajeAdvertencia = avisoAdvertencia.mensaje

// Control de apertura del diálogo de advertencia de cierre
const mostrarDialogoCierre = ref(false)
const mostrarDialogoAutoridades = ref(false)

/**
 * Conserva el número de sesión como borrador textual aunque el control sea type="number".
 * Vue convierte automáticamente a number cuando se usa v-model sobre ese tipo de input;
 * leer value de HTMLInputElement mantiene la invariancia textual que necesitan la validación
 * estricta y el seguimiento dirty, sin truncar decimales ni transformar valores inválidos.
 */
function manejarInputNumeroSesion(evento: Event): void {
  const entrada = evento.target as HTMLInputElement | null
  if (!entrada) return

  numeroSesionInput.value = entrada.value
  numeroSesionDirty.value = true
}

/**
 * Sincroniza los borradores locales con el estado autoritativo del backend.
 * Reglas de gestión de drafts (H1):
 * - En transiciones institucionales (cambio de estado_global), se resincroniza todo y se limpian los dirty flags.
 * - Dentro del mismo estado global:
 *   - Si un campo no está dirty: se actualiza con el valor confirmado del backend.
 *   - Si un campo está dirty y el snapshot confirma exactamente el valor local tipeado: se limpia el dirty flag.
 *   - Si un campo está dirty y el snapshot trae un valor distinto (ej. por eventos de presencia/test ajenos):
 *     SE CONSERVA el texto que el operador está editando sin pisarlo.
 */
watch(
  () => props.estado,
  (nuevoEstado) => {
    if (!nuevoEstado) {
      numeroSesionInput.value = ''
      presidenciaInput.value = ''
      secretariaInput.value = ''
      numeroSesionDirty.value = false
      presidenciaDirty.value = false
      secretariaDirty.value = false
      ultimoEstadoGlobal.value = null
      return
    }

    const estadoGlobalActual = nuevoEstado.estado_global
    const esTransicionEstado = estadoGlobalActual !== ultimoEstadoGlobal.value

    if (esTransicionEstado) {
      // Transición institucional real: resincronizamos todo y reiniciamos el estado dirty
      ultimoEstadoGlobal.value = estadoGlobalActual
      numeroSesionDirty.value = false
      presidenciaDirty.value = false
      secretariaDirty.value = false

      if (estadoGlobalActual === 'PREPARANDO' && nuevoEstado.preparacion) {
        numeroSesionInput.value =
          nuevoEstado.preparacion.numero_sesion !== null
            ? String(nuevoEstado.preparacion.numero_sesion)
            : ''
        presidenciaInput.value = nuevoEstado.preparacion.presidencia ?? ''
        secretariaInput.value = nuevoEstado.preparacion.secretaria_legislativa ?? ''
      } else if (estadoGlobalActual === 'SESION_ABIERTA' && nuevoEstado.sesion) {
        numeroSesionInput.value = String(nuevoEstado.sesion.numero_sesion)
        presidenciaInput.value = nuevoEstado.sesion.presidencia ?? ''
        secretariaInput.value = nuevoEstado.sesion.secretaria_legislativa ?? ''
      } else {
        numeroSesionInput.value = ''
        presidenciaInput.value = ''
        secretariaInput.value = ''
      }
    } else {
      // Mismo estado global: aplicamos dirty tracking selectivo por campo
      if (estadoGlobalActual === 'PREPARANDO' && nuevoEstado.preparacion) {
        const prep = nuevoEstado.preparacion
        const numConfirmado = prep.numero_sesion !== null ? String(prep.numero_sesion) : ''
        const presConfirmada = prep.presidencia ?? ''
        const secConfirmada = prep.secretaria_legislativa ?? ''

        // Número de sesión
        if (!numeroSesionDirty.value) {
          numeroSesionInput.value = numConfirmado
        } else if (numeroSesionInput.value.trim() === numConfirmado) {
          numeroSesionDirty.value = false
        }

        // Presidencia
        if (!presidenciaDirty.value) {
          presidenciaInput.value = presConfirmada
        } else if (presidenciaInput.value === presConfirmada) {
          presidenciaDirty.value = false
        }

        // Secretaría Legislativa
        if (!secretariaDirty.value) {
          secretariaInput.value = secConfirmada
        } else if (secretariaInput.value === secConfirmada) {
          secretariaDirty.value = false
        }
      } else if (estadoGlobalActual === 'SESION_ABIERTA' && nuevoEstado.sesion) {
        const ses = nuevoEstado.sesion
        // En sesión abierta el número es inmutable
        numeroSesionInput.value = String(ses.numero_sesion)
        const presConfirmada = ses.presidencia ?? ''
        const secConfirmada = ses.secretaria_legislativa ?? ''

        if (!presidenciaDirty.value) {
          presidenciaInput.value = presConfirmada
        } else if (presidenciaInput.value === presConfirmada) {
          presidenciaDirty.value = false
        }

        if (!secretariaDirty.value) {
          secretariaInput.value = secConfirmada
        } else if (secretariaInput.value === secConfirmada) {
          secretariaDirty.value = false
        }
      }
    }
  },
  { immediate: true },
)

/**
 * Valida el número de sesión según las reglas institucionales (M3).
 * Debe ser vacío (opcional en preparación) o un entero positivo estricto (> 0).
 * No trunca decimales ni convierte silenciosamente texto inválido.
 */
function validarNumeroSesion(valor: string): { valido: boolean; numero?: number; error?: string } {
  const texto = valor.trim()
  if (texto === '') {
    return { valido: true }
  }
  // Expresión regular que exige dígitos exclusivamente (sin signos, puntos ni exponentes)
  if (!/^\d+$/.test(texto)) {
    return {
      valido: false,
      error: 'El número de sesión debe ser un número entero positivo mayor a cero.',
    }
  }
  const num = Number(texto)
  if (!Number.isInteger(num) || num <= 0) {
    return {
      valido: false,
      error: 'El número de sesión debe ser un número entero positivo mayor a cero.',
    }
  }
  return { valido: true, numero: num }
}

// Helper para extraer un mensaje de error legible sin recurrir a tipos inseguros
function extraerMensajeError(error: unknown, mensajePorDefecto: string): string {
  if (typeof error === 'object' && error !== null) {
    if ('mensaje' in error && typeof (error as { mensaje: unknown }).mensaje === 'string') {
      return (error as { mensaje: string }).mensaje
    }
    if ('message' in error && typeof (error as { message: unknown }).message === 'string') {
      return (error as { message: string }).message
    }
  }
  return mensajePorDefecto
}

// =============================================================================
// Capacidades y autorizaciones de comandos
// =============================================================================

const puedePrepararSala = computed(() => {
  return (
    conectado.value &&
    (props.estado?.capacidades?.preparar_sala?.habilitada ?? false) &&
    !enviando.value
  )
})

const motivosPrepararSala = computed(() =>
  traducirMotivos(props.estado?.capacidades?.preparar_sala?.motivos),
)

const puedeActualizarPreparacion = computed(() => {
  return (
    conectado.value &&
    (props.estado?.capacidades?.actualizar_preparacion?.habilitada ?? false) &&
    !enviando.value
  )
})

const puedeCancelarPreparacion = computed(() => {
  return (
    conectado.value &&
    (props.estado?.capacidades?.cancelar_preparacion?.habilitada ?? false) &&
    !enviando.value
  )
})

const puedeAbrirSesion = computed(() => {
  return (
    conectado.value &&
    (props.estado?.capacidades?.abrir_sesion?.habilitada ?? false) &&
    !enviando.value
  )
})

const motivosAbrirSesion = computed(() =>
  traducirMotivos(props.estado?.capacidades?.abrir_sesion?.motivos),
)

const puedeActualizarSesion = computed(() => {
  return (
    conectado.value &&
    (props.estado?.capacidades?.actualizar_sesion?.habilitada ?? false) &&
    !enviando.value &&
    presidenciaInput.value.trim().length > 0 &&
    secretariaInput.value.trim().length > 0
  )
})

const puedeAbrirEdicionAutoridades = computed(() => {
  return (
    conectado.value &&
    (props.estado?.capacidades?.actualizar_sesion?.habilitada ?? false) &&
    !enviando.value
  )
})

const puedeCerrarSesion = computed(() => {
  return (
    conectado.value &&
    (props.estado?.capacidades?.cerrar_sesion?.habilitada ?? false) &&
    !enviando.value
  )
})

const motivosCerrarSesion = computed(() =>
  traducirMotivos(props.estado?.capacidades?.cerrar_sesion?.motivos),
)

// =============================================================================
// Ejecutores de comandos
// =============================================================================

/**
 * Deja el cuadrante sin feedback previo antes de emitir un comando nuevo.
 *
 * Limpiar el aviso efímero también cancela su temporizador pendiente: así una confirmación
 * vieja no puede apagarse encima de una nueva ni sobrevivir a un error recién ocurrido.
 */
function limpiarMensajes(): void {
  mensajeError.value = null
  avisoExito.limpiar()
  avisoAdvertencia.limpiar()
}

/**
 * Ejecuta el comando de preparación del recinto (CU-01).
 *
 * WP-062 cambió el texto visible a «Preparar recinto», pero la capacidad del backend
 * sigue llamándose `preparar_sala` y el `data-testid` conserva su nombre histórico: son
 * contrato e identificadores de prueba, no terminología dirigida a personas.
 */
async function ejecutarPrepararSala(): Promise<void> {
  if (!puedePrepararSala.value) return
  limpiarMensajes()
  enviando.value = true

  try {
    await cliente.value.prepararSala()
    // Éxito: el nuevo snapshot SSE reflejará PREPARANDO
  } catch (error: unknown) {
    mensajeError.value = extraerMensajeError(error, 'Error al preparar el recinto')
  } finally {
    enviando.value = false
  }
}

/**
 * Guarda los datos institucionales editados durante PREPARANDO.
 */
async function ejecutarActualizarPreparacion(): Promise<void> {
  if (!puedeActualizarPreparacion.value) return
  limpiarMensajes()

  // Validación estricta del número de sesión (M3)
  const validacionNum = validarNumeroSesion(numeroSesionInput.value)
  if (!validacionNum.valido) {
    mensajeError.value = validacionNum.error ?? 'Número de sesión inválido'
    return
  }

  enviando.value = true

  try {
    const datosActualizacion: {
      numero_sesion?: number
      presidencia?: string
      secretaria_legislativa?: string
    } = {
      presidencia: presidenciaInput.value,
      secretaria_legislativa: secretariaInput.value,
    }

    if (validacionNum.numero !== undefined) {
      datosActualizacion.numero_sesion = validacionNum.numero
    }

    await cliente.value.actualizarPreparacion(datosActualizacion)
    // WP-051: confirmación breve. Guardar los mismos valores no produce ningún cambio
    // visible en el formulario, así que un acuse momentáneo es información útil; dejarlo
    // fijo, en cambio, tapaba la pantalla de trabajo durante toda la preparación.
    avisoExito.mostrar('Datos de preparación guardados.')
  } catch (error: unknown) {
    mensajeError.value = extraerMensajeError(error, 'Error al actualizar los datos de preparación')
  } finally {
    enviando.value = false
  }
}

/**
 * Cancela la preparación activa devolviendo el sistema a SIN_PREPARAR (CU-02).
 */
async function ejecutarCancelarPreparacion(): Promise<void> {
  if (!puedeCancelarPreparacion.value) return
  limpiarMensajes()
  enviando.value = true

  try {
    await cliente.value.cancelarPreparacion()
  } catch (error: unknown) {
    mensajeError.value = extraerMensajeError(error, 'Error al cancelar la preparación del recinto')
  } finally {
    enviando.value = false
  }
}

/**
 * Abre formalmente la sesión desde PREPARANDO (CU-05).
 */
async function ejecutarAbrirSesion(): Promise<void> {
  if (!puedeAbrirSesion.value) return
  limpiarMensajes()
  enviando.value = true

  try {
    await cliente.value.abrirSesion()
  } catch (error: unknown) {
    mensajeError.value = extraerMensajeError(error, 'Error al abrir la sesión formal')
  } finally {
    enviando.value = false
  }
}

/**
 * Actualiza Presidencia y/o Secretaría durante una sesión abierta (CU-06).
 */
async function ejecutarActualizarSesion(): Promise<void> {
  if (!puedeActualizarSesion.value) return
  limpiarMensajes()
  enviando.value = true

  try {
    await cliente.value.actualizarSesion({
      presidencia: presidenciaInput.value.trim(),
      secretaria_legislativa: secretariaInput.value.trim(),
    })
    // WP-051: el modal se cierra enseguida, así que la confirmación vive como aviso
    // efímero del cuadrante y no como cartel permanente.
    avisoExito.mostrar('Autoridades actualizadas.')
    // El modal puede cerrarse tras la aceptación HTTP sin falsear el estado visible:
    // la cabecera continúa mostrando exclusivamente el snapshot confirmado.
    mostrarDialogoAutoridades.value = false
  } catch (error: unknown) {
    mensajeError.value = extraerMensajeError(error, 'Error al actualizar las autoridades')
  } finally {
    enviando.value = false
  }
}

/**
 * Abre la edición desde los valores autoritativos vigentes. Mientras el modal está
 * abierto, el watcher general protege cada campo dirty frente a snapshots SSE ajenos.
 */
function abrirEdicionAutoridades(): void {
  if (!props.estado?.sesion) return
  limpiarMensajes()
  presidenciaInput.value = props.estado.sesion.presidencia ?? ''
  secretariaInput.value = props.estado.sesion.secretaria_legislativa ?? ''
  presidenciaDirty.value = false
  secretariaDirty.value = false
  mostrarDialogoAutoridades.value = true
}

/** Cancela la edición local y vuelve a los valores confirmados por el backend. */
function cancelarEdicionAutoridades(): void {
  if (enviando.value) return
  presidenciaInput.value = props.estado?.sesion?.presidencia ?? ''
  secretariaInput.value = props.estado?.sesion?.secretaria_legislativa ?? ''
  presidenciaDirty.value = false
  secretariaDirty.value = false
  mostrarDialogoAutoridades.value = false
  limpiarMensajes()
}

function actualizarPresidenciaModal(valor: string): void {
  presidenciaInput.value = valor
  presidenciaDirty.value = true
}

function actualizarSecretariaModal(valor: string): void {
  secretariaInput.value = valor
  secretariaDirty.value = true
}

/**
 * Inicia el flujo de cierre de sesión: verifica palabra pendiente antes de enviar (CU-07).
 */
function iniciarCerrarSesion(): void {
  if (!puedeCerrarSesion.value) return
  limpiarMensajes()

  // Verificamos si existe palabra pendiente en el estado autoritativo
  const hayOrador =
    props.estado?.palabra?.orador !== null && props.estado?.palabra?.orador !== undefined
  const hayCola = (props.estado?.palabra?.cola?.length ?? 0) > 0

  if (hayOrador || hayCola) {
    // Abrimos el diálogo modal de advertencia confirmatoria
    mostrarDialogoCierre.value = true
  } else {
    // Si no hay orador ni cola, procedemos directamente al cierre normal
    confirmarCerrarSesion()
  }
}

/**
 * Envía el comando de cierre normal de sesión al backend.
 */
async function confirmarCerrarSesion(): Promise<void> {
  mostrarDialogoCierre.value = false
  limpiarMensajes()
  enviando.value = true

  try {
    const resultado = await cliente.value.cerrarSesion()
    anunciarCierreInstitucional(resultado)
  } catch (error: unknown) {
    mensajeError.value = extraerMensajeError(error, 'Error al cerrar la sesión')
  } finally {
    enviando.value = false
  }
}

/**
 * Traduce el resultado del cierre en el aviso efímero que corresponda (WP-085).
 *
 * Los tres desenlaces posibles y por qué se muestran así:
 *
 * - **nada configurado y todo bien** (`OMITIDA` con acta generada): no se muestra nada. La
 *   instalación no pidió copia externa, así que anunciar «no se copió» sería ruido sobre una
 *   operación que salió exactamente como debía.
 * - **copia realizada** (`EXITOSA`): confirmación breve. El operador no puede ver la carpeta
 *   externa desde Moderación, así que este aviso es su única señal de que la réplica existe.
 * - **acta o copia fallidas**: advertencia efímera que empieza afirmando que la sesión cerró.
 *   Es la parte más importante del texto: sin ella, un operador que lee «no se pudo…» justo
 *   después de apretar «Cerrar sesión» concluye que el cierre falló e intenta cerrarla otra
 *   vez, cuando en realidad el estado ya volvió a SIN_PREPARAR y los CSV quedaron completos.
 *
 * El acta y la copia se informan en un solo aviso porque son consecuencias del mismo comando
 * y dos toasts encadenados se pisarían entre sí: el composable mantiene un único mensaje.
 */
function anunciarCierreInstitucional(resultado: RespuestaCierreSesion | undefined): void {
  // Guarda defensiva: si por cualquier motivo el cierre llegara sin cuerpo, no hay nada
  // que anunciar. Dejarlo sin guarda haría que un acceso a un campo inexistente cayera en
  // el `catch` de arriba y mostrara «Error al cerrar la sesión» sobre un cierre exitoso,
  // justo el malentendido que este WP viene a evitar.
  if (!resultado) return

  if (!resultado.acta_generada) {
    avisoAdvertencia.mostrar(
      'La sesión cerró y los registros CSV quedaron completos, pero no se pudo generar el informe de acta.',
    )
    return
  }

  if (resultado.copia_externa === 'FALLIDA') {
    avisoAdvertencia.mostrar(
      'La sesión cerró y los registros quedaron completos en el equipo, pero no se pudo copiarlos a la carpeta externa.',
    )
    return
  }

  if (resultado.copia_externa === 'EXITOSA') {
    avisoExito.mostrar('Sesión cerrada. Registros copiados a la carpeta externa.')
  }
}

function cancelarAdvertenciaCierre(): void {
  mostrarDialogoCierre.value = false
}

// Textos e insignias del panel
const textoBadge = computed(() => {
  if (!props.estado) return 'Esperando datos...'
  switch (props.estado.estado_global) {
    case 'SESION_ABIERTA':
      return 'Sesión activa'
    case 'PREPARANDO':
      return 'Preparando el recinto'
    case 'SIN_PREPARAR':
      return 'Sin preparar'
    default:
      return props.estado.estado_global
  }
})

const claseBadge = computed(() => {
  switch (props.estado?.estado_global) {
    case 'SESION_ABIERTA':
      return 'bg-emerald-950 text-emerald-300 border border-emerald-700'
    case 'PREPARANDO':
      return 'bg-cyan-950 text-cyan-300 border border-cyan-700'
    case 'SIN_PREPARAR':
    default:
      return 'bg-slate-800 text-slate-300 border border-slate-700'
  }
})
</script>

<template>
  <PanelContenedor
    titulo="Sesión y votación"
    data-testid="panel-sesion-votacion"
    :badge="textoBadge"
    :clase-badge="claseBadge"
    :contenido-sin-scroll="true"
  >
    <!--
      WP-048: las acciones de sesión comparten la fila del título y del badge. Al vivir en
      el encabezado ya existente del cuadrante no consumen una franja propia dentro del
      cuerpo, que es la altura que necesitan el resultado anterior y el formulario nuevo.
      Se mantienen deliberadamente en la escala del badge (`py-0.5`, `text-[11px]`) para
      que el encabezado conserve la altura fijada por WP-047.
    -->
    <template v-if="estado?.estado_global === 'SESION_ABIERTA'" #acciones>
      <button
        type="button"
        data-testid="btn-editar-autoridades"
        class="rounded border border-emerald-700 bg-emerald-950 px-2 py-0.5 text-[11px] font-semibold text-emerald-200 disabled:opacity-40"
        :disabled="!puedeAbrirEdicionAutoridades"
        @click="abrirEdicionAutoridades"
      >
        Editar autoridades
      </button>
      <button
        type="button"
        data-testid="btn-cerrar-sesion"
        class="rounded border border-rose-700 bg-rose-950 px-2 py-0.5 text-[11px] font-semibold text-rose-200 disabled:opacity-40"
        :disabled="!puedeCerrarSesion"
        @click="iniciarCerrarSesion"
      >
        {{ enviando ? 'Cerrando...' : 'Cerrar sesión' }}
      </button>
    </template>

    <div class="relative h-full min-h-0 text-xs text-slate-300">
      <!--
        El feedback flota dentro del viewport y no reserva una fila vacía en Q1.
        Sigue siendo accesible mediante role.

        WP-051 separa las dos categorías: el error es accionable y permanece hasta que el
        operador lo resuelve o lo cierra; la confirmación es un aviso efímero que se apaga
        solo y por eso ya no ofrece botón de cierre.
      -->
      <div
        v-if="mensajeError"
        data-testid="alerta-error-comando"
        class="fixed top-16 right-4 z-40 flex max-w-md items-center justify-between gap-2 rounded-lg border border-rose-700/80 bg-rose-950/95 p-2 text-xs text-rose-200 shadow-xl"
        role="alert"
      >
        <div class="flex items-center gap-2">
          <span class="font-bold text-rose-400">Error:</span>
          <span>{{ mensajeError }}</span>
        </div>
        <button
          type="button"
          class="rounded p-1 text-rose-400 hover:bg-rose-900/50"
          @click="limpiarMensajes"
        >
          ✕
        </button>
      </div>

      <!--
        WP-085: aviso efímero de advertencia. Vive entre el error persistente y la
        confirmación porque no es ninguno de los dos: informa un fallo que ya no se puede
        revertir ni reintentar, sobre una operación que sí tuvo éxito.
      -->
      <div
        v-if="mensajeAdvertencia"
        data-testid="alerta-advertencia-comando"
        class="pointer-events-none fixed top-16 right-4 z-40 flex max-w-md items-center gap-2 rounded-lg border border-amber-600/80 bg-amber-950/95 p-2 text-xs text-amber-100 shadow-xl"
        role="status"
      >
        <span>{{ mensajeAdvertencia }}</span>
      </div>

      <div
        v-if="mensajeExito"
        data-testid="alerta-exito-comando"
        class="pointer-events-none fixed top-16 right-4 z-40 flex max-w-md items-center gap-2 rounded-lg border border-emerald-700/80 bg-emerald-950/95 p-2 text-xs text-emerald-200 shadow-xl"
        role="status"
      >
        <span>{{ mensajeExito }}</span>
      </div>

      <div
        v-if="estado?.estado_global === 'SIN_PREPARAR'"
        data-testid="vista-sin-preparar"
        class="flex h-full flex-col justify-center gap-3 rounded-lg border border-slate-800 bg-slate-950/50 p-3"
      >
        <div>
          <h3 class="text-sm font-bold text-slate-100">Recinto sin preparar</h3>
          <p class="mt-0.5 text-xs text-slate-400">Iniciá la preparación para operar la sesión.</p>
        </div>
        <button
          type="button"
          data-testid="btn-preparar-sala"
          class="flex w-full items-center justify-center gap-2 rounded-lg bg-cyan-600 px-4 py-2 text-xs font-bold uppercase tracking-wider text-slate-950 hover:bg-cyan-500 disabled:cursor-not-allowed disabled:opacity-40"
          :disabled="!puedePrepararSala"
          @click="ejecutarPrepararSala"
        >
          <span
            v-if="enviando"
            class="inline-block h-3 w-3 animate-spin rounded-full border-2 border-slate-950 border-t-transparent"
          />
          {{ enviando ? 'Preparando recinto...' : 'Preparar recinto' }}
        </button>
        <!--
          WP-044: cada requisito pendiente ocupa su propia línea. Concatenarlos con
          separadores obligaba al operador a leer un párrafo corrido para descubrir
          cuántas condiciones faltaban realmente. Los motivos siguen viniendo tal cual
          de `capacidades.preparar_sala.motivos`: el frontend no inventa requisitos.
        -->
        <ul
          v-if="!puedePrepararSala && motivosPrepararSala.length > 0"
          data-testid="motivos-preparar-sala"
          class="space-y-0.5 text-[11px] leading-tight text-amber-300"
        >
          <li
            v-for="motivo in motivosPrepararSala"
            :key="motivo"
            data-testid="motivo-preparar-sala"
          >
            {{ motivo }}
          </li>
        </ul>
      </div>

      <div
        v-else-if="estado?.estado_global === 'PREPARANDO'"
        data-testid="vista-preparando"
        class="flex h-full flex-col gap-2 rounded-lg border border-cyan-900/50 bg-slate-950/50 p-2"
      >
        <div class="grid grid-cols-1 gap-2 sm:grid-cols-[0.55fr_1fr_1fr]">
          <label for="prep-numero-sesion" class="text-[11px] font-semibold text-slate-300">
            Sesión Nº
            <input
              id="prep-numero-sesion"
              :value="numeroSesionInput"
              type="number"
              min="1"
              step="1"
              data-testid="input-numero-sesion"
              class="mt-0.5 w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-xs text-slate-100 focus:border-cyan-500 focus:outline-none disabled:opacity-50"
              :disabled="enviando || !conectado"
              @input="manejarInputNumeroSesion"
            />
          </label>
          <label for="prep-presidencia" class="text-[11px] font-semibold text-slate-300">
            Presidencia
            <input
              id="prep-presidencia"
              v-model="presidenciaInput"
              type="text"
              data-testid="input-presidencia"
              class="mt-0.5 w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-xs text-slate-100 focus:border-cyan-500 focus:outline-none disabled:opacity-50"
              :disabled="enviando || !conectado"
              @input="presidenciaDirty = true"
            />
          </label>
          <label for="prep-secretaria" class="text-[11px] font-semibold text-slate-300">
            Secretaría Legislativa
            <input
              id="prep-secretaria"
              v-model="secretariaInput"
              type="text"
              data-testid="input-secretaria"
              class="mt-0.5 w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-xs text-slate-100 focus:border-cyan-500 focus:outline-none disabled:opacity-50"
              :disabled="enviando || !conectado"
              @input="secretariaDirty = true"
            />
          </label>
        </div>

        <div class="flex flex-wrap items-center justify-end gap-2 border-t border-slate-800 pt-2">
          <button
            type="button"
            data-testid="btn-guardar-preparacion"
            class="rounded border border-cyan-700 bg-cyan-950 px-3 py-1.5 text-[11px] font-semibold text-cyan-200 disabled:opacity-40"
            :disabled="!puedeActualizarPreparacion"
            @click="ejecutarActualizarPreparacion"
          >
            Guardar datos
          </button>
          <button
            type="button"
            data-testid="btn-cancelar-preparacion"
            class="rounded border border-slate-700 bg-slate-800 px-3 py-1.5 text-[11px] font-semibold text-rose-300 disabled:opacity-40"
            :disabled="!puedeCancelarPreparacion"
            @click="ejecutarCancelarPreparacion"
          >
            Cancelar preparación
          </button>
          <button
            type="button"
            data-testid="btn-abrir-sesion"
            class="rounded bg-emerald-600 px-3 py-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-950 disabled:opacity-40"
            :disabled="!puedeAbrirSesion"
            @click="ejecutarAbrirSesion"
          >
            {{ enviando ? 'Abriendo...' : 'Abrir sesión' }}
          </button>
        </div>
        <!--
          WP-048: los requisitos que faltan para abrir la sesión se leen uno por renglón.
          Concatenarlos con separadores obligaba al operador a recorrer un párrafo corrido
          para descubrir cuántas condiciones seguían pendientes. Los motivos llegan tal cual
          desde `capacidades.abrir_sesion.motivos`: el frontend no inventa requisitos ni
          decide si la sesión puede abrirse.
        -->
        <ul
          v-if="!puedeAbrirSesion && motivosAbrirSesion.length > 0"
          data-testid="motivos-abrir-sesion"
          class="space-y-0.5 text-[11px] leading-tight text-amber-300"
        >
          <li v-for="motivo in motivosAbrirSesion" :key="motivo" data-testid="motivo-abrir-sesion">
            {{ motivo }}
          </li>
        </ul>
      </div>

      <div
        v-else-if="estado?.estado_global === 'SESION_ABIERTA'"
        data-testid="vista-sesion-abierta"
        class="flex h-full min-h-0 flex-col gap-2"
      >
        <!--
          WP-048: el cuerpo arranca directamente en la votación. El número de sesión no
          reserva una franja acá porque ya es un dato único de la cabecera global, y las
          dos acciones institucionales se movieron al encabezado del cuadrante.
        -->
        <GestionVotacion
          class="min-h-0 flex-1"
          :estado="estado"
          :cliente="cliente"
          :conectado="conectado"
          :punto-preseleccionado="puntoPreseleccionado ?? null"
        />

        <p
          v-if="!puedeCerrarSesion && motivosCerrarSesion.length > 0"
          data-testid="motivos-cerrar-sesion"
          class="shrink-0 text-[11px] leading-tight text-amber-300"
        >
          {{ motivosCerrarSesion.join(' · ') }}
        </p>
      </div>

      <div
        v-else
        class="flex h-full items-center justify-center rounded-lg border border-dashed border-slate-800 p-4 text-center text-xs text-slate-400"
      >
        Conectando y esperando estado autoritativo del backend...
      </div>
    </div>

    <DialogoEdicionAutoridades
      :abierto="mostrarDialogoAutoridades"
      :presidencia="presidenciaInput"
      :secretaria="secretariaInput"
      :puede-guardar="puedeActualizarSesion"
      :enviando="enviando"
      :mensaje-error="mostrarDialogoAutoridades ? mensajeError : null"
      @actualizar-presidencia="actualizarPresidenciaModal"
      @actualizar-secretaria="actualizarSecretariaModal"
      @guardar="ejecutarActualizarSesion"
      @cancelar="cancelarEdicionAutoridades"
    />

    <!-- Diálogo de confirmación ante cierre de sesión con palabra pendiente -->
    <DialogoConfirmacionCierre
      :palabra="estado?.palabra ?? null"
      :abierto="mostrarDialogoCierre"
      :enviando="enviando"
      @confirmar="confirmarCerrarSesion"
      @cancelar="cancelarAdvertenciaCierre"
    />
  </PanelContenedor>
</template>
