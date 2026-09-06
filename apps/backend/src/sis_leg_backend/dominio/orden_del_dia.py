"""Modelo de dominio y parseador canónico del Orden del Día (WP-016).

SIS-Leg adopta un contrato CSV explícito de seis columnas definido en DT-039:

    nro_votacion,tipo,tema,tipo_mayoria,factor,base

El Orden del Día cumple una función exclusivamente asistencial (RN-OD-01):
permite precargar datos en un formulario de Moderación para agilizar la
creación de votaciones, pero no constituye una fuente de autoridad
institucional ni impone un orden estricto de tratamiento.

Principios pedagógicos y de diseño aplicados:
1. Parser puro y desacoplado: la función :func:`parsear_orden_del_dia` recibe
   únicamente bytes, valida legibilidad y estructura técnica, y devuelve
   objetos inmutables :class:`PuntoOrdenDelDia`. No consulta ni muta estado
   global.
2. Carga atómica: si cualquier fila es inválida, falla todo el proceso y no
   se genera una colección parcial.
3. Validación deliberadamente técnica: no se juzga la legitimidad institucional
   del contenido, no se exige unicidad ni secuencia en los números, ni se
   valida el tipo descriptivo contra listas de configuración.
4. Normalización estricta:
   - Para mayoría SIMPLE: factor normalizado a 0 y base a VOTOS_COMPUTABLES.
   - Para mayoría ESPECIAL: factor finito > 0 y <= 1, y base obligatoria.
   - Nunca se infiere el tipo de mayoría a partir del factor.
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass

from sis_leg_backend.dominio.errores import ErrorOrdenDelDiaInvalido
from sis_leg_backend.dominio.votacion import BaseMayoria, TipoMayoria

# Nombres exactos y orden canónico de las seis columnas requeridas por DT-039.
COLUMNAS_CANONICAS: tuple[str, ...] = (
    "nro_votacion",
    "tipo",
    "tema",
    "tipo_mayoria",
    "factor",
    "base",
)
CANTIDAD_COLUMNAS_CANONICAS = len(COLUMNAS_CANONICAS)


@dataclass(frozen=True, slots=True)
class PuntoOrdenDelDia:
    """Representa un punto individual normalizado del Orden del Día.

    Atributos:
        nro_votacion: número externo propuesto para el formulario (entero >= 1).
        tipo: texto descriptivo del tipo de votación (ej: "Despacho", "Moción").
        tema: descripción del tema o asunto a tratar.
        tipo_mayoria: regla de mayoría autoritativa (:class:`TipoMayoria.SIMPLE`
            o :class:`TipoMayoria.ESPECIAL`).
        factor: valor numérico normalizado. Para SIMPLE siempre es 0.0; para
            ESPECIAL es un valor real finito > 0.0 y <= 1.0.
        base: denominador institucional normalizado (:class:`BaseMayoria`).
    """

    nro_votacion: int
    tipo: str
    tema: str
    tipo_mayoria: TipoMayoria
    factor: float
    base: BaseMayoria


def _validar_y_parsear_nro_votacion(valor_crudo: str, indice_fila: int) -> int:
    """Valida y convierte el número de votación a entero estricto >= 1.

    El número se utiliza para precargar el formulario. La regla técnica exige:
    - Que sea un entero estricto (no se admiten decimales, booleanos ni texto).
    - Que sea mayor o igual a 1 (no se admiten 0 ni números negativos).
    - No se exige correlatividad ni unicidad entre filas.

    Args:
        valor_crudo: texto extraído de la columna nro_votacion.
        indice_fila: número de fila en el archivo (1-indexed para mensajes de error).

    Returns:
        El entero validado >= 1.

    Raises:
        ErrorOrdenDelDiaInvalido: si el valor no es un entero estricto o es < 1.
    """
    limpio = valor_crudo.strip()
    if not limpio:
        raise ErrorOrdenDelDiaInvalido(
            f"Fila {indice_fila}: el campo 'nro_votacion' es obligatorio y no puede estar vacío."
        )

    # Exigimos dígitos ASCII puros ('0'-'9'). Esto rechaza signos ('-1', '+1'),
    # decimales ('1.0', '1.5'), texto ('uno') y caracteres numéricos Unicode
    # que isdigit() aceptaría pero int() no puede convertir (ej: '²', '³', '½').
    if not all("0" <= caracter <= "9" for caracter in limpio):
        raise ErrorOrdenDelDiaInvalido(
            f"Fila {indice_fila}: el campo 'nro_votacion' debe ser un entero estricto "
            f"(recibido: '{valor_crudo}')."
        )

    try:
        valor_entero = int(limpio)
    except ValueError as error:
        raise ErrorOrdenDelDiaInvalido(
            f"Fila {indice_fila}: el campo 'nro_votacion' no es un entero interpretable "
            f"(recibido: '{valor_crudo}')."
        ) from error

    if valor_entero < 1:
        raise ErrorOrdenDelDiaInvalido(
            f"Fila {indice_fila}: el campo 'nro_votacion' debe ser mayor o igual a 1 "
            f"(recibido: {valor_entero})."
        )

    return valor_entero


def _validar_y_parsear_mayoria_simple(
    factor_crudo: str,
    base_cruda: str,
    indice_fila: int,
) -> tuple[float, BaseMayoria]:
    """Valida las reglas técnicas específicas de una mayoría SIMPLE.

    Reglas canónicas (DT-039, WP-016):
    - factor: puede estar vacío o contener una representación numérica finita
      cuyo valor real sea exactamente 0 (ej: "0", "0.0", "0.00"). Cualquier
      otro valor numérico, texto, NaN o infinito es inválido.
    - base: puede estar vacía o indicar 'VOTOS_COMPUTABLES' (case-insensitive).
    - Normalización: el punto resultante siempre se fija con factor = 0.0 y
      base = BaseMayoria.VOTOS_COMPUTABLES.

    Args:
        factor_crudo: texto de la columna factor.
        base_cruda: texto de la columna base.
        indice_fila: número de fila para diagnóstico.

    Returns:
        Tupla normalizada (0.0, BaseMayoria.VOTOS_COMPUTABLES).

    Raises:
        ErrorOrdenDelDiaInvalido: si factor o base violan las restricciones de SIMPLE.
    """
    factor_limpio = factor_crudo.strip()
    if factor_limpio:
        try:
            factor_num = float(factor_limpio)
        except ValueError as err:
            raise ErrorOrdenDelDiaInvalido(
                f"Fila {indice_fila}: el factor para mayoría SIMPLE debe ser 0 o vacío "
                f"(recibido texto no numérico: '{factor_crudo}')."
            ) from err

        if math.isnan(factor_num) or math.isinf(factor_num) or factor_num != 0.0:
            raise ErrorOrdenDelDiaInvalido(
                f"Fila {indice_fila}: el factor para mayoría SIMPLE debe ser exactamente 0 o vacío "
                f"(recibido: '{factor_crudo}')."
            )

    base_limpia = base_cruda.strip().upper()
    if base_limpia and base_limpia != BaseMayoria.VOTOS_COMPUTABLES.value:
        raise ErrorOrdenDelDiaInvalido(
            f"Fila {indice_fila}: la base para mayoría SIMPLE debe ser vacía o "
            f"'VOTOS_COMPUTABLES' (recibido: '{base_cruda}')."
        )

    return 0.0, BaseMayoria.VOTOS_COMPUTABLES


def _validar_y_parsear_mayoria_especial(
    factor_crudo: str,
    base_cruda: str,
    indice_fila: int,
) -> tuple[float, BaseMayoria]:
    """Valida las reglas técnicas específicas de una mayoría ESPECIAL.

    Reglas canónicas (DT-039, WP-016):
    - factor: obligatorio, real finito estrictamente mayor a 0 y menor o igual a 1
      (0 < factor <= 1). No se redondea ni se aproxima.
    - base: obligatoria, debe ser una de las tres bases canónicas:
      'VOTOS_COMPUTABLES', 'PRESENTES' o 'CUERPO' (case-insensitive).

    Args:
        factor_crudo: texto de la columna factor.
        base_cruda: texto de la columna base.
        indice_fila: número de fila para diagnóstico.

    Returns:
        Tupla normalizada (factor_float, BaseMayoria).

    Raises:
        ErrorOrdenDelDiaInvalido: si factor o base son inválidos o faltantes.
    """
    factor_limpio = factor_crudo.strip()
    if not factor_limpio:
        raise ErrorOrdenDelDiaInvalido(
            f"Fila {indice_fila}: el factor es obligatorio para mayoría ESPECIAL."
        )

    try:
        factor_num = float(factor_limpio)
    except ValueError as err:
        raise ErrorOrdenDelDiaInvalido(
            f"Fila {indice_fila}: el factor para mayoría ESPECIAL debe ser un número real "
            f"(recibido: '{factor_crudo}')."
        ) from err

    if math.isnan(factor_num) or math.isinf(factor_num) or factor_num <= 0.0 or factor_num > 1.0:
        raise ErrorOrdenDelDiaInvalido(
            f"Fila {indice_fila}: el factor para mayoría ESPECIAL debe ser un número finito "
            f"mayor a 0 y menor o igual a 1 (recibido: '{factor_crudo}')."
        )

    base_limpia = base_cruda.strip().upper()
    if not base_limpia:
        raise ErrorOrdenDelDiaInvalido(
            f"Fila {indice_fila}: la base es obligatoria para mayoría ESPECIAL."
        )

    try:
        base_enum = BaseMayoria(base_limpia)
    except ValueError as err:
        raise ErrorOrdenDelDiaInvalido(
            f"Fila {indice_fila}: base desconocida para mayoría ESPECIAL: '{base_cruda}'. "
            f"Valores permitidos: VOTOS_COMPUTABLES, PRESENTES, CUERPO."
        ) from err

    return factor_num, base_enum


def parsear_orden_del_dia(contenido_bytes: bytes) -> tuple[PuntoOrdenDelDia, ...]:
    """Parsea y valida atómicamente el contenido CSV del Orden del Día.

    Esta función ejecuta la validación pura del formato sin efectos secundarios:
    1. Comprueba que el contenido no esté vacío en bytes (0 bytes => inválido).
    2. Decodifica el texto como UTF-8 y descarta un posible BOM inicial.
    3. Interpreta el formato CSV con quoting estándar.
    4. Verifica que el encabezado coincida exactamente en orden y nombres con
       las 6 columnas canónicas de DT-039.
    5. Parsea cada fila aplicando las reglas de mayoría SIMPLE y ESPECIAL.
    6. Si no hay filas de datos tras un encabezado válido, devuelve una tupla
       vacía (colección vacía válida).
    7. Si cualquier fila es técnicamente defectuosa, lanza
       :class:`ErrorOrdenDelDiaInvalido` y no genera puntos parciales.

    Args:
        contenido_bytes: bytes crudos del archivo subido.

    Returns:
        Tupla inmutable de :class:`PuntoOrdenDelDia` normalizados.

    Raises:
        ErrorOrdenDelDiaInvalido: ante cualquier falla de decodificación,
            encabezado, formato CSV o validación de campos.
    """
    if len(contenido_bytes) == 0:
        raise ErrorOrdenDelDiaInvalido("El archivo de Orden del Día está vacío (0 bytes).")

    # Decodificación UTF-8
    try:
        texto = contenido_bytes.decode("utf-8")
    except UnicodeDecodeError as err:
        raise ErrorOrdenDelDiaInvalido(
            "El archivo no es texto UTF-8 válido o contiene bytes no decodificables."
        ) from err

    # Soporte de UTF-8 con BOM: si el archivo comienza con '\ufeff', eliminamos
    # únicamente ese carácter inicial para interpretar el encabezado limpiamente.
    if texto.startswith("\ufeff"):
        texto = texto[1:]

    if not texto.strip():
        raise ErrorOrdenDelDiaInvalido(
            "El archivo de Orden del Día no contiene datos interpretables."
        )

    # Creamos el lector CSV estándar
    buffer_texto = io.StringIO(texto)
    try:
        lector_csv = csv.reader(buffer_texto, delimiter=",", strict=True)
        primera_fila = next(lector_csv, None)
    except csv.Error as err:
        raise ErrorOrdenDelDiaInvalido(f"El archivo CSV está malformado: {err}") from err

    if primera_fila is None:
        raise ErrorOrdenDelDiaInvalido("El archivo no contiene ninguna fila.")

    # Verificamos que la primera fila coincida exactamente con las 6 columnas canónicas.
    if tuple(primera_fila) != COLUMNAS_CANONICAS:
        raise ErrorOrdenDelDiaInvalido(
            f"Encabezado CSV inválido. Se esperaba exactamente: '{','.join(COLUMNAS_CANONICAS)}'. "
            f"Se recibió: '{','.join(primera_fila)}'."
        )

    puntos: list[PuntoOrdenDelDia] = []

    try:
        for numero_fila, fila in enumerate(lector_csv, start=2):
            # Ignoramos líneas completamente vacías producidas por finales de línea consecutivos
            if len(fila) == 0:
                continue

            if len(fila) != CANTIDAD_COLUMNAS_CANONICAS:
                raise ErrorOrdenDelDiaInvalido(
                    f"Fila {numero_fila}: cantidad incorrecta de columnas. "
                    f"Se esperaban {CANTIDAD_COLUMNAS_CANONICAS}, pero se recibieron {len(fila)}."
                )

            nro_crudo, tipo_crudo, tema_crudo, mayoria_cruda, factor_crudo, base_cruda = fila

            # 1. nro_votacion
            nro_votacion = _validar_y_parsear_nro_votacion(nro_crudo, numero_fila)

            # 2. tipo y tema (textos descriptivos sin validación institucional)
            tipo = tipo_crudo.strip()
            tema = tema_crudo.strip()

            # 3. tipo_mayoria
            mayoria_limpia = mayoria_cruda.strip().upper()
            if mayoria_limpia == TipoMayoria.SIMPLE.value:
                tipo_mayoria = TipoMayoria.SIMPLE
                factor, base = _validar_y_parsear_mayoria_simple(
                    factor_crudo, base_cruda, numero_fila
                )
            elif mayoria_limpia == TipoMayoria.ESPECIAL.value:
                tipo_mayoria = TipoMayoria.ESPECIAL
                factor, base = _validar_y_parsear_mayoria_especial(
                    factor_crudo, base_cruda, numero_fila
                )
            else:
                raise ErrorOrdenDelDiaInvalido(
                    f"Fila {numero_fila}: 'tipo_mayoria' inválido: '{mayoria_cruda}'. "
                    f"Valores permitidos: SIMPLE, ESPECIAL."
                )

            puntos.append(
                PuntoOrdenDelDia(
                    nro_votacion=nro_votacion,
                    tipo=tipo,
                    tema=tema,
                    tipo_mayoria=tipo_mayoria,
                    factor=factor,
                    base=base,
                )
            )
    except csv.Error as err:
        raise ErrorOrdenDelDiaInvalido(f"Error al leer las filas del archivo CSV: {err}") from err

    return tuple(puntos)
