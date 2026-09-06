/**
 * Frontera reactiva entre el estado público y el motor de audio (WP-066), compartida por
 * las dos superficies que sonorizan el recinto (WP-071).
 *
 * ## Quién lo usa
 *
 * La Pantalla del Recinto, desde siempre, y desde WP-071 también el puesto de Apoyo
 * Técnico. El objetivo operativo de esa segunda superficie es poder tomar el audio del
 * salón desde el equipo técnico, así que la paridad debe ser exacta: mismos eventos, misma
 * configuración, mismo volumen y las mismas reglas de silencio.
 *
 * Esa exactitud se consigue **compartiendo este composable**, no replicándolo. Ambas
 * pantallas le entregan los mismos tres insumos —la instantánea sonora adoptada, el estado
 * de su conexión y el número visible de la cuenta regresiva— y obtienen por construcción el
 * mismo comportamiento.
 *
 * Desde WP-074 esa instantánea ya no es el mismo objeto en las dos pantallas: el Recinto
 * entrega su `EstadoRecinto` completo y Apoyo Técnico entrega la subproyección sonora que
 * viaja dentro de su propio estado, para no tener que abrir un segundo stream. Las dos
 * satisfacen `InstantaneaSonora`, así que la decisión de sonar sigue siendo una sola.
 *
 * ## Qué hace
 *
 * Observa dos cosas y nada más:
 *
 * 1. **cada estado adoptado por la sincronización**, para comparar el snapshot nuevo con el
 *    anterior y reproducir las transiciones detectadas;
 * 2. **el número visible de la cuenta regresiva hacia el vivo**, para acompañar con un tic
 *    cada cambio de segundo.
 *
 * ## La frontera entre «baseline» y «transición»
 *
 * Ésta es la decisión central del WP y conviene entenderla bien.
 *
 * El cliente de sincronización tiene dos formas de entregar un estado. Una es el **snapshot
 * REST**, que se pide al arrancar y cada vez que hay que recuperarse de una caída del
 * stream: describe todo lo que pasó hasta ese momento, incluido lo ocurrido mientras la
 * pantalla estaba desconectada. La otra son los **eventos SSE**, que llegan uno por
 * revisión mientras la conexión está viva: cada uno representa un hecho recién ocurrido.
 *
 * Sonorizar un snapshot sería reproducir historia: al abrir la pantalla en mitad de una
 * sesión sonarían de golpe la apertura, las presencias y la votación en curso. Por eso un
 * estado adoptado **fuera de una conexión establecida** se guarda como referencia y no
 * suena. Se reconoce sin adivinar nada: el cliente notifica la conexión abierta después de
 * adoptar su snapshot y la notifica cerrada antes de pedir el siguiente, así que
 * `estadoConexion === 'CONECTADO'` distingue con exactitud un evento SSE de una baseline.
 *
 * Ese mismo criterio cubre los tres casos que exige el WP: el primer snapshot, la recarga
 * de la página y cualquier reconexión, incluida la que ocurre después de reiniciar el
 * backend, cuando la revisión vuelve a empezar.
 *
 * ## Por qué los observadores son síncronos
 *
 * `flush: 'sync'` ejecuta la comparación en el mismo instante en que la referencia cambia.
 * Con el agrupado normal de Vue, dos revisiones que llegaran en el mismo tick se
 * fusionarían y la intermedia desaparecería: se perdería, por ejemplo, el pedido de palabra
 * que quedó entre dos revisiones. Acá cada revisión adoptada se compara una vez y sólo una.
 */

import { onScopeDispose, watch, type Ref } from 'vue'
import { crearMotorSonidos, type MotorSonidosRecinto } from './motor_sonidos'
import { detectarTransicionesSonoras, type InstantaneaSonora } from './transiciones_sonoras'

/**
 * Vocabulario de conexión que comparten las pantallas de SIS-Leg.
 *
 * Recinto y Apoyo Técnico ya declaraban cada uno esta misma unión para su propio
 * indicador. Acá se nombra una vez porque este composable sólo necesita distinguir
 * `CONECTADO` del resto: con el stream abierto, cada estado adoptado es un hecho nuevo;
 * sin él, es una baseline que no debe reproducir historia.
 */
export type EstadoConexionSuperficie = 'INICIAL' | 'CONECTADO' | 'RECONECTANDO' | 'DESCONECTADO'

/**
 * Insumos del composable, parametrizados por la instantánea que entrega cada pantalla.
 *
 * El parámetro genérico existe desde WP-074, cuando las dos superficies dejaron de mirar
 * el mismo DTO: la Pantalla del Recinto sigue pasando su `EstadoRecinto` y Apoyo Técnico
 * pasa la subproyección sonora que viaja dentro de su propio estado. Las dos satisfacen
 * `InstantaneaSonora`, que es lo único que la comparación necesita.
 *
 * Sin el genérico habría que declarar `Ref<InstantaneaSonora | null>` y TypeScript
 * rechazaría un `Ref<EstadoRecinto | null>`: una referencia es mutable y, por lo tanto,
 * invariante en su contenido, aunque el valor de adentro sí sea asignable.
 */
export interface OpcionesSonidosRecinto<T extends InstantaneaSonora = InstantaneaSonora> {
  /** Última instantánea adoptada por la superficie que sonoriza. */
  estado: Ref<T | null>
  /** Estado de la conexión SSE; es lo que separa una baseline de un hecho nuevo. */
  estadoConexion: Ref<EstadoConexionSuperficie>
  /**
   * Segundos visibles de la cuenta regresiva hacia el vivo, o `null` fuera de ella.
   *
   * Llega ya derivado por el reloj de presentación técnica, que avanza localmente entre
   * mensajes SSE. Por eso el tic no agrega ni una sola petición de red.
   */
  segundosCuentaRegresiva: Ref<number | null>
  /**
   * Convierte la ruta configurada por el backend en una URL servible por esta pantalla.
   *
   * Se pide siempre porque depende del `baseURL` de la aplicación. Sólo se usa cuando no
   * se inyecta un `motor` ya construido.
   */
  resolverUrl?: (ruta: string) => string
  /** Motor inyectable; las pruebas pasan uno falso y producción usa el predeterminado. */
  motor?: MotorSonidosRecinto
}

export interface SonidosRecinto {
  /** El motor efectivamente utilizado, expuesto para inspección en pruebas. */
  motor: MotorSonidosRecinto
}

/**
 * Conecta el estado público con el motor de audio y devuelve el motor en uso.
 *
 * Efectos: registra dos observadores reactivos y libera el motor cuando muere el scope que
 * lo creó (el desmontaje de la pantalla). No modifica el estado ni emite comandos: la
 * sonorización es estrictamente de solo lectura en las dos superficies, y en Apoyo Técnico
 * no toca ninguno de los controles que esa pantalla sí puede accionar.
 */
export function useSonidosRecinto<T extends InstantaneaSonora>(
  opciones: OpcionesSonidosRecinto<T>,
): SonidosRecinto {
  const motor =
    opciones.motor ?? crearMotorSonidos({ resolverUrl: exigirResolutor(opciones.resolverUrl) })

  /** Último estado ya sonorizado; es el término de comparación de la próxima revisión. */
  let instantaneaPrevia: T | null = null
  /** Revisión de ese estado, usada como guarda de idempotencia. */
  let revisionPrevia: number | null = null

  watch(
    opciones.estado,
    (actual) => {
      if (actual === null) {
        instantaneaPrevia = null
        revisionPrevia = null
        return
      }

      // La configuración viaja en todos los snapshots, también en `SIN_PREPARAR`. Adoptarla
      // antes de reproducir permite que el primer sonido de una sesión ya encuentre su
      // archivo precargado.
      motor.configurar(actual.sonidos)

      const esBaseline = instantaneaPrevia === null || opciones.estadoConexion.value !== 'CONECTADO'
      // Dentro de una misma conexión la revisión sólo crece. Una revisión repetida es el
      // mismo estado entregado dos veces y no puede volver a sonar.
      const esRevisionRepetida = revisionPrevia !== null && actual.revision <= revisionPrevia

      if (instantaneaPrevia !== null && !esBaseline && !esRevisionRepetida) {
        for (const evento of detectarTransicionesSonoras(instantaneaPrevia, actual)) {
          motor.reproducir(evento)
        }
      }

      instantaneaPrevia = actual
      revisionPrevia = actual.revision
    },
    { immediate: true, flush: 'sync' },
  )

  /*
    El tic no se deduce de dos snapshots: el backend no emite una revisión por segundo y el
    WP prohíbe pedirle una. El número lo baja el reloj local, así que el tic acompaña
    exactamente al dígito que el público ve cambiar.

    Sin `immediate`, el primer valor observado no suena: adoptar un snapshot en mitad de una
    cuenta regresiva muestra el número, pero no es un cambio de segundo. Volver a `null`
    tampoco suena, porque el fin de la cuenta ya tiene su propio sonido de inicio de vivo.
  */
  watch(
    opciones.segundosCuentaRegresiva,
    (actual, previo) => {
      if (actual === null || previo === null || previo === undefined) return
      if (actual === previo) return
      motor.reproducir('transmision_cuenta_regresiva_tic')
    },
    { flush: 'sync' },
  )

  onScopeDispose(motor.liberar)

  return { motor }
}

/**
 * Exige el resolutor de URL cuando hay que construir el motor predeterminado.
 *
 * Sin motor inyectado, `resolverUrl` deja de ser opcional: un motor que no supiera armar
 * la URL reproduciría rutas relativas contra la raíz del servidor y fallaría en silencio,
 * que es exactamente el defecto difícil de detectar que WP-071 quiere evitar. Fallar acá,
 * al construir la pantalla, hace visible el error de cableado de inmediato.
 */
function exigirResolutor(
  resolverUrl: ((ruta: string) => string) | undefined,
): (ruta: string) => string {
  if (resolverUrl === undefined) {
    throw new Error(
      'useSonidosRecinto necesita `resolverUrl` para construir su motor predeterminado.',
    )
  }
  return resolverUrl
}
