# DEC-018 - Coordinador local secuencial en Orca y gestión de cuotas

## Estado

`APROBADA`

## Contexto

SIS-Leg admite lotes de Work Packages independientes que conceptualmente pueden ejecutarse en paralelo mediante worktrees separados y `CURRENT.json.active_assignments`. En el VPS de desarrollo, sin embargo, ejecutar simultáneamente varios agentes de programación puede exceder la capacidad práctica de CPU, RAM o swap.

El operador quiere conservar la ventaja de preparar varios worktrees y asignaciones de una sola vez, pero ejecutar los agentes pesados de forma estrictamente secuencial. También quiere reducir intervenciones manuales repetitivas sin delegar al entorno local decisiones propias del ORCHESTRATOR ni eliminar las puertas de revisión e integración.

El entorno ya dispone de dos capacidades útiles:

1. Orca ofrece coordinación supervisada mediante Runs, Tasks, Dispatches, `worker_done`, `escalation`, `question`, `check --wait`, reutilización/liberación de workers y reintentos controlados.
2. El VPS dispone de `cuotas-agentes --json`, que expone de forma estructurada ventanas de uso, porcentaje libre/usado y tiempo de reinicio para AGY/Antigravity, OpenCode Go, Codex y Claude Code.

Esta decisión complementa DEC-007 y reemplaza parcialmente la exigencia de DEC-017 de una intervención HUMAN_GATE separada para cada sesión local cuando varias asignaciones del mismo tramo ya fueron autorizadas por el ORCHESTRATOR.

## Decisión

### 1. Nuevo rol operativo: COORDINADOR_LOCAL

Se autoriza un rol local llamado `COORDINADOR_LOCAL`.

No es un segundo ORCHESTRATOR. No decide producto, alcance, revisión, integración ni cierre.

Su única responsabilidad es ejecutar mecánicamente un lote finito de asignaciones **ya autorizadas** por el ORCHESTRATOR, respetando dependencias, cuotas y una concurrencia máxima indicada.

El COORDINADOR_LOCAL puede:

- identificar worktrees/terminales Orca ya creados;
- crear un Run/Tasks/Dispatches de Orca para supervisión;
- iniciar o reactivar el agente exacto asignado a cada WP;
- esperar `worker_done`, `escalation` o `question`;
- ejecutar como máximo la cantidad de workers simultáneos autorizada;
- reutilizar o liberar terminales de agente sin borrar el worktree;
- consultar telemetría de cuotas cuando sea apropiada y no genere presión innecesaria sobre el proveedor;
- para Claude Code, abrir/reanudar primero la propia sesión y usar su auto-verificación de disponibilidad como autoridad operativa;
- demorar una asignación sólo ante falta de cuota confirmada por la fuente apropiada;
- elegir otro WP ya autorizado y listo del mismo lote mientras espera una cuota, salvo que el ORCHESTRATOR haya fijado orden estricto;
- reanudar el mismo agente después del reinicio de su ventana;
- si el proceso terminó, iniciar un reemplazo controlado en el **mismo worktree**, conservando el trabajo parcial y la asignación vigente.

### 2. Autoridad que nunca recibe

El COORDINADOR_LOCAL no puede:

- crear, aprobar o redefinir WPs;
- modificar PLAN por decisión propia;
- escribir `CURRENT.json`;
- cambiar implementador o revisor asignado;
- sustituir un modelo por otro sin autorización previa;
- interpretar un handoff como aprobación;
- habilitar REVIEWER después de IMPLEMENTER;
- convertir hallazgos del REVIEWER en trabajo de corrección;
- cruzar una puerta ORCHESTRATOR;
- mergear PRs;
- hacer deploy;
- limpiar ramas/worktrees;
- resolver decisiones DT-038;
- usar force-push, rebase o acciones destructivas.

Cuando termina un lote, vuelve el control al HUMAN_GATE/ORCHESTRATOR.

### 3. HUMAN_GATE por lote

Por defecto sigue siendo válido iniciar cada sesión manualmente.

Como excepción controlada, el HUMAN_GATE puede dar **una única orden** al COORDINADOR_LOCAL para ejecutar secuencialmente un lote de asignaciones que el ORCHESTRATOR ya dejó autorizadas.

Ejemplos válidos:

- cuatro IMPLEMENTER de WPs independientes ya autorizados;
- cuatro REVIEWER ya autorizados sobre candidatos exactos;
- una tanda de re-revisiones ya autorizadas.

Una autorización de lote **no permite atravesar una fase que todavía depende del ORCHESTRATOR**. Por ejemplo, un lote de implementaciones termina al completar sus handoffs; el COORDINADOR_LOCAL no puede iniciar revisiones hasta que el ORCHESTRATOR verifique GitHub, congele candidatos y publique las asignaciones REVIEWER.

### 4. Concurrencia física separada del paralelismo lógico

`active_assignments` puede expresar paralelismo lógico aunque el entorno ejecute físicamente una sola tarea a la vez.

Para el VPS/contenedor actual, el ORCHESTRATOR usa por defecto:

`max_concurrency = 1`

Con el presupuesto de RAM vigente esta concurrencia es **obligatoria** cuando cualquiera de los WPs del lote requiere pruebas de interfaz con navegador —por ejemplo Playwright, Chromium, navegador real o equivalente— durante implementación o revisión.

Esto significa:

1. un solo worker de WP activo;
2. si ese worker puede lanzar o mantener un navegador de pruebas, no se despacha ningún segundo worker hasta que termine y libere esos procesos;
3. al recibir finalización válida, el coordinador libera o deja inactivo ese worker según corresponda;
4. recién entonces inicia el siguiente;
5. los worktrees y `active_assignments` restantes pueden permanecer preparados: el paralelismo sigue siendo lógico, no físico.

El COORDINADOR_LOCAL puede permanecer como proceso supervisor, pero no ejecuta pruebas de navegador ni inicia otro worker mientras el anterior siga activo. Debe usar un agente/modelo de bajo impacto relativo y una cuota independiente de las cuotas que deba supervisar.

Una concurrencia física mayor que 1 no se presume. Si en el futuro cambia la configuración de RAM/recursos del contenedor, debe reevaluarse explícitamente y autorizarse para el lote correspondiente.

### 5. Independencia de cuota del coordinador

No alcanza con usar un nombre de modelo distinto.

El COORDINADOR_LOCAL debe operar, cuando sea razonablemente posible, sobre una **fuente de cuota independiente** de los workers que debe supervisar.

Ejemplo válido:

- COORDINADOR_LOCAL: OpenCode usando OpenCode Go u OpenRouter;
- IMPLEMENTER: Claude Code y/o Codex;
- REVIEWER: AGY/Antigravity.

Si un worker del mismo lote también consume la misma ventana efectiva de OpenCode Go usada por el coordinador, esa combinación deja de ser robusta frente al agotamiento de cuota y debe evitarse o declararse expresamente.

### 6. Gestión de ventanas y rate limits

Las fuentes externas de cuota son **auxiliares**. No todas pueden consultarse con seguridad como gate previo: un mismo proveedor puede estar siendo consultado simultáneamente por Orca, dashboards u otros procesos del VPS y responder `HTTP 429` al endpoint de uso aunque la sesión del agente conserve capacidad efectiva para trabajar.

#### Claude Code: auto-verificación obligatoria en la propia sesión

Para **Claude Code**, `cuotas-agentes --json` no es autoridad para bloquear el inicio y no debe consultarse como preflight obligatorio del worker.

El flujo canónico es:

1. el COORDINADOR_LOCAL crea/abre el worker Claude exacto ya autorizado;
2. antes de editar, Claude verifica **desde su propia sesión** si puede continuar con la asignación;
3. si la sesión dispone de cuota/capacidad, Claude continúa normalmente hasta su handoff;
4. si Claude recibe o muestra un límite explícito de uso/rate limit que impide continuar, no modifica producto por ese intento y devuelve el control al COORDINADOR_LOCAL con estado `quota_unavailable` y, si lo conoce, el momento de reset;
5. recién con esa evidencia propia del agente el COORDINADOR_LOCAL decide mecánicamente si espera, ejecuta otro WP independiente y elegible del lote o detiene el lote según su manifiesto;
6. para reanudar Claude, se vuelve a abrir/reanudar la propia sesión y se repite la auto-verificación. Un `HTTP 429` obtenido únicamente al consultar un monitor externo de cuota nunca prueba por sí solo que Claude no pueda trabajar.

La auto-verificación no requiere predecir consumo futuro: basta con confirmar que la sesión puede operar y no está bloqueada por el límite de uso.

#### Otros agentes y fuentes auxiliares

`cuotas-agentes --json` puede seguir utilizándose como señal operativa para agentes/proveedores donde la consulta sea estable, para planificación aproximada o para conocer resets. Un error del monitor externo se registra como **telemetría no disponible**, no como cuota agotada, salvo que el propio worker/proveedor confirme el bloqueo.

Cuando exista evidencia real de cuota agotada:

1. el worker devuelve control al COORDINADOR_LOCAL;
2. el coordinador registra la causa;
3. si existe otro WP listo e independiente del lote, puede ejecutarlo;
4. de lo contrario puede esperar al reset conocido o detener el lote conforme al manifiesto;
5. antes de reanudar, debe obtener evidencia nueva desde la fuente apropiada; para Claude, la fuente apropiada es la propia sesión Claude.

### 7. Agotamiento durante una tarea

El coordinador no considera un timeout de espera, TUI idle o ausencia temporal de mensajes como prueba de agotamiento.

Para clasificar un bloqueo por cuota debe existir evidencia, por ejemplo:

- mensaje explícito de rate limit/usage limit en el agente;
- estado estructurado de cuota agotada;
- combinación coherente de ambos.

Si un worker queda detenido por cuota:

1. conserva worktree, rama y archivos;
2. no marca el WP como completado;
3. espera el reset de la ventana;
4. revalida cuota;
5. si la sesión sigue viva, reanuda **esa misma sesión**;
6. si el proceso terminó o Orca lo prueba como failed/stopped, crea un reemplazo controlado en el mismo worktree, vinculándolo como reintento cuando Orca lo soporte;
7. el reemplazo debe inspeccionar el estado existente antes de editar y continuar la misma asignación;
8. nunca se crean dos workers activos simultáneos sobre el mismo WP.

### 8. Uso de Orca orchestration

Cuando el COORDINADOR_LOCAL supervise la tanda, debe preferir la capa estructurada de Orca:

- Run para el lote;
- Task por asignación;
- Dispatch/worker-start sobre la terminal del worktree correspondiente;
- `check --wait` para `worker_done`, `escalation` y `question`;
- `worker-release` al terminar cuando no se reutilice inmediatamente;
- `worker-start --retry-of` o mecanismo equivalente sólo ante estado failed/stopped comprobado.

No debe usar polling agresivo ni interpretar un mero cambio visual como finalización.

### 8 bis. Lanzamiento de workers con permisos completos y coordinador mecánico

El COORDINADOR_LOCAL es un **planificador/dispatcher mecánico**. Su inferencia no debe gastarse resolviendo prompts ordinarios de permisos de los workers.

Toda asignación que HUMAN_GATE/ORCHESTRATOR ya autorizó debe iniciarse con el perfil de permisos completos aprobado para ese harness. Los permisos de herramienta **no amplían el alcance de la asignación** ni modifican las prohibiciones de Git, revisión, merge, deploy, secretos o acciones destructivas.

Reglas:

1. el coordinador debe lanzar cada IMPLEMENTER/REVIEWER con el modo de permisos completos aprobado, no con el modo interactivo/restringido por defecto de Orca si éste genera prompts de autorización rutinarios;
2. perfiles actualmente aprobados:
   - Claude Code: `claude --dangerously-skip-permissions`;
   - Antigravity/AGY: `agy --dangerously-skip-permissions`;
3. para cualquier harness adicional, el manifiesto del lote debe fijar previamente la invocación equivalente de permisos completos; no se adivinan flags ni se sustituye silenciosamente por un modo restringido;
4. Orca puede seguir administrando worktrees, terminales, Runs y workers; si el lanzamiento automático `--agent` no permite expresar el perfil completo, el coordinador debe usar el mecanismo soportado por Orca para iniciar en ese worktree la invocación explícita aprobada;
5. un prompt de permiso rutinario provocado por haber lanzado el worker en modo restringido es **un error de configuración del launcher**, no una decisión que deba razonar el COORDINADOR_LOCAL;
6. ante ese error, el coordinador no responde aprobación por aprobación: verifica que no quede un worker duplicado, preserva el mismo worktree/estado y relanza o reanuda el worker con el perfil completo;
7. una vez lanzado correctamente, el worker ejecuta autónomamente toda su asignación hasta `worker_done`, handoff, `quota_unavailable` o una escalación real;
8. el COORDINADOR_LOCAL se limita a ordenar secuencialidad/paralelismo según `max_concurrency`, vigilar vida/liberación de workers, gestionar handbacks de cuota y comprobar gates objetivos ya definidos;
9. el coordinador no interpreta si una acción rutinaria "merece permiso": esa autorización ya viene dada por HUMAN_GATE y la asignación;
10. si un worker intenta una acción **fuera del alcance** o una operación que la gobernanza reserva (force/rebase destructivo, merge/deploy no autorizado, secreto/credencial, decisión DT-038, etc.), los permisos completos no la vuelven válida: eso sí es una escalación real.

Para REVIEWER, permisos completos de CLI no eliminan el modo de solo lectura sobre SIS-Leg: siguen prohibidas las modificaciones del producto y sólo puede escribir el handoff autorizado en SIS-Leg-Control.

### 8 ter. Principio de completar el lote y clasificación de desvíos

El objetivo normal del COORDINADOR_LOCAL es **terminar todo el lote autorizado** y devolver al ORCHESTRATOR la mayor cantidad posible de trabajo implementado y revisado. No debe detenerse por prudencia excesiva ante desvíos de bajo riesgo que quedaron aislados en el worktree y todavía no fueron integrados.

#### Desvío blando: registrar y continuar

Un desvío se considera **blando** cuando, de forma objetiva:

- está contenido en la rama/worktree del WP;
- no toca secretos, infraestructura persistente, deploy ni recursos compartidos externos;
- no requiere force/rebase destructivo;
- no contamina otro WP/worktree;
- no altera una decisión DT-038 ni exige una nueva decisión humana de producto para poder revisar;
- existe candidato remoto identificable y CI/gates objetivos pueden ejecutarse;
- el cambio adicional es razonablemente revisable junto con el candidato.

Ejemplos: archivo documental adicional, test adicional, refactor auxiliar pequeño o ajuste adyacente que el IMPLEMENTER declara expresamente.

Ante un desvío blando, el COORDINADOR_LOCAL:

1. lo registra sin aprobarlo ni interpretarlo como correcto;
2. **no detiene el lote**;
3. si los gates objetivos IMPLEMENTER -> REVIEWER pasan, inicia la revisión independiente incluyendo el desvío en el candidato exacto;
4. continúa con los demás WPs independientes autorizados;
5. deja al ORCHESTRATOR la decisión posterior de integrar, pedir corrección o descartar el candidato.

El hecho de que algo esté en revisión **no implica aceptación del alcance**. La protección principal sigue siendo que ningún candidato llega a `main` sin decisión posterior del ORCHESTRATOR.

#### Desvío duro: detener sólo lo necesario

Sí exige detener el WP —y el lote completo sólo si el riesgo es compartido— cualquiera de estas condiciones:

- secreto/credencial o riesgo de exposición;
- operación destructiva, force/rebase no autorizado;
- merge/deploy o infraestructura persistente no autorizada;
- contaminación de otro worktree/WP o recurso compartido;
- decisión DT-038/contradicción material que impide saber qué revisar;
- pérdida de identidad del candidato, worktree sucio no explicable o imposibilidad de fijar SHA/tree;
- riesgo sistémico que pueda afectar a los demás workers del lote.

Si el problema duro afecta sólo a un WP y los otros son materialmente independientes, el coordinador marca ese WP como detenido y **continúa los demás**.

### 9. Condiciones de detención

El lote se detiene y devuelve control humano si aparece:

- DT-038 o decisión reservada;
- contradicción de asignación;
- pérdida de elegibilidad;
- conflicto Git no trivial;
- operación destructiva necesaria;
- secreto/credencial faltante;
- `escalation` que requiera decisión;
- resultado esperado inconsistente;
- imposibilidad de determinar de forma segura si un worker está vivo o duplicado.

Una falta de cuota con reset conocido **no es por sí sola una escalación**: es una condición de espera/reanudación.

### 10. Prompt obligatorio por lote

Cada vez que el ORCHESTRATOR habilite un lote lógicamente paralelo que vaya a secuencializarse localmente, debe entregar al operador un prompt específico para el COORDINADOR_LOCAL.

Ese prompt debe identificar:

- WPs del lote;
- fase: IMPLEMENTER, REVIEWER o re-revisión;
- worktrees/terminales esperados;
- agente/modelo autorizado por WP;
- concurrencia máxima;
- orden fijo o libertad de reordenar por cuota;
- proveedor de cuota de cada agente;
- política de espera/reanudación;
- stop conditions;
- prohibición expresa de cruzar al siguiente gate del ORCHESTRATOR.

### 10 bis. La continuación humana se interpreta por intención, no por una palabra reservada

Cuando un lote requiera que HUMAN_GATE confirme primero una condición visible —por ejemplo el modelo Luna seleccionado en la TUI del coordinador—, esa confirmación y la orden posterior de continuar son dos hechos distintos.

La orden de continuación **no es un token de protocolo** y no debe exigir literalmente `Seguí`.

Una vez satisfecha la condición previa, COORDINADOR_LOCAL debe aceptar cualquier instrucción humana inequívoca cuyo sentido sea continuar, iniciar, reanudar o proseguir el trabajo ya autorizado. Son ejemplos válidos, sin carácter exhaustivo:

- `Seguí`;
- `Continuá`;
- `Dale`;
- `Procedé`;
- `Retomá el lote`;
- `Seguí con el trabajo`;
- cualquier formulación equivalente que, por contexto, exprese claramente la voluntad de avanzar.

El coordinador interpreta **intención semántica**, no coincidencia textual.

No debe iniciar el lote cuando:

- la condición previa requerida todavía no fue confirmada;
- el mensaje humano es una consulta de estado;
- el mensaje es ambiguo respecto de continuar;
- el humano ordena expresamente esperar, detenerse o cambiar el plan.

Ante ambigüedad real puede pedir aclaración breve. No debe pedir al humano que repita una palabra exacta si la intención de continuar ya es clara.

### 11. Transición mecánica preautorizada dentro de un lote nocturno

Por autorización HUMAN_GATE explícita y acotada, el ORCHESTRATOR puede preparar un lote en el que el COORDINADOR_LOCAL atraviese **una transición mecánica ya decidida** sin esperar una nueva intervención humana, siempre que todos estos elementos hayan sido fijados antes de iniciar el lote:

- WP y fase exacta;
- siguiente rol ya aprobado;
- harness/modelo exacto del siguiente rol;
- criterios de elegibilidad;
- plantilla de asignación;
- condición objetiva de paso;
- condición de detención.

Esta excepción existe para aprovechar ventanas nocturnas o ausencias prolongadas del operador y no convierte al COORDINADOR_LOCAL en ORCHESTRATOR general.

La condición objetiva normal para pasar de una sincronización/implementación ya autorizada a una revisión ya autorizada es:

1. existe el handoff esperado del IMPLEMENTER;
2. la PR exacta sigue abierta contra `main`;
3. el HEAD remoto coincide con el candidate SHA informado;
4. el candidato contiene el `main` requerido mediante merge normal cuando correspondía;
5. el worktree quedó limpio;
6. la CI del SHA exacto terminó `success`;
7. no hubo `escalation`, conflicto no trivial, decisión DT-038 ni desviación material;
8. el revisor y modelo fueron fijados por HUMAN_GATE antes de iniciar el lote.

Sólo en ese caso el COORDINADOR_LOCAL puede, si el lote lo autoriza expresamente:

- reconstruir la asignación REVIEWER desde la plantilla preaprobada;
- fijar en ella PR/base/candidate/tree SHA y CI exactos;
- publicarla en SIS-Leg-Control;
- actualizar exclusivamente los campos operativos de `CURRENT.json` necesarios para volver elegible a ese REVIEWER;
- iniciar el REVIEWER y esperar su handoff.

No puede evaluar el contenido del review, convertir hallazgos en correcciones, habilitar re-revisión ni mergear. Esas decisiones vuelven al ORCHESTRATOR/HUMAN_GATE.

La transición mecánica preautorizada debe aparecer además en un manifiesto de lote append-only en SIS-Leg-Control. Si falta el manifiesto, los datos no coinciden o la condición objetiva no se cumple, el coordinador se detiene.

### 12. Sincronización Git mecánica delegada

Un manifiesto nocturno puede autorizar además al COORDINADOR_LOCAL a realizar personalmente una sincronización Git **puramente mecánica** sobre una rama WP ya existente, sin convertirse en implementador funcional.

Sólo está permitido cuando:

- el worktree está limpio al comenzar;
- la PR/rama ya existe;
- el único objetivo es incorporar `origin/main` vigente mediante merge normal;
- el merge es limpio, sin conflictos;
- no se editan archivos manualmente;
- no se reescribe historia;
- se ejecutan los gates fijados por el manifiesto;
- se hace push normal y se exige CI verde del nuevo SHA.

El commit de merge puede ser creado por el COORDINADOR_LOCAL porque no contiene una decisión de producto ni una corrección funcional: sólo materializa una sincronización ya ordenada.

Si Git presenta conflictos, si el árbol estaba sucio, si el merge exige editar contenido o si aparece cualquier duda sobre qué lado preservar, esta autorización caduca para ese WP: el coordinador no resuelve el conflicto y debe detener esa rama o devolverla al IMPLEMENTER autorizado.

El manifiesto debe identificar expresamente en qué WPs está habilitada esta excepción. No se presume para todo lote.


## Consecuencias

- Los prompts rutinarios de permisos dejan de consumir inferencia del coordinador: los workers se lanzan con permisos completos desde el inicio.
- El COORDINADOR_LOCAL queda deliberadamente reducido a scheduling, lifecycle y gates objetivos; no actúa como aprobador interactivo de herramientas.

- Se mantiene el aislamiento por worktree.
- Se reduce la intervención humana repetitiva.
- La limitación física del VPS deja de impedir preparar lotes lógicamente paralelos.
- El ORCHESTRATOR conserva todas las decisiones sustantivas.
- Los workers pueden esperar resets de cuota durante horas sin perder el trabajo parcial.
- La selección del coordinador se evalúa por **independencia de cuota**, no sólo por nombre de modelo.
- `cuotas-agentes --json` sigue siendo una fuente auxiliar de planificación, pero un error/429 de ese monitor no equivale a agotamiento del agente. Para Claude Code, la autoridad operativa de disponibilidad es la propia sesión Claude.
