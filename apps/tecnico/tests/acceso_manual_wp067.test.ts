/**
 * Pruebas del acceso de ayuda dentro de la cabecera de Apoyo Técnico (WP-067).
 *
 * Son el reflejo exacto de las de Moderación: el WP exige que las dos cabeceras ofrezcan
 * la misma función en la misma posición relativa. El contrato del acceso en sí se verifica
 * en `packages/frontend-shared/tests/acceso_manual_wp067.test.ts`; acá se comprueba que
 * esta cabecera lo monte, que quede en su extremo derecho y que sumarlo no haya costado
 * ningún indicador del puesto.
 */

import { mount, type DOMWrapper, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import { RUTA_MANUAL } from '@sis-leg/frontend-shared'
import CabeceraTecnico from '../app/components/CabeceraTecnico.vue'

const montados: VueWrapper[] = []

afterEach(() => {
  while (montados.length > 0) montados.pop()?.unmount()
})

/**
 * Lee un atributo del elemento real.
 *
 * El DOM liviano que usan estas pruebas guarda los atributos como un objeto plano, no como
 * el `NamedNodeMap` que recorre `DOMWrapper.attributes()`. Ese helper devolvería siempre
 * `undefined` y la prueba pasaría sin comprobar nada, así que se lee directamente con
 * `getAttribute`, que el entorno sí implementa.
 */
function atributo(elemento: DOMWrapper<Element>, nombre: string): string | null {
  return elemento.element.getAttribute(nombre)
}

/** Props que activan todos los indicadores condicionales de la cabecera técnica. */
function montarCabecera(parcial: Record<string, unknown> = {}): VueWrapper {
  const wrapper = mount(CabeceraTecnico, {
    props: {
      estadoConexion: 'CONECTADO',
      estadoGlobal: 'SESION_ABIERTA',
      revision: 12,
      desactualizado: true,
      estadoTransmision: 'EN_VIVO',
      ...parcial,
    },
  })
  montados.push(wrapper)
  return wrapper
}

describe('Acceso al manual desde la cabecera de Apoyo Técnico (WP-067)', () => {
  it('incluye el acceso de ayuda apuntando al manual', () => {
    const acceso = montarCabecera().get('[data-testid="acceso-manual"]')

    expect(atributo(acceso, 'href')).toBe(RUTA_MANUAL)
    expect(atributo(acceso, 'target')).toBe('_blank')
    expect(atributo(acceso, 'rel')).toBe('noopener noreferrer')
  })

  it('lo coloca en el extremo derecho, después del indicador de conexión', () => {
    const cabecera = montarCabecera().get('[data-testid="cabecera-tecnico"]')
    const identificadores = cabecera
      .findAll('[data-testid]')
      .map((elemento) => atributo(elemento, 'data-testid'))

    expect(identificadores.at(-1)).toBe('acceso-manual')
    expect(identificadores.indexOf('acceso-manual')).toBeGreaterThan(
      identificadores.indexOf('estado-conexion'),
    )
  })

  it('aparece también con el recinto sin preparar y sin transmisión', () => {
    // La transmisión y los avisos operan fuera de una sesión, así que este puesto se usa
    // en `SIN_PREPARAR`. La ayuda tiene que estar disponible también entonces.
    const cabecera = montarCabecera({
      estadoGlobal: 'SIN_PREPARAR',
      estadoTransmision: null,
      desactualizado: false,
    })

    expect(cabecera.find('[data-testid="acceso-manual"]').exists()).toBe(true)
    expect(cabecera.find('[data-testid="resumen-transmision"]').exists()).toBe(false)
  })

  it('no desplaza ni elimina ningún indicador anterior', () => {
    const cabecera = montarCabecera()

    for (const identificador of [
      'estado-global-tecnico',
      'resumen-transmision',
      'aviso-desactualizado',
      'estado-conexion',
    ]) {
      expect(cabecera.find(`[data-testid="${identificador}"]`).exists()).toBe(true)
    }
  })
})
