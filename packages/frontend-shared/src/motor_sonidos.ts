/**
 * Motor de reproducción de los sonidos del Recinto (WP-066), compartido por las
 * superficies que los emiten (WP-071).
 *
 * ## Dónde vive y por qué
 *
 * Igual que la detección de transiciones, este motor nació dentro de la Pantalla del
 * Recinto y desde WP-071 lo usa también el puesto de Apoyo Técnico, que debe sonar
 * exactamente igual para poder alimentar la amplificación del salón. Vive en
 * `frontend-shared` para que exista **una sola** implementación de volumen, superposición,
 * precarga y tolerancia a fallos: dos motores paralelos divergirían al primer ajuste.
 *
 * ## Responsabilidad
 *
 * Traducir un evento sonoro ya detectado (`preparacion_iniciada`, `votacion_cerrada`…) en
 * una reproducción concreta, usando la ruta y el volumen que el backend proyecta en
 * `EstadoRecinto.sonidos`. No decide **cuándo** suena algo: eso lo deciden
 * `detectarTransicionesSonoras` y el composable `useSonidosRecinto`.
 *
 * ## Por qué una instancia de audio por reproducción
 *
 * HUMAN_GATE decidió que dos hechos simultáneos puedan oírse superpuestos y que un sonido
 * nuevo nunca interrumpa al anterior. Un elemento `Audio` reutilizado no puede hacer eso:
 * volver a llamar `play()` sobre el mismo elemento reinicia la reproducción en curso. Por
 * eso cada evento crea su **propia** instancia, que el navegador libera sola al terminar.
 * Tampoco existe una cola serial: el WP la prohíbe explícitamente.
 *
 * ## Por qué la fábrica de audio es inyectable
 *
 * `Audio` es una API del navegador. Inyectar su fábrica permite probar el motor completo
 * —volumen aplicado, superposición, rechazo de `play()`— sin navegador y sin reproducir
 * nada, que es la prueba mínima obligatoria del WP. La fábrica predeterminada devuelve
 * `null` cuando `Audio` no existe (prerender de Nuxt, pruebas de componentes con DOM
 * liviano), de modo que el motor simplemente no suena en vez de romper el render.
 *
 * ## Por qué la resolución de URL se inyecta
 *
 * `EstadoRecinto.sonidos` trae rutas **relativas** a la raíz pública de la aplicación
 * (`assets/sonidos/sesion-abierta.wav`). Convertirlas en una URL servible exige conocer el
 * `baseURL` de la aplicación que reproduce, y ese dato lo tiene Nuxt dentro de cada SPA,
 * no este paquete. Por eso `resolverUrl` es un parámetro **obligatorio**: cada pantalla
 * entrega su propio resolutor y ninguna corre el riesgo de heredar en silencio el prefijo
 * de la otra. Las dos apuntan al mismo archivo versionado, publicado una sola vez en
 * `apps/recinto/public/assets/sonidos/`; Apoyo Técnico lo sirve bajo su propio prefijo sin
 * copiarlo al repositorio (ver `apps/tecnico/nuxt.config.ts`).
 *
 * ## Por qué los errores no se propagan
 *
 * Una política de autoplay que rechace la reproducción, un archivo faltante o un códec no
 * soportado no pueden romper la pantalla ni la sincronización: el recinto debe seguir
 * mostrando la sesión aunque el audio falle. Todo error se captura, se informa **una sola
 * vez por evento** en la consola técnica y no se reintenta. Ese límite es deliberado:
 * reintentar un archivo roto ante cada revisión sería un bucle silencioso.
 */

import type { SonidoRecintoProyectado, SonidosRecintoProyectados } from '@sis-leg/api-client'
import type { EventoSonoroRecinto } from './transiciones_sonoras'

/**
 * Superficie mínima de `HTMLAudioElement` que necesita el motor.
 *
 * Se declara acá, y no se importa de las tipificaciones del DOM, para que una prueba pueda
 * implementarla con un objeto plano de tres campos.
 */
export interface InstanciaAudioRecinto {
  /** Volumen normalizado de `0` a `1`, tal como lo define el estándar HTML. */
  volume: number
  /** Sugerencia de carga anticipada; el navegador puede ignorarla. */
  preload: string
  /** Inicia la reproducción. En los navegadores devuelve una promesa que puede rechazar. */
  play: () => Promise<void> | void
  /** Fuerza la descarga del archivo sin reproducirlo. Opcional en la superficie de prueba. */
  load?: () => void
}

/** Crea una instancia de audio para una URL, o `null` si el entorno no puede reproducir. */
export type FabricaAudioRecinto = (url: string) => InstanciaAudioRecinto | null

export interface OpcionesMotorSonidos {
  /**
   * Convierte la ruta configurada por el backend en una URL servible.
   *
   * Obligatorio: depende del `baseURL` de la aplicación que reproduce y este paquete no
   * puede conocerlo. Recinto y Apoyo Técnico entregan cada uno el suyo.
   */
  resolverUrl: (ruta: string) => string
  /** Fábrica de audio inyectable. Por defecto usa `Audio` cuando el navegador la ofrece. */
  crearAudio?: FabricaAudioRecinto
  /** Canal técnico de diagnóstico. Por defecto, una advertencia de consola. */
  registrarDiagnostico?: (mensaje: string, detalle?: unknown) => void
}

/** Superficie pública del motor, la que consume el composable. */
export interface MotorSonidosRecinto {
  /** Adopta la configuración vigente y precarga los archivos nuevos. Es idempotente. */
  configurar: (sonidos: SonidosRecintoProyectados | null | undefined) => void
  /** Reproduce el sonido del evento indicado, si está configurado. Nunca lanza. */
  reproducir: (evento: EventoSonoroRecinto) => void
  /** Suelta las instancias precargadas. Se llama al desmontar la pantalla. */
  liberar: () => void
}

/** Volumen configurado (`0..100`) llevado al rango del estándar HTML (`0..1`). */
function normalizarVolumen(volumen: number): number {
  if (!Number.isFinite(volumen)) return 0
  return Math.min(1, Math.max(0, volumen / 100))
}

/**
 * Fábrica predeterminada: un `Audio` real cuando el entorno lo permite.
 *
 * El `typeof` cubre a la vez el prerender de Nuxt —que ejecuta el código sin DOM— y las
 * pruebas de componentes, que montan la pantalla sobre un DOM liviano sin multimedia.
 */
function crearAudioNavegador(url: string): InstanciaAudioRecinto | null {
  if (typeof Audio === 'undefined') return null
  return new Audio(url)
}

/**
 * Construye el motor de sonidos.
 *
 * @param opciones `resolverUrl` es obligatorio; el resto son puntos de inyección para
 *   pruebas y en producción se usan los valores por defecto.
 * @returns Un motor con estado propio (configuración vigente, precargas y diagnósticos ya
 *   informados). Cada pantalla que sonoriza usa uno solo.
 */
export function crearMotorSonidos(opciones: OpcionesMotorSonidos): MotorSonidosRecinto {
  const crearAudio = opciones.crearAudio ?? crearAudioNavegador
  const resolverUrl = opciones.resolverUrl
  const registrarDiagnostico =
    opciones.registrarDiagnostico ??
    ((mensaje: string, detalle?: unknown) => console.warn(`[sonidos-recinto] ${mensaje}`, detalle))

  /** Evento -> URL resuelta y volumen normalizado, según la última configuración adoptada. */
  let catalogo = new Map<string, { url: string; volumen: number }>()
  /** Firma de la configuración adoptada; evita reconstruir y reprecargar en cada revisión. */
  let firmaConfiguracion: string | null = null
  /** Instancias mantenidas vivas sólo para que el navegador conserve el archivo en caché. */
  const precargas = new Map<string, InstanciaAudioRecinto>()
  /** Eventos cuyo problema ya se informó; impide repetir el mismo diagnóstico sin fin. */
  const diagnosticosInformados = new Set<string>()

  /** Texto estable que cambia si y sólo si cambió alguna ruta o volumen configurado. */
  function calcularFirma(sonidos: readonly SonidoRecintoProyectado[]): string {
    return sonidos.map((sonido) => `${sonido.evento}|${sonido.ruta}|${sonido.volumen}`).join('\n')
  }

  /**
   * Pide al navegador que descargue cada archivo antes del primer evento.
   *
   * Es una precarga real pero no bloqueante: `preload = 'auto'` es una sugerencia y `load()`
   * inicia la descarga en segundo plano. Ninguna de las dos cosas detiene el render ni la
   * sincronización, y si la descarga falla el motor simplemente reproducirá tarde o no
   * reproducirá, sin romper la pantalla.
   */
  function precargar(url: string): void {
    if (precargas.has(url)) return
    // Toda la precarga está protegida, incluida la construcción del elemento: un entorno
    // sin multimedia puede lanzar al instanciarlo, y `configurar` corre dentro de un
    // observador reactivo. Una excepción acá dejaría a medio camino el ciclo de
    // renderizado de la pantalla, que es justamente lo que el WP prohíbe.
    try {
      const audio = crearAudio(url)
      if (audio === null) return
      audio.preload = 'auto'
      audio.volume = 0
      audio.load?.()
      precargas.set(url, audio)
    } catch (error) {
      informarUnaVez(`precarga_fallida:${url}`, `no se pudo precargar ${url}`, error)
    }
  }

  function configurar(sonidos: SonidosRecintoProyectados | null | undefined): void {
    // Una configuración ausente o marcada como no disponible por el backend deja el motor
    // en silencio, sin catálogo. No es un error de la pantalla: `system.toml` está mal y
    // el backend ya lo publicó como tal.
    if (!sonidos || sonidos.disponible !== true) {
      catalogo = new Map()
      firmaConfiguracion = null
      return
    }

    const firma = calcularFirma(sonidos.sonidos)
    if (firma === firmaConfiguracion) return

    const nuevoCatalogo = new Map<string, { url: string; volumen: number }>()
    for (const sonido of sonidos.sonidos) {
      const url = resolverUrl(sonido.ruta)
      nuevoCatalogo.set(sonido.evento, { url, volumen: normalizarVolumen(sonido.volumen) })
    }

    catalogo = nuevoCatalogo
    firmaConfiguracion = firma
    diagnosticosInformados.clear()

    // Cambiar la configuración deja huérfanas las precargas de archivos que ya no se usan;
    // se sueltan antes de descargar las nuevas para no acumular elementos multimedia vivos
    // durante toda la jornada.
    const urlsVigentes = new Set(Array.from(nuevoCatalogo.values(), (sonido) => sonido.url))
    for (const url of Array.from(precargas.keys())) {
      if (!urlsVigentes.has(url)) precargas.delete(url)
    }
    for (const url of urlsVigentes) precargar(url)
  }

  function reproducir(evento: EventoSonoroRecinto): void {
    const configuracion = catalogo.get(evento)
    if (configuracion === undefined) {
      // Un catálogo vacío es un único problema —la configuración no llegó o el backend la
      // publicó como inválida— y se informa una sola vez, no quince. Un evento suelto que
      // falta dentro de un catálogo válido sí se nombra, porque señala otra cosa: el
      // contrato de eventos cambió y esta pantalla quedó atrás.
      if (catalogo.size === 0) {
        informarUnaVez('catalogo_vacio', 'no hay sonidos configurados para el Recinto')
      } else {
        informarUnaVez(`evento_sin_configurar:${evento}`, `sin sonido configurado para ${evento}`)
      }
      return
    }

    try {
      const audio = crearAudio(configuracion.url)
      if (audio === null) return
      audio.volume = configuracion.volumen
      // `play()` devuelve una promesa en los navegadores modernos. Un rechazo típico es la
      // política de autoplay; se informa una vez y no se reintenta.
      const reproduccion = audio.play()
      if (reproduccion && typeof reproduccion.catch === 'function') {
        reproduccion.catch((error: unknown) => {
          informarUnaVez(
            `reproduccion_rechazada:${evento}`,
            `el navegador rechazó reproducir ${evento}`,
            error,
          )
        })
      }
    } catch (error) {
      informarUnaVez(`reproduccion_fallida:${evento}`, `no se pudo reproducir ${evento}`, error)
    }
  }

  /** Informa un problema una única vez por clave, para no generar ruido ni bucles. */
  function informarUnaVez(clave: string, mensaje: string, detalle?: unknown): void {
    if (diagnosticosInformados.has(clave)) return
    diagnosticosInformados.add(clave)
    registrarDiagnostico(mensaje, detalle)
  }

  function liberar(): void {
    precargas.clear()
    diagnosticosInformados.clear()
    catalogo = new Map()
    firmaConfiguracion = null
  }

  return { configurar, reproducir, liberar }
}
