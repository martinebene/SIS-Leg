"""El acta debe poder representar todo texto humano que SIS-Leg acepta (WP-107).

Qué problema documenta esta suite
---------------------------------

El acta institucional (``...-ACTA.txt``) se deriva del L3 ya cerrado traduciendo
cada familia ``(tag, event_code)`` con el catálogo de
:mod:`sis_leg_backend.servicios.politica_acta`. Ese catálogo usa expresiones
regulares ancladas al mensaje completo, y eso es deliberado: impide que un campo
técnico agregado por un WP futuro se publique sin revisión.

El problema que corrige WP-107 es otro. Varios de esos mensajes transportan
**texto humano sin restricción de caracteres**: el ``tema`` y el ``tipo`` de una
votación, el motivo de una finalización manual, las autoridades, el nombre y el
apellido del padrón. La API y el padrón aceptan ahí saltos de línea, ``;``,
``=``, comillas y Unicode arbitrario, y el L3 los persiste correctamente. Sin
embargo el punto ``.`` de una expresión regular **no** coincide con un salto de
línea, así que un ``tema`` de dos renglones —forma habitual de un Orden del Día
real— convertía un L3 perfectamente válido en ``ErrorActaNoDerivable`` y el
cierre respondía ``acta_generada=false``.

La regla que fija WP-107 es por lo tanto asimétrica y hay que leerla así:

- **estricto con la estructura técnica**: encabezado canónico, seis columnas,
  ``level`` igual a ``L3``, timestamp con formato, familia con política
  declarada y forma técnica del mensaje. Nada de eso se relaja;
- **sin restricción con el contenido humano**: cualquier carácter que el sistema
  acepte y persista debe poder representarse en el acta.

Cómo está organizado el archivo
-------------------------------

1. **Regresión por API real.** Una sesión completa ejecutada por los endpoints
   productivos, con padrón, tipos de votación, autoridades, tema, motivo y aviso
   adversariales, cerrada con ``DELETE /api/v1/sesion``. Es la prueba que estaba
   roja antes de la corrección: exige HTTP 200, ``acta_generada=true`` y un acta
   legible. No se limita a probar helpers.
2. **Contrato textual por familia.** Cada familia L3 con texto humano variable
   se somete al catálogo con el corpus adversarial completo.
3. **Estrategia de presentación.** El acta es un informe de una línea por
   evento, así que los saltos de línea del texto humano se aplanan a un espacio.
   Acá se prueba esa decisión explícitamente, incluidas sus formas Unicode.
4. **Fallo cerrado conservado.** Admitir cualquier carácter humano no puede
   ablandar la detección de corrupción estructural real.

Cómo se demuestra que no se filtra metadata técnica
---------------------------------------------------

La suite WP-085 comprueba que ciertos tokens (``DNI=``, ``posicion=``,
``factor=``…) no aparezcan nunca en el acta. Acá esa comprobación **no sirve tal
cual**, porque el propio WP-107 exige que un operador pueda escribir esos
literales dentro de un tema o un motivo y que el acta los conserve.

Por eso la verificación se hace por *valor* y por *conteo*:

- ningún identificador realmente persistido (UUID de votación, DNI del padrón,
  huellas físicas, identificadores de dispositivo) puede aparecer;
- cada literal técnico presente en el acta debe aparecer **exactamente tantas
  veces** como lo escribió una persona. Una aparición de más significa que el
  catálogo copió metadata del mensaje técnico.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from conftest import (
    LINEA_LOGS,
    LINEA_QUORUM,
    LINEA_TYPES,
    TOML_CANONICO,
    escribir_padron,
    escribir_system_toml,
    filas_padron_valido,
)
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sis_leg_backend.aplicacion import crear_aplicacion
from sis_leg_backend.auditoria import NivelAuditoria
from sis_leg_backend.recursos import obtener_recursos_aplicacion
from sis_leg_backend.servicios.acta_institucional import (
    SEPARADOR_LINEA_ACTA,
    componer_acta,
    normalizar_texto_para_acta,
    ruta_acta_de_conjunto,
)
from sis_leg_backend.servicios.politica_acta import (
    ErrorActaNoDerivable,
    redactar_linea_de_acta,
)

pytestmark = pytest.mark.anyio

# ---------------------------------------------------------------------------
# Corpus adversarial
#
# Cada texto combina deliberadamente varias de las formas que el WP exige:
# saltos LF y CRLF, varias líneas, ``;``, ``=``, comillas simples y dobles,
# tildes, ``ñ``, Unicode general y fragmentos que imitan los delimitadores
# técnicos que el propio mensaje L3 usa internamente.
#
# Ninguno lleva espacios dobles ni espacios al principio o al final de una
# línea: el acta colapsa espacios repetidos (comportamiento previo a WP-107) y
# eso haría que la comparación literal de esta suite dejara de ser directa. La
# normalización de espacios se prueba aparte, en el bloque 3.
# ---------------------------------------------------------------------------

TEMA_ADVERSARIAL = (
    'Tema línea 1\nTema línea 2; artículo=3 "texto" — ñ/á; tipo_mayoria=SIMPLE; factor=0'
)
"""El caso exacto que pide el contrato del WP: dos renglones y una cola que imita
la gramática interna del mensaje ``VOTACION_ABIERTA``."""

TIPO_ADVERSARIAL = "Moción 'urgente'\r\nsobre expediente; banca=99"
"""El ``tipo`` sale de ``voting.types``, que la configuración acepta sin filtrar.
Lleva CRLF para probar que el conjunto CSV -> acta conserva ambos finales."""

TEMA_CRLF = "Primera línea\r\nSegunda línea\r\nTercera línea; causa=MANUAL"

MOTIVO_ADVERSARIAL = (
    'Se retira el "expediente";\ncausa=MANUAL; id=00000000-0000-0000-0000-000000000000; banca='
)

PRESIDENCIA_ADVERSARIAL = "Dra. Ñandú Peña\ny Lillo; banca=1; DNI=11111111"

SECRETARIA_ADVERSARIAL = "Sr. Ámbito 'Ç'; causa=; factor="

AVISO_ADVERSARIAL = 'Cuarto intermedio; tipo_mayoria=SIMPLE; factor=0 — "quince" minutos ñ/á'
"""Los avisos de recinto sí prohíben saltos de línea en la API (WP-078), así que
su caso adversarial explora el resto del corpus: ``;``, ``=`` y comillas."""

NOMBRE_ADVERSARIAL = 'Añá "Ñ"'
APELLIDO_ADVERSARIAL = "Pérez; banca=99"
APELLIDO_MULTILINEA = "Ortiz\ndel Valle"
DNI_CON_PUNTO_Y_COMA = "30000001;X"
"""El padrón sólo exige que el DNI no esté vacío: un ``;`` es texto aceptado y
persistido, y antes de WP-107 rompía el bloque de identidad de PALABRA."""

TEXTOS_HUMANOS_PUBLICABLES = (
    TEMA_ADVERSARIAL,
    TIPO_ADVERSARIAL,
    TEMA_CRLF,
    MOTIVO_ADVERSARIAL,
    PRESIDENCIA_ADVERSARIAL,
    SECRETARIA_ADVERSARIAL,
    AVISO_ADVERSARIAL,
    NOMBRE_ADVERSARIAL,
    APELLIDO_ADVERSARIAL,
    APELLIDO_MULTILINEA,
)
"""Texto humano del recorrido que el acta **sí** debe conservar.

El DNI queda deliberadamente afuera: es texto humano del padrón y el L3 lo
persiste, pero el acta no lo publica nunca. Que un DNI adversarial no rompa la
derivación y a la vez siga sin aparecer es justamente lo que prueba
``test_el_acta_adversarial_no_filtra_metadata_tecnica``.
"""

LITERALES_TECNICOS_VIGILADOS = (
    "DNI=",
    "; id=",
    "posicion=",
    "posicion_previa=",
    "posicion_origen=",
    "estado_previo=",
    "resultado_previo=",
    "resultado_nuevo=",
    "votos_conservados=",
    "quorum_requerido=",
    "presentes=",
    "tipo_mayoria=",
    "factor=",
    "base=",
    "denominador=",
    "cociente=",
    "causa=",
    "motivo_manual=",
    "banca=",
    "remapeo_id=",
    "fingerprint_anterior=",
    "fingerprint_candidato=",
    "dispositivo=",
    "persistencia=",
    "=true",
    "=false",
)
"""Claves que el catálogo nunca debe copiar desde el mensaje técnico.

No se exige que estén ausentes: el corpus adversarial las contiene a propósito.
Se exige que su cantidad en el acta coincida exactamente con la que aportó el
texto humano.
"""


def lineas_significativas(texto: str) -> list[str]:
    """Devuelve los renglones no vacíos de un texto humano, sin espacios exteriores.

    El acta aplana los saltos de línea a un espacio, de modo que cada renglón
    original tiene que seguir apareciendo literalmente dentro de la línea del
    evento. Comparar renglón por renglón demuestra que no se truncó ni se perdió
    contenido, sin reimplementar acá la normalización que se prueba en el
    bloque 3.
    """

    return [renglon.strip() for renglon in texto.splitlines() if renglon.strip()]


def exigir_texto_humano_representado(acta: str, texto: str) -> None:
    """Falla si algún renglón del texto humano no sobrevivió al acta."""

    for renglon in lineas_significativas(texto):
        assert renglon in acta, f"El acta perdió el texto humano {renglon!r}"


def acta_sin_texto_humano(acta: str, textos_humanos: tuple[str, ...]) -> str:
    """Borra del acta todo lo que escribió una persona y devuelve el resto.

    Contar apariciones no alcanzaría: un mismo texto humano puede publicarse en
    más de un evento (la Presidencia aparece al actualizarse y otra vez al
    desempatar), así que no existe un número esperado fijo.

    Sustraer es exacto: lo que queda después de quitar el texto humano es
    exclusivamente redacción del catálogo. Si ahí adentro aparece un literal
    técnico, la única explicación posible es que el catálogo lo copió del
    mensaje.

    Los textos se quitan del más largo al más corto para que uno que contenga a
    otro se borre entero antes de que el corto lo parta por la mitad. Se compara
    contra su forma depurada porque es la que efectivamente llega al acta.
    """

    residuo = acta
    for texto in sorted(textos_humanos, key=len, reverse=True):
        residuo = residuo.replace(normalizar_texto_para_acta(texto), " ")
    return residuo


def exigir_sin_fuga_de_metadata(acta: str, textos_humanos: tuple[str, ...]) -> None:
    """Exige que ningún literal técnico sobreviva fuera del texto humano."""

    residuo = acta_sin_texto_humano(acta, textos_humanos)
    for literal in LITERALES_TECNICOS_VIGILADOS:
        assert literal not in residuo, (
            f"La redacción del acta contiene el literal técnico {literal!r} "
            "fuera de todo texto escrito por una persona: el catálogo está "
            "copiando metadata del mensaje L3"
        )


# ---------------------------------------------------------------------------
# 1. Regresión por flujo API real
# ---------------------------------------------------------------------------


class BridgeAdversarial:
    """Bridge falso mínimo para alcanzar ``REMAPEO_AUTORIZADO`` sin hardware.

    Las huellas son reconocibles a propósito: después se afirma que ninguna de
    las dos llegó al acta aunque el resto del recorrido esté lleno de texto que
    se les parece.
    """

    FINGERPRINT_ANTERIOR = "lin|vendor=4242|product=4242|phys=usb-4|name=Anterior"
    FINGERPRINT_CANDIDATO = "lin|vendor=8484|product=8484|phys=usb-8|name=Candidato"

    def iniciar(self, remapeo_id: str, dispositivo: str) -> object:
        from sis_leg_backend.servicios.cliente_bridge import EstadoControlBridge

        return EstadoControlBridge(
            remapeo_id=remapeo_id,
            dispositivo=dispositivo,
            estado="CAPTURANDO",
            fingerprint_anterior=self.FINGERPRINT_ANTERIOR,
            candidato=None,
            diagnostico=None,
            persistencia=None,
            error=None,
        )

    def confirmar(self, remapeo_id: str, fingerprint: str, persistencia: str) -> object:
        from sis_leg_backend.servicios.cliente_bridge import EstadoControlBridge

        return EstadoControlBridge(
            remapeo_id=remapeo_id,
            dispositivo="dev01",
            estado="APLICADO",
            fingerprint_anterior=self.FINGERPRINT_ANTERIOR,
            candidato=fingerprint,
            diagnostico="Teclado sustituto",
            persistencia=persistencia,
            error=None,
        )


def preparar_archivos_adversariales(
    directorio: Path,
    *,
    tipos_extra: tuple[str, ...] = (TIPO_ADVERSARIAL,),
    ajustar_padron: Callable[[list[list[str]]], None] | None = None,
) -> list[str]:
    """Instala configuración y padrón con todo el texto humano del corpus.

    ``tipos_extra`` y ``ajustar_padron`` permiten que las regresiones de la
    iteración 2 inyecten sus propios valores de frontera sin duplicar todo el
    andamiaje: el resto del entorno es exactamente el mismo.

    El ``tipo`` de una votación tiene que estar declarado en ``voting.types``, y
    esa lista acepta cualquier texto no vacío. Escribir ahí el tipo adversarial
    es la forma legítima —no forzada— de que un ``tipo`` multilínea llegue al
    L3 por el camino productivo.

    El padrón recibe nombre, apellido y DNI adversariales en las dos bancas que
    participan del recorrido, de modo que las familias de presencia, palabra y
    voto ordinario también transporten texto humano difícil.

    Devuelve los DNI efectivamente escritos, para poder exigir después que
    ninguno aparezca en el acta.
    """

    carpeta = directorio / "config"
    carpeta.mkdir(parents=True, exist_ok=True)

    # ``json.dumps`` produce una cadena básica de TOML válida para este corpus:
    # escapa comillas, barras y saltos de línea, y deja el Unicode literal.
    tipos = json.loads(LINEA_TYPES.split("=", 1)[1].strip())
    tipos.extend(tipos_extra)
    linea_types = "types = " + json.dumps(tipos, ensure_ascii=False)

    contenido = (
        TOML_CANONICO.replace(LINEA_LOGS, f'logs_dir = "{directorio / "logs"}"')
        .replace(LINEA_QUORUM, "quorum = 2")
        .replace(LINEA_TYPES, linea_types)
    )
    escribir_system_toml(carpeta / "system.toml", contenido)

    filas = filas_padron_valido()
    for numero, fila in enumerate(filas, start=1):
        fila[5] = f"dev{numero:02d}"
    if ajustar_padron is None:
        filas[0][0] = DNI_CON_PUNTO_Y_COMA
        filas[0][1] = NOMBRE_ADVERSARIAL
        filas[0][2] = APELLIDO_ADVERSARIAL
        filas[1][2] = APELLIDO_MULTILINEA
    else:
        ajustar_padron(filas)
    escribir_padron(carpeta / "concejales.csv", filas)
    return [fila[0] for fila in filas]


@asynccontextmanager
async def cliente_adversarial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    tipos_extra: tuple[str, ...] = (TIPO_ADVERSARIAL,),
    ajustar_padron: Callable[[list[list[str]]], None] | None = None,
) -> AsyncGenerator[tuple[AsyncClient, FastAPI, list[str]]]:
    """Entrega cliente, aplicación y DNI del padrón con el lifespan real."""

    dnis = preparar_archivos_adversariales(
        tmp_path,
        tipos_extra=tipos_extra,
        ajustar_padron=ajustar_padron,
    )
    monkeypatch.chdir(tmp_path)
    aplicacion = crear_aplicacion()
    async with aplicacion.router.lifespan_context(aplicacion):
        bridge = BridgeAdversarial()
        recursos = obtener_recursos_aplicacion(aplicacion)
        monkeypatch.setattr(recursos.cliente_control_bridge, "iniciar", bridge.iniciar)
        monkeypatch.setattr(recursos.cliente_control_bridge, "confirmar", bridge.confirmar)
        transporte = ASGITransport(app=aplicacion)
        async with AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
            yield cliente, aplicacion, dnis


def rutas_del_conjunto_activo(aplicacion: FastAPI) -> dict[NivelAuditoria, Path]:
    """Copia las rutas del conjunto abierto antes de que el cierre las suelte."""

    estado = obtener_recursos_aplicacion(aplicacion).estado_operativo
    contexto = estado.contexto_operativo_activo()
    assert contexto is not None
    return dict(contexto.escritor_auditoria.rutas)


async def recorrido_adversarial_completo(cliente: AsyncClient) -> set[str]:
    """Ejecuta por API una sesión donde cada campo humano lleva texto difícil.

    El recorrido toca, con servicios reales, todas las familias L3 que
    transportan texto humano variable: presencia (con y sin efectos sobre la
    palabra), las cuatro de palabra, voto ordinario, apertura de votación,
    cierre por completitud, resultado final, empate y desempate presidencial,
    finalización inconclusa manual y por pérdida de quórum, actualización de
    autoridades, marcadores de recinto y remapeo autorizado.

    Devuelve los identificadores internos realmente persistidos, para exigir
    después que ninguno aparezca en el acta.
    """

    assert (await cliente.post("/api/v1/preparacion")).status_code == 204
    for dispositivo in ("dev01", "dev02"):
        respuesta = await cliente.post(
            "/api/v1/entradas/tecla",
            json={"dispositivo": dispositivo, "tecla": "9"},
        )
        assert respuesta.status_code == 200

    # Remapeo: aporta huellas e identificadores que el acta debe descartar.
    inicio = await cliente.post("/api/v1/remapeos", json={"dispositivo": "dev05"})
    assert inicio.status_code == 201
    remapeo_id = inicio.json()["remapeo_id"]
    assert (
        await cliente.post(
            f"/api/v1/interno/remapeos/{remapeo_id}/candidato",
            json={
                "fingerprint": BridgeAdversarial.FINGERPRINT_CANDIDATO,
                "diagnostico": "Teclado sustituto",
            },
        )
    ).status_code == 200
    assert (
        await cliente.post(
            f"/api/v1/remapeos/{remapeo_id}/confirmacion",
            json={"persistencia": "TEMPORAL"},
        )
    ).status_code == 204

    # Autoridades adversariales durante PREPARANDO y una corrección ya en sesión.
    assert (
        await cliente.patch(
            "/api/v1/preparacion",
            json={
                "numero_sesion": 107,
                "presidencia": "Presidencia Inicial",
                "secretaria_legislativa": SECRETARIA_ADVERSARIAL,
            },
        )
    ).status_code == 204
    assert (await cliente.post("/api/v1/sesion")).status_code == 204
    assert (
        await cliente.patch("/api/v1/sesion", json={"presidencia": PRESIDENCIA_ADVERSARIAL})
    ).status_code == 204

    # Marcadores de recinto: texto humano con ``;``, ``=`` y comillas.
    assert (
        await cliente.post(
            "/api/v1/apoyo-tecnico/avisos",
            json={"texto": AVISO_ADVERSARIAL, "destino": "RECINTO"},
        )
    ).status_code in (200, 201, 204)
    assert (await cliente.delete("/api/v1/apoyo-tecnico/avisos/RECINTO")).status_code in (200, 204)

    # Palabra: pedido, retiro, otorgamiento y las dos causas de finalización.
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

    # Votación 1: tipo y tema adversariales, empate y desempate presidencial.
    empatada = await cliente.post(
        "/api/v1/votaciones",
        json={
            "numero_votacion": 1,
            "tipo": TIPO_ADVERSARIAL,
            "tema": TEMA_ADVERSARIAL,
            "tipo_mayoria": "SIMPLE",
        },
    )
    assert empatada.status_code == 201
    id_empatada = empatada.json()["id"]
    for dispositivo, tecla in (("dev01", "1"), ("dev02", "3")):
        assert (
            await cliente.post(
                "/api/v1/entradas/tecla",
                json={"dispositivo": dispositivo, "tecla": tecla},
            )
        ).status_code == 200
    assert (
        await cliente.post(
            f"/api/v1/votaciones/{id_empatada}/desempate",
            json={"sentido": "POSITIVO"},
        )
    ).status_code in (200, 204)

    # Votación 2: mayoría especial con tema CRLF que llega a resultado final.
    especial = await cliente.post(
        "/api/v1/votaciones",
        json={
            "numero_votacion": 2,
            "tipo": TIPO_ADVERSARIAL,
            "tema": TEMA_CRLF,
            "tipo_mayoria": "ESPECIAL",
            "factor": 0.5,
            "base": "PRESENTES",
        },
    )
    assert especial.status_code == 201
    for dispositivo, tecla in (("dev01", "1"), ("dev02", "2")):
        assert (
            await cliente.post(
                "/api/v1/entradas/tecla",
                json={"dispositivo": dispositivo, "tecla": tecla},
            )
        ).status_code == 200

    # Votación 3: finalizada manualmente con un motivo adversarial.
    manual = await cliente.post(
        "/api/v1/votaciones",
        json={
            "numero_votacion": 3,
            "tipo": TIPO_ADVERSARIAL,
            "tema": TEMA_ADVERSARIAL,
            "tipo_mayoria": "SIMPLE",
        },
    )
    assert manual.status_code == 201
    id_manual = manual.json()["id"]
    assert (
        await cliente.post(
            f"/api/v1/votaciones/{id_manual}/finalizacion",
            json={"motivo": MOTIVO_ADVERSARIAL},
        )
    ).status_code in (200, 204)

    # Votación 4: queda INCONCLUSA por pérdida de quórum al ausentarse una banca.
    quorum = await cliente.post(
        "/api/v1/votaciones",
        json={
            "numero_votacion": 4,
            "tipo": TIPO_ADVERSARIAL,
            "tema": TEMA_CRLF,
            "tipo_mayoria": "SIMPLE",
        },
    )
    assert quorum.status_code == 201
    assert (
        await cliente.post(
            "/api/v1/entradas/tecla",
            json={"dispositivo": "dev02", "tecla": "9"},
        )
    ).status_code == 200

    return {remapeo_id, id_empatada, especial.json()["id"], id_manual, quorum.json()["id"]}


async def test_cerrar_una_sesion_con_texto_humano_adversarial_genera_el_acta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reproducción del defecto: el cierre real debe responder ``acta_generada=true``.

    Ésta es la regresión que el WP exige y la que estaba roja antes de la
    corrección: con un ``tema`` de dos renglones el catálogo no encontraba la
    forma esperada, ``componer_acta`` levantaba ``ErrorActaNoDerivable`` y
    ``DELETE /api/v1/sesion`` devolvía ``acta_generada=false`` sin que ningún
    CSV reflejara el problema.
    """

    async with cliente_adversarial(tmp_path, monkeypatch) as (cliente, aplicacion, _dnis):
        await recorrido_adversarial_completo(cliente)
        rutas = rutas_del_conjunto_activo(aplicacion)

        respuesta = await cliente.delete("/api/v1/sesion")

        assert respuesta.status_code == 200
        cuerpo = respuesta.json()
        assert cuerpo["acta_generada"] is True, (
            "Un L3 estructuralmente válido con texto humano multilínea no puede "
            "impedir la generación del acta"
        )

        ruta_acta = ruta_acta_de_conjunto(rutas[NivelAuditoria.L3])
        assert ruta_acta.exists()
        acta = ruta_acta.read_text(encoding="utf-8")

    assert acta.startswith("SIS-Leg\n")
    assert acta.endswith("\n")


async def test_el_acta_adversarial_conserva_el_texto_humano(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Admitir el texto no alcanza: tiene que seguir estando y ser legible."""

    async with cliente_adversarial(tmp_path, monkeypatch) as (cliente, aplicacion, _dnis):
        await recorrido_adversarial_completo(cliente)
        rutas = rutas_del_conjunto_activo(aplicacion)
        assert (await cliente.delete("/api/v1/sesion")).status_code == 200
        acta = ruta_acta_de_conjunto(rutas[NivelAuditoria.L3]).read_text(encoding="utf-8")

    # Todo renglón escrito por una persona sobrevive literalmente.
    for texto in TEXTOS_HUMANOS_PUBLICABLES:
        exigir_texto_humano_representado(acta, texto)

    # Y los hechos institucionales siguen redactados como corresponde.
    esperados = (
        "Preparación del recinto iniciada",
        "Se autorizó el reemplazo de un dispositivo de votación",
        "Apertura de sesión Nº107",
        "Presidencia actualizado",
        "Secretaría Legislativa actualizado",
        "Pedido de palabra registrado:",
        "Pedido de palabra retirado:",
        "Uso de la palabra otorgado:",
        "Uso de la palabra finalizado por Moderación:",
        "Uso de la palabra finalizado a pedido del propio concejal:",
        "Votación Nro 1 abierta.",
        "Voto ordinario en la votación Nro 1:",
        "Voto de desempate de la Presidencia en la votación Nro 1: POSITIVO",
        "Resultado de la votación Nro 1 por desempate de la Presidencia: APROBADA.",
        "Mayoría especial: proporción requerida",
        "Resultado de la votación Nro 2 por mayoría especial:",
        "Votación Nro 3 finalizada como INCONCLUSA por decisión de Moderación.",
        "se AUSENTÓ",
        "Votación Nro 4 finalizada como INCONCLUSA por pérdida de quórum.",
        "Cierre de sesión Nº107",
    )
    for fragmento in esperados:
        assert fragmento in acta, f"El acta perdió el hecho institucional {fragmento!r}"


async def test_el_acta_adversarial_no_filtra_metadata_tecnica(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Texto humano parecido a la gramática interna no habilita fugas técnicas.

    Es la contracara de la prueba anterior: el corpus contiene a propósito
    ``DNI=``, ``; id=``, ``banca=``, ``causa=``, ``tipo_mayoria=`` y ``factor=``.
    Si el catálogo copiara metadata del mensaje técnico, alguno de esos literales
    aparecería más veces de las que lo escribió una persona.
    """

    async with cliente_adversarial(tmp_path, monkeypatch) as (cliente, aplicacion, dnis):
        identificadores = await recorrido_adversarial_completo(cliente)
        rutas = rutas_del_conjunto_activo(aplicacion)
        assert (await cliente.delete("/api/v1/sesion")).status_code == 200
        acta = ruta_acta_de_conjunto(rutas[NivelAuditoria.L3]).read_text(encoding="utf-8")

    for identificador in identificadores:
        assert identificador not in acta, f"El acta filtró el identificador {identificador!r}"
    for dni in dnis:
        assert dni not in acta, f"El acta filtró el DNI {dni!r}"
    assert BridgeAdversarial.FINGERPRINT_ANTERIOR not in acta
    assert BridgeAdversarial.FINGERPRINT_CANDIDATO not in acta
    for numero in range(1, 13):
        assert f"dev{numero:02d}" not in acta

    exigir_sin_fuga_de_metadata(acta, TEXTOS_HUMANOS_PUBLICABLES)


async def test_el_acta_adversarial_conserva_una_linea_por_evento(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El informe sigue teniendo exactamente una línea por fila del L3.

    Es la comprobación estructural de la estrategia de presentación: si el texto
    humano multilínea se copiara tal cual, un solo evento ocuparía varias líneas
    y el acta dejaría de ser recorrible evento por evento.
    """

    async with cliente_adversarial(tmp_path, monkeypatch) as (cliente, aplicacion, _dnis):
        await recorrido_adversarial_completo(cliente)
        rutas = rutas_del_conjunto_activo(aplicacion)
        assert (await cliente.delete("/api/v1/sesion")).status_code == 200
        ruta_l3 = rutas[NivelAuditoria.L3]
        acta = ruta_acta_de_conjunto(ruta_l3).read_text(encoding="utf-8")

    import csv

    with ruta_l3.open(encoding="utf-8-sig", newline="") as archivo:
        filas_l3 = sum(1 for _ in csv.reader(archivo, delimiter=";")) - 1

    lineas = acta.splitlines()
    assert len(lineas) == 4 + filas_l3

    # Las cuatro primeras son el encabezado fijo; el resto son eventos fechados.
    for linea in lineas[4:]:
        assert SEPARADOR_LINEA_ACTA in linea
        hora, _, _ = linea.partition(SEPARADOR_LINEA_ACTA)
        assert len(hora) == len("HH:MM:SS")


# ---------------------------------------------------------------------------
# 2. Contrato textual, familia por familia
#
# El bloque anterior demuestra que el recorrido productivo funciona. Éste fija
# el contrato de cada familia con texto humano frente al corpus completo,
# incluidas combinaciones que el recorrido no produce en una sola sesión.
#
# Las plantillas repiten literalmente la forma que hoy construye cada productor.
# Si un productor cambiara su forma, el bloque 1 —que usa los servicios reales—
# fallaría, y las pruebas de cobertura del catálogo de WP-085 también.
# ---------------------------------------------------------------------------

CORPUS_ADVERSARIAL = (
    pytest.param("Texto simple", id="texto-simple"),
    pytest.param("Renglón 1\nRenglón 2", id="salto-lf"),
    pytest.param("Renglón 1\r\nRenglón 2", id="salto-crlf"),
    pytest.param("Uno\nDos\nTres\nCuatro", id="varias-lineas"),
    pytest.param("Tildes áéíóú, ñ y Ü; ç", id="unicode"),
    pytest.param("Punto; y coma; repetido", id="punto-y-coma"),
    pytest.param("Igual=uno=dos", id="igual"),
    pytest.param("Comillas 'simples' y \"dobles\"", id="comillas"),
    pytest.param("Cola; tipo_mayoria=SIMPLE; factor=0", id="delimitador-votacion"),
    pytest.param("Cola; banca=99", id="delimitador-banca"),
    pytest.param("Cola; causa=MANUAL", id="delimitador-causa"),
    pytest.param("Cola; id=falso; posicion=7", id="delimitador-id-posicion"),
    pytest.param(
        'Línea 1\r\nLínea 2; artículo=3 "texto" — ñ/á; tipo_mayoria=SIMPLE; factor=0; banca=',
        id="combinacion-adversarial",
    ),
)
"""Corpus mínimo que exige el WP, ampliado con combinaciones.

Cada entrada se inyecta en el campo humano de cada familia. La expectativa es
siempre la misma: el acta se redacta, el texto sobrevive renglón por renglón y
no aparece ningún valor técnico del mensaje.
"""


def redactar_con_texto_humano(
    etiqueta: str,
    codigo: str,
    mensaje: str,
) -> str:
    """Redacta una línea aplicando la misma depuración que usa el generador.

    El generador del acta depura el mensaje (emojis y saltos de línea) antes de
    entregárselo al catálogo. Las pruebas de este bloque llaman al catálogo
    directamente, así que reproducen ese paso usando la función real; de otro
    modo estarían probando un camino que en producción no existe.
    """

    return redactar_linea_de_acta(etiqueta, codigo, normalizar_texto_para_acta(mensaje))


@pytest.mark.parametrize("humano", CORPUS_ADVERSARIAL)
def test_votacion_abierta_admite_cualquier_tipo_y_tema(humano: str) -> None:
    """``tipo`` y ``tema`` son texto libre y ninguno puede abortar el acta."""

    mensaje = (
        f"Votación abierta: número=12; tipo={humano}; tema={humano}; "
        "tipo_mayoria=ESPECIAL; factor=0.66; base=PRESENTES"
    )

    linea = redactar_con_texto_humano("VOTACION", "VOTACION_ABIERTA", mensaje)

    assert "Votación Nro 12 abierta." in linea
    assert "Mayoría especial: proporción requerida 0.66 sobre los concejales presentes." in linea
    for renglon in lineas_significativas(humano):
        assert renglon in linea
    assert "\n" not in linea


@pytest.mark.parametrize("humano", CORPUS_ADVERSARIAL)
def test_finalizacion_manual_admite_cualquier_motivo(humano: str) -> None:
    """El motivo de una finalización manual es el último campo del mensaje."""

    mensaje = (
        "Votación finalizada inconclusa; numero_votacion=3; "
        "id=9f0c2a4e-0000-4000-8000-000000000001; causa=MANUAL; "
        "estado_previo=ABIERTA; resultado_previo=None; votos_conservados=2; "
        f"resultado_nuevo=INCONCLUSA; motivo_manual={humano}"
    )

    linea = redactar_con_texto_humano("VOTACION", "VOTACION_FINALIZADA_INCONCLUSA", mensaje)

    assert "Votación Nro 3 finalizada como INCONCLUSA por decisión de Moderación." in linea
    assert "Votos conservados: 2." in linea
    assert "9f0c2a4e-0000-4000-8000-000000000001" not in linea
    for renglon in lineas_significativas(humano):
        assert renglon in linea
    assert "\n" not in linea


@pytest.mark.parametrize("humano", CORPUS_ADVERSARIAL)
@pytest.mark.parametrize(
    ("codigo", "campo"),
    (
        ("NUMERO_SESION_ACTUALIZADO", "Número de sesión"),
        ("PRESIDENCIA_ACTUALIZADA", "Presidencia"),
        ("SECRETARIA_LEGISLATIVA_ACTUALIZADA", "Secretaría Legislativa"),
    ),
)
def test_autoridades_admiten_cualquier_valor(codigo: str, campo: str, humano: str) -> None:
    """Las tres actualizaciones institucionales llevan valores humanos libres.

    Usa los ``event_code`` **históricos**, que desde WP-107 I003 identifican
    exclusivamente el formato anterior. Son los que llevan los conjuntos ya
    cerrados y esta prueba fija que ninguno de ellos deje de derivarse por el
    contenido de su texto. El formato vigente de estas familias se prueba, con
    su propio código versionado, en la suite del formato.
    """

    mensaje = f"{campo} actualizado: sin informar -> {humano}"

    linea = redactar_con_texto_humano("SESION", codigo, mensaje)

    assert f"{campo} actualizado:" in linea
    for renglon in lineas_significativas(humano):
        assert renglon in linea
    assert "\n" not in linea


@pytest.mark.parametrize("humano", CORPUS_ADVERSARIAL)
def test_presencia_admite_cualquier_identidad(humano: str) -> None:
    """Nombre y apellido salen del padrón, que no restringe caracteres."""

    presente = redactar_con_texto_humano(
        "PRESENCIA",
        "CONCEJAL_PRESENTE",
        f"{humano} (banca Nro:4) se PRESENTÓ",
    )
    ausente = redactar_con_texto_humano(
        "PRESENCIA",
        "CONCEJAL_AUSENTE",
        f"{humano} (banca Nro:4) se AUSENTÓ"
        "; pedido_palabra_retirado=true; uso_palabra_finalizado=true",
    )

    assert "se PRESENTÓ" in presente
    assert "se AUSENTÓ. Como consecuencia, se retiró su pedido de palabra" in ausente
    assert "pedido_palabra_retirado=" not in ausente
    for renglon in lineas_significativas(humano):
        assert renglon in presente
        assert renglon in ausente
    assert "\n" not in presente
    assert "\n" not in ausente


@pytest.mark.parametrize("humano", CORPUS_ADVERSARIAL)
@pytest.mark.parametrize(
    ("codigo", "cola", "esperado"),
    (
        ("PEDIDO_PALABRA_REGISTRADO", "; posicion=3", "Pedido de palabra registrado:"),
        ("PEDIDO_PALABRA_RETIRADO", "; posicion_previa=2", "Pedido de palabra retirado:"),
        ("USO_PALABRA_OTORGADO", "; posicion_origen=1", "Uso de la palabra otorgado:"),
        (
            "USO_PALABRA_FINALIZADO",
            "; causa=MODERACION",
            "Uso de la palabra finalizado por Moderación:",
        ),
    ),
)
def test_palabra_admite_cualquier_identidad(
    codigo: str,
    cola: str,
    esperado: str,
    humano: str,
) -> None:
    """Las cuatro familias de palabra comparten el bloque ``DNI/concejal/banca``.

    El DNI también es texto humano del padrón: acá se le inyecta el corpus para
    demostrar que un DNI con ``;`` o con un salto de línea no rompe el acta ni
    se publica.
    """

    prefijos = {
        "PEDIDO_PALABRA_REGISTRADO": "Pedido de palabra registrado",
        "PEDIDO_PALABRA_RETIRADO": "Pedido de palabra retirado",
        "USO_PALABRA_OTORGADO": "Uso de palabra otorgado",
        "USO_PALABRA_FINALIZADO": "Uso de palabra finalizado",
    }
    mensaje = f"{prefijos[codigo]}: DNI={humano}; concejal={humano}; banca=4{cola}"

    linea = redactar_con_texto_humano("PALABRA", codigo, mensaje)

    assert esperado in linea
    assert "(banca Nro:4)" in linea
    assert "DNI=" not in linea or "DNI=" in humano
    for renglon in lineas_significativas(humano):
        assert renglon in linea
    assert "\n" not in linea


@pytest.mark.parametrize("humano", CORPUS_ADVERSARIAL)
def test_voto_ordinario_admite_cualquier_identidad(humano: str) -> None:
    """El voto publica persona y sentido; el identificador interno se descarta."""

    mensaje = (
        f"Voto ordinario: {humano} (banca Nro:4) votó POSITIVO; "
        "votación número=5; id=9f0c2a4e-0000-4000-8000-000000000002"
    )

    linea = redactar_con_texto_humano("VOTACION", "VOTO_ORDINARIO_REGISTRADO", mensaje)

    assert "Voto ordinario en la votación Nro 5:" in linea
    assert "votó POSITIVO." in linea
    assert "9f0c2a4e-0000-4000-8000-000000000002" not in linea
    for renglon in lineas_significativas(humano):
        assert renglon in linea
    assert "\n" not in linea


@pytest.mark.parametrize("humano", CORPUS_ADVERSARIAL)
def test_desempate_presidencial_admite_cualquier_presidencia(humano: str) -> None:
    """La Presidencia que desempata es texto humano libre en las dos familias."""

    voto = redactar_con_texto_humano(
        "VOTACION",
        "VOTO_DESEMPATE_PRESIDENCIAL",
        f"Voto presidencial de desempate: numero_votacion=7; "
        f"id=9f0c2a4e-0000-4000-8000-000000000003; presidencia={humano}; "
        "sentido=NEGATIVO; estado_previo=CERRADA; resultado_previo=EMPATADA; "
        "votos_ordinarios=4; positivos=2; negativos=2; abstenciones=0",
    )
    resultado = redactar_con_texto_humano(
        "VOTACION",
        "VOTACION_RESULTADO_DESEMPATE",
        f"Resultado por desempate presidencial: numero_votacion=7; "
        f"id=9f0c2a4e-0000-4000-8000-000000000003; presidencia={humano}; "
        "sentido=NEGATIVO; resultado_previo=EMPATADA; resultado_final=RECHAZADA; "
        "votos_ordinarios=4; positivos=2; negativos=2; abstenciones=0",
    )

    assert "Voto de desempate de la Presidencia en la votación Nro 7: NEGATIVO" in voto
    assert "Resultado de la votación Nro 7 por desempate de la Presidencia: RECHAZADA." in resultado
    assert "Votos positivos: 2. Votos negativos: 2. Abstenciones: 0." in resultado
    for texto in (voto, resultado):
        assert "9f0c2a4e-0000-4000-8000-000000000003" not in texto
        assert "\n" not in texto

    # Sólo el evento del voto publica quién desempató; la línea de resultado ya
    # lo atribuye a «la Presidencia» y no repite el nombre (política de WP-085).
    for renglon in lineas_significativas(humano):
        assert renglon in voto


@pytest.mark.parametrize("humano", CORPUS_ADVERSARIAL)
@pytest.mark.parametrize(("codigo", "prefijo"), (("INICIO", "Inicio: "), ("FIN", "Fin: ")))
def test_marcadores_de_recinto_admiten_cualquier_texto(
    codigo: str,
    prefijo: str,
    humano: str,
) -> None:
    """El marcador publica el aviso tal como lo vio el recinto, con su marca.

    La API de avisos ya rechaza saltos de línea y caracteres de control, pero el
    catálogo no debe depender de esa restricción: un aviso registrado por otro
    camino, o un contrato futuro más permisivo, no puede abortar el acta.
    """

    linea = redactar_con_texto_humano("EVENTO", codigo, humano)

    assert linea.startswith(prefijo)
    for renglon in lineas_significativas(humano):
        assert renglon in linea
    assert "\n" not in linea


def test_un_tema_que_imita_el_separador_de_tema_no_pierde_contenido() -> None:
    """Caso límite honesto: un ``tema`` que contiene literalmente ``; tema=``.

    La gramática del mensaje L3 no está escapada, así que un texto humano que
    reproduce el separador ``; tema=`` es genuinamente ambiguo: el acta no puede
    saber dónde termina el ``tipo`` y dónde empieza el ``tema``.

    Lo que WP-107 sí garantiza, y esta prueba fija, es que esa ambigüedad **no**
    rompe el acta, **no** pierde contenido y **no** filtra metadata: todo el
    texto escrito por la persona sigue apareciendo en la línea.
    """

    mensaje = (
        "Votación abierta: número=9; tipo=Moción; tema=Primero; tema=Segundo; "
        "tipo_mayoria=SIMPLE; factor=0.0; base=VOTOS_COMPUTABLES"
    )

    linea = redactar_con_texto_humano("VOTACION", "VOTACION_ABIERTA", mensaje)

    assert "Votación Nro 9 abierta." in linea
    assert "Moción" in linea
    assert "Primero" in linea
    assert "Segundo" in linea
    assert "tipo_mayoria=" not in linea
    assert "base=" not in linea


# ---------------------------------------------------------------------------
# 3. Estrategia de presentación de los saltos de línea
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("original", "esperado"),
    (
        pytest.param("Uno\nDos", "Uno Dos", id="lf"),
        pytest.param("Uno\r\nDos", "Uno Dos", id="crlf"),
        pytest.param("Uno\rDos", "Uno Dos", id="cr-solo"),
        pytest.param("Uno\n\nDos", "Uno Dos", id="linea-en-blanco"),
        pytest.param("Uno\n   Dos", "Uno Dos", id="sangria"),
        pytest.param("Uno Dos", "Uno Dos", id="separador-de-linea-unicode"),
        pytest.param("Uno Dos", "Uno Dos", id="separador-de-parrafo-unicode"),
        pytest.param("\nUno\n", "Uno", id="saltos-en-los-extremos"),
    ),
)
def test_los_saltos_de_linea_se_aplanan_a_un_espacio(original: str, esperado: str) -> None:
    """Un evento del acta ocupa una línea: los saltos se vuelven un espacio.

    Es la estrategia de presentación que WP-107 exige documentar y probar. Se
    eligió un espacio y no un símbolo visible porque el acta se lee como prosa
    institucional y cualquier marca inventada podría confundirse con contenido
    escrito por la persona. Ningún carácter con significado se pierde: sólo se
    reemplaza la separación entre renglones.
    """

    assert normalizar_texto_para_acta(original) == esperado


def test_un_l3_con_tema_multilinea_produce_una_sola_linea(tmp_path: Path) -> None:
    """El aplanado ocurre en el archivo, no sólo en la función de depuración."""

    import csv

    carpeta = tmp_path / "2026-09-24"
    carpeta.mkdir(parents=True)
    ruta = carpeta / "2026-09-24_10-30-00-L3.csv"
    with ruta.open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.writer(archivo, delimiter=";", lineterminator="\n")
        escritor.writerow(("seq", "timestamp", "level", "tag", "event_code", "message"))
        escritor.writerow(
            (
                "1",
                "2026-09-24 10:30:05",
                "L3",
                "VOTACION",
                "VOTACION_ABIERTA",
                f"Votación abierta: número=1; tipo=Moción; tema={TEMA_ADVERSARIAL}; "
                "tipo_mayoria=SIMPLE; factor=0.0; base=VOTOS_COMPUTABLES",
            )
        )

    acta = componer_acta(ruta)

    lineas = acta.splitlines()
    assert len(lineas) == 5
    assert lineas[4].startswith("10:30:05")
    for renglon in lineas_significativas(TEMA_ADVERSARIAL):
        assert renglon in lineas[4]


# ---------------------------------------------------------------------------
# 4. El fallo cerrado estructural sigue vigente
#
# Admitir cualquier carácter humano no puede volver tolerante al generador
# frente a un archivo realmente dañado. WP-085 ya cubre estos casos; se repiten
# acá contra el contrato nuevo para que una relajación futura del texto humano
# no los arrastre sin que nadie lo note.
# ---------------------------------------------------------------------------


def test_una_familia_desconocida_sigue_abortando_el_acta() -> None:
    """Un ``event_code`` sin política declarada no se publica jamás."""

    with pytest.raises(ErrorActaNoDerivable, match="no tiene política de redacción"):
        redactar_linea_de_acta("VOTACION", "EVENT_CODE_INEXISTENTE", "cualquier texto")


@pytest.mark.parametrize(
    ("etiqueta", "codigo", "mensaje"),
    (
        pytest.param(
            "SESION",
            "SESION_ABIERTA",
            "Apertura de sesión NºXVII",
            id="numero-de-sesion-no-numerico",
        ),
        pytest.param(
            "VOTACION",
            "VOTACION_ABIERTA",
            "Votación abierta: número=1; tipo=Moción; tema=Tema; tipo_mayoria=SIMPLE",
            id="apertura-sin-factor-ni-base",
        ),
        pytest.param(
            "VOTACION",
            "VOTACION_ABIERTA",
            "Votación abierta: número=1; tipo=Moción; tema=Tema; tipo_mayoria=SIMPLE; "
            "factor=0.0; base=VOTOS_COMPUTABLES; campo_nuevo=1",
            id="apertura-con-campo-tecnico-agregado",
        ),
        pytest.param(
            "VOTACION",
            "VOTO_ORDINARIO_REGISTRADO",
            "Voto ordinario: Ana Garcia (banca Nro:1) votó DUDOSO; votación número=1; id=abc",
            id="sentido-de-voto-desconocido",
        ),
        pytest.param(
            "PREPARACION",
            "PREPARACION_INICIADA",
            "Preparación del recinto iniciada con detalles extra",
            id="frase-fija-alterada",
        ),
        pytest.param(
            "REMAPEO",
            "REMAPEO_AUTORIZADO",
            "Autorización humana de remapeo remapeo_id=1; dispositivo=dev01; "
            "fingerprint_anterior=a; fingerprint_candidato=b; persistencia=ETERNA",
            id="persistencia-desconocida",
        ),
    ),
)
def test_una_forma_tecnica_invalida_sigue_abortando_el_acta(
    etiqueta: str,
    codigo: str,
    mensaje: str,
) -> None:
    """La tolerancia es sobre el contenido humano, nunca sobre la estructura.

    Un campo técnico faltante, sobrante o con un valor fuera del conjunto
    declarado sigue abortando el acta entera: publicar una línea aproximada, o
    copiar un campo técnico que nadie revisó, es exactamente lo que el fallo
    cerrado existe para impedir.
    """

    with pytest.raises(ErrorActaNoDerivable):
        redactar_con_texto_humano(etiqueta, codigo, mensaje)


# ---------------------------------------------------------------------------
# 5. Fronteras entre campos humanos adyacentes (WP-107 iteración 2)
#
# La iteración 1 resolvió que un campo humano pudiera contener cualquier
# carácter. Quedó abierto un problema distinto y más profundo: cuando **dos**
# campos humanos son adyacentes dentro del mismo mensaje, el separador literal
# que los divide también puede aparecer dentro de uno de ellos, y entonces no
# existe forma de saber por regex dónde termina el primero.
#
# Estas pruebas no comprueban «que los fragmentos estén en alguna parte»: exigen
# la **estructura semántica concreta** de la línea institucional, es decir que
# cada porción de texto siga cumpliendo el rol que le dio la persona que la
# escribió.
# ---------------------------------------------------------------------------

TIPO_QUE_IMITA_LA_FRONTERA = "Moción; tema=esto sigue siendo TIPO"
"""Un ``tipo`` que reproduce literalmente el separador que lo divide del ``tema``."""

TEMA_QUE_IMITA_LA_FRONTERA = (
    "Tema real; tipo_mayoria=SIMPLE; factor=esto sigue siendo TEMA; tema=interno"
)
"""Un ``tema`` que reproduce a la vez el separador siguiente y el anterior."""


async def test_el_acta_atribuye_tipo_y_tema_aunque_imiten_su_propia_frontera(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Round-trip semántico real: ninguna porción puede cambiar de rol.

    Se abre la votación por la API productiva con un ``tipo`` que contiene
    ``; tema=`` y un ``tema`` que contiene ``; tipo_mayoria=`` y ``; tema=``. La
    sesión se cierra con ``DELETE /api/v1/sesion`` y se exige que la línea del
    acta diga exactamente «Tipo: <el tipo entero>. Tema: <el tema entero>.».

    No alcanza con que los dos textos aparezcan en algún lugar del acta: eso ya
    se cumplía antes de la corrección, con el final del tipo atribuido al tema.
    """

    async with cliente_adversarial(
        tmp_path,
        monkeypatch,
        tipos_extra=(TIPO_QUE_IMITA_LA_FRONTERA,),
    ) as (cliente, aplicacion, _dnis):
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
                    "numero_sesion": 107,
                    "presidencia": "Presidencia",
                    "secretaria_legislativa": "Secretaría",
                },
            )
        ).status_code == 204
        assert (await cliente.post("/api/v1/sesion")).status_code == 204

        apertura = await cliente.post(
            "/api/v1/votaciones",
            json={
                "numero_votacion": 1,
                "tipo": TIPO_QUE_IMITA_LA_FRONTERA,
                "tema": TEMA_QUE_IMITA_LA_FRONTERA,
                "tipo_mayoria": "SIMPLE",
            },
        )
        assert apertura.status_code == 201
        id_votacion = apertura.json()["id"]
        for dispositivo, tecla in (("dev01", "1"), ("dev02", "1")):
            assert (
                await cliente.post(
                    "/api/v1/entradas/tecla",
                    json={"dispositivo": dispositivo, "tecla": tecla},
                )
            ).status_code == 200

        rutas = rutas_del_conjunto_activo(aplicacion)
        respuesta = await cliente.delete("/api/v1/sesion")

        assert respuesta.status_code == 200
        assert respuesta.json()["acta_generada"] is True
        ruta_acta = ruta_acta_de_conjunto(rutas[NivelAuditoria.L3])
        assert ruta_acta.exists()
        acta = ruta_acta.read_text(encoding="utf-8")

    # Estructura semántica exacta: cada texto conserva su rol completo.
    esperado = (
        f"Votación Nro 1 abierta. "
        f"Tipo: {TIPO_QUE_IMITA_LA_FRONTERA}. "
        f"Tema: {TEMA_QUE_IMITA_LA_FRONTERA}. "
        f"Mayoría simple."
    )
    assert esperado in acta, (
        f"El acta no atribuyó tipo y tema completos a su propio rol.\nEsperado: {esperado!r}"
    )

    # Y la metadata técnica real sigue sin aparecer.
    assert id_votacion not in acta
    for numero in range(1, 13):
        assert f"dev{numero:02d}" not in acta


DNI_QUE_INYECTA_UN_CONCEJAL = "30000001; concejal=NO_ES_EL_CONCEJAL_REAL"
"""Un DNI del padrón que reproduce el separador del bloque de identidad."""

NOMBRE_REAL_DE_LA_BANCA = "Rosalía"
APELLIDO_REAL_DE_LA_BANCA = "Quiroga"


def _padron_con_dni_que_inyecta(filas: list[list[str]]) -> None:
    """Deja la banca 1 con un DNI que intenta suplantar al concejal."""

    filas[0][0] = DNI_QUE_INYECTA_UN_CONCEJAL
    filas[0][1] = NOMBRE_REAL_DE_LA_BANCA
    filas[0][2] = APELLIDO_REAL_DE_LA_BANCA


async def test_el_acta_publica_el_concejal_real_y_no_el_inyectado_desde_el_dni(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El bloque de identidad de PALABRA no puede suplantarse desde el DNI.

    El padrón acepta cualquier DNI no vacío, así que un DNI puede contener
    literalmente ``; concejal=...``. Si la frontera entre DNI y concejal fuera
    ambigua, el acta publicaría el nombre inyectado en lugar del real —o los dos
    juntos—, que es una falsificación de identidad en un documento institucional.
    """

    async with cliente_adversarial(
        tmp_path,
        monkeypatch,
        ajustar_padron=_padron_con_dni_que_inyecta,
    ) as (cliente, aplicacion, _dnis):
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
                    "numero_sesion": 107,
                    "presidencia": "Presidencia",
                    "secretaria_legislativa": "Secretaría",
                },
            )
        ).status_code == 204
        assert (await cliente.post("/api/v1/sesion")).status_code == 204

        # Pedido de palabra, otorgamiento y finalización: las cuatro familias
        # comparten el mismo bloque de identidad.
        assert (
            await cliente.post(
                "/api/v1/entradas/tecla",
                json={"dispositivo": "dev01", "tecla": "7"},
            )
        ).status_code == 200
        assert (await cliente.post("/api/v1/palabra")).status_code == 204
        assert (await cliente.delete("/api/v1/palabra")).status_code == 204

        rutas = rutas_del_conjunto_activo(aplicacion)
        respuesta = await cliente.delete("/api/v1/sesion")

        assert respuesta.status_code == 200
        assert respuesta.json()["acta_generada"] is True
        acta = ruta_acta_de_conjunto(rutas[NivelAuditoria.L3]).read_text(encoding="utf-8")

    persona_real = f"{NOMBRE_REAL_DE_LA_BANCA} {APELLIDO_REAL_DE_LA_BANCA} (banca Nro:1)"
    for encabezado in (
        "Pedido de palabra registrado: ",
        "Uso de la palabra otorgado: ",
        "Uso de la palabra finalizado por Moderación: ",
    ):
        assert f"{encabezado}{persona_real}" in acta, (
            f"El acta no publicó la identidad real en {encabezado!r}"
        )

    # Lo inyectado dentro del DNI no llega al acta por ningún camino.
    assert "NO_ES_EL_CONCEJAL_REAL" not in acta
    assert "30000001" not in acta
    assert "DNI=" not in acta


AUTORIDAD_QUE_IMITA_LA_FLECHA = "Dra. Paz -> Dr. Lugo"
"""Una autoridad cuyo nombre contiene el separador ``->`` entre valores."""


async def test_el_acta_atribuye_las_autoridades_aunque_contengan_la_flecha(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``anterior -> nuevo`` tampoco puede confundirse con el contenido.

    El valor anterior y el nuevo son dos campos humanos adyacentes separados por
    una flecha literal. Un nombre que contenga ``->`` desplaza la frontera.
    """

    async with cliente_adversarial(tmp_path, monkeypatch) as (cliente, aplicacion, _dnis):
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
                    "numero_sesion": 107,
                    "presidencia": AUTORIDAD_QUE_IMITA_LA_FLECHA,
                    "secretaria_legislativa": "Secretaría",
                },
            )
        ).status_code == 204
        assert (await cliente.post("/api/v1/sesion")).status_code == 204

        rutas = rutas_del_conjunto_activo(aplicacion)
        respuesta = await cliente.delete("/api/v1/sesion")

        assert respuesta.status_code == 200
        assert respuesta.json()["acta_generada"] is True
        acta = ruta_acta_de_conjunto(rutas[NivelAuditoria.L3]).read_text(encoding="utf-8")

    esperado = f"Presidencia actualizado: sin informar -> {AUTORIDAD_QUE_IMITA_LA_FLECHA}"
    assert esperado in acta, (
        f"El acta no atribuyó correctamente la autoridad.\nEsperado: {esperado!r}"
    )


# ---------------------------------------------------------------------------
# 6. Discriminación de formato por event_code (WP-107 iteración 3)
#
# Las actualizaciones de sesión ya no declaran su formato dentro del mensaje: lo
# declaran en su ``event_code``. Acá se comprueba, por el camino productivo, que
# el productor emite el código versionado y que el acta atribuye cada autoridad
# a su rol aunque el texto imite la marca del formato.
# ---------------------------------------------------------------------------

AUTORIDAD_QUE_IMITA_LA_MARCA = "formato=h1; anterior=Ana; nuevo=Beatriz"
AUTORIDAD_CON_VERSION_FUTURA = "formato=h2; texto"
AUTORIDAD_CON_FLECHA_Y_ESCAPES = "formato=h1; anterior=X; nuevo=Y -> Z\\p y \\\\"


async def test_las_autoridades_nuevas_usan_event_code_versionado_y_se_atribuyen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regresión B de la iteración 3, por API real.

    Se cambian Presidencia y Secretaría con valores que imitan exactamente la
    marca de formato y se exige que:

    1. el productor escriba el ``event_code`` versionado en el L3;
    2. el acta atribuya cada valor a su rol, sin que el texto desplace nada;
    3. el cierre responda ``acta_generada=true``;
    4. no se filtre metadata técnica real.
    """

    async with cliente_adversarial(tmp_path, monkeypatch) as (cliente, aplicacion, dnis):
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
                    "numero_sesion": 107,
                    "presidencia": AUTORIDAD_QUE_IMITA_LA_MARCA,
                    "secretaria_legislativa": AUTORIDAD_CON_VERSION_FUTURA,
                },
            )
        ).status_code == 204
        assert (await cliente.post("/api/v1/sesion")).status_code == 204
        assert (
            await cliente.patch(
                "/api/v1/sesion",
                json={"presidencia": AUTORIDAD_CON_FLECHA_Y_ESCAPES},
            )
        ).status_code == 204

        rutas = rutas_del_conjunto_activo(aplicacion)
        respuesta = await cliente.delete("/api/v1/sesion")

        assert respuesta.status_code == 200
        assert respuesta.json()["acta_generada"] is True

        ruta_l3 = rutas[NivelAuditoria.L3]
        acta = ruta_acta_de_conjunto(ruta_l3).read_text(encoding="utf-8")

        import csv as _csv

        with ruta_l3.open(encoding="utf-8-sig", newline="") as archivo:
            codigos = [fila[4] for fila in _csv.reader(archivo, delimiter=";")][1:]

    # 1. El productor versionó el event_code y no dejó ninguno histórico.
    assert "PRESIDENCIA_ACTUALIZADA_H1" in codigos
    assert "SECRETARIA_LEGISLATIVA_ACTUALIZADA_H1" in codigos
    assert "NUMERO_SESION_ACTUALIZADO_H1" in codigos
    for historico in (
        "PRESIDENCIA_ACTUALIZADA",
        "SECRETARIA_LEGISLATIVA_ACTUALIZADA",
        "NUMERO_SESION_ACTUALIZADO",
    ):
        assert historico not in codigos, (
            f"El productor volvió a emitir el event_code histórico {historico!r}"
        )

    # 2. Cada valor conserva su rol completo, aunque imite la marca de formato.
    for esperado in (
        f"Presidencia actualizado: sin informar -> {AUTORIDAD_QUE_IMITA_LA_MARCA}",
        f"Secretaría Legislativa actualizado: sin informar -> {AUTORIDAD_CON_VERSION_FUTURA}",
        (
            f"Presidencia actualizado: {AUTORIDAD_QUE_IMITA_LA_MARCA} -> "
            f"{AUTORIDAD_CON_FLECHA_Y_ESCAPES}"
        ),
        "Número de sesión actualizado: sin informar -> 107",
    ):
        assert esperado in acta, f"El acta no atribuyó la autoridad.\nEsperado: {esperado!r}"

    # 4. Ninguna metadata técnica real se filtró.
    for dni in dnis:
        assert dni not in acta
    for numero in range(1, 13):
        assert f"dev{numero:02d}" not in acta
