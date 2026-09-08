/**
 * Tipos de datos del cliente API derivados de OpenAPI y contratos propios del paquete.
 *
 * Los tipos de modelos del backend (DTOs de Moderación, Recinto, Votación, etc.)
 * se derivan directamente de components["schemas"] generados por openapi-typescript,
 * garantizando que FastAPI sea la única fuente técnica de verdad.
 */

import type { components, paths, operations } from './esquema'

// =============================================================================
// 1. Tipos de dominio derivados de OpenAPI (DTOs de FastAPI)
// =============================================================================

/** Estado global del sistema: SIN_PREPARAR | PREPARANDO | SESION_ABIERTA */
export type EstadoGlobal = components['schemas']['EstadoGlobal']

/** Proyección completa del estado para la interfaz de Moderación */
export type EstadoModeracion = components['schemas']['EstadoModeracion']

/** Proyección restrictiva de solo lectura para la Pantalla del Recinto */
export type EstadoRecinto = components['schemas']['EstadoRecinto']

/** Datos institucionales de la etapa de preparación */
export type DatosPreparacion = components['schemas']['DatosPreparacion']

/** Datos institucionales de la sesión abierta */
export type DatosSesion = components['schemas']['DatosSesion']

/** Configuración congelada del backend expuesta a Moderación */
export type ConfiguracionProyectada = components['schemas']['ConfiguracionProyectada']

/** Información de banca y concejal para la pantalla de Moderación */
export type ConcejalModeracion = components['schemas']['ConcejalModeracion']

/** Información pública de banca y concejal para el Recinto (sin DNI ni dispositivo) */
export type ConcejalPublico = components['schemas']['ConcejalPublico']

/** Estado del quórum calculado por el backend */
export type EstadoQuorum = components['schemas']['EstadoQuorum']

/** Información completa de la votación activa o reciente para Moderación */
export type VotacionModeracion = components['schemas']['VotacionModeracion']

/** Información pública restrictiva de la votación para el Recinto */
export type VotacionPublica = components['schemas']['VotacionPublica']

/** Voto individual de un concejal para Moderación */
export type VotoModeracion = components['schemas']['VotoModeracion']

/** Voto individual público posterior al cierre de votación */
export type VotoPublico = components['schemas']['VotoPublico']

/** Voto presidencial de desempate proyectado */
export type VotoPresidencialProyectado = components['schemas']['VotoPresidencialProyectado']

/** Conteos de votos computados */
export type ConteosVotosProyectados = components['schemas']['ConteosVotosProyectados']

/** Estado del uso de la palabra para Moderación (con DNI) */
export type EstadoPalabraModeracion = components['schemas']['EstadoPalabraModeracion']

/** Estado público del uso de la palabra para Recinto (sin DNI) */
export type EstadoPalabraPublico = components['schemas']['EstadoPalabraPublico']

/** Identidad de orador o solicitante en cola para Moderación */
export type PersonaPalabraModeracion = components['schemas']['PersonaPalabraModeracion']

/** Identidad de orador o solicitante en cola para Recinto */
export type PersonaPalabraPublica = components['schemas']['PersonaPalabraPublica']

/** Punto individual del Orden del Día proyectado en el estado */
export type PuntoOrdenDelDiaProyectado = components['schemas']['PuntoOrdenDelDiaProyectado']

/** Punto normalizado devuelto tras la carga del CSV del Orden del Día */
export type PuntoOrdenDelDiaRespuesta = components['schemas']['PuntoOrdenDelDiaRespuesta']

/** Respuesta de la carga del CSV del Orden del Día */
export type RespuestaOrdenDelDia = components['schemas']['CargaOrdenDelDiaRespuesta']

/** Evento reciente auditado confirmado */
export type EventoRecienteProyectado = components['schemas']['EventoRecienteProyectado']

/**
 * Lectura estructurada y ya filtrada por la frontera de secreto de un evento.
 *
 * Es el contrato que debe consumir la UI para presentar votos y palabra: el
 * campo `mensaje` sigue existiendo para los hechos sin estructura, pero nunca
 * debe interpretarse para deducir identidad, tipo ni sentido.
 */
export type HechoOperativoProyectado = components['schemas']['HechoOperativoProyectado']

/** Identidad mínima del concejal referido por un hecho operativo */
export type ConcejalHechoProyectado = components['schemas']['ConcejalHechoProyectado']

/** Evento principal sanitizado para la franja pública del Recinto */
export type EventoPublicoProyectado = components['schemas']['EventoPublicoProyectado']

/** Estado técnico del escritor institucional de auditoría */
export type EstadoAuditoriaProyectado = components['schemas']['EstadoAuditoriaProyectado']

/** Operación física activa visible exclusivamente para Moderación */
export type EstadoRemapeoModeracion = components['schemas']['EstadoRemapeoModeracion']

/** Respuesta del inicio/callback de una coordinación de remapeo */
export type EstadoRemapeoRespuesta = components['schemas']['EstadoRemapeoRespuesta']

/** Capacidad operativa individual evaluada por el backend */
export type Capacidad = components['schemas']['Capacidad']

/** Conjunto de capacidades operativas disponibles para Moderación */
export type CapacidadesModeracion = components['schemas']['CapacidadesModeracion']

/**
 * Proyección completa del estado para el puesto de Apoyo Técnico (WP-055).
 *
 * Incluye transmisión, los avisos vigentes de AMBOS destinos, la biblioteca de
 * mensajes precargados y la misma franja segura de eventos L1/L2/L3 que ve
 * Moderación (la frontera de secreto de WP-052 se aplica en el backend).
 */
export type EstadoTecnico = components['schemas']['EstadoTecnico']

/**
 * Allowlist de remapeo que viaja dentro de `EstadoTecnico` (WP-074).
 *
 * Sus tres campos se llaman igual que en `EstadoModeracion` a propósito: el
 * componente compartido de remapeo consume las dos proyecciones sin traducción.
 */
export type RemapeoTecnicoProyectado = components['schemas']['RemapeoTecnicoProyectado']

/** Banca mínima que necesita el panel de remapeo: identidad y dispositivo lógico */
export type ConcejalRemapeoProyectado = components['schemas']['ConcejalRemapeoProyectado']

/** Las tres capacidades de remapeo recortadas de las capacidades de Moderación */
export type CapacidadesRemapeoProyectadas = components['schemas']['CapacidadesRemapeoProyectadas']

/**
 * Subproyección pública mínima que permite a Apoyo Técnico sonorizar igual que
 * el Recinto sin abrir un stream propio del Recinto (WP-074).
 *
 * Contiene estrictamente los campos que compara el detector de transiciones y
 * menos información que la pantalla del salón: de la votación sólo viajan la
 * identidad y la recepción, nunca conteos ni votos individuales.
 */
export type SonorizacionRecintoProyectada = components['schemas']['SonorizacionRecintoProyectada']

/** Identidad de cola/orador reducida a la banca, única que distingue los sonidos de palabra */
export type PersonaSonorizacionProyectada = components['schemas']['PersonaSonorizacionProyectada']

/** Cola y orador reducidos a bancas para la sonorización */
export type PalabraSonorizacionProyectada = components['schemas']['PalabraSonorizacionProyectada']

/** Identidad y recepción de la votación visible, sin ningún dato de voto */
export type VotacionSonorizacionProyectada = components['schemas']['VotacionSonorizacionProyectada']

/** Presencia de una banca: lo único que separa `concejal_presente` de `concejal_ausente` */
export type BancaSonorizacionProyectada = components['schemas']['BancaSonorizacionProyectada']

/**
 * Porción técnica que reciben Moderación y Recinto dentro de su propio estado.
 *
 * Cada uno recibe la transmisión y únicamente el aviso de SU destino: la
 * separación la aplica el backend, no el frontend.
 */
export type ApoyoTecnicoProyectado = components['schemas']['ApoyoTecnicoProyectado']

/** Estado autoritativo del indicador de transmisión, con su frontera absoluta */
export type TransmisionProyectada = components['schemas']['TransmisionProyectada']

/** Aviso técnico vigente en una ranura de destino */
export type AvisoTecnicoProyectado = components['schemas']['AvisoTecnicoProyectado']

/** Mensaje precargado de la biblioteca CSV de Apoyo Técnico */
export type MensajeTecnicoProyectado = components['schemas']['MensajeTecnicoProyectado']

/** Biblioteca de mensajes precargados más su condición técnica */
export type BibliotecaMensajesProyectada = components['schemas']['BibliotecaMensajesProyectada']

/**
 * Sonido configurado para un evento de la Pantalla del Recinto (WP-065).
 *
 * `ruta` siempre es relativa a la raíz pública del Recinto y apunta a un asset
 * versionado; el backend rechaza cualquier otra forma antes de proyectarla.
 */
export type SonidoRecintoProyectado = components['schemas']['SonidoRecintoProyectado']

/**
 * Configuración de audio completa del Recinto más su condición técnica.
 *
 * Viaja en los tres estados globales, también en `SIN_PREPARAR`.
 */
export type SonidosRecintoProyectados = components['schemas']['SonidosRecintoProyectados']

/**
 * Nombre del cuerpo legislativo que la Pantalla del Recinto muestra (WP-084).
 *
 * Es el contrato mínimo: sólo el texto configurado en `[institucion]` de
 * `system.toml`. Viaja en los tres estados globales, también en `SIN_PREPARAR`,
 * porque la cabecera pública existe desde que la pantalla se enciende.
 */
export type IdentidadInstitucionalProyectada =
  components['schemas']['IdentidadInstitucionalProyectada']

/** Estado del indicador de transmisión: APAGADO | CUENTA_REGRESIVA | EN_VIVO */
export type EstadoTransmision = components['schemas']['EstadoTransmision']

/** Destino de un aviso o mensaje técnico: MODERACION | RECINTO | AMBOS */
export type DestinoAvisoTecnico = components['schemas']['DestinoAvisoTecnico']

/** Estado de recepción de votos en una votación: EN_CURSO | CERRADA */
export type EstadoVotacion = components['schemas']['EstadoVotacion']

/** Regla de mayoría: SIMPLE | ESPECIAL */
export type TipoMayoria = components['schemas']['TipoMayoria']

/** Base o denominador de mayoría: VOTOS_COMPUTABLES | PRESENTES | CUERPO */
export type BaseMayoria = components['schemas']['BaseMayoria']

/** Sentido de voto ordinario: POSITIVO | ABSTENCION | NEGATIVO */
export type ValorVotoOrdinario = components['schemas']['ValorVotoOrdinario']

/** Acción de palabra producida por tecla 7 */
export type AccionPalabra = components['schemas']['AccionPalabra']

/** Respuesta de salud del backend */
export type RespuestaSalud = components['schemas']['RespuestaSalud']

/** Respuesta tras abrir una votación */
export type RespuestaVotacion = components['schemas']['RespuestaVotacion']

/**
 * Desenlace de la copia externa opcional del conjunto cerrado (WP-085).
 *
 * `OMITIDA` significa que la instalación no configuró `paths.logs_copy_dir` y por lo
 * tanto no hubo ningún intento de acceso externo: no corresponde avisar nada.
 */
export type EstadoCopiaExterna = components['schemas']['EstadoCopiaExterna']

/**
 * Cuerpo devuelto por el cierre normal de sesión (WP-085).
 *
 * Recibirlo significa siempre que la sesión cerró de forma durable: describe qué pasó
 * *después* del cierre con el informe de acta y con la copia externa, nunca si el cierre
 * en sí tuvo éxito.
 */
export type RespuestaCierreSesion = components['schemas']['RespuestaCierreSesion']

/** Cuerpo de error estructurado devuelto por el backend */
export type ErrorRespuesta = components['schemas']['ErrorRespuesta']

// Solicitudes / Bodies de comandos REST
export type SolicitudActualizarPreparacion = components['schemas']['SolicitudActualizarPreparacion']
export type SolicitudActualizarSesion = components['schemas']['SolicitudActualizarSesion']
export type SolicitudVotacionSimple = components['schemas']['SolicitudVotacionSimple']
export type SolicitudVotacionEspecial = components['schemas']['SolicitudVotacionEspecial']
export type SolicitudAperturaVotacion = SolicitudVotacionSimple | SolicitudVotacionEspecial
export type SolicitudFinalizarVotacion = components['schemas']['SolicitudFinalizarVotacion']
export type SolicitudDesempate = components['schemas']['SolicitudDesempate']
export type SolicitudIniciarRemapeo = components['schemas']['SolicitudIniciarRemapeo']
export type SolicitudConfirmarRemapeo = components['schemas']['SolicitudConfirmarRemapeo']
export type SolicitudIniciarTransmision = components['schemas']['SolicitudIniciarTransmision']
export type SolicitudPublicarAviso = components['schemas']['SolicitudPublicarAviso']
export type SolicitudMensajeTecnico = components['schemas']['SolicitudMensajeTecnico']
export type SolicitudTecla = components['schemas']['SolicitudTecla']
export type RespuestaTecla = components['schemas']['RespuestaTecla']

// =============================================================================
// 2. Tipos y contratos del cliente TypeScript (no-DTOs de backend)
// =============================================================================

/**
 * Función temporizadora inyectable para esperas asíncronas con soporte de cancelación.
 */
export type Temporizador = (milisegundos: number, signal?: AbortSignal) => Promise<void>

/**
 * Parámetros de configuración de la estrategia de reconexión con retroceso exponencial.
 */
export interface ConfiguracionBackoff {
  /** Tiempo inicial de espera en milisegundos (por defecto: 500 ms) */
  esperaInicialMs?: number
  /** Tiempo máximo de espera en milisegundos (por defecto: 5000 ms) */
  esperaMaximaMs?: number
  /** Factor de multiplicación para cada reintento consecutivo (por defecto: 1.5) */
  factorMultiplicador?: number
  /** Función temporizadora inyectable para pruebas unitarias */
  temporizador?: Temporizador
}

/**
 * Interfaz mínima requerida de un EventSource nativo o simulado.
 */
export interface InterfazEventSource {
  onopen: ((evento: Event) => void) | null
  onerror: ((evento: Event) => void) | null
  onmessage: ((evento: MessageEvent) => void) | null
  addEventListener(tipo: string, listener: (evento: MessageEvent) => void): void
  removeEventListener(tipo: string, listener: (evento: MessageEvent) => void): void
  close(): void
}

/**
 * Fábrica inyectable para crear instancias de EventSource.
 */
export type FabricaEventSource = (url: string) => InterfazEventSource

/**
 * Configuración general para instanciar clientes de Moderación o Recinto.
 */
export interface ConfiguracionCliente {
  /**
   * URL base del backend (por ejemplo: "http://localhost:8000" o "/").
   * Si se omite, se utiliza una cadena vacía (mismo origen).
   */
  baseUrl?: string

  /**
   * Implementación de fetch inyectable (por defecto: globalThis.fetch).
   */
  fetch?: typeof fetch

  /**
   * Fábrica inyectable para crear conexiones EventSource (por defecto: () => new EventSource(url)).
   */
  fabricaEventSource?: FabricaEventSource

  /**
   * Configuración de la estrategia de retroceso (backoff) para reconexiones SSE.
   */
  backoff?: ConfiguracionBackoff
}

/**
 * Opciones para suscribirse al flujo reactivo de sincronización de estado.
 */
export interface OpcionesSuscripcion<T> {
  /**
   * Callback invocado cada vez que se adopta un nuevo estado completo válido
   * (tanto por snapshot inicial/recuperación como por eventos SSE recibidos).
   */
  alEstado: (estado: T) => void

  /**
   * Callback opcional invocado ante un error de transporte, HTTP o protocolo.
   * La recepción de un error no detiene el ciclo de reconexión automática.
   */
  alError?: (error: unknown) => void

  /**
   * Callback opcional invocado cuando cambia el estado de conexión del stream SSE
   * (true al abrirse el stream, false al perderse o cerrarse).
   */
  alCambiarConexion?: (conectado: boolean) => void
}

/**
 * Representa una suscripción activa a un stream de sincronización de estado.
 */
export interface Suscripcion {
  /**
   * Detiene de forma determinista e idempotente la sincronización,
   * cancelando timers de backoff, abortando requests de recuperación pendientes
   * y cerrando el EventSource activo sin emitir callbacks posteriores.
   */
  cancelar(): void

  /**
   * Indica si la suscripción continúa activa.
   */
  readonly activa: boolean
}

// Re-exportamos los tipos OpenAPI raíz para consumidores avanzados
export type { paths, components, operations }
