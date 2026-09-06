# 10 - Decisiones técnicas abiertas

Las reglas de negocio y las decisiones técnicas previas al inicio de implementación están cerradas.

Las decisiones aprobadas se registran en:

- `12-decisiones-tecnicas.md` para arquitectura, backend/datos, frontend y calidad;
- `13-despliegue-y-operacion.md` para despliegue/operación;
- `14-gobernanza-agentes.md` para ramas, WPs, herramientas agénticas, revisión y autoridad;
- `07-configuracion-datos-y-assets.md` para el contrato canónico de datos/configuración, incluido Orden del Día.

## Estado actual

No existen decisiones técnicas previas abiertas que bloqueen el inicio de `WP-001`.

DT-039 quedó cerrada: SIS-Leg utiliza exclusivamente el nuevo formato explícito de CSV de Orden del Día y **no ofrece compatibilidad automática con el formato histórico**.

Contrato canónico:

```text
nro_votacion,tipo,tema,tipo_mayoria,factor,base
```

Reglas principales:

- `tipo_mayoria = SIMPLE | ESPECIAL`;
- para `SIMPLE`, `factor` y `base` deben estar vacíos;
- para `ESPECIAL`, `factor` es obligatorio y `base = PRESENTES | CUERPO`;
- no se infiere mayoría simple desde `factor=0`, campo vacío ni otro valor;
- el formato histórico `nro_votacion,tipo,tema,factor_de_mayoria,respecto` debe convertirse externamente al nuevo formato antes de importarse.

Ver detalle en `docs/07-configuracion-datos-y-assets.md` y DT-039 en `docs/12-decisiones-tecnicas.md`.

## Decisiones nuevas durante la implementación

Si durante un WP surge una cuestión que:

- modifica arquitectura, contratos o responsabilidades;
- cambia una decisión DT ya aprobada;
- incorpora una dependencia directa no prevista;
- altera reglas, criterios de aceptación, formatos canónicos, seguridad, auditoría, CI o despliegue;
- tiene consecuencias transversales o futuras relevantes;

el agente no debe resolverla unilateralmente.

Debe escalarla según DT-038 y, cuando corresponda, documentarla mediante un `DEC-XXX` aprobado antes de continuar el alcance afectado.

## Criterio de inicio de programación

Antes de ejecutar un WP concreto deben cumplirse sus condiciones operativas:

1. el WP debe existir y estar aprobado en `docs/work-packages/`;
2. sus dependencias deben estar integradas o expresamente autorizadas;
3. no puede depender de una DT/DEC todavía abierta;
4. debe tener rama y `git worktree` propios;
5. debe registrarse el agente implementador cuando pase a `EN_CURSO`;
6. la entrega debe pasar CI y revisión independiente antes de integrarse.

Ningún agente puede improvisar trabajo fuera del PLAN o de un WP aprobado.
