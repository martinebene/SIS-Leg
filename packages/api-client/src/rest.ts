/**
 * Cliente REST base tipado y configurable.
 *
 * Encapsula la comunicación HTTP con FastAPI utilizando fetch nativo, normalización
 * uniforme de errores, serialización JSON, soporte de 204 No Content, multipart/form-data
 * para el Orden del Día y control de cancelación mediante AbortSignal.
 */

import { ErrorCancelacion, ErrorHttp, ErrorProtocolo, ErrorTransporte } from './errores'
import type { ConfiguracionCliente } from './tipos'

/**
 * Opciones para una petición HTTP.
 */
export interface OpcionesSolicitud {
  /** Cuerpo a serializar en formato JSON (omitir para peticiones sin cuerpo) */
  body?: unknown
  /** Señal de cancelación AbortSignal */
  signal?: AbortSignal
  /** Encabezados HTTP adicionales */
  headers?: HeadersInit
}

/**
 * Capa común de transporte REST.
 */
export class ClienteRest {
  readonly baseUrl: string
  private readonly funcionFetch: typeof fetch

  constructor(configuracion: ConfiguracionCliente = {}) {
    // Normalizamos la URL base quitando la barra final si estuviera presente
    this.baseUrl = configuracion.baseUrl ? configuracion.baseUrl.replace(/\/+$/, '') : ''
    // Algunos navegadores exigen que la función nativa conserve `globalThis`
    // como contexto. Si guardáramos `fetch` sin enlazarla, la llamada posterior
    // `this.funcionFetch(...)` podría fallar con "Illegal invocation" antes de
    // emitir la petición. Las implementaciones inyectadas se conservan intactas
    // para que mocks y adaptadores mantengan el contexto que hayan definido.
    this.funcionFetch = configuracion.fetch ?? globalThis.fetch.bind(globalThis)
  }

  /**
   * Construye la URL completa combinando la URL base y la ruta relativa.
   */
  construirUrl(ruta: string): string {
    if (!this.baseUrl) {
      return ruta
    }
    const rutaNormalizada = ruta.startsWith('/') ? ruta : `/${ruta}`
    return `${this.baseUrl}${rutaNormalizada}`
  }

  /**
   * Ejecuta una petición HTTP esperando una respuesta JSON tipada.
   *
   * @template T Tipo del payload JSON esperado.
   * @param metodo Método HTTP (GET, POST, etc.).
   * @param ruta Ruta del endpoint (por ejemplo: "/api/v1/estado/moderacion").
   * @param opciones Opciones de cuerpo, headers y signal.
   * @returns Promesa con el JSON tipado.
   */
  async solicitarJson<T>(
    metodo: string,
    ruta: string,
    opciones: OpcionesSolicitud = {},
  ): Promise<T> {
    const respuesta = await this.ejecutarFetch(metodo, ruta, opciones)

    // Si el servidor responde 204 No Content, no intentamos parsear JSON
    if (respuesta.status === 204) {
      return undefined as unknown as T
    }

    const texto = await respuesta.text().catch((error) => {
      throw new ErrorTransporte('Error al leer el cuerpo de la respuesta HTTP', error)
    })

    if (!texto.trim()) {
      return undefined as unknown as T
    }

    try {
      return JSON.parse(texto) as T
    } catch (error) {
      throw new ErrorProtocolo(
        `La respuesta del backend en ${metodo} ${ruta} no es un JSON válido`,
        error,
      )
    }
  }

  /**
   * Ejecuta una petición HTTP para comandos que no devuelven contenido (204 No Content).
   *
   * @param metodo Método HTTP (POST, PATCH, DELETE, etc.).
   * @param ruta Ruta del endpoint.
   * @param opciones Opciones de cuerpo, headers y signal.
   */
  async solicitarVacio(
    metodo: string,
    ruta: string,
    opciones: OpcionesSolicitud = {},
  ): Promise<void> {
    await this.ejecutarFetch(metodo, ruta, opciones)
  }

  /**
   * Ejecuta una petición HTTP enviando datos en formato multipart/form-data.
   *
   * IMPORTANTE: No se define manualmente el encabezado Content-Type para permitir
   * que el navegador o runtime establezca automáticamente el boundary multipart.
   *
   * @template T Tipo del payload JSON esperado en la respuesta.
   * @param metodo Método HTTP (típicamente POST).
   * @param ruta Ruta del endpoint.
   * @param formData Instancia de FormData con el archivo a cargar.
   * @param opciones Opciones de headers y signal.
   * @returns Promesa con el JSON tipado.
   */
  async solicitarMultipart<T>(
    metodo: string,
    ruta: string,
    formData: FormData,
    opciones: Omit<OpcionesSolicitud, 'body'> = {},
  ): Promise<T> {
    const url = this.construirUrl(ruta)
    let respuesta: Response

    try {
      respuesta = await this.funcionFetch(url, {
        method: metodo,
        body: formData,
        signal: opciones.signal,
        headers: opciones.headers,
      })
    } catch (error) {
      if (opciones.signal?.aborted) {
        throw new ErrorCancelacion('Petición multipart abortada')
      }
      throw new ErrorTransporte('Error de red al ejecutar petición multipart', error)
    }

    if (!respuesta.ok) {
      await this.procesarErrorHttp(respuesta)
    }

    const texto = await respuesta.text().catch((error) => {
      throw new ErrorTransporte('Error al leer respuesta multipart', error)
    })

    try {
      return JSON.parse(texto) as T
    } catch (error) {
      throw new ErrorProtocolo('Respuesta multipart con JSON malformado', error)
    }
  }

  /**
   * Ejecuta la llamada fetch nativa con serialización JSON y gestión uniforme de errores.
   */
  private async ejecutarFetch(
    metodo: string,
    ruta: string,
    opciones: OpcionesSolicitud,
  ): Promise<Response> {
    const url = this.construirUrl(ruta)
    const headers: Record<string, string> = {}

    if (opciones.body !== undefined) {
      headers['Content-Type'] = 'application/json'
    }

    if (opciones.headers) {
      Object.assign(headers, opciones.headers)
    }

    let respuesta: Response
    try {
      respuesta = await this.funcionFetch(url, {
        method: metodo,
        headers,
        body: opciones.body !== undefined ? JSON.stringify(opciones.body) : undefined,
        signal: opciones.signal,
      })
    } catch (error) {
      if (opciones.signal?.aborted) {
        throw new ErrorCancelacion('Petición HTTP abortada')
      }
      throw new ErrorTransporte(`Error de conexión al ejecutar ${metodo} ${url}`, error)
    }

    if (!respuesta.ok) {
      await this.procesarErrorHttp(respuesta)
    }

    return respuesta
  }

  /**
   * Extrae la información de una respuesta HTTP no exitosa y lanza un ErrorHttp estructurado.
   */
  private async procesarErrorHttp(respuesta: Response): Promise<never> {
    const texto = await respuesta.text().catch(() => '')
    let json: Record<string, unknown> | null = null

    if (texto.trim()) {
      try {
        json = JSON.parse(texto) as Record<string, unknown>
      } catch {
        json = null
      }
    }

    // Si coincide con el contrato estructurado canónico { codigo, mensaje }
    if (json !== null && typeof json.codigo === 'string' && typeof json.mensaje === 'string') {
      throw new ErrorHttp(respuesta.status, {
        codigo: json.codigo,
        mensaje: json.mensaje,
        cuerpoCrudo: texto,
      })
    }

    // Si tiene otro detalle estructurado (ej. detalle 422 de Pydantic)
    if (json !== null) {
      throw new ErrorHttp(respuesta.status, {
        detalle: json.detail ?? json,
        cuerpoCrudo: texto,
      })
    }

    // Si es texto plano o está vacío
    throw new ErrorHttp(respuesta.status, {
      detalle: texto || undefined,
      cuerpoCrudo: texto,
    })
  }

  // Métodos de conveniencia para verbos HTTP estándar

  async get<T>(ruta: string, signal?: AbortSignal): Promise<T> {
    return this.solicitarJson<T>('GET', ruta, { signal })
  }

  async post<T>(ruta: string, body?: unknown, signal?: AbortSignal): Promise<T> {
    return this.solicitarJson<T>('POST', ruta, { body, signal })
  }

  async postVacio(ruta: string, body?: unknown, signal?: AbortSignal): Promise<void> {
    return this.solicitarVacio('POST', ruta, { body, signal })
  }

  async put<T>(ruta: string, body?: unknown, signal?: AbortSignal): Promise<T> {
    return this.solicitarJson<T>('PUT', ruta, { body, signal })
  }

  async patchVacio(ruta: string, body?: unknown, signal?: AbortSignal): Promise<void> {
    return this.solicitarVacio('PATCH', ruta, { body, signal })
  }

  async deleteVacio(ruta: string, signal?: AbortSignal): Promise<void> {
    return this.solicitarVacio('DELETE', ruta, { signal })
  }

  /**
   * Variante de DELETE para el único comando que devuelve cuerpo: el cierre de sesión.
   *
   * Se agrega junto a `deleteVacio` en lugar de reemplazarlo porque los demás DELETE del
   * contrato siguen respondiendo 204 y no deben empezar a esperar JSON.
   */
  async delete<T>(ruta: string, signal?: AbortSignal): Promise<T> {
    return this.solicitarJson<T>('DELETE', ruta, { signal })
  }

  async postMultipart<T>(ruta: string, formData: FormData, signal?: AbortSignal): Promise<T> {
    return this.solicitarMultipart<T>('POST', ruta, formData, { signal })
  }
}

/**
 * Fábrica para instanciar ClienteRest.
 */
export function crearClienteRest(configuracion: ConfiguracionCliente = {}): ClienteRest {
  return new ClienteRest(configuracion)
}
