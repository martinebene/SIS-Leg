/**
 * Unificación visual de bancas de la Pantalla del Recinto (WP-045).
 *
 * Es el espejo público de `apps/moderacion/tests/bancas_wp045.test.ts`: los dos
 * archivos comprueban la MISMA semántica sobre superficies distintas, que es
 * exactamente lo que exige el WP. Si alguna de las dos divergiera, uno de los
 * dos conjuntos fallaría.
 */

import { afterEach, describe, expect, it } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import type { ConcejalPublico, VotoPublico } from '@sis-leg/api-client'
import { calcularPresentacionBanca } from '@sis-leg/frontend-shared'
import BancaPublica from '../app/components/BancaPublica.vue'
import GrillaBancas from '../app/components/GrillaBancas.vue'

const montados: VueWrapper[] = []

afterEach(() => {
  while (montados.length) montados.pop()?.unmount()
})

function crearConcejal(cambios: Partial<ConcejalPublico> = {}): ConcejalPublico {
  return {
    nombre: 'Florentina',
    apellido: 'Gómez Miranda',
    bloque: 'Bloque Largo De Prueba',
    banca: 1,
    ruta_imagen: 'assets/bancas/banca-01.png',
    presente: true,
    test_activo: false,
    test_expira_en: null,
    ...cambios,
  }
}

/** Monta una tarjeta pública con los valores por defecto de "sin votación". */
function montarBanca(props: Record<string, unknown> = {}): VueWrapper {
  const wrapper = mount(BancaPublica, {
    props: {
      concejal: crearConcejal(),
      esOrador: false,
      estadoRecepcion: null,
      votoEmitido: false,
      valorVotoFinal: null,
      ...props,
    },
  })
  montados.push(wrapper)
  return wrapper
}

function montarGrilla(props: Record<string, unknown>): VueWrapper {
  const wrapper = mount(GrillaBancas, { props })
  montados.push(wrapper)
  return wrapper
}

function estado(wrapper: VueWrapper): string | null {
  return wrapper.element.getAttribute('data-estado-banca')
}

describe('WP-045 · tarjeta pública de banca', () => {
  it('presente normal: sin etiqueta y sin texto de identidad', () => {
    const wrapper = montarBanca()

    expect(estado(wrapper)).toBe('NORMAL')
    expect(wrapper.find('[data-testid="etiqueta-banca"]').exists()).toBe(false)
    const texto = wrapper.text()
    expect(texto).not.toContain('Florentina')
    expect(texto).not.toContain('Gómez Miranda')
    expect(texto).not.toContain('Bloque Largo De Prueba')
    expect(texto).not.toContain('Banca 1')
    expect(texto).not.toContain('Presente')
  })

  it('resuelve la imagen desde ruta_imagen y resetea el error al cambiar de persona', async () => {
    const wrapper = montarBanca()
    expect(
      wrapper.get('[data-testid="imagen-concejal"]').element.getAttribute('data-ruta-imagen'),
    ).toBe('assets/bancas/banca-01.png')

    await wrapper.get('[data-testid="imagen-concejal"]').trigger('error')
    expect(wrapper.get('[data-testid="imagen-fallback"]').text()).toBe('FG')

    await wrapper.setProps({
      concejal: crearConcejal({ nombre: 'Nueva', apellido: 'Persona' }),
    })
    expect(wrapper.find('[data-testid="imagen-concejal"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="imagen-fallback"]').exists()).toBe(false)
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
    expect(wrapper.text()).not.toContain('Test')
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
    expect(wrapper.findAll('[data-testid="etiqueta-banca"]').length).toBeLessThanOrEqual(1)
  })

  it('los estados subordinados sobreviven como halo no textual', () => {
    const wrapper = montarBanca({
      concejal: crearConcejal({ test_activo: true }),
      esOrador: true,
      estadoRecepcion: 'EN_CURSO',
      votoEmitido: true,
    })

    expect(wrapper.element.getAttribute('data-halo-test')).toBe('true')
    expect(wrapper.element.getAttribute('data-halo-palabra')).toBe('true')
    expect(wrapper.findAll('[data-testid="etiqueta-banca"]')).toHaveLength(1)
  })

  it('secreto: durante EN_CURSO el subárbol no contiene el sentido en ningún atributo', () => {
    const wrapper = montarBanca({
      estadoRecepcion: 'EN_CURSO',
      votoEmitido: true,
      valorVotoFinal: 'POSITIVO',
    })

    expect(wrapper.get('[data-testid="etiqueta-banca"]').text()).toBe('Voto emitido')
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
    expect(wrapper.element.getAttribute('aria-label')).not.toContain('positivo')
  })

  it('conserva identidad y estado en aria-label para accesibilidad', () => {
    expect(
      montarBanca({ concejal: crearConcejal({ presente: false }) }).element.getAttribute(
        'aria-label',
      ),
    ).toBe('Banca 1, Florentina Gómez Miranda, ausente')
  })

  it('coincide exactamente con la semántica compartida usada por Q3', () => {
    // Comparar contra la función pura demuestra que la tarjeta no reimplementa
    // ninguna regla propia: solo representa lo que decide el módulo común.
    const entrada = {
      presente: false,
      testActivo: true,
      esOrador: true,
      estadoRecepcion: 'EN_CURSO',
      votoEmitido: true,
      valorVotoFinal: null,
    }
    const esperado = calcularPresentacionBanca(entrada)
    const wrapper = montarBanca({
      concejal: crearConcejal({ presente: false, test_activo: true }),
      esOrador: true,
      estadoRecepcion: 'EN_CURSO',
      votoEmitido: true,
    })

    expect(estado(wrapper)).toBe(esperado.estado)
    expect(wrapper.get('[data-testid="etiqueta-banca"]').text()).toBe(esperado.etiqueta)
  })
})

describe('WP-045 · grilla pública', () => {
  const concejales: ConcejalPublico[] = [1, 2, 3].map((banca) =>
    crearConcejal({ banca, nombre: `Nombre${banca}` }),
  )

  it('reparte participación por banca durante EN_CURSO sin revelar el sentido', () => {
    const wrapper = montarGrilla({
      filasBancas: [3],
      concejales,
      bancaOrador: null,
      estadoRecepcion: 'EN_CURSO',
      bancasVotoEmitido: [1, 3],
      votosIndividuales: null,
    })

    expect(wrapper.get('[data-banca="1"]').element.getAttribute('data-estado-banca')).toBe(
      'VOTO_EMITIDO',
    )
    expect(wrapper.get('[data-banca="3"]').element.getAttribute('data-estado-banca')).toBe(
      'VOTO_EMITIDO',
    )
    expect(wrapper.get('[data-banca="2"]').element.getAttribute('data-estado-banca')).toBe('NORMAL')
    for (const prohibido of ['POSITIVO', 'Positivo', 'NEGATIVO', 'ABSTENCION']) {
      expect(wrapper.html()).not.toContain(prohibido)
    }
  })

  it('tras el cierre refleja el resultado individual por banca', () => {
    const votos: VotoPublico[] = [
      { nombre: 'Nombre1', apellido: 'A', banca: 1, valor: 'POSITIVO' },
      { nombre: 'Nombre2', apellido: 'A', banca: 2, valor: 'NEGATIVO' },
      { nombre: 'Nombre3', apellido: 'A', banca: 3, valor: 'ABSTENCION' },
    ]
    const wrapper = montarGrilla({
      filasBancas: [3],
      concejales,
      bancaOrador: null,
      estadoRecepcion: 'CERRADA',
      bancasVotoEmitido: [],
      votosIndividuales: votos,
    })

    expect(wrapper.get('[data-banca="1"] [data-testid="etiqueta-banca"]').text()).toBe('Positivo')
    expect(wrapper.get('[data-banca="2"] [data-testid="etiqueta-banca"]').text()).toBe('Negativo')
    expect(wrapper.get('[data-banca="3"] [data-testid="etiqueta-banca"]').text()).toBe('Abstención')
  })

  it('una lista de participación reemplazada por baseline no deja residuos', async () => {
    const wrapper = montarGrilla({
      filasBancas: [3],
      concejales,
      bancaOrador: null,
      estadoRecepcion: 'EN_CURSO',
      bancasVotoEmitido: [1, 2, 3],
      votosIndividuales: null,
    })
    expect(wrapper.findAll('[data-estado-banca="VOTO_EMITIDO"]')).toHaveLength(3)

    // Una reconexión trae un snapshot completo: la lista se reemplaza, no se acumula.
    await wrapper.setProps({ bancasVotoEmitido: [2] })
    expect(wrapper.findAll('[data-estado-banca="VOTO_EMITIDO"]')).toHaveLength(1)
    expect(wrapper.get('[data-banca="2"]').element.getAttribute('data-estado-banca')).toBe(
      'VOTO_EMITIDO',
    )
  })
})
