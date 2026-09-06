/** Utilidades de presentación para el reloj visual de la cabecera pública. */

// Se reexporta la regla compartida para conservar la API local existente de Recinto.
// El cálculo vive en frontend-shared porque Moderación debe aplicar exactamente la
// misma interpretación de timestamps backend sin zona horaria.
export {
  calcularDuracionEnSnapshot,
  convertirMarcaBackend,
  formatearDuracion,
} from '@sis-leg/frontend-shared'

function rellenarConCeros(valor: number, ancho: number): string {
  return String(valor).padStart(ancho, '0')
}

/** Formatea el reloj del monitor como fecha y hora local con segundos. */
export function formatearFechaHoraLocal(fecha: Date): string {
  if (Number.isNaN(fecha.getTime())) return '—'
  return [
    `${rellenarConCeros(fecha.getDate(), 2)}/${rellenarConCeros(fecha.getMonth() + 1, 2)}/${rellenarConCeros(fecha.getFullYear(), 4)}`,
    `${rellenarConCeros(fecha.getHours(), 2)}:${rellenarConCeros(fecha.getMinutes(), 2)}:${rellenarConCeros(fecha.getSeconds(), 2)}`,
  ].join(' ')
}
