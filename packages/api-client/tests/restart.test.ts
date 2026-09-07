import { describe, expect, it, vi } from 'vitest'
import { ClienteApoyoTecnico, ClienteModeracion, ClienteRecinto } from '../src'
import type { EstadoSincronizable, OpcionesSuscripcion, Suscripcion } from '../src'
import {
  INSTANCIA_PRUEBA_A,
  INSTANCIA_PRUEBA_B,
  crearMockEstadoModeracion,
  crearMockEstadoRecinto,
  crearMockEstadoTecnico,
} from './helpers/datos_prueba'
import { MockEventSource } from './helpers/mock_event_source'

describe('Caso crítico: Reinicio (Restart) del backend y nueva baseline', () => {
  it('acepta revisión 0 como nueva baseline tras caída del backend desde revisión 142', async () => {
    let llamadasFetch = 0

    // Estado antes de caer: revision 142, SESION_ABIERTA
    const estadoPrevio = crearMockEstadoModeracion(142, 'SESION_ABIERTA')

    // Estado tras reinicio del backend: revision 0, SIN_PREPARAR
    const estadoReinicio = crearMockEstadoModeracion(0, 'SIN_PREPARAR')

    // Estado siguiente en la nueva vida del proceso: revision 1, PREPARANDO
    const estadoSiguiente = crearMockEstadoModeracion(1, 'PREPARANDO')

    const mockFetch = vi.fn().mockImplementation(() => {
      llamadasFetch++
      if (llamadasFetch === 1) {
        return Promise.resolve(new Response(JSON.stringify(estadoPrevio), { status: 200 }))
      }
      return Promise.resolve(new Response(JSON.stringify(estadoReinicio), { status: 200 }))
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

    const historialEstados: Array<{ revision: number; estadoGlobal: string }> = []

    const suscripcion = cliente.suscribirEstado({
      alEstado: (e) =>
        historialEstados.push({
          revision: e.revision,
          estadoGlobal: e.estado_global,
        }),
    })

    // 1. Conexión inicial: adopta baseline previa revision 142
    await vi.waitFor(() => {
      expect(instanciasEs.length).toBe(1)
      expect(historialEstados).toHaveLength(1)
      expect(historialEstados[0]).toEqual({
        revision: 142,
        estadoGlobal: 'SESION_ABIERTA',
      })
    })

    instanciasEs[0].simularApertura()

    // 2. Ocurre caída del backend: el stream SSE se interrumpe
    instanciasEs[0].simularError()

    // 3. El cliente debe ejecutar recovery por snapshot REST
    // y aceptar revision 0 como NUEVA baseline sin descartarla por ser 0 < 142
    await vi.waitFor(() => {
      expect(instanciasEs.length).toBe(2)
      expect(historialEstados).toHaveLength(2)
      expect(historialEstados[1]).toEqual({
        revision: 0,
        estadoGlobal: 'SIN_PREPARAR',
      })
    })

    instanciasEs[1].simularApertura()

    // 4. El nuevo stream continúa desde la nueva baseline (revision 1)
    instanciasEs[1].simularEvento('estado', estadoSiguiente)

    expect(historialEstados).toHaveLength(3)
    expect(historialEstados[2]).toEqual({
      revision: 1,
      estadoGlobal: 'PREPARANDO',
    })

    suscripcion.cancelar()
  })

  it('permite a ClienteRecinto adoptar nueva baseline tras reinicio del servidor', async () => {
    let llamadasFetch = 0
    const previoRecinto = crearMockEstadoRecinto(88, 'SESION_ABIERTA')
    const reinicioRecinto = crearMockEstadoRecinto(0, 'SIN_PREPARAR')
    const siguienteRecinto = crearMockEstadoRecinto(1, 'PREPARANDO')

    const mockFetch = vi.fn().mockImplementation(() => {
      llamadasFetch++
      if (llamadasFetch === 1) {
        return Promise.resolve(new Response(JSON.stringify(previoRecinto), { status: 200 }))
      }
      return Promise.resolve(new Response(JSON.stringify(reinicioRecinto), { status: 200 }))
    })

    const instanciasEs: MockEventSource[] = []
    const fabricaEs = vi.fn().mockImplementation((url: string) => {
      const es = new MockEventSource(url)
      instanciasEs.push(es)
      return es
    })

    const cliente = new ClienteRecinto({
      fetch: mockFetch,
      fabricaEventSource: fabricaEs,
      backoff: {
        temporizador: vi.fn().mockResolvedValue(undefined),
      },
    })

    const revisiones: number[] = []
    const suscripcion = cliente.suscribirEstado({
      alEstado: (e) => revisiones.push(e.revision),
    })

    await vi.waitFor(() => expect(instanciasEs.length).toBe(1))
    expect(revisiones).toEqual([88])

    // Corte y recovery
    instanciasEs[0].simularError()

    await vi.waitFor(() => expect(instanciasEs.length).toBe(2))
    expect(revisiones).toEqual([88, 0])

    // Avanza en nuevo stream
    instanciasEs[1].simularEvento('estado', siguienteRecinto)
    expect(revisiones).toEqual([88, 0, 1])

    suscripcion.cancelar()
  })
})

/**
 * Reinicio **silencioso**: el backend se reinicia sin que el stream llegue a romperse.
 *
 * Es el hueco que WP-080 vino a cerrar. El caso de arriba se apoya en el `onerror` del
 * `EventSource`: la conexión cae, el cliente pide un snapshot nuevo y ese snapshot vale
 * como baseline. Pero si el reinicio ocurre en la ventana que va entre el snapshot REST y
 * la apertura del stream, la conexión que abre es contra el proceso **nuevo** y nunca
 * falla. Sin identidad de instancia, sus revisiones bajas se descartaban para siempre.
 *
 * La tabla recorre las tres superficies con exactamente el mismo guion para demostrar el
 * criterio de aceptación 4 del WP: Moderación, Recinto y Apoyo Técnico comparten la
 * semántica porque comparten el motor de sincronización, no porque cada una la reimplemente.
 */
describe('Reinicio silencioso entre snapshot REST y apertura del stream (WP-080)', () => {
  /** Firma común de las tres superficies, que es justamente lo que se quiere demostrar. */
  interface SuperficieSincronizable<T extends EstadoSincronizable> {
    suscribirEstado: (opciones: OpcionesSuscripcion<T>) => Suscripcion
  }

  const superficies = [
    {
      nombre: 'Moderación',
      snapshotProcesoA: crearMockEstadoModeracion(142, 'SESION_ABIERTA', INSTANCIA_PRUEBA_A),
      eventoProcesoB: crearMockEstadoModeracion(0, 'SIN_PREPARAR', INSTANCIA_PRUEBA_B),
      crearCliente: (configuracion: ConstructorParameters<typeof ClienteModeracion>[0]) =>
        new ClienteModeracion(configuracion) as SuperficieSincronizable<EstadoSincronizable>,
    },
    {
      nombre: 'Recinto',
      snapshotProcesoA: crearMockEstadoRecinto(88, 'SESION_ABIERTA', INSTANCIA_PRUEBA_A),
      eventoProcesoB: crearMockEstadoRecinto(0, 'SIN_PREPARAR', INSTANCIA_PRUEBA_B),
      crearCliente: (configuracion: ConstructorParameters<typeof ClienteRecinto>[0]) =>
        new ClienteRecinto(configuracion) as SuperficieSincronizable<EstadoSincronizable>,
    },
    {
      nombre: 'Apoyo Técnico',
      snapshotProcesoA: crearMockEstadoTecnico(57, 'SESION_ABIERTA', INSTANCIA_PRUEBA_A),
      eventoProcesoB: crearMockEstadoTecnico(0, 'SIN_PREPARAR', INSTANCIA_PRUEBA_B),
      crearCliente: (configuracion: ConstructorParameters<typeof ClienteApoyoTecnico>[0]) =>
        new ClienteApoyoTecnico(configuracion) as SuperficieSincronizable<EstadoSincronizable>,
    },
  ]

  for (const superficie of superficies) {
    it(`${superficie.nombre} adopta el proceso nuevo sin esperar un corte de conexión`, async () => {
      const mockFetch = vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify(superficie.snapshotProcesoA), { status: 200 }),
        )

      const instanciasEs: MockEventSource[] = []
      const fabricaEs = vi.fn().mockImplementation((url: string) => {
        const fuente = new MockEventSource(url)
        instanciasEs.push(fuente)
        return fuente
      })

      const cliente = superficie.crearCliente({ fetch: mockFetch, fabricaEventSource: fabricaEs })

      const adoptados: EstadoSincronizable[] = []
      const errores: unknown[] = []
      const suscripcion = cliente.suscribirEstado({
        alEstado: (estado) => adoptados.push(estado),
        alError: (error) => errores.push(error),
      })

      await vi.waitFor(() => expect(instanciasEs.length).toBe(1))
      expect(adoptados.map((estado) => estado.revision)).toEqual([
        superficie.snapshotProcesoA.revision,
      ])

      // El stream abre contra el proceso ya reiniciado y funciona perfectamente.
      instanciasEs[0].simularApertura()
      instanciasEs[0].simularEvento('estado', superficie.eventoProcesoB)

      // Se adopta la revisión menor porque viene de otra instancia.
      expect(adoptados).toHaveLength(2)
      expect(adoptados[1].revision).toBe(0)
      expect(adoptados[1].instancia).toBe(INSTANCIA_PRUEBA_B)

      // Y se adopta sin haber pedido un segundo snapshot ni haber visto un solo error.
      expect(mockFetch).toHaveBeenCalledTimes(1)
      expect(instanciasEs).toHaveLength(1)
      expect(errores).toEqual([])

      suscripcion.cancelar()
    })
  }
})
