/**
 * Regresión de la compactación operativa de Q1 y la limpieza de Q2 aprobadas por WP-048.
 *
 * Cada caso demuestra una decisión humana cerrada del Work Package sobre los componentes
 * productivos reales, no sobre una copia de su plantilla:
 *
 * - Q1 presenta cada requisito pendiente de `abrir_sesion` en su propio renglón.
 * - Q1 ubica `Editar autoridades` y `Cerrar sesión` en el área de acciones del encabezado
 *   del cuadrante y deja de reservar una franja interior para repetir `Sesión Nº N`.
 * - Q1 conserva su badge de estado del recinto, que tras WP-047 solo vive acá.
 * - El cuerpo de la votación deja de informar de forma permanente orador y cola, sin tocar
 *   la advertencia CA-062 que aparece al intentar abrir con palabra pendiente.
 * - Los conteos agregados se leen en una sola fila secundaria y el cartel de resultado
 *   sigue siendo el elemento de mayor jerarquía.
 * - Un resultado anterior convive con el formulario completo de la votación siguiente.
 * - Q2 no deja acuse persistente después de una carga exitosa, pero sí muestra los errores.
 *
 * Las mutaciones institucionales se simulan exclusivamente con `setProps`: ninguna de estas
 * decisiones habilita actualización optimista en el frontend.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { compile, nextTick, type Component, ssrContextKey } from 'vue'
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
import DialogoConfirmacionApertura from '../app/components/DialogoConfirmacionApertura.vue'
import fuenteDialogoConfirmacionApertura from '../app/components/DialogoConfirmacionApertura.vue?raw'
import DialogoConfirmacionCierre from '../app/components/DialogoConfirmacionCierre.vue'
import fuenteDialogoConfirmacionCierre from '../app/components/DialogoConfirmacionCierre.vue?raw'
import DialogoEdicionAutoridades from '../app/components/DialogoEdicionAutoridades.vue'
import fuenteDialogoEdicionAutoridades from '../app/components/DialogoEdicionAutoridades.vue?raw'
import PanelOrdenDelDia from '../app/components/PanelOrdenDelDia.vue'
import fuentePanelOrdenDelDia from '../app/components/PanelOrdenDelDia.vue?raw'
import { reiniciarInstanciaCompartidaParaPruebas } from '../app/composables/useEstadoModeracion'

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

/** Preparación con dos requisitos pendientes de apertura, para probar el renderizado en lista. */
function crearEstadoPreparando(motivos: string[]): EstadoModeracion {
  return crearEstado({
    estado_global: 'PREPARANDO',
    sesion: null,
    preparacion: {
      fecha_hora_inicio: '2026-08-30T09:00:00Z',
      numero_sesion: 42,
      presidencia: 'Dra. Presidencia',
      secretaria_legislativa: 'Sr. Secretaría',
    },
    capacidades: {
      ...crearCapacidades(),
      preparar_sala: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      actualizar_preparacion: { habilitada: true, motivos: [] },
      cancelar_preparacion: { habilitada: true, motivos: [] },
      abrir_sesion: { habilitada: false, motivos },
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
    estado_recepcion: 'CERRADA',
    resultado: 'APROBADA',
    fecha_hora_apertura: '2026-08-30T10:00:00Z',
    fecha_hora_cierre: '2026-08-30T10:01:00Z',
    fecha_hora_resultado: '2026-08-30T10:01:00Z',
    motivo_finalizacion_manual: null,
    cantidad_votos_recibidos: 4,
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

/** Palabra pendiente: un orador en uso y un pedido en cola. */
const palabraPendiente: EstadoModeracion['palabra'] = {
  orador: { dni: '1', nombre: 'Ada', apellido: 'Lovelace', banca: 1 },
  cola: [{ dni: '2', nombre: 'Grace', apellido: 'Hopper', banca: 2 }],
}

/** Clases CSS efectivas: el DOM mínimo de este repositorio no expone `classes()`. */
function clasesDe(wrapper: VueWrapper, selector: string): string {
  return (wrapper.get(selector).element as HTMLElement).className
}

beforeEach(() => reiniciarInstanciaCompartidaParaPruebas())

afterEach(() => {
  while (montados.length > 0) montados.pop()?.unmount()
  document.body.textContent = ''
})

describe('WP-048 · Q1 encabezado operativo y requisitos de apertura', () => {
  it('PREPARANDO: cada requisito de apertura ocupa su propio renglón', () => {
    const wrapper = montar(PanelSesionVotacion, {
      estado: crearEstadoPreparando(['QUORUM_INSUFICIENTE', 'PRESIDENCIA_REQUERIDA']),
      clienteInyectado: crearCliente(),
    })

    const renglones = wrapper.findAll('[data-testid="motivo-abrir-sesion"]')
    expect(renglones).toHaveLength(2)
    expect(renglones[0]?.text()).toContain('Quórum insuficiente')
    expect(renglones[1]?.text()).toContain('Debe designar la Presidencia')
    // El separador medio de la concatenación anterior ya no debe existir.
    expect(wrapper.get('[data-testid="motivos-abrir-sesion"]').text()).not.toContain(' · ')
  })

  it('un único requisito pendiente también se presenta como colección', () => {
    const wrapper = montar(PanelSesionVotacion, {
      estado: crearEstadoPreparando(['QUORUM_INSUFICIENTE']),
      clienteInyectado: crearCliente(),
    })

    expect(wrapper.findAll('[data-testid="motivo-abrir-sesion"]')).toHaveLength(1)
  })

  it('SESION_ABIERTA: las acciones institucionales viven en el encabezado del cuadrante', () => {
    const wrapper = montar(PanelSesionVotacion, {
      estado: crearEstado(),
      clienteInyectado: crearCliente(),
    })

    const encabezado = wrapper.get('header')
    expect(encabezado.find('[data-testid="btn-editar-autoridades"]').exists()).toBe(true)
    expect(encabezado.find('[data-testid="btn-cerrar-sesion"]').exists()).toBe(true)

    // El cuerpo del panel ya no contiene ninguna de las dos acciones.
    const cuerpo = wrapper.get('[data-testid="cuerpo-panel"]')
    expect(cuerpo.find('[data-testid="btn-editar-autoridades"]').exists()).toBe(false)
    expect(cuerpo.find('[data-testid="btn-cerrar-sesion"]').exists()).toBe(false)
  })

  it('SESION_ABIERTA: no hay franja interior que repita el número de sesión', () => {
    const wrapper = montar(PanelSesionVotacion, {
      estado: crearEstado(),
      clienteInyectado: crearCliente(),
    })

    expect(wrapper.find('[data-testid="franja-sesion-abierta"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="numero-sesion-inmutable"]').exists()).toBe(false)
    // El número de sesión es un dato único de la cabecera global del shell.
    expect(wrapper.text()).not.toContain('Sesión Nº 42')
  })

  it('el badge de estado del recinto permanece en Q1 en los tres estados globales', async () => {
    const wrapper = montar(PanelSesionVotacion, {
      estado: crearEstado({ estado_global: 'SIN_PREPARAR', sesion: null }),
      clienteInyectado: crearCliente(),
    })
    expect(wrapper.get('header').text()).toContain('Sin preparar')

    await wrapper.setProps({
      estado: crearEstadoPreparando(['QUORUM_INSUFICIENTE']),
    })
    expect(wrapper.get('header').text()).toContain('Preparando el recinto')

    await wrapper.setProps({ estado: crearEstado({ revision: 3 }) })
    expect(wrapper.get('header').text()).toContain('Sesión activa')
  })

  it('las acciones del encabezado siguen gobernadas por las capacidades del backend', () => {
    const wrapper = montar(PanelSesionVotacion, {
      estado: crearEstado({
        capacidades: {
          ...crearCapacidades(),
          actualizar_sesion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
          cerrar_sesion: { habilitada: false, motivos: ['VOTACION_EN_CURSO'] },
        },
      }),
      clienteInyectado: crearCliente(),
    })

    expect(
      (wrapper.get('[data-testid="btn-editar-autoridades"]').element as HTMLButtonElement).disabled,
    ).toBe(true)
    expect(
      (wrapper.get('[data-testid="btn-cerrar-sesion"]').element as HTMLButtonElement).disabled,
    ).toBe(true)
  })
})

describe('WP-048 · Q1 palabra fuera del cuerpo y advertencia preservada', () => {
  it('no informa de forma permanente orador ni cantidad de pedidos en cola', () => {
    const wrapper = montar(GestionVotacion, {
      estado: crearEstado({
        votacion: crearVotacion({ estado_recepcion: 'EN_CURSO', resultado: null }),
        palabra: palabraPendiente,
      }),
      cliente: crearCliente(),
      conectado: true,
      puntoPreseleccionado: null,
    })

    expect(wrapper.find('[data-testid="palabra-durante-votacion"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Ada Lovelace')
    expect(wrapper.text()).not.toContain('en cola')
  })

  it('abrir con palabra pendiente sigue mostrando la advertencia CA-062 y cancelar no envía', async () => {
    const abrirVotacion = vi.fn().mockResolvedValue({ id: 'nueva-votacion' })
    const wrapper = montar(GestionVotacion, {
      estado: crearEstado({ palabra: palabraPendiente }),
      cliente: crearCliente({ abrirVotacion }),
      conectado: true,
      puntoPreseleccionado: null,
    })

    await wrapper.get('[data-testid="input-numero-votacion"]').setValue('12')
    await wrapper.get('[data-testid="input-tema-votacion"]').setValue('Presupuesto')
    await wrapper.get('[data-testid="btn-abrir-votacion"]').trigger('click')
    await nextTick()

    const dialogo = wrapper.get('[data-testid="dialogo-confirmacion-apertura"]')
    expect(dialogo.text()).toContain('Ada Lovelace')

    await wrapper.get('[data-testid="btn-cancelar-apertura"]').trigger('click')
    await nextTick()
    expect(wrapper.find('[data-testid="dialogo-confirmacion-apertura"]').exists()).toBe(false)
    expect(abrirVotacion).not.toHaveBeenCalled()
  })

  it('confirmar la advertencia abre la votación sin tocar orador ni cola', async () => {
    const abrirVotacion = vi.fn().mockResolvedValue({ id: 'nueva-votacion' })
    const estado = crearEstado({ palabra: palabraPendiente })
    const wrapper = montar(GestionVotacion, {
      estado,
      cliente: crearCliente({ abrirVotacion }),
      conectado: true,
      puntoPreseleccionado: null,
    })

    await wrapper.get('[data-testid="input-numero-votacion"]').setValue('12')
    await wrapper.get('[data-testid="input-tema-votacion"]').setValue('Presupuesto')
    await wrapper.get('[data-testid="btn-abrir-votacion"]').trigger('click')
    await nextTick()
    await wrapper.get('[data-testid="btn-confirmar-apertura"]').trigger('click')
    await flushPromises()

    expect(abrirVotacion).toHaveBeenCalledTimes(1)
    expect(abrirVotacion).toHaveBeenCalledWith(
      expect.objectContaining({ numero_votacion: 12, tema: 'Presupuesto' }),
    )
    // El frontend no retira pedidos ni finaliza al orador: la palabra es del backend.
    expect(estado.palabra).toEqual(palabraPendiente)
  })
})

describe('WP-048 · Q1 resultado dominante con conteos compactos', () => {
  it('presenta los conteos en una fila secundaria sin cuatro tarjetas altas', () => {
    const wrapper = montar(GestionVotacion, {
      estado: crearEstado({ votacion: crearVotacion() }),
      cliente: crearCliente(),
      conectado: true,
      puntoPreseleccionado: null,
    })

    const conteos = wrapper.get('[data-testid="conteos-votacion"]')
    // Una única fila flexible: la grilla de cuatro columnas altas ya no existe.
    expect(clasesDe(wrapper, '[data-testid="conteos-votacion"]')).toContain('flex')
    expect(clasesDe(wrapper, '[data-testid="conteos-votacion"]')).not.toContain('grid-cols-4')
    expect(conteos.text()).toContain('Positivos')
    expect(conteos.text()).toContain('Negativos')
    expect(conteos.text()).toContain('Abstenciones')
    expect(conteos.text()).toContain('Total')

    // La convención de color fijada por WP-044 se conserva.
    expect(clasesDe(wrapper, '[data-testid="conteo-positivos"]')).toContain('emerald')
    expect(clasesDe(wrapper, '[data-testid="conteo-negativos"]')).toContain('rose')
    expect(clasesDe(wrapper, '[data-testid="conteo-abstenciones"]')).toContain('amber')
  })

  it('el cartel de resultado sigue siendo el elemento de mayor jerarquía', () => {
    const wrapper = montar(GestionVotacion, {
      estado: crearEstado({ votacion: crearVotacion() }),
      cliente: crearCliente(),
      conectado: true,
      puntoPreseleccionado: null,
    })

    const resultado = wrapper.get('[data-testid="estado-votacion"]')
    expect(resultado.text()).toBe('APROBADA')
    expect(resultado.element.getAttribute('data-jerarquia')).toBe('principal')
    expect(clasesDe(wrapper, '[data-testid="estado-votacion"]')).toContain('text-2xl')
    // Ningún conteo compite con esa jerarquía tipográfica.
    expect(clasesDe(wrapper, '[data-testid="conteo-positivos"]')).toContain('text-')
    expect(clasesDe(wrapper, '[data-testid="conteo-positivos"]')).not.toContain('text-2xl')
  })

  it('Q1 no lista votos individuales aunque el DTO los proyecte', () => {
    const wrapper = montar(GestionVotacion, {
      estado: crearEstado({
        votacion: crearVotacion({
          votos_individuales: [
            { dni: '1', nombre: 'Ada', apellido: 'Lovelace', banca: 1, valor: 'POSITIVO' },
          ],
        }),
      }),
      cliente: crearCliente(),
      conectado: true,
      puntoPreseleccionado: null,
    })

    expect(wrapper.find('[data-testid="votos-individuales"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Ada Lovelace')
  })

  it('el resultado anterior convive con el formulario completo de la votación siguiente', () => {
    const wrapper = montar(GestionVotacion, {
      estado: crearEstado({ votacion: crearVotacion() }),
      cliente: crearCliente(),
      conectado: true,
      puntoPreseleccionado: null,
    })

    expect(wrapper.get('[data-testid="vista-votacion-proyectada"]').exists()).toBe(true)
    const formulario = wrapper.get('[data-testid="formulario-votacion"]')
    expect(formulario.find('[data-testid="input-numero-votacion"]').exists()).toBe(true)
    expect(formulario.find('[data-testid="select-tipo-votacion"]').exists()).toBe(true)
    expect(formulario.find('[data-testid="radio-mayoria-simple"]').exists()).toBe(true)
    expect(formulario.find('[data-testid="radio-mayoria-especial"]').exists()).toBe(true)
    expect(formulario.find('[data-testid="input-tema-votacion"]').exists()).toBe(true)
    expect(formulario.find('[data-testid="btn-abrir-votacion"]').exists()).toBe(true)
    expect(formulario.find('[data-testid="btn-limpiar-borrador"]').exists()).toBe(true)
  })

  it('los campos de mayoría especial siguen apareciendo junto a un resultado anterior', async () => {
    const wrapper = montar(GestionVotacion, {
      estado: crearEstado({ votacion: crearVotacion() }),
      cliente: crearCliente(),
      conectado: true,
      puntoPreseleccionado: null,
    })

    // La mayoría especial se activa por el mismo camino que usa el operador: copiar un
    // punto especial desde Q2. El DOM mínimo de estas pruebas no simula radios nativos.
    await wrapper.setProps({
      puntoPreseleccionado: {
        nro_votacion: 9,
        tipo: 'Moción',
        tema: 'Modificación del reglamento',
        tipo_mayoria: 'ESPECIAL',
        factor: 0.66,
        base: 'CUERPO',
      },
    })
    await nextTick()

    const especiales = wrapper.get('[data-testid="campos-mayoria-especial"]')
    expect(especiales.find('[data-testid="input-factor-mayoria"]').exists()).toBe(true)
    expect(especiales.find('[data-testid="select-base-mayoria"]').exists()).toBe(true)
    expect(wrapper.get('[data-testid="vista-votacion-proyectada"]').exists()).toBe(true)
  })
})

describe('WP-048 · Q2 sin acuse persistente de carga', () => {
  async function seleccionarArchivo(wrapper: VueWrapper, nombre: string): Promise<void> {
    const archivo = new File(['nro_votacion;tipo'], nombre, { type: 'text/csv' })
    const entrada = wrapper.get('[data-testid="input-archivo-orden-dia"]')
    Object.defineProperty(entrada.element, 'files', { configurable: true, value: [archivo] })
    await entrada.trigger('change')
  }

  it('una carga exitosa no deja renglón informativo y la colección es la confirmación', async () => {
    const cargarOrdenDelDia = vi.fn().mockResolvedValue({ puntos: [] })
    const wrapper = montar(PanelOrdenDelDia, {
      estado: crearEstado({ orden_del_dia: [] }),
      clienteInyectado: crearCliente({ cargarOrdenDelDia }),
    })

    await seleccionarArchivo(wrapper, 'orden-sesion-42.csv')
    await wrapper.get('[data-testid="btn-cargar-orden-dia"]').trigger('click')
    await flushPromises()

    expect(cargarOrdenDelDia).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[data-testid="aviso-orden-dia"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Archivo enviado')
    expect(wrapper.text()).not.toContain('La lista cambiará')

    // Recién el snapshot autoritativo reemplaza la vista de carga por la colección.
    await wrapper.setProps({
      estado: crearEstado({
        revision: 2,
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
    })
    expect(wrapper.findAll('[data-testid="punto-orden-dia"]')).toHaveLength(1)
    expect(wrapper.find('[data-testid="aviso-orden-dia"]').exists()).toBe(false)
  })

  it('un error real de carga sí permanece visible y accionable', async () => {
    const cargarOrdenDelDia = vi.fn().mockRejectedValue({ mensaje: 'CSV inválido' })
    const wrapper = montar(PanelOrdenDelDia, {
      estado: crearEstado({ orden_del_dia: [] }),
      clienteInyectado: crearCliente({ cargarOrdenDelDia }),
    })

    await seleccionarArchivo(wrapper, 'invalido.csv')
    await wrapper.get('[data-testid="btn-cargar-orden-dia"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="alerta-error-orden-dia"]').text()).toContain('CSV inválido')
    expect(wrapper.get('[data-testid="input-archivo-orden-dia"]').exists()).toBe(true)
  })

  it('el toast de copiado de punto no cambia con esta corrección', async () => {
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

    await wrapper.get('[data-testid="punto-orden-dia"]').trigger('click')
    expect(wrapper.get('[data-testid="toast-punto-copiado"]').text()).toContain(
      'Punto Nº 7 copiado al borrador',
    )
  })
})
