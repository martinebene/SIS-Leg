/**
 * Presentación compartida de la franja segura de eventos (WP-052 / WP-056).
 *
 * Estas pruebas fijan el contrato que hace imposible que Moderación y el puesto de Apoyo
 * Técnico muestren franjas distintas: mismo filtro acumulativo, mismo orden y misma
 * detección de actividad nueva.
 */

import { describe, expect, it } from 'vitest'
import type { EventoRecienteProyectado } from '@sis-leg/api-client'
import {
  filtrarEventosPorNivel,
  hayActividadNueva,
  NIVELES_POR_FILTRO,
  seqMaximoEventos,
} from '../src/eventos_seguros'

/** Construye un evento proyectado mínimo, sin hecho estructurado ni icono. */
function evento(seq: number, nivel: string): EventoRecienteProyectado {
  return {
    seq,
    timestamp: '2026-09-02 10:00:00',
    nivel,
    etiqueta: 'SISTEMA',
    codigo_evento: `EVENTO_${seq}`,
    mensaje: `Mensaje ${seq}`,
    hecho: null,
  }
}

const EVENTOS = [evento(1, 'L1'), evento(2, 'L2'), evento(3, 'L3'), evento(4, 'L1')]

describe('filtrarEventosPorNivel', () => {
  it('aplica la acumulación institucional L1 ⊇ L2 ⊇ L3', () => {
    expect(NIVELES_POR_FILTRO.L3).toEqual(['L3'])
    expect(NIVELES_POR_FILTRO.L2).toEqual(['L2', 'L3'])
    expect(NIVELES_POR_FILTRO.L1).toEqual(['L1', 'L2', 'L3'])

    expect(filtrarEventosPorNivel(EVENTOS, 'L3').map((e) => e.seq)).toEqual([3])
    expect(filtrarEventosPorNivel(EVENTOS, 'L2').map((e) => e.seq)).toEqual([3, 2])
    expect(filtrarEventosPorNivel(EVENTOS, 'L1').map((e) => e.seq)).toEqual([4, 3, 2, 1])
  })

  it('ordena del más nuevo al más viejo aunque el backend envíe otro orden', () => {
    const desordenados = [evento(2, 'L3'), evento(9, 'L3'), evento(5, 'L3')]

    expect(filtrarEventosPorNivel(desordenados, 'L3').map((e) => e.seq)).toEqual([9, 5, 2])
  })

  it('no muta ni reordena la colección autoritativa recibida', () => {
    const original = [evento(2, 'L3'), evento(9, 'L3')]
    const copiaEsperada = original.map((e) => e.seq)

    filtrarEventosPorNivel(original, 'L3')

    expect(original.map((e) => e.seq)).toEqual(copiaEsperada)
  })

  it('tolera un snapshot todavía inexistente', () => {
    expect(filtrarEventosPorNivel(null, 'L1')).toEqual([])
    expect(filtrarEventosPorNivel(undefined, 'L1')).toEqual([])
  })
})

describe('seqMaximoEventos', () => {
  it('devuelve el mayor seq del snapshot completo', () => {
    expect(seqMaximoEventos(EVENTOS)).toBe(4)
  })

  it('distingue "todavía no llegó nada" de un seq cero', () => {
    expect(seqMaximoEventos([])).toBeNull()
    expect(seqMaximoEventos([evento(0, 'L1')])).toBe(0)
  })
})

describe('hayActividadNueva', () => {
  it('reconoce el primer snapshot con eventos', () => {
    expect(hayActividadNueva(7, null)).toBe(true)
  })

  it('reconoce un seq mayor al último observado', () => {
    expect(hayActividadNueva(8, 7)).toBe(true)
  })

  it('ignora un snapshot sin novedades o con la secuencia reiniciada', () => {
    expect(hayActividadNueva(7, 7)).toBe(false)
    // Reinicio de contexto operativo: la lista se reemplazó entera, no llegó actividad.
    expect(hayActividadNueva(2, 90)).toBe(false)
    expect(hayActividadNueva(null, 7)).toBe(false)
  })
})
