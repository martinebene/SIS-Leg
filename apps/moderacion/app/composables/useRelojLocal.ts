/**
 * Reloj visual y ancla de duración para la cabecera de Moderación.
 *
 * La hora del puesto es local y solo orientativa. La duración de sesión, en cambio,
 * parte de una diferencia confirmada entre `generado_en` y `fecha_hora_apertura`, dos
 * marcas emitidas por el mismo reloj backend. Entre snapshots se suma exclusivamente
 * el tiempo local transcurrido; no hay polling ni llamadas de red adicionales.
 */

import { computed, onMounted, onScopeDispose, ref, watch, type ComputedRef, type Ref } from 'vue'
import type { EstadoGlobal } from '@sis-leg/api-client'
import { calcularDuracionEnSnapshot, formatearDuracion } from '../utils/tiempo'

/** Datos mínimos de un snapshot necesarios para anclar la duración visual. */
export interface AnclaSesionModeracion {
  /** Estado global autoritativo: solo SESION_ABIERTA habilita la duración. */
  estadoGlobal: EstadoGlobal | null
  /** Momento en el que backend construyó la baseline recibida. */
  generadoEn: string | null
  /** Apertura formal de la sesión incluida en esa misma baseline. */
  fechaHoraApertura: string | null
}

/** Superficie reactiva consumida por la cabecera. */
export interface RelojLocal {
  /** Instante local vigente para presentar fecha y hora del puesto. */
  ahora: Ref<Date>
  /** Duración anclada por el último snapshot válido de una sesión abierta. */
  tiempoSesion: ComputedRef<string | null>
}

/**
 * Crea el único ticker visual de la cabecera y lo asocia al ciclo de vida de Vue.
 *
 * Cada cambio de baseline reemplaza el ancla. Si la conexión se interrumpe y no llega
 * otra baseline, el valor conserva la última duración confirmada y continúa avanzando
 * con el reloj local. Al salir de SESION_ABIERTA se descarta inmediatamente el ancla.
 *
 * @param ancla Datos reactivos extraídos del snapshot de Moderación.
 * @returns Hora local y texto de duración, ambos reactivos y sin efectos de red.
 */
export function useRelojLocal(ancla: Ref<AnclaSesionModeracion>): RelojLocal {
  const ahora = ref(new Date())
  const duracionAnclada = ref<number | null>(null)
  const recepcionLocal = ref<number | null>(null)
  let identificadorIntervalo: ReturnType<typeof setInterval> | null = null

  function actualizar(): void {
    ahora.value = new Date()
  }

  /** Reemplaza el ancla únicamente cuando las dos marcas backend son utilizables. */
  function reanclar(nuevaAncla: AnclaSesionModeracion): void {
    if (
      nuevaAncla.estadoGlobal !== 'SESION_ABIERTA' ||
      !nuevaAncla.generadoEn ||
      !nuevaAncla.fechaHoraApertura
    ) {
      duracionAnclada.value = null
      recepcionLocal.value = null
      return
    }

    const duracion = calcularDuracionEnSnapshot(nuevaAncla.generadoEn, nuevaAncla.fechaHoraApertura)
    const recibidoEn = Date.now()
    ahora.value = new Date(recibidoEn)
    duracionAnclada.value = duracion
    recepcionLocal.value = duracion === null ? null : recibidoEn
  }

  const tiempoSesion = computed(() => {
    if (duracionAnclada.value === null || recepcionLocal.value === null) return null

    // El elapsed nunca puede restar duración. Esto cubre ajustes hacia atrás del
    // reloj del navegador sin alterar la baseline ya confirmada por backend.
    const transcurridoLocal = Math.max(0, ahora.value.getTime() - recepcionLocal.value)
    return formatearDuracion(duracionAnclada.value + transcurridoLocal)
  })

  watch(ancla, reanclar, { immediate: true })

  onMounted(() => {
    actualizar()
    identificadorIntervalo = setInterval(actualizar, 1000)
  })

  onScopeDispose(() => {
    if (identificadorIntervalo !== null) clearInterval(identificadorIntervalo)
    identificadorIntervalo = null
  })

  return { ahora, tiempoSesion }
}
