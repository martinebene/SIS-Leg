import { resolverUrlImagenConcejal } from '@sis-leg/api-client'

/**
 * Resuelve un asset versionado de la propia SPA contra su base URL pública.
 *
 * Desde WP-098 esta función ya NO resuelve fotografías de concejales: ésas
 * viven en la configuración local de la instalación y las publica el backend.
 * Sigue siendo la forma correcta de resolver lo que sí viaja dentro del build,
 * como la marca institucional bajo `public/assets/marca/`.
 */
export function resolverRutaAsset(ruta: string): string {
  if (!ruta) return ''
  if (/^(?:https?:|data:)/.test(ruta)) return ruta

  let baseUrl = '/'
  try {
    baseUrl = useRuntimeConfig().app.baseURL || '/'
  } catch {
    // Los tests de componentes no levantan una aplicación Nuxt completa.
  }

  const baseNormalizada = baseUrl.endsWith('/') ? baseUrl : `${baseUrl}/`
  return `${baseNormalizada}${ruta.replace(/^\//, '')}`
}

/**
 * Resuelve la fotografía de banca contra la fuente única de configuración (WP-098).
 *
 * La URL se arma contra la base de la API y no contra el prefijo público de la
 * SPA, porque la foto es un recurso de la configuración de la instalación que
 * publica el backend, no un archivo del build. En producción esa base es cadena
 * vacía: Pantalla del Recinto y API comparten origen detrás de Nginx.
 *
 * La validación y la construcción de la URL viven en `@sis-leg/api-client` para
 * que esta pantalla y Moderación resuelvan exactamente el mismo archivo.
 *
 * @param rutaImagen Valor de `ruta_imagen` recibido en el snapshot del backend.
 * @returns URL utilizable en `src`, o cadena vacía si la ruta es inválida.
 */
export function resolverUrlFotoConcejal(rutaImagen: string): string {
  let baseApi = ''
  try {
    baseApi = useRuntimeConfig().public.apiBaseUrl || ''
  } catch {
    // Fuera del contexto de Nuxt rige el mismo origen, igual que en producción.
  }

  return resolverUrlImagenConcejal(rutaImagen, baseApi)
}
