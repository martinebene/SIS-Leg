/**
 * WP-070 — Microcopy y geometría operativa medidas en el navegador.
 *
 * El WP cerró tres correcciones de uso humano y las tres sólo pueden demostrarse sobre
 * cajas reales, porque jsdom no calcula layout:
 *
 * 1. **Moderación.** Antes de PREPARANDO, el impedimento para cargar el Orden del Día
 *    dice exactamente el texto aprobado y el cuadrante no gana desborde por eso.
 * 2. **Apoyo Técnico.** En cada mensaje precargado, la etiqueta de destino y los tres
 *    botones entran en un único renglón a 1366×768 y a 1920×1080, sin recortar rótulos,
 *    sin desbordar el panel y sin scroll global. El resto de la grilla técnica conserva su
 *    reparto y no adquiere scroll nuevo.
 * 3. **Recinto.** Con la vista desactualizada el indicador dice exactamente
 *    `(Sin conexion)` y la cabecera sigue en un solo renglón, con su altura vigente.
 *
 * Todas las afirmaciones se hacen sobre `getBoundingClientRect`, `scrollWidth` y
 * `clientWidth`: lo que el WP cerró es el resultado visible, no una técnica concreta de
 * CSS. Una prueba que mirara clases dejaría pasar exactamente la regresión que importa.
 */

import { expect, test, type Page } from '@playwright/test'
import {
  esperarSinScrollGlobal,
  estadoModeracion,
  estadoRecinto,
  estadoTecnico,
  instalarBackend,
  medirDocumento,
  RESOLUCIONES,
  URL_RECINTO,
  URL_TECNICO,
} from './soporte/apoyo_tecnico'
import { instalarFotosConcejales } from './soporte/fotos_concejales'

/** Texto exacto aprobado por HUMAN_GATE para el impedimento de carga. */
const TEXTO_ORDEN_DEL_DIA = 'Debe comenzar a preparar el recinto antes de cargar el orden del dia'

/** Texto exacto aprobado por HUMAN_GATE para la vista desactualizada del Recinto. */
const TEXTO_DESACTUALIZADO = '(Sin conexion)'

/** Rótulos que la decisión humana enumera y que no pueden abreviarse ni recortarse. */
const ROTULOS_ACCIONES = ['Usar en el formulario', 'Editar', 'Eliminar'] as const

// =============================================================================
// 1. Apoyo Técnico: destino + tres acciones en una sola fila
// =============================================================================

/**
 * Biblioteca con el peor caso de ancho.
 *
 * `MODERACION` es la etiqueta de destino más larga de las tres posibles, y una lista
 * larga garantiza que el panel esté scrolleando cuando se mide: si el navegador reservara
 * ancho para la barra de desplazamiento, la fila lo sufriría igual que en producción.
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

for (const viewport of RESOLUCIONES) {
  test(`la fila de destino y acciones no envuelve en ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    await abrirPuestoTecnico(page, viewport)

    /*
      Definición operativa de "una sola fila": el contenedor flexible no puede ser más
      alto que su hijo más alto. Si envolviera, sumaría al menos otra altura de botón más
      la separación, y la diferencia sería mucho mayor que el píxel de tolerancia.
    */
    const medidas = await page.evaluate(() => {
      const filas = Array.from(document.querySelectorAll('[data-testid="acciones-mensaje"]'))
      return filas.map((fila) => {
        const hijos = Array.from(fila.children)
        const altoFila = fila.getBoundingClientRect().height
        const altoMayorHijo = Math.max(...hijos.map((hijo) => hijo.getBoundingClientRect().height))
        const derechaHijo = Math.max(...hijos.map((hijo) => hijo.getBoundingClientRect().right))
        return {
          altoFila,
          altoMayorHijo,
          derechaHijo,
          derechaFila: fila.getBoundingClientRect().right,
          // Un rótulo recortado se delata comparando el ancho pintado con el necesario.
          recortes: hijos.map((hijo) => hijo.scrollWidth - hijo.clientWidth),
          rotulos: Array.from(fila.querySelectorAll('button')).map((boton) =>
            (boton.textContent ?? '').trim(),
          ),
        }
      })
    })

    expect(medidas.length).toBe(14)
    for (const fila of medidas) {
      expect(fila.altoFila).toBeLessThanOrEqual(fila.altoMayorHijo + 1)
      // Ningún elemento desborda hacia la derecha del renglón que lo contiene.
      expect(fila.derechaHijo).toBeLessThanOrEqual(fila.derechaFila + 1)
      // Criterio 4: los rótulos siguen completos y sin recorte horizontal.
      for (const recorte of fila.recortes) expect(recorte).toBeLessThanOrEqual(1)
      expect(fila.rotulos).toEqual([...ROTULOS_ACCIONES])
    }
  })

  test(`el panel de Mensajes gana sólo el ancho necesario en ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    await abrirPuestoTecnico(page, viewport)

    const cajas = await page.evaluate(() => {
      const leer = (testid: string) => {
        const nodo = document.querySelector(`[data-testid="${testid}"]`)!
        const caja = nodo.getBoundingClientRect()
        const cuerpo = nodo.querySelector('[data-testid="cuerpo-panel-tecnico"]')
        return {
          x: caja.x,
          width: caja.width,
          cuerpo: cuerpo
            ? {
                scrollWidth: cuerpo.scrollWidth,
                clientWidth: cuerpo.clientWidth,
                scrollHeight: cuerpo.scrollHeight,
                clientHeight: cuerpo.clientHeight,
              }
            : null,
        }
      }
      return {
        grilla: leer('grilla-tecnica'),
        transmision: leer('panel-transmision'),
        remapeo: leer('panel-remapeo-tecnico'),
        biblioteca: leer('panel-biblioteca'),
        eventos: leer('panel-eventos-tecnico'),
      }
    })

    // Criterio 5: Mensajes es más ancho que sus dos vecinos, pero no los duplica.
    expect(cajas.biblioteca.width).toBeGreaterThan(cajas.transmision.width)
    expect(cajas.biblioteca.width).toBeLessThan(cajas.transmision.width * 1.5)
    expect(Math.abs(cajas.transmision.width - cajas.remapeo.width)).toBeLessThanOrEqual(2)

    // El reparto global que cerró WP-059 sigue en pie: Eventos conserva su tercio.
    const proporcionEventos = cajas.eventos.width / cajas.grilla.width
    expect(proporcionEventos).toBeGreaterThan(0.29)
    expect(proporcionEventos).toBeLessThan(0.38)

    /*
      Criterio 6: los demás paneles no sufren regresión material. La comprobación es que
      ninguno adquirió scroll horizontal —que sería la forma en que un panel más angosto
      empieza a recortar contenido— y que Transmisión y Remapeo siguen sin scroll vertical,
      igual que antes del cambio de anchos.
    */
    for (const panel of [cajas.transmision, cajas.remapeo, cajas.eventos, cajas.biblioteca]) {
      expect(panel.cuerpo!.scrollWidth).toBeLessThanOrEqual(panel.cuerpo!.clientWidth + 1)
    }
    for (const panel of [cajas.transmision, cajas.remapeo]) {
      expect(panel.cuerpo!.scrollHeight).toBeLessThanOrEqual(panel.cuerpo!.clientHeight + 1)
    }

    esperarSinScrollGlobal(await medirDocumento(page))
  })
}

// =============================================================================
// 2. Recinto: aviso corto de vista desactualizada
// =============================================================================

/**
 * Doble de backend que entrega un snapshot y después corta el stream para siempre.
 *
 * Es la única forma de reproducir en el navegador el estado que le interesa a este WP: el
 * Recinto conserva una vista ya recibida mientras el transporte no consigue reconectar,
 * que es exactamente cuando el composable marca `desactualizado`. Los reintentos
 * posteriores fallan a propósito, para que el indicador no vuelva solo a "En línea" en
 * medio de la medición.
 */
async function instalarBackendQueSeCae(page: Page, estado: unknown): Promise<void> {
  // WP-098: la fotografía de banca ya no es un asset del build; la publica
  // el backend desde la configuración local. Sin backend real, se responde
  // desde la plantilla versionada, que es el mismo archivo de siempre.
  await instalarFotosConcejales(page)

  await page.addInitScript((snapshot) => {
    type Escucha = (evento: { type: string; data?: string }) => void
    let yaEntregoUnSnapshot = false

    class FuenteQueSeCae {
      cerrada = false
      onopen: Escucha | null = null
      onerror: Escucha | null = null
      onmessage: Escucha | null = null
      escuchas: Record<string, Escucha[]> = {}

      constructor(readonly url: string) {
        setTimeout(() => {
          if (this.cerrada) return
          this.onopen?.({ type: 'open' })
          if (yaEntregoUnSnapshot) {
            // Reintento posterior: el stream vuelve a caerse sin entregar nada.
            this.onerror?.({ type: 'error' })
            return
          }
          for (const escuchar of this.escuchas.estado ?? []) {
            escuchar({ type: 'estado', data: JSON.stringify(snapshot) })
          }
          yaEntregoUnSnapshot = true
          // Un tick después se corta la conexión: la vista queda viva pero vieja.
          setTimeout(() => this.onerror?.({ type: 'error' }), 20)
        }, 10)
      }

      addEventListener(tipo: string, escuchar: Escucha): void {
        this.escuchas[tipo] = this.escuchas[tipo] ?? []
        this.escuchas[tipo]?.push(escuchar)
      }

      removeEventListener(tipo: string, escuchar: Escucha): void {
        this.escuchas[tipo] = (this.escuchas[tipo] ?? []).filter((otro) => otro !== escuchar)
      }

      close(): void {
        this.cerrada = true
      }
    }

    // @ts-expect-error Sustitución determinista de EventSource para el E2E.
    window.EventSource = FuenteQueSeCae

    const fetchOriginal = window.fetch.bind(window)
    window.fetch = async (entrada: RequestInfo | URL, opciones?: RequestInit) => {
      const url =
        typeof entrada === 'string' ? entrada : entrada instanceof URL ? entrada.href : entrada.url
      if (url.includes('/api/v1/estado/recinto')) {
        // El primer snapshot REST sirve de baseline; los siguientes fallan para que la
        // aplicación no consiga recuperarse durante la medición.
        if (yaEntregoUnSnapshot) return new Response('', { status: 503 })
        return new Response(JSON.stringify(snapshot), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      return fetchOriginal(entrada, opciones)
    }
  }, estado)
}

for (const viewport of RESOLUCIONES) {
  test(`la cabecera del Recinto avisa la vista desactualizada en un renglón en ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport)
    await instalarBackendQueSeCae(page, estadoRecinto())
    await page.goto(URL_RECINTO)

    const indicador = page.getByTestId('estado-conexion')
    // Criterio 7: el texto es exactamente el aprobado, con paréntesis y sin tilde.
    await expect(indicador).toHaveText(TEXTO_DESACTUALIZADO)

    /*
      Criterio 8: la cabecera conserva su geometría. Se comprueban las tres cosas que
      podrían romperse por un cambio de texto: que la franja siga midiendo lo mismo que
      declara su CSS (altura fija), que su contenido no la desborde y que el indicador siga
      ocupando un solo renglón.
    */
    const geometria = await page.evaluate(() => {
      const cabecera = document.querySelector('[data-testid="cabecera-recinto"]')!
      const indicadorNodo = document.querySelector('[data-testid="estado-conexion"]')!
      const estiloIndicador = getComputedStyle(indicadorNodo)
      return {
        altoCabecera: cabecera.getBoundingClientRect().height,
        desbordeVertical: cabecera.scrollHeight - cabecera.clientHeight,
        desbordeHorizontal: cabecera.scrollWidth - cabecera.clientWidth,
        altoIndicador: indicadorNodo.getBoundingClientRect().height,
        altoContenidoIndicador: indicadorNodo.scrollHeight,
        recorteIndicador: indicadorNodo.scrollWidth - indicadorNodo.clientWidth,
        alturaLinea: parseFloat(estiloIndicador.fontSize),
      }
    })

    // Altura fija vigente: `clamp(47px, 5.5vh, 60px)`.
    expect(geometria.altoCabecera).toBeGreaterThanOrEqual(47)
    expect(geometria.altoCabecera).toBeLessThanOrEqual(60)
    expect(geometria.desbordeVertical).toBeLessThanOrEqual(1)
    expect(geometria.desbordeHorizontal).toBeLessThanOrEqual(1)
    expect(geometria.recorteIndicador).toBeLessThanOrEqual(1)
    // Un solo renglón: el contenido del indicador no supera su propia caja.
    expect(geometria.altoContenidoIndicador).toBeLessThanOrEqual(geometria.altoIndicador + 1)

    esperarSinScrollGlobal(await medirDocumento(page))
  })
}

// =============================================================================
// 3. Moderación: impedimento de carga del Orden del Día
// =============================================================================

/**
 * Snapshot de Moderación en `SIN_PREPARAR`.
 *
 * Es el único estado en que el operador ve el impedimento: el backend habilita la carga
 * en PREPARANDO y en SESION_ABIERTA, y en cualquier otro caso publica el código genérico
 * `ESTADO_INCOMPATIBLE`. Se construye acá y no en el soporte compartido porque el resto de
 * las pruebas técnicas necesitan justamente lo contrario, una sesión ya abierta.
 */
function moderacionSinPreparar() {
  const base = estadoModeracion()
  return {
    ...base,
    revision: 0,
    estado_global: 'SIN_PREPARAR',
    sesion: null,
    preparacion: null,
    quorum: null,
    orden_del_dia: null,
    capacidades: {
      ...base.capacidades,
      preparar_sala: { habilitada: true, motivos: [] },
      cargar_orden_del_dia: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      descartar_orden_del_dia: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
    },
  }
}

for (const viewport of RESOLUCIONES) {
  test(`Moderación explica cómo destrabar la carga del Orden del Día en ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport)
    await instalarBackend(page, { '/api/v1/estado/moderacion': moderacionSinPreparar() })
    await page.goto('/moderacion/')

    const carga = page.getByTestId('carga-orden-dia')
    await expect(carga).toBeVisible()
    // Criterio 1: el texto exacto aprobado, tal cual, sin tildes agregadas.
    await expect(carga).toContainText(TEXTO_ORDEN_DEL_DIA)
    // Criterio 2: la redacción general del mismo código no aparece en esta vista.
    await expect(carga).not.toContainText('El estado actual del sistema no permite')

    /*
      El texto nuevo es más largo que el anterior, así que se verifica que el cuadrante lo
      absorba: ni la caja de carga ni el panel que la contiene pueden ganar desborde, y la
      página no puede empezar a scrollear por un renglón de ayuda.
    */
    const desbordes = await page.evaluate(() => {
      const cargaNodo = document.querySelector('[data-testid="carga-orden-dia"]')!
      const panel = document.querySelector('[data-testid="panel-orden-del-dia"]')!
      return {
        cargaHorizontal: cargaNodo.scrollWidth - cargaNodo.clientWidth,
        panelHorizontal: panel.scrollWidth - panel.clientWidth,
      }
    })
    expect(desbordes.cargaHorizontal).toBeLessThanOrEqual(1)
    expect(desbordes.panelHorizontal).toBeLessThanOrEqual(1)

    esperarSinScrollGlobal(await medirDocumento(page))
  })
}
