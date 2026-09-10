"""Estado operativo único y volátil de SIS-Leg.

WP-002 estableció el estado que existe al arrancar; WP-005 incorporó la
preparación, WP-008 agregó el contexto real de sesión y WP-009 tipa la votación
activa. WP-055 suma el plano técnico de Apoyo Técnico, que es deliberadamente
independiente del ciclo preparación/sesión: la transmisión y los avisos pueden
operarse también en ``SIN_PREPARAR``. WP-065 agrega por el mismo motivo los
sonidos configurados de la Pantalla del Recinto, y WP-084 la identidad
institucional, que esa pantalla muestra en su cabecera desde el arranque. Las
transiciones las ejecutan los servicios de dominio bajo el serializador único,
nunca este módulo.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from sis_leg_backend.configuracion.modelos import (
    ConfiguracionSonidosRecinto,
    IdentidadInstitucional,
)
from sis_leg_backend.dominio.apoyo_tecnico import (
    AvisoTecnico,
    BibliotecaMensajesTecnicos,
    MarcadorRecintoAbierto,
    MarcadorTransmisionPrincipal,
    TransmisionTecnica,
)
from sis_leg_backend.dominio.preparacion import Preparacion
from sis_leg_backend.dominio.remapeo import OperacionRemapeo
from sis_leg_backend.dominio.sesion import Sesion
from sis_leg_backend.dominio.votacion import Votacion


class EstadoGlobal(StrEnum):
    """Representa las únicas etapas globales permitidas por el dominio.

    Declarar los valores en un tipo evita que servicios futuros guarden textos
    arbitrarios. Que los tres valores existan aquí no habilita sus transiciones:
    cada una es responsabilidad del Work Package que la implementa.
    """

    SIN_PREPARAR = "SIN_PREPARAR"
    PREPARANDO = "PREPARANDO"
    SESION_ABIERTA = "SESION_ABIERTA"


@dataclass(slots=True)
class EstadoOperativo:
    """Contiene la única fuente de verdad funcional durante una ejecución.

    El objeto vive exclusivamente en memoria y comienza sin ninguna entidad
    activa. Los campos se mutan únicamente desde servicios que se ejecutan
    bajo el ``EjecutorMutaciones`` global, de modo que ningún observador
    concurrente puede ver una transición a mitad de camino.

    Atributos:
        estado_global: etapa actual del ciclo de vida (RN-GLOBAL-01).
        preparacion_activa: contexto publicado solamente en ``PREPARANDO``.
        sesion_activa: contexto real publicado solamente en
            ``SESION_ABIERTA``. Compone el mismo objeto operativo que nació en
            la preparación, sin duplicar sus datos.
        votacion_activa: única votación pendiente publicada. Es la misma
            instancia almacenada en el historial de ``Sesion``; ``None`` indica
            que una nueva apertura puede ser evaluada.
        archivos_auditoria_activos: rutas de los tres CSV del conjunto de
            auditoría vigente, en orden L1, L2, L3; tupla vacía cuando no hay
            auditoría abierta. Es una vista derivada del escritor que vive en
            el contexto activo: se expone aquí para que CA-001 (backend recién
            iniciado, sin auditoría abierta) sea verificable sin conocer el
            modelo interno.
        transmision_tecnica: intención vigente del indicador de transmisión, o
            ``None`` cuando está ``APAGADO``. El estado observable
            (``CUENTA_REGRESIVA`` / ``EN_VIVO``) se deriva del reloj al
            proyectar; acá solo vive la frontera temporal absoluta.
        aviso_tecnico_moderacion: aviso técnico dirigido a Moderación, o
            ``None``. Es una ranura independiente de la del Recinto: por eso
            un aviso de un destino nunca puede aparecer en el otro.
        aviso_tecnico_recinto: aviso técnico dirigido al Recinto, o ``None``.
        marcador_recinto_abierto: período de visualización en Recinto cuyo
            evento principal ``INICIO`` ya fue persistido y todavía no fue
            cerrado con su ``FIN`` (WP-078). Vive acá, y no dentro del aviso,
            porque un aviso puede existir sin haber generado marcador —por
            ejemplo si se publicó en ``SIN_PREPARAR``, donde no hay auditoría— y
            porque el período debe poder cerrarse aunque la ranura ya haya sido
            reemplazada por otro texto.
        marcador_transmision_principal: período EN VIVO cuyo evento principal
            ``TRANSMISION_EN_VIVO_INICIADA`` ya fue persistido y todavía no fue
            cerrado con su ``TRANSMISION_EN_VIVO_FINALIZADA`` (WP-096). Vive acá,
            y no dentro de ``transmision_tecnica``, porque esa intención se
            reemplaza entera en cada orden mientras el indicador puede seguir
            encendido sin interrupción.
        biblioteca_mensajes_tecnicos: copia en memoria del CSV de mensajes
            precargados, más su condición técnica. Se carga una sola vez al
            arrancar y se actualiza únicamente después de que una escritura
            atómica confirmó en disco.
        sonidos_recinto: sonidos configurados para la Pantalla del Recinto
            (WP-065). Igual que el plano técnico, es deliberadamente
            independiente del ciclo preparación/sesión: se lee al arrancar el
            proceso para que la Pantalla del Recinto pueda sonar también en
            ``SIN_PREPARAR``, y se refresca desde la configuración congelada
            cada vez que una preparación la vuelve a cargar, de modo que
            durante una sesión coincida exactamente con el snapshot congelado.
        identidad_institucional: nombre del cuerpo legislativo que opera esta
            instalación (WP-084). Sigue exactamente la misma política que los
            sonidos: se lee al arrancar el proceso para que la cabecera pública
            tenga nombre ya en ``SIN_PREPARAR``, y se refresca desde la
            configuración congelada en cada preparación. Mientras la lectura de
            arranque haya fallado conserva el rótulo neutro, que es legible pero
            no nombra ninguna institución concreta.
    """

    estado_global: EstadoGlobal = field(default=EstadoGlobal.SIN_PREPARAR, init=False)
    preparacion_activa: Preparacion | None = field(default=None, init=False)
    sesion_activa: Sesion | None = field(default=None, init=False)
    votacion_activa: Votacion | None = field(default=None, init=False)
    archivos_auditoria_activos: tuple[Path, ...] = field(default=(), init=False)
    remapeo_activo: OperacionRemapeo | None = field(default=None, init=False)
    remapeos_finalizados: dict[str, OperacionRemapeo] = field(
        default_factory=lambda: {}, init=False
    )
    transmision_tecnica: TransmisionTecnica | None = field(default=None, init=False)
    aviso_tecnico_moderacion: AvisoTecnico | None = field(default=None, init=False)
    aviso_tecnico_recinto: AvisoTecnico | None = field(default=None, init=False)
    marcador_recinto_abierto: MarcadorRecintoAbierto | None = field(default=None, init=False)
    marcador_transmision_principal: MarcadorTransmisionPrincipal | None = field(
        default=None, init=False
    )
    biblioteca_mensajes_tecnicos: BibliotecaMensajesTecnicos = field(
        default_factory=BibliotecaMensajesTecnicos, init=False
    )
    sonidos_recinto: ConfiguracionSonidosRecinto = field(
        default_factory=ConfiguracionSonidosRecinto, init=False
    )
    identidad_institucional: IdentidadInstitucional = field(
        default_factory=IdentidadInstitucional, init=False
    )

    def contexto_operativo_activo(self) -> Preparacion | None:
        """Devuelve el único contexto con presencia, test y auditoría activos.

        Durante ``PREPARANDO`` la referencia está en ``preparacion_activa``.
        Durante ``SESION_ABIERTA`` la sesión compone el mismo objeto. Centralizar
        esta selección permite que entradas 8/9 reutilicen una sola lógica sin
        mantener dos mapas de presencia ni dos escritores.
        """

        if self.estado_global is EstadoGlobal.PREPARANDO:
            return self.preparacion_activa
        if self.estado_global is EstadoGlobal.SESION_ABIERTA and self.sesion_activa is not None:
            return self.sesion_activa.contexto_operativo
        return None
