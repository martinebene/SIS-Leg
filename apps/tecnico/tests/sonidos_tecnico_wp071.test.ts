/**
 * Sonidos del recinto reproducidos por el puesto de Apoyo Técnico (WP-071).
 *
 * ## Qué demuestra esta suite
 *
 * El objetivo del WP es operativo: poder tomar el audio del salón desde el equipo técnico.
 * Para eso Apoyo Técnico tiene que sonar **exactamente igual** que la Pantalla del Recinto,
 * y tiene que callarse exactamente en los mismos casos.
 *
 * Las pruebas se apoyan en el mismo cableado que arma `app.vue`: la sincronización real
 * (`crearSincronizacionTecnica`, con un cliente falso que no toca la red) conectada al
 * composable compartido `useSonidosRecinto`. Lo único sustituido es el reproductor, porque
 * lo que acá se verifica es la decisión de sonar, no el audio. La reproducción real en un
 * navegador la demuestra el E2E integrado `sonidos_tecnico_wp071.spec.ts`.
 *
 * Desde WP-074 el insumo sonoro ya no es un `EstadoRecinto` recibido por un stream propio,
 * sino la subproyección `EstadoTecnico.sonorizacion` que llega por el **único** stream del
 * puesto. Los escenarios siguen escritos sobre estados del Recinto —ahí está definida la
 * semántica— y se traducen con el mismo recorte que aplica el backend, de modo que la
 * paridad se sigue comprobando contra la misma tabla canónica.
 *
 * Los quince escenarios no se escriben acá: vienen de la tabla canónica compartida que
 * también ejercita la suite del Recinto. Ésa es la forma concreta de comprobar paridad 1:1
 * en lugar de mantener dos listas parecidas.
 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { computed, effectScope, ref, type Ref } from 'vue'
import {
  EVENTOS_SONOROS_RECINTO,
  useSonidosRecinto,
  type MotorSonidosRecinto,
} from '@botonera2/frontend-shared'
import type {
  ClienteApoyoTecnico,
  EstadoRecinto,
  EstadoTecnico,
  Suscripcion,
} from '@botonera2/api-client'
import {
  crearSincronizacionTecnica,
  type SincronizacionTecnica,
} from '../app/composables/useEstadoTecnico'
import { resolverRutaAsset } from '../app/utils/rutas'
import {
  crearEscenariosSonoros,
  eventosCubiertos,
} from '../../../packages/frontend-shared/tests/helpers/escenarios_sonoros'
import {
  crearEstadoRecintoPrueba,
  crearSonidosRecintoPrueba,
  proyectarSonorizacionTecnica,
} from '../../../packages/frontend-shared/tests/helpers/estado_recinto'
import { crearEstadoTecnicoPrueba } from './datos_prueba'

/** Motor de prueba: anota qué le pidieron reproducir y qué configuración adoptó. */
function crearMotorEspia() {
  const reproducidos: string[] = []
  const motor: MotorSonidosRecinto = {
    configurar: () => {},
    reproducir: (evento) => {
      reproducidos.push(evento)
    },
    liberar: () => {},
  }
  return { motor, reproducidos }
}

/**
 * Cliente falso que expone su callback de estado y de conexión.
 *
 * Reproduce la superficie mínima que consume `crearSincronizacionTecnica`: una suscripción
 * cancelable y los tres callbacks del contrato. Ninguna prueba abre un `EventSource` ni
 * emite una petición HTTP.
 */
function crearClienteSuscribible<T>() {
  let alEstado: ((estado: T) => void) | undefined
  let alCambiarConexion: ((conectado: boolean) => void) | undefined
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
      alCambiarConexion = opciones.alCambiarConexion as unknown as (conectado: boolean) => void
      return suscripcion
    }),
  }
  return {
    cliente,
    emitir: (estado: T) => alEstado?.(estado),
    cambiarConexion: (conectado: boolean) => alCambiarConexion?.(conectado),
    cancelado: () => !activa,
  }
}

/** Banco de pruebas con el cableado completo del puesto técnico. */
interface BancoTecnico {
  sincronizacion: SincronizacionTecnica
  /**
   * Publica un estado técnico cuya porción sonora describe ese `EstadoRecinto`.
   *
   * Es la traducción que hace el backend desde WP-074: el escenario sigue expresándose en
   * términos del salón y llega al puesto dentro de su propio snapshot.
   */
  emitirRecinto: (estado: EstadoRecinto) => void
  /** Abre o corta el único stream del puesto. */
  conexion: (conectado: boolean) => void
  /** Número visible de la cuenta regresiva, el mismo que muestra el panel de Transmisión. */
  segundos: Ref<number | null>
  reproducidos: string[]
  tecnico: ReturnType<typeof crearClienteSuscribible<EstadoTecnico>>
  detener: () => void
}

const bancos: BancoTecnico[] = []

afterEach(() => {
  while (bancos.length > 0) bancos.pop()?.detener()
})

/**
 * Monta el cableado de `app.vue` sin Nuxt ni DOM.
 *
 * Es deliberadamente el mismo orden de dependencias que la SPA: la sincronización expone el
 * estado técnico y su conexión, de ahí sale `sonorizacion`, y ese ref —más el número de la
 * cuenta regresiva que ya calcula el panel de Transmisión— es lo único que recibe el
 * composable.
 */
function montarTecnico(): BancoTecnico {
  const tecnico = crearClienteSuscribible<EstadoTecnico>()
  const espia = crearMotorEspia()
  const segundos = ref<number | null>(null)
  const scope = effectScope()

  const sincronizacion = crearSincronizacionTecnica({
    cliente: tecnico.cliente as unknown as ClienteApoyoTecnico,
  })
  sincronizacion.iniciar()

  scope.run(() => {
    useSonidosRecinto({
      estado: computed(() => sincronizacion.estado.value?.sonorizacion ?? null),
      estadoConexion: sincronizacion.estadoConexion,
      segundosCuentaRegresiva: segundos,
      resolverUrl: resolverRutaAsset,
      motor: espia.motor,
    })
  })

  const banco: BancoTecnico = {
    sincronizacion,
    emitirRecinto: (estado) =>
      tecnico.emitir(
        crearEstadoTecnicoPrueba({
          revision: estado.revision,
          estado_global: estado.estado_global,
          sonorizacion: proyectarSonorizacionTecnica(estado),
        }),
      ),
    conexion: tecnico.cambiarConexion,
    segundos,
    reproducidos: espia.reproducidos,
    tecnico,
    detener: () => {
      scope.stop()
      sincronizacion.cancelar()
    },
  }
  bancos.push(banco)
  return banco
}

/**
 * Deja el puesto técnico con su stream abierto y una baseline ya adoptada.
 *
 * Después de esto, cualquier estado nuevo cuenta como hecho posterior y debe sonar.
 */
function conBaseline(banco: BancoTecnico, baseline: EstadoRecinto): void {
  banco.conexion(true)
  banco.emitirRecinto(baseline)
  banco.reproducidos.length = 0
}

// =============================================================================
// 1. Paridad 1:1 con la Pantalla del Recinto
// =============================================================================

describe('Paridad sonora con la Pantalla del Recinto', () => {
  const escenarios = crearEscenariosSonoros()

  it('la tabla canónica cubre exactamente los quince eventos del contrato', () => {
    // Si el contrato sumara un evento y nadie escribiera su escenario, esta comparación
    // fallaría antes que cualquier prueba de comportamiento.
    expect([...eventosCubiertos(escenarios)].sort()).toEqual([...EVENTOS_SONOROS_RECINTO].sort())
  })

  for (const escenario of escenarios) {
    it(`reproduce ${escenario.evento} cuando ${escenario.descripcion}`, () => {
      const banco = montarTecnico()
      conBaseline(banco, escenario.previo)

      banco.emitirRecinto(escenario.actual)
      if (escenario.segundos !== undefined) {
        banco.segundos.value = escenario.segundos.previo
        banco.segundos.value = escenario.segundos.actual
      }

      expect(banco.reproducidos).toContain(escenario.evento)
    })
  }

  it('no reproduce ningún evento ajeno al hecho ocurrido', () => {
    // Un escenario representativo alcanza para demostrar la ausencia de ruido: si la
    // pantalla sonorizara de más, aparecerían eventos que el hecho no produjo.
    const escenario = escenarios.find((caso) => caso.evento === 'votacion_abierta')
    expect(escenario).toBeDefined()
    const banco = montarTecnico()
    conBaseline(banco, escenario!.previo)

    banco.emitirRecinto(escenario!.actual)

    expect(banco.reproducidos).toEqual(['votacion_abierta'])
  })
})

// =============================================================================
// 2. Silencio obligatorio: baseline, recarga y reconexión
// =============================================================================

describe('El puesto técnico nunca reproduce historia', () => {
  const sesionAvanzada = crearEstadoRecintoPrueba({
    revision: 42,
    estado_global: 'SESION_ABIERTA',
    sonidos: crearSonidosRecintoPrueba(),
  })

  it('no suena al adoptar el primer snapshot, aunque describa una sesión en curso', () => {
    const banco = montarTecnico()

    banco.conexion(true)
    banco.emitirRecinto(sesionAvanzada)

    expect(banco.reproducidos).toEqual([])
  })

  it('no suena cuando el estado llega sin el stream público abierto', () => {
    // Es el caso de la recuperación: el cliente pide un snapshot REST antes de reabrir el
    // stream. Ese snapshot describe todo lo ocurrido mientras el puesto estuvo aislado.
    const banco = montarTecnico()
    conBaseline(banco, crearEstadoRecintoPrueba({ revision: 1 }))

    banco.conexion(false)
    banco.emitirRecinto({ ...sesionAvanzada, revision: 43 })

    expect(banco.reproducidos).toEqual([])
  })

  it('vuelve a sonar recién con el primer hecho posterior a la reconexión', () => {
    const banco = montarTecnico()
    conBaseline(banco, crearEstadoRecintoPrueba({ revision: 1 }))

    banco.conexion(false)
    banco.emitirRecinto({ ...sesionAvanzada, revision: 43 })
    banco.conexion(true)
    banco.emitirRecinto({ ...sesionAvanzada, revision: 44, estado_global: 'SIN_PREPARAR' })

    expect(banco.reproducidos).toEqual(['sesion_cerrada'])
  })

  it('no duplica sonido si el backend reenvía la misma revisión', () => {
    const banco = montarTecnico()
    const previo = crearEstadoRecintoPrueba({ revision: 10, estado_global: 'PREPARANDO' })
    conBaseline(banco, previo)
    const abierta = crearEstadoRecintoPrueba({ revision: 11, estado_global: 'SESION_ABIERTA' })

    banco.emitirRecinto(abierta)
    banco.emitirRecinto(abierta)
    banco.emitirRecinto({ ...abierta, revision: 11 })

    expect(banco.reproducidos).toEqual(['sesion_abierta'])
  })
})

// =============================================================================
// 3. Superposición y tic local
// =============================================================================

describe('Superposición y cuenta regresiva', () => {
  it('reproduce los dos eventos de una misma revisión, sin encolarlos ni descartarlos', () => {
    const banco = montarTecnico()
    const previo = crearEstadoRecintoPrueba({
      revision: 5,
      estado_global: 'SESION_ABIERTA',
      concejales: [
        {
          nombre: 'Nombre1',
          apellido: 'Apellido1',
          bloque: 'Bloque Verde',
          banca: 1,
          ruta_imagen: 'assets/bancas/banca-01.png',
          presente: true,
          test_activo: false,
          test_expira_en: null,
        },
      ],
    })
    conBaseline(banco, previo)

    // Una sola revisión con dos hechos simultáneos: arranca la transmisión y la banca 1
    // se ausenta. Los dos sonidos deben salir, en el orden canónico de la detección.
    banco.emitirRecinto({
      ...previo,
      revision: 6,
      concejales: previo.concejales.map((concejal) => ({ ...concejal, presente: false })),
      tecnico: {
        transmision: {
          estado: 'EN_VIVO',
          iniciada_en: '2026-09-05T10:00:00Z',
          en_vivo_desde: '2026-09-05T10:00:00Z',
          cuenta_regresiva_segundos: null,
          segundos_restantes: null,
        },
        aviso: null,
      },
    })

    expect(banco.reproducidos).toEqual(['transmision_iniciada', 'concejal_ausente'])
  })

  it('acompaña cada cambio de segundo con un tic, sin pedir una revisión por segundo', () => {
    const banco = montarTecnico()
    conBaseline(banco, crearEstadoRecintoPrueba({ revision: 1 }))
    const suscripcionesAntes = banco.tecnico.cliente.suscribirEstado.mock.calls.length

    banco.segundos.value = 4
    banco.segundos.value = 3
    banco.segundos.value = 2
    banco.segundos.value = 1

    expect(banco.reproducidos).toEqual([
      'transmision_cuenta_regresiva_tic',
      'transmision_cuenta_regresiva_tic',
      'transmision_cuenta_regresiva_tic',
    ])
    // El tic no abrió ninguna suscripción nueva: el número lo baja el reloj local.
    expect(banco.tecnico.cliente.suscribirEstado.mock.calls.length).toBe(suscripcionesAntes)
  })

  it('no suena al entrar a una cuenta regresiva ya empezada ni al terminarla', () => {
    const banco = montarTecnico()
    conBaseline(banco, crearEstadoRecintoPrueba({ revision: 1 }))

    // Adoptar un snapshot en mitad de la cuenta muestra el número, pero no es un cambio de
    // segundo; y el final de la cuenta ya tiene el sonido de inicio de transmisión.
    banco.segundos.value = 3
    banco.segundos.value = null

    expect(banco.reproducidos).toEqual([])
  })
})

// =============================================================================
// 4. Una sola suscripción alimenta el sonido y la operación (WP-074)
// =============================================================================

describe('Suscripción única del puesto técnico', () => {
  it('sonoriza sin abrir ninguna suscripción además de la técnica', () => {
    const banco = montarTecnico()

    banco.sincronizacion.iniciar()
    conBaseline(banco, crearEstadoRecintoPrueba({ revision: 1, estado_global: 'PREPARANDO' }))
    banco.emitirRecinto(crearEstadoRecintoPrueba({ revision: 2, estado_global: 'SESION_ABIERTA' }))

    // Sonó el hecho institucional, y para eso alcanzó un único stream: es exactamente la
    // condición que WP-074 necesita para liberar conexiones HTTP/1.1.
    expect(banco.reproducidos).toEqual(['sesion_abierta'])
    expect(banco.tecnico.cliente.suscribirEstado).toHaveBeenCalledTimes(1)
  })

  it('cancela esa única suscripción sin borrar el último estado adoptado', () => {
    const banco = montarTecnico()
    conBaseline(banco, crearEstadoRecintoPrueba({ revision: 7 }))

    banco.sincronizacion.cancelar()

    expect(banco.tecnico.cancelado()).toBe(true)
    expect(banco.sincronizacion.estado.value?.revision).toBe(7)
    expect(banco.sincronizacion.estado.value?.sonorizacion.revision).toBe(7)
  })

  it('un corte del stream deja de sonorizar y conserva el estado en pantalla', () => {
    // Con una sola conexión, perder el stream es perder a la vez la operación y el sonido.
    // Lo que no puede pasar es que la reconexión reproduzca lo ocurrido durante el corte.
    const banco = montarTecnico()
    conBaseline(banco, crearEstadoRecintoPrueba({ revision: 1 }))

    banco.conexion(false)
    banco.emitirRecinto(crearEstadoRecintoPrueba({ revision: 9, estado_global: 'SESION_ABIERTA' }))

    expect(banco.sincronizacion.estadoConexion.value).toBe('RECONECTANDO')
    expect(banco.sincronizacion.desactualizado.value).toBe(true)
    expect(banco.reproducidos).toEqual([])
  })

  it('resuelve las rutas de sonido bajo el prefijo público de Apoyo Técnico', () => {
    // Fuera del runtime de Nuxt el resolutor cae a la raíz; lo que se comprueba acá es la
    // normalización, que es la parte propia de esta aplicación.
    expect(resolverRutaAsset('assets/sonidos/sesion-abierta.wav')).toBe(
      '/assets/sonidos/sesion-abierta.wav',
    )
    expect(resolverRutaAsset('/assets/sonidos/sesion-abierta.wav')).toBe(
      '/assets/sonidos/sesion-abierta.wav',
    )
    expect(resolverRutaAsset('')).toBe('')
  })
})
