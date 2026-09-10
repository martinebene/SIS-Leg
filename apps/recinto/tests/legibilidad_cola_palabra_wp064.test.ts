/**
 * Legibilidad de los nombres de la cola de palabra (WP-064).
 *
 * HUMAN_GATE miró la Pantalla del Recinto desde el fondo de la sala y decidió
 * que los nombres de quienes esperan turno seguían siendo chicos, incluso
 * después del primer salto de legibilidad de WP-054. La decisión cerrada fue
 * agrandarlos **aproximadamente un 80 %** sin ensanchar la columna ni rediseñar
 * el resto de la pantalla.
 *
 * Esta prueba cubre las dos mitades que sí se pueden demostrar sin navegador:
 *
 * 1. el comportamiento del componente con la cola vacía, con un pedido y con
 *    varios, que es lo que exige el WP;
 * 2. el tamaño *declarado* del nombre, leído del propio CSS del componente y
 *    comparado contra la baseline de WP-054.
 *
 * El punto 2 merece una explicación. Estas pruebas montan el componente en un
 * DOM simulado que no calcula layout ni aplica hojas de estilo, así que pedirle
 * `getComputedStyle` daría un valor inventado. Por eso se parsea la regla real
 * del archivo `.vue`, igual que hace la prueba de recorte de bitmaps de WP-058.
 * La medición del tamaño *renderizado* —la que realmente prueba el 80 %— vive
 * en Playwright, donde hay un navegador que calcula píxeles de verdad.
 */

import { existsSync, readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import PanelPalabraPublico from '../app/components/PanelPalabraPublico.vue'

const montados: VueWrapper[] = []

afterEach(() => {
  while (montados.length > 0) montados.pop()?.unmount()
})

/**
 * Raíz del monorepo, buscada hacia arriba desde el directorio de trabajo.
 *
 * Los SFC se compilan en modo cliente, así que `import.meta.url` no apunta a un
 * archivo del disco. Subir hasta el `pnpm-workspace.yaml` ubica el archivo real
 * tanto si Vitest se lanza desde la raíz como desde `apps/recinto`.
 */
function ubicarRaizMonorepo(): string {
  let directorio = resolve(process.cwd())
  while (!existsSync(join(directorio, 'pnpm-workspace.yaml'))) {
    const padre = dirname(directorio)
    if (padre === directorio) throw new Error('No se encontró la raíz del monorepo')
    directorio = padre
  }
  return directorio
}

const rutaComponente = join(
  ubicarRaizMonorepo(),
  'apps',
  'recinto',
  'app',
  'components',
  'PanelPalabraPublico.vue',
)

/**
 * Baseline tipográfica que dejó WP-054 para el nombre de la cola.
 *
 * Son los tres términos del `clamp` anterior, en el mismo orden en que los
 * escribe CSS: mínimo, valor elástico y máximo.
 */
const CLAMP_NOMBRE_WP054 = { minimoRem: 0.92, elasticoVw: 1.02, maximoRem: 1.28 } as const

/** Crecimiento pedido por HUMAN_GATE: aproximadamente 80 %. */
const FACTOR_NOMBRE_WP064 = 1.8

/** Cola de dos pedidos con nombres de longitud realista del padrón. */
const COLA_REALISTA = [
  { nombre: 'María Eugenia', apellido: 'Fernández Robledo', banca: 7 },
  { nombre: 'Juan', apellido: 'Pérez', banca: 1 },
]

/** Monta el panel con la cola indicada y recuerda el wrapper para liberarlo. */
function montarPanel(cola: { nombre: string; apellido: string; banca: number }[]): VueWrapper {
  const wrapper = mount(PanelPalabraPublico, {
    props: { palabra: { orador: { nombre: 'Andrea', apellido: 'Rueda', banca: 3 }, cola } },
  })
  montados.push(wrapper)
  return wrapper
}

describe('Cola de palabra del Recinto con nombres ampliados (WP-064)', () => {
  it('no dibuja lista cuando la cola está vacía', () => {
    const wrapper = montarPanel([])

    // Sin pedidos no hay `<ol>`: el panel muestra su leyenda de espera. Si el
    // cambio tipográfico hubiera roto la rama `v-else`, esto lo delata.
    expect(wrapper.find('[data-testid="cola-palabra"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="cantidad-pedidos-palabra"]').text()).toBe('0')
    expect(wrapper.text()).toContain('No hay pedidos en espera')
  })

  it('dibuja un único renglón completo cuando hay un solo pedido', () => {
    const wrapper = montarPanel([COLA_REALISTA[0]!])

    const renglones = wrapper.findAll('[data-testid="cola-palabra"] li')
    expect(renglones).toHaveLength(1)

    const nombre = wrapper.get('[data-testid="nombre-cola-palabra"]')
    expect(nombre.text().replace(/\s+/g, ' ').trim()).toBe('María Eugenia Fernández Robledo')
    // El nombre completo sigue viajando en `title`, porque en pantalla se recorta.
    expect(nombre.element.getAttribute('title')).toBe('María Eugenia Fernández Robledo')
    expect(wrapper.get('[data-testid="banca-cola-palabra"]').text()).toBe('Banca 7')
    expect(wrapper.get('.orden-cola').text()).toBe('1')
    expect(wrapper.get('[data-testid="cantidad-pedidos-palabra"]').text()).toBe('1')
  })

  it('conserva el orden FIFO y la numeración con varios pedidos', () => {
    const wrapper = montarPanel(COLA_REALISTA)

    const nombres = wrapper
      .findAll('[data-testid="nombre-cola-palabra"]')
      .map((nodo) => nodo.text().replace(/\s+/g, ' ').trim())
    const ordenes = wrapper.findAll('.orden-cola').map((nodo) => nodo.text().trim())

    // El panel no reordena ni introduce al orador en uso en la cola.
    expect(nombres).toEqual(['María Eugenia Fernández Robledo', 'Juan Pérez'])
    expect(ordenes).toEqual(['1', '2'])
    expect(wrapper.get('[data-testid="cantidad-pedidos-palabra"]').text()).toBe('2')
    expect(wrapper.text()).not.toContain('Andrea Rueda')
  })
})

describe('Tamaño declarado del nombre de la cola (WP-064)', () => {
  /**
   * Extrae del CSS del componente el `clamp` que fija el cuerpo del nombre.
   *
   * Se lee el archivo en vez de repetir los números acá para que la regla real
   * y su demostración no puedan separarse: tocar el `clamp` sin actualizar la
   * prueba hace fallar la suite.
   */
  function leerClampDeclarado() {
    const fuente = readFileSync(rutaComponente, 'utf8')
    const bloque = fuente.match(/\.cola-palabra strong \{([\s\S]*?)\}/)
    expect(bloque, 'PanelPalabraPublico.vue debe declarar la regla .cola-palabra strong').not.toBe(
      null,
    )
    /*
      WP-097 envolvió el `clamp` en un `min()` que le agrega un techo geométrico
      en `cqi`. El `clamp` sigue siendo el que fijó WP-064 y se lo extrae igual;
      el techo se comprueba aparte, en su propia prueba.
    */
    const coincidencia = bloque![1]!.match(
      /font-size:\s*min\(\s*clamp\(\s*([\d.]+)rem\s*,\s*([\d.]+)vw\s*,\s*([\d.]+)rem\s*\)\s*,\s*[\d.]+cqi\s*\)/,
    )
    expect(
      coincidencia,
      'El nombre debe seguir dimensionado con un clamp de tres términos bajo un techo en cqi',
    ).not.toBe(null)
    const [, minimoRem, elasticoVw, maximoRem] = coincidencia!
    return {
      minimoRem: Number(minimoRem),
      elasticoVw: Number(elasticoVw),
      maximoRem: Number(maximoRem),
      bloque: bloque![1]!,
    }
  }

  it('multiplica por 1,8 los tres términos de la baseline de WP-054', () => {
    const declarado = leerClampDeclarado()

    // Multiplicar los tres términos por el mismo factor es lo que garantiza que
    // el crecimiento sea del 80 % en cualquier resolución: gane el mínimo, el
    // término elástico o el máximo, la proporción con la baseline es la misma.
    expect(declarado.minimoRem).toBeCloseTo(CLAMP_NOMBRE_WP054.minimoRem * FACTOR_NOMBRE_WP064, 4)
    expect(declarado.elasticoVw).toBeCloseTo(CLAMP_NOMBRE_WP054.elasticoVw * FACTOR_NOMBRE_WP064, 4)
    expect(declarado.maximoRem).toBeCloseTo(CLAMP_NOMBRE_WP054.maximoRem * FACTOR_NOMBRE_WP064, 4)
  })

  it('mantiene el recorte determinista que impide el desborde horizontal', () => {
    const declarado = leerClampDeclarado()

    // Un nombre más grande sin estas tres reglas ensancharía la columna o
    // pasaría a dos líneas. Son la contracara obligatoria del aumento.
    expect(declarado.bloque).toContain('white-space: nowrap')
    expect(declarado.bloque).toContain('text-overflow: ellipsis')
    expect(declarado.bloque).toContain('overflow: hidden')
  })

  it('deja intactos el círculo de orden y el cuerpo de la banca', () => {
    const fuente = readFileSync(rutaComponente, 'utf8')

    // WP-064 sólo autoriza tocar el nombre. Estas dos reglas son las que
    // podrían haberse movido "de paso" y no debían moverse: el círculo quedó
    // congelado por WP-054 y la banca conserva su cuerpo para que la diferencia
    // de jerarquía a favor del nombre sea justamente la que se buscaba.
    const circulo = fuente.match(/\.orden-cola \{([\s\S]*?)\}/)![1]!
    expect(circulo).toContain('width: 1.6rem')
    expect(circulo).toContain('height: 1.6rem')

    const banca = fuente.match(/\.referencia-cola small \{([\s\S]*?)\}/)![1]!
    expect(banca).toContain('font-size: clamp(0.74rem, 0.8vw, 0.98rem)')
  })

  /**
   * Techo geométrico agregado por WP-097.
   *
   * El `clamp` de WP-064 sigue mandando en las tres resoluciones objetivo. El
   * techo sólo actúa si la columna llegara a angostarse por debajo de lo previsto
   * y existe para que la promesa de «un nombre de 18 caracteres entra completo»
   * no dependa de la resolución ni de la tipografía disponible.
   */
  it('acota el cuerpo del nombre a una fracción del ancho del contenedor (WP-097)', () => {
    const fuente = readFileSync(rutaComponente, 'utf8')

    const bloqueNombre = fuente.match(/\.cola-palabra strong \{([\s\S]*?)\}/)![1]!
    const techo = bloqueNombre.match(/,\s*([\d.]+)cqi\s*\)/)
    expect(techo, 'El nombre debe declarar un techo en cqi').not.toBe(null)
    // 18 caracteres ocupan como máximo ~11,2 em, así que el techo no puede pasar
    // de 100/11,2 ≈ 8,9 cqi sin dejar de garantizar el encaje.
    expect(Number(techo![1])).toBeLessThanOrEqual(8.9)

    // El techo sólo tiene sentido si el panel es contenedor de consultas de ancho.
    const panel = fuente.match(/\.panel-palabra \{([\s\S]*?)\}/)![1]!
    expect(panel).toContain('container-type: inline-size')

    // Y la lista debe reservar siempre el canal de la barra de desplazamiento:
    // sin eso, el ancho útil cambiaría según la cantidad de pedidos.
    const lista = fuente.match(/\.cola-palabra \{([\s\S]*?)\}/)![1]!
    expect(lista).toContain('scrollbar-gutter: stable')
  })
})
