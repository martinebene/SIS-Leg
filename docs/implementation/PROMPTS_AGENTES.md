# Política de prompts operativos para agentes

Este documento define cómo debe redactar ChatGPT Web/orquestador los prompts que delegan trabajo a agentes implementadores y revisores de SIS-Leg.

Complementa `AGENTS.md`, `docs/implementation/ORQUESTACION.md`, `PLAN.md`, los Work Packages y las decisiones vigentes. El prompt operativo **no reemplaza** esas fuentes: las convierte en instrucciones de ejecución concretas, ordenadas y difíciles de interpretar de forma ambigua.

## Principio rector

El orquestador debe aprovechar deliberadamente su mayor capacidad de razonamiento para reducir la carga de inferencia que queda en los agentes delegados.

En el flujo operativo vigente, ChatGPT Web utiliza GPT-5.6 Sol como modelo de orquestación de alta capacidad. Esta referencia es operativa y puede cambiar en el futuro: la regla durable es utilizar para orquestación el modelo de mayor capacidad/razonamiento disponible que resulte adecuado, y hacer que ese orquestador traduzca el WP y la gobernanza en prompts explícitos antes de delegar.

Los implementadores y revisores pueden utilizar modelos de menor capacidad, más rápidos o más económicos. Por eso **no se debe asumir que inferirán correctamente pasos implícitos**, aunque esos pasos también estén documentados en el repositorio.

La redundancia intencional entre documentación y prompt es una salvaguarda, no un defecto.

## Regla de explicitud

Todo prompt de delegación importante debe ser autosuficiente respecto del procedimiento operativo de esa tarea.

No alcanza con expresiones genéricas como:

```text
Implementá WP-007.
Revisá esta PR.
Corregí los hallazgos.
```

El orquestador debe indicar de forma expresa:

- qué rol tiene el agente;
- cuál es el objetivo verificable;
- qué fuentes debe leer y en qué orden;
- qué alcance puede modificar;
- qué queda prohibido o fuera de alcance;
- qué decisiones debe escalar en lugar de inventar;
- qué estado Git/worktree se espera;
- qué pasos de implementación o revisión debe ejecutar;
- qué validaciones concretas debe correr;
- qué política de sincronización con `origin/main` aplica;
- si debe o no hacer commits;
- si debe o no hacer push;
- si debe o no abrir/actualizar PR;
- si está expresamente prohibido hacer merge;
- qué evidencia exacta debe devolver al finalizar.

Cuando el WP ya documenta alguno de estos puntos, el prompt puede referenciarlo, pero debe repetir explícitamente los pasos operativos críticos cuya omisión pueda romper el flujo.


## Bloque obligatorio de autonomía del turno

Toda asignación dirigida a IMPLEMENTER o REVIEWER debe dejar explícito que, una vez validada la elegibilidad desde SIS-Leg-Control, el turno ya está autorizado de punta a punta.

El ORCHESTRATOR debe incluir o garantizar por referencia normativa estas instrucciones:

- **no pedir permiso intermedio** para acciones rutinarias comprendidas en el rol/asignación;
- continuar hasta publicar el handoff o hasta encontrar un gate real de escalamiento;
- IMPLEMENTER: editar, probar, corregir, commit, sincronización Git permitida, push, PR, CI y handoff forman parte normal del mismo turno;
- REVIEWER: inspección/tests/builds no destructivos y publicación del handoff forman parte normal del mismo turno; “solo lectura” aplica al producto/candidato, no al commit/push del informe en SIS-Leg-Control;
- un fallo normal de test o un defecto encontrado debe diagnosticarse dentro del turno, no transformarse en una pregunta al humano;
- pedir intervención únicamente por DT-038, aprobación humana expresamente reservada, contradicción material, conflicto Git no trivial, operación destructiva/force, merge/deploy/infraestructura persistente no autorizada, credenciales faltantes, pérdida de elegibilidad o imposibilidad técnica.

Una asignación que deje abierta la pregunta “¿hago el commit/push?” está incompleta.


## Responsabilidad del orquestador

Antes de lanzar un agente, ChatGPT Web/orquestador debe:

1. reconstruir el estado real desde GitHub;
2. conocer el WP, SHA/base y entorno operativo actual;
3. identificar el rol concreto: implementación, corrección, revisión o investigación;
4. resolver previamente las decisiones humanas necesarias;
5. redactar un prompt específico para ese momento del flujo;
6. comprobar que el prompt no contradice el WP ni decisiones canónicas;
7. eliminar ambigüedades sobre Git, PR, validaciones, límites y salida esperada;
8. no delegar al agente decisiones reservadas por DT-038;
9. no confiar en que el agente recuerde conversaciones anteriores;
10. exigir evidencia verificable al terminar.

El orquestador debe preferir un prompt algo redundante antes que uno elegante pero dependiente de inferencias tácitas.

## Prompt inicial de un implementador

El prompt inicial de implementación debe contener, como mínimo, los siguientes bloques conceptuales.

### 1. Rol y objetivo

Debe declarar que el agente es **implementador** del WP concreto y que su responsabilidad no termina cuando el código funciona localmente.

Debe distinguir:

```text
IMPLEMENTACIÓN LOCAL COMPLETA
```

Código y pruebas locales terminados.

De:

```text
CANDIDATO ENTREGADO PARA REVISIÓN
```

Trabajo confirmado en commits, sincronizado con `origin/main`, validado nuevamente, publicado, con PR abierta y SHA candidato identificable.

La tarea normal del implementador termina recién en el segundo estado, salvo que el prompt indique expresamente una investigación o intervención parcial.

### 2. Lecturas obligatorias

Indicar expresamente:

1. `AGENTS.md`;
2. `docs/work-packages/WP-NNN.md`;
3. únicamente las fuentes canónicas exigidas por ese WP;
4. decisiones transversales aplicables.

No pedir exploración indiscriminada del repositorio cuando el WP ya delimita el contexto.

### 3. Alcance y prohibiciones

El prompt debe repetir los límites de mayor riesgo del WP y aclarar expresamente, cuando corresponda:

- no ampliar alcance;
- no modificar contratos ajenos;
- no introducir dependencias no aprobadas;
- no copiar arquitectura histórica por analogía;
- no resolver unilateralmente decisiones DT-038;
- no usar rebase ni force-push salvo autorización específica;
- no hacer merge de la PR;
- no borrar worktree/rama al finalizar.

### 4. Ejecución y calidad

El prompt debe enumerar los checks aplicables **por su comando real**, no decir solamente “corré las pruebas”.

Ejemplo Python cuando aplique:

```text
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
git diff --check
```

Si el WP requiere otros checks, deben enumerarse también.

### 5. Entrega Git obligatoria

Para una implementación normal destinada a revisión independiente, el prompt debe indicar expresamente:

1. inspeccionar `git status` y cambios realizados;
2. crear commits normales del WP;
3. `git fetch origin`;
4. incorporar `origin/main` mediante merge normal si avanzó;
5. detenerse y escalar conflictos no triviales en vez de inventar soluciones de contrato;
6. repetir todos los checks después de la sincronización;
7. exigir `git status` limpio;
8. publicar la rama sin renombrarla por detrás del entorno que la administra;
9. abrir o actualizar PR contra `main`;
10. no hacer merge.

El hecho de que `AGENTS.md`, el WP u ORQUESTACION describan este flujo **no autoriza a omitirlo del prompt**.

### 6. Contenido mínimo de la PR

Cuando el implementador debe crear la PR, el prompt debe pedir como mínimo:

- referencia al WP;
- objetivo y alcance implementado;
- explicación apta para una persona que no conozca la implementación;
- archivos/componentes principales afectados;
- decisiones o escalaciones relevantes;
- agente y modelo efectivo cuando sea relevante;
- comandos y resultados finales de validación;
- confirmación de que no amplió alcance ni hizo merge;
- hallazgos fuera de alcance.

### 7. Salida final obligatoria

El implementador debe devolver un informe estructurado con al menos:

```text
Worktree:
Rama local/remota:
Base incorporada:
SHA candidato:
PR:
Commits:
Archivos cambiados:
Validaciones:
CI si ya existe:
Git status final:
Hallazgos/escalaciones:
```

El orquestador no debe aceptar “terminado”, “todo verde” o un resumen funcional como sustituto de estos identificadores cuando la tarea debía llegar a candidato remoto.

## Prompt de corrección al implementador

Si una revisión encuentra problemas, el prompt de corrección debe especificar:

- SHA revisado;
- hallazgos exactos que debe corregir;
- cuáles NO debe tocar;
- que vuelve a actuar el implementador original;
- que debe conservar la rama/worktree existente;
- que debe repetir sincronización y checks aplicables;
- que debe pushar el nuevo candidato;
- que no debe hacer merge;
- que debe devolver el nuevo SHA y evidencia de cada hallazgo resuelto.

No usar prompts vagos como “arreglá lo que dijo el revisor”.

## Prompt inicial de un revisor independiente

La revisión es una tarea distinta y su prompt debe ser igualmente explícito.

Debe indicar:

### 1. Identidad exacta del candidato

- repositorio;
- número de WP;
- PR;
- rama;
- SHA exacto a revisar;
- base `main`/SHA relevante.

El revisor no debe revisar “lo último” sin congelar primero la identidad del candidato.

### 2. Modo de trabajo

Por defecto:

- mismo worktree del WP de forma secuencial;
- implementador inactivo durante la revisión;
- revisión en **solo lectura**;
- no modificar archivos;
- no crear commits;
- no hacer push;
- no hacer merge;
- finalizar con `git status` limpio.

### 3. Qué revisar

El prompt debe pedir explícitamente:

- cumplimiento del WP y sus criterios;
- respeto de alcance/fuera de alcance;
- contratos e invariantes;
- errores funcionales;
- concurrencia/seguridad cuando corresponda;
- cobertura y calidad de tests;
- calidad estática;
- regresiones;
- documentación requerida;
- comportamiento ante errores;
- cualquier decisión DT-038 introducida sin autorización.

### 4. Validaciones

Enumerar los comandos aplicables y pedir que el revisor contraste también la CI del SHA revisado cuando pueda hacerlo.

### 5. Formato de hallazgos

Cada hallazgo debe incluir:

```text
Severidad: BLOQUEANTE | IMPORTANTE | MENOR
Archivo/línea o componente:
Problema:
Impacto:
Evidencia:
Corrección requerida o recomendada:
```

El veredicto final debe ser inequívoco:

```text
LISTA PARA INTEGRAR
```

o

```text
REQUIERE CORRECCIONES
```

Un veredicto positivo exige cero hallazgos BLOQUEANTES e IMPORTANTES pendientes.

## Prompt de re-revisión

Después de correcciones, el revisor debe recibir un nuevo prompt que identifique el **nuevo SHA** y pida:

- verificar específicamente cada hallazgo previo;
- comprobar que no aparecieron regresiones nuevas;
- repetir validaciones relevantes;
- confirmar `git status` limpio;
- emitir nuevo veredicto sobre ese SHA, no reutilizar el anterior.

## Prompts para investigación o diagnóstico

Incluso cuando no haya implementación, el prompt debe especificar:

- pregunta concreta;
- fuentes permitidas/prioridad de evidencia;
- si puede modificar algo o es solo lectura;
- qué hipótesis debe validar;
- qué no debe cambiar;
- formato de informe;
- cuándo debe detenerse y escalar.

## Relación con el launcher

Los lanzadores (`scripts/iniciar_wp.py` y `scripts/iniciar_wp_orca.py`) son responsables exclusivamente de verificar precondiciones documentales y de estado Git, preparar o reutilizar el worktree y la rama asociada, y abrir la sesión del agente asignado.

El launcher **no genera, valida ni transporta el prompt de trabajo**:
- no construye ningún texto de tarea;
- no pasa `--prompt` a `orca worktree create` ni a ningún subproceso;
- no inyecta instrucciones por stdin, variables de entorno ni archivos temporales.

Tras un inicio exitoso, el launcher muestra al operador una indicación breve para que pegue el prompt entregado por el orquestador:

```text
Agente abierto. Pegá ahora el prompt entregado por el orquestador.
```

El flujo operativo se divide de forma estricta:
1. ChatGPT Web/orquestador redacta el prompt exhaustivo específico para la tarea vigente;
2. el operador recibe y lee el prompt completo visible en la interfaz de chat;
3. el operador lo traslada manualmente (copia y pega) a la sesión del agente abierta en la terminal;
4. el agente ejecuta las instrucciones recibidas.

La revisión humana explícita del prompt antes de su ejecución forma parte deliberada del control de calidad y la gobernanza del proyecto.

## Salida copiable para OpenCode bajo Orca

Esta función aplica **única y exclusivamente** cuando se cumplen simultáneamente ambas condiciones:
- **entorno operativo**: Orca;
- **agente efectivo**: OpenCode.

### Motivación

La interfaz basada en terminal (TUI) de OpenCode presenta dificultades en ciertos clientes (especialmente dispositivos móviles o terminales web remotas) para seleccionar y copiar bloques de texto extensos de forma limpia. Dado que Orca permite crear terminales comunes dentro del mismo workspace y que OpenCode puede ejecutar herramientas locales y cargar skills, se aprovecha esta capacidad para poner a disposición del operador una pestaña de terminal estándar con el texto exacto de la respuesta final.

### Contrato operativo

Cuando entorno=Orca y agente=OpenCode, ChatGPT Web debe incluir al final del prompt de delegación un bloque de instrucciones con el siguiente procedimiento exacto:

1. **Composición de la respuesta**: OpenCode compone primero el informe o respuesta final completo correspondiente a su turno de trabajo.
2. **Almacenamiento temporal fuera del repositorio**: Antes de emitir su mensaje final en la TUI, guarda exactamente ese texto en un archivo temporal no versionado y fuera del árbol Git (por ejemplo `/tmp/sis-leg-wp-NNN-opencode-ultima-respuesta.txt`, sobrescribiéndolo si ya existía para reflejar siempre la última respuesta de ese WP).
3. **Carga de skill oficial**: Carga y consulta la skill oficial `orca-cli` antes de interactuar con la CLI de Orca, sin inventar flags de memoria.
4. **Creación de terminal común auxiliar**: Abre una terminal común dentro del mismo worktree mediante:
   ```bash
   orca terminal create --worktree <selector-valido> --title "Salida OpenCode WP-NNN" --command "cat <archivo-temporal>"
   ```
   (utilizando un selector explícito inequívoco del worktree actual, como `path:<ruta-absoluta>` o `id:<id>`).
5. **Emisión en la TUI**: OpenCode emite a continuación en su propia interfaz el mismo texto de respuesta final que fue guardado en el archivo.
6. **Ejecución estricta y pasiva**: La terminal adicional creada por Orca ejecuta únicamente el comando de lectura (`cat`) del archivo temporal y no inicia otro agente ni ejecuta procesos interactivos adicionales.
7. **Reglas de seguridad y exclusión**:
   - No se utiliza `opencode export` ni se parsea el historial o la base de datos de sesiones de OpenCode.
   - El archivo temporal no debe contener prompts del usuario, historial acumulado, razonamiento interno, llamadas a herramientas ni salidas de depuración: contiene únicamente la respuesta final visible para el operador.
   - No se modifican archivos versionados ni el estado de Git para generar este espejo.
   - Si la skill `orca-cli` o la CLI de Orca no están disponibles o la creación de terminal falla, el agente no debe improvisar automatizaciones alternativas ni alterar su entrega: conserva el archivo temporal si fue posible y reporta el fallo operativo en su respuesta visible.
   - La terminal adicional es un apoyo de visualización y copiado para el operador; no constituye una segunda sesión de agente ni viola la regla de revisión secuencial del worktree.

### Restricción de alcance

Esta ayuda de copia **no aplica** fuera de Orca ni para agentes distintos de OpenCode (como Antigravity, Codex o Claude). Fuera de este caso específico, los agentes entregan su salida exclusivamente a través de sus interfaces habituales.

## Prompt para COORDINADOR_LOCAL de un lote

Cuando el ORCHESTRATOR habilite varios WPs independientes y el entorno vaya a ejecutarlos secuencialmente por limitación de recursos, debe entregar además un prompt específico al COORDINADOR_LOCAL conforme a DEC-018.

Ese prompt no reemplaza las asignaciones de IMPLEMENTER/REVIEWER. Su única función es secuencializarlas.

Debe contener, como mínimo:

1. **Rol y límites**
   - declarar `COORDINADOR_LOCAL`, no ORCHESTRATOR;
   - prohibir cambios de producto, PLAN, `CURRENT.json`, asignaciones, PR, merge, deploy y cleanup;
   - prohibir cruzar el siguiente gate del ORCHESTRATOR.

2. **Lote exacto**
   - WPs incluidos;
   - fase exacta: IMPLEMENTER, REVIEWER o re-revisión;
   - worktree y terminal esperados por WP cuando se conozcan;
   - agente/harness/modelo autorizado de cada WP.

3. **Concurrencia**
   - `max_concurrency` explícito;
   - para el VPS limitado, normalmente `max_concurrency = 1`;
   - no iniciar el siguiente worker pesado hasta que el actual haya terminado, quedado suspendido por cuota con evidencia o sido liberado.

4. **Orca orchestration**
   - usar Run/Task/Dispatch o `worker-start` sobre los worktrees existentes;
   - esperar `worker_done`, `escalation` y `question` con `check --wait`;
   - usar `worker-release` al completar cuando no se reutilice la sesión;
   - no inferir finalización por TUI idle.

5. **Cuotas**
   - consultar `cuotas-agentes --json` antes de cada despacho;
   - identificar la ventana de 5 horas y `reinicia_epoch` cuando estén disponibles;
   - no inventar el consumo futuro de una tarea;
   - aplicar el umbral/reserva fijado por el ORCHESTRATOR, si existe;
   - con agotamiento confirmado, ejecutar otro WP listo o esperar hasta el reset y reconsultar.

6. **Recuperación por agotamiento durante el trabajo**
   - conservar worktree/rama/archivos;
   - si la misma sesión sigue viva, reanudarla tras el reset;
   - si Orca prueba `failed/stopped`, usar un reemplazo controlado en el mismo worktree;
   - nunca dejar dos workers activos sobre el mismo WP;
   - no considerar timeout o idle como rate limit sin evidencia.

7. **Independencia del coordinador**
   - registrar harness/modelo/proveedor efectivo del coordinador;
   - preferir una cuota independiente de las que supervisa;
   - no considerar independiente un modelo distinto que consume la misma ventana efectiva.

8. **Salida**
   - al finalizar el lote, informar por WP: iniciado, completado/suspendido, handoff detectado, cuotas/esperas relevantes y cualquier escalación;
   - detenerse sin iniciar la fase siguiente.

### Forma abreviada que el operador puede usar

Una vez que el prompt completo anterior fue cargado, el operador puede iniciar el lote con una frase breve como:

`Ejecutá el lote autorizado.`

El trabajo real sigue estando definido por el prompt del COORDINADOR_LOCAL, `CURRENT.json` y las asignaciones de cada WP.

## Preflight del prompt antes de delegar

Antes de enviar un prompt a cualquier agente, el orquestador debe preguntarse:

1. ¿El agente sabe exactamente qué rol cumple?
2. ¿Sabe qué debe leer y qué no necesita leer?
3. ¿Sabe qué puede modificar?
4. ¿Sabe qué está prohibido modificar?
5. ¿Sabe qué debe escalar?
6. ¿Sabe qué comandos de validación ejecutar?
7. ¿Sabe qué hacer con `origin/main`?
8. ¿Sabe si debe commit/push/PR?
9. ¿Sabe explícitamente que no debe hacer merge?
10. ¿Sabe qué información exacta debe devolver?

Si alguna respuesta es no, el prompt todavía no está listo.

## Persistencia entre conversaciones

Una conversación nueva de ChatGPT Web debe reconstruir esta política desde el repositorio. No debe depender de memoria de la conversación que originalmente definió esta regla.

La explicitud de los prompts forma parte de la responsabilidad de orquestación y debe conservarse aunque cambien los agentes, los modelos implementadores/revisores, Orca u otras herramientas de ejecución.