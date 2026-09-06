/**
 * Reloj exclusivamente presentacional para la votación pública.
 *
 * El backend ya decidió apertura, secreto, cierre, resultado y deadlines. Este
 * composable solamente hace avanzar la representación visual entre mensajes
 * SSE, sin polling ni una copia histórica de votos/resultados.
 */

import { computed, onScopeDispose, ref, watch, type ComputedRef, type Ref } from 'vue'
import type { EstadoRecinto, VotacionPublica } from '@sis-leg/api-client'
import { resultadoIndividualVisible } from '@sis-leg/frontend-shared'

const INTERVALO_RELOJ_MS = 250

export interface PresentacionVotacion {
  votacion: ComputedRef<VotacionPublica | null>
  segundosCuentaRegresiva: ComputedRef<number | null>
}

/** Convierte un timestamp ISO del contrato en milisegundos, o null si falta. */
function instante(timestamp: string | null): number | null {
  if (timestamp === null) return null
  const valor = Date.parse(timestamp)
  return Number.isFinite(valor) ? valor : null
}

/**
 * Mantiene un reloj local corregido con `generado_en` del último snapshot.
 *
 * El desfase evita depender ciegamente del reloj del monitor. Recibir otra
 * revisión puede corregir ese desfase, pero jamás crea una duración nueva: la
 * cuenta y el resultado continúan apuntando a los deadlines originales.
 */
export function usePresentacionVotacion(estado: Ref<EstadoRecinto | null>): PresentacionVotacion {
  const ahoraLocal = ref(Date.now())
  const desfaseBackend = ref(0)
  let intervalo: ReturnType<typeof setInterval> | null = null
  let ultimoGeneradoEn: number | null = null

  const ahoraBackend = computed(() => ahoraLocal.value + desfaseBackend.value)

  const votacion = computed<VotacionPublica | null>(() => {
    if (estado.value?.estado_global === 'SIN_PREPARAR') return null

    const actual = estado.value?.votacion ?? null
    if (actual === null) return null

    if (
      actual.resultado !== null &&
      !resultadoIndividualVisible({
        estadoRecepcion: actual.estado_recepcion,
        resultado: actual.resultado,
        resultadoVisibleHasta: actual.resultado_visible_hasta,
        ahoraBackend: ahoraBackend.value,
      })
    ) {
      return null
    }

    return actual
  })

  const segundosCuentaRegresiva = computed<number | null>(() => {
    const actual = votacion.value
    if (actual?.estado_recepcion !== 'EN_CURSO') return null

    const hasta = instante(actual.cuenta_regresiva_hasta)
    if (hasta === null) return null

    const restante = hasta - ahoraBackend.value
    return restante > 0 ? Math.ceil(restante / 1000) : null
  })

  function detenerReloj(): void {
    if (intervalo === null) return
    clearInterval(intervalo)
    intervalo = null
  }

  /** Devuelve la próxima frontera que todavía exige actualizar la vista. */
  function fronteraTemporalPendiente(): number | null {
    const actual = estado.value?.votacion
    if (!actual) return null

    if (actual.estado_recepcion === 'EN_CURSO') {
      const countdown = instante(actual.cuenta_regresiva_hasta)
      if (countdown !== null && countdown > ahoraBackend.value) return countdown
    }

    const resultado = instante(actual.resultado_visible_hasta)
    if (resultado !== null && resultado > ahoraBackend.value) return resultado

    return null
  }

  function sincronizarReloj(): void {
    detenerReloj()
    ahoraLocal.value = Date.now()

    if (fronteraTemporalPendiente() === null) return

    intervalo = setInterval(() => {
      ahoraLocal.value = Date.now()
      if (fronteraTemporalPendiente() === null) detenerReloj()
    }, INTERVALO_RELOJ_MS)
  }

  watch(
    estado,
    (nuevoEstado) => {
      const generadoEn = nuevoEstado ? Date.parse(nuevoEstado.generado_en) : Number.NaN
      // Un payload repetido con la misma marca temporal no vuelve a calibrar el
      // reloj y, por lo tanto, tampoco puede reiniciar visualmente un deadline.
      if (Number.isFinite(generadoEn) && generadoEn !== ultimoGeneradoEn) {
        desfaseBackend.value = generadoEn - Date.now()
        ultimoGeneradoEn = generadoEn
      } else if (!Number.isFinite(generadoEn)) {
        desfaseBackend.value = 0
        ultimoGeneradoEn = null
      }
      sincronizarReloj()
    },
    { immediate: true },
  )

  onScopeDispose(detenerReloj)

  return { votacion, segundosCuentaRegresiva }
}
