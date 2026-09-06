/** Pruebas de la frontera Vue sobre el ciclo REST + SSE del ClienteRecinto. */

import { describe, expect, it, vi } from 'vitest'
import type { ClienteRecinto, EstadoRecinto, OpcionesSuscripcion } from '@sis-leg/api-client'
import { crearSincronizacionRecinto } from '../app/composables/useEstadoRecinto'
import { crearEstadoRecintoPrueba } from './datos_prueba'

function crearClienteControlado() {
  let callbacks: OpcionesSuscripcion<EstadoRecinto> | null = null
  let activa = true
  const cancelar = vi.fn(() => {
    activa = false
  })
  const cliente = {
    suscribirEstado: vi.fn((opciones: OpcionesSuscripcion<EstadoRecinto>) => {
      callbacks = opciones
      return {
        cancelar,
        get activa() {
          return activa
        },
      }
    }),
  } as unknown as ClienteRecinto

  return {
    cliente,
    cancelar,
    callbacks: () => {
      if (!callbacks) throw new Error('La prueba todavía no inició la suscripción')
      return callbacks
    },
  }
}

describe('crearSincronizacionRecinto', () => {
  it('comienza sin snapshot y adopta el primero antes de confirmar el SSE', () => {
    const control = crearClienteControlado()
    const sincronizacion = crearSincronizacionRecinto({
      cliente: control.cliente,
      autoIniciar: true,
    })

    expect(sincronizacion.estado.value).toBeNull()
    expect(sincronizacion.estadoConexion.value).toBe('INICIAL')

    const preparando = crearEstadoRecintoPrueba({
      revision: 4,
      estado_global: 'PREPARANDO',
      filas_bancas: [5, 7],
    })
    control.callbacks().alEstado(preparando)

    expect(sincronizacion.estado.value).toEqual(preparando)
    expect(sincronizacion.estadoGlobal.value).toBe('PREPARANDO')
    control.callbacks().alCambiarConexion?.(true)
    expect(sincronizacion.estadoConexion.value).toBe('CONECTADO')
  })

  it('conserva la última vista durante reconexión y adopta una baseline nueva', () => {
    const control = crearClienteControlado()
    const sincronizacion = crearSincronizacionRecinto({
      cliente: control.cliente,
      autoIniciar: true,
    })
    const sesion = crearEstadoRecintoPrueba({ revision: 91, estado_global: 'SESION_ABIERTA' })
    control.callbacks().alEstado(sesion)
    control.callbacks().alCambiarConexion?.(true)

    control.callbacks().alCambiarConexion?.(false)
    expect(sincronizacion.estado.value).toEqual(sesion)
    expect(sincronizacion.desactualizado.value).toBe(true)

    const reinicio = crearEstadoRecintoPrueba({ revision: 0, estado_global: 'SIN_PREPARAR' })
    control.callbacks().alEstado(reinicio)
    control.callbacks().alCambiarConexion?.(true)
    expect(sincronizacion.estado.value).toEqual(reinicio)
    expect(sincronizacion.estadoGlobal.value).toBe('SIN_PREPARAR')
    expect(sincronizacion.desactualizado.value).toBe(false)
  })

  it('marca desconexión inicial, registra el error y cancela determinísticamente', () => {
    const control = crearClienteControlado()
    const sincronizacion = crearSincronizacionRecinto({
      cliente: control.cliente,
      autoIniciar: true,
    })
    const error = new Error('Backend no disponible')

    control.callbacks().alError?.(error)
    expect(sincronizacion.estadoConexion.value).toBe('DESCONECTADO')
    expect(sincronizacion.ultimoError.value).toBe(error)

    sincronizacion.cancelar()
    expect(control.cancelar).toHaveBeenCalledTimes(1)
    expect(sincronizacion.estadoConexion.value).toBe('DESCONECTADO')
  })

  it('no duplica una suscripción activa', () => {
    const control = crearClienteControlado()
    const sincronizacion = crearSincronizacionRecinto({ cliente: control.cliente })

    sincronizacion.iniciar()
    sincronizacion.iniciar()

    expect(control.cliente.suscribirEstado).toHaveBeenCalledTimes(1)
  })
})
