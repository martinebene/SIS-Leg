/**
 * WP-076 — Alineación medida de la fila de acciones de cada mensaje precargado.
 *
 * WP-070 dejó demostrado que la etiqueta de destino y los tres botones entran en un único
 * renglón. Lo que WP-076 agrega es *dónde* queda cada cosa dentro de ese renglón: el
 * destino pegado al borde izquierdo del ancho disponible y las tres acciones agrupadas
 * contra el borde derecho.
 *
 * Esa diferencia es puramente geométrica —la disposición anterior también era una sola
 * fila— así que sólo puede demostrarse midiendo cajas reales en el navegador. Todas las
 * afirmaciones se hacen sobre `getBoundingClientRect`, `scrollWidth` y `clientWidth`: lo
 * que el WP cerró es el resultado visible, no una técnica concreta de CSS.
 *
 * La contraparte estructural, que fija la causa (dos bloques hermanos y el orden interno
 * de las acciones), vive en `apps/tecnico/tests/biblioteca_alineacion_wp076.test.ts`.
 */

import { expect, test, type Page } from '@playwright/test'
import {
  esperarSinScrollGlobal,
  estadoModeracion,
  estadoTecnico,
  instalarBackend,
  medirDocumento,
  RESOLUCIONES,
  URL_TECNICO,
} from './soporte/apoyo_tecnico'

/** Orden exacto de acciones, de izquierda a derecha, dentro del grupo derecho. */
const ROTULOS_ACCIONES = ['Usar en el formulario', 'Editar', 'Eliminar'] as const

/**
 * Tolerancia en píxeles para las comparaciones de borde.
 *
 * El navegador resuelve el layout en subpíxeles y `getBoundingClientRect` devuelve
 * fraccionarios; un píxel de holgura evita falsos rojos sin dejar pasar un corrimiento
 * real, que sería de varios píxeles como mínimo.
 */
const TOLERANCIA = 1

/**
 * Biblioteca con el peor caso de ancho.
 *
 * `MODERACION` es la etiqueta de destino más larga de las tres posibles, y una lista larga
 * garantiza que el panel esté scrolleando verticalmente cuando se mide: si el navegador
 * reservara ancho para la barra de desplazamiento, la fila lo sufriría igual que en
 * producción y el borde derecho se correría.
 */
function bibliotecaAncha() {
  return {
    disponible: true,
    motivo: null,
    detalle: null,
    mensajes: Array.from({ length: 14 }, (_, indice) => ({
      mensaje_id: `m-${indice + 1}`,
      texto: `Mensaje precargado número ${indice + 1} del cuerpo institucional`,
      destino: indice % 2 === 0 ? 'MODERACION' : 'RECINTO',
    })),
  }
}

async function abrirPuestoTecnico(
  page: Page,
  viewport: { width: number; height: number },
): Promise<void> {
  await page.setViewportSize(viewport)
  await instalarBackend(page, {
    '/api/v1/estado/tecnico': estadoTecnico({ biblioteca: bibliotecaAncha() }),
    '/api/v1/estado/moderacion': estadoModeracion(),
  })
  await page.goto(URL_TECNICO)
  await expect(page.getByTestId('grilla-tecnica')).toBeVisible()
  await expect(page.getByTestId('mensaje-precargado').first()).toBeVisible()
}

/**
 * Mide, para cada mensaje precargado, la fila completa y sus dos bloques.
 *
 * Se leen los bordes del contenedor y no un ancho esperado en píxeles: el WP no fija
 * medidas, fija extremos. Así la prueba sigue valiendo si mañana cambia el ancho del panel.
 */
async function medirFilas(page: Page) {
  return page.evaluate(() => {
    const filas = Array.from(document.querySelectorAll('[data-testid="acciones-mensaje"]'))
    return filas.map((fila) => {
      const cajaFila = fila.getBoundingClientRect()
      const destino = fila.querySelector('[data-testid="destino-mensaje"]')!
      const grupo = fila.querySelector('[data-testid="grupo-acciones-mensaje"]')!
      const botones = Array.from(grupo.querySelectorAll('button'))
      return {
        fila: { izquierda: cajaFila.left, derecha: cajaFila.right, alto: cajaFila.height },
        destino: destino.getBoundingClientRect(),
        grupo: grupo.getBoundingClientRect(),
        botones: botones.map((boton) => ({
          rotulo: (boton.textContent ?? '').trim(),
          izquierda: boton.getBoundingClientRect().left,
          derecha: boton.getBoundingClientRect().right,
          alto: boton.getBoundingClientRect().height,
          // Un rótulo recortado se delata comparando el ancho pintado con el necesario.
          recorte: boton.scrollWidth - boton.clientWidth,
        })),
        altoMayorBloque: Math.max(
          destino.getBoundingClientRect().height,
          grupo.getBoundingClientRect().height,
        ),
      }
    })
  })
}

for (const viewport of RESOLUCIONES) {
  test(`el destino queda a la izquierda y las acciones agrupadas a la derecha en ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    await abrirPuestoTecnico(page, viewport)
    const filas = await medirFilas(page)

    expect(filas.length).toBe(14)
    for (const medida of filas) {
      // Criterio 1: la etiqueta de destino arranca en el borde izquierdo disponible.
      expect(medida.destino.left - medida.fila.izquierda).toBeLessThanOrEqual(TOLERANCIA)

      // Criterio 2: el grupo de acciones termina en el borde derecho disponible.
      expect(medida.fila.derecha - medida.grupo.right).toBeLessThanOrEqual(TOLERANCIA)

      /*
        Criterio 3: los dos bloques están realmente separados, no apelmazados a la
        izquierda. Ésta es la afirmación que distingue WP-076 de la disposición anterior:
        antes el hueco entre destino y primer botón era exactamente la separación de 6 px
        de la fila, y todo el sobrante quedaba a la derecha. Ahora el sobrante está en el
        medio, así que el hueco tiene que ser estrictamente mayor que esa separación.
      */
      const huecoCentral = medida.grupo.left - medida.destino.right
      expect(huecoCentral).toBeGreaterThan(6 + TOLERANCIA)
    }
  })

  test(`la fila conserva un solo renglón sin solapamiento ni desborde en ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    await abrirPuestoTecnico(page, viewport)
    const filas = await medirFilas(page)

    expect(filas.length).toBe(14)
    for (const medida of filas) {
      /*
        Definición operativa de "un solo renglón": el contenedor flexible no puede ser más
        alto que su bloque más alto. Si envolviera, sumaría al menos otra altura de bloque
        más la separación, muy por encima del píxel de tolerancia.
      */
      expect(medida.fila.alto).toBeLessThanOrEqual(medida.altoMayorBloque + TOLERANCIA)

      // El grupo tampoco envuelve por dentro: sus tres botones comparten renglón.
      for (const boton of medida.botones) {
        expect(boton.alto).toBeLessThanOrEqual(medida.grupo.height + TOLERANCIA)
      }

      // Criterio 4: orden exacto de las acciones y rótulos completos, sin recorte.
      expect(medida.botones.map((boton) => boton.rotulo)).toEqual([...ROTULOS_ACCIONES])
      for (const boton of medida.botones) expect(boton.recorte).toBeLessThanOrEqual(TOLERANCIA)

      /*
        Criterio 5: sin solapamiento. Cada botón empieza a la derecha del anterior, y el
        primero empieza a la derecha de la etiqueta de destino. Un `justify-end` mal puesto
        o un ancho negociado a la fuerza se manifestaría acá como un borde invertido.
      */
      let bordeAnterior = medida.destino.right
      for (const boton of medida.botones) {
        expect(boton.izquierda).toBeGreaterThanOrEqual(bordeAnterior - TOLERANCIA)
        bordeAnterior = boton.derecha
      }

      // Criterio 6: nada desborda hacia la derecha del renglón que lo contiene.
      expect(bordeAnterior).toBeLessThanOrEqual(medida.fila.derecha + TOLERANCIA)
      expect(medida.destino.left).toBeGreaterThanOrEqual(medida.fila.izquierda - TOLERANCIA)
    }

    // Criterio 7: la página no adquirió scroll horizontal por el cambio de alineación.
    esperarSinScrollGlobal(await medirDocumento(page))
  })
}
