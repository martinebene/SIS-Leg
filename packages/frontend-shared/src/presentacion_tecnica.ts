/**
 * Reloj de presentación del plano técnico de Apoyo Técnico (WP-056).
 *
 * El backend es el único que decide cuándo una cuenta regresiva se convierte en `EN_VIVO`
 * y cuándo un aviso deja de estar vigente: guarda la frontera **absoluta**
 * (`en_vivo_desde`, `expira_en`) y republica una revisión nueva al cruzarla. Este módulo
 * no toma ninguna de esas decisiones; sólo hace avanzar el número visible entre dos
 * mensajes SSE para que el operador y el público vean una cuenta que baja de a un segundo
 * en lugar de un valor congelado.
 *
 * Por eso no hay polling: el intervalo local únicamente redibuja, no consulta la red, y se
 * apaga solo en cuanto no queda ninguna frontera pendiente.
 *
 * ### Por qué se calibra el reloj contra `generado_en`
 *
 * El monitor del recinto o la notebook de Apoyo Técnico pueden tener la hora corrida
 * respecto del servidor. Restar la frontera absoluta contra el reloj del navegador daría
 * entonces una cuenta desplazada. Cada snapshot trae `generado_en`, el instante en que el
 * backend lo construyó; la diferencia contra `Date.now()` en el momento de recibirlo es el
 * desfase que se aplica después. Recibir una revisión nueva corrige ese desfase, pero
 * jamás crea una duración nueva: la frontera sigue siendo la misma marca absoluta.
 *
 * Es el mismo criterio que ya usaba la cuenta regresiva pública de la votación; acá se
 * comparte entre la Pantalla del Recinto y el puesto técnico para que ambos muestren
 * exactamente el mismo número en el mismo instante.
 */

import { computed, onScopeDispose, ref, watch, type ComputedRef, type Ref } from 'vue'
import type { AvisoTecnicoProyectado, TransmisionProyectada } from '@sis-leg/api-client'

/** Cadencia del redibujo local. 250 ms basta para que el segundo cambie sin saltos. */
const INTERVALO_RELOJ_MS = 250

/** Datos del snapshot vigente que alimentan la presentación técnica. */
export interface EntradaPresentacionTecnica {
  /** Estado autoritativo de la transmisión, o `null` si el snapshot todavía no llegó. */
  transmision: TransmisionProyectada | null
  /** Avisos vigentes que esta pantalla necesita cronometrar. Puede ir vacío. */
  avisos: readonly (AvisoTecnicoProyectado | null)[]
  /** Marca `generado_en` del mismo snapshot, usada para calibrar el reloj. */
  generadoEn: string | null
}

/** Superficie reactiva que consumen los componentes. */
export interface PresentacionTecnica {
  /**
   * Segundos que faltan para `EN_VIVO`, o `null` fuera de `CUENTA_REGRESIVA`.
   *
   * Nunca baja de cero ni se vuelve negativo: cuando llega a cero se queda ahí hasta que
   * el backend publica el estado `EN_VIVO`. Esa espera es deliberada; adelantarse sería
   * que la pantalla decidiera una transición que no le corresponde.
   */
  segundosTransmision: ComputedRef<number | null>
  /**
   * Segundos que faltan para que venza un aviso, o `null` si no vence o no existe.
   *
   * Se expone como función y no como `computed` porque cada pantalla cronometra una
   * cantidad distinta de avisos: Moderación y Recinto uno, el puesto técnico dos.
   */
  segundosRestantesAviso: (aviso: AvisoTecnicoProyectado | null) => number | null
}

/** Convierte una marca ISO del contrato en milisegundos, o `null` si falta o es inválida. */
function instante(timestamp: string | null | undefined): number | null {
  if (!timestamp) return null
  const valor = Date.parse(timestamp)
  return Number.isFinite(valor) ? valor : null
}

/** Redondea hacia arriba los segundos que faltan, sin devolver valores negativos. */
function segundosHasta(frontera: number | null, ahora: number): number | null {
  if (frontera === null) return null
  const restante = frontera - ahora
  return restante > 0 ? Math.ceil(restante / 1000) : 0
}

/**
 * Crea el reloj de presentación técnica y lo asocia al scope reactivo que lo usa.
 *
 * @param entrada Snapshot técnico vigente, reactivo.
 * @returns Cuenta regresiva de la transmisión y cálculo de vigencia de cada aviso.
 */
export function usePresentacionTecnica(
  entrada: Ref<EntradaPresentacionTecnica>,
): PresentacionTecnica {
  const ahoraLocal = ref(Date.now())
  const desfaseBackend = ref(0)
  let intervalo: ReturnType<typeof setInterval> | null = null
  let ultimoGeneradoEn: number | null = null

  const ahoraBackend = computed(() => ahoraLocal.value + desfaseBackend.value)

  const segundosTransmision = computed<number | null>(() => {
    const transmision = entrada.value.transmision
    if (transmision?.estado !== 'CUENTA_REGRESIVA') return null
    return segundosHasta(instante(transmision.en_vivo_desde), ahoraBackend.value)
  })

  function segundosRestantesAviso(aviso: AvisoTecnicoProyectado | null): number | null {
    if (aviso === null) return null
    return segundosHasta(instante(aviso.expira_en), ahoraBackend.value)
  }

  function detenerReloj(): void {
    if (intervalo === null) return
    clearInterval(intervalo)
    intervalo = null
  }

  /**
   * Indica si todavía queda alguna frontera futura que obligue a redibujar.
   *
   * Se consultan las fronteras absolutas del snapshot, no los contadores derivados: así
   * el reloj se apaga exactamente cuando ya no hay nada que animar, y no un tick después.
   */
  function quedaFronteraPendiente(): boolean {
    const { transmision, avisos } = entrada.value
    const fronteras: (number | null)[] = [
      transmision?.estado === 'CUENTA_REGRESIVA' ? instante(transmision.en_vivo_desde) : null,
      ...avisos.map((aviso) => instante(aviso?.expira_en)),
    ]
    return fronteras.some((frontera) => frontera !== null && frontera > ahoraBackend.value)
  }

  function sincronizarReloj(): void {
    detenerReloj()
    ahoraLocal.value = Date.now()
    if (!quedaFronteraPendiente()) return

    intervalo = setInterval(() => {
      ahoraLocal.value = Date.now()
      if (!quedaFronteraPendiente()) detenerReloj()
    }, INTERVALO_RELOJ_MS)
  }

  watch(
    entrada,
    (actual) => {
      const generadoEn = instante(actual.generadoEn)
      // Un snapshot repetido con la misma marca no vuelve a calibrar el reloj: si lo
      // hiciera, cada revisión idéntica podría desplazar visualmente una cuenta en curso.
      if (generadoEn !== null && generadoEn !== ultimoGeneradoEn) {
        desfaseBackend.value = generadoEn - Date.now()
        ultimoGeneradoEn = generadoEn
      } else if (generadoEn === null) {
        desfaseBackend.value = 0
        ultimoGeneradoEn = null
      }
      sincronizarReloj()
    },
    { immediate: true, deep: true },
  )

  onScopeDispose(detenerReloj)

  return { segundosTransmision, segundosRestantesAviso }
}
