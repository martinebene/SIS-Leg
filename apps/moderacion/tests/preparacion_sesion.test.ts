/**
 * Pruebas unitarias e interactivas completas para los componentes y flujos de WP-022:
 * UI de preparación, presencia, autoridades, sesión y advertencia de cierre.
 *
 * Cobertura obligatoria:
 * 1. H1 — Gestión de borradores locales (draft/dirty) ante snapshots SSE y transiciones institucionales.
 * 2. H2 — Pruebas interactivas con componentes reales montados ejercitando estado reactivo y llamadas a métodos de API.
 * 3. H4 — Modalidad accesible, atajo Escape y gestión de foco en DialogoConfirmacionCierre.
 * 4. WP-036 — Ausencia de todo resumen global de quórum en Q1 y Q3: ese dato vive sólo en la cabecera.
 * 5. M3 — Validación estricta del número de sesión (enteros positivos > 0 sin truncado ni conversión silenciosa).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { compile, createSSRApp, h, nextTick, type Component, ssrContextKey } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { mount, flushPromises, type MountingOptions, type VueWrapper } from '@vue/test-utils'
import PanelSesionVotacion from '../app/components/PanelSesionVotacion.vue'
import fuentePanelSesionVotacion from '../app/components/PanelSesionVotacion.vue?raw'
import PanelContenedor from '../app/components/PanelContenedor.vue'
import fuentePanelContenedor from '../app/components/PanelContenedor.vue?raw'
import PanelRecintoPalabra from '../app/components/PanelRecintoPalabra.vue'
import BancaConcejal from '../app/components/BancaConcejal.vue'
import fuenteBancaConcejal from '../app/components/BancaConcejal.vue?raw'
import GrillaRecinto from '../app/components/GrillaRecinto.vue'
import fuenteGrillaRecinto from '../app/components/GrillaRecinto.vue?raw'
import DialogoConfirmacionCierre from '../app/components/DialogoConfirmacionCierre.vue'
import fuenteDialogoConfirmacionCierre from '../app/components/DialogoConfirmacionCierre.vue?raw'
import DialogoEdicionAutoridades from '../app/components/DialogoEdicionAutoridades.vue'
import fuenteDialogoEdicionAutoridades from '../app/components/DialogoEdicionAutoridades.vue?raw'
import { resolverRutaAsset } from '../app/utils/rutas'
import { traducirMotivo, traducirMotivos } from '../app/utils/motivos'
import { reiniciarInstanciaCompartidaParaPruebas } from '../app/composables/useEstadoModeracion'
import type {
  EstadoModeracion,
  ClienteModeracion,
  ConcejalModeracion,
  EstadoQuorum,
  OpcionesSuscripcion,
} from '@sis-leg/api-client'

/**
 * Vitest ejecuta este repositorio en entorno Node para conservar la infraestructura liviana.
 * En ese modo el plugin de Vue entrega ssrRender, suficiente para los tests históricos de SSR,
 * pero @vue/test-utils necesita render de cliente para crear nodos e interactuar con ellos.
 *
 * Este helper compila la plantilla exacta del componente productivo importada con ?raw y la
 * adjunta al mismo componente cuyo setup se prueba. No replica lógica, handlers ni condiciones:
 * solo cubre la frontera de compilación que normalmente aporta un navegador/jsdom.
 */
function habilitarRenderCliente(
  componente: Component,
  fuente: string,
  componentesLocales: Record<string, Component> = {},
): void {
  const coincidencia = fuente.match(/<template>([\s\S]*)<\/template>/)
  if (!coincidencia?.[1]) {
    throw new Error('No se encontró la plantilla Vue que debe compilarse para la prueba')
  }

  const componenteCompilable = componente as {
    render?: ReturnType<typeof compile>
    components?: Record<string, Component>
    setup?: (props: unknown, contexto: unknown) => unknown
  }
  const setupOriginal = componenteCompilable.setup
  if (setupOriginal) {
    componenteCompilable.setup = (props, contexto) => {
      const resultado = setupOriginal(props, contexto)
      if (typeof resultado === 'object' && resultado !== null) {
        // El compilador SFC usa esta marca cuando la plantilla accede a $setup directamente.
        // Al compilar la plantilla en runtime, retirarla habilita el acceso equivalente por _ctx.
        return { ...resultado }
      }
      return resultado
    }
  }
  componenteCompilable.render = compile(coincidencia[1], { hoistStatic: false })
  componenteCompilable.components = {
    ...componenteCompilable.components,
    ...componentesLocales,
  }
}

habilitarRenderCliente(PanelContenedor, fuentePanelContenedor)
habilitarRenderCliente(DialogoConfirmacionCierre, fuenteDialogoConfirmacionCierre)
habilitarRenderCliente(DialogoEdicionAutoridades, fuenteDialogoEdicionAutoridades)
habilitarRenderCliente(BancaConcejal, fuenteBancaConcejal)
habilitarRenderCliente(GrillaRecinto, fuenteGrillaRecinto, { BancaConcejal })
habilitarRenderCliente(PanelSesionVotacion, fuentePanelSesionVotacion, {
  PanelContenedor,
  DialogoConfirmacionCierre,
  DialogoEdicionAutoridades,
})

async function renderizarSSR(
  componente: Component,
  props: Record<string, unknown> = {},
  slots: Record<string, () => unknown> = {},
) {
  const app = createSSRApp({
    render() {
      return h(componente, props, slots)
    },
  })
  return renderToString(app)
}

function crearMockCliente(overrides: Partial<ClienteModeracion> = {}): ClienteModeracion {
  return {
    prepararSala: vi.fn().mockResolvedValue(undefined),
    actualizarPreparacion: vi.fn().mockResolvedValue(undefined),
    cancelarPreparacion: vi.fn().mockResolvedValue(undefined),
    abrirSesion: vi.fn().mockResolvedValue(undefined),
    actualizarSesion: vi.fn().mockResolvedValue(undefined),
    // WP-085: el cierre responde con el resultado del acta y de la copia externa.
    // Sin `logs_copy_dir` configurado el desenlace es acta generada y copia omitida,
    // que es el caso que estas pruebas ejercitan.
    cerrarSesion: vi.fn().mockResolvedValue({ acta_generada: true, copia_externa: 'OMITIDA' }),
    otorgarPalabra: vi.fn().mockResolvedValue(undefined),
    quitarPalabra: vi.fn().mockResolvedValue(undefined),
    suscribirEstado: vi.fn((callbacks) => {
      callbacks?.alCambiarConexion?.(true)
      return {
        cancelar: vi.fn(),
        activa: true,
      }
    }),
    obtenerEstado: vi.fn().mockResolvedValue(crearEstadoBase()),
    ...overrides,
  } as unknown as ClienteModeracion
}

function montarComponente<T extends Component>(
  componente: T,
  options: MountingOptions<Record<string, unknown>> = {},
) {
  const ssrContext = { modules: new Set() }
  return mount(componente, {
    ...options,
    global: {
      ...options.global,
      provide: {
        [ssrContextKey]: ssrContext,
        ...options.global?.provide,
      },
    },
  })
}

/**
 * Conserva las referencias a los componentes montados para desmontarlos al finalizar cada prueba.
 * Así cada caso libera su consumidor de useEstadoModeracion y no comparte una conexión reactiva
 * accidentalmente con el caso siguiente.
 */
const wrappersMontados: VueWrapper[] = []

function montarComponenteAislado<T extends Component>(
  componente: T,
  options: MountingOptions<Record<string, unknown>> = {},
) {
  const wrapper = montarComponente(componente, options)
  wrappersMontados.push(wrapper)
  return wrapper
}

function crearConcejalesPrueba(cantidad = 12): ConcejalModeracion[] {
  return Array.from({ length: cantidad }, (_, i) => {
    const banca = i + 1
    const pad = String(banca).padStart(2, '0')
    return {
      banca,
      dni: `300000${pad}`,
      nombre: `Concejal${pad}`,
      apellido: `Apellido${pad}`,
      nombre_mostrar: `C. Apellido${pad}`,
      bloque: banca % 2 === 0 ? 'Frente de Todos' : 'Juntos por el Cambio',
      ruta_imagen: `assets/bancas/banca-${pad}.png`,
      dispositivo_votacion: `dev${pad}`,
      presente: banca <= 8,
      test_activo: banca === 1,
      test_expira_en: banca === 1 ? '2026-08-25T10:00:05Z' : null,
    }
  })
}

function crearEstadoBase(parcial: Partial<EstadoModeracion> = {}): EstadoModeracion {
  return {
    instancia: 'instancia-prueba',
    revision: 1,
    generado_en: '2026-08-25T10:00:00Z',
    estado_global: 'SIN_PREPARAR',
    preparacion: null,
    sesion: null,
    votacion: null,
    palabra: {
      orador: null,
      cola: [],
    },
    quorum: null,
    configuracion: {
      filas_bancas: [3, 4, 5],
    },
    concejales: crearConcejalesPrueba(12),
    capacidades: {
      preparar_sala: { habilitada: true, motivos: [] },
      actualizar_preparacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      cancelar_preparacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      abrir_sesion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      actualizar_sesion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      cerrar_sesion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      iniciar_votacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      cancelar_votacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      cerrar_votacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      desempatar: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      solicitar_palabra: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      cancelar_solicitud_palabra: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      otorgar_palabra: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      quitar_palabra: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      iniciar_remapeo: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      confirmar_remapeo: { habilitada: false, motivos: ['REMAPEO_NO_COINCIDE'] },
      cancelar_remapeo: { habilitada: false, motivos: ['REMAPEO_NO_COINCIDE'] },
      subir_orden_dia: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      seleccionar_expediente: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      cerrar_expediente: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      registrar_evento_manual: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
    },
    ...parcial,
  }
}

describe('WP-022: Preparación, presencia, autoridades, sesión y advertencia de cierre', () => {
  beforeEach(() => {
    reiniciarInstanciaCompartidaParaPruebas()
  })

  afterEach(() => {
    while (wrappersMontados.length > 0) {
      wrappersMontados.pop()?.unmount()
    }
    document.body.textContent = ''
  })

  // ===========================================================================
  // 1. ESTADO SIN_PREPARAR (SSR Y COMPONENTES)
  // ===========================================================================
  describe('1. Estado SIN_PREPARAR', () => {
    it('muestra vista de recinto sin preparar con botón de Preparar recinto y sin resumen de quórum en Q3', async () => {
      const estado = crearEstadoBase({ estado_global: 'SIN_PREPARAR', quorum: null })
      const htmlSesion = await renderizarSSR(PanelSesionVotacion, { estado })

      expect(htmlSesion).toContain('data-testid="vista-sin-preparar"')
      expect(htmlSesion).toContain('Recinto sin preparar')
      expect(htmlSesion).toContain('data-testid="btn-preparar-sala"')
      expect(htmlSesion).not.toContain('data-testid="vista-preparando"')
      expect(htmlSesion).not.toContain('data-testid="vista-sesion-abierta"')

      const htmlRecinto = await renderizarSSR(PanelRecintoPalabra, { estado })
      // WP-036: Q3 ya no presenta ningún resumen de quórum ni conteo global de presentes.
      expect(htmlRecinto).not.toContain('data-testid="indicador-quorum"')
      expect(htmlRecinto).not.toContain('presentes')
    })
  })

  // ===========================================================================
  // 2. ESTADO PREPARANDO (SSR Y ESTRUCTURA)
  // ===========================================================================
  describe('2. Estado PREPARANDO (Estructura)', () => {
    function crearEstadoPreparando(parcial: Partial<EstadoModeracion> = {}): EstadoModeracion {
      return crearEstadoBase({
        estado_global: 'PREPARANDO',
        preparacion: {
          fecha_hora_inicio: '2026-08-25T10:00:00Z',
          numero_sesion: 42,
          presidencia: 'Dr. René Favaloro',
          secretaria_legislativa: 'Lic. Alicia Moreau',
        },
        capacidades: {
          ...crearEstadoBase().capacidades,
          preparar_sala: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
          actualizar_preparacion: { habilitada: true, motivos: [] },
          cancelar_preparacion: { habilitada: true, motivos: [] },
          abrir_sesion: { habilitada: false, motivos: ['QUORUM_INSUFICIENTE'] },
        },
        ...parcial,
      })
    }

    it('renderiza inputs de sesión y motivos de bloqueo si abrir_sesion está deshabilitada', async () => {
      const estado = crearEstadoPreparando()
      const html = await renderizarSSR(PanelSesionVotacion, { estado })

      expect(html).toContain('data-testid="vista-preparando"')
      expect(html).toContain('data-testid="input-numero-sesion"')
      expect(html).toContain('data-testid="input-presidencia"')
      expect(html).toContain('data-testid="input-secretaria"')
      expect(html).toContain('data-testid="btn-guardar-preparacion"')
      expect(html).toContain('data-testid="btn-abrir-sesion"')
      expect(html).toContain('data-testid="btn-cancelar-preparacion"')
      expect(html).toContain('data-testid="motivos-abrir-sesion"')
      expect(html).toContain('Quórum insuficiente')
    })
  })

  // ===========================================================================
  // 3. RECINTO, BANCAS, FOTOS Y QUÓRUM (M1, M2)
  // ===========================================================================
  describe('3. Recinto, Bancas y Quórum', () => {
    it('BancaConcejal: renderiza identidad, foto con fallback, presencia solo lectura y señal de test', async () => {
      const concejal: ConcejalModeracion = {
        banca: 3,
        dni: '30123456',
        nombre: 'Florentina',
        apellido: 'Gómez Miranda',
        nombre_mostrar: 'F. Gómez Miranda',
        bloque: 'UCR',
        ruta_imagen: 'assets/bancas/banca-03.png',
        dispositivo_votacion: 'dev03',
        presente: true,
        test_activo: true,
        test_expira_en: '2026-08-25T10:00:05Z',
      }

      const html = await renderizarSSR(BancaConcejal, { concejal })

      // WP-045: la tarjeta muestra el bitmap y, como máximo, una etiqueta. La
      // identidad ya vive dentro de la propia imagen, de modo que nombre,
      // bloque, dispositivo y número de banca no se repiten como texto visible.
      expect(html).toContain('data-banca="3"')
      expect(html).toContain('assets/bancas/banca-03.png')
      expect(html).toContain('aria-label="Banca 3, Florentina Gómez Miranda, presente')
      expect(html).not.toContain('>UCR<')
      expect(html).not.toContain('dev03')
      expect(html).not.toContain('Presente')
      // El test de dispositivo es el estado principal y se pinta sin etiqueta.
      expect(html).toContain('data-estado-banca="TEST"')
      expect(html).not.toContain('data-testid="etiqueta-banca"')
    })

    it('GrillaRecinto: dibuja [3,4,5] desde arriba sin invertir el orden horizontal', () => {
      const concejales = crearConcejalesPrueba(12)
      const wrapper = montarComponenteAislado(GrillaRecinto, {
        props: { concejales: concejales.reverse(), filasBancas: [3, 4, 5] },
      })

      // El primer nodo visual es la fila física superior, pero cada fila mantiene
      // sus bancas crecientes de izquierda a derecha.
      // WP-045 quitó el texto `Banca N` de la tarjeta: la posición física se
      // comprueba ahora con el atributo `data-banca`, que sigue siendo autoritativo.
      const bancasDeFila = (fila: number): (string | undefined)[] =>
        wrapper
          .get(`[data-fila-fisica="${fila}"]`)
          .findAll('[data-banca]')
          .map((banca) => banca.element.getAttribute('data-banca'))

      const filas = wrapper.findAll('[data-fila-fisica]')
      expect(filas).toHaveLength(3)
      expect(filas[0]?.element.getAttribute('data-fila-fisica')).toBe('3')
      expect(filas[1]?.element.getAttribute('data-fila-fisica')).toBe('2')
      expect(filas[2]?.element.getAttribute('data-fila-fisica')).toBe('1')
      expect(bancasDeFila(1)).toEqual(['1', '2', '3'])
      expect(bancasDeFila(2)).toEqual(['4', '5', '6', '7'])
      expect(bancasDeFila(3)).toEqual(['8', '9', '10', '11', '12'])
    })

    it('GrillaRecinto: soporta [5,7], asociación desordenada y hueco físico', () => {
      const concejales = crearConcejalesPrueba(12)
        .filter((concejal) => concejal.banca !== 4)
        .sort((primero, segundo) => segundo.banca - primero.banca)
      const wrapper = montarComponenteAislado(GrillaRecinto, {
        props: { concejales, filasBancas: [5, 7] },
      })

      const bancasDeFila = (fila: number): (string | undefined)[] =>
        wrapper
          .get(`[data-fila-fisica="${fila}"]`)
          .findAll('[data-banca]')
          .map((banca) => banca.element.getAttribute('data-banca'))

      expect(bancasDeFila(2)).toEqual(['6', '7', '8', '9', '10', '11', '12'])
      expect(bancasDeFila(1)).toEqual(['1', '2', '3', '4', '5'])
      expect(wrapper.get('[data-banca="4"]').text()).toContain('sin datos')
      // La identidad ya no es texto visible, pero sigue disponible para accesibilidad.
      expect(wrapper.get('[data-banca="5"]').element.getAttribute('aria-label')).toContain(
        'Concejal05',
      )
    })

    it('BancaConcejal: ausencia, fallback y baseline nueva no mutan presencia', async () => {
      const concejalAusente = {
        ...crearConcejalesPrueba(1)[0]!,
        presente: false,
        test_activo: true,
      }
      const wrapper = montarComponenteAislado(BancaConcejal, {
        props: { concejal: concejalAusente },
      })

      // Test activo tiene mayor prioridad que la ausencia: el estado principal es
      // TEST (sin etiqueta) y la ausencia sobrevive como halo secundario.
      const tarjeta = wrapper.get('[data-testid="banca-concejal"]')
      expect(tarjeta.element.getAttribute('data-estado-banca')).toBe('TEST')
      expect(tarjeta.element.getAttribute('data-presente')).toBe('false')
      expect(wrapper.find('[data-testid="etiqueta-banca"]').exists()).toBe(false)
      expect(tarjeta.element.getAttribute('aria-label')).toContain(
        'ausente, test de dispositivo activo',
      )
      expect(wrapper.text()).not.toContain('Test de teclado')
      expect(wrapper.text()).not.toContain('dev01')
      expect(wrapper.findAll('button, input, select, textarea')).toHaveLength(0)

      await wrapper.get('[data-testid="imagen-concejal"]').trigger('error')
      expect(wrapper.get('[data-testid="fallback-imagen"]').text()).toBe('CA')

      const concejalNuevo = {
        ...concejalAusente,
        dni: '39999999',
        nombre: 'Nueva',
        apellido: 'Persona',
        ruta_imagen: 'assets/bancas/persona-nueva.png',
        presente: true,
        test_activo: false,
      }
      await wrapper.setProps({ concejal: concejalNuevo })
      await nextTick()

      expect(wrapper.find('[data-ruta-imagen="assets/bancas/persona-nueva.png"]').exists()).toBe(
        true,
      )
      expect(
        wrapper.get('[data-testid="banca-concejal"]').element.getAttribute('data-estado-banca'),
      ).toBe('NORMAL')
      expect(wrapper.find('[data-testid="etiqueta-banca"]').exists()).toBe(false)
      const htmlPresente = await renderizarSSR(BancaConcejal, { concejal: concejalNuevo })
      expect(htmlPresente).toContain('data-estado-banca="NORMAL"')
      expect(concejalAusente.presente).toBe(false)
    })

    it('Q3 no repite el quórum global ni siquiera cuando el backend lo proyecta', async () => {
      // WP-036: aunque exista contexto de quórum, el cuadrante de Recinto no lo presenta;
      // la única sede de ese dato global es la cabecera compacta del shell.
      const quorumFaltante: EstadoQuorum = {
        cantidad_presentes: 5,
        requerido: 7,
        alcanzado: false,
      }
      const html = await renderizarSSR(PanelRecintoPalabra, {
        estado: crearEstadoBase({ estado_global: 'PREPARANDO', quorum: quorumFaltante }),
      })

      expect(html).toContain('data-testid="panel-recinto-palabra"')
      expect(html).not.toContain('data-testid="indicador-quorum"')
      expect(html).not.toContain('data-testid="quorum-faltantes"')
      expect(html).not.toContain('data-testid="quorum-completo"')
      expect(html).not.toContain('Falta quórum')
      expect(html).not.toContain('presentes')
      // Las bancas individuales conservan su propia señal de presencia física.
      expect(html).toContain('data-testid="grilla-recinto"')
    })
  })

  // ===========================================================================
  // 4. SESION_ABIERTA Y AUTORIDADES (SSR Y M1)
  // ===========================================================================
  describe('4. Estado SESION_ABIERTA (Estructura y M1)', () => {
    it('opera desde el encabezado, sin franja de número ni inputs permanentes ni quórum repetido', async () => {
      const estado = crearEstadoBase({
        estado_global: 'SESION_ABIERTA',
        sesion: {
          fecha_hora_inicio_preparacion: '2026-08-25T10:00:00Z',
          fecha_hora_apertura: '2026-08-25T10:30:00Z',
          numero_sesion: 8,
          presidencia: 'Dra. María Elena Walsh',
          secretaria_legislativa: 'Lic. Juan Gómez',
        },
        quorum: {
          cantidad_presentes: 9,
          requerido: 7,
          alcanzado: true,
        },
        capacidades: {
          ...crearEstadoBase().capacidades,
          actualizar_sesion: { habilitada: true, motivos: [] },
          cerrar_sesion: { habilitada: true, motivos: [] },
        },
      })

      const html = await renderizarSSR(PanelSesionVotacion, { estado })

      expect(html).toContain('data-testid="vista-sesion-abierta"')
      // WP-036: Q1 ya no repite el resumen global de quórum.
      expect(html).not.toContain('data-testid="quorum-resumen-sesion"')
      expect(html).not.toContain('data-testid="badge-quorum-resumen-sesion"')
      expect(html).not.toContain('Quórum legal')
      expect(html).not.toContain('9 / 7 presentes')
      // WP-048: el número de sesión es un dato único de la cabecera global del shell.
      // Q1 ya no reserva una franja interior para repetirlo.
      expect(html).not.toContain('data-testid="franja-sesion-abierta"')
      expect(html).not.toContain('data-testid="numero-sesion-inmutable"')
      expect(html).not.toContain('Sesión Nº 8')
      expect(html).not.toContain('data-testid="input-presidencia-sesion"')
      expect(html).not.toContain('data-testid="input-secretaria-sesion"')
      // Las dos acciones institucionales siguen existiendo, ahora en el encabezado.
      expect(html).toContain('data-testid="btn-editar-autoridades"')
      expect(html).toContain('data-testid="btn-cerrar-sesion"')
      // El badge de estado del recinto permanece en Q1: es su única sede visible tras WP-047.
      expect(html).toContain('Sesión activa')
    })
  })

  // ===========================================================================
  // 5. PRUEBAS INTERACTIVAS CON COMPONENTES REALES MONTADOS (H2, N2 Y R1)
  // ===========================================================================
  describe('5. Interacción real con PanelSesionVotacion (H2, N2 y R1)', () => {
    /**
     * Construye una preparación confirmada y permite variar únicamente los datos relevantes
     * para cada interacción. Las reglas bajo prueba permanecen en el componente productivo.
     */
    function crearEstadoPreparando(parcial: Partial<EstadoModeracion> = {}): EstadoModeracion {
      return crearEstadoBase({
        estado_global: 'PREPARANDO',
        preparacion: {
          fecha_hora_inicio: '2026-08-25T10:00:00Z',
          numero_sesion: 10,
          presidencia: 'Dra. Original',
          secretaria_legislativa: 'Lic. Original',
        },
        capacidades: {
          ...crearEstadoBase().capacidades,
          actualizar_preparacion: { habilitada: true, motivos: [] },
          cancelar_preparacion: { habilitada: true, motivos: [] },
          abrir_sesion: { habilitada: true, motivos: [] },
        },
        ...parcial,
      })
    }

    /**
     * Construye una sesión abierta apta para probar autoridades y cierre.
     */
    function crearEstadoSesionAbierta(parcial: Partial<EstadoModeracion> = {}): EstadoModeracion {
      return crearEstadoBase({
        estado_global: 'SESION_ABIERTA',
        sesion: {
          fecha_hora_inicio_preparacion: '2026-08-25T10:00:00Z',
          fecha_hora_apertura: '2026-08-25T10:30:00Z',
          numero_sesion: 42,
          presidencia: 'Dr. Inicial',
          secretaria_legislativa: 'Lic. Inicial',
        },
        capacidades: {
          ...crearEstadoBase().capacidades,
          actualizar_sesion: { habilitada: true, motivos: [] },
          cerrar_sesion: { habilitada: true, motivos: [] },
        },
        ...parcial,
      })
    }

    /**
     * Expone los callbacks reales entregados por useEstadoModeracion al cliente mock.
     * Los tests cambian la conexión exclusivamente por esta frontera, del mismo modo que
     * lo hace el sincronizador compartido cuando abre o pierde el stream SSE.
     */
    function crearClienteConConexionControlable() {
      let callbacks: OpcionesSuscripcion<EstadoModeracion> | null = null
      const cliente = crearMockCliente({
        suscribirEstado: vi.fn((nuevosCallbacks) => {
          callbacks = nuevosCallbacks
          return { cancelar: vi.fn(), activa: true }
        }),
      })

      return {
        cliente,
        callbacks() {
          if (!callbacks) {
            throw new Error('El panel todavía no inició la suscripción compartida')
          }
          return callbacks
        },
      }
    }

    it('N2.A — SIN_PREPARAR prepara el recinto mediante un click real cuando está CONECTADO', async () => {
      const mockCliente = crearMockCliente()
      const estado = crearEstadoBase({
        estado_global: 'SIN_PREPARAR',
        capacidades: {
          ...crearEstadoBase().capacidades,
          preparar_sala: { habilitada: true, motivos: [] },
        },
      })
      const wrapper = montarComponenteAislado(PanelSesionVotacion, {
        props: { estado, clienteInyectado: mockCliente },
      })
      const botonPreparar = wrapper.get<HTMLButtonElement>('[data-testid="btn-preparar-sala"]')

      expect(botonPreparar.exists()).toBe(true)
      expect(botonPreparar.element.disabled).toBe(false)

      await botonPreparar.trigger('click')
      await flushPromises()

      expect(mockCliente.prepararSala).toHaveBeenCalledTimes(1)
    })

    it('N2.B — RECONECTANDO conserva el estado, bloquea la mutación y se recupera por callbacks reales', async () => {
      const control = crearClienteConConexionControlable()
      const estado = crearEstadoBase({
        estado_global: 'SIN_PREPARAR',
        capacidades: {
          ...crearEstadoBase().capacidades,
          preparar_sala: { habilitada: true, motivos: [] },
        },
      })
      const wrapper = montarComponenteAislado(PanelSesionVotacion, {
        props: { estado, clienteInyectado: control.cliente },
      })
      const callbacks = control.callbacks()
      const botonPreparar = wrapper.get<HTMLButtonElement>('[data-testid="btn-preparar-sala"]')

      callbacks.alEstado(estado)
      callbacks.alCambiarConexion?.(true)
      await nextTick()
      expect(wrapper.vm.sincronizacion.estadoConexion.value).toBe('CONECTADO')
      expect(botonPreparar.element.disabled).toBe(false)

      callbacks.alCambiarConexion?.(false)
      await nextTick()
      expect(wrapper.vm.sincronizacion.estadoConexion.value).toBe('RECONECTANDO')
      expect(wrapper.get('[data-testid="vista-sin-preparar"]').text()).toContain(
        'Recinto sin preparar',
      )
      expect(botonPreparar.element.disabled).toBe(true)

      await botonPreparar.trigger('click')
      expect(control.cliente.prepararSala).not.toHaveBeenCalled()

      callbacks.alCambiarConexion?.(true)
      callbacks.alEstado({ ...estado, revision: 2 })
      await nextTick()
      expect(wrapper.vm.sincronizacion.estadoConexion.value).toBe('CONECTADO')
      expect(botonPreparar.element.disabled).toBe(false)

      await botonPreparar.trigger('click')
      await flushPromises()
      expect(control.cliente.prepararSala).toHaveBeenCalledTimes(1)
    })

    it('N2.B — DESCONECTADO bloquea una capacidad habilitada sin falsear capacidades', async () => {
      const control = crearClienteConConexionControlable()
      const estado = crearEstadoBase({
        estado_global: 'SIN_PREPARAR',
        capacidades: {
          ...crearEstadoBase().capacidades,
          preparar_sala: { habilitada: true, motivos: [] },
        },
      })
      const wrapper = montarComponenteAislado(PanelSesionVotacion, {
        props: { estado, clienteInyectado: control.cliente },
      })
      const botonPreparar = wrapper.get<HTMLButtonElement>('[data-testid="btn-preparar-sala"]')

      control.callbacks().alCambiarConexion?.(false)
      await nextTick()

      expect(wrapper.vm.sincronizacion.estadoConexion.value).toBe('DESCONECTADO')
      expect(estado.capacidades.preparar_sala.habilitada).toBe(true)
      expect(botonPreparar.element.disabled).toBe(true)

      await botonPreparar.trigger('click')
      expect(control.cliente.prepararSala).not.toHaveBeenCalled()
    })

    it('muestra por DOM el error de prepararSala y conserva el estado confirmado', async () => {
      const mockCliente = crearMockCliente({
        prepararSala: vi.fn().mockRejectedValue({ mensaje: 'Error de auditoría L1' }),
      })
      const estado = crearEstadoBase()
      const wrapper = montarComponenteAislado(PanelSesionVotacion, {
        props: { estado, clienteInyectado: mockCliente },
      })

      await wrapper.get('[data-testid="btn-preparar-sala"]').trigger('click')
      await flushPromises()

      expect(wrapper.get('[data-testid="alerta-error-comando"]').text()).toContain(
        'Error de auditoría L1',
      )
      expect(wrapper.get('[data-testid="vista-sin-preparar"]').exists()).toBe(true)
    })

    it('N2.C/H1 — setValue activa dirty, preserva el draft ante snapshot ajeno y lo confirma', async () => {
      const mockCliente = crearMockCliente()
      const estadoInicial = crearEstadoPreparando()
      const wrapper = montarComponenteAislado(PanelSesionVotacion, {
        props: { estado: estadoInicial, clienteInyectado: mockCliente },
      })
      const numero = wrapper.get<HTMLInputElement>('[data-testid="input-numero-sesion"]')
      const presidencia = wrapper.get<HTMLInputElement>('[data-testid="input-presidencia"]')
      const secretaria = wrapper.get<HTMLInputElement>('[data-testid="input-secretaria"]')

      await numero.setValue('27')
      await presidencia.setValue('Dra. Edición local')

      expect(numero.element.value).toBe('27')
      expect(presidencia.element.value).toBe('Dra. Edición local')
      expect(wrapper.vm.numeroSesionDirty).toBe(true)
      expect(wrapper.vm.presidenciaDirty).toBe(true)

      const snapshotAjeno = crearEstadoPreparando({
        revision: 2,
        preparacion: {
          fecha_hora_inicio: '2026-08-25T10:00:00Z',
          numero_sesion: 11,
          presidencia: 'Dra. Original',
          secretaria_legislativa: 'Lic. Actualizada por backend',
        },
      })
      await wrapper.setProps({ estado: snapshotAjeno })

      expect(numero.element.value).toBe('27')
      expect(presidencia.element.value).toBe('Dra. Edición local')
      expect(secretaria.element.value).toBe('Lic. Actualizada por backend')

      await wrapper.get('[data-testid="btn-guardar-preparacion"]').trigger('click')
      await flushPromises()

      expect(mockCliente.actualizarPreparacion).toHaveBeenCalledWith({
        numero_sesion: 27,
        presidencia: 'Dra. Edición local',
        secretaria_legislativa: 'Lic. Actualizada por backend',
      })

      const snapshotConfirmatorio = crearEstadoPreparando({
        revision: 3,
        preparacion: {
          fecha_hora_inicio: '2026-08-25T10:00:00Z',
          numero_sesion: 27,
          presidencia: 'Dra. Edición local',
          secretaria_legislativa: 'Lic. Actualizada por backend',
        },
      })
      await wrapper.setProps({ estado: snapshotConfirmatorio })

      expect(numero.element.value).toBe('27')
      expect(presidencia.element.value).toBe('Dra. Edición local')
      expect(wrapper.vm.numeroSesionDirty).toBe(false)
      expect(wrapper.vm.presidenciaDirty).toBe(false)
    })

    it('N2.D — permite limpiar autoridades con inputs y guardar strings vacíos', async () => {
      const mockCliente = crearMockCliente()
      const wrapper = montarComponenteAislado(PanelSesionVotacion, {
        props: { estado: crearEstadoPreparando(), clienteInyectado: mockCliente },
      })

      await wrapper.get('[data-testid="input-presidencia"]').setValue('')
      await wrapper.get('[data-testid="input-secretaria"]').setValue('')
      await wrapper.get('[data-testid="btn-guardar-preparacion"]').trigger('click')
      await flushPromises()

      expect(mockCliente.actualizarPreparacion).toHaveBeenCalledWith({
        numero_sesion: 10,
        presidencia: '',
        secretaria_legislativa: '',
      })
    })

    it('N2.E/M3 — valida mediante input y botón los casos 12, 1, 0, -3, 12.5 y vacío', async () => {
      const mockCliente = crearMockCliente()
      const wrapper = montarComponenteAislado(PanelSesionVotacion, {
        props: {
          estado: crearEstadoPreparando({
            preparacion: {
              fecha_hora_inicio: '2026-08-25T10:00:00Z',
              numero_sesion: null,
              presidencia: 'Dr. A',
              secretaria_legislativa: 'Lic. B',
            },
          }),
          clienteInyectado: mockCliente,
        },
      })
      const numero = wrapper.get('[data-testid="input-numero-sesion"]')
      const guardar = wrapper.get('[data-testid="btn-guardar-preparacion"]')

      for (const valorInvalido of ['0', '-3', '12.5']) {
        vi.mocked(mockCliente.actualizarPreparacion).mockClear()
        await numero.setValue(valorInvalido)
        await guardar.trigger('click')
        await flushPromises()

        expect(mockCliente.actualizarPreparacion).not.toHaveBeenCalled()
        expect(wrapper.get('[data-testid="alerta-error-comando"]').text()).toContain(
          'número entero positivo mayor a cero',
        )
      }

      for (const valorValido of ['12', '1']) {
        vi.mocked(mockCliente.actualizarPreparacion).mockClear()
        await numero.setValue(valorValido)
        await guardar.trigger('click')
        await flushPromises()

        expect(mockCliente.actualizarPreparacion).toHaveBeenCalledWith({
          numero_sesion: Number(valorValido),
          presidencia: 'Dr. A',
          secretaria_legislativa: 'Lic. B',
        })
      }

      vi.mocked(mockCliente.actualizarPreparacion).mockClear()
      await numero.setValue('')
      await guardar.trigger('click')
      await flushPromises()

      expect(mockCliente.actualizarPreparacion).toHaveBeenCalledWith({
        presidencia: 'Dr. A',
        secretaria_legislativa: 'Lic. B',
      })
    })

    it('N2.F — abre y cancela preparación por click, y capacidades deshabilitadas impiden llamadas', async () => {
      const mockCliente = crearMockCliente()
      const wrapper = montarComponenteAislado(PanelSesionVotacion, {
        props: { estado: crearEstadoPreparando(), clienteInyectado: mockCliente },
      })
      const botonAbrir = wrapper.get<HTMLButtonElement>('[data-testid="btn-abrir-sesion"]')
      const botonCancelar = wrapper.get<HTMLButtonElement>(
        '[data-testid="btn-cancelar-preparacion"]',
      )

      await botonAbrir.trigger('click')
      await flushPromises()
      await botonCancelar.trigger('click')
      await flushPromises()

      expect(mockCliente.abrirSesion).toHaveBeenCalledTimes(1)
      expect(mockCliente.cancelarPreparacion).toHaveBeenCalledTimes(1)

      await wrapper.setProps({
        estado: crearEstadoPreparando({
          capacidades: {
            ...crearEstadoBase().capacidades,
            actualizar_preparacion: { habilitada: true, motivos: [] },
            abrir_sesion: { habilitada: false, motivos: ['QUORUM_INSUFICIENTE'] },
            cancelar_preparacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
          },
        }),
      })

      expect(botonAbrir.element.disabled).toBe(true)
      expect(botonCancelar.element.disabled).toBe(true)

      await botonAbrir.trigger('click')
      await botonCancelar.trigger('click')
      expect(mockCliente.abrirSesion).toHaveBeenCalledTimes(1)
      expect(mockCliente.cancelarPreparacion).toHaveBeenCalledTimes(1)
    })

    it('N2.G — abre el modal y actualiza autoridades aunque exista una votación', async () => {
      const mockCliente = crearMockCliente()
      const estado = crearEstadoSesionAbierta({
        votacion: {
          id: 'vot-01',
          titulo: 'Tratamiento sobre tablas',
          tipo: 'MAYORIA_SIMPLE',
          fecha_hora_inicio: '2026-08-25T10:35:00Z',
          base_calculo: 'PRESENTES',
        } as unknown as EstadoModeracion['votacion'],
      })
      const wrapper = montarComponenteAislado(PanelSesionVotacion, {
        props: { estado, clienteInyectado: mockCliente },
      })

      expect(wrapper.find('[data-testid="input-presidencia-sesion"]').exists()).toBe(false)
      await wrapper.get('[data-testid="btn-editar-autoridades"]').trigger('click')
      expect(wrapper.get('[data-testid="dialogo-edicion-autoridades"]').exists()).toBe(true)
      await wrapper
        .get('[data-testid="input-presidencia-modal"]')
        .setValue('Dra. Nueva Presidencia')
      await wrapper.get('[data-testid="input-secretaria-modal"]').setValue('Lic. Nueva Secretaría')
      await wrapper.get('[data-testid="btn-guardar-autoridades"]').trigger('click')
      await flushPromises()

      expect(mockCliente.actualizarSesion).toHaveBeenCalledWith({
        presidencia: 'Dra. Nueva Presidencia',
        secretaria_legislativa: 'Lic. Nueva Secretaría',
      })
      expect(wrapper.find('[data-testid="dialogo-edicion-autoridades"]').exists()).toBe(false)
    })

    it('WP-037 — un rechazo al actualizar queda visible y conserva abierto el modal', async () => {
      const mockCliente = crearMockCliente({
        actualizarSesion: vi.fn().mockRejectedValue({ mensaje: 'Auditoría no disponible' }),
      })
      const wrapper = montarComponenteAislado(PanelSesionVotacion, {
        props: { estado: crearEstadoSesionAbierta(), clienteInyectado: mockCliente },
      })

      await wrapper.get('[data-testid="btn-editar-autoridades"]').trigger('click')
      await wrapper.get('[data-testid="btn-guardar-autoridades"]').trigger('click')
      await flushPromises()

      expect(wrapper.get('[data-testid="dialogo-edicion-autoridades"]').exists()).toBe(true)
      expect(wrapper.get('[data-testid="error-autoridades-modal"]').text()).toContain(
        'Auditoría no disponible',
      )
    })

    it('WP-037 — el modal preserva un borrador dirty ante SSE ajeno y cancelar lo descarta', async () => {
      const wrapper = montarComponenteAislado(PanelSesionVotacion, {
        props: { estado: crearEstadoSesionAbierta(), clienteInyectado: crearMockCliente() },
      })

      await wrapper.get('[data-testid="btn-editar-autoridades"]').trigger('click')
      const presidencia = wrapper.get<HTMLInputElement>('[data-testid="input-presidencia-modal"]')
      const secretaria = wrapper.get<HTMLInputElement>('[data-testid="input-secretaria-modal"]')
      await presidencia.setValue('Dra. Borrador local')

      await wrapper.setProps({
        estado: crearEstadoSesionAbierta({
          revision: 2,
          sesion: {
            fecha_hora_inicio_preparacion: '2026-08-25T10:00:00Z',
            fecha_hora_apertura: '2026-08-25T10:30:00Z',
            numero_sesion: 42,
            presidencia: 'Dr. Cambio ajeno',
            secretaria_legislativa: 'Lic. Confirmada por SSE',
          },
        }),
      })

      expect(presidencia.element.value).toBe('Dra. Borrador local')
      expect(secretaria.element.value).toBe('Lic. Confirmada por SSE')

      await wrapper.get('[data-testid="btn-cancelar-autoridades"]').trigger('click')
      expect(wrapper.find('[data-testid="dialogo-edicion-autoridades"]').exists()).toBe(false)

      await wrapper.get('[data-testid="btn-editar-autoridades"]').trigger('click')
      expect(
        wrapper.get<HTMLInputElement>('[data-testid="input-presidencia-modal"]').element.value,
      ).toBe('Dr. Cambio ajeno')
    })

    it('N2.H/CA-063 — sin palabra pendiente cierra directamente y no muestra diálogo', async () => {
      const mockCliente = crearMockCliente()
      const wrapper = montarComponenteAislado(PanelSesionVotacion, {
        props: {
          estado: crearEstadoSesionAbierta({ palabra: { orador: null, cola: [] } }),
          clienteInyectado: mockCliente,
        },
      })

      await wrapper.get('[data-testid="btn-cerrar-sesion"]').trigger('click')
      await flushPromises()

      expect(mockCliente.cerrarSesion).toHaveBeenCalledTimes(1)
      expect(wrapper.find('[data-testid="dialogo-confirmacion-cierre"]').exists()).toBe(false)
      expect(mockCliente.otorgarPalabra).not.toHaveBeenCalled()
      expect(mockCliente.quitarPalabra).not.toHaveBeenCalled()
    })

    it('N2.H/CA-063 — con orador permite cancelar o confirmar sin comandos de palabra', async () => {
      const mockCliente = crearMockCliente()
      const wrapper = montarComponenteAislado(PanelSesionVotacion, {
        props: {
          estado: crearEstadoSesionAbierta({
            palabra: {
              orador: { dni: '30000001', nombre: 'Ana', apellido: 'García', banca: 1 },
              cola: [],
            },
          }),
          clienteInyectado: mockCliente,
        },
      })
      const botonCerrar = wrapper.get('[data-testid="btn-cerrar-sesion"]')

      await botonCerrar.trigger('click')
      expect(wrapper.get('[data-testid="dialogo-confirmacion-cierre"]').exists()).toBe(true)
      expect(mockCliente.cerrarSesion).not.toHaveBeenCalled()

      await wrapper.get('[data-testid="btn-cancelar-cierre"]').trigger('click')
      expect(wrapper.find('[data-testid="dialogo-confirmacion-cierre"]').exists()).toBe(false)
      expect(mockCliente.cerrarSesion).not.toHaveBeenCalled()
      expect(mockCliente.otorgarPalabra).not.toHaveBeenCalled()
      expect(mockCliente.quitarPalabra).not.toHaveBeenCalled()

      await botonCerrar.trigger('click')
      await wrapper.get('[data-testid="btn-confirmar-cierre"]').trigger('click')
      await flushPromises()

      expect(mockCliente.cerrarSesion).toHaveBeenCalledTimes(1)
      expect(mockCliente.otorgarPalabra).not.toHaveBeenCalled()
      expect(mockCliente.quitarPalabra).not.toHaveBeenCalled()
    })

    it('N2.H/CA-063 — una cola sin orador también abre el diálogo antes de cerrar', async () => {
      const mockCliente = crearMockCliente()
      const wrapper = montarComponenteAislado(PanelSesionVotacion, {
        props: {
          estado: crearEstadoSesionAbierta({
            palabra: {
              orador: null,
              cola: [{ dni: '30000002', nombre: 'Beatriz', apellido: 'Díaz', banca: 2 }],
            },
          }),
          clienteInyectado: mockCliente,
        },
      })

      await wrapper.get('[data-testid="btn-cerrar-sesion"]').trigger('click')

      expect(wrapper.get('[data-testid="dialogo-confirmacion-cierre"]').exists()).toBe(true)
      expect(mockCliente.cerrarSesion).not.toHaveBeenCalled()
    })

    it('N2.I — evita double-submit real mientras cerrarSesion permanece pendiente', async () => {
      let resolverCierre!: () => void
      const cierrePendiente = new Promise<void>((resolve) => {
        resolverCierre = resolve
      })
      const mockCliente = crearMockCliente({
        cerrarSesion: vi.fn().mockReturnValue(cierrePendiente),
      })
      const wrapper = montarComponenteAislado(PanelSesionVotacion, {
        props: {
          estado: crearEstadoSesionAbierta({
            palabra: {
              orador: { dni: '30000001', nombre: 'Ana', apellido: 'García', banca: 1 },
              cola: [],
            },
          }),
          clienteInyectado: mockCliente,
        },
      })

      await wrapper.get('[data-testid="btn-cerrar-sesion"]').trigger('click')
      await wrapper.get('[data-testid="btn-confirmar-cierre"]').trigger('click')

      const botonCerrar = wrapper.get<HTMLButtonElement>('[data-testid="btn-cerrar-sesion"]')
      expect(mockCliente.cerrarSesion).toHaveBeenCalledTimes(1)
      expect(botonCerrar.element.disabled).toBe(true)

      await botonCerrar.trigger('click')
      expect(mockCliente.cerrarSesion).toHaveBeenCalledTimes(1)

      resolverCierre()
      await cierrePendiente
      await flushPromises()

      expect(mockCliente.cerrarSesion).toHaveBeenCalledTimes(1)
      expect(botonCerrar.element.disabled).toBe(false)
    })
  })

  // ===========================================================================
  // 6. ACCESIBILIDAD Y FOCO EN DIALOGOCONFIRMACIONCIERRE (H4, N2.J Y N2.K)
  // ===========================================================================
  describe('6. Accesibilidad y foco real en DialogoConfirmacionCierre', () => {
    const palabra = {
      orador: { dni: '30000001', nombre: 'Carlos', apellido: 'Pérez', banca: 2 },
      cola: [{ dni: '30000002', nombre: 'Diana', apellido: 'López', banca: 4 }],
    }

    it('conserva la semántica accesible y el detalle de palabra pendiente', async () => {
      const html = await renderizarSSR(DialogoConfirmacionCierre, {
        palabra,
        abierto: true,
        enviando: false,
      })

      expect(html).toContain('role="dialog"')
      expect(html).toContain('aria-modal="true"')
      expect(html).toContain('aria-labelledby="titulo-dialogo-cierre"')
      expect(html).toContain('aria-describedby="descripcion-dialogo-cierre"')
      expect(html).toContain('Carlos Pérez')
      expect(html).toContain('1 solicitud pendiente')
    })

    it('N2.J/H4 — enfoca Cancelar, atrapa Tab/Shift+Tab, cancela con Escape y restaura foco', async () => {
      const activador = document.createElement('button')
      activador.setAttribute('data-testid', 'activador-externo')
      document.body.appendChild(activador)
      activador.focus()

      const wrapper = montarComponenteAislado(DialogoConfirmacionCierre, {
        attachTo: document.body,
        props: { palabra, abierto: false, enviando: false },
      })

      await wrapper.setProps({ abierto: true })
      await nextTick()

      const dialogo = wrapper.get('[data-testid="dialogo-confirmacion-cierre"]')
      const botonCancelar = wrapper.get<HTMLButtonElement>('[data-testid="btn-cancelar-cierre"]')
      const botonConfirmar = wrapper.get<HTMLButtonElement>('[data-testid="btn-confirmar-cierre"]')

      expect(document.activeElement).toBe(botonCancelar.element)

      botonConfirmar.element.focus()
      dialogo.element.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }))
      await nextTick()
      expect(document.activeElement).toBe(botonCancelar.element)

      botonCancelar.element.focus()
      dialogo.element.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true }),
      )
      await nextTick()
      expect(document.activeElement).toBe(botonConfirmar.element)

      dialogo.element.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
      await nextTick()
      expect(wrapper.emitted('cancelar')).toHaveLength(1)
      expect(wrapper.emitted('confirmar')).toBeUndefined()

      await wrapper.setProps({ abierto: false })
      await nextTick()
      expect(document.activeElement).toBe(activador)
      document.body.removeChild(activador)
    })

    it('N2.K — enviando deshabilita botones y bloquea click, Escape y confirmación adicional', async () => {
      const wrapper = montarComponenteAislado(DialogoConfirmacionCierre, {
        props: { palabra, abierto: true, enviando: true },
      })
      const dialogo = wrapper.get('[data-testid="dialogo-confirmacion-cierre"]')
      const botonCancelar = wrapper.get<HTMLButtonElement>('[data-testid="btn-cancelar-cierre"]')
      const botonConfirmar = wrapper.get<HTMLButtonElement>('[data-testid="btn-confirmar-cierre"]')

      expect(botonCancelar.element.disabled).toBe(true)
      expect(botonConfirmar.element.disabled).toBe(true)

      await botonCancelar.trigger('click')
      await botonConfirmar.trigger('click')
      await dialogo.trigger('keydown', { key: 'Escape' })

      expect(wrapper.emitted('cancelar')).toBeUndefined()
      expect(wrapper.emitted('confirmar')).toBeUndefined()
    })
  })

  // ===========================================================================
  // 7. UTILIDADES: RUTAS Y MOTIVOS
  // ===========================================================================
  describe('7. Utilidades auxiliares', () => {
    it('resolverRutaAsset: normaliza rutas relativas y respeta esquemas absolutos', () => {
      expect(resolverRutaAsset('assets/bancas/banca-01.png')).toBe('/assets/bancas/banca-01.png')
      expect(resolverRutaAsset('/assets/bancas/banca-02.png')).toBe('/assets/bancas/banca-02.png')
      expect(resolverRutaAsset('https://servidor.gob.ar/foto.png')).toBe(
        'https://servidor.gob.ar/foto.png',
      )
      expect(resolverRutaAsset('')).toBe('')
    })

    it('traducirMotivo: traduce códigos estables a mensajes claros en español', () => {
      expect(traducirMotivo('QUORUM_INSUFICIENTE')).toContain('Quórum insuficiente')
      expect(traducirMotivo('NUMERO_SESION_REQUERIDO')).toContain('número de sesión')
      expect(traducirMotivo('PRESIDENCIA_REQUERIDA')).toContain('Presidencia')
      expect(traducirMotivo('SECRETARIA_LEGISLATIVA_REQUERIDA')).toContain('Secretaría Legislativa')
      expect(traducirMotivo('AUDITORIA_NO_DISPONIBLE')).toContain('auditoría institucional')
      expect(traducirMotivo('VOTACION_PENDIENTE')).toContain('votación en curso')
      expect(traducirMotivo('CODIGO_DESCONOCIDO')).toBe('Motivo técnico: CODIGO_DESCONOCIDO')
    })

    it('traducirMotivos: traduce arrays de motivos y maneja valores nulos o vacíos', () => {
      const motivos = traducirMotivos(['QUORUM_INSUFICIENTE', 'PRESIDENCIA_REQUERIDA'])
      expect(motivos).toHaveLength(2)
      expect(motivos[0]).toContain('Quórum insuficiente')
      expect(motivos[1]).toContain('Presidencia')

      expect(traducirMotivos([])).toEqual([])
      expect(traducirMotivos(null)).toEqual([])
    })
  })
})
