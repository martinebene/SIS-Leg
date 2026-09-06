# Simulador CLI de Dispositivos y Escenarios (tools/device-simulator)

Herramienta de desarrollo y diagnostico por linea de comandos (CLI) de **SIS-Leg** para emitir pulsaciones logicas y ejecutar escenarios declarativos reproducibles sin requerir hardware fisico.

---

## 1. Proposito y limites

El simulador envia pulsaciones reales al endpoint canonico del backend:

```http
POST /api/v1/entradas/tecla
```

con el cuerpo JSON:

```json
{
  "dispositivo": "dev05",
  "tecla": "9"
}
```

### Que hace el simulador

- Permite probar el sistema manualmente desde terminal mediante una consola interactiva persistente.
- Permite emitir una pulsacion rapida individual desde shell.
- Permite ejecutar escenarios declarativos versionados en JSON con pulsaciones secuenciales, pausas temporales y grupos concurrentes reales.
- Muestra el **codigo de estado HTTP** y el **cuerpo literal crudo devuelto por el servidor**, garantizando diagnostico fiel al depurar contratos y rechazos.
- Evalua expectativas opcionales (`status_http`, `aceptada`, `motivo`) para integracion y pruebas automatizadas.

### Convivencia con el Simulador Web (WP-034)

SIS-Leg dispone de dos herramientas complementarias de simulación que comparten el mismo principio arquitectónico (envío directo a `POST /api/v1/entradas/tecla` sin atravesar el `device-bridge`):

1. **Simulador CLI (`tools/device-simulator/`)**: enfocado en terminal, CI, automatización de pruebas y ejecución reproducible de escenarios JSON con temporización y concurrencia controlada.
2. **Simulador Web (`apps/simulador/` en `/simulador/`)**: SPA interactiva en Nuxt 4 para prueba humana y diagnóstico visual, que presenta los 12 dispositivos simultáneamente en pantalla con botones individuales, panel de estado y log en tiempo real.

Ambas herramientas son clientes equivalentes y ninguna de las dos impone reglas de negocio locales: la autoridad absoluta de validación reside en FastAPI.

---

## 2. Requisitos previos

El simulador es un cliente HTTP puro: requiere que el servidor backend de SIS-Leg YA se encuentre en ejecucion y sea accesible en la red (por defecto en `http://127.0.0.1:8000`, o en la direccion que se indique mediante `--url-base`).

El procedimiento de despliegue, configuracion e inicio del proceso del backend pertenece al procedimiento y runtime propio del backend, y queda fuera del alcance de este simulador (WP-007).

---

## 3. Formas de uso

### A. Modo interactivo manual persistente

Ejecutar sin argumentos de pulsacion ni escenario abre una consola interactiva que permanece abierta recibiendo comandos:

```bash
uv run python tools/device-simulator/simulador.py
```

Tambien es posible especificar una URL base diferente:

```bash
uv run python tools/device-simulator/simulador.py --url http://127.0.0.1:8000
```

#### Comandos en la consola interactiva

- **Enviar pulsacion:** Escriba `<numero>-<tecla>` (ejemplos: `1-9`, `12-8`, `3-+`, `5--`, `4-enter`).
- **`ayuda` / `help` / `?`:** Muestra las instrucciones de sintaxis.
- **`url`:** Muestra la URL base activa y el endpoint canonico.
- **`salir` / `exit` / `q`:** Cierra la sesion interactiva.

#### Ejemplo de sesion interactiva

```text
============================================================
SIS-Leg - Simulador CLI de Dispositivos (Modo Interactivo)
Conectado a URL base: http://127.0.0.1:8000
Endpoint: http://127.0.0.1:8000/api/v1/entradas/tecla
Escriba 'ayuda' para ver instrucciones o 'salir' para terminar.
============================================================

> 1-9
[envio] dispositivo=dev01 tecla=9
[respuesta] HTTP 200
{"aceptada":true,"dispositivo":"dev01","tecla":"9","motivo":"PRESENCIA_ACTUALIZADA","concejal":{"dni":"10000001","nombre":"Nombre 01","apellido":"Apellido 01","banca":1},"resultado":{"tipo":"PRESENCIA","presente":true,"presentes":1,"quorum_alcanzado":false}}
[resumen] aceptada=True motivo=PRESENCIA_ACTUALIZADA concejal='Nombre 01 Apellido 01' banca=1 (presente=True, total=1, quorum=False)

> 1-4
[envio] dispositivo=dev01 tecla=4
[respuesta] HTTP 200
{"aceptada":false,"dispositivo":"dev01","tecla":"4","motivo":"TECLA_NO_HABILITADA","concejal":{"dni":"10000001","nombre":"Nombre 01","apellido":"Apellido 01","banca":1},"resultado":null}
[resumen] aceptada=False motivo=TECLA_NO_HABILITADA concejal='Nombre 01 Apellido 01' banca=1

> 99-9
[envio] dispositivo=dev99 tecla=9
[respuesta] HTTP 200
{"aceptada":false,"dispositivo":"dev99","tecla":"9","motivo":"DISPOSITIVO_NO_ASIGNADO","concejal":null,"resultado":null}
[resumen] aceptada=False motivo=DISPOSITIVO_NO_ASIGNADO

> salir
Sesion finalizada.
```

---

### B. Pulsacion unica desde shell

Para enviar un solo comando desde terminal y terminar inmediatamente:

```bash
uv run python tools/device-simulator/simulador.py 5-9
```

Con URL personalizada:

```bash
uv run python tools/device-simulator/simulador.py 12-8 --url http://192.168.1.50:8000
```

#### Codigos de salida del proceso

- `0`: Exito de comunicacion HTTP con codigo `2xx` (incluso si funcionalmente `aceptada=false` en el DTO).
- `1`: Error de sintaxis local, timeout, error de conexion o respuesta HTTP de error `4xx`/`5xx`.

---

### C. Ejecucion de escenarios declarativos (JSON)

Para ejecutar una secuencia automatizada de pasos definida en un archivo JSON:

```bash
uv run python tools/device-simulator/simulador.py --escenario tools/device-simulator/escenarios/presencia_tecla_9.json
```

O en forma corta:

```bash
uv run python tools/device-simulator/simulador.py -e tools/device-simulator/escenarios/grupo_concurrente.json
```

#### Codigos de salida del proceso

- `0`: Todos los pasos se ejecutaron y todas las expectativas declaradas fueron satisfechas.
- `1`: Al menos una expectativa no se cumplio, ocurrio un error de red o el archivo JSON es invalido.

---

## 4. Sintaxis compacta de pulsaciones

La sintaxis utilizada en la consola y por argumento shell es:

```text
<numero-dispositivo>-<tecla>
```

### Reglas

1. **Separador:** Se toma exclusivamente el **primer guion `-`** encontrado.
2. **Parte izquierda (dispositivo):** Numero entero no negativo (sin prefijo `dev`). El simulador lo normaliza a formato de al menos dos digitos:
   - `1` $\rightarrow$ `dev01`
   - `5` $\rightarrow$ `dev05`
   - `12` $\rightarrow$ `dev12`
   - `99` $\rightarrow$ `dev99`
3. **Parte derecha (tecla):** Texto no vacio que identifica la tecla pulsada:
   - Numeros: `1`, `2`, `3`, `8`, `9`, `0`, `4`...
   - Signos: `+`, `-`, `.`, `/`, `*`
   - Nombres textuales: `enter`, `numlock`, `backspace`
4. **Ejemplo con signo menos:** `5--` se parsea correctamente como dispositivo `dev05` y tecla `-`.

---

## 5. Formato de escenarios JSON

Un archivo de escenario tiene la siguiente estructura minima:

```json
{
  "nombre": "mi-escenario-de-prueba",
  "precondicion": "backend en PREPARANDO con configuracion/padron de referencia",
  "pasos": [
    {
      "entrada": "1-9",
      "esperado": {
        "status_http": 200,
        "aceptada": true,
        "motivo": "PRESENCIA_ACTUALIZADA"
      }
    },
    {
      "pausa_ms": 100
    },
    {
      "concurrentes": [
        {
          "entrada": "2-9",
          "esperado": {
            "status_http": 200,
            "aceptada": true,
            "motivo": "PRESENCIA_ACTUALIZADA"
          }
        },
        {
          "entrada": "3-4",
          "esperado": {
            "status_http": 200,
            "aceptada": false,
            "motivo": "TECLA_NO_HABILITADA"
          }
        }
      ]
    }
  ]
}
```

### Tipos de pasos soportados

1. **Pulsacion individual:** Objeto con `"entrada": "5-9"` (o `"dispositivo": "dev05", "tecla": "9"`) y un bloque opcional `"esperado"`.
2. **Pausa temporal:** Objeto con `"pausa_ms": <milisegundos>` o `"pausa_segundos": <segundos>`.
3. **Grupo concurrente:** Objeto con `"concurrentes": [ <lista de pulsaciones> ]`. Dispara todas las peticiones en paralelo real usando asincronismo.

### Expectativas opcionales (`esperado`)

Cualquier campo dentro de `esperado` es opcional:

- `"status_http"`: Codigo entero (ejemplo: `200`, `422`, `503`).
- `"aceptada"`: Booleano (`true` o `false`).
- `"motivo"`: Codigo de motivo esperado (ejemplo: `"PRESENCIA_ACTUALIZADA"`, `"TEST_ACTIVADO"`, `"DISPOSITIVO_NO_ASIGNADO"`, `"TECLA_NO_HABILITADA"`).

---

## 6. Escenarios versionados incluidos

Bajo `tools/device-simulator/escenarios/` se incluyen los siguientes escenarios iniciales de referencia:

- `presencia_tecla_9.json`: Alterna presencia acreditando concejal con tecla 9.
- `test_tecla_8.json`: Activa el test visual de dispositivo con tecla 8.
- `dispositivo_no_asignado.json`: Envia pulsacion desde un dispositivo inexistente (`dev99`) comprobando rechazo `DISPOSITIVO_NO_ASIGNADO`.
- `tecla_no_habilitada.json`: Envia teclas de votacion/palabra (`1`, `2`, `3`, `7`) durante `PREPARANDO` comprobando rechazo `TECLA_NO_HABILITADA`.
- `tecla_sin_semantica.json`: Envia teclas sin asignacion (`4`, `+`, `enter`) comprobando rechazo controlado `TECLA_NO_HABILITADA`.
- `grupo_concurrente.json`: Emite multiples pulsaciones simultaneas comprobando ejecucion concurrente real y serializacion del servidor.
