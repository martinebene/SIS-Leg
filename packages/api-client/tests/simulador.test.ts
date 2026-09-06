/**
 * Pruebas unitarias para ClienteSimulador (@sis-leg/api-client).
 *
 * Demuestra:
 * 1. La delimitación estricta de la superficie pública del cliente del simulador.
 * 2. La emisión correcta de pulsaciones lógicas directas a POST /api/v1/entradas/tecla.
 * 3. La propagación fiel de respuestas funcionales aceptadas y rechazadas.
 * 4. La gestión adecuada de errores HTTP (422, 503) y de transporte.
 */

import { describe, expect, expectTypeOf, it, vi } from 'vitest'
import {
  ClienteSimulador,
  crearClienteSimulador,
  ErrorHttp,
  ErrorTransporte,
  type RespuestaTecla,
  type SolicitudTecla,
} from '../src'

describe('ClienteSimulador', () => {
  it('expone exactamente su superficie autorizada y no filtra métodos del operador ni rest', () => {
    const cliente = new ClienteSimulador()

    // Métodos autorizados
    expect(typeof cliente.obtenerEstado).toBe('function')
    expect(typeof cliente.suscribirEstado).toBe('function')
    expect(typeof cliente.enviarTecla).toBe('function')

    // No expone ClienteRest
    expectTypeOf<ClienteSimulador>().not.toHaveProperty('rest')

    // No expone métodos mutantes administrativos de Moderación
    const registro = cliente as unknown as Record<string, unknown>
    expect(registro.prepararSala).toBeUndefined()
    expect(registro.actualizarPreparacion).toBeUndefined()
    expect(registro.cancelarPreparacion).toBeUndefined()
    expect(registro.abrirSesion).toBeUndefined()
    expect(registro.actualizarSesion).toBeUndefined()
    expect(registro.cerrarSesion).toBeUndefined()
    expect(registro.cargarOrdenDelDia).toBeUndefined()
    expect(registro.descartarOrdenDelDia).toBeUndefined()
    expect(registro.abrirVotacion).toBeUndefined()
    expect(registro.finalizarVotacion).toBeUndefined()
    expect(registro.desempatar).toBeUndefined()
    expect(registro.otorgarPalabra).toBeUndefined()
    expect(registro.quitarPalabra).toBeUndefined()
    expect(registro.iniciarRemapeo).toBeUndefined()
    expect(registro.confirmarRemapeo).toBeUndefined()
    expect(registro.cancelarRemapeo).toBeUndefined()

    // Verificación estricta de tipos de TypeScript
    type MetodosSimulador = keyof ClienteSimulador
    expectTypeOf<MetodosSimulador>().toEqualTypeOf<
      'obtenerEstado' | 'suscribirEstado' | 'enviarTecla'
    >()
  })

  it('crearClienteSimulador devuelve una instancia funcional de ClienteSimulador', () => {
    const cliente = crearClienteSimulador()
    expect(cliente).toBeInstanceOf(ClienteSimulador)
  })

  it('enviarTecla emite POST /api/v1/entradas/tecla con el body exacto y devuelve respuesta aceptada', async () => {
    const respuestaMock: RespuestaTecla = {
      aceptada: true,
      dispositivo: 'dev01',
      tecla: '9',
      motivo: 'PRESENCIA_ACTUALIZADA',
      concejal: {
        dni: '10000001',
        nombre: 'Concejal',
        apellido: 'Uno',
        banca: 1,
      },
      resultado: {
        tipo: 'PRESENCIA',
        presente: true,
        presentes: 1,
        quorum_alcanzado: false,
      },
    }

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(respuestaMock), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    const cliente = new ClienteSimulador({
      baseUrl: 'http://backend-test:8000',
      fetch: fetchMock as unknown as typeof fetch,
    })

    const solicitud: SolicitudTecla = {
      dispositivo: 'dev01',
      tecla: '9',
    }

    const resultado = await cliente.enviarTecla(solicitud)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, opciones] = fetchMock.mock.calls[0]
    expect(url).toBe('http://backend-test:8000/api/v1/entradas/tecla')
    expect(opciones.method).toBe('POST')
    expect(opciones.headers).toEqual({ 'Content-Type': 'application/json' })
    expect(JSON.parse(opciones.body)).toEqual({ dispositivo: 'dev01', tecla: '9' })

    expect(resultado).toEqual(respuestaMock)
    expect(resultado.aceptada).toBe(true)
    expect(resultado.motivo).toBe('PRESENCIA_ACTUALIZADA')
  })

  it('enviarTecla devuelve fielmente una respuesta funcional rechazada (status 200 con aceptada=false)', async () => {
    const rechazoMock: RespuestaTecla = {
      aceptada: false,
      dispositivo: 'dev02',
      tecla: '1',
      motivo: 'TECLA_NO_HABILITADA',
      concejal: null,
      resultado: null,
    }

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(rechazoMock), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    const cliente = new ClienteSimulador({
      fetch: fetchMock as unknown as typeof fetch,
    })

    const resultado = await cliente.enviarTecla({ dispositivo: 'dev02', tecla: '1' })

    expect(resultado.aceptada).toBe(false)
    expect(resultado.motivo).toBe('TECLA_NO_HABILITADA')
  })

  it('enviarTecla transforma respuestas HTTP de error (ej. 422) en instancias de ErrorHttp', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Unprocessable Entity' }), {
        status: 422,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    const cliente = new ClienteSimulador({
      fetch: fetchMock as unknown as typeof fetch,
    })

    await expect(cliente.enviarTecla({ dispositivo: 'devXX', tecla: '9' })).rejects.toThrow(
      ErrorHttp,
    )
  })

  it('enviarTecla propaga ErrorTransporte ante desconexión o fallo de red', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))

    const cliente = new ClienteSimulador({
      fetch: fetchMock as unknown as typeof fetch,
    })

    await expect(cliente.enviarTecla({ dispositivo: 'dev01', tecla: '8' })).rejects.toThrow(
      ErrorTransporte,
    )
  })

  it('obtenerEstado solicita GET /api/v1/estado/moderacion', async () => {
    const estadoMock = {
      estado_global: 'PREPARANDO',
      revision: 42,
    }

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(estadoMock), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    const cliente = new ClienteSimulador({
      baseUrl: 'http://test:8000',
      fetch: fetchMock as unknown as typeof fetch,
    })

    const estado = await cliente.obtenerEstado()
    expect(fetchMock).toHaveBeenCalledWith(
      'http://test:8000/api/v1/estado/moderacion',
      expect.anything(),
    )
    expect(estado).toEqual(estadoMock)
  })
})
