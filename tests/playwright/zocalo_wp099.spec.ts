/**
 * WP-099 — Zócalo para Browser Source de OBS.
 *
 * ## Qué demuestra este archivo
 *
 * Todo lo que el WP exige y que sólo existe cuando un navegador real calcula layout y
 * pinta píxeles:
 *
 * 1. **Geometría.** El bloque está abajo a la izquierda, con margen izquierdo e inferior,
 *    ocupa aproximadamente el 80 % del ancho del frame dejando aproximadamente un 20 %
 *    libre a la derecha, y mide aproximadamente el 20 % del alto.
 * 2. **Sin scroll ni recorte.** Ni la página ni el bloque ganan desplazamiento, y ningún
 *    renglón queda cortado en vertical.
 * 3. **Croma.** Todo lo que no es el zócalo es verde `#00FF00` exacto y opaco, y dentro del
 *    zócalo no hay un solo píxel que ese verde pueda confundir. Es lo que hace utilizable
 *    el filtro de croma de OBS, y se comprueba sobre la captura real, no sobre el CSS.
 * 4. **Actualización en vivo.** Una revisión nueva publicada por el mismo canal SSE cambia
 *    tema y estado sin recargar la página.
 * 5. **Ausencia de controles de operador.**
 *
 * La redacción de los tres renglones no se vuelve a probar acá: vive en
 * `frontend-shared` y la cubren las pruebas unitarias de ese paquete y las del Zócalo.
 *
 * ## Sobre las tolerancias
 *
 * El WP habla de proporciones aproximadas, no de píxeles. Las bandas admitidas son
 * deliberadamente estrechas —dos puntos porcentuales— para que sigan describiendo «cuatro
 * quintos del ancho» y «un quinto del alto» y no cualquier rectángulo grande.
 */

import { expect, test, type Page } from '@playwright/test'

import {
  esperarSinScrollGlobal,
  estadoRecinto,
  instalarBackend,
  medirDocumento,
  publicarEstado,
  URL_ZOCALO,
  votacionPublicaCerrada,
} from './soporte/apoyo_tecnico'
import { decodificarPng, describirPixel } from './soporte/pixeles_png'

/** Ruta de la proyección pública que consume el Zócalo, igual que la del Recinto. */
const RUTA_ESTADO_PUBLICO = '/api/v1/estado/recinto'

/** Las dos resoluciones que el WP exige medir, más la intermedia ya cubierta por WP-097. */
const RESOLUCIONES_ZOCALO = [
  { width: 1920, height: 1080 },
  { width: 1366, height: 768 },
  { width: 1280, height: 720 },
] as const

/** Resoluciones sobre las que se analiza la captura píxel a píxel. */
const RESOLUCIONES_CROMA = [
  { width: 1920, height: 1080 },
  { width: 1280, height: 720 },
] as const

/** Verde de croma canónico exigido por el WP. */
const CROMA = { r: 0, g: 255, b: 0, a: 255 }

/**
 * Tolerancia de un píxel para comparaciones de borde.
 *
 * El navegador resuelve el layout en subpíxeles; un píxel de holgura evita falsos rojos sin
 * dejar pasar un corrimiento real, que sería de varios píxeles.
 */
const TOLERANCIA = 1

/**
 * Ventana de exhibición del resultado, coherente con `generado_en` de la fixture.
 *
 * El reloj de presentación compartido oculta un resultado cuya ventana ya venció. Para
 * medir el peor caso de contenido —tres renglones llenos, con conteos— hace falta que esa
 * ventana siga abierta respecto del instante del snapshot, que es `2026-09-02T10:00:00Z`.
 */
const RESULTADO_VISIBLE_HASTA = '2026-09-02T10:05:00Z'

/** Snapshot con una votación cerrada y su resultado todavía en pantalla. */
function estadoConResultadoVisible(tema: string) {
  return {
    ...estadoRecinto(),
    votacion: votacionPublicaCerrada({
      tema,
      resultado_visible_hasta: RESULTADO_VISIBLE_HASTA,
    }),
  }
}

/** Abre el Zócalo en la resolución indicada y espera a que el bloque esté dibujado. */
async function abrirZocalo(
  page: Page,
  viewport: { width: number; height: number },
  estado: unknown = estadoConResultadoVisible(
    'Expediente 1234/2026 — Ordenanza de presupuesto general del ejercicio siguiente',
  ),
): Promise<void> {
  await page.setViewportSize(viewport)
  await instalarBackend(page, { [RUTA_ESTADO_PUBLICO]: estado })
  await page.goto(URL_ZOCALO)
  await expect(page.getByTestId('zocalo')).toBeVisible()
  // El texto del tema confirma que ya llegó el snapshot y que no se está midiendo el
  // estado neutro previo a la primera revisión.
  await expect(page.getByTestId('zocalo-tema')).not.toHaveText('—')
}

/** Mide, en una sola pasada por el DOM, todo lo que el WP exige del Zócalo. */
async function medirZocalo(page: Page) {
  return page.evaluate(() => {
    const zocalo = document.querySelector('[data-testid="zocalo"]') as HTMLElement
    const caja = zocalo.getBoundingClientRect()

    /** Datos de un renglón concreto: cuerpo, recortes y si entra en una sola línea. */
    function medirTexto(testid: string) {
      const elemento = document.querySelector(`[data-testid="${testid}"]`) as HTMLElement | null
      if (!elemento) return null
      const estilo = getComputedStyle(elemento)
      const propia = elemento.getBoundingClientRect()
      return {
        texto: (elemento.textContent ?? '').replace(/\s+/g, ' ').trim(),
        cuerpo: Number.parseFloat(estilo.fontSize),
        color: estilo.color,
        fondo: estilo.backgroundColor,
        arriba: propia.top,
        abajo: propia.bottom,
        izquierda: propia.left,
        derecha: propia.right,
        recorteHorizontal: elemento.scrollWidth - elemento.clientWidth,
        recorteVertical: elemento.scrollHeight - elemento.clientHeight,
      }
    }

    const estiloZocalo = getComputedStyle(zocalo)
    const raiz = document.documentElement

    return {
      viewport: { ancho: window.innerWidth, alto: window.innerHeight },
      zocalo: {
        izquierda: caja.left,
        derecha: caja.right,
        arriba: caja.top,
        abajo: caja.bottom,
        ancho: caja.width,
        alto: caja.height,
        fondo: estiloZocalo.backgroundColor,
        recorteHorizontal: zocalo.scrollWidth - zocalo.clientWidth,
        recorteVertical: zocalo.scrollHeight - zocalo.clientHeight,
      },
      fondoLienzo: getComputedStyle(
        document.querySelector('[data-testid="lienzo-chroma"]') as HTMLElement,
      ).backgroundColor,
      fondoCuerpo: getComputedStyle(document.body).backgroundColor,
      fondoRaiz: getComputedStyle(raiz).backgroundColor,
      rotulos: [...document.querySelectorAll('.rotulo')].map((nodo) =>
        (nodo.textContent ?? '').trim(),
      ),
      votacion: medirTexto('zocalo-votacion')!,
      tema: medirTexto('zocalo-tema')!,
      estado: medirTexto('zocalo-estado')!,
      detalle: medirTexto('zocalo-detalle-estado'),
      interactivos: document.querySelectorAll(
        'button, input, select, textarea, a, form, [role], [contenteditable], [tabindex]',
      ).length,
    }
  })
}

// =============================================================================
// 1. Geometría, legibilidad y ausencia de recorte
// =============================================================================

for (const viewport of RESOLUCIONES_ZOCALO) {
  test(`Zócalo: geometría inferior izquierda de 80 %×20 % en ${viewport.width}×${viewport.height}`, async ({
    page,
  }, info) => {
    await abrirZocalo(page, viewport)
    const medidas = await medirZocalo(page)
    await info.attach(`zocalo-${viewport.width}x${viewport.height}.png`, {
      body: await page.screenshot(),
      contentType: 'image/png',
    })

    const { ancho: anchoFrame, alto: altoFrame } = medidas.viewport

    // Criterio 1: el bloque vive en el cuadrante inferior izquierdo del frame.
    expect(medidas.zocalo.izquierda).toBeLessThan(anchoFrame / 2)
    expect(medidas.zocalo.arriba).toBeGreaterThan(altoFrame / 2)

    /*
      Criterio 2: hay un margen izquierdo e inferior real, pero pequeño. «Real» es mayor que
      cero —el WP pide no quedar pegado al borde— y «pequeño» es a lo sumo un 5 % del frame,
      que a 1280×720 son 64 px de ancho y 36 px de alto.
    */
    const margenInferior = altoFrame - medidas.zocalo.abajo
    expect(medidas.zocalo.izquierda).toBeGreaterThan(0)
    expect(medidas.zocalo.izquierda).toBeLessThanOrEqual(anchoFrame * 0.05)
    expect(margenInferior).toBeGreaterThan(0)
    expect(margenInferior).toBeLessThanOrEqual(altoFrame * 0.05)

    // Criterio 3: cuatro quintos del ancho, un quinto del alto.
    expect(medidas.zocalo.ancho / anchoFrame).toBeGreaterThanOrEqual(0.78)
    expect(medidas.zocalo.ancho / anchoFrame).toBeLessThanOrEqual(0.82)
    expect(medidas.zocalo.alto / altoFrame).toBeGreaterThanOrEqual(0.18)
    expect(medidas.zocalo.alto / altoFrame).toBeLessThanOrEqual(0.22)

    /*
      Criterio 4: queda aproximadamente un quinto del ancho libre a la derecha. No puede ser
      exactamente el 20 % porque el margen izquierdo también consume ancho; la banda admitida
      refleja esa aritmética sin desnaturalizar la proporción pedida.
    */
    const libreDerecha = (anchoFrame - medidas.zocalo.derecha) / anchoFrame
    expect(libreDerecha).toBeGreaterThanOrEqual(0.15)
    expect(libreDerecha).toBeLessThanOrEqual(0.22)

    // Criterio 5: el bloque entra entero dentro del frame capturado.
    expect(medidas.zocalo.derecha).toBeLessThanOrEqual(anchoFrame + TOLERANCIA)
    expect(medidas.zocalo.abajo).toBeLessThanOrEqual(altoFrame + TOLERANCIA)
  })

  test(`Zócalo: los tres renglones entran sin recorte en ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    await abrirZocalo(page, viewport)
    const medidas = await medirZocalo(page)

    // Criterio 1: están los tres rótulos exigidos, en su orden canónico.
    expect(medidas.rotulos).toEqual(['Votación', 'Tema', 'Estado'])

    // Criterio 2: el bloque no desborda su propia caja en ningún eje.
    expect(medidas.zocalo.recorteHorizontal).toBeLessThanOrEqual(TOLERANCIA)
    expect(medidas.zocalo.recorteVertical).toBeLessThanOrEqual(TOLERANCIA)

    /*
      Criterio 3: ningún valor queda cortado en vertical. Es lo que garantiza que las
      mayúsculas acentuadas —`VOTACIÓN`— se dibujen enteras dentro de su renglón.
    */
    for (const renglon of [medidas.votacion, medidas.tema, medidas.estado]) {
      expect(renglon.recorteVertical).toBeLessThanOrEqual(TOLERANCIA)
      // Criterio 4: y todos quedan dentro del bloque, sin asomar por arriba ni por abajo.
      expect(renglon.arriba).toBeGreaterThanOrEqual(medidas.zocalo.arriba - TOLERANCIA)
      expect(renglon.abajo).toBeLessThanOrEqual(medidas.zocalo.abajo + TOLERANCIA)
      expect(renglon.derecha).toBeLessThanOrEqual(medidas.zocalo.derecha + TOLERANCIA)
    }

    /*
      Criterio 5: legibilidad mínima en la resolución más chica. Doce píxeles es el umbral
      por debajo del cual un texto deja de leerse en una transmisión reescalada; los cuerpos
      reales quedan bien por encima, pero el piso evita que un cambio futuro los achique sin
      que nadie lo note.
    */
    for (const renglon of [medidas.votacion, medidas.tema, medidas.estado]) {
      expect(renglon.cuerpo).toBeGreaterThanOrEqual(12)
    }

    // Criterio 6: la página no ganó desplazamiento en ningún eje.
    esperarSinScrollGlobal(await medirDocumento(page))
  })

  test(`Zócalo: un tema largo se recorta con elipsis y no ensancha el bloque en ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    await abrirZocalo(
      page,
      viewport,
      estadoConResultadoVisible(
        `Expediente 9999/2026 — ${'Texto deliberadamente extenso '.repeat(12)}`,
      ),
    )
    const medidas = await medirZocalo(page)

    // El ancho sigue siendo el pedido por el WP: el texto se recorta, la caja no crece.
    expect(medidas.zocalo.ancho / medidas.viewport.ancho).toBeLessThanOrEqual(0.82)
    expect(medidas.zocalo.derecha).toBeLessThanOrEqual(medidas.viewport.ancho + TOLERANCIA)
    // El renglón tiene más contenido que ancho visible: eso es exactamente la elipsis.
    expect(medidas.tema.recorteHorizontal).toBeGreaterThan(0)
    expect(medidas.tema.recorteVertical).toBeLessThanOrEqual(TOLERANCIA)
    esperarSinScrollGlobal(await medirDocumento(page))
  })
}

// =============================================================================
// 2. Croma sobre la captura real
// =============================================================================

for (const viewport of RESOLUCIONES_CROMA) {
  test(`Zócalo: croma uniforme y opaco alrededor del bloque en ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    await abrirZocalo(page, viewport)
    const medidas = await medirZocalo(page)
    const imagen = decodificarPng(await page.screenshot())

    expect(imagen.ancho).toBe(viewport.width)
    expect(imagen.alto).toBe(viewport.height)

    /*
      Criterio 1: cada píxel fuera del bloque es exactamente `#00FF00` y completamente
      opaco. Se recorre todo el frame con paso de 3 px —unos 230.000 píxeles a 1920×1080—
      saltando una banda de 3 px alrededor del bloque, que es donde el antialiasing del borde
      redondeado mezcla legítimamente los dos colores.

      Un solo píxel distinto basta para fallar: un degradado, una sombra o un fondo
      semitransparente aparecerían justamente así, como una franja de valores intermedios
      que el filtro de croma de OBS no puede recortar limpio.
    */
    /*
      Las comprobaciones se acumulan en listas y se afirman **una sola vez** al final. No es
      un detalle de estilo: llamar a `expect` cientos de miles de veces dentro del bucle
      convierte un recorrido de milisegundos en varios minutos y, como el bucle es síncrono,
      bloquea el temporizador con el que Playwright corta una prueba colgada.
    */
    const margenAntialiasing = 3
    const bloque = {
      izquierda: medidas.zocalo.izquierda - margenAntialiasing,
      derecha: medidas.zocalo.derecha + margenAntialiasing,
      arriba: medidas.zocalo.arriba - margenAntialiasing,
      abajo: medidas.zocalo.abajo + margenAntialiasing,
    }

    const impurezas: string[] = []
    let examinadosFuera = 0
    for (let y = 0; y < imagen.alto; y += 3) {
      for (let x = 0; x < imagen.ancho; x += 3) {
        const dentroDelBloque =
          x >= bloque.izquierda && x <= bloque.derecha && y >= bloque.arriba && y <= bloque.abajo
        if (dentroDelBloque) continue
        examinadosFuera += 1
        const pixel = imagen.leer(x, y)
        if (
          pixel.r !== CROMA.r ||
          pixel.g !== CROMA.g ||
          pixel.b !== CROMA.b ||
          pixel.a !== CROMA.a
        ) {
          if (impurezas.length < 5) impurezas.push(`(${x}, ${y}) = ${describirPixel(pixel)}`)
        }
      }
    }

    expect(examinadosFuera).toBeGreaterThan(10_000)
    expect(impurezas, `píxeles no cromáticos fuera del zócalo: ${impurezas.join('; ')}`).toEqual([])

    /*
      Criterio 2: dentro del bloque no hay ningún píxel que el filtro pueda confundir con el
      croma. El criterio operativo es el mismo que usa un filtro de similitud: se rechaza
      todo píxel muy verde y poco rojo y azul. Incluye deliberadamente al verde oscuro, que
      es el color con el que la Pantalla del Recinto pinta «Aprobada» y que acá se sustituyó
      por cian justamente por esto.
    */
    const interior = {
      izquierda: Math.ceil(medidas.zocalo.izquierda + 8),
      derecha: Math.floor(medidas.zocalo.derecha - 8),
      arriba: Math.ceil(medidas.zocalo.arriba + 8),
      abajo: Math.floor(medidas.zocalo.abajo - 8),
    }

    const sospechosos: string[] = []
    const traslucidos: string[] = []
    let examinadosDentro = 0
    for (let y = interior.arriba; y <= interior.abajo; y += 2) {
      for (let x = interior.izquierda; x <= interior.derecha; x += 2) {
        examinadosDentro += 1
        const pixel = imagen.leer(x, y)
        const esVerdeConfundible = pixel.g >= 140 && pixel.r <= 110 && pixel.b <= 110
        if (esVerdeConfundible && sospechosos.length < 5) {
          sospechosos.push(`(${x}, ${y}) = ${describirPixel(pixel)}`)
        }
        if (pixel.a !== 255 && traslucidos.length < 5) {
          traslucidos.push(`(${x}, ${y}) = ${describirPixel(pixel)}`)
        }
      }
    }

    expect(examinadosDentro).toBeGreaterThan(1_000)
    expect(
      sospechosos,
      `píxeles del zócalo dentro del rango del croma: ${sospechosos.join('; ')}`,
    ).toEqual([])
    // Criterio 3: el interior del zócalo es completamente opaco.
    expect(traslucidos, `píxeles traslúcidos dentro del zócalo: ${traslucidos.join('; ')}`).toEqual(
      [],
    )
  })

  test(`Zócalo: el bloque declara un fondo opaco y el lienzo el croma canónico en ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    await abrirZocalo(page, viewport)
    const medidas = await medirZocalo(page)

    // El croma se declara en el lienzo y también en la raíz del documento, para que el
    // primer frame ya sea verde aunque el CSS de la aplicación todavía no haya llegado.
    expect(medidas.fondoLienzo).toBe('rgb(0, 255, 0)')
    expect(medidas.fondoCuerpo).toBe('rgb(0, 255, 0)')
    expect(medidas.fondoRaiz).toBe('rgb(0, 255, 0)')

    // `rgb(...)` sin cuarto componente es exactamente lo que el navegador devuelve para un
    // color opaco: si alguien introdujera transparencia aparecería `rgba(...)`.
    expect(medidas.zocalo.fondo).toMatch(/^rgb\(\d+, \d+, \d+\)$/)
    expect(medidas.zocalo.fondo).not.toBe('rgb(0, 255, 0)')
    expect(medidas.estado.fondo).toMatch(/^rgb\(\d+, \d+, \d+\)$/)
  })
}

// =============================================================================
// 3. Actualización en vivo desde la fuente autoritativa
// =============================================================================

test('Zócalo: adopta en vivo una revisión nueva sin recargar la página', async ({ page }) => {
  await abrirZocalo(page, RESOLUCIONES_CROMA[0], {
    ...estadoRecinto(),
    votacion: votacionPublicaCerrada({
      tema: 'Expediente 1111/2026 — Primer tratamiento',
      estado_recepcion: 'EN_CURSO',
      resultado: null,
      conteos: null,
    }),
  })

  await expect(page.getByTestId('zocalo-tema')).toHaveText(
    'Expediente 1111/2026 — Primer tratamiento',
  )
  await expect(page.getByTestId('zocalo-estado')).toHaveText('En curso')
  // Con la recepción abierta rige el secreto del voto: no puede haber conteos a la vista.
  await expect(page.getByTestId('zocalo-detalle-estado')).toHaveCount(0)

  // Marca de la instancia de la aplicación: si la página se recargara, este objeto
  // desaparecería y la comprobación final lo delataría.
  await page.evaluate(() => {
    ;(window as unknown as Record<string, unknown>).marcaSinRecarga = 'viva'
  })

  await publicarEstado(page, RUTA_ESTADO_PUBLICO, {
    ...estadoRecinto(),
    revision: 2,
    votacion: votacionPublicaCerrada({
      tema: 'Expediente 2222/2026 — Segundo tratamiento',
      resultado_visible_hasta: RESULTADO_VISIBLE_HASTA,
    }),
  })

  await expect(page.getByTestId('zocalo-tema')).toHaveText(
    'Expediente 2222/2026 — Segundo tratamiento',
  )
  await expect(page.getByTestId('zocalo-estado')).toHaveText('Aprobada')
  await expect(page.getByTestId('zocalo-detalle-estado')).toHaveText(
    'Positivos 8 · Negativos 3 · Abstenciones 1 · Total 12',
  )
  // El tema anterior no quedó en ningún lado: la superficie no acumula historia.
  await expect(page.getByTestId('zocalo')).not.toContainText('Expediente 1111/2026')

  expect(
    await page.evaluate(() => (window as unknown as Record<string, unknown>).marcaSinRecarga),
  ).toBe('viva')
})

test('Zócalo: vuelve al texto neutro si el backend deja de publicar votación', async ({ page }) => {
  await abrirZocalo(page, RESOLUCIONES_CROMA[0])
  await expect(page.getByTestId('zocalo-tema')).not.toHaveText('—')

  await publicarEstado(page, RUTA_ESTADO_PUBLICO, {
    ...estadoRecinto(),
    revision: 3,
    votacion: null,
  })

  await expect(page.getByTestId('zocalo-votacion')).toHaveText('Sin votación activa')
  await expect(page.getByTestId('zocalo-tema')).toHaveText('—')
  await expect(page.getByTestId('zocalo-estado')).toHaveText('Sin votación')
})

// =============================================================================
// 4. Superficie de solo lectura
// =============================================================================

test('Zócalo: no expone ningún control de operador', async ({ page }) => {
  await abrirZocalo(page, RESOLUCIONES_CROMA[1])
  const medidas = await medirZocalo(page)

  // Se cuentan todas las formas de interacción posibles, no sólo los botones: enlaces,
  // formularios, campos, roles ARIA y cualquier elemento enfocable por tabulación.
  expect(medidas.interactivos).toBe(0)
  // Y tampoco hay rastro textual de una acción: el Zócalo no pide nada a nadie.
  await expect(page.getByRole('button')).toHaveCount(0)
  await expect(page.getByRole('link')).toHaveCount(0)
})
