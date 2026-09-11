/**
 * Fuente única de fotografías de banca en la Pantalla del Recinto (WP-098).
 *
 * Qué se demuestra acá
 * --------------------
 *
 * 1. la tarjeta pública pide la foto al endpoint del backend y no a un archivo
 *    del build de la SPA;
 * 2. la URL se deriva de `ruta_imagen`, sin reconstruir nombres a partir del
 *    número de banca;
 * 3. una `ruta_imagen` insegura no produce ningún pedido: la tarjeta dibuja
 *    directamente su fallback de iniciales, sin romper la pantalla;
 * 4. un archivo que no carga sigue cayendo en el mismo fallback.
 *
 * Su espejo en Moderación es `apps/moderacion/tests/fotos_concejales_wp098.test.ts`:
 * ambas superficies deben resolver exactamente la misma URL.
 */

import { afterEach, describe, expect, it } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import type { ConcejalPublico } from '@sis-leg/api-client'
import { resolverUrlImagenConcejal } from '@sis-leg/api-client'
import BancaPublica from '../app/components/BancaPublica.vue'

const montados: VueWrapper[] = []

afterEach(() => {
  while (montados.length) montados.pop()?.unmount()
})

function crearConcejal(cambios: Partial<ConcejalPublico> = {}): ConcejalPublico {
  return {
    nombre: 'Florentina',
    apellido: 'Gómez Miranda',
    bloque: 'Bloque de prueba',
    banca: 1,
    ruta_imagen: 'assets/bancas/banca-01.png',
    presente: true,
    test_activo: false,
    test_expira_en: null,
    ...cambios,
  }
}

function montarBanca(concejal: ConcejalPublico): VueWrapper {
  const wrapper = mount(BancaPublica, {
    props: {
      concejal,
      esOrador: false,
      estadoRecepcion: null,
      votoEmitido: false,
      valorVotoFinal: null,
    },
  })
  montados.push(wrapper)
  return wrapper
}

describe('Fotografías de banca desde la configuración local (WP-098)', () => {
  it('pide la foto al backend y no a un asset del build', () => {
    const wrapper = montarBanca(crearConcejal())
    const imagen = wrapper.get('[data-testid="imagen-concejal"]')
    // Se lee con `getAttribute` y no con `attributes()` porque el DOM liviano
    // del monorepo expone los atributos como objeto plano.
    const src = imagen.element.getAttribute('src')

    expect(src).toBe('/api/v1/recursos/imagenes-concejales/banca-01.png')
    // Antes de WP-098 la SPA servía su propia copia bajo su prefijo público.
    expect(src).not.toContain('/recinto/assets/bancas/')
  })

  it('deriva la URL de ruta_imagen y no del número de banca', () => {
    const wrapper = montarBanca(
      crearConcejal({ banca: 4, ruta_imagen: 'assets/bancas/retrato-especial.png' }),
    )

    expect(wrapper.get('[data-testid="imagen-concejal"]').element.getAttribute('src')).toBe(
      '/api/v1/recursos/imagenes-concejales/retrato-especial.png',
    )
  })

  it('resuelve la misma URL que la función compartida del cliente', () => {
    // La tarjeta no puede tener una regla propia: si la tuviera, Recinto y
    // Moderación podrían mostrar archivos distintos para la misma persona.
    const ruta = 'assets/bancas/banca-09.png'
    const wrapper = montarBanca(crearConcejal({ ruta_imagen: ruta }))

    expect(wrapper.get('[data-testid="imagen-concejal"]').element.getAttribute('src')).toBe(
      resolverUrlImagenConcejal(ruta),
    )
  })

  it.each([
    'assets/bancas/../../../etc/passwd',
    '/etc/passwd',
    'https://ejemplo.invalid/foto.png',
    'assets/sonidos/sesion-abierta.wav',
  ])('ante la ruta insegura %j muestra el fallback sin pedir nada', (rutaInsegura) => {
    const wrapper = montarBanca(crearConcejal({ ruta_imagen: rutaInsegura }))

    expect(wrapper.find('[data-testid="imagen-concejal"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="imagen-fallback"]').text()).toBe('FG')
    // La tarjeta sigue existiendo: un recurso inválido no rompe la superficie.
    expect(wrapper.find('[data-testid="banca-publica"]').exists()).toBe(true)
  })

  it('si la foto configurada no carga, cae en el fallback de iniciales', async () => {
    const wrapper = montarBanca(crearConcejal())

    await wrapper.get('[data-testid="imagen-concejal"]').trigger('error')

    expect(wrapper.find('[data-testid="imagen-concejal"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="imagen-fallback"]').text()).toBe('FG')
  })
})
