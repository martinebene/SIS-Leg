/**
 * Pruebas del acceso de ayuda dentro de la cabecera de Moderación (WP-067).
 *
 * El contrato del acceso en sí —destino, apertura en pestaña nueva y texto accesible— se
 * verifica una sola vez, en `packages/frontend-shared/tests/acceso_manual_wp067.test.ts`.
 * Acá se comprueba lo que sólo puede afirmarse sobre esta cabecera concreta:
 *
 * 1. que el acceso exista;
 * 2. que sea el **último** elemento de la barra, es decir, su extremo derecho;
 * 3. que agregarlo no haya desplazado ni eliminado ningún indicador anterior.
 *
 * El punto 3 es la red de seguridad del WP: sumar un elemento a una cabecera densa no
 * puede costar información vigente. La medición geométrica a 1366×768 y a 1920×1080 vive
 * en `tests/playwright/manual_usuario_wp067.spec.ts`, porque el DOM de Vitest no calcula
 * cajas y cualquier afirmación sobre píxeles sería falsa.
 */

import { describe, expect, it } from 'vitest'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { RUTA_MANUAL } from '@sis-leg/frontend-shared'
import CabeceraModeracion from '../app/components/CabeceraModeracion.vue'

/** Props que activan todos los indicadores condicionales a la vez. */
function propsCompletas(): Record<string, unknown> {
  return {
    estadoConexion: 'CONECTADO',
    estadoGlobal: 'SESION_ABIERTA',
    revision: 12,
    desactualizado: true,
    quorum: { cantidad_presentes: 9, requerido: 7, alcanzado: true },
    totalConcejales: 12,
    presidencia: 'Presidencia de ejemplo',
    secretariaLegislativa: 'Secretaría de ejemplo',
    generadoEn: '2026-09-04T12:30:15',
    fechaHoraApertura: '2026-09-04T12:00:00',
    numeroSesion: 8,
    estadoTransmision: 'EN_VIVO',
  }
}

async function renderizar(props: Record<string, unknown>): Promise<string> {
  return renderToString(createSSRApp({ render: () => h(CabeceraModeracion, props) }))
}

describe('Acceso al manual desde la cabecera de Moderación (WP-067)', () => {
  it('incluye el acceso de ayuda apuntando al manual', async () => {
    const html = await renderizar(propsCompletas())

    expect(html).toContain('data-testid="acceso-manual"')
    expect(html).toContain(`href="${RUTA_MANUAL}"`)
    expect(html).toContain('target="_blank"')
  })

  it('lo coloca en el extremo derecho, después del indicador de conexión', async () => {
    const html = await renderizar(propsCompletas())

    const posicionConexion = html.indexOf('data-testid="estado-conexion"')
    const posicionAcceso = html.indexOf('data-testid="acceso-manual"')

    expect(posicionConexion).toBeGreaterThan(-1)
    expect(posicionAcceso).toBeGreaterThan(posicionConexion)
    // Ningún otro elemento identificado aparece después: la ayuda cierra la barra.
    const posteriorAlAcceso = html.slice(posicionAcceso + 'data-testid="acceso-manual"'.length)
    expect(posteriorAlAcceso).not.toContain('data-testid="')
  })

  it('aparece también cuando la cabecera está en su versión mínima', async () => {
    // En `SIN_PREPARAR` casi todos los indicadores condicionales se omiten. La ayuda no es
    // condicional: se necesita justamente cuando todavía no se sabe qué hacer.
    const html = await renderizar({
      estadoConexion: 'INICIAL',
      estadoGlobal: 'SIN_PREPARAR',
      revision: null,
      desactualizado: false,
    })

    expect(html).toContain('data-testid="acceso-manual"')
    expect(html).not.toContain('data-testid="cabecera-quorum"')
  })

  it('no desplaza ni elimina ningún indicador anterior', async () => {
    const html = await renderizar(propsCompletas())

    for (const identificador of [
      'cabecera-moderacion',
      'cabecera-numero-sesion',
      'cabecera-quorum',
      'alerta-desactualizado',
      'cabecera-presidencia',
      'cabecera-secretaria',
      'cabecera-tiempo-sesion',
      'cabecera-fecha-hora',
      'cabecera-transmision',
      'estado-conexion',
    ]) {
      expect(html).toContain(`data-testid="${identificador}"`)
    }
  })
})
