/**
 * WP-099 · el Zócalo para OBS contra el stack real.
 *
 * ## Qué agrega este recorrido
 *
 * Las pruebas de navegador del Zócalo usan un doble determinista del backend: sirven para
 * medir geometría y color, pero no pueden demostrar que la superficie consume **la misma
 * fuente autoritativa** que la Pantalla del Recinto, porque en ese escenario la fuente la
 * fabrica la propia prueba.
 *
 * Acá corre un único FastAPI real, con la configuración local de este checkout y las SPA ya
 * construidas servidas como archivos estáticos, igual que en producción. Sobre eso se
 * comprueban las dos afirmaciones del WP que sólo el stack completo puede sostener:
 *
 * 1. el Zócalo se publica bajo el mismo origen y el mismo prefijo que el resto de las
 *    superficies públicas, sin autenticación;
 * 2. ante una votación real abierta desde Moderación, el Zócalo y el Recinto muestran
 *    **exactamente el mismo texto** de `Votación`, `Tema` y `Estado`, y los dos cambian
 *    solos cuando el backend publica la revisión siguiente.
 *
 * El punto 2 es la forma verificable de «sin estado paralelo»: si el Zócalo mantuviera un
 * modelo propio, bastaría con que una de las dos pantallas se adelantara o se quedara para
 * que la comparación de textos fallara.
 */

import { expect, test, type Page } from '@playwright/test'

import { ProcesoStackIntegrado, URL_STACK, pulsarSecuencia, puertoOcupado } from './infraestructura'

/** Bancas que se marcan presentes para alcanzar el quórum exigido por la plantilla. */
const PULSACIONES_PRESENCIA = ['1-9', '2-9', '3-9', '4-9', '5-9', '6-9', '7-9']

/** Tema con el que se abre la votación real del recorrido. */
const TEMA_VOTACION = 'Expediente E2E 99/2026 — Zócalo para transmisión'

/** Lee los tres renglones de la franja superior de la Pantalla del Recinto. */
async function leerRecinto(recinto: Page) {
  return {
    votacion: (await recinto.getByTestId('resumen-votacion').textContent())?.trim() ?? '',
    tema: (await recinto.getByTestId('tema-votacion').textContent())?.trim() ?? '',
    estado: (await recinto.getByTestId('estado-votacion').textContent())?.trim() ?? '',
  }
}

/** Lee los tres renglones del Zócalo. */
async function leerZocalo(zocalo: Page) {
  return {
    votacion: (await zocalo.getByTestId('zocalo-votacion').textContent())?.trim() ?? '',
    tema: (await zocalo.getByTestId('zocalo-tema').textContent())?.trim() ?? '',
    estado: (await zocalo.getByTestId('zocalo-estado').textContent())?.trim() ?? '',
  }
}

test.describe.serial('WP-099 · Zócalo para OBS sobre el stack real', () => {
  const stack = new ProcesoStackIntegrado()

  test.beforeAll(async () => {
    expect(await puertoOcupado()).toBe(false)
    await stack.iniciar()
  })

  test.afterAll(async () => {
    await stack.detener()
    expect(await puertoOcupado()).toBe(false)
  })

  test.afterEach(async ({}, informacion) => {
    if (informacion.status !== informacion.expectedStatus) {
      await informacion.attach('stdout-stderr-stack.txt', {
        body: stack.obtenerSalida(),
        contentType: 'text/plain',
      })
    }
  })

  test('se publica bajo el mismo origen y refleja la votación igual que el Recinto', async ({
    browser,
  }) => {
    // El Zócalo se abre a 1920×1080 porque es la medida habitual del programa de
    // transmisión; el Recinto, a la suya de referencia. La comparación es de texto, no de
    // geometría, así que las medidas distintas son deliberadas: demuestran que el mismo
    // contenido llega a dos encuadres diferentes.
    const contexto = await browser.newContext({ viewport: { width: 1920, height: 1080 } })
    const moderacion = await contexto.newPage()
    const recinto = await contexto.newPage()
    const zocalo = await contexto.newPage()

    try {
      await test.step('A · las tres superficies arrancan bajo el mismo origen', async () => {
        const respuesta = await moderacion.request.get(`${URL_STACK}/zocalo/`)
        expect(respuesta.ok()).toBe(true)
        // Mismo origen significa, literalmente, que no hace falta ninguna credencial ni
        // ningún host distinto: es la misma raíz que sirve /recinto/ y /moderacion/.
        expect(respuesta.status()).toBe(200)

        await Promise.all([
          moderacion.goto(`${URL_STACK}/moderacion/`),
          recinto.goto(`${URL_STACK}/recinto/`),
          zocalo.goto(`${URL_STACK}/zocalo/`),
        ])

        await expect(moderacion.getByTestId('vista-sin-preparar')).toBeVisible()
        await expect(zocalo.getByTestId('zocalo')).toBeVisible()
        // En `SIN_PREPARAR` no hay votación que mostrar y el bloque conserva su geometría
        // con texto neutro: una Browser Source no puede quedarse en blanco.
        await expect(zocalo.getByTestId('zocalo-estado')).toHaveText('Sin votación')
        await expect(zocalo.getByTestId('zocalo-tema')).toHaveText('—')
      })

      await test.step('B · preparación y apertura de sesión reales', async () => {
        await moderacion.getByTestId('btn-preparar-sala').click()
        await expect(moderacion.getByTestId('vista-preparando')).toBeVisible()

        await pulsarSecuencia(PULSACIONES_PRESENCIA)
        await expect(recinto.getByTestId('cantidad-presentes')).toHaveText('7/12')

        await moderacion.getByTestId('input-numero-sesion').fill('99')
        await moderacion.getByTestId('input-presidencia').fill('Presidencia E2E Ficticia')
        await moderacion.getByTestId('input-secretaria').fill('Secretaría E2E Ficticia')
        await moderacion.getByTestId('btn-guardar-preparacion').click()
        await expect(moderacion.getByTestId('btn-abrir-sesion')).toBeEnabled()
        await moderacion.getByTestId('btn-abrir-sesion').click()
        await expect(moderacion.getByTestId('vista-sesion-abierta')).toBeVisible()
      })

      await test.step('C · con la votación abierta ambas superficies dicen lo mismo', async () => {
        await moderacion.getByTestId('input-numero-votacion').fill('99')
        await moderacion.getByTestId('select-tipo-votacion').selectOption({ label: 'Otro' })
        await moderacion.getByTestId('input-tema-votacion').fill(TEMA_VOTACION)
        await moderacion.getByTestId('radio-mayoria-simple').check()
        await moderacion.getByTestId('btn-abrir-votacion').click()
        await expect(moderacion.getByTestId('estado-votacion')).toHaveText('EN_CURSO')

        // Ninguna de las dos páginas se recargó: las dos adoptaron la revisión nueva por su
        // propia suscripción al mismo stream autoritativo.
        await expect(zocalo.getByTestId('zocalo-tema')).toHaveText(TEMA_VOTACION)
        await expect(recinto.getByTestId('tema-votacion')).toHaveText(TEMA_VOTACION)

        const enRecinto = await leerRecinto(recinto)
        const enZocalo = await leerZocalo(zocalo)
        expect(enZocalo).toEqual(enRecinto)
        expect(enZocalo.votacion).toContain('N.º 99')
        expect(enZocalo.estado).toBe('En curso')

        // Secreto del voto: con la recepción abierta el Zócalo no publica conteos.
        await expect(zocalo.getByTestId('zocalo-detalle-estado')).toHaveCount(0)
      })

      await test.step('D · el cierre de la votación llega a las dos por igual', async () => {
        // Siete presentes votan y la recepción se cierra sola al completarse.
        await pulsarSecuencia(['1-1', '2-1', '3-1', '4-1', '5-3', '6-3', '7-2'])
        await expect(moderacion.getByTestId('estado-votacion')).toHaveText('APROBADA')

        await expect(zocalo.getByTestId('zocalo-estado')).toHaveText('Aprobada')
        const enRecinto = await leerRecinto(recinto)
        const enZocalo = await leerZocalo(zocalo)
        expect(enZocalo).toEqual(enRecinto)

        // Y el detalle de conteos aparece recién ahora, con los mismos números que
        // publicó el backend.
        await expect(zocalo.getByTestId('zocalo-detalle-estado')).toContainText(
          'Positivos 4 · Negativos 2 · Abstenciones 1 · Total 7',
        )
      })

      await test.step('E · el Zócalo sigue sin exponer controles al aire', async () => {
        const interactivos = await zocalo.evaluate(
          () =>
            document.querySelectorAll(
              'button, input, select, textarea, a, form, [role], [contenteditable], [tabindex]',
            ).length,
        )
        expect(interactivos).toBe(0)
      })
    } finally {
      await contexto.close()
    }
  })
})
