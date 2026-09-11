"""Pruebas del bootstrap de configuración operativa local (WP-073).

Qué se demuestra acá
--------------------

1. el comando **crea** los cuatro archivos operativos cuando faltan;
2. **preserva byte a byte** los que ya existen, aunque su contenido no se
   parezca a la plantilla;
3. es **idempotente**: la segunda ejecución no toca nada;
4. crea los **directorios faltantes** del destino;
5. informa el fallo y termina con **código distinto de cero** ante un error real
   de E/S o ante una plantilla ausente;
6. la separación quedó bien declarada en Git: en un repositorio de prueba que
   usa el `.gitignore` real del proyecto, los cuatro archivos operativos quedan
   **ignorados** y las cuatro plantillas siguen siendo **trackeables**;
7. desde WP-098 existe además una tabla de **recursos por directorio**: copia
   sólo los archivos que faltan, preserva los que el operador ya reemplazó y no
   borra los que agregó. Ése es el modelo que WP-100 debe reutilizar para
   incorporar recursos nuevos sin pisar la configuración de una instalación.

El punto 2 es el que protege el trabajo operativo real: `mensajes.csv` lo
administra el backend por REST y `devices.json` lo reescribe el device bridge al
remapear, así que sobrescribirlos destruiría datos que no están en ningún commit.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.preparar_config_local import (
    ARCHIVOS_CONFIGURACION_LOCAL,
    DIRECTORIOS_CONFIGURACION_LOCAL,
    ArchivoConfiguracionLocal,
    DirectorioConfiguracionLocal,
    ErrorPreparacionConfigLocal,
    describir_resultados,
    main,
    materializar_archivo,
    materializar_directorio,
    preparar_configuracion_local,
    preparar_directorios_configuracion_local,
)

RAIZ_REPOSITORIO = Path(__file__).resolve().parents[1]
RUTA_GITIGNORE = RAIZ_REPOSITORIO / ".gitignore"


def crear_checkout_con_plantillas(raiz: Path) -> None:
    """Arma un checkout mínimo que sólo contiene las cuatro plantillas versionadas.

    Reproduce exactamente la situación de un clon nuevo: existen los
    `*.example.*` y no existe ninguno de los archivos operativos. El contenido
    de cada plantilla se inventa —lo que se prueba es el mecanismo de copia, no
    el formato, que ya tiene sus propias pruebas de carga.
    """

    for archivo in ARCHIVOS_CONFIGURACION_LOCAL:
        ruta_plantilla = raiz / archivo.plantilla
        ruta_plantilla.parent.mkdir(parents=True, exist_ok=True)
        ruta_plantilla.write_text(f"# plantilla de {archivo.destino.name}\n", encoding="utf-8")

    # Desde WP-098 un checkout completo incluye también los directorios
    # plantilla. Se siembran con tres archivos por directorio: alcanza para
    # distinguir «creado», «preservado» y «agregado por el operador».
    for directorio in DIRECTORIOS_CONFIGURACION_LOCAL:
        ruta_plantilla = raiz / directorio.plantilla
        ruta_plantilla.mkdir(parents=True, exist_ok=True)
        for indice in range(1, 4):
            nombre = f"recurso-{indice:02d}.png"
            (ruta_plantilla / nombre).write_bytes(f"plantilla {nombre}".encode())


# =============================================================================
# 1. Creación desde las plantillas
# =============================================================================


def test_crea_los_cuatro_archivos_operativos_cuando_faltan(tmp_path: Path) -> None:
    """En un clon nuevo aparecen las cuatro rutas runtime con el contenido de su ejemplo."""

    crear_checkout_con_plantillas(tmp_path)

    resultados = preparar_configuracion_local(tmp_path)

    assert [resultado.creado for resultado in resultados] == [True, True, True, True]
    for archivo in ARCHIVOS_CONFIGURACION_LOCAL:
        destino = tmp_path / archivo.destino
        assert destino.is_file(), f"No se creó {archivo.destino}"
        assert destino.read_bytes() == (tmp_path / archivo.plantilla).read_bytes()


def test_crea_los_directorios_que_falten(tmp_path: Path) -> None:
    """Un destino cuyo directorio todavía no existe se materializa igual.

    Las cuatro plantillas actuales viven en el mismo directorio que su destino,
    así que en un clon real el directorio nunca falta. La regla 3 del contrato
    igual debe cumplirse, porque protege dos casos concretos: alguien que borró
    ``config/apoyo-tecnico/`` a mano, y una entrada futura de la tabla que
    apunte a un subdirectorio nuevo. Por eso se prueba con una entrada armada al
    efecto en lugar de simular un estado que un clon no puede tener.
    """

    plantilla = Path("config/ejemplo.example.txt")
    (tmp_path / plantilla).parent.mkdir(parents=True)
    (tmp_path / plantilla).write_text("contenido de referencia\n", encoding="utf-8")
    archivo = ArchivoConfiguracionLocal(
        plantilla=plantilla,
        destino=Path("config/subdirectorio/nuevo/ejemplo.txt"),
        descripcion="entrada de prueba con directorio ausente",
    )

    resultado = materializar_archivo(archivo, tmp_path)

    assert resultado.creado is True
    assert (tmp_path / archivo.destino).read_text(encoding="utf-8") == "contenido de referencia\n"


# =============================================================================
# 2. Preservación e idempotencia
# =============================================================================


def test_preserva_byte_a_byte_un_archivo_operativo_existente(tmp_path: Path) -> None:
    """Un archivo local con contenido propio no se toca, ni siquiera parcialmente."""

    crear_checkout_con_plantillas(tmp_path)
    ruta_biblioteca = tmp_path / "config/apoyo-tecnico/mensajes.csv"
    contenido_operativo = "id,texto,destino\nm1,Mensaje real del recinto,RECINTO\n"
    ruta_biblioteca.write_text(contenido_operativo, encoding="utf-8")

    resultados = preparar_configuracion_local(tmp_path)

    por_destino = {resultado.archivo.destino.as_posix(): resultado for resultado in resultados}
    assert por_destino["config/apoyo-tecnico/mensajes.csv"].creado is False
    assert ruta_biblioteca.read_text(encoding="utf-8") == contenido_operativo


def test_la_segunda_ejecucion_es_idempotente(tmp_path: Path) -> None:
    """Repetir el comando no crea ni modifica nada: mismo contenido y misma mtime."""

    crear_checkout_con_plantillas(tmp_path)
    preparar_configuracion_local(tmp_path)

    huellas_previas = {
        archivo.destino: (
            (tmp_path / archivo.destino).read_bytes(),
            (tmp_path / archivo.destino).stat().st_mtime_ns,
        )
        for archivo in ARCHIVOS_CONFIGURACION_LOCAL
    }

    resultados = preparar_configuracion_local(tmp_path)

    assert [resultado.creado for resultado in resultados] == [False, False, False, False]
    for archivo in ARCHIVOS_CONFIGURACION_LOCAL:
        destino = tmp_path / archivo.destino
        contenido, mtime = huellas_previas[archivo.destino]
        assert destino.read_bytes() == contenido
        assert destino.stat().st_mtime_ns == mtime


def test_un_archivo_vacio_tambien_se_preserva(tmp_path: Path) -> None:
    """Vacío es un estado operativo válido y no debe confundirse con «ausente».

    La biblioteca de Apoyo Técnico queda vacía cuando el operador borra todos
    sus mensajes precargados. Rellenarla desde la plantilla sería restaurar
    mensajes que alguien decidió eliminar.
    """

    crear_checkout_con_plantillas(tmp_path)
    ruta_biblioteca = tmp_path / "config/apoyo-tecnico/mensajes.csv"
    ruta_biblioteca.write_text("", encoding="utf-8")

    preparar_configuracion_local(tmp_path)

    assert ruta_biblioteca.read_text(encoding="utf-8") == ""


# =============================================================================
# 3. Fallos reales
# =============================================================================


def test_falla_si_no_puede_crear_el_directorio_de_destino(tmp_path: Path) -> None:
    """Un error de E/S se reporta como tal en lugar de dejar el checkout a medias.

    Se fuerza el fallo poniendo un archivo común donde debería ir el directorio
    del destino: ``mkdir`` no puede crear un directorio con el nombre de un
    archivo existente, en Linux y en Windows por igual.
    """

    plantilla = Path("config/ejemplo.example.txt")
    (tmp_path / plantilla).parent.mkdir(parents=True)
    (tmp_path / plantilla).write_text("contenido de referencia\n", encoding="utf-8")
    (tmp_path / "config/bloqueado").write_text("no soy un directorio", encoding="utf-8")
    archivo = ArchivoConfiguracionLocal(
        plantilla=plantilla,
        destino=Path("config/bloqueado/ejemplo.txt"),
        descripcion="entrada de prueba con E/S imposible",
    )

    with pytest.raises(ErrorPreparacionConfigLocal) as excepcion:
        materializar_archivo(archivo, tmp_path)

    assert "No se pudo crear" in str(excepcion.value)


def test_falla_si_falta_una_plantilla_versionada(tmp_path: Path) -> None:
    """Un checkout incompleto se denuncia en vez de dejar al backend sin configuración."""

    crear_checkout_con_plantillas(tmp_path)
    (tmp_path / ARCHIVOS_CONFIGURACION_LOCAL[0].plantilla).unlink()

    with pytest.raises(ErrorPreparacionConfigLocal) as excepcion:
        materializar_archivo(ARCHIVOS_CONFIGURACION_LOCAL[0], tmp_path)

    assert "Falta la plantilla versionada" in str(excepcion.value)


def test_main_devuelve_cero_al_preparar_y_uno_ante_un_fallo(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """El código de salida es el contrato que usan `pnpm dev:stack` y la CI."""

    crear_checkout_con_plantillas(tmp_path)

    assert main(["--raiz", str(tmp_path)]) == 0
    salida_exitosa = capsys.readouterr().out
    assert "4 creado(s), 0 preservado(s)" in salida_exitosa

    (tmp_path / ARCHIVOS_CONFIGURACION_LOCAL[0].destino).unlink()
    (tmp_path / ARCHIVOS_CONFIGURACION_LOCAL[0].plantilla).unlink()

    assert main(["--raiz", str(tmp_path)]) == 1
    assert "Error:" in capsys.readouterr().err


def test_el_informe_distingue_creados_de_preservados(tmp_path: Path) -> None:
    """La salida tiene que permitir auditar qué pasó con cada archivo."""

    crear_checkout_con_plantillas(tmp_path)
    resultados = preparar_configuracion_local(tmp_path)
    informe_creacion = describir_resultados(resultados)

    assert "creado desde la plantilla" in informe_creacion
    assert "preservado sin cambios" not in informe_creacion

    informe_preservacion = describir_resultados(preparar_configuracion_local(tmp_path))
    assert "preservado sin cambios" in informe_preservacion
    assert "creado desde la plantilla" not in informe_preservacion


# =============================================================================
# 3 bis. Recursos por directorio (WP-098)
# =============================================================================


def test_crea_los_recursos_de_directorio_que_falten(tmp_path: Path) -> None:
    """En un clon nuevo aparecen todas las fotos de referencia bajo la ruta runtime."""

    crear_checkout_con_plantillas(tmp_path)

    resultados = preparar_directorios_configuracion_local(tmp_path)

    assert len(resultados) == len(DIRECTORIOS_CONFIGURACION_LOCAL)
    for resultado in resultados:
        origen = tmp_path / resultado.directorio.plantilla
        destino = tmp_path / resultado.directorio.destino
        esperados = sorted(archivo.name for archivo in origen.iterdir())
        assert list(resultado.creados) == esperados
        assert resultado.preservados == ()
        for nombre in esperados:
            assert (destino / nombre).read_bytes() == (origen / nombre).read_bytes()


def test_preserva_los_recursos_que_el_operador_ya_reemplazo(tmp_path: Path) -> None:
    """El corazón del modelo que hereda WP-100: agregar lo que falta, nunca pisar.

    Se simula una instalación donde ya se cargó la foto real de un concejal: ese
    archivo debe quedar byte a byte intacto mientras los que faltan se crean.
    """

    crear_checkout_con_plantillas(tmp_path)
    directorio = DIRECTORIOS_CONFIGURACION_LOCAL[0]
    destino = tmp_path / directorio.destino
    destino.mkdir(parents=True)
    foto_real = destino / "recurso-02.png"
    contenido_real = b"foto real cargada por el operador"
    foto_real.write_bytes(contenido_real)

    resultado = materializar_directorio(directorio, tmp_path)

    assert "recurso-02.png" in resultado.preservados
    assert "recurso-02.png" not in resultado.creados
    assert foto_real.read_bytes() == contenido_real
    assert sorted(resultado.creados) == ["recurso-01.png", "recurso-03.png"]


def test_no_borra_un_recurso_que_la_plantilla_no_tiene(tmp_path: Path) -> None:
    """Una foto agregada por el operador le pertenece: nadie la elimina.

    Es el caso de un concejal nuevo cuya foto no existe en el repositorio. El
    bootstrap sólo agrega; sincronizar en el otro sentido borraría trabajo real.
    """

    crear_checkout_con_plantillas(tmp_path)
    directorio = DIRECTORIOS_CONFIGURACION_LOCAL[0]
    destino = tmp_path / directorio.destino
    destino.mkdir(parents=True)
    propia = destino / "concejal-nuevo.png"
    propia.write_bytes(b"foto que solo existe en esta instalacion")

    materializar_directorio(directorio, tmp_path)

    assert propia.read_bytes() == b"foto que solo existe en esta instalacion"


def test_repetir_la_preparacion_de_directorios_es_idempotente(tmp_path: Path) -> None:
    """La segunda ejecución no crea ni reescribe: mismo contenido y misma mtime."""

    crear_checkout_con_plantillas(tmp_path)
    preparar_directorios_configuracion_local(tmp_path)
    destino = tmp_path / DIRECTORIOS_CONFIGURACION_LOCAL[0].destino
    huellas = {
        archivo.name: (archivo.read_bytes(), archivo.stat().st_mtime_ns)
        for archivo in destino.iterdir()
    }

    resultados = preparar_directorios_configuracion_local(tmp_path)

    assert all(resultado.creados == () for resultado in resultados)
    for archivo in destino.iterdir():
        contenido, mtime = huellas[archivo.name]
        assert archivo.read_bytes() == contenido
        assert archivo.stat().st_mtime_ns == mtime


def test_falla_si_falta_el_directorio_plantilla_versionado(tmp_path: Path) -> None:
    """Un checkout incompleto se denuncia en vez de dejar bancas sin fotografía."""

    directorio = DirectorioConfiguracionLocal(
        plantilla=Path("config/inexistente.example/recursos"),
        destino=Path("config/inexistente/recursos"),
        descripcion="entrada de prueba sin plantilla",
    )

    with pytest.raises(ErrorPreparacionConfigLocal) as excepcion:
        materializar_directorio(directorio, tmp_path)

    assert "Falta el directorio plantilla versionado" in str(excepcion.value)


def test_el_informe_resume_los_recursos_por_directorio(tmp_path: Path) -> None:
    """La salida tiene que permitir auditar también lo que pasó con las fotos."""

    crear_checkout_con_plantillas(tmp_path)
    archivos = preparar_configuracion_local(tmp_path)
    directorios = preparar_directorios_configuracion_local(tmp_path)

    informe = describir_resultados(archivos, directorios)

    assert "Recursos de configuración por directorio (WP-098)" in informe
    assert "Resumen por directorio: 3 archivo(s) creado(s), 0 preservado(s)." in informe

    # Sin recursos por directorio, el informe conserva exactamente su forma previa.
    assert "por directorio" not in describir_resultados(archivos)


def test_el_comando_completo_prepara_archivos_y_directorios(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`pnpm preparar:config` deja listo todo lo que el backend lee en ejecución."""

    crear_checkout_con_plantillas(tmp_path)

    assert main(["--raiz", str(tmp_path)]) == 0

    salida = capsys.readouterr().out
    assert "4 creado(s), 0 preservado(s)" in salida
    assert "Resumen por directorio: 3 archivo(s) creado(s), 0 preservado(s)." in salida
    destino = tmp_path / DIRECTORIOS_CONFIGURACION_LOCAL[0].destino
    assert sorted(archivo.name for archivo in destino.iterdir()) == [
        "recurso-01.png",
        "recurso-02.png",
        "recurso-03.png",
    ]


# =============================================================================
# 4. Evidencia Git de la separación
# =============================================================================


def ejecutar_git(raiz: Path, *argumentos: str) -> subprocess.CompletedProcess[str]:
    """Ejecuta Git sin shell dentro del repositorio de prueba."""

    return subprocess.run(
        ["git", *argumentos],
        cwd=raiz,
        capture_output=True,
        text=True,
        check=False,
    )


def test_git_ignora_los_operativos_y_conserva_trackeables_las_plantillas(tmp_path: Path) -> None:
    """Comprueba el efecto real del `.gitignore` versionado, no una suposición.

    Se arma un repositorio Git temporal con el `.gitignore` exacto del proyecto,
    se materializan los cuatro archivos operativos desde sus plantillas y se
    agrega todo. El resultado esperado es el corazón de WP-073: Git ve las
    cuatro plantillas y no ve ninguno de los cuatro archivos operativos, de modo
    que editar la configuración local deja `git status --short` vacío.
    """

    repositorio = tmp_path / "repositorio"
    repositorio.mkdir()
    inicializacion = ejecutar_git(repositorio, "init", "--quiet")
    if inicializacion.returncode != 0:  # pragma: no cover - entorno sin Git
        pytest.skip("Git no está disponible en este entorno.")

    (repositorio / ".gitignore").write_bytes(RUTA_GITIGNORE.read_bytes())
    crear_checkout_con_plantillas(repositorio)
    preparar_configuracion_local(repositorio)
    preparar_directorios_configuracion_local(repositorio)

    assert ejecutar_git(repositorio, "add", "-A").returncode == 0
    trackeados = set(ejecutar_git(repositorio, "ls-files").stdout.split())

    # Se confirma el commit inicial para que `git status` refleje sólo lo que
    # cambie después. La identidad se pasa por línea de comandos: la prueba no
    # depende de la configuración Git global de quien la ejecuta.
    confirmacion = ejecutar_git(
        repositorio,
        "-c",
        "user.name=Prueba WP-073",
        "-c",
        "user.email=wp073@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "--quiet",
        "-m",
        "commit inicial de la prueba",
    )
    assert confirmacion.returncode == 0, confirmacion.stderr

    for archivo in ARCHIVOS_CONFIGURACION_LOCAL:
        assert archivo.plantilla.as_posix() in trackeados, (
            f"La plantilla {archivo.plantilla} debe seguir siendo revisable en Git."
        )
        assert archivo.destino.as_posix() not in trackeados, (
            f"El archivo operativo {archivo.destino} no debe versionarse."
        )

    # WP-098: la misma separación rige para los recursos por directorio. Las
    # fotos de referencia se revisan en la PR; las de la instalación no existen
    # para Git, así que cargar la foto real de un concejal no ensucia el checkout.
    for directorio in DIRECTORIOS_CONFIGURACION_LOCAL:
        origen = repositorio / directorio.plantilla
        for archivo_plantilla in origen.iterdir():
            ruta_relativa = (directorio.plantilla / archivo_plantilla.name).as_posix()
            assert ruta_relativa in trackeados, (
                f"La plantilla {ruta_relativa} debe seguir siendo revisable en Git."
            )
            ruta_operativa = (directorio.destino / archivo_plantilla.name).as_posix()
            assert ruta_operativa not in trackeados, (
                f"El recurso operativo {ruta_operativa} no debe versionarse."
            )

    # Modificar la configuración local no ensucia el checkout: ésta es la razón
    # por la que `scripts/iniciar_wp_orca.py` dejaba de poder iniciar un WP.
    (repositorio / "config/system.toml").write_text("quorum = 999\n", encoding="utf-8")
    (repositorio / "config/.system.toml.swp").write_bytes(b"temporal de vim")
    (repositorio / "config/assets/bancas/recurso-01.png").write_bytes(b"foto real")
    assert ejecutar_git(repositorio, "status", "--short").stdout.strip() == ""

    # Un cambio real en una plantilla sí tiene que aparecer y seguir siendo revisable.
    (repositorio / ARCHIVOS_CONFIGURACION_LOCAL[0].plantilla).write_text(
        "# plantilla corregida\n", encoding="utf-8"
    )
    estado = ejecutar_git(repositorio, "status", "--short").stdout
    assert ARCHIVOS_CONFIGURACION_LOCAL[0].plantilla.as_posix() in estado
