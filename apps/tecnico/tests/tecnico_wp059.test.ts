/**
 * Pruebas de la reorganización de la interfaz de Apoyo Técnico (WP-059).
 *
 * La distribución en sí —cuatro columnas visuales, Avisos en la fila inferior completa,
 * qué panel scrollea y cuál no— se mide con Playwright en
 * `tests/playwright/apoyo_tecnico_wp059.spec.ts`, porque el DOM de Vitest no calcula
 * layout: acá `getBoundingClientRect` devolvería ceros y cualquier afirmación sobre
 * proporciones sería falsa.
 *
 * Lo que sí puede comprobarse sobre el DOM, y es lo que cubre este archivo, son las dos
 * decisiones humanas del WP que no dependen del layout:
 *
 * 1. la cabecera dejó de mostrar la marca "Botonera2" **sin** perder ningún indicador;
 * 2. reorganizar Avisos en dos zonas —redacción y avisos vigentes— no eliminó ni
 *    deshabilitó ningún control del puesto.
 *
 * El punto 2 es la red de seguridad contra el riesgo real de un WP de layout: mover cajas
 * y perder por el camino una capacidad operativa.
 */

import { mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ClienteApoyoTecnico } from '@sis-leg/api-client'
import CabeceraTecnico from '../app/components/CabeceraTecnico.vue'
import ControlAvisos from '../app/components/ControlAvisos.vue'
import { crearAvisoPrueba, crearMensajePrueba } from './datos_prueba'

const montados: VueWrapper[] = []

afterEach(() => {
  while (montados.length > 0) montados.pop()?.unmount()
})

function montar(componente: unknown, props: Record<string, unknown>): VueWrapper {
  const wrapper = mount(componente as never, { props })
  montados.push(wrapper)
  return wrapper
}

/** Cliente técnico con todos los comandos espiados; ninguna prueba toca la red. */
function crearClienteEspia(): ClienteApoyoTecnico {
  return {
    iniciarTransmision: vi.fn().mockResolvedValue(undefined),
    detenerTransmision: vi.fn().mockResolvedValue(undefined),
    publicarAviso: vi.fn().mockResolvedValue(undefined),
    cancelarAviso: vi.fn().mockResolvedValue(undefined),
    crearMensaje: vi.fn().mockResolvedValue(crearMensajePrueba('m-nuevo', 'Nuevo')),
    actualizarMensaje: vi.fn().mockResolvedValue(crearMensajePrueba('m-1', 'Editado')),
    eliminarMensaje: vi.fn().mockResolvedValue(undefined),
    listarMensajes: vi.fn(),
    obtenerEstado: vi.fn(),
    suscribirEstado: vi.fn(),
  } as unknown as ClienteApoyoTecnico
}

/** Props mínimas de `ControlAvisos`, con las dos ranuras vacías salvo indicación. */
function propsAvisos(parcial: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    avisoModeracion: null,
    avisoRecinto: null,
    cliente: crearClienteEspia(),
    conectado: true,
    borrador: null,
    segundosRestantes: () => null,
    ...parcial,
  }
}

describe('Cabecera sin la marca del sistema', () => {
  it('muestra el nombre del puesto y ya no muestra "Botonera2"', () => {
    const wrapper = montar(CabeceraTecnico, {
      estadoConexion: 'CONECTADO',
      estadoGlobal: 'SESION_ABIERTA',
      revision: 7,
      desactualizado: false,
      estadoTransmision: 'APAGADO',
    })

    // El entorno DOM de estas pruebas es un mock liviano sin `outerHTML`, así que la
    // comprobación se hace sobre el texto renderizado, que sí es fiel.
    const texto = wrapper.text()
    expect(texto).not.toContain('Botonera2')
    expect(texto).not.toContain('BOTONERA2')
    expect(wrapper.get('h1').text()).toBe('Apoyo Técnico')
  })

  it('conserva todos los indicadores útiles después de recortar el título', () => {
    // La decisión humana del WP fue explícita: se quita la marca, no se reduce
    // información. El puesto técnico es de igual confianza que Moderación.
    const wrapper = montar(CabeceraTecnico, {
      estadoConexion: 'RECONECTANDO',
      estadoGlobal: 'PREPARANDO',
      revision: 12,
      desactualizado: true,
      estadoTransmision: 'EN_VIVO',
    })

    expect(wrapper.get('[data-testid="estado-global-tecnico"]').text()).toBe(
      'Recinto en preparación',
    )
    expect(wrapper.get('[data-testid="resumen-transmision"]').text()).toBe('En vivo')
    expect(wrapper.get('[data-testid="estado-conexion"]').text()).toBe('Reconectando')
    expect(wrapper.find('[data-testid="aviso-desactualizado"]').exists()).toBe(true)
  })
})

describe('Avisos reorganizado en zona de redacción y zona de vigentes', () => {
  it('mantiene todos los controles de publicación habilitados', () => {
    const wrapper = montar(ControlAvisos, propsAvisos())

    // La zona de redacción conserva sus cuatro controles.
    for (const control of [
      'input-texto-aviso',
      'select-destino-aviso',
      'input-duracion-aviso',
      'btn-publicar-aviso',
    ]) {
      const elemento = wrapper.get(`[data-testid="${control}"]`)
      expect(elemento.attributes('disabled')).toBeUndefined()
    }

    // La zona de vigentes conserva una ranura por destino, aun estando vacías.
    expect(wrapper.get('[data-testid="ranura-moderacion"]').text()).toContain('Sin aviso vigente')
    expect(wrapper.get('[data-testid="ranura-recinto"]').text()).toContain('Sin aviso vigente')
  })

  it('separa la redacción de las ranuras vigentes sin perder la cancelación por destino', async () => {
    const cliente = crearClienteEspia()
    const wrapper = montar(
      ControlAvisos,
      propsAvisos({
        cliente,
        avisoModeracion: crearAvisoPrueba({ texto: 'Cuarto intermedio', destino: 'MODERACION' }),
        avisoRecinto: crearAvisoPrueba({ texto: 'Se reanuda la sesión', destino: 'RECINTO' }),
      }),
    )

    // Las dos ranuras viven en el contenedor propio que introdujo WP-059 y siguen
    // mostrando su texto vigente completo, sin recortes.
    const zonaVigentes = wrapper.get('[data-testid="ranuras-avisos"]')
    expect(zonaVigentes.find('[data-testid="ranura-moderacion"]').exists()).toBe(true)
    expect(zonaVigentes.find('[data-testid="ranura-recinto"]').exists()).toBe(true)
    expect(wrapper.get('[data-testid="texto-vigente-moderacion"]').text()).toBe('Cuarto intermedio')
    expect(wrapper.get('[data-testid="texto-vigente-recinto"]').text()).toBe('Se reanuda la sesión')

    // Cancelar sigue afectando exclusivamente al destino elegido.
    await wrapper.get('[data-testid="btn-cancelar-recinto"]').trigger('click')
    expect(cliente.cancelarAviso).toHaveBeenCalledTimes(1)
    expect(cliente.cancelarAviso).toHaveBeenCalledWith('RECINTO')
  })

  it('publica con el mismo contrato después de reorganizar el formulario', async () => {
    const cliente = crearClienteEspia()
    const wrapper = montar(ControlAvisos, propsAvisos({ cliente }))

    await wrapper.get('[data-testid="input-texto-aviso"]').setValue('  Prueba de sonido  ')
    await wrapper.get('[data-testid="select-destino-aviso"]').setValue('MODERACION')
    await wrapper.get('[data-testid="input-duracion-aviso"]').setValue('90')
    await wrapper.get('[data-testid="btn-publicar-aviso"]').trigger('click')

    // Texto recortado, destino elegido y duración entera: el contrato no cambió.
    expect(cliente.publicarAviso).toHaveBeenCalledWith('Prueba de sonido', 'MODERACION', 90)
  })
})
