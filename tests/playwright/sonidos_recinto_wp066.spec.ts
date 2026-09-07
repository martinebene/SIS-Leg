/**
 * Sonidos de la Pantalla del Recinto en un navegador real (WP-066).
 *
 * Las pruebas de Vitest fijan la semántica con un reproductor falso. Éstas comprueban lo
 * que sólo puede verse en Chromium: que el motor cree elementos multimedia de verdad, que
 * el WAV publicado se descargue desde la propia aplicación y que la política de autoplay
 * configurada permita reproducir **sin ninguna interacción humana**, que es la condición
 * real del recinto.
 *
 * La política se declara en `playwright.config.ts` con la misma bandera que el equipo de
 * producción necesita, de modo que la prueba y la operación exigen exactamente lo mismo.
 */

import { expect, test } from '@playwright/test'

import { concejalesPublicos, estadoRecinto, URL_RECINTO } from './soporte/apoyo_tecnico'
import {
  emitirEstado,
  instalarBackendControlable,
  instalarEspiaAudio,
  leerReproducciones,
  prepararEstado,
  romperStream,
} from './soporte/sonidos'

/** Votación pública mínima, en recepción abierta. */
function votacion(parcial: Record<string, unknown> = {}) {
  return {
    id: 'votacion-e2e',
    numero_votacion: 1,
    tipo: 'Despacho',
    tema: 'Expediente de prueba',
    tipo_mayoria: 'SIMPLE',
    factor: 0,
    base: 'VOTOS_COMPUTABLES',
    estado_recepcion: 'EN_CURSO',
    resultado: null,
    fecha_hora_apertura: '2026-09-04T10:00:00Z',
    fecha_hora_cierre: null,
    cuenta_regresiva_hasta: null,
    resultado_visible_hasta: null,
    bancas_voto_emitido: [],
    votos_individuales: null,
    conteos: null,
    voto_presidencial: null,
    ...parcial,
  }
}

/** El nombre de archivo alcanza para identificar el evento que sonó. */
function archivos(reproducciones: { src: string }[]): string[] {
  return reproducciones.map((reproduccion) => reproduccion.src.split('/').pop() ?? '')
}

test.describe('Motor de sonidos del Recinto', () => {
  test('no reproduce nada al adoptar el primer estado', async ({ page }) => {
    await instalarEspiaAudio(page)
    // Una sesión ya avanzada: votación abierta y doce bancas presentes. Si la pantalla
    // sonorizara la baseline, al encender el monitor sonaría todo lo ya ocurrido.
    await instalarBackendControlable(page, { ...estadoRecinto(), votacion: votacion() })

    await page.goto(URL_RECINTO)
    await expect(page.getByTestId('area-bancas-publica')).toBeVisible()
    await page.waitForTimeout(500)

    expect(await leerReproducciones(page)).toEqual([])
  })

  test('reproduce el archivo y el volumen configurados ante un hecho nuevo', async ({ page }) => {
    await instalarEspiaAudio(page)
    await instalarBackendControlable(page, estadoRecinto())

    await page.goto(URL_RECINTO)
    await expect(page.getByTestId('area-bancas-publica')).toBeVisible()

    await emitirEstado(page, { ...estadoRecinto(), revision: 2, votacion: votacion() })

    await expect
      .poll(async () => archivos(await leerReproducciones(page)))
      .toEqual(['votacion-abierta.wav'])

    const [reproduccion] = await leerReproducciones(page)
    // 85 sobre 100 en `config/system.toml` es 0.85 en el estándar HTML.
    expect(reproduccion?.volume).toBeCloseTo(0.85, 2)
    // La promesa cumplida es la prueba de que la política de autoplay dejó reproducir sin
    // que nadie tocara la pantalla.
    await expect.poll(async () => (await leerReproducciones(page))[0]?.resultado).toBe('cumplida')
  })

  test('superpone dos sonidos simultáneos sin interrumpir el primero', async ({ page }) => {
    await instalarEspiaAudio(page)
    const presentes = concejalesPublicos(12)
    await instalarBackendControlable(page, { ...estadoRecinto(), concejales: presentes })

    await page.goto(URL_RECINTO)
    await expect(page.getByTestId('area-bancas-publica')).toBeVisible()

    // Una misma revisión abre la votación y deja ausente a una banca.
    await emitirEstado(page, {
      ...estadoRecinto(),
      revision: 2,
      votacion: votacion(),
      concejales: presentes.map((concejal) =>
        concejal.banca === 5 ? { ...concejal, presente: false } : concejal,
      ),
    })

    await expect.poll(async () => (await leerReproducciones(page)).length).toBe(2)

    const reproducciones = await leerReproducciones(page)
    expect(archivos(reproducciones).sort()).toEqual([
      'concejal-ausente.wav',
      'votacion-abierta.wav',
    ])
    // Instancias distintas y ninguna pausa: el segundo sonido no cortó al primero.
    expect(new Set(reproducciones.map((reproduccion) => reproduccion.id)).size).toBe(2)
    expect(await page.evaluate(() => window.pausasRecinto)).toBe(0)
  })

  test('no reproduce el historial acumulado al recuperarse de una caída del stream', async ({
    page,
  }) => {
    await instalarEspiaAudio(page)
    const presentes = concejalesPublicos(12)
    await instalarBackendControlable(page, { ...estadoRecinto(), concejales: presentes })

    await page.goto(URL_RECINTO)
    await expect(page.getByTestId('area-bancas-publica')).toBeVisible()

    // Mientras la pantalla está desconectada el recinto sigue funcionando: se abre una
    // votación y una banca se ausenta. El snapshot de recuperación traerá ambas cosas.
    await prepararEstado(page, {
      ...estadoRecinto(),
      revision: 20,
      votacion: votacion(),
      concejales: presentes.map((concejal) =>
        concejal.banca === 5 ? { ...concejal, presente: false } : concejal,
      ),
    })
    await romperStream(page)

    // El cliente espera su backoff, vuelve a pedir el snapshot y reabre el stream. Que el
    // tema aparezca en pantalla prueba que esa recuperación —votación abierta y banca
    // ausente en la misma revisión— efectivamente se adoptó.
    await expect(page.getByTestId('tema-votacion')).toHaveText('Expediente de prueba', {
      timeout: 5_000,
    })
    expect(await leerReproducciones(page)).toEqual([])

    // Desde esa nueva referencia, un hecho posterior sí suena.
    await emitirEstado(page, {
      ...estadoRecinto(),
      revision: 21,
      votacion: votacion({ estado_recepcion: 'CERRADA', resultado: 'APROBADA' }),
      concejales: presentes.map((concejal) =>
        concejal.banca === 5 ? { ...concejal, presente: false } : concejal,
      ),
    })

    await expect
      .poll(async () => archivos(await leerReproducciones(page)))
      .toEqual(['votacion-cerrada.wav'])
  })

  test('acompaña con un tic cada segundo de la cuenta regresiva sin pedir revisiones', async ({
    page,
  }) => {
    await instalarEspiaAudio(page)
    await instalarBackendControlable(page, estadoRecinto())

    await page.goto(URL_RECINTO)
    await expect(page.getByTestId('area-bancas-publica')).toBeVisible()

    // Una única revisión inicia una cuenta regresiva de cuatro segundos. El número lo baja
    // el reloj local: no llega ni una revisión más hasta el final de la prueba.
    const ahora = Date.now()
    await emitirEstado(page, {
      ...estadoRecinto({
        transmision: {
          estado: 'CUENTA_REGRESIVA',
          iniciada_en: new Date(ahora).toISOString(),
          en_vivo_desde: new Date(ahora + 4_000).toISOString(),
          cuenta_regresiva_segundos: 4,
          segundos_restantes: 4,
        },
      }),
      instancia: 'instancia-prueba',
      revision: 2,
      generado_en: new Date(ahora).toISOString(),
    })

    // Adoptar el snapshot muestra el número pero no suena; los cambios de segundo sí.
    await expect
      .poll(async () => (await leerReproducciones(page)).length, { timeout: 6_000 })
      .toBeGreaterThanOrEqual(2)

    const reproducciones = await leerReproducciones(page)
    expect(new Set(archivos(reproducciones))).toEqual(
      new Set(['transmision-cuenta-regresiva-tic.wav']),
    )
    expect(reproducciones[0]?.volume).toBeCloseTo(0.35, 2)
  })
})
