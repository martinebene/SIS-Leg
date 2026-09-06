"""Modelo de dominio del plano técnico de Apoyo Técnico (WP-055).

Este módulo describe *qué existe* en el plano técnico, no *cómo* se cambia:
las transiciones las ejecuta ``servicios/apoyo_tecnico.py`` bajo el
serializador único del backend, igual que el resto del dominio.

El plano técnico tiene tres piezas independientes entre sí:

1. **Transmisión**: el indicador autoritativo de que la sesión se está
   transmitiendo. Vale ``APAGADO`` mientras nadie la inició; puede iniciarse
   de inmediato o con una cuenta regresiva de N segundos, y solamente vuelve a
   ``APAGADO`` por una orden manual. No controla ninguna señal de video real
   (decisión humana cerrada 8 del WP-055): es únicamente el estado/indicador.

2. **Avisos técnicos**: mensajes que Apoyo Técnico publica hacia Moderación,
   hacia Recinto o hacia ambos. Cada destino tiene su propia ranura, de modo
   que un aviso dirigido a Moderación jamás puede aparecer en el Recinto.

3. **Biblioteca de mensajes precargados**: textos administrados por Apoyo
   Técnico y persistidos en CSV para sobrevivir a un reinicio del backend.

Decisión de diseño central — *el tiempo no se guarda, se deriva*:

``TransmisionTecnica`` y ``AvisoTecnico`` guardan el instante absoluto en que
cruzan su frontera temporal (``en_vivo_desde`` y ``expira_en``). El estado
observable —``CUENTA_REGRESIVA`` vs ``EN_VIVO``, aviso vigente vs vencido— se
calcula al proyectar comparando ese instante con el reloj. Así:

- no hace falta una tarea que "mute" el dominio al vencer un plazo;
- un cliente que se reconecta reconstruye exactamente la misma verdad temporal
  porque recibe el instante absoluto, no un contador local;
- nunca queda un estado huérfano si el proceso estuvo ocupado en el instante
  exacto del vencimiento.

El único trabajo del temporizador de ``servicios/fronteras_temporales.py`` es
*despertar* en esas fronteras para publicar una revisión nueva, porque el
payload observable cambia aunque nadie haya ejecutado un comando. Eso es lo
que permite cumplir la restricción del WP de no introducir polling.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from botonera2_backend.auditoria import EscritorAuditoriaCsv


class EstadoTransmision(StrEnum):
    """Estados observables del indicador de transmisión.

    Es un valor *derivado*: el dominio no lo almacena, lo calcula
    :func:`estado_transmision` a partir del instante ``en_vivo_desde``. Que el
    enum exista acá y no en la capa de proyección permite que servicios y
    pruebas razonen con el mismo vocabulario que publica el contrato REST/SSE.
    """

    APAGADO = "APAGADO"
    CUENTA_REGRESIVA = "CUENTA_REGRESIVA"
    EN_VIVO = "EN_VIVO"


class DestinoAvisoTecnico(StrEnum):
    """Destinos posibles de un aviso técnico o de un mensaje precargado.

    ``AMBOS`` no es un tercer destino con ranura propia: es la orden de
    afectar coherentemente las dos ranuras reales (Moderación y Recinto) en la
    misma mutación. Se conserva en el aviso publicado para que el puesto
    técnico pueda mostrar con qué intención se emitió.
    """

    MODERACION = "MODERACION"
    RECINTO = "RECINTO"
    AMBOS = "AMBOS"

    def alcanza_moderacion(self) -> bool:
        """Indica si este destino debe afectar la ranura de Moderación."""

        return self in (DestinoAvisoTecnico.MODERACION, DestinoAvisoTecnico.AMBOS)

    def alcanza_recinto(self) -> bool:
        """Indica si este destino debe afectar la ranura del Recinto."""

        return self in (DestinoAvisoTecnico.RECINTO, DestinoAvisoTecnico.AMBOS)


@dataclass(frozen=True, slots=True)
class TransmisionTecnica:
    """Intención vigente de transmisión, con su frontera temporal absoluta.

    Es inmutable a propósito: iniciar la transmisión no muta este objeto sino
    que instala uno nuevo, y detenerla lo reemplaza por ``None``. Así no existe
    ningún camino por el cual un observador pueda ver una transmisión a mitad
    de actualización.

    Atributos:
        iniciada_en: instante civil en que Apoyo Técnico emitió la orden.
        en_vivo_desde: instante civil a partir del cual el estado observable es
            ``EN_VIVO``. Coincide con ``iniciada_en`` en el inicio inmediato.
        cuenta_regresiva_segundos: duración solicitada de la cuenta regresiva,
            o ``None`` cuando el inicio fue inmediato. Se conserva únicamente
            como dato informativo para el puesto técnico; la verdad temporal
            siempre es ``en_vivo_desde``.
    """

    iniciada_en: datetime
    en_vivo_desde: datetime
    cuenta_regresiva_segundos: int | None


@dataclass(frozen=True, slots=True)
class AvisoTecnico:
    """Aviso vigente en una ranura de destino, con vencimiento opcional.

    Atributos:
        aviso_id: identificador de la publicación. Cuando el destino fue
            ``AMBOS``, las dos ranuras comparten exactamente el mismo
            identificador: eso es lo que hace verificable que se trate de una
            única publicación coherente y no de dos avisos casualmente iguales.
        texto: contenido a mostrar, ya validado por la capa de API.
        destino: destino solicitado en el comando que creó el aviso.
        publicado_en: instante civil de publicación.
        expira_en: instante civil en el que el aviso deja de estar vigente, o
            ``None`` cuando debe permanecer hasta la cancelación manual.
    """

    aviso_id: str
    texto: str
    destino: DestinoAvisoTecnico
    publicado_en: datetime
    expira_en: datetime | None

    def vigente(self, ahora: datetime) -> bool:
        """Decide si el aviso todavía debe mostrarse en ese instante.

        La comparación es ``ahora < expira_en``: al alcanzarse exactamente el
        instante de vencimiento el aviso ya no está vigente. Esa frontera
        cerrada por izquierda es la que verifican las pruebas de expiración.
        """

        return self.expira_en is None or ahora < self.expira_en


@dataclass(frozen=True, slots=True)
class MarcadorRecintoAbierto:
    """Período de visualización en Recinto con un ``INICIO`` ya persistido.

    WP-078 convierte cada aparición de un aviso en la Pantalla del Recinto en un
    par de eventos principales de la sesión: ``INICIO`` cuando el texto aparece
    y ``FIN`` cuando deja de mostrarse. Para garantizar que ese par no se
    duplique ni quede desparejo hace falta un dato autoritativo que diga
    "hay un período abierto y todavía no fue cerrado".

    Ese dato **no** puede deducirse del aviso vigente. El aviso sigue existiendo
    en su ranura después de vencer (el vencimiento es derivado del reloj), puede
    haberse publicado en ``SIN_PREPARAR`` —donde no existe auditoría y por lo
    tanto no hubo ``INICIO``— y su texto no permite distinguir un período de
    otro. Por eso el marcador se instala recién **después** de que el ``INICIO``
    quedó confirmado por la auditoría, y se retira recién después de confirmar
    el ``FIN``.

    Atributos:
        aviso_id: identificador del aviso cuya presencia en Recinto abrió el
            período. Permite verificar que el cierre corresponde exactamente a
            la misma publicación y no a una posterior.
        texto: texto exacto que se registró en el ``INICIO``. Se conserva acá y
            no se relee del aviso porque el ``FIN`` debe repetir literalmente el
            mismo texto aunque la ranura ya haya sido reemplazada.
        escritor_auditoria: conjunto de CSV en el que se persistió el
            ``INICIO``. Se compara por identidad: si la preparación/sesión
            terminó y hay otro conjunto abierto, el período pertenece a archivos
            ya cerrados y su ``FIN`` no puede escribirse en un conjunto distinto.
    """

    aviso_id: str
    texto: str
    escritor_auditoria: EscritorAuditoriaCsv


@dataclass(frozen=True, slots=True)
class MensajeTecnico:
    """Mensaje precargado de la biblioteca persistida en CSV.

    Atributos:
        mensaje_id: identificador estable. Se genera al crear el mensaje y no
            cambia nunca al editarlo, para que una futura interfaz pueda
            referenciarlo sin depender de su posición ni de su texto.
        texto: contenido del mensaje.
        destino: destino sugerido al publicarlo.
    """

    mensaje_id: str
    texto: str
    destino: DestinoAvisoTecnico


@dataclass(frozen=True, slots=True)
class BibliotecaMensajesTecnicos:
    """Copia en memoria de la biblioteca CSV más su condición técnica.

    El backend nunca reescribe un archivo que no pudo interpretar: si la carga
    inicial falló, ``disponible`` queda en ``False`` y todos los comandos de
    escritura se rechazan. Es la protección contra la pérdida silenciosa de
    mensajes que un operador editó a mano con un error de formato.

    Atributos:
        mensajes: contenido válido leído del CSV, en el orden del archivo.
        disponible: ``False`` únicamente cuando el archivo existe pero no pudo
            interpretarse. Un archivo inexistente es una biblioteca vacía
            perfectamente válida.
        motivo: código estable del problema, o ``None`` si no hubo problema.
        detalle: explicación humana determinista del rechazo.
    """

    mensajes: tuple[MensajeTecnico, ...] = ()
    disponible: bool = True
    motivo: str | None = None
    detalle: str | None = None


class ErrorMensajeTecnicoNoExistente(Exception):
    """El ``mensaje_id`` recibido no pertenece a la biblioteca vigente.

    Corresponde al código estable ``MENSAJE_TECNICO_NO_EXISTENTE`` con HTTP 404.
    """


class ErrorBibliotecaMensajesNoDisponible(Exception):
    """La biblioteca CSV no pudo interpretarse y no admite escrituras.

    Corresponde al código estable ``BIBLIOTECA_MENSAJES_INVALIDA`` con HTTP 503.
    Rechazar la escritura es deliberado: sobrescribir el archivo con lo poco
    que se pudo leer destruiría el contenido que el operador quiso conservar.
    """


class ErrorPersistenciaMensajesTecnicos(Exception):
    """El CSV de mensajes no pudo escribirse de forma durable.

    Corresponde al código estable ``PERSISTENCIA_MENSAJES_FALLIDA`` con HTTP
    503. Ante este error la biblioteca en memoria queda intacta, porque la
    memoria solo se actualiza después de que la escritura atómica confirmó.
    """


def estado_transmision(
    transmision: TransmisionTecnica | None,
    ahora: datetime,
) -> EstadoTransmision:
    """Deriva el estado observable de la transmisión en un instante dado.

    Entradas:
        transmision: intención vigente, o ``None`` si nadie inició la
            transmisión (o si ya fue detenida manualmente).
        ahora: instante civil con el que se compara la frontera.

    Resultado:
        ``APAGADO`` sin intención vigente; ``EN_VIVO`` cuando ``ahora`` ya
        alcanzó ``en_vivo_desde``; ``CUENTA_REGRESIVA`` mientras falte para
        esa frontera.

    No existe ningún camino que devuelva ``APAGADO`` con una intención vigente:
    eso implementa la regla "no hay autoapagado de EN VIVO" del WP-055.
    """

    if transmision is None:
        return EstadoTransmision.APAGADO
    if ahora >= transmision.en_vivo_desde:
        return EstadoTransmision.EN_VIVO
    return EstadoTransmision.CUENTA_REGRESIVA
