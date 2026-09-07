"""Pruebas unitarias de la redacción segura del Device Bridge (WP-088).

`redaccion.py` es el único lugar donde el bridge decide qué parte de un dato sensible puede
llegar al registro operativo. Las pruebas de `test_cliente_http.py` y `test_servicio_bridge.py`
comprueban la propiedad de extremo a extremo —que dos votos distintos produzcan el mismo
registro—; acá se fija el comportamiento de cada helper por separado, para que una
regresión quede localizada en la función responsable y no sólo en el escenario completo.
"""

from __future__ import annotations

import pytest
from sis_leg_device_bridge.redaccion import (
    MOTIVO_NO_CANONICO,
    TECLA_REDACTADA,
    describir_cuerpo_crudo,
    describir_cuerpo_json,
    describir_tecla_no_funcional,
    sanear_motivo,
)


@pytest.mark.parametrize(
    "motivo_canonico",
    [
        "VOTO_REGISTRADO",
        "PRESENCIA_ACTUALIZADA",
        "AUDITORIA_NO_DISPONIBLE",
        "TECLA_NO_HABILITADA",
        "HTTP_422",
        "OK",
    ],
)
def test_los_codigos_estables_del_backend_pasan_sin_cambios(motivo_canonico: str) -> None:
    """Los motivos reales del backend son códigos estables y deben seguir siendo legibles.

    Sanear no puede degradar el diagnóstico: distinguir un `CONCEJAL_AUSENTE` de un
    `VOTO_YA_EMITIDO` es exactamente lo que WP-088 exige preservar.
    """
    assert sanear_motivo(motivo_canonico) == motivo_canonico


@pytest.mark.parametrize(
    "motivo_peligroso",
    [
        "la banca dev07 voto POSITIVO",  # texto libre con el sentido del voto
        "dev07=1",  # par banca/tecla compacto
        "voto_registrado",  # minúsculas: no es un código estable
        "VOTO REGISTRADO",  # espacios: tampoco lo es
        "A" * 200,  # texto largo que igual respeta el alfabeto
        "",  # cadena vacía
    ],
)
def test_el_texto_libre_del_backend_se_reemplaza_por_un_marcador(motivo_peligroso: str) -> None:
    """El `motivo` viaja dentro del cuerpo de la respuesta, así que es de origen externo.

    Como no se puede saber qué trae, se acepta sólo la forma de un código estable y
    cualquier otra cosa se descarta entera en lugar de intentar limpiarla.
    """
    assert sanear_motivo(motivo_peligroso) == MOTIVO_NO_CANONICO


@pytest.mark.parametrize("motivo_no_texto", [None, 123, True, {"tecla": "1"}, ["1"]])
def test_un_motivo_que_no_es_texto_tambien_se_redacta(motivo_no_texto: object) -> None:
    """El JSON externo puede traer cualquier tipo en ese campo, no necesariamente `str`."""
    assert sanear_motivo(motivo_no_texto) == MOTIVO_NO_CANONICO


def test_el_cuerpo_json_se_describe_por_forma_y_nunca_por_contenido() -> None:
    """De un cuerpo parseado sólo se publica su estructura: ni claves ni valores.

    El nombre de la clave también se omite: ver `tecla` en el registro de una banca
    identificable ya sería una señal que WP-088 no quiere producir.
    """
    descripcion = describir_cuerpo_json({"dispositivo": "dev07", "tecla": "1", "valor": "POSITIVO"})

    assert descripcion == "objeto JSON con 3 clave(s)"
    for prohibido in ("dev07", "tecla", "POSITIVO"):
        assert prohibido not in descripcion


@pytest.mark.parametrize(
    ("cuerpo", "descripcion_esperada"),
    [
        ({}, "objeto JSON con 0 clave(s)"),
        ([1, 2, 3], "arreglo JSON con 3 elemento(s)"),
        (None, "JSON nulo"),
        ("dev07 voto 1", "valor JSON escalar de tipo str"),
        (7, "valor JSON escalar de tipo int"),
    ],
)
def test_cada_forma_de_cuerpo_json_tiene_una_descripcion_no_sensible(
    cuerpo: object, descripcion_esperada: str
) -> None:
    """Todas las raíces posibles de un JSON quedan cubiertas por una descripción segura."""
    assert describir_cuerpo_json(cuerpo) == descripcion_esperada


@pytest.mark.parametrize("vacio", ["", "   ", "\n\t"])
def test_un_cuerpo_vacio_se_distingue_de_uno_con_contenido(vacio: str) -> None:
    """Saber si el backend contestó algo es diagnóstico útil y no revela nada."""
    assert describir_cuerpo_crudo(vacio) == "vacío"


def test_la_descripcion_de_un_cuerpo_crudo_no_depende_de_su_longitud() -> None:
    """La longitud es una medida directa de los valores ecoados, así que es un canal lateral.

    Un cuerpo que repite `POSITIVO` mide dos caracteres menos que el mismo cuerpo con
    `ABSTENCION`: publicar el largo exacto alcanzaría para distinguir sentidos de voto de
    una banca identificable, aunque el texto nunca se registrara.
    """
    positivo = describir_cuerpo_crudo("dev07 voto POSITIVO")
    abstencion = describir_cuerpo_crudo("dev07 voto ABSTENCION")

    assert positivo == abstencion == "no vacío"


@pytest.mark.parametrize("tecla_desconocida", ["KEY_F13", "KEY_LEFTCTRL", "BOTON_RARO"])
def test_una_tecla_que_el_normalizador_rechaza_se_puede_nombrar(tecla_desconocida: str) -> None:
    """DEC-015 permite ese diagnóstico y WP-088 lo conserva.

    Es seguro por construcción: si el normalizador la rechaza, esa tecla nunca se envía al
    backend, así que no puede ser `1`, `2` ni `3` y no tiene semántica de voto.
    """
    assert describir_tecla_no_funcional(tecla_desconocida) == tecla_desconocida


@pytest.mark.parametrize("tecla_funcional", ["KEY_KP1", "KEY_KP2", "KEY_KP3", "1", "3", "KEY_9"])
def test_una_tecla_funcional_nunca_se_nombra_aunque_se_la_pida(tecla_funcional: str) -> None:
    """El helper vuelve a comprobar la condición en vez de confiar en quien lo llama.

    Hoy el servicio sólo lo invoca en la rama donde la normalización ya falló, así que este
    caso no ocurre. Se fija igual porque es lo que impide que una futura ampliación del
    catálogo de normalización convierta ese mensaje en una filtración silenciosa.
    """
    assert describir_tecla_no_funcional(tecla_funcional) == TECLA_REDACTADA
