"""Pruebas de la auditoría de identidad institucional (WP-084).

La auditoría existe para que el desacoplamiento de WP-084 no se deshaga solo. Su
valor depende de dos propiedades que hay que demostrar, no suponer:

1. **Detecta.** Una reintroducción de cualquiera de los tres términos en un
   archivo activo produce un problema con la ruta y una explicación accionable.
2. **No tapa de más.** La allowlist es por ruta y por conteo exacto, así que un
   archivo permitido que gana una ocurrencia falla igual que uno prohibido, y uno
   que las pierde también falla, para que la excepción no siga cubriendo algo que
   ya no existe.

Los escenarios sintéticos se arman inyectando archivos, allowlist y contador,
que es exactamente para lo que la auditoría acepta esos parámetros. La última
prueba sí ejecuta la auditoría real contra el repositorio, que es el gate que
corre en CI.
"""

from __future__ import annotations

from collections.abc import Callable

from scripts.auditar_identidad_institucional import (
    TERMINOS,
    ReferenciaPermitida,
    auditar,
    contar_ocurrencias,
)


def _contador(mapa: dict[str, dict[str, int]]) -> Callable[[str], dict[str, int]]:
    """Devuelve un contador falso que responde desde un diccionario.

    El tipo de retorno se escribe explícitamente porque `auditar` recibe el
    contador como parámetro tipado: una lambda sin anotar dejaría el argumento
    parcialmente desconocido para el verificador de tipos.
    """

    def contar(ruta: str) -> dict[str, int]:
        return mapa.get(ruta, {})

    return contar


# =============================================================================
# 1. Detección en archivos no permitidos
# =============================================================================


def test_detecta_una_reintroduccion_en_un_archivo_activo() -> None:
    """Un término local en un archivo fuera de la allowlist es un problema."""

    problemas = auditar(
        archivos=["docs/07-configuracion-datos-y-assets.md"],
        permitidas=(),
        contador=_contador({"docs/07-configuracion-datos-y-assets.md": {"Madryn": 1}}),
    )

    assert len(problemas) == 1
    assert "docs/07-configuracion-datos-y-assets.md" in problemas[0]
    assert "Madryn" in problemas[0]


def test_informa_los_tres_terminos_por_separado() -> None:
    """Cada término se reporta con su propia explicación, no en un bulto."""

    problemas = auditar(
        archivos=["README.md"],
        permitidas=(),
        contador=_contador({"README.md": {"Madryn": 1, "Chubut": 2, "Concejo Deliberante": 1}}),
    )

    assert len(problemas) == 3
    texto = "\n".join(problemas)
    assert "cuerpo legislativo" in texto
    assert "ficticios" in texto


def test_un_archivo_limpio_no_produce_problemas() -> None:
    """El caso normal: nada que reportar."""

    assert auditar(archivos=["README.md"], permitidas=(), contador=_contador({})) == []


# =============================================================================
# 2. La allowlist no puede tapar de más ni de menos
# =============================================================================


def test_una_ocurrencia_extra_en_un_archivo_permitido_falla() -> None:
    """La excepción es por conteo, no por ruta: una de más es reintroducción."""

    permitida = ReferenciaPermitida(
        "docs/work-packages/WP-050.md",
        {"Madryn": 1},
        "Contrato cerrado.",
    )

    problemas = auditar(
        archivos=["docs/work-packages/WP-050.md"],
        permitidas=(permitida,),
        contador=_contador({"docs/work-packages/WP-050.md": {"Madryn": 2}}),
    )

    assert len(problemas) == 1
    assert "se esperaban 1" in problemas[0]


def test_una_ocurrencia_de_menos_tambien_falla() -> None:
    """Una allowlist desactualizada cubre más de lo necesario y debe corregirse."""

    permitida = ReferenciaPermitida(
        "docs/work-packages/WP-050.md",
        {"Madryn": 2},
        "Contrato cerrado.",
    )

    problemas = auditar(
        archivos=["docs/work-packages/WP-050.md"],
        permitidas=(permitida,),
        contador=_contador({"docs/work-packages/WP-050.md": {"Madryn": 1}}),
    )

    assert len(problemas) == 1
    assert "Actualizá el conteo" in problemas[0]


def test_una_entrada_no_abre_el_archivo_para_los_demas_terminos() -> None:
    """Permitir «Madryn» en un archivo no autoriza «Chubut» en el mismo archivo."""

    permitida = ReferenciaPermitida(
        "docs/work-packages/WP-043.md",
        {"Madryn": 1},
        "Contrato cerrado.",
    )

    problemas = auditar(
        archivos=["docs/work-packages/WP-043.md"],
        permitidas=(permitida,),
        contador=_contador({"docs/work-packages/WP-043.md": {"Madryn": 1, "Chubut": 1}}),
    )

    assert len(problemas) == 1
    assert "Chubut" in problemas[0]


def test_una_entrada_sin_motivo_es_un_error_de_politica() -> None:
    """Una excepción sin justificación escrita no debería existir."""

    permitida = ReferenciaPermitida("README.md", {"Madryn": 1}, "   ")

    problemas = auditar(
        archivos=["README.md"],
        permitidas=(permitida,),
        contador=_contador({"README.md": {"Madryn": 1}}),
    )

    assert any("no declara motivo" in problema for problema in problemas)


def test_una_entrada_con_un_termino_inexistente_es_un_error_de_politica() -> None:
    """Un nombre mal escrito en la allowlist dejaría de cubrir lo que pretendía."""

    permitida = ReferenciaPermitida("README.md", {"Madrin": 1}, "Contrato cerrado.")

    problemas = auditar(archivos=[], permitidas=(permitida,), contador=_contador({}))

    assert any("no es un término auditado" in problema for problema in problemas)


# =============================================================================
# 3. Comportamiento del contador real y gate del repositorio
# =============================================================================


def test_el_contador_ignora_binarios_y_rutas_inexistentes() -> None:
    """Un PNG o una ruta borrada no son un error de auditoría: no aportan texto."""

    assert contar_ocurrencias("ruta/que/no/existe.md") == {}
    assert contar_ocurrencias("assets/branding/sisleg-logo.png") == {}


def test_los_patrones_no_distinguen_mayusculas() -> None:
    """La reintroducción tampoco las distingue: `madryn` es el mismo problema."""

    por_nombre = {termino.nombre: termino for termino in TERMINOS}
    assert por_nombre["Madryn"].patron.search("puerto madryn") is not None
    assert por_nombre["Concejo Deliberante"].patron.search("CONCEJO   DELIBERANTE") is not None


def test_el_repositorio_actual_no_tiene_referencias_activas() -> None:
    """Gate real: es lo mismo que ejecuta la CI en cada Pull Request."""

    assert auditar() == []
