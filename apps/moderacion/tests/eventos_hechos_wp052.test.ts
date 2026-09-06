/**
 * Pruebas DOM de WP-052 sobre el componente productivo `PanelEventos`.
 *
 * Demuestran que el cuadrante Eventos:
 *
 * - presenta identidad/banca y `Voto emitido` mientras el sentido es secreto;
 * - no dibuja ningún emoji de sentido en ese estado;
 * - enriquece exactamente el mismo `seq` con sentido e icono cuando el backend
 *   lo habilita, sin duplicar ni reordenar la tarjeta;
 * - usa ✋ para el pedido de palabra y ✊ para el retiro;
 * - ubica el icono a la derecha del registro, con la altura de las dos filas;
 * - conserva el filtro acumulativo L1/L2/L3 y el evento más nuevo primero;
 * - sigue mostrando el mensaje humano en los eventos sin hecho estructurado.
 *
 * Una decisión importante se comprueba de forma explícita: el componente no
 * interpreta `mensaje` para deducir sentido, identidad ni icono. Todo llega ya
 * resuelto desde el backend, que es donde vive la frontera de secreto.
 */

import { afterEach, describe, expect, it } from 'vitest'
import { compile, type Component, ssrContextKey } from 'vue'
import { mount, type VueWrapper } from '@vue/test-utils'
import PanelContenedor from '../app/components/PanelContenedor.vue'
import fuentePanelContenedor from '../app/components/PanelContenedor.vue?raw'
import PanelEventos from '../app/components/PanelEventos.vue'
import fuentePanelEventos from '../app/components/PanelEventos.vue?raw'
import type { EstadoModeracion, HechoOperativoProyectado } from '@sis-leg/api-client'

/**
 * El entorno de Vitest compila los SFC para SSR. Esta adaptación adjunta el
 * render de cliente de la misma plantilla productiva para poder inspeccionar
 * el DOM real que ve el operador.
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

function montar(estado: EstadoModeracion): VueWrapper {
  const wrapper = mount(PanelEventos, {
    props: { estado },
    global: { provide: { [ssrContextKey]: { modules: new Set() } } },
  })
  wrappers.push(wrapper)
  return wrapper
}

afterEach(() => {
  while (wrappers.length) wrappers.pop()?.unmount()
})

type EventoProyectado = EstadoModeracion['eventos_recientes'][number]

/** Identidad reutilizada en los escenarios de voto y de palabra. */
const CONCEJALA = { nombre: 'Ana', apellido: 'Garcia', banca: 1 }

/**
 * Construye el evento L3 de un voto tal como lo proyecta el backend.
 *
 * El parámetro `hecho` se recibe entero a propósito: refleja que el frontend
 * no compone la presentación, únicamente la dibuja.
 */
function eventoVoto(
  seq: number,
  hecho: HechoOperativoProyectado,
  mensaje: string,
): EventoProyectado {
  return {
    seq,
    timestamp: '2026-09-01 09:20:31',
    nivel: 'L3',
    etiqueta: 'VOTACION',
    codigo_evento: 'VOTO_ORDINARIO_REGISTRADO',
    mensaje,
    hecho,
  } as EventoProyectado
}

/** Evento sin hecho estructurado: conserva el mensaje humano de auditoría. */
function eventoSimple(seq: number, nivel: 'L1' | 'L2' | 'L3'): EventoProyectado {
  return {
    seq,
    timestamp: '2026-09-01 09:20:30',
    nivel,
    etiqueta: 'INPUT',
    codigo_evento: `EVENTO_${nivel}_${seq}`,
    mensaje: `Mensaje del evento ${seq}`,
    hecho: null,
  } as EventoProyectado
}

/** Evento de palabra con su icono ya decidido por el backend. */
function eventoPalabra(
  seq: number,
  codigo: string,
  tipo: string,
  detalle: string,
  icono: string,
): EventoProyectado {
  return {
    seq,
    timestamp: '2026-09-01 09:15:02',
    nivel: 'L3',
    etiqueta: 'PALABRA',
    codigo_evento: codigo,
    mensaje: `Mensaje humano de ${codigo}`,
    hecho: { tipo, concejal: CONCEJALA, detalle, icono, sentido: null },
  } as EventoProyectado
}

function crearEstado(eventos: EventoProyectado[]): EstadoModeracion {
  return { eventos_recientes: eventos } as unknown as EstadoModeracion
}

const HECHO_SECRETO: HechoOperativoProyectado = {
  tipo: 'VOTO_ORDINARIO',
  concejal: CONCEJALA,
  detalle: 'Voto emitido',
  icono: null,
  sentido: null,
}

const HECHO_REVELADO: HechoOperativoProyectado = {
  tipo: 'VOTO_ORDINARIO',
  concejal: CONCEJALA,
  detalle: 'Voto POSITIVO',
  icono: '✅',
  sentido: 'POSITIVO',
}

describe('Voto durante el secreto', () => {
  it('muestra concejal, banca y "Voto emitido" sin ningún emoji de sentido', () => {
    const wrapper = montar(
      crearEstado([
        eventoVoto(
          12,
          HECHO_SECRETO,
          'Voto ordinario: Ana Garcia (banca Nro:1) emitió su voto; votación número=37',
        ),
      ]),
    )

    const tarjeta = wrapper.get('[data-testid="evento-reciente"]')
    expect(tarjeta.get('[data-testid="hecho-concejal"]').text()).toBe('Ana Garcia · Banca 1')
    expect(tarjeta.get('[data-testid="hecho-detalle"]').text()).toBe('Voto emitido')
    expect(tarjeta.find('[data-testid="icono-evento"]').exists()).toBe(false)
    for (const emoji of ['✅', '❌', '🟡']) {
      expect(tarjeta.text()).not.toContain(emoji)
    }
    for (const sentido of ['POSITIVO', 'NEGATIVO', 'ABSTENCION']) {
      expect(tarjeta.text()).not.toContain(sentido)
    }
  })

  it('no reconstruye el sentido aunque el mensaje crudo lo contuviera', () => {
    // Escenario defensivo: si una regresión del backend dejara pasar el texto
    // durable, el panel no debe amplificar la fuga usándolo como contrato.
    const wrapper = montar(
      crearEstado([
        eventoVoto(12, HECHO_SECRETO, 'Voto ordinario: Ana Garcia (banca Nro:1) votó POSITIVO'),
      ]),
    )

    const tarjeta = wrapper.get('[data-testid="evento-reciente"]')
    expect(tarjeta.find('[data-testid="mensaje-evento"]').exists()).toBe(false)
    expect(tarjeta.text()).not.toContain('POSITIVO')
    expect(tarjeta.find('[data-testid="icono-evento"]').exists()).toBe(false)
  })
})

describe('Enriquecimiento posterior del mismo seq', () => {
  it('agrega sentido e icono sin duplicar ni mover la tarjeta', async () => {
    const wrapper = montar(crearEstado([eventoVoto(12, HECHO_SECRETO, 'emitió su voto')]))

    await wrapper.setProps({
      estado: crearEstado([eventoVoto(12, HECHO_REVELADO, 'votó POSITIVO')]),
    })

    const tarjetas = wrapper.findAll('[data-testid="evento-reciente"]')
    expect(tarjetas).toHaveLength(1)
    expect(tarjetas[0]!.text()).toContain('#12')
    expect(tarjetas[0]!.get('[data-testid="hecho-detalle"]').text()).toBe('Voto POSITIVO')
    const icono = tarjetas[0]!.get('[data-testid="icono-evento"]')
    expect(icono.text()).toBe('✅')
    expect(icono.element.getAttribute('aria-label')).toBe('Voto POSITIVO')
  })

  it.each([
    ['POSITIVO', '✅', 'Voto POSITIVO'],
    ['NEGATIVO', '❌', 'Voto NEGATIVO'],
    ['ABSTENCION', '🟡', 'Voto ABSTENCIÓN'],
  ])('dibuja el icono acordado para %s', (sentido, icono, detalle) => {
    const wrapper = montar(
      crearEstado([
        eventoVoto(
          20,
          { tipo: 'VOTO_ORDINARIO', concejal: CONCEJALA, detalle, icono, sentido },
          'mensaje',
        ),
      ]),
    )

    expect(wrapper.get('[data-testid="icono-evento"]').text()).toBe(icono)
    expect(wrapper.get('[data-testid="hecho-detalle"]').text()).toBe(detalle)
  })
})

describe('Palabra', () => {
  it('usa ✋ para el pedido y ✊ para el retiro', () => {
    const wrapper = montar(
      crearEstado([
        eventoPalabra(5, 'PEDIDO_PALABRA_REGISTRADO', 'PEDIDO_PALABRA', 'Pedido de palabra', '✋'),
        eventoPalabra(
          6,
          'PEDIDO_PALABRA_RETIRADO',
          'RETIRO_PALABRA',
          'Pedido de palabra retirado',
          '✊',
        ),
      ]),
    )

    const iconos = wrapper.findAll('[data-testid="icono-evento"]').map((nodo) => nodo.text())
    // El orden visual es descendente por seq: primero el retiro (6).
    expect(iconos).toEqual(['✊', '✋'])
  })
})

describe('Ubicación y tamaño del icono', () => {
  it('queda a la derecha del registro y abarca las dos filas de texto', () => {
    const wrapper = montar(crearEstado([eventoVoto(12, HECHO_REVELADO, 'votó POSITIVO')]))

    const tarjeta = wrapper.get('[data-testid="evento-reciente"]')
    const fila = tarjeta.get('[data-testid="fila-evento"]')
    const hijos = Array.from(fila.element.children)
    const icono = tarjeta.get('[data-testid="icono-evento"]').element

    // Último hijo de una fila horizontal: eso es "a la derecha" sin depender
    // de coordenadas absolutas ni de una resolución concreta.
    expect(hijos).toHaveLength(2)
    expect(hijos[hijos.length - 1]).toBe(icono)
    expect(hijos[0]).toBe(tarjeta.get('[data-testid="cuerpo-evento"]').element)
    expect(fila.element.className).toContain('items-center')
    // `h-7` (1.75rem) equivale aproximadamente a las dos filas de 11px con
    // interlineado ajustado que ya tenía la tarjeta.
    expect(icono.className).toContain('h-7')
    expect(icono.className).toContain('shrink-0')
  })
})

describe('Compatibilidad con eventos sin hecho estructurado', () => {
  it('conserva el mensaje humano y el filtro acumulativo por nivel', async () => {
    const wrapper = montar(
      crearEstado([
        eventoSimple(1, 'L1'),
        eventoSimple(2, 'L2'),
        eventoVoto(3, HECHO_SECRETO, 'Voto ordinario: Ana Garcia (banca Nro:1) emitió su voto'),
      ]),
    )

    // Vista inicial L3: solo el hecho institucional del voto.
    expect(wrapper.findAll('[data-testid="evento-reciente"]')).toHaveLength(1)
    expect(wrapper.get('[data-testid="hecho-detalle"]').text()).toBe('Voto emitido')

    await wrapper.get('[data-testid="filtro-eventos"]').setValue('L2')
    expect(wrapper.findAll('[data-testid="evento-reciente"]')).toHaveLength(2)

    await wrapper.get('[data-testid="filtro-eventos"]').setValue('L1')
    const tarjetas = wrapper.findAll('[data-testid="evento-reciente"]')
    expect(tarjetas).toHaveLength(3)
    // Evento más nuevo primero y mensajes crudos intactos donde corresponde.
    expect(tarjetas[0]!.text()).toContain('#3')
    expect(tarjetas[1]!.get('[data-testid="mensaje-evento"]').text()).toBe('Mensaje del evento 2')
    expect(tarjetas[2]!.get('[data-testid="mensaje-evento"]').text()).toBe('Mensaje del evento 1')
  })
})
