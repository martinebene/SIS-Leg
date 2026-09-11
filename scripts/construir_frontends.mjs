/**
 * Construye las cinco SPA con una identidad estable derivada del commit actual.
 *
 * Nuxt genera por defecto un buildId aleatorio y una fecha de prerender actual.
 * Este lanzador obtiene una sola identidad Git y la entrega a todos los builds,
 * sin depender de sintaxis de shell para conservar compatibilidad con Windows.
 */

import { execFileSync } from 'node:child_process'
import process from 'node:process'

const PAQUETES_FRONTEND = [
  '@sis-leg/moderacion',
  '@sis-leg/recinto',
  '@sis-leg/simulador',
  '@sis-leg/tecnico',
  // El Zócalo para OBS (WP-099) es una SPA más del producto: se construye con la misma
  // identidad Git para que su salida entre en la release y en el manifiesto reproducible.
  '@sis-leg/zocalo',
]

/** Ejecuta una consulta Git de solo lectura y normaliza su salida. */
function ejecutarGit(argumentos) {
  return execFileSync('git', argumentos, {
    cwd: process.cwd(),
    encoding: 'utf8',
  }).trim()
}

/**
 * Ejecuta el script build de un workspace heredando la identidad reproducible.
 * execFileSync evita una shell intermedia y propaga cualquier fallo a pnpm.
 */
function construirPaquete(nombrePaquete, entorno) {
  const ejecutablePnpm = process.platform === 'win32' ? 'pnpm.cmd' : 'pnpm'
  execFileSync(ejecutablePnpm, ['--filter', nombrePaquete, 'build'], {
    cwd: process.cwd(),
    env: entorno,
    stdio: 'inherit',
  })
}

const shaConstruccion = ejecutarGit(['rev-parse', 'HEAD'])
const segundosCommit = ejecutarGit(['show', '--no-patch', '--format=%ct', 'HEAD'])
const instanteConstruccion = String(Number.parseInt(segundosCommit, 10) * 1000)

if (!/^[0-9a-f]{40}$/.test(shaConstruccion) || !/^\d+$/.test(instanteConstruccion)) {
  throw new Error('Git no devolvió una identidad de construcción válida.')
}

const entornoConstruccion = {
  ...process.env,
  SIS_LEG_SHA_CONSTRUCCION: shaConstruccion,
  SIS_LEG_INSTANTE_CONSTRUCCION: instanteConstruccion,
}

for (const nombrePaquete of PAQUETES_FRONTEND) {
  construirPaquete(nombrePaquete, entornoConstruccion)
}
