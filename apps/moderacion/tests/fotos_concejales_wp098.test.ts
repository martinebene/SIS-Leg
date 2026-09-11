/**
 * Fuente única de fotografías de banca en Moderación (WP-098).
 *
 * Es el espejo de `apps/recinto/tests/fotos_concejales_wp098.test.ts`: las dos
 * superficies que dibujan bancas deben resolver **exactamente la misma URL**
 * para la misma `ruta_imagen`, porque ahora hay una sola fuente física bajo
 * `config/assets/bancas/` y ya no una copia por aplicación.
 *
 * Qué se demuestra acá
 * --------------------
 *
 * 1. la tarjeta de Q3 pide la foto al endpoint del backend;
 * 2. la URL sale de `ruta_imagen` y coincide con la del cliente compartido;
 * 3. una ruta insegura no genera pedido y la tarjeta cae en sus iniciales;
 * 4. `resolverRutaAsset` sigue sirviendo para los assets que sí viajan en el
 *    build, como la marca institucional.
 */

import { afterEach, describe, expect, it } from 'vitest'
import { compile, ssrContextKey, type Component } from 'vue'
import { mount, type VueWrapper } from '@vue/test-utils'
import type { ConcejalModeracion } from '@sis-leg/api-client'
import { resolverUrlImagenConcejal } from '@sis-leg/api-client'
import BancaConcejal from '../app/components/BancaConcejal.vue'
import fuenteBancaConcejal from '../app/components/BancaConcejal.vue?raw'
import { resolverRutaAsset, resolverUrlFotoConcejal } from '../app/utils/rutas'

/**
 * Adjunta el render de cliente de la plantilla productiva.
 *
 * Vitest compila los SFC para SSR; este paso cubre la frontera de compilación
 * que en la aplicación real aporta Nuxt, igual que en `bancas_wp045.test.ts`.
 */
function habilitarRenderCliente(componente: Component, fuente: string): void {
  const coincidencia = fuente.match(/<template>([\s\S]*)<\/template>/)
  if (!coincidencia?.[1]) throw new Error('No se encontró la plantilla Vue productiva')

  const compilable = componente as {
    render?: ReturnType<typeof compile>
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
}

habilitarRenderCliente(BancaConcejal, fuenteBancaConcejal)

const montados: VueWrapper[] = []

afterEach(() => {
  while (montados.length) montados.pop()?.unmount()
})

function crearConcejal(cambios: Partial<ConcejalModeracion> = {}): ConcejalModeracion {
  return {
    dni: '30111222',
    nombre: 'Florentina',
    apellido: 'Gómez Miranda',
    bloque: 'Bloque de prueba',
    banca: 1,
    dispositivo_votacion: 'dev01',
    ruta_imagen: 'assets/bancas/banca-01.png',
    presente: true,
    test_activo: false,
    test_expira_en: null,
    ...cambios,
  }
}

function montarBanca(concejal: ConcejalModeracion): VueWrapper {
  const wrapper = mount(BancaConcejal, {
    props: {
      concejal,
      esOrador: false,
      estadoRecepcion: null,
      votoEmitido: false,
      valorVotoFinal: null,
    },
    global: { provide: { [ssrContextKey]: { modules: new Set() } } },
  })
  montados.push(wrapper)
  return wrapper
}

describe('Fotografías de banca desde la configuración local (WP-098)', () => {
  it('pide la foto al backend y no a un asset del build', () => {
    const wrapper = montarBanca(crearConcejal())
    const src = wrapper.get('[data-testid="imagen-concejal"]').element.getAttribute('src')

    expect(src).toBe('/api/v1/recursos/imagenes-concejales/banca-01.png')
    expect(src).not.toContain('/moderacion/assets/bancas/')
  })

  it('resuelve la misma URL que la Pantalla del Recinto para la misma ruta', () => {
    // Ésta es la garantía central del WP: la misma `ruta_imagen` no puede
    // producir dos archivos distintos según qué superficie la dibuje.
    const ruta = 'assets/bancas/banca-09.png'
    const wrapper = montarBanca(crearConcejal({ ruta_imagen: ruta }))

    expect(wrapper.get('[data-testid="imagen-concejal"]').element.getAttribute('src')).toBe(
      resolverUrlImagenConcejal(ruta),
    )
    expect(resolverUrlFotoConcejal(ruta)).toBe(resolverUrlImagenConcejal(ruta))
  })

  it.each([
    'assets/bancas/../../../etc/passwd',
    '/etc/passwd',
    'https://ejemplo.invalid/foto.png',
    'assets/sonidos/sesion-abierta.wav',
  ])('ante la ruta insegura %j muestra el fallback sin pedir nada', (rutaInsegura) => {
    const wrapper = montarBanca(crearConcejal({ ruta_imagen: rutaInsegura }))

    expect(wrapper.find('[data-testid="imagen-concejal"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="fallback-imagen"]').text()).toBe('FG')
    expect(wrapper.find('[data-testid="banca-concejal"]').exists()).toBe(true)
  })

  it('resolverRutaAsset sigue resolviendo los assets versionados del build', () => {
    // La marca institucional sí viaja dentro de cada SPA y se sirve bajo su
    // propio prefijo público, así que conserva la resolución anterior.
    expect(resolverRutaAsset('assets/marca/sisleg-logo.png')).toBe('/assets/marca/sisleg-logo.png')
  })
})
