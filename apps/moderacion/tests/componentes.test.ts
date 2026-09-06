/**
 * Pruebas unitarias de renderizado para los componentes visuales del Shell de Moderación.
 *
 * Utiliza el renderizador nativo de Vue 3 (renderToString / createSSRApp) en entorno Node,
 * validando que los componentes generen la estructura semántica, textos, badges y estados
 * esperados sin dependencias externas adicionales.
 *
 * Valida:
 * 1. Cabecera compacta con estado inicial sin snapshot (guion en estado global).
 * 2. Cabecera con estado conectado y estado global confirmado.
 * 3. Cabecera con advertencia de desactualizado durante reconexión.
 * 4. Los cuatro paneles y sus identidades visuales estables.
 *
 * Los datos globales condicionales de la cabecera (reloj, tiempo de sesión, quórum y
 * autoridades) se prueban de forma dedicada y con reloj controlado en `cabecera.test.ts`.
 */

import { describe, it, expect } from 'vitest'
import { createSSRApp, h, type Component } from 'vue'
import { renderToString } from 'vue/server-renderer'
import CabeceraModeracion from '../app/components/CabeceraModeracion.vue'
import PanelContenedor from '../app/components/PanelContenedor.vue'
import PanelSesionVotacion from '../app/components/PanelSesionVotacion.vue'
import PanelOrdenDelDia from '../app/components/PanelOrdenDelDia.vue'
import PanelRecintoPalabra from '../app/components/PanelRecintoPalabra.vue'
import PanelEventos from '../app/components/PanelEventos.vue'
import type { EstadoModeracion } from '@sis-leg/api-client'

async function renderizarComponente(
  componente: Component,
  props: Record<string, unknown> = {},
  slots: Record<string, () => unknown> = {},
) {
  const app = createSSRApp({
    render() {
      return h(componente, props, slots)
    },
  })
  return renderToString(app)
}

function crearEstadoFixture(parcial: Partial<EstadoModeracion> = {}): EstadoModeracion {
  return {
    revision: parcial.revision ?? 5,
    generado_en: parcial.generado_en ?? '2026-08-24T12:00:00Z',
    estado_global: parcial.estado_global ?? 'PREPARANDO',
    preparacion: parcial.preparacion ?? {
      numero_sesion: 42,
      presidencia: 'Dra. García',
      secretaria_legislativa: 'Lic. Pérez',
    },
    sesion: parcial.sesion ?? null,
    configuracion: parcial.configuracion ?? null,
    concejales: parcial.concejales ?? [
      {
        banca: 1,
        dni: '12345678',
        nombre: 'Juan',
        apellido: 'López',
        nombre_mostrar: 'Juan López',
        bloque: 'Bloque A',
        ruta_imagen: '/fotos/1.jpg',
        dispositivo: 'dev01',
        presente: true,
        test_visual_activo: false,
      },
    ],
    quorum: parcial.quorum ?? {
      cantidad_presentes: 8,
      requerido: 7,
      alcanzado: true,
    },
    votacion: parcial.votacion ?? null,
    palabra: parcial.palabra ?? {
      orador: {
        dni: '12345678',
        nombre: 'Juan',
        apellido: 'López',
        banca: 1,
      },
      cola: [],
    },
    orden_del_dia: parcial.orden_del_dia ?? [
      {
        nro_votacion: 1,
        tipo: 'Proyecto',
        tema: 'Presupuesto Anual',
        tipo_mayoria: 'SIMPLE',
        factor: 0,
        base: 'VOTOS_COMPUTABLES',
      },
    ],
    eventos_recientes: parcial.eventos_recientes ?? [
      {
        seq: 101,
        timestamp: '2026-08-24T12:00:01Z',
        nivel: 'L3',
        etiqueta: 'SESION',
        codigo_evento: 'PREPARACION_INICIADA',
        mensaje: 'Preparación del recinto iniciada',
      },
    ],
    auditoria: parcial.auditoria ?? {
      disponible: true,
      directorio: '/tmp',
      ultimo_error: null,
    },
    remapeo: parcial.remapeo ?? null,
    capacidades: parcial.capacidades ?? {
      preparar_sala: { habilitada: false, motivos: [] },
      actualizar_preparacion: { habilitada: true, motivos: [] },
      cancelar_preparacion: { habilitada: true, motivos: [] },
      abrir_sesion: { habilitada: true, motivos: [] },
      actualizar_sesion: { habilitada: false, motivos: [] },
      cerrar_sesion: { habilitada: false, motivos: [] },
      cargar_orden_del_dia: { habilitada: true, motivos: [] },
      descartar_orden_del_dia: { habilitada: true, motivos: [] },
      abrir_votacion: { habilitada: false, motivos: [] },
      finalizar_votacion: { habilitada: false, motivos: [] },
      desempatar: { habilitada: false, motivos: [] },
      otorgar_palabra: { habilitada: true, motivos: [] },
      quitar_palabra: { habilitada: true, motivos: [] },
      iniciar_remapeo: { habilitada: true, motivos: [] },
      confirmar_remapeo: { habilitada: false, motivos: [] },
      cancelar_remapeo: { habilitada: false, motivos: [] },
    },
  }
}

describe('Componentes del Shell de Moderación', () => {
  describe('CabeceraModeracion', () => {
    it('no inventa contexto institucional antes del primer snapshot', async () => {
      const html = await renderizarComponente(CabeceraModeracion, {
        estadoConexion: 'INICIAL',
        estadoGlobal: null,
        revision: null,
        desactualizado: false,
      })

      // WP-047: identidad, reloj y conexión permanecen; estado y número no se inventan.
      expect(html).not.toContain('SIS-Leg')
      expect(html).toContain('Moderación')
      expect(html).not.toContain('data-testid="estado-global"')
      expect(html).not.toContain('data-testid="cabecera-numero-sesion"')
      // WP-036: la revisión ya no ocupa espacio permanente en la vista principal.
      expect(html).not.toContain('data-testid="revision-estado"')
      expect(html).toContain('Conectando')
      expect(html).not.toContain('data-testid="alerta-desactualizado"')
    })

    it('retira el estado global redundante y conserva la revisión como detalle emergente', async () => {
      const html = await renderizarComponente(CabeceraModeracion, {
        estadoConexion: 'CONECTADO',
        estadoGlobal: 'SESION_ABIERTA',
        revision: 142,
        desactualizado: false,
      })

      expect(html).not.toContain('Sesión abierta')
      expect(html).not.toContain('data-testid="estado-global"')
      expect(html).toContain('Conectado')
      // La revisión sigue disponible para diagnóstico sin ocupar densidad permanente.
      expect(html).toContain('title="Conectado · revisión 142"')
      expect(html).not.toContain('data-testid="alerta-desactualizado"')
    })

    it('muestra alerta visible de desactualizado durante reconexión', async () => {
      const html = await renderizarComponente(CabeceraModeracion, {
        estadoConexion: 'RECONECTANDO',
        estadoGlobal: 'SESION_ABIERTA',
        revision: 142,
        desactualizado: true,
      })

      expect(html).toContain('data-testid="alerta-desactualizado"')
      expect(html).toContain('Estado desactualizado')
      expect(html).toContain('Reconectando')
    })
  })

  describe('PanelContenedor', () => {
    it('renderiza título, subtítulo, badge y contenido del slot', async () => {
      const html = await renderizarComponente(
        PanelContenedor,
        {
          titulo: 'Título de Prueba',
          subtitulo: 'Subtítulo descriptivo',
          badge: 'Activo',
          dataTestid: 'panel-prueba',
        },
        {
          default: () => h('p', { class: 'contenido-slot' }, 'Contenido interno'),
        },
      )

      expect(html).toContain('data-testid="panel-prueba"')
      expect(html).toContain('Título de Prueba')
      expect(html).toContain('Subtítulo descriptivo')
      expect(html).toContain('Activo')
      expect(html).toContain('Contenido interno')
    })
  })

  describe('PanelSesionVotacion', () => {
    it('renderiza el cuadrante de sesión y votación con sus datos', async () => {
      const estado = crearEstadoFixture()
      const html = await renderizarComponente(PanelSesionVotacion, { estado })

      expect(html).toContain('data-testid="panel-sesion-votacion"')
      expect(html).toContain('Sesión y votación')
      expect(html).toContain('Preparando el recinto')
      expect(html).toContain('Dra. García')
    })
  })

  describe('PanelOrdenDelDia', () => {
    it('renderiza los puntos confirmados sin ofrecer carga o reemplazo', async () => {
      const estado = crearEstadoFixture()
      const html = await renderizarComponente(PanelOrdenDelDia, { estado })

      expect(html).toContain('data-testid="panel-orden-del-dia"')
      expect(html).toContain('Orden del Día')
      expect(html).toContain('Presupuesto Anual')
      expect(html).toContain('1 puntos')
      expect(html).toContain('Quitar Orden del Día')
      expect(html).not.toContain('input-archivo-orden-dia')
      expect(html).not.toContain('Reemplazar')
      expect(html).not.toContain('Seleccionar y copiar al borrador')
    })

    it('renderiza únicamente la carga compacta cuando el snapshot no contiene puntos', async () => {
      const estado = crearEstadoFixture({ orden_del_dia: [] })
      const html = await renderizarComponente(PanelOrdenDelDia, { estado })

      expect(html).toContain('data-testid="carga-orden-dia"')
      expect(html).toContain('data-testid="input-archivo-orden-dia"')
      expect(html).toContain('data-testid="btn-cargar-orden-dia"')
      expect(html).not.toContain('Orden del Día opcional')
      expect(html).not.toContain('btn-quitar-orden-dia')
    })

    it('tolera y renderiza puntos con números de votación duplicados o no correlativos (M-2)', async () => {
      const estado = crearEstadoFixture({
        orden_del_dia: [
          {
            nro_votacion: 1,
            tipo: 'Proyecto',
            tema: 'Primer tema con nro 1',
            tipo_mayoria: 'SIMPLE',
            factor: 0,
            base: 'VOTOS_COMPUTABLES',
          },
          {
            nro_votacion: 1,
            tipo: 'Resolución',
            tema: 'Segundo tema con nro 1 repetido',
            tipo_mayoria: 'ESPECIAL',
            factor: 0.66,
            base: 'PRESENTES',
          },
        ],
      })
      const html = await renderizarComponente(PanelOrdenDelDia, { estado })

      expect(html).toContain('Primer tema con nro 1')
      expect(html).toContain('Segundo tema con nro 1 repetido')
      expect(html).toContain('2 puntos')
      expect(html).toContain('Factor 0.66 · Base PRESENTES')
    })
  })

  describe('PanelRecintoPalabra', () => {
    it('renderiza bancas y orador sin repetir el quórum global de la cabecera', async () => {
      const estado = crearEstadoFixture()
      const html = await renderizarComponente(PanelRecintoPalabra, { estado })

      expect(html).toContain('data-testid="panel-recinto-palabra"')
      expect(html).toContain('Recinto y palabra')
      expect(html).toContain('Juan López')
      // WP-036: el quórum es un dato global y sólo se presenta en la cabecera.
      expect(html).not.toContain('Quórum alcanzado')
      expect(html).not.toContain('presentes')
    })
  })

  describe('PanelEventos', () => {
    it('renderiza los eventos recientes auditados en su listado', async () => {
      const estado = crearEstadoFixture()
      const html = await renderizarComponente(PanelEventos, { estado })

      expect(html).toContain('data-testid="panel-eventos"')
      expect(html).toContain('Eventos')
      expect(html).toContain('#101')
      expect(html).toContain('PREPARACION_INICIADA')
      expect(html).toContain('Preparación del recinto iniciada')
    })
  })
})
