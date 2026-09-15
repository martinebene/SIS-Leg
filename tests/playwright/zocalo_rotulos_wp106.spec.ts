/**
 * WP-106 — Zócalo: ancho dinámico de la columna de rótulos.
 *
 * ## Qué problema cubre
 *
 * Hasta WP-106 cada renglón del Zócalo reservaba para su rótulo (`Votación`, `Tema`,
 * `Estado`) un ancho calculado con `clamp(...)` sobre el ancho del viewport. El cuerpo
 * tipográfico del rótulo, en cambio, depende de otras reglas (su propio `clamp` y un techo en
 * `cqh`). Las dos cuentas no crecen igual: en algunas proporciones de frame el ancho
 * reservado quedaba apenas por debajo del texto y `VOTACIÓN` perdía su última letra.
 *
 * La corrección hace que esa columna mida lo que mide el rótulo más largo, en todas las
 * resoluciones, y que la columna de valores ceda exactamente esa diferencia sin agrandar ni
 * mover la placa.
 *
 * ## Qué demuestra este archivo
 *
 * Para cada resolución, en Chromium real:
 *
 * 1. cada `.rotulo` se ve completo: su contenido no es más ancho que su caja;
 * 2. ningún rótulo se parte en dos líneas ni usa puntos suspensivos;
 * 3. la columna de rótulos es **una sola** para las tres filas: los valores empiezan en la
 *    misma coordenada horizontal y esa columna mide lo que mide el rótulo más largo;
 * 4. la placa conserva su geometría exterior (margen izquierdo de 1,5 vw y ancho de 80 vw),
 *    no desborda y no genera desplazamiento horizontal.
 *
 * ## Por qué estas resoluciones
 *
 * - `1280×720` y `1920×1080` son las exigidas por el WP y las más usadas en transmisión.
 * - `1024×768` (4:3) achica el ancho sin achicar tanto el alto: estresa el `clamp` por `vw`.
 * - `2560×1080` (21:9) lleva el cuerpo del rótulo a su techo en `rem` mientras el ancho
 *   reservado anterior también quedaba topado en `9rem`.
 *
 * Con la regla anterior a WP-106 este archivo fallaba en las cuatro resoluciones: en Chromium
 * de pruebas `VOTACIÓN` quedaba recortado entre 14 y 32 px.
 */

import { expect, test, type Page } from '@playwright/test'

import {
  esperarSinScrollGlobal,
  estadoRecinto,
  instalarBackend,
  medirDocumento,
  URL_ZOCALO,
  votacionPublicaCerrada,
} from './soporte/apoyo_tecnico'

/** Ruta de la proyección pública que consume el Zócalo. */
const RUTA_ESTADO_PUBLICO = '/api/v1/estado/recinto'

/** Resoluciones medidas; el motivo de cada una está explicado en la cabecera. */
const RESOLUCIONES_ROTULOS = [
  { width: 1280, height: 720 },
  { width: 1920, height: 1080 },
  { width: 1024, height: 768 },
  { width: 2560, height: 1080 },
] as const

/**
 * Holgura de un píxel para comparaciones geométricas.
 *
 * El navegador resuelve el layout en subpíxeles; un píxel evita falsos rojos por redondeo sin
 * esconder un recorte real, que en este defecto era de varios píxeles.
 */
const TOLERANCIA = 1

/** Snapshot con los tres renglones llenos y conteos visibles: el peor caso de contenido. */
function estadoConResultadoVisible() {
  return {
    ...estadoRecinto(),
    votacion: votacionPublicaCerrada({
      tema: 'Expediente 1234/2026 — Ordenanza de presupuesto general del ejercicio siguiente',
      // Ventana abierta respecto de `generado_en` de la fixture, para que el resultado se vea.
      resultado_visible_hasta: '2026-09-02T10:05:00Z',
    }),
  }
}

/** Abre el Zócalo en la resolución indicada y espera a que llegue el snapshot. */
async function abrirZocalo(page: Page, viewport: { width: number; height: number }) {
  await page.setViewportSize(viewport)
  await instalarBackend(page, { [RUTA_ESTADO_PUBLICO]: estadoConResultadoVisible() })
  await page.goto(URL_ZOCALO)
  await expect(page.getByTestId('zocalo')).toBeVisible()
  await expect(page.getByTestId('zocalo-tema')).not.toHaveText('—')
  // Las mediciones de ancho de texto dependen de la fuente definitiva, no de la de reemplazo.
  await page.evaluate(() => document.fonts.ready)
}

/**
 * Mide, en una sola pasada por el DOM, la placa, los rótulos y dónde empieza cada valor.
 *
 * Se mide sobre el DOM real y no sobre el CSS declarado: lo que importa es qué calculó el
 * navegador, no qué regla se escribió.
 */
async function medirRotulos(page: Page) {
  return page.evaluate(() => {
    const zocalo = document.querySelector('[data-testid="zocalo"]') as HTMLElement
    const caja = zocalo.getBoundingClientRect()

    const renglones = [...zocalo.querySelectorAll<HTMLElement>('.renglon')].map((renglon) => {
      const rotulo = renglon.querySelector('.rotulo') as HTMLElement
      // El primer elemento posterior al rótulo es el valor: el resumen, el tema o la píldora.
      const valor = rotulo.nextElementSibling as HTMLElement
      const estiloRotulo = getComputedStyle(rotulo)
      const cajaRotulo = rotulo.getBoundingClientRect()

      /*
        Ancho que el texto necesita de verdad. `scrollWidth` redondea a entero; un `Range`
        sobre el contenido da el ancho de la tinta en subpíxeles y permite comparar contra
        la columna sin esconder un recorte de menos de un píxel.
      */
      const rango = document.createRange()
      rango.selectNodeContents(rotulo)
      const anchoTexto = rango.getBoundingClientRect().width

      return {
        texto: (rotulo.textContent ?? '').trim(),
        anchoCaja: cajaRotulo.width,
        anchoTexto,
        altoCaja: cajaRotulo.height,
        interlineado: Number.parseFloat(estiloRotulo.lineHeight),
        lineas: new Set([...rango.getClientRects()].map((linea) => Math.round(linea.top))).size,
        recorteHorizontal: rotulo.scrollWidth - rotulo.clientWidth,
        desbordeTexto: estiloRotulo.textOverflow,
        espaciosEnBlanco: estiloRotulo.whiteSpace,
        izquierdaRotulo: cajaRotulo.left,
        derechaRotulo: cajaRotulo.right,
        izquierdaValor: valor.getBoundingClientRect().left,
        recorteRenglon: renglon.scrollWidth - renglon.clientWidth,
      }
    })

    return {
      viewport: { ancho: window.innerWidth, alto: window.innerHeight },
      zocalo: {
        izquierda: caja.left,
        derecha: caja.right,
        ancho: caja.width,
        recorteHorizontal: zocalo.scrollWidth - zocalo.clientWidth,
      },
      renglones,
    }
  })
}

for (const viewport of RESOLUCIONES_ROTULOS) {
  const nombre = `${viewport.width}×${viewport.height}`

  test(`Zócalo: los rótulos se ven completos y en una línea en ${nombre}`, async ({
    page,
  }, info) => {
    await abrirZocalo(page, viewport)
    const medidas = await medirRotulos(page)
    await info.attach(`zocalo-rotulos-${viewport.width}x${viewport.height}.png`, {
      body: await page.screenshot(),
      contentType: 'image/png',
    })

    expect(medidas.renglones.map((renglon) => renglon.texto)).toEqual([
      'Votación',
      'Tema',
      'Estado',
    ])

    for (const renglon of medidas.renglones) {
      // Criterio 1: el contenido no es más ancho que la caja visible del rótulo.
      expect(renglon.recorteHorizontal, `recorte de ${renglon.texto}`).toBeLessThanOrEqual(0)
      expect(renglon.anchoTexto, `ancho de ${renglon.texto}`).toBeLessThanOrEqual(
        renglon.anchoCaja + 0.5,
      )
      // Y la caja del rótulo termina antes de que empiece su valor: no hay solapamiento.
      expect(renglon.derechaRotulo).toBeLessThanOrEqual(renglon.izquierdaValor + TOLERANCIA)

      // Criterio 2: una sola línea, sin puntos suspensivos.
      expect(renglon.espaciosEnBlanco).toBe('nowrap')
      expect(renglon.desbordeTexto).not.toBe('ellipsis')
      expect(renglon.lineas, `líneas de ${renglon.texto}`).toBe(1)
      expect(renglon.altoCaja).toBeLessThanOrEqual(renglon.interlineado * 1.5)

      // El renglón tampoco desborda: la columna de valores cedió el espacio.
      expect(renglon.recorteRenglon).toBeLessThanOrEqual(TOLERANCIA)
    }
  })

  test(`Zócalo: la columna de rótulos es común y se ajusta al más largo en ${nombre}`, async ({
    page,
  }) => {
    await abrirZocalo(page, viewport)
    const medidas = await medirRotulos(page)
    const [primero, ...resto] = medidas.renglones

    /*
      Criterio 3a: divisiones alineadas. Si cada renglón midiera su propio rótulo, `TEMA`
      dejaría su valor mucho más a la izquierda que `VOTACIÓN`. Todas las filas deben
      empezar sus valores en la misma coordenada y sus rótulos en la misma columna.
    */
    for (const renglon of resto) {
      expect(Math.abs(renglon.izquierdaValor - primero!.izquierdaValor)).toBeLessThanOrEqual(
        TOLERANCIA,
      )
      expect(Math.abs(renglon.izquierdaRotulo - primero!.izquierdaRotulo)).toBeLessThanOrEqual(
        TOLERANCIA,
      )
      expect(Math.abs(renglon.anchoCaja - primero!.anchoCaja)).toBeLessThanOrEqual(TOLERANCIA)
    }

    /*
      Criterio 3b: la columna mide lo que mide el rótulo más largo, ni menos (recortaría) ni
      bastante más (robaría espacio a los valores). La cota superior de un píxel es la
      diferencia entre el ancho entero que usa la pista y el ancho en subpíxeles del texto.
    */
    const anchoColumna = primero!.anchoCaja
    const rotuloMasLargo = Math.max(...medidas.renglones.map((renglon) => renglon.anchoTexto))
    expect(anchoColumna).toBeGreaterThanOrEqual(rotuloMasLargo - 0.5)
    expect(anchoColumna).toBeLessThanOrEqual(rotuloMasLargo + TOLERANCIA)
  })

  test(`Zócalo: la placa conserva su geometría exterior en ${nombre}`, async ({ page }) => {
    await abrirZocalo(page, viewport)
    const medidas = await medirRotulos(page)
    const { ancho: anchoFrame } = medidas.viewport

    /*
      Criterio 4: la regla de layout vigente de la placa es `left: 1.5vw` y `width: 80vw`.
      Se compara contra esos valores exactos —y no contra una banda aproximada— porque el WP
      exige que el ancho de los rótulos no pueda agrandar ni mover el bloque en absoluto.
    */
    expect(Math.abs(medidas.zocalo.izquierda - anchoFrame * 0.015)).toBeLessThanOrEqual(TOLERANCIA)
    expect(Math.abs(medidas.zocalo.ancho - anchoFrame * 0.8)).toBeLessThanOrEqual(TOLERANCIA)
    expect(medidas.zocalo.derecha).toBeLessThanOrEqual(anchoFrame + TOLERANCIA)
    expect(medidas.zocalo.recorteHorizontal).toBeLessThanOrEqual(TOLERANCIA)
    esperarSinScrollGlobal(await medirDocumento(page))
  })
}
