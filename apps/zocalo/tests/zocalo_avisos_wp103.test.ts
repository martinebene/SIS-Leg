/**
 * Avisos de Apoyo Técnico en el Zócalo para OBS (WP-103).
 *
 * ## Qué demuestra esta suite
 *
 * Que el Zócalo repite, sobre su propio bloque, el ciclo de vida que la Pantalla del Recinto
 * ya aplica a su franja de votación/tema/estado:
 *
 * 1. sin aviso, el bloque muestra `Votación`, `Tema` y `Estado` como antes de WP-103;
 * 2. con `estado.tecnico.aviso`, el aviso **reemplaza** esos renglones —no se superpone—;
 * 3. un aviso nuevo en el snapshot sustituye al anterior sin dejar rastro;
 * 4. cuando el snapshot deja de traer aviso, los renglones vuelven con el contenido vigente;
 * 5. la única fuente es `EstadoRecinto.tecnico.aviso`, el mismo campo que lee el Recinto, y
 *    el texto se muestra tal como llegó;
 * 6. el Zócalo no decide por su cuenta cuándo vence un aviso ni programa temporizadores;
 * 7. con aviso tampoco aparece ningún control de operador.
 *
 * La geometría y el croma con aviso se miden en Chromium, en
 * `tests/playwright/zocalo_avisos_wp103.spec.ts`: un DOM simulado no calcula layout.
 */

import { mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import type { AvisoTecnicoProyectado } from '@sis-leg/api-client'

import PantallaZocalo from '../app/components/PantallaZocalo.vue'
import fuentePantallaZocalo from '../app/components/PantallaZocalo.vue?raw'
import fuenteAppZocalo from '../app/app.vue?raw'
import fuenteEstadoZocalo from '../app/composables/useEstadoZocalo.ts?raw'
import {
  crearApoyoTecnicoPrueba,
  crearEstadoRecintoPrueba,
  crearVotacionPublicaPrueba,
} from './datos_prueba'

type EstadoPrueba = ReturnType<typeof crearEstadoRecintoPrueba>

const montados: VueWrapper[] = []

/** Instante del snapshot; todas las marcas de las fixtures se expresan respecto de él. */
const INSTANTE_SNAPSHOT = '2026-09-12T10:00:00Z'

/** Selectores de los tres renglones normales del bloque. */
const RENGLONES = ['zocalo-votacion', 'zocalo-tema', 'zocalo-estado'] as const

afterEach(() => {
  while (montados.length > 0) montados.pop()?.unmount()
  vi.restoreAllMocks()
})

/** Monta el Zócalo con un snapshot público concreto. */
function montarZocalo(estado: EstadoPrueba | null): VueWrapper {
  const wrapper = mount(PantallaZocalo, { props: { estado } })
  montados.push(wrapper)
  return wrapper
}

/** Aviso tal como lo proyecta el backend en la ranura pública del Recinto. */
function crearAviso(
  texto: string,
  parcial: Partial<AvisoTecnicoProyectado> = {},
): AvisoTecnicoProyectado {
  return {
    aviso_id: 'aviso-wp103',
    texto,
    destino: 'RECINTO',
    publicado_en: INSTANTE_SNAPSHOT,
    expira_en: null,
    segundos_restantes: null,
    ...parcial,
  }
}

/**
 * Snapshot de sesión abierta con una votación en curso y, opcionalmente, un aviso.
 *
 * Se usa una votación con tema reconocible para poder afirmar que sus renglones desaparecen
 * mientras hay aviso y reaparecen después.
 */
function estadoSesion(
  aviso: AvisoTecnicoProyectado | null,
  tema = 'Expediente 4321/2026 — Ordenanza de tránsito',
): EstadoPrueba {
  return crearEstadoRecintoPrueba({
    estado_global: 'SESION_ABIERTA',
    generado_en: INSTANTE_SNAPSHOT,
    votacion: crearVotacionPublicaPrueba({ tema, estado_recepcion: 'EN_CURSO' }),
    tecnico: crearApoyoTecnicoPrueba({ aviso }),
  })
}

/**
 * Clases CSS de un elemento montado.
 *
 * Se leen desde `className` y no con `wrapper.classes()` porque el DOM liviano compartido de
 * las pruebas implementa `className`/`getAttribute`, pero no toda la API que usa ese helper.
 */
function clasesDe(nodo: { element: Element }): string[] {
  return nodo.element.className.split(/\s+/).filter(Boolean)
}

/** Afirma que el bloque muestra sus tres renglones normales y ningún aviso. */
function esperarContenidoNormal(wrapper: VueWrapper): void {
  for (const testid of RENGLONES) {
    expect(wrapper.find(`[data-testid="${testid}"]`).exists(), testid).toBe(true)
  }
  expect(wrapper.find('[data-testid="aviso-tecnico-zocalo"]').exists()).toBe(false)
  expect(clasesDe(wrapper.get('[data-testid="zocalo"]'))).not.toContain('zocalo-con-aviso')
}

/** Afirma que el aviso ocupa el bloque y que los renglones no existen en el DOM. */
function esperarAviso(wrapper: VueWrapper, texto: string): void {
  const bloque = wrapper.get('[data-testid="zocalo"]')
  const aviso = bloque.get('[data-testid="aviso-tecnico-zocalo"]')
  expect(aviso.get('[data-testid="texto-aviso"]').text()).toBe(texto)
  expect(clasesDe(bloque)).toContain('zocalo-con-aviso')
  // Reemplazo real: los renglones no están ocultos por CSS, directamente no existen.
  for (const testid of RENGLONES) {
    expect(wrapper.find(`[data-testid="${testid}"]`).exists(), testid).toBe(false)
  }
  expect(wrapper.findAll('.rotulo')).toHaveLength(0)
}

describe('WP-103 · ciclo de vida del aviso en el Zócalo', () => {
  it('sin aviso conserva los tres renglones de siempre', () => {
    const wrapper = montarZocalo(estadoSesion(null))

    esperarContenidoNormal(wrapper)
    expect(wrapper.get('[data-testid="zocalo-tema"]').text()).toBe(
      'Expediente 4321/2026 — Ordenanza de tránsito',
    )
    expect(wrapper.get('[data-testid="zocalo-estado"]').text()).toBe('En curso')
  })

  it.each(['RECINTO', 'AMBOS'] as const)(
    'un aviso con destino %s reemplaza el contenido normal del bloque',
    (destino) => {
      const wrapper = montarZocalo(
        estadoSesion(crearAviso('Se reanuda la sesión en instantes', { destino })),
      )

      esperarAviso(wrapper, 'Se reanuda la sesión en instantes')
      expect(wrapper.text()).not.toContain('Expediente 4321/2026')
      // El bloque sigue siendo el mismo elemento: el aviso vive adentro, no en otra capa.
      expect(wrapper.findAll('[data-testid="zocalo"]')).toHaveLength(1)
      expect(wrapper.get('[data-testid="zocalo"]').element.getAttribute('aria-label')).toBe(
        'Aviso de Apoyo Técnico',
      )
    },
  )

  it('refleja el reemplazo de un aviso por otro desde el snapshot público', async () => {
    const wrapper = montarZocalo(estadoSesion(crearAviso('Cuarto intermedio')))
    esperarAviso(wrapper, 'Cuarto intermedio')

    await wrapper.setProps({
      estado: estadoSesion(crearAviso('Se reanuda la sesión', { aviso_id: 'aviso-2' })),
    })
    await nextTick()

    esperarAviso(wrapper, 'Se reanuda la sesión')
    expect(wrapper.text()).not.toContain('Cuarto intermedio')
  })

  it('al desaparecer el aviso vuelve el contenido vigente, sin memoria del anterior', async () => {
    const wrapper = montarZocalo(estadoSesion(crearAviso('Cuarto intermedio'), 'Tema previo'))
    esperarAviso(wrapper, 'Cuarto intermedio')

    // Mientras duró el aviso cambió la votación: al volver debe verse la actual, no la que
    // estaba antes del aviso. Eso prueba que no hubo restauración local de nada.
    await wrapper.setProps({ estado: estadoSesion(null, 'Tema actual') })
    await nextTick()

    esperarContenidoNormal(wrapper)
    expect(wrapper.get('[data-testid="zocalo-tema"]').text()).toBe('Tema actual')
    expect(wrapper.text()).not.toContain('Cuarto intermedio')
    expect(wrapper.text()).not.toContain('Tema previo')
    expect(wrapper.get('[data-testid="zocalo"]').element.getAttribute('aria-label')).toBe(
      'Votación en curso',
    )
  })

  it('sin snapshot todavía no inventa aviso y dibuja el bloque normal', () => {
    esperarContenidoNormal(montarZocalo(null))
  })
})

describe('WP-103 · misma fuente autoritativa que el Recinto', () => {
  it('muestra el texto de `tecnico.aviso` exactamente como llegó', () => {
    // Texto con signos, comillas y espacios internos: nada debe normalizarse ni recortarse
    // en el modelo. El recorte con `…`, si hiciera falta, es sólo visual y lo decide
    // `AvisoSuperficie` midiendo el layout real.
    const texto = '«Atención»: la sesión se reanuda a las 11:30 h — gracias.'
    const estado = estadoSesion(crearAviso(texto))
    const wrapper = montarZocalo(estado)

    expect(wrapper.get('[data-testid="texto-aviso"]').text()).toBe(estado.tecnico.aviso!.texto)
  })

  it('lee el aviso desde `EstadoRecinto.tecnico.aviso`, igual que la Pantalla del Recinto', () => {
    // Comprobación estructural: el Zócalo deriva el aviso del mismo campo del mismo tipo que
    // `PantallaRecinto.vue`, y lo dibuja con el mismo componente compartido.
    expect(fuentePantallaZocalo).toContain('props.estado?.tecnico?.aviso ?? null')
    expect(fuentePantallaZocalo).toContain(
      "import AvisoSuperficie from '@sis-leg/frontend-shared/componentes/AvisoSuperficie.vue'",
    )
    // Y su única suscripción sigue siendo la compartida con el Recinto: no se agregó ninguna
    // fuente propia del Zócalo.
    expect(fuenteEstadoZocalo).toContain('usarSincronizacionRecintoEnComponente')
  })

  it('muestra el aviso también sin votación y fuera de sesión, mientras el backend lo publique', () => {
    // Los avisos técnicos operan sin sesión (WP-056). El bloque del Zócalo está siempre al
    // aire, así que muestra el aviso vigente cualquiera sea el estado global.
    for (const estado_global of ['SIN_PREPARAR', 'PREPARANDO', 'SESION_ABIERTA'] as const) {
      const wrapper = montarZocalo(
        crearEstadoRecintoPrueba({
          estado_global,
          generado_en: INSTANTE_SNAPSHOT,
          votacion: null,
          tecnico: crearApoyoTecnicoPrueba({ aviso: crearAviso('Prueba de transmisión') }),
        }),
      )
      esperarAviso(wrapper, 'Prueba de transmisión')
    }
  })
})

describe('WP-103 · sin temporizadores ni caducidad local', () => {
  it('no oculta un aviso cuyo `expira_en` ya pasó: eso lo decide el backend', () => {
    // Si el snapshot todavía trae el aviso, el backend lo considera vigente. El Zócalo no
    // compara `expira_en` contra ningún reloj, así que lo sigue mostrando.
    const wrapper = montarZocalo(
      estadoSesion(
        crearAviso('Aviso con duración', {
          expira_en: '2026-09-12T09:59:00Z',
          segundos_restantes: 0,
        }),
      ),
    )
    esperarAviso(wrapper, 'Aviso con duración')
  })

  it('mostrar, reemplazar y retirar un aviso no programa ningún temporizador', async () => {
    const intervalos = vi.spyOn(globalThis, 'setInterval')
    const esperas = vi.spyOn(globalThis, 'setTimeout')

    const wrapper = montarZocalo(
      estadoSesion(
        crearAviso('Aviso con vencimiento', {
          expira_en: '2026-09-12T10:05:00Z',
          segundos_restantes: 300,
        }),
      ),
    )
    await nextTick()
    await wrapper.setProps({ estado: estadoSesion(crearAviso('Otro aviso')) })
    await nextTick()
    await wrapper.setProps({ estado: estadoSesion(null) })
    await nextTick()

    // La votación de la fixture está en curso y no tiene ventana de resultado: ninguna pieza
    // compartida necesita reloj, así que cualquier llamada vendría del aviso.
    expect(intervalos).not.toHaveBeenCalled()
    expect(esperas).not.toHaveBeenCalled()
  })

  it('el código del Zócalo no contiene temporizadores, polling ni pedidos de red propios', () => {
    for (const [archivo, fuente] of [
      ['PantallaZocalo.vue', fuentePantallaZocalo],
      ['app.vue', fuenteAppZocalo],
      ['useEstadoZocalo.ts', fuenteEstadoZocalo],
    ] as const) {
      for (const prohibido of [
        'setInterval(',
        'setTimeout(',
        'requestAnimationFrame(',
        'fetch(',
        'EventSource(',
      ]) {
        expect(fuente, `${archivo} no debe usar ${prohibido}`).not.toContain(prohibido)
      }
    }
  })
})

describe('WP-103 · el aviso no agrega controles', () => {
  it('con aviso no hay elementos interactivos; sólo la región de estado accesible del aviso', () => {
    const wrapper = montarZocalo(estadoSesion(crearAviso('Cuarto intermedio')))

    for (const selector of ['button', 'input', 'select', 'textarea', 'a', 'form']) {
      expect(wrapper.findAll(selector), `sin elementos «${selector}»`).toHaveLength(0)
    }
    expect(wrapper.findAll('[contenteditable]')).toHaveLength(0)
    expect(wrapper.findAll('[tabindex]')).toHaveLength(0)
    // `AvisoSuperficie` declara `role="status"`: es una región que los lectores de pantalla
    // anuncian, no un control. Es el único rol permitido.
    const roles = wrapper.findAll('[role]').map((nodo) => nodo.element.getAttribute('role'))
    expect(roles).toEqual(['status'])
  })
})
