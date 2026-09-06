/**
 * Cliente TypeScript para la Pantalla del Recinto de SIS-Leg.
 *
 * Superficie estrictamente de solo lectura: consume directamente las rutas
 * de proyección pública /api/v1/estado/recinto y /api/v1/estado/recinto/stream.
 *
 * NO contiene métodos mutantes de preparación, sesión, votación, palabra u Orden del Día,
 * asegurando desde el sistema de tipos de TypeScript que el frontend público no pueda
 * emitir comandos del operador.
 *
 * Tampoco filtra campos del EstadoModeracion en el cliente: consume directamente
 * el EstadoRecinto provisto por el backend donde el secreto temporal ya está garantizado.
 */

import { ClienteRest, crearClienteRest } from './rest'
import { iniciarSincronizacionEstado } from './sincronizador'
import type { ConfiguracionCliente, EstadoRecinto, OpcionesSuscripcion, Suscripcion } from './tipos'

/**
 * Cliente para la Pantalla del Recinto.
 */
export class ClienteRecinto {
  private readonly rest: ClienteRest
  private readonly configuracion: ConfiguracionCliente

  constructor(configuracion: ConfiguracionCliente = {}) {
    this.configuracion = configuracion
    this.rest = crearClienteRest(configuracion)
  }

  // ===========================================================================
  // Lectura y sincronización reactiva de solo lectura
  // ===========================================================================

  /**
   * Obtiene un snapshot REST completo del estado público del Recinto.
   *
   * Endpoint: GET /api/v1/estado/recinto
   */
  async obtenerEstado(signal?: AbortSignal): Promise<EstadoRecinto> {
    return this.rest.get<EstadoRecinto>('/api/v1/estado/recinto', signal)
  }

  /**
   * Inicia el ciclo reactivo de sincronización pública (Snapshot -> SSE -> Reconexión).
   *
   * Endpoint SSE: GET /api/v1/estado/recinto/stream
   *
   * @param opciones Callbacks alEstado, alError y alCambiarConexion.
   * @returns Instancia de Suscripcion cancelable.
   */
  suscribirEstado(opciones: OpcionesSuscripcion<EstadoRecinto>): Suscripcion {
    const urlStream = this.rest.construirUrl('/api/v1/estado/recinto/stream')
    return iniciarSincronizacionEstado<EstadoRecinto>({
      obtenerSnapshot: (signal) => this.obtenerEstado(signal),
      urlStream,
      opciones,
      configuracion: this.configuracion,
    })
  }
}

/**
 * Fábrica para instanciar ClienteRecinto.
 */
export function crearClienteRecinto(configuracion: ConfiguracionCliente = {}): ClienteRecinto {
  return new ClienteRecinto(configuracion)
}
