# 09 - Fuentes y trazabilidad

## 1. Jerarquía de autoridad

Para SIS-Leg:

1. documentación vigente de este repositorio;
2. decisiones explícitas aprobadas incorporadas posteriormente a esta documentación, incluyendo `DEC-XXX` vigentes;
3. código vigente de `martinebene/Botonera/main` únicamente como fallback para aclarar reglas de negocio, experiencia de usuario o diseño/flujo visual que no estén suficientemente definidos en SIS-Leg;
4. documentación histórica y rama `v2` como contexto no normativo.

Una vez que una regla fue resuelta y documentada en SIS-Leg, no debe reabrirse por encontrar un comportamiento distinto en el sistema anterior.

La regla transversal de consulta a producción y estilo de trabajo está definida en `docs/decisions/DEC-001-estilo-codigo-y-referencia-produccion.md`.

## 2. Snapshot histórico principal

Repositorio: `martinebene/Botonera`

Rama de producción de referencia: `main`

Commit usado en el relevamiento inicial:

`537823b4a0045853c74a388058fa3739cf7457a5`

Ese commit conserva valor histórico para trazabilidad, pero cuando un agente deba verificar **cómo funciona actualmente producción** por una ambigüedad funcional/UX/visual, debe consultar el `main` vigente al momento de la tarea y no asumir que el snapshot inicial sigue siendo idéntico.

Rama secundaria analizada como contexto:

`v2`

Snapshot observado:

`9330812aaed93bc79e5043d3d34061c6aa19a7a0`

`v2` no fue validada en producción y no define reglas de SIS-Leg.

## 3. Mapa de fuentes históricas relevantes

### Sesión

- `app/services/sesion_service.py`
- `app/models/sesion.py`

Aportó comportamiento de una sesión en memoria, apertura/cierre, palabra y quórum.

### Votación

- `app/models/votacion.py`
- `app/services/votacion_service.py`
- `app/models/voto.py`

Aportó estados históricos, autocierre, voto único, cierre forzado y desempate.

### Entradas físicas

- `app/services/input_service.py`
- `app/api/routes/entradas.py`
- `devices_services/teclados_fisicos/input_devices_service.py`

Aportó mapa real de teclas y contrato físico actual.

### Moderación

- `app/api/routes/moderacion.py`
- `app/web/static/moderacion/`

Aportó operaciones, interacción del operador y organización visual histórica.

### Pantalla pública

- `app/web/static/pantalla/`

Aportó política histórica de secreto de votos, disposición de bancas y temporizadores visuales.

### Configuración y padrón

- `config.json`
- `app/services/concejal_service.py`
- `data/concejales.csv`

Aportó esquema y valores de la instalación vigente.

### Logging

- `app/utils/logging.py`

Aportó la semántica de tres niveles acumulativos y escritura inmediata.

## 4. Contradicciones históricas ya resueltas

### Mapa de teclas

Documentos antiguos diferían del código. SIS-Leg adopta el código vigente:

- 1 positivo;
- 2 abstención;
- 3 negativo;
- 7 palabra;
- 8 test;
- 9 presencia.

### Orden del Día

La implementación real de producción utiliza CSV separado por coma y el Orden del Día es solo asistencia. SIS-Leg adopta un contrato nuevo explícito definido en DT-039 y no acepta automáticamente el formato histórico.

### Presencia previa a sesión

`main` rechazaba toda interacción sin sesión abierta. SIS-Leg adopta explícitamente `PREPARANDO`, donde presencia y test están habilitados antes de la apertura formal.

### Mayoría simple

La implementación histórica representaba mayoría simple mediante factor especial `0`. SIS-Leg lo reemplaza por tipo explícito `SIMPLE` y lo separa de cualquier factor numérico.

### Presidencia

El sistema anterior resolvía desempate desde Moderación sin modelar plenamente autoridades. SIS-Leg define Presidencia como rol institucional independiente del rol Concejal y registra explícitamente su voto de desempate.

### Logs

La versión histórica escribe `.txt` por día. SIS-Leg conserva los tres niveles acumulativos pero adopta tres CSV por preparación/sesión, nombrados con fecha y hora de inicio.

### Estado ante reinicio

SIS-Leg confirma deliberadamente estado solo en memoria y prohíbe recuperación automática de sesión/preparación.

## 5. Comportamientos históricos descartados como bugs o insuficiencias

No deben copiarse como requisitos:

- permitir abrir otra votación mientras una anterior permanece `EMPATADA`;
- dejar una votación empatada colgante al cerrar sesión;
- posible división por cero al cerrar mayoría especial sin votos;
- serializaciones o IDs internos propios del modelo viejo;
- acoplamiento de estado a singleton/clases concretas como decisión arquitectónica obligatoria;
- exposición de votos al frontend público y ocultamiento solo del lado cliente;
- archivos de log compartidos por todas las sesiones de un mismo día.

Las reglas correctas están en `01-reglas-de-negocio.md`.

## 6. Assets autorizados

Las imágenes históricas de bancas pueden copiarse desde:

`martinebene/Botonera/main/app/web/static/bancas/`

Su reutilización no habilita a copiar la implementación frontend histórica.

## 7. Compatibilidad externa relevante

El bridge físico actual usa conceptualmente:

`POST /entradas/tecla`

con `dispositivo` y `tecla`.

Esta integración sí debe considerarse al diseñar SIS-Leg para evitar una migración física innecesaria, salvo decisión técnica explícita.

## 8. Regla para futuros agentes

No navegar indiscriminadamente el repositorio histórico.

### Cuándo consultar producción

La consulta a `martinebene/Botonera/main` procede cuando existe una duda concreta y no resuelta por SIS-Leg sobre:

- regla de negocio;
- experiencia de usuario;
- comportamiento de un control;
- secuencia de interacción;
- información mostrada al operador o al público;
- disposición funcional o diseño visual de una interfaz.

Procedimiento:

1. identificar primero qué parte no está definida en SIS-Leg;
2. consultar el `main` vigente y solo los archivos necesarios;
3. para conocer comportamiento real, priorizar código ejecutable sobre README, manuales o comentarios históricos cuando difieran;
4. documentar en WP/PR qué se verificó y los archivos consultados si la consulta influyó en la implementación;
5. no sustituir una regla ya definida en SIS-Leg;
6. si producción es ambigua, inconsistente o no contiene la respuesta, escalar en vez de inventar.

### Cuándo NO usar producción como referencia

No utilizar el sistema histórico para decidir por analogía:

- arquitectura;
- estructura interna de clases/módulos;
- dependencias;
- transporte frontend/backend;
- concurrencia;
- persistencia;
- estrategia de pruebas;
- CI;
- despliegue;
- versiones/stack;
- contratos técnicos nuevos.

Ante una duda técnica no definida, aplicar DT-038 y escalar si corresponde.

## 9. Trazabilidad futura

Al comenzar la implementación, cada unidad funcional debe poder relacionarse con:

- regla `RN-*`;
- caso de uso `CU-*`;
- criterio de aceptación correspondiente;
- pruebas automáticas relevantes;
- WP y PR que implementaron el cambio.

Cuando un comportamiento haya requerido consultar producción como fallback, la PR debe añadir esa referencia de trazabilidad.

Las decisiones técnicas que se adopten antes o durante la programación deberán registrarse en la documentación correspondiente y dejar de tratarse como preguntas abiertas una vez aprobadas.
