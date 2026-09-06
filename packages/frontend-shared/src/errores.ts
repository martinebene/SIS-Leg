/**
 * Lectura del rechazo devuelto por `@sis-leg/api-client`.
 *
 * Cuando el backend rechaza un comando, el cliente REST lanza un error que puede traer el
 * mensaje institucional en `mensajeBackend`, un texto propio del transporte en `mensaje`, o
 * simplemente el `message` estándar de `Error`. La interfaz debe mostrar el más específico
 * de los tres, en ese orden, **sin inventar** un texto propio cuando el backend ya explicó
 * el motivo: ocultar el rechazo detrás de una redacción genérica dificultaría diagnosticar
 * una operación fallida durante una sesión.
 *
 * Es una función pura, sin dependencias de Vue, para poder probarla directamente. La usan
 * el remapeo compartido y todos los comandos del puesto de Apoyo Técnico.
 */

/**
 * Devuelve el mensaje más específico disponible dentro de un rechazo.
 *
 * @param error Valor capturado en el `catch`. Puede ser cualquier cosa, por eso se
 *   inspecciona defensivamente en lugar de asumir una clase concreta.
 * @param mensajePredeterminado Texto a mostrar cuando el rechazo no aporta ninguno.
 */
export function extraerMensajeError(error: unknown, mensajePredeterminado: string): string {
  if (typeof error === 'object' && error !== null) {
    for (const campo of ['mensajeBackend', 'mensaje', 'message'] as const) {
      const valor = (error as Record<string, unknown>)[campo]
      if (typeof valor === 'string' && valor !== '') return valor
    }
  }
  return mensajePredeterminado
}
