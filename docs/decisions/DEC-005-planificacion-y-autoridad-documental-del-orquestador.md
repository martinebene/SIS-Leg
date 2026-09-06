# DEC-005 - Planificación y autoridad documental del orquestador

## Estado

`APROBADA`

## Contexto

SIS-Leg utiliza una conversación de ChatGPT Web como orquestador operativo con acceso independiente al repositorio GitHub. DEC-004 formalizó ese rol para coordinación, verificación remota, sincronización y algunos cambios administrativos mínimos de `PLAN.md`.

Durante el inicio de la Fase 2 se decidió ampliar ese modelo: la misma conversación de orquestación será también la superficie principal de **planificación documental**. El objetivo es que los Work Packages y demás definiciones canónicas se elaboren junto con el operador humano antes de delegar implementación a agentes locales, aprovechando que el orquestador puede consultar directamente el repositorio, detectar decisiones reservadas por DT-038 y mantener continuidad entre planificación y ejecución.

Bajo la regla anterior, incluso una definición documental elaborada y aprobada conjuntamente por el operador y el orquestador debía atravesar una rama y una Pull Request para volver a ser aprobada por el mismo operador. Ese control sigue siendo valioso para trabajo producido por agentes implementadores o revisores, pero resulta redundante para documentación que se construye deliberadamente en la conversación de orquestación con aprobación humana explícita.

Esta decisión amplía de forma controlada la excepción de commits directos a `main`. No modifica las protecciones aplicables al código productivo, configuración ejecutable, CI, dependencias, testing ni despliegue.

## Decisión

### 1. ChatGPT Web asume también la planificación documental

La conversación de ChatGPT Web que actúa como orquestador es además el planificador documental preferido de la implementación.

Sus responsabilidades incluyen:

- reconstruir el estado vigente desde GitHub antes de planificar;
- identificar el próximo Work Package habilitado por `PLAN.md` y sus dependencias;
- leer únicamente las fuentes canónicas necesarias para delimitar ese WP;
- inspeccionar el código integrado previo cuando sea necesario para que el contrato sea implementable y no duplique responsabilidades;
- detectar contradicciones, ambigüedades y decisiones reservadas por DT-038;
- formular al operador humano las preguntas de definición realmente necesarias;
- proponer alternativas, impacto y recomendación cuando exista una decisión reservada;
- redactar y mantener `WP-XXX.md`, decisiones `DEC-XXX` y demás documentación canónica acordada;
- mantener la trazabilidad requisito -> WP -> criterios -> pruebas -> PR;
- no delegar implementación hasta que el WP aplicable esté documentalmente cerrado y aprobado.

Los agentes locales de implementación no deben reconstruir ni rediseñar el alcance que ya fue definido por el orquestador y aprobado por el operador. Conservan la autonomía técnica local establecida por DT-038.

### 2. Intercambio humano antes de cerrar decisiones reservadas

Cuando la planificación encuentre una cuestión reservada por DT-038, el orquestador no la decide silenciosamente.

Debe presentarla al operador con, como mínimo:

```text
Decisión requerida:
Motivo:
Alternativas:
Impacto:
Recomendación:
Alcance bloqueado:
```

El operador puede aprobar una alternativa, modificarla o pedir más análisis. Solo después de esa decisión humana el orquestador la incorpora como definición canónica.

No es necesario consultar al operador por microdecisiones internas que DT-038 ya deja bajo autonomía del futuro implementador.

### 3. Autoridad documental directa sobre `main`

Con autorización humana explícita en la conversación de orquestación, ChatGPT Web puede crear o modificar directamente en `main` documentación canónica acordada conjuntamente, sin rama ni Pull Request intermedia.

La excepción incluye los siguientes archivos documentales:

- `AGENTS.md`;
- `README.md` cuando el cambio sea exclusivamente documental;
- `docs/**/*.md`, incluyendo:
  - `docs/implementation/PLAN.md`;
  - `docs/implementation/ORQUESTACION.md`;
  - `docs/work-packages/WP-XXX.md`;
  - `docs/decisions/DEC-XXX-*.md`;
  - reglas, modelos, casos de uso, contratos y demás especificación Markdown del proyecto.

Esta autoridad permite, entre otras operaciones:

- crear un WP como `BORRADOR`;
- modificar su alcance y criterios durante la planificación con el operador;
- marcarlo `APROBADO` cuando exista aprobación humana explícita de su definición;
- crear o modificar una decisión canónica aprobada por el operador;
- mantener AGENTS y procedimientos de orquestación consistentes;
- actualizar `PLAN.md`, tanto para planificación como para transiciones operativas autorizadas.

La excepción pertenece exclusivamente al orquestador ChatGPT Web con acceso independiente a GitHub y aprobación humana. No se transfiere automáticamente a agentes locales, CLIs ni automatismos.

### 4. Límites estrictos de los commits directos

La autoridad documental directa **no permite** modificar en `main` sin rama + PR:

- código fuente;
- tests ejecutables;
- scripts;
- workflows o configuración de CI;
- archivos de configuración funcional o productiva como TOML, CSV o JSON;
- dependencias, manifiestos o lockfiles;
- configuración de tooling ejecutable;
- assets binarios;
- infraestructura o archivos ejecutables de despliegue;
- cualquier cambio que mezcle documentación con implementación productiva.

Tampoco permite al orquestador aprobar por sí mismo una decisión que DT-038 reserve al humano. La capacidad de escribir el archivo no reemplaza la autoridad humana sobre su contenido.

Si una modificación documental requiere necesariamente un cambio ejecutable para mantenerse coherente, el cambio documental puede registrarse directamente si ya está aprobado, pero la implementación ejecutable correspondiente continúa mediante WP/rama/PR y no se presenta como realizada hasta su integración.

### 5. Documentación producida por agentes locales

Cuando un agente implementador modifica documentación como parte de un WP de implementación, esos cambios forman parte de la rama y PR del WP normalmente.

El agente no debe usar esta excepción para escribir directamente en `main` ni pedir al operador que copie sus cambios documentales a `main` para eludir la revisión de la PR.

Si un agente detecta que hace falta cambiar una definición canónica fuera de su autoridad, registra y escala el hallazgo. El orquestador y el operador resuelven la definición documental por el flujo de esta decisión y la registran en `main`.

Si esa modificación afecta o resuelve una escalación de un WP que ya está `EN_CURSO`, antes de que el implementador continúe deben sincronizarse **tanto el checkout coordinador como el worktree activo del WP**. El worktree incorpora `origin/main` mediante merge normal, nunca rebase ni force-push, con árbol limpio y repetición posterior de las validaciones aplicables. Así el agente no continúa trabajando contra un WP, DEC u otra definición canónica que ya fue reemplazada en `main`.

### 6. Revisión de documentación elaborada por el orquestador

La documentación planificada y aprobada conjuntamente por el operador y ChatGPT Web no requiere por defecto una segunda revisión independiente ni una PR puramente burocrática.

El operador o el orquestador pueden solicitar revisión adicional cuando el riesgo o complejidad lo justifique, especialmente para decisiones arquitectónicas, contractuales o institucionales sensibles. Esa revisión es una salvaguarda opcional y no una puerta general obligatoria para los commits documentales directos autorizados por esta decisión.

La revisión independiente obligatoria de DT-037 se mantiene para las Pull Requests de implementación y para otros cambios ejecutables o sustantivos que no estén dentro de esta excepción documental.

### 7. Puerta de seguridad antes de cada commit documental directo

Antes de escribir directamente en `main`, el orquestador debe:

1. consultar GitHub y confirmar el HEAD actual de `main`;
2. verificar que el cambio es exclusivamente documental y está dentro de las rutas permitidas;
3. confirmar que el contenido refleja una definición ya acordada o una autorización humana explícita de modificarla;
4. evitar incluir cambios no discutidos o decisiones reservadas no aprobadas;
5. realizar el commit con mensaje descriptivo y conservar su SHA;
6. volver a verificar el HEAD remoto resultante;
7. verificar la CI de `main` aplicable cuando exista;
8. no habilitar trabajo dependiente si esa CI falla;
9. indicar al operador que sincronice el checkout coordinador mediante fast-forward antes de ejecutar trabajo local dependiente;
10. si el cambio afecta un WP `EN_CURSO`, exigir además que su worktree limpio ejecute `git fetch origin` y `git merge origin/main` antes de reanudar la implementación.

Si `main` avanza entre la lectura y la escritura y el cambio puede quedar obsoleto o conflictivo, el orquestador debe volver a leer el estado vigente antes de insistir.

### 8. Flujo canónico de planificación e implementación

El ciclo preferido pasa a ser:

```text
ChatGPT Web orquestador
  -> reconstruye estado desde GitHub
  -> identifica próximo WP habilitado
  -> carga fuentes canónicas necesarias
  -> planifica el WP con el operador
  -> escala y resuelve con el humano decisiones DT-038
  -> actualiza directamente documentación canónica en main
  -> verifica SHA/CI y sincronización local
  -> si existe WP EN_CURSO afectado, sincroniza también su worktree con origin/main
  -> WP queda APROBADO
  -> con autorización humana, PLAN pasa a EN_CURSO y se asigna implementador
  -> operador ejecuta scripts/iniciar_wp.py
  -> agente local implementa en rama + worktree del WP
  -> candidato se sincroniza con origin/main
  -> validaciones + push + PR
  -> revisión independiente secuencial
  -> correcciones por el implementador cuando corresponda
  -> orquestador verifica SHA + CI + revisión
  -> squash merge productivo
  -> orquestador actualiza documentación administrativa necesaria en main
  -> sincronización y limpieza
  -> siguiente planificación
```

La planificación documental ocurre **antes** de consumir capacidad de los agentes de implementación.

## Relación con decisiones anteriores

### DEC-004

DEC-004 continúa vigente para:

- ChatGPT Web como orquestador operativo;
- un worktree por WP usado secuencialmente por implementador y revisor;
- sincronización GitHub/local;
- puertas de revisión e integración;
- squash merge productivo.

La sección de DEC-004 que limitaba los commits directos del orquestador exclusivamente a operaciones administrativas de `PLAN.md` queda **ampliada y reemplazada** por las secciones 3 a 7 de DEC-005.

### DT-033

Se mantiene rama + PR para toda implementación productiva y para cambios no documentales. La prohibición general de commits directos a `main` recibe la excepción documental específica definida por DEC-005.

### DT-035

Se mantiene la estructura documental canónica. Se precisa que su planificación y mantenimiento pueden realizarse directamente por el orquestador en `main` bajo aprobación humana.

### DT-036

Se mantiene la separación de roles de implementación y revisión. Se agrega explícitamente que ChatGPT Web concentra planificación documental antes de delegar trabajo local.

### DT-037

La revisión independiente obligatoria continúa aplicando a PRs de implementación. No se exige una segunda revisión por defecto para documentación creada y aprobada conjuntamente por operador + orquestador bajo DEC-005.

### DT-038

No cambia la distribución de autoridad sustantiva. Las decisiones reservadas siguen requiriendo aprobación humana. DEC-005 modifica el **mecanismo de registro** de esas decisiones, no quién tiene autoridad para tomarlas.

## Alternativas consideradas

### Mantener PR para toda modificación documental

Se descarta para trabajo producido conjuntamente por el operador y el orquestador porque agrega una segunda aprobación manual sin aumentar materialmente el control.

### Permitir commits directos a cualquier archivo desde ChatGPT Web

Se rechaza. El beneficio buscado es reducir burocracia de planificación/documentación, no eliminar las protecciones de implementación, CI y revisión independiente.

### Delegar la planificación de WPs a los implementadores

Se descarta como flujo normal. Mezcla definición de alcance con ejecución, consume capacidad de agentes destinada a codificación y aumenta el riesgo de que el implementador resuelva unilateralmente decisiones reservadas.

## Consecuencias

- ChatGPT Web concentra orquestación y planificación documental.
- Los WPs se definen y aprueban antes de lanzar agentes de implementación.
- Se reducen PRs documentales cuya única aprobación real sería la del mismo operador que participó en la definición.
- Las decisiones DT-038 siguen siendo humanas y explícitas.
- Los agentes locales reciben contratos más cerrados y consumen su capacidad principalmente en implementación/revisión.
- Código, configuración ejecutable, CI, dependencias, testing y despliegue conservan rama + PR + controles existentes.
- Después de cada cambio documental directo sigue siendo obligatoria la sincronización del clon coordinador antes de trabajo dependiente y, cuando el cambio afecta un WP `EN_CURSO`, también la sincronización de su worktree activo con `origin/main`.

## Documentos y WPs afectados

- `AGENTS.md`;
- `docs/14-gobernanza-agentes.md`;
- `docs/decisions/DEC-004-orquestacion-revision-secuencial-y-sincronizacion.md`, precisada/superada parcialmente;
- `docs/implementation/ORQUESTACION.md`;
- `docs/implementation/PLAN.md`;
- todos los `docs/work-packages/WP-XXX.md` futuros;
- futuras decisiones `DEC-XXX`;
- todos los WPs posteriores en su fase de planificación y autorización.
