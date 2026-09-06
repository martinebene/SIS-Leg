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
 * reproducir exactamente los mismos quince eventos. Si estas reglas vivieran duplicadas,
 * una corrección posterior podría aplicarse en una sola interfaz.
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
