"""Catálogo de redacción institucional del acta a partir del L3 (WP-085).

Por qué existe este módulo
--------------------------

El archivo L3 es evidencia técnica: su columna ``message`` está redactada para
poder **reconstruir** un hecho, no para leerse en un acta. Por eso muchos
mensajes durables llevan metadata embebida —identificadores internos, huellas de
dispositivo, banderas booleanas, posiciones de cola— que un acta institucional no
debe contener. Reutilizar el ``message`` tal cual cumpliría la regla "sin
columnas técnicas" y aun así violaría la regla "sin identificadores ni
información técnica".

Este catálogo traduce cada familia ``(tag, event_code)`` del L3 a **una** línea
de acta redactada en castellano, que conserva el hecho institucional y descarta
lo técnico.

Segura por construcción, no por borrado
---------------------------------------

Cada familia declara explícitamente qué información publica. No se intenta
borrar a posteriori lo que "parezca" técnico. Un borrado genérico de pares
``clave=valor`` sería peor por dos motivos: podría comerse un nombre humano que
contenga un ``=``, y dejaría pasar en silencio cualquier campo técnico nuevo que
un WP futuro agregue al final de un mensaje existente.

Los patrones están **anclados al mensaje completo**. Si mañana alguien agrega un
campo al final de un ``message``, el patrón deja de coincidir y el acta falla en
vez de publicar ese campo sin que nadie lo haya revisado.

Fallo cerrado
-------------

Si aparece una familia L3 que este catálogo no conoce, o si el ``message`` de una
familia conocida no tiene la forma esperada, la generación del acta **falla**
entera con :class:`ErrorActaNoDerivable`. Nunca se copia el mensaje crudo ni se
emite una línea aproximada: un acta que filtre metadata técnica, o que omita en
silencio un hecho, es peor que un acta que no se generó. Los CSV siguen siendo el
registro completo y el cierre institucional sigue siendo válido.

Por qué las etiquetas y códigos se escriben acá como texto literal
------------------------------------------------------------------

Sería natural importar las constantes de cada servicio, pero
``servicios.sesion`` importa el generador del acta para ejecutarlo al cerrar: si
este módulo importara ``servicios.sesion`` habría un ciclo de importación. En su
lugar, las cadenas se repiten acá y el test de cobertura del catálogo comprueba
en CI que sigan coincidiendo exactamente con las constantes de cada servicio.

Cómo agregar una familia nueva
------------------------------

Cuando un WP futuro registre un ``event_code`` L3 nuevo hay que agregar su
entrada en :data:`POLITICAS_ACTA`. Si no se hace, el test de cobertura del
catálogo falla en CI antes de que nadie pueda generar un acta con un hecho sin
redacción revisada.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

PREFIJO_MARCADOR_INICIO = "Inicio: "
PREFIJO_MARCADOR_FIN = "Fin: "
"""Redacción formal de los marcadores ``EVENTO/INICIO`` y ``EVENTO/FIN`` (WP-078).

En el CSV esos dos eventos se distinguen por su ``event_code``, que el acta no
imprime. Sin este prefijo, un ``INICIO`` y su ``FIN`` producirían dos líneas de
texto idéntico y quien lee el acta no podría saber cuál abrió y cuál cerró el
período.
"""


class ErrorActaNoDerivable(RuntimeError):
    """El L3 no puede convertirse en un acta institucional confiable.

    Se levanta ante una fila con forma no canónica, un timestamp ilegible, una
    familia ``(tag, event_code)`` sin política declarada o un ``message`` que no
    respeta la forma que su familia produce hoy.

    Quien la captura debe abandonar el acta completa. Nunca debe usarse para
    saltear la fila problemática: omitir evidencia sin señal es exactamente lo
    que este error existe para impedir.
    """


@dataclass(frozen=True, slots=True)
class PoliticaActa:
    """Cómo se publica en el acta una familia ``(tag, event_code)`` del L3.

    Atributos:
        redactar: recibe el ``message`` ya depurado de emojis y devuelve el texto
            de la línea del acta. Levanta :class:`ErrorActaNoDerivable` si el
            mensaje no tiene la forma que esa familia produce.
        motivo: explica en una frase qué publica y qué descarta esa familia.
            Es documentación viva del catálogo y se usa en los mensajes de error.
    """

    redactar: Callable[[str], str]
    motivo: str


# ---------------------------------------------------------------------------
# Familias del L3: etiquetas y códigos
#
# Cada constante repite literalmente la cadena que registra su servicio. El test
# de cobertura del catálogo comprueba que sigan siendo idénticas.
# ---------------------------------------------------------------------------

ETIQUETA_PREPARACION = "PREPARACION"
CODIGO_PREPARACION_INICIADA = "PREPARACION_INICIADA"
CODIGO_PREPARACION_CANCELADA = "PREPARACION_CANCELADA"

ETIQUETA_SESION = "SESION"
CODIGO_SESION_ABIERTA = "SESION_ABIERTA"
CODIGO_SESION_CERRADA = "SESION_CERRADA"
CODIGO_NUMERO_SESION_ACTUALIZADO = "NUMERO_SESION_ACTUALIZADO"
CODIGO_PRESIDENCIA_ACTUALIZADA = "PRESIDENCIA_ACTUALIZADA"
CODIGO_SECRETARIA_LEGISLATIVA_ACTUALIZADA = "SECRETARIA_LEGISLATIVA_ACTUALIZADA"

ETIQUETA_PRESENCIA = "PRESENCIA"
CODIGO_CONCEJAL_PRESENTE = "CONCEJAL_PRESENTE"
CODIGO_CONCEJAL_AUSENTE = "CONCEJAL_AUSENTE"

ETIQUETA_PALABRA = "PALABRA"
CODIGO_PEDIDO_PALABRA_REGISTRADO = "PEDIDO_PALABRA_REGISTRADO"
CODIGO_PEDIDO_PALABRA_RETIRADO = "PEDIDO_PALABRA_RETIRADO"
CODIGO_USO_PALABRA_OTORGADO = "USO_PALABRA_OTORGADO"
CODIGO_USO_PALABRA_FINALIZADO = "USO_PALABRA_FINALIZADO"

ETIQUETA_VOTACION = "VOTACION"
CODIGO_VOTACION_ABIERTA = "VOTACION_ABIERTA"
CODIGO_VOTO_ORDINARIO_REGISTRADO = "VOTO_ORDINARIO_REGISTRADO"
CODIGO_VOTACION_CERRADA_COMPLETITUD = "VOTACION_CERRADA_COMPLETITUD"
CODIGO_VOTACION_RESULTADO_FINAL = "VOTACION_RESULTADO_FINAL"
CODIGO_VOTACION_RESULTADO_EMPATE = "VOTACION_RESULTADO_EMPATE"
CODIGO_VOTACION_FINALIZADA_INCONCLUSA = "VOTACION_FINALIZADA_INCONCLUSA"
CODIGO_VOTO_DESEMPATE_PRESIDENCIAL = "VOTO_DESEMPATE_PRESIDENCIAL"
CODIGO_VOTACION_RESULTADO_DESEMPATE = "VOTACION_RESULTADO_DESEMPATE"

ETIQUETA_REMAPEO = "REMAPEO"
CODIGO_REMAPEO_AUTORIZADO = "REMAPEO_AUTORIZADO"

ETIQUETA_EVENTO_PRINCIPAL = "EVENTO"
CODIGO_MARCADOR_INICIO = "INICIO"
CODIGO_MARCADOR_FIN = "FIN"
CODIGO_TRANSMISION_PRINCIPAL_INICIO = "TRANSMISION_EN_VIVO_INICIADA"
CODIGO_TRANSMISION_PRINCIPAL_FIN = "TRANSMISION_EN_VIVO_FINALIZADA"

MENSAJE_TRANSMISION_PRINCIPAL_INICIO = "Transmisión en vivo iniciada"
MENSAJE_TRANSMISION_PRINCIPAL_FIN = "Transmisión en vivo finalizada"
"""Frases institucionales exactas de los eventos de transmisión (WP-096).

Se repiten acá por el mismo motivo que las etiquetas y los códigos —evitar el
ciclo de importación con los servicios— y el test de cobertura del catálogo
comprueba en CI que sigan coincidiendo con las constantes de
``servicios/apoyo_tecnico.py``.

El acta las publica tal cual, sin prefijo: a diferencia de los marcadores de
aviso, estas dos frases ya dicen por sí solas cuál abrió y cuál cerró el
período, y no arrastran ningún dato técnico que haya que descartar.
"""


# ---------------------------------------------------------------------------
# Utilidades de redacción
# ---------------------------------------------------------------------------


def _texto_fijo(esperado: str, familia: str) -> Callable[[str], str]:
    """Acepta únicamente la frase fija y segura que produce una familia.

    Aunque hoy el mensaje no lleve metadata, comparar su contenido completo
    evita que un cambio futuro en el productor agregue un campo técnico sin que
    el catálogo lo advierta. La frase se devuelve sin reescritura porque ya es
    institucional.
    """

    def redactar(mensaje: str) -> str:
        if mensaje != esperado:
            raise ErrorActaNoDerivable(
                f"El mensaje L3 de {familia} no coincide con su frase institucional "
                f"vigente: {mensaje!r}"
            )
        return mensaje

    return redactar


def _conservar_si_coincide(
    patron: re.Pattern[str],
    familia: str,
) -> Callable[[str], str]:
    """Conserva una frase humana sólo cuando respeta su forma completa actual."""

    def redactar(mensaje: str) -> str:
        _exigir(patron, mensaje, familia)
        return mensaje

    return redactar


def _con_prefijo(prefijo: str) -> Callable[[str], str]:
    """Devuelve una redacción que antepone un prefijo fijo al texto humano."""

    def redactar(mensaje: str) -> str:
        return f"{prefijo}{mensaje}"

    return redactar


def _exigir(patron: re.Pattern[str], mensaje: str, familia: str) -> re.Match[str]:
    """Aplica un patrón anclado al mensaje completo o falla cerrado."""

    coincidencia = patron.fullmatch(mensaje)
    if coincidencia is None:
        raise ErrorActaNoDerivable(
            f"El mensaje L3 de {familia} no tiene la forma que el acta sabe redactar: {mensaje!r}"
        )
    return coincidencia


def _persona(concejal: str, banca: str) -> str:
    """Redacta identidad y banca como aparecen en el resto del acta.

    Es la misma forma que ya usan los eventos de presencia y de voto, de modo que
    todo el informe nombre a las personas de una única manera.
    """

    return f"{concejal} (banca Nro:{banca})"


# ---------------------------------------------------------------------------
# Presencia
# ---------------------------------------------------------------------------

# ``CONCEJAL_AUSENTE`` agrega dos banderas cuando la ausencia ocurre con sesión
# abierta: si además se retiró un pedido de palabra y si se cortó un uso en
# curso. Ambos son hechos institucionales que el acta debe conservar, pero
# escritos en prosa y no como ``clave=valor``.
_AUSENCIA = re.compile(
    r"(?P<persona>.*) se AUSENTÓ"
    r"(?:; pedido_palabra_retirado=(?P<pedido>true|false)"
    r"; uso_palabra_finalizado=(?P<uso>true|false))?"
)

_PRESENCIA = re.compile(r".+ \(banca Nro:[^)]+\) se PRESENTÓ")

# Los cambios de sesión transportan sólo valores institucionales, pero se exige
# el prefijo y el separador exactos para detectar cualquier campo agregado.
_NUMERO_SESION_ACTUALIZADO = re.compile(r"Número de sesión actualizado: .* -> .*", re.DOTALL)
_PRESIDENCIA_ACTUALIZADA = re.compile(r"Presidencia actualizado: .* -> .*", re.DOTALL)
_SECRETARIA_ACTUALIZADA = re.compile(
    r"Secretaría Legislativa actualizado: .* -> .*",
    re.DOTALL,
)
_SESION_ABIERTA = re.compile(r"Apertura de sesión Nº\d+")
_SESION_CERRADA = re.compile(r"Cierre de sesión Nº\d+")


def _redactar_ausencia(mensaje: str) -> str:
    """Conserva la ausencia y sus efectos sobre la palabra, sin banderas."""

    datos = _exigir(_AUSENCIA, mensaje, "PRESENCIA/CONCEJAL_AUSENTE")
    linea = f"{datos['persona']} se AUSENTÓ"

    efectos: list[str] = []
    if datos["pedido"] == "true":
        efectos.append("se retiró su pedido de palabra")
    if datos["uso"] == "true":
        efectos.append("finalizó su uso de la palabra")
    if not efectos:
        return linea
    return f"{linea}. Como consecuencia, {' y '.join(efectos)}."


# ---------------------------------------------------------------------------
# Palabra
#
# Los cuatro mensajes comparten el bloque de identidad ``DNI=...; concejal=...;
# banca=...``. El acta publica nombre y banca; el DNI es dato técnico de
# trazabilidad y queda sólo en el CSV. Las posiciones de cola tampoco se
# publican: son estado interno del mecanismo de turnos.
# ---------------------------------------------------------------------------

_IDENTIDAD_PALABRA = r"DNI=[^;]*; concejal=(?P<concejal>.*); banca=(?P<banca>[^;]*)"

_PEDIDO_REGISTRADO = re.compile(
    rf"Pedido de palabra registrado: {_IDENTIDAD_PALABRA}; posicion=\d+"
)
_PEDIDO_RETIRADO = re.compile(
    rf"Pedido de palabra retirado: {_IDENTIDAD_PALABRA}; posicion_previa=\d+"
)
_USO_OTORGADO = re.compile(rf"Uso de palabra otorgado: {_IDENTIDAD_PALABRA}; posicion_origen=\d+")
_USO_FINALIZADO = re.compile(
    rf"Uso de palabra finalizado: {_IDENTIDAD_PALABRA}; causa=(?P<causa>PROPIO|MODERACION)"
)

_CAUSAS_FIN_PALABRA = MappingProxyType(
    {
        "PROPIO": "a pedido del propio concejal",
        "MODERACION": "por Moderación",
    }
)


def _redactar_pedido_registrado(mensaje: str) -> str:
    datos = _exigir(_PEDIDO_REGISTRADO, mensaje, "PALABRA/PEDIDO_PALABRA_REGISTRADO")
    return f"Pedido de palabra registrado: {_persona(datos['concejal'], datos['banca'])}"


def _redactar_pedido_retirado(mensaje: str) -> str:
    datos = _exigir(_PEDIDO_RETIRADO, mensaje, "PALABRA/PEDIDO_PALABRA_RETIRADO")
    return f"Pedido de palabra retirado: {_persona(datos['concejal'], datos['banca'])}"


def _redactar_uso_otorgado(mensaje: str) -> str:
    datos = _exigir(_USO_OTORGADO, mensaje, "PALABRA/USO_PALABRA_OTORGADO")
    return f"Uso de la palabra otorgado: {_persona(datos['concejal'], datos['banca'])}"


def _redactar_uso_finalizado(mensaje: str) -> str:
    """Conserva quién dejó de hablar y a instancias de quién terminó.

    La causa es un hecho institucional —no es lo mismo que el concejal cierre su
    intervención a que Moderación se la retire— así que se publica en prosa en
    lugar del par ``causa=...`` del registro técnico.
    """

    datos = _exigir(_USO_FINALIZADO, mensaje, "PALABRA/USO_PALABRA_FINALIZADO")
    causa = _CAUSAS_FIN_PALABRA[datos["causa"]]
    return f"Uso de la palabra finalizado {causa}: {_persona(datos['concejal'], datos['banca'])}"


# ---------------------------------------------------------------------------
# Votación
# ---------------------------------------------------------------------------

# ``tipo`` y ``tema`` son texto libre cargado por Moderación u obtenido del Orden
# del Día: pueden contener ``;`` y ``=``. Por eso el patrón los delimita con las
# claves literales que vienen después y no partiendo el mensaje por separadores.
_VOTACION_ABIERTA = re.compile(
    r"Votación abierta: número=(?P<numero>\d+); tipo=(?P<tipo>.*?); tema=(?P<tema>.*)"
    r"; tipo_mayoria=(?P<mayoria>SIMPLE|ESPECIAL); factor=(?P<factor>[^;]*)"
    r"; base=(?P<base>[A-Z_]+)"
)

_BASES_EN_PROSA = MappingProxyType(
    {
        "PRESENTES": "los concejales presentes",
        "CUERPO": "la totalidad del cuerpo",
    }
)


def _base_en_prosa(base: str, familia: str) -> str:
    """Traduce la base de una mayoría especial a lenguaje de acta.

    Una base desconocida hace fallar el acta: antes que publicar un valor de
    enumeración crudo en un documento institucional, conviene que alguien revise
    qué significa esa base nueva.
    """

    if base not in _BASES_EN_PROSA:
        raise ErrorActaNoDerivable(
            f"El acta no sabe redactar la base de mayoría {base!r} usada en {familia}"
        )
    return _BASES_EN_PROSA[base]


def _redactar_votacion_abierta(mensaje: str) -> str:
    """Publica número, tipo, tema y regla de mayoría de la votación abierta."""

    datos = _exigir(_VOTACION_ABIERTA, mensaje, "VOTACION/VOTACION_ABIERTA")
    if datos["mayoria"] == "SIMPLE":
        regla = "Mayoría simple."
    else:
        base = _base_en_prosa(datos["base"], "VOTACION/VOTACION_ABIERTA")
        regla = f"Mayoría especial: proporción requerida {datos['factor']} sobre {base}."
    return (
        f"Votación Nro {datos['numero']} abierta. "
        f"Tipo: {datos['tipo']}. Tema: {datos['tema']}. {regla}"
    )


_VOTO_ORDINARIO = re.compile(
    r"Voto ordinario: (?P<persona>.*) votó (?P<valor>POSITIVO|NEGATIVO|ABSTENCION)"
    r"; votación número=(?P<numero>\d+); id=[^;]*"
)


def _redactar_voto_ordinario(mensaje: str) -> str:
    """Publica quién votó, qué votó y en qué votación; descarta el id interno."""

    datos = _exigir(_VOTO_ORDINARIO, mensaje, "VOTACION/VOTO_ORDINARIO_REGISTRADO")
    return (
        f"Voto ordinario en la votación Nro {datos['numero']}: "
        f"{datos['persona']} votó {datos['valor']}."
    )


_VOTACION_CERRADA = re.compile(
    r"Votación cerrada: número=(?P<numero>\d+); id=[^;]*; motivo=COMPLETITUD"
    r"; todos_los_presentes_votaron=true; quorum_alcanzado=true"
)


def _redactar_votacion_cerrada(mensaje: str) -> str:
    """Traduce el cierre por completitud a la frase que explica por qué cerró."""

    datos = _exigir(_VOTACION_CERRADA, mensaje, "VOTACION/VOTACION_CERRADA_COMPLETITUD")
    return (
        f"Votación Nro {datos['numero']} cerrada: emitieron su voto todos los concejales presentes."
    )


_CONTEOS = (
    r"positivos=(?P<positivos>\d+); negativos=(?P<negativos>\d+)"
    r"; abstenciones=(?P<abstenciones>\d+)"
)

_RESULTADO_SIMPLE = re.compile(
    r"Resultado ordinario: número=(?P<numero>\d+); id=[^;]*; tipo_mayoria=SIMPLE"
    rf"; {_CONTEOS}; comparación=positivos_vs_negativos; abstenciones_excluidas=true"
    r"; resultado=(?P<resultado>[A-Z]+)"
)

_RESULTADO_ESPECIAL = re.compile(
    r"Resultado ordinario: número=(?P<numero>\d+); id=[^;]*; tipo_mayoria=ESPECIAL"
    rf"; {_CONTEOS}; base=(?P<base>[A-Z_]+); denominador=(?P<denominador>\d+)"
    r"; factor=[^;]*; cociente=[^;]*; caso_sin_division=(?:true|false)"
    r"; resultado=(?P<resultado>[A-Z]+)"
)


def _detalle_conteos(datos: re.Match[str]) -> str:
    """Redacta los tres conteos que un acta necesita para justificar el resultado."""

    return (
        f"Votos positivos: {datos['positivos']}. "
        f"Votos negativos: {datos['negativos']}. "
        f"Abstenciones: {datos['abstenciones']}."
    )


def _redactar_resultado_ordinario(mensaje: str) -> str:
    """Publica el resultado y su fundamento aritmético, sin id ni banderas.

    El mismo ``event_code`` puede describir una mayoría simple o una especial, y
    cada una lleva campos distintos. Se prueban ambas formas y, si ninguna
    coincide, el acta falla en vez de publicar una línea aproximada.
    """

    familia = "VOTACION/VOTACION_RESULTADO_FINAL o VOTACION_RESULTADO_EMPATE"

    simple = _RESULTADO_SIMPLE.fullmatch(mensaje)
    if simple is not None:
        return (
            f"Resultado de la votación Nro {simple['numero']} por mayoría simple: "
            f"{simple['resultado']}. {_detalle_conteos(simple)} "
            "Las abstenciones no se computan."
        )

    especial = _exigir(_RESULTADO_ESPECIAL, mensaje, familia)
    base = _base_en_prosa(especial["base"], familia)
    return (
        f"Resultado de la votación Nro {especial['numero']} por mayoría especial: "
        f"{especial['resultado']}. {_detalle_conteos(especial)} "
        f"Base de cálculo: {especial['denominador']} sobre {base}."
    )


_INCONCLUSA = re.compile(
    r"Votación finalizada inconclusa; numero_votacion=(?P<numero>\d+); id=[^;]*"
    r"; causa=(?P<causa>MANUAL|PERDIDA_QUORUM|CIERRE_SESION); estado_previo=[A-Z_]+"
    r"; resultado_previo=[A-Za-z]+; votos_conservados=(?P<votos>\d+)"
    r"; resultado_nuevo=INCONCLUSA(?P<cola>.*)"
)

_COLA_MANUAL = re.compile(r"; motivo_manual=(?P<motivo>.*)")
_COLA_QUORUM = re.compile(r"; presentes=(?P<presentes>\d+); quorum_requerido=(?P<quorum>\d+)")
_COLA_CIERRE = re.compile(r"; resuelta_por_cierre_sesion=true")


def _redactar_inconclusa(mensaje: str) -> str:
    """Explica por qué la votación quedó INCONCLUSA y cuántos votos se conservan.

    La causa determina qué datos adicionales trae el mensaje, así que cada una
    tiene su propio patrón para la cola. Los votos conservados se publican porque
    el acta debe dejar constancia de que esos votos no se descartaron.
    """

    familia = "VOTACION/VOTACION_FINALIZADA_INCONCLUSA"
    datos = _exigir(_INCONCLUSA, mensaje, familia)
    encabezado = f"Votación Nro {datos['numero']} finalizada como INCONCLUSA"
    conservados = f"Votos conservados: {datos['votos']}."
    cola = datos["cola"]

    if datos["causa"] == "MANUAL":
        detalle = _exigir(_COLA_MANUAL, cola, f"{familia} (MANUAL)")
        return (
            f"{encabezado} por decisión de Moderación. Motivo: {detalle['motivo']}. {conservados}"
        )

    if datos["causa"] == "PERDIDA_QUORUM":
        detalle = _exigir(_COLA_QUORUM, cola, f"{familia} (PERDIDA_QUORUM)")
        return (
            f"{encabezado} por pérdida de quórum. "
            f"Concejales presentes: {detalle['presentes']}. "
            f"Quórum requerido: {detalle['quorum']}. {conservados}"
        )

    _exigir(_COLA_CIERRE, cola, f"{familia} (CIERRE_SESION)")
    return f"{encabezado} por el cierre de la sesión. {conservados}"


_VOTO_DESEMPATE = re.compile(
    r"Voto presidencial de desempate: numero_votacion=(?P<numero>\d+); id=[^;]*"
    r"; presidencia=(?P<presidencia>.*); sentido=(?P<sentido>POSITIVO|NEGATIVO)"
    r"; estado_previo=[A-Z_]+; resultado_previo=[A-Z]+; votos_ordinarios=\d+"
    rf"; {_CONTEOS}"
)


def _redactar_voto_desempate(mensaje: str) -> str:
    """Publica el voto presidencial de desempate con su sentido y quién lo emitió."""

    datos = _exigir(_VOTO_DESEMPATE, mensaje, "VOTACION/VOTO_DESEMPATE_PRESIDENCIAL")
    return (
        f"Voto de desempate de la Presidencia en la votación Nro {datos['numero']}: "
        f"{datos['sentido']}, emitido por {datos['presidencia']}."
    )


_RESULTADO_DESEMPATE = re.compile(
    r"Resultado por desempate presidencial: numero_votacion=(?P<numero>\d+); id=[^;]*"
    r"; presidencia=(?P<presidencia>.*); sentido=(?P<sentido>POSITIVO|NEGATIVO)"
    r"; resultado_previo=EMPATADA; resultado_final=(?P<final>[A-Z]+)"
    rf"; votos_ordinarios=\d+; {_CONTEOS}"
)


def _redactar_resultado_desempate(mensaje: str) -> str:
    """Publica el resultado final alcanzado por el desempate presidencial."""

    datos = _exigir(_RESULTADO_DESEMPATE, mensaje, "VOTACION/VOTACION_RESULTADO_DESEMPATE")
    return (
        f"Resultado de la votación Nro {datos['numero']} por desempate de la Presidencia: "
        f"{datos['final']}. {_detalle_conteos(datos)}"
    )


# ---------------------------------------------------------------------------
# Remapeo
# ---------------------------------------------------------------------------

# El registro técnico identifica la operación, el dispositivo lógico y las dos
# huellas físicas involucradas. Nada de eso pertenece al acta: para el cuerpo
# legislativo el hecho institucional es que se autorizó reemplazar un dispositivo
# durante la sesión, y si esa autorización rige sólo para esta sesión o queda
# asentada en la configuración del sistema.
_REMAPEO = re.compile(
    r"Autorización humana de remapeo remapeo_id=[^;]*; dispositivo=[^;]*"
    r"; fingerprint_anterior=[^;]*; fingerprint_candidato=[^;]*"
    r"; persistencia=(?P<persistencia>TEMPORAL|PERSISTENTE)"
)

_PERSISTENCIAS_EN_PROSA = MappingProxyType(
    {
        "TEMPORAL": "con validez limitada a esta sesión",
        "PERSISTENTE": "de forma permanente",
    }
)


def _redactar_remapeo(mensaje: str) -> str:
    """Deja el hecho institucional del remapeo sin identificadores ni huellas."""

    datos = _exigir(_REMAPEO, mensaje, "REMAPEO/REMAPEO_AUTORIZADO")
    alcance = _PERSISTENCIAS_EN_PROSA[datos["persistencia"]]
    return f"Se autorizó el reemplazo de un dispositivo de votación {alcance}."


# ---------------------------------------------------------------------------
# El catálogo
# ---------------------------------------------------------------------------

POLITICAS_ACTA: Mapping[tuple[str, str], PoliticaActa] = MappingProxyType(
    {
        (ETIQUETA_PREPARACION, CODIGO_PREPARACION_INICIADA): PoliticaActa(
            redactar=_texto_fijo(
                "Preparación del recinto iniciada",
                "PREPARACION/PREPARACION_INICIADA",
            ),
            motivo="Frase fija sin datos: 'Preparación del recinto iniciada'.",
        ),
        (ETIQUETA_PREPARACION, CODIGO_PREPARACION_CANCELADA): PoliticaActa(
            redactar=_texto_fijo(
                "Preparación del recinto cancelada",
                "PREPARACION/PREPARACION_CANCELADA",
            ),
            motivo="Frase fija sin datos: 'Preparación del recinto cancelada'.",
        ),
        (ETIQUETA_SESION, CODIGO_SESION_ABIERTA): PoliticaActa(
            redactar=_conservar_si_coincide(_SESION_ABIERTA, "SESION/SESION_ABIERTA"),
            motivo="Sólo apertura y número de sesión, ambos institucionales.",
        ),
        (ETIQUETA_SESION, CODIGO_SESION_CERRADA): PoliticaActa(
            redactar=_conservar_si_coincide(_SESION_CERRADA, "SESION/SESION_CERRADA"),
            motivo="Sólo cierre y número de sesión, ambos institucionales.",
        ),
        (ETIQUETA_SESION, CODIGO_NUMERO_SESION_ACTUALIZADO): PoliticaActa(
            redactar=_conservar_si_coincide(
                _NUMERO_SESION_ACTUALIZADO,
                "SESION/NUMERO_SESION_ACTUALIZADO",
            ),
            motivo="Valor anterior y nuevo del número de sesión, sin metadata técnica.",
        ),
        (ETIQUETA_SESION, CODIGO_PRESIDENCIA_ACTUALIZADA): PoliticaActa(
            redactar=_conservar_si_coincide(
                _PRESIDENCIA_ACTUALIZADA,
                "SESION/PRESIDENCIA_ACTUALIZADA",
            ),
            motivo="Nombres de la autoridad anterior y nueva, sin metadata técnica.",
        ),
        (ETIQUETA_SESION, CODIGO_SECRETARIA_LEGISLATIVA_ACTUALIZADA): PoliticaActa(
            redactar=_conservar_si_coincide(
                _SECRETARIA_ACTUALIZADA,
                "SESION/SECRETARIA_LEGISLATIVA_ACTUALIZADA",
            ),
            motivo="Nombres de la autoridad anterior y nueva, sin metadata técnica.",
        ),
        (ETIQUETA_PRESENCIA, CODIGO_CONCEJAL_PRESENTE): PoliticaActa(
            redactar=_conservar_si_coincide(
                _PRESENCIA,
                "PRESENCIA/CONCEJAL_PRESENTE",
            ),
            motivo="Nombre, apellido y banca de quien se presentó.",
        ),
        (ETIQUETA_PRESENCIA, CODIGO_CONCEJAL_AUSENTE): PoliticaActa(
            redactar=_redactar_ausencia,
            motivo="Conserva la ausencia y sus efectos sobre la palabra; descarta las banderas.",
        ),
        (ETIQUETA_PALABRA, CODIGO_PEDIDO_PALABRA_REGISTRADO): PoliticaActa(
            redactar=_redactar_pedido_registrado,
            motivo="Conserva nombre y banca; descarta DNI y posición en la cola.",
        ),
        (ETIQUETA_PALABRA, CODIGO_PEDIDO_PALABRA_RETIRADO): PoliticaActa(
            redactar=_redactar_pedido_retirado,
            motivo="Conserva nombre y banca; descarta DNI y posición previa.",
        ),
        (ETIQUETA_PALABRA, CODIGO_USO_PALABRA_OTORGADO): PoliticaActa(
            redactar=_redactar_uso_otorgado,
            motivo="Conserva nombre y banca; descarta DNI y posición de origen.",
        ),
        (ETIQUETA_PALABRA, CODIGO_USO_PALABRA_FINALIZADO): PoliticaActa(
            redactar=_redactar_uso_finalizado,
            motivo="Conserva nombre, banca y a instancias de quién terminó; descarta DNI.",
        ),
        (ETIQUETA_VOTACION, CODIGO_VOTACION_ABIERTA): PoliticaActa(
            redactar=_redactar_votacion_abierta,
            motivo="Conserva número, tipo, tema y regla de mayoría en prosa.",
        ),
        (ETIQUETA_VOTACION, CODIGO_VOTO_ORDINARIO_REGISTRADO): PoliticaActa(
            redactar=_redactar_voto_ordinario,
            motivo="Conserva persona, sentido y número de votación; descarta el id interno.",
        ),
        (ETIQUETA_VOTACION, CODIGO_VOTACION_CERRADA_COMPLETITUD): PoliticaActa(
            redactar=_redactar_votacion_cerrada,
            motivo="Conserva número y motivo del cierre; descarta id y banderas.",
        ),
        (ETIQUETA_VOTACION, CODIGO_VOTACION_RESULTADO_FINAL): PoliticaActa(
            redactar=_redactar_resultado_ordinario,
            motivo="Conserva resultado, conteos y regla aplicada; descarta id y banderas.",
        ),
        (ETIQUETA_VOTACION, CODIGO_VOTACION_RESULTADO_EMPATE): PoliticaActa(
            redactar=_redactar_resultado_ordinario,
            motivo="Conserva resultado, conteos y regla aplicada; descarta id y banderas.",
        ),
        (ETIQUETA_VOTACION, CODIGO_VOTACION_FINALIZADA_INCONCLUSA): PoliticaActa(
            redactar=_redactar_inconclusa,
            motivo="Conserva causa en prosa, votos conservados y datos de quórum; descarta id.",
        ),
        (ETIQUETA_VOTACION, CODIGO_VOTO_DESEMPATE_PRESIDENCIAL): PoliticaActa(
            redactar=_redactar_voto_desempate,
            motivo="Conserva número, sentido y Presidencia; descarta id y estados previos.",
        ),
        (ETIQUETA_VOTACION, CODIGO_VOTACION_RESULTADO_DESEMPATE): PoliticaActa(
            redactar=_redactar_resultado_desempate,
            motivo="Conserva resultado final y conteos; descarta id y estados previos.",
        ),
        (ETIQUETA_REMAPEO, CODIGO_REMAPEO_AUTORIZADO): PoliticaActa(
            redactar=_redactar_remapeo,
            motivo="Conserva el hecho y su alcance; descarta id, dispositivo y huellas.",
        ),
        (ETIQUETA_EVENTO_PRINCIPAL, CODIGO_MARCADOR_INICIO): PoliticaActa(
            redactar=_con_prefijo(PREFIJO_MARCADOR_INICIO),
            motivo="Texto del aviso tal como lo vio el recinto, con marca de apertura.",
        ),
        (ETIQUETA_EVENTO_PRINCIPAL, CODIGO_MARCADOR_FIN): PoliticaActa(
            redactar=_con_prefijo(PREFIJO_MARCADOR_FIN),
            motivo="Texto del aviso tal como lo vio el recinto, con marca de cierre.",
        ),
        (ETIQUETA_EVENTO_PRINCIPAL, CODIGO_TRANSMISION_PRINCIPAL_INICIO): PoliticaActa(
            redactar=_texto_fijo(
                MENSAJE_TRANSMISION_PRINCIPAL_INICIO,
                "el inicio efectivo de la transmisión EN VIVO",
            ),
            motivo="Conserva la frase institucional fija; no publica horas ni banderas internas.",
        ),
        (ETIQUETA_EVENTO_PRINCIPAL, CODIGO_TRANSMISION_PRINCIPAL_FIN): PoliticaActa(
            redactar=_texto_fijo(
                MENSAJE_TRANSMISION_PRINCIPAL_FIN,
                "el fin efectivo de la transmisión EN VIVO",
            ),
            motivo="Conserva la frase institucional fija; no publica la causa técnica del cierre.",
        ),
    }
)
"""Única fuente de verdad de qué publica el acta para cada familia del L3.

Es un ``MappingProxyType`` para que ningún módulo pueda agregar una política en
tiempo de ejecución: el catálogo tiene que ser revisable leyendo este archivo.
"""


def redactar_linea_de_acta(etiqueta: str, codigo_evento: str, mensaje: str) -> str:
    """Traduce un evento L3 a su única línea de acta.

    Entradas:
        etiqueta: columna ``tag`` del CSV.
        codigo_evento: columna ``event_code``. Se usa **sólo** para elegir la
            política; nunca se imprime en el acta.
        mensaje: columna ``message``, ya depurada de emojis por el llamador.

    Resultado:
        El texto institucional de la línea, sin la hora, que agrega el llamador.

    Errores:
        ErrorActaNoDerivable: si la familia no está en el catálogo o si el
            mensaje no tiene la forma que esa familia produce.
    """

    politica = POLITICAS_ACTA.get((etiqueta, codigo_evento))
    if politica is None:
        raise ErrorActaNoDerivable(
            f"El acta no tiene política de redacción para la familia L3 "
            f"{etiqueta}/{codigo_evento}. Agregarla en POLITICAS_ACTA antes de "
            f"que ese evento pueda aparecer en un conjunto cerrado."
        )
    return politica.redactar(mensaje)
