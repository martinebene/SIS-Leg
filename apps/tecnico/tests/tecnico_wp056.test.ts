/**
 * Pruebas de componentes del puesto de Apoyo Técnico (WP-056).
 *
 * Cubren las decisiones humanas cerradas que pueden comprobarse sobre el DOM:
 *
 * 1. transmisión instantánea, con cuenta regresiva y detención manual;
 * 2. publicación de avisos con destino MODERACION / RECINTO / AMBOS;
 * 3. duración opcional: vacía significa "hasta cancelación manual";
 * 4. cancelación por destino;
 * 5. CRUD completo de mensajes precargados;
 * 6. seleccionar un preset precarga el formulario **sin** publicar nada;
 * 7. filtro L1/L2/L3 con la misma acumulación institucional que Moderación;
 * 8. frontera de secreto de WP-052: sin `hecho`, no hay identidad ni icono;
 * 9. reconstrucción del estado desde el snapshot autoritativo y conservación del último
 *    estado confirmado ante una desconexión;
 * 10. desde WP-074, que todo eso se sostiene con **una sola** suscripción SSE.
 *
 * La geometría real (ausencia de scroll global, proporciones) se mide aparte con
 * Playwright: el DOM de estas pruebas no calcula layout.
 */

import { mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ClienteApoyoTecnico, Suscripcion } from '@sis-leg/api-client'
import ControlTransmision from '../app/components/ControlTransmision.vue'
import ControlAvisos from '../app/components/ControlAvisos.vue'
import BibliotecaMensajes from '../app/components/BibliotecaMensajes.vue'
import ListaEventosTecnicos from '../app/components/ListaEventosTecnicos.vue'
import CabeceraTecnico from '../app/components/CabeceraTecnico.vue'
import { crearSincronizacionTecnica } from '../app/composables/useEstadoTecnico'
import {
  crearAvisoPrueba,
  crearBibliotecaPrueba,
  crearEstadoTecnicoPrueba,
  crearEventoPrueba,
  crearMensajePrueba,
  crearTransmisionPrueba,
} from './datos_prueba'

const montados: VueWrapper[] = []

afterEach(() => {
  while (montados.length > 0) montados.pop()?.unmount()
  vi.useRealTimers()
})

function montar(componente: unknown, props: Record<string, unknown>): VueWrapper {
  const wrapper = mount(componente as never, { props })
  montados.push(wrapper)
  return wrapper
}

/** Cliente técnico con todos los comandos espiados; ninguna prueba toca la red. */
function crearClienteEspia(): ClienteApoyoTecnico {
  return {
    iniciarTransmision: vi.fn().mockResolvedValue(undefined),
    detenerTransmision: vi.fn().mockResolvedValue(undefined),
    publicarAviso: vi.fn().mockResolvedValue(undefined),
    cancelarAviso: vi.fn().mockResolvedValue(undefined),
    crearMensaje: vi.fn().mockResolvedValue(crearMensajePrueba('m-nuevo', 'Nuevo')),
    actualizarMensaje: vi.fn().mockResolvedValue(crearMensajePrueba('m-1', 'Editado')),
    eliminarMensaje: vi.fn().mockResolvedValue(undefined),
    listarMensajes: vi.fn(),
    obtenerEstado: vi.fn(),
    suscribirEstado: vi.fn(),
  } as unknown as ClienteApoyoTecnico
}

// =============================================================================
// 1. Transmisión
// =============================================================================

describe('Controles de transmisión', () => {
  it('inicia la transmisión de inmediato cuando no se pide cuenta regresiva', async () => {
    const cliente = crearClienteEspia()
    const wrapper = montar(ControlTransmision, {
      transmision: crearTransmisionPrueba({ estado: 'APAGADO' }),
      segundosRestantes: null,
      cliente,
      conectado: true,
    })

    await wrapper.get('[data-testid="btn-transmision-instantanea"]').trigger('click')

    // `null` es exactamente lo que el contrato interpreta como inicio inmediato.
    expect(cliente.iniciarTransmision).toHaveBeenCalledWith(null)
  })

  it('inicia con la cuenta regresiva elegida por el operador', async () => {
    const cliente = crearClienteEspia()
    const wrapper = montar(ControlTransmision, {
      transmision: crearTransmisionPrueba({ estado: 'APAGADO' }),
      segundosRestantes: null,
      cliente,
      conectado: true,
    })

    await wrapper.get('[data-testid="input-cuenta-regresiva"]').setValue('25')
    await wrapper.get('[data-testid="btn-transmision-cuenta"]').trigger('click')

    expect(cliente.iniciarTransmision).toHaveBeenCalledWith(25)
  })

  it('muestra la cuenta regresiva y el rótulo EN VIVO según el estado autoritativo', () => {
    const cuenta = montar(ControlTransmision, {
      transmision: crearTransmisionPrueba({
        estado: 'CUENTA_REGRESIVA',
        en_vivo_desde: '2026-09-02T10:00:12Z',
        cuenta_regresiva_segundos: 12,
      }),
      segundosRestantes: 7,
      cliente: crearClienteEspia(),
      conectado: true,
    })
    expect(cuenta.get('[data-testid="cuenta-regresiva-tecnico"]').text()).toBe('7')

    const enVivo = montar(ControlTransmision, {
      transmision: crearTransmisionPrueba({ estado: 'EN_VIVO' }),
      segundosRestantes: null,
      cliente: crearClienteEspia(),
      conectado: true,
    })
    expect(enVivo.get('[data-testid="estado-transmision"]').text()).toContain('En vivo')
  })

  it('detiene la transmisión solamente cuando hay algo que detener', async () => {
    const cliente = crearClienteEspia()
    const apagada = montar(ControlTransmision, {
      transmision: crearTransmisionPrueba({ estado: 'APAGADO' }),
      segundosRestantes: null,
      cliente,
      conectado: true,
    })
    expect(
      (apagada.get('[data-testid="btn-transmision-detener"]').element as HTMLButtonElement)
        .disabled,
    ).toBe(true)

    const enVivo = montar(ControlTransmision, {
      transmision: crearTransmisionPrueba({ estado: 'EN_VIVO' }),
      segundosRestantes: null,
      cliente,
      conectado: true,
    })
    await enVivo.get('[data-testid="btn-transmision-detener"]').trigger('click')
    expect(cliente.detenerTransmision).toHaveBeenCalledTimes(1)
  })

  it('bloquea todos los comandos sin conexión confirmada', () => {
    const wrapper = montar(ControlTransmision, {
      transmision: crearTransmisionPrueba({ estado: 'APAGADO' }),
      segundosRestantes: null,
      cliente: crearClienteEspia(),
      conectado: false,
    })

    expect(
      (wrapper.get('[data-testid="btn-transmision-instantanea"]').element as HTMLButtonElement)
        .disabled,
    ).toBe(true)
    expect(wrapper.find('[data-testid="transmision-sin-conexion"]').exists()).toBe(true)
  })

  it('muestra el rechazo del backend en lugar de un texto genérico', async () => {
    const cliente = crearClienteEspia()
    vi.mocked(cliente.iniciarTransmision).mockRejectedValueOnce({
      mensajeBackend: 'La auditoría institucional no está disponible',
    })
    const wrapper = montar(ControlTransmision, {
      transmision: crearTransmisionPrueba({ estado: 'APAGADO' }),
      segundosRestantes: null,
      cliente,
      conectado: true,
    })

    await wrapper.get('[data-testid="btn-transmision-instantanea"]').trigger('click')
    await new Promise((resolver) => setTimeout(resolver, 0))
    await wrapper.vm.$nextTick()

    expect(wrapper.get('[data-testid="error-transmision"]').text()).toContain(
      'La auditoría institucional no está disponible',
    )
  })
})

// =============================================================================
// 2. Avisos
// =============================================================================

describe('Publicación y cancelación de avisos', () => {
  function montarAvisos(props: Record<string, unknown> = {}): {
    wrapper: VueWrapper
    cliente: ClienteApoyoTecnico
  } {
    const cliente = (props.cliente as ClienteApoyoTecnico) ?? crearClienteEspia()
    const wrapper = montar(ControlAvisos, {
      avisoModeracion: null,
      avisoRecinto: null,
      conectado: true,
      borrador: null,
      segundosRestantes: () => null,
      ...props,
      cliente,
    })
    return { wrapper, cliente }
  }

  it.each(['MODERACION', 'RECINTO', 'AMBOS'])(
    'publica hacia el destino %s elegido por el operador',
    async (destino) => {
      const { wrapper, cliente } = montarAvisos()

      await wrapper.get('[data-testid="input-texto-aviso"]').setValue('Falla de audio')
      await wrapper.get('[data-testid="select-destino-aviso"]').setValue(destino)
      await wrapper.get('[data-testid="btn-publicar-aviso"]').trigger('click')

      expect(cliente.publicarAviso).toHaveBeenCalledWith('Falla de audio', destino, null)
    },
  )

  it('interpreta la duración vacía como "hasta cancelación manual"', async () => {
    const { wrapper, cliente } = montarAvisos()

    await wrapper.get('[data-testid="input-texto-aviso"]').setValue('Sin límite')
    await wrapper.get('[data-testid="btn-publicar-aviso"]').trigger('click')

    expect(cliente.publicarAviso).toHaveBeenCalledWith('Sin límite', 'AMBOS', null)
    expect(wrapper.get('[data-testid="rotulo-duracion"]').text()).toContain(
      'hasta cancelarlo manualmente',
    )
  })

  it('envía la duración cuando el operador la carga', async () => {
    const { wrapper, cliente } = montarAvisos()

    await wrapper.get('[data-testid="input-texto-aviso"]').setValue('Con vencimiento')
    await wrapper.get('[data-testid="input-duracion-aviso"]').setValue('45')
    await wrapper.get('[data-testid="btn-publicar-aviso"]').trigger('click')

    expect(cliente.publicarAviso).toHaveBeenCalledWith('Con vencimiento', 'AMBOS', 45)
  })

  it('rechaza una duración fuera del rango del contrato sin llamar al backend', async () => {
    const { wrapper, cliente } = montarAvisos()

    await wrapper.get('[data-testid="input-texto-aviso"]').setValue('Duración inválida')
    await wrapper.get('[data-testid="input-duracion-aviso"]').setValue('999999')
    await wrapper.vm.$nextTick()

    expect(wrapper.find('[data-testid="duracion-invalida"]').exists()).toBe(true)
    expect(
      (wrapper.get('[data-testid="btn-publicar-aviso"]').element as HTMLButtonElement).disabled,
    ).toBe(true)
    expect(cliente.publicarAviso).not.toHaveBeenCalled()
  })

  it('no publica un aviso vacío ni compuesto sólo de espacios', async () => {
    const { wrapper, cliente } = montarAvisos()

    await wrapper.get('[data-testid="input-texto-aviso"]').setValue('    ')
    await wrapper.vm.$nextTick()

    expect(
      (wrapper.get('[data-testid="btn-publicar-aviso"]').element as HTMLButtonElement).disabled,
    ).toBe(true)
    expect(cliente.publicarAviso).not.toHaveBeenCalled()
  })

  it('muestra cada ranura por separado y cancela sólo el destino elegido', async () => {
    const { wrapper, cliente } = montarAvisos({
      avisoModeracion: crearAvisoPrueba({ texto: 'Solo Moderación', destino: 'MODERACION' }),
      avisoRecinto: null,
    })

    expect(wrapper.get('[data-testid="texto-vigente-moderacion"]').text()).toBe('Solo Moderación')
    expect(wrapper.get('[data-testid="ranura-recinto"]').text()).toContain('Sin aviso vigente')

    await wrapper.get('[data-testid="btn-cancelar-moderacion"]').trigger('click')
    expect(cliente.cancelarAviso).toHaveBeenCalledWith('MODERACION')
    expect(cliente.cancelarAviso).toHaveBeenCalledTimes(1)
  })

  it('rotula la vigencia según haya o no vencimiento', () => {
    const { wrapper } = montarAvisos({
      avisoModeracion: crearAvisoPrueba({ expira_en: '2026-09-02T10:00:30Z' }),
      avisoRecinto: crearAvisoPrueba({ aviso_id: 'aviso-2', expira_en: null }),
      segundosRestantes: () => 30,
    })

    expect(wrapper.get('[data-testid="vigencia-moderacion"]').text()).toBe('Vence en 30 s')
    expect(wrapper.get('[data-testid="vigencia-recinto"]').text()).toBe('Hasta cancelación manual')
  })

  it('adopta un borrador precargado sin publicarlo', async () => {
    const { wrapper, cliente } = montarAvisos()

    await wrapper.setProps({
      borrador: { texto: 'Preset institucional', destino: 'RECINTO', marca: 1 },
    })

    expect(
      (wrapper.get('[data-testid="input-texto-aviso"]').element as HTMLTextAreaElement).value,
    ).toBe('Preset institucional')
    expect(cliente.publicarAviso).not.toHaveBeenCalled()

    // El mismo preset elegido otra vez vuelve a precargar: la marca cambia aunque el
    // texto y el destino sean idénticos.
    await wrapper.get('[data-testid="input-texto-aviso"]').setValue('Editado a mano')
    await wrapper.setProps({
      borrador: { texto: 'Preset institucional', destino: 'RECINTO', marca: 2 },
    })
    expect(
      (wrapper.get('[data-testid="input-texto-aviso"]').element as HTMLTextAreaElement).value,
    ).toBe('Preset institucional')
  })
})

// =============================================================================
// 3. Biblioteca de mensajes precargados
// =============================================================================

describe('Biblioteca de mensajes precargados', () => {
  function montarBiblioteca(props: Record<string, unknown> = {}): {
    wrapper: VueWrapper
    cliente: ClienteApoyoTecnico
  } {
    const cliente = crearClienteEspia()
    const wrapper = montar(BibliotecaMensajes, {
      biblioteca: crearBibliotecaPrueba({
        mensajes: [
          crearMensajePrueba('m-1', 'Cuarto intermedio', 'AMBOS'),
          crearMensajePrueba('m-2', 'Prueba de sonido', 'RECINTO'),
        ],
      }),
      conectado: true,
      ...props,
      cliente,
    })
    return { wrapper, cliente }
  }

  it('lista los mensajes persistidos con su destino', () => {
    const { wrapper } = montarBiblioteca()

    const filas = wrapper.findAll('[data-testid="mensaje-precargado"]')
    expect(filas).toHaveLength(2)
    expect(filas[0]!.get('[data-testid="texto-mensaje"]').text()).toBe('Cuarto intermedio')
    expect(filas[1]!.get('[data-testid="destino-mensaje"]').text()).toBe('RECINTO')
  })

  it('crea un mensaje nuevo con texto y destino', async () => {
    const { wrapper, cliente } = montarBiblioteca()

    await wrapper.get('[data-testid="input-mensaje-nuevo"]').setValue('Retomamos en 5 minutos')
    await wrapper.get('[data-testid="select-destino-nuevo"]').setValue('MODERACION')
    await wrapper.get('[data-testid="btn-crear-mensaje"]').trigger('click')

    expect(cliente.crearMensaje).toHaveBeenCalledWith('Retomamos en 5 minutos', 'MODERACION')
  })

  it('edita un mensaje conservando su identificador', async () => {
    const { wrapper, cliente } = montarBiblioteca()

    const fila = wrapper.findAll('[data-testid="mensaje-precargado"]')[0]!
    await fila.get('[data-testid="btn-editar-mensaje"]').trigger('click')
    await fila.get('[data-testid="input-mensaje-editado"]').setValue('Cuarto intermedio breve')
    await fila.get('[data-testid="select-destino-editado"]').setValue('RECINTO')
    await fila.get('[data-testid="btn-guardar-mensaje"]').trigger('click')

    expect(cliente.actualizarMensaje).toHaveBeenCalledWith(
      'm-1',
      'Cuarto intermedio breve',
      'RECINTO',
    )
  })

  it('elimina un mensaje por su identificador', async () => {
    const { wrapper, cliente } = montarBiblioteca()

    const fila = wrapper.findAll('[data-testid="mensaje-precargado"]')[1]!
    await fila.get('[data-testid="btn-eliminar-mensaje"]').trigger('click')

    expect(cliente.eliminarMensaje).toHaveBeenCalledWith('m-2')
  })

  it('emite el preset al formulario sin publicarlo', async () => {
    const { wrapper, cliente } = montarBiblioteca()

    const fila = wrapper.findAll('[data-testid="mensaje-precargado"]')[0]!
    await fila.get('[data-testid="btn-cargar-mensaje"]').trigger('click')

    expect(wrapper.emitted('cargar')).toEqual([[{ texto: 'Cuarto intermedio', destino: 'AMBOS' }]])
    expect(cliente.publicarAviso).not.toHaveBeenCalled()
  })

  it('bloquea toda escritura cuando el CSV no pudo interpretarse', () => {
    const { wrapper } = montarBiblioteca({
      biblioteca: crearBibliotecaPrueba({
        disponible: false,
        motivo: 'BIBLIOTECA_MENSAJES_INVALIDA',
        detalle: 'La fila 3 no tiene destino',
        mensajes: [],
      }),
    })

    expect(wrapper.get('[data-testid="detalle-biblioteca"]').text()).toBe(
      'La fila 3 no tiene destino',
    )
    expect(
      (wrapper.get('[data-testid="btn-crear-mensaje"]').element as HTMLButtonElement).disabled,
    ).toBe(true)
  })
})

// =============================================================================
// 4. Eventos seguros
// =============================================================================

describe('Franja de eventos del puesto técnico', () => {
  const EVENTOS = [
    crearEventoPrueba({ seq: 1, nivel: 'L1', codigo_evento: 'PULSACION_RECIBIDA' }),
    crearEventoPrueba({ seq: 2, nivel: 'L2', codigo_evento: 'PRESENCIA_ACTIVADA' }),
    crearEventoPrueba({ seq: 3, nivel: 'L3', codigo_evento: 'SESION_ABIERTA' }),
  ]

  it('aplica la acumulación L1 ⊇ L2 ⊇ L3 y ordena del más nuevo al más viejo', async () => {
    const wrapper = montar(ListaEventosTecnicos, { eventos: EVENTOS })

    expect(wrapper.findAll('[data-testid="evento-tecnico"]')).toHaveLength(1)

    await wrapper.get('[data-testid="filtro-eventos-tecnico"]').setValue('L1')
    const codigos = wrapper
      .findAll('[data-testid="codigo-evento-tecnico"]')
      .map((nodo) => nodo.text())
    expect(codigos).toEqual(['SESION_ABIERTA', 'PRESENCIA_ACTIVADA', 'PULSACION_RECIBIDA'])
  })

  it('conserva la frontera de secreto: sin hecho no hay identidad ni icono', () => {
    const wrapper = montar(ListaEventosTecnicos, {
      eventos: [crearEventoPrueba({ seq: 5, nivel: 'L3', mensaje: 'Voto registrado' })],
    })

    expect(wrapper.find('[data-testid="hecho-evento-tecnico"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="icono-evento-tecnico"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="mensaje-evento-tecnico"]').text()).toBe('Voto registrado')
  })

  it('muestra identidad e icono sólo cuando el backend los envía resueltos', () => {
    const wrapper = montar(ListaEventosTecnicos, {
      eventos: [
        crearEventoPrueba({
          seq: 6,
          nivel: 'L3',
          hecho: {
            concejal: { nombre: 'Ana', apellido: 'Pérez', banca: 4 },
            detalle: 'Pedido de palabra',
            icono: '✋',
          },
        }),
      ],
    })

    expect(wrapper.get('[data-testid="hecho-evento-tecnico"]').text()).toContain('Banca 4')
    expect(wrapper.get('[data-testid="detalle-evento-tecnico"]').text()).toBe('Pedido de palabra')
    expect(wrapper.get('[data-testid="icono-evento-tecnico"]').text()).toBe('✋')
  })

  it('informa un estado vacío distinto según haya o no eventos en el snapshot', async () => {
    const sinEventos = montar(ListaEventosTecnicos, { eventos: [] })
    expect(sinEventos.get('[data-testid="eventos-tecnico-vacio"]').text()).toBe(
      'Sin eventos en la sesión activa',
    )

    const conFiltro = montar(ListaEventosTecnicos, {
      eventos: [crearEventoPrueba({ seq: 1, nivel: 'L1' })],
    })
    expect(conFiltro.get('[data-testid="eventos-tecnico-vacio"]').text()).toBe(
      'No hay eventos para el nivel seleccionado',
    )
    await conFiltro.get('[data-testid="filtro-eventos-tecnico"]').setValue('L1')
    expect(conFiltro.findAll('[data-testid="evento-tecnico"]')).toHaveLength(1)
  })
})

// =============================================================================
// 5. Cabecera y sincronización
// =============================================================================

describe('Cabecera del puesto técnico', () => {
  it('refleja el estado de conexión y advierte cuando los datos pueden estar viejos', () => {
    const wrapper = montar(CabeceraTecnico, {
      estadoConexion: 'RECONECTANDO',
      estadoGlobal: 'SESION_ABIERTA',
      revision: 42,
      desactualizado: true,
      estadoTransmision: 'EN_VIVO',
    })

    expect(wrapper.get('[data-testid="estado-conexion"]').text()).toBe('Reconectando')
    expect(wrapper.find('[data-testid="aviso-desactualizado"]').exists()).toBe(true)
    expect(wrapper.get('[data-testid="estado-global-tecnico"]').text()).toBe('Sesión abierta')
    expect(wrapper.get('[data-testid="resumen-transmision"]').text()).toBe('En vivo')
  })

  it('no inventa estado global antes del primer snapshot', () => {
    const wrapper = montar(CabeceraTecnico, {
      estadoConexion: 'INICIAL',
      estadoGlobal: null,
      revision: null,
      desactualizado: false,
      estadoTransmision: null,
    })

    expect(wrapper.find('[data-testid="estado-global-tecnico"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="resumen-transmision"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="estado-conexion"]').text()).toBe('Conectando')
  })
})

describe('Sincronización del puesto técnico', () => {
  /** Cliente de sincronización que expone sus callbacks para dispararlos a mano. */
  function crearClienteSuscribible<T>(): {
    cliente: { suscribirEstado: ReturnType<typeof vi.fn> }
    emitir: (estado: T) => void
    cambiarConexion: (conectado: boolean) => void
    cancelado: () => boolean
  } {
    let alEstado: ((estado: T) => void) | null = null
    let alCambiarConexion: ((conectado: boolean) => void) | null = null
    let activa = true
    const suscripcion: Suscripcion = {
      get activa() {
        return activa
      },
      cancelar: () => {
        activa = false
      },
    }
    const cliente = {
      suscribirEstado: vi.fn((opciones: Record<string, never>) => {
        alEstado = opciones.alEstado as unknown as (estado: T) => void
        alCambiarConexion = opciones.alCambiarConexion as unknown as (c: boolean) => void
        return suscripcion
      }),
    }
    return {
      cliente,
      emitir: (estado) => alEstado?.(estado),
      cambiarConexion: (conectado) => alCambiarConexion?.(conectado),
      cancelado: () => !activa,
    }
  }

  it('abre exactamente una suscripción y no la duplica al reiniciar (WP-074)', () => {
    // El criterio central del WP: una sola conexión persistente para todo el puesto.
    // Antes eran tres —técnica, Moderación y Recinto— y con las cuatro superficies
    // abiertas el navegador se quedaba sin conexiones HTTP/1.1 para los comandos REST.
    const tecnico = crearClienteSuscribible()

    const sincronizacion = crearSincronizacionTecnica({
      cliente: tecnico.cliente as unknown as ClienteApoyoTecnico,
    })
    sincronizacion.iniciar()
    sincronizacion.iniciar()

    expect(tecnico.cliente.suscribirEstado).toHaveBeenCalledTimes(1)
  })

  it('vuelve a suscribirse después de cancelar, sin dejar la anterior viva', () => {
    // Cleanup idempotente: cancelar dos veces no falla y reiniciar abre una sola conexión
    // nueva, de modo que un ciclo montar/desmontar no acumule streams abiertos.
    const tecnico = crearClienteSuscribible()
    const sincronizacion = crearSincronizacionTecnica({
      cliente: tecnico.cliente as unknown as ClienteApoyoTecnico,
    })

    sincronizacion.iniciar()
    sincronizacion.cancelar()
    sincronizacion.cancelar()
    sincronizacion.iniciar()

    expect(tecnico.cliente.suscribirEstado).toHaveBeenCalledTimes(2)
    expect(tecnico.cancelado()).toBe(true)
  })

  it('reconstruye los controles desde el snapshot autoritativo', () => {
    const tecnico = crearClienteSuscribible()
    const sincronizacion = crearSincronizacionTecnica({
      cliente: tecnico.cliente as unknown as ClienteApoyoTecnico,
    })
    sincronizacion.iniciar()

    tecnico.cambiarConexion(true)
    tecnico.emitir(
      crearEstadoTecnicoPrueba({
        revision: 12,
        transmision: crearTransmisionPrueba({ estado: 'EN_VIVO' }),
        aviso_recinto: crearAvisoPrueba({ texto: 'Volvemos enseguida', destino: 'RECINTO' }),
      }),
    )

    expect(sincronizacion.conectado.value).toBe(true)
    expect(sincronizacion.revision.value).toBe(12)
    expect(sincronizacion.estado.value?.transmision.estado).toBe('EN_VIVO')
    expect(sincronizacion.estado.value?.aviso_recinto?.texto).toBe('Volvemos enseguida')
  })

  it('recibe remapeo y sonorización dentro del mismo snapshot (WP-074)', () => {
    // Las dos porciones que antes exigían un stream propio llegan ahora en el estado
    // técnico, y con la misma revisión que el resto de los paneles.
    const tecnico = crearClienteSuscribible()
    const sincronizacion = crearSincronizacionTecnica({
      cliente: tecnico.cliente as unknown as ClienteApoyoTecnico,
    })
    sincronizacion.iniciar()

    tecnico.cambiarConexion(true)
    tecnico.emitir(crearEstadoTecnicoPrueba({ revision: 20, estado_global: 'PREPARANDO' }))

    const estado = sincronizacion.estado.value
    expect(estado?.remapeo.concejales.map((concejal) => concejal.dispositivo_votacion)).toEqual([
      'dev01',
      'dev02',
    ])
    expect(estado?.remapeo.capacidades.iniciar_remapeo.habilitada).toBe(true)
    expect(estado?.sonorizacion.revision).toBe(20)
    expect(estado?.sonorizacion.sonidos.sonidos).toHaveLength(15)
  })

  it('conserva el último estado confirmado y lo marca desactualizado al desconectarse', () => {
    const tecnico = crearClienteSuscribible()
    const sincronizacion = crearSincronizacionTecnica({
      cliente: tecnico.cliente as unknown as ClienteApoyoTecnico,
    })
    sincronizacion.iniciar()

    tecnico.cambiarConexion(true)
    tecnico.emitir(crearEstadoTecnicoPrueba({ revision: 3 }))
    tecnico.cambiarConexion(false)

    expect(sincronizacion.estadoConexion.value).toBe('RECONECTANDO')
    expect(sincronizacion.desactualizado.value).toBe(true)
    expect(sincronizacion.estado.value?.revision).toBe(3)
  })

  it('informa DESCONECTADO si nunca hubo un snapshot previo', () => {
    const tecnico = crearClienteSuscribible()
    const sincronizacion = crearSincronizacionTecnica({
      cliente: tecnico.cliente as unknown as ClienteApoyoTecnico,
    })
    sincronizacion.iniciar()

    tecnico.cambiarConexion(false)

    expect(sincronizacion.estadoConexion.value).toBe('DESCONECTADO')
    expect(sincronizacion.desactualizado.value).toBe(false)
  })

  it('cancela la suscripción sin borrar el último estado visible', () => {
    const tecnico = crearClienteSuscribible()
    const sincronizacion = crearSincronizacionTecnica({
      cliente: tecnico.cliente as unknown as ClienteApoyoTecnico,
    })
    sincronizacion.iniciar()
    tecnico.emitir(crearEstadoTecnicoPrueba({ revision: 8 }))

    sincronizacion.cancelar()

    expect(tecnico.cancelado()).toBe(true)
    expect(sincronizacion.estado.value?.revision).toBe(8)
  })
})
