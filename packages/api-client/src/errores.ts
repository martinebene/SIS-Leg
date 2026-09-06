/**
 * Modelo uniforme y discriminado de errores para el cliente API de SIS-Leg.
 *
 * Permite distinguir de forma tipada entre:
 * 1. ErrorHttp: Respuestas HTTP no exitosas devueltas por FastAPI (4xx, 5xx),
 *    preservando el contrato canónico { codigo, mensaje } cuando esté disponible.
 * 2. ErrorTransporte: Fallos de red, conexión rechazada o pérdida de enlace físico.
 * 3. ErrorProtocolo: Payloads corruptos, JSON inválido o respuestas que violan el contrato.
 * 4. ErrorCancelacion: Abortos intencionales o llamadas a dispose/cancelar.
 */

/**
 * Discriminante semántico para los tipos de errores del cliente API.
 */
export type TipoErrorApi = 'HTTP' | 'TRANSPORTE' | 'PROTOCOLO' | 'CANCELACION'

/**
 * Clase base abstracta para todos los errores generados o normalizados por el cliente API.
 */
export abstract class ErrorApi extends Error {
  abstract readonly tipo: TipoErrorApi

  constructor(mensaje: string, options?: ErrorOptions) {
    super(mensaje, options)
    // Garantiza compatibilidad con comprobaciones instanceof en entornos compilados a ES5/ES6
    Object.setPrototypeOf(this, new.target.prototype)
  }
}

/**
 * Representa un error devuelto formalmente por el backend mediante un código de estado HTTP no exitoso.
 *
 * Preserva exactamente los campos { codigo, mensaje } del backend cuando existan,
 * sin traducirlos ni reinterpretarlos. Si la respuesta es un 422 de validación de Pydantic
 * u otro cuerpo estructurado diferente, conserva el status y el detalle completo sin inventar
 * un código ficticio de dominio.
 */
export class ErrorHttp extends ErrorApi {
  readonly tipo = 'HTTP' as const

  /** Código de estado HTTP (por ejemplo: 400, 409, 422, 500, 503) */
  readonly estado: number

  /** Identificador de dominio estable del backend (si venía en el cuerpo { codigo, mensaje }) */
  readonly codigo?: string

  /** Mensaje explicativo provisto por el backend (si venía en el cuerpo { codigo, mensaje }) */
  readonly mensajeBackend?: string

  /** Detalle estructurado (por ejemplo, lista de errores de validación 422 de Pydantic/FastAPI) */
  readonly detalle?: unknown

  /** Texto crudo del cuerpo de la respuesta HTTP */
  readonly cuerpoCrudo?: string

  constructor(
    estado: number,
    opciones: {
      codigo?: string
      mensaje?: string
      detalle?: unknown
      cuerpoCrudo?: string
    } = {},
  ) {
    let mensajeError: string
    if (opciones.codigo && opciones.mensaje) {
      mensajeError = `Error HTTP ${estado} [${opciones.codigo}]: ${opciones.mensaje}`
    } else if (opciones.mensaje) {
      mensajeError = `Error HTTP ${estado}: ${opciones.mensaje}`
    } else if (opciones.detalle !== undefined) {
      const detalleTexto =
        typeof opciones.detalle === 'string' ? opciones.detalle : JSON.stringify(opciones.detalle)
      mensajeError = `Error HTTP ${estado}: ${detalleTexto}`
    } else {
      mensajeError = `Error HTTP ${estado}`
    }

    super(mensajeError)
    this.estado = estado
    this.codigo = opciones.codigo
    this.mensajeBackend = opciones.mensaje
    this.detalle = opciones.detalle
    this.cuerpoCrudo = opciones.cuerpoCrudo
  }
}

/**
 * Representa una falla en la capa de red o transporte HTTP / EventSource
 * (por ejemplo, servidor inalcanzable, timeout, conexión rechazada o abortada por red).
 */
export class ErrorTransporte extends ErrorApi {
  readonly tipo = 'TRANSPORTE' as const
  readonly causaOriginal?: unknown

  constructor(mensaje: string = 'Error de conexión o transporte de red', causaOriginal?: unknown) {
    super(mensaje, causaOriginal instanceof Error ? { cause: causaOriginal } : undefined)
    this.causaOriginal = causaOriginal
  }
}

/**
 * Representa una violación del protocolo esperado (por ejemplo: JSON malformado en SSE,
 * cuerpo no parseable cuando se esperaba JSON, o falta de campos mínimos requeridos).
 */
export class ErrorProtocolo extends ErrorApi {
  readonly tipo = 'PROTOCOLO' as const
  readonly causaOriginal?: unknown

  constructor(mensaje: string = 'Error de protocolo o formato de datos', causaOriginal?: unknown) {
    super(mensaje, causaOriginal instanceof Error ? { cause: causaOriginal } : undefined)
    this.causaOriginal = causaOriginal
  }
}

/**
 * Representa la cancelación o aborto deliberado de una operación o suscripción
 * (por ejemplo, vía AbortSignal o al invocar cancelar/dispose).
 */
export class ErrorCancelacion extends ErrorApi {
  readonly tipo = 'CANCELACION' as const

  constructor(mensaje: string = 'Operación cancelada') {
    super(mensaje)
  }
}

/**
 * Normaliza cualquier excepción capturada al modelo discriminado ErrorApi.
 *
 * @param error Objeto capturado en un bloque catch.
 * @returns Instancia tipada de ErrorApi.
 */
export function normalizarError(error: unknown): ErrorApi {
  if (error instanceof ErrorApi) {
    return error
  }

  if (error instanceof Error) {
    if (error.name === 'AbortError') {
      return new ErrorCancelacion(error.message)
    }
    if (error.name === 'TypeError' && error.message.includes('fetch')) {
      return new ErrorTransporte(error.message, error)
    }
    return new ErrorTransporte(error.message, error)
  }

  if (typeof error === 'string') {
    return new ErrorTransporte(error)
  }

  return new ErrorTransporte('Error desconocido', error)
}
