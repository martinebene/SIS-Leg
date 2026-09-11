import tailwindcss from '@tailwindcss/vite'

const shaConstruccion = process.env.SIS_LEG_SHA_CONSTRUCCION
const instanteConstruccion = Number(process.env.SIS_LEG_INSTANTE_CONSTRUCCION ?? Date.now())
const patronInstantePrerender = /(\[\{"prerenderedAt":\d+,"serverRendered":\d+\},)\d+(,false\])/g

/** Prefijo público de la aplicación, declarado una sola vez (WP-099). */
const rutaBase = '/zocalo/'

/**
 * Color de chroma del Zócalo.
 *
 * Se escribe también acá, y no sólo en la hoja de estilos, porque el HTML estático llega
 * al navegador antes que el CSS de la aplicación. Sin esta regla en línea, OBS mostraría
 * un frame blanco durante la descarga del bundle: el operador vería un destello que el
 * filtro de croma no puede recortar. Con ella, el primer pintado ya es verde uniforme.
 */
const colorChroma = '#00FF00'

export default defineNuxtConfig({
  // El Zócalo comparte la estrategia de despliegue estático del resto de las SPA: en
  // producción Nginx sirve archivos y no hay proceso Node en runtime. Es una superficie
  // pública de solo lectura, sin autenticación, pensada para abrirse como Browser Source
  // de OBS desde el equipo que produce la transmisión.
  ssr: false,
  // El lanzador productivo usa el SHA Git exacto para construcciones reproducibles.
  buildId: shaConstruccion,
  /*
    Nuxt DevTools apagado en esta SPA y sólo en esta.

    DevTools dibuja un panel flotante sobre la página durante el desarrollo. En cualquier
    otra superficie es una ayuda; acá es un objeto opaco encima del croma, que aparecería
    tanto en una Browser Source apuntada al servidor de desarrollo como en las capturas con
    las que se verifica el color del frame. Como el Zócalo no debe pintar nada más que el
    croma y su bloque, la herramienta se desactiva de raíz en lugar de tratarse como un
    falso positivo de las pruebas.
  */
  devtools: { enabled: false },
  /*
    A diferencia de las otras cuatro SPA, el Zócalo **no** usa el indicador de carga
    compartido de WP-061. Ese indicador pinta un fondo institucional oscuro con el logo y
    una barra animada: en una Browser Source eso aparecería sobre la transmisión como un
    rectángulo opaco que el filtro de croma no puede quitar. La superficie de fondo debe
    ser verde uniforme desde el primer frame y hasta el último, así que el hueco de carga
    se deja deliberadamente vacío sobre el color de croma.
  */
  experimental: {
    // Sin app manifest no se generan UUID/timestamps volátiles ni polling en el cliente.
    appManifest: false,
  },
  app: {
    // Prefijo canónico de la subruta pública bajo el contrato de mismo origen.
    baseURL: rutaBase,
    head: {
      // Identidad de la pestaña cuando alguien abre el Zócalo en un navegador normal para
      // verificarlo. OBS no muestra pestañas: no se declara favicon, y así se evita copiar
      // otra vez el isotipo dentro de una aplicación que nunca lo dibuja.
      title: 'SIS-Leg · Zócalo',
      style: [{ textContent: `html,body{margin:0;background:${colorChroma};}` }],
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
      // En producción el Zócalo y FastAPI comparten origen. Esta variable sólo permite
      // apuntar a otro backend durante desarrollo o pruebas manuales.
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
       * El hook oficial de Nitro actúa sobre el HTML ya generado, justo antes de
       * escribirlo, y usa la fecha estable del commit como equivalente.
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
