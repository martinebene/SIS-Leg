<script setup lang="ts">
/**
 * Controles de transmisión del puesto de Apoyo Técnico (WP-056).
 *
 * El ciclo es `APAGADO → (cuenta regresiva opcional) → EN VIVO → APAGADO manual`. Ninguna
 * de esas transiciones se decide acá: este componente sólo emite comandos y representa
 * `EstadoTecnico.transmision`, que el backend deriva de la frontera absoluta
 * `en_vivo_desde`. En particular, cuando la cuenta llega a cero la pantalla **no** pasa
 * sola a `EN VIVO`: espera la revisión que publica el backend al cruzar la frontera. Si
 * lo hiciera por su cuenta, dos puestos con relojes distintos mostrarían cosas distintas.
 *
 * Tampoco existe apagado automático: `EN VIVO` sólo termina con la orden de detener.
 *
 * El componente no controla ninguna señal audiovisual real: es únicamente el indicador
 * institucional, tal como fijó la decisión humana cerrada del WP-055.
 */

import { computed, ref } from 'vue'
import type { ClienteApoyoTecnico, TransmisionProyectada } from '@sis-leg/api-client'
import { extraerMensajeError } from '@sis-leg/frontend-shared'

const props = defineProps<{
  /** Estado autoritativo de la transmisión, o `null` antes del primer snapshot. */
  transmision: TransmisionProyectada | null
  /** Segundos que faltan para EN VIVO, derivados del reloj calibrado con el backend. */
  segundosRestantes: number | null
  /** Cliente de comandos del plano técnico. */
  cliente: ClienteApoyoTecnico
  /** Sólo una conexión confirmada habilita los comandos. */
  conectado: boolean
}>()

/** Cuenta regresiva propuesta por el operador, en segundos. El contrato admite 1..3600. */
const CUENTA_REGRESIVA_MINIMA = 1
const CUENTA_REGRESIVA_MAXIMA = 3600

/**
 * Valor propuesto al abrir la pantalla, en segundos (WP-083).
 *
 * Es sólo una **propuesta editable**: el operador puede escribir cualquier entero del
 * rango del contrato antes de pulsar «Iniciar con cuenta». La quinta ronda bajó la
 * propuesta de 10 s a 5 s porque la cuenta larga obligaba a corregir el campo casi
 * siempre; cinco segundos es lo que se usa en la práctica para anunciar la salida al
 * aire. No cambia ninguna validación: el rango 1..3600 lo sigue fijando el backend.
 */
const CUENTA_REGRESIVA_PROPUESTA = 5

const segundosSolicitados = ref(CUENTA_REGRESIVA_PROPUESTA)
const accionEnVuelo = ref<'INSTANTANEA' | 'CUENTA' | 'DETENER' | null>(null)
const mensajeError = ref<string | null>(null)

const estado = computed(() => props.transmision?.estado ?? 'APAGADO')
const apagada = computed(() => estado.value === 'APAGADO')

/** El valor propuesto debe estar dentro del rango que acepta el contrato REST. */
const cuentaValida = computed(
  () =>
    Number.isInteger(segundosSolicitados.value) &&
    segundosSolicitados.value >= CUENTA_REGRESIVA_MINIMA &&
    segundosSolicitados.value <= CUENTA_REGRESIVA_MAXIMA,
)

const puedeIniciar = computed(
  () => props.conectado && apagada.value && accionEnVuelo.value === null,
)
const puedeIniciarConCuenta = computed(() => puedeIniciar.value && cuentaValida.value)
const puedeDetener = computed(
  () => props.conectado && !apagada.value && accionEnVuelo.value === null,
)

/**
 * Ejecuta un comando de transmisión y deja que el snapshot confirme el resultado.
 *
 * Nunca se adelanta el estado de forma optimista: si la respuesta llega antes que la
 * revisión SSE, la pantalla sigue mostrando el estado autoritativo anterior hasta que el
 * backend publique el nuevo. Es la misma disciplina del remapeo.
 */
async function ejecutar(
  accion: 'INSTANTANEA' | 'CUENTA' | 'DETENER',
  comando: () => Promise<void>,
  mensajePredeterminado: string,
): Promise<void> {
  mensajeError.value = null
  accionEnVuelo.value = accion
  try {
    await comando()
  } catch (error: unknown) {
    mensajeError.value = extraerMensajeError(error, mensajePredeterminado)
  } finally {
    accionEnVuelo.value = null
  }
}

function iniciarInstantanea(): void {
  if (!puedeIniciar.value) return
  void ejecutar(
    'INSTANTANEA',
    () => props.cliente.iniciarTransmision(null),
    'No se pudo iniciar la transmisión.',
  )
}

function iniciarConCuenta(): void {
  if (!puedeIniciarConCuenta.value) return
  void ejecutar(
    'CUENTA',
    () => props.cliente.iniciarTransmision(segundosSolicitados.value),
    'No se pudo iniciar la cuenta regresiva.',
  )
}

function detener(): void {
  if (!puedeDetener.value) return
  void ejecutar(
    'DETENER',
    () => props.cliente.detenerTransmision(),
    'No se pudo detener la transmisión.',
  )
}
</script>

<template>
  <div data-testid="control-transmision" class="space-y-3 text-xs">
    <div
      data-testid="estado-transmision"
      class="flex items-center justify-between gap-2 rounded-lg border px-3 py-2"
      :data-estado="estado"
      :class="
        estado === 'EN_VIVO'
          ? 'border-rose-700 bg-rose-950/50 text-rose-200'
          : estado === 'CUENTA_REGRESIVA'
            ? 'border-sky-700 bg-sky-950/50 text-sky-200'
            : 'border-slate-700 bg-slate-950/60 text-slate-400'
      "
    >
      <span class="font-bold uppercase tracking-wider">
        <template v-if="estado === 'EN_VIVO'">● En vivo</template>
        <template v-else-if="estado === 'CUENTA_REGRESIVA'">Sale al aire en</template>
        <template v-else>Transmisión apagada</template>
      </span>
      <strong
        v-if="estado === 'CUENTA_REGRESIVA'"
        data-testid="cuenta-regresiva-tecnico"
        class="text-2xl leading-none tabular-nums text-white"
      >
        {{ segundosRestantes ?? 0 }}
      </strong>
    </div>

    <div class="flex flex-wrap items-center gap-2">
      <button
        type="button"
        data-testid="btn-transmision-instantanea"
        class="rounded-lg border border-emerald-700 bg-emerald-950 px-3 py-2 font-bold text-emerald-200 disabled:cursor-not-allowed disabled:opacity-40"
        :disabled="!puedeIniciar"
        @click="iniciarInstantanea"
      >
        {{ accionEnVuelo === 'INSTANTANEA' ? 'Iniciando...' : 'Iniciar ahora' }}
      </button>

      <!--
        WP-059 angostó esta columna a dos novenos del ancho útil. Sin `flex-wrap` el grupo
        "Cuenta / N / Iniciar con cuenta" mide más que la columna y produciría scroll
        horizontal dentro del panel; envolviendo, el botón baja de línea y el panel sigue
        sin desbordar en ninguna de las dos resoluciones de referencia.
      -->
      <div class="flex flex-wrap items-center gap-1">
        <label for="segundos-cuenta-regresiva" class="text-slate-400">Cuenta</label>
        <!--
          WP-083 achica este campo de `w-20` (5rem) a `w-12` (3rem).

          El ancho anterior venía de WP-056 y sobraba: la propuesta habitual tiene uno o
          dos dígitos, así que el campo mostraba una franja vacía tan ancha como el número.
          3rem es el mínimo práctico medido para dos dígitos con este cuerpo tipográfico:
          48 px de caja menos 2 px de borde y 8 px de relleno horizontal dejan 38 px de
          contenido, y dos dígitos `text-xs` ocupan ~14 px. El margen restante existe a
          propósito, porque el contrato sigue aceptando hasta cuatro dígitos y el operador
          debe poder escribir 3600 sin que el texto quede cortado; el campo desplaza su
          contenido, no lo recorta.

          `[appearance:textfield]` suprime las flechas nativas del `type=number`. En un
          campo de 3rem esas flechas se comerían la mitad del ancho útil justo cuando el
          puntero está encima, que es el momento en que el operador está por escribir. La
          entrada por teclado, la validación del rango y el contrato REST no cambian.
        -->
        <input
          id="segundos-cuenta-regresiva"
          v-model.number="segundosSolicitados"
          data-testid="input-cuenta-regresiva"
          type="number"
          :min="CUENTA_REGRESIVA_MINIMA"
          :max="CUENTA_REGRESIVA_MAXIMA"
          step="1"
          class="w-12 rounded border border-slate-700 bg-slate-950 px-1 py-1.5 text-center text-slate-100 tabular-nums [appearance:textfield] disabled:opacity-50 [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
          :disabled="!puedeIniciar"
        />
        <span class="text-slate-500">s</span>
        <button
          type="button"
          data-testid="btn-transmision-cuenta"
          class="rounded-lg border border-sky-700 bg-sky-950 px-3 py-2 font-bold text-sky-200 disabled:cursor-not-allowed disabled:opacity-40"
          :disabled="!puedeIniciarConCuenta"
          @click="iniciarConCuenta"
        >
          {{ accionEnVuelo === 'CUENTA' ? 'Iniciando...' : 'Iniciar con cuenta' }}
        </button>
      </div>

      <button
        type="button"
        data-testid="btn-transmision-detener"
        class="rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 font-bold text-slate-200 disabled:cursor-not-allowed disabled:opacity-40"
        :disabled="!puedeDetener"
        @click="detener"
      >
        {{ accionEnVuelo === 'DETENER' ? 'Deteniendo...' : 'Detener' }}
      </button>
    </div>

    <p
      v-if="!cuentaValida"
      data-testid="cuenta-invalida"
      class="rounded border border-amber-800 bg-amber-950/40 px-2 py-1 text-amber-200"
    >
      La cuenta regresiva debe ser un número entero entre {{ CUENTA_REGRESIVA_MINIMA }} y
      {{ CUENTA_REGRESIVA_MAXIMA }} segundos.
    </p>

    <p
      v-if="!conectado"
      data-testid="transmision-sin-conexion"
      class="rounded border border-amber-800 bg-amber-950/40 px-2 py-1 text-amber-200"
    >
      Los comandos de transmisión requieren conexión confirmada con FastAPI.
    </p>

    <p
      v-if="mensajeError"
      data-testid="error-transmision"
      class="rounded border border-rose-700 bg-rose-950/60 px-2 py-1 text-rose-200"
      role="alert"
    >
      {{ mensajeError }}
    </p>
  </div>
</template>
