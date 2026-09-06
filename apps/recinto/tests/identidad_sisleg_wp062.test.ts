/**
 * Identidad SIS-Leg en el estado público sin sesión (WP-062).
 *
 * HUMAN_GATE decidió que `SIN_PREPARAR` deje de mostrar el monograma provisional dibujado
 * con CSS y presente el logo completo aprobado. Como ese estado es lo que el recinto ve
 * durante horas —entre una sesión y la siguiente—, conviene protegerlo con una prueba
 * explícita en vez de confiarlo a la inspección visual de cada revisión.
 *
 * Se afirman las tres condiciones que el WP declara verificables:
 *
 * 1. el logo está presente y apunta al asset publicado por esta aplicación;
 * 2. la marca no se repite como texto, porque el logo ya la contiene;
 * 3. el estado se nombra «recinto» y no «sala».
 */

import { mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import PantallaRecinto from '../app/components/PantallaRecinto.vue'
import { crearEstadoRecintoPrueba } from './datos_prueba'

const montados: VueWrapper[] = []

afterEach(() => {
  while (montados.length > 0) montados.pop()?.unmount()
})

function montarSinPreparar(): VueWrapper {
  const wrapper = mount(PantallaRecinto, {
    props: {
      estado: crearEstadoRecintoPrueba({ estado_global: 'SIN_PREPARAR' }),
      estadoConexion: 'CONECTADO',
      desactualizado: false,
    },
  })
  montados.push(wrapper)
  return wrapper
}

describe('Identidad institucional en SIN_PREPARAR', () => {
  it('muestra el logo completo aprobado', () => {
    const logo = montarSinPreparar().get('[data-testid="logo-sin-preparar"]')

    // Se leen los atributos del nodo real y no `attributes()` de Vue Test Utils: el
    // entorno DOM liviano que usan estas pruebas no publica la colección de atributos,
    // pero sí responde `getAttribute`.
    //
    // La ruta se resuelve con el mismo helper que las fotos de banca. Fuera del runtime de
    // Nuxt el `baseURL` no existe, así que el helper devuelve la raíz: lo que importa acá
    // es que el archivo pedido sea el logo aprobado y no otro.
    expect(logo.element.getAttribute('src')).toBe('/assets/marca/sisleg-logo.png')
    expect(logo.element.getAttribute('alt')).toBe('SIS-Leg')
  })

  it('no repite la marca como texto donde ya está el logo', () => {
    const texto = montarSinPreparar().get('[data-testid="estado-sin-preparar"]').text()

    expect(texto).not.toContain('SIS-Leg')
    expect(texto).not.toContain('Botonera2')
  })

  it('nombra el espacio legislativo como recinto', () => {
    const texto = montarSinPreparar().get('[data-testid="estado-sin-preparar"]').text()

    expect(texto).toContain('Recinto sin preparar')
    expect(texto).not.toContain('Sala')
  })
})
