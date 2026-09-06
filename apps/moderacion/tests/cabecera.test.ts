/**
 * Pruebas dedicadas de la cabecera compacta de Moderación (WP-047).
 *
 * Cobertura:
 * 1. Densidad: el distintivo `SIS-LEG` desapareció y `Moderación` sigue siendo la identidad.
 * 2. Reloj local: se muestra la fecha/hora del equipo y avanza con el paso del tiempo,
 *    verificado con un reloj falso (sin depender del reloj real de la máquina de CI).
 * 3. Tiempo de sesión: se ancla con `generado_en - fecha_hora_apertura`, dos marcas
 *    backend comparables aunque el navegador use otra zona horaria.
 * 4. Autoridades: Presidencia y Secretaría Legislativa se muestran desde que fueron cargadas,
 *    tanto en PREPARANDO como en SESION_ABIERTA, y se omiten mientras no existan.
 * 5. Quórum: se presenta en cabecera cuando el backend lo proyecta y se omite cuando es null.
 * 6. Conexión y advertencia de estado desactualizado.
 * 7. Número de sesión antes del quórum y ausencia del estado global redundante.
 * 8. Funciones puras de formateo temporal compartidas con Recinto.
 * 9. WP-054: agrupación del sector derecho (autoridades + tiempo + fecha + conexión)
 *    y etiquetas explícitas `Tiempo de sesión` y `Fecha`.
 *
 * El shell completo (`app.vue`) aporta a la cabecera los datos derivados del estado; esas
 * derivaciones se comprueban aquí sobre las mismas reglas: sesión primero, preparación después.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { compile, createSSRApp, h, nextTick, ssrContextKey, type Component } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { mount, type VueWrapper } from '@vue/test-utils'
import CabeceraModeracion from '../app/components/CabeceraModeracion.vue'
import fuenteCabeceraModeracion from '../app/components/CabeceraModeracion.vue?raw'
import {
  formatearFechaHoraLocal,
  formatearDuracion,
  calcularDuracionEnSnapshot,
  convertirMarcaBackend,
} from '../app/utils/tiempo'
import type { EstadoQuorum } from '@sis-leg/api-client'

/**
 * Vitest ejecuta este paquete en entorno Node, donde el plugin de Vue produce `ssrRender`.
 * Para montar el componente real con @vue/test-utils hace falta además un render de cliente:
 * compilamos la plantilla exacta del componente productivo importada con `?raw`. No se replica
 * ninguna lógica; sólo se cubre la frontera de compilación que en un navegador ya viene resuelta.
 */
function habilitarRenderCliente(componente: Component, fuente: string): void {
  const coincidencia = fuente.match(/<template>([\s\S]*)<\/template>/)
  if (!coincidencia?.[1]) {
    throw new Error('No se encontró la plantilla Vue que debe compilarse para la prueba')
  }

  const componenteCompilable = componente as {
    render?: ReturnType<typeof compile>
    setup?: (props: unknown, contexto: unknown) => unknown
  }

  const setupOriginal = componenteCompilable.setup
  if (setupOriginal) {
    componenteCompilable.setup = (props, contexto) => {
      const resultado = setupOriginal(props, contexto)
      if (typeof resultado === 'object' && resultado !== null) {
        // El compilador SFC marca el resultado como `$setup`. Al compilar la plantilla en
        // runtime, copiar el objeto retira esa marca y habilita el acceso equivalente por `_ctx`.
        return { ...resultado }
      }
      return resultado
    }
  }

  componenteCompilable.render = compile(coincidencia[1], { hoistStatic: false })
}

habilitarRenderCliente(CabeceraModeracion, fuenteCabeceraModeracion)

/** Props mínimas obligatorias de la cabecera, para no repetirlas en cada caso. */
function propsBase(parcial: Record<string, unknown> = {}) {
  return {
    estadoConexion: 'CONECTADO',
    estadoGlobal: 'SESION_ABIERTA',
    revision: 7,
    desactualizado: false,
    generadoEn: '2026-08-29T12:30:15',
    fechaHoraApertura: '2026-08-29T12:00:00',
    numeroSesion: 8,
    ...parcial,
  }
}

/** Renderiza la cabecera a texto para inspeccionar su estructura sin montar el DOM. */
async function renderizarSSR(props: Record<string, unknown>): Promise<string> {
  const app = createSSRApp({
    render() {
      return h(CabeceraModeracion, props)
    },
  })
  return renderToString(app)
}

const montados: VueWrapper[] = []

/** Monta la cabecera real para poder observar la reactividad del reloj tick a tick. */
function montarCabecera(props: Record<string, unknown>): VueWrapper {
  // El componente compilado para SSR consulta el contexto de servidor durante su setup;
  // proveerlo explícitamente permite montarlo también como componente de cliente.
  const contextoSsr = { modules: new Set<string>() }
  const wrapper = mount(CabeceraModeracion, {
    props,
    global: { provide: { [ssrContextKey]: contextoSsr } },
  })
  montados.push(wrapper)
  return wrapper
}

describe('Utilidades de tiempo de la cabecera', () => {
  it('formatea fecha y hora local en formato compacto y estable', () => {
    // Se construye con componentes locales para no depender de la zona horaria del entorno.
    const fecha = new Date(2026, 7, 29, 9, 5, 3)
    expect(formatearFechaHoraLocal(fecha)).toBe('29/08/2026 09:05:03')
  })

  it('devuelve un guion ante una fecha inválida en lugar de texto basura', () => {
    expect(formatearFechaHoraLocal(new Date('no-es-una-fecha'))).toBe('—')
  })

  it('formatea duraciones como hh:mm:ss y recorta valores negativos a cero', () => {
    expect(formatearDuracion(0)).toBe('00:00:00')
    expect(formatearDuracion(45_000)).toBe('00:00:45')
    expect(formatearDuracion(3_725_000)).toBe('01:02:05')
    expect(formatearDuracion(90_000_000)).toBe('25:00:00')
    expect(formatearDuracion(-5_000)).toBe('00:00:00')
  })

  it('resta marcas backend naive sin incorporar la zona horaria del navegador', () => {
    expect(calcularDuracionEnSnapshot('2026-08-29T12:30:15', '2026-08-29T12:00:00')).toBe(1_815_000)
    expect(convertirMarcaBackend('fecha-invalida')).toBeNull()
  })
})

describe('CabeceraModeracion (WP-047)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    while (montados.length > 0) {
      montados.pop()?.unmount()
    }
    vi.useRealTimers()
  })

  describe('Densidad e identidad', () => {
    it('conserva Moderación, retira el estado global y no muestra la revisión permanentemente', async () => {
      const html = await renderizarSSR(propsBase())

      expect(html).toContain('Moderación')
      expect(html).not.toContain('SIS-Leg')
      expect(html).not.toContain('SIS-LEG')
      expect(html).not.toContain('data-testid="estado-global"')
      expect(html).not.toContain('Sesión abierta')
      expect(html).not.toContain('data-testid="revision-estado"')
      expect(html).not.toContain('Revisión:')
    })

    it('muestra el número de sesión antes del quórum y admite el provisorio de PREPARANDO', async () => {
      const quorum: EstadoQuorum = { cantidad_presentes: 9, requerido: 7, alcanzado: true }
      const htmlSesion = await renderizarSSR(propsBase({ quorum, totalConcejales: 12 }))
      const htmlPreparacion = await renderizarSSR(
        propsBase({
          estadoGlobal: 'PREPARANDO',
          numeroSesion: 9,
          generadoEn: null,
          fechaHoraApertura: null,
        }),
      )

      expect(htmlSesion).toContain('data-testid="cabecera-numero-sesion"')
      expect(htmlSesion).toContain('Sesión Nº 8')
      expect(htmlSesion.indexOf('cabecera-numero-sesion')).toBeLessThan(
        htmlSesion.indexOf('cabecera-quorum'),
      )
      expect(htmlPreparacion).toContain('Sesión Nº 9')
    })

    it('no inventa un número mientras la preparación todavía no lo tiene', async () => {
      const html = await renderizarSSR(
        propsBase({
          estadoGlobal: 'PREPARANDO',
          numeroSesion: null,
          generadoEn: null,
          fechaHoraApertura: null,
        }),
      )

      expect(html).not.toContain('data-testid="cabecera-numero-sesion"')
    })
  })

  describe('Reloj local y tiempo de sesión', () => {
    it('muestra la hora local y la actualiza con el paso del tiempo sin polling', async () => {
      vi.setSystemTime(new Date(2026, 7, 29, 10, 0, 0))
      const wrapper = montarCabecera(propsBase())

      // Desde WP-054 el valor viaja junto a su rótulo explícito `Fecha`.
      expect(wrapper.get('[data-testid="cabecera-fecha-hora"]').text()).toContain(
        '29/08/2026 10:00:00',
      )

      // Un tick del temporizador local basta para refrescar la vista: no hay ningún fetch de por medio.
      vi.advanceTimersByTime(1000)
      await nextTick()

      expect(wrapper.get('[data-testid="cabecera-fecha-hora"]').text()).toContain(
        '29/08/2026 10:00:01',
      )
    })

    it('cancela su temporizador al desmontarse para no dejar trabajo pendiente', async () => {
      vi.setSystemTime(new Date(2026, 7, 29, 10, 0, 0))
      const wrapper = montarCabecera(propsBase())

      expect(vi.getTimerCount()).toBeGreaterThan(0)

      wrapper.unmount()
      montados.pop()

      expect(vi.getTimerCount()).toBe(0)
    })

    it('omite el tiempo de sesión mientras no exista fecha de apertura formal', async () => {
      const html = await renderizarSSR(
        propsBase({ estadoGlobal: 'PREPARANDO', fechaHoraApertura: null }),
      )

      expect(html).not.toContain('data-testid="cabecera-tiempo-sesion"')
    })

    it('deriva la duración de dos marcas backend aunque el reloj local esté en otro año', async () => {
      vi.setSystemTime(new Date('2035-01-02T03:04:05Z'))
      const wrapper = montarCabecera(propsBase())

      expect(wrapper.get('[data-testid="cabecera-tiempo-sesion"]').text()).toContain('00:30:15')

      vi.advanceTimersByTime(45_000)
      await nextTick()

      expect(wrapper.get('[data-testid="cabecera-tiempo-sesion"]').text()).toContain('00:31:00')
    })

    it('continúa sin baseline nueva y se reancla completamente al recibir otro snapshot', async () => {
      vi.setSystemTime(new Date('2040-05-01T00:00:00Z'))
      const wrapper = montarCabecera(
        propsBase({
          generadoEn: '2026-08-30T10:00:00',
          fechaHoraApertura: '2026-08-30T09:00:00',
        }),
      )
      expect(wrapper.get('[data-testid="cabecera-tiempo-sesion"]').text()).toContain('01:00:00')

      // Esta ventana representa una reconexión sin baseline nueva: el ticker local
      // conserva el último anclaje confirmado en lugar de resetear el contador.
      vi.advanceTimersByTime(5000)
      await nextTick()
      expect(wrapper.get('[data-testid="cabecera-tiempo-sesion"]').text()).toContain('01:00:05')

      await wrapper.setProps({
        generadoEn: '2026-08-30T10:10:00',
        fechaHoraApertura: '2026-08-30T10:05:00',
        numeroSesion: 9,
      })
      expect(wrapper.get('[data-testid="cabecera-tiempo-sesion"]').text()).toContain('00:05:00')
      expect(wrapper.get('[data-testid="cabecera-numero-sesion"]').text()).toBe('Sesión Nº 9')
    })

    it('recorta aperturas futuras, admite más de 24 horas y omite estados sin sesión', async () => {
      vi.setSystemTime(new Date('2040-05-01T00:00:00Z'))
      const wrapper = montarCabecera(
        propsBase({
          generadoEn: '2026-08-30T10:00:00',
          fechaHoraApertura: '2026-08-30T10:05:00',
        }),
      )
      expect(wrapper.get('[data-testid="cabecera-tiempo-sesion"]').text()).toContain('00:00:00')

      await wrapper.setProps({ estadoGlobal: 'PREPARANDO' })
      expect(wrapper.find('[data-testid="cabecera-tiempo-sesion"]').exists()).toBe(false)

      expect(
        formatearDuracion(
          calcularDuracionEnSnapshot('2026-08-31T11:00:00', '2026-08-30T10:00:00')!,
        ),
      ).toBe('25:00:00')
    })
  })

  describe('Autoridades institucionales', () => {
    it('muestra Presidencia y Secretaría ya cargadas durante PREPARANDO', async () => {
      const html = await renderizarSSR(
        propsBase({
          estadoGlobal: 'PREPARANDO',
          presidencia: 'Dra. María Elena Walsh',
          secretariaLegislativa: 'Lic. Juan Gómez',
        }),
      )

      expect(html).toContain('data-testid="cabecera-presidencia"')
      expect(html).toContain('Dra. María Elena Walsh')
      expect(html).toContain('data-testid="cabecera-secretaria"')
      expect(html).toContain('Lic. Juan Gómez')
    })

    it('omite cada autoridad mientras no haya sido cargada', async () => {
      const html = await renderizarSSR(
        propsBase({
          estadoGlobal: 'PREPARANDO',
          presidencia: null,
          secretariaLegislativa: null,
        }),
      )

      expect(html).not.toContain('data-testid="cabecera-presidencia"')
      expect(html).not.toContain('data-testid="cabecera-secretaria"')
    })
  })

  describe('Quórum global', () => {
    it('presenta presentes, padrón y mínimo requerido cuando el quórum está alcanzado', async () => {
      const quorum: EstadoQuorum = { cantidad_presentes: 9, requerido: 7, alcanzado: true }
      const html = await renderizarSSR(propsBase({ quorum, totalConcejales: 12 }))

      expect(html).toContain('data-testid="cabecera-quorum"')
      expect(html).toContain('Quórum 9/12 · mín 7')
    })

    it('distingue explícitamente la falta de quórum', async () => {
      const quorum: EstadoQuorum = { cantidad_presentes: 5, requerido: 7, alcanzado: false }
      const html = await renderizarSSR(
        propsBase({ estadoGlobal: 'PREPARANDO', quorum, totalConcejales: 12 }),
      )

      expect(html).toContain('Sin quórum 5/12 · mín 7')
    })

    it('no muestra ningún indicador de quórum cuando el backend no lo proyecta', async () => {
      const html = await renderizarSSR(
        propsBase({ estadoGlobal: 'SIN_PREPARAR', quorum: null, totalConcejales: 12 }),
      )

      expect(html).not.toContain('data-testid="cabecera-quorum"')
      expect(html).not.toContain('Sin quórum')
    })
  })

  describe('Conexión y advertencia de desactualización', () => {
    it('refleja cada estado técnico de conexión con su etiqueta legible', async () => {
      const esperados: Array<[string, string]> = [
        ['INICIAL', 'Conectando'],
        ['CONECTADO', 'Conectado'],
        ['RECONECTANDO', 'Reconectando'],
        ['DESCONECTADO', 'Sin conexión'],
      ]

      for (const [estadoConexion, etiqueta] of esperados) {
        const html = await renderizarSSR(propsBase({ estadoConexion }))
        expect(html).toContain('data-testid="estado-conexion"')
        expect(html).toContain(etiqueta)
      }
    })

    it('mantiene la advertencia de estado desactualizado durante una reconexión', async () => {
      const html = await renderizarSSR(
        propsBase({ estadoConexion: 'RECONECTANDO', desactualizado: true }),
      )

      expect(html).toContain('data-testid="alerta-desactualizado"')
      expect(html).toContain('Estado desactualizado')
    })

    it('no muestra la advertencia mientras la conexión es plena', async () => {
      const html = await renderizarSSR(propsBase({ desactualizado: false }))

      expect(html).not.toContain('data-testid="alerta-desactualizado"')
    })
  })
})

/**
 * Reorganización de la cabecera pedida por HUMAN_GATE sobre la captura real
 * del 01/09/2026 (WP-054).
 *
 * Acá se fija el *orden estructural* del renglón —qué dato vive en qué sector—
 * y la presencia de las etiquetas explícitas. Que todo eso entre efectivamente
 * en una sola línea, con la misma altura que antes, se mide con bounding boxes
 * en Playwright a 1366×768 y 1920×1080.
 */
describe('Cabecera reorganizada de Moderación (WP-054)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    while (montados.length > 0) {
      montados.pop()?.unmount()
    }
    vi.useRealTimers()
  })

  /** Props con autoridades y quórum cargados: el caso completo de sesión abierta. */
  function propsCompletas(parcial: Record<string, unknown> = {}) {
    const quorum: EstadoQuorum = { cantidad_presentes: 9, requerido: 7, alcanzado: true }
    return propsBase({
      quorum,
      totalConcejales: 12,
      presidencia: 'Dra. María Elena Walsh',
      secretariaLegislativa: 'Lic. Juan Gómez',
      ...parcial,
    })
  }

  it('agrupa autoridades, tiempo, fecha y conexión después del bloque institucional', async () => {
    const html = await renderizarSSR(propsCompletas())

    // Orden de aparición en el marcado: identidad, sesión y quórum a la
    // izquierda; autoridades, tiempo, fecha y conexión a la derecha.
    const posiciones = [
      'cabecera-numero-sesion',
      'cabecera-quorum',
      'cabecera-presidencia',
      'cabecera-secretaria',
      'cabecera-tiempo-sesion',
      'cabecera-fecha-hora',
      'estado-conexion',
    ].map((testid) => html.indexOf(`data-testid="${testid}"`))

    for (const posicion of posiciones) {
      expect(posicion).toBeGreaterThan(-1)
    }
    // Cada elemento aparece después del anterior: antes de WP-054 las
    // autoridades estaban entre el quórum y el bloque temporal, pero en el
    // centro flexible, no dentro del sector derecho.
    for (let indice = 1; indice < posiciones.length; indice += 1) {
      expect(posiciones[indice]!).toBeGreaterThan(posiciones[indice - 1]!)
    }
  })

  it('rotula explícitamente el tiempo de sesión y la fecha', async () => {
    const html = await renderizarSSR(propsCompletas())

    // Dos valores numéricos conviven en el mismo sector: sin rótulo, `00:30:15`
    // y `29/08/2026 12:30:15` se leen como dos relojes indistinguibles.
    expect(html).toContain('Tiempo de sesión')
    expect(html).toContain('Fecha')
  })

  it('mantiene las autoridades y el resto del sector derecho en el mismo grupo', () => {
    const wrapper = montarCabecera(propsCompletas())

    // El sector derecho es un único contenedor: si las autoridades quedaran
    // fuera, volverían a ocupar el centro flexible de la cabecera.
    const presidencia = wrapper.get('[data-testid="cabecera-presidencia"]').element
    const conexion = wrapper.get('[data-testid="estado-conexion"]').element
    const sectores = wrapper
      .findAll('div')
      .filter(
        (nodo) =>
          nodo.element.querySelector('[data-testid="cabecera-presidencia"]') !== null &&
          nodo.element.querySelector('[data-testid="estado-conexion"]') !== null,
      )
    expect(sectores.length).toBeGreaterThan(0)

    // Ambos textos siguen presentes y con su contenido institucional.
    expect(presidencia.textContent).toContain('Dra. María Elena Walsh')
    expect(conexion.textContent).toContain('Conectado')
  })

  it('conserva el nombre completo de cada autoridad en `title` porque se recorta', () => {
    const wrapper = montarCabecera(propsCompletas())

    expect(wrapper.get('[data-testid="cabecera-presidencia"]').element.getAttribute('title')).toBe(
      'Presidencia: Dra. María Elena Walsh',
    )
    expect(wrapper.get('[data-testid="cabecera-secretaria"]').element.getAttribute('title')).toBe(
      'Secretaría: Lic. Juan Gómez',
    )
  })
})
