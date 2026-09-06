/**
 * Frontera reactiva de sincronización del puesto de Apoyo Técnico (WP-056, ampliada por
 * WP-071 y consolidada por WP-074).
 *
 * ## Una sola suscripción, y por qué importa tanto
 *
 * Este puesto observa **una** proyección autoritativa: `EstadoTecnico`
 * (`/api/v1/estado/tecnico` + `/api/v1/estado/tecnico/stream`). De ahí salen la
 * transmisión, los avisos vigentes de ambos destinos, la biblioteca de mensajes
 * precargados, la franja segura de eventos L1/L2/L3, la allowlist de remapeo y la
 * subproyección con la que se sonoriza igual que el Recinto.
 *
 * Hasta WP-074 eran **tres** suscripciones: además de la técnica, una al `EstadoModeracion`
 * para el remapeo y otra al `EstadoRecinto` para el sonido. La razón de entonces era
 * razonable —no duplicar en el backend una verdad que ya existía— pero tenía un costo que
 * sólo se hizo visible con las cuatro superficies abiertas a la vez.
 *
 * El navegador limita las conexiones simultáneas por origen sobre HTTP/1.1 (típicamente
 * seis en Chromium). Un stream SSE es una conexión que no termina nunca. Con Moderación,
 * Recinto y Simulador aportando una cada uno y este puesto aportando tres, se llegaba
 * exactamente al límite: la séptima petición —cualquier comando REST, «Preparar sala» el
 * primero— quedaba encolada en el navegador sin llegar jamás al backend. El operador lo
 * vivía como una caída del servidor, aunque el servicio estuviera perfectamente sano.
 *
 * La corrección no es operativa («cerrá una pestaña») sino de contrato: el backend ahora
 * transporta dentro de `EstadoTecnico` las dos porciones que faltaban, cada una recortada
 * por su propia allowlist. Esta pantalla consume esas porciones y ya no abre streams
 * ajenos, así que el escenario completo usa cuatro conexiones persistentes en lugar de
 * seis y sobran conexiones para los comandos.
 *
 * ## Qué sigue igual
 *
 * - No hay polling: snapshot REST inicial, SSE y reconexión con retroceso, todo resuelto
 *   dentro de `@botonera2/api-client`. La cuenta regresiva la deriva localmente
 *   `usePresentacionTecnica`.
 * - El remapeo sigue siendo el mismo componente compartido, con las mismas capacidades y
 *   los mismos endpoints REST (`/api/v1/remapeos`). Lo único que cambió es que sus
 *   comandos viajan por un cliente propio de remapeo, que no abre ninguna conexión
 *   persistente.
 * - El secreto de voto sigue garantizado en el servidor. Esta pantalla nunca representa
 *   votos ni resultados, y la porción que usa para sonorizar contiene **menos** información
 *   que la pantalla pública del salón: de la votación sólo su identidad y su recepción.
 */

import {
  computed,
  onMounted,
  onScopeDispose,
  ref,
  type ComputedRef,
  type Ref,
  shallowRef,
} from 'vue'
import {
  crearClienteApoyoTecnico,
  crearClienteRemapeo,
  type ClienteApoyoTecnico,
  type ClienteRemapeo,
  type ConfiguracionCliente,
  type EstadoTecnico,
  type Suscripcion,
} from '@botonera2/api-client'

/**
 * Estados visibles del canal de sincronización, con el mismo vocabulario que usan
 * Moderación y Recinto para que el operador lea siempre lo mismo.
 */
export type EstadoConexionTecnico = 'INICIAL' | 'CONECTADO' | 'RECONECTANDO' | 'DESCONECTADO'

/** Superficie reactiva que consume la SPA técnica. */
export interface SincronizacionTecnica {
  /** Último `EstadoTecnico` confirmado, o `null` antes del primer snapshot. */
  estado: Ref<EstadoTecnico | null>
  /** Estado del único stream de esta pantalla. */
  estadoConexion: Ref<EstadoConexionTecnico>
  /** Último error de transporte observado. */
  ultimoError: Ref<unknown | null>
  /** `true` sólo con el stream plenamente abierto. */
  conectado: ComputedRef<boolean>
  /** `true` cuando se conserva un estado previo pero la conexión se interrumpió. */
  desactualizado: ComputedRef<boolean>
  /** Revisión monotónica del último `EstadoTecnico` adoptado. */
  revision: ComputedRef<number | null>
  /** Cliente de comandos del plano técnico. */
  cliente: ClienteApoyoTecnico
  /**
   * Cliente de los tres comandos de remapeo.
   *
   * Es sólo REST: no tiene `suscribirEstado` ni abre ningún `EventSource`, así que no
   * consume ninguna de las conexiones persistentes que WP-074 vino a liberar.
   */
  clienteRemapeo: ClienteRemapeo
  /** Abre la suscripción. Es idempotente. */
  iniciar: () => void
  /** Cierra la suscripción sin borrar el último estado confirmado. */
  cancelar: () => void
}

/** Opciones de construcción; los clientes inyectables mantienen las pruebas deterministas. */
export interface OpcionesSincronizacionTecnica {
  cliente?: ClienteApoyoTecnico
  clienteRemapeo?: ClienteRemapeo
  configuracionCliente?: ConfiguracionCliente
  autoIniciar?: boolean
}

/**
 * Crea una sincronización técnica aislada, testeable fuera del runtime de Nuxt.
 *
 * El último snapshot nunca se borra por un error de red: se conserva y se marca como
 * potencialmente desactualizado, igual que en las otras dos pantallas. Cuando llega otra
 * baseline —incluso con revisión menor tras reiniciar FastAPI— se reemplaza por completo.
 */
export function crearSincronizacionTecnica(
  opciones: OpcionesSincronizacionTecnica = {},
): SincronizacionTecnica {
  const configuracion = opciones.configuracionCliente ?? {}
  const cliente = opciones.cliente ?? crearClienteApoyoTecnico(configuracion)
  const clienteRemapeo = opciones.clienteRemapeo ?? crearClienteRemapeo(configuracion)

  // `shallowRef` alcanza porque cada snapshot se reemplaza entero y nunca se muta por
  // dentro: evita que Vue recorra en profundidad un objeto grande en cada revisión.
  const estado = shallowRef<EstadoTecnico | null>(null)
  const estadoConexion = ref<EstadoConexionTecnico>('INICIAL')
  const ultimoError = ref<unknown | null>(null)

  let suscripcionTecnica: Suscripcion | null = null

  const conectado = computed(() => estadoConexion.value === 'CONECTADO')
  const desactualizado = computed(
    () => estadoConexion.value === 'RECONECTANDO' && estado.value !== null,
  )
  const revision = computed(() => estado.value?.revision ?? null)

  /**
   * El indicador de conexión refleja el único canal de la pantalla, que es el que habilita
   * sus comandos. Se distingue "sin conexión" de "reconectando" según haya o no un estado
   * previo que el operador siga viendo.
   */
  function marcarDesconexion(): void {
    estadoConexion.value = estado.value === null ? 'DESCONECTADO' : 'RECONECTANDO'
  }

  function iniciar(): void {
    if (suscripcionTecnica?.activa === true) return
    suscripcionTecnica = cliente.suscribirEstado({
      alEstado: (nuevoEstado) => {
        estado.value = nuevoEstado
      },
      alCambiarConexion: (estaConectado) => {
        if (estaConectado) {
          estadoConexion.value = 'CONECTADO'
          ultimoError.value = null
        } else {
          marcarDesconexion()
        }
      },
      alError: (error) => {
        ultimoError.value = error
        marcarDesconexion()
      },
    })
  }

  function cancelar(): void {
    suscripcionTecnica?.cancelar()
    suscripcionTecnica = null
    estadoConexion.value = 'DESCONECTADO'
  }

  if (opciones.autoIniciar) iniciar()

  return {
    estado,
    estadoConexion,
    ultimoError,
    conectado,
    desactualizado,
    revision,
    cliente,
    clienteRemapeo,
    iniciar,
    cancelar,
  }
}

/**
 * Integra la sincronización con el ciclo de vida del shell técnico.
 *
 * `onScopeDispose` también cubre un desmontaje de prueba, de modo que ninguna suite deje
 * conexiones SSE abiertas contra el backend.
 */
export function useEstadoTecnico(
  clientes: Pick<OpcionesSincronizacionTecnica, 'cliente' | 'clienteRemapeo'> = {},
): SincronizacionTecnica {
  let baseUrl = ''
  if (!clientes.cliente || !clientes.clienteRemapeo) {
    baseUrl = useRuntimeConfig().public.apiBaseUrl
  }

  const sincronizacion = crearSincronizacionTecnica({
    ...clientes,
    configuracionCliente: { baseUrl },
  })

  onMounted(sincronizacion.iniciar)
  onScopeDispose(sincronizacion.cancelar)
  return sincronizacion
}
