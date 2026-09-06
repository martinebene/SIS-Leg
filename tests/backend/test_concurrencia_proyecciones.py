"""Carreras deterministas entre snapshots y el único serializador funcional."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from sis_leg_backend.auditoria import ErrorAuditoria, EscritorAuditoriaCsv, NivelAuditoria
from sis_leg_backend.dominio.votacion import (
    ResultadoVotacion,
    SentidoVotoDesempate,
    ValorVotoOrdinario,
    VotoOrdinario,
)
from sis_leg_backend.hechos_operativos import ReferenciaHechoOperativo
from sis_leg_backend.servicios.proyecciones import EstadoModeracion
from sis_leg_backend.servicios.votacion import (
    CODIGO_VOTACION_RESULTADO_DESEMPATE,
    ServicioVotacion,
)

from tests.backend.ayudas_proyecciones import (
    EntornoProyecciones,
    abrir_sesion_prueba,
    abrir_votacion_prueba,
    crear_entorno_proyecciones,
)

pytestmark = pytest.mark.anyio


class EscritorAuditoriaConFallo(EscritorAuditoriaCsv):
    """Provoca un ``fsync`` real fallido solo para un código elegido."""

    def __init__(self, tmp_path: Path, entorno: EntornoProyecciones, codigo: str) -> None:
        self._codigo_objetivo = codigo
        self._fallar_sincronizacion = False
        super().__init__(
            tmp_path / "logs-fallo",
            entorno.reloj.ahora(),
            reloj=entorno.reloj.ahora,
            sincronizar=self._sincronizar_controlado,
        )

    def registrar_evento(
        self,
        nivel: NivelAuditoria,
        etiqueta: str,
        codigo_evento: str,
        mensaje: str,
        *,
        referencia: ReferenciaHechoOperativo | None = None,
    ) -> int:
        """Activa el fallo al entrar al evento objetivo y delega persistencia."""

        self._fallar_sincronizacion = codigo_evento == self._codigo_objetivo
        return super().registrar_evento(
            nivel, etiqueta, codigo_evento, mensaje, referencia=referencia
        )

    def _sincronizar_controlado(self, _descriptor: int) -> None:
        """Falla dentro del escritor para que éste active su estado cerrado."""

        if self._fallar_sincronizacion:
            raise OSError("fallo sintético en el segundo hecho")


async def leer_mientras_mutacion_esta_a_mitad(
    entorno: EntornoProyecciones,
    mutacion: Callable[[asyncio.Event, asyncio.Event], Awaitable[None]],
) -> EstadoModeracion:
    """Demuestra que la lectura intenta entrar pero espera el mismo lock."""

    mitad_alcanzada = asyncio.Event()
    continuar = asyncio.Event()
    lectura_intento_entrar = asyncio.Event()
    lectura_completada = asyncio.Event()

    tarea_mutacion = asyncio.create_task(
        entorno.ejecutor.ejecutar(lambda: mutacion(mitad_alcanzada, continuar))
    )
    await mitad_alcanzada.wait()

    async def leer() -> EstadoModeracion:
        lectura_intento_entrar.set()
        estado = await entorno.servicio.obtener_estado_moderacion()
        lectura_completada.set()
        return estado

    tarea_lectura = asyncio.create_task(leer())
    await lectura_intento_entrar.wait()
    assert not lectura_completada.is_set()

    continuar.set()
    await tarea_mutacion
    estado = await tarea_lectura
    assert lectura_completada.is_set()
    return estado


async def test_snapshot_no_observa_presencia_sin_su_finalizacion_por_quorum(
    tmp_path: Path,
) -> None:
    """La lectura ve presencia retirada e INCONCLUSA juntas, nunca la mitad."""

    entorno = crear_entorno_proyecciones(tmp_path)
    abrir_sesion_prueba(entorno)
    votacion = abrir_votacion_prueba(entorno)
    primer_dni, segundo_dni = (concejal.dni for concejal in entorno.contexto.padron.concejales[:2])
    entorno.contexto.presencias[primer_dni] = True
    entorno.contexto.presencias[segundo_dni] = True

    async def mutar(mitad: asyncio.Event, continuar: asyncio.Event) -> None:
        entorno.contexto.presencias[segundo_dni] = False
        mitad.set()
        await continuar.wait()
        votacion.finalizar_inconclusa_derivada(entorno.reloj.ahora())
        entorno.estado.votacion_activa = None

    estado = await leer_mientras_mutacion_esta_a_mitad(entorno, mutar)
    assert estado.quorum is not None and not estado.quorum.alcanzado
    assert estado.votacion is not None and estado.votacion.resultado == "INCONCLUSA"


async def test_snapshot_no_observa_voto_antes_de_autocierre_y_resultado(tmp_path: Path) -> None:
    """Voto, cierre y cálculo quedan atómicos desde el punto de vista lector."""

    entorno = crear_entorno_proyecciones(tmp_path, revelado_moderacion=0)
    abrir_sesion_prueba(entorno)
    votacion = abrir_votacion_prueba(entorno)
    dni = entorno.contexto.padron.concejales[0].dni

    async def mutar(mitad: asyncio.Event, continuar: asyncio.Event) -> None:
        votacion.registrar_voto(VotoOrdinario(dni, ValorVotoOrdinario.POSITIVO))
        mitad.set()
        await continuar.wait()
        votacion.cerrar_recepcion(entorno.reloj.ahora())
        votacion.aplicar_resultado_ordinario(
            ResultadoVotacion.APROBADA,
            entorno.reloj.ahora(),
        )
        entorno.estado.votacion_activa = None

    estado = await leer_mientras_mutacion_esta_a_mitad(entorno, mutar)
    assert estado.votacion is not None
    assert estado.votacion.estado_recepcion == "CERRADA"
    assert estado.votacion.resultado == "APROBADA"
    assert estado.votacion.cantidad_votos_recibidos == 1


async def test_snapshot_no_observa_reemplazo_de_orador_a_mitad(tmp_path: Path) -> None:
    """Finalizar al actual y otorgar al siguiente se proyectan como una unidad."""

    entorno = crear_entorno_proyecciones(tmp_path)
    sesion = abrir_sesion_prueba(entorno)
    primer_dni, segundo_dni = (concejal.dni for concejal in entorno.contexto.padron.concejales[:2])
    sesion.palabra.agregar_pedido(primer_dni)
    sesion.palabra.otorgar_primer_pedido(primer_dni)
    sesion.palabra.agregar_pedido(segundo_dni)

    async def mutar(mitad: asyncio.Event, continuar: asyncio.Event) -> None:
        sesion.palabra.finalizar_uso(primer_dni)
        mitad.set()
        await continuar.wait()
        sesion.palabra.otorgar_primer_pedido(segundo_dni)

    estado = await leer_mientras_mutacion_esta_a_mitad(entorno, mutar)
    assert estado.palabra is not None and estado.palabra.orador is not None
    assert estado.palabra.orador.dni == segundo_dni
    assert estado.palabra.cola == ()


async def test_snapshot_no_observa_desempate_antes_del_resultado_final(tmp_path: Path) -> None:
    """Un lector normal ve voto presidencial y APROBADA de forma compatible."""

    entorno = crear_entorno_proyecciones(tmp_path, revelado_moderacion=0)
    abrir_sesion_prueba(entorno)
    votacion = abrir_votacion_prueba(entorno)
    votacion.cerrar_recepcion(entorno.reloj.ahora())
    votacion.aplicar_resultado_ordinario(ResultadoVotacion.EMPATADA, entorno.reloj.ahora())

    async def mutar(mitad: asyncio.Event, continuar: asyncio.Event) -> None:
        voto = votacion.preparar_voto_desempate(
            SentidoVotoDesempate.POSITIVO,
            "Presidencia de prueba",
        )
        votacion.registrar_voto_desempate(voto)
        mitad.set()
        await continuar.wait()
        votacion.consolidar_resultado_desempate(entorno.reloj.ahora())
        entorno.estado.votacion_activa = None

    estado = await leer_mientras_mutacion_esta_a_mitad(entorno, mutar)
    assert estado.votacion is not None
    assert estado.votacion.resultado == "APROBADA"
    assert estado.votacion.voto_presidencial is not None
    assert estado.votacion.voto_presidencial.sentido == "POSITIVO"


async def test_snapshot_posterior_muestra_fallo_cerrado_real_del_segundo_hecho(
    tmp_path: Path,
) -> None:
    """El 503 no oculta EMPATADA + voto presidencial durable en memoria."""

    entorno = crear_entorno_proyecciones(tmp_path, revelado_moderacion=0)
    abrir_sesion_prueba(entorno)
    votacion = abrir_votacion_prueba(entorno)
    votacion.cerrar_recepcion(entorno.reloj.ahora())
    votacion.aplicar_resultado_ordinario(ResultadoVotacion.EMPATADA, entorno.reloj.ahora())
    entorno.contexto.escritor_auditoria.cerrar()
    escritor_fallido = EscritorAuditoriaConFallo(
        tmp_path,
        entorno,
        CODIGO_VOTACION_RESULTADO_DESEMPATE,
    )
    entorno.contexto.escritor_auditoria = escritor_fallido
    servicio = ServicioVotacion(
        entorno.estado,
        entorno.ejecutor,
        reloj=entorno.reloj.ahora,
    )

    with pytest.raises(ErrorAuditoria):
        await servicio.desempatar_votacion(votacion.id, SentidoVotoDesempate.NEGATIVO)

    estado = await entorno.servicio.obtener_estado_moderacion()
    publico = await entorno.servicio.obtener_estado_recinto()
    assert estado.revision == 1
    assert estado.auditoria.fallado
    assert estado.votacion is not None and estado.votacion.resultado == "EMPATADA"
    assert estado.votacion.voto_presidencial is not None
    assert estado.votacion.voto_presidencial.sentido == "NEGATIVO"
    assert publico.votacion is not None and publico.votacion.voto_presidencial is None
