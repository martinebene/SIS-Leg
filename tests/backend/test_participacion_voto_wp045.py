"""Pruebas del contrato de participación sin sentido introducido por WP-045.

`bancas_voto_emitido` responde una única pregunta autorizada por HUMAN_GATE:
"¿esta banca ya emitió su voto?". Estas pruebas comprueban que responde bien esa
pregunta y, sobre todo, que no permite responder ninguna otra —sentido, DNI,
dispositivo, tecla, instante ni orden de emisión— mientras la recepción sigue
abierta.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sis_leg_backend.dominio.votacion import (
    ValorVotoOrdinario,
    VotoOrdinario,
)

from tests.backend.ayudas_proyecciones import (
    EntornoProyecciones,
    abrir_sesion_prueba,
    abrir_votacion_prueba,
    crear_entorno_proyecciones,
)

pytestmark = pytest.mark.anyio

# Doce bancas repartidas como en la instalación real: permite ejercitar el caso
# límite "todas las bancas emitieron" sin depender de una grilla rectangular.
FILAS_DOCE_BANCAS = (5, 7)


def _dni_de_banca(entorno: EntornoProyecciones, banca: int) -> str:
    """Traduce número de banca a DNI usando el mismo padrón congelado."""

    for concejal in entorno.contexto.padron.concejales:
        if concejal.banca == banca:
            return concejal.dni
    raise AssertionError(f"El padrón de prueba no tiene banca {banca}")


async def test_sin_votos_la_participacion_esta_vacia(tmp_path: Path) -> None:
    """Una votación recién abierta no reporta ninguna banca participante."""

    entorno = crear_entorno_proyecciones(tmp_path)
    abrir_sesion_prueba(entorno)
    abrir_votacion_prueba(entorno)

    moderacion = await entorno.servicio.obtener_estado_moderacion()
    recinto = await entorno.servicio.obtener_estado_recinto()

    assert moderacion.votacion is not None
    assert recinto.votacion is not None
    assert moderacion.votacion.bancas_voto_emitido == ()
    assert recinto.votacion.bancas_voto_emitido == ()


async def test_una_sola_banca_emitida(tmp_path: Path) -> None:
    """El caso mínimo distinto de vacío identifica exactamente esa banca."""

    entorno = crear_entorno_proyecciones(tmp_path)
    abrir_sesion_prueba(entorno)
    votacion = abrir_votacion_prueba(entorno)
    votacion.registrar_voto(VotoOrdinario(_dni_de_banca(entorno, 2), ValorVotoOrdinario.ABSTENCION))

    recinto = await entorno.servicio.obtener_estado_recinto()

    assert recinto.votacion is not None
    assert recinto.votacion.bancas_voto_emitido == (2,)


async def test_varias_bancas_se_ordenan_ascendentemente(tmp_path: Path) -> None:
    """El orden del payload es por banca, nunca por instante de emisión.

    Los votos se registran deliberadamente en orden descendente y con sentidos
    distintos: si la proyección conservara el orden de inserción, la tupla
    revelaría quién votó primero.
    """

    entorno = crear_entorno_proyecciones(tmp_path, filas_bancas=FILAS_DOCE_BANCAS)
    abrir_sesion_prueba(entorno)
    votacion = abrir_votacion_prueba(entorno)
    for banca, valor in (
        (9, ValorVotoOrdinario.NEGATIVO),
        (3, ValorVotoOrdinario.POSITIVO),
        (11, ValorVotoOrdinario.ABSTENCION),
        (1, ValorVotoOrdinario.POSITIVO),
    ):
        votacion.registrar_voto(VotoOrdinario(_dni_de_banca(entorno, banca), valor))

    moderacion = await entorno.servicio.obtener_estado_moderacion()
    recinto = await entorno.servicio.obtener_estado_recinto()

    assert moderacion.votacion is not None
    assert recinto.votacion is not None
    assert moderacion.votacion.bancas_voto_emitido == (1, 3, 9, 11)
    assert recinto.votacion.bancas_voto_emitido == (1, 3, 9, 11)


async def test_todas_las_bancas_emitidas(tmp_path: Path) -> None:
    """Con doce votos la tupla contiene las doce bancas, sin repetir ninguna."""

    entorno = crear_entorno_proyecciones(tmp_path, filas_bancas=FILAS_DOCE_BANCAS)
    abrir_sesion_prueba(entorno)
    votacion = abrir_votacion_prueba(entorno)
    for banca in range(1, 13):
        votacion.registrar_voto(
            VotoOrdinario(_dni_de_banca(entorno, banca), ValorVotoOrdinario.POSITIVO)
        )

    recinto = await entorno.servicio.obtener_estado_recinto()

    assert recinto.votacion is not None
    assert recinto.votacion.bancas_voto_emitido == tuple(range(1, 13))
    assert len(set(recinto.votacion.bancas_voto_emitido)) == 12


async def test_voto_duplicado_no_duplica_la_banca(tmp_path: Path) -> None:
    """Un segundo intento del mismo DNI se rechaza y no altera la lista.

    El voto ordinario es irreversible: el dominio rechaza el reintento y la
    proyección debe seguir informando la banca exactamente una vez.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    abrir_sesion_prueba(entorno)
    votacion = abrir_votacion_prueba(entorno)
    dni = _dni_de_banca(entorno, 1)
    votacion.registrar_voto(VotoOrdinario(dni, ValorVotoOrdinario.POSITIVO))
    with pytest.raises(ValueError):
        votacion.registrar_voto(VotoOrdinario(dni, ValorVotoOrdinario.NEGATIVO))

    recinto = await entorno.servicio.obtener_estado_recinto()

    assert recinto.votacion is not None
    assert recinto.votacion.bancas_voto_emitido == (1,)


async def test_una_votacion_nueva_reinicia_la_participacion(tmp_path: Path) -> None:
    """La participación pertenece a la votación relevante, no a la sesión."""

    entorno = crear_entorno_proyecciones(tmp_path)
    abrir_sesion_prueba(entorno)
    primera = abrir_votacion_prueba(entorno, id_votacion="votacion-1")
    primera.registrar_voto(VotoOrdinario(_dni_de_banca(entorno, 1), ValorVotoOrdinario.POSITIVO))
    primera.cerrar_recepcion(entorno.reloj.ahora())
    entorno.estado.votacion_activa = None

    segunda = abrir_votacion_prueba(entorno, id_votacion="votacion-2")
    segunda.registrar_voto(VotoOrdinario(_dni_de_banca(entorno, 3), ValorVotoOrdinario.NEGATIVO))

    moderacion = await entorno.servicio.obtener_estado_moderacion()

    assert moderacion.votacion is not None
    assert moderacion.votacion.id == "votacion-2"
    assert moderacion.votacion.bancas_voto_emitido == (3,)


async def test_cierre_de_recepcion_vacia_la_participacion(tmp_path: Path) -> None:
    """Fuera de EN_CURSO el sentido final ya viaja por su contrato propio."""

    entorno = crear_entorno_proyecciones(tmp_path)
    abrir_sesion_prueba(entorno)
    votacion = abrir_votacion_prueba(entorno)
    votacion.registrar_voto(VotoOrdinario(_dni_de_banca(entorno, 1), ValorVotoOrdinario.POSITIVO))
    votacion.cerrar_recepcion(entorno.reloj.ahora())

    moderacion = await entorno.servicio.obtener_estado_moderacion()
    recinto = await entorno.servicio.obtener_estado_recinto()

    assert moderacion.votacion is not None
    assert recinto.votacion is not None
    assert moderacion.votacion.bancas_voto_emitido == ()
    assert recinto.votacion.bancas_voto_emitido == ()


async def test_finalizacion_manual_inconclusa_vacia_la_participacion(tmp_path: Path) -> None:
    """Una finalización manual también deja de reportar participación."""

    entorno = crear_entorno_proyecciones(tmp_path)
    abrir_sesion_prueba(entorno)
    votacion = abrir_votacion_prueba(entorno)
    votacion.registrar_voto(VotoOrdinario(_dni_de_banca(entorno, 2), ValorVotoOrdinario.ABSTENCION))
    votacion.finalizar_inconclusa_manual(entorno.reloj.ahora(), "Falta un voto")

    moderacion = await entorno.servicio.obtener_estado_moderacion()

    assert moderacion.votacion is not None
    assert moderacion.votacion.bancas_voto_emitido == ()


async def test_la_ausencia_no_inventa_participaciones(tmp_path: Path) -> None:
    """Presencia y participación son hechos distintos y no se derivan entre sí.

    Marcar presentes a todos los concejales no agrega bancas emitidas, y una
    banca ausente que igualmente votó sí figura: la única fuente es el mapa de
    votos ordinarios.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    abrir_sesion_prueba(entorno)
    contexto = entorno.contexto
    for concejal in contexto.padron.concejales:
        contexto.presencias[concejal.dni] = True
    votacion = abrir_votacion_prueba(entorno)

    recinto_sin_votos = await entorno.servicio.obtener_estado_recinto()
    assert recinto_sin_votos.votacion is not None
    assert recinto_sin_votos.votacion.bancas_voto_emitido == ()

    dni_banca_tres = _dni_de_banca(entorno, 3)
    contexto.presencias[dni_banca_tres] = False
    votacion.registrar_voto(VotoOrdinario(dni_banca_tres, ValorVotoOrdinario.POSITIVO))

    recinto = await entorno.servicio.obtener_estado_recinto()
    assert recinto.votacion is not None
    assert recinto.votacion.bancas_voto_emitido == (3,)


async def test_rest_y_sse_serializan_la_misma_proyeccion(tmp_path: Path) -> None:
    """El campo llega por el mismo constructor a snapshot y stream.

    No hay dos rutas de construcción: ambos consumidores piden el estado al
    mismo servicio, de modo que una política de secreto no puede divergir.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    abrir_sesion_prueba(entorno)
    votacion = abrir_votacion_prueba(entorno)
    votacion.registrar_voto(VotoOrdinario(_dni_de_banca(entorno, 2), ValorVotoOrdinario.NEGATIVO))

    primero = await entorno.servicio.obtener_estado_recinto()
    segundo = await entorno.servicio.obtener_estado_recinto()

    assert primero.votacion is not None and segundo.votacion is not None
    assert primero.votacion.bancas_voto_emitido == segundo.votacion.bancas_voto_emitido
    assert primero.model_dump_json() == segundo.model_dump_json()


async def test_la_serializacion_no_filtra_sentido_ni_identidad(tmp_path: Path) -> None:
    """Gate crítico de secreto sobre el JSON efectivamente enviado.

    Se inspecciona el payload serializado completo, no solo el campo nuevo: si
    alguna otra parte de la proyección pública filtrara el sentido durante la
    recepción, esta prueba también fallaría.
    """

    entorno = crear_entorno_proyecciones(tmp_path, filas_bancas=FILAS_DOCE_BANCAS)
    abrir_sesion_prueba(entorno)
    votacion = abrir_votacion_prueba(entorno)
    for banca, valor in (
        (1, ValorVotoOrdinario.POSITIVO),
        (4, ValorVotoOrdinario.NEGATIVO),
        (7, ValorVotoOrdinario.ABSTENCION),
    ):
        votacion.registrar_voto(VotoOrdinario(_dni_de_banca(entorno, banca), valor))

    recinto = await entorno.servicio.obtener_estado_recinto()
    payload = recinto.model_dump_json()
    votacion_publica = json.loads(payload)["votacion"]

    assert votacion_publica["bancas_voto_emitido"] == [1, 4, 7]
    # El campo solo transporta enteros de banca.
    assert all(isinstance(banca, int) for banca in votacion_publica["bancas_voto_emitido"])
    # Ningún sentido, ni siquiera dentro de conteos parciales, durante EN_CURSO.
    for prohibido in ("POSITIVO", "NEGATIVO", "ABSTENCION"):
        assert prohibido not in payload
    assert votacion_publica["votos_individuales"] is None
    assert votacion_publica["conteos"] is None
    # Identidad y hardware nunca forman parte del contrato público.
    for concejal in entorno.contexto.padron.concejales:
        assert concejal.dni not in payload
        assert concejal.dispositivo_votacion not in payload


async def test_moderacion_tampoco_transporta_dni_ni_dispositivo_en_el_campo_nuevo(
    tmp_path: Path,
) -> None:
    """La ampliación de Moderación tampoco agrega identidad al nuevo campo.

    Moderación sí puede recibir DNI en otros campos por su política histórica;
    lo que se comprueba acá es que `bancas_voto_emitido` es exclusivamente una
    lista de enteros de banca.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    abrir_sesion_prueba(entorno)
    votacion = abrir_votacion_prueba(entorno)
    votacion.registrar_voto(VotoOrdinario(_dni_de_banca(entorno, 1), ValorVotoOrdinario.POSITIVO))

    moderacion = await entorno.servicio.obtener_estado_moderacion()
    assert moderacion.votacion is not None
    volcado = moderacion.votacion.model_dump()

    assert volcado["bancas_voto_emitido"] == (1,)
    assert all(isinstance(banca, int) for banca in volcado["bancas_voto_emitido"])


async def test_la_ampliacion_no_altera_conteos_ni_resultado(tmp_path: Path) -> None:
    """El campo es derivado y de solo lectura: no toca reglas ni resultados."""

    entorno = crear_entorno_proyecciones(tmp_path)
    abrir_sesion_prueba(entorno)
    votacion = abrir_votacion_prueba(entorno)
    votacion.registrar_voto(VotoOrdinario(_dni_de_banca(entorno, 1), ValorVotoOrdinario.POSITIVO))
    votacion.registrar_voto(VotoOrdinario(_dni_de_banca(entorno, 2), ValorVotoOrdinario.POSITIVO))
    votacion.registrar_voto(VotoOrdinario(_dni_de_banca(entorno, 3), ValorVotoOrdinario.NEGATIVO))

    en_curso = await entorno.servicio.obtener_estado_moderacion()
    assert en_curso.votacion is not None
    assert en_curso.votacion.bancas_voto_emitido == (1, 2, 3)
    assert en_curso.votacion.cantidad_votos_recibidos == 3

    conteos = votacion.contar_votos_ordinarios()
    assert (conteos.positivos, conteos.negativos, conteos.abstenciones) == (2, 1, 0)

    votacion.cerrar_recepcion(entorno.reloj.ahora())
    cerrada = await entorno.servicio.obtener_estado_moderacion()
    assert cerrada.votacion is not None
    assert cerrada.votacion.bancas_voto_emitido == ()
    assert cerrada.votacion.cantidad_votos_recibidos == 3
