/**
 * Fixtures públicas de la Pantalla del Recinto.
 *
 * Desde WP-071 el contenido real vive en `packages/frontend-shared/tests/helpers/`, porque
 * el puesto de Apoyo Técnico sonoriza el mismo `EstadoRecinto` y sus pruebas necesitan las
 * mismas fixtures. Este archivo se conserva como reexportación para que las suites del
 * Recinto sigan importando `./datos_prueba` sin cambios y para que exista un único
 * constructor de estado público en todo el monorepo.
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
