/**
 * Fixtures públicas completas de `EstadoRecinto`; nunca incluyen campos privados de
 * Moderación.
 *
 * Vivían dentro de las pruebas de la Pantalla del Recinto. Desde WP-071 el puesto de
 * Apoyo Técnico sonoriza el mismo estado público y sus pruebas necesitan exactamente las
 * mismas fixtures. Mantener dos copias sería la forma más silenciosa de que una pantalla
 * quedara probada contra un contrato viejo, así que las fixtures se comparten desde acá y
 * `apps/recinto/tests/datos_prueba.ts` las reexporta para no tocar sus suites existentes.
 *
 * Este archivo es soporte de pruebas, no código de producción: no se publica por el índice
 * del paquete y ningún build de las SPA lo incluye.
 */

import type {
  ApoyoTecnicoProyectado,
  ConcejalPublico,
  EstadoRecinto,
  SonidosRecintoProyectados,
  SonorizacionRecintoProyectada,
  VotacionPublica,
} from '@botonera2/api-client'
import { EVENTOS_SONOROS_RECINTO } from '../../src/transiciones_sonoras'

/**
 * Porción técnica por defecto: transmisión apagada y sin aviso vigente (WP-056).
 *
 * Es el estado en el que arranca el backend, de modo que las fixtures existentes
 * conservan exactamente el comportamiento que ya verificaban.
 */
export function crearApoyoTecnicoPrueba(
  parcial: Partial<ApoyoTecnicoProyectado> = {},
): ApoyoTecnicoProyectado {
  return {
    transmision: parcial.transmision ?? {
      estado: 'APAGADO',
      iniciada_en: null,
      en_vivo_desde: null,
      cuenta_regresiva_segundos: null,
      segundos_restantes: null,
    },
    aviso: parcial.aviso ?? null,
  }
}

export function crearConcejalesPublicos(cantidad: number): ConcejalPublico[] {
  return Array.from({ length: cantidad }, (_, indice) => {
    const banca = indice + 1
    return {
      nombre: `Nombre${banca}`,
      apellido: `Apellido${banca}`,
      bloque: banca % 2 === 0 ? 'Bloque Azul' : 'Bloque Verde',
      banca,
      ruta_imagen: `assets/bancas/banca-${String(banca).padStart(2, '0')}.png`,
      presente: banca !== 2,
      test_activo: banca === 3,
      test_expira_en: banca === 3 ? '2026-08-27T10:00:05Z' : null,
    }
  })
}

/**
 * Configuración de audio por defecto de las fixtures (WP-065).
 *
 * Recorre el catálogo canónico del código de producción —y no una lista escrita a mano— con
 * un volumen distinto por evento, de modo que una prueba que confundiera dos sonidos se
 * note. Si alguna vez el contrato sumara o quitara un evento, las fixtures lo acompañarían
 * solas y ninguna prueba de paridad podría quedarse comparando contra una lista vieja.
 */
export function crearSonidosRecintoPrueba(
  parcial: Partial<SonidosRecintoProyectados> = {},
): SonidosRecintoProyectados {
  return {
    disponible: parcial.disponible ?? true,
    motivo: parcial.motivo ?? null,
    detalle: parcial.detalle ?? null,
    sonidos:
      parcial.sonidos ??
      EVENTOS_SONOROS_RECINTO.map((evento, indice) => ({
        evento,
        ruta: `assets/sonidos/${evento.replaceAll('_', '-')}.wav`,
        volumen: (indice * 7) % 101,
      })),
  }
}

export function crearEstadoRecintoPrueba(parcial: Partial<EstadoRecinto> = {}): EstadoRecinto {
  return {
    revision: parcial.revision ?? 1,
    generado_en: parcial.generado_en ?? '2026-08-27T10:00:00Z',
    estado_global: parcial.estado_global ?? 'SIN_PREPARAR',
    preparacion: parcial.preparacion ?? null,
    sesion: parcial.sesion ?? null,
    filas_bancas: parcial.filas_bancas ?? null,
    concejales: parcial.concejales ?? [],
    quorum: parcial.quorum ?? null,
    votacion: parcial.votacion ?? null,
    palabra: parcial.palabra ?? null,
    eventos_publicos: parcial.eventos_publicos ?? [],
    tecnico: parcial.tecnico ?? crearApoyoTecnicoPrueba(),
    sonidos: parcial.sonidos ?? crearSonidosRecintoPrueba(),
  }
}

/** Construye el DTO público exacto que entregan REST y SSE. */
export function crearVotacionPublicaPrueba(
  parcial: Partial<VotacionPublica> = {},
): VotacionPublica {
  return {
    id: parcial.id ?? 'votacion-1',
    numero_votacion: parcial.numero_votacion ?? 1,
    tipo: parcial.tipo ?? 'Despacho',
    tema: parcial.tema ?? 'Tratamiento del expediente público',
    tipo_mayoria: parcial.tipo_mayoria ?? 'SIMPLE',
    factor: parcial.factor ?? 0,
    base: parcial.base ?? 'VOTOS_COMPUTABLES',
    estado_recepcion: parcial.estado_recepcion ?? 'EN_CURSO',
    resultado: parcial.resultado ?? null,
    fecha_hora_apertura: parcial.fecha_hora_apertura ?? '2026-08-28T10:00:00Z',
    fecha_hora_cierre: parcial.fecha_hora_cierre ?? null,
    cuenta_regresiva_hasta: parcial.cuenta_regresiva_hasta ?? null,
    resultado_visible_hasta: parcial.resultado_visible_hasta ?? null,
    bancas_voto_emitido: parcial.bancas_voto_emitido ?? [],
    votos_individuales: parcial.votos_individuales ?? null,
    conteos: parcial.conteos ?? null,
    voto_presidencial: parcial.voto_presidencial ?? null,
  }
}

/**
 * Convierte una fixture pública del Recinto en la subproyección sonora del puesto técnico.
 *
 * ## Por qué existe
 *
 * WP-074 dejó a Apoyo Técnico con una sola suscripción: la sonorización ya no llega en un
 * `EstadoRecinto` propio sino recortada dentro de `EstadoTecnico.sonorizacion`. La tabla
 * canónica de los quince escenarios sigue estando escrita sobre estados del Recinto, que es
 * donde la semántica está definida, así que las pruebas del puesto técnico necesitan
 * traducir cada escenario a la forma que ahora reciben.
 *
 * Esta función aplica exactamente el mismo recorte que hace el backend en
 * `_sonorizacion`. Que las dos coincidan no se confía a la vista: lo comprueban las pruebas
 * backend de la proyección, que verifican campo por campo qué viaja y qué no. Acá el
 * recorte existe sólo para poder ejecutar la misma tabla de escenarios contra las dos
 * superficies y seguir demostrando paridad 1:1.
 */
export function proyectarSonorizacionTecnica(estado: EstadoRecinto): SonorizacionRecintoProyectada {
  return {
    revision: estado.revision,
    estado_global: estado.estado_global,
    tecnico: estado.tecnico,
    palabra:
      estado.palabra === null
        ? null
        : {
            cola: estado.palabra.cola.map((persona) => ({ banca: persona.banca })),
            orador: estado.palabra.orador === null ? null : { banca: estado.palabra.orador.banca },
          },
    votacion:
      estado.votacion === null
        ? null
        : { id: estado.votacion.id, estado_recepcion: estado.votacion.estado_recepcion },
    concejales: estado.concejales.map((concejal) => ({
      banca: concejal.banca,
      presente: concejal.presente,
    })),
    sonidos: estado.sonidos,
  }
}
