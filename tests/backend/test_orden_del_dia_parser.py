"""Pruebas unitarias exhaustivas del parser canónico de Orden del Día (WP-016).

Verifica todas las reglas de negocio y restricciones técnicas de DT-039 y WP-016:
- Validación y rechazo de encabezados (exactitud, orden, columnas faltantes/sobrantes).
- Incompatibilidad deliberada con el formato histórico de 5 columnas.
- Soporte de UTF-8 con y sin BOM.
- Quoting CSV estándar con comas y comillas en textos descriptivos.
- Manejo de archivos de 0 bytes y archivos con solo encabezado (colección vacía).
- Validación de nro_votacion (entero estricto >= 1, repetidos, desordenados, rechazo de
  decimales/negativos/0/texto).
- Mayoría SIMPLE: factor 0/vacío, base vacía/VOTOS_COMPUTABLES, rechazo de factores != 0,
  NaN, infinitos y otras bases.
- Mayoría ESPECIAL: factor finito > 0 y <= 1, bases canónicas válidas, rechazo de factores
  <= 0, > 1, NaN, inf y bases inválidas/vacías.
- Normalización case-insensitive de enumerados.
- Atomicidad: cualquier fila defectuosa produce rechazo total sin resultados parciales.
"""

from __future__ import annotations

import pytest
from sis_leg_backend.dominio.errores import ErrorOrdenDelDiaInvalido
from sis_leg_backend.dominio.orden_del_dia import (
    PuntoOrdenDelDia,
    normalizar_tipo_para_comparacion,
    parsear_orden_del_dia,
)
from sis_leg_backend.dominio.votacion import BaseMayoria, TipoMayoria


@pytest.mark.parametrize(
    ("tipo", "clave_esperada"),
    [
        ("Ratificación", "ratificacion"),
        ("RATIFICACIÓN", "ratificacion"),
        ("Ratificacio\u0301n", "ratificacion"),
        ("  Despacho\t\u2003  OP\n", "despacho op"),
        (" \tRATIFICACIO\u0301N   ESPECIAL ", "ratificacion especial"),
    ],
)
def test_normalizador_tipo_ignora_case_diacriticos_y_whitespace(
    tipo: str,
    clave_esperada: str,
) -> None:
    """Demuestra cada tolerancia aislada y su combinación sobre texto Unicode."""

    assert normalizar_tipo_para_comparacion(tipo) == clave_esperada


# ==============================================================================
# 1. ENCABEZADO Y FORMATO BASE
# ==============================================================================


def test_encabezado_exacto_valido() -> None:
    """Demuestra que el encabezado canónico de seis columnas es aceptado."""
    csv_bytes = (
        b"nro_votacion,tipo,tema,tipo_mayoria,factor,base\n"
        b"1,Despacho,Tema 1,SIMPLE,0,VOTOS_COMPUTABLES\n"
    )
    puntos = parsear_orden_del_dia(csv_bytes)
    assert len(puntos) == 1
    assert puntos[0] == PuntoOrdenDelDia(
        nro_votacion=1,
        tipo="Despacho",
        tema="Tema 1",
        tipo_mayoria=TipoMayoria.SIMPLE,
        factor=0.0,
        base=BaseMayoria.VOTOS_COMPUTABLES,
    )


def test_encabezado_con_columnas_fuera_de_orden_es_invalido() -> None:
    """Demuestra que columnas en orden distinto son rechazadas."""
    csv_bytes = (
        b"tipo,nro_votacion,tema,tipo_mayoria,factor,base\n"
        b"Despacho,1,Tema 1,SIMPLE,0,VOTOS_COMPUTABLES\n"
    )
    with pytest.raises(ErrorOrdenDelDiaInvalido, match="Encabezado CSV inválido"):
        parsear_orden_del_dia(csv_bytes)


def test_encabezado_con_columna_faltante_es_invalido() -> None:
    """Demuestra que un encabezado con menos de seis columnas es rechazado."""
    csv_bytes = b"nro_votacion,tipo,tema,tipo_mayoria,factor\n1,Despacho,Tema 1,SIMPLE,0\n"
    with pytest.raises(ErrorOrdenDelDiaInvalido, match="Encabezado CSV inválido"):
        parsear_orden_del_dia(csv_bytes)


def test_encabezado_con_columna_extra_es_invalido() -> None:
    """Demuestra que un encabezado con columnas adicionales es rechazado."""
    csv_bytes = (
        b"nro_votacion,tipo,tema,tipo_mayoria,factor,base,extra\n"
        b"1,Despacho,Tema 1,SIMPLE,0,VOTOS_COMPUTABLES,extra\n"
    )
    with pytest.raises(ErrorOrdenDelDiaInvalido, match="Encabezado CSV inválido"):
        parsear_orden_del_dia(csv_bytes)


def test_formato_historico_cinco_columnas_es_rechazado() -> None:
    """Demuestra el rechazo terminante del formato histórico de 5 columnas (DT-039)."""
    csv_bytes = (
        b"nro_votacion,tipo,tema,factor_de_mayoria,respecto\n"
        b"1,Despacho,Tema 1,0,votos_computables\n"
    )
    with pytest.raises(ErrorOrdenDelDiaInvalido, match="Encabezado CSV inválido"):
        parsear_orden_del_dia(csv_bytes)


def test_utf8_con_bom_es_aceptado_y_descarta_bom_inicial() -> None:
    """Demuestra que un archivo UTF-8 con BOM inicial se procesa correctamente."""
    csv_bytes = (
        b"\xef\xbb\xbfnro_votacion,tipo,tema,tipo_mayoria,factor,base\n"
        b"1,Despacho,Tema con BOM,SIMPLE,,\n"
    )
    puntos = parsear_orden_del_dia(csv_bytes)
    assert len(puntos) == 1
    assert puntos[0].nro_votacion == 1
    assert puntos[0].tema == "Tema con BOM"


def test_bytes_no_utf8_son_rechazados() -> None:
    """Demuestra que bytes no decodificables como UTF-8 son rechazados."""
    csv_bytes = b"\xff\xfe\x00\x00nro_votacion,tipo,tema,tipo_mayoria,factor,base\n"
    with pytest.raises(ErrorOrdenDelDiaInvalido, match="no es texto UTF-8 válido"):
        parsear_orden_del_dia(csv_bytes)


# ==============================================================================
# 2. ARCHIVOS VACÍOS Y COLECCIÓN VACÍA
# ==============================================================================


def test_archivo_cero_bytes_es_invalido() -> None:
    """Demuestra que un archivo de 0 bytes se considera inválido."""
    with pytest.raises(ErrorOrdenDelDiaInvalido, match="está vacío"):
        parsear_orden_del_dia(b"")


def test_archivo_solo_espacios_es_invalido() -> None:
    """Demuestra que un archivo con solo espacios o saltos de línea es inválido."""
    with pytest.raises(ErrorOrdenDelDiaInvalido, match="no contiene datos interpretables"):
        parsear_orden_del_dia(b"   \n\r\n   ")


def test_encabezado_canonico_sin_filas_devuelve_coleccion_vacia() -> None:
    """Demuestra que un encabezado canónico con 0 filas normaliza a puntos=[]."""
    csv_bytes = b"nro_votacion,tipo,tema,tipo_mayoria,factor,base\n"
    puntos = parsear_orden_del_dia(csv_bytes)
    assert puntos == ()


# ==============================================================================
# 3. CSV QUOTING Y CARACTERES ESPECIALES
# ==============================================================================


def test_quoting_estandar_con_comas_en_tema_y_tipo() -> None:
    """Demuestra que comas dentro de campos entrecomillados se preservan."""
    csv_bytes = (
        b"nro_votacion,tipo,tema,tipo_mayoria,factor,base\n"
        b'1,"Despacho, Especial","Tema con, comas y punto, y coma;",SIMPLE,0,VOTOS_COMPUTABLES\n'
    )
    puntos = parsear_orden_del_dia(csv_bytes)
    assert len(puntos) == 1
    assert puntos[0].tipo == "Despacho, Especial"
    assert puntos[0].tema == "Tema con, comas y punto, y coma;"


def test_quoting_con_comillas_dobles_escapadas() -> None:
    """Demuestra que las comillas dobles estándar de CSV se interpretan bien."""
    csv_bytes = (
        b"nro_votacion,tipo,tema,tipo_mayoria,factor,base\n"
        b'1,Despacho,"Proyecto de Ordenanza sobre ""Transporte""",SIMPLE,,\n'
    )
    puntos = parsear_orden_del_dia(csv_bytes)
    assert len(puntos) == 1
    assert puntos[0].tema == 'Proyecto de Ordenanza sobre "Transporte"'


def test_fila_con_cantidad_incorrecta_de_columnas_es_rechazada() -> None:
    """Demuestra que una fila con menos o más columnas es rechazada."""
    csv_bytes = b"nro_votacion,tipo,tema,tipo_mayoria,factor,base\n1,Despacho,Tema 1,SIMPLE,0\n"
    with pytest.raises(ErrorOrdenDelDiaInvalido, match="cantidad incorrecta de columnas"):
        parsear_orden_del_dia(csv_bytes)


# ==============================================================================
# 4. VALIDACIÓN DE NRO_VOTACION
# ==============================================================================


@pytest.mark.parametrize("nro_valido", [1, 2, 59, 9999])
def test_nro_votacion_enteros_validos(nro_valido: int) -> None:
    """Demuestra que cualquier entero estricto >= 1 es aceptado."""
    csv_bytes = (
        f"nro_votacion,tipo,tema,tipo_mayoria,factor,base\n{nro_valido},Tipo,Tema,SIMPLE,,\n"
    ).encode()
    puntos = parsear_orden_del_dia(csv_bytes)
    assert len(puntos) == 1
    assert puntos[0].nro_votacion == nro_valido


def test_nro_votacion_repetidos_y_desordenados_son_validos() -> None:
    """Demuestra que el parser no exige secuencia ni unicidad en nro_votacion."""
    csv_bytes = (
        b"nro_votacion,tipo,tema,tipo_mayoria,factor,base\n"
        b"10,Tipo A,Tema 10,SIMPLE,,\n"
        b"5,Tipo B,Tema 5,SIMPLE,,\n"
        b"10,Tipo C,Tema 10 duplicado,SIMPLE,,\n"
        b"1,Tipo D,Tema 1,SIMPLE,,\n"
    )
    puntos = parsear_orden_del_dia(csv_bytes)
    assert len(puntos) == 4
    assert [p.nro_votacion for p in puntos] == [10, 5, 10, 1]


@pytest.mark.parametrize(
    "nro_invalido",
    [
        "0",
        "-1",
        "-10",
        "+1",
        "1.0",
        "1.5",
        "abc",
        "True",
        "False",
        "",
        "²",
        "³",
        "¹",
        "½",
        "٣",
        "①",
    ],
)
def test_nro_votacion_invalido_es_rechazado(nro_invalido: str) -> None:
    """Demuestra que negativos, signos, decimales, texto, vacío y no-ASCII son rechazados."""
    csv_bytes = (
        f"nro_votacion,tipo,tema,tipo_mayoria,factor,base\n{nro_invalido},Tipo,Tema,SIMPLE,,\n"
    ).encode()
    with pytest.raises(ErrorOrdenDelDiaInvalido, match="nro_votacion"):
        parsear_orden_del_dia(csv_bytes)


def test_nro_votacion_unicode_superindice_no_genera_value_error_inesperado() -> None:
    """Demuestra que '²' no escapa como ValueError sino como ErrorOrdenDelDiaInvalido."""
    csv_bytes = (
        b"nro_votacion,tipo,tema,tipo_mayoria,factor,base\n\xc2\xb2,Despacho,Tema,SIMPLE,,\n"
    )
    with pytest.raises(ErrorOrdenDelDiaInvalido, match="nro_votacion"):
        parsear_orden_del_dia(csv_bytes)


# ==============================================================================
# 5. MAYORÍA SIMPLE
# ==============================================================================


@pytest.mark.parametrize(
    ("factor_crudo", "base_cruda"),
    [
        ("", ""),
        ("0", ""),
        ("0.0", ""),
        ("0.00", ""),
        ("-0.0", ""),
        ("", "VOTOS_COMPUTABLES"),
        ("", "votos_computables"),
        ("0", "Votos_Computables"),
        ("0.0", "VOTOS_COMPUTABLES"),
    ],
)
def test_mayoria_simple_entradas_validas_normalizan_a_factor_cero_y_votos_computables(
    factor_crudo: str,
    base_cruda: str,
) -> None:
    """Demuestra que SIMPLE normaliza siempre a factor=0.0 y base=VOTOS_COMPUTABLES."""
    csv_bytes = (
        f"nro_votacion,tipo,tema,tipo_mayoria,factor,base\n"
        f"1,Despacho,Tema Simple,SIMPLE,{factor_crudo},{base_cruda}\n"
    ).encode()
    puntos = parsear_orden_del_dia(csv_bytes)
    assert len(puntos) == 1
    assert puntos[0].tipo_mayoria is TipoMayoria.SIMPLE
    assert puntos[0].factor == 0.0
    assert puntos[0].base is BaseMayoria.VOTOS_COMPUTABLES


@pytest.mark.parametrize(
    "tipo_mayoria_case",
    ["SIMPLE", "simple", "Simple", "SiMpLe"],
)
def test_mayoria_simple_case_insensitive(tipo_mayoria_case: str) -> None:
    """Demuestra que el texto SIMPLE se normaliza sin importar mayúsculas/minúsculas."""
    csv_bytes = (
        f"nro_votacion,tipo,tema,tipo_mayoria,factor,base\n1,Despacho,Tema,{tipo_mayoria_case},,\n"
    ).encode()
    puntos = parsear_orden_del_dia(csv_bytes)
    assert puntos[0].tipo_mayoria is TipoMayoria.SIMPLE


@pytest.mark.parametrize(
    "factor_invalido",
    ["0.5", "1", "1.0", "-1", "2/3", "NaN", "inf", "-inf", "texto"],
)
def test_mayoria_simple_factor_distinto_de_cero_es_invalido(factor_invalido: str) -> None:
    """Demuestra que cualquier factor no representativo de cero exacto es inválido para SIMPLE."""
    csv_bytes = (
        f"nro_votacion,tipo,tema,tipo_mayoria,factor,base\n"
        f"1,Despacho,Tema,SIMPLE,{factor_invalido},\n"
    ).encode()
    with pytest.raises(ErrorOrdenDelDiaInvalido, match="factor para mayoría SIMPLE"):
        parsear_orden_del_dia(csv_bytes)


@pytest.mark.parametrize(
    "base_invalida",
    ["PRESENTES", "CUERPO", "presentes", "cuerpo", "OTRA_BASE"],
)
def test_mayoria_simple_base_distinta_de_votos_computables_es_invalida(
    base_invalida: str,
) -> None:
    """Demuestra que bases como PRESENTES o CUERPO son inválidas para SIMPLE."""
    csv_bytes = (
        f"nro_votacion,tipo,tema,tipo_mayoria,factor,base\n"
        f"1,Despacho,Tema,SIMPLE,0,{base_invalida}\n"
    ).encode()
    with pytest.raises(ErrorOrdenDelDiaInvalido, match="base para mayoría SIMPLE"):
        parsear_orden_del_dia(csv_bytes)


# ==============================================================================
# 6. MAYORÍA ESPECIAL
# ==============================================================================


@pytest.mark.parametrize(
    ("factor_crudo", "base_cruda", "base_esperada"),
    [
        ("0.5", "VOTOS_COMPUTABLES", BaseMayoria.VOTOS_COMPUTABLES),
        ("0.6666666667", "PRESENTES", BaseMayoria.PRESENTES),
        ("0.6666666667", "presentes", BaseMayoria.PRESENTES),
        ("0.75", "CUERPO", BaseMayoria.CUERPO),
        ("0.75", "cuerpo", BaseMayoria.CUERPO),
        ("1", "VOTOS_COMPUTABLES", BaseMayoria.VOTOS_COMPUTABLES),
        ("1.0", "CUERPO", BaseMayoria.CUERPO),
        ("0.0001", "PRESENTES", BaseMayoria.PRESENTES),
    ],
)
def test_mayoria_especial_entradas_validas(
    factor_crudo: str,
    base_cruda: str,
    base_esperada: BaseMayoria,
) -> None:
    """Demuestra que ESPECIAL acepta factores finitos en (0, 1] y bases válidas."""
    csv_bytes = (
        f"nro_votacion,tipo,tema,tipo_mayoria,factor,base\n"
        f"1,Despacho,Tema Especial,ESPECIAL,{factor_crudo},{base_cruda}\n"
    ).encode()
    puntos = parsear_orden_del_dia(csv_bytes)
    assert len(puntos) == 1
    assert puntos[0].tipo_mayoria is TipoMayoria.ESPECIAL
    assert puntos[0].factor == float(factor_crudo)
    assert puntos[0].base is base_esperada


@pytest.mark.parametrize(
    "tipo_mayoria_case",
    ["ESPECIAL", "especial", "Especial", "EsPeCiAl"],
)
def test_mayoria_especial_case_insensitive(tipo_mayoria_case: str) -> None:
    """Demuestra que el texto ESPECIAL se normaliza sin importar mayúsculas/minúsculas."""
    csv_bytes = (
        f"nro_votacion,tipo,tema,tipo_mayoria,factor,base\n"
        f"1,Despacho,Tema,{tipo_mayoria_case},0.66,PRESENTES\n"
    ).encode()
    puntos = parsear_orden_del_dia(csv_bytes)
    assert puntos[0].tipo_mayoria is TipoMayoria.ESPECIAL


@pytest.mark.parametrize(
    "factor_invalido",
    ["", "0", "0.0", "-0.1", "-1", "1.0001", "2", "NaN", "inf", "-inf", "dos tercios"],
)
def test_mayoria_especial_factor_invalido_es_rechazado(factor_invalido: str) -> None:
    """Demuestra que factores vacíos, <= 0, > 1, NaN, inf y texto son rechazados."""
    csv_bytes = (
        f"nro_votacion,tipo,tema,tipo_mayoria,factor,base\n"
        f"1,Despacho,Tema,ESPECIAL,{factor_invalido},PRESENTES\n"
    ).encode()
    with pytest.raises(ErrorOrdenDelDiaInvalido, match="factor"):
        parsear_orden_del_dia(csv_bytes)


@pytest.mark.parametrize(
    "base_invalida",
    ["", "CONCEJALES", "TOTAL", "VOTOS", "PADRON"],
)
def test_mayoria_especial_base_invalida_es_rechazada(base_invalida: str) -> None:
    """Demuestra que bases vacías o no reconocidas son rechazadas en ESPECIAL."""
    csv_bytes = (
        f"nro_votacion,tipo,tema,tipo_mayoria,factor,base\n"
        f"1,Despacho,Tema,ESPECIAL,0.66,{base_invalida}\n"
    ).encode()
    with pytest.raises(ErrorOrdenDelDiaInvalido, match="base"):
        parsear_orden_del_dia(csv_bytes)


# ==============================================================================
# 7. VALIDACIÓN DEL TIPO DE MAYORÍA (NO SE INFIERE DESDE FACTOR)
# ==============================================================================


@pytest.mark.parametrize(
    "mayoria_invalida",
    ["", "ABSOLUTA", "CALIFICADA", "OTRA", "0", "0.5"],
)
def test_tipo_mayoria_invalido_es_rechazado(mayoria_invalida: str) -> None:
    """Demuestra que tipo_mayoria debe ser explícitamente SIMPLE o ESPECIAL."""
    csv_bytes = (
        f"nro_votacion,tipo,tema,tipo_mayoria,factor,base\n"
        f"1,Despacho,Tema,{mayoria_invalida},0,VOTOS_COMPUTABLES\n"
    ).encode()
    with pytest.raises(ErrorOrdenDelDiaInvalido, match="tipo_mayoria"):
        parsear_orden_del_dia(csv_bytes)


# ==============================================================================
# 8. ATOMICIDAD DE CARGA
# ==============================================================================


def test_atomicidad_rechaza_todo_el_archivo_ante_una_fila_invalida() -> None:
    """Demuestra que si una sola fila entre varias es inválida, nada se carga."""
    csv_bytes = (
        b"nro_votacion,tipo,tema,tipo_mayoria,factor,base\n"
        b"1,Despacho,Tema 1 valido,SIMPLE,,\n"
        b"2,Despacho,Tema 2 valido,ESPECIAL,0.66,PRESENTES\n"
        b"3,Despacho,Tema 3 INVALIDO (factor negativo),ESPECIAL,-0.5,PRESENTES\n"
        b"4,Despacho,Tema 4 valido,SIMPLE,,\n"
    )
    with pytest.raises(ErrorOrdenDelDiaInvalido, match="factor"):
        parsear_orden_del_dia(csv_bytes)


def test_archivo_completo_con_multiples_filas_validas() -> None:
    """Demuestra la carga exitosa de un archivo con diversos puntos y tipos."""
    csv_bytes = (
        b"nro_votacion,tipo,tema,tipo_mayoria,factor,base\n"
        b'1,Ratificacion,"Convenio de Cooperacion",SIMPLE,0,VOTOS_COMPUTABLES\n'
        b'2,Despacho OP,"Pavimentacion calle Fontana",ESPECIAL,0.6666666667,PRESENTES\n'
        b'3,Despacho Gob,"Expropiacion de tierras",ESPECIAL,0.75,CUERPO\n'
        b'4,Mocion,"Mocion de preferencia",SIMPLE,,\n'
    )
    puntos = parsear_orden_del_dia(csv_bytes)
    assert len(puntos) == 4
    assert puntos[0].nro_votacion == 1
    assert puntos[0].tipo == "Ratificacion"
    assert puntos[0].tipo_mayoria is TipoMayoria.SIMPLE

    assert puntos[1].nro_votacion == 2
    assert puntos[1].tipo == "Despacho OP"
    assert puntos[1].tipo_mayoria is TipoMayoria.ESPECIAL
    assert puntos[1].base is BaseMayoria.PRESENTES

    assert puntos[2].nro_votacion == 3
    assert puntos[2].base is BaseMayoria.CUERPO
    assert puntos[2].factor == 0.75

    assert puntos[3].nro_votacion == 4
    assert puntos[3].tipo_mayoria is TipoMayoria.SIMPLE
    assert puntos[3].factor == 0.0
    assert puntos[3].base is BaseMayoria.VOTOS_COMPUTABLES
