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
7. La política de privacidad del registro (WP-082): las pulsaciones de un dispositivo que
   no está mapeado y autorizado jamás se escriben en el log, ni siquiera a DEBUG.

Invariantes críticas:
- Cero asignación automática: Un fingerprint no presente en `devices.json` NUNCA
  recibe un `devXX` ni emite POST al backend.
- Cero reintentos: Cada evento físico `keydown` emite a lo sumo un POST.
- No decide reglas de negocio: El bridge no evalúa presencia, quórum, voto ni palabra.
- Exclusividad fail-safe: un descriptor mapeado sin exclusividad no despacha pulsaciones
  funcionales; nunca se degrada silenciosamente a captura compartida.
- Ningún dispositivo fuera del mapping efectivo se toma en exclusiva, de modo que el
  teclado y el mouse del moderador siguen funcionando con normalidad.
- Minimización de datos: el bridge corre en el mismo equipo que el teclado del operador y
  con permisos sobre `/dev/input`, así que *puede* leer lo que esa persona escribe. Por eso
  no registra el contenido de ninguna tecla que no provenga de un descriptor mapeado y
  capturado en exclusiva, y en ese caso registra una sola vez por dispositivo que lo está
  ignorando, sin dejar en el journal ni el texto ni la cadencia de lo tecleado.

Por qué la autorización se representa por descriptor y no por fingerprint (WP-082)
----------------------------------------------------------------------------------

`EVIOCGRAB` es una capacidad que el kernel concede a un **descriptor abierto** concreto,
identificado por su ruta `/dev/input/eventN`. El fingerprint, en cambio, es una identidad
lógica derivada de metadatos (vendor, product, version, phys, uniq, name) que el kernel no
garantiza única entre nodos distintos.

Si la autorización se guardara por fingerprint, dos descriptores que produjeran el mismo
fingerprint compartirían la autorización aunque sólo uno estuviese capturado: el segundo
seguiría entregando sus pulsaciones al escritorio *y* al bridge, y el bridge las aceptaría
como si vinieran de la botonera capturada. Por eso el servicio guarda las **rutas** que
sostienen la exclusividad y cada evento demuestra su origen con `ruta_dispositivo`.

El fingerprint conserva intacto su papel de identidad para el mapping y el remapeo; lo que
deja de hacer es representar una autorización que el kernel nunca le otorgó.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

from sis_leg_device_bridge.adaptador_linux import (
    AdaptadorEntradaFisica,
    DispositivoFisico,
    ErrorDispositivoDesconectado,
    ErrorExclusividadNoDisponible,
)
from sis_leg_device_bridge.cliente_http import ClienteHttpBackend
from sis_leg_device_bridge.configuracion import ConfiguracionBridge
from sis_leg_device_bridge.modelos import (
    EventoTeclaFisica,
    RespuestaEnvioBackend,
    SolicitudEntradaLogica,
)
from sis_leg_device_bridge.normalizador import normalizar_tecla
from sis_leg_device_bridge.remapeo import CoordinadorRemapeoBridge

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
        # Rutas/descriptores que actualmente están tomados en exclusiva por este proceso.
        # Es la proyección que decide el despacho funcional: si el descriptor por el que
        # entró una pulsación no figura acá, esa pulsación no sale hacia FastAPI. Se indexa
        # por ruta y no por fingerprint porque el kernel concede `EVIOCGRAB` al descriptor
        # (WP-082 / ASTRA-004).
        self.rutas_exclusivas: set[str] = set()
        # Rutas cuyo fallo de exclusividad ya fue reportado, para no inundar el log en cada
        # iteración mientras la condición degradada persiste.
        self._fallos_exclusividad_reportados: set[str] = set()
        # Rutas descartadas por identidad física ambigua (otro descriptor activo ya sostiene
        # la exclusividad de ese mismo fingerprint mapeado). Se reportan una sola vez.
        self._identidades_ambiguas_reportadas: set[str] = set()
        # Fingerprints no mapeados cuya pulsación ya fue reportada como ignorada. Evita
        # escribir una línea por tecla: además de ruido, la cadencia de un teclado ajeno es
        # información que el bridge no tiene por qué conservar.
        self._no_mapeados_reportados: set[str] = set()
        # Descriptores mapeados cuyo descarte por falta de exclusividad ya fue reportado.
        self._descartes_sin_exclusividad_reportados: set[str] = set()
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
        3. Exigir que el **descriptor de origen** del evento sostenga la captura exclusiva:
           - Si el bridge no la tiene sobre esa ruta: Registrar diagnóstico y NO enviar POST.
        4. Normalizar el nombre o código de la tecla física:
           - Si la tecla no es reconocida: Registrar diagnóstico y NO enviar POST.
        5. Transmitir {dispositivo, tecla} al backend mediante un único intento HTTP.
        6. Registrar el resultado funcional o error de red.

        Dos reglas de este método existen por el endurecimiento de WP-082 y conviene no
        deshacerlas por comodidad de diagnóstico:

        - hasta el paso 3 inclusive **no se registra el contenido de la tecla**, porque
          hasta ahí el evento puede venir del teclado normal del operador;
        - el paso 3 compara `evento.ruta_dispositivo` contra las rutas capturadas, no el
          fingerprint: un segundo descriptor con el mismo fingerprint no hereda la
          autorización del primero.

        Args:
            evento: Evento de tecla física capturado, con su descriptor de origen sellado
                por el adaptador.

        Returns:
            RespuestaEnvioBackend si se emitió una solicitud HTTP, o None si el evento fue ignorado.
        """
        if not evento.es_bajada:
            # No se registra qué tecla era: en este punto todavía no sabemos si el evento
            # viene de una botonera de banca o del teclado con el que el operador acaba de
            # escribir una contraseña.
            logger.debug(
                "Evento ignorado (no es keydown): fp=%s",
                evento.fingerprint,
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
            elif evento.fingerprint not in self._no_mapeados_reportados:
                # ASTRA-003: acá llegaban antes el nombre de cada tecla y una línea por
                # pulsación. En la topología de una sola PC eso deja en el journal el texto
                # que el operador escribe en cualquier ventana. Se conserva un aviso único
                # por dispositivo, con la identidad del hardware y sin nada de lo tecleado:
                # alcanza para diagnosticar «este teclado no está en devices.json» y no
                # revela ni el contenido ni el ritmo de la escritura.
                self._no_mapeados_reportados.add(evento.fingerprint)
                logger.info(
                    "Pulsaciones ignoradas de un dispositivo no mapeado/no elegible "
                    "(fp=%s). El contenido de sus teclas no se registra por política de "
                    "privacidad; para incorporarlo use el remapeo o devices.json.",
                    evento.fingerprint,
                )
            return None

        # 3. Exclusividad obligatoria antes de despachar (política fail-safe de WP-075,
        # endurecida por WP-082). La comparación es contra la ruta de origen del evento:
        # si ese descriptor no sostiene el `EVIOCGRAB`, sus pulsaciones también las está
        # recibiendo el escritorio. Aceptarlas sería degradar silenciosamente a captura
        # compartida, así que se descartan aunque otro descriptor con el mismo fingerprint
        # sí esté capturado.
        ruta_origen = evento.ruta_dispositivo
        if not ruta_origen or ruta_origen not in self.rutas_exclusivas:
            if ruta_origen not in self._descartes_sin_exclusividad_reportados:
                # Se reporta una sola vez mientras dure la condición: el aviso se repone
                # cuando el descriptor recupera la exclusividad, en `reconciliar_exclusividad`.
                self._descartes_sin_exclusividad_reportados.add(ruta_origen)
                logger.warning(
                    "Pulsaciones descartadas de %s: el descriptor de origen (%s) no "
                    "sostiene la captura exclusiva del dispositivo mapeado (fp=%s). "
                    "Revise el diagnóstico de exclusividad del bridge.",
                    dispositivo_logico,
                    ruta_origen or "desconocido",
                    evento.fingerprint,
                )
            return None

        # 4. Normalización de tecla.
        # Recién en este punto se puede nombrar la tecla en el log: el evento proviene de un
        # descriptor mapeado y capturado en exclusiva, es decir de una botonera dedicada a
        # SIS-Leg y no del teclado de trabajo de una persona. Saber qué tecla no se reconoce
        # es justamente lo que necesita soporte para diagnosticar una botonera distinta.
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

        Reglas aplicadas, en este orden, para cada **descriptor** activo:

        1. si su fingerprint no pertenece al mapping efectivo y ese descriptor estaba tomado,
           se libera, de modo que un teclado desplazado por un remapeo vuelve al sistema;
        2. si ya sostiene la exclusividad, no se vuelve a pedir nada;
        3. si otro descriptor activo ya sostiene la exclusividad del mismo fingerprint
           mapeado, este descriptor queda **sin autorizar** y se reporta la ambigüedad;
        4. en cualquier otro caso se pide la exclusividad de ese descriptor; un fallo se
           registra y lo deja sin despacho funcional.

        La regla 3 es el otro lado de ASTRA-004. Un `devXX` designa una sola banca, así que
        no puede haber dos fuentes simultáneas autorizadas para él. Antes ese segundo
        descriptor ni siquiera intentaba el `grab()` y aun así despachaba; ahora ni despacha
        ni se apropia del teclado, que es la salida conservadora: el bridge informa que
        encontró dos descriptores con la misma identidad y deja que un humano revise el
        inventario. Esto **no afirma** que exista una colisión real de hardware; describe
        exactamente lo observado.

        Nunca toca dispositivos ajenos al mapping efectivo: el teclado del moderador jamás
        recibe `grab()` por el simple hecho de ser un teclado.
        """
        for disp in list(self.dispositivos_activos.values()):
            dispositivo_logico = self.coordinador_remapeo.resolver_dispositivo(disp.fingerprint)
            esta_mapeado = dispositivo_logico is not None

            if not esta_mapeado:
                if disp.ruta in self.rutas_exclusivas:
                    self.adaptador.liberar_exclusividad(disp)
                    self.rutas_exclusivas.discard(disp.ruta)
                    logger.info(
                        "Exclusividad liberada en %s ('%s'): su fingerprint ya no pertenece "
                        "al mapping efectivo.",
                        disp.ruta,
                        disp.nombre,
                    )
                self._olvidar_diagnosticos_de(disp.ruta)
                continue

            # Si el fingerprint volvió al mapping efectivo (por ejemplo tras un remapeo),
            # se repone su aviso de «no mapeado» por si más adelante vuelve a salir.
            self._no_mapeados_reportados.discard(disp.fingerprint)

            if disp.ruta in self.rutas_exclusivas:
                continue

            ruta_titular = self._ruta_que_sostiene_exclusividad(disp.fingerprint)
            if ruta_titular is not None:
                if disp.ruta not in self._identidades_ambiguas_reportadas:
                    self._identidades_ambiguas_reportadas.add(disp.ruta)
                    logger.warning(
                        "Identidad física ambigua: el descriptor %s ('%s') declara el mismo "
                        "fingerprint que %s, que ya está capturado en exclusiva para %s. "
                        "El descriptor %s NO se captura ni despacha pulsaciones. Revise el "
                        "inventario de botoneras y el mapeo de %s.",
                        disp.ruta,
                        disp.nombre,
                        ruta_titular,
                        dispositivo_logico,
                        disp.ruta,
                        dispositivo_logico,
                    )
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

            self.rutas_exclusivas.add(disp.ruta)
            # Al recuperar la exclusividad se reponen los avisos: si el descriptor vuelve a
            # degradarse más adelante, soporte tiene que volver a verlo en el registro.
            self._olvidar_diagnosticos_de(disp.ruta)

    def _ruta_que_sostiene_exclusividad(self, fingerprint: str) -> str | None:
        """Devuelve el descriptor activo que ya tiene capturado ese fingerprint, si existe.

        Se recalcula en cada reconciliación en lugar de guardarse en un índice propio. Así
        una desconexión que retira una ruta de `rutas_exclusivas` habilita automáticamente
        al descriptor siguiente, sin dejar un «titular» fantasma bloqueando a la botonera
        que sí está conectada.
        """
        for otro in self.dispositivos_activos.values():
            if otro.fingerprint == fingerprint and otro.ruta in self.rutas_exclusivas:
                return otro.ruta
        return None

    def _olvidar_diagnosticos_de(self, ruta: str) -> None:
        """Repone los avisos de una ruta para que un problema nuevo vuelva a registrarse."""
        self._fallos_exclusividad_reportados.discard(ruta)
        self._identidades_ambiguas_reportadas.discard(ruta)
        self._descartes_sin_exclusividad_reportados.discard(ruta)

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
        # adaptador; acá además olvidamos el descriptor para que una reconexión posterior
        # vuelva a exigir una adquisición explícita antes de despachar. Como la autorización
        # es por ruta, la desconexión de un descriptor no le quita la autorización a otro
        # que estuviera legítimamente capturado.
        for ruta in rutas_a_remover:
            disp_removido = self.dispositivos_activos.pop(ruta, None)
            if disp_removido is not None:
                self.adaptador.cerrar_dispositivo(disp_removido)
                self.rutas_exclusivas.discard(ruta)
                self._olvidar_diagnosticos_de(ruta)

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
        self.rutas_exclusivas.clear()
        self._fallos_exclusividad_reportados.clear()
        self._identidades_ambiguas_reportadas.clear()
        self._no_mapeados_reportados.clear()
        self._descartes_sin_exclusividad_reportados.clear()
