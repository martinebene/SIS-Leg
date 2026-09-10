"""Servicio de dominio del plano técnico de Apoyo Técnico (WP-055).

Concentra los comandos que puede ejecutar el futuro puesto técnico:

- iniciar la transmisión de inmediato o con cuenta regresiva, y detenerla;
- publicar y cancelar avisos hacia Moderación, Recinto o ambos;
- administrar (alta, edición, baja) la biblioteca CSV de mensajes precargados.

Todas las mutaciones pasan por el ``EjecutorMutaciones`` único del proceso
(DT-004): dos comandos concurrentes se ordenan uno detrás del otro y ningún
observador puede ver una transición a mitad de camino. Al salir del lock, el
ejecutor publica una revisión nueva y REST/SSE reconstruyen el DTO completo.

Independencia del ciclo preparación/sesión
------------------------------------------

El plano técnico funciona en los tres estados globales, incluido
``SIN_PREPARAR``: Apoyo Técnico puede encender el indicador de transmisión
antes de que Moderación prepare el recinto. Por eso ningún comando de este módulo
exige un contexto operativo.

Auditoría
---------

Cuando existe una preparación/sesión activa, las órdenes de transmisión y de
aviso son interacciones operativas relevantes y se registran en los tres CSV
jerárquicos con nivel ``L2``, antes de mutar la memoria. Si el escritor no
puede garantizar la persistencia, la excepción se propaga y el comando **no**
se aplica: es el mismo fallo cerrado que usa el resto del backend.

En ``SIN_PREPARAR`` no existe un conjunto de auditoría abierto —ese es
justamente el invariante del proyecto— y la orden se aplica sin registrar.

La biblioteca de mensajes precargados no se audita: es mantenimiento de
configuración, del mismo orden que editar ``config/concejales.csv``, y no una
interacción del transcurso de la sesión. Su rastro durable es el propio CSV.

El estado visible de la cuenta regresiva sigue derivándose del reloj. Desde
WP-092, al alcanzar ``EN VIVO`` el temporizador registra además un hecho L2 y
marca esa intención como procesada, sin cambiar el contrato proyectado.

Transmisión en el log principal (WP-096)
----------------------------------------

Los hechos técnicos ``L2`` de WP-092 se conservan sin cambios, pero el panel de
eventos muestra por omisión el nivel "Principales (L3)": la operación no veía
allí cuándo empezó ni cuándo terminó la transmisión. Por eso cada transición
**efectiva** agrega ahora, además del hecho técnico, un único evento principal
``L3`` con etiqueta ``EVENTO``:

- ``TRANSMISION_EN_VIVO_INICIADA`` cuando el indicador pasa realmente a EN VIVO;
- ``TRANSMISION_EN_VIVO_FINALIZADA`` cuando deja realmente de estarlo.

Los dos eventos cuelgan de las mismas costuras que WP-092 dejó como únicas
autoridades del cambio efectivo de estado,
:meth:`ServicioApoyoTecnico._auditar_inicio_transmision` y
:meth:`ServicioApoyoTecnico._cerrar_transmision_en_vivo`. Programar o cancelar
una cuenta regresiva no pasa por ninguna de las dos, así que una intención que
nunca llegó a EN VIVO no puede producir un evento principal.

Pero el "exactamente uno por transición real" no se puede deducir de esas
costuras solas, porque ellas siguen la vida de la **intención** técnica y el log
principal sigue la del **indicador**. Reemplazar un EN VIVO por un inicio
inmediato cierra una intención y abre otra sin que el indicador se apague nunca:
para WP-092 son dos hechos técnicos, para WP-096 no ocurrió ninguna transición.
Por eso la autoridad institucional es
``EstadoOperativo.marcador_transmision_principal``, que se instala recién después
de persistir el ``INICIO`` y se retira recién después de persistir el ``FIN``,
tal como WP-078 hizo con los avisos del Recinto:

- ``_abrir_marcador_transmision`` no reabre un período ya abierto, de modo que un
  start repetido o un reemplazo con continuidad no duplican el ``INICIO``;
- ``_cerrar_transmision_en_vivo`` recibe ``continuidad=True`` cuando la misma
  mutación va a dejar el indicador encendido, y entonces no cierra el período.

Un ``FIN`` cuyo escritor ya no es el vigente no se escribe en otro conjunto de
CSV: la transmisión sobrevive al ciclo preparación/sesión y su cierre pertenece
al conjunto que vio su ``INICIO``.

Marcadores de sesión INICIO/FIN (WP-078)
----------------------------------------

Además de esa auditoría técnica ``L2``, un aviso que **alcanza la Pantalla del
Recinto** delimita un momento de la sesión y por eso genera dos eventos
principales ``L3`` con etiqueta general ``EVENTO``:

- ``INICIO`` cuando el texto aparece en Recinto;
- ``FIN`` cuando deja de mostrarse, con exactamente el mismo texto.

Un aviso dirigido sólo a ``MODERACION`` nunca genera estos marcadores, y un
aviso ``AMBOS`` genera una única pareja, la de su presencia en Recinto.

La pieza que hace verificable "un INICIO y un FIN por período" es
``EstadoOperativo.marcador_recinto_abierto``: se instala recién después de que
el ``INICIO`` quedó persistido y se retira recién después de persistir el
``FIN``. Nunca se decide leyendo el texto del aviso ni comparando mensajes de
auditoría, como exige el WP.

El cierre puede llegar por cuatro caminos, y los cuatro pasan por el mismo
helper privado, así que ninguno puede duplicar el ``FIN``:

1. cancelación manual que alcanza la ranura Recinto;
2. reemplazo por otro aviso que alcanza Recinto (``FIN`` del anterior antes del
   ``INICIO`` del nuevo, dentro de la misma mutación);
3. vencimiento por duración, que el temporizador de fronteras convierte en un
   hecho institucional durable llamando a
   :meth:`ServicioApoyoTecnico.cerrar_marcadores_recinto_vencidos`;
4. una cancelación posterior a cualquiera de los anteriores, que ya no encuentra
   período abierto y por lo tanto no escribe nada.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sis_leg_backend.auditoria import NivelAuditoria
from sis_leg_backend.configuracion.errores import ErrorMensajesTecnicosInvalido
from sis_leg_backend.configuracion.mensajes_tecnicos import (
    cargar_mensajes_tecnicos,
    guardar_mensajes_tecnicos,
)
from sis_leg_backend.dominio.apoyo_tecnico import (
    AvisoTecnico,
    BibliotecaMensajesTecnicos,
    DestinoAvisoTecnico,
    ErrorBibliotecaMensajesNoDisponible,
    ErrorMensajeTecnicoNoExistente,
    EstadoTransmision,
    MarcadorRecintoAbierto,
    MarcadorTransmisionPrincipal,
    MensajeTecnico,
    TransmisionTecnica,
    estado_transmision,
)
from sis_leg_backend.dominio.estado import EstadoOperativo
from sis_leg_backend.servicios.serializacion import EjecutorMutaciones

# Ruta canónica de la biblioteca. Vive en su propio subdirectorio porque el
# backend necesita permiso de escritura sobre el directorio para reemplazar el
# archivo de manera atómica, y ``config/`` es de solo lectura para el servicio.
# Es exactamente el mismo motivo por el que el device-bridge administra
# ``config/bridge/`` en lugar de escribir dentro de ``config/``.
RUTA_MENSAJES_TECNICOS_POR_DEFECTO = Path("config/apoyo-tecnico/mensajes.csv")

# Código estable que se publica en la proyección cuando el CSV existe pero no
# pudo interpretarse. La interfaz técnica puede así explicar el problema sin
# leer textos variables.
MOTIVO_BIBLIOTECA_INVALIDA = "BIBLIOTECA_MENSAJES_INVALIDA"

# Datos canónicos de los eventos de auditoría del plano técnico.
ETIQUETA_APOYO_TECNICO = "APOYO_TECNICO"
CODIGO_TRANSMISION_INICIADA = "TRANSMISION_INICIADA"
CODIGO_TRANSMISION_DETENIDA = "TRANSMISION_DETENIDA"
CODIGO_TRANSMISION_EN_VIVO_INICIO = "TRANSMISION_EN_VIVO_INICIO"
CODIGO_TRANSMISION_EN_VIVO_FIN = "TRANSMISION_EN_VIVO_FIN"
CODIGO_AVISO_PUBLICADO = "AVISO_TECNICO_PUBLICADO"
CODIGO_AVISO_CANCELADO = "AVISO_TECNICO_CANCELADO"

# Datos canónicos de los marcadores de sesión de WP-078.
#
# La etiqueta es deliberadamente ``EVENTO`` y no ``APOYO_TECNICO``: la decisión
# humana del WP es que estos registros representan **momentos generales de la
# sesión** —"acá empezó el cuarto intermedio", "acá terminó"— y no una acción
# técnica del operador. Quien lea el CSV institucional no debe encontrarlos
# clasificados como mensajería del puesto técnico.
ETIQUETA_EVENTO_PRINCIPAL = "EVENTO"
CODIGO_MARCADOR_INICIO = "INICIO"
CODIGO_MARCADOR_FIN = "FIN"

# Datos canónicos de los eventos principales de transmisión (WP-096).
#
# Comparten la etiqueta general ``EVENTO`` con los marcadores de WP-078 porque
# son exactamente la misma clase de registro: un momento general de la sesión
# que la operación necesita ver en el nivel "Principales (L3)" del panel de
# eventos, junto a la apertura de sesión o al resultado de una votación.
#
# El ``event_code`` es distinto del que usan los hechos técnicos L2
# ``TRANSMISION_EN_VIVO_INICIO`` / ``TRANSMISION_EN_VIVO_FIN`` de WP-092, y
# también distinto de ``INICIO`` / ``FIN`` de los avisos. Esa separación es
# deliberada: quien filtra el CSV por ``event_code`` debe poder distinguir sin
# ambigüedad el hecho institucional de transmisión del hecho técnico homónimo y
# del marcador de un aviso cuyo texto podría casualmente hablar de transmisión.
CODIGO_TRANSMISION_PRINCIPAL_INICIO = "TRANSMISION_EN_VIVO_INICIADA"
CODIGO_TRANSMISION_PRINCIPAL_FIN = "TRANSMISION_EN_VIVO_FINALIZADA"

# Los mensajes principales son frases fijas y legibles, sin metadata técnica.
# El log institucional (y el acta que se deriva de él) no debe contener horas
# internas, banderas ni identificadores: la hora la aporta la columna
# ``timestamp`` que escribe el propio escritor, que es la misma fuente temporal
# autoritativa que usan los demás eventos institucionales.
MENSAJE_TRANSMISION_PRINCIPAL_INICIO = "Transmisión en vivo iniciada"
MENSAJE_TRANSMISION_PRINCIPAL_FIN = "Transmisión en vivo finalizada"


def leer_biblioteca_mensajes_tecnicos(ruta: Path) -> BibliotecaMensajesTecnicos:
    """Carga la biblioteca al arrancar sin poder impedir el arranque.

    Un CSV inválido no debe dejar al backend sin votaciones, presencia ni
    auditoría: se degrada solamente la funcionalidad afectada. Por eso el error
    se traduce en una biblioteca ``disponible=False`` que la proyección publica
    y que rechaza cualquier escritura posterior, en vez de propagarse.

    Entradas:
        ruta: ubicación del CSV de mensajes precargados.

    Resultado:
        La biblioteca vigente. Vacía y disponible si el archivo no existe;
        vacía y no disponible si existe pero no pudo interpretarse.
    """

    try:
        mensajes = cargar_mensajes_tecnicos(ruta)
    except ErrorMensajesTecnicosInvalido as error:
        return BibliotecaMensajesTecnicos(
            mensajes=(),
            disponible=False,
            motivo=MOTIVO_BIBLIOTECA_INVALIDA,
            detalle=str(error),
        )
    return BibliotecaMensajesTecnicos(mensajes=mensajes)


class ServicioApoyoTecnico:
    """Ejecuta los comandos del plano técnico sobre el estado único.

    Igual que los demás servicios del backend, no guarda estado propio:
    recibe el ``EstadoOperativo`` y el ``EjecutorMutaciones`` compartidos, de
    modo que construir una instancia por request es seguro.

    La ruta del CSV, el reloj y el generador de identificadores se inyectan
    para que las pruebas controlen disco, tiempo e identidad sin depender del
    entorno real.
    """

    def __init__(
        self,
        estado_operativo: EstadoOperativo,
        ejecutor_mutaciones: EjecutorMutaciones,
        *,
        ruta_mensajes: Path = RUTA_MENSAJES_TECNICOS_POR_DEFECTO,
        reloj: Callable[[], datetime] = datetime.now,
        generar_identificador: Callable[[], str] = lambda: uuid4().hex,
    ) -> None:
        self._estado = estado_operativo
        self._ejecutor = ejecutor_mutaciones
        self._ruta_mensajes = ruta_mensajes
        self._reloj = reloj
        self._generar_identificador = generar_identificador

    # =========================================================================
    # 1. Transmisión
    # =========================================================================

    async def iniciar_transmision(self, cuenta_regresiva_segundos: int | None) -> None:
        """Instala la intención de transmitir, inmediata o con cuenta regresiva.

        Entradas:
            cuenta_regresiva_segundos: segundos de cuenta regresiva, o ``None``
                para pasar a ``EN VIVO`` de inmediato. La capa de API ya validó
                que sea un entero estricto dentro de los límites del contrato.

        Efectos:
            Reemplaza cualquier transmisión vigente. Reemplazar (en lugar de
            rechazar con un conflicto) es deliberado: durante una transmisión
            en vivo, corregir una cuenta regresiva mal cargada no debería
            obligar a apagar el indicador delante del público. La orden es
            siempre explícita y humana, así que no puede producirse sola.

            Si la intención anterior ya estaba efectivamente ``EN_VIVO``,
            cierra ese período antes de instalar la nueva. Un inicio inmediato
            registra además su ``INICIO`` efectivo en esta misma mutación.

        Errores:
            ``ErrorAuditoria`` si existe una preparación/sesión activa y el
            evento ``TRANSMISION_INICIADA`` no pudo persistirse. En ese caso el
            estado no cambia.
        """

        async def aplicar() -> None:
            ahora = self._reloj()
            en_vivo_desde = (
                ahora
                if cuenta_regresiva_segundos is None
                else ahora + timedelta(seconds=cuenta_regresiva_segundos)
            )
            modo = "INMEDIATO" if cuenta_regresiva_segundos is None else "CUENTA_REGRESIVA"
            self._auditar(
                CODIGO_TRANSMISION_INICIADA,
                (
                    f"Transmisión iniciada modo={modo}; "
                    f"cuenta_regresiva_segundos={cuenta_regresiva_segundos}; "
                    f"en_vivo_desde={en_vivo_desde.isoformat()}"
                ),
            )
            # La orden nueva ya quedó durable. Antes de instalarla se cierra el
            # período anterior según el reloj autoritativo. El helper procesa
            # primero un INICIO que pudiera haber coincidido con esta carrera,
            # de modo que nunca aparezca un FIN huérfano ni duplicado.
            #
            # Un reemplazo por un inicio inmediato deja el indicador encendido
            # sin ningún intervalo apagado, así que se declara continuidad: el
            # hecho técnico L2 se registra igual y el período institucional de
            # WP-096 sigue abierto. Reemplazar por una cuenta regresiva sí apaga
            # el indicador, y por eso no la declara.
            self._cerrar_transmision_en_vivo(
                "REEMPLAZO",
                ahora,
                continuidad=cuenta_regresiva_segundos is None,
            )

            nueva_transmision = TransmisionTecnica(
                iniciada_en=ahora,
                en_vivo_desde=en_vivo_desde,
                cuenta_regresiva_segundos=cuenta_regresiva_segundos,
                inicio_en_vivo_procesado=False,
            )
            if cuenta_regresiva_segundos is None:
                # El cruce inmediato forma parte del mismo comando seguro. La
                # intención no se instala hasta que el fsync efectivo termina:
                # un fallo no puede proyectar EN VIVO sin el hecho requerido.
                self._auditar_inicio_transmision(nueva_transmision)
                nueva_transmision = replace(
                    nueva_transmision,
                    inicio_en_vivo_procesado=True,
                )
            self._estado.transmision_tecnica = nueva_transmision

        await self._ejecutor.ejecutar(aplicar)

    async def detener_transmision(self) -> None:
        """Vuelve el indicador a ``APAGADO``.

        Es idempotente: detener una transmisión ya apagada no falla ni escribe
        un evento de auditoría, porque no hubo ningún cambio institucional que
        registrar. Esto evita que un reintento de red duplique filas del CSV.
        """

        async def aplicar() -> None:
            if self._estado.transmision_tecnica is None:
                return
            self._auditar(CODIGO_TRANSMISION_DETENIDA, "Transmisión detenida por orden manual")
            self._cerrar_transmision_en_vivo("DETENCION_MANUAL", self._reloj())
            self._estado.transmision_tecnica = None

        await self._ejecutor.ejecutar(aplicar)

    # =========================================================================
    # 2. Avisos técnicos
    # =========================================================================

    async def publicar_aviso(
        self,
        texto: str,
        destino: DestinoAvisoTecnico,
        duracion_segundos: int | None,
    ) -> None:
        """Publica un aviso en las ranuras que correspondan al destino.

        Entradas:
            texto: contenido ya validado por la capa de API.
            destino: ``MODERACION``, ``RECINTO`` o ``AMBOS``.
            duracion_segundos: vigencia en segundos, o ``None`` para que el
                aviso permanezca hasta la cancelación manual.

        Efectos:
            Cada destino alcanzado queda con **un** aviso vigente: publicar
            reemplaza el anterior de esa ranura. Con ``AMBOS`` las dos ranuras
            reciben el mismo ``aviso_id``, el mismo texto y el mismo
            vencimiento, que es lo que hace verificable la coherencia entre
            destinos. Las ranuras no alcanzadas quedan intactas, de modo que
            un aviso previo dirigido al otro destino nunca queda huérfano.

            Cuando el destino alcanza Recinto se registran además los marcadores
            de sesión de WP-078 en este orden dentro de la **misma** mutación:
            el ``FIN`` del período anterior (si lo había) y después el ``INICIO``
            del nuevo. Registrar el cierre antes de la apertura es lo que impide
            que un reemplazo deje un período abierto de más.
        """

        async def aplicar() -> None:
            ahora = self._reloj()
            expira_en = (
                None if duracion_segundos is None else ahora + timedelta(seconds=duracion_segundos)
            )
            self._auditar(
                CODIGO_AVISO_PUBLICADO,
                (
                    f"Aviso técnico publicado destino={destino.value}; "
                    f"duracion_segundos={duracion_segundos}; "
                    f"texto={texto}"
                ),
            )
            aviso = AvisoTecnico(
                aviso_id=self._generar_identificador(),
                texto=texto,
                destino=destino,
                publicado_en=ahora,
                expira_en=expira_en,
            )
            # Toda la auditoría del comando ocurre antes de tocar las ranuras,
            # igual que en el resto del backend: si cualquiera de las filas no
            # pudo persistirse, la mutación completa se aborta y el texto ni
            # siquiera llega a la pantalla.
            if destino.alcanza_recinto():
                self._cerrar_marcador_recinto()
                self._abrir_marcador_recinto(aviso)
            if destino.alcanza_moderacion():
                self._estado.aviso_tecnico_moderacion = aviso
            if destino.alcanza_recinto():
                self._estado.aviso_tecnico_recinto = aviso

        await self._ejecutor.ejecutar(aplicar)

    async def cancelar_aviso(self, destino: DestinoAvisoTecnico) -> None:
        """Retira el aviso vigente de las ranuras alcanzadas por el destino.

        Es idempotente por la misma razón que ``detener_transmision``: cancelar
        una ranura vacía (o una que acaba de vencer sola) no es un error del
        operador, y no debe producir ni un fallo ni una fila de auditoría.

        Sólo cierra el marcador de sesión de WP-078 cuando la cancelación afecta
        realmente a la ranura Recinto. Cancelar únicamente Moderación sobre un
        aviso ``AMBOS`` deja el texto visible en el Recinto y por lo tanto deja
        el período abierto, que es exactamente lo que pide el WP.
        """

        async def aplicar() -> None:
            alcanza_moderacion = (
                destino.alcanza_moderacion() and self._estado.aviso_tecnico_moderacion is not None
            )
            alcanza_recinto = (
                destino.alcanza_recinto() and self._estado.aviso_tecnico_recinto is not None
            )
            if not alcanza_moderacion and not alcanza_recinto:
                return
            self._auditar(
                CODIGO_AVISO_CANCELADO,
                f"Aviso técnico cancelado destino={destino.value}",
            )
            if alcanza_recinto:
                self._cerrar_marcador_recinto()
            if alcanza_moderacion:
                self._estado.aviso_tecnico_moderacion = None
            if alcanza_recinto:
                self._estado.aviso_tecnico_recinto = None

        await self._ejecutor.ejecutar(aplicar)

    def hay_marcador_recinto_vencido(self) -> bool:
        """Informa si queda un período abierto cuyo aviso ya venció.

        Es una consulta **síncrona y sin efectos**: el temporizador de
        ``servicios/fronteras_temporales.py`` la evalúa dentro de la misma
        lectura coherente con la que calcula la próxima frontera, así que
        observa el estado bajo el lock y no puede leerlo a mitad de una
        mutación.

        Por qué existe: un aviso ya vencido deja de aportar una frontera futura
        (``_demoras_tecnicas`` sólo considera vencimientos con ``faltante > 0``),
        de modo que el temporizador necesita una forma de reconocer que la
        frontera **ya se alcanzó** y que su efecto institucional sigue
        pendiente. Sin esta pregunta, el cruce dependería de que la tarea de
        espera haya sido marcada como completada, es decir, del orden en que el
        planificador de asyncio despachó sus callbacks.

        Devuelve exactamente la misma condición que aplica
        ``cerrar_marcadores_recinto_vencidos``. Compartir el predicado es
        deliberado: si las dos condiciones pudieran divergir, el temporizador
        podría quedar preguntando eternamente por un cierre que el cierre real
        se niega a ejecutar.
        """

        marcador = self._estado.marcador_recinto_abierto
        aviso = self._estado.aviso_tecnico_recinto
        if marcador is None or aviso is None:
            return False
        # Comparar el identificador evita confundir el período abierto con otro
        # aviso que un comando acaba de instalar en la misma ranura.
        return aviso.aviso_id == marcador.aviso_id and not aviso.vigente(self._reloj())

    def hay_efecto_temporal_pendiente(self) -> bool:
        """Informa si alguna frontera técnica alcanzada todavía debe procesarse.

        El temporizador consulta este predicado dentro del lock compartido. Se
        combinan los dos hechos automáticos del plano técnico —inicio efectivo
        de transmisión y fin de un aviso— para conservar una sola costura y una
        sola tarea de fronteras, sin agregar polling.
        """

        return self._hay_inicio_transmision_pendiente(self._reloj()) or (
            self.hay_marcador_recinto_vencido()
        )

    async def procesar_efectos_temporales_pendientes(self) -> None:
        """Audita y confirma todos los efectos técnicos cuyo plazo ya venció.

        La comprobación se repite dentro del ``EjecutorMutaciones`` porque un
        stop, reemplazo o cambio de aviso pudo ganar la carrera desde la lectura
        previa del temporizador. Un fallo de auditoría se propaga sin marcar el
        efecto como procesado; ``ServicioFronterasTemporales`` espera entonces
        un cambio real y evita un ciclo ocupado.
        """

        async def aplicar() -> None:
            ahora = self._reloj()
            self._procesar_inicio_transmision_pendiente(ahora)
            if self.hay_marcador_recinto_vencido():
                self._cerrar_marcador_recinto()

        await self._ejecutor.ejecutar(aplicar)

    async def cerrar_marcadores_recinto_vencidos(self) -> None:
        """Convierte el vencimiento por duración en un ``FIN`` durable.

        La llama el temporizador de ``servicios/fronteras_temporales.py`` cada
        vez que cruza una frontera temporal, siempre bajo el mismo
        ``EjecutorMutaciones`` que el resto de las mutaciones: no hay polling ni
        un segundo camino de escritura.

        Por qué hace falta: la vigencia de un aviso es un valor *derivado* del
        reloj, así que al vencer simplemente desaparece del DTO sin que nadie
        ejecute un comando. WP-078 exige que ese cierre sea un hecho
        institucional registrado, no una desaparición silenciosa.

        No toca la ranura del aviso. Retirarlo sería un cambio de comportamiento
        ajeno al WP —la proyección ya lo oculta por vencido— y podría alterar la
        ranura de Moderación cuando ambas comparten el mismo aviso ``AMBOS``. La
        autoridad de "período abierto" es el marcador, no la ranura.

        Errores:
            ``ErrorAuditoria`` si el escritor institucional no pudo persistir el
            ``FIN``. En ese caso el marcador queda abierto y no se anuncia una
            transición que no pudo registrarse.
        """

        async def aplicar() -> None:
            # La condición se evalúa de nuevo **dentro** del lock: entre que el
            # temporizador decidió cruzar y que obtuvo el turno exclusivo, una
            # cancelación o un reemplazo pudo haber cerrado ya este período.
            if not self.hay_marcador_recinto_vencido():
                return
            self._cerrar_marcador_recinto()

        await self._ejecutor.ejecutar(aplicar)

    # =========================================================================
    # 3. Biblioteca de mensajes precargados
    # =========================================================================

    async def obtener_biblioteca(self) -> BibliotecaMensajesTecnicos:
        """Devuelve la biblioteca vigente bajo el mismo lock funcional."""

        return await self._ejecutor.leer_coherente(
            lambda: self._estado.biblioteca_mensajes_tecnicos
        )

    async def crear_mensaje(self, texto: str, destino: DestinoAvisoTecnico) -> MensajeTecnico:
        """Agrega un mensaje al final de la biblioteca y lo persiste.

        El identificador lo genera el backend y no cambia nunca después: una
        interfaz futura puede guardarlo y seguir refiriéndose al mismo mensaje
        aunque su texto, su destino o su posición cambien.
        """

        async def aplicar() -> MensajeTecnico:
            biblioteca = self._exigir_biblioteca_disponible()
            mensaje = MensajeTecnico(
                mensaje_id=self._generar_identificador(),
                texto=texto,
                destino=destino,
            )
            self._persistir((*biblioteca.mensajes, mensaje))
            return mensaje

        return await self._ejecutor.ejecutar(aplicar)

    async def actualizar_mensaje(
        self,
        mensaje_id: str,
        texto: str,
        destino: DestinoAvisoTecnico,
    ) -> MensajeTecnico:
        """Reemplaza texto y destino de un mensaje conservando su posición.

        Errores:
            ``ErrorMensajeTecnicoNoExistente`` si el identificador no pertenece
            a la biblioteca vigente. No se crea un mensaje nuevo en ese caso:
            un ``PUT`` sobre un id desconocido casi siempre significa que la
            interfaz está mirando una biblioteca desactualizada.
        """

        async def aplicar() -> MensajeTecnico:
            biblioteca = self._exigir_biblioteca_disponible()
            posicion = self._buscar_posicion(biblioteca.mensajes, mensaje_id)
            actualizado = MensajeTecnico(mensaje_id=mensaje_id, texto=texto, destino=destino)
            mensajes = list(biblioteca.mensajes)
            mensajes[posicion] = actualizado
            self._persistir(tuple(mensajes))
            return actualizado

        return await self._ejecutor.ejecutar(aplicar)

    async def eliminar_mensaje(self, mensaje_id: str) -> None:
        """Quita un mensaje de la biblioteca y persiste el resultado.

        No es idempotente a propósito: eliminar un id inexistente devuelve
        ``MENSAJE_TECNICO_NO_EXISTENTE`` para que la interfaz detecte que su
        copia de la biblioteca quedó vieja, en vez de creer que borró algo.
        """

        async def aplicar() -> None:
            biblioteca = self._exigir_biblioteca_disponible()
            posicion = self._buscar_posicion(biblioteca.mensajes, mensaje_id)
            mensajes = list(biblioteca.mensajes)
            del mensajes[posicion]
            self._persistir(tuple(mensajes))

        await self._ejecutor.ejecutar(aplicar)

    # =========================================================================
    # 4. Ayudas privadas
    # =========================================================================

    def _auditar(self, codigo_evento: str, mensaje: str) -> None:
        """Registra un hecho del plano técnico si hay auditoría abierta.

        Se ejecuta dentro del lock y **antes** de mutar la memoria. Si el
        escritor está en fallo cerrado lanza ``ErrorAuditoria``, la mutación se
        aborta y la API responde ``503 AUDITORIA_NO_DISPONIBLE``.

        Cuando no hay contexto operativo (``SIN_PREPARAR``) no existe ningún
        conjunto de CSV abierto y la orden se aplica sin registrar: es el
        invariante del proyecto, que solo exige auditar desde ``PREPARANDO``.
        """

        contexto = self._estado.contexto_operativo_activo()
        if contexto is None:
            return
        contexto.escritor_auditoria.registrar_evento(
            NivelAuditoria.L2,
            ETIQUETA_APOYO_TECNICO,
            codigo_evento,
            mensaje,
        )

    def _abrir_marcador_transmision(self) -> None:
        """Registra el ``INICIO`` principal de un período EN VIVO (WP-096).

        Usa el mismo mecanismo autoritativo que el resto del log institucional:
        un ``registrar_evento`` de nivel ``L3`` con etiqueta general ``EVENTO``
        sobre el escritor del contexto activo. No existe un segundo log ni una
        fuente de verdad paralela.

        Escribe **una sola vez por período**. Si ya hay un marcador abierto, el
        indicador nunca llegó a apagarse —es un reemplazo de intención con
        continuidad— y no hubo transición institucional que registrar.

        Igual que en WP-078, el marcador en memoria se instala recién después de
        que ``registrar_evento`` confirmó su ``fsync``: si la persistencia falla,
        la excepción aborta la mutación completa y no queda abierto un período
        que nadie podría cerrar.

        En ``SIN_PREPARAR`` no hay conjunto de auditoría abierto, así que no se
        registra nada ni se abre marcador. El indicador funciona igual, pero ese
        encendido no pertenece a ninguna preparación ni sesión, y preparar más
        tarde no debe reconstruirlo retrospectivamente.
        """

        if self._estado.marcador_transmision_principal is not None:
            return
        contexto = self._estado.contexto_operativo_activo()
        if contexto is None:
            return
        contexto.escritor_auditoria.registrar_evento(
            NivelAuditoria.L3,
            ETIQUETA_EVENTO_PRINCIPAL,
            CODIGO_TRANSMISION_PRINCIPAL_INICIO,
            MENSAJE_TRANSMISION_PRINCIPAL_INICIO,
        )
        self._estado.marcador_transmision_principal = MarcadorTransmisionPrincipal(
            escritor_auditoria=contexto.escritor_auditoria,
        )

    def _cerrar_marcador_transmision(self) -> None:
        """Registra el ``FIN`` principal del período abierto, si existe.

        Es el **único** camino de cierre institucional de la transmisión, igual
        que :meth:`_cerrar_marcador_recinto` lo es para los avisos. Como el
        marcador se borra en la misma llamada que escribe el ``FIN``, dos causas
        que coincidan —el temporizador cruzando el deadline y una detención
        manual, por ejemplo— producen un solo ``FIN``: la segunda ya no encuentra
        período abierto.

        Un marcador cuyo escritor ya no es el vigente pertenece a un conjunto de
        CSV cerrado por una preparación/sesión anterior. La transmisión es
        independiente de ese ciclo y puede seguir encendida cuando la sesión
        termina, así que escribir su ``FIN`` en los archivos de otra sesión sería
        un registro falso: el marcador se descarta sin auditar.
        """

        marcador = self._estado.marcador_transmision_principal
        if marcador is None:
            return
        contexto = self._estado.contexto_operativo_activo()
        if contexto is not None and contexto.escritor_auditoria is marcador.escritor_auditoria:
            contexto.escritor_auditoria.registrar_evento(
                NivelAuditoria.L3,
                ETIQUETA_EVENTO_PRINCIPAL,
                CODIGO_TRANSMISION_PRINCIPAL_FIN,
                MENSAJE_TRANSMISION_PRINCIPAL_FIN,
            )
        self._estado.marcador_transmision_principal = None

    def _hay_inicio_transmision_pendiente(self, ahora: datetime) -> bool:
        """Decide por reloj si la intención vigente cruzó y aún no fue tratada."""

        transmision = self._estado.transmision_tecnica
        return (
            transmision is not None
            and not transmision.inicio_en_vivo_procesado
            and estado_transmision(transmision, ahora) is EstadoTransmision.EN_VIVO
        )

    def _procesar_inicio_transmision_pendiente(self, ahora: datetime) -> None:
        """Registra un único ``INICIO`` efectivo y marca esa intención.

        En ``SIN_PREPARAR`` ``_auditar`` es deliberadamente un no-op, pero la
        marca igualmente avanza: si más tarde se abre una preparación, el
        backend no reconstruye retrospectivamente un hecho ocurrido sin CSV.
        """

        if not self._hay_inicio_transmision_pendiente(ahora):
            return
        transmision = self._estado.transmision_tecnica
        if transmision is None:  # Defensa para el tipado; el predicado ya lo excluye.
            return
        self._auditar_inicio_transmision(transmision)
        self._estado.transmision_tecnica = replace(
            transmision,
            inicio_en_vivo_procesado=True,
        )

    def _auditar_inicio_transmision(self, transmision: TransmisionTecnica) -> None:
        """Persiste el hecho efectivo sin decidir todavía la mutación de memoria.

        Es el **único** lugar del backend donde se registra que la transmisión
        pasó realmente de no-activa a activa, sin importar si el cruce llegó por
        un inicio inmediato o por el vencimiento de una cuenta regresiva. Por eso
        el evento principal de WP-096 se escribe acá y no en los comandos: un
        countdown programado, uno reemplazado y uno cancelado nunca llegan a
        este método, así que no pueden generar un ``INICIO`` institucional falso.

        Escribe en este orden:

        1. el hecho técnico ``L2`` de WP-092, siempre, porque esa intención sí
           empezó a estar vigente y conserva su contrato completo;
        2. el ``INICIO`` principal ``L3`` de WP-096, sólo cuando no había ya un
           período institucional abierto. Un reemplazo con continuidad reutiliza
           el período vigente y por eso no agrega una segunda fila.

        Todo lo que se escriba queda durable antes de que el llamador marque la
        intención como procesada, de modo que un fallo de auditoría aborta la
        mutación entera y el sistema no proyecta un EN VIVO cuyo registro no pudo
        escribirse.
        """

        self._auditar(
            CODIGO_TRANSMISION_EN_VIVO_INICIO,
            (
                "Transmisión efectivamente EN VIVO; "
                f"iniciada_en={transmision.iniciada_en.isoformat()}; "
                f"en_vivo_desde={transmision.en_vivo_desde.isoformat()}"
            ),
        )
        self._abrir_marcador_transmision()

    def _cerrar_transmision_en_vivo(
        self,
        causa: str,
        ahora: datetime,
        *,
        continuidad: bool = False,
    ) -> None:
        """Cierra el período vigente una sola vez si el reloj ya marca EN VIVO.

        Un deadline que compite con stop/reemplazo puede estar visible pero aún
        no procesado. En ese caso se confirma primero su ``INICIO`` y después el
        ``FIN``. Al persistir el cierre se retira inmediatamente la intención:
        si una fila posterior del reemplazo falla, no queda en memoria un vivo
        cuyo fin ya fue registrado.

        Entradas:
            causa: motivo técnico que se registra en el hecho ``L2``.
            ahora: instante civil autoritativo de la mutación en curso.
            continuidad: ``True`` cuando el llamador va a dejar el indicador
                encendido sin interrupción en esta misma mutación, es decir un
                reemplazo por un inicio inmediato. El hecho técnico ``L2`` de
                WP-092 se registra igual —esa intención sí terminó—, pero el
                período **institucional** no se cierra: para el público y para el
                log principal la transmisión nunca dejó de estar EN VIVO, y
                emitir un FIN seguido de un INICIO produciría exactamente el par
                espurio que WP-096 prohíbe.
        """

        transmision = self._estado.transmision_tecnica
        if (
            transmision is None
            or estado_transmision(transmision, ahora) is not EstadoTransmision.EN_VIVO
        ):
            return
        self._procesar_inicio_transmision_pendiente(ahora)
        transmision = self._estado.transmision_tecnica
        if transmision is None:  # Defensa para el tipado; no hay awaits entre pasos.
            return
        self._auditar(
            CODIGO_TRANSMISION_EN_VIVO_FIN,
            (
                "Transmisión dejó de estar EN VIVO; "
                f"iniciada_en={transmision.iniciada_en.isoformat()}; "
                f"en_vivo_desde={transmision.en_vivo_desde.isoformat()}; "
                f"causa={causa}"
            ),
        )
        # El evento principal de WP-096 acompaña al hecho técnico dentro del
        # mismo cierre, salvo continuidad. La causa (detención manual o
        # reemplazo) es información técnica de operación y se conserva sólo en el
        # mensaje L2: para el log institucional el hecho relevante es que la
        # transmisión terminó.
        if not continuidad:
            self._cerrar_marcador_transmision()
        self._estado.transmision_tecnica = None

    def _abrir_marcador_recinto(self, aviso: AvisoTecnico) -> None:
        """Registra el ``INICIO`` de un período de visualización en Recinto.

        Se ejecuta dentro del lock y sólo para avisos que alcanzan Recinto. El
        mensaje del evento es **exactamente** el texto del aviso: sin prefijos
        como "Aviso técnico", sin destino, sin duración y sin identificadores
        internos, porque quien lee el registro institucional debe ver el mismo
        texto que vio el recinto.

        Igual que el resto de la auditoría del backend, el marcador en memoria se
        instala recién después de que ``registrar_evento`` confirmó su ``fsync``:
        si la persistencia falla, la excepción aborta la mutación completa y no
        queda un período abierto que nadie podría cerrar.

        En ``SIN_PREPARAR`` no hay conjunto de auditoría abierto, así que no se
        registra nada ni se abre marcador. Ese aviso simplemente no delimita un
        momento de una sesión que todavía no existe.
        """

        contexto = self._estado.contexto_operativo_activo()
        if contexto is None:
            return
        contexto.escritor_auditoria.registrar_evento(
            NivelAuditoria.L3,
            ETIQUETA_EVENTO_PRINCIPAL,
            CODIGO_MARCADOR_INICIO,
            aviso.texto,
        )
        self._estado.marcador_recinto_abierto = MarcadorRecintoAbierto(
            aviso_id=aviso.aviso_id,
            texto=aviso.texto,
            escritor_auditoria=contexto.escritor_auditoria,
        )

    def _cerrar_marcador_recinto(self) -> None:
        """Registra el ``FIN`` del período abierto, si existe exactamente uno.

        Es el **único** camino de cierre: cancelación, reemplazo y vencimiento
        pasan todos por acá. Como el marcador se borra en la misma llamada que
        escribe el ``FIN``, dos causas que coincidan en el tiempo —el timer y una
        cancelación manual, por ejemplo— producen un solo ``FIN``: la segunda ya
        no encuentra período abierto. Esa es la garantía de idempotencia del WP,
        y no depende de comparar textos ni de releer la auditoría.

        Un marcador cuyo escritor ya no es el vigente pertenece a un conjunto de
        CSV cerrado por una preparación/sesión anterior. Escribir su ``FIN`` en
        los archivos de otra sesión sería un registro falso, así que el marcador
        se descarta sin auditar: el período quedó terminado junto con su propio
        conjunto institucional.
        """

        marcador = self._estado.marcador_recinto_abierto
        if marcador is None:
            return
        contexto = self._estado.contexto_operativo_activo()
        if contexto is not None and contexto.escritor_auditoria is marcador.escritor_auditoria:
            contexto.escritor_auditoria.registrar_evento(
                NivelAuditoria.L3,
                ETIQUETA_EVENTO_PRINCIPAL,
                CODIGO_MARCADOR_FIN,
                marcador.texto,
            )
        self._estado.marcador_recinto_abierto = None

    def _exigir_biblioteca_disponible(self) -> BibliotecaMensajesTecnicos:
        """Impide escribir sobre un CSV que el backend no pudo interpretar."""

        biblioteca = self._estado.biblioteca_mensajes_tecnicos
        if not biblioteca.disponible:
            raise ErrorBibliotecaMensajesNoDisponible(
                biblioteca.detalle
                or "La biblioteca de mensajes técnicos no pudo interpretarse y no admite cambios"
            )
        return biblioteca

    @staticmethod
    def _buscar_posicion(mensajes: tuple[MensajeTecnico, ...], mensaje_id: str) -> int:
        """Ubica un mensaje por identificador o rechaza el comando."""

        for posicion, mensaje in enumerate(mensajes):
            if mensaje.mensaje_id == mensaje_id:
                return posicion
        raise ErrorMensajeTecnicoNoExistente(
            f"El mensaje técnico {mensaje_id} no pertenece a la biblioteca vigente"
        )

    def _persistir(self, mensajes: tuple[MensajeTecnico, ...]) -> None:
        """Escribe el CSV completo y solo entonces actualiza la memoria.

        El orden importa: ``guardar_mensajes_tecnicos`` reemplaza el archivo de
        forma atómica y lanza ``ErrorPersistenciaMensajesTecnicos`` si algo
        falla. Al actualizar la memoria después, un fallo de disco deja la
        biblioteca en memoria idéntica al archivo que quedó en disco, sin
        divergencia posible entre lo que se muestra y lo que se conserva.
        """

        guardar_mensajes_tecnicos(self._ruta_mensajes, mensajes)
        self._estado.biblioteca_mensajes_tecnicos = BibliotecaMensajesTecnicos(mensajes=mensajes)
