/**
 * Cliente TypeScript del puesto de Apoyo Técnico de SIS-Leg (WP-055).
 *
 * Expone la superficie completa del plano técnico: lectura/sincronización del
 * EstadoTecnico, comandos de transmisión, avisos por destino y CRUD de la
 * biblioteca de mensajes precargados.
 *
 * Es una superficie separada de ClienteModeracion a propósito. El puesto
 * técnico no abre sesiones, no vota, no otorga la palabra y no carga el Orden
 * del Día: que esos métodos ni siquiera existan acá lo garantiza desde el
 * sistema de tipos, igual que ClienteRecinto garantiza la solo-lectura del
 * frontend público.
 *
 * WP-055 entrega únicamente backend y contrato: la SPA técnica que consumirá
 * este cliente todavía no existe.
 */

import { ClienteRest, crearClienteRest } from './rest'
import { iniciarSincronizacionEstado } from './sincronizador'
import type {
  BibliotecaMensajesProyectada,
  ConfiguracionCliente,
  DestinoAvisoTecnico,
  EstadoTecnico,
  MensajeTecnicoProyectado,
  OpcionesSuscripcion,
  SolicitudIniciarTransmision,
  SolicitudMensajeTecnico,
  SolicitudPublicarAviso,
  Suscripcion,
} from './tipos'

/**
 * Cliente para el puesto de Apoyo Técnico.
 */
export class ClienteApoyoTecnico {
  private readonly rest: ClienteRest
  private readonly configuracion: ConfiguracionCliente

  constructor(configuracion: ConfiguracionCliente = {}) {
    this.configuracion = configuracion
    this.rest = crearClienteRest(configuracion)
  }

  // ===========================================================================
  // 1. Lectura y sincronización reactiva
  // ===========================================================================

  /**
   * Obtiene un snapshot REST completo del estado técnico.
   *
   * Endpoint: GET /api/v1/estado/tecnico
   */
  async obtenerEstado(signal?: AbortSignal): Promise<EstadoTecnico> {
    return this.rest.get<EstadoTecnico>('/api/v1/estado/tecnico', signal)
  }

  /**
   * Inicia el ciclo reactivo de sincronización (Snapshot -> SSE -> Reconexión).
   *
   * Endpoint SSE: GET /api/v1/estado/tecnico/stream
   *
   * El backend republica al cruzar cada frontera temporal (fin de la cuenta
   * regresiva, vencimiento de un aviso), así que no hace falta ningún sondeo
   * periódico para ver el estado correcto.
   *
   * @param opciones Callbacks alEstado, alError y alCambiarConexion.
   * @returns Instancia de Suscripcion cancelable.
   */
  suscribirEstado(opciones: OpcionesSuscripcion<EstadoTecnico>): Suscripcion {
    const urlStream = this.rest.construirUrl('/api/v1/estado/tecnico/stream')
    return iniciarSincronizacionEstado<EstadoTecnico>({
      obtenerSnapshot: (signal) => this.obtenerEstado(signal),
      urlStream,
      opciones,
      configuracion: this.configuracion,
    })
  }

  // ===========================================================================
  // 2. Comandos de transmisión
  // ===========================================================================

  /**
   * Inicia la transmisión de inmediato o con una cuenta regresiva de N segundos.
   *
   * Endpoint: POST /api/v1/apoyo-tecnico/transmision
   *
   * @param cuentaRegresivaSegundos Segundos de cuenta regresiva, o null/omitido
   *   para pasar a EN_VIVO inmediatamente.
   */
  async iniciarTransmision(
    cuentaRegresivaSegundos?: number | null,
    signal?: AbortSignal,
  ): Promise<void> {
    const cuerpo: SolicitudIniciarTransmision = {
      cuenta_regresiva_segundos: cuentaRegresivaSegundos ?? null,
    }
    return this.rest.postVacio('/api/v1/apoyo-tecnico/transmision', cuerpo, signal)
  }

  /**
   * Detiene la transmisión y devuelve el indicador a APAGADO.
   *
   * Endpoint: DELETE /api/v1/apoyo-tecnico/transmision
   *
   * No existe apagado automático: EN_VIVO solo termina con esta orden.
   */
  async detenerTransmision(signal?: AbortSignal): Promise<void> {
    return this.rest.deleteVacio('/api/v1/apoyo-tecnico/transmision', signal)
  }

  // ===========================================================================
  // 3. Comandos de avisos técnicos
  // ===========================================================================

  /**
   * Publica un aviso hacia Moderación, Recinto o ambos.
   *
   * Endpoint: POST /api/v1/apoyo-tecnico/avisos
   *
   * @param texto Contenido del aviso, de una sola línea.
   * @param destino MODERACION, RECINTO o AMBOS.
   * @param duracionSegundos Vigencia en segundos, o null/omitido para que el
   *   aviso permanezca hasta cancelarlo manualmente.
   */
  async publicarAviso(
    texto: string,
    destino: DestinoAvisoTecnico,
    duracionSegundos?: number | null,
    signal?: AbortSignal,
  ): Promise<void> {
    const cuerpo: SolicitudPublicarAviso = {
      texto,
      destino,
      duracion_segundos: duracionSegundos ?? null,
    }
    return this.rest.postVacio('/api/v1/apoyo-tecnico/avisos', cuerpo, signal)
  }

  /**
   * Cancela el aviso vigente de un destino antes de su vencimiento.
   *
   * Endpoint: DELETE /api/v1/apoyo-tecnico/avisos/{destino}
   *
   * Es idempotente: cancelar un destino sin aviso vigente no falla.
   */
  async cancelarAviso(destino: DestinoAvisoTecnico, signal?: AbortSignal): Promise<void> {
    return this.rest.deleteVacio(
      `/api/v1/apoyo-tecnico/avisos/${encodeURIComponent(destino)}`,
      signal,
    )
  }

  // ===========================================================================
  // 4. Biblioteca de mensajes precargados
  // ===========================================================================

  /**
   * Lista la biblioteca de mensajes precargados persistida en CSV.
   *
   * Endpoint: GET /api/v1/apoyo-tecnico/mensajes
   *
   * Devuelve el mismo submodelo que viaja dentro de EstadoTecnico.biblioteca.
   */
  async listarMensajes(signal?: AbortSignal): Promise<BibliotecaMensajesProyectada> {
    return this.rest.get<BibliotecaMensajesProyectada>('/api/v1/apoyo-tecnico/mensajes', signal)
  }

  /**
   * Crea un mensaje precargado y lo persiste en el CSV.
   *
   * Endpoint: POST /api/v1/apoyo-tecnico/mensajes
   *
   * El identificador lo genera el backend y no cambia nunca después.
   */
  async crearMensaje(
    texto: string,
    destino: DestinoAvisoTecnico,
    signal?: AbortSignal,
  ): Promise<MensajeTecnicoProyectado> {
    const cuerpo: SolicitudMensajeTecnico = { texto, destino }
    return this.rest.post<MensajeTecnicoProyectado>(
      '/api/v1/apoyo-tecnico/mensajes',
      cuerpo,
      signal,
    )
  }

  /**
   * Edita el texto y el destino de un mensaje precargado existente.
   *
   * Endpoint: PUT /api/v1/apoyo-tecnico/mensajes/{mensaje_id}
   *
   * Responde 404 MENSAJE_TECNICO_NO_EXISTENTE si el id ya no está en la
   * biblioteca, en lugar de crear un mensaje nuevo.
   */
  async actualizarMensaje(
    mensajeId: string,
    texto: string,
    destino: DestinoAvisoTecnico,
    signal?: AbortSignal,
  ): Promise<MensajeTecnicoProyectado> {
    const cuerpo: SolicitudMensajeTecnico = { texto, destino }
    return this.rest.put<MensajeTecnicoProyectado>(
      `/api/v1/apoyo-tecnico/mensajes/${encodeURIComponent(mensajeId)}`,
      cuerpo,
      signal,
    )
  }

  /**
   * Elimina un mensaje precargado de la biblioteca.
   *
   * Endpoint: DELETE /api/v1/apoyo-tecnico/mensajes/{mensaje_id}
   */
  async eliminarMensaje(mensajeId: string, signal?: AbortSignal): Promise<void> {
    return this.rest.deleteVacio(
      `/api/v1/apoyo-tecnico/mensajes/${encodeURIComponent(mensajeId)}`,
      signal,
    )
  }
}

/**
 * Fábrica para instanciar ClienteApoyoTecnico.
 */
export function crearClienteApoyoTecnico(
  configuracion: ConfiguracionCliente = {},
): ClienteApoyoTecnico {
  return new ClienteApoyoTecnico(configuracion)
}
