/**
 * Cliente TypeScript para el Simulador Web de Dispositivos Lógicos de SIS-Leg.
 *
 * Responsabilidades:
 * 1. Proporcionar un canal tipado y seguro para la emisión de pulsaciones lógicas
 *    directas al endpoint canónico del backend: POST /api/v1/entradas/tecla.
 * 2. Permitir la sincronización diagnóstica del estado general del sistema consumiendo
 *    la proyección autoritativa de Moderación (GET /api/v1/estado/moderacion y su stream SSE).
 * 3. Mantener una estricta separación de responsabilidades:
 *    - NO expone los comandos mutantes administrativos del operador (iniciar sesión, abrir votación, etc.).
 *    - NO atraviesa el device-bridge físico: se comunica directamente con FastAPI emitiendo identificadores
 *      lógicos (ej. dev01..dev12) y teclas funcionales (1, 2, 3, 7, 8, 9).
 *    - Deja que FastAPI sea la única autoridad para validar padrón, habilitación de teclas y efectos institucionales.
 */

import { ClienteRest, crearClienteRest } from './rest'
import { iniciarSincronizacionEstado } from './sincronizador'
import type {
  ConfiguracionCliente,
  EstadoModeracion,
  OpcionesSuscripcion,
  RespuestaTecla,
  SolicitudTecla,
  Suscripcion,
} from './tipos'

/**
 * Cliente especializado para la aplicación web del simulador lógico.
 */
export class ClienteSimulador {
  /** Capa REST subyacente para comunicación HTTP directa */
  private readonly rest: ClienteRest
  /** Configuración inyectada al cliente (URL base, función fetch, etc.) */
  private readonly configuracion: ConfiguracionCliente

  /**
   * Crea una nueva instancia del cliente de simulador.
   *
   * @param configuracion Parámetros opcionales de conexión, URL base o fetch personalizado.
   */
  constructor(configuracion: ConfiguracionCliente = {}) {
    this.configuracion = configuracion
    this.rest = crearClienteRest(configuracion)
  }

  // ===========================================================================
  // 1. Diagnóstico y sincronización del estado general
  // ===========================================================================

  /**
   * Obtiene un snapshot REST completo del estado institucional actual.
   *
   * Utiliza la proyección de Moderación para alimentar el panel general con
   * datos de quórum, presentes, estado global y resumen de votación activa.
   *
   * Endpoint: GET /api/v1/estado/moderacion
   *
   * @param signal Señal opcional de cancelación AbortSignal.
   * @returns Promesa con el EstadoModeracion actual devuelto por FastAPI.
   */
  async obtenerEstado(signal?: AbortSignal): Promise<EstadoModeracion> {
    return this.rest.get<EstadoModeracion>('/api/v1/estado/moderacion', signal)
  }

  /**
   * Inicia el ciclo reactivo de sincronización continua (Snapshot inicial -> Stream SSE -> Reconexión).
   *
   * Mantiene el panel de diagnóstico actualizado en tiempo real ante eventos emitidos
   * por el backend, reconectando con retroceso exponencial si la conexión se interrumpe.
   *
   * Endpoint SSE: GET /api/v1/estado/moderacion/stream
   *
   * @param opciones Callbacks de actualización (alEstado), errores (alError) y estado de conexión (alCambiarConexion).
   * @returns Objeto Suscripcion con método cancelar() para liberar recursos al desmontar la interfaz.
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
  // 2. Emisión de pulsaciones lógicas directas
  // ===========================================================================

  /**
   * Envía una pulsación lógica de tecla para un dispositivo determinado directamente a FastAPI.
   *
   * Esta llamada no pasa por el device-bridge físico. FastAPI procesa la pulsación de forma
   * atómica mediante el serializador único del backend y responde con el resultado funcional
   * estable (aceptada o rechazada con su motivo).
   *
   * Endpoint: POST /api/v1/entradas/tecla
   * Body exacto: { "dispositivo": string, "tecla": string }
   *
   * @param solicitud Objeto con el identificador lógico del dispositivo (ej. 'dev01') y la tecla (ej. '9').
   * @param signal Señal opcional de cancelación AbortSignal.
   * @returns Promesa con la RespuestaTecla devuelta por el servidor (status 200 con aceptada=true/false).
   * @throws ErrorHttp Si el backend responde 422 (body inválido), 500 o 503 (fallo de fsync en auditoría).
   * @throws ErrorTransporte Si falla la conexión de red con el backend.
   */
  async enviarTecla(solicitud: SolicitudTecla, signal?: AbortSignal): Promise<RespuestaTecla> {
    return this.rest.post<RespuestaTecla>('/api/v1/entradas/tecla', solicitud, signal)
  }
}

/**
 * Función fábrica para instanciar convenientemente un ClienteSimulador.
 *
 * @param configuracion Parámetros opcionales de conexión.
 * @returns Nueva instancia de ClienteSimulador.
 */
export function crearClienteSimulador(configuracion: ConfiguracionCliente = {}): ClienteSimulador {
  return new ClienteSimulador(configuracion)
}
