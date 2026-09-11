/**
 * Pantalla del Zócalo para OBS (WP-099).
 *
 * ## Qué demuestra esta suite
 *
 * Lo que puede comprobarse sin un navegador: **qué** dibuja el Zócalo y **qué no**. La
 * geometría real —posición, proporciones, croma, ausencia de recorte— se mide en Chromium,
 * en `tests/playwright/zocalo_wp099.spec.ts`, porque sólo existe cuando un motor de layout
 * la calcula.
 *
 * Acá se fijan cuatro propiedades:
 *
 * 1. muestra `Votación`, `Tema` y `Estado` con la misma redacción que el Recinto;
 * 2. refleja en vivo el snapshot recibido, sin conservar el anterior;
 * 3. aplica las mismas reglas de visibilidad que la Pantalla del Recinto —secreto del voto
 *    durante la recepción, nada que mostrar en `SIN_PREPARAR`, resultado que deja de verse
 *    cuando venció su ventana—;
 * 4. no contiene ningún control de operador.
 */

import { mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import { nextTick } from 'vue'

import PantallaZocalo from '../app/components/PantallaZocalo.vue'
import { crearEstadoRecintoPrueba, crearVotacionPublicaPrueba } from './datos_prueba'

const montados: VueWrapper[] = []

/** Monta la pantalla con un estado público concreto y registra el wrapper para limpiarlo. */
function montarZocalo(estado: ReturnType<typeof crearEstadoRecintoPrueba> | null): VueWrapper {
  const wrapper = mount(PantallaZocalo, { props: { estado } })
  montados.push(wrapper)
  return wrapper
}

/**
 * Instante del snapshot y ventana de visibilidad del resultado.
 *
 * El reloj de presentación compartido se calibra con `generado_en`, así que un resultado
 * sólo se muestra mientras `resultado_visible_hasta` siga por delante de esa marca. Las
 * fixtures declaran las dos fechas de forma explícita para que las pruebas no dependan del
 * reloj de la máquina que las ejecuta.
 */
const INSTANTE_SNAPSHOT = '2026-08-27T10:00:00Z'
const RESULTADO_VISIBLE_HASTA = '2026-08-27T10:00:30Z'
const RESULTADO_YA_VENCIDO = '2026-08-27T09:59:30Z'

/** Estado de sesión abierta con la votación indicada, que es el caso normal al aire. */
function estadoConVotacion(parcial: Parameters<typeof crearVotacionPublicaPrueba>[0] = {}) {
  return crearEstadoRecintoPrueba({
    estado_global: 'SESION_ABIERTA',
    generado_en: INSTANTE_SNAPSHOT,
    votacion: crearVotacionPublicaPrueba(parcial),
  })
}

/** Votación ya cerrada cuyo resultado todavía está dentro de su ventana de exhibición. */
function estadoConResultadoVisible(parcial: Parameters<typeof crearVotacionPublicaPrueba>[0] = {}) {
  return estadoConVotacion({
    estado_recepcion: 'CERRADA',
    resultado_visible_hasta: RESULTADO_VISIBLE_HASTA,
    ...parcial,
  })
}

afterEach(() => {
  while (montados.length > 0) montados.pop()?.unmount()
})

describe('WP-099 · contenido del Zócalo', () => {
  it('muestra los tres renglones con la redacción institucional compartida', () => {
    const wrapper = montarZocalo(
      estadoConResultadoVisible({
        numero_votacion: 12,
        tipo: 'Despacho de comisión',
        tema: 'Expediente 1234/2026 — Ordenanza de presupuesto',
        tipo_mayoria: 'ESPECIAL',
        factor: 0.6666,
        base: 'PRESENTES',
        resultado: 'APROBADA',
        conteos: { positivos: 8, negativos: 3, abstenciones: 1, total: 12 },
      }),
    )

    expect(wrapper.get('[data-testid="zocalo-votacion"]').text()).toBe(
      'N.º 12 · Despacho de comisión · Mayoría especial · factor 0.66 · base presentes',
    )
    expect(wrapper.get('[data-testid="zocalo-tema"]').text()).toBe(
      'Expediente 1234/2026 — Ordenanza de presupuesto',
    )
    expect(wrapper.get('[data-testid="zocalo-estado"]').text()).toBe('Aprobada')
    expect(wrapper.get('[data-testid="zocalo-detalle-estado"]').text()).toBe(
      'Positivos 8 · Negativos 3 · Abstenciones 1 · Total 12',
    )
    // Los rótulos son parte del contrato visual pedido por el WP.
    expect(wrapper.text()).toContain('Votación')
    expect(wrapper.text()).toContain('Tema')
    expect(wrapper.text()).toContain('Estado')
  })

  it('respeta el secreto del voto mientras la recepción está en curso', () => {
    const wrapper = montarZocalo(
      estadoConVotacion({
        estado_recepcion: 'EN_CURSO',
        conteos: { positivos: 5, negativos: 1, abstenciones: 0, total: 6 },
      }),
    )

    expect(wrapper.get('[data-testid="zocalo-estado"]').text()).toBe('En curso')
    expect(wrapper.find('[data-testid="zocalo-detalle-estado"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Positivos')
  })

  it('anuncia la espera del desempate y, después, el voto de Presidencia', async () => {
    const wrapper = montarZocalo(
      estadoConVotacion({ estado_recepcion: 'CERRADA', resultado: 'EMPATADA' }),
    )
    expect(wrapper.get('[data-testid="zocalo-detalle-estado"]').text()).toContain(
      'En espera del desempate de Presidencia',
    )

    await wrapper.setProps({
      estado: estadoConResultadoVisible({
        resultado: 'APROBADA',
        voto_presidencial: { presidencia: 'Presidencia', sentido: 'POSITIVO' },
      }),
    })
    expect(wrapper.get('[data-testid="zocalo-detalle-estado"]').text()).toContain(
      'Desempate: Presidencia · Positivo',
    )
  })

  it('mantiene los renglones con texto neutro cuando no hay votación', () => {
    const wrapper = montarZocalo(crearEstadoRecintoPrueba({ estado_global: 'SESION_ABIERTA' }))

    // El bloque no desaparece: una Browser Source necesita geometría estable al aire.
    expect(wrapper.find('[data-testid="zocalo"]').exists()).toBe(true)
    expect(wrapper.get('[data-testid="zocalo-votacion"]').text()).toBe('Sin votación activa')
    expect(wrapper.get('[data-testid="zocalo-tema"]').text()).toBe('—')
    expect(wrapper.get('[data-testid="zocalo-estado"]').text()).toBe('Sin votación')
  })

  it('no muestra ninguna votación en SIN_PREPARAR, igual que la Pantalla del Recinto', () => {
    const wrapper = montarZocalo(
      crearEstadoRecintoPrueba({
        estado_global: 'SIN_PREPARAR',
        votacion: crearVotacionPublicaPrueba({ tema: 'Resto de una sesión anterior' }),
      }),
    )

    expect(wrapper.text()).not.toContain('Resto de una sesión anterior')
    expect(wrapper.get('[data-testid="zocalo-estado"]').text()).toBe('Sin votación')
  })

  it('deja de mostrar un resultado cuya ventana de exhibición ya venció', () => {
    // Misma regla que aplica la Pantalla del Recinto: pasada la ventana, el resultado no
    // se congela en pantalla. El Zócalo no la reimplementa, usa el mismo composable.
    const wrapper = montarZocalo(
      estadoConVotacion({
        estado_recepcion: 'CERRADA',
        resultado: 'APROBADA',
        tema: 'Expediente ya exhibido',
        resultado_visible_hasta: RESULTADO_YA_VENCIDO,
      }),
    )

    expect(wrapper.get('[data-testid="zocalo-estado"]').text()).toBe('Sin votación')
    expect(wrapper.text()).not.toContain('Expediente ya exhibido')
  })

  it('dibuja el bloque aunque todavía no haya llegado el primer snapshot', () => {
    const wrapper = montarZocalo(null)
    expect(wrapper.find('[data-testid="lienzo-chroma"]').exists()).toBe(true)
    expect(wrapper.get('[data-testid="zocalo-estado"]').text()).toBe('Sin votación')
  })
})

describe('WP-099 · sin estado paralelo', () => {
  it('adopta cada snapshot nuevo y olvida por completo el anterior', async () => {
    const wrapper = montarZocalo(
      estadoConVotacion({ numero_votacion: 1, tema: 'Primer expediente' }),
    )
    expect(wrapper.get('[data-testid="zocalo-tema"]').text()).toBe('Primer expediente')

    await wrapper.setProps({
      estado: estadoConResultadoVisible({
        numero_votacion: 2,
        tema: 'Segundo expediente',
        resultado: 'RECHAZADA',
      }),
    })
    await nextTick()

    expect(wrapper.get('[data-testid="zocalo-votacion"]').text()).toContain('N.º 2')
    expect(wrapper.get('[data-testid="zocalo-tema"]').text()).toBe('Segundo expediente')
    expect(wrapper.get('[data-testid="zocalo-estado"]').text()).toBe('Rechazada')
    // El expediente anterior no sobrevive en ningún lado del marcado: no hay historia.
    expect(wrapper.text()).not.toContain('Primer expediente')
    expect(wrapper.text()).not.toContain('N.º 1')
  })

  it('vuelve al texto neutro si el backend deja de publicar votación', async () => {
    const wrapper = montarZocalo(estadoConVotacion({ tema: 'Expediente vigente' }))
    await wrapper.setProps({
      estado: crearEstadoRecintoPrueba({ estado_global: 'SESION_ABIERTA', votacion: null }),
    })

    expect(wrapper.get('[data-testid="zocalo-tema"]').text()).toBe('—')
    expect(wrapper.text()).not.toContain('Expediente vigente')
  })
})

describe('WP-099 · ausencia de controles de operador', () => {
  it('no renderiza ningún elemento interactivo', () => {
    const wrapper = montarZocalo(estadoConResultadoVisible({ resultado: 'APROBADA' }))

    // Se enumeran todas las formas de interacción posibles, no sólo los botones: el WP
    // exige una superficie de visualización pura.
    for (const selector of ['button', 'input', 'select', 'textarea', 'a', 'form', '[role]']) {
      expect(
        wrapper.findAll(selector),
        `el Zócalo no debe contener elementos «${selector}»`,
      ).toHaveLength(0)
    }
    expect(wrapper.findAll('[contenteditable]')).toHaveLength(0)
  })
})
