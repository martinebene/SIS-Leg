# DEC-017 - Coordinación mediante SIS-Leg-Control

## Estado

`APROBADA`

## Contexto

SIS-Leg ya utiliza una separación de responsabilidades entre un orquestador de alta capacidad, un implementador local y un revisor independiente. DEC-004, DEC-005 y DEC-007 formalizaron respectivamente la orquestación, la autoridad documental del orquestador y el uso multi-entorno/Orca.

El procedimiento operativo vigente hasta WP-022 todavía exigía que ChatGPT Web redactara prompts extensos y que el operador humano los copiara y pegara manualmente entre la conversación web y las sesiones locales de IMPLEMENTER y REVIEWER. Del mismo modo, los informes de los agentes debían volver al orquestador por transporte manual.

Ese mecanismo preservaba el control humano, pero trasladaba al operador una tarea mecánica y propensa a errores: recordar WP, iteración, PR, SHA, rol siguiente, prompt vigente y resultado que debía transportar.

Para eliminar ese trabajo mecánico sin convertir el flujo en autónomo, se creó el repositorio privado:

`martinebene/SIS-Leg-Control`

Su protocolo, evolucionado a v1.1, implementa un bus de mensajes persistente basado en Git, con estado mutable `CURRENT.json`, asignaciones e informes append-only y una compuerta humana obligatoria entre turnos. La versión 1.1 admite varias asignaciones activas en paralelo.

## Decisión

### 1. Separación entre repositorio de producto y repositorio de control

`martinebene/SIS-Leg` continúa siendo la fuente canónica para:

- producto y código;
- reglas de negocio y arquitectura;
- Work Packages;
- decisiones `DEC-XXX`;
- PLAN;
- ramas y Pull Requests;
- criterios de aceptación;
- pruebas y CI;
- integración y despliegue.

`martinebene/SIS-Leg-Control` se adopta exclusivamente como capa de coordinación operativa para:

- asignaciones del ORCHESTRATOR;
- resultados del IMPLEMENTER;
- resultados del REVIEWER;
- estado/turno operativo actual;
- historial de iteraciones y handoffs;
- trazabilidad de la coordinación entre actores.

El repositorio de control no puede redefinir producto, alcance, contratos, criterios, arquitectura ni reglas canónicas de SIS-Leg.

### 2. Human-in-the-loop obligatorio

GitHub actúa como transporte y persistencia; no como orquestador autónomo.

Cada turno sustantivo requiere intervención humana:

```text
ORCHESTRATOR
  -> publica asignación
  -> HUMAN_GATE inicia manualmente al actor correspondiente
  -> agente ejecuta y publica resultado
  -> HUMAN_GATE informa al ORCHESTRATOR
  -> ORCHESTRATOR verifica y decide el siguiente movimiento
```

Publicar un resultado no puede iniciar automáticamente al siguiente agente.

### Notificación auxiliar al HUMAN_GATE

Se autoriza un canal de alerta event-driven, inicialmente GitHub Actions -> Telegram, cuyo único objetivo es hacer visible que una transición ya existente requiere intervención humana.

Ese canal puede avisar cuando:

- aparece el `expected_response_path` de IMPLEMENTER o REVIEWER, señalando que el turno terminó y corresponde devolver el control al ORCHESTRATOR;
- `CURRENT.json` incorpora un `assignment_id` nuevo, señalando que el ORCHESTRATOR dejó un turno listo para que HUMAN_GATE inicie manualmente al actor autorizado;
- `CURRENT.json` pasa a `state: COMPLETED` con un nuevo `last_completed_work_package`, sin asignaciones activas y con `next_actor: ORCHESTRATOR`, señalando que el WP terminó y corresponde volver al ORCHESTRATOR para limpieza y selección del siguiente WP.

La alerta no forma parte de la autoridad del protocolo, no modifica repositorios, no decide el siguiente movimiento y no dispara agentes. Ante discrepancia, prevalecen `SIS-Leg-Control`, el protocolo vigente y la decisión del ORCHESTRATOR/HUMAN_GATE. Las credenciales del canal se mantienen fuera de ambos repositorios mediante GitHub Actions Secrets.

El operador conserva la autoridad de iniciar el turno, aprobar decisiones reservadas por DT-038 y autorizar las transiciones documentales que DEC-005 reserve a aprobación humana.

La compuerta humana opera **entre turnos**, no entre cada acción del mismo turno. Una vez que HUMAN_GATE inicia un actor cuya asignación es elegible, ese actor queda autorizado a ejecutar autónomamente la tarea completa hasta publicar su resultado.

No se requiere una nueva confirmación humana para commits normales, push, tests, builds, creación/actualización de PR, consultas de CI ni publicación del handoff cuando esas acciones están comprendidas por el rol y la asignación. En REVIEWER, el modo solo lectura prohíbe modificar el candidato de SIS-Leg, pero no prohíbe commitear/pushear el informe de revisión en SIS-Leg-Control.

Solo gates expresos —DT-038, aprobaciones humanas reservadas, contradicciones materiales, operaciones destructivas/no autorizadas, conflicto Git no trivial, merge/deploy/cambios persistentes de infraestructura no autorizados, credenciales faltantes o imposibilidad técnica— interrumpen legítimamente el turno antes del handoff.


### 3. `CURRENT.json` como estado operativo

`SIS-Leg-Control/CURRENT.json` es el estado mutable de coordinación y solo lo modifica el ORCHESTRATOR.

Desde protocolo 1.1 puede contener `active_assignments` con cero, una o varias asignaciones activas. Cada entrada determina WP, iteración, siguiente actor, `assignment_id`, `assignment_path`, `expected_response_path`, agente/arnés/modelo cuando corresponda y PR/SHA si existen.

Cuando `active_assignments` está presente bajo protocolo 1.1, esa colección es la autoridad de elegibilidad. Los campos escalares históricos pueden conservarse como resumen, pero no autorizan trabajo.

El paralelismo solo se habilita para WPs independientes, con worktrees separados y selección inequívoca por rol/arnés. Cada HUMAN_GATE sigue iniciando manualmente cada turno.

La existencia del resultado esperado consume solo esa asignación. Cambios en otras entradas paralelas no invalidan un turno ya iniciado; solo una modificación/eliminación de la entrada propia o la aparición de su respuesta esperada alteran su elegibilidad.

IMPLEMENTER y REVIEWER deben detenerse si no pueden seleccionar exactamente una entrada compatible o si cualquier metadato de su asignación resulta ambiguo.

### 4. Descubrimiento del trabajo desde una sesión local

Todo agente local que participe como IMPLEMENTER o REVIEWER debe, antes de interpretar una instrucción humana breve como `Seguí` o `Revisá`:

1. sincronizar una copia de `martinebene/SIS-Leg-Control` con su `main` remoto;
2. leer `AGENTS.md` del repositorio de control;
3. leer `CURRENT.json`;
4. leer el archivo de rol correspondiente;
5. ejecutar la regla de elegibilidad del protocolo y, en v1.1, seleccionar exactamente una entrada compatible de `active_assignments`;
6. leer exclusivamente la asignación seleccionada;
7. recién entonces cargar el WP y las fuentes canónicas necesarias de `martinebene/SIS-Leg`.

La frase humana breve no contiene por sí misma la tarea. El trabajo autorizado se descubre desde `CURRENT.json` y la asignación indicada.

Si no existe una copia local del repositorio de control, el agente puede clonarla con las credenciales GitHub ya disponibles en el entorno. No se fija una ruta local única; sí se exige que el agente identifique inequívocamente la copia correcta.

### 5. Reemplazo del transporte manual de prompts

Desde la activación de esta decisión, las asignaciones versionadas de `SIS-Leg-Control` reemplazan el copiado/pegado manual de prompts extensos como mecanismo normal de delegación.

`docs/implementation/PROMPTS_AGENTES.md` se conserva como **estándar de calidad y contenido mínimo** para que el ORCHESTRATOR redacte las asignaciones de implementación, corrección, revisión y re-revisión.

Por lo tanto:

- el ORCHESTRATOR sigue siendo responsable de producir instrucciones exhaustivas y explícitas;
- la asignación debe contener los mismos límites, verificaciones, prohibiciones, evidencia y criterios que antes debía contener el prompt manual;
- la asignación no sustituye al WP canónico;
- la documentación canónica de SIS-Leg prevalece ante contradicción;
- el operador ya no necesita transportar el texto completo entre actores.

Quedan superadas por esta decisión las cláusulas operativas anteriores que exigían que el operador copiara y pegara manualmente el prompt exhaustivo después de abrir un agente. WP-030/WP-031 conservan valor como soporte del lanzamiento Orca sin prompt automático, pero el agente ahora obtiene su trabajo desde el repositorio de control.

### 6. Aislamiento entre IMPLEMENTER y REVIEWER

Está prohibida la comunicación lateral directa entre IMPLEMENTER y REVIEWER.

El IMPLEMENTER:

- lee únicamente la asignación `orchestrator-to-implementer` vigente;
- no consume informes `reviewer-to-orchestrator`;
- publica únicamente el resultado exacto esperado para el ORCHESTRATOR.

El REVIEWER:

- lee únicamente la asignación `orchestrator-to-reviewer` vigente;
- no consume informes `implementer-to-orchestrator`;
- reconstruye la revisión desde el WP, fuentes canónicas, PR/diff, SHA exacto, pruebas y CI;
- trabaja en modo solo lectura;
- publica únicamente su informe para el ORCHESTRATOR.

Si una revisión produce hallazgos, el flujo obligatorio es:

```text
REVIEWER
  -> reviewer-to-orchestrator
  -> ORCHESTRATOR decide/filtra
  -> nueva asignación orchestrator-to-implementer
  -> IMPLEMENTER
```

El informe bruto del REVIEWER nunca se convierte automáticamente en una orden para el IMPLEMENTER.

### 7. Iteraciones y mensajes inmutables

Los handoffs se organizan por WP e iteración bajo `SIS-Leg-Control/work-packages/WP-NNN/iteration-XXX/`.

Las asignaciones y resultados publicados son inmutables. Una corrección o nueva revisión se registra como un nuevo mensaje/iteración; no se reescribe historia.

Solo `CURRENT.json` es normalmente mutable.

No existe un máximo artificial de ciclos de corrección/re-revisión.

### 8. Lanzadores y Orca

DEC-007 continúa vigente para seleccionar entorno, launcher, rama/worktree y agentes.

En Orca, `scripts/iniciar_wp_orca.py` continúa creando el worktree y abriendo el agente sin inyectar un prompt de trabajo. La diferencia es que, una vez abierto, el HUMAN_GATE puede usar una instrucción breve (`Seguí` para IMPLEMENTER o `Revisá` para REVIEWER) y el agente debe descubrir su asignación desde `SIS-Leg-Control`.

En entornos genéricos se mantiene `scripts/iniciar_wp.py` conforme DEC-007.

Esta decisión no modifica los scripts ni autoriza cambios ejecutables directos en `main`.

### 9. Integración, CI y cierre

Las puertas de integración continúan perteneciendo a SIS-Leg:

- PR sobre `main`;
- candidato remoto con SHA exacto;
- CI aplicable verde;
- revisión independiente procesada;
- cero hallazgos BLOQUEANTES/IMPORTANTES pendientes;
- squash merge;
- cierre documental y limpieza según DEC-004/DEC-005/DEC-007.

El repositorio de control no puede declarar verde una CI ni sustituir evidencia real de GitHub.

#### Excepción por fallo demostrado del control-plane de GitHub Actions

Una corrida post-merge que no llegue a materializar jobs por una incidencia demostrada de GitHub Actions no obliga a fabricar un commit vacío ni a modificar código para obtener otra ejecución.

El ORCHESTRATOR puede documentar una excepción de plataforma únicamente si se cumplen conjuntamente:

1. la CI del candidato exacto previo al merge terminó verde;
2. la revisión independiente aprobó ese candidato;
3. la PR fue integrada mediante squash normal;
4. el árbol Git (`tree SHA`) del candidato validado y del commit de squash en `main` es exactamente el mismo;
5. existe evidencia verificable de que la corrida post-merge quedó huérfana/inconsistente por infraestructura externa y no por fallo del código;
6. el operador humano autoriza explícitamente documentar la excepción.

La excepción debe quedar registrada con los identificadores de candidato, squash, tree SHA y run afectada.

### 10. Precedencia

Ante contradicción operativa se aplica, de mayor a menor:

1. reglas canónicas de SIS-Leg sobre producto, WP, Git, CI, revisión e integración;
2. decisiones `DEC-XXX` posteriores aplicables, incluida esta DEC-017;
3. protocolo vigente de `SIS-Leg-Control` para transporte, turnos e aislamiento;
4. decisión explícita del ORCHESTRATOR dentro de su autoridad;
5. asignación particular.

Una asignación nunca puede autorizar una violación de las reglas canónicas del producto.

### 11. Seguridad y fallos seguros

- No registrar secretos, tokens ni credenciales en el repositorio de control.
- No usar force-push para publicar handoffs.
- Un push rechazado o divergencia debe detener el turno y volver a verificar elegibilidad.
- IMPLEMENTER y REVIEWER no modifican `CURRENT.json`.
- Un actor invocado fuera de turno no intenta adivinar qué hacer: informa el actor esperado y no modifica nada.

## Activación y migración desde WP-022

WP-022 fue el último WP gestionado íntegramente con el flujo legado.

Su candidato final fue `7000fccbc9896f1b2e39bdb3829bde0f4b0de422`, revisado independientemente y validado por CI #201 / run `32977081279` con 6/6 checks verdes. La PR #29 fue squash-mergeada como `6f9b6f1d5e277e0b07fe737cefb231ea37119b38`.

La corrida post-merge #202 / run `32984587789` quedó huérfana durante una incidencia de GitHub Actions: la API/UI la mantuvo `queued` con cero jobs, mientras los endpoints de cancelación/re-ejecución devolvían estados incompatibles. El candidato y el squash apuntan exactamente al mismo árbol Git `e66721570b5d441b8783a7b8143a8180a6d05d6e`, por lo que el contenido integrado es idéntico al contenido validado por #201.

Con autorización humana explícita se acepta esta excepción de plataforma para cerrar WP-022 sin alterar artificialmente `main`.

Después de integrar esta DEC y las actualizaciones documentales asociadas, `SIS-Leg-Control` puede abandonar `LEGACY_TRANSITION` y pasar a `PLANNING`. El primer WP nativo del protocolo se seleccionará posteriormente desde el `PLAN.md` vigente y no por simple continuidad numérica.

## Relación con decisiones anteriores

### DEC-004

Se mantienen orquestación, revisión independiente secuencial, sincronización Git, puerta de integración y limpieza. Se reemplaza el transporte manual de instrucciones/resultados por el bus de mensajes del repositorio de control.

### DEC-005

Se mantiene la autoridad documental directa del ORCHESTRATOR con aprobación humana y sus límites. `SIS-Leg-Control` no amplía esa autoridad sobre archivos ejecutables.

### DEC-007

Se mantienen selección flexible de agentes, independencia de modelos, Orca y lanzadores. Se sustituye únicamente la entrega manual posterior del prompt por el descubrimiento de la asignación desde `SIS-Leg-Control`.

### WP-030 / WP-031

Sus capacidades de lanzamiento y salida copiable continúan disponibles. La salida copiable deja de ser el transporte normal entre actores porque los resultados se publican estructuradamente en el repositorio de control.

## Consecuencias

- El operador deja de copiar/pegar prompts e informes extensos entre interfaces.
- El control humano entre turnos se conserva.
- Un agente recién abierto puede descubrir de forma determinista qué trabajo le corresponde.
- Se reduce el riesgo de ejecutar el WP, iteración, PR o SHA incorrectos.
- La independencia del revisor queda reforzada por aislamiento explícito de mensajes.
- GitHub conserva un historial auditable de handoffs sin convertirse en un sistema de agentes autónomos.
- SIS-Leg continúa siendo la única fuente normativa del producto.