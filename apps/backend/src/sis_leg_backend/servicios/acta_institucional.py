"""Informe formal de acta y copia externa opcional del conjunto cerrado (WP-085).

Qué resuelve este módulo
------------------------

Al cerrar una sesión, el conjunto institucional queda en disco como tres CSV
acumulativos (L1, L2 y L3). Esos archivos son el registro auditable, pero no son
cómodos para redactar el acta: llevan ``seq``, ``level``, ``tag`` y
``event_code``, columnas técnicas que quien escribe el acta no necesita ni debe
copiar.

WP-085 agrega dos cosas, ambas **posteriores** al cierre durable:

1. un **informe de acta** en texto plano (``...-ACTA.txt``), derivado del archivo
   L3 ya cerrado, con una línea por evento y sin metadatos técnicos;
2. una **copia externa opcional** del conjunto completo (los tres CSV más el
   TXT) hacia un directorio de sistema de archivos ya montado, cuando la
   instalación lo configuró en ``paths.logs_copy_dir``.

Quitar las columnas técnicas no alcanza
---------------------------------------

Las columnas ``seq``, ``level``, ``tag`` y ``event_code`` no son el único lugar
donde vive lo técnico: el propio ``message`` durable transporta identificadores
internos, huellas de dispositivo, banderas booleanas y posiciones de cola,
porque está redactado para reconstruir un hecho, no para leerse en un acta.

Por eso el texto de cada línea **no** se copia del CSV: lo redacta el catálogo
explícito de :mod:`sis_leg_backend.servicios.politica_acta`, que declara familia
por familia qué información institucional se publica y qué metadata se descarta.

Integridad estructural: fallo cerrado
-------------------------------------

Un informe formal no puede parecer completo si su fuente no lo está. La lectura
del L3 valida el encabezado canónico, la forma de cada fila, el timestamp y que
la familia ``(tag, event_code)`` tenga política declarada. Cualquier desvío
aborta **todo** el acta con ``ErrorActaNoDerivable``: no se repara la fila, no se
descarta y no se sigue de largo.

Cuando eso ocurre los CSV quedan intactos, el cierre institucional sigue
consumado, la copia externa no se intenta y la API informa ``acta_generada`` en
``false`` para que Moderación avise que la sesión sí cerró pero el informe no se
pudo derivar.

La regla que ordena todo el módulo
----------------------------------

Los CSV son la autoridad institucional. El TXT es una derivación de conveniencia
y la copia externa es redundancia. Por eso **ninguna** función pública de este
módulo levanta excepciones: se ejecutan después de que ``SESION_CERRADA`` quedó
persistido con ``fsync`` y los archivos quedaron cerrados, así que un fallo acá
no puede convertirse en un error de cierre. Si lo hiciera, Moderación mostraría
un cierre fallido sobre una sesión que en realidad ya cerró y el operador
intentaría cerrarla otra vez.

Lo que sí se hace con un fallo es informarlo por dos vías: el registro técnico
del proceso (``logging``) para diagnóstico, y un resultado tipado que la API
devuelve para que Moderación muestre un aviso efímero. No se audita en los CSV
porque ya están cerrados: agregar una fila después del cierre rompería el
contrato de conjunto irreversible de WP-004.

Por qué se lee el archivo y no el buffer en memoria
---------------------------------------------------

``EscritorAuditoriaCsv`` mantiene un ``deque`` de los últimos 200 eventos
confirmados. Ese buffer existe para la proyección de Moderación y **descarta**
los eventos más antiguos: una sesión larga tiene muchos más de 200 eventos L3.
El acta debe contenerlos todos, así que la única fuente correcta es el archivo
L3 físico ya cerrado.
"""

from __future__ import annotations

import csv
import logging
import re
import shutil
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from sis_leg_backend.auditoria import (
    ENCABEZADO_CSV,
    FORMATO_NOMBRE,
    FORMATO_TIMESTAMP,
    NivelAuditoria,
)
from sis_leg_backend.servicios.politica_acta import (
    ErrorActaNoDerivable,
    redactar_linea_de_acta,
)

REGISTRO = logging.getLogger(__name__)

SUFIJO_ACTA = "-ACTA.txt"
"""Sufijo estable del informe de acta, análogo a ``-L1.csv``/``-L2.csv``/``-L3.csv``.

El prefijo temporal es exactamente el mismo del conjunto, de modo que los cuatro
archivos de una sesión se ordenen juntos en cualquier explorador de archivos.
"""

TITULO_ACTA = "SIS-Leg"
SUBTITULO_ACTA = "Registro de eventos para acta institucional"
PREFIJO_FECHA_ACTA = "Fecha: "
"""Las tres líneas fijas del encabezado aprobado por HUMAN_GATE.

``SIS-Leg`` es el nombre del sistema, no el de la institución: el acta la redacta
el cuerpo legislativo y no necesita que el informe repita su denominación.
"""

FORMATO_FECHA_ACTA = "%d/%m/%Y"
"""Fecha civil del encabezado, en el formato local del cuerpo legislativo."""

SEPARADOR_LINEA_ACTA = " — "
"""Raya (U+2014) entre la hora y el texto del evento, con espacios a ambos lados."""

# Rangos Unicode de emojis y pictogramas. Un evento L3 puede transportar texto
# escrito por el operador (por ejemplo el cuerpo de un aviso técnico), así que el
# informe institucional no puede asumir que sólo llegan letras: si alguien
# escribió un emoji, el CSV lo conserva como evidencia y el acta lo omite, porque
# un acta institucional se redacta en texto llano.
_EMOJIS = re.compile(
    "["
    "\U0001f000-\U0001faff"  # emoticones, pictogramas, transporte, simbolos suplementarios
    "\u2600-\u27bf"  # simbolos misceláneos y dingbats
    "\u2b00-\u2bff"  # flechas y formas decorativas
    "\ufe0f"  # selector de variación que fuerza presentación emoji
    "\u20e3"  # combinador de teclado (1 + U+20E3)
    "]"
)

_ESPACIOS_REPETIDOS = re.compile(r" {2,}")


class EstadoCopiaExterna(StrEnum):
    """Desenlace del intento de copia externa del conjunto cerrado.

    Los tres valores son mutuamente excluyentes y describen exactamente lo que
    Moderación debe mostrar:

    - ``OMITIDA``: ``paths.logs_copy_dir`` no está configurado. No hubo intento,
      no hubo acceso externo y no corresponde ningún aviso;
    - ``EXITOSA``: los cuatro archivos quedaron replicados en el destino;
    - ``FALLIDA``: el destino estaba configurado pero la copia no pudo
      completarse. Los archivos locales siguen intactos y el cierre sigue siendo
      válido.
    """

    OMITIDA = "OMITIDA"
    EXITOSA = "EXITOSA"
    FALLIDA = "FALLIDA"


@dataclass(frozen=True, slots=True)
class ResultadoCierreInstitucional:
    """Qué ocurrió con el informe de acta y con la copia externa.

    Es un dato puramente informativo que viaja como respuesta de
    ``DELETE /api/v1/sesion``. Que ``acta_generada`` sea ``False`` o que
    ``copia_externa`` sea ``FALLIDA`` **no** significa que la sesión no haya
    cerrado: el cierre ya era durable antes de construir este objeto.

    Atributos:
        acta_generada: ``True`` si el TXT quedó escrito en disco.
        ruta_acta: ubicación del TXT cuando se generó; ``None`` si falló.
        copia_externa: desenlace del intento de copia.
    """

    acta_generada: bool
    ruta_acta: Path | None
    copia_externa: EstadoCopiaExterna


def generar_acta_y_copiar_conjunto(
    rutas: Mapping[NivelAuditoria, Path],
    directorio_copia: str | None,
) -> ResultadoCierreInstitucional:
    """Deriva el informe de acta y, si corresponde, replica el conjunto cerrado.

    Entradas:
        rutas: las tres rutas del conjunto ya cerrado, tal como las publica
            ``EscritorAuditoriaCsv.rutas``. Los archivos deben estar cerrados:
            este módulo los lee, nunca los escribe ni los reabre para agregar.
        directorio_copia: valor de ``paths.logs_copy_dir``. ``None`` significa
            que la instalación no pidió copia externa.

    Resultado:
        Un ``ResultadoCierreInstitucional`` que describe ambos pasos.

    Efectos laterales:
        Crea el TXT junto a los CSV y, cuando hay destino configurado, crea la
        carpeta de fecha en el destino y copia allí los cuatro archivos. Nunca
        mueve, borra ni modifica los archivos locales.

    Errores:
        Ninguno. La función **no propaga excepciones**: cualquier fallo se
        registra en el log técnico y se refleja en el resultado. Ver el
        docstring del módulo para el motivo institucional de esa decisión.

    Orden de los dos pasos: primero el TXT y después la copia, porque el TXT
    forma parte del conjunto que se replica. Si el TXT no se pudo generar, la
    copia no se intenta: replicar un conjunto incompleto y anunciarlo como
    exitoso sería peor que no copiar.
    """

    ruta_l3 = rutas[NivelAuditoria.L3]

    try:
        ruta_acta = _escribir_acta(ruta_l3)
    except Exception:
        # ``exception`` incluye el traceback completo en el log del servicio.
        REGISTRO.exception(
            "No se pudo generar el informe de acta a partir de %s. "
            "El cierre institucional ya es durable y los CSV quedan intactos.",
            ruta_l3,
        )
        return ResultadoCierreInstitucional(
            acta_generada=False,
            ruta_acta=None,
            copia_externa=EstadoCopiaExterna.OMITIDA,
        )

    if directorio_copia is None:
        return ResultadoCierreInstitucional(
            acta_generada=True,
            ruta_acta=ruta_acta,
            copia_externa=EstadoCopiaExterna.OMITIDA,
        )

    conjunto = (
        rutas[NivelAuditoria.L1],
        rutas[NivelAuditoria.L2],
        ruta_l3,
        ruta_acta,
    )
    try:
        _copiar_conjunto(conjunto, Path(directorio_copia) / ruta_l3.parent.name)
    except Exception:
        REGISTRO.exception(
            "No se pudo copiar el conjunto cerrado a %s. "
            "Los archivos locales siguen siendo el registro institucional válido.",
            directorio_copia,
        )
        return ResultadoCierreInstitucional(
            acta_generada=True,
            ruta_acta=ruta_acta,
            copia_externa=EstadoCopiaExterna.FALLIDA,
        )

    return ResultadoCierreInstitucional(
        acta_generada=True,
        ruta_acta=ruta_acta,
        copia_externa=EstadoCopiaExterna.EXITOSA,
    )


def componer_acta(ruta_l3: Path) -> str:
    """Construye el texto completo del informe a partir del L3 cerrado.

    Se expone por separado del guardado para que las pruebas puedan afirmar el
    contenido exacto sin depender de la escritura en disco.

    Entradas:
        ruta_l3: archivo ``...-L3.csv`` ya cerrado.

    Resultado:
        El informe completo, con salto de línea final.

    Errores:
        ErrorActaNoDerivable: si el encabezado no es el canónico, si alguna fila
            no tiene la forma canónica o si alguna familia ``(tag, event_code)``
            no tiene política de redacción. Un informe formal no puede omitir
            evidencia en silencio, así que se aborta entero.
        OSError: si el archivo no puede leerse.

    Cómo se arma, paso a paso:

    1. la fecha del encabezado sale del **nombre** del conjunto, no del reloj
       actual: el TXT se genera al cerrar, pero pertenece a la sesión que se
       inició con esa marca temporal;
    2. se lee el CSV con el mismo dialecto con que se escribió —delimitador
       ``;`` y codificación ``utf-8-sig``—, de modo que un mensaje que contenga
       ``;`` o un salto de línea se recomponga correctamente;
    3. la primera fila se compara contra ``ENCABEZADO_CSV``: si no coincide
       exactamente, el archivo no es un L3 canónico y nada de lo que siga puede
       interpretarse con confianza;
    4. **todas** las filas restantes producen exactamente una línea, en el mismo
       orden en que fueron persistidas. No se filtra por ``level`` ni se saltea
       ninguna: cada fila se valida y se redacta, o el acta falla.
    """

    lineas = [
        TITULO_ACTA,
        SUBTITULO_ACTA,
        f"{PREFIJO_FECHA_ACTA}{_fecha_del_conjunto(ruta_l3)}",
        "",
    ]

    with ruta_l3.open(encoding="utf-8-sig", newline="") as archivo:
        filas = csv.reader(archivo, delimiter=";")
        _verificar_encabezado(next(filas, None), ruta_l3)
        # ``start=2`` porque la fila 1 del archivo es el encabezado ya consumido.
        # El número se usa sólo para que un fallo indique dónde mirar en el CSV.
        for numero_fila, fila in enumerate(filas, start=2):
            lineas.append(_formatear_evento(fila, numero_fila, ruta_l3))

    return "\n".join(lineas) + "\n"


def _verificar_encabezado(fila: Sequence[str] | None, ruta_l3: Path) -> None:
    """Exige la primera fila canónica ``seq;timestamp;level;tag;event_code;message``.

    Un encabezado distinto significa que el archivo no fue escrito por el
    escritor de auditoría vigente, o que fue editado. En cualquiera de los dos
    casos el resto del archivo deja de ser interpretable con garantías y el acta
    no puede derivarse.
    """

    if fila is None:
        raise ErrorActaNoDerivable(
            f"El archivo {ruta_l3.name} está vacío y no contiene el encabezado canónico"
        )
    if tuple(fila) != ENCABEZADO_CSV:
        raise ErrorActaNoDerivable(
            f"El encabezado de {ruta_l3.name} no es el canónico "
            f"{ENCABEZADO_CSV!r}; se leyó {tuple(fila)!r}"
        )


def ruta_acta_de_conjunto(ruta_l3: Path) -> Path:
    """Traduce ``AAAA-MM-DD_HH-MM-SS-L3.csv`` a ``AAAA-MM-DD_HH-MM-SS-ACTA.txt``.

    El informe vive en la misma carpeta de fecha que los CSV y comparte su
    prefijo temporal exacto. Como el prefijo ya es único por conjunto (WP-004
    avanza la marca nominal hasta encontrar un segundo libre), el nombre del TXT
    hereda esa unicidad y no puede pisar el informe de otra sesión.
    """

    return ruta_l3.with_name(f"{_prefijo_del_conjunto(ruta_l3)}{SUFIJO_ACTA}")


def _escribir_acta(ruta_l3: Path) -> Path:
    """Guarda el informe en UTF-8 sin poder reemplazar un archivo existente.

    El modo ``x`` es la misma garantía que usa el escritor de auditoría: si el
    nombre ya existiera —lo que indicaría un conjunto histórico con el mismo
    prefijo— la escritura falla en vez de sobrescribir evidencia.

    ``newline="\\n"`` fija el fin de línea del archivo con independencia del
    sistema operativo, para que el informe se vea igual en cualquier equipo.
    """

    ruta_acta = ruta_acta_de_conjunto(ruta_l3)
    contenido = componer_acta(ruta_l3)
    with ruta_acta.open(mode="x", encoding="utf-8", newline="\n") as archivo:
        archivo.write(contenido)
    return ruta_acta


def _copiar_conjunto(origenes: Sequence[Path], directorio_destino: Path) -> None:
    """Replica los cuatro archivos en la carpeta de fecha del destino externo.

    Entradas:
        origenes: rutas locales a replicar, en el orden L1, L2, L3, ACTA.
        directorio_destino: ``<logs_copy_dir>/AAAA-MM-DD``. La carpeta de fecha
            repite exactamente la del conjunto local, de modo que el destino
            conserve la misma estructura por fecha.

    Errores:
        ``OSError`` (incluida ``FileExistsError``) si el destino no existe, no es
        escribible o alguno de los nombres ya estaba ocupado. El llamador lo
        traduce a ``EstadoCopiaExterna.FALLIDA``.

    Dos decisiones que conviene entender:

    - **nunca se sobrescribe**. Cada destino se abre en modo ``xb``: un nombre ya
      ocupado en la carpeta externa es un conjunto histórico ajeno y pisarlo
      destruiría evidencia. La colisión se trata como falla de copia;
    - **se revierte sólo lo que este intento creó**. Si el tercer archivo falla,
      los dos que ya se habían copiado se eliminan para no dejar en el destino un
      conjunto incompleto que parezca completo. Un archivo preexistente no se
      toca jamás, porque no lo creó este intento.
    """

    directorio_destino.mkdir(parents=True, exist_ok=True)

    creados: list[Path] = []
    try:
        for origen in origenes:
            destino = directorio_destino / origen.name
            with destino.open(mode="xb") as salida:
                # El destino ya existe en disco desde que ``open`` retornó, así
                # que se anota antes de copiar: si ``copyfileobj`` falla a mitad,
                # el archivo parcial también debe revertirse.
                creados.append(destino)
                with origen.open(mode="rb") as entrada:
                    shutil.copyfileobj(entrada, salida)
    except OSError:
        for creado in creados:
            # Si tampoco se puede borrar, el error original es el que importa.
            with suppress(OSError):
                creado.unlink()
        raise


def _prefijo_del_conjunto(ruta_l3: Path) -> str:
    """Extrae ``AAAA-MM-DD_HH-MM-SS`` del nombre del archivo L3.

    Errores:
        ``ValueError`` si el nombre no termina en el sufijo esperado. Es una
        invariante interna: el único productor de estos nombres es WP-004.
    """

    sufijo_l3 = f"-{NivelAuditoria.L3.value}"
    tallo = ruta_l3.stem
    if not tallo.endswith(sufijo_l3):
        raise ValueError(f"El archivo {ruta_l3.name} no sigue el patrón del conjunto de auditoría")
    return tallo[: -len(sufijo_l3)]


def _fecha_del_conjunto(ruta_l3: Path) -> str:
    """Convierte la marca nominal del conjunto en ``DD/MM/AAAA``."""

    marca = datetime.strptime(_prefijo_del_conjunto(ruta_l3), FORMATO_NOMBRE)
    return marca.strftime(FORMATO_FECHA_ACTA)


def _formatear_evento(fila: Sequence[str], numero_fila: int, ruta_l3: Path) -> str:
    """Convierte una fila del CSV en la línea ``HH:MM:SS — texto`` del acta.

    Entradas:
        fila: las seis columnas canónicas ``seq;timestamp;level;tag;event_code;message``.
        numero_fila: posición dentro del archivo, sólo para ubicar un fallo.
        ruta_l3: archivo de origen, sólo para ubicar un fallo.

    Resultado:
        La línea del informe. Nunca ``None``: una fila que no puede publicarse
        hace fallar el acta completa.

    Errores:
        ErrorActaNoDerivable: si la fila no tiene exactamente seis columnas, si
            ``seq`` no es un entero, si ``level`` no es ``L3``, si el timestamp
            no respeta el formato canónico, o si la familia ``(tag, event_code)``
            no tiene política de redacción declarada.

    Por qué se valida tan estrictamente: I001 de este WP salteaba las filas
    truncadas y declaraba el acta exitosa igual. Un informe formal que aparenta
    estar completo mientras omite evidencia es peor que un informe que no se
    generó, porque nadie llega a enterarse de que faltaba algo.

    De las seis columnas, el acta publica exactamente una hora y un texto. Ni
    ``seq``, ni ``level``, ni ``tag``, ni ``event_code`` se imprimen: ``tag`` y
    ``event_code`` sólo eligen, internamente, qué política redacta el texto.
    """

    def rechazar(detalle: str) -> ErrorActaNoDerivable:
        return ErrorActaNoDerivable(
            f"Fila {numero_fila} de {ruta_l3.name}: {detalle}. "
            "El acta no se deriva de un L3 que no puede interpretarse por completo."
        )

    if len(fila) != len(ENCABEZADO_CSV):
        raise rechazar(
            f"se esperaban {len(ENCABEZADO_CSV)} columnas canónicas y se leyeron {len(fila)}"
        )

    secuencia, timestamp, nivel, etiqueta, codigo_evento, mensaje = fila

    if not secuencia.isdigit():
        raise rechazar(f"la columna seq {secuencia!r} no es un entero")
    if nivel != NivelAuditoria.L3.value:
        raise rechazar(f"la columna level es {nivel!r} y el archivo L3 sólo admite eventos L3")

    try:
        hora = _hora_del_timestamp(timestamp)
    except ValueError as error:
        raise rechazar(f"el timestamp {timestamp!r} no respeta el formato canónico") from error

    try:
        texto = redactar_linea_de_acta(etiqueta, codigo_evento, _depurar_texto(mensaje))
    except ErrorActaNoDerivable as error:
        raise rechazar(str(error)) from error

    return f"{hora}{SEPARADOR_LINEA_ACTA}{texto}"


def _hora_del_timestamp(timestamp: str) -> str:
    """Devuelve ``HH:MM:SS`` a partir de ``AAAA-MM-DD HH:MM:SS``.

    Se valida con ``strptime`` en vez de recortar por posición para que un
    timestamp con otro formato produzca un error visible durante la generación,
    en lugar de una hora silenciosamente mal recortada.
    """

    return datetime.strptime(timestamp, FORMATO_TIMESTAMP).strftime("%H:%M:%S")


def _depurar_texto(mensaje: str) -> str:
    """Retira pictogramas antes de aplicar la política explícita de la familia.

    Quita emojis y pictogramas, colapsa los espacios dobles que esa eliminación
    puede dejar y recorta los extremos. La función no decide qué parte del
    mensaje es institucional: esa responsabilidad pertenece al formatter
    declarado en ``POLITICAS_ACTA``, que reconstruye el hecho sin copiar su
    metadata técnica.
    """

    return _ESPACIOS_REPETIDOS.sub(" ", _EMOJIS.sub("", mensaje)).strip()
