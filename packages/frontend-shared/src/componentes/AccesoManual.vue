<script setup lang="ts">
/**
 * Acceso de ayuda al manual de usuario de SIS-Leg (WP-067).
 *
 * ## Qué es
 *
 * Un enlace pequeño y redondo, con el signo de interrogación que la mayoría de las
 * interfaces usa para «ayuda», que abre el manual del sistema. Se coloca en el extremo
 * derecho de la cabecera de Moderación y de la de Apoyo Técnico.
 *
 * ## Por qué es un componente compartido
 *
 * El Work Package exige que las dos cabeceras ofrezcan «la misma función y un tratamiento
 * visual equivalente». Si cada aplicación dibujara su propio botón, una corrección
 * posterior podría aplicarse en una sola y las dos pantallas empezarían a diferir. Con un
 * único componente, la apariencia y el comportamiento son literalmente los mismos.
 *
 * Se estiliza con utilidades de Tailwind, igual que `GestionRemapeo.vue`: las dos únicas
 * aplicaciones que lo montan —Moderación y Apoyo Técnico— están construidas con Tailwind.
 *
 * ## Por qué es un enlace y no un botón
 *
 * Porque navega a un documento. Al ser un `<a>` con `href`, funciona el menú contextual
 * del navegador, se puede copiar la dirección y abrirla con el teclado sin necesidad de
 * ningún manejador propio. Un `<button>` con JavaScript perdería todo eso.
 *
 * ## Por qué se abre en otra pestaña
 *
 * La pantalla operativa no debe reemplazarse. Moderación puede tener una votación
 * recibiendo votos y Apoyo Técnico una transmisión en curso; navegar fuera obligaría a
 * volver a cargar la aplicación y a reconstruir el estado desde el backend. `target`
 * abre una pestaña aparte y `rel="noopener noreferrer"` impide que el documento abierto
 * pueda manipular la pestaña de origen.
 */

import { RUTA_MANUAL, ROTULO_ACCESO_MANUAL } from '../manual'

withDefaults(
  defineProps<{
    /** Identificador estable para las pruebas de DOM, componente y navegador. */
    dataTestid?: string
  }>(),
  {
    dataTestid: 'acceso-manual',
  },
)
</script>

<template>
  <!--
    `shrink-0` es deliberado: cuando el ancho aprieta, la cabecera recorta los textos de
    longitud imprevisible —los nombres de las autoridades— y nunca este acceso, que mide
    siempre lo mismo. Las medidas (`h-4 w-4`, cuerpo de 11 píxeles) son las de los demás
    indicadores de la cabecera, así que el enlace crece a lo ancho y no altera la altura
    de una barra que debe conservarse en una sola línea.
  -->
  <a
    :href="RUTA_MANUAL"
    target="_blank"
    rel="noopener noreferrer"
    :data-testid="dataTestid"
    :aria-label="ROTULO_ACCESO_MANUAL"
    :title="ROTULO_ACCESO_MANUAL"
    class="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-slate-600 bg-slate-800 text-[11px] font-bold leading-none text-slate-300 no-underline transition-colors hover:border-sky-600 hover:bg-sky-950 hover:text-sky-200 focus-visible:border-sky-500 focus-visible:text-sky-200"
  >
    <!-- El signo es decorativo: el texto accesible ya lo aporta `aria-label`. -->
    <span aria-hidden="true">?</span>
  </a>
</template>
