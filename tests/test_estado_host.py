"""Pruebas del estado formal del host, del lock global y de ``target-release`` (WP-101A).

Qué demuestran estas pruebas
----------------------------

- que los cuatro estados formales se derivan de evidencia y no de suposiciones,
  y que cualquier mezcla no reconocida cae en ``ESTADO_INCONSISTENTE``;
- que el lock global impide dos operaciones simultáneas y no se queda esperando;
- que ``target-release`` sólo puede apuntar a una release realmente preparada, y
  que las ocho comprobaciones del contrato están todas presentes, incluida la identidad de árbol;
- que el guard institucional del sistema anterior falla cerrado.

Ninguna prueba usa systemd, Nginx, red ni ``/opt/sis-leg``: el ejecutor, la sonda
de puertos y el consultor HTTP se inyectan, y la raíz de instalación es siempre
un ``tmp_path``.
"""

from __future__ import annotations

import json
import multiprocessing
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from conftest import escribir_release_json_de_prueba

from deploy.estado_host import (
    ESTABLE_LEGACY,
    ESTABLE_SISLEG,
    ESTADO_INCONSISTENTE,
    INERTE_SEGURO,
    MARCADOR_PREPARADA,
    PUERTO_BACKEND,
    PUERTO_BRIDGE_SISLEG,
    SERVICIO_BACKEND_LEGACY,
    SERVICIO_BRIDGE_LEGACY,
    ErrorEstadoHost,
    InspectorEstadoHost,
    escribir_target_release,
    leer_target_release,
    leer_target_release_tolerante,
    lock_operacion_global,
    validar_release_objetivo,
)
from deploy.herramienta_despliegue import (
    SERVICIO_BACKEND,
    SERVICIO_BRIDGE,
    ResultadoComando,
)

SHA = "a" * 40
SHA_OTRO = "b" * 40
# Árbol Git que declaran las releases de fantasía de esta suite.
SHA_ARBOL = "c" * 40
SHA_ARBOL_OTRO = "d" * 40


class EjecutorSystemdFalso:
    """Responde ``is-active``/``is-enabled`` desde un diccionario de unidades.

    Es la única frontera hacia systemd que el inspector usa, así que emularla
    alcanza para reproducir cualquier combinación de servicios sin privilegios y
    sin systemd instalado.
    """

    def __init__(self, activas: set[str], habilitadas: set[str]) -> None:
        self.activas = activas
        self.habilitadas = habilitadas
        self.llamadas: list[list[str]] = []

    def ejecutar(
        self,
        argumentos: Sequence[str],
        *,
        directorio: Path | None = None,
        entorno: Mapping[str, str] | None = None,
        comprobar: bool = True,
    ) -> ResultadoComando:
        del directorio, entorno, comprobar
        args = [str(valor) for valor in argumentos]
        self.llamadas.append(args)
        if args[:2] == ["systemctl", "is-active"]:
            return ResultadoComando(0, "active\n" if args[2] in self.activas else "inactive\n")
        if args[:2] == ["systemctl", "is-enabled"]:
            return ResultadoComando(0, "enabled\n" if args[2] in self.habilitadas else "disabled\n")
        return ResultadoComando(0)


def crear_release_preparada(
    raiz: Path,
    sha: str,
    *,
    commit_en_marcador: str | None = None,
    arbol_en_marcador: str | None = SHA_ARBOL,
    arbol_en_manifest: str | None = SHA_ARBOL,
) -> Path:
    """Materializa ``releases/<SHA>`` con su marcador, como lo dejaría ``preparar``.

    Los dos parámetros de árbol permiten fabricar los casos que exige la octava
    comprobación del contrato: marcador sin ``tree_sha``, con un árbol inválido,
    con uno que no coincide con el manifest, o el caso válido.
    ``arbol_en_manifest=None`` deja la release sin ``release.json``.
    """

    release = raiz / "releases" / sha
    release.mkdir(parents=True)
    marcador: dict[str, str] = {"commit_sha": commit_en_marcador or sha}
    if arbol_en_marcador is not None:
        marcador["tree_sha"] = arbol_en_marcador
    (release / MARCADOR_PREPARADA).write_text(json.dumps(marcador), encoding="utf-8")
    if arbol_en_manifest is not None:
        escribir_release_json_de_prueba(release, sha, arbol_en_manifest)
    return release


def crear_inspector(
    tmp_path: Path,
    *,
    activas: set[str],
    habilitadas: set[str],
    vhost_legacy: bool,
    vhost_sisleg: bool,
    puertos: set[int],
    release_actual: str | None = None,
) -> InspectorEstadoHost:
    """Arma un host completo de fantasía bajo ``tmp_path`` y devuelve su inspector."""

    raiz = tmp_path / "opt/sis-leg"
    (raiz / "releases").mkdir(parents=True, exist_ok=True)
    if release_actual is not None:
        release = crear_release_preparada(raiz, release_actual)
        (raiz / "current").symlink_to(os.path.relpath(release, raiz))

    ruta_legacy = tmp_path / "etc/nginx/sites-enabled/botonera"
    ruta_disponible = tmp_path / "etc/nginx/sites-available/botonera"
    ruta_disponible.parent.mkdir(parents=True, exist_ok=True)
    ruta_disponible.write_text("server {}", encoding="utf-8")
    ruta_legacy.parent.mkdir(parents=True, exist_ok=True)
    if vhost_legacy:
        ruta_legacy.symlink_to(ruta_disponible)

    ruta_sisleg = tmp_path / "etc/nginx/conf.d/sis-leg.conf"
    ruta_sisleg.parent.mkdir(parents=True, exist_ok=True)
    if vhost_sisleg:
        ruta_sisleg.write_text("server {}", encoding="utf-8")

    return InspectorEstadoHost(
        raiz,
        ejecutor=EjecutorSystemdFalso(activas, habilitadas),
        sonda_puerto=lambda puerto: puerto in puertos,
        consultor_json=lambda url, timeout: {"hay_sesion": False},
        ruta_vhost_legacy=ruta_legacy,
        ruta_vhost_sisleg=ruta_sisleg,
    )


UNIDADES_LEGACY = {SERVICIO_BACKEND_LEGACY, SERVICIO_BRIDGE_LEGACY}
UNIDADES_SISLEG = {SERVICIO_BACKEND, SERVICIO_BRIDGE}


def inspector_legacy(tmp_path: Path) -> InspectorEstadoHost:
    """Host en el estado real de hoy: sistema anterior en servicio."""

    return crear_inspector(
        tmp_path,
        activas=UNIDADES_LEGACY | {"nginx.service"},
        habilitadas=UNIDADES_LEGACY,
        vhost_legacy=True,
        vhost_sisleg=False,
        puertos={PUERTO_BACKEND},
    )


def inspector_sisleg(tmp_path: Path, sha: str = SHA) -> InspectorEstadoHost:
    """Host con SIS-Leg en servicio y una release activa coherente."""

    return crear_inspector(
        tmp_path,
        activas=UNIDADES_SISLEG | {"nginx.service"},
        habilitadas=UNIDADES_SISLEG,
        vhost_legacy=False,
        vhost_sisleg=True,
        puertos={PUERTO_BACKEND, PUERTO_BRIDGE_SISLEG},
        release_actual=sha,
    )


# ---------------------------------------------------------------------------
# Clasificación del estado formal
# ---------------------------------------------------------------------------


def test_legacy_activo_se_clasifica_como_estable_legacy(tmp_path: Path) -> None:
    """El estado documentado del host hoy tiene que reconocerse sin ambigüedad."""

    assert inspector_legacy(tmp_path).clasificar() == ESTABLE_LEGACY


def test_sisleg_activo_se_clasifica_como_estable_sisleg(tmp_path: Path) -> None:
    """SIS-Leg en servicio exige además que ``current`` apunte a una release."""

    inspector = inspector_sisleg(tmp_path)
    assert inspector.clasificar() == ESTABLE_SISLEG
    assert inspector.evidencia().release_actual == SHA


def test_host_sin_ningun_sistema_activo_es_inerte_seguro(tmp_path: Path) -> None:
    """Ningún servicio y ningún puerto tomado: no es operativo, pero es seguro."""

    inspector = crear_inspector(
        tmp_path,
        activas={"nginx.service"},
        habilitadas=set(),
        vhost_legacy=False,
        vhost_sisleg=False,
        puertos=set(),
    )
    assert inspector.clasificar() == INERTE_SEGURO


def test_dos_bridges_activos_es_estado_inconsistente(tmp_path: Path) -> None:
    """La mezcla más peligrosa no puede pasar por ninguno de los estados estables."""

    inspector = crear_inspector(
        tmp_path,
        activas=UNIDADES_LEGACY | UNIDADES_SISLEG | {"nginx.service"},
        habilitadas=UNIDADES_LEGACY | UNIDADES_SISLEG,
        vhost_legacy=True,
        vhost_sisleg=True,
        puertos={PUERTO_BACKEND, PUERTO_BRIDGE_SISLEG},
        release_actual=SHA,
    )
    assert inspector.clasificar() == ESTADO_INCONSISTENTE
    with pytest.raises(ErrorEstadoHost, match="bridges"):
        inspector.exigir_maximo_un_bridge()


def test_legacy_activo_pero_no_habilitado_es_inconsistente(tmp_path: Path) -> None:
    """Un sistema que no vuelve tras un reinicio no es un estado estable."""

    inspector = crear_inspector(
        tmp_path,
        activas=UNIDADES_LEGACY | {"nginx.service"},
        habilitadas=set(),
        vhost_legacy=True,
        vhost_sisleg=False,
        puertos={PUERTO_BACKEND},
    )
    assert inspector.clasificar() == ESTADO_INCONSISTENTE


def test_legacy_estable_exige_que_sisleg_este_deshabilitado(tmp_path: Path) -> None:
    """Con SIS-Leg apagado pero todavía ``enabled``, el host no es estable.

    Es el riesgo exacto que *disable-first* busca eliminar: un reinicio en ese
    estado levantaría los dos sistemas a la vez sobre el mismo puerto y los
    mismos numpads.
    """

    inspector = crear_inspector(
        tmp_path,
        activas=UNIDADES_LEGACY | {"nginx.service"},
        habilitadas=UNIDADES_LEGACY | UNIDADES_SISLEG,
        vhost_legacy=True,
        vhost_sisleg=False,
        puertos={PUERTO_BACKEND},
    )
    assert inspector.clasificar() == ESTADO_INCONSISTENTE


def test_sisleg_estable_exige_que_legacy_este_deshabilitado(tmp_path: Path) -> None:
    """La coherencia enabled/disabled se exige en los dos sentidos."""

    inspector = crear_inspector(
        tmp_path,
        activas=UNIDADES_SISLEG | {"nginx.service"},
        habilitadas=UNIDADES_SISLEG | UNIDADES_LEGACY,
        vhost_legacy=False,
        vhost_sisleg=True,
        puertos={PUERTO_BACKEND, PUERTO_BRIDGE_SISLEG},
        release_actual=SHA,
    )
    assert inspector.clasificar() == ESTADO_INCONSISTENTE


def test_exigir_unidades_deshabilitadas_detecta_un_disable_no_efectivo(tmp_path: Path) -> None:
    """La comprobación posterior al ``disable`` nombra exactamente qué quedó mal."""

    inspector = crear_inspector(
        tmp_path,
        activas=set(),
        habilitadas={SERVICIO_BRIDGE_LEGACY},
        vhost_legacy=False,
        vhost_sisleg=False,
        puertos=set(),
    )
    inspector.exigir_unidades_deshabilitadas([SERVICIO_BACKEND_LEGACY])
    with pytest.raises(ErrorEstadoHost, match=SERVICIO_BRIDGE_LEGACY):
        inspector.exigir_unidades_deshabilitadas([SERVICIO_BACKEND_LEGACY, SERVICIO_BRIDGE_LEGACY])


def test_sisleg_activo_sin_current_es_inconsistente(tmp_path: Path) -> None:
    """Servicios de SIS-Leg arriba sin release activa: nadie sabe qué está corriendo."""

    inspector = crear_inspector(
        tmp_path,
        activas=UNIDADES_SISLEG | {"nginx.service"},
        habilitadas=UNIDADES_SISLEG,
        vhost_legacy=False,
        vhost_sisleg=True,
        puertos={PUERTO_BACKEND, PUERTO_BRIDGE_SISLEG},
    )
    assert inspector.clasificar() == ESTADO_INCONSISTENTE


def test_bridge_de_sisleg_ocupando_el_puerto_con_legacy_activo_es_inconsistente(
    tmp_path: Path,
) -> None:
    """La evidencia de puertos detecta lo que systemd por sí solo no vería."""

    inspector = crear_inspector(
        tmp_path,
        activas=UNIDADES_LEGACY | {"nginx.service"},
        habilitadas=UNIDADES_LEGACY,
        vhost_legacy=True,
        vhost_sisleg=False,
        puertos={PUERTO_BACKEND, PUERTO_BRIDGE_SISLEG},
    )
    assert inspector.clasificar() == ESTADO_INCONSISTENTE


# ---------------------------------------------------------------------------
# Guard institucional del sistema anterior
# ---------------------------------------------------------------------------


def test_guard_legacy_rechaza_una_sesion_en_curso(tmp_path: Path) -> None:
    """Con sesión abierta ninguna operación puede mutar el host."""

    inspector = InspectorEstadoHost(
        tmp_path,
        ejecutor=EjecutorSystemdFalso(set(), set()),
        sonda_puerto=lambda puerto: False,
        consultor_json=lambda url, timeout: {"hay_sesion": True},
    )
    with pytest.raises(ErrorEstadoHost, match="sesión en curso"):
        inspector.guard_institucional_legacy()


def test_guard_legacy_falla_cerrado_si_no_puede_consultar(tmp_path: Path) -> None:
    """No poder demostrar la ausencia de sesión equivale a que la haya."""

    def consultor_roto(url: str, timeout: float) -> dict[str, Any]:
        raise OSError("conexión rechazada")

    inspector = InspectorEstadoHost(
        tmp_path,
        ejecutor=EjecutorSystemdFalso(set(), set()),
        sonda_puerto=lambda puerto: False,
        consultor_json=consultor_roto,
    )
    with pytest.raises(ErrorEstadoHost, match="No se pudo consultar"):
        inspector.guard_institucional_legacy()


def test_guard_legacy_rechaza_una_respuesta_sin_el_campo(tmp_path: Path) -> None:
    """Una respuesta que no declara ``hay_sesion`` no demuestra nada."""

    inspector = InspectorEstadoHost(
        tmp_path,
        ejecutor=EjecutorSystemdFalso(set(), set()),
        sonda_puerto=lambda puerto: False,
        consultor_json=lambda url, timeout: {"otro": 1},
    )
    with pytest.raises(ErrorEstadoHost, match="hay_sesion"):
        inspector.guard_institucional_legacy()


# ---------------------------------------------------------------------------
# Contrato de ``target-release``
# ---------------------------------------------------------------------------


def test_target_valido_se_escribe_atomicamente_con_salto_de_linea(tmp_path: Path) -> None:
    """El contenido es exactamente el SHA más ``\\n``, y el modo es 0644."""

    raiz = tmp_path / "opt/sis-leg"
    crear_release_preparada(raiz, SHA)
    destino = escribir_target_release(raiz, SHA)
    assert destino.read_text(encoding="utf-8") == f"{SHA}\n"
    assert oct(destino.stat().st_mode & 0o777) == "0o644"
    assert leer_target_release(raiz) == SHA


def test_target_inexistente_devuelve_none(tmp_path: Path) -> None:
    """Un host recién instalado todavía no declara ningún objetivo."""

    assert leer_target_release(tmp_path / "opt/sis-leg") is None


def test_target_corrupto_no_se_interpreta_con_tolerancia(tmp_path: Path) -> None:
    """Un contenido que no es un SHA exige intervención humana, no una conjetura."""

    raiz = tmp_path / "opt/sis-leg"
    raiz.mkdir(parents=True)
    (raiz / "target-release").write_text("no-es-un-sha\n", encoding="utf-8")
    with pytest.raises(ErrorEstadoHost, match="SHA de release válido"):
        leer_target_release(raiz)


def test_no_se_puede_apuntar_a_una_release_inexistente(tmp_path: Path) -> None:
    """Comprobación 2 del contrato: el directorio de la release debe existir."""

    raiz = tmp_path / "opt/sis-leg"
    (raiz / "releases").mkdir(parents=True)
    with pytest.raises(ErrorEstadoHost, match="no existe"):
        escribir_target_release(raiz, SHA)
    assert not (raiz / "target-release").exists()


def test_no_se_puede_apuntar_a_una_release_que_es_enlace(tmp_path: Path) -> None:
    """Comprobación 3: un enlace podría llevar a activar contenido arbitrario."""

    raiz = tmp_path / "opt/sis-leg"
    real = crear_release_preparada(raiz, SHA_OTRO)
    (raiz / "releases" / SHA).symlink_to(real)
    with pytest.raises(ErrorEstadoHost, match="enlace simbólico"):
        escribir_target_release(raiz, SHA)


def test_no_se_puede_apuntar_a_una_release_sin_marcador(tmp_path: Path) -> None:
    """Comprobación 5: sin marcador la release no está preparada."""

    raiz = tmp_path / "opt/sis-leg"
    (raiz / "releases" / SHA).mkdir(parents=True)
    with pytest.raises(ErrorEstadoHost, match="marcador"):
        escribir_target_release(raiz, SHA)


def test_no_se_puede_apuntar_a_una_release_con_marcador_ilegible(tmp_path: Path) -> None:
    """Comprobación 6: el marcador tiene que parsear como JSON."""

    raiz = tmp_path / "opt/sis-leg"
    release = crear_release_preparada(raiz, SHA)
    (release / MARCADOR_PREPARADA).write_text("{no es json", encoding="utf-8")
    with pytest.raises(ErrorEstadoHost, match="JSON legible"):
        escribir_target_release(raiz, SHA)


def test_no_se_puede_apuntar_a_una_release_cuyo_marcador_declara_otro_commit(
    tmp_path: Path,
) -> None:
    """Comprobación 7: el marcador debe declarar ese mismo ``commit_sha``."""

    raiz = tmp_path / "opt/sis-leg"
    crear_release_preparada(raiz, SHA, commit_en_marcador=SHA_OTRO)
    with pytest.raises(ErrorEstadoHost, match="commit_sha"):
        escribir_target_release(raiz, SHA)


def test_un_target_previo_sobrevive_a_un_intento_invalido(tmp_path: Path) -> None:
    """Validar antes de escribir significa que un intento fallido no borra el valor útil."""

    raiz = tmp_path / "opt/sis-leg"
    crear_release_preparada(raiz, SHA)
    escribir_target_release(raiz, SHA)
    with pytest.raises(ErrorEstadoHost):
        escribir_target_release(raiz, SHA_OTRO)
    assert leer_target_release(raiz) == SHA


def test_validar_release_objetivo_devuelve_la_ruta_canonica(tmp_path: Path) -> None:
    """El resultado es la ruta real de la release, útil para el resto del flujo."""

    raiz = tmp_path / "opt/sis-leg"
    release = crear_release_preparada(raiz, SHA)
    assert validar_release_objetivo(raiz, SHA) == release


# ---------------------------------------------------------------------------
# Octava comprobación: identidad de árbol
# ---------------------------------------------------------------------------


def test_un_marcador_sin_tree_sha_no_demuestra_la_identidad_del_arbol(tmp_path: Path) -> None:
    """Comprobación 8: el commit no alcanza para identificar el contenido."""

    raiz = tmp_path / "opt/sis-leg"
    crear_release_preparada(raiz, SHA, arbol_en_marcador=None)
    with pytest.raises(ErrorEstadoHost, match="identidad de árbol"):
        escribir_target_release(raiz, SHA)
    assert not (raiz / "target-release").exists()


def test_un_tree_sha_invalido_se_rechaza_antes_de_mirar_el_manifest(tmp_path: Path) -> None:
    """Un árbol abreviado o con basura no es un árbol Git y no se interpreta."""

    raiz = tmp_path / "opt/sis-leg"
    crear_release_preparada(raiz, SHA, arbol_en_marcador="no-es-un-arbol")
    with pytest.raises(ErrorEstadoHost, match="tree SHA Git válido"):
        escribir_target_release(raiz, SHA)


def test_un_tree_sha_divergente_del_manifest_se_rechaza(tmp_path: Path) -> None:
    """Marcador y ``release.json`` tienen que declarar exactamente el mismo árbol.

    Es el caso que detecta una release manipulada después de instalada: alguien
    pudo reescribir el marcador, pero el manifest que viajó dentro del paquete
    público sigue declarando el árbol real.
    """

    raiz = tmp_path / "opt/sis-leg"
    crear_release_preparada(raiz, SHA, arbol_en_marcador=SHA_ARBOL_OTRO)
    with pytest.raises(ErrorEstadoHost, match="declara el árbol"):
        escribir_target_release(raiz, SHA)


def test_una_release_sin_manifest_no_puede_demostrar_su_arbol(tmp_path: Path) -> None:
    """Sin ``release.json`` no hay contra qué contrastar el marcador."""

    raiz = tmp_path / "opt/sis-leg"
    crear_release_preparada(raiz, SHA, arbol_en_manifest=None)
    with pytest.raises(ErrorEstadoHost, match="release.json"):
        escribir_target_release(raiz, SHA)


def test_un_tree_sha_coherente_supera_la_octava_comprobacion(tmp_path: Path) -> None:
    """El caso válido: marcador y manifest declaran el mismo árbol."""

    raiz = tmp_path / "opt/sis-leg"
    release = crear_release_preparada(raiz, SHA)
    assert validar_release_objetivo(raiz, SHA) == release
    assert escribir_target_release(raiz, SHA).read_text(encoding="utf-8") == f"{SHA}\n"


# ---------------------------------------------------------------------------
# Independencia entre la clasificación y un target corrupto
# ---------------------------------------------------------------------------


def test_un_target_corrupto_no_impide_clasificar_el_host(tmp_path: Path) -> None:
    """Saber qué sistema está en servicio no depende de qué release se activaría.

    Si un ``target-release`` ilegible bloqueara la clasificación, también
    bloquearía la vuelta al sistema anterior, que es la operación que nunca
    puede quedar impedida por un archivo que ni siquiera va a consumir.
    """

    inspector = inspector_sisleg(tmp_path)
    (inspector.raiz / "target-release").write_text("no-es-un-sha\n", encoding="utf-8")

    evidencia = inspector.evidencia()

    assert inspector.clasificar(evidencia) == ESTABLE_SISLEG
    assert evidencia.target_release is None
    assert evidencia.target_release_diagnostico is not None
    assert "SHA de release válido" in evidencia.target_release_diagnostico


def test_la_lectura_tolerante_no_inventa_un_diagnostico_cuando_todo_esta_bien(
    tmp_path: Path,
) -> None:
    """Sin objetivo declarado no hay error: simplemente todavía no hay uno."""

    assert leer_target_release_tolerante(tmp_path / "opt/sis-leg") == (None, None)


# ---------------------------------------------------------------------------
# Lock global
# ---------------------------------------------------------------------------


def _tomar_lock_en_otro_proceso(ruta: str, listo: Any, seguir: Any) -> None:
    """Toma el lock en un proceso hijo y lo retiene hasta que el padre avise.

    Se usa un proceso y no un hilo porque ``flock`` es por descriptor y por
    proceso: dos hilos del mismo proceso podrían tomarlo dos veces y la prueba
    no demostraría nada.
    """

    with lock_operacion_global(Path(ruta)):
        listo.set()
        seguir.wait(10)


def test_el_lock_global_impide_dos_operaciones_simultaneas(tmp_path: Path) -> None:
    """Mientras otra operación corre, la segunda informa y sale en lugar de esperar."""

    ruta = tmp_path / "operacion.lock"
    contexto = multiprocessing.get_context("fork")
    listo = contexto.Event()
    seguir = contexto.Event()
    proceso = contexto.Process(target=_tomar_lock_en_otro_proceso, args=(str(ruta), listo, seguir))
    proceso.start()
    try:
        assert listo.wait(10)
        with (
            pytest.raises(ErrorEstadoHost, match="operación de SIS-Leg en curso"),
            lock_operacion_global(ruta),
        ):
            pass
    finally:
        seguir.set()
        proceso.join(10)


def test_el_lock_se_libera_al_salir_del_bloque(tmp_path: Path) -> None:
    """Dos operaciones consecutivas son normales; sólo se prohíben las simultáneas."""

    ruta = tmp_path / "operacion.lock"
    with lock_operacion_global(ruta):
        pass
    with lock_operacion_global(ruta):
        pass
