"""Pruebas del aplicador que WP-101B usará sobre el host real (WP-101A).

Qué demuestran
--------------

- que el modo plan inventaría el host y **no escribe nada**;
- que aplicar exige confirmación explícita;
- que todo wrapper reemplazado se respalda antes de escribirse;
- que la instalación es atómica, con modo y propietario declarados;
- que el conjunto de destinos es cerrado y no incluye ``.desktop``, ``sudoers``,
  PolicyKit, configuración local, releases ni unidades de systemd;
- que el aplicador es idempotente: correrlo dos veces no reescribe lo igual;
- que un destino que sea enlace simbólico se rechaza en lugar de seguirse.

Todo ocurre bajo ``tmp_path``: no se escribe en ``/usr/local/bin``, ``/etc`` ni en
el home productivo, y el ``chown`` se observa a través del ejecutor inyectado en
lugar de ejecutarse.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from deploy.herramienta_despliegue import ResultadoComando
from deploy.instalador_host import (
    ACCION_CREAR,
    ACCION_REEMPLAZAR,
    ACCION_SIN_CAMBIO,
    ErrorInstaladorHost,
    InstaladorHost,
)

RAIZ_REPOSITORIO = Path(__file__).resolve().parents[1]

COMPONENTES_EN_RELEASE = (
    "deploy/host/sisleg-operacion",
    "deploy/host/actualizar-sisleg.sh",
    "deploy/host/control-cambiar-sisleg.sh",
    "deploy/host/control-cambiar-legacy.sh",
)


class EjecutorChownFalso:
    """Registra los ``chown`` sin ejecutarlos: la suite no corre como root."""

    def __init__(self) -> None:
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
        self.llamadas.append([str(valor) for valor in argumentos])
        return ResultadoComando(0)


def crear_release(tmp_path: Path) -> Path:
    """Copia los wrappers versionados reales a una release de fantasía.

    Se usan los archivos del repositorio y no copias inventadas: así, si alguien
    renombra o borra un wrapper canónico, estas pruebas fallan.
    """

    release = tmp_path / "releases/aaaa"
    for relativa in COMPONENTES_EN_RELEASE:
        destino = release / relativa
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes((RAIZ_REPOSITORIO / relativa).read_bytes())
    return release


def crear_instalador(tmp_path: Path) -> tuple[InstaladorHost, EjecutorChownFalso, Path]:
    """Arma el aplicador sobre un host simulado y devuelve sus piezas."""

    release = crear_release(tmp_path)
    ejecutor = EjecutorChownFalso()
    home = tmp_path / "home/operador"
    instalador = InstaladorHost(
        release,
        raiz_respaldos=tmp_path / "respaldos",
        usuario_operador="operador",
        home_operador=home,
        directorio_binarios=tmp_path / "usr/local/bin",
        ejecutor=ejecutor,
        reloj=lambda: time.gmtime(0),
    )
    return instalador, ejecutor, home


def test_el_plan_no_escribe_absolutamente_nada(tmp_path: Path) -> None:
    """El modo de inventario es el que WP-101B correrá primero sobre el host real."""

    instalador, ejecutor, home = crear_instalador(tmp_path)

    plan = instalador.planificar()

    assert [entrada.accion for entrada in plan] == [ACCION_CREAR] * 4
    assert all(not entrada.inventario.existe for entrada in plan)
    assert ejecutor.llamadas == []
    assert not home.exists()
    assert not (tmp_path / "usr/local/bin").exists()


def test_aplicar_sin_confirmacion_no_modifica_nada(tmp_path: Path) -> None:
    """Escribir sobre el host productivo exige una decisión consciente."""

    instalador, _, home = crear_instalador(tmp_path)

    with pytest.raises(ErrorInstaladorHost, match="confirmación"):
        instalador.aplicar()

    assert not home.exists()


def test_aplicar_instala_los_cuatro_componentes_con_modo_y_duenio(tmp_path: Path) -> None:
    """Cada destino recibe el contenido de la release, su modo y su propietario."""

    instalador, ejecutor, home = crear_instalador(tmp_path)

    resultado = instalador.aplicar(confirmado=True)

    entrada_privilegiada = tmp_path / "usr/local/bin/sisleg-operacion"
    assert entrada_privilegiada.is_file()
    assert oct(entrada_privilegiada.stat().st_mode & 0o777) == "0o755"
    assert (
        entrada_privilegiada.read_bytes()
        == (RAIZ_REPOSITORIO / "deploy/host/sisleg-operacion").read_bytes()
    )
    for nombre in (
        "actualizar-sisleg.sh",
        "control-cambiar-sisleg.sh",
        "control-cambiar-legacy.sh",
    ):
        assert (home / ".local/bin" / nombre).is_file()
    assert len(resultado.instalados) == 4
    assert resultado.respaldados == ()
    assert resultado.directorio_respaldos is None

    propietarios = {llamada[2] for llamada in ejecutor.llamadas}
    assert propietarios == {"root:root", "operador:operador"}
    assert all(llamada[1] == "--no-dereference" for llamada in ejecutor.llamadas)


def test_un_wrapper_existente_se_respalda_antes_de_reemplazarse(tmp_path: Path) -> None:
    """El wrapper escrito a mano en el host no se pierde: queda una copia fechada."""

    instalador, _, home = crear_instalador(tmp_path)
    anterior = home / ".local/bin/actualizar-sisleg.sh"
    anterior.parent.mkdir(parents=True)
    anterior.write_text("#!/bin/sh\n# version historica escrita en el host\n", encoding="utf-8")
    contenido_previo = anterior.read_bytes()

    plan = instalador.planificar()
    entrada = next(entrada for entrada in plan if entrada.destino == str(anterior))
    assert entrada.accion == ACCION_REEMPLAZAR
    assert entrada.respaldo_previsto is not None

    resultado = instalador.aplicar(confirmado=True)

    assert resultado.directorio_respaldos is not None
    respaldo = Path(resultado.respaldados[0])
    assert respaldo.read_bytes() == contenido_previo
    assert anterior.read_bytes() != contenido_previo


def test_aplicar_dos_veces_no_reescribe_lo_que_ya_esta_igual(tmp_path: Path) -> None:
    """Idempotencia: la segunda aplicación no toca nada ni genera respaldos."""

    instalador, _, _ = crear_instalador(tmp_path)
    instalador.aplicar(confirmado=True)

    plan = instalador.planificar()
    assert [entrada.accion for entrada in plan] == [ACCION_SIN_CAMBIO] * 4

    resultado = instalador.aplicar(confirmado=True)
    assert resultado.instalados == ()
    assert resultado.respaldados == ()
    assert len(resultado.sin_cambio) == 4


def test_un_destino_que_es_enlace_simbolico_se_rechaza(tmp_path: Path) -> None:
    """Nunca se escribe a través de un enlace: podría apuntar fuera del host esperado."""

    instalador, _, home = crear_instalador(tmp_path)
    destino = home / ".local/bin/control-cambiar-legacy.sh"
    destino.parent.mkdir(parents=True)
    otro = tmp_path / "otro-archivo.sh"
    otro.write_text("#!/bin/sh\n", encoding="utf-8")
    destino.symlink_to(otro)

    with pytest.raises(ErrorInstaladorHost, match="enlace simbólico"):
        instalador.aplicar(confirmado=True)

    # La compuerta actúa antes de la primera escritura: ni siquiera los
    # componentes previos de la lista llegaron a instalarse.
    assert otro.read_text(encoding="utf-8") == "#!/bin/sh\n"
    assert not (tmp_path / "usr/local/bin/sisleg-operacion").exists()


def test_el_conjunto_de_destinos_es_cerrado_y_excluye_lo_prohibido(tmp_path: Path) -> None:
    """El aplicador no puede tocar lanzadores, privilegios ni configuración local."""

    instalador, _, _ = crear_instalador(tmp_path)

    destinos = [str(componente.destino) for componente in instalador.componentes()]

    assert len(destinos) == 4
    prohibidos = (
        ".desktop",
        "sudoers",
        "polkit",
        "/etc/systemd",
        "/etc/nginx",
        "/opt/sis-leg/config",
        "/opt/sis-leg/releases",
    )
    for destino in destinos:
        for prohibido in prohibidos:
            assert prohibido not in destino


def test_el_aplicador_falla_si_la_release_no_trae_un_componente(tmp_path: Path) -> None:
    """Una release incompleta se detecta al planificar, antes de escribir nada."""

    instalador, _, home = crear_instalador(tmp_path)
    (instalador.release / "deploy/host/sisleg-operacion").unlink()

    with pytest.raises(ErrorInstaladorHost, match="archivo regular"):
        instalador.planificar()

    assert not home.exists()


def test_los_wrappers_versionados_no_contienen_ningun_sha(tmp_path: Path) -> None:
    """Los wrappers deben ser version-agnósticos: el SHA sale de ``target-release``.

    Se comprueba sobre los archivos reales del repositorio, no sobre una copia:
    un SHA incrustado en un wrapper volvería a atar el escritorio a una versión
    concreta, que es justamente lo que la transición eliminó.
    """

    del tmp_path
    for relativa in COMPONENTES_EN_RELEASE:
        texto = (RAIZ_REPOSITORIO / relativa).read_text(encoding="utf-8")
        assert not any(
            len(palabra) == 40 and all(caracter in "0123456789abcdef" for caracter in palabra)
            for palabra in texto.replace("/", " ").split()
        )
