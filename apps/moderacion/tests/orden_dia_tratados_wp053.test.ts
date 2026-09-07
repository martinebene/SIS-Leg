/**
 * Regresión de la ayuda asistencial "número ya tratado" del Orden del Día (WP-053).
 *
 * El backend informa por punto el campo `tratado`. Este panel sólo lo pinta: no lo calcula,
 * no lo recuerda entre snapshots y, sobre todo, no lo convierte en una restricción. Los
 * casos de abajo fijan exactamente eso:
 *
 * - un punto tratado se atenúa y lo declara en `data-tratado`;
 * - si el CSV repite el número, se atenúan todas las filas que lo comparten;
 * - un punto atenuado conserva click, emisión de la copia y toast, igual que cualquier otro;
 * - el estado llega siempre por `setProps`, equivalente a adoptar un snapshot/SSE nuevo,
 *   que es también lo que ocurre tras una reconexión o un reload.
 *
 * Ningún caso simula la apertura de una votación desde el frontend: la marca es una lectura
 * del estado autoritativo, nunca una consecuencia local de haber hecho click.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { compile, type Component, ssrContextKey } from 'vue'
import { mount, type VueWrapper } from '@vue/test-utils'
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
    cargar_orden_del_dia: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
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

function crearEstado(parcial: Partial<EstadoModeracion> = {}): EstadoModeracion {
  return {
    instancia: 'instancia-prueba',
    revision: 1,
    generado_en: '2026-09-02T10:00:00Z',
    estado_global: 'SESION_ABIERTA',
    preparacion: null,
    sesion: {
      fecha_hora_inicio_preparacion: '2026-09-02T09:00:00Z',
      fecha_hora_apertura: '2026-09-02T09:30:00Z',
      numero_sesion: 42,
      presidencia: 'Dra. Presidencia',
      secretaria_legislativa: 'Sr. Secretaría',
    },
    configuracion: {
      quorum: 2,
      filas_bancas: [3],
      tipos_votacion: ['Despacho', 'Moción'],
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
    actualizarPreparacion: vi.fn().mockResolvedValue(undefined),
    cancelarPreparacion: vi.fn().mockResolvedValue(undefined),
    abrirSesion: vi.fn().mockResolvedValue(undefined),
    actualizarSesion: vi.fn().mockResolvedValue(undefined),
    cerrarSesion: vi.fn().mockResolvedValue(undefined),
    cargarOrdenDelDia: vi.fn().mockResolvedValue({ puntos: [] }),
    descartarOrdenDelDia: vi.fn().mockResolvedValue(undefined),
    abrirVotacion: vi.fn().mockResolvedValue({ id: 'votacion-2' }),
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

/** Punto mínimo del Orden del Día proyectado, con la marca asistencial explícita. */
function crearPunto(
  nroVotacion: number,
  tratado: boolean,
  tema = `Tema ${nroVotacion}`,
): PuntoOrdenDelDiaProyectado {
  return {
    nro_votacion: nroVotacion,
    tipo: 'Despacho',
    tema,
    tipo_mayoria: 'SIMPLE',
    factor: 0,
    base: 'VOTOS_COMPUTABLES',
    tratado,
  }
}

/**
 * El entorno DOM liviano de estas pruebas no implementa `NamedNodeMap` ni un `classList`
 * iterable, así que `attributes()` y `classes()` de Vue Test Utils no sirven acá. Se leen
 * los mismos datos por la API que el mock sí soporta: `getAttribute` y `className`.
 */
function marcasRenderizadas(wrapper: VueWrapper): (string | null)[] {
  return wrapper
    .findAll('[data-testid="punto-orden-dia"]')
    .map((punto) => (punto.element as HTMLElement).getAttribute('data-tratado'))
}

/** Indica si la tarjeta lleva la clase de atenuación aplicada por el componente. */
function estaAtenuado(punto: { element: Element }): boolean {
  return (punto.element as HTMLElement).className.split(/\s+/).includes('opacity-50')
}

beforeEach(() => reiniciarInstanciaCompartidaParaPruebas())

afterEach(() => {
  while (montados.length > 0) montados.pop()?.unmount()
  document.body.textContent = ''
  vi.useRealTimers()
})

describe('WP-053 · atenuación de los números ya tratados', () => {
  it('atenúa sólo los puntos que el backend marca como tratados', () => {
    const wrapper = montar(PanelOrdenDelDia, {
      estado: crearEstado({
        orden_del_dia: [crearPunto(4, true), crearPunto(5, false)],
      }),
      clienteInyectado: crearCliente(),
    })

    const puntos = wrapper.findAll('[data-testid="punto-orden-dia"]')
    expect(puntos).toHaveLength(2)
    expect(puntos[0] && estaAtenuado(puntos[0])).toBe(true)
    expect(puntos[1] && estaAtenuado(puntos[1])).toBe(false)
    expect(marcasRenderizadas(wrapper)).toEqual(['true', 'false'])
    // La atenuación no puede quedar sólo en el color: el texto oculto la hace audible.
    expect(puntos[0]?.text()).toContain('número ya tratado en esta sesión')
    expect(puntos[1]?.text()).not.toContain('número ya tratado en esta sesión')
  })

  it('atenúa todas las filas que comparten un mismo número repetido en el CSV', () => {
    const wrapper = montar(PanelOrdenDelDia, {
      estado: crearEstado({
        orden_del_dia: [
          crearPunto(7, true, 'Primera lectura'),
          crearPunto(8, false, 'Otro asunto'),
          crearPunto(7, true, 'Segunda lectura'),
        ],
      }),
      clienteInyectado: crearCliente(),
    })

    expect(marcasRenderizadas(wrapper)).toEqual(['true', 'false', 'true'])
    // Las dos filas Nº 7 siguen siendo tarjetas distintas con su propio tema.
    const puntos = wrapper.findAll('[data-testid="punto-orden-dia"]')
    expect(puntos[0]?.text()).toContain('Primera lectura')
    expect(puntos[2]?.text()).toContain('Segunda lectura')
  })

  it('un punto atenuado sigue siendo clickeable, emite la copia y muestra el toast', async () => {
    const puntoTratado = crearPunto(4, true)
    const wrapper = montar(PanelOrdenDelDia, {
      estado: crearEstado({ orden_del_dia: [puntoTratado, crearPunto(5, false)] }),
      clienteInyectado: crearCliente(),
    })

    const boton = wrapper.findAll('[data-testid="punto-orden-dia"]')[0]
    expect((boton?.element as HTMLButtonElement).disabled).toBe(false)

    await boton?.trigger('click')

    // La copia que precarga Q1 es exactamente el punto proyectado, marca incluida.
    expect(wrapper.emitted('seleccionar')?.[0]?.[0]).toEqual(puntoTratado)
    expect(wrapper.get('[data-testid="toast-punto-copiado"]').text()).toContain(
      'Punto Nº 4 copiado al borrador',
    )
    // Copiar no consume el punto ni altera la colección proyectada.
    expect(marcasRenderizadas(wrapper)).toEqual(['true', 'false'])
  })

  it('adopta la marca de cada snapshot nuevo sin recordar el anterior', async () => {
    const wrapper = montar(PanelOrdenDelDia, {
      estado: crearEstado({
        orden_del_dia: [crearPunto(4, false), crearPunto(5, false)],
      }),
      clienteInyectado: crearCliente(),
    })

    expect(marcasRenderizadas(wrapper)).toEqual(['false', 'false'])

    // Abrir la votación Nº 5 llega como snapshot nuevo, igual que por SSE.
    await wrapper.setProps({
      estado: crearEstado({
        revision: 2,
        orden_del_dia: [crearPunto(4, false), crearPunto(5, true)],
      }),
    })
    expect(marcasRenderizadas(wrapper)).toEqual(['false', 'true'])

    // Una reconexión que trae un estado sin la marca la retira: el panel nunca
    // conserva un valor propio por encima del backend.
    await wrapper.setProps({
      estado: crearEstado({
        revision: 3,
        orden_del_dia: [crearPunto(4, false), crearPunto(5, false)],
      }),
    })
    expect(marcasRenderizadas(wrapper)).toEqual(['false', 'false'])
  })

  it('no muestra ninguna advertencia institucional por un número ya tratado', async () => {
    const wrapper = montar(PanelOrdenDelDia, {
      estado: crearEstado({ orden_del_dia: [crearPunto(4, true)] }),
      clienteInyectado: crearCliente(),
    })

    await wrapper.get('[data-testid="punto-orden-dia"]').trigger('click')

    expect(wrapper.find('[data-testid="alerta-error-orden-dia"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('repetido')
    expect(wrapper.text()).not.toContain('ya votado')
    // El botón de quitar es el único comando del cuadrante y sigue disponible.
    expect(
      (wrapper.get('[data-testid="btn-quitar-orden-dia"]').element as HTMLButtonElement).disabled,
    ).toBe(false)
  })
})
