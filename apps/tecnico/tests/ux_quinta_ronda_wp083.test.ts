/**
 * WP-083 — Ajustes de microcopy y densidad del puesto de Apoyo Técnico.
 *
 * La quinta ronda de revisión humana cerró cuatro correcciones sobre esta pantalla, y
 * las cuatro son afirmaciones sobre el DOM, no sobre el layout:
 *
 * 1. ningún panel técnico dibuja subtítulo;
 * 2. el primer panel se titula exactamente `Indicador de transmisión`;
 * 3. la cuenta regresiva propuesta al abrir la pantalla es 5 segundos;
 * 4. la biblioteca se lee como «avisos precargados» en todos sus textos visibles.
 *
 * El ancho real del campo de segundos y la ausencia de recorte se miden en
 * `tests/playwright/ux_quinta_ronda_wp083.spec.ts`, porque jsdom no calcula cajas: acá
 * `getBoundingClientRect` devolvería ceros y cualquier afirmación sobre píxeles sería
 * falsa. Las dos pruebas son complementarias.
 *
 * Una advertencia que conviene leer antes de tocar este archivo: el renombre de la quinta
 * ronda es **sólo visible**. Los `data-testid`, el DTO, el endpoint y el CSV siguen
 * diciendo «mensaje», así que estas pruebas localizan por `data-testid` y afirman sobre el
 * texto. Si alguna vez hiciera falta cambiar un `data-testid`, ya no sería microcopy: sería
 * un cambio de contrato y quedaría fuera del alcance de este WP.
 */

import { mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ClienteApoyoTecnico } from '@sis-leg/api-client'
import PanelTecnico from '../app/components/PanelTecnico.vue'
import ControlTransmision from '../app/components/ControlTransmision.vue'
import BibliotecaMensajes from '../app/components/BibliotecaMensajes.vue'
import { crearBibliotecaPrueba, crearMensajePrueba, crearTransmisionPrueba } from './datos_prueba'

/** Cuenta regresiva propuesta que cerró HUMAN_GATE en la quinta ronda. */
const CUENTA_PROPUESTA = 5

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

// =============================================================================
// 1. Encabezado sin subtítulo
// =============================================================================

describe('Encabezado de los paneles técnicos', () => {
  it('dibuja el título y ningún renglón adicional de aclaración', () => {
    const wrapper = montar(PanelTecnico, {
      titulo: 'Indicador de transmisión',
      dataTestid: 'panel-transmision',
    })

    const encabezado = wrapper.get('header')
    expect(encabezado.get('h2').text()).toBe('Indicador de transmisión')
    // El subtítulo se dibujaba como el único `<p>` del encabezado: si no hay ninguno,
    // no hay forma de que quede una aclaración visible debajo del título.
    expect(encabezado.findAll('p')).toHaveLength(0)
  })

  it('ignora un subtítulo pasado por descuido, porque ya no forma parte del contrato', () => {
    /*
      Esta prueba defiende la decisión, no la implementación actual. `PanelTecnico` dejó
      de declarar la prop `subtitulo`; Vue no falla al recibir una prop no declarada, la
      deja pasar como atributo. Lo que no puede volver a ocurrir es que ese texto se
      pinte dentro del encabezado, y eso es exactamente lo que se afirma acá.
    */
    const wrapper = montar(PanelTecnico, {
      titulo: 'Eventos',
      subtitulo: 'Misma franja segura que ve Moderación',
    })

    expect(wrapper.get('header').text()).toBe('Eventos')
  })

  it('conserva el badge y la ranura de acciones del encabezado', () => {
    // Quitar el subtítulo no puede haberse llevado por delante las otras dos piezas
    // opcionales del encabezado, que otros paneles siguen usando.
    const wrapper = mount(PanelTecnico as never, {
      props: { titulo: 'Avisos', badge: 'L2' },
      slots: { acciones: '<button data-testid="accion-panel">Filtrar</button>' },
    })
    montados.push(wrapper)

    expect(wrapper.text()).toContain('L2')
    expect(wrapper.find('[data-testid="accion-panel"]').exists()).toBe(true)
  })
})

// =============================================================================
// 2. Cuenta regresiva propuesta
// =============================================================================

describe('Cuenta regresiva propuesta por el puesto técnico', () => {
  it('propone 5 segundos al abrir la pantalla', () => {
    const wrapper = montar(ControlTransmision, {
      transmision: crearTransmisionPrueba({ estado: 'APAGADO' }),
      segundosRestantes: null,
      cliente: crearClienteEspia(),
      conectado: true,
    })

    const campo = wrapper.get('[data-testid="input-cuenta-regresiva"]').element as HTMLInputElement
    expect(campo.value).toBe(String(CUENTA_PROPUESTA))
  })

  it('inicia con la propuesta cuando el operador no la edita', async () => {
    const cliente = crearClienteEspia()
    const wrapper = montar(ControlTransmision, {
      transmision: crearTransmisionPrueba({ estado: 'APAGADO' }),
      segundosRestantes: null,
      cliente,
      conectado: true,
    })

    await wrapper.get('[data-testid="btn-transmision-cuenta"]').trigger('click')

    expect(cliente.iniciarTransmision).toHaveBeenCalledWith(CUENTA_PROPUESTA)
  })

  it('sigue aceptando y validando todo el rango del contrato', async () => {
    // El valor propuesto es una comodidad, no una restricción nueva: el contrato REST
    // sigue admitiendo 1..3600 y el aviso de rango sigue apareciendo fuera de él.
    const cliente = crearClienteEspia()
    const wrapper = montar(ControlTransmision, {
      transmision: crearTransmisionPrueba({ estado: 'APAGADO' }),
      segundosRestantes: null,
      cliente,
      conectado: true,
    })

    await wrapper.get('[data-testid="input-cuenta-regresiva"]').setValue('3600')
    await wrapper.get('[data-testid="btn-transmision-cuenta"]').trigger('click')
    expect(cliente.iniciarTransmision).toHaveBeenCalledWith(3600)

    await wrapper.get('[data-testid="input-cuenta-regresiva"]').setValue('3601')
    expect(wrapper.find('[data-testid="cuenta-invalida"]').exists()).toBe(true)
  })
})

// =============================================================================
// 3. Microcopy de la biblioteca
// =============================================================================

describe('Microcopy visible de la biblioteca', () => {
  it('rotula el alta como «Nuevo aviso precargado»', () => {
    const wrapper = montar(BibliotecaMensajes, {
      biblioteca: crearBibliotecaPrueba(),
      cliente: crearClienteEspia(),
      conectado: true,
    })

    // El alta es la única etiqueta `<label>` del panel: los demás controles se describen
    // con `aria-label`. Se localiza por etiqueta y no por el selector `label[for=...]`
    // porque el DOM simulado de estas pruebas no resuelve selectores compuestos.
    const etiquetas = wrapper.findAll('label')
    expect(etiquetas).toHaveLength(1)
    expect(etiquetas[0]!.text()).toBe('Nuevo aviso precargado')
    expect(etiquetas[0]!.element.getAttribute('for')).toBe('texto-mensaje-nuevo')
  })

  it('nombra la lista vacía como avisos precargados', () => {
    const wrapper = montar(BibliotecaMensajes, {
      biblioteca: crearBibliotecaPrueba({ mensajes: [] }),
      cliente: crearClienteEspia(),
      conectado: true,
    })

    expect(wrapper.get('[data-testid="biblioteca-vacia"]').text()).toBe('No hay avisos precargados')
  })

  it('no deja ningún «mensaje precargado» visible con la biblioteca cargada', () => {
    const wrapper = montar(BibliotecaMensajes, {
      biblioteca: crearBibliotecaPrueba({
        mensajes: [crearMensajePrueba('m-1', 'Cuarto intermedio', 'AMBOS')],
      }),
      cliente: crearClienteEspia(),
      conectado: true,
    })

    // Se compara en minúsculas para atrapar también «Mensaje precargado» al inicio de
    // una oración, que es la forma en la que estaba escrito el rótulo del alta.
    expect(wrapper.text().toLowerCase()).not.toContain('mensaje precargado')
    expect(wrapper.text().toLowerCase()).not.toContain('mensajes precargados')
  })

  it('mantiene los contratos internos, que el WP prohíbe renombrar', () => {
    /*
      La contracara del renombre visible: los identificadores por los que se localiza cada
      control, y el `mensaje_id` que viaja al backend, siguen diciendo «mensaje». Si
      alguien "completara" el renombre tocando estos nombres, rompería el CSV, el endpoint
      y todas las pruebas que dependen de ellos.
    */
    const wrapper = montar(BibliotecaMensajes, {
      biblioteca: crearBibliotecaPrueba({
        mensajes: [crearMensajePrueba('m-1', 'Cuarto intermedio', 'AMBOS')],
      }),
      cliente: crearClienteEspia(),
      conectado: true,
    })

    expect(wrapper.find('[data-testid="biblioteca-mensajes"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="lista-mensajes"]').exists()).toBe(true)
    expect(
      wrapper.get('[data-testid="mensaje-precargado"]').element.getAttribute('data-mensaje-id'),
    ).toBe('m-1')
  })

  it('nombra el fallo de alta como aviso precargado', async () => {
    const cliente = crearClienteEspia()
    // El rechazo no lleva ningún texto propio, así que `extraerMensajeError` cae en el
    // mensaje predeterminado: justamente la cadena que este WP renombró.
    ;(cliente.crearMensaje as unknown as ReturnType<typeof vi.fn>).mockRejectedValue({})
    const wrapper = montar(BibliotecaMensajes, {
      biblioteca: crearBibliotecaPrueba(),
      cliente,
      conectado: true,
    })

    await wrapper.get('[data-testid="input-mensaje-nuevo"]').setValue('Cuarto intermedio')
    await wrapper.get('[data-testid="btn-crear-mensaje"]').trigger('click')
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()

    expect(wrapper.get('[data-testid="error-biblioteca"]').text()).toBe(
      'No se pudo crear el aviso precargado.',
    )
  })
})
