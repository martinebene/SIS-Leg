/**
 * Ubicación y rótulos del manual de usuario de SIS-Leg (WP-067).
 *
 * El manual es un único documento HTML estático que se publica bajo el mismo origen que
 * las aplicaciones, en `/manual/`. No pertenece a ninguna SPA: Nginx lo sirve desde
 * `web/manual/` dentro de la release, y los dos entornos integrados de desarrollo lo
 * publican en esa misma ruta. Por eso la dirección se escribe una sola vez acá, y no
 * dentro de cada cabecera: si alguna vez cambiara, cambiaría en un solo lugar y las dos
 * pantallas seguirían abriendo exactamente el mismo documento.
 *
 * La ruta es **absoluta a propósito**. Cada aplicación se sirve bajo su propio prefijo
 * (`/moderacion/`, `/tecnico/`), así que una ruta relativa se resolvería dentro de ese
 * prefijo y buscaría un manual que no existe ahí.
 */

/** Dirección de mismo origen donde se publica el manual de usuario. */
export const RUTA_MANUAL = '/manual/'

/**
 * Texto accesible del acceso de ayuda.
 *
 * Se usa a la vez como `aria-label` —lo que anuncia un lector de pantalla— y como `title`
 * —lo que ve quien deja el cursor encima—. Menciona explícitamente que se abre en una
 * pestaña nueva, porque abrir una ventana sin avisar desorienta a quien no ve la pantalla.
 */
export const ROTULO_ACCESO_MANUAL = 'Abrir el manual de usuario en una pestaña nueva'
