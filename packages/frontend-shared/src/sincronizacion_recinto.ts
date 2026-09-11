/**
 * Frontera reactiva de solo lectura sobre la proyección pública del Recinto.
 *
 * ## Qué resuelve
 *
 * El api-client ya implementa snapshot REST, SSE, backoff, reconexión y recuperación de
 * baseline. Este módulo no repite nada de eso: traduce esos callbacks a estado de Vue y
 * cierra la suscripción cuando el ámbito reactivo que la creó desaparece.
 *
 * ## Por qué es compartido desde WP-099
 *
 * Nació dentro de `apps/recinto` cuando la Pantalla del Recinto era la única superficie
 * pública. El Zócalo para OBS consume **la misma** proyección autoritativa —el mismo
 * endpoint, el mismo stream, el mismo DTO— y el WP prohíbe expresamente que mantenga un
 * modelo de estado propio. Compartir la frontera es la forma literal de cumplirlo: las dos
 * pantallas no sólo leen los mismos datos, ejecutan el mismo código para leerlos.
 *
 * Lo único que no vive acá es el acceso a `useRuntimeConfig()`, porque es un auto-import de
 * Nuxt que no existe fuera de una aplicación. Cada SPA conserva un envoltorio de tres
 * líneas que lee su `apiBaseUrl` y llama a esta fábrica.
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

/**
 * Estados posibles del vínculo con el backend.
 *
 * `INICIAL` es «todavía no llegó nada»; `RECONECTANDO` sólo puede ocurrir cuando ya hubo
 * al menos un snapshot, porque es la situación en la que la pantalla sigue mostrando datos
 * válidos aunque potencialmente atrasados.
 */
export type EstadoConexionRecinto = 'INICIAL' | 'CONECTADO' | 'RECONECTANDO' | 'DESCONECTADO'

/** Estado que una vista pública consume sin crear otra fuente institucional. */
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
 * Ata una sincronización al ciclo de vida del componente que la pide.
 *
 * Se separa de `crearSincronizacionRecinto` porque los hooks de Vue sólo pueden llamarse
 * dentro de un `setup()`: la fábrica de arriba se ejerce en pruebas puras, y este
 * envoltorio agrega el arranque en `onMounted` y el cierre en `onScopeDispose`, que
 * también cubre un desmontaje de prueba sin dejar conexiones abiertas.
 *
 * @param baseUrl Base del backend. Cadena vacía significa mismo origen, que es el caso
 *   productivo detrás de Nginx.
 * @param clienteInyectado Cliente alternativo para pruebas; cuando se pasa, `baseUrl` se
 *   ignora porque el cliente ya trae su propia configuración.
 */
export function usarSincronizacionRecintoEnComponente(
  baseUrl: string,
  clienteInyectado?: ClienteRecinto,
): SincronizacionRecinto {
  const sincronizacion = crearSincronizacionRecinto({
    cliente: clienteInyectado,
    configuracionCliente: { baseUrl },
  })

  onMounted(sincronizacion.iniciar)
  onScopeDispose(sincronizacion.cancelar)
  return sincronizacion
}
