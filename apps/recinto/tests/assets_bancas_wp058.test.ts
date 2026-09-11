/**
 * Prueba del recorte de margen inerte del bitmap institucional (WP-058).
 *
 * HUMAN_GATE pidió que la identidad de cada concejal se vea con mayor escala.
 * Nombre, apellido y bloque están dibujados *dentro* del archivo PNG, así que
 * la única ganancia posible sin duplicarlos como texto ni recortar contenido es
 * dejar de dibujar el marco blanco que el propio archivo desperdicia.
 *
 * `BancaPublica.vue` declara ese recorte con `object-view-box`. Esta prueba es
 * la demostración que exige el WP: decodifica los doce archivos reales píxel a
 * píxel, calcula cuánto margen totalmente inerte tiene cada uno y verifica que
 * el recorte declarado en el CSS cabe dentro de ese margen en *todos* ellos.
 *
 * Dicho de otro modo: si mañana alguien reemplaza un asset por otro con el
 * nombre pegado al borde, esta prueba falla antes de que la pantalla recorte
 * información institucional.
 *
 * Alcance después de WP-098
 * -------------------------
 *
 * WP-098 eliminó las copias por aplicación: las fotografías ya no viven en
 * el directorio `public/assets/bancas/` de cada aplicación sino en la configuración local de cada
 * instalación, bajo `config/assets/bancas/`. Lo único versionado —y por lo
 * tanto lo único que una prueba puede medir en cada Pull Request— es la
 * plantilla reproducible `config/assets.example/bancas/`, que es de donde sale
 * el directorio runtime en desarrollo y en las pruebas.
 *
 * Queda escrito con claridad: esta prueba ya no puede garantizar el encuadre de
 * una fotografía que el operador cargue en producción, porque ese archivo no
 * está en el repositorio. Sigue garantizando el de las doce de referencia, que
 * son las que ejercitan desarrollo, las pruebas y el E2E integrado.
 */

import { existsSync, readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { inflateSync } from 'node:zlib'
import { describe, expect, it } from 'vitest'

/** Cantidad de bancas del padrón de desarrollo y, por lo tanto, de archivos. */
const CANTIDAD_ASSETS = 12

/**
 * Raíz del monorepo, buscada hacia arriba desde el directorio de trabajo.
 *
 * Estas pruebas se compilan en modo cliente (ver `entorno_dom_cliente.ts`), así
 * que `import.meta.url` no apunta a un archivo del disco. Subir hasta el
 * `pnpm-workspace.yaml` es la forma estable de ubicar los archivos reales tanto
 * si Vitest se lanza desde la raíz como si se lanza desde `apps/recinto`.
 */
function ubicarRaizMonorepo(): string {
  let directorio = resolve(process.cwd())
  while (!existsSync(join(directorio, 'pnpm-workspace.yaml'))) {
    const padre = dirname(directorio)
    if (padre === directorio) throw new Error('No se encontró la raíz del monorepo')
    directorio = padre
  }
  return directorio
}

const raizMonorepo = ubicarRaizMonorepo()
const rutaComponente = join(
  raizMonorepo,
  'apps',
  'recinto',
  'app',
  'components',
  'BancaPublica.vue',
)

/** Plantilla versionada de las fotografías, única fuente revisable (WP-098). */
const directorioPlantilla = join(raizMonorepo, 'config', 'assets.example', 'bancas')

function rutaAsset(banca: number): string {
  return join(directorioPlantilla, `banca-${String(banca).padStart(2, '0')}.png`)
}

interface ImagenDecodificada {
  ancho: number
  alto: number
  /** Píxeles RGBA consecutivos, cuatro bytes por píxel. */
  pixeles: Uint8Array
}

/**
 * Decodificador PNG mínimo, suficiente para estos assets.
 *
 * No se agrega una dependencia nueva sólo para leer doce archivos: los doce son
 * PNG de 8 bits por canal, RGBA y sin entrelazado, que es el caso más simple del
 * formato. La prueba verifica esas tres condiciones antes de decodificar, así
 * que un archivo con otro formato falla con un mensaje claro en lugar de
 * producir píxeles inventados.
 *
 * El formato guarda las filas comprimidas con zlib y, antes de comprimir,
 * aplica a cada fila uno de cinco "filtros" que la expresan como diferencia
 * respecto del píxel de la izquierda y/o de la fila de arriba. Deshacer esos
 * filtros es todo lo que hace el bucle principal.
 */
function decodificarPng(ruta: string): ImagenDecodificada {
  const archivo = readFileSync(ruta)
  const firma = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]
  for (const [indice, byte] of firma.entries()) {
    expect(archivo[indice], `${ruta} no tiene firma PNG`).toBe(byte)
  }

  let posicion = 8
  let ancho = 0
  let alto = 0
  const trozosDatos: Buffer[] = []

  while (posicion < archivo.length) {
    const largo = archivo.readUInt32BE(posicion)
    const tipo = archivo.toString('ascii', posicion + 4, posicion + 8)
    const cuerpo = archivo.subarray(posicion + 8, posicion + 8 + largo)

    if (tipo === 'IHDR') {
      ancho = cuerpo.readUInt32BE(0)
      alto = cuerpo.readUInt32BE(4)
      expect(cuerpo[8], `${ruta} debe tener 8 bits por canal`).toBe(8)
      expect(cuerpo[9], `${ruta} debe ser RGBA (color type 6)`).toBe(6)
      expect(cuerpo[12], `${ruta} no debe estar entrelazado`).toBe(0)
    } else if (tipo === 'IDAT') {
      trozosDatos.push(Buffer.from(cuerpo))
    }

    // 4 bytes de longitud + 4 de tipo + cuerpo + 4 de CRC.
    posicion += 12 + largo
  }

  const bytesPorPixel = 4
  const bytesPorFila = ancho * bytesPorPixel
  const comprimido = Buffer.concat(trozosDatos)
  const bruto = inflateSync(comprimido)
  const pixeles = new Uint8Array(alto * bytesPorFila)

  let lectura = 0
  for (let fila = 0; fila < alto; fila += 1) {
    const filtro = bruto[lectura]
    lectura += 1
    const destino = fila * bytesPorFila
    const anterior = destino - bytesPorFila

    for (let columna = 0; columna < bytesPorFila; columna += 1) {
      const crudo = bruto[lectura + columna] ?? 0
      // `izquierda` y `arriba` valen 0 fuera de la imagen, como exige el formato.
      const izquierda = columna >= bytesPorPixel ? pixeles[destino + columna - bytesPorPixel]! : 0
      const arriba = fila > 0 ? pixeles[anterior + columna]! : 0
      const diagonal =
        fila > 0 && columna >= bytesPorPixel ? pixeles[anterior + columna - bytesPorPixel]! : 0

      let valor: number
      switch (filtro) {
        case 0:
          valor = crudo
          break
        case 1:
          valor = crudo + izquierda
          break
        case 2:
          valor = crudo + arriba
          break
        case 3:
          valor = crudo + Math.floor((izquierda + arriba) / 2)
          break
        case 4: {
          // Filtro "Paeth": elige como predicción el vecino más cercano a la
          // suma izquierda + arriba − diagonal.
          const estimado = izquierda + arriba - diagonal
          const distanciaIzquierda = Math.abs(estimado - izquierda)
          const distanciaArriba = Math.abs(estimado - arriba)
          const distanciaDiagonal = Math.abs(estimado - diagonal)
          const prediccion =
            distanciaIzquierda <= distanciaArriba && distanciaIzquierda <= distanciaDiagonal
              ? izquierda
              : distanciaArriba <= distanciaDiagonal
                ? arriba
                : diagonal
          valor = crudo + prediccion
          break
        }
        default:
          throw new Error(`${ruta}: filtro PNG desconocido ${filtro}`)
      }
      pixeles[destino + columna] = valor & 0xff
    }
    lectura += bytesPorFila
  }

  return { ancho, alto, pixeles }
}

/**
 * Un píxel es inerte cuando no aporta información visible: o es transparente, o
 * es blanco puro sobre el fondo blanco de la tarjeta. Se exige blanco exacto
 * —no "casi blanco"— para que el margen que se recorta sea indiscutible.
 */
function esInerte(imagen: ImagenDecodificada, x: number, y: number): boolean {
  const base = (y * imagen.ancho + x) * 4
  const alfa = imagen.pixeles[base + 3]!
  if (alfa === 0) return true
  return (
    imagen.pixeles[base]! === 255 &&
    imagen.pixeles[base + 1]! === 255 &&
    imagen.pixeles[base + 2]! === 255
  )
}

interface MargenInerte {
  arriba: number
  abajo: number
  izquierda: number
  derecha: number
}

/** Mide cuántos píxeles completamente inertes hay en cada borde del archivo. */
function medirMargenInerte(imagen: ImagenDecodificada): MargenInerte {
  const filaInerte = (y: number) => {
    for (let x = 0; x < imagen.ancho; x += 1) if (!esInerte(imagen, x, y)) return false
    return true
  }
  const columnaInerte = (x: number) => {
    for (let y = 0; y < imagen.alto; y += 1) if (!esInerte(imagen, x, y)) return false
    return true
  }

  let arriba = 0
  while (arriba < imagen.alto && filaInerte(arriba)) arriba += 1
  let abajo = 0
  while (abajo < imagen.alto - arriba && filaInerte(imagen.alto - 1 - abajo)) abajo += 1
  let izquierda = 0
  while (izquierda < imagen.ancho && columnaInerte(izquierda)) izquierda += 1
  let derecha = 0
  while (derecha < imagen.ancho - izquierda && columnaInerte(imagen.ancho - 1 - derecha)) {
    derecha += 1
  }

  return { arriba, abajo, izquierda, derecha }
}

/**
 * Lee del propio componente el recorte declarado.
 *
 * Se parsea el CSS en lugar de repetir los números en la prueba para que el
 * recorte real y su demostración no puedan separarse: cambiar el `inset` sin
 * volver a comprobarlo contra los archivos hace fallar esta prueba.
 */
function leerRecorteDeclarado(): MargenInerte {
  const fuente = readFileSync(rutaComponente, 'utf8')
  const coincidencia = fuente.match(
    /object-view-box:\s*inset\(\s*([\d.]+)px\s+([\d.]+)px\s+([\d.]+)px\s+([\d.]+)px\s*\)/,
  )
  expect(
    coincidencia,
    'BancaPublica.vue debe declarar object-view-box con cuatro valores',
  ).not.toBe(null)
  const [, arriba, derecha, abajo, izquierda] = coincidencia!
  return {
    arriba: Number(arriba),
    derecha: Number(derecha),
    abajo: Number(abajo),
    izquierda: Number(izquierda),
  }
}

describe('Recorte del marco inerte de los bitmaps de banca (WP-058)', () => {
  const bancas = Array.from({ length: CANTIDAD_ASSETS }, (_, indice) => indice + 1)
  const imagenes = new Map(bancas.map((banca) => [banca, decodificarPng(rutaAsset(banca))]))
  const recorte = leerRecorteDeclarado()

  it('los doce archivos comparten el mismo lienzo cuadrado', () => {
    // El recorte se expresa en píxeles del archivo, así que sólo es uniforme si
    // los doce archivos miden lo mismo.
    for (const [banca, imagen] of imagenes) {
      expect({ banca, ancho: imagen.ancho, alto: imagen.alto }).toEqual({
        banca,
        ancho: 300,
        alto: 300,
      })
    }
  })

  it('el recorte declarado no toca ni un píxel con contenido en ningún archivo', () => {
    for (const [banca, imagen] of imagenes) {
      const margen = medirMargenInerte(imagen)
      // Cada borde recortado debe seguir estando dentro del margen inerte real.
      expect({ banca, borde: 'arriba', recorta: recorte.arriba <= margen.arriba }).toEqual({
        banca,
        borde: 'arriba',
        recorta: true,
      })
      expect({ banca, borde: 'abajo', recorta: recorte.abajo <= margen.abajo }).toEqual({
        banca,
        borde: 'abajo',
        recorta: true,
      })
      expect({ banca, borde: 'izquierda', recorta: recorte.izquierda <= margen.izquierda }).toEqual(
        {
          banca,
          borde: 'izquierda',
          recorta: true,
        },
      )
      expect({ banca, borde: 'derecha', recorta: recorte.derecha <= margen.derecha }).toEqual({
        banca,
        borde: 'derecha',
        recorta: true,
      })
    }
  })

  it('el recorte gana escala real y conserva el lienzo dentro de la tarjeta', () => {
    const alto = 300 - recorte.arriba - recorte.abajo
    const ancho = 300 - recorte.izquierda - recorte.derecha

    // La tarjeta pública es más ancha que alta, así que `object-fit: contain`
    // ajusta por altura: la escala útil crece exactamente en la proporción en
    // que se acortó el lienzo.
    const ganancia = 300 / alto
    expect(ganancia).toBeGreaterThan(1)
    expect(ganancia).toBeCloseTo(1.053, 3)

    // El recorte debe seguir siendo un recorte: nunca puede pedir más lienzo del
    // que el archivo tiene.
    expect(alto).toBeGreaterThan(0)
    expect(ancho).toBeGreaterThan(0)
    expect(alto).toBeLessThanOrEqual(300)
    expect(ancho).toBeLessThanOrEqual(300)
  })

  it('el recorte se declara detrás de @supports para degradar sin romper', () => {
    const fuente = readFileSync(rutaComponente, 'utf8')
    // Donde el motor no conozca `object-view-box`, la tarjeta debe volver al
    // encuadre anterior en lugar de quedar sin imagen.
    expect(fuente).toContain('@supports (object-view-box: inset(0))')
  })
})
