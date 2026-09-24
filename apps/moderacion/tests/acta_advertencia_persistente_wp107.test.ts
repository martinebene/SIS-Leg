/**
 * Advertencia persistente cuando el informe de acta no se pudo generar (WP-107).
 *
 * Qué cambia respecto de WP-085
 * -----------------------------
 * WP-085 informaba los tres desenlaces posteriores al cierre —acta, copia externa y éxito—
 * con avisos efímeros de 2500 ms. Para la copia externa eso alcanza: los archivos locales,
 * que son el registro institucional válido, quedaron completos y la réplica es redundancia.
 *
 * Para el informe de acta no alcanza. Es el único desenlace que deja al cuerpo legislativo
 * sin un documento que esperaba tener, y obliga a una acción humana posterior fuera de
 * Moderación. Un aviso que se apaga solo a los 2,5 segundos se pierde exactamente cuando el
 * operador está mirando el recinto y no la pantalla, y entonces nadie se entera hasta que
 * alguien busca el archivo días después.
 *
 * Las cuatro reglas que fija este archivo
 * ---------------------------------------
 * 1. `acta_generada: false` muestra una advertencia que **no** caduca sola.
 * 2. Su texto afirma primero que la sesión cerró y que los CSV quedaron completos: el cierre
 *    institucional no se presenta como fallido, porque ya es irreversible.
 * 3. El operador puede cerrarla a mano.
 * 4. El camino normal (`acta_generada: true`) no gana ningún ruido nuevo.
 *
 * Igual que el resto de las pruebas de Moderación, el cliente es falso: el componente nunca
 * decide reglas institucionales por su cuenta.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { compile, type Component, ssrContextKey } from 'vue'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import type {
  ClienteModeracion,
  ConcejalModeracion,
  EstadoModeracion,
  RespuestaCierreSesion,
} from '@sis-leg/api-client'
import PanelContenedor from '../app/components/PanelContenedor.vue'
import fuentePanelContenedor from '../app/components/PanelContenedor.vue?raw'
import PanelSesionVotacion from '../app/components/PanelSesionVotacion.vue'
import fuentePanelSesionVotacion from '../app/components/PanelSesionVotacion.vue?raw'
import GestionVotacion from '../app/components/GestionVotacion.vue'
import fuenteGestionVotacion from '../app/components/GestionVotacion.vue?raw'
import DialogoConfirmacionApertura from '../app/components/DialogoConfirmacionApertura.vue'
import fuenteDialogoConfirmacionApertura from '../app/components/DialogoConfirmacionApertura.vue?raw'
import DialogoConfirmacionCierre from '../app/components/DialogoConfirmacionCierre.vue'
import fuenteDialogoConfirmacionCierre from '../app/components/DialogoConfirmacionCierre.vue?raw'
import DialogoEdicionAutoridades from '../app/components/DialogoEdicionAutoridades.vue'
import fuenteDialogoEdicionAutoridades from '../app/components/DialogoEdicionAutoridades.vue?raw'
import { reiniciarInstanciaCompartidaParaPruebas } from '../app/composables/useEstadoModeracion'
import { DURACION_AVISO_EFIMERO_MS } from '../app/composables/useAvisoEfimero'

/**
 * Vitest compila los SFC para SSR; este helper adjunta el render de cliente de la misma
 * plantilla productiva para poder interactuar con el DOM. No duplica lógica: solo cubre la
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
habilitarRenderCliente(DialogoConfirmacionApertura, fuenteDialogoConfirmacionApertura)
habilitarRenderCliente(DialogoConfirmacionCierre, fuenteDialogoConfirmacionCierre)
habilitarRenderCliente(DialogoEdicionAutoridades, fuenteDialogoEdicionAutoridades)
habilitarRenderCliente(GestionVotacion, fuenteGestionVotacion, { DialogoConfirmacionApertura })
habilitarRenderCliente(PanelSesionVotacion, fuentePanelSesionVotacion, {
  PanelContenedor,
  GestionVotacion,
  DialogoConfirmacionCierre,
  DialogoEdicionAutoridades,
})

const montados: VueWrapper[] = []

function montar(componente: Component, props: Record<string, unknown>): VueWrapper {
  const wrapper = mount(componente, {
    props,
    global: { provide: { [ssrContextKey]: { modules: new Set() } } },
  })
  montados.push(wrapper)
  return wrapper
}

function crearConcejales(): ConcejalModeracion[] {
  return [1, 2, 3].map((banca) => ({
    dni: String(banca),
    nombre: `Concejal${banca}`,
    apellido: `Apellido${banca}`,
    bloque: 'Bloque',
    banca,
    dispositivo_votacion: `dev0${banca}`,
    ruta_imagen: `assets/bancas/banca-0${banca}.png`,
    presente: true,
    test_activo: false,
    test_expira_en: null,
  }))
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

/** Sesión abierta sin orador ni cola: el botón de cierre no abre diálogo de advertencia. */
function crearEstadoSesionAbierta(): EstadoModeracion {
  return {
    instancia: 'instancia-prueba',
    revision: 1,
    generado_en: '2026-09-24T10:00:00Z',
    estado_global: 'SESION_ABIERTA',
    preparacion: null,
    sesion: {
      fecha_hora_inicio_preparacion: '2026-09-24T09:00:00Z',
      fecha_hora_apertura: '2026-09-24T09:30:00Z',
      numero_sesion: 107,
      presidencia: 'Dra. Presidencia',
      secretaria_legislativa: 'Sr. Secretaría',
    },
    configuracion: {
      quorum: 2,
      filas_bancas: [3],
      tipos_votacion: ['Proyecto'],
      duracion_test_segundos: 3,
      revelado_votos_moderacion_segundos: 4,
      cuenta_regresiva_recinto_segundos: 3,
      resultado_publico_recinto_segundos: 6,
    },
    concejales: crearConcejales(),
    quorum: { cantidad_presentes: 3, requerido: 2, alcanzado: true },
    votacion: null,
    palabra: { orador: null, cola: [] },
    orden_del_dia: [],
    eventos_recientes: [],
    auditoria: { activa: true, disponible: true, fallado: false, cerrado: false, motivo: null },
    remapeo: null,
    capacidades: crearCapacidades(),
  }
}

/** Cliente falso cuyo único comportamiento relevante es el cuerpo devuelto por el cierre. */
function crearCliente(respuestaCierre: RespuestaCierreSesion): ClienteModeracion {
  return {
    prepararSala: vi.fn().mockResolvedValue(undefined),
    actualizarPreparacion: vi.fn().mockResolvedValue(undefined),
    cancelarPreparacion: vi.fn().mockResolvedValue(undefined),
    abrirSesion: vi.fn().mockResolvedValue(undefined),
    actualizarSesion: vi.fn().mockResolvedValue(undefined),
    cerrarSesion: vi.fn().mockResolvedValue(respuestaCierre),
    cargarOrdenDelDia: vi.fn().mockResolvedValue({ puntos: [] }),
    descartarOrdenDelDia: vi.fn().mockResolvedValue(undefined),
    abrirVotacion: vi.fn().mockResolvedValue({ id: 'votacion-1' }),
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
  } as unknown as ClienteModeracion
}

/** Cierra la sesión desde el botón real del cuadrante y espera la respuesta del cliente. */
async function cerrarSesionDesdeElPanel(
  respuestaCierre: RespuestaCierreSesion,
): Promise<VueWrapper> {
  const wrapper = montar(PanelSesionVotacion, {
    estado: crearEstadoSesionAbierta(),
    clienteInyectado: crearCliente(respuestaCierre),
  })

  await wrapper.get('[data-testid="btn-cerrar-sesion"]').trigger('click')
  await flushPromises()
  return wrapper
}

const SELECTOR_ADVERTENCIA_ACTA = '[data-testid="alerta-advertencia-acta"]'
const SELECTOR_DESCARTAR_ACTA = '[data-testid="btn-descartar-advertencia-acta"]'
const SELECTOR_ADVERTENCIA_EFIMERA = '[data-testid="alerta-advertencia-comando"]'
const SELECTOR_EXITO = '[data-testid="alerta-exito-comando"]'
const SELECTOR_ERROR = '[data-testid="alerta-error-comando"]'

/**
 * Margen muy superior al temporizador efímero.
 *
 * No alcanza con avanzar exactamente 2500 ms: eso sólo probaría que no caduca en ese
 * instante. Avanzar cuarenta veces esa duración demuestra que no hay **ningún** temporizador
 * detrás de la advertencia, cualquiera fuese su valor.
 */
const ESPERA_MUY_LARGA_MS = DURACION_AVISO_EFIMERO_MS * 40

beforeEach(() => reiniciarInstanciaCompartidaParaPruebas())

afterEach(() => {
  while (montados.length > 0) montados.pop()?.unmount()
  document.body.textContent = ''
  vi.useRealTimers()
})

describe('WP-107 — advertencia persistente de informe de acta no generado', () => {
  it('la advertencia no desaparece sola después del temporizador efímero', async () => {
    vi.useFakeTimers()
    const wrapper = await cerrarSesionDesdeElPanel({
      acta_generada: false,
      copia_externa: 'OMITIDA',
    })

    expect(wrapper.find(SELECTOR_ADVERTENCIA_ACTA).exists()).toBe(true)

    vi.advanceTimersByTime(DURACION_AVISO_EFIMERO_MS)
    await flushPromises()
    expect(wrapper.find(SELECTOR_ADVERTENCIA_ACTA).exists()).toBe(true)

    vi.advanceTimersByTime(ESPERA_MUY_LARGA_MS)
    await flushPromises()
    expect(wrapper.find(SELECTOR_ADVERTENCIA_ACTA).exists()).toBe(true)
  })

  it('el texto afirma que la sesión cerró y que los CSV quedaron completos', async () => {
    const wrapper = await cerrarSesionDesdeElPanel({
      acta_generada: false,
      copia_externa: 'OMITIDA',
    })

    const texto = wrapper.get(SELECTOR_ADVERTENCIA_ACTA).text()
    // Lo primero que se lee es el cierre consumado: sin eso el operador intentaría cerrar
    // otra vez una sesión que ya no existe.
    expect(texto.indexOf('La sesión cerró correctamente')).toBe(0)
    expect(texto).toContain('los registros CSV quedaron completos y cerrados')
    expect(texto).toContain('No se pudo generar el informe de acta')
    expect(texto).toContain('Los CSV siguen siendo el registro institucional válido')
    // No se presenta como un fallo del cierre ni como un error accionable.
    expect(texto).not.toContain('Error')
    expect(wrapper.find(SELECTOR_ERROR).exists()).toBe(false)
  })

  it('el operador puede descartarla manualmente', async () => {
    const wrapper = await cerrarSesionDesdeElPanel({
      acta_generada: false,
      copia_externa: 'OMITIDA',
    })

    const boton = wrapper.get(SELECTOR_DESCARTAR_ACTA)
    // El botón dice con palabras qué hace: la «✕» sola no es descriptiva para un lector de
    // pantalla. Se lee del elemento y no de `attributes()` porque el entorno de prueba no
    // serializa los atributos estáticos del render compilado a mano.
    expect(boton.element.getAttribute('aria-label')).toContain('Descartar')

    await boton.trigger('click')
    await flushPromises()

    expect(wrapper.find(SELECTOR_ADVERTENCIA_ACTA).exists()).toBe(false)
  })

  it('usa un canal propio y no el aviso efímero de advertencia', async () => {
    const wrapper = await cerrarSesionDesdeElPanel({
      acta_generada: false,
      copia_externa: 'OMITIDA',
    })

    expect(wrapper.find(SELECTOR_ADVERTENCIA_ACTA).exists()).toBe(true)
    expect(wrapper.find(SELECTOR_ADVERTENCIA_EFIMERA).exists()).toBe(false)
    expect(wrapper.find(SELECTOR_EXITO).exists()).toBe(false)
  })

  it('un acta generada no muestra ninguna advertencia nueva', async () => {
    // El camino feliz es el habitual: WP-107 no puede agregarle ruido.
    for (const copia of ['OMITIDA', 'EXITOSA'] as const) {
      const wrapper = await cerrarSesionDesdeElPanel({
        acta_generada: true,
        copia_externa: copia,
      })

      expect(wrapper.find(SELECTOR_ADVERTENCIA_ACTA).exists()).toBe(false)
      expect(wrapper.find(SELECTOR_ERROR).exists()).toBe(false)
    }
  })

  it('una copia externa fallida sigue usando el aviso efímero de WP-085', async () => {
    // La copia es redundancia y los archivos locales quedaron completos: ese desenlace no
    // justifica ocupar la pantalla hasta que alguien lo cierre.
    vi.useFakeTimers()
    const wrapper = await cerrarSesionDesdeElPanel({
      acta_generada: true,
      copia_externa: 'FALLIDA',
    })

    expect(wrapper.find(SELECTOR_ADVERTENCIA_EFIMERA).exists()).toBe(true)
    expect(wrapper.find(SELECTOR_ADVERTENCIA_ACTA).exists()).toBe(false)

    vi.advanceTimersByTime(DURACION_AVISO_EFIMERO_MS)
    await flushPromises()
    expect(wrapper.find(SELECTOR_ADVERTENCIA_EFIMERA).exists()).toBe(false)
  })
})
