/**
 * Pruebas interactivas del WP-024 sobre componentes productivos reales.
 *
 * Los escenarios demuestran la frontera autoritativa: los clicks llaman a
 * ClienteModeracion, pero cola, orador, eventos y remapeo cambian solamente
 * cuando la prueba entrega un snapshot posterior mediante props.
 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { compile, type Component, ssrContextKey } from 'vue'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import GestionPalabra from '../app/components/GestionPalabra.vue'
import fuenteGestionPalabra from '../app/components/GestionPalabra.vue?raw'
import GestionRemapeo from '@sis-leg/frontend-shared/componentes/GestionRemapeo.vue'
import fuenteGestionRemapeo from '@sis-leg/frontend-shared/componentes/GestionRemapeo.vue?raw'
import PanelRecintoPalabra from '../app/components/PanelRecintoPalabra.vue'
import fuentePanelRecintoPalabra from '../app/components/PanelRecintoPalabra.vue?raw'
import GrillaRecinto from '../app/components/GrillaRecinto.vue'
import fuenteGrillaRecinto from '../app/components/GrillaRecinto.vue?raw'
import BancaConcejal from '../app/components/BancaConcejal.vue'
import fuenteBancaConcejal from '../app/components/BancaConcejal.vue?raw'
import PanelContenedor from '../app/components/PanelContenedor.vue'
import fuentePanelContenedor from '../app/components/PanelContenedor.vue?raw'
import PanelEventos from '../app/components/PanelEventos.vue'
import fuentePanelEventos from '../app/components/PanelEventos.vue?raw'
import type { ClienteModeracion, ConcejalModeracion, EstadoModeracion } from '@sis-leg/api-client'

/**
 * El entorno de Vitest compila los SFC para SSR. Esta adaptación adjunta el
 * render de cliente de la misma plantilla productiva para interactuar con DOM.
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

habilitarRenderCliente(GestionPalabra, fuenteGestionPalabra)
habilitarRenderCliente(GestionRemapeo, fuenteGestionRemapeo)
habilitarRenderCliente(PanelContenedor, fuentePanelContenedor)
habilitarRenderCliente(PanelEventos, fuentePanelEventos, { PanelContenedor })
habilitarRenderCliente(BancaConcejal, fuenteBancaConcejal)
habilitarRenderCliente(GrillaRecinto, fuenteGrillaRecinto, { BancaConcejal })
habilitarRenderCliente(PanelRecintoPalabra, fuentePanelRecintoPalabra, {
  PanelContenedor,
  GestionPalabra,
  GestionRemapeo,
  GrillaRecinto,
})

const wrappers: VueWrapper[] = []

function montar(componente: Component, props: Record<string, unknown>): VueWrapper {
  const wrapper = mount(componente, {
    props,
    global: {
      // Los SFC llegan precompilados para SSR en Vitest; este contexto mínimo
      // reproduce el que Nuxt aporta al montar el mismo componente en la app.
      provide: { [ssrContextKey]: { modules: new Set() } },
    },
  })
  wrappers.push(wrapper)
  return wrapper
}

afterEach(() => {
  while (wrappers.length > 0) wrappers.pop()?.unmount()
})

function crearConcejales(): ConcejalModeracion[] {
  return [
    {
      dni: '1',
      nombre: 'Ada',
      apellido: 'Lovelace',
      bloque: 'Bloque A',
      banca: 1,
      dispositivo_votacion: 'dev01',
      ruta_imagen: 'assets/bancas/banca-01.png',
      presente: true,
      test_activo: false,
      test_expira_en: null,
    },
    {
      dni: '2',
      nombre: 'Grace',
      apellido: 'Hopper',
      bloque: 'Bloque B',
      banca: 2,
      dispositivo_votacion: 'dev02',
      ruta_imagen: 'assets/bancas/banca-02.png',
      presente: true,
      test_activo: false,
      test_expira_en: null,
    },
    {
      dni: '3',
      nombre: 'Edsger',
      apellido: 'Dijkstra',
      bloque: 'Bloque C',
      banca: 3,
      dispositivo_votacion: 'dev03',
      ruta_imagen: 'assets/bancas/banca-03.png',
      presente: true,
      test_activo: false,
      test_expira_en: null,
    },
  ]
}

function crearEstado(parcial: Partial<EstadoModeracion> = {}): EstadoModeracion {
  return {
    revision: 10,
    generado_en: '2026-08-27T10:00:00Z',
    estado_global: 'SESION_ABIERTA',
    preparacion: null,
    sesion: {
      fecha_hora_inicio_preparacion: '2026-08-27T09:00:00Z',
      fecha_hora_apertura: '2026-08-27T09:30:00Z',
      numero_sesion: 24,
      presidencia: 'Presidencia',
      secretaria_legislativa: 'Secretaría',
    },
    configuracion: null,
    concejales: crearConcejales(),
    quorum: { cantidad_presentes: 3, requerido: 2, alcanzado: true },
    votacion: null,
    palabra: {
      orador: { dni: '1', nombre: 'Ada', apellido: 'Lovelace', banca: 1 },
      cola: [
        { dni: '2', nombre: 'Grace', apellido: 'Hopper', banca: 2 },
        { dni: '3', nombre: 'Edsger', apellido: 'Dijkstra', banca: 3 },
      ],
    },
    orden_del_dia: [],
    eventos_recientes: [
      {
        seq: 1,
        timestamp: '2026-08-27T10:00:01',
        nivel: 'L1',
        etiqueta: 'SISTEMA',
        codigo_evento: 'EVENTO_L1',
        mensaje: 'Detalle técnico',
      },
      {
        seq: 2,
        timestamp: '2026-08-27T10:00:02',
        nivel: 'L2',
        etiqueta: 'OPERACION',
        codigo_evento: 'EVENTO_L2',
        mensaje: 'Detalle intermedio',
      },
      {
        seq: 3,
        timestamp: '2026-08-27T10:00:03',
        nivel: 'L3',
        etiqueta: 'PALABRA',
        codigo_evento: 'EVENTO_L3',
        mensaje: 'Hecho principal',
      },
    ],
    auditoria: { activa: true, disponible: true, fallado: false, cerrado: false, motivo: null },
    remapeo: null,
    capacidades: {
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
    },
    ...parcial,
  }
}

function crearCliente(parcial: Partial<ClienteModeracion> = {}): ClienteModeracion {
  return {
    otorgarPalabra: vi.fn().mockResolvedValue(undefined),
    quitarPalabra: vi.fn().mockResolvedValue(undefined),
    iniciarRemapeo: vi.fn().mockResolvedValue({}),
    confirmarRemapeo: vi.fn().mockResolvedValue(undefined),
    cancelarRemapeo: vi.fn().mockResolvedValue(undefined),
    ...parcial,
  } as unknown as ClienteModeracion
}

describe('Palabra autoritativa y CA-061', () => {
  it('muestra la cola FIFO completa sin repetir el orador como texto durante una votación', () => {
    const estado = crearEstado({
      votacion: {
        id: 'voto-activo',
        numero_votacion: 1,
        tipo: 'Moción',
        tema: 'Tema',
        tipo_mayoria: 'SIMPLE',
        factor: 0,
        base: 'VOTOS_COMPUTABLES',
        estado_recepcion: 'EN_CURSO',
        resultado: null,
        fecha_hora_apertura: '2026-08-27T10:00:00Z',
        fecha_hora_cierre: null,
        fecha_hora_resultado: null,
        motivo_finalizacion_manual: null,
        cantidad_votos_recibidos: 0,
        revelado_individual_desde: '2026-08-27T10:00:04Z',
        votos_individuales_revelados: false,
        votos_individuales: null,
        conteos: null,
        voto_presidencial: null,
      },
    })
    const wrapper = montar(GestionPalabra, {
      estado,
      cliente: crearCliente(),
      conectado: true,
    })

    // WP-044: el orador ya no se replica acá; su señal vive en la banca del recinto.
    expect(wrapper.find('[data-testid="orador-actual-texto"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Ada Lovelace')
    expect(wrapper.text()).not.toContain('Sin orador activo')
    expect(wrapper.text()).not.toContain('Cola FIFO autoritativa')
    expect(wrapper.get('[data-testid="pedido-palabra-1"]').text()).toContain('Grace Hopper')
    expect(wrapper.get('[data-testid="pedido-palabra-2"]').text()).toContain('Edsger Dijkstra')
    expect(
      (wrapper.get('[data-testid="btn-otorgar-palabra"]').element as HTMLButtonElement).disabled,
    ).toBe(false)
  })

  it('bloquea doble submit y no avanza ni quita palabra hasta recibir otro snapshot', async () => {
    let resolverQuitar: (() => void) | undefined
    const quitar = vi.fn(
      () =>
        new Promise<void>((resolver) => {
          resolverQuitar = resolver
        }),
    )
    const cliente = crearCliente({ quitarPalabra: quitar })
    const estadoInicial = crearEstado()
    const wrapper = montar(GestionPalabra, { estado: estadoInicial, cliente, conectado: true })

    await wrapper.get('[data-testid="btn-quitar-palabra"]').trigger('click')
    await wrapper.get('[data-testid="btn-quitar-palabra"]').trigger('click')
    expect(quitar).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('Grace Hopper')
    expect(wrapper.get('[data-testid="badge-cola-palabra"]').text()).toContain('2 en cola')

    resolverQuitar?.()
    await flushPromises()
    // El 204 no produce acuse ni renglón de estado: la cola sigue exactamente igual (WP-044).
    expect(wrapper.find('[data-testid="aviso-palabra"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Comando enviado')
    expect(wrapper.get('[data-testid="badge-cola-palabra"]').text()).toContain('2 en cola')

    const sinOrador = crearEstado({
      revision: 11,
      palabra: { orador: null, cola: estadoInicial.palabra?.cola ?? [] },
    })
    await wrapper.setProps({ estado: sinOrador })
    expect(wrapper.get('[data-testid="badge-cola-palabra"]').text()).toContain('2 en cola')

    await wrapper.get('[data-testid="btn-otorgar-palabra"]').trigger('click')
    expect(cliente.otorgarPalabra).toHaveBeenCalledTimes(1)
    expect(wrapper.get('[data-testid="badge-cola-palabra"]').text()).toContain('2 en cola')

    await wrapper.setProps({
      estado: crearEstado({
        revision: 12,
        palabra: {
          orador: { dni: '2', nombre: 'Grace', apellido: 'Hopper', banca: 2 },
          cola: [{ dni: '3', nombre: 'Edsger', apellido: 'Dijkstra', banca: 3 }],
        },
      }),
    })
    expect(wrapper.get('[data-testid="badge-cola-palabra"]').text()).toContain('1 en cola')
  })

  it('respeta conexión, capacidades y errores sin mutar la proyección visible', async () => {
    const otorgar = vi.fn().mockRejectedValue({ mensajeBackend: 'Auditoría no disponible' })
    const estado = crearEstado()
    const wrapper = montar(GestionPalabra, {
      estado,
      cliente: crearCliente({ otorgarPalabra: otorgar }),
      conectado: false,
    })
    expect(
      (wrapper.get('[data-testid="btn-otorgar-palabra"]').element as HTMLButtonElement).disabled,
    ).toBe(true)

    await wrapper.setProps({ conectado: true })
    await wrapper.get('[data-testid="btn-otorgar-palabra"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-testid="error-palabra"]').text()).toContain('Auditoría no disponible')
    expect(wrapper.text()).toContain('Grace Hopper')
    expect(wrapper.get('[data-testid="badge-cola-palabra"]').text()).toContain('2 en cola')
  })
})

describe('Eventos recientes y baseline reemplazable', () => {
  it('comienza en L3 y aplica los tres umbrales sin reinterpretar niveles', async () => {
    const wrapper = montar(PanelEventos, { estado: crearEstado() })
    expect(wrapper.findAll('[data-testid="evento-reciente"]')).toHaveLength(1)
    expect(wrapper.text()).toContain('EVENTO_L3')
    expect(wrapper.text()).not.toContain('EVENTO_L2')

    await wrapper.get('[data-testid="filtro-eventos"]').setValue('L2')
    expect(wrapper.findAll('[data-testid="evento-reciente"]')).toHaveLength(2)
    expect(wrapper.text()).toContain('EVENTO_L2')
    expect(wrapper.text()).toContain('EVENTO_L3')

    await wrapper.get('[data-testid="filtro-eventos"]').setValue('L1')
    expect(wrapper.findAll('[data-testid="evento-reciente"]')).toHaveLength(3)
    // WP-041: el orden visual es descendente por seq, así que el evento más
    // nuevo (L3, seq 3) encabeza la lista y el más antiguo (L1, seq 1) la cierra.
    expect(wrapper.findAll('[data-testid="nivel-evento"]').map((nodo) => nodo.text())).toEqual([
      'L3',
      'L2',
      'L1',
    ])
  })

  it('reemplaza por completo el listado cuando llega una baseline nueva', async () => {
    const wrapper = montar(PanelEventos, { estado: crearEstado() })
    await wrapper.setProps({
      estado: crearEstado({
        revision: 1,
        eventos_recientes: [
          {
            seq: 40,
            timestamp: '2026-08-27T11:00:00',
            nivel: 'L3',
            etiqueta: 'NUEVA',
            codigo_evento: 'BASELINE_NUEVA',
            mensaje: 'Reinicio confirmado',
          },
        ],
      }),
    })
    expect(wrapper.findAll('[data-testid="evento-reciente"]')).toHaveLength(1)
    expect(wrapper.text()).toContain('BASELINE_NUEVA')
    expect(wrapper.text()).not.toContain('EVENTO_L3')
  })
})

describe('Remapeo coordinado y persistencia explícita', () => {
  it('inicia desde banca/persona/devXX, bloquea doble submit y espera snapshot CAPTURANDO', async () => {
    let resolverInicio: (() => void) | undefined
    const iniciar = vi.fn(
      () =>
        new Promise<void>((resolver) => {
          resolverInicio = resolver
        }),
    )
    const estado = crearEstado()
    const wrapper = montar(GestionRemapeo, {
      estado,
      cliente: crearCliente({ iniciarRemapeo: iniciar as never }),
      conectado: true,
    })

    await wrapper.get('[data-testid="selector-banca-remapeo"]').setValue('dev02')
    expect(wrapper.get('[data-testid="resumen-inicio-remapeo"]').text()).toContain('Grace Hopper')
    expect(wrapper.get('[data-testid="resumen-inicio-remapeo"]').text()).toContain('dev02')
    await wrapper.get('[data-testid="btn-iniciar-remapeo"]').trigger('click')
    await wrapper.get('[data-testid="btn-iniciar-remapeo"]').trigger('click')
    expect(iniciar).toHaveBeenCalledTimes(1)
    expect(iniciar).toHaveBeenCalledWith('dev02')
    expect(wrapper.find('[data-testid="remapeo-activo"]').exists()).toBe(false)

    resolverInicio?.()
    await flushPromises()
    await wrapper.setProps({
      estado: crearEstado({
        revision: 11,
        remapeo: {
          remapeo_id: 'remapeo-1',
          dispositivo: 'dev02',
          estado: 'CAPTURANDO',
          fingerprint_anterior: 'fp-anterior',
          candidato: null,
          diagnostico: null,
        },
        capacidades: {
          ...estado.capacidades,
          iniciar_remapeo: { habilitada: false, motivos: ['REMAPEO_YA_ACTIVO'] },
          cancelar_remapeo: { habilitada: true, motivos: [] },
        },
      }),
    })
    expect(wrapper.get('[data-testid="estado-remapeo"]').text()).toBe('CAPTURANDO')
    expect(wrapper.get('[data-testid="persona-remapeo"]').text()).toContain('Grace Hopper')
    expect(wrapper.get('[data-testid="espera-captura-remapeo"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="inicio-remapeo"]').exists()).toBe(false)
  })

  it.each(['TEMPORAL', 'PERSISTENTE'] as const)(
    'confirma %s sin default, con resumen y usando el remapeo_id exacto',
    async (persistencia) => {
      let resolverConfirmacion: (() => void) | undefined
      const confirmar = vi.fn(
        () =>
          new Promise<void>((resolver) => {
            resolverConfirmacion = resolver
          }),
      )
      const estado = crearEstado()
      const candidato = crearEstado({
        remapeo: {
          remapeo_id: `remapeo-${persistencia}`,
          dispositivo: 'dev01',
          estado: 'CANDIDATO',
          fingerprint_anterior: 'fp-viejo',
          candidato: 'fp-nuevo',
          diagnostico: 'Teclado USB de reemplazo',
        },
        capacidades: {
          ...estado.capacidades,
          iniciar_remapeo: { habilitada: false, motivos: ['REMAPEO_YA_ACTIVO'] },
          confirmar_remapeo: { habilitada: true, motivos: [] },
          cancelar_remapeo: { habilitada: true, motivos: [] },
        },
      })
      const wrapper = montar(GestionRemapeo, {
        estado: candidato,
        cliente: crearCliente({ confirmarRemapeo: confirmar }),
        conectado: true,
      })

      const temporal = wrapper.get('[data-testid="persistencia-temporal"]')
      const persistente = wrapper.get('[data-testid="persistencia-persistente"]')
      expect((temporal.element as HTMLInputElement).checked).toBe(false)
      expect((persistente.element as HTMLInputElement).checked).toBe(false)
      expect(
        (wrapper.get('[data-testid="btn-confirmar-remapeo"]').element as HTMLButtonElement)
          .disabled,
      ).toBe(true)
      expect(wrapper.text()).toContain('fp-viejo')
      expect(wrapper.text()).toContain('fp-nuevo')
      expect(wrapper.text()).toContain('Teclado USB de reemplazo')

      await wrapper
        .get(`[data-testid="persistencia-${persistencia.toLowerCase()}"]`)
        .setValue(persistencia)
      expect(wrapper.get('[data-testid="resumen-confirmacion-remapeo"]').text()).toContain(
        persistencia,
      )
      await wrapper.get('[data-testid="btn-confirmar-remapeo"]').trigger('click')
      await wrapper.get('[data-testid="btn-confirmar-remapeo"]').trigger('click')
      expect(confirmar).toHaveBeenCalledTimes(1)
      expect(confirmar).toHaveBeenCalledWith(`remapeo-${persistencia}`, persistencia)
      expect(wrapper.find('[data-testid="remapeo-activo"]').exists()).toBe(true)

      resolverConfirmacion?.()
      await flushPromises()
    },
  )

  it('cancela por ID exacto, conserva estado ante error y reconstruye CONFIRMANDO', async () => {
    const cancelar = vi.fn().mockRejectedValue({ mensajeBackend: 'Bridge no disponible' })
    const base = crearEstado()
    const estadoCapturando = crearEstado({
      remapeo: {
        remapeo_id: 'remapeo-cancelar',
        dispositivo: 'dev03',
        estado: 'CAPTURANDO',
        fingerprint_anterior: 'fp-3',
        candidato: null,
        diagnostico: null,
      },
      capacidades: {
        ...base.capacidades,
        iniciar_remapeo: { habilitada: false, motivos: ['REMAPEO_YA_ACTIVO'] },
        cancelar_remapeo: { habilitada: true, motivos: [] },
      },
    })
    const wrapper = montar(GestionRemapeo, {
      estado: estadoCapturando,
      cliente: crearCliente({ cancelarRemapeo: cancelar }),
      conectado: true,
    })
    await wrapper.get('[data-testid="btn-cancelar-remapeo"]').trigger('click')
    await flushPromises()
    expect(cancelar).toHaveBeenCalledWith('remapeo-cancelar')
    expect(wrapper.get('[data-testid="error-remapeo"]').text()).toContain('Bridge no disponible')
    expect(wrapper.get('[data-testid="estado-remapeo"]').text()).toBe('CAPTURANDO')

    await wrapper.setProps({
      estado: crearEstado({
        revision: 12,
        remapeo: {
          remapeo_id: 'remapeo-confirmando',
          dispositivo: 'dev01',
          estado: 'CONFIRMANDO',
          fingerprint_anterior: 'fp-viejo',
          candidato: 'fp-nuevo',
          diagnostico: null,
        },
        capacidades: {
          ...base.capacidades,
          iniciar_remapeo: { habilitada: false, motivos: ['REMAPEO_YA_ACTIVO'] },
          confirmar_remapeo: { habilitada: false, motivos: ['REMAPEO_SIN_CANDIDATO'] },
          cancelar_remapeo: { habilitada: true, motivos: [] },
        },
      }),
    })
    expect(wrapper.get('[data-testid="confirmando-remapeo"]').exists()).toBe(true)
    expect(
      (wrapper.get('[data-testid="btn-cancelar-remapeo"]').element as HTMLButtonElement).disabled,
    ).toBe(true)
    expect(wrapper.find('[data-testid="btn-confirmar-remapeo"]').exists()).toBe(false)
  })
})

describe('Q3 horizontal, orador derivado y remapeo colapsable', () => {
  it('compone bancas a la izquierda, palabra a la derecha y deja controles fuera del scroll', () => {
    const wrapper = montar(PanelRecintoPalabra, {
      estado: crearEstado({ configuracion: { filas_bancas: [3] } }),
      cliente: crearCliente(),
      conectado: true,
    })

    const composicion = wrapper.get('[data-testid="composicion-recinto-palabra"]')
    expect(composicion.get('[data-testid="area-bancas-moderacion"]').exists()).toBe(true)
    expect(composicion.get('[data-testid="columna-palabra-moderacion"]').exists()).toBe(true)
    const scrollCola = wrapper.get('[data-testid="contenedor-scroll-cola-palabra"]')
    expect(scrollCola.find('[data-testid="btn-otorgar-palabra"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="controles-palabra"]').exists()).toBe(true)
  })

  it('mueve y limpia el resaltado cuando cambia la banca del orador', async () => {
    const estadoInicial = crearEstado({ configuracion: { filas_bancas: [3] } })
    const wrapper = montar(PanelRecintoPalabra, {
      estado: estadoInicial,
      cliente: crearCliente(),
      conectado: true,
    })

    // WP-045: el uso de la palabra ya no es un chip aparte sino el estado
    // principal de la tarjeta, con una única etiqueta textual.
    expect(wrapper.get('[data-banca="1"]').element.getAttribute('data-estado-banca')).toBe(
      'PALABRA',
    )
    expect(wrapper.get('[data-banca="1"] [data-testid="etiqueta-banca"]').text()).toBe(
      'En uso de la palabra',
    )
    expect(wrapper.get('[data-banca="2"]').element.getAttribute('data-estado-banca')).not.toBe(
      'PALABRA',
    )

    await wrapper.setProps({
      estado: crearEstado({
        revision: 11,
        configuracion: { filas_bancas: [3] },
        palabra: {
          orador: { dni: '2', nombre: 'Grace', apellido: 'Hopper', banca: 2 },
          cola: [],
        },
      }),
    })
    expect(wrapper.get('[data-banca="1"]').element.getAttribute('data-estado-banca')).not.toBe(
      'PALABRA',
    )
    expect(wrapper.get('[data-banca="2"]').element.getAttribute('data-estado-banca')).toBe(
      'PALABRA',
    )

    await wrapper.setProps({
      estado: crearEstado({
        revision: 12,
        configuracion: { filas_bancas: [3] },
        palabra: { orador: null, cola: [] },
      }),
    })
    expect(wrapper.find('[data-estado-banca="PALABRA"]').exists()).toBe(false)
  })

  it('abre y cierra el remapeo inactivo sin REST y fuerza la operación backend activa', async () => {
    const cliente = crearCliente()
    const estadoInicial = crearEstado({ configuracion: { filas_bancas: [3] } })
    const wrapper = montar(PanelRecintoPalabra, {
      estado: estadoInicial,
      cliente,
      conectado: true,
    })

    expect(wrapper.get('[data-testid="btn-desplegar-remapeo"]').text()).toContain(
      'Remapear dispositivo',
    )
    expect(wrapper.find('[data-testid="gestion-remapeo"]').exists()).toBe(false)
    await wrapper.get('[data-testid="btn-desplegar-remapeo"]').trigger('click')
    expect(wrapper.get('[data-testid="gestion-remapeo"]').exists()).toBe(true)
    await wrapper.get('[data-testid="btn-cerrar-remapeo"]').trigger('click')
    expect(wrapper.find('[data-testid="gestion-remapeo"]').exists()).toBe(false)
    expect(cliente.iniciarRemapeo).not.toHaveBeenCalled()
    expect(cliente.cancelarRemapeo).not.toHaveBeenCalled()

    await wrapper.setProps({
      estado: crearEstado({
        revision: 11,
        configuracion: { filas_bancas: [3] },
        remapeo: {
          remapeo_id: 'remapeo-activo',
          dispositivo: 'dev01',
          estado: 'CAPTURANDO',
          fingerprint_anterior: 'fp-anterior',
          candidato: null,
          diagnostico: null,
        },
      }),
    })
    expect(wrapper.get('[data-testid="gestion-remapeo"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="btn-cerrar-remapeo"]').exists()).toBe(false)

    await wrapper.setProps({
      estado: crearEstado({ revision: 12, configuracion: { filas_bancas: [3] }, remapeo: null }),
    })
    expect(wrapper.find('[data-testid="gestion-remapeo"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="btn-desplegar-remapeo"]').exists()).toBe(true)
  })
})
