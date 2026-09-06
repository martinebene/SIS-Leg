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

La cuenta regresiva que llega a ``EN VIVO`` no se audita ni muta el dominio:
es un estado derivado del reloj, exactamente como la expiración del test de
dispositivo de WP-006.

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
    MarcadorRecintoAbierto,
    MensajeTecnico,
    TransmisionTecnica,
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
            # La memoria se actualiza recién después de que la auditoría
            # confirmó su ``fsync``: nunca se anuncia como aplicada una orden
            # cuyo registro institucional falló.
            self._estado.transmision_tecnica = TransmisionTecnica(
                iniciada_en=ahora,
                en_vivo_desde=en_vivo_desde,
                cuenta_regresiva_segundos=cuenta_regresiva_segundos,
            )

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
            marcador = self._estado.marcador_recinto_abierto
            aviso = self._estado.aviso_tecnico_recinto
            if marcador is None or aviso is None:
                return
            # Sólo cierra el período que corresponde exactamente a este aviso y
            # únicamente si ya venció. Comparar el identificador evita cerrar por
            # error un período que otro comando acaba de abrir en la misma ranura.
            if aviso.aviso_id != marcador.aviso_id or aviso.vigente(self._reloj()):
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
