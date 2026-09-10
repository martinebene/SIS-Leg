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
 *
 * Redistribución horizontal (WP-097). La prueba de campo mostró que a 1280×720 el
 * título se partía en dos renglones y que nombres corrientes se cortaban con
 * elipsis. HUMAN_GATE pidió resolverlo **ensanchando y redistribuyendo**, no
 * achicando la tipografía ni estirando la altura. Por eso:
 *
 * - el título ocupa ahora el ancho completo del encabezado, en un solo renglón,
 *   y su cuerpo escala con el ancho real de la columna;
 * - dentro de cada pedido, el nombre pasa a la primera línea a **ancho completo**
 *   del renglón y el círculo de orden baja a la segunda línea junto a la banca.
 *   El círculo dejaba de estar disponible para el nombre ~36 px de ancho, que es
 *   justamente lo que faltaba para que entrara un nombre de 18 caracteres;
 * - el renglón resultante no es más alto que antes: se cambió alto por ancho, que
 *   es lo que el WP pide priorizar.
 *
 * El límite de 18 caracteres se garantiza por geometría y no por confiar en una
 * tipografía concreta: el cuerpo del nombre está acotado por una fracción del
 * ancho del propio contenedor (`cqi`), de modo que si la columna se angosta el
 * texto se angosta con ella y el nombre sigue entrando entero.
 */

import type { EstadoPalabraPublico } from '@sis-leg/api-client'

defineProps<{ palabra: EstadoPalabraPublico | null }>()
</script>

<template>
  <section data-testid="panel-palabra" class="panel-palabra">
    <div class="encabezado-cola">
      <span data-testid="titulo-cola-palabra" class="titulo-cola">
        Pedidos de uso de la palabra
      </span>
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
        <strong data-testid="nombre-cola-palabra" :title="`${persona.nombre} ${persona.apellido}`">
          {{ persona.nombre }} {{ persona.apellido }}
        </strong>
        <span class="referencia-cola">
          <span class="orden-cola">{{ indice + 1 }}</span>
          <small data-testid="banca-cola-palabra">Banca {{ persona.banca }}</small>
        </span>
      </li>
    </ol>
    <p v-else class="cola-vacia">No hay pedidos en espera</p>
  </section>
</template>

<style scoped>
/*
  Relleno lateral reducido a la mitad (WP-097): cada píxel que el panel deja de
  gastar en su propio borde interior es ancho que gana el nombre, que es el dato
  que debe leerse desde el fondo del recinto.

  `container-type: inline-size` convierte al panel en el contenedor de referencia
  de las consultas `cqi` que usan el título y el nombre. Es un contenedor de ancho
  solamente —no de tamaño— para no romper el reparto vertical de la columna.
*/
.panel-palabra {
  min-height: 0;
  display: flex;
  flex: 1;
  flex-direction: column;
  padding: clamp(0.35rem, 0.55vw, 0.5rem);
  overflow: hidden;
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 16px;
  background: rgba(15, 23, 42, 0.78);
  container-type: inline-size;
}

/*
  Encabezado a ancho completo (WP-097).

  Antes era un `flex` con `space-between` y cuerpo fijo de 0,66 rem: a 1280×720 el
  título no entraba en una línea y se partía en dos, desperdiciando alto y dando
  la impresión de un bloque angosto. Ahora es una grilla de dos columnas donde el
  título toma todo el sobrante y el contador conserva su ancho propio.

  El cuerpo del título se expresa como fracción del ancho del panel (`cqi`) con un
  tope en `rem`: así llena el ancho disponible en pantallas chicas —que es lo que
  pidió HUMAN_GATE— sin volverse desproporcionado en Full HD.
*/
.encabezado-cola {
  display: grid;
  flex: 0 0 auto;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 0.5rem;
  margin: 0 0 0.4rem;
  color: #94a3b8;
  font-size: min(1rem, 3.9cqi);
  font-weight: 900;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.titulo-cola {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
  /*
    WP-097 reserva siempre el canal de la barra de desplazamiento. Sin esa reserva el
    ancho útil del renglón cambia según haya o no scroll, y la garantía de que un nombre
    de 18 caracteres entra completo valdría sólo con la lista corta.
  */
  scrollbar-gutter: stable;
}

/*
  Renglón apilado (WP-097): el nombre arriba, a ancho completo, y la referencia
  secundaria —orden y banca— abajo, en una sola línea horizontal. Antes el orden
  ocupaba una columna propia a la izquierda y le restaba ancho al nombre en los
  dos renglones.
*/
.cola-palabra li {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
  padding: 0.4rem 0;
  border-top: 1px solid rgba(148, 163, 184, 0.13);
}

/*
  Línea inferior de referencia: orden y banca comparten renglón horizontal. Es
  información de consulta cercana, no de lectura a distancia, así que conserva su
  tamaño chico y cede todo el protagonismo al nombre.
*/
.referencia-cola {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 0.4rem;
}

/*
  Círculo de orden: geometría deliberadamente congelada (WP-054).

  1,6 rem exactos, igual que en la baseline. Es la referencia secundaria del
  renglón; todo el crecimiento tipográfico va al nombre. Desde WP-097 comparte
  línea con la banca en lugar de ocupar una columna propia.
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

  WP-097 conserva ese `clamp` intacto y sólo le agrega un techo geométrico: el
  cuerpo nunca supera el 8,6 % del ancho del panel. Ese número sale de una cuenta
  y no de una prueba a ojo: con el ancho de columna que fija `PantallaRecinto`,
  18 caracteres ocupan como máximo `18 × 0,62 em ≈ 11,2 em`, y `100 / 11,2 ≈ 8,9`,
  así que 8,6 cqi deja además un margen para tipografías más anchas que Inter.

  El techo está por encima del `clamp` en las tres resoluciones objetivo, de modo
  que el tamaño medido no cambia respecto de WP-064 y sólo actúa como red de
  seguridad si la columna se angostara.
*/
.cola-palabra strong {
  display: block;
  min-width: 0;
  overflow: hidden;
  font-size: min(clamp(1.656rem, 1.836vw, 2.304rem), 8.6cqi);
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
.referencia-cola small {
  min-width: 0;
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
