/**
 * WP-070 — Microcopy del impedimento para cargar el Orden del Día.
 *
 * Qué demuestra este archivo:
 *
 * 1. El diccionario compartido devuelve el texto exacto aprobado por HUMAN_GATE cuando el
 *    motivo `ESTADO_INCOMPATIBLE` se lee desde la capacidad `cargar_orden_del_dia`.
 * 2. Ese mismo código conserva su redacción general en cualquier otro contexto. Es el
 *    criterio de aceptación 2 del WP y la razón por la que la traducción es contextual y
 *    no una reescritura del diccionario.
 * 3. El panel real de Moderación muestra ese texto cuando el sistema todavía está
 *    `SIN_PREPARAR`, y sigue mostrando la redacción general para el descarte.
 *
 * El texto se compara con `toBe` y letra por letra: HUMAN_GATE lo fijó sin tildes y sin
 * punto final, y prohibió corregirle la ortografía sin una decisión nueva. Una prueba con
 * `toContain` dejaría pasar precisamente el arreglo que no está autorizado.
 */

import { compile, type Component, ssrContextKey } from 'vue'
import { mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ClienteModeracion, EstadoModeracion } from '@sis-leg/api-client'
import PanelContenedor from '../app/components/PanelContenedor.vue'
import fuentePanelContenedor from '../app/components/PanelContenedor.vue?raw'
import PanelOrdenDelDia from '../app/components/PanelOrdenDelDia.vue'
import fuentePanelOrdenDelDia from '../app/components/PanelOrdenDelDia.vue?raw'
import { reiniciarInstanciaCompartidaParaPruebas } from '../app/composables/useEstadoModeracion'
import { traducirMotivo, traducirMotivos } from '../app/utils/motivos'

/** Texto exacto cerrado por HUMAN_GATE. No se normaliza ni se acentúa. */
const TEXTO_APROBADO = 'Debe comenzar a preparar el recinto antes de cargar el orden del dia'

/** Redacción general del mismo código, vigente desde antes de este WP. */
const TEXTO_GENERAL = 'El estado actual del sistema no permite ejecutar esta acción.'

/**
 * Compila la plantilla del componente para poder montarlo fuera de Nuxt.
 *
 * Es la misma técnica que ya usan las suites de Moderación: los SFC se construyen con el
 * render de servidor y sin esto no producirían DOM en Vitest.
 */
function habilitarRenderCliente(
  componente: Component,
  fuente: string,
  componentesLocales: Record<string, Component> = {},
): void {
  const coincidencia = fuente.match(/<template>([\s\S]*)<\/template>/)
  if (!coincidencia?.[1]) throw new Error('No se encontró la plantilla Vue del componente')

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

afterEach(() => {
  while (montados.length > 0) montados.pop()?.unmount()
})

/** Cliente mínimo: sólo necesita reportar conexión para que el panel se pinte completo. */
function crearCliente(): ClienteModeracion {
  return {
    cargarOrdenDelDia: vi.fn().mockResolvedValue({ puntos: [] }),
    descartarOrdenDelDia: vi.fn().mockResolvedValue(undefined),
    suscribirEstado: vi.fn((opciones: { alCambiarConexion?: (valor: boolean) => void }) => {
      opciones.alCambiarConexion?.(true)
      return { activa: true, cancelar: vi.fn() }
    }),
  } as unknown as ClienteModeracion
}

/**
 * Estado `SIN_PREPARAR`: es el único momento en que el operador ve el impedimento.
 *
 * El backend publica exactamente esto —`ESTADO_INCOMPATIBLE` en carga y en descarte—
 * porque ambas capacidades sólo existen en PREPARANDO y en SESION_ABIERTA.
 */
function crearEstadoSinPreparar(): EstadoModeracion {
  return {
    revision: 1,
    generado_en: '2026-09-04T10:00:00Z',
    estado_global: 'SIN_PREPARAR',
    preparacion: null,
    sesion: null,
    configuracion: {
      quorum: 7,
      filas_bancas: [3, 4, 5],
      tipos_votacion: ['Proyecto', 'Moción'],
      duracion_test_segundos: 3,
      revelado_votos_moderacion_segundos: 4,
      cuenta_regresiva_recinto_segundos: 3,
      resultado_publico_recinto_segundos: 6,
    },
    concejales: [],
    quorum: { cantidad_presentes: 0, requerido: 7, alcanzado: false },
    votacion: null,
    palabra: { orador: null, cola: [] },
    orden_del_dia: [],
    eventos_recientes: [],
    auditoria: { activa: false, disponible: true, fallado: false, cerrado: false, motivo: null },
    remapeo: null,
    capacidades: {
      preparar_sala: { habilitada: true, motivos: [] },
      actualizar_preparacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      cancelar_preparacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      abrir_sesion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      actualizar_sesion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      cerrar_sesion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      cargar_orden_del_dia: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      descartar_orden_del_dia: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      abrir_votacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      finalizar_votacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      desempatar: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      otorgar_palabra: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      quitar_palabra: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      iniciar_remapeo: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      confirmar_remapeo: { habilitada: false, motivos: ['REMAPEO_NO_COINCIDE'] },
      cancelar_remapeo: { habilitada: false, motivos: ['REMAPEO_NO_COINCIDE'] },
    },
  } as unknown as EstadoModeracion
}

describe('WP-070 · traducción contextual del impedimento de carga', () => {
  it('usa el texto aprobado sólo en el contexto de cargar el Orden del Día', () => {
    expect(traducirMotivo('ESTADO_INCOMPATIBLE', 'cargar_orden_del_dia')).toBe(TEXTO_APROBADO)
  })

  it('conserva la redacción general del mismo código en los demás contextos', () => {
    // Sin contexto: cualquier capacidad que todavía no necesite redacción propia.
    expect(traducirMotivo('ESTADO_INCOMPATIBLE')).toBe(TEXTO_GENERAL)
    // Con otro contexto ya existente: WP-051 no queda alterado por este cambio.
    expect(traducirMotivo('ESTADO_INCOMPATIBLE', 'abrir_votacion')).toBe(TEXTO_GENERAL)
    expect(traducirMotivo('QUORUM_INSUFICIENTE', 'abrir_votacion')).toBe(
      'Quórum insuficiente para abrir una votación.',
    )
  })

  it('no altera los demás motivos leídos desde el contexto nuevo', () => {
    // El contexto sólo agrega una redacción para un código; el resto cae en el diccionario.
    expect(traducirMotivo('AUDITORIA_NO_DISPONIBLE', 'cargar_orden_del_dia')).toBe(
      traducirMotivo('AUDITORIA_NO_DISPONIBLE'),
    )
    expect(traducirMotivos(['ESTADO_INCOMPATIBLE', 'COLA_VACIA'], 'cargar_orden_del_dia')).toEqual([
      TEXTO_APROBADO,
      'No hay pedidos de palabra registrados en la cola.',
    ])
  })
})

describe('WP-070 · PanelOrdenDelDia antes de preparar el recinto', () => {
  beforeEach(() => reiniciarInstanciaCompartidaParaPruebas())

  it('muestra el texto exacto aprobado en la vista de carga', () => {
    const wrapper = mount(PanelOrdenDelDia, {
      props: { estado: crearEstadoSinPreparar(), clienteInyectado: crearCliente() },
      global: { provide: { [ssrContextKey]: { modules: new Set() } } },
    })
    montados.push(wrapper)

    const carga = wrapper.get('[data-testid="carga-orden-dia"]')
    expect(carga.text()).toContain(TEXTO_APROBADO)
    // La redacción general del mismo código no debe aparecer en esta vista.
    expect(carga.text()).not.toContain(TEXTO_GENERAL)
  })

  it('no cambia la redacción del impedimento de descarte', () => {
    // El descarte sólo se dibuja con una colección ya cargada; se fuerza esa vista.
    const estado = crearEstadoSinPreparar()
    const conPuntos = {
      ...estado,
      orden_del_dia: [
        {
          nro_votacion: 1,
          tipo: 'Proyecto',
          tema: 'Tema de prueba',
          tipo_mayoria: 'SIMPLE',
          factor: 0,
          base: 'VOTOS_COMPUTABLES',
          tratado: false,
        },
      ],
    } as unknown as EstadoModeracion

    const wrapper = mount(PanelOrdenDelDia, {
      props: { estado: conPuntos, clienteInyectado: crearCliente() },
      global: { provide: { [ssrContextKey]: { modules: new Set() } } },
    })
    montados.push(wrapper)

    expect(wrapper.text()).toContain(TEXTO_GENERAL)
    expect(wrapper.text()).not.toContain(TEXTO_APROBADO)
  })
})
