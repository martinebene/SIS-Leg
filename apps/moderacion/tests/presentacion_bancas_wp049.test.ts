/** Pruebas del ciclo visual Q3 gobernado por el deadline común de backend. */

import { effectScope, ref, type ComputedRef, type EffectScope } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { EstadoModeracion, VotoModeracion } from '@sis-leg/api-client'
import { usePresentacionBancas } from '../app/composables/usePresentacionBancas'

const HORA_BASE = '2026-09-01T12:00:00Z'
const VOTOS: VotoModeracion[] = [
  {
    dni: '30000001',
    nombre: 'Concejal',
    apellido: 'Uno',
    banca: 1,
    valor: 'POSITIVO',
  },
]

/** Construye solo la porción de EstadoModeracion consumida por el composable. */
function crearEstado(
  cambios: Partial<NonNullable<EstadoModeracion['votacion']>> = {},
): EstadoModeracion {
  return {
    generado_en: HORA_BASE,
    votacion: {
      estado_recepcion: 'CERRADA',
      resultado: 'APROBADA',
      resultado_visible_hasta: '2026-09-01T12:00:02Z',
      votos_individuales: VOTOS,
      ...cambios,
    },
  } as EstadoModeracion
}

function iniciar(estadoInicial: EstadoModeracion): {
  estado: ReturnType<typeof ref<EstadoModeracion | null>>
  votos: ComputedRef<VotoModeracion[] | null>
  scope: EffectScope
} {
  const estado = ref<EstadoModeracion | null>(estadoInicial)
  const scope = effectScope()
  let votos: ComputedRef<VotoModeracion[] | null> | undefined
  scope.run(() => {
    votos = usePresentacionBancas(estado).votosIndividuales
  })
  if (!votos) throw new Error('El composable no creó la proyección de votos')
  return { estado, votos, scope }
}

afterEach(() => {
  vi.useRealTimers()
})

describe('usePresentacionBancas · WP-049', () => {
  it('retira Q3 al vencer la frontera sin borrar el resultado institucional', () => {
    vi.useFakeTimers()
    vi.setSystemTime(HORA_BASE)
    const { estado, votos, scope } = iniciar(crearEstado())

    expect(votos.value).toEqual(VOTOS)
    vi.advanceTimersByTime(2250)
    expect(votos.value).toBeNull()
    // El composable presenta una vista; nunca modifica el snapshot que Q1 usa.
    expect(estado.value?.votacion?.resultado).toBe('APROBADA')
    expect(estado.value?.votacion?.votos_individuales).toEqual(VOTOS)

    scope.stop()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('durante EN_CURSO ignora sentidos aunque el DTO privado los transporte', () => {
    vi.useFakeTimers()
    vi.setSystemTime(HORA_BASE)
    const { votos, scope } = iniciar(
      crearEstado({
        estado_recepcion: 'EN_CURSO',
        resultado: null,
        resultado_visible_hasta: null,
      }),
    )

    expect(votos.value).toBeNull()
    scope.stop()
  })

  it('una baseline recibida después del deadline no revive el resultado', () => {
    vi.useFakeTimers()
    vi.setSystemTime('2026-09-01T12:00:10Z')
    const estado = crearEstado({ resultado_visible_hasta: '2026-09-01T12:00:02Z' })
    estado.generado_en = '2026-09-01T12:00:10Z'
    const { votos, scope } = iniciar(estado)

    expect(votos.value).toBeNull()
    expect(vi.getTimerCount()).toBe(0)
    scope.stop()
  })
})
