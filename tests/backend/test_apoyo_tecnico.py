"""Pruebas de dominio, servicios y proyecciones de Apoyo Técnico (WP-055).

Se agrupan por las tres decisiones humanas cerradas del WP:

- **Transmisión**: ``APAGADO`` -> cuenta regresiva opcional -> ``EN VIVO`` ->
  ``APAGADO`` manual, con frontera temporal exacta y sin autoapagado.
- **Avisos**: destinos independientes, ``AMBOS`` coherente, duración opcional,
  expiración autoritativa y cancelación manual.
- **Biblioteca CSV**: CRUD, identificadores estables, supervivencia a un
  reinicio simulado, validación y escritura concurrente segura.

Todas las pruebas usan el ``RelojManual`` del entorno compartido: las fronteras
temporales se cruzan avanzando el reloj, nunca esperando segundos reales, de
modo que el resultado es determinista y la suite sigue siendo rápida.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from botonera2_backend.auditoria import NivelAuditoria
from botonera2_backend.configuracion.mensajes_tecnicos import cargar_mensajes_tecnicos
from botonera2_backend.dominio.apoyo_tecnico import (
    BibliotecaMensajesTecnicos,
    DestinoAvisoTecnico,
    ErrorBibliotecaMensajesNoDisponible,
    ErrorMensajeTecnicoNoExistente,
    EstadoTransmision,
)
from botonera2_backend.dominio.estado import EstadoGlobal

from tests.backend.ayudas_proyecciones import (
    EntornoProyecciones,
    crear_entorno_proyecciones,
    crear_servicio_apoyo_tecnico,
)

pytestmark = pytest.mark.anyio


def sin_preparacion(entorno: EntornoProyecciones) -> None:
    """Deja el entorno en ``SIN_PREPARAR``, sin contexto ni auditoría abierta.

    El plano técnico debe funcionar igual en ese estado: Apoyo Técnico puede
    encender el indicador antes de que Moderación prepare el recinto.
    """

    entorno.estado.preparacion_activa = None
    entorno.estado.estado_global = EstadoGlobal.SIN_PREPARAR


def codigos_auditados(entorno: EntornoProyecciones) -> list[str]:
    """Lista los códigos de evento ya confirmados por el escritor activo."""

    eventos = entorno.contexto.escritor_auditoria.eventos_recientes
    return [evento.codigo_evento for evento in eventos]


# =============================================================================
# 1. Transmisión
# =============================================================================


async def test_estado_inicial_es_apagado(tmp_path: Path) -> None:
    """Prueba 1: sin ninguna orden, el indicador está apagado."""

    entorno = crear_entorno_proyecciones(tmp_path)

    tecnico = await entorno.servicio.obtener_estado_tecnico()

    assert tecnico.transmision.estado is EstadoTransmision.APAGADO
    assert tecnico.transmision.en_vivo_desde is None
    assert tecnico.transmision.segundos_restantes is None


async def test_inicio_inmediato_proyecta_en_vivo(tmp_path: Path) -> None:
    """Prueba 2: sin cuenta regresiva se pasa a ``EN VIVO`` sin esperar."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.iniciar_transmision(None)

    tecnico = await entorno.servicio.obtener_estado_tecnico()
    assert tecnico.transmision.estado is EstadoTransmision.EN_VIVO
    assert tecnico.transmision.cuenta_regresiva_segundos is None
    assert tecnico.transmision.en_vivo_desde == entorno.reloj.ahora()
    assert tecnico.transmision.segundos_restantes is None


async def test_inicio_con_segundos_proyecta_cuenta_regresiva(tmp_path: Path) -> None:
    """Prueba 3: con N segundos el estado observable es la cuenta regresiva."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.iniciar_transmision(10)

    tecnico = await entorno.servicio.obtener_estado_tecnico()
    assert tecnico.transmision.estado is EstadoTransmision.CUENTA_REGRESIVA
    assert tecnico.transmision.cuenta_regresiva_segundos == 10
    assert tecnico.transmision.segundos_restantes == 10


async def test_frontera_exacta_de_cuenta_regresiva_pasa_a_en_vivo(tmp_path: Path) -> None:
    """Prueba 4: la frontera es inclusiva y no requiere ningún comando extra.

    Un segundo antes todavía es cuenta regresiva; en el instante exacto ya es
    ``EN VIVO``. Nadie ejecutó una mutación entre ambos snapshots: la verdad la
    deriva el backend del reloj.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")
    await servicio.iniciar_transmision(10)

    entorno.reloj.avanzar(9)
    antes = await entorno.servicio.obtener_estado_tecnico()
    entorno.reloj.avanzar(1)
    justo = await entorno.servicio.obtener_estado_tecnico()

    assert antes.transmision.estado is EstadoTransmision.CUENTA_REGRESIVA
    assert antes.transmision.segundos_restantes == 1
    assert justo.transmision.estado is EstadoTransmision.EN_VIVO
    assert justo.transmision.segundos_restantes is None


async def test_detener_durante_cuenta_regresiva_vuelve_a_apagado(tmp_path: Path) -> None:
    """Prueba 5: detener cancela la cuenta regresiva sin llegar a EN VIVO."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")
    await servicio.iniciar_transmision(10)

    await servicio.detener_transmision()
    entorno.reloj.avanzar(60)

    tecnico = await entorno.servicio.obtener_estado_tecnico()
    assert tecnico.transmision.estado is EstadoTransmision.APAGADO


async def test_detener_estando_en_vivo_vuelve_a_apagado(tmp_path: Path) -> None:
    """Prueba 6: la orden manual es el único camino de salida de EN VIVO."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")
    await servicio.iniciar_transmision(None)

    await servicio.detener_transmision()

    tecnico = await entorno.servicio.obtener_estado_tecnico()
    assert tecnico.transmision.estado is EstadoTransmision.APAGADO


async def test_reconexion_durante_cuenta_regresiva_conserva_la_verdad_temporal(
    tmp_path: Path,
) -> None:
    """Prueba 7: dos snapshots sucesivos comparten la misma frontera absoluta.

    Es exactamente lo que ve un cliente que recarga la página o reconecta el
    SSE: ``en_vivo_desde`` no se mueve y ``segundos_restantes`` refleja el
    tiempo realmente transcurrido, no un contador reiniciado en el navegador.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")
    await servicio.iniciar_transmision(30)
    primero = await entorno.servicio.obtener_estado_tecnico()

    entorno.reloj.avanzar(12)
    segundo = await entorno.servicio.obtener_estado_tecnico()

    assert segundo.transmision.en_vivo_desde == primero.transmision.en_vivo_desde
    assert primero.transmision.segundos_restantes == 30
    assert segundo.transmision.segundos_restantes == 18


async def test_en_vivo_no_se_apaga_solo_con_el_paso_del_tiempo(tmp_path: Path) -> None:
    """Prueba 8: no existe duración automática de ``EN VIVO``."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")
    await servicio.iniciar_transmision(5)

    entorno.reloj.avanzar(60 * 60 * 8)

    tecnico = await entorno.servicio.obtener_estado_tecnico()
    assert tecnico.transmision.estado is EstadoTransmision.EN_VIVO


async def test_transmision_funciona_sin_preparacion_activa(tmp_path: Path) -> None:
    """El plano técnico es independiente del ciclo preparación/sesión."""

    entorno = crear_entorno_proyecciones(tmp_path)
    sin_preparacion(entorno)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.iniciar_transmision(None)

    tecnico = await entorno.servicio.obtener_estado_tecnico()
    assert tecnico.estado_global is EstadoGlobal.SIN_PREPARAR
    assert tecnico.transmision.estado is EstadoTransmision.EN_VIVO


async def test_detener_transmision_apagada_es_idempotente_y_no_audita(tmp_path: Path) -> None:
    """Un reintento de red no puede duplicar filas en el CSV institucional."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.detener_transmision()

    assert codigos_auditados(entorno) == []


async def test_ordenes_de_transmision_se_auditan_en_l2(tmp_path: Path) -> None:
    """Durante PREPARANDO/SESION las órdenes técnicas quedan en los tres CSV."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.iniciar_transmision(15)
    await servicio.detener_transmision()

    eventos = entorno.contexto.escritor_auditoria.eventos_recientes
    assert [evento.codigo_evento for evento in eventos] == [
        "TRANSMISION_INICIADA",
        "TRANSMISION_DETENIDA",
    ]
    assert all(evento.nivel is NivelAuditoria.L2 for evento in eventos)
    assert all(evento.etiqueta == "APOYO_TECNICO" for evento in eventos)


async def test_fallo_de_auditoria_no_aplica_la_orden_de_transmision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fallo cerrado: sin registro durable no hay cambio de estado técnico."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")
    monkeypatch.setattr(entorno.contexto.escritor_auditoria, "_fallado", True)

    from botonera2_backend.auditoria import ErrorAuditoria

    with pytest.raises(ErrorAuditoria):
        await servicio.iniciar_transmision(None)

    tecnico = await entorno.servicio.obtener_estado_tecnico()
    assert tecnico.transmision.estado is EstadoTransmision.APAGADO


# =============================================================================
# 2. Avisos técnicos
# =============================================================================


async def test_aviso_solo_moderacion_no_aparece_en_recinto(tmp_path: Path) -> None:
    """Prueba 9: la ranura del Recinto queda intacta."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.publicar_aviso("Revisar micrófono 3", DestinoAvisoTecnico.MODERACION, None)

    moderacion = await entorno.servicio.obtener_estado_moderacion()
    recinto = await entorno.servicio.obtener_estado_recinto()
    assert moderacion.tecnico.aviso is not None
    assert moderacion.tecnico.aviso.texto == "Revisar micrófono 3"
    assert recinto.tecnico.aviso is None


async def test_aviso_solo_recinto_no_aparece_en_moderacion(tmp_path: Path) -> None:
    """Prueba 10: la separación por destino es simétrica."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.publicar_aviso("Volvemos en cinco minutos", DestinoAvisoTecnico.RECINTO, None)

    moderacion = await entorno.servicio.obtener_estado_moderacion()
    recinto = await entorno.servicio.obtener_estado_recinto()
    assert moderacion.tecnico.aviso is None
    assert recinto.tecnico.aviso is not None
    assert recinto.tecnico.aviso.texto == "Volvemos en cinco minutos"


async def test_ambos_activa_los_dos_destinos_con_el_mismo_aviso(tmp_path: Path) -> None:
    """Prueba 11: ``AMBOS`` deja una única publicación coherente, no dos avisos."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(
        entorno,
        tmp_path / "mensajes.csv",
        identificadores=("aviso-unico",),
    )

    await servicio.publicar_aviso("Corte de energía", DestinoAvisoTecnico.AMBOS, 60)

    moderacion = await entorno.servicio.obtener_estado_moderacion()
    recinto = await entorno.servicio.obtener_estado_recinto()
    assert moderacion.tecnico.aviso is not None
    assert recinto.tecnico.aviso is not None
    assert moderacion.tecnico.aviso.aviso_id == recinto.tecnico.aviso.aviso_id == "aviso-unico"
    assert moderacion.tecnico.aviso.expira_en == recinto.tecnico.aviso.expira_en


async def test_aviso_sin_duracion_no_expira(tmp_path: Path) -> None:
    """Prueba 12: sin duración permanece hasta la cancelación manual."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")
    await servicio.publicar_aviso("Aviso permanente", DestinoAvisoTecnico.RECINTO, None)

    entorno.reloj.avanzar(60 * 60 * 24)

    recinto = await entorno.servicio.obtener_estado_recinto()
    assert recinto.tecnico.aviso is not None
    assert recinto.tecnico.aviso.expira_en is None
    assert recinto.tecnico.aviso.segundos_restantes is None


async def test_aviso_con_duracion_expira_en_la_frontera(tmp_path: Path) -> None:
    """Prueba 13: la expiración es autoritativa y ocurre sin ningún comando."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")
    await servicio.publicar_aviso("Aviso breve", DestinoAvisoTecnico.RECINTO, 30)

    entorno.reloj.avanzar(29)
    antes = await entorno.servicio.obtener_estado_recinto()
    entorno.reloj.avanzar(1)
    justo = await entorno.servicio.obtener_estado_recinto()

    assert antes.tecnico.aviso is not None
    assert antes.tecnico.aviso.segundos_restantes == 1
    assert justo.tecnico.aviso is None


async def test_cancelacion_manual_antes_del_vencimiento(tmp_path: Path) -> None:
    """Prueba 14: cancelar retira el aviso aunque todavía faltara tiempo."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")
    await servicio.publicar_aviso("Aviso cancelable", DestinoAvisoTecnico.RECINTO, 300)

    await servicio.cancelar_aviso(DestinoAvisoTecnico.RECINTO)

    recinto = await entorno.servicio.obtener_estado_recinto()
    assert recinto.tecnico.aviso is None
    assert entorno.estado.aviso_tecnico_recinto is None


async def test_publicar_reemplaza_solo_las_ranuras_alcanzadas(tmp_path: Path) -> None:
    """Prueba 15: publicar sobre un destino no deja huérfano el otro."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")
    await servicio.publicar_aviso("Aviso inicial", DestinoAvisoTecnico.AMBOS, None)

    await servicio.publicar_aviso("Solo moderación", DestinoAvisoTecnico.MODERACION, None)

    moderacion = await entorno.servicio.obtener_estado_moderacion()
    recinto = await entorno.servicio.obtener_estado_recinto()
    assert moderacion.tecnico.aviso is not None
    assert moderacion.tecnico.aviso.texto == "Solo moderación"
    assert recinto.tecnico.aviso is not None
    assert recinto.tecnico.aviso.texto == "Aviso inicial"


async def test_cancelar_ambos_limpia_las_dos_ranuras(tmp_path: Path) -> None:
    """Cancelar con ``AMBOS`` no deja restos en ninguno de los dos destinos."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")
    await servicio.publicar_aviso("Aviso doble", DestinoAvisoTecnico.AMBOS, None)

    await servicio.cancelar_aviso(DestinoAvisoTecnico.AMBOS)

    assert entorno.estado.aviso_tecnico_moderacion is None
    assert entorno.estado.aviso_tecnico_recinto is None


async def test_cancelar_destino_sin_aviso_es_idempotente_y_no_audita(tmp_path: Path) -> None:
    """Cancelar una ranura vacía no falla ni escribe una fila institucional."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.cancelar_aviso(DestinoAvisoTecnico.AMBOS)

    assert codigos_auditados(entorno) == []


async def test_reconexion_reconstruye_el_aviso_vigente(tmp_path: Path) -> None:
    """Prueba 16: un snapshot posterior conserva id, texto y vencimiento."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(
        entorno,
        tmp_path / "mensajes.csv",
        identificadores=("aviso-persistente",),
    )
    await servicio.publicar_aviso("Aviso vigente", DestinoAvisoTecnico.RECINTO, 120)
    primero = await entorno.servicio.obtener_estado_recinto()

    entorno.reloj.avanzar(45)
    segundo = await entorno.servicio.obtener_estado_recinto()

    assert primero.tecnico.aviso is not None
    assert segundo.tecnico.aviso is not None
    assert segundo.tecnico.aviso.aviso_id == primero.tecnico.aviso.aviso_id
    assert segundo.tecnico.aviso.expira_en == primero.tecnico.aviso.expira_en
    assert segundo.tecnico.aviso.segundos_restantes == 75


async def test_avisos_se_auditan_en_l2(tmp_path: Path) -> None:
    """Publicar y cancelar dejan su rastro institucional con etiqueta técnica.

    El aviso del ejemplo alcanza Recinto, así que desde WP-078 cada orden deja
    dos filas: la técnica ``L2`` que registra el comando y el marcador de sesión
    ``L3`` que delimita la presencia del texto en la pantalla pública. Esta
    prueba sigue cuidando la parte técnica; los marcadores tienen su propio
    módulo en ``test_marcadores_recinto_wp078.py``.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.publicar_aviso("Aviso auditado", DestinoAvisoTecnico.AMBOS, 30)
    await servicio.cancelar_aviso(DestinoAvisoTecnico.AMBOS)

    assert codigos_auditados(entorno) == [
        "AVISO_TECNICO_PUBLICADO",
        "INICIO",
        "AVISO_TECNICO_CANCELADO",
        "FIN",
    ]


# =============================================================================
# 3. Fronteras temporales sin polling
# =============================================================================


async def test_frontera_temporal_despierta_por_transmision_y_avisos(tmp_path: Path) -> None:
    """Prueba 17: el temporizador conoce la frontera más cercana pendiente.

    ``demora_hasta_proxima_frontera`` es lo que consume el servicio de
    lifespan: mientras devuelva un número, el backend publicará solo al cruzar
    esa frontera. Sin esta información habría que sondear periódicamente, que es
    justamente lo que el WP prohíbe.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.iniciar_transmision(50)
    await servicio.publicar_aviso("Aviso corto", DestinoAvisoTecnico.AMBOS, 20)

    demora = await entorno.ejecutor.leer_coherente(entorno.servicio.demora_hasta_proxima_frontera)
    assert demora == 20

    entorno.reloj.avanzar(20)
    demora_siguiente = await entorno.ejecutor.leer_coherente(
        entorno.servicio.demora_hasta_proxima_frontera
    )
    assert demora_siguiente == 30

    entorno.reloj.avanzar(30)
    assert (
        await entorno.ejecutor.leer_coherente(entorno.servicio.demora_hasta_proxima_frontera)
        is None
    )


async def test_frontera_temporal_existe_sin_preparacion_activa(tmp_path: Path) -> None:
    """Sin contexto operativo el temporizador sigue conociendo las fronteras.

    Antes de WP-055 la función devolvía ``None`` apenas faltaba el contexto.
    Como el plano técnico funciona en ``SIN_PREPARAR``, ese atajo habría dejado
    una cuenta regresiva sin nadie que publicara su vencimiento.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    sin_preparacion(entorno)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.iniciar_transmision(25)

    demora = await entorno.ejecutor.leer_coherente(entorno.servicio.demora_hasta_proxima_frontera)
    assert demora == 25


async def test_aviso_ambos_no_duplica_la_frontera(tmp_path: Path) -> None:
    """Las dos ranuras de un mismo aviso aportan un único despertar."""

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    await servicio.publicar_aviso("Aviso doble", DestinoAvisoTecnico.AMBOS, 40)

    demora = await entorno.ejecutor.leer_coherente(entorno.servicio.demora_hasta_proxima_frontera)
    assert demora == 40


# =============================================================================
# 4. Biblioteca de mensajes precargados
# =============================================================================


async def test_ciclo_crud_completo_persiste_en_csv(tmp_path: Path) -> None:
    """Prueba 19: alta, lectura, edición y baja se reflejan en el archivo."""

    ruta = tmp_path / "mensajes.csv"
    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, ruta, identificadores=("m1", "m2"))

    primero = await servicio.crear_mensaje("Prueba de sonido", DestinoAvisoTecnico.MODERACION)
    await servicio.crear_mensaje("Volvemos en cinco", DestinoAvisoTecnico.RECINTO)
    assert [item.mensaje_id for item in cargar_mensajes_tecnicos(ruta)] == ["m1", "m2"]

    actualizado = await servicio.actualizar_mensaje(
        primero.mensaje_id,
        "Prueba de sonido en curso",
        DestinoAvisoTecnico.AMBOS,
    )
    assert actualizado.mensaje_id == "m1"
    assert cargar_mensajes_tecnicos(ruta)[0].texto == "Prueba de sonido en curso"
    assert cargar_mensajes_tecnicos(ruta)[0].destino is DestinoAvisoTecnico.AMBOS

    await servicio.eliminar_mensaje("m1")
    assert [item.mensaje_id for item in cargar_mensajes_tecnicos(ruta)] == ["m2"]

    biblioteca = await servicio.obtener_biblioteca()
    assert [item.mensaje_id for item in biblioteca.mensajes] == ["m2"]


async def test_identificador_es_estable_ante_la_edicion(tmp_path: Path) -> None:
    """Prueba 21: editar no reasigna el id ni cambia la posición del mensaje."""

    ruta = tmp_path / "mensajes.csv"
    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, ruta, identificadores=("m1", "m2", "m3"))
    await servicio.crear_mensaje("Uno", DestinoAvisoTecnico.RECINTO)
    await servicio.crear_mensaje("Dos", DestinoAvisoTecnico.RECINTO)
    await servicio.crear_mensaje("Tres", DestinoAvisoTecnico.RECINTO)

    await servicio.actualizar_mensaje("m2", "Dos editado", DestinoAvisoTecnico.MODERACION)

    mensajes = cargar_mensajes_tecnicos(ruta)
    assert [item.mensaje_id for item in mensajes] == ["m1", "m2", "m3"]
    assert mensajes[1].texto == "Dos editado"


async def test_biblioteca_sobrevive_a_un_reinicio_simulado(tmp_path: Path) -> None:
    """Prueba 20: un backend nuevo relee exactamente lo que quedó en disco.

    Se descarta por completo el estado en memoria (equivalente a reiniciar el
    proceso, que según RN-GLOBAL-03 no restaura sesión ni presencia) y se
    vuelve a cargar la biblioteca desde el archivo.
    """

    ruta = tmp_path / "mensajes.csv"
    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, ruta, identificadores=("m1",))
    await servicio.crear_mensaje("Mensaje persistente", DestinoAvisoTecnico.AMBOS)

    otro = crear_entorno_proyecciones(tmp_path / "segundo")
    from botonera2_backend.servicios.apoyo_tecnico import leer_biblioteca_mensajes_tecnicos

    otro.estado.biblioteca_mensajes_tecnicos = leer_biblioteca_mensajes_tecnicos(ruta)

    tecnico = await otro.servicio.obtener_estado_tecnico()
    assert tecnico.biblioteca.disponible
    assert [item.mensaje_id for item in tecnico.biblioteca.mensajes] == ["m1"]
    assert tecnico.biblioteca.mensajes[0].texto == "Mensaje persistente"


async def test_editar_o_eliminar_un_id_desconocido_se_rechaza(tmp_path: Path) -> None:
    """Un id viejo revela una copia desactualizada, no habilita crear ni borrar."""

    ruta = tmp_path / "mensajes.csv"
    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, ruta)

    with pytest.raises(ErrorMensajeTecnicoNoExistente):
        await servicio.actualizar_mensaje("inexistente", "Texto", DestinoAvisoTecnico.RECINTO)
    with pytest.raises(ErrorMensajeTecnicoNoExistente):
        await servicio.eliminar_mensaje("inexistente")

    assert not ruta.exists()


async def test_biblioteca_invalida_rechaza_toda_escritura(tmp_path: Path) -> None:
    """Prueba 23 y 25: un archivo corrupto nunca se sobrescribe en silencio."""

    ruta = tmp_path / "mensajes.csv"
    ruta.write_text("id,texto\nroto,sin destino\n", encoding="utf-8")
    entorno = crear_entorno_proyecciones(tmp_path)
    from botonera2_backend.servicios.apoyo_tecnico import leer_biblioteca_mensajes_tecnicos

    entorno.estado.biblioteca_mensajes_tecnicos = leer_biblioteca_mensajes_tecnicos(ruta)
    servicio = crear_servicio_apoyo_tecnico(entorno, ruta)
    contenido_previo = ruta.read_bytes()

    with pytest.raises(ErrorBibliotecaMensajesNoDisponible):
        await servicio.crear_mensaje("Nuevo", DestinoAvisoTecnico.RECINTO)

    assert ruta.read_bytes() == contenido_previo
    tecnico = await entorno.servicio.obtener_estado_tecnico()
    assert not tecnico.biblioteca.disponible
    assert tecnico.biblioteca.motivo == "BIBLIOTECA_MENSAJES_INVALIDA"
    assert tecnico.biblioteca.mensajes == ()


async def test_altas_concurrentes_se_serializan_sin_perder_mensajes(tmp_path: Path) -> None:
    """Prueba 24: el serializador único ordena las escrituras al mismo archivo.

    Se lanzan cinco altas a la vez. Como todas pasan por el mismo
    ``EjecutorMutaciones``, se aplican una detrás de otra: ninguna lee una
    biblioteca desactualizada ni pisa el resultado de la anterior.
    """

    ruta = tmp_path / "mensajes.csv"
    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(
        entorno,
        ruta,
        identificadores=tuple(f"m{numero}" for numero in range(1, 6)),
    )

    await asyncio.gather(
        *(
            servicio.crear_mensaje(f"Mensaje {numero}", DestinoAvisoTecnico.RECINTO)
            for numero in range(1, 6)
        )
    )

    persistidos = cargar_mensajes_tecnicos(ruta)
    assert len(persistidos) == 5
    assert {item.mensaje_id for item in persistidos} == {"m1", "m2", "m3", "m4", "m5"}
    biblioteca = await servicio.obtener_biblioteca()
    assert biblioteca.mensajes == persistidos


async def test_fallo_de_persistencia_no_actualiza_la_memoria(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La memoria nunca puede quedar adelantada respecto del archivo real."""

    ruta = tmp_path / "mensajes.csv"
    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, ruta, identificadores=("m1",))
    await servicio.crear_mensaje("Persistido", DestinoAvisoTecnico.RECINTO)

    import botonera2_backend.servicios.apoyo_tecnico as modulo_servicio
    from botonera2_backend.dominio.apoyo_tecnico import ErrorPersistenciaMensajesTecnicos

    def guardado_fallido(*_argumentos: object, **_claves: object) -> None:
        raise ErrorPersistenciaMensajesTecnicos("disco lleno simulado")

    monkeypatch.setattr(modulo_servicio, "guardar_mensajes_tecnicos", guardado_fallido)

    with pytest.raises(ErrorPersistenciaMensajesTecnicos):
        await servicio.crear_mensaje("No persistido", DestinoAvisoTecnico.RECINTO)

    biblioteca = await servicio.obtener_biblioteca()
    assert [item.texto for item in biblioteca.mensajes] == ["Persistido"]
    assert [item.texto for item in cargar_mensajes_tecnicos(ruta)] == ["Persistido"]


async def test_crud_de_biblioteca_no_escribe_auditoria(tmp_path: Path) -> None:
    """El mantenimiento de configuración no es una interacción de la sesión.

    Igual que editar ``config/concejales.csv``, administrar la biblioteca no
    produce filas institucionales: su rastro durable es el propio CSV. Auditarla
    obligaría además a elegir un orden entre dos escrituras durables, con el
    riesgo de dejar el registro y el archivo contradiciéndose.
    """

    entorno = crear_entorno_proyecciones(tmp_path)
    servicio = crear_servicio_apoyo_tecnico(entorno, tmp_path / "mensajes.csv")

    mensaje = await servicio.crear_mensaje("Cualquiera", DestinoAvisoTecnico.RECINTO)
    await servicio.eliminar_mensaje(mensaje.mensaje_id)

    assert codigos_auditados(entorno) == []


async def test_biblioteca_vacia_por_defecto_esta_disponible(tmp_path: Path) -> None:
    """El estado recién creado permite escribir desde el primer comando."""

    entorno = crear_entorno_proyecciones(tmp_path)

    assert entorno.estado.biblioteca_mensajes_tecnicos == BibliotecaMensajesTecnicos()

    tecnico = await entorno.servicio.obtener_estado_tecnico()
    assert tecnico.biblioteca.disponible
    assert tecnico.biblioteca.mensajes == ()
