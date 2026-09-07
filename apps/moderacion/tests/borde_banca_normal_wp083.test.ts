/**
 * WP-083 — Borde invisible de la banca NORMAL en el cuadrante 3 de Moderación.
 *
 * La quinta ronda observó que, en Q3, la banca presente sin novedad dibujaba una línea
 * gris clara por dentro del blanco de la tarjeta, que se leía como un recuadro superpuesto
 * al bitmap institucional. La corrección aprobada es estrictamente cromática: la banca
 * `NORMAL` pinta su borde transparente, conservando el ancho de 2 px para que la geometría
 * no se mueva ni un píxel.
 *
 * Este archivo cubre las tres afirmaciones que **no** necesitan un navegador:
 *
 * 1. la regla existe y aplica exactamente a `NORMAL`, no a los otros siete estados;
 * 2. el ancho del borde sigue siendo 2 px, es decir, la corrección no achicó la caja;
 * 3. la paleta compartida `PALETA_BANCAS` no cambió, que es la forma de garantizar que la
 *    Pantalla del Recinto quedó intacta.
 *
 * El efecto visible —el color realmente pintado y la geometría idéntica— se mide en
 * `tests/playwright/ux_quinta_ronda_wp083.spec.ts`. Acá no puede medirse: Vitest corre
 * sobre jsdom, que no aplica los `<style scoped>` de un SFC ni calcula cajas.
 *
 * Por eso las dos primeras afirmaciones se hacen sobre el **texto fuente** del componente
 * productivo, importado con `?raw`, que es la misma técnica que ya usa
 * `bancas_wp045.test.ts` para acceder a la plantilla real. No es una prueba de estilo
 * escrita a mano: es el archivo que se despliega, y si alguien borra la regla o cambia el
 * ancho, esta prueba falla antes de llegar al navegador.
 */

import { describe, expect, it } from 'vitest'
import fuenteBancaConcejal from '../app/components/BancaConcejal.vue?raw'
import {
  PALETA_BANCAS,
  calcularPresentacionBanca,
  estilosBanca,
  type EstadoPrincipalBanca,
} from '@sis-leg/frontend-shared'

/** Los siete estados que conservan su borde visible tal como estaba antes del WP. */
const ESTADOS_CON_BORDE: readonly EstadoPrincipalBanca[] = [
  'AUSENTE',
  'PALABRA',
  'TEST',
  'VOTO_EMITIDO',
  'RESULTADO_POSITIVO',
  'RESULTADO_NEGATIVO',
  'RESULTADO_ABSTENCION',
]

/** Aísla el bloque `<style scoped>` del componente productivo de Moderación. */
function estilosDeLaBanca(): string {
  const coincidencia = fuenteBancaConcejal.match(/<style scoped>([\s\S]*)<\/style>/)
  if (!coincidencia?.[1]) throw new Error('No se encontró el bloque de estilos productivo')
  return coincidencia[1]
}

/** Quita comentarios CSS para que una explicación no pueda hacer pasar una prueba. */
function sinComentarios(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, '')
}

describe('Borde de la banca NORMAL en Q3 · WP-083', () => {
  it('pinta el borde transparente sólo para el estado NORMAL', () => {
    const css = sinComentarios(estilosDeLaBanca())

    // La regla existe, apunta al selector de estado y no depende de ninguna clase nueva.
    expect(css).toMatch(
      /\.banca-concejal-moderacion\[data-estado-banca='NORMAL'\]\s*\{[^}]*border-color:\s*transparent/,
    )

    /*
      Y es la única regla del componente que toca `border-color`. Se comprueba así, y no
      buscando cada estado por separado, porque el componente sí tiene otras reglas por
      estado —`AUSENTE` desatura la imagen, por ejemplo— que no tienen nada que ver con el
      borde. Lo que el WP prohíbe es apagarle el borde a otro estado, no usar el selector.
    */
    const reglasConBorde = [...css.matchAll(/([^{}]+)\{([^}]*border-color[^}]*)\}/g)].map((regla) =>
      (regla[1] ?? '').trim(),
    )
    expect(reglasConBorde).toEqual([".banca-concejal-moderacion[data-estado-banca='NORMAL']"])
    for (const estado of ESTADOS_CON_BORDE) {
      expect(reglasConBorde.join(' ')).not.toContain(estado)
    }
  })

  it('conserva el ancho de borde de 2 px, así que la tarjeta mide lo mismo', () => {
    const css = sinComentarios(estilosDeLaBanca())

    // Se cambió el color, no la caja: el borde sigue declarado con su ancho original y la
    // regla de NORMAL sólo toca `border-color`.
    expect(css).toMatch(
      /\.banca-concejal-moderacion\s*\{[^}]*border:\s*2px solid var\(--borde-banca\)/,
    )
    const reglaNormal = css.match(
      /\.banca-concejal-moderacion\[data-estado-banca='NORMAL'\]\s*\{([^}]*)\}/,
    )?.[1]
    expect(reglaNormal).toBeDefined()
    expect(reglaNormal).not.toMatch(/border-width|padding|margin|border-radius|transform|scale/)
  })

  it('no toca la paleta compartida, de modo que el Recinto no cambia', () => {
    /*
      Ésta es la prueba que impide la solución fácil y equivocada: apagar el borde
      cambiando `PALETA_BANCAS.BLANCO.borde` habría resuelto Q3 y, en el mismo acto,
      habría apagado el borde de la Pantalla del Recinto, que este WP debe dejar intacta.
      Las custom properties que salen de la paleta siguen entregando el color aprobado.
    */
    expect(PALETA_BANCAS.BLANCO.borde).toBe('#c7d2dd')

    const normal = calcularPresentacionBanca({
      presente: true,
      testActivo: false,
      esOrador: false,
      estadoRecepcion: null,
      votoEmitido: false,
      valorVotoFinal: null,
    })
    expect(normal.estado).toBe('NORMAL')
    // La banca NORMAL además no lleva etiqueta ni halo: es exactamente el caso que la
    // decisión humana delimitó, y no hace falta ninguna condición extra en el CSS.
    expect(normal.etiqueta).toBeNull()
    expect(normal.haloTest).toBe(false)
    expect(normal.haloPalabra).toBe(false)
    expect(estilosBanca(normal)['--borde-banca']).toBe('#c7d2dd')
  })
})
