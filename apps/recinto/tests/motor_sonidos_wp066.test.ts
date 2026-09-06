/**
 * Motor de reproducción de audio del Recinto (WP-066).
 *
 * El motor es la única pieza que toca `Audio`, así que su fábrica es inyectable y estas
 * pruebas corren sin navegador: cada «reproducción» es un objeto que registra qué URL
 * recibió, con qué volumen y cuántas veces se llamó `play()`.
 *
 * Lo que se demuestra acá es lo que HUMAN_GATE decidió y el WP exige: volumen individual,
 * superposición sin interrupciones, precarga, y fallos de reproducción que no rompen nada
 * ni generan bucles.
 */

import { describe, expect, it } from 'vitest'
import { crearMotorSonidos, type InstanciaAudioRecinto } from '@sis-leg/frontend-shared'
import { crearSonidosRecintoPrueba } from './datos_prueba'

/** Instancia de audio de prueba: recuerda todo lo que el motor le hizo. */
class AudioEspia implements InstanciaAudioRecinto {
  volume = 1
  preload = 'none'
  reproducciones = 0
  cargas = 0
  terminada = false

  constructor(
    readonly url: string,
    private readonly resultado: () => Promise<void> | void = () => Promise.resolve(),
  ) {}

  play(): Promise<void> | void {
    this.reproducciones += 1
    return this.resultado()
  }

  load(): void {
    this.cargas += 1
  }
}

/** Fábrica que conserva cada instancia creada, en orden. */
function crearFabricaEspia(resultado?: () => Promise<void> | void) {
  const creadas: AudioEspia[] = []
  return {
    creadas,
    crearAudio: (url: string) => {
      const audio = new AudioEspia(url, resultado)
      creadas.push(audio)
      return audio
    },
  }
}

/** URL sin `baseURL` de Nuxt: las pruebas no levantan la aplicación completa. */
const resolverUrl = (ruta: string) => `/recinto/${ruta}`

describe('Configuración y precarga', () => {
  it('precarga un archivo por evento sin reproducir ninguno', () => {
    const fabrica = crearFabricaEspia()
    const motor = crearMotorSonidos({ crearAudio: fabrica.crearAudio, resolverUrl })

    motor.configurar(crearSonidosRecintoPrueba())

    expect(fabrica.creadas).toHaveLength(15)
    expect(fabrica.creadas.every((audio) => audio.preload === 'auto')).toBe(true)
    expect(fabrica.creadas.every((audio) => audio.cargas === 1)).toBe(true)
    // Precargar no es reproducir: nadie escuchó nada todavía.
    expect(fabrica.creadas.every((audio) => audio.reproducciones === 0)).toBe(true)
  })

  it('no vuelve a precargar cuando la configuración no cambió', () => {
    const fabrica = crearFabricaEspia()
    const motor = crearMotorSonidos({ crearAudio: fabrica.crearAudio, resolverUrl })

    motor.configurar(crearSonidosRecintoPrueba())
    motor.configurar(crearSonidosRecintoPrueba())
    motor.configurar(crearSonidosRecintoPrueba())

    expect(fabrica.creadas).toHaveLength(15)
  })

  it('precarga los archivos nuevos cuando cambia la configuración', () => {
    const fabrica = crearFabricaEspia()
    const motor = crearMotorSonidos({ crearAudio: fabrica.crearAudio, resolverUrl })

    motor.configurar(
      crearSonidosRecintoPrueba({
        sonidos: [
          { evento: 'sesion_abierta', ruta: 'assets/sonidos/sesion-abierta.wav', volumen: 90 },
        ],
      }),
    )
    motor.configurar(
      crearSonidosRecintoPrueba({
        sonidos: [
          {
            evento: 'sesion_abierta',
            ruta: 'assets/sonidos/alternativa-campana.wav',
            volumen: 90,
          },
        ],
      }),
    )

    expect(fabrica.creadas.map((audio) => audio.url)).toEqual([
      '/recinto/assets/sonidos/sesion-abierta.wav',
      '/recinto/assets/sonidos/alternativa-campana.wav',
    ])
  })

  it('queda en silencio si el backend informa la configuración como no disponible', () => {
    const fabrica = crearFabricaEspia()
    const diagnosticos: string[] = []
    const motor = crearMotorSonidos({
      crearAudio: fabrica.crearAudio,
      resolverUrl,
      registrarDiagnostico: (mensaje) => diagnosticos.push(mensaje),
    })

    motor.configurar(
      crearSonidosRecintoPrueba({
        disponible: false,
        motivo: 'SONIDOS_RECINTO_INVALIDOS',
        sonidos: [],
      }),
    )
    motor.reproducir('sesion_abierta')
    motor.reproducir('votacion_abierta')
    motor.reproducir('concejal_presente')

    expect(fabrica.creadas).toHaveLength(0)
    // El problema se informa una sola vez por el canal técnico —no una por evento— y sin
    // agregar ninguna superficie visible.
    expect(diagnosticos).toHaveLength(1)
  })
})

describe('Reproducción', () => {
  it('aplica a cada evento su propio volumen configurado', () => {
    const fabrica = crearFabricaEspia()
    const motor = crearMotorSonidos({ crearAudio: fabrica.crearAudio, resolverUrl })
    const sonidos = crearSonidosRecintoPrueba({
      sonidos: [
        { evento: 'sesion_abierta', ruta: 'assets/sonidos/sesion-abierta.wav', volumen: 90 },
        { evento: 'concejal_ausente', ruta: 'assets/sonidos/concejal-ausente.wav', volumen: 50 },
      ],
    })

    motor.configurar(sonidos)
    const precargas = fabrica.creadas.length
    motor.reproducir('sesion_abierta')
    motor.reproducir('concejal_ausente')

    const [apertura, ausencia] = fabrica.creadas.slice(precargas)
    expect(apertura?.url).toBe('/recinto/assets/sonidos/sesion-abierta.wav')
    expect(apertura?.volume).toBeCloseTo(0.9)
    expect(ausencia?.url).toBe('/recinto/assets/sonidos/concejal-ausente.wav')
    expect(ausencia?.volume).toBeCloseTo(0.5)
  })

  it('respeta el volumen 0 como silencio configurado y no como error', () => {
    const fabrica = crearFabricaEspia()
    const motor = crearMotorSonidos({ crearAudio: fabrica.crearAudio, resolverUrl })

    motor.configurar(
      crearSonidosRecintoPrueba({
        sonidos: [
          { evento: 'sesion_abierta', ruta: 'assets/sonidos/sesion-abierta.wav', volumen: 0 },
        ],
      }),
    )
    const precargas = fabrica.creadas.length
    motor.reproducir('sesion_abierta')

    expect(fabrica.creadas).toHaveLength(precargas + 1)
    expect(fabrica.creadas[precargas]?.volume).toBe(0)
    expect(fabrica.creadas[precargas]?.reproducciones).toBe(1)
  })

  it('crea una instancia nueva por evento, de modo que dos sonidos se superpongan', () => {
    // La prueba de la superposición es exactamente ésta: dos instancias distintas,
    // reproducidas ambas, y ninguna llamada que detenga o reinicie a la anterior. Un
    // elemento reutilizado habría cortado el primer sonido al empezar el segundo.
    const fabrica = crearFabricaEspia()
    const motor = crearMotorSonidos({ crearAudio: fabrica.crearAudio, resolverUrl })

    motor.configurar(crearSonidosRecintoPrueba())
    const precargas = fabrica.creadas.length
    motor.reproducir('votacion_abierta')
    motor.reproducir('concejal_presente')

    const reproducidas = fabrica.creadas.slice(precargas)
    expect(reproducidas).toHaveLength(2)
    expect(reproducidas[0]).not.toBe(reproducidas[1])
    expect(reproducidas.every((audio) => audio.reproducciones === 1)).toBe(true)
  })

  it('permite que el mismo evento suene dos veces sin cortarse', () => {
    const fabrica = crearFabricaEspia()
    const motor = crearMotorSonidos({ crearAudio: fabrica.crearAudio, resolverUrl })

    motor.configurar(crearSonidosRecintoPrueba())
    const precargas = fabrica.creadas.length
    motor.reproducir('concejal_ausente')
    motor.reproducir('concejal_ausente')

    const reproducidas = fabrica.creadas.slice(precargas)
    expect(reproducidas).toHaveLength(2)
    expect(reproducidas[0]).not.toBe(reproducidas[1])
  })
})

describe('Errores y ausencia de entorno de audio', () => {
  it('no propaga el rechazo de autoplay y lo informa una sola vez', async () => {
    const rechazos: unknown[] = []
    const diagnosticos: string[] = []
    const fabrica = crearFabricaEspia(() => Promise.reject(new Error('NotAllowedError')))
    const motor = crearMotorSonidos({
      crearAudio: fabrica.crearAudio,
      resolverUrl,
      registrarDiagnostico: (mensaje, detalle) => {
        diagnosticos.push(mensaje)
        rechazos.push(detalle)
      },
    })

    motor.configurar(crearSonidosRecintoPrueba())
    expect(() => {
      motor.reproducir('sesion_abierta')
      motor.reproducir('sesion_abierta')
      motor.reproducir('sesion_abierta')
    }).not.toThrow()

    // Las promesas rechazadas se resuelven en el microtask siguiente.
    await Promise.resolve()
    await Promise.resolve()

    expect(diagnosticos).toHaveLength(1)
    expect(rechazos[0]).toBeInstanceOf(Error)
  })

  it('sobrevive a una fábrica que lanza al construir el audio', () => {
    const diagnosticos: string[] = []
    const motor = crearMotorSonidos({
      crearAudio: () => {
        throw new Error('archivo inaccesible')
      },
      resolverUrl,
      registrarDiagnostico: (mensaje) => diagnosticos.push(mensaje),
    })

    expect(() => {
      motor.configurar(crearSonidosRecintoPrueba())
      motor.reproducir('votacion_cerrada')
    }).not.toThrow()
    expect(diagnosticos.length).toBeGreaterThan(0)
  })

  it('no hace nada cuando el entorno no puede reproducir audio', () => {
    // Es el caso del prerender de Nuxt y de las pruebas de componentes: sin `Audio` el
    // motor simplemente calla, y la pantalla se monta igual.
    const motor = crearMotorSonidos({ crearAudio: () => null, resolverUrl })

    expect(() => {
      motor.configurar(crearSonidosRecintoPrueba())
      motor.reproducir('sesion_cerrada')
      motor.liberar()
    }).not.toThrow()
  })

  it('informa una única vez un evento sin sonido configurado', () => {
    const diagnosticos: string[] = []
    const fabrica = crearFabricaEspia()
    const motor = crearMotorSonidos({
      crearAudio: fabrica.crearAudio,
      resolverUrl,
      registrarDiagnostico: (mensaje) => diagnosticos.push(mensaje),
    })

    motor.configurar(
      crearSonidosRecintoPrueba({
        sonidos: [
          { evento: 'sesion_abierta', ruta: 'assets/sonidos/sesion-abierta.wav', volumen: 90 },
        ],
      }),
    )
    motor.reproducir('votacion_abierta')
    motor.reproducir('votacion_abierta')

    expect(diagnosticos).toHaveLength(1)
  })
})
