/**
 * Unificación visual de bancas de Q3 y participación sin sentido (WP-045).
 *
 * Cada caso demuestra una decisión cerrada por HUMAN_GATE sobre el componente
 * productivo real `BancaConcejal` y sobre la grilla que lo alimenta:
 *
 * - la tarjeta muestra el bitmap y como máximo UNA etiqueta textual;
 * - identidad, bloque, `Banca N`, presencia y dispositivo dejan de ser texto;
 * - la prioridad de estados es única y determinista;
 * - el test de dispositivo se pinta sin etiqueta;
 * - durante `EN_CURSO` la banca que ya votó muestra `Voto emitido` y el DOM no
 *   contiene el sentido en texto, clases ni atributos;
 * - tras el cierre Q3 refleja el resultado individual igual que el Recinto.
 */

import { afterEach, describe, expect, it } from 'vitest'
import { compile, ssrContextKey, type Component } from 'vue'
import { mount, type VueWrapper } from '@vue/test-utils'
import type { ConcejalModeracion, VotoModeracion } from '@sis-leg/api-client'
import BancaConcejal from '../app/components/BancaConcejal.vue'
import fuenteBancaConcejal from '../app/components/BancaConcejal.vue?raw'
import GrillaRecinto from '../app/components/GrillaRecinto.vue'
import fuenteGrillaRecinto from '../app/components/GrillaRecinto.vue?raw'

/**
 * Adjunta el render de cliente de la plantilla productiva.
 *
 * Vitest compila los SFC para SSR; este helper cubre solo la frontera de
 * compilación que en la aplicación real aporta Nuxt. No duplica lógica alguna.
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

habilitarRenderCliente(BancaConcejal, fuenteBancaConcejal)
habilitarRenderCliente(GrillaRecinto, fuenteGrillaRecinto, { BancaConcejal })

const montados: VueWrapper[] = []

function montar(componente: Component, props: Record<string, unknown>): VueWrapper {
  const wrapper = mount(componente, {
    props,
    global: { provide: { [ssrContextKey]: { modules: new Set() } } },
  })
  montados.push(wrapper)
  return wrapper
}

afterEach(() => {
  while (montados.length) montados.pop()?.unmount()
})

function crearConcejal(cambios: Partial<ConcejalModeracion> = {}): ConcejalModeracion {
  return {
    dni: '30111222',
    nombre: 'Florentina',
    apellido: 'Gómez Miranda',
    bloque: 'Bloque Largo De Prueba',
    banca: 1,
    dispositivo_votacion: 'dev01',
    ruta_imagen: 'assets/bancas/banca-01.png',
    presente: true,
    test_activo: false,
    test_expira_en: null,
    ...cambios,
  }
}

/** Monta una sola tarjeta con los valores por defecto de una banca sin votación. */
function montarBanca(props: Record<string, unknown> = {}): VueWrapper {
  return montar(BancaConcejal, {
    concejal: crearConcejal(),
    esOrador: false,
    estadoRecepcion: null,
    votoEmitido: false,
    valorVotoFinal: null,
    ...props,
  })
}

function estado(wrapper: VueWrapper): string | null {
  return wrapper.get('[data-testid="banca-concejal"]').element.getAttribute('data-estado-banca')
}

describe('WP-045 · tarjeta de banca en Q3 de Moderación', () => {
  it('presente normal: sin etiqueta y sin texto de identidad', () => {
    const wrapper = montarBanca()

    expect(estado(wrapper)).toBe('NORMAL')
    expect(wrapper.find('[data-testid="etiqueta-banca"]').exists()).toBe(false)
    // La identidad vive dentro del bitmap; fuera de él no se repite como texto.
    const texto = wrapper.text()
    expect(texto).not.toContain('Florentina')
    expect(texto).not.toContain('Gómez Miranda')
    expect(texto).not.toContain('Bloque Largo De Prueba')
    expect(texto).not.toContain('Banca 1')
    expect(texto).not.toContain('Presente')
    expect(texto).not.toContain('dev01')
  })

  it('la imagen se resuelve desde ruta_imagen y se muestra completa', () => {
    const wrapper = montarBanca()
    const imagen = wrapper.get('[data-testid="imagen-concejal"]')

    expect(imagen.element.getAttribute('data-ruta-imagen')).toBe('assets/bancas/banca-01.png')
    expect(imagen.element.classList.contains('imagen-banca')).toBe(true)
    // `object-fit: contain` se declara en la hoja del componente para .imagen-banca.
    expect(fuenteBancaConcejal).toContain('object-fit: contain')
  })

  it('el error de imagen se resetea cuando cambia la identidad de la banca', async () => {
    const wrapper = montarBanca()

    await wrapper.get('[data-testid="imagen-concejal"]').trigger('error')
    expect(wrapper.get('[data-testid="fallback-imagen"]').text()).toBe('FG')

    await wrapper.setProps({
      concejal: crearConcejal({ dni: '39999999', nombre: 'Nueva', apellido: 'Persona' }),
    })
    expect(wrapper.find('[data-testid="imagen-concejal"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="fallback-imagen"]').exists()).toBe(false)
  })

  it.each([
    ['ausente', { concejal: crearConcejal({ presente: false }) }, 'AUSENTE', 'Ausente'],
    ['orador', { esOrador: true }, 'PALABRA', 'En uso de la palabra'],
    [
      'voto emitido',
      { estadoRecepcion: 'EN_CURSO', votoEmitido: true },
      'VOTO_EMITIDO',
      'Voto emitido',
    ],
    [
      'positivo',
      { estadoRecepcion: 'CERRADA', valorVotoFinal: 'POSITIVO' },
      'RESULTADO_POSITIVO',
      'Positivo',
    ],
    [
      'negativo',
      { estadoRecepcion: 'CERRADA', valorVotoFinal: 'NEGATIVO' },
      'RESULTADO_NEGATIVO',
      'Negativo',
    ],
    [
      'abstención',
      { estadoRecepcion: 'CERRADA', valorVotoFinal: 'ABSTENCION' },
      'RESULTADO_ABSTENCION',
      'Abstención',
    ],
  ])('%s muestra exactamente una etiqueta', (_titulo, props, esperado, etiqueta) => {
    const wrapper = montarBanca(props as Record<string, unknown>)

    expect(estado(wrapper)).toBe(esperado)
    expect(wrapper.findAll('[data-testid="etiqueta-banca"]')).toHaveLength(1)
    expect(wrapper.get('[data-testid="etiqueta-banca"]').text()).toBe(etiqueta)
  })

  it('el test de dispositivo se pinta sin ninguna etiqueta textual', () => {
    const wrapper = montarBanca({ concejal: crearConcejal({ test_activo: true }) })

    expect(estado(wrapper)).toBe('TEST')
    expect(wrapper.findAll('[data-testid="etiqueta-banca"]')).toHaveLength(0)
    const texto = wrapper.text()
    expect(texto).not.toContain('Test')
    expect(texto).not.toContain('!')
  })

  it.each([
    [
      'el resultado final gana a todo lo demás',
      {
        concejal: crearConcejal({ presente: false, test_activo: true }),
        esOrador: true,
        estadoRecepcion: 'CERRADA',
        votoEmitido: true,
        valorVotoFinal: 'NEGATIVO',
      },
      'RESULTADO_NEGATIVO',
    ],
    [
      'voto emitido gana a test, palabra y ausencia',
      {
        concejal: crearConcejal({ presente: false, test_activo: true }),
        esOrador: true,
        estadoRecepcion: 'EN_CURSO',
        votoEmitido: true,
      },
      'VOTO_EMITIDO',
    ],
    [
      'test gana a palabra y ausencia',
      { concejal: crearConcejal({ presente: false, test_activo: true }), esOrador: true },
      'TEST',
    ],
    [
      'palabra gana a ausencia',
      { concejal: crearConcejal({ presente: false }), esOrador: true },
      'PALABRA',
    ],
  ])('prioridad: %s', (_titulo, props, esperado) => {
    const wrapper = montarBanca(props as Record<string, unknown>)

    expect(estado(wrapper)).toBe(esperado)
    // Los estados subordinados nunca agregan una segunda etiqueta.
    expect(wrapper.findAll('[data-testid="etiqueta-banca"]').length).toBeLessThanOrEqual(1)
  })

  it('los estados subordinados sobreviven como halo no textual', () => {
    const wrapper = montarBanca({
      concejal: crearConcejal({ test_activo: true }),
      esOrador: true,
      estadoRecepcion: 'EN_CURSO',
      votoEmitido: true,
    })
    const tarjeta = wrapper.get('[data-testid="banca-concejal"]')

    expect(tarjeta.element.getAttribute('data-halo-test')).toBe('true')
    expect(tarjeta.element.getAttribute('data-halo-palabra')).toBe('true')
    expect(wrapper.findAll('[data-testid="etiqueta-banca"]')).toHaveLength(1)
  })

  it('secreto: durante EN_CURSO el subárbol no contiene el sentido en ningún atributo', () => {
    const wrapper = montarBanca({
      estadoRecepcion: 'EN_CURSO',
      votoEmitido: true,
      // El padre nunca debería enviarlo en EN_CURSO; si igual llegara, se descarta.
      valorVotoFinal: 'POSITIVO',
    })

    expect(wrapper.get('[data-testid="etiqueta-banca"]').text()).toBe('Voto emitido')
    // Se inspecciona el HTML completo del subárbol: texto, clases y data-*.
    const html = wrapper.html()
    for (const prohibido of [
      'POSITIVO',
      'NEGATIVO',
      'ABSTENCION',
      'Positivo',
      'Negativo',
      'Abstención',
    ]) {
      expect(html).not.toContain(prohibido)
    }
    const tarjeta = wrapper.get('[data-testid="banca-concejal"]')
    expect(tarjeta.element.getAttribute('aria-label')).not.toContain('positivo')
    expect(tarjeta.element.getAttribute('data-estado-banca')).toBe('VOTO_EMITIDO')
  })

  it('conserva identidad y estado en aria-label para accesibilidad', () => {
    const wrapper = montarBanca({ concejal: crearConcejal({ presente: false }) })
    const etiquetaAccesible = wrapper
      .get('[data-testid="banca-concejal"]')
      .element.getAttribute('aria-label')

    expect(etiquetaAccesible).toBe('Banca 1, Florentina Gómez Miranda, ausente')
  })
})

describe('WP-045 · grilla de Q3', () => {
  const concejales: ConcejalModeracion[] = [1, 2, 3].map((banca) =>
    crearConcejal({ dni: `dni-${banca}`, banca, nombre: `Nombre${banca}` }),
  )

  it('reparte participación por banca durante EN_CURSO sin usar el sentido', () => {
    // Moderación puede recibir votos individuales antes del cierre por su
    // política histórica; las tarjetas de WP-045 deben ignorarlos mientras la
    // recepción siga abierta.
    const votos: VotoModeracion[] = [
      { dni: 'dni-1', nombre: 'Nombre1', apellido: 'Gómez Miranda', banca: 1, valor: 'POSITIVO' },
    ]
    const wrapper = montar(GrillaRecinto, {
      concejales,
      filasBancas: [3],
      bancaOrador: null,
      estadoRecepcion: 'EN_CURSO',
      bancasVotoEmitido: [1, 3],
      votosIndividuales: votos,
    })

    expect(wrapper.get('[data-banca="1"]').element.getAttribute('data-estado-banca')).toBe(
      'VOTO_EMITIDO',
    )
    expect(wrapper.get('[data-banca="3"]').element.getAttribute('data-estado-banca')).toBe(
      'VOTO_EMITIDO',
    )
    expect(wrapper.get('[data-banca="2"]').element.getAttribute('data-estado-banca')).toBe('NORMAL')
    for (const prohibido of ['POSITIVO', 'Positivo']) {
      expect(wrapper.html()).not.toContain(prohibido)
    }
  })

  it('tras el cierre refleja el resultado individual por banca', () => {
    const votos: VotoModeracion[] = [
      { dni: 'dni-1', nombre: 'Nombre1', apellido: 'A', banca: 1, valor: 'POSITIVO' },
      { dni: 'dni-2', nombre: 'Nombre2', apellido: 'A', banca: 2, valor: 'NEGATIVO' },
      { dni: 'dni-3', nombre: 'Nombre3', apellido: 'A', banca: 3, valor: 'ABSTENCION' },
    ]
    const wrapper = montar(GrillaRecinto, {
      concejales,
      filasBancas: [3],
      bancaOrador: null,
      estadoRecepcion: 'CERRADA',
      bancasVotoEmitido: [],
      votosIndividuales: votos,
    })

    expect(wrapper.get('[data-banca="1"] [data-testid="etiqueta-banca"]').text()).toBe('Positivo')
    expect(wrapper.get('[data-banca="2"] [data-testid="etiqueta-banca"]').text()).toBe('Negativo')
    expect(wrapper.get('[data-banca="3"] [data-testid="etiqueta-banca"]').text()).toBe('Abstención')
  })

  it('sin votación activa ninguna banca muestra participación', () => {
    const wrapper = montar(GrillaRecinto, {
      concejales,
      filasBancas: [3],
      bancaOrador: null,
      estadoRecepcion: null,
      bancasVotoEmitido: null,
      votosIndividuales: null,
    })

    expect(wrapper.findAll('[data-testid="etiqueta-banca"]')).toHaveLength(0)
    expect(wrapper.text()).not.toContain('Voto emitido')
  })
})
