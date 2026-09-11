/**
 * Redacción compartida de `Votación`, `Tema` y `Estado` (WP-099).
 *
 * ## Qué demuestra
 *
 * WP-099 mueve a `frontend-shared` el vocabulario que antes vivía dentro del componente de
 * la Pantalla del Recinto, para que el Zócalo para OBS muestre el mismo significado con
 * otra geometría. Estas pruebas fijan ese vocabulario como contrato: si alguien cambia un
 * texto o una condición, las dos superficies cambian a la vez y acá se ve.
 *
 * Son pruebas puras: no montan componentes ni levantan una aplicación. Lo que se ejercita
 * es la función, que es exactamente lo que las dos pantallas comparten.
 */

import { ref } from 'vue'
import { describe, expect, it } from 'vitest'

import {
  claseEstadoVotacion,
  conteosVisiblesVotacion,
  describirEstadoVotacion,
  describirMayoriaVotacion,
  describirTemaVotacion,
  etiquetaSentidoVoto,
  resumirVotacion,
  usePresentacionVotacionPublica,
  votacionEnCurso,
} from '../src/presentacion_votacion_publica'
import { crearVotacionPublicaPrueba } from './helpers/estado_recinto'

describe('WP-099 · renglón Votación', () => {
  it('describe una mayoría simple sin nombrar factor ni base', () => {
    const votacion = crearVotacionPublicaPrueba({
      numero_votacion: 7,
      tipo: 'Despacho de comisión',
      tipo_mayoria: 'SIMPLE',
    })

    expect(resumirVotacion(votacion)).toBe('N.º 7 · Despacho de comisión · Mayoría simple')
    // Una mayoría simple no tiene factor ni base: nombrarlos sería inventar información
    // que el reglamento no usa para ese tipo de votación.
    expect(resumirVotacion(votacion)).not.toContain('factor')
    expect(resumirVotacion(votacion)).not.toContain('base')
  })

  it('describe una mayoría especial con el factor truncado a dos decimales', () => {
    const votacion = crearVotacionPublicaPrueba({
      tipo_mayoria: 'ESPECIAL',
      factor: 0.6789,
      base: 'PRESENTES',
    })

    // El truncado lo aporta la regla única de WP-063; acá se comprueba que la descripción
    // compartida la use y no imprima el número crudo.
    expect(describirMayoriaVotacion(votacion)).toBe(
      'Mayoría especial · factor 0.67 · base presentes',
    )
  })

  it('muestra el código crudo si apareciera una base que todavía no tiene traducción', () => {
    const votacion = crearVotacionPublicaPrueba({
      tipo_mayoria: 'ESPECIAL',
      // El contrato podría incorporar otra base en el futuro; mostrar el valor es más
      // informativo que dejar el renglón vacío.
      base: 'BASE_FUTURA' as never,
    })

    expect(describirMayoriaVotacion(votacion)).toContain('base BASE_FUTURA')
  })

  it('anuncia la ausencia de votación en lugar de dejar el renglón vacío', () => {
    expect(resumirVotacion(null)).toBe('Sin votación activa')
    expect(describirMayoriaVotacion(null)).toBe('')
  })
})

describe('WP-099 · renglón Tema', () => {
  it('muestra el tema tal como lo publicó el backend', () => {
    const votacion = crearVotacionPublicaPrueba({ tema: 'Expediente 1234/2026' })
    expect(describirTemaVotacion(votacion)).toBe('Expediente 1234/2026')
  })

  it('usa un guion largo cuando no hay votación', () => {
    expect(describirTemaVotacion(null)).toBe('—')
  })
})

describe('WP-099 · renglón Estado', () => {
  it('dice «En curso» mientras la recepción sigue abierta', () => {
    const votacion = crearVotacionPublicaPrueba({ estado_recepcion: 'EN_CURSO' })
    expect(votacionEnCurso(votacion)).toBe(true)
    expect(describirEstadoVotacion(votacion)).toBe('En curso')
  })

  it('traduce los cuatro resultados institucionales', () => {
    const traducciones = (['APROBADA', 'RECHAZADA', 'EMPATADA', 'INCONCLUSA'] as const).map(
      (resultado) =>
        describirEstadoVotacion(
          crearVotacionPublicaPrueba({ estado_recepcion: 'CERRADA', resultado }),
        ),
    )

    expect(traducciones).toEqual(['Aprobada', 'Rechazada', 'Empatada', 'Inconclusa'])
  })

  it('dice «Recepción cerrada» en el instante entre el cierre y el resultado', () => {
    const votacion = crearVotacionPublicaPrueba({ estado_recepcion: 'CERRADA', resultado: null })
    expect(describirEstadoVotacion(votacion)).toBe('Recepción cerrada')
  })

  it('dice «Sin votación» cuando no hay ninguna', () => {
    expect(describirEstadoVotacion(null)).toBe('Sin votación')
    expect(claseEstadoVotacion(null)).toBe('sin_votacion')
  })

  it('deriva la clase visual del resultado y, si no hay, del estado de recepción', () => {
    expect(
      claseEstadoVotacion(
        crearVotacionPublicaPrueba({ estado_recepcion: 'CERRADA', resultado: 'APROBADA' }),
      ),
    ).toBe('aprobada')
    expect(claseEstadoVotacion(crearVotacionPublicaPrueba({ estado_recepcion: 'EN_CURSO' }))).toBe(
      'en_curso',
    )
  })
})

describe('WP-099 · secreto del voto y conteos', () => {
  const conteos = { positivos: 8, negativos: 3, abstenciones: 1, total: 12 }

  it('oculta los conteos mientras la recepción está en curso', () => {
    const votacion = crearVotacionPublicaPrueba({ estado_recepcion: 'EN_CURSO', conteos })
    // Es la regla del secreto del voto: aunque el DTO trajera números, no se muestran.
    expect(conteosVisiblesVotacion(votacion)).toBeNull()
  })

  it('publica los conteos en cuanto la recepción quedó cerrada', () => {
    const votacion = crearVotacionPublicaPrueba({
      estado_recepcion: 'CERRADA',
      resultado: 'APROBADA',
      conteos,
    })
    expect(conteosVisiblesVotacion(votacion)).toEqual(conteos)
  })
})

describe('WP-099 · desempate de Presidencia', () => {
  it('traduce el sentido del voto de desempate', () => {
    expect(etiquetaSentidoVoto('POSITIVO')).toBe('Positivo')
    expect(etiquetaSentidoVoto('NEGATIVO')).toBe('Negativo')
    // Un sentido desconocido se muestra tal cual antes que desaparecer del renglón.
    expect(etiquetaSentidoVoto('OTRO')).toBe('OTRO')
  })

  it('señala la espera del desempate sólo mientras la votación está empatada', () => {
    const empatada = ref(
      crearVotacionPublicaPrueba({ estado_recepcion: 'CERRADA', resultado: 'EMPATADA' }),
    )
    const presentacion = usePresentacionVotacionPublica(empatada)
    expect(presentacion.esperaDesempate.value).toBe(true)

    empatada.value = crearVotacionPublicaPrueba({
      estado_recepcion: 'CERRADA',
      resultado: 'APROBADA',
    })
    expect(presentacion.esperaDesempate.value).toBe(false)
  })
})

describe('WP-099 · reactividad del composable', () => {
  it('recalcula los tres renglones cuando llega otra votación, sin recordar la anterior', () => {
    const votacion = ref(crearVotacionPublicaPrueba({ numero_votacion: 1, tema: 'Primero' }))
    const { resumen, tema, estado } = usePresentacionVotacionPublica(votacion)

    expect(resumen.value).toContain('N.º 1')
    expect(tema.value).toBe('Primero')
    expect(estado.value).toBe('En curso')

    votacion.value = crearVotacionPublicaPrueba({
      numero_votacion: 2,
      tema: 'Segundo',
      estado_recepcion: 'CERRADA',
      resultado: 'RECHAZADA',
    })

    expect(resumen.value).toContain('N.º 2')
    expect(tema.value).toBe('Segundo')
    expect(estado.value).toBe('Rechazada')

    // Al desaparecer la votación no queda ningún rastro de la anterior: el composable no
    // guarda estado propio, que es exactamente lo que el WP prohíbe a la nueva superficie.
    votacion.value = null
    expect(resumen.value).toBe('Sin votación activa')
    expect(tema.value).toBe('—')
    expect(estado.value).toBe('Sin votación')
  })
})
