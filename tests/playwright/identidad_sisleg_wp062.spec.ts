/**
 * Identidad SIS-Leg en el navegador real (WP-062).
 *
 * Las pruebas de DOM comprueban que el marcado pide el logo correcto, pero no pueden
 * comprobar lo que el WP realmente exige: que la imagen **se descargue**, que **entre** en
 * el viewport en las dos resoluciones de referencia, que no introduzca scroll de página y
 * que su transparencia no dibuje un rectángulo blanco sobre las superficies oscuras. Eso
 * necesita un navegador de verdad, y por eso vive acá.
 *
 * Se cubren las dos superficies donde HUMAN_GATE decidió mostrar el logo completo:
 *
 * 1. la ventana de carga previa a la hidratación, común a las cuatro SPA;
 * 2. el estado público `SIN_PREPARAR` de la Pantalla del Recinto.
 *
 * Y, además, los metadatos que identifican cada pestaña: título con la marca y favicon con
 * el isotipo bajo el prefijo público de cada aplicación.
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

const URL_SIMULADOR = 'http://localhost:3002/simulador/'

/** Azul profundo institucional sobre el que se dibuja el logo. */
const FONDO_INSTITUCIONAL = 'rgb(7, 17, 31)'

/** Ventana durante la cual se retienen los scripts para observar la carga previa. */
const DEMORA_SCRIPTS_MS = 2_500

/** Tolerancia en píxeles al comparar bordes que deberían coincidir. */
const TOLERANCIA = 1

/**
 * Proporción real del lienzo aprobado (1536×1024 desde WP-069).
 *
 * Es la proporción del **archivo**, no la del dibujo: el asset humano trae márgenes
 * transparentes que el WP prohíbe recortar, así que la caja del `<img>` es más alta que la
 * marca visible. Lo que se comprueba acá es que el navegador no la deforme.
 */
const ANCHO_LOGO = 1536
const ALTO_LOGO = 1024
const PROPORCION_LOGO = ANCHO_LOGO / ALTO_LOGO

const SUPERFICIES = [
  {
    nombre: 'Moderación',
    url: URL_MODERACION,
    prefijo: '/moderacion/',
    titulo: 'SIS-Leg · Moderación',
    estados: { '/api/v1/estado/moderacion': estadoModeracion() },
  },
  {
    nombre: 'Recinto',
    url: URL_RECINTO,
    prefijo: '/recinto/',
    titulo: 'SIS-Leg · Pantalla del Recinto',
    estados: { '/api/v1/estado/recinto': estadoRecinto() },
  },
  {
    nombre: 'Simulador',
    url: URL_SIMULADOR,
    prefijo: '/simulador/',
    titulo: 'SIS-Leg · Simulador de Dispositivos',
    estados: { '/api/v1/estado/moderacion': estadoModeracion() },
  },
  {
    nombre: 'Apoyo Técnico',
    url: URL_TECNICO,
    prefijo: '/tecnico/',
    titulo: 'SIS-Leg · Apoyo Técnico',
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
 * Retiene los scripts hasta un instante límite para poder observar la ventana previa a la
 * hidratación. Es el mismo procedimiento que usa el E2E del indicador de carga: un límite
 * absoluto y compartido, no una demora por petición, porque Vite descubre los módulos en
 * cascada.
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
 * Mide una imagen ya cargada en la página.
 *
 * `naturalWidth` es la prueba de que el archivo llegó y el navegador pudo decodificarlo:
 * una imagen rota, un 404 o una ruta mal armada dejan ese valor en 0 aunque el elemento
 * exista y ocupe lugar en el layout.
 */
async function medirImagen(page: Page, selector: string) {
  return page.evaluate((consulta) => {
    const imagen = document.querySelector(consulta) as HTMLImageElement | null
    if (imagen === null) throw new Error(`No existe ${consulta}`)
    const caja = imagen.getBoundingClientRect()
    return {
      completa: imagen.complete,
      anchoNatural: imagen.naturalWidth,
      altoNatural: imagen.naturalHeight,
      src: imagen.currentSrc || imagen.src,
      x: caja.x,
      y: caja.y,
      ancho: caja.width,
      alto: caja.height,
    }
  }, selector)
}

/**
 * Cuenta cuántas de las cuatro esquinas del PNG son totalmente transparentes.
 *
 * Es la forma objetiva de comprobar el criterio 7 del WP —«no introducen fondo blanco
 * rectangular»—: se vuelve a dibujar la imagen en un canvas y se lee el canal alfa. Si el
 * archivo tuviera el fondo blanco original, las cuatro esquinas darían alfa 255.
 */
async function esquinasTransparentes(page: Page, selector: string): Promise<number> {
  return page.evaluate((consulta) => {
    const imagen = document.querySelector(consulta) as HTMLImageElement | null
    if (imagen === null) throw new Error(`No existe ${consulta}`)
    const lienzo = document.createElement('canvas')
    lienzo.width = imagen.naturalWidth
    lienzo.height = imagen.naturalHeight
    const contexto = lienzo.getContext('2d')
    if (contexto === null) throw new Error('El navegador no expuso contexto 2d')
    contexto.drawImage(imagen, 0, 0)

    const esquinas: Array<[number, number]> = [
      [0, 0],
      [lienzo.width - 1, 0],
      [0, lienzo.height - 1],
      [lienzo.width - 1, lienzo.height - 1],
    ]
    return esquinas.filter(([x, y]) => contexto.getImageData(x, y, 1, 1).data[3] === 0).length
  }, selector)
}

/** Verifica que la caja de un elemento entre completa dentro del viewport. */
function esperarDentroDelViewport(
  caja: { x: number; y: number; ancho: number; alto: number },
  viewport: { width: number; height: number },
): void {
  expect(caja.x).toBeGreaterThanOrEqual(-TOLERANCIA)
  expect(caja.y).toBeGreaterThanOrEqual(-TOLERANCIA)
  expect(caja.x + caja.ancho).toBeLessThanOrEqual(viewport.width + TOLERANCIA)
  expect(caja.y + caja.alto).toBeLessThanOrEqual(viewport.height + TOLERANCIA)
}

// =============================================================================
// 1. Logo en la ventana de carga de las cuatro SPA
// =============================================================================

for (const superficie of SUPERFICIES) {
  for (const viewport of RESOLUCIONES) {
    test(`${superficie.nombre} muestra el logo SIS-Leg antes de hidratar en ${viewport.width}×${viewport.height}`, async ({
      page,
    }) => {
      await page.setViewportSize(viewport)
      await instalarBackend(page, superficie.estados)
      await demorarScripts(page, DEMORA_SCRIPTS_MS)
      await page.goto(superficie.url, { waitUntil: 'commit' })

      const indicador = page.getByTestId('carga-inicial-previa')
      await expect(indicador).toBeVisible()
      const logo = page.getByTestId('carga-inicial-logo')
      await expect(logo).toBeVisible()

      // 1. La imagen llegó y se decodificó: la ruta relativa resolvió contra el prefijo
      //    público de esta aplicación y no contra la raíz del servidor.
      await expect
        .poll(
          async () => (await medirImagen(page, '[data-testid="carga-inicial-logo"]')).anchoNatural,
        )
        .toBeGreaterThan(0)
      const medidas = await medirImagen(page, '[data-testid="carga-inicial-logo"]')
      expect(medidas.src).toContain(`${superficie.prefijo}assets/marca/sisleg-logo.png`)
      expect(medidas.anchoNatural).toBe(ANCHO_LOGO)
      expect(medidas.altoNatural).toBe(ALTO_LOGO)

      // 2. Conserva la proporción del archivo y entra completo en la ventana.
      expect(medidas.ancho / medidas.alto).toBeCloseTo(PROPORCION_LOGO, 1)
      esperarDentroDelViewport(medidas, viewport)

      // 3. No hay marca escrita duplicando el logo ni resto de la marca anterior.
      const textoIndicador = (await indicador.textContent()) ?? ''
      expect(textoIndicador).not.toContain('Botonera2')
      expect(textoIndicador).not.toContain('SIS-Leg')

      // 4. El PNG es transparente: las cuatro esquinas tienen alfa 0, así que el azul
      //    institucional se ve a través y no aparece un rectángulo blanco.
      expect(await esquinasTransparentes(page, '[data-testid="carga-inicial-logo"]')).toBe(4)
      expect(
        await page.evaluate(
          () =>
            getComputedStyle(document.querySelector('[data-testid="carga-inicial-previa"]')!)
              .backgroundColor,
        ),
      ).toBe(FONDO_INSTITUCIONAL)

      // 5. El logo no puede introducir scroll de página en ninguna de las dos medidas.
      esperarSinScrollGlobal(await medirDocumento(page))
    })
  }
}

// =============================================================================
// 2. Metadatos visibles de cada pestaña
// =============================================================================

for (const superficie of SUPERFICIES) {
  test(`${superficie.nombre} publica título y favicon de SIS-Leg`, async ({ page }) => {
    await instalarBackend(page, superficie.estados)
    await page.goto(superficie.url)

    await expect(page).toHaveTitle(superficie.titulo)

    const icono = page.locator('link[rel="icon"]')
    await expect(icono).toHaveCount(1)
    expect(await icono.getAttribute('href')).toBe(
      `${superficie.prefijo}assets/marca/sisleg-isotipo.png`,
    )

    // El favicon tiene que existir realmente en el servidor estático de esta aplicación:
    // un `href` correcto sobre un archivo ausente sería igual de inútil.
    const respuesta = await page.request.get(
      new URL(`${superficie.prefijo}assets/marca/sisleg-isotipo.png`, superficie.url).href,
    )
    expect(respuesta.status()).toBe(200)
  })
}

// =============================================================================
// 3. Logo en el estado público SIN_PREPARAR
// =============================================================================

for (const viewport of RESOLUCIONES) {
  test(`SIN_PREPARAR muestra el logo completo sin desbordar en ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport)
    await instalarBackend(page, {
      '/api/v1/estado/recinto': {
        ...estadoRecinto(),
        estado_global: 'SIN_PREPARAR',
        sesion: null,
        preparacion: null,
        filas_bancas: null,
        concejales: [],
        quorum: null,
        palabra: null,
      },
    })
    await page.goto(URL_RECINTO)

    const bloque = page.getByTestId('estado-sin-preparar')
    await expect(bloque).toBeVisible()

    // 1. El logo aprobado, cargado desde el `public/` del Recinto.
    await expect
      .poll(async () => (await medirImagen(page, '[data-testid="logo-sin-preparar"]')).anchoNatural)
      .toBeGreaterThan(0)
    const medidas = await medirImagen(page, '[data-testid="logo-sin-preparar"]')
    expect(medidas.src).toContain('/recinto/assets/marca/sisleg-logo.png')
    expect(medidas.ancho / medidas.alto).toBeCloseTo(PROPORCION_LOGO, 1)

    // 2. Entra completo en la pantalla y dentro de su propio contenedor: nada se recorta.
    esperarDentroDelViewport(medidas, viewport)
    const cajaBloque = await bloque.boundingBox()
    expect(cajaBloque).not.toBeNull()
    expect(medidas.x).toBeGreaterThanOrEqual(cajaBloque!.x - TOLERANCIA)
    expect(medidas.x + medidas.ancho).toBeLessThanOrEqual(
      cajaBloque!.x + cajaBloque!.width + TOLERANCIA,
    )

    // 3. Transparencia efectiva sobre la superficie oscura.
    expect(await esquinasTransparentes(page, '[data-testid="logo-sin-preparar"]')).toBe(4)

    // 4. No se repite la marca como texto ni sobrevive la terminología anterior.
    const texto = (await bloque.textContent()) ?? ''
    expect(texto).toContain('Recinto sin preparar')
    expect(texto).not.toContain('Sala')
    expect(texto).not.toContain('SIS-Leg')

    // 5. El WP prohíbe introducir scroll global: se mide el documento completo.
    esperarSinScrollGlobal(await medirDocumento(page))
  })
}
