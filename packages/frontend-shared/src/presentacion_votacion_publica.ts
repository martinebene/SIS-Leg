/**
 * Semántica compartida del bloque público `Votación / Tema / Estado` (WP-099).
 *
 * ## Por qué existe este archivo
 *
 * Hasta WP-098 este vocabulario vivía dentro de `PanelVotacionPublica.vue`, el componente
 * que dibuja la franja superior de la Pantalla del Recinto. Era el único lugar que lo
 * necesitaba, así que estaba bien ahí.
 *
 * WP-099 agrega una segunda superficie pública —el Zócalo para OBS— que debe mostrar
 * **exactamente el mismo significado** con otra geometría. Si cada pantalla escribiera sus
 * propias etiquetas, una corrección futura («Recepción cerrada» pasa a decir otra cosa,
 * la mayoría especial se describe distinto) se aplicaría en una sola y las dos divergirían
 * en silencio. Por eso las reglas de redacción se mudan acá y las dos superficies las
 * consumen: hay una sola definición de qué dice cada renglón.
 *
 * ## Qué NO hace
 *
 * No calcula reglas de negocio. El backend ya decidió resultado, conteos, mayoría y
 * estado de recepción; este módulo sólo traduce ese DTO a los textos institucionales que
 * se leen en pantalla. Tampoco decide *qué* votación mostrar: esa regla —ocultar la
 * votación en `SIN_PREPARAR` y dejar de mostrar un resultado ya vencido— vive en
 * `presentacion_votacion.ts`, que también es compartido.
 */

import { computed, type ComputedRef, type Ref } from 'vue'
import type { VotacionPublica } from '@sis-leg/api-client'

import { formatearFactorMayoria } from './factor_mayoria'

/** Conteos proyectados tal como viajan dentro del DTO público. */
export type ConteosVotacionPublica = NonNullable<VotacionPublica['conteos']>

/** Voto de desempate de Presidencia tal como viaja dentro del DTO público. */
export type VotoPresidencialPublico = NonNullable<VotacionPublica['voto_presidencial']>

/**
 * Redacción institucional de cada resultado cerrado.
 *
 * Las claves son los valores del contrato (mayúsculas) y los valores, el texto que lee una
 * persona. No se inventan estados nuevos: son exactamente los cuatro que define el dominio.
 */
export const ETIQUETAS_RESULTADO_VOTACION: Record<string, string> = {
  APROBADA: 'Aprobada',
  RECHAZADA: 'Rechazada',
  EMPATADA: 'Empatada',
  INCONCLUSA: 'Inconclusa',
}

/** Redacción institucional de cada base de cálculo de una mayoría especial. */
export const ETIQUETAS_BASE_MAYORIA: Record<string, string> = {
  VOTOS_COMPUTABLES: 'votos computables',
  PRESENTES: 'presentes',
  CUERPO: 'cuerpo completo',
}

/** Texto mostrado cuando el renglón no tiene dato que representar. */
export const TEXTO_SIN_DATO = '—'

/** Indica si la recepción de votos sigue abierta, único caso en que se ocultan conteos. */
export function votacionEnCurso(votacion: VotacionPublica | null): boolean {
  return votacion?.estado_recepcion === 'EN_CURSO'
}

/**
 * Describe la mayoría exigida por la votación.
 *
 * Una mayoría simple no lleva factor ni base: nombrarlos sería inventar información. Una
 * especial se describe con el factor formateado por la regla única de WP-063 y con la base
 * traducida; si apareciera una base desconocida se muestra el valor crudo antes que
 * ocultarlo, porque un rótulo vacío sería menos informativo que el código del contrato.
 */
export function describirMayoriaVotacion(votacion: VotacionPublica | null): string {
  if (!votacion) return ''
  if (votacion.tipo_mayoria === 'SIMPLE') return 'Mayoría simple'
  const base = ETIQUETAS_BASE_MAYORIA[votacion.base] ?? votacion.base
  return `Mayoría especial · factor ${formatearFactorMayoria(votacion.factor)} · base ${base}`
}

/** Arma el renglón `Votación`: número, tipo y mayoría exigida. */
export function resumirVotacion(votacion: VotacionPublica | null): string {
  if (!votacion) return 'Sin votación activa'
  return `N.º ${votacion.numero_votacion} · ${votacion.tipo} · ${describirMayoriaVotacion(votacion)}`
}

/** Arma el renglón `Tema`, con guion largo cuando todavía no hay votación. */
export function describirTemaVotacion(votacion: VotacionPublica | null): string {
  return votacion?.tema ?? TEXTO_SIN_DATO
}

/**
 * Arma el renglón `Estado`.
 *
 * Tres casos y ningún otro: sin votación, recepción abierta, o recepción cerrada. En el
 * último, el resultado manda; `Recepción cerrada` cubre el instante en que la recepción ya
 * terminó pero el backend todavía no publicó un resultado.
 */
export function describirEstadoVotacion(votacion: VotacionPublica | null): string {
  if (!votacion) return 'Sin votación'
  if (votacionEnCurso(votacion)) return 'En curso'
  return votacion.resultado
    ? (ETIQUETAS_RESULTADO_VOTACION[votacion.resultado] ?? 'Recepción cerrada')
    : 'Recepción cerrada'
}

/**
 * Devuelve el sufijo de clase CSS con el que cada superficie colorea el estado.
 *
 * Es sólo el dato normalizado en minúsculas: cada pantalla decide su propia paleta, pero
 * ambas parten del mismo discriminante para no pintar de verde en una lo que en la otra
 * está en ámbar.
 */
export function claseEstadoVotacion(votacion: VotacionPublica | null): string {
  return (votacion?.resultado ?? votacion?.estado_recepcion ?? 'SIN_VOTACION').toLowerCase()
}

/**
 * Devuelve los conteos sólo cuando pueden mostrarse.
 *
 * Mientras la recepción está `EN_CURSO` el secreto del voto lo impide, así que se devuelve
 * `null` aunque el DTO trajera números. Es la misma regla que ya aplicaba el Recinto.
 */
export function conteosVisiblesVotacion(
  votacion: VotacionPublica | null,
): ConteosVotacionPublica | null {
  if (votacionEnCurso(votacion)) return null
  return votacion?.conteos ?? null
}

/** Traduce el sentido de un voto de desempate a su forma legible. */
export function etiquetaSentidoVoto(sentido: string): string {
  if (sentido === 'POSITIVO') return 'Positivo'
  if (sentido === 'NEGATIVO') return 'Negativo'
  return sentido
}

/** Vista reactiva que consumen las plantillas de Recinto y de Zócalo. */
export interface PresentacionVotacionPublica {
  /** `true` mientras la recepción sigue abierta. */
  enCurso: ComputedRef<boolean>
  /** Renglón `Votación`. */
  resumen: ComputedRef<string>
  /** Renglón `Tema`. */
  tema: ComputedRef<string>
  /** Renglón `Estado`. */
  estado: ComputedRef<string>
  /** Sufijo de clase para colorear el estado. */
  claseEstado: ComputedRef<string>
  /** Conteos publicables, o `null` mientras rige el secreto del voto. */
  conteosVisibles: ComputedRef<ConteosVotacionPublica | null>
  /** `true` cuando la votación quedó empatada y espera el desempate de Presidencia. */
  esperaDesempate: ComputedRef<boolean>
  /** Voto de desempate ya emitido, o `null`. */
  votoPresidencial: ComputedRef<VotoPresidencialPublico | null>
}

/**
 * Convierte una referencia al DTO público en los textos de los tres renglones.
 *
 * @param votacion Referencia reactiva a la votación que la superficie decidió mostrar.
 *   Puede ser `null`, que es el caso normal fuera de una votación.
 * @returns Valores calculados; ninguno guarda estado propio, de modo que un snapshot nuevo
 *   se refleja en la misma renderización sin que la pantalla recuerde el anterior.
 *
 * No tiene efectos laterales ni temporizadores: todo lo que devuelve es función pura del
 * DTO recibido.
 */
export function usePresentacionVotacionPublica(
  votacion: Ref<VotacionPublica | null> | ComputedRef<VotacionPublica | null>,
): PresentacionVotacionPublica {
  return {
    enCurso: computed(() => votacionEnCurso(votacion.value)),
    resumen: computed(() => resumirVotacion(votacion.value)),
    tema: computed(() => describirTemaVotacion(votacion.value)),
    estado: computed(() => describirEstadoVotacion(votacion.value)),
    claseEstado: computed(() => claseEstadoVotacion(votacion.value)),
    conteosVisibles: computed(() => conteosVisiblesVotacion(votacion.value)),
    esperaDesempate: computed(() => votacion.value?.resultado === 'EMPATADA'),
    votoPresidencial: computed(() => votacion.value?.voto_presidencial ?? null),
  }
}
