/**
 * Pruebas de la resolución compartida de fotografías de banca (WP-098).
 *
 * Qué se demuestra acá
 * --------------------
 *
 * 1. una `ruta_imagen` válida se convierte en la URL del endpoint del backend,
 *    y no en una ruta del build de ninguna SPA;
 * 2. las cuatro superficies obtienen exactamente la misma URL, que es el
 *    objetivo central del WP: una sola fuente física;
 * 3. se rechazan path traversal, rutas absolutas y URLs externas con las mismas
 *    reglas que aplica el backend;
 * 4. ante una ruta inválida se devuelve cadena vacía en vez de lanzar, para que
 *    la tarjeta muestre su fallback sin romper la pantalla completa.
 */

import { describe, expect, it } from 'vitest'
import {
  PREFIJO_RUTA_IMAGEN_CONCEJAL,
  RUTA_ENDPOINT_IMAGENES_CONCEJALES,
  nombreArchivoImagenConcejal,
  resolverUrlImagenConcejal,
} from '../src'

describe('Fuente única de fotografías de banca (WP-098)', () => {
  it('resuelve una ruta canónica contra el endpoint del backend', () => {
    expect(resolverUrlImagenConcejal('assets/bancas/banca-01.png')).toBe(
      '/api/v1/recursos/imagenes-concejales/banca-01.png',
    )
  })

  it('no resuelve contra el prefijo público de ninguna SPA', () => {
    const url = resolverUrlImagenConcejal('assets/bancas/banca-01.png')

    // Antes de WP-098 la URL era `/moderacion/assets/bancas/...` o
    // `/recinto/assets/bancas/...`, es decir un archivo del build.
    expect(url.startsWith(RUTA_ENDPOINT_IMAGENES_CONCEJALES)).toBe(true)
    expect(url).not.toContain('/moderacion/')
    expect(url).not.toContain('/recinto/')
  })

  it('antepone la URL base del backend cuando la API vive en otro origen', () => {
    // En producción la base es cadena vacía porque SPA y API comparten origen;
    // en desarrollo puede apuntarse a otro host con NUXT_PUBLIC_API_BASE_URL.
    expect(resolverUrlImagenConcejal('assets/bancas/banca-01.png', 'http://127.0.0.1:8000')).toBe(
      'http://127.0.0.1:8000/api/v1/recursos/imagenes-concejales/banca-01.png',
    )
    expect(resolverUrlImagenConcejal('assets/bancas/banca-01.png', 'http://127.0.0.1:8000/')).toBe(
      'http://127.0.0.1:8000/api/v1/recursos/imagenes-concejales/banca-01.png',
    )
  })

  it('da exactamente la misma URL a todas las superficies', () => {
    const ruta = 'assets/bancas/banca-07.png'
    const urls = new Set([
      resolverUrlImagenConcejal(ruta),
      resolverUrlImagenConcejal(ruta),
      resolverUrlImagenConcejal(ruta, ''),
    ])

    expect(urls.size).toBe(1)
  })

  it('codifica un nombre de archivo con espacios o acentos', () => {
    // El padrón lo escribe una persona: un nombre así es legítimo y la URL
    // tiene que seguir apuntando al mismo archivo.
    expect(resolverUrlImagenConcejal(`${PREFIJO_RUTA_IMAGEN_CONCEJAL}Perez Nuñez.png`)).toBe(
      '/api/v1/recursos/imagenes-concejales/Perez%20Nu%C3%B1ez.png',
    )
  })

  it('admite las mismas extensiones que el backend, sin distinguir mayúsculas', () => {
    for (const extension of ['.png', '.jpg', '.jpeg', '.webp', '.PNG']) {
      expect(nombreArchivoImagenConcejal(`assets/bancas/retrato${extension}`)).not.toBe(null)
    }
  })

  describe('rechazo de rutas inseguras', () => {
    const rutasInvalidas = [
      // Path traversal
      'assets/bancas/../../../etc/passwd',
      'assets/bancas/..',
      'assets/bancas/subdirectorio/banca-01.png',
      '../../etc/passwd',
      // Rutas absolutas
      '/etc/passwd',
      '/assets/bancas/banca-01.png',
      '//servidor/recurso.png',
      // URLs externas
      'http://ejemplo.invalid/banca-01.png',
      'https://ejemplo.invalid/banca-01.png',
      'ftp://ejemplo.invalid/banca-01.png',
      'data:image/png;base64,AAAA',
      // Separadores de Windows
      'assets\\bancas\\banca-01.png',
      // Fuera del prefijo, oculto o con extensión no admitida
      'assets/sonidos/sesion-abierta.wav',
      'banca-01.png',
      'assets/bancas/',
      'assets/bancas/.oculto.png',
      'assets/bancas/banca-01.svg',
      'assets/bancas/banca-01',
      '',
    ]

    it.each(rutasInvalidas)('rechaza %j sin lanzar excepción', (ruta) => {
      expect(nombreArchivoImagenConcejal(ruta)).toBe(null)
      // Cadena vacía y no una excepción: la tarjeta dibuja sus iniciales y la
      // pantalla completa sigue funcionando.
      expect(resolverUrlImagenConcejal(ruta)).toBe('')
    })
  })
})
