/**
 * Indicador de carga inicial de las cuatro SPA (WP-061).
 *
 * El defecto que corrige este WP no se puede observar con el DOM liviano de Vitest: hay
 * que mirar la ventana real en la que el navegador todavía no ejecutó el bundle de Vue.
 * Por eso las afirmaciones de acá se hacen sobre cajas reales (`getBoundingClientRect`),
 * colores computados y desborde del documento, en las dos resoluciones que exige el WP.
 *
 * Se cubren las tres ventanas temporales de una carga:
 *
 * 1. **Antes de la hidratación.** Se demoran deliberadamente los scripts: durante esa
 *    espera debe verse el indicador que Nuxt incrusta en el HTML, con fondo institucional
 *    y barra indeterminada, y el viewport no puede quedar blanco.
 * 2. **Después del montaje y antes del primer snapshot.** El backend se sustituye por un
 *    doble que sólo devuelve errores, así que el estado nunca llega: debe verse la barra
 *    del componente compartido, y no puede ocupar espacio ni desplazar la interfaz.
 * 3. **Aplicación operativa.** Con un backend que responde, los dos indicadores
 *    desaparecen y no queda hueco ni scroll de página.
 *
 * Cada aplicación se sirve desde su propio servidor de desarrollo declarado en
 * `playwright.config.ts`.
 */

import { expect, test, type Page, type Route } from '@playwright/test'

import {
  esperarSinScrollGlobal,
  estadoModeracion,
  estadoRecinto,
  estadoTecnico,
  instalarBackend,
  medirDocumento,
  RESOLUCIONES,
  URL_MODERACION,
  URL_RECINTO,
  URL_TECNICO,
} from './soporte/apoyo_tecnico'
import { instalarFotosConcejales } from './soporte/fotos_concejales'

const URL_SIMULADOR = 'http://localhost:3002/simulador/'

/** Azul profundo institucional declarado por `carga_inicial.html`. */
const FONDO_INSTITUCIONAL = 'rgb(7, 17, 31)'

/** Cuánto se retiene la carga de scripts para poder observar la ventana pre-hidratación. */
const DEMORA_SCRIPTS_MS = 2_500

/** Tolerancia en píxeles al comparar bordes que deben coincidir. */
const TOLERANCIA = 1

/**
 * Las cuatro superficies frontend servidas por SIS-Leg, con los snapshots que cada una
 * consume. Apoyo Técnico necesita dos proyecciones a la vez; el Simulador consume la de
 * Moderación, que es la única que le interesa para su panel de diagnóstico.
 */
const SUPERFICIES = [
  {
    nombre: 'Moderación',
    url: URL_MODERACION,
    estados: { '/api/v1/estado/moderacion': estadoModeracion() },
  },
  {
    nombre: 'Recinto',
    url: URL_RECINTO,
    estados: { '/api/v1/estado/recinto': estadoRecinto() },
  },
  {
    nombre: 'Simulador',
    url: URL_SIMULADOR,
    estados: { '/api/v1/estado/moderacion': estadoModeracion() },
  },
  {
    nombre: 'Apoyo Técnico',
    url: URL_TECNICO,
    estados: {
      '/api/v1/estado/tecnico': estadoTecnico(),
      '/api/v1/estado/moderacion': estadoModeracion(),
    },
  },
] as const

function esperar(milisegundos: number): Promise<void> {
  return new Promise((resolver) => setTimeout(resolver, milisegundos))
}

/**
 * Retiene todos los scripts hasta un instante límite y deja pasar el resto sin demora.
 *
 * Es la forma de reproducir de manera determinista "el bundle todavía no llegó". Se usa un
 * **límite absoluto** y no una demora por petición porque Vite descubre los módulos en
 * cascada: demorar cada uno multiplicaría la espera hasta agotar el tiempo de la prueba.
 * Con un límite común, todas las peticiones que nacen dentro de la ventana esperan hasta
 * el mismo instante y las posteriores pasan enseguida.
 *
 * @param page Página donde instalar la intercepción.
 * @param milisegundos Duración de la ventana, contada desde la instalación.
 */
async function demorarScripts(page: Page, milisegundos: number): Promise<void> {
  const limite = Date.now() + milisegundos
  await page.route('**/*', async (ruta: Route) => {
    if (ruta.request().resourceType() === 'script') {
      const restante = limite - Date.now()
      if (restante > 0) await esperar(restante)
    }
    await ruta.continue()
  })
}

/**
 * Instala un backend que siempre falla, de modo que el primer snapshot nunca llegue.
 *
 * Devolver 503 —en lugar de dejar la petición colgada— es lo más parecido a un backend que
 * todavía no está listo: el cliente reintenta con su backoff normal y la aplicación
 * conserva `estado === null`, que es exactamente la ventana que se quiere observar.
 */
async function instalarBackendSinRespuesta(page: Page): Promise<void> {
  // WP-098: la fotografía de banca ya no es un asset del build; la publica
  // el backend desde la configuración local. Sin backend real, se responde
  // desde la plantilla versionada, que es el mismo archivo de siempre.
  await instalarFotosConcejales(page)

  await page.route('**/api/v1/**', (ruta: Route) =>
    ruta.fulfill({
      status: 503,
      contentType: 'text/plain',
      body: 'backend no disponible durante la prueba',
    }),
  )
}

/** Lee el color de fondo efectivamente computado por el navegador para un selector. */
function colorDeFondo(page: Page, selector: string): Promise<string> {
  return page.evaluate((consulta) => {
    const elemento = document.querySelector(consulta)
    if (elemento === null) return 'sin elemento'
    return getComputedStyle(elemento).backgroundColor
  }, selector)
}

// =============================================================================
// 1. Ventana previa a la hidratación
// =============================================================================

for (const superficie of SUPERFICIES) {
  for (const viewport of RESOLUCIONES) {
    test(`${superficie.nombre} muestra fondo y barra antes de hidratar en ${viewport.width}×${viewport.height}`, async ({
      page,
    }) => {
      await page.setViewportSize(viewport)
      await instalarBackend(page, superficie.estados)
      await demorarScripts(page, DEMORA_SCRIPTS_MS)

      // `commit` devuelve el control apenas empieza a llegar el documento, que es cuando
      // hay que mirar. Esperar `load` significaría esperar justamente a los scripts.
      await page.goto(superficie.url, { waitUntil: 'commit' })

      const indicadorPrevio = page.getByTestId('carga-inicial-previa')
      await expect(indicadorPrevio).toBeVisible()

      // 1. El fondo cubre el viewport completo y no es blanco.
      expect(await colorDeFondo(page, '[data-testid="carga-inicial-previa"]')).toBe(
        FONDO_INSTITUCIONAL,
      )
      const cajaIndicador = await indicadorPrevio.boundingBox()
      expect(cajaIndicador).not.toBeNull()
      expect(cajaIndicador!.x).toBeLessThanOrEqual(TOLERANCIA)
      expect(cajaIndicador!.y).toBeLessThanOrEqual(TOLERANCIA)
      expect(cajaIndicador!.width).toBeGreaterThanOrEqual(viewport.width - TOLERANCIA)
      expect(cajaIndicador!.height).toBeGreaterThanOrEqual(viewport.height - TOLERANCIA)

      // 2. La aplicación todavía no dibujó nada: la ventana observada es la real.
      expect(await page.locator('#__nuxt').innerHTML()).toBe('')

      // 3. Hay barra indeterminada, con ancho propio y sin porcentaje declarado.
      const barra = page.locator('.carga-inicial__barra')
      const avance = page.locator('.carga-inicial__avance')
      await expect(barra).toBeVisible()
      const cajaBarra = await barra.boundingBox()
      const cajaAvance = await avance.boundingBox()
      expect(cajaBarra!.width).toBeGreaterThanOrEqual(viewport.width - TOLERANCIA)
      expect(cajaAvance!.width).toBeGreaterThan(0)
      expect(cajaAvance!.width).toBeLessThan(cajaBarra!.width)
      await expect(indicadorPrevio).not.toHaveAttribute('aria-valuenow', /.*/)

      // 4. El indicador no puede introducir scroll de página.
      esperarSinScrollGlobal(await medirDocumento(page))

      // 5. Cuando la aplicación queda montada, Nuxt retira el indicador previo por
      //    completo: no queda un nodo invisible ocupando lugar.
      await expect(indicadorPrevio).toHaveCount(0, { timeout: 20_000 })
      await expect(page.locator('#__nuxt-loader')).toHaveCount(0)
      esperarSinScrollGlobal(await medirDocumento(page))
    })
  }
}

// =============================================================================
// 2. Recarga dura
// =============================================================================

for (const superficie of SUPERFICIES) {
  test(`${superficie.nombre} vuelve a mostrar el indicador tras una recarga dura`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1366, height: 768 })
    await instalarBackend(page, superficie.estados)
    await page.goto(superficie.url)
    await expect(page.getByTestId('carga-inicial-previa')).toHaveCount(0)

    // Una recarga vuelve a pedir el documento y el bundle: la ventana pre-hidratación
    // existe otra vez, y el indicador debe volver a cubrirla.
    await demorarScripts(page, DEMORA_SCRIPTS_MS)
    await page.reload({ waitUntil: 'commit' })

    await expect(page.getByTestId('carga-inicial-previa')).toBeVisible()
    expect(await colorDeFondo(page, '[data-testid="carga-inicial-previa"]')).toBe(
      FONDO_INSTITUCIONAL,
    )
    await expect(page.getByTestId('carga-inicial-previa')).toHaveCount(0, { timeout: 20_000 })
    esperarSinScrollGlobal(await medirDocumento(page))
  })
}

// =============================================================================
// 3. Espera del primer snapshot, ya montada la aplicación
// =============================================================================

for (const superficie of SUPERFICIES) {
  for (const viewport of RESOLUCIONES) {
    test(`${superficie.nombre} conserva la barra mientras no llega el primer snapshot en ${viewport.width}×${viewport.height}`, async ({
      page,
    }) => {
      await page.setViewportSize(viewport)
      await instalarBackendSinRespuesta(page)
      await page.goto(superficie.url)

      const indicadorAplicacion = page.getByTestId('carga-inicial-aplicacion')
      await expect(indicadorAplicacion).toBeVisible()

      // 1. Geometría: barra completa arriba, de alto fijo y sin desbordar.
      const cajaIndicador = await indicadorAplicacion.boundingBox()
      expect(cajaIndicador).not.toBeNull()
      expect(cajaIndicador!.y).toBeLessThanOrEqual(TOLERANCIA)
      expect(cajaIndicador!.width).toBeGreaterThanOrEqual(viewport.width - TOLERANCIA)
      expect(cajaIndicador!.height).toBeLessThanOrEqual(6)

      // 2. No ocupa espacio en el flujo: el hermano siguiente —la cabecera de cada
      //    aplicación— sigue empezando en el borde superior del viewport.
      const cajaHermano = await page
        .locator('[data-testid="carga-inicial-aplicacion"] + *')
        .boundingBox()
      expect(cajaHermano).not.toBeNull()
      expect(Math.abs(cajaHermano!.y)).toBeLessThanOrEqual(TOLERANCIA)

      // 3. El fondo de la pantalla tampoco es blanco durante esta espera.
      expect(await colorDeFondo(page, 'html')).not.toBe('rgb(255, 255, 255)')

      // 4. Sigue sin haber scroll de página.
      esperarSinScrollGlobal(await medirDocumento(page))
    })
  }
}

// =============================================================================
// 4. Aplicación operativa
// =============================================================================

for (const superficie of SUPERFICIES) {
  test(`${superficie.nombre} retira la barra cuando llega el primer snapshot`, async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 })
    await instalarBackend(page, superficie.estados)
    await page.goto(superficie.url)

    await expect(page.getByTestId('carga-inicial-aplicacion')).toHaveCount(0)
    await expect(page.getByTestId('carga-inicial-previa')).toHaveCount(0)
    esperarSinScrollGlobal(await medirDocumento(page))
  })
}
