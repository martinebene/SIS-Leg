/**
 * Pruebas del reloj anclado y del renglón único de la cabecera pública.
 *
 * La geometría real (altura, una sola línea, elipsis) se verifica en Playwright
 * con bounding boxes; acá se fija la *estructura* que la hace posible, porque
 * jsdom no calcula layout.
 */

import { mount, type VueWrapper } from '@vue/test-utils'
import type { EstadoRecinto } from '@sis-leg/api-client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import CabeceraRecinto from '../app/components/CabeceraRecinto.vue'
import {
  calcularDuracionEnSnapshot,
  convertirMarcaBackend,
  formatearDuracion,
} from '../app/utils/tiempo'
import {
  crearEstadoRecintoPrueba,
  crearIdentidadInstitucionalPrueba,
  NOMBRE_INSTITUCIONAL_DE_PRUEBA,
} from './datos_prueba'

const montados: VueWrapper[] = []

function crearSesion(generadoEn: string, fechaHoraApertura: string, numeroSesion = 39) {
  return crearEstadoRecintoPrueba({
    generado_en: generadoEn,
    estado_global: 'SESION_ABIERTA',
    sesion: {
      fecha_hora_inicio_preparacion: fechaHoraApertura,
      fecha_hora_apertura: fechaHoraApertura,
      numero_sesion: numeroSesion,
      presidencia: 'Presidencia de prueba',
      secretaria_legislativa: 'Secretaría de prueba',
    },
  })
}

/**
 * Monta la cabecera con un snapshot público.
 *
 * Admite `null` a propósito: es el estado real de la pantalla entre que Vue
 * monta y llega el primer snapshot del backend, y desde WP-084 esa ventana tiene
 * comportamiento propio para el nombre institucional.
 */
function montarCabecera(estado: EstadoRecinto | null = crearEstadoRecintoPrueba()): VueWrapper {
  const wrapper = mount(CabeceraRecinto, {
    props: { estado, estadoConexion: 'CONECTADO', desactualizado: false },
  })
  montados.push(wrapper)
  return wrapper
}

/** Etiquetas de los hijos directos del bloque central, para las suites de abajo. */
function hijosDelContextoCentral(wrapper: VueWrapper): string[] {
  return Array.from(wrapper.get('[data-testid="cabecera-contexto"]').element.children).map((hijo) =>
    hijo.tagName.toLowerCase(),
  )
}

afterEach(() => {
  while (montados.length > 0) montados.pop()?.unmount()
  vi.useRealTimers()
})

describe('Cabecera pública con reloj anclado', () => {
  it('resta dos marcas naive backend sin usar la zona ni el instante absoluto del navegador', async () => {
    vi.useFakeTimers()
    // El monitor simulado vive nueve años después del snapshot. La solución
    // anterior Date.now()-Date.parse(apertura) habría producido una duración
    // absurda; la nueva solo resta las dos lecturas del reloj backend.
    vi.setSystemTime('2035-01-02T03:04:05Z')
    const wrapper = montarCabecera(crearSesion('2026-08-30T10:00:00', '2026-08-30T09:30:00'))

    expect(calcularDuracionEnSnapshot('2026-08-30T10:00:00', '2026-08-30T09:30:00')).toBe(1_800_000)
    expect(wrapper.get('[data-testid="cabecera-tiempo-sesion"]').text()).toContain('00:30:00')
    expect(wrapper.get('[data-testid="cabecera-autoridades"]').text()).toContain(
      'Presidencia de prueba',
    )

    vi.advanceTimersByTime(1000)
    await nextTick()
    expect(wrapper.get('[data-testid="cabecera-tiempo-sesion"]').text()).toContain('00:30:01')
  })

  it('continúa entre snapshots y una baseline nueva reemplaza completamente el ancla', async () => {
    vi.useFakeTimers()
    vi.setSystemTime('2040-05-01T00:00:00Z')
    const wrapper = montarCabecera(crearSesion('2026-08-30T10:00:00', '2026-08-30T09:00:00'))
    expect(wrapper.get('[data-testid="cabecera-tiempo-sesion"]').text()).toContain('01:00:00')

    // No llega snapshot durante esta ventana (equivale a una reconexión con la
    // última baseline confirmada): el elapsed local continúa visualmente.
    vi.advanceTimersByTime(5000)
    await nextTick()
    expect(wrapper.get('[data-testid="cabecera-tiempo-sesion"]').text()).toContain('01:00:05')

    await wrapper.setProps({
      estado: crearSesion('2026-08-30T10:10:00', '2026-08-30T10:05:00', 40),
    })
    expect(wrapper.get('[data-testid="cabecera-tiempo-sesion"]').text()).toContain('00:05:00')
    expect(wrapper.get('[data-testid="cabecera-sesion"]').text()).toBe('Sesión N.º 40')

    vi.advanceTimersByTime(1000)
    await nextTick()
    expect(wrapper.get('[data-testid="cabecera-tiempo-sesion"]').text()).toContain('00:05:01')
  })

  it('recorta aperturas futuras, omite PREPARANDO y acepta más de 24 horas', async () => {
    vi.useFakeTimers()
    vi.setSystemTime('2040-05-01T00:00:00Z')
    const wrapper = montarCabecera(crearSesion('2026-08-30T10:00:00', '2026-08-30T10:05:00'))
    expect(wrapper.get('[data-testid="cabecera-tiempo-sesion"]').text()).toContain('00:00:00')

    await wrapper.setProps({
      estado: crearEstadoRecintoPrueba({
        generado_en: '2026-08-30T10:00:00',
        estado_global: 'PREPARANDO',
        preparacion: {
          fecha_hora_inicio: '2026-08-30T09:00:00',
          numero_sesion: 40,
          presidencia: 'Otra Presidencia',
          secretaria_legislativa: 'Otra Secretaría',
        },
      }),
    })
    expect(wrapper.find('[data-testid="cabecera-tiempo-sesion"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="cabecera-sesion"]').text()).toContain('Preparando')

    expect(
      formatearDuracion(calcularDuracionEnSnapshot('2026-08-31T11:00:00', '2026-08-30T10:00:00')!),
    ).toBe('25:00:00')
    expect(convertirMarcaBackend('marca inválida')).toBeNull()
  })

  it('libera el único ticker visual al desmontar', () => {
    vi.useFakeTimers()
    const wrapper = montarCabecera(crearSesion('2026-08-30T10:00:00', '2026-08-30T09:30:00'))
    expect(vi.getTimerCount()).toBe(1)
    wrapper.unmount()
    montados.pop()
    expect(vi.getTimerCount()).toBe(0)
  })
})

describe('Cabecera pública de una sola línea (WP-050, refinada por WP-054)', () => {
  /** Devuelve las etiquetas de los hijos directos del bloque central. */
  function hijosDelContexto(wrapper: VueWrapper): string[] {
    return Array.from(wrapper.get('[data-testid="cabecera-contexto"]').element.children).map(
      (hijo) => hijo.tagName.toLowerCase(),
    )
  }

  /**
   * Texto de cada renglón de autoridad del sector derecho.
   *
   * El DOM simulado del monorepo entiende selectores simples y descendientes,
   * no combinadores de hijo directo: por eso se busca por clase.
   */
  function renglonesDeAutoridades(wrapper: VueWrapper): string[] {
    return wrapper
      .findAll('.renglon-autoridad')
      .map((renglon) => renglon.text().replace(/\s+/g, ' ').trim())
  }

  it('condensa título, sesión y duración como elementos en línea del centro', () => {
    vi.useFakeTimers()
    vi.setSystemTime('2030-01-01T00:00:00Z')
    const wrapper = montarCabecera(crearSesion('2026-08-30T10:00:00', '2026-08-30T09:30:00'))

    // Tres elementos en línea, ningún párrafo: antes de WP-050 el centro eran
    // un `h1` y dos `p`, es decir tres renglones apilados. WP-054 le quita
    // además las autoridades, que se mudaron al sector derecho.
    expect(hijosDelContexto(wrapper)).toEqual(['h1', 'span', 'span'])
    expect(hijosDelContexto(wrapper)).not.toContain('p')

    // Cada dato conserva su texto limpio: el separador `·` lo dibuja CSS, de
    // modo que ninguna prueba ni lector de pantalla lo lee como contenido.
    expect(wrapper.get('[data-testid="cabecera-sesion"]').text()).toBe('Sesión N.º 39')
    expect(wrapper.get('[data-testid="cabecera-tiempo-sesion"]').text()).toBe('00:30:00')
    // Desde WP-084 el nombre institucional llega del snapshot, no de la
    // plantilla: lo que se comprueba es que el centro publique el valor
    // configurado por la fixture.
    expect(wrapper.text()).toContain(NOMBRE_INSTITUCIONAL_DE_PRUEBA)
  })

  it('no reserva renglón cuando faltan autoridades o duración', async () => {
    const wrapper = montarCabecera(
      crearEstadoRecintoPrueba({
        generado_en: '2026-08-30T10:00:00',
        estado_global: 'PREPARANDO',
        preparacion: {
          fecha_hora_inicio: '2026-08-30T09:00:00',
          numero_sesion: 61,
          presidencia: null,
          secretaria_legislativa: null,
        },
      }),
    )

    // Sin autoridades el bloque directamente no existe: ya no queda un párrafo
    // con un espacio duro ocupando altura.
    expect(wrapper.find('[data-testid="cabecera-autoridades"]').exists()).toBe(false)
    // PREPARANDO no expone duración de sesión.
    expect(wrapper.find('[data-testid="cabecera-tiempo-sesion"]').exists()).toBe(false)
    expect(hijosDelContexto(wrapper)).toEqual(['h1', 'span'])
    expect(wrapper.get('[data-testid="cabecera-sesion"]').text()).toContain('61')

    // Con una sola autoridad se dibuja un único renglón: el bloque derecho no
    // reserva el segundo mientras Secretaría no exista.
    await wrapper.setProps({
      estado: crearEstadoRecintoPrueba({
        generado_en: '2026-08-30T10:00:00',
        estado_global: 'PREPARANDO',
        preparacion: {
          fecha_hora_inicio: '2026-08-30T09:00:00',
          numero_sesion: 61,
          presidencia: 'Sólo Presidencia',
          secretaria_legislativa: null,
        },
      }),
    })
    expect(hijosDelContexto(wrapper)).toEqual(['h1', 'span'])
    expect(renglonesDeAutoridades(wrapper)).toEqual(['Presidencia: Sólo Presidencia'])
  })

  it('ofrece el texto completo de autoridades en `title` porque en pantalla se recorta', () => {
    const largo = 'Presidencia con un nombre deliberadamente extenso para forzar el recorte visual'
    const wrapper = montarCabecera(
      crearEstadoRecintoPrueba({
        generado_en: '2026-08-30T10:00:00',
        estado_global: 'SESION_ABIERTA',
        sesion: {
          fecha_hora_inicio_preparacion: '2026-08-30T09:00:00',
          fecha_hora_apertura: '2026-08-30T09:30:00',
          numero_sesion: 62,
          presidencia: largo,
          secretaria_legislativa: null,
        },
      }),
    )
    // El DOM liviano de estas pruebas expone los atributos por `getAttribute`.
    const autoridades = wrapper.get('[data-testid="cabecera-autoridades"]').element
    expect(autoridades.getAttribute('title')).toBe(`Presidencia: ${largo}`)
    // El texto largo no agrega renglones ni vuelve al centro de la cabecera.
    expect(renglonesDeAutoridades(wrapper)).toHaveLength(1)
    expect(hijosDelContexto(wrapper)).toEqual(['h1', 'span', 'span'])
  })
})

/**
 * Reorganización de jerarquía pedida por HUMAN_GATE sobre la captura real.
 *
 * jsdom no calcula layout, así que acá se fija la *estructura* que hace posible
 * el resultado visual —qué dato vive en qué zona y qué clases comparten— y la
 * geometría concreta (centrado real, dos renglones, sin invasión) se mide en
 * Playwright con bounding boxes en 1366×768 y 1920×1080.
 */
describe('Cabecera pública reorganizada (WP-054)', () => {
  it('deja en el centro sólo institución, sesión y duración, con una única escala', () => {
    vi.useFakeTimers()
    vi.setSystemTime('2030-01-01T00:00:00Z')
    const wrapper = montarCabecera(crearSesion('2026-08-30T10:00:00', '2026-08-30T09:30:00'))

    const contexto = wrapper.get('[data-testid="cabecera-contexto"]')
    // Los tres datos centrales comparten la clase que fija el tamaño: es lo que
    // impide que el título vuelva a leerse como un encabezado con apostillas.
    const hijosCentrales = Array.from(contexto.element.children)
    expect(hijosCentrales).toHaveLength(3)
    for (const hijo of hijosCentrales) {
      expect(hijo.classList.contains('dato-cabecera')).toBe(true)
    }

    // Las autoridades ya no forman parte del centro.
    expect(contexto.find('[data-testid="cabecera-autoridades"]').exists()).toBe(false)
    expect(contexto.text()).not.toContain('Presidencia')
  })

  it('ubica las autoridades en dos renglones del sector derecho, junto a la conexión', () => {
    vi.useFakeTimers()
    vi.setSystemTime('2030-01-01T00:00:00Z')
    const wrapper = montarCabecera(crearSesion('2026-08-30T10:00:00', '2026-08-30T09:30:00'))

    const autoridades = wrapper.get('[data-testid="cabecera-autoridades"]')
    const renglones = autoridades.findAll('.renglon-autoridad')
    // Un renglón por autoridad, en el orden institucional Presidencia/Secretaría.
    expect(renglones).toHaveLength(2)
    expect(renglones[0]!.text().replace(/\s+/g, ' ').trim()).toBe(
      'Presidencia: Presidencia de prueba',
    )
    expect(renglones[1]!.text().replace(/\s+/g, ' ').trim()).toBe(
      'Secretaría: Secretaría de prueba',
    )

    // Autoridades y conexión comparten el mismo contenedor derecho: ambas
    // aparecen como descendientes del sector, y ninguna quedó en el centro.
    const sector = wrapper.get('.sector-derecho')
    expect(sector.find('[data-testid="cabecera-autoridades"]').exists()).toBe(true)
    expect(sector.find('[data-testid="estado-conexion"]').exists()).toBe(true)
  })
})

/**
 * Identidad institucional configurable (WP-084).
 *
 * Hasta este WP el nombre del cuerpo legislativo estaba escrito dentro de la
 * plantilla, así que instalar SIS-Leg en otra institución obligaba a editar
 * código. Acá se fija el comportamiento observable de la cabecera: publica
 * exactamente lo que viene en `EstadoRecinto.institucion`, en cualquier estado
 * global, y sólo cae a un rótulo genérico cuando no hay nada que mostrar.
 *
 * La geometría con nombres de distinta longitud —que ninguno recorte, solape ni
 * genere scroll— se mide en Playwright, porque jsdom no calcula layout.
 */
describe('Identidad institucional configurable (WP-084)', () => {
  /** Devuelve el texto del `h1` institucional, ya normalizado. */
  function nombreMostrado(wrapper: VueWrapper): string {
    return wrapper.get('[data-testid="cabecera-institucion"]').text().replace(/\s+/g, ' ').trim()
  }

  it('muestra el nombre configurado incluso en SIN_PREPARAR', () => {
    const wrapper = montarCabecera(
      crearEstadoRecintoPrueba({
        estado_global: 'SIN_PREPARAR',
        institucion: crearIdentidadInstitucionalPrueba({
          nombre: 'Concejo Municipal de Aguas Claras',
        }),
      }),
    )

    expect(nombreMostrado(wrapper)).toBe('Concejo Municipal de Aguas Claras')
    // El resto del centro sigue diciendo lo mismo que antes: el WP cambia el
    // origen del nombre, no la semántica del contexto.
    expect(wrapper.get('[data-testid="cabecera-sesion"]').text()).toBe('Recinto sin preparar')
  })

  it('publica dos nombres de longitud muy distinta sin alterar la estructura del centro', async () => {
    const corto = 'Concejo de Villa Sur'
    const largo =
      'Honorable Legislatura Provincial de la Región Continental de Nuevos Territorios del Sur'

    const wrapper = montarCabecera(
      crearEstadoRecintoPrueba({
        institucion: crearIdentidadInstitucionalPrueba({ nombre: corto }),
      }),
    )
    expect(nombreMostrado(wrapper)).toBe(corto)
    expect(hijosDelContextoCentral(wrapper)).toEqual(['h1', 'span'])

    await wrapper.setProps({
      estado: crearEstadoRecintoPrueba({
        institucion: crearIdentidadInstitucionalPrueba({ nombre: largo }),
      }),
    })
    // El nombre viaja completo al DOM: el recorte es visual (elipsis), nunca una
    // truncación del texto, y por eso el emergente conserva la lectura íntegra.
    expect(nombreMostrado(wrapper)).toBe(largo)
    expect(wrapper.get('[data-testid="cabecera-institucion"]').element.getAttribute('title')).toBe(
      largo,
    )
    expect(hijosDelContextoCentral(wrapper)).toEqual(['h1', 'span'])
  })

  it('conserva el valor configurado tal cual, sin recortarlo ni normalizarlo', () => {
    const conEspacios = '  Concejo Deliberativo del Valle  '
    const wrapper = montarCabecera(
      crearEstadoRecintoPrueba({
        institucion: crearIdentidadInstitucionalPrueba({ nombre: conEspacios }),
      }),
    )

    // `textContent` conserva el valor exacto; la normalización de `nombreMostrado`
    // existe sólo para las demás aserciones, así que acá se lee el crudo.
    expect(wrapper.get('[data-testid="cabecera-institucion"]').element.textContent).toBe(
      conEspacios,
    )
  })

  it('cae a un rótulo genérico cuando todavía no hay snapshot o el nombre viene vacío', async () => {
    const wrapper = montarCabecera(null)
    expect(nombreMostrado(wrapper)).toBe('Cuerpo legislativo')

    // Un nombre vacío sólo puede llegar de un backend que no pudo leer la
    // configuración; la cabecera no debe quedarse sin texto ni cambiar de alto.
    await wrapper.setProps({
      estado: crearEstadoRecintoPrueba({
        institucion: crearIdentidadInstitucionalPrueba({ nombre: '   ' }),
      }),
    })
    expect(nombreMostrado(wrapper)).toBe('Cuerpo legislativo')
  })
})
