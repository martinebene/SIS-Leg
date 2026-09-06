"""Pruebas de la configuración y los assets de sonido del Recinto (WP-065).

Cubren las cuatro fronteras que el WP declara obligatorias:

1. la sección ``[sonidos]`` válida se carga completa y congelada;
2. cada forma inválida —evento faltante, evento sobrante, tipo equivocado,
   volumen fuera de ``0..100`` y ruta no admitida— produce un error de
   configuración claro y determinista;
3. los 22 archivos WAV existen, son los que genera el script versionado y las
   quince rutas configuradas resuelven a archivos reales;
4. el arranque tolerante nunca propaga un error, aunque el archivo esté roto.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest
from conftest import TOML_CANONICO, escribir_system_toml
from sis_leg_backend.configuracion.cargar_configuracion import cargar_configuracion_sistema
from sis_leg_backend.configuracion.errores import ErrorValidacionConfiguracion
from sis_leg_backend.configuracion.sonidos_recinto import (
    EVENTOS_SONIDO_RECINTO,
    MOTIVO_SONIDOS_INVALIDOS,
    leer_sonidos_recinto,
    validar_assets_sonidos,
)

from deploy.validar_configuracion import validar as validar_despliegue
from scripts.generar_sonidos_recinto import (
    RECETAS,
    RECETAS_ALTERNATIVAS,
    RECETAS_ASIGNADAS,
    generar,
)

# Rutas reales del repositorio. Las pruebas de assets no usan fixtures: su
# propósito es justamente comprobar los archivos versionados. Desde WP-073 la
# configuración versionada es la plantilla `config/system.example.toml`: el
# `config/system.toml` operativo está ignorado por Git y puede no existir.
RAIZ_REPOSITORIO = Path(__file__).resolve().parents[1]
RUTA_SYSTEM_TOML = RAIZ_REPOSITORIO / "config/system.example.toml"
RAIZ_PUBLICA_RECINTO = RAIZ_REPOSITORIO / "apps/recinto/public"
DIRECTORIO_SONIDOS = RAIZ_PUBLICA_RECINTO / "assets/sonidos"


def _toml_con_sonido(evento: str, cuerpo: str) -> str:
    """Devuelve el TOML canónico reemplazando la entrada de un evento.

    Permite fabricar variantes inválidas sin reescribir el archivo completo ni
    depender del orden en que están declarados los quince eventos.
    """

    marca = f"[sonidos.{evento}]"
    inicio = TOML_CANONICO.index(marca)
    fin = TOML_CANONICO.find("\n[", inicio + 1)
    resto = TOML_CANONICO[fin:] if fin != -1 else ""
    return TOML_CANONICO[:inicio] + cuerpo + resto


# =============================================================================
# 1. Carga válida
# =============================================================================


def test_carga_los_quince_sonidos_en_el_orden_canonico(ruta_system_toml_valido: Path) -> None:
    """El contrato exige exactamente quince entradas y un orden estable."""

    configuracion = cargar_configuracion_sistema(ruta_system_toml_valido)

    sonidos = configuracion.sonidos_recinto
    assert sonidos.disponible is True
    assert sonidos.motivo is None
    assert tuple(sonido.evento for sonido in sonidos.sonidos) == EVENTOS_SONIDO_RECINTO


def test_cada_sonido_conserva_ruta_y_volumen_entero(ruta_system_toml_valido: Path) -> None:
    """Ruta y volumen viajan tal como se configuraron, sin normalizaciones."""

    sonidos = cargar_configuracion_sistema(ruta_system_toml_valido).sonidos_recinto

    for indice, sonido in enumerate(sonidos.sonidos):
        assert sonido.ruta.startswith("assets/sonidos/")
        assert sonido.ruta.endswith(".wav")
        assert isinstance(sonido.volumen, int)
        assert 0 <= sonido.volumen <= 100
        # El conftest asigna un volumen distinto a cada evento; comprobarlo
        # demuestra que la carga no mezcla entradas entre sí.
        assert sonido.volumen == (indice * 7) % 101


def test_buscar_devuelve_el_sonido_del_evento_o_none(ruta_system_toml_valido: Path) -> None:
    """La búsqueda por evento es la forma soportada de consultar un sonido."""

    sonidos = cargar_configuracion_sistema(ruta_system_toml_valido).sonidos_recinto

    encontrado = sonidos.buscar("sesion_abierta")
    assert encontrado is not None
    assert encontrado.evento == "sesion_abierta"
    assert sonidos.buscar("evento_inexistente") is None


def test_cambiar_el_archivo_no_altera_los_sonidos_ya_cargados(tmp_path: Path) -> None:
    """Los sonidos quedan congelados igual que el resto de la configuración."""

    ruta = escribir_system_toml(tmp_path / "system.toml", TOML_CANONICO)
    configuracion = cargar_configuracion_sistema(ruta)
    volumen_original = configuracion.sonidos_recinto.sonidos[0].volumen

    escribir_system_toml(ruta, TOML_CANONICO.replace("volumen = 0", "volumen = 99"))

    assert configuracion.sonidos_recinto.sonidos[0].volumen == volumen_original


# =============================================================================
# 2. Configuración inválida
# =============================================================================


def test_falta_la_seccion_sonidos(tmp_path: Path) -> None:
    """Sin sección no hay audio configurable: la carga falla explícitamente."""

    contenido = TOML_CANONICO[: TOML_CANONICO.index("[sonidos.")]
    ruta = escribir_system_toml(tmp_path / "system.toml", contenido)

    with pytest.raises(ErrorValidacionConfiguracion, match=r"falta la sección \[sonidos\]"):
        cargar_configuracion_sistema(ruta)


def test_falta_un_evento_obligatorio(tmp_path: Path) -> None:
    """Los quince eventos son obligatorios, ninguno es opcional."""

    ruta = escribir_system_toml(tmp_path / "system.toml", _toml_con_sonido("concejal_presente", ""))

    with pytest.raises(
        ErrorValidacionConfiguracion,
        match=r"falta la sección \[sonidos\.concejal_presente\]",
    ):
        cargar_configuracion_sistema(ruta)


def test_rechaza_un_evento_desconocido(tmp_path: Path) -> None:
    """Un nombre mal escrito debe fallar, no quedar silenciosamente inerte."""

    contenido = TOML_CANONICO + '\n[sonidos.sesion_abierrta]\nruta = "assets/sonidos/x.wav"\n'
    ruta = escribir_system_toml(tmp_path / "system.toml", contenido)

    with pytest.raises(ErrorValidacionConfiguracion, match="eventos desconocidos: sesion_abierrta"):
        cargar_configuracion_sistema(ruta)


def test_rechaza_una_clave_desconocida_dentro_de_un_evento(tmp_path: Path) -> None:
    """Sólo existen ``ruta`` y ``volumen``; cualquier otra clave es un error."""

    cuerpo = (
        "[sonidos.sesion_abierta]\n"
        'ruta = "assets/sonidos/sesion-abierta.wav"\n'
        "volumen = 90\n"
        "repeticiones = 3\n"
    )
    ruta = escribir_system_toml(
        tmp_path / "system.toml", _toml_con_sonido("sesion_abierta", cuerpo)
    )

    with pytest.raises(ErrorValidacionConfiguracion, match="claves desconocidas: repeticiones"):
        cargar_configuracion_sistema(ruta)


@pytest.mark.parametrize(
    ("valor", "descripcion"),
    [
        ("-1", "negativo"),
        ("101", "mayor que cien"),
        ("70.0", "decimal"),
        ("true", "booleano"),
        ('"70"', "texto"),
    ],
    ids=["negativo", "mayor-que-cien", "decimal", "booleano", "texto"],
)
def test_rechaza_volumenes_invalidos(tmp_path: Path, valor: str, descripcion: str) -> None:
    """El volumen es un entero de 0 a 100; nada más se acepta (WP-065 CA-2).

    El caso decimal y el booleano son los importantes: Python trataría ``70.0``
    como número y ``true`` como ``1`` si la validación no los rechazara a mano.
    """

    cuerpo = (
        "[sonidos.votacion_abierta]\n"
        'ruta = "assets/sonidos/votacion-abierta.wav"\n'
        f"volumen = {valor}\n"
    )
    ruta = escribir_system_toml(
        tmp_path / "system.toml", _toml_con_sonido("votacion_abierta", cuerpo)
    )

    with pytest.raises(ErrorValidacionConfiguracion, match=r"sonidos\.votacion_abierta\.volumen"):
        cargar_configuracion_sistema(ruta)
    assert descripcion  # el identificador del caso documenta qué se probó


@pytest.mark.parametrize(
    ("ruta_configurada", "fragmento_error"),
    [
        ("https://cdn.example.com/campana.wav", "URL externa"),
        ("//cdn.example.com/campana.wav", "URL externa"),
        ("/etc/passwd.wav", "assets/sonidos/"),
        ("sonidos/campana.wav", "assets/sonidos/"),
        ("assets/sonidos/../../../etc/passwd.wav", "segmentos vacíos ni relativos"),
        ("assets\\sonidos\\campana.wav", "barras invertidas"),
        ("assets/sonidos/campana.mp3", "debe terminar en .wav"),
        ("", "texto no vacío"),
    ],
    ids=[
        "url-https",
        "url-protocolo-relativo",
        "ruta-absoluta",
        "prefijo-incorrecto",
        "traversal",
        "barra-invertida",
        "extension-incorrecta",
        "vacia",
    ],
)
def test_rechaza_rutas_no_admitidas(
    tmp_path: Path, ruta_configurada: str, fragmento_error: str
) -> None:
    """La ruta proyectada al navegador nunca puede ser arbitraria (CA-4)."""

    # Se usa un literal TOML con comillas simples: no interpreta secuencias de
    # escape, así que la variante con barras invertidas llega intacta al
    # validador en lugar de fallar antes, al parsear el archivo.
    cuerpo = f"[sonidos.sesion_cerrada]\nruta = '{ruta_configurada}'\nvolumen = 50\n"
    ruta = escribir_system_toml(
        tmp_path / "system.toml", _toml_con_sonido("sesion_cerrada", cuerpo)
    )

    with pytest.raises(ErrorValidacionConfiguracion) as error:
        cargar_configuracion_sistema(ruta)
    assert "sonidos.sesion_cerrada.ruta" in str(error.value)
    assert fragmento_error in str(error.value)


# =============================================================================
# 3. Arranque tolerante
# =============================================================================


def test_arranque_con_archivo_inexistente_degrada_sin_excepcion(tmp_path: Path) -> None:
    """Un TOML ausente no puede impedir que el backend arranque."""

    sonidos = leer_sonidos_recinto(tmp_path / "no-existe.toml")

    assert sonidos.disponible is False
    assert sonidos.motivo == MOTIVO_SONIDOS_INVALIDOS
    assert sonidos.sonidos == ()
    assert sonidos.detalle is not None


def test_arranque_con_toml_invalido_degrada_sin_excepcion(tmp_path: Path) -> None:
    """Un archivo corrupto degrada sólo el audio, no el resto del sistema."""

    ruta = escribir_system_toml(tmp_path / "system.toml", "[sonidos\nesto no es TOML")

    sonidos = leer_sonidos_recinto(ruta)

    assert sonidos.disponible is False
    assert sonidos.motivo == MOTIVO_SONIDOS_INVALIDOS


def test_arranque_con_seccion_invalida_degrada_sin_excepcion(tmp_path: Path) -> None:
    """Un volumen fuera de rango tampoco puede tumbar el arranque."""

    cuerpo = (
        '[sonidos.concejal_ausente]\nruta = "assets/sonidos/concejal-ausente.wav"\nvolumen = 300\n'
    )
    ruta = escribir_system_toml(
        tmp_path / "system.toml", _toml_con_sonido("concejal_ausente", cuerpo)
    )

    sonidos = leer_sonidos_recinto(ruta)

    assert sonidos.disponible is False
    assert "volumen" in (sonidos.detalle or "")


def test_arranque_con_archivo_valido_carga_los_quince(ruta_system_toml_valido: Path) -> None:
    """El camino feliz del arranque entrega exactamente el mismo contrato."""

    sonidos = leer_sonidos_recinto(ruta_system_toml_valido)

    assert sonidos.disponible is True
    assert len(sonidos.sonidos) == len(EVENTOS_SONIDO_RECINTO)


# =============================================================================
# 4. Assets versionados
# =============================================================================


def test_hay_exactamente_veintidos_wav_versionados() -> None:
    """WP-065 fija la cantidad: 15 asignados + 7 alternativas, ni uno más."""

    archivos = sorted(ruta.name for ruta in DIRECTORIO_SONIDOS.glob("*.wav"))

    assert len(RECETAS_ASIGNADAS) == 15
    assert len(RECETAS_ALTERNATIVAS) == 7
    assert archivos == sorted(receta.nombre_archivo for receta in RECETAS)


def test_las_quince_rutas_configuradas_resuelven_a_assets_reales() -> None:
    """La configuración versionada del repositorio debe ser desplegable tal cual."""

    configuracion = cargar_configuracion_sistema(RUTA_SYSTEM_TOML)

    # No lanza: cada ruta existe y queda dentro de la raíz pública del Recinto.
    validar_assets_sonidos(configuracion.sonidos_recinto, RAIZ_PUBLICA_RECINTO)


def test_las_siete_alternativas_no_estan_asignadas_a_ningun_evento() -> None:
    """Las alternativas existen justamente para no estar en uso todavía."""

    configuracion = cargar_configuracion_sistema(RUTA_SYSTEM_TOML)
    asignadas = {sonido.ruta for sonido in configuracion.sonidos_recinto.sonidos}

    for receta in RECETAS_ALTERNATIVAS:
        assert f"assets/sonidos/{receta.nombre_archivo}" not in asignadas


def test_un_asset_faltante_produce_error_de_configuracion(tmp_path: Path) -> None:
    """La validación de despliegue detecta una ruta que no existe."""

    configuracion = cargar_configuracion_sistema(RUTA_SYSTEM_TOML)

    with pytest.raises(ErrorValidacionConfiguracion, match="archivo inexistente"):
        validar_assets_sonidos(configuracion.sonidos_recinto, tmp_path)


def test_los_wav_versionados_son_los_que_genera_el_script(tmp_path: Path) -> None:
    """Demuestra la procedencia: los 22 archivos son reproducibles byte a byte.

    Es la prueba que sostiene la afirmación de licencia del README de assets.
    Si alguien reemplazara un archivo por una grabación de terceros, o
    modificara una receta sin regenerar, esta comparación fallaría.
    """

    generar(tmp_path)

    for receta in RECETAS:
        versionado = (DIRECTORIO_SONIDOS / receta.nombre_archivo).read_bytes()
        regenerado = (tmp_path / receta.nombre_archivo).read_bytes()
        assert hashlib.sha256(versionado).hexdigest() == hashlib.sha256(regenerado).hexdigest(), (
            f"{receta.nombre_archivo} difiere de su receta versionada"
        )


def test_los_wav_declaran_el_formato_esperado() -> None:
    """WAV PCM mono de 16 bits a 44,1 kHz: el formato que todo navegador lee."""

    import wave

    for receta in RECETAS:
        with wave.open(str(DIRECTORIO_SONIDOS / receta.nombre_archivo), "rb") as archivo:
            assert archivo.getnchannels() == 1
            assert archivo.getsampwidth() == 2
            assert archivo.getframerate() == 44100
            # Ningún aviso puede durar tanto como para pisar al siguiente hecho
            # institucional: se acota a dos segundos.
            assert 0 < archivo.getnframes() / archivo.getframerate() <= 2.0


# =============================================================================
# 5. Validación de despliegue
# =============================================================================


def _preparar_instalacion(tmp_path: Path, *, copiar_sonidos: bool) -> tuple[Path, Path]:
    """Arma una instalación productiva mínima y devuelve ``(raiz, release)``.

    Reproduce el árbol real que ve ``deploy/validar_configuracion.py``: la raíz
    contiene ``config/`` y ``logs/``, y la release publica la SPA del Recinto
    bajo ``web/recinto``. Se copian los archivos canónicos del repositorio para
    que la prueba valide la configuración que realmente se despliega.
    """

    raiz = tmp_path / "instalacion"
    (raiz / "config/bridge").mkdir(parents=True)
    (raiz / "logs").mkdir()
    shutil.copy(RUTA_SYSTEM_TOML, raiz / "config/system.toml")
    shutil.copy(RAIZ_REPOSITORIO / "config/concejales.example.csv", raiz / "config/concejales.csv")
    shutil.copy(
        RAIZ_REPOSITORIO / "services/device-bridge/config/devices.example.json",
        raiz / "config/bridge/devices.json",
    )

    release = tmp_path / "release"
    destino_web = release / "web/recinto/assets"
    destino_web.mkdir(parents=True)
    if copiar_sonidos:
        shutil.copytree(DIRECTORIO_SONIDOS, destino_web / "sonidos")
    return raiz, release


def test_la_validacion_de_despliegue_acepta_una_release_completa(tmp_path: Path) -> None:
    """Con los 22 assets publicados, activar la release no encuentra problemas."""

    raiz, release = _preparar_instalacion(tmp_path, copiar_sonidos=True)

    validar_despliegue(raiz, release)


def test_la_validacion_de_despliegue_rechaza_una_release_sin_sonidos(tmp_path: Path) -> None:
    """Una release que no publicó los assets no debe llegar a activarse."""

    raiz, release = _preparar_instalacion(tmp_path, copiar_sonidos=False)

    with pytest.raises(ErrorValidacionConfiguracion, match="archivo inexistente"):
        validar_despliegue(raiz, release)
