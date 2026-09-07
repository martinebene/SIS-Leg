<script setup lang="ts">
/**
 * Contenedor estructural de cada panel del puesto de Apoyo Técnico.
 *
 * Cumple la misma función que `PanelContenedor` en Moderación —encabezado fijo, cuerpo
 * con scroll propio y altura acotada a la celda de la grilla— con la densidad y la
 * paleta de esta pantalla. Es una copia deliberada de la *forma*, no de la lógica: no
 * contiene ninguna regla de negocio, y DT-024 pide compartición mínima de UI, no una
 * librería de componentes común construida por anticipado.
 *
 * La invariante importante es la misma que en Moderación: el panel nunca fija su propia
 * altura ni crece con su contenido. Ocupa exactamente la celda que le asigna el shell y
 * confina cualquier desborde a su cuerpo, de modo que ningún panel pueda empujar a otro
 * ni provocar scroll de página.
 *
 * WP-083 elimina el subtítulo del encabezado. Hasta la quinta ronda cada panel llevaba
 * una línea explicativa debajo del título; la revisión humana concluyó que ninguna de
 * esas frases le decía nada nuevo al operador entrenado y que todas competían con el
 * contenido por un alto que en este puesto es escaso. La aclaración no se movió a otro
 * lugar de la pantalla: vive en el manual, que es donde se explica el sistema. Como el
 * subtítulo desaparece del *contrato* del componente y no sólo de las llamadas, ningún
 * panel futuro puede reintroducirlo por descuido.
 */

defineProps<{
  /** Título del área operativa. */
  titulo: string
  /** Texto informativo compacto alineado a la derecha del encabezado. */
  badge?: string
  /** Clases del badge cuando conviene destacarlo. */
  claseBadge?: string
  /** Identificador estable para las pruebas de DOM. */
  dataTestid?: string
}>()
</script>

<template>
  <section
    :data-testid="dataTestid"
    class="flex h-full min-h-0 min-w-0 flex-col overflow-hidden rounded-lg border border-slate-800 bg-slate-900/90 shadow-sm"
  >
    <header
      class="flex shrink-0 items-center justify-between gap-2 border-b border-slate-800 bg-slate-900 px-2.5 py-1"
    >
      <!-- Encabezado de una sola línea desde WP-083: título y, si corresponde, badge. -->
      <div class="min-w-0 flex-1">
        <h2 class="truncate text-sm font-semibold text-slate-100">{{ titulo }}</h2>
      </div>
      <div v-if="badge || $slots.acciones" class="flex shrink-0 items-center gap-2">
        <span
          v-if="badge"
          class="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium"
          :class="claseBadge || 'border border-slate-700 bg-slate-800 text-slate-300'"
        >
          {{ badge }}
        </span>
        <slot name="acciones" />
      </div>
    </header>

    <!-- Único contenedor con scroll del panel: el desborde muere acá dentro. -->
    <div data-testid="cuerpo-panel-tecnico" class="min-h-0 flex-1 overflow-y-auto p-2">
      <slot />
    </div>
  </section>
</template>
