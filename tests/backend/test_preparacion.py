"""Pruebas del servicio de dominio ``ServicioPreparacion`` (WP-005).

Cubren el ciclo ``SIN_PREPARAR -> PREPARANDO -> SIN_PREPARAR`` a nivel de
servicio, con disco y reloj aislados: configuración/padrón se escriben en
``tmp_path`` y el directorio de registros se redirige a esa misma carpeta
temporal mediante la clave ``paths.logs_dir`` del TOML de prueba.

Los escenarios corresponden a las pruebas obligatorias de dominio/servicio
del WP: preparación exitosa y contexto congelado, concejales ausentes,
rechazos por estado incompatible, fallos de configuración/padrón/auditoría
sin estado parcial, cancelación exitosa con cierre definitivo, fallo cerrado
al cancelar, preparaciones sucesivas con conjuntos de auditoría distintos,
congelamiento de snapshots, reinicio y concurrencia por el serializador
único.
"""

from __future__ import annotations

import asyncio
import csv
from collections.abc import Callable
from datetime import datetime
from functools import partial
from pathlib import Path

import pytest
from conftest import (
    LINEA_LOGS,
    LINEA_QUORUM,
    TOML_CANONICO,
    escribir_padron,
    escribir_system_toml,
    filas_padron_valido,
)
from sis_leg_backend.auditoria import (
    ErrorAuditoria,
    ErrorEscritorNoDisponible,
    EscritorAuditoriaCsv,
    NivelAuditoria,
)
from sis_leg_backend.configuracion.errores import (
    ErrorPadronInvalido,
    ErrorTomlInvalido,
    ErrorValidacionConfiguracion,
)
from sis_leg_backend.dominio.errores import ErrorEstadoIncompatible
from sis_leg_backend.dominio.estado import EstadoGlobal, EstadoOperativo
from sis_leg_backend.servicios.preparacion import ServicioPreparacion
from sis_leg_backend.servicios.serializacion import EjecutorMutaciones

pytestmark = pytest.mark.anyio

# Hora fija de referencia para que los nombres de los CSV sean predecibles.
HORA_INICIO = datetime(2026, 8, 20, 15, 30, 45)


def leer_filas(ruta: Path) -> list[list[str]]:
    """Lee un CSV de auditoría con el delimitador y la codificación canónicos."""

    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.reader(archivo, delimiter=";"))


def csv_auditoria(directorio: Path) -> list[Path]:
    """Lista los CSV de auditoría bajo ``logs``, excluyendo el padrón de prueba."""

    return sorted((directorio / "logs").rglob("*.csv"))


def toml_con_logs_en(directorio_logs: Path, **reemplazos: str) -> str:
    """Devuelve el TOML canónico apuntando los registros a ``directorio_logs``.

    Acepta además pares ``linea_original=linea_nueva`` para fabricar
    configuraciones alteradas sin duplicar el TOML completo.
    """

    contenido = TOML_CANONICO.replace(LINEA_LOGS, f'logs_dir = "{directorio_logs}"')
    for original, nuevo in reemplazos.items():
        contenido = contenido.replace(original, nuevo)
    return contenido


def crear_servicio(
    tmp_path: Path,
    *,
    estado: EstadoOperativo | None = None,
    ejecutor: EjecutorMutaciones | None = None,
    contenido_toml: str | None = None,
    filas_padron: list[list[str]] | None = None,
    reloj: Callable[[], datetime] = lambda: HORA_INICIO,
    fabrica_escritor: Callable[[Path, datetime], EscritorAuditoriaCsv] | None = None,
) -> ServicioPreparacion:
    """Construye un servicio con archivos válidos de fantasía en ``tmp_path``.

    Centraliza el armado repetido de los tests: escribe ``system.toml`` y
    ``concejales.csv`` (salvo que el llamador inyecte variantes) y devuelve el
    servicio listo para operar sobre un estado/serializador propios.

    Cuando no se inyecta una fábrica de escritor, se construye una que pasa el
    mismo ``reloj`` al escritor, de modo que tanto la hora de inicio como los
    timestamps de los eventos sean deterministas en las pruebas.
    """

    ruta_config = escribir_system_toml(
        tmp_path / "system.toml", contenido_toml or toml_con_logs_en(tmp_path / "logs")
    )
    filas = filas_padron if filas_padron is not None else filas_padron_valido()
    ruta_padron = escribir_padron(tmp_path / "concejales.csv", filas)
    return ServicioPreparacion(
        estado_operativo=estado or EstadoOperativo(),
        ejecutor_mutaciones=ejecutor or EjecutorMutaciones(),
        ruta_configuracion=ruta_config,
        ruta_padron=ruta_padron,
        reloj=reloj,
        fabrica_escritor=fabrica_escritor or partial(EscritorAuditoriaCsv, reloj=reloj),
    )


async def test_preparacion_exitosa_construye_contexto_congelado(tmp_path: Path) -> None:
    """Preparar desde SIN_PREPARAR deja PREPARANDO con snapshots y auditoría."""

    estado = EstadoOperativo()
    servicio = crear_servicio(tmp_path, estado=estado)

    await servicio.preparar_sala()

    assert estado.estado_global is EstadoGlobal.PREPARANDO
    preparacion = estado.preparacion_activa
    assert preparacion is not None
    assert preparacion.fecha_hora_inicio == HORA_INICIO
    # Los snapshots congelados provienen de WP-003 y son independientes del disco.
    assert preparacion.configuracion.quorum == 7
    assert len(preparacion.padron.concejales) == 12
    # Las tres rutas de auditoría quedan asociadas al estado para los WPs futuros.
    assert len(estado.archivos_auditoria_activos) == 3
    assert preparacion.rutas_auditoria() == estado.archivos_auditoria_activos


async def test_todos_los_concejales_comienzan_ausentes(tmp_path: Path) -> None:
    """RN-PRE-01: ninguna presencia puede venir del padrón ni de ejecuciones previas."""

    estado = EstadoOperativo()
    servicio = crear_servicio(tmp_path, estado=estado)

    await servicio.preparar_sala()

    preparacion = estado.preparacion_activa
    assert preparacion is not None
    dnis = {concejal.dni for concejal in preparacion.padron.concejales}
    assert set(preparacion.presencias) == dnis
    assert not any(preparacion.presencias.values())


async def test_evento_iniciada_aparece_en_los_tres_niveles_con_el_mismo_seq(
    tmp_path: Path,
) -> None:
    """CA-053/CA-054: el evento L3 propietario se replica en L1+L2+L3."""

    estado = EstadoOperativo()
    servicio = crear_servicio(tmp_path, estado=estado)

    await servicio.preparar_sala()

    preparacion = estado.preparacion_activa
    assert preparacion is not None
    for ruta in estado.archivos_auditoria_activos:
        filas = leer_filas(ruta)
        # Una sola fila de evento tras el encabezado, idéntica en los tres CSV.
        assert len(filas) == 2
        assert filas[1][0] == "1"
        assert filas[1][1] == "2026-08-20 15:30:45"
        assert filas[1][2] == "L3"
        assert filas[1][3] == "PREPARACION"
        assert filas[1][4] == "PREPARACION_INICIADA"
        assert filas[1][5] == "Preparación del recinto iniciada"


async def test_preparar_fuera_de_sin_preparar_se_rechaza_sin_efectos(tmp_path: Path) -> None:
    """Una segunda preparación se rechaza y no crea otro conjunto de auditoría."""

    estado = EstadoOperativo()
    servicio = crear_servicio(tmp_path, estado=estado)
    await servicio.preparar_sala()
    rutas_previas = estado.archivos_auditoria_activos

    with pytest.raises(ErrorEstadoIncompatible):
        await servicio.preparar_sala()

    assert estado.estado_global is EstadoGlobal.PREPARANDO
    assert estado.archivos_auditoria_activos == rutas_previas
    # No se crearon archivos nuevos: solo existen los tres de la preparación válida.
    assert len(csv_auditoria(tmp_path)) == 3


async def test_cancelar_fuera_de_preparando_se_rechaza_sin_efectos(tmp_path: Path) -> None:
    """Cancelar desde SIN_PREPARAR no altera estado ni crea archivos."""

    estado = EstadoOperativo()
    servicio = crear_servicio(tmp_path, estado=estado)

    with pytest.raises(ErrorEstadoIncompatible):
        await servicio.cancelar_preparacion()

    assert estado.estado_global is EstadoGlobal.SIN_PREPARAR
    assert estado.preparacion_activa is None
    assert not csv_auditoria(tmp_path)


async def test_configuracion_no_legible_impide_preparar_sin_estado_parcial(
    tmp_path: Path,
) -> None:
    """Un TOML ilegible deja el sistema en SIN_PREPARAR y sin auditoría."""

    estado = EstadoOperativo()
    servicio = crear_servicio(tmp_path, estado=estado, contenido_toml="esto no es toml = [")

    with pytest.raises(ErrorTomlInvalido):
        await servicio.preparar_sala()

    assert estado.estado_global is EstadoGlobal.SIN_PREPARAR
    assert estado.preparacion_activa is None
    assert estado.archivos_auditoria_activos == ()
    assert not csv_auditoria(tmp_path)


async def test_configuracion_invalida_impide_preparar_sin_estado_parcial(tmp_path: Path) -> None:
    """Una regla del esquema incumplida bloquea la preparación (CA-003)."""

    estado = EstadoOperativo()
    servicio = crear_servicio(
        tmp_path,
        estado=estado,
        contenido_toml=toml_con_logs_en(tmp_path / "logs").replace(LINEA_QUORUM, "quorum = 0"),
    )

    with pytest.raises(ErrorValidacionConfiguracion):
        await servicio.preparar_sala()

    assert estado.estado_global is EstadoGlobal.SIN_PREPARAR
    assert estado.preparacion_activa is None
    assert not csv_auditoria(tmp_path)


async def test_padron_invalido_impide_preparar_sin_estado_parcial(tmp_path: Path) -> None:
    """Un padrón que incumple el contrato bloquea la preparación (CA-003)."""

    filas = filas_padron_valido()
    filas[3][0] = filas[0][0]  # DNI duplicado: bloquea la carga del padrón.
    estado = EstadoOperativo()
    servicio = crear_servicio(tmp_path, estado=estado, filas_padron=filas)

    with pytest.raises(ErrorPadronInvalido):
        await servicio.preparar_sala()

    assert estado.estado_global is EstadoGlobal.SIN_PREPARAR
    assert estado.preparacion_activa is None
    assert not csv_auditoria(tmp_path)


async def test_fallo_de_creacion_del_escritor_no_transita_a_preparando(tmp_path: Path) -> None:
    """Si el conjunto CSV no puede crearse, no hay preparación activa."""

    # Un archivo ocupando el lugar del directorio de registros hace fallar la
    # creación de la carpeta de auditoría.
    ruta_logs = tmp_path / "logs"
    ruta_logs.write_text("no es un directorio", encoding="utf-8")
    estado = EstadoOperativo()
    servicio = crear_servicio(tmp_path, estado=estado, contenido_toml=toml_con_logs_en(ruta_logs))

    with pytest.raises(ErrorAuditoria):
        await servicio.preparar_sala()

    assert estado.estado_global is EstadoGlobal.SIN_PREPARAR
    assert estado.preparacion_activa is None
    assert estado.archivos_auditoria_activos == ()


async def test_fallo_al_persistir_evento_inicial_conserva_archivos_y_no_transita(
    tmp_path: Path,
) -> None:
    """Si ``PREPARACION_INICIADA`` no puede persistirse, no se confirma la preparación.

    Los tres primeros ``fsync`` corresponden a los encabezados; el cuarto falla
    al persistir el evento. Los CSV alcanzados a crear se conservan como
    evidencia técnica: no se borran para simular que el intento no existió.
    """

    llamadas = 0

    def sincronizar_con_fallo(_descriptor: int) -> None:
        nonlocal llamadas
        llamadas += 1
        if llamadas == 4:
            raise OSError("disco no disponible")

    estado = EstadoOperativo()
    servicio = crear_servicio(
        tmp_path,
        estado=estado,
        fabrica_escritor=partial(EscritorAuditoriaCsv, sincronizar=sincronizar_con_fallo),
    )

    with pytest.raises(ErrorAuditoria):
        await servicio.preparar_sala()

    assert estado.estado_global is EstadoGlobal.SIN_PREPARAR
    assert estado.preparacion_activa is None
    assert estado.archivos_auditoria_activos == ()
    # Evidencia conservada: los tres CSV existen. La fila del evento fallido
    # pudo alcanzar el primer destino (L1) antes del ``fsync`` que falló: esa
    # escritura parcial también se conserva, nunca se borra retrospectivamente.
    archivos = csv_auditoria(tmp_path)
    assert len(archivos) == 3
    assert len(leer_filas(archivos[0])) <= 2
    for ruta in archivos[1:]:
        assert len(leer_filas(ruta)) == 1

    # Un intento posterior con la misma hora usa la regla de nombres libres y
    # nunca sobrescribe la evidencia del intento fallido (WP-004).
    servicio_sano = crear_servicio(tmp_path, estado=estado)
    await servicio_sano.preparar_sala()
    assert estado.estado_global is EstadoGlobal.PREPARANDO
    assert len(csv_auditoria(tmp_path)) == 6


async def test_cancelacion_exitosa_registra_cierra_y_limpia_el_contexto(tmp_path: Path) -> None:
    """CA-008/CA-056: cancelar persiste el evento final y cierra definitivamente."""

    estado = EstadoOperativo()
    servicio = crear_servicio(tmp_path, estado=estado)
    await servicio.preparar_sala()
    preparacion = estado.preparacion_activa
    assert preparacion is not None
    rutas = estado.archivos_auditoria_activos

    await servicio.cancelar_preparacion()

    assert estado.estado_global is EstadoGlobal.SIN_PREPARAR
    assert estado.preparacion_activa is None
    assert estado.archivos_auditoria_activos == ()
    assert preparacion.escritor_auditoria.cerrado

    # El evento final quedó en los tres niveles con el mismo seq (RN-LOG-07).
    for ruta in rutas:
        filas = leer_filas(ruta)
        assert len(filas) == 3
        assert filas[2][0] == "2"
        assert filas[2][2] == "L3"
        assert filas[2][3] == "PREPARACION"
        assert filas[2][4] == "PREPARACION_CANCELADA"
        assert filas[2][5] == "Preparación del recinto cancelada"

    # CA-056: los archivos cerrados no vuelven a modificarse por el backend.
    contenidos = {ruta: ruta.read_bytes() for ruta in rutas}
    with pytest.raises(ErrorEscritorNoDisponible):
        preparacion.escritor_auditoria.registrar_evento(
            NivelAuditoria.L3, "PREPARACION", "OTRO", "No debe escribirse"
        )
    assert {ruta: ruta.read_bytes() for ruta in rutas} == contenidos


async def test_fallo_de_persistencia_al_cancelar_deja_preparando_en_fallo_cerrado(
    tmp_path: Path,
) -> None:
    """Si el evento de cancelación no persiste, no se confirma la cancelación."""

    llamadas = 0

    def sincronizar_hasta_la_cancelacion(_descriptor: int) -> None:
        nonlocal llamadas
        llamadas += 1
        # Encabezados (3) + evento de inicio (3) funcionan; el primer fsync
        # del evento de cancelación (7.º) falla.
        if llamadas == 7:
            raise OSError("disco no disponible al cancelar")

    estado = EstadoOperativo()
    fabrica = partial(EscritorAuditoriaCsv, sincronizar=sincronizar_hasta_la_cancelacion)
    servicio = crear_servicio(tmp_path, estado=estado, fabrica_escritor=fabrica)
    await servicio.preparar_sala()

    with pytest.raises(ErrorAuditoria):
        await servicio.cancelar_preparacion()

    # No se confirma éxito parcial: el estado permanece PREPARANDO y no se
    # inventa un cuarto estado reglamentario (WP-005, fallo cerrado).
    assert estado.estado_global is EstadoGlobal.PREPARANDO
    assert estado.preparacion_activa is not None

    # La preparación queda en fallo cerrado para nuevas mutaciones auditables:
    # reintentar la cancelación vuelve a rechazarse sin confirmar nada.
    with pytest.raises(ErrorAuditoria):
        await servicio.cancelar_preparacion()
    assert estado.estado_global is EstadoGlobal.PREPARANDO


class EscritorConCierreFallido(EscritorAuditoriaCsv):
    """Escritor de prueba cuyo cierre informa un error del sistema operativo."""

    def cerrar(self) -> None:
        super().cerrar()
        raise ErrorAuditoria("fallo simulado al cerrar el conjunto")


async def test_fallo_de_cierre_al_cancelar_deja_preparando_en_fallo_cerrado(
    tmp_path: Path,
) -> None:
    """Si el cierre no puede garantizarse, la cancelación no se confirma.

    Aunque el evento ``PREPARACION_CANCELADA`` alcanzó a persistirse antes del
    fallo de cierre, el sistema no reescribe ni borra retrospectivamente los
    CSV y el estado permanece ``PREPARANDO`` (WP-005, fallo cerrado).
    """

    estado = EstadoOperativo()
    servicio = crear_servicio(tmp_path, estado=estado, fabrica_escritor=EscritorConCierreFallido)
    await servicio.preparar_sala()
    rutas = estado.archivos_auditoria_activos

    with pytest.raises(ErrorAuditoria, match="cerrar"):
        await servicio.cancelar_preparacion()

    assert estado.estado_global is EstadoGlobal.PREPARANDO
    assert estado.preparacion_activa is not None
    # El evento alcanzó a persistirse y no se borra retrospectivamente.
    assert leer_filas(rutas[0])[-1][4] == "PREPARACION_CANCELADA"

    # El conjunto quedó marcado como cerrado/fallado: todo reintento se
    # rechaza sin confirmar cancelación (fallo cerrado).
    with pytest.raises(ErrorAuditoria):
        await servicio.cancelar_preparacion()
    assert estado.estado_global is EstadoGlobal.PREPARANDO


async def test_nueva_preparacion_tras_cancelar_comienza_limpia_y_con_otro_conjunto(
    tmp_path: Path,
) -> None:
    """RN-PREP-06/CA-008: cada preparación crea archivos nuevos y estado limpio."""

    estado = EstadoOperativo()
    servicio = crear_servicio(tmp_path, estado=estado, reloj=lambda: HORA_INICIO)
    await servicio.preparar_sala()
    primeras_rutas = estado.archivos_auditoria_activos
    await servicio.cancelar_preparacion()

    await servicio.preparar_sala()

    assert estado.estado_global is EstadoGlobal.PREPARANDO
    preparacion = estado.preparacion_activa
    assert preparacion is not None
    # Conjunto distinto: la colisión nominal avanzó un segundo en el nombre.
    segundas_rutas = estado.archivos_auditoria_activos
    assert set(segundas_rutas).isdisjoint(primeras_rutas)
    assert "15-30-46" in segundas_rutas[0].name
    # Estado limpio: todos ausentes nuevamente.
    assert not any(preparacion.presencias.values())
    # Los archivos de la preparación cancelada siguen intactos (conservados).
    for ruta in primeras_rutas:
        assert leer_filas(ruta)[-1][4] == "PREPARACION_CANCELADA"


async def test_cambios_en_disco_durante_preparando_no_alteran_los_snapshots(
    tmp_path: Path,
) -> None:
    """CA-059/RN-CFG-02: la preparación activa nunca relee archivos para mutarse."""

    estado = EstadoOperativo()
    servicio = crear_servicio(tmp_path, estado=estado)
    await servicio.preparar_sala()
    preparacion = estado.preparacion_activa
    assert preparacion is not None
    padron_original = preparacion.padron

    # Se modifican ambos archivos en disco después de preparar.
    escribir_system_toml(
        tmp_path / "system.toml",
        toml_con_logs_en(tmp_path / "logs").replace(LINEA_QUORUM, "quorum = 3"),
    )
    filas_otras = filas_padron_valido()
    filas_otras[0][1] = "NombreCambiado"
    escribir_padron(tmp_path / "concejales.csv", filas_otras)

    # Los snapshots activos no se enteran de los cambios.
    assert preparacion.configuracion.quorum == 7
    assert preparacion.padron is padron_original
    assert preparacion.padron.concejales[0].nombre == "Ana"

    # Una preparación nueva posterior sí vuelve a cargar desde disco (CA-059).
    await servicio.cancelar_preparacion()
    await servicio.preparar_sala()
    preparacion_nueva = estado.preparacion_activa
    assert preparacion_nueva is not None
    assert preparacion_nueva.configuracion.quorum == 3
    assert preparacion_nueva.padron.concejales[0].nombre == "NombreCambiado"


async def test_estado_nuevo_no_reconstruye_preparacion_desde_disco(tmp_path: Path) -> None:
    """CA-057/RN-GLOBAL-03: un estado nuevo arranca en SIN_PREPARAR.

    Simula el reinicio del backend: se descarta el ``EstadoOperativo`` y se
    crea otro, como hace el lifespan. Los CSV previos quedan intactos y nadie
    los reconstruye ni los modifica retrospectivamente.
    """

    estado_inicial = EstadoOperativo()
    servicio = crear_servicio(tmp_path, estado=estado_inicial)
    await servicio.preparar_sala()
    rutas_previas = estado_inicial.archivos_auditoria_activos
    contenidos_previos = {ruta: ruta.read_bytes() for ruta in rutas_previas}

    # "Reinicio": un estado operativo completamente nuevo (como WP-002).
    estado_reiniciado = EstadoOperativo()

    assert estado_reiniciado.estado_global is EstadoGlobal.SIN_PREPARAR
    assert estado_reiniciado.preparacion_activa is None
    assert estado_reiniciado.archivos_auditoria_activos == ()
    assert {ruta: ruta.read_bytes() for ruta in rutas_previas} == contenidos_previos


async def test_dos_preparaciones_concurrentes_se_ordenan_por_el_serializador(
    tmp_path: Path,
) -> None:
    """CA-058: dos comandos concurrentes no crean estados simultáneos.

    Ambos pedidos compiten por el mismo ``EjecutorMutaciones``: exactamente
    uno prepara y el otro se rechaza por estado incompatible. Al final existe
    un único conjunto de auditoría y un único estado coherente.
    """

    estado = EstadoOperativo()
    ejecutor = EjecutorMutaciones()
    servicio = crear_servicio(tmp_path, estado=estado, ejecutor=ejecutor)

    resultados: list[str] = []

    async def intentar_preparar() -> None:
        try:
            await servicio.preparar_sala()
            resultados.append("exito")
        except ErrorEstadoIncompatible:
            resultados.append("rechazado")

    await asyncio.gather(intentar_preparar(), intentar_preparar())

    assert sorted(resultados) == ["exito", "rechazado"]
    assert estado.estado_global is EstadoGlobal.PREPARANDO
    assert len(csv_auditoria(tmp_path)) == 3


async def test_preparar_y_cancelar_concurrentes_dejan_un_estado_coherente(
    tmp_path: Path,
) -> None:
    """CA-058: la mezcla de comandos concurrentes nunca corrompe el estado.

    Cualquiera de los dos órdenes posibles es válido, pero el resultado final
    debe ser consistente: o la cancelación llegó primero (rechazada) y el recinto
    quedó preparada, o preparó primero y luego se canceló.
    """

    estado = EstadoOperativo()
    ejecutor = EjecutorMutaciones()
    servicio = crear_servicio(tmp_path, estado=estado, ejecutor=ejecutor)

    resultados: dict[str, str] = {}

    async def intentar_preparar() -> None:
        try:
            await servicio.preparar_sala()
            resultados["preparar"] = "exito"
        except ErrorEstadoIncompatible:
            resultados["preparar"] = "rechazado"

    async def intentar_cancelar() -> None:
        try:
            await servicio.cancelar_preparacion()
            resultados["cancelar"] = "exito"
        except ErrorEstadoIncompatible:
            resultados["cancelar"] = "rechazado"

    await asyncio.gather(intentar_preparar(), intentar_cancelar())

    # La preparación siempre es válida desde SIN_PREPARAR; la cancelación solo
    # puede completarse si se ejecutó después de ella.
    assert resultados["preparar"] == "exito"
    if resultados["cancelar"] == "exito":
        assert estado.estado_global is EstadoGlobal.SIN_PREPARAR
        assert estado.preparacion_activa is None
    else:
        assert estado.estado_global is EstadoGlobal.PREPARANDO
        assert estado.preparacion_activa is not None
    # En ambos casos hay exactamente un conjunto de auditoría, sin corrupción.
    assert len(csv_auditoria(tmp_path)) == 3


async def test_preparar_refresca_los_sonidos_del_recinto(tmp_path: Path) -> None:
    """La preparación alinea el audio publicado con la configuración congelada.

    Los sonidos (WP-065) se leen al arrancar el proceso para estar disponibles
    en ``SIN_PREPARAR``. Si el archivo cambió entre ese arranque y esta
    preparación, lo que ve la Pantalla del Recinto durante la sesión debe ser
    el snapshot recién congelado y no la copia vieja del arranque.
    """

    estado = EstadoOperativo()
    contenido = toml_con_logs_en(tmp_path / "logs").replace("volumen = 0\n", "volumen = 11\n")
    servicio = crear_servicio(tmp_path, estado=estado, contenido_toml=contenido)

    await servicio.preparar_sala()

    preparacion = estado.preparacion_activa
    assert preparacion is not None
    assert estado.sonidos_recinto == preparacion.configuracion.sonidos_recinto
    assert estado.sonidos_recinto.sonidos[0].volumen == 11


async def test_una_configuracion_invalida_no_toca_los_sonidos_vigentes(tmp_path: Path) -> None:
    """Fallo cerrado: si la preparación falla, el audio anterior sigue vigente."""

    estado = EstadoOperativo()
    directorio_valido = tmp_path / "valido"
    directorio_valido.mkdir()
    servicio_valido = crear_servicio(directorio_valido, estado=estado)
    await servicio_valido.preparar_sala()
    sonidos_vigentes = estado.sonidos_recinto

    # Se vuelve a SIN_PREPARAR sin tocar el audio y se intenta preparar con un
    # TOML cuyo volumen está fuera de rango.
    await servicio_valido.cancelar_preparacion()
    directorio_invalido = tmp_path / "invalido"
    directorio_invalido.mkdir()
    # El salto de línea evita que el reemplazo alcance también a "volumen = 70"
    # o "volumen = 77": la prueba debe alterar exactamente una entrada.
    invalido = toml_con_logs_en(tmp_path / "logs").replace("volumen = 7\n", "volumen = 700\n")
    servicio_invalido = crear_servicio(directorio_invalido, estado=estado, contenido_toml=invalido)

    with pytest.raises(ErrorValidacionConfiguracion):
        await servicio_invalido.preparar_sala()

    assert estado.estado_global is EstadoGlobal.SIN_PREPARAR
    assert estado.sonidos_recinto == sonidos_vigentes
