# Decisiones de implementación

Este directorio contiene decisiones operativas y de implementación que complementan los documentos normativos de `docs/`.

Las decisiones aquí registradas no reemplazan reglas de negocio ni decisiones técnicas propietarias. Sirven para fijar contratos concretos, procedimientos y acuerdos necesarios para implementar WPs sin dejar ambigüedades relevantes a los agentes.

## Decisiones vigentes

- `DEC-001-estilo-codigo-y-referencia-produccion.md`: estilo de código, documentación pedagógica y uso acotado de producción como referencia funcional.
- `DEC-002-lanzador-work-packages.md`: contrato del lanzador genérico de WPs y validaciones previas.
- `DEC-003-herramientas-mcp-agentes.md`: uso de herramientas MCP/documentación externa, fallbacks y manejo de secretos.
- `DEC-004-orquestacion-revision-secuencial-y-sincronizacion.md`: relevo secuencial implementador/revisor, sincronización y reglas de integración.
- `DEC-005-planificacion-y-autoridad-documental-del-orquestador.md`: autoridad documental del orquestador y mantenimiento directo autorizado de documentación en `main`.
- `DEC-006-entrada-logica-presencia-test-y-quorum.md`: contrato de entrada lógica, presencia, test y quórum de WP-006.
- `DEC-007-entorno-orca-asignacion-agentes-y-lanzadores.md`: entorno Orca, selección de agentes, lanzadores, prompts manuales y limpieza segura de worktrees.
- `DEC-008-sesion-autoridades-y-contrato-rest.md`: contrato de número de sesión, autoridades, transición `PREPARANDO -> SESION_ABIERTA`, REST de sesión, auditoría y extensión de presencia/test durante sesión para WP-008.
- `DEC-009-apertura-votacion-mayorias-y-contrato-rest.md`: contrato de apertura de votaciones, mayoría SIMPLE/ESPECIAL, bases, inmutabilidad y REST de WP-009.
- `DEC-010-ciclo-vida-cierre-y-resultado-votacion.md`: separación entre ciclo de vida y resultado, autocierre sin cálculo, cálculo unificado de mayorías y carácter transitorio de `EMPATADA`.
- `DEC-011-finalizacion-inconclusa-y-cierre-de-sesion.md`: finalización `INCONCLUSA`, pérdida de quórum, cierre de sesión con votación pendiente y fallo cerrado asociado.
- `DEC-012-desempate-presidencial-contrato-rest-y-fallo-cerrado.md`: contrato REST de desempate presidencial, voto separado y frontera de fallo cerrado.
- `DEC-013-proyecciones-snapshots-sse-y-secreto-temporal.md`: contratos REST/SSE de `ModerationState`/`PublicState`, revisión, reconexión, secreto temporal, eventos recientes y capacidades.
- `DEC-014-cliente-api-typescript-openapi-y-reconexion.md`: contrato del cliente TypeScript compartido, generación OpenAPI/tipos, superficies separadas de Moderación/Recinto y recuperación/reconexión.
- `DEC-015-device-bridge-linux-fingerprint-y-entrega-de-pulsaciones.md`: contrato Linux del bridge físico, `evdev`, fingerprint compatible con producción histórica, `devices.json`, normalización amplia de teclas y entrega HTTP sin reintentos.
- `DEC-016-remapeo-fisico-coordinado-y-persistencia-seleccionable.md`: contrato de remapeo coordinado backend/bridge, captura no bloqueante, candidato físico seguro e implementación temporal o persistente elegida explícitamente por el operador.
- `DEC-017-coordinacion-mediante-sis-leg-control.md`: coordinación de turnos y handoffs mediante el repositorio Control.
- `DEC-018-coordinador-local-secuencial-orca-y-cuotas.md`: coordinador local secuencial, lotes Orca y gestión de cuotas.
- `DEC-019-ci-proporcional-y-commits-documentales.md`: CI completa para PRs/cambios materiales y omisión de CI de Product en pushes puramente documentales a `main`.

## Criterio de uso

Una decisión nueva debe existir cuando un WP necesita fijar un contrato o comportamiento que no puede quedar librado a la autonomía local del implementador y cuya semántica no está suficientemente cerrada en los documentos propietarios existentes.

No se crean decisiones para detalles locales reversibles que un agente puede resolver de forma segura dentro de un WP aprobado.

Las decisiones que cambien reglas de negocio, arquitectura, contratos transversales, seguridad, auditoría, CI o despliegue deben respetar DT-038 y la autoridad humana correspondiente antes de considerarse aprobadas.
