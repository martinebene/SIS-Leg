/**
 * Presentación del factor de mayoría especial en Moderación (WP-063).
 *
 * Estas pruebas cubren las dos superficies visibles del panel de Moderación:
 *
 * - el rótulo "Regla" de Q1, que describe la votación en curso;
 * - el renglón de cada punto ESPECIAL del Orden del Día en Q2.
 *
 * Ambas deben escribir el factor con exactamente dos decimales truncados. La tercera
 * comprobación es la contracara imprescindible del WP: el campo editable del formulario
 * de apertura **no** se trunca, porque ese texto es el valor que después viaja al backend.
 * Confundir presentación con dato editable convertiría un cambio visual en una pérdida
 * silenciosa de precisión institucional.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { compile, type Component, ssrContextKey } from 'vue'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import type {
  ClienteModeracion,
  EstadoModeracion,
  PuntoOrdenDelDiaProyectado,
  VotacionModeracion,
} from '@sis-leg/api-client'
import DialogoConfirmacionApertura from '../app/components/DialogoConfirmacionApertura.vue'
import fuenteDialogoConfirmacionApertura from '../app/components/DialogoConfirmacionApertura.vue?raw'
import GestionVotacion from '../app/components/GestionVotacion.vue'
import fuenteGestionVotacion from '../app/components/GestionVotacion.vue?raw'
import PanelContenedor from '../app/components/PanelContenedor.vue'
import fuentePanelContenedor from '../app/components/PanelContenedor.vue?raw'
import PanelOrdenDelDia from '../app/components/PanelOrdenDelDia.vue'
import fuentePanelOrdenDelDia from '../app/components/PanelOrdenDelDia.vue?raw'
import { reiniciarInstanciaCompartidaParaPruebas } from '../app/composables/useEstadoModeracion'

/**
 * Vitest compila los SFC para SSR; este helper adjunta el render de cliente de la misma
 * plantilla productiva para poder leer e interactuar con el DOM. No duplica lógica: cubre
 * la frontera de compilación que en la aplicación real aporta Nuxt.
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
habilitarRenderCliente(DialogoConfirmacionApertura, fuenteDialogoConfirmacionApertura)
habilitarRenderCliente(GestionVotacion, fuenteGestionVotacion, { DialogoConfirmacionApertura })
habilitarRenderCliente(PanelOrdenDelDia, fuentePanelOrdenDelDia, { PanelContenedor })

const montados: VueWrapper[] = []

function montar(componente: Component, props: Record<string, unknown>): VueWrapper {
  const wrapper = mount(componente, {
    props,
    global: { provide: { [ssrContextKey]: { modules: new Set() } } },
  })
  montados.push(wrapper)
  return wrapper
}

function crearCapacidades(): EstadoModeracion['capacidades'] {
  return {
    preparar_sala: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
    actualizar_preparacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
    cancelar_preparacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
    abrir_sesion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
    actualizar_sesion: { habilitada: true, motivos: [] },
    cerrar_sesion: { habilitada: true, motivos: [] },
    cargar_orden_del_dia: { habilitada: true, motivos: [] },
    descartar_orden_del_dia: { habilitada: true, motivos: [] },
    abrir_votacion: { habilitada: true, motivos: [] },
    finalizar_votacion: { habilitada: false, motivos: ['VOTACION_NO_EN_CURSO'] },
    desempatar: { habilitada: false, motivos: ['VOTACION_NO_EMPATADA'] },
    otorgar_palabra: { habilitada: true, motivos: [] },
    quitar_palabra: { habilitada: true, motivos: [] },
    iniciar_remapeo: { habilitada: true, motivos: [] },
    confirmar_remapeo: { habilitada: false, motivos: ['REMAPEO_NO_COINCIDE'] },
    cancelar_remapeo: { habilitada: false, motivos: ['REMAPEO_NO_COINCIDE'] },
  }
}

function crearVotacion(parcial: Partial<VotacionModeracion> = {}): VotacionModeracion {
  return {
    id: 'votacion-1',
    numero_votacion: 7,
    tipo: 'Proyecto',
    tema: 'Modificación del reglamento',
    tipo_mayoria: 'ESPECIAL',
    factor: 0.6789,
    base: 'CUERPO',
    estado_recepcion: 'EN_CURSO',
    resultado: null,
    fecha_hora_apertura: '2026-09-03T10:00:00Z',
    fecha_hora_cierre: null,
    fecha_hora_resultado: null,
    motivo_finalizacion_manual: null,
    cantidad_votos_recibidos: 2,
    revelado_individual_desde: '2026-09-03T10:00:04Z',
    votos_individuales_revelados: false,
    votos_individuales: null,
    conteos: null,
    voto_presidencial: null,
    ...parcial,
  }
}

function crearEstado(parcial: Partial<EstadoModeracion> = {}): EstadoModeracion {
  return {
    revision: 1,
    generado_en: '2026-09-03T10:00:01Z',
    estado_global: 'SESION_ABIERTA',
    preparacion: null,
    sesion: {
      fecha_hora_inicio_preparacion: '2026-09-03T09:00:00Z',
      fecha_hora_apertura: '2026-09-03T09:30:00Z',
      numero_sesion: 42,
      presidencia: 'Dra. Presidencia',
      secretaria_legislativa: 'Sr. Secretaría',
    },
    configuracion: {
      quorum: 2,
      filas_bancas: [3],
      tipos_votacion: ['Proyecto', 'Moción'],
      duracion_test_segundos: 3,
      revelado_votos_moderacion_segundos: 4,
      cuenta_regresiva_recinto_segundos: 3,
      resultado_publico_recinto_segundos: 6,
    },
    concejales: [],
    quorum: { cantidad_presentes: 3, requerido: 2, alcanzado: true },
    votacion: null,
    palabra: { orador: null, cola: [] },
    orden_del_dia: [],
    eventos_recientes: [],
    auditoria: { activa: true, disponible: true, fallado: false, cerrado: false, motivo: null },
    remapeo: null,
    capacidades: crearCapacidades(),
    ...parcial,
  }
}

function crearCliente(parcial: Partial<ClienteModeracion> = {}): ClienteModeracion {
  return {
    cargarOrdenDelDia: vi.fn().mockResolvedValue({ puntos: [] }),
    descartarOrdenDelDia: vi.fn().mockResolvedValue(undefined),
    abrirVotacion: vi.fn().mockResolvedValue({ id: 'votacion-2' }),
    finalizarVotacion: vi.fn().mockResolvedValue(undefined),
    desempatar: vi.fn().mockResolvedValue(undefined),
    suscribirEstado: vi.fn((opciones) => {
      opciones?.alCambiarConexion?.(true)
      return { activa: true, cancelar: vi.fn() }
    }),
    ...parcial,
  } as unknown as ClienteModeracion
}

/** Punto ESPECIAL del Orden del Día con el factor real que se quiere presentar truncado. */
function crearPuntoEspecial(factor: number): PuntoOrdenDelDiaProyectado {
  return {
    nro_votacion: 7,
    tipo: 'Moción',
    tema: 'Modificación del reglamento',
    tipo_mayoria: 'ESPECIAL',
    factor,
    base: 'CUERPO',
    tratado: false,
  }
}

beforeEach(() => reiniciarInstanciaCompartidaParaPruebas())

afterEach(() => {
  while (montados.length > 0) montados.pop()?.unmount()
  document.body.textContent = ''
})

describe('WP-063 · factor con dos decimales truncados en Moderación', () => {
  it('trunca el factor de la votación en curso en el rótulo de regla de Q1', async () => {
    const wrapper = montar(GestionVotacion, {
      estado: crearEstado({ votacion: crearVotacion({ factor: 0.6789 }) }),
      cliente: crearCliente(),
      conectado: true,
      puntoPreseleccionado: null,
    })

    expect(wrapper.text()).toContain('0.67')
    expect(wrapper.text()).not.toContain('0.6789')

    // Un valor que un redondeo llevaría al centésimo siguiente debe seguir truncándose.
    await wrapper.setProps({
      estado: crearEstado({ votacion: crearVotacion({ factor: 0.6799 }) }),
    })
    expect(wrapper.text()).toContain('0.67')
    expect(wrapper.text()).not.toContain('0.68')

    // Un entero exacto se completa a dos decimales en lugar de mostrarse como "1".
    await wrapper.setProps({ estado: crearEstado({ votacion: crearVotacion({ factor: 1 }) }) })
    expect(wrapper.text()).toContain('1.00')
  })

  it('trunca el factor de cada punto ESPECIAL del Orden del Día', async () => {
    const wrapper = montar(PanelOrdenDelDia, {
      estado: crearEstado({ orden_del_dia: [crearPuntoEspecial(0.6789)] }),
      clienteInyectado: crearCliente(),
    })

    const punto = wrapper.get('[data-testid="punto-orden-dia"]')
    expect(punto.text()).toContain('Factor 0.67')
    expect(punto.text()).not.toContain('0.6789')

    // `0.6` debe completarse a `0.60`, no mostrarse con un solo decimal.
    await wrapper.setProps({
      estado: crearEstado({ orden_del_dia: [crearPuntoEspecial(0.6)] }),
    })
    expect(wrapper.get('[data-testid="punto-orden-dia"]').text()).toContain('Factor 0.60')
  })

  it('conserva la precisión real del factor en el campo editable y en la apertura enviada', async () => {
    // Criterio de aceptación 5: el truncamiento es sólo un rótulo. El punto copiado precarga
    // el formulario con el factor completo y ese mismo número es el que llega al backend.
    const abrir = vi.fn().mockResolvedValue({ id: 'votacion-especial' })
    const wrapper = montar(GestionVotacion, {
      estado: crearEstado(),
      cliente: crearCliente({ abrirVotacion: abrir }),
      conectado: true,
      puntoPreseleccionado: null,
    })

    await wrapper.setProps({ puntoPreseleccionado: crearPuntoEspecial(0.6789) })

    const campoFactor = wrapper.get('[data-testid="input-factor-mayoria"]')
    expect((campoFactor.element as HTMLInputElement).value).toBe('0.6789')

    await wrapper.get('[data-testid="btn-abrir-votacion"]').trigger('click')
    await flushPromises()
    expect(abrir).toHaveBeenCalledWith({
      numero_votacion: 7,
      tipo: 'Moción',
      tema: 'Modificación del reglamento',
      tipo_mayoria: 'ESPECIAL',
      factor: 0.6789,
      base: 'CUERPO',
    })
  })
})
