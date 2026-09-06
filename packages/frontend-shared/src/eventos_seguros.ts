/**
 * Reglas de presentación de la franja segura de eventos operativos.
 *
 * Moderación (WP-041/WP-052) y Apoyo Técnico (WP-056) muestran exactamente la misma
 * colección `eventos_recientes`: el backend ya aplicó la frontera de secreto de WP-052
 * antes de proyectarla, de modo que ninguna de las dos pantallas decide qué puede verse.
 * Lo único que ambas comparten es *cómo* se presenta esa colección:
 *
 * - el filtro por nivel es **acumulativo**, igual que los tres CSV institucionales:
 *   L1 contiene L1+L2+L3, L2 contiene L2+L3 y L3 contiene sólo L3;
 * - el evento más nuevo (mayor `seq`) se muestra primero;
 * - la detección de "llegó actividad nueva" se hace con un único número, el `seq` máximo
 *   del snapshot, y nunca acumulando un historial local.
 *
 * Estas funciones son puras a propósito: no tocan el DOM, no guardan estado y no
 * consultan el reloj. Así pueden probarse sin montar ningún componente y las dos
 * interfaces quedan obligadas a comportarse igual.
 */

import type { EventoRecienteProyectado } from '@sis-leg/api-client'

/** Nivel elegido por el operador en el selector visual. */
export type FiltroNivelEventos = 'L1' | 'L2' | 'L3'

/**
 * Niveles efectivamente visibles para cada opción del selector.
 *
 * Se declara como tabla y no como comparación de orden porque los niveles son
 * etiquetas institucionales, no números: escribirlos explícitamente evita que una
 * refactorización futura invente una jerarquía distinta de la de la auditoría.
 */
export const NIVELES_POR_FILTRO: Record<FiltroNivelEventos, readonly string[]> = {
  L3: ['L3'],
  L2: ['L2', 'L3'],
  L1: ['L1', 'L2', 'L3'],
}

/**
 * Devuelve los eventos visibles para un nivel, ordenados del más nuevo al más viejo.
 *
 * Trabaja siempre sobre una copia: `filter` ya crea un arreglo nuevo y el `sort`
 * posterior opera sobre esa copia. La colección autoritativa que llegó del backend no
 * se reordena ni se muta, que es la invariante que permite adoptar cada snapshot tal
 * como viene sin acumular estado local.
 *
 * @param eventos Colección `eventos_recientes` del snapshot vigente.
 * @param filtro Nivel elegido por el operador.
 * @returns Copia filtrada y ordenada por `seq` descendente.
 */
export function filtrarEventosPorNivel(
  eventos: readonly EventoRecienteProyectado[] | null | undefined,
  filtro: FiltroNivelEventos,
): EventoRecienteProyectado[] {
  const permitidos = NIVELES_POR_FILTRO[filtro]
  return (eventos ?? [])
    .filter((evento) => permitidos.includes(evento.nivel))
    .sort((primero, segundo) => segundo.seq - primero.seq)
}

/**
 * Calcula el `seq` máximo del snapshot completo, sin aplicar el filtro visual.
 *
 * Se ignora el filtro a propósito: cambiar el nivel visible no es actividad nueva en el
 * recinto y no debe interpretarse como tal. Devuelve `null` cuando todavía no hay ningún
 * evento, para poder distinguir "no llegó nada" de "llegó el evento número cero".
 *
 * @param eventos Colección `eventos_recientes` del snapshot vigente.
 * @returns Mayor `seq` observado, o `null` si la colección está vacía.
 */
export function seqMaximoEventos(
  eventos: readonly EventoRecienteProyectado[] | null | undefined,
): number | null {
  let maximo: number | null = null
  for (const evento of eventos ?? []) {
    if (maximo === null || evento.seq > maximo) maximo = evento.seq
  }
  return maximo
}

/**
 * Indica si un snapshot trae actividad posterior a la última observada.
 *
 * Es la condición que usa la interfaz para devolver la lista al inicio de su scroll.
 * Un `seq` menor al anterior (reinicio de contexto operativo, con la secuencia otra vez
 * desde cero) **no** cuenta como actividad nueva: en ese caso la lista ya fue
 * reemplazada por completo y mover el scroll del operador no aportaría nada.
 *
 * @param maximoActual `seq` máximo del snapshot recién adoptado.
 * @param maximoPrevio `seq` máximo observado hasta ese momento, o `null` al inicio.
 */
export function hayActividadNueva(
  maximoActual: number | null,
  maximoPrevio: number | null,
): boolean {
  if (maximoActual === null) return false
  if (maximoPrevio === null) return true
  return maximoActual > maximoPrevio
}
