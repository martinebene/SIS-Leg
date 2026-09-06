"""Servicio orquestador del bridge de dispositivos físicos.

Este módulo implementa `ServicioDeviceBridge`, el componente central que coordina:
1. El descubrimiento periódico de hardware mediante `AdaptadorEntradaFisica`.
2. La resolución estricta de `fingerprint -> devXX` usando `devices.json`.
3. La normalización amplia de teclas físicas mediante `normalizar_tecla`.
4. El envío determinista de pulsaciones hacia FastAPI mediante `ClienteHttpBackend`.
5. El ciclo de vida resiliente del proceso (tolerancia a cero dispositivos iniciales,
   desconexión y reconexión en caliente de hardware, y parada limpia ante señales).
6. La política de captura exclusiva (WP-075): pide al adaptador tomar en exclusiva
   únicamente los dispositivos del mapping efectivo, para que sus pulsaciones no lleguen
   al escritorio ni al navegador de Moderación.

Invariantes críticas:
- Cero asignación automática: Un fingerprint no presente en `devices.json` NUNCA
  recibe un `devXX` ni emite POST al backend.
- Cero reintentos: Cada evento físico `keydown` emite a lo sumo un POST.
- No decide reglas de negocio: El bridge no evalúa presencia, quórum, voto ni palabra.
- Exclusividad fail-safe: un dispositivo mapeado sin exclusividad no despacha pulsaciones
  funcionales; nunca se degrada silenciosamente a captura compartida.
- Ningún dispositivo fuera del mapping efectivo se toma en exclusiva, de modo que el
  teclado y el mouse del moderador siguen funcionando con normalidad.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

from botonera2_device_bridge.adaptador_linux import (
    AdaptadorEntradaFisica,
    DispositivoFisico,
    ErrorDispositivoDesconectado,
    ErrorExclusividadNoDisponible,
)
from botonera2_device_bridge.cliente_http import ClienteHttpBackend
from botonera2_device_bridge.configuracion import ConfiguracionBridge
from botonera2_device_bridge.modelos import (
    EventoTeclaFisica,
    RespuestaEnvioBackend,
    SolicitudEntradaLogica,
)
from botonera2_device_bridge.normalizador import normalizar_tecla
from botonera2_device_bridge.remapeo import CoordinadorRemapeoBridge

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class ServicioDeviceBridge:
    """Orquestador del ciclo de vida y despacho de eventos del bridge físico."""

    def __init__(
        self,
        configuracion: ConfiguracionBridge,
        adaptador: AdaptadorEntradaFisica,
        cliente_http: ClienteHttpBackend,
        mapeo_dispositivos: dict[str, str],
    ) -> None:
        """Inicializa el servicio con sus dependencias inyectables.

        Args:
            configuracion: Parámetros operacionales del bridge.
            adaptador: Adaptador de hardware (evdev real o fake para pruebas).
            cliente_http: Cliente HTTP síncrono para comunicarse con FastAPI.
            mapeo_dispositivos: Diccionario de correspondencia fingerprint -> devXX.
        """
        self.configuracion = configuracion
        self.adaptador = adaptador
        self.cliente_http = cliente_http
        # La configuración base y la efectiva ya no comparten un diccionario
        # mutable: el coordinador conserva copias y protege ambas con un RLock.
        self.coordinador_remapeo = CoordinadorRemapeoBridge(
            configuracion.ruta_devices_json,
            mapeo_dispositivos,
        )

        # Registro de dispositivos abiertos actualmente (indexados por su ruta de sistema)
        self.dispositivos_activos: dict[str, DispositivoFisico] = {}
        # Fingerprints que actualmente están tomados en exclusiva por este proceso. Es la
        # proyección que decide el despacho funcional: si un fingerprint mapeado no figura
        # acá, sus pulsaciones no salen hacia FastAPI.
        self.fingerprints_exclusivos: set[str] = set()
        # Rutas cuyo fallo de exclusividad ya fue reportado, para no inundar el log en cada
        # iteración mientras la condición degradada persiste.
        self._fallos_exclusividad_reportados: set[str] = set()
        self._evento_detencion = threading.Event()
        self._ultimo_escaneo: float = 0.0

    def procesar_evento_tecla(self, evento: EventoTeclaFisica) -> RespuestaEnvioBackend | None:
        """Procesa un único evento físico y, si corresponde, lo despacha al backend.

        Flujo paso a paso:
        1. Ignorar si no es una pulsación (es_bajada == False).
        2. Resolver el fingerprint en el mapping efectivo vigente:
           - Si está mapeado: continuar siempre por el flujo funcional normal.
           - Si no está mapeado: ofrecerlo al coordinador de captura y NO enviar
             esa pulsación como entrada funcional.
        3. Exigir captura exclusiva vigente del fingerprint mapeado:
           - Si el bridge no la tiene: Registrar diagnóstico y NO enviar POST.
        4. Normalizar el nombre o código de la tecla física:
           - Si la tecla no es reconocida: Registrar diagnóstico y NO enviar POST.
        5. Transmitir {dispositivo, tecla} al backend mediante un único intento HTTP.
        6. Registrar el resultado funcional o error de red.

        Args:
            evento: Evento de tecla física capturado.

        Returns:
            RespuestaEnvioBackend si se emitió una solicitud HTTP, o None si el evento fue ignorado.
        """
        if not evento.es_bajada:
            logger.debug(
                "Evento ignorado (no es keydown): fp=%s, tecla=%s",
                evento.fingerprint,
                evento.nombre_tecla,
            )
            return None

        # Resolver primero el mapping efectivo es crítico: un teclado ya
        # mapeado jamás queda absorbido por la captura concurrente.
        dispositivo_logico = self.coordinador_remapeo.resolver_dispositivo(evento.fingerprint)
        if not dispositivo_logico:
            candidato = self.coordinador_remapeo.considerar_candidato(evento)
            if candidato is not None:
                # La red queda deliberadamente fuera del RLock del coordinador.
                self.cliente_http.informar_candidato(
                    candidato["remapeo_id"],
                    candidato["fingerprint"],
                    candidato["diagnostico"],
                )
            else:
                logger.info(
                    "Pulsación de dispositivo no mapeado/no elegible: fp='%s', tecla='%s'",
                    evento.fingerprint,
                    evento.nombre_tecla,
                )
            return None

        # 3. Exclusividad obligatoria antes de despachar (política fail-safe de WP-075).
        # Si el dispositivo está mapeado pero el bridge no consiguió tomarlo en exclusiva,
        # sus pulsaciones también las está recibiendo el escritorio. Aceptarlas sería
        # degradar silenciosamente a captura compartida, así que se descartan.
        if evento.fingerprint not in self.fingerprints_exclusivos:
            logger.warning(
                "Pulsación descartada de %s: el dispositivo mapeado (fp=%s) todavía no "
                "tiene captura exclusiva. Revise el diagnóstico de exclusividad del bridge.",
                dispositivo_logico,
                evento.fingerprint,
            )
            return None

        # 4. Normalización de tecla
        tecla_normalizada = normalizar_tecla(evento.nombre_tecla)
        if tecla_normalizada is None:
            logger.info(
                "Tecla física desconocida ignorada para %s: '%s'",
                dispositivo_logico,
                evento.nombre_tecla,
            )
            return None

        # 5. Transmisión HTTP al backend
        solicitud = SolicitudEntradaLogica(
            dispositivo=dispositivo_logico,
            tecla=tecla_normalizada,
        )

        logger.debug(
            "Despachando pulsación a FastAPI: %s -> %s (fp=%s)",
            dispositivo_logico,
            tecla_normalizada,
            evento.fingerprint,
        )

        respuesta = self.cliente_http.enviar_pulsacion(solicitud)
        return respuesta

    def ejecutar_ciclo_descubrimiento(self) -> list[DispositivoFisico]:
        """Descubre nuevos dispositivos de entrada y actualiza el registro activo.

        Returns:
            Lista de nuevos dispositivos descubiertos e incorporados en esta iteración.
        """
        nuevos_dispositivos: list[DispositivoFisico] = []
        candidatos = self.adaptador.descubrir_dispositivos()

        for disp in candidatos:
            if disp.ruta not in self.dispositivos_activos:
                self.dispositivos_activos[disp.ruta] = disp
                nuevos_dispositivos.append(disp)

                dev_id = self.coordinador_remapeo.resolver_dispositivo(disp.fingerprint)
                if dev_id:
                    logger.info(
                        "Hardware reconocido y MAPEADO: %s -> %s ('%s' en %s)",
                        disp.fingerprint,
                        dev_id,
                        disp.nombre,
                        disp.ruta,
                    )
                else:
                    logger.info(
                        "Hardware reconocido NO MAPEADO: %s ('%s' en %s)",
                        disp.fingerprint,
                        disp.nombre,
                        disp.ruta,
                    )

        # Un dispositivo recién descubierto (o reconectado) todavía no está tomado en
        # exclusiva: la reconciliación lo resuelve antes de que pueda despachar nada.
        self.reconciliar_exclusividad()

        return nuevos_dispositivos

    def reconciliar_exclusividad(self) -> None:
        """Alinea la captura exclusiva con el mapping efectivo vigente.

        Se ejecuta en cada descubrimiento y en cada iteración de lectura, porque el mapping
        efectivo puede cambiar en cualquier momento desde el hilo de la API local de control
        (remapeo TEMPORAL o PERSISTENTE).

        Reglas aplicadas, en este orden, para cada dispositivo activo:

        1. si su fingerprint pertenece al mapping efectivo y todavía no está tomado, se pide
           la exclusividad; un fallo se registra y deja al dispositivo sin despacho funcional;
        2. si su fingerprint dejó de pertenecer al mapping efectivo y estaba tomado, se
           libera, de modo que un teclado desplazado por un remapeo vuelve al sistema.

        Nunca toca dispositivos ajenos al mapping efectivo: el teclado del moderador jamás
        recibe `grab()` por el simple hecho de ser un teclado.
        """
        for disp in list(self.dispositivos_activos.values()):
            dispositivo_logico = self.coordinador_remapeo.resolver_dispositivo(disp.fingerprint)
            esta_mapeado = dispositivo_logico is not None

            if not esta_mapeado:
                if disp.fingerprint in self.fingerprints_exclusivos:
                    self.adaptador.liberar_exclusividad(disp)
                    self.fingerprints_exclusivos.discard(disp.fingerprint)
                    logger.info(
                        "Exclusividad liberada: %s ('%s') ya no pertenece al mapping efectivo.",
                        disp.fingerprint,
                        disp.nombre,
                    )
                self._fallos_exclusividad_reportados.discard(disp.ruta)
                continue

            if disp.fingerprint in self.fingerprints_exclusivos:
                continue

            try:
                self.adaptador.adquirir_exclusividad(disp)
            except ErrorExclusividadNoDisponible as exc:
                if disp.ruta not in self._fallos_exclusividad_reportados:
                    self._fallos_exclusividad_reportados.add(disp.ruta)
                    logger.error(
                        "No se pudo tomar en exclusiva el dispositivo mapeado %s ('%s'): %s. "
                        "Sus pulsaciones NO se despacharán al backend hasta conseguirlo. "
                        "Verifique que ningún otro proceso lo esté capturando y que el "
                        "usuario del bridge tenga permisos sobre /dev/input.",
                        disp.ruta,
                        disp.nombre,
                        exc,
                    )
                continue

            self.fingerprints_exclusivos.add(disp.fingerprint)
            self._fallos_exclusividad_reportados.discard(disp.ruta)

    def ejecutar_paso(self) -> list[RespuestaEnvioBackend]:
        """Ejecuta una iteración de lectura y procesamiento de eventos pendientes.

        Returns:
            Lista de respuestas HTTP obtenidas de los eventos procesados en esta iteración.
        """
        respuestas: list[RespuestaEnvioBackend] = []
        rutas_a_remover: list[str] = []

        # Antes de leer nada reconciliamos la exclusividad: un remapeo confirmado desde la
        # API local pudo cambiar el mapping efectivo desde la iteración anterior.
        self.reconciliar_exclusividad()

        # Leemos eventos de cada dispositivo activo
        for ruta, disp in list(self.dispositivos_activos.items()):
            try:
                eventos = self.adaptador.leer_eventos(disp)
                for ev in eventos:
                    resp = self.procesar_evento_tecla(ev)
                    if resp is not None:
                        respuestas.append(resp)
                        # Si ocurrió un fallo de transporte, timeout o error de servidor (5xx),
                        # interrumpimos el procesamiento del lote actual y purgamos los búferes
                        # para garantizar cero replay tardío conforme a WP-019 §11.
                        if (
                            resp.error_transporte is not None
                            or resp.codigo_http is None
                            or resp.codigo_http >= 500
                        ):
                            descartados = self.adaptador.descartar_eventos_pendientes()
                            logger.warning(
                                "Fallo de comunicación con el backend (motivo=%s). "
                                "Se interrumpe el lote y se descartan %d eventos acumulados "
                                "para evitar ráfaga tardía.",
                                resp.motivo,
                                descartados,
                            )
                            return respuestas
            except ErrorDispositivoDesconectado as exc:
                logger.warning(
                    "Detectada desconexión de hardware en %s ('%s'): %s",
                    ruta,
                    disp.nombre,
                    exc,
                )
                rutas_a_remover.append(ruta)

        # Limpiamos dispositivos desconectados. El cierre libera la exclusividad en el
        # adaptador; acá además olvidamos el fingerprint para que una reconexión posterior
        # vuelva a exigir una adquisición explícita antes de despachar.
        for ruta in rutas_a_remover:
            disp_removido = self.dispositivos_activos.pop(ruta, None)
            if disp_removido is not None:
                self.adaptador.cerrar_dispositivo(disp_removido)
                self.fingerprints_exclusivos.discard(disp_removido.fingerprint)
                self._fallos_exclusividad_reportados.discard(ruta)

        return respuestas

    def ejecutar_servicio(
        self,
        evento_detencion: threading.Event | None = None,
        limite_iteraciones: int | None = None,
        pausa_paso_segundos: float = 0.01,
    ) -> None:
        """Bucle principal de ejecución del bridge.

        Tolera el inicio sin hardware conectado y realiza escaneos periódicos
        sin busy-loop agresivo.

        Args:
            evento_detencion: Señal para finalizar limpiamente la ejecución.
            limite_iteraciones: Opcional para pruebas deterministas acotadas.
            pausa_paso_segundos: Intervalo de reposo entre comprobaciones no bloqueantes.
        """
        detener = evento_detencion or self._evento_detencion
        iteracion = 0

        logger.info(
            "Iniciando servicio de bridge físico Linux (URL API: %s, Mapeos: %d)",
            self.configuracion.url_base_api,
            len(self.coordinador_remapeo.instantanea_mapeo_efectivo()),
        )

        try:
            # Escaneo inicial
            self.ejecutar_ciclo_descubrimiento()
            self._ultimo_escaneo = time.monotonic()

            while not detener.is_set():
                if limite_iteraciones is not None and iteracion >= limite_iteraciones:
                    break

                ahora = time.monotonic()
                if (ahora - self._ultimo_escaneo) >= self.configuracion.intervalo_escaneo_segundos:
                    self.ejecutar_ciclo_descubrimiento()
                    self._ultimo_escaneo = ahora

                self.ejecutar_paso()
                iteracion += 1

                # Pausa controlada para evitar consumo de CPU
                detener.wait(timeout=pausa_paso_segundos)

        finally:
            self.detener()
            logger.info("Servicio de bridge físico detenido correctamente.")

    def detener(self) -> None:
        """Detiene el servicio, libera toda exclusividad y cierra los descriptores.

        `cerrar_todo()` del adaptador ejecuta el `ungrab()` de cada dispositivo tomado antes
        de cerrar su descriptor, así que al terminar el proceso los numpads vuelven a estar
        disponibles para el resto del sistema.
        """
        self._evento_detencion.set()
        self.adaptador.cerrar_todo()
        self.dispositivos_activos.clear()
        self.fingerprints_exclusivos.clear()
        self._fallos_exclusividad_reportados.clear()
