"""Servicio de dominio para la carga y descarte del Orden del Día (WP-016).

Este servicio orquesta la recepción, validación y mutación temporal del Orden
del Día en el contexto operativo activo de SIS-Leg.

Principios de funcionamiento y concurrencia:
1. Parseo fuera del lock: la decodificación y validación sintáctica/semántica
   del archivo CSV se realiza fuera de la sección crítica mediante la función
   pura :func:`parsear_orden_del_dia`. Si el archivo es inválido, la excepción
   se produce de inmediato sin adquirir el lock ni consumir tiempo del
   serializador global.
2. Canonicalización bajo el lock: recién después de obtener el contexto activo,
   cada tipo se compara con el snapshot congelado de ``voting.types``. El parser
   continúa siendo puro e independiente de configuración.
3. Instalación atómica bajo el serializador: la validación del estado operativo,
   la auditoría institucional y el reemplazo de la colección se ejecutan de
   forma exclusiva bajo el :class:`EjecutorMutaciones` único.
4. Auditoría previa (AUDITAR -> MUTAR): el evento de nivel L2
   (``ORDEN_DEL_DIA_CARGADO`` o ``ORDEN_DEL_DIA_DESCARTADO``) se escribe y
   sincroniza en disco antes de modificar la referencia en memoria. Si la
   auditoría falla, el estado previo permanece intacto (fallo cerrado).
5. Ciclo de vida compartido: la colección vive en :class:`Preparacion`, por lo
   que una carga realizada durante ``PREPARANDO`` sigue disponible al pasar a
   ``SESION_ABIERTA``.
6. Descarte no-op: si se solicita descartar cuando no había colección cargada,
   la operación es un no-op exitoso que no inventa un evento ficticio de
   descarte en los CSV.
"""

from __future__ import annotations

from dataclasses import replace

from sis_leg_backend.auditoria import NivelAuditoria
from sis_leg_backend.dominio.errores import ErrorEstadoIncompatible
from sis_leg_backend.dominio.estado import EstadoOperativo
from sis_leg_backend.dominio.orden_del_dia import (
    PuntoOrdenDelDia,
    canonicalizar_tipo_configurado,
    parsear_orden_del_dia,
)
from sis_leg_backend.servicios.serializacion import EjecutorMutaciones

ETIQUETA_ORDEN_DEL_DIA = "ORDEN_DEL_DIA"
CODIGO_ORDEN_DEL_DIA_CARGADO = "ORDEN_DEL_DIA_CARGADO"
CODIGO_ORDEN_DEL_DIA_DESCARTADO = "ORDEN_DEL_DIA_DESCARTADO"


class ServicioOrdenDelDia:
    """Orquesta las operaciones de carga y descarte del Orden del Día.

    El servicio no guarda estado propio: interactúa exclusivamente con el
    :class:`EstadoOperativo` y el :class:`EjecutorMutaciones` compartidos de
    la aplicación.
    """

    def __init__(
        self,
        estado_operativo: EstadoOperativo,
        ejecutor_mutaciones: EjecutorMutaciones,
    ) -> None:
        self._estado = estado_operativo
        self._ejecutor = ejecutor_mutaciones

    async def cargar_orden_del_dia(
        self,
        contenido_archivo: bytes,
    ) -> tuple[PuntoOrdenDelDia, ...]:
        """Parsea el archivo y lo instala atómicamente en el contexto activo.

        Paso 1 (fuera del lock): parseo y validación de todas las filas. Si una
        sola fila falla, se lanza :class:`ErrorOrdenDelDiaInvalido` y el estado
        vigente no se altera.

        Paso 2 (bajo el lock): revalidación de que existe un contexto operativo
        activo (``PREPARANDO`` o ``SESION_ABIERTA``), canonicalización de cada
        tipo contra el snapshot vigente, persistencia del evento L2
        ``ORDEN_DEL_DIA_CARGADO`` y reemplazo de la colección.

        Args:
            contenido_archivo: bytes crudos del CSV subido.

        Returns:
            Tupla de :class:`PuntoOrdenDelDia` normalizados instalados.

        Raises:
            ErrorOrdenDelDiaInvalido: si el archivo no es interpretable.
            ErrorEstadoIncompatible: si el backend está en ``SIN_PREPARAR``.
            ErrorAuditoria: si no puede persistirse el evento obligatorio.
        """
        # Paso 1: parseo puro fuera del lock.
        puntos = parsear_orden_del_dia(contenido_archivo)

        # Paso 2: instalación serializada.
        async def _instalar_bajo_lock() -> tuple[PuntoOrdenDelDia, ...]:
            contexto = self._estado.contexto_operativo_activo()
            if contexto is None:
                raise ErrorEstadoIncompatible(
                    "Solo puede cargarse el Orden del Día en PREPARANDO o SESION_ABIERTA "
                    f"(estado actual: {self._estado.estado_global.value})"
                )

            # El parser no conoce ``system.toml``. Recién acá, con el contexto
            # congelado y protegido por el serializador, reemplazamos sólo la
            # grafía del tipo cuando existe una coincidencia inequívoca. ``replace``
            # crea otro dataclass inmutable y deja intactos número, tema, mayoría,
            # factor y base.
            puntos_canonicalizados = tuple(
                replace(
                    punto,
                    tipo=canonicalizar_tipo_configurado(
                        punto.tipo,
                        contexto.configuracion.tipos_votacion,
                    ),
                )
                for punto in puntos
            )

            # Persistimos primero el evento institucional L2
            contexto.escritor_auditoria.registrar_evento(
                NivelAuditoria.L2,
                ETIQUETA_ORDEN_DEL_DIA,
                CODIGO_ORDEN_DEL_DIA_CARGADO,
                f"Orden del Día cargado con {len(puntos_canonicalizados)} punto(s) normalizado(s)",
            )

            # Reemplazamos la colección únicamente tras la auditoría exitosa
            contexto.orden_del_dia = puntos_canonicalizados
            return puntos_canonicalizados

        return await self._ejecutor.ejecutar(_instalar_bajo_lock)

    async def descartar_orden_del_dia(self) -> None:
        """Descarta la colección vigente del contexto operativo activo.

        Si existe una colección cargada:
        1. Persiste el evento L2 ``ORDEN_DEL_DIA_DESCARTADO``.
        2. Limpia la colección en memoria fijándola en ``None``.

        Si no había ninguna colección cargada:
        - Completa exitosamente como un no-op sin emitir evento ficticio.

        Raises:
            ErrorEstadoIncompatible: si el backend está en ``SIN_PREPARAR``.
            ErrorAuditoria: si no puede persistirse el evento obligatorio.
        """

        async def _descartar_bajo_lock() -> None:
            contexto = self._estado.contexto_operativo_activo()
            if contexto is None:
                raise ErrorEstadoIncompatible(
                    "Solo puede descartarse el Orden del Día en PREPARANDO o SESION_ABIERTA "
                    f"(estado actual: {self._estado.estado_global.value})"
                )

            if contexto.orden_del_dia is not None:
                contexto.escritor_auditoria.registrar_evento(
                    NivelAuditoria.L2,
                    ETIQUETA_ORDEN_DEL_DIA,
                    CODIGO_ORDEN_DEL_DIA_DESCARTADO,
                    "Orden del Día descartado",
                )
                contexto.orden_del_dia = None

        await self._ejecutor.ejecutar(_descartar_bajo_lock)
