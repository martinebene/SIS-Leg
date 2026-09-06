<script setup lang="ts">
/**
 * Indicador público de transmisión (WP-056).
 *
 * Ocupa el quinto superior de la columna derecha del Recinto y representa los tres
 * estados que decide el backend, sin decidir ninguna transición por su cuenta:
 *
 * - `APAGADO`: presencia discreta. No se oculta el bloque porque su altura está
 *   reservada por la grilla; si desapareciera, los pedidos de palabra se moverían cada
 *   vez que Apoyo Técnico enciende o apaga la transmisión. Es la misma razón por la que
 *   la franja de votación conserva su alto aunque no haya votación.
 * - `CUENTA_REGRESIVA`: número grande, legible desde el fondo del recinto.
 * - `EN_VIVO`: rótulo `● EN VIVO` claramente visible.
 *
 * El número que baja lo calcula `usePresentacionTransmision` a partir de la frontera
 * absoluta `en_vivo_desde`; este componente sólo lo dibuja. Cuando la cuenta termina, el
 * backend republica y el estado pasa a `EN_VIVO`: la pantalla nunca hace esa transición
 * por sí misma, ni siquiera cuando el contador visual llega a cero.
 */

import type { TransmisionProyectada } from '@sis-leg/api-client'

defineProps<{
  /** Estado autoritativo de la transmisión proyectado por el backend. */
  transmision: TransmisionProyectada | null
  /** Segundos que faltan para EN VIVO, derivados del reloj local calibrado. */
  segundosRestantes: number | null
}>()
</script>

<template>
  <section
    data-testid="bloque-transmision"
    class="bloque-transmision"
    :data-estado-transmision="transmision?.estado ?? 'APAGADO'"
    role="status"
    aria-live="polite"
  >
    <template v-if="transmision?.estado === 'CUENTA_REGRESIVA'">
      <span class="rotulo-transmision">Sale al aire en</span>
      <strong data-testid="cuenta-regresiva-transmision" class="cuenta-transmision">
        {{ segundosRestantes ?? 0 }}
      </strong>
    </template>

    <strong v-else-if="transmision?.estado === 'EN_VIVO'" data-testid="en-vivo" class="en-vivo">
      <span aria-hidden="true">●</span> EN VIVO
    </strong>

    <span v-else data-testid="transmision-apagada" class="transmision-apagada">
      Transmisión apagada
    </span>
  </section>
</template>

<style scoped>
/*
  El bloque llena la celda que le asigna la columna derecha y recorta cualquier
  excedente: nunca puede empujar hacia abajo a los pedidos de palabra.
*/
.bloque-transmision {
  min-width: 0;
  min-height: 0;
  display: grid;
  place-content: center;
  justify-items: center;
  gap: 0.1rem;
  /*
    Relleno reducido en WP-058. El contenedor no cambia de tamaño —lo fija la
    grilla de la columna derecha— pero su content box sí crece unos 4 px en
    1366x768 y 3 px en 1920x1080, y ese es exactamente el espacio que necesita
    el número grande para entrar íntegro sin acercarse al borde.
  */
  padding: clamp(0.25rem, 0.45vw, 0.6rem);
  overflow: hidden;
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 16px;
  background: rgba(15, 23, 42, 0.78);
  text-align: center;
}

/* En vivo: el borde también comunica el estado a quien mira de lejos. */
.bloque-transmision[data-estado-transmision='EN_VIVO'] {
  border-color: rgba(248, 113, 113, 0.65);
  background: rgba(69, 10, 10, 0.55);
}

.bloque-transmision[data-estado-transmision='CUENTA_REGRESIVA'] {
  border-color: rgba(125, 211, 252, 0.55);
  background: rgba(8, 47, 73, 0.5);
}

/*
  Rótulo de la cuenta regresiva (WP-058).

  Crece junto con el número porque forma parte del mismo mensaje, pero se lo
  mantiene deliberadamente por debajo para que la jerarquía siga siendo
  "cuántos segundos faltan" y no "cómo se llama la espera". El techo de
  0,95 rem es lo que hace que su renglón nunca supere ~19 px y le deje al
  número el alto que necesita.

  El `line-height` de 1,25 no es decorativo: con 1,1 la caja de tinta de las
  mayúsculas superaba en 1 px la caja de línea y el bloque quedaba con
  `scrollHeight > clientHeight`. Es el mismo cuidado que se aplica al número.
*/
.rotulo-transmision {
  color: #bae6fd;
  font-size: clamp(0.6rem, 0.8vw, 0.95rem);
  font-weight: 900;
  letter-spacing: 0.14em;
  line-height: 1.25;
  text-transform: uppercase;
}

/*
  La cuenta usa el mayor cuerpo que admite un quinto de la columna derecha.

  Content box del bloque medido en Chromium sobre este WP —es decir, ya
  descontando borde y relleno, que es donde el texto tiene que entrar entero:

  | resolución | content box | rótulo + gap | alto libre para el número |
  |------------|-------------|--------------|---------------------------|
  | 1920x1080  | 365 x 142   | ~21 px       | ~121 px                   |
  | 1366x768   | 259 x 98    | ~15 px       | ~83 px                    |

  El `line-height` merece una explicación: la caja de tinta de un dígito de esta
  tipografía mide ~1,124 em, más que la caja de línea que produciría un
  `line-height` de 1. Con 1 o 1,1 el número desbordaba unos 2 px su propia caja
  y el bloque quedaba con `scrollHeight > clientHeight`, es decir con recorte
  silencioso. 1,15 em contiene el glifo completo y sigue entrando holgado.

  Con eso, 8,9vh da 96,1 px de cuerpo (caja de 110 px) en Full HD y 68,4 px
  (caja de 79 px) en 1366x768: en ambos casos el conjunto rótulo + número entra
  dentro del content box con margen. El ancho nunca es el límite —tres dígitos
  ocupan ~2,09 em, es decir 201 px y 143 px— y el techo absoluto de 6,5 rem
  protege a los monitores muy altos, donde el bloque crece de alto pero su ancho
  sigue acotado en 384 px.
*/
.cuenta-transmision {
  color: #f8fafc;
  font-size: clamp(1.8rem, 8.9vh, 6.5rem);
  font-variant-numeric: tabular-nums;
  line-height: 1.15;
  text-shadow: 0 0 24px rgba(56, 189, 248, 0.45);
}

/*
  EN VIVO ocupa el bloque entero, así que su límite es el ancho y no el alto:
  el rótulo completo mide ~6,6 em, de modo que 4,2vh (45,4 px en 1920x1080 y
  32,3 px en 1366x768) deja ~18 % de margen contra los 365 px y 259 px de
  content box. El techo de 3 rem evita que en pantallas muy altas el texto
  supere el ancho fijo máximo de la columna, y el `line-height` de 1,2 contiene
  la caja de tinta de las mayúsculas igual que en el rótulo de la cuenta.
*/
.en-vivo {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  overflow: hidden;
  color: #fecaca;
  font-size: clamp(0.95rem, 4.2vh, 3rem);
  font-weight: 900;
  letter-spacing: 0.12em;
  line-height: 1.2;
  white-space: nowrap;
}

.en-vivo span {
  color: #f87171;
}

/*
  Apagado: deliberadamente discreto. Comunica que el indicador existe y funciona, sin
  competir con los pedidos de palabra que ocupan los cuatro quintos inferiores.
*/
.transmision-apagada {
  overflow: hidden;
  color: #64748b;
  font-size: clamp(0.56rem, 0.72vw, 0.78rem);
  font-weight: 700;
  letter-spacing: 0.1em;
  line-height: 1.1;
  text-overflow: ellipsis;
  text-transform: uppercase;
  white-space: nowrap;
}
</style>
