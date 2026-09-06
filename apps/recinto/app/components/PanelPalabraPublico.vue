<script setup lang="ts">
/**
 * Cola FIFO pública de pedidos de uso de la palabra.
 *
 * El orador en uso no se muestra acá: se comunica exclusivamente resaltando su
 * banca en la grilla. Este panel sólo enumera a quienes esperan turno, en el
 * orden exacto que envía el backend.
 *
 * Legibilidad a distancia (WP-054). HUMAN_GATE observó sobre la captura real que
 * la cola era ilegible desde el recinto, así que:
 *
 * - el nombre pasa a ser el elemento dominante del renglón;
 * - el número de banca crece hasta ser legible sin acercarse;
 * - el círculo de orden **no** crece: es una referencia secundaria y agrandarlo
 *   le robaría ancho al nombre, que es el dato que se necesita leer;
 * - nada de esto puede producir scroll horizontal: el ancho de la columna es
 *   fijo y ambos textos se recortan con elipsis dentro de él.
 *
 * Segundo salto de legibilidad (WP-064). HUMAN_GATE volvió a mirar la pantalla
 * desde el recinto y decidió que el nombre todavía era chico, así que se lo
 * agranda **aproximadamente un 80 %** respecto de lo que dejó WP-054. La
 * decisión se aplica sólo al nombre:
 *
 * - la banca, el círculo de orden y el ancho de la columna quedan intactos, de
 *   modo que todo el crecimiento se traduce en jerarquía a favor del nombre;
 * - el renglón se vuelve más alto y entran menos pedidos a la vez en la parte
 *   visible de la lista; eso es un costo aceptado, porque la lista ya nació con
 *   desplazamiento vertical propio y el orden FIFO no cambia;
 * - el recorte con elipsis sigue siendo la única respuesta a un nombre que no
 *   entra, que es lo que mantiene la promesa de "nunca scroll horizontal".
 */

import type { EstadoPalabraPublico } from '@sis-leg/api-client'

defineProps<{ palabra: EstadoPalabraPublico | null }>()
</script>

<template>
  <section data-testid="panel-palabra" class="panel-palabra">
    <div class="encabezado-cola">
      <span>Pedidos de uso de la palabra</span>
      <b data-testid="cantidad-pedidos-palabra">{{ palabra?.cola.length ?? 0 }}</b>
    </div>

    <!-- La lista conserva el orden recibido; no consulta ni reordena al orador. -->
    <ol
      v-if="palabra?.cola.length"
      data-testid="cola-palabra"
      class="cola-palabra"
      aria-label="Pedidos de uso de la palabra en orden FIFO"
    >
      <li v-for="(persona, indice) in palabra.cola" :key="`${persona.banca}-${indice}`">
        <span class="orden-cola">{{ indice + 1 }}</span>
        <span class="persona-cola">
          <strong
            data-testid="nombre-cola-palabra"
            :title="`${persona.nombre} ${persona.apellido}`"
          >
            {{ persona.nombre }} {{ persona.apellido }}
          </strong>
          <small data-testid="banca-cola-palabra">Banca {{ persona.banca }}</small>
        </span>
      </li>
    </ol>
    <p v-else class="cola-vacia">No hay pedidos en espera</p>
  </section>
</template>

<style scoped>
.panel-palabra {
  min-height: 0;
  display: flex;
  flex: 1;
  flex-direction: column;
  padding: clamp(0.65rem, 1vw, 0.9rem);
  overflow: hidden;
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 16px;
  background: rgba(15, 23, 42, 0.78);
}

.encabezado-cola {
  display: flex;
  flex: 0 0 auto;
  justify-content: space-between;
  gap: 0.6rem;
  margin: 0 0 0.55rem;
  color: #94a3b8;
  font-size: 0.66rem;
  font-weight: 900;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.encabezado-cola b {
  min-width: 1.5rem;
  padding: 0.12rem 0.4rem;
  border-radius: 999px;
  color: #e2e8f0;
  background: rgba(14, 116, 144, 0.38);
  text-align: center;
}

/*
  `overflow-x: hidden` es explícito, no heredado: la lista es el único
  contenedor que podría desplazarse lateralmente si un nombre no entrara, y el
  WP exige que eso jamás ocurra. El desplazamiento vertical sí es legítimo
  cuando hay más pedidos que altura disponible.
*/
.cola-palabra {
  min-height: 0;
  margin: 0;
  padding: 0 0.15rem 0 0;
  overflow-x: hidden;
  overflow-y: auto;
  list-style: none;
}

.cola-palabra li {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  padding: 0.52rem 0;
  border-top: 1px solid rgba(148, 163, 184, 0.13);
}

/*
  Círculo de orden: geometría deliberadamente congelada (WP-054).

  1,6 rem exactos, igual que en la baseline. Es la referencia secundaria del
  renglón; todo el crecimiento tipográfico va al nombre y a la banca.
*/
.orden-cola {
  display: grid;
  place-items: center;
  width: 1.6rem;
  height: 1.6rem;
  flex: 0 0 auto;
  border-radius: 50%;
  color: #0c4a6e;
  background: #bae6fd;
  font-size: 0.68rem;
  font-weight: 900;
}

.persona-cola {
  min-width: 0;
}

/*
  Nombre: dato dominante del renglón. Es un rango elástico, no un tamaño fijo,
  para que crezca con la pantalla sin depender de una resolución concreta. El
  recorte por elipsis se conserva: es lo que impide que un apellido largo empuje
  el ancho de la columna.

  WP-064 multiplica por 1,8 los tres términos del `clamp` que había fijado
  WP-054 —`0,92rem / 1,02vw / 1,28rem`—. Multiplicar los tres por el mismo
  factor, en vez de elegir números nuevos "a ojo", tiene una consecuencia útil:
  cualquiera sea el término que gane en una resolución dada, el resultado es
  exactamente 1,8 veces el anterior. Por eso el aumento del 80 % se puede medir
  y se cumple igual en Full HD, donde manda el término `vw`, que en 1366×768,
  donde manda el mínimo en `rem`.

  Medición real en Chromium sobre el commit base, con raíz de 16 px:

  | resolución | antes     | ahora     | factor |
  |------------|-----------|-----------|--------|
  | 1920×1080  | 19,584 px | 35,251 px | 1,80   |
  | 1366×768   | 14,720 px | 26,496 px | 1,80   |
*/
.persona-cola strong {
  display: block;
  overflow: hidden;
  font-size: clamp(1.656rem, 1.836vw, 2.304rem);
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/*
  Banca: dato de identificación institucional. También crece respecto de la
  baseline (0,63 rem) y se recorta igual que el nombre.

  WP-064 la deja deliberadamente donde estaba. El pedido humano era agrandar el
  nombre, y no tocar la banca hace dos cosas a la vez: ensancha la diferencia de
  jerarquía entre el dato que se lee de lejos y el que se consulta de cerca, y
  evita gastar en la segunda línea el alto vertical que ahora necesita el nombre.
*/
.persona-cola small {
  display: block;
  margin-top: 0.1rem;
  overflow: hidden;
  color: #cbd5e1;
  font-size: clamp(0.74rem, 0.8vw, 0.98rem);
  font-weight: 700;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cola-vacia {
  min-height: 0;
  display: grid;
  flex: 1;
  place-items: center;
  margin: 0;
  color: #64748b;
  font-size: 0.76rem;
  text-align: center;
}
</style>
