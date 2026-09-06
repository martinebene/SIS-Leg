# DEC-014 - Cliente API TypeScript, OpenAPI y reconexión

**Estado:** `APROBADA`

## Contexto

DT-006 estableció REST para comandos, snapshots y consultas puntuales, y Server-Sent Events (SSE) para cambios de estado backend -> frontend. DT-007 estableció que FastAPI + Pydantic y el OpenAPI generado por FastAPI constituyen el contrato HTTP técnico canónico. DT-018 reservó `packages/api-client/` para tipos derivados de OpenAPI, cliente REST, errores uniformes, SSE, reconexión, recuperación de snapshot y control de sincronización.

WP-017 integró los cuatro endpoints canónicos de estado, DTOs separados de Moderación/Recinto, revisión monotónica volátil y el protocolo de recuperación documentado por DEC-013. Los frontends futuros necesitan consumir ese contrato sin duplicar reglas de negocio ni mantener manualmente tipos que puedan divergir del backend.

El scaffold de `packages/api-client/` existe desde WP-001, pero permanece sin implementación funcional.

Al planificar WP-018 se presentaron al responsable humano tres decisiones reservadas por DT-038 y fueron aprobadas explícitamente:

1. utilizar `openapi-typescript@7.13.0` como única nueva dependencia directa de desarrollo necesaria para derivar tipos desde OpenAPI;
2. versionar tanto un snapshot OpenAPI generado desde FastAPI como los tipos TypeScript generados, con comprobación automática de drift;
3. exponer clientes separados para Moderación y Recinto, de modo que el cliente público carezca estructuralmente de métodos mutantes.

La versión `7.13.0` fue verificada al momento de la decisión como la etiqueta `latest` publicada de `openapi-typescript`. Es una herramienta de generación de tipos sin runtime para el código cliente.

## Decisión

### 1. Paquete canónico

El cliente compartido vive exclusivamente en:

```text
packages/api-client/
```

El paquete es la frontera TypeScript común para consumir la API interna de SIS-Leg. No se duplicarán clientes REST/SSE independientes dentro de `apps/moderacion` y `apps/recinto`.

### 2. Fuente de verdad y generación de tipos

FastAPI + Pydantic continúan siendo la fuente técnica canónica del contrato HTTP.

El flujo derivado será:

```text
FastAPI/Pydantic
    -> OpenAPI versionado
    -> tipos TypeScript generados
    -> cliente API escrito contra esos tipos
```

Se versionarán en el repositorio:

- un snapshot OpenAPI generado desde la aplicación FastAPI vigente;
- los tipos TypeScript generados desde ese snapshot.

Los nombres/rutas exactos de esos dos artefactos pueden definirse dentro de WP-018, siempre dentro de `packages/api-client/` y con comandos deterministas y documentados para regenerarlos.

No se mantendrán manualmente copias alternativas de los mismos DTOs como fuente de verdad.

### 3. Herramienta aprobada

Se aprueba como única nueva dependencia directa externa para este alcance:

```text
openapi-typescript@7.13.0
```

Debe incorporarse como `devDependency` asociada al tooling de `packages/api-client/`.

No se aprueban por esta decisión dependencias runtime adicionales como `openapi-fetch`, librerías SSE, librerías de reconexión, stores de estado, clientes HTTP alternativos ni validadores de esquema runtime.

Si el implementador considera imprescindible otra dependencia directa, debe escalarla nuevamente conforme DT-038 antes de incorporarla.

### 4. Drift de contrato

La CI debe poder detectar por separado:

1. que el snapshot OpenAPI versionado coincide con el OpenAPI que genera el backend actual;
2. que los tipos TypeScript versionados coinciden con ese snapshot OpenAPI.

Una modificación de backend que cambie OpenAPI sin regenerar los artefactos debe fallar en un gate automático aplicable.

La generación debe ser determinista y ejecutable localmente sin depender de un servidor externo ni de red.

### 5. Primitivas runtime

El cliente runtime utilizará primitivas web/nativas:

- `fetch` para REST;
- `EventSource` para SSE.

Ambas deben poder sustituirse/injectarse mediante una frontera testeable equivalente, para que las pruebas no dependan de red real ni de temporizadores no deterministas.

No se reintroduce polling periódico.

### 6. Clientes separados

El paquete expondrá dos superficies públicas distintas:

#### ClienteModeracion

Incluye:

- snapshot completo de Moderación;
- stream SSE de Moderación;
- recuperación/reconexión;
- los comandos REST ya implementados y destinados a la aplicación de Moderación.

No debe exponer como comando de operador el endpoint de entrada física destinado al bridge.

#### ClienteRecinto

Incluye únicamente operaciones de solo lectura necesarias para la Pantalla del Recinto:

- snapshot completo del Recinto;
- stream SSE del Recinto;
- recuperación/reconexión.

No debe contener métodos de preparar, modificar sesión, votar, finalizar, desempatar, palabra, Orden del Día ni ninguna otra mutación, aunque esas rutas existan en el mismo OpenAPI.

Esta separación refuerza en TypeScript la regla de solo lectura del Recinto; no sustituye la seguridad y proyección restrictiva ya garantizadas por backend.

### 7. Comandos de Moderación

Los wrappers REST deben cubrir las operaciones canónicas existentes que corresponden al operador, incluyendo según el OpenAPI vigente:

- preparar, actualizar y cancelar preparación;
- abrir, actualizar y cerrar sesión;
- cargar y descartar Orden del Día;
- abrir y finalizar votación;
- emitir desempate presidencial;
- otorgar y quitar palabra.

La carga de Orden del Día conserva el contrato multipart/form-data del backend.

Los wrappers no reconstruyen capacidades ni reglas de negocio: envían la intención y propagan el resultado/error tipado del backend.

### 8. Modelo uniforme de errores

El paquete debe ofrecer una representación discriminable y estable para errores de cliente, separando como mínimo:

- respuesta HTTP no exitosa del backend;
- error de transporte/red;
- error de protocolo/parsing;
- cancelación/disposición cuando corresponda.

Cuando el backend responda el contrato estructurado `{ codigo, mensaje }`, ambos valores deben preservarse sin reinterpretarlos ni reemplazarlos por mensajes locales.

Cuando una respuesta de validación HTTP no utilice ese contrato exacto, el cliente debe conservar información útil de status/body sin inventar un supuesto código estable de dominio.

Los comandos `204 No Content` no deben intentar parsear JSON inexistente.

### 9. Sincronización inicial

Para cada consumidor, la secuencia normal es:

1. obtener snapshot REST completo;
2. establecer ese snapshot como baseline local;
3. abrir el SSE correspondiente;
4. procesar el primer estado completo del stream y las publicaciones posteriores.

Los mensajes SSE son estados completos, no deltas.

Dentro de una misma conexión/época observada, el cliente no debe retroceder a una revisión anterior por reordenamiento o duplicación. Revisiones iguales pueden considerarse idempotentes.

### 10. Revisión reiniciable después de restart

`revision` es monotónica únicamente durante la vida de un proceso backend y reinicia junto con el estado volátil cuando FastAPI reinicia.

Por eso una recuperación mediante snapshot REST **establece una nueva baseline aunque su número de revisión sea menor que el observado antes de la desconexión**.

Ejemplo válido:

```text
antes de caer backend: revision 142
backend reinicia
snapshot de recuperación: revision 0, SIN_PREPARAR
```

El cliente debe aceptar ese snapshot de recuperación y no conservar indebidamente el estado viejo por comparar `0 < 142`.

Luego, sobre el nuevo stream, vuelve a exigir progreso/no retroceso relativo a esa nueva baseline.

Si durante una conexión aparentemente continua aparece una revisión incompatible que no puede explicarse de forma segura, el cliente debe forzar recuperación por snapshot en lugar de intentar reconstruir continuidad por su cuenta.

### 11. Reconexión canónica

El `EventSource` nativo no debe quedar librado a una reconexión automática que omita la recuperación de snapshot requerida por DT-006/DEC-013.

Ante pérdida/error del stream, el cliente debe controlar el ciclo:

1. cerrar/descartar el `EventSource` fallado;
2. aplicar una espera de reconexión acotada/configurable;
3. obtener un nuevo snapshot REST;
4. tomarlo como nueva baseline;
5. crear un `EventSource` nuevo;
6. repetir mientras el consumidor continúe activo.

La estrategia puede utilizar backoff acotado y testeable. Los valores concretos por defecto son una decisión local reversible del WP, siempre que no produzcan polling continuo ni esperas ilimitadas no cancelables.

El ciclo debe poder detenerse explícitamente mediante `dispose`, `abort`, `cerrar` o una interfaz equivalente.

### 12. Carrera snapshot -> SSE

El backend ya garantiza que el primer mensaje SSE contiene el estado completo vigente. Por ello, si ocurre una mutación entre el snapshot REST y la apertura del stream, el primer mensaje SSE posterior debe actualizar al cliente sin necesidad de replay histórico.

El cliente debe comparar revisiones dentro de la baseline vigente y conservar la versión igual o más reciente, sin depender de haber observado todos los números intermedios.

### 13. Separación de responsabilidades

El `api-client` se ocupa de:

- transporte REST;
- tipos derivados;
- normalización de errores de transporte/HTTP/protocolo;
- parseo del protocolo SSE;
- reconexión;
- snapshot recovery;
- control técnico de revisión/sincronización.

No se ocupa de:

- reglas de negocio;
- capacidades operativas calculadas localmente;
- estado visual Vue/Nuxt;
- countdown visual por segundo;
- modales/confirmaciones;
- layout;
- remapeo físico;
- seguridad pública basada en ocultamiento de campos.

Los frontends consumen las capacidades, deadlines y DTOs decididos por backend.

### 14. Tests

WP-018 debe incluir pruebas deterministas del paquete que cubran al menos:

- REST exitoso con JSON;
- comandos 204;
- errores `{ codigo, mensaje }`;
- validaciones HTTP no estructuradas como error de dominio;
- fallo de red;
- snapshot inicial antes de SSE;
- primer evento SSE completo;
- revisiones duplicadas/anteriores;
- salto de revisiones;
- mutación conceptual entre snapshot y primer evento;
- pérdida del stream -> snapshot -> nuevo stream;
- restart backend con revisión numéricamente menor aceptada como nueva baseline;
- cancelación/disposición durante espera o reconexión;
- ausencia de métodos mutantes en la superficie pública del Recinto;
- drift OpenAPI/backend y OpenAPI/TypeScript.

No deben usarse sleeps reales prolongados para probar backoff/reconexión.

## Consecuencias

- El contrato TypeScript deja de depender de duplicación manual de DTOs.
- Los cambios HTTP del backend requieren regeneración explícita y verificable.
- Los frontends reciben una única implementación de reconexión y errores.
- El Recinto queda limitado estructuralmente a una superficie de solo lectura.
- Un reinicio del backend no deja al cliente atrapado en una revisión antigua mayor.
- Se agrega una dependencia de desarrollo aprobada y ninguna dependencia runtime nueva.

## Alternativas descartadas

### Mantener tipos manuales

Descartado porque duplica OpenAPI y permite drift silencioso.

### Usar un cliente único para Moderación y Recinto

Descartado porque expondría métodos mutantes innecesarios al consumidor público y debilitaría la frontera de responsabilidades.

### Usar librería runtime adicional de fetch/SSE

Descartado para este alcance porque `fetch` y `EventSource` nativos cubren las necesidades aprobadas y una dependencia adicional no aporta suficiente valor frente al coste de contrato/tooling.

### Confiar únicamente en la reconexión automática de EventSource

Descartado porque no garantiza la recuperación por snapshot requerida antes de asumir continuidad.

## Relación con otras decisiones

Esta decisión concreta DT-006, DT-007, DT-018, DT-022 y DEC-013 para el cliente TypeScript compartido.

No modifica el secreto servidor de DEC-013, los contratos HTTP del backend ni la regla de estado autoritativo en FastAPI.

## Aprobación DT-038

La incorporación directa de `openapi-typescript@7.13.0`, la política de artefactos versionados y la separación `ClienteModeracion`/`ClienteRecinto` fueron aprobadas explícitamente por el responsable humano al planificar WP-018.

Cualquier ampliación material de dependencias, transporte, persistencia o responsabilidades requiere nuevo escalamiento conforme DT-038.
