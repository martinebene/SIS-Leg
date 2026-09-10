/**
 * Refinamiento visual de la Pantalla del Recinto (WP-054).
 *
 * Estas pruebas fijan las decisiones humanas del 01/09/2026 que se pueden
 * comprobar sobre el DOM: qué texto se muestra, qué color corresponde a cada
 * relación presentes/requerido y qué estructura hace posible el resultado
 * visual. La geometría concreta —tamaños reales, contención y ausencia de
 * scroll horizontal— se mide aparte en Playwright con bounding boxes, porque el
 * DOM de estas pruebas no calcula layout.
 */

import { mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import IndicadorQuorumPublico from '../app/components/IndicadorQuorumPublico.vue'
import PanelPalabraPublico from '../app/components/PanelPalabraPublico.vue'
import PantallaRecinto from '../app/components/PantallaRecinto.vue'
import {
  crearConcejalesPublicos,
  crearEstadoRecintoPrueba,
  crearVotacionPublicaPrueba,
} from './datos_prueba'

const montados: VueWrapper[] = []

afterEach(() => {
  while (montados.length > 0) montados.pop()?.unmount()
  vi.useRealTimers()
})

/** Monta el indicador con un quórum concreto y recuerda el wrapper para liberarlo. */
function montarQuorum(cantidadPresentes: number, requerido: number, total: number): VueWrapper {
  const wrapper = mount(IndicadorQuorumPublico, {
    props: {
      quorum: {
        cantidad_presentes: cantidadPresentes,
        requerido,
        // `alcanzado` es la condición reglamentaria del backend: presentes >= mínimo.
        alcanzado: cantidadPresentes >= requerido,
      },
      total,
    },
  })
  montados.push(wrapper)
  return wrapper
}

describe('Quórum público como presentes/total (WP-054)', () => {
  it('muestra la fracción completa en lugar de un número suelto', () => {
    const wrapper = montarQuorum(8, 7, 12)

    // El testid conserva su nombre histórico; su contenido es ahora la fracción.
    expect(wrapper.get('[data-testid="cantidad-presentes"]').text()).toBe('8/12')
    /*
      WP-097 eliminó el detalle `Presentes · requiere N` por decisión de
      HUMAN_GATE: el bloque quedó sólo con título y número. El mínimo
      reglamentario lo sigue publicando el backend y lo sigue mostrando la
      pantalla de Moderación, que es la superficie de quien opera.
    */
    expect(wrapper.find('.detalle-quorum').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('requiere 7')
  })

  /**
   * Nivel declarado por el panel.
   *
   * El DOM pedagógico del monorepo expone los atributos por `getAttribute`, no
   * como colección iterable, así que se lee directamente el elemento.
   */
  function nivelDeclarado(wrapper: VueWrapper): string | null {
    return wrapper.get('[data-testid="panel-quorum"]').element.getAttribute('data-nivel-quorum')
  }

  /** Indica si el panel lleva la clase cromática de un nivel concreto. */
  function tieneClaseDeNivel(wrapper: VueWrapper, nivel: string): boolean {
    return wrapper.get('[data-testid="panel-quorum"]').element.classList.contains(`nivel-${nivel}`)
  }

  it('pinta de verde la holgura, de amarillo el mínimo exacto y de rojo la falta', () => {
    // Por encima del mínimo: hay margen ante una ausencia.
    const holgado = montarQuorum(8, 7, 12)
    expect(nivelDeclarado(holgado)).toBe('holgado')
    expect(tieneClaseDeNivel(holgado, 'holgado')).toBe(true)

    // Exactamente en el mínimo: el quórum está alcanzado, pero al límite.
    const limite = montarQuorum(7, 7, 12)
    expect(nivelDeclarado(limite)).toBe('limite')
    // La condición reglamentaria no cambia: igualar el mínimo alcanza quórum.
    // WP-058 lo había distinguido además con palabras; WP-097 dejó el bloque con
    // título y número, así que el color y el atributo vuelven a ser el vehículo
    // único de esa distinción, sin que la distinción se pierda.
    expect(tieneClaseDeNivel(limite, 'limite')).toBe(true)

    // Por debajo del mínimo: sin quórum.
    const insuficiente = montarQuorum(6, 7, 12)
    expect(nivelDeclarado(insuficiente)).toBe('insuficiente')
    expect(tieneClaseDeNivel(insuficiente, 'insuficiente')).toBe(true)
  })

  it('cada nivel usa una clase cromática distinta y sólo una', () => {
    const paneles = {
      holgado: montarQuorum(8, 7, 12),
      limite: montarQuorum(7, 7, 12),
      insuficiente: montarQuorum(6, 7, 12),
    }
    const niveles = ['holgado', 'limite', 'insuficiente'] as const

    for (const nivelPropio of niveles) {
      // Cada panel lleva su clase y ninguna de las otras dos: el color no puede
      // quedar ambiguo entre dos estados reglamentarios distintos.
      for (const nivel of niveles) {
        expect(tieneClaseDeNivel(paneles[nivelPropio], nivel)).toBe(nivel === nivelPropio)
      }
    }
  })

  it('conserva el estado neutro mientras el backend no proyecta quórum', () => {
    const wrapper = mount(IndicadorQuorumPublico, { props: { quorum: null, total: 12 } })
    montados.push(wrapper)

    expect(wrapper.find('[data-testid="cantidad-presentes"]').exists()).toBe(false)
    // Sin quórum proyectado no se declara ningún nivel cromático.
    expect(nivelDeclarado(wrapper) ?? null).toBeNull()
    for (const nivel of ['holgado', 'limite', 'insuficiente']) {
      expect(tieneClaseDeNivel(wrapper, nivel)).toBe(false)
    }
    expect(wrapper.text()).toContain('Quórum sin información')
  })
})

describe('Cola de palabra legible desde el recinto (WP-054)', () => {
  /** Cola de dos pedidos con nombres de longitud realista. */
  const palabraConCola = {
    orador: { nombre: 'Nombre4', apellido: 'Apellido4', banca: 4 },
    cola: [
      { nombre: 'María Eugenia', apellido: 'Fernández Robledo', banca: 7 },
      { nombre: 'Juan', apellido: 'Pérez', banca: 1 },
    ],
  }

  function montarPalabra(): VueWrapper {
    const wrapper = mount(PanelPalabraPublico, { props: { palabra: palabraConCola } })
    montados.push(wrapper)
    return wrapper
  }

  it('expone nombre y banca como datos identificables por separado', () => {
    const wrapper = montarPalabra()

    const nombres = wrapper
      .findAll('[data-testid="nombre-cola-palabra"]')
      .map((nodo) => nodo.text().replace(/\s+/g, ' ').trim())
    const bancas = wrapper
      .findAll('[data-testid="banca-cola-palabra"]')
      .map((nodo) => nodo.text().trim())

    // El orden FIFO recibido se respeta y el orador no aparece en la cola.
    expect(nombres).toEqual(['María Eugenia Fernández Robledo', 'Juan Pérez'])
    expect(bancas).toEqual(['Banca 7', 'Banca 1'])
    expect(wrapper.get('[data-testid="cantidad-pedidos-palabra"]').text()).toBe('2')
  })

  it('conserva el nombre completo en `title` porque en pantalla se recorta', () => {
    const wrapper = montarPalabra()

    const primerNombre = wrapper.findAll('[data-testid="nombre-cola-palabra"]')[0]!
    expect(primerNombre.element.getAttribute('title')).toBe('María Eugenia Fernández Robledo')
  })

  it('mantiene un círculo de orden por pedido, con su numeración FIFO', () => {
    const wrapper = montarPalabra()

    // El círculo sigue siendo el mismo elemento con la misma clase: su tamaño
    // está congelado en el CSS y Playwright verifica que no haya crecido.
    const ordenes = wrapper.findAll('.orden-cola').map((nodo) => nodo.text().trim())
    expect(ordenes).toEqual(['1', '2'])
  })

  it('no dibuja lista cuando no hay pedidos en espera', () => {
    const wrapper = mount(PanelPalabraPublico, {
      props: { palabra: { orador: null, cola: [] } },
    })
    montados.push(wrapper)

    expect(wrapper.find('[data-testid="cola-palabra"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('No hay pedidos en espera')
  })
})

describe('Countdown público de votación (WP-054)', () => {
  /** Sesión abierta con una votación EN_CURSO y cuenta regresiva vigente. */
  function crearSesionConCuentaRegresiva() {
    return crearEstadoRecintoPrueba({
      instancia: 'instancia-prueba',
      revision: 1,
      generado_en: '2026-08-28T10:00:00Z',
      estado_global: 'SESION_ABIERTA',
      sesion: {
        fecha_hora_inicio_preparacion: '2026-08-28T09:30:00Z',
        fecha_hora_apertura: '2026-08-28T09:45:00Z',
        numero_sesion: 59,
        presidencia: 'Ana Presidencia',
        secretaria_legislativa: 'Luis Secretaría',
      },
      filas_bancas: [2, 2],
      concejales: crearConcejalesPublicos(4),
      quorum: { cantidad_presentes: 3, requerido: 3, alcanzado: true },
      palabra: { orador: null, cola: [] },
      votacion: crearVotacionPublicaPrueba({
        estado_recepcion: 'EN_CURSO',
        cuenta_regresiva_hasta: '2026-08-28T10:00:05Z',
      }),
    })
  }

  it('rotula la cuenta regresiva como votación en curso, no como espera previa', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-28T10:00:00Z'))
    const wrapper = mount(PantallaRecinto, {
      props: {
        estado: crearSesionConCuentaRegresiva(),
        estadoConexion: 'CONECTADO',
        desactualizado: false,
      },
    })
    montados.push(wrapper)

    const countdown = wrapper.get('[data-testid="countdown-votacion"]')
    // La recepción ya está abierta: el número es tiempo restante para votar.
    expect(countdown.text()).toContain('Votación en curso')
    expect(countdown.text()).not.toContain('Comienza en')
    expect(countdown.text()).toContain('5')
  })

  it('la pantalla aporta al quórum el total del padrón que ya trae el snapshot', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-28T10:00:00Z'))
    const wrapper = mount(PantallaRecinto, {
      props: {
        estado: crearSesionConCuentaRegresiva(),
        estadoConexion: 'CONECTADO',
        desactualizado: false,
      },
    })
    montados.push(wrapper)

    // Cuatro bancas en el padrón de esta fixture, tres presentes.
    expect(wrapper.get('[data-testid="cantidad-presentes"]').text()).toBe('3/4')
  })
})
