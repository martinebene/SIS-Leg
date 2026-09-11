/**
 * Pruebas Playwright para el Shell y la UI de Moderación de SIS-Leg (WP-021 a WP-023).
 *
 * Cobertura de pruebas E2E deterministas (H3, N1, WP-036):
 * 1. Contrato de Shell 2×2 completo en 1920×1080 y 1366×768:
 *    - Cabecera compacta permanente, sin el distintivo BOTONERA2.
 *    - Cuatro cuadrantes simultáneos (Q1 Sesión, Q2 Orden del Día, Q3 Recinto, Q4 Eventos).
 *    - Cuatro títulos visibles y bounding boxes válidos.
 *    - Alineación precisa por filas y columnas sin solapamientos horizontales ni verticales.
 *    - Ausencia de scroll de página en ambas resoluciones.
 * 2. Estado SIN_PREPARAR (1920×1080 y 1366×768):
 *    - Vista de recinto sin preparar con botón 'Preparar recinto'.
 *    - Ausencia de todo indicador de quórum mientras el backend no lo proyecta.
 * 3. Estado PREPARANDO (1920×1080 y 1366×768):
 *    - Inputs de número de sesión y autoridades institucionales.
 *    - Botones de guardar preparación, abrir sesión y cancelar preparación.
 *    - 12 bancas en recinto con fotos, nombres, presencia y señal de test activo.
 *    - Quórum y autoridades ya cargadas visibles en la cabecera, y no repetidos en los cuadrantes.
 * 4. Estado SESION_ABIERTA y Diálogo de Advertencia de Cierre (1920×1080 y 1366×768):
 *    - Ausencia en Q1 del resumen de quórum y, desde WP-048, del número de sesión.
 *    - Quórum, autoridades, reloj local y tiempo de sesión en cabecera.
 *    - Edición de autoridades mediante modal, sin inputs permanentes en Q1.
 *    - Apertura de diálogo modal de confirmación ante orador/cola de palabra activa (H4).
 *    - Accesibilidad del diálogo (role="dialog", aria-modal="true") y cancelación segura.
 * 5. Aislamiento de scroll interno:
 *    - Demostración de que el crecimiento de contenido en contenedores internos genera scroll local
 *      sin deformar ni aumentar las alturas exteriores de los paneles hermanos ni producir scroll global.
 */

import { test, expect, type Page } from '@playwright/test'

import { instalarFotosConcejales } from './soporte/fotos_concejales'

function crearConcejalesFixture(cantidad = 12) {
  return Array.from({ length: cantidad }, (_, i) => {
    const banca = i + 1
    const pad = String(banca).padStart(2, '0')
    return {
      banca,
      dni: `300000${pad}`,
      nombre: `Concejal${pad}`,
      apellido: `Apellido${pad}`,
      nombre_mostrar: `C. Apellido${pad}`,
      bloque: banca % 2 === 0 ? 'Frente de Todos' : 'Juntos por el Cambio',
      ruta_imagen: `assets/bancas/banca-${pad}.png`,
      dispositivo_votacion: `dev${pad}`,
      presente: banca <= 8,
      test_activo: banca === 1,
      test_expira_en: banca === 1 ? '2026-08-25T10:00:05Z' : null,
    }
  })
}

function crearEstadoFixture(parcial: Record<string, unknown> = {}) {
  return {
    instancia: 'instancia-prueba',
    revision: 1,
    generado_en: '2026-08-25T10:00:00Z',
    estado_global: 'SIN_PREPARAR',
    preparacion: null,
    sesion: null,
    votacion: null,
    palabra: {
      orador: null,
      cola: [],
    },
    quorum: null,
    configuracion: {
      filas_bancas: [3, 4, 5],
    },
    concejales: crearConcejalesFixture(12),
    capacidades: {
      preparar_sala: { habilitada: true, motivos: [] },
      actualizar_preparacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      cancelar_preparacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      abrir_sesion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      actualizar_sesion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      cerrar_sesion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      iniciar_votacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      cancelar_votacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      cerrar_votacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      desempatar: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      solicitar_palabra: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      cancelar_solicitud_palabra: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      otorgar_palabra: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      quitar_palabra: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      iniciar_remapeo: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      confirmar_remapeo: { habilitada: false, motivos: ['REMAPEO_NO_COINCIDE'] },
      cancelar_remapeo: { habilitada: false, motivos: ['REMAPEO_NO_COINCIDE'] },
      subir_orden_dia: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      seleccionar_expediente: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      cerrar_expediente: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      registrar_evento_manual: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
    },
    // Porción técnica en su estado inicial (WP-056): sin transmisión ni aviso, que es
    // lo que publica el backend mientras Apoyo Técnico no interviene.
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

async function configurarRutasMock(page: Page, estado: Record<string, unknown>) {
  // WP-098: la fotografía de banca ya no es un asset del build; la publica
  // el backend desde la configuración local. Sin backend real, se responde
  // desde la plantilla versionada, que es el mismo archivo de siempre.
  await instalarFotosConcejales(page)

  const estadoJson = JSON.stringify(estado)

  await page.addInitScript((jsonStr) => {
    // 1. Mock de EventSource para streaming SSE determinista
    class MockEventSource {
      url: string
      readyState = 1
      listeners: Record<string, ((e: unknown) => void)[]> = {}
      onopen: ((e: unknown) => void) | null = null
      onerror: ((e: unknown) => void) | null = null
      onmessage: ((e: unknown) => void) | null = null

      constructor(url: string) {
        this.url = url
        setTimeout(() => {
          if (this.onopen) this.onopen({ type: 'open' })
          const handlers = this.listeners['estado'] || []
          for (const handler of handlers) {
            handler({ type: 'estado', data: jsonStr })
          }
        }, 10)
      }

      addEventListener(tipo: string, handler: (e: unknown) => void) {
        this.listeners[tipo] = this.listeners[tipo] || []
        this.listeners[tipo].push(handler)
      }

      removeEventListener(tipo: string, handler: (e: unknown) => void) {
        if (!this.listeners[tipo]) return
        this.listeners[tipo] = this.listeners[tipo].filter((h) => h !== handler)
      }

      close() {
        this.readyState = 2
      }
    }

    // @ts-expect-error Mock inyectado en el runtime del navegador
    window.EventSource = MockEventSource

    // 2. Mock de fetch para snapshots REST inmediatos (MN-3: sin ramas muertas)
    const originalFetch = window.fetch.bind(window)
    window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url

      if (url.includes('/api/v1/estado/moderacion')) {
        return new Response(jsonStr, {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }

      return originalFetch(input, init)
    }
  }, estadoJson)
}

/**
 * Instala un backend controlado que publica snapshots completos después de cada comando.
 * La prueba de WP-023 puede así recorrer transiciones autoritativas sin calcular resultados
 * en el frontend ni depender de un backend real dentro del test de interfaz.
 */
async function configurarCicloVotacionMock(page: Page, estadoInicial: Record<string, unknown>) {
  // WP-098: la fotografía de banca ya no es un asset del build; la publica
  // el backend desde la configuración local. Sin backend real, se responde
  // desde la plantilla versionada, que es el mismo archivo de siempre.
  await instalarFotosConcejales(page)

  await page.addInitScript((inicial) => {
    type EstadoPrueba = Record<string, unknown> & {
      revision: number
      votacion: Record<string, unknown> | null
      capacidades: Record<string, { habilitada: boolean; motivos: string[] }>
    }

    let estadoActual = inicial as EstadoPrueba
    const fuentes: MockEventSourceVotacion[] = []

    function publicar(nuevoEstado: EstadoPrueba): void {
      estadoActual = nuevoEstado
      const data = JSON.stringify(estadoActual)
      for (const fuente of fuentes) {
        for (const handler of fuente.listeners.estado ?? []) {
          handler({ type: 'estado', data })
        }
      }
    }

    class MockEventSourceVotacion {
      readyState = 1
      listeners: Record<string, ((evento: { type: string; data: string }) => void)[]> = {}
      onopen: ((evento: { type: string }) => void) | null = null
      onerror: ((evento: { type: string }) => void) | null = null
      onmessage: ((evento: { type: string; data: string }) => void) | null = null

      constructor(readonly url: string) {
        fuentes.push(this)
        setTimeout(() => {
          this.onopen?.({ type: 'open' })
          const data = JSON.stringify(estadoActual)
          for (const handler of this.listeners.estado ?? []) handler({ type: 'estado', data })
        }, 5)
      }

      addEventListener(
        tipo: string,
        handler: (evento: { type: string; data: string }) => void,
      ): void {
        this.listeners[tipo] = this.listeners[tipo] ?? []
        this.listeners[tipo]?.push(handler)
      }

      removeEventListener(
        tipo: string,
        handler: (evento: { type: string; data: string }) => void,
      ): void {
        this.listeners[tipo] = (this.listeners[tipo] ?? []).filter(
          (registrado) => registrado !== handler,
        )
      }

      close(): void {
        this.readyState = 2
      }
    }

    // @ts-expect-error EventSource controlado para este recorrido de navegador.
    window.EventSource = MockEventSourceVotacion

    const ventanaPrueba = window as Window & {
      cerrarComoEmpatada?: () => void
      perderQuorum?: () => void
    }
    /**
     * WP-051: simula la pérdida de quórum durante la sesión abierta. El backend deja de
     * habilitar `abrir_votacion` con el motivo estable `QUORUM_INSUFICIENTE`; la sesión
     * sigue abierta, así que el frontend debe leer ese motivo en clave de votación.
     */
    ventanaPrueba.perderQuorum = () => {
      publicar({
        ...estadoActual,
        revision: estadoActual.revision + 1,
        quorum: { cantidad_presentes: 3, requerido: 7, alcanzado: false },
        capacidades: {
          ...estadoActual.capacidades,
          abrir_votacion: { habilitada: false, motivos: ['QUORUM_INSUFICIENTE'] },
        },
      })
    }
    ventanaPrueba.cerrarComoEmpatada = () => {
      if (!estadoActual.votacion) return
      publicar({
        ...estadoActual,
        revision: estadoActual.revision + 1,
        votacion: {
          ...estadoActual.votacion,
          estado_recepcion: 'CERRADA',
          resultado: 'EMPATADA',
          fecha_hora_cierre: '2026-08-26T10:00:10Z',
          fecha_hora_resultado: '2026-08-26T10:00:10Z',
          cantidad_votos_recibidos: 8,
          bancas_voto_emitido: [],
          votos_individuales_revelados: true,
          votos_individuales: [
            {
              dni: '30000001',
              nombre: 'Concejal01',
              apellido: 'Apellido01',
              banca: 1,
              valor: 'POSITIVO',
            },
          ],
          conteos: { positivos: 4, negativos: 4, abstenciones: 0, total: 8 },
        },
        capacidades: {
          ...estadoActual.capacidades,
          abrir_votacion: { habilitada: false, motivos: ['VOTACION_PENDIENTE'] },
          finalizar_votacion: { habilitada: false, motivos: ['VOTACION_NO_EN_CURSO'] },
          desempatar: { habilitada: true, motivos: [] },
        },
      })
    }

    const fetchOriginal = window.fetch.bind(window)
    window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      const metodo = init?.method?.toUpperCase() ?? 'GET'

      if (url.includes('/api/v1/estado/moderacion')) {
        return new Response(JSON.stringify(estadoActual), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }

      if (url.endsWith('/api/v1/votaciones') && metodo === 'POST') {
        const solicitud = JSON.parse(String(init?.body)) as {
          numero_votacion: number
          tipo: string
          tema: string
          tipo_mayoria: string
          factor?: number
          base: string
        }
        const votacion = {
          id: 'votacion-e2e',
          numero_votacion: solicitud.numero_votacion,
          tipo: solicitud.tipo,
          tema: solicitud.tema,
          tipo_mayoria: solicitud.tipo_mayoria,
          factor: solicitud.factor ?? 0,
          base: solicitud.base,
          estado_recepcion: 'EN_CURSO',
          resultado: null,
          fecha_hora_apertura: '2026-08-26T10:00:00Z',
          fecha_hora_cierre: null,
          fecha_hora_resultado: null,
          motivo_finalizacion_manual: null,
          cantidad_votos_recibidos: 0,
          bancas_voto_emitido: [],
          revelado_individual_desde: '2026-08-26T10:00:04Z',
          votos_individuales_revelados: false,
          votos_individuales: null,
          conteos: null,
          voto_presidencial: null,
        }
        publicar({
          ...estadoActual,
          revision: estadoActual.revision + 1,
          votacion,
          capacidades: {
            ...estadoActual.capacidades,
            abrir_votacion: { habilitada: false, motivos: ['VOTACION_PENDIENTE'] },
            finalizar_votacion: { habilitada: true, motivos: [] },
          },
        })
        return new Response(JSON.stringify(votacion), {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        })
      }

      if (url.endsWith('/finalizacion') && metodo === 'POST' && estadoActual.votacion) {
        // El backend cierra la votación y publica el snapshot; el frontend nunca adopta
        // un resultado propio. Este escenario cierra empatado para poder recorrer también
        // el desempate presidencial dentro del mismo ciclo operativo.
        ventanaPrueba.cerrarComoEmpatada?.()
        return new Response(null, { status: 204 })
      }

      if (url.endsWith('/desempate') && metodo === 'POST' && estadoActual.votacion) {
        publicar({
          ...estadoActual,
          revision: estadoActual.revision + 1,
          votacion: {
            ...estadoActual.votacion,
            resultado: 'APROBADA',
            fecha_hora_resultado: '2026-08-26T10:00:15Z',
            voto_presidencial: { presidencia: 'Dra. Presidencia', sentido: 'POSITIVO' },
          },
          capacidades: {
            ...estadoActual.capacidades,
            abrir_votacion: { habilitada: true, motivos: [] },
            desempatar: { habilitada: false, motivos: ['VOTACION_NO_EMPATADA'] },
          },
        })
        return new Response(null, { status: 204 })
      }

      return fetchOriginal(input, init)
    }
  }, estadoInicial)
}

/**
 * Instala un backend determinista para el recorrido específico de WP-040.
 *
 * Tanto la carga como el descarte publican un snapshot completo por el EventSource
 * simulado. El componente nunca recibe instrucciones para ocultar o crear puntos por
 * su cuenta: la prueba reproduce la misma autoridad backend que existe en producción.
 */
async function configurarOrdenDelDiaMock(page: Page, estadoInicial: Record<string, unknown>) {
  // WP-098: la fotografía de banca ya no es un asset del build; la publica
  // el backend desde la configuración local. Sin backend real, se responde
  // desde la plantilla versionada, que es el mismo archivo de siempre.
  await instalarFotosConcejales(page)

  await page.addInitScript((inicial) => {
    type PuntoOrdenPrueba = {
      nro_votacion: number
      tipo: string
      tema: string
      tipo_mayoria: 'SIMPLE' | 'ESPECIAL'
      factor: number
      base: 'VOTOS_COMPUTABLES' | 'PRESENTES' | 'CUERPO'
    }
    type EstadoOrdenPrueba = Record<string, unknown> & {
      revision: number
      orden_del_dia: PuntoOrdenPrueba[]
    }

    let estadoActual = inicial as EstadoOrdenPrueba
    const fuentes: MockEventSourceOrden[] = []

    function publicar(puntos: PuntoOrdenPrueba[]): void {
      estadoActual = {
        ...estadoActual,
        revision: estadoActual.revision + 1,
        orden_del_dia: puntos,
      }
      const data = JSON.stringify(estadoActual)
      for (const fuente of fuentes) {
        for (const handler of fuente.listeners.estado ?? []) {
          handler({ type: 'estado', data })
        }
      }
    }

    function crearPuntos(cantidad: number): PuntoOrdenPrueba[] {
      return Array.from({ length: cantidad }, (_, indice) => {
        const numero = indice + 1
        if (numero % 3 === 0) {
          return {
            nro_votacion: numero,
            tipo: 'Moción',
            tema: `Tema especial ${numero} con información suficiente para comprobar densidad`,
            tipo_mayoria: 'ESPECIAL',
            factor: 0.66,
            base: 'CUERPO',
          }
        }
        return {
          nro_votacion: numero,
          tipo: 'Proyecto',
          tema: `Tema ordinario ${numero} del Orden del Día`,
          tipo_mayoria: 'SIMPLE',
          factor: 0,
          base: 'VOTOS_COMPUTABLES',
        }
      })
    }

    class MockEventSourceOrden {
      readyState = 1
      listeners: Record<string, ((evento: { type: string; data: string }) => void)[]> = {}
      onopen: ((evento: { type: string }) => void) | null = null
      onerror: ((evento: { type: string }) => void) | null = null
      onmessage: ((evento: { type: string; data: string }) => void) | null = null

      constructor(readonly url: string) {
        fuentes.push(this)
        setTimeout(() => {
          this.onopen?.({ type: 'open' })
          const data = JSON.stringify(estadoActual)
          for (const handler of this.listeners.estado ?? []) handler({ type: 'estado', data })
        }, 5)
      }

      addEventListener(
        tipo: string,
        handler: (evento: { type: string; data: string }) => void,
      ): void {
        this.listeners[tipo] = this.listeners[tipo] ?? []
        this.listeners[tipo]?.push(handler)
      }

      removeEventListener(
        tipo: string,
        handler: (evento: { type: string; data: string }) => void,
      ): void {
        this.listeners[tipo] = (this.listeners[tipo] ?? []).filter(
          (registrado) => registrado !== handler,
        )
      }

      close(): void {
        this.readyState = 2
      }
    }

    // @ts-expect-error EventSource controlado para el recorrido de WP-040.
    window.EventSource = MockEventSourceOrden

    const ventanaPrueba = window as Window & { publicarOrdenDelDiaLargo?: () => void }
    ventanaPrueba.publicarOrdenDelDiaLargo = () => publicar(crearPuntos(24))

    const fetchOriginal = window.fetch.bind(window)
    window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      const metodo = init?.method?.toUpperCase() ?? 'GET'

      if (url.includes('/api/v1/estado/moderacion')) {
        return new Response(JSON.stringify(estadoActual), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }

      if (url.endsWith('/api/v1/orden-del-dia') && metodo === 'POST') {
        const puntos = crearPuntos(2)
        publicar(puntos)
        return new Response(JSON.stringify({ puntos }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }

      if (url.endsWith('/api/v1/orden-del-dia') && metodo === 'DELETE') {
        publicar([])
        return new Response(null, { status: 204 })
      }

      return fetchOriginal(input, init)
    }
  }, estadoInicial)
}

/**
 * Simula el ciclo coordinado de WP-024 conservando una única fuente de estado.
 * Cada comando publica luego un snapshot completo: la página no conoce ni
 * calcula por su cuenta el avance de palabra, los eventos o el remapeo físico.
 */
async function configurarCicloPalabraRemapeoMock(
  page: Page,
  estadoInicial: Record<string, unknown>,
) {
  // WP-098: la fotografía de banca ya no es un asset del build; la publica
  // el backend desde la configuración local. Sin backend real, se responde
  // desde la plantilla versionada, que es el mismo archivo de siempre.
  await instalarFotosConcejales(page)

  await page.addInitScript((inicial) => {
    type CapacidadPrueba = { habilitada: boolean; motivos: string[] }
    type PersonaPalabra = {
      dni: string
      nombre: string
      apellido: string
      banca: number
    }
    type RemapeoPrueba = {
      remapeo_id: string
      dispositivo: string
      estado: string
      fingerprint_anterior: string | null
      candidato: string | null
      diagnostico: string | null
    }
    type EstadoPrueba = Record<string, unknown> & {
      revision: number
      palabra: { orador: PersonaPalabra | null; cola: PersonaPalabra[] }
      eventos_recientes: Record<string, unknown>[]
      remapeo: RemapeoPrueba | null
      capacidades: Record<string, CapacidadPrueba>
    }

    let estadoActual = inicial as EstadoPrueba
    const fuentes: MockEventSourceWp024[] = []
    const conteos = { quitar: 0, otorgar: 0, iniciar: 0, confirmar: 0 }
    let ultimaConfirmacion: { remapeoId: string; persistencia: string } | null = null

    function publicar(cambios: Partial<EstadoPrueba>): void {
      estadoActual = {
        ...estadoActual,
        ...cambios,
        revision: estadoActual.revision + 1,
      }
      const data = JSON.stringify(estadoActual)
      for (const fuente of fuentes) {
        for (const handler of fuente.listeners.estado ?? []) {
          handler({ type: 'estado', data })
        }
      }
    }

    class MockEventSourceWp024 {
      readyState = 1
      listeners: Record<string, ((evento: { type: string; data: string }) => void)[]> = {}
      onopen: ((evento: { type: string }) => void) | null = null
      onerror: ((evento: { type: string }) => void) | null = null
      onmessage: ((evento: { type: string; data: string }) => void) | null = null

      constructor(readonly url: string) {
        fuentes.push(this)
        setTimeout(() => {
          this.onopen?.({ type: 'open' })
          const data = JSON.stringify(estadoActual)
          for (const handler of this.listeners.estado ?? []) handler({ type: 'estado', data })
        }, 5)
      }

      addEventListener(
        tipo: string,
        handler: (evento: { type: string; data: string }) => void,
      ): void {
        this.listeners[tipo] = this.listeners[tipo] ?? []
        this.listeners[tipo]?.push(handler)
      }

      removeEventListener(
        tipo: string,
        handler: (evento: { type: string; data: string }) => void,
      ): void {
        this.listeners[tipo] = (this.listeners[tipo] ?? []).filter(
          (registrado) => registrado !== handler,
        )
      }

      close(): void {
        this.readyState = 2
      }
    }

    // @ts-expect-error EventSource determinista para el recorrido de WP-024.
    window.EventSource = MockEventSourceWp024

    const ventanaPrueba = window as Window & {
      capturarCandidatoRemapeo?: () => void
      obtenerControlWp024?: () => {
        conteos: typeof conteos
        ultimaConfirmacion: typeof ultimaConfirmacion
      }
    }
    ventanaPrueba.capturarCandidatoRemapeo = () => {
      if (!estadoActual.remapeo) return
      publicar({
        remapeo: {
          ...estadoActual.remapeo,
          estado: 'CANDIDATO',
          candidato: 'lin|vendor=9001|product=9001|phys=usb-9|name=Reemplazo',
          diagnostico: 'Teclado USB de reemplazo',
        },
        capacidades: {
          ...estadoActual.capacidades,
          confirmar_remapeo: { habilitada: true, motivos: [] },
        },
      })
    }
    ventanaPrueba.obtenerControlWp024 = () => ({ conteos, ultimaConfirmacion })

    const fetchOriginal = window.fetch.bind(window)
    window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      const metodo = init?.method?.toUpperCase() ?? 'GET'

      if (url.includes('/api/v1/estado/moderacion')) {
        return new Response(JSON.stringify(estadoActual), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }

      if (url.endsWith('/api/v1/palabra') && metodo === 'DELETE') {
        conteos.quitar += 1
        await new Promise((resolver) => setTimeout(resolver, 30))
        publicar({ palabra: { ...estadoActual.palabra, orador: null } })
        return new Response(null, { status: 204 })
      }

      if (url.endsWith('/api/v1/palabra') && metodo === 'POST') {
        conteos.otorgar += 1
        await new Promise((resolver) => setTimeout(resolver, 30))
        const [siguiente, ...restantes] = estadoActual.palabra.cola
        publicar({
          palabra: {
            orador: siguiente ?? null,
            cola: restantes,
          },
        })
        return new Response(null, { status: 204 })
      }

      if (url.endsWith('/api/v1/remapeos') && metodo === 'POST') {
        conteos.iniciar += 1
        const solicitud = JSON.parse(String(init?.body)) as { dispositivo: string }
        await new Promise((resolver) => setTimeout(resolver, 30))
        const remapeo: RemapeoPrueba = {
          remapeo_id: 'remapeo-e2e-wp024',
          dispositivo: solicitud.dispositivo,
          estado: 'CAPTURANDO',
          fingerprint_anterior: 'lin|vendor=1001|product=1001|phys=usb-1|name=Anterior',
          candidato: null,
          diagnostico: null,
        }
        publicar({
          remapeo,
          capacidades: {
            ...estadoActual.capacidades,
            iniciar_remapeo: { habilitada: false, motivos: ['REMAPEO_YA_ACTIVO'] },
            confirmar_remapeo: { habilitada: false, motivos: ['REMAPEO_SIN_CANDIDATO'] },
            cancelar_remapeo: { habilitada: true, motivos: [] },
          },
        })
        return new Response(JSON.stringify(remapeo), {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        })
      }

      if (url.endsWith('/confirmacion') && metodo === 'POST' && estadoActual.remapeo) {
        conteos.confirmar += 1
        const solicitud = JSON.parse(String(init?.body)) as { persistencia: string }
        ultimaConfirmacion = {
          remapeoId: estadoActual.remapeo.remapeo_id,
          persistencia: solicitud.persistencia,
        }
        publicar({
          remapeo: { ...estadoActual.remapeo, estado: 'CONFIRMANDO' },
          capacidades: {
            ...estadoActual.capacidades,
            confirmar_remapeo: { habilitada: false, motivos: ['REMAPEO_NO_COINCIDE'] },
            cancelar_remapeo: { habilitada: false, motivos: ['REMAPEO_NO_COINCIDE'] },
          },
        })
        await new Promise((resolver) => setTimeout(resolver, 30))
        publicar({
          remapeo: null,
          capacidades: {
            ...estadoActual.capacidades,
            iniciar_remapeo: { habilitada: true, motivos: [] },
            confirmar_remapeo: { habilitada: false, motivos: ['REMAPEO_NO_COINCIDE'] },
            cancelar_remapeo: { habilitada: false, motivos: ['REMAPEO_NO_COINCIDE'] },
          },
        })
        return new Response(null, { status: 204 })
      }

      return fetchOriginal(input, init)
    }
  }, estadoInicial)
}

function obtenerPaneles(page: Page) {
  return {
    sesion: page.locator('[data-testid="panel-sesion-votacion"]'),
    ordenDia: page.locator('[data-testid="panel-orden-del-dia"]'),
    recinto: page.locator('[data-testid="panel-recinto-palabra"]'),
    eventos: page.locator('[data-testid="panel-eventos"]'),
  }
}

/**
 * Valida de forma exhaustiva el contrato geométrico 2×2 del shell de Moderación (N1):
 * - Cabecera visible
 * - Cuatro cuadrantes con sus títulos institucionales correspondientes
 * - Bounding boxes no nulos
 * - Fila superior: Q1 a la izquierda de Q2 con igual coordenada Y (aprox)
 * - Fila inferior: Q3 a la izquierda de Q4 con igual coordenada Y (aprox)
 * - Columnas: Q1 alineado verticalmente con Q3; Q2 alineado con Q4
 * - Fila inferior debajo de la fila superior (sin solapamiento vertical)
 * - Ausencia de solapamiento horizontal entre paneles
 * - Ausencia de scroll global indebido en la ventana
 */
async function verificarGeometriaShellCompleto(
  page: Page,
  viewport: { width: number; height: number },
) {
  // 1. Cabecera compacta permanente visible, con `Moderación` como única identidad (WP-036)
  const cabecera = page.locator('[data-testid="cabecera-moderacion"]')
  await expect(cabecera).toBeVisible()
  await expect(cabecera).toContainText('Moderación')
  await expect(cabecera).not.toContainText('BOTONERA2')
  await expect(cabecera).not.toContainText('Botonera2')
  await expect(cabecera).not.toContainText('Revisión')

  // 2. Los cuatro cuadrantes simultáneamente visibles con sus cuatro títulos institucionales
  const paneles = obtenerPaneles(page)
  await expect(paneles.sesion).toBeVisible()
  await expect(paneles.ordenDia).toBeVisible()
  await expect(paneles.recinto).toBeVisible()
  await expect(paneles.eventos).toBeVisible()

  await expect(paneles.sesion).toContainText('Sesión y votación')
  await expect(paneles.ordenDia).toContainText('Orden del Día')
  await expect(paneles.recinto).toContainText('Recinto y palabra')
  await expect(paneles.eventos).toContainText('Eventos')

  // 3. Medición geométrica precisa
  const boxQ1 = await paneles.sesion.boundingBox()
  const boxQ2 = await paneles.ordenDia.boundingBox()
  const boxQ3 = await paneles.recinto.boundingBox()
  const boxQ4 = await paneles.eventos.boundingBox()

  expect(boxQ1).not.toBeNull()
  expect(boxQ2).not.toBeNull()
  expect(boxQ3).not.toBeNull()
  expect(boxQ4).not.toBeNull()

  if (boxQ1 && boxQ2 && boxQ3 && boxQ4) {
    // Fila superior: Q1 a la izquierda de Q2 y aproximadamente a la misma altura Y
    expect(Math.abs(boxQ1.y - boxQ2.y)).toBeLessThanOrEqual(6)
    expect(boxQ1.x + boxQ1.width).toBeLessThanOrEqual(boxQ2.x + 2)

    // Fila inferior: Q3 a la izquierda de Q4 y aproximadamente a la misma altura Y
    expect(Math.abs(boxQ3.y - boxQ4.y)).toBeLessThanOrEqual(6)
    expect(boxQ3.x + boxQ3.width).toBeLessThanOrEqual(boxQ4.x + 2)

    // Columnas: Q1 alineado aprox con Q3 en coordenada X y ancho
    expect(Math.abs(boxQ1.x - boxQ3.x)).toBeLessThanOrEqual(6)
    expect(Math.abs(boxQ1.width - boxQ3.width)).toBeLessThanOrEqual(6)

    // Columnas: Q2 alineado aprox con Q4 en coordenada X y ancho
    expect(Math.abs(boxQ2.x - boxQ4.x)).toBeLessThanOrEqual(6)
    expect(Math.abs(boxQ2.width - boxQ4.width)).toBeLessThanOrEqual(6)

    // Fila inferior situada debajo de la fila superior (sin solapamiento vertical)
    expect(boxQ1.y + boxQ1.height).toBeLessThanOrEqual(boxQ3.y + 2)
    expect(boxQ2.y + boxQ2.height).toBeLessThanOrEqual(boxQ4.y + 2)
  }

  // 4. Ausencia de scroll de página: la grilla 2×2 completa entra en el viewport (CA 11 y 12)
  const scrollW = await page.evaluate(() => document.documentElement.scrollWidth)
  const scrollH = await page.evaluate(() => document.documentElement.scrollHeight)
  expect(scrollW).toBeLessThanOrEqual(viewport.width + 2)
  expect(scrollH).toBeLessThanOrEqual(viewport.height + 2)

  // El documento tampoco debe poder desplazarse: ningún elemento del shell excede el viewport.
  const desplazamiento = await page.evaluate(() => {
    window.scrollTo(0, 10_000)
    return { x: window.scrollX, y: window.scrollY }
  })
  expect(desplazamiento.y).toBe(0)
  expect(desplazamiento.x).toBe(0)
}

/**
 * Mide la densidad común fijada por WP-047 y comprueba que la cabecera no envuelva.
 *
 * La baseline previa usaba 12 px de padding/gap en desktop y 6/12 px en los
 * encabezados/cuerpos comunes. Producción histórica usa 10 px. El nuevo shell usa
 * 8 px de padding/gap, encabezados de 4/10 px y cuerpos de 8 px: menos chrome que
 * ambas referencias, sin tocar el tamaño de los controles internos de cada cuadrante.
 */
async function verificarDensidadComunWp047(
  page: Page,
  viewport: { width: number; height: number },
) {
  const medicion = await page.evaluate(() => {
    const cabecera = document.querySelector<HTMLElement>('[data-testid="cabecera-moderacion"]')!
    const grilla = document.querySelector<HTMLElement>('[data-testid="grilla-paneles"]')!
    const principal = grilla.parentElement as HTMLElement
    const paneles = Array.from(
      document.querySelectorAll<HTMLElement>('[data-testid^="panel-"]'),
    ).filter((panel) => panel.querySelector('[data-testid="cuerpo-panel"]'))
    const encabezadoPanel = paneles[0]?.querySelector<HTMLElement>(':scope > header')
    const cuerpos = paneles.map((panel) =>
      panel.querySelector<HTMLElement>('[data-testid="cuerpo-panel"]')!,
    )
    const cajaCabecera = cabecera.getBoundingClientRect()
    const cajaGrilla = grilla.getBoundingClientRect()
    const estiloCabecera = getComputedStyle(cabecera)
    const estiloGrilla = getComputedStyle(grilla)
    const estiloPrincipal = getComputedStyle(principal)
    const estiloEncabezado = getComputedStyle(encabezadoPanel!)

    return {
      cabecera: {
        altura: cajaCabecera.height,
        flexWrap: estiloCabecera.flexWrap,
        altoVisible: cabecera.clientHeight,
        altoContenido: cabecera.scrollHeight,
        anchoVisible: cabecera.clientWidth,
        anchoContenido: cabecera.scrollWidth,
      },
      grilla: {
        x: cajaGrilla.x,
        y: cajaGrilla.y,
        ancho: cajaGrilla.width,
        alto: cajaGrilla.height,
        gapFila: Number.parseFloat(estiloGrilla.rowGap),
        gapColumna: Number.parseFloat(estiloGrilla.columnGap),
      },
      principal: {
        paddingSuperior: Number.parseFloat(estiloPrincipal.paddingTop),
        paddingDerecho: Number.parseFloat(estiloPrincipal.paddingRight),
        paddingInferior: Number.parseFloat(estiloPrincipal.paddingBottom),
        paddingIzquierdo: Number.parseFloat(estiloPrincipal.paddingLeft),
      },
      encabezadoPanel: {
        paddingVertical: Number.parseFloat(estiloEncabezado.paddingTop),
        paddingHorizontal: Number.parseFloat(estiloEncabezado.paddingLeft),
      },
      cuerpos: cuerpos.map((cuerpo) => {
        const estilo = getComputedStyle(cuerpo)
        return {
          paddingSuperior: Number.parseFloat(estilo.paddingTop),
          paddingDerecho: Number.parseFloat(estilo.paddingRight),
          paddingInferior: Number.parseFloat(estilo.paddingBottom),
          paddingIzquierdo: Number.parseFloat(estilo.paddingLeft),
        }
      }),
    }
  })

  expect(medicion.principal).toEqual({
    paddingSuperior: 8,
    paddingDerecho: 8,
    paddingInferior: 8,
    paddingIzquierdo: 8,
  })
  expect(medicion.grilla.gapFila).toBe(8)
  expect(medicion.grilla.gapColumna).toBe(8)
  expect(medicion.encabezadoPanel).toEqual({ paddingVertical: 4, paddingHorizontal: 10 })
  expect(medicion.cuerpos).toHaveLength(4)
  for (const cuerpo of medicion.cuerpos) {
    expect(cuerpo).toEqual({
      paddingSuperior: 8,
      paddingDerecho: 8,
      paddingInferior: 8,
      paddingIzquierdo: 8,
    })
  }

  expect(medicion.cabecera.flexWrap).toBe('nowrap')
  expect(medicion.cabecera.altoContenido).toBeLessThanOrEqual(medicion.cabecera.altoVisible + 1)
  expect(medicion.cabecera.anchoContenido).toBeLessThanOrEqual(medicion.cabecera.anchoVisible + 1)
  expect(medicion.cabecera.altura).toBeLessThanOrEqual(32)

  // Las medidas de la grilla quedan registradas junto con los bounding boxes de
  // los cuatro paneles que verifica `verificarGeometriaShellCompleto`.
  expect(medicion.grilla.x).toBe(8)
  expect(medicion.grilla.ancho).toBe(viewport.width - 16)
  expect(medicion.grilla.y + medicion.grilla.alto).toBeLessThanOrEqual(viewport.height - 8 + 1)
}

/**
 * Verifica la frontera específica de WP-037 con medidas reales del DOM.
 *
 * No alcanza con buscar una clase Tailwind: el cuerpo debe tener overflow no
 * desplazable y, al mismo tiempo, todo su contenido debe entrar sin recorte. La
 * comparación entre scrollHeight y clientHeight detecta justamente un `hidden`
 * usado para esconder controles que en realidad quedaron fuera del cuadrante.
 */
async function verificarQ1SinScroll(page: Page): Promise<void> {
  const cuerpo = page.locator('[data-testid="panel-sesion-votacion"] [data-testid="cuerpo-panel"]')
  await expect(cuerpo).toBeVisible()
  const medicion = await cuerpo.evaluate((elemento) => {
    const estilo = getComputedStyle(elemento)
    return {
      overflowY: estilo.overflowY,
      altoVisible: elemento.clientHeight,
      altoContenido: elemento.scrollHeight,
      desplazamiento: elemento.scrollTop,
    }
  })

  expect(['auto', 'scroll']).not.toContain(medicion.overflowY)
  expect(medicion.altoContenido).toBeLessThanOrEqual(medicion.altoVisible + 1)
  expect(medicion.desplazamiento).toBe(0)
}

/**
 * Comprueba que el estado vacío de Q2 no crea una zona desplazable innecesaria.
 * Se mide el DOM real porque declarar `overflow-hidden` no alcanza si el contenido
 * quedó recortado: `scrollHeight` también debe entrar dentro del alto disponible.
 */
async function verificarOrdenVacioSinScroll(page: Page): Promise<void> {
  const cuerpo = page.locator('[data-testid="panel-orden-del-dia"] [data-testid="cuerpo-panel"]')
  await expect(cuerpo).toBeVisible()
  const medicion = await cuerpo.evaluate((elemento) => {
    const estilo = getComputedStyle(elemento)
    return {
      overflowY: estilo.overflowY,
      altoVisible: elemento.clientHeight,
      altoContenido: elemento.scrollHeight,
      desplazamiento: elemento.scrollTop,
    }
  })

  expect(['auto', 'scroll']).not.toContain(medicion.overflowY)
  expect(medicion.altoContenido).toBeLessThanOrEqual(medicion.altoVisible + 1)
  expect(medicion.desplazamiento).toBe(0)
}

function crearCapacidadesSesionCompacta() {
  return {
    preparar_sala: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
    actualizar_preparacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
    cancelar_preparacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
    abrir_sesion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
    actualizar_sesion: { habilitada: true, motivos: [] },
    cerrar_sesion: { habilitada: true, motivos: [] },
    cargar_orden_del_dia: { habilitada: true, motivos: [] },
    descartar_orden_del_dia: { habilitada: true, motivos: [] },
    abrir_votacion: { habilitada: true, motivos: [] },
    finalizar_votacion: { habilitada: false, motivos: ['VOTACION_NO_EN_CURSO'] },
    desempatar: { habilitada: false, motivos: ['VOTACION_NO_EMPATADA'] },
    otorgar_palabra: { habilitada: true, motivos: [] },
    quitar_palabra: { habilitada: true, motivos: [] },
  }
}

function crearEstadoSesionCompacta(parcial: Record<string, unknown> = {}) {
  return crearEstadoFixture({
    estado_global: 'SESION_ABIERTA',
    sesion: {
      fecha_hora_inicio_preparacion: '2026-08-29T09:30:00Z',
      fecha_hora_apertura: '2026-08-29T09:45:00Z',
      numero_sesion: 42,
      presidencia: 'Dra. Presidencia',
      secretaria_legislativa: 'Lic. Secretaría',
    },
    configuracion: {
      quorum: 7,
      filas_bancas: [3, 4, 5],
      tipos_votacion: ['Proyecto', 'Moción'],
      duracion_test_segundos: 3,
      revelado_votos_moderacion_segundos: 4,
      cuenta_regresiva_recinto_segundos: 3,
      resultado_publico_recinto_segundos: 6,
    },
    quorum: { cantidad_presentes: 8, requerido: 7, alcanzado: true },
    palabra: { orador: null, cola: [] },
    orden_del_dia: [],
    eventos_recientes: [],
    capacidades: crearCapacidadesSesionCompacta(),
    ...parcial,
  })
}

function crearVotacionCompacta(parcial: Record<string, unknown> = {}) {
  return {
    id: 'votacion-wp037',
    numero_votacion: 12,
    tipo: 'Proyecto',
    tema: 'Tratamiento de presupuesto anual',
    tipo_mayoria: 'SIMPLE',
    factor: 0,
    base: 'VOTOS_COMPUTABLES',
    estado_recepcion: 'EN_CURSO',
    resultado: null,
    fecha_hora_apertura: '2026-08-29T10:00:00Z',
    fecha_hora_cierre: null,
    fecha_hora_resultado: null,
    motivo_finalizacion_manual: null,
    cantidad_votos_recibidos: 8,
    bancas_voto_emitido: [],
    revelado_individual_desde: '2026-08-29T10:00:04Z',
    votos_individuales_revelados: true,
    votos_individuales: [
      {
        dni: '30000001',
        nombre: 'No debe',
        apellido: 'renderizarse',
        banca: 1,
        valor: 'POSITIVO',
      },
    ],
    conteos: { positivos: 4, negativos: 3, abstenciones: 1, total: 8 },
    voto_presidencial: null,
    ...parcial,
  }
}

test.describe('UI de Moderación - Estados Institucionales y Contrato de Shell (WP-022)', () => {
  // ===========================================================================
  // 1. ESTADO SIN_PREPARAR (1920×1080 y 1366×768)
  // ===========================================================================
  test('Estado SIN_PREPARAR: verifica contrato 2×2, recinto sin preparar y ausencia total de indicadores de quórum (1920×1080 y 1366×768)', async ({
    page,
  }) => {
    const estado = crearEstadoFixture({
      estado_global: 'SIN_PREPARAR',
      quorum: null,
    })
    await configurarRutasMock(page, estado)

    for (const viewport of [
      { width: 1920, height: 1080 },
      { width: 1366, height: 768 },
    ]) {
      await page.setViewportSize(viewport)
      await page.goto('/moderacion/')
      await page
        .locator('[data-testid="cabecera-moderacion"]')
        .waitFor({ state: 'visible', timeout: 30000 })

      // Verificamos el contrato geométrico 2×2 completo del shell (N1)
      await verificarGeometriaShellCompleto(page, viewport)

      // WP-047 retira el estado global redundante: Q1 sigue siendo su sede operativa.
      await expect(page.locator('[data-testid="estado-global"]')).toHaveCount(0)

      // Cuadrante 1: Sesión y votación
      const vistaSinPreparar = page.locator('[data-testid="vista-sin-preparar"]')
      await expect(vistaSinPreparar).toBeVisible()
      await expect(vistaSinPreparar).toContainText('Recinto sin preparar')
      await expect(page.locator('[data-testid="btn-preparar-sala"]')).toBeVisible()
      await expect(page.locator('[data-testid="vista-preparando"]')).toHaveCount(0)
      await expect(page.locator('[data-testid="vista-sesion-abierta"]')).toHaveCount(0)

      // WP-036: sin contexto de quórum no se muestra ningún indicador, tampoco en cabecera
      await expect(page.locator('[data-testid="cabecera-quorum"]')).toHaveCount(0)
      await expect(page.locator('[data-testid="indicador-quorum"]')).toHaveCount(0)
      await expect(page.locator('[data-testid="quorum-resumen-sesion"]')).toHaveCount(0)
      await expect(page.locator('text=0 de 0 presentes')).toHaveCount(0)

      // Sin sesión abierta tampoco hay tiempo transcurrido, pero el reloj local sí está presente
      await expect(page.locator('[data-testid="cabecera-tiempo-sesion"]')).toHaveCount(0)
      // WP-054: el valor viaja precedido por su rótulo explícito `Fecha`.
      await expect(page.locator('[data-testid="cabecera-fecha-hora"]')).toHaveText(
        /^Fecha\s+\d{2}\/\d{2}\/\d{4} \d{2}:\d{2}:\d{2}$/,
      )
    }
  })

  // ===========================================================================
  // 2. ESTADO PREPARANDO (1920×1080 y 1366×768)
  // ===========================================================================
  test('Estado PREPARANDO: verifica contrato 2×2, inputs de preparación, quórum y autoridades en cabecera y 12 bancas (1920×1080 y 1366×768)', async ({
    page,
  }) => {
    const estado = crearEstadoFixture({
      estado_global: 'PREPARANDO',
      preparacion: {
        fecha_hora_inicio: '2026-08-25T10:00:00Z',
        numero_sesion: 42,
        presidencia: 'Dr. René Favaloro',
        secretaria_legislativa: 'Lic. Alicia Moreau',
      },
      quorum: {
        cantidad_presentes: 5,
        requerido: 7,
        alcanzado: false,
      },
      capacidades: {
        preparar_sala: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
        actualizar_preparacion: { habilitada: true, motivos: [] },
        cancelar_preparacion: { habilitada: true, motivos: [] },
        abrir_sesion: { habilitada: false, motivos: ['QUORUM_INSUFICIENTE'] },
        actualizar_sesion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
        cerrar_sesion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
        iniciar_votacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
        cancelar_votacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
        cerrar_votacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
        desempatar: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
        solicitar_palabra: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
        cancelar_solicitud_palabra: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
        otorgar_palabra: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
        quitar_palabra: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
        subir_orden_dia: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
        seleccionar_expediente: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
        cerrar_expediente: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
        registrar_evento_manual: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      },
    })
    await configurarRutasMock(page, estado)

    for (const viewport of [
      { width: 1920, height: 1080 },
      { width: 1366, height: 768 },
    ]) {
      await page.setViewportSize(viewport)
      await page.goto('/moderacion/')
      await page
        .locator('[data-testid="cabecera-moderacion"]')
        .waitFor({ state: 'visible', timeout: 30000 })

      // Verificamos el contrato geométrico 2×2 completo del shell (N1)
      await verificarGeometriaShellCompleto(page, viewport)

      // Cuadrante 1: Controles de preparación
      const vistaPreparando = page.locator('[data-testid="vista-preparando"]')
      await expect(vistaPreparando).toBeVisible()
      await expect(page.locator('[data-testid="input-numero-sesion"]')).toHaveValue('42')
      await expect(page.locator('[data-testid="input-presidencia"]')).toHaveValue(
        'Dr. René Favaloro',
      )
      await expect(page.locator('[data-testid="input-secretaria"]')).toHaveValue(
        'Lic. Alicia Moreau',
      )
      await expect(page.locator('[data-testid="btn-guardar-preparacion"]')).toBeVisible()
      await expect(page.locator('[data-testid="btn-abrir-sesion"]')).toBeDisabled()
      await expect(page.locator('[data-testid="btn-cancelar-preparacion"]')).toBeVisible()

      // Motivo visible de quórum insuficiente para abrir sesión
      await expect(page.locator('[data-testid="motivos-abrir-sesion"]')).toContainText(
        'Quórum insuficiente',
      )

      // WP-047: el número provisorio ya cargado antecede al quórum en la cabecera.
      await expect(page.locator('[data-testid="cabecera-numero-sesion"]')).toHaveText(
        'Sesión Nº 42',
      )

      // WP-036: el quórum es global y se muestra únicamente en la cabecera
      const quorumCabecera = page.locator('[data-testid="cabecera-quorum"]')
      await expect(quorumCabecera).toBeVisible()
      await expect(quorumCabecera).toContainText('Sin quórum 5/12 · mín 7')
      await expect(page.locator('[data-testid="indicador-quorum"]')).toHaveCount(0)
      await expect(page.locator('[data-testid="quorum-faltantes"]')).toHaveCount(0)

      // WP-036: las autoridades ya cargadas se ven en cabecera desde PREPARANDO
      await expect(page.locator('[data-testid="cabecera-presidencia"]')).toContainText(
        'Dr. René Favaloro',
      )
      await expect(page.locator('[data-testid="cabecera-secretaria"]')).toContainText(
        'Lic. Alicia Moreau',
      )

      // 12 Bancas renderizadas
      const bancas = page.locator('[data-testid="banca-concejal"]')
      await expect(bancas).toHaveCount(12)

      // Banca 1 con test activo: WP-045 lo pinta como estado principal sin etiqueta.
      await expect(page.locator('[data-estado-banca="TEST"]')).toHaveCount(1)
    }
  })

  test('WP-038: Q3 usa geometría física [5,7], preserva huecos y ausencia en ambas resoluciones', async ({
    page,
  }) => {
    const concejales = crearConcejalesFixture(12)
      .map((concejal) => ({ ...concejal, presente: concejal.banca !== 2 }))
      .filter((concejal) => concejal.banca !== 4)
      .reverse()
    const estado = crearEstadoFixture({
      estado_global: 'PREPARANDO',
      preparacion: {
        fecha_hora_inicio: '2026-08-25T10:00:00Z',
        numero_sesion: 38,
        presidencia: 'Presidencia de prueba',
        secretaria_legislativa: 'Secretaría de prueba',
      },
      configuracion: { filas_bancas: [5, 7] },
      concejales,
      quorum: { cantidad_presentes: 10, requerido: 7, alcanzado: true },
    })
    await configurarRutasMock(page, estado)

    for (const viewport of [
      { width: 1366, height: 768 },
      { width: 1920, height: 1080 },
    ]) {
      await page.setViewportSize(viewport)
      await page.goto('/moderacion/')
      await expect(page.locator('[data-testid="grilla-recinto"]')).toBeAttached()

      const filaSuperior = page.locator('[data-fila-fisica="2"]')
      const filaInferior = page.locator('[data-fila-fisica="1"]')
      const bancaUno = filaInferior.locator('[data-banca="1"]')
      const bancaSeis = filaSuperior.locator('[data-banca="6"]')
      const cajaUno = await bancaUno.boundingBox()
      const cajaSeis = await bancaSeis.boundingBox()
      expect(cajaUno).not.toBeNull()
      expect(cajaSeis).not.toBeNull()
      expect(cajaUno!.y).toBeGreaterThan(cajaSeis!.y)

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

      await expect(filaInferior.locator('[data-banca="4"]')).toContainText('sin datos')
      // WP-045: la identidad ya no se repite como texto fuera del bitmap.
      await expect(filaInferior.locator('[data-banca="5"]')).toHaveAttribute(
        'aria-label',
        /Concejal05/,
      )
      // El fixture activa el test en la banca 1: WP-045 lo pinta como estado
      // principal, en azul y sin ninguna etiqueta textual.
      await expect(bancaUno).toHaveAttribute('data-estado-banca', 'TEST')
      await expect(bancaUno.locator('[data-testid="etiqueta-banca"]')).toHaveCount(0)
      await expect(bancaUno).not.toContainText('Concejal01')
      await expect(bancaUno).not.toContainText('Banca 1')
      await expect(page.locator('[data-banca="2"]')).toHaveAttribute('data-estado-banca', 'AUSENTE')
      await expect(page.locator('[data-banca="2"] [data-testid="etiqueta-banca"]')).toHaveText(
        'Ausente',
      )
      const ausencia = await page.locator('[data-banca="2"]').evaluate((banca) => ({
        filtroFoto: getComputedStyle(
          banca.querySelector('[data-testid="imagen-concejal"]') as HTMLElement,
        ).filter,
      }))
      expect(ausencia.filtroFoto).not.toBe('none')

      // WP-039: palabra comparte horizontalmente Q3 y el remapeo inactivo ocupa
      // solamente una acción compacta, sin obligar a desplazar el cuadrante.
      await expect(page.locator('[data-testid="gestion-palabra"]')).toBeVisible()
      await expect(page.locator('[data-testid="btn-desplegar-remapeo"]')).toBeVisible()
      await expect(page.locator('[data-testid="gestion-remapeo"]')).toHaveCount(0)
      await expect(bancaUno).toBeVisible()
      await verificarGeometriaShellCompleto(page, viewport)
    }
  })

  // ===========================================================================
  // 3. ESTADO SESION_ABIERTA Y DIÁLOGO DE ADVERTENCIA DE CIERRE (1920×1080 y 1366×768)
  // ===========================================================================
  test('Estado SESION_ABIERTA: verifica contrato 2×2, número inmutable, datos globales en cabecera y diálogo modal accesible (1920×1080 y 1366×768)', async ({
    page,
  }) => {
    const estado = crearEstadoFixture({
      estado_global: 'SESION_ABIERTA',
      sesion: {
        fecha_hora_inicio_preparacion: '2026-08-25T10:00:00Z',
        fecha_hora_apertura: '2026-08-25T10:30:00Z',
        numero_sesion: 8,
        presidencia: 'Dra. María Elena Walsh',
        secretaria_legislativa: 'Lic. Juan Gómez',
      },
      quorum: {
        cantidad_presentes: 9,
        requerido: 7,
        alcanzado: true,
      },
      palabra: {
        orador: { dni: '30000001', nombre: 'Carlos', apellido: 'Pérez', banca: 2 },
        cola: [{ dni: '30000003', nombre: 'Diana', apellido: 'López', banca: 4 }],
      },
      capacidades: {
        preparar_sala: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
        actualizar_preparacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
        cancelar_preparacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
        abrir_sesion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
        actualizar_sesion: { habilitada: true, motivos: [] },
        cerrar_sesion: { habilitada: true, motivos: [] },
        iniciar_votacion: { habilitada: true, motivos: [] },
        cancelar_votacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
        cerrar_votacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
        desempatar: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
        solicitar_palabra: { habilitada: true, motivos: [] },
        cancelar_solicitud_palabra: { habilitada: true, motivos: [] },
        otorgar_palabra: { habilitada: true, motivos: [] },
        quitar_palabra: { habilitada: true, motivos: [] },
        subir_orden_dia: { habilitada: true, motivos: [] },
        seleccionar_expediente: { habilitada: true, motivos: [] },
        cerrar_expediente: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
        registrar_evento_manual: { habilitada: true, motivos: [] },
      },
    })
    await configurarRutasMock(page, estado)

    for (const viewport of [
      { width: 1920, height: 1080 },
      { width: 1366, height: 768 },
    ]) {
      await page.setViewportSize(viewport)
      await page.goto('/moderacion/')
      await page
        .locator('[data-testid="cabecera-moderacion"]')
        .waitFor({ state: 'visible', timeout: 30000 })

      // Verificamos el contrato geométrico 2×2 completo del shell (N1)
      await verificarGeometriaShellCompleto(page, viewport)

      // Cuadrante 1: tras WP-036 no repite el quórum global y, tras WP-048, tampoco el
      // número de sesión, que ya es un dato único de la cabecera del shell.
      await expect(page.locator('[data-testid="vista-sesion-abierta"]')).toBeVisible()
      await expect(page.locator('[data-testid="numero-sesion-inmutable"]')).toHaveCount(0)
      await expect(page.locator('[data-testid="franja-sesion-abierta"]')).toHaveCount(0)
      await expect(page.locator('[data-testid="panel-sesion-votacion"]')).not.toContainText(
        'Sesión Nº 8',
      )
      await expect(page.locator('[data-testid="quorum-resumen-sesion"]')).toHaveCount(0)
      await expect(page.locator('[data-testid="badge-quorum-resumen-sesion"]')).toHaveCount(0)
      await expect(page.locator('[data-testid="indicador-quorum"]')).toHaveCount(0)

      // Cabecera: única sede del quórum y de las autoridades vigentes
      await expect(page.locator('[data-testid="cabecera-numero-sesion"]')).toHaveText('Sesión Nº 8')
      await expect(page.locator('[data-testid="estado-global"]')).toHaveCount(0)
      await expect(page.locator('[data-testid="cabecera-quorum"]')).toContainText(
        'Quórum 9/12 · mín 7',
      )
      await expect(page.locator('[data-testid="cabecera-presidencia"]')).toContainText(
        'Dra. María Elena Walsh',
      )
      await expect(page.locator('[data-testid="cabecera-secretaria"]')).toContainText(
        'Lic. Juan Gómez',
      )

      // Cabecera: reloj local y tiempo transcurrido desde la apertura formal de la
      // sesión, ambos con el rótulo explícito que introdujo WP-054.
      await expect(page.locator('[data-testid="cabecera-fecha-hora"]')).toHaveText(
        /^Fecha\s+\d{2}\/\d{2}\/\d{4} \d{2}:\d{2}:\d{2}$/,
      )
      await expect(page.locator('[data-testid="cabecera-tiempo-sesion"]')).toHaveText(
        /Tiempo de sesión\s+\d{2,}:\d{2}:\d{2}/,
      )

      // WP-037: Q1 no conserva inputs permanentes; la edición se abre en un modal.
      await expect(page.locator('[data-testid="input-presidencia-sesion"]')).toHaveCount(0)
      await expect(page.locator('[data-testid="input-secretaria-sesion"]')).toHaveCount(0)
      await page.locator('[data-testid="btn-editar-autoridades"]').click()
      const modalAutoridades = page.locator('[data-testid="dialogo-edicion-autoridades"]')
      await expect(modalAutoridades).toBeVisible()
      await expect(page.locator('[data-testid="input-presidencia-modal"]')).toHaveValue(
        'Dra. María Elena Walsh',
      )
      await expect(page.locator('[data-testid="input-secretaria-modal"]')).toHaveValue(
        'Lic. Juan Gómez',
      )
      await page.locator('[data-testid="btn-cancelar-autoridades"]').click()
      await expect(modalAutoridades).toHaveCount(0)

      // Intentar cerrar la sesión teniendo un orador activo -> debe abrir el diálogo modal (H4)
      const botonCerrar = page.locator('[data-testid="btn-cerrar-sesion"]')
      await expect(botonCerrar).toBeVisible()
      await botonCerrar.click()

      // Diálogo modal abierto con semántica accesible
      const modal = page.locator('[data-testid="dialogo-confirmacion-cierre"]')
      await expect(modal).toBeVisible()
      await expect(modal).toHaveAttribute('role', 'dialog')
      await expect(modal).toHaveAttribute('aria-modal', 'true')
      await expect(modal).toContainText('Carlos Pérez')
      await expect(modal).toContainText('1 solicitud pendiente en la cola')

      // El botón 'Cancelar y conservar sesión' debe ser clickeable y cerrar el modal
      const botonCancelar = page.locator('[data-testid="btn-cancelar-cierre"]')
      await expect(botonCancelar).toBeVisible()
      await botonCancelar.click()

      // Al cancelar, el modal se oculta y la sesión continúa abierta
      await expect(modal).toHaveCount(0)
      await expect(page.locator('[data-testid="vista-sesion-abierta"]')).toBeVisible()
    }
  })

  // ===========================================================================
  // 4. AISLAMIENTO DE SCROLL INTERNO EN PANELES (1920×1080 y 1366×768)
  // ===========================================================================
  test('Aislamiento de scroll: el crecimiento de contenido interno no modifica alturas exteriores ni la grilla 2×2 (1920×1080 y 1366×768)', async ({
    page,
  }) => {
    const estado = crearEstadoFixture({
      estado_global: 'SESION_ABIERTA',
      sesion: {
        fecha_hora_inicio_preparacion: '2026-08-25T10:00:00Z',
        fecha_hora_apertura: '2026-08-25T10:30:00Z',
        numero_sesion: 1,
        presidencia: 'Dra. A',
        secretaria_legislativa: 'Lic. B',
      },
      quorum: { cantidad_presentes: 8, requerido: 7, alcanzado: true },
    })
    await configurarRutasMock(page, estado)

    for (const viewport of [
      { width: 1920, height: 1080 },
      { width: 1366, height: 768 },
    ]) {
      await page.setViewportSize(viewport)
      await page.goto('/moderacion/')
      await page
        .locator('[data-testid="cabecera-moderacion"]')
        .waitFor({ state: 'visible', timeout: 30000 })

      const paneles = obtenerPaneles(page)

      // 1. Obtenemos las dimensiones exteriores iniciales de los 4 cuadrantes
      const boxQ1Ini = await paneles.sesion.boundingBox()
      const boxQ2Ini = await paneles.ordenDia.boundingBox()
      const boxQ3Ini = await paneles.recinto.boundingBox()
      const boxQ4Ini = await paneles.eventos.boundingBox()

      expect(boxQ1Ini).not.toBeNull()
      expect(boxQ2Ini).not.toBeNull()
      expect(boxQ3Ini).not.toBeNull()
      expect(boxQ4Ini).not.toBeNull()

      // 2. Inyectamos 100 elementos de prueba en el contenedor scrollable interno de Eventos (Q4)
      const scrollInternoGenerado = await page.evaluate(() => {
        const contenedorScrollQ4 = document.querySelector(
          '[data-testid="panel-eventos"] .overflow-y-auto',
        )
        if (!contenedorScrollQ4) return false

        for (let i = 0; i < 100; i++) {
          const item = document.createElement('div')
          item.textContent = `Evento auditado de prueba con texto largo #${i}`
          item.style.padding = '16px'
          item.style.borderBottom = '1px solid #334155'
          contenedorScrollQ4.appendChild(item)
        }

        // Comprobamos que el contenedor interno ahora requiere scroll vertical
        return contenedorScrollQ4.scrollHeight > contenedorScrollQ4.clientHeight
      })

      expect(scrollInternoGenerado).toBe(true)

      // 3. Volvemos a medir las dimensiones exteriores de los 4 cuadrantes
      const boxQ1Fin = await paneles.sesion.boundingBox()
      const boxQ2Fin = await paneles.ordenDia.boundingBox()
      const boxQ3Fin = await paneles.recinto.boundingBox()
      const boxQ4Fin = await paneles.eventos.boundingBox()

      expect(boxQ1Fin).not.toBeNull()
      expect(boxQ2Fin).not.toBeNull()
      expect(boxQ3Fin).not.toBeNull()
      expect(boxQ4Fin).not.toBeNull()

      if (
        boxQ1Ini &&
        boxQ2Ini &&
        boxQ3Ini &&
        boxQ4Ini &&
        boxQ1Fin &&
        boxQ2Fin &&
        boxQ3Fin &&
        boxQ4Fin
      ) {
        // La altura exterior del panel con scroll (Q4) NO aumentó arbitrariamente
        expect(Math.abs(boxQ4Fin.height - boxQ4Ini.height)).toBeLessThanOrEqual(2)

        // Las alturas de los paneles hermanos (Q1, Q2, Q3) permanecen inalteradas
        expect(Math.abs(boxQ1Fin.height - boxQ1Ini.height)).toBeLessThanOrEqual(2)
        expect(Math.abs(boxQ2Fin.height - boxQ2Ini.height)).toBeLessThanOrEqual(2)
        expect(Math.abs(boxQ3Fin.height - boxQ3Ini.height)).toBeLessThanOrEqual(2)

        // La geometría 2×2 se preserva intacta sin solapamientos
        expect(boxQ1Fin.x + boxQ1Fin.width).toBeLessThanOrEqual(boxQ2Fin.x + 2)
        expect(boxQ3Fin.x + boxQ3Fin.width).toBeLessThanOrEqual(boxQ4Fin.x + 2)
        expect(boxQ1Fin.y + boxQ1Fin.height).toBeLessThanOrEqual(boxQ3Fin.y + 2)
        expect(boxQ2Fin.y + boxQ2Fin.height).toBeLessThanOrEqual(boxQ4Fin.y + 2)
      }

      // 4. El scroll global de la ventana NO debe desbordar
      const scrollH = await page.evaluate(() => document.documentElement.scrollHeight)
      const scrollW = await page.evaluate(() => document.documentElement.scrollWidth)
      expect(scrollH).toBeLessThanOrEqual(viewport.height + 2)
      expect(scrollW).toBeLessThanOrEqual(viewport.width + 2)
    }
  })
})

test.describe('WP-036 - Cabecera compacta y redistribución del shell', () => {
  /** Estado con sesión abierta, quórum alcanzado y autoridades cargadas. */
  function crearEstadoSesionAbierta() {
    return crearEstadoFixture({
      estado_global: 'SESION_ABIERTA',
      sesion: {
        fecha_hora_inicio_preparacion: '2026-08-25T10:00:00Z',
        fecha_hora_apertura: '2026-08-25T10:30:00Z',
        numero_sesion: 8,
        presidencia: 'Dra. María Elena Walsh',
        secretaria_legislativa: 'Lic. Juan Gómez',
      },
      quorum: { cantidad_presentes: 9, requerido: 7, alcanzado: true },
    })
  }

  test('el reloj local de la cabecera avanza sin intervención ni recarga', async ({ page }) => {
    await configurarRutasMock(page, crearEstadoSesionAbierta())
    await page.setViewportSize({ width: 1366, height: 768 })
    await page.goto('/moderacion/')

    const reloj = page.locator('[data-testid="cabecera-fecha-hora"]')
    await expect(reloj).toBeVisible()

    // El primer valor sirve de referencia: al segundo siguiente el reloj debe haber cambiado.
    const primerValor = await reloj.textContent()
    expect(primerValor?.trim()).toMatch(/^Fecha\s+\d{2}\/\d{2}\/\d{4} \d{2}:\d{2}:\d{2}$/)
    await expect(reloj).not.toHaveText(primerValor ?? '')

    // El tiempo de sesión se deriva de la misma marca autoritativa y también avanza.
    const tiempoSesion = page.locator('[data-testid="cabecera-tiempo-sesion"]')
    const primerTiempo = await tiempoSesion.textContent()
    await expect(tiempoSesion).not.toHaveText(primerTiempo ?? '')
  })

  test('la grilla 2×2 escala con el viewport en lugar de depender de alturas fijas', async ({
    page,
  }) => {
    await configurarRutasMock(page, crearEstadoSesionAbierta())

    const alturas: Record<string, number> = {}

    for (const viewport of [
      { width: 1920, height: 1080 },
      { width: 1366, height: 768 },
    ]) {
      await page.setViewportSize(viewport)
      await page.goto('/moderacion/')
      await page
        .locator('[data-testid="cabecera-moderacion"]')
        .waitFor({ state: 'visible', timeout: 30000 })

      await verificarGeometriaShellCompleto(page, viewport)

      const cajaQ1 = await obtenerPaneles(page).sesion.boundingBox()
      const cajaCabecera = await page.locator('[data-testid="cabecera-moderacion"]').boundingBox()
      expect(cajaQ1).not.toBeNull()
      expect(cajaCabecera).not.toBeNull()

      if (cajaQ1 && cajaCabecera) {
        alturas[`${viewport.height}`] = cajaQ1.height

        // La cabecera compacta no debe consumir más del 10 % de la altura del viewport.
        expect(cajaCabecera.height).toBeLessThanOrEqual(viewport.height * 0.1)

        // Cada fila de la grilla ocupa una fracción sustancial del alto restante:
        // eso sólo es posible si el shell reparte el espacio en unidades fraccionarias.
        expect(cajaQ1.height).toBeGreaterThan(viewport.height * 0.35)
      }
    }

    // Si el layout dependiera de alturas absolutas en píxeles, el cuadrante mediría igual
    // en ambas resoluciones. Debe crecer junto con el viewport.
    expect(alturas['1080']).toBeGreaterThan(alturas['768'] + 50)
  })
})

test.describe('WP-047 - Densidad, cabecera y reloj robusto de Moderación', () => {
  // La zona difiere deliberadamente de las marcas naive del backend. Una resta
  // Date.now()-Date.parse(apertura) produciría otro valor y haría fallar la prueba.
  test.use({ timezoneId: 'America/Los_Angeles' })

  function crearEstadoWp047() {
    return crearEstadoFixture({
      generado_en: '2026-08-31T10:30:00',
      estado_global: 'SESION_ABIERTA',
      sesion: {
        fecha_hora_inicio_preparacion: '2026-08-31T09:45:00',
        fecha_hora_apertura: '2026-08-31T10:00:00',
        numero_sesion: 47,
        presidencia: 'Dra. María Elena Walsh',
        secretaria_legislativa: 'Lic. Juan Gómez',
      },
      quorum: { cantidad_presentes: 9, requerido: 7, alcanzado: true },
    })
  }

  for (const viewport of [
    { width: 1366, height: 768 },
    { width: 1920, height: 1080 },
  ]) {
    test(`reduce chrome y conserva toda la grilla/cabecera en ${viewport.width}×${viewport.height}`, async ({
      page,
    }, testInfo) => {
      await configurarRutasMock(page, crearEstadoWp047())
      await page.setViewportSize(viewport)
      await page.goto('/moderacion/')
      await page.getByTestId('cabecera-moderacion').waitFor()

      await verificarGeometriaShellCompleto(page, viewport)
      await verificarDensidadComunWp047(page, viewport)

      const cabecera = page.getByTestId('cabecera-moderacion')
      await expect(cabecera).not.toContainText('Sesión abierta')
      await expect(page.getByTestId('estado-global')).toHaveCount(0)
      await expect(page.getByTestId('cabecera-numero-sesion')).toHaveText('Sesión Nº 47')
      await expect(page.getByTestId('cabecera-quorum')).toContainText('Quórum 9/12')
      await expect(page.getByTestId('cabecera-presidencia')).toContainText('Dra. María Elena Walsh')
      await expect(page.getByTestId('cabecera-secretaria')).toContainText('Lic. Juan Gómez')
      await expect(page.getByTestId('cabecera-fecha-hora')).toBeVisible()
      await expect(page.getByTestId('estado-conexion')).toBeVisible()

      // La captura queda adjunta al reporte reproducible de Playwright para comparar
      // la proporción de chrome con la referencia histórica consultada.
      await testInfo.attach(`wp047-${viewport.width}x${viewport.height}.png`, {
        body: await page.screenshot({ fullPage: true }),
        contentType: 'image/png',
      })
    })
  }

  test('ancla dos marcas backend naive y continúa avanzando en otra zona horaria', async ({
    page,
  }) => {
    await page.clock.install({ time: new Date('2035-01-02T03:04:05Z') })
    await configurarRutasMock(page, crearEstadoWp047())
    await page.setViewportSize({ width: 1366, height: 768 })
    await page.goto('/moderacion/')
    await page.clock.runFor(50)

    const tiempoSesion = page.getByTestId('cabecera-tiempo-sesion')
    await expect(tiempoSesion).toContainText('00:30:00')
    await page.clock.runFor(1000)
    await expect(tiempoSesion).toContainText('00:30:01')
  })
})

test.describe('WP-037 - Q1 compacto sin scroll interno', () => {
  const escenarios = [
    {
      nombre: 'SIN_PREPARAR',
      estado: crearEstadoFixture({ estado_global: 'SIN_PREPARAR', quorum: null }),
      selectorVisible: '[data-testid="btn-preparar-sala"]',
    },
    {
      nombre: 'PREPARANDO',
      estado: crearEstadoFixture({
        estado_global: 'PREPARANDO',
        preparacion: {
          fecha_hora_inicio: '2026-08-29T09:30:00Z',
          numero_sesion: 42,
          presidencia: 'Dra. Presidencia',
          secretaria_legislativa: 'Lic. Secretaría',
        },
        quorum: { cantidad_presentes: 8, requerido: 7, alcanzado: true },
        capacidades: {
          ...crearEstadoFixture().capacidades,
          preparar_sala: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
          actualizar_preparacion: { habilitada: true, motivos: [] },
          cancelar_preparacion: { habilitada: true, motivos: [] },
          abrir_sesion: { habilitada: true, motivos: [] },
        },
      }),
      selectorVisible: '[data-testid="btn-abrir-sesion"]',
    },
    {
      nombre: 'SESION_ABIERTA lista para votar',
      estado: crearEstadoSesionCompacta(),
      selectorVisible: '[data-testid="formulario-votacion"]',
    },
    {
      nombre: 'votación EN_CURSO',
      estado: crearEstadoSesionCompacta({
        votacion: crearVotacionCompacta(),
        capacidades: {
          ...crearCapacidadesSesionCompacta(),
          abrir_votacion: { habilitada: false, motivos: ['VOTACION_PENDIENTE'] },
          finalizar_votacion: { habilitada: true, motivos: [] },
        },
      }),
      selectorVisible: '[data-testid="btn-finalizar-votacion"]',
    },
    {
      nombre: 'resultado cerrado con conteos',
      estado: crearEstadoSesionCompacta({
        votacion: crearVotacionCompacta({
          estado_recepcion: 'CERRADA',
          resultado: 'APROBADA',
          fecha_hora_cierre: '2026-08-29T10:00:10Z',
          fecha_hora_resultado: '2026-08-29T10:00:10Z',
        }),
      }),
      selectorVisible: '[data-testid="conteos-votacion"]',
    },
    {
      nombre: 'empate pendiente',
      estado: crearEstadoSesionCompacta({
        votacion: crearVotacionCompacta({
          estado_recepcion: 'CERRADA',
          resultado: 'EMPATADA',
          fecha_hora_cierre: '2026-08-29T10:00:10Z',
          fecha_hora_resultado: '2026-08-29T10:00:10Z',
          conteos: { positivos: 4, negativos: 4, abstenciones: 0, total: 8 },
        }),
        capacidades: {
          ...crearCapacidadesSesionCompacta(),
          abrir_votacion: { habilitada: false, motivos: ['VOTACION_PENDIENTE'] },
          desempatar: { habilitada: true, motivos: [] },
        },
      }),
      selectorVisible: '[data-testid="controles-desempate"]',
    },
  ]

  for (const escenario of escenarios) {
    test(`${escenario.nombre}: el contenido real entra completo a 1366×768`, async ({ page }) => {
      await configurarRutasMock(page, escenario.estado)
      await page.setViewportSize({ width: 1366, height: 768 })
      await page.goto('/moderacion/')

      await expect(page.locator(escenario.selectorVisible)).toBeVisible()
      await verificarQ1SinScroll(page)
      await expect(page.locator('[data-testid="votos-individuales"]')).toHaveCount(0)
      await expect(page.locator('[data-testid="panel-sesion-votacion"]')).not.toContainText(
        'No debe renderizarse',
      )
    })
  }

  test('el modal de autoridades no deforma Q1 ni el shell a 1366×768', async ({ page }) => {
    await configurarRutasMock(page, crearEstadoSesionCompacta())
    await page.setViewportSize({ width: 1366, height: 768 })
    await page.goto('/moderacion/')

    const panel = page.locator('[data-testid="panel-sesion-votacion"]')
    const cajaAntes = await panel.boundingBox()
    await verificarQ1SinScroll(page)

    await page.locator('[data-testid="btn-editar-autoridades"]').click()
    const modal = page.locator('[data-testid="dialogo-edicion-autoridades"]')
    await expect(modal).toBeVisible()
    await expect(modal).toHaveAttribute('role', 'dialog')
    await expect(page.locator('[data-testid="input-presidencia-modal"]')).toBeVisible()
    await expect(page.locator('[data-testid="input-secretaria-modal"]')).toBeVisible()

    const cajaDurante = await panel.boundingBox()
    expect(cajaAntes).not.toBeNull()
    expect(cajaDurante).not.toBeNull()
    if (cajaAntes && cajaDurante) {
      expect(Math.abs(cajaDurante.height - cajaAntes.height)).toBeLessThanOrEqual(1)
      expect(Math.abs(cajaDurante.width - cajaAntes.width)).toBeLessThanOrEqual(1)
    }
    await verificarQ1SinScroll(page)
  })

  test('resultado y siguiente formulario entran completos a 1920×1080', async ({ page }) => {
    await configurarRutasMock(
      page,
      crearEstadoSesionCompacta({
        votacion: crearVotacionCompacta({
          estado_recepcion: 'CERRADA',
          resultado: 'RECHAZADA',
          fecha_hora_cierre: '2026-08-29T10:00:10Z',
          fecha_hora_resultado: '2026-08-29T10:00:10Z',
        }),
      }),
    )
    await page.setViewportSize({ width: 1920, height: 1080 })
    await page.goto('/moderacion/')

    await expect(page.locator('[data-testid="conteos-votacion"]')).toBeVisible()
    await expect(page.locator('[data-testid="formulario-votacion"]')).toBeVisible()
    await verificarQ1SinScroll(page)
    await verificarGeometriaShellCompleto(page, { width: 1920, height: 1080 })
  })
})

test.describe('WP-040 - Dos estados del Orden del Día', () => {
  test('recorre carga, puntos, precarga Q1, descarte y retorno autoritativo a 1366×768', async ({
    page,
  }) => {
    await configurarOrdenDelDiaMock(page, crearEstadoSesionCompacta())
    await page.setViewportSize({ width: 1366, height: 768 })
    await page.goto('/moderacion/')

    const panel = page.locator('[data-testid="panel-orden-del-dia"]')
    const entrada = panel.locator('[data-testid="input-archivo-orden-dia"]')
    await expect(entrada).toBeVisible()
    await expect(panel.locator('[data-testid="btn-cargar-orden-dia"]')).toBeVisible()
    await expect(panel.locator('[data-testid="btn-quitar-orden-dia"]')).toHaveCount(0)
    await expect(panel).not.toContainText('Orden del Día opcional')
    await verificarOrdenVacioSinScroll(page)

    await entrada.setInputFiles({
      name: 'orden-sesion-42.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from(
        'nro_votacion,tipo,tema,tipo_mayoria,factor,base\n1,Proyecto,Tema,SIMPLE,0,VOTOS_COMPUTABLES',
      ),
    })
    // WP-044: el input nativo ya muestra el nombre; el panel no lo repite.
    await expect(panel).not.toContainText('Seleccionado:')
    await panel.locator('[data-testid="btn-cargar-orden-dia"]').click()

    await expect(panel.locator('[data-testid="punto-orden-dia"]')).toHaveCount(2)
    await expect(panel.locator('[data-testid="input-archivo-orden-dia"]')).toHaveCount(0)
    await expect(panel).not.toContainText('Reemplazar')
    await expect(panel.locator('[data-testid="btn-quitar-orden-dia"]')).toHaveCount(1)

    // La tarjeta continúa copiando sus datos al borrador editable de Q1.
    await panel.locator('[data-testid="punto-orden-dia"]').first().click()
    await expect(page.locator('[data-testid="input-numero-votacion"]')).toHaveValue('1')
    await expect(page.locator('[data-testid="select-tipo-votacion"]')).toHaveValue('Proyecto')
    await expect(page.locator('[data-testid="input-tema-votacion"]')).toHaveValue(
      'Tema ordinario 1 del Orden del Día',
    )
    await expect(panel.locator('[data-testid="punto-orden-dia"]')).toHaveCount(2)

    await panel.locator('[data-testid="btn-quitar-orden-dia"]').click()
    await expect(panel.locator('[data-testid="punto-orden-dia"]')).toHaveCount(0)
    await expect(panel.locator('[data-testid="input-archivo-orden-dia"]')).toBeVisible()
    await expect(panel.locator('[data-testid="btn-quitar-orden-dia"]')).toHaveCount(0)
    await verificarOrdenVacioSinScroll(page)
    await verificarGeometriaShellCompleto(page, { width: 1366, height: 768 })
  })

  test('confina un listado largo y conserva accesible Quitar en 1366×768 y 1920×1080', async ({
    page,
  }) => {
    await configurarOrdenDelDiaMock(page, crearEstadoSesionCompacta())

    for (const viewport of [
      { width: 1366, height: 768 },
      { width: 1920, height: 1080 },
    ]) {
      await page.setViewportSize(viewport)
      await page.goto('/moderacion/')
      await page.evaluate(() => {
        ;(window as Window & { publicarOrdenDelDiaLargo?: () => void }).publicarOrdenDelDiaLargo?.()
      })

      const panel = page.locator('[data-testid="panel-orden-del-dia"]')
      const cuerpo = panel.locator('[data-testid="cuerpo-panel"]')
      const lista = panel.locator('[data-testid="lista-orden-dia"]')
      const botonQuitar = panel.locator('[data-testid="btn-quitar-orden-dia"]')
      await expect(panel.locator('[data-testid="punto-orden-dia"]')).toHaveCount(24)
      await expect(botonQuitar).toBeVisible()

      const medicion = await lista.evaluate((elemento) => ({
        altoVisible: elemento.clientHeight,
        altoContenido: elemento.scrollHeight,
        overflowY: getComputedStyle(elemento).overflowY,
      }))
      expect(['auto', 'scroll']).toContain(medicion.overflowY)
      expect(medicion.altoContenido).toBeGreaterThan(medicion.altoVisible)

      const medicionExterior = await cuerpo.evaluate((elemento) => ({
        altoVisible: elemento.clientHeight,
        altoContenido: elemento.scrollHeight,
        overflowY: getComputedStyle(elemento).overflowY,
      }))
      expect(['auto', 'scroll']).not.toContain(medicionExterior.overflowY)
      expect(medicionExterior.altoContenido).toBeLessThanOrEqual(medicionExterior.altoVisible + 1)

      const cajaPanel = await panel.boundingBox()
      const cajaBoton = await botonQuitar.boundingBox()
      expect(cajaPanel).not.toBeNull()
      expect(cajaBoton).not.toBeNull()
      expect(cajaBoton!.y).toBeGreaterThanOrEqual(cajaPanel!.y)
      expect(cajaBoton!.y + cajaBoton!.height).toBeLessThanOrEqual(cajaPanel!.y + cajaPanel!.height)
      await verificarGeometriaShellCompleto(page, viewport)
    }
  })
})

test.describe('WP-023 - Recorrido de votación y Orden del Día', () => {
  test('selecciona un punto, confirma CA-062 y adopta EN_CURSO, EMPATADA y desempate desde SSE', async ({
    page,
  }) => {
    const capacidades = {
      preparar_sala: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      actualizar_preparacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      cancelar_preparacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      abrir_sesion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      actualizar_sesion: { habilitada: true, motivos: [] },
      cerrar_sesion: { habilitada: true, motivos: [] },
      cargar_orden_del_dia: { habilitada: true, motivos: [] },
      descartar_orden_del_dia: { habilitada: true, motivos: [] },
      abrir_votacion: { habilitada: true, motivos: [] },
      finalizar_votacion: { habilitada: false, motivos: ['VOTACION_NO_EN_CURSO'] },
      desempatar: { habilitada: false, motivos: ['VOTACION_NO_EMPATADA'] },
      otorgar_palabra: { habilitada: true, motivos: [] },
      quitar_palabra: { habilitada: true, motivos: [] },
    }
    const estado = crearEstadoFixture({
      estado_global: 'SESION_ABIERTA',
      sesion: {
        fecha_hora_inicio_preparacion: '2026-08-26T09:30:00Z',
        fecha_hora_apertura: '2026-08-26T09:45:00Z',
        numero_sesion: 42,
        presidencia: 'Dra. Presidencia',
        secretaria_legislativa: 'Sr. Secretaría',
      },
      configuracion: {
        quorum: 7,
        filas_bancas: [3, 4, 5],
        tipos_votacion: ['Proyecto', 'Moción'],
        duracion_test_segundos: 3,
        revelado_votos_moderacion_segundos: 4,
        cuenta_regresiva_recinto_segundos: 3,
        resultado_publico_recinto_segundos: 6,
      },
      quorum: { cantidad_presentes: 8, requerido: 7, alcanzado: true },
      palabra: {
        orador: { dni: '30000001', nombre: 'Ada', apellido: 'Lovelace', banca: 1 },
        cola: [{ dni: '30000002', nombre: 'Grace', apellido: 'Hopper', banca: 2 }],
      },
      orden_del_dia: [
        {
          nro_votacion: 12,
          tipo: 'Proyecto',
          tema: 'Presupuesto anual',
          tipo_mayoria: 'SIMPLE',
          factor: 0,
          base: 'VOTOS_COMPUTABLES',
        },
      ],
      eventos_recientes: [],
      auditoria: {
        activa: true,
        disponible: true,
        fallado: false,
        cerrado: false,
        motivo: null,
      },
      capacidades,
    })
    await configurarCicloVotacionMock(page, estado)
    await page.setViewportSize({ width: 1366, height: 768 })
    await page.goto('/moderacion/')
    await expect(page.locator('[data-testid="formulario-votacion"]')).toBeVisible()

    // Q2 copia el punto como borrador editable en Q1, sin consumirlo.
    await page.locator('[data-testid="punto-orden-dia"]').click()
    await expect(page.locator('[data-testid="input-numero-votacion"]')).toHaveValue('12')
    await expect(page.locator('[data-testid="select-tipo-votacion"]')).toHaveValue('Proyecto')
    await expect(page.locator('[data-testid="input-tema-votacion"]')).toHaveValue(
      'Presupuesto anual',
    )
    await page.locator('[data-testid="input-tema-votacion"]').fill('Presupuesto editado')
    await expect(page.locator('[data-testid="punto-orden-dia"]')).toHaveCount(1)

    // CA-062: cancelar no envía; confirmar conserva orador y cola.
    await page.locator('[data-testid="btn-abrir-votacion"]').click()
    const dialogo = page.locator('[data-testid="dialogo-confirmacion-apertura"]')
    await expect(dialogo).toBeVisible()
    await expect(dialogo).toContainText('Ada Lovelace')
    await page.locator('[data-testid="btn-cancelar-apertura"]').click()
    await expect(dialogo).toHaveCount(0)
    await expect(page.locator('[data-testid="vista-votacion-proyectada"]')).toHaveCount(0)

    await page.locator('[data-testid="btn-abrir-votacion"]').click()
    await page.locator('[data-testid="btn-confirmar-apertura"]').click()
    const vista = page.locator('[data-testid="vista-votacion-proyectada"]')
    await expect(vista).toBeVisible()
    await expect(vista).toContainText('Presupuesto editado')
    await expect(page.locator('[data-testid="estado-votacion"]')).toContainText('EN_CURSO')
    await expect(page.locator('[data-testid="votos-ocultos"]')).toBeVisible()
    // WP-048: Q1 tampoco informa de forma permanente al orador ni la cantidad en cola.
    // Esa información es continua y su sede es Q3, no el cuerpo de la votación.
    await expect(page.locator('[data-testid="palabra-durante-votacion"]')).toHaveCount(0)
    await expect(page.locator('[data-testid="panel-sesion-votacion"]')).not.toContainText(
      'Ada Lovelace',
    )
    // WP-044: Q3 dejó de repetir al orador; su señal vive en la banca resaltada.
    await expect(page.locator('[data-testid="orador-actual-texto"]')).toHaveCount(0)

    // El backend controlado simula el cierre normal empatado y lo publica como snapshot completo.
    await page.evaluate(() => {
      ;(window as Window & { cerrarComoEmpatada?: () => void }).cerrarComoEmpatada?.()
    })
    await expect(page.locator('[data-testid="estado-votacion"]')).toContainText('EMPATADA')
    await expect(page.locator('[data-testid="conteos-votacion"]')).toContainText('4')
    await expect(page.locator('[data-testid="votos-individuales"]')).toHaveCount(0)
    await expect(vista).not.toContainText('Concejal01')
    const controles = page.locator('[data-testid="controles-desempate"]')
    await expect(controles).toContainText('Dra. Presidencia')
    await expect(controles).not.toContainText('ABSTENCION')

    await page.locator('[data-testid="btn-desempate-positivo"]').click()
    await expect(page.locator('[data-testid="estado-votacion"]')).toContainText('APROBADA')
    await expect(controles).toHaveCount(0)
    await expect(page.locator('[data-testid="formulario-votacion"]')).toBeVisible()
  })
})

test.describe('WP-024 - Palabra, eventos y remapeo autoritativos', () => {
  test('recorre CA-061, filtros de eventos y confirmación física en ambas resoluciones', async ({
    page,
  }) => {
    const capacidades = {
      preparar_sala: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      actualizar_preparacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      cancelar_preparacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      abrir_sesion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      actualizar_sesion: { habilitada: true, motivos: [] },
      cerrar_sesion: { habilitada: true, motivos: [] },
      cargar_orden_del_dia: { habilitada: true, motivos: [] },
      descartar_orden_del_dia: { habilitada: true, motivos: [] },
      abrir_votacion: { habilitada: true, motivos: [] },
      finalizar_votacion: { habilitada: false, motivos: ['VOTACION_NO_EN_CURSO'] },
      desempatar: { habilitada: false, motivos: ['VOTACION_NO_EMPATADA'] },
      otorgar_palabra: { habilitada: true, motivos: [] },
      quitar_palabra: { habilitada: true, motivos: [] },
      iniciar_remapeo: { habilitada: true, motivos: [] },
      confirmar_remapeo: { habilitada: false, motivos: ['REMAPEO_NO_COINCIDE'] },
      cancelar_remapeo: { habilitada: false, motivos: ['REMAPEO_NO_COINCIDE'] },
    }
    const estado = crearEstadoFixture({
      estado_global: 'SESION_ABIERTA',
      sesion: {
        fecha_hora_inicio_preparacion: '2026-08-27T09:00:00Z',
        fecha_hora_apertura: '2026-08-27T09:30:00Z',
        numero_sesion: 24,
        presidencia: 'Dra. Presidencia',
        secretaria_legislativa: 'Sr. Secretaría',
      },
      quorum: { cantidad_presentes: 8, requerido: 7, alcanzado: true },
      palabra: {
        orador: {
          dni: '30000001',
          nombre: 'Concejal01',
          apellido: 'Apellido01',
          banca: 1,
        },
        cola: [
          {
            dni: '30000002',
            nombre: 'Concejal02',
            apellido: 'Apellido02',
            banca: 2,
          },
          {
            dni: '30000003',
            nombre: 'Concejal03',
            apellido: 'Apellido03',
            banca: 3,
          },
        ],
      },
      eventos_recientes: [
        {
          seq: 201,
          timestamp: '2026-08-27T10:00:01',
          nivel: 'L1',
          etiqueta: 'SISTEMA',
          codigo_evento: 'EVENTO_TECNICO',
          mensaje: 'Detalle técnico persistido',
        },
        {
          seq: 202,
          timestamp: '2026-08-27T10:00:02',
          nivel: 'L2',
          etiqueta: 'OPERACION',
          codigo_evento: 'EVENTO_INTERMEDIO',
          mensaje: 'Detalle operativo persistido',
        },
        {
          seq: 203,
          timestamp: '2026-08-27T10:00:03',
          nivel: 'L3',
          etiqueta: 'PALABRA',
          codigo_evento: 'EVENTO_PRINCIPAL',
          mensaje: 'Hecho institucional persistido',
        },
      ],
      auditoria: {
        activa: true,
        disponible: true,
        fallado: false,
        cerrado: false,
        motivo: null,
      },
      remapeo: null,
      capacidades,
    })
    await configurarCicloPalabraRemapeoMock(page, estado)

    for (const viewport of [
      { width: 1920, height: 1080 },
      { width: 1366, height: 768 },
    ]) {
      await page.setViewportSize(viewport)
      await page.goto('/moderacion/')
      await expect(page.locator('[data-testid="gestion-palabra"]')).toBeVisible()
      await verificarGeometriaShellCompleto(page, viewport)

      // La cola completa conserva FIFO y quitar no promueve implícitamente.
      // WP-044: el orador se lee en su banca, no en un texto repetido dentro de la columna.
      await expect(page.locator('[data-testid="orador-actual-texto"]')).toHaveCount(0)
      // La banca 1 también tiene test activo, que gana en prioridad; el uso de
      // la palabra sobrevive como halo, sin agregar una segunda etiqueta.
      await expect(page.locator('[data-banca="1"]')).toHaveAttribute('data-halo-palabra', 'true')
      await expect(page.locator('[data-testid="pedido-palabra-1"]')).toContainText(
        'Concejal02 Apellido02',
      )
      await expect(page.locator('[data-testid="pedido-palabra-2"]')).toContainText(
        'Concejal03 Apellido03',
      )
      await page.locator('[data-testid="btn-quitar-palabra"]').evaluate((boton) => {
        ;(boton as HTMLButtonElement).click()
        ;(boton as HTMLButtonElement).click()
      })
      await expect(page.locator('[data-halo-palabra="true"]')).toHaveCount(0)
      await expect(page.locator('[data-estado-banca="PALABRA"]')).toHaveCount(0)
      await expect(page.locator('[data-testid="badge-cola-palabra"]')).toContainText('2 en cola')

      await page.locator('[data-testid="btn-otorgar-palabra"]').evaluate((boton) => {
        ;(boton as HTMLButtonElement).click()
        ;(boton as HTMLButtonElement).click()
      })
      await expect(page.locator('[data-banca="2"]')).toHaveAttribute('data-estado-banca', 'PALABRA')
      await expect(page.locator('[data-testid="badge-cola-palabra"]')).toContainText('1 en cola')

      // L3 es inicial; L2 y L1 incluyen acumulativamente los niveles inferiores.
      await expect(page.locator('[data-testid="evento-reciente"]')).toHaveCount(1)
      await expect(page.locator('[data-testid="panel-eventos"]')).toContainText('EVENTO_PRINCIPAL')
      await page.locator('[data-testid="filtro-eventos"]').selectOption('L2')
      await expect(page.locator('[data-testid="evento-reciente"]')).toHaveCount(2)
      await page.locator('[data-testid="filtro-eventos"]').selectOption('L1')
      await expect(page.locator('[data-testid="evento-reciente"]')).toHaveCount(3)
      // WP-041: el orden visual es descendente, así que el evento más nuevo encabeza.
      await expect(page.locator('[data-testid="nivel-evento"]')).toHaveText(['L3', 'L2', 'L1'])

      // El objetivo se elige desde banca/persona/devXX; luego manda el snapshot.
      await page.locator('[data-testid="btn-desplegar-remapeo"]').click()
      await page.locator('[data-testid="selector-banca-remapeo"]').selectOption('dev03')
      await expect(page.locator('[data-testid="resumen-inicio-remapeo"]')).toContainText('Banca 3')
      await page.locator('[data-testid="btn-iniciar-remapeo"]').evaluate((boton) => {
        ;(boton as HTMLButtonElement).click()
        ;(boton as HTMLButtonElement).click()
      })
      await expect(page.locator('[data-testid="estado-remapeo"]')).toHaveText('CAPTURANDO')
      await expect(page.locator('[data-testid="dispositivo-remapeo"]')).toHaveText('dev03')

      await page.evaluate(() => {
        ;(window as Window & { capturarCandidatoRemapeo?: () => void }).capturarCandidatoRemapeo?.()
      })
      await expect(page.locator('[data-testid="estado-remapeo"]')).toHaveText('CANDIDATO')
      await expect(page.locator('[data-testid="fingerprint-candidato"]')).toContainText(
        'vendor=9001',
      )
      await expect(page.locator('[data-testid="diagnostico-remapeo"]')).toContainText(
        'Teclado USB de reemplazo',
      )
      await expect(page.locator('[data-testid="btn-confirmar-remapeo"]')).toBeDisabled()
      await page.locator('[data-testid="persistencia-temporal"]').check()
      await expect(page.locator('[data-testid="resumen-confirmacion-remapeo"]')).toContainText(
        'TEMPORAL',
      )
      await page.locator('[data-testid="btn-confirmar-remapeo"]').evaluate((boton) => {
        ;(boton as HTMLButtonElement).click()
        ;(boton as HTMLButtonElement).click()
      })
      await expect(page.locator('[data-testid="remapeo-activo"]')).toHaveCount(0)
      await expect(page.locator('[data-testid="btn-desplegar-remapeo"]')).toBeVisible()

      const control = await page.evaluate(() =>
        (
          window as Window & {
            obtenerControlWp024?: () => {
              conteos: { quitar: number; otorgar: number; iniciar: number; confirmar: number }
              ultimaConfirmacion: { remapeoId: string; persistencia: string } | null
            }
          }
        ).obtenerControlWp024?.(),
      )
      expect(control?.conteos).toEqual({ quitar: 1, otorgar: 1, iniciar: 1, confirmar: 1 })
      expect(control?.ultimaConfirmacion).toEqual({
        remapeoId: 'remapeo-e2e-wp024',
        persistencia: 'TEMPORAL',
      })
      await verificarGeometriaShellCompleto(page, viewport)
    }
  })
})

test.describe('WP-039 - Q3 horizontal, scroll de cola y remapeo compacto', () => {
  test('mantiene bancas, palabra y controles dentro del cuadrante en ambas resoluciones', async ({
    page,
  }) => {
    const estado = crearEstadoFixture({
      estado_global: 'SESION_ABIERTA',
      sesion: {
        fecha_hora_inicio_preparacion: '2026-08-30T09:00:00Z',
        fecha_hora_apertura: '2026-08-30T09:30:00Z',
        numero_sesion: 39,
        presidencia: 'Presidencia de prueba',
        secretaria_legislativa: 'Secretaría de prueba',
      },
      configuracion: { filas_bancas: [3, 4, 5] },
      concejales: crearConcejalesFixture(12),
      quorum: { cantidad_presentes: 8, requerido: 7, alcanzado: true },
      palabra: {
        orador: {
          dni: '30000001',
          nombre: 'Concejal01',
          apellido: 'Apellido01',
          banca: 1,
        },
        cola: Array.from({ length: 11 }, (_, indice) => {
          const banca = indice + 2
          return {
            dni: `300000${String(banca).padStart(2, '0')}`,
            nombre: `Concejal${String(banca).padStart(2, '0')}`,
            apellido: `Apellido${String(banca).padStart(2, '0')}`,
            banca,
          }
        }),
      },
      remapeo: null,
    })
    await configurarRutasMock(page, estado)

    for (const viewport of [
      { width: 1366, height: 768 },
      { width: 1920, height: 1080 },
    ]) {
      await page.setViewportSize(viewport)
      await page.goto('/moderacion/')

      const bancas = page.locator('[data-testid="area-bancas-moderacion"]')
      const palabra = page.locator('[data-testid="columna-palabra-moderacion"]')
      const cajaBancas = await bancas.boundingBox()
      const cajaPalabra = await palabra.boundingBox()
      expect(cajaBancas).not.toBeNull()
      expect(cajaPalabra).not.toBeNull()
      expect(cajaBancas!.x + cajaBancas!.width).toBeLessThanOrEqual(cajaPalabra!.x)

      // WP-044 devolvió altura a la columna al quitar el texto del orador y el subtítulo
      // FIFO, así que una cola de 11 pedidos puede entrar completa. Lo que WP-039 exige
      // sigue verificándose: la cola es la única región desplazable y nada desborda la
      // columna ni el cuadrante.
      const medidasCola = await page
        .locator('[data-testid="contenedor-scroll-cola-palabra"]')
        .evaluate((cola) => ({
          altoVisible: cola.clientHeight,
          altoContenido: cola.scrollHeight,
          overflowY: getComputedStyle(cola).overflowY,
        }))
      expect(['auto', 'scroll']).toContain(medidasCola.overflowY)
      expect(medidasCola.altoVisible).toBeGreaterThan(0)
      const medidasColumnaPalabra = await page
        .locator('[data-testid="columna-palabra-moderacion"]')
        .evaluate((columna) => ({
          altoVisible: columna.clientHeight,
          altoContenido: columna.scrollHeight,
        }))
      expect(medidasColumnaPalabra.altoContenido).toBeLessThanOrEqual(
        medidasColumnaPalabra.altoVisible + 1,
      )
      await expect(page.locator('[data-testid="btn-otorgar-palabra"]')).toBeVisible()
      await expect(page.locator('[data-testid="btn-quitar-palabra"]')).toBeVisible()
      expect(
        await page
          .locator('[data-testid="contenedor-scroll-cola-palabra"]')
          .locator('button')
          .count(),
      ).toBe(0)

      // WP-045: con test y palabra simultáneos gana el test como estado
      // principal y la palabra sobrevive como halo, sin segunda etiqueta.
      const bancaOrador = page.locator('[data-banca="1"]')
      await expect(bancaOrador).toHaveAttribute('data-estado-banca', 'TEST')
      await expect(bancaOrador).toHaveAttribute('data-halo-palabra', 'true')
      await expect(bancaOrador.locator('[data-testid="etiqueta-banca"]')).toHaveCount(0)
      expect(await bancaOrador.evaluate((banca) => getComputedStyle(banca).boxShadow)).not.toBe(
        'none',
      )

      await expect(page.locator('[data-testid="btn-desplegar-remapeo"]')).toBeVisible()
      await expect(page.locator('[data-testid="gestion-remapeo"]')).toHaveCount(0)
      await page.locator('[data-testid="btn-desplegar-remapeo"]').click()
      await expect(page.locator('[data-testid="gestion-remapeo"]')).toBeVisible()
      await page.locator('[data-testid="btn-cerrar-remapeo"]').click()
      await expect(page.locator('[data-testid="gestion-remapeo"]')).toHaveCount(0)

      const medidasGrilla = await page
        .locator('[data-testid="grilla-recinto"]')
        .evaluate((nodo) => ({
          altoVisible: nodo.clientHeight,
          altoContenido: nodo.scrollHeight,
        }))
      expect(medidasGrilla.altoContenido).toBeLessThanOrEqual(medidasGrilla.altoVisible + 1)
      await verificarGeometriaShellCompleto(page, viewport)
    }
  })
})

/**
 * WP-041 - Eventos recientes con nivel fijo y evento más nuevo primero.
 *
 * Este recorrido comprueba sobre el navegador real (no sobre clases CSS) que:
 *
 * 1. una cantidad suficiente de eventos produce scroll interno real en Q4;
 * 2. el selector de nivel sigue visible antes y después de desplazar la lista;
 * 3. los eventos se ordenan por `seq` descendente;
 * 4. la llegada de un evento nuevo devuelve la lista al inicio;
 * 5. el selector continúa siendo operable después del scroll;
 * 6. el shell no genera scroll de página a 1366×768;
 * 7. el comportamiento se verifica también a 1920×1080.
 */
test.describe('WP-041 - Eventos con selector fijo y evento más nuevo primero', () => {
  /**
   * Backend simulado que publica snapshots completos por SSE y expone
   * `window.publicarEventoNuevo` para provocar la llegada de actividad nueva
   * sin depender de tiempos ni de un backend real.
   */
  async function configurarBackendEventosMock(page: Page, estadoInicial: Record<string, unknown>) {
    // WP-098: la fotografía de banca ya no es un asset del build; la publica
    // el backend desde la configuración local. Sin backend real, se responde
    // desde la plantilla versionada, que es el mismo archivo de siempre.
    await instalarFotosConcejales(page)

    await page.addInitScript((inicial) => {
      type EstadoPrueba = Record<string, unknown> & {
        revision: number
        eventos_recientes: Record<string, unknown>[]
      }

      let estadoActual = inicial as EstadoPrueba
      const fuentes: MockEventSourceEventos[] = []

      function publicar(nuevoEstado: EstadoPrueba): void {
        estadoActual = nuevoEstado
        const data = JSON.stringify(estadoActual)
        for (const fuente of fuentes) {
          for (const handler of fuente.listeners.estado ?? []) handler({ type: 'estado', data })
        }
      }

      class MockEventSourceEventos {
        readyState = 1
        listeners: Record<string, ((evento: { type: string; data: string }) => void)[]> = {}
        onopen: ((evento: { type: string }) => void) | null = null
        onerror: ((evento: { type: string }) => void) | null = null
        onmessage: ((evento: { type: string; data: string }) => void) | null = null

        constructor(readonly url: string) {
          fuentes.push(this)
          setTimeout(() => {
            this.onopen?.({ type: 'open' })
            const data = JSON.stringify(estadoActual)
            for (const handler of this.listeners.estado ?? []) handler({ type: 'estado', data })
          }, 5)
        }

        addEventListener(
          tipo: string,
          handler: (evento: { type: string; data: string }) => void,
        ): void {
          this.listeners[tipo] = this.listeners[tipo] ?? []
          this.listeners[tipo].push(handler)
        }

        removeEventListener(
          tipo: string,
          handler: (evento: { type: string; data: string }) => void,
        ): void {
          this.listeners[tipo] = (this.listeners[tipo] ?? []).filter(
            (registrado) => registrado !== handler,
          )
        }

        close(): void {
          this.readyState = 2
        }
      }

      // @ts-expect-error Mock inyectado en el runtime del navegador
      window.EventSource = MockEventSourceEventos

      const fetchOriginal = window.fetch.bind(window)
      window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
        const url =
          typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
        if (url.includes('/api/v1/estado/moderacion')) {
          return new Response(JSON.stringify(estadoActual), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          })
        }
        return fetchOriginal(input, init)
      }

      // El backend simulado agrega un evento con seq mayor y republica la baseline
      // completa, tal como haría el backend real ante actividad institucional.
      ;(window as Window & { publicarEventoNuevo?: (seq: number) => void }).publicarEventoNuevo = (
        seq: number,
      ) => {
        publicar({
          ...estadoActual,
          revision: estadoActual.revision + 1,
          eventos_recientes: [
            ...estadoActual.eventos_recientes,
            {
              seq,
              timestamp: '2026-08-27T11:00:00',
              nivel: 'L3',
              etiqueta: 'SESION',
              codigo_evento: `EVENTO_NUEVO_${seq}`,
              mensaje: `Actividad institucional número ${seq}`,
            },
          ],
        })
      }
    }, estadoInicial)
  }

  test('ordena descendente, mantiene el selector fijo y vuelve al inicio ante un evento nuevo (1920×1080 y 1366×768)', async ({
    page,
  }) => {
    // Cantidad deliberadamente alta: garantiza desbordamiento real del cuadrante.
    const eventos = Array.from({ length: 60 }, (_, indice) => {
      const seq = indice + 1
      return {
        seq,
        timestamp: `2026-08-27T10:${String(indice).padStart(2, '0')}:00`,
        nivel: 'L3',
        etiqueta: 'SESION',
        codigo_evento: `EVENTO_BASE_${seq}`,
        mensaje: `Hecho institucional registrado número ${seq}`,
      }
    })

    const estado = crearEstadoFixture({
      estado_global: 'SESION_ABIERTA',
      sesion: {
        fecha_hora_inicio_preparacion: '2026-08-27T09:00:00Z',
        fecha_hora_apertura: '2026-08-27T09:30:00Z',
        numero_sesion: 41,
        presidencia: 'Dra. Presidencia',
        secretaria_legislativa: 'Sr. Secretaría',
      },
      quorum: { cantidad_presentes: 8, requerido: 7, alcanzado: true },
      // El backend proyecta la baseline en orden ascendente de seq (doc 05, §14).
      eventos_recientes: eventos,
      auditoria: {
        activa: true,
        disponible: true,
        fallado: false,
        cerrado: false,
        motivo: null,
      },
      remapeo: null,
    })

    await configurarBackendEventosMock(page, estado)

    for (const viewport of [
      { width: 1920, height: 1080 },
      { width: 1366, height: 768 },
    ]) {
      await page.setViewportSize(viewport)
      await page.goto('/moderacion/')
      // El shell recién monta los cuadrantes cuando adopta el primer snapshot;
      // el margen amplio cubre el arranque en frío del servidor de desarrollo.
      await page
        .locator('[data-testid="cabecera-moderacion"]')
        .waitFor({ state: 'visible', timeout: 30000 })
      await page
        .locator('[data-testid="panel-eventos"]')
        .waitFor({ state: 'visible', timeout: 30000 })

      const lista = page.locator('[data-testid="lista-eventos"]')
      const selector = page.locator('[data-testid="filtro-eventos"]')
      await expect(lista).toBeVisible()
      await expect(page.locator('[data-testid="evento-reciente"]')).toHaveCount(60)

      // 1. Scroll interno real: el contenido desborda el contenedor del listado.
      const desbordaAlInicio = await lista.evaluate(
        (elemento) => elemento.scrollHeight > elemento.clientHeight,
      )
      expect(desbordaAlInicio).toBe(true)

      // 2. El selector está en la cabecera del panel, fuera del área scrolleable.
      await expect(selector).toBeVisible()
      const selectorDentroDeLista = await lista.evaluate(
        (elemento) => elemento.querySelector('[data-testid="filtro-eventos"]') !== null,
      )
      expect(selectorDentroDeLista).toBe(false)
      const cajaSelectorInicial = await selector.boundingBox()

      // 3. Orden descendente: el evento más nuevo encabeza el listado.
      await expect(page.locator('[data-testid="evento-reciente"]').first()).toContainText(
        'EVENTO_BASE_60',
      )
      await expect(page.locator('[data-testid="evento-reciente"]').last()).toContainText(
        'EVENTO_BASE_1',
      )

      // 4. El operador desplaza la lista hacia eventos anteriores.
      await lista.evaluate((elemento) => {
        elemento.scrollTop = elemento.scrollHeight
      })
      const scrollDesplazado = await lista.evaluate((elemento) => elemento.scrollTop)
      expect(scrollDesplazado).toBeGreaterThan(0)

      // 5. El selector no se desplazó con la lista: sigue visible y en su lugar.
      await expect(selector).toBeVisible()
      const cajaSelectorDesplazado = await selector.boundingBox()
      expect(cajaSelectorInicial).not.toBeNull()
      expect(cajaSelectorDesplazado).not.toBeNull()
      if (cajaSelectorInicial && cajaSelectorDesplazado) {
        expect(Math.abs(cajaSelectorInicial.y - cajaSelectorDesplazado.y)).toBeLessThanOrEqual(1)
      }

      // 6. Llega un evento nuevo: la lista vuelve al inicio y lo deja visible.
      await page.evaluate(() => {
        ;(window as Window & { publicarEventoNuevo?: (seq: number) => void }).publicarEventoNuevo?.(
          61,
        )
      })
      await expect(page.locator('[data-testid="evento-reciente"]')).toHaveCount(61)
      await expect(page.locator('[data-testid="evento-reciente"]').first()).toContainText(
        'EVENTO_NUEVO_61',
      )
      await expect.poll(async () => await lista.evaluate((elemento) => elemento.scrollTop)).toBe(0)

      // 7. El selector sigue operable después del scroll y del evento nuevo.
      await selector.selectOption('L1')
      await expect(page.locator('[data-testid="evento-reciente"]')).toHaveCount(61)
      await selector.selectOption('L3')
      await expect(selector).toHaveValue('L3')

      // 8. Contrato de shell intacto: sin scroll de página en ninguna resolución.
      await verificarGeometriaShellCompleto(page, viewport)
    }
  })
})

/**
 * WP-044 - Correcciones UX de Moderación tras la segunda prueba humana.
 *
 * Todo se mide sobre el navegador real y en las dos resoluciones de referencia:
 *
 * 1. ningún cuadrante conserva una segunda línea descriptiva bajo su título;
 * 2. Q1/SIN_PREPARAR separa los motivos en líneas propias sin ganar scroll;
 * 3. el resultado cerrado domina visualmente y la abstención usa amarillo;
 * 4. Q2 muestra el nombre del archivo una sola vez;
 * 5. el toast de copia se superpone, desaparece y no altera la geometría;
 * 6. Q3 pierde el subencabezado interior, gana altura útil para las bancas y
 *    ofrece `Remapear dispositivo` alineado con el título del cuadrante.
 */
test.describe('WP-044 - Correcciones UX de Moderación', () => {
  const resoluciones = [
    { width: 1366, height: 768 },
    { width: 1920, height: 1080 },
  ]

  /** Devuelve el alto del encabezado y la cantidad de líneas de texto que contiene. */
  async function medirEncabezado(page: Page, testidPanel: string) {
    return page.locator(`[data-testid="${testidPanel}"] > header`).evaluate((encabezado) => ({
      alto: encabezado.getBoundingClientRect().height,
      parrafos: encabezado.querySelectorAll('p').length,
      texto: encabezado.textContent ?? '',
    }))
  }

  test('ningún cuadrante muestra subtítulo bajo su título principal', async ({ page }) => {
    await configurarRutasMock(
      page,
      crearEstadoSesionCompacta({
        orden_del_dia: [],
        eventos_recientes: [],
      }),
    )

    for (const viewport of resoluciones) {
      await page.setViewportSize(viewport)
      await page.goto('/moderacion/')
      await expect(page.locator('[data-testid="panel-sesion-votacion"]')).toBeVisible()

      for (const testid of [
        'panel-sesion-votacion',
        'panel-orden-del-dia',
        'panel-recinto-palabra',
        'panel-eventos',
      ]) {
        const medicion = await medirEncabezado(page, testid)
        expect(medicion.parrafos).toBe(0)
      }

      const q2 = await medirEncabezado(page, 'panel-orden-del-dia')
      expect(q2.texto).not.toContain('Carga CSV compacta')
      expect(q2.texto).not.toContain('Puntos confirmados por backend')

      const q3 = await medirEncabezado(page, 'panel-recinto-palabra')
      expect(q3.texto).not.toContain('coordinación de dispositivos')

      const q4 = await medirEncabezado(page, 'panel-eventos')
      expect(q4.texto).not.toContain('Registro de actividad')

      await expect(page.locator('[data-testid="panel-recinto-palabra"]')).not.toContainText(
        'Distribución de bancas',
      )
      await expect(page.locator('[data-testid="gestion-palabra"]')).not.toContainText(
        'Cola FIFO autoritativa',
      )
      await verificarGeometriaShellCompleto(page, viewport)
    }
  })

  test('Q1 SIN_PREPARAR muestra un requisito por línea y sigue sin scroll', async ({ page }) => {
    await configurarRutasMock(
      page,
      crearEstadoFixture({
        capacidades: {
          ...crearEstadoFixture().capacidades,
          preparar_sala: {
            habilitada: false,
            motivos: ['AUDITORIA_NO_DISPONIBLE', 'PADRON_NO_DISPONIBLE'],
          },
        },
      }),
    )

    for (const viewport of resoluciones) {
      await page.setViewportSize(viewport)
      await page.goto('/moderacion/')

      const motivos = page.locator('[data-testid="motivo-preparar-sala"]')
      await expect(motivos).toHaveCount(2)

      // Dos líneas distintas implican dos coordenadas verticales distintas.
      const cajaPrimera = await motivos.nth(0).boundingBox()
      const cajaSegunda = await motivos.nth(1).boundingBox()
      expect(cajaPrimera).not.toBeNull()
      expect(cajaSegunda).not.toBeNull()
      expect(cajaSegunda!.y).toBeGreaterThan(cajaPrimera!.y + cajaPrimera!.height - 1)

      await verificarQ1SinScroll(page)
      await verificarGeometriaShellCompleto(page, viewport)
    }
  })

  test('Q1 jerarquiza el resultado cerrado y pinta la abstención de amarillo', async ({ page }) => {
    await configurarRutasMock(
      page,
      crearEstadoSesionCompacta({
        votacion: crearVotacionCompacta({
          estado_recepcion: 'CERRADA',
          resultado: 'APROBADA',
          fecha_hora_cierre: '2026-08-30T10:00:10Z',
          fecha_hora_resultado: '2026-08-30T10:00:10Z',
        }),
      }),
    )

    for (const viewport of resoluciones) {
      await page.setViewportSize(viewport)
      await page.goto('/moderacion/')

      const resultado = page.locator('[data-testid="estado-votacion"]')
      await expect(resultado).toContainText('APROBADA')
      await expect(resultado).toHaveAttribute('data-jerarquia', 'principal')

      const tamanos = await page.evaluate(() => {
        const leer = (selector: string) => {
          const nodo = document.querySelector(selector)
          return nodo ? parseFloat(getComputedStyle(nodo).fontSize) : 0
        }
        return {
          resultado: leer('[data-testid="estado-votacion"]'),
          conteo: leer('[data-testid="conteo-abstenciones"]'),
        }
      })
      expect(tamanos.resultado).toBeGreaterThan(tamanos.conteo)

      // La familia amarilla se comprueba sobre el color realmente pintado, no sobre la
      // clase: Tailwind v4 expresa los colores en oklch, así que se resuelven a RGB
      // dibujándolos en un canvas.
      const componentes = await page
        .locator('[data-testid="conteo-abstenciones"]')
        .evaluate((nodo) => {
          const contexto = document.createElement('canvas').getContext('2d')
          if (!contexto) return null
          contexto.fillStyle = getComputedStyle(nodo).color
          contexto.fillRect(0, 0, 1, 1)
          const datos = contexto.getImageData(0, 0, 1, 1).data
          return { rojo: datos[0] ?? 0, verde: datos[1] ?? 0, azul: datos[2] ?? 0 }
        })
      expect(componentes).not.toBeNull()
      // Amarillo institucional: rojo y verde altos, azul claramente menor.
      expect(componentes!.rojo).toBeGreaterThan(componentes!.azul + 40)
      expect(componentes!.verde).toBeGreaterThan(componentes!.azul + 40)

      await verificarQ1SinScroll(page)
      await verificarGeometriaShellCompleto(page, viewport)
    }
  })

  test('Q2 acusa la copia con un toast superpuesto que no mueve la lista', async ({ page }) => {
    await configurarOrdenDelDiaMock(page, crearEstadoSesionCompacta())

    for (const viewport of resoluciones) {
      await page.setViewportSize(viewport)
      await page.goto('/moderacion/')

      const panel = page.locator('[data-testid="panel-orden-del-dia"]')
      await panel.locator('[data-testid="input-archivo-orden-dia"]').setInputFiles({
        name: 'orden-sesion-44.csv',
        mimeType: 'text/csv',
        buffer: Buffer.from('nro_votacion,tipo,tema,tipo_mayoria,factor,base'),
      })
      await expect(panel).not.toContainText('Seleccionado:')
      await expect(panel).not.toContainText('orden-sesion-44.csv')
      await panel.locator('[data-testid="btn-cargar-orden-dia"]').click()
      await expect(panel.locator('[data-testid="punto-orden-dia"]')).toHaveCount(2)

      const lista = panel.locator('[data-testid="lista-orden-dia"]')
      const cuerpo = panel.locator('[data-testid="cuerpo-panel"]')
      const cajaListaAntes = await lista.boundingBox()
      const alturaCuerpoAntes = await cuerpo.evaluate((nodo) => nodo.scrollHeight)

      await panel.locator('[data-testid="punto-orden-dia"]').first().click()
      const toast = panel.locator('[data-testid="toast-punto-copiado"]')
      await expect(toast).toHaveCount(1)
      await expect(toast).toContainText('copiado al borrador')

      // El precargado de Q1 sigue funcionando exactamente igual que antes.
      await expect(page.locator('[data-testid="input-numero-votacion"]')).toHaveValue('1')
      // Q1 no repite el aviso: el único acuse vive en Q2.
      await expect(page.locator('[data-testid="aviso-votacion"]')).toHaveCount(0)

      const cajaListaDurante = await lista.boundingBox()
      const alturaCuerpoDurante = await cuerpo.evaluate((nodo) => nodo.scrollHeight)
      expect(Math.abs(cajaListaDurante!.y - cajaListaAntes!.y)).toBeLessThanOrEqual(1)
      expect(Math.abs(cajaListaDurante!.height - cajaListaAntes!.height)).toBeLessThanOrEqual(1)
      expect(Math.abs(alturaCuerpoDurante - alturaCuerpoAntes)).toBeLessThanOrEqual(1)

      // El acuse es efímero: aproximadamente un segundo después ya no existe.
      await expect(toast).toHaveCount(0, { timeout: 4000 })
      const cajaListaDespues = await lista.boundingBox()
      expect(Math.abs(cajaListaDespues!.y - cajaListaAntes!.y)).toBeLessThanOrEqual(1)
      await verificarGeometriaShellCompleto(page, viewport)
    }
  })

  test('Q3 mueve Remapear al encabezado y devuelve altura a las bancas', async ({ page }) => {
    const estado = crearEstadoFixture({
      estado_global: 'SESION_ABIERTA',
      sesion: {
        fecha_hora_inicio_preparacion: '2026-08-30T09:00:00Z',
        fecha_hora_apertura: '2026-08-30T09:30:00Z',
        numero_sesion: 44,
        presidencia: 'Presidencia de prueba',
        secretaria_legislativa: 'Secretaría de prueba',
      },
      configuracion: { filas_bancas: [3, 4, 5] },
      quorum: { cantidad_presentes: 8, requerido: 7, alcanzado: true },
      palabra: {
        orador: { dni: '30000001', nombre: 'Concejal01', apellido: 'Apellido01', banca: 1 },
        cola: Array.from({ length: 11 }, (_, indice) => {
          const banca = indice + 2
          const pad = String(banca).padStart(2, '0')
          return {
            dni: `300000${pad}`,
            nombre: `Concejal${pad}`,
            apellido: `Apellido${pad}`,
            banca,
          }
        }),
      },
    })
    await configurarRutasMock(page, estado)

    for (const viewport of resoluciones) {
      await page.setViewportSize(viewport)
      await page.goto('/moderacion/')

      const panel = page.locator('[data-testid="panel-recinto-palabra"]')
      const encabezado = panel.locator('> header')
      const boton = page.locator('[data-testid="btn-desplegar-remapeo"]')
      await expect(boton).toBeVisible()

      // El botón comparte la franja del título y queda alineado a la derecha.
      const cajaEncabezado = await encabezado.boundingBox()
      const cajaBoton = await boton.boundingBox()
      const cajaTitulo = await encabezado.locator('h2').boundingBox()
      expect(cajaBoton!.y).toBeGreaterThanOrEqual(cajaEncabezado!.y - 1)
      expect(cajaBoton!.y + cajaBoton!.height).toBeLessThanOrEqual(
        cajaEncabezado!.y + cajaEncabezado!.height + 1,
      )
      expect(cajaBoton!.x).toBeGreaterThan(cajaTitulo!.x + cajaTitulo!.width)
      expect(cajaBoton!.x + cajaBoton!.width).toBeLessThanOrEqual(
        cajaEncabezado!.x + cajaEncabezado!.width + 1,
      )

      // El área de bancas ya no gasta altura en un subencabezado propio.
      const areaBancas = page.locator('[data-testid="area-bancas-moderacion"]')
      const grilla = page.locator('[data-testid="grilla-recinto"]')
      const cajaArea = await areaBancas.boundingBox()
      const cajaGrilla = await grilla.boundingBox()
      expect(cajaGrilla!.height / cajaArea!.height).toBeGreaterThan(0.9)
      await expect(panel).not.toContainText('Distribución de bancas')
      await expect(page.locator('[data-testid="orador-actual-texto"]')).toHaveCount(0)

      // La cola sigue siendo la única región desplazable de la columna de palabra.
      // Ya no se exige desbordamiento: con la altura recuperada la cola puede entrar
      // completa, y eso es una mejora, no una regresión.
      const medidasCola = await page
        .locator('[data-testid="contenedor-scroll-cola-palabra"]')
        .evaluate((cola) => ({
          altoVisible: cola.clientHeight,
          altoContenido: cola.scrollHeight,
          overflowY: getComputedStyle(cola).overflowY,
        }))
      expect(['auto', 'scroll']).toContain(medidasCola.overflowY)
      expect(medidasCola.altoVisible).toBeGreaterThan(0)
      const medidasColumna = await page
        .locator('[data-testid="columna-palabra-moderacion"]')
        .evaluate((columna) => ({
          altoVisible: columna.clientHeight,
          altoContenido: columna.scrollHeight,
        }))
      expect(medidasColumna.altoContenido).toBeLessThanOrEqual(medidasColumna.altoVisible + 1)
      await expect(page.locator('[data-testid="btn-otorgar-palabra"]')).toBeVisible()
      await expect(page.locator('[data-testid="btn-quitar-palabra"]')).toBeVisible()

      // Abrir el flujo desde el encabezado sigue mostrando el remapeo completo.
      await boton.click()
      await expect(page.locator('[data-testid="gestion-remapeo"]')).toBeVisible()
      await page.locator('[data-testid="btn-cerrar-remapeo"]').click()
      await expect(page.locator('[data-testid="gestion-remapeo"]')).toHaveCount(0)

      await verificarGeometriaShellCompleto(page, viewport)
    }
  })
})

/**
 * WP-048 - Compactación operativa de Q1 y limpieza de Q2.
 *
 * Demuestra con medidas reales del DOM, en 1366×768 y 1920×1080, que:
 *
 * 1. las dos acciones institucionales de la sesión se operan desde el encabezado del
 *    cuadrante y Q1 ya no reserva una franja interior para repetir `Sesión Nº N`;
 * 2. durante PREPARANDO cada requisito de apertura ocupa su propio renglón;
 * 3. el cuerpo de la votación no informa de forma permanente orador ni cola, pero la
 *    advertencia CA-062 al abrir con palabra pendiente se conserva íntegra;
 * 4. un resultado anterior convive con el formulario completo de la votación siguiente
 *    —incluidos los campos condicionales de mayoría especial— sin scroll interno y con
 *    todos los controles dentro del bounding box de Q1;
 * 5. la demanda vertical del conjunto cae muy por debajo de la baseline medida antes del
 *    cambio, que a 1366×768 pedía 333 px de contenido para 323 px disponibles;
 * 6. Q2 no deja ninguna fila informativa después de una carga exitosa.
 */
test.describe('WP-048 - Q1 compacto y Q2 sin acuse persistente', () => {
  const resoluciones = [
    { width: 1366, height: 768 },
    { width: 1920, height: 1080 },
  ]

  /**
   * Demanda vertical del contenido de Q1 en el escenario crítico (resultado anterior más
   * formulario nuevo) medida a 1366×768 sobre el código previo a WP-048: 333 px de
   * contenido para 323 px disponibles, es decir un recorte real de 10 px.
   *
   * El objetivo aprobado es reducir aproximadamente un 30 %. Se exige aquí un techo del
   * 75 % de esa baseline para dejar margen a variaciones de fuente entre entornos sin
   * volver la prueba complaciente: la medición efectiva del cambio quedó en 234 px.
   */
  const DEMANDA_VERTICAL_BASELINE = 333

  /** Palabra pendiente real: un orador en uso y un pedido en cola. */
  const palabraPendiente = {
    orador: { dni: '30000001', nombre: 'Ada', apellido: 'Lovelace', banca: 1 },
    cola: [{ dni: '30000002', nombre: 'Grace', apellido: 'Hopper', banca: 2 }],
  }

  /**
   * Suma la altura que realmente pide el contenido del cuerpo de Q1.
   *
   * No alcanza con leer el alto de los contenedores: tanto la vista de sesión abierta como
   * `GestionVotacion` son cajas flexibles acotadas por el shell, y su `scrollHeight` deja
   * de crecer cuando el contenido ya no entra. Por eso la medición desciende por esos
   * contenedores y suma la altura de sus hijos reales más los espacios declarados entre
   * ellos: esa suma es la demanda que el cuadrante debe absorber sin recortar nada.
   */
  async function medirDemandaVerticalQ1(page: Page): Promise<{
    demanda: number
    disponible: number
  }> {
    return page.evaluate(() => {
      const cuerpo = document.querySelector<HTMLElement>(
        '[data-testid="panel-sesion-votacion"] [data-testid="cuerpo-panel"]',
      )!
      // Contenedores cuyo alto está limitado por el shell y no expresa la demanda real.
      const contenedoresFlexibles = ['vista-sesion-abierta', 'gestion-votacion']

      function demandaDe(contenedor: HTMLElement): number {
        const separacion = Number.parseFloat(getComputedStyle(contenedor).rowGap) || 0
        const hijos = Array.from(contenedor.children) as HTMLElement[]
        const suma = hijos.reduce((total, hijo) => {
          const testid = hijo.getAttribute('data-testid') ?? ''
          return (
            total + (contenedoresFlexibles.includes(testid) ? demandaDe(hijo) : hijo.scrollHeight)
          )
        }, 0)
        return suma + separacion * Math.max(hijos.length - 1, 0)
      }

      const vista =
        cuerpo.querySelector<HTMLElement>('[data-testid="vista-sesion-abierta"]') ??
        (cuerpo.firstElementChild as HTMLElement)
      return { demanda: Math.round(demandaDe(vista)), disponible: cuerpo.clientHeight }
    })
  }

  /** Comprueba que un control quede íntegramente dentro del bounding box de Q1. */
  async function verificarControlContenido(page: Page, testid: string): Promise<void> {
    const panel = page.locator('[data-testid="panel-sesion-votacion"]')
    const control = page.locator(`[data-testid="${testid}"]`)
    await expect(control).toBeVisible()
    const cajaPanel = await panel.boundingBox()
    const cajaControl = await control.boundingBox()
    expect(cajaPanel).not.toBeNull()
    expect(cajaControl).not.toBeNull()
    expect(cajaControl!.y).toBeGreaterThanOrEqual(cajaPanel!.y - 1)
    expect(cajaControl!.x).toBeGreaterThanOrEqual(cajaPanel!.x - 1)
    expect(cajaControl!.y + cajaControl!.height).toBeLessThanOrEqual(
      cajaPanel!.y + cajaPanel!.height + 1,
    )
    expect(cajaControl!.x + cajaControl!.width).toBeLessThanOrEqual(
      cajaPanel!.x + cajaPanel!.width + 1,
    )
  }

  for (const viewport of resoluciones) {
    test(`acciones en encabezado y sin franja de número a ${viewport.width}×${viewport.height}`, async ({
      page,
    }) => {
      await configurarRutasMock(page, crearEstadoSesionCompacta())
      await page.setViewportSize(viewport)
      await page.goto('/moderacion/')
      await expect(page.locator('[data-testid="formulario-votacion"]')).toBeVisible()

      const panel = page.locator('[data-testid="panel-sesion-votacion"]')
      const encabezado = panel.locator('> header')
      const cuerpo = panel.locator('[data-testid="cuerpo-panel"]')

      // Las dos acciones institucionales viven en el encabezado del cuadrante.
      await expect(encabezado.locator('[data-testid="btn-editar-autoridades"]')).toBeVisible()
      await expect(encabezado.locator('[data-testid="btn-cerrar-sesion"]')).toBeVisible()
      await expect(cuerpo.locator('[data-testid="btn-editar-autoridades"]')).toHaveCount(0)
      await expect(cuerpo.locator('[data-testid="btn-cerrar-sesion"]')).toHaveCount(0)

      // El badge de estado del recinto permanece en Q1: tras WP-047 es su única sede.
      await expect(encabezado).toContainText('Sesión activa')

      // Ninguna franja interior repite el número de sesión, que ya publica la cabecera.
      await expect(page.locator('[data-testid="franja-sesion-abierta"]')).toHaveCount(0)
      await expect(page.locator('[data-testid="numero-sesion-inmutable"]')).toHaveCount(0)
      await expect(panel).not.toContainText('Sesión Nº 42')
      await expect(page.locator('[data-testid="cabecera-numero-sesion"]')).toHaveText(
        'Sesión Nº 42',
      )

      await verificarQ1SinScroll(page)
      await verificarControlContenido(page, 'btn-editar-autoridades')
      await verificarControlContenido(page, 'btn-cerrar-sesion')
      await verificarGeometriaShellCompleto(page, viewport)
    })

    test(`requisitos de apertura en renglones separados a ${viewport.width}×${viewport.height}`, async ({
      page,
    }) => {
      await configurarRutasMock(
        page,
        crearEstadoFixture({
          estado_global: 'PREPARANDO',
          preparacion: {
            fecha_hora_inicio: '2026-08-29T09:30:00Z',
            numero_sesion: 42,
            presidencia: '',
            secretaria_legislativa: '',
          },
          quorum: { cantidad_presentes: 5, requerido: 7, alcanzado: false },
          capacidades: {
            ...crearEstadoFixture().capacidades,
            preparar_sala: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
            actualizar_preparacion: { habilitada: true, motivos: [] },
            cancelar_preparacion: { habilitada: true, motivos: [] },
            abrir_sesion: {
              habilitada: false,
              motivos: [
                'QUORUM_INSUFICIENTE',
                'PRESIDENCIA_REQUERIDA',
                'SECRETARIA_LEGISLATIVA_REQUERIDA',
              ],
            },
          },
        }),
      )
      await page.setViewportSize(viewport)
      await page.goto('/moderacion/')

      const renglones = page.locator('[data-testid="motivo-abrir-sesion"]')
      await expect(renglones).toHaveCount(3)

      // Cada requisito ocupa su propia línea: distinta coordenada Y, sin concatenación.
      const cajas = await renglones.evaluateAll((elementos) =>
        elementos.map((elemento) => Math.round(elemento.getBoundingClientRect().y)),
      )
      expect(new Set(cajas).size).toBe(3)
      await expect(page.locator('[data-testid="motivos-abrir-sesion"]')).not.toContainText(' · ')

      await verificarQ1SinScroll(page)
      await verificarGeometriaShellCompleto(page, viewport)
    })

    test(`resultado previo y formulario completo conviven a ${viewport.width}×${viewport.height}`, async ({
      page,
    }, testInfo) => {
      await configurarRutasMock(
        page,
        crearEstadoSesionCompacta({
          votacion: crearVotacionCompacta({
            estado_recepcion: 'CERRADA',
            resultado: 'APROBADA',
            fecha_hora_cierre: '2026-08-29T10:00:10Z',
            fecha_hora_resultado: '2026-08-29T10:00:10Z',
          }),
          palabra: palabraPendiente,
        }),
      )
      await page.setViewportSize(viewport)
      await page.goto('/moderacion/')

      // El resultado conserva la jerarquía dominante del cuadrante.
      const resultado = page.locator('[data-testid="estado-votacion"]')
      await expect(resultado).toHaveText('APROBADA')
      await expect(resultado).toHaveAttribute('data-jerarquia', 'principal')

      // Los conteos se leen en una sola fila: sus cuatro cajas comparten coordenada Y.
      const conteos = page.locator('[data-testid="conteos-votacion"]')
      await expect(conteos).toBeVisible()
      const filas = await conteos.evaluate((elemento) => {
        const hijos = Array.from(elemento.children) as HTMLElement[]
        return {
          cantidad: hijos.length,
          coordenadas: new Set(hijos.map((hijo) => Math.round(hijo.getBoundingClientRect().y)))
            .size,
          alto: Math.round(elemento.getBoundingClientRect().height),
        }
      })
      expect(filas.cantidad).toBe(4)
      expect(filas.coordenadas).toBe(1)
      expect(filas.alto).toBeLessThanOrEqual(28)

      // Q1 no lista votos individuales aunque el DTO los proyecte.
      await expect(page.locator('[data-testid="votos-individuales"]')).toHaveCount(0)
      await expect(page.locator('[data-testid="panel-sesion-votacion"]')).not.toContainText(
        'No debe renderizarse',
      )

      // El formulario completo de la votación siguiente sigue accesible sin scroll.
      for (const control of [
        'input-numero-votacion',
        'select-tipo-votacion',
        'radio-mayoria-simple',
        'radio-mayoria-especial',
        'input-tema-votacion',
        'btn-abrir-votacion',
        'btn-limpiar-borrador',
      ]) {
        await verificarControlContenido(page, control)
      }

      await verificarQ1SinScroll(page)

      // Demanda vertical con mayoría simple, que es el escenario de la baseline medida.
      const medicion = await medirDemandaVerticalQ1(page)
      expect(medicion.demanda).toBeLessThanOrEqual(medicion.disponible)
      if (viewport.height === 768) {
        expect(medicion.demanda).toBeLessThanOrEqual(Math.round(DEMANDA_VERTICAL_BASELINE * 0.75))
      }

      // Los campos condicionales de mayoría especial también entran completos.
      await page.locator('[data-testid="radio-mayoria-especial"]').check()
      await expect(page.locator('[data-testid="campos-mayoria-especial"]')).toBeVisible()
      await verificarControlContenido(page, 'input-factor-mayoria')
      await verificarControlContenido(page, 'select-base-mayoria')
      await verificarControlContenido(page, 'btn-abrir-votacion')
      await verificarQ1SinScroll(page)

      const medicionEspecial = await medirDemandaVerticalQ1(page)
      expect(medicionEspecial.demanda).toBeLessThanOrEqual(medicionEspecial.disponible)

      // La captura queda adjunta al reporte reproducible de Playwright como evidencia
      // visual de la compactación en la resolución exacta que se está midiendo.
      await testInfo.attach(`wp048-${viewport.width}x${viewport.height}.png`, {
        body: await page.screenshot({ fullPage: true }),
        contentType: 'image/png',
      })

      await verificarGeometriaShellCompleto(page, viewport)
    })

    test(`la palabra pendiente no ocupa el cuerpo pero conserva su advertencia a ${viewport.width}×${viewport.height}`, async ({
      page,
    }) => {
      await configurarRutasMock(
        page,
        crearEstadoSesionCompacta({
          votacion: crearVotacionCompacta(),
          palabra: palabraPendiente,
          capacidades: {
            ...crearCapacidadesSesionCompacta(),
            abrir_votacion: { habilitada: false, motivos: ['VOTACION_PENDIENTE'] },
            finalizar_votacion: { habilitada: true, motivos: [] },
          },
        }),
      )
      await page.setViewportSize(viewport)
      await page.goto('/moderacion/')
      await expect(page.locator('[data-testid="btn-finalizar-votacion"]')).toBeVisible()

      // Con una votación en curso y palabra pendiente, Q1 no informa orador ni cola.
      await expect(page.locator('[data-testid="palabra-durante-votacion"]')).toHaveCount(0)
      await expect(page.locator('[data-testid="panel-sesion-votacion"]')).not.toContainText(
        'Ada Lovelace',
      )
      await expect(page.locator('[data-testid="panel-sesion-votacion"]')).not.toContainText(
        'en cola',
      )
      // La información de palabra sigue disponible en su cuadrante propio.
      await expect(page.locator('[data-testid="badge-cola-palabra"]')).toContainText('1 en cola')

      await verificarQ1SinScroll(page)
      await verificarGeometriaShellCompleto(page, viewport)
    })

    test(`abrir votación con palabra pendiente sigue advirtiendo a ${viewport.width}×${viewport.height}`, async ({
      page,
    }) => {
      await configurarRutasMock(page, crearEstadoSesionCompacta({ palabra: palabraPendiente }))
      await page.setViewportSize(viewport)
      await page.goto('/moderacion/')

      await page.locator('[data-testid="input-numero-votacion"]').fill('12')
      await page.locator('[data-testid="input-tema-votacion"]').fill('Presupuesto anual')
      await page.locator('[data-testid="btn-abrir-votacion"]').click()

      const dialogo = page.locator('[data-testid="dialogo-confirmacion-apertura"]')
      await expect(dialogo).toBeVisible()
      await expect(dialogo).toHaveAttribute('role', 'dialog')
      await expect(dialogo).toContainText('Ada Lovelace')

      // Cancelar continúa siendo la opción segura: no abre nada.
      await page.locator('[data-testid="btn-cancelar-apertura"]').click()
      await expect(dialogo).toHaveCount(0)
      await expect(page.locator('[data-testid="vista-votacion-proyectada"]')).toHaveCount(0)

      await verificarQ1SinScroll(page)
    })

    test(`Q2 no deja fila informativa tras una carga exitosa a ${viewport.width}×${viewport.height}`, async ({
      page,
    }) => {
      await configurarOrdenDelDiaMock(page, crearEstadoSesionCompacta())
      await page.setViewportSize(viewport)
      await page.goto('/moderacion/')

      const panel = page.locator('[data-testid="panel-orden-del-dia"]')
      const entrada = panel.locator('[data-testid="input-archivo-orden-dia"]')
      await expect(entrada).toBeVisible()
      await entrada.setInputFiles({
        name: 'orden-sesion-42.csv',
        mimeType: 'text/csv',
        buffer: Buffer.from(
          'nro_votacion,tipo,tema,tipo_mayoria,factor,base\n1,Proyecto,Tema,SIMPLE,0,VOTOS_COMPUTABLES',
        ),
      })
      await panel.locator('[data-testid="btn-cargar-orden-dia"]').click()

      // La colección proyectada es la única confirmación: no hay acuse de texto.
      await expect(panel.locator('[data-testid="punto-orden-dia"]')).toHaveCount(2)
      await expect(panel.locator('[data-testid="aviso-orden-dia"]')).toHaveCount(0)
      await expect(panel).not.toContainText('Archivo enviado')
      await expect(panel).not.toContainText('La lista cambiará')

      // El toast de copiado de punto no forma parte de esta corrección y sigue vigente.
      await panel.locator('[data-testid="punto-orden-dia"]').first().click()
      await expect(panel.locator('[data-testid="toast-punto-copiado"]')).toContainText(
        'copiado al borrador',
      )

      await verificarGeometriaShellCompleto(page, viewport)
    })
  }
})

/**
 * Evidencia geométrica del refinamiento visual de Moderación (WP-054).
 *
 * Dos objetivos independientes:
 *
 * 1. La cabecera reorganizada debe seguir siendo una sola línea de la misma
 *    altura que la baseline WP-047 (≤ 32 px, `nowrap`, sin desborde), con
 *    autoridades, tiempo, fecha y conexión agrupados en el sector derecho y con
 *    los dos rótulos explícitos visibles.
 * 2. La geometría de `BancaConcejal.vue` debe auditarse contra las imágenes
 *    canónicas reales. El WP obliga a decidir por evidencia: sólo se corrige si
 *    los bounding boxes prueban clipping o desborde. Esta prueba es esa
 *    auditoría y queda versionada como regresión permanente.
 */
test.describe('WP-054 - Cabecera derecha y auditoría geométrica de bancas', () => {
  // Misma zona deliberadamente distinta de las marcas naive del backend.
  test.use({ timezoneId: 'America/Los_Angeles' })

  function crearEstadoWp054() {
    return crearEstadoFixture({
      generado_en: '2026-08-31T10:30:00',
      estado_global: 'SESION_ABIERTA',
      sesion: {
        fecha_hora_inicio_preparacion: '2026-08-31T09:45:00',
        fecha_hora_apertura: '2026-08-31T10:00:00',
        numero_sesion: 47,
        presidencia: 'Dra. María Elena Walsh',
        secretaria_legislativa: 'Lic. Juan Gómez',
      },
      quorum: { cantidad_presentes: 9, requerido: 7, alcanzado: true },
    })
  }

  for (const viewport of [
    { width: 1366, height: 768 },
    { width: 1920, height: 1080 },
  ]) {
    test(`agrupa autoridades y tiempo a la derecha en ${viewport.width}×${viewport.height}`, async ({
      page,
    }) => {
      await configurarRutasMock(page, crearEstadoWp054())
      await page.setViewportSize(viewport)
      await page.goto('/moderacion/')
      await page.getByTestId('cabecera-moderacion').waitFor()

      const caja = async (testid: string) => (await page.getByTestId(testid).boundingBox())!
      const cajaCabecera = await caja('cabecera-moderacion')
      const cajaQuorum = await caja('cabecera-quorum')
      const cajaPresidencia = await caja('cabecera-presidencia')
      const cajaSecretaria = await caja('cabecera-secretaria')
      const cajaTiempo = await caja('cabecera-tiempo-sesion')
      const cajaFecha = await caja('cabecera-fecha-hora')
      const cajaConexion = await caja('estado-conexion')
      // WP-067 sumó el acceso de ayuda al final del mismo grupo, así que es él —y ya no
      // el indicador de conexión— quien debe quedar contra el borde derecho.
      const cajaAyuda = await caja('acceso-manual')

      // 1 · Sector derecho: el orden horizontal es autoridades → tiempo → fecha
      // → conexión → ayuda, y todo el grupo empieza después del bloque institucional.
      const sectorDerecho = [
        cajaPresidencia,
        cajaSecretaria,
        cajaTiempo,
        cajaFecha,
        cajaConexion,
        cajaAyuda,
      ]
      expect(cajaQuorum.x + cajaQuorum.width).toBeLessThanOrEqual(cajaPresidencia.x)
      for (let indice = 1; indice < sectorDerecho.length; indice += 1) {
        expect(sectorDerecho[indice - 1]!.x + sectorDerecho[indice - 1]!.width).toBeLessThanOrEqual(
          sectorDerecho[indice]!.x + 1,
        )
      }

      // 2 · El grupo está efectivamente pegado al borde derecho: entre el último
      // elemento y el límite de la cabecera sólo queda su padding horizontal.
      const bordeDerechoCabecera = cajaCabecera.x + cajaCabecera.width
      expect(bordeDerechoCabecera - (cajaAyuda.x + cajaAyuda.width)).toBeLessThanOrEqual(12)

      // 3 · Una sola línea: todos los elementos comparten renglón con el título.
      const cajaTitulo = await page.locator('[data-testid="cabecera-moderacion"] h1').boundingBox()
      for (const elemento of [cajaQuorum, ...sectorDerecho]) {
        const centro = elemento.y + elemento.height / 2
        const centroTitulo = cajaTitulo!.y + cajaTitulo!.height / 2
        expect(Math.abs(centro - centroTitulo)).toBeLessThanOrEqual(2)
      }

      // 4 · Altura y contención: la baseline WP-047 no se degrada.
      expect(cajaCabecera.height).toBeLessThanOrEqual(32)
      const contencion = await page.getByTestId('cabecera-moderacion').evaluate((cabecera) => ({
        flexWrap: getComputedStyle(cabecera).flexWrap,
        altoVisible: cabecera.clientHeight,
        altoContenido: cabecera.scrollHeight,
        anchoVisible: cabecera.clientWidth,
        anchoContenido: cabecera.scrollWidth,
      }))
      expect(contencion.flexWrap).toBe('nowrap')
      expect(contencion.altoContenido).toBeLessThanOrEqual(contencion.altoVisible + 1)
      expect(contencion.anchoContenido).toBeLessThanOrEqual(contencion.anchoVisible + 1)

      // 5 · Rótulos explícitos efectivamente visibles.
      await expect(page.getByTestId('cabecera-tiempo-sesion')).toContainText('Tiempo de sesión')
      await expect(page.getByTestId('cabecera-fecha-hora')).toContainText('Fecha')

      await verificarGeometriaShellCompleto(page, viewport)
    })

    test(`audita el clipping de las bancas de Q3 en ${viewport.width}×${viewport.height}`, async ({
      page,
    }) => {
      await configurarRutasMock(page, crearEstadoWp054())
      await page.setViewportSize(viewport)
      await page.goto('/moderacion/')
      await expect(page.getByTestId('banca-concejal')).toHaveCount(12)

      // Las imágenes reales deben estar cargadas antes de medir cualquier recorte.
      await expect(page.getByTestId('imagen-concejal').first()).toBeVisible()
      await page.waitForFunction(() =>
        Array.from(document.querySelectorAll('img')).every((imagen) => imagen.complete),
      )

      const auditoria = await page.getByTestId('banca-concejal').evaluateAll((tarjetas) =>
        tarjetas.map((tarjeta) => {
          const imagen = tarjeta.querySelector(
            '[data-testid="imagen-concejal"]',
          ) as HTMLImageElement
          const area = tarjeta.querySelector('.area-imagen') as HTMLElement
          const cajaTarjeta = tarjeta.getBoundingClientRect()
          const cajaArea = area.getBoundingClientRect()
          const cajaImagen = imagen.getBoundingClientRect()
          return {
            banca: tarjeta.getAttribute('data-banca'),
            ajuste: getComputedStyle(imagen).objectFit,
            cargada: imagen.naturalWidth > 0,
            // Contención real, medida en píxeles, no deducida del CSS.
            dentroDelArea:
              cajaImagen.left >= cajaArea.left - 1 &&
              cajaImagen.right <= cajaArea.right + 1 &&
              cajaImagen.top >= cajaArea.top - 1 &&
              cajaImagen.bottom <= cajaArea.bottom + 1,
            dentroDeLaTarjeta:
              cajaImagen.left >= cajaTarjeta.left - 1 &&
              cajaImagen.right <= cajaTarjeta.right + 1 &&
              cajaImagen.top >= cajaTarjeta.top - 1 &&
              cajaImagen.bottom <= cajaTarjeta.bottom + 1,
            // Un contenido mayor que la caja visible sería recorte encubierto.
            desbordeHorizontal: tarjeta.scrollWidth - tarjeta.clientWidth,
            desbordeVertical: tarjeta.scrollHeight - tarjeta.clientHeight,
            tamano: { ancho: cajaTarjeta.width, alto: cajaTarjeta.height },
          }
        }),
      )

      expect(auditoria).toHaveLength(12)
      for (const banca of auditoria) {
        // `contain` es la garantía de que el bitmap institucional entra entero:
        // incluye el nombre y los logos dibujados dentro de la propia imagen.
        expect(banca.ajuste).toBe('contain')
        expect(banca.cargada).toBe(true)
        expect(banca.dentroDelArea).toBe(true)
        expect(banca.dentroDeLaTarjeta).toBe(true)
        expect(banca.desbordeHorizontal).toBeLessThanOrEqual(1)
        expect(banca.desbordeVertical).toBeLessThanOrEqual(1)
      }

      // Tarjetas uniformes: ninguna banca queda más chica que las demás por un
      // recorte propio de su contenido.
      for (const banca of auditoria) {
        expect(banca.tamano.ancho).toBeCloseTo(auditoria[0]!.tamano.ancho, 0)
        expect(banca.tamano.alto).toBeCloseTo(auditoria[0]!.tamano.alto, 0)
      }

      await verificarGeometriaShellCompleto(page, viewport)
    })
  }
})

test.describe('WP-051 - Feedback operativo y ciclo de votación legible', () => {
  /**
   * Recorrido operativo principal con la política de feedback aprobada por WP-051.
   *
   * Se ejercita el ciclo completo sobre el shell real: abrir la votación, finalizarla
   * manualmente, resolver el empate y volver al formulario. En cada paso se verifica que la
   * pantalla no acumule acuses puramente técnicos, que la instrucción de desempate sea
   * inequívoca y que la pérdida de quórum se explique en clave de votación.
   */
  test('el ciclo completo no deja acuses técnicos y explica empate y quórum', async ({ page }) => {
    const capacidades = {
      preparar_sala: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      actualizar_preparacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      cancelar_preparacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      abrir_sesion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      actualizar_sesion: { habilitada: true, motivos: [] },
      cerrar_sesion: { habilitada: true, motivos: [] },
      cargar_orden_del_dia: { habilitada: true, motivos: [] },
      descartar_orden_del_dia: { habilitada: true, motivos: [] },
      abrir_votacion: { habilitada: true, motivos: [] },
      finalizar_votacion: { habilitada: false, motivos: ['VOTACION_NO_EN_CURSO'] },
      desempatar: { habilitada: false, motivos: ['VOTACION_NO_EMPATADA'] },
      otorgar_palabra: { habilitada: true, motivos: [] },
      quitar_palabra: { habilitada: true, motivos: [] },
    }
    const estado = crearEstadoFixture({
      estado_global: 'SESION_ABIERTA',
      sesion: {
        fecha_hora_inicio_preparacion: '2026-09-01T09:30:00Z',
        fecha_hora_apertura: '2026-09-01T09:45:00Z',
        numero_sesion: 42,
        presidencia: 'Dra. Presidencia',
        secretaria_legislativa: 'Sr. Secretaría',
      },
      configuracion: {
        quorum: 7,
        filas_bancas: [3, 4, 5],
        tipos_votacion: ['Proyecto', 'Moción'],
        duracion_test_segundos: 3,
        revelado_votos_moderacion_segundos: 4,
        cuenta_regresiva_recinto_segundos: 3,
        resultado_publico_recinto_segundos: 6,
      },
      quorum: { cantidad_presentes: 8, requerido: 7, alcanzado: true },
      // Sin palabra pendiente: la salvaguarda CA-062 ya tiene su propio recorrido en WP-023.
      palabra: { orador: null, cola: [] },
      orden_del_dia: [],
      eventos_recientes: [],
      auditoria: {
        activa: true,
        disponible: true,
        fallado: false,
        cerrado: false,
        motivo: null,
      },
      capacidades,
    })
    await configurarCicloVotacionMock(page, estado)
    await page.setViewportSize({ width: 1366, height: 768 })
    await page.goto('/moderacion/')

    const panelQ1 = page.locator('[data-testid="panel-sesion-votacion"]')
    await expect(page.locator('[data-testid="formulario-votacion"]')).toBeVisible()

    // 1. Apertura: la votación proyectada es la confirmación; no hay acuse de tránsito.
    await page.locator('[data-testid="input-numero-votacion"]').fill('12')
    await page.locator('[data-testid="input-tema-votacion"]').fill('Presupuesto anual')
    await page.locator('[data-testid="btn-abrir-votacion"]').click()
    await expect(page.locator('[data-testid="estado-votacion"]')).toContainText('EN_CURSO')
    await expect(page.locator('[data-testid="aviso-votacion"]')).toHaveCount(0)
    await expect(panelQ1).not.toContainText('Apertura enviada')

    // 2. Finalización manual: tampoco deja acuse propio, el resultado habla por sí solo.
    await page.locator('[data-testid="input-motivo-finalizacion"]').fill('Moción previa')
    await page.locator('[data-testid="btn-finalizar-votacion"]').click()
    await expect(page.locator('[data-testid="estado-votacion"]')).toContainText('EMPATADA')
    await expect(page.locator('[data-testid="aviso-votacion"]')).toHaveCount(0)
    await expect(panelQ1).not.toContainText('Finalización enviada')

    // 3. Empate: la instrucción a Presidencia precede visualmente a los dos botones.
    const controles = page.locator('[data-testid="controles-desempate"]')
    const instruccion = controles.locator('[data-testid="instruccion-desempate"]')
    await expect(instruccion).toHaveText(
      'Votación empatada. La Presidencia debe emitir el voto de desempate:',
    )
    const cajaInstruccion = await instruccion.boundingBox()
    const cajaBoton = await page.locator('[data-testid="btn-desempate-positivo"]').boundingBox()
    expect(cajaInstruccion).not.toBeNull()
    expect(cajaBoton).not.toBeNull()
    expect(cajaInstruccion!.y).toBeLessThan(cajaBoton!.y)

    // 4. Desempate: el resultado confirmado reemplaza al bloque, sin acuse intermedio.
    await page.locator('[data-testid="btn-desempate-positivo"]').click()
    await expect(page.locator('[data-testid="estado-votacion"]')).toContainText('APROBADA')
    await expect(controles).toHaveCount(0)
    await expect(page.locator('[data-testid="aviso-votacion"]')).toHaveCount(0)
    await expect(panelQ1).not.toContainText('Desempate enviado')

    // 5. Pérdida de quórum con la sesión abierta: el impedimento es votar, no abrir sesión.
    await expect(page.locator('[data-testid="formulario-votacion"]')).toBeVisible()
    await page.evaluate(() => {
      ;(window as Window & { perderQuorum?: () => void }).perderQuorum?.()
    })
    await expect(page.locator('[data-testid="btn-abrir-votacion"]')).toBeDisabled()
    await expect(panelQ1).toContainText('Quórum insuficiente para abrir una votación.')
    await expect(panelQ1).not.toContainText('para abrir la sesión')
  })
})

/**
 * Evidencia geométrica de las dos correcciones operativas de WP-057.
 *
 * 1. Cabecera: indicador binario de transmisión junto al indicador de conexión.
 *    Se recorren los tres estados autoritativos (`APAGADO`, `CUENTA_REGRESIVA` y
 *    `EN_VIVO`), se comprueba el mapeo binario aprobado y se verifica que la cabecera
 *    conserva la altura de la baseline WP-047/WP-054 y sigue siendo una sola línea.
 *
 * 2. Q1: caso exacto de regresión reportado por la operación real. Con el resultado de
 *    la votación anterior todavía visible y un borrador nuevo de mayoría ESPECIAL
 *    completo, los controles de apertura deben quedar íntegramente dentro del bounding
 *    box visible de Q1, y ni Q1 ni el formulario pueden adquirir scroll.
 *
 *    Medición sobre el código previo a WP-057, a 1366×768 y con el mismo escenario:
 *    el cuerpo de Q1 pedía 345 px para 323 px disponibles y el botón `Abrir votación`
 *    terminaba 4 px por debajo del borde del cuadrante. La causa era la segunda fila
 *    `Factor | Base`, que sólo existía con mayoría ESPECIAL y costaba 52 px.
 */
test.describe('WP-057 - Transmisión en cabecera y compactación operativa de Q1', () => {
  /**
   * Tres resoluciones: las dos canónicas del producto más la intermedia de ~1440×768
   * que el WP pide cubrir si el harness la soporta sin costo estructural.
   */
  const resoluciones = [
    { width: 1366, height: 768 },
    { width: 1440, height: 768 },
    { width: 1920, height: 1080 },
  ]

  /** Porción técnica del snapshot con el estado de transmisión pedido. */
  function crearTecnico(estado: 'APAGADO' | 'CUENTA_REGRESIVA' | 'EN_VIVO') {
    return {
      transmision: {
        estado,
        iniciada_en: estado === 'APAGADO' ? null : '2026-09-03T12:00:00Z',
        en_vivo_desde: estado === 'APAGADO' ? null : '2026-09-03T12:00:10Z',
        cuenta_regresiva_segundos: estado === 'CUENTA_REGRESIVA' ? 10 : null,
        segundos_restantes: estado === 'CUENTA_REGRESIVA' ? 6 : null,
      },
      aviso: null,
    }
  }

  /**
   * Escenario exacto de regresión: sesión abierta, votación anterior cerrada cuyo
   * resultado todavía se ve en Q1 y formulario disponible para la siguiente.
   *
   * El tema y el tipo son de longitud institucional realista. Ese detalle importa:
   * con un tema corto el defecto no se manifestaba, porque el bloque de resultado
   * ocupaba dos renglones menos y alcanzaba a disimular los 52 px sobrantes.
   */
  function crearEstadoResultadoAnterior(estadoTransmision: 'APAGADO' | 'EN_VIVO' = 'APAGADO') {
    return crearEstadoSesionCompacta({
      votacion: crearVotacionCompacta({
        estado_recepcion: 'CERRADA',
        resultado: 'APROBADA',
        tipo: 'Proyecto de Ordenanza',
        tema: 'Expediente 4521-D-2026: Ordenanza de creación del Programa Municipal de Eficiencia Energética y Reconversión del Alumbrado Público de la ciudad',
        fecha_hora_cierre: '2026-08-29T10:00:10Z',
        fecha_hora_resultado: '2026-08-29T10:00:10Z',
      }),
      tecnico: crearTecnico(estadoTransmision),
    })
  }

  /** Completa el borrador de una votación nueva de mayoría ESPECIAL. */
  async function completarBorradorEspecial(page: Page): Promise<void> {
    await page.getByTestId('input-numero-votacion').fill('13')
    await page.getByTestId('select-tipo-votacion').selectOption('Proyecto')
    await page.getByTestId('radio-mayoria-especial').check()
    await page.getByTestId('input-factor-mayoria').fill('0.66')
    await page.getByTestId('select-base-mayoria').selectOption('PRESENTES')
    await page.getByTestId('input-tema-votacion').fill('Ordenanza de mayoría especial')
  }

  /**
   * Reúne en una sola pasada todos los rectángulos y desbordes que el WP exige medir.
   * Se devuelve un objeto plano para poder adjuntarlo íntegro al reporte de Playwright
   * como evidencia reproducible, además de usarlo en las aserciones.
   */
  async function medirGeometriaQ1(page: Page) {
    return page.evaluate(() => {
      const rectangulo = (selector: string) => {
        const elemento = document.querySelector(selector)
        if (!elemento) return null
        const caja = elemento.getBoundingClientRect()
        return {
          x: Math.round(caja.x),
          y: Math.round(caja.y),
          ancho: Math.round(caja.width),
          alto: Math.round(caja.height),
          derecha: Math.round(caja.right),
          abajo: Math.round(caja.bottom),
        }
      }
      const desborde = (selector: string) => {
        const elemento = document.querySelector(selector) as HTMLElement | null
        if (!elemento) return null
        return {
          altoContenido: elemento.scrollHeight,
          altoVisible: elemento.clientHeight,
          anchoContenido: elemento.scrollWidth,
          anchoVisible: elemento.clientWidth,
        }
      }
      const cuerpoQ1 = '[data-testid="panel-sesion-votacion"] [data-testid="cuerpo-panel"]'
      return {
        q1: rectangulo('[data-testid="panel-sesion-votacion"]')!,
        cuerpoQ1: rectangulo(cuerpoQ1)!,
        resultadoAnterior: rectangulo('[data-testid="vista-votacion-proyectada"]')!,
        filaReglaMayoria: rectangulo('[data-testid="fila-regla-mayoria"]')!,
        accionesApertura: rectangulo('[data-testid="btn-abrir-votacion"]')!,
        formulario: rectangulo('[data-testid="formulario-votacion"]')!,
        campos: {
          numero: rectangulo('[data-testid="input-numero-votacion"]')!,
          tipo: rectangulo('[data-testid="select-tipo-votacion"]')!,
          mayoria: rectangulo('[data-testid="radio-mayoria-especial"]')!,
          factor: rectangulo('[data-testid="input-factor-mayoria"]')!,
          base: rectangulo('[data-testid="select-base-mayoria"]')!,
        },
        desbordeCuerpoQ1: desborde(cuerpoQ1)!,
        desbordeFormulario: desborde('[data-testid="formulario-votacion"]')!,
      }
    })
  }

  for (const viewport of resoluciones) {
    test(`resultado anterior y votación ESPECIAL conviven a ${viewport.width}×${viewport.height}`, async ({
      page,
    }, testInfo) => {
      await configurarRutasMock(page, crearEstadoResultadoAnterior())
      await page.setViewportSize(viewport)
      await page.goto('/moderacion/')
      // El shell se monta y adopta el primer snapshot antes de medir nada.
      await page.getByTestId('cabecera-moderacion').waitFor({ state: 'visible', timeout: 30000 })

      // Precondición del caso: el resultado anterior sigue siendo la señal dominante
      // y, aun así, el formulario de la siguiente votación está disponible.
      await expect(page.getByTestId('estado-votacion')).toHaveText('APROBADA')
      await expect(page.getByTestId('formulario-votacion')).toBeVisible()

      await completarBorradorEspecial(page)
      await expect(page.getByTestId('campos-mayoria-especial')).toBeVisible()

      const medicion = await medirGeometriaQ1(page)
      await testInfo.attach(`wp057-geometria-${viewport.width}x${viewport.height}.json`, {
        body: JSON.stringify(medicion, null, 2),
        contentType: 'application/json',
      })

      // 1 · Los cinco campos comparten una única línea funcional: sus rectángulos se
      // solapan verticalmente y ninguno arranca por debajo del que lo precede.
      const campos = [
        medicion.campos.numero,
        medicion.campos.tipo,
        medicion.campos.mayoria,
        medicion.campos.factor,
        medicion.campos.base,
      ]
      for (const campo of campos) {
        expect(campo.y).toBeGreaterThanOrEqual(medicion.filaReglaMayoria.y - 1)
        expect(campo.abajo).toBeLessThanOrEqual(medicion.filaReglaMayoria.abajo + 1)
      }
      // Orden horizontal estable y sin superposición: Número → Tipo → Mayoría → Factor → Base.
      for (let indice = 1; indice < campos.length; indice += 1) {
        expect(campos[indice - 1]!.derecha).toBeLessThanOrEqual(campos[indice]!.x + 1)
      }
      // Una sola línea de campos: la fila no puede medir más que un control más su rótulo.
      expect(medicion.filaReglaMayoria.alto).toBeLessThanOrEqual(48)

      // 2 · Los controles de apertura quedan completos dentro del bounding box de Q1.
      expect(medicion.accionesApertura.y).toBeGreaterThanOrEqual(medicion.q1.y - 1)
      expect(medicion.accionesApertura.abajo).toBeLessThanOrEqual(medicion.q1.abajo + 1)
      expect(medicion.accionesApertura.x).toBeGreaterThanOrEqual(medicion.q1.x - 1)
      expect(medicion.accionesApertura.derecha).toBeLessThanOrEqual(medicion.q1.derecha + 1)
      await expect(page.getByTestId('btn-abrir-votacion')).toBeEnabled()

      // 3 · El resultado anterior sigue visible por encima del formulario y ambos
      // caben dentro del cuadrante: la corrección no se logró escondiendo información.
      expect(medicion.resultadoAnterior.abajo).toBeLessThanOrEqual(medicion.formulario.y + 1)
      expect(medicion.formulario.abajo).toBeLessThanOrEqual(medicion.q1.abajo + 1)

      // 4 · Ni Q1 ni el formulario adquieren scroll vertical u horizontal.
      for (const desborde of [medicion.desbordeCuerpoQ1, medicion.desbordeFormulario]) {
        expect(desborde.altoContenido).toBeLessThanOrEqual(desborde.altoVisible + 1)
        expect(desborde.anchoContenido).toBeLessThanOrEqual(desborde.anchoVisible + 1)
      }
      await verificarQ1SinScroll(page)

      await testInfo.attach(`wp057-q1-${viewport.width}x${viewport.height}.png`, {
        body: await page.getByTestId('panel-sesion-votacion').screenshot(),
        contentType: 'image/png',
      })

      await verificarGeometriaShellCompleto(page, viewport)
    })

    test(`mayoría ESPECIAL no agrega alto estructural a ${viewport.width}×${viewport.height}`, async ({
      page,
    }) => {
      await configurarRutasMock(page, crearEstadoResultadoAnterior())
      await page.setViewportSize(viewport)
      await page.goto('/moderacion/')
      await page.getByTestId('cabecera-moderacion').waitFor({ state: 'visible', timeout: 30000 })
      await expect(page.getByTestId('formulario-votacion')).toBeVisible()

      const altoFormulario = async () =>
        (await page.getByTestId('formulario-votacion').boundingBox())!.height

      // Mayoría SIMPLE es la baseline de densidad aprobada en WP-048.
      await expect(page.getByTestId('campos-mayoria-especial')).toHaveCount(0)
      const altoSimple = await altoFormulario()

      await page.getByTestId('radio-mayoria-especial').check()
      await expect(page.getByTestId('campos-mayoria-especial')).toBeVisible()
      const altoEspecial = await altoFormulario()

      // Decisión cerrada del WP: la segunda regla no puede costar alto estructural.
      expect(Math.abs(altoEspecial - altoSimple)).toBeLessThanOrEqual(1)

      // Volver a SIMPLE conserva funcionalidad y densidad.
      await page.getByTestId('radio-mayoria-simple').check()
      await expect(page.getByTestId('campos-mayoria-especial')).toHaveCount(0)
      expect(Math.abs((await altoFormulario()) - altoSimple)).toBeLessThanOrEqual(1)

      await verificarQ1SinScroll(page)
    })
  }

  for (const [estado, textoEsperado] of [
    ['APAGADO', 'Sin transmisión'],
    ['CUENTA_REGRESIVA', 'Sin transmisión'],
    ['EN_VIVO', 'En vivo'],
  ] as const) {
    test(`la cabecera presenta ${estado} como "${textoEsperado}" sin crecer a lo alto`, async ({
      page,
    }) => {
      await configurarRutasMock(page, crearEstadoSesionCompacta({ tecnico: crearTecnico(estado) }))
      await page.setViewportSize({ width: 1366, height: 768 })
      await page.goto('/moderacion/')
      await page.getByTestId('cabecera-moderacion').waitFor({ state: 'visible', timeout: 30000 })

      const indicador = page.getByTestId('cabecera-transmision')
      await expect(indicador).toHaveText(textoEsperado)
      await expect(indicador).toHaveAttribute('data-estado-transmision', estado)

      // Junto al indicador de conexión y en el mismo renglón que el título.
      const cajaTransmision = (await indicador.boundingBox())!
      const cajaConexion = (await page.getByTestId('estado-conexion').boundingBox())!
      const cajaTitulo = (await page
        .locator('[data-testid="cabecera-moderacion"] h1')
        .boundingBox())!
      expect(cajaTransmision.x + cajaTransmision.width).toBeLessThanOrEqual(cajaConexion.x + 1)
      expect(
        Math.abs(
          cajaTransmision.y + cajaTransmision.height / 2 - (cajaTitulo.y + cajaTitulo.height / 2),
        ),
      ).toBeLessThanOrEqual(2)

      // La cabecera conserva la baseline de altura y sigue siendo una sola línea.
      const cajaCabecera = (await page.getByTestId('cabecera-moderacion').boundingBox())!
      expect(cajaCabecera.height).toBeLessThanOrEqual(32)
      const contencion = await page.getByTestId('cabecera-moderacion').evaluate((cabecera) => ({
        flexWrap: getComputedStyle(cabecera).flexWrap,
        altoVisible: cabecera.clientHeight,
        altoContenido: cabecera.scrollHeight,
        anchoVisible: cabecera.clientWidth,
        anchoContenido: cabecera.scrollWidth,
      }))
      expect(contencion.flexWrap).toBe('nowrap')
      expect(contencion.altoContenido).toBeLessThanOrEqual(contencion.altoVisible + 1)
      expect(contencion.anchoContenido).toBeLessThanOrEqual(contencion.anchoVisible + 1)

      await verificarGeometriaShellCompleto(page, { width: 1366, height: 768 })
    })
  }
})
