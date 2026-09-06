/**
 * WP-076 — Alineación de destino y acciones en cada mensaje precargado.
 *
 * La decisión humana pide que, fuera del modo edición, la etiqueta de destino quede
 * pegada al extremo izquierdo de la fila y que los tres botones queden agrupados contra el
 * extremo derecho, sin dejar de ser un único renglón a 1366×768 y 1920×1080.
 *
 * WP-070 ya había conseguido el renglón único, pero con los cuatro controles como hermanos
 * directos: todos quedaban apelmazados a la izquierda. Lo que WP-076 cambia es el reparto
 * del espacio sobrante, y eso en CSS es una consecuencia de la estructura: hacen falta
 * exactamente dos bloques hermanos para que `justify-between` mande uno a cada extremo.
 *
 * jsdom no calcula layout, así que acá se fija esa estructura —que es la causa— y se deja
 * la medición de las cajas reales para `tests/playwright/geometria_wp076.spec.ts`, que es
 * donde se demuestra el efecto. Las dos pruebas son complementarias: sin la estructural,
 * un cambio de clases podría romper la alineación sin que nadie lo note hasta el navegador;
 * sin la de geometría, las clases podrían estar bien y el resultado visible no.
 */

import { mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ClienteApoyoTecnico } from '@sis-leg/api-client'
import BibliotecaMensajes from '../app/components/BibliotecaMensajes.vue'
import { crearBibliotecaPrueba, crearMensajePrueba } from './datos_prueba'

/** Orden exacto de acciones que el WP fija de izquierda a derecha dentro del grupo. */
const ORDEN_ACCIONES = [
  { testid: 'btn-cargar-mensaje', rotulo: 'Usar en el formulario' },
  { testid: 'btn-editar-mensaje', rotulo: 'Editar' },
  { testid: 'btn-eliminar-mensaje', rotulo: 'Eliminar' },
] as const

const montados: VueWrapper[] = []

afterEach(() => {
  while (montados.length > 0) montados.pop()?.unmount()
})

function crearClienteEspia(): ClienteApoyoTecnico {
  return {
    crearMensaje: vi.fn(),
    actualizarMensaje: vi.fn(),
    eliminarMensaje: vi.fn(),
  } as unknown as ClienteApoyoTecnico
}

/**
 * Monta la biblioteca con un solo mensaje, fuera del modo edición.
 *
 * El destino es `MODERACION` porque es la etiqueta más larga de las tres posibles: si la
 * alineación fuera a romperse por ancho, sería con ésta.
 */
function montarBiblioteca(): VueWrapper {
  const wrapper = mount(BibliotecaMensajes, {
    props: {
      biblioteca: crearBibliotecaPrueba({
        mensajes: [crearMensajePrueba('m-1', 'Cuarto intermedio', 'MODERACION')],
      }),
      cliente: crearClienteEspia(),
      conectado: true,
    },
  })
  montados.push(wrapper)
  return wrapper
}

describe('WP-076 · destino a la izquierda y acciones agrupadas a la derecha', () => {
  it('parte la fila en exactamente dos bloques: destino y grupo de acciones', () => {
    const fila = montarBiblioteca().get('[data-testid="acciones-mensaje"]')

    const bloques = Array.from(fila.element.children)
    expect(bloques.map((bloque) => bloque.getAttribute('data-testid'))).toEqual([
      'destino-mensaje',
      'grupo-acciones-mensaje',
    ])
  })

  it('reparte el espacio sobrante entre los dos extremos de la fila', () => {
    const fila = montarBiblioteca().get('[data-testid="acciones-mensaje"]')

    // `justify-between` es lo que empuja el primer bloque al borde izquierdo y el segundo
    // al derecho. Sin él los dos bloques quedarían juntos contra la izquierda.
    expect(fila.element.className).toContain('justify-between')
    expect(fila.element.className).toContain('flex')
  })

  it('mantiene el grupo de acciones contra la derecha aunque la fila envuelva', () => {
    const grupo = montarBiblioteca().get('[data-testid="grupo-acciones-mensaje"]')

    // Por debajo de las resoluciones canónicas el grupo puede caer solo en su renglón, y
    // ahí `justify-between` ya no tiene contra qué separarlo: el margen automático es lo
    // que sigue absorbiendo el espacio sobrante a su izquierda.
    expect(grupo.element.className).toContain('ml-auto')
    // Si el propio grupo tuviera que envolver, sus botones siguen alineados a la derecha.
    expect(grupo.element.className).toContain('justify-end')
  })

  it('conserva las tres acciones dentro del bloque derecho, en orden y con rótulo completo', () => {
    const grupo = montarBiblioteca().get('[data-testid="grupo-acciones-mensaje"]')

    const botones = Array.from(grupo.element.querySelectorAll('button'))
    expect(botones).toHaveLength(3)
    expect(botones.map((boton) => boton.getAttribute('data-testid'))).toEqual(
      ORDEN_ACCIONES.map((accion) => accion.testid),
    )
    expect(botones.map((boton) => (boton.textContent ?? '').trim())).toEqual(
      ORDEN_ACCIONES.map((accion) => accion.rotulo),
    )
  })

  it('deja la etiqueta de destino fuera del grupo de acciones', () => {
    const wrapper = montarBiblioteca()

    // La etiqueta sigue existiendo una sola vez y no quedó arrastrada al bloque derecho:
    // si estuviera adentro, viajaría con los botones hacia la derecha.
    expect(wrapper.findAll('[data-testid="destino-mensaje"]')).toHaveLength(1)
    const grupo = wrapper.get('[data-testid="grupo-acciones-mensaje"]')
    expect(grupo.element.querySelector('[data-testid="destino-mensaje"]')).toBeNull()
    expect(wrapper.get('[data-testid="destino-mensaje"]').text()).toBe('MODERACION')
  })
})
