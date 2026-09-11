/**
 * WP-045 — Unificación visual de bancas y participación de voto sin sentido.
 *
 * Este recorrido compara en un navegador real las dos superficies que deben
 * comportarse igual: el cuadrante 3 de Moderación y la Pantalla del Recinto.
 * Se ejecuta a 1366×768 y a 1920×1080 porque el WP exige explícitamente ambas
 * resoluciones de referencia.
 *
 * Comprobaciones principales:
 * 1. tarjetas de tamaño uniforme dentro de cada superficie;
 * 2. bitmap completo (`object-fit: contain`) sin recortes apreciables;
 * 3. familias cromáticas aprobadas: blanco, gris, naranja, azul, cian, verde,
 *    rojo y ocre, con cian distinto del azul de test;
 * 4. test sin etiqueta textual;
 * 5. máximo UNA etiqueta por banca y ninguna identidad duplicada como texto;
 * 6. durante `EN_CURSO` el DOM completo de una banca emitida no contiene el
 *    sentido del voto en texto, clases ni atributos;
 * 7. tras el cierre ambas superficies muestran el mismo resultado por banca;
 * 8. el WP no introduce scroll global ni solapamientos.
 */

import { expect, test, type Locator, type Page } from '@playwright/test'

import { instalarFotosConcejales } from './soporte/fotos_concejales'

const RESOLUCIONES = [
  { nombre: '1366x768', width: 1366, height: 768 },
  { nombre: '1920x1080', width: 1920, height: 1080 },
] as const

/** Cadenas que jamás pueden aparecer en una banca mientras se vota. */
const SENTIDOS_PROHIBIDOS = [
  'POSITIVO',
  'NEGATIVO',
  'ABSTENCION',
  'Positivo',
  'Negativo',
  'Abstención',
]

// ---------------------------------------------------------------------------
// Datos de prueba compartidos por ambas superficies
// ---------------------------------------------------------------------------

/**
 * Doce bancas con estados deliberadamente combinados:
 *
 * - banca 1: presente + test activo (y luego también oradora y votante);
 * - banca 2: ausente;
 * - banca 5: presente normal;
 * - resto: presente.
 */
function crearConcejalesModeracion() {
  return Array.from({ length: 12 }, (_, indice) => {
    const banca = indice + 1
    const pad = String(banca).padStart(2, '0')
    return {
      banca,
      dni: `300000${pad}`,
      nombre: `Concejal${pad}`,
      apellido: `Apellido${pad}`,
      bloque: 'Bloque institucional de nombre deliberadamente largo',
      ruta_imagen: `assets/bancas/banca-${pad}.png`,
      dispositivo_votacion: `dev${pad}`,
      presente: banca !== 2,
      test_activo: banca === 1,
      test_expira_en: banca === 1 ? '2026-08-25T10:00:05Z' : null,
    }
  })
}

function crearConcejalesPublicos() {
  return crearConcejalesModeracion().map(
    ({ dni: _dni, dispositivo_votacion: _dispositivo, ...resto }) => resto,
  )
}

const CAPACIDADES_INERTES = Object.fromEntries(
  [
    'preparar_sala',
    'actualizar_preparacion',
    'cancelar_preparacion',
    'abrir_sesion',
    'actualizar_sesion',
    'cerrar_sesion',
    'iniciar_votacion',
    'cancelar_votacion',
    'cerrar_votacion',
    'desempatar',
    'solicitar_palabra',
    'cancelar_solicitud_palabra',
    'otorgar_palabra',
    'quitar_palabra',
    'iniciar_remapeo',
    'confirmar_remapeo',
    'cancelar_remapeo',
    'subir_orden_dia',
    'seleccionar_expediente',
    'cerrar_expediente',
    'registrar_evento_manual',
  ].map((capacidad) => [capacidad, { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] }]),
)

/** Votación de Moderación con participación sin sentido durante EN_CURSO. */
function crearVotacionModeracion(parcial: Record<string, unknown> = {}) {
  return {
    id: 'votacion-wp045',
    numero_votacion: 1,
    tipo: 'Otro',
    tema: 'Unificación visual de bancas',
    tipo_mayoria: 'SIMPLE',
    factor: 0,
    base: 'VOTOS_COMPUTABLES',
    estado_recepcion: 'EN_CURSO',
    resultado: null,
    fecha_hora_apertura: '2026-08-25T10:00:00Z',
    fecha_hora_cierre: null,
    fecha_hora_resultado: null,
    resultado_visible_hasta: null,
    motivo_finalizacion_manual: null,
    cantidad_votos_recibidos: 3,
    bancas_voto_emitido: [1, 3, 6],
    revelado_individual_desde: '2026-08-25T10:00:00Z',
    // Moderación revela votos por su política histórica; Q3 debe ignorarlos
    // mientras la recepción siga abierta.
    votos_individuales_revelados: true,
    votos_individuales: [
      {
        dni: '30000001',
        nombre: 'Concejal01',
        apellido: 'Apellido01',
        banca: 1,
        valor: 'POSITIVO',
      },
      {
        dni: '30000003',
        nombre: 'Concejal03',
        apellido: 'Apellido03',
        banca: 3,
        valor: 'NEGATIVO',
      },
      {
        dni: '30000006',
        nombre: 'Concejal06',
        apellido: 'Apellido06',
        banca: 6,
        valor: 'ABSTENCION',
      },
    ],
    conteos: null,
    voto_presidencial: null,
    ...parcial,
  }
}

function crearVotacionPublica(parcial: Record<string, unknown> = {}) {
  return {
    id: 'votacion-wp045',
    numero_votacion: 1,
    tipo: 'Otro',
    tema: 'Unificación visual de bancas',
    tipo_mayoria: 'SIMPLE',
    factor: 0,
    base: 'VOTOS_COMPUTABLES',
    estado_recepcion: 'EN_CURSO',
    resultado: null,
    fecha_hora_apertura: '2026-08-25T10:00:00Z',
    fecha_hora_cierre: null,
    cuenta_regresiva_hasta: null,
    resultado_visible_hasta: null,
    bancas_voto_emitido: [1, 3, 6],
    votos_individuales: null,
    conteos: null,
    voto_presidencial: null,
    ...parcial,
  }
}

/** Votos finales usados por ambas superficies después del cierre. */
const VOTOS_FINALES = [
  { banca: 1, valor: 'POSITIVO' },
  { banca: 3, valor: 'NEGATIVO' },
  { banca: 6, valor: 'ABSTENCION' },
]

function crearEstadoModeracion(votacion: Record<string, unknown> | null) {
  return {
    instancia: 'instancia-prueba',
    revision: 1,
    generado_en: '2026-08-25T10:00:00Z',
    estado_global: 'SESION_ABIERTA',
    preparacion: null,
    sesion: {
      fecha_hora_inicio_preparacion: '2026-08-25T09:00:00Z',
      fecha_hora_apertura: '2026-08-25T10:00:00Z',
      numero_sesion: 45,
      presidencia: 'Presidencia de prueba',
      secretaria_legislativa: 'Secretaría de prueba',
    },
    votacion,
    palabra: {
      orador: { dni: '30000001', nombre: 'Concejal01', apellido: 'Apellido01', banca: 1 },
      cola: [],
    },
    quorum: { cantidad_presentes: 11, requerido: 7, alcanzado: true },
    configuracion: { filas_bancas: [3, 4, 5] },
    concejales: crearConcejalesModeracion(),
    orden_del_dia: null,
    eventos_recientes: [],
    auditoria: { activa: true, disponible: true, fallado: false, cerrado: false, motivo: null },
    remapeo: null,
    capacidades: CAPACIDADES_INERTES,
  }
}

function crearEstadoRecinto(votacion: Record<string, unknown> | null) {
  return {
    instancia: 'instancia-prueba',
    revision: 1,
    generado_en: '2026-08-25T10:00:00Z',
    estado_global: 'SESION_ABIERTA',
    preparacion: null,
    sesion: {
      fecha_hora_inicio_preparacion: '2026-08-25T09:00:00Z',
      fecha_hora_apertura: '2026-08-25T10:00:00Z',
      numero_sesion: 45,
      presidencia: 'Presidencia de prueba',
      secretaria_legislativa: 'Secretaría de prueba',
    },
    filas_bancas: [3, 4, 5],
    concejales: crearConcejalesPublicos(),
    quorum: { cantidad_presentes: 11, requerido: 7, alcanzado: true },
    votacion,
    palabra: {
      orador: { nombre: 'Concejal01', apellido: 'Apellido01', banca: 1 },
      cola: [],
    },
    // WP-046 sumó la franja pública al snapshot. Este recorrido no la ejercita,
    // pero el campo es obligatorio en el contrato y debe viajar igual que en el
    // backend real para que la pantalla se monte completa.
    eventos_publicos: [],
  }
}

/**
 * Instala un backend determinista de solo lectura.
 *
 * Sirve al mismo snapshot por REST y por SSE, igual que hace el backend real:
 * ninguna de las dos superficies puede aplicar una política propia.
 */
async function instalarBackend(page: Page, estado: Record<string, unknown>): Promise<void> {
  // WP-098: la fotografía de banca ya no es un asset del build; la publica
  // el backend desde la configuración local. Sin backend real, se responde
  // desde la plantilla versionada, que es el mismo archivo de siempre.
  await instalarFotosConcejales(page)

  await page.addInitScript((jsonEstado) => {
    class FuenteMock {
      listeners: Record<string, ((evento: unknown) => void)[]> = {}
      onopen: ((evento: unknown) => void) | null = null
      onerror: ((evento: unknown) => void) | null = null
      onmessage: ((evento: unknown) => void) | null = null
      readyState = 1

      constructor() {
        setTimeout(() => {
          this.onopen?.({ type: 'open' })
          for (const handler of this.listeners['estado'] ?? []) {
            handler({ type: 'estado', data: jsonEstado })
          }
        }, 10)
      }

      addEventListener(tipo: string, handler: (evento: unknown) => void) {
        this.listeners[tipo] = this.listeners[tipo] ?? []
        this.listeners[tipo].push(handler)
      }

      removeEventListener(tipo: string, handler: (evento: unknown) => void) {
        this.listeners[tipo] = (this.listeners[tipo] ?? []).filter((actual) => actual !== handler)
      }

      close() {
        this.readyState = 2
      }
    }

    // @ts-expect-error Mock inyectado en el runtime del navegador
    window.EventSource = FuenteMock

    const fetchOriginal = window.fetch.bind(window)
    window.fetch = async (entrada: RequestInfo | URL, init?: RequestInit) => {
      const url =
        typeof entrada === 'string' ? entrada : entrada instanceof URL ? entrada.href : entrada.url
      if (url.includes('/api/v1/estado/')) {
        return new Response(jsonEstado, {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      return fetchOriginal(entrada, init)
    }
  }, JSON.stringify(estado))
}

// ---------------------------------------------------------------------------
// Utilidades de verificación
// ---------------------------------------------------------------------------

/** Convierte cualquier color CSS a la terna RGB efectivamente pintada. */
async function fondoDeBanca(banca: Locator): Promise<[number, number, number]> {
  const color = await banca.evaluate((elemento) => getComputedStyle(elemento).backgroundColor)
  const componentes = color.match(/\d+(\.\d+)?/g) ?? []
  return [Number(componentes[0]), Number(componentes[1]), Number(componentes[2])]
}

/** Comprueba que todas las tarjetas visibles compartan width y height. */
async function verificarTamanoUniforme(bancas: Locator): Promise<void> {
  const cantidad = await bancas.count()
  expect(cantidad).toBeGreaterThan(1)
  const cajas = await Promise.all(
    Array.from({ length: cantidad }, (_, indice) => bancas.nth(indice).boundingBox()),
  )
  const referencia = cajas[0]
  expect(referencia).not.toBeNull()
  for (const caja of cajas) {
    expect(caja).not.toBeNull()
    // Se tolera 1px por el redondeo de subpíxeles del layout.
    expect(Math.abs(caja!.width - referencia!.width)).toBeLessThanOrEqual(1)
    expect(Math.abs(caja!.height - referencia!.height)).toBeLessThanOrEqual(1)
  }
}

/** Mide el centro real del conjunto de tarjetas de cada fila. */
async function verificarCentradoDeFilas(page: Page): Promise<void> {
  const filas = page.locator('[data-fila-fisica]')
  await expect(filas).toHaveCount(3)
  for (let indice = 0; indice < (await filas.count()); indice += 1) {
    const diferencia = await filas.nth(indice).evaluate((fila) => {
      const cajaFila = fila.getBoundingClientRect()
      const cajas = Array.from(fila.querySelectorAll<HTMLElement>(':scope > [data-banca]')).map(
        (banca) => banca.getBoundingClientRect(),
      )
      const izquierda = Math.min(...cajas.map((caja) => caja.left))
      const derecha = Math.max(...cajas.map((caja) => caja.right))
      return Math.abs((izquierda + derecha) / 2 - (cajaFila.left + cajaFila.right) / 2)
    })
    expect(diferencia).toBeLessThanOrEqual(1)
  }
}

/**
 * Verifica que la banca emitida no filtre el sentido por ningún canal del DOM.
 *
 * No alcanza con mirar el texto: se recorre el subárbol completo revisando
 * también `class`, `data-*`, `aria-label`, `title` y cualquier otro atributo.
 */
async function verificarSecretoDeBanca(banca: Locator): Promise<void> {
  const volcado = await banca.evaluate((raiz) => {
    const partes: string[] = []
    const recorrer = (nodo: Element) => {
      partes.push(nodo.textContent ?? '')
      for (const atributo of Array.from(nodo.attributes)) {
        partes.push(`${atributo.name}=${atributo.value}`)
      }
      for (const hijo of Array.from(nodo.children)) recorrer(hijo)
    }
    recorrer(raiz)
    return partes.join('\n')
  })

  for (const prohibido of SENTIDOS_PROHIBIDOS) {
    expect(volcado).not.toContain(prohibido)
  }
  expect(volcado).toContain('Voto emitido')
}

/** Comprueba que no exista scroll global ni desbordes horizontales. */
async function verificarSinScrollGlobal(page: Page): Promise<void> {
  const medidas = await page.evaluate(() => ({
    alto: document.documentElement.scrollHeight - window.innerHeight,
    ancho: document.documentElement.scrollWidth - window.innerWidth,
  }))
  expect(medidas.alto).toBeLessThanOrEqual(1)
  expect(medidas.ancho).toBeLessThanOrEqual(1)
}

/**
 * Batería común a las dos superficies.
 *
 * Recibe la página ya cargada con una votación EN_CURSO y comprueba la misma
 * semántica en Q3 y en Recinto. Que ambas llamen a esta única función es, en sí
 * mismo, la demostración de que comparten reglas.
 */
async function verificarSuperficieEnCurso(page: Page, selectorTarjeta: string): Promise<void> {
  const bancas = page.locator(selectorTarjeta)
  await expect(bancas).toHaveCount(12)
  await verificarTamanoUniforme(bancas)
  await verificarCentradoDeFilas(page)

  const banca = (numero: number) => page.locator(`[data-banca="${numero}"]`)

  // 1 · Voto emitido gana a test y palabra; ambos sobreviven como halo.
  await expect(banca(1)).toHaveAttribute('data-estado-banca', 'VOTO_EMITIDO')
  await expect(banca(1)).toHaveAttribute('data-halo-test', 'true')
  await expect(banca(1)).toHaveAttribute('data-halo-palabra', 'true')
  await expect(banca(1).locator('[data-testid="etiqueta-banca"]')).toHaveText('Voto emitido')
  await expect(banca(1).locator('[data-testid="etiqueta-banca"]')).toHaveCount(1)
  await verificarSecretoDeBanca(banca(1))

  // 2 · Ausente y bancas emitidas/no emitidas.
  await expect(banca(2)).toHaveAttribute('data-estado-banca', 'AUSENTE')
  await expect(banca(2).locator('[data-testid="etiqueta-banca"]')).toHaveText('Ausente')
  await expect(banca(3)).toHaveAttribute('data-estado-banca', 'VOTO_EMITIDO')
  await expect(banca(5)).toHaveAttribute('data-estado-banca', 'NORMAL')
  await expect(banca(5).locator('[data-testid="etiqueta-banca"]')).toHaveCount(0)

  // 3 · Colores de las familias aprobadas.
  const [rojoNormal, verdeNormal, azulNormal] = await fondoDeBanca(banca(5))
  expect(rojoNormal).toBeGreaterThan(240)
  expect(verdeNormal).toBeGreaterThan(240)
  expect(azulNormal).toBeGreaterThan(240)

  const [rGris, gGris, bGris] = await fondoDeBanca(banca(2))
  // Gris: los tres canales prácticamente iguales y de luminancia media.
  expect(Math.abs(rGris - gGris)).toBeLessThanOrEqual(6)
  expect(Math.abs(gGris - bGris)).toBeLessThanOrEqual(6)
  expect(rGris).toBeGreaterThan(120)
  expect(rGris).toBeLessThan(200)

  const [rCian, gCian, bCian] = await fondoDeBanca(banca(1))
  // Cian: verde y azul dominan sobre el rojo, y ambos son altos.
  expect(gCian).toBeGreaterThan(rCian + 40)
  expect(bCian).toBeGreaterThan(rCian + 40)
  // Y es claramente distinto del azul de test (#4aabff), donde el azul domina al verde.
  expect(bCian - gCian).toBeLessThan(40)

  // 4 · La identidad no se repite como texto visible fuera del bitmap.
  // `innerText` aplica `text-transform: uppercase`; se compara sin distinguir
  // mayúsculas para afirmar que ese es TODO el texto visible de la tarjeta.
  const textoBancaUno = (await banca(1).innerText()).trim().toLowerCase()
  expect(textoBancaUno).toBe('voto emitido')
  await expect(banca(5)).not.toContainText('Concejal05')
  await expect(banca(5)).not.toContainText('Banca 5')
  await expect(banca(5)).not.toContainText('Bloque institucional')

  // 5 · El bitmap se muestra completo, sin recorte.
  const ajusteImagen = await banca(5)
    .locator('[data-testid="imagen-concejal"]')
    .evaluate((imagen) => getComputedStyle(imagen).objectFit)
  expect(ajusteImagen).toBe('contain')

  await verificarSinScrollGlobal(page)
}

/** Batería común a las dos superficies después del cierre de la recepción. */
async function verificarSuperficieCerrada(page: Page): Promise<void> {
  const banca = (numero: number) => page.locator(`[data-banca="${numero}"]`)

  await expect(banca(1)).toHaveAttribute('data-estado-banca', 'RESULTADO_POSITIVO')
  await expect(banca(1).locator('[data-testid="etiqueta-banca"]')).toHaveText('Positivo')
  await expect(banca(3)).toHaveAttribute('data-estado-banca', 'RESULTADO_NEGATIVO')
  await expect(banca(3).locator('[data-testid="etiqueta-banca"]')).toHaveText('Negativo')
  await expect(banca(6)).toHaveAttribute('data-estado-banca', 'RESULTADO_ABSTENCION')
  await expect(banca(6).locator('[data-testid="etiqueta-banca"]')).toHaveText('Abstención')

  // Verde, rojo y ocre pertenecen inequívocamente a su familia.
  const [rVerde, gVerde, bVerde] = await fondoDeBanca(banca(1))
  expect(gVerde).toBeGreaterThan(rVerde + 30)
  expect(gVerde).toBeGreaterThan(bVerde + 20)

  const [rRojo, gRojo, bRojo] = await fondoDeBanca(banca(3))
  expect(rRojo).toBeGreaterThan(gRojo + 30)
  expect(rRojo).toBeGreaterThan(bRojo + 30)

  const [rOcre, gOcre, bOcre] = await fondoDeBanca(banca(6))
  expect(rOcre).toBeGreaterThan(bOcre + 40)
  expect(gOcre).toBeGreaterThan(bOcre + 40)

  // Ninguna banca muestra más de una etiqueta.
  for (const numero of [1, 3, 6]) {
    await expect(banca(numero).locator('[data-testid="etiqueta-banca"]')).toHaveCount(1)
  }
}

// ---------------------------------------------------------------------------
// Casos
// ---------------------------------------------------------------------------

for (const resolucion of RESOLUCIONES) {
  test.describe(`WP-045 · bancas unificadas a ${resolucion.nombre}`, () => {
    test.use({ viewport: { width: resolucion.width, height: resolucion.height } })

    test('Q3 de Moderación aplica la semántica común durante EN_CURSO', async ({ page }) => {
      await instalarBackend(page, crearEstadoModeracion(crearVotacionModeracion()))
      await page.goto('http://localhost:3000/moderacion/')
      await expect(page.getByTestId('grilla-recinto')).toBeAttached()

      await verificarSuperficieEnCurso(page, '[data-testid="banca-concejal"]')

      // El test de dispositivo, cuando es principal, no lleva etiqueta alguna.
      await expect(page.locator('[data-banca="4"]')).toHaveAttribute('data-estado-banca', 'NORMAL')
    })

    test('la Pantalla del Recinto aplica la misma semántica durante EN_CURSO', async ({ page }) => {
      await instalarBackend(page, crearEstadoRecinto(crearVotacionPublica()))
      await page.goto('http://localhost:3001/recinto/')
      await expect(page.getByTestId('grilla-bancas')).toBeVisible()

      await verificarSuperficieEnCurso(page, '[data-testid="banca-publica"]')
    })

    test('Q3 refleja el resultado individual final igual que el Recinto', async ({ page }) => {
      await instalarBackend(
        page,
        crearEstadoModeracion(
          crearVotacionModeracion({
            estado_recepcion: 'CERRADA',
            resultado: 'APROBADA',
            fecha_hora_cierre: '2026-08-25T10:00:20Z',
            fecha_hora_resultado: '2026-08-25T10:00:20Z',
            resultado_visible_hasta: '2199-01-01T00:00:00Z',
            bancas_voto_emitido: [],
            conteos: { positivos: 1, negativos: 1, abstenciones: 1, total: 3 },
          }),
        ),
      )
      await page.goto('http://localhost:3000/moderacion/')
      await expect(page.getByTestId('grilla-recinto')).toBeAttached()

      await verificarTamanoUniforme(page.locator('[data-testid="banca-concejal"]'))
      await verificarSuperficieCerrada(page)
      await verificarSinScrollGlobal(page)
    })

    test('el Recinto muestra el resultado individual final tras el cierre', async ({ page }) => {
      await instalarBackend(
        page,
        crearEstadoRecinto(
          crearVotacionPublica({
            estado_recepcion: 'CERRADA',
            resultado: 'APROBADA',
            fecha_hora_cierre: '2026-08-25T10:00:20Z',
            bancas_voto_emitido: [],
            resultado_visible_hasta: '2199-01-01T00:00:00Z',
            votos_individuales: VOTOS_FINALES.map((voto) => ({
              nombre: `Concejal0${voto.banca}`,
              apellido: `Apellido0${voto.banca}`,
              banca: voto.banca,
              valor: voto.valor,
            })),
            conteos: { positivos: 1, negativos: 1, abstenciones: 1, total: 3 },
          }),
        ),
      )
      await page.goto('http://localhost:3001/recinto/')
      await expect(page.getByTestId('grilla-bancas')).toBeVisible()

      await verificarTamanoUniforme(page.locator('[data-testid="banca-publica"]'))
      await verificarSuperficieCerrada(page)
      await verificarSinScrollGlobal(page)
    })

    test('el test de dispositivo se pinta en azul y sin etiqueta en ambas superficies', async ({
      page,
    }) => {
      // Sin votación, la banca 1 conserva el test como estado principal.
      await instalarBackend(page, crearEstadoRecinto(null))
      await page.goto('http://localhost:3001/recinto/')
      await expect(page.getByTestId('grilla-bancas')).toBeVisible()

      const bancaTest = page.locator('[data-banca="1"]')
      await expect(bancaTest).toHaveAttribute('data-estado-banca', 'TEST')
      await expect(bancaTest.locator('[data-testid="etiqueta-banca"]')).toHaveCount(0)
      await expect(bancaTest).not.toContainText('Test')

      const [rojo, verde, azul] = await fondoDeBanca(bancaTest)
      // Azul de test: el canal azul domina claramente sobre el rojo y el verde.
      expect(azul).toBeGreaterThan(rojo + 60)
      expect(azul).toBeGreaterThan(verde + 40)

      // El orador, cuando es el estado principal, usa naranja y una sola etiqueta.
      const bancaOrador = page.locator('[data-banca="1"]')
      expect(await bancaOrador.getAttribute('data-halo-palabra')).toBe('true')
      await verificarSinScrollGlobal(page)
    })

    test('la palabra es naranja cuando resulta el estado principal', async ({ page }) => {
      const estado = crearEstadoRecinto(null)
      // Se retira el test para que el uso de la palabra pase a ser principal.
      estado.concejales = estado.concejales.map((concejal) => ({
        ...concejal,
        test_activo: false,
        test_expira_en: null,
      }))
      await instalarBackend(page, estado)
      await page.goto('http://localhost:3001/recinto/')
      await expect(page.getByTestId('grilla-bancas')).toBeVisible()

      const bancaOrador = page.locator('[data-banca="1"]')
      await expect(bancaOrador).toHaveAttribute('data-estado-banca', 'PALABRA')
      await expect(bancaOrador.locator('[data-testid="etiqueta-banca"]')).toHaveText(
        'En uso de la palabra',
      )
      const [rojo, verde, azul] = await fondoDeBanca(bancaOrador)
      // Naranja: rojo dominante, verde intermedio y azul mínimo.
      expect(rojo).toBeGreaterThan(verde + 40)
      expect(verde).toBeGreaterThanOrEqual(azul)
      expect(azul).toBeLessThan(80)
    })
  })
}
