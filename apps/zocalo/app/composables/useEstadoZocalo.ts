/**
 * Envoltorio Nuxt de la frontera reactiva del Zócalo para OBS (WP-099).
 *
 * El Zócalo **no** tiene una fuente propia: consume la misma proyección pública que la
 * Pantalla del Recinto —`/api/v1/estado/recinto` y su stream SSE— mediante exactamente el
 * mismo código compartido. Por eso este archivo no implementa transporte, reconexión ni
 * modelo de estado: sólo lee la base del backend configurada para esta SPA y delega.
 *
 * Que sean dos superficies distintas no crea dos verdades: si el backend publica una
 * revisión nueva, las dos la adoptan por el mismo camino y muestran lo mismo.
 */

import type { ClienteRecinto } from '@sis-leg/api-client'
import {
  usarSincronizacionRecintoEnComponente,
  type SincronizacionRecinto,
} from '@sis-leg/frontend-shared'

/**
 * Abre la única suscripción autoritativa del Zócalo y la ata al ciclo de vida del shell.
 *
 * @param clienteInyectado Cliente alternativo usado por las pruebas de componentes. Sin él
 *   se construye uno contra `apiBaseUrl`, que en producción es cadena vacía porque la SPA
 *   y FastAPI comparten origen detrás de Nginx.
 * @returns La misma estructura reactiva que usa la Pantalla del Recinto.
 */
export function useEstadoZocalo(clienteInyectado?: ClienteRecinto): SincronizacionRecinto {
  let baseUrl = ''
  if (!clienteInyectado) {
    const configuracion = useRuntimeConfig()
    baseUrl = configuracion.public.apiBaseUrl
  }

  return usarSincronizacionRecintoEnComponente(baseUrl, clienteInyectado)
}
