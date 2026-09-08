"""WP-089: el timeout del canal de control debe ser finito y estrictamente positivo.

El backend habla con el device-bridge por HTTP local para coordinar un remapeo
urgente. La duración máxima de esa espera se configura por entorno con
``SIS_LEG_BRIDGE_CONTROL_TIMEOUT``. Antes de este WP, el valor se convertía con
un ``float(...)`` desnudo: ``nan``, ``inf``, ``0`` o un negativo atravesaban la
conversión y llegaban tal cual al socket de ``urllib``, donde su semántica es
indefinida o directamente peligrosa (``timeout=0`` significa "no esperar nada").

Estas pruebas fijan las dos mitades del contrato:

- la **frontera de configuración**: qué acepta y qué rechaza la construcción de
  los recursos del proceso, que es donde debe fallar (arranque), no en medio de
  un remapeo;
- la **frontera del cliente**: una construcción directa de
  ``ClienteControlBridge`` tampoco puede saltarse la invariante.

Para comprobar que un valor válido no sólo se acepta sino que además *llega* al
socket, se espía ``urllib.request.urlopen`` y se lee el ``timeout`` recibido.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from types import TracebackType
from typing import Any

import pytest
from sis_leg_backend.aplicacion import crear_aplicacion
from sis_leg_backend.recursos import RecursosAplicacion, crear_recursos_aplicacion
from sis_leg_backend.servicios.cliente_bridge import (
    ClienteControlBridge,
    ErrorConfiguracionBridge,
)

# Nombre literal exigido por el WP. Se escribe a mano —y no reutilizando la
# constante— para que un renombrado accidental de la variable de entorno rompa
# esta prueba en lugar de pasar inadvertido.
VARIABLE = "SIS_LEG_BRIDGE_CONTROL_TIMEOUT"

CUERPO_BRIDGE = json.dumps(
    {"remapeo_id": "rm-1", "dispositivo": "dev01", "estado": "CAPTURANDO"}
).encode("utf-8")


class RespuestaFalsa:
    """Imita lo justo de la respuesta de ``urlopen``: contexto y ``read()``."""

    def __enter__(self) -> RespuestaFalsa:
        return self

    def __exit__(
        self,
        tipo: type[BaseException] | None,
        valor: BaseException | None,
        traza: TracebackType | None,
    ) -> None:
        return None

    def read(self) -> bytes:
        return CUERPO_BRIDGE


class EspiaUrlopen:
    """Reemplaza a ``urlopen`` y anota con qué ``timeout`` fue invocado.

    Es la única manera de comprobar el valor *efectivo* sin leer un atributo
    privado del cliente: se observa exactamente el número que habría recibido el
    socket real.
    """

    def __init__(self) -> None:
        self.timeouts: list[float] = []

    def __call__(self, peticion: Any, timeout: float) -> RespuestaFalsa:
        self.timeouts.append(timeout)
        return RespuestaFalsa()


def construir_recursos(tmp_path: Path) -> RecursosAplicacion:
    """Construye recursos reales sin depender de los archivos del repositorio.

    Las rutas apuntan a archivos inexistentes a propósito: ni la biblioteca
    técnica ni el ``system.toml`` pueden impedir el arranque, así que la única
    causa posible de fallo en estas pruebas es el timeout del canal de control.
    """

    return crear_recursos_aplicacion(
        ruta_mensajes_tecnicos=tmp_path / "no-existe.csv",
        ruta_configuracion=tmp_path / "no-existe.toml",
    )


def timeout_efectivo(recursos: RecursosAplicacion, monkeypatch: pytest.MonkeyPatch) -> float:
    """Ejecuta un comando de control y devuelve el timeout que vio el socket."""

    espia = EspiaUrlopen()
    monkeypatch.setattr(urllib.request, "urlopen", espia)
    recursos.cliente_control_bridge.iniciar("rm-1", "dev01")
    assert len(espia.timeouts) == 1
    return espia.timeouts[0]


# --------------------------------------------------------------------------
# Frontera de configuración: variable ausente y valores válidos
# --------------------------------------------------------------------------


def test_variable_ausente_conserva_el_default_de_tres_segundos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin variable definida rige exactamente 3.0 s, el default histórico.

    El WP prohíbe cambiar ese default: la prueba compara contra el número
    literal y no contra una constante importada, para que un cambio silencioso
    del valor productivo falle acá.
    """

    monkeypatch.delenv(VARIABLE, raising=False)

    recursos = construir_recursos(tmp_path)

    assert timeout_efectivo(recursos, monkeypatch) == 3.0


@pytest.mark.parametrize(
    ("configurado", "esperado"),
    [("0.1", 0.1), ("1", 1.0), ("3.0", 3.0), ("30", 30.0)],
)
def test_valores_finitos_positivos_se_aceptan_y_llegan_al_socket(
    configurado: str,
    esperado: float,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enteros y decimales representables se aceptan y se usan tal cual.

    Comprobar el valor en el socket —y no sólo que la construcción no falle—
    demuestra que la validación no altera ni redondea la duración configurada.
    """

    monkeypatch.setenv(VARIABLE, configurado)

    recursos = construir_recursos(tmp_path)

    assert timeout_efectivo(recursos, monkeypatch) == esperado


# --------------------------------------------------------------------------
# Frontera de configuración: valores rechazados
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "configurado",
    [
        "nan",
        "NaN",
        "inf",
        "+inf",
        "-inf",
        "Infinity",
        "-Infinity",
        "0",
        "0.0",
        "-0.0",
        "-1",
        "-0.5",
        "",
        "   ",
        "abc",
        "3,0",
        "3 segundos",
        "3.0s",
    ],
)
def test_valores_invalidos_impiden_construir_los_recursos(
    configurado: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No finitos, cero, negativos, vacío y texto abortan el arranque.

    Un mismo caso cubre los tres criterios del WP a la vez: el rechazo ocurre,
    ocurre **al construir los recursos** y el mensaje nombra literalmente la
    variable para que quien opera sepa qué corregir.
    """

    monkeypatch.setenv(VARIABLE, configurado)

    with pytest.raises(ErrorConfiguracionBridge) as fallo:
        construir_recursos(tmp_path)

    assert VARIABLE in str(fallo.value)


def test_un_valor_invalido_no_cae_silenciosamente_al_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La variable presente pero inválida falla; nunca se degrada a 3.0 s.

    Es el escenario que motiva el WP: un despliegue con la variable mal escrita
    debe detenerse de forma ruidosa en lugar de arrancar aparentando estar
    configurado.
    """

    monkeypatch.setenv(VARIABLE, "nan")

    with pytest.raises(ErrorConfiguracionBridge):
        construir_recursos(tmp_path)


@pytest.mark.anyio
async def test_el_arranque_de_la_aplicacion_falla_antes_de_cualquier_remapeo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El lifespan real no llega a levantar con una duración inválida.

    Criterio 5 del WP: el fallo pertenece al arranque del proceso. Si la
    validación viviera recién en el uso, esta aplicación arrancaría y el error
    aparecería durante un remapeo urgente, que es el peor momento posible.
    """

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(VARIABLE, "0")
    aplicacion = crear_aplicacion()

    with pytest.raises(ErrorConfiguracionBridge) as fallo:
        async with aplicacion.router.lifespan_context(aplicacion):
            pass  # pragma: no cover - el arranque no debe completarse

    assert VARIABLE in str(fallo.value)


# --------------------------------------------------------------------------
# Frontera del cliente: construcción directa
# --------------------------------------------------------------------------


@pytest.mark.parametrize("duracion", [float("nan"), float("inf"), float("-inf"), 0, 0.0, -1, -0.5])
def test_el_cliente_rechaza_una_duracion_no_finita_o_no_positiva(duracion: float) -> None:
    """Construir el cliente a mano tampoco puede saltarse la invariante.

    El código del backend crea el cliente desde ``crear_recursos_aplicacion``,
    pero un test, un script o una futura ruta podrían instanciarlo directamente.
    La defensa vive en el constructor, así que ambas puertas comparten la misma
    regla sin duplicar la comprobación.
    """

    with pytest.raises(ErrorConfiguracionBridge) as fallo:
        ClienteControlBridge(timeout_segundos=duracion)

    assert "timeout_segundos" in str(fallo.value)


@pytest.mark.parametrize("duracion", [0.1, 1, 3.0, 30])
def test_el_cliente_acepta_duraciones_validas(
    duracion: float, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un valor válido pasado a mano se conserva y llega al socket."""

    espia = EspiaUrlopen()
    monkeypatch.setattr(urllib.request, "urlopen", espia)

    ClienteControlBridge(timeout_segundos=duracion).iniciar("rm-1", "dev01")

    assert espia.timeouts == [float(duracion)]


def test_el_cliente_sin_argumentos_mantiene_el_default_de_tres_segundos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El default del constructor sigue siendo 3.0 s y no depende del entorno."""

    espia = EspiaUrlopen()
    monkeypatch.setattr(urllib.request, "urlopen", espia)
    monkeypatch.setenv(VARIABLE, "17")

    ClienteControlBridge().iniciar("rm-1", "dev01")

    assert espia.timeouts == [3.0]
