"""Modelos tipados e inmutables de configuración y padrón (WP-003).

Este módulo define las estructuras de datos que el backend entrega como
**snapshots congelados**: una vez cargados desde disco, ningún cambio
posterior de los archivos puede alterarlos (criterio CA-059 y RN-CON-07).

Se usan ``dataclasses`` con ``frozen=True`` y ``slots=True``:

- ``frozen`` impide reasignar atributos después de la construcción;
- ``slots`` evita agregar atributos dinámicos por error y ahorra memoria;
- las colecciones se guardan como ``tuple`` (inmutable) en lugar de ``list``,
  de modo que no exista ninguna referencia externa mutable que pueda alterar
  el snapshot por accidente.

Todos los identificadores propios están en español, sin tildes ni ``ñ``,
conforme a DEC-001. Los nombres de las claves del TOML canónico se conservan
en inglés porque forman parte del contrato de archivo aprobado en WP-003.
"""

from __future__ import annotations

from dataclasses import dataclass

NOMBRE_INSTITUCIONAL_NEUTRO = "Cuerpo legislativo"
"""Rótulo genérico que se muestra cuando la identidad configurada no está disponible.

No nombra ninguna institución concreta a propósito: es el texto que la Pantalla
del Recinto muestra mientras el backend todavía no pudo leer ``[institucion]``
(WP-084). Que sea genérico es parte del contrato —el sistema debe poder
instalarse en cualquier cuerpo legislativo— y por eso vive acá, junto al modelo
que lo usa como valor por omisión, y no disperso en cada punto de lectura.

La Pantalla del Recinto repite este mismo literal como último recurso, para el
instante previo al primer snapshot. ``tests/test_identidad_institucional.py``
comprueba que las dos copias digan exactamente lo mismo.
"""


@dataclass(frozen=True, slots=True)
class IdentidadInstitucional:
    """Nombre del cuerpo legislativo que opera esta instalación (WP-084).

    ``nombre`` es el texto que la Pantalla del Recinto muestra en su cabecera,
    exactamente como fue configurado en ``[institucion]``: no se recorta ni se
    normaliza, porque una instalación puede necesitar mayúsculas, artículos o
    puntuación propios.

    ``disponible=False`` significa que la sección no pudo interpretarse al
    arrancar el backend. En ese caso ``nombre`` vale
    :data:`NOMBRE_INSTITUCIONAL_NEUTRO` y ``motivo``/``detalle`` explican el
    problema, igual que hacen los sonidos del Recinto: una identidad mal escrita
    degrada un rótulo, no impide arrancar, votar ni auditar. La carga estricta
    del momento de preparar sí exige la sección.

    El valor por defecto —neutro y disponible— existe para que las pruebas que
    no ejercitan identidad construyan una ``ConfiguracionSistema`` sin
    declararla. El cargador canónico siempre lo completa con el nombre real.
    """

    nombre: str = NOMBRE_INSTITUCIONAL_NEUTRO
    disponible: bool = True
    motivo: str | None = None
    detalle: str | None = None


@dataclass(frozen=True, slots=True)
class SonidoRecinto:
    """Sonido configurado para un evento de la Pantalla del Recinto (WP-065).

    ``evento`` es el nombre canónico del hecho que dispara el sonido (por
    ejemplo ``sesion_abierta``); ``ruta`` es una referencia a un asset
    versionado y servido por la propia Pantalla del Recinto, nunca una ruta
    arbitraria del sistema de archivos; ``volumen`` es un entero de 0 a 100,
    donde 0 silencia el evento sin borrar su configuración.
    """

    evento: str
    ruta: str
    volumen: int


@dataclass(frozen=True, slots=True)
class ConfiguracionSonidosRecinto:
    """Conjunto congelado de sonidos del Recinto y su condición técnica (WP-065).

    ``disponible=False`` significa que la sección ``[sonidos]`` existe pero no
    pudo interpretarse al arrancar el backend. En ese caso la tupla viaja vacía
    y ``motivo``/``detalle`` explican el problema, igual que hace la biblioteca
    de mensajes de Apoyo Técnico: un archivo mal escrito degrada el audio, no
    impide votar ni auditar.

    El valor por defecto —vacío y disponible— existe para que las pruebas que
    no ejercitan audio construyan una ``ConfiguracionSistema`` sin declararlo.
    El cargador canónico siempre lo completa con los quince sonidos.
    """

    sonidos: tuple[SonidoRecinto, ...] = ()
    disponible: bool = True
    motivo: str | None = None
    detalle: str | None = None

    def buscar(self, evento: str) -> SonidoRecinto | None:
        """Devuelve el sonido de un evento, o ``None`` si no está configurado."""

        for sonido in self.sonidos:
            if sonido.evento == evento:
                return sonido
        return None


@dataclass(frozen=True, slots=True)
class ConfiguracionSistema:
    """Configuración funcional congelada cargada desde ``config/system.toml``.

    Representa la disposición de bancas, el quórum, los tipos de votación
    asistenciales, los temporizadores de los frontends y el directorio de
    registros CSV. Se construye una única vez por carga y no cambia aunque el
    archivo de disco sea modificado después (congelamiento de configuración).
    """

    quorum: int
    """Cantidad mínima de concejales presentes para sesionar."""

    filas_bancas: tuple[int, ...]
    """Disposición del recinto: cantidad de bancas de cada fila."""

    tipos_votacion: tuple[str, ...]
    """Tipos descriptivos de votación, en el orden configurado."""

    device_test_seconds: int | float
    """Duración congelada del test visual de un dispositivo.

    Es un temporizador independiente de los temporizadores de las pantallas.
    Puede ser entero o decimal, siempre que sea finito y no negativo (WP-086
    rechaza ``nan``, ``inf`` y ``-inf`` para todos los temporizadores). Al formar
    parte del snapshot inmutable, una pulsación nunca vuelve a leer el TOML para
    conocer su duración.
    """

    moderacion_revelado_votos_segundos: int | float
    """Retardo antes de revelar votos individuales en Moderación.

    Es un número finito no negativo (puede ser entero o decimal, p. ej.
    ``0.5``); se conserva el tipo que vino en el archivo: un ``4`` sigue siendo
    ``int`` y un ``4.5`` queda como ``float``, sin conversión silenciosa.
    """

    recinto_cuenta_regresiva_inicial_segundos: int | float
    """Cuenta regresiva/efecto visual inicial de votación en el Recinto.

    Número finito no negativo con la misma semántica de tipo que el retardo de
    Moderación: entero o decimal, sin conversión silenciosa.
    """

    recinto_resultado_publico_segundos: int | float
    """Tiempo de permanencia del resultado en la pantalla pública.

    Número finito no negativo (entero o decimal), sin conversión silenciosa.
    """

    directorio_registros: str
    """Directorio donde se escribirán los CSV de auditoría en el futuro."""

    directorio_copia_registros: str | None = None
    """Directorio externo opcional donde replicar el conjunto cerrado (WP-085).

    ``None`` significa que ``paths.logs_copy_dir`` no aparece en el archivo: al
    cerrar la sesión no se intenta ningún acceso externo y Moderación no muestra
    aviso alguno. Un texto significa que la instalación declaró un destino y
    quiere la copia.

    SIS-Leg lo interpreta como una **ruta de sistema de archivos ya montada** por
    el sistema operativo. El backend no implementa cliente SMB ni NFS, no guarda
    credenciales y no monta nada: si la ruta no está disponible, la copia falla y
    se informa, pero el cierre institucional ya quedó persistido localmente.

    El valor por omisión ``None`` mantiene compatible la construcción directa de
    ``ConfiguracionSistema`` en las pruebas anteriores a este WP.
    """

    sonidos_recinto: ConfiguracionSonidosRecinto = ConfiguracionSonidosRecinto()
    """Sonidos configurados para la Pantalla del Recinto (WP-065).

    Forman parte del mismo archivo y del mismo snapshot congelado que el resto
    de la configuración, de modo que una sección ``[sonidos]`` inválida impide
    preparar el recinto igual que un ``quorum`` inválido. La disponibilidad
    permanente que exige WP-065 —incluso en ``SIN_PREPARAR``— se resuelve
    releyendo el archivo al arrancar el proceso, no relajando este
    congelamiento.
    """

    identidad_institucional: IdentidadInstitucional = IdentidadInstitucional()
    """Nombre del cuerpo legislativo que opera esta instalación (WP-084).

    Viaja en el mismo archivo y en el mismo snapshot congelado que el resto de
    la configuración, de modo que una sección ``[institucion]`` ausente o
    inválida impide preparar el recinto igual que un ``quorum`` inválido. La
    disponibilidad permanente que exige el WP —el nombre también se ve en
    ``SIN_PREPARAR``— se resuelve releyendo el archivo al arrancar el proceso,
    no relajando este congelamiento.
    """

    @property
    def capacidad_total(self) -> int:
        """Cantidad total de bancas del recinto: ``sum(room.rows)``.

        Es la capacidad contra la cual se valida la cantidad exacta de
        concejales del padrón (RN-CON-04).
        """
        return sum(self.filas_bancas)


@dataclass(frozen=True, slots=True)
class Concejal:
    """Datos base congelados de un concejal del padrón (RN-CON-01 a RN-CON-05).

    El DNI es el identificador primario (se conserva como texto, porque es la
    identidad y no se realizan operaciones aritméticas con él). ``bloque``
    puede quedar vacío; banca y dispositivo de votación son asociaciones
    únicas dentro del padrón. ``ruta_imagen`` es una ruta interna del propio
    sistema: no se hardcodea imagen por número de banca (RN-CON-05).
    """

    dni: str
    nombre: str
    apellido: str
    bloque: str
    banca: int
    dispositivo_votacion: str
    ruta_imagen: str


@dataclass(frozen=True, slots=True)
class Padron:
    """Padrón completo congelado, en el orden de las filas del CSV.

    Contiene la secuencia de concejales que una futura preparación (WP-005)
    utilizará como base. Al igual que la configuración, una vez cargado no
    cambia aunque el archivo de disco sea reemplazado.
    """

    concejales: tuple[Concejal, ...]
    """Concejales cargados, en el orden del archivo de padrón."""
