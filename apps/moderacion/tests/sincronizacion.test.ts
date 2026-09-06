/**
 * Pruebas unitarias de la frontera reactiva de sincronización de Moderación.
 *
 * Demuestra:
 * 1. Estado inicial sin snapshot (no se inventa SIN_PREPARAR).
 * 2. Recepción del primer EstadoModeracion por snapshot.
 * 3. Actualización posterior por stream SSE.
 * 4. Transición a estado CONECTADO cuando el stream abre.
 * 5. Pérdida de conexión conservando el último estado confirmado y marcando desactualizado.
 * 6. Preservación del estado durante reconexión.
 * 7. Adopción de nueva baseline de recuperación incluso con revisión menor tras reinicio del backend.
 * 8. Manejo de error técnico sin borrar el estado confirmado existente.
 * 9. Cancelación determinista de la suscripción al invocar cancelar().
 * 10. Ausencia de suscripciones duplicadas ante llamadas consecutivas a iniciar().
 */

import { describe, it, expect, vi } from 'vitest'
import {
  crearSincronizacionModeracion,
  type EstadoConexion,
} from '../app/composables/useEstadoModeracion'
import type {
  ClienteModeracion,
  EstadoModeracion,
  OpcionesSuscripcion,
  Suscripcion,
} from '@sis-leg/api-client'

// Fixture pedagógica de EstadoModeracion para pruebas
function crearEstadoModeracionPrueba(parcial: Partial<EstadoModeracion> = {}): EstadoModeracion {
  return {
    revision: parcial.revision ?? 1,
    generado_en: parcial.generado_en ?? '2026-08-24T12:00:00Z',
    estado_global: parcial.estado_global ?? 'SIN_PREPARAR',
    preparacion: parcial.preparacion ?? null,
    sesion: parcial.sesion ?? null,
    configuracion: parcial.configuracion ?? null,
    concejales: parcial.concejales ?? [],
    quorum: parcial.quorum ?? null,
    votacion: parcial.votacion ?? null,
    palabra: parcial.palabra ?? null,
    orden_del_dia: parcial.orden_del_dia ?? [],
    eventos_recientes: parcial.eventos_recientes ?? [],
    auditoria: parcial.auditoria ?? {
      disponible: true,
      directorio: '/tmp',
      ultimo_error: null,
    },
    remapeo: parcial.remapeo ?? null,
    capacidades: parcial.capacidades ?? {
      preparar_sala: { habilitada: true, motivos: [] },
      actualizar_preparacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      cancelar_preparacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      abrir_sesion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      actualizar_sesion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      cerrar_sesion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      cargar_orden_del_dia: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      descartar_orden_del_dia: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      abrir_votacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      finalizar_votacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      desempatar: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      otorgar_palabra: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      quitar_palabra: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      iniciar_remapeo: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      confirmar_remapeo: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      cancelar_remapeo: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
    },
  }
}

describe('Frontera reactiva useEstadoModeracion / crearSincronizacionModeracion', () => {
  it('inicia en estado INICIAL sin snapshot ni estado global ficticio', () => {
    const mockCliente = {
      suscribirEstado: vi.fn(),
    } as unknown as ClienteModeracion

    const sincronizacion = crearSincronizacionModeracion({ cliente: mockCliente })

    expect(sincronizacion.estado.value).toBeNull()
    expect(sincronizacion.estadoConexion.value).toBe<EstadoConexion>('INICIAL')
    expect(sincronizacion.estadoGlobal.value).toBeNull()
    expect(sincronizacion.revision.value).toBeNull()
    expect(sincronizacion.conectado.value).toBe(false)
    expect(sincronizacion.desactualizado.value).toBe(false)
    expect(sincronizacion.ultimoError.value).toBeNull()
  })

  it('adopta el primer snapshot recibido y avanza con el stream SSE', () => {
    let callbacks: OpcionesSuscripcion<EstadoModeracion> | null = null
    const mockSuscripcion: Suscripcion = {
      cancelar: vi.fn(),
      activa: true,
    }

    const mockCliente = {
      suscribirEstado: vi.fn((ops) => {
        callbacks = ops
        return mockSuscripcion
      }),
    } as unknown as ClienteModeracion

    const sincronizacion = crearSincronizacionModeracion({
      cliente: mockCliente,
      autoIniciar: true,
    })

    expect(mockCliente.suscribirEstado).toHaveBeenCalledTimes(1)
    expect(callbacks).not.toBeNull()

    // 1. Llega primer snapshot
    const snapshotInicial = crearEstadoModeracionPrueba({
      revision: 10,
      estado_global: 'PREPARANDO',
    })
    callbacks!.alEstado(snapshotInicial)

    expect(sincronizacion.estado.value).toEqual(snapshotInicial)
    expect(sincronizacion.estadoGlobal.value).toBe('PREPARANDO')
    expect(sincronizacion.revision.value).toBe(10)

    // 2. Stream SSE confirma apertura
    callbacks!.alCambiarConexion?.(true)
    expect(sincronizacion.estadoConexion.value).toBe<EstadoConexion>('CONECTADO')
    expect(sincronizacion.conectado.value).toBe(true)
    expect(sincronizacion.desactualizado.value).toBe(false)

    // 3. Llega actualización SSE
    const estadoActualizado = crearEstadoModeracionPrueba({
      revision: 11,
      estado_global: 'SESION_ABIERTA',
    })
    callbacks!.alEstado(estadoActualizado)

    expect(sincronizacion.estado.value).toEqual(estadoActualizado)
    expect(sincronizacion.estadoGlobal.value).toBe('SESION_ABIERTA')
    expect(sincronizacion.revision.value).toBe(11)
  })

  it('conserva el último estado y marca desactualizado durante pérdida de conexión', () => {
    let callbacks: OpcionesSuscripcion<EstadoModeracion> | null = null
    const mockCliente = {
      suscribirEstado: vi.fn((ops) => {
        callbacks = ops
        return { cancelar: vi.fn(), activa: true }
      }),
    } as unknown as ClienteModeracion

    const sincronizacion = crearSincronizacionModeracion({
      cliente: mockCliente,
      autoIniciar: true,
    })

    // Establecemos estado previo
    const estadoPrevio = crearEstadoModeracionPrueba({
      revision: 45,
      estado_global: 'SESION_ABIERTA',
    })
    callbacks!.alEstado(estadoPrevio)
    callbacks!.alCambiarConexion?.(true)

    expect(sincronizacion.conectado.value).toBe(true)
    expect(sincronizacion.desactualizado.value).toBe(false)

    // Se interrumpe el stream SSE
    callbacks!.alCambiarConexion?.(false)

    // El estado NO se vacía
    expect(sincronizacion.estado.value).toEqual(estadoPrevio)
    expect(sincronizacion.estadoGlobal.value).toBe('SESION_ABIERTA')
    expect(sincronizacion.revision.value).toBe(45)

    // Se refleja la condición de reconexión y desactualización
    expect(sincronizacion.estadoConexion.value).toBe<EstadoConexion>('RECONECTANDO')
    expect(sincronizacion.desactualizado.value).toBe(true)
    expect(sincronizacion.conectado.value).toBe(false)
  })

  it('recupera una nueva baseline tras reinicio del backend incluso con revisión menor', () => {
    let callbacks: OpcionesSuscripcion<EstadoModeracion> | null = null
    const mockCliente = {
      suscribirEstado: vi.fn((ops) => {
        callbacks = ops
        return { cancelar: vi.fn(), activa: true }
      }),
    } as unknown as ClienteModeracion

    const sincronizacion = crearSincronizacionModeracion({
      cliente: mockCliente,
      autoIniciar: true,
    })

    // 1. Estado previo antes de la caída del backend
    const estadoAntesDeCaer = crearEstadoModeracionPrueba({
      revision: 142,
      estado_global: 'SESION_ABIERTA',
    })
    callbacks!.alEstado(estadoAntesDeCaer)
    callbacks!.alCambiarConexion?.(true)

    expect(sincronizacion.revision.value).toBe(142)

    // 2. Pérdida de conexión
    callbacks!.alCambiarConexion?.(false)
    expect(sincronizacion.desactualizado.value).toBe(true)

    // 3. El backend reinicia en SIN_PREPARAR con revisión 0 y el recovery snapshot lo adopta
    const snapshotRecoveryPostRestart = crearEstadoModeracionPrueba({
      revision: 0,
      estado_global: 'SIN_PREPARAR',
    })
    callbacks!.alEstado(snapshotRecoveryPostRestart)

    expect(sincronizacion.estado.value).toEqual(snapshotRecoveryPostRestart)
    expect(sincronizacion.revision.value).toBe(0)
    expect(sincronizacion.estadoGlobal.value).toBe('SIN_PREPARAR')

    // 4. Stream SSE vuelve a conectar
    callbacks!.alCambiarConexion?.(true)
    expect(sincronizacion.estadoConexion.value).toBe<EstadoConexion>('CONECTADO')
    expect(sincronizacion.conectado.value).toBe(true)
    expect(sincronizacion.desactualizado.value).toBe(false)
  })

  it('captura errores técnicos sin borrar el estado confirmado', () => {
    let callbacks: OpcionesSuscripcion<EstadoModeracion> | null = null
    const mockCliente = {
      suscribirEstado: vi.fn((ops) => {
        callbacks = ops
        return { cancelar: vi.fn(), activa: true }
      }),
    } as unknown as ClienteModeracion

    const sincronizacion = crearSincronizacionModeracion({
      cliente: mockCliente,
      autoIniciar: true,
    })

    const estadoConfirmado = crearEstadoModeracionPrueba({
      revision: 20,
      estado_global: 'PREPARANDO',
    })
    callbacks!.alEstado(estadoConfirmado)
    callbacks!.alCambiarConexion?.(true)

    // Emitimos un error de red
    const errorRed = new Error('Fallo de conexión HTTP')
    callbacks!.alError?.(errorRed)

    expect(sincronizacion.ultimoError.value).toBe(errorRed)
    expect(sincronizacion.estado.value).toEqual(estadoConfirmado)
    expect(sincronizacion.estadoConexion.value).toBe<EstadoConexion>('RECONECTANDO')
    expect(sincronizacion.desactualizado.value).toBe(true)
  })

  it('pasa a DESCONECTADO si ocurre un error antes del primer snapshot', () => {
    let callbacks: OpcionesSuscripcion<EstadoModeracion> | null = null
    const mockCliente = {
      suscribirEstado: vi.fn((ops) => {
        callbacks = ops
        return { cancelar: vi.fn(), activa: true }
      }),
    } as unknown as ClienteModeracion

    const sincronizacion = crearSincronizacionModeracion({
      cliente: mockCliente,
      autoIniciar: true,
    })

    const errorInicial = new Error('Backend no disponible')
    callbacks!.alError?.(errorInicial)

    expect(sincronizacion.estado.value).toBeNull()
    expect(sincronizacion.estadoConexion.value).toBe<EstadoConexion>('DESCONECTADO')
    expect(sincronizacion.conectado.value).toBe(false)
    expect(sincronizacion.desactualizado.value).toBe(false)
  })

  it('cancela la suscripción al llamar a cancelar(), pasa estadoConexion a DESCONECTADO y conectado a false', () => {
    let callbacks: OpcionesSuscripcion<EstadoModeracion> | null = null
    const fnCancelar = vi.fn()
    let mockActiva = true
    const mockSuscripcion: Suscripcion = {
      cancelar: () => {
        mockActiva = false
        fnCancelar()
      },
      get activa() {
        return mockActiva
      },
    }

    const mockCliente = {
      suscribirEstado: vi.fn((ops) => {
        callbacks = ops
        return mockSuscripcion
      }),
    } as unknown as ClienteModeracion

    const sincronizacion = crearSincronizacionModeracion({
      cliente: mockCliente,
      autoIniciar: true,
    })

    // Establecemos estado y conexión previa
    const estadoPrevio = crearEstadoModeracionPrueba({ revision: 5, estado_global: 'PREPARANDO' })
    callbacks!.alEstado(estadoPrevio)
    callbacks!.alCambiarConexion?.(true)

    expect(sincronizacion.estadoConexion.value).toBe<EstadoConexion>('CONECTADO')
    expect(sincronizacion.conectado.value).toBe(true)

    // Cancelamos explícitamente
    sincronizacion.cancelar()

    expect(fnCancelar).toHaveBeenCalledTimes(1)
    // M-1: estadoConexion no debe quedar en CONECTADO
    expect(sincronizacion.estadoConexion.value).toBe<EstadoConexion>('DESCONECTADO')
    expect(sincronizacion.conectado.value).toBe(false)
    // El último estado se conserva
    expect(sincronizacion.estado.value).toEqual(estadoPrevio)
  })

  it('no crea suscripciones duplicadas ante llamadas consecutivas a iniciar()', () => {
    const mockSuscripcion: Suscripcion = {
      cancelar: vi.fn(),
      activa: true,
    }

    const mockCliente = {
      suscribirEstado: vi.fn(() => mockSuscripcion),
    } as unknown as ClienteModeracion

    const sincronizacion = crearSincronizacionModeracion({
      cliente: mockCliente,
    })

    sincronizacion.iniciar()
    sincronizacion.iniciar()
    sincronizacion.iniciar()

    expect(mockCliente.suscribirEstado).toHaveBeenCalledTimes(1)
  })
})
