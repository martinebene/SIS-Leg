"""Contrato, validación y lectura de los sonidos de la Pantalla del Recinto (WP-065).

Qué resuelve este módulo
------------------------
``config/system.toml`` incorpora una sección ``[sonidos]`` con **quince**
entradas obligatorias, una por cada evento sonoro del Recinto. Cada entrada
declara un archivo y un volumen entero de ``0`` a ``100``.

Este módulo es el único lugar donde se interpreta esa sección. Ofrece tres
operaciones con propósitos distintos:

- :func:`exigir_sonidos_recinto` valida la sección dentro de un TOML ya
  parseado. La usa ``cargar_configuracion_sistema``, de modo que una sección
  inválida impide preparar el recinto igual que un ``quorum`` inválido.
- :func:`leer_sonidos_recinto` lee el archivo por su cuenta al **arrancar** el
  backend y, si algo falla, devuelve una configuración marcada como no
  disponible en lugar de propagar el error. Ese arranque tolerante es
  deliberado: la Pantalla del Recinto debe poder mostrarse en ``SIN_PREPARAR``
  aunque los sonidos estén mal configurados, y un TOML roto no puede dejar al
  sistema sin votaciones ni auditoría. Es exactamente el mismo criterio que ya
  se aplica a la biblioteca de mensajes de Apoyo Técnico (WP-055).
- :func:`validar_assets_sonidos` comprueba que cada ruta configurada resuelva a
  un archivo realmente existente dentro de la raíz pública del Recinto. Es una
  validación de **despliegue**, no de arranque, porque el backend no conoce ni
  debe conocer el árbol de archivos del frontend.

Por qué las rutas son restringidas
----------------------------------
La ruta configurada viaja al navegador dentro de la proyección pública. Si se
admitiera cualquier texto, ``system.toml`` podría hacer que la Pantalla del
Recinto pidiera ``/etc/passwd`` o un archivo remoto. Por eso se exige que toda
ruta empiece por ``assets/sonidos/``, termine en ``.wav`` y no contenga
esquemas, rutas absolutas ni segmentos ``..``: el resultado es siempre una
referencia a un asset versionado y servido por la propia aplicación.

Por qué los nombres están en español
------------------------------------
Las secciones anteriores del TOML (``session``, ``room``, ``timers``…) están en
inglés porque WP-003 las aprobó así y renombrarlas rompería instalaciones. Esta
sección es nueva y no arrastra compatibilidad, de modo que aplica la regla
general de DEC-001 —identificadores propios en español— que WP-065 vuelve a
pedir explícitamente para los nombres de los quince eventos.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, cast

from sis_leg_backend.configuracion.errores import (
    ErrorConfiguracion,
    ErrorValidacionConfiguracion,
)
from sis_leg_backend.configuracion.modelos import (
    ConfiguracionSonidosRecinto,
    SonidoRecinto,
)

NOMBRE_SECCION = "sonidos"
"""Nombre de la sección del TOML que contiene los sonidos."""

EVENTOS_SONIDO_RECINTO: tuple[str, ...] = (
    "preparacion_iniciada",
    "aviso_tecnico_publicado",
    "aviso_tecnico_retirado",
    "pedido_palabra_registrado",
    "pedido_palabra_retirado",
    "uso_palabra_otorgado",
    "transmision_iniciada",
    "transmision_detenida",
    "transmision_cuenta_regresiva_tic",
    "sesion_abierta",
    "sesion_cerrada",
    "votacion_abierta",
    "votacion_cerrada",
    "concejal_ausente",
    "concejal_presente",
)
"""Los quince eventos sonoros obligatorios de WP-065, en su orden canónico.

El orden importa porque es el que viaja en la proyección: mantenerlo estable
evita que dos snapshots idénticos difieran sólo por el orden de una lista.

Cada nombre coincide con el código de auditoría equivalente cuando existe
(``SESION_ABIERTA`` -> ``sesion_abierta``). Las dos excepciones son
``aviso_tecnico_retirado`` —cubre tanto la cancelación como el vencimiento de un
aviso, porque desde la Pantalla del Recinto ambas cosas se ven igual— y
``transmision_cuenta_regresiva_tic``, que no es un hecho auditable sino un
cambio de segundo en la cuenta regresiva hacia el vivo.
"""

CLAVE_RUTA = "ruta"
CLAVE_VOLUMEN = "volumen"
CLAVES_SONIDO = frozenset({CLAVE_RUTA, CLAVE_VOLUMEN})

PREFIJO_RUTA_SONIDO = "assets/sonidos/"
"""Único prefijo admitido: los assets versionados del propio Recinto."""

EXTENSION_SONIDO = ".wav"
"""Única extensión admitida (WAV PCM, reproducible sin decodificador externo)."""

VOLUMEN_MINIMO = 0
VOLUMEN_MAXIMO = 100

MOTIVO_SONIDOS_INVALIDOS = "SONIDOS_RECINTO_INVALIDOS"
"""Código estable publicado cuando la sección existe pero no pudo leerse.

La Pantalla del Recinto puede así explicar por qué no hay sonidos sin depender
de textos variables.
"""


def exigir_sonidos_recinto(datos: dict[str, Any]) -> ConfiguracionSonidosRecinto:
    """Valida la sección ``[sonidos]`` de un TOML ya parseado.

    Entradas:
        datos: diccionario completo devuelto por ``tomllib``.

    Resultado:
        Una ``ConfiguracionSonidosRecinto`` disponible, con los quince sonidos
        en el orden canónico de :data:`EVENTOS_SONIDO_RECINTO`.

    Errores:
        ``ErrorValidacionConfiguracion`` si falta la sección, falta o sobra un
        evento, sobra una clave dentro de un evento, la ruta no es una
        referencia admitida a un asset versionado o el volumen no es un entero
        de ``0`` a ``100``. Los mensajes nombran la clave canónica completa
        (por ejemplo ``sonidos.sesion_abierta.volumen``) para que corregir el
        archivo sea inmediato.
    """

    seccion = datos.get(NOMBRE_SECCION)
    if not isinstance(seccion, dict):
        raise ErrorValidacionConfiguracion(f"falta la sección [{NOMBRE_SECCION}]")
    seccion_tipada = cast(dict[str, Any], seccion)

    # A diferencia del resto del archivo, aquí las claves desconocidas se
    # rechazan. Ignorarlas convertiría un evento mal escrito en un sonido
    # silenciosamente perdido, que es justamente el error más difícil de notar
    # durante una sesión.
    conocidos = set(EVENTOS_SONIDO_RECINTO)
    sobrantes = sorted(clave for clave in seccion_tipada if clave not in conocidos)
    if sobrantes:
        raise ErrorValidacionConfiguracion(
            f"[{NOMBRE_SECCION}] declara eventos desconocidos: {', '.join(sobrantes)}"
        )

    sonidos: list[SonidoRecinto] = []
    for evento in EVENTOS_SONIDO_RECINTO:
        sonidos.append(_exigir_sonido(seccion_tipada, evento))
    return ConfiguracionSonidosRecinto(sonidos=tuple(sonidos))


def leer_sonidos_recinto(ruta: Path) -> ConfiguracionSonidosRecinto:
    """Lee los sonidos al arrancar el backend sin poder impedir el arranque.

    Entradas:
        ruta: ubicación de ``system.toml``.

    Resultado:
        La configuración de sonidos vigente. Si el archivo no existe, no es
        TOML válido o la sección no cumple el contrato, devuelve una
        configuración vacía con ``disponible=False`` y el detalle del problema,
        para que la Pantalla del Recinto lo muestre en lugar de quedarse sin
        explicación.

    Efectos:
        Ninguno fuera de la lectura del archivo. Nunca escribe ni corrige el
        TOML: un archivo inválido lo corrige una persona.
    """

    try:
        contenido = ruta.read_text(encoding="utf-8")
        datos = tomllib.loads(contenido)
        return exigir_sonidos_recinto(datos)
    except (OSError, tomllib.TOMLDecodeError, ErrorConfiguracion) as error:
        return ConfiguracionSonidosRecinto(
            sonidos=(),
            disponible=False,
            motivo=MOTIVO_SONIDOS_INVALIDOS,
            detalle=f"no se pudieron leer los sonidos de {ruta}: {error}",
        )


def validar_assets_sonidos(
    configuracion: ConfiguracionSonidosRecinto,
    raiz_publica: Path,
) -> None:
    """Exige que las quince rutas configuradas resuelvan a archivos existentes.

    Entradas:
        configuracion: sonidos ya validados sintácticamente.
        raiz_publica: directorio que la Pantalla del Recinto sirve como raíz
            (``apps/recinto/public`` en el repositorio, ``web/recinto`` dentro
            de una release productiva).

    Errores:
        ``ErrorValidacionConfiguracion`` si un archivo no existe o si la ruta,
        una vez resuelta, quedaría fuera de la raíz pública. La segunda
        comprobación es defensiva: la validación sintáctica ya prohíbe ``..``,
        pero un enlace simbólico podría escapar igual y no debe hacerlo.

    Esta comprobación no se hace al cargar la configuración porque el backend
    no conoce el árbol de archivos del frontend: pertenece al despliegue y a
    las pruebas del repositorio.
    """

    raiz_resuelta = raiz_publica.resolve()
    for sonido in configuracion.sonidos:
        destino = (raiz_publica / sonido.ruta).resolve()
        if not destino.is_relative_to(raiz_resuelta):
            raise ErrorValidacionConfiguracion(
                f"{NOMBRE_SECCION}.{sonido.evento}.{CLAVE_RUTA} resuelve fuera de "
                f"{raiz_resuelta}: {destino}"
            )
        if not destino.is_file():
            raise ErrorValidacionConfiguracion(
                f"{NOMBRE_SECCION}.{sonido.evento}.{CLAVE_RUTA} apunta a un archivo "
                f"inexistente: {destino}"
            )


def _exigir_sonido(seccion: dict[str, Any], evento: str) -> SonidoRecinto:
    """Valida una entrada ``[sonidos.<evento>]`` completa."""

    entrada = seccion.get(evento)
    if not isinstance(entrada, dict):
        raise ErrorValidacionConfiguracion(
            f"falta la sección [{NOMBRE_SECCION}.{evento}] con sus claves "
            f"{CLAVE_RUTA} y {CLAVE_VOLUMEN}"
        )
    entrada_tipada = cast(dict[str, Any], entrada)

    sobrantes = sorted(clave for clave in entrada_tipada if clave not in CLAVES_SONIDO)
    if sobrantes:
        raise ErrorValidacionConfiguracion(
            f"[{NOMBRE_SECCION}.{evento}] declara claves desconocidas: {', '.join(sobrantes)}"
        )

    return SonidoRecinto(
        evento=evento,
        ruta=_exigir_ruta(entrada_tipada, evento),
        volumen=_exigir_volumen(entrada_tipada, evento),
    )


def _exigir_ruta(entrada: dict[str, Any], evento: str) -> str:
    """Valida ``ruta`` como referencia a un asset versionado del Recinto.

    Se rechaza, en este orden: un valor que no sea texto no vacío; cualquier
    esquema de URL o URL de protocolo relativo; la barra invertida de Windows
    (que un servidor POSIX no interpretaría como separador); una ruta que no
    empiece por el prefijo canónico; un segmento vacío o ``.``/``..``; y una
    extensión distinta de ``.wav``.
    """

    clave = f"{NOMBRE_SECCION}.{evento}.{CLAVE_RUTA}"
    valor = entrada.get(CLAVE_RUTA)
    if not isinstance(valor, str) or not valor.strip():
        raise ErrorValidacionConfiguracion(f"{clave} debe ser un texto no vacío")

    if "://" in valor or valor.startswith("//"):
        raise ErrorValidacionConfiguracion(f"{clave} no puede ser una URL externa: {valor}")
    if "\\" in valor:
        raise ErrorValidacionConfiguracion(f"{clave} no puede contener barras invertidas: {valor}")
    if not valor.startswith(PREFIJO_RUTA_SONIDO):
        raise ErrorValidacionConfiguracion(
            f"{clave} debe empezar por {PREFIJO_RUTA_SONIDO} para referirse a un "
            f"asset versionado del Recinto: {valor}"
        )
    for segmento in valor.split("/"):
        if segmento in ("", ".", ".."):
            raise ErrorValidacionConfiguracion(
                f"{clave} no puede contener segmentos vacíos ni relativos: {valor}"
            )
    if not valor.endswith(EXTENSION_SONIDO):
        raise ErrorValidacionConfiguracion(f"{clave} debe terminar en {EXTENSION_SONIDO}: {valor}")
    return valor


def _exigir_volumen(entrada: dict[str, Any], evento: str) -> int:
    """Valida ``volumen`` como entero de 0 a 100.

    Los booleanos se rechazan explícitamente: en Python ``True`` es subclase de
    ``int`` y ``volumen = true`` no debe interpretarse como volumen ``1``. Los
    decimales también se rechazan, porque WP-065 fija el contrato en enteros y
    aceptar ``70.0`` obligaría a decidir un redondeo que nadie pidió.
    """

    clave = f"{NOMBRE_SECCION}.{evento}.{CLAVE_VOLUMEN}"
    valor = entrada.get(CLAVE_VOLUMEN)
    if not isinstance(valor, int) or isinstance(valor, bool):
        raise ErrorValidacionConfiguracion(
            f"{clave} debe ser un entero entre {VOLUMEN_MINIMO} y {VOLUMEN_MAXIMO}"
        )
    if not VOLUMEN_MINIMO <= valor <= VOLUMEN_MAXIMO:
        raise ErrorValidacionConfiguracion(
            f"{clave} debe estar entre {VOLUMEN_MINIMO} y {VOLUMEN_MAXIMO}, y vale {valor}"
        )
    return valor
