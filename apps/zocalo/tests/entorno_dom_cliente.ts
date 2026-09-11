/**
 * Entorno Vitest para apps/zocalo que compila SFC en modo cliente.
 *
 * Evita la compilación SSR en Node y garantiza que Vue Test Utils pueda montar los
 * componentes en el DOM simulado compartido.
 */

import { builtinEnvironments, type Environment } from 'vitest/runtime'

const entornoDomCliente: Environment = {
  ...builtinEnvironments.node,
  name: 'sis-leg-dom-cliente',
  viteEnvironment: 'client',
}

export default entornoDomCliente
