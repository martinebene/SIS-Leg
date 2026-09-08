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
- de un motivo devuelto por el backend sólo se acepta un valor que figure en un catálogo
  explícito de códigos verificados uno por uno, y cualquier otro texto se reemplaza por un
  marcador único; respetar una sintaxis no alcanza, porque `DEV07_VOTO_1` también la
  respeta;
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

from typing import Any, cast

from sis_leg_device_bridge.normalizador import normalizar_tecla

# Marcador único con el que se reemplaza cualquier motivo que no pertenezca al catálogo
# conocido. Es deliberadamente **uno solo**: publicar dos marcadores distintos —por ejemplo
# «no canónico» frente a «desconocido»— comunicaría un bit de información derivado del
# contenido externo, y un bit por pulsación alcanza para distinguir dos sentidos de voto.
MOTIVO_DESCONOCIDO = "MOTIVO_DESCONOCIDO"

# Marcador que reemplaza al nombre de una tecla cuando no se puede demostrar que sea
# no funcional. Es la salida conservadora exigida por WP-088 ante cualquier ambigüedad.
TECLA_REDACTADA = "REDACTADA"

# Catálogo cerrado de motivos funcionales que `POST /api/v1/entradas/tecla` puede devolver
# en una respuesta 2xx. Son las doce clasificaciones que el backend define en
# `servicios/entrada.py`. Ninguna contiene identidad de banca ni sentido de voto: las tres
# teclas de votación producen el mismo `VOTO_REGISTRADO`, que dice **que** hubo voto y no
# **cuál** fue.
_MOTIVOS_FUNCIONALES_BACKEND = frozenset(
    {
        "VOTO_REGISTRADO",
        "PRESENCIA_ACTUALIZADA",
        "TEST_ACTIVADO",
        "SIN_PREPARAR",
        "DISPOSITIVO_NO_ASIGNADO",
        "TECLA_NO_HABILITADA",
        "VOTACION_NO_EN_CURSO",
        "CONCEJAL_AUSENTE",
        "VOTO_YA_EMITIDO",
        "PEDIDO_PALABRA_REGISTRADO",
        "PEDIDO_PALABRA_RETIRADO",
        "USO_PALABRA_FINALIZADO",
    }
)

# Catálogo cerrado de códigos de error estables que el backend publica en el campo
# `codigo` de su envoltura de error (`api/errores.py` y el manejador genérico de
# `aplicacion.py`). Todos nombran una categoría técnica o institucional del fallo; ninguno
# transporta datos de la pulsación que lo provocó.
_CODIGOS_ERROR_BACKEND = frozenset(
    {
        "ERROR_INTERNO",
        "CONFIGURACION_INVALIDA",
        "PADRON_INVALIDO",
        "AUDITORIA_NO_DISPONIBLE",
        "BRIDGE_NO_DISPONIBLE",
        "APLICACION_BRIDGE_RECHAZADA",
        "BIBLIOTECA_MENSAJES_INVALIDA",
        "PERSISTENCIA_MENSAJES_FALLIDA",
        "MENSAJE_TECNICO_NO_EXISTENTE",
        "ESTADO_INCOMPATIBLE",
        "QUORUM_INSUFICIENTE",
        "NUMERO_SESION_REQUERIDO",
        "PRESIDENCIA_REQUERIDA",
        "SECRETARIA_LEGISLATIVA_REQUERIDA",
        "VOTACION_PENDIENTE",
        "VOTACION_NO_COINCIDE",
        "VOTACION_NO_EMPATADA",
        "VOTACION_NO_EN_CURSO",
        "DESEMPATE_YA_EMITIDO",
        "DISPOSITIVO_REMAPEO_NO_EXISTENTE",
        "REMAPEO_YA_ACTIVO",
        "REMAPEO_NO_COINCIDE",
        "REMAPEO_SIN_CANDIDATO",
        "CANDIDATO_YA_REGISTRADO",
        "PARAMETROS_REMAPEO_INCOMPATIBLES",
        "TIPO_VOTACION_NO_PERMITIDO",
        "ORDEN_DEL_DIA_INVALIDO",
    }
)

# Unión de ambos: el único conjunto de textos de origen externo que el bridge acepta
# reproducir en su registro.
MOTIVOS_CONOCIDOS = _MOTIVOS_FUNCIONALES_BACKEND | _CODIGOS_ERROR_BACKEND


def sanear_motivo(motivo: object) -> str:
    """Devuelve el motivo sólo si pertenece al catálogo conocido; si no, un marcador.

    Por qué una allowlist explícita y no una regla de forma
    -------------------------------------------------------

    La primera versión de esta función aceptaba cualquier texto que *pareciera* un código
    estable, comprobando con una expresión regular que fuese MAYUSCULAS_CON_GUION_BAJO. Esa
    comprobación valida **forma** y no **contenido**, así que dejaba pasar intactos valores
    como `DEV07_VOTO_1`, `VOTO_POSITIVO_DEV07` o `ABSTENCION_BANCA_7`, que después se
    registraban junto al dispositivo lógico. Un backend o intermediario mal configurado que
    colocara datos ecoados en ese campo reabría exactamente la fuga que WP-088 cierra.

    La lección es general y conviene no perderla: que un dato de origen externo respete una
    sintaxis no demuestra que sea inofensivo. Sólo una enumeración explícita de valores
    verificados uno por uno lo demuestra, y por eso el catálogo de arriba se construyó
    leyendo el contrato real del backend en lugar de describir un patrón.

    Comportamiento fail-closed
    --------------------------

    Un motivo legítimo que el backend agregue en el futuro y que todavía no figure acá
    quedará clasificado como `MOTIVO_DESCONOCIDO`. Es la degradación deliberada y correcta:
    se pierde una etiqueta de diagnóstico, no la capacidad de diagnosticar, porque el código
    HTTP, la clase de resultado y el detalle de transporte siguen registrándose. Ampliar el
    catálogo es entonces un acto consciente y revisable, que es justamente lo que la regla
    de forma no exigía.

    Dónde se aplica
    ---------------

    Se sanea en el **ingreso** al bridge y no en cada punto de logging: así el valor que
    queda guardado en `RespuestaEnvioBackend.motivo` ya es seguro y ningún consumidor
    posterior (por ejemplo el servicio, que lo registra ante un fallo de comunicación)
    necesita acordarse de sanearlo otra vez. Es la diferencia entre un dato seguro por
    construcción y un filtro que hay que recordar aplicar.

    Los motivos que fabrica el propio bridge (`TIMEOUT`, `ERROR_CONEXION`, `HTTP_422`,
    `RESPUESTA_NO_JSON`…) no pasan por acá: no son de origen externo, así que no hay nada
    que autorizar.

    Args:
        motivo: Valor recibido en el cuerpo de la respuesta. Se acepta `object` porque el
            JSON externo puede traer cualquier tipo, no necesariamente `str`.

    Returns:
        El mismo texto si pertenece al catálogo conocido, o `MOTIVO_DESCONOCIDO`.
    """
    if isinstance(motivo, str) and motivo in MOTIVOS_CONOCIDOS:
        return motivo
    return MOTIVO_DESCONOCIDO


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
