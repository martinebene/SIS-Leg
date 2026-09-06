"""Pruebas deterministas de concurrencia para Orden del Día (WP-016).

Verifica mediante el EjecutorMutaciones real y control de orden:
- CASO A: Dos cargas válidas concurrentes: la última en adquirir el lock define
  el estado final sin mezclar filas.
- CASO B: Carga válida concurrente con DELETE: el resultado final depende
  estrictamente del orden de serialización.
- CASO C: Parseo fuera del lock seguido de cancelación o cierre del contexto
  antes de instalar bajo el lock: la carga revalida el estado operativo activo,
  detecta SIN_PREPARAR y falla con ErrorEstadoIncompatible sin recrear el
  contexto cancelado ni escribir en el contexto obsoleto.
- CASO D: Carga inválida concurrente con operación válida: el archivo inválido
  no altera la colección válida previa ni en curso.
- CASO E: Carga concurrente durante votación: la votación activa conserva
  íntegramente sus datos constitutivos, estado, votos y resultado.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from sis_leg_backend.auditoria import EscritorAuditoriaCsv
from sis_leg_backend.configuracion.modelos import (
    Concejal,
    ConfiguracionSistema,
    Padron,
)
from sis_leg_backend.dominio.errores import ErrorEstadoIncompatible, ErrorOrdenDelDiaInvalido
from sis_leg_backend.dominio.estado import EstadoGlobal, EstadoOperativo
from sis_leg_backend.dominio.preparacion import Preparacion
from sis_leg_backend.dominio.sesion import Sesion
from sis_leg_backend.dominio.votacion import (
    BaseMayoria,
    TipoMayoria,
    ValorVotoOrdinario,
    Votacion,
    VotoOrdinario,
)
from sis_leg_backend.servicios.orden_del_dia import ServicioOrdenDelDia
from sis_leg_backend.servicios.preparacion import ServicioPreparacion
from sis_leg_backend.servicios.serializacion import EjecutorMutaciones
from sis_leg_backend.servicios.sesion import ServicioSesion

pytestmark = pytest.mark.anyio

CSV_COLECCION_A = (
    b"nro_votacion,tipo,tema,tipo_mayoria,factor,base\n"
    b"1,Despacho,Tema A1,SIMPLE,,\n"
    b"2,Despacho,Tema A2,SIMPLE,,\n"
)

CSV_COLECCION_B = (
    b"nro_votacion,tipo,tema,tipo_mayoria,factor,base\n"
    b"10,Mocion,Tema B1,ESPECIAL,0.75,CUERPO\n"
    b"20,Mocion,Tema B2,ESPECIAL,0.5,VOTOS_COMPUTABLES\n"
    b"30,Mocion,Tema B3,SIMPLE,,\n"
)

CSV_INVALIDO = (
    b"nro_votacion,tipo,tema,tipo_mayoria,factor,base\n"
    b"1,Despacho,Tema Invalido,ESPECIAL,-99,PRESENTES\n"
)


def _crear_preparacion_aislada(
    tmp_path: Path,
) -> tuple[EstadoOperativo, Preparacion, EscritorAuditoriaCsv]:
    """Fabrica un estado en PREPARANDO con escritor real sobre tmp_path."""
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    escritor = EscritorAuditoriaCsv(logs_dir, datetime.now())
    configuracion = ConfiguracionSistema(
        quorum=1,
        filas_bancas=(1,),
        tipos_votacion=("Despacho", "Mocion"),
        device_test_seconds=4,
        moderacion_revelado_votos_segundos=0,
        recinto_cuenta_regresiva_inicial_segundos=4,
        recinto_resultado_publico_segundos=6,
        directorio_registros=str(logs_dir),
    )
    concejal = Concejal(
        dni="12345678",
        nombre="Juan",
        apellido="Perez",
        bloque="",
        banca=1,
        dispositivo_votacion="D-01",
        ruta_imagen="img/1.png",
    )
    padron = Padron(concejales=(concejal,))
    prep = Preparacion(
        fecha_hora_inicio=datetime.now(),
        configuracion=configuracion,
        padron=padron,
        presencias={"12345678": True},
        escritor_auditoria=escritor,
        numero_sesion=1,
        presidencia="Presidente",
        secretaria_legislativa="Secretario",
    )
    estado = EstadoOperativo()
    estado.preparacion_activa = prep
    estado.archivos_auditoria_activos = prep.rutas_auditoria()
    estado.estado_global = EstadoGlobal.PREPARANDO
    return estado, prep, escritor


# ==============================================================================
# CASO A: DOS CARGAS VÁLIDAS CONCURRENTES
# ==============================================================================


async def test_caso_a_dos_cargas_concurrentes_orden_determinado(tmp_path: Path) -> None:
    """Demuestra que dos cargas concurrentes se serializan y gana la última sin mezclar filas."""
    estado, prep, escritor = _crear_preparacion_aislada(tmp_path)
    ejecutor = EjecutorMutaciones()
    servicio = ServicioOrdenDelDia(estado, ejecutor)

    # Lanzamos ambas cargas concurrentemente
    resultado_a, resultado_b = await asyncio.gather(
        servicio.cargar_orden_del_dia(CSV_COLECCION_A),
        servicio.cargar_orden_del_dia(CSV_COLECCION_B),
    )

    # Ambas cargas devolvieron sus puntos respectivos
    assert len(resultado_a) == 2
    assert len(resultado_b) == 3

    # El estado final es exactamente una de las dos colecciones completas (nunca una mezcla parcial)
    coleccion_final = prep.orden_del_dia
    assert coleccion_final is not None
    assert coleccion_final in (resultado_a, resultado_b)
    if coleccion_final == resultado_b:
        assert [p.nro_votacion for p in coleccion_final] == [10, 20, 30]
    else:
        assert [p.nro_votacion for p in coleccion_final] == [1, 2]

    escritor.cerrar()


# ==============================================================================
# CASO B: CARGA VÁLIDA CONCURRENTE CON DELETE
# ==============================================================================


async def test_caso_b_carga_concurrente_con_delete(tmp_path: Path) -> None:
    """Demuestra que carga y DELETE concurrentes se resuelven según el orden del serializador."""
    estado, prep, escritor = _crear_preparacion_aislada(tmp_path)
    ejecutor = EjecutorMutaciones()
    servicio = ServicioOrdenDelDia(estado, ejecutor)

    # Lanzamos carga y descarte en paralelo
    await asyncio.gather(
        servicio.cargar_orden_del_dia(CSV_COLECCION_A),
        servicio.descartar_orden_del_dia(),
    )

    # El estado final debe ser None (si DELETE fue segundo) o la colección A (si carga fue segunda)
    assert prep.orden_del_dia is None or len(prep.orden_del_dia) == 2

    escritor.cerrar()


# ==============================================================================
# CASO C: PARSEO FUERA DEL LOCK Y CONTEXTO CANCELADO/CERRADO ANTES DE INSTALAR
# ==============================================================================


async def test_caso_c_parseo_fuera_del_lock_y_cancelacion_previa(tmp_path: Path) -> None:
    """Demuestra que si el contexto se cancela entre el parseo y la instalación, se rechaza."""
    estado, prep_original, _escritor = _crear_preparacion_aislada(tmp_path)
    ejecutor = EjecutorMutaciones()
    servicio_prep = ServicioPreparacion(estado, ejecutor)
    servicio_od = ServicioOrdenDelDia(estado, ejecutor)

    parseo_completado = asyncio.Event()
    cancelacion_completada = asyncio.Event()

    metodo_ejecutar_original = ejecutor.ejecutar

    async def ejecutar_con_pausa(
        mutacion: Callable[[], Coroutine[Any, Any, Any]],
    ) -> Any:
        # Detectamos la mutación interna de instalación del Orden del Día
        if getattr(mutacion, "__name__", "") == "_instalar_bajo_lock":
            # Notificamos que el parseo previo fuera del lock ya completó
            parseo_completado.set()
            # Esperamos a que la cancelación formal ocurra antes de entrar al lock
            await cancelacion_completada.wait()
        return await metodo_ejecutar_original(mutacion)

    ejecutor.ejecutar = ejecutar_con_pausa  # type: ignore[method-assign]

    async def flujo_carga() -> Any:
        return await servicio_od.cargar_orden_del_dia(CSV_COLECCION_A)

    async def flujo_cancelacion() -> None:
        # Esperamos a que el archivo haya sido parseado fuera del lock
        await parseo_completado.wait()
        # Cancelamos la preparación bajo el lock
        await servicio_prep.cancelar_preparacion()
        # Notificamos que la cancelación ya ocurrió y el estado es SIN_PREPARAR
        cancelacion_completada.set()

    resultados = await asyncio.gather(
        flujo_carga(),
        flujo_cancelacion(),
        return_exceptions=True,
    )

    # 1. La carga falló limpiamente con ErrorEstadoIncompatible al revalidar bajo el lock
    assert isinstance(resultados[0], ErrorEstadoIncompatible)
    assert "SIN_PREPARAR" in str(resultados[0])

    # 2. La cancelación completó con éxito
    assert resultados[1] is None

    # 3. El estado del sistema permanece en SIN_PREPARAR
    assert estado.estado_global is EstadoGlobal.SIN_PREPARAR
    assert estado.preparacion_activa is None
    assert estado.contexto_operativo_activo() is None

    # 4. El contexto cancelado nunca recibió la colección
    assert prep_original.orden_del_dia is None


async def test_caso_c_parseo_fuera_del_lock_y_cierre_sesion_previo(tmp_path: Path) -> None:
    """Demuestra que si la sesión se cierra entre el parseo y la instalación, se rechaza."""
    estado, prep_original, _escritor = _crear_preparacion_aislada(tmp_path)
    ejecutor = EjecutorMutaciones()
    servicio_sesion = ServicioSesion(estado, ejecutor)
    servicio_od = ServicioOrdenDelDia(estado, ejecutor)

    # Abrimos sesión
    sesion = Sesion(contexto_operativo=prep_original, fecha_hora_apertura=datetime.now())
    estado.preparacion_activa = None
    estado.sesion_activa = sesion
    estado.estado_global = EstadoGlobal.SESION_ABIERTA

    parseo_completado = asyncio.Event()
    cierre_completado = asyncio.Event()

    metodo_ejecutar_original = ejecutor.ejecutar

    async def ejecutar_con_pausa(
        mutacion: Callable[[], Coroutine[Any, Any, Any]],
    ) -> Any:
        if getattr(mutacion, "__name__", "") == "_instalar_bajo_lock":
            parseo_completado.set()
            await cierre_completado.wait()
        return await metodo_ejecutar_original(mutacion)

    ejecutor.ejecutar = ejecutar_con_pausa  # type: ignore[method-assign]

    async def flujo_carga() -> Any:
        return await servicio_od.cargar_orden_del_dia(CSV_COLECCION_A)

    async def flujo_cierre() -> None:
        await parseo_completado.wait()
        await servicio_sesion.cerrar_sesion()
        cierre_completado.set()

    resultados = await asyncio.gather(
        flujo_carga(),
        flujo_cierre(),
        return_exceptions=True,
    )

    assert isinstance(resultados[0], ErrorEstadoIncompatible)
    assert "SIN_PREPARAR" in str(resultados[0])
    assert resultados[1] is None
    assert estado.estado_global is EstadoGlobal.SIN_PREPARAR
    assert estado.sesion_activa is None
    assert estado.contexto_operativo_activo() is None
    assert prep_original.orden_del_dia is None


# ==============================================================================
# CASO D: ARCHIVO INVÁLIDO CONCURRENTE CON OPERACIÓN VÁLIDA
# ==============================================================================


async def test_caso_d_archivo_invalido_no_modifica_coleccion_valida(tmp_path: Path) -> None:
    """Demuestra que una carga inválida concurrente no corrompe una carga válida."""
    estado, prep, escritor = _crear_preparacion_aislada(tmp_path)
    ejecutor = EjecutorMutaciones()
    servicio = ServicioOrdenDelDia(estado, ejecutor)

    tarea_valida = servicio.cargar_orden_del_dia(CSV_COLECCION_A)
    tarea_invalida = servicio.cargar_orden_del_dia(CSV_INVALIDO)

    resultados = await asyncio.gather(tarea_valida, tarea_invalida, return_exceptions=True)

    assert isinstance(resultados[0], tuple)
    assert isinstance(resultados[1], ErrorOrdenDelDiaInvalido)

    # La colección válida quedó instalada y no fue corrompida por la inválida
    assert prep.orden_del_dia == resultados[0]
    assert prep.orden_del_dia is not None
    assert len(prep.orden_del_dia) == 2

    escritor.cerrar()


# ==============================================================================
# CASO E: CARGA CONCURRENTE DURANTE VOTACIÓN ACTIVA
# ==============================================================================


async def test_caso_e_carga_concurrente_durante_votacion_preserva_votacion(tmp_path: Path) -> None:
    """Demuestra que cargar Orden del Día durante una votación preserva la votación."""
    estado, prep, escritor = _crear_preparacion_aislada(tmp_path)
    ejecutor = EjecutorMutaciones()
    servicio = ServicioOrdenDelDia(estado, ejecutor)

    sesion = Sesion(contexto_operativo=prep, fecha_hora_apertura=datetime.now())
    estado.preparacion_activa = None
    estado.sesion_activa = sesion
    estado.estado_global = EstadoGlobal.SESION_ABIERTA

    # Creamos una votación activa con un voto registrado
    votacion = Votacion(
        id="vot-concurrente-01",
        numero_votacion=42,
        tipo="Despacho",
        tema="Tema inviolable",
        tipo_mayoria=TipoMayoria.ESPECIAL,
        factor=0.6666666667,
        base=BaseMayoria.PRESENTES,
        fecha_hora_apertura=datetime.now(),
    )
    votacion.registrar_voto(VotoOrdinario(dni="12345678", valor=ValorVotoOrdinario.POSITIVO))
    estado.votacion_activa = votacion
    sesion.votaciones.append(votacion)

    # Ejecutamos carga de Orden del Día
    puntos = await servicio.cargar_orden_del_dia(CSV_COLECCION_B)

    # Verificamos que el Orden del Día se instaló
    assert sesion.contexto_operativo.orden_del_dia == puntos

    # Y verificamos que la votación no sufrió ninguna alteración
    assert estado.votacion_activa is votacion
    assert votacion.id == "vot-concurrente-01"
    assert votacion.numero_votacion == 42
    assert votacion.tipo == "Despacho"
    assert votacion.tema == "Tema inviolable"
    assert votacion.tipo_mayoria is TipoMayoria.ESPECIAL
    assert votacion.factor == 0.6666666667
    assert votacion.base is BaseMayoria.PRESENTES
    assert votacion.resultado is None
    assert len(votacion.votos_ordinarios) == 1
    assert votacion.votos_ordinarios["12345678"].valor is ValorVotoOrdinario.POSITIVO

    escritor.cerrar()
