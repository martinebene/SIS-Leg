/**
 * WP-098 · fuente única de fotografías de banca contra el stack real.
 *
 * Este recorrido es el que no puede hacerse con dobles: corre contra el FastAPI
 * real sirviendo la configuración local de este checkout y contra las cuatro SPA
 * ya construidas, servidas como archivos estáticos igual que en producción.
 *
 * Qué demuestra
 * -------------
 *
 * 1. las dos superficies que dibujan bancas —Q3 de Moderación y la Pantalla del
 *    Recinto— piden **exactamente la misma URL** para la misma persona, y esa
 *    URL es el endpoint de configuración del backend;
 * 2. la imagen realmente se descarga y decodifica (`naturalWidth > 0`);
 * 3. **ningún build de frontend contiene fotografías de banca**: es la prueba
 *    directa de que cambiar una foto no puede requerir un rebuild, porque no hay
 *    nada que reconstruir;
 * 4. sustituir el archivo en la configuración local cambia lo que entrega el
 *    backend en el pedido siguiente, con el mismo proceso corriendo.
 *
 * Por qué el punto 4 usa un archivo propio
 * ----------------------------------------
 *
 * La regla de WP-073 es explícita: ninguna prueba escribe sobre la
 * configuración operativa de quien la ejecuta. Las doce fotos de
 * `config/assets/bancas/` pueden ser las reales de una instalación, así que la
 * sustitución se demuestra sobre un archivo que esta misma prueba crea y borra.
 * La garantía que interesa —que el archivo se lee en cada pedido y no se
 * congela en el arranque ni en el build— queda igual de demostrada.
 */

import { expect, test, type Page } from '@playwright/test'
import { promises as archivos } from 'node:fs'
import { join, resolve } from 'node:path'
import { ProcesoStackIntegrado, URL_STACK, puertoOcupado } from './infraestructura'

const RAIZ_REPOSITORIO = resolve(__dirname, '../..')

/** Directorio runtime de las fotografías, el mismo que lee el backend. */
const DIRECTORIO_FOTOS = join(RAIZ_REPOSITORIO, 'config/assets/bancas')

/** Archivo propio de esta prueba; el padrón no lo referencia. */
const NOMBRE_FOTO_PRUEBA = 'banca-prueba-wp098.png'
const RUTA_FOTO_PRUEBA = join(DIRECTORIO_FOTOS, NOMBRE_FOTO_PRUEBA)
const URL_FOTO_PRUEBA = `${URL_STACK}/api/v1/recursos/imagenes-concejales/${NOMBRE_FOTO_PRUEBA}`

/** Prefijo público de cada SPA construida, tal como los sirve el stack. */
const SALIDAS_SPA = ['moderacion', 'recinto', 'simulador', 'tecnico'] as const

const PRIMERA_VERSION = Buffer.concat([
  Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
  Buffer.from('primera version de la fotografia'),
])
const SEGUNDA_VERSION = Buffer.concat([
  Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
  Buffer.from('segunda version, cargada por el operador'),
])

/** Devuelve el `src` y el ancho natural de la primera foto de banca dibujada. */
async function medirPrimeraFoto(page: Page): Promise<{ src: string; anchoNatural: number }> {
  const imagen = page.locator('[data-testid="imagen-concejal"]').first()
  await expect(imagen).toBeVisible()
  await page.waitForFunction(() => {
    const nodo = document.querySelector<HTMLImageElement>('[data-testid="imagen-concejal"]')
    return Boolean(nodo?.complete && nodo.naturalWidth > 0)
  })
  return imagen.evaluate((nodo) => {
    const elemento = nodo as HTMLImageElement
    return { src: elemento.getAttribute('src') ?? '', anchoNatural: elemento.naturalWidth }
  })
}

test.describe.serial('WP-098 · fotografías de banca desde la configuración local', () => {
  const stack = new ProcesoStackIntegrado()

  test.beforeAll(async () => {
    expect(await puertoOcupado()).toBe(false)
    await stack.iniciar()
  })

  test.afterAll(async () => {
    // El archivo de prueba se borra siempre, incluso si una aserción falló.
    await archivos.rm(RUTA_FOTO_PRUEBA, { force: true })
    await stack.detener()
    expect(await puertoOcupado()).toBe(false)
  })

  test.afterEach(async ({}, informacion) => {
    if (informacion.status !== informacion.expectedStatus) {
      await informacion.attach('stdout-stderr-stack.txt', {
        body: stack.obtenerSalida(),
        contentType: 'text/plain',
      })
    }
  })

  test('ningún build de frontend publica fotografías de banca', async () => {
    // Es la evidencia más directa del criterio «sin rebuild»: si el build no
    // contiene la foto, cambiarla no puede exigir volver a construirlo.
    for (const aplicacion of SALIDAS_SPA) {
      const directorio = join(RAIZ_REPOSITORIO, 'apps', aplicacion, '.output/public/assets/bancas')
      await expect(archivos.stat(directorio)).rejects.toThrow()
    }
  })

  test('Moderación y Recinto piden la misma foto al mismo endpoint', async ({ browser }) => {
    const contexto = await browser.newContext({ viewport: { width: 1366, height: 768 } })
    const moderacion = await contexto.newPage()
    const recinto = await contexto.newPage()

    await moderacion.goto(`${URL_STACK}/moderacion/`)
    // Las bancas sólo se dibujan a partir de `PREPARANDO`, así que hay que
    // preparar el recinto igual que lo haría el operador.
    await moderacion.getByTestId('btn-preparar-sala').click()
    await moderacion.getByTestId('vista-preparando').waitFor()
    await recinto.goto(`${URL_STACK}/recinto/`)

    const enModeracion = await medirPrimeraFoto(moderacion)
    const enRecinto = await medirPrimeraFoto(recinto)

    // Una sola fuente física: la misma URL desde las dos superficies.
    expect(enModeracion.src).toBe(enRecinto.src)
    expect(enModeracion.src).toContain('/api/v1/recursos/imagenes-concejales/')
    // Ninguna resuelve ya contra el prefijo público de su propia SPA.
    expect(enModeracion.src).not.toContain('/moderacion/assets/bancas/')
    expect(enRecinto.src).not.toContain('/recinto/assets/bancas/')
    // La imagen llegó y el navegador pudo decodificarla.
    expect(enModeracion.anchoNatural).toBeGreaterThan(0)
    expect(enRecinto.anchoNatural).toBe(enModeracion.anchoNatural)

    await contexto.close()
  })

  test('sustituir el archivo configurado se refleja sin reconstruir ni reiniciar', async ({
    request,
  }) => {
    // Antes de existir, el recurso responde 404 con el código estable.
    const ausente = await request.get(URL_FOTO_PRUEBA)
    expect(ausente.status()).toBe(404)
    expect((await ausente.json()).codigo).toBe('IMAGEN_CONCEJAL_NO_DISPONIBLE')

    await archivos.writeFile(RUTA_FOTO_PRUEBA, PRIMERA_VERSION)
    const primera = await request.get(URL_FOTO_PRUEBA)
    expect(primera.status()).toBe(200)
    expect(primera.headers()['content-type']).toBe('image/png')
    expect(Buffer.from(await primera.body()).equals(PRIMERA_VERSION)).toBe(true)

    // El operador reemplaza la fotografía. No se reconstruye ningún frontend y
    // tampoco se reinicia el backend: es el mismo proceso de siempre.
    await archivos.writeFile(RUTA_FOTO_PRUEBA, SEGUNDA_VERSION)
    const segunda = await request.get(URL_FOTO_PRUEBA)
    expect(segunda.status()).toBe(200)
    expect(Buffer.from(await segunda.body()).equals(SEGUNDA_VERSION)).toBe(true)
    // `no-cache` es lo que impide que el navegador siga mostrando la anterior.
    expect(segunda.headers()['cache-control']).toBe('no-cache')

    // Y al quitarla vuelve al 404 explícito, sin dejar una versión cacheada.
    await archivos.rm(RUTA_FOTO_PRUEBA, { force: true })
    expect((await request.get(URL_FOTO_PRUEBA)).status()).toBe(404)
  })

  test('una ruta insegura nunca devuelve un archivo del servidor', async ({ request }) => {
    for (const rutaPeligrosa of [
      '/api/v1/recursos/imagenes-concejales/..%2F..%2Fconcejales.csv',
      '/api/v1/recursos/imagenes-concejales/%2e%2e%2fsystem.toml',
      '/api/v1/recursos/imagenes-concejales/.env',
      '/api/v1/recursos/imagenes-concejales/banca-01.svg',
    ]) {
      const respuesta = await request.get(`${URL_STACK}${rutaPeligrosa}`)
      expect(respuesta.status()).not.toBe(200)
    }
  })
})
