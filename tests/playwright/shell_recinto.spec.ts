/** Recorrido público determinista de WP-026 en Full HD y 1366×768. */

import { expect, test, type Page } from '@playwright/test'

const HORA_RELOJ_E2E = new Date('2026-08-28T10:00:00Z')

// La zona del navegador difiere deliberadamente de la escala sin offset del
// backend. Así, la prueba falla si alguien vuelve a interpretar esas marcas
// como hora local del navegador en lugar de comparar el reloj institucional.
test.use({ timezoneId: 'America/Los_Angeles' })

function crearConcejales(cantidad: number) {
  return Array.from({ length: cantidad }, (_, indice) => {
    const banca = indice + 1
    return {
      nombre: `Nombre${banca}`,
      apellido: `Apellido${banca}`,
      bloque: banca % 2 === 0 ? 'Bloque Azul' : 'Bloque Verde',
      banca,
      ruta_imagen: `assets/bancas/banca-${String(banca).padStart(2, '0')}.png`,
      presente: banca !== 2,
      test_activo: banca === 3,
      test_expira_en: banca === 3 ? '2026-08-27T10:00:05Z' : null,
    }
  })
}

function crearEstado(parcial: Record<string, unknown> = {}) {
  return {
    revision: 0,
    generado_en: '2026-08-27T10:00:00Z',
    estado_global: 'SIN_PREPARAR',
    preparacion: null,
    sesion: null,
    filas_bancas: null,
    concejales: [],
    quorum: null,
    votacion: null,
    palabra: null,
    eventos_publicos: [],
    // Porción técnica en su estado inicial (WP-056): sin transmisión ni aviso, que es
    // exactamente lo que publica el backend antes de que Apoyo Técnico intervenga.
    tecnico: {
      transmision: {
        estado: 'APAGADO',
        iniciada_en: null,
        en_vivo_desde: null,
        cuenta_regresiva_segundos: null,
        segundos_restantes: null,
      },
      aviso: null,
    },
    ...parcial,
  }
}

function crearVotacion(parcial: Record<string, unknown> = {}) {
  return {
    id: 'votacion-e2e',
    numero_votacion: 2,
    tipo: 'Despacho',
    tema: 'Coexistencia palabra-votación',
    tipo_mayoria: 'SIMPLE',
    factor: 0,
    base: 'VOTOS_COMPUTABLES',
    estado_recepcion: 'EN_CURSO',
    resultado: null,
    fecha_hora_apertura: HORA_RELOJ_E2E.toISOString(),
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

function crearEventosPublicos() {
  // Códigos, categorías y textos copiados literalmente de la allowlist del
  // backend: si alguien cambia el mapeo público, esta prueba deja de reflejar
  // el contrato real y el desvío se vuelve visible.
  const codigos = [
    ['SESION_ABIERTA', 'SESION', 'Sesión abierta'],
    ['CONCEJAL_PRESENTE', 'PRESENCIA', 'Concejal presente'],
    ['PEDIDO_PALABRA_REGISTRADO', 'PALABRA', 'Pedido de palabra registrado'],
    ['USO_PALABRA_OTORGADO', 'PALABRA', 'Uso de palabra otorgado'],
    ['VOTACION_ABIERTA', 'VOTACION', 'Votación abierta'],
  ] as const
  return Array.from({ length: 20 }, (_, indice) => {
    const [codigo_evento, categoria, texto] = codigos[indice % codigos.length]!
    return {
      seq: indice + 1,
      timestamp: `2026-08-28 09:59:${String(indice).padStart(2, '0')}`,
      categoria,
      codigo_evento,
      texto,
      // La vista no debe recorrer ni renderizar campos ajenos al DTO público.
      mensaje: 'DNI 99999999 dispositivo USB tecla 1 sentido POSITIVO',
      nivel: 'L3',
    }
  })
}

/**
 * Instala un backend público controlado. Las únicas operaciones visibles para
 * la aplicación siguen siendo GET snapshot y EventSource de EstadoRecinto.
 */
async function instalarBackendPublico(page: Page, estadoInicial: Record<string, unknown>) {
  await page.addInitScript((inicial) => {
    type EstadoPrueba = Record<string, unknown> & { revision: number }
    type EventoPrueba = { type: string; data?: string }
    type ControlRecinto = {
      publicar: (estado: EstadoPrueba) => void
      cortarYRecuperar: (estado: EstadoPrueba) => void
    }

    let estadoActual = inicial as EstadoPrueba
    const fuentes: FuentePublicaPrueba[] = []

    function publicar(estado: EstadoPrueba): void {
      estadoActual = estado
      const data = JSON.stringify(estadoActual)
      for (const fuente of fuentes) {
        if (fuente.cerrada) continue
        for (const escuchar of fuente.escuchas.estado ?? []) {
          escuchar({ type: 'estado', data })
        }
      }
    }

    class FuentePublicaPrueba {
      cerrada = false
      onopen: ((evento: EventoPrueba) => void) | null = null
      onerror: ((evento: EventoPrueba) => void) | null = null
      onmessage: ((evento: EventoPrueba) => void) | null = null
      escuchas: Record<string, ((evento: EventoPrueba) => void)[]> = {}

      constructor(readonly url: string) {
        fuentes.push(this)
        setTimeout(() => {
          if (this.cerrada) return
          this.onopen?.({ type: 'open' })
          const data = JSON.stringify(estadoActual)
          for (const escuchar of this.escuchas.estado ?? []) {
            escuchar({ type: 'estado', data })
          }
        }, 10)
      }

      addEventListener(tipo: string, escuchar: (evento: EventoPrueba) => void): void {
        this.escuchas[tipo] = this.escuchas[tipo] ?? []
        this.escuchas[tipo]?.push(escuchar)
      }

      removeEventListener(tipo: string, escuchar: (evento: EventoPrueba) => void): void {
        this.escuchas[tipo] = (this.escuchas[tipo] ?? []).filter(
          (registrado) => registrado !== escuchar,
        )
      }

      close(): void {
        this.cerrada = true
      }
    }

    // @ts-expect-error Sustitución determinista de EventSource para el E2E.
    window.EventSource = FuentePublicaPrueba

    const ventana = window as Window & { __controlRecinto?: ControlRecinto }
    ventana.__controlRecinto = {
      publicar,
      cortarYRecuperar: (estado) => {
        estadoActual = estado
        const fuenteActiva = [...fuentes].reverse().find((fuente) => !fuente.cerrada)
        fuenteActiva?.onerror?.({ type: 'error' })
      },
    }

    const fetchOriginal = window.fetch.bind(window)
    window.fetch = async (entrada: RequestInfo | URL, opciones?: RequestInit) => {
      const url =
        typeof entrada === 'string' ? entrada : entrada instanceof URL ? entrada.href : entrada.url
      if (url.includes('/api/v1/estado/recinto')) {
        return new Response(JSON.stringify(estadoActual), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      return fetchOriginal(entrada, opciones)
    }
  }, estadoInicial)
}

async function publicar(page: Page, estado: Record<string, unknown>) {
  await page.evaluate((nuevoEstado) => {
    const ventana = window as Window & {
      __controlRecinto?: { publicar: (valor: Record<string, unknown>) => void }
    }
    ventana.__controlRecinto?.publicar(nuevoEstado)
  }, estado)
}

async function cortarYRecuperar(page: Page, estado: Record<string, unknown>) {
  await page.evaluate((nuevoEstado) => {
    const ventana = window as Window & {
      __controlRecinto?: { cortarYRecuperar: (valor: Record<string, unknown>) => void }
    }
    ventana.__controlRecinto?.cortarYRecuperar(nuevoEstado)
  }, estado)
}

for (const viewport of [
  { width: 1920, height: 1080 },
  { width: 1366, height: 768 },
]) {
  test(`recorre estado, bancas, palabra y reconexión en ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport)
    // Playwright reemplaza Date y los timers del navegador. Así se recorren
    // los deadlines del contrato sin esperas reales ni carreras de CI.
    await page.clock.install({ time: new Date('2026-08-28T09:59:00Z') })
    await instalarBackendPublico(page, crearEstado())
    await page.goto('http://localhost:3001/recinto/')
    // El EventSource de prueba abre con un setTimeout(10). También se lo hace
    // avanzar de forma controlada, una vez montado el shell que lo construye,
    // antes de fijar el instante institucional.
    await page.getByTestId('estado-conexion').waitFor()
    await page.clock.runFor(20)
    await page.clock.pauseAt(HORA_RELOJ_E2E)

    await expect(page.getByTestId('estado-sin-preparar')).toContainText('Recinto sin preparar')
    await expect(page.getByTestId('estado-conexion')).toContainText('En línea')

    const preparando = crearEstado({
      revision: 1,
      estado_global: 'PREPARANDO',
      preparacion: {
        fecha_hora_inicio: '2026-08-27T10:00:00Z',
        numero_sesion: 59,
        presidencia: 'Ana Presidencia',
        secretaria_legislativa: 'Luis Secretaría',
      },
      filas_bancas: [5, 7],
      concejales: crearConcejales(12)
        .filter((concejal) => concejal.banca !== 4)
        .reverse(),
      quorum: { cantidad_presentes: 6, requerido: 7, alcanzado: false },
    })
    await publicar(page, preparando)

    await expect(page.getByTestId('cabecera-sesion')).toContainText('Preparando')
    await expect(page.getByTestId('cabecera-fecha-hora')).toBeVisible()
    await expect(page.getByTestId('cabecera-sesion')).toContainText('Preparando')
    await expect(page.getByTestId('cabecera-tiempo-sesion')).toHaveCount(0)
    await expect(page.getByTestId('estado-quorum')).toHaveText('Sin quórum')
    // WP-045: una sola etiqueta por banca; el test se pinta sin texto.
    await expect(page.locator('[data-banca="2"]')).toHaveAttribute('data-estado-banca', 'AUSENTE')
    await expect(page.locator('[data-banca="2"] [data-testid="etiqueta-banca"]')).toHaveText(
      'Ausente',
    )
    await expect(page.locator('[data-banca="3"]')).toHaveAttribute('data-estado-banca', 'TEST')
    await expect(page.locator('[data-banca="3"] [data-testid="etiqueta-banca"]')).toHaveCount(0)
    await expect(
      page.getByTestId('fila-fisica-1').getByTestId('banca-publica').first(),
    ).toHaveAttribute('data-banca', '1')

    const filaInferior = page.getByTestId('fila-fisica-1')
    const filaSuperior = page.getByTestId('fila-fisica-2')
    const cajaBancaUno = await filaInferior.locator('[data-banca="1"]').boundingBox()
    const cajaBancaSeis = await filaSuperior.locator('[data-banca="6"]').boundingBox()
    expect(cajaBancaUno).not.toBeNull()
    expect(cajaBancaSeis).not.toBeNull()
    expect(cajaBancaUno!.y).toBeGreaterThan(cajaBancaSeis!.y)

    for (const [fila, numeros] of [
      [filaInferior, [1, 2, 3, 4, 5]],
      [filaSuperior, [6, 7, 8, 9, 10, 11, 12]],
    ] as const) {
      const cajas = await Promise.all(
        numeros.map((numero) => fila.locator(`[data-banca="${numero}"]`).boundingBox()),
      )
      expect(cajas.every((caja) => caja !== null)).toBe(true)
      for (let indice = 1; indice < cajas.length; indice += 1) {
        expect(cajas[indice - 1]!.x + cajas[indice - 1]!.width).toBeLessThanOrEqual(
          cajas[indice]!.x + 1,
        )
      }
    }

    await expect(filaInferior.locator('[data-banca="4"]')).toContainText('sin datos públicos')
    // La identidad ya no se repite como texto: vive en el bitmap y en aria-label.
    await expect(filaInferior.locator('[data-banca="5"]')).toHaveAttribute('aria-label', /Nombre5/)
    const bancaUnoPublica = filaInferior.locator('[data-banca="1"]')
    await expect(bancaUnoPublica).toHaveAttribute('data-estado-banca', 'NORMAL')
    await expect(bancaUnoPublica.locator('[data-testid="etiqueta-banca"]')).toHaveCount(0)
    await expect(bancaUnoPublica).not.toContainText('Nombre1')
    await expect(bancaUnoPublica).not.toContainText('Banca 1')
    const ausencia = await page.locator('[data-banca="2"]').evaluate((banca) => ({
      filtroFoto: getComputedStyle(
        banca.querySelector('[data-testid="imagen-concejal"]') as HTMLElement,
      ).filter,
    }))
    expect(ausencia.filtroFoto).not.toBe('none')
    expect(
      await page.evaluate(() => document.documentElement.scrollHeight <= window.innerHeight + 1),
    ).toBe(true)

    const sesion = crearEstado({
      revision: 2,
      generado_en: '2026-08-28T10:00:00',
      estado_global: 'SESION_ABIERTA',
      sesion: {
        fecha_hora_inicio_preparacion: '2026-08-27T10:00:00',
        fecha_hora_apertura: '2026-08-28T09:45:00',
        numero_sesion: 59,
        presidencia: 'Ana Presidencia',
        secretaria_legislativa: 'Luis Secretaría',
      },
      filas_bancas: [3, 4, 5],
      concejales: crearConcejales(12),
      quorum: { cantidad_presentes: 8, requerido: 7, alcanzado: true },
      palabra: {
        orador: { nombre: 'Nombre4', apellido: 'Apellido4', banca: 4 },
        cola: [
          { nombre: 'Nombre7', apellido: 'Apellido7', banca: 7 },
          { nombre: 'Nombre1', apellido: 'Apellido1', banca: 1 },
          ...Array.from({ length: 30 }, (_, indice) => ({
            nombre: `Pedido${indice + 3}`,
            apellido: 'En espera',
            banca: (indice % 12) + 1,
          })),
        ],
      },
      votacion: null,
      eventos_publicos: crearEventosPublicos(),
    })
    await publicar(page, sesion)

    await expect(page.getByTestId('cabecera-sesion')).toContainText('59')
    await expect(page.getByTestId('cabecera-tiempo-sesion')).toContainText('00:15:00')
    await expect(page.getByTestId('cabecera-autoridades')).toContainText('Ana Presidencia')
    await expect(page.getByTestId('cabecera-autoridades')).toContainText('Luis Secretaría')
    await expect(page.getByTestId('estado-quorum')).toHaveText('Quórum alcanzado')
    await expect(page.locator('[data-banca="4"]')).toHaveAttribute('data-estado-banca', 'PALABRA')
    await expect(page.getByTestId('panel-palabra')).not.toContainText('Nombre4 Apellido4')
    await expect(page.getByTestId('cola-palabra').locator('li')).toHaveCount(32)
    await expect(page.getByTestId('cola-palabra').locator('li').nth(0)).toContainText(
      'Nombre7 Apellido7',
    )
    await expect(page.getByTestId('cola-palabra').locator('li').nth(1)).toContainText(
      'Nombre1 Apellido1',
    )
    const scrollCola = await page.getByTestId('cola-palabra').evaluate((cola) => ({
      altoVisible: cola.clientHeight,
      altoContenido: cola.scrollHeight,
    }))
    expect(scrollCola.altoContenido).toBeGreaterThan(scrollCola.altoVisible)

    const horaAntes = await page.getByTestId('cabecera-fecha-hora').textContent()
    await page.clock.runFor(1000)
    await expect(page.getByTestId('cabecera-tiempo-sesion')).toContainText('00:15:01')
    expect(await page.getByTestId('cabecera-fecha-hora').textContent()).not.toBe(horaAntes)

    const cajaCabecera = await page.getByTestId('cabecera-recinto').boundingBox()
    const cajaFranja = await page.getByTestId('franja-votacion-quorum').boundingBox()
    const cajaQuorum = await page.getByTestId('panel-quorum').boundingBox()
    expect(cajaCabecera).not.toBeNull()
    expect(cajaFranja).not.toBeNull()
    expect(cajaQuorum).not.toBeNull()
    // WP-050 bajó la cabecera de tres renglones a uno: 76 px era la baseline.
    expect(cajaCabecera!.height).toBeLessThanOrEqual(60)
    expect(cajaFranja!.height).toBeGreaterThan(110)
    expect(cajaQuorum!.height).toBeGreaterThan(110)

    const cajaBancasSesion = await page.getByTestId('area-bancas-publica').boundingBox()
    const cajaPalabraSesion = await page.getByTestId('columna-palabra-publica').boundingBox()
    const cajaVotacionSesion = await page.getByTestId('votacion-publica').boundingBox()
    expect(cajaBancasSesion).not.toBeNull()
    expect(cajaPalabraSesion).not.toBeNull()
    expect(cajaVotacionSesion).not.toBeNull()
    expect(cajaVotacionSesion!.x + cajaVotacionSesion!.width).toBeLessThanOrEqual(cajaQuorum!.x)
    expect(cajaFranja!.y + cajaFranja!.height).toBeLessThanOrEqual(cajaBancasSesion!.y)
    expect(cajaBancasSesion!.x + cajaBancasSesion!.width).toBeLessThanOrEqual(cajaPalabraSesion!.x)
    expect(cajaBancasSesion!.width).toBeGreaterThan(cajaPalabraSesion!.width * 2)

    // WP-050: el snapshot sigue trayendo `eventos_publicos` —el contrato no
    // cambió— pero la pantalla ya no los dibuja ni les reserva una franja.
    expect(crearEventosPublicos().length).toBeGreaterThan(0)
    await expect(page.getByTestId('panel-eventos-publicos')).toHaveCount(0)
    await expect(page.getByTestId('franja-eventos-publicos')).toHaveCount(0)
    await expect(page.getByTestId('lista-eventos-publicos')).toHaveCount(0)

    // La votación nueva reemplaza la sesión sin votación. Aun si el mock
    // incluyera datos prohibidos, EN_CURSO no revela voto ni conteos en DOM.
    const ahoraCountdown = await page.evaluate(() => Date.now())
    const enCurso = {
      ...sesion,
      revision: 3,
      generado_en: new Date(ahoraCountdown).toISOString(),
      votacion: crearVotacion({
        tema: 'Expediente público con countdown',
        fecha_hora_apertura: new Date(ahoraCountdown).toISOString(),
        cuenta_regresiva_hasta: new Date(ahoraCountdown + 1200).toISOString(),
        votos_individuales: [
          { nombre: 'Nombre1', apellido: 'Apellido1', banca: 1, valor: 'POSITIVO' },
        ],
        conteos: { positivos: 99, negativos: 0, abstenciones: 0, total: 99 },
      }),
    }
    await publicar(page, enCurso)

    await expect(page.getByTestId('estado-votacion')).toHaveText('En curso')
    await expect(page.getByTestId('tema-votacion')).toContainText('Expediente público')
    await expect(page.getByTestId('countdown-votacion')).toBeVisible()
    await expect(page.getByTestId('panel-quorum')).toBeVisible()
    await expect(page.getByTestId('panel-palabra')).not.toContainText('Nombre4 Apellido4')
    await expect(page.locator('[data-estado-banca^="RESULTADO_"]')).toHaveCount(0)
    await expect(page.getByTestId('conteos-votacion')).toHaveCount(0)
    await expect(page.getByText('Positivo', { exact: true })).toHaveCount(0)

    const cajaCountdown = await page.getByTestId('countdown-votacion').boundingBox()
    const cajaPalabraCountdown = await page.getByTestId('columna-palabra-publica').boundingBox()
    expect(cajaCountdown).not.toBeNull()
    expect(cajaPalabraCountdown).not.toBeNull()
    expect(cajaCountdown!.x + cajaCountdown!.width).toBeLessThanOrEqual(cajaPalabraCountdown!.x)

    await page.clock.runFor(1500)
    await expect(page.getByTestId('countdown-votacion')).toHaveCount(0)
    await expect(page.getByTestId('estado-votacion')).toHaveText('En curso')
    await expect(page.locator('[data-estado-banca^="RESULTADO_"]')).toHaveCount(0)

    // Antes se auditaba el HTML de la franja de eventos. Retirada esa franja, la
    // comprobación se amplía a TODA la aplicación: si algún dato reservado del
    // mock volviera a dibujarse en cualquier región, la prueba falla.
    //
    // Se descartan los nodos comentario porque en modo desarrollo Vue conserva
    // los comentarios pedagógicos del código fuente, que hablan de "sentido" o
    // "dispositivo" sin ser datos de la sesión.
    const marcasEnCurso = await page.evaluate(() => {
      const raiz = document.querySelector('.aplicacion-recinto') as HTMLElement
      const copia = raiz.cloneNode(true) as HTMLElement
      const recorrido = document.createTreeWalker(copia, NodeFilter.SHOW_COMMENT)
      const comentarios: Comment[] = []
      while (recorrido.nextNode()) comentarios.push(recorrido.currentNode as Comment)
      for (const comentario of comentarios) comentario.remove()
      return { html: copia.outerHTML.toLowerCase(), texto: raiz.innerText.toLowerCase() }
    })
    // El `mensaje` crudo de auditoría que trae el mock no puede aparecer en
    // ningún atributo, clase ni texto de la aplicación.
    for (const datoProhibido of ['99999999', 'usb', 'tecla', 'dni ']) {
      expect(marcasEnCurso.html).not.toContain(datoProhibido)
    }
    // Y ningún sentido de voto puede leerse mientras la recepción sigue abierta.
    for (const sentido of ['positivo', 'negativo', 'abstenci']) {
      expect(marcasEnCurso.texto).not.toContain(sentido)
    }

    const selectoresGeometria = [
      'cabecera-recinto',
      'votacion-publica',
      'panel-quorum',
      'area-bancas-publica',
      'columna-palabra-publica',
    ] as const
    const geometriaTemaCorto = await Promise.all(
      selectoresGeometria.map((selector) => page.getByTestId(selector).boundingBox()),
    )

    const temaLargo =
      'Tratamiento extenso del expediente institucional con una descripción deliberadamente larga para validar la degradación controlada del texto público'
    await publicar(page, {
      ...enCurso,
      revision: 4,
      votacion: crearVotacion({
        tema: temaLargo,
        fecha_hora_apertura: new Date(ahoraCountdown).toISOString(),
      }),
    })
    await expect(page.getByTestId('tema-votacion')).toHaveAttribute('title', temaLargo)
    const estiloTema = await page.getByTestId('tema-votacion').evaluate((tema) => {
      const estilo = getComputedStyle(tema)
      return {
        whiteSpace: estilo.whiteSpace,
        overflow: estilo.overflow,
        textOverflow: estilo.textOverflow,
      }
    })
    expect(estiloTema).toEqual({
      whiteSpace: 'nowrap',
      overflow: 'hidden',
      textOverflow: 'ellipsis',
    })
    const geometriaTemaLargo = await Promise.all(
      selectoresGeometria.map((selector) => page.getByTestId(selector).boundingBox()),
    )
    for (let indice = 0; indice < geometriaTemaCorto.length; indice += 1) {
      const corta = geometriaTemaCorto[indice]
      const larga = geometriaTemaLargo[indice]
      expect(corta).not.toBeNull()
      expect(larga).not.toBeNull()
      for (const dimension of ['x', 'y', 'width', 'height'] as const) {
        expect(Math.abs(corta![dimension] - larga![dimension])).toBeLessThanOrEqual(1)
      }
    }

    const ahoraAprobada = await page.evaluate(() => Date.now())
    const aprobada = {
      ...sesion,
      revision: 5,
      generado_en: new Date(ahoraAprobada).toISOString(),
      votacion: crearVotacion({
        tema: temaLargo,
        estado_recepcion: 'CERRADA',
        resultado: 'APROBADA',
        fecha_hora_cierre: new Date(ahoraAprobada).toISOString(),
        cuenta_regresiva_hasta: null,
        resultado_visible_hasta: new Date(ahoraAprobada + 1400).toISOString(),
        votos_individuales: [
          { nombre: 'Nombre3', apellido: 'Apellido3', banca: 3, valor: 'ABSTENCION' },
          { nombre: 'Nombre1', apellido: 'Apellido1', banca: 1, valor: 'POSITIVO' },
          { nombre: 'Nombre2', apellido: 'Apellido2', banca: 2, valor: 'NEGATIVO' },
        ],
        conteos: { positivos: 8, negativos: 2, abstenciones: 1, total: 11 },
      }),
    }
    await publicar(page, aprobada)

    await expect(page.getByTestId('estado-votacion')).toHaveText('Aprobada')
    await expect(page.getByTestId('tema-votacion')).toHaveAttribute('title', temaLargo)
    await expect(page.locator('[data-banca="1"] [data-testid="etiqueta-banca"]')).toHaveText(
      'Positivo',
    )
    await expect(page.locator('[data-banca="2"] [data-testid="etiqueta-banca"]')).toHaveText(
      'Negativo',
    )
    await expect(page.locator('[data-banca="3"] [data-testid="etiqueta-banca"]')).toHaveText(
      'Abstención',
    )
    await expect(page.locator('[data-banca="4"]')).not.toHaveAttribute(
      'data-estado-banca',
      /RESULTADO_/,
    )
    await expect(page.getByTestId('conteos-votacion')).toContainText('Positivos 8')
    await expect(page.getByTestId('conteos-votacion')).toContainText('Total 11')
    await page.clock.runFor(1750)
    await expect(page.getByTestId('estado-votacion')).toHaveText('Sin votación')
    await expect(page.locator('[data-estado-banca^="RESULTADO_"]')).toHaveCount(0)

    const empatada = {
      ...sesion,
      revision: 6,
      generado_en: new Date(await page.evaluate(() => Date.now())).toISOString(),
      votacion: crearVotacion({
        id: 'votacion-empate',
        numero_votacion: 3,
        tema: 'Votación simple empatada',
        estado_recepcion: 'CERRADA',
        resultado: 'EMPATADA',
        resultado_visible_hasta: null,
        votos_individuales: [
          { nombre: 'Nombre1', apellido: 'Apellido1', banca: 1, valor: 'POSITIVO' },
          { nombre: 'Nombre2', apellido: 'Apellido2', banca: 2, valor: 'NEGATIVO' },
        ],
        conteos: { positivos: 1, negativos: 1, abstenciones: 0, total: 2 },
      }),
    }
    await publicar(page, empatada)
    await expect(page.getByTestId('estado-votacion')).toHaveText('Empatada')
    await expect(page.getByTestId('espera-desempate')).toContainText('Presidencia')
    await page.clock.runFor(1500)
    await expect(page.getByTestId('estado-votacion')).toHaveText('Empatada')
    await expect(page.locator('[data-estado-banca^="RESULTADO_"]')).toHaveCount(2)

    const ahoraDesempate = await page.evaluate(() => Date.now())
    await publicar(page, {
      ...empatada,
      revision: 7,
      generado_en: new Date(ahoraDesempate).toISOString(),
      votacion: crearVotacion({
        id: 'votacion-empate',
        numero_votacion: 3,
        tema: 'Votación simple desempatada',
        estado_recepcion: 'CERRADA',
        resultado: 'RECHAZADA',
        resultado_visible_hasta: new Date(ahoraDesempate + 1800).toISOString(),
        votos_individuales: [
          { nombre: 'Nombre1', apellido: 'Apellido1', banca: 1, valor: 'POSITIVO' },
          { nombre: 'Nombre2', apellido: 'Apellido2', banca: 2, valor: 'NEGATIVO' },
        ],
        conteos: { positivos: 1, negativos: 1, abstenciones: 0, total: 2 },
        voto_presidencial: { presidencia: 'Ana Presidencia', sentido: 'NEGATIVO' },
      }),
    })
    await expect(page.getByTestId('estado-votacion')).toHaveText('Rechazada')
    await expect(page.getByTestId('voto-presidencial')).toContainText('Ana Presidencia')
    await expect(page.getByTestId('voto-presidencial')).toContainText('Negativo')
    await expect(page.locator('[data-estado-banca^="RESULTADO_"]')).toHaveCount(2)
    await expect(page.getByTestId('conteos-votacion')).toContainText('Total 2')

    const ahoraInconclusa = await page.evaluate(() => Date.now())
    const inconclusa = {
      ...sesion,
      revision: 8,
      generado_en: new Date(ahoraInconclusa).toISOString(),
      votacion: crearVotacion({
        id: 'votacion-inconclusa',
        numero_votacion: 4,
        tema: 'Votación inconclusa con recepción parcial',
        estado_recepcion: 'CERRADA',
        resultado: 'INCONCLUSA',
        resultado_visible_hasta: new Date(ahoraInconclusa + 1800).toISOString(),
        votos_individuales: [
          { nombre: 'Nombre1', apellido: 'Apellido1', banca: 1, valor: 'POSITIVO' },
        ],
        conteos: { positivos: 1, negativos: 0, abstenciones: 0, total: 1 },
      }),
    }
    await publicar(page, inconclusa)
    await expect(page.getByTestId('estado-votacion')).toHaveText('Inconclusa')
    await expect(page.locator('[data-estado-banca^="RESULTADO_"]')).toHaveCount(1)
    // La banca 4 no votó, así que su estado principal sigue siendo el uso de la palabra.
    await expect(page.locator('[data-banca="4"]')).toHaveAttribute('data-estado-banca', 'PALABRA')
    await expect(page.getByTestId('panel-palabra')).not.toContainText('Nombre4 Apellido4')

    const cajas = await Promise.all([
      page.getByTestId('area-bancas-publica').boundingBox(),
      page.getByTestId('columna-palabra-publica').boundingBox(),
    ])
    expect(cajas[0]).not.toBeNull()
    expect(cajas[1]).not.toBeNull()
    expect(cajas[0]!.x + cajas[0]!.width).toBeLessThanOrEqual(cajas[1]!.x)
    expect(
      await page.evaluate(() => document.documentElement.scrollHeight <= window.innerHeight + 1),
    ).toBe(true)

    const reinicio = crearEstado({ revision: 0, estado_global: 'SIN_PREPARAR' })
    // La reconexión pertenece a WP-025 y sí necesita que el backoff vuelva a
    // avanzar naturalmente después de completar las fronteras de WP-026.
    await page.clock.resume()
    await cortarYRecuperar(page, reinicio)
    // WP-070 acortó este aviso: la vista atrasada se señala como «(Sin conexion)».
    await expect(page.getByTestId('estado-conexion')).toContainText('(Sin conexion)')
    await expect(page.locator('[data-banca="4"]')).toHaveAttribute('data-estado-banca', 'PALABRA')
    await expect(page.getByTestId('estado-sin-preparar')).toBeVisible({ timeout: 5000 })
    await expect(page.getByTestId('estado-conexion')).toContainText('En línea')
    await expect(page.getByTestId('grilla-bancas')).toHaveCount(0)
  })
  /**
   * WP-050 — proporciones finales de la Pantalla del Recinto.
   *
   * Esta prueba mide geometría real del DOM (bounding boxes), no clases CSS.
   * Los umbrales salen de contrastar la composición con el sistema histórico en
   * producción (`martinebene/Botonera@main`, `app/web/static/pantalla/`), medido
   * en Chromium a las mismas dos resoluciones:
   *
   * | región                | producción 1920×1080 | producción 1366×768 |
   * |-----------------------|----------------------|---------------------|
   * | cabecera              | 59 px (5,5 %)        | 47 px (6,1 %)       |
   * | votación + quórum     | 216 px (20,0 %)      | 174 px (22,7 %)     |
   * | ancho de quórum       | 220 px (11,5 %)      | 164 px (12,0 %)     |
   * | bancas + palabra      | 637 px (59,0 %)      | 422 px (55,0 %)     |
   * | ancho de palabra      | 384 px (20 vw)       | 273 px (20 vw)      |
   * | eventos               | 127 px (11,8 %)      | 84 px (11,0 %)      |
   *
   * SIS-Leg retira la franja de eventos por decisión humana, así que su
   * altura debe aparecer en la zona principal: acá se exige que bancas+palabra
   * superen la proporción histórica en lugar de igualarla.
   */
  test(`respeta las proporciones WP-050 en ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport)
    await page.clock.install({ time: new Date('2026-08-28T09:59:00Z') })
    await instalarBackendPublico(page, crearEstado())
    await page.goto('http://localhost:3001/recinto/')
    await page.getByTestId('estado-conexion').waitFor()
    await page.clock.runFor(20)
    await page.clock.pauseAt(HORA_RELOJ_E2E)

    const eventosPublicos = crearEventosPublicos()
    const datosSesion = {
      fecha_hora_inicio_preparacion: '2026-08-28T09:30:00',
      fecha_hora_apertura: '2026-08-28T09:45:00',
      numero_sesion: 59,
      presidencia: 'Ana Presidencia',
      secretaria_legislativa: 'Luis Secretaría',
    }
    const sesion = crearEstado({
      revision: 1,
      generado_en: '2026-08-28T10:00:00',
      estado_global: 'SESION_ABIERTA',
      sesion: datosSesion,
      filas_bancas: [3, 4, 5],
      concejales: crearConcejales(12),
      quorum: { cantidad_presentes: 8, requerido: 7, alcanzado: true },
      palabra: {
        orador: { nombre: 'Nombre4', apellido: 'Apellido4', banca: 4 },
        cola: [
          { nombre: 'Nombre7', apellido: 'Apellido7', banca: 7 },
          { nombre: 'Nombre1', apellido: 'Apellido1', banca: 1 },
        ],
      },
      votacion: crearVotacion({ tema: 'Expediente breve', cuenta_regresiva_hasta: null }),
      eventos_publicos: eventosPublicos,
    })
    await publicar(page, sesion)
    await expect(page.getByTestId('cabecera-sesion')).toContainText('59')
    // Las imágenes reales deben estar cargadas antes de medir recortes.
    await expect(page.getByTestId('imagen-concejal').first()).toBeVisible()
    await page.waitForFunction(() =>
      Array.from(document.querySelectorAll('img')).every((imagen) => imagen.complete),
    )

    // ---------------------------------------------------------------------
    // 1 · Eventos retirados de la vista, contrato intacto en el snapshot
    // ---------------------------------------------------------------------
    expect(eventosPublicos).toHaveLength(20)
    await expect(page.getByTestId('panel-eventos-publicos')).toHaveCount(0)
    await expect(page.getByTestId('franja-eventos-publicos')).toHaveCount(0)
    const estadoPublicado = await page.evaluate(async () => {
      const respuesta = await fetch('/api/v1/estado/recinto')
      return (await respuesta.json()) as { eventos_publicos: unknown[] }
    })
    expect(estadoPublicado.eventos_publicos).toHaveLength(20)

    // El contenido principal solo tiene dos regiones: ya no queda una tercera
    // fila reservada (ni vacía) para la franja de eventos.
    const regiones = await page.locator('.contenido-recinto').evaluate((contenido) => ({
      hijos: Array.from(contenido.children).map((hijo) => hijo.getAttribute('data-testid')),
      filas: getComputedStyle(contenido).gridTemplateRows.split(' ').length,
    }))
    expect(regiones.hijos).toEqual(['franja-votacion-quorum', 'zona-principal-recinto'])
    expect(regiones.filas).toBe(2)

    // ---------------------------------------------------------------------
    // 2 · Cabecera de una sola línea y más baja que la baseline previa
    // ---------------------------------------------------------------------
    const cajaCabecera = (await page.getByTestId('cabecera-recinto').boundingBox())!
    const cajaContexto = (await page.getByTestId('cabecera-contexto').boundingBox())!
    const cajaReloj = (await page.getByTestId('cabecera-fecha-hora').boundingBox())!
    const cajaConexion = (await page.getByTestId('estado-conexion').boundingBox())!
    const cajaSesion = (await page.getByTestId('cabecera-sesion').boundingBox())!
    const cajaTiempo = (await page.getByTestId('cabecera-tiempo-sesion').boundingBox())!

    // Baseline previa a WP-050: 76 px en Full HD y 62 px en 1366×768.
    expect(cajaCabecera.height).toBeLessThanOrEqual(60)
    expect(cajaCabecera.height).toBeLessThan(viewport.height === 1080 ? 76 : 62)

    // Una sola línea: el bloque central mide un renglón y sus datos caben
    // enteros dentro de ese renglón. Si alguno pasara a una segunda fila, su
    // caja sobresaldría del contenedor. Desde WP-054 las autoridades ya no
    // viven acá: se miden en su propio bloque.
    //
    // El umbral subió de 26 px a 36 px en WP-058 porque el cuerpo del centro se
    // duplicó por decisión de HUMAN_GATE: el renglón pasó de ~17 px a ~34 px en
    // Full HD y a ~23 px en 1366×768. Lo que se sigue exigiendo es lo mismo de
    // antes —una única línea— y ahora además que ese renglón entre dentro de la
    // altura fija de la cabecera, que no creció.
    expect(cajaContexto.height).toBeLessThanOrEqual(36)
    expect(cajaContexto.y).toBeGreaterThanOrEqual(cajaCabecera.y)
    expect(cajaContexto.y + cajaContexto.height).toBeLessThanOrEqual(
      cajaCabecera.y + cajaCabecera.height,
    )
    for (const caja of [cajaSesion, cajaTiempo]) {
      expect(caja.y).toBeGreaterThanOrEqual(cajaContexto.y - 1)
      expect(caja.y + caja.height).toBeLessThanOrEqual(cajaContexto.y + cajaContexto.height + 1)
    }

    // Reloj a la izquierda, contexto al medio, conexión a la derecha.
    expect(cajaReloj.x + cajaReloj.width).toBeLessThanOrEqual(cajaContexto.x)
    expect(cajaContexto.x + cajaContexto.width).toBeLessThanOrEqual(cajaConexion.x)
    // Fecha/hora, sesión, duración y conexión siguen disponibles.
    await expect(page.getByTestId('cabecera-fecha-hora')).not.toBeEmpty()
    await expect(page.getByTestId('cabecera-tiempo-sesion')).toContainText('00:15:00')
    await expect(page.getByTestId('estado-conexion')).toContainText('En línea')

    // ---------------------------------------------------------------------
    // 3 · Jerarquía de superficies y espacio recuperado
    // ---------------------------------------------------------------------
    const cajaFranja = (await page.getByTestId('franja-votacion-quorum').boundingBox())!
    const cajaZona = (await page.getByTestId('zona-principal-recinto').boundingBox())!
    const cajaVotacion = (await page.getByTestId('votacion-publica').boundingBox())!
    const cajaQuorum = (await page.getByTestId('panel-quorum').boundingBox())!
    const cajaBancas = (await page.getByTestId('area-bancas-publica').boundingBox())!
    const cajaPalabra = (await page.getByTestId('columna-palabra-publica').boundingBox())!

    // Orden espacial: votación/quórum arriba; bancas abajo-izquierda; palabra
    // abajo-derecha. Es la relación histórica que el WP obliga a conservar.
    expect(cajaCabecera.y + cajaCabecera.height).toBeLessThanOrEqual(cajaFranja.y)
    expect(cajaVotacion.x + cajaVotacion.width).toBeLessThanOrEqual(cajaQuorum.x)
    expect(cajaFranja.y + cajaFranja.height).toBeLessThanOrEqual(cajaZona.y)
    expect(cajaBancas.x + cajaBancas.width).toBeLessThanOrEqual(cajaPalabra.x)
    expect(Math.abs(cajaBancas.y - cajaPalabra.y)).toBeLessThanOrEqual(1)

    // La zona principal supera la proporción histórica (59,0 % y 55,0 %)
    // porque absorbió la franja de eventos y la altura sobrante de cabecera.
    const proporcionZona = cajaZona.height / viewport.height
    expect(proporcionZona).toBeGreaterThan(viewport.height === 1080 ? 0.7 : 0.65)

    // Bancas dominantes: más altas que la franja superior y mucho más anchas
    // que la columna de palabra.
    expect(cajaBancas.height).toBeGreaterThan(cajaFranja.height * 3)
    expect(cajaBancas.width).toBeGreaterThan(cajaPalabra.width * 2)
    const superficieBancas = cajaBancas.width * cajaBancas.height
    const superficieResto =
      cajaFranja.width * cajaFranja.height + cajaPalabra.width * cajaPalabra.height
    expect(superficieBancas).toBeGreaterThan(superficieResto)

    // Anchos calibrados contra producción: 20 vw exactos de palabra (igual que
    // `flex: 0 0 20vw`) y ≈12 % de ancho para el quórum (220 px y 164 px allá).
    expect(Math.abs(cajaPalabra.width - viewport.width * 0.2)).toBeLessThanOrEqual(2)
    expect(cajaQuorum.width / viewport.width).toBeGreaterThanOrEqual(0.11)
    expect(cajaQuorum.width / viewport.width).toBeLessThanOrEqual(0.125)

    // ---------------------------------------------------------------------
    // 4 · Sin scroll global y sin imágenes recortadas
    // ---------------------------------------------------------------------
    const desbordes = await page.evaluate(() => ({
      vertical: document.documentElement.scrollHeight - window.innerHeight,
      horizontal: document.documentElement.scrollWidth - window.innerWidth,
    }))
    expect(desbordes.vertical).toBeLessThanOrEqual(1)
    expect(desbordes.horizontal).toBeLessThanOrEqual(1)

    const imagenes = await page.getByTestId('banca-publica').evaluateAll((tarjetas) =>
      tarjetas.map((tarjeta) => {
        const imagen = tarjeta.querySelector('[data-testid="imagen-concejal"]') as HTMLImageElement
        const cajaTarjeta = tarjeta.getBoundingClientRect()
        const cajaImagen = imagen.getBoundingClientRect()
        return {
          ajuste: getComputedStyle(imagen).objectFit,
          cargada: imagen.naturalWidth > 0,
          dentro:
            cajaImagen.left >= cajaTarjeta.left - 1 &&
            cajaImagen.right <= cajaTarjeta.right + 1 &&
            cajaImagen.top >= cajaTarjeta.top - 1 &&
            cajaImagen.bottom <= cajaTarjeta.bottom + 1,
        }
      }),
    )
    expect(imagenes).toHaveLength(12)
    for (const imagen of imagenes) {
      // `contain` es la garantía de que el bitmap institucional entra completo.
      expect(imagen.ajuste).toBe('contain')
      expect(imagen.cargada).toBe(true)
      expect(imagen.dentro).toBe(true)
    }

    // ---------------------------------------------------------------------
    // 5 · Tarjetas uniformes y estables ante texto variable
    // ---------------------------------------------------------------------
    async function medirTarjetas() {
      return page.getByTestId('banca-publica').evaluateAll((tarjetas) =>
        tarjetas.map((tarjeta) => {
          const caja = tarjeta.getBoundingClientRect()
          return { w: Math.round(caja.width), h: Math.round(caja.height) }
        }),
      )
    }
    const tarjetasAntes = await medirTarjetas()
    for (const tarjeta of tarjetasAntes) {
      expect(tarjeta.w).toBe(tarjetasAntes[0]!.w)
      expect(tarjeta.h).toBe(tarjetasAntes[0]!.h)
    }

    const selectoresEstructurales = [
      'cabecera-recinto',
      'franja-votacion-quorum',
      'zona-principal-recinto',
      'votacion-publica',
      'panel-quorum',
      'area-bancas-publica',
      'columna-palabra-publica',
    ] as const
    const geometriaAntes = await Promise.all(
      selectoresEstructurales.map((selector) => page.getByTestId(selector).boundingBox()),
    )

    // Tema y autoridades extremos al mismo tiempo: el peor caso de texto.
    const temaExtenso =
      'Tratamiento del expediente institucional 1234/2026 sobre reordenamiento integral del ' +
      'sistema de transporte urbano de pasajeros con todas sus modificaciones sucesivas'
    await publicar(page, {
      ...sesion,
      revision: 2,
      sesion: {
        ...datosSesion,
        presidencia: 'María de los Ángeles Presidencia Apellido Compuesto Extremadamente Largo',
        secretaria_legislativa: 'Juan Carlos Secretaría Legislativa Apellido Igualmente Extenso',
      },
      votacion: crearVotacion({ tema: temaExtenso, cuenta_regresiva_hasta: null }),
    })
    await expect(page.getByTestId('tema-votacion')).toHaveAttribute('title', temaExtenso)
    await expect(page.getByTestId('cabecera-autoridades')).toContainText('María')

    // El tema se recorta con elipsis en una única línea.
    const estiloTema = await page.getByTestId('tema-votacion').evaluate((elemento) => {
      const computado = getComputedStyle(elemento)
      return {
        overflow: computado.overflow,
        textOverflow: computado.textOverflow,
        recortado: elemento.scrollWidth > elemento.clientWidth,
      }
    })
    expect(estiloTema.overflow).toBe('hidden')
    expect(estiloTema.textOverflow).toBe('ellipsis')
    expect(estiloTema.recortado).toBe(true)

    // Cada autoridad se recorta por separado (WP-054): el bloque derecho apila
    // dos renglones y ninguno puede envolver a una tercera línea.
    const estilosAutoridades = await page
      .locator('[data-testid="cabecera-autoridades"] .renglon-autoridad')
      .evaluateAll((renglones) =>
        renglones.map((renglon) => {
          const computado = getComputedStyle(renglon)
          return {
            whiteSpace: computado.whiteSpace,
            overflow: computado.overflow,
            textOverflow: computado.textOverflow,
            recortado: renglon.scrollWidth > renglon.clientWidth,
          }
        }),
      )
    expect(estilosAutoridades).toHaveLength(2)
    for (const estilo of estilosAutoridades) {
      expect(estilo.whiteSpace).toBe('nowrap')
      expect(estilo.overflow).toBe('hidden')
      expect(estilo.textOverflow).toBe('ellipsis')
      expect(estilo.recortado).toBe(true)
    }
    // `white-space` lo hereda el contenedor de la cabecera; se verifica el
    // resultado observable: una sola línea, sin segunda fila.
    const cajaContextoLargo = (await page.getByTestId('cabecera-contexto').boundingBox())!
    expect(cajaContextoLargo.height).toBeLessThanOrEqual(36)

    const geometriaDespues = await Promise.all(
      selectoresEstructurales.map((selector) => page.getByTestId(selector).boundingBox()),
    )
    for (let indice = 0; indice < geometriaAntes.length; indice += 1) {
      for (const dimension of ['x', 'y', 'width', 'height'] as const) {
        expect(
          Math.abs(geometriaAntes[indice]![dimension] - geometriaDespues[indice]![dimension]),
        ).toBeLessThanOrEqual(1)
      }
    }
    expect(await medirTarjetas()).toEqual(tarjetasAntes)

    const desbordesFinales = await page.evaluate(() => ({
      vertical: document.documentElement.scrollHeight - window.innerHeight,
      horizontal: document.documentElement.scrollWidth - window.innerWidth,
    }))
    expect(desbordesFinales.vertical).toBeLessThanOrEqual(1)
    expect(desbordesFinales.horizontal).toBeLessThanOrEqual(1)

    // ---------------------------------------------------------------------
    // 6 · El reloj de sesión sigue avanzando
    // ---------------------------------------------------------------------
    const relojAntes = await page.getByTestId('cabecera-fecha-hora').textContent()
    await page.clock.runFor(1000)
    await expect(page.getByTestId('cabecera-tiempo-sesion')).toContainText('00:15:01')
    expect(await page.getByTestId('cabecera-fecha-hora').textContent()).not.toBe(relojAntes)
  })
}

/**
 * Evidencia geométrica del refinamiento visual público (WP-054).
 *
 * HUMAN_GATE decidió estos cambios mirando capturas reales del 01/09/2026, así
 * que la comprobación no puede quedarse en clases CSS: cada criterio se mide
 * con bounding boxes y estilos calculados en las dos resoluciones canónicas.
 *
 * Baselines contra las que se compara (medidas sobre el código previo a WP-054):
 *
 * | dato                    | baseline           | exigencia WP-054            |
 * |-------------------------|--------------------|-----------------------------|
 * | nombre en cola          | 0,76 rem = 12,16 px| estrictamente mayor         |
 * | banca en cola           | 0,63 rem = 10,08 px| estrictamente mayor         |
 * | círculo de orden        | 1,6 rem = 25,6 px  | exactamente igual           |
 * | autoridades en cabecera | centro             | sector derecho, dos líneas  |
 */
for (const viewport of [
  { width: 1920, height: 1080 },
  { width: 1366, height: 768 },
]) {
  test(`aplica el refinamiento visual WP-054 en ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    // Baselines tipográficas previas al WP, en píxeles (raíz de 16 px).
    const NOMBRE_BASELINE_PX = 12.16
    const BANCA_BASELINE_PX = 10.08
    const CIRCULO_ORDEN_PX = 25.6

    await page.setViewportSize(viewport)
    await page.clock.install({ time: new Date('2026-08-28T09:59:00Z') })
    await instalarBackendPublico(page, crearEstado())
    await page.goto('http://localhost:3001/recinto/')
    await page.getByTestId('estado-conexion').waitFor()
    await page.clock.runFor(20)
    await page.clock.pauseAt(HORA_RELOJ_E2E)

    const datosSesion = {
      fecha_hora_inicio_preparacion: '2026-08-28T09:30:00',
      fecha_hora_apertura: '2026-08-28T09:45:00',
      numero_sesion: 59,
      presidencia: 'Ana Presidencia',
      secretaria_legislativa: 'Luis Secretaría',
    }
    // Nombres tomados del padrón real: el criterio de aceptación pide que la
    // cola no genere scroll horizontal "con nombres reales".
    const colaReal = [
      { nombre: 'Gastón', apellido: 'Cuis Taccari', banca: 4 },
      { nombre: 'Federico', apellido: 'Garitano', banca: 7 },
      { nombre: 'Lorena', apellido: 'Moreno', banca: 1 },
    ]
    const sesion = crearEstado({
      revision: 1,
      generado_en: '2026-08-28T10:00:00',
      estado_global: 'SESION_ABIERTA',
      sesion: datosSesion,
      filas_bancas: [3, 4, 5],
      concejales: crearConcejales(12),
      quorum: { cantidad_presentes: 8, requerido: 7, alcanzado: true },
      palabra: {
        orador: { nombre: 'Andrea', apellido: 'Rueda', banca: 3 },
        cola: colaReal,
      },
      votacion: crearVotacion({ tema: 'Expediente breve', cuenta_regresiva_hasta: null }),
    })
    await publicar(page, sesion)
    await expect(page.getByTestId('cabecera-sesion')).toContainText('59')

    // -----------------------------------------------------------------------
    // 1 · Cabecera pública: centro real y autoridades a la derecha
    // -----------------------------------------------------------------------
    const cajaCabecera = (await page.getByTestId('cabecera-recinto').boundingBox())!
    const cajaContexto = (await page.getByTestId('cabecera-contexto').boundingBox())!
    const cajaReloj = (await page.getByTestId('cabecera-fecha-hora').boundingBox())!
    const cajaAutoridades = (await page.getByTestId('cabecera-autoridades').boundingBox())!
    const cajaConexion = (await page.getByTestId('estado-conexion').boundingBox())!

    // Centro real: el eje del bloque central coincide con el eje del viewport.
    // La tolerancia de 2 px absorbe el redondeo de subpíxel del navegador.
    const centroContexto = cajaContexto.x + cajaContexto.width / 2
    expect(Math.abs(centroContexto - viewport.width / 2)).toBeLessThanOrEqual(2)

    // Sin invasión: el centro termina antes de que empiece el bloque derecho.
    expect(cajaReloj.x + cajaReloj.width).toBeLessThanOrEqual(cajaContexto.x)
    expect(cajaContexto.x + cajaContexto.width).toBeLessThanOrEqual(cajaAutoridades.x)
    expect(cajaAutoridades.x + cajaAutoridades.width).toBeLessThanOrEqual(cajaConexion.x + 1)

    // Toda la cabecera entra en su altura fija: nada se recorta ni la empuja.
    expect(cajaCabecera.height).toBeLessThanOrEqual(60)
    for (const caja of [cajaContexto, cajaAutoridades, cajaConexion]) {
      expect(caja.y).toBeGreaterThanOrEqual(cajaCabecera.y - 1)
      expect(caja.y + caja.height).toBeLessThanOrEqual(cajaCabecera.y + cajaCabecera.height + 1)
    }

    // El centro sigue midiendo un solo renglón, con el cuerpo ampliado por
    // WP-058 (≈34 px en Full HD y ≈23 px en 1366×768).
    expect(cajaContexto.height).toBeLessThanOrEqual(36)

    // Jerarquía uniforme: institución, sesión y duración comparten tamaño.
    const tamanosCentro = await page
      .locator('[data-testid="cabecera-contexto"] > *')
      .evaluateAll((nodos) => nodos.map((nodo) => getComputedStyle(nodo).fontSize))
    expect(tamanosCentro).toHaveLength(3)
    expect(new Set(tamanosCentro).size).toBe(1)

    // Autoridades en dos renglones apilados, no en una línea con separadores.
    const cajasAutoridades = await page
      .locator('[data-testid="cabecera-autoridades"] .renglon-autoridad')
      .evaluateAll((renglones) =>
        renglones.map((renglon) => {
          const caja = renglon.getBoundingClientRect()
          return { y: caja.y, alto: caja.height, texto: renglon.textContent?.trim() ?? '' }
        }),
      )
    expect(cajasAutoridades).toHaveLength(2)
    expect(cajasAutoridades[0]!.texto).toContain('Presidencia')
    expect(cajasAutoridades[1]!.texto).toContain('Secretaría')
    // El segundo renglón arranca por debajo del primero: están apilados.
    expect(cajasAutoridades[1]!.y).toBeGreaterThanOrEqual(
      cajasAutoridades[0]!.y + cajasAutoridades[0]!.alto - 1,
    )

    // -----------------------------------------------------------------------
    // 2 · Cola de palabra: más grande, mismo círculo, sin scroll horizontal
    // -----------------------------------------------------------------------
    const tipografiaCola = await page
      .locator('[data-testid="cola-palabra"] li')
      .evaluateAll((elementos) =>
        elementos.map((elemento) => {
          const nombre = elemento.querySelector(
            '[data-testid="nombre-cola-palabra"]',
          ) as HTMLElement
          const banca = elemento.querySelector('[data-testid="banca-cola-palabra"]') as HTMLElement
          const circulo = elemento.querySelector('.orden-cola') as HTMLElement
          const cajaCirculo = circulo.getBoundingClientRect()
          return {
            nombrePx: Number.parseFloat(getComputedStyle(nombre).fontSize),
            bancaPx: Number.parseFloat(getComputedStyle(banca).fontSize),
            circulo: { ancho: cajaCirculo.width, alto: cajaCirculo.height },
          }
        }),
      )
    expect(tipografiaCola).toHaveLength(colaReal.length)
    for (const medida of tipografiaCola) {
      // Criterio 7: nombre y banca visiblemente mayores que la baseline.
      expect(medida.nombrePx).toBeGreaterThan(NOMBRE_BASELINE_PX)
      expect(medida.bancaPx).toBeGreaterThan(BANCA_BASELINE_PX)
      // El nombre sigue dominando sobre el número de banca.
      expect(medida.nombrePx).toBeGreaterThan(medida.bancaPx)
      // Criterio 8: el círculo no creció ni un píxel.
      expect(medida.circulo.ancho).toBeCloseTo(CIRCULO_ORDEN_PX, 1)
      expect(medida.circulo.alto).toBeCloseTo(CIRCULO_ORDEN_PX, 1)
    }

    // Criterio 6: la cola no desborda lateralmente ni desplaza su contenedor.
    const desbordeCola = await page.getByTestId('cola-palabra').evaluate((lista) => ({
      horizontal: lista.scrollWidth - lista.clientWidth,
      overflowX: getComputedStyle(lista).overflowX,
    }))
    expect(desbordeCola.horizontal).toBeLessThanOrEqual(0)
    expect(desbordeCola.overflowX).toBe('hidden')

    // Cada renglón queda contenido dentro de la columna de palabra.
    const cajaPalabra = (await page.getByTestId('columna-palabra-publica').boundingBox())!
    const cajasNombres = await page.getByTestId('nombre-cola-palabra').evaluateAll((nombres) =>
      nombres.map((nombre) => {
        const caja = nombre.getBoundingClientRect()
        return { izquierda: caja.left, derecha: caja.right }
      }),
    )
    for (const caja of cajasNombres) {
      expect(caja.izquierda).toBeGreaterThanOrEqual(cajaPalabra.x - 1)
      expect(caja.derecha).toBeLessThanOrEqual(cajaPalabra.x + cajaPalabra.width + 1)
    }

    // -----------------------------------------------------------------------
    // 3 · Quórum presentes/total con tres estados cromáticos
    // -----------------------------------------------------------------------
    /** Lee nivel declarado, texto y color real de la fracción de quórum. */
    async function medirQuorum() {
      return page.getByTestId('panel-quorum').evaluate((panel) => {
        const fraccion = panel.querySelector('[data-testid="cantidad-presentes"]') as HTMLElement
        return {
          nivel: panel.getAttribute('data-nivel-quorum'),
          texto: fraccion.textContent?.replace(/\s+/g, '') ?? '',
          color: getComputedStyle(fraccion).color,
          desborde: fraccion.scrollWidth - fraccion.clientWidth,
        }
      })
    }

    // Criterio 9 y 10: por encima del mínimo, verde.
    const quorumHolgado = await medirQuorum()
    expect(quorumHolgado.texto).toBe('8/12')
    expect(quorumHolgado.nivel).toBe('holgado')
    // La fracción entra completa en el ancho calibrado del panel.
    expect(quorumHolgado.desborde).toBeLessThanOrEqual(0)

    // Exactamente en el mínimo: amarillo, pero el quórum sigue alcanzado.
    await publicar(page, {
      ...sesion,
      revision: 2,
      quorum: { cantidad_presentes: 7, requerido: 7, alcanzado: true },
    })
    await expect(page.getByTestId('cantidad-presentes')).toHaveText('7/12')
    const quorumLimite = await medirQuorum()
    expect(quorumLimite.nivel).toBe('limite')
    // WP-058: el empate exacto con el mínimo tiene texto propio. El quórum sigue
    // alcanzado; lo que la pantalla agrega es que no queda margen.
    await expect(page.getByTestId('estado-quorum')).toHaveText('Quórum límite')

    // Por debajo del mínimo: rojo y sin quórum.
    await publicar(page, {
      ...sesion,
      revision: 3,
      quorum: { cantidad_presentes: 6, requerido: 7, alcanzado: false },
    })
    await expect(page.getByTestId('cantidad-presentes')).toHaveText('6/12')
    const quorumInsuficiente = await medirQuorum()
    expect(quorumInsuficiente.nivel).toBe('insuficiente')
    await expect(page.getByTestId('estado-quorum')).toHaveText('Sin quórum')

    // Los tres estados se distinguen por color real, no sólo por nombre de clase.
    const colores = [quorumHolgado.color, quorumLimite.color, quorumInsuficiente.color]
    expect(new Set(colores).size).toBe(3)

    // -----------------------------------------------------------------------
    // 4 · Rótulo del countdown
    // -----------------------------------------------------------------------
    // El countdown se deriva del reloj corregido con `generado_en`, así que la
    // ventana se construye a partir del instante que ve la propia página.
    const ahoraCountdown = await page.evaluate(() => Date.now())
    await publicar(page, {
      ...sesion,
      revision: 4,
      generado_en: new Date(ahoraCountdown).toISOString(),
      votacion: crearVotacion({
        tema: 'Expediente con cuenta regresiva',
        fecha_hora_apertura: new Date(ahoraCountdown).toISOString(),
        cuenta_regresiva_hasta: new Date(ahoraCountdown + 5000).toISOString(),
      }),
    })
    const countdown = page.getByTestId('countdown-votacion')
    await expect(countdown).toBeVisible()
    // Criterio 11: la recepción ya está abierta, así que el rótulo lo dice.
    await expect(countdown).toContainText('Votación en curso')
    await expect(countdown).not.toContainText('Comienza en')

    // -----------------------------------------------------------------------
    // 5 · Ningún cambio introdujo scroll global
    // -----------------------------------------------------------------------
    const desbordes = await page.evaluate(() => ({
      vertical: document.documentElement.scrollHeight - window.innerHeight,
      horizontal: document.documentElement.scrollWidth - window.innerWidth,
    }))
    expect(desbordes.vertical).toBeLessThanOrEqual(1)
    expect(desbordes.horizontal).toBeLessThanOrEqual(1)
  })
}

/**
 * Evidencia geométrica de legibilidad a distancia (WP-058).
 *
 * HUMAN_GATE pidió textos mucho mayores sin agrandar ningún contenedor y sin
 * generar scroll. Eso no se puede comprobar mirando clases CSS: hay que medir
 * cuerpos tipográficos calculados, bounding boxes y la relación
 * `scrollWidth/clientWidth` y `scrollHeight/clientHeight` de cada contenedor
 * crítico, en las resoluciones canónicas y también en una intermedia.
 *
 * Baselines medidas en Chromium sobre el commit base de este WP:
 *
 * | dato                      | 1920×1080 | 1366×768 |
 * |---------------------------|-----------|----------|
 * | alto de la cabecera       | 59,4 px   | 47,0 px  |
 * | cuerpo del centro         | 16,00 px  | 14,34 px |
 * | cuerpo de la fecha/hora   | 13,12 px  | 12,29 px |
 * | cuenta de transmisión     | 45,36 px  | 32,26 px |
 * | rótulo EN VIVO            | 17,28 px  | 15,20 px |
 *
 * La resolución intermedia de 1440×768 no tiene baseline propia: se exige que
 * el resultado quede entre las dos canónicas y que tampoco desborde.
 */
const BASELINES_WP058 = {
  1920: { altoCabecera: 59.4, centro: 16.0, reloj: 13.12, cuenta: 45.36, enVivo: 17.28 },
  1366: { altoCabecera: 47.0, centro: 14.343, reloj: 12.294, cuenta: 32.256, enVivo: 15.2 },
} as const

/** Devuelve la baseline de la resolución, o `null` para la intermedia. */
function baselineWp058(ancho: number) {
  if (ancho === 1920) return BASELINES_WP058[1920]
  if (ancho === 1366) return BASELINES_WP058[1366]
  return null
}

for (const viewport of [
  { width: 1920, height: 1080 },
  { width: 1440, height: 768 },
  { width: 1366, height: 768 },
]) {
  test(`aplica la legibilidad WP-058 en ${viewport.width}×${viewport.height}`, async ({ page }) => {
    const baseline = baselineWp058(viewport.width)

    await page.setViewportSize(viewport)
    await page.clock.install({ time: new Date('2026-08-28T09:59:00Z') })
    await instalarBackendPublico(page, crearEstado())
    await page.goto('http://localhost:3001/recinto/')
    await page.getByTestId('estado-conexion').waitFor()
    await page.clock.runFor(20)
    await page.clock.pauseAt(HORA_RELOJ_E2E)

    const datosSesion = {
      fecha_hora_inicio_preparacion: '2026-08-28T09:30:00',
      fecha_hora_apertura: '2026-08-28T09:45:00',
      numero_sesion: 59,
      presidencia: 'Ana Presidencia',
      secretaria_legislativa: 'Luis Secretaría',
    }
    /** Transmisión en cuenta regresiva: el número grande de la columna derecha. */
    const transmisionEnCuenta = {
      transmision: {
        estado: 'CUENTA_REGRESIVA',
        iniciada_en: '2026-08-28T09:59:00',
        en_vivo_desde: '2026-08-28T10:02:00',
        cuenta_regresiva_segundos: 180,
        segundos_restantes: 120,
      },
      aviso: null,
    }
    const sesion = crearEstado({
      revision: 1,
      generado_en: '2026-08-28T10:00:00',
      estado_global: 'SESION_ABIERTA',
      sesion: datosSesion,
      filas_bancas: [3, 4, 5],
      concejales: crearConcejales(12),
      quorum: { cantidad_presentes: 8, requerido: 7, alcanzado: true },
      palabra: { orador: { nombre: 'Andrea', apellido: 'Rueda', banca: 3 }, cola: [] },
      votacion: crearVotacion({ tema: 'Expediente breve', cuenta_regresiva_hasta: null }),
      tecnico: transmisionEnCuenta,
    })
    await publicar(page, sesion)
    await expect(page.getByTestId('cabecera-sesion')).toContainText('59')
    await expect(page.getByTestId('imagen-concejal').first()).toBeVisible()
    await page.waitForFunction(() =>
      Array.from(document.querySelectorAll('img')).every((imagen) => imagen.complete),
    )

    /**
     * Mide un elemento: caja, cuerpo tipográfico y desbordes propios.
     *
     * `scrollWidth > clientWidth` o `scrollHeight > clientHeight` significan que
     * el contenido no entra en su propia caja, que es exactamente lo que este WP
     * no puede permitir.
     */
    async function medir(selector: string) {
      return page.locator(selector).evaluate((elemento) => {
        const caja = elemento.getBoundingClientRect()
        const estilo = getComputedStyle(elemento)
        return {
          x: caja.x,
          y: caja.y,
          ancho: caja.width,
          alto: caja.height,
          cuerpo: Number.parseFloat(estilo.fontSize),
          desbordeHorizontal: elemento.scrollWidth - elemento.clientWidth,
          desbordeVertical: elemento.scrollHeight - elemento.clientHeight,
        }
      })
    }

    /** Content box real de un contenedor: su caja interior menos borde y relleno. */
    async function medirContentBox(selector: string) {
      return page.locator(selector).evaluate((elemento) => {
        const caja = elemento.getBoundingClientRect()
        const estilo = getComputedStyle(elemento)
        const izquierda =
          caja.x + Number.parseFloat(estilo.borderLeftWidth) + Number.parseFloat(estilo.paddingLeft)
        const arriba =
          caja.y + Number.parseFloat(estilo.borderTopWidth) + Number.parseFloat(estilo.paddingTop)
        const derecha =
          caja.right -
          Number.parseFloat(estilo.borderRightWidth) -
          Number.parseFloat(estilo.paddingRight)
        const abajo =
          caja.bottom -
          Number.parseFloat(estilo.borderBottomWidth) -
          Number.parseFloat(estilo.paddingBottom)
        return { izquierda, arriba, derecha, abajo }
      })
    }

    // -----------------------------------------------------------------------
    // 1 · Cabecera: mismo alto físico, cuerpo mucho mayor y una sola línea
    // -----------------------------------------------------------------------
    const cabecera = await medir('[data-testid="cabecera-recinto"]')
    const reloj = await medir('[data-testid="cabecera-fecha-hora"]')
    const contexto = await medir('[data-testid="cabecera-contexto"]')
    const titulo = await medir('.titulo-institucional')
    const sectorDerecho = await medir('.sector-derecho')

    // El cuerpo del centro se lee en sus datos, no en el contenedor flex: la
    // caja `.marca-institucional` conserva el tamaño heredado y sólo aporta la
    // geometría del renglón.
    const sesionTexto = await medir('[data-testid="cabecera-sesion"]')
    const duracion = await medir('[data-testid="cabecera-tiempo-sesion"]')

    if (baseline) {
      // Criterio 1: la altura física de la cabecera no crece ni un píxel.
      expect(cabecera.alto).toBeCloseTo(baseline.altoCabecera, 1)
      // Criterio 2: el centro se acerca al doble del cuerpo anterior.
      expect(titulo.cuerpo / baseline.centro).toBeGreaterThan(1.35)
      // La fecha/hora crece todavía más porque partía de un cuerpo menor.
      expect(reloj.cuerpo / baseline.reloj).toBeGreaterThan(1.6)
    }
    // Nunca por encima del techo físico de la franja.
    expect(cabecera.alto).toBeLessThanOrEqual(60)

    // Institución, sesión y duración conservan una única jerarquía (WP-054) y la
    // fecha/hora alcanza exactamente ese mismo alto tipográfico (WP-058).
    expect(sesionTexto.cuerpo).toBeCloseTo(titulo.cuerpo, 2)
    expect(duracion.cuerpo).toBeCloseTo(titulo.cuerpo, 2)
    expect(reloj.cuerpo).toBeCloseTo(titulo.cuerpo, 2)
    // La fecha/hora conserva su fuente monoespaciada y su lugar a la izquierda.
    const familiaReloj = await page
      .getByTestId('cabecera-fecha-hora')
      .evaluate((elemento) => getComputedStyle(elemento).fontFamily)
    expect(familiaReloj).toContain('monospace')
    expect(reloj.x).toBeLessThan(contexto.x)

    // Una sola línea, sin recortes y sin desbordar la cabecera.
    expect(reloj.desbordeHorizontal).toBeLessThanOrEqual(0)
    expect(contexto.desbordeHorizontal).toBeLessThanOrEqual(0)
    expect(cabecera.desbordeVertical).toBeLessThanOrEqual(0)
    // Y ningún renglón desborda su propia caja: al duplicar el cuerpo, un
    // interlineado apenas corto dejaba la tinta 1 px fuera del renglón. No se
    // veía, pero es la definición misma del recorte silencioso que este WP
    // tiene que descartar, así que se fija acá.
    for (const renglon of [reloj, contexto, titulo, sesionTexto, duracion]) {
      expect(renglon.desbordeVertical).toBeLessThanOrEqual(0)
    }
    expect(contexto.alto).toBeLessThanOrEqual(cabecera.alto)
    for (const caja of [reloj, contexto, sectorDerecho]) {
      expect(caja.y).toBeGreaterThanOrEqual(cabecera.y - 1)
      expect(caja.y + caja.alto).toBeLessThanOrEqual(cabecera.y + cabecera.alto + 1)
    }

    // Sin colisión entre las tres zonas: el crecimiento no invadió a nadie.
    expect(reloj.x + reloj.ancho).toBeLessThanOrEqual(contexto.x)
    expect(contexto.x + contexto.ancho).toBeLessThanOrEqual(sectorDerecho.x)
    // Y el centro sigue estando realmente centrado (tolerancia de subpíxel).
    expect(Math.abs(contexto.x + contexto.ancho / 2 - viewport.width / 2)).toBeLessThanOrEqual(2)

    // -----------------------------------------------------------------------
    // 2 · Transmisión en cuenta regresiva: el texto entra en el content box
    // -----------------------------------------------------------------------
    const bloque = await medir('[data-testid="bloque-transmision"]')
    const contenidoBloque = await medirContentBox('[data-testid="bloque-transmision"]')
    const rotulo = await medir('.rotulo-transmision')
    const numero = await medir('[data-testid="cuenta-regresiva-transmision"]')

    if (baseline) {
      // Criterio 3: la cuenta se acerca al máximo razonable del contenedor.
      expect(numero.cuerpo / baseline.cuenta).toBeGreaterThan(1.9)
    }
    // Ninguno de los dos textos sale del content box del bloque, que es la
    // demostración que exige el WP: no alcanza con que "se vea bien".
    for (const texto of [rotulo, numero]) {
      expect(texto.x).toBeGreaterThanOrEqual(contenidoBloque.izquierda - 0.5)
      expect(texto.x + texto.ancho).toBeLessThanOrEqual(contenidoBloque.derecha + 0.5)
      expect(texto.y).toBeGreaterThanOrEqual(contenidoBloque.arriba - 0.5)
      expect(texto.y + texto.alto).toBeLessThanOrEqual(contenidoBloque.abajo + 0.5)
      expect(texto.desbordeHorizontal).toBeLessThanOrEqual(0)
      expect(texto.desbordeVertical).toBeLessThanOrEqual(0)
    }
    // El contenedor no ganó scroll propio en ninguna dirección.
    expect(bloque.desbordeHorizontal).toBeLessThanOrEqual(0)
    expect(bloque.desbordeVertical).toBeLessThanOrEqual(0)

    // -----------------------------------------------------------------------
    // 3 · Bancas: tarjetas uniformes y más escala útil sin recortar contenido
    // -----------------------------------------------------------------------
    const tarjetas = await page.getByTestId('banca-publica').evaluateAll((nodos) =>
      nodos.map((nodo) => {
        const caja = nodo.getBoundingClientRect()
        const imagen = nodo.querySelector('[data-testid="imagen-concejal"]') as HTMLImageElement
        const area = nodo.querySelector('.area-imagen') as HTMLElement
        const cajaArea = area.getBoundingClientRect()
        const estilo = getComputedStyle(imagen)
        return {
          ancho: Math.round(caja.width),
          alto: Math.round(caja.height),
          areaAncho: cajaArea.width,
          areaAlto: cajaArea.height,
          ajuste: estilo.objectFit,
          recorte: estilo.objectViewBox,
          naturalAlto: imagen.naturalHeight,
          naturalAncho: imagen.naturalWidth,
          cargada: imagen.naturalWidth > 0,
          dentro:
            cajaArea.left >= caja.left - 1 &&
            cajaArea.right <= caja.right + 1 &&
            cajaArea.top >= caja.top - 1 &&
            cajaArea.bottom <= caja.bottom + 1,
        }
      }),
    )
    expect(tarjetas).toHaveLength(12)
    for (const tarjeta of tarjetas) {
      // Criterio 4, primera mitad: todas las tarjetas siguen midiendo lo mismo.
      expect(tarjeta.ancho).toBe(tarjetas[0]!.ancho)
      expect(tarjeta.alto).toBe(tarjetas[0]!.alto)
      expect(tarjeta.cargada).toBe(true)
      expect(tarjeta.dentro).toBe(true)
      // El ajuste sigue siendo `contain`: nada del lienzo visible se recorta.
      expect(tarjeta.ajuste).toBe('contain')
      // Criterio 4, segunda mitad: el recorte de margen inerte está aplicado.
      // `assets_bancas_wp058.test.ts` demuestra que ese marco no tiene contenido.
      expect(tarjeta.recorte).toBe('inset(12px 33px 3px)')
      expect(tarjeta.naturalAlto).toBe(300)
      expect(tarjeta.naturalAncho).toBe(300)
    }

    // La tarjeta es más ancha que alta, así que `contain` ajusta por altura: la
    // escala útil pasa de alto/300 a alto/285 px de lienzo. Se comprueba la
    // premisa (tarjeta apaisada) y la ganancia resultante.
    const primera = tarjetas[0]!
    expect(primera.areaAncho / primera.areaAlto).toBeGreaterThan(234 / 285)
    const escalaAntes = primera.areaAlto / 300
    const escalaDespues = primera.areaAlto / (300 - 12 - 3)
    expect(escalaDespues).toBeGreaterThan(escalaAntes)
    expect(escalaDespues / escalaAntes).toBeCloseTo(1.053, 2)

    // -----------------------------------------------------------------------
    // 4 · Quórum: las tres redacciones sobre números ya proyectados
    // -----------------------------------------------------------------------
    await expect(page.getByTestId('estado-quorum')).toHaveText('Quórum alcanzado')

    await publicar(page, {
      ...sesion,
      revision: 2,
      quorum: { cantidad_presentes: 7, requerido: 7, alcanzado: true },
    })
    await expect(page.getByTestId('cantidad-presentes')).toHaveText('7/12')
    await expect(page.getByTestId('estado-quorum')).toHaveText('Quórum límite')
    // El backend sigue declarando alcanzado: la pantalla no cambió la regla.
    await expect(page.getByTestId('panel-quorum')).toHaveAttribute('data-nivel-quorum', 'limite')

    await publicar(page, {
      ...sesion,
      revision: 3,
      quorum: { cantidad_presentes: 6, requerido: 7, alcanzado: false },
    })
    await expect(page.getByTestId('estado-quorum')).toHaveText('Sin quórum')

    // -----------------------------------------------------------------------
    // 5 · EN VIVO: mismo contenedor, texto mucho mayor, sin desbordes
    // -----------------------------------------------------------------------
    await publicar(page, {
      ...sesion,
      revision: 4,
      tecnico: {
        transmision: {
          estado: 'EN_VIVO',
          iniciada_en: '2026-08-28T09:59:00',
          en_vivo_desde: '2026-08-28T09:59:30',
          cuenta_regresiva_segundos: 30,
          segundos_restantes: 0,
        },
        aviso: null,
      },
    })
    await expect(page.getByTestId('en-vivo')).toBeVisible()
    const bloqueEnVivo = await medir('[data-testid="bloque-transmision"]')
    const contenidoEnVivo = await medirContentBox('[data-testid="bloque-transmision"]')
    const enVivo = await medir('[data-testid="en-vivo"]')

    if (baseline) {
      expect(enVivo.cuerpo / baseline.enVivo).toBeGreaterThan(1.9)
    }
    // El contenedor no cambió de tamaño al cambiar de estado.
    expect(bloqueEnVivo.ancho).toBeCloseTo(bloque.ancho, 1)
    expect(bloqueEnVivo.alto).toBeCloseTo(bloque.alto, 1)
    expect(enVivo.x).toBeGreaterThanOrEqual(contenidoEnVivo.izquierda - 0.5)
    expect(enVivo.x + enVivo.ancho).toBeLessThanOrEqual(contenidoEnVivo.derecha + 0.5)
    expect(enVivo.y).toBeGreaterThanOrEqual(contenidoEnVivo.arriba - 0.5)
    expect(enVivo.y + enVivo.alto).toBeLessThanOrEqual(contenidoEnVivo.abajo + 0.5)
    expect(enVivo.desbordeHorizontal).toBeLessThanOrEqual(0)
    expect(enVivo.desbordeVertical).toBeLessThanOrEqual(0)
    expect(bloqueEnVivo.desbordeHorizontal).toBeLessThanOrEqual(0)
    expect(bloqueEnVivo.desbordeVertical).toBeLessThanOrEqual(0)

    // -----------------------------------------------------------------------
    // 6 · Countdown de votación: el rótulo correcto no puede volver atrás
    // -----------------------------------------------------------------------
    const ahoraCountdown = await page.evaluate(() => Date.now())
    await publicar(page, {
      ...sesion,
      revision: 5,
      generado_en: new Date(ahoraCountdown).toISOString(),
      votacion: crearVotacion({
        tema: 'Expediente con cuenta regresiva',
        fecha_hora_apertura: new Date(ahoraCountdown).toISOString(),
        cuenta_regresiva_hasta: new Date(ahoraCountdown + 5000).toISOString(),
      }),
    })
    const countdown = page.getByTestId('countdown-votacion')
    await expect(countdown).toBeVisible()
    await expect(countdown).toContainText('Votación en curso')
    await expect(countdown).not.toContainText('Comienza en')

    // -----------------------------------------------------------------------
    // 7 · Contenedores críticos sin scroll propio ni scroll global
    // -----------------------------------------------------------------------
    const criticos = [
      'cabecera-recinto',
      'franja-votacion-quorum',
      'panel-quorum',
      'zona-principal-recinto',
      'area-bancas-publica',
      'columna-palabra-publica',
      'bloque-transmision',
      'grilla-bancas',
    ] as const
    for (const selector of criticos) {
      const desbordes = await page.getByTestId(selector).evaluate((elemento) => ({
        horizontal: elemento.scrollWidth - elemento.clientWidth,
        vertical: elemento.scrollHeight - elemento.clientHeight,
      }))
      expect({ selector, ...desbordes }).toEqual({ selector, horizontal: 0, vertical: 0 })
    }

    const desbordeGlobal = await page.evaluate(() => ({
      vertical: document.documentElement.scrollHeight - window.innerHeight,
      horizontal: document.documentElement.scrollWidth - window.innerWidth,
    }))
    expect(desbordeGlobal.vertical).toBeLessThanOrEqual(1)
    expect(desbordeGlobal.horizontal).toBeLessThanOrEqual(1)
  })
}

/**
 * Legibilidad de los nombres de la cola de palabra (WP-064).
 *
 * HUMAN_GATE decidió que el nombre debía crecer **aproximadamente un 80 %**
 * respecto de lo que había dejado WP-054, sin ensanchar la columna ni rediseñar
 * el resto del Recinto. Esa afirmación no se puede sostener leyendo el CSS: hay
 * que medir el cuerpo tipográfico calculado y las cajas reales en las dos
 * resoluciones canónicas, con la cola vacía, con un solo pedido y con varios.
 *
 * Baselines medidas en Chromium sobre el commit base de este WP (raíz 16 px):
 *
 * | dato                          | 1920×1080 | 1366×768  |
 * |-------------------------------|-----------|-----------|
 * | nombre en cola                | 19,584 px | 14,720 px |
 * | ancho de la columna de palabra | 384,00 px | 273,19 px |
 * | ancho del panel de palabra    | 384,00 px | 273,19 px |
 * | círculo de orden              | 25,59 px  | 25,59 px  |
 *
 * El factor exigido es exactamente 1,8 porque el `clamp` nuevo multiplica por
 * 1,8 sus tres términos: gane el que gane en cada resolución, la proporción se
 * conserva. Se admite una tolerancia mínima para el redondeo de subpíxel.
 */
const BASELINES_WP064 = {
  1920: { nombrePx: 19.584, anchoColumna: 384.0 },
  1366: { nombrePx: 14.72, anchoColumna: 273.19 },
} as const

/** Factor de crecimiento pedido por HUMAN_GATE para el nombre de la cola. */
const FACTOR_NOMBRE_WP064 = 1.8

/** Diámetro congelado del círculo de orden, heredado sin cambios de WP-054. */
const CIRCULO_ORDEN_WP064_PX = 25.59

for (const viewport of [
  { width: 1920, height: 1080 },
  { width: 1366, height: 768 },
]) {
  test(`agranda los nombres de la cola de palabra WP-064 en ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    const baseline = BASELINES_WP064[viewport.width as 1920 | 1366]

    await page.setViewportSize(viewport)
    await page.clock.install({ time: new Date('2026-08-28T09:59:00Z') })
    await instalarBackendPublico(page, crearEstado())
    await page.goto('http://localhost:3001/recinto/')
    await page.getByTestId('estado-conexion').waitFor()
    await page.clock.runFor(20)
    await page.clock.pauseAt(HORA_RELOJ_E2E)

    const datosSesion = {
      fecha_hora_inicio_preparacion: '2026-08-28T09:30:00',
      fecha_hora_apertura: '2026-08-28T09:45:00',
      numero_sesion: 59,
      presidencia: 'Ana Presidencia',
      secretaria_legislativa: 'Luis Secretaría',
    }
    /** Sesión abierta cuya única variable entre escenarios es la cola. */
    function sesionConCola(revision: number, cola: Record<string, unknown>[]) {
      return crearEstado({
        revision,
        generado_en: '2026-08-28T10:00:00',
        estado_global: 'SESION_ABIERTA',
        sesion: datosSesion,
        filas_bancas: [3, 4, 5],
        concejales: crearConcejales(12),
        quorum: { cantidad_presentes: 8, requerido: 7, alcanzado: true },
        palabra: { orador: { nombre: 'Andrea', apellido: 'Rueda', banca: 3 }, cola },
        votacion: crearVotacion({ tema: 'Expediente breve', cuenta_regresiva_hasta: null }),
      })
    }

    /**
     * Mide, en una sola pasada por el DOM, todo lo que el WP exige comprobar:
     * cuerpo tipográfico, cajas y relación `scroll*`/`client*` de los
     * contenedores que podrían desbordar.
     */
    async function medirCola() {
      return page.evaluate(() => {
        /** Caja de un elemento redondeada para comparar sin ruido de subpíxel. */
        function caja(elemento: HTMLElement) {
          const rectangulo = elemento.getBoundingClientRect()
          return {
            ancho: rectangulo.width,
            alto: rectangulo.height,
            izquierda: rectangulo.left,
            derecha: rectangulo.right,
          }
        }
        /** Desborde propio de un contenedor, en píxeles. */
        function desborde(elemento: HTMLElement) {
          return {
            horizontal: elemento.scrollWidth - elemento.clientWidth,
            vertical: elemento.scrollHeight - elemento.clientHeight,
          }
        }

        const columna = document.querySelector(
          '[data-testid="columna-palabra-publica"]',
        ) as HTMLElement
        const panel = document.querySelector('[data-testid="panel-palabra"]') as HTMLElement
        const lista = document.querySelector('[data-testid="cola-palabra"]') as HTMLElement | null

        return {
          columna: { ...caja(columna), ...desborde(columna) },
          panel: { ...caja(panel), ...desborde(panel) },
          lista: lista
            ? {
                ...caja(lista),
                ...desborde(lista),
                clientWidth: lista.clientWidth,
                overflowX: getComputedStyle(lista).overflowX,
              }
            : null,
          renglones: [...(lista?.querySelectorAll('li') ?? [])].map((renglon) => {
            const nombre = renglon.querySelector(
              '[data-testid="nombre-cola-palabra"]',
            ) as HTMLElement
            const circulo = renglon.querySelector('.orden-cola') as HTMLElement
            const estilo = getComputedStyle(nombre)
            return {
              texto: nombre.textContent?.replace(/\s+/g, ' ').trim() ?? '',
              nombrePx: Number.parseFloat(estilo.fontSize),
              alturaLinea: Number.parseFloat(estilo.lineHeight),
              recorte: { overflow: estilo.overflow, salto: estilo.whiteSpace },
              caja: caja(nombre),
              // `clientHeight` frente a `scrollHeight` delata si el texto pasó
              // a ocupar dos renglones: el WP exige que siga en uno solo.
              altoVisible: nombre.clientHeight,
              altoContenido: nombre.scrollHeight,
              circulo: caja(circulo),
            }
          }),
          documento: {
            horizontal: document.documentElement.scrollWidth - window.innerWidth,
            vertical: document.documentElement.scrollHeight - window.innerHeight,
          },
        }
      })
    }

    /** Comprobaciones comunes a todos los escenarios de cola. */
    function exigirGeometriaEstable(medidas: Awaited<ReturnType<typeof medirCola>>) {
      // Criterio 5: la columna y el panel conservan sus dimensiones estructurales.
      expect(medidas.columna.ancho).toBeCloseTo(baseline.anchoColumna, 1)
      expect(medidas.panel.ancho).toBeCloseTo(baseline.anchoColumna, 1)
      // Criterio 3: ni la columna ni el panel desarrollan desplazamiento propio.
      expect(medidas.columna.horizontal).toBe(0)
      expect(medidas.columna.vertical).toBe(0)
      expect(medidas.panel.horizontal).toBe(0)
      expect(medidas.panel.vertical).toBe(0)
      // Criterio 4: la página completa sigue sin scroll en ningún eje.
      expect(medidas.documento.horizontal).toBeLessThanOrEqual(1)
      expect(medidas.documento.vertical).toBeLessThanOrEqual(1)
    }

    // -----------------------------------------------------------------------
    // 1 · Cola vacía: el panel existe, no dibuja lista y no desborda
    // -----------------------------------------------------------------------
    await publicar(page, sesionConCola(1, []))
    await expect(page.getByTestId('cantidad-pedidos-palabra')).toHaveText('0')
    await expect(page.getByTestId('cola-palabra')).toHaveCount(0)
    await expect(page.getByTestId('panel-palabra')).toContainText('No hay pedidos en espera')
    const colaVacia = await medirCola()
    expect(colaVacia.lista).toBeNull()
    exigirGeometriaEstable(colaVacia)

    // -----------------------------------------------------------------------
    // 2 · Un solo pedido: el nombre crece ≈80 % y sigue en una línea
    // -----------------------------------------------------------------------
    // Nombre tomado del padrón real y deliberadamente largo: es el caso que
    // pondría en riesgo el ancho de la columna si el recorte no funcionara.
    const unicoPedido = [{ nombre: 'María Eugenia', apellido: 'Fernández Robledo', banca: 7 }]
    await publicar(page, sesionConCola(2, unicoPedido))
    await expect(page.getByTestId('cola-palabra').locator('li')).toHaveCount(1)
    const unaEntrada = await medirCola()
    exigirGeometriaEstable(unaEntrada)
    expect(unaEntrada.renglones).toHaveLength(1)

    const renglonUnico = unaEntrada.renglones[0]!
    // Criterio 1: el crecimiento medido es exactamente el factor pedido. La
    // tolerancia de 0,05 px sólo absorbe el redondeo de subpíxel del navegador.
    expect(renglonUnico.nombrePx).toBeCloseTo(baseline.nombrePx * FACTOR_NOMBRE_WP064, 1)
    expect(renglonUnico.nombrePx / baseline.nombrePx).toBeGreaterThanOrEqual(1.75)
    expect(renglonUnico.nombrePx / baseline.nombrePx).toBeLessThanOrEqual(1.85)
    // Criterio 2: una sola línea, con el recorte determinista de siempre.
    expect(renglonUnico.altoContenido).toBe(renglonUnico.altoVisible)
    expect(renglonUnico.altoVisible).toBeLessThanOrEqual(Math.ceil(renglonUnico.alturaLinea) + 1)
    expect(renglonUnico.recorte).toEqual({ overflow: 'hidden', salto: 'nowrap' })
    // El círculo de orden no participó del crecimiento (herencia de WP-054).
    expect(renglonUnico.circulo.ancho).toBeCloseTo(CIRCULO_ORDEN_WP064_PX, 1)
    expect(renglonUnico.circulo.alto).toBeCloseTo(CIRCULO_ORDEN_WP064_PX, 1)

    // Decisión humana 2: el nombre aprovecha casi todo el ancho útil del
    // renglón. Lo que queda fuera es sólo el círculo de orden y su separación.
    const anchoUtil = unaEntrada.lista!.clientWidth
    expect(renglonUnico.caja.ancho / anchoUtil).toBeGreaterThanOrEqual(0.82)
    // Y aun así termina dentro de la columna: no la ensancha ni la desborda.
    expect(renglonUnico.caja.derecha).toBeLessThanOrEqual(unaEntrada.columna.derecha + 1)
    expect(renglonUnico.caja.izquierda).toBeGreaterThanOrEqual(unaEntrada.columna.izquierda - 1)

    // -----------------------------------------------------------------------
    // 3 · Varios pedidos: el panel sigue siendo usable y sin desborde lateral
    // -----------------------------------------------------------------------
    const colaLarga = [
      { nombre: 'María Eugenia', apellido: 'Fernández Robledo', banca: 7 },
      { nombre: 'Gastón', apellido: 'Cuis Taccari', banca: 4 },
      { nombre: 'Juan', apellido: 'Pérez', banca: 1 },
      { nombre: 'Federico', apellido: 'Garitano', banca: 9 },
      { nombre: 'Lorena', apellido: 'Moreno', banca: 2 },
      { nombre: 'Andrea', apellido: 'Rueda', banca: 5 },
    ]
    await publicar(page, sesionConCola(3, colaLarga))
    await expect(page.getByTestId('cola-palabra').locator('li')).toHaveCount(colaLarga.length)
    const variasEntradas = await medirCola()
    exigirGeometriaEstable(variasEntradas)
    expect(variasEntradas.renglones).toHaveLength(colaLarga.length)

    // El orden FIFO recibido se conserva pese al cambio tipográfico.
    expect(variasEntradas.renglones.map((renglon) => renglon.texto)).toEqual(
      colaLarga.map((persona) => `${persona.nombre} ${persona.apellido}`),
    )
    for (const renglon of variasEntradas.renglones) {
      expect(renglon.nombrePx).toBeCloseTo(baseline.nombrePx * FACTOR_NOMBRE_WP064, 1)
      expect(renglon.altoContenido).toBe(renglon.altoVisible)
      expect(renglon.circulo.ancho).toBeCloseTo(CIRCULO_ORDEN_WP064_PX, 1)
      // Cada renglón queda contenido dentro de la columna de palabra.
      expect(renglon.caja.derecha).toBeLessThanOrEqual(variasEntradas.columna.derecha + 1)
      expect(renglon.caja.izquierda).toBeGreaterThanOrEqual(variasEntradas.columna.izquierda - 1)
    }

    // Criterio 3: la lista nunca se desplaza en horizontal, ni siquiera con el
    // nombre más largo del padrón. El desplazamiento vertical sí es legítimo:
    // es el mecanismo con el que la cola absorbe más pedidos que altura.
    expect(variasEntradas.lista!.horizontal).toBe(0)
    expect(variasEntradas.lista!.overflowX).toBe('hidden')

    // -----------------------------------------------------------------------
    // 4 · Volver a cola vacía deja la geometría como al principio
    // -----------------------------------------------------------------------
    await publicar(page, sesionConCola(4, []))
    await expect(page.getByTestId('cantidad-pedidos-palabra')).toHaveText('0')
    exigirGeometriaEstable(await medirCola())
  })
}
