/**
 * Regresión interactiva de WP-023 sobre componentes Vue reales.
 *
 * Los casos disparan eventos DOM para demostrar que los gates, modales y borradores
 * ejecutan la misma ruta que usaría el operador. Los cambios institucionales se simulan
 * únicamente mediante `setProps`, equivalente a adoptar un nuevo snapshot/SSE.
 */

import { compile, type Component, ssrContextKey } from 'vue'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type {
  ClienteModeracion,
  EstadoModeracion,
  PuntoOrdenDelDiaProyectado,
  VotacionModeracion,
} from '@sis-leg/api-client'
import DialogoConfirmacionApertura from '../app/components/DialogoConfirmacionApertura.vue'
import fuenteDialogoConfirmacionApertura from '../app/components/DialogoConfirmacionApertura.vue?raw'
import GestionVotacion from '../app/components/GestionVotacion.vue'
import fuenteGestionVotacion from '../app/components/GestionVotacion.vue?raw'
import PanelContenedor from '../app/components/PanelContenedor.vue'
import fuentePanelContenedor from '../app/components/PanelContenedor.vue?raw'
import PanelOrdenDelDia from '../app/components/PanelOrdenDelDia.vue'
import fuentePanelOrdenDelDia from '../app/components/PanelOrdenDelDia.vue?raw'
import { reiniciarInstanciaCompartidaParaPruebas } from '../app/composables/useEstadoModeracion'

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
habilitarRenderCliente(DialogoConfirmacionApertura, fuenteDialogoConfirmacionApertura)
habilitarRenderCliente(GestionVotacion, fuenteGestionVotacion, {
  DialogoConfirmacionApertura,
})
habilitarRenderCliente(PanelOrdenDelDia, fuentePanelOrdenDelDia, { PanelContenedor })

const montados: VueWrapper[] = []

function montar(componente: Component, props: Record<string, unknown>): VueWrapper {
  const wrapper = mount(componente, {
    props,
    global: {
      provide: { [ssrContextKey]: { modules: new Set() } },
    },
  })
  montados.push(wrapper)
  return wrapper
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
  nro_votacion: 7,
  tipo: 'Moción',
  tema: 'Modificación del reglamento',
  tipo_mayoria: 'ESPECIAL',
  factor: 0.66,
  base: 'CUERPO',
  tratado: false,
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
    fecha_hora_apertura: '2026-08-26T10:00:00Z',
    fecha_hora_cierre: null,
    fecha_hora_resultado: null,
    motivo_finalizacion_manual: null,
    cantidad_votos_recibidos: 2,
    revelado_individual_desde: '2026-08-26T10:00:04Z',
    votos_individuales_revelados: false,
    votos_individuales: null,
    conteos: null,
    voto_presidencial: null,
    ...parcial,
  }
}

function crearEstado(parcial: Partial<EstadoModeracion> = {}): EstadoModeracion {
  return {
    instancia: 'instancia-prueba',
    revision: 1,
    generado_en: '2026-08-26T10:00:01Z',
    estado_global: 'SESION_ABIERTA',
    preparacion: null,
    sesion: {
      fecha_hora_inicio_preparacion: '2026-08-26T09:30:00Z',
      fecha_hora_apertura: '2026-08-26T09:45:00Z',
      numero_sesion: 42,
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
    votacion: null,
    palabra: { orador: null, cola: [] },
    orden_del_dia: [],
    eventos_recientes: [],
    auditoria: {
      activa: true,
      disponible: true,
      fallado: false,
      cerrado: false,
      motivo: null,
    },
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
    cargarOrdenDelDia: vi.fn().mockResolvedValue({ puntos: [] }),
    descartarOrdenDelDia: vi.fn().mockResolvedValue(undefined),
    abrirVotacion: vi.fn().mockResolvedValue({ id: 'nueva-votacion' }),
    finalizarVotacion: vi.fn().mockResolvedValue(undefined),
    desempatar: vi.fn().mockResolvedValue(undefined),
    suscribirEstado: vi.fn((opciones) => {
      opciones.alCambiarConexion?.(true)
      return { activa: true, cancelar: vi.fn() }
    }),
    ...parcial,
  } as unknown as ClienteModeracion
}

async function completarFormularioSimple(wrapper: VueWrapper): Promise<void> {
  await wrapper.get('[data-testid="input-numero-votacion"]').setValue('9')
  await wrapper.get('[data-testid="select-tipo-votacion"]').setValue('Proyecto')
  await wrapper.get('[data-testid="input-tema-votacion"]').setValue('Tema manual')
}

/**
 * Reproduce la elección real de un archivo sobre el input nativo. JSDOM no abre el
 * selector del sistema operativo, por eso la prueba instala la lista y dispara el
 * mismo evento `change` que recibe el componente en el navegador.
 */
async function seleccionarArchivoOrdenDelDia(
  wrapper: VueWrapper,
  nombre = 'orden.csv',
): Promise<File> {
  const archivo = new File(['nro_votacion,tipo,tema,tipo_mayoria,factor,base'], nombre, {
    type: 'text/csv',
  })
  const entrada = wrapper.get('[data-testid="input-archivo-orden-dia"]')
  Object.defineProperty(entrada.element, 'files', { configurable: true, value: [archivo] })
  await entrada.trigger('change')
  return archivo
}

describe('WP-023: Orden del Día y ciclo visual de votaciones', () => {
  beforeEach(() => reiniciarInstanciaCompartidaParaPruebas())

  afterEach(() => {
    while (montados.length) montados.pop()?.unmount()
    document.body.textContent = ''
  })

  it('muestra una carga CSV compacta y habilita Cargar al elegir un archivo', async () => {
    const cargar = vi.fn().mockResolvedValue({ puntos: [] })
    const wrapper = montar(PanelOrdenDelDia, {
      estado: crearEstado({ orden_del_dia: [] }),
      clienteInyectado: crearCliente({ cargarOrdenDelDia: cargar }),
    })

    expect(wrapper.get('[data-testid="carga-orden-dia"]').exists()).toBe(true)
    expect(wrapper.get('[data-testid="input-archivo-orden-dia"]').exists()).toBe(true)
    expect(wrapper.get('[data-testid="btn-cargar-orden-dia"]').text()).toBe('Cargar')
    expect(
      (wrapper.get('[data-testid="btn-cargar-orden-dia"]').element as HTMLButtonElement).disabled,
    ).toBe(true)
    expect(wrapper.find('[data-testid="btn-quitar-orden-dia"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Orden del Día opcional')
    expect(wrapper.text()).not.toContain('Podés cargar un CSV')

    await seleccionarArchivoOrdenDelDia(wrapper, 'sesion-42.csv')

    // WP-044: el nombre del archivo se ve una sola vez, en el input nativo.
    expect(wrapper.text()).not.toContain('Seleccionado: sesion-42.csv')
    expect(wrapper.text()).not.toContain('sesion-42.csv')
    expect(
      (wrapper.get('[data-testid="btn-cargar-orden-dia"]').element as HTMLButtonElement).disabled,
    ).toBe(false)
  })

  it('carga sin optimismo, muestra errores y adopta los puntos solo desde un snapshot', async () => {
    const cargar = vi.fn().mockResolvedValueOnce({ puntos: [puntoSimple] })
    const wrapper = montar(PanelOrdenDelDia, {
      estado: crearEstado({ orden_del_dia: [] }),
      clienteInyectado: crearCliente({ cargarOrdenDelDia: cargar }),
    })

    const archivo = await seleccionarArchivoOrdenDelDia(wrapper)
    await wrapper.get('[data-testid="btn-cargar-orden-dia"]').trigger('click')
    await flushPromises()

    expect(cargar).toHaveBeenCalledWith(archivo)
    expect(wrapper.findAll('[data-testid="punto-orden-dia"]')).toHaveLength(0)
    expect(wrapper.get('[data-testid="carga-orden-dia"]').exists()).toBe(true)
    // WP-048: el envío exitoso no deja acuse propio. La ausencia de puntos sigue siendo
    // fiel al backend y la confirmación llegará como colección proyectada, no como texto.
    expect(wrapper.find('[data-testid="aviso-orden-dia"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('backend proyecte la colección confirmada')

    cargar.mockRejectedValueOnce({ mensaje: 'CSV inválido' })
    await seleccionarArchivoOrdenDelDia(wrapper, 'invalido.csv')
    await wrapper.get('[data-testid="btn-cargar-orden-dia"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-testid="alerta-error-orden-dia"]').text()).toContain('CSV inválido')
    expect(wrapper.findAll('[data-testid="punto-orden-dia"]')).toHaveLength(0)

    await wrapper.setProps({
      estado: crearEstado({ revision: 2, orden_del_dia: [puntoSimple, puntoEspecial] }),
    })
    expect(wrapper.find('[data-testid="input-archivo-orden-dia"]').exists()).toBe(false)
    expect(wrapper.findAll('[data-testid="punto-orden-dia"]')).toHaveLength(2)
  })

  it('muestra solo puntos y Quitar Orden del Día, con tarjetas informativas clickeables', async () => {
    const wrapper = montar(PanelOrdenDelDia, {
      estado: crearEstado({ orden_del_dia: [puntoSimple, puntoEspecial] }),
      clienteInyectado: crearCliente(),
    })

    expect(wrapper.find('[data-testid="input-archivo-orden-dia"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="btn-cargar-orden-dia"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Reemplazar')
    expect(wrapper.findAll('[data-testid="btn-quitar-orden-dia"]')).toHaveLength(1)
    expect(wrapper.get('[data-testid="btn-quitar-orden-dia"]').text()).toBe('Quitar Orden del Día')

    const puntos = wrapper.findAll('[data-testid="punto-orden-dia"]')
    expect(puntos).toHaveLength(2)
    expect(puntos[1]?.text()).toContain('Factor 0.66 · Base CUERPO')
    expect(wrapper.text()).not.toContain('Seleccionar y copiar al borrador')
    await puntos[1]?.trigger('click')
    expect(wrapper.emitted('seleccionar')?.[0]?.[0]).toEqual(puntoEspecial)
    expect(wrapper.findAll('[data-testid="punto-orden-dia"]')).toHaveLength(2)
  })

  it('bloquea doble descarte, conserva puntos ante error y vuelve a carga por snapshot vacío', async () => {
    let rechazarDescarte: ((motivo: unknown) => void) | undefined
    const descartar = vi.fn(
      () =>
        new Promise<void>((_resolver, rechazar) => {
          rechazarDescarte = rechazar
        }),
    )
    const wrapper = montar(PanelOrdenDelDia, {
      estado: crearEstado({ orden_del_dia: [puntoSimple, puntoEspecial] }),
      clienteInyectado: crearCliente({ descartarOrdenDelDia: descartar }),
    })

    const boton = wrapper.get('[data-testid="btn-quitar-orden-dia"]')
    await boton.trigger('click')
    await boton.trigger('click')

    expect(descartar).toHaveBeenCalledTimes(1)
    expect((boton.element as HTMLButtonElement).disabled).toBe(true)
    expect(boton.text()).toBe('Quitando...')
    expect(wrapper.findAll('[data-testid="punto-orden-dia"]')).toHaveLength(2)

    rechazarDescarte?.({ mensaje: 'Descarte rechazado' })
    await flushPromises()
    expect(wrapper.get('[data-testid="alerta-error-orden-dia"]').text()).toContain(
      'Descarte rechazado',
    )
    expect(wrapper.findAll('[data-testid="punto-orden-dia"]')).toHaveLength(2)

    descartar.mockResolvedValueOnce(undefined)
    await wrapper.get('[data-testid="btn-quitar-orden-dia"]').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-testid="punto-orden-dia"]')).toHaveLength(2)

    await wrapper.setProps({ estado: crearEstado({ revision: 2, orden_del_dia: [] }) })
    expect(wrapper.get('[data-testid="carga-orden-dia"]').exists()).toBe(true)
    expect(wrapper.get('[data-testid="input-archivo-orden-dia"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="btn-quitar-orden-dia"]').exists()).toBe(false)
  })

  it('reemplaza por completo la colección al reconectar y respeta conexión y capacidades', async () => {
    const clienteDesconectado = crearCliente({
      suscribirEstado: vi.fn(() => ({ activa: true, cancelar: vi.fn() })),
    })
    const capacidadesBloqueadas = {
      ...crearEstado().capacidades,
      cargar_orden_del_dia: { habilitada: false, motivos: ['AUDITORIA_NO_DISPONIBLE'] },
      descartar_orden_del_dia: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
    }
    const wrapper = montar(PanelOrdenDelDia, {
      estado: crearEstado({ orden_del_dia: [], capacidades: capacidadesBloqueadas }),
      clienteInyectado: clienteDesconectado,
    })

    await seleccionarArchivoOrdenDelDia(wrapper)
    expect(wrapper.text()).toContain('recuperar la conexión confirmada')
    expect(wrapper.text()).toContain('auditoría institucional no está disponible')
    expect(
      (wrapper.get('[data-testid="btn-cargar-orden-dia"]').element as HTMLButtonElement).disabled,
    ).toBe(true)

    await wrapper.setProps({
      estado: crearEstado({
        revision: 2,
        orden_del_dia: [puntoSimple],
        capacidades: capacidadesBloqueadas,
      }),
    })
    expect(wrapper.text()).toContain('Presupuesto anual')
    expect(wrapper.text()).toContain('estado actual del sistema no permite')
    expect(
      (wrapper.get('[data-testid="btn-quitar-orden-dia"]').element as HTMLButtonElement).disabled,
    ).toBe(true)

    await wrapper.setProps({
      estado: crearEstado({ revision: 3, orden_del_dia: [puntoEspecial] }),
    })
    expect(wrapper.text()).not.toContain('Presupuesto anual')
    expect(wrapper.text()).toContain('Modificación del reglamento')

    await wrapper.setProps({ estado: crearEstado({ revision: 4, orden_del_dia: [] }) })
    expect(wrapper.get('[data-testid="carga-orden-dia"]').exists()).toBe(true)
  })

  it('abre una votación manual SIMPLE sin Orden del Día y valida el número estrictamente', async () => {
    const abrir = vi.fn().mockResolvedValue({ id: 'votacion-manual' })
    const wrapper = montar(GestionVotacion, {
      estado: crearEstado(),
      cliente: crearCliente({ abrirVotacion: abrir }),
      conectado: true,
      puntoPreseleccionado: null,
    })

    await completarFormularioSimple(wrapper)
    expect(wrapper.find('[data-testid="campos-mayoria-especial"]').exists()).toBe(false)
    await wrapper.get('[data-testid="btn-abrir-votacion"]').trigger('click')
    await flushPromises()
    expect(abrir).toHaveBeenCalledWith({
      numero_votacion: 9,
      tipo: 'Proyecto',
      tema: 'Tema manual',
      tipo_mayoria: 'SIMPLE',
      base: 'VOTOS_COMPUTABLES',
    })

    abrir.mockClear()
    await wrapper.get('[data-testid="input-numero-votacion"]').setValue('9.5')
    await wrapper.get('[data-testid="btn-abrir-votacion"]').trigger('click')
    expect(abrir).not.toHaveBeenCalled()
    expect(wrapper.get('[data-testid="alerta-error-votacion"]').text()).toContain('entero estricto')
  })

  it('copia un punto al formulario editable y valida factor/base de mayoría ESPECIAL', async () => {
    const abrir = vi.fn().mockResolvedValue({ id: 'especial-1' })
    const wrapper = montar(GestionVotacion, {
      estado: crearEstado(),
      cliente: crearCliente({ abrirVotacion: abrir }),
      conectado: true,
      puntoPreseleccionado: puntoEspecial,
    })
    await wrapper.setProps({ puntoPreseleccionado: { ...puntoEspecial } })

    expect(wrapper.get('[data-testid="input-numero-votacion"]').element).toHaveProperty(
      'value',
      '7',
    )
    expect(wrapper.get('[data-testid="campos-mayoria-especial"]').exists()).toBe(true)
    await wrapper.get('[data-testid="input-tema-votacion"]').setValue('Tema editado')
    await wrapper.get('[data-testid="input-factor-mayoria"]').setValue('0x1')
    await wrapper.get('[data-testid="btn-abrir-votacion"]').trigger('click')
    expect(abrir).not.toHaveBeenCalled()

    await wrapper.get('[data-testid="input-factor-mayoria"]').setValue('0.75')
    await wrapper.get('[data-testid="select-base-mayoria"]').setValue('PRESENTES')
    await wrapper.get('[data-testid="btn-abrir-votacion"]').trigger('click')
    await flushPromises()
    expect(abrir).toHaveBeenCalledWith({
      numero_votacion: 7,
      tipo: 'Moción',
      tema: 'Tema editado',
      tipo_mayoria: 'ESPECIAL',
      factor: 0.75,
      base: 'PRESENTES',
    })
  })

  it('aplica CA-062 con orador/cola, permite cancelar y evita confirmaciones duplicadas', async () => {
    let resolverApertura: ((valor: { id: string }) => void) | undefined
    const abrir = vi.fn(
      () =>
        new Promise<{ id: string }>((resolver) => {
          resolverApertura = resolver
        }),
    )
    const estadoConPalabra = crearEstado({
      palabra: {
        orador: { dni: '1', nombre: 'Ada', apellido: 'Lovelace', banca: 1 },
        cola: [{ dni: '2', nombre: 'Grace', apellido: 'Hopper', banca: 2 }],
      },
    })
    const wrapper = montar(GestionVotacion, {
      estado: estadoConPalabra,
      cliente: crearCliente({ abrirVotacion: abrir }),
      conectado: true,
      puntoPreseleccionado: null,
    })
    await completarFormularioSimple(wrapper)

    await wrapper.get('[data-testid="btn-abrir-votacion"]').trigger('click')
    expect(wrapper.get('[data-testid="dialogo-confirmacion-apertura"]').exists()).toBe(true)
    await wrapper.get('[data-testid="btn-cancelar-apertura"]').trigger('click')
    expect(abrir).not.toHaveBeenCalled()

    await wrapper.setProps({
      estado: crearEstado({
        palabra: {
          orador: null,
          cola: [{ dni: '2', nombre: 'Grace', apellido: 'Hopper', banca: 2 }],
        },
      }),
    })
    await wrapper.get('[data-testid="btn-abrir-votacion"]').trigger('click')
    expect(wrapper.get('[data-testid="apertura-cola-pendiente"]').text()).toContain('1')
    const confirmar = wrapper.get('[data-testid="btn-confirmar-apertura"]')
    await confirmar.trigger('click')
    await confirmar.trigger('click')
    expect(abrir).toHaveBeenCalledTimes(1)
    expect(estadoConPalabra.palabra?.orador?.nombre).toBe('Ada')
    expect(estadoConPalabra.palabra?.cola).toHaveLength(1)
    resolverApertura?.({ id: 'apertura-confirmada' })
    await flushPromises()
  })

  it('representa EN_CURSO sin lista individual y finaliza solo con motivo', async () => {
    let resolverFinalizacion: (() => void) | undefined
    const finalizar = vi.fn(
      () =>
        new Promise<void>((resolver) => {
          resolverFinalizacion = resolver
        }),
    )
    const estadoEnCurso = crearEstado({
      votacion: crearVotacion(),
      capacidades: {
        ...crearEstado().capacidades,
        abrir_votacion: { habilitada: false, motivos: ['VOTACION_PENDIENTE'] },
        finalizar_votacion: { habilitada: true, motivos: [] },
      },
    })
    const wrapper = montar(GestionVotacion, {
      estado: estadoEnCurso,
      cliente: crearCliente({ finalizarVotacion: finalizar }),
      conectado: true,
      puntoPreseleccionado: null,
    })

    expect(wrapper.get('[data-testid="cantidad-votos-recibidos"]').text()).toBe('2')
    expect(wrapper.get('[data-testid="votos-ocultos"]').exists()).toBe(true)
    await wrapper.get('[data-testid="btn-finalizar-votacion"]').trigger('click')
    expect(finalizar).not.toHaveBeenCalled()

    await wrapper.get('[data-testid="input-motivo-finalizacion"]').setValue('Moción previa')
    await wrapper.get('[data-testid="btn-finalizar-votacion"]').trigger('click')
    await wrapper.get('[data-testid="btn-finalizar-votacion"]').trigger('click')
    expect(finalizar).toHaveBeenCalledTimes(1)
    resolverFinalizacion?.()
    await flushPromises()
    expect(finalizar).toHaveBeenCalledWith('votacion-1', 'Moción previa')

    // WP-051: una finalización aceptada vacía el motivo, así que el siguiente intento
    // vuelve a exigirlo. Antes el texto quedaba pegado y podía reutilizarse sin querer.
    const campoMotivo = wrapper.get('[data-testid="input-motivo-finalizacion"]')
    expect((campoMotivo.element as HTMLInputElement).value).toBe('')

    finalizar.mockRejectedValueOnce({ mensaje: 'Finalización rechazada' })
    await campoMotivo.setValue('Moción previa')
    await wrapper.get('[data-testid="btn-finalizar-votacion"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-testid="alerta-error-votacion"]').text()).toContain(
      'Finalización rechazada',
    )
    expect(wrapper.get('[data-testid="estado-votacion"]').text()).toBe('EN_CURSO')

    await wrapper.setProps({
      estado: crearEstado({
        revision: 2,
        votacion: crearVotacion({
          cantidad_votos_recibidos: 3,
          votos_individuales_revelados: true,
          votos_individuales: [
            {
              dni: '1',
              nombre: 'Ada',
              apellido: 'Lovelace',
              banca: 1,
              valor: 'POSITIVO',
            },
          ],
          conteos: { positivos: 1, negativos: 1, abstenciones: 1, total: 3 },
        }),
        capacidades: estadoEnCurso.capacidades,
      }),
    })
    // WP-037: aunque el DTO proyecte individuales, Q1 conserva solamente agregados.
    expect(wrapper.find('[data-testid="votos-individuales"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Ada Lovelace')
    expect(wrapper.get('[data-testid="votos-ocultos"]').exists()).toBe(true)
    expect(wrapper.get('[data-testid="conteos-votacion"]').text()).toContain('Abstenciones')
  })

  it('distingue los cuatro resultados y limita el desempate a EMPATADA SIMPLE', async () => {
    let resolverDesempate: (() => void) | undefined
    const desempatar = vi.fn(
      () =>
        new Promise<void>((resolver) => {
          resolverDesempate = resolver
        }),
    )
    const capacidadesEmpate = {
      ...crearEstado().capacidades,
      abrir_votacion: { habilitada: false, motivos: ['VOTACION_PENDIENTE'] },
      desempatar: { habilitada: true, motivos: [] },
    }
    const wrapper = montar(GestionVotacion, {
      estado: crearEstado({
        votacion: crearVotacion({ estado_recepcion: 'CERRADA', resultado: 'APROBADA' }),
      }),
      cliente: crearCliente({ desempatar }),
      conectado: true,
      puntoPreseleccionado: null,
    })

    for (const resultado of ['APROBADA', 'RECHAZADA', 'INCONCLUSA', 'EMPATADA']) {
      await wrapper.setProps({
        estado: crearEstado({
          votacion: crearVotacion({ estado_recepcion: 'CERRADA', resultado }),
          capacidades: resultado === 'EMPATADA' ? capacidadesEmpate : crearEstado().capacidades,
        }),
      })
      expect(wrapper.get('[data-testid="estado-votacion"]').text()).toBe(resultado)
    }

    expect(wrapper.get('[data-testid="controles-desempate"]').text()).not.toContain('ABSTENCION')
    expect(wrapper.find('[data-testid="votos-individuales"]').exists()).toBe(false)
    await wrapper.get('[data-testid="btn-desempate-positivo"]').trigger('click')
    await wrapper.get('[data-testid="btn-desempate-negativo"]').trigger('click')
    expect(desempatar).toHaveBeenCalledTimes(1)
    resolverDesempate?.()
    await flushPromises()
    expect(desempatar).toHaveBeenCalledWith('votacion-1', 'POSITIVO')

    await wrapper.setProps({
      estado: crearEstado({
        votacion: crearVotacion({
          estado_recepcion: 'CERRADA',
          resultado: 'EMPATADA',
          tipo_mayoria: 'ESPECIAL',
          factor: 0.66,
          base: 'CUERPO',
        }),
        capacidades: capacidadesEmpate,
      }),
    })
    expect(wrapper.find('[data-testid="controles-desempate"]').exists()).toBe(false)
  })

  it('deshabilita mutaciones por desconexión o capacidad sin inventar cambios locales', async () => {
    const abrir = vi.fn().mockResolvedValue({ id: 'no-debe-abrir' })
    const wrapper = montar(GestionVotacion, {
      estado: crearEstado(),
      cliente: crearCliente({ abrirVotacion: abrir }),
      conectado: false,
      puntoPreseleccionado: null,
    })
    await completarFormularioSimple(wrapper)
    expect(
      (wrapper.get('[data-testid="btn-abrir-votacion"]').element as HTMLButtonElement).disabled,
    ).toBe(true)
    await wrapper.get('[data-testid="btn-abrir-votacion"]').trigger('click')
    expect(abrir).not.toHaveBeenCalled()

    await wrapper.setProps({
      conectado: true,
      estado: crearEstado({
        capacidades: {
          ...crearEstado().capacidades,
          abrir_votacion: { habilitada: false, motivos: ['QUORUM_INSUFICIENTE'] },
        },
      }),
    })
    expect(
      (wrapper.get('[data-testid="btn-abrir-votacion"]').element as HTMLButtonElement).disabled,
    ).toBe(true)
    expect(wrapper.text()).toContain('Quórum insuficiente')
    expect(wrapper.find('[data-testid="vista-votacion-proyectada"]').exists()).toBe(false)
  })
})
