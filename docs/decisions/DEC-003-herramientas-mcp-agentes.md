# DEC-003 - Herramientas MCP estándar para agentes

## Estado

`APROBADA`

## Contexto

SIS-Leg se implementará con agentes de código intercambiables, principalmente Codex, Claude Code y OpenCode. Para reducir errores por conocimiento desactualizado, mejorar la consulta de documentación oficial y facilitar validaciones de interfaz, el proyecto adopta un conjunto pequeño de herramientas MCP con responsabilidades explícitas.

La disponibilidad de un MCP no modifica la autoridad documental del proyecto ni amplía el alcance de un Work Package. Los MCP son herramientas auxiliares: nunca reemplazan `AGENTS.md`, el WP asignado, las decisiones canónicas, los criterios de aceptación ni las pruebas versionadas.

## Decisión

Los MCP estándar recomendados para el entorno de desarrollo de SIS-Leg son:

- Context7;
- Nuxt MCP;
- Playwright MCP;
- GitHub MCP o integración equivalente de GitHub disponible en el arnés utilizado.

La configuración efectiva puede variar entre Codex, Claude Code y OpenCode. Las credenciales, tokens, API keys y configuraciones personales del cliente **no se versionan en el repositorio**.

## 1. Context7 - documentación técnica externa actualizada

Context7 es la herramienta de consulta prioritaria cuando una implementación, configuración o explicación dependa de la API actual de una librería, framework o herramienta externa.

El agente debe consultar Context7 antes de asumir sintaxis, APIs, opciones de configuración o comportamiento específico de versión cuando trabaje con dependencias como, entre otras:

- FastAPI;
- Pydantic;
- HTTPX;
- AnyIO;
- pytest;
- Nuxt;
- Vue;
- TypeScript;
- Tailwind CSS;
- Vitest;
- Playwright;
- Ruff, Pyright, ESLint y Prettier cuando una decisión dependa de su configuración vigente.

### Regla de uso automático

No es necesario que el prompt humano diga `use context7`.

El agente debe invocarlo automáticamente cuando:

- genere código que use una API externa cuya forma pueda variar por versión;
- configure una librería, framework, plugin o herramienta;
- necesite confirmar una opción, firma, comportamiento, compatibilidad o práctica recomendada actual;
- encuentre un error que pueda deberse a diferencias entre versiones;
- vaya a incorporar una solución basada principalmente en conocimiento general del modelo sobre una dependencia externa.

No es obligatorio invocarlo para cada edición trivial ni para lógica puramente interna ya definida por contratos propios del repositorio.

Context7 es una fuente técnica externa, no una fuente de reglas de SIS-Leg. Si la documentación externa ofrece varias alternativas, el agente solo puede escoger entre las compatibles con las decisiones canónicas. Si una alternativa requiere cambiar arquitectura, dependencia, stack, contrato o una decisión reservada por DT-038, debe escalarla.

## 2. Nuxt MCP - fuente oficial específica para Nuxt

Para cuestiones específicamente relacionadas con Nuxt, el agente debe preferir el MCP oficial de Nuxt cuando esté disponible, especialmente para:

- documentación de Nuxt 4;
- auto-imports, composables y convenciones;
- configuración de Nuxt;
- módulos y compatibilidad;
- cambios entre versiones;
- recomendaciones específicas del framework.

Context7 puede complementar esta consulta para Vue, TypeScript, Tailwind u otras dependencias, pero el MCP oficial de Nuxt es la referencia externa preferente para comportamiento propio de Nuxt.

La documentación oficial de Nuxt expone su MCP mediante `https://nuxt.com/mcp` y permite filtrar documentación por versiones, incluida 4.x.

## 3. Playwright MCP y Playwright versionado

Playwright MCP puede utilizarse para exploración interactiva del frontend, inspección del DOM/accesibilidad, reproducción de recorridos y diagnóstico visual/funcional cuando resulte útil.

Sin embargo:

- Playwright MCP no sustituye los tests Playwright versionados del repositorio;
- los criterios de aceptación que requieran E2E deben quedar demostrados por tests reproducibles en código/CI cuando el WP lo exija;
- una exploración manual mediante MCP puede aportar diagnóstico o evidencia adicional, pero no reemplaza la evidencia determinista requerida.

Cuando para una tarea sea más eficiente la CLI de Playwright o una capacidad equivalente del agente, puede utilizarse sin forzar MCP, siempre que se preserve la reproducibilidad de los tests del proyecto.

## 4. GitHub MCP / integración equivalente

Los agentes pueden utilizar GitHub MCP o la integración GitHub equivalente disponible en su arnés para:

- inspeccionar repositorio y ramas;
- consultar PRs, issues y revisiones;
- obtener contexto de CI y trazabilidad cuando la herramienta lo permita;
- crear la PR al finalizar un WP si el flujo aprobado lo autoriza.

Esta herramienta no amplía la autoridad del agente. Continúan vigentes DT-033 a DT-038 y DEC-002: el agente no puede fusionar una PR, cambiar unilateralmente el PLAN, aprobar su propio WP, eludir revisión independiente ni desplegar por disponer de una herramienta GitHub.

## 5. Disponibilidad, ausencia y fallback de MCP

Los agentes **no deben asumir silenciosamente que un MCP está disponible**.

Al iniciar un WP, o antes del primer punto en el que una herramienta resulte necesaria, el agente debe comprobar razonablemente las capacidades disponibles en su arnés.

### MCP necesario o prescripto y no disponible

Si una regla de este documento, el WP o una tarea concreta requiere utilizar un MCP y ese MCP no está conectado, falla o no puede invocarse, el agente debe **informarlo explícitamente al usuario/operador** antes de continuar la parte que dependía de él.

El aviso debe indicar como mínimo:

```text
Herramienta no disponible:
Uso que se necesitaba:
Alternativa disponible, si existe:
Impacto de continuar sin ella:
```

### Cuándo puede continuar sin el MCP

El agente puede continuar sin esperar autorización adicional solamente cuando exista una alternativa claramente equivalente y segura que:

- use una fuente primaria/oficial adecuada o una herramienta local equivalente;
- no cambie arquitectura, dependencias, alcance ni contratos;
- no reduzca un criterio de aceptación o una prueba obligatoria;
- no convierta una verificación requerida en una suposición del modelo.

Debe dejar constancia en la PR de que se utilizó el fallback y cuál fue la fuente/herramienta alternativa.

Ejemplos aceptables:

- Context7 no disponible -> consultar documentación oficial primaria vigente del framework/librería mediante una capacidad web/documental disponible;
- Nuxt MCP no disponible -> usar documentación oficial de Nuxt 4;
- Playwright MCP no disponible -> usar Playwright CLI/tests versionados para la misma comprobación cuando alcancen el objetivo;
- GitHub MCP no disponible -> usar Git/`gh` u otra integración GitHub ya disponible y autorizada.

### Cuándo debe detenerse y avisar

Debe detener únicamente la parte afectada y pedir intervención si:

- no existe una fuente/herramienta equivalente confiable;
- el WP exige expresamente evidencia producida con esa capacidad específica;
- continuar obligaría a adivinar una API, comportamiento o configuración;
- la alternativa implicaría instalar una dependencia, cambiar stack, alterar seguridad/permisos o tomar una decisión reservada por DT-038.

La falta de un MCP nunca autoriza al agente a inventar comportamiento ni a basarse exclusivamente en memoria del modelo cuando la consulta externa era necesaria.

## 6. Configuración y secretos

La política de MCP es canónica en el repositorio, pero la configuración efectiva del cliente pertenece al entorno del desarrollador/agente.

No deben versionarse:

- API keys;
- tokens;
- cookies/sesiones;
- credenciales de GitHub;
- configuraciones personales con secretos;
- archivos de usuario como `~/.codex/config.toml` o equivalentes.

WP-001 debe documentar cómo verificar las herramientas esperadas y cómo configurarlas en los arneses principales sin almacenar secretos en Git.

Si se agregan archivos de ejemplo, deben usar placeholders evidentes y nunca valores reales.

## 7. MCPs no adoptados como estándar

No se incorporan por defecto:

- MCPs genéricos de filesystem cuando el agente ya dispone de acceso local suficiente;
- MCPs genéricos de shell/terminal redundantes con la capacidad local del agente;
- accesos MCP directos a bases de datos o servicios productivos;
- herramientas con permisos amplios no justificadas por un WP.

Agregar otro MCP como estándar transversal requiere una decisión documentada. Un WP puede usar temporalmente una herramienta adicional si está dentro de su autoridad y no introduce dependencias/riesgos reservados; de lo contrario debe escalarse.

## Consecuencias

- Los prompts humanos no necesitan repetir `use context7` ni enumerar MCPs en cada WP.
- Los agentes deben utilizar documentación externa actual cuando corresponda, en lugar de confiar ciegamente en conocimiento de entrenamiento.
- La ausencia de una herramienta se vuelve observable y trazable: debe avisarse y, cuando exista, usarse un fallback seguro y explícito.
- El entorno local puede diferir entre Codex, Claude Code y OpenCode sin alterar las reglas del proyecto.
- La evidencia reproducible continúa viviendo en código, tests, CI y PRs, no en el estado interno de un MCP.

## Documentos y WPs afectados

- `AGENTS.md`;
- `docs/14-gobernanza-agentes.md`;
- `docs/work-packages/WP-001.md`;
- `.github/pull_request_template.md`;
- `docs/decisions/README.md`;
- todos los WPs de implementación presentes y futuros.
