"""Fuente única de las fotografías de banca bajo ``config/`` (WP-098).

¿Qué problema resuelve este módulo?
-----------------------------------

Hasta WP-097 cada aplicación web guardaba su **propia copia** de las doce
fotografías en ``apps/<aplicacion>/public/assets/bancas/``. Eso obligaba a
reconstruir el frontend para cambiar una foto y permitía que las superficies
mostraran versiones distintas de la misma persona.

WP-098 deja una sola ubicación física en tiempo de ejecución:

```text
config/assets/bancas/<archivo>
```

Ese directorio es **configuración local de la instalación**, igual que
``config/concejales.csv``: no se versiona, no viaja dentro de una release y lo
administra quien opera el sistema. El backend lo publica por HTTP y las dos
superficies que dibujan bancas piden la imagen a esa única ruta. Reemplazar el
archivo en disco cambia lo que ven todas las pantallas sin reconstruir nada,
porque el archivo se lee en cada pedido.

El contrato de la ruta
----------------------

``ruta_imagen`` del padrón sigue siendo exactamente el mismo texto de antes,
por ejemplo ``assets/bancas/banca-01.png``. Lo que cambia es contra qué se
resuelve: antes contra la raíz pública de cada SPA, ahora contra ``config/``.

La ruta se valida de forma **estricta**, con el mismo criterio que WP-065 aplicó
a ``[sonidos]``:

- debe empezar por ``assets/bancas/``;
- después de ese prefijo debe quedar un **único nombre de archivo**, sin barras
  ni subdirectorios;
- la extensión debe pertenecer a la lista de formatos admitidos;
- se rechazan URLs (``http://``, ``//servidor``, ``data:``), rutas absolutas,
  barras invertidas de Windows, segmentos ``.``/``..`` y nombres ocultos.

La razón de ser tan estricto es concreta: este texto viene de un archivo CSV que
edita una persona y termina convertido en una ruta del sistema de archivos del
servidor. Sin estas reglas, un ``assets/bancas/../../../etc/passwd`` publicaría
por HTTP cualquier archivo legible por el backend.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

# Prefijo obligatorio de toda ``ruta_imagen`` del padrón. Se conserva el texto
# histórico para que los padrones ya escritos sigan siendo válidos: lo que
# cambió con WP-098 es la raíz contra la que se resuelve, no el valor del CSV.
PREFIJO_RUTA_IMAGEN = "assets/bancas/"

# Directorio runtime donde viven realmente las fotografías. Es relativo, igual
# que ``config/system.toml`` y ``config/concejales.csv``: se resuelve contra el
# directorio de trabajo del proceso, que en producción es ``/opt/sis-leg`` por
# la unidad systemd y en desarrollo es la raíz del repositorio.
DIRECTORIO_IMAGENES_CONCEJALES = Path("config/assets/bancas")

# Directorio versionado que sirve de plantilla reproducible. No lo lee el
# backend: lo copia ``scripts/preparar_config_local.py`` a la ruta runtime
# cuando falta un archivo. Se declara acá para que exista un único lugar donde
# la pareja plantilla/destino esté escrita.
DIRECTORIO_IMAGENES_CONCEJALES_EJEMPLO = Path("config/assets.example/bancas")

# Formatos admitidos y su tipo de contenido HTTP. La tabla es cerrada a
# propósito: el backend devuelve el archivo tal cual, así que sólo puede
# prometer un ``Content-Type`` de los formatos que realmente conoce. PNG es el
# formato de las fotografías institucionales existentes; JPEG y WebP se admiten
# porque una instalación puede exportar sus fotos desde otra herramienta.
TIPOS_CONTENIDO_IMAGEN: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


class ErrorRutaImagenInvalida(ValueError):
    """La ``ruta_imagen`` declarada no cumple el contrato seguro de WP-098.

    Hereda de ``ValueError`` porque describe un dato de entrada mal formado y
    no una falla técnica. Quien la captura decide cómo comunicarla: la carga del
    padrón la convierte en ``ErrorPadronInvalido`` con número de fila, y el
    endpoint HTTP la convierte en un 404 que no revela nada del disco.
    """


def validar_ruta_imagen_concejal(ruta_imagen: str) -> str:
    """Comprueba el contrato de ``ruta_imagen`` y devuelve el nombre de archivo.

    Entradas:
        ruta_imagen: valor literal declarado en la columna ``ruta_imagen`` del
            padrón, por ejemplo ``assets/bancas/banca-01.png``.

    Resultado:
        El nombre de archivo sin el prefijo, por ejemplo ``banca-01.png``. Es lo
        único que hace falta para ubicar el archivo dentro del directorio
        runtime y también lo único que viaja en la URL pública.

    Errores:
        ``ErrorRutaImagenInvalida`` con un mensaje que explica qué regla se
        incumplió. El mensaje nombra la regla, nunca una ruta del servidor.

    El orden de las comprobaciones es deliberado: primero se descartan las
    formas que ni siquiera son rutas internas (URLs y rutas absolutas), después
    se exige el prefijo y recién al final se mira el nombre del archivo.
    """

    if not ruta_imagen:
        raise ErrorRutaImagenInvalida("la ruta de imagen no puede estar vacía")

    # Una barra invertida nunca es un separador válido acá: el contrato es
    # POSIX y ``config/assets/bancas`` se escribe igual en Windows y en Linux.
    # Aceptarla permitiría colar ``assets/bancas/..\\..\\secreto`` en sistemas
    # que la traducen a separador.
    if "\\" in ruta_imagen:
        raise ErrorRutaImagenInvalida(
            f"la ruta de imagen no puede contener barras invertidas; se recibió '{ruta_imagen}'"
        )

    # ``://`` cubre http, https, ftp y cualquier otro esquema; ``//`` inicial
    # cubre las URL de protocolo relativo. ``data:`` se rechaza aparte porque no
    # lleva ``//`` y de todos modos no es un archivo de configuración.
    if "://" in ruta_imagen or ruta_imagen.startswith("//") or ruta_imagen.startswith("data:"):
        raise ErrorRutaImagenInvalida(
            "la ruta de imagen debe ser interna del sistema y no una URL externa; "
            f"se recibió '{ruta_imagen}'"
        )

    if ruta_imagen.startswith("/"):
        raise ErrorRutaImagenInvalida(
            "la ruta de imagen debe ser relativa a la configuración y no absoluta; "
            f"se recibió '{ruta_imagen}'"
        )

    if not ruta_imagen.startswith(PREFIJO_RUTA_IMAGEN):
        raise ErrorRutaImagenInvalida(
            f"la ruta de imagen debe empezar por '{PREFIJO_RUTA_IMAGEN}'; "
            f"se recibió '{ruta_imagen}'"
        )

    nombre_archivo = ruta_imagen[len(PREFIJO_RUTA_IMAGEN) :]
    return _validar_nombre_archivo_imagen(nombre_archivo, ruta_imagen)


def _validar_nombre_archivo_imagen(nombre_archivo: str, ruta_original: str) -> str:
    """Valida la porción de ``ruta_imagen`` que queda después del prefijo.

    Se separa de la función anterior porque el endpoint HTTP recibe solamente el
    nombre del archivo —el prefijo ya está en la propia ruta del endpoint— y
    debe aplicar exactamente las mismas reglas. Tener una sola implementación
    evita que la validación del CSV y la de la URL puedan divergir.
    """

    if not nombre_archivo:
        raise ErrorRutaImagenInvalida(
            f"la ruta de imagen '{ruta_original}' no nombra ningún archivo"
        )

    # Un único segmento: ni subdirectorios ni ``..`` pueden aparecer, así que
    # después de esta comprobación ya no hay forma de escapar del directorio.
    if "/" in nombre_archivo:
        raise ErrorRutaImagenInvalida(
            "la ruta de imagen debe nombrar un archivo directamente bajo "
            f"'{PREFIJO_RUTA_IMAGEN}', sin subdirectorios; se recibió '{ruta_original}'"
        )

    if nombre_archivo in {".", ".."} or nombre_archivo.startswith("."):
        raise ErrorRutaImagenInvalida(
            "la ruta de imagen no puede nombrar un archivo oculto ni un directorio relativo; "
            f"se recibió '{ruta_original}'"
        )

    # Los bytes de control y el NUL no aparecen en un nombre de archivo legítimo
    # y sí en intentos de truncar rutas a nivel del sistema operativo.
    if any(caracter < " " or caracter == "\x7f" for caracter in nombre_archivo):
        raise ErrorRutaImagenInvalida(
            "la ruta de imagen contiene caracteres de control no admitidos"
        )

    sufijo = PurePosixPath(nombre_archivo).suffix.lower()
    if sufijo not in TIPOS_CONTENIDO_IMAGEN:
        admitidas = ", ".join(sorted(TIPOS_CONTENIDO_IMAGEN))
        raise ErrorRutaImagenInvalida(
            f"la extensión de la imagen debe ser una de {admitidas}; se recibió '{ruta_original}'"
        )

    return nombre_archivo


def validar_nombre_archivo_imagen(nombre_archivo: str) -> str:
    """Valida un nombre de archivo suelto, tal como llega en la URL pública.

    Es la puerta de entrada del endpoint ``GET`` de imágenes. Aplica las mismas
    reglas que ``validar_ruta_imagen_concejal`` sobre la parte final de la ruta,
    de modo que un pedido HTTP no pueda pedir nada que un padrón válido no
    pudiera declarar.
    """

    return _validar_nombre_archivo_imagen(nombre_archivo, f"{PREFIJO_RUTA_IMAGEN}{nombre_archivo}")


def tipo_contenido_imagen(nombre_archivo: str) -> str:
    """Devuelve el ``Content-Type`` que corresponde a la extensión del archivo.

    Se asume que el nombre ya pasó por la validación: la extensión existe en la
    tabla. Se deja igualmente un valor genérico como red de seguridad para que
    un cambio futuro en la tabla no produzca un ``KeyError`` en pleno pedido.
    """

    sufijo = PurePosixPath(nombre_archivo).suffix.lower()
    return TIPOS_CONTENIDO_IMAGEN.get(sufijo, "application/octet-stream")


def resolver_archivo_imagen_concejal(
    nombre_archivo: str,
    directorio: Path = DIRECTORIO_IMAGENES_CONCEJALES,
) -> Path:
    """Ubica en disco la fotografía pedida dentro del directorio de configuración.

    Entradas:
        nombre_archivo: nombre ya validado o por validar; la función vuelve a
            validarlo porque es la última barrera antes de tocar el disco.
        directorio: raíz runtime donde viven las fotografías. Las pruebas la
            apuntan a un directorio temporal; en uso normal es
            ``config/assets/bancas``.

    Resultado:
        La ruta del archivo existente.

    Errores:
        ``ErrorRutaImagenInvalida`` si el nombre incumple el contrato, si el
        archivo no existe, si no es un archivo regular o si —pese a todo— la
        ruta resuelta quedara fuera del directorio configurado.

    La comprobación final de contención es redundante con la validación del
    nombre, y se conserva a propósito: es barata y convierte un eventual error
    de programación futuro en un error controlado en vez de en una fuga de
    archivos del servidor. Se hace sobre rutas ya resueltas, de modo que un
    enlace simbólico que apunte fuera del directorio también quede descartado.
    """

    nombre_validado = validar_nombre_archivo_imagen(nombre_archivo)
    directorio_resuelto = directorio.resolve()
    archivo = (directorio_resuelto / nombre_validado).resolve()

    if not archivo.is_relative_to(directorio_resuelto):
        raise ErrorRutaImagenInvalida(
            "la ruta de imagen resuelve fuera del directorio de configuración"
        )
    if not archivo.is_file():
        raise ErrorRutaImagenInvalida(
            f"no existe la fotografía configurada '{PREFIJO_RUTA_IMAGEN}{nombre_validado}'"
        )

    return archivo
