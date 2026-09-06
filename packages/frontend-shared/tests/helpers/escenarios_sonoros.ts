/**
 * Los quince escenarios sonoros canónicos del recinto (WP-071).
 *
 * ## Para qué existe esta tabla
 *
 * WP-071 exige paridad **1:1** entre la Pantalla del Recinto y el puesto de Apoyo Técnico:
 * un mismo hecho nuevo tiene que producir el mismo sonido en las dos pantallas. Una forma
 * frágil de comprobarlo sería escribir dos suites parecidas y confiar en que sigan
 * pareciéndose. Una forma sólida es tener **una sola** tabla de escenarios y ejecutarla
 * contra las dos superficies: si alguna vez una de las dos dejara de reproducir un evento,
 * la misma línea fallaría en su suite.
 *
 * Cada escenario describe el hecho mínimo que produce un evento: un par de snapshots
 * consecutivos y, para el tic de la cuenta regresiva, el cambio del número visible. No
 * pretende cubrir los casos límite de cada transición —eso ya lo hacen en detalle las
 * pruebas de `transiciones_sonoras_wp066`—; pretende cubrir los quince eventos, ninguno
 * menos.
 *
 * Este archivo es soporte de pruebas: no se publica por el índice del paquete y ningún
 * build de las SPA lo incluye.
 */

import type { EstadoRecinto, EstadoPalabraPublico, VotacionPublica } from '@sis-leg/api-client'
import type { EventoSonoroRecinto } from '../../src/transiciones_sonoras'
import {
  crearApoyoTecnicoPrueba,
  crearConcejalesPublicos,
  crearEstadoRecintoPrueba,
  crearVotacionPublicaPrueba,
} from './estado_recinto'

/**
 * Un hecho institucional y el sonido que debe producir.
 *
 * `previo` es el estado ya adoptado y ya sonorizado; `actual` es la revisión siguiente. La
 * revisión de `actual` siempre es mayor, porque una revisión repetida está deliberadamente
 * excluida de sonorizar y tiene su propia prueba.
 */
export interface EscenarioSonoro {
  /** Evento que debe reproducirse exactamente una vez. */
  evento: EventoSonoroRecinto
  /** Descripción legible del hecho, usada como nombre del caso. */
  descripcion: string
  /** Estado ya adoptado antes del hecho. */
  previo: EstadoRecinto
  /** Estado adoptado después del hecho. */
  actual: EstadoRecinto
  /**
   * Cambio del número visible de la cuenta regresiva, cuando el evento nace de ahí.
   *
   * Sólo lo usa `transmision_cuenta_regresiva_tic`: es el único de los quince que no se
   * deduce comparando snapshots, porque el backend no publica una revisión por segundo.
   */
  segundos?: { previo: number; actual: number }
}

/** Sesión abierta con doce bancas, base de los hechos que sólo existen dentro de sesión. */
function enSesion(parcial: Partial<EstadoRecinto> = {}): EstadoRecinto {
  return crearEstadoRecintoPrueba({
    estado_global: 'SESION_ABIERTA',
    concejales: crearConcejalesPublicos(12),
    ...parcial,
  })
}

/** Cola de palabra con las bancas indicadas y, opcionalmente, un orador en uso. */
function palabra(bancas: number[], bancaOrador: number | null = null): EstadoPalabraPublico {
  const persona = (banca: number) => ({
    nombre: `Nombre${banca}`,
    apellido: `Apellido${banca}`,
    banca,
  })
  return {
    cola: bancas.map(persona),
    orador: bancaOrador === null ? null : persona(bancaOrador),
  }
}

/** Votación pública con la identidad y la recepción indicadas. */
function votacion(
  id: string,
  estadoRecepcion: VotacionPublica['estado_recepcion'],
): VotacionPublica {
  return crearVotacionPublicaPrueba({ id, estado_recepcion: estadoRecepcion })
}

/** Copia el padrón cambiando la presencia de una banca concreta. */
function conPresencia(base: EstadoRecinto, banca: number, presente: boolean): EstadoRecinto {
  return {
    ...base,
    concejales: base.concejales.map((concejal) =>
      concejal.banca === banca ? { ...concejal, presente } : concejal,
    ),
  }
}

/** Aviso técnico vigente con el identificador indicado. */
function conAviso(base: EstadoRecinto, avisoId: string | null): EstadoRecinto {
  return {
    ...base,
    tecnico: crearApoyoTecnicoPrueba({
      aviso:
        avisoId === null
          ? null
          : {
              aviso_id: avisoId,
              texto: 'Aviso de prueba',
              destino: 'RECINTO' as const,
              publicado_en: '2026-09-05T10:00:00Z',
              expira_en: null,
              segundos_restantes: null,
            },
    }),
  }
}

/** Estado técnico con la transmisión en el estado indicado. */
function conTransmision(
  base: EstadoRecinto,
  estado: 'APAGADO' | 'CUENTA_REGRESIVA' | 'EN_VIVO',
): EstadoRecinto {
  return {
    ...base,
    tecnico: crearApoyoTecnicoPrueba({
      transmision: {
        estado,
        iniciada_en: estado === 'APAGADO' ? null : '2026-09-05T10:00:00Z',
        en_vivo_desde: estado === 'EN_VIVO' ? '2026-09-05T10:00:00Z' : null,
        cuenta_regresiva_segundos: null,
        segundos_restantes: null,
      },
    }),
  }
}

/** Devuelve el mismo estado con la revisión indicada. */
function conRevision(estado: EstadoRecinto, revision: number): EstadoRecinto {
  return { ...estado, revision }
}

/**
 * Construye la tabla completa, con revisiones consecutivas ya asignadas.
 *
 * Se expone como función y no como constante para que cada suite trabaje sobre objetos
 * propios: los estados son inmutables por convención, pero una prueba que los compartiera
 * podría enmascarar un defecto de reactividad si alguna vez dejaran de serlo.
 */
export function crearEscenariosSonoros(): EscenarioSonoro[] {
  const sesion = enSesion()
  const sinPreparar = crearEstadoRecintoPrueba()
  const preparando = crearEstadoRecintoPrueba({ estado_global: 'PREPARANDO' })

  const tabla: EscenarioSonoro[] = [
    {
      evento: 'preparacion_iniciada',
      descripcion: 'el operador empieza a preparar la sala',
      previo: sinPreparar,
      actual: preparando,
    },
    {
      evento: 'sesion_abierta',
      descripcion: 'la Presidencia abre la sesión reglamentariamente',
      previo: preparando,
      actual: enSesion(),
    },
    {
      evento: 'sesion_cerrada',
      descripcion: 'la sesión termina y el sistema vuelve a SIN_PREPARAR',
      previo: sesion,
      actual: sinPreparar,
    },
    {
      evento: 'aviso_tecnico_publicado',
      descripcion: 'Apoyo Técnico publica un aviso hacia el recinto',
      previo: conAviso(sesion, null),
      actual: conAviso(sesion, 'aviso-1'),
    },
    {
      evento: 'aviso_tecnico_retirado',
      descripcion: 'el aviso vigente se cancela o vence',
      previo: conAviso(sesion, 'aviso-1'),
      actual: conAviso(sesion, null),
    },
    {
      evento: 'transmision_iniciada',
      descripcion: 'la transmisión pasa a EN VIVO',
      previo: conTransmision(sesion, 'APAGADO'),
      actual: conTransmision(sesion, 'EN_VIVO'),
    },
    {
      evento: 'transmision_detenida',
      descripcion: 'la transmisión se detiene',
      previo: conTransmision(sesion, 'EN_VIVO'),
      actual: conTransmision(sesion, 'APAGADO'),
    },
    {
      evento: 'transmision_cuenta_regresiva_tic',
      descripcion: 'el número visible de la cuenta regresiva baja un segundo',
      previo: conTransmision(sesion, 'CUENTA_REGRESIVA'),
      actual: conTransmision(sesion, 'CUENTA_REGRESIVA'),
      segundos: { previo: 4, actual: 3 },
    },
    {
      evento: 'pedido_palabra_registrado',
      descripcion: 'una banca pide la palabra',
      previo: enSesion({ palabra: palabra([]) }),
      actual: enSesion({ palabra: palabra([3]) }),
    },
    {
      evento: 'pedido_palabra_retirado',
      descripcion: 'una banca retira su pedido sin haber hablado',
      previo: enSesion({ palabra: palabra([3]) }),
      actual: enSesion({ palabra: palabra([]) }),
    },
    {
      evento: 'uso_palabra_otorgado',
      descripcion: 'la Presidencia otorga el uso de la palabra',
      previo: enSesion({ palabra: palabra([3]) }),
      actual: enSesion({ palabra: palabra([], 3) }),
    },
    {
      evento: 'votacion_abierta',
      descripcion: 'se abre la recepción de votos',
      previo: enSesion({ votacion: null }),
      actual: enSesion({ votacion: votacion('votacion-1', 'EN_CURSO') }),
    },
    {
      evento: 'votacion_cerrada',
      descripcion: 'se cierra la recepción de votos',
      previo: enSesion({ votacion: votacion('votacion-1', 'EN_CURSO') }),
      actual: enSesion({ votacion: votacion('votacion-1', 'CERRADA') }),
    },
    {
      evento: 'concejal_ausente',
      descripcion: 'una banca presente marca su ausencia',
      previo: conPresencia(sesion, 5, true),
      actual: conPresencia(sesion, 5, false),
    },
    {
      evento: 'concejal_presente',
      descripcion: 'una banca ausente marca su presencia',
      previo: conPresencia(sesion, 5, false),
      actual: conPresencia(sesion, 5, true),
    },
  ]

  return tabla.map((escenario) => ({
    ...escenario,
    previo: conRevision(escenario.previo, 10),
    actual: conRevision(escenario.actual, 11),
  }))
}

/**
 * Comprueba que la tabla cubra exactamente los quince eventos del contrato.
 *
 * Se exporta para que cada suite lo afirme por su cuenta: es la garantía de que «paridad
 * 1:1» significa los quince eventos y no los que alguien recordó escribir.
 */
export function eventosCubiertos(escenarios: EscenarioSonoro[]): EventoSonoroRecinto[] {
  return escenarios.map((escenario) => escenario.evento)
}
