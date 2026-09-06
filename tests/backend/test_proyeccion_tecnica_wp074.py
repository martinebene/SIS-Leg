"""Allowlists de remapeo y sonorización dentro de ``EstadoTecnico`` (WP-074).

## Qué defiende esta suite

WP-074 corrige un defecto operativo concreto: con las cuatro superficies de
SIS-Leg abiertas en el mismo navegador y bajo el mismo origen HTTP/1.1, los
comandos REST dejaban de llegar al backend porque los seis streams SSE
persistentes agotaban el cupo de conexiones. Tres de esos seis los abría el
puesto de Apoyo Técnico.

La corrección consiste en que la proyección técnica transporte lo que el puesto
obtenía de las otras dos, recortado por allowlists explícitas. Estas pruebas
fijan **las dos mitades** de esa decisión:

1. que la información necesaria efectivamente esté, en los tres estados
   globales, y sea la misma que produce el resto del sistema;
2. que no se haya colado nada más, especialmente ningún dato que pudiera
   debilitar el secreto temporal del voto.

La segunda mitad es la importante: ampliar una proyección es fácil y una
ampliación de más no rompe ninguna pantalla, así que sólo una prueba explícita
puede impedir que la allowlist se convierta con el tiempo en una copia del
estado de Moderación.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sis_leg_backend.dominio.apoyo_tecnico import EstadoTransmision
from sis_leg_backend.dominio.estado import EstadoGlobal
from sis_leg_backend.dominio.remapeo import EstadoRemapeo, OperacionRemapeo
from sis_leg_backend.dominio.votacion import (
    EstadoVotacion,
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


def sin_preparacion(entorno: EntornoProyecciones) -> None:
    """Deja el entorno en ``SIN_PREPARAR``, que es donde arranca el proceso."""

    entorno.estado.preparacion_activa = None
    entorno.estado.estado_global = EstadoGlobal.SIN_PREPARAR


# =============================================================================
# 1. Forma del contrato en los tres estados globales
# =============================================================================


async def test_estado_tecnico_declara_exactamente_los_campos_del_contrato(
    tmp_path: Path,
) -> None:
    """La proyección técnica no gana campos sueltos entre WPs.

    Comparar el conjunto completo de claves, y no sólo la presencia de las dos
    nuevas, es lo que convierte a esta prueba en una barrera: cualquier campo
    agregado sin decisión documentada la rompe.
    """

    entorno = crear_entorno_proyecciones(tmp_path)

    tecnico = await entorno.servicio.obtener_estado_tecnico()

    assert tecnico.model_dump().keys() == {
        "revision",
        "generado_en",
        "estado_global",
        "transmision",
        "aviso_moderacion",
        "aviso_recinto",
        "biblioteca",
        "eventos_recientes",
        "auditoria",
        # WP-074 agrega estas dos porciones para que el puesto no necesite
        # suscribirse a Moderación ni al Recinto.
        "remapeo",
        "sonorizacion",
    }
    assert tecnico.remapeo.model_dump().keys() == {"remapeo", "concejales", "capacidades"}
    assert tecnico.sonorizacion.model_dump().keys() == {
        "revision",
        "estado_global",
        "tecnico",
        "palabra",
        "votacion",
        "concejales",
        "sonidos",
    }


@pytest.mark.parametrize(
    "estado_global",
    (EstadoGlobal.SIN_PREPARAR, EstadoGlobal.PREPARANDO, EstadoGlobal.SESION_ABIERTA),
)
async def test_las_dos_porciones_viajan_en_los_tres_estados_globales(
    tmp_path: Path,
    estado_global: EstadoGlobal,
) -> None:
    """El puesto técnico opera fuera de una sesión y también debe sonar ahí.

    En ``SIN_PREPARAR`` no hay padrón, así que las dos listas viajan vacías,
    pero los objetos existen: la pantalla nunca recibe ``null`` donde espera una
    estructura, y la configuración de audio está disponible desde el arranque.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    if estado_global is EstadoGlobal.SIN_PREPARAR:
        sin_preparacion(entorno)
    elif estado_global is EstadoGlobal.SESION_ABIERTA:
        abrir_sesion_prueba(entorno)

    tecnico = await entorno.servicio.obtener_estado_tecnico()

    assert tecnico.estado_global is estado_global
    assert tecnico.sonorizacion.estado_global is estado_global
    assert len(tecnico.sonorizacion.sonidos.sonidos) == 15
    if estado_global is EstadoGlobal.SIN_PREPARAR:
        assert tecnico.remapeo.concejales == ()
        assert tecnico.sonorizacion.concejales == ()
    else:
        assert len(tecnico.remapeo.concejales) == len(entorno.contexto.padron.concejales)
        assert len(tecnico.sonorizacion.concejales) == len(entorno.contexto.padron.concejales)


async def test_la_sonorizacion_comparte_revision_con_el_snapshot_que_la_contiene(
    tmp_path: Path,
) -> None:
    """Una sola revisión describe todo el puesto.

    Con tres streams, sonido y paneles podían adelantarse uno al otro. Con uno,
    la porción sonora es parte del mismo snapshot y la guarda de revisión
    repetida del frontend compara el mismo número que muestra la cabecera.
    """

    entorno = crear_entorno_proyecciones(tmp_path)

    primero = await entorno.servicio.obtener_estado_tecnico()
    assert primero.sonorizacion.revision == primero.revision

    entorno.coordinador.publicar()
    segundo = await entorno.servicio.obtener_estado_tecnico()

    assert segundo.revision > primero.revision
    assert segundo.sonorizacion.revision == segundo.revision


# =============================================================================
# 2. Remapeo: mismos datos que Moderación, recortados
# =============================================================================


async def test_remapeo_tecnico_reproduce_operacion_y_capacidades_de_moderacion(
    tmp_path: Path,
) -> None:
    """No hay una segunda semántica de remapeo: se recorta la única que existe."""

    entorno = crear_entorno_proyecciones(tmp_path)
    operacion = OperacionRemapeo(remapeo_id="remapeo-prueba", dispositivo="P-01")
    operacion.candidato = "fingerprint-candidato"
    operacion.estado = EstadoRemapeo.CANDIDATO
    entorno.estado.remapeo_activo = operacion

    moderacion = await entorno.servicio.obtener_estado_moderacion()
    tecnico = await entorno.servicio.obtener_estado_tecnico()

    assert tecnico.remapeo.remapeo == moderacion.remapeo
    assert tecnico.remapeo.capacidades.iniciar_remapeo == moderacion.capacidades.iniciar_remapeo
    assert tecnico.remapeo.capacidades.confirmar_remapeo == moderacion.capacidades.confirmar_remapeo
    assert tecnico.remapeo.capacidades.cancelar_remapeo == moderacion.capacidades.cancelar_remapeo


async def test_remapeo_tecnico_lista_las_mismas_bancas_con_su_dispositivo_logico(
    tmp_path: Path,
) -> None:
    """El selector necesita identidad y devXX, y eso es todo lo que recibe."""

    entorno = crear_entorno_proyecciones(tmp_path)

    moderacion = await entorno.servicio.obtener_estado_moderacion()
    tecnico = await entorno.servicio.obtener_estado_tecnico()

    assert [concejal.dispositivo_votacion for concejal in tecnico.remapeo.concejales] == [
        concejal.dispositivo_votacion for concejal in moderacion.concejales
    ]
    assert [concejal.banca for concejal in tecnico.remapeo.concejales] == [
        concejal.banca for concejal in moderacion.concejales
    ]
    assert tecnico.remapeo.concejales[0].model_dump().keys() == {
        "dni",
        "nombre",
        "apellido",
        "banca",
        "dispositivo_votacion",
    }


async def test_remapeo_tecnico_no_transporta_presencia_ni_test_de_dispositivo(
    tmp_path: Path,
) -> None:
    """La allowlist se define por lo que el panel usa, no por lo que existe.

    Presencia y test de dispositivo son datos legítimos de Moderación, pero el
    panel de remapeo no los lee. Dejarlos afuera es lo que impide que esta
    porción crezca hasta convertirse en el padrón completo.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    primer_dni = entorno.contexto.padron.concejales[0].dni
    entorno.contexto.presencias[primer_dni] = True
    entorno.contexto.activar_test_dispositivo(primer_dni, entorno.reloj.monotono())

    tecnico = await entorno.servicio.obtener_estado_tecnico()

    campos = tecnico.remapeo.concejales[0].model_dump().keys()
    assert "presente" not in campos
    assert "test_activo" not in campos
    assert "test_expira_en" not in campos
    assert "bloque" not in campos
    assert "ruta_imagen" not in campos


async def test_estado_tecnico_no_incluye_el_snapshot_de_moderacion(tmp_path: Path) -> None:
    """La corrección no puede degenerar en «Moderación adentro de Técnico».

    Se comprueba sobre el JSON serializado —que es lo que efectivamente viaja—
    y no sólo sobre los modelos, porque un submodelo anidado por error también
    aparecería ahí.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    abrir_votacion_prueba(entorno)

    tecnico = await entorno.servicio.obtener_estado_tecnico()
    carga = tecnico.model_dump()

    assert "orden_del_dia" not in carga
    assert "quorum" not in carga
    assert "preparacion" not in carga
    assert "sesion" not in carga
    assert "capacidades" not in carga
    # Las capacidades institucionales de Moderación tampoco llegan por el
    # camino del remapeo: sólo viajan las tres que ese panel gobierna.
    assert tecnico.remapeo.capacidades.model_dump().keys() == {
        "iniciar_remapeo",
        "confirmar_remapeo",
        "cancelar_remapeo",
    }


# =============================================================================
# 3. Sonorización: idéntica al Recinto y estrictamente más pobre
# =============================================================================


async def test_sonorizacion_replica_el_plano_tecnico_que_ve_el_recinto(tmp_path: Path) -> None:
    """El sonido debe seguir la ranura del salón, no la de Moderación.

    Si esta porción tomara el aviso dirigido a Moderación, el puesto técnico
    sonaría por hechos que en el recinto nunca ocurrieron. Por eso se construye
    con el mismo helper y la misma ranura que la proyección pública.
    """

    entorno = crear_entorno_proyecciones(tmp_path)

    recinto = await entorno.servicio.obtener_estado_recinto()
    tecnico = await entorno.servicio.obtener_estado_tecnico()

    assert tecnico.sonorizacion.tecnico == recinto.tecnico
    assert tecnico.sonorizacion.tecnico.transmision.estado is EstadoTransmision.APAGADO


async def test_sonorizacion_replica_presencia_palabra_y_votacion_publicas(
    tmp_path: Path,
) -> None:
    """Cada campo sonoro coincide con el de la proyección pública equivalente."""

    entorno = crear_entorno_proyecciones(tmp_path)
    primer_dni = entorno.contexto.padron.concejales[0].dni
    entorno.contexto.presencias[primer_dni] = True
    sesion = abrir_sesion_prueba(entorno)
    sesion.palabra.agregar_pedido(primer_dni)
    votacion = abrir_votacion_prueba(entorno)

    recinto = await entorno.servicio.obtener_estado_recinto()
    tecnico = await entorno.servicio.obtener_estado_tecnico()

    assert [(banca.banca, banca.presente) for banca in tecnico.sonorizacion.concejales] == [
        (concejal.banca, concejal.presente) for concejal in recinto.concejales
    ]
    assert recinto.palabra is not None and tecnico.sonorizacion.palabra is not None
    assert [persona.banca for persona in tecnico.sonorizacion.palabra.cola] == [
        persona.banca for persona in recinto.palabra.cola
    ]
    assert recinto.votacion is not None and tecnico.sonorizacion.votacion is not None
    assert tecnico.sonorizacion.votacion.id == votacion.id
    assert tecnico.sonorizacion.votacion.estado_recepcion == recinto.votacion.estado_recepcion
    assert tecnico.sonorizacion.sonidos == recinto.sonidos


async def test_sonorizacion_no_revela_votos_durante_el_secreto(tmp_path: Path) -> None:
    """La porción sonora es estrictamente más pobre que la pantalla pública.

    Mientras la votación está ``EN_CURSO``, el Recinto ya oculta el sentido de
    cada voto y publica sólo qué bancas participaron. La porción sonora no
    necesita ni siquiera eso: de la votación transporta la identidad y la
    recepción, que es lo único que distingue una apertura de un cierre.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    for concejal in entorno.contexto.padron.concejales:
        entorno.contexto.presencias[concejal.dni] = True
    abrir_sesion_prueba(entorno)
    votacion = abrir_votacion_prueba(entorno)
    votacion.registrar_voto(
        VotoOrdinario(
            entorno.contexto.padron.concejales[0].dni,
            ValorVotoOrdinario.POSITIVO,
        )
    )

    tecnico = await entorno.servicio.obtener_estado_tecnico()

    assert tecnico.sonorizacion.votacion is not None
    campos = tecnico.sonorizacion.votacion.model_dump().keys()
    assert campos == {"id", "estado_recepcion"}
    assert tecnico.sonorizacion.votacion.estado_recepcion == EstadoVotacion.EN_CURSO.value
    # Ni siquiera las bancas que ya votaron, que el Recinto sí publica.
    carga = tecnico.sonorizacion.model_dump()
    assert "bancas_voto_emitido" not in str(carga)
    assert "votos_individuales" not in str(carga)
    assert "conteos" not in str(carga)


async def test_sonorizacion_identifica_a_las_personas_solo_por_banca(tmp_path: Path) -> None:
    """La cola de palabra no lleva DNI ni nombres al puesto técnico.

    La proyección pública ya excluye el DNI; acá se excluyen además nombre y
    apellido, porque el detector de transiciones compara bancas y nada más.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    primer_dni = entorno.contexto.padron.concejales[0].dni
    entorno.contexto.presencias[primer_dni] = True
    sesion = abrir_sesion_prueba(entorno)
    sesion.palabra.agregar_pedido(primer_dni)

    tecnico = await entorno.servicio.obtener_estado_tecnico()

    assert tecnico.sonorizacion.palabra is not None
    assert tecnico.sonorizacion.palabra.cola[0].model_dump().keys() == {"banca"}
    carga = str(tecnico.sonorizacion.model_dump())
    assert primer_dni not in carga
    assert "Nombre1" not in carga


async def test_sonorizacion_de_bancas_solo_transporta_presencia(tmp_path: Path) -> None:
    """De cada banca viaja lo mínimo para distinguir presente de ausente."""

    entorno = crear_entorno_proyecciones(tmp_path)
    primer_dni = entorno.contexto.padron.concejales[0].dni
    entorno.contexto.activar_test_dispositivo(primer_dni, entorno.reloj.monotono())

    tecnico = await entorno.servicio.obtener_estado_tecnico()

    assert tecnico.sonorizacion.concejales[0].model_dump().keys() == {"banca", "presente"}
