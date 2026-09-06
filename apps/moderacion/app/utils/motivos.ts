/**
 * Punto de acceso local de Moderación a la traducción de motivos de capacidad.
 *
 * La tabla de traducciones vive ahora en `packages/frontend-shared` porque el puesto de
 * Apoyo Técnico (WP-056) comparte el componente de remapeo y necesita exactamente las
 * mismas redacciones. Duplicar el diccionario habría permitido que una corrección de
 * texto quedara aplicada en una sola pantalla.
 *
 * Este archivo se conserva como reexportación por la misma razón que `utils/tiempo.ts`:
 * los componentes y las pruebas de Moderación siguen importando `../utils/motivos` y no
 * necesitan conocer la estructura interna del paquete compartido.
 */

export { traducirMotivo, traducirMotivos, type ContextoMotivo } from '@sis-leg/frontend-shared'
