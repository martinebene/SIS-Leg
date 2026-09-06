# DEC-007 - Entorno Orca, asignación flexible de agentes y lanzadores por entorno

## Estado

`APROBADA`

## Contexto

SIS-Leg comenzó su implementación con un flujo local genérico pensado para terminales administradas manualmente. `DEC-002` estableció `scripts/iniciar_wp.py` para validar autorización, sincronizar `main`, crear rama/worktree y abrir directamente una CLI de agente. `DT-036` estableció además a Codex como implementador predeterminado, permitiendo otras herramientas por capacidad, disponibilidad o cuota.

El entorno operativo principal cambió posteriormente a **Orca**, utilizando un cliente conectado a un runtime `orca serve` en el entorno de desarrollo remoto. En este modo, crear un worktree con Git y lanzar el agente fuera de Orca obliga a importar/reabrir después ese trabajo para que Orca pueda administrar correctamente terminal, sesión, estado, notificaciones y demás integración del agente.

El 20 de agosto de 2026 se verificó empíricamente sobre el runtime Orca disponible que:

- el repositorio `SIS-Leg` está registrado nativamente en Orca;
- `orca worktree create` admite `--repo`, `--name`, `--base-branch`, `--agent`, `--prompt`, `--setup`, `--no-parent`, `--activate` y salida `--json`;
- un worktree creado desde `origin/main` parte exactamente del SHA solicitado y queda registrado por Orca;
- Orca genera una rama local propia derivada del nombre del workspace; en el entorno probado adoptó la forma `<git-username>/wp-NNN-descripcion`;
- `orca worktree rm` elimina de forma normal el worktree Orca y su rama local cuando el árbol está limpio;
- Antigravity/AGY, Codex, OpenCode y Claude Code están disponibles como arneses admitidos por el flujo Orca; los hooks/skills de integración se mantienen según las capacidades de cada agente.

También se decidió administrar con mayor cuidado la capacidad/cuota de los agentes. La oferta de modelos, sus capacidades relativas, los límites de suscripciones y las cuotas disponibles cambian con suficiente frecuencia como para que una pareja fija implementador/revisor se vuelva obsoleta rápidamente. Por eso la selección debe resolverse para cada WP con información operativa vigente.

Esta decisión modifica reglas operativas de DT-033, DT-036 y DEC-002, sin alterar arquitectura ni reglas funcionales del producto.

## Decisión

### 1. El orquestador debe conocer el entorno operativo actual

Antes de iniciar un WP, el orquestador debe determinar qué entorno de ejecución está utilizando el operador.

- Si el entorno está explícito en la conversación o en el estado operativo vigente, se utiliza ese entorno.
- Si no puede determinarse con seguridad, el orquestador debe preguntarlo antes de entregar el comando de inicio.
- No debe seguir recomendando un entorno antiguo únicamente porque aparezca en documentación histórica.

Mientras el operador trabaje mediante Orca Server, **Orca es el entorno operativo preferido** para iniciar y administrar WPs. Esta preferencia es operacional y puede cambiar sin modificar la arquitectura del producto.

### 2. Se mantienen lanzadores diferentes según el entorno

`scripts/iniciar_wp.py` se conserva como lanzador **genérico** para terminal, SSH, Warp u otros entornos donde corresponda crear el worktree mediante Git y abrir directamente la CLI del agente.

Se incorporará un segundo lanzador:

```text
scripts/iniciar_wp_orca.py
```

Su responsabilidad será aplicar las mismas puertas de seguridad documentales/Git y delegar en la CLI de Orca la creación del worktree y el lanzamiento del agente.

Los dos lanzadores deben reutilizar una misma lógica de validación en la medida razonable para evitar que las reglas de autorización diverjan.

### 3. Validaciones obligatorias antes de crear un WP

Independientemente del entorno, antes de crear/reutilizar un worktree deben verificarse como mínimo:

1. ejecución desde el checkout coordinador correcto;
2. rama local `main`;
3. árbol local limpio;
4. `git fetch --prune origin`;
5. actualización de `main` únicamente mediante fast-forward;
6. `HEAD` local idéntico a `origin/main`;
7. existencia de `docs/work-packages/WP-NNN.md`;
8. estado documental `APROBADO`;
9. WP `EN_CURSO` en `PLAN.md`;
10. agente solicitado igual al agente asignado;
11. dependencias del WP en estado `INTEGRADO`;
12. ausencia de un conflicto de rama/worktree que pueda ocultar o sobrescribir trabajo.

Ningún lanzador adquiere autoridad para aprobar WPs, cambiar el PLAN, integrar PRs o resolver contradicciones documentales.

### 4. Flujo específico de Orca

Después de las validaciones anteriores, el lanzador Orca debe verificar además:

- runtime Orca alcanzable y en estado `ready`;
- repositorio coordinador registrado en Orca;
- disponibilidad razonable del agente solicitado.

El flujo conceptual normal será equivalente a:

```text
orca worktree create
  --repo path:<checkout-coordinador>
  --name wp/NNN-descripcion
  --base-branch origin/main
  --no-parent
  --agent <id-orca>
  --setup run
  --activate
  --json
```

A partir de WP-031, el comando conserva `--agent` pero no pasa `--prompt`: el launcher no genera ni transporta texto de trabajo. El prompt exhaustivo es redactado por ChatGPT Web/orquestador y trasladado manualmente por el operador (copia y pega) a la terminal del agente tras el lanzamiento.

El lanzador debe interpretar la respuesta JSON y comprobar al menos que:

- el worktree fue creado por Orca;
- el `head` coincide con el SHA de `origin/main` previamente validado;
- la base corresponde a `origin/main`;
- no se creó una relación padre/hijo con otro WP cuando el trabajo es independiente;
- el agente fue lanzado o existe evidencia suficiente de su terminal según las capacidades de la versión de Orca utilizada.

Ante una respuesta parcial, inconsistente o un fallo cuyo efecto sea incierto, el lanzador **no debe borrar ni reparar automáticamente** el worktree. Debe informar el estado disponible para diagnóstico.

### 5. Convención de ramas compatible con Orca

Se mantiene el principio de **una rama corta e inequívoca por WP**, pero deja de exigirse una única forma literal para todos los entornos.

- Lanzador genérico: convención `wp/NNN-descripcion-corta`.
- Orca: se acepta la rama nativa generada por Orca a partir del workspace canónico `wp/NNN-descripcion-corta`, incluida una forma como `<git-username>/wp-NNN-descripcion-corta`.

Para una rama Orca son obligatorias estas propiedades:

- identificar inequívocamente el número del WP;
- nacer del `origin/main` validado;
- pertenecer a un único worktree/WP;
- terminar en una PR contra `main`;
- eliminarse después de la integración y verificaciones de cierre.

No se renombra por detrás una rama administrada por Orca únicamente para forzar la convención del lanzador genérico.

Esta regla precisa y reemplaza, para worktrees Orca, la forma literal única indicada originalmente por DT-033.

### 6. Asignación dinámica de implementador y revisor por WP

Deja de existir un **implementador universal predeterminado** y tampoco se fija una pareja permanente implementador/revisor. La frase de DT-036 que declara a Codex como implementador predeterminado queda reemplazada por esta política.

Antes de iniciar cada WP, ChatGPT Web/orquestador debe consultar al operador el estado operativo vigente de los agentes y modelos que tenga a disposición, incluyendo cuando sea relevante:

- agentes/arneses disponibles;
- modelos efectivos disponibles en cada uno;
- cuota o capacidad remanente de las suscripciones;
- restricciones temporales, costes o límites que hagan conveniente reservar capacidad.

Con esos datos, el orquestador evalúa el WP y propone al operador **tanto el implementador como el revisor independiente previsto**. La elección se acuerda explícitamente antes del lanzamiento del implementador.

La recomendación debe considerar en conjunto:

- complejidad y sensibilidad del cambio;
- necesidad de razonamiento transversal;
- riesgo sobre estados, concurrencia, auditoría, seguridad o contratos;
- desempeño observado de agentes/modelos disponibles;
- capacidad relativa de los modelos disponibles en ese momento;
- disponibilidad y cuota/coste operativo;
- integración de cada agente con el entorno actual;
- independencia razonable entre implementador y revisor, prefiriendo familias de modelo distintas.

Los modelos y sus capacidades cambian durante la vida del proyecto. Por ello:

- la documentación canónica **no fija modelos concretos como elección obligatoria**;
- no se asume que la pareja usada en un WP seguirá siendo óptima para el siguiente;
- el orquestador puede sugerir una combinación basándose en experiencia previa, pero debe volver a consultar disponibilidad/cuotas para el nuevo WP;
- la pareja prevista puede reconsiderarse antes de comenzar la revisión si cambió materialmente la disponibilidad, cuota o capacidad, siempre conservando independencia y dejando claro el cambio al operador;
- reducir consumo de una suscripción es un criterio operativo válido, pero nunca habilita a reducir alcance, pruebas, calidad ni profundidad de revisión.

El implementador finalmente autorizado se registra en `PLAN.md` según el flujo vigente. El revisor es una asignación operativa de revisión y no requiere agregar una columna fija al PLAN.

El modelo efectivo utilizado por implementador y revisor debe registrarse en la PR/informe cuando sea relevante para trazabilidad e independencia.

A agosto de 2026, Claude Code con Claude Opus 5 forma parte de las alternativas operativas disponibles del entorno. Esta mención registra capacidad actual para la selección del ORCHESTRATOR; no convierte a Opus 5 en modelo obligatorio ni reemplaza la evaluación dinámica por WP.

### 7. Revisión independiente

DT-037 continúa vigente: implementador y revisor deben ser sesiones/agentes independientes y se prefiere una familia de modelo diferente.

La selección concreta del revisor se rige por la evaluación dinámica del punto anterior, no por una preferencia permanente por un arnés o proveedor específico.

Antes de iniciar efectivamente la revisión, el orquestador puede reconfirmar con el operador que el revisor previsto sigue siendo adecuado según disponibilidad y cuota actuales. Si se cambia, debe acordarse la nueva elección antes de lanzar la sesión revisora.

Cambiar solamente de arnés manteniendo el mismo modelo efectivo no satisface por sí mismo la independencia.

El revisor permanece en modo solo lectura y las correcciones vuelven al implementador original.

Adicionalmente, conforme a WP-031, cuando OpenCode actúe bajo Orca (sea como implementador o revisor), el prompt preparado por el orquestador incluye una instrucción condicional para espejar la respuesta final en un archivo temporal fuera del repositorio y abrir una terminal común mediante la CLI y la skill `orca-cli` ejecutando `cat` sobre dicho archivo, facilitando el copiado limpio de su informe final desde clientes con limitaciones de TUI.

### 8. Limpieza posterior según el entorno

Después de un squash merge verificado y con el worktree limpio:

- si el worktree fue administrado por Orca, **se elimina primero mediante `orca worktree rm`**, para que Orca retire coordinadamente su metadata, el worktree Git y la rama local asociada;
- antes del `rm`, se obtiene el worktree real mediante `orca worktree list --repo path:<checkout-coordinador> --json`;
- `orca worktree rm --worktree` debe recibir un **selector explícito válido**; se prefiere `id:<id-exacto-devuelto-por-orca>` por ser inequívoco;
- también pueden usarse selectores explícitos como `path:<ruta-absoluta>` o `name:<nombre>` si la versión vigente los soporta y el valor fue previamente verificado;
- no se pasa el nombre visible del workspace desnudo, por ejemplo `--worktree "wp/007-descripcion"`, porque no constituye por sí mismo un selector y puede devolver `selector_not_found` sin eliminar nada;
- ante `selector_not_found`, se vuelve a listar Orca y se reintenta únicamente con un selector explícito verificado; nunca se asume que el worktree fue retirado;
- después de `orca worktree rm` se verifican tanto `orca worktree list ... --json` como `git worktree list` antes de efectuar limpiezas manuales;
- en el flujo Orca normal la rama local asociada desaparece con el worktree; solo si permanece, y una vez verificada la integración y ausencia de trabajo posterior, puede limpiarse manualmente conforme a `ORQUESTACION.md`;
- después se elimina explícitamente la rama remota publicada para la PR y se ejecuta `git fetch --prune`;
- en un entorno genérico se utiliza la limpieza Git documentada en `ORQUESTACION.md`;
- en ambos casos se comprueba que no quede trabajo posterior no integrado.

Comando preferido conceptual en Orca:

```text
orca worktree rm
  --worktree id:<id-exacto-devuelto-por-orca>
  --json
```

Nunca se usa eliminación forzada para descartar trabajo no investigado. `--force` en Orca solo puede considerarse ante una causa diagnosticada y autorizada, no como respuesta automática a un selector inválido o a un worktree que no pudo retirarse normalmente.

### 9. Bootstrap del lanzador Orca

La implementación de `scripts/iniciar_wp_orca.py` se realizará en un WP de tooling separado de los WPs funcionales.

Ese WP constituye una excepción de bootstrap: como todavía no existe el lanzador Orca, puede iniciarse mediante `orca worktree create` ejecutado manualmente **después de reproducir las mismas validaciones obligatorias** de esta decisión.

Una vez integrado el lanzador Orca, los nuevos WPs iniciados mientras Orca sea el entorno activo deberán preferirlo en lugar de crear/importar worktrees externamente.

## Alternativas consideradas

### Sustituir completamente `scripts/iniciar_wp.py`

Se descarta. El lanzador genérico sigue siendo útil si el operador vuelve a Warp, SSH directo u otro entorno sin Orca.

### Seguir creando worktrees con Git e importarlos después en Orca

Se descarta como flujo normal porque agrega fricción y hace que el agente nazca fuera de la administración de Orca.

### Renombrar manualmente las ramas creadas por Orca

Se descarta por defecto. No aporta una garantía funcional adicional y puede introducir discrepancias entre metadata Orca y Git.

### Reservar siempre un agente o modelo concreto

Se descarta. La herramienta y el modelo deben elegirse por adecuación al WP, riesgo, capacidad disponible, independencia de revisión y coste/cuota vigentes, manteniendo siempre las mismas fuentes y criterios de aceptación.

## Consecuencias

- Orca puede administrar worktree, terminal, agente, estado y notificaciones desde el nacimiento del WP.
- Se eliminan los pasos de cerrar/importar/reabrir agentes creados externamente.
- Se conservan todas las puertas de seguridad del lanzador original.
- El flujo continúa funcionando fuera de Orca mediante el lanzador genérico.
- La convención de ramas pasa a ser semántica y trazable, no dependiente de una única forma literal.
- La selección de implementador y revisor se adapta a la complejidad real del WP y al estado vigente de modelos, cuotas y suscripciones.
- La documentación no queda atada a una generación concreta de modelos ni a una pareja fija de proveedores.
- Se conserva la independencia de revisión sin desperdiciar innecesariamente capacidad escasa o costosa.

## Documentos y WPs afectados

- `docs/14-gobernanza-agentes.md`, precisado por esta decisión;
- `docs/decisions/DEC-002-lanzador-work-packages.md`, complementado y parcialmente reemplazado en selección de entorno/lanzador;
- `docs/decisions/DEC-004-orquestacion-revision-secuencial-y-sincronizacion.md`, complementado en operación bajo Orca;
- `docs/implementation/ORQUESTACION.md`;
- `docs/implementation/PLAN.md`;
- `AGENTS.md` y `docs/work-packages/TEMPLATE.md` cuando se sincronicen sus resúmenes operativos;
- el WP de tooling que implemente el lanzador Orca;
- todos los WPs posteriores en selección de implementador, revisor, inicio y limpieza.