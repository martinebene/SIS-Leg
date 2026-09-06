import tailwindcss from '@tailwindcss/vite'

const shaConstruccion = process.env.SIS_LEG_SHA_CONSTRUCCION
const instanteConstruccion = Number(process.env.SIS_LEG_INSTANTE_CONSTRUCCION ?? Date.now())
const patronInstantePrerender = /(\[\{"prerenderedAt":\d+,"serverRendered":\d+\},)\d+(,false\])/g
/**
 * Prefijo público de la aplicación (WP-062).
 *
 * Antes estaba escrito directamente en `app.baseURL`. Ahora se declara una sola vez
 * porque el favicon lo necesita también: Nuxt no antepone el `baseURL` a los `href` de
 * `app.head.link`, así que la ruta del icono debe construirse con el mismo prefijo o el
 * navegador lo buscaría en la raíz del servidor, donde no existe.
 */
const rutaBase = '/simulador/'

export default defineNuxtConfig({
  // El simulador comparte la estrategia de despliegue estático como SPA independiente.
  // En producción Nginx servirá los archivos estáticos y no existirá un proceso Node runtime.
  ssr: false,
  // El lanzador productivo usa el SHA Git exacto para garantizar compilaciones reproducibles.
  buildId: shaConstruccion,
  // Indicador de carga inicial compartido (WP-061). Nuxt incrusta este archivo dentro
  // del `index.html` generado, de modo que la pantalla muestre fondo institucional y una
  // barra indeterminada desde antes de que exista el árbol de Vue. La ruta es relativa a
  // `srcDir` (`app/`) y apunta al único archivo común de las cuatro SPA.
  spaLoadingTemplate: '../../../packages/frontend-shared/src/carga_inicial.html',
  experimental: {
    // Sin app manifest no se generan UUIDs/timestamps volátiles ni polling en el cliente.
    appManifest: false,
  },
  app: {
    // Prefijo canónico de la subruta del simulador bajo el contrato de mismo origen.
    // En desarrollo interactivo con `dev:stack:hot`, HMR se transporta sobre WebSocket
    // en la misma URL base y puerto unificado del proxy sin requerir configuración adicional.
    baseURL: rutaBase,
    // Identidad visible de la pestaña del navegador (WP-062). El título nombra al
    // producto —SIS-Leg— y a la pantalla concreta, porque el operador suele tener varias
    // superficies abiertas a la vez. El icono es el isotipo aprobado, servido desde
    // `public/assets/marca/` de esta misma aplicación.
    head: {
      title: 'SIS-Leg · Simulador de Dispositivos',
      link: [
        { rel: 'icon', type: 'image/png', href: `${rutaBase}assets/marca/sisleg-isotipo.png` },
      ],
    },
  },
  modules: ['@nuxt/eslint'],
  css: ['~/assets/css/principal.css'],
  typescript: {
    strict: true,
    typeCheck: true,
  },
  runtimeConfig: {
    public: {
      // URL base del backend. Cadena vacía por defecto para consumir /api/v1 bajo mismo origen.
      apiBaseUrl: '',
    },
  },
  vite: {
    plugins: [tailwindcss()],
  },
  nitro: {
    hooks: {
      /**
       * Reemplaza la hora de ejecución que Nuxt agrega al payload de cada SPA.
       * El hook oficial de Nitro actúa sobre el HTML generado antes de guardarlo,
       * fijando el instante del commit para garantizar reproducibilidad exacta byte a byte.
       */
      'prerender:generate'(ruta) {
        if (!ruta.contents?.includes('data-nuxt-data')) {
          return
        }

        const contenidoEstable = ruta.contents.replace(
          patronInstantePrerender,
          `$1${instanteConstruccion}$2`,
        )
        if (contenidoEstable === ruta.contents) {
          throw new Error(`No se pudo estabilizar la fecha de prerender de la ruta ${ruta.route}.`)
        }
        ruta.contents = contenidoEstable
      },
    },
  },
})
