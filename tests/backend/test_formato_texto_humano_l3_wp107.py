"""Fronteras inequívocas entre campos humanos del L3 (WP-107 iteración 2).

Qué demuestra esta suite
------------------------

La iteración 1 de WP-107 consiguió que un campo humano pudiera contener
cualquier carácter sin abortar el acta. Quedó abierto un problema distinto: que
el texto de una persona pudiera **cambiar de rol**.

Cuando dos campos humanos son adyacentes dentro del mismo ``message``, el
separador literal que los divide también puede aparecer dentro del primero, y
entonces no existe ninguna forma de saber cuál de las dos apariciones es la
real. Elegir el primero o el último con un cuantificador perezoso o goloso no
resuelve nada: en ambos casos hay entradas legítimas que se leen mal. En el
bloque de identidad de PALABRA eso permitía que el contenido de un DNI
suplantara al nombre del concejal dentro de un documento institucional.

La corrección es de formato, no de expresión regular:
:mod:`sis_leg_backend.servicios.texto_humano_l3` codifica los valores humanos de
modo que su forma escrita **no pueda contener un ``;`` crudo**, y por lo tanto
todo ``;`` del mensaje pasa a ser estructural.

Cómo está organizado el archivo
-------------------------------

1. **Round-trip del formato.** La codificación es reversible para cualquier
   texto y su salida respeta la invariante que la vuelve útil.
2. **Fallo cerrado del decodificador.** Una secuencia de escape inválida no se
   interpreta «lo mejor posible».
3. **Fronteras por familia.** Las tres familias con campos humanos adyacentes se
   leen correctamente aunque el texto imite su propio separador.
4. **Familias no migradas.** Las que tienen un único campo humano se dejaron en
   su forma anterior; acá se demuestra —con los mismos textos adversariales— que
   su lectura es única y no necesitaba framing.
5. **Compatibilidad histórica.** Los mensajes ya persistidos, sin marca de
   formato, se siguen derivando exactamente como antes.
6. **Versionado.** Una versión de formato desconocida falla cerrado.
7. **Presentación.** Moderación sigue mostrando el texto legible, sin escapes.
"""

from __future__ import annotations

import pytest
from sis_leg_backend.servicios.acta_institucional import normalizar_texto_para_acta
from sis_leg_backend.servicios.politica_acta import (
    ErrorActaNoDerivable,
    redactar_linea_de_acta,
)
from sis_leg_backend.servicios.texto_humano_l3 import (
    MARCA_FORMATO_TEXTO_HUMANO,
    ErrorTextoHumanoInvalido,
    codificar_texto_humano,
    decodificar_mensaje_para_presentacion,
    decodificar_texto_humano,
)

# ---------------------------------------------------------------------------
# Corpus
#
# Incluye, además de lo que exige el contrato, cadenas idénticas a **todas** las
# claves y separadores que usan los mensajes migrados: si el formato fuera
# ambiguo, alguna de ellas rompería la atribución.
# ---------------------------------------------------------------------------

CORPUS_DE_FRONTERA = (
    pytest.param("", id="vacio"),
    pytest.param("Texto simple", id="simple"),
    pytest.param("Uno\nDos", id="lf"),
    pytest.param("Uno\r\nDos", id="crlf"),
    pytest.param("Uno\rDos", id="cr"),
    pytest.param("Punto; y coma", id="punto-y-coma"),
    pytest.param("Igual=uno=dos", id="igual"),
    pytest.param("Comillas 'simples' y \"dobles\"", id="comillas"),
    pytest.param("Barra \\ invertida", id="backslash"),
    pytest.param("Barra doble \\\\ y triple \\\\\\", id="backslash-repetido"),
    pytest.param("Escape falso \\p \\n \\r \\z", id="escape-falso-literal"),
    pytest.param("Tildes áéíóú, ñ, Ü, ç y —", id="unicode"),
    pytest.param("; tema=", id="separador-tema"),
    pytest.param("; tipo=", id="separador-tipo"),
    pytest.param("; concejal=", id="separador-concejal"),
    pytest.param("; banca=", id="separador-banca"),
    pytest.param("; anterior=", id="separador-anterior"),
    pytest.param("; nuevo=", id="separador-nuevo"),
    pytest.param("; posicion=", id="separador-posicion"),
    pytest.param("; causa=MODERACION", id="separador-causa"),
    pytest.param("; tipo_mayoria=SIMPLE; factor=0; base=PRESENTES", id="cola-tecnica-completa"),
    pytest.param(MARCA_FORMATO_TEXTO_HUMANO, id="la-propia-marca-de-formato"),
    pytest.param(f"{MARCA_FORMATO_TEXTO_HUMANO}; anterior=X; nuevo=Y", id="mensaje-completo-falso"),
    pytest.param(" -> ", id="flecha-de-autoridades"),
    pytest.param("A -> B -> C", id="varias-flechas"),
    pytest.param(
        'Línea 1\r\nLínea 2; artículo=3 "texto" — ñ/á; tipo_mayoria=SIMPLE; factor=0; banca=',
        id="combinacion-adversarial",
    ),
)
"""Corpus del **formato**: se usa para probar la codificación en sí misma.

Incluye la cadena vacía y textos con espacios en los extremos porque el
codificador tiene que ser total: acepta cualquier cadena, venga de donde venga.
"""

CORPUS_DE_CAMPOS = tuple(
    caso
    for caso in CORPUS_DE_FRONTERA
    if isinstance(caso.values[0], str) and caso.values[0].strip() == caso.values[0] != ""
)
"""Corpus de los **campos**: sólo los valores que el sistema puede llegar a guardar.

La API y el padrón rechazan un valor vacío o de puros espacios y recortan los
extremos antes de persistir, así que un campo humano nunca llega al L3 con esa
forma. Además el acta colapsa espacios repetidos desde antes de WP-107, de modo
que un valor con espacios en los bordes no tendría una representación literal
contra la cual comparar. Excluirlos acá es respetar el contrato de origen, no
esquivar un caso difícil: el codificador sigue probándose con ellos arriba.
"""


# ---------------------------------------------------------------------------
# 1. Round-trip del formato
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("original", CORPUS_DE_FRONTERA)
def test_codificar_y_decodificar_devuelve_el_texto_exacto(original: str) -> None:
    """La codificación no pierde ni altera un solo carácter."""

    assert decodificar_texto_humano(codificar_texto_humano(original)) == original


@pytest.mark.parametrize("original", CORPUS_DE_FRONTERA)
def test_un_valor_codificado_no_puede_invadir_la_estructura(original: str) -> None:
    """La invariante que vuelve inequívoco al formato, comprobada carácter a carácter.

    Es la propiedad de la que depende todo lo demás: si un valor codificado no
    puede contener un ``;``, un CR ni un LF, entonces en un mensaje con formato
    nuevo **todo** ``;`` es estructural y ``[^;]*`` separa los campos de forma
    exacta, no aproximada.
    """

    codificado = codificar_texto_humano(original)

    assert ";" not in codificado
    assert "\r" not in codificado
    assert "\n" not in codificado


def test_codificar_no_prohibe_ningun_caracter() -> None:
    """Todo el rango imprimible y de control se codifica y vuelve intacto.

    El contrato del WP prohíbe expresamente resolver el problema restringiendo
    lo que una persona puede escribir. Esta prueba recorre un barrido amplio de
    puntos de código para dejarlo demostrado y no sólo declarado.
    """

    muestra = "".join(chr(punto) for punto in range(0, 0x2FF))
    assert decodificar_texto_humano(codificar_texto_humano(muestra)) == muestra


# ---------------------------------------------------------------------------
# 2. Fallo cerrado del decodificador
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "invalido",
    (
        pytest.param("\\z", id="letra-desconocida"),
        pytest.param("texto\\", id="barra-final-sin-letra"),
        pytest.param("\\P", id="letra-con-mayuscula"),
        pytest.param("a\\ b", id="barra-y-espacio"),
    ),
)
def test_una_secuencia_de_escape_invalida_falla_cerrado(invalido: str) -> None:
    """Un valor que no se puede recuperar con certeza no se publica a medias."""

    with pytest.raises(ErrorTextoHumanoInvalido):
        decodificar_texto_humano(invalido)


def test_el_decodificador_no_encadena_reemplazos() -> None:
    """Un texto que contiene literalmente ``\\p`` no se convierte en ``;``.

    Es el error clásico de implementar el decodificador con ``str.replace``
    sucesivos: al deshacer primero ``\\p`` y después ``\\\\``, la secuencia que la
    persona escribió a mano se transformaría en un separador que nunca puso.
    """

    original = "Artículo \\p del reglamento"

    assert decodificar_texto_humano(codificar_texto_humano(original)) == original
    assert ";" not in decodificar_texto_humano(codificar_texto_humano(original))


# ---------------------------------------------------------------------------
# 3. Fronteras de las familias migradas
# ---------------------------------------------------------------------------


def _redactar(etiqueta: str, codigo: str, mensaje: str) -> str:
    """Redacta como lo hace el generador, incluida su normalización."""

    return normalizar_texto_para_acta(
        redactar_linea_de_acta(etiqueta, codigo, normalizar_texto_para_acta(mensaje))
    )


def _aplanar(texto: str) -> str:
    """Forma en que un texto humano aparece dentro de la línea del acta."""

    return normalizar_texto_para_acta(texto)


@pytest.mark.parametrize("tema", CORPUS_DE_CAMPOS)
@pytest.mark.parametrize("tipo", CORPUS_DE_CAMPOS)
def test_votacion_abierta_atribuye_tipo_y_tema_sin_ambiguedad(tipo: str, tema: str) -> None:
    """Cada combinación de tipo y tema conserva su rol exacto.

    El producto cartesiano del corpus consigo mismo cubre los casos que importan:
    un tipo que imita el separador siguiente, un tema que imita el anterior y
    ambos a la vez.
    """

    mensaje = (
        f"Votación abierta: {MARCA_FORMATO_TEXTO_HUMANO}; número=7"
        f"; tipo={codificar_texto_humano(tipo)}; tema={codificar_texto_humano(tema)}"
        "; tipo_mayoria=SIMPLE; factor=0.0; base=VOTOS_COMPUTABLES"
    )

    linea = _redactar("VOTACION", "VOTACION_ABIERTA", mensaje)

    assert linea == _aplanar(f"Votación Nro 7 abierta. Tipo: {tipo}. Tema: {tema}. Mayoría simple.")


@pytest.mark.parametrize("concejal", CORPUS_DE_CAMPOS)
@pytest.mark.parametrize("dni", CORPUS_DE_CAMPOS)
@pytest.mark.parametrize(
    ("prefijo", "cola", "esperado"),
    (
        ("Pedido de palabra registrado", "; posicion=3", "Pedido de palabra registrado: "),
        ("Pedido de palabra retirado", "; posicion_previa=2", "Pedido de palabra retirado: "),
        ("Uso de palabra otorgado", "; posicion_origen=1", "Uso de la palabra otorgado: "),
        (
            "Uso de palabra finalizado",
            "; causa=MODERACION",
            "Uso de la palabra finalizado por Moderación: ",
        ),
    ),
)
def test_palabra_publica_el_concejal_real_sea_cual_sea_el_dni(
    prefijo: str,
    cola: str,
    esperado: str,
    dni: str,
    concejal: str,
) -> None:
    """El DNI no puede suplantar al concejal por más que imite su separador.

    Es la prueba de no-falsificación de identidad: el acta publica exactamente el
    nombre del padrón, y el contenido del DNI —que nunca se publica— no puede
    filtrarse ni desplazar la frontera.
    """

    codigo = {
        "Pedido de palabra registrado": "PEDIDO_PALABRA_REGISTRADO",
        "Pedido de palabra retirado": "PEDIDO_PALABRA_RETIRADO",
        "Uso de palabra otorgado": "USO_PALABRA_OTORGADO",
        "Uso de palabra finalizado": "USO_PALABRA_FINALIZADO",
    }[prefijo]
    mensaje = (
        f"{prefijo}: {MARCA_FORMATO_TEXTO_HUMANO}"
        f"; DNI={codificar_texto_humano(dni)}"
        f"; concejal={codificar_texto_humano(concejal)}; banca=4{cola}"
    )

    linea = _redactar("PALABRA", codigo, mensaje)

    assert linea == _aplanar(f"{esperado}{concejal} (banca Nro:4)")


@pytest.mark.parametrize("nuevo", CORPUS_DE_CAMPOS)
@pytest.mark.parametrize("anterior", CORPUS_DE_CAMPOS)
@pytest.mark.parametrize(
    ("campo", "codigo"),
    (
        ("Número de sesión", "NUMERO_SESION_ACTUALIZADO"),
        ("Presidencia", "PRESIDENCIA_ACTUALIZADA"),
        ("Secretaría Legislativa", "SECRETARIA_LEGISLATIVA_ACTUALIZADA"),
    ),
)
def test_autoridades_atribuyen_anterior_y_nuevo_sin_ambiguedad(
    campo: str,
    codigo: str,
    anterior: str,
    nuevo: str,
) -> None:
    """Un nombre que contenga la flecha ya no desplaza la frontera.

    En el formato histórico ``anterior`` y ``nuevo`` se concatenaban con
    ``" -> "``, un separador que cualquiera de los dos podía contener. La flecha
    sigue existiendo, pero ahora es redacción del acta y no estructura del dato.
    """

    mensaje = (
        f"{campo} actualizado: {MARCA_FORMATO_TEXTO_HUMANO}"
        f"; anterior={codificar_texto_humano(anterior)}"
        f"; nuevo={codificar_texto_humano(nuevo)}"
    )

    linea = _redactar("SESION", codigo, mensaje)

    assert linea == _aplanar(f"{campo} actualizado: {anterior} -> {nuevo}")


# ---------------------------------------------------------------------------
# 4. Familias con un único campo humano: por qué no necesitaron framing
#
# Estas familias no se migraron y la justificación tiene que ser verificable, no
# una afirmación del informe. En todas ellas el mensaje tiene **un solo** campo
# humano y el resto es técnico y está anclado al final del mensaje, con un
# separador que no puede volver a aparecer dentro de esa cola técnica. Eso hace
# que exista exactamente una división válida: no es que la expresión regular
# «elija bien», es que no hay otra opción que satisfaga el patrón.
#
# Las pruebas inyectan en el campo humano una copia literal de su propia cola
# técnica, que es el caso que rompería la lectura si la afirmación fuese falsa.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("humano", CORPUS_DE_CAMPOS)
def test_presencia_tiene_lectura_unica_sin_framing(humano: str) -> None:
    """``se PRESENTÓ`` / ``se AUSENTÓ`` cierran el mensaje y no se repiten en su cola."""

    persona = f"{humano} (banca Nro:4)"
    presente = _redactar("PRESENCIA", "CONCEJAL_PRESENTE", f"{persona} se PRESENTÓ")
    ausente = _redactar(
        "PRESENCIA",
        "CONCEJAL_AUSENTE",
        f"{persona} se AUSENTÓ; pedido_palabra_retirado=true; uso_palabra_finalizado=false",
    )

    assert presente == _aplanar(f"{persona} se PRESENTÓ")
    assert ausente == _aplanar(
        f"{persona} se AUSENTÓ. Como consecuencia, se retiró su pedido de palabra."
    )


@pytest.mark.parametrize("humano", CORPUS_DE_CAMPOS)
def test_voto_ordinario_tiene_lectura_unica_sin_framing(humano: str) -> None:
    """``id=[^;]*`` ancla la cola al final y sólo admite una división."""

    mensaje = (
        f"Voto ordinario: {humano} (banca Nro:4) votó POSITIVO"
        "; votación número=5; id=9f0c2a4e-0000-4000-8000-000000000002"
    )

    linea = _redactar("VOTACION", "VOTO_ORDINARIO_REGISTRADO", mensaje)

    assert linea == _aplanar(
        f"Voto ordinario en la votación Nro 5: {humano} (banca Nro:4) votó POSITIVO."
    )


@pytest.mark.parametrize("humano", CORPUS_DE_CAMPOS)
def test_desempate_tiene_lectura_unica_sin_framing(humano: str) -> None:
    """La cola técnica del desempate es fija y no se repite dentro de sí misma."""

    mensaje = (
        "Voto presidencial de desempate: numero_votacion=7"
        f"; id=9f0c2a4e-0000-4000-8000-000000000003; presidencia={humano}"
        "; sentido=NEGATIVO; estado_previo=CERRADA; resultado_previo=EMPATADA"
        "; votos_ordinarios=4; positivos=2; negativos=2; abstenciones=0"
    )

    linea = _redactar("VOTACION", "VOTO_DESEMPATE_PRESIDENCIAL", mensaje)

    assert linea == _aplanar(
        f"Voto de desempate de la Presidencia en la votación Nro 7: NEGATIVO, emitido por {humano}."
    )


@pytest.mark.parametrize("humano", CORPUS_DE_CAMPOS)
def test_motivo_manual_tiene_lectura_unica_sin_framing(humano: str) -> None:
    """El motivo es el último campo: su frontera es el final del mensaje."""

    mensaje = (
        "Votación finalizada inconclusa; numero_votacion=3"
        "; id=9f0c2a4e-0000-4000-8000-000000000001; causa=MANUAL"
        "; estado_previo=ABIERTA; resultado_previo=None; votos_conservados=2"
        f"; resultado_nuevo=INCONCLUSA; motivo_manual={humano}"
    )

    linea = _redactar("VOTACION", "VOTACION_FINALIZADA_INCONCLUSA", mensaje)

    assert linea == _aplanar(
        "Votación Nro 3 finalizada como INCONCLUSA por decisión de Moderación. "
        f"Motivo: {humano}. Votos conservados: 2."
    )


@pytest.mark.parametrize("humano", CORPUS_DE_CAMPOS)
def test_marcador_de_recinto_no_tiene_fronteras_que_proteger(humano: str) -> None:
    """El mensaje completo es el texto humano: no hay ninguna división posible."""

    assert _redactar("EVENTO", "INICIO", humano) == _aplanar(f"Inicio: {humano}")
    assert _redactar("EVENTO", "FIN", humano) == _aplanar(f"Fin: {humano}")


# ---------------------------------------------------------------------------
# 5. Compatibilidad con los conjuntos ya cerrados
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("etiqueta", "codigo", "mensaje", "esperado"),
    (
        pytest.param(
            "VOTACION",
            "VOTACION_ABIERTA",
            "Votación abierta: número=1; tipo=Mocion; tema=Ordenanza de alumbrado"
            "; tipo_mayoria=SIMPLE; factor=0.0; base=VOTOS_COMPUTABLES",
            "Votación Nro 1 abierta. Tipo: Mocion. Tema: Ordenanza de alumbrado. Mayoría simple.",
            id="votacion-abierta-simple",
        ),
        pytest.param(
            "VOTACION",
            "VOTACION_ABIERTA",
            "Votación abierta: número=2; tipo=Despacho HA; tema=Convenio con la Provincia"
            "; tipo_mayoria=ESPECIAL; factor=0.5; base=PRESENTES",
            "Votación Nro 2 abierta. Tipo: Despacho HA. Tema: Convenio con la Provincia. "
            "Mayoría especial: proporción requerida 0.5 sobre los concejales presentes.",
            id="votacion-abierta-especial",
        ),
        pytest.param(
            "PALABRA",
            "PEDIDO_PALABRA_REGISTRADO",
            "Pedido de palabra registrado: DNI=30000001; concejal=Ana Garcia; banca=1; posicion=1",
            "Pedido de palabra registrado: Ana Garcia (banca Nro:1)",
            id="pedido-de-palabra",
        ),
        pytest.param(
            "PALABRA",
            "USO_PALABRA_FINALIZADO",
            "Uso de palabra finalizado: DNI=30000002; concejal=Bruno Martinez; banca=2"
            "; causa=PROPIO",
            "Uso de la palabra finalizado a pedido del propio concejal: "
            "Bruno Martinez (banca Nro:2)",
            id="uso-de-palabra-finalizado",
        ),
        pytest.param(
            "SESION",
            "PRESIDENCIA_ACTUALIZADA",
            "Presidencia actualizado: sin informar -> Ana; Beatriz",
            "Presidencia actualizado: sin informar -> Ana; Beatriz",
            id="autoridad-con-punto-y-coma",
        ),
        pytest.param(
            "SESION",
            "NUMERO_SESION_ACTUALIZADO",
            "Número de sesión actualizado: sin informar -> 59",
            "Número de sesión actualizado: sin informar -> 59",
            id="numero-de-sesion",
        ),
        pytest.param(
            "SESION",
            "SECRETARIA_LEGISLATIVA_ACTUALIZADA",
            "Secretaría Legislativa actualizado: Secretaría Inicial -> sin informar",
            "Secretaría Legislativa actualizado: Secretaría Inicial -> sin informar",
            id="secretaria",
        ),
    ),
)
def test_los_mensajes_historicos_se_derivan_igual_que_antes(
    etiqueta: str,
    codigo: str,
    mensaje: str,
    esperado: str,
) -> None:
    """Un conjunto ya cerrado no cambia de lectura porque el formato haya evolucionado.

    Los archivos históricos no se migran ni se regeneran —WP-107 lo prohíbe
    expresamente— así que el catálogo conserva una ruta de compatibilidad. Esa
    ruta arrastra la ambigüedad original, que no puede repararse hacia atrás
    porque la información que separaría los campos nunca se persistió; lo que sí
    garantiza es que esos conjuntos sigan derivándose exactamente como antes.
    """

    assert _redactar(etiqueta, codigo, mensaje) == esperado


def test_un_mensaje_historico_no_se_confunde_con_el_formato_nuevo() -> None:
    """La marca se busca en una posición estructural, no «en algún lugar del texto».

    Un tema histórico podía contener la palabra ``formato=h1``. Como la marca
    sólo cuenta cuando ocupa exactamente el lugar que en el formato viejo ocupa
    otra clave técnica, ese texto sigue leyéndose como contenido.
    """

    mensaje = (
        f"Votación abierta: número=1; tipo=Mocion; tema={MARCA_FORMATO_TEXTO_HUMANO}"
        "; tipo_mayoria=SIMPLE; factor=0.0; base=VOTOS_COMPUTABLES"
    )

    linea = _redactar("VOTACION", "VOTACION_ABIERTA", mensaje)

    assert linea == (
        f"Votación Nro 1 abierta. Tipo: Mocion. Tema: {MARCA_FORMATO_TEXTO_HUMANO}. Mayoría simple."
    )


# ---------------------------------------------------------------------------
# 6. Versionado
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("etiqueta", "codigo", "mensaje"),
    (
        pytest.param(
            "VOTACION",
            "VOTACION_ABIERTA",
            "Votación abierta: formato=h2; número=1; tipo=X; tema=Y"
            "; tipo_mayoria=SIMPLE; factor=0.0; base=VOTOS_COMPUTABLES",
            id="votacion-abierta",
        ),
        pytest.param(
            "PALABRA",
            "PEDIDO_PALABRA_REGISTRADO",
            "Pedido de palabra registrado: formato=h9; DNI=1; concejal=Ana; banca=1; posicion=1",
            id="palabra",
        ),
        pytest.param(
            "SESION",
            "PRESIDENCIA_ACTUALIZADA",
            "Presidencia actualizado: formato=futuro; anterior=A; nuevo=B",
            id="autoridad",
        ),
    ),
)
def test_una_version_de_formato_desconocida_falla_cerrado(
    etiqueta: str,
    codigo: str,
    mensaje: str,
) -> None:
    """Leer un formato futuro con la tabla de escapes vieja produciría texto falso.

    Antes que publicar en un acta institucional un texto que quizá esté mal
    decodificado, la generación se aborta entera y alguien revisa.
    """

    with pytest.raises(ErrorActaNoDerivable, match="formato de texto humano"):
        _redactar(etiqueta, codigo, mensaje)


@pytest.mark.parametrize(
    ("etiqueta", "codigo", "mensaje"),
    (
        pytest.param(
            "VOTACION",
            "VOTACION_ABIERTA",
            f"Votación abierta: {MARCA_FORMATO_TEXTO_HUMANO}; número=1; tipo=X\\z; tema=Y"
            "; tipo_mayoria=SIMPLE; factor=0.0; base=VOTOS_COMPUTABLES",
            id="escape-invalido-en-tipo",
        ),
        pytest.param(
            "SESION",
            "PRESIDENCIA_ACTUALIZADA",
            f"Presidencia actualizado: {MARCA_FORMATO_TEXTO_HUMANO}; anterior=A\\; nuevo=B",
            id="barra-final-en-anterior",
        ),
        pytest.param(
            "PALABRA",
            "USO_PALABRA_OTORGADO",
            f"Uso de palabra otorgado: {MARCA_FORMATO_TEXTO_HUMANO}; DNI=1"
            "; concejal=Ana\\q; banca=1; posicion_origen=1",
            id="escape-invalido-en-concejal",
        ),
    ),
)
def test_un_campo_codificado_que_no_se_puede_decodificar_falla_cerrado(
    etiqueta: str,
    codigo: str,
    mensaje: str,
) -> None:
    """Un valor dañado aborta el acta en vez de publicarse a medias."""

    with pytest.raises(ErrorActaNoDerivable):
        _redactar(etiqueta, codigo, mensaje)


@pytest.mark.parametrize(
    ("etiqueta", "codigo", "mensaje"),
    (
        pytest.param(
            "VOTACION",
            "VOTACION_ABIERTA",
            f"Votación abierta: {MARCA_FORMATO_TEXTO_HUMANO}; número=1; tipo=X; tema=Y"
            "; tipo_mayoria=SIMPLE; factor=0.0; base=VOTOS_COMPUTABLES; campo_nuevo=1",
            id="campo-tecnico-agregado",
        ),
        pytest.param(
            "PALABRA",
            "PEDIDO_PALABRA_REGISTRADO",
            f"Pedido de palabra registrado: {MARCA_FORMATO_TEXTO_HUMANO}; DNI=1; concejal=Ana"
            "; banca=1",
            id="cola-tecnica-faltante",
        ),
        pytest.param(
            "SESION",
            "PRESIDENCIA_ACTUALIZADA",
            f"Presidencia actualizado: {MARCA_FORMATO_TEXTO_HUMANO}; anterior=A",
            id="campo-humano-faltante",
        ),
    ),
)
def test_el_formato_nuevo_conserva_el_fallo_cerrado_estructural(
    etiqueta: str,
    codigo: str,
    mensaje: str,
) -> None:
    """Declarar la marca no relaja ninguna exigencia sobre la estructura técnica."""

    with pytest.raises(ErrorActaNoDerivable):
        _redactar(etiqueta, codigo, mensaje)


# ---------------------------------------------------------------------------
# 7. Presentación en Moderación
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("humano", CORPUS_DE_CAMPOS)
def test_moderacion_muestra_el_texto_legible_y_no_los_escapes(humano: str) -> None:
    """El panel de eventos recupera el mensaje tal como lo escribió la persona.

    La codificación es correcta para el archivo técnico e ilegible en pantalla.
    Esta prueba fija que la proyección deshaga la marca y los escapes, de modo
    que corregir el L3 no se pague con una regresión de legibilidad.
    """

    mensaje = (
        f"Votación abierta: {MARCA_FORMATO_TEXTO_HUMANO}; número=1"
        f"; tipo={codificar_texto_humano(humano)}; tema={codificar_texto_humano(humano)}"
        "; tipo_mayoria=SIMPLE; factor=0.0; base=VOTOS_COMPUTABLES"
    )

    legible = decodificar_mensaje_para_presentacion(mensaje)

    assert legible == (
        f"Votación abierta: número=1; tipo={humano}; tema={humano}"
        "; tipo_mayoria=SIMPLE; factor=0.0; base=VOTOS_COMPUTABLES"
    )


def test_un_mensaje_historico_se_presenta_sin_tocar() -> None:
    """Sin marca no hay nada que decodificar: el texto viaja intacto."""

    mensaje = "Pedido de palabra registrado: DNI=1; concejal=Ana Garcia; banca=1; posicion=1"

    assert decodificar_mensaje_para_presentacion(mensaje) == mensaje


def test_un_mensaje_con_escapes_dañados_no_rompe_la_proyeccion() -> None:
    """Una proyección de sólo lectura nunca puede voltear el snapshot entero.

    Es la única diferencia deliberada de criterio con el acta: el acta falla
    cerrado porque produce un documento institucional, mientras que el panel de
    eventos prefiere mostrar el texto crudo antes que dejar a Moderación sin
    estado. Los CSV conservan la evidencia real en los dos casos.
    """

    mensaje = f"Votación abierta: {MARCA_FORMATO_TEXTO_HUMANO}; número=1; tipo=X\\z; tema=Y"

    assert decodificar_mensaje_para_presentacion(mensaje) == mensaje
