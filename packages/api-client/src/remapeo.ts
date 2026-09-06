/**
 * Comandos REST de la coordinación de remapeo físico, como superficie propia (WP-074).
 *
 * ## Por qué existe este archivo
 *
 * El remapeo siempre vivió en `ClienteModeracion`, pero sus tres endpoints nunca
 * pertenecieron a Moderación: cuelgan de `/api/v1/remapeos`, no de una ruta de
 * Moderación, y desde WP-056 los usan **dos** puestos, el de Moderación y el de Apoyo
 * Técnico.
 *
 * Mientras el puesto técnico también miraba el estado de Moderación, tomar prestado su
 * cliente era razonable. WP-074 corta esa dependencia: Apoyo Técnico ya no observa la
 * proyección de Moderación, así que instanciar un `ClienteModeracion` sólo para enviar tres
 * comandos dejaría en el código una pista falsa —parecería que el puesto técnico sigue
 * atado a esa superficie— y ofrecería a esa pantalla métodos que no le corresponden, como
 * abrir una sesión o una votación.
 *
 * Acá viven entonces esos tres comandos, y `ClienteModeracion` los delega en esta clase
 * para que la implementación siga siendo una sola. Ningún endpoint cambió.
 *
 * ## Qué NO hace
 *
 * No abre ninguna conexión persistente: no tiene `suscribirEstado` ni `EventSource`.
 * Construirlo no consume ninguna de las conexiones que HTTP/1.1 concede por origen, que es
 * justamente el recurso escaso que WP-074 vino a liberar.
 */

import { ClienteRest, crearClienteRest } from './rest'
import type { ConfiguracionCliente, EstadoRemapeoRespuesta, SolicitudIniciarRemapeo } from './tipos'

/** Modo de aplicación del remapeo elegido por el operador antes de confirmar. */
export type PersistenciaRemapeo = 'TEMPORAL' | 'PERSISTENTE'

/**
 * Contrato mínimo de comandos que necesita la interfaz compartida de remapeo.
 *
 * Es la frontera que consume `GestionRemapeo.vue`. Al declararla como interfaz —y no como
 * la clase concreta— el componente acepta tanto `ClienteRemapeoDispositivos` como
 * `ClienteModeracion`, sin que ninguna de las dos pantallas tenga que cambiar de cliente ni
 * duplicar la implementación.
 */
export interface ClienteRemapeo {
  /** Inicia la captura de un nuevo fingerprint para un devXX del padrón activo. */
  iniciarRemapeo(dispositivo: string, signal?: AbortSignal): Promise<EstadoRemapeoRespuesta>
  /** Autoriza el candidato congelado con la persistencia elegida. */
  confirmarRemapeo(
    remapeoId: string,
    persistencia: PersistenciaRemapeo,
    signal?: AbortSignal,
  ): Promise<void>
  /** Cancela captura o candidato sin cambiar el mapping físico. */
  cancelarRemapeo(remapeoId: string, signal?: AbortSignal): Promise<void>
}

/**
 * Implementación única de los tres comandos de remapeo sobre la API REST.
 *
 * El navegador nunca conoce la URL local del device-bridge: habla siempre con FastAPI, que
 * es quien coordina la captura y aplica el cambio físico.
 */
export class ClienteRemapeoDispositivos implements ClienteRemapeo {
  private readonly rest: ClienteRest

  constructor(configuracion: ConfiguracionCliente = {}) {
    this.rest = crearClienteRest(configuracion)
  }

  /**
   * Inicia captura para un devXX del padrón activo.
   *
   * Endpoint: POST /api/v1/remapeos
   */
  async iniciarRemapeo(dispositivo: string, signal?: AbortSignal): Promise<EstadoRemapeoRespuesta> {
    const cuerpo: SolicitudIniciarRemapeo = { dispositivo }
    return this.rest.post<EstadoRemapeoRespuesta>('/api/v1/remapeos', cuerpo, signal)
  }

  /**
   * Autoriza el candidato congelado con la persistencia elegida.
   *
   * Endpoint: POST /api/v1/remapeos/{remapeo_id}/confirmacion
   *
   * El 204 no describe el resultado físico: la operación proyectada es la que dice si el
   * remapeo quedó aplicado, y llega por el stream de estado.
   */
  async confirmarRemapeo(
    remapeoId: string,
    persistencia: PersistenciaRemapeo,
    signal?: AbortSignal,
  ): Promise<void> {
    return this.rest.postVacio(
      `/api/v1/remapeos/${encodeURIComponent(remapeoId)}/confirmacion`,
      { persistencia },
      signal,
    )
  }

  /**
   * Cancela captura/candidato sin cambiar el mapping físico.
   *
   * Endpoint: DELETE /api/v1/remapeos/{remapeo_id}
   */
  async cancelarRemapeo(remapeoId: string, signal?: AbortSignal): Promise<void> {
    return this.rest.deleteVacio(`/api/v1/remapeos/${encodeURIComponent(remapeoId)}`, signal)
  }
}

/** Fábrica para instanciar el cliente de comandos de remapeo. */
export function crearClienteRemapeo(
  configuracion: ConfiguracionCliente = {},
): ClienteRemapeoDispositivos {
  return new ClienteRemapeoDispositivos(configuracion)
}
