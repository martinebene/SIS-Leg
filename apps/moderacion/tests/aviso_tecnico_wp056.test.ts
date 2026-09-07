/**
 * Sustitución del cuadrante 4 por un aviso de Apoyo Técnico (WP-056).
 *
 * Comprueban las decisiones humanas cerradas que se pueden verificar sobre el DOM del
 * shell productivo de Moderación:
 *
 * 1. un aviso dirigido a Moderación reemplaza **completamente** Q4: el panel de Eventos
 *    y su selector de nivel dejan de existir en el árbol, no quedan ocultos ni detrás;
 * 2. un aviso dirigido sólo al Recinto no llega siquiera al snapshot de Moderación, así
 *    que Q4 sigue intacto;
 * 3. AMBOS sí reemplaza Q4, porque el backend deja el mismo aviso en las dos ranuras;
 * 4. al expirar o cancelarse el aviso, el panel de Eventos reaparece con el nivel visible
 *    que el operador había elegido;
 * 5. Q1, Q2 y Q3 nunca se ven afectados.
 *
 * La ausencia real de scroll y la geometría del reemplazo se miden aparte con Playwright:
 * el DOM de estas pruebas no calcula layout.
 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { compile, ssrContextKey, type Component } from 'vue'
import { mount, type VueWrapper } from '@vue/test-utils'
import type {
  ApoyoTecnicoProyectado,
  ClienteModeracion,
  EstadoModeracion,
} from '@sis-leg/api-client'
import App from '../app/app.vue'
import fuenteApp from '../app/app.vue?raw'
import PanelContenedor from '../app/components/PanelContenedor.vue'
import fuentePanelContenedor from '../app/components/PanelContenedor.vue?raw'
import PanelEventos from '../app/components/PanelEventos.vue'
import fuentePanelEventos from '../app/components/PanelEventos.vue?raw'
import AvisoSuperficie from '@sis-leg/frontend-shared/componentes/AvisoSuperficie.vue'
import fuenteAvisoSuperficie from '@sis-leg/frontend-shared/componentes/AvisoSuperficie.vue?raw'
import {
  reiniciarInstanciaCompartidaParaPruebas,
  useEstadoModeracion,
} from '../app/composables/useEstadoModeracion'

/**
 * El entorno de Vitest compila los SFC para SSR. Esta adaptación adjunta el render de
 * cliente de la misma plantilla productiva para poder inspeccionar el DOM real.
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

habilitarRenderCliente(PanelContenedor, fuentePanelContenedor)
habilitarRenderCliente(PanelEventos, fuentePanelEventos, { PanelContenedor })
habilitarRenderCliente(AvisoSuperficie, fuenteAvisoSuperficie)

const wrappers: VueWrapper[] = []

afterEach(() => {
  while (wrappers.length) wrappers.pop()?.unmount()
  reiniciarInstanciaCompartidaParaPruebas()
})

/** Porción técnica sin transmisión ni aviso: el estado inicial del backend. */
function tecnicoSinAviso(): ApoyoTecnicoProyectado {
  return {
    transmision: {
      estado: 'APAGADO',
      iniciada_en: null,
      en_vivo_desde: null,
      cuenta_regresiva_segundos: null,
      segundos_restantes: null,
    },
    aviso: null,
  }
}

/** Porción técnica con un aviso vigente para esta pantalla. */
function tecnicoConAviso(destino: 'MODERACION' | 'AMBOS'): ApoyoTecnicoProyectado {
  return {
    ...tecnicoSinAviso(),
    aviso: {
      aviso_id: 'aviso-1',
      texto: 'Cuarto intermedio de quince minutos',
      destino,
      publicado_en: '2026-09-02T10:00:00Z',
      expira_en: null,
      segundos_restantes: null,
    },
  }
}

function crearEstado(tecnico: ApoyoTecnicoProyectado): EstadoModeracion {
  return {
    instancia: 'instancia-prueba',
    revision: 1,
    generado_en: '2026-09-02T10:00:00Z',
    estado_global: 'SESION_ABIERTA',
    eventos_recientes: [
      {
        seq: 1,
        timestamp: '2026-09-02 10:00:00',
        nivel: 'L1',
        etiqueta: 'INPUT',
        codigo_evento: 'PULSACION_RECIBIDA',
        mensaje: 'Pulsación recibida',
        hecho: null,
      },
    ],
    concejales: [],
    tecnico,
  } as unknown as EstadoModeracion
}

/**
 * Monta el shell productivo alimentándolo con snapshots controlados.
 *
 * El shell obtiene su estado de la instancia compartida de `useEstadoModeracion`. Se la
 * siembra antes de montar con un cliente espía que no abre ninguna conexión: así se
 * prueba exactamente el componente productivo, sin red y sin reimplementar su plantilla.
 */
function montarShell(tecnico: ApoyoTecnicoProyectado): {
  wrapper: VueWrapper
  emitir: (tecnico: ApoyoTecnicoProyectado) => Promise<void>
} {
  let alEstado: ((estado: EstadoModeracion) => void) | null = null
  const cliente = {
    suscribirEstado: vi.fn((opciones: { alEstado: (estado: EstadoModeracion) => void }) => {
      alEstado = opciones.alEstado
      opciones.alEstado(crearEstado(tecnico))
      return { activa: true, cancelar: vi.fn() }
    }),
  } as unknown as ClienteModeracion

  // Sembrar la instancia compartida: el `useEstadoModeracion()` sin argumentos del shell
  // reutiliza esta misma instancia en lugar de crear un cliente contra la red.
  useEstadoModeracion(cliente)

  habilitarRenderCliente(App, fuenteApp, { PanelEventos, AvisoSuperficie })

  const wrapper = mount(App, {
    global: {
      provide: { [ssrContextKey]: { modules: new Set() } },
      stubs: {
        CabeceraModeracion: true,
        PanelSesionVotacion: true,
        PanelOrdenDelDia: true,
        PanelRecintoPalabra: true,
      },
    },
  })
  wrappers.push(wrapper)

  return {
    wrapper,
    emitir: async (nuevoTecnico) => {
      alEstado?.(crearEstado(nuevoTecnico))
      await wrapper.vm.$nextTick()
    },
  }
}

describe('Aviso técnico en el cuadrante 4 de Moderación', () => {
  it('mantiene el panel de Eventos cuando no hay aviso dirigido a esta pantalla', () => {
    const { wrapper } = montarShell(tecnicoSinAviso())

    expect(wrapper.find('[data-testid="panel-eventos"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="aviso-tecnico-moderacion"]').exists()).toBe(false)
  })

  it.each<'MODERACION' | 'AMBOS'>(['MODERACION', 'AMBOS'])(
    'reemplaza Q4 por completo con un aviso %s',
    async (destino) => {
      const { wrapper, emitir } = montarShell(tecnicoSinAviso())

      await emitir(tecnicoConAviso(destino))

      expect(wrapper.get('[data-testid="aviso-tecnico-moderacion"]').text()).toContain(
        'Cuarto intermedio de quince minutos',
      )
      // Reemplazo real: ni el panel ni su selector de nivel siguen en el árbol.
      expect(wrapper.find('[data-testid="panel-eventos"]').exists()).toBe(false)
      expect(wrapper.find('[data-testid="filtro-eventos"]').exists()).toBe(false)
      expect(wrapper.find('[data-testid="lista-eventos"]').exists()).toBe(false)
    },
  )

  it('no toca los otros tres cuadrantes', async () => {
    const { wrapper, emitir } = montarShell(tecnicoSinAviso())
    const grilla = wrapper.get('[data-testid="grilla-paneles"]')
    const cuadrantesAntes = grilla.element.children.length

    await emitir(tecnicoConAviso('AMBOS'))

    expect(wrapper.find('panel-sesion-votacion-stub').exists()).toBe(true)
    expect(wrapper.find('panel-orden-del-dia-stub').exists()).toBe(true)
    expect(wrapper.find('panel-recinto-palabra-stub').exists()).toBe(true)
    // La grilla conserva exactamente cuatro celdas ocupadas: el aviso ocupa una, no suma.
    expect(grilla.element.children.length).toBe(cuadrantesAntes)
  })

  it('restaura el panel con el nivel elegido al expirar o cancelarse el aviso', async () => {
    const { wrapper, emitir } = montarShell(tecnicoSinAviso())

    // El operador cambia el nivel visible antes de que aparezca el aviso.
    await wrapper.get('[data-testid="filtro-eventos"]').setValue('L1')
    expect(wrapper.findAll('[data-testid="evento-reciente"]')).toHaveLength(1)

    await emitir(tecnicoConAviso('MODERACION'))
    expect(wrapper.find('[data-testid="panel-eventos"]').exists()).toBe(false)

    // Expiración o cancelación: en ambos casos el backend deja de proyectar el aviso.
    await emitir(tecnicoSinAviso())

    expect(wrapper.find('[data-testid="panel-eventos"]').exists()).toBe(true)
    expect((wrapper.get('[data-testid="filtro-eventos"]').element as HTMLSelectElement).value).toBe(
      'L1',
    )
    expect(wrapper.findAll('[data-testid="evento-reciente"]')).toHaveLength(1)
  })
})
