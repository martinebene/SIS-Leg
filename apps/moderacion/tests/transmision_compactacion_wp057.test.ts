/**
 * Regresión de las dos correcciones operativas de Moderación aprobadas por WP-057.
 *
 * A. Indicador binario de transmisión en la cabecera.
 *    - `EN_VIVO` se lee `En vivo`; `APAGADO` y `CUENTA_REGRESIVA` se leen `Sin transmisión`.
 *      La agrupación es deliberada: mientras corre la cuenta regresiva todavía no hay
 *      emisión pública, así que Moderación no debe leer nada distinto de "no estamos al aire".
 *    - Sin snapshot todavía recibido, la cabecera no muestra el indicador en lugar de
 *      afirmar un estado que el backend no publicó.
 *    - El shell productivo proyecta ese valor desde `EstadoModeracion.tecnico.transmision`,
 *      es decir desde el mismo snapshot SSE: no hay consulta adicional ni reloj local que
 *      decida la transición.
 *
 * B. Compactación estructural de Q1.
 *    - Número, Tipo, Mayoría, Factor y Base pertenecen a una única fila del formulario.
 *      Antes Factor y Base formaban una segunda fila que sólo existía con mayoría ESPECIAL,
 *      y ese renglón extra era lo que empujaba los controles de apertura fuera del área
 *      visible cuando aún se mostraba el resultado de la votación anterior.
 *    - Elegir ESPECIAL no agrega ni quita ningún otro renglón al formulario.
 *    - La funcionalidad de mayoría SIMPLE y ESPECIAL se conserva intacta.
 *
 * La altura real, la ausencia de scroll y la contención de los controles dentro del
 * bounding box de Q1 se miden con Playwright: el DOM de estas pruebas no calcula layout.
 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { compile, ssrContextKey, type Component } from 'vue'
import { mount, type VueWrapper } from '@vue/test-utils'
import type {
  ApoyoTecnicoProyectado,
  ClienteModeracion,
  EstadoModeracion,
  EstadoTransmision,
} from '@sis-leg/api-client'
import App from '../app/app.vue'
import fuenteApp from '../app/app.vue?raw'
import CabeceraModeracion from '../app/components/CabeceraModeracion.vue'
import fuenteCabeceraModeracion from '../app/components/CabeceraModeracion.vue?raw'
import GestionVotacion from '../app/components/GestionVotacion.vue'
import fuenteGestionVotacion from '../app/components/GestionVotacion.vue?raw'
import DialogoConfirmacionApertura from '../app/components/DialogoConfirmacionApertura.vue'
import fuenteDialogoConfirmacionApertura from '../app/components/DialogoConfirmacionApertura.vue?raw'
import {
  reiniciarInstanciaCompartidaParaPruebas,
  useEstadoModeracion,
} from '../app/composables/useEstadoModeracion'

/**
 * Vitest compila los SFC para SSR. Este helper adjunta el render de cliente de la misma
 * plantilla productiva para poder inspeccionar el DOM real, sin duplicar lógica alguna.
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

habilitarRenderCliente(CabeceraModeracion, fuenteCabeceraModeracion)
habilitarRenderCliente(DialogoConfirmacionApertura, fuenteDialogoConfirmacionApertura)
habilitarRenderCliente(GestionVotacion, fuenteGestionVotacion, { DialogoConfirmacionApertura })

const wrappers: VueWrapper[] = []

afterEach(() => {
  while (wrappers.length) wrappers.pop()?.unmount()
  reiniciarInstanciaCompartidaParaPruebas()
})

/**
 * Lee un atributo del elemento real.
 *
 * El entorno de estas pruebas usa el DOM liviano propio del repositorio, cuya colección
 * `attributes` no es un `NamedNodeMap`; por eso se consulta `getAttribute` directamente
 * en lugar del helper de @vue/test-utils.
 */
function atributo(elemento: Element, nombre: string): string | null {
  return (elemento as unknown as { getAttribute(nombre: string): string | null }).getAttribute(
    nombre,
  )
}

/**
 * Devuelve el elemento padre.
 *
 * El DOM liviano de estas pruebas expone `parentNode` pero no `parentElement`; usar sólo
 * `parentElement` haría que las comparaciones se cumplieran comparando `undefined` contra
 * `undefined`, es decir sin verificar nada.
 */
function padre(elemento: Element): Element | null {
  const nodo = elemento as unknown as { parentElement?: Element; parentNode?: Element }
  return nodo.parentElement ?? nodo.parentNode ?? null
}

function montar(componente: Component, props: Record<string, unknown> = {}): VueWrapper {
  const wrapper = mount(componente, {
    props,
    global: { provide: { [ssrContextKey]: { modules: new Set() } } },
  })
  wrappers.push(wrapper)
  return wrapper
}

// ---------------------------------------------------------------------------
// A. Indicador binario de transmisión
// ---------------------------------------------------------------------------

/** Props mínimas obligatorias de la cabecera, para no repetirlas en cada caso. */
function propsCabecera(parcial: Record<string, unknown> = {}) {
  return {
    estadoConexion: 'CONECTADO',
    estadoGlobal: 'SESION_ABIERTA',
    revision: 7,
    desactualizado: false,
    generadoEn: '2026-09-03T12:30:15',
    fechaHoraApertura: '2026-09-03T12:00:00',
    numeroSesion: 57,
    ...parcial,
  }
}

describe('Cabecera de Moderación: indicador binario de transmisión (WP-057)', () => {
  it.each<[EstadoTransmision, string]>([
    ['EN_VIVO', 'En vivo'],
    ['APAGADO', 'Sin transmisión'],
    ['CUENTA_REGRESIVA', 'Sin transmisión'],
  ])('presenta %s como "%s"', (estadoTransmision, textoEsperado) => {
    const wrapper = montar(CabeceraModeracion, propsCabecera({ estadoTransmision }))

    const indicador = wrapper.get('[data-testid="cabecera-transmision"]')
    expect(indicador.text()).toBe(textoEsperado)
    // El estado autoritativo crudo queda publicado para que la evidencia no dependa
    // solamente del texto traducido.
    expect(atributo(indicador.element, 'data-estado-transmision')).toBe(estadoTransmision)
  })

  it('omite el indicador mientras el backend no proyectó ningún estado', () => {
    const wrapper = montar(CabeceraModeracion, propsCabecera({ estadoTransmision: null }))

    expect(wrapper.find('[data-testid="cabecera-transmision"]').exists()).toBe(false)
  })

  it('coloca el indicador inmediatamente antes del estado de conexión', () => {
    const wrapper = montar(CabeceraModeracion, propsCabecera({ estadoTransmision: 'EN_VIVO' }))

    const transmision = wrapper.get('[data-testid="cabecera-transmision"]').element
    const conexion = wrapper.get('[data-testid="estado-conexion"]').element

    // Misma caja contenedora y adyacencia directa: es el requisito "junto al indicador
    // de conexión" expresado de una forma verificable sin medir píxeles.
    expect(padre(transmision)).not.toBeNull()
    expect(padre(transmision)).toBe(padre(conexion))
    expect(transmision.nextElementSibling).toBe(conexion)
  })
})

// ---------------------------------------------------------------------------
// A bis. El shell proyecta la verdad autoritativa del snapshot
// ---------------------------------------------------------------------------

/** Porción técnica del snapshot con el estado de transmisión pedido. */
function crearTecnico(estado: EstadoTransmision): ApoyoTecnicoProyectado {
  return {
    transmision: {
      estado,
      iniciada_en: estado === 'APAGADO' ? null : '2026-09-03T12:00:00Z',
      en_vivo_desde: estado === 'APAGADO' ? null : '2026-09-03T12:00:10Z',
      cuenta_regresiva_segundos: estado === 'CUENTA_REGRESIVA' ? 10 : null,
      segundos_restantes: estado === 'CUENTA_REGRESIVA' ? 6 : null,
    },
    aviso: null,
  }
}

function crearEstadoConTecnico(tecnico: ApoyoTecnicoProyectado): EstadoModeracion {
  return {
    instancia: 'instancia-prueba',
    revision: 1,
    generado_en: '2026-09-03T12:30:15',
    estado_global: 'SESION_ABIERTA',
    sesion: {
      fecha_hora_inicio_preparacion: '2026-09-03T11:30:00',
      fecha_hora_apertura: '2026-09-03T12:00:00',
      numero_sesion: 57,
      presidencia: 'Dra. Presidencia',
      secretaria_legislativa: 'Sr. Secretaría',
    },
    concejales: [],
    eventos_recientes: [],
    tecnico,
  } as unknown as EstadoModeracion
}

/**
 * Monta el shell productivo sembrando la instancia compartida de `useEstadoModeracion`
 * con un cliente espía que no abre ninguna conexión. Así se comprueba el cableado real
 * entre el snapshot y la cabecera, sin red y sin reimplementar la plantilla.
 */
function montarShell(estadoInicial: EstadoTransmision): {
  wrapper: VueWrapper
  emitir: (estado: EstadoTransmision) => Promise<void>
} {
  let alEstado: ((estado: EstadoModeracion) => void) | null = null
  const cliente = {
    suscribirEstado: vi.fn((opciones: { alEstado: (estado: EstadoModeracion) => void }) => {
      alEstado = opciones.alEstado
      opciones.alEstado(crearEstadoConTecnico(crearTecnico(estadoInicial)))
      return { activa: true, cancelar: vi.fn() }
    }),
  } as unknown as ClienteModeracion

  useEstadoModeracion(cliente)

  habilitarRenderCliente(App, fuenteApp, { CabeceraModeracion })

  const wrapper = mount(App, {
    global: {
      provide: { [ssrContextKey]: { modules: new Set() } },
      stubs: {
        PanelSesionVotacion: true,
        PanelOrdenDelDia: true,
        PanelRecintoPalabra: true,
        PanelEventos: true,
        AvisoSuperficie: true,
      },
    },
  })
  wrappers.push(wrapper)

  return {
    wrapper,
    emitir: async (estado) => {
      alEstado?.(crearEstadoConTecnico(crearTecnico(estado)))
      await wrapper.vm.$nextTick()
    },
  }
}

describe('Shell de Moderación: transmisión proyectada desde el snapshot (WP-057)', () => {
  it('recorre los tres estados autoritativos sin timer ni consulta adicional', async () => {
    const { wrapper, emitir } = montarShell('APAGADO')

    const leer = () => wrapper.get('[data-testid="cabecera-transmision"]')
    expect(leer().text()).toBe('Sin transmisión')
    expect(atributo(leer().element, 'data-estado-transmision')).toBe('APAGADO')

    // Apoyo Técnico lanza la cuenta regresiva: todavía no hay emisión pública.
    await emitir('CUENTA_REGRESIVA')
    expect(leer().text()).toBe('Sin transmisión')
    expect(atributo(leer().element, 'data-estado-transmision')).toBe('CUENTA_REGRESIVA')

    // El cambio a EN_VIVO llega porque el backend republicó, no porque el frontend
    // haya contado los segundos por su cuenta.
    await emitir('EN_VIVO')
    expect(leer().text()).toBe('En vivo')
    expect(atributo(leer().element, 'data-estado-transmision')).toBe('EN_VIVO')
  })
})

// ---------------------------------------------------------------------------
// B. Compactación estructural de Q1
// ---------------------------------------------------------------------------

function crearCapacidadesVotacion(): EstadoModeracion['capacidades'] {
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

/** Sesión abierta con el resultado de la votación anterior todavía proyectado. */
function crearEstadoConResultadoAnterior(): EstadoModeracion {
  return {
    instancia: 'instancia-prueba',
    revision: 9,
    generado_en: '2026-09-03T12:30:15',
    estado_global: 'SESION_ABIERTA',
    preparacion: null,
    sesion: {
      fecha_hora_inicio_preparacion: '2026-09-03T11:30:00',
      fecha_hora_apertura: '2026-09-03T12:00:00',
      numero_sesion: 57,
      presidencia: 'Dra. Presidencia',
      secretaria_legislativa: 'Sr. Secretaría',
    },
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
    quorum: { cantidad_presentes: 8, requerido: 7, alcanzado: true },
    votacion: {
      id: 'votacion-anterior',
      numero_votacion: 12,
      tipo: 'Proyecto',
      tema: 'Expediente 4521-D-2026',
      tipo_mayoria: 'SIMPLE',
      factor: 0,
      base: 'VOTOS_COMPUTABLES',
      estado_recepcion: 'CERRADA',
      resultado: 'APROBADA',
      fecha_hora_apertura: '2026-09-03T12:10:00',
      fecha_hora_cierre: '2026-09-03T12:12:00',
      fecha_hora_resultado: '2026-09-03T12:12:00',
      motivo_finalizacion_manual: null,
      cantidad_votos_recibidos: 8,
      revelado_individual_desde: '2026-09-03T12:12:04',
      votos_individuales_revelados: true,
      votos_individuales: null,
      conteos: { positivos: 5, negativos: 2, abstenciones: 1, total: 8 },
      voto_presidencial: null,
    },
    palabra: { orador: null, cola: [] },
    orden_del_dia: [],
    eventos_recientes: [],
    capacidades: crearCapacidadesVotacion(),
    tecnico: crearTecnico('EN_VIVO'),
  } as unknown as EstadoModeracion
}

function crearClienteVotacion(): ClienteModeracion {
  return {
    abrirVotacion: vi.fn().mockResolvedValue({ id: 'nueva-votacion' }),
    finalizarVotacion: vi.fn().mockResolvedValue(undefined),
    desempatar: vi.fn().mockResolvedValue(undefined),
  } as unknown as ClienteModeracion
}

function montarGestionVotacion(): VueWrapper {
  return montar(GestionVotacion, {
    estado: crearEstadoConResultadoAnterior(),
    cliente: crearClienteVotacion(),
    conectado: true,
    puntoPreseleccionado: null,
  })
}

/**
 * Devuelve el hijo directo del formulario que contiene a un control dado.
 *
 * Se sube por `parentElement` en lugar de usar `closest`, que el DOM liviano de estas
 * pruebas no implementa. El resultado identifica el renglón del formulario al que
 * pertenece el control, que es exactamente lo que WP-057 unifica.
 */
function filaDe(wrapper: VueWrapper, testid: string): Element {
  const formulario = wrapper.get('[data-testid="formulario-votacion"]').element
  let actual: Element | null = wrapper.get(`[data-testid="${testid}"]`).element
  while (actual && padre(actual) !== formulario) {
    actual = padre(actual)
  }
  if (!actual) throw new Error(`El control ${testid} no está dentro de una fila del formulario`)
  return actual
}

describe('Q1: los cinco campos de mayoría comparten una fila (WP-057)', () => {
  it('deja Número, Tipo, Mayoría, Factor y Base en el mismo renglón del formulario', async () => {
    const wrapper = montarGestionVotacion()

    await wrapper.get('[data-testid="radio-mayoria-especial"]').setValue('ESPECIAL')

    // Todos los controles cuelgan del mismo hijo directo del formulario: eso es lo que
    // convierte la antigua segunda fila de mayoría especial en un tramo de la primera.
    const fila = filaDe(wrapper, 'input-numero-votacion')
    for (const control of [
      'select-tipo-votacion',
      'radio-mayoria-simple',
      'radio-mayoria-especial',
      'input-factor-mayoria',
      'select-base-mayoria',
    ]) {
      expect(filaDe(wrapper, control)).toBe(fila)
    }

    // El grupo condicional conserva su identidad, pero ahora es un tramo más de esa fila.
    const grupoEspecial = wrapper.get('[data-testid="campos-mayoria-especial"]').element
    expect(padre(grupoEspecial)).toBe(fila)
  })

  it('no agrega ni quita renglones al formulario al elegir mayoría ESPECIAL', async () => {
    const wrapper = montarGestionVotacion()
    const formulario = wrapper.get('[data-testid="formulario-votacion"]').element

    const renglonesConSimple = formulario.children.length
    await wrapper.get('[data-testid="radio-mayoria-especial"]').setValue('ESPECIAL')
    const renglonesConEspecial = formulario.children.length

    // Antes de WP-057 la mayoría especial sumaba una fila entera; ahora la estructura
    // vertical del formulario es idéntica en ambos casos.
    expect(renglonesConEspecial).toBe(renglonesConSimple)
  })

  it('conserva la funcionalidad de ambos tipos de mayoría', async () => {
    const wrapper = montarGestionVotacion()

    // SIMPLE no expone Factor ni Base: la regla no los usa.
    expect(wrapper.find('[data-testid="campos-mayoria-especial"]').exists()).toBe(false)

    await wrapper.get('[data-testid="radio-mayoria-especial"]').setValue('ESPECIAL')
    expect(wrapper.find('[data-testid="campos-mayoria-especial"]').exists()).toBe(true)

    await wrapper.get('[data-testid="input-factor-mayoria"]').setValue('0.66')
    await wrapper.get('[data-testid="select-base-mayoria"]').setValue('PRESENTES')
    expect(
      (wrapper.get('[data-testid="input-factor-mayoria"]').element as HTMLInputElement).value,
    ).toBe('0.66')
    expect(
      (wrapper.get('[data-testid="select-base-mayoria"]').element as HTMLSelectElement).value,
    ).toBe('PRESENTES')

    // Volver a SIMPLE retira los campos sin dejar residuos en la fila.
    await wrapper.get('[data-testid="radio-mayoria-simple"]').setValue('SIMPLE')
    expect(wrapper.find('[data-testid="campos-mayoria-especial"]').exists()).toBe(false)
  })

  it('mantiene visible el resultado anterior junto al formulario de la votación siguiente', () => {
    const wrapper = montarGestionVotacion()

    expect(wrapper.get('[data-testid="estado-votacion"]').text()).toBe('APROBADA')
    expect(wrapper.find('[data-testid="conteos-votacion"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="formulario-votacion"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="btn-abrir-votacion"]').exists()).toBe(true)
  })
})
