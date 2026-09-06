<script setup lang="ts">
/**
 * Shell de la SPA de Apoyo Técnico (WP-056, redistribuido por WP-059).
 *
 * Responsabilidades:
 * 1. Abrir la **única** suscripción autoritativa del puesto (WP-074). Desde ese mismo
 *    estado salen también el remapeo y la sonorización, que antes exigían dos streams más
 *    y agotaban las conexiones HTTP/1.1 del navegador con las cuatro superficies abiertas.
 * 2. Alimentar la cabecera con conexión, estado global y estado de transmisión.
 * 3. Disponer los cinco bloques operativos en una grilla que entra completa a 1366×768 y
 *    a 1920×1080, sin scroll de página.
 * 4. Conectar la biblioteca de mensajes con el formulario de avisos, de modo que elegir
 *    un preset lo precargue sin publicarlo.
 * 5. Reproducir los mismos quince sonidos que la Pantalla del Recinto (WP-071), sin
 *    agregar ningún control visible.
 *
 * Sobre el dimensionado: el shell no fija alturas en píxeles. La altura total la aporta
 * `h-dvh`, el reparto lo resuelven Flexbox y CSS Grid con fracciones, y cada panel
 * confina su desborde a su propio cuerpo.
 *
 * La distribución de escritorio la cerró HUMAN_GATE en WP-059 y es la siguiente:
 *
 * ```text
 * ┌──────────────┬──────────────┬─────────────────┬──────────────────┐
 * │ Transmisión  │   Remapeo    │    Mensajes     │                  │
 * ├──────────────┴──────────────┴─────────────────┤     Eventos      │
 * │                    Avisos                     │                  │
 * └───────────────────────────────────────────────┴──────────────────┘
 * ```
 *
 * Son cuatro columnas visuales, pero **no** cuatro columnas iguales: las tres de la
 * izquierda comparten aproximadamente dos tercios del ancho y Eventos conserva el tercio
 * restante. Eventos ocupa además las dos filas: es la única lista que crece sola y
 * necesita todo el alto útil.
 *
 * WP-070 desbalancea levemente esas tres columnas izquierdas: `2fr 2fr 2,6fr` en lugar de
 * `2fr 2fr 2fr`. El motivo es medible y no estético. En cada mensaje precargado, la
 * etiqueta de destino más los botones «Usar en el formulario», «Editar» y «Eliminar»
 * necesitan ~311 px de renglón una vez achicados los botones, y a 1366×768 la columna de
 * 2fr sólo ofrecía ~259 px útiles: la fila envolvía a dos y hasta tres renglones. Con
 * 2,6fr la columna de Mensajes pasa a ~359 px y deja ~323 px útiles, que alcanzan con
 * margen. El costo se reparte proporcionalmente entre las otras tres columnas (~6 % cada
 * una) y no cambia la estructura: Eventos sigue quedándose con algo más del 30 % del
 * ancho y las tres izquierdas con algo menos del 70 %, exactamente el reparto que cerró
 * WP-059. Es el ajuste mínimo que resuelve la fila única sin rediseñar ningún panel.
 *
 * Las dos filas se reparten con fracciones y no con alturas fijas —9fr arriba y 11fr
 * abajo— porque Avisos es la superficie de trabajo grande del puesto: debe poder
 * redactarse un aviso largo sin que el panel gane scroll, y el textarea crece para ocupar
 * lo que sobra. La proporción está elegida para que a 1366×768 los tres paneles
 * superiores sigan enteros y a 1920×1080 sobre espacio en ambas filas.
 *
 * Por debajo del breakpoint `lg` la grilla se apila en una sola columna y recupera scroll
 * defensivo, que es la misma estrategia adaptable que ya usa Moderación.
 */

import { computed, shallowRef } from 'vue'
import { usePresentacionTecnica, useSonidosRecinto } from '@botonera2/frontend-shared'
import GestionRemapeo from '@botonera2/frontend-shared/componentes/GestionRemapeo.vue'
import IndicadorCargaInicial from '@botonera2/frontend-shared/componentes/IndicadorCargaInicial.vue'
import type { DestinoAvisoTecnico } from '@botonera2/api-client'
import { useEstadoTecnico } from './composables/useEstadoTecnico'
import { resolverRutaAsset } from './utils/rutas'
import CabeceraTecnico from './components/CabeceraTecnico.vue'
import PanelTecnico from './components/PanelTecnico.vue'
import ControlTransmision from './components/ControlTransmision.vue'
import ControlAvisos from './components/ControlAvisos.vue'
import BibliotecaMensajes from './components/BibliotecaMensajes.vue'
import ListaEventosTecnicos from './components/ListaEventosTecnicos.vue'

const { estado, estadoConexion, revision, conectado, desactualizado, cliente, clienteRemapeo } =
  useEstadoTecnico()

const transmision = computed(() => estado.value?.transmision ?? null)
const avisoModeracion = computed(() => estado.value?.aviso_moderacion ?? null)
const avisoRecinto = computed(() => estado.value?.aviso_recinto ?? null)
const biblioteca = computed(() => estado.value?.biblioteca ?? null)
const eventos = computed(() => estado.value?.eventos_recientes ?? [])

/**
 * Allowlist de remapeo que viaja dentro del estado técnico (WP-074).
 *
 * Antes este dato salía de un `EstadoModeracion` completo obtenido por una suscripción
 * propia. Ahora es una porción del único snapshot: mismos campos, misma autoridad, una
 * conexión menos.
 */
const remapeo = computed(() => estado.value?.remapeo ?? null)

/**
 * Subproyección con la que este puesto sonoriza igual que el salón (WP-074).
 *
 * Contiene exactamente los campos que compara el detector de transiciones. Al venir dentro
 * del mismo estado, el sonido queda además sincronizado con lo que muestran los paneles: es
 * la misma revisión, no dos streams que podrían adelantarse uno al otro.
 */
const sonorizacion = computed(() => estado.value?.sonorizacion ?? null)

const { segundosTransmision, segundosRestantesAviso } = usePresentacionTecnica(
  computed(() => ({
    transmision: transmision.value,
    avisos: [avisoModeracion.value, avisoRecinto.value],
    generadoEn: estado.value?.generado_en ?? null,
  })),
)

/**
 * Borrador precargado desde la biblioteca.
 *
 * Se pasa como prop y no se publica: `ControlAvisos` decide cuándo adoptarlo. La copia
 * lleva una marca incremental para que volver a elegir el mismo preset también vuelva a
 * precargar el formulario, aunque el texto y el destino sean idénticos.
 */
const borradorSeleccionado = shallowRef<{
  texto: string
  destino: DestinoAvisoTecnico
  marca: number
} | null>(null)
let marcaBorrador = 0

function seleccionarBorrador(mensaje: { texto: string; destino: DestinoAvisoTecnico }): void {
  marcaBorrador += 1
  borradorSeleccionado.value = { ...mensaje, marca: marcaBorrador }
}

/**
 * Sonidos del recinto reproducidos también por Apoyo Técnico (WP-071).
 *
 * El objetivo operativo lo cerró HUMAN_GATE: poder tomar el audio del salón desde el
 * equipo técnico. Para que la paridad sea exacta y no una imitación, esta pantalla usa el
 * **mismo** composable que la Pantalla del Recinto y le entrega los mismos tres insumos.
 *
 * 1. `sonorizacion` y `estadoConexion` son la subproyección pública y el estado del único
 *    stream de esta pantalla. Con el stream abierto, cada estado adoptado es un hecho
 *    nuevo; sin él, es una baseline y no debe sonar. Eso cubre a la vez el primer snapshot,
 *    la recarga de la página y cualquier reconexión: Apoyo Técnico no reproduce historia.
 *    Desde WP-074 el canal que se observa es el técnico, porque ya no existe un segundo
 *    stream público que pudiera reconectar por su cuenta.
 * 2. `segundosTransmision` es el número de la cuenta regresiva que ya se calcula acá
 *    arriba para mostrarlo en el panel de Transmisión. Se reutiliza a propósito, por dos
 *    motivos: el tic acompaña exactamente al dígito que el operador ve bajar, y no se
 *    agrega ningún reloj ni ninguna consulta nueva. El backend no emite una revisión por
 *    segundo y este WP prohíbe pedírsela.
 * 3. `resolverRutaAsset` arma la URL bajo el prefijo `/tecnico/`, donde la construcción
 *    publica los mismos archivos versionados del Recinto.
 *
 * No se renderiza nada: no hay botón de activación, ni control de volumen, ni selector de
 * salida. Si el navegador del puesto técnico bloquea la reproducción automática, la
 * pantalla sigue operando con normalidad y el permiso se otorga en la configuración del
 * equipo, igual que en el recinto (ver `docs/13-despliegue-y-operacion.md`).
 */
useSonidosRecinto({
  estado: sonorizacion,
  estadoConexion,
  segundosCuentaRegresiva: segundosTransmision,
  resolverUrl: resolverRutaAsset,
})
</script>

<template>
  <div
    class="flex h-dvh w-full min-w-0 flex-col overflow-hidden bg-slate-950 text-slate-100 antialiased"
  >
    <!--
      Barra indeterminada de carga inicial (WP-061): continúa el indicador previo a la
      hidratación hasta que llega el primer `EstadoTecnico`. Posicionada `fixed`, no
      participa del reparto de la grilla y desaparece sin dejar espacio.
    -->
    <IndicadorCargaInicial v-if="!estado" />

    <CabeceraTecnico
      :estado-conexion="estadoConexion"
      :estado-global="estado?.estado_global ?? null"
      :revision="revision"
      :desactualizado="desactualizado"
      :estado-transmision="transmision?.estado ?? null"
    />

    <main class="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden p-2">
      <div
        data-testid="grilla-tecnica"
        class="grid min-h-0 min-w-0 flex-1 auto-rows-[minmax(45dvh,auto)] grid-cols-1 gap-2 overflow-y-auto lg:auto-rows-auto lg:grid-cols-[repeat(2,minmax(0,2fr))_minmax(0,2.6fr)_minmax(0,3fr)] lg:grid-rows-[minmax(0,9fr)_minmax(0,11fr)] lg:overflow-hidden"
      >
        <PanelTecnico
          titulo="Transmisión"
          subtitulo="Indicador institucional; no controla la señal audiovisual"
          data-testid="panel-transmision"
          class="lg:col-start-1 lg:row-start-1"
        >
          <ControlTransmision
            :transmision="transmision"
            :segundos-restantes="segundosTransmision"
            :cliente="cliente"
            :conectado="conectado"
          />
        </PanelTecnico>

        <PanelTecnico
          titulo="Remapeo de dispositivos"
          subtitulo="Misma operación y capacidades que Moderación"
          data-testid="panel-remapeo-tecnico"
          class="lg:col-start-2 lg:row-start-1"
        >
          <GestionRemapeo :estado="remapeo" :cliente="clienteRemapeo" :conectado="conectado" />
        </PanelTecnico>

        <!--
          Único panel de los dos tercios izquierdos autorizado a tener scroll interno
          permanente: la biblioteca es una lista que crece con el uso y no puede recortarse.
        -->
        <PanelTecnico
          titulo="Mensajes precargados"
          subtitulo="Persistidos por el backend en CSV"
          data-testid="panel-biblioteca"
          class="lg:col-start-3 lg:row-start-1"
        >
          <BibliotecaMensajes
            :biblioteca="biblioteca"
            :cliente="cliente"
            :conectado="conectado"
            @cargar="seleccionarBorrador"
          />
        </PanelTecnico>

        <!-- Avisos toma la fila inferior completa de las tres columnas izquierdas. -->
        <PanelTecnico
          titulo="Avisos"
          subtitulo="Reemplazan temporalmente una superficie de Moderación o del Recinto"
          data-testid="panel-avisos"
          class="lg:col-span-3 lg:col-start-1 lg:row-start-2"
        >
          <ControlAvisos
            :aviso-moderacion="avisoModeracion"
            :aviso-recinto="avisoRecinto"
            :cliente="cliente"
            :conectado="conectado"
            :borrador="borradorSeleccionado"
            :segundos-restantes="segundosRestantesAviso"
          />
        </PanelTecnico>

        <!-- Eventos ocupa la columna derecha completa: es la única lista que crece sola. -->
        <PanelTecnico
          titulo="Eventos"
          subtitulo="Misma franja segura que ve Moderación"
          data-testid="panel-eventos-tecnico"
          class="lg:col-start-4 lg:row-span-2 lg:row-start-1"
        >
          <ListaEventosTecnicos :eventos="eventos" />
        </PanelTecnico>
      </div>
    </main>
  </div>
</template>
