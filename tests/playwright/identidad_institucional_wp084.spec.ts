/**
 * Identidad institucional configurable en el navegador real (WP-084).
 *
 * La prueba de componente ya fija que la cabecera publica el nombre que llega en
 * `EstadoRecinto.institucion`. Lo que no puede comprobar es lo que de verdad
 * arriesga este WP: que un nombre institucional **de longitud arbitraria** no
 * rompa la cabecera. Hasta ahora ese texto era un literal escrito en la
 * plantilla y toda la geometría de WP-050/WP-054/WP-058 se calibró contra él;
 * desde este WP lo escribe quien opera y puede ser mucho más corto o más largo.
 *
 * ## Qué se descubrió midiendo
 *
 * Con las columnas anteriores —`minmax(0, 1fr) auto minmax(0, 1fr)`— un nombre
 * largo hacía que la columna central pidiera más ancho que la cabecera entera:
 * las dos columnas laterales colapsaban a cero y el título se dibujaba **encima
 * del reloj**. Con 86 caracteres, en 1366×768, el `h1` ocupaba de 37 px a
 * 1027 px y el reloj termina en 248 px. No producía scroll —la cabecera recorta
 * con `overflow: hidden`— así que era exactamente el tipo de rotura silenciosa
 * que sólo aparece midiendo cajas reales.
 *
 * WP-084 corrigió las dos causas: las columnas laterales reservan su
 * `min-content` y el título es el único dato central que puede encogerse. Estas
 * pruebas son la regresión de esa corrección.
 *
 * ## Qué se afirma
 *
 * Para los dos nombres de referencia, en las dos resoluciones canónicas:
 *
 * 1. se muestra exactamente el valor configurado, sin recorte;
 * 2. la cabecera conserva su altura fija y el texto ocupa una sola línea;
 * 3. las tres zonas no se solapan y el centro queda realmente centrado;
 * 4. la página no adquiere scroll global.
 *
 * Y, además, que un nombre desmedido degrada de forma ordenada: se recorta con
 * elipsis dentro del propio título en lugar de invadir a sus vecinos.
 */

import { expect, test, type Page } from '@playwright/test'

import {
  esperarSinScrollGlobal,
  estadoRecinto,
  instalarBackend,
  medirDocumento,
  RESOLUCIONES,
  URL_RECINTO,
} from './soporte/apoyo_tecnico'

/**
 * Los dos nombres de referencia exigidos por el criterio de aceptación 3.
 *
 * El corto es el piso realista de un cuerpo legislativo municipal. El largo casi
 * duplica su cantidad de caracteres y está calibrado contra el presupuesto real
 * de la cabecera: con la sesión y la duración ocupando el resto del renglón,
 * 1366×768 admite alrededor de 42 caracteres antes de que aparezca la elipsis.
 * Los dos son ficticios y ninguno nombra una institución concreta.
 */
const NOMBRES = [
  { etiqueta: 'corto', valor: 'Concejo de Villa Sur' },
  { etiqueta: 'largo', valor: 'Honorable Legislatura de Ciudad Ejemplo' },
] as const

/**
 * Nombre desmedido usado sólo para el escenario de degradación.
 *
 * No entra en ninguna resolución: es el caso en que el sistema tiene que elegir
 * entre recortar el nombre o tapar el reloj, y la respuesta correcta es recortar.
 */
const NOMBRE_DESMEDIDO =
  'Honorable Legislatura Provincial de la Región Continental de Nuevos Territorios del Sur'

/** Tolerancia en píxeles: el layout resuelve en subpíxeles y devuelve fraccionarios. */
const TOLERANCIA = 1

/** Techo físico de la franja, fijado por WP-050 y remedido por WP-058. */
const ALTO_MAXIMO_CABECERA = 60

async function abrirRecintoCon(
  page: Page,
  viewport: { width: number; height: number },
  nombre: string,
): Promise<void> {
  await page.setViewportSize(viewport)
  await instalarBackend(page, {
    '/api/v1/estado/recinto': { ...estadoRecinto(), institucion: { nombre } },
  })
  await page.goto(URL_RECINTO)
  await expect(page.getByTestId('cabecera-institucion')).toBeVisible()
}

/**
 * Mide la cabecera completa: las tres zonas y el recorte del título.
 *
 * `scrollWidth - clientWidth` delata un texto que necesita más ancho del pintado,
 * que es la definición operativa de «se recortó». `scrollHeight` contra la altura
 * de línea delata un salto a un segundo renglón, que es lo que la altura fija de
 * la franja no puede absorber.
 */
async function medirCabecera(page: Page) {
  return page.evaluate(() => {
    function caja(selector: string) {
      const elemento = document.querySelector(selector)
      if (elemento === null) throw new Error(`No existe ${selector}`)
      const rect = elemento.getBoundingClientRect()
      const estilo = getComputedStyle(elemento)
      return {
        izquierda: rect.left,
        derecha: rect.right,
        ancho: rect.width,
        alto: rect.height,
        alturaLinea: Number.parseFloat(estilo.lineHeight),
        recorteHorizontal: elemento.scrollWidth - elemento.clientWidth,
        altoVisible: elemento.clientHeight,
        altoContenido: elemento.scrollHeight,
        texto: (elemento.textContent ?? '').trim(),
      }
    }

    return {
      cabecera: caja('[data-testid="cabecera-recinto"]'),
      reloj: caja('[data-testid="cabecera-fecha-hora"]'),
      centro: caja('[data-testid="cabecera-contexto"]'),
      titulo: caja('[data-testid="cabecera-institucion"]'),
      sectorDerecho: caja('.sector-derecho'),
    }
  })
}

/** Comprueba las invariantes que ningún nombre puede romper, se recorte o no. */
function esperarCabeceraSana(
  medidas: Awaited<ReturnType<typeof medirCabecera>>,
  viewport: { width: number; height: number },
): void {
  // La franja conserva su altura fija: ningún texto la empuja hacia abajo.
  expect(medidas.cabecera.alto).toBeLessThanOrEqual(ALTO_MAXIMO_CABECERA + TOLERANCIA)

  // Un solo renglón: si el título saltara a una segunda línea, su contenido
  // mediría más alto que una línea y la franja lo recortaría verticalmente.
  expect(medidas.titulo.altoContenido).toBeLessThanOrEqual(
    Math.ceil(medidas.titulo.alturaLinea) + TOLERANCIA,
  )

  // Sin solapamiento entre las tres zonas: el título empieza después del reloj y
  // termina antes del sector derecho. Es la comprobación que fallaba antes de la
  // corrección de columnas de este WP.
  expect(medidas.titulo.izquierda).toBeGreaterThanOrEqual(medidas.reloj.derecha - TOLERANCIA)
  expect(medidas.titulo.derecha).toBeLessThanOrEqual(medidas.sectorDerecho.izquierda + TOLERANCIA)

  // Todo entra en el viewport y la cabecera no desborda hacia los lados.
  expect(medidas.reloj.izquierda).toBeGreaterThanOrEqual(-TOLERANCIA)
  expect(medidas.sectorDerecho.derecha).toBeLessThanOrEqual(viewport.width + TOLERANCIA)
  expect(medidas.cabecera.recorteHorizontal).toBeLessThanOrEqual(TOLERANCIA)
}

for (const viewport of RESOLUCIONES) {
  for (const nombre of NOMBRES) {
    test(`la cabecera muestra completo un nombre institucional ${nombre.etiqueta} en ${viewport.width}×${viewport.height}`, async ({
      page,
    }) => {
      await abrirRecintoCon(page, viewport, nombre.valor)
      const medidas = await medirCabecera(page)

      // Criterio 2: se muestra exactamente el valor configurado.
      expect(medidas.titulo.texto).toBe(nombre.valor)

      // Criterio 3: ninguno de los dos nombres de referencia se recorta.
      expect(medidas.titulo.recorteHorizontal).toBeLessThanOrEqual(TOLERANCIA)

      esperarCabeceraSana(medidas, viewport)

      // El centrado real de WP-054 se conserva con los dos nombres: mientras el
      // nombre entra, la columna central sigue cayendo sobre el eje del viewport.
      const ejeCentro = (medidas.centro.izquierda + medidas.centro.derecha) / 2
      expect(ejeCentro).toBeCloseTo(viewport.width / 2, 0)

      esperarSinScrollGlobal(await medirDocumento(page))
    })
  }

  test(`un nombre desmedido se recorta dentro del título y no invade sus vecinos en ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    await abrirRecintoCon(page, viewport, NOMBRE_DESMEDIDO)
    const medidas = await medirCabecera(page)

    // El texto completo sigue en el DOM: el recorte es visual, no una truncación
    // del contenido, así que el emergente conserva la lectura íntegra.
    expect(medidas.titulo.texto).toBe(NOMBRE_DESMEDIDO)
    expect(medidas.titulo.recorteHorizontal).toBeGreaterThan(TOLERANCIA)

    // Y aun recortado, respeta todas las invariantes de la franja.
    esperarCabeceraSana(medidas, viewport)
    esperarSinScrollGlobal(await medirDocumento(page))
  })
}
