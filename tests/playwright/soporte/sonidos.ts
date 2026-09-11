/**
 * Soporte de navegador para el motor de sonidos del Recinto (WP-066).
 *
 * Las pruebas de Vitest demuestran la semántica con un `Audio` falso. Lo que no pueden
 * demostrar es lo que sólo existe en un navegador real: que el elemento multimedia se cree
 * de verdad, que el archivo WAV publicado se pueda descargar y que la **política de
 * autoplay** permita reproducir sin que nadie toque la pantalla. Eso es exactamente lo que
 * necesita el recinto, donde no hay teclado ni mouse frente al monitor.
 *
 * Dos piezas hacen falta para eso:
 *
 * 1. un espía que envuelve `HTMLAudioElement.prototype.play` **sin sustituirlo**, de modo
 *    que la reproducción real ocurra y se registre si la promesa se cumplió o se rechazó;
 * 2. un backend de prueba cuyo stream pueda emitir revisiones nuevas a pedido, porque un
 *    sonido sólo debe sonar ante un hecho posterior a la baseline.
 *
 * El archivo no declara pruebas: Playwright sólo ejecuta los `*.spec.ts`.
 */

import type { Page } from '@playwright/test'

import { instalarFotosConcejales } from './fotos_concejales'

/** Registro de una reproducción observada en la ventana real. */
export interface ReproduccionObservada {
  /** Identificador del elemento multimedia; dos ids distintos son dos instancias. */
  id: number
  /** URL absoluta del archivo. */
  src: string
  /** Volumen normalizado que el motor aplicó antes de reproducir. */
  volume: number
  /** `cumplida` cuando el navegador aceptó reproducir; `rechazada` ante autoplay bloqueado. */
  resultado: 'pendiente' | 'cumplida' | 'rechazada'
  /** Detalle del rechazo, si lo hubo. */
  motivo: string | null
}

declare global {
  interface Window {
    reproduccionesRecinto?: ReproduccionObservada[]
    pausasRecinto?: number
    emitirEstadoRecinto?: (estado: unknown) => void
    prepararEstadoRecinto?: (estado: unknown) => void
    fallarStreamRecinto?: () => void
  }
}

/**
 * Instala el espía de audio antes de que cargue la aplicación.
 *
 * Envuelve `play` y `pause` en el prototipo: así se observan todas las instancias que cree
 * el motor, incluidas las que nacen para permitir la superposición. `pause` se cuenta
 * porque su ausencia es la prueba de que un sonido nuevo no interrumpe al anterior.
 */
export async function instalarEspiaAudio(page: Page): Promise<void> {
  await page.addInitScript(() => {
    window.reproduccionesRecinto = []
    window.pausasRecinto = 0
    let contador = 0

    const prototipo = HTMLAudioElement.prototype as HTMLAudioElement & {
      identificadorPrueba?: number
    }
    const reproducirOriginal = prototipo.play
    const pausarOriginal = prototipo.pause

    prototipo.play = function reproducirEspiado(this: HTMLAudioElement) {
      const elemento = this as HTMLAudioElement & { identificadorPrueba?: number }
      elemento.identificadorPrueba ??= ++contador
      const registro = {
        id: elemento.identificadorPrueba,
        src: this.src,
        volume: this.volume,
        resultado: 'pendiente' as const,
        motivo: null as string | null,
      }
      window.reproduccionesRecinto?.push(registro)

      const resultado = reproducirOriginal.call(this)
      resultado.then(
        () => {
          Object.assign(registro, { resultado: 'cumplida' })
        },
        (error: unknown) => {
          Object.assign(registro, {
            resultado: 'rechazada',
            motivo: error instanceof Error ? `${error.name}: ${error.message}` : String(error),
          })
        },
      )
      return resultado
    }

    prototipo.pause = function pausarEspiado(this: HTMLAudioElement) {
      window.pausasRecinto = (window.pausasRecinto ?? 0) + 1
      return pausarOriginal.call(this)
    }
  })
}

/**
 * Instala un backend de prueba con un stream que la prueba controla.
 *
 * Reproduce la secuencia real del cliente de sincronización: primero responde el snapshot
 * REST, después abre el stream y emite ese mismo estado. A partir de ahí, la prueba publica
 * revisiones nuevas llamando a `emitirEstadoRecinto`, que es la única forma de simular un
 * hecho posterior a la baseline.
 */
export async function instalarBackendControlable(page: Page, inicial: unknown): Promise<void> {
  // WP-098: la fotografía de banca ya no es un asset del build; la publica
  // el backend desde la configuración local. Sin backend real, se responde
  // desde la plantilla versionada, que es el mismo archivo de siempre.
  await instalarFotosConcejales(page)

  await page.addInitScript((estadoInicial) => {
    type Escucha = (evento: { type: string; data?: string }) => void
    let ultimoEstado = estadoInicial
    const fuentes: {
      escuchas: Record<string, Escucha[]>
      cerrada: boolean
      onerror: Escucha | null
    }[] = []

    class FuenteControlable {
      cerrada = false
      onopen: Escucha | null = null
      onerror: Escucha | null = null
      escuchas: Record<string, Escucha[]> = {}

      constructor(readonly url: string) {
        fuentes.push(this)
        setTimeout(() => {
          if (this.cerrada) return
          this.onopen?.({ type: 'open' })
          this.enviar(ultimoEstado)
        }, 10)
      }

      enviar(estado: unknown): void {
        if (this.cerrada) return
        for (const escuchar of this.escuchas.estado ?? []) {
          escuchar({ type: 'estado', data: JSON.stringify(estado) })
        }
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

    // Deja preparado el estado que devolverá el próximo snapshot REST, sin publicarlo por
    // el stream. Es la forma de simular lo que ocurre mientras la pantalla está
    // desconectada: el backend siguió avanzando y nadie se lo contó todavía.
    window.prepararEstadoRecinto = (estado: unknown) => {
      ultimoEstado = estado
    }

    // Rompe el stream vigente. El cliente cierra la conexión, espera su backoff, vuelve a
    // pedir el snapshot y abre un stream nuevo, exactamente como ante una caída real.
    window.fallarStreamRecinto = () => {
      for (const fuente of fuentes) {
        if (fuente.cerrada) continue
        ;(fuente as unknown as { onerror: Escucha | null }).onerror?.({ type: 'error' })
      }
    }

    window.emitirEstadoRecinto = (estado: unknown) => {
      ultimoEstado = estado
      for (const fuente of fuentes) {
        if (fuente.cerrada) continue
        for (const escuchar of fuente.escuchas.estado ?? []) {
          escuchar({ type: 'estado', data: JSON.stringify(estado) })
        }
      }
    }

    // @ts-expect-error Sustitución determinista de EventSource para el E2E.
    window.EventSource = FuenteControlable

    const fetchOriginal = window.fetch.bind(window)
    window.fetch = async (entrada: RequestInfo | URL, opciones?: RequestInit) => {
      const url =
        typeof entrada === 'string' ? entrada : entrada instanceof URL ? entrada.href : entrada.url
      if (url.includes('/api/v1/estado/recinto')) {
        return new Response(JSON.stringify(ultimoEstado), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      return fetchOriginal(entrada, opciones)
    }
  }, inicial)
}

/** Lee las reproducciones observadas hasta el momento. */
export function leerReproducciones(page: Page): Promise<ReproduccionObservada[]> {
  return page.evaluate(() => window.reproduccionesRecinto ?? [])
}

/** Publica una revisión nueva por el stream controlado. */
export function emitirEstado(page: Page, estado: unknown): Promise<void> {
  return page.evaluate((nuevo) => window.emitirEstadoRecinto?.(nuevo), estado)
}

/** Deja listo el estado que devolverá el próximo snapshot, sin emitirlo por el stream. */
export function prepararEstado(page: Page, estado: unknown): Promise<void> {
  return page.evaluate((nuevo) => window.prepararEstadoRecinto?.(nuevo), estado)
}

/** Provoca la caída del stream para forzar el ciclo de recuperación del cliente. */
export function romperStream(page: Page): Promise<void> {
  return page.evaluate(() => window.fallarStreamRecinto?.())
}
