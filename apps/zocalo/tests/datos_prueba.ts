/**
 * Fixtures públicas del Zócalo para OBS.
 *
 * El Zócalo consume exactamente el mismo `EstadoRecinto` que la Pantalla del Recinto, así
 * que reutiliza el único constructor de estado público del monorepo en lugar de mantener
 * una copia. Si el contrato cambiara, las dos superficies lo notarían al mismo tiempo.
 */

export {
  crearApoyoTecnicoPrueba,
  crearConcejalesPublicos,
  crearEstadoRecintoPrueba,
  crearIdentidadInstitucionalPrueba,
  crearSonidosRecintoPrueba,
  crearVotacionPublicaPrueba,
  NOMBRE_INSTITUCIONAL_DE_PRUEBA,
} from '../../../packages/frontend-shared/tests/helpers/estado_recinto'
