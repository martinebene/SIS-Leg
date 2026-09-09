/**
 * WP-083 — Ajustes de UX de quinta ronda medidos en el navegador.
 *
 * La revisión humana de la quinta ronda cerró cinco correcciones visuales. Tres de ellas
 * son afirmaciones sobre cajas reales y por lo tanto sólo pueden demostrarse acá, porque
 * jsdom no calcula layout ni aplica los `<style scoped>` de un SFC:
 *
 * 1. **Apoyo Técnico.** Ningún encabezado de panel dibuja subtítulo, el primer panel se
 *    titula exactamente `Indicador de transmisión`, la biblioteca se llama
 *    `Avisos precargados` y el campo de segundos es visiblemente más angosto que antes,
 *    pero sigue mostrando dos dígitos sin recortarlos.
 * 2. **Moderación Q3.** La banca `NORMAL` no pinta borde visible, mientras que los demás
 *    estados conservan el suyo, y la tarjeta mide exactamente lo mismo que las otras: el
 *    cambio es de color, no de geometría.
 * 3. **Ninguna de las dos pantallas gana scroll global** por estos cambios.
 *
 * Todo se afirma sobre `getBoundingClientRect`, `scrollWidth`/`clientWidth` y
 * `getComputedStyle`, nunca sobre clases: lo que HUMAN_GATE aprobó es el resultado
 * visible, no una técnica concreta de CSS.
 *
 * La contracara del alcance también se mide: la Pantalla del Recinto no participa de este
 * WP, así que su banca `NORMAL` debe seguir mostrando el borde de la paleta compartida.
 * Esa prueba es la que impide "resolver" Q3 tocando `PALETA_BANCAS`.
 */

import { expect, test, type Page } from '@playwright/test'
import {
  estadoModeracion,
  estadoRecinto,
  estadoTecnico,
  instalarBackend,
  RESOLUCIONES,
  URL_MODERACION,
  URL_RECINTO,
  URL_TECNICO,
} from './soporte/apoyo_tecnico'

/** Título exacto del primer panel técnico según el criterio 2 del WP. */
const TITULO_TRANSMISION = 'Indicador de transmisión'

/** Rótulos exactos de la biblioteca según el criterio 5 del WP. */
const TITULO_BIBLIOTECA = 'Avisos precargados'
const ROTULO_ALTA = 'Nuevo aviso precargado'

/**
 * Ancho máximo tolerado para el campo de segundos, en píxeles CSS.
 *
 * El valor anterior a este WP era `w-20`, es decir 80 px, y la decisión pide un control
 * «visiblemente más angosto». 64 px deja margen para diferencias de redondeo entre
 * plataformas y sigue siendo inequívocamente menor que el ancho que se venía usando: si
 * alguien restituyera `w-20`, o cualquier ancho intermedio que no se note, la prueba falla.
 */
const ANCHO_MAXIMO_CUENTA = 64

/** Cinco encabezados del puesto técnico, en el orden en que los reparte la grilla. */
const PANELES_TECNICOS = [
  { testid: 'panel-transmision', titulo: TITULO_TRANSMISION },
  { testid: 'panel-remapeo-tecnico', titulo: 'Remapeo de dispositivos' },
  { testid: 'panel-biblioteca', titulo: TITULO_BIBLIOTECA },
  { testid: 'panel-avisos', titulo: 'Avisos' },
  { testid: 'panel-eventos-tecnico', titulo: 'Eventos' },
] as const

/** Comprueba que el documento no desborde; definición operativa de "sin scroll global". */
async function esperarSinScrollGlobal(page: Page): Promise<void> {
  const medidas = await page.evaluate(() => ({
    alto: document.documentElement.scrollHeight - document.documentElement.clientHeight,
    ancho: document.documentElement.scrollWidth - document.documentElement.clientWidth,
  }))
  expect(medidas.alto).toBeLessThanOrEqual(1)
  expect(medidas.ancho).toBeLessThanOrEqual(1)
}

// =============================================================================
// 1. Apoyo Técnico: encabezados, microcopy y campo de segundos
// =============================================================================

async function abrirPuestoTecnico(
  page: Page,
  viewport: { width: number; height: number },
): Promise<void> {
  await page.setViewportSize(viewport)
  await instalarBackend(page, {
    '/api/v1/estado/tecnico': estadoTecnico(),
    '/api/v1/estado/moderacion': estadoModeracion(),
  })
  await page.goto(URL_TECNICO)
  await expect(page.getByTestId('grilla-tecnica')).toBeVisible()
  await expect(page.getByTestId('control-transmision')).toBeVisible()
}

for (const viewport of RESOLUCIONES) {
  test(`los encabezados técnicos quedan sin subtítulo en ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    await abrirPuestoTecnico(page, viewport)

    for (const panel of PANELES_TECNICOS) {
      const encabezado = page.getByTestId(panel.testid).locator('header')

      // Criterio 2 y 5: el título es exactamente el aprobado, sin abreviar ni recortar.
      await expect(encabezado.locator('h2')).toHaveText(panel.titulo)

      /*
        Criterio 1: el encabezado ya no contiene ningún párrafo. Se mira el DOM real y no
        una clase, porque lo que la decisión prohíbe es el renglón visible; que se hubiera
        conseguido borrando la prop, ocultándolo con CSS o vaciando el texto es indistinto
        para el operador.
      */
      await expect(encabezado.locator('p')).toHaveCount(0)

      // Y el título entra completo: sin subtítulo, el encabezado tiene todo el alto.
      const recorte = await encabezado
        .locator('h2')
        .evaluate((titulo) => titulo.scrollWidth - titulo.clientWidth)
      expect(recorte, `el título de ${panel.testid} quedó recortado`).toBeLessThanOrEqual(1)
    }

    await esperarSinScrollGlobal(page)
  })

  test(`el campo de segundos es angosto y muestra dos dígitos en ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    await abrirPuestoTecnico(page, viewport)

    const campo = page.getByTestId('input-cuenta-regresiva')

    // Criterio 3: la propuesta inicial es 5 segundos.
    await expect(campo).toHaveValue('5')

    // Criterio 4a: el control es visiblemente más angosto que el ancho anterior.
    const caja = await campo.boundingBox()
    expect(caja).not.toBeNull()
    expect(caja!.width).toBeLessThanOrEqual(ANCHO_MAXIMO_CUENTA)

    /*
      Criterio 4b: dos dígitos entran sin clipping. `scrollWidth - clientWidth` es la
      medida directa de "el contenido no cabe en la caja pintada": si el campo se hubiera
      achicado de más, este número sería positivo. Se prueba con el peor caso de dos
      dígitos, que es el que la decisión humana exige garantizar.
    */
    await campo.fill('99')
    const recorteDosDigitos = await campo.evaluate(
      (entrada) => entrada.scrollWidth - entrada.clientWidth,
    )
    expect(recorteDosDigitos).toBeLessThanOrEqual(1)

    // El campo sigue siendo el mismo control del contrato: acepta todo el rango 1..3600.
    await campo.fill('3600')
    await expect(page.getByTestId('cuenta-invalida')).toHaveCount(0)
    await expect(page.getByTestId('btn-transmision-cuenta')).toBeEnabled()

    // Y su grupo no desborda el panel al que pertenece.
    const cuerpo = await page.evaluate(() => {
      const panel = document.querySelector('[data-testid="panel-transmision"]')!
      const interior = panel.querySelector('[data-testid="cuerpo-panel-tecnico"]')!
      return { scrollWidth: interior.scrollWidth, clientWidth: interior.clientWidth }
    })
    expect(cuerpo.scrollWidth).toBeLessThanOrEqual(cuerpo.clientWidth + 1)

    await esperarSinScrollGlobal(page)
  })

  test(`la biblioteca se lee como avisos precargados en ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    await abrirPuestoTecnico(page, viewport)

    // Criterio 5: título del panel y rótulo del borrador visible.
    await expect(page.getByTestId('panel-biblioteca').locator('h2')).toHaveText(TITULO_BIBLIOTECA)
    await expect(page.locator('label[for="texto-mensaje-nuevo"]')).toHaveText(ROTULO_ALTA)

    // Ningún texto visible del panel vuelve a decir «mensaje precargado».
    const textoPanel = await page
      .getByTestId('panel-biblioteca')
      .evaluate((panel) => (panel as HTMLElement).innerText.toLowerCase())
    expect(textoPanel).not.toContain('mensaje precargado')
    expect(textoPanel).not.toContain('mensajes precargados')

    /*
      Criterio 6: la fila de WP-076 sigue en un solo renglón. El renombre tocó el título
      del panel, no el ancho de la columna, pero es exactamente la clase de cambio que
      podría haberla roto sin que nadie lo advirtiera hasta operar.
    */
    const filas = await page.evaluate(() => {
      const nodos = Array.from(document.querySelectorAll('[data-testid="acciones-mensaje"]'))
      return nodos.map((fila) => {
        const hijos = Array.from(fila.children)
        return {
          altoFila: fila.getBoundingClientRect().height,
          altoMayorHijo: Math.max(...hijos.map((hijo) => hijo.getBoundingClientRect().height)),
        }
      })
    })
    expect(filas.length).toBeGreaterThan(0)
    for (const fila of filas) {
      expect(fila.altoFila).toBeLessThanOrEqual(fila.altoMayorHijo + 1)
    }
  })
}

// =============================================================================
// 2. Moderación Q3: borde invisible sólo en la banca NORMAL
// =============================================================================

/**
 * Estado de Moderación con los estados de banca que este WP debe distinguir.
 *
 * Se parte del mismo snapshot compartido que usan las demás pruebas de navegador y se
 * modifican tres bancas, de modo que la comparación «NORMAL contra el resto» se haga
 * dentro de una misma grilla, con el mismo tamaño de tarjeta y la misma resolución.
 */
function estadoConEstadosDeBanca(): Record<string, unknown> {
  const estado = estadoModeracion() as unknown as Record<string, unknown>
  const concejales = estado.concejales as Record<string, unknown>[]

  // Banca 2 ausente, banca 3 con test de dispositivo activo.
  concejales[1]!.presente = false
  concejales[2]!.test_activo = true
  concejales[2]!.test_expira_en = '2026-09-02T10:00:05Z'

  // Banca 4 en uso de la palabra.
  estado.palabra = {
    orador: {
      dni: concejales[3]!.dni,
      nombre: concejales[3]!.nombre,
      apellido: concejales[3]!.apellido,
      banca: 4,
    },
    cola: [],
  }
  estado.quorum = { cantidad_presentes: 11, requerido: 7, alcanzado: true }
  return estado
}

/** Alfa efectivo de un color CSS resuelto; 0 significa completamente transparente. */
function alfaDe(color: string): number {
  if (color.includes('rgba')) {
    const partes = color.match(/[\d.]+/g) ?? []
    return Number(partes[3] ?? 1)
  }
  return color === 'transparent' ? 0 : 1
}

for (const viewport of RESOLUCIONES) {
  test(`la banca NORMAL de Q3 no dibuja borde en ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport)
    await instalarBackend(page, { '/api/v1/estado/moderacion': estadoConEstadosDeBanca() })
    await page.goto(URL_MODERACION)
    await expect(page.locator('[data-testid="banca-concejal"]').first()).toBeVisible()

    const banca = (numero: number) => `[data-testid="banca-concejal"][data-banca="${numero}"]`

    // Se confirma primero que la grilla contiene los cuatro estados que se comparan.
    await expect(page.locator(banca(1))).toHaveAttribute('data-estado-banca', 'NORMAL')
    await expect(page.locator(banca(2))).toHaveAttribute('data-estado-banca', 'AUSENTE')
    await expect(page.locator(banca(3))).toHaveAttribute('data-estado-banca', 'TEST')
    await expect(page.locator(banca(4))).toHaveAttribute('data-estado-banca', 'PALABRA')

    // WP-090 completa el criterio 7: además del color transparente, el fondo blanco debe
    // terminar en el padding para que no siga apareciendo por debajo del borde real.
    const pinturaNormal = await page.locator(banca(1)).evaluate((elemento) => {
      const estilo = getComputedStyle(elemento)
      return {
        colorBorde: estilo.borderTopColor,
        recorteFondo: estilo.backgroundClip,
      }
    })
    expect(
      alfaDe(pinturaNormal.colorBorde),
      `NORMAL no debería pintar borde: ${pinturaNormal.colorBorde}`,
    ).toBe(0)
    expect(pinturaNormal.recorteFondo).toBe('padding-box')
    await expect(page.locator(`${banca(1)} [data-testid="etiqueta-banca"]`)).toHaveCount(0)

    // Criterio 8: los demás estados conservan un borde opaco.
    for (const numero of [2, 3, 4]) {
      const pintura = await page.locator(banca(numero)).evaluate((elemento) => {
        const estilo = getComputedStyle(elemento)
        return { colorBorde: estilo.borderTopColor, recorteFondo: estilo.backgroundClip }
      })
      expect(
        alfaDe(pintura.colorBorde),
        `la banca ${numero} perdió su borde: ${pintura.colorBorde}`,
      ).toBe(1)
      expect(pintura.recorteFondo).toBe('border-box')
    }

    /*
      Criterio 7, segunda mitad: «sin mover ni escalar la imagen». El borde sigue midiendo
      2 px y las tarjetas siguen siendo del mismo tamaño, de modo que el área útil del
      bitmap es idéntica en NORMAL y en cualquier otro estado. Si alguien hubiera resuelto
      el pedido poniendo `border: none`, las tarjetas NORMAL medirían 4 px menos y esta
      comparación lo delataría.
    */
    const medidas = await page.evaluate(() => {
      const tarjetas = Array.from(
        document.querySelectorAll<HTMLElement>('[data-testid="banca-concejal"]'),
      )
      return tarjetas.map((tarjeta) => {
        const estilo = getComputedStyle(tarjeta)
        const caja = tarjeta.getBoundingClientRect()
        const imagen = tarjeta
          .querySelector('[data-testid="imagen-concejal"], [data-testid="fallback-imagen"]')!
          .getBoundingClientRect()
        return {
          estado: tarjeta.dataset.estadoBanca ?? '',
          anchoBorde: estilo.borderTopWidth,
          ancho: caja.width,
          alto: caja.height,
          anchoImagen: imagen.width,
          altoImagen: imagen.height,
        }
      })
    })

    expect(medidas.length).toBe(12)
    const referencia = medidas[0]!
    for (const tarjeta of medidas) {
      expect(tarjeta.anchoBorde, `${tarjeta.estado} cambió el ancho del borde`).toBe('2px')
      expect(Math.abs(tarjeta.ancho - referencia.ancho)).toBeLessThanOrEqual(1)
      expect(Math.abs(tarjeta.alto - referencia.alto)).toBeLessThanOrEqual(1)
      expect(Math.abs(tarjeta.anchoImagen - referencia.anchoImagen)).toBeLessThanOrEqual(1)
      expect(Math.abs(tarjeta.altoImagen - referencia.altoImagen)).toBeLessThanOrEqual(1)
    }

    await esperarSinScrollGlobal(page)
  })
}

// =============================================================================
// 3. La Pantalla del Recinto no cambia
// =============================================================================

for (const viewport of RESOLUCIONES) {
  test(`la banca NORMAL del Recinto conserva su borde en ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    /*
      Criterio 9. Ésta es la prueba que delimita el WP: Q3 y Recinto comparten la paleta
      `PALETA_BANCAS`, así que la forma más cómoda de apagar el borde de una banca blanca
      habría sido cambiar `PALETA_BANCAS.BLANCO.borde`. Eso habría apagado también el
      borde del Recinto, que este WP debe dejar intacto. Se mide sobre la pantalla real:
      si alguien tomara ese atajo, esta prueba falla aunque las de Q3 pasen.
    */
    await page.setViewportSize(viewport)
    await instalarBackend(page, { '/api/v1/estado/recinto': estadoRecinto() })
    await page.goto(URL_RECINTO)
    await expect(page.locator('[data-testid="banca-publica"]').first()).toBeVisible()

    const primera = page.locator('[data-testid="banca-publica"][data-banca="1"]')
    await expect(primera).toHaveAttribute('data-estado-banca', 'NORMAL')

    const borde = await primera.evaluate((elemento) => {
      const estilo = getComputedStyle(elemento)
      return { color: estilo.borderTopColor, ancho: estilo.borderTopWidth }
    })
    expect(alfaDe(borde.color), `el Recinto perdió el borde de NORMAL: ${borde.color}`).toBe(1)
    expect(borde.ancho).toBe('2px')
  })
}
