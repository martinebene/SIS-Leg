/**
 * Regresión de WP-102: la acción `Quitar Orden del Día` vive en la barra de título de Q2.
 *
 * El Work Package sólo reubica un control ya existente, así que estas pruebas se concentran
 * en dos cosas distintas:
 *
 * 1. **Dónde** está el botón. Se exige que el DOM productivo lo dibuje dentro del `<header>`
 *    del panel, después del badge de cantidad, y que el cuerpo desplazable ya no reserve la
 *    fila que antes ocupaba.
 * 2. **Que nada más haya cambiado**. Habilitación por capacidad, texto transitorio
 *    `Quitando...`, comando enviado al backend y motivos de indisponibilidad siguen
 *    comportándose igual que antes de mover el botón.
 *
 * La altura real de la cabecera sólo puede medirse con un motor de layout, y eso lo cubre la
 * prueba Playwright correspondiente. Acá se verifica la condición que la hace posible: el
 * botón declara exactamente la misma caja vertical que el badge (`text-xs`, `py-0.5` y un
 * borde de 1 px), de modo que dentro de un `flex items-center` no puede estirar el
 * encabezado.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { compile, type Component, ssrContextKey } from 'vue'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import type {
  ClienteModeracion,
  EstadoModeracion,
  PuntoOrdenDelDiaProyectado,
} from '@sis-leg/api-client'
import PanelContenedor from '../app/components/PanelContenedor.vue'
import fuentePanelContenedor from '../app/components/PanelContenedor.vue?raw'
import PanelOrdenDelDia from '../app/components/PanelOrdenDelDia.vue'
import fuentePanelOrdenDelDia from '../app/components/PanelOrdenDelDia.vue?raw'
import { reiniciarInstanciaCompartidaParaPruebas } from '../app/composables/useEstadoModeracion'

/**
 * Vitest compila los SFC para SSR; este helper adjunta el render de cliente de la misma
 * plantilla productiva para poder interactuar con el DOM. No duplica lógica: sólo cubre la
 * frontera de compilación que en la aplicación real aporta Nuxt.
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
habilitarRenderCliente(PanelOrdenDelDia, fuentePanelOrdenDelDia, { PanelContenedor })

const montados: VueWrapper[] = []

function montar(props: Record<string, unknown>): VueWrapper {
  const wrapper = mount(PanelOrdenDelDia, {
    props,
    global: { provide: { [ssrContextKey]: { modules: new Set() } } },
  })
  montados.push(wrapper)
  return wrapper
}

const puntos: PuntoOrdenDelDiaProyectado[] = [
  {
    nro_votacion: 1,
    tipo: 'Proyecto',
    tema: 'Presupuesto anual',
    tipo_mayoria: 'SIMPLE',
    factor: 0,
    base: 'VOTOS_COMPUTABLES',
    tratado: false,
  },
  {
    nro_votacion: 2,
    tipo: 'Moción',
    tema: 'Modificación del reglamento',
    tipo_mayoria: 'ESPECIAL',
    factor: 0.66,
    base: 'CUERPO',
    tratado: false,
  },
]

function crearCapacidades(
  parcial: Partial<EstadoModeracion['capacidades']> = {},
): EstadoModeracion['capacidades'] {
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
    ...parcial,
  }
}

function crearEstado(parcial: Partial<EstadoModeracion> = {}): EstadoModeracion {
  return {
    instancia: 'instancia-prueba',
    revision: 1,
    generado_en: '2026-09-12T10:00:00Z',
    estado_global: 'SESION_ABIERTA',
    preparacion: null,
    sesion: {
      fecha_hora_inicio_preparacion: '2026-09-12T09:00:00Z',
      fecha_hora_apertura: '2026-09-12T09:30:00Z',
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
    prepararSala: vi.fn().mockResolvedValue(undefined),
    cargarOrdenDelDia: vi.fn().mockResolvedValue({ puntos: [] }),
    descartarOrdenDelDia: vi.fn().mockResolvedValue(undefined),
    abrirVotacion: vi.fn().mockResolvedValue({ id: 'nueva-votacion' }),
    finalizarVotacion: vi.fn().mockResolvedValue(undefined),
    desempatar: vi.fn().mockResolvedValue(undefined),
    otorgarPalabra: vi.fn().mockResolvedValue(undefined),
    quitarPalabra: vi.fn().mockResolvedValue(undefined),
    iniciarRemapeo: vi.fn().mockResolvedValue({}),
    confirmarRemapeo: vi.fn().mockResolvedValue(undefined),
    cancelarRemapeo: vi.fn().mockResolvedValue(undefined),
    suscribirEstado: vi.fn((opciones) => {
      opciones?.alCambiarConexion?.(true)
      return { activa: true, cancelar: vi.fn() }
    }),
    ...parcial,
  } as unknown as ClienteModeracion
}

/** Clases CSS efectivas: el DOM mínimo de este repositorio no expone `classes()`. */
function clasesDe(wrapper: VueWrapper, selector: string): string[] {
  return (wrapper.get(selector).element as HTMLElement).className.split(/\s+/).filter(Boolean)
}

beforeEach(() => reiniciarInstanciaCompartidaParaPruebas())

afterEach(() => {
  while (montados.length > 0) montados.pop()?.unmount()
  document.body.textContent = ''
})

describe('WP-102 · la acción de descarte se dibuja en la cabecera de Q2', () => {
  it('con puntos cargados el botón está en el encabezado y después del badge de cantidad', () => {
    const wrapper = montar({
      estado: crearEstado({ orden_del_dia: puntos }),
      clienteInyectado: crearCliente(),
    })

    const encabezado = wrapper.get('header')
    expect(encabezado.find('[data-testid="btn-quitar-orden-dia"]').exists()).toBe(true)

    // El orden pedido por el WP es título -> badge -> acción. En un `flex` sin reordenar,
    // el orden del documento es el orden visual, así que alcanza con comparar posiciones.
    const htmlEncabezado = (encabezado.element as HTMLElement).innerHTML
    const posicionTitulo = htmlEncabezado.indexOf('Orden del Día')
    const posicionBadge = htmlEncabezado.indexOf('2 puntos')
    const posicionBoton = htmlEncabezado.indexOf('btn-quitar-orden-dia')
    expect(posicionTitulo).toBeGreaterThanOrEqual(0)
    expect(posicionBadge).toBeGreaterThan(posicionTitulo)
    expect(posicionBoton).toBeGreaterThan(posicionBadge)
  })

  it('el cuerpo desplazable ya no reserva una fila para la acción', () => {
    const wrapper = montar({
      estado: crearEstado({ orden_del_dia: puntos }),
      clienteInyectado: crearCliente(),
    })

    const cuerpo = wrapper.get('[data-testid="cuerpo-panel"]')
    expect(cuerpo.find('[data-testid="btn-quitar-orden-dia"]').exists()).toBe(false)
    // Sin motivos de indisponibilidad tampoco queda el bloque explicativo que lo acompañaba.
    expect(cuerpo.find('[data-testid="avisos-descarte-orden-dia"]').exists()).toBe(false)
    // La lista conserva su propio desplazamiento: el cuerpo sigue delegándolo.
    expect(clasesDe(wrapper, '[data-testid="lista-orden-dia"]')).toContain('overflow-y-auto')
  })

  it('el botón replica la caja vertical del badge, así el encabezado no puede crecer', () => {
    const wrapper = montar({
      estado: crearEstado({ orden_del_dia: puntos }),
      clienteInyectado: crearCliente(),
    })

    const clasesBadge = clasesDe(wrapper, 'header span')
    const clasesBoton = clasesDe(wrapper, '[data-testid="btn-quitar-orden-dia"]')
    for (const clase of ['py-0.5', 'text-xs', 'border']) {
      expect(clasesBadge).toContain(clase)
      expect(clasesBoton).toContain(clase)
    }
    // Ninguna clase puede agregar alto propio al encabezado.
    for (const clase of clasesBoton) {
      expect(clase).not.toMatch(/^(py-[1-9]|h-|min-h-|leading-)/)
    }
  })

  it('sin Orden del Día cargado la acción no se renderiza y el badge informa el estado', () => {
    const wrapper = montar({
      estado: crearEstado({ orden_del_dia: [] }),
      clienteInyectado: crearCliente(),
    })

    expect(wrapper.find('[data-testid="btn-quitar-orden-dia"]').exists()).toBe(false)
    expect(wrapper.get('header').text()).toContain('Sin cargar')
    expect(wrapper.get('[data-testid="carga-orden-dia"]').exists()).toBe(true)
  })
})

describe('WP-102 · la reubicación no cambia la semántica del descarte', () => {
  it('envía el comando una sola vez, muestra Quitando... y conserva la lista', async () => {
    let resolverDescarte: (() => void) | undefined
    const descartar = vi.fn(
      () =>
        new Promise<void>((resolver) => {
          resolverDescarte = resolver
        }),
    )
    const wrapper = montar({
      estado: crearEstado({ orden_del_dia: puntos }),
      clienteInyectado: crearCliente({ descartarOrdenDelDia: descartar }),
    })

    const boton = wrapper.get('[data-testid="btn-quitar-orden-dia"]')
    await boton.trigger('click')
    await boton.trigger('click')

    expect(descartar).toHaveBeenCalledTimes(1)
    expect(boton.text()).toBe('Quitando...')
    expect((boton.element as HTMLButtonElement).disabled).toBe(true)
    // La colección autoritativa sigue completa hasta que llegue el snapshot vacío.
    expect(wrapper.findAll('[data-testid="punto-orden-dia"]')).toHaveLength(2)

    resolverDescarte?.()
    await flushPromises()
    expect(wrapper.get('[data-testid="btn-quitar-orden-dia"]').text()).toBe('Quitar Orden del Día')
    expect(wrapper.get('[data-testid="aviso-orden-dia"]').text()).toContain(
      'Orden del Día descartado',
    )

    await wrapper.setProps({ estado: crearEstado({ revision: 2, orden_del_dia: [] }) })
    expect(wrapper.find('[data-testid="btn-quitar-orden-dia"]').exists()).toBe(false)
  })

  it('una capacidad deshabilitada apaga el botón y explica el motivo en el cuerpo', () => {
    const wrapper = montar({
      estado: crearEstado({
        orden_del_dia: puntos,
        capacidades: crearCapacidades({
          descartar_orden_del_dia: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
        }),
      }),
      clienteInyectado: crearCliente(),
    })

    expect(
      (wrapper.get('[data-testid="btn-quitar-orden-dia"]').element as HTMLButtonElement).disabled,
    ).toBe(true)
    const avisos = wrapper
      .get('[data-testid="cuerpo-panel"]')
      .get('[data-testid="avisos-descarte-orden-dia"]')
    expect(avisos.text()).toContain('estado actual del sistema no permite')
  })

  it('un error del backend se sigue mostrando en el cuerpo y no borra los puntos', async () => {
    const descartar = vi.fn().mockRejectedValue({ mensaje: 'Descarte rechazado' })
    const wrapper = montar({
      estado: crearEstado({ orden_del_dia: puntos }),
      clienteInyectado: crearCliente({ descartarOrdenDelDia: descartar }),
    })

    await wrapper.get('[data-testid="btn-quitar-orden-dia"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="alerta-error-orden-dia"]').text()).toContain(
      'Descarte rechazado',
    )
    expect(wrapper.findAll('[data-testid="punto-orden-dia"]')).toHaveLength(2)
    expect(
      (wrapper.get('[data-testid="btn-quitar-orden-dia"]').element as HTMLButtonElement).disabled,
    ).toBe(false)
  })
})
