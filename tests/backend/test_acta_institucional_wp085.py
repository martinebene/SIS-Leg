"""Pruebas del informe de acta y de la copia externa opcional (WP-085).

Qué demuestra cada bloque:

1. **Derivación del acta.** El informe se arma leyendo el archivo L3 ya cerrado,
   así que contiene todos los eventos aunque superen ampliamente los 200 que
   caben en el buffer en memoria del escritor. También se comprueba el
   encabezado exacto aprobado, el formato de línea, la redacción de los
   marcadores ``INICIO``/``FIN`` y la ausencia de metadatos técnicos y emojis.
2. **Copia externa.** Los cuatro archivos se replican byte a byte en la carpeta
   de fecha del destino; una colisión o un destino imposible se informan como
   falla sin tocar los archivos locales.
3. **No contaminación del cierre.** Un fallo del informe o de la copia nunca
   convierte un cierre institucional durable en un error: la sesión queda
   cerrada, el estado vuelve a ``SIN_PREPARAR`` y la respuesta HTTP sigue siendo
   200 con el detalle del problema en el cuerpo.
"""

from __future__ import annotations

import csv
import hashlib
from collections.abc import AsyncGenerator
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
from sis_leg_backend.auditoria import EscritorAuditoriaCsv, NivelAuditoria
from sis_leg_backend.dominio.estado import EstadoGlobal
from sis_leg_backend.recursos import obtener_recursos_aplicacion
from sis_leg_backend.servicios.acta_institucional import (
    EstadoCopiaExterna,
    componer_acta,
    generar_acta_y_copiar_conjunto,
    ruta_acta_de_conjunto,
)
from sis_leg_backend.servicios.apoyo_tecnico import (
    CODIGO_MARCADOR_FIN,
    CODIGO_MARCADOR_INICIO,
    ETIQUETA_EVENTO_PRINCIPAL,
)

pytestmark = pytest.mark.anyio

# Marca nominal del conjunto de prueba. Se fija para poder afirmar el encabezado
# y las horas exactas sin depender del reloj de la máquina que corre las pruebas.
INICIO_CONJUNTO = datetime(2026, 9, 8, 10, 30, 0)
HORA_EVENTOS = datetime(2026, 9, 8, 11, 45, 7)

ENCABEZADO_ESPERADO = [
    "SIS-Leg",
    "Registro de eventos para acta institucional",
    "Fecha: 08/09/2026",
    "",
]


def crear_escritor(directorio: Path) -> EscritorAuditoriaCsv:
    """Crea un conjunto real con relojes fijos para afirmar nombres y horas."""

    return EscritorAuditoriaCsv(
        directorio,
        INICIO_CONJUNTO,
        reloj=lambda: HORA_EVENTOS,
    )


def leer_acta(ruta_acta: Path) -> list[str]:
    """Devuelve las líneas del informe leyéndolo como UTF-8 estricto.

    Se abre con ``encoding="utf-8"`` (no ``utf-8-sig``) a propósito: si el
    archivo llevara BOM, el primer carácter aparecería como ``﻿`` y la
    comparación del encabezado fallaría.
    """

    return ruta_acta.read_text(encoding="utf-8").splitlines()


def sha256_de(ruta: Path) -> str:
    """Huella del contenido de un archivo, para comparar original y copia."""

    return hashlib.sha256(ruta.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# 1. Derivación del informe de acta
# ---------------------------------------------------------------------------


def test_acta_incluye_todos_los_eventos_aunque_superen_el_buffer_en_memoria(
    tmp_path: Path,
) -> None:
    """Con 250 eventos L3 el informe los trae todos, no los últimos 200.

    Esta es la prueba que distingue la fuente correcta de la incorrecta: el
    buffer ``eventos_recientes`` del escritor está acotado a 200 entradas por
    construcción, así que un informe derivado de él perdería silenciosamente los
    primeros 50 eventos de esta sesión.
    """

    escritor = crear_escritor(tmp_path / "logs")
    for numero in range(1, 251):
        escritor.registrar_evento(
            NivelAuditoria.L3,
            ETIQUETA_EVENTO_PRINCIPAL,
            CODIGO_MARCADOR_INICIO,
            f"Aviso numero {numero}",
        )
    ruta_l3 = escritor.rutas[NivelAuditoria.L3]
    escritor.cerrar()

    # El buffer en memoria efectivamente perdió los primeros eventos.
    assert len(escritor.eventos_recientes) == 200
    assert escritor.eventos_recientes[0].mensaje == "Aviso numero 51"

    lineas = componer_acta(ruta_l3).splitlines()

    assert lineas[:4] == ENCABEZADO_ESPERADO
    cuerpo = lineas[4:]
    assert len(cuerpo) == 250
    assert cuerpo[0] == "11:45:07 — Inicio: Aviso numero 1"
    assert cuerpo[-1] == "11:45:07 — Inicio: Aviso numero 250"


def test_marcadores_inicio_y_fin_se_distinguen_formalmente(tmp_path: Path) -> None:
    """``EVENTO/INICIO`` y ``EVENTO/FIN`` comparten texto y deben diferenciarse.

    Los marcadores de WP-078 registran exactamente el texto del aviso, sin
    prefijos. En el CSV los distingue la columna ``event_code``, que el acta no
    imprime; sin la redacción formal, el informe mostraría dos líneas idénticas.
    """

    escritor = crear_escritor(tmp_path / "logs")
    escritor.registrar_evento(
        NivelAuditoria.L3,
        ETIQUETA_EVENTO_PRINCIPAL,
        CODIGO_MARCADOR_INICIO,
        "Cuarto intermedio",
    )
    escritor.registrar_evento(
        NivelAuditoria.L3,
        ETIQUETA_EVENTO_PRINCIPAL,
        CODIGO_MARCADOR_FIN,
        "Cuarto intermedio",
    )
    ruta_l3 = escritor.rutas[NivelAuditoria.L3]
    escritor.cerrar()

    cuerpo = componer_acta(ruta_l3).splitlines()[4:]

    assert cuerpo == [
        "11:45:07 — Inicio: Cuarto intermedio",
        "11:45:07 — Fin: Cuarto intermedio",
    ]


def test_acta_no_publica_metadatos_tecnicos_ni_emojis(tmp_path: Path) -> None:
    """El informe transporta hora y texto humano, nada más.

    El emoji llega al CSV porque el operador puede escribirlo en un aviso
    técnico. El CSV lo conserva como evidencia; el acta institucional se redacta
    en texto llano, así que el pictograma se omite y el espacio doble que deja se
    colapsa.
    """

    escritor = crear_escritor(tmp_path / "logs")
    escritor.registrar_evento(
        NivelAuditoria.L3,
        ETIQUETA_EVENTO_PRINCIPAL,
        CODIGO_MARCADOR_INICIO,
        "Se reanuda la sesion 🎉 en cinco minutos",
    )
    ruta_l3 = escritor.rutas[NivelAuditoria.L3]
    escritor.cerrar()

    texto = componer_acta(ruta_l3)
    cuerpo = texto.splitlines()[4:]

    assert cuerpo == ["11:45:07 — Inicio: Se reanuda la sesion en cinco minutos"]
    # Ninguna columna técnica del CSV aparece en el informe.
    for metadato in ("L3", "EVENTO", "INICIO:", ";"):
        assert metadato not in texto


def test_acta_se_guarda_en_utf8_sin_bom_junto_a_los_csv(tmp_path: Path) -> None:
    """Nombre, ubicación y codificación del archivo generado.

    Los CSV institucionales llevan BOM porque su contrato lo exige (DT-012); el
    informe no es un CSV y se guarda como texto UTF-8 llano, que es lo que
    esperan los procesadores de texto donde se pega el acta.
    """

    escritor = crear_escritor(tmp_path / "logs")
    escritor.registrar_evento(NivelAuditoria.L3, "SESION", "SESION_CERRADA", "Cierre de sesión Nº7")
    rutas = dict(escritor.rutas)
    escritor.cerrar()

    resultado = generar_acta_y_copiar_conjunto(rutas, None)

    assert resultado.acta_generada is True
    assert resultado.copia_externa is EstadoCopiaExterna.OMITIDA
    ruta_acta = rutas[NivelAuditoria.L3].with_name("2026-09-08_10-30-00-ACTA.txt")
    assert resultado.ruta_acta == ruta_acta
    assert ruta_acta.parent == rutas[NivelAuditoria.L3].parent
    crudo = ruta_acta.read_bytes()
    assert not crudo.startswith(b"\xef\xbb\xbf")
    assert crudo.decode("utf-8").endswith("11:45:07 — Cierre de sesión Nº7\n")


def test_acta_conserva_texto_con_punto_y_coma_y_saltos_de_linea(tmp_path: Path) -> None:
    """El informe se recompone con el mismo dialecto CSV con que se escribió.

    Un mensaje que contiene el delimitador ``;`` queda entrecomillado en el CSV.
    Leerlo con ``csv.reader`` lo devuelve entero; partir la línea a mano lo
    rompería en dos columnas inventadas.
    """

    escritor = crear_escritor(tmp_path / "logs")
    escritor.registrar_evento(
        NivelAuditoria.L3,
        "SESION",
        "PRESIDENCIA_ACTUALIZADA",
        "Presidencia actualizado: sin informar -> Ana; Beatriz",
    )
    ruta_l3 = escritor.rutas[NivelAuditoria.L3]
    escritor.cerrar()

    cuerpo = componer_acta(ruta_l3).splitlines()[4:]

    assert cuerpo == ["11:45:07 — Presidencia actualizado: sin informar -> Ana; Beatriz"]


# ---------------------------------------------------------------------------
# 2. Copia externa opcional
# ---------------------------------------------------------------------------


def test_copia_externa_replica_los_cuatro_archivos_sin_tocar_los_locales(
    tmp_path: Path,
) -> None:
    """Con destino configurado quedan L1, L2, L3 y ACTA idénticos en la copia."""

    escritor = crear_escritor(tmp_path / "logs")
    escritor.registrar_evento(NivelAuditoria.L3, "SESION", "SESION_CERRADA", "Cierre de sesión Nº7")
    rutas = dict(escritor.rutas)
    escritor.cerrar()
    destino = tmp_path / "copia"
    destino.mkdir()

    resultado = generar_acta_y_copiar_conjunto(rutas, str(destino))

    assert resultado.copia_externa is EstadoCopiaExterna.EXITOSA
    assert resultado.ruta_acta is not None
    originales = [*rutas.values(), resultado.ruta_acta]
    # La carpeta de fecha del destino repite exactamente la del conjunto local.
    carpeta_copia = destino / "2026-09-08"
    assert sorted(ruta.name for ruta in carpeta_copia.iterdir()) == sorted(
        ruta.name for ruta in originales
    )
    for original in originales:
        assert original.exists()
        assert sha256_de(carpeta_copia / original.name) == sha256_de(original)


def test_copia_externa_falla_ante_colision_sin_pisar_ni_dejar_conjunto_parcial(
    tmp_path: Path,
) -> None:
    """Un nombre ya ocupado en el destino es una falla de copia, no un reemplazo.

    Se comprueban las dos mitades de la garantía: el archivo ajeno conserva su
    contenido y los archivos que este intento sí alcanzó a crear se eliminan,
    para que en el destino no quede un conjunto incompleto con apariencia de
    completo.
    """

    escritor = crear_escritor(tmp_path / "logs")
    escritor.registrar_evento(NivelAuditoria.L3, "SESION", "SESION_CERRADA", "Cierre de sesión Nº7")
    rutas = dict(escritor.rutas)
    escritor.cerrar()
    carpeta_copia = tmp_path / "copia" / "2026-09-08"
    carpeta_copia.mkdir(parents=True)
    # El conjunto se copia en orden L1, L2, L3, ACTA: ocupar el nombre del L3
    # obliga a revertir dos archivos ya creados.
    ocupado = carpeta_copia / rutas[NivelAuditoria.L3].name
    ocupado.write_text("conjunto historico ajeno", encoding="utf-8")

    resultado = generar_acta_y_copiar_conjunto(rutas, str(tmp_path / "copia"))

    assert resultado.acta_generada is True
    assert resultado.copia_externa is EstadoCopiaExterna.FALLIDA
    assert ocupado.read_text(encoding="utf-8") == "conjunto historico ajeno"
    assert list(carpeta_copia.iterdir()) == [ocupado]
    # Los archivos locales, incluido el informe recién generado, siguen intactos.
    assert resultado.ruta_acta is not None
    for ruta in (*rutas.values(), resultado.ruta_acta):
        assert ruta.exists()


def test_copia_externa_falla_ante_destino_imposible(tmp_path: Path) -> None:
    """Una ruta que no puede ser directorio se informa como copia fallida.

    Es el escenario realista del recurso de red desmontado o mal escrito: acá se
    reproduce con un archivo común ocupando el lugar del directorio de destino.
    """

    escritor = crear_escritor(tmp_path / "logs")
    escritor.registrar_evento(NivelAuditoria.L3, "SESION", "SESION_CERRADA", "Cierre de sesión Nº7")
    rutas = dict(escritor.rutas)
    escritor.cerrar()
    destino = tmp_path / "no-es-un-directorio"
    destino.write_text("archivo comun", encoding="utf-8")

    resultado = generar_acta_y_copiar_conjunto(rutas, str(destino))

    assert resultado.acta_generada is True
    assert resultado.copia_externa is EstadoCopiaExterna.FALLIDA
    assert destino.read_text(encoding="utf-8") == "archivo comun"
    for ruta in rutas.values():
        assert ruta.exists()


def test_sin_directorio_configurado_no_se_crea_nada_fuera_del_directorio_local(
    tmp_path: Path,
) -> None:
    """Ausencia de ``logs_copy_dir`` significa cero acceso externo."""

    escritor = crear_escritor(tmp_path / "logs")
    escritor.registrar_evento(NivelAuditoria.L3, "SESION", "SESION_CERRADA", "Cierre de sesión Nº7")
    rutas = dict(escritor.rutas)
    escritor.cerrar()

    resultado = generar_acta_y_copiar_conjunto(rutas, None)

    assert resultado.copia_externa is EstadoCopiaExterna.OMITIDA
    # El único directorio creado sigue siendo el de registros locales.
    assert sorted(hijo.name for hijo in tmp_path.iterdir()) == ["logs"]


def test_fallo_al_generar_el_acta_no_intenta_la_copia(tmp_path: Path) -> None:
    """Sin informe no hay conjunto completo, así que no se replica nada.

    El fallo se provoca ocupando de antemano el nombre del informe: el escritor
    usa creación exclusiva y no puede sobrescribir un archivo existente.
    """

    escritor = crear_escritor(tmp_path / "logs")
    escritor.registrar_evento(NivelAuditoria.L3, "SESION", "SESION_CERRADA", "Cierre de sesión Nº7")
    rutas = dict(escritor.rutas)
    escritor.cerrar()
    ruta_acta = ruta_acta_de_conjunto(rutas[NivelAuditoria.L3])
    ruta_acta.write_text("informe previo", encoding="utf-8")
    destino = tmp_path / "copia"
    destino.mkdir()

    resultado = generar_acta_y_copiar_conjunto(rutas, str(destino))

    assert resultado.acta_generada is False
    assert resultado.ruta_acta is None
    assert resultado.copia_externa is EstadoCopiaExterna.OMITIDA
    assert ruta_acta.read_text(encoding="utf-8") == "informe previo"
    assert list(destino.iterdir()) == []


# ---------------------------------------------------------------------------
# 3. Integración con el cierre de sesión por HTTP
# ---------------------------------------------------------------------------


def preparar_archivos_canonicos(directorio: Path, *, directorio_copia: Path | None) -> None:
    """Escribe configuración y padrón ficticios para una aplicación aislada.

    ``directorio_copia`` se traduce a la clave opcional ``paths.logs_copy_dir``:
    ``None`` deja el archivo exactamente como antes de este WP.
    """

    carpeta = directorio / "config"
    carpeta.mkdir(parents=True, exist_ok=True)
    linea_paths = f'logs_dir = "{directorio / "logs"}"'
    if directorio_copia is not None:
        linea_paths += f'\nlogs_copy_dir = "{directorio_copia}"'
    contenido = TOML_CANONICO.replace(LINEA_LOGS, linea_paths).replace(LINEA_QUORUM, "quorum = 1")
    escribir_system_toml(carpeta / "system.toml", contenido)
    escribir_padron(carpeta / "concejales.csv", filas_padron_valido())


@asynccontextmanager
async def cliente_de_prueba(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    directorio_copia: Path | None = None,
) -> AsyncGenerator[tuple[AsyncClient, FastAPI]]:
    """Entrega cliente y aplicación con lifespan y archivos canónicos reales."""

    preparar_archivos_canonicos(tmp_path, directorio_copia=directorio_copia)
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()
    async with aplicacion.router.lifespan_context(aplicacion):
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            yield cliente, aplicacion


async def preparar_y_abrir(cliente: AsyncClient) -> None:
    """Completa las precondiciones mínimas y abre una sesión válida."""

    assert (await cliente.post("/api/v1/preparacion")).status_code == 204
    assert (
        await cliente.post(
            "/api/v1/entradas/tecla",
            json={"dispositivo": "D-01", "tecla": "9"},
        )
    ).status_code == 200
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


def rutas_del_conjunto_activo(aplicacion: FastAPI) -> dict[NivelAuditoria, Path]:
    """Copia las rutas del conjunto abierto antes de que el cierre las suelte."""

    estado = obtener_recursos_aplicacion(aplicacion).estado_operativo
    contexto = estado.contexto_operativo_activo()
    assert contexto is not None
    return dict(contexto.escritor_auditoria.rutas)


async def test_cierre_genera_el_acta_y_replica_el_conjunto_configurado(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Camino completo: cerrar deja cuatro archivos locales y cuatro copiados."""

    destino = tmp_path / "copia-externa"
    destino.mkdir()
    async with cliente_de_prueba(tmp_path, monkeypatch, directorio_copia=destino) as (
        cliente,
        aplicacion,
    ):
        await preparar_y_abrir(cliente)
        rutas = rutas_del_conjunto_activo(aplicacion)

        respuesta = await cliente.delete("/api/v1/sesion")

        assert respuesta.status_code == 200
        assert respuesta.json() == {"acta_generada": True, "copia_externa": "EXITOSA"}
        estado = obtener_recursos_aplicacion(aplicacion).estado_operativo
        assert estado.estado_global is EstadoGlobal.SIN_PREPARAR

        ruta_acta = ruta_acta_de_conjunto(rutas[NivelAuditoria.L3])
        assert ruta_acta.exists()
        # El informe termina con el mismo cierre que cerró el CSV.
        assert leer_acta(ruta_acta)[-1].endswith("Cierre de sesión Nº59")

        carpeta_copia = destino / rutas[NivelAuditoria.L3].parent.name
        for original in (*rutas.values(), ruta_acta):
            assert sha256_de(carpeta_copia / original.name) == sha256_de(original)


async def test_copia_fallida_no_convierte_el_cierre_en_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un destino externo inaccesible informa el problema sin romper el cierre."""

    destino = tmp_path / "destino-imposible"
    destino.write_text("no es un directorio", encoding="utf-8")
    async with cliente_de_prueba(tmp_path, monkeypatch, directorio_copia=destino) as (
        cliente,
        aplicacion,
    ):
        await preparar_y_abrir(cliente)
        rutas = rutas_del_conjunto_activo(aplicacion)

        respuesta = await cliente.delete("/api/v1/sesion")

        assert respuesta.status_code == 200
        assert respuesta.json() == {"acta_generada": True, "copia_externa": "FALLIDA"}
        estado = obtener_recursos_aplicacion(aplicacion).estado_operativo
        assert estado.estado_global is EstadoGlobal.SIN_PREPARAR
        assert estado.sesion_activa is None
        # El registro institucional local está completo y cerrado.
        with rutas[NivelAuditoria.L1].open(encoding="utf-8-sig", newline="") as archivo:
            filas = list(csv.reader(archivo, delimiter=";"))
        assert filas[-1][4] == "SESION_CERRADA"
        assert ruta_acta_de_conjunto(rutas[NivelAuditoria.L3]).exists()


async def test_fallo_del_acta_no_deja_la_sesion_atrapada(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin informe la sesión igual cierra: el CSV ya era durable.

    Es el escenario que el WP prohíbe explícitamente: quedar en
    ``SESION_ABIERTA`` con el escritor cerrado dejaría al sistema sin poder
    auditar nada y empujaría al operador a repetir un cierre ya consumado.
    """

    async with cliente_de_prueba(tmp_path, monkeypatch) as (cliente, aplicacion):
        await preparar_y_abrir(cliente)
        rutas = rutas_del_conjunto_activo(aplicacion)
        # Ocupar el nombre del informe hace fallar su creación exclusiva.
        ruta_acta = ruta_acta_de_conjunto(rutas[NivelAuditoria.L3])
        ruta_acta.write_text("informe previo", encoding="utf-8")

        respuesta = await cliente.delete("/api/v1/sesion")

        assert respuesta.status_code == 200
        assert respuesta.json() == {"acta_generada": False, "copia_externa": "OMITIDA"}
        estado = obtener_recursos_aplicacion(aplicacion).estado_operativo
        assert estado.estado_global is EstadoGlobal.SIN_PREPARAR
        assert estado.sesion_activa is None
        assert estado.archivos_auditoria_activos == ()
        # Una preparación nueva vuelve a ser posible inmediatamente.
        assert (await cliente.post("/api/v1/preparacion")).status_code == 204
