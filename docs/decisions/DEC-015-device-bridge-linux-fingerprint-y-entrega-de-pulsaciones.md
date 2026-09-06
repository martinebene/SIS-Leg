# DEC-015 - Device bridge Linux, fingerprint físico y entrega de pulsaciones

## Estado

`APROBADA`

## Fecha

2026-08-24

## Contexto

WP-019 debe convertir el scaffold `services/device-bridge/` en el bridge físico base de SIS-Leg. Los documentos canónicos ya separan responsabilidades de esta forma:

```text
fingerprint físico -> device-bridge -> identificador lógico -> backend -> concejal
```

El backend recibe únicamente `{dispositivo, tecla}` en `POST /api/v1/entradas/tecla`; no conoce fingerprints físicos. Presencia, quórum, voto, palabra, cierre y resultado pertenecen al backend.

La instalación histórica autorizada de `martinebene/Botonera` identifica teclados Linux mediante `evdev`, construye un fingerprint persistente, resuelve un mapa `fingerprint -> devXX` y transmite la pulsación por HTTP. SIS-Leg conserva esa compatibilidad física inicial sin copiar la arquitectura monolítica histórica ni trasladar reglas de negocio al bridge.

DT-027 fija Linux Mint 22.3 como plataforma productiva de referencia. DT-014 fija que el remapeo futuro debe sustituir el fingerprint físico asociado a un identificador lógico estable sin alterar concejal, presencia ni votos.

Las decisiones de este documento fueron aprobadas explícitamente por el operador antes de redactar WP-019.

## Decisión

### 1. Plataforma inicial: Linux

WP-019 implementa captura física únicamente para Linux.

La implementación debe aislar la captura detrás de una frontera/adaptador propio para no acoplar el resto del bridge a `evdev`, pero no se implementa Raw Input/Windows en este alcance.

Linux Mint 22.3 es la plataforma productiva de referencia; el código Linux debe conservar compatibilidad razonable con otras distribuciones Linux que expongan `evdev` y `/dev/input/event*`.

### 2. Única dependencia runtime directa nueva

Se aprueba como única nueva dependencia runtime directa del bridge:

```text
evdev>=1.9.3,<2
```

Se utiliza para descubrimiento y lectura de dispositivos Linux.

La comunicación HTTP con FastAPI se implementa con biblioteca estándar de Python. No se agrega `requests`, `httpx` ni otra librería HTTP como dependencia runtime del bridge.

Cualquier otra dependencia directa nueva requiere una nueva aprobación conforme DT-038.

### 3. Fingerprint Linux compatible con producción histórica

El fingerprint canónico inicial conserva exactamente la forma histórica:

```text
lin|vendor=<hex4>|product=<hex4>|version=<hex4>|phys=<texto>|uniq=<texto>|name=<texto>
```

Los campos provienen del dispositivo `evdev`:

- `vendor`: `dev.info.vendor` en hexadecimal de cuatro dígitos;
- `product`: `dev.info.product` en hexadecimal de cuatro dígitos;
- `version`: `dev.info.version` en hexadecimal de cuatro dígitos;
- `phys`: `dev.phys` normalizado a texto vacío cuando no exista;
- `uniq`: `dev.uniq` normalizado a texto vacío cuando no exista;
- `name`: `dev.name` normalizado a texto vacío cuando no exista.

No se incorpora la ruta efímera `/dev/input/eventN` al fingerprint.

La compatibilidad deliberada permite reutilizar/migrar mapeos físicos de la instalación histórica cuando el hardware y los atributos expuestos por Linux sean los mismos.

### 4. `devices.json` plano y propietario del bridge

El archivo canónico continúa siendo:

```text
services/device-bridge/config/devices.json
```

Su forma inicial es un objeto JSON plano:

```json
{
  "lin|vendor=1a2c|product=2d43|version=0110|phys=usb-...|uniq=|name=USB Keyboard": "dev01"
}
```

Reglas:

- cada clave es un fingerprint Linux no vacío con la forma canónica anterior;
- cada valor es un identificador lógico `devXX`, donde `XX` son exactamente dos dígitos decimales;
- un fingerprint aparece una sola vez;
- un identificador lógico aparece una sola vez;
- configuración ausente, JSON ilegible, claves duplicadas, fingerprints inválidos, valores inválidos o dos fingerprints asociados al mismo lógico son errores de configuración explícitos;
- un dispositivo físico detectado pero no mapeado no se asigna automáticamente a ningún `devXX` y no envía pulsaciones funcionales al backend;
- WP-019 no reescribe automáticamente `devices.json`.

El padrón del backend sigue siendo la única fuente de relación `devXX -> concejal` durante una preparación. El bridge no carga ni interpreta `concejales.csv`.

### 5. Normalización y transmisión amplia de teclas reconocidas

El bridge conserva la normalización amplia del servicio histórico para facilitar diagnóstico y la evolución del remapeo coordinado a través del backend.

Se reconocen y transmiten, cuando el dispositivo está mapeado:

```text
0 1 2 3 4 5 6 7 8 9
. + - * /
ENTER ESC TAB SPACE BACKSPACE
```

Los equivalentes del teclado numérico (`KP0`..`KP9`, `KPDOT`, `KPPLUS`, `KPMINUS`, `KPASTERISK`, `KPSLASH`, `KPENTER`) se normalizan a esos valores.

Solo `1`, `2`, `3`, `7`, `8` y `9` poseen semántica funcional actual según el backend. El bridge no filtra las demás teclas reconocidas por significado de negocio: las transmite y deja que `POST /api/v1/entradas/tecla` acepte o rechace conforme al estado y contrato vigente.

Una tecla no reconocida por el normalizador se ignora localmente y puede registrarse a nivel diagnóstico, pero no se inventa un valor de API.

### 6. Un único evento por pulsación física

El bridge transmite únicamente eventos físicos de `keydown`.

No transmite:

- `keyup`;
- eventos de repetición/hold generados por mantener la tecla presionada.

Una pulsación humana no debe convertirse en múltiples POST por autorepeat del sistema operativo.

### 7. HTTP directo al backend y contrato exacto

El bridge envía al endpoint canónico:

```text
POST /api/v1/entradas/tecla
```

con JSON:

```json
{
  "dispositivo": "dev01",
  "tecla": "1"
}
```

La URL base, timeout HTTP y ruta de `devices.json` son configuración técnica del bridge y deben poder suministrarse sin modificar código. El valor productivo de referencia para comunicación local directa es loopback hacia FastAPI.

El bridge puede interpretar la respuesta para logging/diagnóstico, pero no replica reglas de negocio ni transforma un rechazo funcional del backend en una decisión local alternativa.

### 8. Sin reintentos automáticos

Cada `keydown` válido y mapeado genera como máximo un intento HTTP.

No existe reintento automático ante:

- timeout;
- conexión rechazada;
- conexión interrumpida;
- HTTP 4xx;
- HTTP 5xx;
- respuesta inválida.

Motivo: si FastAPI procesó la pulsación pero la respuesta se perdió, un reintento podría duplicar un voto o volver a alternar presencia/pedido de palabra.

El fallo se registra claramente y la siguiente acción funcional requiere una nueva pulsación física.

El bridge tampoco mantiene una cola durable ni reproduce pulsaciones después de reiniciar o recuperar la conectividad. La implementación debe evitar convertir indisponibilidad del backend en reproducción tardía de entradas antiguas.

### 9. Robustez frente a dispositivos

La ausencia temporal de teclados físicos no es un error de configuración del mapa y no debe requerir reiniciar manualmente el bridge para detectar posteriormente un dispositivo conectado.

El runtime debe tolerar conexión/desconexión de dispositivos, cerrar descriptores obsoletos y volver a descubrir dispositivos de entrada sin perder la separación `fingerprint -> devXX`.

Un dispositivo no mapeado se informa de forma diagnóstica pero nunca obtiene asignación automática.

### 10. Remapeo fuera de este alcance

Esta decisión prepara las fronteras necesarias para el remapeo, pero WP-019 no implementa el flujo coordinado de remapeo físico.

El futuro remapeo seguirá DT-014:

- se inicia desde Moderación a través del backend;
- cambia únicamente `fingerprint físico -> devXX` dentro del bridge;
- no cambia identidad, presencia ni votos;
- no habilita conexión directa navegador -> bridge.

### 11. systemd y despliegue

WP-019 debe producir un servicio ejecutable y testeable, pero no instala unidades systemd ni despliega producción.

La unidad `sis-leg-device-bridge.service`, permisos del usuario de servicio, releases y wiring de producción pertenecen al alcance posterior de empaquetado/despliegue conforme DT-028/DT-031.

## Consecuencias

- El bridge nuevo queda acotado al hardware productivo real sin sostener dos backends de captura desde el primer WP.
- Se conserva compatibilidad con fingerprints históricos Linux.
- `devices.json` puede prepararse/migrarse sin cambiar padrón ni backend.
- El backend conserva autoridad exclusiva sobre significado y aceptación de teclas.
- La transmisión de teclas reconocidas no funcionales permite diagnóstico y evolución futura sin ampliar reglas del bridge.
- La ausencia de retries prioriza no duplicar hechos institucionales frente a disponibilidad aparente.
- `evdev` queda como única dependencia runtime directa nueva aprobada para WP-019.

## Pruebas exigidas por la decisión

WP-019 debe cubrir de forma determinista, sin requerir hardware real en CI, al menos:

- construcción exacta de fingerprint Linux;
- validación de `devices.json`, incluidos duplicados y valores inválidos;
- normalización de teclas numéricas, operadores y teclas comunes aprobadas;
- exclusión de `keyup` y auto-repeat;
- resolución fingerprint mapeado/no mapeado;
- un único intento HTTP por pulsación;
- ausencia de retry ante timeout, error de conexión y 5xx;
- contrato JSON exacto hacia `/api/v1/entradas/tecla`;
- manejo de respuesta funcional aceptada y rechazada sin replicar negocio;
- descubrimiento/re-descubrimiento mediante adaptadores inyectables/fakes;
- cierre limpio de recursos.

Las pruebas normales de CI no dependen de `/dev/input/event*`, permisos del grupo `input`, dispositivos USB reales ni conectividad externa.

## Relación con decisiones previas

Esta DEC concreta, sin reemplazarlas:

- DT-002: Python 3.14 + uv;
- DT-004/DT-005: autoridad y serialización únicas del backend;
- DT-007: `/api/v1` y OpenAPI como contrato HTTP;
- DT-010: `services/device-bridge/config/devices.json`;
- DT-014: separación fingerprint físico -> lógico y remapeo futuro;
- DT-021/DT-025/DT-026: pruebas, CI y calidad Python;
- DT-027: Linux Mint 22.3 como plataforma productiva;
- DT-028: servicio systemd futuro;
- DT-038: aprobación humana de dependencias/decisiones reservadas;
- DEC-006: contrato de entrada lógica ya implementado por el backend.
