"""Ayudas deterministas para probar snapshots, SSE y fronteras temporales."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import count
from pathlib import Path

from sis_leg_backend.auditoria import EscritorAuditoriaCsv
from sis_leg_backend.configuracion.modelos import (
    Concejal,
    ConfiguracionSistema,
    ConfiguracionSonidosRecinto,
    Padron,
    SonidoRecinto,
)
from sis_leg_backend.configuracion.sonidos_recinto import EVENTOS_SONIDO_RECINTO
from sis_leg_backend.dominio.estado import EstadoGlobal, EstadoOperativo
from sis_leg_backend.dominio.preparacion import Preparacion
from sis_leg_backend.dominio.sesion import Sesion
from sis_leg_backend.dominio.votacion import (
    BaseMayoria,
    TipoMayoria,
    Votacion,
)
from sis_leg_backend.servicios.apoyo_tecnico import ServicioApoyoTecnico
from sis_leg_backend.servicios.proyecciones import ServicioProyecciones
from sis_leg_backend.servicios.publicacion import CoordinadorPublicacion
from sis_leg_backend.servicios.serializacion import EjecutorMutaciones


def sonidos_de_prueba() -> ConfiguracionSonidosRecinto:
    """Construye los quince sonidos obligatorios de WP-065 para una prueba.

    Se derivan del contrato real ``EVENTOS_SONIDO_RECINTO`` en lugar de una
    lista copiada: si el contrato cambiara, las pruebas de proyección lo
    reflejan sin edición manual. El volumen es distinto para cada evento, de
    modo que una proyección que mezclara dos entradas sea detectable.
    """

    return ConfiguracionSonidosRecinto(
        sonidos=tuple(
            SonidoRecinto(
                evento=evento,
                ruta=f"assets/sonidos/{evento.replace('_', '-')}.wav",
                volumen=(indice * 7) % 101,
            )
            for indice, evento in enumerate(EVENTOS_SONIDO_RECINTO)
        )
    )


@dataclass(slots=True)
class RelojManual:
    """Controla en conjunto el reloj civil y el monotónico de una prueba."""

    fecha: datetime
    instante_monotono: float = 1000.0

    def ahora(self) -> datetime:
        """Devuelve la hora civil controlada."""

        return self.fecha

    def monotono(self) -> float:
        """Devuelve el instante monotónico controlado."""

        return self.instante_monotono

    def avanzar(self, segundos: float) -> None:
        """Avanza ambos relojes exactamente la misma duración."""

        self.fecha += timedelta(seconds=segundos)
        self.instante_monotono += segundos


@dataclass(slots=True)
class EntornoProyecciones:
    """Agrupa las instancias únicas usadas por una prueba de proyección."""

    reloj: RelojManual
    estado: EstadoOperativo
    contexto: Preparacion
    coordinador: CoordinadorPublicacion
    ejecutor: EjecutorMutaciones
    servicio: ServicioProyecciones


def crear_entorno_proyecciones(
    tmp_path: Path,
    *,
    revelado_moderacion: float = 4,
    cuenta_regresiva: float = 4,
    resultado_publico: float = 6,
    duracion_test: float = 0.6,
    filas_bancas: tuple[int, ...] = (3,),
) -> EntornoProyecciones:
    """Crea un contexto válido con una disposición de bancas configurable.

    Permitir filas de distinta longitud en esta ayuda hace posible demostrar
    que la proyección pública conserva el contrato físico exacto, sin adaptar
    los datos de prueba a una grilla rectangular.
    """

    reloj = RelojManual(datetime(2026, 8, 24, 10, 0, 0))
    configuracion = ConfiguracionSistema(
        quorum=2,
        filas_bancas=filas_bancas,
        tipos_votacion=("Otro", "Despacho"),
        device_test_seconds=duracion_test,
        moderacion_revelado_votos_segundos=revelado_moderacion,
        recinto_cuenta_regresiva_inicial_segundos=cuenta_regresiva,
        recinto_resultado_publico_segundos=resultado_publico,
        directorio_registros=str(tmp_path / "logs"),
        sonidos_recinto=sonidos_de_prueba(),
    )
    concejales = tuple(
        Concejal(
            dni=f"9000000{numero}",
            nombre=f"Nombre{numero}",
            apellido=f"Apellido{numero}",
            bloque="Bloque de prueba",
            banca=numero,
            dispositivo_votacion=f"P-{numero:02d}",
            ruta_imagen=f"assets/pruebas/banca-{numero}.png",
        )
        for numero in range(1, sum(filas_bancas) + 1)
    )
    escritor = EscritorAuditoriaCsv(
        tmp_path / "logs",
        reloj.ahora(),
        reloj=reloj.ahora,
        sincronizar=lambda _descriptor: None,
    )
    contexto = Preparacion(
        fecha_hora_inicio=reloj.ahora(),
        configuracion=configuracion,
        padron=Padron(concejales=concejales),
        presencias={concejal.dni: False for concejal in concejales},
        escritor_auditoria=escritor,
    )
    estado = EstadoOperativo()
    # Los sonidos viven en el estado operativo, no en el contexto: es lo que
    # permite proyectarlos también en SIN_PREPARAR (WP-065).
    estado.sonidos_recinto = configuracion.sonidos_recinto
    estado.preparacion_activa = contexto
    estado.estado_global = EstadoGlobal.PREPARANDO
    estado.archivos_auditoria_activos = contexto.rutas_auditoria()
    coordinador = CoordinadorPublicacion()
    ejecutor = EjecutorMutaciones(coordinador.publicar)
    servicio = ServicioProyecciones(
        estado,
        ejecutor,
        coordinador,
        reloj=reloj.ahora,
        reloj_monotono=reloj.monotono,
    )
    return EntornoProyecciones(
        reloj=reloj,
        estado=estado,
        contexto=contexto,
        coordinador=coordinador,
        ejecutor=ejecutor,
        servicio=servicio,
    )


def abrir_sesion_prueba(entorno: EntornoProyecciones) -> Sesion:
    """Instala una sesión formal reutilizando exactamente el mismo contexto."""

    contexto = entorno.contexto
    contexto.numero_sesion = 17
    contexto.presidencia = "Presidencia de prueba"
    contexto.secretaria_legislativa = "Secretaría de prueba"
    sesion = Sesion(
        contexto_operativo=contexto,
        fecha_hora_apertura=entorno.reloj.ahora(),
    )
    entorno.estado.preparacion_activa = None
    entorno.estado.sesion_activa = sesion
    entorno.estado.estado_global = EstadoGlobal.SESION_ABIERTA
    return sesion


def abrir_votacion_prueba(
    entorno: EntornoProyecciones,
    *,
    id_votacion: str = "votacion-prueba",
    tipo_mayoria: TipoMayoria = TipoMayoria.SIMPLE,
    numero_votacion: int | None = None,
) -> Votacion:
    """Agrega al historial y publica una única votación ``EN_CURSO``.

    ``numero_votacion`` permite fijar el número externo exacto. Sin él se sigue
    usando la posición en el historial, que es lo que necesitaban las pruebas
    anteriores; con él, WP-053 puede demostrar que la ayuda del Orden del Día
    compara ese número y no el orden de apertura.
    """

    sesion = entorno.estado.sesion_activa or abrir_sesion_prueba(entorno)
    votacion = Votacion(
        id=id_votacion,
        numero_votacion=(
            numero_votacion if numero_votacion is not None else len(sesion.votaciones) + 1
        ),
        tipo="Otro",
        tema="Tema de prueba",
        tipo_mayoria=tipo_mayoria,
        factor=0.0 if tipo_mayoria is TipoMayoria.SIMPLE else 0.6,
        base=(
            BaseMayoria.VOTOS_COMPUTABLES
            if tipo_mayoria is TipoMayoria.SIMPLE
            else BaseMayoria.PRESENTES
        ),
        fecha_hora_apertura=entorno.reloj.ahora(),
    )
    sesion.votaciones.append(votacion)
    entorno.estado.votacion_activa = votacion
    return votacion


def crear_servicio_apoyo_tecnico(
    entorno: EntornoProyecciones,
    ruta_mensajes: Path,
    *,
    identificadores: Iterable[str] = (),
) -> ServicioApoyoTecnico:
    """Construye el servicio técnico atado al reloj y al estado del entorno.

    ``identificadores`` permite fijar los ids generados para que las pruebas
    puedan afirmar igualdad exacta (por ejemplo, que un aviso ``AMBOS`` deja el
    mismo ``aviso_id`` en las dos ranuras). Agotada la secuencia se vuelve a
    numerar de forma determinista, nunca aleatoria.
    """

    secuencia = iter(identificadores)
    contador = count(1)

    def generar() -> str:
        return next(secuencia, None) or f"id-{next(contador)}"

    return ServicioApoyoTecnico(
        entorno.estado,
        entorno.ejecutor,
        ruta_mensajes=ruta_mensajes,
        reloj=entorno.reloj.ahora,
        generar_identificador=generar,
    )
