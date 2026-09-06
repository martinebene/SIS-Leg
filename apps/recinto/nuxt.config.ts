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
const rutaBase = '/recinto/'

export default defineNuxtConfig({
  // Recinto comparte la estrategia de despliegue estático de Moderación, pero
  // conserva una aplicación separada para no mezclar responsabilidades.
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
    // Recinto tampoco usa route rules del lado cliente. Sin app manifest no se
    // generan UUID/timestamps ni se activa el polling de builds obsoletos.
    appManifest: false,
  },
  app: {
    // El build queda listo para que Nginx o el harness lo sirvan en la
    // subruta pública acordada, sin fijar un host absoluto.
    // En desarrollo interactivo con `dev:stack:hot`, Vite HMR se conecta automáticamente
    // al host y puerto de origen visible (@vite/client), atravesando el proxy unificado
    // y los túneles SSH de forma transparente.
    baseURL: rutaBase,
    // Identidad visible de la pestaña del navegador (WP-062). El título nombra al
    // producto —SIS-Leg— y a la pantalla concreta, porque el operador suele tener varias
    // superficies abiertas a la vez. El icono es el isotipo aprobado, servido desde
    // `public/assets/marca/` de esta misma aplicación.
    head: {
      title: 'SIS-Leg · Pantalla del Recinto',
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
      // En producción Recinto y FastAPI comparten origen. Esta variable solo
      // permite apuntar a otro backend durante desarrollo o pruebas manuales.
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
