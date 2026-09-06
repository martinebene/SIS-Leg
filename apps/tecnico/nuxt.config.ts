import { fileURLToPath } from 'node:url'

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
const rutaBase = '/tecnico/'

export default defineNuxtConfig({
  // El puesto de Apoyo Técnico comparte la estrategia de despliegue estático del resto
  // de las SPA: en producción Nginx sirve archivos estáticos y no hay proceso Node runtime.
  // Se accede desde otro equipo de la LAN sin autenticación adicional (decisión WP-056),
  // así que su ruta no lleva la restricción a loopback del simulador de dispositivos.
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
    // Prefijo canónico de la subruta técnica bajo el contrato de mismo origen.
    // En desarrollo interactivo con `dev:stack:hot`, HMR se transporta sobre WebSocket
    // en la misma URL base y puerto unificado del proxy sin requerir configuración adicional.
    baseURL: rutaBase,
    // Identidad visible de la pestaña del navegador (WP-062). El título nombra al
    // producto —SIS-Leg— y a la pantalla concreta, porque el operador suele tener varias
    // superficies abiertas a la vez. El icono es el isotipo aprobado, servido desde
    // `public/assets/marca/` de esta misma aplicación.
    head: {
      title: 'SIS-Leg · Apoyo Técnico',
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
    /**
     * Sonidos del recinto servidos también por Apoyo Técnico (WP-071).
     *
     * Desde WP-071 este puesto reproduce los mismos quince eventos sonoros que la Pantalla
     * del Recinto, para poder alimentar la amplificación del salón desde el equipo técnico.
     * El backend proyecta rutas relativas —`assets/sonidos/sesion-abierta.wav`— y cada SPA
     * las resuelve contra su propio prefijo, así que Apoyo Técnico necesita esos archivos
     * publicados bajo `/tecnico/assets/sonidos/`.
     *
     * Se declaran acá como directorio público adicional en lugar de copiarlos a
     * `apps/tecnico/public/`. La diferencia importa: los WAV siguen versionados una sola
     * vez, en `apps/recinto/public/assets/sonidos/`, que es la raíz que valida
     * `validar_assets_sonidos` al desplegar y la que documenta `assets/sonidos/README.md`.
     * Una segunda copia en el repositorio podría quedar desactualizada sin que nada lo
     * notara; una copia hecha en cada construcción, no.
     */
    publicAssets: [
      {
        dir: fileURLToPath(new URL('../recinto/public/assets/sonidos', import.meta.url)),
        baseURL: '/assets/sonidos',
      },
    ],
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
