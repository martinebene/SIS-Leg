/**
 * WP-097 — Moderación y Recinto optimizados para 1280×720.
 *
 * HUMAN_GATE probó las dos superficies en un monitor de 1280×720 durante la
 * validación de campo y pidió cambios concretos, todos geométricos o
 * tipográficos. Como son cambios que sólo existen cuando un navegador calcula
 * layout, la única forma honesta de demostrarlos es medir cajas y cuerpos reales
 * en las tres resoluciones objetivo: la nueva y las dos que ya estaban.
 *
 * Qué demuestra cada bloque:
 *
 * 1. **Recinto / franja superior.** Los rótulos y valores de `Votación`, `Tema` y
 *    `Estado` duplican aproximadamente su cuerpo sin que la franja crezca ni
 *    aparezca desplazamiento propio.
 * 2. **Recinto / quórum.** El título duplica su cuerpo, el número crece la mitad
 *    y el bloque queda exactamente con esos dos elementos: los textos secundarios
 *    desaparecieron.
 * 3. **Recinto / pedidos de palabra.** El título ocupa el ancho del encabezado en
 *    un solo renglón y un nombre de 18 caracteres entra completo, sin elipsis.
 * 4. **Moderación.** Los cuatro cuadrantes entran completos dentro del viewport,
 *    sin scroll de página, y los controles de operación siguen alcanzables.
 *
 * Las baselines son medidas reales tomadas en Chromium sobre el commit base de
 * este WP (`7118cc7`), con tamaño de raíz de 16 px. Se comparan como proporción y
 * no como píxeles exactos: lo que HUMAN_GATE cerró es «aproximadamente el doble»
 * y «aproximadamente un 50 % más», no un valor concreto.
 */

import { expect, test, type Page } from '@playwright/test'
import {
  esperarSinScrollGlobal,
  estadoModeracion,
  estadoRecinto,
  instalarBackend,
  medirDocumento,
  RESOLUCIONES_SESION,
  URL_MODERACION,
  URL_RECINTO,
  votacionPublicaCerrada,
} from './soporte/apoyo_tecnico'

/**
 * Cuerpos tipográficos medidos en el commit base, en píxeles.
 *
 * `franja` es el cuerpo de los valores de la franja superior y `rotuloFranja` el
 * de sus tres rótulos; `rotuloQuorum` y `numeroQuorum` son los dos elementos que
 * sobreviven en el bloque de quórum.
 */
const BASELINES_WP097 = {
  1920: { franja: 18.56, rotuloFranja: 17.92, rotuloQuorum: 12.48, numeroQuorum: 54.0 },
  1366: { franja: 17.075, rotuloFranja: 16.392, rotuloQuorum: 11.611, numeroQuorum: 38.4 },
  1280: { franja: 16.0, rotuloFranja: 15.36, rotuloQuorum: 10.88, numeroQuorum: 36.0 },
} as const

/**
 * Tolerancia de un píxel para comparaciones de borde.
 *
 * El navegador resuelve el layout en subpíxeles; un píxel de holgura evita falsos
 * rojos sin dejar pasar un corrimiento real, que sería de varios píxeles.
 */
const TOLERANCIA = 1

/**
 * Nombres de exactamente 18 caracteres que deben entrar completos.
 *
 * No son cadenas arbitrarias: son nombres del formato que trae el padrón
 * —mayúscula inicial y minúsculas— elegidos entre los más anchos posibles, con
 * `M`, `W`, `V` y `B`. El requisito humano habla de nombres de hasta 18
 * caracteres, no de 18 mayúsculas seguidas, que sería un caso inexistente.
 */
const NOMBRES_18 = [
  { nombre: 'Maximiliano', apellido: 'Suarez', banca: 1 },
  { nombre: 'Wanda', apellido: 'Von Bismarck', banca: 2 },
  { nombre: 'Maria', apellido: 'Wollenweider', banca: 3 },
] as const

/** Cola larga: obliga a la lista a desplazarse y a mostrar su barra reservada. */
function colaConNombresLargos() {
  return {
    orador: null,
    cola: [
      ...NOMBRES_18,
      { nombre: 'Ana', apellido: 'Gomez', banca: 4 },
      { nombre: 'Roberto Carlos', apellido: 'Villanueva Etchegaray', banca: 5 },
      { nombre: 'Juan', apellido: 'Perez', banca: 6 },
      { nombre: 'Lucia', apellido: 'Fernandez', banca: 7 },
      { nombre: 'Pedro', apellido: 'Martinez', banca: 8 },
    ],
  }
}

/** Abre el Recinto con sesión abierta, votación cerrada y cola de pedidos larga. */
async function abrirRecinto(
  page: Page,
  viewport: { width: number; height: number },
): Promise<void> {
  await page.setViewportSize(viewport)
  const estado = {
    ...estadoRecinto(),
    votacion: votacionPublicaCerrada(),
    palabra: colaConNombresLargos(),
  }
  await instalarBackend(page, { '/api/v1/estado/recinto': estado })
  await page.goto(URL_RECINTO)
  await expect(page.getByTestId('franja-votacion-quorum')).toBeVisible()
  await expect(page.getByTestId('cola-palabra').locator('li').first()).toBeVisible()
}

/**
 * Mide, en una sola pasada por el DOM, todo lo que el WP exige del Recinto.
 *
 * Se leen cuerpos calculados (`getComputedStyle`), cajas reales y la relación
 * `scroll*`/`client*`, que es la definición operativa de «no hay recorte».
 */
async function medirRecinto(page: Page) {
  return page.evaluate(() => {
    /** Datos de una caja concreta, o `null` si el elemento no existe. */
    function medir(selector: string) {
      const elemento = document.querySelector(selector) as HTMLElement | null
      if (!elemento) return null
      const caja = elemento.getBoundingClientRect()
      const estilo = getComputedStyle(elemento)
      return {
        ancho: caja.width,
        alto: caja.height,
        izquierda: caja.left,
        derecha: caja.right,
        cuerpo: Number.parseFloat(estilo.fontSize),
        alturaLinea: Number.parseFloat(estilo.lineHeight),
        recorteHorizontal: elemento.scrollWidth - elemento.clientWidth,
        recorteVertical: elemento.scrollHeight - elemento.clientHeight,
      }
    }

    const panelPalabra = document.querySelector('[data-testid="panel-palabra"]') as HTMLElement
    const encabezado = panelPalabra.querySelector('.encabezado-cola') as HTMLElement

    return {
      franja: medir('[data-testid="franja-votacion-quorum"]')!,
      panelVotacion: medir('[data-testid="votacion-publica"]')!,
      rotulos: [...document.querySelectorAll('.renglon-votacion > strong')].map((rotulo) => {
        const elemento = rotulo as HTMLElement
        return {
          texto: (elemento.textContent ?? '').trim(),
          cuerpo: Number.parseFloat(getComputedStyle(elemento).fontSize),
          recorteHorizontal: elemento.scrollWidth - elemento.clientWidth,
          recorteVertical: elemento.scrollHeight - elemento.clientHeight,
        }
      }),
      resumen: medir('[data-testid="resumen-votacion"]')!,
      tema: medir('[data-testid="tema-votacion"]')!,
      estado: medir('[data-testid="estado-votacion"]')!,
      quorum: medir('[data-testid="panel-quorum"]')!,
      rotuloQuorum: medir('.rotulo-panel')!,
      numeroQuorum: medir('[data-testid="cantidad-presentes"]')!,
      // Los dos textos secundarios que WP-097 eliminó del bloque de quórum.
      detalleQuorum: document.querySelector('.detalle-quorum'),
      estadoQuorum: document.querySelector('[data-testid="estado-quorum"]'),
      textoQuorum: (document.querySelector('[data-testid="panel-quorum"]')?.textContent ?? '')
        .replace(/\s+/g, ' ')
        .trim(),
      panelPalabra: medir('[data-testid="panel-palabra"]')!,
      encabezadoCola: {
        ancho: encabezado.getBoundingClientRect().width,
        alto: encabezado.getBoundingClientRect().height,
        // El contador de pedidos comparte el renglón y lleva su propio relleno:
        // es el elemento que fija el alto mínimo del encabezado.
        altoContador:
          encabezado
            .querySelector('[data-testid="cantidad-pedidos-palabra"]')!
            .getBoundingClientRect().height ?? 0,
      },
      tituloCola: medir('[data-testid="titulo-cola-palabra"]')!,
      lista: medir('[data-testid="cola-palabra"]')!,
      nombres: [...document.querySelectorAll('[data-testid="nombre-cola-palabra"]')].map((nodo) => {
        const elemento = nodo as HTMLElement
        return {
          texto: (elemento.textContent ?? '').replace(/\s+/g, ' ').trim(),
          ancho: elemento.getBoundingClientRect().width,
          recorteHorizontal: elemento.scrollWidth - elemento.clientWidth,
          // Si el nombre pasara a dos renglones, el alto de contenido superaría
          // al visible: el WP exige que siga siendo un único renglón.
          altoVisible: elemento.clientHeight,
          altoContenido: elemento.scrollHeight,
        }
      }),
    }
  })
}

for (const viewport of RESOLUCIONES_SESION) {
  const baseline = BASELINES_WP097[viewport.width as keyof typeof BASELINES_WP097]

  test(`Recinto: la franja duplica su tipografía sin crecer en ${viewport.width}×${viewport.height}`, async ({
    page,
  }, info) => {
    await abrirRecinto(page, viewport)
    const medidas = await medirRecinto(page)
    await info.attach(`recinto-${viewport.width}x${viewport.height}.png`, {
      body: await page.screenshot(),
      contentType: 'image/png',
    })

    /*
      Criterio 1: el alto de la franja es exactamente el que reserva la grilla de
      `PantallaRecinto`, y el panel de votación la llena sin sobrar ni faltar. Es
      la parte «sin aumentar el alto de sus contenedores» del pedido humano.
    */
    const altoReservado = Math.min(Math.max(118, viewport.height * 0.16), 172)
    expect(medidas.franja.alto).toBeCloseTo(altoReservado, 0)
    expect(medidas.panelVotacion.alto).toBeCloseTo(altoReservado, 0)

    // Criterio 2: nada dentro de la franja desborda su propia caja.
    expect(medidas.panelVotacion.recorteVertical).toBe(0)
    expect(medidas.panelVotacion.recorteHorizontal).toBe(0)

    /*
      Criterio 3: los tres valores y los tres rótulos crecieron aproximadamente al
      doble. Se acepta la banda 1,9–2,1 porque el pedido es «aproximadamente» y el
      techo geométrico puede recortar unas centésimas donde la franja es más baja
      en proporción al ancho.
    */
    for (const valor of [medidas.resumen, medidas.tema, medidas.estado]) {
      expect(valor.cuerpo / baseline.franja).toBeGreaterThanOrEqual(1.9)
      expect(valor.cuerpo / baseline.franja).toBeLessThanOrEqual(2.1)
    }
    expect(medidas.rotulos.map((rotulo) => rotulo.texto)).toEqual(['Votación', 'Tema', 'Estado'])
    for (const rotulo of medidas.rotulos) {
      expect(rotulo.cuerpo / baseline.rotuloFranja).toBeGreaterThanOrEqual(1.9)
      expect(rotulo.cuerpo / baseline.rotuloFranja).toBeLessThanOrEqual(2.1)
      // Criterio 4: el rótulo entero entra en su columna; ninguno queda recortado.
      expect(rotulo.recorteHorizontal).toBeLessThanOrEqual(TOLERANCIA)
      expect(rotulo.recorteVertical).toBeLessThanOrEqual(TOLERANCIA)
    }

    /*
      Criterio 5: ningún valor queda recortado en vertical. Es lo que garantiza que
      las mayúsculas acentuadas —`VOTACIÓN`, `SIN VOTACIÓN`— se dibujen enteras y
      no aparezcan «cortadas» como en la captura humana.
    */
    for (const valor of [medidas.resumen, medidas.tema, medidas.estado]) {
      expect(valor.recorteVertical).toBeLessThanOrEqual(TOLERANCIA)
    }

    // Criterio 6: la página no ganó desplazamiento en ningún eje.
    esperarSinScrollGlobal(await medirDocumento(page))
  })

  test(`Recinto: el quórum queda con título y número agrandados en ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    await abrirRecinto(page, viewport)
    const medidas = await medirRecinto(page)

    // Criterio 1: el título duplica su cuerpo y el número crece aproximadamente 50 %.
    expect(medidas.rotuloQuorum.cuerpo / baseline.rotuloQuorum).toBeGreaterThanOrEqual(1.95)
    expect(medidas.rotuloQuorum.cuerpo / baseline.rotuloQuorum).toBeLessThanOrEqual(2.05)
    expect(medidas.numeroQuorum.cuerpo / baseline.numeroQuorum).toBeGreaterThanOrEqual(1.45)
    expect(medidas.numeroQuorum.cuerpo / baseline.numeroQuorum).toBeLessThanOrEqual(1.55)

    /*
      Criterio 2: el bloque quedó exactamente con esos dos elementos. Se comprueba
      por estructura —los nodos eliminados no existen— y por texto, para que no
      alcance con esconderlos.
    */
    expect(medidas.detalleQuorum).toBeNull()
    expect(medidas.estadoQuorum).toBeNull()
    // El texto se compara sin separadores: el título y el número son nodos
    // hermanos sin espacio entre ellos en el marcado.
    expect(medidas.textoQuorum).toBe('Quórum12/12')
    expect(medidas.textoQuorum).not.toContain('Presentes')
    expect(medidas.textoQuorum).not.toContain('requiere')

    // Criterio 3: ni el título ni el número quedan recortados dentro de la caja.
    for (const elemento of [medidas.rotuloQuorum, medidas.numeroQuorum]) {
      expect(elemento.recorteHorizontal).toBeLessThanOrEqual(TOLERANCIA)
      expect(elemento.recorteVertical).toBeLessThanOrEqual(TOLERANCIA)
    }

    // Criterio 4: el bloque sigue dentro de la franja, sin desbordarla.
    expect(medidas.quorum.alto).toBeCloseTo(medidas.franja.alto, 0)
    expect(medidas.quorum.derecha).toBeLessThanOrEqual(medidas.franja.derecha + TOLERANCIA)
  })

  test(`Recinto: los pedidos de palabra admiten nombres de 18 caracteres en ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    await abrirRecinto(page, viewport)
    const medidas = await medirRecinto(page)

    /*
      Criterio 1: el título ocupa el ancho del encabezado en un solo renglón. «Un
      solo renglón» se define como que el encabezado no sea más alto que su propio
      título, que es lo que ocurriría si el texto envolviera.
    */
    expect(medidas.tituloCola.recorteHorizontal).toBeLessThanOrEqual(TOLERANCIA)
    expect(medidas.tituloCola.recorteVertical).toBeLessThanOrEqual(TOLERANCIA)
    // El título ocupa exactamente una línea de texto, no dos.
    expect(medidas.tituloCola.alto).toBeLessThanOrEqual(
      Math.ceil(medidas.tituloCola.alturaLinea) + TOLERANCIA,
    )
    // Y el encabezado completo no es más alto que su elemento más alto, que es el
    // contador: si el título envolviera, el encabezado sumaría otra línea entera.
    expect(medidas.encabezadoCola.alto).toBeLessThanOrEqual(
      Math.max(medidas.tituloCola.alto, medidas.encabezadoCola.altoContador) + TOLERANCIA,
    )
    /*
      Criterio 2: el título usa el ancho disponible y no una fracción menor. El
      resto del encabezado es sólo el contador de pedidos, así que exigir el 75 %
      del ancho deja lugar a ese contador y descarta el título encajonado que
      HUMAN_GATE vio en la captura.
    */
    expect(medidas.tituloCola.ancho / medidas.encabezadoCola.ancho).toBeGreaterThanOrEqual(0.75)

    /*
      Criterio 3: los tres nombres de 18 caracteres se dibujan completos, en una
      sola línea y sin elipsis. Éste es el requisito central del pedido humano.
    */
    const nombresLargos = medidas.nombres.filter((nombre) => nombre.texto.length === 18)
    expect(nombresLargos).toHaveLength(NOMBRES_18.length)
    for (const nombre of nombresLargos) {
      expect(nombre.recorteHorizontal, `«${nombre.texto}» quedó recortado`).toBeLessThanOrEqual(
        TOLERANCIA,
      )
      expect(nombre.altoContenido).toBe(nombre.altoVisible)
    }

    /*
      Criterio 4: la promesa histórica de WP-054 sigue en pie. Un nombre más largo
      que 18 caracteres se recorta con elipsis dentro de la columna y jamás produce
      desplazamiento horizontal.
    */
    expect(medidas.lista.recorteHorizontal).toBe(0)
    expect(medidas.panelPalabra.recorteHorizontal).toBe(0)
    expect(medidas.panelPalabra.recorteVertical).toBe(0)
    esperarSinScrollGlobal(await medirDocumento(page))
  })
}

// =============================================================================
// Moderación
// =============================================================================

/**
 * Controles de operación que deben seguir alcanzables en las tres resoluciones.
 *
 * Se eligieron uno o dos por cuadrante, siempre los que ejecutan la acción
 * principal de su panel: si alguno quedara fuera del viewport o tapado por otro
 * elemento, la pantalla dejaría de ser operable aunque no hubiera scroll.
 */
const CONTROLES_MODERACION = [
  'Cerrar sesión',
  'Editar autoridades',
  'Abrir votación',
  'Cargar',
  'Remapear dispositivo',
] as const

for (const viewport of RESOLUCIONES_SESION) {
  test(`Moderación: los cuatro cuadrantes entran completos en ${viewport.width}×${viewport.height}`, async ({
    page,
  }, info) => {
    await page.setViewportSize(viewport)
    await instalarBackend(page, { '/api/v1/estado/moderacion': estadoModeracion() })
    await page.goto(URL_MODERACION)
    await expect(page.getByTestId('grilla-paneles')).toBeVisible()
    await expect(page.getByTestId('panel-eventos')).toBeVisible()
    await info.attach(`moderacion-${viewport.width}x${viewport.height}.png`, {
      body: await page.screenshot(),
      contentType: 'image/png',
    })

    const medidas = await page.evaluate(() => {
      const grilla = document.querySelector('[data-testid="grilla-paneles"]') as HTMLElement
      return {
        grilla: {
          alto: grilla.getBoundingClientRect().height,
          recorteVertical: grilla.scrollHeight - grilla.clientHeight,
          recorteHorizontal: grilla.scrollWidth - grilla.clientWidth,
        },
        paneles: [...grilla.children].map((panel) => {
          const elemento = panel as HTMLElement
          const caja = elemento.getBoundingClientRect()
          return {
            testid: elemento.getAttribute('data-testid'),
            alto: caja.height,
            ancho: caja.width,
            arriba: caja.top,
            abajo: caja.bottom,
            derecha: caja.right,
            // Un panel que desbordara su celda empujaría a los demás fuera de vista.
            recorteVertical: elemento.scrollHeight - elemento.clientHeight,
          }
        }),
        viewport: { ancho: window.innerWidth, alto: window.innerHeight },
      }
    })

    // Criterio 1: son exactamente cuatro cuadrantes, los cuatro con superficie real.
    expect(medidas.paneles.map((panel) => panel.testid)).toEqual([
      'panel-sesion-votacion',
      'panel-orden-del-dia',
      'panel-recinto-palabra',
      'panel-eventos',
    ])
    for (const panel of medidas.paneles) {
      expect(panel.alto).toBeGreaterThan(0)
      expect(panel.ancho).toBeGreaterThan(0)
      // Criterio 2: cada cuadrante entra completo dentro del viewport visible.
      expect(panel.arriba).toBeGreaterThanOrEqual(-TOLERANCIA)
      expect(panel.abajo).toBeLessThanOrEqual(medidas.viewport.alto + TOLERANCIA)
      expect(panel.derecha).toBeLessThanOrEqual(medidas.viewport.ancho + TOLERANCIA)
      // Criterio 3: ningún cuadrante desborda su celda; el scroll vive adentro.
      expect(panel.recorteVertical).toBe(0)
    }

    // Criterio 4: la grilla no scrollea y la página tampoco.
    expect(medidas.grilla.recorteVertical).toBe(0)
    expect(medidas.grilla.recorteHorizontal).toBe(0)
    esperarSinScrollGlobal(await medirDocumento(page))
  })

  test(`Moderación: los controles siguen alcanzables en ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport)
    await instalarBackend(page, { '/api/v1/estado/moderacion': estadoModeracion() })
    await page.goto(URL_MODERACION)
    await expect(page.getByTestId('grilla-paneles')).toBeVisible()

    for (const rotulo of CONTROLES_MODERACION) {
      const control = page.getByRole('button', { name: rotulo, exact: true }).first()
      await expect(control, `el control «${rotulo}» debe estar visible`).toBeVisible()

      const caja = (await control.boundingBox())!
      // Criterio 1: el control entra entero dentro del viewport, sin recorte.
      expect(caja.x).toBeGreaterThanOrEqual(-TOLERANCIA)
      expect(caja.y).toBeGreaterThanOrEqual(-TOLERANCIA)
      expect(caja.x + caja.width).toBeLessThanOrEqual(viewport.width + TOLERANCIA)
      expect(caja.y + caja.height).toBeLessThanOrEqual(viewport.height + TOLERANCIA)

      /*
        Criterio 2: el control es realmente alcanzable con el cursor. Se comprueba
        preguntando al navegador qué elemento hay en el centro de su caja: si otro
        panel lo tapara, ahí aparecería ese otro elemento y no el botón.
      */
      const alcanzable = await control.evaluate((elemento) => {
        const caja = elemento.getBoundingClientRect()
        const encima = document.elementFromPoint(
          caja.left + caja.width / 2,
          caja.top + caja.height / 2,
        )
        return encima !== null && elemento.contains(encima)
      })
      expect(alcanzable, `el control «${rotulo}» quedó tapado por otro elemento`).toBe(true)
    }
  })
}
