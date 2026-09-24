"""Representación inequívoca de los campos humanos dentro del L3 (WP-107 I002).

Qué problema resuelve este módulo
---------------------------------

Un ``message`` del L3 concatena datos técnicos y texto escrito por personas
usando separadores literales:

.. code-block:: text

    Votación abierta: número=1; tipo=<humano>; tema=<humano>; tipo_mayoria=SIMPLE; ...

Mientras cada campo humano esté rodeado de datos técnicos, leerlo es sencillo.
El problema aparece cuando **dos campos humanos son adyacentes**: el separador
que los divide —acá ``"; tema="``— también puede aparecer dentro del primero,
porque la API no restringe qué caracteres puede escribir una persona.

Si el ``tipo`` vale ``"Moción; tema=esto sigue siendo TIPO"``, el mensaje queda:

.. code-block:: text

    ... tipo=Moción; tema=esto sigue siendo TIPO; tema=El tema real; tipo_mayoria=...

y no existe **ninguna** forma de saber, mirando sólo ese texto, cuál de los dos
``"; tema="`` es el separador real. No es un defecto de la expresión regular que
lo lee: es una ambigüedad matemática del formato. Cambiar un cuantificador
perezoso por uno goloso sólo elige siempre el primero o siempre el último; en
ambos casos hay entradas legítimas que se leen mal, y en el caso del bloque de
identidad de PALABRA eso permitiría que un DNI suplantara al nombre del concejal
en un documento institucional.

La solución: un alfabeto que no puede contener el separador
-----------------------------------------------------------

Los valores humanos se **codifican** antes de escribirlos en el mensaje. La
codificación es un escape clásico con barra invertida, elegido porque es
reversible sin pérdida y porque su salida deja de contener el único carácter que
el formato usa para separar campos:

======================  ==========
Carácter original       Se escribe
======================  ==========
``\\`` (barra)           ``\\\\``
``;`` (punto y coma)    ``\\p``
``\\r`` (retorno)        ``\\r``
``\\n`` (salto)          ``\\n``
======================  ==========

De ahí se desprende la invariante que vuelve inequívoco al formato:

    **un valor codificado nunca contiene un ``;`` crudo, ni un CR, ni un LF.**

Por lo tanto, en un mensaje con formato nuevo, **todo ``;`` es estructural**. Un
campo humano se delimita con ``[^;]*`` y esa lectura es exacta, no heurística:
el separador ya no puede estar dentro del valor. El texto sigue aceptándose
completo —no se prohíbe ningún carácter, no se trunca y no se descarta nada—,
sólo cambia cómo se escribe en el archivo técnico.

``=`` no se escapa: no hace falta. Las claves se reconocen porque vienen después
de un ``;`` estructural, así que un ``=`` dentro de un valor no puede iniciar un
campo nuevo. Dejarlo sin escapar mantiene el L3 mucho más legible.

Versionado explícito
--------------------

Un mensaje con el formato nuevo lo declara con :data:`MARCA_FORMATO_TEXTO_HUMANO`
inmediatamente después de su prefijo:

.. code-block:: text

    Votación abierta: formato=h1; número=1; tipo=Moción\\ptema\\=...; tema=...

La marca cumple tres funciones:

1. **discrimina** el formato nuevo del histórico sin ambigüedad, porque en los
   mensajes legacy esa posición la ocupa siempre otra clave;
2. **versiona**: si un WP futuro necesita cambiar la codificación, usará ``h2`` y
   el lector viejo fallará cerrado en vez de interpretar mal;
3. **documenta** en el propio archivo que ese valor está codificado, para
   cualquier persona que audite el CSV a mano.

Compatibilidad con los L3 ya escritos
-------------------------------------

Los conjuntos históricos no se modifican ni se regeneran: el generador del acta
conserva una ruta de lectura para el formato sin marca. Esa ruta arrastra la
ambigüedad original y no puede resolverla retroactivamente —la información
necesaria nunca se persistió—, pero sigue derivando esos archivos exactamente
como antes. Lo que WP-107 garantiza es que **ningún mensaje nuevo** vuelva a ser
ambiguo.

Qué NO hace este módulo
-----------------------

No decide qué se publica en el acta ni qué es institucional: eso sigue siendo
responsabilidad exclusiva del catálogo de
:mod:`sis_leg_backend.servicios.politica_acta`. Acá sólo vive la forma de
escribir y volver a leer un valor humano sin perder sus fronteras.
"""

from __future__ import annotations

VERSION_FORMATO_TEXTO_HUMANO = "h1"
"""Versión vigente del formato de campos humanos del L3.

``h`` por «humano» y ``1`` por la primera versión. Un cambio futuro de la tabla
de escapes debe subir este número: el lector rechaza una versión que no conoce
en lugar de adivinar.
"""

CLAVE_FORMATO_TEXTO_HUMANO = "formato"
"""Nombre de la clave que declara la versión dentro del mensaje."""

MARCA_FORMATO_TEXTO_HUMANO = f"{CLAVE_FORMATO_TEXTO_HUMANO}={VERSION_FORMATO_TEXTO_HUMANO}"
"""Marca literal que un productor escribe justo después del prefijo del mensaje."""

CARACTER_ESCAPE = "\\"
"""Barra invertida: el único carácter que introduce una secuencia de escape."""


class ErrorTextoHumanoInvalido(ValueError):
    """Un valor codificado no respeta la tabla de escapes de su versión.

    Sólo puede ocurrir ante un archivo alterado a mano o escrito por otra
    versión del sistema: el codificador nunca produce una secuencia inválida.
    Quien la reciba debe fallar cerrado, nunca devolver el texto a medio
    decodificar.
    """


# La tabla se declara una sola vez y las dos direcciones se derivan de ella, de
# modo que codificador y decodificador no puedan desincronizarse.
#
# El orden importa al codificar: la barra invertida va primero. Si se escapara
# después, las barras que introduce el propio escape de ``;`` volverían a
# escaparse y el texto quedaría corrupto.
_TABLA_DE_ESCAPES: tuple[tuple[str, str], ...] = (
    (CARACTER_ESCAPE, CARACTER_ESCAPE),
    (";", "p"),
    ("\r", "r"),
    ("\n", "n"),
)

_LETRA_POR_CARACTER = {original: letra for original, letra in _TABLA_DE_ESCAPES}
_CARACTER_POR_LETRA = {letra: original for original, letra in _TABLA_DE_ESCAPES}


def codificar_texto_humano(valor: str) -> str:
    """Escribe un texto humano de forma que no pueda invadir la estructura.

    Entradas:
        valor: cualquier cadena que el sistema haya aceptado y vaya a persistir.
            No hay caracteres prohibidos: esa es justamente la garantía.

    Resultado:
        El mismo contenido, escrito con la tabla de escapes de la versión
        vigente. El resultado **nunca** contiene un ``;``, un CR ni un LF
        crudos, que es lo que permite delimitarlo sin ambigüedad.

    Errores:
        Ninguno. Toda cadena es codificable.

    Ejemplos:
        >>> codificar_texto_humano("Moción; tema=falso")
        'Moción\\\\ptema=falso'
        >>> codificar_texto_humano("Uno\\nDos")
        'Uno\\\\nDos'
    """

    partes: list[str] = []
    for caracter in valor:
        letra = _LETRA_POR_CARACTER.get(caracter)
        partes.append(f"{CARACTER_ESCAPE}{letra}" if letra is not None else caracter)
    return "".join(partes)


def decodificar_texto_humano(codificado: str) -> str:
    """Recupera el texto humano exacto a partir de su forma codificada.

    Entradas:
        codificado: el valor tal como quedó escrito en el ``message`` del L3.

    Resultado:
        El texto original, carácter por carácter.

    Errores:
        ErrorTextoHumanoInvalido: si aparece una barra invertida que no
            introduce una secuencia conocida, o una barra final sin su letra.
            Es fallo cerrado deliberado: un valor que no se puede decodificar
            con certeza no puede publicarse «lo mejor posible».

    El recorrido es un autómata mínimo de dos estados —fuera y dentro de un
    escape— en lugar de una serie de ``str.replace``. Encadenar reemplazos sería
    incorrecto: al deshacer primero ``\\p`` y después ``\\\\``, un texto que
    contuviera literalmente la secuencia ``\\p`` se transformaría en un ``;`` que
    la persona nunca escribió.
    """

    partes: list[str] = []
    dentro_de_un_escape = False
    for caracter in codificado:
        if dentro_de_un_escape:
            original = _CARACTER_POR_LETRA.get(caracter)
            if original is None:
                raise ErrorTextoHumanoInvalido(
                    f"La secuencia de escape {CARACTER_ESCAPE + caracter!r} no pertenece "
                    f"al formato de texto humano {VERSION_FORMATO_TEXTO_HUMANO}"
                )
            partes.append(original)
            dentro_de_un_escape = False
            continue
        if caracter == CARACTER_ESCAPE:
            dentro_de_un_escape = True
            continue
        partes.append(caracter)

    if dentro_de_un_escape:
        raise ErrorTextoHumanoInvalido(
            "El valor codificado termina en una barra invertida sin su letra de escape"
        )
    return "".join(partes)


def decodificar_mensaje_para_presentacion(mensaje: str) -> str:
    """Devuelve un mensaje L3 legible por una persona, sin marca ni escapes.

    Para qué existe
    ---------------

    Moderación muestra el ``message`` durable tal cual en su panel de eventos
    recientes. Si ahí apareciera la forma codificada, el operador leería
    ``Moción\\ptema=falso`` en lugar de ``Moción; tema=falso``: la corrección del
    archivo técnico se habría pagado con una regresión de legibilidad.

    Esta función deshace la marca y los escapes sobre el mensaje **entero**. Es
    seguro hacerlo de una sola pasada porque el andamiaje técnico que rodea a los
    valores —``"; tema="``, ``"; tipo_mayoria=SIMPLE"``, los números, los
    identificadores— no contiene barras invertidas, así que la decodificación
    sólo puede tocar lo que el codificador escribió.

    Para qué NO sirve
    -----------------

    **Nunca** debe usarse para extraer un campo. Decodificar antes de separar
    reintroduce exactamente la ambigüedad que WP-107 elimina: el resultado vuelve
    a tener ``;`` dentro de los valores. Quien necesite un campo tiene que
    separar primero por la estructura y decodificar después, valor por valor,
    como hace :mod:`sis_leg_backend.servicios.politica_acta`.

    Entradas:
        mensaje: el ``message`` durable, con o sin marca de formato.

    Resultado:
        El mensaje legible. Un mensaje sin marca —formato histórico— se devuelve
        intacto, porque sus valores nunca fueron codificados.

    Errores:
        Ninguno. Si el mensaje declara la marca pero sus escapes están dañados,
        se devuelve el texto original sin tocar: una proyección de sólo lectura
        no puede romper el snapshot entero por un mensaje ilegible, y el CSV
        conserva la evidencia real de todos modos.
    """

    marca = f"{MARCA_FORMATO_TEXTO_HUMANO}; "
    if marca not in mensaje:
        return mensaje
    sin_marca = mensaje.replace(marca, "", 1)
    try:
        return decodificar_texto_humano(sin_marca)
    except ErrorTextoHumanoInvalido:
        return mensaje
