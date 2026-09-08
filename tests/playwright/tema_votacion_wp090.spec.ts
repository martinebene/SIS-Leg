/**
 * WP-090 — Contención del tema proyectado en Q1 medida en navegador real.
 *
 * El DOM liviano de Vitest no calcula líneas ni cajas. Estas pruebas usan las dos
 * resoluciones operativas para demostrar que un tema breve no recibe scroll, que uno
 * extenso queda limitado a tres renglones recorribles y que el formulario inferior sigue
 * íntegramente dentro de Q1 sin agregar scroll al cuadrante ni al documento.
 */

import { expect, test, type Page } from '@playwright/test'
import {
  estadoModeracion,
  instalarBackend,
  RESOLUCIONES,
  URL_MODERACION,
} from './soporte/apoyo_tecnico'

const TEMA_CORTO = 'Presupuesto anual'
const TEMA_LARGO =
  'Expediente 4521-D-2026: Ordenanza de creación del Programa Municipal de Eficiencia Energética y Reconversión del Alumbrado Público, incorporación progresiva de luminarias de bajo consumo, mantenimiento preventivo, seguimiento trimestral, anexos técnicos y disposiciones complementarias para todos los barrios de la ciudad, con sus fundamentos, antecedentes y modificaciones sucesivas.'

/**
 * Construye el caso operativo de WP-048/WP-057: resultado anterior todavía visible y
 * formulario habilitado para abrir la votación siguiente. Sólo varía el tema proyectado.
 */
function estadoConResultadoAnterior(tema: string): Record<string, unknown> {
  const estado = estadoModeracion() as unknown as Record<string, unknown>
  estado.configuracion = {
    quorum: 7,
    filas_bancas: [6, 6],
    tipos_votacion: ['Proyecto', 'Moción'],
    duracion_test_segundos: 3,
    revelado_votos_moderacion_segundos: 4,
    cuenta_regresiva_recinto_segundos: 3,
    resultado_publico_recinto_segundos: 6,
  }
  estado.votacion = {
    id: 'votacion-anterior-wp090',
    numero_votacion: 12,
    tipo: 'Proyecto de Ordenanza',
    tema,
    tipo_mayoria: 'SIMPLE',
    factor: 0,
    base: 'VOTOS_COMPUTABLES',
    estado_recepcion: 'CERRADA',
    resultado: 'APROBADA',
    fecha_hora_apertura: '2026-09-08T10:00:00Z',
    fecha_hora_cierre: '2026-09-08T10:02:00Z',
    fecha_hora_resultado: '2026-09-08T10:02:00Z',
    motivo_finalizacion_manual: null,
    cantidad_votos_recibidos: 12,
    bancas_voto_emitido: [],
    revelado_individual_desde: '2026-09-08T10:00:04Z',
    votos_individuales_revelados: true,
    votos_individuales: null,
    conteos: { positivos: 8, negativos: 3, abstenciones: 1, total: 12 },
    voto_presidencial: null,
  }
  return estado
}

/** Abre Moderación con el snapshot pedido y espera que Q1 esté listo para medir. */
async function abrirQ1(page: Page, tema: string): Promise<void> {
  await instalarBackend(page, {
    '/api/v1/estado/moderacion': estadoConResultadoAnterior(tema),
  })
  await page.goto(URL_MODERACION)
  await expect(page.getByTestId('tema-votacion-proyectada')).toHaveText(tema)
  await expect(page.getByTestId('formulario-votacion')).toBeVisible()
}

/** Mide líneas, scroll y cajas sin depender de nombres de utilidades CSS. */
async function medirTemaYQ1(page: Page) {
  return page.evaluate(() => {
    const tema = document.querySelector<HTMLElement>('[data-testid="tema-votacion-proyectada"]')!
    const boton = document.querySelector<HTMLElement>('[data-testid="btn-abrir-votacion"]')!
    const formulario = document.querySelector<HTMLElement>('[data-testid="formulario-votacion"]')!
    const panel = document.querySelector<HTMLElement>('[data-testid="panel-sesion-votacion"]')!
    const cuerpo = panel.querySelector<HTMLElement>('[data-testid="cuerpo-panel"]')!
    const estiloTema = getComputedStyle(tema)
    const cajaBoton = boton.getBoundingClientRect()
    const cajaFormulario = formulario.getBoundingClientRect()
    const cajaPanel = panel.getBoundingClientRect()
    return {
      tema: {
        altoVisible: tema.clientHeight,
        altoContenido: tema.scrollHeight,
        altoLinea: Number.parseFloat(estiloTema.lineHeight),
        overflowY: estiloTema.overflowY,
        texto: tema.textContent?.trim() ?? '',
      },
      boton: { arriba: cajaBoton.top, abajo: cajaBoton.bottom },
      formulario: { arriba: cajaFormulario.top, abajo: cajaFormulario.bottom },
      panel: { arriba: cajaPanel.top, abajo: cajaPanel.bottom },
      desbordeQ1: cuerpo.scrollHeight - cuerpo.clientHeight,
      desbordeFormulario: formulario.scrollHeight - formulario.clientHeight,
      desbordeDocumento:
        document.documentElement.scrollHeight - document.documentElement.clientHeight,
      desbordeHorizontalDocumento:
        document.documentElement.scrollWidth - document.documentElement.clientWidth,
    }
  })
}

for (const viewport of RESOLUCIONES) {
  test(`el tema corto se muestra completo y sin scroll en ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport)
    await abrirQ1(page, TEMA_CORTO)

    const medicion = await medirTemaYQ1(page)
    expect(medicion.tema.texto).toBe(TEMA_CORTO)
    expect(medicion.tema.overflowY).toBe('auto')
    expect(medicion.tema.altoContenido).toBeLessThanOrEqual(medicion.tema.altoVisible + 1)
    expect(medicion.tema.altoVisible).toBeLessThanOrEqual(medicion.tema.altoLinea * 3 + 1)
    expect(medicion.boton.arriba).toBeGreaterThanOrEqual(medicion.panel.arriba - 1)
    expect(medicion.boton.abajo).toBeLessThanOrEqual(medicion.panel.abajo + 1)
    expect(medicion.desbordeQ1).toBeLessThanOrEqual(1)
    expect(medicion.desbordeFormulario).toBeLessThanOrEqual(1)
    expect(medicion.desbordeDocumento).toBeLessThanOrEqual(1)
    expect(medicion.desbordeHorizontalDocumento).toBeLessThanOrEqual(1)
  })

  test(`el tema largo queda en tres líneas recorribles en ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport)
    await abrirQ1(page, TEMA_LARGO)

    const medicion = await medirTemaYQ1(page)
    expect(medicion.tema.texto).toBe(TEMA_LARGO)
    expect(medicion.tema.overflowY).toBe('auto')
    expect(medicion.tema.altoVisible).toBeCloseTo(medicion.tema.altoLinea * 3, 0)
    expect(medicion.tema.altoContenido).toBeGreaterThan(medicion.tema.altoVisible + 1)

    // El excedente no está truncado: se puede recorrer dentro del propio encabezado.
    const desplazamiento = await page.getByTestId('tema-votacion-proyectada').evaluate((tema) => {
      tema.scrollTop = tema.scrollHeight
      return tema.scrollTop
    })
    expect(desplazamiento).toBeGreaterThan(0)

    // El resultado y el formulario siguen ordenados, y el botón permanece alcanzable.
    expect(medicion.formulario.arriba).toBeGreaterThanOrEqual(medicion.panel.arriba)
    expect(medicion.formulario.abajo).toBeLessThanOrEqual(medicion.panel.abajo + 1)
    expect(medicion.boton.abajo).toBeLessThanOrEqual(medicion.panel.abajo + 1)
    await expect(page.getByTestId('btn-abrir-votacion')).toBeVisible()
    expect(medicion.desbordeQ1).toBeLessThanOrEqual(1)
    expect(medicion.desbordeFormulario).toBeLessThanOrEqual(1)
    expect(medicion.desbordeDocumento).toBeLessThanOrEqual(1)
    expect(medicion.desbordeHorizontalDocumento).toBeLessThanOrEqual(1)
  })
}
