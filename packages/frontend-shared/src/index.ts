/**
 * Punto de entrada del código genuinamente común a los frontends de SIS-Leg.
 *
 * Solo se publica aquí lo que necesita ser idéntico en más de una interfaz. Hoy
 * incluye la semántica visual de una banca (WP-045), el cálculo temporal
 * backend-backend de la duración de sesión (WP-047) y, desde WP-056, la traducción
 * de motivos de capacidad, la presentación de la franja segura de eventos y el ajuste
 * tipográfico de los avisos de Apoyo Técnico. Desde WP-063 también incluye el formato
 * visual del factor de mayoría especial. Desde WP-067 se agrega la ubicación del manual
 * de usuario, que las cabeceras de Moderación y de Apoyo Técnico deben compartir. Desde
 * WP-071 se agrega la sonorización completa del recinto —transiciones, motor de audio y
 * frontera reactiva—, porque la Pantalla del Recinto y el puesto de Apoyo Técnico deben
 * reproducir exactamente los mismos quince eventos. Desde WP-099 se agrega la proyección
 * pública completa del Recinto —suscripción autoritativa, reloj de presentación de la
 * votación y redacción de los renglones `Votación`, `Tema` y `Estado`—, porque el Zócalo
 * para OBS debe mostrar exactamente el mismo contenido que la Pantalla del Recinto sin
 * mantener un modelo de estado propio. Si estas reglas vivieran duplicadas, una corrección
 * posterior podría aplicarse en una sola interfaz.
 *
 * Los componentes Vue compartidos no se exportan por este índice: se importan por su
 * subruta (`@sis-leg/frontend-shared/componentes/…`) para que cada aplicación cargue
 * únicamente el que usa y para que este archivo no arrastre plantillas ni estilos.
 *
 * Sigue vigente DT-024: acá va sólo código realmente común, no una librería de UI
 * construida por anticipado.
 */
export {
  calcularPresentacionBanca,
  estilosBanca,
  PALETA_BANCAS,
  resultadoIndividualVisible,
  type ColoresBanca,
  type EntradaEstadoBanca,
  type EntradaVisibilidadResultadoBanca,
  type EstadoPrincipalBanca,
  type FamiliaCromaticaBanca,
  type PresentacionBanca,
} from './estado_banca'

export { calcularDuracionEnSnapshot, convertirMarcaBackend, formatearDuracion } from './tiempo'

export { traducirMotivo, traducirMotivos, type ContextoMotivo } from './motivos'

export {
  filtrarEventosPorNivel,
  hayActividadNueva,
  NIVELES_POR_FILTRO,
  seqMaximoEventos,
  type FiltroNivelEventos,
} from './eventos_seguros'

export {
  ajustarTamanoAviso,
  lineasVisiblesAviso,
  type OpcionesAjusteAviso,
  type ResultadoAjusteAviso,
} from './aviso_adaptable'

export {
  usePresentacionTecnica,
  type EntradaPresentacionTecnica,
  type PresentacionTecnica,
} from './presentacion_tecnica'

export { extraerMensajeError } from './errores'

export { formatearFactorMayoria } from './factor_mayoria'

export { RUTA_MANUAL, ROTULO_ACCESO_MANUAL } from './manual'

/*
  Contrato mínimo del remapeo compartido (WP-074).

  Se exporta el tipo, y no una implementación, porque el remapeo no tiene lógica común más
  allá del componente: lo que las dos pantallas necesitan compartir es la forma del estado
  que ese componente lee.
*/
export type {
  CapacidadesRemapeoCompartidas,
  ConcejalRemapeoCompartido,
  EstadoRemapeoCompartido,
} from './contrato_remapeo'

/*
  Sonorización del recinto (WP-066, compartida por WP-071).

  Se exportan las tres capas por separado —qué ocurrió, cómo suena y cuándo suena— porque
  cada pantalla necesita cablearlas con sus propios insumos, y las pruebas de paridad
  necesitan poder ejercitar la capa pura sin construir un motor de audio.
*/
export {
  detectarTransicionesSonoras,
  EVENTOS_SONOROS_RECINTO,
  type EventoSonoroRecinto,
  type InstantaneaSonora,
} from './transiciones_sonoras'

export {
  crearMotorSonidos,
  type FabricaAudioRecinto,
  type InstanciaAudioRecinto,
  type MotorSonidosRecinto,
  type OpcionesMotorSonidos,
} from './motor_sonidos'

export {
  useSonidosRecinto,
  type EstadoConexionSuperficie,
  type OpcionesSonidosRecinto,
  type SonidosRecinto,
} from './sonidos_recinto'

/*
  Proyección pública del Recinto compartida con el Zócalo para OBS (WP-099).

  Las tres piezas responden a preguntas distintas y por eso se exportan por separado:

  - `sincronizacion_recinto` resuelve *de dónde* sale el estado. Es el único vínculo con el
    backend autoritativo, así que las dos superficies públicas no pueden divergir en
    transporte, reconexión ni manejo de baseline.
  - `presentacion_votacion` resuelve *qué* votación se muestra y hasta cuándo. Contiene el
    reloj presentacional que oculta un resultado vencido sin recalcular nada.
  - `presentacion_votacion_publica` resuelve *cómo se lee* esa votación: los textos exactos
    de los renglones `Votación`, `Tema` y `Estado`.

  Ninguna de las tres implementa reglas de negocio: todas traducen el DTO que ya decidió el
  backend.
*/
export {
  crearSincronizacionRecinto,
  usarSincronizacionRecintoEnComponente,
  type EstadoConexionRecinto,
  type OpcionesSincronizacionRecinto,
  type SincronizacionRecinto,
} from './sincronizacion_recinto'

export { usePresentacionVotacion, type PresentacionVotacion } from './presentacion_votacion'

export {
  claseEstadoVotacion,
  conteosVisiblesVotacion,
  describirEstadoVotacion,
  describirMayoriaVotacion,
  describirTemaVotacion,
  etiquetaSentidoVoto,
  resumirVotacion,
  usePresentacionVotacionPublica,
  votacionEnCurso,
  ETIQUETAS_BASE_MAYORIA,
  ETIQUETAS_RESULTADO_VOTACION,
  TEXTO_SIN_DATO,
  type ConteosVotacionPublica,
  type PresentacionVotacionPublica,
  type VotoPresidencialPublico,
} from './presentacion_votacion_publica'
