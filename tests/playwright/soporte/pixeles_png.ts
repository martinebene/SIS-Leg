/**
 * Lector mínimo de PNG para inspeccionar píxeles reales de una captura (WP-099).
 *
 * ## Por qué hace falta
 *
 * El Zócalo se usa como Browser Source de OBS con un filtro de croma. Lo que decide si ese
 * filtro va a funcionar no es una declaración CSS sino el color que el navegador termina
 * pintando: un degradado, una transparencia o una sombra producen píxeles intermedios que
 * el filtro recorta mal y se ven al aire como un halo alrededor del zócalo.
 *
 * Comprobar `getComputedStyle` no alcanza para demostrarlo, porque describe la intención y
 * no el resultado compuesto. Playwright sí entrega la captura real, pero como PNG. Este
 * módulo la decodifica para poder afirmar sobre píxeles concretos.
 *
 * ## Alcance deliberadamente mínimo
 *
 * Sólo soporta lo que produce Chromium al capturar una página: profundidad de 8 bits, sin
 * entrelazado, en color verdadero con o sin canal alfa. Cualquier otra combinación produce
 * un error explícito en lugar de devolver píxeles equivocados en silencio. No se agrega una
 * dependencia nueva al proyecto: la descompresión la resuelve `node:zlib`, que ya viene con
 * el runtime.
 */

import { inflateSync } from 'node:zlib'

/** Firma obligatoria con la que empieza todo archivo PNG. */
const FIRMA_PNG = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])

/** Canales por píxel de los dos tipos de color que puede emitir una captura. */
const CANALES_POR_TIPO_COLOR: Record<number, number> = {
  2: 3, // color verdadero sin alfa
  6: 4, // color verdadero con alfa
}

/** Color de un píxel con sus cuatro canales normalizados a 0–255. */
export interface PixelRgba {
  r: number
  g: number
  b: number
  a: number
}

/** Imagen ya decodificada, lista para consultarse píxel por píxel. */
export interface ImagenDecodificada {
  ancho: number
  alto: number
  /** Devuelve el color del píxel indicado; coordenadas fuera del lienzo lanzan error. */
  leer: (x: number, y: number) => PixelRgba
}

/**
 * Predictor Paeth definido por la especificación PNG.
 *
 * Elige, entre el píxel izquierdo, el superior y el diagonal, el que menos se aleja de su
 * suma menos el diagonal. Se implementa tal cual porque es el filtro que más usa Chromium.
 */
function predictorPaeth(izquierdo: number, superior: number, diagonal: number): number {
  const estimacion = izquierdo + superior - diagonal
  const distanciaIzquierdo = Math.abs(estimacion - izquierdo)
  const distanciaSuperior = Math.abs(estimacion - superior)
  const distanciaDiagonal = Math.abs(estimacion - diagonal)
  if (distanciaIzquierdo <= distanciaSuperior && distanciaIzquierdo <= distanciaDiagonal) {
    return izquierdo
  }
  return distanciaSuperior <= distanciaDiagonal ? superior : diagonal
}

/**
 * Revierte el filtro por línea que aplica PNG antes de comprimir.
 *
 * Cada scanline empieza con un byte que indica con qué filtro fue codificada. La operación
 * se hace en el mismo búfer y de arriba hacia abajo porque cada línea necesita la anterior
 * ya reconstruida.
 */
function revertirFiltros(crudo: Buffer, ancho: number, alto: number, canales: number): Buffer {
  const bytesPorLinea = ancho * canales
  const salida = Buffer.alloc(bytesPorLinea * alto)

  for (let fila = 0; fila < alto; fila += 1) {
    const inicioCrudo = fila * (bytesPorLinea + 1)
    const filtro = crudo[inicioCrudo]
    const inicioSalida = fila * bytesPorLinea
    const inicioSuperior = inicioSalida - bytesPorLinea

    for (let indice = 0; indice < bytesPorLinea; indice += 1) {
      const valor = crudo[inicioCrudo + 1 + indice] ?? 0
      const izquierdo = indice >= canales ? (salida[inicioSalida + indice - canales] ?? 0) : 0
      const superior = fila > 0 ? (salida[inicioSuperior + indice] ?? 0) : 0
      const diagonal =
        fila > 0 && indice >= canales ? (salida[inicioSuperior + indice - canales] ?? 0) : 0

      let reconstruido: number
      switch (filtro) {
        case 0:
          reconstruido = valor
          break
        case 1:
          reconstruido = valor + izquierdo
          break
        case 2:
          reconstruido = valor + superior
          break
        case 3:
          reconstruido = valor + ((izquierdo + superior) >> 1)
          break
        case 4:
          reconstruido = valor + predictorPaeth(izquierdo, superior, diagonal)
          break
        default:
          throw new Error(`Filtro PNG no soportado en la fila ${fila}: ${filtro}`)
      }
      salida[inicioSalida + indice] = reconstruido & 0xff
    }
  }

  return salida
}

/**
 * Decodifica una captura PNG de Playwright.
 *
 * @param png Búfer devuelto por `page.screenshot()`.
 * @returns Dimensiones y un lector de píxeles.
 * @throws Si el archivo no es PNG o usa una variante fuera del alcance descrito arriba.
 */
export function decodificarPng(png: Buffer): ImagenDecodificada {
  if (!png.subarray(0, 8).equals(FIRMA_PNG)) {
    throw new Error('La captura recibida no es un archivo PNG.')
  }

  let ancho = 0
  let alto = 0
  let canales = 0
  const bloquesDatos: Buffer[] = []
  let posicion = 8

  // Recorrido de chunks: longitud (4) + tipo (4) + datos + CRC (4).
  while (posicion < png.length) {
    const longitud = png.readUInt32BE(posicion)
    const tipo = png.toString('ascii', posicion + 4, posicion + 8)
    const datos = png.subarray(posicion + 8, posicion + 8 + longitud)

    if (tipo === 'IHDR') {
      ancho = datos.readUInt32BE(0)
      alto = datos.readUInt32BE(4)
      const profundidad = datos.readUInt8(8)
      const tipoColor = datos.readUInt8(9)
      const entrelazado = datos.readUInt8(12)
      if (profundidad !== 8) {
        throw new Error(`Sólo se soportan capturas de 8 bits por canal; se recibió ${profundidad}.`)
      }
      if (entrelazado !== 0) {
        throw new Error('No se soportan capturas PNG entrelazadas.')
      }
      const canalesDeclarados = CANALES_POR_TIPO_COLOR[tipoColor]
      if (canalesDeclarados === undefined) {
        throw new Error(`Tipo de color PNG no soportado: ${tipoColor}.`)
      }
      canales = canalesDeclarados
    } else if (tipo === 'IDAT') {
      bloquesDatos.push(datos)
    } else if (tipo === 'IEND') {
      break
    }

    posicion += 12 + longitud
  }

  if (ancho === 0 || alto === 0 || canales === 0) {
    throw new Error('La captura PNG no declara un encabezado IHDR utilizable.')
  }

  const pixeles = revertirFiltros(inflateSync(Buffer.concat(bloquesDatos)), ancho, alto, canales)

  return {
    ancho,
    alto,
    leer(x: number, y: number): PixelRgba {
      const columna = Math.trunc(x)
      const fila = Math.trunc(y)
      if (columna < 0 || fila < 0 || columna >= ancho || fila >= alto) {
        throw new Error(`Píxel fuera del lienzo: (${columna}, ${fila}) en ${ancho}×${alto}.`)
      }
      const base = (fila * ancho + columna) * canales
      return {
        r: pixeles[base] ?? 0,
        g: pixeles[base + 1] ?? 0,
        b: pixeles[base + 2] ?? 0,
        // Una captura sin canal alfa es, por definición, completamente opaca.
        a: canales === 4 ? (pixeles[base + 3] ?? 0) : 255,
      }
    },
  }
}

/** Formatea un píxel para que un fallo diga qué color apareció realmente. */
export function describirPixel(pixel: PixelRgba): string {
  return `rgba(${pixel.r}, ${pixel.g}, ${pixel.b}, ${pixel.a})`
}
