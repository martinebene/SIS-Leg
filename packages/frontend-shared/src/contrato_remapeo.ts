/**
 * Contrato mínimo de estado que consume la interfaz compartida de remapeo (WP-074).
 *
 * ## Por qué existe
 *
 * `GestionRemapeo.vue` es una sola pantalla usada por dos puestos: Moderación y Apoyo
 * Técnico. Hasta WP-074 pedía un `EstadoModeracion` completo, lo que obligaba al puesto
 * técnico a suscribirse al stream de Moderación sólo para poder remapear. Con las cuatro
 * superficies de SISLeg abiertas bajo el mismo origen, esa suscripción de más era una de
 * las que dejaban al navegador sin conexiones HTTP/1.1 disponibles para los comandos REST.
 *
 * Declarando el contrato por lo que el componente **realmente lee**, el mismo componente
 * acepta las dos proyecciones sin adaptadores:
 *
 * - Moderación sigue pasando su `EstadoModeracion`, que satisface esta forma porque tiene
 *   estos campos y muchos más;
 * - Apoyo Técnico pasa `EstadoTecnico.remapeo`, la allowlist que el backend arma con los
 *   mismos constructores autoritativos.
 *
 * Los nombres de los campos son deliberadamente los de `EstadoModeracion`: así ninguna de
 * las dos pantallas necesita traducir nada, y una regla de remapeo sigue viviendo en un
 * solo lugar.
 *
 * ## Qué NO es
 *
 * No es una proyección nueva ni una fuente de verdad: es la descripción tipada de lo que la
 * interfaz lee. Toda la semántica del remapeo —qué se puede iniciar, confirmar o cancelar—
 * la sigue decidiendo el backend y llega en `capacidades`.
 */

import type { Capacidad, EstadoRemapeoModeracion } from '@botonera2/api-client'

/**
 * Banca elegible, tal como la muestra el selector y el resumen de confirmación.
 *
 * `dispositivo_votacion` es el identificador **lógico** (devXX): es el que viaja en el
 * comando y el que se conserva cuando cambia el fingerprint físico.
 */
export interface ConcejalRemapeoCompartido {
  dni: string
  nombre: string
  apellido: string
  banca: number
  dispositivo_votacion: string
}

/** Las tres capacidades que gobiernan los botones del panel. */
export interface CapacidadesRemapeoCompartidas {
  iniciar_remapeo: Capacidad
  confirmar_remapeo: Capacidad
  cancelar_remapeo: Capacidad
}

/** Estado mínimo autoritativo que necesita la interfaz de remapeo. */
export interface EstadoRemapeoCompartido {
  /** Operación física activa, o `null` si no hay ninguna en curso. */
  remapeo: EstadoRemapeoModeracion | null
  /** Padrón proyectado del que se elige la banca a reemplazar. */
  concejales: readonly ConcejalRemapeoCompartido[]
  /** Precondiciones evaluadas por el backend, con sus motivos de bloqueo. */
  capacidades: CapacidadesRemapeoCompartidas
}
