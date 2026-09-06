/**
 * @botonera2/api-client
 *
 * Paquete TypeScript compartido para el consumo de la API REST y streams SSE de SISLeg.
 * Deriva sus tipos de OpenAPI generado por FastAPI, normaliza errores, separa las superficies
 * de Moderación y Recinto, y administra el ciclo de vida de sincronización y reconexión.
 */

// Clientes y fábricas públicas
export { ClienteModeracion, crearClienteModeracion } from './moderacion'
export { ClienteRecinto, crearClienteRecinto } from './recinto'
export { ClienteApoyoTecnico, crearClienteApoyoTecnico } from './apoyo_tecnico'
export { ClienteRemapeoDispositivos, crearClienteRemapeo } from './remapeo'
export { ClienteSimulador, crearClienteSimulador } from './simulador'
export { SincronizadorEstado, iniciarSincronizacionEstado } from './sincronizador'
export { EstrategiaBackoff, temporizadorPredeterminado } from './backoff'
export { crearFabricaEventSourcePredeterminada } from './event_source'

// Errores discriminados
// Contratos mínimos compartidos entre superficies (WP-074)
export type { ClienteRemapeo, PersistenciaRemapeo } from './remapeo'

export {
  ErrorApi,
  ErrorHttp,
  ErrorTransporte,
  ErrorProtocolo,
  ErrorCancelacion,
  normalizarError,
  type TipoErrorApi,
} from './errores'

// Tipos de dominio y configuración
export type {
  // DTOs derivados de OpenAPI
  EstadoGlobal,
  EstadoModeracion,
  EstadoRecinto,
  DatosPreparacion,
  DatosSesion,
  ConfiguracionProyectada,
  ConcejalModeracion,
  ConcejalPublico,
  EstadoQuorum,
  VotacionModeracion,
  VotacionPublica,
  VotoModeracion,
  VotoPublico,
  VotoPresidencialProyectado,
  ConteosVotosProyectados,
  EstadoPalabraModeracion,
  EstadoPalabraPublico,
  PersonaPalabraModeracion,
  PersonaPalabraPublica,
  PuntoOrdenDelDiaProyectado,
  PuntoOrdenDelDiaRespuesta,
  RespuestaOrdenDelDia,
  EventoRecienteProyectado,
  HechoOperativoProyectado,
  ConcejalHechoProyectado,
  EventoPublicoProyectado,
  EstadoAuditoriaProyectado,
  EstadoRemapeoModeracion,
  EstadoRemapeoRespuesta,
  EstadoTecnico,
  RemapeoTecnicoProyectado,
  ConcejalRemapeoProyectado,
  CapacidadesRemapeoProyectadas,
  SonorizacionRecintoProyectada,
  PersonaSonorizacionProyectada,
  PalabraSonorizacionProyectada,
  VotacionSonorizacionProyectada,
  BancaSonorizacionProyectada,
  ApoyoTecnicoProyectado,
  TransmisionProyectada,
  AvisoTecnicoProyectado,
  MensajeTecnicoProyectado,
  BibliotecaMensajesProyectada,
  SonidoRecintoProyectado,
  SonidosRecintoProyectados,
  EstadoTransmision,
  DestinoAvisoTecnico,
  Capacidad,
  CapacidadesModeracion,
  EstadoVotacion,
  TipoMayoria,
  BaseMayoria,
  ValorVotoOrdinario,
  AccionPalabra,
  RespuestaSalud,
  RespuestaVotacion,
  ErrorRespuesta,
  // Solicitudes / Bodies
  SolicitudActualizarPreparacion,
  SolicitudActualizarSesion,
  SolicitudVotacionSimple,
  SolicitudVotacionEspecial,
  SolicitudAperturaVotacion,
  SolicitudFinalizarVotacion,
  SolicitudDesempate,
  SolicitudIniciarRemapeo,
  SolicitudConfirmarRemapeo,
  SolicitudIniciarTransmision,
  SolicitudPublicarAviso,
  SolicitudMensajeTecnico,
  SolicitudTecla,
  RespuestaTecla,
  // Tipos de cliente y ciclo de vida
  Temporizador,
  ConfiguracionBackoff,
  InterfazEventSource,
  FabricaEventSource,
  ConfiguracionCliente,
  OpcionesSuscripcion,
  Suscripcion,
  // Tipos raíz de OpenAPI
  paths,
  components,
  operations,
} from './tipos'
