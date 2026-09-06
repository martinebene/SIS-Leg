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
const rutaBase = '/moderacion/'

export default defineNuxtConfig({
  // Estas opciones fuerzan una SPA generable como archivos estáticos. En
  // producción Nginx servirá el resultado y no habrá un proceso Node/Nitro.
  ssr: false,
  // El lanzador productivo usa el SHA Git exacto. Nuxt acepta oficialmente un
  // hash del estado del proyecto como buildId; en desarrollo conserva su valor
  // automático porque la variable sólo existe durante el build raíz.
  buildId: shaConstruccion,
  // Indicador de carga inicial compartido (WP-061). Nuxt incrusta este archivo dentro
  // del `index.html` generado, de modo que la pantalla muestre fondo institucional y una
  // barra indeterminada desde antes de que exista el árbol de Vue. La ruta es relativa a
  // `srcDir` (`app/`) y apunta al único archivo común de las cuatro SPA.
  spaLoadingTemplate: '../../../packages/frontend-shared/src/carga_inicial.html',
  experimental: {
    // Estas SPA no usan route rules del lado cliente. Omitir el app manifest
    // evita UUID/timestamps volátiles y también su polling de builds obsoletos.
    appManifest: false,
  },
  app: {
    // El prefijo forma parte del contrato de mismo origen. Nuxt lo incorpora
    // tanto a las rutas de la aplicación como a las URLs de sus assets.
    // En desarrollo con `dev:stack:hot`, el cliente de Vite (@vite/client) deriva
    // automáticamente la conexión WebSocket HMR desde la URL de origen (import.meta.url),
    // permitiendo que el hot reload funcione a través del puerto único del reverse proxy
    // y de túneles SSH sin hardcodear puertos internos.
    baseURL: rutaBase,
    // Identidad visible de la pestaña del navegador (WP-062). El título nombra al
    // producto —SIS-Leg— y a la pantalla concreta, porque el operador suele tener varias
    // superficies abiertas a la vez. El icono es el isotipo aprobado, servido desde
    // `public/assets/marca/` de esta misma aplicación.
    head: {
      title: 'SIS-Leg · Moderación',
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
      // URL base del backend. Por defecto cadena vacía para conservar el contrato de mismo origen
      // en producción (ej. /api/v1). En desarrollo puede sobreescribirse mediante NUXT_PUBLIC_API_BASE_URL.
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
       * El hook oficial de Nitro actúa sobre el HTML ya generado, justo antes
       * de escribirlo, y usa la fecha estable del commit como equivalente.
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
