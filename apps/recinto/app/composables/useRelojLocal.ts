/**
 * Reloj visual de la Pantalla del Recinto.
 *
 * La fecha/hora del monitor y la duración visible de una sesión no son estado
 * institucional. Este composable actualiza una referencia local una vez por
 * segundo, sin polling ni llamadas de red, y libera el intervalo al desmontar
 * el componente que lo usa.
 */

import { computed, onMounted, onScopeDispose, ref, watch, type ComputedRef, type Ref } from 'vue'
import type { EstadoRecinto } from '@sis-leg/api-client'
import { calcularDuracionEnSnapshot, formatearDuracion } from '../utils/tiempo'

export interface RelojLocal {
  /** Instante local vigente para las presentaciones de cabecera. */
  ahora: Ref<Date>
  /** Duración anclada por el último snapshot backend de una sesión abierta. */
  tiempoSesion: ComputedRef<string | null>
}

/**
 * Crea un reloj cancelable y ancla la duración a snapshots de EstadoRecinto.
 *
 * Cada baseline válida aporta dos marcas del mismo reloj backend. La resta se
 * captura junto con el instante local de recepción; desde allí solo se suma el
 * tiempo local transcurrido. Si la red se corta, el último ancla sigue viva. Si
 * llega otra baseline, reemplaza completamente la anterior.
 */
export function useRelojLocal(estado: Ref<EstadoRecinto | null>): RelojLocal {
  const ahora = ref(new Date())
  const duracionAnclada = ref<number | null>(null)
  const recepcionLocal = ref<number | null>(null)
  let intervalo: ReturnType<typeof setInterval> | null = null

  function actualizar(): void {
    ahora.value = new Date()
  }

  /** Reemplaza el ancla solo con una sesión abierta y dos marcas válidas. */
  function reanclar(nuevoEstado: EstadoRecinto | null): void {
    const sesion = nuevoEstado?.estado_global === 'SESION_ABIERTA' ? nuevoEstado.sesion : null
    if (!nuevoEstado || !sesion) {
      duracionAnclada.value = null
      recepcionLocal.value = null
      return
    }

    const duracion = calcularDuracionEnSnapshot(nuevoEstado.generado_en, sesion.fecha_hora_apertura)
    const recibidoEn = Date.now()
    ahora.value = new Date(recibidoEn)
    duracionAnclada.value = duracion
    recepcionLocal.value = duracion === null ? null : recibidoEn
  }

  const tiempoSesion = computed(() => {
    if (duracionAnclada.value === null || recepcionLocal.value === null) return null
    const transcurridoLocal = Math.max(0, ahora.value.getTime() - recepcionLocal.value)
    return formatearDuracion(duracionAnclada.value + transcurridoLocal)
  })

  watch(estado, reanclar, { immediate: true })

  onMounted(() => {
    actualizar()
    intervalo = setInterval(actualizar, 1000)
  })

  onScopeDispose(() => {
    if (intervalo !== null) clearInterval(intervalo)
    intervalo = null
  })

  return { ahora, tiempoSesion }
}
