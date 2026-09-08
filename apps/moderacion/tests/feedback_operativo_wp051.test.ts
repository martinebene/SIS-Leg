/**
 * Regresión de las correcciones operativas de feedback y ciclo de votación de WP-051.
 *
 * Cada caso demuestra una decisión humana cerrada del Work Package sobre los componentes
 * productivos reales:
 *
 * - Los acuses puramente técnicos ("Apertura enviada…", "Finalización enviada…",
 *   "Desempate enviado…", "Inicio/Confirmación/Cancelación enviada…") ya no se muestran:
 *   el backend los audita y el snapshot autoritativo confirma su efecto.
 * - Las confirmaciones humanas no críticas se muestran como aviso efímero y caducan solas.
 * - Los errores reales siguen siendo visibles y accionables, sin caducidad.
 * - El motivo de finalización manual se vacía únicamente después de un comando aceptado.
 * - `QUORUM_INSUFICIENTE` se lee según la capacidad afectada: durante una sesión abierta
 *   impide abrir una votación, no "abrir la sesión".
 * - Un empate muestra la instrucción explícita a Presidencia antes de POSITIVO/NEGATIVO.
 *
 * Ninguna de estas decisiones cambia reglas institucionales: las mutaciones se simulan con
 * clientes falsos y los cambios de estado llegan siempre por `setProps`, nunca de forma
 * optimista desde el frontend.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { compile, type Component, ssrContextKey } from 'vue'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import type {
  ClienteModeracion,
  ConcejalModeracion,
  EstadoModeracion,
  VotacionModeracion,
} from '@sis-leg/api-client'
import PanelContenedor from '../app/components/PanelContenedor.vue'
import fuentePanelContenedor from '../app/components/PanelContenedor.vue?raw'
import PanelSesionVotacion from '../app/components/PanelSesionVotacion.vue'
import fuentePanelSesionVotacion from '../app/components/PanelSesionVotacion.vue?raw'
import GestionVotacion from '../app/components/GestionVotacion.vue'
import fuenteGestionVotacion from '../app/components/GestionVotacion.vue?raw'
import GestionRemapeo from '@sis-leg/frontend-shared/componentes/GestionRemapeo.vue'
import fuenteGestionRemapeo from '@sis-leg/frontend-shared/componentes/GestionRemapeo.vue?raw'
import DialogoConfirmacionApertura from '../app/components/DialogoConfirmacionApertura.vue'
import fuenteDialogoConfirmacionApertura from '../app/components/DialogoConfirmacionApertura.vue?raw'
import DialogoConfirmacionCierre from '../app/components/DialogoConfirmacionCierre.vue'
import fuenteDialogoConfirmacionCierre from '../app/components/DialogoConfirmacionCierre.vue?raw'
import DialogoEdicionAutoridades from '../app/components/DialogoEdicionAutoridades.vue'
import fuenteDialogoEdicionAutoridades from '../app/components/DialogoEdicionAutoridades.vue?raw'
import PanelOrdenDelDia from '../app/components/PanelOrdenDelDia.vue'
import fuentePanelOrdenDelDia from '../app/components/PanelOrdenDelDia.vue?raw'
import { reiniciarInstanciaCompartidaParaPruebas } from '../app/composables/useEstadoModeracion'
import { DURACION_AVISO_EFIMERO_MS, useAvisoEfimero } from '../app/composables/useAvisoEfimero'
import { traducirMotivo, traducirMotivos } from '../app/utils/motivos'

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
habilitarRenderCliente(GestionRemapeo, fuenteGestionRemapeo)
habilitarRenderCliente(PanelSesionVotacion, fuentePanelSesionVotacion, {
  PanelContenedor,
  GestionVotacion,
  DialogoConfirmacionCierre,
  DialogoEdicionAutoridades,
})
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

function crearEstado(parcial: Partial<EstadoModeracion> = {}): EstadoModeracion {
  return {
    instancia: 'instancia-prueba',
    revision: 1,
    generado_en: '2026-09-01T10:00:00Z',
    estado_global: 'SESION_ABIERTA',
    preparacion: null,
    sesion: {
      fecha_hora_inicio_preparacion: '2026-09-01T09:00:00Z',
      fecha_hora_apertura: '2026-09-01T09:30:00Z',
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

/** Estado PREPARANDO con los comandos preparatorios habilitados. */
function crearEstadoPreparando(): EstadoModeracion {
  return crearEstado({
    estado_global: 'PREPARANDO',
    sesion: null,
    preparacion: {
      fecha_hora_inicio: '2026-09-01T09:00:00Z',
      numero_sesion: 42,
      presidencia: 'Dra. Presidencia',
      secretaria_legislativa: 'Sr. Secretaría',
    },
    capacidades: {
      ...crearCapacidades(),
      actualizar_preparacion: { habilitada: true, motivos: [] },
      cancelar_preparacion: { habilitada: true, motivos: [] },
      actualizar_sesion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      cerrar_sesion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      abrir_votacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
    },
  })
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
    estado_recepcion: 'EN_CURSO',
    resultado: null,
    fecha_hora_apertura: '2026-09-01T10:00:00Z',
    fecha_hora_cierre: null,
    fecha_hora_resultado: null,
    motivo_finalizacion_manual: null,
    cantidad_votos_recibidos: 2,
    revelado_individual_desde: null,
    votos_individuales_revelados: false,
    votos_individuales: null,
    conteos: null,
    voto_presidencial: null,
    ...parcial,
  }
}

/** Sesión con una votación EN_CURSO y la finalización manual habilitada. */
function crearEstadoConVotacionEnCurso(): EstadoModeracion {
  return crearEstado({
    votacion: crearVotacion(),
    capacidades: {
      ...crearCapacidades(),
      abrir_votacion: { habilitada: false, motivos: ['VOTACION_PENDIENTE'] },
      finalizar_votacion: { habilitada: true, motivos: [] },
    },
  })
}

/** Mayoría simple cerrada en empate, con el desempate presidencial habilitado. */
function crearEstadoEmpatado(): EstadoModeracion {
  return crearEstado({
    votacion: crearVotacion({
      estado_recepcion: 'CERRADA',
      resultado: 'EMPATADA',
      fecha_hora_cierre: '2026-09-01T10:05:00Z',
      fecha_hora_resultado: '2026-09-01T10:05:00Z',
      cantidad_votos_recibidos: 2,
      conteos: { positivos: 1, negativos: 1, abstenciones: 0, total: 2 },
    }),
    capacidades: {
      ...crearCapacidades(),
      abrir_votacion: { habilitada: false, motivos: ['VOTACION_PENDIENTE'] },
      desempatar: { habilitada: true, motivos: [] },
    },
  })
}

function crearCliente(parcial: Partial<ClienteModeracion> = {}): ClienteModeracion {
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

beforeEach(() => reiniciarInstanciaCompartidaParaPruebas())

afterEach(() => {
  while (montados.length > 0) montados.pop()?.unmount()
  document.body.textContent = ''
  vi.useRealTimers()
})

describe('WP-051 · caducidad del feedback no crítico', () => {
  it('useAvisoEfimero muestra, reemplaza y apaga solo un aviso por vez', () => {
    vi.useFakeTimers()
    const aviso = useAvisoEfimero(1000)

    aviso.mostrar('Primero')
    expect(aviso.mensaje.value).toBe('Primero')

    // Reemplazar reinicia la cuenta: el temporizador viejo no puede apagar el aviso nuevo.
    vi.advanceTimersByTime(900)
    aviso.mostrar('Segundo')
    vi.advanceTimersByTime(900)
    expect(aviso.mensaje.value).toBe('Segundo')

    vi.advanceTimersByTime(100)
    expect(aviso.mensaje.value).toBeNull()
  })

  it('useAvisoEfimero permite apagar el aviso a mano antes de su caducidad', () => {
    vi.useFakeTimers()
    const aviso = useAvisoEfimero(1000)

    aviso.mostrar('Visible')
    aviso.limpiar()
    expect(aviso.mensaje.value).toBeNull()

    // El temporizador cancelado tampoco puede reescribir el estado más tarde.
    expect(() => vi.advanceTimersByTime(2000)).not.toThrow()
    expect(aviso.mensaje.value).toBeNull()
  })

  it('Q1: guardar la preparación confirma con un aviso breve que caduca solo', async () => {
    vi.useFakeTimers()
    const wrapper = montar(PanelSesionVotacion, {
      estado: crearEstadoPreparando(),
      clienteInyectado: crearCliente(),
    })

    await wrapper.get('[data-testid="btn-guardar-preparacion"]').trigger('click')
    await flushPromises()

    const aviso = wrapper.get('[data-testid="alerta-exito-comando"]')
    expect(aviso.text()).toContain('Datos de preparación guardados')
    // El acuse técnico anterior desaparece por completo del cuadrante.
    expect(wrapper.text()).not.toContain('enviados correctamente')

    vi.advanceTimersByTime(DURACION_AVISO_EFIMERO_MS - 1)
    await flushPromises()
    expect(wrapper.find('[data-testid="alerta-exito-comando"]').exists()).toBe(true)

    vi.advanceTimersByTime(1)
    await flushPromises()
    expect(wrapper.find('[data-testid="alerta-exito-comando"]').exists()).toBe(false)
  })

  it('Q1: un error de preparación permanece visible sin caducidad', async () => {
    vi.useFakeTimers()
    const actualizarPreparacion = vi.fn().mockRejectedValue({ mensaje: 'Número ya utilizado' })
    const wrapper = montar(PanelSesionVotacion, {
      estado: crearEstadoPreparando(),
      clienteInyectado: crearCliente({ actualizarPreparacion }),
    })

    await wrapper.get('[data-testid="btn-guardar-preparacion"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="alerta-error-comando"]').text()).toContain(
      'Número ya utilizado',
    )
    expect(wrapper.find('[data-testid="alerta-exito-comando"]').exists()).toBe(false)

    // Un error accionable no desaparece con el paso del tiempo: se resuelve o se cierra.
    vi.advanceTimersByTime(DURACION_AVISO_EFIMERO_MS * 4)
    await flushPromises()
    expect(wrapper.find('[data-testid="alerta-error-comando"]').exists()).toBe(true)
  })

  it('Q2: descartar el Orden del Día deja una confirmación breve, no un acuse fijo', async () => {
    vi.useFakeTimers()
    const wrapper = montar(PanelOrdenDelDia, {
      estado: crearEstado({
        orden_del_dia: [
          {
            nro_votacion: 7,
            tipo: 'Proyecto',
            tema: 'Presupuesto anual',
            tipo_mayoria: 'SIMPLE',
            factor: 0,
            base: 'VOTOS_COMPUTABLES',
          },
        ],
      }),
      clienteInyectado: crearCliente(),
    })

    await wrapper.get('[data-testid="btn-quitar-orden-dia"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="aviso-orden-dia"]').text()).toContain(
      'Orden del Día descartado',
    )
    expect(wrapper.text()).not.toContain('Descarte enviado')

    vi.advanceTimersByTime(1000)
    await flushPromises()
    expect(wrapper.find('[data-testid="aviso-orden-dia"]').exists()).toBe(false)
  })
})

describe('WP-051 · acuses técnicos retirados de la interfaz', () => {
  it('Q1: abrir una votación no deja ningún aviso de tránsito', async () => {
    const wrapper = montar(GestionVotacion, {
      estado: crearEstado(),
      cliente: crearCliente(),
      conectado: true,
      puntoPreseleccionado: null,
    })

    await wrapper.get('[data-testid="input-numero-votacion"]').setValue('7')
    await wrapper.get('[data-testid="input-tema-votacion"]').setValue('Presupuesto anual')
    await wrapper.get('[data-testid="btn-abrir-votacion"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="aviso-votacion"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Apertura enviada')
  })

  it('Q1: finalizar y desempatar tampoco dejan acuses técnicos visibles', async () => {
    const finalizar = vi.fn().mockResolvedValue(undefined)
    const wrapper = montar(GestionVotacion, {
      estado: crearEstadoConVotacionEnCurso(),
      cliente: crearCliente({ finalizarVotacion: finalizar }),
      conectado: true,
      puntoPreseleccionado: null,
    })

    await wrapper.get('[data-testid="input-motivo-finalizacion"]').setValue('Moción previa')
    await wrapper.get('[data-testid="btn-finalizar-votacion"]').trigger('click')
    await flushPromises()

    expect(finalizar).toHaveBeenCalledWith('votacion-1', 'Moción previa')
    expect(wrapper.find('[data-testid="aviso-votacion"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Finalización enviada')

    // El desempate se ejerce sobre el mismo componente, ya con la votación empatada.
    await wrapper.setProps({ estado: crearEstadoEmpatado() })
    await wrapper.get('[data-testid="btn-desempate-positivo"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="aviso-votacion"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Desempate enviado')
  })

  it('Q1: un error real de la votación sigue siendo visible', async () => {
    const abrirVotacion = vi.fn().mockRejectedValue({ mensaje: 'Tipo no permitido' })
    const wrapper = montar(GestionVotacion, {
      estado: crearEstado(),
      cliente: crearCliente({ abrirVotacion }),
      conectado: true,
      puntoPreseleccionado: null,
    })

    await wrapper.get('[data-testid="input-numero-votacion"]').setValue('7')
    await wrapper.get('[data-testid="input-tema-votacion"]').setValue('Presupuesto anual')
    await wrapper.get('[data-testid="btn-abrir-votacion"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="alerta-error-votacion"]').text()).toContain(
      'Tipo no permitido',
    )
  })

  it('Q4: el remapeo no acusa el tránsito de sus comandos pero sí sus errores', async () => {
    const iniciarRemapeo = vi.fn().mockResolvedValue({})
    const wrapper = montar(GestionRemapeo, {
      estado: crearEstado(),
      cliente: crearCliente({ iniciarRemapeo }),
      conectado: true,
    })

    await wrapper.get('[data-testid="selector-banca-remapeo"]').setValue('dev01')
    await wrapper.get('[data-testid="btn-iniciar-remapeo"]').trigger('click')
    await flushPromises()

    expect(iniciarRemapeo).toHaveBeenCalledWith('dev01')
    expect(wrapper.find('[data-testid="aviso-remapeo"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Inicio enviado')

    iniciarRemapeo.mockRejectedValueOnce({ mensaje: 'Bridge no disponible' })
    await wrapper.get('[data-testid="btn-iniciar-remapeo"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="error-remapeo"]').text()).toContain('Bridge no disponible')
  })
})

describe('WP-051 · ciclo de votación legible', () => {
  it('el motivo de finalización se vacía solo después de un comando aceptado', async () => {
    const finalizar = vi.fn().mockRejectedValueOnce({ mensaje: 'Finalización rechazada' })
    const wrapper = montar(GestionVotacion, {
      estado: crearEstadoConVotacionEnCurso(),
      cliente: crearCliente({ finalizarVotacion: finalizar }),
      conectado: true,
      puntoPreseleccionado: null,
    })

    const campo = wrapper.get('[data-testid="input-motivo-finalizacion"]')
    await campo.setValue('Moción previa')
    await wrapper.get('[data-testid="btn-finalizar-votacion"]').trigger('click')
    await flushPromises()

    // Comando rechazado: el texto tipeado se conserva para reintentar sin reescribirlo.
    expect(wrapper.get('[data-testid="alerta-error-votacion"]').text()).toContain(
      'Finalización rechazada',
    )
    expect((campo.element as HTMLInputElement).value).toBe('Moción previa')

    finalizar.mockResolvedValueOnce(undefined)
    await wrapper.get('[data-testid="btn-finalizar-votacion"]').trigger('click')
    await flushPromises()

    expect((campo.element as HTMLInputElement).value).toBe('')
  })

  it('la pérdida de quórum durante la sesión habla de la votación, no de abrir la sesión', () => {
    const estado = crearEstado({
      capacidades: {
        ...crearCapacidades(),
        abrir_votacion: { habilitada: false, motivos: ['QUORUM_INSUFICIENTE'] },
      },
    })
    const wrapper = montar(GestionVotacion, {
      estado,
      cliente: crearCliente(),
      conectado: true,
      puntoPreseleccionado: null,
    })

    const texto = wrapper.text()
    expect(texto).toContain('Quórum insuficiente para abrir una votación.')
    expect(texto).not.toContain('para abrir la sesión')
  })

  it('el empate instruye explícitamente a Presidencia antes de ofrecer los botones', () => {
    const wrapper = montar(GestionVotacion, {
      estado: crearEstadoEmpatado(),
      cliente: crearCliente(),
      conectado: true,
      puntoPreseleccionado: null,
    })

    const bloque = wrapper.get('[data-testid="controles-desempate"]')
    expect(wrapper.get('[data-testid="instruccion-desempate"]').text()).toBe(
      'Votación empatada. La Presidencia debe emitir el voto de desempate:',
    )

    // La instrucción precede a POSITIVO/NEGATIVO: se lee antes de poder actuar.
    const texto = bloque.text()
    expect(texto.indexOf('voto de desempate:')).toBeLessThan(texto.indexOf('POSITIVO'))

    // La autoridad sobre el desempate sigue siendo la capacidad del backend.
    const boton = wrapper.get('[data-testid="btn-desempate-positivo"]').element
    expect((boton as HTMLButtonElement).disabled).toBe(false)
  })

  it('el bloque de empate respeta una capacidad deshabilitada por el backend', () => {
    const estado = crearEstadoEmpatado()
    const wrapper = montar(GestionVotacion, {
      estado: {
        ...estado,
        capacidades: {
          ...estado.capacidades,
          desempatar: { habilitada: false, motivos: ['DESEMPATE_YA_EMITIDO'] },
        },
      },
      cliente: crearCliente(),
      conectado: true,
      puntoPreseleccionado: null,
    })

    expect(wrapper.get('[data-testid="instruccion-desempate"]').exists()).toBe(true)
    const boton = wrapper.get('[data-testid="btn-desempate-positivo"]').element
    expect((boton as HTMLButtonElement).disabled).toBe(true)
  })
})

describe('WP-051 · traducción contextual de motivos', () => {
  it('traducirMotivo distingue el contexto de la capacidad afectada', () => {
    expect(traducirMotivo('QUORUM_INSUFICIENTE')).toBe('Quórum insuficiente para abrir la sesión.')
    expect(traducirMotivo('QUORUM_INSUFICIENTE', 'abrir_votacion')).toBe(
      'Quórum insuficiente para abrir una votación.',
    )
  })

  it('un contexto sin redacción propia conserva la traducción general', () => {
    expect(traducirMotivo('PRESIDENCIA_REQUERIDA', 'abrir_votacion')).toBe(
      traducirMotivo('PRESIDENCIA_REQUERIDA'),
    )
    expect(
      traducirMotivos(['QUORUM_INSUFICIENTE', 'VOTACION_PENDIENTE'], 'abrir_votacion'),
    ).toEqual([
      'Quórum insuficiente para abrir una votación.',
      'No se puede cerrar la sesión con una votación en curso o pendiente de desempate.',
    ])
  })
})
