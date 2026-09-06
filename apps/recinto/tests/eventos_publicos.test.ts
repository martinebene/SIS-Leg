/**
 * Regresiones DOM de la proyección pública de eventos y de su retiro visual.
 *
 * WP-050 sacó la franja de eventos de la Pantalla del Recinto, pero **solo de
 * la vista**: el backend, el DTO y `EstadoRecinto.eventos_publicos` siguen
 * intactos. Por eso este archivo cubre dos cosas distintas:
 *
 * 1. que `PanelEventosPublicos` continúe sanitizando el DTO (el componente se
 *    conserva versionado porque el dato del contrato sigue existiendo);
 * 2. que la pantalla ya no lo renderice ni le reserve altura, aun cuando el
 *    snapshot traiga eventos.
 */

import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import type { EventoPublicoProyectado } from '@sis-leg/api-client'
import PanelEventosPublicos from '../app/components/PanelEventosPublicos.vue'
import PantallaRecinto from '../app/components/PantallaRecinto.vue'
import { crearConcejalesPublicos, crearEstadoRecintoPrueba } from './datos_prueba'

function crearEvento(indice: number): EventoPublicoProyectado {
  return {
    seq: indice,
    timestamp: `2026-08-31 10:00:${String(indice).padStart(2, '0')}`,
    categoria: indice % 2 === 0 ? 'PALABRA' : 'SESION',
    codigo_evento: indice % 2 === 0 ? 'PEDIDO_PALABRA_REGISTRADO' : 'SESION_ABIERTA',
    texto: indice % 2 === 0 ? 'Pedido de palabra registrado' : 'Sesión abierta',
  }
}

describe('Eventos públicos del Recinto', () => {
  it('no ofrece selector y renderiza exclusivamente los cinco campos sanitizados', () => {
    const eventoConCampoAjeno = {
      ...crearEvento(1),
      mensaje: 'DNI 99999999 dispositivo USB tecla 1 sentido POSITIVO',
      nivel: 'L3',
      etiqueta: 'INTERNA',
    } as unknown as EventoPublicoProyectado
    const wrapper = mount(PanelEventosPublicos, { props: { eventos: [eventoConCampoAjeno] } })

    expect(wrapper.find('select').exists()).toBe(false)
    expect(wrapper.get('[data-testid="lista-eventos-publicos"]').text()).toContain('Sesión abierta')
    for (const secreto of ['99999999', 'USB', 'tecla', 'sentido', 'POSITIVO', 'INTERNA', 'L3']) {
      expect(wrapper.html()).not.toContain(secreto)
    }
    expect(wrapper.findAll('[data-testid="lista-eventos-publicos"] li')).toHaveLength(1)
  })

  it('deja de dibujar la franja de eventos y no le reserva una tercera fila', async () => {
    vi.useFakeTimers()
    vi.setSystemTime('2030-01-01T00:00:00Z')
    const estadoPreparando = crearEstadoRecintoPrueba({
      generado_en: '2026-08-31T10:00:00',
      estado_global: 'PREPARANDO',
      preparacion: {
        fecha_hora_inicio: '2026-08-31T09:55:00',
        numero_sesion: 60,
        presidencia: 'Presidencia',
        secretaria_legislativa: 'Secretaría',
      },
      filas_bancas: [2],
      concejales: crearConcejalesPublicos(2),
      quorum: { cantidad_presentes: 1, requerido: 2, alcanzado: false },
      // El snapshot sigue trayendo la proyección completa: el contrato público
      // no cambió, únicamente dejó de dibujarse.
      eventos_publicos: Array.from({ length: 20 }, (_, indice) => crearEvento(indice + 1)),
    })
    const wrapper = mount(PantallaRecinto, {
      props: { estado: estadoPreparando, estadoConexion: 'CONECTADO', desactualizado: false },
    })

    const contenido = wrapper.get('.contenido-recinto')
    // Quedan exactamente dos regiones, en el orden canónico. Si alguien volviera
    // a agregar una fila reservada (aunque estuviera vacía), esto falla.
    expect(
      Array.from(contenido.element.children).map((elemento) =>
        elemento.getAttribute('data-testid'),
      ),
    ).toEqual(['franja-votacion-quorum', 'zona-principal-recinto'])
    expect(wrapper.find('[data-testid="franja-eventos-publicos"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="panel-eventos-publicos"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="lista-eventos-publicos"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="cabecera-tiempo-sesion"]').exists()).toBe(false)
    // El dato sigue disponible para quien lo necesite: no se tocó el contrato.
    expect(estadoPreparando.eventos_publicos).toHaveLength(20)

    await wrapper.setProps({
      estado: crearEstadoRecintoPrueba({ revision: 0, estado_global: 'SIN_PREPARAR' }),
    })
    expect(wrapper.find('.contenido-recinto').exists()).toBe(false)
    wrapper.unmount()
    vi.useRealTimers()
  })
})
