/**
 * Utilidades para resolución de rutas de assets y recursos estáticos en Moderación.
 *
 * En arquitecturas SPA y aplicaciones web corporativas, la aplicación puede estar
 * desplegada en la raíz de un dominio (ej: https://votacion.concejo.gob.ar/) o bajo
 * un prefijo de ruta (ej: https://servidor/moderacion/).
 *
 * Esta función normaliza las rutas de los assets versionados de la propia aplicación
 * anteponiendo el baseURL configurado por Nuxt, sin depender de convenciones implícitas
 * ni de URLs fijas.
 */

import { resolverUrlImagenConcejal } from '@sis-leg/api-client'

/**
 * Resuelve la ruta pública accesible de un asset institucional respetando el baseURL configurado.
 *
 * Desde WP-098 esta función ya NO resuelve fotografías de concejales: ésas viven
 * en la configuración local y las publica el backend. Sigue siendo la forma
 * correcta de resolver los assets que sí viajan dentro del build, como la marca
 * institucional bajo `public/assets/marca/`.
 *
 * @param ruta Ruta interna del asset versionado (ej: "assets/marca/sisleg-logo.png")
 * @returns Ruta final utilizable en atributos src de imágenes HTML
 */
export function resolverRutaAsset(ruta: string): string {
  if (!ruta) {
    return ''
  }

  // Si la ruta ya es absoluta o un esquema URI (http, https, data), se retorna intacta
  if (ruta.startsWith('http://') || ruta.startsWith('https://') || ruta.startsWith('data:')) {
    return ruta
  }

  let baseUrl = '/'
  try {
    if (typeof useRuntimeConfig === 'function') {
      const config = useRuntimeConfig()
      baseUrl = (config.app?.baseURL as string) || '/'
    }
  } catch {
    // Si se ejecuta fuera del contexto de Nuxt (ej: pruebas unitarias aisladas), usamos "/"
    baseUrl = '/'
  }

  // Normalización segura: aseguramos que la base termine en "/" y la ruta no comience con "/"
  const baseNormalizada = baseUrl.endsWith('/') ? baseUrl : `${baseUrl}/`
  const rutaNormalizada = ruta.startsWith('/') ? ruta.slice(1) : ruta

  return `${baseNormalizada}${rutaNormalizada}`
}

/**
 * Resuelve la fotografía de banca contra la fuente única de configuración (WP-098).
 *
 * A diferencia de `resolverRutaAsset`, esta función NO resuelve contra el
 * prefijo público de la SPA. Desde WP-098 las fotos de los concejales ya no
 * viajan dentro del build: viven en `config/assets/bancas/` de la instalación y
 * las publica el backend. Por eso la URL se arma contra la base de la API, que
 * es cadena vacía en producción porque frontend y API comparten origen.
 *
 * La validación y la construcción de la URL viven en `@sis-leg/api-client`, de
 * modo que Moderación y la Pantalla del Recinto no puedan divergir. Acá sólo se
 * resuelve de dónde sale la URL base.
 *
 * @param rutaImagen Valor de `ruta_imagen` recibido en el snapshot del backend.
 * @returns URL utilizable en `src`, o cadena vacía si la ruta es inválida.
 */
export function resolverUrlFotoConcejal(rutaImagen: string): string {
  let baseApi = ''
  try {
    if (typeof useRuntimeConfig === 'function') {
      const config = useRuntimeConfig()
      baseApi = (config.public?.apiBaseUrl as string) ?? ''
    }
  } catch {
    // Fuera del contexto de Nuxt (pruebas unitarias aisladas) rige el mismo
    // origen, exactamente igual que en producción.
    baseApi = ''
  }

  return resolverUrlImagenConcejal(rutaImagen, baseApi)
}
