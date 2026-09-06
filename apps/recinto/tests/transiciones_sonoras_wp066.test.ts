/**
 * Semántica de disparo de los sonidos del Recinto (WP-066).
 *
 * Estas pruebas fijan la parte más delicada del WP: qué cuenta como transición y qué no.
 * Trabajan sobre la función pura `detectarTransicionesSonoras`, que compara dos snapshots
 * públicos consecutivos, así que cada caso se lee como «este estado, después este otro,
 * debe sonar exactamente esto».
 *
 * Los catorce eventos que nacen de comparar snapshots se cubren acá. El decimoquinto —el
 * tic de la cuenta regresiva— no se deduce de dos snapshots sino del número visible que
 * baja localmente, y se verifica en `sonidos_recinto_wp066.test.ts`.
 */

import { describe, expect, it } from 'vitest'
import type {
  AvisoTecnicoProyectado,
  EstadoRecinto,
  EstadoTransmision,
  PersonaPalabraPublica,
} from '@sis-leg/api-client'
import { detectarTransicionesSonoras } from '@sis-leg/frontend-shared'
import {
  crearApoyoTecnicoPrueba,
  crearConcejalesPublicos,
  crearEstadoRecintoPrueba,
  crearVotacionPublicaPrueba,
} from './datos_prueba'

/** Estado de sesión abierta con doce bancas, base de la mayoría de los casos. */
function sesionAbierta(parcial: Partial<EstadoRecinto> = {}): EstadoRecinto {
  return crearEstadoRecintoPrueba({
    estado_global: 'SESION_ABIERTA',
    concejales: crearConcejalesPublicos(12),
    ...parcial,
  })
}

function persona(banca: number): PersonaPalabraPublica {
  return { nombre: `Nombre${banca}`, apellido: `Apellido${banca}`, banca }
}

function avisoRecinto(avisoId: string): AvisoTecnicoProyectado {
  return {
    aviso_id: avisoId,
    texto: 'Cuarto intermedio',
    destino: 'RECINTO',
    publicado_en: '2026-09-04T10:00:00Z',
    expira_en: null,
    segundos_restantes: null,
  }
}

function conTransmision(estado: EstadoTransmision): EstadoRecinto {
  return sesionAbierta({
    tecnico: crearApoyoTecnicoPrueba({
      transmision: {
        estado,
        iniciada_en: '2026-09-04T10:00:00Z',
        en_vivo_desde: '2026-09-04T10:00:10Z',
        cuenta_regresiva_segundos: estado === 'CUENTA_REGRESIVA' ? 10 : null,
        segundos_restantes: estado === 'CUENTA_REGRESIVA' ? 4 : null,
      },
    }),
  })
}

describe('Transiciones globales', () => {
  it('suena la preparación al pasar de SIN_PREPARAR a PREPARANDO', () => {
    const previo = crearEstadoRecintoPrueba({ estado_global: 'SIN_PREPARAR' })
    const actual = crearEstadoRecintoPrueba({
      estado_global: 'PREPARANDO',
      concejales: crearConcejalesPublicos(12),
    })

    expect(detectarTransicionesSonoras(previo, actual)).toEqual(['preparacion_iniciada'])
  })

  it('suena la apertura de sesión y no la preparación', () => {
    const previo = crearEstadoRecintoPrueba({
      estado_global: 'PREPARANDO',
      concejales: crearConcejalesPublicos(12),
    })

    expect(detectarTransicionesSonoras(previo, sesionAbierta())).toEqual(['sesion_abierta'])
  })

  it('suena el cierre de sesión al volver a SIN_PREPARAR', () => {
    const previo = sesionAbierta()
    const actual = crearEstadoRecintoPrueba({ estado_global: 'SIN_PREPARAR' })

    expect(detectarTransicionesSonoras(previo, actual)).toEqual(['sesion_cerrada'])
  })

  it('no convierte el vaciado del recinto en retiros de pedidos ni en ausencias', () => {
    // Al cerrar la sesión el backend deja de proyectar padrón y cola. Esa limpieza es una
    // consecuencia del cierre, no una docena de hechos individuales.
    const previo = sesionAbierta({
      palabra: { orador: persona(1), cola: [persona(2), persona(3)] },
    })
    const actual = crearEstadoRecintoPrueba({ estado_global: 'SIN_PREPARAR' })

    expect(detectarTransicionesSonoras(previo, actual)).toEqual(['sesion_cerrada'])
  })
})

describe('Avisos de Apoyo Técnico', () => {
  it('suena la publicación de un aviso nuevo', () => {
    const previo = sesionAbierta()
    const actual = sesionAbierta({
      tecnico: crearApoyoTecnicoPrueba({ aviso: avisoRecinto('aviso-1') }),
    })

    expect(detectarTransicionesSonoras(previo, actual)).toEqual(['aviso_tecnico_publicado'])
  })

  it('trata el reemplazo de un aviso como una publicación nueva, no como retiro', () => {
    const previo = sesionAbierta({
      tecnico: crearApoyoTecnicoPrueba({ aviso: avisoRecinto('aviso-1') }),
    })
    const actual = sesionAbierta({
      tecnico: crearApoyoTecnicoPrueba({ aviso: avisoRecinto('aviso-2') }),
    })

    expect(detectarTransicionesSonoras(previo, actual)).toEqual(['aviso_tecnico_publicado'])
  })

  it('no repite la publicación mientras el mismo aviso sigue vigente', () => {
    const previo = sesionAbierta({
      tecnico: crearApoyoTecnicoPrueba({ aviso: avisoRecinto('aviso-1') }),
    })
    const actual = sesionAbierta({
      revision: 2,
      tecnico: crearApoyoTecnicoPrueba({ aviso: avisoRecinto('aviso-1') }),
    })

    expect(detectarTransicionesSonoras(previo, actual)).toEqual([])
  })

  it('suena el retiro cuando el aviso desaparece del snapshot', () => {
    const previo = sesionAbierta({
      tecnico: crearApoyoTecnicoPrueba({ aviso: avisoRecinto('aviso-1') }),
    })

    expect(detectarTransicionesSonoras(previo, sesionAbierta())).toEqual(['aviso_tecnico_retirado'])
  })
})

describe('Transmisión en vivo', () => {
  it('suena el inicio al entrar en EN_VIVO desde la cuenta regresiva', () => {
    const previo = conTransmision('CUENTA_REGRESIVA')
    const actual = conTransmision('EN_VIVO')

    expect(detectarTransicionesSonoras(previo, actual)).toEqual(['transmision_iniciada'])
  })

  it('suena la detención al volver de EN_VIVO a APAGADO', () => {
    const previo = conTransmision('EN_VIVO')
    const actual = conTransmision('APAGADO')

    expect(detectarTransicionesSonoras(previo, actual)).toEqual(['transmision_detenida'])
  })

  it('no suena nada al iniciarse una cuenta regresiva', () => {
    // Empezar a contar no es todavía transmitir; el sonido de inicio pertenece al vivo.
    const previo = conTransmision('APAGADO')
    const actual = conTransmision('CUENTA_REGRESIVA')

    expect(detectarTransicionesSonoras(previo, actual)).toEqual([])
  })
})

describe('Uso de la palabra', () => {
  it('suena el pedido cuando una banca entra en la cola', () => {
    const previo = sesionAbierta({ palabra: { orador: null, cola: [persona(4)] } })
    const actual = sesionAbierta({ palabra: { orador: null, cola: [persona(4), persona(7)] } })

    expect(detectarTransicionesSonoras(previo, actual)).toEqual(['pedido_palabra_registrado'])
  })

  it('suena el retiro cuando una banca sale de la cola sin ser orador', () => {
    const previo = sesionAbierta({ palabra: { orador: null, cola: [persona(4), persona(7)] } })
    const actual = sesionAbierta({ palabra: { orador: null, cola: [persona(4)] } })

    expect(detectarTransicionesSonoras(previo, actual)).toEqual(['pedido_palabra_retirado'])
  })

  it('suena solamente el otorgamiento cuando la banca pasa de la cola a orador', () => {
    // El mismo movimiento no puede contarse dos veces: sale de la cola porque le dieron
    // la palabra, no porque haya retirado su pedido.
    const previo = sesionAbierta({ palabra: { orador: null, cola: [persona(4), persona(7)] } })
    const actual = sesionAbierta({ palabra: { orador: persona(4), cola: [persona(7)] } })

    expect(detectarTransicionesSonoras(previo, actual)).toEqual(['uso_palabra_otorgado'])
  })

  it('no suena nada cuando el orador termina y no hay reemplazo', () => {
    const previo = sesionAbierta({ palabra: { orador: persona(4), cola: [] } })
    const actual = sesionAbierta({ palabra: { orador: null, cola: [] } })

    expect(detectarTransicionesSonoras(previo, actual)).toEqual([])
  })
})

describe('Votación', () => {
  it('suena la apertura cuando adopta una votación EN_CURSO', () => {
    const previo = sesionAbierta()
    const actual = sesionAbierta({ votacion: crearVotacionPublicaPrueba({ id: 'votacion-1' }) })

    expect(detectarTransicionesSonoras(previo, actual)).toEqual(['votacion_abierta'])
  })

  it('no repite la apertura mientras la misma votación sigue EN_CURSO', () => {
    const previo = sesionAbierta({ votacion: crearVotacionPublicaPrueba({ id: 'votacion-1' }) })
    const actual = sesionAbierta({
      revision: 2,
      votacion: crearVotacionPublicaPrueba({ id: 'votacion-1', bancas_voto_emitido: [1, 2] }),
    })

    expect(detectarTransicionesSonoras(previo, actual)).toEqual([])
  })

  it('suena el cierre al pasar la recepción de EN_CURSO a CERRADA', () => {
    const previo = sesionAbierta({ votacion: crearVotacionPublicaPrueba({ id: 'votacion-1' }) })
    const actual = sesionAbierta({
      votacion: crearVotacionPublicaPrueba({
        id: 'votacion-1',
        estado_recepcion: 'CERRADA',
        resultado: 'APROBADA',
      }),
    })

    expect(detectarTransicionesSonoras(previo, actual)).toEqual(['votacion_cerrada'])
  })

  it('no vuelve a sonar el cierre aunque después cambie el resultado', () => {
    // Caso real: cierre EMPATADA y, más tarde, desempate de Presidencia. Es una revisión
    // nueva de una votación ya cerrada, no un cierre nuevo.
    const previo = sesionAbierta({
      votacion: crearVotacionPublicaPrueba({
        id: 'votacion-1',
        estado_recepcion: 'CERRADA',
        resultado: 'EMPATADA',
      }),
    })
    const actual = sesionAbierta({
      votacion: crearVotacionPublicaPrueba({
        id: 'votacion-1',
        estado_recepcion: 'CERRADA',
        resultado: 'APROBADA',
        voto_presidencial: { presidencia: 'Presidencia', sentido: 'POSITIVO' },
      }),
    })

    expect(detectarTransicionesSonoras(previo, actual)).toEqual([])
  })

  it('suena la apertura de una votación distinta aunque la anterior siga visible', () => {
    const previo = sesionAbierta({
      votacion: crearVotacionPublicaPrueba({
        id: 'votacion-1',
        estado_recepcion: 'CERRADA',
        resultado: 'APROBADA',
      }),
    })
    const actual = sesionAbierta({
      votacion: crearVotacionPublicaPrueba({ id: 'votacion-2', numero_votacion: 2 }),
    })

    expect(detectarTransicionesSonoras(previo, actual)).toEqual(['votacion_abierta'])
  })
})

describe('Presencia', () => {
  it('suena la ausencia cuando una banca deja de estar presente', () => {
    const presentes = crearConcejalesPublicos(12)
    const ausente = presentes.map((concejal) =>
      concejal.banca === 5 ? { ...concejal, presente: false } : concejal,
    )

    expect(
      detectarTransicionesSonoras(
        sesionAbierta({ concejales: presentes }),
        sesionAbierta({ concejales: ausente }),
      ),
    ).toEqual(['concejal_ausente'])
  })

  it('suena la presencia cuando una banca vuelve a estar presente', () => {
    const base = crearConcejalesPublicos(12)
    const presente = base.map((concejal) =>
      concejal.banca === 2 ? { ...concejal, presente: true } : concejal,
    )

    expect(
      detectarTransicionesSonoras(
        sesionAbierta({ concejales: base }),
        sesionAbierta({ concejales: presente }),
      ),
    ).toEqual(['concejal_presente'])
  })

  it('emite un evento por cada banca que cambió en la misma revisión', () => {
    const base = crearConcejalesPublicos(12)
    const cambiados = base.map((concejal) => {
      if (concejal.banca === 5) return { ...concejal, presente: false }
      if (concejal.banca === 2) return { ...concejal, presente: true }
      return concejal
    })

    expect(
      detectarTransicionesSonoras(
        sesionAbierta({ concejales: base }),
        sesionAbierta({ concejales: cambiados }),
      ),
    ).toEqual(['concejal_presente', 'concejal_ausente'])
  })

  it('ignora el padrón que aparece al preparar el recinto', () => {
    const previo = crearEstadoRecintoPrueba({ estado_global: 'PREPARANDO', concejales: [] })
    const actual = crearEstadoRecintoPrueba({
      estado_global: 'PREPARANDO',
      concejales: crearConcejalesPublicos(12),
    })

    expect(detectarTransicionesSonoras(previo, actual)).toEqual([])
  })
})

describe('Idempotencia y simultaneidad', () => {
  it('no produce sonidos al comparar un snapshot contra sí mismo', () => {
    const estado = sesionAbierta({
      votacion: crearVotacionPublicaPrueba({ id: 'votacion-1' }),
      palabra: { orador: persona(3), cola: [persona(5)] },
      tecnico: crearApoyoTecnicoPrueba({ aviso: avisoRecinto('aviso-1') }),
    })

    expect(detectarTransicionesSonoras(estado, estado)).toEqual([])
  })

  it('devuelve los dos eventos cuando una misma revisión trae dos hechos', () => {
    const base = crearConcejalesPublicos(12)
    const previo = sesionAbierta({ concejales: base })
    const actual = sesionAbierta({
      concejales: base.map((concejal) =>
        concejal.banca === 5 ? { ...concejal, presente: false } : concejal,
      ),
      tecnico: crearApoyoTecnicoPrueba({ aviso: avisoRecinto('aviso-1') }),
    })

    expect(detectarTransicionesSonoras(previo, actual)).toEqual([
      'aviso_tecnico_publicado',
      'concejal_ausente',
    ])
  })
})
