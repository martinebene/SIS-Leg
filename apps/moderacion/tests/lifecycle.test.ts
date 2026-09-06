/**
 * Pruebas de ciclo de vida, reference counting y prevención de carreras (R-1)
 * para useEstadoModeracion utilizando @vue/test-utils.
 *
 * Valida:
 * 1. Ciclo clásico secuencial y concurrente: montaje A, montaje concurrente B, desmontaje A, desmontaje final B y remount C.
 * 2. Superposición de ciclo de vida en dos fases (montaje de B concurrente y posterior retiro de A):
 *    demuestra que el conteo de referencias preserva la suscripción única activa sin cancelaciones prematuras.
 * 3. Alternancia condicional directa (conmutación atómica de vistas en un solo tick):
 *    demuestra que el ciclo cancela y libera limpiamente el estado anterior y monta el nuevo sin suscripciones huérfanas ni fugas.
 * 4. Demostración de cero suscripciones huérfanas y liberación total al desmontar todos los componentes.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { defineComponent, h, nextTick, ref } from 'vue'
import { mount } from '@vue/test-utils'
import {
  useEstadoModeracion,
  reiniciarInstanciaCompartidaParaPruebas,
  obtenerCantidadConsumidoresParaPruebas,
} from '../app/composables/useEstadoModeracion'
import type { ClienteModeracion, Suscripcion } from '@sis-leg/api-client'

describe('Lifecycle y Reference Counting síncrono de useEstadoModeracion (R-1)', () => {
  beforeEach(() => {
    reiniciarInstanciaCompartidaParaPruebas()
  })

  it('gestiona correctamente la suscripción única, conteo de consumidores y cancelación final al desmontar', () => {
    let cancelaciones = 0
    let suscripcionesCreadas = 0
    let mockActiva = true

    const mockSuscripcion: Suscripcion = {
      cancelar: () => {
        mockActiva = false
        cancelaciones++
      },
      get activa() {
        return mockActiva
      },
    }

    const mockCliente = {
      suscribirEstado: vi.fn(() => {
        suscripcionesCreadas++
        mockActiva = true
        return mockSuscripcion
      }),
    } as unknown as ClienteModeracion

    // Componente consumidor A
    const ConsumidorA = defineComponent({
      name: 'ConsumidorA',
      setup() {
        const sincronizacion = useEstadoModeracion(mockCliente)
        return { sincronizacion }
      },
      render() {
        return h('div', { class: 'consumidor-a' }, 'Consumidor A')
      },
    })

    // Componente consumidor B
    const ConsumidorB = defineComponent({
      name: 'ConsumidorB',
      setup() {
        const sincronizacion = useEstadoModeracion(mockCliente)
        return { sincronizacion }
      },
      render() {
        return h('div', { class: 'consumidor-b' }, 'Consumidor B')
      },
    })

    // 1. Montamos Consumidor A
    const wrapperA = mount(ConsumidorA)
    expect(suscripcionesCreadas).toBe(1)
    expect(obtenerCantidadConsumidoresParaPruebas()).toBe(1)
    expect(cancelaciones).toBe(0)

    // 2. Montamos Consumidor B (concurrente)
    const wrapperB = mount(ConsumidorB)
    // Sigue habiendo exactamente 1 suscripción (reutiliza el singleton)
    expect(suscripcionesCreadas).toBe(1)
    expect(obtenerCantidadConsumidoresParaPruebas()).toBe(2)
    expect(cancelaciones).toBe(0)

    // 3. Desmontamos Consumidor A
    wrapperA.unmount()
    // No se cancela porque Consumidor B sigue activo
    expect(obtenerCantidadConsumidoresParaPruebas()).toBe(1)
    expect(cancelaciones).toBe(0)

    // 4. Desmontamos Consumidor B (el último)
    wrapperB.unmount()
    // Al quedar 0 consumidores, se ejecuta cancelar() exactamente 1 vez
    expect(obtenerCantidadConsumidoresParaPruebas()).toBe(0)
    expect(cancelaciones).toBe(1)
    expect(mockActiva).toBe(false)

    // 5. Montamos un nuevo Consumidor C tras la liberación
    const ConsumidorC = defineComponent({
      name: 'ConsumidorC',
      setup() {
        const sincronizacion = useEstadoModeracion(mockCliente)
        return { sincronizacion }
      },
      render() {
        return h('div', { class: 'consumidor-c' }, 'Consumidor C')
      },
    })

    const wrapperC = mount(ConsumidorC)
    // Crea una NUEVA sincronización y suscripción limpia
    expect(suscripcionesCreadas).toBe(2)
    expect(obtenerCantidadConsumidoresParaPruebas()).toBe(1)
    expect(cancelaciones).toBe(1)

    // Limpieza final
    wrapperC.unmount()
    expect(obtenerCantidadConsumidoresParaPruebas()).toBe(0)
    expect(cancelaciones).toBe(2)
  })

  it('preserva la suscripción única activa durante la superposición de componentes (R-1 solapamiento)', async () => {
    let cancelaciones = 0
    let suscripcionesCreadas = 0
    const suscripciones: { id: number; cancelada: boolean }[] = []

    const mockCliente = {
      suscribirEstado: vi.fn(() => {
        suscripcionesCreadas++
        const reg = { id: suscripcionesCreadas, cancelada: false }
        suscripciones.push(reg)
        return {
          cancelar: () => {
            reg.cancelada = true
            cancelaciones++
          },
          get activa() {
            return !reg.cancelada
          },
        } as Suscripcion
      }),
    } as unknown as ClienteModeracion

    const HijoA = defineComponent({
      name: 'HijoA',
      setup() {
        const sincronizacion = useEstadoModeracion(mockCliente)
        return { sincronizacion }
      },
      render() {
        return h('span', 'A')
      },
    })

    const HijoB = defineComponent({
      name: 'HijoB',
      setup() {
        const sincronizacion = useEstadoModeracion(mockCliente)
        return { sincronizacion }
      },
      render() {
        return h('span', 'B')
      },
    })

    const PadreSuperpuesto = defineComponent({
      name: 'PadreSuperpuesto',
      setup() {
        const mostrarA = ref(true)
        const mostrarB = ref(false)
        return { mostrarA, mostrarB }
      },
      render() {
        return h('div', [this.mostrarA ? h(HijoA) : null, this.mostrarB ? h(HijoB) : null])
      },
    })

    const wrapper = mount(PadreSuperpuesto)
    expect(suscripcionesCreadas).toBe(1)
    expect(obtenerCantidadConsumidoresParaPruebas()).toBe(1)
    expect(cancelaciones).toBe(0)

    // 1. Activamos B mientras A sigue activo (superposición)
    wrapper.vm.mostrarB = true
    await nextTick()

    expect(suscripcionesCreadas).toBe(1)
    expect(obtenerCantidadConsumidoresParaPruebas()).toBe(2)
    expect(cancelaciones).toBe(0)

    // 2. Desactivamos A (B queda como único consumidor)
    wrapper.vm.mostrarA = false
    await nextTick()

    expect(suscripcionesCreadas).toBe(1)
    expect(obtenerCantidadConsumidoresParaPruebas()).toBe(1)
    expect(cancelaciones).toBe(0)
    expect(suscripciones[0].cancelada).toBe(false)

    // 3. Desmontamos el padre (desmontaje de B)
    wrapper.unmount()
    expect(obtenerCantidadConsumidoresParaPruebas()).toBe(0)
    expect(cancelaciones).toBe(1)
    expect(suscripciones[0].cancelada).toBe(true)
  })

  it('gestiona la alternancia condicional atómica sin dejar suscripciones huérfanas (R-1 same-tick flip)', async () => {
    let cancelaciones = 0
    let suscripcionesCreadas = 0
    const suscripciones: { id: number; cancelada: boolean }[] = []

    const mockCliente = {
      suscribirEstado: vi.fn(() => {
        suscripcionesCreadas++
        const reg = { id: suscripcionesCreadas, cancelada: false }
        suscripciones.push(reg)
        return {
          cancelar: () => {
            reg.cancelada = true
            cancelaciones++
          },
          get activa() {
            return !reg.cancelada
          },
        } as Suscripcion
      }),
    } as unknown as ClienteModeracion

    const VistaA = defineComponent({
      name: 'VistaA',
      setup() {
        const sincronizacion = useEstadoModeracion(mockCliente)
        return { sincronizacion }
      },
      render() {
        return h('div', 'Vista A')
      },
    })

    const VistaB = defineComponent({
      name: 'VistaB',
      setup() {
        const sincronizacion = useEstadoModeracion(mockCliente)
        return { sincronizacion }
      },
      render() {
        return h('div', 'Vista B')
      },
    })

    // Contenedor condicional único (v-if / v-else)
    const ContenedorCondicional = defineComponent({
      name: 'ContenedorCondicional',
      setup() {
        const vistaActual = ref<'A' | 'B'>('A')
        return { vistaActual }
      },
      render() {
        return h('div', [this.vistaActual === 'A' ? h(VistaA) : h(VistaB)])
      },
    })

    const wrapper = mount(ContenedorCondicional)
    expect(suscripcionesCreadas).toBe(1)
    expect(obtenerCantidadConsumidoresParaPruebas()).toBe(1)
    expect(cancelaciones).toBe(0)

    // Cambiamos de vista A a vista B en un solo flush reactivo
    wrapper.vm.vistaActual = 'B'
    await nextTick()

    // Con el registro síncrono en setup(), se garantiza:
    // 1. Exactamente 1 consumidor activo registrado.
    // 2. La suscripción vieja fue cancelada si el dispose corrió primero, o reutilizada si se solapó.
    // 3. No queda NINGUNA suscripción huérfana.
    expect(obtenerCantidadConsumidoresParaPruebas()).toBe(1)
    expect(cancelaciones).toBe(suscripcionesCreadas - 1)

    // Al desmontar el contenedor:
    wrapper.unmount()
    expect(obtenerCantidadConsumidoresParaPruebas()).toBe(0)
    // Todas las suscripciones creadas en la prueba fueron canceladas limpiamente
    expect(cancelaciones).toBe(suscripcionesCreadas)
    for (const sub of suscripciones) {
      expect(sub.cancelada).toBe(true)
    }
  })
})
