"""Generador determinista de los 22 sonidos WAV de la Pantalla del Recinto (WP-065).

¿Por qué existe este script?
----------------------------
WP-065 exige versionar sonidos **aptos para redistribución** y con procedencia
documentada. En lugar de descargar archivos de terceros con licencias difíciles
de auditar, SIS-Leg **sintetiza** sus propios sonidos: este script es la única
fuente de los 22 archivos versionados en
``apps/recinto/public/assets/sonidos/``. La procedencia queda demostrada por el
propio repositorio y la licencia es la del proyecto.

¿Por qué "determinista"?
------------------------
El script no usa azar, ni la hora del sistema, ni ninguna biblioteca externa:
solamente ``math``, ``struct`` y ``wave`` de la biblioteca estándar. Con las
mismas recetas produce siempre exactamente los mismos bytes. Eso permite que
``tests/test_sonidos_recinto.py`` regenere los 22 archivos en un directorio
temporal y los compare byte a byte contra los versionados: si alguien
reemplazara un asset por otro de origen desconocido, la prueba fallaría.

¿Cómo se sintetiza un sonido?
-----------------------------
Cada sonido es una mezcla de **voces**. Una voz es un tono con:

- un instante de comienzo (permite acordes y arpegios superponiendo voces);
- una duración;
- una frecuencia inicial y una final (si difieren, la voz "barre" de una a otra);
- una envolvente de amplitud: ataque muy corto y caída exponencial, para que
  el sonido tenga forma de campana/percusión y no de zumbido continuo;
- una lista de armónicos (múltiplos de la frecuencia base con su peso), que es
  lo que distingue un timbre puro de uno metálico o de madera.

Las voces se suman en un búfer de números reales, se normaliza el pico al nivel
declarado por la receta y recién entonces se cuantiza a PCM de 16 bits. Ese
orden importa: normalizar antes de cuantizar evita tanto la saturación (que
suena a distorsión) como el ruido de cuantización de una señal demasiado débil.

Uso::

    uv run python scripts/generar_sonidos_recinto.py            # escribe los WAV
    uv run python scripts/generar_sonidos_recinto.py --destino DIR
"""

from __future__ import annotations

import argparse
import math
import struct
import wave
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# 1. Parámetros técnicos del formato
# ---------------------------------------------------------------------------

FRECUENCIA_MUESTREO = 44100
"""Muestras por segundo. 44,1 kHz es el estándar de audio de consumo y lo
reproduce cualquier navegador sin remuestreo."""

CANALES = 1
"""Los avisos del Recinto son monofónicos: no aportan información espacial."""

BYTES_POR_MUESTRA = 2
"""PCM de 16 bits con signo, el formato WAV más universalmente soportado."""

VALOR_MAXIMO = 32767
"""Mayor valor representable en PCM de 16 bits con signo."""

SEGUNDOS_ENTRADA = 0.003
"""Rampa de entrada global (3 ms). Evita el "clic" que produce empezar a
reproducir desde una muestra distinta de cero."""

SEGUNDOS_SALIDA = 0.012
"""Rampa de salida global (12 ms), por el mismo motivo que la de entrada."""

# Directorio canónico de los assets, relativo a la raíz del monorepo. Vive
# dentro de ``public/`` del Recinto porque es la única aplicación que los
# reproducirá (WP-066) y porque Nuxt publica ese directorio tal cual bajo el
# prefijo ``/recinto/``, sin necesidad de una ruta de servidor adicional.
DESTINO_POR_DEFECTO = Path("apps/recinto/public/assets/sonidos")


# ---------------------------------------------------------------------------
# 2. Modelo de una receta de sonido
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Voz:
    """Un tono individual dentro de un sonido.

    Atributos:
        comienzo: instante, en segundos desde el inicio del archivo, en el que
            empieza a sonar. Superponer voces con distinto ``comienzo`` produce
            arpegios y acordes sin ninguna maquinaria adicional.
        duracion: cuánto dura la voz, en segundos.
        frecuencia: frecuencia en hercios al comenzar.
        frecuencia_final: frecuencia al terminar. ``None`` significa "la misma
            que ``frecuencia``"; un valor distinto produce un barrido lineal.
        amplitud: peso relativo de la voz dentro de la mezcla (0 a 1).
        caida: velocidad de la caída exponencial de la envolvente. Valores
            altos suenan percusivos (se apagan enseguida); valores bajos, más
            sostenidos.
        armonicos: pares ``(multiplicador, peso)``. ``(1.0, 1.0)`` es la
            fundamental; agregar ``(2.0, 0.3)`` suma una octava con 30 % de
            peso, etc. Es lo que define el timbre.
    """

    comienzo: float
    duracion: float
    frecuencia: float
    frecuencia_final: float | None = None
    amplitud: float = 1.0
    caida: float = 4.0
    armonicos: tuple[tuple[float, float], ...] = ((1.0, 1.0),)


@dataclass(frozen=True, slots=True)
class RecetaSonido:
    """Descripción completa y reproducible de uno de los 22 archivos.

    Atributos:
        nombre_archivo: nombre exacto del ``.wav`` generado.
        descripcion: para qué sirve, en lenguaje humano. Es la misma frase que
            aparece en ``assets/sonidos/README.md``, de modo que la
            documentación no pueda desincronizarse de las recetas reales.
        nivel: pico objetivo de la mezcla antes de las rampas globales, entre
            0 y 1. En sonidos muy cortos la rampa de salida recorta un poco ese
            pico, lo cual es deseado. No reemplaza al volumen
            configurable de ``system.toml``: fija la relación de intensidad
            *entre* los sonidos (un tic de cuenta regresiva debe ser más discreto
            que la apertura de sesión aunque ambos se configuren al mismo
            volumen).
        voces: las voces que se mezclan.
    """

    nombre_archivo: str
    descripcion: str
    nivel: float
    voces: tuple[Voz, ...] = field(default=())


# ---------------------------------------------------------------------------
# 3. Timbres reutilizables
# ---------------------------------------------------------------------------

# Un timbre es solamente una lista de armónicos. Se nombran para que las
# recetas de abajo se lean como música y no como números sueltos.

TIMBRE_PURO: tuple[tuple[float, float], ...] = ((1.0, 1.0), (2.0, 0.12))
"""Casi una senoidal: suave y neutro. Para avisos discretos."""

TIMBRE_CAMPANA: tuple[tuple[float, float], ...] = (
    (1.0, 1.0),
    (2.76, 0.34),
    (5.40, 0.16),
    (8.93, 0.07),
)
"""Parciales inarmónicos típicos de una campana tubular: metálico y solemne."""

TIMBRE_MADERA: tuple[tuple[float, float], ...] = (
    (1.0, 1.0),
    (3.0, 0.30),
    (5.0, 0.12),
)
"""Sólo armónicos impares: recuerda a un bloque de madera, seco y corto."""

TIMBRE_CALIDO: tuple[tuple[float, float], ...] = (
    (1.0, 1.0),
    (2.0, 0.42),
    (3.0, 0.18),
    (4.0, 0.08),
)
"""Serie armónica completa decreciente: cuerpo redondo, para tonos graves."""


def _nota(
    comienzo: float,
    duracion: float,
    frecuencia: float,
    *,
    amplitud: float = 1.0,
    caida: float = 4.0,
    armonicos: tuple[tuple[float, float], ...] = TIMBRE_PURO,
) -> Voz:
    """Atajo para declarar una voz de frecuencia constante."""

    return Voz(
        comienzo=comienzo,
        duracion=duracion,
        frecuencia=frecuencia,
        amplitud=amplitud,
        caida=caida,
        armonicos=armonicos,
    )


def _barrido(
    comienzo: float,
    duracion: float,
    desde: float,
    hasta: float,
    *,
    amplitud: float = 1.0,
    caida: float = 2.2,
    armonicos: tuple[tuple[float, float], ...] = TIMBRE_PURO,
) -> Voz:
    """Atajo para declarar una voz que se desliza entre dos frecuencias."""

    return Voz(
        comienzo=comienzo,
        duracion=duracion,
        frecuencia=desde,
        frecuencia_final=hasta,
        amplitud=amplitud,
        caida=caida,
        armonicos=armonicos,
    )


# Frecuencias de las notas usadas (afinación estándar A4 = 440 Hz). Tener los
# nombres musicales evita repetir constantes numéricas sin significado.
DO5 = 523.25
RE5 = 587.33
MI5 = 659.25
SOL5 = 783.99
LA5 = 880.00
SI5 = 987.77
DO6 = 1046.50
MI6 = 1318.51
SOL6 = 1567.98
SOL3 = 196.00
DO4 = 261.63
MI4 = 329.63
SOL4 = 392.00
LA4 = 440.00


# ---------------------------------------------------------------------------
# 4. Las 22 recetas
# ---------------------------------------------------------------------------

# Las primeras quince corresponden, en el mismo orden, a los quince eventos
# obligatorios de WP-065. Las siete últimas son alternativas sin asignar: están
# versionadas para que una instalación pueda cambiar un sonido editando
# ``system.toml``, sin agregar archivos ni tocar código.

RECETAS_ASIGNADAS: tuple[RecetaSonido, ...] = (
    RecetaSonido(
        nombre_archivo="preparacion-iniciada.wav",
        descripcion="Comienza la preparación del recinto: dos notas ascendentes suaves.",
        nivel=0.55,
        voces=(
            _nota(0.00, 0.34, DO5, caida=3.6, armonicos=TIMBRE_CALIDO),
            _nota(0.16, 0.42, SOL5, caida=3.2, armonicos=TIMBRE_CALIDO),
        ),
    ),
    RecetaSonido(
        nombre_archivo="aviso-tecnico-publicado.wav",
        descripcion="Aparece un mensaje de Apoyo Técnico en la Pantalla del Recinto.",
        nivel=0.52,
        voces=(
            _nota(0.00, 0.16, LA5, caida=7.0),
            _nota(0.11, 0.26, DO6, caida=5.5),
        ),
    ),
    RecetaSonido(
        nombre_archivo="aviso-tecnico-retirado.wav",
        descripcion="Se retira el mensaje de Apoyo Técnico (por cancelación o vencimiento).",
        nivel=0.46,
        voces=(
            _nota(0.00, 0.16, DO6, caida=7.0),
            _nota(0.11, 0.26, LA5, caida=5.5),
        ),
    ),
    RecetaSonido(
        nombre_archivo="pedido-palabra-registrado.wav",
        descripcion="Un concejal cualquiera pide la palabra: repique breve y claro.",
        nivel=0.50,
        voces=(_nota(0.00, 0.30, MI6, caida=8.0, armonicos=TIMBRE_MADERA),),
    ),
    RecetaSonido(
        nombre_archivo="pedido-palabra-retirado.wav",
        descripcion="Un concejal cualquiera retira su pedido de palabra: mismo repique, más grave.",
        nivel=0.44,
        voces=(_nota(0.00, 0.30, MI5, caida=8.0, armonicos=TIMBRE_MADERA),),
    ),
    RecetaSonido(
        nombre_archivo="uso-palabra-otorgado.wav",
        descripcion="Se asigna la palabra a un concejal: arpegio ascendente de tres notas.",
        nivel=0.56,
        voces=(
            _nota(0.00, 0.22, DO5, caida=5.5),
            _nota(0.10, 0.22, MI5, caida=5.5),
            _nota(0.20, 0.40, SOL5, caida=3.8),
        ),
    ),
    RecetaSonido(
        nombre_archivo="transmision-iniciada.wav",
        descripcion="Comienza la transmisión en vivo: barrido ascendente decidido.",
        nivel=0.58,
        voces=(
            _barrido(0.00, 0.46, SOL4, SOL5, amplitud=1.0, caida=1.6),
            _nota(0.34, 0.34, SOL5, amplitud=0.45, caida=4.0, armonicos=TIMBRE_CALIDO),
        ),
    ),
    RecetaSonido(
        nombre_archivo="transmision-detenida.wav",
        descripcion="Se detiene la transmisión en vivo: barrido descendente.",
        nivel=0.52,
        voces=(
            _barrido(0.00, 0.46, SOL5, SOL4, amplitud=1.0, caida=1.6),
            _nota(0.34, 0.34, SOL4, amplitud=0.45, caida=4.0, armonicos=TIMBRE_CALIDO),
        ),
    ),
    RecetaSonido(
        nombre_archivo="transmision-cuenta-regresiva-tic.wav",
        descripcion=(
            "Cada cambio de segundo de la cuenta regresiva hacia el vivo: tic muy corto y discreto."
        ),
        nivel=0.34,
        voces=(_nota(0.00, 0.09, DO6, caida=16.0, armonicos=TIMBRE_MADERA),),
    ),
    RecetaSonido(
        nombre_archivo="sesion-abierta.wav",
        descripcion="Apertura de sesión: acorde ascendente de campana, el sonido más solemne.",
        nivel=0.62,
        voces=(
            _nota(0.00, 0.90, DO4, amplitud=0.85, caida=1.5, armonicos=TIMBRE_CAMPANA),
            _nota(0.18, 0.80, MI4, amplitud=0.70, caida=1.6, armonicos=TIMBRE_CAMPANA),
            _nota(0.36, 0.92, SOL4, amplitud=0.75, caida=1.4, armonicos=TIMBRE_CAMPANA),
            _nota(0.54, 1.00, DO5, amplitud=0.60, caida=1.3, armonicos=TIMBRE_CAMPANA),
        ),
    ),
    RecetaSonido(
        nombre_archivo="sesion-cerrada.wav",
        descripcion="Cierre de sesión: la misma campana, en orden descendente.",
        nivel=0.60,
        voces=(
            _nota(0.00, 0.90, DO5, amplitud=0.70, caida=1.5, armonicos=TIMBRE_CAMPANA),
            _nota(0.20, 0.90, SOL4, amplitud=0.75, caida=1.4, armonicos=TIMBRE_CAMPANA),
            _nota(0.40, 1.10, DO4, amplitud=0.85, caida=1.1, armonicos=TIMBRE_CAMPANA),
        ),
    ),
    RecetaSonido(
        nombre_archivo="votacion-abierta.wav",
        descripcion="Apertura de votación: dos notas ascendentes firmes que llaman a votar.",
        nivel=0.58,
        voces=(
            _nota(0.00, 0.26, SOL5, caida=5.0, armonicos=TIMBRE_CALIDO),
            _nota(0.16, 0.44, DO6, caida=3.4, armonicos=TIMBRE_CALIDO),
        ),
    ),
    RecetaSonido(
        nombre_archivo="votacion-cerrada.wav",
        descripcion="Cierre de votación: dos notas descendentes que cierran el bloque.",
        nivel=0.56,
        voces=(
            _nota(0.00, 0.26, DO6, caida=5.0, armonicos=TIMBRE_CALIDO),
            _nota(0.16, 0.46, SOL5, caida=3.2, armonicos=TIMBRE_CALIDO),
        ),
    ),
    RecetaSonido(
        nombre_archivo="concejal-ausente.wav",
        descripcion="Un concejal cualquiera pasa a ausente: destello grave y breve.",
        nivel=0.40,
        voces=(_nota(0.00, 0.20, RE5, caida=9.0, armonicos=TIMBRE_PURO),),
    ),
    RecetaSonido(
        nombre_archivo="concejal-presente.wav",
        descripcion="Un concejal cualquiera pasa a presente: destello agudo y breve.",
        nivel=0.42,
        voces=(_nota(0.00, 0.20, SI5, caida=9.0, armonicos=TIMBRE_PURO),),
    ),
)

RECETAS_ALTERNATIVAS: tuple[RecetaSonido, ...] = (
    RecetaSonido(
        nombre_archivo="alternativa-campana.wav",
        descripcion="Campana única y sostenida.",
        nivel=0.58,
        voces=(_nota(0.00, 1.20, LA4, caida=1.2, armonicos=TIMBRE_CAMPANA),),
    ),
    RecetaSonido(
        nombre_archivo="alternativa-barrido-ascendente.wav",
        descripcion="Barrido ascendente largo.",
        nivel=0.54,
        voces=(_barrido(0.00, 0.55, DO4, DO6, caida=1.4),),
    ),
    RecetaSonido(
        nombre_archivo="alternativa-barrido-descendente.wav",
        descripcion="Barrido descendente largo.",
        nivel=0.54,
        voces=(_barrido(0.00, 0.55, DO6, DO4, caida=1.4),),
    ),
    RecetaSonido(
        nombre_archivo="alternativa-doble-tono.wav",
        descripcion="Dos tonos iguales separados por un silencio corto.",
        nivel=0.50,
        voces=(
            _nota(0.00, 0.18, LA5, caida=6.5),
            _nota(0.24, 0.18, LA5, caida=6.5),
        ),
    ),
    RecetaSonido(
        nombre_archivo="alternativa-golpe-grave.wav",
        descripcion="Golpe grave y corto, para avisos serios.",
        nivel=0.60,
        voces=(_barrido(0.00, 0.28, DO4, SOL3, caida=7.0, armonicos=TIMBRE_CALIDO),),
    ),
    RecetaSonido(
        nombre_archivo="alternativa-pulso-corto.wav",
        descripcion="Pulso agudo mínimo, apenas perceptible.",
        nivel=0.32,
        voces=(_nota(0.00, 0.07, SOL6, caida=18.0),),
    ),
    RecetaSonido(
        nombre_archivo="alternativa-triple-tic.wav",
        descripcion="Tres tics de madera consecutivos.",
        nivel=0.44,
        voces=(
            _nota(0.00, 0.08, DO6, caida=16.0, armonicos=TIMBRE_MADERA),
            _nota(0.13, 0.08, DO6, caida=16.0, armonicos=TIMBRE_MADERA),
            _nota(0.26, 0.10, DO6, caida=14.0, armonicos=TIMBRE_MADERA),
        ),
    ),
)

RECETAS: tuple[RecetaSonido, ...] = RECETAS_ASIGNADAS + RECETAS_ALTERNATIVAS
"""Las 22 recetas versionadas: 15 asignadas a eventos + 7 alternativas libres."""


# ---------------------------------------------------------------------------
# 5. Síntesis
# ---------------------------------------------------------------------------


def _envolvente(indice: int, total: int, caida: float) -> float:
    """Devuelve el factor de amplitud de una voz en la muestra ``indice``.

    La forma es: ataque lineal muy corto (2 ms o el 20 % de la voz, lo que sea
    menor) y luego caída exponencial ``exp(-caida * avance)``. Sobre el final se
    aplica además una rampa lineal a cero durante el último 8 % de la voz, para
    que ninguna voz termine con la señal "cortada" en un valor alto: ese corte
    se oye como un chasquido.
    """

    if total <= 1:
        return 0.0

    muestras_ataque = max(1, min(int(0.002 * FRECUENCIA_MUESTREO), total // 5))
    ataque = indice / muestras_ataque if indice < muestras_ataque else 1.0

    avance = indice / total
    decaimiento = math.exp(-caida * avance)

    muestras_cola = max(1, int(total * 0.08))
    restantes = total - indice
    cola = min(1.0, restantes / muestras_cola)

    return ataque * decaimiento * cola


def _sintetizar_voz(voz: Voz, mezcla: list[float]) -> None:
    """Suma una voz sobre el búfer de mezcla, en su posición temporal.

    Se integra la fase muestra a muestra (``fase += 2*pi*f/fs``) en lugar de
    calcular ``sin(2*pi*f*t)``: cuando la frecuencia cambia a lo largo de la
    voz (un barrido), la fórmula directa produce saltos de fase audibles y la
    integración no.
    """

    total = int(round(voz.duracion * FRECUENCIA_MUESTREO))
    if total <= 0:
        return
    desplazamiento = int(round(voz.comienzo * FRECUENCIA_MUESTREO))
    frecuencia_final = voz.frecuencia if voz.frecuencia_final is None else voz.frecuencia_final
    peso_total = sum(peso for _, peso in voz.armonicos)

    fase = 0.0
    for indice in range(total):
        avance = indice / total
        frecuencia = voz.frecuencia + (frecuencia_final - voz.frecuencia) * avance
        fase += 2.0 * math.pi * frecuencia / FRECUENCIA_MUESTREO
        valor = sum(math.sin(fase * multiplicador) * peso for multiplicador, peso in voz.armonicos)
        muestra = (valor / peso_total) * voz.amplitud * _envolvente(indice, total, voz.caida)
        mezcla[desplazamiento + indice] += muestra


def sintetizar(receta: RecetaSonido) -> bytes:
    """Convierte una receta en el cuerpo PCM de 16 bits de su archivo WAV.

    Pasos:

    1. se calcula la duración total como el mayor ``comienzo + duracion``;
    2. se mezclan todas las voces sobre un búfer de números reales;
    3. se normaliza el pico de la mezcla al ``nivel`` declarado por la receta;
    4. se aplican rampas globales de entrada/salida;
    5. se cuantiza a enteros de 16 bits con signo y se empaqueta en bytes.
    """

    duracion = max(voz.comienzo + voz.duracion for voz in receta.voces)
    total = int(round(duracion * FRECUENCIA_MUESTREO))
    mezcla = [0.0] * total

    for voz in receta.voces:
        _sintetizar_voz(voz, mezcla)

    pico = max(abs(muestra) for muestra in mezcla)
    escala = (receta.nivel / pico) if pico > 0.0 else 0.0

    muestras_entrada = max(1, int(SEGUNDOS_ENTRADA * FRECUENCIA_MUESTREO))
    muestras_salida = max(1, int(SEGUNDOS_SALIDA * FRECUENCIA_MUESTREO))

    enteros: list[int] = []
    for indice, muestra in enumerate(mezcla):
        rampa = min(
            1.0,
            (indice + 1) / muestras_entrada,
            (total - indice) / muestras_salida,
        )
        valor = muestra * escala * rampa
        # ``round`` a entero y recorte defensivo: la normalización ya garantiza
        # |valor| <= nivel <= 1, pero recortar deja el invariante explícito.
        entero = int(round(valor * VALOR_MAXIMO))
        enteros.append(max(-VALOR_MAXIMO, min(VALOR_MAXIMO, entero)))

    return struct.pack(f"<{len(enteros)}h", *enteros)


def escribir_wav(ruta: Path, cuerpo: bytes) -> None:
    """Escribe un WAV PCM mono de 16 bits con el cuerpo ya sintetizado."""

    with wave.open(str(ruta), "wb") as archivo:
        archivo.setnchannels(CANALES)
        archivo.setsampwidth(BYTES_POR_MUESTRA)
        archivo.setframerate(FRECUENCIA_MUESTREO)
        archivo.writeframes(cuerpo)


def generar(destino: Path) -> list[Path]:
    """Genera los 22 archivos dentro de ``destino`` y devuelve sus rutas.

    El directorio se crea si no existe. Los archivos previos se sobrescriben:
    al ser determinista, regenerar sobre un árbol limpio no produce ningún
    cambio en Git.
    """

    destino.mkdir(parents=True, exist_ok=True)
    generados: list[Path] = []
    for receta in RECETAS:
        ruta = destino / receta.nombre_archivo
        escribir_wav(ruta, sintetizar(receta))
        generados.append(ruta)
    return generados


def main(argumentos: Sequence[str] | None = None) -> int:
    """Punto de entrada de línea de comandos."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--destino",
        type=Path,
        default=DESTINO_POR_DEFECTO,
        help="Directorio donde escribir los WAV (por defecto, los assets del Recinto).",
    )
    opciones = parser.parse_args(argumentos)
    for ruta in generar(opciones.destino):
        print(f"generado {ruta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
