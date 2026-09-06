/**
 * WP-070 — Estructura de la fila de acciones de cada mensaje precargado.
 *
 * La decisión humana pide que la etiqueta de destino y los tres botones «Usar en el
 * formulario», «Editar» y «Eliminar» entren en un solo renglón a 1366×768 y 1920×1080, y
 * que para lograrlo no se recorte ni se abrevie el rótulo de ningún botón.
 *
 * jsdom no calcula layout, así que acá se fija lo que sí es estructural y protege esa
 * decisión de una regresión silenciosa:
 *
 * - los cuatro controles viven bajo un único contenedor de acciones;
 * - los rótulos siguen completos, sin abreviaturas ni recortes;
 * - ningún control de la fila puede partir su texto en dos líneas (`whitespace-nowrap`),
 *   de modo que la falta de ancho se manifieste como desborde medible en Playwright y no
 *   como un rótulo cortado que nadie note.
 *
 * WP-076 agregó un nivel de anidamiento: los tres botones pasaron a vivir dentro de un
 * subcontenedor para poder alinearlos a la derecha. Por eso este archivo dejó de exigir
 * que los cuatro sean hermanos directos y pasó a recorrer los controles reales de la fila.
 * La alineación en sí la cubre `biblioteca_alineacion_wp076.test.ts`.
 *
 * La medición real —una sola fila, sin desborde, sin scroll global— vive en
 * `tests/playwright/geometria_wp070.spec.ts`.
 */

import { mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ClienteApoyoTecnico } from '@sis-leg/api-client'
import BibliotecaMensajes from '../app/components/BibliotecaMensajes.vue'
import { crearBibliotecaPrueba, crearMensajePrueba } from './datos_prueba'

/** Rótulos exactos que la decisión humana enumera y que no pueden abreviarse. */
const ROTULOS_ESPERADOS = ['Usar en el formulario', 'Editar', 'Eliminar'] as const

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

function montarBiblioteca(): VueWrapper {
  const wrapper = mount(BibliotecaMensajes, {
    props: {
      biblioteca: crearBibliotecaPrueba({
        // MODERACION es la etiqueta de destino más larga: es el peor caso de ancho.
        mensajes: [crearMensajePrueba('m-1', 'Cuarto intermedio', 'MODERACION')],
      }),
      cliente: crearClienteEspia(),
      conectado: true,
    },
  })
  montados.push(wrapper)
  return wrapper
}

/**
 * Controles reales de la fila: la etiqueta de destino y los tres botones.
 *
 * Se resuelven por consulta y no por `children` para no volver a atar la prueba a un nivel
 * de anidamiento concreto, que es justamente lo que WP-076 tuvo que cambiar.
 */
function controlesDeLaFila(fila: Element): Element[] {
  return [
    fila.querySelector('[data-testid="destino-mensaje"]')!,
    ...fila.querySelectorAll('button'),
  ]
}

describe('WP-070 · fila única de destino y acciones', () => {
  it('agrupa la etiqueta de destino y los tres botones en un solo contenedor', () => {
    const fila = montarBiblioteca().get('[data-testid="acciones-mensaje"]')

    const controles = controlesDeLaFila(fila.element)
    expect(controles).toHaveLength(4)
    expect(controles[0]!.getAttribute('data-testid')).toBe('destino-mensaje')
    expect(controles.slice(1).map((control) => control.tagName)).toEqual([
      'BUTTON',
      'BUTTON',
      'BUTTON',
    ])
  })

  it('conserva los rótulos completos de los tres botones', () => {
    const fila = montarBiblioteca().get('[data-testid="acciones-mensaje"]')

    const rotulos = fila.findAll('button').map((boton) => boton.text().trim())
    expect(rotulos).toEqual([...ROTULOS_ESPERADOS])
  })

  it('impide que cualquier control de la fila parta su texto en dos líneas', () => {
    const fila = montarBiblioteca().get('[data-testid="acciones-mensaje"]')

    for (const control of controlesDeLaFila(fila.element)) {
      expect(control.className).toContain('whitespace-nowrap')
      // `shrink-0` evita el otro modo silencioso de falla: que flexbox comprima un botón
      // hasta hacerlo ilegible en vez de dejar que el desborde sea visible.
      expect(control.className).toContain('shrink-0')
    }
  })
})
