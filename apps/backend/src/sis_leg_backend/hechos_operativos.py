"""Vocabulario estructurado que acompaña en memoria a un evento de auditoría.

## Por qué existe este módulo

La auditoría institucional persiste seis columnas fijas
(``seq;timestamp;level;tag;event_code;message``) y su columna ``message`` está
escrita para que la lea una persona. Ese texto es completo a propósito: el CSV
durable debe conservar, por ejemplo, que tal concejal votó ``POSITIVO``.

Moderación, en cambio, ve el listado de eventos **mientras la votación sigue en
curso**. Si la proyección enviara ese mismo texto, el secreto del voto se
perdería en la propia pantalla del operador. Y si el frontend intentara
resolverlo "parseando" el mensaje, quedaría acoplado a una redacción humana que
puede cambiar en cualquier momento: eso convertiría al mensaje en un contrato
de UI encubierto.

WP-052 resuelve las dos cosas con una única idea: al registrar un evento, quien
lo emite puede adjuntar una **referencia estructurada** que describe el hecho
con campos estables y, cuando el mensaje durable revela un secreto, propone
además un texto alternativo seguro.

## Qué NO es esta referencia

- No se persiste en los CSV. El formato canónico de seis columnas no cambia y
  la auditoría histórica no se reescribe.
- No es un segundo registro institucional. Vive únicamente junto al buffer de
  200 eventos recientes del escritor activo y desaparece con él.
- No decide por sí sola qué se muestra. La frontera de secreto la evalúa la
  proyección (:mod:`sis_leg_backend.servicios.proyecciones`) contra el estado
  autoritativo vigente, nunca este dato adjunto.

El módulo no importa nada del resto del backend justamente para poder ser usado
tanto por la capa de auditoría como por los servicios de dominio sin crear
dependencias circulares.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TipoHechoOperativo(StrEnum):
    """Clasifica el hecho para que la UI no tenga que interpretar textos.

    Es un vocabulario cerrado y pequeño: solo entran los hechos que Moderación
    necesita presentar de forma enriquecida o proteger durante el secreto del
    voto. Agregar un código de auditoría nuevo no obliga a agregar un tipo aquí;
    los eventos sin referencia se siguen mostrando con su mensaje humano.

    Miembros:
        VOTO_ORDINARIO: un voto individual ya auditado. Su sentido es secreto
            hasta que la frontera autoritativa de la votación lo habilita.
        PEDIDO_PALABRA: un concejal pidió la palabra.
        RETIRO_PALABRA: un concejal retiró su propio pedido de palabra.
        PULSACION_DE_VOTO: entrada física de teclas 1/2/3 recibida o rechazada
            mientras hay una recepción abierta. No es un hecho institucional
            que Moderación deba presentar con identidad e icono, pero su
            mensaje técnico (``tecla [1]`` + ``dispositivo``) permitiría deducir
            el sentido de un voto, así que también necesita texto seguro.
    """

    VOTO_ORDINARIO = "VOTO_ORDINARIO"
    PEDIDO_PALABRA = "PEDIDO_PALABRA"
    RETIRO_PALABRA = "RETIRO_PALABRA"
    PULSACION_DE_VOTO = "PULSACION_DE_VOTO"


@dataclass(frozen=True, slots=True)
class ReferenciaHechoOperativo:
    """Describe un evento con datos estables en lugar de texto libre.

    Atributos:
        tipo: clasificación cerrada del hecho.
        dni: concejal referido, resuelto contra el padrón congelado por quien
            proyecta. Se guarda el DNI y no nombre/banca para no duplicar en
            memoria una identidad que ya tiene una única fuente de verdad.
            Es ``None`` cuando el hecho no pertenece a un concejal
            individualizable en la proyección, como una pulsación cuyo
            dispositivo todavía no se resolvió.
        votacion_id: votación a la que pertenece el secreto. Es la clave que
            permite evaluar la frontera de revelado de **esa** votación y no la
            de la votación que casualmente esté activa al generar el snapshot.
            ``None`` significa que el hecho no depende de ninguna frontera.
        mensaje_seguro: redacción alternativa que puede publicarse mientras el
            sentido individual siga siendo secreto. ``None`` significa que el
            mensaje durable ya es seguro y puede publicarse siempre.
    """

    tipo: TipoHechoOperativo
    dni: str | None = None
    votacion_id: str | None = None
    mensaje_seguro: str | None = None
