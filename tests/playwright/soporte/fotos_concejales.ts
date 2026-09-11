/**
 * Fotografías de banca para los recorridos E2E de componentes (WP-098).
 *
 * ¿Por qué hace falta esto?
 * -------------------------
 *
 * Estos recorridos corren contra los servidores de desarrollo de Nuxt con un
 * backend simulado dentro de la página. Hasta WP-097 la foto era un archivo del
 * propio build (`public/assets/bancas/`) y el servidor de desarrollo la servía
 * sin que nadie hiciera nada.
 *
 * Desde WP-098 la foto es un recurso de la configuración local que publica el
 * backend en `/api/v1/recursos/imagenes-concejales/<archivo>`. Como en estos
 * recorridos no hay backend real, hay que responder ese pedido igual que lo
 * haría el backend: devolviendo el archivo de la **plantilla versionada**
 * `config/assets.example/bancas/`, que es exactamente la que un clon nuevo
 * materializa en su configuración local.
 *
 * No es un atajo ni un mock de comodidad: reproduce el contrato real. Las
 * pruebas que comprueban que el bitmap se dibuja completo (`naturalWidth > 0`,
 * `object-fit: contain`) siguen midiendo el mismo archivo de siempre.
 *
 * El E2E integrado (`tests/playwright-integrado/`) NO usa este helper: ahí hay
 * un backend real sirviendo la configuración local de verdad.
 */

import { existsSync, readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import type { Page } from '@playwright/test'

/** Patrón de la ruta pública que publica el backend, con cualquier prefijo. */
const PATRON_RUTA_FOTOS = '**/api/v1/recursos/imagenes-concejales/*'

/**
 * Ubica la raíz del monorepo subiendo hasta encontrar `pnpm-workspace.yaml`.
 *
 * Es la misma estrategia que usa `assets_bancas_wp058.test.ts`: funciona igual
 * si el runner se lanza desde la raíz o desde un subdirectorio.
 */
function ubicarRaizMonorepo(): string {
  let directorio = resolve(__dirname)
  while (!existsSync(join(directorio, 'pnpm-workspace.yaml'))) {
    const padre = dirname(directorio)
    if (padre === directorio) throw new Error('No se encontró la raíz del monorepo')
    directorio = padre
  }
  return directorio
}

const DIRECTORIO_PLANTILLA = join(ubicarRaizMonorepo(), 'config', 'assets.example', 'bancas')

/**
 * Responde los pedidos de fotografía con la plantilla versionada.
 *
 * Un archivo que no existe en la plantilla se responde con 404, igual que haría
 * el backend real: así los recorridos que ejercitan el fallback de iniciales
 * siguen viendo exactamente el mismo comportamiento.
 *
 * @param page Página de Playwright sobre la que instalar la intercepción.
 */
export async function instalarFotosConcejales(page: Page): Promise<void> {
  await page.route(PATRON_RUTA_FOTOS, async (ruta) => {
    const nombreArchivo = decodeURIComponent(
      new URL(ruta.request().url()).pathname.split('/').pop() ?? '',
    )
    const rutaArchivo = join(DIRECTORIO_PLANTILLA, nombreArchivo)

    // La comprobación de contención repite la del backend: el helper nunca
    // puede terminar leyendo un archivo fuera de la plantilla.
    if (!rutaArchivo.startsWith(DIRECTORIO_PLANTILLA) || !existsSync(rutaArchivo)) {
      await ruta.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({
          codigo: 'IMAGEN_CONCEJAL_NO_DISPONIBLE',
          mensaje: 'La fotografía solicitada no está disponible en la configuración.',
        }),
      })
      return
    }

    await ruta.fulfill({
      status: 200,
      contentType: 'image/png',
      headers: { 'Cache-Control': 'no-cache' },
      body: readFileSync(rutaArchivo),
    })
  })
}
