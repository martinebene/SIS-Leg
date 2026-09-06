/**
 * Generador reproducible del logo completo de SIS-Leg (WP-069).
 *
 * ## Por qué existe este script
 *
 * HUMAN_GATE entregó el 04/09/2026 un PNG con el logo ya recortado y autorizó **una sola**
 * edición sobre él: suavizar mínimamente el borde. Cualquier otra cosa —recortar,
 * redimensionar, recolorear, redibujar, agregar fondo— está expresamente prohibida por
 * `docs/work-packages/WP-069.md`.
 *
 * Una edición hecha a mano en un editor de imágenes no se puede auditar: nadie que revise
 * la PR puede saber si además se movió un píxel del interior. Este script convierte esa
 * edición en un procedimiento determinista, ejecutable y verificable: dado el mismo
 * archivo humano produce siempre exactamente los mismos bytes, y comprueba por sí mismo
 * que el resultado respeta todos los límites que el WP declara.
 *
 * ## Qué transformación aplica, exactamente
 *
 * Sólo toca el **canal alfa**, y sólo en la **banda de borde**: los píxeles que ya tenían
 * alfa mayor que cero y que tienen al menos un vecino (en las ocho direcciones)
 * completamente transparente en el archivo original. Ahí calcula un promedio gaussiano
 * 3×3 del alfa y se queda con el **mínimo** entre ese promedio y el alfa original:
 *
 *     alfa_final(x, y) = min(alfa_original(x, y), promedioGaussiano3x3(alfa_original)(x, y))
 *
 * Tomar el mínimo es lo que vuelve segura la operación. Un desenfoque normal reparte
 * opacidad hacia afuera y engordaría el contorno; al acotarlo por el valor original, el
 * alfa sólo puede bajar. De ahí salen tres garantías que el WP exige y que este script
 * comprueba después sobre el resultado:
 *
 * 1. no aparecen píxeles opacos donde el original era completamente transparente;
 * 2. el soporte de la imagen —la silueta— nunca se expande, así que el suavizado no puede
 *    excederse del contorno blanco existente;
 * 3. el interior no cambia: un píxel rodeado de píxeles igual de opacos tiene promedio
 *    igual a su propio valor, y además ni siquiera entra en la banda de borde.
 *
 * Los tres canales de color viajan intactos byte a byte.
 *
 * ## Uso
 *
 *     node scripts/generar_logo_sisleg.mjs --fuente <ruta-al-png-humano>
 *     node scripts/generar_logo_sisleg.mjs --fuente <ruta> --verificar
 *
 * Sin `--verificar` escribe `assets/branding/sisleg-logo.png` y las copias públicas de las
 * cuatro aplicaciones. Con `--verificar` no escribe nada: sólo recalcula el derivado y
 * confirma que coincide con lo que ya está versionado.
 */

import { createHash } from 'node:crypto'
import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import zlib from 'node:zlib'

/** Raíz del monorepo: este archivo vive en `scripts/`, un nivel por debajo. */
const RAIZ = resolve(dirname(fileURLToPath(import.meta.url)), '..')

/**
 * SHA-256 del archivo entregado por HUMAN_GATE el 04/09/2026 («Logo recortado.png»).
 *
 * Es la única entrada admitida. Si no coincide, el script aborta en lugar de producir un
 * derivado de un archivo parecido: WP-069 prohíbe expresamente sustituir el asset humano
 * por una recreación, una captura o un logo previo.
 */
const SHA256_FUENTE = '98d155ddf73e7d10d7b8b40f8510e0423b0d6dbffd749c79173b173fd0cfc756'

/** Dimensiones del lienzo humano, que el derivado debe conservar sin recorte ni escala. */
const ANCHO_ESPERADO = 1536
const ALTO_ESPERADO = 1024

/** Ruta del logo canónico dentro del repositorio. */
const RUTA_CANONICA = join('assets', 'branding', 'sisleg-logo.png')

/** Las cuatro SPA que publican una copia byte a byte del logo canónico. */
const APLICACIONES = ['moderacion', 'recinto', 'tecnico', 'simulador']

/**
 * Núcleo gaussiano 3×3 discreto, con peso central 4 y suma 16.
 *
 * Se elige el más pequeño posible a propósito: el WP pide un suavizado **mínimo**, no un
 * desenfoque. Con este núcleo la transición afecta a un único píxel de ancho y el borde
 * recto pierde a lo sumo un cuarto de su opacidad, mientras que los escalones del
 * dentado —que tienen menos vecinos opacos— bajan más y dejan de leerse como escalera.
 */
const NUCLEO = [
  [1, 2, 1],
  [2, 4, 2],
  [1, 2, 1],
]
const PESO_TOTAL = 16

// =============================================================================
// Lectura y escritura de PNG
// =============================================================================

/**
 * Tabla del CRC-32 que exige el formato PNG (polinomio 0xEDB88320).
 *
 * Cada bloque de un PNG termina con el CRC de su tipo y su contenido. Los navegadores lo
 * verifican y descartan la imagen entera si no cierra, así que hay que calcularlo bien al
 * escribir: durante WP-062 un CRC alterado dejó el logo invisible en Chromium.
 */
const TABLA_CRC = (() => {
  const tabla = new Uint32Array(256)
  for (let byte = 0; byte < 256; byte += 1) {
    let resto = byte
    for (let bit = 0; bit < 8; bit += 1) {
      resto = resto & 1 ? (resto >>> 1) ^ 0xedb88320 : resto >>> 1
    }
    tabla[byte] = resto >>> 0
  }
  return tabla
})()

/** CRC-32 de un bloque de bytes. */
function crc32(datos) {
  let resto = 0xffffffff
  for (const byte of datos) resto = TABLA_CRC[(resto ^ byte) & 0xff] ^ (resto >>> 8)
  return (resto ^ 0xffffffff) >>> 0
}

/**
 * Decodifica un PNG RGBA de 8 bits por canal, sin entrelazado.
 *
 * No se usa una biblioteca externa porque el proyecto no declara ninguna dependencia de
 * imágenes y agregar una sólo para esto sería una decisión de stack reservada. El formato
 * que hace falta leer es además el más simple del estándar: firma, bloque `IHDR` con las
 * dimensiones, uno o varios `IDAT` con el flujo `zlib` y el cierre `IEND`.
 *
 * Lo único que tiene sustancia es deshacer los **filtros** por línea. Antes de comprimir,
 * un codificador PNG resta a cada byte una predicción calculada a partir del píxel de la
 * izquierda (`a`), el de arriba (`b`) y el de arriba a la izquierda (`c`). Decodificar es
 * volver a sumar esa predicción, línea por línea y en orden, porque cada línea depende de
 * la anterior ya reconstruida.
 *
 * @param {Buffer} archivo contenido completo del PNG
 * @returns {{ancho: number, alto: number, pixeles: Buffer}} píxeles RGBA sin filtrar
 */
function decodificarPng(archivo) {
  if (archivo.subarray(0, 8).toString('latin1') !== '\x89PNG\r\n\x1a\n') {
    throw new Error('El archivo no tiene la firma de un PNG.')
  }

  let posicion = 8
  let ancho = 0
  let alto = 0
  let profundidad = 0
  let tipoColor = 0
  let entrelazado = 0
  const bloquesDatos = []

  while (posicion + 12 <= archivo.length) {
    const longitud = archivo.readUInt32BE(posicion)
    const tipo = archivo.subarray(posicion + 4, posicion + 8).toString('latin1')
    const contenido = archivo.subarray(posicion + 8, posicion + 8 + longitud)

    if (tipo === 'IHDR') {
      ancho = contenido.readUInt32BE(0)
      alto = contenido.readUInt32BE(4)
      profundidad = contenido[8]
      tipoColor = contenido[9]
      entrelazado = contenido[12]
    } else if (tipo === 'IDAT') {
      bloquesDatos.push(contenido)
    }

    posicion += 12 + longitud
    if (tipo === 'IEND') break
  }

  if (profundidad !== 8 || tipoColor !== 6 || entrelazado !== 0) {
    throw new Error(
      `Sólo se admite PNG RGBA de 8 bits sin entrelazar; se recibió profundidad ${profundidad}, ` +
        `tipo de color ${tipoColor}, entrelazado ${entrelazado}.`,
    )
  }

  const crudo = zlib.inflateSync(Buffer.concat(bloquesDatos))
  const bytesPorPixel = 4
  const bytesPorLinea = ancho * bytesPorPixel
  const pixeles = Buffer.alloc(alto * bytesPorLinea)
  let lectura = 0

  for (let y = 0; y < alto; y += 1) {
    const filtro = crudo[lectura]
    lectura += 1
    const linea = crudo.subarray(lectura, lectura + bytesPorLinea)
    lectura += bytesPorLinea

    const destino = pixeles.subarray(y * bytesPorLinea, (y + 1) * bytesPorLinea)
    const anterior = y > 0 ? pixeles.subarray((y - 1) * bytesPorLinea, y * bytesPorLinea) : null

    for (let i = 0; i < bytesPorLinea; i += 1) {
      const izquierda = i >= bytesPorPixel ? destino[i - bytesPorPixel] : 0
      const arriba = anterior ? anterior[i] : 0
      const diagonal = anterior && i >= bytesPorPixel ? anterior[i - bytesPorPixel] : 0
      const valor = linea[i]

      switch (filtro) {
        case 0:
          destino[i] = valor
          break
        case 1:
          destino[i] = (valor + izquierda) & 0xff
          break
        case 2:
          destino[i] = (valor + arriba) & 0xff
          break
        case 3:
          destino[i] = (valor + ((izquierda + arriba) >> 1)) & 0xff
          break
        case 4:
          destino[i] = (valor + prediccionPaeth(izquierda, arriba, diagonal)) & 0xff
          break
        default:
          throw new Error(`Filtro PNG desconocido: ${filtro}`)
      }
    }
  }

  return { ancho, alto, pixeles }
}

/**
 * Predictor Paeth del estándar PNG: elige, entre el vecino izquierdo, el superior y el
 * diagonal, aquel que más se aproxima a `izquierda + arriba - diagonal`.
 */
function prediccionPaeth(izquierda, arriba, diagonal) {
  const estimacion = izquierda + arriba - diagonal
  const distanciaIzquierda = Math.abs(estimacion - izquierda)
  const distanciaArriba = Math.abs(estimacion - arriba)
  const distanciaDiagonal = Math.abs(estimacion - diagonal)
  if (distanciaIzquierda <= distanciaArriba && distanciaIzquierda <= distanciaDiagonal) {
    return izquierda
  }
  return distanciaArriba <= distanciaDiagonal ? arriba : diagonal
}

/**
 * Codifica píxeles RGBA como PNG.
 *
 * Para cada línea se prueban los cinco filtros del estándar y se conserva el que produce
 * la menor suma de valores absolutos con signo, que es la heurística que recomienda la
 * especificación y la que usan los codificadores habituales. La elección es determinista,
 * así que dos ejecuciones sobre los mismos píxeles producen los mismos bytes.
 */
function codificarPng(ancho, alto, pixeles) {
  const bytesPorPixel = 4
  const bytesPorLinea = ancho * bytesPorPixel
  const crudo = Buffer.alloc(alto * (bytesPorLinea + 1))
  const candidato = Buffer.alloc(bytesPorLinea)
  let escritura = 0

  for (let y = 0; y < alto; y += 1) {
    const linea = pixeles.subarray(y * bytesPorLinea, (y + 1) * bytesPorLinea)
    const anterior = y > 0 ? pixeles.subarray((y - 1) * bytesPorLinea, y * bytesPorLinea) : null

    let mejorFiltro = 0
    let mejorCosto = Number.POSITIVE_INFINITY
    let mejorLinea = Buffer.from(linea)

    for (let filtro = 0; filtro <= 4; filtro += 1) {
      let costo = 0
      for (let i = 0; i < bytesPorLinea; i += 1) {
        const izquierda = i >= bytesPorPixel ? linea[i - bytesPorPixel] : 0
        const arriba = anterior ? anterior[i] : 0
        const diagonal = anterior && i >= bytesPorPixel ? anterior[i - bytesPorPixel] : 0
        let valor
        switch (filtro) {
          case 0:
            valor = linea[i]
            break
          case 1:
            valor = linea[i] - izquierda
            break
          case 2:
            valor = linea[i] - arriba
            break
          case 3:
            valor = linea[i] - ((izquierda + arriba) >> 1)
            break
          default:
            valor = linea[i] - prediccionPaeth(izquierda, arriba, diagonal)
        }
        candidato[i] = valor & 0xff
        // El costo se mide sobre el byte interpretado con signo: un residuo cercano a
        // cero, positivo o negativo, es lo que comprime bien.
        costo += Math.abs(((valor & 0xff) << 24) >> 24)
      }
      if (costo < mejorCosto) {
        mejorCosto = costo
        mejorFiltro = filtro
        mejorLinea = Buffer.from(candidato)
      }
    }

    crudo[escritura] = mejorFiltro
    escritura += 1
    mejorLinea.copy(crudo, escritura)
    escritura += bytesPorLinea
  }

  const cabecera = Buffer.alloc(13)
  cabecera.writeUInt32BE(ancho, 0)
  cabecera.writeUInt32BE(alto, 4)
  cabecera[8] = 8 // profundidad de bits
  cabecera[9] = 6 // tipo de color RGBA
  cabecera[10] = 0 // compresión deflate
  cabecera[11] = 0 // filtrado estándar
  cabecera[12] = 0 // sin entrelazado

  const comprimido = zlib.deflateSync(crudo, { level: 9, memLevel: 9, windowBits: 15 })

  return Buffer.concat([
    Buffer.from('\x89PNG\r\n\x1a\n', 'latin1'),
    armarBloque('IHDR', cabecera),
    armarBloque('IDAT', comprimido),
    armarBloque('IEND', Buffer.alloc(0)),
  ])
}

/** Envuelve un contenido en la estructura `longitud | tipo | contenido | CRC` del PNG. */
function armarBloque(tipo, contenido) {
  const longitud = Buffer.alloc(4)
  longitud.writeUInt32BE(contenido.length, 0)
  const etiqueta = Buffer.from(tipo, 'latin1')
  const crc = Buffer.alloc(4)
  crc.writeUInt32BE(crc32(Buffer.concat([etiqueta, contenido])), 0)
  return Buffer.concat([longitud, etiqueta, contenido, crc])
}

// =============================================================================
// Suavizado autorizado
// =============================================================================

/**
 * Aplica el único retoque permitido por WP-069 y devuelve los píxeles resultantes junto
 * con las medidas que después se informan en la PR.
 *
 * @param {{ancho: number, alto: number, pixeles: Buffer}} imagen imagen original
 */
function suavizarBorde({ ancho, alto, pixeles }) {
  const resultado = Buffer.from(pixeles)

  /** Alfa del original, con el exterior del lienzo tratado como transparente. */
  const alfa = (x, y) =>
    x < 0 || y < 0 || x >= ancho || y >= alto ? 0 : pixeles[(y * ancho + x) * 4 + 3]

  let pixelesEnBanda = 0
  let pixelesModificados = 0
  let diferenciaMaxima = 0
  let sumaDiferencias = 0

  for (let y = 0; y < alto; y += 1) {
    for (let x = 0; x < ancho; x += 1) {
      const original = alfa(x, y)
      // Un píxel completamente transparente no se toca nunca: es lo que garantiza que el
      // soporte de la imagen no crezca ni un píxel.
      if (original === 0) continue

      // La banda de borde son los píxeles con algún vecino transparente. El interior
      // queda excluido antes de calcular nada, de modo que «el interior no cambia» no
      // depende de que el promedio dé por casualidad el mismo valor.
      let esBorde = false
      for (let dy = -1; dy <= 1 && !esBorde; dy += 1) {
        for (let dx = -1; dx <= 1; dx += 1) {
          if (alfa(x + dx, y + dy) === 0) {
            esBorde = true
            break
          }
        }
      }
      if (!esBorde) continue
      pixelesEnBanda += 1

      let acumulado = 0
      for (let dy = -1; dy <= 1; dy += 1) {
        for (let dx = -1; dx <= 1; dx += 1) {
          acumulado += NUCLEO[dy + 1][dx + 1] * alfa(x + dx, y + dy)
        }
      }
      const promedio = Math.round(acumulado / PESO_TOTAL)
      const nuevo = Math.min(original, promedio)

      if (nuevo !== original) {
        pixelesModificados += 1
        const diferencia = original - nuevo
        sumaDiferencias += diferencia
        if (diferencia > diferenciaMaxima) diferenciaMaxima = diferencia
        resultado[(y * ancho + x) * 4 + 3] = nuevo
      }
    }
  }

  return {
    pixeles: resultado,
    pixelesEnBanda,
    pixelesModificados,
    diferenciaMaxima,
    diferenciaPromedio: pixelesModificados === 0 ? 0 : sumaDiferencias / pixelesModificados,
  }
}

/**
 * Comprueba sobre los píxeles finales todos los límites que WP-069 declara innegociables.
 *
 * Se verifica el resultado y no la intención: aunque el algoritmo esté escrito para
 * respetarlos, un error de programación se detecta acá y aborta la generación.
 */
function verificarInvariantes(original, derivado) {
  if (original.ancho !== ANCHO_ESPERADO || original.alto !== ALTO_ESPERADO) {
    throw new Error(`El lienzo original no es ${ANCHO_ESPERADO}×${ALTO_ESPERADO}.`)
  }
  if (derivado.length !== original.pixeles.length) {
    throw new Error('El derivado no conserva la cantidad de píxeles del original.')
  }

  let alfaReducido = 0
  for (let indice = 0; indice < original.pixeles.length; indice += 4) {
    for (let canal = 0; canal < 3; canal += 1) {
      if (derivado[indice + canal] !== original.pixeles[indice + canal]) {
        const pixel = indice / 4
        throw new Error(
          `Se modificó un canal de color en (${pixel % original.ancho}, ` +
            `${Math.floor(pixel / original.ancho)}).`,
        )
      }
    }

    const antes = original.pixeles[indice + 3]
    const despues = derivado[indice + 3]
    if (despues > antes) {
      const pixel = indice / 4
      throw new Error(
        `El alfa aumentó en (${pixel % original.ancho}, ${Math.floor(pixel / original.ancho)}): ` +
          'el suavizado no puede expandir la silueta ni exceder el contorno.',
      )
    }
    if (despues < antes) alfaReducido += 1
  }

  // El interior estricto —píxeles opacos sin ningún vecino transparente— tiene que haber
  // quedado idéntico. Se recorre otra vez de forma independiente del bucle que suaviza.
  const alfa = (x, y) =>
    x < 0 || y < 0 || x >= original.ancho || y >= original.alto
      ? 0
      : original.pixeles[(y * original.ancho + x) * 4 + 3]

  for (let y = 0; y < original.alto; y += 1) {
    for (let x = 0; x < original.ancho; x += 1) {
      if (alfa(x, y) === 0) continue
      let tocaTransparente = false
      for (let dy = -1; dy <= 1 && !tocaTransparente; dy += 1) {
        for (let dx = -1; dx <= 1; dx += 1) {
          if (alfa(x + dx, y + dy) === 0) {
            tocaTransparente = true
            break
          }
        }
      }
      if (tocaTransparente) continue
      const indice = (y * original.ancho + x) * 4 + 3
      if (derivado[indice] !== original.pixeles[indice]) {
        throw new Error(`Se modificó alfa fuera de la banda de borde, en (${x}, ${y}).`)
      }
    }
  }

  return { alfaReducido }
}

// =============================================================================
// Programa
// =============================================================================

function leerArgumento(nombre) {
  const posicion = process.argv.indexOf(nombre)
  return posicion === -1 ? null : process.argv[posicion + 1]
}

function principal() {
  const rutaFuente = leerArgumento('--fuente')
  const soloVerificar = process.argv.includes('--verificar')

  if (!rutaFuente) {
    throw new Error(
      'Falta --fuente con la ruta del PNG entregado por HUMAN_GATE.\n' +
        'Uso: node scripts/generar_logo_sisleg.mjs --fuente <ruta> [--verificar]',
    )
  }

  const archivoFuente = readFileSync(rutaFuente)
  const hashFuente = createHash('sha256').update(archivoFuente).digest('hex')
  if (hashFuente !== SHA256_FUENTE) {
    throw new Error(
      `El archivo fuente no es el aprobado por HUMAN_GATE.\n` +
        `  esperado: ${SHA256_FUENTE}\n  recibido: ${hashFuente}`,
    )
  }

  const original = decodificarPng(archivoFuente)
  const suavizado = suavizarBorde(original)
  const { alfaReducido } = verificarInvariantes(original, suavizado.pixeles)
  const png = codificarPng(original.ancho, original.alto, suavizado.pixeles)

  // Releer lo que se acaba de escribir cierra el círculo: comprueba que el PNG generado se
  // vuelve a decodificar exactamente igual, y no sólo que el arreglo de píxeles era bueno.
  const releido = decodificarPng(png)
  if (!releido.pixeles.equals(suavizado.pixeles)) {
    throw new Error('El PNG codificado no vuelve a decodificarse igual.')
  }

  const hashDerivado = createHash('sha256').update(png).digest('hex')
  const destinos = [
    RUTA_CANONICA,
    ...APLICACIONES.map((app) => join('apps', app, 'public', 'assets', 'marca', 'sisleg-logo.png')),
  ]

  console.log(`fuente ......................... ${rutaFuente}`)
  console.log(`SHA-256 fuente ................. ${hashFuente}`)
  console.log(`lienzo ......................... ${original.ancho}×${original.alto} RGBA 8 bits`)
  console.log(`píxeles en la banda de borde ... ${suavizado.pixelesEnBanda}`)
  console.log(`píxeles con alfa modificado .... ${suavizado.pixelesModificados}`)
  console.log(`reducción máxima de alfa ....... ${suavizado.diferenciaMaxima} / 255`)
  console.log(`reducción media de alfa ........ ${suavizado.diferenciaPromedio.toFixed(2)} / 255`)
  console.log(`píxeles con alfa reducido ...... ${alfaReducido}`)
  console.log(`canales de color modificados ... 0`)
  console.log(`tamaño del derivado ............ ${png.length} bytes`)
  console.log(`SHA-256 derivado ............... ${hashDerivado}`)

  if (soloVerificar) {
    let diferencias = 0
    for (const destino of destinos) {
      const existente = readFileSync(join(RAIZ, destino))
      if (!existente.equals(png)) {
        console.error(`DIFIERE: ${destino}`)
        diferencias += 1
      }
    }
    if (diferencias > 0) {
      throw new Error(`${diferencias} archivo(s) versionados no coinciden con el derivado.`)
    }
    console.log('\nVerificación correcta: todo lo versionado coincide con el derivado.')
    return
  }

  for (const destino of destinos) {
    writeFileSync(join(RAIZ, destino), png)
    console.log(`escrito ........................ ${destino}`)
  }
}

principal()
