/**
 * Pruebas DOM del shell público completo.
 *
 * La vista presentacional y sus componentes se montan realmente con Vue Test
 * Utils. El transporte se prueba por separado en la frontera del composable.
 */

import { mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import BancaPublica from '../app/components/BancaPublica.vue'
import PantallaRecinto from '../app/components/PantallaRecinto.vue'
import { crearConcejalesPublicos, crearEstadoRecintoPrueba } from './datos_prueba'

const montados: VueWrapper[] = []

async function montarPantalla(estado = crearEstadoRecintoPrueba()) {
  const wrapper = mount(PantallaRecinto, {
    props: { estado, estadoConexion: 'CONECTADO', desactualizado: false },
  })
  montados.push(wrapper)
  return wrapper
}

afterEach(() => {
  while (montados.length > 0) montados.pop()?.unmount()
})

describe('Shell público del Recinto', () => {
  it('distingue ausencia de snapshot y SIN_PREPARAR sin conservar datos funcionales', async () => {
    const wrapper = mount(PantallaRecinto, {
      props: { estado: null, estadoConexion: 'INICIAL', desactualizado: false },
    })
    montados.push(wrapper)
    expect(wrapper.get('[data-testid="estado-inicial"]').text()).toContain('Conectando')

    await wrapper.setProps({
      estado: crearEstadoRecintoPrueba({
        estado_global: 'SIN_PREPARAR',
        filas_bancas: null,
        concejales: [],
        quorum: null,
        palabra: null,
      }),
    })

    expect(wrapper.get('[data-testid="estado-sin-preparar"]').text()).toContain(
      'Recinto sin preparar',
    )
    expect(wrapper.find('[data-testid="grilla-bancas"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="panel-quorum"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="panel-palabra"]').exists()).toBe(false)
  })

  it('renderiza PREPARANDO con filas [5,7], asociación por banca y estados inequívocos', async () => {
    const concejales = crearConcejalesPublicos(12)
      .filter((concejal) => concejal.banca !== 4)
      .reverse()
    const wrapper = await montarPantalla(
      crearEstadoRecintoPrueba({
        estado_global: 'PREPARANDO',
        preparacion: {
          fecha_hora_inicio: '2026-08-27T10:00:00Z',
          numero_sesion: 25,
          presidencia: 'María Presidencia',
          secretaria_legislativa: null,
        },
        filas_bancas: [5, 7],
        concejales,
        quorum: { cantidad_presentes: 6, requerido: 7, alcanzado: false },
      }),
    )

    expect(wrapper.get('[data-testid="cabecera-sesion"]').text()).toContain('25')
    expect(wrapper.get('[data-testid="cabecera-autoridades"]').text()).toContain(
      'María Presidencia',
    )
    // Desde WP-097 el bloque de quórum sólo dibuja título y número: el nivel se
    // lee del atributo del panel, que es su único portador.
    expect(
      wrapper.get('[data-testid="panel-quorum"]').element.getAttribute('data-nivel-quorum'),
    ).toBe('insuficiente')

    const filas = wrapper.findAll('.fila-bancas')
    expect(filas).toHaveLength(2)
    const filaSuperior = wrapper.get('[data-testid="fila-fisica-2"]')
    expect(filaSuperior.findAll('[data-testid="banca-publica"]')).toHaveLength(7)
    expect(filaSuperior.find('[data-banca="6"]').exists()).toBe(true)
    expect(filaSuperior.find('[data-banca="12"]').exists()).toBe(true)
    const filaInferior = wrapper.get('[data-testid="fila-fisica-1"]')
    expect(filaInferior.findAll('[data-banca]')).toHaveLength(5)
    // WP-045: la identidad ya no se dibuja como texto; vive en el bitmap y en
    // `aria-label`. La tarjeta solo muestra imagen + como máximo una etiqueta.
    expect(
      filaInferior.findAll('[data-testid="banca-publica"]')[0]?.element.getAttribute('aria-label'),
    ).toContain('Nombre1')
    expect(filaInferior.get('[data-banca="4"]').text()).toContain('sin datos públicos')
    expect(filaInferior.get('[data-banca="5"]').element.getAttribute('aria-label')).toContain(
      'Nombre5',
    )

    const bancaDos = wrapper.get('[data-banca="2"]')
    expect(bancaDos.element.getAttribute('data-estado-banca')).toBe('AUSENTE')
    expect(bancaDos.get('[data-testid="etiqueta-banca"]').text()).toBe('Ausente')
    expect(bancaDos.find('[data-ruta-imagen="assets/bancas/banca-02.png"]').exists()).toBe(true)
    // El test es el estado principal y, por decisión HUMAN_GATE, no lleva etiqueta.
    const bancaTres = wrapper.get('[data-banca="3"]')
    expect(bancaTres.element.getAttribute('data-estado-banca')).toBe('TEST')
    expect(bancaTres.find('[data-testid="etiqueta-banca"]').exists()).toBe(false)
  })

  it('muestra sesión, autoridades, quórum, orador y cola FIFO aun con votación', async () => {
    const wrapper = await montarPantalla(
      crearEstadoRecintoPrueba({
        estado_global: 'SESION_ABIERTA',
        sesion: {
          fecha_hora_inicio_preparacion: '2026-08-27T10:00:00Z',
          fecha_hora_apertura: '2026-08-27T10:15:00Z',
          numero_sesion: 59,
          presidencia: 'Ana Presidencia',
          secretaria_legislativa: 'Luis Secretaría',
        },
        filas_bancas: [3, 4, 5],
        concejales: crearConcejalesPublicos(12),
        quorum: { cantidad_presentes: 8, requerido: 7, alcanzado: true },
        palabra: {
          orador: { nombre: 'Nombre4', apellido: 'Apellido4', banca: 4 },
          cola: [
            { nombre: 'Nombre7', apellido: 'Apellido7', banca: 7 },
            { nombre: 'Nombre1', apellido: 'Apellido1', banca: 1 },
          ],
        },
        votacion: {
          id: 'votacion-en-curso',
          numero_votacion: 2,
          tipo: 'Despacho',
          tema: 'Tema reservado para WP-026',
          tipo_mayoria: 'SIMPLE',
          factor: 0,
          base: 'VOTOS_COMPUTABLES',
          estado_recepcion: 'EN_CURSO',
          resultado: null,
          fecha_hora_apertura: '2026-08-27T10:20:00Z',
          fecha_hora_cierre: null,
          cuenta_regresiva_hasta: null,
          resultado_visible_hasta: null,
          votos_individuales: null,
          conteos: null,
          voto_presidencial: null,
        },
      }),
    )

    expect(wrapper.get('[data-testid="cabecera-sesion"]').text()).toContain('59')
    expect(wrapper.get('[data-testid="cabecera-autoridades"]').text()).toContain('Ana Presidencia')
    expect(wrapper.get('[data-testid="cabecera-autoridades"]').text()).toContain('Luis Secretaría')
    expect(
      wrapper.get('[data-testid="panel-quorum"]').element.getAttribute('data-nivel-quorum'),
    ).toBe('holgado')
    expect(wrapper.get('[data-banca="4"]').element.getAttribute('data-estado-banca')).toBe(
      'PALABRA',
    )
    expect(wrapper.get('[data-testid="panel-palabra"]').text()).not.toContain('Nombre4 Apellido4')
    expect(wrapper.get('[data-testid="cabecera-sesion"]').text()).toContain('59')
    expect(wrapper.get('[data-testid="cabecera-tiempo-sesion"]').exists()).toBe(true)

    /*
      WP-097 redistribuyó el renglón: el nombre pasó a la primera línea, a ancho
      completo, y el número de orden bajó junto a la banca. El orden FIFO de la
      cola no cambió —sigue siendo 7 y después 1—; lo que cambia es la posición
      del número dentro de cada renglón.
    */
    const pedidos = wrapper.findAll('[data-testid="cola-palabra"] li')
    expect(pedidos.map((pedido) => pedido.text())).toEqual([
      'Nombre7 Apellido71Banca 7',
      'Nombre1 Apellido12Banca 1',
    ])
    expect(wrapper.get('[data-testid="tema-votacion"]').text()).toContain(
      'Tema reservado para WP-026',
    )
    expect(wrapper.findAll('button, input, select, textarea, form')).toHaveLength(0)
  })

  it('mueve y limpia el resaltado del orador con cada baseline', async () => {
    const estadoBase = crearEstadoRecintoPrueba({
      estado_global: 'SESION_ABIERTA',
      sesion: {
        fecha_hora_inicio_preparacion: '2026-08-27T10:00:00Z',
        fecha_hora_apertura: '2026-08-27T10:15:00Z',
        numero_sesion: 59,
        presidencia: 'Presidencia',
        secretaria_legislativa: 'Secretaría',
      },
      filas_bancas: [2],
      concejales: crearConcejalesPublicos(2),
      quorum: { cantidad_presentes: 1, requerido: 1, alcanzado: true },
      palabra: {
        orador: { nombre: 'Nombre1', apellido: 'Apellido1', banca: 1 },
        cola: [],
      },
    })
    const wrapper = await montarPantalla(estadoBase)

    expect(wrapper.get('[data-banca="1"]').element.getAttribute('data-estado-banca')).toBe(
      'PALABRA',
    )
    expect(wrapper.get('[data-banca="2"]').element.getAttribute('data-estado-banca')).not.toBe(
      'PALABRA',
    )

    await wrapper.setProps({
      estado: {
        ...estadoBase,
        revision: 2,
        palabra: {
          orador: { nombre: 'Nombre2', apellido: 'Apellido2', banca: 2 },
          cola: [],
        },
      },
    })
    expect(wrapper.get('[data-banca="1"]').element.getAttribute('data-estado-banca')).not.toBe(
      'PALABRA',
    )
    expect(wrapper.get('[data-banca="2"]').element.getAttribute('data-estado-banca')).toBe(
      'PALABRA',
    )

    await wrapper.setProps({
      estado: { ...estadoBase, revision: 3, palabra: { orador: null, cola: [] } },
    })
    expect(wrapper.find('[data-estado-banca="PALABRA"]').exists()).toBe(false)
  })

  it('conserva la vista al reconectar, adopta SIN_PREPARAR y degrada imagen rota', async () => {
    const wrapper = await montarPantalla(
      crearEstadoRecintoPrueba({
        estado_global: 'PREPARANDO',
        preparacion: {
          fecha_hora_inicio: '2026-08-27T10:00:00Z',
          numero_sesion: null,
          presidencia: null,
          secretaria_legislativa: null,
        },
        filas_bancas: [1],
        concejales: crearConcejalesPublicos(1),
        quorum: { cantidad_presentes: 1, requerido: 1, alcanzado: true },
      }),
    )
    await wrapper.setProps({ estadoConexion: 'RECONECTANDO', desactualizado: true })

    // WP-070 acortó este aviso: el indicador dice exactamente "(Sin conexion)".
    expect(wrapper.get('[data-testid="estado-conexion"]').text()).toContain('(Sin conexion)')
    expect(wrapper.get('[data-banca="1"]').exists()).toBe(true)

    await wrapper.setProps({
      estado: crearEstadoRecintoPrueba({ revision: 0, estado_global: 'SIN_PREPARAR' }),
    })
    expect(wrapper.get('[data-testid="estado-sin-preparar"]').exists()).toBe(true)
    expect(wrapper.find('[data-banca="1"]').exists()).toBe(false)

    const banca = mount(BancaPublica, {
      props: {
        concejal: crearConcejalesPublicos(1)[0]!,
        esOrador: false,
        estadoRecepcion: null,
        votoEmitido: false,
        valorVotoFinal: null,
      },
    })
    await banca.get('img').trigger('error')
    expect(banca.get('[data-testid="imagen-fallback"]').text()).toBe('NA')
  })

  it('unifica ausencia y reinicia una imagen fallida al cambiar persona o ruta', async () => {
    const concejalAusente = {
      ...crearConcejalesPublicos(1)[0]!,
      presente: false,
      test_activo: true,
    }
    const banca = mount(BancaPublica, {
      props: {
        concejal: concejalAusente,
        esOrador: true,
        estadoRecepcion: null,
        votoEmitido: false,
        valorVotoFinal: null,
      },
    })

    // Prioridad WP-045: test gana a palabra y a ausencia. El estado principal es
    // TEST (sin etiqueta) y la palabra subordinada sobrevive solo como halo.
    expect(banca.element.getAttribute('data-estado-banca')).toBe('TEST')
    expect(banca.find('[data-testid="etiqueta-banca"]').exists()).toBe(false)
    expect(banca.element.getAttribute('data-halo-palabra')).toBe('true')
    expect(banca.element.getAttribute('aria-label')).toContain('Banca 1')
    expect(banca.text()).not.toContain('Banca 1')

    await banca.get('[data-testid="imagen-concejal"]').trigger('error')
    expect(banca.get('[data-testid="imagen-fallback"]').text()).toBe('NA')

    // Se reutiliza deliberadamente la misma ruta: el cambio de persona también
    // debe invalidar el error visual perteneciente a la baseline anterior.
    await banca.setProps({
      concejal: {
        ...concejalAusente,
        nombre: 'Otra',
        apellido: 'Persona',
        presente: true,
      },
    })
    expect(banca.find('[data-testid="imagen-concejal"]').exists()).toBe(true)
    expect(banca.find('[data-testid="imagen-fallback"]').exists()).toBe(false)
    expect(banca.element.getAttribute('data-presente')).toBe('true')
    expect(concejalAusente.presente).toBe(false)
  })
})
