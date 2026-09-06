/**
 * Identidad visible SIS-Leg en las superficies compartidas (WP-062).
 *
 * ## Qué demuestra esta prueba
 *
 * WP-062 no cambia comportamiento: cambia qué marca ve una persona. Eso vive en archivos
 * que ningún test de componentes toca —el HTML que Nuxt incrusta antes de hidratar, las
 * cuatro `nuxt.config.ts` y los PNG copiados a cada `public/`—, así que la única forma de
 * protegerlo de una regresión es leer esos archivos reales desde el disco y afirmar sobre
 * su contenido.
 *
 * Se comprueban tres cosas distintas:
 *
 * 1. **Fidelidad de la marca.** Cada aplicación sirve una copia de los PNG aprobados. Si
 *    alguien reemplaza una copia por otra versión —recortada distinto, recoloreada, con
 *    fondo—, la comparación byte a byte contra `assets/branding/` falla. El WP prohíbe
 *    expresamente redibujar la marca, y esto es lo que lo hace verificable.
 * 2. **Pantalla de carga.** Debe mostrar el logo completo y no puede volver a nombrar
 *    «Botonera2» como marca.
 * 3. **Metadatos de las cuatro SPA.** Título con SIS-Leg y favicon con el isotipo, cada uno
 *    bajo el prefijo público de su propia aplicación: un `href` sin ese prefijo apuntaría
 *    a la raíz del servidor, donde el archivo no existe.
 */

import { createHash } from 'node:crypto'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * Raíz del monorepo, buscada hacia arriba desde el directorio de trabajo.
 *
 * Mismo procedimiento que usa la prueba de assets de bancas: Vitest puede lanzarse desde
 * la raíz o desde un paquete, y `import.meta.url` no siempre apunta a un archivo real
 * cuando la prueba se compila en modo cliente. El `pnpm-workspace.yaml` es el único
 * marcador estable de la raíz.
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

const raiz = ubicarRaizMonorepo()

/** Las cuatro SPA y el prefijo público bajo el que se sirve cada una. */
const APLICACIONES = [
  { nombre: 'moderacion', rutaBase: '/moderacion/', titulo: 'SIS-Leg · Moderación' },
  { nombre: 'recinto', rutaBase: '/recinto/', titulo: 'SIS-Leg · Pantalla del Recinto' },
  { nombre: 'tecnico', rutaBase: '/tecnico/', titulo: 'SIS-Leg · Apoyo Técnico' },
  { nombre: 'simulador', rutaBase: '/simulador/', titulo: 'SIS-Leg · Simulador de Dispositivos' },
] as const

/**
 * Archivos de marca aprobados por HUMAN_GATE, con el SHA-256 que declara
 * `assets/branding/README.md`. El isotipo viene de WP-062; el logo completo lo reemplazó
 * WP-069 a partir de una entrega humana posterior.
 *
 * Fijar el hash acá no es ceremonia: durante WP-062 el PNG del logo llegó al repositorio
 * con un byte alterado en el CRC de su cabecera. Servía por HTTP y el archivo «se veía»
 * bien en cualquier visor tolerante, pero Chromium rechazaba decodificarlo y la imagen
 * quedaba vacía en pantalla. Comparar contra el hash documentado convierte ese fallo
 * silencioso en una prueba roja.
 */
const ARCHIVOS_MARCA = [
  {
    nombre: 'sisleg-logo.png',
    sha256: '72a025cab597d5ce54cf048c39800de3c647a3d7ab9846fa458b63f81192eff7',
    ancho: 1536,
    alto: 1024,
    // 6 = RGBA con canal alfa completo, que es lo que exige un logo sin fondo.
    tipoColor: 6,
  },
  {
    nombre: 'sisleg-isotipo.png',
    sha256: 'cd26723bc3fa2016816a4a1ebc0684b987b15219a7ef4ebe6bdd406fd0cc7540',
    ancho: 256,
    alto: 250,
    // 3 = color indexado por paleta, con la transparencia en el bloque `tRNS`. Es como
    // llegó el isotipo en WP-062 y este WP no lo toca.
    tipoColor: 3,
  },
] as const

/**
 * Lee del bloque `IHDR` de un PNG lo que declara sobre sí mismo.
 *
 * `IHDR` es siempre el primer bloque y ocupa trece bytes con un orden fijo: ancho, alto,
 * profundidad de bits, tipo de color, método de compresión, método de filtrado y
 * entrelazado. Leerlo alcanza para comprobar que el archivo versionado sigue siendo el
 * lienzo aprobado y no una versión reescalada o convertida a otro modo de color, sin tener
 * que descomprimir la imagen.
 */
function leerCabeceraPng(png: Buffer) {
  return {
    ancho: png.readUInt32BE(16),
    alto: png.readUInt32BE(20),
    profundidad: png[24],
    tipoColor: png[25],
    entrelazado: png[28],
  }
}

/**
 * Recorre los chunks de un PNG y devuelve los que tienen el CRC mal calculado.
 *
 * Un PNG es una firma de ocho bytes seguida de bloques con la forma
 * `longitud | tipo | contenido | CRC32(tipo + contenido)`. Los navegadores verifican al
 * menos el CRC de la cabecera `IHDR` y descartan la imagen entera si no coincide, que es
 * exactamente lo que ocurrió con el logo original. Recalcular los CRC es, por lo tanto,
 * la comprobación que distingue «el archivo llegó» de «el archivo se puede mostrar».
 */
function chunksConCrcInvalido(png: Buffer): string[] {
  const invalidos: string[] = []
  let posicion = 8
  while (posicion + 12 <= png.length) {
    const longitud = png.readUInt32BE(posicion)
    const tipo = png.subarray(posicion + 4, posicion + 8)
    const contenido = png.subarray(posicion + 8, posicion + 8 + longitud)
    const crcDeclarado = png.readUInt32BE(posicion + 8 + longitud)
    if (crc32(Buffer.concat([tipo, contenido])) !== crcDeclarado) {
      invalidos.push(tipo.toString('latin1'))
    }
    posicion += 12 + longitud
    if (tipo.toString('latin1') === 'IEND') break
  }
  return invalidos
}

/** CRC-32 estándar (polinomio 0xEDB88320), el mismo que exige el formato PNG. */
function crc32(datos: Buffer): number {
  let resto = 0xffffffff
  for (const byte of datos) {
    resto ^= byte
    for (let bit = 0; bit < 8; bit += 1) {
      resto = resto & 1 ? (resto >>> 1) ^ 0xedb88320 : resto >>> 1
    }
  }
  return (resto ^ 0xffffffff) >>> 0
}

describe('Integridad de los archivos de marca canónicos', () => {
  for (const archivo of ARCHIVOS_MARCA) {
    const png = readFileSync(join(raiz, 'assets', 'branding', archivo.nombre))

    it(`${archivo.nombre} coincide con el SHA-256 documentado`, () => {
      expect(createHash('sha256').update(png).digest('hex')).toBe(archivo.sha256)
    })

    it(`${archivo.nombre} es un PNG decodificable por un navegador`, () => {
      expect(png.subarray(0, 8).toString('latin1')).toBe('\x89PNG\r\n\x1a\n')
      expect(chunksConCrcInvalido(png)).toEqual([])
    })

    it(`${archivo.nombre} conserva el lienzo y el modo de color aprobados`, () => {
      // WP-069 prohíbe recortar y redimensionar el logo: el lienzo declarado es parte del
      // asset aprobado, no un detalle de compresión. `entrelazado` 0 es el formato
      // progresivo por líneas que esperan los navegadores.
      expect(leerCabeceraPng(png)).toEqual({
        ancho: archivo.ancho,
        alto: archivo.alto,
        profundidad: 8,
        tipoColor: archivo.tipoColor,
        entrelazado: 0,
      })
    })
  }
})

describe('Assets de marca copiados a cada SPA', () => {
  for (const archivo of ARCHIVOS_MARCA) {
    for (const aplicacion of APLICACIONES) {
      it(`${aplicacion.nombre} sirve una copia idéntica de ${archivo.nombre}`, () => {
        const canonico = readFileSync(join(raiz, 'assets', 'branding', archivo.nombre))
        const publicado = readFileSync(
          join(raiz, 'apps', aplicacion.nombre, 'public', 'assets', 'marca', archivo.nombre),
        )

        // `equals` compara los bytes: cualquier reprocesamiento del PNG —otro recorte,
        // otra compresión, otro color— produciría un archivo distinto y fallaría acá.
        expect(publicado.equals(canonico)).toBe(true)
      })
    }
  }
})

describe('Indicador de carga previo a la hidratación', () => {
  const carga = readFileSync(
    join(raiz, 'packages', 'frontend-shared', 'src', 'carga_inicial.html'),
    'utf8',
  )

  it('muestra el logo completo con una ruta relativa al prefijo de cada aplicación', () => {
    expect(carga).toContain('src="assets/marca/sisleg-logo.png"')

    // Una ruta absoluta rompería tres de las cuatro aplicaciones, porque este mismo
    // archivo se incrusta en las cuatro y cada una vive bajo su propio prefijo.
    expect(carga).not.toContain('src="/assets/marca/sisleg-logo.png"')
  })

  it('no repite el nombre del producto como texto junto al logo', () => {
    // El nombre accesible lo aporta el contenedor; la imagen va con `alt` vacío para que
    // un lector de pantalla no anuncie la marca dos veces.
    expect(carga).toContain('aria-label="Cargando la interfaz de SIS-Leg"')
    expect(carga).toContain('alt=""')
    expect(carga).not.toContain('>SIS-Leg<')
  })

  it('ya no presenta «Botonera2» como marca visible', () => {
    // La palabra sobrevive solamente dentro del comentario que explica el cambio, así que
    // se comprueba sobre el cuerpo del documento y no sobre el archivo completo.
    const cuerpo = carga.replace(/<!--[\s\S]*?-->/g, '')
    expect(cuerpo).not.toContain('Botonera2')
  })
})

describe('Metadatos visibles de las cuatro SPA', () => {
  for (const aplicacion of APLICACIONES) {
    const configuracion = readFileSync(
      join(raiz, 'apps', aplicacion.nombre, 'nuxt.config.ts'),
      'utf8',
    )

    it(`${aplicacion.nombre} declara el título con la marca SIS-Leg`, () => {
      expect(configuracion).toContain(`title: '${aplicacion.titulo}'`)
    })

    it(`${aplicacion.nombre} declara el favicon bajo su propio prefijo público`, () => {
      expect(configuracion).toContain(`const rutaBase = '${aplicacion.rutaBase}'`)
      expect(configuracion).toContain('href: `${rutaBase}assets/marca/sisleg-isotipo.png`')
    })
  }
})
