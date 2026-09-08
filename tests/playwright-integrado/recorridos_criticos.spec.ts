import { expect, test, type Page } from '@playwright/test'
import { resolve } from 'node:path'

import {
  ProcesoStackIntegrado,
  URL_STACK,
  leerAuditoria,
  listarCsvAuditoria,
  puertoOcupado,
  pulsar,
  pulsarSecuencia,
  tamanosArchivos,
} from './infraestructura'

const RUTA_ORDEN_DIA = resolve(__dirname, 'fixtures/orden-del-dia.csv')

/**
 * Nombre completo de quien ocupa la banca 1 en la plantilla del padrón.
 *
 * El recorrido corre contra el stack real, que arranca desde
 * `config/concejales.example.csv`. Desde WP-084 esa plantilla trae datos
 * ficticios: antes reproducía el padrón real de la institución de origen. Se
 * declara como constante para que un cambio futuro de la plantilla se corrija en
 * un solo lugar en vez de en tres aserciones sueltas.
 */
const NOMBRE_BANCA_1 = 'Amparo Bermudez'

interface EstadoBasico {
  estado_global: string
  revision: number
  votacion?: {
    estado_recepcion: string
    resultado: string | null
    cantidad_votos_recibidos: number
    votos_individuales: unknown
    conteos: unknown
  } | null
  /**
   * Proyección pública de hechos (WP-046).
   *
   * WP-050 dejó de dibujarla en la Pantalla del Recinto, así que este recorrido
   * dejó de comprobarla mirando el DOM y pasó a comprobarla donde realmente
   * vive: el DTO que entrega el backend. Es, además, la evidencia de que el
   * contrato de `eventos_publicos` no cambió.
   */
  eventos_publicos?: { codigo_evento: string; categoria: string; texto: string }[]
}

/** Textos de la proyección pública, en el orden en que los emitió el backend. */
async function textosEventosPublicos(recinto: Page): Promise<string[]> {
  const estado = await obtenerEstado(recinto, 'recinto')
  return (estado.eventos_publicos ?? []).map((evento) => evento.texto)
}

async function obtenerEstado(page: Page, destino: 'moderacion' | 'recinto'): Promise<EstadoBasico> {
  const respuesta = await page.request.get(`${URL_STACK}/api/v1/estado/${destino}`)
  expect(respuesta.ok()).toBe(true)
  return (await respuesta.json()) as EstadoBasico
}

async function abrirVotacion(
  moderacion: Page,
  numero: number,
  tema: string,
  confirmarPalabra = true,
): Promise<void> {
  await expect(moderacion.getByTestId('formulario-votacion')).toBeVisible()
  await moderacion.getByTestId('input-numero-votacion').fill(String(numero))
  await moderacion.getByTestId('select-tipo-votacion').selectOption({ label: 'Otro' })
  await moderacion.getByTestId('input-tema-votacion').fill(tema)
  await moderacion.getByTestId('radio-mayoria-simple').check()
  await moderacion.getByTestId('btn-abrir-votacion').click()

  if (confirmarPalabra) {
    await expect(moderacion.getByTestId('dialogo-confirmacion-apertura')).toBeVisible()
    await moderacion.getByTestId('btn-confirmar-apertura').click()
  }
  await expect(moderacion.getByTestId('estado-votacion')).toHaveText('EN_CURSO')
}

async function finalizarManualmente(moderacion: Page, motivo: string): Promise<void> {
  await moderacion.getByTestId('input-motivo-finalizacion').fill(motivo)
  await moderacion.getByTestId('btn-finalizar-votacion').click()
  await expect(moderacion.getByTestId('estado-votacion')).toHaveText('INCONCLUSA')
}

test.describe.serial('WP-027 · recorridos críticos sobre el stack real', () => {
  const stack = new ProcesoStackIntegrado()

  test.beforeAll(async () => {
    await stack.iniciar()
  })

  test.afterAll(async () => {
    await stack.detener()
    expect(await puertoOcupado()).toBe(false)
  })

  test.afterEach(async ({}, informacion) => {
    if (informacion.status !== informacion.expectedStatus) {
      await informacion.attach('stdout-stderr-stack.txt', {
        body: stack.obtenerSalida(),
        contentType: 'text/plain',
      })
    }
  })

  test('integra preparación, sesión, palabra, votaciones, auditoría y reinicio', async ({
    browser,
  }) => {
    const contexto = await browser.newContext()
    const moderacion = await contexto.newPage()
    const recinto = await contexto.newPage()
    const csvPrevios = new Set(await listarCsvAuditoria())
    let csvPrimeraPreparacion: string[] = []

    try {
      await test.step('A · inicia limpio y prepara el recinto desde Moderación', async () => {
        await Promise.all([
          moderacion.goto(`${URL_STACK}/moderacion/`),
          recinto.goto(`${URL_STACK}/recinto/`),
        ])
        await expect(moderacion.getByTestId('vista-sin-preparar')).toBeVisible()
        await expect(recinto.getByTestId('estado-sin-preparar')).toBeVisible()
        expect((await obtenerEstado(moderacion, 'moderacion')).estado_global).toBe('SIN_PREPARAR')

        await moderacion.getByTestId('btn-preparar-sala').click()
        await expect(moderacion.getByTestId('vista-preparando')).toBeVisible()
        await expect(recinto.getByTestId('cabecera-sesion')).toHaveText('Recinto en preparación')
        await expect(moderacion.getByTestId('banca-concejal')).toHaveCount(12)
        await expect(recinto.getByTestId('banca-publica')).toHaveCount(12)

        csvPrimeraPreparacion = (await listarCsvAuditoria()).filter((ruta) => !csvPrevios.has(ruta))
        expect(csvPrimeraPreparacion).toHaveLength(3)

        // El indicador dura 0,6 s: el comando y la observación se coordinan en
        // paralelo, sin modificar el timer funcional ni dormir artificialmente.
        await Promise.all([
          pulsar('1-8'),
          // WP-045 unifica la señal: ambas superficies pintan el test como
          // estado principal, con el mismo atributo y sin etiqueta textual.
          expect(moderacion.locator('[data-banca="1"]')).toHaveAttribute(
            'data-estado-banca',
            'TEST',
          ),
          expect(recinto.locator('[data-banca="1"]')).toHaveAttribute('data-estado-banca', 'TEST'),
        ])

        await pulsarSecuencia(['1-9', '2-9', '3-9', '4-9', '5-9', '6-9', '7-9'])
        // WP-036: el quórum de Moderación es un dato único de la cabecera compacta.
        await expect(moderacion.getByTestId('cabecera-quorum')).toContainText('Quórum 7/12')
        // WP-054: el indicador público muestra `presentes/total` del padrón (12 bancas).
        await expect(recinto.getByTestId('cantidad-presentes')).toHaveText('7/12')
        // Con 7 presentes sobre los 7 exigidos por `config/system.toml`, WP-058
        // exige la redacción de límite en vez de la genérica.
        await expect(recinto.getByTestId('estado-quorum')).toContainText('Quórum límite')

        await moderacion.getByTestId('input-numero-sesion').fill('27')
        await moderacion.getByTestId('input-presidencia').fill('Presidencia E2E Ficticia')
        await moderacion.getByTestId('input-secretaria').fill('Secretaría E2E Ficticia')
        await moderacion.getByTestId('btn-guardar-preparacion').click()
        await expect(moderacion.getByTestId('btn-abrir-sesion')).toBeEnabled()

        const preparacion = await obtenerEstado(moderacion, 'moderacion')
        expect(preparacion.estado_global).toBe('PREPARANDO')
        await moderacion.getByTestId('btn-abrir-sesion').click()
        await expect(moderacion.getByTestId('vista-sesion-abierta')).toBeVisible()
        await expect(recinto.getByTestId('cabecera-sesion')).toContainText('27')
        // WP-050: la franja dejó de dibujarse; la proyección sigue existiendo.
        await expect(recinto.getByTestId('panel-eventos-publicos')).toHaveCount(0)
        expect(await textosEventosPublicos(recinto)).toContain('Sesión abierta')
        expect((await obtenerEstado(moderacion, 'moderacion')).estado_global).toBe('SESION_ABIERTA')
      })

      await test.step('B · palabra y advertencia CA-062 conservan el estado autoritativo', async () => {
        await pulsar('1-7')
        await expect(moderacion.getByTestId('cola-palabra')).toContainText('Banca 1')
        await expect(recinto.getByTestId('cola-palabra')).toContainText(NOMBRE_BANCA_1)
        await moderacion.getByTestId('btn-otorgar-palabra').click()
        // WP-044: Moderación ya no repite al orador como texto; la señal vive en su banca.
        await expect(moderacion.locator('[data-banca="1"]')).toHaveAttribute(
          'data-estado-banca',
          'PALABRA',
        )
        await expect(recinto.locator('[data-banca="1"]')).toHaveAttribute(
          'data-estado-banca',
          'PALABRA',
        )
        await expect(recinto.getByTestId('panel-palabra')).not.toContainText(NOMBRE_BANCA_1)

        await moderacion.getByTestId('input-numero-votacion').fill('1')
        await moderacion.getByTestId('select-tipo-votacion').selectOption({ label: 'Otro' })
        await moderacion.getByTestId('input-tema-votacion').fill('Votación con palabra coexistente')
        await moderacion.getByTestId('btn-abrir-votacion').click()
        await expect(moderacion.getByTestId('dialogo-confirmacion-apertura')).toBeVisible()
        await moderacion.getByTestId('btn-cancelar-apertura').click()
        await expect(moderacion.getByTestId('dialogo-confirmacion-apertura')).toHaveCount(0)
        await expect(moderacion.getByTestId('formulario-votacion')).toBeVisible()
        // WP-044: Moderación ya no repite al orador como texto; la señal vive en su banca.
        await expect(moderacion.locator('[data-banca="1"]')).toHaveAttribute(
          'data-estado-banca',
          'PALABRA',
        )

        await moderacion.getByTestId('btn-abrir-votacion').click()
        await moderacion.getByTestId('btn-confirmar-apertura').click()
        await expect(moderacion.getByTestId('estado-votacion')).toHaveText('EN_CURSO')
        await expect(recinto.getByTestId('estado-votacion')).toHaveText('En curso')
        expect(await textosEventosPublicos(recinto)).toContain('Votación abierta')
        await expect(recinto.getByTestId('countdown-votacion')).toBeVisible()
        await expect(recinto.locator('[data-banca="1"]')).toHaveAttribute(
          'data-estado-banca',
          'PALABRA',
        )
        await expect(recinto.getByTestId('panel-palabra')).not.toContainText(NOMBRE_BANCA_1)
      })

      await test.step('C · mantiene secreto, revela y autocierra una votación real', async () => {
        await pulsarSecuencia(['1-1', '2-3', '3-2'])
        await expect(moderacion.getByTestId('cantidad-votos-recibidos')).toHaveText('3')
        await expect(moderacion.getByTestId('votos-ocultos')).toBeVisible()
        await expect(recinto.getByTestId('conteos-votacion')).toHaveCount(0)
        await expect(recinto.locator('[data-estado-banca^="RESULTADO_"]')).toHaveCount(0)

        // WP-045: las tres bancas que ya votaron muestran participación en las
        // dos superficies, con la misma etiqueta y sin ningún sentido.
        for (const pagina of [moderacion, recinto]) {
          for (const banca of [1, 2, 3]) {
            await expect(pagina.locator(`[data-banca="${banca}"]`)).toHaveAttribute(
              'data-estado-banca',
              'VOTO_EMITIDO',
            )
            await expect(
              pagina.locator(`[data-banca="${banca}"] [data-testid="etiqueta-banca"]`),
            ).toHaveText('Voto emitido')
          }
          await expect(pagina.locator('[data-banca="4"]')).not.toHaveAttribute(
            'data-estado-banca',
            'VOTO_EMITIDO',
          )
        }

        const publicoEnCurso = await obtenerEstado(recinto, 'recinto')
        expect(publicoEnCurso.votacion?.estado_recepcion).toBe('EN_CURSO')
        expect(publicoEnCurso.votacion?.votos_individuales).toBeNull()
        expect(publicoEnCurso.votacion?.conteos).toBeNull()
        expect(publicoEnCurso.votacion?.bancas_voto_emitido).toEqual([1, 2, 3])
        expect(JSON.stringify(publicoEnCurso)).not.toContain('POSITIVO')
        expect(JSON.stringify(publicoEnCurso)).not.toContain('10000008')
        // El secreto sigue garantizado en la proyección, no por ocultamiento
        // visual: ningún voto individual aparece entre los hechos públicos.
        const codigosEnCurso = (
          (await obtenerEstado(recinto, 'recinto')).eventos_publicos ?? []
        ).map((evento) => evento.codigo_evento)
        expect(codigosEnCurso).not.toContain('VOTO_ORDINARIO_REGISTRADO')

        // WP-037 reserva Q1 para conducción: aun cuando la proyección privada tenga el
        // detalle nominal, la interfaz compacta sólo muestra el progreso agregado.
        await expect(moderacion.getByTestId('votos-individuales')).toHaveCount(0)
        await pulsarSecuencia(['4-1', '5-1', '6-1', '7-1'])
        await expect(moderacion.getByTestId('estado-votacion')).toHaveText('APROBADA')
        await expect(recinto.getByTestId('estado-votacion')).toHaveText('Aprobada')
        await expect(recinto.getByTestId('conteos-votacion')).toContainText('Positivos')
        // Tras el cierre ambas superficies muestran el mismo resultado por banca.
        for (const pagina of [moderacion, recinto]) {
          await expect(
            pagina.locator('[data-banca="1"] [data-testid="etiqueta-banca"]'),
          ).toHaveText('Positivo')
          await expect(
            pagina.locator('[data-banca="2"] [data-testid="etiqueta-banca"]'),
          ).toHaveText('Negativo')
          await expect(
            pagina.locator('[data-banca="3"] [data-testid="etiqueta-banca"]'),
          ).toHaveText('Abstención')
        }
        await expect(recinto.getByTestId('estado-votacion')).toHaveText('Sin votación', {
          timeout: 9_000,
        })
      })

      await test.step('D · empate simple persiste y el desempate queda separado', async () => {
        await pulsar('8-9')
        await expect(recinto.getByTestId('cantidad-presentes')).toHaveText('8/12')
        await abrirVotacion(moderacion, 2, 'Empate simple real')
        await pulsarSecuencia(['1-1', '2-1', '3-1', '4-1', '5-3', '6-3', '7-3', '8-3'])

        await expect(moderacion.getByTestId('estado-votacion')).toHaveText('EMPATADA')
        await expect(recinto.getByTestId('espera-desempate')).toBeVisible()
        await expect(moderacion.getByTestId('formulario-votacion')).toHaveCount(0)
        const conteosAntes = await moderacion.getByTestId('conteos-votacion').textContent()

        // EMPATADA no usa la expiración pública normal de seis segundos. Esta
        // espera real atraviesa deliberadamente esa frontera y recién después
        // vuelve a observar la misma votación, sus conteos y el bloqueo de una
        // apertura nueva. No se usa fake clock porque aquí se integra el timer
        // real comunicado por backend, api-client y Recinto.
        await recinto.waitForTimeout(6_500)
        await expect(recinto.getByTestId('espera-desempate')).toBeVisible()
        await expect(recinto.getByTestId('estado-votacion')).toHaveText('Empatada')
        await expect(recinto.getByTestId('tema-votacion')).toHaveText('Empate simple real')
        await expect(recinto.getByTestId('conteos-votacion')).toBeVisible()
        await expect(moderacion.getByTestId('estado-votacion')).toHaveText('EMPATADA')
        expect(await moderacion.getByTestId('conteos-votacion').textContent()).toBe(conteosAntes)
        await expect(moderacion.getByTestId('formulario-votacion')).toHaveCount(0)

        await moderacion.getByTestId('btn-desempate-positivo').click()
        await expect(moderacion.getByTestId('estado-votacion')).toHaveText('APROBADA')
        await expect(recinto.getByTestId('voto-presidencial')).toContainText(
          'Presidencia E2E Ficticia',
        )
        expect(await moderacion.getByTestId('conteos-votacion').textContent()).toBe(conteosAntes)
        await expect(recinto.getByTestId('estado-votacion')).toHaveText('Sin votación', {
          timeout: 9_000,
        })
      })

      await test.step('E · pérdida de quórum cierra INCONCLUSA y no se revierte', async () => {
        await abrirVotacion(moderacion, 3, 'Pérdida de quórum')
        await pulsar('1-1')
        await pulsarSecuencia(['2-9', '3-9'])
        await expect(moderacion.getByTestId('estado-votacion')).toHaveText('INCONCLUSA')
        await expect(recinto.getByTestId('estado-votacion')).toHaveText('Inconclusa')
        await expect(recinto.locator('[data-banca="1"] [data-testid="etiqueta-banca"]')).toHaveText(
          'Positivo',
        )
        await expect(recinto.locator('[data-banca="4"]')).not.toHaveAttribute(
          'data-estado-banca',
          /RESULTADO_/,
        )

        await pulsarSecuencia(['2-9', '3-9'])
        await expect(recinto.getByTestId('cantidad-presentes')).toHaveText('8/12')
        await expect(moderacion.getByTestId('estado-votacion')).toHaveText('INCONCLUSA')
        await expect(moderacion.getByTestId('formulario-votacion')).toBeVisible()
      })

      await test.step('F · finalización manual conserva el voto parcial', async () => {
        await abrirVotacion(moderacion, 4, 'Finalización manual')
        await pulsar('1-3')
        await finalizarManualmente(moderacion, 'Cierre manual E2E con votos faltantes')
        await expect(moderacion.getByTestId('votos-individuales')).toHaveCount(0)
        await expect(moderacion.getByTestId('conteos-votacion')).toContainText('Negativos')
        await expect(moderacion.getByTestId('conteos-votacion')).toContainText('1')
        await expect(recinto.locator('[data-banca="1"] [data-testid="etiqueta-banca"]')).toHaveText(
          'Negativo',
        )
        // WP-045: el resultado final gana a la palabra, que sobrevive como halo
        // sin agregar una segunda etiqueta. La señal sigue viviendo en la banca.
        await expect(moderacion.locator('[data-banca="1"]')).toHaveAttribute(
          'data-estado-banca',
          'RESULTADO_NEGATIVO',
        )
        await expect(moderacion.locator('[data-banca="1"]')).toHaveAttribute(
          'data-halo-palabra',
          'true',
        )
        await expect(
          moderacion.locator('[data-banca="1"] [data-testid="etiqueta-banca"]'),
        ).toHaveCount(1)
      })

      await test.step('G · Orden del Día deja una votación real EN_CURSO para el cierre', async () => {
        await moderacion.getByTestId('input-archivo-orden-dia').setInputFiles(RUTA_ORDEN_DIA)
        await moderacion.getByTestId('btn-cargar-orden-dia').click()
        await expect(moderacion.getByTestId('punto-orden-dia')).toContainText(
          'Tema canónico desde Orden del Día',
        )
        await moderacion.getByTestId('punto-orden-dia').click()
        await expect(moderacion.getByTestId('input-numero-votacion')).toHaveValue('70')
        await expect(moderacion.getByTestId('input-tema-votacion')).toHaveValue(
          'Tema canónico desde Orden del Día',
        )
        await moderacion.getByTestId('input-tema-votacion').fill('Tema editado por Moderación')
        await moderacion.getByTestId('btn-abrir-votacion').click()
        await moderacion.getByTestId('btn-confirmar-apertura').click()
        await expect(recinto.getByTestId('tema-votacion')).toHaveText('Tema editado por Moderación')
        await pulsar('1-2')
        await expect(moderacion.getByTestId('estado-votacion')).toHaveText('EN_CURSO')
        await expect(moderacion.getByTestId('cantidad-votos-recibidos')).toHaveText('1')
      })

      await test.step('H · CA-063 cancela y CA-042 resuelve la votación antes del cierre', async () => {
        await moderacion.getByTestId('btn-cerrar-sesion').click()
        await expect(moderacion.getByTestId('dialogo-confirmacion-cierre')).toBeVisible()
        await moderacion.getByTestId('btn-cancelar-cierre').click()
        await expect(moderacion.getByTestId('vista-sesion-abierta')).toBeVisible()
        // WP-045: la banca 1 ya votó en esta votación EN_CURSO, así que su
        // estado principal es la participación sin sentido; la palabra sigue
        // señalizada como halo, sin una segunda etiqueta.
        await expect(moderacion.locator('[data-banca="1"]')).toHaveAttribute(
          'data-estado-banca',
          'VOTO_EMITIDO',
        )
        await expect(moderacion.locator('[data-banca="1"]')).toHaveAttribute(
          'data-halo-palabra',
          'true',
        )
        const estadoTrasCancelar = await obtenerEstado(moderacion, 'moderacion')
        expect(estadoTrasCancelar.estado_global).toBe('SESION_ABIERTA')
        expect(estadoTrasCancelar.votacion?.estado_recepcion).toBe('EN_CURSO')
        expect(estadoTrasCancelar.votacion?.cantidad_votos_recibidos).toBe(1)
        await expect(recinto.getByTestId('estado-votacion')).toHaveText('En curso')

        await moderacion.getByTestId('btn-cerrar-sesion').click()
        await moderacion.getByTestId('btn-confirmar-cierre').click()
        await expect(moderacion.getByTestId('vista-sin-preparar')).toBeVisible()
        await expect(recinto.getByTestId('estado-sin-preparar')).toBeVisible()
        expect((await obtenerEstado(moderacion, 'recinto')).estado_global).toBe('SIN_PREPARAR')

        // La UI ya limpió la votación al adoptar SIN_PREPARAR. El L1 durable
        // permite demostrar la transición intermedia exacta exigida por CA-042:
        // la votación 70 conservó su voto parcial, quedó INCONCLUSA por
        // CIERRE_SESION y ese hecho fue fsync antes de SESION_CERRADA.
        const rutaL1 = csvPrimeraPreparacion.find((ruta) => ruta.endsWith('-L1.csv'))
        if (rutaL1 === undefined) throw new Error('La preparación no creó su archivo L1.')
        const filasL1 = (await leerAuditoria([rutaL1])).split(/\r?\n/)
        const indiceInconclusa = filasL1.findLastIndex(
          (fila) =>
            fila.includes(';VOTACION_FINALIZADA_INCONCLUSA;') &&
            fila.includes('numero_votacion=70') &&
            fila.includes('causa=CIERRE_SESION') &&
            fila.includes('votos_conservados=1') &&
            fila.includes('resultado_nuevo=INCONCLUSA'),
        )
        const indiceCierre = filasL1.findLastIndex((fila) => fila.includes(';SESION_CERRADA;'))
        expect(indiceInconclusa).toBeGreaterThan(-1)
        expect(indiceCierre).toBeGreaterThan(indiceInconclusa)
      })

      await test.step('I · auditoría no se reutiliza y un restart adopta baseline revisión 0', async () => {
        const textoAuditoria = await leerAuditoria(csvPrimeraPreparacion)
        for (const codigo of [
          'PREPARACION_INICIADA',
          'SESION_ABIERTA',
          'PEDIDO_PALABRA_REGISTRADO',
          'VOTACION_ABIERTA',
          'VOTO_ORDINARIO_REGISTRADO',
          'VOTACION_RESULTADO_FINAL',
          'SESION_CERRADA',
        ]) {
          expect(textoAuditoria).toContain(codigo)
        }

        const tamanosCerrados = await tamanosArchivos(csvPrimeraPreparacion)
        await moderacion.getByTestId('btn-preparar-sala').click()
        await expect(moderacion.getByTestId('vista-preparando')).toBeVisible()
        const csvSegundaPreparacion = (await listarCsvAuditoria()).filter(
          (ruta) => !csvPrevios.has(ruta) && !csvPrimeraPreparacion.includes(ruta),
        )
        expect(csvSegundaPreparacion).toHaveLength(3)
        expect(await tamanosArchivos(csvPrimeraPreparacion)).toEqual(tamanosCerrados)

        await stack.detener()
        expect(await puertoOcupado()).toBe(false)
        await stack.iniciar()

        const estadoReiniciado = await obtenerEstado(moderacion, 'moderacion')
        expect(estadoReiniciado.estado_global).toBe('SIN_PREPARAR')
        expect(estadoReiniciado.revision).toBe(0)
        await Promise.all([moderacion.reload(), recinto.reload()])
        await expect(moderacion.getByTestId('vista-sin-preparar')).toBeVisible()
        await expect(recinto.getByTestId('estado-sin-preparar')).toBeVisible()
      })
    } finally {
      await contexto.close()
    }
  })
})
