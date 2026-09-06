/**
 * Acceso de ayuda en las cabeceras de Moderación y de Apoyo Técnico (WP-067).
 *
 * Las pruebas de componente ya fijan el destino, la apertura en pestaña nueva y el texto
 * accesible. Lo que sólo puede medirse en un navegador real es la parte geométrica, que es
 * justamente la que el WP protege: agregar un elemento a una cabecera densa no puede
 * romper la línea única ni introducir desplazamiento en la página.
 *
 * Por eso acá se mide, con cajas reales y en las dos resoluciones exigidas:
 *
 * 1. que el acceso exista y sea visible;
 * 2. que esté en el **extremo derecho**: ningún otro elemento de la cabecera termina más a
 *    la derecha, y su borde llega al borde útil de la barra;
 * 3. que la cabecera siga ocupando **una sola línea**, comprobado por los centros
 *    verticales de todos sus elementos y no por una altura arbitraria;
 * 4. que el documento no adquiera desplazamiento general;
 * 5. que al activarlo se abra una pestaña nueva en la dirección esperada, sin reemplazar
 *    la pantalla operativa.
 *
 * El documento en sí —que abra, que tenga sus trece capítulos y que sus enlaces internos
 * funcionen— se prueba contra el stack real en
 * `tests/playwright-integrado/manual_usuario_wp067.spec.ts`, porque `/manual/` es una ruta
 * del origen unificado y no de los servidores de desarrollo por aplicación.
 */

import { expect, test, type Page } from '@playwright/test'

import {
  esperarSinScrollGlobal,
  estadoModeracion,
  estadoTecnico,
  instalarBackend,
  medirDocumento,
  RESOLUCIONES,
  URL_MODERACION,
  URL_TECNICO,
} from './soporte/apoyo_tecnico'

/** Ruta canónica del manual, la misma que declara `@sis-leg/frontend-shared`. */
const RUTA_MANUAL = '/manual/'

/**
 * Tolerancia en píxeles al comparar cajas.
 *
 * Los rectángulos del navegador son decimales y el redondeo de subpíxeles puede mover un
 * borde una fracción. Un margen de un píxel absorbe eso sin ocultar un desplazamiento
 * real, que sería de varios píxeles como mínimo.
 */
const TOLERANCIA = 1

/** Las dos cabeceras que deben ofrecer el mismo acceso. */
const CABECERAS = [
  {
    nombre: 'Moderación',
    url: URL_MODERACION,
    testidCabecera: 'cabecera-moderacion',
    estados: () => ({ '/api/v1/estado/moderacion': estadoModeracion() }),
  },
  {
    nombre: 'Apoyo Técnico',
    url: URL_TECNICO,
    testidCabecera: 'cabecera-tecnico',
    estados: () => ({
      '/api/v1/estado/tecnico': estadoTecnico(),
      '/api/v1/estado/moderacion': estadoModeracion(),
    }),
  },
] as const

/** Espera de montaje: las aplicaciones se sirven en modo desarrollo y compilan al vuelo. */
const ESPERA_MONTAJE = 45_000

/**
 * Fotografía geométrica de la cabecera y de todos sus elementos identificados.
 *
 * Se calcula todo dentro del navegador en una sola pasada para que las medidas describan
 * el mismo instante de layout.
 */
async function medirCabecera(page: Page, testidCabecera: string) {
  return page.evaluate((id) => {
    const cabecera = document.querySelector(`[data-testid="${id}"]`)
    if (cabecera === null) throw new Error(`No se encontró la cabecera ${id}`)

    const estilos = getComputedStyle(cabecera)
    const caja = cabecera.getBoundingClientRect()
    const elementos = Array.from(cabecera.querySelectorAll('[data-testid]')).map((elemento) => {
      const rectangulo = elemento.getBoundingClientRect()
      return {
        testid: elemento.getAttribute('data-testid') ?? '',
        derecha: rectangulo.right,
        centroVertical: rectangulo.top + rectangulo.height / 2,
        ancho: rectangulo.width,
        alto: rectangulo.height,
      }
    })

    return {
      derechaUtil: caja.right - Number.parseFloat(estilos.paddingRight),
      alto: caja.height,
      desbordeHorizontal: cabecera.scrollWidth - cabecera.clientWidth,
      elementos,
    }
  }, testidCabecera)
}

for (const cabecera of CABECERAS) {
  test.describe(`WP-067 · Acceso al manual en ${cabecera.nombre}`, () => {
    for (const resolucion of RESOLUCIONES) {
      test(`${resolucion.width}×${resolucion.height}: queda a la derecha y en una sola línea`, async ({
        page,
      }) => {
        test.setTimeout(ESPERA_MONTAJE + 30_000)
        await page.setViewportSize(resolucion)
        await instalarBackend(page, cabecera.estados())
        await page.goto(cabecera.url)

        const acceso = page.getByTestId('acceso-manual')
        await expect(acceso).toBeVisible({ timeout: ESPERA_MONTAJE })

        const medidas = await medirCabecera(page, cabecera.testidCabecera)
        const accesoMedido = medidas.elementos.find(
          (elemento) => elemento.testid === 'acceso-manual',
        )
        expect(accesoMedido).toBeDefined()
        if (accesoMedido === undefined) return

        // 1. Ningún elemento de la cabecera termina más a la derecha que la ayuda.
        for (const elemento of medidas.elementos) {
          expect(
            elemento.derecha,
            `${elemento.testid} no puede quedar a la derecha del acceso de ayuda`,
          ).toBeLessThanOrEqual(accesoMedido.derecha + TOLERANCIA)
        }

        // 2. Y llega efectivamente al borde útil: está en el extremo, no simplemente
        //    después de los demás.
        expect(accesoMedido.derecha).toBeGreaterThanOrEqual(medidas.derechaUtil - TOLERANCIA)

        // 3. Todos los elementos comparten renglón: sus centros verticales coinciden.
        const centros = medidas.elementos.map((elemento) => elemento.centroVertical)
        expect(Math.max(...centros) - Math.min(...centros)).toBeLessThanOrEqual(TOLERANCIA)

        // 4. La cabecera no desborda hacia los costados ni empuja la página.
        expect(medidas.desbordeHorizontal).toBeLessThanOrEqual(TOLERANCIA)
        esperarSinScrollGlobal(await medirDocumento(page))

        // 5. Es un objetivo pulsable, no un punto decorativo de dos píxeles.
        expect(accesoMedido.ancho).toBeGreaterThanOrEqual(12)
        expect(accesoMedido.alto).toBeGreaterThanOrEqual(12)
      })
    }

    test('abre el manual en una pestaña nueva sin reemplazar la pantalla operativa', async ({
      page,
      context,
    }) => {
      test.setTimeout(ESPERA_MONTAJE + 30_000)
      await page.setViewportSize(RESOLUCIONES[0])
      await instalarBackend(page, cabecera.estados())
      await page.goto(cabecera.url)

      const acceso = page.getByTestId('acceso-manual')
      await expect(acceso).toBeVisible({ timeout: ESPERA_MONTAJE })
      await expect(acceso).toHaveAttribute('href', RUTA_MANUAL)
      await expect(acceso).toHaveAttribute('target', '_blank')
      await expect(acceso).toHaveAttribute('rel', 'noopener noreferrer')

      const urlOperativa = page.url()
      const [nueva] = await Promise.all([context.waitForEvent('page'), acceso.click()])

      /*
        La pestaña nueva apunta al manual bajo el mismo origen.

        La ruta final se comprueba por sufijo y no por igualdad exacta: acá cada aplicación
        corre en su propio servidor de desarrollo Nuxt, que redirige bajo su prefijo
        (`/moderacion/`, `/tecnico/`) cualquier ruta ajena. Es un comportamiento del
        servidor de desarrollo, no del enlace: el `href` es `/manual/`, tal como acaba de
        verificarse, y así lo resuelve el navegador. Que la URL definitiva sea exactamente
        `/manual/` bajo el origen unificado lo demuestra
        `tests/playwright-integrado/manual_usuario_wp067.spec.ts`, donde una sola superficie
        publica las cuatro aplicaciones, la API y el manual, igual que Nginx en producción.
      */
      expect(new URL(nueva.url()).pathname.endsWith(RUTA_MANUAL)).toBe(true)
      expect(new URL(nueva.url()).origin).toBe(new URL(urlOperativa).origin)

      // Y la pantalla operativa sigue exactamente donde estaba.
      expect(page.url()).toBe(urlOperativa)
      await expect(page.getByTestId(cabecera.testidCabecera)).toBeVisible()

      await nueva.close()
    })
  })
}
