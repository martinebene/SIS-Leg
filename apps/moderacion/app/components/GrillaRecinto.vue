<script setup lang="ts">
/**
 * Construye en Moderación la misma geometría física que ve el Recinto público.
 *
 * `filas_bancas` enumera filas desde abajo hacia arriba. Como el DOM se dibuja
 * de arriba hacia abajo, se invierte solamente la colección de filas. Dentro de
 * cada fila se conserva la numeración creciente y cada persona se busca por banca.
 */

import { computed } from 'vue'
import type { ConcejalModeracion, VotoModeracion } from '@sis-leg/api-client'
import BancaConcejal from './BancaConcejal.vue'

interface BancaFisica {
  numero: number
  concejal: ConcejalModeracion | null
  /** Media-columna inicial; cada tarjeta ocupa dos para permitir centrado exacto. */
  columnaInicial: number
}

interface FilaFisica {
  numero: number
  bancas: BancaFisica[]
}

const props = defineProps<{
  /** Lista proyectada; su orden no expresa la ubicación física. */
  concejales: ConcejalModeracion[]
  /** Cantidad de posiciones por fila, enumeradas desde la fila inferior. */
  filasBancas?: number[] | null
  /** Banca del orador proyectado; null retira inmediatamente el resaltado. */
  bancaOrador?: number | null
  /**
   * `estado_recepcion` de la votación relevante; `null` cuando no hay votación.
   *
   * Es lo que distingue "ya votó" (recepción abierta) de "votó esto" (cerrada).
   */
  estadoRecepcion?: string | null
  /**
   * Contenido de `bancas_voto_emitido`: qué bancas ya emitieron su voto.
   *
   * El backend solo lo puebla mientras la recepción está `EN_CURSO` y jamás
   * incluye el sentido, de modo que Q3 puede mostrar participación sin romper
   * el secreto del voto.
   */
  bancasVotoEmitido?: number[] | null
  /**
   * Votos individuales finales, ya asociados a su banca.
   *
   * Solo debe llegar cuando la votación dejó de estar `EN_CURSO`: es la regla
   * visual común con Recinto y prevalece sobre la política histórica de
   * revelado anticipado que otros componentes de Moderación puedan aplicar.
   */
  votosIndividuales?: VotoModeracion[] | null
}>()

/** Conjunto para consultar participación en tiempo constante por banca. */
const bancasEmitidas = computed(() => new Set(props.bancasVotoEmitido ?? []))

/**
 * Sentido final por banca.
 *
 * Se ignora por completo mientras la recepción sigue abierta: aunque el DTO de
 * Moderación revele votos antes del cierre por su política histórica, estas
 * tarjetas comparten la regla pública de WP-045.
 */
const votoFinalPorBanca = computed(() => {
  if (props.estadoRecepcion === 'EN_CURSO') return new Map<number, string>()
  return new Map((props.votosIndividuales ?? []).map((voto) => [voto.banca, voto.valor]))
})

/**
 * Cantidad de columnas de la grilla común a todas las filas.
 *
 * WP-045 exige que TODAS las tarjetas de Q3 midan lo mismo. Con filas de
 * distinta longitud (por ejemplo `[5, 7]`), repartir cada fila en `1fr` propios
 * haría más anchas las tarjetas de la fila corta. Se usa entonces una única
 * grilla con dos subcolumnas por banca. Cada tarjeta ocupa dos, por lo que una
 * fila con sobrante impar reparte media tarjeta a cada lado y queda realmente
 * centrada sin cambiar el ancho de ninguna tarjeta.
 */
const columnasMaximas = computed(() =>
  props.filasBancas?.length ? Math.max(...props.filasBancas) : props.concejales.length || 1,
)

const filasVisuales = computed<FilaFisica[]>(() => {
  if (!props.filasBancas?.length) {
    // SIN_PREPARAR puede no incluir configuración. Para un uso aislado del componente,
    // el fallback conserva una única fila ordenada sin inventar una geometría adicional.
    const bancas = [...props.concejales]
      .sort((primero, segundo) => primero.banca - segundo.banca)
      .map((concejal, indice) => ({
        numero: concejal.banca,
        concejal,
        columnaInicial: indice * 2 + 1,
      }))
    return bancas.length > 0 ? [{ numero: 1, bancas }] : []
  }

  const concejalesPorBanca = new Map(props.concejales.map((concejal) => [concejal.banca, concejal]))
  const columnas = columnasMaximas.value
  let primeraBanca = 1
  const filasInferiorASuperior = props.filasBancas.map((cantidad, indice) => {
    // Una subcolumna equivale a media tarjeta. Así el sobrante se distribuye
    // simétricamente aunque la diferencia entre filas sea impar.
    const desplazamientoInicial = columnas - cantidad
    const bancas = Array.from({ length: cantidad }, (_, desplazamiento) => {
      const numero = primeraBanca + desplazamiento
      return {
        numero,
        concejal: concejalesPorBanca.get(numero) ?? null,
        columnaInicial: desplazamientoInicial + desplazamiento * 2 + 1,
      }
    })
    primeraBanca += cantidad
    return { numero: indice + 1, bancas }
  })

  // Nunca se invierte `bancas`: banca 1 debe continuar abajo a la izquierda.
  return filasInferiorASuperior.reverse()
})
</script>

<template>
  <div
    data-testid="grilla-recinto"
    class="flex h-full min-h-0 w-full flex-1 flex-col justify-end gap-1.5 py-1"
  >
    <div
      v-for="fila in filasVisuales"
      :key="fila.numero"
      :data-testid="`fila-bancas-${fila.numero}`"
      :data-fila-fisica="fila.numero"
      class="grid min-h-0 w-full flex-1 items-stretch gap-1.5 xl:gap-2"
      :style="{ gridTemplateColumns: `repeat(${columnasMaximas * 2}, minmax(0, 1fr))` }"
    >
      <template v-for="banca in fila.bancas" :key="banca.numero">
        <BancaConcejal
          v-if="banca.concejal"
          :style="{ gridColumn: `${banca.columnaInicial} / span 2` }"
          :concejal="banca.concejal"
          :es-orador="bancaOrador === banca.numero"
          :estado-recepcion="estadoRecepcion ?? null"
          :voto-emitido="bancasEmitidas.has(banca.numero)"
          :valor-voto-final="votoFinalPorBanca.get(banca.numero) ?? null"
        />
        <div
          v-else
          data-testid="banca-sin-datos"
          :data-banca="banca.numero"
          :style="{ gridColumn: `${banca.columnaInicial} / span 2` }"
          class="grid min-h-20 place-items-center rounded-lg border border-dashed border-slate-700 bg-slate-950/40 p-1 text-center text-[8px] text-slate-500"
        >
          Banca {{ banca.numero }} sin datos
        </div>
      </template>
    </div>

    <div
      v-if="filasVisuales.length === 0"
      data-testid="sin-concejales"
      class="rounded-lg border border-dashed border-slate-800 p-4 text-center text-xs text-slate-400"
    >
      No hay concejales registrados en el padrón activo.
    </div>
  </div>
</template>
