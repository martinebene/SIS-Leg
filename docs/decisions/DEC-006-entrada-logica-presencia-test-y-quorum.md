# DEC-006 - Entrada lógica, presencia, test y quórum

## Estado

`APROBADA`

## Contexto

WP-006 debe implementar la primera vía lógica de entrada de dispositivos de SIS-Leg sobre el backend ya integrado por WP-002 a WP-005.

La documentación canónica ya define el significado funcional de las teclas y varias invariantes:

- el backend recibe un identificador lógico de dispositivo y una tecla;
- `9` alterna presencia exclusivamente desde el dispositivo asignado al concejal;
- `8` activa un test visual temporal sin modificar estado de negocio;
- en `SIN_PREPARAR` ninguna pulsación produce efecto funcional ni se incorpora a CSV;
- en `PREPARANDO` solo `8` y `9` tienen efecto funcional;
- el quórum se deriva de las presencias actuales y del valor congelado de configuración;
- las pulsaciones, rechazos, presencias y tests deben quedar auditados durante una preparación/sesión;
- toda mutación auditable se ejecuta bajo el serializador único y falla de forma cerrada si no puede garantizarse la auditoría.

Sin embargo, antes de WP-006 no estaban cerrados el endpoint REST exacto, el DTO de respuesta, la duración configurable del test, los códigos concretos de auditoría ni el límite temporal de responsabilidad entre WP-006 y los WPs posteriores de sesión/votación.

Estas decisiones afectan a más de un WP y establecen contratos compartidos, por lo que se registran como DEC conforme a DT-038 y `docs/decisions/README.md`.

## Decisión

### 1. Endpoint REST canónico de pulsación lógica

La API nueva utiliza:

```text
POST /api/v1/entradas/tecla
```

Body obligatorio:

```json
{
  "dispositivo": "dev01",
  "tecla": "9"
}
```

Ambos campos son texto no vacío. El identificador recibido ya es **lógico**; resolver fingerprint físico → dispositivo lógico continúa siendo responsabilidad exclusiva del `device-bridge`.

La operación no recibe DNI, banca ni concejal desde el cliente. El backend resuelve el concejal únicamente mediante el padrón congelado y su `dispositivo_votacion`.

### 2. Semántica HTTP

Una pulsación cuyo JSON cumple el esquema responde `200 OK` tanto cuando produce una acción funcional como cuando es rechazada normalmente por las reglas de entrada.

El bridge debe decidir por el contenido estable de la respuesta, no por textos humanos.

Se reservan:

- `422 Unprocessable Entity`: JSON/body inválido según FastAPI/Pydantic; es un error de contrato de transporte, no un rechazo funcional de una pulsación válida;
- `503 Service Unavailable` + `AUDITORIA_NO_DISPONIBLE`: durante un contexto auditable activo no puede garantizarse el registro obligatorio; la pulsación no se confirma como procesada normalmente;
- `500 Internal Server Error` + `ERROR_INTERNO`: fallo inesperado no clasificado, sin filtrar detalles internos.

### 3. DTO base de respuesta

La forma canónica para una pulsación procesada normalmente es:

```json
{
  "aceptada": true,
  "motivo": "PRESENCIA_ACTUALIZADA",
  "dispositivo": "dev01",
  "tecla": "9",
  "concejal": {
    "dni": "10000001",
    "nombre": "Nombre",
    "apellido": "Apellido",
    "banca": 1
  },
  "resultado": {
    "tipo": "PRESENCIA",
    "presente": true,
    "presentes": 7,
    "quorum_alcanzado": true
  }
}
```

Reglas:

- `aceptada` indica si la pulsación produjo el efecto funcional correspondiente;
- `motivo` es un identificador estable legible por máquina;
- `dispositivo` y `tecla` repiten la entrada lógica efectivamente procesada;
- `concejal` es `null` cuando no puede asociarse el dispositivo; cuando existe contiene únicamente `dni`, `nombre`, `apellido` y `banca`;
- `resultado` es `null` para rechazos normales y un resultado tipado para acciones aceptadas.

Resultado de presencia:

```json
{
  "tipo": "PRESENCIA",
  "presente": true,
  "presentes": 7,
  "quorum_alcanzado": true
}
```

Resultado de test:

```json
{
  "tipo": "TEST",
  "activo": true,
  "duracion_segundos": 0.6
}
```

Los motivos iniciales cerrados por esta decisión son:

- `PRESENCIA_ACTUALIZADA`;
- `TEST_ACTIVADO`;
- `SIN_PREPARAR`;
- `DISPOSITIVO_NO_ASIGNADO`;
- `TECLA_NO_HABILITADA`.

WPs posteriores pueden ampliar el conjunto de motivos para teclas `1`, `2`, `3` y `7` sin cambiar la forma base del DTO, siempre que respeten sus propias reglas canónicas.

### 4. Orden de resolución funcional

Para una pulsación con esquema válido:

1. se evalúa primero el estado global;
2. si está `SIN_PREPARAR`, se responde rechazo normal con `aceptada=false`, `motivo=SIN_PREPARAR`, `concejal=null` y `resultado=null`; no se consulta ni crea auditoría de una preparación inexistente;
3. en un contexto auditable activo, la pulsación recibida debe registrarse antes de resolver su resultado funcional;
4. se busca el dispositivo lógico en el padrón congelado;
5. si no existe asociación, se rechaza con `DISPOSITIVO_NO_ASIGNADO`;
6. se evalúa si la tecla tiene efecto funcional en el estado actual;
7. en `PREPARANDO`, solo `8` y `9` están habilitadas; `1`, `2`, `3`, `7` y cualquier otra tecla válida de transporte se rechazan con `TECLA_NO_HABILITADA`;
8. una acción aceptada solo modifica el estado operativo después de que sus eventos obligatorios hayan quedado persistidos durablemente.

Si el registro de la pulsación recibida o del resultado obligatorio falla, prevalece `503 AUDITORIA_NO_DISPONIBLE`; no se devuelve un `200` que simule un procesamiento normal.

### 5. Presencia y quórum en WP-006

En `PREPARANDO`, tecla `9` del dispositivo asignado alterna exclusivamente la presencia del concejal asociado.

Moderación no dispone de operación equivalente.

Después de cada cambio aceptado se deriva:

```text
presentes = cantidad de valores de presencia en true
quorum_alcanzado = presentes >= configuracion.quorum
```

`configuracion.quorum` pertenece al snapshot congelado de la preparación. No se mantiene una segunda configuración ni se relee `system.toml` al procesar pulsaciones.

El conteo/quórum debe quedar disponible como lógica reutilizable para WP-008 y los WPs de votación, sin adelantar en WP-006 las consecuencias que solo existen con `SESION_ABIERTA` o una votación activa.

### 6. Test visual temporal configurable

Se agrega al contrato canónico de `system.toml`:

```toml
[timers]
device_test_seconds = 0.6
```

Reglas:

- es un número `>= 0`;
- se carga y valida junto con el resto de la configuración;
- queda congelado al iniciar la preparación;
- el valor inicial de referencia es `0.6` segundos;
- representa exclusivamente la duración del test de dispositivo y no reutiliza ningún otro temporizador.

Tecla `8` activa un estado visual temporal para el concejal asociado sin cambiar presencia, quórum ni otro estado de negocio.

Una nueva pulsación `8` mientras el test ya está activo garantiza que el indicador permanezca activo al menos hasta `ahora + device_test_seconds`, sin acortar una expiración posterior ya vigente.

Esta última semántica se conserva por fallback funcional de DEC-001 tras verificar la implementación productiva vigente en:

- `martinebene/Botonera/main/app/services/input_service.py`;
- `martinebene/Botonera/main/app/models/concejal.py`.

La referencia a producción solo resuelve este comportamiento funcional; no se copia su arquitectura ni su implementación técnica.

### 7. Catálogo exacto de auditoría de WP-006

Durante `PREPARANDO`, el catálogo inicial es:

| Nivel | tag | event_code | Semántica |
|---|---|---|---|
| L2 | `INPUT` | `PULSACION_RECIBIDA` | Pulsación lógica recibida antes de resolver su resultado funcional |
| L2 | `INPUT` | `PULSACION_RECHAZADA` | Pulsación procesable a nivel transporte pero rechazada por regla funcional |
| L3 | `PRESENCIA` | `CONCEJAL_PRESENTE` | Cambio aceptado de ausente a presente |
| L3 | `PRESENCIA` | `CONCEJAL_AUSENTE` | Cambio aceptado de presente a ausente |
| L2 | `INPUT` | `TEST_DISPOSITIVO_ACTIVADO` | Activación/renovación aceptada del test visual |

Mensajes humanos canónicos:

```text
PULSACION_RECIBIDA:
Pulsación recibida: tecla [{tecla}] del dispositivo [{dispositivo}]

PULSACION_RECHAZADA:
Pulsación rechazada: tecla [{tecla}] del dispositivo [{dispositivo}]; motivo={motivo}

CONCEJAL_PRESENTE:
{nombre} {apellido} (banca Nro:{banca}) se PRESENTÓ

CONCEJAL_AUSENTE:
{nombre} {apellido} (banca Nro:{banca}) se AUSENTÓ

TEST_DISPOSITIVO_ACTIVADO:
Test de dispositivo activado: {nombre} {apellido} (banca Nro:{banca}); dispositivo=[{dispositivo}]
```

El mensaje puede sustituir únicamente los placeholders con los valores reales; no se cambia el `event_code` para expresar datos variables.

Orden dentro del serializador:

- pulsación aceptada de presencia: `PULSACION_RECIBIDA` → `CONCEJAL_PRESENTE|CONCEJAL_AUSENTE` → mutación de presencia;
- test aceptado: `PULSACION_RECIBIDA` → `TEST_DISPOSITIVO_ACTIVADO` → activación/renovación temporal;
- rechazo normal: `PULSACION_RECIBIDA` → `PULSACION_RECHAZADA` → respuesta `200` con `aceptada=false`.

Los niveles conservan la acumulación definida por DT-011: un L2 se replica en CSV L1+L2 y un L3 en L1+L2+L3.

En `SIN_PREPARAR` no se registra ninguno de estos eventos porque no existe conjunto CSV activo.

### 8. Fallo cerrado

Todo el procesamiento que pueda escribir auditoría o modificar estado operativo se ejecuta bajo el `EjecutorMutaciones` único.

Si el escritor está fallado/cerrado o falla `write`, `flush` o `fsync`:

- no se confirma la mutación funcional dependiente;
- el escritor queda o continúa en fallo cerrado conforme a WP-004/DT-012;
- la API responde `503 AUDITORIA_NO_DISPONIBLE`;
- no se intenta crear un segundo writer, reabrir CSV ni reparar archivos.

El test visual, aunque no sea estado de negocio, forma parte del estado operativo proyectable y tampoco se activa/renueva si no puede persistirse su auditoría obligatoria.

### 9. Límite de WP-006 y extensión posterior

WP-006 implementa el ciclo de entrada, presencia, test y cálculo de quórum **para `PREPARANDO`**, además del rechazo sin efecto de `SIN_PREPARAR` y las primitivas reutilizables necesarias.

No crea `Sesion`, `Votacion`, cola de palabra ni semántica funcional de teclas `1`, `2`, `3` o `7`.

La misma ruta `/api/v1/entradas/tecla` se extenderá posteriormente:

- WP-008 reutilizará presencia/test en `SESION_ABIERTA`;
- los WPs propietarios de votación incorporarán votos y consecuencias de cambios de presencia durante una votación;
- WP-015 incorporará tecla `7` y sus consecuencias de palabra;
- WP-019 implementará el bridge físico y compatibilidad fingerprint → dispositivo lógico.

Esas extensiones no deben romper la forma base de request/response establecida aquí.

## Alternativas consideradas

### Endpoint que responda errores HTTP para rechazos funcionales

Rechazada. El bridge necesita distinguir de forma uniforme pulsaciones aceptadas/rechazadas como resultado normal del procesamiento. Los errores HTTP quedan reservados para contrato de transporte y fallos técnicos.

### Duración de test fija en código

Rechazada. El test es un temporizador con significado propio y la configuración canónica ya exige parámetros semánticos separados para temporizadores distintos.

### Copiar íntegramente la lógica histórica de entradas

Rechazada. Producción se utiliza únicamente como fallback funcional permitido por DEC-001. La arquitectura, serialización, auditoría y contratos técnicos se rigen por SIS-Leg.

### Implementar desde WP-006 presencia dentro de sesión/votación

Rechazada. Adelantaría entidades y consecuencias cuyos propietarios son WP-008 y los WPs de votación, ampliando innecesariamente el contexto y el alcance.

## Consecuencias

- WP-006 debe ampliar el modelo/cargador de configuración y el archivo de referencia `config/system.toml` mediante su rama/PR de implementación; este DEC solo fija documentalmente el contrato.
- La respuesta de entrada queda preparada para crecer sin que el bridge deba reinterpretar textos humanos.
- El quórum queda como dato derivado de las presencias y de la configuración congelada, no como segunda fuente de verdad.
- Los tests temporales requieren una representación operativa consultable por futuras proyecciones, pero la estructura interna concreta queda dentro de la autonomía técnica local del implementador.
- Los futuros WPs de sesión, votación, palabra y bridge deben reutilizar la ruta y forma base definidas aquí.
- La auditoría de entrada de WP-006 queda cerrada en niveles, tags, códigos y mensajes, por lo que el implementador no puede cambiarlos unilateralmente.

## Documentos y WPs afectados

Fuentes relacionadas que esta decisión precisa sin reemplazar:

- `docs/01-reglas-de-negocio.md`: RN-INP, RN-PRE y RN-LOG;
- `docs/02-modelo-de-dominio-y-estados.md`: Preparacion, Concejal, Presencia y MapeoDispositivo;
- `docs/03-casos-de-uso.md`: CU-03 y CU-04;
- `docs/04-contratos-e-integraciones.md`: entrada física, API nueva, concurrencia y auditoría;
- `docs/07-configuracion-datos-y-assets.md`: configuración, temporizadores y mapeo físico;
- `docs/08-observabilidad-y-auditoria.md`: categorías, niveles y fallo cerrado;
- `docs/11-criterios-de-aceptacion.md`: CA-005, CA-006, CA-007, CA-055, CA-058 y CA-059;
- `docs/12-decisiones-tecnicas.md`: DT-004, DT-007, DT-010, DT-011, DT-012 y DT-021;
- WP-006;
- WP-008;
- WPs de votación que procesen presencia/votos;
- WP-015;
- WP-019.
