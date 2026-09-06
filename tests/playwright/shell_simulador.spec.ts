/**
 * Pruebas E2E de interfaz de usuario para el Simulador Web (@sis-leg/simulador).
 *
 * Verificaciones obligatorias (WP-034 y WP-035):
 * 1. Resolución Full HD 1920×1080 sin scroll vertical ni horizontal para 12 dispositivos iniciales.
 * 2. Visualización simultánea de los 12 dispositivos dev01..dev12 por defecto.
 * 3. Disposición exacta 2 filas × 3 columnas en cada tarjeta:
 *    - Fila superior: Presencia (9), Test (8), Palabra (7).
 *    - Fila inferior: Afirmativo (1), Abstención (2), Negativo (3).
 * 4. Selector compacto de cantidad en zona superior (1..20, default 12):
 *    - Decrementar a 8 oculta solo dev09..dev12.
 *    - Incrementar hasta 20 muestra dev01..dev20 y deshabilita el botón (+).
 * 5. Envío de pulsaciones desde dispositivos >12 (ej. dev20) hacia FastAPI sin filtrado frontend.
 * 6. Símbolos textuales y etiqueta neutra de presencia.
 * 7. Adaptabilidad en resoluciones menores (DT-020).
 */

import { expect, test, type Page } from '@playwright/test'

const URL_SIMULADOR = 'http://localhost:3002/simulador/'

test.describe('Shell del Simulador Web de Dispositivos Lógicos (WP-034 y WP-035)', () => {
  test('en resolución Full HD 1920×1080 presenta los 12 dispositivos simultáneamente sin scroll y selector en 12', async ({
    page,
  }) => {
    // Configurar viewport de referencia Full HD 1920×1080
    await page.setViewportSize({ width: 1920, height: 1080 })
    await page.goto(URL_SIMULADOR)

    // 1. Cabecera, distintivo de simulador y selector compacto
    const cabecera = page.getByTestId('cabecera-simulador')
    await expect(cabecera).toBeVisible()
    await expect(page.getByTestId('badge-simulador')).toContainText(
      'Simulador · Entradas reales a FastAPI',
    )
    await expect(cabecera).toContainText('sin device-bridge')

    // Selector visible arriba con valor inicial 12 (WP-035)
    await expect(page.getByTestId('selector-cantidad')).toBeVisible()
    await expect(page.getByTestId('valor-cantidad')).toHaveText('12')

    // 2. Panel general visible
    await expect(page.getByTestId('panel-general')).toBeVisible()

    // 3. Los 12 dispositivos dev01..dev12 presentes en pantalla
    for (let i = 1; i <= 12; i++) {
      const idDev = `dev${String(i).padStart(2, '0')}`
      const tarjeta = page.getByTestId(`tarjeta-${idDev}`)
      await expect(tarjeta).toBeVisible()
      await expect(tarjeta.getByTestId(`titulo-${idDev}`)).toHaveText(idDev)

      // Seis botones funcionales por tarjeta
      await expect(tarjeta.getByTestId(`btn-${idDev}-9`)).toBeVisible()
      await expect(tarjeta.getByTestId(`btn-${idDev}-8`)).toBeVisible()
      await expect(tarjeta.getByTestId(`btn-${idDev}-7`)).toBeVisible()
      await expect(tarjeta.getByTestId(`btn-${idDev}-1`)).toBeVisible()
      await expect(tarjeta.getByTestId(`btn-${idDev}-2`)).toBeVisible()
      await expect(tarjeta.getByTestId(`btn-${idDev}-3`)).toBeVisible()
    }

    // 4. Log global visible en la parte inferior
    await expect(page.getByTestId('seccion-log-pulsaciones')).toBeVisible()

    // 5. Comprobación matemática estricta de ausencia de scroll en 1920×1080
    const scrollInfo = await page.evaluate(() => {
      const doc = document.documentElement
      return {
        scrollHeight: doc.scrollHeight,
        clientHeight: doc.clientHeight,
        scrollWidth: doc.scrollWidth,
        clientWidth: doc.clientWidth,
      }
    })

    // La altura y anchura del contenido no deben desbordar el viewport disponible
    expect(scrollInfo.scrollHeight).toBeLessThanOrEqual(scrollInfo.clientHeight + 1)
    expect(scrollInfo.scrollWidth).toBeLessThanOrEqual(scrollInfo.clientWidth + 1)
  })

  test('cada tarjeta dispone 2 filas x 3 columnas con orden exacto de acciones y símbolos accesibles (WP-035)', async ({
    page,
  }) => {
    await page.goto(URL_SIMULADOR)

    const tarjeta = page.getByTestId('tarjeta-dev01')

    // Verificar orden exacto de botones dentro de la tarjeta
    const botones = tarjeta.locator('button')
    await expect(botones).toHaveCount(6)

    // Fila superior: Presencia (9), Test (8), Palabra (7)
    await expect(botones.nth(0)).toHaveAttribute('data-testid', 'btn-dev01-9')
    await expect(botones.nth(0)).toContainText('Pres. / Aus.')
    await expect(botones.nth(0)).toContainText('👤')

    await expect(botones.nth(1)).toHaveAttribute('data-testid', 'btn-dev01-8')
    await expect(botones.nth(1)).toContainText('Test')
    await expect(botones.nth(1)).toContainText('⚡')

    await expect(botones.nth(2)).toHaveAttribute('data-testid', 'btn-dev01-7')
    await expect(botones.nth(2)).toContainText('Palabra')
    await expect(botones.nth(2)).toContainText('🎤')

    // Fila inferior: Afirmativo (1), Abstención (2), Negativo (3)
    await expect(botones.nth(3)).toHaveAttribute('data-testid', 'btn-dev01-1')
    await expect(botones.nth(3)).toContainText('Afirmativo')
    await expect(botones.nth(3)).toContainText('✓')

    await expect(botones.nth(4)).toHaveAttribute('data-testid', 'btn-dev01-2')
    await expect(botones.nth(4)).toContainText('Abstención')
    await expect(botones.nth(4)).toContainText('○')

    await expect(botones.nth(5)).toHaveAttribute('data-testid', 'btn-dev01-3')
    await expect(botones.nth(5)).toContainText('Negativo')
    await expect(botones.nth(5)).toContainText('✗')

    // Etiqueta neutra de presencia: nunca dice "Presente" ni "Ausente"
    const textoBotonPresencia = await botones.nth(0).innerText()
    expect(textoBotonPresencia).not.toContain('Presente')
    expect(textoBotonPresencia).not.toContain('Ausente')

    // No revela concejal ni banca
    const textoTarjeta = await tarjeta.innerText()
    expect(textoTarjeta).not.toContain('Banca')
    expect(textoTarjeta).not.toContain('Concejal')
  })

  test('permite ajustar cantidad dinámicamente con selector − / cantidad / + (WP-035)', async ({
    page,
  }) => {
    await page.goto(URL_SIMULADOR)

    const btnMenos = page.getByTestId('btn-disminuir-cantidad')
    const btnMas = page.getByTestId('btn-aumentar-cantidad')
    const valorCantidad = page.getByTestId('valor-cantidad')

    // 1. Inicialmente 12 dispositivos dev01..dev12
    await expect(valorCantidad).toHaveText('12')
    await expect(page.getByTestId('tarjeta-dev12')).toBeVisible()

    // 2. Decrementar 4 veces: de 12 a 8
    for (let i = 0; i < 4; i++) {
      await btnMenos.click()
    }

    await expect(valorCantidad).toHaveText('8')
    // dev01..dev08 visibles
    await expect(page.getByTestId('tarjeta-dev01')).toBeVisible()
    await expect(page.getByTestId('tarjeta-dev08')).toBeVisible()
    // dev09..dev12 ocultos
    await expect(page.getByTestId('tarjeta-dev09')).not.toBeAttached()
    await expect(page.getByTestId('tarjeta-dev12')).not.toBeAttached()

    // 3. Incrementar hasta el máximo permitido de 20
    for (let i = 8; i < 20; i++) {
      await btnMas.click()
    }

    await expect(valorCantidad).toHaveText('20')
    await expect(page.getByTestId('tarjeta-dev20')).toBeVisible()
    // El botón (+) queda deshabilitado en el máximo de 20
    await expect(btnMas).toBeDisabled()
  })

  test('emite pulsaciones desde dev20 sin filtrado frontend y refleja rechazo en el log (WP-035)', async ({
    page,
  }) => {
    let cuerpoRecibido: unknown = null

    // Interceptar la llamada para simular respuesta de FastAPI ante dispositivo no asignado
    await page.route('**/api/v1/entradas/tecla', async (route) => {
      cuerpoRecibido = route.request().postDataJSON()
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          aceptada: false,
          dispositivo: 'dev20',
          tecla: '9',
          motivo: 'DISPOSITIVO_NO_ASIGNADO',
          concejal: null,
          resultado: null,
        }),
      })
    })

    await page.goto(URL_SIMULADOR)

    // Aumentar a 20 dispositivos
    const btnMas = page.getByTestId('btn-aumentar-cantidad')
    for (let i = 12; i < 20; i++) {
      await btnMas.click()
    }

    // Pulsar tecla 9 en dev20
    const tarjeta20 = page.getByTestId('tarjeta-dev20')
    await expect(tarjeta20).toBeVisible()
    await tarjeta20.getByTestId('btn-dev20-9').click()

    // Verificar que el body emitido es { dispositivo: "dev20", tecla: "9" }
    expect(cuerpoRecibido).toEqual({
      dispositivo: 'dev20',
      tecla: '9',
    })

    // Verificar que el log registra el rechazo diagnóstico normalmente
    const entradaLog = page.getByTestId('entrada-log-dev20-9')
    await expect(entradaLog).toBeVisible()
    await expect(entradaLog).toContainText('dev20')
    await expect(entradaLog).toContainText('RECHAZADA')
    await expect(entradaLog).toContainText('DISPOSITIVO_NO_ASIGNADO')
  })

  test('emite la pulsación ordinaria dev04 hacia FastAPI y refleja la respuesta en el log global', async ({
    page,
  }) => {
    // Interceptar la llamada a POST /api/v1/entradas/tecla para simular respuesta controlada
    let cuerpoRecibido: unknown = null

    await page.route('**/api/v1/entradas/tecla', async (route) => {
      cuerpoRecibido = route.request().postDataJSON()
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          aceptada: true,
          dispositivo: 'dev04',
          tecla: '9',
          motivo: 'PRESENCIA_ACTUALIZADA',
          concejal: null,
          resultado: null,
        }),
      })
    })

    await page.goto(URL_SIMULADOR)

    // Pulsar tecla 9 en dev04
    await page.getByTestId('btn-dev04-9').click()

    // Verificar que el body emitido es { dispositivo: "dev04", tecla: "9" }
    expect(cuerpoRecibido).toEqual({
      dispositivo: 'dev04',
      tecla: '9',
    })

    // Verificar que la respuesta se refleja en el log global
    const entradaLog = page.getByTestId('entrada-log-dev04-9')
    await expect(entradaLog).toBeVisible()
    await expect(entradaLog).toContainText('dev04')
    await expect(entradaLog).toContainText('Pres. / Aus.')
    await expect(entradaLog).toContainText('HTTP 200')
    await expect(entradaLog).toContainText('ACEPTADA')
    await expect(entradaLog).toContainText('PRESENCIA_ACTUALIZADA')
  })

  test('se adapta a resoluciones menores sin romper los componentes', async ({ page }) => {
    // Vista en resolución compacta tipo laptop / tablet
    await page.setViewportSize({ width: 1024, height: 768 })
    await page.goto(URL_SIMULADOR)

    // Los dispositivos siguen existiendo y son interactivos
    await expect(page.getByTestId('tarjeta-dev01')).toBeVisible()
    await expect(page.getByTestId('tarjeta-dev12')).toBeVisible()
    await expect(page.getByTestId('selector-cantidad')).toBeVisible()
    await expect(page.getByTestId('seccion-log-pulsaciones')).toBeVisible()
  })
})
