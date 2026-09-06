/**
 * Frontera entre sincronización y audio en la Pantalla del Recinto (WP-066).
 *
 * Acá se verifica la regla que evita el peor defecto posible de este WP: que al abrir la
 * pantalla, recargarla o reconectarla suene de golpe todo lo que ya había pasado. También
 * se cubre el tic de la cuenta regresiva, que es el único de los quince eventos que no
 * nace de comparar dos snapshots.
 *
 * El motor real se sustituye por uno que sólo anota qué le pidieron reproducir: el objetivo
 * de estas pruebas es la decisión, no el audio.
 */

import { describe, expect, it } from 'vitest'
import { effectScope, ref, type Ref } from 'vue'
import type { EstadoRecinto } from '@sis-leg/api-client'
import type { EstadoConexionRecinto } from '../app/composables/useEstadoRecinto'
import {
  EVENTOS_SONOROS_RECINTO,
  useSonidosRecinto,
  type MotorSonidosRecinto,
} from '@sis-leg/frontend-shared'
import {
  crearApoyoTecnicoPrueba,
  crearConcejalesPublicos,
  crearEstadoRecintoPrueba,
  crearSonidosRecintoPrueba,
  crearVotacionPublicaPrueba,
} from './datos_prueba'
import {
  crearEscenariosSonoros,
  eventosCubiertos,
} from '../../../packages/frontend-shared/tests/helpers/escenarios_sonoros'

/** Motor de prueba: registra los eventos pedidos y las configuraciones adoptadas. */
function crearMotorEspia() {
  const reproducidos: string[] = []
  let configuraciones = 0
  let liberado = false
  const motor: MotorSonidosRecinto = {
    configurar: () => {
      configuraciones += 1
    },
    reproducir: (evento) => {
      reproducidos.push(evento)
    },
    liberar: () => {
      liberado = true
    },
  }
  return {
    motor,
    reproducidos,
    get configuraciones() {
      return configuraciones
    },
    get liberado() {
      return liberado
    },
  }
}

interface Banco {
  estado: Ref<EstadoRecinto | null>
  estadoConexion: Ref<EstadoConexionRecinto>
  segundos: Ref<number | null>
  espia: ReturnType<typeof crearMotorEspia>
  detener: () => void
}

/** Monta el composable dentro de un scope reactivo propio, sin componente ni Nuxt. */
function montar(inicial: EstadoRecinto | null = null): Banco {
  const estado = ref<EstadoRecinto | null>(inicial)
  const estadoConexion = ref<EstadoConexionRecinto>('INICIAL')
  const segundos = ref<number | null>(null)
  const espia = crearMotorEspia()
  const scope = effectScope()

  scope.run(() => {
    useSonidosRecinto({
      estado,
      estadoConexion,
      segundosCuentaRegresiva: segundos,
      motor: espia.motor,
    })
  })

  return { estado, estadoConexion, segundos, espia, detener: () => scope.stop() }
}

function sesionAbierta(parcial: Partial<EstadoRecinto> = {}): EstadoRecinto {
  return crearEstadoRecintoPrueba({
    estado_global: 'SESION_ABIERTA',
    concejales: crearConcejalesPublicos(12),
    ...parcial,
  })
}

/** Simula la secuencia real del cliente: snapshot adoptado y después stream abierto. */
function adoptarBaseline(banco: Banco, estado: EstadoRecinto): void {
  banco.estadoConexion.value = banco.estado.value === null ? 'INICIAL' : 'RECONECTANDO'
  banco.estado.value = estado
  banco.estadoConexion.value = 'CONECTADO'
}

describe('Baseline y reconexión', () => {
  it('no reproduce nada al adoptar el primer snapshot', () => {
    const banco = montar()

    // Una sesión en marcha, con votación, aviso y presencias: si sonorizara la baseline,
    // acá sonarían cuatro eventos históricos de una sola vez.
    adoptarBaseline(
      banco,
      sesionAbierta({
        votacion: crearVotacionPublicaPrueba({ id: 'votacion-1' }),
        tecnico: crearApoyoTecnicoPrueba({
          aviso: {
            aviso_id: 'aviso-1',
            texto: 'Cuarto intermedio',
            destino: 'RECINTO',
            publicado_en: '2026-09-04T10:00:00Z',
            expira_en: null,
            segundos_restantes: null,
          },
        }),
      }),
    )

    expect(banco.espia.reproducidos).toEqual([])
    // Aun sin reproducir, adopta la configuración de audio para poder precargarla.
    expect(banco.espia.configuraciones).toBe(1)
    banco.detener()
  })

  it('reproduce las transiciones que llegan por el stream ya conectado', () => {
    const banco = montar()
    adoptarBaseline(banco, sesionAbierta())

    banco.estado.value = sesionAbierta({
      revision: 2,
      votacion: crearVotacionPublicaPrueba({ id: 'votacion-1' }),
    })

    expect(banco.espia.reproducidos).toEqual(['votacion_abierta'])
    banco.detener()
  })

  it('no reproduce el historial acumulado durante una reconexión', () => {
    const banco = montar()
    adoptarBaseline(banco, sesionAbierta())

    // Se cae el stream y, cuando vuelve, el snapshot de recuperación trae todo lo que
    // ocurrió mientras la pantalla estaba desconectada.
    banco.estadoConexion.value = 'RECONECTANDO'
    banco.estado.value = sesionAbierta({
      revision: 9,
      votacion: crearVotacionPublicaPrueba({ id: 'votacion-1' }),
      palabra: {
        orador: { nombre: 'Nombre3', apellido: 'Apellido3', banca: 3 },
        cola: [{ nombre: 'Nombre5', apellido: 'Apellido5', banca: 5 }],
      },
    })
    banco.estadoConexion.value = 'CONECTADO'

    expect(banco.espia.reproducidos).toEqual([])

    // A partir de esa nueva referencia, los hechos siguientes sí suenan.
    banco.estado.value = sesionAbierta({
      revision: 10,
      votacion: crearVotacionPublicaPrueba({ id: 'votacion-1', estado_recepcion: 'CERRADA' }),
      palabra: {
        orador: { nombre: 'Nombre3', apellido: 'Apellido3', banca: 3 },
        cola: [{ nombre: 'Nombre5', apellido: 'Apellido5', banca: 5 }],
      },
    })

    expect(banco.espia.reproducidos).toEqual(['votacion_cerrada'])
    banco.detener()
  })

  it('no reproduce nada cuando el backend reinicia y la revisión vuelve a empezar', () => {
    const banco = montar()
    adoptarBaseline(banco, sesionAbierta({ revision: 42 }))

    banco.estadoConexion.value = 'DESCONECTADO'
    banco.estado.value = crearEstadoRecintoPrueba({ revision: 0, estado_global: 'SIN_PREPARAR' })
    banco.estadoConexion.value = 'CONECTADO'

    expect(banco.espia.reproducidos).toEqual([])
    banco.detener()
  })

  it('vuelve a tratar como baseline el estado que llega después de perder el estado', () => {
    const banco = montar()
    adoptarBaseline(banco, sesionAbierta())

    banco.estado.value = null
    adoptarBaseline(banco, sesionAbierta({ revision: 3 }))

    expect(banco.espia.reproducidos).toEqual([])
    banco.detener()
  })
})

describe('Idempotencia', () => {
  it('no repite el sonido cuando una revisión nueva trae el mismo contenido', () => {
    // El backend republica por motivos que no cambian lo que se oye: vencimiento de una
    // ventana, recálculo de un contador. La votación sigue siendo la misma y ya sonó.
    const banco = montar()
    adoptarBaseline(banco, sesionAbierta())

    banco.estado.value = sesionAbierta({
      revision: 2,
      votacion: crearVotacionPublicaPrueba({ id: 'votacion-1' }),
    })
    banco.estado.value = sesionAbierta({
      revision: 3,
      votacion: crearVotacionPublicaPrueba({ id: 'votacion-1' }),
    })

    expect(banco.espia.reproducidos).toEqual(['votacion_abierta'])
    banco.detener()
  })

  it('descarta una revisión repetida recibida dentro de la misma conexión', () => {
    const banco = montar()
    adoptarBaseline(banco, sesionAbierta())

    const conVotacion = sesionAbierta({
      revision: 2,
      votacion: crearVotacionPublicaPrueba({ id: 'votacion-1' }),
    })
    banco.estado.value = conVotacion
    // El cliente tolera un reenvío con la misma revisión; el audio no puede repetirse.
    banco.estado.value = { ...conVotacion }

    expect(banco.espia.reproducidos).toEqual(['votacion_abierta'])
    banco.detener()
  })
})

describe('Eventos simultáneos', () => {
  it('pide los dos sonidos de una revisión que trae dos hechos', () => {
    const banco = montar()
    const base = crearConcejalesPublicos(12)
    adoptarBaseline(banco, sesionAbierta({ concejales: base }))

    banco.estado.value = sesionAbierta({
      revision: 2,
      concejales: base.map((concejal) =>
        concejal.banca === 5 ? { ...concejal, presente: false } : concejal,
      ),
      votacion: crearVotacionPublicaPrueba({ id: 'votacion-1' }),
    })

    expect(banco.espia.reproducidos).toEqual(['votacion_abierta', 'concejal_ausente'])
    banco.detener()
  })

  it('no pierde una revisión intermedia adoptada en el mismo tick', () => {
    // El observador es síncrono justamente para esto: con el agrupado normal de Vue, la
    // revisión 2 desaparecería y el pedido de palabra nunca habría sonado.
    const banco = montar()
    adoptarBaseline(banco, sesionAbierta())

    banco.estado.value = sesionAbierta({
      revision: 2,
      palabra: { orador: null, cola: [{ nombre: 'Nombre5', apellido: 'Apellido5', banca: 5 }] },
    })
    banco.estado.value = sesionAbierta({
      revision: 3,
      palabra: {
        orador: { nombre: 'Nombre5', apellido: 'Apellido5', banca: 5 },
        cola: [],
      },
    })

    expect(banco.espia.reproducidos).toEqual(['pedido_palabra_registrado', 'uso_palabra_otorgado'])
    banco.detener()
  })
})

describe('Tic de la cuenta regresiva', () => {
  it('suena una vez por cada segundo visible que cambia', () => {
    const banco = montar()
    adoptarBaseline(banco, sesionAbierta())

    banco.segundos.value = 4
    banco.segundos.value = 3
    banco.segundos.value = 2
    banco.segundos.value = 1

    // El primer valor observado es la adopción del snapshot y no suena; los tres cambios
    // posteriores sí.
    expect(banco.espia.reproducidos).toEqual([
      'transmision_cuenta_regresiva_tic',
      'transmision_cuenta_regresiva_tic',
      'transmision_cuenta_regresiva_tic',
    ])
    banco.detener()
  })

  it('no suena al terminar la cuenta ni al repetirse el mismo segundo', () => {
    const banco = montar()
    adoptarBaseline(banco, sesionAbierta())

    banco.segundos.value = 2
    banco.segundos.value = 2
    banco.segundos.value = null

    expect(banco.espia.reproducidos).toEqual([])
    banco.detener()
  })

  it('no depende de recibir un snapshot por segundo', () => {
    const banco = montar()
    adoptarBaseline(banco, sesionAbierta({ sonidos: crearSonidosRecintoPrueba() }))
    const revisionesAdoptadas = banco.espia.configuraciones

    banco.segundos.value = 3
    banco.segundos.value = 2

    // El tic sonó sin que llegara ninguna revisión nueva del backend.
    expect(banco.espia.configuraciones).toBe(revisionesAdoptadas)
    expect(banco.espia.reproducidos).toEqual(['transmision_cuenta_regresiva_tic'])
    banco.detener()
  })
})

describe('Ciclo de vida', () => {
  it('libera el motor cuando muere el scope de la pantalla', () => {
    const banco = montar()
    adoptarBaseline(banco, sesionAbierta())

    banco.detener()

    expect(banco.espia.liberado).toBe(true)
  })
})

// =============================================================================
// Paridad con el puesto de Apoyo Técnico (WP-071)
// =============================================================================

/**
 * La misma tabla canónica que ejercita la suite de Apoyo Técnico.
 *
 * Acá corre sobre el cableado de la Pantalla del Recinto. Que las dos superficies
 * atraviesen los mismos quince escenarios y produzcan los mismos quince eventos es lo que
 * convierte «paridad 1:1» en algo comprobable y no en una intención escrita en un
 * comentario: si alguna de las dos dejara de reproducir un evento, fallaría su propia
 * suite contra esta misma lista.
 */
describe('Paridad de los quince eventos con Apoyo Técnico (WP-071)', () => {
  const escenarios = crearEscenariosSonoros()

  it('la tabla canónica cubre exactamente los quince eventos del contrato', () => {
    expect([...eventosCubiertos(escenarios)].sort()).toEqual([...EVENTOS_SONOROS_RECINTO].sort())
  })

  for (const escenario of escenarios) {
    it(`reproduce ${escenario.evento} cuando ${escenario.descripcion}`, () => {
      const banco = montar()
      adoptarBaseline(banco, escenario.previo)
      banco.espia.reproducidos.length = 0

      banco.estado.value = escenario.actual
      if (escenario.segundos !== undefined) {
        banco.segundos.value = escenario.segundos.previo
        banco.segundos.value = escenario.segundos.actual
      }

      expect(banco.espia.reproducidos).toContain(escenario.evento)
      banco.detener()
    })
  }
})
