"""Materializa la configuración operativa local desde las plantillas versionadas (WP-073).

¿Por qué existe este script?
----------------------------

SIS-Leg distingue dos cosas que antes vivían en el mismo archivo:

- la **plantilla versionada** (`config/system.example.toml`, por ejemplo), que
  es contenido de referencia revisable en cada Pull Request;
- el **archivo operativo local** (`config/system.toml`), que es el estado real
  de *esta* instalación y cambia con cada prueba humana, cada remapeo de
  hardware o cada ajuste de volumen.

Los archivos operativos están ignorados por Git (ver `.gitignore`). Eso evita
que una prueba humana ensucie el checkout coordinador y bloquee
`scripts/iniciar_wp_orca.py`, pero deja un hueco: un clon nuevo no tendría
ninguno de esos cuatro archivos. Este script cierra ese hueco copiando cada
plantilla a su ruta operativa **sólo cuando la ruta operativa no existe**.

Reglas de contrato (WP-073)
---------------------------

1. si el archivo operativo no existe, se copia desde su plantilla;
2. si ya existe, se deja **byte a byte intacto**; nunca se sobrescribe;
3. los directorios que falten se crean;
4. la salida informa qué se creó y qué se preservó;
5. repetir la ejecución es idempotente: la segunda vez no crea nada;
6. no usa credenciales ni datos externos;
7. ante un fallo real de E/S termina con código distinto de cero;
8. no depende de banderas del índice de Git como ``skip-worktree``.

La regla 2 es la más importante de todas: `config/apoyo-tecnico/mensajes.csv`
es la biblioteca de mensajes que el propio backend administra por REST, y
`services/device-bridge/config/devices.json` guarda el mapeo físico real de las
botoneras. Sobrescribir cualquiera de los dos destruiría trabajo operativo que
no está en ningún commit.

Recursos por directorio (WP-098)
--------------------------------

Las fotografías de banca no son un archivo sino un **conjunto**: el padrón
declara una ``ruta_imagen`` por concejal y todas resuelven bajo
``config/assets/bancas/``. Por eso existe una segunda tabla, la de directorios,
con exactamente la misma regla de oro: se copia desde la plantilla versionada
``config/assets.example/bancas/`` **cada archivo que falte**, y jamás se toca
uno que ya exista.

La diferencia con la tabla de archivos es sólo la unidad de trabajo. La
comparación se hace archivo por archivo, no directorio contra directorio: si el
operador ya reemplazó ocho fotos por las reales y faltan cuatro, se crean
únicamente esas cuatro y las ocho propias quedan intactas.

Éste es el modelo que WP-100 debe reutilizar para incorporar recursos nuevos de
configuración durante una actualización: agregar lo que falta, nunca sobrescribir
lo que la instalación ya tiene.

Uso
---

```bash
uv run python scripts/preparar_config_local.py
```

o, desde la raíz del monorepo, mediante el alias de pnpm:

```bash
pnpm preparar:config
```
"""

from __future__ import annotations

import argparse
import shutil
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

# Raíz del repositorio. Se resuelve desde la ubicación del propio script para
# que el comando funcione igual invocado desde cualquier directorio, en
# PowerShell o en una terminal POSIX.
RAIZ_REPOSITORIO = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ArchivoConfiguracionLocal:
    """Describe un archivo operativo local y la plantilla que lo origina.

    Atributos:
        plantilla: ruta relativa a la raíz del repositorio del archivo
            versionado que sirve de punto de partida.
        destino: ruta relativa a la raíz del archivo operativo ignorado por Git
            que el sistema lee realmente en tiempo de ejecución.
        descripcion: texto corto que explica en la salida para qué sirve el
            archivo, de modo que quien ejecuta el comando entienda qué acaba de
            aparecer en su checkout.

    Es ``frozen`` porque esta tabla es un contrato: ningún paso del script debe
    poder alterar un destino a mitad de la ejecución.
    """

    plantilla: Path
    destino: Path
    descripcion: str


# Tabla canónica de los cuatro archivos operativos definidos por WP-073. Las
# rutas de destino son exactamente las que ya leían el backend y el device
# bridge: este WP cambia cómo se materializan, nunca dónde viven.
ARCHIVOS_CONFIGURACION_LOCAL: tuple[ArchivoConfiguracionLocal, ...] = (
    ArchivoConfiguracionLocal(
        plantilla=Path("config/system.example.toml"),
        destino=Path("config/system.toml"),
        descripcion="configuración funcional del backend",
    ),
    ArchivoConfiguracionLocal(
        plantilla=Path("config/concejales.example.csv"),
        destino=Path("config/concejales.csv"),
        descripcion="padrón del cuerpo",
    ),
    ArchivoConfiguracionLocal(
        plantilla=Path("config/apoyo-tecnico/mensajes.example.csv"),
        destino=Path("config/apoyo-tecnico/mensajes.csv"),
        descripcion="biblioteca de mensajes precargados de Apoyo Técnico",
    ),
    ArchivoConfiguracionLocal(
        plantilla=Path("services/device-bridge/config/devices.example.json"),
        destino=Path("services/device-bridge/config/devices.json"),
        descripcion="mapeo físico del device bridge",
    ),
)


@dataclass(frozen=True)
class DirectorioConfiguracionLocal:
    """Describe un conjunto de recursos operativos y su plantilla versionada.

    Atributos:
        plantilla: directorio versionado con los archivos de referencia.
        destino: directorio operativo ignorado por Git que el sistema lee en
            ejecución.
        descripcion: texto corto para la salida del comando.

    Es la versión «muchos archivos» de :class:`ArchivoConfiguracionLocal`. Se
    modela aparte y no como una variante con bandera porque las dos operaciones
    son distintas: una copia un archivo, la otra recorre un directorio y decide
    archivo por archivo.
    """

    plantilla: Path
    destino: Path
    descripcion: str


# Tabla canónica de los recursos de configuración que son un directorio
# completo (WP-098). Hoy hay uno solo; la tabla existe igual porque es el punto
# de extensión que WP-100 debe usar para incorporar recursos nuevos.
DIRECTORIOS_CONFIGURACION_LOCAL: tuple[DirectorioConfiguracionLocal, ...] = (
    DirectorioConfiguracionLocal(
        plantilla=Path("config/assets.example/bancas"),
        destino=Path("config/assets/bancas"),
        descripcion="fotografías de banca de los concejales",
    ),
)


class ErrorPreparacionConfigLocal(RuntimeError):
    """Indica que un archivo operativo local no pudo quedar disponible.

    Se usa tanto para una plantilla ausente —el repositorio está incompleto o
    alguien renombró un archivo versionado— como para un fallo real de E/S al
    crear el directorio o copiar el contenido. En ambos casos el comando debe
    terminar con código distinto de cero: seguir adelante dejaría al backend
    arrancando contra una configuración que no existe.
    """


@dataclass(frozen=True)
class ResultadoArchivo:
    """Resultado de procesar un archivo: qué ruta es y si hubo que crearla.

    Atributos:
        archivo: entrada de la tabla canónica que se acaba de procesar.
        creado: ``True`` si el destino no existía y se copió desde la
            plantilla; ``False`` si ya existía y se preservó intacto.
    """

    archivo: ArchivoConfiguracionLocal
    creado: bool


def materializar_archivo(
    archivo: ArchivoConfiguracionLocal, raiz: Path = RAIZ_REPOSITORIO
) -> ResultadoArchivo:
    """Crea un archivo operativo local desde su plantilla si todavía no existe.

    Entradas:
        archivo: entrada de la tabla canónica a materializar.
        raiz: raíz sobre la que se resuelven ambas rutas relativas. Las pruebas
            la apuntan a un directorio temporal; en uso normal es la raíz del
            repositorio.

    Resultado:
        Un ``ResultadoArchivo`` que indica si el destino se creó o se preservó.

    Efectos laterales:
        Puede crear directorios y escribir el archivo de destino. Nunca escribe
        sobre un destino existente ni modifica la plantilla.

    Errores:
        ErrorPreparacionConfigLocal: si falta la plantilla o si crear el
            directorio o copiar el contenido falla por E/S.
    """

    ruta_destino = raiz / archivo.destino

    # La comprobación de existencia va primero y es la única condición que
    # habilita escribir. Un archivo operativo existente se preserva aunque su
    # contenido no se parezca en nada a la plantilla: justamente por eso está
    # fuera de Git.
    if ruta_destino.exists():
        return ResultadoArchivo(archivo=archivo, creado=False)

    ruta_plantilla = raiz / archivo.plantilla
    if not ruta_plantilla.is_file():
        raise ErrorPreparacionConfigLocal(
            f"Falta la plantilla versionada {archivo.plantilla}. "
            "El checkout está incompleto: no se puede crear "
            f"{archivo.destino} sin su archivo de ejemplo."
        )

    try:
        # ``parents=True`` cubre el caso de ``config/apoyo-tecnico/``, que en un
        # clon nuevo podría no existir todavía. ``exist_ok=True`` mantiene la
        # idempotencia cuando el directorio ya está creado.
        ruta_destino.parent.mkdir(parents=True, exist_ok=True)
        # ``copyfile`` copia únicamente el contenido, sin arrastrar permisos ni
        # marcas de tiempo de la plantilla: el archivo operativo nace como un
        # archivo nuevo y normal del usuario que ejecuta el comando.
        shutil.copyfile(ruta_plantilla, ruta_destino)
    except OSError as error:
        raise ErrorPreparacionConfigLocal(
            f"No se pudo crear {archivo.destino} desde {archivo.plantilla}: {error}"
        ) from error

    return ResultadoArchivo(archivo=archivo, creado=True)


def preparar_configuracion_local(
    raiz: Path = RAIZ_REPOSITORIO,
    archivos: Sequence[ArchivoConfiguracionLocal] = ARCHIVOS_CONFIGURACION_LOCAL,
) -> list[ResultadoArchivo]:
    """Materializa todos los archivos operativos locales que falten.

    Entradas:
        raiz: raíz del checkout sobre la que se resuelven las rutas.
        archivos: tabla de archivos a procesar. Se puede acotar en pruebas.

    Resultado:
        La lista de resultados en el mismo orden de la tabla, para que quien
        llame pueda informar o verificar qué ocurrió con cada archivo.

    Errores:
        ErrorPreparacionConfigLocal: se propaga en el primer archivo que falle.
            Detenerse ahí es deliberado: si el disco o los permisos están mal,
            insistir con los siguientes sólo enmascara el problema real.
    """

    return [materializar_archivo(archivo, raiz) for archivo in archivos]


@dataclass(frozen=True)
class ResultadoDirectorio:
    """Resultado de procesar un directorio: qué archivos se crearon y cuáles no.

    Atributos:
        directorio: entrada de la tabla canónica que se acaba de procesar.
        creados: nombres de los archivos que faltaban y se copiaron.
        preservados: nombres de los archivos que ya existían y no se tocaron.

    Se guardan los nombres y no sólo las cantidades porque la salida del
    comando es también una auditoría: quien la lee tiene que poder ver
    exactamente qué apareció en su checkout.
    """

    directorio: DirectorioConfiguracionLocal
    creados: tuple[str, ...]
    preservados: tuple[str, ...]


def materializar_directorio(
    directorio: DirectorioConfiguracionLocal, raiz: Path = RAIZ_REPOSITORIO
) -> ResultadoDirectorio:
    """Copia desde la plantilla únicamente los archivos que falten en el destino.

    Entradas:
        directorio: entrada de la tabla canónica de directorios.
        raiz: raíz sobre la que se resuelven ambas rutas relativas.

    Resultado:
        Un ``ResultadoDirectorio`` con los nombres creados y preservados, en
        orden alfabético para que la salida sea determinista.

    Efectos laterales:
        Crea el directorio de destino si falta y escribe los archivos ausentes.
        **Nunca** sobrescribe ni borra un archivo existente, y tampoco elimina
        del destino un archivo que la plantilla ya no tenga: si el operador
        agregó la foto de un concejal nuevo, ese archivo le pertenece.

    Errores:
        ErrorPreparacionConfigLocal: si falta el directorio plantilla o si
            crear el destino o copiar un archivo falla por E/S.

    Esta es la pieza que WP-100 necesita: «agregar lo que falta, respetar lo que
    ya está» es exactamente la semántica que debe tener una actualización frente
    a la configuración local de una instalación en producción.
    """

    ruta_plantilla = raiz / directorio.plantilla
    if not ruta_plantilla.is_dir():
        raise ErrorPreparacionConfigLocal(
            f"Falta el directorio plantilla versionado {directorio.plantilla}. "
            "El checkout está incompleto: no se pueden crear los recursos de "
            f"{directorio.destino} sin sus archivos de ejemplo."
        )

    ruta_destino = raiz / directorio.destino
    creados: list[str] = []
    preservados: list[str] = []

    try:
        ruta_destino.mkdir(parents=True, exist_ok=True)
        # ``sorted`` fija el orden del informe; ``is_file`` descarta
        # subdirectorios, que esta tabla no contempla todavía.
        for archivo_plantilla in sorted(ruta_plantilla.iterdir()):
            if not archivo_plantilla.is_file():
                continue
            destino_archivo = ruta_destino / archivo_plantilla.name
            if destino_archivo.exists():
                preservados.append(archivo_plantilla.name)
                continue
            shutil.copyfile(archivo_plantilla, destino_archivo)
            creados.append(archivo_plantilla.name)
    except OSError as error:
        raise ErrorPreparacionConfigLocal(
            f"No se pudo preparar {directorio.destino} desde {directorio.plantilla}: {error}"
        ) from error

    return ResultadoDirectorio(
        directorio=directorio,
        creados=tuple(creados),
        preservados=tuple(preservados),
    )


def preparar_directorios_configuracion_local(
    raiz: Path = RAIZ_REPOSITORIO,
    directorios: Sequence[DirectorioConfiguracionLocal] = DIRECTORIOS_CONFIGURACION_LOCAL,
) -> list[ResultadoDirectorio]:
    """Materializa los recursos faltantes de todos los directorios de la tabla.

    Se detiene en el primero que falle, por el mismo motivo que la versión de
    archivos: si el disco o los permisos están mal, seguir sólo enmascara el
    problema real.
    """

    return [materializar_directorio(directorio, raiz) for directorio in directorios]


def describir_resultados(
    resultados: Sequence[ResultadoArchivo],
    resultados_directorios: Sequence[ResultadoDirectorio] = (),
) -> str:
    """Arma el informe legible que el comando imprime al terminar.

    Entradas:
        resultados: lo devuelto por ``preparar_configuracion_local``.
        resultados_directorios: lo devuelto por
            ``preparar_directorios_configuracion_local``. Es opcional para que
            quien sólo procesa archivos no tenga que pasar una lista vacía.

    Resultado:
        Texto de varias líneas: una por archivo indicando ``creado`` o
        ``preservado``, el resumen de WP-073 y, cuando hay recursos por
        directorio, una sección propia con su propio resumen. Se separa de
        ``main`` para que las pruebas puedan verificar el mensaje sin capturar
        la salida estándar.
    """

    lineas = ["Configuración operativa local (WP-073):"]
    for resultado in resultados:
        estado = "creado desde la plantilla" if resultado.creado else "preservado sin cambios"
        lineas.append(
            f"  - {resultado.archivo.destino}: {estado} ({resultado.archivo.descripcion})"
        )

    creados = sum(1 for resultado in resultados if resultado.creado)
    preservados = len(resultados) - creados
    lineas.append(f"Resumen: {creados} creado(s), {preservados} preservado(s).")

    if resultados_directorios:
        lineas.append("Recursos de configuración por directorio (WP-098):")
        creados_directorios = 0
        preservados_directorios = 0
        for resultado in resultados_directorios:
            creados_directorios += len(resultado.creados)
            preservados_directorios += len(resultado.preservados)
            lineas.append(
                f"  - {resultado.directorio.destino}: "
                f"{len(resultado.creados)} creado(s), "
                f"{len(resultado.preservados)} preservado(s) "
                f"({resultado.directorio.descripcion})"
            )
        lineas.append(
            f"Resumen por directorio: {creados_directorios} archivo(s) creado(s), "
            f"{preservados_directorios} preservado(s)."
        )

    return "\n".join(lineas)


def crear_analizador_argumentos() -> argparse.ArgumentParser:
    """Declara la única opción del comando: sobre qué checkout trabajar."""

    analizador = argparse.ArgumentParser(
        prog="preparar_config_local",
        description=(
            "Crea los archivos y recursos de configuración operativa local que falten, "
            "copiándolos desde sus plantillas versionadas. Nunca sobrescribe uno existente."
        ),
    )
    analizador.add_argument(
        "--raiz",
        type=Path,
        default=RAIZ_REPOSITORIO,
        help=(
            "Raíz del checkout sobre la que trabajar "
            "(predeterminado: la raíz del repositorio que contiene este script)."
        ),
    )
    return analizador


def main(argumentos: Sequence[str] | None = None) -> int:
    """Punto de entrada del comando.

    Resultado:
        ``0`` si los cuatro archivos y los recursos por directorio quedaron
        disponibles; ``1`` si algún fallo real de E/S o una plantilla ausente
        impidió dejarlos listos.
    """

    opciones = crear_analizador_argumentos().parse_args(argumentos)

    try:
        resultados = preparar_configuracion_local(opciones.raiz)
        resultados_directorios = preparar_directorios_configuracion_local(opciones.raiz)
    except ErrorPreparacionConfigLocal as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(describir_resultados(resultados, resultados_directorios))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
