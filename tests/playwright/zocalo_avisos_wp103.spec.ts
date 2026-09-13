/**
 * WP-103 — Avisos de Apoyo Técnico en el Zócalo para OBS.
 *
 * ## Qué demuestra este archivo
 *
 * Lo que sólo puede comprobarse con un navegador real que calcula layout y pinta píxeles:
 *
 * 1. **Geometría intacta.** Con aviso, el bloque conserva exactamente la caja que tenía sin
 *    aviso —abajo a la izquierda, ≈ 80 % de ancho, ≈ 20 % de alto, con márgenes— y el aviso
 *    queda íntegramente dentro de ella, sin scroll global ni propio.
 * 2. **Croma.** Fuera del bloque todo sigue siendo `#00FF00` opaco, y dentro del bloque —ahora
 *    ocupado por el aviso— no aparece ningún píxel que el filtro de croma pueda confundir.
 * 3. **Ciclo de vida en vivo.** Aparición, reemplazo y retiro del aviso llegan por el mismo
 *    canal SSE, sin recargar la página, y al retirarse vuelven los tres renglones.
 * 4. **Misma fuente que el Recinto.** Con la misma proyección `/api/v1/estado/recinto` y las
 *    mismas revisiones, la Pantalla del Recinto y el Zócalo muestran y retiran el mismo aviso.
 *
 * Se miden 1280×720 y 1920×1080, las dos resoluciones de transmisión que exige el WP. Las
 * tolerancias de proporción son las mismas que fijó WP-099 para el bloque sin aviso.
 */

import { expect, test, type Page } from '@playwright/test'

import {
  aviso,
  esperarSinScrollGlobal,
  estadoRecinto,
  instalarBackend,
  medirDocumento,
  publicarEstado,
  URL_RECINTO,
  URL_ZOCALO,
  votacionPublicaCerrada,
} from './soporte/apoyo_tecnico'
import { decodificarPng, describirPixel } from './soporte/pixeles_png'

/** Proyección pública compartida por el Recinto y el Zócalo. */
const RUTA_ESTADO_PUBLICO = '/api/v1/estado/recinto'

/** Resoluciones de transmisión exigidas por el WP. */
const RESOLUCIONES = [
  { width: 1920, height: 1080 },
  { width: 1280, height: 720 },
] as const

/** Verde de croma canónico. */
const CROMA = { r: 0, g: 255, b: 0, a: 255 }

/** Holgura de un píxel para bordes resueltos en subpíxeles. */
const TOLERANCIA = 1

/** Ventana del resultado coherente con `generado_en` de la fixture (`2026-09-02T10:00:00Z`). */
const RESULTADO_VISIBLE_HASTA = '2026-09-02T10:05:00Z'

/** Tema reconocible de la votación que el aviso reemplaza. */
const TEMA_NORMAL = 'Expediente 5678/2026 — Ordenanza de espacios verdes'

/** Snapshot público con votación cerrada visible y, opcionalmente, un aviso técnico. */
function estadoPublico(
  avisoTecnico: ReturnType<typeof aviso> | null,
  revision = 1,
  tema = TEMA_NORMAL,
) {
  return {
    ...estadoRecinto({ aviso: avisoTecnico }),
    revision,
    votacion: votacionPublicaCerrada({ tema, resultado_visible_hasta: RESULTADO_VISIBLE_HASTA }),
  }
}

/** Abre el Zócalo con el snapshot indicado y espera a que el bloque esté dibujado. */
async function abrirZocalo(
  page: Page,
  viewport: { width: number; height: number },
  estado: unknown,
): Promise<void> {
  await page.setViewportSize(viewport)
  await instalarBackend(page, { [RUTA_ESTADO_PUBLICO]: estado })
  await page.goto(URL_ZOCALO)
  await expect(page.getByTestId('zocalo')).toBeVisible()
}

/** Caja del bloque del Zócalo en coordenadas del viewport. */
async function cajaZocalo(page: Page) {
  return page.evaluate(() => {
    const caja = document.querySelector('[data-testid="zocalo"]')!.getBoundingClientRect()
    return {
      izquierda: caja.left,
      derecha: caja.right,
      arriba: caja.top,
      abajo: caja.bottom,
      ancho: caja.width,
      alto: caja.height,
    }
  })
}

/** Mide el aviso dentro del bloque: caja, contención del texto y recortes. */
async function medirAviso(page: Page) {
  return page.evaluate(() => {
    const zocalo = document.querySelector('[data-testid="zocalo"]') as HTMLElement
    const superficie = document.querySelector('[data-testid="aviso-tecnico-zocalo"]') as HTMLElement
    const texto = superficie.querySelector('[data-testid="texto-aviso"]') as HTMLElement
    const caja = superficie.getBoundingClientRect()
    const cajaTexto = texto.getBoundingClientRect()
    return {
      caja: { izquierda: caja.left, derecha: caja.right, arriba: caja.top, abajo: caja.bottom },
      texto: {
        izquierda: cajaTexto.left,
        derecha: cajaTexto.right,
        arriba: cajaTexto.top,
        abajo: cajaTexto.bottom,
      },
      truncado: superficie.getAttribute('data-truncado'),
      tamanoFuente: Number.parseFloat(getComputedStyle(texto).fontSize),
      recorteSuperficie: {
        horizontal: superficie.scrollWidth - superficie.clientWidth,
        vertical: superficie.scrollHeight - superficie.clientHeight,
      },
      recorteZocalo: {
        horizontal: zocalo.scrollWidth - zocalo.clientWidth,
        vertical: zocalo.scrollHeight - zocalo.clientHeight,
      },
      fondoZocalo: getComputedStyle(zocalo).backgroundColor,
      fondoLienzo: getComputedStyle(
        document.querySelector('[data-testid="lienzo-chroma"]') as HTMLElement,
      ).backgroundColor,
    }
  })
}

/** Afirma que el aviso ocupa el bloque y que los tres renglones no existen. */
async function esperarAvisoEnZocalo(page: Page, texto: string): Promise<void> {
  await expect(page.getByTestId('aviso-tecnico-zocalo')).toBeVisible()
  await expect(page.getByTestId('aviso-tecnico-zocalo').getByTestId('texto-aviso')).toHaveText(
    texto,
  )
  for (const testid of ['zocalo-votacion', 'zocalo-tema', 'zocalo-estado']) {
    await expect(page.getByTestId(testid)).toHaveCount(0)
  }
}

// =============================================================================
// 1. Geometría con aviso
// =============================================================================

for (const viewport of RESOLUCIONES) {
  test(`Zócalo con aviso: conserva la caja del bloque y contiene el aviso en ${viewport.width}×${viewport.height}`, async ({
    page,
  }, info) => {
    await abrirZocalo(page, viewport, estadoPublico(null))
    await expect(page.getByTestId('zocalo-tema')).toHaveText(TEMA_NORMAL)
    const sinAviso = await cajaZocalo(page)

    await publicarEstado(
      page,
      RUTA_ESTADO_PUBLICO,
      estadoPublico(aviso('Se reanuda la sesión en instantes', 'RECINTO'), 2),
    )
    await esperarAvisoEnZocalo(page, 'Se reanuda la sesión en instantes')
    // Se espera a que el ajuste tipográfico posterior al render haya elegido un cuerpo mayor
    // que el mínimo inicial antes de medir: hay espacio de sobra y debe aprovecharse.
    await expect.poll(async () => (await medirAviso(page)).tamanoFuente).toBeGreaterThan(14)
    const conAviso = await cajaZocalo(page)
    const medidas = await medirAviso(page)
    await info.attach(`zocalo-aviso-${viewport.width}x${viewport.height}.png`, {
      body: await page.screenshot(),
      contentType: 'image/png',
    })

    // Criterio 1: el aviso no mueve ni redimensiona la placa ya encuadrada.
    for (const lado of ['izquierda', 'derecha', 'arriba', 'abajo'] as const) {
      expect(Math.abs(conAviso[lado] - sinAviso[lado]), lado).toBeLessThanOrEqual(TOLERANCIA)
    }

    // Criterio 2: la geometría sigue siendo la aprobada en WP-099.
    const { width: anchoFrame, height: altoFrame } = viewport
    expect(conAviso.izquierda).toBeGreaterThan(0)
    expect(conAviso.izquierda).toBeLessThanOrEqual(anchoFrame * 0.05)
    expect(altoFrame - conAviso.abajo).toBeGreaterThan(0)
    expect(altoFrame - conAviso.abajo).toBeLessThanOrEqual(altoFrame * 0.05)
    expect(conAviso.ancho / anchoFrame).toBeGreaterThanOrEqual(0.78)
    expect(conAviso.ancho / anchoFrame).toBeLessThanOrEqual(0.82)
    expect(conAviso.alto / altoFrame).toBeGreaterThanOrEqual(0.18)
    expect(conAviso.alto / altoFrame).toBeLessThanOrEqual(0.22)
    const libreDerecha = (anchoFrame - conAviso.derecha) / anchoFrame
    expect(libreDerecha).toBeGreaterThanOrEqual(0.15)
    expect(libreDerecha).toBeLessThanOrEqual(0.22)

    // Criterio 3: el aviso y su texto quedan íntegramente dentro del bloque.
    for (const caja of [medidas.caja, medidas.texto]) {
      expect(caja.izquierda).toBeGreaterThanOrEqual(conAviso.izquierda - TOLERANCIA)
      expect(caja.derecha).toBeLessThanOrEqual(conAviso.derecha + TOLERANCIA)
      expect(caja.arriba).toBeGreaterThanOrEqual(conAviso.arriba - TOLERANCIA)
      expect(caja.abajo).toBeLessThanOrEqual(conAviso.abajo + TOLERANCIA)
    }

    // Criterio 4: ni el bloque ni el aviso ganan scroll, y el texto aprovecha el espacio.
    expect(medidas.recorteZocalo.horizontal).toBeLessThanOrEqual(TOLERANCIA)
    expect(medidas.recorteZocalo.vertical).toBeLessThanOrEqual(TOLERANCIA)
    expect(medidas.recorteSuperficie.horizontal).toBeLessThanOrEqual(TOLERANCIA)
    expect(medidas.recorteSuperficie.vertical).toBeLessThanOrEqual(TOLERANCIA)
    expect(medidas.truncado).toBe('no')
    expect(medidas.tamanoFuente).toBeGreaterThan(14)

    esperarSinScrollGlobal(await medirDocumento(page))
  })

  test(`Zócalo con aviso largo: recorta con elipsis dentro del bloque en ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    // Unos 2.800 caracteres: ni con el cuerpo mínimo entran en un quinto del alto, tampoco a
    // 1920×1080, así que el componente compartido está obligado a recortar.
    const textoLargo = 'Comunicación institucional extensa para la transmisión. '.repeat(50)
    await abrirZocalo(page, viewport, estadoPublico(aviso(textoLargo, 'AMBOS')))
    // El ajuste tipográfico ocurre después del render: se espera su decisión en lugar de
    // leer el atributo una sola vez y medir un estado intermedio.
    await expect(page.getByTestId('aviso-tecnico-zocalo')).toHaveAttribute('data-truncado', 'si')
    const bloque = await cajaZocalo(page)
    const medidas = await medirAviso(page)

    // El bloque no crece por el texto: sigue midiendo un quinto del alto y cuatro quintos
    // del ancho, y el excedente se recorta con `…` visible en lugar de desbordar.
    expect(bloque.ancho / viewport.width).toBeLessThanOrEqual(0.82)
    expect(bloque.alto / viewport.height).toBeLessThanOrEqual(0.22)
    expect(medidas.tamanoFuente).toBeGreaterThanOrEqual(14)
    expect(medidas.recorteSuperficie.vertical).toBeLessThanOrEqual(TOLERANCIA)
    expect(medidas.caja.abajo).toBeLessThanOrEqual(bloque.abajo + TOLERANCIA)
    // El texto autoritativo llega entero al DOM: el recorte es sólo visual.
    await expect(page.getByTestId('texto-aviso')).toHaveText(textoLargo.trim())

    esperarSinScrollGlobal(await medirDocumento(page))
  })

  // ===========================================================================
  // 2. Croma con aviso, sobre la captura real
  // ===========================================================================

  test(`Zócalo con aviso: croma uniforme afuera y ningún píxel confundible adentro en ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    await abrirZocalo(page, viewport, estadoPublico(aviso('Cuarto intermedio', 'RECINTO')))
    await esperarAvisoEnZocalo(page, 'Cuarto intermedio')
    const bloque = await cajaZocalo(page)
    const medidas = await medirAviso(page)
    const imagen = decodificarPng(await page.screenshot())

    // El lienzo sigue declarando el croma canónico y el bloque un fondo opaco.
    expect(medidas.fondoLienzo).toBe('rgb(0, 255, 0)')
    expect(medidas.fondoZocalo).toMatch(/^rgb\(\d+, \d+, \d+\)$/)

    /*
      Criterio 1: fuera del bloque, todo píxel es `#00FF00` opaco. Misma técnica que WP-099:
      paso de 3 px, banda de 3 px de antialiasing alrededor del borde redondeado, y las
      comprobaciones se acumulan para afirmarlas una sola vez fuera del bucle.
    */
    const margen = 3
    const impurezas: string[] = []
    let examinadosFuera = 0
    for (let y = 0; y < imagen.alto; y += 3) {
      for (let x = 0; x < imagen.ancho; x += 3) {
        const dentro =
          x >= bloque.izquierda - margen &&
          x <= bloque.derecha + margen &&
          y >= bloque.arriba - margen &&
          y <= bloque.abajo + margen
        if (dentro) continue
        examinadosFuera += 1
        const pixel = imagen.leer(x, y)
        const esCroma =
          pixel.r === CROMA.r && pixel.g === CROMA.g && pixel.b === CROMA.b && pixel.a === CROMA.a
        if (!esCroma && impurezas.length < 5) {
          impurezas.push(`(${x}, ${y}) = ${describirPixel(pixel)}`)
        }
      }
    }
    expect(examinadosFuera).toBeGreaterThan(10_000)
    expect(impurezas, `píxeles no cromáticos fuera del zócalo: ${impurezas.join('; ')}`).toEqual([])

    /*
      Criterio 2: dentro del bloque —ocupado por el aviso— no hay píxeles que un filtro de
      similitud pueda tomar por croma, ni píxeles traslúcidos. El aviso compartido usa un
      degradado semitransparente, pero se compone sobre el fondo opaco del bloque y nunca
      sobre el verde: esta medición es la que lo demuestra.
    */
    const interior = {
      izquierda: Math.ceil(bloque.izquierda + 8),
      derecha: Math.floor(bloque.derecha - 8),
      arriba: Math.ceil(bloque.arriba + 8),
      abajo: Math.floor(bloque.abajo - 8),
    }
    const sospechosos: string[] = []
    const traslucidos: string[] = []
    let examinadosDentro = 0
    for (let y = interior.arriba; y <= interior.abajo; y += 2) {
      for (let x = interior.izquierda; x <= interior.derecha; x += 2) {
        examinadosDentro += 1
        const pixel = imagen.leer(x, y)
        if (pixel.g >= 140 && pixel.r <= 110 && pixel.b <= 110 && sospechosos.length < 5) {
          sospechosos.push(`(${x}, ${y}) = ${describirPixel(pixel)}`)
        }
        if (pixel.a !== 255 && traslucidos.length < 5) {
          traslucidos.push(`(${x}, ${y}) = ${describirPixel(pixel)}`)
        }
      }
    }
    expect(examinadosDentro).toBeGreaterThan(1_000)
    expect(sospechosos, `píxeles del aviso en rango de croma: ${sospechosos.join('; ')}`).toEqual(
      [],
    )
    expect(traslucidos, `píxeles traslúcidos dentro del zócalo: ${traslucidos.join('; ')}`).toEqual(
      [],
    )
  })
}

// =============================================================================
// 3. Ciclo de vida en vivo
// =============================================================================

test('Zócalo: aparición, reemplazo y retiro del aviso llegan en vivo sin recargar', async ({
  page,
}) => {
  await abrirZocalo(page, RESOLUCIONES[1], estadoPublico(null))
  await expect(page.getByTestId('zocalo-tema')).toHaveText(TEMA_NORMAL)
  await expect(page.getByTestId('aviso-tecnico-zocalo')).toHaveCount(0)

  // Marca de instancia: si la página se recargara, desaparecería.
  await page.evaluate(() => {
    ;(window as unknown as Record<string, unknown>).marcaSinRecarga = 'viva'
  })

  // Aparición.
  await publicarEstado(
    page,
    RUTA_ESTADO_PUBLICO,
    estadoPublico(aviso('Cuarto intermedio', 'RECINTO'), 2),
  )
  await esperarAvisoEnZocalo(page, 'Cuarto intermedio')

  // Reemplazo por otro aviso: el anterior no queda en ningún lado.
  await publicarEstado(
    page,
    RUTA_ESTADO_PUBLICO,
    estadoPublico(aviso('Se reanuda la sesión en instantes', 'AMBOS'), 3),
  )
  await esperarAvisoEnZocalo(page, 'Se reanuda la sesión en instantes')
  await expect(page.getByTestId('zocalo')).not.toContainText('Cuarto intermedio')

  // Retiro, con una votación distinta de la que había antes del aviso: vuelve la vigente.
  await publicarEstado(
    page,
    RUTA_ESTADO_PUBLICO,
    estadoPublico(null, 4, 'Expediente 9012/2026 — Tratamiento posterior al aviso'),
  )
  await expect(page.getByTestId('aviso-tecnico-zocalo')).toHaveCount(0)
  await expect(page.getByTestId('zocalo-tema')).toHaveText(
    'Expediente 9012/2026 — Tratamiento posterior al aviso',
  )
  await expect(page.getByTestId('zocalo-votacion')).toBeVisible()
  await expect(page.getByTestId('zocalo-estado')).toHaveText('Aprobada')
  await expect(page.getByTestId('zocalo')).not.toContainText('Se reanuda la sesión')

  expect(
    await page.evaluate(() => (window as unknown as Record<string, unknown>).marcaSinRecarga),
  ).toBe('viva')
})

// =============================================================================
// 4. Misma proyección autoritativa que la Pantalla del Recinto
// =============================================================================

test('Recinto y Zócalo muestran y retiran el mismo aviso desde la misma proyección', async ({
  browser,
}) => {
  const contexto = await browser.newContext({ viewport: RESOLUCIONES[0] })
  try {
    const recinto = await contexto.newPage()
    const zocalo = await contexto.newPage()
    const inicial = estadoPublico(aviso('Cuarto intermedio', 'RECINTO'))

    await instalarBackend(recinto, { [RUTA_ESTADO_PUBLICO]: inicial })
    await instalarBackend(zocalo, { [RUTA_ESTADO_PUBLICO]: inicial })
    await recinto.goto(URL_RECINTO)
    await zocalo.goto(URL_ZOCALO)

    // Mismo snapshot, mismo aviso en las dos superficies.
    await expect(
      recinto.getByTestId('aviso-tecnico-recinto').getByTestId('texto-aviso'),
    ).toHaveText('Cuarto intermedio')
    await esperarAvisoEnZocalo(zocalo, 'Cuarto intermedio')

    // La misma revisión de reemplazo, publicada por la misma ruta a las dos.
    const reemplazo = estadoPublico(aviso('Se reanuda la sesión en instantes', 'AMBOS'), 2)
    await publicarEstado(recinto, RUTA_ESTADO_PUBLICO, reemplazo)
    await publicarEstado(zocalo, RUTA_ESTADO_PUBLICO, reemplazo)
    await expect(
      recinto.getByTestId('aviso-tecnico-recinto').getByTestId('texto-aviso'),
    ).toHaveText('Se reanuda la sesión en instantes')
    await esperarAvisoEnZocalo(zocalo, 'Se reanuda la sesión en instantes')

    // La misma revisión sin aviso: las dos vuelven a su contenido normal.
    const retiro = estadoPublico(null, 3)
    await publicarEstado(recinto, RUTA_ESTADO_PUBLICO, retiro)
    await publicarEstado(zocalo, RUTA_ESTADO_PUBLICO, retiro)
    await expect(recinto.getByTestId('aviso-tecnico-recinto')).toHaveCount(0)
    await expect(recinto.getByTestId('franja-votacion-quorum')).toBeVisible()
    await expect(zocalo.getByTestId('aviso-tecnico-zocalo')).toHaveCount(0)
    await expect(zocalo.getByTestId('zocalo-tema')).toHaveText(TEMA_NORMAL)
  } finally {
    await contexto.close()
  }
})
