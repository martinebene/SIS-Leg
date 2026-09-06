# DEC-009 - Apertura de votación, bases de mayoría y contrato REST

## Estado

`APROBADA`

## Contexto

WP-009 inicia el núcleo de votación de SIS-Leg. Su alcance funcional inmediato es abrir una votación dentro de una sesión ya abierta, validar sus datos y precondiciones, publicar una única votación activa e impedir que sus datos constitutivos cambien después de la apertura.

Durante la planificación de WP-009 el operador cerró además una precisión de negocio necesaria para los WPs posteriores de cálculo de resultados: la palabra institucional `PRESENTES`, cuando se utiliza como base de una mayoría especial, refiere a quienes participaron efectivamente de esa votación emitiendo voto, independientemente de que su presencia dinámica cambie después. Técnicamente equivale a contar todos los votos ordinarios emitidos, incluidas las abstenciones.

Esta decisión fue resuelta explícitamente por el operador el 2026-08-21.

## Autoridad y compatibilidad documental

Esta DEC es vinculante para WP-009 y para los WPs posteriores que modelen votos, mayorías, Orden del Día o formularios de votación.

Cuando exista una formulación anterior incompatible, esta DEC posterior prevalece. En particular:

- `PRESENTES` no significa una fotografía de la presencia dinámica al momento del cálculo: como base de mayoría significa votos ordinarios emitidos, incluidas abstenciones;
- se agrega `VOTOS_COMPUTABLES` como tercera base explícita;
- una mayoría especial puede computarse sobre `VOTOS_COMPUTABLES`, `PRESENTES` o `CUERPO`;
- una mayoría simple puede recibir `factor` omitido/nulo o `0`, pero su base canónica es siempre `VOTOS_COMPUTABLES`;
- `factor=0` no convierte una mayoría declarada como `ESPECIAL` en `SIMPLE`: `tipo_mayoria` continúa siendo explícito y autoritativo.

La documentación funcional general debe quedar alineada con estas reglas cuando el WP propietario modifique las secciones afectadas.

## Decisiones

### 1. Número externo de votación

`numero_votacion` es un entero estricto positivo, `>= 1`.

Se rechazan como entrada:

- `0`;
- negativos;
- booleanos;
- decimales;
- texto.

El número es un dato institucional externo. El sistema no valida secuencia, unicidad, repetición ni continuidad respecto de votaciones anteriores. Repetir un número o usar uno fuera de secuencia es válido.

### 2. Tipo descriptivo de votación

`tipo` es texto obligatorio y debe corresponder a uno de los valores configurados en el snapshot congelado de `system.toml -> [voting].types` de la preparación/sesión vigente.

Reglas:

- la entrada se normaliza retirando espacios exteriores;
- después de normalizar no puede quedar vacía;
- la comparación con los tipos configurados es exacta en contenido y mayúsculas/minúsculas; no se inventan alias ni equivalencias;
- los tipos configurados son la autoridad para la sesión activa y no se relee `system.toml` al abrir cada votación.

### 3. Tema

`tema` es texto libre obligatorio.

Se normaliza con `strip` y debe conservar al menos un carácter después de normalizar. No se acepta un tema vacío o compuesto solo por espacios.

### 4. Tipos de mayoría

Los valores canónicos son:

```text
SIMPLE
ESPECIAL
```

`tipo_mayoria` es siempre explícito. No se infiere silenciosamente el tipo de mayoría únicamente a partir del valor de `factor`.

### 5. Bases de cálculo

Los valores canónicos de `base` son:

```text
VOTOS_COMPUTABLES
PRESENTES
CUERPO
```

Su significado institucional y técnico es:

#### `VOTOS_COMPUTABLES`

Representa únicamente los votos que participan del cálculo comparativo/cociente:

```text
positivos + negativos
```

Las abstenciones son votos válidos y se registran, pero no integran esta base.

#### `PRESENTES`

Es la denominación institucional de quienes estuvieron presentes a efectos de esa votación y lograron emitir su voto.

Su denominador técnico es:

```text
positivos + negativos + abstenciones
```

Por lo tanto:

- quien votó y luego se retiró continúa integrando `PRESENTES` para esa votación;
- quien se incorporó durante `EN_CURSO` y logró votar también la integra;
- la base no se recalcula retirando votos por cambios posteriores de presencia dinámica.

La presencia dinámica conserva, de forma independiente, sus responsabilidades sobre quórum, habilitación para votar y completitud de la votación.

#### `CUERPO`

Representa la cantidad total de concejales cargados en el padrón congelado para la preparación/sesión.

Presidencia no agrega una unidad por ocupar ese rol institucional.

### 6. Mayoría SIMPLE

Una mayoría simple utiliza siempre, conceptualmente, la base:

```text
VOTOS_COMPUTABLES
```

No utiliza cociente ni porcentaje para decidir el resultado. Su regla, que será implementada por el WP propietario del cálculo, es:

```text
positivos > negativos  -> APROBADA
positivos < negativos  -> RECHAZADA
positivos = negativos  -> EMPATADA
```

Las abstenciones no participan del cálculo.

Ejemplos:

```text
3 positivos, 0 negativos, 4 abstenciones -> APROBADA
3 positivos, 3 negativos, 1 abstención  -> EMPATADA
```

Para creación por API:

- `factor` puede omitirse, ser `null` o ser numéricamente `0`;
- una cadena vacía `""` no es un número y se rechaza como body inválido; una UI con caja vacía debe enviar omisión o `null`;
- internamente y en la representación normalizada de la votación, la ausencia de mayoría especial se representa de forma consistente como `factor = 0`;
- `base` puede omitirse o declarar `VOTOS_COMPUTABLES`;
- si se suministra `PRESENTES` o `CUERPO` con `SIMPLE`, la entrada es incoherente y se rechaza;
- la representación normalizada siempre expone `base = VOTOS_COMPUTABLES`.

### 7. Mayoría ESPECIAL

Una mayoría especial exige:

```text
tipo_mayoria = ESPECIAL
factor > 0 y <= 1
base = VOTOS_COMPUTABLES | PRESENTES | CUERPO
```

`factor` debe ser un número real finito. Se rechazan booleanos, cero, negativos, `NaN`, infinitos y valores mayores que `1`.

El cálculo futuro será:

```text
positivos / denominador >= factor -> APROBADA
positivos / denominador <  factor -> RECHAZADA
```

con el denominador determinado por `base` según esta DEC.

`ESPECIAL` con `factor` omitido, `null` o `0` es incoherente y se rechaza. No se transforma silenciosamente en `SIMPLE`.

Si una votación especial sobre `VOTOS_COMPUTABLES` finaliza normalmente con denominador `0` porque todos los votos emitidos fueron abstenciones, no se realiza una división por cero: el resultado es `RECHAZADA`, interpretando que no se alcanzó el mínimo exigido.

El cálculo de resultados no pertenece a WP-009; esta regla se fija ahora para evitar reinterpretaciones posteriores.

### 8. Precondiciones de apertura

Una votación solo puede abrirse si, en este orden lógico:

1. el estado global es `SESION_ABIERTA` y existe una sesión activa coherente;
2. existe quórum en ese momento;
3. no existe una votación pendiente publicada en `EstadoOperativo.votacion_activa`;
4. el body cumple el contrato técnico y de negocio de esta DEC.

Mientras una votación permanezca `EN_CURSO` o, en WPs posteriores, `EMPATADA`, debe mantenerse como votación pendiente y bloquear una nueva apertura.

Una votación que alcance un estado final no bloqueante será retirada de `votacion_activa` por el WP propietario de esa transición, pero debe permanecer en el historial de la sesión.

### 9. Inmutabilidad de datos constitutivos

Después de una apertura aceptada quedan inmutables durante toda la vida de esa votación:

- identificador técnico;
- número externo;
- tipo descriptivo;
- tema;
- tipo de mayoría;
- factor normalizado;
- base normalizada;
- fecha/hora de apertura.

No debe existir `PATCH` de votación ni otro comando que edite esos campos. Si institucionalmente se cargaron mal, la corrección futura consiste en finalizar la votación conforme a las reglas de negocio y abrir otra.

El estado de la votación, votos, fecha/hora de cierre, motivo de finalización y eventual desempate son datos evolutivos de WPs posteriores y no contradicen la inmutabilidad de los datos constitutivos.

### 10. Identificador técnico

Cada votación recibe al abrir un `id` técnico generado por backend.

Contrato:

- se expone como texto opaco;
- no posee significado institucional;
- no sustituye a `numero_votacion`;
- debe ser único dentro de la ejecución activa, como mínimo;
- el mecanismo concreto de generación puede variar mientras preserve esas propiedades y no introduzca una nueva dependencia/persistencia.

### 11. Historial y fuente de verdad

La `Sesion` debe poder conservar una colección ordenada de votaciones abiertas durante esa sesión.

Al abrir:

- se crea una única entidad `Votacion`;
- esa misma entidad queda referenciada por `EstadoOperativo.votacion_activa`;
- esa misma entidad se incorpora al historial de la sesión;
- no se mantienen copias funcionales divergentes de una misma votación.

En WP-009 la única transición creada es apertura a `EN_CURSO`.

### 12. Contrato REST de apertura

El recurso canónico es una colección:

```text
POST /api/v1/votaciones
```

No se utiliza una ruta de acción `/abrir_votacion` ni un `POST /api/v1/votacion` singleton.

Ejemplo SIMPLE:

```json
{
  "numero_votacion": 37,
  "tipo": "Mocion",
  "tema": "Tratamiento del proyecto X",
  "tipo_mayoria": "SIMPLE"
}
```

También son válidos para SIMPLE, respetando las reglas anteriores:

```json
{
  "numero_votacion": 37,
  "tipo": "Mocion",
  "tema": "Tratamiento del proyecto X",
  "tipo_mayoria": "SIMPLE",
  "factor": 0,
  "base": "VOTOS_COMPUTABLES"
}
```

Ejemplo ESPECIAL:

```json
{
  "numero_votacion": 38,
  "tipo": "Despacho HA",
  "tema": "Tratamiento del proyecto Y",
  "tipo_mayoria": "ESPECIAL",
  "factor": 0.6666666667,
  "base": "CUERPO"
}
```

El body no admite campos extra.

Respuesta exitosa:

```text
201 Created
```

con una representación normalizada de la votación creada que incluya, como mínimo:

```json
{
  "id": "identificador-opaco",
  "numero_votacion": 37,
  "tipo": "Mocion",
  "tema": "Tratamiento del proyecto X",
  "tipo_mayoria": "SIMPLE",
  "factor": 0,
  "base": "VOTOS_COMPUTABLES",
  "estado": "EN_CURSO",
  "fecha_hora_apertura": "2026-08-21T14:00:00"
}
```

No se exige todavía exponer votos, resultado ni datos de cierre porque no pertenecen al alcance de apertura.

### 13. Errores

La forma de error funcional/técnico continúa siendo:

```json
{
  "codigo": "CODIGO_ESTABLE",
  "mensaje": "Mensaje legible por personas."
}
```

Mapeo mínimo para apertura:

- body Pydantic inválido o combinación incoherente de campos: `422 Unprocessable Entity`;
- `tipo` técnicamente válido pero no perteneciente a `voting.types` de la configuración congelada: `422 Unprocessable Entity` + `TIPO_VOTACION_NO_PERMITIDO`;
- estado global incompatible: `409 Conflict` + `ESTADO_INCOMPATIBLE`;
- falta de quórum: `409 Conflict` + `QUORUM_INSUFICIENTE`;
- existe una votación pendiente: `409 Conflict` + `VOTACION_PENDIENTE`;
- auditoría obligatoria no disponible: `503 Service Unavailable` + `AUDITORIA_NO_DISPONIBLE`;
- fallo inesperado no clasificado: `500 Internal Server Error` + `ERROR_INTERNO`.

Un `422` rechazado antes de entrar al servicio de dominio no requiere evento de auditoría institucional.

### 14. Auditoría de apertura

Una apertura aceptada debe persistir antes de publicar la mutación:

```text
L3 | VOTACION | VOTACION_ABIERTA
```

El mensaje humano debe permitir identificar al menos:

- número externo;
- tipo;
- tema;
- tipo de mayoría;
- factor normalizado;
- base normalizada.

Los rechazos funcionales de apertura que ocurran mientras existe auditoría activa se registran, cuando la auditoría está disponible, como:

```text
L2 | VOTACION | COMANDO_VOTACION_RECHAZADO
```

El mensaje identifica la operación y el código estable del rechazo.

Toda mutación sigue el orden obligatorio:

```text
VALIDAR -> AUDITAR -> MUTAR/PUBLICAR
```

mediante el `EjecutorMutaciones` único. Si falla la auditoría, no se publica `votacion_activa`, no se incorpora la votación al historial y no se devuelve `201`.

### 15. Convivencia con presencia, test y autoridades

Abrir una votación no congela ni reinicia el contexto operativo de sesión.

Continúan siendo válidos, de acuerdo con sus WPs propietarios:

- test por tecla `8`;
- cambio de presencia por tecla `9`;
- cambio de Presidencia;
- cambio de Secretaría Legislativa.

WP-009 no implementa todavía las consecuencias completas de votos, autocierre o pérdida de quórum durante `EN_CURSO`. Esas transiciones pertenecen a WPs posteriores definidos por PLAN.

### 16. Fuera de alcance de DEC-009/WP-009

Esta decisión no adelanta implementación de:

- votos ordinarios `1`, `2`, `3`;
- unicidad/irreversibilidad de voto;
- autocierre por completitud;
- cálculo efectivo de SIMPLE o ESPECIAL;
- transición a `APROBADA`, `RECHAZADA`, `EMPATADA` o `INCONCLUSA`;
- pérdida de quórum durante `EN_CURSO`;
- finalización manual;
- motivo de finalización;
- desempate presidencial;
- cierre de sesión que resuelva una votación pendiente;
- Orden del Día;
- frontend de Moderación;
- snapshots/SSE/proyección pública;
- uso de palabra.

## Consecuencias

- WP-009 puede implementar la apertura sin decidir semántica de campos durante la ejecución.
- El contrato distingue con claridad número externo e identificador técnico.
- `VOTOS_COMPUTABLES`, `PRESENTES` y `CUERPO` quedan definidos una única vez para todos los WPs de mayorías.
- `PRESENTES` conserva la terminología institucional usada por los operadores, mientras el código puede documentar que su denominador técnico son los votos ordinarios emitidos.
- La mayoría simple conserva la comparación positivos/negativos y el futuro estado `EMPATADA`.
- Las mayorías especiales pueden expresar los tres denominadores institucionalmente necesarios sin reutilizar términos ambiguos.
- Los documentos generales y el contrato futuro de Orden del Día deberán alinearse con esta decisión antes de implementar sus respectivos alcances.
