/**
 * Utilidades puras de presentación temporal para el Shell de Moderación.
 *
 * Aquí no se calcula ningún dato institucional: la única fuente autoritativa de la
 * apertura formal de una sesión es `sesion.fecha_hora_apertura`, que llega desde el
 * backend. La resta robusta entre marcas backend se comparte con Recinto; este archivo
 * conserva el formateo de la hora local propio del puesto de Moderación.
 *
 * Todas las funciones son deterministas: reciben las fechas ya resueltas por quien
 * las llama y nunca consultan el reloj por su cuenta. Esa separación es la que permite
 * probarlas con un reloj falso.
 */

/**
 * Rellena un número con ceros a la izquierda hasta alcanzar el ancho indicado.
 *
 * @param valor Número a formatear (se asume entero no negativo).
 * @param ancho Cantidad mínima de dígitos del resultado.
 * @returns Texto con ceros a la izquierda, por ejemplo `07`.
 */
function rellenarConCeros(valor: number, ancho: number): string {
  return String(valor).padStart(ancho, '0')
}

/**
 * Formatea un instante en la hora local del puesto de Moderación.
 *
 * Se usa la hora local del equipo (y no UTC) porque la cabecera cumple la misma
 * función que el reloj de pared del recinto: orientar a quien opera. El formato es
 * el mismo que usa la interfaz en producción, `dd/mm/aaaa hh:mm:ss`, pero construido
 * de forma explícita para que el resultado sea idéntico en cualquier entorno.
 *
 * @param fecha Instante a mostrar.
 * @returns Texto compacto `dd/mm/aaaa hh:mm:ss`, o `'—'` si la fecha no es válida.
 */
export function formatearFechaHoraLocal(fecha: Date): string {
  if (Number.isNaN(fecha.getTime())) {
    return '—'
  }

  const dia = rellenarConCeros(fecha.getDate(), 2)
  const mes = rellenarConCeros(fecha.getMonth() + 1, 2)
  const anio = rellenarConCeros(fecha.getFullYear(), 4)
  const horas = rellenarConCeros(fecha.getHours(), 2)
  const minutos = rellenarConCeros(fecha.getMinutes(), 2)
  const segundos = rellenarConCeros(fecha.getSeconds(), 2)

  return `${dia}/${mes}/${anio} ${horas}:${minutos}:${segundos}`
}

// Las utilidades comunes se reexportan para mantener imports locales legibles y
// evitar que tests/componentes de Moderación deban conocer la estructura del paquete.
export {
  calcularDuracionEnSnapshot,
  convertirMarcaBackend,
  formatearDuracion,
} from '@sis-leg/frontend-shared'
