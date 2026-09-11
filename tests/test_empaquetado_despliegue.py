"""Pruebas de seguridad, atomicidad y rollback del mecanismo productivo."""

from __future__ import annotations

import io
import json
import stat
import subprocess
import sys
import tarfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

import deploy.herramienta_despliegue as modulo_despliegue
import scripts.verificar_reproducibilidad_produccion as modulo_reproducibilidad
from deploy.herramienta_despliegue import (
    DIRECTORIO_SONDAS_RUNTIME,
    EjecutorSubprocess,
    ErrorDespliegue,
    GestorDespliegue,
    ResultadoComando,
    extraer_paquete_seguro,
    plan_permisos,
    resolver_enlace_release,
    validar_manifest,
    verificar_checksum,
)
from scripts.empaquetar_produccion import construir_paquete, sha256_archivo
from scripts.verificar_reproducibilidad_produccion import ErrorReproducibilidad

SHA_A = "a" * 40
SHA_B = "b" * 40


def crear_checkout_minimo(raiz: Path) -> None:
    """Construye la allowlist mínima que consume el empaquetador real."""

    archivos = {
        "pyproject.toml": "[project]\nname='raiz'\nversion='0'\n",
        "uv.lock": "version = 1\n",
        ".python-version": "3.14\n",
        "apps/backend/pyproject.toml": "[project]\nname='sis-leg-backend'\nversion='0'\n",
        "apps/backend/src/sis_leg_backend/__init__.py": "",
        "services/device-bridge/pyproject.toml": (
            "[project]\nname='sis-leg-device-bridge'\nversion='0'\n"
        ),
        "services/device-bridge/src/sis_leg_device_bridge/__init__.py": "",
        "apps/moderacion/.output/public/index.html": "<!doctype html>Moderación",
        "apps/moderacion/.output/public/_nuxt/app.js": "m",
        "apps/recinto/.output/public/index.html": "<!doctype html>Recinto",
        "apps/recinto/.output/public/_nuxt/app.js": "r",
        "apps/simulador/.output/public/index.html": "<!doctype html>Simulador",
        "apps/simulador/.output/public/_nuxt/app.js": "s",
        "apps/tecnico/.output/public/index.html": "<!doctype html>Apoyo Técnico",
        "apps/tecnico/.output/public/_nuxt/app.js": "t",
        "apps/zocalo/.output/public/index.html": "<!doctype html>Zócalo",
        "apps/zocalo/.output/public/_nuxt/app.js": "z",
        "manual/index.html": '<!doctype html><html lang="es"><body>SIS-Leg</body></html>',
        "deploy/__init__.py": "",
        "deploy/herramienta_despliegue.py": "# herramienta",
        "deploy/validar_configuracion.py": "# validador",
        "deploy/systemd/sis-leg-backend.service": "[Service]\n",
        "deploy/systemd/sis-leg-device-bridge.service": "[Service]\n",
        "deploy/nginx/sis-leg.conf": "server {}\n",
    }
    for relativa, contenido in archivos.items():
        ruta = raiz / relativa
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(contenido, encoding="utf-8")


def test_paquete_es_reproducible_trazable_y_excluye_configuracion(tmp_path: Path) -> None:
    """Mismo SHA/contenido produce bytes iguales y nunca empaqueta fixtures."""

    checkout = tmp_path / "checkout"
    crear_checkout_minimo(checkout)
    (checkout / "config").mkdir()
    (checkout / "config/system.toml").write_text("secreto='no'", encoding="utf-8")

    paquete_1, sidecar_1 = construir_paquete(
        raiz=checkout,
        directorio_salida=tmp_path / "salida-1",
        sha_commit=SHA_A,
        sha_arbol="c" * 40,
    )
    paquete_2, _ = construir_paquete(
        raiz=checkout,
        directorio_salida=tmp_path / "salida-2",
        sha_commit=SHA_A,
        sha_arbol="c" * 40,
    )

    assert paquete_1.name == f"sis-leg-{SHA_A}.tar.gz"
    assert sha256_archivo(paquete_1) == sha256_archivo(paquete_2)
    verificar_checksum(paquete_1, sidecar_1)
    with tarfile.open(paquete_1, "r:gz") as tar:
        nombres = tar.getnames()
        manifest = json.load(tar.extractfile("release.json"))  # type: ignore[arg-type]
    assert manifest["commit_sha"] == SHA_A
    assert "config/system.toml" not in nombres
    assert not any("node_modules" in nombre or ".venv" in nombre for nombre in nombres)
    # El manual (WP-067) viaja en la misma raíz web que las SPA y queda inventariado como
    # cualquier otro archivo, de modo que la reproducibilidad byte a byte también lo cubre.
    assert "web/manual/index.html" in nombres
    assert manifest["manual"] == "web/manual/index.html"
    assert any(entrada["ruta"] == "web/manual/index.html" for entrada in manifest["archivos"])


def test_gate_compara_dos_empaquetados_completos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dos ejecuciones idénticas dejan la segunda release y devuelven su hash."""

    salida = tmp_path / "dist/produccion"
    paquete = salida / f"sis-leg-{SHA_A}.tar.gz"
    sidecar = paquete.with_name(f"{paquete.name}.sha256")
    ejecuciones = 0

    def empaquetar_falso(raiz: Path) -> None:
        """Simula el comando público sin pagar dos builds Nuxt en este test."""

        nonlocal ejecuciones
        assert raiz == tmp_path
        ejecuciones += 1
        salida.mkdir(parents=True, exist_ok=True)
        paquete.write_bytes(b"release estable")
        sidecar.write_text("checksum estable\n", encoding="ascii")

    def devolver_sha_falso(*argumentos: str, raiz: Path = tmp_path) -> str:
        """Sustituye sólo la consulta Git usada para nombrar el paquete."""

        del argumentos, raiz
        return SHA_A

    monkeypatch.setattr(modulo_reproducibilidad, "_ejecutar_empaquetado", empaquetar_falso)
    monkeypatch.setattr(modulo_reproducibilidad, "ejecutar_git", devolver_sha_falso)

    checksum = modulo_reproducibilidad.verificar_reproducibilidad(tmp_path)

    assert ejecuciones == 2
    assert checksum == sha256_archivo(paquete)


@pytest.mark.parametrize("archivo_variable", ["paquete", "sidecar"])
def test_gate_rechaza_bytes_variables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    archivo_variable: str,
) -> None:
    """Una diferencia en el tar o su sidecar impide aceptar la release."""

    salida = tmp_path / "dist/produccion"
    paquete = salida / f"sis-leg-{SHA_A}.tar.gz"
    sidecar = paquete.with_name(f"{paquete.name}.sha256")
    ejecuciones = 0

    def empaquetar_falso(raiz: Path) -> None:
        """Introduce variación sólo en el archivo parametrizado."""

        nonlocal ejecuciones
        assert raiz == tmp_path
        ejecuciones += 1
        salida.mkdir(parents=True, exist_ok=True)
        sufijo_paquete = str(ejecuciones) if archivo_variable == "paquete" else "estable"
        sufijo_sidecar = str(ejecuciones) if archivo_variable == "sidecar" else "estable"
        paquete.write_bytes(f"release {sufijo_paquete}".encode())
        sidecar.write_text(f"checksum {sufijo_sidecar}\n", encoding="ascii")

    def devolver_sha_falso(*argumentos: str, raiz: Path = tmp_path) -> str:
        """Sustituye sólo la consulta Git usada para nombrar el paquete."""

        del argumentos, raiz
        return SHA_A

    monkeypatch.setattr(modulo_reproducibilidad, "_ejecutar_empaquetado", empaquetar_falso)
    monkeypatch.setattr(modulo_reproducibilidad, "ejecutar_git", devolver_sha_falso)

    with pytest.raises(ErrorReproducibilidad):
        modulo_reproducibilidad.verificar_reproducibilidad(tmp_path)

    assert ejecuciones == 2


@pytest.mark.parametrize(
    ("campo", "valor", "mensaje"),
    [
        ("tree_sha", "abreviado", "tree SHA"),
        ("spas", {"moderacion": "otra-ruta"}, "SPA canónicas"),
        ("paquetes_python", ["sis-leg-backend"], "paquetes Python canónicos"),
        ("manual", "web/otro/index.html", "manual de usuario canónico"),
    ],
    ids=["tree-sha", "spas", "paquetes-python", "manual"],
)
def test_manifest_rechaza_identidad_runtime_incompleta(
    tmp_path: Path, campo: str, valor: object, mensaje: str
) -> None:
    """El receptor no confía en metadatos parciales aunque el tar sea legible."""

    checkout = tmp_path / "checkout"
    crear_checkout_minimo(checkout)
    paquete, _ = construir_paquete(
        raiz=checkout,
        directorio_salida=tmp_path / "salida",
        sha_commit=SHA_A,
        sha_arbol="c" * 40,
    )
    with tarfile.open(paquete, "r:gz") as tar:
        manifest = json.load(tar.extractfile("release.json"))  # type: ignore[arg-type]
    manifest[campo] = valor

    with pytest.raises(ErrorDespliegue, match=mensaje):
        validar_manifest(manifest, SHA_A)


def test_checksum_adulterado_es_rechazado(tmp_path: Path) -> None:
    """Un solo byte distinto impide preparar antes de extraer."""

    paquete = tmp_path / "sis-leg.tar.gz"
    paquete.write_bytes(b"contenido")
    sidecar = tmp_path / "sis-leg.tar.gz.sha256"
    sidecar.write_text(f"{'0' * 64}  {paquete.name}\n", encoding="ascii")

    with pytest.raises(ErrorDespliegue, match="Checksum incorrecto"):
        verificar_checksum(paquete, sidecar)


def test_validador_release_directo_expone_ayuda() -> None:
    """La misma invocación que usa CI debe resolver imports desde ``scripts/``."""

    raiz = Path(__file__).resolve().parents[1]
    resultado = subprocess.run(
        [sys.executable, str(raiz / "scripts/validar_release_produccion.py"), "--help"],
        cwd=raiz,
        capture_output=True,
        text=True,
        check=False,
    )

    assert resultado.returncode == 0, resultado.stderr
    assert "Valida una release" in resultado.stdout


def test_bootstrap_es_idempotente_y_crea_solo_estructura_externa(tmp_path: Path) -> None:
    """Repetir bootstrap conserva directorios y no inventa datos institucionales."""

    gestor = crear_gestor(tmp_path)
    primer_plan = gestor.bootstrap()
    segundo_plan = gestor.bootstrap()

    assert primer_plan == segundo_plan == plan_permisos()
    assert gestor.releases.is_dir()
    assert (gestor.config / "bridge").is_dir()
    assert gestor.logs.is_dir()
    assert not (gestor.config / "system.toml").exists()
    assert not (gestor.config / "concejales.csv").exists()
    assert not (gestor.config / "bridge/devices.json").exists()


def test_bootstrap_aplica_el_plan_a_directorios_y_archivos_existentes(tmp_path: Path) -> None:
    """La segunda ejecución materializa ownership/modo sin inventar archivos."""

    ejecutor = EjecutorFalso()
    gestor = crear_gestor(tmp_path, ejecutor)
    gestor.bootstrap()
    crear_config_externa(gestor)

    plan = gestor.bootstrap(aplicar_usuarios=True)

    for entrada in plan:
        ruta = gestor.raiz / entrada.ruta_relativa
        assert [
            "chown",
            "--no-dereference",
            f"{entrada.usuario}:{entrada.grupo}",
            str(ruta),
        ] in ejecutor.llamadas
        assert ["chmod", f"{entrada.modo:04o}", str(ruta)] in ejecutor.llamadas


def test_preparar_es_idempotente_y_no_cambia_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La venv nace en la ruta final y repetir el mismo SHA no reinstala."""

    checkout = tmp_path / "checkout"
    crear_checkout_minimo(checkout)
    paquete, sidecar = construir_paquete(
        raiz=checkout,
        directorio_salida=tmp_path / "salida",
        sha_commit=SHA_A,
        sha_arbol="c" * 40,
    )
    ejecutor = EjecutorFalso()
    gestor = crear_gestor(tmp_path, ejecutor)

    # En producción root puede administrar un árbol 0555. El test evita ese
    # modo únicamente para que pytest retire su directorio temporal al final.
    def conservar_escribible(release: Path) -> None:
        del release

    monkeypatch.setattr(gestor, "_hacer_release_solo_lectura", conservar_escribible)

    release = gestor.preparar(paquete, sidecar, SHA_A)
    llamadas_primera = len(ejecutor.llamadas)
    repetida = gestor.preparar(paquete, sidecar, SHA_A)

    assert release == repetida == gestor.releases / SHA_A
    assert (release / ".venv/bin/uvicorn").is_file()
    assert resolver_enlace_release(gestor.current, gestor.releases) is None
    assert len(ejecutor.llamadas) == llamadas_primera
    llamada_uv = next(llamada for llamada in ejecutor.llamadas if llamada[:2] == ["uv", "sync"])
    python_base = str(Path("/usr/bin/python3").resolve())
    assert llamada_uv[llamada_uv.index("--python") + 1] == python_base
    assert "--no-python-downloads" in llamada_uv
    marcador = json.loads((release / modulo_despliegue.MARCADOR_PREPARADA).read_text())
    assert marcador["python_base"] == python_base


def crear_tar_malicioso(ruta: Path, nombre: str, *, tipo: bytes | None = None) -> None:
    """Crea una entrada controlada para probar traversal y enlaces."""

    with tarfile.open(ruta, "w:gz") as tar:
        datos = b"x"
        info = tarfile.TarInfo(nombre)
        if tipo is not None:
            info.type = tipo
            info.linkname = "../../escape"
            info.size = 0
            tar.addfile(info)
        else:
            info.size = len(datos)
            tar.addfile(info, io.BytesIO(datos))


@pytest.mark.parametrize(
    ("nombre", "tipo"),
    [("../escape", None), ("/absoluto", None), ("app/enlace", tarfile.SYMTYPE)],
    ids=["traversal", "absoluta", "symlink"],
)
def test_extraccion_rechaza_rutas_y_enlaces(
    tmp_path: Path, nombre: str, tipo: bytes | None
) -> None:
    """La inspección ocurre antes de que una entrada pueda escribir afuera."""

    paquete = tmp_path / "malicioso.tar.gz"
    crear_tar_malicioso(paquete, nombre, tipo=tipo)

    with pytest.raises(ErrorDespliegue):
        extraer_paquete_seguro(paquete, tmp_path / "destino", SHA_A)
    assert not (tmp_path / "escape").exists()


def test_solo_lectura_no_sigue_symlinks_fuera_de_release(tmp_path: Path) -> None:
    """La inmutabilidad jamás cambia bytes ni modo de targets externos."""

    externo = tmp_path / "externo"
    externo.mkdir(mode=0o775)
    archivo_externo = externo / "python3.14"
    archivo_externo.write_bytes(b"interprete compartido")
    archivo_externo.chmod(0o775)
    modo_directorio_antes = stat.S_IMODE(externo.stat().st_mode)
    modo_archivo_antes = stat.S_IMODE(archivo_externo.stat().st_mode)

    release = tmp_path / "release"
    interno = release / "app/modulo.py"
    interno.parent.mkdir(parents=True)
    interno.write_text("dato = 1\n", encoding="utf-8")
    (release / "python").symlink_to(archivo_externo)
    (release / "biblioteca-externa").symlink_to(externo, target_is_directory=True)

    GestorDespliegue._hacer_release_solo_lectura(  # pyright: ignore[reportPrivateUsage]
        release
    )

    assert archivo_externo.read_bytes() == b"interprete compartido"
    assert stat.S_IMODE(archivo_externo.stat().st_mode) == modo_archivo_antes
    assert stat.S_IMODE(externo.stat().st_mode) == modo_directorio_antes
    assert stat.S_IMODE(interno.stat().st_mode) & 0o222 == 0
    assert stat.S_IMODE(release.stat().st_mode) & 0o222 == 0
    assert (release / "python").is_symlink()
    assert (release / "biblioteca-externa").is_symlink()

    # pytest necesita volver a retirar el árbol temporal con el usuario normal.
    release.chmod(0o755)
    interno.parent.chmod(0o755)
    interno.chmod(0o644)


def test_python_base_rechaza_directorio_privado(tmp_path: Path) -> None:
    """Un Python bajo un home no atravesable no puede sostener la venv productiva."""

    privado = tmp_path / "home-privado"
    privado.mkdir(mode=0o700)
    python_privado = privado / "python3.14"
    python_privado.write_text("binario", encoding="utf-8")
    python_privado.chmod(0o755)
    gestor = GestorDespliegue(tmp_path / "opt/sis-leg", python_base=python_privado)

    with pytest.raises(ErrorDespliegue, match="no atravesable"):
        gestor._validar_python_base()  # pyright: ignore[reportPrivateUsage]


class EjecutorFalso:
    """Emula comandos privilegiados y materializa la venv mínima al preparar."""

    def __init__(self) -> None:
        self.llamadas: list[list[str]] = []
        self.invocaciones: list[tuple[list[str], Path | None, bool]] = []
        self.estado_backend = "active"

    def ejecutar(
        self,
        argumentos: Sequence[str],
        *,
        directorio: Path | None = None,
        entorno: Mapping[str, str] | None = None,
        comprobar: bool = True,
    ) -> ResultadoComando:
        args = [str(valor) for valor in argumentos]
        self.llamadas.append(args)
        self.invocaciones.append((args, directorio, comprobar))
        if len(args) >= 3 and args[1] == "-c" and "sys.version_info" in args[2]:
            return ResultadoComando(0, "3.14\n")
        if args[:2] == ["uv", "sync"]:
            assert directorio is not None and entorno is not None
            venv = Path(entorno["UV_PROJECT_ENVIRONMENT"])
            (venv / "bin").mkdir(parents=True)
            for nombre in ("python", "uvicorn", "sis-leg-device-bridge"):
                (venv / "bin" / nombre).write_text("ejecutable", encoding="utf-8")
        if args[:2] == ["systemctl", "is-active"]:
            return ResultadoComando(0, f"{self.estado_backend}\n")
        if args == ["id", "--groups", "--name", "sis-leg-backend"]:
            return ResultadoComando(0, "sis-leg-backend\n")
        if args == ["id", "--groups", "--name", "sis-leg-bridge"]:
            return ResultadoComando(0, "sis-leg-bridge input\n")
        return ResultadoComando(0)


def crear_release_preparada(gestor: GestorDespliegue, sha: str) -> Path:
    """Crea una release operacional mínima para probar activación sin uv real."""

    release = gestor.releases / sha
    requeridos = (
        ".venv/bin/python",
        ".venv/bin/uvicorn",
        ".venv/bin/sis-leg-device-bridge",
        "web/moderacion/index.html",
        "web/recinto/index.html",
        "web/simulador/index.html",
        "web/tecnico/index.html",
        "web/zocalo/index.html",
        "web/manual/index.html",
        "deploy/systemd/sis-leg-backend.service",
        "deploy/systemd/sis-leg-device-bridge.service",
        "deploy/nginx/sis-leg.conf",
        "deploy/validar_configuracion.py",
    )
    for relativa in requeridos:
        ruta = release / relativa
        ruta.parent.mkdir(parents=True, exist_ok=True)
        contenido = "<!doctype html>" if ruta.name == "index.html" else "archivo"
        ruta.write_text(contenido, encoding="utf-8")
    (release / modulo_despliegue.MARCADOR_PREPARADA).write_text(
        json.dumps({"commit_sha": sha}), encoding="utf-8"
    )
    return release


def crear_gestor(
    tmp_path: Path,
    ejecutor: EjecutorFalso | None = None,
    *,
    durmiente: Callable[[float], None] | None = None,
) -> GestorDespliegue:
    """Aísla todas las rutas que en producción pertenecen a /opt y /etc."""

    ejecutor = ejecutor or EjecutorFalso()

    def json_ok(url: str, timeout: float) -> dict[str, Any]:
        del timeout
        if url.endswith("estado/moderacion"):
            return {"estado_global": "SIN_PREPARAR"}
        return {"estado": "ok"}

    def html_ok(url: str, timeout: float) -> str:
        """Emula el HTML que Nginx sirve para cualquiera de las dos SPA."""

        del url, timeout
        return "<!doctype html><title>SIS-Leg</title>"

    return GestorDespliegue(
        tmp_path / "opt/sis-leg",
        ejecutor=ejecutor,
        consultor_json=json_ok,
        consultor_texto=html_ok,
        durmiente=durmiente,
        directorio_systemd=tmp_path / "etc/systemd/system",
        ruta_nginx=tmp_path / "etc/nginx/conf.d/sis-leg.conf",
        python_base=Path("/usr/bin/python3"),
    )


def crear_config_externa(gestor: GestorDespliegue) -> None:
    """Crea placeholders; el fake confirma que el parser se invoca por subprocess."""

    # ``apoyo-tecnico/mensajes.csv`` es opcional en producción (el backend lo
    # crea al dar de alta el primer mensaje), pero la fixture lo incluye para
    # comprobar que, cuando existe, recibe el dueño y el modo declarados.
    for relativa in (
        "system.toml",
        "concejales.csv",
        "bridge/devices.json",
        "apoyo-tecnico/mensajes.csv",
    ):
        ruta = gestor.config / relativa
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text("fixture externo", encoding="utf-8")
    gestor.logs.mkdir(parents=True, exist_ok=True)


def test_convergencia_tolera_404_inicial_y_luego_exige_todas_las_superficies(
    tmp_path: Path,
) -> None:
    """Un worker Legacy transitorio no invalida un reload que luego converge completo."""

    pausas: list[float] = []
    gestor = crear_gestor(tmp_path, durmiente=pausas.append)
    consultas: list[str] = []

    def html_con_404_inicial(url: str, _timeout: float) -> str:
        """Representa el 404 observado en campo para la primera Moderación."""

        consultas.append(url)
        if consultas == [modulo_despliegue.URL_NGINX_MODERACION]:
            raise ErrorDespliegue("HTTP 404 transitorio")
        return "<!doctype html><title>SIS-Leg</title>"

    gestor.consultor_texto = html_con_404_inicial
    gestor._esperar_convergencia_nginx()  # pyright: ignore[reportPrivateUsage]

    assert pausas == [0.5]
    assert consultas == [
        modulo_despliegue.URL_NGINX_MODERACION,
        *modulo_despliegue.SUPERFICIES_NGINX,
    ]


def test_convergencia_tolera_varios_fallos_transitorios_sin_espera_real(
    tmp_path: Path,
) -> None:
    """Cada intento vuelve a validar el conjunto después de health y HTML transitorios."""

    pausas: list[float] = []
    gestor = crear_gestor(tmp_path, durmiente=pausas.append)
    cantidad_health = 0
    cantidad_moderacion = 0

    def health_transitorio(_url: str, _timeout: float) -> dict[str, Any]:
        """La primera conexión falla y las siguientes alcanzan al backend sano."""

        nonlocal cantidad_health
        cantidad_health += 1
        if cantidad_health == 1:
            raise ErrorDespliegue("URLError transitorio")
        return {"estado": "ok"}

    def html_transitorio(_url: str, _timeout: float) -> str:
        """La segunda pasada aún recibe contenido Legacy y la tercera converge."""

        nonlocal cantidad_moderacion
        cantidad_moderacion += 1
        if cantidad_moderacion == 1:
            return "respuesta Legacy sin documento SIS-Leg"
        return "<!doctype html><title>SIS-Leg</title>"

    gestor.consultor_json = health_transitorio
    gestor.consultor_texto = html_transitorio
    gestor._esperar_convergencia_nginx(  # pyright: ignore[reportPrivateUsage]
        intentos=3, pausa=0.25
    )

    assert cantidad_health == 3
    assert pausas == [0.25, 0.25]


def test_convergencia_que_nunca_llega_falla_acotada_con_ultimo_diagnostico(
    tmp_path: Path,
) -> None:
    """Agotar el presupuesto informa la última superficie y no duerme tras el final."""

    pausas: list[float] = []
    gestor = crear_gestor(tmp_path, durmiente=pausas.append)

    def html_legacy(_url: str, _timeout: float) -> str:
        """Mantiene al cliente en el vhost anterior durante todo el presupuesto."""

        return "contenido Legacy"

    gestor.consultor_texto = html_legacy

    with pytest.raises(ErrorDespliegue) as captura:
        gestor._esperar_convergencia_nginx(  # pyright: ignore[reportPrivateUsage]
            intentos=3, pausa=0.2
        )

    assert "último diagnóstico" in str(captura.value)
    assert modulo_despliegue.URL_NGINX_MODERACION in str(captura.value)
    assert pausas == [0.2, 0.2]


def test_convergencia_falla_si_health_proxy_permanece_incorrecto(tmp_path: Path) -> None:
    """Las páginas estáticas no convierten en éxito un health proxy inválido."""

    pausas: list[float] = []
    gestor = crear_gestor(tmp_path, durmiente=pausas.append)
    consultas_html = 0

    def health_degradado(_url: str, _timeout: float) -> dict[str, Any]:
        """Simula un backend accesible cuyo contrato de salud no está satisfecho."""

        return {"estado": "degradado"}

    gestor.consultor_json = health_degradado

    def contar_html(_url: str, _timeout: float) -> str:
        nonlocal consultas_html
        consultas_html += 1
        return "<!doctype html><title>SIS-Leg</title>"

    gestor.consultor_texto = contar_html
    with pytest.raises(ErrorDespliegue, match="health vía Nginx"):
        gestor._esperar_convergencia_nginx(  # pyright: ignore[reportPrivateUsage]
            intentos=2
        )

    assert consultas_html == 0
    assert pausas == [0.5]


def test_convergencia_falla_si_una_superficie_estatica_permanece_incorrecta(
    tmp_path: Path,
) -> None:
    """Una sola ruta Legacy impide aceptar parcialmente el vhost nuevo."""

    pausas: list[float] = []
    gestor = crear_gestor(tmp_path, durmiente=pausas.append)
    consultas: list[str] = []

    def html_con_recinto_legacy(url: str, _timeout: float) -> str:
        consultas.append(url)
        if url == modulo_despliegue.URL_NGINX_RECINTO:
            return "<!doctype html><title>Legacy</title>"
        return "<!doctype html><title>SIS-Leg</title>"

    gestor.consultor_texto = html_con_recinto_legacy
    with pytest.raises(ErrorDespliegue, match="recinto"):
        gestor._esperar_convergencia_nginx(  # pyright: ignore[reportPrivateUsage]
            intentos=2
        )

    assert consultas == [
        modulo_despliegue.URL_NGINX_MODERACION,
        modulo_despliegue.URL_NGINX_RECINTO,
        modulo_despliegue.URL_NGINX_MODERACION,
        modulo_despliegue.URL_NGINX_RECINTO,
    ]
    assert pausas == [0.5]


def test_activacion_inmediata_verifica_cinco_superficies_y_recarga_nginx_una_vez(
    tmp_path: Path,
) -> None:
    """Sin transición no hay pausa, reload duplicado ni restart de Nginx."""

    pausas: list[float] = []
    ejecutor = EjecutorFalso()
    gestor = crear_gestor(tmp_path, ejecutor, durmiente=pausas.append)
    release = crear_release_preparada(gestor, SHA_A)
    crear_config_externa(gestor)
    consultas: list[str] = []

    def registrar_html(url: str, _timeout: float) -> str:
        consultas.append(url)
        return "<!doctype html><title>SIS-Leg</title>"

    gestor.consultor_texto = registrar_html
    gestor.activar(SHA_A)

    assert resolver_enlace_release(gestor.current, gestor.releases) == release
    assert consultas == list(modulo_despliegue.SUPERFICIES_NGINX)
    assert pausas == []
    assert ejecutor.llamadas.count(["systemctl", "reload", "nginx.service"]) == 1
    assert ["systemctl", "restart", "nginx.service"] not in ejecutor.llamadas


def test_primera_instalacion_sin_convergencia_restaura_estado_inicial(
    tmp_path: Path,
) -> None:
    """Sin release anterior, un vhost persistente incorrecto deja todo desactivado."""

    ejecutor = EjecutorFalso()

    def no_dormir(_pausa: float) -> None:
        """Recorre el presupuesto de producción sin demoras de reloj en el test."""

    gestor = crear_gestor(tmp_path, ejecutor, durmiente=no_dormir)
    crear_release_preparada(gestor, SHA_A)
    crear_config_externa(gestor)

    def html_legacy(_url: str, _timeout: float) -> str:
        """Impide que la primera instalación llegue a observar su nuevo vhost."""

        return "contenido Legacy"

    gestor.consultor_texto = html_legacy

    with pytest.raises(ErrorDespliegue, match="se restauró la release anterior"):
        gestor.activar(SHA_A)

    assert resolver_enlace_release(gestor.current, gestor.releases) is None
    assert resolver_enlace_release(gestor.previous, gestor.releases) is None
    assert not (gestor.directorio_systemd / modulo_despliegue.SERVICIO_BACKEND).exists()
    assert not (gestor.directorio_systemd / modulo_despliegue.SERVICIO_BRIDGE).exists()
    assert not gestor.ruta_nginx.exists()
    assert ["systemctl", "stop", modulo_despliegue.SERVICIO_BRIDGE] in ejecutor.llamadas
    assert ["systemctl", "stop", modulo_despliegue.SERVICIO_BACKEND] in ejecutor.llamadas


def test_activacion_previous_y_rollback_preservan_config_y_logs(tmp_path: Path) -> None:
    """Los enlaces rotan, mientras los datos externos quedan byte a byte iguales."""

    gestor = crear_gestor(tmp_path)
    release_a = crear_release_preparada(gestor, SHA_A)
    crear_release_preparada(gestor, SHA_B)
    crear_config_externa(gestor)
    config_antes = (gestor.config / "system.toml").read_bytes()
    log = gestor.logs / "institucional.csv"
    log.write_text("durable", encoding="utf-8")

    gestor.activar(SHA_A)
    assert resolver_enlace_release(gestor.current, gestor.releases) == release_a
    assert resolver_enlace_release(gestor.previous, gestor.releases) is None

    gestor.activar(SHA_B)
    assert resolver_enlace_release(gestor.current, gestor.releases).name == SHA_B  # type: ignore[union-attr]
    assert resolver_enlace_release(gestor.previous, gestor.releases).name == SHA_A  # type: ignore[union-attr]

    gestor.rollback()
    assert resolver_enlace_release(gestor.current, gestor.releases).name == SHA_A  # type: ignore[union-attr]
    assert resolver_enlace_release(gestor.previous, gestor.releases).name == SHA_B  # type: ignore[union-attr]
    assert (gestor.config / "system.toml").read_bytes() == config_antes
    assert log.read_text(encoding="utf-8") == "durable"


@pytest.mark.parametrize("estado", ["PREPARANDO", "SESION_ABIERTA"])
def test_guard_rechaza_estado_institucional_activo(tmp_path: Path, estado: str) -> None:
    """No existe flag que permita interrumpir deliberadamente una sesión."""

    gestor = crear_gestor(tmp_path)
    release = crear_release_preparada(gestor, SHA_A)
    cambiar = modulo_despliegue.cambiar_enlace_atomico
    cambiar(gestor.current, release)

    def consultar_estado(_url: str, _timeout: float) -> dict[str, Any]:
        return {"estado_global": estado}

    gestor.consultor_json = consultar_estado

    with pytest.raises(ErrorDespliegue, match="Despliegue rechazado"):
        gestor.guard_institucional()


def test_guard_falla_cerrado_si_systemd_activo_pero_http_inaccesible(tmp_path: Path) -> None:
    """Un active inconsistente no se interpreta como permiso para reiniciar."""

    gestor = crear_gestor(tmp_path)
    release = crear_release_preparada(gestor, SHA_A)
    modulo_despliegue.cambiar_enlace_atomico(gestor.current, release)

    def inaccesible(_url: str, _timeout: float) -> dict[str, Any]:
        raise ErrorDespliegue("sin respuesta")

    gestor.consultor_json = inaccesible
    with pytest.raises(ErrorDespliegue, match="sin respuesta"):
        gestor.guard_institucional()


def test_instalacion_parcial_restaura_todo_sin_switch_ni_reinicios(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un fallo tras copiar la segunda unit revierte existentes y nuevos."""

    ejecutor = EjecutorFalso()
    gestor = crear_gestor(tmp_path, ejecutor)
    release_a = crear_release_preparada(gestor, SHA_A)
    crear_release_preparada(gestor, SHA_B)
    crear_config_externa(gestor)
    modulo_despliegue.cambiar_enlace_atomico(gestor.current, release_a)

    unit_backend = gestor.directorio_systemd / modulo_despliegue.SERVICIO_BACKEND
    unit_bridge = gestor.directorio_systemd / modulo_despliegue.SERVICIO_BRIDGE
    unit_backend.parent.mkdir(parents=True)
    unit_backend.write_bytes(b"backend anterior")
    unit_backend.chmod(0o600)
    gestor.ruta_nginx.parent.mkdir(parents=True)
    gestor.ruta_nginx.write_bytes(b"nginx anterior")
    original = gestor._copiar_atomico  # pyright: ignore[reportPrivateUsage]
    cantidad = 0

    def copiar_y_fallar_segunda(origen: Path, destino: Path) -> None:
        """Simula un error posterior al reemplazo de la segunda entrada."""

        nonlocal cantidad
        cantidad += 1
        original(origen, destino)
        if cantidad == 2:
            raise OSError("fallo inyectado en segunda copia")

    monkeypatch.setattr(gestor, "_copiar_atomico", copiar_y_fallar_segunda)

    with pytest.raises(ErrorDespliegue, match="todos los destinos modificados"):
        gestor.activar(SHA_B)

    assert resolver_enlace_release(gestor.current, gestor.releases) == release_a
    assert unit_backend.read_bytes() == b"backend anterior"
    assert stat.S_IMODE(unit_backend.stat().st_mode) == 0o600
    assert not unit_bridge.exists()
    assert gestor.ruta_nginx.read_bytes() == b"nginx anterior"
    assert not any(
        llamada[:2]
        in (["systemctl", "daemon-reload"], ["systemctl", "restart"], ["systemctl", "reload"])
        for llamada in ejecutor.llamadas
    )


def test_permisos_incompatibles_fallan_antes_del_switch(tmp_path: Path) -> None:
    """La activación no avanza si backend no puede escribir el directorio de logs."""

    class EjecutorConLogsDenegados(EjecutorFalso):
        """Niega una comprobación efectiva sin crear usuarios reales en el test."""

        def ejecutar(
            self,
            argumentos: Sequence[str],
            *,
            directorio: Path | None = None,
            entorno: Mapping[str, str] | None = None,
            comprobar: bool = True,
        ) -> ResultadoComando:
            args = [str(valor) for valor in argumentos]
            if args[:7] == [
                "runuser",
                "--user",
                "sis-leg-backend",
                "--",
                "test",
                "-w",
                str(tmp_path / "opt/sis-leg/logs"),
            ]:
                self.llamadas.append(args)
                self.invocaciones.append((args, directorio, comprobar))
                return ResultadoComando(1, error="permiso denegado")
            return super().ejecutar(
                argumentos,
                directorio=directorio,
                entorno=entorno,
                comprobar=comprobar,
            )

    ejecutor = EjecutorConLogsDenegados()
    gestor = crear_gestor(tmp_path, ejecutor)
    crear_release_preparada(gestor, SHA_A)
    crear_config_externa(gestor)

    with pytest.raises(ErrorDespliegue, match="logs debe ser escribible"):
        gestor.activar(SHA_A)

    assert resolver_enlace_release(gestor.current, gestor.releases) is None
    assert not (gestor.directorio_systemd / modulo_despliegue.SERVICIO_BACKEND).exists()
    assert not any(llamada[:2] == ["systemctl", "restart"] for llamada in ejecutor.llamadas)
    assert any(
        llamada[0][4:] == ["test", "-w", str(gestor.logs)]
        and llamada[1] == DIRECTORIO_SONDAS_RUNTIME
        and llamada[2] is False
        for llamada in ejecutor.invocaciones
    )


def test_permisos_correctos_verifican_ambos_usuarios_y_grupo_input(tmp_path: Path) -> None:
    """El gate confirma accesos/grupos correctos y permite completar la activación."""

    ejecutor = EjecutorFalso()
    gestor = crear_gestor(tmp_path, ejecutor)
    release = crear_release_preparada(gestor, SHA_A)
    crear_config_externa(gestor)

    gestor.activar(SHA_A)

    llamadas_runuser = [llamada for llamada in ejecutor.llamadas if llamada[:1] == ["runuser"]]
    assert any("sis-leg-backend" in llamada for llamada in llamadas_runuser)
    assert any("sis-leg-bridge" in llamada for llamada in llamadas_runuser)
    assert [
        "runuser",
        "--user",
        "sis-leg-bridge",
        "--",
        "test",
        "-x",
        str(gestor.config),
    ] in llamadas_runuser
    assert [
        "runuser",
        "--user",
        "sis-leg-bridge",
        "--",
        "test",
        "!",
        "-r",
        str(gestor.config / "system.toml"),
    ] in llamadas_runuser
    assert ["id", "--groups", "--name", "sis-leg-backend"] in ejecutor.llamadas
    assert ["id", "--groups", "--name", "sis-leg-bridge"] in ejecutor.llamadas
    sondas_runtime = [
        invocacion for invocacion in ejecutor.invocaciones if invocacion[0][:1] == ["runuser"]
    ]
    assert any(invocacion[0][4] == "test" for invocacion in sondas_runtime)
    assert any(invocacion[0][4] == "find" for invocacion in sondas_runtime)
    assert all(
        directorio == DIRECTORIO_SONDAS_RUNTIME and comprobar is False
        for _, directorio, comprobar in sondas_runtime
    )
    assert resolver_enlace_release(gestor.current, gestor.releases) == release


def test_release_valida_no_depende_del_cwd_privado_del_invocador(tmp_path: Path) -> None:
    """Un home privado sólo dañaría una sonda ``runuser`` que heredara ese cwd."""

    class EjecutorConCwdPrivado(EjecutorFalso):
        """Modela el fallo de campo sin necesitar usuarios reales ni privilegios."""

        def ejecutar(
            self,
            argumentos: Sequence[str],
            *,
            directorio: Path | None = None,
            entorno: Mapping[str, str] | None = None,
            comprobar: bool = True,
        ) -> ResultadoComando:
            args = [str(valor) for valor in argumentos]
            if args[:1] == ["runuser"] and directorio is None:
                self.llamadas.append(args)
                self.invocaciones.append((args, directorio, comprobar))
                return ResultadoComando(
                    1,
                    error=(
                        "find: fallo al restaurar el directorio de trabajo inicial: "
                        "/home/concejo: Permiso denegado"
                    ),
                )
            return super().ejecutar(
                argumentos,
                directorio=directorio,
                entorno=entorno,
                comprobar=comprobar,
            )

    ejecutor = EjecutorConCwdPrivado()
    gestor = crear_gestor(tmp_path, ejecutor)
    release = crear_release_preparada(gestor, SHA_A)
    crear_config_externa(gestor)

    gestor.activar(SHA_A)

    assert resolver_enlace_release(gestor.current, gestor.releases) == release
    assert all(
        directorio == DIRECTORIO_SONDAS_RUNTIME
        for argumentos, directorio, _ in ejecutor.invocaciones
        if argumentos[:1] == ["runuser"]
    )


def test_release_escribible_sigue_rechazada_antes_del_switch(tmp_path: Path) -> None:
    """Fijar el cwd no reduce el recorrido ``find -writable`` de la release."""

    class EjecutorConReleaseEscribible(EjecutorFalso):
        """Devuelve la ruta que una identidad runtime podría modificar."""

        def ejecutar(
            self,
            argumentos: Sequence[str],
            *,
            directorio: Path | None = None,
            entorno: Mapping[str, str] | None = None,
            comprobar: bool = True,
        ) -> ResultadoComando:
            args = [str(valor) for valor in argumentos]
            if args[:5] == ["runuser", "--user", "sis-leg-backend", "--", "find"]:
                self.llamadas.append(args)
                self.invocaciones.append((args, directorio, comprobar))
                return ResultadoComando(0, salida=f"{args[5]}/archivo-escribible\n")
            return super().ejecutar(
                argumentos,
                directorio=directorio,
                entorno=entorno,
                comprobar=comprobar,
            )

    ejecutor = EjecutorConReleaseEscribible()
    gestor = crear_gestor(tmp_path, ejecutor)
    crear_release_preparada(gestor, SHA_A)
    crear_config_externa(gestor)

    with pytest.raises(ErrorDespliegue, match="archivo-escribible"):
        gestor.activar(SHA_A)

    assert resolver_enlace_release(gestor.current, gestor.releases) is None


def test_error_real_de_find_sigue_fallando_cerrado(tmp_path: Path) -> None:
    """Un error de ``runuser``/``find`` conserva stderr y bloquea la activación."""

    class EjecutorConFindFallido(EjecutorFalso):
        """Inyecta un código no cero equivalente al observado en producción."""

        def ejecutar(
            self,
            argumentos: Sequence[str],
            *,
            directorio: Path | None = None,
            entorno: Mapping[str, str] | None = None,
            comprobar: bool = True,
        ) -> ResultadoComando:
            args = [str(valor) for valor in argumentos]
            if args[:5] == ["runuser", "--user", "sis-leg-backend", "--", "find"]:
                self.llamadas.append(args)
                self.invocaciones.append((args, directorio, comprobar))
                return ResultadoComando(1, error="find: permiso denegado real")
            return super().ejecutar(
                argumentos,
                directorio=directorio,
                entorno=entorno,
                comprobar=comprobar,
            )

    ejecutor = EjecutorConFindFallido()
    gestor = crear_gestor(tmp_path, ejecutor)
    crear_release_preparada(gestor, SHA_A)
    crear_config_externa(gestor)

    with pytest.raises(ErrorDespliegue, match="find: permiso denegado real"):
        gestor.activar(SHA_A)

    assert resolver_enlace_release(gestor.current, gestor.releases) is None


def test_ejecutor_subprocess_propaga_cwd_sin_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La frontera real pasa cwd a subprocess y mantiene argumentos estructurados."""

    def ejecutar_falso(argumentos: list[str], **opciones: Any) -> subprocess.CompletedProcess[str]:
        assert argumentos == ["runuser", "--user", "usuario", "--", "test", "-r", "/ruta"]
        assert opciones["cwd"] == DIRECTORIO_SONDAS_RUNTIME
        assert "shell" not in opciones
        assert opciones["check"] is False
        return subprocess.CompletedProcess(argumentos, 0, stdout="", stderr="")

    monkeypatch.setattr(modulo_despliegue.subprocess, "run", ejecutar_falso)

    resultado = EjecutorSubprocess().ejecutar(
        ["runuser", "--user", "usuario", "--", "test", "-r", "/ruta"],
        directorio=DIRECTORIO_SONDAS_RUNTIME,
        comprobar=False,
    )

    assert resultado.codigo == 0


def test_fallo_health_restaura_current_y_no_actualiza_previous(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un fallo posterior al switch vuelve a la release sana anterior."""

    gestor = crear_gestor(tmp_path)
    crear_release_preparada(gestor, SHA_A)
    crear_release_preparada(gestor, SHA_B)
    crear_config_externa(gestor)
    gestor.activar(SHA_A)

    def no_dormir(segundos: float) -> None:
        """Evita una espera real mientras se recorren todos los intentos."""

        del segundos

    monkeypatch.setattr(modulo_despliegue.time, "sleep", no_dormir)

    def salud_por_release(url: str, _timeout: float) -> dict[str, Any]:
        if url.endswith("estado/moderacion"):
            return {"estado_global": "SIN_PREPARAR"}
        actual = resolver_enlace_release(gestor.current, gestor.releases)
        if url == modulo_despliegue.URL_HEALTH and actual is not None and actual.name == SHA_B:
            raise ErrorDespliegue("health nuevo falló")
        return {"estado": "ok"}

    gestor.consultor_json = salud_por_release
    with pytest.raises(ErrorDespliegue, match="se restauró la release anterior"):
        gestor.activar(SHA_B)

    assert resolver_enlace_release(gestor.current, gestor.releases).name == SHA_A  # type: ignore[union-attr]
    assert resolver_enlace_release(gestor.previous, gestor.releases) is None


def test_fallo_del_rollback_detiene_y_reporta_ambos_errores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La herramienta no sigue mutando si tampoco recupera la release anterior."""

    gestor = crear_gestor(tmp_path)
    crear_release_preparada(gestor, SHA_A)
    crear_release_preparada(gestor, SHA_B)
    crear_config_externa(gestor)
    gestor.activar(SHA_A)

    def no_dormir(segundos: float) -> None:
        del segundos

    def health_siempre_fallido(url: str, _timeout: float) -> dict[str, Any]:
        if url.endswith("estado/moderacion"):
            return {"estado_global": "SIN_PREPARAR"}
        if url == modulo_despliegue.URL_HEALTH:
            raise ErrorDespliegue("health indisponible")
        return {"estado": "ok"}

    monkeypatch.setattr(modulo_despliegue.time, "sleep", no_dormir)
    gestor.consultor_json = health_siempre_fallido

    with pytest.raises(ErrorDespliegue, match="también el rollback automático"):
        gestor.activar(SHA_B)


def test_plan_de_permisos_separa_backend_bridge_e_input() -> None:
    """El plan completo satisface traversal y mínimo privilegio POSIX."""

    por_ruta = {entrada.ruta_relativa: entrada for entrada in plan_permisos()}

    def tiene_permiso(usuario: str, grupos: set[str], ruta: str, permiso: int) -> bool:
        """Evalúa un bit efectivo y el traversal de cada directorio padre."""

        partes = Path(ruta).parts
        for cantidad in range(1, len(partes)):
            padre = por_ruta[Path(*partes[:cantidad]).as_posix()]
            if not bit_efectivo(usuario, grupos, padre, 0o1):
                return False
        return bit_efectivo(usuario, grupos, por_ruta[ruta], permiso)

    def bit_efectivo(
        usuario: str,
        grupos: set[str],
        entrada: modulo_despliegue.PlanPermiso,
        permiso: int,
    ) -> bool:
        """Selecciona owner/group/other como lo hace el modelo POSIX clásico."""

        desplazamiento = 6 if usuario == entrada.usuario else 3 if entrada.grupo in grupos else 0
        return bool(entrada.modo & (permiso << desplazamiento))

    grupos_backend = {"sis-leg-backend"}
    grupos_bridge = {"sis-leg-bridge", "input"}

    assert por_ruta["."].modo == 0o755
    assert por_ruta["releases"].usuario == "root"
    assert por_ruta["logs"].usuario == "sis-leg-backend"
    assert por_ruta["config/bridge"].usuario == "sis-leg-bridge"
    assert por_ruta["config/system.toml"].modo == 0o640
    assert por_ruta["config"].modo == 0o751

    # Backend puede leer sus dos entradas y crear auditoría, pero no modificar
    # configuración ni atravesar el subdirectorio privado del bridge.
    assert tiene_permiso("sis-leg-backend", grupos_backend, "config/system.toml", 0o4)
    assert tiene_permiso("sis-leg-backend", grupos_backend, "config/concejales.csv", 0o4)
    assert not tiene_permiso("sis-leg-backend", grupos_backend, "config/system.toml", 0o2)
    assert not tiene_permiso("sis-leg-backend", grupos_backend, "config", 0o2)
    assert not tiene_permiso("sis-leg-backend", grupos_backend, "config/bridge/devices.json", 0o4)
    assert tiene_permiso("sis-leg-backend", grupos_backend, "logs", 0o2)
    assert tiene_permiso("sis-leg-backend", grupos_backend, "logs", 0o1)

    # Bridge atraviesa el padre sin poder enumerarlo, llega a devices.json y
    # tiene write+execute sobre su directorio para tempfile + os.replace.
    assert tiene_permiso("sis-leg-bridge", grupos_bridge, "config", 0o1)
    assert not tiene_permiso("sis-leg-bridge", grupos_bridge, "config", 0o4)
    assert not tiene_permiso("sis-leg-bridge", grupos_bridge, "config/system.toml", 0o4)
    assert not tiene_permiso("sis-leg-bridge", grupos_bridge, "config/concejales.csv", 0o4)
    assert tiene_permiso("sis-leg-bridge", grupos_bridge, "config/bridge", 0o2)
    assert tiene_permiso("sis-leg-bridge", grupos_bridge, "config/bridge", 0o1)
    assert tiene_permiso("sis-leg-bridge", grupos_bridge, "config/bridge/devices.json", 0o4)
    assert tiene_permiso("sis-leg-bridge", grupos_bridge, "config/bridge/devices.json", 0o2)


def test_plantillas_fijan_loopback_worker_usuarios_y_sse() -> None:
    """Las propiedades productivas críticas son visibles en los artefactos."""

    raiz = Path(__file__).resolve().parents[1]
    backend = (raiz / "deploy/systemd/sis-leg-backend.service").read_text(encoding="utf-8")
    bridge = (raiz / "deploy/systemd/sis-leg-device-bridge.service").read_text(encoding="utf-8")
    nginx = (raiz / "deploy/nginx/sis-leg.conf").read_text(encoding="utf-8")

    assert "User=sis-leg-backend" in backend
    assert "--host 127.0.0.1 --port 8000 --workers 1" in backend
    assert "WorkingDirectory=/opt/sis-leg" in backend
    assert "PYTHONDONTWRITEBYTECODE=1" in backend
    assert "User=sis-leg-bridge" in bridge
    assert "SupplementaryGroups=input" in bridge
    assert "--control-host 127.0.0.1 --control-port 8765" in bridge
    assert "proxy_http_version 1.1" in nginx
    assert "proxy_buffering off" in nginx
    assert "proxy_read_timeout 1h" in nginx
    assert "proxy_pass http://127.0.0.1:8000;" in nginx
    assert "cors" not in nginx.lower()
    assert "ssl" not in nginx.lower()


def test_configuracion_nginx_expone_apoyo_tecnico_en_la_red() -> None:
    """El puesto de Apoyo Técnico se opera desde otro equipo de la LAN (WP-056).

    A diferencia de ``/simulador/``, su bloque no lleva ``deny all``: la decisión humana
    cerrada es que se acceda sin autenticación adicional desde la red del Concejo. La
    prueba fija esa diferencia para que un endurecimiento accidental del sitio no deje
    inoperable al puesto técnico sin que nadie lo advierta.
    """

    raiz = Path(__file__).resolve().parents[1]
    nginx = (raiz / "deploy/nginx/sis-leg.conf").read_text(encoding="utf-8")

    inicio = nginx.index("location /tecnico/ {")
    bloque = nginx[inicio : nginx.index("}", inicio)]
    assert "try_files $uri $uri/ /tecnico/index.html;" in bloque
    assert "root /opt/sis-leg/current/web;" in bloque
    assert "deny" not in bloque
    assert "allow" not in bloque


def test_configuracion_nginx_expone_el_zocalo_para_obs() -> None:
    """El Zócalo se abre como Browser Source desde el equipo de transmisión (WP-099).

    Es una superficie pública de solo lectura que se consume desde otro puesto de la LAN,
    igual que ``/recinto/`` y ``/tecnico/``: no lleva ``deny all`` ni autenticación. Sin
    este bloque la release podría contener la SPA y aun así nadie podría abrirla, que es
    exactamente el fallo que esta prueba impide que llegue a una transmisión en vivo.
    """

    raiz = Path(__file__).resolve().parents[1]
    nginx = (raiz / "deploy/nginx/sis-leg.conf").read_text(encoding="utf-8")

    inicio = nginx.index("location /zocalo/ {")
    bloque = nginx[inicio : nginx.index("}", inicio)]
    assert "try_files $uri $uri/ /zocalo/index.html;" in bloque
    assert "root /opt/sis-leg/current/web;" in bloque
    assert "deny" not in bloque
    assert "allow" not in bloque


def test_configuracion_nginx_publica_el_manual_sin_restriccion_de_red() -> None:
    """El manual (WP-067) se publica en una única ruta de mismo origen.

    Es el destino del icono de ayuda de Moderación y del de Apoyo Técnico, así que debe
    resolverse desde cualquier puesto que opere el sistema. No lleva el ``deny all`` del
    simulador y tampoco reenvía a una SPA: es un documento estático y una ruta inexistente
    dentro de ``/manual/`` debe responder 404 en lugar de devolver el índice.
    """

    raiz = Path(__file__).resolve().parents[1]
    nginx = (raiz / "deploy/nginx/sis-leg.conf").read_text(encoding="utf-8")

    inicio = nginx.index("location /manual/ {")
    bloque = nginx[inicio : nginx.index("}", inicio)]
    assert "root /opt/sis-leg/current/web;" in bloque
    assert "try_files $uri $uri/ =404;" in bloque
    assert "deny" not in bloque
    assert "allow" not in bloque


def test_configuracion_nginx_restringe_simulador_a_loopback() -> None:
    """Nginx expone /simulador/ restringido a loopback con allow 127.0.0.1; ::1; deny all."""

    raiz = Path(__file__).resolve().parents[1]
    nginx = (raiz / "deploy/nginx/sis-leg.conf").read_text(encoding="utf-8")

    assert "location /simulador/ {" in nginx
    assert "allow 127.0.0.1;" in nginx
    assert "allow ::1;" in nginx
    assert "deny all;" in nginx
    assert "try_files $uri $uri/ /simulador/index.html;" in nginx
