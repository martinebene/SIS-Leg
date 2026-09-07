"""Auditoría de referencias al nombre legado del proyecto.

WP-077 renombró la identidad técnica de `Botonera2` a `SIS-Leg`. El riesgo permanente
después de un cambio así no es el estado del día del corte, sino la reintroducción
silenciosa del nombre viejo: alguien copia un fragmento antiguo, restaura un archivo de
una rama vieja o escribe una ruta de memoria, y la identidad vuelve a quedar mezclada.

Esta auditoría recorre todos los archivos de texto versionados y falla si el nombre legado
aparece fuera de una excepción explícita. Hay exactamente dos clases de excepción, y ninguna
de las dos es «excluir un directorio».

**Allowlist por ruta y conteo exacto.** Es la política por defecto y cubre archivos cuyo
contenido histórico ya está congelado: contratos de WP cerrados, pruebas de regresión que
usan el literal como valor bajo prueba, el manual y esta misma herramienta. Cada entrada
declara la ruta, cuántas ocurrencias se esperan allí y por qué son legítimas. El conteo es
parte del contrato: si un archivo permitido gana una ocurrencia nueva, la auditoría falla
igual que si el nombre apareciera en un archivo prohibido; y si pierde ocurrencias, también
falla, porque significa que la allowlist quedó desactualizada y está tapando más de lo que
hoy necesita cubrir.

**Registros históricos vivos.** Unos pocos documentos existen justamente para acumular
trazabilidad y siguen creciendo después del corte de identidad. `docs/implementation/PLAN.md`
es el caso claro: cada cierre de Work Package puede necesitar contar qué pasó con el nombre
o las rutas anteriores. Exigirles un conteo exacto convierte el gate en un obstáculo que se
rompe solo, y fue exactamente lo que ocurrió (hallazgo ASTRA-010, WP-079). Para esas rutas
--declaradas una por una, nunca por directorio-- la regla no es cuántas veces aparece el
nombre legado sino **cómo** aparece, y la pregunta se hace por cada mención y no por la línea
entera: una mención se admite si una flecha la conecta con la identidad vigente o si viene
precedida, en su misma cláusula y sin verbos en el medio, por una palabra completa del
vocabulario histórico. Una preposición suelta hacia SIS-Leg no basta, porque no distingue un
reemplazo de una conexión entre dos sistemas vivos. Nombrar SIS-Leg no alcanza por sí solo,
una palabra histórica que califique otra cosa tampoco, y las raíces sueltas quedaron
descartadas para que `delegado` no se lea como `legado`. El bloque de comentarios que precede
a los patrones detalla las dos formas admitidas y los nueve falsos negativos que obligaron a
endurecerlas. Una referencia
activa, como una ruta de instalación o un módulo, no cumple ninguna de las dos y sigue
fallando.

Ninguna de las dos políticas autoriza borrar o reescribir un hecho histórico para conseguir
verde: la historia es evidencia y el gate existe para protegerla, no para empujarla afuera.

Uso:

    uv run python scripts/auditar_identidad_legada.py

Devuelve 0 si la identidad está limpia y 1 con un informe accionable si no lo está.
`tests/test_auditoria_identidad_legada.py` ejecuta lo mismo dentro de la suite.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

RAIZ_REPOSITORIO = Path(__file__).resolve().parents[1]

# El nombre legado se busca sin distinguir mayúsculas y sin frontera final, para que
# `botonera2`, `Botonera2`, `BOTONERA2_SHA`, `@botonera2/api-client`, `botonera2_backend` y
# `/opt/botonera2` cuenten igual. Importa que el `2` sea obligatorio: `martinebene/Botonera`
# es otro repositorio, el sistema histórico en producción, y `botonera` a secas es el nombre
# común del dispositivo físico que usan los concejales. Ninguno de los dos se renombra.
PATRON_LEGADO = re.compile(r"botonera2", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ReferenciaPermitida:
    """Una ruta que puede nombrar la identidad legada, y bajo qué condiciones.

    `ocurrencias` es la cantidad exacta que se espera encontrar hoy. `motivo` explica por
    qué reescribirlas sería incorrecto; sin ese motivo la entrada no debería existir.
    """

    ruta: str
    ocurrencias: int
    motivo: str


# Categoría A - documentación que existe para explicar la migración. Sin el nombre viejo
# estos archivos no cumplirían su función.
DOCUMENTACION_DE_MIGRACION = (
    ReferenciaPermitida(
        "docs/NOTA-LEGADO-BOTONERA2.md",
        26,
        "Nota canónica de legado: traduce el nombre histórico al vigente.",
    ),
    ReferenciaPermitida(
        "docs/MIGRACION-A-SIS-LEG.md",
        38,
        "Runbook de migración: opera sobre rutas, unidades y usuarios anteriores.",
    ),
    ReferenciaPermitida(
        "docs/work-packages/WP-077.md",
        29,
        "Contrato versionado del propio renombrado; define qué se sustituye por qué.",
    ),
    ReferenciaPermitida(
        "manual/index.html",
        2,
        "Apartado 12.7: explica a quien opera cómo migrar la instalación anterior.",
    ),
    ReferenciaPermitida(
        "README.md",
        2,
        "Presentación del proyecto: nombra el nombre histórico y remite a la nota de legado.",
    ),
    ReferenciaPermitida(
        "docs/07-configuracion-datos-y-assets.md",
        2,
        "Reglas de marca: distingue identidad vigente de nombre histórico.",
    ),
    ReferenciaPermitida(
        "AGENTS.md",
        2,
        "Autoridad documental: remite a la nota de legado y a esta auditoría.",
    ),
)

# Categoría B - enunciados históricos. Documentan que la marca vieja fue retirada; cambiar
# el nombre convertiría una afirmación verdadera sobre el pasado en una falsa.
ENUNCIADOS_HISTORICOS = (
    ReferenciaPermitida(
        "docs/work-packages/WP-036.md",
        2,
        "Criterio cerrado: la cabecera de Moderación dejó de mostrar el distintivo legado.",
    ),
    ReferenciaPermitida(
        "docs/work-packages/WP-059.md",
        2,
        "Criterio cerrado: la cabecera de Apoyo Técnico dejó de mostrar la marca legada.",
    ),
    ReferenciaPermitida(
        "docs/work-packages/WP-062.md",
        5,
        "Contrato que sustituyó la marca visible legada; describe el estado previo.",
    ),
    ReferenciaPermitida(
        "packages/frontend-shared/src/carga_inicial.html",
        1,
        "Comentario que explica qué palabra reemplazó el logo en la carga inicial.",
    ),
)

# Categoría C - pruebas de regresión que verifican la ausencia de la marca legada. El
# literal es el valor bajo prueba: sustituirlo dejaría el test comprobando otra cosa.
PRUEBAS_DE_AUSENCIA = (
    ReferenciaPermitida(
        "apps/recinto/tests/identidad_sisleg_wp062.test.ts",
        1,
        "Comprueba que la Pantalla del Recinto no muestre la marca legada.",
    ),
    ReferenciaPermitida(
        "apps/tecnico/tests/tecnico_wp059.test.ts",
        4,
        "Comprueba que la cabecera de Apoyo Técnico no muestre la marca legada.",
    ),
    ReferenciaPermitida(
        "packages/frontend-shared/tests/identidad_sisleg_wp062.test.ts",
        3,
        "Comprueba que la carga inicial no muestre la marca legada.",
    ),
    ReferenciaPermitida(
        "tests/playwright/apoyo_tecnico_wp059.spec.ts",
        1,
        "Comprobación en navegador de la cabecera de Apoyo Técnico.",
    ),
    ReferenciaPermitida(
        "tests/playwright/identidad_sisleg_wp062.spec.ts",
        1,
        "Comprobación en navegador del indicador de carga inicial.",
    ),
    ReferenciaPermitida(
        "tests/playwright/shell_moderacion.spec.ts",
        3,
        "Comprobación en navegador de la cabecera de Moderación.",
    ),
    ReferenciaPermitida(
        "tests/test_manual_usuario.py",
        1,
        "Acota el nombre legado del manual al apartado de migración.",
    ),
)

# Categoría D - la auditoría misma y su contrato: necesitan el literal para poder buscarlo
# y para poder describir qué se sigue prohibiendo.
HERRAMIENTAS_DE_AUDITORIA = (
    ReferenciaPermitida(
        "scripts/auditar_identidad_legada.py",
        9,
        "Patrón de búsqueda, allowlist y mensajes de esta misma auditoría.",
    ),
    ReferenciaPermitida(
        "docs/work-packages/WP-079.md",
        1,
        "Contrato versionado de esta política; nombra el literal que debe seguir fallando.",
    ),
    ReferenciaPermitida(
        "tests/test_auditoria_identidad_legada.py",
        49,
        "Prueba que la auditoría detecte una reintroducción del nombre legado.",
    ),
)

ALLOWLIST: tuple[ReferenciaPermitida, ...] = (
    DOCUMENTACION_DE_MIGRACION
    + ENUNCIADOS_HISTORICOS
    + PRUEBAS_DE_AUSENCIA
    + HERRAMIENTAS_DE_AUDITORIA
)


@dataclass(frozen=True, slots=True)
class RegistroHistoricoVivo:
    """Una ruta documental que sigue acumulando trazabilidad sobre el pasado.

    A diferencia de `ReferenciaPermitida`, aquí no se declara un conteo: el documento está
    vivo y su cantidad de menciones cambia de forma legítima cada vez que se cierra un Work
    Package. Lo que sí se exige es la forma de cada mención, según la regla que implementa
    `linea_tiene_contexto_historico`. `motivo` explica por qué esta ruta concreta necesita
    esa política y no la del conteo exacto.
    """

    ruta: str
    motivo: str


# Cómo se reconoce un enunciado sobre el pasado.
#
# Esta regla se endureció dos veces porque las dos primeras versiones dejaban pasar
# referencias activas, que es el error que de verdad importa aquí: un falso positivo molesta,
# un falso negativo desarma el gate.
#
# La primera versión comparaba subcadenas contra un vocabulario de raíces, y `delegado`
# activaba `legad`. La segunda pasó a palabras completas pero seguía preguntando por la
# *línea*: bastaba que la palabra apareciera en cualquier parte, aunque no dijera nada sobre
# la mención. Estas seis formas tienen que fallar, y hay una prueba exacta para cada una:
#
#     El concejal delegado solicitó acceso a /opt/<legado>
#     Como se indicó en la sección anterior, el servicio arranca con /opt/<legado>/bin/start
#     Para desplegar sis-leg, ejecutar /opt/<legado>/bin/start
#     Para migrar la base de datos, ejecutar /opt/<legado>/bin/start
#     El sistema legado de expedientes usa /opt/<legado>/bin/start
#     Durante la migración de usuarios, ejecutar /opt/<legado>/bin/start
#     Usar <legado> por compatibilidad con SIS-Leg
#     Conectar <legado> a SIS-Leg
#     Redirigir <legado> hacia SIS-Leg
#
# Las tres del medio comparten la misma raíz: la palabra histórica califica otra cosa (una
# base de datos, un sistema de expedientes, unos usuarios) y la ruta legada es el objeto de
# un verbo activo. Las tres últimas comparten otra: nombran las dos identidades unidas por
# una preposición, pero describen dos sistemas conviviendo, no uno reemplazado por el otro.
#
# Por eso ahora la pregunta no es «¿esta línea habla del pasado?» sino «¿**esta mención**
# viene enmarcada?». La evaluación es por ocurrencia y ocurre dentro de dos límites:
#
# - el **segmento**: la porción de la línea entre los signos de puntuación fuerte que rodean
#   a la mención. Una coma o un punto y coma cortan el segmento, de modo que un marco que
#   vive en otra cláusula ya no alcanza. Eso solo descarta tres de los seis contraejemplos;
# - el **token**: la mención se expande hasta abarcar la ruta completa que la contiene, para
#   que `/workspace/<legado>` cuente como una sola palabra y no como tres.
#
# Dentro de esos límites se aceptan dos formas, y basta con una:
#
# 1. **transición de identidad**: justo después de la mención aparece una flecha (`->`,
#    `-->`, `=>`, `→`) y la identidad vigente, como en «`/opt/<legado>` -> `/opt/sis-leg`».
#    Sólo la flecha, porque una preposición suelta no distingue un reemplazo de una
#    conexión entre dos sistemas vivos. El orden también es parte de la regla: nombrar la
#    identidad vigente *antes* del literal no alcanza, porque eso es justamente lo que hace
#    una instrucción de despliegue que menciona el proyecto;
# 2. **calificador ligado**: la mención viene precedida por una palabra completa del
#    vocabulario histórico, separada de ella a lo sumo por una palabra libre y una
#    preposición de pertenencia (`de`, `del`, `en`). Lo decisivo es qué hay pegado a la
#    mención: o el calificador mismo («Renombrar <legado>»), o esa preposición
#    («un registro metadata legado vacío de `/workspace/<legado>`»). Un verbo pegado a la
#    mención («usa /opt/<legado>», «arranca con /opt/<legado>») nunca encaja, que es lo que
#    descarta los otros tres contraejemplos.
#
# Ampliar cualquiera de las dos formas, el vocabulario o las preposiciones exige la misma
# justificación explícita que agregar una entrada a la allowlist.

# La identidad vigente, escrita como aparece realmente: `SIS-Leg`, `sis-leg`, `sis_leg`,
# `sisleg`. Se usa sólo dentro de la transición, nunca como marcador por sí misma.
_IDENTIDAD_VIGENTE = r"sis[-_ ]?leg"

# Puntuación que corta el segmento. La barra vertical está incluida porque el PLAN registra
# los WPs en tablas Markdown y cada celda es una afirmación independiente.
PATRON_PUNTUACION_DE_CORTE = re.compile(r"[.;,:!?|()\[\]]")

# Caracteres que delimitan el token de la mención. Todo lo demás (barras, guiones, puntos de
# una ruta) forma parte de ella: `/workspace/<legado>` es una palabra sola, no tres.
SEPARADORES_DE_TOKEN = frozenset(" \t`\"'()[]{}<>,;")

# Forma 1, aplicada al texto que sigue a la mención dentro de su segmento. El conector tiene
# que ser una flecha, y nada más.
#
# Al principio esta forma también aceptaba las preposiciones `a`, `hacia` y `por`, y eso
# volvía a abrir el gate: «Conectar <legado> a SIS-Leg», «Redirigir <legado> hacia SIS-Leg» y
# «Usar <legado> por compatibilidad con SIS-Leg» son instrucciones activas que describen dos
# sistemas conviviendo, no una identidad que fue reemplazada por otra. Una preposición sola
# no distingue «esto pasó a ser aquello» de «esto se conecta con aquello».
#
# La flecha sí lo distingue, porque en este repositorio se usa exactamente para eso: anotar
# que algo dejó de estar en un lado y pasó al otro. Las transiciones narradas con palabras
# siguen siendo válidas, pero por la otra forma: necesitan un calificador histórico ligado a
# la mención, como en «Renombrar <legado> a SIS-Leg» o «migración física de /opt/<legado> a
# /opt/sis-leg». Es decir, la palabra sigue alcanzando cuando el texto además dice que está
# hablando del pasado.
#
# Las cotas son perezosas y cortas para que la transición sea una frase y no dos ideas que
# casualmente conviven en el mismo segmento.
PATRON_TRANSICION_DESDE_LA_MENCION = re.compile(
    rf"^[^\n]{{0,40}}?\s*(?:->|-->|=>|→)\s*[^\n]{{0,25}}?{_IDENTIDAD_VIGENTE}",
    re.IGNORECASE,
)

# Vocabulario histórico cerrado, en palabras completas. Las variantes con y sin tilde se
# listan por separado porque `\b` trata la vocal acentuada como otra letra: `\bhistorico\b`
# no encuentra `histórico`.
PALABRAS_DE_CONTEXTO_HISTORICO: tuple[str, ...] = (
    "legado",
    "legada",
    "legados",
    "legadas",
    "historico",
    "historica",
    "historicos",
    "historicas",
    "histórico",
    "histórica",
    "históricos",
    "históricas",
    "migracion",
    "migración",
    "migraciones",
    "migrar",
    "migrado",
    "migrada",
    "migrados",
    "migradas",
    "renombrar",
    "renombrado",
    "renombrada",
    "renombrados",
    "renombradas",
    "renombro",
    "renombró",
    "anterior",
    "anteriores",
)

# Preposiciones de pertenencia o ubicación admitidas entre el calificador y la mención. La
# lista es mínima a propósito: `con`, `para` o `a` introducen complementos de verbos activos
# («arranca con /opt/<legado>»), así que admitirlas volvería a abrir el agujero.
PREPOSICIONES_DE_PERTENENCIA: tuple[str, ...] = ("de", "del", "en")

# Forma 2, aplicada al texto que precede a la mención dentro de su segmento y que termina
# justo donde empieza su token. Lo decisivo es qué palabra queda pegada a la mención, y sólo
# hay dos posibilidades admitidas:
#
# - el calificador mismo, sin nada en medio: «Renombrar <legado>»;
# - una preposición de pertenencia, con a lo sumo una palabra libre entre ella y el
#   calificador: «un registro metadata legado vacío de `/workspace/<legado>`».
#
# Cualquier otra cosa pegada a la mención la descalifica, y eso incluye justamente el caso
# que hay que atrapar: un verbo activo, como en «el sistema legado usa /opt/<legado>» o «el
# sistema legado arranca con /opt/<legado>». Ahí la palabra histórica califica al sistema,
# no a la ruta, y la ruta es el objeto de una acción presente.
_CALIFICADOR = r"\b(?:" + "|".join(PALABRAS_DE_CONTEXTO_HISTORICO) + r")\b"
_PREPOSICION = r"(?:" + "|".join(PREPOSICIONES_DE_PERTENENCIA) + r")"

PATRON_CALIFICADOR_LIGADO = re.compile(
    rf"(?:{_CALIFICADOR}(?:\s+\w+)?\s+{_PREPOSICION}|{_CALIFICADOR})\W*$",
    re.IGNORECASE,
)

# Registros históricos vivos declarados. La lista es corta a propósito: no es un mecanismo
# para excluir documentación, es una excepción por ruta con una regla de contenido propia.
REGISTROS_HISTORICOS_VIVOS: tuple[RegistroHistoricoVivo, ...] = (
    RegistroHistoricoVivo(
        "docs/implementation/PLAN.md",
        "Bitácora viva del plan: cada cierre de WP puede narrar qué pasó con el nombre o "
        "las rutas anteriores, así que su cantidad de menciones crece de forma legítima.",
    ),
)


def listar_archivos_versionados() -> list[str]:
    """Devuelve las rutas versionadas, que son el universo auditable.

    Se usa `git ls-files` en lugar de recorrer el disco para no auditar artefactos de
    build, dependencias instaladas ni configuración runtime local ignorada.
    """

    salida = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=RAIZ_REPOSITORIO,
        capture_output=True,
        text=True,
        check=True,
    )
    return [ruta for ruta in salida.stdout.split("\0") if ruta]


def contar_ocurrencias(ruta_relativa: str) -> int:
    """Cuenta apariciones del nombre legado en un archivo de texto.

    Los archivos binarios (imágenes, sonidos) se saltean devolviendo 0: no contienen texto
    auditable y decodificarlos sólo produciría ruido.
    """

    ruta = RAIZ_REPOSITORIO / ruta_relativa
    try:
        contenido = ruta.read_text(encoding="utf-8")
    except (UnicodeDecodeError, FileNotFoundError):
        return 0
    return len(PATRON_LEGADO.findall(contenido))


def leer_lineas(ruta_relativa: str) -> list[str]:
    """Devuelve las líneas de un archivo de texto, o ninguna si no se puede leer.

    Comparte el criterio de `contar_ocurrencias`: un binario o una ruta inexistente no son
    un error de auditoría, simplemente no aportan texto que revisar.
    """

    ruta = RAIZ_REPOSITORIO / ruta_relativa
    try:
        return ruta.read_text(encoding="utf-8").splitlines()
    except (UnicodeDecodeError, FileNotFoundError):
        return []


def _segmento_de_la_mencion(linea: str, comienzo: int, fin: int) -> tuple[str, int]:
    """Recorta la cláusula en la que vive una mención y dice dónde empieza dentro de ella.

    El segmento va desde la puntuación fuerte anterior más cercana hasta la siguiente. Sirve
    para que un marco histórico que está en otra cláusula deje de contar: en «Durante la
    migración de usuarios, ejecutar /opt/<legado>/bin/start» la coma separa el marco de la
    mención, y la instrucción de la derecha queda sola, que es lo correcto.

    Devuelve el texto del segmento y la posición de la mención relativa a él.
    """

    inicio_segmento = 0
    for corte in PATRON_PUNTUACION_DE_CORTE.finditer(linea, 0, comienzo):
        inicio_segmento = corte.end()

    corte_posterior = PATRON_PUNTUACION_DE_CORTE.search(linea, fin)
    fin_segmento = corte_posterior.start() if corte_posterior else len(linea)

    return linea[inicio_segmento:fin_segmento], comienzo - inicio_segmento


def _inicio_del_token(texto: str, posicion: int) -> int:
    """Retrocede desde una mención hasta el comienzo de la palabra que la contiene.

    `/workspace/<legado>` es una sola palabra para esta auditoría, no tres. Sin esta
    expansión las barras de una ruta contarían como separadores y el calificador quedaría
    artificialmente lejos de la mención.
    """

    while posicion > 0 and texto[posicion - 1] not in SEPARADORES_DE_TOKEN:
        posicion -= 1
    return posicion


def _fin_del_token(texto: str, posicion: int) -> int:
    """Avanza hasta el final de la palabra que contiene la mención. Espejo del anterior."""

    while posicion < len(texto) and texto[posicion] not in SEPARADORES_DE_TOKEN:
        posicion += 1
    return posicion


def mencion_tiene_marco_historico(linea: str, comienzo: int, fin: int) -> bool:
    """Decide si *una* mención concreta viene enmarcada como enunciado sobre el pasado.

    `comienzo` y `fin` son las posiciones del literal legado dentro de `linea`. La mención se
    juzga dentro de su segmento y por su vecindad inmediata, nunca por lo que diga el resto
    de la línea. Devuelve `True` si se cumple la transición de identidad o el calificador
    ligado descritos arriba; basta con una de las dos.
    """

    segmento, posicion = _segmento_de_la_mencion(linea, comienzo, fin)
    if not segmento:
        return False

    posterior = segmento[posicion + (fin - comienzo) :]
    if PATRON_TRANSICION_DESDE_LA_MENCION.search(posterior) is not None:
        return True

    anterior = segmento[: _inicio_del_token(segmento, posicion)]
    return PATRON_CALIFICADOR_LIGADO.search(anterior) is not None


def menciones_sin_marco_historico(linea: str) -> list[tuple[int, str]]:
    """Devuelve las menciones de la línea que no logran justificarse.

    Cada elemento es la columna donde empieza la mención, contada desde 1 como la muestran
    los editores, y el token completo que la contiene. Se informa el token y no sólo el
    literal para que el mensaje de la CI muestre la ruta o el identificador real que hay que
    revisar.
    """

    sin_marco: list[tuple[int, str]] = []
    for aparicion in PATRON_LEGADO.finditer(linea):
        comienzo, fin = aparicion.start(), aparicion.end()
        if mencion_tiene_marco_historico(linea, comienzo, fin):
            continue
        inicio_token = _inicio_del_token(linea, comienzo)
        sin_marco.append((inicio_token + 1, linea[inicio_token : _fin_del_token(linea, fin)]))
    return sin_marco


def linea_tiene_contexto_historico(linea: str) -> bool:
    """Fachada de conveniencia: `True` si todas las menciones de la línea están enmarcadas.

    Una línea sin ninguna mención devuelve `True` de forma vacua, porque no hay nada que
    justificar. Existe sobre todo para que las pruebas puedan expresar un caso completo en
    una sola frase legible, mientras la auditoría real usa `menciones_sin_marco_historico`,
    que además dice dónde está el problema.
    """

    return not menciones_sin_marco_historico(linea)


def _revisar_registro_vivo(
    registro: RegistroHistoricoVivo,
    leer: Callable[[str], list[str]],
) -> list[str]:
    """Revisa un registro histórico vivo mención por mención y describe lo que no encaja.

    Devuelve un problema por cada mención del nombre legado que no logre justificarse. El
    mensaje incluye línea, columna y el token exacto, para que quien lea la CI vaya directo
    al lugar en vez de buscar el literal a mano dentro de un párrafo largo.
    """

    problemas: list[str] = []
    for numero, linea in enumerate(leer(registro.ruta), start=1):
        for columna, token in menciones_sin_marco_historico(linea):
            problemas.append(
                f"{registro.ruta}:{numero}:{columna}: la mención «{token}» no viene "
                "enmarcada como historia. Para ser admitida en este registro debe describir "
                "la transición con una flecha hacia la identidad vigente (por ejemplo "
                "«/opt/... -> /opt/sis-leg») o venir precedida, en la misma cláusula, por "
                "una palabra "
                "completa del vocabulario histórico (legado, histórico, migración, "
                "renombrar, anterior y sus variantes). Una palabra histórica suelta en otra "
                "parte de la línea no alcanza, y nombrar SIS-Leg tampoco."
            )
    return problemas


def auditar(
    *,
    archivos: Sequence[str] | None = None,
    permitidas: Sequence[ReferenciaPermitida] | None = None,
    contador: Callable[[str], int] | None = None,
    registros_vivos: Sequence[RegistroHistoricoVivo] | None = None,
    lector: Callable[[str], list[str]] | None = None,
) -> list[str]:
    """Compara el estado real del repositorio contra las dos políticas declaradas.

    Todos los parámetros existen para poder probar la auditoría con un repositorio
    sintético: por omisión mira los archivos versionados reales, la allowlist real, los
    registros vivos reales, el contador real y el lector real. Devuelve la lista de
    problemas encontrados, vacía si la identidad está limpia.

    Una ruta se clasifica en un único régimen. Si es registro histórico vivo se revisa línea
    por línea y no se le exige conteo; si está en la allowlist se le exige el conteo exacto;
    si no está en ninguna de las dos, cualquier ocurrencia es un problema.
    """

    entradas = tuple(ALLOWLIST if permitidas is None else permitidas)
    vivos = tuple(REGISTROS_HISTORICOS_VIVOS if registros_vivos is None else registros_vivos)
    rutas = listar_archivos_versionados() if archivos is None else list(archivos)
    contar = contar_ocurrencias if contador is None else contador
    leer = leer_lineas if lector is None else lector

    esperado = {entrada.ruta: entrada for entrada in entradas}
    vivos_por_ruta = {registro.ruta: registro for registro in vivos}
    problemas: list[str] = []

    for entrada in entradas:
        if archivos is None and not (RAIZ_REPOSITORIO / entrada.ruta).exists():
            problemas.append(
                f"{entrada.ruta}: la allowlist declara un archivo que ya no existe; "
                "quitá la entrada."
            )
        if not entrada.motivo.strip():
            problemas.append(f"{entrada.ruta}: la entrada de allowlist no declara motivo.")

    # Un registro vivo con conteo exacto sería contradictorio: las dos reglas se aplicarían
    # a la misma ruta y la primera anularía a la otra. Se detecta como error de política.
    for registro in vivos:
        if archivos is None and not (RAIZ_REPOSITORIO / registro.ruta).exists():
            problemas.append(
                f"{registro.ruta}: se declara registro histórico vivo un archivo que ya no "
                "existe; quitá la entrada."
            )
        if not registro.motivo.strip():
            problemas.append(f"{registro.ruta}: el registro histórico vivo no declara motivo.")
        if registro.ruta in esperado:
            problemas.append(
                f"{registro.ruta}: está declarada a la vez en la allowlist por conteo y "
                "como registro histórico vivo; elegí una sola política."
            )

    for ruta_relativa in rutas:
        registro = vivos_por_ruta.get(ruta_relativa)
        if registro is not None:
            problemas.extend(_revisar_registro_vivo(registro, leer))
            continue

        encontradas = contar(ruta_relativa)
        entrada = esperado.get(ruta_relativa)

        if entrada is None:
            if encontradas:
                problemas.append(
                    f"{ruta_relativa}: {encontradas} referencia(s) al nombre legado en un "
                    "archivo no permitido. Usá la identidad SIS-Leg o justificá la "
                    "excepción en la allowlist de esta auditoría."
                )
            continue

        if encontradas > entrada.ocurrencias:
            problemas.append(
                f"{ruta_relativa}: {encontradas} referencia(s) al nombre legado, se esperaban "
                f"{entrada.ocurrencias}. Motivo declarado: {entrada.motivo}"
            )
        elif encontradas < entrada.ocurrencias:
            problemas.append(
                f"{ruta_relativa}: quedan {encontradas} referencia(s) al nombre legado pero la "
                f"allowlist declara {entrada.ocurrencias}. Actualizá el conteo."
            )

    return problemas


def main() -> int:
    """Punto de entrada de línea de comandos."""

    problemas = auditar()
    if problemas:
        print("Auditoría de identidad legada: FALLA", file=sys.stderr)
        for problema in problemas:
            print(f"  - {problema}", file=sys.stderr)
        return 1

    permitidas = sum(entrada.ocurrencias for entrada in ALLOWLIST)
    print(
        "Auditoría de identidad legada OK: ninguna referencia activa al nombre anterior. "
        f"{permitidas} ocurrencia(s) históricas permitidas en {len(ALLOWLIST)} archivo(s) "
        f"con conteo exacto y {len(REGISTROS_HISTORICOS_VIVOS)} registro(s) histórico(s) "
        "vivo(s) revisado(s) mención por mención."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
