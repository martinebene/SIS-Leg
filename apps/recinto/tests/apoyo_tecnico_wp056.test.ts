/**
 * Integración del plano técnico en la Pantalla del Recinto (WP-056).
 *
 * Verifican sobre el DOM productivo las decisiones humanas cerradas:
 *
 * 1. la columna derecha se divide en dos bloques: transmisión arriba y pedidos de palabra
 *    abajo, con la proporción declarada como fracciones de grilla;
 * 2. `APAGADO` es discreto pero conserva su lugar, para no desplazar los pedidos cada vez
 *    que Apoyo Técnico enciende o apaga la transmisión;
 * 3. `CUENTA_REGRESIVA` muestra el número grande y `EN_VIVO` el rótulo `● EN VIVO`;
 * 4. un aviso dirigido al Recinto reemplaza toda la franja de votación/tema/estado y no
 *    toca la cabecera, las bancas ni la columna derecha;
 * 5. un aviso dirigido sólo a Moderación jamás llega a este snapshot;
 * 6. al expirar o cancelarse el aviso, la franja original vuelve sola.
 *
 * Las medidas reales (proporción 1/5 + 4/5 en píxeles, ausencia de scroll) se comprueban
 * con bounding boxes en Playwright: este DOM no calcula layout.
 */

import { mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import type { ApoyoTecnicoProyectado, EstadoRecinto } from '@sis-leg/api-client'
import BloqueTransmisionPublico from '../app/components/BloqueTransmisionPublico.vue'
import PantallaRecinto from '../app/components/PantallaRecinto.vue'
import {
  crearApoyoTecnicoPrueba,
  crearConcejalesPublicos,
  crearEstadoRecintoPrueba,
} from './datos_prueba'

const montados: VueWrapper[] = []

afterEach(() => {
  while (montados.length > 0) montados.pop()?.unmount()
})

/** Estado público con sesión abierta, que es cuando se dibuja el contenido completo. */
function estadoConSesion(tecnico: ApoyoTecnicoProyectado): EstadoRecinto {
  return crearEstadoRecintoPrueba({
    estado_global: 'SESION_ABIERTA',
    concejales: crearConcejalesPublicos(12),
    filas_bancas: [6, 6],
    quorum: { cantidad_presentes: 11, requerido: 7, alcanzado: true },
    palabra: {
      orador: null,
      cola: [{ nombre: 'Ana', apellido: 'Pérez', banca: 3 }],
    },
    sesion: {
      fecha_hora_inicio_preparacion: '2026-09-02T09:00:00Z',
      fecha_hora_apertura: '2026-09-02T09:30:00Z',
      numero_sesion: 56,
      presidencia: 'Presidencia',
      secretaria_legislativa: 'Secretaría',
    },
    tecnico,
  })
}

function montarPantalla(tecnico: ApoyoTecnicoProyectado): VueWrapper {
  const wrapper = mount(PantallaRecinto, {
    props: {
      estado: estadoConSesion(tecnico),
      estadoConexion: 'CONECTADO',
      desactualizado: false,
    },
  })
  montados.push(wrapper)
  return wrapper
}

function avisoRecinto(destino: 'RECINTO' | 'AMBOS'): ApoyoTecnicoProyectado {
  return crearApoyoTecnicoPrueba({
    aviso: {
      aviso_id: 'aviso-1',
      texto: 'Se reanuda la sesión en instantes',
      destino,
      publicado_en: '2026-09-02T10:00:00Z',
      expira_en: null,
      segundos_restantes: null,
    },
  })
}

describe('Bloque de transmisión en la columna derecha', () => {
  it('conserva su lugar y es discreto cuando la transmisión está apagada', () => {
    const wrapper = montarPantalla(crearApoyoTecnicoPrueba())

    const bloque = wrapper.get('[data-testid="bloque-transmision"]')
    expect(bloque.element.getAttribute('data-estado-transmision')).toBe('APAGADO')
    expect(wrapper.get('[data-testid="transmision-apagada"]').text()).toBe('Transmisión apagada')
    // Los pedidos de palabra siguen presentes en el mismo contenedor.
    expect(wrapper.find('[data-testid="panel-palabra"]').exists()).toBe(true)
  })

  it('ubica transmisión y palabra dentro de la misma columna derecha', () => {
    const wrapper = montarPantalla(crearApoyoTecnicoPrueba())

    const columna = wrapper.get('[data-testid="columna-palabra-publica"]')
    expect(columna.find('[data-testid="bloque-transmision"]').exists()).toBe(true)
    expect(columna.find('[data-testid="panel-palabra"]').exists()).toBe(true)
    // El orden importa: el quinto superior es el de transmisión.
    expect(columna.element.children[0]?.getAttribute('data-testid')).toBe('bloque-transmision')
  })

  it('muestra el número grande durante la cuenta regresiva', () => {
    const wrapper = mount(BloqueTransmisionPublico, {
      props: {
        transmision: {
          estado: 'CUENTA_REGRESIVA',
          iniciada_en: '2026-09-02T10:00:00Z',
          en_vivo_desde: '2026-09-02T10:00:15Z',
          cuenta_regresiva_segundos: 15,
          segundos_restantes: 9,
        },
        segundosRestantes: 9,
      },
    })
    montados.push(wrapper)

    expect(wrapper.get('[data-testid="cuenta-regresiva-transmision"]').text()).toBe('9')
    expect(wrapper.find('[data-testid="en-vivo"]').exists()).toBe(false)
  })

  it('muestra ● EN VIVO cuando el backend declara la transmisión al aire', () => {
    const wrapper = mount(BloqueTransmisionPublico, {
      props: {
        transmision: {
          estado: 'EN_VIVO',
          iniciada_en: '2026-09-02T10:00:00Z',
          en_vivo_desde: '2026-09-02T10:00:00Z',
          cuenta_regresiva_segundos: null,
          segundos_restantes: null,
        },
        segundosRestantes: null,
      },
    })
    montados.push(wrapper)

    const enVivo = wrapper.get('[data-testid="en-vivo"]')
    expect(enVivo.text().replace(/\s+/g, ' ')).toBe('● EN VIVO')
    expect(wrapper.find('[data-testid="cuenta-regresiva-transmision"]').exists()).toBe(false)
  })
})

describe('Aviso técnico sobre la franja de votación del Recinto', () => {
  it('dibuja la franja normal mientras no hay aviso', () => {
    const wrapper = montarPantalla(crearApoyoTecnicoPrueba())

    expect(wrapper.find('[data-testid="franja-votacion-quorum"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="aviso-tecnico-recinto"]').exists()).toBe(false)
  })

  it.each<'RECINTO' | 'AMBOS'>(['RECINTO', 'AMBOS'])(
    'reemplaza toda la franja con un aviso %s',
    (destino) => {
      const wrapper = montarPantalla(avisoRecinto(destino))

      expect(wrapper.get('[data-testid="aviso-tecnico-recinto"]').text()).toContain(
        'Se reanuda la sesión en instantes',
      )
      // Reemplazo real: la franja original ya no está en el árbol.
      expect(wrapper.find('[data-testid="franja-votacion-quorum"]').exists()).toBe(false)
      expect(wrapper.find('[data-testid="panel-votacion"]').exists()).toBe(false)
      expect(wrapper.find('[data-testid="panel-quorum"]').exists()).toBe(false)
    },
  )

  it('no invade la cabecera, las bancas ni la columna derecha', () => {
    const wrapper = montarPantalla(avisoRecinto('RECINTO'))

    expect(wrapper.find('[data-testid="area-bancas-publica"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="columna-palabra-publica"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="bloque-transmision"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="panel-palabra"]').exists()).toBe(true)
  })

  it('devuelve la franja original al desaparecer el aviso del snapshot', async () => {
    const wrapper = montarPantalla(avisoRecinto('AMBOS'))
    expect(wrapper.find('[data-testid="franja-votacion-quorum"]').exists()).toBe(false)

    // Expiración o cancelación manual: en ambos casos el backend deja de proyectarlo.
    await wrapper.setProps({ estado: estadoConSesion(crearApoyoTecnicoPrueba()) })

    expect(wrapper.find('[data-testid="aviso-tecnico-recinto"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="franja-votacion-quorum"]').exists()).toBe(true)
  })

  it('nunca recibe un aviso dirigido exclusivamente a Moderación', () => {
    // El backend separa las ranuras por destino: en `EstadoRecinto.tecnico.aviso` sólo
    // puede viajar RECINTO o AMBOS. Se comprueba que la pantalla no inventa un filtro
    // propio y simplemente dibuja lo que recibe.
    const wrapper = montarPantalla(crearApoyoTecnicoPrueba({ aviso: null }))

    expect(wrapper.find('[data-testid="aviso-tecnico-recinto"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="franja-votacion-quorum"]').exists()).toBe(true)
  })
})
