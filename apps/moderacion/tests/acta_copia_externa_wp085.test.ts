/**
 * Avisos de Moderación tras el cierre institucional (WP-085).
 *
 * Qué demuestra este archivo
 * --------------------------
 * Al cerrar una sesión el backend produce dos archivos derivados —el informe de acta y,
 * opcionalmente, una copia externa del conjunto— y devuelve en el cuerpo de la respuesta qué
 * pasó con cada uno. El operador no puede ver ninguno de los dos desde Moderación, así que el
 * único canal por el que se entera es el aviso efímero que muestra este cuadrante.
 *
 * Las cuatro reglas que se verifican acá son decisiones cerradas del WP:
 *
 * 1. **Sin copia configurada no hay aviso.** `copia_externa: 'OMITIDA'` con acta generada es la
 *    operación normal de una instalación que no pidió copia externa; anunciarla sería ruido.
 * 2. **Copia realizada muestra confirmación.** Es la única evidencia visible de que la réplica
 *    existe.
 * 3. **Un fallo del acta o de la copia se anuncia sin decir que el cierre falló.** El texto debe
 *    empezar afirmando que la sesión cerró: es lo que evita que el operador intente cerrarla otra
 *    vez sobre un sistema que ya volvió a «sin preparar».
 * 4. **Ese fallo no usa el canal de error persistente.** El error persistente de este cuadrante es
 *    accionable y se cierra a mano; acá no hay nada que reintentar desde Moderación, porque el
 *    cierre institucional ya es irreversible.
 *
 * Como el resto de las pruebas de Moderación, las mutaciones se simulan con un cliente falso: el
 * componente nunca decide reglas institucionales por su cuenta.
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
    generado_en: '2026-09-08T10:00:00Z',
    estado_global: 'SESION_ABIERTA',
    preparacion: null,
    sesion: {
      fecha_hora_inicio_preparacion: '2026-09-08T09:00:00Z',
      fecha_hora_apertura: '2026-09-08T09:30:00Z',
      numero_sesion: 42,
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

const SELECTOR_ADVERTENCIA = '[data-testid="alerta-advertencia-comando"]'
const SELECTOR_EXITO = '[data-testid="alerta-exito-comando"]'
const SELECTOR_ERROR = '[data-testid="alerta-error-comando"]'

beforeEach(() => reiniciarInstanciaCompartidaParaPruebas())

afterEach(() => {
  while (montados.length > 0) montados.pop()?.unmount()
  document.body.textContent = ''
  vi.useRealTimers()
})

describe('WP-085 — avisos de acta y copia externa al cerrar la sesión', () => {
  it('CA-085.5 — sin copia configurada el cierre no muestra ningún aviso', async () => {
    const wrapper = await cerrarSesionDesdeElPanel({
      acta_generada: true,
      copia_externa: 'OMITIDA',
    })

    expect(wrapper.find(SELECTOR_EXITO).exists()).toBe(false)
    expect(wrapper.find(SELECTOR_ADVERTENCIA).exists()).toBe(false)
    expect(wrapper.find(SELECTOR_ERROR).exists()).toBe(false)
  })

  it('CA-085.8 — una copia exitosa se confirma con un aviso efímero', async () => {
    vi.useFakeTimers()
    const wrapper = await cerrarSesionDesdeElPanel({
      acta_generada: true,
      copia_externa: 'EXITOSA',
    })

    const aviso = wrapper.get(SELECTOR_EXITO)
    expect(aviso.text()).toContain('copiados a la carpeta externa')
    expect(wrapper.find(SELECTOR_ADVERTENCIA).exists()).toBe(false)
    expect(wrapper.find(SELECTOR_ERROR).exists()).toBe(false)

    // Efímero de verdad: caduca solo, sin que el operador lo cierre.
    vi.advanceTimersByTime(DURACION_AVISO_EFIMERO_MS)
    await flushPromises()
    expect(wrapper.find(SELECTOR_EXITO).exists()).toBe(false)
  })

  it('CA-085.7 — una copia fallida avisa el error diciendo que la sesión sí cerró', async () => {
    vi.useFakeTimers()
    const wrapper = await cerrarSesionDesdeElPanel({
      acta_generada: true,
      copia_externa: 'FALLIDA',
    })

    const aviso = wrapper.get(SELECTOR_ADVERTENCIA)
    // Lo primero que se lee es que el cierre ocurrió: sin eso, el operador
    // intentaría cerrar otra vez una sesión que ya no existe.
    expect(aviso.text()).toContain('La sesión cerró')
    expect(aviso.text()).toContain('no se pudo copiarlos a la carpeta externa')
    // No usa el canal persistente y accionable: no hay nada que reintentar acá.
    expect(wrapper.find(SELECTOR_ERROR).exists()).toBe(false)
    expect(wrapper.find(SELECTOR_EXITO).exists()).toBe(false)

    vi.advanceTimersByTime(DURACION_AVISO_EFIMERO_MS)
    await flushPromises()
    expect(wrapper.find(SELECTOR_ADVERTENCIA).exists()).toBe(false)
  })

  it('CA-085.1 — un informe de acta fallido también avisa que la sesión sí cerró', async () => {
    const wrapper = await cerrarSesionDesdeElPanel({
      acta_generada: false,
      copia_externa: 'OMITIDA',
    })

    const aviso = wrapper.get(SELECTOR_ADVERTENCIA)
    expect(aviso.text()).toContain('La sesión cerró')
    expect(aviso.text()).toContain('no se pudo generar el informe de acta')
    expect(wrapper.find(SELECTOR_ERROR).exists()).toBe(false)
    expect(wrapper.find(SELECTOR_EXITO).exists()).toBe(false)
  })

  it('un cierre sin cuerpo no se confunde con un cierre fallido', async () => {
    // Guarda defensiva del componente: si la respuesta llegara vacía, el panel no
    // debe caer en su `catch` y mostrar «Error al cerrar la sesión» sobre un cierre
    // que en realidad fue exitoso.
    const wrapper = await cerrarSesionDesdeElPanel(undefined as unknown as RespuestaCierreSesion)

    expect(wrapper.find(SELECTOR_ERROR).exists()).toBe(false)
    expect(wrapper.find(SELECTOR_ADVERTENCIA).exists()).toBe(false)
    expect(wrapper.find(SELECTOR_EXITO).exists()).toBe(false)
  })
})
