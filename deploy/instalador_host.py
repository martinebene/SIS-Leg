"""Aplicador de los componentes versionados sobre el host productivo (WP-101A).

Para qué existe
---------------

WP-101A no toca producción. Lo que sí hace es dejar preparado, revisado y
probado el mecanismo con el que WP-101B —cuando exista acceso al equipo real y
una compuerta humana específica— instalará los componentes canónicos en el host.

La diferencia importa: hoy los wrappers que operan el host fueron escritos
directamente sobre esa máquina. Con este aplicador, instalarlos deja de ser una
sesión de programación sobre producción y pasa a ser la copia de archivos que ya
viajaron dentro de una release, con inventario previo, respaldo y permisos
declarados.

Qué **nunca** hace
------------------

Estas prohibiciones son parte del contrato y están comprobadas por la suite:

- no modifica lanzadores ``.desktop``: los ajustó una persona a mano y quedan
  fuera de este trabajo;
- no toca ``sudoers``, PolicyKit ni ningún privilegio;
- no escribe configuración local salvo lo que autorice el contrato add-only, que
  es competencia de la herramienta de despliegue y no de este módulo;
- no borra releases, registros ni respaldos;
- no retira ni degrada el sistema anterior;
- no ejecuta ninguna conmutación ni actualización: instalar y operar son dos
  decisiones distintas, y WP-101B puede detenerse después de instalar.

El modo predeterminado es **plan**: inventaría, compara y explica qué cambiaría,
sin escribir un solo byte. Aplicar exige una confirmación explícita.
"""

from __future__ import annotations

import argparse
import grp
import hashlib
import json
import os
import pwd
import stat
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

# Igual que el resto de los módulos de despliegue: producción lo invoca como
# script suelto desde la release y hay que hacer explícita la raíz de imports.
RAIZ_PARA_IMPORTS = Path(__file__).resolve().parents[1]
if str(RAIZ_PARA_IMPORTS) not in sys.path:
    sys.path.insert(0, str(RAIZ_PARA_IMPORTS))

from deploy.herramienta_despliegue import (  # noqa: E402 - raíz preparada arriba
    EjecutorComandos,
    EjecutorSubprocess,
)

# Usuario operador del escritorio institucional. Se declara como constante y se
# puede sobrescribir por parámetro: es un dato del host, no una decisión del
# producto, y WP-101B deberá relevarlo de nuevo antes de aplicar.
USUARIO_OPERADOR_PREDETERMINADO = "concejo"
HOME_OPERADOR_PREDETERMINADO = Path("/home/concejo")

DIRECTORIO_BINARIOS_SISTEMA = Path("/usr/local/bin")
NOMBRE_ENTRADA_PRIVILEGIADA = "sisleg-operacion"

ACCION_CREAR = "CREAR"
ACCION_REEMPLAZAR = "REEMPLAZAR"
ACCION_SIN_CAMBIO = "SIN_CAMBIO"
# Corrige propietario y permisos sin reescribir el contenido. Existe porque un
# archivo con los bytes correctos pero con el modo o el dueño equivocados no
# está bien instalado: la entrada privilegiada del host debe ser inescribible
# para el usuario operador, y eso es una propiedad del archivo, no de su texto.
ACCION_AJUSTAR_METADATA = "AJUSTAR_METADATA"


def uid_de_usuario(usuario: str) -> int | None:
    """UID declarado por el sistema, o ``None`` si ese usuario no existe acá.

    Devolver ``None`` en lugar de fallar permite planificar sobre una máquina
    que no tiene todavía las cuentas institucionales —por ejemplo al revisar el
    plan antes de aplicarlo— sin inventar un propietario.
    """

    try:
        return pwd.getpwnam(usuario).pw_uid
    except KeyError:
        return None


def gid_de_grupo(grupo: str) -> int | None:
    """GID declarado por el sistema, o ``None`` si ese grupo no existe acá."""

    try:
        return grp.getgrnam(grupo).gr_gid
    except KeyError:
        return None


class ErrorInstaladorHost(RuntimeError):
    """Falla segura del aplicador; nunca deja una instalación a medias.

    Cada escritura es atómica y va precedida por su respaldo, así que esta
    excepción significa siempre que el destino quedó como estaba o como lo dejó
    una escritura previa ya respaldada.
    """


@dataclass(frozen=True, slots=True)
class ComponenteInstalable:
    """Un archivo versionado que el host debe tener, y con qué identidad.

    Atributos:
        origen_en_release: ruta relativa dentro de la release donde viaja el
            contenido canónico.
        destino: ruta absoluta en el host.
        usuario, grupo: propietario declarado. Se aplica con ``chown`` a través
            del ejecutor auditable, nunca siguiendo enlaces.
        modo: permisos declarados, siempre explícitos. No se hereda el modo del
            archivo de origen, porque el empaquetado normaliza los modos del tar.
        descripcion: para qué sirve, en la salida del plan.
    """

    origen_en_release: str
    destino: Path
    usuario: str
    grupo: str
    modo: int
    descripcion: str


@dataclass(frozen=True, slots=True)
class EntradaInventario:
    """Estado observado de un destino antes de tocarlo.

    ``sha256`` permite distinguir «ya está instalado lo mismo» de «hay otra
    versión»; ``es_enlace`` existe porque un destino que sea un symlink se
    rechaza en lugar de seguirse.
    """

    destino: str
    existe: bool
    es_enlace: bool
    sha256: str | None
    modo: str | None
    usuario_uid: int | None
    grupo_gid: int | None


@dataclass(frozen=True, slots=True)
class EntradaPlanInstalacion:
    """Qué haría el aplicador con un componente concreto."""

    componente: str
    destino: str
    accion: str
    motivo: str
    inventario: EntradaInventario
    respaldo_previsto: str | None


@dataclass(frozen=True, slots=True)
class ResultadoInstalacion:
    """Qué se instaló realmente y dónde quedaron los respaldos.

    ``metadata_ajustada`` lista los destinos cuyo contenido ya era correcto pero
    cuyo propietario o permisos hubo que corregir. Se informa aparte de
    ``instalados`` porque son dos hechos distintos y el segundo, en un host
    productivo, suele ser el síntoma de una intervención manual previa.
    """

    directorio_respaldos: str | None
    instalados: tuple[str, ...]
    respaldados: tuple[str, ...]
    sin_cambio: tuple[str, ...]
    metadata_ajustada: tuple[str, ...] = ()


def sha256_de(ruta: Path) -> str:
    """Huella del contenido de un archivo, para comparar sin leerlo entero dos veces."""

    digest = hashlib.sha256()
    with ruta.open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
            digest.update(bloque)
    return digest.hexdigest()


class InstaladorHost:
    """Inventaría, respalda e instala los componentes canónicos del host.

    Entradas del constructor:
        release: raíz de la release preparada de donde salen los contenidos.
        raiz_respaldos: directorio donde se guardan copias de lo reemplazado.
        usuario_operador / home_operador: identidad del escritorio institucional.
        directorio_binarios: dónde vive la entrada privilegiada.
        ejecutor: frontera auditable para ``chown``.
        reloj: fuente de la marca temporal del directorio de respaldos; se
            inyecta para que las pruebas sean deterministas.
        resolutor_uid / resolutor_gid: traducen el usuario y el grupo declarados
            a identificadores numéricos para poder compararlos con lo que hay en
            disco. Se inyectan porque la suite corre sin las cuentas del host
            institucional y sin privilegios para crearlas.

    Todo lo que el aplicador toca está declarado en :meth:`componentes`. No hay
    escritura posible fuera de esa lista, y la suite comprueba explícitamente que
    ningún destino sea un ``.desktop``, ``sudoers`` o configuración local.
    """

    def __init__(
        self,
        release: Path,
        *,
        raiz_respaldos: Path | None = None,
        usuario_operador: str = USUARIO_OPERADOR_PREDETERMINADO,
        home_operador: Path = HOME_OPERADOR_PREDETERMINADO,
        directorio_binarios: Path = DIRECTORIO_BINARIOS_SISTEMA,
        ejecutor: EjecutorComandos | None = None,
        reloj: Callable[[], time.struct_time] = time.gmtime,
        resolutor_uid: Callable[[str], int | None] = uid_de_usuario,
        resolutor_gid: Callable[[str], int | None] = gid_de_grupo,
    ) -> None:
        self.release = release
        self.usuario_operador = usuario_operador
        self.home_operador = home_operador
        self.directorio_binarios = directorio_binarios
        self.raiz_respaldos = raiz_respaldos or (home_operador / "sisleg-respaldos-wrappers")
        self.ejecutor = ejecutor or EjecutorSubprocess()
        self.reloj = reloj
        self.resolutor_uid = resolutor_uid
        self.resolutor_gid = resolutor_gid

    def componentes(self) -> tuple[ComponenteInstalable, ...]:
        """Declara el conjunto completo y cerrado de archivos a instalar.

        Los tres wrappers de usuario conservan **exactamente** el nombre y la
        ruta que hoy invocan los lanzadores del escritorio. Esa coincidencia no
        es casual: es lo que permite reemplazar la implementación sin modificar
        ningún ``.desktop``, que está fuera de alcance por decisión explícita.
        """

        binarios = self.directorio_binarios
        local = self.home_operador / ".local/bin"
        propietario = self.usuario_operador
        return (
            ComponenteInstalable(
                origen_en_release="deploy/host/sisleg-operacion",
                destino=binarios / NOMBRE_ENTRADA_PRIVILEGIADA,
                usuario="root",
                grupo="root",
                modo=0o755,
                descripcion="entrada privilegiada única a las operaciones versionadas",
            ),
            ComponenteInstalable(
                origen_en_release="deploy/host/actualizar-sisleg.sh",
                destino=local / "actualizar-sisleg.sh",
                usuario=propietario,
                grupo=propietario,
                modo=0o755,
                descripcion="wrapper del lanzador «Actualizar SIS-Leg»",
            ),
            ComponenteInstalable(
                origen_en_release="deploy/host/control-cambiar-sisleg.sh",
                destino=local / "control-cambiar-sisleg.sh",
                usuario=propietario,
                grupo=propietario,
                modo=0o755,
                descripcion="wrapper del lanzador «Cambiar a SIS-Leg»",
            ),
            ComponenteInstalable(
                origen_en_release="deploy/host/control-cambiar-legacy.sh",
                destino=local / "control-cambiar-legacy.sh",
                usuario=propietario,
                grupo=propietario,
                modo=0o755,
                descripcion="wrapper del lanzador «Cambiar a Legacy»",
            ),
        )

    # ------------------------------------------------------------------
    # Plan (solo lectura)
    # ------------------------------------------------------------------

    def _inventariar(self, destino: Path) -> EntradaInventario:
        """Observa un destino sin modificarlo ni seguir enlaces."""

        if not destino.exists() and not destino.is_symlink():
            return EntradaInventario(str(destino), False, False, None, None, None, None)
        estado = destino.lstat()
        es_enlace = stat.S_ISLNK(estado.st_mode)
        huella = None if es_enlace or not destino.is_file() else sha256_de(destino)
        return EntradaInventario(
            destino=str(destino),
            existe=True,
            es_enlace=es_enlace,
            sha256=huella,
            modo=f"{stat.S_IMODE(estado.st_mode):04o}",
            usuario_uid=estado.st_uid,
            grupo_gid=estado.st_gid,
        )

    def _origen(self, componente: ComponenteInstalable) -> Path:
        """Ruta del contenido canónico dentro de la release, ya comprobada."""

        origen = self.release / componente.origen_en_release
        if origen.is_symlink() or not origen.is_file():
            raise ErrorInstaladorHost(
                f"La release no trae el componente {componente.origen_en_release} como archivo "
                f"regular: {origen}"
            )
        return origen

    def _diferencias_de_metadata(
        self, componente: ComponenteInstalable, inventario: EntradaInventario
    ) -> list[str]:
        """Enumera en castellano qué parte de la metadata no es la declarada.

        Resultado: lista vacía cuando modo, usuario y grupo son demostrablemente
        los correctos; en cualquier otro caso, una descripción por diferencia.

        Un propietario que no se puede resolver cuenta como diferencia y no como
        coincidencia. La razón es la de siempre en este módulo: no se declara
        correcto lo que no se pudo demostrar. Aplicar ``chown`` y ``chmod`` de
        más es inocuo; dar por bueno un binario privilegiado con el dueño
        equivocado, no.
        """

        diferencias: list[str] = []
        modo_declarado = f"{componente.modo:04o}"
        if inventario.modo != modo_declarado:
            diferencias.append(f"modo {inventario.modo} en lugar de {modo_declarado}")

        uid_declarado = self.resolutor_uid(componente.usuario)
        if uid_declarado is None:
            diferencias.append(
                f"no se pudo resolver el usuario declarado {componente.usuario} para comprobar "
                "el propietario"
            )
        elif inventario.usuario_uid != uid_declarado:
            diferencias.append(
                f"UID {inventario.usuario_uid} en lugar de {uid_declarado} ({componente.usuario})"
            )

        gid_declarado = self.resolutor_gid(componente.grupo)
        if gid_declarado is None:
            diferencias.append(
                f"no se pudo resolver el grupo declarado {componente.grupo} para comprobar el "
                "grupo propietario"
            )
        elif inventario.grupo_gid != gid_declarado:
            diferencias.append(
                f"GID {inventario.grupo_gid} en lugar de {gid_declarado} ({componente.grupo})"
            )
        return diferencias

    def planificar(self) -> tuple[EntradaPlanInstalacion, ...]:
        """Calcula el plan completo sin escribir absolutamente nada.

        Resultado: una entrada por componente, con el inventario observado, la
        acción prevista y dónde iría su respaldo.

        Es el modo que WP-101B debe ejecutar primero sobre el host real: permite
        comparar el estado instalado hoy contra lo que preparó WP-101A antes de
        pedir ninguna autorización de escritura.

        Un destino sólo se declara ``SIN_CAMBIO`` cuando coinciden **las dos**
        cosas: el contenido y la metadata declarada. Que los bytes sean los
        correctos no alcanza, porque el permiso y el propietario son parte de lo
        que hace segura a la entrada privilegiada del host.
        """

        marca = self._marca_temporal()
        plan: list[EntradaPlanInstalacion] = []
        for componente in self.componentes():
            origen = self._origen(componente)
            inventario = self._inventariar(componente.destino)
            if inventario.es_enlace:
                accion = ACCION_REEMPLAZAR
                motivo = (
                    f"{componente.destino} es un enlace simbólico; el aplicador lo rechazará "
                    "en lugar de escribir a través de él."
                )
            elif not inventario.existe:
                accion = ACCION_CREAR
                motivo = f"{componente.destino} no existe y se creará desde la release."
            elif inventario.sha256 != sha256_de(origen):
                accion = ACCION_REEMPLAZAR
                motivo = (
                    f"{componente.destino} existe con otro contenido; se respaldará antes de "
                    "reemplazarlo."
                )
            else:
                diferencias = self._diferencias_de_metadata(componente, inventario)
                if diferencias:
                    accion = ACCION_AJUSTAR_METADATA
                    motivo = (
                        f"{componente.destino} ya contiene la versión de la release, pero su "
                        f"metadata no es la declarada: {'; '.join(diferencias)}. Se corregirán "
                        "permisos y propietario sin reescribir el contenido."
                    )
                else:
                    accion = ACCION_SIN_CAMBIO
                    motivo = (
                        f"{componente.destino} ya contiene exactamente la versión de la release, "
                        "con el propietario y los permisos declarados."
                    )
            plan.append(
                EntradaPlanInstalacion(
                    componente=componente.origen_en_release,
                    destino=str(componente.destino),
                    accion=accion,
                    motivo=motivo,
                    inventario=inventario,
                    respaldo_previsto=(
                        str(self.raiz_respaldos / marca / componente.destino.name)
                        if accion == ACCION_REEMPLAZAR
                        else None
                    ),
                )
            )
        return tuple(plan)

    def _marca_temporal(self) -> str:
        """Marca UTC estable usada para nombrar el directorio de respaldos."""

        return time.strftime("%Y%m%dT%H%M%SZ", self.reloj())

    # ------------------------------------------------------------------
    # Aplicación
    # ------------------------------------------------------------------

    def aplicar(self, *, confirmado: bool = False) -> ResultadoInstalacion:
        """Instala los componentes declarados, respaldando lo que reemplaza.

        Entradas:
            confirmado: debe ser ``True``. El parámetro existe para que una
                invocación distraída no escriba nada: aplicar sobre el host
                productivo requiere una decisión consciente y una compuerta
                humana previa.

        Resultado: :class:`ResultadoInstalacion` con lo instalado, lo respaldado,
        lo que sólo necesitó corrección de metadata y lo que ya estaba igual.

        Efectos laterales: crea el directorio de respaldos, copia los archivos
        de forma atómica y fija modo y propietario declarados. Sobre un destino
        cuyo contenido ya era el de la release pero cuya metadata no lo era,
        corrige permisos y propietario sin reescribir el archivo.

        Errores:
            ErrorInstaladorHost si falta confirmación, si algún destino es un
            enlace simbólico —en cuyo caso no se escribe ninguno— o si una
            escritura falla.

        No hay rollback automático de una instalación parcial, y es deliberado:
        cada archivo se escribe con ``os.replace`` después de respaldar el
        anterior, así que restaurar es copiar de vuelta un archivo concreto del
        directorio de respaldos, una operación que una persona puede verificar.
        Un rollback automático agregaría un mecanismo nuevo que también podría
        fallar, sobre un host que en ese momento estaría en servicio.
        """

        if not confirmado:
            raise ErrorInstaladorHost(
                "Aplicar requiere confirmación explícita. Ejecutá primero el plan y revisalo."
            )
        plan = self.planificar()
        marca = self._marca_temporal()
        directorio_respaldos = self.raiz_respaldos / marca
        instalados: list[str] = []
        respaldados: list[str] = []
        sin_cambio: list[str] = []
        metadata_ajustada: list[str] = []

        # Compuerta previa: se rechazan **todos** los destinos inválidos antes de
        # escribir el primero. Descubrir un enlace simbólico a mitad de la
        # aplicación dejaría el host con la mitad de los wrappers reemplazados.
        for entrada in plan:
            if entrada.inventario.es_enlace:
                raise ErrorInstaladorHost(
                    f"El destino {entrada.destino} es un enlace simbólico; no se escribe a "
                    "través de enlaces y no se modificó nada."
                )

        for componente, entrada in zip(self.componentes(), plan, strict=True):
            if entrada.accion == ACCION_SIN_CAMBIO:
                sin_cambio.append(str(componente.destino))
                continue
            if entrada.accion == ACCION_AJUSTAR_METADATA:
                # No se respalda: el contenido ya es el de la release, así que la
                # copia de seguridad sería idéntica al archivo que va a quedar.
                self._aplicar_metadata(componente)
                metadata_ajustada.append(str(componente.destino))
                continue
            if entrada.accion == ACCION_REEMPLAZAR:
                directorio_respaldos.mkdir(parents=True, exist_ok=True)
                respaldo = directorio_respaldos / componente.destino.name
                respaldo.write_bytes(componente.destino.read_bytes())
                respaldados.append(str(respaldo))
            self._instalar_atomico(self._origen(componente), componente)
            instalados.append(str(componente.destino))

        return ResultadoInstalacion(
            directorio_respaldos=str(directorio_respaldos) if respaldados else None,
            instalados=tuple(instalados),
            respaldados=tuple(respaldados),
            sin_cambio=tuple(sin_cambio),
            metadata_ajustada=tuple(metadata_ajustada),
        )

    def _aplicar_metadata(self, componente: ComponenteInstalable) -> None:
        """Fija modo y propietario declarados sobre un destino que ya existe.

        Se usa tanto al terminar una instalación como para corregir un archivo
        cuyo contenido ya era correcto. El ``chown`` pasa por el ejecutor
        auditable con ``--no-dereference`` para que nunca pueda aplicar
        privilegios a través de un enlace.
        """

        destino = componente.destino
        try:
            os.chmod(destino, componente.modo)
        except OSError as error:
            raise ErrorInstaladorHost(
                f"No se pudieron fijar los permisos de {destino}: {error}"
            ) from error
        self.ejecutor.ejecutar(
            [
                "chown",
                "--no-dereference",
                f"{componente.usuario}:{componente.grupo}",
                str(destino),
            ]
        )

    def _instalar_atomico(self, origen: Path, componente: ComponenteInstalable) -> None:
        """Escribe el destino mediante temporal en el mismo directorio y ``os.replace``.

        El temporal vive junto al destino a propósito: ``os.replace`` sólo es
        atómico dentro del mismo sistema de archivos. Así nadie puede llegar a
        ejecutar un wrapper a medio escribir.
        """

        destino = componente.destino
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporal = destino.with_name(f".{destino.name}.nuevo-{os.getpid()}")
        temporal.unlink(missing_ok=True)
        try:
            temporal.write_bytes(origen.read_bytes())
            os.chmod(temporal, componente.modo)
            os.replace(temporal, destino)
        except OSError as error:
            raise ErrorInstaladorHost(f"No se pudo instalar {destino}: {error}") from error
        finally:
            temporal.unlink(missing_ok=True)
        # Se vuelve a fijar la metadata sobre el destino final y no sólo sobre el
        # temporal: así queda un único camino que deja modo y propietario
        # exactos, compartido con la corrección de metadata.
        self._aplicar_metadata(componente)


def plan_como_json(plan: Sequence[EntradaPlanInstalacion]) -> list[dict[str, object]]:
    """Serializa el plan para mostrarlo por la CLI o archivarlo como evidencia."""

    return [asdict(entrada) for entrada in plan]


def crear_parser() -> argparse.ArgumentParser:
    """CLI con ``plan`` como modo predeterminado y ``aplicar`` bajo confirmación."""

    parser = argparse.ArgumentParser(
        description=(
            "Inventaría e instala los componentes versionados del host de SIS-Leg. "
            "No conmuta, no actualiza y no toca lanzadores del escritorio."
        )
    )
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--usuario-operador", default=USUARIO_OPERADOR_PREDETERMINADO)
    parser.add_argument("--home-operador", type=Path, default=HOME_OPERADOR_PREDETERMINADO)
    parser.add_argument("--raiz-respaldos", type=Path, default=None)
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("plan", help="Inventaría el host y muestra qué cambiaría. No escribe nada.")
    aplicar = sub.add_parser("aplicar", help="Instala los componentes declarados.")
    aplicar.add_argument(
        "--confirmar",
        action="store_true",
        help="Obligatorio para escribir. Sin esta bandera no se modifica nada.",
    )
    return parser


def main(argumentos: Sequence[str] | None = None) -> int:
    """Ejecuta plan o aplicación y traduce cualquier falla a exit code 1."""

    opciones = crear_parser().parse_args(argumentos)
    instalador = InstaladorHost(
        opciones.release,
        raiz_respaldos=opciones.raiz_respaldos,
        usuario_operador=opciones.usuario_operador,
        home_operador=opciones.home_operador,
    )
    try:
        if opciones.comando == "plan":
            salida: object = plan_como_json(instalador.planificar())
        else:
            salida = asdict(instalador.aplicar(confirmado=opciones.confirmar))
    except (ErrorInstaladorHost, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(salida, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
