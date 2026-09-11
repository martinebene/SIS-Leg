import { defineConfig, devices } from '@playwright/test'

/** Configuración E2E de los frontends estáticos del monorepo. */
export default defineConfig({
  testDir: './tests/playwright',
  timeout: 30000,
  expect: {
    timeout: 10000,
  },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: 'http://localhost:3000',
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        launchOptions: {
          /*
            Política de autoplay del recinto (WP-066).

            La Pantalla del Recinto reproduce sonidos sin que nadie toque el monitor: no hay
            teclado ni mouse frente a la proyección. Chromium, por defecto, exige una
            interacción previa antes de dejar sonar audio, y HUMAN_GATE descartó agregar un
            botón «Activar sonido» para conseguirla.

            La bandera declara acá la misma condición que el equipo de producción debe
            cumplir, documentada en `docs/13-despliegue-y-operacion.md`. No cambia el
            comportamiento de ninguna otra prueba: las demás superficies no reproducen audio.
          */
          args: ['--autoplay-policy=no-user-gesture-required'],
        },
      },
    },
  ],
  webServer: [
    {
      command: 'pnpm --filter @sis-leg/moderacion dev --port 3000',
      url: 'http://localhost:3000/moderacion/',
      reuseExistingServer: !process.env.CI,
      timeout: 120 * 1000,
    },
    {
      command: 'pnpm --filter @sis-leg/recinto dev --port 3001',
      url: 'http://localhost:3001/recinto/',
      reuseExistingServer: !process.env.CI,
      timeout: 120 * 1000,
    },
    {
      command: 'pnpm --filter @sis-leg/simulador dev --port 3002',
      url: 'http://localhost:3002/simulador/',
      reuseExistingServer: !process.env.CI,
      timeout: 120 * 1000,
    },
    {
      command: 'pnpm --filter @sis-leg/tecnico dev --port 3003',
      url: 'http://localhost:3003/tecnico/',
      reuseExistingServer: !process.env.CI,
      timeout: 120 * 1000,
    },
    {
      // Zócalo para OBS (WP-099). Sus pruebas miden geometría y color reales, así que
      // necesitan la superficie servida como cualquier otra SPA.
      command: 'pnpm --filter @sis-leg/zocalo dev --port 3004',
      url: 'http://localhost:3004/zocalo/',
      reuseExistingServer: !process.env.CI,
      timeout: 120 * 1000,
    },
  ],
})
