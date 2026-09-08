"""DTOs y constructores autoritativos de los estados de solo lectura.

REST y SSE llaman a este mismo servicio. Esa única ruta de construcción evita
que el stream público aplique una política de secreto distinta del snapshot o
que alguno serialice accidentalmente objetos mutables del dominio.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field

from sis_leg_backend.auditoria import EventoAuditoriaReciente, NivelAuditoria
from sis_leg_backend.configuracion.modelos import (
    Concejal,
    ConfiguracionSistema,
    ConfiguracionSonidosRecinto,
    IdentidadInstitucional,
)
from sis_leg_backend.dominio.apoyo_tecnico import (
    AvisoTecnico,
    BibliotecaMensajesTecnicos,
    DestinoAvisoTecnico,
    EstadoTransmision,
    TransmisionTecnica,
    estado_transmision,
)
from sis_leg_backend.dominio.estado import EstadoGlobal, EstadoOperativo
from sis_leg_backend.dominio.preparacion import Preparacion
from sis_leg_backend.dominio.remapeo import EstadoRemapeo, OperacionRemapeo
from sis_leg_backend.dominio.sesion import Sesion
from sis_leg_backend.dominio.votacion import (
    EstadoVotacion,
    ResultadoVotacion,
    TipoMayoria,
    ValorVotoOrdinario,
    Votacion,
)
from sis_leg_backend.hechos_operativos import (
    ReferenciaHechoOperativo,
    TipoHechoOperativo,
)
from sis_leg_backend.servicios.publicacion import CoordinadorPublicacion
from sis_leg_backend.servicios.serializacion import EjecutorMutaciones

# La pantalla pública trabaja con una allowlist positiva y textos escritos a
# mano. El mensaje de auditoría no participa de este mapeo: puede contener DNI,
# dispositivos, teclas o detalles institucionales que no pertenecen al DTO.
MAPEO_EVENTOS_PUBLICOS: dict[str, tuple[str, str]] = {
    "SESION_ABIERTA": ("SESION", "Sesión abierta"),
    "SESION_CERRADA": ("SESION", "Sesión cerrada"),
    "CONCEJAL_PRESENTE": ("PRESENCIA", "Concejal presente"),
    "CONCEJAL_AUSENTE": ("PRESENCIA", "Concejal ausente"),
    "PEDIDO_PALABRA_REGISTRADO": ("PALABRA", "Pedido de palabra registrado"),
    "PEDIDO_PALABRA_RETIRADO": ("PALABRA", "Pedido de palabra retirado"),
    "USO_PALABRA_OTORGADO": ("PALABRA", "Uso de palabra otorgado"),
    "USO_PALABRA_FINALIZADO": ("PALABRA", "Uso de palabra finalizado"),
    "VOTACION_ABIERTA": ("VOTACION", "Votación abierta"),
    "VOTACION_CERRADA_COMPLETITUD": ("VOTACION", "Votación cerrada"),
    "VOTACION_FINALIZADA_INCONCLUSA": ("VOTACION", "Votación finalizada inconclusa"),
    "VOTACION_RESULTADO_FINAL": ("VOTACION", "Resultado de votación disponible"),
    "VOTACION_RESULTADO_EMPATE": ("VOTACION", "Resultado de votación empatado"),
    "VOTACION_RESULTADO_DESEMPATE": ("VOTACION", "Resultado de desempate disponible"),
}
LIMITE_EVENTOS_PUBLICOS = 20

# Iconografía y textos decididos por HUMAN_GATE para el panel de eventos de
# Moderación (WP-052). Viven en el backend, y no en Vue, porque forman parte de
# la frontera de secreto: si el icono de sentido lo eligiera el frontend, el
# payload tendría que transportar el sentido incluso cuando todavía es secreto.
ICONO_POR_SENTIDO: dict[ValorVotoOrdinario, str] = {
    ValorVotoOrdinario.POSITIVO: "\u2705",
    ValorVotoOrdinario.NEGATIVO: "\u274c",
    ValorVotoOrdinario.ABSTENCION: "\U0001f7e1",
}
DETALLE_POR_SENTIDO: dict[ValorVotoOrdinario, str] = {
    ValorVotoOrdinario.POSITIVO: "Voto POSITIVO",
    ValorVotoOrdinario.NEGATIVO: "Voto NEGATIVO",
    ValorVotoOrdinario.ABSTENCION: "Voto ABSTENCIÓN",
}
# Texto único mientras el sentido individual sigue siendo secreto: identifica
# que la banca ya participó sin decir nunca qué votó.
DETALLE_VOTO_SECRETO = "Voto emitido"
ICONO_PEDIDO_PALABRA = "\u270b"
ICONO_RETIRO_PALABRA = "\u270a"
DETALLE_PEDIDO_PALABRA = "Pedido de palabra"
DETALLE_RETIRO_PALABRA = "Pedido de palabra retirado"


class ModeloProyeccion(BaseModel):
    """Base inmutable de todos los DTOs enviados por REST o SSE."""

    model_config = ConfigDict(frozen=True)


class ConfiguracionProyectada(ModeloProyeccion):
    """Configuración congelada necesaria para construir la UI de Moderación."""

    quorum: int
    filas_bancas: tuple[int, ...]
    tipos_votacion: tuple[str, ...]
    duracion_test_segundos: int | float
    revelado_votos_moderacion_segundos: int | float
    cuenta_regresiva_recinto_segundos: int | float
    resultado_publico_recinto_segundos: int | float


class DatosPreparacion(ModeloProyeccion):
    """Identifica el contexto que todavía no es una sesión formal."""

    fecha_hora_inicio: datetime
    numero_sesion: int | None
    presidencia: str | None
    secretaria_legislativa: str | None


class DatosSesion(ModeloProyeccion):
    """Identifica la sesión formal y sus autoridades vigentes."""

    fecha_hora_inicio_preparacion: datetime
    fecha_hora_apertura: datetime
    numero_sesion: int
    presidencia: str
    secretaria_legislativa: str


class EstadoQuorum(ModeloProyeccion):
    """Expone los cálculos de quórum para que la UI no los reimplemente."""

    cantidad_presentes: int
    requerido: int
    alcanzado: bool


class ConcejalModeracion(ModeloProyeccion):
    """Banca completa disponible para el operador institucional."""

    dni: str
    nombre: str
    apellido: str
    bloque: str
    banca: int
    dispositivo_votacion: str
    ruta_imagen: str
    presente: bool
    test_activo: bool
    test_expira_en: datetime | None


class ConcejalPublico(ModeloProyeccion):
    """Banca pública por allowlist, sin DNI ni identificador de dispositivo."""

    nombre: str
    apellido: str
    bloque: str
    banca: int
    ruta_imagen: str
    presente: bool
    test_activo: bool
    test_expira_en: datetime | None


class PersonaPalabraModeracion(ModeloProyeccion):
    """Identidad de cola/orador apropiada para Moderación."""

    dni: str
    nombre: str
    apellido: str
    banca: int


class PersonaPalabraPublica(ModeloProyeccion):
    """Identidad pública de cola/orador sin DNI."""

    nombre: str
    apellido: str
    banca: int


class EstadoPalabraModeracion(ModeloProyeccion):
    """Copia ordenada de la única cola y el único orador del dominio."""

    cola: tuple[PersonaPalabraModeracion, ...]
    orador: PersonaPalabraModeracion | None


class EstadoPalabraPublico(ModeloProyeccion):
    """Versión pública del uso de palabra."""

    cola: tuple[PersonaPalabraPublica, ...]
    orador: PersonaPalabraPublica | None


class ConteosVotosProyectados(ModeloProyeccion):
    """Conteos derivados que nunca incluyen el voto presidencial."""

    positivos: int
    negativos: int
    abstenciones: int
    total: int


class VotoModeracion(ModeloProyeccion):
    """Voto ordinario individual revelable a Moderación según su deadline."""

    dni: str
    nombre: str
    apellido: str
    banca: int
    valor: str


class VotoPublico(ModeloProyeccion):
    """Voto ordinario público posterior al cierre, asociado solo a la banca."""

    nombre: str
    apellido: str
    banca: int
    valor: str


class VotoPresidencialProyectado(ModeloProyeccion):
    """Desempate separado que no se mezcla con los votos de concejales."""

    presidencia: str
    sentido: str


class VotacionModeracion(ModeloProyeccion):
    """Vista completa de la votación relevante para el operador."""

    id: str
    numero_votacion: int
    tipo: str
    tema: str
    tipo_mayoria: str
    factor: float
    base: str
    estado_recepcion: str
    resultado: str | None
    fecha_hora_apertura: datetime
    fecha_hora_cierre: datetime | None
    fecha_hora_resultado: datetime | None
    resultado_visible_hasta: datetime | None
    motivo_finalizacion_manual: str | None
    cantidad_votos_recibidos: int
    bancas_voto_emitido: tuple[int, ...]
    revelado_individual_desde: datetime
    votos_individuales_revelados: bool
    votos_individuales: tuple[VotoModeracion, ...] | None
    conteos: ConteosVotosProyectados | None
    voto_presidencial: VotoPresidencialProyectado | None


class VotacionPublica(ModeloProyeccion):
    """Vista pública restrictiva construida sin serializar el dominio completo."""

    id: str
    numero_votacion: int
    tipo: str
    tema: str
    tipo_mayoria: str
    factor: float
    base: str
    estado_recepcion: str
    resultado: str | None
    fecha_hora_apertura: datetime
    fecha_hora_cierre: datetime | None
    cuenta_regresiva_hasta: datetime | None
    resultado_visible_hasta: datetime | None
    bancas_voto_emitido: tuple[int, ...]
    votos_individuales: tuple[VotoPublico, ...] | None
    conteos: ConteosVotosProyectados | None
    voto_presidencial: VotoPresidencialProyectado | None


class PuntoOrdenDelDiaProyectado(ModeloProyeccion):
    """Punto asistencial normalizado disponible solo para Moderación.

    ``tratado`` es la ayuda visual que introduce WP-053. Vale ``True`` cuando el
    historial autoritativo de la sesión ya contiene una votación **abierta** con
    ese mismo ``nro_votacion``. Se calcula en el backend, y no en Vue, por dos
    razones: el frontend nunca decide reglas y, al viajar ya resuelto, cualquier
    reconexión o recarga reconstruye la marca desde el snapshot sin guardar
    estado local. La marca es puramente asistencial: no bloquea el punto, no lo
    consume y no impide volver a usar el mismo número.
    """

    nro_votacion: int
    tipo: str
    tema: str
    tipo_mayoria: str
    factor: float
    base: str
    tratado: bool


class ConcejalHechoProyectado(ModeloProyeccion):
    """Identidad mínima del concejal al que se refiere un hecho operativo.

    Se resuelve contra el padrón congelado en el momento de proyectar, así que
    el buffer de auditoría no guarda una copia paralela de la identidad. No
    incluye DNI ni dispositivo porque el panel de eventos necesita reconocer la
    banca, no repetir datos que ya viajan en la grilla de concejales.
    """

    nombre: str
    apellido: str
    banca: int


class HechoOperativoProyectado(ModeloProyeccion):
    """Lectura estructurada y ya filtrada por la frontera de secreto (WP-052).

    Este es el contrato que consume la interfaz de Moderación para pintar un
    evento sensible. Existe justamente para que el frontend **no** tenga que
    interpretar ``mensaje``: el texto humano puede reescribirse en cualquier WP
    posterior sin romper la UI, y ningún cambio de redacción puede convertirse
    accidentalmente en un canal lateral que revele un voto.

    Atributos:
        tipo: valor de :class:`TipoHechoOperativo` que clasifica el hecho.
        concejal: banca e identidad legible del hecho.
        detalle: texto corto ya resuelto para mostrar. Durante el secreto de un
            voto vale exactamente ``"Voto emitido"``.
        icono: emoji decidido por el backend. Es ``None`` mientras el sentido
            individual siga siendo secreto, de modo que la ausencia del icono
            no dependa de una decisión del frontend.
        sentido: ``POSITIVO``/``NEGATIVO``/``ABSTENCION`` únicamente cuando la
            frontera autoritativa de esa votación ya habilitó el revelado. Antes
            de esa frontera vale ``None`` y el dato no viaja en el payload.
    """

    tipo: str
    concejal: ConcejalHechoProyectado
    detalle: str
    icono: str | None
    sentido: str | None


class EventoRecienteProyectado(ModeloProyeccion):
    """Evento cuyo ``fsync`` ya fue confirmado por el escritor activo.

    ``mensaje`` conserva el texto humano de la auditoría salvo cuando ese texto
    revelaría el sentido individual de un voto todavía secreto: en ese caso se
    publica la redacción segura declarada al registrar el hecho. El CSV durable
    nunca cambia; lo único que se elige acá es qué puede ver Moderación ahora.
    """

    seq: int
    timestamp: str
    nivel: str
    etiqueta: str
    codigo_evento: str
    mensaje: str
    hecho: HechoOperativoProyectado | None


class EventoPublicoProyectado(ModeloProyeccion):
    """Hecho público seguro derivado de un evento L3 ya confirmado.

    El DTO omite deliberadamente nivel, etiqueta y mensaje de auditoría. Su
    texto nace de :data:`MAPEO_EVENTOS_PUBLICOS`, por lo que agregar un código
    futuro al registro institucional no lo publica de manera accidental.
    """

    seq: int
    timestamp: str
    categoria: str
    codigo_evento: str
    texto: str


class EstadoAuditoriaProyectado(ModeloProyeccion):
    """Condición técnica del escritor, separada del estado reglamentario."""

    activa: bool
    disponible: bool
    fallado: bool
    cerrado: bool
    motivo: str | None


class EstadoRemapeoModeracion(ModeloProyeccion):
    """Operación física activa visible exclusivamente para Moderación."""

    remapeo_id: str
    dispositivo: str
    estado: str
    fingerprint_anterior: str | None
    candidato: str | None
    diagnostico: str | None


class Capacidad(ModeloProyeccion):
    """Indica disponibilidad actual y códigos estables que explican el bloqueo."""

    habilitada: bool
    motivos: tuple[str, ...] = Field(default_factory=tuple)


class CapacidadesModeracion(ModeloProyeccion):
    """Precondiciones derivables sin intentar validar bodies futuros."""

    preparar_sala: Capacidad
    actualizar_preparacion: Capacidad
    cancelar_preparacion: Capacidad
    abrir_sesion: Capacidad
    actualizar_sesion: Capacidad
    cerrar_sesion: Capacidad
    cargar_orden_del_dia: Capacidad
    descartar_orden_del_dia: Capacidad
    abrir_votacion: Capacidad
    finalizar_votacion: Capacidad
    desempatar: Capacidad
    otorgar_palabra: Capacidad
    quitar_palabra: Capacidad
    iniciar_remapeo: Capacidad
    confirmar_remapeo: Capacidad
    cancelar_remapeo: Capacidad


class TransmisionProyectada(ModeloProyeccion):
    """Estado autoritativo del indicador de transmisión (WP-055).

    El DTO publica a la vez la frontera absoluta y el resto calculado por el
    backend. El frontend puede animar el contador con ``segundos_restantes``
    sin decidir nunca por su cuenta cuándo empieza ``EN VIVO``: esa decisión
    sigue siendo del servidor, que republica al cruzar ``en_vivo_desde``.

    Atributos:
        estado: ``APAGADO``, ``CUENTA_REGRESIVA`` o ``EN_VIVO``.
        iniciada_en: instante de la orden humana, o ``None`` si está apagada.
        en_vivo_desde: frontera absoluta a partir de la cual vale ``EN_VIVO``.
            Es el dato que permite reconstruir la verdad temporal exacta tras
            un reload o una reconexión SSE.
        cuenta_regresiva_segundos: duración solicitada, o ``None`` cuando el
            inicio fue inmediato.
        segundos_restantes: faltante para la frontera, nunca negativo. Vale
            ``None`` fuera de ``CUENTA_REGRESIVA``.
    """

    estado: EstadoTransmision
    iniciada_en: datetime | None
    en_vivo_desde: datetime | None
    cuenta_regresiva_segundos: int | None
    segundos_restantes: float | None


class AvisoTecnicoProyectado(ModeloProyeccion):
    """Aviso técnico vigente en una ranura de destino (WP-055).

    Solo se proyecta mientras está vigente: un aviso vencido desaparece del
    payload sin que ninguna mutación lo haya borrado, porque la vigencia se
    deriva de ``expira_en`` contra el reloj del backend.

    Atributos:
        aviso_id: identificador de la publicación. Cuando el destino fue
            ``AMBOS``, Moderación y Recinto reciben el mismo valor.
        texto: contenido a mostrar.
        destino: destino solicitado al publicarlo.
        publicado_en: instante civil de publicación.
        expira_en: frontera absoluta de vencimiento, o ``None`` si permanece
            hasta la cancelación manual.
        segundos_restantes: faltante para el vencimiento, o ``None`` si no
            vence.
    """

    aviso_id: str
    texto: str
    destino: DestinoAvisoTecnico
    publicado_en: datetime
    expira_en: datetime | None
    segundos_restantes: float | None


class ApoyoTecnicoProyectado(ModeloProyeccion):
    """Porción del plano técnico que corresponde a **un** destino (WP-055).

    Moderación y Recinto reciben este mismo submodelo, pero cada uno con su
    propio aviso: la separación se aplica en el servidor, igual que el secreto
    de voto, de manera que un aviso dirigido a Moderación jamás viaja en el
    payload del Recinto aunque el frontend público tuviera un error.
    """

    transmision: TransmisionProyectada
    aviso: AvisoTecnicoProyectado | None


class MensajeTecnicoProyectado(ModeloProyeccion):
    """Mensaje precargado de la biblioteca CSV (WP-055)."""

    mensaje_id: str
    texto: str
    destino: DestinoAvisoTecnico


class BibliotecaMensajesProyectada(ModeloProyeccion):
    """Biblioteca CSV más su condición técnica (WP-055).

    ``disponible=False`` indica que el archivo existe pero no pudo
    interpretarse. En ese caso la lista viaja vacía y el backend rechaza toda
    escritura, para no destruir el contenido que el operador quiso conservar.
    """

    disponible: bool
    motivo: str | None
    detalle: str | None
    mensajes: tuple[MensajeTecnicoProyectado, ...]


class SonidoRecintoProyectado(ModeloProyeccion):
    """Sonido configurado para un evento de la Pantalla del Recinto (WP-065).

    ``ruta`` es siempre una referencia relativa a un asset servido por la
    propia Pantalla del Recinto (``assets/sonidos/…``), validada en servidor:
    el navegador nunca recibe una ruta arbitraria del sistema de archivos.
    """

    evento: str
    ruta: str
    volumen: int


class SonidosRecintoProyectados(ModeloProyeccion):
    """Configuración de audio completa del Recinto y su condición técnica.

    ``disponible=False`` indica que la sección ``[sonidos]`` de
    ``system.toml`` no pudo interpretarse al arrancar el backend. En ese caso
    la lista viaja vacía y ``motivo``/``detalle`` explican el problema, en
    lugar de dejar a la pantalla sin sonidos y sin razón.

    Viaja en los tres estados globales, también en ``SIN_PREPARAR``: la
    transmisión en vivo y los avisos de Apoyo Técnico funcionan fuera de una
    sesión y necesitan sonar igual.
    """

    disponible: bool
    motivo: str | None
    detalle: str | None
    sonidos: tuple[SonidoRecintoProyectado, ...]


class IdentidadInstitucionalProyectada(ModeloProyeccion):
    """Nombre del cuerpo legislativo que la Pantalla del Recinto debe mostrar (WP-084).

    Es deliberadamente el contrato mínimo: un único campo con el texto exacto
    configurado en ``[institucion]``. No se publica el diagnóstico interno
    (``disponible``/``motivo``) porque la pantalla pública no tiene que explicar
    un problema de configuración a la sala: si la identidad no pudo leerse, el
    backend ya sustituyó el valor por un rótulo genérico y quien opera lo
    diagnostica con el archivo delante.

    Viaja en los tres estados globales, también en ``SIN_PREPARAR``: la cabecera
    del Recinto existe desde que la pantalla se enciende, mucho antes de que
    alguien prepare una sesión.
    """

    nombre: str


class ConcejalRemapeoProyectado(ModeloProyeccion):
    """Banca mínima que el panel de remapeo necesita para operar (WP-074).

    Es una **allowlist** deliberadamente corta. El remapeo sólo tiene que poder
    listar bancas elegibles, mostrar de quién es la que se está reemplazando y
    enviar su identificador lógico de dispositivo. No necesita presencia, test
    de dispositivo, bloque ni imagen, así que esos campos no viajan al puesto
    técnico dentro de esta porción.

    Los campos son exactamente los que lee ``GestionRemapeo.vue``; por eso el
    componente compartido acepta indistintamente esta proyección y la de
    Moderación sin adaptadores ni copias de reglas.
    """

    dni: str
    nombre: str
    apellido: str
    banca: int
    dispositivo_votacion: str


class CapacidadesRemapeoProyectadas(ModeloProyeccion):
    """Las tres capacidades de remapeo, recortadas de ``CapacidadesModeracion``.

    Se copian tal cual del mismo evaluador autoritativo: acá no se recalcula
    ninguna precondición. Si mañana cambiara la regla que habilita confirmar un
    remapeo, cambia en un solo lugar y los dos puestos la heredan.
    """

    iniciar_remapeo: Capacidad
    confirmar_remapeo: Capacidad
    cancelar_remapeo: Capacidad


class RemapeoTecnicoProyectado(ModeloProyeccion):
    """Todo lo que Apoyo Técnico necesita para remapear, y nada más (WP-074).

    Antes de WP-074 el puesto técnico obtenía estos tres datos abriendo una
    segunda suscripción SSE al ``EstadoModeracion`` completo. Con cuatro
    superficies abiertas bajo el mismo origen HTTP/1.1 eso agotaba el cupo de
    conexiones del navegador y los comandos REST quedaban esperando, con
    apariencia de servidor caído.

    La solución no es copiar Moderación acá dentro: es proyectar sólo esta
    allowlist. El puesto técnico sigue sin ver votación, quórum, orden del día,
    autoridades ni las capacidades institucionales que no le corresponden.

    Los nombres de los tres campos coinciden a propósito con los de
    ``EstadoModeracion`` para que el componente compartido de remapeo consuma
    ambas proyecciones sin ninguna traducción intermedia.
    """

    remapeo: EstadoRemapeoModeracion | None
    concejales: tuple[ConcejalRemapeoProyectado, ...]
    capacidades: CapacidadesRemapeoProyectadas


class PersonaSonorizacionProyectada(ModeloProyeccion):
    """Identidad mínima de una persona en la cola o en uso de la palabra.

    Sólo la banca: es la única identidad que el detector de transiciones compara
    para saber si alguien pidió, retiró o recibió la palabra. Nombre y apellido
    no cambian ningún sonido, así que no viajan en esta porción.
    """

    banca: int


class PalabraSonorizacionProyectada(ModeloProyeccion):
    """Cola y orador reducidos a bancas, para deducir los tres sonidos de palabra."""

    cola: tuple[PersonaSonorizacionProyectada, ...]
    orador: PersonaSonorizacionProyectada | None


class VotacionSonorizacionProyectada(ModeloProyeccion):
    """Identidad y recepción de la votación visible, sin ningún dato de voto.

    Los dos sonidos de votación se deducen comparando estos dos campos: una
    identidad nueva ``EN_CURSO`` es una apertura y el paso ``EN_CURSO`` ->
    ``CERRADA`` de la misma identidad es un cierre. Conteos, resultado y votos
    individuales no participan de esa deducción y por eso quedan afuera: la
    frontera de secreto se estrecha en lugar de ampliarse.
    """

    id: str
    # ``str`` y no el enum, exactamente igual que en ``VotacionPublica``: esta
    # porción se deriva de esa proyección y debe poder compararse contra ella
    # sin una conversión intermedia.
    estado_recepcion: str


class BancaSonorizacionProyectada(ModeloProyeccion):
    """Presencia de una banca, que es lo único que distingue los dos sonidos de presencia."""

    banca: int
    presente: bool


class SonorizacionRecintoProyectada(ModeloProyeccion):
    """Subproyección pública mínima que permite sonorizar igual que el Recinto (WP-074).

    ## Por qué existe

    Los quince sonidos de WP-065 no son eventos que publique el backend: se
    deducen comparando dos estados públicos consecutivos. Hasta WP-074 el puesto
    técnico obtenía esos estados abriendo un tercer stream SSE al Recinto. Este
    submodelo transporta, dentro del **único** stream técnico, exactamente los
    campos que esa comparación consulta y ninguno más.

    ## Por qué no expone de más

    Cada campo se construye con el mismo helper que arma la proyección pública
    del Recinto y después se recorta. De ``VotacionPublica`` sólo sobreviven la
    identidad y la recepción; de cada banca, la presencia; de la palabra, las
    bancas. En consecuencia esta porción contiene **menos** información que la
    pantalla del salón, que cualquiera puede mirar: nunca puede convertirse en
    una vía de fuga del secreto temporal del voto.

    ``tecnico`` sí viaja completo porque es el mismo submodelo pequeño que ve el
    Recinto, con el aviso del destino ``RECINTO``. Que se construya con
    ``_apoyo_tecnico`` —el helper que usa la proyección pública— es lo que
    garantiza que un aviso o una transmisión suenen en el puesto técnico en la
    misma revisión en que suenan en el salón.

    ``revision`` se repite acá, además de en el estado técnico que la contiene,
    porque la frontera reactiva usa la revisión del objeto que compara para
    descartar una revisión repetida sin volver a sonar. Desde WP-080 ``instancia``
    la acompaña por el mismo motivo: esa frontera necesita reconocer que dos
    revisiones consecutivas pueden venir de procesos distintos y que, en ese
    caso, la segunda es una baseline nueva y no un hecho que deba sonar.
    """

    instancia: str
    revision: int
    estado_global: EstadoGlobal
    tecnico: ApoyoTecnicoProyectado
    palabra: PalabraSonorizacionProyectada | None
    votacion: VotacionSonorizacionProyectada | None
    concejales: tuple[BancaSonorizacionProyectada, ...]
    sonidos: SonidosRecintoProyectados


class EstadoModeracion(ModeloProyeccion):
    """Snapshot completo y reconstruible del frontend de Moderación.

    ``instancia`` (WP-080) identifica de forma opaca al proceso backend que
    construyó este snapshot. El cliente compara el par ``(instancia, revision)``:
    dentro de una misma instancia la revisión sigue siendo monotónica, y un
    cambio de instancia obliga a adoptar la baseline nueva aunque su revisión
    sea menor.
    """

    instancia: str
    revision: int
    generado_en: datetime
    estado_global: EstadoGlobal
    preparacion: DatosPreparacion | None
    sesion: DatosSesion | None
    configuracion: ConfiguracionProyectada | None
    concejales: tuple[ConcejalModeracion, ...]
    quorum: EstadoQuorum | None
    votacion: VotacionModeracion | None
    palabra: EstadoPalabraModeracion | None
    orden_del_dia: tuple[PuntoOrdenDelDiaProyectado, ...]
    eventos_recientes: tuple[EventoRecienteProyectado, ...]
    auditoria: EstadoAuditoriaProyectado
    remapeo: EstadoRemapeoModeracion | None
    capacidades: CapacidadesModeracion
    tecnico: ApoyoTecnicoProyectado


class EstadoRecinto(ModeloProyeccion):
    """Snapshot público por allowlist, sin capacidades ni auditoría cruda.

    ``instancia`` (WP-080) es el mismo identificador técnico y opaco que viaja en
    las otras dos proyecciones. No agrega información institucional ni nombra a
    nadie: sólo dice qué proceso emitió el snapshot, que es lo que el cliente
    necesita para no descartar la primera revisión de un backend reiniciado.
    """

    instancia: str
    revision: int
    generado_en: datetime
    estado_global: EstadoGlobal
    preparacion: DatosPreparacion | None
    sesion: DatosSesion | None
    filas_bancas: tuple[int, ...] | None
    concejales: tuple[ConcejalPublico, ...]
    quorum: EstadoQuorum | None
    votacion: VotacionPublica | None
    palabra: EstadoPalabraPublico | None
    eventos_publicos: tuple[EventoPublicoProyectado, ...]
    tecnico: ApoyoTecnicoProyectado
    sonidos: SonidosRecintoProyectados
    institucion: IdentidadInstitucionalProyectada


class EstadoTecnico(ModeloProyeccion):
    """Snapshot completo del puesto de Apoyo Técnico (WP-055, consolidado por WP-074).

    Reúne todo lo que ese puesto necesita observar y nada más: el estado de
    transmisión, los avisos vigentes de **ambos** destinos, la biblioteca de
    mensajes precargados, la misma franja de eventos L1/L2/L3 que ve Moderación
    y, desde WP-074, las dos allowlists que faltaban: la del remapeo y la de la
    sonorización.

    ## Por qué WP-074 amplió este DTO

    El puesto técnico observaba tres proyecciones a la vez y abría, por lo
    tanto, tres streams SSE. Con Moderación, Recinto, Simulador y Apoyo Técnico
    abiertos en el mismo navegador y bajo el mismo origen, eso daba seis
    conexiones persistentes: más de las que HTTP/1.1 permite por origen. La
    séptima petición —cualquier comando REST, por ejemplo «Preparar sala»—
    quedaba encolada en el navegador sin llegar nunca al backend, y el operador
    lo vivía como una caída del servidor.

    La corrección consiste en que esta proyección transporte lo que el puesto
    necesitaba pedirles a las otras dos. No se copia ``EstadoModeracion`` ni
    ``EstadoRecinto``: ``remapeo`` y ``sonorizacion`` son allowlists mínimas,
    documentadas en sus propias clases, construidas con los mismos helpers
    autoritativos que usan las otras dos proyecciones.

    ``eventos_recientes`` se construye con el mismo método que la proyección
    de Moderación, de modo que la frontera de secreto de WP-052 se aplica una
    sola vez y no puede divergir entre puestos: mientras el sentido individual
    de un voto siga siendo secreto, tampoco lo ve Apoyo Técnico.

    ``instancia`` (WP-080) viaja acá con el mismo significado que en Moderación y
    Recinto, de modo que las tres superficies apliquen exactamente la misma
    regla de continuidad tras un reinicio del backend.
    """

    instancia: str
    revision: int
    generado_en: datetime
    estado_global: EstadoGlobal
    transmision: TransmisionProyectada
    aviso_moderacion: AvisoTecnicoProyectado | None
    aviso_recinto: AvisoTecnicoProyectado | None
    biblioteca: BibliotecaMensajesProyectada
    eventos_recientes: tuple[EventoRecienteProyectado, ...]
    auditoria: EstadoAuditoriaProyectado
    remapeo: RemapeoTecnicoProyectado
    sonorizacion: SonorizacionRecintoProyectada


class ServicioProyecciones:
    """Construye copias coherentes desde la única fuente de verdad operativa.

    Los relojes civil y monotónico son inyectables. El primero interpreta
    deadlines visibles; el segundo coincide con las expiraciones de test y no
    se ve afectado por ajustes del reloj del sistema.
    """

    def __init__(
        self,
        estado_operativo: EstadoOperativo,
        ejecutor_mutaciones: EjecutorMutaciones,
        coordinador: CoordinadorPublicacion,
        *,
        reloj: Callable[[], datetime] = datetime.now,
        reloj_monotono: Callable[[], float] = time.monotonic,
    ) -> None:
        self._estado = estado_operativo
        self._ejecutor = ejecutor_mutaciones
        self._coordinador = coordinador
        self._reloj = reloj
        self._reloj_monotono = reloj_monotono

    async def obtener_estado_moderacion(self) -> EstadoModeracion:
        """Toma una copia completa bajo el lock compartido."""

        return await self._ejecutor.leer_coherente(self._construir_moderacion)

    async def obtener_estado_recinto(self) -> EstadoRecinto:
        """Toma la proyección pública usando el mismo constructor de REST/SSE."""

        return await self._ejecutor.leer_coherente(self._construir_recinto)

    async def obtener_estado_tecnico(self) -> EstadoTecnico:
        """Toma la proyección del puesto técnico bajo el lock compartido."""

        return await self._ejecutor.leer_coherente(self._construir_tecnico)

    def demora_hasta_proxima_frontera(self) -> float | None:
        """Calcula bajo lock cuánto falta para el próximo cambio de payload.

        El llamador es el temporizador de lifespan y ya utiliza
        ``leer_coherente``. Se ignora el fin de la cuenta regresiva pública de
        una votación porque su DTO expone el deadline absoluto y el frontend
        puede dibujarlo localmente sin una publicación por segundo ni un cambio
        de payload al llegar a cero.

        Las fronteras del plano técnico (WP-055) sí cambian el payload al
        cruzarse —``CUENTA_REGRESIVA`` pasa a ``EN_VIVO`` y un aviso vencido
        desaparece—, por eso se calculan primero y **fuera** de la condición de
        contexto operativo: Apoyo Técnico opera también en ``SIN_PREPARAR``, y
        sin esta llamada no habría forma de publicar esas transiciones sin
        recurrir al polling que el WP prohíbe.
        """

        ahora = self._reloj()
        demoras: list[float] = self._demoras_tecnicas(ahora)

        contexto = self._estado.contexto_operativo_activo()
        if contexto is None:
            return min(demoras) if demoras else None

        ahora_monotono = self._reloj_monotono()
        demoras.extend(
            expiracion - ahora_monotono
            for expiracion in contexto.expiraciones_test.values()
            if expiracion > ahora_monotono
        )

        # El revelado se evalúa sobre todas las votaciones conocidas y no solo
        # sobre la relevante: el panel de eventos puede seguir mostrando votos
        # de una votación anterior cuya frontera todavía no venció, y esa fila
        # debe enriquecerse sola, sin esperar a que ocurra otra mutación.
        for votacion_conocida in self._votaciones_conocidas():
            demora_revelado = (
                self._revelado_individual_desde(contexto, votacion_conocida) - ahora
            ).total_seconds()
            if demora_revelado > 0:
                demoras.append(demora_revelado)

        votacion = self._votacion_relevante()
        if votacion is not None:
            limite = self._resultado_visible_hasta(contexto, votacion)
            if limite is not None:
                demora_resultado = (limite - ahora).total_seconds()
                if demora_resultado > 0:
                    demoras.append(demora_resultado)

        return min(demoras) if demoras else None

    def _construir_moderacion(self) -> EstadoModeracion:
        """Construye el DTO sin devolver referencias mutables del dominio."""

        generado_en = self._reloj()
        monotono = self._reloj_monotono()
        contexto = self._estado.contexto_operativo_activo()
        sesion = self._estado.sesion_activa
        return EstadoModeracion(
            instancia=self._coordinador.instancia,
            revision=self._coordinador.revision,
            generado_en=generado_en,
            estado_global=self._estado.estado_global,
            preparacion=self._datos_preparacion(contexto),
            sesion=self._datos_sesion(sesion),
            configuracion=(
                self._configuracion(contexto.configuracion) if contexto is not None else None
            ),
            concejales=self._concejales_moderacion(contexto, generado_en, monotono),
            quorum=self._quorum(contexto),
            votacion=self._votacion_moderacion(contexto, generado_en),
            palabra=self._palabra_moderacion(sesion, contexto),
            orden_del_dia=self._orden_del_dia(contexto, sesion),
            eventos_recientes=self._eventos(contexto, generado_en),
            auditoria=self._auditoria(contexto),
            remapeo=self._remapeo(self._estado.remapeo_activo),
            capacidades=self._capacidades(contexto),
            tecnico=self._apoyo_tecnico(
                self._estado.aviso_tecnico_moderacion,
                generado_en,
            ),
        )

    def _construir_recinto(self) -> EstadoRecinto:
        """Construye por allowlist el DTO que protege el secreto en servidor."""

        generado_en = self._reloj()
        monotono = self._reloj_monotono()
        contexto = self._estado.contexto_operativo_activo()
        sesion = self._estado.sesion_activa
        return EstadoRecinto(
            instancia=self._coordinador.instancia,
            revision=self._coordinador.revision,
            generado_en=generado_en,
            estado_global=self._estado.estado_global,
            preparacion=self._datos_preparacion(contexto),
            sesion=self._datos_sesion(sesion),
            # La disposición pertenece a la configuración congelada de esta
            # preparación. Copiar la tupla exacta evita que el frontend deba
            # inferir filas desde el padrón o asumir una matriz rectangular.
            filas_bancas=(contexto.configuracion.filas_bancas if contexto is not None else None),
            concejales=self._concejales_publicos(contexto, generado_en, monotono),
            quorum=self._quorum(contexto),
            votacion=self._votacion_publica(contexto, generado_en),
            palabra=self._palabra_publica(sesion, contexto),
            eventos_publicos=self._eventos_publicos(contexto),
            # El Recinto recibe la ranura del Recinto y nunca la de Moderación:
            # la separación por destino se decide en servidor, igual que el
            # secreto de voto, y no depende de que el frontend público filtre.
            tecnico=self._apoyo_tecnico(self._estado.aviso_tecnico_recinto, generado_en),
            # Los sonidos no dependen de ``contexto``: se leen del estado
            # operativo, que los conserva desde el arranque del proceso. Por eso
            # viajan también en SIN_PREPARAR, que es exactamente lo que pide
            # WP-065.
            sonidos=self._sonidos(self._estado.sonidos_recinto),
            # La identidad institucional sigue exactamente la misma regla que
            # los sonidos y por el mismo motivo: no depende de ``contexto``, se
            # lee del estado operativo y por eso viaja también en SIN_PREPARAR,
            # que es donde WP-084 exige verla.
            institucion=self._institucion(self._estado.identidad_institucional),
        )

    def _construir_tecnico(self) -> EstadoTecnico:
        """Construye el DTO del puesto técnico con la misma fuente de verdad.

        Reutiliza ``_eventos`` y ``_auditoria`` sin variantes propias: si un WP
        posterior endurece la frontera de secreto, Apoyo Técnico la hereda
        automáticamente y no puede quedar como una vía de fuga olvidada.

        Desde WP-074 arma además las dos porciones que el puesto obtenía antes
        abriendo streams adicionales. Las dos se construyen acá, bajo el mismo
        lock y en la misma revisión que el resto del snapshot, de modo que el
        remapeo y el sonido nunca describan un instante distinto del que
        muestran los demás paneles.
        """

        generado_en = self._reloj()
        monotono = self._reloj_monotono()
        contexto = self._estado.contexto_operativo_activo()
        sesion = self._estado.sesion_activa
        return EstadoTecnico(
            instancia=self._coordinador.instancia,
            revision=self._coordinador.revision,
            generado_en=generado_en,
            estado_global=self._estado.estado_global,
            transmision=self._transmision(generado_en),
            aviso_moderacion=self._aviso_proyectado(
                self._estado.aviso_tecnico_moderacion,
                generado_en,
            ),
            aviso_recinto=self._aviso_proyectado(
                self._estado.aviso_tecnico_recinto,
                generado_en,
            ),
            biblioteca=self.proyectar_biblioteca(self._estado.biblioteca_mensajes_tecnicos),
            eventos_recientes=self._eventos(contexto, generado_en),
            auditoria=self._auditoria(contexto),
            remapeo=self._remapeo_tecnico(contexto),
            sonorizacion=self._sonorizacion(contexto, sesion, generado_en, monotono),
        )

    def _remapeo_tecnico(self, contexto: Preparacion | None) -> RemapeoTecnicoProyectado:
        """Recorta a la allowlist de remapeo lo que ya construyó Moderación.

        No hay ninguna regla nueva acá: la operación activa sale del mismo
        ``_remapeo`` que ve Moderación, las capacidades del mismo
        ``_capacidades`` y el padrón del mismo ``_concejales_moderacion``. Lo
        único propio de este método es **quitar** campos, que es exactamente lo
        que WP-074 pide para no convertir la proyección técnica en una copia del
        estado de Moderación.

        Nótese que el padrón se recorre sin presencia ni test de dispositivo: el
        panel de remapeo no los usa, así que tampoco los recibe.
        """

        capacidades = self._capacidades(contexto)
        concejales = (
            ()
            if contexto is None
            else tuple(
                ConcejalRemapeoProyectado(
                    dni=concejal.dni,
                    nombre=concejal.nombre,
                    apellido=concejal.apellido,
                    banca=concejal.banca,
                    dispositivo_votacion=concejal.dispositivo_votacion,
                )
                for concejal in contexto.padron.concejales
            )
        )
        return RemapeoTecnicoProyectado(
            remapeo=self._remapeo(self._estado.remapeo_activo),
            concejales=concejales,
            capacidades=CapacidadesRemapeoProyectadas(
                iniciar_remapeo=capacidades.iniciar_remapeo,
                confirmar_remapeo=capacidades.confirmar_remapeo,
                cancelar_remapeo=capacidades.cancelar_remapeo,
            ),
        )

    def _sonorizacion(
        self,
        contexto: Preparacion | None,
        sesion: Sesion | None,
        generado_en: datetime,
        monotono: float,
    ) -> SonorizacionRecintoProyectada:
        """Deriva la porción sonora **desde la proyección pública**, y la recorta.

        Éste es el punto donde se juega la paridad exigida por WP-071 y
        preservada por WP-074: cada campo se calcula con el mismo helper que
        arma ``EstadoRecinto`` y recién después se reduce a lo que el detector
        de transiciones compara. Si mañana cambiara, por ejemplo, la ventana de
        visibilidad de una votación pública, el puesto técnico la heredaría sola
        y seguiría sonando en el mismo instante que el salón.

        El recorte también es una decisión de seguridad: al pasar por
        ``_votacion_publica`` se hereda el secreto temporal del voto, y al
        quedarse sólo con la identidad y la recepción se descartan además los
        conteos y los votos individuales que la pantalla del salón sí puede
        mostrar una vez cerrada la votación.
        """

        palabra_publica = self._palabra_publica(sesion, contexto)
        votacion_publica = self._votacion_publica(contexto, generado_en)
        return SonorizacionRecintoProyectada(
            instancia=self._coordinador.instancia,
            revision=self._coordinador.revision,
            estado_global=self._estado.estado_global,
            # Misma ranura que recibe el Recinto: el puesto técnico debe sonar
            # con el aviso del salón, no con el suyo propio.
            tecnico=self._apoyo_tecnico(self._estado.aviso_tecnico_recinto, generado_en),
            palabra=(
                None
                if palabra_publica is None
                else PalabraSonorizacionProyectada(
                    cola=tuple(
                        PersonaSonorizacionProyectada(banca=persona.banca)
                        for persona in palabra_publica.cola
                    ),
                    orador=(
                        None
                        if palabra_publica.orador is None
                        else PersonaSonorizacionProyectada(banca=palabra_publica.orador.banca)
                    ),
                )
            ),
            votacion=(
                None
                if votacion_publica is None
                else VotacionSonorizacionProyectada(
                    id=votacion_publica.id,
                    estado_recepcion=votacion_publica.estado_recepcion,
                )
            ),
            concejales=tuple(
                BancaSonorizacionProyectada(banca=concejal.banca, presente=concejal.presente)
                for concejal in self._concejales_publicos(contexto, generado_en, monotono)
            ),
            sonidos=self._sonidos(self._estado.sonidos_recinto),
        )

    @staticmethod
    def _sonidos(configuracion: ConfiguracionSonidosRecinto) -> SonidosRecintoProyectados:
        """Copia la configuración de audio a DTOs inmutables (WP-065).

        No filtra ni reordena: publica los quince sonidos en el orden canónico
        del contrato para que dos snapshots con la misma configuración sean
        idénticos byte a byte.
        """

        return SonidosRecintoProyectados(
            disponible=configuracion.disponible,
            motivo=configuracion.motivo,
            detalle=configuracion.detalle,
            sonidos=tuple(
                SonidoRecintoProyectado(
                    evento=sonido.evento,
                    ruta=sonido.ruta,
                    volumen=sonido.volumen,
                )
                for sonido in configuracion.sonidos
            ),
        )

    @staticmethod
    def _institucion(identidad: IdentidadInstitucional) -> IdentidadInstitucionalProyectada:
        """Copia el nombre institucional al DTO público (WP-084).

        No recorta espacios ni aplica mayúsculas: el criterio del WP es que el
        Recinto muestre *exactamente* el valor configurado. Cuando la lectura de
        arranque falló, ``identidad.nombre`` ya trae el rótulo genérico, así que
        acá no hay ninguna decisión que tomar.
        """

        return IdentidadInstitucionalProyectada(nombre=identidad.nombre)

    def _apoyo_tecnico(
        self,
        aviso: AvisoTecnico | None,
        generado_en: datetime,
    ) -> ApoyoTecnicoProyectado:
        """Arma la porción técnica que corresponde a un único destino."""

        return ApoyoTecnicoProyectado(
            transmision=self._transmision(generado_en),
            aviso=self._aviso_proyectado(aviso, generado_en),
        )

    def _transmision(self, generado_en: datetime) -> TransmisionProyectada:
        """Deriva el estado observable de la transmisión desde el reloj.

        ``segundos_restantes`` se acota con ``max(0.0, ...)`` para que nunca
        viaje un valor negativo si el temporizador despierta con unos
        microsegundos de retraso respecto de la frontera exacta.
        """

        transmision = self._estado.transmision_tecnica
        estado = estado_transmision(transmision, generado_en)
        if transmision is None:
            return TransmisionProyectada(
                estado=estado,
                iniciada_en=None,
                en_vivo_desde=None,
                cuenta_regresiva_segundos=None,
                segundos_restantes=None,
            )
        restantes = (
            max(0.0, (transmision.en_vivo_desde - generado_en).total_seconds())
            if estado is EstadoTransmision.CUENTA_REGRESIVA
            else None
        )
        return TransmisionProyectada(
            estado=estado,
            iniciada_en=transmision.iniciada_en,
            en_vivo_desde=transmision.en_vivo_desde,
            cuenta_regresiva_segundos=transmision.cuenta_regresiva_segundos,
            segundos_restantes=restantes,
        )

    @staticmethod
    def _aviso_proyectado(
        aviso: AvisoTecnico | None,
        generado_en: datetime,
    ) -> AvisoTecnicoProyectado | None:
        """Publica el aviso solamente mientras sigue vigente.

        Un aviso vencido no se elimina del dominio: simplemente deja de
        proyectarse. Esa es la diferencia entre "expirar" y "cancelar", y es lo
        que hace que la expiración sea autoritativa aunque nadie ejecute un
        comando en ese instante.
        """

        if aviso is None or not aviso.vigente(generado_en):
            return None
        restantes = (
            None
            if aviso.expira_en is None
            else max(0.0, (aviso.expira_en - generado_en).total_seconds())
        )
        return AvisoTecnicoProyectado(
            aviso_id=aviso.aviso_id,
            texto=aviso.texto,
            destino=aviso.destino,
            publicado_en=aviso.publicado_en,
            expira_en=aviso.expira_en,
            segundos_restantes=restantes,
        )

    @staticmethod
    def proyectar_biblioteca(
        biblioteca: BibliotecaMensajesTecnicos,
    ) -> BibliotecaMensajesProyectada:
        """Copia la biblioteca a DTOs inmutables sin exponer el dominio.

        Es público (y estático) porque el recurso REST de la biblioteca
        devuelve exactamente el mismo submodelo que viaja dentro de
        ``EstadoTecnico``. Compartir el constructor evita que ambos caminos
        publiquen formas distintas del mismo dato.
        """

        return BibliotecaMensajesProyectada(
            disponible=biblioteca.disponible,
            motivo=biblioteca.motivo,
            detalle=biblioteca.detalle,
            mensajes=tuple(
                MensajeTecnicoProyectado(
                    mensaje_id=mensaje.mensaje_id,
                    texto=mensaje.texto,
                    destino=mensaje.destino,
                )
                for mensaje in biblioteca.mensajes
            ),
        )

    def _demoras_tecnicas(self, ahora: datetime) -> list[float]:
        """Calcula las fronteras temporales del plano técnico pendientes.

        Son dos clases de frontera y ambas cambian el payload observable:

        - el fin de la cuenta regresiva, que convierte ``CUENTA_REGRESIVA`` en
          ``EN_VIVO``;
        - el vencimiento de cada aviso con duración, que lo retira del DTO.

        Cuando ``AMBOS`` publicó el mismo aviso en las dos ranuras, ambas
        aportan la misma demora y ``min`` las colapsa: no genera despertares
        duplicados.
        """

        demoras: list[float] = []
        transmision: TransmisionTecnica | None = self._estado.transmision_tecnica
        if transmision is not None:
            faltante = (transmision.en_vivo_desde - ahora).total_seconds()
            if faltante > 0:
                demoras.append(faltante)

        for aviso in (
            self._estado.aviso_tecnico_moderacion,
            self._estado.aviso_tecnico_recinto,
        ):
            if aviso is None or aviso.expira_en is None:
                continue
            faltante = (aviso.expira_en - ahora).total_seconds()
            if faltante > 0:
                demoras.append(faltante)

        return demoras

    def _datos_preparacion(self, contexto: Preparacion | None) -> DatosPreparacion | None:
        """Expone preparación solo durante ``PREPARANDO``."""

        if contexto is None or self._estado.estado_global is not EstadoGlobal.PREPARANDO:
            return None
        return DatosPreparacion(
            fecha_hora_inicio=contexto.fecha_hora_inicio,
            numero_sesion=contexto.numero_sesion,
            presidencia=contexto.presidencia,
            secretaria_legislativa=contexto.secretaria_legislativa,
        )

    @staticmethod
    def _datos_sesion(sesion: Sesion | None) -> DatosSesion | None:
        """Copia los datos formales si existe una sesión abierta."""

        if sesion is None:
            return None
        return DatosSesion(
            fecha_hora_inicio_preparacion=sesion.contexto_operativo.fecha_hora_inicio,
            fecha_hora_apertura=sesion.fecha_hora_apertura,
            numero_sesion=sesion.numero_sesion,
            presidencia=sesion.presidencia,
            secretaria_legislativa=sesion.secretaria_legislativa,
        )

    @staticmethod
    def _configuracion(configuracion: ConfiguracionSistema) -> ConfiguracionProyectada:
        """Copia los parámetros congelados con nombres propios del DTO."""

        return ConfiguracionProyectada(
            quorum=configuracion.quorum,
            filas_bancas=configuracion.filas_bancas,
            tipos_votacion=configuracion.tipos_votacion,
            duracion_test_segundos=configuracion.device_test_seconds,
            revelado_votos_moderacion_segundos=(configuracion.moderacion_revelado_votos_segundos),
            cuenta_regresiva_recinto_segundos=(
                configuracion.recinto_cuenta_regresiva_inicial_segundos
            ),
            resultado_publico_recinto_segundos=(configuracion.recinto_resultado_publico_segundos),
        )

    @staticmethod
    def _quorum(contexto: Preparacion | None) -> EstadoQuorum | None:
        """Proyecta los tres datos de quórum desde el mapa autoritativo."""

        if contexto is None:
            return None
        return EstadoQuorum(
            cantidad_presentes=contexto.cantidad_presentes(),
            requerido=contexto.configuracion.quorum,
            alcanzado=contexto.quorum_alcanzado(),
        )

    def _concejales_moderacion(
        self,
        contexto: Preparacion | None,
        generado_en: datetime,
        monotono: float,
    ) -> tuple[ConcejalModeracion, ...]:
        """Copia padrón, presencia y test para el operador."""

        if contexto is None:
            return ()
        return tuple(
            ConcejalModeracion(
                dni=concejal.dni,
                nombre=concejal.nombre,
                apellido=concejal.apellido,
                bloque=concejal.bloque,
                banca=concejal.banca,
                dispositivo_votacion=concejal.dispositivo_votacion,
                ruta_imagen=concejal.ruta_imagen,
                presente=contexto.presencias[concejal.dni],
                test_activo=contexto.test_dispositivo_activo(concejal.dni, monotono),
                test_expira_en=self._deadline_test(contexto, concejal.dni, generado_en, monotono),
            )
            for concejal in contexto.padron.concejales
        )

    def _concejales_publicos(
        self,
        contexto: Preparacion | None,
        generado_en: datetime,
        monotono: float,
    ) -> tuple[ConcejalPublico, ...]:
        """Copia solamente campos públicos de cada banca."""

        if contexto is None:
            return ()
        return tuple(
            ConcejalPublico(
                nombre=concejal.nombre,
                apellido=concejal.apellido,
                bloque=concejal.bloque,
                banca=concejal.banca,
                ruta_imagen=concejal.ruta_imagen,
                presente=contexto.presencias[concejal.dni],
                test_activo=contexto.test_dispositivo_activo(concejal.dni, monotono),
                test_expira_en=self._deadline_test(contexto, concejal.dni, generado_en, monotono),
            )
            for concejal in contexto.padron.concejales
        )

    @staticmethod
    def _deadline_test(
        contexto: Preparacion,
        dni: str,
        generado_en: datetime,
        monotono: float,
    ) -> datetime | None:
        """Convierte la expiración monotónica en deadline civil aproximado."""

        expiracion = contexto.expiraciones_test.get(dni)
        if expiracion is None or expiracion <= monotono:
            return None
        return generado_en + timedelta(seconds=expiracion - monotono)

    def _votacion_relevante(self) -> Votacion | None:
        """Selecciona activa o, si ya terminó, la última del historial."""

        if self._estado.votacion_activa is not None:
            return self._estado.votacion_activa
        sesion = self._estado.sesion_activa
        if sesion is None or not sesion.votaciones:
            return None
        return sesion.votaciones[-1]

    def _votaciones_conocidas(self) -> tuple[Votacion, ...]:
        """Devuelve todas las votaciones vivas del contexto operativo actual.

        La sesión conserva su historial en orden de apertura y la votación
        activa siempre pertenece a esa lista. Igualmente se agrega de forma
        defensiva por si el estado se instalara sin pasar por el historial: es
        preferible evaluar una frontera de más que dejar de proteger un voto.
        """

        sesion = self._estado.sesion_activa
        conocidas = list(sesion.votaciones) if sesion is not None else []
        activa = self._estado.votacion_activa
        if activa is not None and activa not in conocidas:
            conocidas.append(activa)
        return tuple(conocidas)

    def _buscar_votacion(self, votacion_id: str) -> Votacion | None:
        """Resuelve por identificador la votación a la que pertenece un hecho.

        Es lo que permite que un evento de una votación anterior siga usando
        **su** frontera de revelado y no la de la votación que casualmente esté
        activa cuando se genera el snapshot.
        """

        for votacion in self._votaciones_conocidas():
            if votacion.id == votacion_id:
                return votacion
        return None

    @staticmethod
    def _revelado_individual_desde(contexto: Preparacion, votacion: Votacion) -> datetime:
        """Calcula la única frontera de revelado individual para Moderación.

        El retardo se cuenta desde la apertura de la votación y proviene de la
        configuración congelada de la preparación. Centralizarlo garantiza que
        la grilla de votos y el panel de eventos no puedan aplicar dos políticas
        de secreto distintas sobre el mismo hecho.
        """

        return votacion.fecha_hora_apertura + timedelta(
            seconds=contexto.configuracion.moderacion_revelado_votos_segundos
        )

    def _votacion_moderacion(
        self,
        contexto: Preparacion | None,
        generado_en: datetime,
    ) -> VotacionModeracion | None:
        """Aplica el retardo global desde la apertura, nunca por voto."""

        votacion = self._votacion_relevante()
        if contexto is None or votacion is None:
            return None
        revelado_desde = self._revelado_individual_desde(contexto, votacion)
        revelados = generado_en >= revelado_desde
        votos = self._votos_moderacion(contexto, votacion) if revelados else None
        conteos = self._conteos(votacion) if revelados else None
        presidencial = votacion.voto_desempate
        resultado_visible_hasta = self._resultado_visible_hasta(contexto, votacion)
        return VotacionModeracion(
            id=votacion.id,
            numero_votacion=votacion.numero_votacion,
            tipo=votacion.tipo,
            tema=votacion.tema,
            tipo_mayoria=votacion.tipo_mayoria.value,
            factor=votacion.factor,
            base=votacion.base.value,
            estado_recepcion=votacion.estado.value,
            resultado=votacion.resultado.value if votacion.resultado is not None else None,
            fecha_hora_apertura=votacion.fecha_hora_apertura,
            fecha_hora_cierre=votacion.fecha_hora_cierre,
            fecha_hora_resultado=votacion.fecha_hora_resultado,
            resultado_visible_hasta=resultado_visible_hasta,
            motivo_finalizacion_manual=votacion.motivo_finalizacion_manual,
            cantidad_votos_recibidos=len(votacion.votos_ordinarios),
            bancas_voto_emitido=self._bancas_voto_emitido(contexto, votacion),
            revelado_individual_desde=revelado_desde,
            votos_individuales_revelados=revelados,
            votos_individuales=votos,
            conteos=conteos,
            voto_presidencial=(
                VotoPresidencialProyectado(
                    presidencia=presidencial.presidencia,
                    sentido=presidencial.sentido.value,
                )
                if presidencial is not None
                else None
            ),
        )

    def _votacion_publica(
        self,
        contexto: Preparacion | None,
        generado_en: datetime,
    ) -> VotacionPublica | None:
        """Omite votos EN_CURSO y expira solo los resultados finales."""

        votacion = self._votacion_relevante()
        if contexto is None or votacion is None:
            return None

        resultado_visible_hasta = self._resultado_visible_hasta(contexto, votacion)
        if resultado_visible_hasta is not None and generado_en >= resultado_visible_hasta:
            return None

        en_curso = votacion.estado is EstadoVotacion.EN_CURSO
        votos = None if en_curso else self._votos_publicos(contexto, votacion)
        conteos = None if en_curso else self._conteos(votacion)
        presidencial = votacion.voto_desempate
        # En el estado parcial EMPATADA + voto presidencial todavía no existe
        # un resultado final auditado. Omitir el sentido evita inferirlo en la
        # pantalla pública; Moderación sí ve el último hecho durable.
        exponer_presidencial = presidencial is not None and votacion.resultado in (
            ResultadoVotacion.APROBADA,
            ResultadoVotacion.RECHAZADA,
        )
        return VotacionPublica(
            id=votacion.id,
            numero_votacion=votacion.numero_votacion,
            tipo=votacion.tipo,
            tema=votacion.tema,
            tipo_mayoria=votacion.tipo_mayoria.value,
            factor=votacion.factor,
            base=votacion.base.value,
            estado_recepcion=votacion.estado.value,
            resultado=votacion.resultado.value if votacion.resultado is not None else None,
            fecha_hora_apertura=votacion.fecha_hora_apertura,
            fecha_hora_cierre=votacion.fecha_hora_cierre,
            cuenta_regresiva_hasta=(
                votacion.fecha_hora_apertura
                + timedelta(
                    seconds=contexto.configuracion.recinto_cuenta_regresiva_inicial_segundos
                )
                if en_curso
                else None
            ),
            resultado_visible_hasta=resultado_visible_hasta,
            bancas_voto_emitido=self._bancas_voto_emitido(contexto, votacion),
            votos_individuales=votos,
            conteos=conteos,
            voto_presidencial=(
                VotoPresidencialProyectado(
                    presidencia=presidencial.presidencia,
                    sentido=presidencial.sentido.value,
                )
                if exponer_presidencial and presidencial is not None
                else None
            ),
        )

    @staticmethod
    def _resultado_visible_hasta(
        contexto: Preparacion,
        votacion: Votacion,
    ) -> datetime | None:
        """Calcula la única frontera temporal de las bancas Q3 y Recinto.

        El resultado institucional permanece en el dominio y en la proyección de
        Moderación. Este deadline gobierna solamente cuánto tiempo las tarjetas de
        ambas superficies pueden pintar sentidos individuales. Centralizar el
        cálculo evita que Q3 agregue un temporizador propio o que use una duración
        distinta de la pantalla pública.

        ``EMPATADA`` no expira mientras espera a Presidencia. Cuando el desempate
        produce un resultado final, ``fecha_hora_resultado`` cambia y comienza una
        ventana completa desde ese hecho durable.
        """

        if votacion.resultado not in (
            ResultadoVotacion.APROBADA,
            ResultadoVotacion.RECHAZADA,
            ResultadoVotacion.INCONCLUSA,
        ):
            return None

        disponible_desde = votacion.fecha_hora_resultado
        if disponible_desde is None:
            raise RuntimeError("Resultado final sin fecha de disponibilidad")
        return disponible_desde + timedelta(
            seconds=contexto.configuracion.recinto_resultado_publico_segundos
        )

    def _bancas_voto_emitido(
        self,
        contexto: Preparacion | None,
        votacion: Votacion,
    ) -> tuple[int, ...]:
        """Deriva qué bancas ya emitieron voto, sin revelar el sentido (WP-045).

        Responde exclusivamente a la pregunta autorizada por HUMAN_GATE
        "¿esta banca ya emitió su voto?". Para no filtrar el secreto del voto
        mientras la recepción sigue abierta, la tupla:

        - se construye únicamente desde el mapa autoritativo
          ``votacion.votos_ordinarios``, es decir la misma fuente que ya usan los
          conteos; nunca desde auditoría, eventos, UI ni timestamps;
        - traduce DNI a número de banca contra el padrón congelado de la
          preparación, de modo que el payload no transporte identidad personal;
        - se ordena ascendentemente por banca, de manera que el orden del payload
          no codifique en qué orden temporal votó cada concejal;
        - queda vacía fuera de ``EN_CURSO``, porque una vez cerrada la recepción
          el sentido final ya viaja por su propio contrato de votos individuales
          y este campo dejaría de aportar información nueva.

        Args:
            contexto: preparación congelada con el padrón; ``None`` significa que
                todavía no hay padrón contra el cual resolver bancas.
            votacion: votación relevante del snapshot.

        Returns:
            Tupla ordenada y sin duplicados de números de banca. El propio
            ``dict`` de votos ya impide duplicados: hay a lo sumo un voto por DNI.
        """

        if contexto is None or votacion.estado is not EstadoVotacion.EN_CURSO:
            return ()
        bancas = [self._buscar_concejal(contexto, dni).banca for dni in votacion.votos_ordinarios]
        return tuple(sorted(bancas))

    @staticmethod
    def _conteos(votacion: Votacion) -> ConteosVotosProyectados:
        """Deriva conteos de los votos ordinarios en el instante del snapshot."""

        conteos = votacion.contar_votos_ordinarios()
        return ConteosVotosProyectados(
            positivos=conteos.positivos,
            negativos=conteos.negativos,
            abstenciones=conteos.abstenciones,
            total=conteos.votos_emitidos,
        )

    @staticmethod
    def _buscar_concejal(contexto: Preparacion, dni: str) -> Concejal:
        """Resuelve un DNI contra el padrón congelado sin cache paralelo."""

        for concejal in contexto.padron.concejales:
            if concejal.dni == dni:
                return concejal
        raise RuntimeError(f"Voto o palabra con DNI ausente del padrón: {dni}")

    def _votos_moderacion(
        self,
        contexto: Preparacion,
        votacion: Votacion,
    ) -> tuple[VotoModeracion, ...]:
        """Ordena por banca los votos revelados y copia su identidad completa."""

        votos: list[VotoModeracion] = []
        for dni, voto in votacion.votos_ordinarios.items():
            concejal = self._buscar_concejal(contexto, dni)
            votos.append(
                VotoModeracion(
                    dni=dni,
                    nombre=concejal.nombre,
                    apellido=concejal.apellido,
                    banca=concejal.banca,
                    valor=voto.valor.value,
                )
            )
        return tuple(sorted(votos, key=lambda voto: voto.banca))

    def _votos_publicos(
        self,
        contexto: Preparacion,
        votacion: Votacion,
    ) -> tuple[VotoPublico, ...]:
        """Construye votos públicos sin transportar DNI ni objetos de dominio."""

        votos: list[VotoPublico] = []
        for dni, voto in votacion.votos_ordinarios.items():
            concejal = self._buscar_concejal(contexto, dni)
            votos.append(
                VotoPublico(
                    nombre=concejal.nombre,
                    apellido=concejal.apellido,
                    banca=concejal.banca,
                    valor=voto.valor.value,
                )
            )
        return tuple(sorted(votos, key=lambda voto: voto.banca))

    def _palabra_moderacion(
        self,
        sesion: Sesion | None,
        contexto: Preparacion | None,
    ) -> EstadoPalabraModeracion | None:
        """Copia FIFO y orador con identidad de Moderación."""

        if sesion is None or contexto is None:
            return None
        return EstadoPalabraModeracion(
            cola=tuple(
                self._persona_palabra_moderacion(contexto, dni) for dni in sesion.palabra.cola_dnis
            ),
            orador=(
                self._persona_palabra_moderacion(contexto, sesion.palabra.orador_dni)
                if sesion.palabra.orador_dni is not None
                else None
            ),
        )

    def _palabra_publica(
        self,
        sesion: Sesion | None,
        contexto: Preparacion | None,
    ) -> EstadoPalabraPublico | None:
        """Copia FIFO y orador omitiendo DNI."""

        if sesion is None or contexto is None:
            return None
        return EstadoPalabraPublico(
            cola=tuple(
                self._persona_palabra_publica(contexto, dni) for dni in sesion.palabra.cola_dnis
            ),
            orador=(
                self._persona_palabra_publica(contexto, sesion.palabra.orador_dni)
                if sesion.palabra.orador_dni is not None
                else None
            ),
        )

    def _persona_palabra_moderacion(
        self,
        contexto: Preparacion,
        dni: str,
    ) -> PersonaPalabraModeracion:
        """Resuelve una identidad interna para la cola de Moderación."""

        concejal = self._buscar_concejal(contexto, dni)
        return PersonaPalabraModeracion(
            dni=dni,
            nombre=concejal.nombre,
            apellido=concejal.apellido,
            banca=concejal.banca,
        )

    def _persona_palabra_publica(
        self,
        contexto: Preparacion,
        dni: str,
    ) -> PersonaPalabraPublica:
        """Resuelve una identidad segura para la cola pública."""

        concejal = self._buscar_concejal(contexto, dni)
        return PersonaPalabraPublica(
            nombre=concejal.nombre,
            apellido=concejal.apellido,
            banca=concejal.banca,
        )

    @staticmethod
    def _numeros_votacion_tratados(sesion: Sesion | None) -> frozenset[int]:
        """Deriva del historial de la sesión los números ya abiertos.

        ``Sesion.votaciones`` recibe cada votación en el momento exacto de su
        apertura (``ServicioVotacion`` la agrega recién después de auditar), así
        que basta con recorrerlo: no hace falta que la votación esté finalizada
        para considerar tratado su número, ni existe otra fuente que pueda
        contradecirlo. Sin sesión abierta —``SIN_PREPARAR`` o ``PREPARANDO``— no
        hay historial y ningún punto puede estar tratado todavía.

        Args:
            sesion: sesión formal activa, o ``None`` si no hay ninguna.

        Returns:
            Conjunto inmutable de ``numero_votacion`` ya abiertos en la sesión.
        """

        if sesion is None:
            return frozenset()
        return frozenset(votacion.numero_votacion for votacion in sesion.votaciones)

    @classmethod
    def _orden_del_dia(
        cls,
        contexto: Preparacion | None,
        sesion: Sesion | None,
    ) -> tuple[PuntoOrdenDelDiaProyectado, ...]:
        """Copia la colección temporal marcando los números ya tratados.

        La comparación usa exclusivamente ``nro_votacion``: no se miran tema,
        tipo ni mayoría. Por eso, si el CSV repite un número, todas las filas que
        lo comparten quedan marcadas a la vez, que es exactamente la ayuda que
        pidió WP-053. Sin colección cargada se devuelve una tupla vacía.
        """

        if contexto is None or contexto.orden_del_dia is None:
            return ()
        numeros_tratados = cls._numeros_votacion_tratados(sesion)
        return tuple(
            PuntoOrdenDelDiaProyectado(
                nro_votacion=punto.nro_votacion,
                tipo=punto.tipo,
                tema=punto.tema,
                tipo_mayoria=punto.tipo_mayoria.value,
                factor=punto.factor,
                base=punto.base.value,
                tratado=punto.nro_votacion in numeros_tratados,
            )
            for punto in contexto.orden_del_dia
        )

    def _eventos(
        self,
        contexto: Preparacion | None,
        generado_en: datetime,
    ) -> tuple[EventoRecienteProyectado, ...]:
        """Copia hasta 200 eventos confirmados aplicando la frontera de secreto."""

        if contexto is None:
            return ()
        return tuple(
            self._evento(evento, contexto, generado_en)
            for evento in contexto.escritor_auditoria.eventos_recientes
        )

    @staticmethod
    def _eventos_publicos(
        contexto: Preparacion | None,
    ) -> tuple[EventoPublicoProyectado, ...]:
        """Filtra y sanitiza los últimos hechos aptos para la pantalla pública.

        La fuente es el mismo buffer que Moderación consume, cuyos elementos se
        incorporan únicamente después del último ``fsync``. Primero se exige
        nivel L3, luego se consulta la allowlist por código y finalmente se
        recortan los veinte hechos permitidos más recientes. El orden ascendente
        original se conserva para que el evento más nuevo quede al final de la
        franja y el frontend pueda hacer un auto-scroll sencillo.

        ``evento.mensaje`` no se lee ni se transforma. Esto es una frontera de
        seguridad: un mensaje con DNI, tecla, dispositivo o sentido individual
        jamás alcanza siquiera el constructor del DTO público.
        """

        if contexto is None:
            return ()

        eventos: list[EventoPublicoProyectado] = []
        for evento in contexto.escritor_auditoria.eventos_recientes:
            if evento.nivel is not NivelAuditoria.L3:
                continue
            traduccion = MAPEO_EVENTOS_PUBLICOS.get(evento.codigo_evento)
            if traduccion is None:
                continue
            categoria, texto = traduccion
            eventos.append(
                EventoPublicoProyectado(
                    seq=evento.secuencia,
                    timestamp=evento.timestamp,
                    categoria=categoria,
                    codigo_evento=evento.codigo_evento,
                    texto=texto,
                )
            )

        return tuple(eventos[-LIMITE_EVENTOS_PUBLICOS:])

    def _evento(
        self,
        evento: EventoAuditoriaReciente,
        contexto: Preparacion,
        generado_en: datetime,
    ) -> EventoRecienteProyectado:
        """Traduce las seis dimensiones canónicas y agrega el hecho estructurado.

        El paso decisivo es ``revelable``: se calcula una sola vez por evento y
        gobierna a la vez qué mensaje se publica y si el hecho puede llevar
        sentido e icono. Al derivarse del estado autoritativo y no del texto de
        auditoría, un cambio de redacción futuro no puede abrir una fuga.

        Args:
            evento: hecho ya confirmado en los tres CSV correspondientes.
            contexto: preparación vigente, con padrón y configuración congelados.
            generado_en: hora civil del snapshot, la misma que usa el resto de
                la proyección para evaluar fronteras temporales.

        Returns:
            El DTO listo para Moderación, sin sentido individual cuando el
            secreto de esa votación sigue vigente.
        """

        referencia = evento.referencia
        revelable = self._sentido_revelable(contexto, referencia, generado_en)
        return EventoRecienteProyectado(
            seq=evento.secuencia,
            timestamp=evento.timestamp,
            nivel=evento.nivel.value,
            etiqueta=evento.etiqueta,
            codigo_evento=evento.codigo_evento,
            mensaje=self._mensaje_evento(evento, revelable),
            hecho=self._hecho_operativo(contexto, referencia, revelable),
        )

    @staticmethod
    def _mensaje_evento(evento: EventoAuditoriaReciente, revelable: bool) -> str:
        """Elige entre el mensaje durable y su variante segura.

        Un evento sin referencia, o con referencia que no declaró texto
        alternativo, publica siempre su mensaje original: no se inventa una
        censura donde el emisor no declaró un secreto.
        """

        referencia = evento.referencia
        if revelable or referencia is None or referencia.mensaje_seguro is None:
            return evento.mensaje
        return referencia.mensaje_seguro

    def _sentido_revelable(
        self,
        contexto: Preparacion,
        referencia: ReferenciaHechoOperativo | None,
        generado_en: datetime,
    ) -> bool:
        """Decide si el sentido asociado a un hecho ya puede publicarse.

        Un hecho sin referencia o sin votación asociada nunca fue secreto, así
        que se considera revelable. Si la votación referida ya no existe en el
        contexto vivo, se falla cerrado devolviendo ``False``: ante la duda, el
        secreto se conserva.
        """

        if referencia is None or referencia.votacion_id is None:
            return True
        votacion = self._buscar_votacion(referencia.votacion_id)
        if votacion is None:
            return False
        return generado_en >= self._revelado_individual_desde(contexto, votacion)

    def _hecho_operativo(
        self,
        contexto: Preparacion,
        referencia: ReferenciaHechoOperativo | None,
        revelable: bool,
    ) -> HechoOperativoProyectado | None:
        """Construye la lectura estructurada del hecho, o ``None`` si no aplica.

        Solo los hechos institucionales que el WP pide presentar de forma
        enriquecida producen un DTO. Las pulsaciones sensibles quedan fuera a
        propósito: su protección consiste en publicar el mensaje seguro, no en
        convertirlas en una tarjeta con identidad e icono.
        """

        if referencia is None or referencia.dni is None:
            return None
        if referencia.tipo is TipoHechoOperativo.PULSACION_DE_VOTO:
            return None

        concejal = self._buscar_concejal(contexto, referencia.dni)
        identidad = ConcejalHechoProyectado(
            nombre=concejal.nombre,
            apellido=concejal.apellido,
            banca=concejal.banca,
        )

        if referencia.tipo is TipoHechoOperativo.PEDIDO_PALABRA:
            return HechoOperativoProyectado(
                tipo=referencia.tipo.value,
                concejal=identidad,
                detalle=DETALLE_PEDIDO_PALABRA,
                icono=ICONO_PEDIDO_PALABRA,
                sentido=None,
            )
        if referencia.tipo is TipoHechoOperativo.RETIRO_PALABRA:
            return HechoOperativoProyectado(
                tipo=referencia.tipo.value,
                concejal=identidad,
                detalle=DETALLE_RETIRO_PALABRA,
                icono=ICONO_RETIRO_PALABRA,
                sentido=None,
            )

        # Voto ordinario: el mismo ``seq`` se enriquece más tarde sin cambiar de
        # identidad. El sentido se relee del mapa autoritativo de votos, nunca
        # del buffer de auditoría, para que la única verdad siga siendo la
        # votación y no una copia envejecida del hecho.
        sentido = self._sentido_de_voto(referencia) if revelable else None
        if sentido is None:
            return HechoOperativoProyectado(
                tipo=referencia.tipo.value,
                concejal=identidad,
                detalle=DETALLE_VOTO_SECRETO,
                icono=None,
                sentido=None,
            )
        return HechoOperativoProyectado(
            tipo=referencia.tipo.value,
            concejal=identidad,
            detalle=DETALLE_POR_SENTIDO[sentido],
            icono=ICONO_POR_SENTIDO[sentido],
            sentido=sentido.value,
        )

    def _sentido_de_voto(
        self,
        referencia: ReferenciaHechoOperativo,
    ) -> ValorVotoOrdinario | None:
        """Relee el sentido desde la votación autoritativa referida por el hecho.

        Devuelve ``None`` si la votación o el voto ya no existen, por ejemplo
        ante un evento cuyo contexto quedó fuera del estado vivo. En ese caso el
        hecho se presenta como si el secreto continuara vigente.
        """

        if referencia.votacion_id is None or referencia.dni is None:
            return None
        votacion = self._buscar_votacion(referencia.votacion_id)
        if votacion is None:
            return None
        voto = votacion.votos_ordinarios.get(referencia.dni)
        return voto.valor if voto is not None else None

    @staticmethod
    def _auditoria(contexto: Preparacion | None) -> EstadoAuditoriaProyectado:
        """Distingue ausencia normal de contexto y fallo técnico activo."""

        if contexto is None:
            return EstadoAuditoriaProyectado(
                activa=False,
                disponible=True,
                fallado=False,
                cerrado=False,
                motivo=None,
            )
        escritor = contexto.escritor_auditoria
        disponible = not escritor.fallado and not escritor.cerrado
        motivo = None
        if escritor.fallado:
            motivo = "AUDITORIA_NO_DISPONIBLE"
        elif escritor.cerrado:
            motivo = "AUDITORIA_CERRADA"
        return EstadoAuditoriaProyectado(
            activa=True,
            disponible=disponible,
            fallado=escritor.fallado,
            cerrado=escritor.cerrado,
            motivo=motivo,
        )

    @staticmethod
    def _remapeo(operacion: OperacionRemapeo | None) -> EstadoRemapeoModeracion | None:
        """Copia el submodelo sin incorporarlo a la allowlist de Recinto."""

        if operacion is None:
            return None
        return EstadoRemapeoModeracion(
            remapeo_id=operacion.remapeo_id,
            dispositivo=operacion.dispositivo,
            estado=operacion.estado.value,
            fingerprint_anterior=operacion.fingerprint_anterior,
            candidato=operacion.candidato,
            diagnostico=operacion.diagnostico,
        )

    def _capacidades(self, contexto: Preparacion | None) -> CapacidadesModeracion:
        """Evalúa solo precondiciones que ya existen en el estado actual."""

        estado = self._estado.estado_global
        sesion = self._estado.sesion_activa
        votacion = self._estado.votacion_activa
        remapeo = self._estado.remapeo_activo
        auditoria_no_disponible = contexto is not None and (
            contexto.escritor_auditoria.fallado or contexto.escritor_auditoria.cerrado
        )

        def motivos_estado(*estados_permitidos: EstadoGlobal) -> list[str]:
            return [] if estado in estados_permitidos else ["ESTADO_INCOMPATIBLE"]

        def capacidad(
            motivos: list[str],
            *,
            requiere_auditoria: bool = True,
        ) -> Capacidad:
            """Construye una capacidad sin reemplazar la validación del endpoint.

            La confirmación de remapeo sí requiere auditoría institucional antes
            de ordenar el cambio físico. Iniciar y cancelar son coordinación
            técnica y sus endpoints no escriben un hecho institucional, por lo
            que permanecen disponibles para poder cancelar incluso ante un
            writer cerrado.
            """

            if (
                requiere_auditoria
                and auditoria_no_disponible
                and "AUDITORIA_NO_DISPONIBLE" not in motivos
            ):
                motivos.append("AUDITORIA_NO_DISPONIBLE")
            return Capacidad(habilitada=not motivos, motivos=tuple(motivos))

        motivos_iniciar_remapeo = motivos_estado(
            EstadoGlobal.PREPARANDO,
            EstadoGlobal.SESION_ABIERTA,
        )
        if remapeo is not None:
            motivos_iniciar_remapeo.append("REMAPEO_YA_ACTIVO")

        motivos_confirmar_remapeo = motivos_estado(
            EstadoGlobal.PREPARANDO,
            EstadoGlobal.SESION_ABIERTA,
        )
        if remapeo is None:
            motivos_confirmar_remapeo.append("REMAPEO_NO_COINCIDE")
        elif remapeo.candidato is None:
            motivos_confirmar_remapeo.append("REMAPEO_SIN_CANDIDATO")
        elif remapeo.estado is not EstadoRemapeo.CANDIDATO:
            motivos_confirmar_remapeo.append("REMAPEO_NO_COINCIDE")

        motivos_cancelar_remapeo: list[str] = []
        if remapeo is None:
            motivos_cancelar_remapeo.append("REMAPEO_NO_COINCIDE")

        motivos_abrir_sesion = motivos_estado(EstadoGlobal.PREPARANDO)
        if estado is EstadoGlobal.PREPARANDO and contexto is not None:
            if not contexto.quorum_alcanzado():
                motivos_abrir_sesion.append("QUORUM_INSUFICIENTE")
            if contexto.numero_sesion is None:
                motivos_abrir_sesion.append("NUMERO_SESION_REQUERIDO")
            if contexto.presidencia is None:
                motivos_abrir_sesion.append("PRESIDENCIA_REQUERIDA")
            if contexto.secretaria_legislativa is None:
                motivos_abrir_sesion.append("SECRETARIA_LEGISLATIVA_REQUERIDA")

        motivos_cerrar = motivos_estado(EstadoGlobal.SESION_ABIERTA)
        if (
            estado is EstadoGlobal.SESION_ABIERTA
            and votacion is not None
            and votacion.estado is EstadoVotacion.CERRADA
            and votacion.resultado is None
        ):
            motivos_cerrar.append("VOTACION_PENDIENTE")

        motivos_abrir_votacion = motivos_estado(EstadoGlobal.SESION_ABIERTA)
        if estado is EstadoGlobal.SESION_ABIERTA and sesion is not None:
            if not sesion.contexto_operativo.quorum_alcanzado():
                motivos_abrir_votacion.append("QUORUM_INSUFICIENTE")
            if votacion is not None:
                motivos_abrir_votacion.append("VOTACION_PENDIENTE")

        motivos_finalizar = motivos_estado(EstadoGlobal.SESION_ABIERTA)
        if estado is EstadoGlobal.SESION_ABIERTA and (
            votacion is None
            or votacion.estado is not EstadoVotacion.EN_CURSO
            or votacion.resultado is not None
        ):
            motivos_finalizar.append("VOTACION_NO_EN_CURSO")

        motivos_desempatar = motivos_estado(EstadoGlobal.SESION_ABIERTA)
        if estado is EstadoGlobal.SESION_ABIERTA:
            if (
                votacion is None
                or votacion.estado is not EstadoVotacion.CERRADA
                or votacion.resultado is not ResultadoVotacion.EMPATADA
                or votacion.tipo_mayoria is not TipoMayoria.SIMPLE
            ):
                motivos_desempatar.append("VOTACION_NO_EMPATADA")
            elif votacion.voto_desempate is not None:
                motivos_desempatar.append("DESEMPATE_YA_EMITIDO")

        return CapacidadesModeracion(
            preparar_sala=capacidad(motivos_estado(EstadoGlobal.SIN_PREPARAR)),
            actualizar_preparacion=capacidad(motivos_estado(EstadoGlobal.PREPARANDO)),
            cancelar_preparacion=capacidad(motivos_estado(EstadoGlobal.PREPARANDO)),
            abrir_sesion=capacidad(motivos_abrir_sesion),
            actualizar_sesion=capacidad(motivos_estado(EstadoGlobal.SESION_ABIERTA)),
            cerrar_sesion=capacidad(motivos_cerrar),
            cargar_orden_del_dia=capacidad(
                motivos_estado(EstadoGlobal.PREPARANDO, EstadoGlobal.SESION_ABIERTA)
            ),
            descartar_orden_del_dia=capacidad(
                motivos_estado(EstadoGlobal.PREPARANDO, EstadoGlobal.SESION_ABIERTA)
            ),
            abrir_votacion=capacidad(motivos_abrir_votacion),
            finalizar_votacion=capacidad(motivos_finalizar),
            desempatar=capacidad(motivos_desempatar),
            otorgar_palabra=capacidad(motivos_estado(EstadoGlobal.SESION_ABIERTA)),
            quitar_palabra=capacidad(motivos_estado(EstadoGlobal.SESION_ABIERTA)),
            iniciar_remapeo=capacidad(
                motivos_iniciar_remapeo,
                requiere_auditoria=False,
            ),
            confirmar_remapeo=capacidad(motivos_confirmar_remapeo),
            cancelar_remapeo=capacidad(
                motivos_cancelar_remapeo,
                requiere_auditoria=False,
            ),
        )
