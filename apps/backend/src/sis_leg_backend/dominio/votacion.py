"""Entidades y vocabulario canónico de una votación de SIS-Leg.

La entidad separa deliberadamente el estado de recepción del resultado
institucional. El cierre y la aplicación del resultado son dos transiciones
distintas: entre ambas existe ``CERRADA`` con ``resultado=None`` conforme a
DEC-010, aunque el flujo normal las encadena bajo una sola sección crítica.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType


class TipoMayoria(StrEnum):
    """Distingue la regla de decisión declarada por Moderación.

    El tipo es autoritativo: nunca se deduce una mayoría simple o especial a
    partir del factor. Los valores coinciden con el contrato REST de DEC-009.
    """

    SIMPLE = "SIMPLE"
    ESPECIAL = "ESPECIAL"


class BaseMayoria(StrEnum):
    """Representa el denominador conceptual de una regla de mayoría.

    ``VOTOS_COMPUTABLES`` cuenta positivos y negativos. ``PRESENTES`` es el
    término institucional para quienes emitieron voto ordinario en esa
    votación, incluidas abstenciones. ``CUERPO`` es el total del padrón
    congelado. La elección se almacena al abrir y WP-011 la consume al cerrar.
    """

    VOTOS_COMPUTABLES = "VOTOS_COMPUTABLES"
    PRESENTES = "PRESENTES"
    CUERPO = "CUERPO"


class EstadoVotacion(StrEnum):
    """Indica exclusivamente si la recepción todavía admite votos."""

    EN_CURSO = "EN_CURSO"
    CERRADA = "CERRADA"


class ResultadoVotacion(StrEnum):
    """Enumera las interpretaciones institucionales separadas de la recepción.

    El resultado ordinario puede asignar ``APROBADA``, ``RECHAZADA`` o
    ``EMPATADA``. ``INCONCLUSA`` permanece en el vocabulario para otros flujos,
    pero no es una salida válida del cálculo por completitud.
    """

    APROBADA = "APROBADA"
    RECHAZADA = "RECHAZADA"
    EMPATADA = "EMPATADA"
    INCONCLUSA = "INCONCLUSA"


class CausaFinalizacionInconclusa(StrEnum):
    """Distingue el hecho institucional que impidió un resultado ordinario.

    La causa no se almacena como motivo humano dentro de ``Votacion``: vive en
    la auditoría histórica. Solo ``MANUAL`` aporta además un texto del operador
    que sí queda disponible en la entidad mientras la sesión vive en memoria.
    """

    MANUAL = "MANUAL"
    PERDIDA_QUORUM = "PERDIDA_QUORUM"
    CIERRE_SESION = "CIERRE_SESION"


class ValorVotoOrdinario(StrEnum):
    """Representa los tres valores que puede emitir una banca mediante 1/2/3."""

    POSITIVO = "POSITIVO"
    ABSTENCION = "ABSTENCION"
    NEGATIVO = "NEGATIVO"


class SentidoVotoDesempate(StrEnum):
    """Limita la decisión presidencial a los dos sentidos reglamentarios."""

    POSITIVO = "POSITIVO"
    NEGATIVO = "NEGATIVO"


@dataclass(frozen=True, slots=True)
class VotoOrdinario:
    """Conserva el voto irreversible de un concejal dentro de una votación.

    El DNI vincula el hecho con el padrón congelado y ``frozen=True`` impide
    cambiar su identidad o valor después de aceptarlo. Los intentos posteriores
    se auditan como rechazos, pero nunca reemplazan esta instancia.
    """

    dni: str
    valor: ValorVotoOrdinario


@dataclass(frozen=True, slots=True)
class VotoDesempate:
    """Conserva la decisión irreversible de la Presidencia vigente.

    No contiene DNI ni banca porque Presidencia y Concejal son roles
    independientes. ``frozen=True`` impide reescribir retrospectivamente la
    identidad o el sentido aunque luego cambie la autoridad de la sesión.
    """

    presidencia: str
    sentido: SentidoVotoDesempate

    @property
    def resultado_final(self) -> ResultadoVotacion:
        """Deriva el resultado sin recalcular ni alterar los votos ordinarios."""

        if self.sentido is SentidoVotoDesempate.POSITIVO:
            return ResultadoVotacion.APROBADA
        return ResultadoVotacion.RECHAZADA


@dataclass(frozen=True, slots=True)
class ConteosVotosOrdinarios:
    """Resume los votos almacenados sin convertirse en otra fuente de verdad.

    La estructura se construye de nuevo desde ``Votacion.votos_ordinarios`` en
    cada cálculo. Sirve para transportar los tres conteos y sus dos sumas
    derivadas hacia la auditoría, pero nunca conserva ni reemplaza votos.
    """

    positivos: int
    negativos: int
    abstenciones: int

    @property
    def votos_emitidos(self) -> int:
        """Cuenta todos los votos ordinarios, incluidas las abstenciones."""

        return self.positivos + self.negativos + self.abstenciones

    @property
    def votos_computables(self) -> int:
        """Cuenta solo positivos y negativos, como exige esa base."""

        return self.positivos + self.negativos


@dataclass(frozen=True, slots=True)
class CalculoResultadoVotacion:
    """Describe una decisión calculada que todavía no fue aplicada.

    Separar el cálculo de la mutación permite persistir primero el hecho
    institucional. ``denominador`` y ``cociente`` se completan para mayorías
    especiales; el cociente queda ausente en el caso documentado de
    ``VOTOS_COMPUTABLES=0`` para demostrar que no hubo división por cero.
    """

    resultado: ResultadoVotacion
    conteos: ConteosVotosOrdinarios
    denominador: int | None
    cociente: float | None


@dataclass(frozen=True, slots=True)
class DatosAperturaVotacion:
    """Transporta al servicio los datos ya normalizados de una apertura.

    La capa Pydantic valida el body discriminado y convierte omisiones de una
    mayoría simple en ``factor=0`` y ``base=VOTOS_COMPUTABLES``. Esta estructura
    desacopla el servicio de FastAPI sin duplicar el modelo HTTP.
    """

    numero_votacion: int
    tipo: str
    tema: str
    tipo_mayoria: TipoMayoria
    factor: float
    base: BaseMayoria


@dataclass(frozen=True, slots=True)
class DatosConstitutivosVotacion:
    """Agrupa los metadatos que nunca cambian después de abrir.

    ``frozen=True`` impide reasignar cualquiera de estos campos. Separarlos del
    estado evolutivo permite que futuros WPs agreguen votos, cierre o desempate
    sin volver editables los datos que identifican la decisión institucional.
    """

    id: str
    numero_votacion: int
    tipo: str
    tema: str
    tipo_mayoria: TipoMayoria
    factor: float
    base: BaseMayoria
    fecha_hora_apertura: datetime


class Votacion:
    """Representa una única votación publicada en historial y estado activo.

    La entidad encapsula los datos constitutivos congelados y mantiene en una
    única instancia el estado evolutivo autorizado. Los votos se indexan por
    DNI para que la unicidad sea estructural y se exponen mediante una vista de
    solo lectura; no existe operación para reemplazarlos o eliminarlos.
    """

    __slots__ = (
        "__datos_constitutivos",
        "__estado",
        "__fecha_hora_cierre",
        "__fecha_hora_resultado",
        "__motivo_finalizacion_manual",
        "__resultado",
        "__voto_desempate",
        "__votos_ordinarios",
    )

    def __init__(
        self,
        *,
        id: str,
        numero_votacion: int,
        tipo: str,
        tema: str,
        tipo_mayoria: TipoMayoria,
        factor: float,
        base: BaseMayoria,
        fecha_hora_apertura: datetime,
    ) -> None:
        """Crea una votación exclusivamente en el estado inicial ``EN_CURSO``."""

        self.__datos_constitutivos = DatosConstitutivosVotacion(
            id=id,
            numero_votacion=numero_votacion,
            tipo=tipo,
            tema=tema,
            tipo_mayoria=tipo_mayoria,
            factor=factor,
            base=base,
            fecha_hora_apertura=fecha_hora_apertura,
        )
        self.__estado = EstadoVotacion.EN_CURSO
        self.__fecha_hora_cierre: datetime | None = None
        self.__fecha_hora_resultado: datetime | None = None
        self.__motivo_finalizacion_manual: str | None = None
        self.__resultado: ResultadoVotacion | None = None
        self.__voto_desempate: VotoDesempate | None = None
        self.__votos_ordinarios: dict[str, VotoOrdinario] = {}

    @property
    def estado(self) -> EstadoVotacion:
        """Devuelve si la recepción continúa abierta o ya quedó cerrada."""

        return self.__estado

    @property
    def resultado(self) -> ResultadoVotacion | None:
        """Devuelve el resultado institucional o ``None`` antes de aplicarlo."""

        return self.__resultado

    @property
    def fecha_hora_cierre(self) -> datetime | None:
        """Devuelve el único instante de cierre o ``None`` mientras está abierta."""

        return self.__fecha_hora_cierre

    @property
    def fecha_hora_resultado(self) -> datetime | None:
        """Marca volátil cuándo el resultado vigente quedó disponible.

        No es un nuevo hecho institucional ni se persiste. La proyección
        pública la usa únicamente para calcular su ventana transitoria. En un
        desempate tardío difiere deliberadamente de ``fecha_hora_cierre``.
        """

        return self.__fecha_hora_resultado

    @property
    def motivo_finalizacion_manual(self) -> str | None:
        """Devuelve el motivo humano solo cuando la finalización fue manual.

        Pérdida de quórum, cierre de sesión y completitud normal no reutilizan
        este campo para guardar códigos institucionales. Al no existir setter y
        admitirse una sola transición, el valor queda inmutable.
        """

        return self.__motivo_finalizacion_manual

    @property
    def voto_desempate(self) -> VotoDesempate | None:
        """Devuelve el único voto presidencial, separado de los ordinarios."""

        return self.__voto_desempate

    @property
    def votos_ordinarios(self) -> Mapping[str, VotoOrdinario]:
        """Expone los votos por DNI sin permitir editar el diccionario interno.

        ``MappingProxyType`` es una vista viva de solo lectura. Así el historial
        y ``votacion_activa`` observan siempre el mismo conjunto autoritativo,
        pero ningún consumidor puede borrar o sustituir un voto directamente.
        """

        return MappingProxyType(self.__votos_ordinarios)

    def contar_votos_ordinarios(self) -> ConteosVotosOrdinarios:
        """Expone un resumen inmutable derivado del mapa autoritativo de votos.

        El desempate usa este resumen solo para demostrar en auditoría que los
        conteos ordinarios se preservaron. El resumen no incorpora el voto de
        Presidencia ni se convierte en una segunda fuente de verdad.
        """

        return self._contar_votos_ordinarios()

    def preparar_voto_desempate(
        self,
        sentido: SentidoVotoDesempate,
        presidencia: str,
    ) -> VotoDesempate:
        """Valida sin mutar y construye la decisión presidencial candidata.

        Esta fase permite que el servicio forme y persista el primer hecho L3
        antes de almacenar el voto. No se consulta quórum: la recepción ya está
        cerrada y la pérdida posterior no invalida un empate.

        Raises:
            ValueError: si no existe exactamente ``CERRADA + EMPATADA + SIMPLE``,
                ya hay voto presidencial o la identidad de Presidencia es vacía.
        """

        self._validar_desempate_pendiente()
        presidencia_normalizada = presidencia.strip()
        if not presidencia_normalizada:
            raise ValueError("El desempate exige una Presidencia vigente")
        return VotoDesempate(
            presidencia=presidencia_normalizada,
            sentido=sentido,
        )

    def registrar_voto_desempate(self, voto: VotoDesempate) -> None:
        """Almacena una sola vez el voto después de su primer hecho durable.

        La entidad permanece ``CERRADA + EMPATADA``. Ese estado intermedio es
        deliberado: el resultado final todavía no puede aplicarse hasta que su
        segundo evento institucional haya sido persistido.
        """

        self._validar_desempate_pendiente()
        self.__voto_desempate = voto

    def consolidar_resultado_desempate(
        self,
        fecha_hora_resultado: datetime | None = None,
    ) -> None:
        """Aplica determinísticamente el resultado del voto ya almacenado.

        El servicio invoca esta primitiva solo después de auditar el segundo
        hecho L3. No llama al cálculo de mayoría simple: ``POSITIVO`` conduce a
        ``APROBADA`` y ``NEGATIVO`` a ``RECHAZADA`` de forma directa.
        """

        voto = self.__voto_desempate
        if voto is None:
            raise ValueError("No existe un voto presidencial para consolidar")
        if self.__estado is not EstadoVotacion.CERRADA:
            raise ValueError("El desempate debe conservar la votación CERRADA")
        if self.__resultado is not ResultadoVotacion.EMPATADA:
            raise ValueError("Solo un empate puede consolidar desempate")
        if self.tipo_mayoria is not TipoMayoria.SIMPLE:
            raise ValueError("Una mayoría especial no admite desempate")
        self.__resultado = voto.resultado_final
        self.__fecha_hora_resultado = fecha_hora_resultado or self.__fecha_hora_cierre

    def _validar_desempate_pendiente(self) -> None:
        """Protege la precondición exacta y la unicidad del voto presidencial."""

        if self.__voto_desempate is not None:
            raise ValueError("El voto presidencial ya fue emitido")
        if self.__estado is not EstadoVotacion.CERRADA:
            raise ValueError("El desempate exige una votación CERRADA")
        if self.__resultado is not ResultadoVotacion.EMPATADA:
            raise ValueError("El desempate exige resultado EMPATADA")
        if self.tipo_mayoria is not TipoMayoria.SIMPLE:
            raise ValueError("Una mayoría especial no admite desempate")
        if self.__fecha_hora_cierre is None:
            raise ValueError("Una votación empatada debe conservar fecha de cierre")

    def ya_emitio_voto(self, dni_concejal: str) -> bool:
        """Indica si el DNI ya consumió su único voto en esta votación."""

        return dni_concejal in self.__votos_ordinarios

    def registrar_voto(self, voto: VotoOrdinario) -> None:
        """Incorpora el primer voto de un DNI durante una recepción abierta.

        El servicio llama a este método únicamente después de persistir el
        evento L3. Las validaciones internas protegen además la entidad frente a
        un uso incorrecto: nunca se sobrescribe un valor existente.

        Raises:
            ValueError: si la recepción ya cerró o el DNI ya tiene un voto.
        """

        if self.__estado is not EstadoVotacion.EN_CURSO:
            raise ValueError("La recepción de votos ya está cerrada")
        if voto.dni in self.__votos_ordinarios:
            raise ValueError("El concejal ya emitió su voto ordinario")
        self.__votos_ordinarios[voto.dni] = voto

    def cerrar_recepcion(self, fecha_hora_cierre: datetime) -> None:
        """Cierra una sola vez la recepción sin calcular resultado institucional.

        El llamador debe persistir antes el evento de autocierre. Mantener la
        transición encapsulada garantiza que la fecha no pueda regenerarse y
        que el resultado continúe en ``None`` hasta su auditoría separada.

        Raises:
            ValueError: si la recepción ya había sido cerrada.
        """

        if self.__estado is not EstadoVotacion.EN_CURSO:
            raise ValueError("La recepción de votos ya fue cerrada")
        self.__fecha_hora_cierre = fecha_hora_cierre
        self.__estado = EstadoVotacion.CERRADA

    def validar_finalizacion_inconclusa_manual(self, motivo: str) -> str:
        """Valida sin mutar y devuelve el motivo manual normalizado.

        Esta separación permite que el servicio construya y persista el hecho
        completo antes de aplicar la transición. El dominio vuelve a validar al
        mutar para protegerse también de usos internos incorrectos.

        Raises:
            ValueError: si no está ``EN_CURSO + None`` o el motivo queda vacío.
        """

        self._validar_recepcion_finalizable_inconclusa()
        normalizado = motivo.strip()
        if not normalizado:
            raise ValueError("El motivo manual no puede quedar vacío")
        if self.__motivo_finalizacion_manual is not None:
            raise ValueError("El motivo manual ya fue establecido")
        return normalizado

    def finalizar_inconclusa_manual(
        self,
        fecha_hora_cierre: datetime,
        motivo: str,
        fecha_hora_resultado: datetime | None = None,
    ) -> None:
        """Aplica ``CERRADA + INCONCLUSA`` y conserva el motivo humano.

        El servicio debe haber auditado el hecho antes de invocar este método.
        No se calcula mayoría ni se modifica ningún voto o dato constitutivo.
        """

        normalizado = self.validar_finalizacion_inconclusa_manual(motivo)
        self._aplicar_finalizacion_inconclusa(
            fecha_hora_cierre,
            fecha_hora_resultado or fecha_hora_cierre,
        )
        self.__motivo_finalizacion_manual = normalizado

    def validar_finalizacion_inconclusa_derivada(self) -> None:
        """Comprueba la transición ``EN_CURSO + None`` sin asignar motivo."""

        self._validar_recepcion_finalizable_inconclusa()

    def finalizar_inconclusa_derivada(
        self,
        fecha_hora_cierre: datetime,
        fecha_hora_resultado: datetime | None = None,
    ) -> None:
        """Finaliza por quórum o sesión sin inventar un motivo manual."""

        self.validar_finalizacion_inconclusa_derivada()
        self._aplicar_finalizacion_inconclusa(
            fecha_hora_cierre,
            fecha_hora_resultado or fecha_hora_cierre,
        )

    def validar_empate_inconcluso_por_cierre_sesion(self) -> None:
        """Valida la excepción ``EMPATADA -> INCONCLUSA`` de cierre de sesión.

        El nombre deliberadamente específico evita convertir ``resultado`` en
        un setter general. La finalización manual nunca utiliza esta primitiva.
        """

        if self.__estado is not EstadoVotacion.CERRADA:
            raise ValueError("El empate pendiente debe permanecer CERRADA")
        if self.__resultado is not ResultadoVotacion.EMPATADA:
            raise ValueError("Solo un empate puede resolverse por este flujo")
        if self.__fecha_hora_cierre is None:
            raise ValueError("Una votación empatada debe conservar fecha de cierre")
        if self.__motivo_finalizacion_manual is not None:
            raise ValueError("Un empate no puede tener motivo de finalización manual")

    def finalizar_empate_inconcluso_por_cierre_sesion(
        self,
        fecha_hora_resultado: datetime | None = None,
    ) -> None:
        """Cambia solo el resultado del empate al cerrar explícitamente sesión.

        La fecha de cierre y los votos no se tocan: ambos pertenecen al cierre
        normal que produjo el empate y deben conservar su identidad histórica.
        """

        self.validar_empate_inconcluso_por_cierre_sesion()
        self.__resultado = ResultadoVotacion.INCONCLUSA
        self.__fecha_hora_resultado = fecha_hora_resultado or self.__fecha_hora_cierre

    def _validar_recepcion_finalizable_inconclusa(self) -> None:
        """Exige exactamente la recepción abierta sin resultado de DEC-011."""

        if self.__estado is not EstadoVotacion.EN_CURSO or self.__resultado is not None:
            raise ValueError("La votación no está EN_CURSO sin resultado")
        if self.__fecha_hora_cierre is not None:
            raise ValueError("Una recepción abierta no puede tener fecha de cierre")
        if self.__motivo_finalizacion_manual is not None:
            raise ValueError("Una recepción abierta no puede tener motivo manual")

    def _aplicar_finalizacion_inconclusa(
        self,
        fecha_hora_cierre: datetime,
        fecha_hora_resultado: datetime,
    ) -> None:
        """Realiza una vez la mutación común después de validación y auditoría."""

        self.__fecha_hora_cierre = fecha_hora_cierre
        self.__estado = EstadoVotacion.CERRADA
        self.__resultado = ResultadoVotacion.INCONCLUSA
        self.__fecha_hora_resultado = fecha_hora_resultado

    def calcular_resultado_ordinario(
        self,
        *,
        cantidad_total_cuerpo: int,
    ) -> CalculoResultadoVotacion:
        """Calcula, sin mutar, el resultado ordinario de una votación cerrada.

        La única fuente de los conteos es el mapa de votos de esta instancia.
        Para ``CUERPO`` el llamador aporta la cantidad del padrón congelado de
        la sesión; nunca se relee configuración ni se consulta presencia actual.
        La comparación especial usa directamente ``cociente >= factor`` sin
        redondeo, epsilon ni tolerancia.

        Args:
            cantidad_total_cuerpo: total de concejales del padrón congelado.

        Returns:
            El resultado y los datos exactos que explican su cálculo, todavía
            sin modificar ``resultado``.

        Raises:
            ValueError: si la recepción sigue abierta, ya existe un resultado o
                el contexto recibido viola una invariante constitutiva.
        """

        self._validar_resultado_ordinario_pendiente()
        conteos = self._contar_votos_ordinarios()

        if self.tipo_mayoria is TipoMayoria.SIMPLE:
            if conteos.positivos > conteos.negativos:
                resultado = ResultadoVotacion.APROBADA
            elif conteos.positivos < conteos.negativos:
                resultado = ResultadoVotacion.RECHAZADA
            else:
                resultado = ResultadoVotacion.EMPATADA
            return CalculoResultadoVotacion(
                resultado=resultado,
                conteos=conteos,
                denominador=None,
                cociente=None,
            )

        if self.base is BaseMayoria.VOTOS_COMPUTABLES:
            denominador = conteos.votos_computables
        elif self.base is BaseMayoria.PRESENTES:
            # PRESENTES es una denominación institucional: técnicamente son
            # quienes lograron votar, incluidas las abstenciones. No se mira el
            # mapa dinámico de presencia al momento de calcular.
            denominador = conteos.votos_emitidos
        elif self.base is BaseMayoria.CUERPO:
            denominador = cantidad_total_cuerpo
        else:  # pragma: no cover - el enum cerrado hace defensiva esta rama.
            raise ValueError("Base de mayoría especial desconocida")

        if denominador == 0:
            if self.base is not BaseMayoria.VOTOS_COMPUTABLES:
                raise ValueError("La base especial no puede tener denominador cero")
            return CalculoResultadoVotacion(
                resultado=ResultadoVotacion.RECHAZADA,
                conteos=conteos,
                denominador=0,
                cociente=None,
            )
        if denominador < 0:
            raise ValueError("El denominador de una mayoría no puede ser negativo")

        cociente = conteos.positivos / denominador
        resultado = (
            ResultadoVotacion.APROBADA if cociente >= self.factor else ResultadoVotacion.RECHAZADA
        )
        return CalculoResultadoVotacion(
            resultado=resultado,
            conteos=conteos,
            denominador=denominador,
            cociente=cociente,
        )

    def aplicar_resultado_ordinario(
        self,
        resultado: ResultadoVotacion,
        fecha_hora_resultado: datetime | None = None,
    ) -> None:
        """Aplica una sola vez un resultado ordinario previamente auditado.

        Este método no vuelve a contar votos ni modifica cierre, datos
        constitutivos o votos. Sus validaciones protegen la entidad aun si un
        servicio interno intenta usarla fuera de la transición autorizada.

        Raises:
            ValueError: si la votación no está ``CERRADA + None``, se intenta
                producir ``INCONCLUSA`` o una ESPECIAL intenta quedar empatada.
        """

        self._validar_resultado_ordinario_pendiente()
        if resultado not in (
            ResultadoVotacion.APROBADA,
            ResultadoVotacion.RECHAZADA,
            ResultadoVotacion.EMPATADA,
        ):
            raise ValueError("El flujo ordinario no admite ese resultado")
        if self.tipo_mayoria is TipoMayoria.ESPECIAL and resultado is ResultadoVotacion.EMPATADA:
            raise ValueError("Una mayoría especial no puede quedar EMPATADA")
        self.__resultado = resultado
        self.__fecha_hora_resultado = fecha_hora_resultado or self.__fecha_hora_cierre

    def _validar_resultado_ordinario_pendiente(self) -> None:
        """Exige la etapa intermedia exacta autorizada por DEC-010."""

        if self.__estado is not EstadoVotacion.CERRADA:
            raise ValueError("Solo una votación cerrada puede recibir resultado")
        if self.__resultado is not None:
            raise ValueError("La votación ya posee un resultado irreversible")

    def _contar_votos_ordinarios(self) -> ConteosVotosOrdinarios:
        """Deriva los conteos directamente de los votos de esta instancia."""

        positivos = 0
        negativos = 0
        abstenciones = 0
        for voto in self.__votos_ordinarios.values():
            if voto.valor is ValorVotoOrdinario.POSITIVO:
                positivos += 1
            elif voto.valor is ValorVotoOrdinario.NEGATIVO:
                negativos += 1
            else:
                abstenciones += 1
        return ConteosVotosOrdinarios(
            positivos=positivos,
            negativos=negativos,
            abstenciones=abstenciones,
        )

    @property
    def id(self) -> str:
        """Devuelve el identificador técnico opaco generado por backend."""

        return self.__datos_constitutivos.id

    @property
    def numero_votacion(self) -> int:
        """Devuelve el número institucional externo, sin imponer secuencia."""

        return self.__datos_constitutivos.numero_votacion

    @property
    def tipo(self) -> str:
        """Devuelve el tipo descriptivo validado contra la sesión congelada."""

        return self.__datos_constitutivos.tipo

    @property
    def tema(self) -> str:
        """Devuelve el tema libre normalizado al abrir."""

        return self.__datos_constitutivos.tema

    @property
    def tipo_mayoria(self) -> TipoMayoria:
        """Devuelve la regla SIMPLE o ESPECIAL declarada explícitamente."""

        return self.__datos_constitutivos.tipo_mayoria

    @property
    def factor(self) -> float:
        """Devuelve el factor normalizado; SIMPLE siempre expone cero."""

        return self.__datos_constitutivos.factor

    @property
    def base(self) -> BaseMayoria:
        """Devuelve una de las tres bases canónicas de DEC-009."""

        return self.__datos_constitutivos.base

    @property
    def fecha_hora_apertura(self) -> datetime:
        """Devuelve la hora civil inmutable en que se abrió la votación."""

        return self.__datos_constitutivos.fecha_hora_apertura
