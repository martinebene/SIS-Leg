/**
 * Regresión del incidente de la cuarta ronda humana: comandos REST bloqueados (WP-074).
 *
 * ## Qué ocurrió
 *
 * Con las cuatro superficies de SIS-Leg abiertas en un mismo navegador y bajo el mismo
 * origen —Moderación, Pantalla del Recinto, Simulador y Apoyo Técnico— los comandos dejaban
 * de llegar al backend. «Preparar sala» quedaba girando y el operador leía el síntoma como
 * una caída del servidor, aunque el servicio respondiera perfectamente a cualquier otro
 * cliente.
 *
 * La causa no era el backend sino el navegador. HTTP/1.1 limita las conexiones simultáneas
 * por origen (seis en Chromium) y un stream SSE es una conexión que no se cierra nunca.
 * Moderación, Recinto y Simulador abrían una cada uno; Apoyo Técnico abría **tres**, porque
 * además de su propia proyección observaba la de Moderación —para el remapeo— y la del
 * Recinto —para el sonido—. Seis conexiones permanentes: la séptima petición, es decir
 * cualquier comando, quedaba encolada en el navegador sin llegar a salir.
 *
 * ## Qué demuestra esta prueba
 *
 * Que el escenario completo vuelve a funcionar **sin cerrar ninguna pestaña**, que es la
 * condición que el WP exige: la corrección debe eliminar el agotamiento, no enseñar al
 * operador a convivir con él.
 *
 * Se comprueban tres cosas sobre el stack real, no sobre un doble:
 *
 * 1. el puesto técnico no solicita los streams de Moderación ni del Recinto;
 * 2. con las cuatro superficies abiertas quedan cuatro streams de estado vivos, uno por
 *    superficie, y no seis;
 * 3. `Preparar sala` sale del navegador, llega al backend y las cuatro pantallas ven el
 *    cambio de estado global.
 *
 * El conteo se hace observando las peticiones reales del contexto del navegador, así que
 * una regresión futura que volviera a abrir un stream de más fallaría acá aunque la
 * pantalla siguiera funcionando en apariencia.
 */

import { expect, test, type Page, type Request } from '@playwright/test'
import { ProcesoStackIntegrado, URL_STACK, puertoOcupado } from './infraestructura'

/** Identifica un stream de estado por su ruta, sin depender del host ni del puerto. */
function esStreamDeEstado(url: string): boolean {
  return /\/api\/v1\/estado\/[a-z]+\/stream$/.test(url)
}

/** Deja la ruta relativa de una URL, que es lo que se afirma en los mensajes de error. */
function ruta(url: string): string {
  return new URL(url).pathname
}

/**
 * Registra, para una pantalla, qué streams pidió y cuáles siguen abiertos.
 *
 * Un SSE no emite `requestfinished` mientras la conexión vive, así que la diferencia entre
 * lo pedido y lo terminado es exactamente el conjunto de conexiones persistentes que esa
 * pestaña mantiene ocupadas.
 */
function observarStreams(pagina: Page): { pedidos: string[]; vivos: () => string[] } {
  const pedidos: string[] = []
  const abiertos = new Set<Request>()

  pagina.on('request', (peticion) => {
    if (!esStreamDeEstado(peticion.url())) return
    pedidos.push(ruta(peticion.url()))
    abiertos.add(peticion)
  })
  const cerrar = (peticion: Request) => {
    abiertos.delete(peticion)
  }
  pagina.on('requestfinished', cerrar)
  pagina.on('requestfailed', cerrar)

  return { pedidos, vivos: () => [...abiertos].map((peticion) => ruta(peticion.url())) }
}

test.describe.serial('WP-074 · Las cuatro superficies conviven bajo un mismo origen', () => {
  const stack = new ProcesoStackIntegrado()

  test.beforeAll(async () => {
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

  test('mantiene cuatro streams y ejecuta Preparar sala sin cerrar pestañas', async ({
    browser,
  }) => {
    const contexto = await browser.newContext({ viewport: { width: 1920, height: 1080 } })
    const moderacion = await contexto.newPage()
    const recinto = await contexto.newPage()
    const simulador = await contexto.newPage()
    const tecnico = await contexto.newPage()

    // Los observadores se instalan antes de navegar: de otro modo el primer stream de cada
    // pantalla, que se abre durante la carga, no quedaría registrado.
    const observado = {
      moderacion: observarStreams(moderacion),
      recinto: observarStreams(recinto),
      simulador: observarStreams(simulador),
      tecnico: observarStreams(tecnico),
    }

    try {
      // ---------------------------------------------------------------------
      // 1. Las cuatro superficies abiertas a la vez, en el mismo origen.
      // ---------------------------------------------------------------------
      await Promise.all([
        moderacion.goto(`${URL_STACK}/moderacion/`),
        recinto.goto(`${URL_STACK}/recinto/`),
        simulador.goto(`${URL_STACK}/simulador/`),
        tecnico.goto(`${URL_STACK}/tecnico/`),
      ])

      // Las dos pantallas con indicador de conexión propio confirman que su stream quedó
      // efectivamente abierto; esperar por ellas evita medir un instante intermedio.
      await expect(tecnico.getByTestId('estado-conexion')).toHaveText('Conectado')
      await expect(moderacion.getByTestId('estado-conexion')).toHaveText('Conectado')
      await expect
        .poll(() => observado.recinto.vivos().length, { timeout: 15_000 })
        .toBeGreaterThan(0)
      await expect
        .poll(() => observado.simulador.vivos().length, { timeout: 15_000 })
        .toBeGreaterThan(0)

      // ---------------------------------------------------------------------
      // 2. El puesto técnico no pide los streams ajenos.
      // ---------------------------------------------------------------------
      expect(observado.tecnico.pedidos).toEqual(['/api/v1/estado/tecnico/stream'])
      expect(observado.tecnico.vivos()).toEqual(['/api/v1/estado/tecnico/stream'])

      // ---------------------------------------------------------------------
      // 3. Cuatro conexiones persistentes de estado en total, no seis.
      // ---------------------------------------------------------------------
      const vivos = [
        ...observado.moderacion.vivos(),
        ...observado.recinto.vivos(),
        ...observado.simulador.vivos(),
        ...observado.tecnico.vivos(),
      ]
      expect(vivos.sort()).toEqual([
        '/api/v1/estado/moderacion/stream',
        '/api/v1/estado/moderacion/stream',
        '/api/v1/estado/recinto/stream',
        '/api/v1/estado/tecnico/stream',
      ])

      // ---------------------------------------------------------------------
      // 4. El comando sale, llega y se confirma. Ninguna pestaña se cerró.
      // ---------------------------------------------------------------------
      const respuestaPreparacion = moderacion.waitForResponse(
        (respuesta) =>
          respuesta.url().endsWith('/api/v1/preparacion') &&
          respuesta.request().method() === 'POST',
        { timeout: 20_000 },
      )
      await moderacion.getByTestId('btn-preparar-sala').click()
      expect((await respuestaPreparacion).status()).toBe(204)

      await expect(moderacion.getByTestId('vista-preparando')).toBeVisible()
      // El hecho se propaga por los cuatro streams, que siguen vivos: la corrección no
      // sacrificó la actualización continua de ninguna superficie.
      await expect(tecnico.getByTestId('estado-global-tecnico')).toHaveText(
        'Recinto en preparación',
      )
      await expect(simulador.getByTestId('indicador-estado-global')).toHaveText('PREPARANDO')

      expect(contexto.pages()).toHaveLength(4)
      expect(observado.tecnico.pedidos).toEqual(['/api/v1/estado/tecnico/stream'])
    } finally {
      await contexto.close()
    }
  })
})
