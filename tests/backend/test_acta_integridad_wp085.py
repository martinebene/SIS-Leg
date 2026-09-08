"""Integridad estructural del L3 y sanitización del acta institucional (WP-085 I002).

Qué demuestra cada bloque:

1. **Fallo cerrado estructural.** Un L3 cuyo encabezado, cantidad de columnas,
   nivel, timestamp o familia ``(tag, event_code)`` no sea el canónico hace
   fallar el acta **entera**. La iteración anterior salteaba una fila truncada y
   declaraba el informe exitoso igual: ese comportamiento está prohibido, porque
   un informe formal que aparenta estar completo mientras omite evidencia es peor
   que un informe que no se generó.
2. **Sanitización con eventos reales.** El acta se deriva de un recorrido
   completo ejecutado por los servicios reales a través de la API, no de filas
   sintéticas ya limpias. Se comprueba que no aparezca ningún token técnico
   —identificadores, huellas, DNI, posiciones de cola, banderas— y que sí
   aparezcan los hechos institucionales que el acta debe conservar.
3. **Cobertura del catálogo.** Un análisis del código fuente encuentra todos los
   ``registrar_evento(NivelAuditoria.L3, ...)`` del backend y exige que cada
   familia tenga política declarada. Si un WP futuro agrega un ``event_code`` L3
   sin agregar su redacción, CI falla antes de que ese evento pueda llegar a un
   acta.
"""

from __future__ import annotations

import ast
from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import pytest
from conftest import (
    LINEA_LOGS,
    LINEA_QUORUM,
    TOML_CANONICO,
    escribir_padron,
    escribir_system_toml,
    filas_padron_valido,
)
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sis_leg_backend.aplicacion import crear_aplicacion
from sis_leg_backend.auditoria import ENCABEZADO_CSV, EscritorAuditoriaCsv, NivelAuditoria
from sis_leg_backend.dominio.estado import EstadoGlobal
from sis_leg_backend.recursos import obtener_recursos_aplicacion
from sis_leg_backend.servicios import (
    apoyo_tecnico,
    entrada,
    finalizacion_votacion,
    palabra,
    politica_acta,
    preparacion,
    remapeo,
    sesion,
    votacion,
)
from sis_leg_backend.servicios.acta_institucional import componer_acta, ruta_acta_de_conjunto
from sis_leg_backend.servicios.politica_acta import POLITICAS_ACTA, ErrorActaNoDerivable

pytestmark = pytest.mark.anyio

INICIO_CONJUNTO = datetime(2026, 9, 8, 10, 30, 0)
HORA_EVENTOS = datetime(2026, 9, 8, 11, 45, 7)

# Tokens que jamás pueden aparecer en un acta institucional. La lista combina los
# que el ORCHESTRATOR enumeró y los prefijos de clave que hoy produce cada
# servicio. Se comprueba sobre un acta derivada de eventos reales, no inventados.
TOKENS_TECNICOS_PROHIBIDOS = (
    "DNI=",
    "remapeo_id",
    "fingerprint",
    "dispositivo=",
    "dev01",
    "dev05",
    "D-01",
    " id=",
    "posicion=",
    "posicion_previa=",
    "posicion_origen=",
    "causa=",
    "estado_previo=",
    "resultado_previo=",
    "resultado_nuevo=",
    "motivo=",
    "motivo_manual=",
    "tipo_mayoria=",
    "denominador=",
    "cociente=",
    "factor=",
    "base=",
    "persistencia=",
    "votos_conservados=",
    "quorum_requerido=",
    "presentes=",
    "=true",
    "=false",
    "L3",
    "event_code",
)


# ---------------------------------------------------------------------------
# 1. Integridad estructural del archivo L3
# ---------------------------------------------------------------------------


def escribir_l3(tmp_path: Path, filas: list[list[str]], *, encabezado: list[str] | None) -> Path:
    """Escribe a mano un archivo con nombre canónico y contenido controlado.

    Se escribe directamente en vez de usar el escritor de auditoría porque estas
    pruebas necesitan producir exactamente las formas que el escritor **no**
    puede generar: una fila truncada, una columna de más, un encabezado alterado.
    Es la simulación de un archivo dañado, editado a mano o escrito por una
    versión distinta del sistema.
    """

    carpeta = tmp_path / "2026-09-08"
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / "2026-09-08_10-30-00-L3.csv"
    lineas = [] if encabezado is None else [";".join(encabezado)]
    lineas.extend(";".join(fila) for fila in filas)
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8-sig", newline="")
    return ruta


def fila_valida(secuencia: int = 1) -> list[str]:
    """Fila canónica mínima de seis columnas con una familia real del catálogo."""

    return [
        str(secuencia),
        "2026-09-08 11:45:07",
        "L3",
        "EVENTO",
        "INICIO",
        "Cuarto intermedio",
    ]


def test_fila_con_cinco_columnas_hace_fallar_el_acta_completa(tmp_path: Path) -> None:
    """Una fila truncada ya no se saltea: aborta el informe entero.

    Es la corrección directa del hallazgo de I001. Antes, esta fila desaparecía
    del TXT y el resto se publicaba como si el acta estuviera completa.
    """

    ruta = escribir_l3(
        tmp_path,
        [fila_valida(1), fila_valida(2)[:5]],
        encabezado=list(ENCABEZADO_CSV),
    )

    with pytest.raises(ErrorActaNoDerivable) as fallo:
        componer_acta(ruta)

    assert "Fila 3" in str(fallo.value)
    assert "6 columnas" in str(fallo.value)


def test_fila_con_siete_columnas_hace_fallar_el_acta_completa(tmp_path: Path) -> None:
    """Una columna de más también es forma no canónica y no se ignora."""

    ruta = escribir_l3(
        tmp_path,
        [[*fila_valida(1), "columna_extra"]],
        encabezado=list(ENCABEZADO_CSV),
    )

    with pytest.raises(ErrorActaNoDerivable):
        componer_acta(ruta)


def test_encabezado_alterado_hace_fallar_el_acta(tmp_path: Path) -> None:
    """Sin el encabezado canónico ninguna fila puede interpretarse con garantías."""

    encabezado: list[str] = list(ENCABEZADO_CSV)
    encabezado[3] = "etiqueta"
    ruta = escribir_l3(tmp_path, [fila_valida()], encabezado=encabezado)

    with pytest.raises(ErrorActaNoDerivable) as fallo:
        componer_acta(ruta)

    assert "encabezado" in str(fallo.value)


def test_archivo_sin_encabezado_hace_fallar_el_acta(tmp_path: Path) -> None:
    """Un archivo vacío no produce un acta vacía: produce un fallo explícito."""

    ruta = escribir_l3(tmp_path, [], encabezado=None)

    with pytest.raises(ErrorActaNoDerivable):
        componer_acta(ruta)


def test_event_code_desconocido_hace_fallar_el_acta(tmp_path: Path) -> None:
    """Una familia sin política no puede publicarse copiando el mensaje crudo.

    Es la defensa contra un WP futuro que agregue un evento L3 con metadata
    técnica embebida y nadie revise su redacción: el acta falla en vez de filtrar.
    """

    fila = fila_valida()
    fila[4] = "CODIGO_QUE_NADIE_DECLARO"
    ruta = escribir_l3(tmp_path, [fila], encabezado=list(ENCABEZADO_CSV))

    with pytest.raises(ErrorActaNoDerivable) as fallo:
        componer_acta(ruta)

    assert "política de redacción" in str(fallo.value)


def test_mensaje_de_familia_conocida_con_forma_inesperada_hace_fallar_el_acta(
    tmp_path: Path,
) -> None:
    """Un campo nuevo al final de un mensaje conocido rompe el patrón anclado.

    Este es el mecanismo que impide que un WP futuro agregue ``; equipo=dev07`` a
    un mensaje existente y ese dato llegue al acta sin que nadie lo decida.
    """

    fila = fila_valida()
    fila[3] = "REMAPEO"
    fila[4] = "REMAPEO_AUTORIZADO"
    fila[5] = (
        "Autorización humana de remapeo remapeo_id=r1; dispositivo=dev05; "
        "fingerprint_anterior=fp1; fingerprint_candidato=fp2; "
        "persistencia=TEMPORAL; equipo=dev07"
    )
    ruta = escribir_l3(tmp_path, [fila], encabezado=list(ENCABEZADO_CSV))

    with pytest.raises(ErrorActaNoDerivable):
        componer_acta(ruta)


def test_timestamp_ilegible_hace_fallar_el_acta(tmp_path: Path) -> None:
    """Sin hora válida no hay línea de acta posible, y no se inventa una."""

    fila = fila_valida()
    fila[1] = "08/09/2026 11:45"
    ruta = escribir_l3(tmp_path, [fila], encabezado=list(ENCABEZADO_CSV))

    with pytest.raises(ErrorActaNoDerivable) as fallo:
        componer_acta(ruta)

    assert "timestamp" in str(fallo.value)


def test_nivel_distinto_de_l3_hace_fallar_el_acta(tmp_path: Path) -> None:
    """El archivo L3 contiene sólo eventos L3; otro nivel indica corrupción."""

    fila = fila_valida()
    fila[2] = "L2"
    ruta = escribir_l3(tmp_path, [fila], encabezado=list(ENCABEZADO_CSV))

    with pytest.raises(ErrorActaNoDerivable):
        componer_acta(ruta)


def test_seq_no_numerico_hace_fallar_el_acta(tmp_path: Path) -> None:
    """La secuencia es parte de la forma canónica y también se valida."""

    fila = fila_valida()
    fila[0] = "primera"
    ruta = escribir_l3(tmp_path, [fila], encabezado=list(ENCABEZADO_CSV))

    with pytest.raises(ErrorActaNoDerivable):
        componer_acta(ruta)


def test_un_l3_integro_con_muchas_filas_produce_una_linea_por_fila(tmp_path: Path) -> None:
    """La validación estricta no rompe el caso normal de más de 200 eventos."""

    escritor = EscritorAuditoriaCsv(tmp_path / "logs", INICIO_CONJUNTO, reloj=lambda: HORA_EVENTOS)
    for numero in range(1, 251):
        escritor.registrar_evento(
            NivelAuditoria.L3,
            "EVENTO",
            "INICIO",
            f"Aviso numero {numero}",
        )
    ruta_l3 = escritor.rutas[NivelAuditoria.L3]
    escritor.cerrar()

    cuerpo = componer_acta(ruta_l3).splitlines()[4:]

    assert len(cuerpo) == 250


# ---------------------------------------------------------------------------
# 2. Sanitización con eventos producidos por los servicios reales
# ---------------------------------------------------------------------------


class BridgeFalso:
    """Autoridad física mínima para llegar a ``REMAPEO_AUTORIZADO`` sin hardware.

    Sólo implementa lo que el servicio de remapeo necesita para recorrer
    inicio -> candidato -> confirmación. Los fingerprints son deliberadamente
    reconocibles para poder afirmar después que no llegaron al acta.
    """

    FINGERPRINT_ANTERIOR = "lin|vendor=1001|product=2001|phys=usb-1|name=Anterior"
    FINGERPRINT_CANDIDATO = "lin|vendor=9001|product=9001|phys=usb-9|name=Candidato"

    def __init__(self) -> None:
        self.estados: dict[str, object] = {}

    def iniciar(self, remapeo_id: str, dispositivo: str) -> object:
        from sis_leg_backend.servicios.cliente_bridge import EstadoControlBridge

        estado = EstadoControlBridge(
            remapeo_id=remapeo_id,
            dispositivo=dispositivo,
            estado="CAPTURANDO",
            fingerprint_anterior=self.FINGERPRINT_ANTERIOR,
            candidato=None,
            diagnostico=None,
            persistencia=None,
            error=None,
        )
        self.estados[remapeo_id] = estado
        return estado

    def confirmar(self, remapeo_id: str, fingerprint: str, persistencia: str) -> object:
        from sis_leg_backend.servicios.cliente_bridge import EstadoControlBridge

        estado = EstadoControlBridge(
            remapeo_id=remapeo_id,
            dispositivo="dev01",
            estado="APLICADO",
            fingerprint_anterior=self.FINGERPRINT_ANTERIOR,
            candidato=fingerprint,
            diagnostico="Teclado sustituto",
            persistencia=persistencia,
            error=None,
        )
        self.estados[remapeo_id] = estado
        return estado


def preparar_archivos(
    directorio: Path,
    *,
    directorio_copia: Path | None = None,
) -> None:
    """Instala configuración y padrón con dispositivos ``devXX`` y quórum 2.

    ``directorio_copia`` permite verificar que un L3 inválido detenga la copia
    externa antes de tocar su destino. El valor se agrega sólo a la configuración
    aislada de la prueba; la configuración operativa local permanece intacta.
    """

    carpeta = directorio / "config"
    carpeta.mkdir(parents=True, exist_ok=True)
    linea_rutas = f'logs_dir = "{directorio / "logs"}"'
    if directorio_copia is not None:
        linea_rutas += f'\nlogs_copy_dir = "{directorio_copia}"'
    contenido = TOML_CANONICO.replace(LINEA_LOGS, linea_rutas).replace(LINEA_QUORUM, "quorum = 2")
    escribir_system_toml(carpeta / "system.toml", contenido)
    filas = filas_padron_valido()
    for numero, fila in enumerate(filas, start=1):
        fila[5] = f"dev{numero:02d}"
    escribir_padron(carpeta / "concejales.csv", filas)


@asynccontextmanager
async def cliente_de_prueba(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    directorio_copia: Path | None = None,
) -> AsyncGenerator[tuple[AsyncClient, FastAPI, BridgeFalso]]:
    """Entrega cliente, aplicación y bridge falso con lifespan real."""

    preparar_archivos(tmp_path, directorio_copia=directorio_copia)
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()
    async with aplicacion.router.lifespan_context(aplicacion):
        bridge = BridgeFalso()
        recursos = obtener_recursos_aplicacion(aplicacion)
        monkeypatch.setattr(recursos.cliente_control_bridge, "iniciar", bridge.iniciar)
        monkeypatch.setattr(recursos.cliente_control_bridge, "confirmar", bridge.confirmar)
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            yield cliente, aplicacion, bridge


def rutas_del_conjunto_activo(aplicacion: FastAPI) -> dict[NivelAuditoria, Path]:
    """Copia las rutas del conjunto abierto antes de que el cierre las suelte."""

    estado = obtener_recursos_aplicacion(aplicacion).estado_operativo
    contexto = estado.contexto_operativo_activo()
    assert contexto is not None
    return dict(contexto.escritor_auditoria.rutas)


async def recorrido_institucional_completo(cliente: AsyncClient) -> set[str]:
    """Ejecuta con servicios reales una sesión que toca todas las familias L3.

    El orden importa: cada paso deja al menos un evento L3 de una familia
    distinta, de modo que el acta resultante sea una muestra representativa de
    todo lo que el sistema sabe registrar hoy.
    """

    # Preparación, presencia de dos bancas y remapeo de un dispositivo.
    assert (await cliente.post("/api/v1/preparacion")).status_code == 204
    for dispositivo in ("dev01", "dev02"):
        respuesta = await cliente.post(
            "/api/v1/entradas/tecla",
            json={"dispositivo": dispositivo, "tecla": "9"},
        )
        assert respuesta.status_code == 200

    inicio = await cliente.post("/api/v1/remapeos", json={"dispositivo": "dev05"})
    assert inicio.status_code == 201
    remapeo_id = inicio.json()["remapeo_id"]
    candidato = await cliente.post(
        f"/api/v1/interno/remapeos/{remapeo_id}/candidato",
        json={
            "fingerprint": BridgeFalso.FINGERPRINT_CANDIDATO,
            "diagnostico": "Teclado sustituto",
        },
    )
    assert candidato.status_code == 200
    confirmacion = await cliente.post(
        f"/api/v1/remapeos/{remapeo_id}/confirmacion",
        json={"persistencia": "TEMPORAL"},
    )
    assert confirmacion.status_code == 204

    # Autoridades y apertura.
    assert (
        await cliente.patch(
            "/api/v1/preparacion",
            json={
                "numero_sesion": 59,
                "presidencia": "Presidencia Inicial",
                "secretaria_legislativa": "Secretaría Inicial",
            },
        )
    ).status_code == 204
    assert (await cliente.post("/api/v1/sesion")).status_code == 204
    assert (
        await cliente.patch("/api/v1/sesion", json={"presidencia": "Presidencia Definitiva"})
    ).status_code == 204

    # Marcadores INICIO/FIN del recinto.
    aviso = await cliente.post(
        "/api/v1/apoyo-tecnico/avisos",
        json={"texto": "Cuarto intermedio de quince minutos", "destino": "RECINTO"},
    )
    assert aviso.status_code in (200, 201, 204)
    assert (await cliente.delete("/api/v1/apoyo-tecnico/avisos/RECINTO")).status_code in (200, 204)

    # Palabra: pedido, retiro, nuevo pedido, otorgamiento y las dos finalizaciones.
    async def tecla_palabra(dispositivo: str) -> None:
        respuesta = await cliente.post(
            "/api/v1/entradas/tecla",
            json={"dispositivo": dispositivo, "tecla": "7"},
        )
        assert respuesta.status_code == 200

    await tecla_palabra("dev01")
    await tecla_palabra("dev01")
    await tecla_palabra("dev01")
    assert (await cliente.post("/api/v1/palabra")).status_code == 204
    assert (await cliente.delete("/api/v1/palabra")).status_code == 204
    await tecla_palabra("dev02")
    assert (await cliente.post("/api/v1/palabra")).status_code == 204
    await tecla_palabra("dev02")

    # Votación de mayoría simple que termina EMPATADA y se resuelve por desempate.
    empatada = await cliente.post(
        "/api/v1/votaciones",
        json={
            "numero_votacion": 1,
            "tipo": "Mocion",
            "tema": "Ordenanza de alumbrado público",
            "tipo_mayoria": "SIMPLE",
        },
    )
    assert empatada.status_code == 201
    id_empatada = empatada.json()["id"]
    for dispositivo, tecla in (("dev01", "1"), ("dev02", "3")):
        respuesta = await cliente.post(
            "/api/v1/entradas/tecla",
            json={"dispositivo": dispositivo, "tecla": tecla},
        )
        assert respuesta.status_code == 200
    desempate = await cliente.post(
        f"/api/v1/votaciones/{id_empatada}/desempate",
        json={"sentido": "POSITIVO"},
    )
    assert desempate.status_code in (200, 204)

    # Votación de mayoría especial que llega a resultado final.
    especial = await cliente.post(
        "/api/v1/votaciones",
        json={
            "numero_votacion": 2,
            "tipo": "Despacho HA",
            "tema": "Convenio con la Provincia",
            "tipo_mayoria": "ESPECIAL",
            "factor": 0.5,
            "base": "PRESENTES",
        },
    )
    assert especial.status_code == 201
    for dispositivo, tecla in (("dev01", "1"), ("dev02", "2")):
        respuesta = await cliente.post(
            "/api/v1/entradas/tecla",
            json={"dispositivo": dispositivo, "tecla": tecla},
        )
        assert respuesta.status_code == 200

    # Votación finalizada manualmente como INCONCLUSA.
    manual = await cliente.post(
        "/api/v1/votaciones",
        json={
            "numero_votacion": 3,
            "tipo": "Mocion",
            "tema": "Expediente sin despacho",
            "tipo_mayoria": "SIMPLE",
        },
    )
    assert manual.status_code == 201
    id_manual = manual.json()["id"]
    finalizacion = await cliente.post(
        f"/api/v1/votaciones/{id_manual}/finalizacion",
        json={"motivo": "Se retira el expediente del tratamiento"},
    )
    assert finalizacion.status_code in (200, 204)

    # Votación que queda INCONCLUSA por pérdida de quórum al ausentarse una banca.
    quorum = await cliente.post(
        "/api/v1/votaciones",
        json={
            "numero_votacion": 4,
            "tipo": "Mocion",
            "tema": "Expediente interrumpido",
            "tipo_mayoria": "SIMPLE",
        },
    )
    assert quorum.status_code == 201
    ausencia = await cliente.post(
        "/api/v1/entradas/tecla",
        json={"dispositivo": "dev02", "tecla": "9"},
    )
    assert ausencia.status_code == 200

    # Los identificadores se devuelven sólo a la prueba adversarial: permiten
    # demostrar que ninguno de los UUID reales persistidos en el L3 llegó al
    # informe. No alcanza con buscar un patrón genérico que también podría
    # coincidir con fechas o texto humano.
    return {
        remapeo_id,
        id_empatada,
        especial.json()["id"],
        id_manual,
        quorum.json()["id"],
    }


async def test_acta_de_una_sesion_real_no_contiene_metadata_tecnica(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El acta derivada de servicios reales queda libre de todo token técnico.

    Es la prueba adversarial que exige el hallazgo: los mensajes no se inventan
    limpios, los produce el backend con los mismos servicios que corren en
    producción, incluidos remapeo, desempate y finalización inconclusa.
    """

    async with cliente_de_prueba(tmp_path, monkeypatch) as (cliente, aplicacion, _bridge):
        identificadores = await recorrido_institucional_completo(cliente)
        rutas = rutas_del_conjunto_activo(aplicacion)

        respuesta = await cliente.delete("/api/v1/sesion")

        assert respuesta.status_code == 200
        assert respuesta.json()["acta_generada"] is True

        acta = ruta_acta_de_conjunto(rutas[NivelAuditoria.L3]).read_text(encoding="utf-8")

    for token in TOKENS_TECNICOS_PROHIBIDOS:
        assert token not in acta, f"El acta filtró el token técnico {token!r}"
    for identificador in identificadores:
        assert identificador not in acta
    assert BridgeFalso.FINGERPRINT_CANDIDATO not in acta
    assert BridgeFalso.FINGERPRINT_ANTERIOR not in acta


async def test_acta_de_una_sesion_real_conserva_los_hechos_institucionales(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sanear no puede vaciar el acta: cada hecho sigue siendo reconocible.

    Se comprueba el contenido humano exigido por el WP: identidad y banca,
    número y tema de la votación, sentido del voto, resultados, apertura y
    cierre, autoridad actualizada, hechos de palabra y el remapeo como hecho
    institucional legible.
    """

    async with cliente_de_prueba(tmp_path, monkeypatch) as (cliente, aplicacion, _bridge):
        await recorrido_institucional_completo(cliente)
        rutas = rutas_del_conjunto_activo(aplicacion)
        assert (await cliente.delete("/api/v1/sesion")).status_code == 200
        acta = ruta_acta_de_conjunto(rutas[NivelAuditoria.L3]).read_text(encoding="utf-8")

    esperados = (
        "Preparación del recinto iniciada",
        "Se autorizó el reemplazo de un dispositivo de votación",
        "Presidencia actualizado",
        "Apertura de sesión Nº59",
        "Inicio: Cuarto intermedio de quince minutos",
        "Fin: Cuarto intermedio de quince minutos",
        "Pedido de palabra registrado:",
        "Pedido de palabra retirado:",
        "Uso de la palabra otorgado:",
        "Uso de la palabra finalizado por Moderación:",
        "Uso de la palabra finalizado a pedido del propio concejal:",
        "Votación Nro 1 abierta.",
        "Tema: Ordenanza de alumbrado público.",
        "Mayoría simple.",
        "Voto ordinario en la votación Nro 1:",
        "votó POSITIVO.",
        "votó NEGATIVO.",
        "emitieron su voto todos los concejales presentes.",
        "Voto de desempate de la Presidencia en la votación Nro 1: POSITIVO",
        "Resultado de la votación Nro 1 por desempate de la Presidencia: APROBADA.",
        "Mayoría especial: proporción requerida",
        "Resultado de la votación Nro 2 por mayoría especial:",
        "Base de cálculo:",
        "sobre los concejales presentes.",
        "Votación Nro 3 finalizada como INCONCLUSA por decisión de Moderación.",
        "Motivo: Se retira el expediente del tratamiento.",
        "se AUSENTÓ",
        "Votación Nro 4 finalizada como INCONCLUSA por pérdida de quórum.",
        "Cierre de sesión Nº59",
    )
    for fragmento in esperados:
        assert fragmento in acta, f"El acta perdió el hecho institucional {fragmento!r}"

    # Una línea por fila del L3, sin omisiones ni duplicados.
    with rutas[NivelAuditoria.L3].open(encoding="utf-8-sig", newline="") as archivo:
        filas_l3 = archivo.read().count("\n") - 1
    assert len(acta.splitlines()) == 4 + filas_l3


async def test_acta_conserva_la_finalizacion_inconclusa_por_cierre_de_sesion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La tercera causa de INCONCLUSA sólo aparece al cerrar con una pendiente."""

    async with cliente_de_prueba(tmp_path, monkeypatch) as (cliente, aplicacion, _bridge):
        assert (await cliente.post("/api/v1/preparacion")).status_code == 204
        for dispositivo in ("dev01", "dev02"):
            assert (
                await cliente.post(
                    "/api/v1/entradas/tecla",
                    json={"dispositivo": dispositivo, "tecla": "9"},
                )
            ).status_code == 200
        assert (
            await cliente.patch(
                "/api/v1/preparacion",
                json={
                    "numero_sesion": 60,
                    "presidencia": "Presidencia",
                    "secretaria_legislativa": "Secretaría",
                },
            )
        ).status_code == 204
        assert (await cliente.post("/api/v1/sesion")).status_code == 204
        assert (
            await cliente.post(
                "/api/v1/votaciones",
                json={
                    "numero_votacion": 1,
                    "tipo": "Mocion",
                    "tema": "Expediente sin resolver",
                    "tipo_mayoria": "SIMPLE",
                },
            )
        ).status_code == 201
        rutas = rutas_del_conjunto_activo(aplicacion)

        respuesta = await cliente.delete("/api/v1/sesion")

        assert respuesta.status_code == 200
        assert respuesta.json()["acta_generada"] is True
        acta = ruta_acta_de_conjunto(rutas[NivelAuditoria.L3]).read_text(encoding="utf-8")

    assert "Votación Nro 1 finalizada como INCONCLUSA por el cierre de la sesión." in acta
    for token in TOKENS_TECNICOS_PROHIBIDOS:
        assert token not in acta


async def test_acta_de_una_preparacion_cancelada_es_derivable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancelar la preparación también cierra un conjunto, y su L3 debe leerse."""

    async with cliente_de_prueba(tmp_path, monkeypatch) as (cliente, aplicacion, _bridge):
        assert (await cliente.post("/api/v1/preparacion")).status_code == 204
        rutas = rutas_del_conjunto_activo(aplicacion)
        assert (await cliente.delete("/api/v1/preparacion")).status_code == 204

    cuerpo = componer_acta(rutas[NivelAuditoria.L3]).splitlines()[4:]

    assert cuerpo[0].endswith("Preparación del recinto iniciada")
    assert cuerpo[-1].endswith("Preparación del recinto cancelada")


@pytest.mark.parametrize(
    "corrupcion",
    ("FILA_CINCO_COLUMNAS", "FILA_SIETE_COLUMNAS", "ENCABEZADO", "CODIGO_DESCONOCIDO"),
)
async def test_cierre_con_l3_invalido_falla_sin_tocar_csv_ni_copia(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    corrupcion: str,
) -> None:
    """Cada forma inválida falla después del cierre durable, sin omitir evidencia.

    La corrupción se introduce dentro de un reemplazo controlado del efecto
    post-cierre: cuando corre este wrapper, ``SESION_CERRADA`` ya fue persistido,
    el writer ya cerró sus tres archivos y el estado ya volvió a
    ``SIN_PREPARAR``. Así se prueba el recorrido real de la API sin escribir a la
    vez que el escritor institucional mantiene un descriptor abierto.

    Para cada caso se capturan los bytes de L1/L2/L3 inmediatamente antes de
    invocar el generador real. El resultado debe conservar esos mismos bytes,
    informar ``acta_generada=false`` y no crear siquiera la carpeta fechada de
    copia externa.
    """

    destino = tmp_path / "copia-externa"
    destino.mkdir()
    evidencia_cerrada: dict[Path, bytes] = {}

    async with cliente_de_prueba(
        tmp_path,
        monkeypatch,
        directorio_copia=destino,
    ) as (cliente, aplicacion, _bridge):
        assert (await cliente.post("/api/v1/preparacion")).status_code == 204
        for dispositivo in ("dev01", "dev02"):
            assert (
                await cliente.post(
                    "/api/v1/entradas/tecla",
                    json={"dispositivo": dispositivo, "tecla": "9"},
                )
            ).status_code == 200
        assert (
            await cliente.patch(
                "/api/v1/preparacion",
                json={
                    "numero_sesion": 61,
                    "presidencia": "Presidencia",
                    "secretaria_legislativa": "Secretaría",
                },
            )
        ).status_code == 204
        assert (await cliente.post("/api/v1/sesion")).status_code == 204
        rutas = rutas_del_conjunto_activo(aplicacion)

        generar_real = sesion.generar_acta_y_copiar_conjunto

        def generar_con_fuente_corrupta(
            rutas_conjunto: dict[NivelAuditoria, Path],
            directorio_copia: str | None,
        ) -> object:
            """Corrompe el L3 ya cerrado y delega al generador productivo real."""

            ruta_l3 = rutas_conjunto[NivelAuditoria.L3]
            lineas = ruta_l3.read_text(encoding="utf-8-sig").splitlines()
            if corrupcion == "ENCABEZADO":
                lineas[0] = "seq;timestamp;level;etiqueta;event_code;message"
            elif corrupcion == "FILA_CINCO_COLUMNAS":
                lineas.append("999;2026-09-08 11:45:07;L3;EVENTO;INICIO")
            elif corrupcion == "FILA_SIETE_COLUMNAS":
                lineas.append("999;2026-09-08 11:45:07;L3;EVENTO;INICIO;Aviso;columna_extra")
            else:
                lineas.append("999;2026-09-08 11:45:07;L3;EVENTO;CODIGO_DESCONOCIDO;Aviso")
            ruta_l3.write_text("\n".join(lineas) + "\n", encoding="utf-8-sig", newline="")
            evidencia_cerrada.update({ruta: ruta.read_bytes() for ruta in rutas_conjunto.values()})
            return generar_real(rutas_conjunto, directorio_copia)

        monkeypatch.setattr(sesion, "generar_acta_y_copiar_conjunto", generar_con_fuente_corrupta)

        respuesta = await cliente.delete("/api/v1/sesion")

        assert respuesta.status_code == 200
        assert respuesta.json() == {"acta_generada": False, "copia_externa": "OMITIDA"}
        estado = obtener_recursos_aplicacion(aplicacion).estado_operativo
        assert estado.estado_global is EstadoGlobal.SIN_PREPARAR
        assert estado.sesion_activa is None

    assert evidencia_cerrada
    for ruta, contenido in evidencia_cerrada.items():
        assert ruta.read_bytes() == contenido
        assert ruta.exists()
    assert "SESION_CERRADA" in rutas[NivelAuditoria.L3].read_text(encoding="utf-8-sig")
    assert not ruta_acta_de_conjunto(rutas[NivelAuditoria.L3]).exists()
    assert list(destino.iterdir()) == []


# ---------------------------------------------------------------------------
# 3. Cobertura del catálogo frente a los productores reales
# ---------------------------------------------------------------------------

MODULOS_DE_SERVICIO = (
    apoyo_tecnico,
    entrada,
    finalizacion_votacion,
    palabra,
    preparacion,
    remapeo,
    sesion,
    votacion,
)


class ResolutorDeConstantes:
    """Resuelve a qué cadenas puede corresponder un argumento de ``registrar_evento``.

    Los servicios pasan la etiqueta y el código de tres formas distintas:

    1. una cadena literal (``"REMAPEO"``);
    2. una constante de módulo (``ETIQUETA_VOTACION``);
    3. una variable local asignada con una expresión condicional entre dos
       constantes (``codigo = A if condicion else B``);
    4. un parámetro de una función auxiliar del mismo módulo, que los llamadores
       completan con constantes.

    El resolutor cubre esas cuatro formas. Si aparece una quinta, devuelve un
    conjunto vacío y el test falla: preferimos exigir que el código siga siendo
    analizable antes que dejar de comprobar la cobertura del catálogo.
    """

    def __init__(self, arbol: ast.Module) -> None:
        self._arbol = arbol
        self._constantes = self._recolectar_constantes_de_modulo()

    def _recolectar_constantes_de_modulo(self) -> dict[str, str]:
        """Indexa las asignaciones ``NOMBRE = "texto"`` del nivel superior."""

        constantes: dict[str, str] = {}
        for nodo in self._arbol.body:
            if not isinstance(nodo, ast.Assign):
                continue
            if not isinstance(nodo.value, ast.Constant) or not isinstance(nodo.value.value, str):
                continue
            for destino in nodo.targets:
                if isinstance(destino, ast.Name):
                    constantes[destino.id] = nodo.value.value
        return constantes

    def resolver(self, expresion: ast.expr, funcion: ast.AST | None) -> set[str]:
        """Devuelve todos los valores textuales posibles de una expresión."""

        if isinstance(expresion, ast.Constant) and isinstance(expresion.value, str):
            return {expresion.value}
        if isinstance(expresion, ast.IfExp):
            return self.resolver(expresion.body, funcion) | self.resolver(expresion.orelse, funcion)
        if isinstance(expresion, ast.Name):
            if expresion.id in self._constantes:
                return {self._constantes[expresion.id]}
            return self._resolver_nombre_local(expresion.id, funcion)
        return set()

    def _resolver_nombre_local(self, nombre: str, funcion: ast.AST | None) -> set[str]:
        """Resuelve una variable local o un parámetro de la función que la usa."""

        if funcion is None:
            return set()

        valores: set[str] = set()
        for nodo in ast.walk(funcion):
            if isinstance(nodo, ast.Assign) and any(
                isinstance(destino, ast.Name) and destino.id == nombre for destino in nodo.targets
            ):
                valores |= self.resolver(nodo.value, funcion)

        if valores:
            return valores
        return self._resolver_parametro(nombre, funcion)

    def _resolver_parametro(self, nombre: str, funcion: ast.AST) -> set[str]:
        """Busca con qué constantes llaman los demás al parámetro ``nombre``."""

        if not isinstance(funcion, ast.FunctionDef | ast.AsyncFunctionDef):
            return set()
        parametros = [argumento.arg for argumento in funcion.args.args]
        if nombre not in parametros:
            return set()
        posicion = parametros.index(nombre)

        valores: set[str] = set()
        for nodo, contenedor in self._llamadas_con_contexto():
            if _nombre_de_llamada(nodo) != funcion.name:
                continue
            # ``self``/``cls`` no viajan como argumento explícito en una llamada
            # por atributo, así que la posición se corrige cuando corresponde.
            argumentos = list(nodo.args)
            desplazamiento = posicion - (
                1 if parametros and parametros[0] in ("self", "cls") else 0
            )
            if 0 <= desplazamiento < len(argumentos):
                valores |= self.resolver(argumentos[desplazamiento], contenedor)
            for palabra_clave in nodo.keywords:
                if palabra_clave.arg == nombre:
                    valores |= self.resolver(palabra_clave.value, contenedor)
        return valores

    def _llamadas_con_contexto(self) -> Iterator[tuple[ast.Call, ast.AST | None]]:
        """Recorre todas las llamadas del módulo junto con la función que las contiene."""

        yield from _llamadas_de(self._arbol)


def _nombre_de_llamada(nodo: ast.Call) -> str:
    """Devuelve el nombre invocado, sea ``f(...)`` u ``objeto.f(...)``."""

    funcion = nodo.func
    if isinstance(funcion, ast.Attribute):
        return funcion.attr
    if isinstance(funcion, ast.Name):
        return funcion.id
    return ""


def _llamadas_de(
    nodo: ast.AST,
    funcion: ast.AST | None = None,
) -> Iterator[tuple[ast.Call, ast.AST | None]]:
    """Recorre el árbol llevando la función que contiene cada llamada."""

    for hijo in ast.iter_child_nodes(nodo):
        contenedor = hijo if isinstance(hijo, ast.FunctionDef | ast.AsyncFunctionDef) else funcion
        if isinstance(hijo, ast.Call):
            yield hijo, funcion
        yield from _llamadas_de(hijo, contenedor)


def familias_l3_declaradas_en_el_codigo() -> set[tuple[str, str]]:
    """Extrae del código fuente cada familia ``(tag, event_code)`` que se registra en L3."""

    familias: set[tuple[str, str]] = set()
    for modulo in MODULOS_DE_SERVICIO:
        ruta = Path(modulo.__file__ or "")
        arbol = ast.parse(ruta.read_text(encoding="utf-8"))
        resolutor = ResolutorDeConstantes(arbol)
        for llamada, contenedor in _llamadas_de(arbol):
            if _nombre_de_llamada(llamada) != "registrar_evento" or len(llamada.args) < 4:
                continue
            nivel = llamada.args[0]
            if not (isinstance(nivel, ast.Attribute) and nivel.attr == "L3"):
                continue
            etiquetas = resolutor.resolver(llamada.args[1], contenedor)
            codigos = resolutor.resolver(llamada.args[2], contenedor)
            assert etiquetas, (
                f"{ruta.name}:{llamada.lineno}: no se pudo determinar la etiqueta L3. "
                "El catálogo del acta necesita que estos argumentos sean analizables."
            )
            assert codigos, (
                f"{ruta.name}:{llamada.lineno}: no se pudo determinar el event_code L3. "
                "El catálogo del acta necesita que estos argumentos sean analizables."
            )
            familias |= {(etiqueta, codigo) for etiqueta in etiquetas for codigo in codigos}
    return familias


def test_el_catalogo_cubre_todas_las_familias_l3_que_produce_el_backend() -> None:
    """Ningún productor L3 puede quedar sin política de redacción sin romper CI.

    Este test es la red que impide la regresión estructural: si mañana un WP
    agrega un ``registrar_evento(NivelAuditoria.L3, ...)`` nuevo y olvida
    declarar cómo se redacta en el acta, falla acá y no en una sesión real.
    """

    familias = familias_l3_declaradas_en_el_codigo()

    # El remapeo se registra con literales y también debe estar contemplado.
    assert ("REMAPEO", "REMAPEO_AUTORIZADO") in familias
    assert len(familias) >= 20

    sin_politica = sorted(familia for familia in familias if familia not in POLITICAS_ACTA)
    assert not sin_politica, (
        "Estas familias L3 se registran pero no tienen redacción de acta declarada "
        f"en POLITICAS_ACTA: {sin_politica}"
    )


def test_el_catalogo_no_declara_familias_que_ya_nadie_produce() -> None:
    """Una política huérfana indica que el catálogo quedó desactualizado."""

    familias = familias_l3_declaradas_en_el_codigo()
    huerfanas = sorted(familia for familia in POLITICAS_ACTA if familia not in familias)

    assert not huerfanas, f"POLITICAS_ACTA declara familias que ya no se registran: {huerfanas}"


def test_las_constantes_del_catalogo_coinciden_con_las_de_cada_servicio() -> None:
    """El catálogo repite las cadenas por evitar un ciclo de importación.

    Esa repetición sólo es segura si algo comprueba que sigan siendo idénticas.
    Eso es exactamente lo que hace este test.
    """

    equivalencias = (
        (politica_acta.ETIQUETA_PREPARACION, preparacion.ETIQUETA_PREPARACION),
        (politica_acta.CODIGO_PREPARACION_INICIADA, preparacion.CODIGO_PREPARACION_INICIADA),
        (politica_acta.CODIGO_PREPARACION_CANCELADA, preparacion.CODIGO_PREPARACION_CANCELADA),
        (politica_acta.ETIQUETA_SESION, sesion.ETIQUETA_SESION),
        (politica_acta.CODIGO_SESION_ABIERTA, sesion.CODIGO_SESION_ABIERTA),
        (politica_acta.CODIGO_SESION_CERRADA, sesion.CODIGO_SESION_CERRADA),
        (
            politica_acta.CODIGO_NUMERO_SESION_ACTUALIZADO,
            sesion.CODIGO_NUMERO_SESION_ACTUALIZADO,
        ),
        (politica_acta.CODIGO_PRESIDENCIA_ACTUALIZADA, sesion.CODIGO_PRESIDENCIA_ACTUALIZADA),
        (
            politica_acta.CODIGO_SECRETARIA_LEGISLATIVA_ACTUALIZADA,
            sesion.CODIGO_SECRETARIA_LEGISLATIVA_ACTUALIZADA,
        ),
        (politica_acta.ETIQUETA_PRESENCIA, entrada.ETIQUETA_PRESENCIA),
        (politica_acta.CODIGO_CONCEJAL_PRESENTE, entrada.CODIGO_CONCEJAL_PRESENTE),
        (politica_acta.CODIGO_CONCEJAL_AUSENTE, entrada.CODIGO_CONCEJAL_AUSENTE),
        (politica_acta.ETIQUETA_PALABRA, entrada.ETIQUETA_PALABRA),
        (politica_acta.ETIQUETA_PALABRA, palabra.ETIQUETA_PALABRA),
        (
            politica_acta.CODIGO_PEDIDO_PALABRA_REGISTRADO,
            entrada.CODIGO_PEDIDO_PALABRA_REGISTRADO,
        ),
        (politica_acta.CODIGO_PEDIDO_PALABRA_RETIRADO, entrada.CODIGO_PEDIDO_PALABRA_RETIRADO),
        (politica_acta.CODIGO_USO_PALABRA_FINALIZADO, entrada.CODIGO_USO_PALABRA_FINALIZADO),
        (politica_acta.CODIGO_USO_PALABRA_FINALIZADO, palabra.CODIGO_USO_PALABRA_FINALIZADO),
        (politica_acta.CODIGO_USO_PALABRA_OTORGADO, palabra.CODIGO_USO_PALABRA_OTORGADO),
        (politica_acta.ETIQUETA_VOTACION, votacion.ETIQUETA_VOTACION),
        (politica_acta.ETIQUETA_VOTACION, entrada.ETIQUETA_VOTACION),
        (politica_acta.ETIQUETA_VOTACION, finalizacion_votacion.ETIQUETA_VOTACION),
        (politica_acta.CODIGO_VOTACION_ABIERTA, votacion.CODIGO_VOTACION_ABIERTA),
        (
            politica_acta.CODIGO_VOTO_ORDINARIO_REGISTRADO,
            entrada.CODIGO_VOTO_ORDINARIO_REGISTRADO,
        ),
        (
            politica_acta.CODIGO_VOTACION_CERRADA_COMPLETITUD,
            entrada.CODIGO_VOTACION_CERRADA_COMPLETITUD,
        ),
        (
            politica_acta.CODIGO_VOTACION_RESULTADO_FINAL,
            entrada.CODIGO_VOTACION_RESULTADO_FINAL,
        ),
        (
            politica_acta.CODIGO_VOTACION_RESULTADO_EMPATE,
            entrada.CODIGO_VOTACION_RESULTADO_EMPATE,
        ),
        (
            politica_acta.CODIGO_VOTACION_FINALIZADA_INCONCLUSA,
            finalizacion_votacion.CODIGO_VOTACION_FINALIZADA_INCONCLUSA,
        ),
        (
            politica_acta.CODIGO_VOTO_DESEMPATE_PRESIDENCIAL,
            votacion.CODIGO_VOTO_DESEMPATE_PRESIDENCIAL,
        ),
        (
            politica_acta.CODIGO_VOTACION_RESULTADO_DESEMPATE,
            votacion.CODIGO_VOTACION_RESULTADO_DESEMPATE,
        ),
        (politica_acta.ETIQUETA_EVENTO_PRINCIPAL, apoyo_tecnico.ETIQUETA_EVENTO_PRINCIPAL),
        (politica_acta.CODIGO_MARCADOR_INICIO, apoyo_tecnico.CODIGO_MARCADOR_INICIO),
        (politica_acta.CODIGO_MARCADOR_FIN, apoyo_tecnico.CODIGO_MARCADOR_FIN),
    )
    for del_catalogo, del_servicio in equivalencias:
        assert del_catalogo == del_servicio
