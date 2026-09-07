/**
 * Geometría y overflow de la interfaz de Apoyo Técnico redistribuida (WP-059).
 *
 * WP-056 ya probó que el puesto entra completo en pantalla. Lo que se mide acá es la
 * distribución nueva que cerró HUMAN_GATE:
 *
 * ```text
 * ┌───────────────┬───────────────┬───────────────┬───────────────────┐
 * │  Transmisión  │    Remapeo    │   Mensajes    │                   │
 * ├───────────────┴───────────────┴───────────────┤      Eventos      │
 * │                    Avisos                     │                   │
 * └───────────────────────────────────────────────┴───────────────────┘
 * ```
 *
 * Son cuatro columnas visuales pero **no** cuatro columnas iguales: las tres de arriba a
 * la izquierda comparten dos tercios del ancho y Eventos conserva el tercio restante y
 * todo el alto útil.
 *
 * WP-070 matizó una sola de esas afirmaciones: las tres columnas izquierdas ya no miden
 * exactamente lo mismo, porque Mensajes recibió el ancho mínimo que necesita para que la
 * fila de acciones de cada mensaje precargado no envuelva a 1366×768. El reparto de dos
 * tercios / un tercio, el alto compartido y el confinamiento del scroll no cambian.
 *
 * Las afirmaciones no se hacen sobre clases CSS sino sobre cajas reales
 * (`getBoundingClientRect`) y sobre `scrollHeight` / `clientHeight`, porque lo que el WP
 * cerró es el resultado visible y no una técnica de implementación concreta. Por la misma
 * razón las proporciones se comprueban con márgenes de tolerancia: la regla es "un tercio
 * aproximado", no un número de píxeles.
 *
 * El backend se sustituye por el mismo doble determinista que usa la suite de WP-056: lo
 * que se verifica es la interfaz, no el transporte.
 */

import { expect, test, type Page } from '@playwright/test'

const URL_TECNICO = 'http://localhost:3003/tecnico/'

const RESOLUCIONES = [
  { width: 1920, height: 1080 },
  { width: 1366, height: 768 },
] as const

/** Tolerancia en píxeles para comparar bordes que deben coincidir. */
const TOLERANCIA = 2

// =============================================================================
// Fábricas de estado
// =============================================================================

function crearTransmision(parcial: Record<string, unknown> = {}) {
  return {
    estado: 'APAGADO',
    iniciada_en: null,
    en_vivo_desde: null,
    cuenta_regresiva_segundos: null,
    segundos_restantes: null,
    ...parcial,
  }
}

/**
 * Estado técnico con una biblioteca deliberadamente larga y muchos eventos.
 *
 * La biblioteca larga es un caso obligatorio del WP: es el único panel de los dos tercios
 * izquierdos autorizado a desplazarse, y sólo puede demostrarse con más mensajes de los
 * que entran en su columna.
 */
function crearEstadoTecnico(parcial: Record<string, unknown> = {}) {
  return {
    instancia: 'instancia-prueba',
    revision: 1,
    generado_en: '2026-09-02T10:00:00Z',
    estado_global: 'SESION_ABIERTA',
    transmision: crearTransmision(),
    aviso_moderacion: null,
    aviso_recinto: null,
    biblioteca: {
      disponible: true,
      motivo: null,
      detalle: null,
      mensajes: Array.from({ length: 14 }, (_, indice) => ({
        mensaje_id: `m-${indice + 1}`,
        texto: `Mensaje precargado número ${indice + 1} del cuerpo institucional`,
        destino: indice % 2 === 0 ? 'AMBOS' : 'RECINTO',
      })),
    },
    eventos_recientes: Array.from({ length: 25 }, (_, indice) => ({
      seq: indice + 1,
      timestamp: `2026-09-02 09:59:${String(indice).padStart(2, '0')}`,
      nivel: indice % 3 === 0 ? 'L3' : indice % 3 === 1 ? 'L2' : 'L1',
      etiqueta: 'SESION',
      codigo_evento: `EVENTO_${indice + 1}`,
      mensaje: `Mensaje del evento ${indice + 1}`,
      hecho: null,
    })),
    auditoria: { activa: true, disponible: true, fallado: false, cerrado: false, motivo: null },
    remapeo: crearRemapeoTecnico(),
    sonorizacion: crearSonorizacion(),
    ...parcial,
  }
}

/**
 * Allowlist de remapeo dentro del estado técnico (WP-074).
 *
 * Antes de WP-074 estos datos llegaban en un `EstadoModeracion` completo, por una
 * suscripción propia del puesto. Ahora viajan acá, así que el doble del navegador debe
 * entregarlos por este camino para que el panel se dibuje igual que en producción.
 */
function crearRemapeoTecnico(operacion: unknown = null) {
  return {
    remapeo: operacion,
    concejales: Array.from({ length: 12 }, (_, indice) => ({
      dni: `1000000${indice}`,
      nombre: `Nombre${indice + 1}`,
      apellido: `Apellido${indice + 1}`,
      banca: indice + 1,
      dispositivo_votacion: `dev${String(indice + 1).padStart(2, '0')}`,
    })),
    capacidades: {
      iniciar_remapeo: { habilitada: true, motivos: [] },
      confirmar_remapeo: { habilitada: false, motivos: ['REMAPEO_NO_COINCIDE'] },
      cancelar_remapeo: { habilitada: true, motivos: [] },
    },
  }
}

/** Subproyección sonora mínima: estas pruebas miden geometría, no audio. */
function crearSonorizacion() {
  return {
    revision: 1,
    estado_global: 'SESION_ABIERTA',
    tecnico: { transmision: crearTransmision(), aviso: null },
    palabra: { cola: [], orador: null },
    votacion: null,
    concejales: [],
    sonidos: { disponible: true, motivo: null, detalle: null, sonidos: [] },
  }
}

function crearAvisoVigente(texto: string, destino: string) {
  return {
    aviso_id: `aviso-${destino.toLowerCase()}`,
    texto,
    destino,
    publicado_en: '2026-09-02T10:00:00Z',
    expira_en: null,
    segundos_restantes: null,
  }
}

/** Remapeo en curso; sirve para el caso de contenido abundante del panel de Remapeo. */
const REMAPEO_CAPTURANDO = {
  estado: 'CAPTURANDO',
  dispositivo: 'dev07',
  fingerprint_anterior: 'usb-0000:00:14.0-2/input0-1a2b3c4d5e6f7890',
  candidato: null,
  diagnostico: null,
  iniciado_en: '2026-09-02T10:00:00Z',
}

// =============================================================================
// Doble determinista del backend
// =============================================================================

/** Instala el mismo doble de SSE + REST que usa la suite de WP-056. */
async function instalarBackend(page: Page, estados: Record<string, unknown>): Promise<void> {
  await page.addInitScript((iniciales) => {
    type Escucha = (evento: { type: string; data?: string }) => void
    const mapa = iniciales as Record<string, unknown>

    function resolver(url: string): unknown | null {
      for (const [clave, estado] of Object.entries(mapa)) {
        if (url.includes(clave)) return estado
      }
      return null
    }

    class FuentePrueba {
      cerrada = false
      onopen: Escucha | null = null
      onerror: Escucha | null = null
      onmessage: Escucha | null = null
      escuchas: Record<string, Escucha[]> = {}

      constructor(readonly url: string) {
        setTimeout(() => {
          if (this.cerrada) return
          this.onopen?.({ type: 'open' })
          const estado = resolver(this.url)
          if (estado === null) return
          for (const escuchar of this.escuchas.estado ?? []) {
            escuchar({ type: 'estado', data: JSON.stringify(estado) })
          }
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
    window.EventSource = FuentePrueba

    const fetchOriginal = window.fetch.bind(window)
    window.fetch = async (entrada: RequestInfo | URL, opciones?: RequestInit) => {
      const url =
        typeof entrada === 'string' ? entrada : entrada instanceof URL ? entrada.href : entrada.url
      const estado = resolver(url)
      if (estado !== null) {
        return new Response(JSON.stringify(estado), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      return fetchOriginal(entrada, opciones)
    }
  }, estados)
}

/**
 * Abre el puesto técnico con los estados indicados y espera a que la grilla esté armada.
 *
 * Devolver la promesa ya resuelta evita repetir en cada prueba la misma secuencia de
 * viewport, doble de backend, navegación y espera del primer snapshot.
 */
async function abrirPuestoTecnico(
  page: Page,
  viewport: { width: number; height: number },
  opciones: { remapeo?: unknown; avisos?: Record<string, unknown> } = {},
): Promise<void> {
  await page.setViewportSize(viewport)
  await instalarBackend(page, {
    '/api/v1/estado/tecnico': crearEstadoTecnico({
      ...(opciones.avisos ?? {}),
      ...(opciones.remapeo === undefined ? {} : { remapeo: crearRemapeoTecnico(opciones.remapeo) }),
    }),
  })
  await page.goto(URL_TECNICO)
  await expect(page.getByTestId('grilla-tecnica')).toBeVisible()
  await expect(page.getByTestId('estado-conexion')).toHaveText('Conectado')
}

/** Caja de un elemento identificado por `data-testid`. Falla si no existe. */
async function caja(page: Page, testid: string) {
  const rectangulo = await page.getByTestId(testid).boundingBox()
  expect(rectangulo, `no se encontró la caja de ${testid}`).not.toBeNull()
  return rectangulo!
}

/** Desborde del documento; es la definición operativa de "sin scroll global". */
async function medirDocumento(page: Page) {
  return page.evaluate(() => {
    const raiz = document.documentElement
    return {
      scrollHeight: raiz.scrollHeight,
      clientHeight: raiz.clientHeight,
      scrollWidth: raiz.scrollWidth,
      clientWidth: raiz.clientWidth,
    }
  })
}

function esperarSinScrollGlobal(medidas: Awaited<ReturnType<typeof medirDocumento>>): void {
  expect(medidas.scrollHeight).toBeLessThanOrEqual(medidas.clientHeight + 1)
  expect(medidas.scrollWidth).toBeLessThanOrEqual(medidas.clientWidth + 1)
}

/**
 * Mide el cuerpo con scroll de un panel.
 *
 * `PanelTecnico` confina el desborde a un único contenedor interno rotulado
 * `cuerpo-panel-tecnico`; comparar su `scrollHeight` con su `clientHeight` es la forma
 * directa de responder "¿este panel scrollea?" sin mirar clases CSS.
 */
async function medirCuerpoPanel(page: Page, testidPanel: string) {
  return page.evaluate((testid) => {
    const panel = document.querySelector(`[data-testid="${testid}"]`)!
    const cuerpo = panel.querySelector('[data-testid="cuerpo-panel-tecnico"]')!
    return {
      scrollHeight: cuerpo.scrollHeight,
      clientHeight: cuerpo.clientHeight,
      scrollWidth: cuerpo.scrollWidth,
      clientWidth: cuerpo.clientWidth,
    }
  }, testidPanel)
}

function esperarPanelSinScroll(
  medidas: Awaited<ReturnType<typeof medirCuerpoPanel>>,
  panel: string,
): void {
  expect(medidas.scrollHeight, `${panel} no debería scrollear en vertical`).toBeLessThanOrEqual(
    medidas.clientHeight + 1,
  )
  expect(medidas.scrollWidth, `${panel} no debería scrollear en horizontal`).toBeLessThanOrEqual(
    medidas.clientWidth + 1,
  )
}

// =============================================================================
// 1. Reparto de columnas y filas
// =============================================================================

for (const viewport of RESOLUCIONES) {
  test(`la grilla técnica reparte cuatro columnas visuales en ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    await abrirPuestoTecnico(page, viewport)

    const grilla = await caja(page, 'grilla-tecnica')
    const transmisionCaja = await caja(page, 'panel-transmision')
    const remapeoCaja = await caja(page, 'panel-remapeo-tecnico')
    const bibliotecaCaja = await caja(page, 'panel-biblioteca')
    const avisosCaja = await caja(page, 'panel-avisos')
    const eventosCaja = await caja(page, 'panel-eventos-tecnico')

    // 1. Eventos conserva aproximadamente el tercio derecho.
    const proporcionEventos = eventosCaja.width / grilla.width
    expect(proporcionEventos).toBeGreaterThan(0.29)
    expect(proporcionEventos).toBeLessThan(0.38)
    expect(eventosCaja.x).toBeGreaterThan(bibliotecaCaja.x + bibliotecaCaja.width - 1)
    expect(eventosCaja.x + eventosCaja.width).toBeLessThanOrEqual(
      grilla.x + grilla.width + TOLERANCIA,
    )

    // 2. Eventos ocupa todo el alto útil de la grilla: arranca con la primera fila y
    //    termina con la segunda.
    expect(Math.abs(eventosCaja.y - grilla.y)).toBeLessThanOrEqual(TOLERANCIA)
    expect(
      Math.abs(eventosCaja.y + eventosCaja.height - (grilla.y + grilla.height)),
    ).toBeLessThanOrEqual(TOLERANCIA)

    /*
      3. Los tres paneles superiores comparten la fila.

      Hasta WP-070 los tres tenían además el mismo ancho. Ese empate dejó de ser posible:
      la fila «destino + tres acciones» de cada mensaje precargado no entra en un tercio de
      los dos tercios izquierdos a 1366×768, y HUMAN_GATE autorizó darle a Mensajes el
      ancho mínimo que necesita. Lo que sigue siendo cierto —y es lo que WP-059 cerró— es
      que los tres comparten fila, alto y una escala comparable entre sí; por eso acá se
      exige que Transmisión y Remapeo sigan siendo idénticos entre ellos y que Mensajes
      sea más ancho, pero sin llegar a duplicarlos.
    */
    expect(Math.abs(remapeoCaja.width - transmisionCaja.width)).toBeLessThanOrEqual(TOLERANCIA)
    expect(bibliotecaCaja.width).toBeGreaterThan(transmisionCaja.width)
    expect(bibliotecaCaja.width).toBeLessThan(transmisionCaja.width * 1.5)
    for (const otro of [remapeoCaja, bibliotecaCaja]) {
      expect(Math.abs(otro.y - transmisionCaja.y)).toBeLessThanOrEqual(TOLERANCIA)
      expect(Math.abs(otro.height - transmisionCaja.height)).toBeLessThanOrEqual(TOLERANCIA)
    }
    expect(remapeoCaja.x).toBeGreaterThan(transmisionCaja.x + transmisionCaja.width - 1)
    expect(bibliotecaCaja.x).toBeGreaterThan(remapeoCaja.x + remapeoCaja.width - 1)

    // 4. Las tres columnas izquierdas suman aproximadamente dos tercios del ancho.
    const anchoIzquierdo = bibliotecaCaja.x + bibliotecaCaja.width - transmisionCaja.x
    const proporcionIzquierda = anchoIzquierdo / grilla.width
    expect(proporcionIzquierda).toBeGreaterThan(0.62)
    expect(proporcionIzquierda).toBeLessThan(0.71)

    // 5. Avisos ocupa la fila inferior completa de esas tres columnas: mismo borde
    //    izquierdo que Transmisión, mismo borde derecho que Biblioteca.
    expect(Math.abs(avisosCaja.x - transmisionCaja.x)).toBeLessThanOrEqual(TOLERANCIA)
    expect(
      Math.abs(avisosCaja.x + avisosCaja.width - (bibliotecaCaja.x + bibliotecaCaja.width)),
    ).toBeLessThanOrEqual(TOLERANCIA)
    expect(avisosCaja.y).toBeGreaterThan(transmisionCaja.y + transmisionCaja.height - 1)
    expect(
      Math.abs(avisosCaja.y + avisosCaja.height - (grilla.y + grilla.height)),
    ).toBeLessThanOrEqual(TOLERANCIA)

    // 6. Avisos es la superficie de trabajo grande: se queda con la fila más alta.
    expect(avisosCaja.height).toBeGreaterThan(transmisionCaja.height)

    // 7. Ninguna de las dos dimensiones del documento desborda.
    esperarSinScrollGlobal(await medirDocumento(page))
  })
}

// =============================================================================
// 2. Confinamiento del scroll
// =============================================================================

for (const viewport of RESOLUCIONES) {
  test(`sólo Biblioteca y Eventos se desplazan en ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    await abrirPuestoTecnico(page, viewport, {
      avisos: {
        aviso_moderacion: crearAvisoVigente('Cuarto intermedio de quince minutos', 'MODERACION'),
        aviso_recinto: crearAvisoVigente('Se reanuda la sesión en instantes', 'RECINTO'),
      },
    })

    // Transmisión, Remapeo y Avisos operan sin scroll de panel.
    for (const panel of ['panel-transmision', 'panel-remapeo-tecnico', 'panel-avisos']) {
      esperarPanelSinScroll(await medirCuerpoPanel(page, panel), panel)
    }

    // La biblioteca larga sí se desplaza: es el único panel de los dos tercios izquierdos
    // autorizado a tener scroll interno permanente.
    const biblioteca = await medirCuerpoPanel(page, 'panel-biblioteca')
    expect(biblioteca.scrollHeight).toBeGreaterThan(biblioteca.clientHeight)
    expect(biblioteca.scrollWidth).toBeLessThanOrEqual(biblioteca.clientWidth + 1)

    // Eventos conserva su scroll propio, y lo hace dentro de su lista, no del panel. Se
    // abre el nivel acumulativo L1 para que la franja tenga más filas de las que entran:
    // con el filtro L3 predeterminado la columna es tan alta que ni siquiera se llena.
    await page.getByTestId('filtro-eventos-tecnico').selectOption('L1')
    const eventos = await medirCuerpoPanel(page, 'panel-eventos-tecnico')
    esperarPanelSinScroll(eventos, 'panel-eventos-tecnico')
    const lista = await page.evaluate(() => {
      const elemento = document.querySelector('[data-testid="lista-eventos-tecnico"]')!
      return { scrollHeight: elemento.scrollHeight, clientHeight: elemento.clientHeight }
    })
    expect(lista.scrollHeight).toBeGreaterThan(lista.clientHeight)

    esperarSinScrollGlobal(await medirDocumento(page))
  })

  test(`el panel de Avisos no scrollea con contenido corto ni abundante en ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    await abrirPuestoTecnico(page, viewport)

    // Caso corto: textarea vacío.
    esperarPanelSinScroll(await medirCuerpoPanel(page, 'panel-avisos'), 'panel-avisos')
    const textareaCorto = await page.evaluate(() => {
      const campo = document.querySelector(
        '[data-testid="input-texto-aviso"]',
      ) as HTMLTextAreaElement
      return { scrollHeight: campo.scrollHeight, clientHeight: campo.clientHeight }
    })
    expect(textareaCorto.scrollHeight).toBeLessThanOrEqual(textareaCorto.clientHeight + 1)

    // Caso abundante: el máximo que admite el contrato, 500 caracteres.
    const textoLargo = 'Comunicación institucional del Concejo Deliberante. '
      .repeat(10)
      .slice(0, 500)
    await page.getByTestId('input-texto-aviso').fill(textoLargo)

    // El textarea usa su superficie y sólo entonces adquiere scroll propio; el panel, no.
    const textareaLargo = await page.evaluate(() => {
      const campo = document.querySelector(
        '[data-testid="input-texto-aviso"]',
      ) as HTMLTextAreaElement
      return {
        scrollHeight: campo.scrollHeight,
        clientHeight: campo.clientHeight,
        alto: Math.round(campo.getBoundingClientRect().height),
      }
    })
    // La superficie de escritura es realmente grande, no un campo de dos renglones.
    expect(textareaLargo.alto).toBeGreaterThan(120)
    esperarPanelSinScroll(await medirCuerpoPanel(page, 'panel-avisos'), 'panel-avisos')
    esperarSinScrollGlobal(await medirDocumento(page))
  })
}

test('el textarea de Avisos scrollea solo cuando el texto supera su superficie', async ({
  page,
}) => {
  // Se usa la resolución chica porque es donde el textarea tiene menos alto disponible y
  // el umbral se cruza con menos texto.
  await abrirPuestoTecnico(page, RESOLUCIONES[1])

  const campo = page.getByTestId('input-texto-aviso')
  await campo.fill('Aviso breve')
  const corto = await page.evaluate(() => {
    const elemento = document.querySelector(
      '[data-testid="input-texto-aviso"]',
    ) as HTMLTextAreaElement
    return { scrollHeight: elemento.scrollHeight, clientHeight: elemento.clientHeight }
  })
  expect(corto.scrollHeight).toBeLessThanOrEqual(corto.clientHeight + 1)

  // Muchas líneas cortas fuerzan el desborde vertical sin llegar al máximo de caracteres.
  await campo.fill(Array.from({ length: 40 }, (_, indice) => `Línea ${indice + 1}`).join('\n'))
  const desbordado = await page.evaluate(() => {
    const elemento = document.querySelector(
      '[data-testid="input-texto-aviso"]',
    ) as HTMLTextAreaElement
    return { scrollHeight: elemento.scrollHeight, clientHeight: elemento.clientHeight }
  })
  expect(desbordado.scrollHeight).toBeGreaterThan(desbordado.clientHeight)

  // Aun así el panel y la página siguen sin scroll: el desborde muere en el campo.
  esperarPanelSinScroll(await medirCuerpoPanel(page, 'panel-avisos'), 'panel-avisos')
  esperarSinScrollGlobal(await medirDocumento(page))
})

// =============================================================================
// 3. Remapeo en curso: contenido abundante del panel más denso
// =============================================================================

for (const viewport of RESOLUCIONES) {
  test(`un remapeo en curso no rompe la grilla en ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    await abrirPuestoTecnico(page, viewport, { remapeo: REMAPEO_CAPTURANDO })

    await expect(page.getByTestId('remapeo-activo')).toBeVisible()

    // El panel conserva exactamente su celda: el contenido abundante no empuja a nadie.
    const remapeoCaja = await caja(page, 'panel-remapeo-tecnico')
    const transmisionCaja = await caja(page, 'panel-transmision')
    expect(Math.abs(remapeoCaja.height - transmisionCaja.height)).toBeLessThanOrEqual(TOLERANCIA)
    expect(Math.abs(remapeoCaja.y - transmisionCaja.y)).toBeLessThanOrEqual(TOLERANCIA)

    // Nunca hay desborde horizontal, en ninguna resolución.
    const medidas = await medirCuerpoPanel(page, 'panel-remapeo-tecnico')
    expect(medidas.scrollWidth).toBeLessThanOrEqual(medidas.clientWidth + 1)

    esperarSinScrollGlobal(await medirDocumento(page))
  })
}

test('en 1920×1080 el remapeo en curso entra sin scroll de panel', async ({ page }) => {
  // A 1920×1080 la fila superior alcanza para el remapeo desplegado completo. A 1366×768
  // el mismo contenido excede la celda y usa el scroll defensivo del cuerpo del panel:
  // eso está medido en la prueba anterior, que comprueba que la grilla no se rompe.
  await abrirPuestoTecnico(page, RESOLUCIONES[0], { remapeo: REMAPEO_CAPTURANDO })
  await expect(page.getByTestId('remapeo-activo')).toBeVisible()
  esperarPanelSinScroll(
    await medirCuerpoPanel(page, 'panel-remapeo-tecnico'),
    'panel-remapeo-tecnico',
  )
})

// =============================================================================
// 4. Cabecera
// =============================================================================

test('la cabecera técnica conserva sus indicadores y ya no muestra la marca del sistema', async ({
  page,
}) => {
  await abrirPuestoTecnico(page, RESOLUCIONES[0])

  const cabecera = page.getByTestId('cabecera-tecnico')
  await expect(cabecera).not.toContainText('Botonera2')
  await expect(cabecera).toContainText('Apoyo Técnico')

  // Ningún indicador se perdió al recortar el título.
  await expect(page.getByTestId('estado-global-tecnico')).toHaveText('Sesión abierta')
  await expect(page.getByTestId('resumen-transmision')).toHaveText('Transmisión apagada')
  await expect(page.getByTestId('estado-conexion')).toHaveText('Conectado')
})

// =============================================================================
// 5. Regresión funcional de todas las capacidades del puesto
// =============================================================================

test('la redistribución conserva todas las operaciones del puesto técnico', async ({ page }) => {
  const comandos: string[] = []
  await page.route('**/api/v1/apoyo-tecnico/**', async (ruta) => {
    comandos.push(`${ruta.request().method()} ${new URL(ruta.request().url()).pathname}`)
    await ruta.fulfill({ status: 204, body: '' })
  })
  await page.route('**/api/v1/remapeos**', async (ruta) => {
    comandos.push(`${ruta.request().method()} ${new URL(ruta.request().url()).pathname}`)
    await ruta.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ remapeo_id: 'rm-1', estado: 'CAPTURANDO' }),
    })
  })

  await abrirPuestoTecnico(page, RESOLUCIONES[1], {
    avisos: { aviso_recinto: crearAvisoVigente('Aviso vigente en el Recinto', 'RECINTO') },
  })

  // Transmisión: instantánea, con cuenta y detención.
  await page.getByTestId('btn-transmision-instantanea').click()
  await page.getByTestId('input-cuenta-regresiva').fill('20')
  await page.getByTestId('btn-transmision-cuenta').click()

  // Avisos: publicar con destino y duración, y cancelar la ranura vigente.
  await page.getByTestId('input-texto-aviso').fill('Aviso publicado desde la nueva grilla')
  await page.getByTestId('select-destino-aviso').selectOption('RECINTO')
  await page.getByTestId('input-duracion-aviso').fill('45')
  await page.getByTestId('btn-publicar-aviso').click()
  await page.getByTestId('btn-cancelar-recinto').click()

  // Biblioteca: alta y uso de un preset ya persistido.
  await page.getByTestId('input-mensaje-nuevo').fill('Nuevo mensaje precargado')
  await page.getByTestId('btn-crear-mensaje').click()
  await page.getByTestId('mensaje-precargado').first().getByTestId('btn-cargar-mensaje').click()
  await expect(page.getByTestId('input-texto-aviso')).toHaveValue(
    'Mensaje precargado número 1 del cuerpo institucional',
  )

  // Remapeo: la operación completa sigue disponible desde este puesto.
  await page.getByTestId('selector-banca-remapeo').selectOption('dev03')
  await page.getByTestId('btn-iniciar-remapeo').click()

  // Eventos: el filtro acumulativo sigue funcionando dentro de su columna.
  const soloL3 = await page.getByTestId('evento-tecnico').count()
  await page.getByTestId('filtro-eventos-tecnico').selectOption('L1')
  expect(await page.getByTestId('evento-tecnico').count()).toBeGreaterThan(soloL3)

  await expect
    .poll(() => comandos)
    .toEqual(
      expect.arrayContaining([
        'POST /api/v1/apoyo-tecnico/transmision',
        'POST /api/v1/apoyo-tecnico/avisos',
        'DELETE /api/v1/apoyo-tecnico/avisos/RECINTO',
        'POST /api/v1/apoyo-tecnico/mensajes',
        'POST /api/v1/remapeos',
      ]),
    )

  esperarSinScrollGlobal(await medirDocumento(page))
})
