"""Pruebas del contrato CSV de la biblioteca de mensajes técnicos (WP-055).

Cubren las tres garantías que exige el WP para esta persistencia:

1. **Validación determinista**: archivo inexistente, vacío, con encabezado
   distinto, con columnas de más o de menos, con identificadores inválidos o
   duplicados, con texto vacío/largo/multilínea y con destinos desconocidos.
2. **Escritura segura**: el reemplazo es atómico y un fallo de E/S deja el
   archivo anterior intacto, sin temporales huérfanos ni pérdida silenciosa.
3. **Ida y vuelta**: lo que el backend escribe siempre puede releerse.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sis_leg_backend.configuracion.errores import ErrorMensajesTecnicosInvalido
from sis_leg_backend.configuracion.mensajes_tecnicos import (
    LARGO_MAXIMO_TEXTO,
    cargar_mensajes_tecnicos,
    guardar_mensajes_tecnicos,
    interpretar_mensajes_tecnicos,
    serializar_mensajes_tecnicos,
)
from sis_leg_backend.dominio.apoyo_tecnico import DestinoAvisoTecnico, MensajeTecnico
from sis_leg_backend.servicios.apoyo_tecnico import (
    MOTIVO_BIBLIOTECA_INVALIDA,
    leer_biblioteca_mensajes_tecnicos,
)


def mensaje(identificador: str = "abc123", texto: str = "Volvemos en breve") -> MensajeTecnico:
    """Construye un mensaje válido para las pruebas de ida y vuelta."""

    return MensajeTecnico(
        mensaje_id=identificador,
        texto=texto,
        destino=DestinoAvisoTecnico.RECINTO,
    )


def test_archivo_inexistente_es_biblioteca_vacia(tmp_path: Path) -> None:
    """Una instalación nueva todavía no tiene mensajes y eso no es un error."""

    assert cargar_mensajes_tecnicos(tmp_path / "no-existe.csv") == ()


def test_biblioteca_inicial_de_archivo_inexistente_queda_disponible(tmp_path: Path) -> None:
    """Sin archivo la biblioteca está vacía pero admite escrituras."""

    biblioteca = leer_biblioteca_mensajes_tecnicos(tmp_path / "no-existe.csv")

    assert biblioteca.mensajes == ()
    assert biblioteca.disponible
    assert biblioteca.motivo is None


def test_biblioteca_inicial_de_archivo_invalido_queda_no_disponible(tmp_path: Path) -> None:
    """Un CSV corrupto degrada solo su funcionalidad, no impide arrancar."""

    ruta = tmp_path / "mensajes.csv"
    ruta.write_text("otro,encabezado\n", encoding="utf-8")

    biblioteca = leer_biblioteca_mensajes_tecnicos(ruta)

    assert biblioteca.mensajes == ()
    assert not biblioteca.disponible
    assert biblioteca.motivo == MOTIVO_BIBLIOTECA_INVALIDA
    assert biblioteca.detalle is not None


def test_archivo_valido_conserva_orden_y_destinos(tmp_path: Path) -> None:
    """El orden del archivo es el orden de la biblioteca."""

    ruta = tmp_path / "mensajes.csv"
    ruta.write_text(
        "id,texto,destino\n"
        "uno,Prueba de sonido,MODERACION\n"
        "dos,Volvemos en cinco minutos,RECINTO\n"
        "tres,Se reanuda la sesión,AMBOS\n",
        encoding="utf-8",
    )

    mensajes = cargar_mensajes_tecnicos(ruta)

    assert [item.mensaje_id for item in mensajes] == ["uno", "dos", "tres"]
    assert mensajes[0].destino is DestinoAvisoTecnico.MODERACION
    assert mensajes[1].destino is DestinoAvisoTecnico.RECINTO
    assert mensajes[2].destino is DestinoAvisoTecnico.AMBOS


def test_bom_de_editor_windows_se_tolera(tmp_path: Path) -> None:
    """``utf-8-sig`` descarta el BOM sin alterar el encabezado canónico."""

    ruta = tmp_path / "mensajes.csv"
    ruta.write_text("id,texto,destino\nuno,Prueba,RECINTO\n", encoding="utf-8-sig")

    assert cargar_mensajes_tecnicos(ruta)[0].mensaje_id == "uno"


def test_lineas_en_blanco_se_ignoran() -> None:
    """Una línea vacía es formato CSV aceptable y no rompe la carga."""

    mensajes = interpretar_mensajes_tecnicos(
        "id,texto,destino\nuno,Prueba,RECINTO\n\ndos,Otra,AMBOS\n"
    )

    assert [item.mensaje_id for item in mensajes] == ["uno", "dos"]


@pytest.mark.parametrize(
    ("contenido", "fragmento_esperado"),
    [
        ("", "vacío"),
        ("id,mensaje,destino\n", "encabezado"),
        ("destino,texto,id\n", "encabezado"),
        ("id,texto,destino\nuno,Prueba\n", "columnas"),
        ("id,texto,destino\nuno,Prueba,RECINTO,extra\n", "columnas"),
        ("id,texto,destino\n,Prueba,RECINTO\n", "el id debe tener"),
        ("id,texto,destino\nid con espacios,Prueba,RECINTO\n", "el id debe tener"),
        ("id,texto,destino\nuno,Prueba,RECINTO\nuno,Otra,AMBOS\n", "id duplicado"),
        ("id,texto,destino\nuno,   ,RECINTO\n", "texto no puede estar vacío"),
        ("id,texto,destino\nuno,Prueba,PANTALLA\n", "destino debe ser uno de"),
        ('id,texto,destino\nuno,"Con\nsalto",RECINTO\n', "saltos de línea"),
    ],
    ids=[
        "vacio",
        "encabezado-renombrado",
        "encabezado-reordenado",
        "columnas-de-menos",
        "columnas-de-mas",
        "id-vacio",
        "id-con-espacios",
        "id-duplicado",
        "texto-vacio",
        "destino-desconocido",
        "texto-multilinea",
    ],
)
def test_contenido_invalido_se_rechaza_con_mensaje_determinista(
    contenido: str,
    fragmento_esperado: str,
) -> None:
    """Cada incumplimiento del contrato produce siempre el mismo diagnóstico."""

    with pytest.raises(ErrorMensajesTecnicosInvalido, match=fragmento_esperado):
        interpretar_mensajes_tecnicos(contenido)


def test_texto_demasiado_largo_se_rechaza() -> None:
    """El límite protege el payload SSE de un archivo desmesurado."""

    excesivo = "x" * (LARGO_MAXIMO_TEXTO + 1)
    with pytest.raises(ErrorMensajesTecnicosInvalido, match="no puede superar"):
        interpretar_mensajes_tecnicos(f"id,texto,destino\nuno,{excesivo},RECINTO\n")


def test_texto_en_el_limite_exacto_se_acepta() -> None:
    """La frontera es inclusiva: exactamente el máximo sigue siendo válido."""

    limite = "x" * LARGO_MAXIMO_TEXTO
    mensajes = interpretar_mensajes_tecnicos(f"id,texto,destino\nuno,{limite},RECINTO\n")

    assert mensajes[0].texto == limite


def test_texto_con_comas_y_comillas_sobrevive_la_ida_y_vuelta(tmp_path: Path) -> None:
    """El CSV se escribe con ``csv.writer``, así que entrecomilla lo necesario."""

    ruta = tmp_path / "mensajes.csv"
    original = mensaje(texto='Atención: pausa, "breve"')

    guardar_mensajes_tecnicos(ruta, (original,))

    assert cargar_mensajes_tecnicos(ruta) == (original,)


def test_guardado_escribe_encabezado_canonico_sin_bom(tmp_path: Path) -> None:
    """El archivo usa UTF-8 sin BOM y ``\\n``, igual que ``concejales.csv``."""

    ruta = tmp_path / "mensajes.csv"
    guardar_mensajes_tecnicos(ruta, (mensaje(),))

    crudo = ruta.read_bytes()
    assert not crudo.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in crudo
    assert crudo.decode("utf-8").splitlines()[0] == "id,texto,destino"


def test_guardado_crea_el_directorio_faltante(tmp_path: Path) -> None:
    """Una instalación de desarrollo todavía no tiene ``config/apoyo-tecnico``."""

    ruta = tmp_path / "config" / "apoyo-tecnico" / "mensajes.csv"

    guardar_mensajes_tecnicos(ruta, (mensaje(),))

    assert cargar_mensajes_tecnicos(ruta) == (mensaje(),)


def test_biblioteca_vacia_se_persiste_solo_con_encabezado(tmp_path: Path) -> None:
    """Eliminar el último mensaje deja un archivo válido, no un archivo vacío."""

    ruta = tmp_path / "mensajes.csv"
    guardar_mensajes_tecnicos(ruta, ())

    assert ruta.read_text(encoding="utf-8") == "id,texto,destino\n"
    assert cargar_mensajes_tecnicos(ruta) == ()


def test_guardado_no_deja_temporales_al_terminar(tmp_path: Path) -> None:
    """Tras un guardado exitoso el directorio contiene solamente el archivo."""

    ruta = tmp_path / "mensajes.csv"
    guardar_mensajes_tecnicos(ruta, (mensaje(),))

    assert sorted(item.name for item in tmp_path.iterdir()) == ["mensajes.csv"]


def test_fallo_de_reemplazo_conserva_el_archivo_anterior(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un fallo de E/S nunca deja la biblioteca a medias ni temporales sueltos.

    Se interrumpe exactamente en ``os.replace``, que es el único paso capaz de
    cambiar el archivo real: si fallara después de truncarlo, el contenido
    anterior se habría perdido. Con escritura atómica, en cambio, el archivo
    original permanece byte a byte igual.
    """

    ruta = tmp_path / "mensajes.csv"
    guardar_mensajes_tecnicos(ruta, (mensaje("original", "Texto original"),))
    contenido_previo = ruta.read_bytes()

    def reemplazo_fallido(origen: object, destino: object) -> None:
        raise OSError("disco lleno simulado")

    monkeypatch.setattr(os, "replace", reemplazo_fallido)

    from sis_leg_backend.dominio.apoyo_tecnico import ErrorPersistenciaMensajesTecnicos

    with pytest.raises(ErrorPersistenciaMensajesTecnicos):
        guardar_mensajes_tecnicos(ruta, (mensaje("nuevo", "Texto nuevo"),))

    assert ruta.read_bytes() == contenido_previo
    assert sorted(item.name for item in tmp_path.iterdir()) == ["mensajes.csv"]


def test_serializacion_es_estable_y_relegible() -> None:
    """La serialización que se persiste es exactamente la que se vuelve a leer."""

    mensajes = (
        MensajeTecnico("uno", "Prueba de sonido", DestinoAvisoTecnico.MODERACION),
        MensajeTecnico("dos", "Volvemos en cinco", DestinoAvisoTecnico.AMBOS),
    )

    texto = serializar_mensajes_tecnicos(mensajes)

    assert texto == (
        "id,texto,destino\nuno,Prueba de sonido,MODERACION\ndos,Volvemos en cinco,AMBOS\n"
    )
    assert interpretar_mensajes_tecnicos(texto) == mensajes
