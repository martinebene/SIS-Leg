"""Simulación reproducible de las tres operaciones del host institucional (WP-101A).

Qué se simula
-------------

Un host completo de fantasía bajo ``tmp_path``: raíz de instalación, releases,
configuración local, unidades de systemd de los dos sistemas, vhosts de Nginx y
puertos. El ejecutor falso **mantiene estado**: un ``systemctl stop`` apaga de
verdad la unidad simulada, de modo que el clasificador de estado ve después lo
mismo que vería en el host real y las secuencias mal ordenadas fallan.

Los escenarios cubren el contrato completo de WP-101A: Legacy activo, SIS-Leg
activo, target válido/inválido/inexistente, release ya actualizada, evidencia
pública inválida, paquete corrupto, preservación byte a byte de la configuración,
altas add-only, aborto ante migración antes de mutar, rollback SIS-Leg -> SIS-Leg,
estados inconsistentes, exclusión de bridges en toda transición, ausencia de
credenciales de GitHub e inclusión del Zócalo.

Ninguna prueba requiere systemd, Nginx ni red, y ninguna escribe fuera de
``tmp_path``: en particular, nunca se tocan ``/opt/sis-leg``, ``/usr/local/bin``,
``/etc`` ni el home productivo.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from conftest import escribir_release_json_de_prueba

from deploy.actualizador_publico import (
    ErrorActualizadorPublico,
    JobCi,
    ReleaseDescargada,
    RunCi,
)
from deploy.configuracion_local import RUTA_CONTRATO_EN_RELEASE
from deploy.estado_host import (
    ESTABLE_LEGACY,
    ESTABLE_SISLEG,
    PUERTO_BACKEND,
    PUERTO_BRIDGE_SISLEG,
    SERVICIO_BACKEND_LEGACY,
    SERVICIO_BRIDGE_LEGACY,
    InspectorEstadoHost,
    escribir_target_release,
    leer_target_release,
)
from deploy.herramienta_despliegue import (
    MARCADOR_PREPARADA,
    SERVICIO_BACKEND,
    SERVICIO_BRIDGE,
    SUPERFICIES_NGINX,
    URL_NGINX_ZOCALO,
    ErrorDespliegue,
    GestorDespliegue,
    ResultadoComando,
)
from deploy.operaciones_host import (
    ErrorOperacionHost,
    OperadorHost,
    PlanOperacion,
    registrar_en_historial,
    resultado_de_falla,
)
from scripts.empaquetar_produccion import construir_paquete

RAIZ_REPOSITORIO = Path(__file__).resolve().parents[1]

SHA_VIEJO = "a" * 40
SHA_NUEVO = "b" * 40
SHA_ARBOL = "c" * 40
# Tercera cabeza de ``main``: representa un avance ocurrido **mientras** corría
# una actualización que ya había congelado ``SHA_NUEVO``.
SHA_MAS_NUEVO = "d" * 40
# Hora fija que inyecta la suite para que el historial sea comparable.
MARCA_TEMPORAL_FIJA = "2026-09-11T20:00:00-03:00"

UNIDADES_LEGACY = (SERVICIO_BACKEND_LEGACY, SERVICIO_BRIDGE_LEGACY)
UNIDADES_SISLEG = (SERVICIO_BACKEND, SERVICIO_BRIDGE)


# ---------------------------------------------------------------------------
# Construcción de un paquete productivo real
# ---------------------------------------------------------------------------


def crear_checkout_minimo(raiz: Path) -> None:
    """Materializa la allowlist mínima que consume el empaquetador canónico.

    Se define acá y no se importa de otro módulo de prueba porque pytest carga
    cada archivo de test por separado: importarlo entre módulos lo registraría
    dos veces. El contenido es de fantasía salvo el contrato de configuración,
    que se copia del repositorio real para que la compuerta add-only se pruebe
    contra el contrato vigente y no contra una copia que podría envejecer.
    """

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
        "deploy/configuracion_local.py": "# contrato",
        "deploy/actualizador_publico.py": "# canal publico",
        "deploy/estado_host.py": "# estado",
        "deploy/operaciones_host.py": "# operaciones",
        "deploy/instalador_host.py": "# instalador",
        "deploy/host/sisleg-operacion": "#!/bin/sh\n",
        "deploy/systemd/sis-leg-backend.service": "[Service]\n",
        "deploy/systemd/sis-leg-device-bridge.service": "[Service]\n",
        "deploy/nginx/sis-leg.conf": "server {}\n",
    }
    for relativa, contenido in archivos.items():
        ruta = raiz / relativa
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(contenido, encoding="utf-8")
    contrato = raiz / RUTA_CONTRATO_EN_RELEASE
    contrato.parent.mkdir(parents=True, exist_ok=True)
    contrato.write_text(
        (RAIZ_REPOSITORIO / RUTA_CONTRATO_EN_RELEASE).read_text(encoding="utf-8"),
        encoding="utf-8",
    )


def construir_artefactos(
    tmp_path: Path, sha: str, *, contrato: list[dict[str, Any]] | None = None
) -> tuple[Path, Path]:
    """Genera paquete y sidecar reales, con un contrato de configuración opcional."""

    checkout = tmp_path / f"checkout-{sha[:6]}"
    crear_checkout_minimo(checkout)
    if contrato is not None:
        (checkout / RUTA_CONTRATO_EN_RELEASE).write_text(
            json.dumps(
                {
                    "formato": "sis-leg-configuracion",
                    "version_contrato": 1,
                    "recursos": contrato,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return construir_paquete(
        raiz=checkout,
        directorio_salida=tmp_path / f"artefactos-{sha[:6]}",
        sha_commit=sha,
        sha_arbol=SHA_ARBOL,
    )


def release_descargada(paquete: Path, sidecar: Path, sha: str) -> ReleaseDescargada:
    """Arma el resultado que el canal público entregaría para ese SHA.

    Se construye el objeto y no se emula GitHub porque el canal público ya tiene
    su propia suite: acá interesa lo que la operación hace **con** una release ya
    verificada, no volver a verificar la verificación.
    """

    return ReleaseDescargada(
        commit_sha=sha,
        tree_sha=SHA_ARBOL,
        tag=f"sis-leg-{sha}",
        paquete=paquete,
        sidecar=sidecar,
        metadatos=paquete.with_suffix(".metadatos.json"),
        run_ci=RunCi(identificador=1, numero=1, intento=1, head_sha=sha, workflow="CI"),
        job_ci=JobCi(
            identificador=2,
            nombre="Empaquetado · release productiva",
            head_sha=sha,
            run_id=1,
            intento=1,
        ),
    )


# ---------------------------------------------------------------------------
# Host simulado con estado
# ---------------------------------------------------------------------------


class HostSimulado:
    """Ejecutor falso que **mantiene** el estado de systemd, Nginx y permisos.

    Es el corazón de esta suite: cada ``systemctl start/stop/enable/disable`` se
    aplica sobre conjuntos internos, así que el clasificador de estado ve las
    consecuencias reales de la secuencia ejecutada. Además registra, después de
    cada comando, si los dos device bridges quedaron activos a la vez: esa
    historia es la que demuestra que la invariante de exclusión se respeta en
    **todas** las transiciones y no sólo al final.
    """

    def __init__(self, *, activas: set[str], habilitadas: set[str]) -> None:
        self.activas = set(activas)
        self.habilitadas = set(habilitadas)
        self.llamadas: list[list[str]] = []
        self.historia_bridges: list[tuple[bool, bool]] = []
        # Fragmentos de comando que deben fallar. Es una colección y no un único
        # patrón porque las pruebas de doble falla necesitan romper primero la
        # vuelta al sistema anterior y después la restauración de SIS-Leg.
        self.fallas: tuple[str, ...] = ()
        # Unidades cuyo ``disable`` se acepta pero no surte efecto. Reproduce el
        # caso peligroso: systemd responde sin error y la unidad sigue habilitada.
        self.disable_inefectivo: frozenset[str] = frozenset()

    def _registrar_bridges(self) -> None:
        self.historia_bridges.append(
            (SERVICIO_BRIDGE_LEGACY in self.activas, SERVICIO_BRIDGE in self.activas)
        )

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

        linea = " ".join(args)
        for patron in self.fallas:
            if patron in linea:
                if comprobar:
                    raise ErrorDespliegue(f"Falla simulada en {patron}")
                return ResultadoComando(1, "", "falla simulada")

        # Sonda de versión del Python base que usa ``preparar``.
        if len(args) >= 3 and args[1] == "-c" and "sys.version_info" in args[2]:
            return ResultadoComando(0, "3.14\n")
        if args[:2] == ["uv", "sync"]:
            assert directorio is not None and entorno is not None
            venv = Path(entorno["UV_PROJECT_ENVIRONMENT"])
            (venv / "bin").mkdir(parents=True, exist_ok=True)
            for nombre in ("python", "uvicorn", "sis-leg-device-bridge"):
                (venv / "bin" / nombre).write_text("ejecutable", encoding="utf-8")
            return ResultadoComando(0)
        if args[:1] == ["systemctl"]:
            return self._systemctl(args[1:])
        if args == ["id", "--groups", "--name", "sis-leg-backend"]:
            return ResultadoComando(0, "sis-leg-backend\n")
        if args == ["id", "--groups", "--name", "sis-leg-bridge"]:
            return ResultadoComando(0, "sis-leg-bridge input\n")
        return ResultadoComando(0)

    def _systemctl(self, args: list[str]) -> ResultadoComando:
        """Aplica la acción sobre el estado simulado y responde como systemd."""

        accion = args[0]
        unidades = [unidad for unidad in args[1:] if unidad.endswith(".service")]
        if accion == "is-active":
            activa = unidades[0] in self.activas
            self._registrar_bridges()
            return ResultadoComando(0 if activa else 3, "active\n" if activa else "inactive\n")
        if accion == "is-enabled":
            habilitada = unidades[0] in self.habilitadas
            return ResultadoComando(
                0 if habilitada else 1, "enabled\n" if habilitada else "disabled\n"
            )
        for unidad in unidades:
            if accion in {"start", "restart"}:
                self.activas.add(unidad)
            elif accion == "stop":
                self.activas.discard(unidad)
            elif accion == "enable":
                self.habilitadas.add(unidad)
            elif accion == "disable" and unidad not in self.disable_inefectivo:
                self.habilitadas.discard(unidad)
        self._registrar_bridges()
        return ResultadoComando(0)

    def hubo_dos_bridges_simultaneos(self) -> bool:
        """``True`` si en algún instante observado convivieron los dos bridges."""

        return any(legacy and sisleg for legacy, sisleg in self.historia_bridges)


def crear_release_preparada(gestor: GestorDespliegue, sha: str) -> Path:
    """Deja en disco una release con la estructura mínima que exige ``activar``."""

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
        ruta.write_text(
            "<!doctype html>" if ruta.name == "index.html" else "archivo", encoding="utf-8"
        )
    contrato = release / RUTA_CONTRATO_EN_RELEASE
    contrato.parent.mkdir(parents=True, exist_ok=True)
    contrato.write_text(
        (RAIZ_REPOSITORIO / RUTA_CONTRATO_EN_RELEASE).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    # Identidad de árbol (WP-101A I002): el marcador y el ``release.json`` deben
    # declarar el mismo árbol o la release no puede activarse ni fijarse como
    # objetivo. Las releases de fantasía tienen que cumplirlo igual que las
    # reales, porque si no la comprobación no estaría probada por nadie.
    escribir_release_json_de_prueba(release, sha, SHA_ARBOL)
    (release / MARCADOR_PREPARADA).write_text(
        json.dumps({"commit_sha": sha, "tree_sha": SHA_ARBOL}), encoding="utf-8"
    )
    return release


CONTENIDO_CONFIG = {
    "system.toml": "[institucion]\nnombre = 'Cuerpo de Prueba'\n",
    "concejales.csv": "dni,nombre\n1,Ana\n",
    "bridge/devices.json": '{"dispositivos": []}',
}


def crear_config_local(gestor: GestorDespliegue) -> dict[str, bytes]:
    """Escribe la configuración institucional y devuelve sus bytes exactos.

    Los bytes se conservan para poder demostrar después, byte a byte, que
    ninguna operación los tocó.
    """

    original: dict[str, bytes] = {}
    for relativa, contenido in CONTENIDO_CONFIG.items():
        ruta = gestor.config / relativa
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(contenido, encoding="utf-8")
        original[relativa] = ruta.read_bytes()
    gestor.logs.mkdir(parents=True, exist_ok=True)
    return original


class EscenarioHost:
    """Un host simulado completo, listo para ejecutar operaciones sobre él."""

    def __init__(self, tmp_path: Path, *, sisleg_activo: bool, sha_activo: str | None) -> None:
        self.tmp_path = tmp_path
        self.raiz = tmp_path / "opt/sis-leg"
        self.ruta_vhost_legacy = tmp_path / "etc/nginx/sites-enabled/botonera"
        self.ruta_vhost_disponible = tmp_path / "etc/nginx/sites-available/botonera"
        self.ruta_vhost_sisleg = tmp_path / "etc/nginx/conf.d/sis-leg.conf"
        for ruta in (
            self.ruta_vhost_legacy.parent,
            self.ruta_vhost_disponible.parent,
            self.ruta_vhost_sisleg.parent,
        ):
            ruta.mkdir(parents=True, exist_ok=True)
        self.ruta_vhost_disponible.write_text("server { legacy }", encoding="utf-8")

        activas: set[str]
        habilitadas: set[str]
        if sisleg_activo:
            activas = {*UNIDADES_SISLEG, "nginx.service"}
            habilitadas = set(UNIDADES_SISLEG)
            self.ruta_vhost_sisleg.write_text("server { sis-leg }", encoding="utf-8")
        else:
            activas = {*UNIDADES_LEGACY, "nginx.service"}
            habilitadas = set(UNIDADES_LEGACY)
            self.ruta_vhost_legacy.symlink_to(self.ruta_vhost_disponible)

        self.host = HostSimulado(activas=activas, habilitadas=habilitadas)
        self.gestor = GestorDespliegue(
            self.raiz,
            ejecutor=self.host,
            consultor_json=self._json,
            consultor_texto=self._texto,
            durmiente=lambda segundos: None,
            directorio_systemd=tmp_path / "etc/systemd/system",
            ruta_nginx=self.ruta_vhost_sisleg,
            python_base=Path("/usr/bin/python3"),
        )
        self.gestor.releases.mkdir(parents=True, exist_ok=True)
        self.config_original = crear_config_local(self.gestor)

        if sha_activo is not None:
            release = crear_release_preparada(self.gestor, sha_activo)
            if sisleg_activo:
                self.gestor.current.symlink_to(release.relative_to(self.raiz))
            escribir_target_release(self.raiz, sha_activo)

        self.inspector = InspectorEstadoHost(
            self.raiz,
            ejecutor=self.host,
            sonda_puerto=self._puerto,
            consultor_json=self._json,
            ruta_vhost_legacy=self.ruta_vhost_legacy,
            ruta_vhost_sisleg=self.ruta_vhost_sisleg,
        )
        self.preflights = 0

    # -- fronteras simuladas ------------------------------------------------

    def _json(self, url: str, timeout: float) -> dict[str, Any]:
        """Health y guards institucionales de los dos sistemas."""

        del timeout
        if url.endswith("/estados/estado_global"):
            return {"hay_sesion": False}
        if url.endswith("estado/moderacion"):
            return {"estado_global": "SIN_PREPARAR", "sesion": None}
        return {"estado": "ok"}

    def _texto(self, url: str, timeout: float) -> str:
        del url, timeout
        return "<!doctype html><title>SIS-Leg</title>"

    def _puerto(self, puerto: int) -> bool:
        """Los puertos se derivan del estado real de las unidades simuladas."""

        if puerto == PUERTO_BACKEND:
            return (
                SERVICIO_BACKEND_LEGACY in self.host.activas
                or SERVICIO_BACKEND in self.host.activas
            )
        if puerto == PUERTO_BRIDGE_SISLEG:
            return SERVICIO_BRIDGE in self.host.activas
        return False

    def preflight_simulado(self) -> None:
        """Preflight inyectado: el real sondea binarios que acá no existen."""

        self.preflights += 1

    def operador(
        self,
        *,
        sha_publico: str | None = None,
        shas_publicos: Sequence[str] | None = None,
        release: ReleaseDescargada | None = None,
        error_canal: Exception | None = None,
    ) -> OperadorHost:
        """Construye el operador con el canal público reemplazado por un doble.

        ``shas_publicos`` entrega una respuesta distinta por consulta: sirve para
        reproducir que ``main`` avanzó mientras la actualización estaba en curso.
        La última respuesta se repite si alguien vuelve a preguntar.
        """

        respuestas = list(shas_publicos) if shas_publicos is not None else []

        def resolver() -> str:
            if respuestas:
                return respuestas.pop(0) if len(respuestas) > 1 else respuestas[0]
            if sha_publico is None:
                raise ErrorActualizadorPublico("no hay versión publicada")
            return sha_publico

        def obtener(destino: Path) -> ReleaseDescargada:
            del destino
            if error_canal is not None:
                raise error_canal
            assert release is not None
            return release

        return OperadorHost(
            self.raiz,
            gestor=self.gestor,
            inspector=self.inspector,
            ejecutor=self.host,
            resolver_sha_publico=resolver,
            obtener_release=obtener,
            preflight=self.preflight_simulado,
            durmiente=lambda segundos: None,
            reloj=lambda: MARCA_TEMPORAL_FIJA,
            ruta_lock=self.tmp_path / "operacion.lock",
            ruta_vhost_legacy=self.ruta_vhost_legacy,
            ruta_vhost_legacy_disponible=self.ruta_vhost_disponible,
            ruta_vhost_sisleg=self.ruta_vhost_sisleg,
            directorio_descargas=self.tmp_path / "descargas",
        )

    def config_intacta(self) -> bool:
        """``True`` si los tres archivos institucionales siguen byte a byte iguales."""

        return all(
            (self.gestor.config / relativa).read_bytes() == bytes_originales
            for relativa, bytes_originales in self.config_original.items()
        )


def escenario_legacy(tmp_path: Path, *, sha_preparado: str | None = SHA_VIEJO) -> EscenarioHost:
    """Host tal como está hoy: sistema anterior en servicio, SIS-Leg preparado."""

    return EscenarioHost(tmp_path, sisleg_activo=False, sha_activo=sha_preparado)


def escenario_sisleg(tmp_path: Path) -> EscenarioHost:
    """Host con SIS-Leg en servicio sobre la release vieja."""

    return EscenarioHost(tmp_path, sisleg_activo=True, sha_activo=SHA_VIEJO)


# ---------------------------------------------------------------------------
# Actualizar con el sistema anterior activo
# ---------------------------------------------------------------------------


def test_actualizar_con_legacy_activo_prepara_y_fija_target_sin_conmutar(tmp_path: Path) -> None:
    """Actualizar no es conmutar: el recinto sigue atendido por el sistema anterior."""

    escenario = escenario_legacy(tmp_path)
    paquete, sidecar = construir_artefactos(tmp_path, SHA_NUEVO)
    operador = escenario.operador(
        sha_publico=SHA_NUEVO, release=release_descargada(paquete, sidecar, SHA_NUEVO)
    )

    resultado = operador.actualizar()

    assert resultado.muto is True
    assert resultado.estado_final == ESTABLE_LEGACY
    assert leer_target_release(escenario.raiz) == SHA_NUEVO
    assert (escenario.gestor.releases / SHA_NUEVO / MARCADOR_PREPARADA).is_file()
    # El sistema anterior no fue tocado en ningún momento.
    assert SERVICIO_BACKEND_LEGACY in escenario.host.activas
    assert SERVICIO_BRIDGE_LEGACY in escenario.host.activas
    assert SERVICIO_BACKEND not in escenario.host.activas
    assert not escenario.gestor.current.exists()
    assert escenario.config_intacta()
    assert not escenario.host.hubo_dos_bridges_simultaneos()


def test_actualizar_descarta_la_descarga_pero_conserva_la_release(tmp_path: Path) -> None:
    """El tar descargado no se acumula; lo que queda es la release preparada."""

    escenario = escenario_legacy(tmp_path)
    paquete, sidecar = construir_artefactos(tmp_path, SHA_NUEVO)
    operador = escenario.operador(
        sha_publico=SHA_NUEVO, release=release_descargada(paquete, sidecar, SHA_NUEVO)
    )

    operador.actualizar()

    assert not paquete.exists()
    assert not sidecar.exists()
    assert (escenario.gestor.releases / SHA_NUEVO / MARCADOR_PREPARADA).is_file()
    assert (escenario.gestor.releases / SHA_VIEJO).is_dir()


def test_una_descarga_que_no_pudo_prepararse_queda_para_diagnostico(tmp_path: Path) -> None:
    """Si ``preparar`` falla, los artefactos no se borran: sirven para diagnosticar."""

    escenario = escenario_legacy(tmp_path)
    paquete, sidecar = construir_artefactos(tmp_path, SHA_NUEVO)
    sidecar.write_text(f"{'0' * 64}  {paquete.name}\n", encoding="utf-8")
    operador = escenario.operador(
        sha_publico=SHA_NUEVO, release=release_descargada(paquete, sidecar, SHA_NUEVO)
    )

    with pytest.raises(ErrorOperacionHost, match="preparar"):
        operador.actualizar()

    assert paquete.exists()
    assert leer_target_release(escenario.raiz) == SHA_VIEJO


def test_actualizar_es_idempotente_si_la_release_ya_esta_preparada(tmp_path: Path) -> None:
    """Con ``target == main`` y la release lista no se descarga ni se prepara nada."""

    escenario = escenario_legacy(tmp_path)
    descargas: list[Path] = []

    def obtener(destino: Path) -> ReleaseDescargada:
        descargas.append(destino)
        raise AssertionError("no debía descargarse nada")

    operador = OperadorHost(
        escenario.raiz,
        gestor=escenario.gestor,
        inspector=escenario.inspector,
        ejecutor=escenario.host,
        resolver_sha_publico=lambda: SHA_VIEJO,
        obtener_release=obtener,
        preflight=escenario.preflight_simulado,
        durmiente=lambda segundos: None,
        ruta_lock=tmp_path / "operacion.lock",
        ruta_vhost_legacy=escenario.ruta_vhost_legacy,
        ruta_vhost_legacy_disponible=escenario.ruta_vhost_disponible,
        ruta_vhost_sisleg=escenario.ruta_vhost_sisleg,
        directorio_descargas=tmp_path / "descargas",
    )

    resultado = operador.actualizar()

    assert resultado.muto is False
    assert "ya está actualizado" in resultado.mensaje
    assert descargas == []
    assert escenario.preflights == 0


def test_actualizar_aborta_si_el_canal_publico_no_valida_la_evidencia(tmp_path: Path) -> None:
    """Evidencia de CI inconsistente o publicación inválida: no se muta nada."""

    escenario = escenario_legacy(tmp_path)
    operador = escenario.operador(
        sha_publico=SHA_NUEVO,
        error_canal=ErrorActualizadorPublico("el intento de CI declarado no fue exitoso"),
    )

    with pytest.raises(ErrorOperacionHost, match="release pública"):
        operador.actualizar()

    assert leer_target_release(escenario.raiz) == SHA_VIEJO
    assert not (escenario.gestor.releases / SHA_NUEVO).exists()
    assert escenario.config_intacta()


def test_actualizar_rechaza_un_paquete_con_checksum_invalido(tmp_path: Path) -> None:
    """Una descarga truncada no puede prepararse: manda el sidecar canónico."""

    escenario = escenario_legacy(tmp_path)
    paquete, sidecar = construir_artefactos(tmp_path, SHA_NUEVO)
    paquete.write_bytes(paquete.read_bytes()[:-64])  # descarga truncada
    operador = escenario.operador(
        sha_publico=SHA_NUEVO, release=release_descargada(paquete, sidecar, SHA_NUEVO)
    )

    with pytest.raises(ErrorOperacionHost, match="preparar"):
        operador.actualizar()

    assert leer_target_release(escenario.raiz) == SHA_VIEJO
    assert not (escenario.gestor.releases / SHA_NUEVO).exists()


def test_actualizar_aborta_desde_un_estado_inconsistente(tmp_path: Path) -> None:
    """Ninguna operación mutante puede partir de una mezcla no reconocida."""

    escenario = escenario_legacy(tmp_path)
    escenario.host.activas.add(SERVICIO_BRIDGE)  # dos bridges: estado inconsistente
    operador = escenario.operador(sha_publico=SHA_NUEVO)

    with pytest.raises(ErrorOperacionHost, match="ESTADO_INCONSISTENTE"):
        operador.actualizar()

    assert leer_target_release(escenario.raiz) == SHA_VIEJO


def test_actualizar_aborta_si_hay_sesion_institucional_en_curso(tmp_path: Path) -> None:
    """El guard institucional va antes que cualquier consulta al canal público."""

    escenario = escenario_legacy(tmp_path)

    def consultor_con_sesion(url: str, timeout: float) -> dict[str, Any]:
        del url, timeout
        return {"hay_sesion": True}

    escenario.inspector.consultor_json = consultor_con_sesion
    operador = escenario.operador(sha_publico=SHA_NUEVO)

    with pytest.raises(Exception, match="sesión en curso"):
        operador.actualizar()

    assert leer_target_release(escenario.raiz) == SHA_VIEJO


def test_actualizar_no_pide_nada_si_la_persona_no_confirma(tmp_path: Path) -> None:
    """El plan se muestra antes de mutar y una negativa deja el host intacto."""

    escenario = escenario_legacy(tmp_path)
    paquete, sidecar = construir_artefactos(tmp_path, SHA_NUEVO)
    operador = escenario.operador(
        sha_publico=SHA_NUEVO, release=release_descargada(paquete, sidecar, SHA_NUEVO)
    )
    planes: list[PlanOperacion] = []

    def rechazar(plan: PlanOperacion) -> bool:
        planes.append(plan)
        return False

    resultado = operador.actualizar(confirmador=rechazar)

    assert resultado.muto is False
    assert planes[0].sha_objetivo == SHA_NUEVO
    assert planes[0].estado_inicial == ESTABLE_LEGACY
    assert leer_target_release(escenario.raiz) == SHA_VIEJO


# ---------------------------------------------------------------------------
# Actualizar con SIS-Leg activo
# ---------------------------------------------------------------------------


def test_actualizar_con_sisleg_activo_conmuta_en_caliente_sin_pasar_por_legacy(
    tmp_path: Path,
) -> None:
    """SIS-Leg -> SIS-Leg: version-agnóstico, con health completo y sin Legacy."""

    escenario = escenario_sisleg(tmp_path)
    paquete, sidecar = construir_artefactos(tmp_path, SHA_NUEVO)
    operador = escenario.operador(
        sha_publico=SHA_NUEVO, release=release_descargada(paquete, sidecar, SHA_NUEVO)
    )

    resultado = operador.actualizar()

    assert resultado.estado_final == ESTABLE_SISLEG
    assert leer_target_release(escenario.raiz) == SHA_NUEVO
    assert escenario.gestor.current.resolve().name == SHA_NUEVO
    assert escenario.gestor.previous.resolve().name == SHA_VIEJO
    # El sistema anterior nunca se levantó durante una actualización en caliente.
    assert SERVICIO_BACKEND_LEGACY not in escenario.host.activas
    assert not escenario.host.hubo_dos_bridges_simultaneos()
    assert escenario.config_intacta()


def test_actualizar_revierte_a_la_release_anterior_si_falla_la_activacion(
    tmp_path: Path,
) -> None:
    """Ante falla se vuelve a la release previa y el target anterior se conserva."""

    escenario = escenario_sisleg(tmp_path)
    paquete, sidecar = construir_artefactos(tmp_path, SHA_NUEVO)
    operador = escenario.operador(
        sha_publico=SHA_NUEVO, release=release_descargada(paquete, sidecar, SHA_NUEVO)
    )
    escenario.host.fallas = ("restart sis-leg-device-bridge.service",)

    with pytest.raises(ErrorOperacionHost, match="restauró la release anterior"):
        operador.actualizar()

    assert escenario.gestor.current.resolve().name == SHA_VIEJO
    assert leer_target_release(escenario.raiz) == SHA_VIEJO
    assert escenario.config_intacta()
    assert not escenario.host.hubo_dos_bridges_simultaneos()


def test_actualizar_aborta_si_current_y_target_divergen(tmp_path: Path) -> None:
    """Un estado que no se puede resolver de forma inequívoca es fail-safe."""

    escenario = escenario_sisleg(tmp_path)
    crear_release_preparada(escenario.gestor, SHA_NUEVO)
    escribir_target_release(escenario.raiz, SHA_NUEVO)  # target != current
    operador = escenario.operador(sha_publico=SHA_NUEVO)

    with pytest.raises(ErrorOperacionHost, match="ambiguo|inequívoca"):
        operador.actualizar()

    assert escenario.gestor.current.resolve().name == SHA_VIEJO


# ---------------------------------------------------------------------------
# Contrato de configuración local
# ---------------------------------------------------------------------------


RECURSO_CON_BOOTSTRAP = "config/apoyo-tecnico/mensajes.csv"


def contrato_con_recurso_nuevo() -> list[dict[str, Any]]:
    """Contrato vigente, pero declarando bootstrap para un recurso que hoy no lo tiene.

    Así se ejercita el alta add-only real: el recurso falta en el host y la
    release trae contenido para crearlo. Como bootstrap alcanza cualquier archivo
    regular de la release; lo que se prueba es la política de creación, no el
    contenido concreto del recurso.
    """

    base = json.loads((RAIZ_REPOSITORIO / RUTA_CONTRATO_EN_RELEASE).read_text(encoding="utf-8"))
    recursos: list[dict[str, Any]] = []
    for recurso in base["recursos"]:
        if recurso["ruta_local"] != RECURSO_CON_BOOTSTRAP:
            recursos.append(recurso)
            continue
        recursos.append(
            {
                **recurso,
                "bootstrap": "deploy/nginx/sis-leg.conf",
                "usuario": "sis-leg-backend",
                "grupo": "sis-leg-backend",
                "modo": "0640",
            }
        )
    return recursos


def test_actualizar_incorpora_add_only_un_recurso_nuevo_ausente(tmp_path: Path) -> None:
    """Un recurso que falta se crea desde la release; los existentes no se tocan."""

    escenario = escenario_legacy(tmp_path)
    paquete, sidecar = construir_artefactos(
        tmp_path, SHA_NUEVO, contrato=contrato_con_recurso_nuevo()
    )
    operador = escenario.operador(
        sha_publico=SHA_NUEVO, release=release_descargada(paquete, sidecar, SHA_NUEVO)
    )

    resultado = operador.actualizar()

    creado = escenario.gestor.config / "apoyo-tecnico/mensajes.csv"
    assert creado.is_file()
    assert "config/apoyo-tecnico/mensajes.csv" in resultado.configuracion_incorporada
    assert escenario.config_intacta()


def test_actualizar_no_sobrescribe_un_recurso_que_ya_existe(tmp_path: Path) -> None:
    """Add-only significa exactamente eso: lo que ya está no se reemplaza."""

    escenario = escenario_legacy(tmp_path)
    existente = escenario.gestor.config / "apoyo-tecnico/mensajes.csv"
    existente.parent.mkdir(parents=True, exist_ok=True)
    existente.write_text("codigo;mensaje\n1;hola\n", encoding="utf-8")
    bytes_previos = existente.read_bytes()

    paquete, sidecar = construir_artefactos(
        tmp_path, SHA_NUEVO, contrato=contrato_con_recurso_nuevo()
    )
    operador = escenario.operador(
        sha_publico=SHA_NUEVO, release=release_descargada(paquete, sidecar, SHA_NUEVO)
    )

    resultado = operador.actualizar()

    assert existente.read_bytes() == bytes_previos
    assert resultado.configuracion_incorporada == []


def test_actualizar_aborta_antes_de_mutar_si_la_release_exige_migrar(tmp_path: Path) -> None:
    """Un cambio de schema sobre un archivo existente exige HUMAN_GATE."""

    escenario = escenario_legacy(tmp_path)
    # La release activa declara el contrato vigente; la nueva cambia el schema
    # de un recurso que ya existe en el host.
    contrato_nuevo = json.loads(
        (RAIZ_REPOSITORIO / RUTA_CONTRATO_EN_RELEASE).read_text(encoding="utf-8")
    )["recursos"]
    for recurso in contrato_nuevo:
        if recurso["ruta_local"] == "config/system.toml":
            recurso["schema"] = "system-toml-v2"
    paquete, sidecar = construir_artefactos(tmp_path, SHA_NUEVO, contrato=contrato_nuevo)

    # Para que exista contrato anterior con el que comparar, se activa SIS-Leg
    # apuntando a la release vieja.
    escenario.gestor.current.symlink_to(Path("releases") / SHA_VIEJO)

    operador = escenario.operador(
        sha_publico=SHA_NUEVO, release=release_descargada(paquete, sidecar, SHA_NUEVO)
    )

    with pytest.raises(ErrorOperacionHost, match="HUMAN_GATE"):
        operador.actualizar()

    assert escenario.config_intacta()
    assert leer_target_release(escenario.raiz) == SHA_VIEJO


# ---------------------------------------------------------------------------
# Conmutación a SIS-Leg
# ---------------------------------------------------------------------------


def test_cambiar_a_sisleg_activa_el_target_y_nunca_deja_dos_bridges(tmp_path: Path) -> None:
    """Secuencia completa: retirar el sistema anterior y activar la release declarada."""

    escenario = escenario_legacy(tmp_path)
    operador = escenario.operador()

    resultado = operador.cambiar_a_sis_leg()

    assert resultado.estado_final == ESTABLE_SISLEG
    assert resultado.sha_objetivo == SHA_VIEJO
    assert escenario.gestor.current.resolve().name == SHA_VIEJO
    assert SERVICIO_BACKEND_LEGACY not in escenario.host.activas
    assert SERVICIO_BRIDGE_LEGACY not in escenario.host.activas
    assert SERVICIO_BACKEND_LEGACY not in escenario.host.habilitadas
    assert not escenario.ruta_vhost_legacy.exists()
    assert not escenario.host.hubo_dos_bridges_simultaneos()
    assert escenario.config_intacta()


def test_cambiar_a_sisleg_detiene_el_bridge_anterior_antes_que_su_backend(
    tmp_path: Path,
) -> None:
    """El orden importa: primero se suelta el hardware, después el backend."""

    escenario = escenario_legacy(tmp_path)
    operador = escenario.operador()
    operador.cambiar_a_sis_leg()

    ordenes = [" ".join(llamada) for llamada in escenario.host.llamadas]
    indice_disable = ordenes.index(f"systemctl disable {SERVICIO_BRIDGE_LEGACY}")
    indice_stop_bridge = ordenes.index(f"systemctl stop {SERVICIO_BRIDGE_LEGACY}")
    indice_stop_backend = ordenes.index(f"systemctl stop {SERVICIO_BACKEND_LEGACY}")
    indice_restart_backend = ordenes.index(f"systemctl restart {SERVICIO_BACKEND}")
    indice_restart_bridge = ordenes.index(f"systemctl restart {SERVICIO_BRIDGE}")
    assert indice_disable < indice_stop_bridge < indice_stop_backend
    assert indice_stop_backend < indice_restart_backend < indice_restart_bridge


def test_cambiar_a_sisleg_es_idempotente(tmp_path: Path) -> None:
    """Si SIS-Leg ya está activo, la operación informa y no muta."""

    escenario = escenario_sisleg(tmp_path)
    resultado = escenario.operador().cambiar_a_sis_leg()

    assert resultado.muto is False
    assert "ya estaba activo" in resultado.mensaje


def test_cambiar_a_sisleg_sin_target_declarado_no_muta(tmp_path: Path) -> None:
    """Sin ``target-release`` no hay nada que activar y el host queda intacto."""

    escenario = escenario_legacy(tmp_path, sha_preparado=None)
    operador = escenario.operador()

    with pytest.raises(ErrorOperacionHost, match="target-release"):
        operador.cambiar_a_sis_leg()

    assert SERVICIO_BACKEND_LEGACY in escenario.host.activas


def test_cambiar_a_sisleg_rechaza_un_target_que_apunta_a_una_release_incompleta(
    tmp_path: Path,
) -> None:
    """El target se valida antes de tocar el sistema anterior, no después."""

    escenario = escenario_legacy(tmp_path)
    (escenario.gestor.releases / SHA_VIEJO / MARCADOR_PREPARADA).unlink()
    operador = escenario.operador()

    with pytest.raises(Exception, match="marcador"):
        operador.cambiar_a_sis_leg()

    assert SERVICIO_BACKEND_LEGACY in escenario.host.activas
    assert escenario.ruta_vhost_legacy.exists()


def test_cambiar_a_sisleg_restaura_el_sistema_anterior_si_falla_la_activacion(
    tmp_path: Path,
) -> None:
    """Rollback externo completo, sin borrar releases, configuración ni registros."""

    escenario = escenario_legacy(tmp_path)
    operador = escenario.operador()
    escenario.host.fallas = (f"restart {SERVICIO_BACKEND}",)

    with pytest.raises(ErrorOperacionHost, match="se restauró el sistema anterior"):
        operador.cambiar_a_sis_leg()

    assert escenario.inspector.clasificar() == ESTABLE_LEGACY
    assert SERVICIO_BACKEND_LEGACY in escenario.host.activas
    assert SERVICIO_BRIDGE_LEGACY in escenario.host.activas
    assert escenario.ruta_vhost_legacy.is_symlink()
    assert not escenario.gestor.current.exists()
    assert (escenario.gestor.releases / SHA_VIEJO).is_dir()
    assert escenario.config_intacta()
    assert not escenario.host.hubo_dos_bridges_simultaneos()


# ---------------------------------------------------------------------------
# Conmutación al sistema anterior
# ---------------------------------------------------------------------------


def test_cambiar_a_legacy_retira_sisleg_y_conserva_todo(tmp_path: Path) -> None:
    """Independiente de versión: no borra releases ni configuración de SIS-Leg."""

    escenario = escenario_sisleg(tmp_path)
    operador = escenario.operador()

    resultado = operador.cambiar_a_legacy()

    assert resultado.estado_final == ESTABLE_LEGACY
    assert SERVICIO_BRIDGE not in escenario.host.activas
    assert SERVICIO_BACKEND not in escenario.host.activas
    assert SERVICIO_BACKEND not in escenario.host.habilitadas
    assert not escenario.ruta_vhost_sisleg.exists()
    assert escenario.ruta_vhost_sisleg.with_name("sis-leg.conf.disabled").is_file()
    assert not escenario.gestor.current.exists()
    assert (escenario.gestor.releases / SHA_VIEJO).is_dir()
    assert leer_target_release(escenario.raiz) == SHA_VIEJO
    assert escenario.config_intacta()
    assert not escenario.host.hubo_dos_bridges_simultaneos()


def test_cambiar_a_legacy_es_idempotente(tmp_path: Path) -> None:
    """Pedir el sistema que ya está activo no puede mutar nada."""

    escenario = escenario_legacy(tmp_path)
    resultado = escenario.operador().cambiar_a_legacy()

    assert resultado.muto is False
    assert "ya estaba activo" in resultado.mensaje


def test_cambiar_a_legacy_aborta_desde_un_estado_inconsistente(tmp_path: Path) -> None:
    """No existe recuperación destructiva automática desde estados ambiguos."""

    escenario = escenario_sisleg(tmp_path)
    escenario.host.activas.add(SERVICIO_BRIDGE_LEGACY)
    operador = escenario.operador()

    with pytest.raises(ErrorOperacionHost, match="ESTADO_INCONSISTENTE"):
        operador.cambiar_a_legacy()


def test_una_operacion_no_puede_empezar_mientras_otra_tiene_el_lock(tmp_path: Path) -> None:
    """El lock global es el mismo para conmutación y actualización."""

    escenario = escenario_legacy(tmp_path)
    operador = escenario.operador()

    def confirmador_que_reentra(plan: PlanOperacion) -> bool:
        del plan
        with pytest.raises(Exception, match="operación de SIS-Leg en curso"):
            operador.cambiar_a_legacy()
        return False

    operador.cambiar_a_sis_leg(confirmador=confirmador_que_reentra)


# ---------------------------------------------------------------------------
# Superficies, Zócalo y ausencia de credenciales
# ---------------------------------------------------------------------------


def test_la_release_preparada_incluye_el_zocalo_como_superficie_verificable(
    tmp_path: Path,
) -> None:
    """El Zócalo viaja en la release y se sonda como una superficie más."""

    escenario = escenario_legacy(tmp_path)
    paquete, sidecar = construir_artefactos(tmp_path, SHA_NUEVO)
    operador = escenario.operador(
        sha_publico=SHA_NUEVO, release=release_descargada(paquete, sidecar, SHA_NUEVO)
    )
    operador.actualizar()

    assert (escenario.gestor.releases / SHA_NUEVO / "web/zocalo/index.html").is_file()
    assert URL_NGINX_ZOCALO in SUPERFICIES_NGINX


# ---------------------------------------------------------------------------
# Revalidación de main durante la actualización
# ---------------------------------------------------------------------------


def test_actualizar_aborta_si_main_avanza_con_legacy_activo(tmp_path: Path) -> None:
    """Una release pública inmutable sigue descargándose aunque ``main`` avance.

    Por eso no alcanza con confiar en que el canal público fallaría: hay que
    volver a preguntar por la cabeza de ``main`` antes de fijar el objetivo. Si
    avanzó, la autorización con la que empezó la operación está vencida.
    """

    escenario = escenario_legacy(tmp_path)
    paquete, sidecar = construir_artefactos(tmp_path, SHA_NUEVO)
    operador = escenario.operador(
        shas_publicos=(SHA_NUEVO, SHA_MAS_NUEVO),
        release=release_descargada(paquete, sidecar, SHA_NUEVO),
    )

    with pytest.raises(ErrorOperacionHost, match="main avanzó"):
        operador.actualizar()

    # El objetivo y el sistema en servicio quedan exactamente como estaban.
    assert leer_target_release(escenario.raiz) == SHA_VIEJO
    assert SERVICIO_BACKEND_LEGACY in escenario.host.activas
    assert not escenario.gestor.current.exists()
    # La release preparada se conserva: preparar es aditivo y sirve de caché y
    # de diagnóstico para el próximo intento.
    assert (escenario.gestor.releases / SHA_NUEVO / MARCADOR_PREPARADA).is_file()


def test_actualizar_aborta_si_main_avanza_con_sisleg_activo(tmp_path: Path) -> None:
    """Con SIS-Leg en servicio, la carrera tampoco puede activar la release vencida."""

    escenario = escenario_sisleg(tmp_path)
    paquete, sidecar = construir_artefactos(tmp_path, SHA_NUEVO)
    operador = escenario.operador(
        shas_publicos=(SHA_NUEVO, SHA_MAS_NUEVO),
        release=release_descargada(paquete, sidecar, SHA_NUEVO),
    )

    with pytest.raises(ErrorOperacionHost, match="main avanzó"):
        operador.actualizar()

    assert escenario.gestor.current.resolve().name == SHA_VIEJO
    assert leer_target_release(escenario.raiz) == SHA_VIEJO
    assert escenario.config_intacta()
    assert not escenario.host.hubo_dos_bridges_simultaneos()


# ---------------------------------------------------------------------------
# disable-first verificable
# ---------------------------------------------------------------------------


def test_cambiar_a_sisleg_aborta_si_el_disable_del_sistema_anterior_no_surte_efecto(
    tmp_path: Path,
) -> None:
    """Un ``disable`` que responde sin error pero no deshabilita detiene la conmutación.

    Se aborta **antes** de detener nada: en ese punto el host sigue entero, así
    que no hace falta ningún rollback y el recinto ni se entera.
    """

    escenario = escenario_legacy(tmp_path)
    escenario.host.disable_inefectivo = frozenset({SERVICIO_BRIDGE_LEGACY})
    operador = escenario.operador()

    with pytest.raises(ErrorOperacionHost, match="disable-first"):
        operador.cambiar_a_sis_leg()

    # El host queda exactamente como estaba: ningún servicio detenido y la
    # habilitación previa restaurada.
    assert escenario.inspector.clasificar() == ESTABLE_LEGACY
    assert SERVICIO_BACKEND_LEGACY in escenario.host.activas
    assert SERVICIO_BRIDGE_LEGACY in escenario.host.activas
    assert SERVICIO_BACKEND_LEGACY in escenario.host.habilitadas
    assert escenario.ruta_vhost_legacy.is_symlink()
    assert not escenario.gestor.current.exists()
    assert not escenario.host.hubo_dos_bridges_simultaneos()


def test_cambiar_a_legacy_aborta_si_el_disable_de_sisleg_no_surte_efecto(
    tmp_path: Path,
) -> None:
    """La misma exigencia gobierna la retirada de SIS-Leg."""

    escenario = escenario_sisleg(tmp_path)
    escenario.host.disable_inefectivo = frozenset({SERVICIO_BACKEND})
    operador = escenario.operador()

    with pytest.raises(ErrorOperacionHost, match="disable-first"):
        operador.cambiar_a_legacy()

    assert escenario.inspector.clasificar() == ESTABLE_SISLEG
    assert SERVICIO_BACKEND in escenario.host.activas
    assert SERVICIO_BRIDGE in escenario.host.activas
    assert SERVICIO_BRIDGE in escenario.host.habilitadas
    assert escenario.gestor.current.resolve().name == SHA_VIEJO
    assert not escenario.host.hubo_dos_bridges_simultaneos()


# ---------------------------------------------------------------------------
# Salida segura hacia el sistema anterior
# ---------------------------------------------------------------------------


def corromper_target(escenario: EscenarioHost) -> None:
    """Deja ``target-release`` ilegible, como lo dejaría una escritura a mano."""

    (escenario.raiz / "target-release").write_text("no-es-un-sha\n", encoding="utf-8")


def test_cambiar_a_legacy_funciona_aunque_el_target_este_corrupto(tmp_path: Path) -> None:
    """Volver al sistema anterior es version-agnóstico y no consume el objetivo.

    Un ``target-release`` corrupto es un problema real y se informa, pero no
    puede impedir la operación de salida segura del host.
    """

    escenario = escenario_sisleg(tmp_path)
    corromper_target(escenario)
    operador = escenario.operador()

    resultado = operador.cambiar_a_legacy()

    assert resultado.estado_final == ESTABLE_LEGACY
    assert resultado.diagnostico_target is not None
    assert "SHA de release válido" in resultado.diagnostico_target
    assert any("target-release ilegible" in accion for accion in resultado.acciones)
    # El archivo corrupto se conserva tal cual para que alguien lo diagnostique.
    assert (escenario.raiz / "target-release").read_text(encoding="utf-8") == "no-es-un-sha\n"
    assert escenario.config_intacta()
    assert not escenario.host.hubo_dos_bridges_simultaneos()


def test_cambiar_a_sisleg_sigue_fallando_cerrado_con_un_target_corrupto(
    tmp_path: Path,
) -> None:
    """Lo que **consume** el objetivo no puede tolerarlo corrupto."""

    escenario = escenario_legacy(tmp_path)
    corromper_target(escenario)
    operador = escenario.operador()

    with pytest.raises(Exception, match="SHA de release válido"):
        operador.cambiar_a_sis_leg()

    assert SERVICIO_BACKEND_LEGACY in escenario.host.activas
    assert escenario.ruta_vhost_legacy.is_symlink()


def test_cambiar_a_legacy_restaura_sisleg_si_el_sistema_anterior_no_vuelve(
    tmp_path: Path,
) -> None:
    """Fail-safe: nunca se pasa de un sistema sano a un host inerte.

    Si el sistema anterior no logra volver a servicio después de haber retirado
    SIS-Leg, se restaura el SIS-Leg que estaba atendiendo el recinto.
    """

    escenario = escenario_sisleg(tmp_path)
    operador = escenario.operador()
    escenario.host.fallas = (f"start {SERVICIO_BACKEND_LEGACY}",)

    with pytest.raises(ErrorOperacionHost, match="se restauró SIS-Leg"):
        operador.cambiar_a_legacy()

    assert escenario.inspector.clasificar() == ESTABLE_SISLEG
    assert escenario.gestor.current.resolve().name == SHA_VIEJO
    assert SERVICIO_BACKEND in escenario.host.activas
    assert SERVICIO_BRIDGE in escenario.host.activas
    assert SERVICIO_BACKEND_LEGACY not in escenario.host.habilitadas
    assert not escenario.ruta_vhost_legacy.exists()
    assert escenario.config_intacta()
    assert not escenario.host.hubo_dos_bridges_simultaneos()
    assert operador.ultimo_resultado is not None
    assert operador.ultimo_resultado.rollback == "EXITOSO"


def test_una_doble_falla_reporta_ambos_errores_y_exige_intervencion_humana(
    tmp_path: Path,
) -> None:
    """Si tampoco se puede restaurar SIS-Leg, no se simula ningún estado bueno."""

    escenario = escenario_sisleg(tmp_path)
    operador = escenario.operador()
    escenario.host.fallas = (
        f"start {SERVICIO_BACKEND_LEGACY}",
        f"restart {SERVICIO_BACKEND}",
    )

    with pytest.raises(ErrorOperacionHost, match="intervención humana inmediata") as excepcion:
        operador.cambiar_a_legacy()

    mensaje = str(excepcion.value)
    assert SERVICIO_BACKEND_LEGACY in mensaje
    assert SERVICIO_BACKEND in mensaje
    assert operador.ultimo_resultado is not None
    assert operador.ultimo_resultado.rollback == "FALLIDO"
    # Ni siquiera en la doble falla se permiten dos bridges a la vez.
    assert not escenario.host.hubo_dos_bridges_simultaneos()


# ---------------------------------------------------------------------------
# Historial operativo
# ---------------------------------------------------------------------------


def leer_historial(ruta: Path) -> list[dict[str, Any]]:
    """Lee el historial JSON Lines que anexa la CLI."""

    return [json.loads(linea) for linea in ruta.read_text(encoding="utf-8").splitlines()]


def test_el_historial_de_una_actualizacion_exitosa_conserva_la_evidencia_publica(
    tmp_path: Path,
) -> None:
    """Timestamp, estado, exit code y trazabilidad del canal público, sin secretos."""

    escenario = escenario_legacy(tmp_path)
    paquete, sidecar = construir_artefactos(tmp_path, SHA_NUEVO)
    operador = escenario.operador(
        sha_publico=SHA_NUEVO, release=release_descargada(paquete, sidecar, SHA_NUEVO)
    )
    historial = tmp_path / "registros/operaciones.jsonl"

    resultado = operador.actualizar()
    assert registrar_en_historial(historial, resultado) is True

    (registro,) = leer_historial(historial)
    assert registro["estado"] == "EXITO"
    assert registro["exit_code"] == 0
    assert registro["timestamp"] == MARCA_TEMPORAL_FIJA
    assert registro["estado_inicial"] == ESTABLE_LEGACY
    assert registro["estado_final"] == ESTABLE_LEGACY
    assert registro["rollback"] == "NO_APLICA"
    evidencia = registro["evidencia_publica"]
    assert evidencia["commit_sha"] == SHA_NUEVO
    assert evidencia["tree_sha"] == SHA_ARBOL
    assert evidencia["ci_run_id"] == 1
    assert evidencia["ci_run_numero"] == 1
    assert evidencia["ci_run_intento"] == 1
    assert evidencia["ci_job_id"] == 2
    assert evidencia["paquete"] == paquete.name
    assert evidencia["paquete_sha256"] is not None and len(evidencia["paquete_sha256"]) == 64
    for patron in PATRONES_CREDENCIALES:
        assert re.search(patron, historial.read_text(encoding="utf-8")) is None


def test_el_historial_registra_una_cancelacion(tmp_path: Path) -> None:
    """«No hice nada porque me dijeron que no» también es evidencia."""

    escenario = escenario_legacy(tmp_path)
    paquete, sidecar = construir_artefactos(tmp_path, SHA_NUEVO)
    operador = escenario.operador(
        sha_publico=SHA_NUEVO, release=release_descargada(paquete, sidecar, SHA_NUEVO)
    )
    historial = tmp_path / "registros/operaciones.jsonl"

    resultado = operador.actualizar(confirmador=lambda plan: False)
    registrar_en_historial(historial, resultado)

    (registro,) = leer_historial(historial)
    assert registro["estado"] == "CANCELADA"
    assert registro["exit_code"] == 0
    assert registro["muto"] is False
    assert leer_target_release(escenario.raiz) == SHA_VIEJO


def test_el_historial_registra_una_falla_con_su_rollback(tmp_path: Path) -> None:
    """El caso que la implementación anterior no registraba: la operación que falló."""

    escenario = escenario_sisleg(tmp_path)
    paquete, sidecar = construir_artefactos(tmp_path, SHA_NUEVO)
    operador = escenario.operador(
        sha_publico=SHA_NUEVO, release=release_descargada(paquete, sidecar, SHA_NUEVO)
    )
    escenario.host.fallas = (f"restart {SERVICIO_BRIDGE}",)
    historial = tmp_path / "registros/operaciones.jsonl"

    with pytest.raises(ErrorOperacionHost) as excepcion:
        operador.actualizar()

    resultado = resultado_de_falla(operador, "actualizar", excepcion.value)
    assert registrar_en_historial(historial, resultado) is True

    (registro,) = leer_historial(historial)
    assert registro["estado"] == "FALLA"
    assert registro["exit_code"] == 1
    assert registro["rollback"] == "EXITOSO"
    assert registro["estado_final"] == ESTABLE_SISLEG
    assert registro["target_final"] == SHA_VIEJO
    assert registro["error"]
    assert registro["evidencia_publica"]["commit_sha"] == SHA_NUEVO
    assert registro["timestamp"] == MARCA_TEMPORAL_FIJA


def test_una_falla_que_ocurre_antes_de_conocer_el_estado_igual_se_registra(
    tmp_path: Path,
) -> None:
    """Incluso un intento que ni siquiera llegó a clasificar el host deja rastro."""

    escenario = escenario_legacy(tmp_path)
    operador = escenario.operador()
    historial = tmp_path / "registros/operaciones.jsonl"

    resultado = resultado_de_falla(operador, "actualizar", RuntimeError("lock tomado"))
    registrar_en_historial(historial, resultado)

    (registro,) = leer_historial(historial)
    assert registro["estado"] == "FALLA"
    assert registro["estado_inicial"] == "DESCONOCIDO"
    assert registro["error"] == "lock tomado"
    assert registro["exit_code"] == 1


def test_un_historial_que_no_se_puede_escribir_no_falsea_la_operacion(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """El registro es importante, pero no es la razón por la que se actualiza el host.

    Una conmutación que dejó el recinto funcionando no puede convertirse en un
    fracaso porque el archivo de historial no se pudo escribir; y la falla del
    registro tampoco puede silenciarse.
    """

    escenario = escenario_legacy(tmp_path)
    operador = escenario.operador()
    resultado = operador.cambiar_a_legacy()
    bloqueo = tmp_path / "bloqueo"
    bloqueo.write_text("no soy un directorio", encoding="utf-8")

    assert registrar_en_historial(bloqueo / "operaciones.jsonl", resultado) is False

    capturado = capsys.readouterr()
    assert "no se pudo anexar el historial" in capturado.err
    assert resultado.estado == "EXITO"
    assert resultado.exit_code == 0


PATRONES_CREDENCIALES = (
    r"\bgh\s+auth\b",
    r"\.github_token\b",
    r"\bAuthorization\b",
    r"\bGITHUB_TOKEN\b",
    r"\bPAT\b",
    r"\btoken=",
)


def test_los_modulos_del_host_no_dependen_de_credenciales_de_github() -> None:
    """Ninguna operación del host puede necesitar ``gh``, PAT, token ni login.

    Es una comprobación textual deliberada: el requisito de WP-100 y WP-101 no es
    sólo que hoy funcione sin credenciales, sino que nadie pueda reintroducirlas
    sin que la CI lo note.
    """

    modulos = (
        "deploy/operaciones_host.py",
        "deploy/estado_host.py",
        "deploy/instalador_host.py",
        "deploy/host/sisleg-operacion",
        "deploy/host/actualizar-sisleg.sh",
        "deploy/host/control-cambiar-sisleg.sh",
        "deploy/host/control-cambiar-legacy.sh",
    )
    for relativa in modulos:
        texto = (RAIZ_REPOSITORIO / relativa).read_text(encoding="utf-8")
        for patron in PATRONES_CREDENCIALES:
            assert re.search(patron, texto) is None, f"{relativa} menciona {patron}"
