/**
 * Regresión DOM de secreto, revelado y deadlines del Recinto.
 *
 * Los relojes falsos permiten recorrer fronteras temporales sin esperas reales
 * y verifican contenido, no solamente clases CSS.
 */

import { mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import PantallaRecinto from '../app/components/PantallaRecinto.vue'
import {
  crearConcejalesPublicos,
  crearEstadoRecintoPrueba,
  crearVotacionPublicaPrueba,
} from './datos_prueba'

const HORA_BASE = '2026-08-28T10:00:00Z'

function crearSesionConVotacion(
  votacion: ReturnType<typeof crearVotacionPublicaPrueba> | null,
  parcial: Parameters<typeof crearEstadoRecintoPrueba>[0] = {},
) {
  return crearEstadoRecintoPrueba({
    instancia: 'instancia-prueba',
    revision: 1,
    generado_en: HORA_BASE,
    estado_global: 'SESION_ABIERTA',
    sesion: {
      fecha_hora_inicio_preparacion: '2026-08-28T09:30:00Z',
      fecha_hora_apertura: '2026-08-28T09:45:00Z',
      numero_sesion: 59,
      presidencia: 'Ana Presidencia',
      secretaria_legislativa: 'Luis Secretaría',
    },
    filas_bancas: [2, 2],
    concejales: crearConcejalesPublicos(4),
    quorum: { cantidad_presentes: 3, requerido: 3, alcanzado: true },
    palabra: { orador: null, cola: [] },
    votacion,
    ...parcial,
  })
}

function montar(estado: ReturnType<typeof crearEstadoRecintoPrueba>): VueWrapper {
  return mount(PantallaRecinto, {
    props: { estado, estadoConexion: 'CONECTADO', desactualizado: false },
  })
}

/**
 * Cuenta cuántas bancas muestran un resultado individual final.
 *
 * El DOM simulado de estas pruebas no implementa selectores de prefijo, así que
 * se filtra a mano por el atributo `data-estado-banca` que expone la tarjeta.
 */
function contarBancasConResultado(wrapper: VueWrapper): number {
  return wrapper
    .findAll('[data-banca]')
    .filter((banca) =>
      (banca.element.getAttribute('data-estado-banca') ?? '').startsWith('RESULTADO_'),
    ).length
}

afterEach(() => {
  vi.useRealTimers()
})

describe('Experiencia pública de votación', () => {
  it('distingue sesión sin votación y EN_CURSO sin revelar payloads impropios', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(HORA_BASE)
    const wrapper = montar(crearSesionConVotacion(null))
    expect(wrapper.get('[data-testid="estado-votacion"]').text()).toBe('Sin votación')

    await wrapper.setProps({
      estado: crearSesionConVotacion(
        crearVotacionPublicaPrueba({
          tema: 'Expediente secreto durante la recepción',
          // El backend normal no envía estos campos. La prueba demuestra que
          // la capa visual tampoco los utiliza si recibe un payload inválido.
          votos_individuales: [
            { nombre: 'Nombre1', apellido: 'Apellido1', banca: 1, valor: 'POSITIVO' },
          ],
          conteos: { positivos: 99, negativos: 0, abstenciones: 0, total: 99 },
        }),
      ),
    })

    expect(wrapper.get('[data-testid="estado-votacion"]').text()).toBe('En curso')
    expect(wrapper.get('[data-testid="tema-votacion"]').text()).toContain('Expediente secreto')
    expect(wrapper.find('[data-testid="countdown-votacion"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="conteos-votacion"]').exists()).toBe(false)
    expect(wrapper.find('[data-estado-banca^="RESULTADO_"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Positivo')
    expect(wrapper.text()).not.toContain('99')
    wrapper.unmount()
  })

  it('deriva el countdown del deadline, avanza y no se reinicia por otra revisión', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(HORA_BASE)
    const deadline = '2026-08-28T10:00:04Z'
    const wrapper = montar(
      crearSesionConVotacion(crearVotacionPublicaPrueba({ cuenta_regresiva_hasta: deadline })),
    )

    expect(wrapper.get('[data-testid="countdown-votacion"]').text()).toContain('4')
    vi.advanceTimersByTime(1250)
    await wrapper.vm.$nextTick()
    expect(wrapper.get('[data-testid="countdown-votacion"]').text()).toContain('3')

    await wrapper.setProps({
      estado: crearSesionConVotacion(
        crearVotacionPublicaPrueba({ cuenta_regresiva_hasta: deadline }),
        { revision: 2, generado_en: '2026-08-28T10:00:01.250Z' },
      ),
    })
    expect(wrapper.get('[data-testid="countdown-votacion"]').text()).toContain('3')

    vi.advanceTimersByTime(3000)
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-testid="countdown-votacion"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="estado-votacion"]').text()).toBe('En curso')
    expect(wrapper.find('[data-estado-banca^="RESULTADO_"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('no revive un countdown vencido al recibir una baseline posterior', () => {
    vi.useFakeTimers()
    vi.setSystemTime('2026-08-28T10:00:10Z')
    const wrapper = montar(
      crearSesionConVotacion(
        crearVotacionPublicaPrueba({ cuenta_regresiva_hasta: '2026-08-28T10:00:04Z' }),
        { generado_en: '2026-08-28T10:00:10Z' },
      ),
    )
    expect(wrapper.find('[data-testid="countdown-votacion"]').exists()).toBe(false)
    // La única tarea restante es el reloj permanente de la cabecera pública.
    expect(vi.getTimerCount()).toBe(1)
    wrapper.unmount()
  })

  it('asocia votos por banca y conserva presencia, test, orador y conteos backend', () => {
    vi.useFakeTimers()
    vi.setSystemTime(HORA_BASE)
    const concejales = crearConcejalesPublicos(4)
    concejales[0]!.test_activo = true
    const wrapper = montar(
      crearSesionConVotacion(
        crearVotacionPublicaPrueba({
          estado_recepcion: 'CERRADA',
          resultado: 'APROBADA',
          fecha_hora_cierre: HORA_BASE,
          resultado_visible_hasta: '2026-08-28T10:00:10Z',
          votos_individuales: [
            { nombre: 'Nombre3', apellido: 'Apellido3', banca: 3, valor: 'ABSTENCION' },
            { nombre: 'Nombre1', apellido: 'Apellido1', banca: 1, valor: 'POSITIVO' },
            { nombre: 'Nombre2', apellido: 'Apellido2', banca: 2, valor: 'NEGATIVO' },
          ],
          // Los valores deliberadamente no coinciden con la lista corta: la
          // UI debe presentar el DTO de conteos, no recontar votos.
          conteos: { positivos: 8, negativos: 2, abstenciones: 1, total: 11 },
        }),
        {
          concejales,
          palabra: {
            orador: { nombre: 'Nombre1', apellido: 'Apellido1', banca: 1 },
            cola: [{ nombre: 'Nombre4', apellido: 'Apellido4', banca: 4 }],
          },
        },
      ),
    )

    expect(wrapper.get('[data-testid="estado-votacion"]').text()).toBe('Aprobada')
    // WP-045: el resultado final es el estado de mayor prioridad. En la banca 1
    // coexisten test y palabra, que quedan subordinados como halo sin agregar
    // una segunda etiqueta.
    expect(wrapper.get('[data-banca="1"]').element.getAttribute('data-estado-banca')).toBe(
      'RESULTADO_POSITIVO',
    )
    expect(wrapper.get('[data-banca="1"] [data-testid="etiqueta-banca"]').text()).toBe('Positivo')
    expect(wrapper.get('[data-banca="1"]').element.getAttribute('data-halo-test')).toBe('true')
    expect(wrapper.get('[data-banca="1"]').element.getAttribute('data-halo-palabra')).toBe('true')
    expect(wrapper.findAll('[data-banca="1"] [data-testid="etiqueta-banca"]')).toHaveLength(1)
    expect(wrapper.get('[data-banca="2"] [data-testid="etiqueta-banca"]').text()).toBe('Negativo')
    expect(wrapper.get('[data-banca="3"] [data-testid="etiqueta-banca"]').text()).toBe('Abstención')
    // La banca 4 no votó: sin resultado ni participación, vuelve al estado normal.
    expect(wrapper.get('[data-banca="4"]').element.getAttribute('data-estado-banca')).toBe('NORMAL')
    expect(wrapper.find('[data-banca="4"] [data-testid="etiqueta-banca"]').exists()).toBe(false)
    expect(wrapper.get('[data-banca="2"]').element.getAttribute('data-presente')).toBe('false')
    expect(wrapper.get('[data-testid="conteos-votacion"]').text()).toContain('Positivos 8')
    expect(wrapper.get('[data-testid="conteos-votacion"]').text()).toContain('Total 11')
    // La fixture tiene 3 presentes sobre 3 requeridos: desde WP-058 ese empate
    // exacto se anuncia como `Quórum límite`, sin dejar de estar alcanzado.
    expect(wrapper.get('[data-testid="estado-quorum"]').text()).toBe('Quórum límite')
    expect(wrapper.get('[data-testid="panel-palabra"]').text()).not.toContain('Nombre1 Apellido1')
    wrapper.unmount()
  })

  it.each([
    ['RECHAZADA', 'Rechazada'],
    ['INCONCLUSA', 'Inconclusa'],
  ])('muestra %s sin inventar una explicación causal', (resultado, etiqueta) => {
    vi.useFakeTimers()
    vi.setSystemTime(HORA_BASE)
    const wrapper = montar(
      crearSesionConVotacion(
        crearVotacionPublicaPrueba({
          estado_recepcion: 'CERRADA',
          resultado,
          resultado_visible_hasta: '2026-08-28T10:00:10Z',
          votos_individuales: [],
          conteos: { positivos: 0, negativos: 0, abstenciones: 0, total: 0 },
        }),
      ),
    )
    expect(wrapper.get('[data-testid="estado-votacion"]').text()).toBe(etiqueta)
    expect(wrapper.text()).not.toContain('pérdida')
    expect(wrapper.text()).not.toContain('manual')
    wrapper.unmount()
  })

  it('mantiene EMPATADA sin expiración y conserva votos ordinarios visibles', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(HORA_BASE)
    const wrapper = montar(
      crearSesionConVotacion(
        crearVotacionPublicaPrueba({
          estado_recepcion: 'CERRADA',
          resultado: 'EMPATADA',
          resultado_visible_hasta: null,
          votos_individuales: [
            { nombre: 'Nombre1', apellido: 'Apellido1', banca: 1, valor: 'POSITIVO' },
            { nombre: 'Nombre2', apellido: 'Apellido2', banca: 2, valor: 'NEGATIVO' },
          ],
          conteos: { positivos: 1, negativos: 1, abstenciones: 0, total: 2 },
        }),
      ),
    )

    expect(wrapper.get('[data-testid="estado-votacion"]').text()).toBe('Empatada')
    expect(wrapper.get('[data-testid="espera-desempate"]').text()).toContain('Presidencia')
    // Una votación empatada ya está cerrada: la espera del desempate no puede
    // tapar los conteos autoritativos que el backend ya publicó.
    expect(wrapper.get('[data-testid="conteos-votacion"]').text()).toContain('Positivos 1')
    expect(wrapper.get('[data-testid="conteos-votacion"]').text()).toContain('Total 2')
    expect(vi.getTimerCount()).toBe(1)
    vi.advanceTimersByTime(60_000)
    await wrapper.vm.$nextTick()
    expect(wrapper.get('[data-testid="estado-votacion"]').text()).toBe('Empatada')
    expect(contarBancasConResultado(wrapper)).toBe(2)
    wrapper.unmount()
  })

  it('muestra el voto presidencial separado y no altera bancas ni conteos', () => {
    vi.useFakeTimers()
    vi.setSystemTime(HORA_BASE)
    const votos = [
      { nombre: 'Nombre1', apellido: 'Apellido1', banca: 1, valor: 'POSITIVO' },
      { nombre: 'Nombre2', apellido: 'Apellido2', banca: 2, valor: 'NEGATIVO' },
    ]
    const wrapper = montar(
      crearSesionConVotacion(
        crearVotacionPublicaPrueba({
          estado_recepcion: 'CERRADA',
          resultado: 'RECHAZADA',
          resultado_visible_hasta: '2026-08-28T10:00:10Z',
          votos_individuales: votos,
          conteos: { positivos: 1, negativos: 1, abstenciones: 0, total: 2 },
          voto_presidencial: { presidencia: 'Ana Presidencia', sentido: 'NEGATIVO' },
        }),
      ),
    )

    const presidencial = wrapper.get('[data-testid="voto-presidencial"]')
    expect(presidencial.text()).toContain('Ana Presidencia')
    expect(presidencial.text()).toContain('Negativo')
    expect(contarBancasConResultado(wrapper)).toBe(2)
    expect(wrapper.get('[data-testid="conteos-votacion"]').text()).toContain('Total 2')
    expect(wrapper.get('[data-banca="3"]').element.getAttribute('data-estado-banca')).not.toContain(
      'RESULTADO_',
    )
    wrapper.unmount()
  })

  it('expira desde resultado_visible_hasta, reemplaza con una nueva votación y limpia SIN_PREPARAR', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(HORA_BASE)
    const wrapper = montar(
      crearSesionConVotacion(
        crearVotacionPublicaPrueba({
          estado_recepcion: 'CERRADA',
          resultado: 'APROBADA',
          resultado_visible_hasta: '2026-08-28T10:00:02Z',
          votos_individuales: [
            { nombre: 'Nombre1', apellido: 'Apellido1', banca: 1, valor: 'POSITIVO' },
          ],
          conteos: { positivos: 1, negativos: 0, abstenciones: 0, total: 1 },
        }),
      ),
    )

    expect(wrapper.get('[data-testid="estado-votacion"]').text()).toBe('Aprobada')
    vi.advanceTimersByTime(2250)
    await wrapper.vm.$nextTick()
    expect(wrapper.get('[data-testid="estado-votacion"]').text()).toBe('Sin votación')
    expect(wrapper.find('[data-estado-banca^="RESULTADO_"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="panel-quorum"]').exists()).toBe(true)

    await wrapper.setProps({
      estado: crearSesionConVotacion(
        crearVotacionPublicaPrueba({
          id: 'votacion-2',
          numero_votacion: 2,
          tema: 'Nueva votación inmediata',
          cuenta_regresiva_hasta: '2026-08-28T10:00:06Z',
        }),
        { revision: 2, generado_en: '2026-08-28T10:00:02.250Z' },
      ),
    })
    expect(wrapper.get('[data-testid="tema-votacion"]').text()).toContain('Nueva votación')
    expect(wrapper.find('[data-estado-banca^="RESULTADO_"]').exists()).toBe(false)

    await wrapper.setProps({
      estado: crearEstadoRecintoPrueba({ revision: 0, estado_global: 'SIN_PREPARAR' }),
    })
    expect(wrapper.get('[data-testid="estado-sin-preparar"]').exists()).toBe(true)
    expect(vi.getTimerCount()).toBe(1)
    wrapper.unmount()
  })

  it('no muestra un resultado ya vencido y cancela el ticker al desmontar', () => {
    vi.useFakeTimers()
    vi.setSystemTime(HORA_BASE)
    const vencido = montar(
      crearSesionConVotacion(
        crearVotacionPublicaPrueba({
          estado_recepcion: 'CERRADA',
          resultado: 'INCONCLUSA',
          resultado_visible_hasta: '2026-08-28T09:59:59Z',
        }),
      ),
    )
    expect(vencido.get('[data-testid="estado-votacion"]').text()).toBe('Sin votación')
    vencido.unmount()

    const conTimer = montar(
      crearSesionConVotacion(
        crearVotacionPublicaPrueba({ cuenta_regresiva_hasta: '2026-08-28T10:00:04Z' }),
      ),
    )
    // Cabecera + presentación temporal de votación.
    expect(vi.getTimerCount()).toBe(2)
    conTimer.unmount()
    expect(vi.getTimerCount()).toBe(0)
  })
})
