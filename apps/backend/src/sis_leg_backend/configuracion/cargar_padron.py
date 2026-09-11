"""Carga y validación técnica de ``config/concejales.csv`` (WP-003).

Flujo principal paso a paso:

1. Se lee el archivo completo con ``utf-8-sig``: esa codificación tolera el
   BOM que algunos editores de Windows agregan al guardar CSV.
2. ``csv`` (biblioteca estándar) convierte cada línea en una lista de
   columnas, respetando comillas y comas dentro de los campos.
3. La primera fila debe ser **exactamente** el encabezado canónico de siete
   columnas. Cualquier diferencia (faltante, extra o renombrada, como el
   ``presente`` del formato histórico) rechaza el archivo: así el padrón
   histórico no se acepta silenciosamente como el nuevo contrato.
4. Cada fila restante se valida por campos: DNI, nombre y apellido
   obligatorios tras recortar espacios; banca entera positiva, dentro de la
   capacidad y única; dispositivo obligatorio y único; ``ruta_imagen``
   obligatoria y conforme al contrato seguro de WP-098. ``bloque`` puede
   quedar vacío.
   Ante el primer incumplimiento se lanza el error correspondiente, con el
   número de fila para facilitar la corrección del archivo.
5. Al final se exige la correspondencia exacta padrón/disposición
   (RN-CON-04): la cantidad de concejales debe ser ``sum(room.rows)``.
   Como cada banca ya se validó única y dentro de ``1..capacidad``, la
   igualdad de cantidades garantiza que las bancas cubren por completo la
   disposición, sin faltantes ni sobrantes.
6. Con las filas validadas se construye ``Padron`` (dataclass congelado,
   tupla inmutable de concejales), independiente del archivo de disco
   (congelamiento de padrón, RN-CON-07 y CA-059).
"""

from __future__ import annotations

import csv
from pathlib import Path

from sis_leg_backend.configuracion.errores import ErrorPadronInvalido
from sis_leg_backend.configuracion.imagenes_concejales import (
    ErrorRutaImagenInvalida,
    validar_ruta_imagen_concejal,
)
from sis_leg_backend.configuracion.modelos import Concejal, ConfiguracionSistema, Padron

# Encabezado canónico exacto aprobado en WP-003: siete columnas y ese orden.
ENCABEZADO_CANONICO = "dni,nombre,apellido,bloque,banca,dispositivo_votacion,ruta_imagen"

# Posiciones de columna, con nombre semántico para que las validaciones se
# lean como texto y no como números mágicos.
INDICE_DNI = 0
INDICE_NOMBRE = 1
INDICE_APELLIDO = 2
INDICE_BLOQUE = 3
INDICE_BANCA = 4
INDICE_DISPOSITIVO = 5
INDICE_RUTA_IMAGEN = 6
CANTIDAD_COLUMNAS = 7


def cargar_padron_concejales(ruta: Path, configuracion: ConfiguracionSistema) -> Padron:
    """Lee y valida ``concejales.csv`` contra la disposición configurada.

    Entradas:
        ruta: ubicación del archivo CSV del padrón.
        configuracion: snapshot ya cargado de ``system.toml``; aporta la
            capacidad total del recinto contra la que se valida la
            correspondencia exacta.

    Resultado:
        Un ``Padron`` inmutable e independiente del archivo de disco.

    Errores:
        ``ErrorPadronInvalido`` para cualquier incumplimiento del contrato,
        con mensajes deterministas que incluyen el número de fila cuando el
        problema está en un concejal concreto.
    """
    try:
        # ``utf-8-sig`` descarta un posible BOM inicial sin alterar el resto.
        contenido = ruta.read_text(encoding="utf-8-sig")
    except OSError as error:
        raise ErrorPadronInvalido(
            f"no se pudo leer el archivo de padrón {ruta}: {error}"
        ) from error

    filas = list(csv.reader(contenido.splitlines()))
    if not filas:
        raise ErrorPadronInvalido("el archivo de padrón está vacío")

    encabezado = filas[0]
    if encabezado != ENCABEZADO_CANONICO.split(","):
        # La comparación es literal: mayúsculas, espacios u orden distintos
        # también rechazan el archivo, igual que el ``presente`` histórico.
        recibido = ",".join(encabezado)
        raise ErrorPadronInvalido(
            f"el encabezado del padrón debe ser exactamente "
            f"'{ENCABEZADO_CANONICO}' y se recibió '{recibido}'"
        )

    concejales: list[Concejal] = []
    dnis_vistos: set[str] = set()
    bancas_vistas: set[int] = set()
    dispositivos_vistos: set[str] = set()
    capacidad = configuracion.capacidad_total

    # Las filas numeradas por ``enumerate(start=2)``: la 1 es el encabezado,
    # así los mensajes de error coinciden con la línea del archivo.
    for numero_fila, fila in enumerate(filas[1:], start=2):
        if not fila:
            # Línea en blanco: se ignora, es un formato aceptable de CSV.
            continue
        if len(fila) != CANTIDAD_COLUMNAS:
            raise ErrorPadronInvalido(
                f"la fila {numero_fila} debe tener exactamente "
                f"{CANTIDAD_COLUMNAS} columnas y tiene {len(fila)}"
            )

        dni = fila[INDICE_DNI].strip()
        if not dni:
            raise ErrorPadronInvalido(f"la fila {numero_fila}: el dni no puede estar vacío")
        if dni in dnis_vistos:
            raise ErrorPadronInvalido(f"la fila {numero_fila}: dni duplicado: {dni}")
        dnis_vistos.add(dni)

        nombre = fila[INDICE_NOMBRE].strip()
        if not nombre:
            raise ErrorPadronInvalido(f"la fila {numero_fila}: el nombre no puede estar vacío")

        apellido = fila[INDICE_APELLIDO].strip()
        if not apellido:
            raise ErrorPadronInvalido(f"la fila {numero_fila}: el apellido no puede estar vacío")

        # ``bloque`` no se valida: puede quedar vacío (CA-003).
        bloque = fila[INDICE_BLOQUE].strip()

        try:
            banca = int(fila[INDICE_BANCA].strip())
        except ValueError as error:
            raise ErrorPadronInvalido(
                f"la fila {numero_fila}: la banca debe ser un entero positivo"
            ) from error
        if banca <= 0:
            raise ErrorPadronInvalido(
                f"la fila {numero_fila}: la banca debe ser un entero positivo"
            )
        if banca > capacidad:
            raise ErrorPadronInvalido(
                f"la fila {numero_fila}: la banca {banca} excede la capacidad "
                f"del recinto ({capacidad})"
            )
        if banca in bancas_vistas:
            raise ErrorPadronInvalido(f"la fila {numero_fila}: banca duplicada: {banca}")
        bancas_vistas.add(banca)

        dispositivo = fila[INDICE_DISPOSITIVO].strip()
        if not dispositivo:
            raise ErrorPadronInvalido(
                f"la fila {numero_fila}: el dispositivo de votación no puede estar vacío"
            )
        if dispositivo in dispositivos_vistos:
            raise ErrorPadronInvalido(
                f"la fila {numero_fila}: dispositivo de votación duplicado: {dispositivo}"
            )
        dispositivos_vistos.add(dispositivo)

        ruta_imagen = fila[INDICE_RUTA_IMAGEN].strip()
        if not ruta_imagen:
            raise ErrorPadronInvalido(f"la fila {numero_fila}: la ruta_imagen no puede estar vacía")
        try:
            # WP-098: la validación vive en un único módulo porque exactamente
            # las mismas reglas las aplica el endpoint que publica la imagen.
            # Si la carga del padrón aceptara algo que el endpoint rechaza, la
            # banca quedaría con una foto que nunca puede resolverse.
            validar_ruta_imagen_concejal(ruta_imagen)
        except ErrorRutaImagenInvalida as error:
            raise ErrorPadronInvalido(f"la fila {numero_fila}: {error}") from error

        concejales.append(
            Concejal(
                dni=dni,
                nombre=nombre,
                apellido=apellido,
                bloque=bloque,
                banca=banca,
                dispositivo_votacion=dispositivo,
                ruta_imagen=ruta_imagen,
            )
        )

    if len(concejales) != capacidad:
        raise ErrorPadronInvalido(
            f"la cantidad de concejales ({len(concejales)}) debe coincidir "
            f"exactamente con la capacidad del recinto ({capacidad})"
        )

    return Padron(concejales=tuple(concejales))
