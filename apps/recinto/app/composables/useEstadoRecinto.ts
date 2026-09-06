/**
 * Frontera reactiva de solo lectura para la Pantalla del Recinto.
 *
 * El composable no implementa transporte por su cuenta: delega snapshot REST,
 * SSE, backoff y recuperación de baseline al ClienteRecinto canónico. Su única
 * responsabilidad es traducir esos callbacks a estado visual de Vue y cerrar
 * la suscripción cuando desaparece el componente consumidor.
 */

import { computed, onMounted, onScopeDispose, ref, type ComputedRef, type Ref } from 'vue'
import {
  crearClienteRecinto,
  type ClienteRecinto,
  type ConfiguracionCliente,
  type EstadoGlobal,
  type EstadoRecinto,
  type Suscripcion,
} from '@sis-leg/api-client'

export type EstadoConexionRecinto = 'INICIAL' | 'CONECTADO' | 'RECONECTANDO' | 'DESCONECTADO'

/** Estado que la vista pública consume sin crear otra fuente institucional. */
export interface SincronizacionRecinto {
  estado: Ref<EstadoRecinto | null>
  estadoConexion: Ref<EstadoConexionRecinto>
  ultimoError: Ref<unknown | null>
  conectado: ComputedRef<boolean>
  desactualizado: ComputedRef<boolean>
  estadoGlobal: ComputedRef<EstadoGlobal | null>
  iniciar: () => void
  cancelar: () => void
}

export interface OpcionesSincronizacionRecinto {
  cliente?: ClienteRecinto
  configuracionCliente?: ConfiguracionCliente
  autoIniciar?: boolean
}

/**
 * Crea una sincronización aislada y testeable fuera del runtime de Nuxt.
 *
 * El último snapshot nunca se borra por un error de red. Cuando el api-client
 * obtiene una baseline nueva —incluso revisión 0 tras reiniciar FastAPI— se
 * reemplaza el objeto completo y la plantilla obedece ese nuevo estado.
 */
export function crearSincronizacionRecinto(
  opciones: OpcionesSincronizacionRecinto = {},
): SincronizacionRecinto {
  const cliente = opciones.cliente ?? crearClienteRecinto(opciones.configuracionCliente ?? {})
  const estado = ref<EstadoRecinto | null>(null)
  const estadoConexion = ref<EstadoConexionRecinto>('INICIAL')
  const ultimoError = ref<unknown | null>(null)
  let suscripcion: Suscripcion | null = null

  const conectado = computed(() => estadoConexion.value === 'CONECTADO')
  const desactualizado = computed(
    () => estadoConexion.value === 'RECONECTANDO' && estado.value !== null,
  )
  const estadoGlobal = computed(() => estado.value?.estado_global ?? null)

  function marcarDesconexion(): void {
    estadoConexion.value = estado.value === null ? 'DESCONECTADO' : 'RECONECTANDO'
  }

  /** Inicia una única suscripción; llamadas repetidas son idempotentes. */
  function iniciar(): void {
    if (suscripcion?.activa) return

    suscripcion = cliente.suscribirEstado({
      alEstado: (nuevoEstado) => {
        estado.value = nuevoEstado
      },
      alCambiarConexion: (estaConectado) => {
        if (estaConectado) {
          estadoConexion.value = 'CONECTADO'
          ultimoError.value = null
        } else {
          marcarDesconexion()
        }
      },
      alError: (error) => {
        ultimoError.value = error
        marcarDesconexion()
      },
    })
  }

  /** Cierra EventSource, requests y esperas pendientes sin borrar la última vista. */
  function cancelar(): void {
    suscripcion?.cancelar()
    suscripcion = null
    estadoConexion.value = 'DESCONECTADO'
  }

  if (opciones.autoIniciar) iniciar()

  return {
    estado,
    estadoConexion,
    ultimoError,
    conectado,
    desactualizado,
    estadoGlobal,
    iniciar,
    cancelar,
  }
}

/**
 * Integra la sincronización con el ciclo de vida del único shell público.
 * `onScopeDispose` también cubre un desmontaje de prueba sin dejar conexiones.
 */
export function useEstadoRecinto(clienteInyectado?: ClienteRecinto): SincronizacionRecinto {
  let baseUrl = ''
  if (!clienteInyectado) {
    const configuracion = useRuntimeConfig()
    baseUrl = configuracion.public.apiBaseUrl
  }

  const sincronizacion = crearSincronizacionRecinto({
    cliente: clienteInyectado,
    configuracionCliente: { baseUrl },
  })

  onMounted(sincronizacion.iniciar)
  onScopeDispose(sincronizacion.cancelar)
  return sincronizacion
}
