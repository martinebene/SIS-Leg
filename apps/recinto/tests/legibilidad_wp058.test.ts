/**
 * Legibilidad y estados de la Pantalla del Recinto (WP-058).
 *
 * Acá viven las comprobaciones que se pueden hacer sobre el DOM: qué nivel de
 * quórum declara la pantalla en cada relación presentes/requerido y qué rótulo
 * acompaña a la cuenta regresiva de una votación ya abierta.
 *
 * WP-097 cambió el **vehículo** del primer dato, no su contenido: el bloque de
 * quórum quedó reducido a título y número por pedido de HUMAN_GATE, así que el
 * nivel se lee del atributo `data-nivel-quorum` en lugar de la palabra impresa.
 * Los tres casos de borde que exigía WP-058 se siguen comprobando, y se agrega
 * una regresión que prohíbe que las redacciones vuelvan sin decisión humana.
 *
 * La parte geométrica del WP —cuerpos tipográficos, altura de la cabecera,
 * contención dentro del content box del bloque de transmisión y escala útil del
 * bitmap de cada banca— no se puede medir acá porque este entorno no calcula
 * layout: se mide con bounding boxes en `tests/playwright/shell_recinto.spec.ts`.
 */

import { mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import IndicadorQuorumPublico from '../app/components/IndicadorQuorumPublico.vue'
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

/**
 * Monta el indicador con una proyección de quórum concreta.
 *
 * `alcanzado` se calcula igual que el backend (presentes >= mínimo) porque la
 * pantalla nunca decide esa condición: sólo elige cómo enunciarla.
 */
function montarQuorum(cantidadPresentes: number, requerido: number, total: number): VueWrapper {
  const wrapper = mount(IndicadorQuorumPublico, {
    props: {
      quorum: {
        cantidad_presentes: cantidadPresentes,
        requerido,
        alcanzado: cantidadPresentes >= requerido,
      },
      total,
    },
  })
  montados.push(wrapper)
  return wrapper
}

/**
 * Nivel declarado por el indicador, leído del atributo del contenedor.
 *
 * Hasta WP-097 este dato tenía dos vehículos redundantes: el atributo y la
 * palabra impresa debajo del número. HUMAN_GATE pidió dejar el bloque de quórum
 * sólo con título y número, así que la palabra ya no se dibuja y el atributo
 * queda como el único portador del nivel. Las tres distinciones que WP-058
 * exigía —falta, límite exacto y holgura— se siguen comprobando igual, sobre los
 * mismos casos de borde.
 */
function nivelDeclarado(wrapper: VueWrapper): string | null {
  return wrapper.get('[data-testid="panel-quorum"]').element.getAttribute('data-nivel-quorum')
}

describe('Quórum público con tres niveles distinguibles (WP-058, forma revisada por WP-097)', () => {
  it('distingue la falta, el empate exacto y la holgura', () => {
    // Por debajo del mínimo reglamentario.
    expect(nivelDeclarado(montarQuorum(6, 7, 12))).toBe('insuficiente')
    // Exactamente en el mínimo: alcanzado, pero sin margen ante una ausencia.
    expect(nivelDeclarado(montarQuorum(7, 7, 12))).toBe('limite')
    // Por encima del mínimo.
    expect(nivelDeclarado(montarQuorum(8, 7, 12))).toBe('holgado')
  })

  it('el empate exacto sigue siendo quórum alcanzado para el backend', () => {
    const limite = montarQuorum(7, 7, 12)

    // La forma cambia, la condición reglamentaria no: el nivel de WP-054 deriva
    // de la misma comparación de números ya proyectados y no recalcula la regla.
    expect(nivelDeclarado(limite)).toBe('limite')
    expect(nivelDeclarado(limite)).not.toBe('insuficiente')
  })

  it('un mínimo de una sola banca también distingue límite de holgura', () => {
    // Caso de borde: con `requerido = 1`, un solo presente ya es el límite.
    expect(nivelDeclarado(montarQuorum(1, 1, 3))).toBe('limite')
    expect(nivelDeclarado(montarQuorum(2, 1, 3))).toBe('holgado')
    expect(nivelDeclarado(montarQuorum(0, 1, 3))).toBe('insuficiente')
  })

  it('sin quórum proyectado no declara ningún nivel', () => {
    const wrapper = mount(IndicadorQuorumPublico, { props: { quorum: null, total: 12 } })
    montados.push(wrapper)

    expect(nivelDeclarado(wrapper)).toBeNull()
    expect(wrapper.text()).toContain('Quórum sin información')
  })

  /**
   * Regresión de WP-097: las tres redacciones que introdujo WP-058 dejaron de
   * dibujarse. Se comprueba explícitamente para que nadie las reintroduzca sin
   * una decisión humana nueva.
   */
  it('ya no imprime ninguna de las tres redacciones de WP-058', () => {
    for (const wrapper of [
      montarQuorum(6, 7, 12),
      montarQuorum(7, 7, 12),
      montarQuorum(8, 7, 12),
    ]) {
      expect(wrapper.find('[data-testid="estado-quorum"]').exists()).toBe(false)
      expect(wrapper.text()).not.toContain('Sin quórum')
      expect(wrapper.text()).not.toContain('Quórum límite')
      expect(wrapper.text()).not.toContain('Quórum alcanzado')
    }
  })
})

describe('Rótulo de la cuenta regresiva de votación (WP-058)', () => {
  /**
   * Sesión abierta con una votación ya `EN_CURSO` y cuenta regresiva vigente.
   *
   * Es el único escenario en el que la pantalla dibuja el countdown: la
   * recepción ya está abierta, así que el número es el tiempo que resta para
   * votar y no una espera previa a la apertura.
   */
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

  /**
   * Regresión pedida explícitamente por WP-058.
   *
   * El rótulo correcto ya estaba en `main` desde WP-054; este WP no lo cambia,
   * lo verifica y deja fijada la prohibición de que `Comienza en` reaparezca en
   * *toda* la pantalla, no sólo dentro del recuadro del countdown.
   */
  it('nunca vuelve a decir "Comienza en" mientras la votación está EN_CURSO', () => {
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

    expect(wrapper.get('[data-testid="countdown-votacion"]').text()).toContain('Votación en curso')
    expect(wrapper.text()).not.toContain('Comienza en')
    expect(wrapper.html()).not.toContain('Comienza en')
  })
})
