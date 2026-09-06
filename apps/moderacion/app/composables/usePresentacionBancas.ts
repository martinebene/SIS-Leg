/**
 * Ciclo visual de los resultados individuales de Q3.
 *
 * El snapshot de Moderación conserva la votación para Q1 y para la conducción
 * institucional. Q3, en cambio, debe retirar colores y etiquetas en la misma
 * frontera que la Pantalla del Recinto. Este composable no inventa una duración:
 * calibra el reloj local con `generado_en` y compara contra el deadline backend
 * `resultado_visible_hasta` usando la regla pura compartida por ambas apps.
 */

import { computed, onScopeDispose, ref, watch, type ComputedRef, type Ref } from 'vue'
import type { EstadoModeracion, VotoModeracion } from '@sis-leg/api-client'
import { resultadoIndividualVisible } from '@sis-leg/frontend-shared'

const INTERVALO_RELOJ_MS = 250

export interface PresentacionBancasModeracion {
  /** Votos que Q3 puede pintar ahora; Q1 continúa consumiendo el DTO completo. */
  votosIndividuales: ComputedRef<VotoModeracion[] | null>
}

/** Convierte una marca ISO del contrato en milisegundos utilizables. */
function instante(timestamp: string | null): number | null {
  if (timestamp === null) return null
  const valor = Date.parse(timestamp)
  return Number.isFinite(valor) ? valor : null
}

/**
 * Deriva exclusivamente la presentación temporal de las bancas de Q3.
 *
 * Una nueva baseline recalibra el desfase con el reloj backend. Entre snapshots,
 * el ticker solo actualiza la vista; no hace polling ni muta estado institucional.
 */
export function usePresentacionBancas(
  estado: Ref<EstadoModeracion | null>,
): PresentacionBancasModeracion {
  const ahoraLocal = ref(Date.now())
  const desfaseBackend = ref(0)
  let intervalo: ReturnType<typeof setInterval> | null = null
  let ultimoGeneradoEn: number | null = null

  const ahoraBackend = computed(() => ahoraLocal.value + desfaseBackend.value)

  const votosIndividuales = computed<VotoModeracion[] | null>(() => {
    const votacion = estado.value?.votacion
    if (!votacion) return null

    const visible = resultadoIndividualVisible({
      estadoRecepcion: votacion.estado_recepcion,
      resultado: votacion.resultado,
      resultadoVisibleHasta: votacion.resultado_visible_hasta,
      ahoraBackend: ahoraBackend.value,
    })
    return visible ? votacion.votos_individuales : null
  })

  function detenerReloj(): void {
    if (intervalo === null) return
    clearInterval(intervalo)
    intervalo = null
  }

  function fronteraPendiente(): number | null {
    const limite = instante(estado.value?.votacion?.resultado_visible_hasta ?? null)
    return limite !== null && limite > ahoraBackend.value ? limite : null
  }

  function sincronizarReloj(): void {
    detenerReloj()
    ahoraLocal.value = Date.now()
    if (fronteraPendiente() === null) return

    intervalo = setInterval(() => {
      ahoraLocal.value = Date.now()
      if (fronteraPendiente() === null) detenerReloj()
    }, INTERVALO_RELOJ_MS)
  }

  watch(
    estado,
    (nuevoEstado) => {
      const generadoEn = nuevoEstado ? Date.parse(nuevoEstado.generado_en) : Number.NaN
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

  return { votosIndividuales }
}
