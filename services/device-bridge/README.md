# SIS-Leg — Device Bridge (Bridge Físico Linux)

## Propósito y Función

El **Device Bridge** (`services/device-bridge`) es el servicio encargado de interactuar con el hardware físico en el recinto legislativo (teclados numéricos USB asociados a cada banca) en sistemas operativos Linux.

Su única función es:
1. Detectar teclados físicos mediante `evdev`.
2. Extraer sus metadatos de hardware para derivar un identificador persistente (**fingerprint canónico**).
3. Resolver el identificador físico hacia un identificador lógico (`dev01`, `dev02`, etc.) a través del archivo de mapeo `config/devices.json`.
4. Normalizar la tecla presionada al catálogo de la API.
5. Transmitir el evento como una pulsación lógica a FastAPI (`POST /api/v1/entradas/tecla`).
6. Coordinar remapeos confirmados conservando estable el mismo `devXX`.

```text
Teclado Físico (USB)
       ↓
     evdev (/dev/input/event*)
       ↓
Fingerprint Físico (lin|vendor=...|product=...)
       ↓
  devices.json (Mapeo estricto)
       ↓
Dispositivo Lógico (dev01 .. devXX)
       ↓
Normalización de Tecla (0..9, +, -, ENTER, etc.)
       ↓
POST /api/v1/entradas/tecla (FastAPI)
```

## Frontera de Responsabilidades

### Lo que SÍ hace el Bridge:
- Descubre y abre dispositivos Linux con capacidad `EV_KEY`.
- Genera el fingerprint persistente e independiente de la ruta efímera `/dev/input/eventN`.
- Filtra estrictamente eventos de pulsación (`keydown`), descartando `keyup` y `repeat/hold`.
- Valida la integridad de `devices.json` (incluyendo detección de claves JSON duplicadas y unicidad inversa).
- Despacha a lo sumo **un intento HTTP** por pulsación.
- Loguea diagnósticos locales (stdout/stderr y journald).
- Se recupera automáticamente de desconexiones y reconexiones de hardware en caliente.
- **Toma en exclusiva los numpads mapeados** (`EVIOCGRAB`) para que sus pulsaciones no
  lleguen al escritorio ni al navegador de Moderación.

### Lo que NO hace el Bridge:
- **No evalúa reglas de negocio**: No decide presencia, quórum, validez de votos, irreversibilidad, pedidos de palabra ni resultados. Toda la semántica institucional reside en FastAPI.
- **No interpreta el padrón**: No lee `config/concejales.csv`.
- **No reintenta peticiones**: No realiza retries automáticos ante timeouts o errores de red.
- **No acumula eventos (cero replay)**: No utiliza colas durables ni reintentos automáticos. Ante caídas de red, timeouts o fallos de transporte, interrumpe el procesamiento del lote y purga activamente los búferes de hardware para evitar ráfagas tardías de eventos antiguos cuando se restablece la conexión.
- **No asigna dispositivos no mapeados**: Un fingerprint desconocido nunca se asigna automáticamente a un `devXX` libre.
- **No captura teclados ajenos**: Nunca toma en exclusiva un dispositivo que no pertenezca al mapping efectivo. El teclado y el mouse del moderador siguen funcionando con normalidad aunque el bridge esté activo.

---

## Arquitectura y Componentes

El paquete `sis_leg_device_bridge` está estructurado en módulos enfocados y testeables:

- `fingerprint.py`: construcción y validación del formato canónico Linux.
- `configuracion.py`: parámetros operacionales y lector estricto de `devices.json`.
- `normalizador.py`: normalización amplia de teclas físicas.
- `cliente_http.py`: pulsaciones y callback de candidato mediante `urllib.request`.
- `adaptador_linux.py`: hardware `evdev` real y adaptador falso para CI.
- `servicio.py`: descubrimiento y flujo no bloqueante de eventos.
- `remapeo.py`: mapping base/efectivo, elegibilidad, idempotencia y persistencia.
- `servidor_control.py`: API HTTP local stdlib para la coordinación backend↔bridge.
- `cli.py`: ciclo de vida conjunto del loop físico y el servidor de control.

---

## Formato del Fingerprint Canónico

El fingerprint identifica de forma determinista y estable a cada teclado físico en Linux:

```text
lin|vendor=<hex4>|product=<hex4>|version=<hex4>|phys=<texto>|uniq=<texto>|name=<texto>
```

Ejemplo:
```text
lin|vendor=1a2c|product=2d43|version=0110|phys=usb-0000:00:14.0-1/input0|uniq=|name=USB Keyboard
```

- `vendor`, `product`, `version`: Cuatro caracteres hexadecimales en minúsculas.
- `phys`, `uniq`, `name`: Información reportada por el kernel. Si no están presentes se representan como texto vacío (ej: `uniq=`).
- No contiene `/dev/input/eventN` para evitar variaciones si los dispositivos cambian de nodo tras reconectar.

---

## Configuración y `devices.json`

Ruta por defecto:
`services/device-bridge/config/devices.json`

Esa ruta runtime no cambió, pero desde WP-073 **el archivo no se versiona**: los
fingerprints físicos son estado real de cada instalación y el propio bridge los
reescribe al remapear. El repositorio versiona la plantilla
`services/device-bridge/config/devices.example.json`, y el archivo runtime se
materializa desde ella con:

```bash
uv run python scripts/preparar_config_local.py   # o: pnpm preparar:config
```

El comando nunca sobrescribe un `devices.json` existente, así que puede
ejecutarse cuantas veces haga falta sin perder un remapeo.

Formato:
```json
{
  "lin|vendor=1a2c|product=2d43|version=0110|phys=usb-0000:00:14.0-1/input0|uniq=|name=USB Keyboard": "dev01",
  "lin|vendor=1a2c|product=2d43|version=0110|phys=usb-0000:00:14.0-2/input0|uniq=|name=USB Keyboard": "dev02"
}
```

Reglas del validador:
- Objeto JSON plano.
- Claves no vacías y con formato `lin|...`.
- Valores estrictamente string con formato `devXX` (dos dígitos).
- Sin claves duplicadas.
- Sin identificadores lógicos duplicados.

---

## Normalización de Teclas

El bridge traduce teclas físicas de teclado estándar y teclado numérico (numpad) hacia los valores reconocidos:

| Teclas Físicas / evdev | Valor API |
| :--- | :--- |
| `0`..`9`, `KEY_0`..`KEY_9`, `KP0`..`KP9`, `KEY_KP0`..`KEY_KP9` | `'0'`..`'9'` |
| `.`, `DOT`, `KEY_DOT`, `KPDOT`, `KEY_KPDOT` | `'.'` |
| `+`, `PLUS`, `KEY_KPPLUS`, `KPPLUS` | `'+'` |
| `-`, `MINUS`, `KEY_MINUS`, `KPMINUS`, `KEY_KPMINUS` | `'-'` |
| `*`, `ASTERISK`, `KEY_KPASTERISK`, `KPASTERISK` | `'*'` |
| `/`, `SLASH`, `KEY_SLASH`, `KEY_KPSLASH`, `KPSLASH` | `'/'` |
| `ENTER`, `KEY_ENTER`, `KPENTER`, `KEY_KPENTER` | `'ENTER'` |
| `ESC`, `KEY_ESC` | `'ESC'` |
| `TAB`, `KEY_TAB` | `'TAB'` |
| `SPACE`, `KEY_SPACE` | `'SPACE'` |
| `BACKSPACE`, `KEY_BACKSPACE` | `'BACKSPACE'` |

> **Nota (Decisión Humana 4.B)**: Las teclas reconocidas sin función activa actual (como `4`, `5`, `6`, `0`, `ENTER`, etc.) también se envían al backend. El bridge no las descarta; la decisión de aceptar o rechazar pertenece a FastAPI. Teclas físicas no catalogadas se ignoran con log diagnóstico.

---

## Requisitos y Permisos en Linux

### Requisitos:
- Python 3.14
- Linux con soporte `evdev` y nodos `/dev/input/event*` (Plataforma de referencia: Linux Mint 22.3).
- Dependencia directa: `evdev>=1.9.3,<2` (gestionada mediante `uv`).

### Permisos de Acceso a `/dev/input`:
Para que un proceso no root pueda leer `/dev/input/event*`, el usuario debe tener permisos de lectura sobre esos nodos.

En Linux Mint / Debian / Ubuntu, esto se logra habitualmente agregando al usuario al grupo `input`:
```bash
sudo usermod -a -G input $USER
```
*(Requiere cerrar e iniciar sesión para que el grupo tome efecto)*.

---

## Ejecución y Parámetros CLI

El paquete registra el comando de consola `sis-leg-device-bridge`.

### Ejecutar con uv:
```bash
# Ejecución estándar con defaults
uv run sis-leg-device-bridge

# Especificando parámetros
uv run sis-leg-device-bridge \
  --config services/device-bridge/config/devices.json \
  --url http://127.0.0.1:8000 \
  --timeout 3.0 \
  --intervalo-escaneo 2.0 \
  --control-host 127.0.0.1 \
  --control-port 8765 \
  --log-level INFO
```

### Variables de Entorno Soportadas:
- `SIS_LEG_DEVICES_CONFIG`: Ruta al archivo `devices.json`.
- `SIS_LEG_BACKEND_URL`: URL base de FastAPI (ej: `http://127.0.0.1:8000`).
- `SIS_LEG_HTTP_TIMEOUT`: Timeout HTTP en segundos (ej: `3.0`).
- `SIS_LEG_SCAN_INTERVAL`: Intervalo de re-escaneo de dispositivos en segundos (ej: `2.0`).
- `SIS_LEG_LOG_LEVEL`: Nivel de log (`DEBUG`, `INFO`, `WARNING`, `ERROR`).
- `SIS_LEG_CONTROL_HOST`: bind de la API de control; default seguro `127.0.0.1`.
- `SIS_LEG_CONTROL_PORT`: puerto de control; default `8765`.

---

## Captura exclusiva de los numpads de banca

La instalación real usa una sola PC para Moderación, el bridge y los hubs USB de las
botoneras. Sin captura exclusiva, una pulsación de banca llega a la vez al bridge y al
escritorio, de modo que un `3` de voto también se escribiría en el campo de texto que
tenga el foco en el navegador.

Para evitarlo, el bridge toma cada dispositivo del **mapping efectivo** con
`InputDevice.grab()` de `python-evdev`, que usa la capacidad `EVIOCGRAB` del kernel. Solo
un proceso puede sostener ese grab: mientras el bridge lo conserva, ninguna otra aplicación
recibe eventos de ese teclado. La liberación se hace con `InputDevice.ungrab()`.

### Qué se captura y qué no

| Dispositivo | Captura exclusiva |
| :--- | :--- |
| Fingerprint presente en el mapping efectivo (`devXX`) | Sí, mientras el bridge esté activo |
| Teclado y mouse del moderador | No |
| Teclado descubierto pero no mapeado | No |
| Candidato de un reemplazo todavía no confirmado | No, hasta que el remapeo se aplique |

La decisión se toma exclusivamente por pertenencia al mapping efectivo. No se usa el
nombre, el vendor/product ni la mera capacidad `EV_KEY` como heurística, para que ningún
teclado del operador quede secuestrado por parecerse a una botonera.

### Política fail-safe

La exclusividad es **requisito previo** al despacho funcional. Si `grab()` falla sobre un
dispositivo mapeado —por ejemplo porque otro proceso ya lo tomó o porque faltan permisos
sobre `/dev/input`—, el bridge:

- registra un diagnóstico de nivel `ERROR` con la ruta, el nombre del dispositivo y la
  causa devuelta por el sistema operativo;
- **no** despacha ninguna pulsación de ese dispositivo al backend, para no operar en modo
  compartido de forma silenciosa;
- reintenta la adquisición en cada ciclo, de modo que el dispositivo vuelve a operar apenas
  se consigue la exclusividad, sin reiniciar el servicio.

Los demás dispositivos mapeados siguen funcionando normalmente: el fallo es por
dispositivo, no global.

### Ciclo de vida

- **Descubrimiento y reconexión**: cada dispositivo mapeado recién abierto adquiere la
  exclusividad antes de poder despachar; una reconexión física la vuelve a adquirir aunque
  el kernel le asigne otro nodo `/dev/input/eventN`.
- **Remapeo TEMPORAL o PERSISTENTE**: al cambiar el mapping efectivo, el fingerprint nuevo
  adquiere la exclusividad y el reemplazado la libera, de modo que nunca quedan dos
  dispositivos apropiándose del mismo `devXX`.
- **Cierre normal**: la parada del servicio libera la exclusividad de cada dispositivo antes
  de cerrar su descriptor. Cerrar el descriptor sigue siendo la última garantía de
  liberación, así que una caída abrupta también devuelve los teclados al sistema.

Adquirir y liberar son idempotentes desde la perspectiva del bridge: el adaptador lleva un
registro local de qué rutas están tomadas, porque el contrato oficial de `python-evdev`
indica que liberar un dispositivo que no fue tomado provoca un `OSError`.

### Verificación humana sobre Linux real

Con el bridge en ejecución y Moderación abierta con el foco en un campo editable:

- pulsar teclas funcionales en un numpad mapeado **no** debe escribir ningún carácter en la
  pantalla, y sí debe producir el efecto funcional correspondiente;
- el teclado del moderador debe escribir con normalidad.

Si el numpad escribe en el campo, la exclusividad no se adquirió: revisar el diagnóstico
del servicio (`journalctl -u sis-leg-device-bridge.service`) buscando el error de captura
exclusiva.

---

## Remapeo coordinado y API local de control

La separación permanece siempre:

```text
fingerprint físico -> device-bridge -> devXX -> FastAPI -> concejal
```

El remapeo cambia únicamente el primer tramo. El navegador habla con FastAPI;
nunca conoce ni consume la API local del bridge.

La API usa solo biblioteca estándar, escucha en loopback por defecto y expone:

| Operación | Método y path | Body |
| :--- | :--- | :--- |
| Iniciar captura | `POST /control/v1/remapeos` | `{"remapeo_id":"UUID","dispositivo":"dev05"}` |
| Consultar/reconciliar | `GET /control/v1/remapeos/{remapeo_id}` | sin body |
| Confirmar/aplicar | `POST /control/v1/remapeos/{remapeo_id}/confirmacion` | `{"fingerprint":"lin|...","persistencia":"TEMPORAL"}` |
| Cancelar | `DELETE /control/v1/remapeos/{remapeo_id}` | sin body |

Los bodies son cerrados y los comandos son idempotentes por `remapeo_id`:
repetir el mismo comando con los mismos parámetros no duplica aplicación ni
escritura; reutilizar el ID con parámetros distintos se rechaza. `GET` permite
resolver si una respuesta de confirmación se perdió después de que el cambio ya
había sido aplicado.

### Captura sin bloquear otros teclados

El teclado candidato de un reemplazo todavía no pertenece al mapping efectivo, así que no
se toma en exclusiva mientras dura la captura. Recién al confirmar el remapeo el nuevo
fingerprint queda dedicado a SIS-Leg y el reemplazado vuelve al sistema.

El loop físico resuelve primero el mapping efectivo bajo un `RLock`. Si el
fingerprint está mapeado, su keydown sigue inmediatamente por el flujo normal
hacia `POST /api/v1/entradas/tecla`, incluso durante una votación. Solamente un
fingerprint no mapeado puede evaluarse como candidato. El primer elegible queda
congelado, no se envía como pulsación funcional y los posteriores no lo reemplazan.

Además de no pertenecer al mapping efectivo, un fingerprint que todavía figure
en `devices.json` solo es elegible para su mismo `devXX` base. Esto permite
volver al teclado original después de un override temporal, pero impide “robar”
el teclado base de otra banca.

### TEMPORAL

- reemplaza solo el fingerprint efectivo del `devXX` en memoria;
- no modifica `devices.json`;
- no se revierte al cerrar sesión o cancelar preparación en FastAPI;
- desaparece al reiniciar el proceso del bridge, que vuelve a cargar el archivo base.

### PERSISTENTE

Después de la confirmación humana, el bridge construye y valida el mapping base
completo, reemplazando solo el fingerprint del objetivo. Crea un temporal en el
mismo directorio que `devices.json`, escribe el JSON completo, ejecuta
`flush()`, `os.fsync()` y finalmente `os.replace()` atómico. Recién después de
un reemplazo exitoso instala el mapping efectivo nuevo. Un fallo de escritura,
`fsync` o `replace` conserva el mapping efectivo anterior y no degrada a TEMPORAL.

El servidor HTTP y el loop físico comparten un único coordinador protegido por
`threading.RLock`; por eso no existe doble candidato, mapping parcialmente
visible ni doble persistencia concurrente.

### Contrato público de FastAPI y errores estables

La futura UI usa exclusivamente `POST /api/v1/remapeos`,
`POST /api/v1/remapeos/{remapeo_id}/confirmacion` y
`DELETE /api/v1/remapeos/{remapeo_id}`. El callback
`POST /api/v1/interno/remapeos/{remapeo_id}/candidato` pertenece al bridge.

Los conflictos funcionales se distinguen con `ESTADO_INCOMPATIBLE`,
`DISPOSITIVO_REMAPEO_NO_EXISTENTE`, `REMAPEO_YA_ACTIVO`,
`REMAPEO_NO_COINCIDE`, `REMAPEO_SIN_CANDIDATO`,
`CANDIDATO_YA_REGISTRADO` y `PARAMETROS_REMAPEO_INCOMPATIBLES`. Los fallos
técnicos usan `BRIDGE_NO_DISPONIBLE`, `APLICACION_BRIDGE_RECHAZADA` o
`AUDITORIA_NO_DISPONIBLE`. Los bodies inválidos/campos extra responden `422`.

---

## Pruebas Automatizadas

Las pruebas del bridge se ejecutan mediante `pytest` y no requieren hardware real ni privilegios especiales gracias al `AdaptadorFalso`:

```bash
uv run pytest tests/device_bridge/
```

Para ejecutar la suite completa de calidad y tests:
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
```

---

## Alcance Futuro y Pendientes

- **UI de Moderación**: los contratos de WP-020 quedan listos; la pantalla visual corresponde a un WP posterior.
- **Unidad systemd e instalación (Fase de Despliegue)**: El empaquetado del servicio `sis-leg-device-bridge.service` y reglas udev se implementará en la etapa de despliegue productivo (DT-028).
