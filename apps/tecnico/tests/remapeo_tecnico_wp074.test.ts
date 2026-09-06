/**
 * Remapeo del puesto de Apoyo Técnico sin ninguna suscripción a Moderación (WP-074).
 *
 * ## Qué demuestra esta suite
 *
 * WP-056 exige que el puesto técnico ofrezca **exactamente** el mismo remapeo que
 * Moderación. Hasta WP-074 eso se conseguía haciéndole observar el `EstadoModeracion`
 * completo por un stream propio, y ése era uno de los tres streams que dejaban al navegador
 * sin conexiones HTTP/1.1 disponibles para los comandos REST.
 *
 * Ahora el mismo componente compartido recibe la allowlist `EstadoTecnico.remapeo` y un
 * cliente que sólo sabe emitir los tres comandos. Lo que se comprueba acá es que esa
 * sustitución no cambió nada observable: se elige una banca, se inicia, se confirma con el
 * modo elegido y se cancela, con los mismos identificadores lógicos y las mismas
 * capacidades del backend.
 *
 * La geometría del panel y su presencia en la grilla ya las cubren otras suites; acá
 * interesa el comportamiento del remapeo con la proyección nueva.
 */

import { mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import GestionRemapeo from '@sis-leg/frontend-shared/componentes/GestionRemapeo.vue'
import type { ClienteRemapeo, EstadoRemapeoModeracion } from '@sis-leg/api-client'
import { crearRemapeoTecnicoPrueba } from './datos_prueba'

const montados: VueWrapper[] = []

afterEach(() => {
  while (montados.length > 0) montados.pop()?.unmount()
})

/** Cliente de remapeo con los tres comandos espiados; ninguna prueba toca la red. */
function crearClienteRemapeoEspia(): ClienteRemapeo {
  return {
    iniciarRemapeo: vi.fn().mockResolvedValue({
      remapeo_id: 'rem-1',
      dispositivo: 'dev01',
      estado: 'CAPTURANDO',
      fingerprint_anterior: 'fp-viejo',
      candidato: null,
      diagnostico: null,
    }),
    confirmarRemapeo: vi.fn().mockResolvedValue(undefined),
    cancelarRemapeo: vi.fn().mockResolvedValue(undefined),
  } as unknown as ClienteRemapeo
}

/** Operación con candidato congelado, que es la etapa donde se puede confirmar. */
function operacionConCandidato(): EstadoRemapeoModeracion {
  return {
    remapeo_id: 'rem-1',
    dispositivo: 'dev01',
    estado: 'CANDIDATO',
    fingerprint_anterior: 'fp-viejo',
    candidato: 'fp-nuevo',
    diagnostico: null,
  }
}

function montarPanel(
  estado: ReturnType<typeof crearRemapeoTecnicoPrueba> | null,
  cliente: ClienteRemapeo,
  conectado = true,
): VueWrapper {
  const wrapper = mount(GestionRemapeo as never, { props: { estado, cliente, conectado } })
  montados.push(wrapper)
  return wrapper
}

describe('Remapeo alimentado por la proyección técnica', () => {
  it('lista las bancas de la allowlist con su identificador lógico', () => {
    const wrapper = montarPanel(crearRemapeoTecnicoPrueba(), crearClienteRemapeoEspia())

    const opciones = wrapper.findAll('[data-testid="selector-banca-remapeo"] option')
    // La primera opción es el texto de invitación; después vienen las dos bancas.
    expect(opciones).toHaveLength(3)
    expect(opciones[1]?.text()).toContain('dev01')
    expect(opciones[2]?.text()).toContain('dev02')
  })

  it('inicia la captura con el devXX elegido y no con la banca ni el DNI', async () => {
    const cliente = crearClienteRemapeoEspia()
    const wrapper = montarPanel(crearRemapeoTecnicoPrueba(), cliente)

    await wrapper.get('[data-testid="selector-banca-remapeo"]').setValue('dev02')
    await wrapper.get('[data-testid="btn-iniciar-remapeo"]').trigger('click')

    expect(cliente.iniciarRemapeo).toHaveBeenCalledWith('dev02')
  })

  it('confirma el identificador proyectado con la persistencia elegida', async () => {
    const cliente = crearClienteRemapeoEspia()
    const wrapper = montarPanel(
      crearRemapeoTecnicoPrueba({ remapeo: operacionConCandidato() }),
      cliente,
    )

    await wrapper.get('[data-testid="persistencia-persistente"]').setValue('PERSISTENTE')
    await wrapper.get('[data-testid="btn-confirmar-remapeo"]').trigger('click')

    expect(cliente.confirmarRemapeo).toHaveBeenCalledWith('rem-1', 'PERSISTENTE')
  })

  it('muestra la persona objetivo tomada de la misma allowlist', () => {
    const wrapper = montarPanel(
      crearRemapeoTecnicoPrueba({ remapeo: operacionConCandidato() }),
      crearClienteRemapeoEspia(),
    )

    expect(wrapper.get('[data-testid="persona-remapeo"]').text()).toContain('Nombre1')
    expect(wrapper.get('[data-testid="fingerprint-candidato"]').text()).toContain('fp-nuevo')
  })

  it('cancela la operación activa por su identificador', async () => {
    const cliente = crearClienteRemapeoEspia()
    const wrapper = montarPanel(
      crearRemapeoTecnicoPrueba({ remapeo: operacionConCandidato() }),
      cliente,
    )

    await wrapper.get('[data-testid="btn-cancelar-remapeo"]').trigger('click')

    expect(cliente.cancelarRemapeo).toHaveBeenCalledWith('rem-1')
  })

  it('respeta las capacidades del backend en lugar de decidir por su cuenta', () => {
    // Las capacidades llegan recortadas del mismo evaluador que usa Moderación: si el
    // backend bloquea iniciar, el puesto técnico también lo bloquea y explica el motivo.
    const wrapper = montarPanel(
      crearRemapeoTecnicoPrueba({
        capacidades: {
          iniciar_remapeo: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
          confirmar_remapeo: { habilitada: false, motivos: ['REMAPEO_NO_COINCIDE'] },
          cancelar_remapeo: { habilitada: false, motivos: ['REMAPEO_NO_COINCIDE'] },
        },
      }),
      crearClienteRemapeoEspia(),
    )

    const boton = wrapper.get('[data-testid="btn-iniciar-remapeo"]')
    expect((boton.element as HTMLButtonElement).disabled).toBe(true)
    expect(wrapper.get('[data-testid="motivos-iniciar-remapeo"]').text()).not.toHaveLength(0)
  })

  it('exige conexión confirmada del único stream del puesto', () => {
    // Con una sola suscripción, «conectado» ya no puede significar «el canal técnico está
    // vivo pero el de Moderación no»: es el mismo canal para todo.
    const wrapper = montarPanel(crearRemapeoTecnicoPrueba(), crearClienteRemapeoEspia(), false)

    expect(wrapper.find('[data-testid="remapeo-sin-conexion"]').exists()).toBe(true)
  })

  it('no rompe antes del primer snapshot', () => {
    const wrapper = montarPanel(null, crearClienteRemapeoEspia())

    expect(wrapper.get('[data-testid="gestion-remapeo"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-testid="selector-banca-remapeo"] option')).toHaveLength(1)
  })
})
