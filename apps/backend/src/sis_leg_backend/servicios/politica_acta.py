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

Estricto con la estructura, sin restricción con el texto humano (WP-107)
------------------------------------------------------------------------

Esa estricticidad vale para la **estructura técnica** del mensaje, no para el
contenido de sus campos humanos. Varios mensajes transportan texto que una
persona escribió —el ``tipo`` y el ``tema`` de una votación, el motivo de una
finalización manual, las autoridades, el nombre y el apellido del padrón— y ni
la API ni el padrón restringen ahí los caracteres: aceptan saltos de línea,
``;``, ``=``, comillas y Unicode arbitrario, y el L3 los persiste tal cual.

El generador del acta no puede imponer indirectamente, mediante sus propias
expresiones regulares, un subconjunto textual más chico que el que el sistema
acepta y persiste. Antes de WP-107 lo hacía sin querer: el punto ``.`` de una
expresión regular **no** coincide con un salto de línea, así que un ``tema`` de
dos renglones —forma habitual de un Orden del Día real— convertía un L3
perfectamente válido en :class:`ErrorActaNoDerivable`.

Por eso todo campo humano se escribe hoy con :data:`CARACTER_TEXTO_HUMANO` en
lugar de ``.``: un campo humano acepta **cualquier** carácter. Los campos
técnicos conservan sus clases estrictas (un entero, una enumeración en
mayúsculas, un conjunto cerrado de valores), de modo que la tolerancia nueva no
alcanza a la estructura.

El salto de línea, además, se aplana a un espacio antes de llegar acá: el acta
es un informe de una línea por evento y esa normalización de presentación vive
en ``acta_institucional.normalizar_texto_para_acta``, documentada allí.

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

from sis_leg_backend.servicios.texto_humano_l3 import (
    CLAVE_FORMATO_TEXTO_HUMANO,
    MARCA_FORMATO_TEXTO_HUMANO,
    VERSION_FORMATO_TEXTO_HUMANO,
    ErrorTextoHumanoInvalido,
    decodificar_texto_humano,
)

CARACTER_TEXTO_HUMANO = r"[\s\S]"
"""Clase de caracteres de un campo humano: cualquiera, incluido el salto de línea.

Por qué no se usa ``.``
-----------------------

``.`` coincide con cualquier carácter **menos** el salto de línea, y ésa es
justamente la restricción que WP-107 vino a sacar: un ``tema`` de dos renglones
es texto que la API acepta, que el L3 persiste correctamente y que el acta debe
poder publicar.

Por qué no se usa ``re.DOTALL``
-------------------------------

``re.DOTALL`` produciría el mismo efecto, pero es una bandera que se aplica al
patrón **entero** y no deja ver en cada lugar cuál es la intención. Escribir la
clase en el sitio del campo hace evidente, leyendo una sola línea, qué campos
son humanos —y por lo tanto ilimitados— y cuáles son técnicos y siguen atados a
``\\d+``, ``[A-Z_]+`` o a un conjunto cerrado de valores. Esa asimetría es el
contrato de WP-107 y tiene que poder auditarse mirando el patrón.

Se usa ``[\\s\\S]`` y no ``[\\w\\W]`` o ``(?s:.)`` por ser la forma más difundida
y legible de "cualquier carácter" en una expresión regular.
"""

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


CAMPO_HUMANO_CODIFICADO = r"[^;]*"
"""Cómo se delimita un campo humano en el formato nuevo del L3 (WP-107 I002).

Un valor codificado no puede contener un ``;`` crudo —esa es la invariante que
garantiza :mod:`sis_leg_backend.servicios.texto_humano_l3`—, así que en un
mensaje con marca de formato **todo ``;`` es estructural** y ``[^;]*`` separa el
campo de forma exacta.

Es la diferencia de fondo con :data:`CARACTER_TEXTO_HUMANO`, que sigue usándose
para leer los mensajes históricos: aquella clase admite cualquier carácter y por
eso depende de que el resto del patrón fije la frontera; ésta no puede invadir la
estructura ni aunque la persona haya escrito el separador.
"""


def _declara_formato_nuevo(mensaje: str, prefijo: str, familia: str) -> bool:
    """Decide si el mensaje usa el formato codificado y valida su versión.

    Entradas:
        mensaje: el ``message`` completo del evento L3.
        prefijo: el texto fijo con el que empieza esa familia, por ejemplo
            ``"Votación abierta: "``. La marca vive siempre justo después.
        familia: nombre de la familia, sólo para el mensaje de error.

    Resultado:
        ``True`` cuando el mensaje declara la versión vigente y debe leerse con
        la gramática nueva; ``False`` cuando no declara ninguna y corresponde la
        ruta de compatibilidad histórica.

    Errores:
        ErrorActaNoDerivable: si declara una versión que este código no conoce.
            Es fallo cerrado deliberado: un formato futuro puede haber cambiado
            la tabla de escapes, y leerlo con la tabla vieja produciría un texto
            institucional silenciosamente equivocado.

    Por qué se mira la posición exacta y no «si aparece la marca en algún lado»:
    un texto humano podría contener la palabra ``formato=h1``. Exigir que esté
    inmediatamente después del prefijo la vuelve estructural, porque en los
    mensajes históricos esa posición la ocupa siempre otra clave técnica.
    """

    if not mensaje.startswith(prefijo):
        return False
    resto = mensaje[len(prefijo) :]
    if not resto.startswith(f"{CLAVE_FORMATO_TEXTO_HUMANO}="):
        return False
    if resto.startswith(f"{MARCA_FORMATO_TEXTO_HUMANO}; "):
        return True

    fin = resto.find(";")
    declarada = resto[len(CLAVE_FORMATO_TEXTO_HUMANO) + 1 : fin if fin != -1 else len(resto)]
    raise ErrorActaNoDerivable(
        f"El mensaje L3 de {familia} declara el formato de texto humano {declarada!r}, "
        f"y esta versión del acta sólo sabe leer {VERSION_FORMATO_TEXTO_HUMANO!r}. "
        "Actualizar el catálogo antes de derivar un conjunto con ese formato."
    )


def _decodificar_campo(valor: str, familia: str) -> str:
    """Devuelve el texto humano original de un campo ya separado del mensaje.

    Se aplica **después** de partir el mensaje por su estructura, nunca antes:
    decodificar el mensaje entero devolvería los ``;`` al interior de los valores
    y reintroduciría exactamente la ambigüedad que el formato elimina.

    Errores:
        ErrorActaNoDerivable: si el valor tiene escapes que no pertenecen al
            formato. Un acta no puede publicar un texto que no se pudo recuperar
            con certeza.
    """

    try:
        return decodificar_texto_humano(valor)
    except ErrorTextoHumanoInvalido as error:
        raise ErrorActaNoDerivable(
            f"El mensaje L3 de {familia} tiene un campo humano que no se puede decodificar: {error}"
        ) from error


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
    rf"(?P<persona>{CARACTER_TEXTO_HUMANO}*) se AUSENTÓ"
    r"(?:; pedido_palabra_retirado=(?P<pedido>true|false)"
    r"; uso_palabra_finalizado=(?P<uso>true|false))?"
)

_PRESENCIA = re.compile(rf"{CARACTER_TEXTO_HUMANO}+ \(banca Nro:[^)]+\) se PRESENTÓ")

# Los cambios de sesión transportan dos valores humanos adyacentes, el anterior
# y el nuevo. En el formato histórico los separaba una flecha literal ``" -> "``
# que también podía aparecer dentro de cualquiera de los dos nombres: la
# frontera era ambigua aunque el acta no la partiera. El formato nuevo los
# escribe como dos campos codificados y la flecha vuelve a ser sólo redacción
# del acta (WP-107 I002).
_SUFIJO_ACTUALIZACION = " actualizado: "

_ACTUALIZACION_CODIFICADA = (
    rf"{MARCA_FORMATO_TEXTO_HUMANO}; anterior=(?P<anterior>{CAMPO_HUMANO_CODIFICADO})"
    rf"; nuevo=(?P<nuevo>{CAMPO_HUMANO_CODIFICADO})"
)

# Ruta histórica: se conserva tal como la leía la iteración 1 para que los
# conjuntos ya cerrados sigan derivándose exactamente igual.
_ACTUALIZACION_LEGACY = rf"{CARACTER_TEXTO_HUMANO}* -> {CARACTER_TEXTO_HUMANO}*"


def _redactar_actualizacion(campo: str, familia: str) -> Callable[[str], str]:
    """Publica «<campo> actualizado: <anterior> -> <nuevo>» en ambos formatos.

    En el formato nuevo los dos valores se separan por estructura y se decodifican
    por separado, de modo que la línea del acta atribuye cada nombre a su rol aunque
    contenga la propia flecha. En el histórico el mensaje se conserva tal cual,
    que es lo que hacía la iteración 1: no se puede desambiguar hacia atrás un
    texto cuya frontera nunca se persistió, pero tampoco cambia lo que el acta
    venía publicando para esos conjuntos.
    """

    prefijo = f"{campo}{_SUFIJO_ACTUALIZACION}"
    # Se compilan una vez, al construir el catálogo, y quedan capturados por el
    # closure: cada evento sólo aplica el patrón que le corresponde.
    codificado = re.compile(rf"{re.escape(prefijo)}{_ACTUALIZACION_CODIFICADA}")
    legacy = re.compile(rf"{re.escape(prefijo)}{_ACTUALIZACION_LEGACY}")

    def redactar(mensaje: str) -> str:
        if _declara_formato_nuevo(mensaje, prefijo, familia):
            datos = _exigir(codificado, mensaje, familia)
            anterior = _decodificar_campo(datos["anterior"], familia)
            nuevo = _decodificar_campo(datos["nuevo"], familia)
            return f"{prefijo}{anterior} -> {nuevo}"
        _exigir(legacy, mensaje, familia)
        return mensaje

    return redactar


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

# El DNI también es texto humano: el padrón sólo exige que no esté vacío, así
# que puede traer un ``;`` y suplantar el nombre del concejal que viene después.
# En el formato nuevo ambos campos van codificados y ``[^;]*`` los separa de
# forma exacta; la ruta histórica conserva la lectura de la iteración 1.
_IDENTIDAD_CODIFICADA = (
    rf"{MARCA_FORMATO_TEXTO_HUMANO}; DNI={CAMPO_HUMANO_CODIFICADO}"
    rf"; concejal=(?P<concejal>{CAMPO_HUMANO_CODIFICADO}); banca=(?P<banca>[^;]*)"
)

_IDENTIDAD_LEGACY = (
    rf"DNI={CARACTER_TEXTO_HUMANO}*?; concejal=(?P<concejal>{CARACTER_TEXTO_HUMANO}*)"
    r"; banca=(?P<banca>[^;]*)"
)

# Cada familia de palabra es el mismo bloque de identidad con una cola técnica
# propia. Se declaran juntas para que agregar una futura no pueda olvidarse de
# ninguno de los dos formatos.
_COLAS_DE_PALABRA: Mapping[str, str] = MappingProxyType(
    {
        "Pedido de palabra registrado": r"; posicion=\d+",
        "Pedido de palabra retirado": r"; posicion_previa=\d+",
        "Uso de palabra otorgado": r"; posicion_origen=\d+",
        "Uso de palabra finalizado": r"; causa=(?P<causa>PROPIO|MODERACION)",
    }
)


# Los dos patrones de cada familia se compilan una sola vez, al importar el
# módulo. Además de ahorrar trabajo por evento, deja el catálogo completo
# construido de entrada: una cola mal escrita explota al importar y no la primera
# vez que alguien cierra una sesión.
_PATRONES_DE_PALABRA: Mapping[str, tuple[re.Pattern[str], re.Pattern[str]]] = MappingProxyType(
    {
        prefijo: (
            re.compile(rf"{re.escape(prefijo)}: {_IDENTIDAD_CODIFICADA}{cola}"),
            re.compile(rf"{re.escape(prefijo)}: {_IDENTIDAD_LEGACY}{cola}"),
        )
        for prefijo, cola in _COLAS_DE_PALABRA.items()
    }
)


def _redactar_identidad(prefijo: str, mensaje: str, familia: str) -> tuple[re.Match[str], str]:
    """Separa el bloque de identidad y devuelve la persona lista para publicarse.

    Entradas:
        prefijo: frase fija con la que empieza esa familia, por ejemplo
            ``"Pedido de palabra registrado"``.
        mensaje: el ``message`` completo, ya depurado por el generador.
        familia: nombre ``ETIQUETA/CODIGO``, sólo para los mensajes de error.

    Resultado:
        La coincidencia —que las familias con cola propia necesitan para leer su
        último campo técnico— y la persona ya redactada como la nombra el resto
        del acta.

    Errores:
        ErrorActaNoDerivable: si el mensaje no tiene la forma de su formato o si
            un campo codificado no se puede decodificar.

    Concentra en un solo lugar la regla de que el nombre se decodifica **sólo**
    cuando el mensaje declara el formato nuevo. La banca es un entero del dominio
    y nunca estuvo codificada.
    """

    codificado, legacy = _PATRONES_DE_PALABRA[prefijo]
    if _declara_formato_nuevo(mensaje, f"{prefijo}: ", familia):
        datos = _exigir(codificado, mensaje, familia)
        concejal = _decodificar_campo(datos["concejal"], familia)
    else:
        datos = _exigir(legacy, mensaje, familia)
        concejal = datos["concejal"]
    return datos, _persona(concejal, datos["banca"])


_CAUSAS_FIN_PALABRA = MappingProxyType(
    {
        "PROPIO": "a pedido del propio concejal",
        "MODERACION": "por Moderación",
    }
)


def _redactar_pedido_registrado(mensaje: str) -> str:
    _, persona = _redactar_identidad(
        "Pedido de palabra registrado", mensaje, "PALABRA/PEDIDO_PALABRA_REGISTRADO"
    )
    return f"Pedido de palabra registrado: {persona}"


def _redactar_pedido_retirado(mensaje: str) -> str:
    _, persona = _redactar_identidad(
        "Pedido de palabra retirado", mensaje, "PALABRA/PEDIDO_PALABRA_RETIRADO"
    )
    return f"Pedido de palabra retirado: {persona}"


def _redactar_uso_otorgado(mensaje: str) -> str:
    _, persona = _redactar_identidad(
        "Uso de palabra otorgado", mensaje, "PALABRA/USO_PALABRA_OTORGADO"
    )
    return f"Uso de la palabra otorgado: {persona}"


def _redactar_uso_finalizado(mensaje: str) -> str:
    """Conserva quién dejó de hablar y a instancias de quién terminó.

    La causa es un hecho institucional —no es lo mismo que el concejal cierre su
    intervención a que Moderación se la retire— así que se publica en prosa en
    lugar del par ``causa=...`` del registro técnico.
    """

    datos, persona = _redactar_identidad(
        "Uso de palabra finalizado", mensaje, "PALABRA/USO_PALABRA_FINALIZADO"
    )
    causa = _CAUSAS_FIN_PALABRA[datos["causa"]]
    return f"Uso de la palabra finalizado {causa}: {persona}"


# ---------------------------------------------------------------------------
# Votación
# ---------------------------------------------------------------------------

# ``tipo`` y ``tema`` son texto libre cargado por Moderación u obtenido del Orden
# del Día, y son los dos únicos campos humanos **adyacentes** del L3: el
# separador ``"; tema="`` puede aparecer dentro del propio ``tipo``. En el
# formato nuevo van codificados, así que ``[^;]*`` los separa de forma exacta.
_PREFIJO_VOTACION_ABIERTA = "Votación abierta: "

_VOTACION_ABIERTA_CODIFICADA = re.compile(
    rf"{_PREFIJO_VOTACION_ABIERTA}{MARCA_FORMATO_TEXTO_HUMANO}; número=(?P<numero>\d+)"
    rf"; tipo=(?P<tipo>{CAMPO_HUMANO_CODIFICADO}); tema=(?P<tema>{CAMPO_HUMANO_CODIFICADO})"
    r"; tipo_mayoria=(?P<mayoria>SIMPLE|ESPECIAL); factor=(?P<factor>[^;]*)"
    r"; base=(?P<base>[A-Z_]+)"
)

# Ruta histórica. Conserva la lectura de la iteración 1, incluida su ambigüedad
# irreparable: la información que permitiría separar tipo de tema nunca se
# persistió en esos archivos.
_VOTACION_ABIERTA_LEGACY = re.compile(
    rf"{_PREFIJO_VOTACION_ABIERTA}número=(?P<numero>\d+); tipo=(?P<tipo>{CARACTER_TEXTO_HUMANO}*?)"
    rf"; tema=(?P<tema>{CARACTER_TEXTO_HUMANO}*)"
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

    familia = "VOTACION/VOTACION_ABIERTA"
    if _declara_formato_nuevo(mensaje, _PREFIJO_VOTACION_ABIERTA, familia):
        datos = _exigir(_VOTACION_ABIERTA_CODIFICADA, mensaje, familia)
        tipo = _decodificar_campo(datos["tipo"], familia)
        tema = _decodificar_campo(datos["tema"], familia)
    else:
        datos = _exigir(_VOTACION_ABIERTA_LEGACY, mensaje, familia)
        tipo, tema = datos["tipo"], datos["tema"]
    if datos["mayoria"] == "SIMPLE":
        regla = "Mayoría simple."
    else:
        base = _base_en_prosa(datos["base"], familia)
        regla = f"Mayoría especial: proporción requerida {datos['factor']} sobre {base}."
    return f"Votación Nro {datos['numero']} abierta. Tipo: {tipo}. Tema: {tema}. {regla}"


_VOTO_ORDINARIO = re.compile(
    rf"Voto ordinario: (?P<persona>{CARACTER_TEXTO_HUMANO}*)"
    r" votó (?P<valor>POSITIVO|NEGATIVO|ABSTENCION)"
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
    rf"; resultado_nuevo=INCONCLUSA(?P<cola>{CARACTER_TEXTO_HUMANO}*)"
)

_COLA_MANUAL = re.compile(rf"; motivo_manual=(?P<motivo>{CARACTER_TEXTO_HUMANO}*)")
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
    rf"; presidencia=(?P<presidencia>{CARACTER_TEXTO_HUMANO}*)"
    r"; sentido=(?P<sentido>POSITIVO|NEGATIVO)"
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
    rf"; presidencia=(?P<presidencia>{CARACTER_TEXTO_HUMANO}*)"
    r"; sentido=(?P<sentido>POSITIVO|NEGATIVO)"
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
            redactar=_redactar_actualizacion(
                "Número de sesión", "SESION/NUMERO_SESION_ACTUALIZADO"
            ),
            motivo="Valor anterior y nuevo del número de sesión, sin metadata técnica.",
        ),
        (ETIQUETA_SESION, CODIGO_PRESIDENCIA_ACTUALIZADA): PoliticaActa(
            redactar=_redactar_actualizacion("Presidencia", "SESION/PRESIDENCIA_ACTUALIZADA"),
            motivo="Nombres de la autoridad anterior y nueva, sin metadata técnica.",
        ),
        (ETIQUETA_SESION, CODIGO_SECRETARIA_LEGISLATIVA_ACTUALIZADA): PoliticaActa(
            redactar=_redactar_actualizacion(
                "Secretaría Legislativa", "SESION/SECRETARIA_LEGISLATIVA_ACTUALIZADA"
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
