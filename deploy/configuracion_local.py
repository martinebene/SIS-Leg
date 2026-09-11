"""Contrato de configuración local: preservar, incorporar y detectar migraciones (WP-100).

¿Qué problema resuelve este módulo?
-----------------------------------

Una release de SIS-Leg **no es dueña** de la configuración institucional. El
padrón, el `system.toml`, el mapeo de botoneras y la biblioteca de mensajes de
Apoyo Técnico viven en `/opt/sis-leg/config/` y son el estado real de *esta*
instalación. Una actualización jamás debe copiarlos desde Git ni desde el
paquete: si lo hiciera, borraría trabajo humano que no está en ningún commit.

Pero hay un caso que sí puede aparecer en el futuro: que una release nueva
necesite un recurso local **que antes no existía**. Ese caso no puede
resolverse copiando `config/` completo, porque arrasaría con lo anterior.

Este módulo implementa la regla exacta:

1. un recurso **que ya existe** se preserva byte a byte y no se lo mira más;
2. un recurso **ausente** puede crearse sólo si la release declara para él una
   fuente de bootstrap segura, y se crea de forma atómica y add-only;
3. si la release nueva declara para un recurso existente un **schema distinto**
   del que declaraba la release en uso, eso es una migración: se aborta antes de
   tocar nada y se exige aprobación humana (HUMAN_GATE).

El contrato viaja dentro de la propia release
---------------------------------------------

El archivo `deploy/contrato_configuracion.json` está versionado en Git y se copia
dentro del paquete productivo junto al resto de `deploy/`. Eso significa que su
contenido queda inventariado y con checksum en `release.json`: un contrato
adulterado no sobrevive a las defensas que ya valida la herramienta de
despliegue. Comparar el contrato de la release nueva con el de la release activa
es, entonces, comparar dos documentos íntegros y firmados por su propio SHA.

Este módulo no importa `herramienta_despliegue` a propósito: la herramienta lo
usa a él, y mantener la dependencia en una sola dirección evita un import
circular y deja el planificador testeable de forma aislada.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

# Nombre canónico del contrato dentro de una release ya extraída. Es una ruta
# relativa POSIX porque así aparece también en el inventario de `release.json`.
RUTA_CONTRATO_EN_RELEASE = "deploy/contrato_configuracion.json"

FORMATO_CONTRATO = "sis-leg-configuracion"

# Versión de contrato que esta herramienta sabe interpretar. Una release futura
# que suba este número describe su configuración con reglas que este código no
# conoce: la conducta correcta es abortar, no adivinar.
VERSION_CONTRATO_SOPORTADA = 1

# Todo recurso declarado debe vivir bajo `config/`. La restricción es
# deliberadamente estrecha: el contrato administra configuración institucional,
# nunca releases, logs ni archivos de sistema.
PREFIJO_RUTA_LOCAL = "config"

TIPOS_RECURSO = ("archivo", "directorio")

# Acciones posibles del plan. Son cadenas y no un Enum para que el plan se
# serialice a JSON sin conversiones y se lea igual en la salida de la CLI.
ACCION_PRESERVAR = "PRESERVAR"
ACCION_CREAR = "CREAR"
ACCION_MIGRACION_REQUERIDA = "MIGRACION_REQUERIDA"


class ErrorConfiguracionLocal(RuntimeError):
    """Falla segura del contrato de configuración local.

    Se lanza tanto ante un contrato inválido como ante una migración detectada.
    En ambos casos la conducta esperada de quien la recibe es la misma: abortar
    sin haber modificado ningún archivo de configuración.
    """


@dataclass(frozen=True, slots=True)
class RecursoConfiguracion:
    """Un recurso local declarado por una release.

    Atributos:
        ruta_local: ruta relativa a la raíz de instalación (`/opt/sis-leg`),
            siempre bajo `config/`.
        tipo: ``"archivo"`` para un único archivo, ``"directorio"`` para un
            conjunto de archivos que se completa entrada por entrada.
        schema: identificador opaco del formato/semántica esperado. No se
            interpreta: sólo se compara contra el que declaraba la release
            anterior. Cambiarlo es la forma explícita de anunciar una migración.
        bootstrap: ruta relativa **dentro de la release** con el contenido por
            defecto, o ``None`` cuando el recurso debe ser provisionado por el
            operador y jamás creado por una actualización.
        usuario, grupo, modo: ownership y permisos previstos para lo que se
            cree. Sólo son obligatorios cuando ``bootstrap`` no es ``None``,
            porque un recurso que nunca se crea no necesita declararlos.
        descripcion: texto corto para la salida diagnóstica.
    """

    ruta_local: str
    tipo: str
    schema: str
    bootstrap: str | None
    descripcion: str
    usuario: str | None = None
    grupo: str | None = None
    modo: int | None = None


@dataclass(frozen=True, slots=True)
class EntradaPlanConfiguracion:
    """Qué decidió el planificador para un recurso concreto.

    Atributos:
        recurso: el recurso tal como lo declara la release nueva.
        accion: ``PRESERVAR``, ``CREAR`` o ``MIGRACION_REQUERIDA``.
        motivo: explicación accionable, pensada para que un operador entienda
            sin leer el código por qué la actualización se detuvo o qué se creó.
    """

    recurso: RecursoConfiguracion
    accion: str
    motivo: str


def _validar_ruta_local(ruta: str) -> PurePosixPath:
    """Rechaza rutas ambiguas antes de tocar el filesystem.

    Una ruta de contrato nunca debe poder salirse de `config/`. Se validan la
    forma normalizada, la ausencia de componentes `.`/`..`, la ausencia de raíz
    absoluta y el prefijo obligatorio.
    """

    if not ruta or ruta.startswith("/"):
        raise ErrorConfiguracionLocal(f"El contrato declara una ruta local inválida: {ruta!r}")
    camino = PurePosixPath(ruta)
    if camino.is_absolute() or camino.as_posix() != ruta:
        raise ErrorConfiguracionLocal(f"El contrato declara una ruta no normalizada: {ruta!r}")
    if any(parte in {"", ".", ".."} for parte in camino.parts):
        raise ErrorConfiguracionLocal(f"El contrato declara una ruta con traversal: {ruta!r}")
    if camino.parts[0] != PREFIJO_RUTA_LOCAL or len(camino.parts) < 2:
        raise ErrorConfiguracionLocal(
            f"El contrato sólo puede administrar rutas bajo {PREFIJO_RUTA_LOCAL}/: {ruta!r}"
        )
    return camino


def _validar_ruta_bootstrap(ruta: str) -> PurePosixPath:
    """Valida la fuente de bootstrap, que vive dentro de la release extraída."""

    if not ruta or ruta.startswith("/"):
        raise ErrorConfiguracionLocal(f"El contrato declara un bootstrap inválido: {ruta!r}")
    camino = PurePosixPath(ruta)
    if camino.is_absolute() or camino.as_posix() != ruta:
        raise ErrorConfiguracionLocal(f"El contrato declara un bootstrap no normalizado: {ruta!r}")
    if any(parte in {"", ".", ".."} for parte in camino.parts):
        raise ErrorConfiguracionLocal(f"El contrato declara un bootstrap con traversal: {ruta!r}")
    return camino


def _leer_modo(valor: Any, ruta_local: str) -> int:
    """Convierte el modo declarado en octal textual a un entero POSIX.

    Se exige la forma ``"0640"`` y no un entero para que el contrato no dependa
    de que quien lo escribe recuerde que ``640`` decimal no es ``0o640``.
    """

    if not isinstance(valor, str) or not valor.startswith("0") or len(valor) != 4:
        raise ErrorConfiguracionLocal(
            f"El modo de {ruta_local} debe declararse como octal de cuatro dígitos, por "
            f'ejemplo "0640".'
        )
    try:
        modo = int(valor, 8)
    except ValueError as error:
        raise ErrorConfiguracionLocal(f"El modo de {ruta_local} no es octal válido.") from error
    if modo < 0 or modo > 0o7777:
        raise ErrorConfiguracionLocal(f"El modo de {ruta_local} está fuera de rango.")
    return modo


def interpretar_contrato(datos: Mapping[str, Any], origen: str) -> tuple[RecursoConfiguracion, ...]:
    """Valida un contrato ya parseado y lo convierte en recursos tipados.

    Entradas:
        datos: objeto JSON del contrato.
        origen: descripción legible del archivo, usada sólo en los mensajes de
            error para que el operador sepa cuál de los dos contratos falló.

    Resultado: la tupla de recursos, en el orden declarado.

    Errores:
        ErrorConfiguracionLocal ante formato, versión, tipo, ruta, duplicado o
        permisos mal declarados. No existe modo tolerante: un contrato que no se
        entiende por completo no habilita ninguna mutación.
    """

    if datos.get("formato") != FORMATO_CONTRATO:
        raise ErrorConfiguracionLocal(f"{origen} no declara el formato {FORMATO_CONTRATO}.")
    version = datos.get("version_contrato")
    if version != VERSION_CONTRATO_SOPORTADA:
        raise ErrorConfiguracionLocal(
            f"{origen} declara version_contrato={version!r} y esta herramienta soporta "
            f"{VERSION_CONTRATO_SOPORTADA}. Se requiere aprobación humana (HUMAN_GATE) antes "
            "de continuar."
        )
    recursos_crudos = datos.get("recursos")
    if not isinstance(recursos_crudos, list):
        raise ErrorConfiguracionLocal(f"{origen} no contiene una lista de recursos.")

    recursos: list[RecursoConfiguracion] = []
    vistos: set[str] = set()
    for entrada in cast(list[Any], recursos_crudos):
        if not isinstance(entrada, dict):
            raise ErrorConfiguracionLocal(f"{origen} contiene un recurso que no es un objeto.")
        entrada_tipada = cast(dict[str, Any], entrada)
        ruta_local = entrada_tipada.get("ruta_local")
        if not isinstance(ruta_local, str):
            raise ErrorConfiguracionLocal(f"{origen} contiene un recurso sin ruta_local textual.")
        _validar_ruta_local(ruta_local)
        if ruta_local in vistos:
            raise ErrorConfiguracionLocal(f"{origen} declara dos veces el recurso {ruta_local}.")
        vistos.add(ruta_local)

        tipo = entrada_tipada.get("tipo")
        if tipo not in TIPOS_RECURSO:
            raise ErrorConfiguracionLocal(
                f"{origen} declara un tipo no soportado para {ruta_local}: {tipo!r}"
            )
        schema = entrada_tipada.get("schema")
        if not isinstance(schema, str) or not schema:
            raise ErrorConfiguracionLocal(f"{origen} no declara schema para {ruta_local}.")
        descripcion = entrada_tipada.get("descripcion")
        if not isinstance(descripcion, str) or not descripcion:
            raise ErrorConfiguracionLocal(f"{origen} no declara descripción para {ruta_local}.")

        bootstrap = entrada_tipada.get("bootstrap")
        usuario: str | None = None
        grupo: str | None = None
        modo: int | None = None
        if bootstrap is not None:
            if not isinstance(bootstrap, str):
                raise ErrorConfiguracionLocal(
                    f"{origen} declara un bootstrap no textual para {ruta_local}."
                )
            _validar_ruta_bootstrap(bootstrap)
            # Un recurso que la actualización puede crear necesita ownership y
            # modo previstos: crear un archivo institucional con permisos por
            # defecto sería una regresión de seguridad silenciosa.
            usuario = entrada_tipada.get("usuario")
            grupo = entrada_tipada.get("grupo")
            if not isinstance(usuario, str) or not isinstance(grupo, str):
                raise ErrorConfiguracionLocal(
                    f"{origen} declara bootstrap para {ruta_local} sin usuario/grupo previstos."
                )
            modo = _leer_modo(entrada_tipada.get("modo"), ruta_local)

        recursos.append(
            RecursoConfiguracion(
                ruta_local=ruta_local,
                tipo=tipo,
                schema=schema,
                bootstrap=bootstrap,
                descripcion=descripcion,
                usuario=usuario,
                grupo=grupo,
                modo=modo,
            )
        )

    if not recursos:
        raise ErrorConfiguracionLocal(f"{origen} no declara ningún recurso de configuración.")
    return tuple(recursos)


def leer_contrato_de_release(release: Path) -> tuple[RecursoConfiguracion, ...]:
    """Lee el contrato que viaja dentro de una release ya extraída.

    Entradas:
        release: raíz de la release (`/opt/sis-leg/releases/<sha>`).

    Resultado: los recursos declarados por esa release.

    Errores:
        ErrorConfiguracionLocal si el archivo falta, no es un archivo regular,
        no es JSON válido o el contrato es inválido. Una release sin contrato no
        puede activarse: no habría forma de decidir si hace falta una migración.
    """

    ruta = release / RUTA_CONTRATO_EN_RELEASE
    if not ruta.is_file():
        raise ErrorConfiguracionLocal(
            f"La release no incluye {RUTA_CONTRATO_EN_RELEASE}; no se puede evaluar la "
            "compatibilidad de la configuración local."
        )
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ErrorConfiguracionLocal(f"No se pudo leer {ruta}: {error}") from error
    if not isinstance(datos, dict):
        raise ErrorConfiguracionLocal(f"{ruta} no contiene un objeto JSON.")
    return interpretar_contrato(cast(dict[str, Any], datos), str(ruta))


def _existe_recurso(raiz: Path, recurso: RecursoConfiguracion) -> bool:
    """Decide si el recurso ya está provisionado en esta instalación.

    Un directorio cuenta como existente apenas está creado, aunque esté vacío:
    el operador puede haberlo creado a propósito para llenarlo después, y esa
    decisión también debe preservarse.
    """

    ruta = raiz / recurso.ruta_local
    # ``exists`` sigue symlinks; se comprueba también ``is_symlink`` para que un
    # enlace roto cuente como existente y nunca se lo reemplace por un archivo.
    return ruta.exists() or ruta.is_symlink()


def planificar_configuracion(
    raiz: Path,
    contrato_nuevo: Sequence[RecursoConfiguracion],
    contrato_actual: Sequence[RecursoConfiguracion] | None,
) -> tuple[EntradaPlanConfiguracion, ...]:
    """Decide, sin tocar nada, qué haría una actualización con cada recurso.

    Entradas:
        raiz: raíz de la instalación productiva.
        contrato_nuevo: recursos declarados por la release que se quiere activar.
        contrato_actual: recursos declarados por la release en uso, o ``None``
            cuando no hay release activa o la activa es anterior al contrato.

    Resultado: una entrada de plan por recurso del contrato nuevo.

    Efectos laterales: ninguno. Planificar es deliberadamente una operación de
    solo lectura para que quien la ejecute pueda abortar antes de mutar.

    Reglas aplicadas, en este orden:

    1. si el recurso existe y el contrato anterior declaraba otro ``schema``,
       hace falta una migración aprobada: ``MIGRACION_REQUERIDA``;
    2. si el recurso existe, se preserva intacto: ``PRESERVAR``;
    3. si está ausente y la release declara bootstrap, se puede crear: ``CREAR``;
    4. si está ausente y no hay bootstrap declarado, se preserva la ausencia y
       queda a cargo del operador: ``PRESERVAR`` con motivo explícito.

    Cuando ``contrato_actual`` es ``None`` no se puede comparar schema alguno.
    Eso **no** habilita ninguna mutación adicional: los recursos existentes
    siguen preservándose, así que la ausencia de comparación nunca puede
    traducirse en una escritura sobre configuración institucional.
    """

    schemas_anteriores = (
        {recurso.ruta_local: recurso.schema for recurso in contrato_actual}
        if contrato_actual is not None
        else {}
    )

    plan: list[EntradaPlanConfiguracion] = []
    for recurso in contrato_nuevo:
        existe = _existe_recurso(raiz, recurso)
        schema_anterior = schemas_anteriores.get(recurso.ruta_local)

        if existe and schema_anterior is not None and schema_anterior != recurso.schema:
            plan.append(
                EntradaPlanConfiguracion(
                    recurso=recurso,
                    accion=ACCION_MIGRACION_REQUERIDA,
                    motivo=(
                        f"{recurso.ruta_local} existe con schema {schema_anterior} y la release "
                        f"nueva declara {recurso.schema}. Una migración de configuración "
                        "requiere aprobación humana (HUMAN_GATE); la actualización se detiene "
                        "sin modificar nada."
                    ),
                )
            )
            continue

        if existe:
            plan.append(
                EntradaPlanConfiguracion(
                    recurso=recurso,
                    accion=ACCION_PRESERVAR,
                    motivo=f"{recurso.ruta_local} ya existe y se conserva byte a byte.",
                )
            )
            continue

        if recurso.bootstrap is None:
            plan.append(
                EntradaPlanConfiguracion(
                    recurso=recurso,
                    accion=ACCION_PRESERVAR,
                    motivo=(
                        f"{recurso.ruta_local} no existe y la release no declara un bootstrap "
                        "seguro: debe provisionarlo el operador."
                    ),
                )
            )
            continue

        plan.append(
            EntradaPlanConfiguracion(
                recurso=recurso,
                accion=ACCION_CREAR,
                motivo=(
                    f"{recurso.ruta_local} no existe y la release declara el bootstrap "
                    f"{recurso.bootstrap}: se creará sin tocar ningún archivo previo."
                ),
            )
        )

    return tuple(plan)


def exigir_plan_sin_migraciones(plan: Sequence[EntradaPlanConfiguracion]) -> None:
    """Aborta si el plan detectó al menos una migración pendiente.

    Se separa del planificador para que el llamador pueda mostrar el plan
    completo —incluidas las entradas correctas— antes de fallar, en lugar de
    cortar en la primera incompatibilidad.
    """

    bloqueantes = [entrada for entrada in plan if entrada.accion == ACCION_MIGRACION_REQUERIDA]
    if not bloqueantes:
        return
    detalle = " ".join(entrada.motivo for entrada in bloqueantes)
    raise ErrorConfiguracionLocal(
        "La release nueva exige migrar configuración local existente. "
        f"No se modificó nada. {detalle}"
    )


def _crear_archivo_add_only(origen: Path, destino: Path, modo: int) -> bool:
    """Crea un archivo sólo si su destino no existe, de forma atómica.

    ¿Por qué no ``shutil.copyfile`` directo? Porque copiar escribe byte a byte
    sobre el destino final: si el proceso muere a la mitad queda un archivo de
    configuración truncado que el backend leería como válido. Y porque
    ``copyfile`` sobrescribe, que es justamente lo que este contrato prohíbe.

    La secuencia segura es: escribir un temporal **en el mismo directorio**
    (para que el enlace posterior no cruce sistemas de archivos), aplicarle el
    modo previsto y publicarlo con ``os.link``. ``link`` falla con
    ``FileExistsError`` si el destino apareció mientras tanto, de modo que la
    regla «jamás reemplazar» se cumple incluso ante una carrera.

    Resultado: ``True`` si creó el archivo, ``False`` si el destino ya existía.
    """

    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_name(f".{destino.name}.nuevo-{os.getpid()}")
    temporal.unlink(missing_ok=True)
    try:
        shutil.copyfile(origen, temporal)
        temporal.chmod(modo)
        try:
            os.link(temporal, destino)
        except FileExistsError:
            return False
        return True
    finally:
        temporal.unlink(missing_ok=True)


def _fijar_propietario(
    ruta: Path,
    recurso: RecursoConfiguracion,
    aplicar_propietario: Callable[[Path, str, str], None] | None,
) -> None:
    """Aplica el ownership declarado a algo recién creado, si se puede.

    Un archivo de configuración creado con modo ``0640`` pero con dueño y grupo
    equivocados sería ilegible para el servicio que lo necesita. Por eso el
    ownership forma parte del contrato y no de la buena voluntad del llamador.
    """

    if aplicar_propietario is None or recurso.usuario is None or recurso.grupo is None:
        return
    aplicar_propietario(ruta, recurso.usuario, recurso.grupo)


def aplicar_plan_configuracion(
    raiz: Path,
    release: Path,
    plan: Sequence[EntradaPlanConfiguracion],
    *,
    aplicar_propietario: Callable[[Path, str, str], None] | None = None,
) -> tuple[str, ...]:
    """Materializa únicamente las entradas ``CREAR`` del plan.

    Entradas:
        raiz: raíz de la instalación productiva.
        release: release cuyo contrato generó el plan; de ahí salen los
            contenidos de bootstrap declarados.
        plan: plan ya calculado por :func:`planificar_configuracion`.
        aplicar_propietario: callback que recibe ``(ruta, usuario, grupo)`` para
            fijar el ownership declarado. Se inyecta porque cambiar de dueño es
            una operación privilegiada: la herramienta de despliegue la delega en
            su ejecutor auditable y las pruebas la observan sin ser root. Si es
            ``None`` sólo se aplica el modo, que ``chmod`` sí puede fijar sin
            privilegios sobre un archivo recién creado.

    Resultado: rutas locales efectivamente creadas, en orden.

    Efectos laterales: crea archivos y directorios ausentes. Nunca escribe sobre
    algo existente y nunca modifica una entrada marcada ``PRESERVAR``.

    Errores:
        ErrorConfiguracionLocal si el plan todavía contiene una migración
        pendiente, si la fuente de bootstrap falta o no es del tipo declarado, o
        si la creación falla por E/S.
    """

    # Doble compuerta deliberada: aunque el llamador ya debería haber invocado
    # ``exigir_plan_sin_migraciones``, aplicar un plan con migraciones
    # pendientes nunca puede pasar por descuido.
    exigir_plan_sin_migraciones(plan)

    creados: list[str] = []
    for entrada in plan:
        if entrada.accion != ACCION_CREAR:
            continue
        recurso = entrada.recurso
        # El planificador ya garantizó que estas tres cosas están declaradas;
        # se vuelven a comprobar acá porque el aplicador es público y podría
        # recibir un plan construido a mano en una prueba o en WP-101.
        if recurso.bootstrap is None or recurso.modo is None:
            raise ErrorConfiguracionLocal(
                f"{recurso.ruta_local} está marcado para crearse sin bootstrap o modo previsto."
            )
        origen = release / recurso.bootstrap
        destino = raiz / recurso.ruta_local

        try:
            if recurso.tipo == "archivo":
                if not origen.is_file() or origen.is_symlink():
                    raise ErrorConfiguracionLocal(
                        f"El bootstrap declarado para {recurso.ruta_local} no es un archivo "
                        f"regular de la release: {origen}"
                    )
                if _crear_archivo_add_only(origen, destino, recurso.modo):
                    _fijar_propietario(destino, recurso, aplicar_propietario)
                    creados.append(recurso.ruta_local)
                continue

            if not origen.is_dir() or origen.is_symlink():
                raise ErrorConfiguracionLocal(
                    f"El bootstrap declarado para {recurso.ruta_local} no es un directorio de "
                    f"la release: {origen}"
                )
            # Un recurso de tipo directorio se completa archivo por archivo: si
            # el operador ya puso ocho fotos reales y faltan cuatro, se crean
            # sólo esas cuatro. Es el mismo criterio que WP-098 fijó para el
            # checkout de desarrollo, aplicado ahora a producción.
            destino.mkdir(parents=True, exist_ok=True)
            _fijar_propietario(destino, recurso, aplicar_propietario)
            hubo_creacion = False
            for archivo in sorted(ruta for ruta in origen.rglob("*") if ruta.is_file()):
                if archivo.is_symlink():
                    raise ErrorConfiguracionLocal(
                        f"El bootstrap de {recurso.ruta_local} contiene un enlace: {archivo}"
                    )
                relativa = archivo.relative_to(origen)
                creado = destino / relativa
                if _crear_archivo_add_only(archivo, creado, recurso.modo):
                    _fijar_propietario(creado, recurso, aplicar_propietario)
                    hubo_creacion = True
            if hubo_creacion:
                creados.append(recurso.ruta_local)
        except OSError as error:
            raise ErrorConfiguracionLocal(
                f"No se pudo incorporar {recurso.ruta_local}: {error}"
            ) from error

    return tuple(creados)


def plan_como_json(plan: Sequence[EntradaPlanConfiguracion]) -> list[dict[str, Any]]:
    """Serializa el plan para mostrarlo por la CLI o registrarlo en un log."""

    return [
        {
            "ruta_local": entrada.recurso.ruta_local,
            "tipo": entrada.recurso.tipo,
            "schema": entrada.recurso.schema,
            "accion": entrada.accion,
            "motivo": entrada.motivo,
        }
        for entrada in plan
    ]
