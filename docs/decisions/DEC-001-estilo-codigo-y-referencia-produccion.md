# DEC-001 - Estilo de código, documentación pedagógica y referencia a producción

## Estado

`APROBADA`

## Contexto

SIS-Leg se utilizará no solo como sistema productivo sino también como proyecto de aprendizaje. El código debe ser comprensible para una persona que está aprendiendo Python, FastAPI, TypeScript, Vue y Nuxt.

Además, SIS-Leg dispone de una versión actualmente en producción en `martinebene/Botonera`, rama `main`. La documentación de SIS-Leg continúa siendo la fuente normativa principal, pero el comportamiento productivo existente es una referencia valiosa cuando una regla de negocio, experiencia de usuario o decisión visual no está suficientemente definida.

Esta decisión es transversal y aplica a todos los Work Packages de implementación futuros.

## Decisión

### 1. Código propio escrito en español

Todo identificador **bajo control del proyecto** debe utilizar nombres semánticos en español:

- funciones y métodos;
- clases;
- variables;
- constantes propias;
- tipos e interfaces propias;
- atributos/campos internos;
- helpers;
- nombres de tests y fixtures cuando sean propios del proyecto.

Los identificadores deben escribirse sin tildes ni `ñ`, para mantener compatibilidad y legibilidad transversal. Ejemplos preferidos:

- `abrir_sesion`;
- `cantidad_presentes`;
- `EstadoVotacion`;
- `resultado_actual`;
- `obtenerEstadoModeracion`.

Debe respetarse la convención idiomática del lenguaje/framework. Por ejemplo:

- Python: `snake_case` para funciones/variables y `PascalCase` para clases;
- TypeScript/Vue: `camelCase` para funciones/variables y `PascalCase` para clases/tipos/componentes cuando corresponda.

#### Excepciones

No se traducen nombres impuestos por:

- el lenguaje;
- FastAPI, Pydantic, Nuxt, Vue, Tailwind u otras librerías;
- hooks o convenciones obligatorias de frameworks;
- APIs externas;
- contratos HTTP/OpenAPI o formatos de archivo ya definidos canónicamente;
- nombres de paquetes, comandos o propiedades técnicas cuya traducción rompería compatibilidad.

Cuando una convención del framework exige una parte fija del nombre, se conserva esa parte y se expresa en español la parte bajo control del proyecto. Ejemplo: un composable Nuxt puede llamarse `useEstadoModeracion`.

No se deben renombrar contratos técnicos cerrados únicamente para traducirlos si ello rompe compatibilidad o contradice una decisión canónica previa.

### 2. Comentarios y documentación del código con finalidad pedagógica

El código debe estar **abundantemente documentado en español**, con un nivel apto para una persona que está aprendiendo los lenguajes y frameworks utilizados.

Como mínimo:

- cada clase propia debe explicar qué representa, su responsabilidad y cómo se relaciona con el sistema;
- cada función/método no trivial debe explicar qué hace, entradas relevantes, resultado, efectos laterales y errores esperables cuando corresponda;
- los flujos de estado, concurrencia, SSE, reactividad Vue/Nuxt, persistencia de auditoría y otras partes no obvias deben contener comentarios que expliquen el razonamiento y la secuencia;
- las decisiones de implementación que puedan resultar poco evidentes deben explicar **por qué** se hacen de esa manera;
- los tests deben ser legibles y, cuando el escenario no sea evidente, explicar qué regla o comportamiento están demostrando.

Los comentarios no deben limitarse a repetir sintácticamente la línea siguiente. Deben aportar contexto útil para aprender y mantener el sistema.

Si se modifica código comentado, el agente debe mantener los comentarios sincronizados con el comportamiento real. Un comentario desactualizado se considera un defecto.

### 3. Explicación para principiantes en cada Pull Request

Toda PR de implementación debe incluir una sección específica de explicación pedagógica, escrita para una persona con conocimientos básicos de programación pero que puede estar aprendiendo el lenguaje/framework usado en ese WP.

Debe explicar, según corresponda:

1. qué problema resuelve el WP;
2. qué se implementó;
3. cómo funciona el flujo principal paso a paso;
4. qué conceptos de Python/FastAPI/TypeScript/Vue/Nuxt u otras herramientas aparecen y para qué se usan;
5. cuáles son los archivos principales y en qué orden conviene leerlos;
6. cómo probar manualmente o entender el resultado;
7. cualquier término o sigla no obvia utilizada en la explicación.

La explicación pedagógica complementa el resumen técnico; no lo reemplaza.

### 4. Regla de fallback al sistema actualmente en producción

La jerarquía de autoridad para **reglas de negocio, experiencia de usuario y diseño/flujo de interfaz** es:

1. documentación canónica vigente de SIS-Leg;
2. decisiones explícitas aprobadas e incorporadas al repositorio;
3. si lo anterior no define claramente el comportamiento, verificar el sistema actualmente en producción consultando `martinebene/Botonera`, rama `main`, en su estado vigente al momento de la tarea;
4. si producción tampoco permite determinarlo de forma inequívoca, escalar la duda en lugar de inventar una regla o experiencia nueva.

Al consultar producción:

- debe inspeccionarse únicamente el código necesario para la duda concreta;
- para comportamiento real prevalece el código ejecutable de `main` sobre README, manuales o comentarios históricos si difieren;
- debe registrarse en el WP o PR qué comportamiento se verificó y qué archivos de producción se consultaron cuando esa consulta influyó en la implementación;
- si SIS-Leg ya define explícitamente algo distinto, **prevalece SIS-Leg** y producción no reabre la decisión.

Esta regla se aplica también al diseño de interfaz cuando la documentación nueva no define con claridad, por ejemplo:

- disposición funcional de controles;
- estados visuales existentes;
- secuencia de interacción;
- avisos/confirmaciones;
- comportamiento de botones;
- información que el operador o el público espera ver.

### 5. La producción NO es fallback para decisiones técnicas

El sistema anterior no debe utilizarse para decidir por analogía:

- arquitectura;
- estructura interna de módulos/clases;
- dependencias;
- patrones de concurrencia;
- transporte frontend/backend;
- polling vs SSE;
- persistencia;
- estrategia de testing;
- CI;
- despliegue;
- stack o versiones;
- contratos técnicos nuevos;
- estilo técnico que ya esté cerrado en las decisiones de SIS-Leg.

Estas cuestiones se rigen exclusivamente por la documentación y decisiones técnicas de SIS-Leg. Ante una duda técnica no definida, se escala según DT-038; no se copia la solución histórica por defecto.

## Consecuencias

- Los WPs futuros deben heredar estas reglas aunque no las repitan completas.
- El revisor independiente debe considerar incumplimiento sustantivo que código propio nuevo utilice nomenclatura inglesa sin una excepción justificada, que falte documentación pedagógica relevante o que una PR carezca de la explicación para principiantes requerida.
- Consultar producción deja de ser una excepción ad hoc y pasa a ser un procedimiento formal de resolución de ambigüedades funcionales/UX/visuales.
- La versión histórica continúa sin autoridad para arquitectura o decisiones técnicas de SIS-Leg.

## Documentos y WPs afectados

- `AGENTS.md`;
- `docs/09-fuentes-y-trazabilidad.md`;
- `docs/work-packages/TEMPLATE.md`;
- `.github/pull_request_template.md`;
- todos los WPs de implementación presentes y futuros, por herencia de `AGENTS.md`.
