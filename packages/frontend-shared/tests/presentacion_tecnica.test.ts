/**
 * Reloj de presentación del plano técnico (WP-056).
 *
 * Lo que se comprueba acá es que la pantalla **anima** la cuenta regresiva pero no
 * **decide** ninguna transición: el estado `EN_VIVO` sólo aparece cuando lo publica el
 * backend, aunque el contador visual ya haya llegado a cero. También se verifica que el
 * reloj local se apaga cuando no queda ninguna frontera pendiente, que es la forma de
 * garantizar que no se introdujo polling encubierto.
 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { effectScope, ref } from 'vue'
import type { AvisoTecnicoProyectado, TransmisionProyectada } from '@sis-leg/api-client'
import {
  usePresentacionTecnica,
  type EntradaPresentacionTecnica,
} from '../src/presentacion_tecnica'

const AHORA = Date.parse('2026-09-02T10:00:00.000Z')

const scopes: ReturnType<typeof effectScope>[] = []

afterEach(() => {
  while (scopes.length > 0) scopes.pop()?.stop()
  vi.useRealTimers()
})

/** Ejecuta el composable dentro de un scope propio, como haría un componente. */
function montar(entrada: ReturnType<typeof ref<EntradaPresentacionTecnica>>) {
  const scope = effectScope()
  scopes.push(scope)
  return scope.run(() => usePresentacionTecnica(entrada as never))!
}

function transmision(parcial: Partial<TransmisionProyectada> = {}): TransmisionProyectada {
  return {
    estado: parcial.estado ?? 'APAGADO',
    iniciada_en: parcial.iniciada_en ?? null,
    en_vivo_desde: parcial.en_vivo_desde ?? null,
    cuenta_regresiva_segundos: parcial.cuenta_regresiva_segundos ?? null,
    segundos_restantes: parcial.segundos_restantes ?? null,
  }
}

function aviso(expiraEn: string | null): AvisoTecnicoProyectado {
  return {
    aviso_id: 'aviso-1',
    texto: 'Aviso de prueba',
    destino: 'AMBOS',
    publicado_en: '2026-09-02T10:00:00.000Z',
    expira_en: expiraEn,
    segundos_restantes: null,
  }
}

describe('usePresentacionTecnica', () => {
  it('no informa cuenta regresiva fuera del estado CUENTA_REGRESIVA', () => {
    vi.useFakeTimers()
    vi.setSystemTime(AHORA)
    const entrada = ref<EntradaPresentacionTecnica>({
      transmision: transmision({ estado: 'EN_VIVO', en_vivo_desde: '2026-09-02T09:59:00.000Z' }),
      avisos: [],
      generadoEn: '2026-09-02T10:00:00.000Z',
    })

    const { segundosTransmision } = montar(entrada)

    expect(segundosTransmision.value).toBeNull()
  })

  it('hace bajar el contador con el reloj local entre snapshots', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(AHORA)
    const entrada = ref<EntradaPresentacionTecnica>({
      transmision: transmision({
        estado: 'CUENTA_REGRESIVA',
        en_vivo_desde: '2026-09-02T10:00:10.000Z',
        cuenta_regresiva_segundos: 10,
      }),
      avisos: [],
      generadoEn: '2026-09-02T10:00:00.000Z',
    })

    const { segundosTransmision } = montar(entrada)
    expect(segundosTransmision.value).toBe(10)

    await vi.advanceTimersByTimeAsync(4_000)
    expect(segundosTransmision.value).toBe(6)
  })

  it('se detiene en cero y nunca declara EN VIVO por su cuenta', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(AHORA)
    const entrada = ref<EntradaPresentacionTecnica>({
      transmision: transmision({
        estado: 'CUENTA_REGRESIVA',
        en_vivo_desde: '2026-09-02T10:00:03.000Z',
        cuenta_regresiva_segundos: 3,
      }),
      avisos: [],
      generadoEn: '2026-09-02T10:00:00.000Z',
    })

    const { segundosTransmision } = montar(entrada)

    // Se avanza mucho más allá de la frontera: el contador se queda en cero y el estado
    // observable sigue siendo CUENTA_REGRESIVA hasta que el backend publique otra cosa.
    await vi.advanceTimersByTimeAsync(20_000)
    expect(segundosTransmision.value).toBe(0)
    expect(entrada.value.transmision?.estado).toBe('CUENTA_REGRESIVA')
  })

  it('corrige el desfase del reloj del equipo con generado_en', () => {
    vi.useFakeTimers()
    vi.setSystemTime(AHORA)
    // El equipo va treinta segundos adelantado respecto del backend.
    const entrada = ref<EntradaPresentacionTecnica>({
      transmision: transmision({
        estado: 'CUENTA_REGRESIVA',
        en_vivo_desde: '2026-09-02T09:59:50.000Z',
        cuenta_regresiva_segundos: 20,
      }),
      avisos: [],
      generadoEn: '2026-09-02T09:59:30.000Z',
    })

    const { segundosTransmision } = montar(entrada)

    // Sin calibrar daría cero; con el desfase aplicado faltan los 20 s reales.
    expect(segundosTransmision.value).toBe(20)
  })

  it('cronometra el vencimiento de un aviso y respeta el que no vence', () => {
    vi.useFakeTimers()
    vi.setSystemTime(AHORA)
    const conVencimiento = aviso('2026-09-02T10:00:45.000Z')
    const sinVencimiento = aviso(null)
    const entrada = ref<EntradaPresentacionTecnica>({
      transmision: transmision(),
      avisos: [conVencimiento, sinVencimiento],
      generadoEn: '2026-09-02T10:00:00.000Z',
    })

    const { segundosRestantesAviso } = montar(entrada)

    expect(segundosRestantesAviso(conVencimiento)).toBe(45)
    expect(segundosRestantesAviso(sinVencimiento)).toBeNull()
    expect(segundosRestantesAviso(null)).toBeNull()
  })

  it('no deja ningún temporizador vivo cuando no hay fronteras pendientes', () => {
    vi.useFakeTimers()
    vi.setSystemTime(AHORA)
    const entrada = ref<EntradaPresentacionTecnica>({
      transmision: transmision({ estado: 'APAGADO' }),
      avisos: [aviso(null)],
      generadoEn: '2026-09-02T10:00:00.000Z',
    })

    montar(entrada)

    // Sin cuenta regresiva ni vencimientos no hace falta redibujar: cero temporizadores.
    expect(vi.getTimerCount()).toBe(0)
  })

  it('libera el temporizador al destruirse el scope del componente', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(AHORA)
    const entrada = ref<EntradaPresentacionTecnica>({
      transmision: transmision({
        estado: 'CUENTA_REGRESIVA',
        en_vivo_desde: '2026-09-02T10:05:00.000Z',
        cuenta_regresiva_segundos: 300,
      }),
      avisos: [],
      generadoEn: '2026-09-02T10:00:00.000Z',
    })

    montar(entrada)
    expect(vi.getTimerCount()).toBeGreaterThan(0)

    scopes.pop()?.stop()
    expect(vi.getTimerCount()).toBe(0)
  })
})
