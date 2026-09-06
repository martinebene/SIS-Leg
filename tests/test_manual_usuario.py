"""Pruebas del manual de usuario estático de SIS-Leg (WP-067).

El manual es un entregable de contenido, no de código, así que lo que puede comprobarse
automáticamente no es «que esté bien escrito» sino tres propiedades verificables que, si
se rompen, lo vuelven inútil o incorrecto:

1. **Está completo y navegable.** Existen los trece capítulos exigidos por el WP, el
   índice los enumera a todos y ningún enlace interno apunta a un ancla inexistente.
2. **Es autocontenido.** No referencia ningún recurso externo: una instalación sin salida
   a Internet debe verlo exactamente igual, y una red de distribución de contenidos caída
   no puede degradarlo. Tampoco enlaza a rutas que no estarán disponibles en el artefacto
   servido: los archivos de configuración se **nombran**, no se enlazan.
3. **Es genérico.** No contiene reglas, nombres, autoridades ni datos de la institución
   concreta que hoy usa el sistema. Ese es el requisito que permite reutilizarlo, y es
   también el más fácil de romper sin darse cuenta al ampliar un capítulo.

Las referencias a archivos del proyecto se marcan en el HTML con `data-archivo`, de modo
que esta prueba pueda comprobar que cada una sigue existiendo. Un archivo renombrado
convierte al manual en documentación equivocada; acá eso falla la CI en lugar de llegar a
producción.
"""

from __future__ import annotations

import base64
import csv
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

RAIZ_REPOSITORIO = Path(__file__).resolve().parents[1]
RUTA_MANUAL = RAIZ_REPOSITORIO / "manual" / "index.html"
RUTA_LOGO_CANONICO = RAIZ_REPOSITORIO / "assets" / "branding" / "sisleg-logo.png"

# Los trece capítulos obligatorios del WP, en su orden canónico. El identificador es parte
# del contrato: los enlaces internos y las pruebas de navegador dependen de él.
CAPITULOS_OBLIGATORIOS = (
    "cap-01-vision-general",
    "cap-02-preparacion",
    "cap-03-sesion-autoridades",
    "cap-04-presencia-quorum",
    "cap-05-orden-del-dia",
    "cap-06-votaciones",
    "cap-07-palabra",
    "cap-08-apoyo-tecnico",
    "cap-09-sonidos",
    "cap-10-configuracion",
    "cap-11-instalacion",
    "cap-12-operacion",
    "cap-13-navegador",
)

# Los quince eventos sonoros configurables. El manual debe nombrarlos con el mismo texto
# que se escribe en `system.toml`, o quien lo lea no sabrá qué clave editar.
EVENTOS_SONOROS = (
    "preparacion_iniciada",
    "aviso_tecnico_publicado",
    "aviso_tecnico_retirado",
    "pedido_palabra_registrado",
    "pedido_palabra_retirado",
    "uso_palabra_otorgado",
    "transmision_iniciada",
    "transmision_detenida",
    "transmision_cuenta_regresiva_tic",
    "sesion_abierta",
    "sesion_cerrada",
    "votacion_abierta",
    "votacion_cerrada",
    "concejal_ausente",
    "concejal_presente",
)

# Términos que identificarían a la institución concreta en un documento que debe poder
# entregarse tal cual a otro cliente.
TERMINOS_PROHIBIDOS = (
    "Madryn",
    "Concejo Deliberante",
    "Chubut",
)

# Nombre histórico del producto, retirado por WP-077. Presentarlo como marca sería una
# regresión, pero el capítulo de migración necesita nombrar la instalación anterior y sus
# rutas para que quien opera sepa qué está convirtiendo. La regla verificable es de
# ubicación, no de ausencia: el nombre legado sólo puede aparecer dentro de ese apartado.
MARCA_LEGADA = "botonera2"
TITULO_MIGRACION = "12.7 Migración desde una instalación con el nombre anterior"


class AnalizadorManual(HTMLParser):
    """Recolecta del manual todo lo que las pruebas necesitan comprobar.

    Se usa un analizador real en lugar de expresiones regulares porque las tres cosas que
    interesan —anclas declaradas, enlaces emitidos y recursos externos— son estructura
    HTML, y una expresión regular sobre el texto crudo confundiría un ejemplo de código
    con una etiqueta real.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.identificadores: set[str] = set()
        self.enlaces: list[str] = []
        self.archivos_referenciados: list[str] = []
        self.recursos_externos: list[str] = []
        self.etiquetas: list[str] = []
        self.imagenes: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        atributos = {nombre: (valor or "") for nombre, valor in attrs}
        self.etiquetas.append(tag)

        if "id" in atributos:
            self.identificadores.add(atributos["id"])
        if "data-archivo" in atributos:
            self.archivos_referenciados.append(atributos["data-archivo"])
        if tag == "a" and "href" in atributos:
            self.enlaces.append(atributos["href"])
        if tag == "img":
            self.imagenes.append((atributos.get("src", ""), atributos.get("alt", "")))

        # `src` y el `href` de un `link` cargan recursos; el `href` de un `a` sólo navega.
        candidatos = [atributos.get("src", "")]
        if tag == "link":
            candidatos.append(atributos.get("href", ""))
        for candidato in candidatos:
            if candidato and re.match(r"^(https?:)?//", candidato):
                self.recursos_externos.append(candidato)


@pytest.fixture(scope="module")
def texto_manual() -> str:
    """Devuelve el manual tal cual se publica, sin normalizar nada."""

    return RUTA_MANUAL.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def manual(texto_manual: str) -> AnalizadorManual:
    """Analiza el manual una sola vez para todas las pruebas del módulo."""

    analizador = AnalizadorManual()
    analizador.feed(texto_manual)
    return analizador


def test_el_manual_existe_y_declara_idioma_y_codificacion(texto_manual: str) -> None:
    """Un manual sin idioma ni codificación declarados se lee mal fuera del navegador."""

    assert RUTA_MANUAL.is_file()
    assert texto_manual.lstrip().lower().startswith("<!doctype html>")
    assert '<html lang="es">' in texto_manual
    assert '<meta charset="utf-8"' in texto_manual


def test_incluye_los_trece_capitulos_obligatorios(manual: AnalizadorManual) -> None:
    """Cada capítulo exigido por el WP existe como sección con su ancla estable."""

    faltantes = [
        capitulo for capitulo in CAPITULOS_OBLIGATORIOS if capitulo not in manual.identificadores
    ]
    assert not faltantes, f"El manual no cubre estos capítulos: {faltantes}"


def test_el_indice_enumera_todos_los_capitulos(manual: AnalizadorManual) -> None:
    """Un capítulo al que el índice no llega es, en la práctica, un capítulo perdido."""

    enlazados = {enlace.removeprefix("#") for enlace in manual.enlaces if enlace.startswith("#")}
    faltantes = [capitulo for capitulo in CAPITULOS_OBLIGATORIOS if capitulo not in enlazados]
    assert not faltantes, f"El índice no enlaza estos capítulos: {faltantes}"


def test_ningun_enlace_interno_queda_roto(manual: AnalizadorManual) -> None:
    """Todo `#ancla` del documento corresponde a un `id` realmente declarado."""

    rotos = sorted(
        {
            enlace
            for enlace in manual.enlaces
            if enlace.startswith("#") and enlace.removeprefix("#") not in manual.identificadores
        }
    )
    assert not rotos, f"Enlaces internos rotos: {rotos}"


def test_todos_los_enlaces_son_internos(manual: AnalizadorManual) -> None:
    """El manual no enlaza rutas que podrían no existir donde se lo sirve.

    Los archivos de configuración se nombran como texto, no como enlace: dentro del
    artefacto servido no hay ningún `config/` alcanzable por el navegador, así que un
    enlace a esa ruta sería un enlace roto en producción.
    """

    externos = sorted({enlace for enlace in manual.enlaces if not enlace.startswith("#")})
    assert not externos, f"El manual enlaza fuera de sí mismo: {externos}"


def test_no_depende_de_ningun_recurso_externo(manual: AnalizadorManual, texto_manual: str) -> None:
    """Debe verse igual en una instalación sin salida a Internet."""

    assert not manual.recursos_externos, f"Recursos externos: {manual.recursos_externos}"
    # Tampoco puede traer una hoja de estilos o un script de otro archivo: el manual viaja
    # como un único documento y el empaquetado no declara recursos adicionales.
    assert "<link" not in texto_manual
    assert "<script" not in texto_manual


def test_las_referencias_a_archivos_del_proyecto_existen(manual: AnalizadorManual) -> None:
    """Un archivo renombrado convierte al manual en documentación equivocada."""

    assert manual.archivos_referenciados, "El manual no referencia ningún archivo verificable."
    inexistentes = [
        ruta for ruta in manual.archivos_referenciados if not (RAIZ_REPOSITORIO / ruta).exists()
    ]
    assert not inexistentes, f"El manual referencia rutas inexistentes: {inexistentes}"


def test_documenta_las_claves_reales_de_configuracion(texto_manual: str) -> None:
    """Los nombres citados tienen que ser los que la persona va a escribir en el archivo."""

    for clave in (
        "session.quorum",
        "room.rows",
        "voting.types",
        "timers.moderation_vote_reveal_seconds",
        "timers.public_initial_countdown_seconds",
        "timers.public_result_display_seconds",
        "paths.logs_dir",
    ):
        assert clave in texto_manual, f"El manual no documenta la clave {clave}."

    # Encabezado canónico del padrón y del Orden del Día, y formato de la auditoría.
    assert "dni,nombre,apellido,bloque,banca,dispositivo_votacion,ruta_imagen" in texto_manual
    assert "nro_votacion,tipo,tema,tipo_mayoria,factor,base" in texto_manual
    assert "seq;timestamp;level;tag;event_code;message" in texto_manual


def test_documenta_los_quince_eventos_sonoros(texto_manual: str) -> None:
    """Sin el nombre exacto del evento no se puede cambiar su sonido ni su volumen."""

    faltantes = [evento for evento in EVENTOS_SONOROS if evento not in texto_manual]
    assert not faltantes, f"El manual no documenta estos eventos sonoros: {faltantes}"


def test_documenta_el_requisito_de_reproduccion_automatica(texto_manual: str) -> None:
    """Es el único requisito del puesto sin el cual el sonido falla en silencio."""

    assert "autoplay-policy=no-user-gesture-required" in texto_manual
    assert "reproducción automática" in texto_manual


def test_usa_la_marca_sisleg_y_la_terminologia_recinto(texto_manual: str) -> None:
    """La marca visible es SIS-Leg y el ámbito se llama recinto, nunca «sala»."""

    assert "SIS-Leg" in texto_manual
    assert "recinto" in texto_manual.lower()
    # `sala` aparecería como sinónimo indebido; se busca como palabra completa para no
    # confundirla con otra que la contenga.
    assert not re.search(r"\bsalas?\b", texto_manual, flags=re.IGNORECASE)


def test_no_particulariza_la_institucion(texto_manual: str) -> None:
    """El manual debe poder entregarse a otra institución sin editarlo."""

    encontrados = [termino for termino in TERMINOS_PROHIBIDOS if termino in texto_manual]
    assert not encontrados, f"El manual incluye referencias específicas: {encontrados}"


def test_la_marca_legada_solo_aparece_en_el_apartado_de_migracion(texto_manual: str) -> None:
    """El nombre anterior sobrevive únicamente donde explica qué se está migrando."""

    inicio = texto_manual.find(TITULO_MIGRACION)
    assert inicio != -1, "Falta el apartado de migración desde la instalación anterior."
    # El apartado termina donde empieza el enlace de cierre del capítulo.
    fin = texto_manual.find('<a class="volver"', inicio)
    assert fin != -1, "El apartado de migración no cierra con el enlace al índice."

    apartado = texto_manual[inicio:fin]
    total = texto_manual.lower().count(MARCA_LEGADA)
    dentro = apartado.lower().count(MARCA_LEGADA)

    assert dentro > 0, "El apartado de migración debe nombrar la instalación anterior."
    assert total == dentro, (
        f"La marca legada aparece {total - dentro} vez/veces fuera del apartado de migración."
    )


def test_no_expone_datos_del_padron_instalado(texto_manual: str) -> None:
    """Ningún dato personal del padrón versionado puede filtrarse al manual genérico."""

    filtrados: list[str] = []
    with (RAIZ_REPOSITORIO / "config" / "concejales.example.csv").open(encoding="utf-8") as archivo:
        for fila in csv.DictReader(archivo):
            for campo in ("dni", "nombre", "apellido", "bloque"):
                valor = (fila[campo] or "").strip()
                if valor and valor in texto_manual:
                    filtrados.append(f"{campo}={valor}")
    assert not filtrados, f"El manual contiene datos del padrón instalado: {filtrados}"


def test_la_cabecera_muestra_el_logo_canonico_incrustado(texto_manual: str) -> None:
    """La cabecera muestra el logo aprobado y lo lleva adentro, no como archivo aparte.

    WP-069 pide que el manual use la misma identidad visual que el resto del producto sin
    reinterpretarla y sin dejar de ser un documento único. Ambas cosas se comprueban de la
    misma manera: la imagen viaja como `data:` y, al decodificarla, tiene que salir
    **exactamente** el PNG versionado en `assets/branding/`. Si alguien la reemplazara por
    una versión reescalada, recomprimida o recortada «para que pese menos», la comparación
    byte a byte fallaría, que es justamente lo que el WP prohíbe.
    """

    cabecera = re.search(r"<header class=\"encabezado\">(.*?)</header>", texto_manual, re.S)
    assert cabecera is not None, "El manual ya no tiene la cabecera esperada."

    analizador = AnalizadorManual()
    analizador.feed(cabecera.group(1))
    assert analizador.imagenes, "La cabecera del manual no muestra ninguna imagen."

    origen, alternativo = analizador.imagenes[0]
    prefijo = "data:image/png;base64,"
    assert origen.startswith(prefijo), "El logo de la cabecera no viaja incrustado en el manual."

    # `validate=True` rechaza cualquier carácter ajeno al alfabeto base64: si el atributo
    # quedara cortado o con espacios, se ve acá y no como una imagen rota en pantalla.
    incrustado = base64.b64decode(origen.removeprefix(prefijo), validate=True)
    assert incrustado == RUTA_LOGO_CANONICO.read_bytes(), (
        "El logo incrustado en el manual no es idéntico al canónico de assets/branding/."
    )

    # Donde se ve el logo no se repite la marca como texto, así que el nombre accesible lo
    # aporta el texto alternativo de la imagen.
    assert alternativo == "SIS-Leg"
