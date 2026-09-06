/**
 * Detección de las transiciones sonoras del Recinto (WP-066), compartida por las
 * superficies que las reproducen (WP-071).
 *
 * ## Dónde vive y por qué
 *
 * Este módulo nació dentro de la Pantalla del Recinto. Desde WP-071 el puesto de Apoyo
 * Técnico debe reproducir **exactamente los mismos** eventos, para poder tomar el audio
 * del salón desde el equipo técnico. Dos implementaciones de esta semántica se separarían
 * con el primer cambio, así que la comparación se mudó tal cual a `frontend-shared` y las
 * dos pantallas la consumen desde acá. Sigue siendo la semántica del Recinto: lo que
 * cambió es cuántas superficies la escuchan, no qué significa cada transición.
 *
 * ## Qué resuelve este módulo
 *
 * El backend no publica «eventos de sonido»: publica **estados completos**. Cada snapshot
 * de `EstadoRecinto` describe cómo está el recinto ahora, no qué acaba de pasar. Sonorizar
 * consiste entonces en comparar dos estados consecutivos ya adoptados por la
 * sincronización y deducir qué cambió entre ellos.
 *
 * Esa comparación vive acá, en una función **pura**, separada de Vue y de `Audio`. Es la
 * pieza que concentra toda la semántica de WP-066, así que conviene poder probarla con dos
 * objetos y una lista esperada, sin montar componentes ni simular audio.
 *
 * ## Por qué no se inventan eventos
 *
 * WP-066 prohíbe expresamente crear eventos optimistas o pedirle al backend campos nuevos
 * para facilitar el audio: si la transición puede inferirse comparando estados confirmados,
 * se infiere. Todo lo que sigue se deduce de campos que ya viajaban en el contrato público.
 *
 * ## Qué NO se detecta acá
 *
 * El tic de la cuenta regresiva (`transmision_cuenta_regresiva_tic`) no nace de comparar
 * dos snapshots: nace de que el **número visible** en pantalla cambió de segundo mientras
 * la transmisión está en `CUENTA_REGRESIVA`. Ese número lo deriva localmente el reloj de
 * presentación técnica, sin pedir un snapshot por segundo, así que su tic lo dispara el
 * composable `useSonidosRecinto` observando ese valor y no esta función.
 */

import type {
  EstadoGlobal,
  EstadoTransmision,
  SonidosRecintoProyectados,
} from '@sis-leg/api-client'

/**
 * Contrato mínimo que necesita esta comparación para deducir un sonido (WP-074).
 *
 * ## Por qué no se pide directamente `EstadoRecinto`
 *
 * Hasta WP-074 esta función recibía el `EstadoRecinto` completo, porque la única pantalla
 * que sonorizaba era la del salón y el puesto técnico se suscribía a esa misma proyección.
 * Ese segundo stream, sumado a los otros cinco que abrían las cuatro superficies de SIS-Leg
 * bajo el mismo origen, agotaba el cupo de conexiones de HTTP/1.1 y dejaba los comandos
 * REST esperando indefinidamente.
 *
 * La corrección fue que el backend transporte, dentro del único estado técnico, una
 * subproyección con **exactamente estos campos**. Declarándolos acá como contrato, la
 * misma comparación sirve a las dos pantallas: el Recinto sigue pasando su `EstadoRecinto`
 * —que satisface esta forma por tener todos estos campos y más— y Apoyo Técnico pasa la
 * subproyección mínima que le manda el backend.
 *
 * Que el contrato sea así de chico es también la definición ejecutable de la frontera:
 * todo lo que no está acá no hace falta para sonorizar y, por lo tanto, no tiene por qué
 * viajar al puesto técnico. En particular no aparecen conteos, resultados ni votos
 * individuales.
 */
export interface InstantaneaSonora {
  /** Revisión monotónica; quien llama la usa para no sonorizar dos veces la misma. */
  revision: number
  /** Estado global, que delimita qué hechos de sesión pueden compararse. */
  estado_global: EstadoGlobal
  /** Plano técnico visible en el salón: transmisión y aviso del destino RECINTO. */
  tecnico: {
    transmision: { estado: EstadoTransmision } | null
    aviso: { aviso_id: string } | null
  } | null
  /** Cola y orador identificados por banca. */
  palabra: {
    cola: readonly { banca: number }[]
    orador: { banca: number } | null
  } | null
  /**
   * Identidad y recepción de la votación visible.
   *
   * `estado_recepcion` es `string` porque así viaja en el contrato público desde WP-049;
   * los dos valores que esta comparación distingue son `EN_CURSO` y `CERRADA`.
   */
  votacion: { id: string; estado_recepcion: string } | null
  /** Presencia de cada banca proyectada. */
  concejales: readonly { banca: number; presente: boolean }[]
  /** Configuración de audio, que el motor adopta antes de reproducir. */
  sonidos: SonidosRecintoProyectados
}

/**
 * Los quince eventos sonoros del contrato de WP-065, en su orden canónico.
 *
 * Los nombres son exactamente los que declara `config/system.toml` y proyecta el backend
 * en `EstadoRecinto.sonidos`. Se declaran como una tupla `as const` y no sólo como unión
 * de tipos por dos motivos complementarios:
 *
 * 1. el compilador sigue deteniendo un typo, porque el tipo se deriva de la tupla;
 * 2. existe además **en tiempo de ejecución**, de modo que una prueba de paridad puede
 *    recorrer los quince eventos sin volver a escribirlos. Desde WP-071 hay dos pantallas
 *    que deben reproducirlos todos: una lista repetida a mano en cada suite sería
 *    justamente la forma más fácil de que una de las dos se quedara con catorce.
 */
export const EVENTOS_SONOROS_RECINTO = [
  'preparacion_iniciada',
  'aviso_tecnico_publicado',
  'aviso_tecnico_retirado',
  'pedido_palabra_registrado',
  'pedido_palabra_retirado',
  'uso_palabra_otorgado',
  'transmision_iniciada',
  'transmision_detenida',
  'transmision_cuenta_regresiva_tic',
  'sesion_abierta',
  'sesion_cerrada',
  'votacion_abierta',
  'votacion_cerrada',
  'concejal_ausente',
  'concejal_presente',
] as const

/** Nombre de uno de los quince eventos sonoros del contrato de WP-065. */
export type EventoSonoroRecinto = (typeof EVENTOS_SONOROS_RECINTO)[number]

/** Estado de palabra normalizado: el contrato admite `null` fuera de una sesión. */
const PALABRA_VACIA: NonNullable<InstantaneaSonora['palabra']> = { cola: [], orador: null }

/**
 * Compara dos snapshots consecutivos y devuelve los eventos sonoros que ocurrieron.
 *
 * @param previo Último estado ya adoptado y **ya sonorizado**. Nunca es una baseline
 *   recién recibida: quien llama decide eso (ver `useSonidosRecinto`).
 * @param actual Estado nuevo adoptado por la sincronización.
 * @returns Lista de eventos en orden canónico. Puede venir vacía —lo normal— o traer
 *   varios eventos si una misma revisión cambió más de una cosa. La lista puede repetir
 *   un evento cuando el hecho ocurrió varias veces (por ejemplo dos concejales que se
 *   ausentan en la misma revisión); reproducirlos es responsabilidad del motor de audio.
 *
 * No tiene efectos laterales ni conserva memoria entre llamadas: dos llamadas con los
 * mismos argumentos devuelven lo mismo. Esa pureza es la que garantiza que procesar un
 * snapshot repetido no duplique sonidos, porque un estado comparado contra sí mismo no
 * produce ninguna transición.
 */
export function detectarTransicionesSonoras(
  previo: InstantaneaSonora,
  actual: InstantaneaSonora,
): EventoSonoroRecinto[] {
  const eventos: EventoSonoroRecinto[] = []

  agregarTransicionesGlobales(previo, actual, eventos)
  agregarTransicionesTecnicas(previo, actual, eventos)

  /*
    Los hechos de sesión (palabra, votación, presencia) sólo se comparan dentro del mismo
    estado global. Cerrar la sesión vacía de golpe la cola de palabra y el padrón: leer esa
    limpieza como «cinco concejales retiraron su pedido» sonorizaría una consecuencia
    administrativa en lugar de un hecho institucional. El cambio de estado global ya tiene
    su propio sonido y es el que corresponde escuchar.
  */
  if (previo.estado_global === actual.estado_global) {
    agregarTransicionesPalabra(previo, actual, eventos)
    agregarTransicionesVotacion(previo, actual, eventos)
    agregarTransicionesPresencia(previo, actual, eventos)
  }

  return eventos
}

/**
 * Preparación, apertura y cierre de sesión.
 *
 * `sesion_cerrada` se dispara ante cualquier salida de `SESION_ABIERTA` porque el estado
 * global es autoritativo: si el sistema dejó de estar en sesión, la sesión terminó.
 */
function agregarTransicionesGlobales(
  previo: InstantaneaSonora,
  actual: InstantaneaSonora,
  eventos: EventoSonoroRecinto[],
): void {
  if (previo.estado_global === actual.estado_global) return

  if (previo.estado_global === 'SIN_PREPARAR' && actual.estado_global === 'PREPARANDO') {
    eventos.push('preparacion_iniciada')
  }
  if (actual.estado_global === 'SESION_ABIERTA') {
    eventos.push('sesion_abierta')
  }
  if (previo.estado_global === 'SESION_ABIERTA') {
    eventos.push('sesion_cerrada')
  }
}

/**
 * Avisos de Apoyo Técnico y transmisión en vivo.
 *
 * Se evalúan siempre, incluso cuando cambia el estado global, porque el plano técnico
 * opera fuera de una sesión: WP-065 exige que estos sonidos existan también en
 * `SIN_PREPARAR`.
 *
 * Un aviso reemplazado por otro cuenta como publicación nueva y no como retiro más
 * publicación: desde el recinto se ve un solo hecho, el cartel cambió. Por eso se compara
 * `aviso_id` y no la mera presencia del objeto.
 */
function agregarTransicionesTecnicas(
  previo: InstantaneaSonora,
  actual: InstantaneaSonora,
  eventos: EventoSonoroRecinto[],
): void {
  const avisoPrevio = previo.tecnico?.aviso ?? null
  const avisoActual = actual.tecnico?.aviso ?? null

  if (avisoActual !== null && avisoActual.aviso_id !== avisoPrevio?.aviso_id) {
    eventos.push('aviso_tecnico_publicado')
  }
  if (avisoPrevio !== null && avisoActual === null) {
    eventos.push('aviso_tecnico_retirado')
  }

  const transmisionPrevia = previo.tecnico?.transmision?.estado ?? null
  const transmisionActual = actual.tecnico?.transmision?.estado ?? null

  if (transmisionPrevia !== 'EN_VIVO' && transmisionActual === 'EN_VIVO') {
    eventos.push('transmision_iniciada')
  }
  if (transmisionPrevia === 'EN_VIVO' && transmisionActual === 'APAGADO') {
    eventos.push('transmision_detenida')
  }
}

/**
 * Pedidos de palabra, retiros y otorgamiento del uso de la palabra.
 *
 * Cada persona se identifica por su banca, que es la única identidad estable que publica
 * la proyección pública (no viaja el DNI, y no debería).
 *
 * La distinción fina está en el retiro: una banca puede salir de la cola por dos motivos
 * opuestos. Si salió **porque le otorgaron la palabra**, el hecho es `uso_palabra_otorgado`
 * y sonorizarlo además como retiro sería contar dos veces el mismo movimiento. Sólo se
 * considera retiro la salida de la cola de alguien que no quedó como orador.
 */
function agregarTransicionesPalabra(
  previo: InstantaneaSonora,
  actual: InstantaneaSonora,
  eventos: EventoSonoroRecinto[],
): void {
  const palabraPrevia = previo.palabra ?? PALABRA_VACIA
  const palabraActual = actual.palabra ?? PALABRA_VACIA

  const colaPrevia = new Set(palabraPrevia.cola.map((persona) => persona.banca))
  const colaActual = new Set(palabraActual.cola.map((persona) => persona.banca))
  const bancaOradorActual = palabraActual.orador?.banca ?? null

  for (const persona of palabraActual.cola) {
    if (!colaPrevia.has(persona.banca)) eventos.push('pedido_palabra_registrado')
  }

  for (const persona of palabraPrevia.cola) {
    if (colaActual.has(persona.banca)) continue
    if (persona.banca === bancaOradorActual) continue
    eventos.push('pedido_palabra_retirado')
  }

  if (bancaOradorActual !== null && bancaOradorActual !== (palabraPrevia.orador?.banca ?? null)) {
    eventos.push('uso_palabra_otorgado')
  }
}

/**
 * Apertura y cierre de la votación.
 *
 * La apertura se reconoce por la **identidad** de la votación: una votación distinta que
 * llega `EN_CURSO` es una apertura, aunque la anterior siga visible mientras dura su
 * resultado.
 *
 * El cierre exige que la votación sea la misma y que su recepción pase de `EN_CURSO` a
 * `CERRADA`. Como después del cierre la recepción ya no vuelve a `EN_CURSO`, las revisiones
 * posteriores —resultado calculado, desempate de Presidencia, votos individuales
 * revelados— no vuelven a producir el sonido. Es exactamente el «una sola vez aunque luego
 * cambie el resultado» que pide el WP.
 */
function agregarTransicionesVotacion(
  previo: InstantaneaSonora,
  actual: InstantaneaSonora,
  eventos: EventoSonoroRecinto[],
): void {
  const votacionPrevia = previo.votacion
  const votacionActual = actual.votacion
  if (votacionActual === null) return

  const esOtraVotacion = votacionPrevia === null || votacionPrevia.id !== votacionActual.id

  if (esOtraVotacion) {
    if (votacionActual.estado_recepcion === 'EN_CURSO') eventos.push('votacion_abierta')
    return
  }

  if (
    votacionPrevia.estado_recepcion === 'EN_CURSO' &&
    votacionActual.estado_recepcion === 'CERRADA'
  ) {
    eventos.push('votacion_cerrada')
  }
}

/**
 * Ausencia y presencia de cada banca.
 *
 * Sólo se comparan las bancas que existen en **ambos** snapshots. Un padrón que aparece o
 * desaparece —preparar el recinto, cancelar la preparación— no es una docena de cambios de
 * presencia, y leerlo así llenaría el recinto de sonidos en el peor momento.
 */
function agregarTransicionesPresencia(
  previo: InstantaneaSonora,
  actual: InstantaneaSonora,
  eventos: EventoSonoroRecinto[],
): void {
  const presenciaPrevia = new Map(
    previo.concejales.map((concejal) => [concejal.banca, concejal.presente]),
  )

  for (const concejal of actual.concejales) {
    const presenciaAnterior = presenciaPrevia.get(concejal.banca)
    if (presenciaAnterior === undefined || presenciaAnterior === concejal.presente) continue
    eventos.push(concejal.presente ? 'concejal_presente' : 'concejal_ausente')
  }
}
