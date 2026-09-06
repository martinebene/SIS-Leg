# AGENTS.md

## Propósito

Este repositorio contiene la especificación canónica y, posteriormente, la implementación de SIS-Leg, nueva versión del sistema de votación del Concejo Deliberante de Puerto Madryn.

Los agentes deben implementar lo documentado aquí; no reconstruir el producto a partir del repositorio histórico.

## Coordinación operativa obligatoria - DEC-017

Desde la activación de `docs/decisions/DEC-017-coordinacion-mediante-sis-leg-control.md`, todo agente local que participe como IMPLEMENTER o REVIEWER en un WP orquestado debe usar `martinebene/SIS-Leg-Control` como fuente de turno y handoff antes de realizar trabajo sustantivo.

Una instrucción humana breve como `Seguí` o `Revisá` **no contiene por sí misma la tarea**. Antes de actuar, el agente debe:

1. sincronizar una copia local de `martinebene/SIS-Leg-Control` con su `main` remoto;
2. leer `AGENTS.md` de ese repositorio;
3. leer `CURRENT.json`;
4. leer el archivo de rol que corresponda;
5. verificar que `next_actor`, `assignment_id`, WP, iteración y destinatario coincidan con su rol y, si la asignación fija agente/arnés o modelo, que esta sesión esté autorizada para ejecutarla;
6. comprobar que el `expected_response_path` todavía no exista;
7. leer únicamente la asignación vigente indicada por `assignment_path`;
8. recién entonces leer el WP y las fuentes canónicas de SIS-Leg necesarias para ejecutar esa asignación.

Si el rol no coincide, la asignación no existe, los metadatos no coinciden, el resultado esperado ya existe o el estado es ambiguo, el agente debe detenerse sin modificar nada e indicar al operador qué actor corresponde.

### Varios WPs activos

Desde protocolo 1.2, `SIS-Leg-Control/CURRENT.json` puede contener `active_assignments`. Cuando exista esa colección, los campos escalares históricos de turno no son autoridad de elegibilidad.

La sesión debe determinar primero su worktree/rama actual y resolver de forma inequívoca el `WP-NNN` local. Después filtra `active_assignments` por ese WP, luego por rol y finalmente por arnés/modelo cuando estén fijados. Debe quedar exactamente una asignación compatible **dentro del WP actual**; recién entonces verifica `assignment_id`, iteración, ruta y respuesta pendiente y actúa.

Asignaciones del mismo arnés/modelo en otros worktrees/WPs no generan ambigüedad y se ignoran desde esta sesión. Cero coincidencias para el WP local implica que ese agente no tiene turno; más de una dentro de ese mismo WP implica ambigüedad real y obliga a detenerse. Cambios en otras asignaciones paralelas no invalidan un turno ya iniciado: solo la entrada del mismo WP determina su continuidad.

El mismo arnés/modelo puede implementar varios WPs paralelos en worktrees distintos, o revisar varios WPs paralelos en worktrees distintos. La independencia de revisión se exige por WP/candidato: quien revisa un WP no puede ser quien implementó ese mismo WP. Dentro de un mismo lote paralelo activo se evita mezclar al mismo arnés/modelo simultáneamente entre roles IMPLEMENTER y REVIEWER.

Una vez que esas comprobaciones pasan, la intervención humana que inició el turno **autoriza la ejecución completa de la asignación hasta el handoff**. El agente no debe introducir micro-confirmaciones adicionales para acciones rutinarias ya autorizadas.

En particular:

- IMPLEMENTER no pide permiso para editar dentro del alcance, ejecutar comandos/tests/builds, crear commits normales, sincronizar Git según el flujo, hacer push, crear/actualizar PR, esperar/verificar CI ni publicar su handoff;
- REVIEWER no pide permiso para inspeccionar, ejecutar tests/builds/validaciones no destructivas ni completar el análisis; su modo solo lectura prohíbe modificar/commitear/pushear SIS-Leg, pero **sí** puede crear, commitear y pushear su único handoff en SIS-Leg-Control;
- encontrar un bug o un test fallido no habilita detenerse para preguntar: el IMPLEMENTER lo corrige dentro del alcance y el REVIEWER lo investiga/documenta;
- solo se detiene antes del handoff ante DT-038/aprobación humana explícita, contradicción material, conflicto/divergencia Git no trivial, operación destructiva o no autorizada, merge/deploy/cambio persistente de infraestructura no autorizado, secreto/credencial faltante, pérdida de elegibilidad o imposibilidad técnica real.

La configuración del arnés/Orca con permisos completos debe aprovecharse para ejecutar estas acciones sin solicitudes de confirmación artificiales.


El repositorio `SIS-Leg-Control` es únicamente transporte, estado de turno e historial operativo. **Este repositorio SIS-Leg continúa siendo la fuente normativa del producto, WPs, decisiones, código, CI e integración.** Una asignación del repositorio de control no puede ampliar ni contradecir el alcance canónico.

IMPLEMENTER y REVIEWER no se comunican lateralmente. El implementador no consume informes `reviewer-to-orchestrator`; el revisor no consume informes `implementer-to-orchestrator`. Todo hallazgo que deba cruzar de un rol al otro pasa primero por el ORCHESTRATOR.

## Flujo de lectura obligatorio para implementación

Para un Work Package normal, después de completar la elegibilidad operativa anterior y antes de proponer o modificar código:

1. leer `AGENTS.md`;
2. leer el `docs/work-packages/WP-XXX.md` asignado;
3. leer únicamente las fuentes canónicas y secciones que ese WP declare obligatorias;
4. leer las decisiones `DEC-XXX` transversales vigentes que este archivo declare obligatorias para todos los WPs;
5. inspeccionar el código, contratos y pruebas directamente necesarios para ese alcance.

No recorrer indiscriminadamente toda la documentación o todo el monorepo cuando el WP ya delimita el contexto necesario.

Los agentes de planificación, auditoría global, revisión transversal o resolución de contradicciones pueden necesitar ampliar el contexto según su tarea.

## Documentos de orientación global

Cuando una tarea requiera reconstrucción global, las fuentes principales son:

- `README.md`;
- `docs/00-principios-y-alcance.md`;
- `docs/01-reglas-de-negocio.md`;
- `docs/02-modelo-de-dominio-y-estados.md`;
- `docs/03-casos-de-uso.md`;
- `docs/04-contratos-e-integraciones.md`;
- `docs/05-frontend-moderacion.md`;
- `docs/06-frontend-pantalla-recinto.md`;
- `docs/07-configuracion-datos-y-assets.md`;
- `docs/08-observabilidad-y-auditoria.md`;
- `docs/09-fuentes-y-trazabilidad.md`;
- `docs/10-preguntas-abiertas.md`;
- `docs/11-criterios-de-aceptacion.md`;
- `docs/12-decisiones-tecnicas.md`;
- `docs/13-despliegue-y-operacion.md`;
- `docs/14-gobernanza-agentes.md`;
- `docs/implementation/PLAN.md`;
- decisiones `docs/decisions/DEC-XXX-*.md` vigentes que afecten el alcance.

## Autoridad documental

- La documentación de SIS-Leg es la fuente normativa para la nueva implementación.
- El WP asignado define el alcance operativo, pero no puede contradecir reglas o decisiones canónicas.
- Las decisiones `DEC-XXX` aprobadas posteriores son vinculantes para todos los WPs afectados.
- `DEC-001`, `DEC-003`, `DEC-007` y `DEC-017` son decisiones transversales obligatorias para todos los WPs de implementación, aunque un WP antiguo no las enumere explícitamente.
- El repositorio histórico `martinebene/Botonera`, rama `main`, puede consultarse como referencia funcional únicamente según la regla de fallback definida más abajo y en `docs/decisions/DEC-001-estilo-codigo-y-referencia-produccion.md`.
- No copiar arquitectura, clases, endpoints internos, polling, serialización ni estructura histórica por defecto.
- La rama histórica `v2` no es normativa.
- El proyecto se llamó `Botonera2` hasta WP-077. `docs/NOTA-LEGADO-BOTONERA2.md` traduce ese
  nombre histórico al vigente y explica qué evidencia conserva la identidad anterior;
  `scripts/auditar_identidad_legada.py` falla si el nombre legado reaparece fuera de esa
  allowlist.
- Si una implementación antigua contradice SIS-Leg, manda SIS-Leg.
- La asignación operativa o prompt no reemplaza la especificación versionada del WP ni puede ampliar silenciosamente su alcance.

## Regla de fallback funcional a producción

Ante cualquier duda sobre **reglas de negocio, experiencia de usuario o diseño/flujo de interfaz gráfica**:

1. consultar primero la documentación canónica vigente de SIS-Leg y las decisiones aprobadas;
2. si el comportamiento no está claramente definido, verificar cómo funciona el sistema actualmente en producción en `martinebene/Botonera`, rama `main`, usando el estado vigente de esa rama al momento de la tarea;
3. consultar únicamente los archivos necesarios para resolver la duda concreta;
4. para comportamiento real, si existen contradicciones internas en el repositorio histórico, priorizar el código ejecutable de `main` sobre README, manuales o comentarios antiguos;
5. si producción tampoco resuelve la duda de manera inequívoca, escalarla antes de inventar una nueva regla, interacción o decisión visual;
6. si SIS-Leg ya define explícitamente un comportamiento distinto, prevalece SIS-Leg y la producción anterior no reabre esa decisión.

Cuando la consulta a producción influya en una implementación, la PR debe indicar qué comportamiento se verificó y qué archivos fueron consultados.

Esta regla **no aplica a decisiones técnicas**. Ante dudas de arquitectura, dependencias, transporte, concurrencia, persistencia, stack, testing, CI, despliegue o contratos técnicos nuevos, no copiar por analogía el sistema histórico: aplicar DT-038 y escalar cuando corresponda.

## Arquitectura funcional obligatoria

La solución se implementa como **monorepo** con responsabilidades separadas:

- `apps/backend`: FastAPI;
- `apps/moderacion`: Nuxt 4;
- `apps/recinto`: Nuxt 4;
- `services/device-bridge`: captura/remapeo físico;
- `packages/api-client`: cliente REST/SSE y tipos compartidos;
- `packages/frontend-shared`: solo código realmente común;
- `config`: configuración del backend/padrón.

El backend es la única autoridad de estado global, preparación, sesión, presencia, votaciones/resultados, palabra, autoridades y auditoría institucional.

Los frontends representan estado y envían comandos permitidos. Nunca deciden reglas de negocio.

## Stack técnico cerrado DT-001 a DT-026

- Python **3.14** con **uv** y `uv.lock`.
- Node.js **24 LTS** con **pnpm workspaces** y `pnpm-lock.yaml`.
- FastAPI con un único proceso/worker y un único estado operativo en memoria.
- Toda mutación pasa por un mecanismo único de serialización/exclusión.
- Sin base de datos en la primera versión.
- API REST `/api/v1`, Pydantic y OpenAPI.
- REST para comandos/snapshots; **SSE** para actualización continua.
- Proyecciones independientes `ModerationState` y `PublicState`.
- Configuración funcional en `config/system.toml`.
- Padrón en `config/concejales.csv`.
- Mapeo físico del bridge en `services/device-bridge/config/devices.json`.
- Orden del Día parseado exclusivamente por backend.
- Auditoría CSV: `seq;timestamp;level;tag;event_code;message`, delimitador `;`, UTF-8 con BOM.
- Persistencia de auditoría con escritura síncrona + `flush` + `fsync`; ante imposibilidad de auditar, fallo cerrado para nuevas mutaciones.
- Remapeo urgente: nuevo fingerprint físico -> mismo identificador lógico dentro del bridge.
- Nuxt 4 + Vue 3 + TypeScript estricto.
- Tailwind CSS v4 + componentes propios; sin Nuxt UI inicial.
- Sin Pinia inicialmente; estado frontend mediante composables/primitives.
- `packages/api-client/` concentra REST/SSE/reconexión/tipos.
- Compartición de UI mínima, no una librería común extensa preventiva.
- 1920×1080 es resolución de referencia, no dependencia rígida; ambos frontends deben ser adaptables.
- pytest + HTTPX + AnyIO para backend.
- Vitest + Nuxt Test Utils + Vue Test Utils para frontend.
- Playwright para E2E críticos.
- GitHub Actions por PR.
- Ruff + Pyright en Python; ESLint + Prettier + `nuxt typecheck` en frontend.

Estas decisiones están desarrolladas en `docs/12-decisiones-tecnicas.md` y no deben reconsiderarse dentro de un WP normal.

## Despliegue cerrado DT-027 a DT-032

Ver `docs/13-despliegue-y-operacion.md`.

Principios principales:

- Linux Mint 22.3 Cinnamon como plataforma de referencia;
- systemd nativo;
- Nuxt SPA estáticas;
- Nginx y mismo origen para frontends/API;
- releases inmutables con `current` y rollback;
- no desplegar deliberadamente durante preparación/sesión;
- CSV institucionales conservados localmente en la primera versión.

## Gobernanza cerrada DT-033 a DT-038, precisada por DEC posteriores

Ver `docs/14-gobernanza-agentes.md` y las DEC posteriores vigentes, especialmente DEC-004, DEC-005, DEC-007 y DEC-017.

- `main` es la única rama estable de integración.
- Cada WP usa una rama corta inequívoca y una PR; la forma literal depende del entorno conforme a DEC-007 (`wp/NNN-descripcion-corta` en el flujo genérico o rama nativa trazable administrada por Orca).
- WPs pequeños, con un único resultado verificable.
- `docs/implementation/PLAN.md` ordena WPs, dependencias, estado y agente asignado.
- `docs/work-packages/WP-XXX.md` es el contrato versionado del trabajo.
- `docs/decisions/DEC-XXX-*.md` se reserva para decisiones nuevas realmente transversales/relevantes.
- `.github/pull_request_template.md` define el mínimo de entrega de cada PR.
- No existe un implementador universal predeterminado: el agente se selecciona por WP según complejidad, riesgo, capacidad, disponibilidad/cuota e integración con el entorno, conforme a DEC-007.
- Antigravity/AGY, Codex, OpenCode y Claude Code son opciones aprobadas de primera clase para implementar o revisar según el WP, el modelo efectivo, el riesgo, la disponibilidad y la cuota. Claude Code puede utilizar actualmente Claude Opus 5 cuando el ORCHESTRATOR lo seleccione; esta disponibilidad es operativa y no fija un modelo permanente.
- Un WP tiene un único agente implementador.
- Cada WP `EN_CURSO` usa rama, `git worktree` y sesión de agente propios.
- Dos agentes solo pueden trabajar en paralelo sobre WPs independientes autorizados por PLAN.
- Está prohibido compartir working tree, rama o WP entre agentes simultáneos.
- La herramienta/modelo concreto no forma parte de la arquitectura permanente; debe registrarse en la PR cuando sea relevante.
- No se automatizan agentes generativos dentro de CI en la primera etapa.
- Toda PR de implementación requiere revisión independiente en modo solo lectura.
- Se prefiere otra familia de modelo para revisar; no puede integrarse una PR con hallazgos BLOQUEANTES o IMPORTANTES pendientes.
- El implementador tiene autonomía sobre detalles internos locales que no cambien comportamiento observable, contratos, dependencias ni decisiones globales.
- Las decisiones reservadas por DT-038 requieren aprobación humana/documentada antes de continuar el alcance afectado.
- La coordinación de turnos, handoffs e aislamiento entre roles se rige por DEC-017 y `martinebene/SIS-Leg-Control`.

## Evaluación obligatoria de impacto en el manual de usuario y soporte

`manual/index.html` es el manual único de operación, configuración, instalación, diagnóstico y
soporte de SIS-Leg. Es documentación destinada a personas que usan u operan el sistema, no
documentación interna de desarrollo.

Regla permanente, aplicable a **todo** cambio del sistema, tenga o no código:

1. antes de cerrar el trabajo hay que evaluar explícitamente si el cambio necesita ser explicado
   al usuario o al soporte técnico;
2. si la respuesta es **sí**, `manual/index.html` se actualiza dentro del mismo WP/PR o cambio
   autorizado, nunca en un trabajo posterior indeterminado;
3. si la respuesta es **no**, la entrega debe dejar registrado de forma explícita que el impacto
   sobre el manual fue evaluado y no requiere actualización.

La regla alcanza tanto funciones nuevas como cambios de comportamiento, operación, configuración,
instalación, diagnóstico, textos relevantes para quien opera y flujos de soporte.

No exige documentar en el manual detalles internos de desarrollo sin utilidad para usuario o
soporte: refactors internos, nombres de módulos, estructura de tests o decisiones puramente
técnicas invisibles para quien opera se declaran «sin impacto» y se cierra el punto ahí.

La evaluación es una obligación humana/agéntica de criterio. No existe ni se pretende una
automatización que decida por sí sola si el manual necesita cambios.

Esta regla no altera DEC-005 ni DEC-019: un cambio puramente documental autorizado sigue el
mecanismo de DEC-005, y qué eventos ejecutan CI sigue determinándose exclusivamente por DEC-019.

## Decisiones transversales posteriores

### DEC-001 - Estilo de código y referencia a producción

Ver `docs/decisions/DEC-001-estilo-codigo-y-referencia-produccion.md`.

Obliga a todos los WPs de implementación a:

- escribir en español todos los identificadores propios bajo control del proyecto;
- documentar el código abundantemente en español con finalidad pedagógica;
- incluir en cada PR una explicación apta para principiantes;
- consultar la producción vigente como fallback solo ante ambigüedades de negocio, UX o diseño visual, nunca para decidir arquitectura o cuestiones técnicas.

### DEC-002 - Lanzador local de Work Packages

Ver `docs/decisions/DEC-002-lanzador-work-packages.md`.

Después de integrar WP-001, `scripts/iniciar_wp.py` continúa como lanzador genérico que valida autorización documental y prepara rama + worktree + CLI sin adquirir autoridad para aprobar, integrar o desplegar. DEC-007 agrega un lanzador específico para Orca y reemplaza la idea de un único lanzador preferido para todos los entornos.

### DEC-003 - Herramientas MCP estándar

Ver `docs/decisions/DEC-003-herramientas-mcp-agentes.md`.

Todos los WPs de implementación deben aplicar estas reglas:

- usar Context7 automáticamente cuando código/configuración dependa de documentación externa actual o específica de versión;
- preferir el MCP oficial de Nuxt para comportamiento específico de Nuxt cuando esté disponible;
- usar Playwright MCP como apoyo exploratorio sin sustituir tests Playwright versionados;
- usar GitHub MCP o integración equivalente únicamente dentro de la autoridad ya aprobada;
- comprobar razonablemente la disponibilidad de las herramientas antes de depender de ellas;
- **avisar explícitamente al operador si un MCP necesario no está disponible**;
- continuar sin él solo si existe un fallback claramente equivalente y seguro según DEC-003;
- no adivinar APIs/configuración cuando la consulta externa era necesaria;
- no versionar API keys, tokens ni configuraciones personales con secretos.

### DEC-004 - Orquestación, revisión secuencial y sincronización Git

Ver `docs/decisions/DEC-004-orquestacion-revision-secuencial-y-sincronizacion.md`.

Establece a ChatGPT Web como orquestador operativo preferido, revisión independiente secuencial en el worktree del WP y sincronización GitHub/local obligatoria en los puntos de control.

### DEC-005 - Planificación y autoridad documental del orquestador

Ver `docs/decisions/DEC-005-planificacion-y-autoridad-documental-del-orquestador.md`.

Con aprobación humana explícita, el orquestador puede mantener directamente en `main` la documentación canónica autorizada. Código, tests ejecutables, scripts, CI y demás cambios productivos siguen mediante rama + PR.

### DEC-007 - Entorno Orca, asignación flexible y lanzadores

Ver `docs/decisions/DEC-007-entorno-orca-asignacion-agentes-y-lanzadores.md`.

Obliga a:

- determinar o preguntar el entorno operativo antes de iniciar un WP;
- usar el lanzador Orca cuando Orca sea el entorno activo y el lanzador genérico en otros entornos;
- aceptar la rama nativa trazable administrada por Orca en lugar de renombrarla por detrás;
- asignar implementador por complejidad/riesgo/capacidad/disponibilidad-cuota en lugar de un agente universal predeterminado, incluyendo explícitamente Claude Code entre las alternativas soportadas;
- mantener revisión independiente por sesión/agente/modelo efectivo;
- limpiar worktree/rama usando el mecanismo correspondiente al entorno después del merge verificado.

### DEC-019 - CI proporcional y commits documentales

Ver `docs/decisions/DEC-019-ci-proporcional-y-commits-documentales.md`.

Obliga a interpretar «CI aplicable» de forma proporcional al tipo de cambio:

- toda PR y todo push material a `main` conserva CI completa;
- un push directo a `main` compuesto únicamente por `docs/**` y/o archivos `*.md` puede no generar run de Product y esa ausencia es esperada;
- un commit mixto o cualquier cambio en código, tests, scripts, CI, configuración, dependencias, assets binarios o despliegue sigue siendo material;
- modificar el workflow de CI requiere WP, rama, PR, revisión independiente y CI completa.

### DEC-017 - Coordinación mediante SIS-Leg-Control

Ver `docs/decisions/DEC-017-coordinacion-mediante-sis-leg-control.md`.

Obliga a:

- descubrir el turno y la asignación desde `martinebene/SIS-Leg-Control` antes de actuar;
- mantener al humano como compuerta entre turnos;
- usar `CURRENT.json` y la existencia del resultado esperado como regla de elegibilidad;
- impedir comunicación lateral IMPLEMENTER/REVIEWER;
- publicar handoffs append-only dirigidos al ORCHESTRATOR;
- usar `PROMPTS_AGENTES.md` como estándar de contenido de las asignaciones, no como transporte manual;
- detenerse de forma segura ante rol incorrecto, asignación consumida o estado ambiguo.

## Estilo obligatorio del código

### Identificadores propios en español

Todo identificador bajo control de SIS-Leg debe tener nombre semántico en español:

- funciones/métodos;
- clases;
- variables;
- constantes propias;
- tipos/interfaces propias;
- atributos/campos internos;
- helpers;
- tests y fixtures propios cuando corresponda.

Usar español **sin tildes ni `ñ`** en identificadores fuente y respetar las convenciones idiomáticas del lenguaje:

- Python: `snake_case` para funciones/variables y `PascalCase` para clases;
- TypeScript/Vue: `camelCase` para funciones/variables y `PascalCase` para clases/tipos/componentes cuando corresponda.

Ejemplos: `abrir_sesion`, `cantidad_presentes`, `EstadoVotacion`, `resultadoActual`, `useEstadoModeracion`.

No traducir nombres impuestos por el lenguaje, frameworks/librerías, hooks obligatorios, APIs externas, paquetes, comandos ni contratos técnicos canónicos cuando hacerlo rompa compatibilidad o contradiga decisiones previas.

### Comentarios pedagógicos abundantes

El código debe estar comentado y documentado en español con nivel apto para una persona que está aprendiendo Python, FastAPI, TypeScript, Vue y Nuxt.

Como mínimo:

- cada clase propia explica qué representa, su responsabilidad y relación con el sistema;
- cada función/método no trivial explica propósito, entradas, resultado, efectos laterales y errores relevantes;
- flujos no obvios de estado, concurrencia, SSE, reactividad, auditoría y sincronización deben explicarse paso a paso cuando ayude a comprenderlos;
- comentarios importantes deben explicar tanto **qué** ocurre como **por qué** se implementa de esa forma;
- tests no evidentes deben indicar qué regla o escenario demuestran.

No llenar el código con comentarios que solo repiten literalmente la sintaxis. El objetivo es enseñar y aclarar intención, flujo y decisiones.

Todo comentario debe mantenerse sincronizado con el código. Un comentario incorrecto o desactualizado es un defecto.

## Invariantes que no se pueden reinterpretar

- Estados globales: `SIN_PREPARAR`, `PREPARANDO`, `SESION_ABIERTA`.
- El estado operativo se mantiene en memoria y no se restaura después de una caída.
- Una interrupción técnica obliga a nueva preparación y nueva apertura reglamentaria.
- Una sola votación activa por vez.
- Mayoría simple y especial son tipos distintos.
- Mayoría simple: `positivos > negativos`; abstenciones fuera del cálculo; igualdad produce empate.
- Mayoría especial: factor explícito y base `PRESENTES` o `CUERPO`; igualdad exacta con factor aprueba (`>=`).
- En especial sobre presentes, la abstención forma parte de votos emitidos y del denominador.
- Si falta voto de algún presente al finalizar manualmente, la votación es `INCONCLUSA`.
- La pérdida de quórum durante votación la convierte inmediatamente en `INCONCLUSA`.
- Una votación cerrada nunca se recalcula.
- Un voto ordinario es irreversible y Moderación no puede modificarlo.
- Presidencia es rol independiente del rol Concejal; una persona puede ejercer ambos sin interferencia funcional.
- Presidencia desempata solo mayoría simple `EMPATADA`, desde Moderación, con voto positivo/negativo irreversible.
- Secretaría Legislativa es rol institucional sin acciones funcionales.
- Los votos individuales no se revelan en Recinto hasta cierre.
- El Orden del Día es opcional y asistencial.
- Toda interacción relevante desde `PREPARANDO` hasta cierre/cancelación se registra de inmediato en tres CSV jerárquicos.

## Dispositivos

Mapa funcional:

- `1`: voto positivo;
- `2`: abstención;
- `3`: voto negativo;
- `7`: pedir/retirar palabra; si habla, finalizar su uso;
- `8`: test visual;
- `9`: alternar presencia.

Durante `PREPARANDO` solo tienen efecto funcional `8` y `9`.

En `SIN_PREPARAR` ninguna pulsación produce efecto funcional ni pertenece a CSV de sesión.

### Remapeo rápido

```text
fingerprint físico -> device-bridge -> identificador lógico -> backend -> concejal
```

Ante falla, el bridge reasigna un nuevo fingerprint al **mismo identificador lógico**. No se cambia concejal, presencia, votos ni padrón. Puede ocurrir durante una votación y debe registrarse.

## Registros y auditoría

- Tres CSV por preparación/sesión.
- Fecha y hora de inicio en el nombre.
- L1 contiene L1+L2+L3; L2 contiene L2+L3; L3 contiene L3.
- Formato canónico: `seq;timestamp;level;tag;event_code;message`.
- Delimitador `;`, UTF-8 con BOM, hora local, precisión a segundos.
- Persistencia inmediata con `flush` + `fsync`.
- Si no puede garantizarse auditoría, no confirmar nuevas mutaciones como exitosas.
- Al cancelar preparación/cerrar sesión se escribe evento final y los archivos quedan cerrados.
- Ante caída abrupta, quedan hasta el último evento efectivamente persistido y no se reparan retrospectivamente.

## Autonomía y escalamiento

El agente puede resolver microdecisiones internas de código dentro del WP: nombres, helpers, módulos privados, algoritmos equivalentes, tests y refactors locales que no alteren comportamiento observable ni contratos, siempre respetando DEC-001 para nomenclatura en español y documentación pedagógica.

Debe escalar antes de:

- cambiar reglas de negocio o decisiones DT/DEC cerradas;
- modificar arquitectura o responsabilidades entre componentes;
- cambiar contratos públicos/API/DTO compartidos fuera de lo autorizado por el WP;
- cambiar formatos canónicos de configuración, padrón, Orden del Día o auditoría;
- agregar una dependencia directa nueva no prevista;
- introducir persistencia/recuperación, cambiar concurrencia, REST/SSE, secreto de votos o seguridad;
- cambiar stack, testing, CI, calidad o despliegue;
- ampliar el WP, modificar criterios de aceptación o documentación canónica para facilitar la implementación;
- relajar/eliminar tests o criterios para hacer pasar la CI.

Formato mínimo de escalamiento:

```text
Decisión requerida:
Motivo:
Alternativas:
Impacto:
Recomendación:
Alcance bloqueado:
```

Solo debe detenerse la parte dependiente de esa decisión; el trabajo independiente seguro puede continuar.

## Restricciones de implementación para agentes

- No trabajar fuera de un WP aprobado y registrado en PLAN.
- No iniciar un WP cuyas dependencias no estén satisfechas salvo autorización explícita documentada.
- No ampliar silenciosamente el WP asignado.
- No modificar decisiones cerradas por iniciativa propia.
- No introducir base de datos ni persistencia de sesión activa.
- No sustituir stack, transporte, testing, calidad o despliegue sin decisión documentada.
- No introducir autenticación de operador salvo decisión explícita.
- No sustituir CSV como registro institucional.
- No agregar edición/corrección de votos.
- No validar autoridad o contenido político/administrativo del Orden del Día.
- No conectar frontends directamente al device-bridge.
- No diseñar UI dependiente exclusivamente de 1920×1080.
- No ejecutar dos agentes sobre el mismo working tree, rama o WP.
- No integrar una PR sin CI aplicable verde y revisión independiente aprobatoria.
- No introducir identificadores propios nuevos en inglés sin una excepción real impuesta por framework, librería o contrato externo.
- No entregar código sustantivo sin comentarios/documentación pedagógica suficiente para comprender su intención y funcionamiento.
- No inventar reglas de negocio, UX o diseño visual: aplicar la jerarquía documental y el fallback a producción definido en DEC-001.
- No ocultar la ausencia de un MCP requerido: aplicar el aviso y fallback de DEC-003.
- No usar memoria del modelo como sustituto de documentación externa cuando DEC-003 exige verificar una API/configuración vigente.
- No ignorar DEC-007 al seleccionar entorno, rama/worktree, implementador o revisor.
- No ignorar DEC-017 ni ejecutar trabajo si `SIS-Leg-Control` no autoriza inequívocamente el rol/turno.
- No consumir informes privados del otro rol para eludir la mediación del ORCHESTRATOR.
- No cerrar una entrega sin evaluar el impacto sobre `manual/index.html` y sin dejar constancia
  de esa evaluación, actualice o no el manual.
- No versionar credenciales o secretos de MCP ni configuración personal de agentes/Orca.

Si aparece trabajo fuera de alcance, registrarlo en el WP/PR como hallazgo. Si aparece una decisión transversal nueva, detener solo el alcance afectado y elevarla para posible `DEC-XXX`.

## Calidad esperada

Cada cambio debe:

- corresponder al WP y a fuentes canónicas indicadas;
- cumplir criterios de aceptación;
- incluir pruebas proporcionales al riesgo;
- preservar invariantes;
- mantener backend/frontends desacoplados por contratos claros;
- evitar secretos y datos reales;
- mantener trazabilidad `requisito -> WP -> aceptación -> prueba -> PR`;
- utilizar español para el código propio bajo control del proyecto;
- incluir comentarios pedagógicos suficientes y actualizados;
- permitir que la PR explique la implementación a nivel principiante;
- utilizar documentación técnica externa actualizada cuando corresponda según DEC-003;
- hacer explícito cualquier fallback por MCP no disponible;
- respetar el entorno y la independencia de agentes definidos por DEC-007;
- dejar `manual/index.html` consistente con el cambio cuando sea relevante para usuario/soporte, o
  registrar explícitamente que se evaluó y no requiere actualización;
- respetar el turno, aislamiento y handoffs definidos por DEC-017 y `SIS-Leg-Control`.

Si aparece una contradicción real entre documentos, no adivinar: detener únicamente el alcance afectado y documentar la inconsistencia.

## Puerta propia del ORCHESTRATOR antes de integrar

Un veredicto REVIEWER `LISTA PARA INTEGRAR` y una CI verde **no autorizan por sí solos el merge**.

Cuando el control vuelve a ChatGPT Web, el ORCHESTRATOR debe reconstruir y auditar toda la cadena del WP antes de integrar: asignaciones, implementaciones, reviews, correcciones/re-revisiones, candidate SHA final, diff, CI, staleness, soft deviations y coherencia con WP/DEC/documentación.

Debe inspeccionar directamente el candidato final con acceso a GitHub y buscar activamente contradicciones o defectos razonables, aunque no pueda ejecutar pruebas localmente.

Sólo después de registrar un audit append-only `work-packages/WP-NNN/audits/pre-merge-XXX.md` con veredicto `APROBADO_PARA_MERGE` puede decidir el merge. Esta capa no reemplaza al REVIEWER: agrega una revisión de alto nivel por el ORCHESTRATOR.

