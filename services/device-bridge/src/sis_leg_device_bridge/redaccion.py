"""Redacción segura de los registros operativos del Device Bridge (WP-088).

¿Por qué existe este módulo?
----------------------------

El bridge traduce una pulsación física en el par `{dispositivo, tecla}` que viaja al
backend. Ese par es exactamente lo que **no** puede quedar junto en un log: `dispositivo`
(o su fingerprint, o su ruta `/dev/input/eventN`) identifica una banca y, por lo tanto, a
una persona; las teclas `1`, `2` y `3` tienen semántica de voto POSITIVO, ABSTENCIÓN y
NEGATIVO. Un solo renglón de journal que contenga ambas cosas permite reconstruir el
sentido del voto de un concejal identificable **antes** de que el backend levante la
frontera autoritativa de revelado. Eso degradaría el secreto temporal del voto por una vía
puramente accesoria: la observabilidad del proceso.

WP-082 ya había cerrado la fuga de los dispositivos ajenos (el teclado del operador). WP-088
cierra la fuga simétrica y más grave: la de los dispositivos **propios**, es decir las
botoneras de banca, cuyo contenido de tecla sí es el voto.

La regla que implementa este módulo
-----------------------------------

> Ningún mensaje de log emitido por una pulsación funcional puede contener a la vez
> identidad de banca y contenido de tecla, en ningún nivel, DEBUG incluido.

El enfoque es **por construcción y no por filtrado de texto**: en lugar de intentar
detectar y tachar datos sensibles ya formateados dentro de un mensaje (algo frágil, que se
rompe con el primer formato nuevo), las funciones de acá construyen descripciones que
*jamás* pueden contener un valor sensible, porque nunca reciben ni copian valores:

- de un cuerpo de respuesta HTTP sólo se describe su **forma** (si llegó, y de qué tipo
  estructural es), nunca sus claves, sus valores ni su longitud, que es una medida directa
  de esos valores;
- de un motivo devuelto por el backend sólo se acepta la **forma** de un código estable
  (una allowlist de caracteres), y cualquier texto libre se reemplaza por un marcador;
- de una tecla física sólo se acepta el nombre cuando el normalizador demuestra que no
  corresponde a ninguna tecla funcional enviable al backend.

Frontera con la auditoría institucional
---------------------------------------

Nada de esto toca los CSV del backend ni su proyección de eventos. La auditoría durable es
la fuente institucional aprobada y conserva su contrato; lo que se endurece acá es el log
**operativo** del proceso del bridge (stdout/stderr y journald), que no es evidencia
institucional y que cualquier persona con acceso al equipo puede leer sin trazabilidad.
"""

from __future__ import annotations

import re
from typing import Any, cast

from sis_leg_device_bridge.normalizador import normalizar_tecla

# Marcador que reemplaza a un `motivo` que no tiene forma de código estable. Se registra
# tal cual para que soporte distinga «el backend no contestó un código canónico» de «el
# backend contestó un código que no conozco».
MOTIVO_NO_CANONICO = "MOTIVO_NO_CANONICO"

# Marcador que reemplaza al nombre de una tecla cuando no se puede demostrar que sea
# no funcional. Es la salida conservadora exigida por WP-088 ante cualquier ambigüedad.
TECLA_REDACTADA = "REDACTADA"

# Un código estable del backend es MAYUSCULAS_CON_GUION_BAJO y dígitos (por ejemplo
# `VOTO_REGISTRADO`, `AUDITORIA_NO_DISPONIBLE`, `HTTP_422`). La expresión es una allowlist
# de forma, no un filtro de contenido: cualquier cosa que no encaje se descarta entera en
# lugar de intentar limpiarla. El límite de longitud evita que un cuerpo malicioso escriba
# un párrafo en el journal aunque respete el alfabeto.
_PATRON_MOTIVO_ESTABLE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


def sanear_motivo(motivo: object) -> str:
    """Devuelve el motivo sólo si tiene forma de código estable; si no, un marcador.

    El `motivo` llega dentro del cuerpo JSON que contesta el backend, así que es texto de
    origen externo: el bridge no puede asumir que sea un código corto y neutro. Un cuerpo
    mal construido —o manipulado— podría traer algo como `"dev07 votó 1"`, y registrarlo
    reconstruiría el sentido del voto igual que si el bridge lo hubiese escrito.

    Se sanea en el **ingreso** al bridge y no en cada punto de logging: así el valor que
    queda guardado en `RespuestaEnvioBackend.motivo` ya es seguro y ningún consumidor
    posterior (por ejemplo el servicio, que lo registra ante un fallo de comunicación)
    necesita acordarse de sanearlo otra vez. Es la diferencia entre un dato seguro por
    construcción y un filtro que hay que recordar aplicar.

    Args:
        motivo: Valor recibido en el cuerpo de la respuesta. Se acepta `object` porque el
            JSON externo puede traer cualquier tipo, no necesariamente `str`.

    Returns:
        El mismo texto si respeta la forma de código estable, o `MOTIVO_NO_CANONICO`.
    """
    if isinstance(motivo, str) and _PATRON_MOTIVO_ESTABLE.match(motivo):
        return motivo
    return MOTIVO_NO_CANONICO


def describir_cuerpo_json(cuerpo: Any) -> str:
    """Describe la forma de un cuerpo JSON ya parseado, sin copiar claves ni valores.

    Es el reemplazo de los antiguos volcados `%r` del cuerpo de respuesta. Un 422 de
    FastAPI, por ejemplo, incluye en `detail` la entrada que rechazó: es decir, el propio
    `{"dispositivo": ..., "tecla": ...}` que el bridge acababa de enviar. Volcarlo dejaba
    el voto completo en el journal justamente en el camino de error.

    Se conserva el diagnóstico que sí importa para decidir qué hacer —«contestó un objeto
    con 3 claves» frente a «contestó una lista»— y se descarta todo lo demás. Tampoco se
    enumeran los nombres de las claves: `tecla` es un nombre de clave, y verlo aparecer en
    un log de una banca identificable ya sería una señal que WP-088 no quiere producir.

    Args:
        cuerpo: Valor devuelto por `json.loads`, de cualquier tipo.

    Returns:
        Descripción breve y no sensible de la forma del cuerpo.
    """
    if isinstance(cuerpo, dict):
        # `cast` sólo acota el genérico para Pyright estricto: no se lee ningún elemento,
        # únicamente se cuenta cuántos hay.
        return f"objeto JSON con {len(cast(dict[str, Any], cuerpo))} clave(s)"
    if isinstance(cuerpo, list):
        return f"arreglo JSON con {len(cast(list[Any], cuerpo))} elemento(s)"
    if cuerpo is None:
        return "JSON nulo"
    return f"valor JSON escalar de tipo {type(cuerpo).__name__}"


def describir_cuerpo_crudo(cuerpo_crudo: str) -> str:
    """Informa únicamente si un cuerpo de respuesta llegó vacío o no.

    El texto crudo no se registra nunca: cuando el cuerpo no es JSON válido, el bridge
    tampoco puede saber qué contiene, así que asumirlo inofensivo sería exactamente la
    suposición que WP-088 prohíbe.

    Tampoco se registra su **longitud**, aunque parezca un dato inocuo. La longitud de un
    cuerpo que ecoa la pulsación es una función directa de los valores que ecoa: un cuerpo
    que repite `POSITIVO` mide dos caracteres menos que el mismo cuerpo con `ABSTENCION`.
    Publicar el largo exacto sería, por lo tanto, publicar un canal lateral suficiente para
    distinguir sentidos de voto de una banca identificable. Lo detectó la propia prueba
    adversarial de indistinguibilidad de WP-088, y por eso la descripción se limita a la
    única dimensión que no depende de ningún valor: si hubo cuerpo o no lo hubo.

    Args:
        cuerpo_crudo: Texto recibido, ya decodificado a `str`.

    Returns:
        `"vacío"` o `"no vacío"`.
    """
    if not cuerpo_crudo.strip():
        return "vacío"
    return "no vacío"


def describir_tecla_no_funcional(nombre_tecla: str) -> str:
    """Devuelve el nombre de una tecla física sólo si el normalizador la rechaza.

    DEC-015 permite registrar de forma diagnóstica una tecla física desconocida, y es un
    dato genuinamente útil: es lo que permite reconocer que en una banca hay un modelo de
    botonera distinto al previsto. WP-088 mantiene ese diagnóstico porque una tecla que el
    normalizador rechaza **no puede ser** `1`, `2` ni `3`: por definición nunca se envía al
    backend y no tiene semántica de voto.

    La comprobación se repite acá aunque quien llama ya la haya hecho. No es redundancia
    inútil: convierte una garantía que hoy depende del orden de un `if` en una garantía del
    propio helper, de modo que una futura ampliación del catálogo de normalización no pueda
    transformar en silencio este mensaje en una filtración.

    Args:
        nombre_tecla: Nombre textual del evento físico (ej: `KEY_F13`).

    Returns:
        El nombre recibido si no normaliza a ninguna tecla de la API, o `TECLA_REDACTADA`.
    """
    if normalizar_tecla(nombre_tecla) is None:
        return nombre_tecla
    return TECLA_REDACTADA
