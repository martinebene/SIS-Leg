import { describe, expect, it, vi } from 'vitest'
import {
  ClienteModeracion,
  ClienteRecinto,
  ErrorProtocolo,
  ErrorTransporte,
  SincronizadorEstado,
  type EstadoModeracion,
} from '../src'
import {
  INSTANCIA_PRUEBA_A,
  INSTANCIA_PRUEBA_B,
  crearMockEstadoModeracion,
  crearMockEstadoRecinto,
} from './helpers/datos_prueba'
import { MockEventSource } from './helpers/mock_event_source'

describe('Sincronizador reactivo y protocolo SSE', () => {
  it('obtiene el snapshot inicial REST antes de abrir la conexión EventSource', async () => {
    const ordenLlamadas: string[] = []
    const estadoInicial = crearMockEstadoModeracion(10)

    const mockFetch = vi.fn().mockImplementation(() => {
      ordenLlamadas.push('FETCH_SNAPSHOT')
      return Promise.resolve(new Response(JSON.stringify(estadoInicial), { status: 200 }))
    })

    let mockEs: MockEventSource | null = null
    const fabricaEs = vi.fn().mockImplementation((url: string) => {
      ordenLlamadas.push('CREAR_EVENT_SOURCE')
      mockEs = new MockEventSource(url)
      return mockEs
    })

    const cliente = new ClienteModeracion({
      baseUrl: 'http://api.test',
      fetch: mockFetch,
      fabricaEventSource: fabricaEs,
    })

    const estadosRecibidos: number[] = []
    const suscripcion = cliente.suscribirEstado({
      alEstado: (estado) => estadosRecibidos.push(estado.revision),
    })

    // Permitimos que la promesa del fetch se resuelva
    await vi.waitFor(() => {
      expect(estadosRecibidos).toEqual([10])
    })

    expect(ordenLlamadas).toEqual(['FETCH_SNAPSHOT', 'CREAR_EVENT_SOURCE'])
    expect(fabricaEs).toHaveBeenCalledWith('http://api.test/api/v1/estado/moderacion/stream')

    suscripcion.cancelar()
  })

  it('procesa el primer evento SSE como estado completo y avanza revisión ante mutación intermedia', async () => {
    // Escenario de carrera: Snapshot rev 10 -> mutación -> primer SSE rev 11
    const snapshotRev10 = crearMockEstadoModeracion(10)
    const sseRev11 = crearMockEstadoModeracion(11)

    const mockFetch = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(snapshotRev10), { status: 200 }))

    let instanciaEs: MockEventSource | null = null
    const fabricaEs = vi.fn().mockImplementation((url: string) => {
      instanciaEs = new MockEventSource(url)
      return instanciaEs
    })

    const cliente = new ClienteModeracion({
      fetch: mockFetch,
      fabricaEventSource: fabricaEs,
    })

    const revisionesRecibidas: number[] = []
    const suscripcion = cliente.suscribirEstado({
      alEstado: (e) => revisionesRecibidas.push(e.revision),
    })

    await vi.waitFor(() => {
      expect(revisionesRecibidas).toEqual([10])
      expect(instanciaEs).not.toBeNull()
    })

    instanciaEs!.simularApertura()
    instanciaEs!.simularEvento('estado', sseRev11)

    expect(revisionesRecibidas).toEqual([10, 11])

    suscripcion.cancelar()
  })

  it('descarta revisiones anteriores y acepta revisiones iguales o saltos dentro de la baseline', async () => {
    const snapshot = crearMockEstadoModeracion(10)
    const mockFetch = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(snapshot), { status: 200 }))

    let instanciaEs: MockEventSource | null = null
    const fabricaEs = vi.fn().mockImplementation((url: string) => {
      instanciaEs = new MockEventSource(url)
      return instanciaEs
    })

    const cliente = new ClienteModeracion({
      fetch: mockFetch,
      fabricaEventSource: fabricaEs,
    })

    const revisiones: number[] = []
    const suscripcion = cliente.suscribirEstado({
      alEstado: (e) => revisiones.push(e.revision),
    })

    await vi.waitFor(() => expect(instanciaEs).not.toBeNull())

    // 1. Revision menor (rev 9): debe descartarse
    instanciaEs!.simularEvento('estado', crearMockEstadoModeracion(9))
    expect(revisiones).toEqual([10])

    // 2. Revision igual (rev 10): tratada idempotentemente
    instanciaEs!.simularEvento('estado', crearMockEstadoModeracion(10))
    expect(revisiones).toEqual([10, 10])

    // 3. Salto de revisión (rev 15 sin pasar por 11, 12, 13, 14): válido y aceptado
    instanciaEs!.simularEvento('estado', crearMockEstadoModeracion(15))
    expect(revisiones).toEqual([10, 10, 15])

    suscripcion.cancelar()
  })

  it('cierra el EventSource fallado inmediatamente ante error SSE y ejecuta recovery con snapshot', async () => {
    let llamadasFetch = 0
    const mockFetch = vi.fn().mockImplementation(() => {
      llamadasFetch++
      const rev = llamadasFetch === 1 ? 10 : 12
      return Promise.resolve(
        new Response(JSON.stringify(crearMockEstadoModeracion(rev)), { status: 200 }),
      )
    })

    const instanciasEs: MockEventSource[] = []
    const fabricaEs = vi.fn().mockImplementation((url: string) => {
      const es = new MockEventSource(url)
      instanciasEs.push(es)
      return es
    })

    const temporizadorInmediato = vi.fn().mockResolvedValue(undefined)

    const cliente = new ClienteModeracion({
      fetch: mockFetch,
      fabricaEventSource: fabricaEs,
      backoff: {
        temporizador: temporizadorInmediato,
      },
    })

    const revisiones: number[] = []
    const errores: unknown[] = []
    const cambiosConexion: boolean[] = []

    const suscripcion = cliente.suscribirEstado({
      alEstado: (e) => revisiones.push(e.revision),
      alError: (err) => errores.push(err),
      alCambiarConexion: (c) => cambiosConexion.push(c),
    })

    await vi.waitFor(() => {
      expect(instanciasEs.length).toBe(1)
      expect(revisiones).toEqual([10])
    })

    instanciasEs[0].simularApertura()
    expect(cambiosConexion).toContain(true)

    // Simulamos fallo del stream
    instanciasEs[0].simularError()

    // Verificamos que se cerró inmediatamente la primera instancia
    expect(instanciasEs[0].cerrado).toBe(true)

    // Debe haberse disparado el recovery: fetch snapshot nuevo -> nuevo EventSource
    await vi.waitFor(() => {
      expect(instanciasEs.length).toBe(2)
      expect(revisiones).toEqual([10, 12])
    })

    expect(temporizadorInmediato).toHaveBeenCalled()
    expect(mockFetch).toHaveBeenCalledTimes(2)

    suscripcion.cancelar()
    expect(instanciasEs[1].cerrado).toBe(true)
  })

  it('fuerza recuperación segura ante evento SSE con JSON corrupto o malformado', async () => {
    let llamadasFetch = 0
    const mockFetch = vi.fn().mockImplementation(() => {
      llamadasFetch++
      return Promise.resolve(
        new Response(JSON.stringify(crearMockEstadoModeracion(llamadasFetch * 10)), {
          status: 200,
        }),
      )
    })

    const instanciasEs: MockEventSource[] = []
    const fabricaEs = vi.fn().mockImplementation((url: string) => {
      const es = new MockEventSource(url)
      instanciasEs.push(es)
      return es
    })

    const cliente = new ClienteModeracion({
      fetch: mockFetch,
      fabricaEventSource: fabricaEs,
      backoff: {
        temporizador: vi.fn().mockResolvedValue(undefined),
      },
    })

    const revisiones: number[] = []
    const errores: unknown[] = []

    const suscripcion = cliente.suscribirEstado({
      alEstado: (e) => revisiones.push(e.revision),
      alError: (err) => errores.push(err),
    })

    await vi.waitFor(() => expect(instanciasEs.length).toBe(1))

    // Enviamos JSON malformado
    instanciasEs[0].simularEvento('estado', '{ corrupt json ...')

    // La instancia corrupta debe cerrarse y reportarse ErrorProtocolo
    expect(instanciasEs[0].cerrado).toBe(true)

    await vi.waitFor(() => {
      expect(instanciasEs.length).toBe(2)
      expect(revisiones).toEqual([10, 20])
    })

    expect(errores.some((e) => e instanceof ErrorProtocolo)).toBe(true)

    suscripcion.cancelar()
  })

  it('soporta cancelación (dispose) durante conexión activa', async () => {
    const mockFetch = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify(crearMockEstadoModeracion(1)), { status: 200 }),
      )

    let instanciaEs: MockEventSource | null = null
    const fabricaEs = vi.fn().mockImplementation((url: string) => {
      instanciaEs = new MockEventSource(url)
      return instanciaEs
    })

    const cliente = new ClienteModeracion({
      fetch: mockFetch,
      fabricaEventSource: fabricaEs,
    })

    const suscripcion = cliente.suscribirEstado({
      alEstado: vi.fn(),
    })

    await vi.waitFor(() => expect(instanciaEs).not.toBeNull())

    expect(suscripcion.activa).toBe(true)
    suscripcion.cancelar()

    expect(suscripcion.activa).toBe(false)
    expect(instanciaEs!.cerrado).toBe(true)

    // Cancelar repetidamente es idempotente y seguro
    expect(() => suscripcion.cancelar()).not.toThrow()
  })

  it('soporta cancelación (dispose) durante espera de backoff y durante snapshot de recuperación', async () => {
    let resolverTimer: (() => void) | undefined
    const temporizadorPausado = vi.fn().mockImplementation(() => {
      return new Promise<void>((resolve) => {
        resolverTimer = resolve
      })
    })

    const mockFetch = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify(crearMockEstadoModeracion(1)), { status: 200 }),
      )

    let instanciaEs: MockEventSource | null = null
    const fabricaEs = vi.fn().mockImplementation((url: string) => {
      instanciaEs = new MockEventSource(url)
      return instanciaEs
    })

    const cliente = new ClienteModeracion({
      fetch: mockFetch,
      fabricaEventSource: fabricaEs,
      backoff: { temporizador: temporizadorPausado },
    })

    const suscripcion = cliente.suscribirEstado({ alEstado: vi.fn() })

    await vi.waitFor(() => expect(instanciaEs).not.toBeNull())

    // Provocamos error en SSE para entrar en backoff
    instanciaEs!.simularError()

    await vi.waitFor(() => expect(temporizadorPausado).toHaveBeenCalled())

    // Cancelamos durante el backoff
    suscripcion.cancelar()
    expect(suscripcion.activa).toBe(false)

    // Si el timer se resolviera más tarde, no debe continuar
    if (resolverTimer) {
      ;(resolverTimer as () => void)()
    }
    expect(fabricaEs).toHaveBeenCalledTimes(1)
  })

  it('no emite callbacks al consumidor después de la cancelación', async () => {
    const mockFetch = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify(crearMockEstadoModeracion(1)), { status: 200 }),
      )

    let instanciaEs: MockEventSource | null = null
    const fabricaEs = vi.fn().mockImplementation((url: string) => {
      instanciaEs = new MockEventSource(url)
      return instanciaEs
    })

    const cliente = new ClienteModeracion({
      fetch: mockFetch,
      fabricaEventSource: fabricaEs,
    })

    const alEstado = vi.fn()
    const suscripcion = cliente.suscribirEstado({ alEstado })

    await vi.waitFor(() => expect(alEstado).toHaveBeenCalledTimes(1))

    suscripcion.cancelar()

    // Intentamos emitir un evento posterior
    instanciaEs!.simularEvento('estado', crearMockEstadoModeracion(2))
    expect(alEstado).toHaveBeenCalledTimes(1)
  })

  it('protege el ciclo interno ante excepciones en el callback del consumidor', async () => {
    const mockFetch = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify(crearMockEstadoModeracion(1)), { status: 200 }),
      )

    let instanciaEs: MockEventSource | null = null
    const fabricaEs = vi.fn().mockImplementation((url: string) => {
      instanciaEs = new MockEventSource(url)
      return instanciaEs
    })

    const cliente = new ClienteModeracion({
      fetch: mockFetch,
      fabricaEventSource: fabricaEs,
    })

    const callbackConError = vi.fn().mockImplementation(() => {
      throw new Error('Fallo voluntario en UI')
    })

    const alError = vi.fn()
    const suscripcion = cliente.suscribirEstado({
      alEstado: callbackConError,
      alError,
    })

    await vi.waitFor(() => expect(instanciaEs).not.toBeNull())

    // El error en alEstado debe notificarse a alError sin quebrar la instancia
    expect(alError).toHaveBeenCalled()
    expect(suscripcion.activa).toBe(true)

    suscripcion.cancelar()
  })
})

/**
 * Continuidad de sincronización tras un reinicio del backend (WP-080).
 *
 * El escenario que estas pruebas fijan no es el de una caída visible del stream: ése ya
 * estaba cubierto por el ciclo de recuperación. Acá el backend reinicia en la ventana que
 * va entre el snapshot REST y la apertura del `EventSource`, así que el cliente nunca
 * recibe un `onerror` y la conexión que abre es sana desde el primer instante.
 */
describe('Continuidad de instancia del backend tras reinicio (WP-080)', () => {
  it('adopta el estado de una instancia nueva aunque su revisión sea menor y sin onerror previo', async () => {
    // Proceso A ya venía trabajando hace rato: su contador llegó a 142.
    const snapshotInstanciaA = crearMockEstadoModeracion(142, 'SESION_ABIERTA', INSTANCIA_PRUEBA_A)
    // El backend reinicia antes de que abra el stream. El proceso B arranca de cero.
    const eventoInstanciaB = crearMockEstadoModeracion(0, 'SIN_PREPARAR', INSTANCIA_PRUEBA_B)

    const mockFetch = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(snapshotInstanciaA), { status: 200 }))

    let instanciaEs: MockEventSource | null = null
    const fabricaEs = vi.fn().mockImplementation((url: string) => {
      instanciaEs = new MockEventSource(url)
      return instanciaEs
    })

    const cliente = new ClienteModeracion({ fetch: mockFetch, fabricaEventSource: fabricaEs })

    const adoptados: EstadoModeracion[] = []
    const errores: unknown[] = []
    const suscripcion = cliente.suscribirEstado({
      alEstado: (estado) => adoptados.push(estado),
      alError: (error) => errores.push(error),
    })

    await vi.waitFor(() => {
      expect(adoptados).toHaveLength(1)
      expect(instanciaEs).not.toBeNull()
    })

    // El stream abre sano contra el backend nuevo: no hay ningún error de transporte.
    instanciaEs!.simularApertura()
    instanciaEs!.simularEvento('estado', eventoInstanciaB)

    // La revisión 0 es menor que 142, pero pertenece a otra instancia: se adopta.
    expect(adoptados).toHaveLength(2)
    expect(adoptados[1].revision).toBe(0)
    expect(adoptados[1].instancia).toBe(INSTANCIA_PRUEBA_B)
    expect(adoptados[1].estado_global).toBe('SIN_PREPARAR')
    // No hizo falta ningún error ni ninguna reconexión para rebaselinar.
    expect(errores).toEqual([])
    expect(instanciaEs!.cerrado).toBe(false)
    expect(mockFetch).toHaveBeenCalledTimes(1)

    suscripcion.cancelar()
  })

  it('sigue descartando revisiones menores mientras la instancia no cambia', async () => {
    const snapshot = crearMockEstadoModeracion(142, 'SESION_ABIERTA', INSTANCIA_PRUEBA_A)
    const mockFetch = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(snapshot), { status: 200 }))

    let instanciaEs: MockEventSource | null = null
    const fabricaEs = vi.fn().mockImplementation((url: string) => {
      instanciaEs = new MockEventSource(url)
      return instanciaEs
    })

    const cliente = new ClienteModeracion({ fetch: mockFetch, fabricaEventSource: fabricaEs })

    const revisiones: number[] = []
    const suscripcion = cliente.suscribirEstado({
      alEstado: (estado) => revisiones.push(estado.revision),
    })

    await vi.waitFor(() => expect(instanciaEs).not.toBeNull())
    instanciaEs!.simularApertura()

    // Evento atrasado del MISMO proceso: se descarta, igual que antes de WP-080.
    instanciaEs!.simularEvento(
      'estado',
      crearMockEstadoModeracion(141, 'SESION_ABIERTA', INSTANCIA_PRUEBA_A),
    )
    expect(revisiones).toEqual([142])

    // Revisión posterior del mismo proceso: se adopta con normalidad.
    instanciaEs!.simularEvento(
      'estado',
      crearMockEstadoModeracion(143, 'SESION_ABIERTA', INSTANCIA_PRUEBA_A),
    )
    expect(revisiones).toEqual([142, 143])

    suscripcion.cancelar()
  })

  it('vuelve a comparar revisiones dentro de la instancia nueva una vez adoptada', async () => {
    const snapshot = crearMockEstadoModeracion(142, 'SESION_ABIERTA', INSTANCIA_PRUEBA_A)
    const mockFetch = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(snapshot), { status: 200 }))

    let instanciaEs: MockEventSource | null = null
    const fabricaEs = vi.fn().mockImplementation((url: string) => {
      instanciaEs = new MockEventSource(url)
      return instanciaEs
    })

    const cliente = new ClienteModeracion({ fetch: mockFetch, fabricaEventSource: fabricaEs })

    const revisiones: number[] = []
    const suscripcion = cliente.suscribirEstado({
      alEstado: (estado) => revisiones.push(estado.revision),
    })

    await vi.waitFor(() => expect(instanciaEs).not.toBeNull())
    instanciaEs!.simularApertura()

    // Rebaseline por cambio de instancia: la revisión vigente pasa a ser la de B.
    instanciaEs!.simularEvento(
      'estado',
      crearMockEstadoModeracion(5, 'SIN_PREPARAR', INSTANCIA_PRUEBA_B),
    )
    // Un evento atrasado de B se descarta: dentro de B la revisión volvió a ser monotónica.
    instanciaEs!.simularEvento(
      'estado',
      crearMockEstadoModeracion(4, 'SIN_PREPARAR', INSTANCIA_PRUEBA_B),
    )
    // Y una revisión mayor de B se adopta.
    instanciaEs!.simularEvento(
      'estado',
      crearMockEstadoModeracion(6, 'PREPARANDO', INSTANCIA_PRUEBA_B),
    )

    expect(revisiones).toEqual([142, 5, 6])

    suscripcion.cancelar()
  })

  it('trata un payload SSE sin instancia como violación de contrato y se recupera', async () => {
    let llamadasFetch = 0
    const mockFetch = vi.fn().mockImplementation(() => {
      llamadasFetch++
      return Promise.resolve(
        new Response(JSON.stringify(crearMockEstadoModeracion(llamadasFetch * 10)), {
          status: 200,
        }),
      )
    })

    const instanciasEs: MockEventSource[] = []
    const fabricaEs = vi.fn().mockImplementation((url: string) => {
      const fuente = new MockEventSource(url)
      instanciasEs.push(fuente)
      return fuente
    })

    const cliente = new ClienteModeracion({
      fetch: mockFetch,
      fabricaEventSource: fabricaEs,
      backoff: { temporizador: vi.fn().mockResolvedValue(undefined) },
    })

    const revisiones: number[] = []
    const errores: unknown[] = []
    const suscripcion = cliente.suscribirEstado({
      alEstado: (estado) => revisiones.push(estado.revision),
      alError: (error) => errores.push(error),
    })

    await vi.waitFor(() => expect(instanciasEs.length).toBe(1))

    // Payload con revisión válida pero sin la mitad que hace comparable esa revisión.
    const sinInstancia = crearMockEstadoModeracion(11) as Partial<EstadoModeracion>
    delete sinInstancia.instancia
    instanciasEs[0].simularEvento('estado', sinInstancia)

    // No se adopta a ciegas: se cierra el stream y se recupera con un snapshot completo.
    await vi.waitFor(() => {
      expect(instanciasEs.length).toBe(2)
      expect(revisiones).toEqual([10, 20])
    })
    expect(errores[0]).toBeInstanceOf(ErrorProtocolo)

    suscripcion.cancelar()
  })
})
