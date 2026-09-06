/**
 * Cliente TypeScript para la interfaz de Moderación de SISLeg.
 *
 * Expone la superficie completa de lectura/sincronización y comandos mutantes
 * permitidos para el operador único de Moderación, encapsulando las rutas REST y SSE.
 *
 * NO expone la ruta física POST /api/v1/entradas/tecla, que pertenece exclusivamente
 * al device-bridge.
 */

import { ClienteRest, crearClienteRest } from './rest'
import {
  ClienteRemapeoDispositivos,
  type ClienteRemapeo,
  type PersistenciaRemapeo,
} from './remapeo'
import { iniciarSincronizacionEstado } from './sincronizador'
import type {
  ConfiguracionCliente,
  EstadoModeracion,
  OpcionesSuscripcion,
  RespuestaOrdenDelDia,
  EstadoRemapeoRespuesta,
  RespuestaVotacion,
  SolicitudActualizarPreparacion,
  SolicitudActualizarSesion,
  SolicitudAperturaVotacion,
  SolicitudDesempate,
  SolicitudFinalizarVotacion,
  Suscripcion,
} from './tipos'

/**
 * Cliente para la aplicación de Moderación.
 */
export class ClienteModeracion implements ClienteRemapeo {
  private readonly rest: ClienteRest
  private readonly configuracion: ConfiguracionCliente
  /** Implementación compartida de los comandos de remapeo (WP-074). */
  private readonly remapeo: ClienteRemapeoDispositivos

  constructor(configuracion: ConfiguracionCliente = {}) {
    this.configuracion = configuracion
    this.rest = crearClienteRest(configuracion)
    this.remapeo = new ClienteRemapeoDispositivos(configuracion)
  }

  // ===========================================================================
  // 1. Lectura y sincronización reactiva
  // ===========================================================================

  /**
   * Obtiene un snapshot REST completo del estado de Moderación.
   *
   * Endpoint: GET /api/v1/estado/moderacion
   */
  async obtenerEstado(signal?: AbortSignal): Promise<EstadoModeracion> {
    return this.rest.get<EstadoModeracion>('/api/v1/estado/moderacion', signal)
  }

  /**
   * Inicia el ciclo reactivo de sincronización (Snapshot -> SSE -> Reconexión).
   *
   * Endpoint SSE: GET /api/v1/estado/moderacion/stream
   *
   * @param opciones Callbacks alEstado, alError y alCambiarConexion.
   * @returns Instancia de Suscripcion cancelable.
   */
  suscribirEstado(opciones: OpcionesSuscripcion<EstadoModeracion>): Suscripcion {
    const urlStream = this.rest.construirUrl('/api/v1/estado/moderacion/stream')
    return iniciarSincronizacionEstado<EstadoModeracion>({
      obtenerSnapshot: (signal) => this.obtenerEstado(signal),
      urlStream,
      opciones,
      configuracion: this.configuracion,
    })
  }

  // ===========================================================================
  // 2. Comandos de Preparación del Recinto
  // ===========================================================================

  /**
   * Inicia una nueva preparación del recinto (CU-01).
   *
   * Endpoint: POST /api/v1/preparacion
   */
  async prepararSala(signal?: AbortSignal): Promise<void> {
    return this.rest.postVacio('/api/v1/preparacion', undefined, signal)
  }

  /**
   * Actualiza el número de sesión y/o autoridades durante PREPARANDO.
   *
   * Endpoint: PATCH /api/v1/preparacion
   */
  async actualizarPreparacion(
    datos: SolicitudActualizarPreparacion,
    signal?: AbortSignal,
  ): Promise<void> {
    return this.rest.patchVacio('/api/v1/preparacion', datos, signal)
  }

  /**
   * Cancela la preparación activa y devuelve el sistema a SIN_PREPARAR (CU-02).
   *
   * Endpoint: DELETE /api/v1/preparacion
   */
  async cancelarPreparacion(signal?: AbortSignal): Promise<void> {
    return this.rest.deleteVacio('/api/v1/preparacion', signal)
  }

  // ===========================================================================
  // 3. Comandos de Sesión Formal
  // ===========================================================================

  /**
   * Abre formalmente la sesión desde PREPARANDO con quórum y autoridades completas (CU-03).
   *
   * Endpoint: POST /api/v1/sesion
   */
  async abrirSesion(signal?: AbortSignal): Promise<void> {
    return this.rest.postVacio('/api/v1/sesion', undefined, signal)
  }

  /**
   * Actualiza Presidencia y/o Secretaría Legislativa durante SESION_ABIERTA.
   *
   * Endpoint: PATCH /api/v1/sesion
   */
  async actualizarSesion(datos: SolicitudActualizarSesion, signal?: AbortSignal): Promise<void> {
    return this.rest.patchVacio('/api/v1/sesion', datos, signal)
  }

  /**
   * Cierra formalmente la sesión y devuelve el sistema a SIN_PREPARAR (CU-04).
   * Si existe una votación EN_CURSO o EMPATADA, el backend la resuelve antes como INCONCLUSA.
   *
   * Endpoint: DELETE /api/v1/sesion
   */
  async cerrarSesion(signal?: AbortSignal): Promise<void> {
    return this.rest.deleteVacio('/api/v1/sesion', signal)
  }

  // ===========================================================================
  // 4. Comandos de Orden del Día
  // ===========================================================================

  /**
   * Carga el archivo CSV del Orden del Día para su parseo por el backend (DT-013 / DT-039).
   *
   * Endpoint: POST /api/v1/orden-del-dia (multipart/form-data con campo 'archivo')
   *
   * @param archivo Blob, File, FormData, string o Uint8Array conteniendo el CSV.
   * @param signal Señal de cancelación opcional.
   * @returns Lista de puntos normalizados devuelta por el backend.
   */
  async cargarOrdenDelDia(
    archivo: Blob | File | FormData | string | Uint8Array,
    signal?: AbortSignal,
  ): Promise<RespuestaOrdenDelDia> {
    let formData: FormData

    if (typeof FormData !== 'undefined' && archivo instanceof FormData) {
      formData = archivo
    } else {
      formData = new FormData()
      if (typeof Blob !== 'undefined' && archivo instanceof Blob) {
        formData.append('archivo', archivo, 'orden_del_dia.csv')
      } else if (typeof archivo === 'string') {
        const blob = new Blob([archivo], { type: 'text/csv;charset=utf-8' })
        formData.append('archivo', blob, 'orden_del_dia.csv')
      } else if (archivo instanceof Uint8Array) {
        const blob = new Blob([archivo as unknown as BlobPart], { type: 'text/csv' })
        formData.append('archivo', blob, 'orden_del_dia.csv')
      } else {
        formData.append('archivo', archivo as unknown as Blob)
      }
    }

    return this.rest.postMultipart<RespuestaOrdenDelDia>('/api/v1/orden-del-dia', formData, signal)
  }

  /**
   * Descarta la colección activa del Orden del Día en memoria.
   *
   * Endpoint: DELETE /api/v1/orden-del-dia
   */
  async descartarOrdenDelDia(signal?: AbortSignal): Promise<void> {
    return this.rest.deleteVacio('/api/v1/orden-del-dia', signal)
  }

  // ===========================================================================
  // 5. Comandos de Votaciones
  // ===========================================================================

  /**
   * Abre una nueva votación formal en el sistema (CU-07 / CU-08).
   *
   * Endpoint: POST /api/v1/votaciones
   */
  async abrirVotacion(
    datos: SolicitudAperturaVotacion,
    signal?: AbortSignal,
  ): Promise<RespuestaVotacion> {
    return this.rest.post<RespuestaVotacion>('/api/v1/votaciones', datos, signal)
  }

  /**
   * Finaliza anticipadamente una votación EN_CURSO con motivo obligatorio, resultando en INCONCLUSA (CU-10).
   *
   * Endpoint: POST /api/v1/votaciones/{id}/finalizacion
   */
  async finalizarVotacion(id: string, motivo: string, signal?: AbortSignal): Promise<void> {
    const cuerpo: SolicitudFinalizarVotacion = { motivo }
    return this.rest.postVacio(
      `/api/v1/votaciones/${encodeURIComponent(id)}/finalizacion`,
      cuerpo,
      signal,
    )
  }

  /**
   * Emite el voto presidencial de desempate en una votación simple CERRADA y EMPATADA (CU-13).
   *
   * Endpoint: POST /api/v1/votaciones/{id}/desempate
   */
  async desempatar(
    id: string,
    sentido: 'POSITIVO' | 'NEGATIVO',
    signal?: AbortSignal,
  ): Promise<void> {
    const cuerpo: SolicitudDesempate = { sentido }
    return this.rest.postVacio(
      `/api/v1/votaciones/${encodeURIComponent(id)}/desempate`,
      cuerpo,
      signal,
    )
  }

  // ===========================================================================
  // 6. Comandos de Uso de la Palabra
  // ===========================================================================

  /**
   * Otorga la palabra al primer concejal en cola, finalizando al orador anterior si existía (CU-17).
   *
   * Endpoint: POST /api/v1/palabra
   */
  async otorgarPalabra(signal?: AbortSignal): Promise<void> {
    return this.rest.postVacio('/api/v1/palabra', undefined, signal)
  }

  /**
   * Finaliza el uso de palabra del orador actual sin promover automáticamente al siguiente en cola (CU-18).
   *
   * Endpoint: DELETE /api/v1/palabra
   */
  async quitarPalabra(signal?: AbortSignal): Promise<void> {
    return this.rest.deleteVacio('/api/v1/palabra', signal)
  }

  // ===========================================================================
  // 7. Coordinación pública de remapeo físico
  // ===========================================================================

  /*
    Los tres comandos siguientes se delegan en `ClienteRemapeoDispositivos` desde WP-074.

    Los endpoints y la firma pública no cambiaron: Moderación sigue llamando a
    `cliente.iniciarRemapeo(...)` igual que antes. Lo que cambió es dónde está la
    implementación, porque el puesto de Apoyo Técnico también la necesita y ya no observa
    la proyección de Moderación. Una sola implementación evita que una corrección futura
    quede aplicada en un solo puesto.
  */

  /**
   * Inicia captura para un devXX del padrón activo. El navegador sigue
   * comunicándose solo con FastAPI; nunca conoce la URL local del bridge.
   */
  async iniciarRemapeo(dispositivo: string, signal?: AbortSignal): Promise<EstadoRemapeoRespuesta> {
    return this.remapeo.iniciarRemapeo(dispositivo, signal)
  }

  /** Autoriza el candidato congelado con la persistencia elegida. */
  async confirmarRemapeo(
    remapeoId: string,
    persistencia: PersistenciaRemapeo,
    signal?: AbortSignal,
  ): Promise<void> {
    return this.remapeo.confirmarRemapeo(remapeoId, persistencia, signal)
  }

  /** Cancela captura/candidato sin cambiar el mapping físico. */
  async cancelarRemapeo(remapeoId: string, signal?: AbortSignal): Promise<void> {
    return this.remapeo.cancelarRemapeo(remapeoId, signal)
  }
}

/**
 * Fábrica para instanciar ClienteModeracion.
 */
export function crearClienteModeracion(
  configuracion: ConfiguracionCliente = {},
): ClienteModeracion {
  return new ClienteModeracion(configuracion)
}
