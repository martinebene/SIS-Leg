"""Lectura y escritura durable de la biblioteca de mensajes técnicos (WP-055).

Este archivo es el único del proyecto que el backend **escribe** dentro de
``config``. Por eso concentra dos responsabilidades simétricas:

1. ``cargar_mensajes_tecnicos``: valida el CSV con el mismo rigor que el padrón
   (encabezado exacto, columnas exactas, campos obligatorios, identificadores
   únicos, destino dentro del enum). Un archivo que no existe **no** es un
   error: representa una biblioteca vacía.
2. ``guardar_mensajes_tecnicos``: reemplaza el archivo de forma atómica
   siguiendo exactamente el patrón que ya usa el device-bridge para
   ``devices.json``: escribir un temporal en el mismo directorio, ``flush``,
   ``fsync`` y recién entonces ``os.replace``.

¿Por qué escritura atómica y no un ``open("w")`` directo? Porque ``open("w")``
trunca el archivo real antes de escribir: si el proceso muere (o el disco se
llena) en el medio, la biblioteca queda a medias y no hay forma de saber qué
se perdió. Con ``os.replace`` el archivo destino pasa del contenido viejo
completo al contenido nuevo completo en una sola operación del sistema de
archivos, y un fallo intermedio solo deja un temporal huérfano que este módulo
intenta retirar.

Formato canónico del archivo::

    id,texto,destino
    3f2b...,Volvemos en cinco minutos,RECINTO

Se escribe en UTF-8 sin BOM, igual que ``config/concejales.csv``, y se lee con
``utf-8-sig`` para tolerar el BOM que agregan algunos editores de Windows.
El BOM obligatorio de DT-020 corresponde a los CSV de auditoría, que son otro
contrato distinto y no se ven afectados por este archivo.
"""

from __future__ import annotations

import csv
import io
import logging
import os
import re
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path

from sis_leg_backend.configuracion.errores import ErrorMensajesTecnicosInvalido
from sis_leg_backend.dominio.apoyo_tecnico import DestinoAvisoTecnico, MensajeTecnico

REGISTRO = logging.getLogger(__name__)

# Encabezado canónico exacto del archivo. Igual que en el padrón, la
# comparación es literal: un encabezado renombrado, reordenado o con columnas
# extra rechaza el archivo en lugar de adivinar la intención.
ENCABEZADO_CANONICO: tuple[str, ...] = ("id", "texto", "destino")
CANTIDAD_COLUMNAS = len(ENCABEZADO_CANONICO)

INDICE_ID = 0
INDICE_TEXTO = 1
INDICE_DESTINO = 2

# Los identificadores se restringen a un alfabeto seguro y estable. Los que
# genera el backend son UUID4, que entran holgadamente en este patrón; el
# límite existe para que un archivo editado a mano no introduzca separadores,
# espacios ni caracteres de control en una clave que después viaja por URL.
PATRON_IDENTIFICADOR = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# Longitud máxima del texto de un mensaje. Es un aviso para mostrar en
# pantalla, no un documento: acotarlo evita que un archivo corrupto de varios
# megabytes se cargue entero en memoria y termine en un payload SSE.
LARGO_MAXIMO_TEXTO = 500


def cargar_mensajes_tecnicos(ruta: Path) -> tuple[MensajeTecnico, ...]:
    """Lee y valida el CSV de mensajes precargados.

    Entradas:
        ruta: ubicación del archivo CSV de la biblioteca.

    Resultado:
        Tupla inmutable con los mensajes en el orden del archivo. Un archivo
        inexistente devuelve una tupla vacía, porque una instalación que
        todavía no cargó mensajes es un caso normal y no un error.

    Errores:
        ``ErrorMensajesTecnicosInvalido`` ante cualquier incumplimiento del
        contrato, con el número de fila para poder corregir el archivo. Los
        mensajes son deterministas: la misma entrada produce siempre el mismo
        texto de error.
    """

    if not ruta.exists():
        return ()

    try:
        contenido = ruta.read_text(encoding="utf-8-sig")
    except OSError as error:
        raise ErrorMensajesTecnicosInvalido(
            f"no se pudo leer el archivo de mensajes técnicos {ruta}: {error}"
        ) from error
    except UnicodeDecodeError as error:
        raise ErrorMensajesTecnicosInvalido(
            f"el archivo de mensajes técnicos {ruta} no está codificado en UTF-8"
        ) from error

    return interpretar_mensajes_tecnicos(contenido)


def interpretar_mensajes_tecnicos(contenido: str) -> tuple[MensajeTecnico, ...]:
    """Valida el contenido textual ya leído del CSV.

    Se separa de la lectura de disco para que las pruebas puedan ejercitar
    todas las variantes inválidas sin fabricar archivos, y para que el
    guardado pueda reutilizar exactamente las mismas reglas de validación
    antes de persistir.
    """

    # ``csv.reader`` sobre un ``StringIO`` respeta comillas y comas dentro de
    # los campos; ``splitlines()`` rompería un texto entrecomillado con salto
    # de línea en dos filas falsas en lugar de rechazarlo con un mensaje claro.
    filas = list(csv.reader(io.StringIO(contenido, newline="")))
    if not filas:
        raise ErrorMensajesTecnicosInvalido("el archivo de mensajes técnicos está vacío")

    encabezado = tuple(filas[0])
    if encabezado != ENCABEZADO_CANONICO:
        recibido = ",".join(encabezado)
        esperado = ",".join(ENCABEZADO_CANONICO)
        raise ErrorMensajesTecnicosInvalido(
            f"el encabezado de mensajes técnicos debe ser exactamente "
            f"'{esperado}' y se recibió '{recibido}'"
        )

    mensajes: list[MensajeTecnico] = []
    identificadores_vistos: set[str] = set()

    # ``start=2`` porque la fila 1 es el encabezado: así el número del mensaje
    # de error coincide con la línea real del archivo.
    for numero_fila, fila in enumerate(filas[1:], start=2):
        if not fila:
            # Línea en blanco: formato aceptable de CSV, se ignora.
            continue
        if len(fila) != CANTIDAD_COLUMNAS:
            raise ErrorMensajesTecnicosInvalido(
                f"la fila {numero_fila} debe tener exactamente "
                f"{CANTIDAD_COLUMNAS} columnas y tiene {len(fila)}"
            )

        identificador = fila[INDICE_ID].strip()
        if not PATRON_IDENTIFICADOR.match(identificador):
            raise ErrorMensajesTecnicosInvalido(
                f"la fila {numero_fila}: el id debe tener entre 1 y 64 caracteres "
                f"alfanuméricos, '-' o '_'"
            )
        if identificador in identificadores_vistos:
            raise ErrorMensajesTecnicosInvalido(
                f"la fila {numero_fila}: id duplicado: {identificador}"
            )
        identificadores_vistos.add(identificador)

        texto = fila[INDICE_TEXTO].strip()
        if not texto:
            raise ErrorMensajesTecnicosInvalido(
                f"la fila {numero_fila}: el texto no puede estar vacío"
            )
        if len(texto) > LARGO_MAXIMO_TEXTO:
            raise ErrorMensajesTecnicosInvalido(
                f"la fila {numero_fila}: el texto no puede superar {LARGO_MAXIMO_TEXTO} caracteres"
            )
        if any(caracter in texto for caracter in "\r\n"):
            raise ErrorMensajesTecnicosInvalido(
                f"la fila {numero_fila}: el texto no puede contener saltos de línea"
            )

        destino_bruto = fila[INDICE_DESTINO].strip()
        try:
            destino = DestinoAvisoTecnico(destino_bruto)
        except ValueError as error:
            permitidos = "/".join(destino.value for destino in DestinoAvisoTecnico)
            raise ErrorMensajesTecnicosInvalido(
                f"la fila {numero_fila}: el destino debe ser uno de {permitidos} "
                f"y se recibió '{destino_bruto}'"
            ) from error

        mensajes.append(MensajeTecnico(mensaje_id=identificador, texto=texto, destino=destino))

    return tuple(mensajes)


def serializar_mensajes_tecnicos(mensajes: Iterable[MensajeTecnico]) -> str:
    """Convierte la biblioteca en el texto exacto que se persistirá.

    Se usa ``\\n`` como fin de línea en todas las plataformas para que el
    archivo sea idéntico en Windows y Linux y no genere diferencias espurias
    al compararlo o versionarlo.
    """

    buffer = io.StringIO(newline="")
    escritor = csv.writer(buffer, lineterminator="\n")
    escritor.writerow(ENCABEZADO_CANONICO)
    for mensaje in mensajes:
        escritor.writerow((mensaje.mensaje_id, mensaje.texto, mensaje.destino.value))
    return buffer.getvalue()


def guardar_mensajes_tecnicos(ruta: Path, mensajes: Sequence[MensajeTecnico]) -> None:
    """Reemplaza el CSV completo de forma atómica y durable.

    Pasos, en este orden exacto:

    1. se serializa la biblioteca completa en memoria y se vuelve a validar,
       de modo que un defecto de programación nunca escriba un archivo que el
       propio backend no podría releer;
    2. se crea el directorio destino si falta (una instalación nueva todavía
       no lo tiene);
    3. se escribe un archivo temporal **en el mismo directorio** —requisito
       para que ``os.replace`` sea atómico, porque cruzar sistemas de archivos
       lo degrada a copiar y borrar—;
    4. ``flush`` + ``fsync`` bajan los bytes al disco;
    5. ``os.replace`` instala el archivo nuevo en un único paso indivisible.

    Errores:
        ``ErrorPersistenciaMensajesTecnicos`` si cualquier paso de E/S falla.
        En ese caso el archivo anterior permanece intacto y el llamador no
        debe actualizar la biblioteca en memoria.
    """

    # Import local: el error pertenece al dominio y el dominio no debe
    # depender de este módulo de infraestructura. Importarlo acá evita un
    # ciclo entre ``configuracion`` y ``dominio``.
    from sis_leg_backend.dominio.apoyo_tecnico import ErrorPersistenciaMensajesTecnicos

    contenido = serializar_mensajes_tecnicos(mensajes)
    # Releer lo serializado es barato y convierte en imposible persistir una
    # biblioteca que después se rechazaría al reiniciar el backend.
    interpretar_mensajes_tecnicos(contenido)

    ruta_temporal: Path | None = None
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            prefix=f".{ruta.name}.",
            suffix=".tmp",
            dir=ruta.parent,
            delete=False,
        ) as archivo:
            ruta_temporal = Path(archivo.name)
            archivo.write(contenido)
            archivo.flush()
            os.fsync(archivo.fileno())
        os.replace(ruta_temporal, ruta)
        ruta_temporal = None
    except OSError as error:
        raise ErrorPersistenciaMensajesTecnicos(
            f"no se pudo persistir la biblioteca de mensajes técnicos: {error}"
        ) from error
    finally:
        if ruta_temporal is not None:
            try:
                ruta_temporal.unlink(missing_ok=True)
            except OSError:
                REGISTRO.warning("No se pudo retirar el temporal fallido %s", ruta_temporal)
