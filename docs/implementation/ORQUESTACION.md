# Orquestación operativa de la implementación

Este documento describe el procedimiento práctico de coordinación de SIS-Leg. Deriva de `DEC-004`, `DEC-005`, `DEC-007` y `DEC-017` y no reemplaza `AGENTS.md`, los Work Packages ni las decisiones canónicas.

## Principio general

La coordinación y planificación documental se realizan preferentemente desde una conversación de ChatGPT Web con acceso independiente a GitHub.

Existen dos repositorios con responsabilidades distintas:

- `martinebene/SIS-Leg`: producto, documentación canónica, WPs, decisiones, código, PR, CI e integración;
- `martinebene/SIS-Leg-Control`: asignaciones, resultados, iteraciones y estado operativo de turnos.

GitHub se utiliza como transporte y persistencia. No existe encadenamiento autónomo que atraviese decisiones del ORCHESTRATOR. Conforme a DEC-018, el operador puede delegar a un **COORDINADOR_LOCAL** la secuencialización mecánica de un lote finito de asignaciones ya autorizadas, sin habilitarlo a cruzar puertas de implementación/revisión/integración.

## Actores

### ORCHESTRATOR

El ORCHESTRATOR:

- reconstruye el estado real desde GitHub;
- planifica los WPs con el operador;
- escala decisiones DT-038;
- mantiene documentación canónica dentro de la autoridad de DEC-005;
- selecciona/proponer implementador y revisor conforme DEC-007;
- crea las asignaciones en `SIS-Leg-Control`;
- es el único actor que modifica `CURRENT.json`;
- procesa los resultados de IMPLEMENTER y REVIEWER;
- decide correcciones, re-revisiones, integración, bloqueo y cierre.

### IMPLEMENTER

El IMPLEMENTER ejecuta únicamente la asignación vigente dirigida a su rol. Trabaja sobre la rama/worktree del WP y publica su resultado exclusivamente para el ORCHESTRATOR.

### REVIEWER

El REVIEWER ejecuta únicamente la asignación vigente dirigida a su rol, revisa el SHA exacto indicado en modo solo lectura y publica su informe exclusivamente para el ORCHESTRATOR.

### HUMAN_GATE

El operador humano conserva la compuerta entre decisiones sustantivas. Puede iniciar manualmente cada turno o, conforme a DEC-018, emitir una única autorización de lote a un COORDINADOR_LOCAL para ejecutar secuencialmente varias asignaciones ya autorizadas del mismo tramo. No necesita transportar WP, iteración, PR, SHA ni prompt completo entre actores.

### COORDINADOR_LOCAL

El COORDINADOR_LOCAL es un ejecutor mecánico de lotes bajo Orca, no un ORCHESTRATOR alternativo. Puede supervisar Runs/Tasks/Dispatches, limitar concurrencia física, consultar `cuotas-agentes --json`, esperar resets y reanudar workers. No puede modificar `CURRENT.json`, cambiar asignaciones, habilitar revisiones, interpretar hallazgos, mergear, desplegar ni limpiar worktrees. Su contrato completo está en DEC-018.

Las frases breves como `Seguí`, `Continuá`, `Dale`, `Procedé`, `Revisá` o `Terminó el agente` son **ejemplos de intención**, no palabras reservadas del protocolo.

Una sesión debe interpretar la intención humana dentro del contexto vigente. Si HUMAN_GATE ya verificó una condición previa requerida —por ejemplo el modelo del COORDINADOR_LOCAL—, cualquier instrucción inequívoca de continuar/reanudar/iniciar el trabajo autorizado habilita la ejecución. No se exige repetir literalmente `Seguí`.

Estas frases **no contienen el trabajo**. El actor descubre la tarea desde `SIS-Leg-Control`.

## Fuente de autoridad y precedencia

Para producto, alcance, contratos, criterios, Git, CI e integración manda SIS-Leg.

Para turno y transporte operativo manda el protocolo vigente de `SIS-Leg-Control`, subordinado a la documentación canónica.

En caso de contradicción:

1. reglas canónicas de SIS-Leg;
2. decisiones `DEC-XXX` posteriores aplicables;
3. protocolo de `SIS-Leg-Control`;
4. decisión del ORCHESTRATOR dentro de su autoridad;
5. asignación particular.

## Fuentes mínimas de una conversación nueva de orquestación

Leer o verificar:

1. `AGENTS.md`;
2. `docs/decisions/DEC-004-orquestacion-revision-secuencial-y-sincronizacion.md`;
3. `docs/decisions/DEC-005-planificacion-y-autoridad-documental-del-orquestador.md`;
4. `docs/decisions/DEC-007-entorno-orca-asignacion-agentes-y-lanzadores.md`;
5. `docs/decisions/DEC-017-coordinacion-mediante-sis-leg-control.md`;
6. `docs/implementation/ORQUESTACION.md`;
7. `docs/implementation/PROMPTS_AGENTES.md` como estándar de contenido de delegación;
8. `docs/implementation/PLAN.md`;
9. `SIS-Leg-Control/PROTOCOL.md` y `SIS-Leg-Control/CURRENT.json`;
10. PR abiertas o recientemente integradas relevantes;
11. el `WP-XXX.md` concreto cuando corresponda.

No depender de memoria de conversaciones anteriores cuando GitHub puede reconstruir el estado.

## Planificación documental de un WP

Antes de iniciar implementación, el ORCHESTRATOR:

1. identifica el próximo WP permitido por `PLAN.md` y sus dependencias;
2. verifica dependencias `INTEGRADO`;
3. carga las fuentes canónicas propietarias del alcance;
4. inspecciona solo el código integrado necesario;
5. detecta ambigüedades y decisiones reservadas por DT-038;
6. consulta al operador únicamente las decisiones humanas necesarias;
7. redacta o actualiza `docs/work-packages/WP-XXX.md` siguiendo el formato vigente;
8. mantiene `BORRADOR` mientras haya decisiones pendientes;
9. registra `APROBADO` tras aprobación humana explícita;
10. actualiza documentación canónica en `main` conforme DEC-005;
11. verifica el SHA y la CI aplicable;
12. consulta disponibilidad/cuota de agentes/modelos cuando sea necesario;
13. propone y acuerda implementador + revisor independiente conforme DEC-007;
14. cambia PLAN a `EN_CURSO` con el implementador autorizado;
15. prepara la primera asignación en `SIS-Leg-Control`.

Al redactar o aprobar el WP, el ORCHESTRATOR verifica además que la sección obligatoria
`## Impacto en el manual de usuario y soporte` exista y esté resuelta con una de las dos
declaraciones previstas por `docs/work-packages/TEMPLATE.md`. Un WP que no declare ese impacto
no está listo para pasar a `APROBADO`.

Los agentes locales reciben un WP ya cerrado. No redefinen alcance ni decisiones reservadas.

## Calidad de las asignaciones

`docs/implementation/PROMPTS_AGENTES.md` continúa vigente como estándar de calidad y contenido, aunque deja de ser el mecanismo normal de transporte manual.

Toda asignación debe ser explícita respecto de:

- rol y objetivo;
- WP y fuentes canónicas;
- alcance y exclusiones;
- decisiones/prohibiciones relevantes;
- branch/worktree/PR/SHA cuando correspondan;
- sincronización Git;
- tests y gates requeridos;
- escalamiento;
- evidencia final;
- ruta exacta del resultado a publicar.

La asignación no reemplaza al WP. La redundancia deliberada sigue siendo una salvaguarda para agentes con capacidades distintas.

## Preparación de un turno en SIS-Leg-Control

El ORCHESTRATOR crea un mensaje append-only bajo:

```text
work-packages/WP-NNN/iteration-XXX/
```

Archivos normales:

```text
01-orchestrator-to-implementer.md
02-implementer-to-orchestrator.md
03-orchestrator-to-reviewer.md
04-reviewer-to-orchestrator.md
```

Luego actualiza `CURRENT.json` con:

- WP;
- iteración;
- estado;
- `next_actor`;
- `assignment_id`;
- `assignment_path`;
- `expected_response_path`;
- PR/SHA cuando corresponda.

Los mensajes publicados no se reescriben. Una corrección o re-revisión genera una nueva iteración/mensaje.

## Elegibilidad obligatoria del agente local

Antes de actuar, IMPLEMENTER o REVIEWER debe:

1. determinar el worktree Git actual y la rama activa;
2. resolver de forma inequívoca el `WP-NNN` correspondiente a ese worktree/rama;
3. sincronizar `martinebene/SIS-Leg-Control` con `main` remoto;
4. leer su `AGENTS.md`;
5. leer `CURRENT.json`;
6. cuando `protocol_version >= 1.2` y exista `active_assignments`, filtrar primero por el WP del worktree actual;
7. dentro de ese WP, confirmar que `next_actor` coincide con su rol y que harness/modelo coinciden cuando estén fijados;
8. exigir exactamente una asignación compatible dentro del WP actual;
9. verificar `assignment_id`, WP, iteración y destinatario;
10. comprobar que `expected_response_path` todavía no exista;
11. leer únicamente la asignación dirigida a su rol;
12. recién entonces cargar el contexto canónico de SIS-Leg.

Asignaciones del mismo harness/modelo en otros WPs paralelos no generan ambigüedad porque pertenecen a otros worktrees. Si no puede resolver el WP local o quedan cero/múltiples asignaciones para ese mismo WP, el agente se detiene sin modificar nada.

La existencia del resultado esperado significa que ese turno terminó, incluso si `CURRENT.json` todavía conserva el estado anterior hasta que el humano vuelva al ORCHESTRATOR.

## Aislamiento entre roles

No existe canal lateral IMPLEMENTER -> REVIEWER ni REVIEWER -> IMPLEMENTER.

El IMPLEMENTER no debe leer informes `reviewer-to-orchestrator`.

El REVIEWER no debe leer informes `implementer-to-orchestrator`.

Los hallazgos del REVIEWER llegan al ORCHESTRATOR, quien decide cuáles acepta, reformula, descarta o escala. Solo una nueva asignación del ORCHESTRATOR puede convertirlos en trabajo autorizado para el IMPLEMENTER.

## Cambios documentales directos desde ChatGPT Web

Con aprobación humana explícita, DEC-005 permite al ORCHESTRATOR modificar directamente en `main` documentación autorizada como:

- `AGENTS.md`;
- README exclusivamente documental;
- `docs/**/*.md`, incluidos PLAN, ORQUESTACION, WPs y DECs.

Antes de escribir debe:

1. verificar HEAD actual de `main`;
2. confirmar que el cambio es exclusivamente documental y está autorizado;
3. no introducir decisiones DT-038 no aprobadas;
4. realizar la escritura y registrar SHA;
5. volver a verificar HEAD remoto;
6. verificar la CI aplicable;
7. no habilitar trabajo dependiente si la CI falla;
8. exigir sincronización local antes de continuar.

Esta excepción no alcanza a código, tests ejecutables, scripts, workflows/CI, configuración funcional, dependencias, lockfiles, tooling ejecutable, assets ni despliegue.

## Inicio local de un WP

Antes del lanzamiento:

- WP `APROBADO`;
- dependencias `INTEGRADO`;
- PLAN `EN_CURSO` con un implementador;
- implementador/revisor acordados;
- asignación IMPLEMENTER publicada en `SIS-Leg-Control`;
- `CURRENT.json` apuntando a esa asignación.

El checkout coordinador se sincroniza:

```bash
cd /workspace/SIS-Leg
git switch main
git status --short
git fetch --prune origin
git pull --ff-only origin main
```

`git status --short` debe estar vacío y `HEAD` debe coincidir con `origin/main`.

### Orca

Cuando Orca es el entorno vigente:

```bash
uv run python scripts/iniciar_wp_orca.py NNN agente
```

El lanzador crea el worktree/rama nativa y abre el agente **sin inyectar el trabajo**.

Una vez abierto, el operador puede decir `Seguí`. El agente debe entonces sincronizar `SIS-Leg-Control`, descubrir la asignación y verificar su elegibilidad antes de modificar el WP.

No se copia/pega normalmente un prompt exhaustivo desde ChatGPT Web.

### Entorno genérico

Se conserva:

```bash
uv run python scripts/iniciar_wp.py NNN agente
```

El agente sigue la misma regla de descubrimiento desde `SIS-Leg-Control`.

## Paralelismo de WPs

Cuando el PLAN permite WPs independientes, protocolo 1.2 de SIS-Leg-Control permite publicarlos simultáneamente mediante `CURRENT.json.active_assignments`.

Cada entrada activa debe identificar WP, iteración, rol, `assignment_id`, `assignment_path`, `expected_response_path` y agente/arnés/modelo cuando corresponda. Los worktrees deben ser distintos y no puede existir superposición sustantiva no coordinada.

El mismo harness/modelo puede ser IMPLEMENTER de varios WPs paralelos o REVIEWER de varios WPs paralelos. No hace falta reservar un harness distinto por WP. La sesión local se desambigua primero por el WP de su worktree y después por rol/harness/modelo.

Para evitar cruces operativos, dentro de un mismo lote paralelo activo no se asigna el mismo harness/modelo simultáneamente como IMPLEMENTER de unos WPs y REVIEWER de otros. La independencia exigida sigue siendo por WP/candidato: quien revisa un WP no puede ser quien implementó ese mismo WP.

Por defecto cada HUMAN_GATE puede iniciar manualmente cada sesión. Como excepción de DEC-018, una sola autorización humana puede iniciar un lote supervisado por COORDINADOR_LOCAL, que despacha esas sesiones una por una o hasta la concurrencia máxima autorizada. Cada worker sigue resolviendo exactamente una asignación compatible **para su WP local**; asignaciones compatibles del mismo agente en otros worktrees se ignoran.

Agregar o completar otro WP paralelo no revoca una asignación ya iniciada. Los campos escalares históricos de `CURRENT.json` quedan como resumen/compatibilidad y no autorizan trabajo cuando `active_assignments` existe.

## Ejecución secuencial de lotes paralelos bajo restricción de recursos

Cuando varios WPs son independientes pero el VPS no puede sostener varios agentes pesados simultáneos, el paralelismo lógico de `active_assignments` se conserva y la ejecución física se limita mediante `max_concurrency`.

Con la configuración actual del contenedor, **si cualquiera de los WPs del lote requiere pruebas de interfaz con navegador, `max_concurrency = 1` es obligatorio**. Esto incluye Playwright, Chromium, navegador real o herramientas equivalentes que incrementen el consumo de RAM. El paralelismo puede seguir existiendo a nivel de worktrees/asignaciones, pero no a nivel de ejecución física.

El ORCHESTRATOR entrega un prompt específico de COORDINADOR_LOCAL que contiene los WPs, fase, worktrees, agentes/modelos autorizados, política de cuota y condiciones de detención. El coordinador:

1. crea o adopta un Run de Orca;
2. crea una Task por asignación;
3. usa telemetría externa de cuota sólo cuando corresponda; **para Claude Code no usa `cuotas-agentes --json` como gate previo**;
4. cuando el worker es Claude, lo abre/reanuda y le exige auto-verificar desde su propia sesión si tiene capacidad efectiva; si está disponible, Claude continúa la asignación; si reporta límite de uso/rate limit impeditivo, devuelve control al coordinador sin iniciar trabajo sustantivo;
5. inicia sólo un worker de WP a la vez cuando `max_concurrency = 1`;
6. si ese worker ejecuta o puede ejecutar pruebas de navegador, espera a que termine y libere esos procesos antes de despachar otro;
7. espera `worker_done`, `escalation`, `question` o una devolución explícita `quota_unavailable` mediante la capa de orchestration;
8. libera o deja inactivo el worker finalizado sin borrar el worktree;
9. inicia el siguiente WP autorizado;
10. ante `quota_unavailable` confirmado por el propio worker, espera el reset, aprovecha otro WP independiente listo o detiene el lote según el manifiesto;
11. reanuda la misma sesión tras el reset cuando sigue viva; si Orca prueba `failed/stopped`, usa un reemplazo controlado en el mismo worktree;
12. termina el lote sin atravesar la siguiente puerta del ORCHESTRATOR.

El COORDINADOR_LOCAL puede permanecer como supervisor, pero no ejecuta pruebas de navegador ni abre un segundo worker. Una concurrencia física mayor que 1 requiere reevaluación explícita del perfil de RAM/recursos y autorización HUMAN_GATE; no se habilita automáticamente porque los WPs sean independientes.

El coordinador debe usar, cuando sea razonablemente posible, una fuente de cuota distinta de las ventanas que supervisa. Usar un modelo con nombre diferente pero dentro de la misma cuota efectiva no brinda independencia suficiente.

Un timeout, TUI idle o falta temporal de mensajes no prueba agotamiento. Tampoco lo prueba un `HTTP 429` del monitor `cuotas-agentes`. Para Claude, suspender/reanudar por cuota requiere evidencia de la propia sesión Claude; para otros agentes, evidencia explícita del worker o de una fuente operativa confiable.

## Lotes nocturnos con transición mecánica preautorizada

DEC-018 permite una excepción acotada para aprovechar periodos prolongados sin presencia del operador.

El ORCHESTRATOR puede preparar un manifiesto de lote que autorice al COORDINADOR_LOCAL a pasar automáticamente de una asignación IMPLEMENTER/SYNC ya autorizada a una REVIEWER ya decidida por HUMAN_GATE, **sin decidir nada por sí mismo**, cuando se cumplan condiciones objetivas verificables de PR/SHA/main/CI/handoff y no exista escalamiento.

En ese caso el COORDINADOR_LOCAL puede publicar la asignación REVIEWER exacta y actualizar únicamente el estado operativo necesario de SIS-Leg-Control para volver elegible al revisor fijado. Esa autoridad debe estar expresamente listada en el manifiesto del lote.

Esta excepción no alcanza a:

- interpretar el informe del REVIEWER;
- ordenar correcciones;
- re-revisiones;
- merge;
- cierre documental;
- cleanup;
- deploy.

Ante cualquier hallazgo o desviación material, el lote termina y vuelve al ORCHESTRATOR/HUMAN_GATE.

Cuando el manifiesto nocturno lo autoriza expresamente, el COORDINADOR_LOCAL también puede ejecutar un **merge normal puramente mecánico de origin/main** sobre una rama WP ya existente y limpia. Esta excepción sólo vale si el merge no presenta conflictos ni exige editar archivos. Puede crear el commit de merge, pushar y exigir CI verde. Cualquier conflicto, árbol sucio o necesidad de resolución de contenido devuelve el WP al implementador/ORCHESTRATOR.

## Turno de implementación

IMPLEMENTER:

1. verifica elegibilidad;
2. desde ese momento continúa autónomamente hasta el handoff, sin pedir permisos intermedios para acciones rutinarias;
3. trabaja únicamente en el worktree/rama del WP;
4. respeta AGENTS, WP, DECs y asignación;
5. sincroniza con `origin/main` según corresponda;
6. ejecuta validaciones aplicables;
7. diagnostica y corrige fallos normales dentro del alcance;
8. evalúa el impacto sobre `manual/index.html`, lo actualiza dentro del mismo WP cuando el cambio es relevante para usuario o soporte, y deja constancia explícita del resultado de esa evaluación en la PR y en su informe;
9. crea commits sin solicitar confirmación adicional;
10. push de rama sin solicitar confirmación adicional;
11. crea/actualiza PR;
12. deja candidato remoto con SHA exacto;
13. verifica CI según la asignación;
14. publica mediante commit/push únicamente `expected_response_path` en `SIS-Leg-Control`;
15. se detiene.

El inicio del turno por HUMAN_GATE ya autoriza estos pasos. El IMPLEMENTER solo vuelve al humano antes del handoff ante un gate real: DT-038/aprobación reservada, contradicción material, conflicto Git no trivial, operación destructiva/no autorizada, merge/deploy/infraestructura persistente no autorizada, credencial faltante o imposibilidad técnica.

El operador informa al ORCHESTRATOR que terminó el implementador.

El ORCHESTRATOR verifica GitHub real y no toma el autorreporte como autoridad suficiente.

## Sincronización final y staleness material

Antes de congelar el candidato para revisión, desde el worktree real:

```bash
git status --short
git fetch origin
git merge origin/main
```

No usar rebase ni force-push. Si `origin/main` avanzó **antes de la revisión**, se incorpora mediante merge normal y se ejecutan las validaciones aplicables antes de publicar el candidato final.

Después de que el REVIEWER aprobó un SHA exacto, un avance externo de `main` no obliga automáticamente a modificar esa rama ni a repetir pruebas.

El ORCHESTRATOR clasifica el avance posterior de `main`:

- **documental/operativo no ejecutable**: no sync, no nueva CI de candidato, no re-review;
- **código funcionalmente disjunto y con independencia demostrable**: puede conservarse el SHA revisado, documentando archivos/diferencias y exigiendo merge limpio + CI post-merge;
- **material o dudoso** —solapamiento de archivos, contratos, dependencias, componentes compartidos, misma superficie funcional, conflicto o interacción razonable—: sync normal + validaciones proporcionales + re-review proporcional sobre el SHA nuevo.

Ante duda se trata como material.

La evidencia mínima de no-materialidad incluye SHA revisado, `main` anterior/actual, archivos intervenientes, mergeabilidad y explicación de por qué el cambio no puede alterar el comportamiento revisado.

## Turno de revisión independiente

El ORCHESTRATOR crea una asignación REVIEWER normalizada que incluye únicamente el contexto necesario para una revisión independiente: WP, PR, base, SHA exacto, criterios, fuentes, pruebas, CI y prohibiciones.

El operador inicia manualmente el turno con `Revisá`.

REVIEWER:

- verifica elegibilidad desde `SIS-Leg-Control`;
- desde ese momento completa autónomamente toda la revisión hasta el handoff, sin pedir permisos intermedios;
- utiliza una sesión distinta;
- preferentemente usa otra familia de modelo;
- revisa el SHA exacto;
- inspecciona directamente código/diff/tests/CI;
- comprueba que la evaluación de impacto sobre `manual/index.html` esté declarada explícitamente y
  que el manual haya sido actualizado cuando el cambio sí es relevante para usuario o soporte;
- ejecuta tests/builds/validaciones no destructivas sin solicitar confirmación;
- trabaja en solo lectura respecto de SIS-Leg;
- no lee el informe privado del IMPLEMENTER;
- no modifica/pushea/mergea código de SIS-Leg;
- crea, commitea y pushea sin confirmación adicional únicamente su resultado para el ORCHESTRATOR en SIS-Leg-Control;
- finaliza con el worktree limpio.

Encontrar hallazgos no detiene el turno: debe completar la revisión y publicarlos. Solo un gate real de escalamiento o una imposibilidad técnica justifica devolver el control antes del handoff.

Cambiar solo de arnés manteniendo el mismo modelo efectivo no satisface por sí mismo la independencia.

## Correcciones y re-revisiones

Si existen hallazgos que el ORCHESTRATOR considera accionables:

1. ORCHESTRATOR procesa el informe del REVIEWER;
2. crea una nueva iteración/asignación IMPLEMENTER con los hallazgos autorizados;
3. HUMAN_GATE vuelve al implementador;
4. IMPLEMENTER corrige en la misma rama/PR salvo decisión canónica contraria;
5. publica nuevo candidato y resultado;
6. ORCHESTRATOR verifica;
7. crea nueva asignación REVIEWER sobre el nuevo SHA;
8. HUMAN_GATE inicia re-revisión.

El ciclo puede repetirse sin límite artificial.

## Auditoría sustantiva del ORCHESTRATOR antes del merge

Cuando IMPLEMENTER + REVIEWER —directamente o bajo COORDINADOR_LOCAL— terminan y el control vuelve a ChatGPT Web, **no se pasa mecánicamente al merge**.

El ORCHESTRATOR debe realizar la auditoría pre-integración definida por DEC-004. Como mínimo:

1. fresh-check de `main`, PR, base, HEAD, candidate/tree SHA, mergeabilidad y CI;
2. reconstrucción completa en SIS-Leg-Control de asignaciones, handoffs, correcciones, sincronizaciones, reviews y re-reviews;
3. confirmación de que el último REVIEWER cubrió exactamente el candidate SHA final;
4. comprobación de independencia de implementador/revisor y modelos efectivos;
5. inspección propia del diff completo y archivos cambiados;
6. contraste contra WP, criterios, exclusiones, DECs/DTs y documentación canónica;
7. análisis de tests modificados/agregados y de lo que realmente prueban;
8. verificación del impacto en manual/documentación;
9. resolución explícita de `soft_deviation`, staleness y excepciones;
10. búsqueda activa de contradicciones entre implementación, review, CI y contenido real del candidato.

ChatGPT Web no necesita ejecutar localmente la suite para esta auditoría. Debe usar el acceso independiente a GitHub y la evidencia persistida para aplicar análisis técnico propio.

El informe del REVIEWER y la CI verde son entradas de la auditoría, no sustitutos de ella.

La auditoría se registra append-only en:

`work-packages/WP-NNN/audits/pre-merge-XXX.md`

Sólo un veredicto `APROBADO_PARA_MERGE` permite continuar a la puerta de integración. Si el análisis detecta un problema, se vuelve a corrección/re-revisión o se bloquea el WP según corresponda.

## Puerta de integración

Antes de indicar que una PR puede integrarse, el ORCHESTRATOR verifica directamente en GitHub:

- PR abierta y base `main`;
- mergeable;
- SHA revisado igual al HEAD actual;
- CI aplicable del candidato revisado verde;
- revisión independiente procesada;
- evaluación de impacto sobre `manual/index.html` declarada y resuelta;
- cero hallazgos BLOQUEANTES pendientes;
- cero hallazgos IMPORTANTES pendientes;
- si `main` avanzó después de la revisión, clasificación explícita de staleness material.

Un avance no material de `main` no cambia el SHA revisado y no exige por sí mismo re-review. Un avance material exige sincronización y validación proporcional antes de integrar.

La integración productiva se realiza mediante squash merge.

El REVIEWER no mergea ni autoriza por sí mismo la integración.

## Después del merge

El ORCHESTRATOR verifica:

- PR efectivamente mergeada;
- SHA de integración;
- estado de `main`;
- CI post-merge cuando corresponda;
- ausencia de trabajo productivo pendiente;
- cierre documental;
- limpieza de worktree/rama.

### Excepción demostrada de plataforma en CI post-merge

DEC-017 permite documentar una excepción únicamente cuando:

1. la CI del candidato exacto fue verde;
2. la revisión independiente aprobó ese candidato;
3. el squash merge fue normal;
4. candidato y squash tienen el mismo tree SHA;
5. existe evidencia de que la corrida post-merge quedó huérfana/inconsistente por infraestructura GitHub;
6. el operador autoriza explícitamente la excepción.

No se crea un commit vacío ni se modifica código solo para fabricar una nueva corrida.

## Limpieza en Orca

Cuando Orca administró el worktree, usar primero Orca:

```bash
orca worktree list --repo path:/workspace/SIS-Leg --json
```

Obtener un selector inequívoco, preferentemente `id:<id>`, y ejecutar:

```bash
orca worktree rm \
  --worktree "id:<id-exacto-devuelto-por-orca>" \
  --json
```

Luego verificar:

```bash
orca worktree list --repo path:/workspace/SIS-Leg --json
git worktree list
git branch --list '*wp-NNN*'
```

Solo después se elimina la rama remota:

```bash
git push origin --delete <rama-remota>
git fetch --prune origin
```

No usar `--force` en `orca worktree rm` para descartar trabajo no investigado.

## Limpieza en entorno genérico

```bash
cd /workspace/SIS-Leg
git worktree remove <ruta-del-worktree>
git branch -d <rama> || git branch -D <rama>
git push origin --delete <rama>
git fetch --prune origin
git worktree list
git branch -r
```

`git branch -D` solo es admisible después de verificar que la PR fue integrada por squash, el árbol está limpio y no existen commits posteriores no integrados.

Como estado remoto normal, si no hay ningún WP activo debe quedar únicamente `main`.

## Flujo resumido

```text
ORCHESTRATOR
  -> reconstruye SIS-Leg + SIS-Leg-Control
  -> planifica WP con HUMAN_GATE
  -> resuelve decisiones DT-038
  -> documenta/aprueba WP
  -> selecciona implementador + revisor
  -> PLAN EN_CURSO
  -> publica asignación IMPLEMENTER + CURRENT
  -> HUMAN_GATE: "Seguí"
  -> IMPLEMENTER descubre asignación, implementa, PR/SHA/CI, publica resultado
  -> HUMAN_GATE vuelve al ORCHESTRATOR
  -> ORCHESTRATOR verifica GitHub
  -> publica asignación REVIEWER + CURRENT
  -> HUMAN_GATE: "Revisá"
  -> REVIEWER revisa solo lectura y publica resultado
  -> HUMAN_GATE vuelve al ORCHESTRATOR
  -> correcciones/re-revisiones si hacen falta
  -> ORCHESTRATOR verifica puerta de integración
  -> squash merge
  -> cierre documental + Control FINAL_DECISION
  -> limpieza
  -> CURRENT vuelve a PLANNING
```

## Regla para una conversación nueva

Una conversación nueva de ORCHESTRATOR debe reconstruir el estado desde ambos repositorios y no desde memoria.

`SIS-Leg-Control/CURRENT.json` indica el turno operativo; `SIS-Leg/docs/implementation/PLAN.md` y los WPs indican qué trabajo de producto existe y bajo qué reglas.

El contexto durable reside en GitHub.