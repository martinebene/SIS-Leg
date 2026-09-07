/**
 * Regresión de las correcciones UX aprobadas por HUMAN_GATE en WP-044.
 *
 * Cada caso demuestra una decisión concreta de la segunda prueba humana sobre los
 * componentes productivos reales de Moderación:
 *
 * - Q1..Q4 pierden el subtítulo de cuadrante.
 * - Q1 lista los motivos de `preparar_sala` en líneas separadas y jerarquiza el
 *   resultado de la votación cerrada con la convención de color de producción.
 * - Q2 muestra el nombre del archivo una sola vez y acusa la copia de un punto con
 *   un único toast flotante de ~1 s que se reemplaza y se limpia al desmontar.
 * - Q3 elimina el texto redundante del orador, el subtítulo FIFO, el subencabezado
 *   de bancas y el acuse de éxito de Otorgar/Quitar, conservando los errores reales
 *   y el flujo de remapeo autoritativo.
 * - Q4 solo pierde el subtítulo.
 *
 * Las mutaciones institucionales siguen simulándose exclusivamente con `setProps`,
 * porque ninguna de estas correcciones habilita actualización optimista.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { compile, nextTick, type Component, ssrContextKey } from 'vue'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import type {
  ClienteModeracion,
  ConcejalModeracion,
  EstadoModeracion,
  PuntoOrdenDelDiaProyectado,
  VotacionModeracion,
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
import PanelOrdenDelDia from '../app/components/PanelOrdenDelDia.vue'
import fuentePanelOrdenDelDia from '../app/components/PanelOrdenDelDia.vue?raw'
import PanelRecintoPalabra from '../app/components/PanelRecintoPalabra.vue'
import fuentePanelRecintoPalabra from '../app/components/PanelRecintoPalabra.vue?raw'
import GestionPalabra from '../app/components/GestionPalabra.vue'
import fuenteGestionPalabra from '../app/components/GestionPalabra.vue?raw'
import GestionRemapeo from '@sis-leg/frontend-shared/componentes/GestionRemapeo.vue'
import fuenteGestionRemapeo from '@sis-leg/frontend-shared/componentes/GestionRemapeo.vue?raw'
import GrillaRecinto from '../app/components/GrillaRecinto.vue'
import fuenteGrillaRecinto from '../app/components/GrillaRecinto.vue?raw'
import BancaConcejal from '../app/components/BancaConcejal.vue'
import fuenteBancaConcejal from '../app/components/BancaConcejal.vue?raw'
import PanelEventos from '../app/components/PanelEventos.vue'
import fuentePanelEventos from '../app/components/PanelEventos.vue?raw'
import { reiniciarInstanciaCompartidaParaPruebas } from '../app/composables/useEstadoModeracion'

/**
 * Vitest compila los SFC para SSR; este helper adjunta el render de cliente de la
 * misma plantilla productiva para poder interactuar con el DOM. No duplica lógica:
 * únicamente cubre la frontera de compilación que en la aplicación aporta Nuxt.
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
habilitarRenderCliente(PanelOrdenDelDia, fuentePanelOrdenDelDia, { PanelContenedor })
habilitarRenderCliente(GestionPalabra, fuenteGestionPalabra)
habilitarRenderCliente(GestionRemapeo, fuenteGestionRemapeo)
habilitarRenderCliente(BancaConcejal, fuenteBancaConcejal)
habilitarRenderCliente(GrillaRecinto, fuenteGrillaRecinto, { BancaConcejal })
habilitarRenderCliente(PanelRecintoPalabra, fuentePanelRecintoPalabra, {
  PanelContenedor,
  GestionPalabra,
  GestionRemapeo,
  GrillaRecinto,
})
habilitarRenderCliente(PanelEventos, fuentePanelEventos, { PanelContenedor })

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
    preparar_sala: { habilitada: true, motivos: [] },
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

function crearEstado(parcial: Partial<EstadoModeracion> = {}): EstadoModeracion {
  return {
    instancia: 'instancia-prueba',
    revision: 1,
    generado_en: '2026-08-30T10:00:00Z',
    estado_global: 'SESION_ABIERTA',
    preparacion: null,
    sesion: {
      fecha_hora_inicio_preparacion: '2026-08-30T09:00:00Z',
      fecha_hora_apertura: '2026-08-30T09:30:00Z',
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
    concejales: crearConcejales(),
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

function crearVotacion(parcial: Partial<VotacionModeracion> = {}): VotacionModeracion {
  return {
    id: 'votacion-1',
    numero_votacion: 7,
    tipo: 'Proyecto',
    tema: 'Presupuesto anual',
    tipo_mayoria: 'SIMPLE',
    factor: 0,
    base: 'VOTOS_COMPUTABLES',
    estado_recepcion: 'CERRADA',
    resultado: 'APROBADA',
    fecha_hora_apertura: '2026-08-30T10:00:00Z',
    fecha_hora_cierre: '2026-08-30T10:01:00Z',
    fecha_hora_resultado: '2026-08-30T10:01:00Z',
    motivo_finalizacion_manual: null,
    cantidad_votos_recibidos: 3,
    revelado_individual_desde: '2026-08-30T10:01:04Z',
    votos_individuales_revelados: true,
    votos_individuales: null,
    conteos: { positivos: 2, negativos: 1, abstenciones: 1, total: 4 },
    voto_presidencial: null,
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

const puntoSimple: PuntoOrdenDelDiaProyectado = {
  nro_votacion: 7,
  tipo: 'Proyecto',
  tema: 'Presupuesto anual',
  tipo_mayoria: 'SIMPLE',
  factor: 0,
  base: 'VOTOS_COMPUTABLES',
  tratado: false,
}

const puntoEspecial: PuntoOrdenDelDiaProyectado = {
  nro_votacion: 9,
  tipo: 'Moción',
  tema: 'Modificación del reglamento',
  tipo_mayoria: 'ESPECIAL',
  factor: 0.66,
  base: 'CUERPO',
  tratado: false,
}

/**
 * Texto del encabezado del panel: título más cualquier segunda línea descriptiva.
 * Sirve para afirmar que ningún cuadrante conserva subtítulo sin acoplar la prueba
 * a las clases de Tailwind del componente contenedor.
 *
 * El encabezado es el `<header>` de `PanelContenedor`, que además es el nodo raíz del
 * panel montado; por eso se busca directamente por etiqueta.
 */
function textoEncabezado(wrapper: VueWrapper): string {
  return wrapper.get('header').text()
}

/**
 * Clases CSS efectivas de un elemento.
 *
 * El entorno de pruebas usa un DOM mínimo propio del repositorio donde `classes()` de
 * Vue Test Utils no está disponible: se lee el atributo real renderizado.
 */
function clasesDe(wrapper: VueWrapper, selector: string): string {
  return (wrapper.get(selector).element as HTMLElement).className
}

/** Lee un atributo renderizado, por el mismo motivo que `clasesDe`. */
function atributoDe(wrapper: VueWrapper, selector: string, atributo: string): string | null {
  return wrapper.get(selector).element.getAttribute(atributo)
}

beforeEach(() => reiniciarInstanciaCompartidaParaPruebas())

afterEach(() => {
  while (montados.length > 0) montados.pop()?.unmount()
  document.body.textContent = ''
  vi.useRealTimers()
})

describe('WP-044 · Q1 Sesión y votación', () => {
  it('no muestra subtítulo de cuadrante en el encabezado', () => {
    const wrapper = montar(PanelSesionVotacion, {
      estado: crearEstado({ estado_global: 'SIN_PREPARAR', sesion: null }),
      clienteInyectado: crearCliente(),
    })

    expect(textoEncabezado(wrapper)).toContain('Sesión y votación')
    expect(wrapper.find('header p').exists()).toBe(false)
  })

  it('SIN_PREPARAR: renderiza un motivo por línea sin concatenarlos', () => {
    const estado = crearEstado({
      estado_global: 'SIN_PREPARAR',
      sesion: null,
      capacidades: {
        ...crearCapacidades(),
        preparar_sala: {
          habilitada: false,
          motivos: ['AUDITORIA_NO_DISPONIBLE', 'PADRON_NO_DISPONIBLE'],
        },
      },
    })
    const wrapper = montar(PanelSesionVotacion, { estado, clienteInyectado: crearCliente() })

    const lineas = wrapper.findAll('[data-testid="motivo-preparar-sala"]')
    expect(lineas).toHaveLength(2)
    expect(lineas[0]?.text()).toContain('auditoría institucional no está disponible')
    expect(lineas[1]?.text()).toContain('padrón de concejales')
    // La concatenación anterior usaba un separador medio; ya no debe existir.
    expect(wrapper.get('[data-testid="motivos-preparar-sala"]').text()).not.toContain(' · ')
  })

  it('resultado cerrado: abstención amarilla, convención de color y jerarquía dominante', () => {
    const wrapper = montar(GestionVotacion, {
      estado: crearEstado({ votacion: crearVotacion() }),
      cliente: crearCliente(),
      conectado: true,
      puntoPreseleccionado: null,
    })

    expect(clasesDe(wrapper, '[data-testid="conteo-positivos"]')).toContain('emerald')
    expect(clasesDe(wrapper, '[data-testid="conteo-negativos"]')).toContain('rose')
    // Amber es la familia amarilla del sistema visual; es la convención de producción.
    expect(clasesDe(wrapper, '[data-testid="conteo-abstenciones"]')).toContain('amber')
    expect(clasesDe(wrapper, '[data-testid="conteo-abstenciones"]')).not.toContain('slate')

    expect(wrapper.get('[data-testid="estado-votacion"]').text()).toBe('APROBADA')
    expect(atributoDe(wrapper, '[data-testid="estado-votacion"]', 'data-jerarquia')).toBe(
      'principal',
    )
    expect(clasesDe(wrapper, '[data-testid="estado-votacion"]')).toContain('text-2xl')
  })

  it('mantiene diferenciadas EMPATADA e INCONCLUSA sin presentarlas como aprobadas', async () => {
    const wrapper = montar(GestionVotacion, {
      estado: crearEstado({ votacion: crearVotacion({ resultado: 'EMPATADA' }) }),
      cliente: crearCliente(),
      conectado: true,
      puntoPreseleccionado: null,
    })

    expect(wrapper.get('[data-testid="estado-votacion"]').text()).toBe('EMPATADA')
    expect(atributoDe(wrapper, '[data-testid="estado-votacion"]', 'data-jerarquia')).toBe(
      'principal',
    )
    expect(clasesDe(wrapper, '[data-testid="estado-votacion"]')).toContain('amber')

    await wrapper.setProps({
      estado: crearEstado({
        revision: 2,
        votacion: crearVotacion({ resultado: 'INCONCLUSA' }),
      }),
    })
    expect(wrapper.get('[data-testid="estado-votacion"]').text()).toBe('INCONCLUSA')
    expect(clasesDe(wrapper, '[data-testid="estado-votacion"]')).toContain('slate')
    expect(clasesDe(wrapper, '[data-testid="estado-votacion"]')).not.toContain('emerald')
  })

  it('una votación EN_CURSO conserva el badge compacto', () => {
    const wrapper = montar(GestionVotacion, {
      estado: crearEstado({
        votacion: crearVotacion({ estado_recepcion: 'EN_CURSO', resultado: null, conteos: null }),
      }),
      cliente: crearCliente(),
      conectado: true,
      puntoPreseleccionado: null,
    })

    expect(wrapper.get('[data-testid="estado-votacion"]').text()).toBe('EN_CURSO')
    expect(atributoDe(wrapper, '[data-testid="estado-votacion"]', 'data-jerarquia')).toBe(
      'secundaria',
    )
    expect(clasesDe(wrapper, '[data-testid="estado-votacion"]')).not.toContain('text-2xl')
  })

  it('un punto preseleccionado precarga el borrador sin generar un segundo aviso', async () => {
    const wrapper = montar(GestionVotacion, {
      estado: crearEstado(),
      cliente: crearCliente(),
      conectado: true,
      puntoPreseleccionado: null,
    })

    await wrapper.setProps({ puntoPreseleccionado: puntoEspecial })
    await nextTick()

    expect(
      (wrapper.get('[data-testid="input-numero-votacion"]').element as HTMLInputElement).value,
    ).toBe('9')
    expect(
      (wrapper.get('[data-testid="input-tema-votacion"]').element as HTMLInputElement).value,
    ).toBe('Modificación del reglamento')
    expect(wrapper.find('[data-testid="aviso-votacion"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('copiado al borrador')
  })
})

describe('WP-044 · Q2 Orden del Día', () => {
  async function seleccionarArchivo(wrapper: VueWrapper, nombre: string): Promise<void> {
    const archivo = new File(['nro_votacion;tipo'], nombre, { type: 'text/csv' })
    const entrada = wrapper.get('[data-testid="input-archivo-orden-dia"]')
    Object.defineProperty(entrada.element, 'files', { configurable: true, value: [archivo] })
    await entrada.trigger('change')
  }

  it('no muestra subtítulo de cuadrante en ninguna de sus dos vistas', async () => {
    const wrapper = montar(PanelOrdenDelDia, {
      estado: crearEstado({ orden_del_dia: [] }),
      clienteInyectado: crearCliente(),
    })
    expect(wrapper.find('header p').exists()).toBe(false)
    expect(textoEncabezado(wrapper)).toContain('Orden del Día')
    expect(textoEncabezado(wrapper)).not.toContain('Carga CSV compacta')

    await wrapper.setProps({ estado: crearEstado({ revision: 2, orden_del_dia: [puntoSimple] }) })
    expect(wrapper.find('header p').exists()).toBe(false)
    expect(textoEncabezado(wrapper)).not.toContain('Puntos confirmados por backend')
  })

  it('muestra el nombre del archivo una sola vez, en el input nativo', async () => {
    const wrapper = montar(PanelOrdenDelDia, {
      estado: crearEstado({ orden_del_dia: [] }),
      clienteInyectado: crearCliente(),
    })

    await seleccionarArchivo(wrapper, 'orden-sesion-42.csv')

    // El input nativo dibuja el nombre por sí mismo: el componente no debe repetirlo.
    expect(wrapper.text()).not.toContain('orden-sesion-42.csv')
    expect(wrapper.text()).not.toContain('Seleccionado:')
  })

  it('copiar un punto produce un único toast que desaparece cerca de los 1000 ms', async () => {
    vi.useFakeTimers()
    const wrapper = montar(PanelOrdenDelDia, {
      estado: crearEstado({ orden_del_dia: [puntoSimple, puntoEspecial] }),
      clienteInyectado: crearCliente(),
    })

    await wrapper.findAll('[data-testid="punto-orden-dia"]')[0]?.trigger('click')
    expect(wrapper.emitted('seleccionar')?.[0]?.[0]).toEqual(puntoSimple)

    const toasts = wrapper.findAll('[data-testid="toast-punto-copiado"]')
    expect(toasts).toHaveLength(1)
    expect(toasts[0]?.text()).toContain('Punto Nº 7 copiado al borrador')
    // El acuse anterior vivía en el flujo normal del cuadrante; ahora no existe.
    expect(wrapper.find('[data-testid="aviso-orden-dia"]').exists()).toBe(false)

    vi.advanceTimersByTime(999)
    await nextTick()
    expect(wrapper.find('[data-testid="toast-punto-copiado"]').exists()).toBe(true)

    vi.advanceTimersByTime(1)
    await nextTick()
    expect(wrapper.find('[data-testid="toast-punto-copiado"]').exists()).toBe(false)
  })

  it('una selección nueva reemplaza el toast vigente sin acumular avisos ni timers', async () => {
    vi.useFakeTimers()
    const wrapper = montar(PanelOrdenDelDia, {
      estado: crearEstado({ orden_del_dia: [puntoSimple, puntoEspecial] }),
      clienteInyectado: crearCliente(),
    })

    await wrapper.findAll('[data-testid="punto-orden-dia"]')[0]?.trigger('click')
    vi.advanceTimersByTime(700)
    await wrapper.findAll('[data-testid="punto-orden-dia"]')[1]?.trigger('click')
    await nextTick()

    expect(wrapper.findAll('[data-testid="toast-punto-copiado"]')).toHaveLength(1)
    expect(wrapper.get('[data-testid="toast-punto-copiado"]').text()).toContain('Punto Nº 9')

    // El timer viejo ya no puede apagar el acuse nuevo antes de tiempo.
    vi.advanceTimersByTime(400)
    await nextTick()
    expect(wrapper.get('[data-testid="toast-punto-copiado"]').text()).toContain('Punto Nº 9')

    vi.advanceTimersByTime(600)
    await nextTick()
    expect(wrapper.find('[data-testid="toast-punto-copiado"]').exists()).toBe(false)
  })

  it('cancela el temporizador pendiente al desmontar el componente', async () => {
    vi.useFakeTimers()
    const limpiar = vi.spyOn(globalThis, 'clearTimeout')
    const wrapper = montar(PanelOrdenDelDia, {
      estado: crearEstado({ orden_del_dia: [puntoSimple] }),
      clienteInyectado: crearCliente(),
    })

    await wrapper.get('[data-testid="punto-orden-dia"]').trigger('click')
    limpiar.mockClear()
    wrapper.unmount()
    montados.splice(montados.indexOf(wrapper), 1)

    expect(limpiar).toHaveBeenCalled()
    // Avanzar el reloj después del unmount no debe ejecutar ninguna escritura pendiente.
    expect(() => vi.advanceTimersByTime(2000)).not.toThrow()
    limpiar.mockRestore()
  })
})

describe('WP-044 · Q3 Recinto y palabra', () => {
  it('no muestra subtítulo de cuadrante ni el subencabezado de bancas', () => {
    const wrapper = montar(PanelRecintoPalabra, {
      estado: crearEstado(),
      cliente: crearCliente(),
      conectado: true,
    })

    expect(wrapper.find('header p').exists()).toBe(false)
    expect(textoEncabezado(wrapper)).toContain('Recinto y palabra')
    expect(textoEncabezado(wrapper)).not.toContain('coordinación de dispositivos')
    expect(wrapper.text()).not.toContain('Distribución de bancas')
    // La altura recuperada queda para la grilla, que sigue presente.
    expect(wrapper.find('[data-testid="area-bancas-moderacion"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-testid="banca-concejal"]').length).toBe(3)
  })

  it('ofrece Remapear dispositivo dentro del área de acciones del encabezado', async () => {
    const wrapper = montar(PanelRecintoPalabra, {
      estado: crearEstado(),
      cliente: crearCliente(),
      conectado: true,
    })

    const encabezado = wrapper.get('header')
    expect(encabezado.find('[data-testid="btn-desplegar-remapeo"]').exists()).toBe(true)
    expect(
      wrapper
        .get('[data-testid="area-bancas-moderacion"]')
        .find('[data-testid="btn-desplegar-remapeo"]')
        .exists(),
    ).toBe(false)

    await encabezado.get('[data-testid="btn-desplegar-remapeo"]').trigger('click')
    expect(wrapper.find('[data-testid="panel-remapeo-desplegado"]').exists()).toBe(true)
    // Con el cajón abierto la acción se retira del encabezado para no duplicar el flujo.
    expect(encabezado.find('[data-testid="btn-desplegar-remapeo"]').exists()).toBe(false)
  })

  it('un remapeo autoritativo mantiene el flujo visible y sin posibilidad de cerrarlo', () => {
    const wrapper = montar(PanelRecintoPalabra, {
      estado: crearEstado({
        remapeo: {
          identificador_logico: 'dev02',
          banca: 2,
          iniciado_en: '2026-08-30T10:05:00Z',
          fingerprint_candidato: null,
        },
      } as Partial<EstadoModeracion>),
      cliente: crearCliente(),
      conectado: true,
    })

    expect(wrapper.find('[data-testid="panel-remapeo-desplegado"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="btn-cerrar-remapeo"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="btn-desplegar-remapeo"]').exists()).toBe(false)
  })

  it('no repite al orador como texto ni conserva el subtítulo de la cola', () => {
    const wrapper = montar(GestionPalabra, {
      estado: crearEstado({
        palabra: {
          orador: { dni: '1', nombre: 'Concejal1', apellido: 'Apellido1', banca: 1 },
          cola: [{ dni: '2', nombre: 'Concejal2', apellido: 'Apellido2', banca: 2 }],
        },
      }),
      cliente: crearCliente(),
      conectado: true,
    })

    expect(wrapper.find('[data-testid="orador-actual-texto"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('En uso:')
    expect(wrapper.text()).not.toContain('Sin orador activo')
    expect(wrapper.text()).not.toContain('Cola FIFO autoritativa')
    // La cola y su badge se conservan intactos.
    expect(wrapper.get('[data-testid="badge-cola-palabra"]').text()).toContain('1 en cola')
    expect(wrapper.get('[data-testid="pedido-palabra-1"]').text()).toContain('Concejal2')
  })

  it('el éxito de Otorgar/Quitar no deja mensaje informativo pero el error real sí se ve', async () => {
    const cliente = crearCliente()
    const wrapper = montar(GestionPalabra, {
      estado: crearEstado({
        palabra: {
          orador: null,
          cola: [{ dni: '2', nombre: 'Concejal2', apellido: 'Apellido2', banca: 2 }],
        },
      }),
      cliente,
      conectado: true,
    })

    await wrapper.get('[data-testid="btn-otorgar-palabra"]').trigger('click')
    await flushPromises()
    expect(cliente.otorgarPalabra).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[data-testid="aviso-palabra"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Comando enviado')

    await wrapper.get('[data-testid="btn-quitar-palabra"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="aviso-palabra"]').exists()).toBe(false)

    const clienteConFalla = crearCliente({
      quitarPalabra: vi.fn().mockRejectedValue({ mensajeBackend: 'Auditoría no disponible' }),
    })
    const conError = montar(GestionPalabra, {
      estado: crearEstado(),
      cliente: clienteConFalla,
      conectado: true,
    })
    await conError.get('[data-testid="btn-quitar-palabra"]').trigger('click')
    await flushPromises()
    expect(conError.get('[data-testid="error-palabra"]').text()).toContain(
      'Auditoría no disponible',
    )
  })
})

describe('WP-044 · Q4 Eventos recientes', () => {
  it('pierde el subtítulo y conserva selector, orden y consola de eventos', async () => {
    const eventos = [1, 2].map((seq) => ({
      seq,
      timestamp: `2026-08-30T10:00:0${seq}`,
      nivel: seq === 1 ? 'L2' : 'L3',
      etiqueta: 'OPERACION',
      codigo_evento: `EVENTO_${seq}`,
      mensaje: `Mensaje ${seq}`,
    }))
    const wrapper = montar(PanelEventos, {
      estado: crearEstado({ eventos_recientes: eventos } as Partial<EstadoModeracion>),
    })

    expect(wrapper.find('header p').exists()).toBe(false)
    expect(textoEncabezado(wrapper)).not.toContain('Registro de actividad')

    // El resto del cuadrante permanece igual: filtro acumulativo y evento más nuevo primero.
    expect(wrapper.findAll('[data-testid="evento-reciente"]')).toHaveLength(1)
    await wrapper.get('[data-testid="filtro-eventos"]').setValue('L2')
    const visibles = wrapper.findAll('[data-testid="evento-reciente"]')
    expect(visibles).toHaveLength(2)
    expect(visibles[0]?.text()).toContain('EVENTO_2')
  })
})
