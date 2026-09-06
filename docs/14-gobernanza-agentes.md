# 14 - Gobernanza del trabajo con agentes

Este documento registra las decisiones cerradas sobre ramas, unidades de trabajo, documentación operativa, herramientas agénticas, revisión y autoridad de cambios.

Las decisiones técnicas DT-001 a DT-038 están cerradas. Cualquier decisión transversal nueva que aparezca durante la implementación se gestiona mediante la política `DEC-XXX` definida aquí y en `docs/decisions/README.md`.

## DT-033 - Modelo de ramas

SIS-Leg utilizará un modelo **trunk-based simple** con `main` como única rama estable de integración.

### Reglas

- `main` debe mantenerse siempre integrable.
- No se permiten commits directos a `main` durante la implementación productiva.
- Cada **Work Package (WP)** se implementa en una rama corta propia.
- Convención inicial de ramas: `wp/NNN-descripcion-corta`.
- Cada rama nace desde `main` actualizado.
- Un agente trabaja exclusivamente sobre el WP que tenga asignado.
- No se permite que dos agentes implementen simultáneamente sobre la misma rama.
- Todo cambio de producto entra mediante Pull Request.
- La CI definida para el alcance debe estar verde antes de integrar.
- La revisión independiente definida en DT-037 debe estar completada antes de integrar una PR de implementación.
- El merge se realiza mediante **squash merge**, dejando un único commit final trazable al WP.
- El título del PR y el commit resultante deben incluir el identificador del WP.
- Después del merge se elimina la rama de trabajo.
- Las versiones desplegables se identifican posteriormente mediante tags/releases.

### No adoptar

No se utilizará GitFlow, una rama `develop` permanente ni ramas de integración largas. La coordinación se hace mediante WPs pequeños y PRs cortas contra `main`.

## DT-034 - Tamaño de los Work Packages

Los WPs serán **pequeños y orientados a un resultado verificable**, no a una cantidad arbitraria de líneas, archivos o tiempo.

### Cada WP debe contener

- un único objetivo principal;
- alcance explícito;
- exclusiones claras;
- dependencias previas;
- componentes/áreas previsiblemente afectadas;
- criterios de aceptación verificables;
- pruebas que deben pasar;
- documentación que deba actualizarse;
- ninguna decisión arquitectónica o reglamentaria abierta necesaria para completar el alcance.

### Regla de división

Un WP debe poder ser comprendido y revisado por un agente implementador y un agente revisor sin necesidad de cargar innecesariamente todo el proyecto.

Debe dividirse cuando aparezca cualquiera de estas señales:

- más de un objetivo funcional independiente;
- cambios grandes simultáneos en backend, ambos frontends y bridge sin necesidad atómica;
- demasiados criterios de aceptación independientes;
- una parte pueda integrarse y probarse de forma autónoma;
- la revisión requiera reconstruir demasiado contexto no relacionado.

No se impondrán límites rígidos de líneas o cantidad de archivos.

### Dependencias

Los WPs pueden declarar dependencias explícitas entre sí. Un WP dependiente no debe comenzar sobre supuestos de otro WP todavía no integrado salvo que el plan de trabajo lo autorice expresamente.

### Una PR por WP

Cada WP termina en una única Pull Request.

Si durante la implementación aparece trabajo necesario pero fuera del alcance aprobado:

- el agente no lo incorpora silenciosamente;
- lo registra como hallazgo o candidato a un WP separado;
- solo modifica el alcance si existe una decisión humana/documentada que lo autorice.

## DT-035 - Documentación operativa para agentes

La implementación se coordinará mediante una estructura documental **explícita pero liviana**. No se mantendrán matrices o documentos redundantes sin una necesidad concreta.

### Artefactos canónicos

```text
docs/
├── implementation/
│   └── PLAN.md
├── work-packages/
│   ├── TEMPLATE.md
│   ├── WP-001.md
│   └── ...
└── decisions/
    ├── README.md
    └── DEC-NNN-....md

.github/
└── pull_request_template.md

manual/
└── index.html
```

`manual/index.html` no es documentación interna para agentes: es el manual de usuario y soporte
publicado con la release. Aparece aquí porque su actualización forma parte del contrato de entrega
de cualquier WP que afecte lo que una persona usuaria o de soporte necesita saber.

### `docs/implementation/PLAN.md`

Es el mapa de implementación. Debe contener:

- secuencia de WPs;
- dependencias;
- objetivo breve;
- estado `PENDIENTE`, `EN_CURSO`, `INTEGRADO` o `BLOQUEADO`;
- agente/herramienta asignado cuando un WP esté en ejecución.

No debe duplicar reglas de negocio ni diseño técnico ya documentado.

### `docs/work-packages/WP-XXX.md`

Cada WP es el contrato operativo de trabajo del agente. Debe declarar como mínimo:

- identificador y título;
- objetivo;
- resultado esperado;
- dependencias;
- **fuentes canónicas obligatorias y secciones propietarias del alcance**;
- alcance;
- fuera de alcance;
- componentes previsiblemente afectados;
- criterios de aceptación;
- pruebas obligatorias;
- invariantes/restricciones;
- documentación a actualizar;
- **impacto sobre el manual de usuario y soporte**;
- hallazgos fuera de alcance;
- decisiones que requieran escalamiento;
- checklist de entrega.

`docs/work-packages/TEMPLATE.md` es la plantilla inicial obligatoria.

### Manual de usuario y soporte

`manual/index.html` es el manual único de operación, configuración, instalación, diagnóstico y
soporte del sistema. Se mantiene con el mismo criterio de vigencia que la documentación canónica:
un manual desactualizado es un defecto de la entrega, no una tarea pendiente difusa.

Regla permanente de evaluación de impacto, obligatoria para todo WP y para todo cambio autorizado:

1. la entrega evalúa explícitamente si el cambio necesita ser explicado a la persona usuaria o al
   soporte técnico;
2. si necesita explicarse, `manual/index.html` se actualiza dentro del mismo WP/PR o cambio
   autorizado;
3. si no necesita explicarse, la entrega registra de forma explícita que el impacto fue evaluado y
   no requiere actualización.

Qué cuenta como impacto relevante:

- funciones nuevas visibles para quien usa u opera el sistema;
- cambios de comportamiento observable, flujo de operación o resultados;
- cambios de configuración, padrón, instalación, empaquetado o despliegue que alguien deba aplicar;
- cambios de diagnóstico, mensajes de error o procedimientos de soporte;
- textos, rótulos o identidad visible que el manual describa literalmente.

Qué **no** obliga a tocar el manual:

- refactors internos sin efecto observable;
- nombres de módulos, helpers o fixtures;
- estructura de pruebas o de tooling de desarrollo;
- detalles de implementación sin utilidad para usuario o soporte.

La decisión es de criterio humano/agéntico y queda registrada. No se introduce automatización que
decida semánticamente por sí sola si el manual necesita cambios; el tooling sólo puede exigir que
la evaluación esté declarada.

Esta regla no modifica DEC-005 ni DEC-019. Un cambio puramente documental autorizado sigue el
mecanismo de DEC-005, y qué eventos disparan CI sigue determinándose exclusivamente por DEC-019.

### Lectura de contexto por agentes

Para un WP normal, el agente no debe cargar de forma indiscriminada toda la documentación del proyecto.

Orden normal:

1. `AGENTS.md`;
2. el `WP-XXX.md` asignado;
3. únicamente las fuentes canónicas y secciones indicadas por ese WP;
4. código/contratos directamente necesarios para el alcance.

Un agente de planificación, auditoría global o resolución de una contradicción puede necesitar un contexto documental más amplio.

### Decisiones `DEC-XXX`

`docs/decisions/` se reserva para decisiones nuevas que aparezcan durante la implementación y que tengan consecuencias arquitectónicas, contractuales o transversales relevantes.

No se creará un DEC para cada detalle local de implementación.

Un DEC corresponde cuando la decisión, por ejemplo:

- afecta a más de un WP/componente;
- modifica una decisión técnica ya aprobada;
- establece un contrato global nuevo;
- presenta alternativas relevantes con consecuencias futuras;
- requiere aprobación humana antes de continuar.

La política detallada está en `docs/decisions/README.md`.

### Trazabilidad

La trazabilidad principal se mantiene dentro del propio flujo:

```text
regla/requisito -> WP -> criterio de aceptación -> prueba -> PR
```

No se mantendrá inicialmente una matriz global duplicada. Puede agregarse más adelante si el volumen del proyecto la vuelve útil.

### Pull Requests

`.github/pull_request_template.md` exige como mínimo:

- WP implementado;
- agente/herramienta que lo implementó;
- qué cambió;
- qué explícitamente no cambió;
- criterios de aceptación;
- pruebas ejecutadas;
- estado de CI;
- documentación actualizada;
- resultado de la evaluación de impacto sobre `manual/index.html`;
- decisiones/desviaciones;
- hallazgos fuera de alcance;
- riesgos pendientes;
- evidencia de revisión independiente cuando corresponda.

El prompt entregado a un agente puede aportar instrucciones de ejecución, pero **no reemplaza el WP documentado como fuente canónica del alcance**.

## DT-036 - Estrategia multiagente y herramientas

La gobernanza se define por **roles y responsabilidades**, no por una herramienta o modelo concreto.

### Roles

#### Planificación y autoridad documental

La planificación, creación/modificación de WPs, mantenimiento de `PLAN.md` y aprobación de decisiones canónicas se realiza bajo control humano mediante las herramientas de planificación/documentación disponibles.

El agente implementador no redefine unilateralmente su propio alcance ni convierte una decisión abierta en una decisión aprobada.

#### Implementación

Cada WP tiene un único agente implementador responsable.

- **Codex** es el implementador predeterminado.
- **Claude Code** u **OpenCode** pueden ejecutar un WP cuando convenga por capacidad, disponibilidad, cuota o naturaleza de la tarea.
- El WP debe permanecer agnóstico respecto de la herramienta concreta: las mismas fuentes, alcance, criterios y pruebas rigen para cualquier implementador.
- No se fijarán modelos/versiones concretas en la documentación canónica porque cambian con mayor frecuencia que la arquitectura del proyecto.
- La PR debe registrar qué herramienta/agente ejecutó realmente el WP.

OpenCode se considera un arnés multiproveedor; la independencia de una revisión se evalúa por el agente/modelo efectivo utilizado, no por el nombre de la aplicación contenedora.

#### Revisión

La herramienta de revisión puede ser Codex, Claude Code, OpenCode con otro modelo u otra capacidad equivalente, siempre que cumpla DT-037.

### Aislamiento obligatorio de trabajo

Dos agentes pueden trabajar en paralelo únicamente sobre WPs independientes y autorizados por `PLAN.md`.

Cada WP en ejecución debe usar:

- rama propia `wp/NNN-descripcion-corta`;
- **`git worktree` propio**;
- sesión de agente propia;
- WP propio.

Está prohibido que dos agentes editen simultáneamente el mismo working tree, la misma rama o el mismo WP.

Si aparece una dependencia no prevista o una superposición importante de archivos/contratos, los WPs se serializan o se replantea el PLAN.

### Registro en PLAN

`PLAN.md` debe permitir registrar agente/herramienta asignado para cada WP en ejecución. El nombre del agente es información operativa, no una decisión arquitectónica permanente.

### Archivos de instrucciones por herramienta

`AGENTS.md` es la fuente común de instrucciones para agentes. Cuando una herramienta requiera su propio archivo de entrada, este debe ser mínimo y remitir a `AGENTS.md` en lugar de duplicar reglas.

### Automatización agéntica

En la primera etapa no se incorporarán agentes generativos que modifiquen automáticamente PRs desde GitHub Actions. La CI será determinista y la invocación de agentes para implementar o revisar será deliberada y trazable.

## DT-037 - Revisión independiente obligatoria

Toda Pull Request de implementación debe recibir una **revisión independiente** antes de integrarse.

### Independencia

- El revisor no puede ser la misma sesión/agente que implementó el WP.
- Se prefiere utilizar una **familia de modelo diferente** de la utilizada por el implementador.
- Ejemplos preferidos: Codex implementa → Claude revisa; Claude implementa → Codex revisa.
- OpenCode cuenta como herramienta independiente solo si el modelo/agente efectivo usado para revisar es diferente del implementador.
- Cambiar únicamente de aplicación o arnés manteniendo el mismo modelo no constituye por sí solo una revisión independiente suficiente.

La independencia se evalúa por el agente/modelo efectivo y la sesión de trabajo, no por el nombre comercial del cliente utilizado.

### Modalidad de revisión

El revisor actúa en **modo de solo lectura** sobre el alcance revisado. No implementa correcciones directamente en la rama del WP.

Debe reconstruir el contexto desde:

1. `AGENTS.md`;
2. el `WP-XXX.md` correspondiente;
3. las fuentes canónicas indicadas por el WP;
4. el diff completo entre `main` y la rama/PR;
5. las pruebas agregadas o modificadas;
6. los resultados de CI disponibles.

### Alcance mínimo de la revisión

Debe evaluar, según corresponda:

- cumplimiento exacto del objetivo, alcance y exclusiones del WP;
- reglas de negocio e invariantes afectadas;
- cambios fuera de alcance;
- errores funcionales y casos límite;
- concurrencia y estado en memoria;
- contratos/API y compatibilidad entre componentes;
- secreto temporal de votos;
- auditoría y persistencia obligatoria;
- seguridad y exposición accidental de datos;
- regresiones;
- calidad y suficiencia de las pruebas;
- documentación y trazabilidad;
- evaluación de impacto sobre `manual/index.html`, comprobando que exista una declaración explícita
  y que el manual esté actualizado cuando el cambio sí es relevante para usuario o soporte.

### Severidades

Los hallazgos se clasifican al menos como:

- **BLOQUEANTE**: impide integración; compromete corrección, invariantes, seguridad, auditoría, contratos esenciales o capacidad de operar/probar el WP.
- **IMPORTANTE**: defecto significativo o incumplimiento del WP que debe corregirse antes de integrar.
- **MENOR**: mejora o defecto de bajo impacto que puede corregirse antes de integrar o registrarse explícitamente como seguimiento cuando no comprometa aceptación.

Una PR **no puede integrarse con hallazgos BLOQUEANTES o IMPORTANTES pendientes**.

### Ciclo de corrección

Si el revisor encuentra problemas:

1. el implementador corrige en la misma rama del WP;
2. se vuelven a ejecutar las pruebas/CI aplicables;
3. el mismo revisor independiente puede volver a revisar;
4. se repite hasta que no queden hallazgos BLOQUEANTES o IMPORTANTES abiertos.

El revisor no pierde independencia por revisar sucesivas correcciones mientras no se convierta en implementador de esas correcciones.

### Qué cambios requieren esta revisión

- Toda PR de implementación de un WP.
- Cambios canónicos relevantes de arquitectura, contratos, auditoría, CI o despliegue, aunque tengan poco código.

Cambios administrativos puramente menores pueden quedar exentos cuando no modifiquen comportamiento, arquitectura, contratos ni reglas. La exención debe ser evidente y no utilizarse para eludir la revisión de cambios sustantivos.

### Evidencia

La PR debe registrar:

- herramienta/agente revisor;
- modelo efectivo cuando sea relevante para demostrar independencia;
- resultado de la revisión;
- hallazgos pendientes o confirmación de que no existen BLOQUEANTES/IMPORTANTES abiertos.

## DT-038 - Autoridad de cambios y autonomía del agente

Los agentes tienen **autonomía técnica local dentro del WP**, pero no tienen autoridad para cambiar reglas, contratos globales, decisiones canónicas ni el alcance aprobado.

### Decisiones que el implementador puede tomar autónomamente

Siempre que respeten el WP, las fuentes canónicas, los contratos y el comportamiento observable, el agente puede decidir sin aprobación adicional:

- nombres de variables, funciones, clases y símbolos internos;
- organización razonable en módulos, helpers y funciones privadas;
- algoritmos internos equivalentes;
- estructura concreta de las pruebas requeridas;
- mensajes internos de diagnóstico que no formen parte de un contrato estable;
- refactors locales estrictamente necesarios para completar el WP;
- corrección de defectos encontrados dentro del alcance autorizado;
- detalles de implementación que no cambien comportamiento observable, contratos, dependencias ni decisiones globales.

No debe solicitar aprobación humana para microdecisiones de código que pertenecen claramente a esta categoría.

### Decisiones que requieren escalamiento y aprobación humana/documentada

El agente **no puede decidir unilateralmente**:

- crear, cambiar o reinterpretar una regla de negocio;
- cambiar cualquiera de las decisiones DT-001 a DT-038;
- redistribuir responsabilidades entre backend, frontends, bridge u otros componentes;
- cambiar arquitectura o estrategia global;
- crear o modificar un contrato público/API, DTO compartido o semántica OpenAPI fuera de lo autorizado explícitamente por el WP;
- cambiar formatos canónicos de configuración, padrón, Orden del Día o CSV de auditoría;
- cambiar niveles o semántica institucional de auditoría;
- agregar una **nueva dependencia directa** de producto o tooling no prevista por el WP/configuración ya aprobada;
- introducir base de datos, persistencia operativa o recuperación de sesión;
- cambiar estrategia de concurrencia, REST/SSE, secreto temporal de votos o seguridad;
- cambiar stack, testing, calidad estática, CI o despliegue;
- modificar `AGENTS.md`, decisiones canónicas o el alcance/criterios del WP para facilitar la implementación;
- incorporar trabajo sustancial fuera del WP;
- eliminar, relajar, desactivar o reescribir una prueba/criterio de aceptación con el objetivo de hacer pasar la CI en lugar de corregir el defecto.

Una dependencia directa nueva requiere aprobación aunque sea pequeña. El agente debe preferir primero el stack ya aprobado o la biblioteca estándar cuando sea razonable.

### Forma de escalamiento

Cuando aparezca una decisión reservada, el agente debe registrar de forma concisa:

```text
Decisión requerida:
Motivo:
Alternativas:
Impacto:
Recomendación:
Alcance bloqueado:
```

Si la cuestión es transversal o tiene consecuencias futuras relevantes, puede proponer crear un `DEC-XXX`, pero **no puede aprobarlo ni tratarlo como vigente por sí mismo**.

### Bloqueo mínimo

Una decisión pendiente no debe detener innecesariamente todo el WP.

El agente debe:

- detener únicamente la parte que dependa de la decisión;
- continuar trabajo independiente que pueda completarse con seguridad y sin asumir la respuesta;
- dejar claramente identificado qué quedó bloqueado;
- no introducir una solución provisional que condicione silenciosamente la decisión humana posterior.

### Hallazgos fuera de alcance

Un defecto o mejora detectado fuera del WP se documenta como hallazgo. No se implementa salvo que sea estrictamente necesario para cumplir el WP y esa ampliación haya sido autorizada documentalmente.

### Regla de precedencia

Cuando exista duda entre autonomía local y cambio reservado, se considera reservado si existe riesgo razonable de alterar:

- comportamiento observable;
- contrato entre componentes;
- regla institucional;
- arquitectura;
- dependencia;
- operación/despliegue;
- criterio de aceptación.

En ese caso se escala la decisión en lugar de inferir autoridad.