/**
 * Envoltorio Nuxt de la frontera reactiva pública de la Pantalla del Recinto.
 *
 * Desde WP-099 la implementación vive en `@sis-leg/frontend-shared`: el Zócalo para OBS
 * consume la misma proyección autoritativa y el WP prohíbe que cada superficie mantenga su
 * propio modelo de estado. Acá queda únicamente lo que no puede compartirse, que es la
 * lectura de `useRuntimeConfig()`: es un auto-import de Nuxt y sólo existe dentro de una
 * aplicación.
 *
 * Los símbolos compartidos se reexportan con su nombre histórico para que los componentes
 * y las pruebas de esta SPA sigan importándolos desde acá.
 */

import type { ClienteRecinto } from '@sis-leg/api-client'
import {
  usarSincronizacionRecintoEnComponente,
  type SincronizacionRecinto,
} from '@sis-leg/frontend-shared'

export {
  crearSincronizacionRecinto,
  type EstadoConexionRecinto,
  type OpcionesSincronizacionRecinto,
  type SincronizacionRecinto,
} from '@sis-leg/frontend-shared'

/**
 * Integra la sincronización con el ciclo de vida del único shell público.
 *
 * @param clienteInyectado Cliente alternativo usado por las pruebas de componentes. Sin él
 *   se construye uno contra `apiBaseUrl`, que en producción es cadena vacía porque la SPA
 *   y FastAPI comparten origen.
 */
export function useEstadoRecinto(clienteInyectado?: ClienteRecinto): SincronizacionRecinto {
  let baseUrl = ''
  if (!clienteInyectado) {
    const configuracion = useRuntimeConfig()
    baseUrl = configuracion.public.apiBaseUrl
  }

  return usarSincronizacionRecintoEnComponente(baseUrl, clienteInyectado)
}
