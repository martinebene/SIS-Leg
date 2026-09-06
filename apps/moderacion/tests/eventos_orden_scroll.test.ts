/**
 * Pruebas DOM de WP-041 sobre el componente productivo `PanelEventos`.
 *
 * Demuestran que el cuadrante Eventos:
 *
 * - conserva la semántica acumulativa del filtro (L3, L2+L3, L1+L2+L3);
 * - deriva un orden visual descendente por `seq` sin mutar la baseline;
 * - devuelve la lista al inicio cuando el backend proyecta un `seq` mayor;
 * - no confunde un cambio de filtro con la llegada de actividad nueva;
 * - adopta por completo cada snapshot, incluso ante reinicio de secuencia;
 * - ubica el selector de nivel en la cabecera, fuera del área scrolleable.
 *
 * El backend sigue siendo la única autoridad: cada escenario cambia lo que se
 * ve exclusivamente entregando un snapshot posterior mediante props.
 */

import { afterEach, describe, expect, it } from 'vitest'
import { compile, type Component, ssrContextKey } from 'vue'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import PanelContenedor from '../app/components/PanelContenedor.vue'
import fuentePanelContenedor from '../app/components/PanelContenedor.vue?raw'
import PanelEventos from '../app/components/PanelEventos.vue'
import fuentePanelEventos from '../app/components/PanelEventos.vue?raw'
import type { EstadoModeracion } from '@sis-leg/api-client'

/**
 * El entorno de Vitest compila los SFC para SSR. Esta adaptación adjunta el
 * render de cliente de la misma plantilla productiva para poder interactuar
 * con el DOM y observar el contenedor scrolleable real.
 */
function habilitarRenderCliente(
  componente: Component,
  fuente: string,
  componentesLocales: Record<string, Component> = {},
): void {
  const coincidencia = fuente.match(/<template>([\s\S]*)<\/template>/)
  if (!coincidencia?.[1]) throw new Error('No se encontró la plantilla Vue productiva')

  const compilable = componente as {
    render?: ReturnType<typeof compile>
    components?: Record<string, Component>
    setup?: (props: unknown, contexto: unknown) => unknown
  }
  const setupOriginal = compilable.setup
  if (setupOriginal) {
    compilable.setup = (props, contexto) => {
      const resultado = setupOriginal(props, contexto)
      return typeof resultado === 'object' && resultado !== null ? { ...resultado } : resultado
    }
  }
  compilable.render = compile(coincidencia[1], { hoistStatic: false })
  compilable.components = { ...compilable.components, ...componentesLocales }
}

habilitarRenderCliente(PanelContenedor, fuentePanelContenedor)
habilitarRenderCliente(PanelEventos, fuentePanelEventos, { PanelContenedor })

const wrappers: VueWrapper[] = []

function montar(props: Record<string, unknown>): VueWrapper {
  const wrapper = mount(PanelEventos, {
    props,
    global: {
      // Los SFC llegan precompilados para SSR en Vitest; este contexto mínimo
      // reproduce el que Nuxt aporta al montar el mismo componente en la app.
      provide: { [ssrContextKey]: { modules: new Set() } },
    },
  })
  wrappers.push(wrapper)
  return wrapper
}

afterEach(() => {
  while (wrappers.length) wrappers.pop()?.unmount()
})

type EventoProyectado = EstadoModeracion['eventos_recientes'][number]

/**
 * Construye un evento de auditoría proyectado con los seis datos que la
 * tarjeta debe seguir mostrando: seq, timestamp, nivel, etiqueta, código y
 * mensaje.
 */
function crearEvento(seq: number, nivel: 'L1' | 'L2' | 'L3'): EventoProyectado {
  return {
    seq,
    timestamp: `2026-08-27T10:00:${String(seq).padStart(2, '0')}`,
    nivel,
    etiqueta: `ETIQUETA_${nivel}`,
    codigo_evento: `EVENTO_${nivel}_${seq}`,
    mensaje: `Mensaje del evento ${seq}`,
  } as EventoProyectado
}

/**
 * `PanelEventos` solo consume `eventos_recientes`; el resto del snapshot no
 * interviene en esta proyección, por lo que el fixture se mantiene mínimo.
 */
function crearEstado(eventos: EventoProyectado[]): EstadoModeracion {
  return { eventos_recientes: eventos } as unknown as EstadoModeracion
}

/** Lee los `seq` en el orden en que quedaron renderizados en el DOM. */
function seqRenderizados(wrapper: VueWrapper): number[] {
  return wrapper
    .findAll('[data-testid="evento-reciente"]')
    .map((nodo) => Number(nodo.text().match(/#(\d+)/)?.[1]))
}

/** Devuelve el contenedor con scroll interno del listado. */
function contenedorScrolleable(wrapper: VueWrapper): HTMLElement {
  return wrapper.get('[data-testid="lista-eventos"]').element as HTMLElement
}

describe('WP-041 - Filtro acumulativo por nivel', () => {
  it('arranca en L3 y respeta la semántica acumulativa de L2 y L1', async () => {
    const wrapper = montar({
      estado: crearEstado([crearEvento(1, 'L1'), crearEvento(2, 'L2'), crearEvento(3, 'L3')]),
    })

    expect((wrapper.get('[data-testid="filtro-eventos"]').element as HTMLSelectElement).value).toBe(
      'L3',
    )
    expect(seqRenderizados(wrapper)).toEqual([3])

    await wrapper.get('[data-testid="filtro-eventos"]').setValue('L2')
    expect(seqRenderizados(wrapper)).toEqual([3, 2])

    await wrapper.get('[data-testid="filtro-eventos"]').setValue('L1')
    expect(seqRenderizados(wrapper)).toEqual([3, 2, 1])
  })

  it('muestra un aviso compacto cuando hay eventos pero ninguno coincide con el filtro', () => {
    const wrapper = montar({ estado: crearEstado([crearEvento(7, 'L1')]) })

    expect(wrapper.findAll('[data-testid="evento-reciente"]')).toHaveLength(0)
    expect(wrapper.get('[data-testid="eventos-vacio"]').text()).toContain(
      'No hay eventos para el nivel seleccionado',
    )
  })

  it('muestra el estado vacío cuando el backend no proyecta ningún evento', () => {
    const wrapper = montar({ estado: crearEstado([]) })

    expect(wrapper.get('[data-testid="eventos-vacio"]').text()).toContain(
      'Sin eventos en la sesión activa',
    )
  })
})

describe('WP-041 - Orden visual descendente derivado', () => {
  it('renderiza de mayor a menor seq un snapshot recibido en orden ascendente', () => {
    const wrapper = montar({
      estado: crearEstado([crearEvento(10, 'L3'), crearEvento(11, 'L3'), crearEvento(12, 'L3')]),
    })

    expect(seqRenderizados(wrapper)).toEqual([12, 11, 10])
  })

  it('mantiene el mismo orden y sin duplicados si el snapshot ya llega descendente', () => {
    const wrapper = montar({
      estado: crearEstado([crearEvento(12, 'L3'), crearEvento(11, 'L3'), crearEvento(10, 'L3')]),
    })

    expect(seqRenderizados(wrapper)).toEqual([12, 11, 10])
  })

  it('no reordena ni muta el arreglo recibido en props', () => {
    const eventos = [crearEvento(1, 'L3'), crearEvento(2, 'L3'), crearEvento(3, 'L3')]
    const wrapper = montar({ estado: crearEstado(eventos) })

    expect(seqRenderizados(wrapper)).toEqual([3, 2, 1])
    // La baseline autoritativa conserva exactamente el orden del backend.
    expect(eventos.map((evento) => evento.seq)).toEqual([1, 2, 3])
  })

  it('conserva los seis datos de cada tarjeta en la vista compacta', () => {
    const wrapper = montar({ estado: crearEstado([crearEvento(5, 'L3')]) })
    const tarjeta = wrapper.get('[data-testid="evento-reciente"]')

    expect(tarjeta.text()).toContain('#5')
    expect(tarjeta.text()).toContain('2026-08-27T10:00:05')
    expect(tarjeta.get('[data-testid="nivel-evento"]').text()).toBe('L3')
    expect(tarjeta.get('[data-testid="etiqueta-evento"]').text()).toBe('[ETIQUETA_L3]')
    expect(tarjeta.get('[data-testid="codigo-evento"]').text()).toBe('EVENTO_L3_5')
    expect(tarjeta.get('[data-testid="mensaje-evento"]').text()).toBe('Mensaje del evento 5')
  })
})

describe('WP-041 - Retorno al inicio ante actividad nueva', () => {
  it('vuelve el scroll al inicio cuando el snapshot trae un seq mayor al observado', async () => {
    const wrapper = montar({
      estado: crearEstado([crearEvento(1, 'L3'), crearEvento(2, 'L3')]),
    })

    // El operador estaba mirando eventos anteriores.
    contenedorScrolleable(wrapper).scrollTop = 320

    await wrapper.setProps({
      estado: crearEstado([crearEvento(1, 'L3'), crearEvento(2, 'L3'), crearEvento(3, 'L3')]),
    })
    // El reposicionamiento ocurre después del render de la colección derivada.
    await flushPromises()

    expect(seqRenderizados(wrapper)).toEqual([3, 2, 1])
    expect(contenedorScrolleable(wrapper).scrollTop).toBe(0)
  })

  it('no mueve el scroll cuando el snapshot no incorpora un seq mayor', async () => {
    const wrapper = montar({
      estado: crearEstado([crearEvento(1, 'L3'), crearEvento(2, 'L3')]),
    })

    contenedorScrolleable(wrapper).scrollTop = 180

    // Mismo seq máximo: el backend reemitió la baseline sin actividad nueva.
    await wrapper.setProps({
      estado: crearEstado([crearEvento(2, 'L3')]),
    })
    await flushPromises()

    expect(contenedorScrolleable(wrapper).scrollTop).toBe(180)
  })

  it('no trata un cambio de filtro como llegada de un evento nuevo', async () => {
    const wrapper = montar({
      estado: crearEstado([crearEvento(1, 'L1'), crearEvento(2, 'L2'), crearEvento(3, 'L3')]),
    })

    contenedorScrolleable(wrapper).scrollTop = 240
    await wrapper.get('[data-testid="filtro-eventos"]').setValue('L1')
    await flushPromises()

    expect(seqRenderizados(wrapper)).toEqual([3, 2, 1])
    expect(contenedorScrolleable(wrapper).scrollTop).toBe(240)
  })
})

describe('WP-041 - Reemplazo de snapshot y reconexión', () => {
  it('adopta íntegramente una baseline nueva sin acumular la anterior', async () => {
    const wrapper = montar({
      estado: crearEstado([crearEvento(1, 'L3'), crearEvento(2, 'L3')]),
    })

    await wrapper.setProps({
      estado: crearEstado([crearEvento(40, 'L3'), crearEvento(41, 'L3')]),
    })

    expect(seqRenderizados(wrapper)).toEqual([41, 40])
    expect(wrapper.text()).not.toContain('Mensaje del evento 1')
  })

  it('adopta un reinicio de contexto con secuencia menor sin mezclarla con la anterior', async () => {
    const wrapper = montar({
      estado: crearEstado([crearEvento(80, 'L3'), crearEvento(81, 'L3')]),
    })

    // Nueva preparación: el buffer arranca otra vez desde seq bajos.
    await wrapper.setProps({ estado: crearEstado([crearEvento(1, 'L3')]) })

    expect(seqRenderizados(wrapper)).toEqual([1])

    // A partir del nuevo contexto, el siguiente evento vuelve a considerarse nuevo.
    contenedorScrolleable(wrapper).scrollTop = 90
    await wrapper.setProps({
      estado: crearEstado([crearEvento(1, 'L3'), crearEvento(2, 'L3')]),
    })
    await flushPromises()

    expect(seqRenderizados(wrapper)).toEqual([2, 1])
    expect(contenedorScrolleable(wrapper).scrollTop).toBe(0)
  })

  it('vuelve al estado vacío cuando el backend deja de proyectar eventos', async () => {
    const wrapper = montar({ estado: crearEstado([crearEvento(3, 'L3')]) })

    await wrapper.setProps({ estado: crearEstado([]) })

    expect(wrapper.findAll('[data-testid="evento-reciente"]')).toHaveLength(0)
    expect(wrapper.get('[data-testid="eventos-vacio"]').text()).toContain(
      'Sin eventos en la sesión activa',
    )
  })
})

describe('WP-041 - Selector fijo fuera del área scrolleable', () => {
  it('coloca el selector en la cabecera del panel y no dentro del contenedor con scroll', () => {
    const wrapper = montar({ estado: crearEstado([crearEvento(1, 'L3')]) })

    const selector = wrapper.get('[data-testid="filtro-eventos"]').element
    const lista = contenedorScrolleable(wrapper)

    // El selector existe, pero no es descendiente del contenedor scrolleable.
    expect(lista.querySelector('[data-testid="filtro-eventos"]')).toBeNull()
    // Sí pertenece a la cabecera del panel, que nunca se desplaza.
    expect(wrapper.get('header').element.querySelector('[data-testid="filtro-eventos"]')).toBe(
      selector,
    )
  })

  it('conserva el label accesible y las tres opciones canónicas', () => {
    const wrapper = montar({ estado: crearEstado([crearEvento(1, 'L3')]) })

    const etiqueta = wrapper.get('[data-testid="etiqueta-filtro-eventos"]')
    expect(etiqueta.text()).toContain('Nivel visible')
    expect(etiqueta.element.getAttribute('for')).toBe('filtro-eventos')
    expect(wrapper.get('[data-testid="filtro-eventos"]').element.getAttribute('id')).toBe(
      'filtro-eventos',
    )

    const opciones = wrapper.findAll('[data-testid="filtro-eventos"] option').map((o) => o.text())
    expect(opciones).toEqual(['Principales (L3)', 'Intermedios (L2+L3)', 'Sistema (L1+L2+L3)'])
  })

  it('mantiene el listado como único contenedor con scroll interno del panel', () => {
    const wrapper = montar({ estado: crearEstado([crearEvento(1, 'L3')]) })
    const lista = wrapper.get('[data-testid="lista-eventos"]')

    expect(lista.element.classList.contains('overflow-y-auto')).toBe(true)
    expect(lista.element.classList.contains('h-full')).toBe(true)
  })
})
