# DEC-019 - CI proporcional al tipo de cambio y omisión de CI completa en commits documentales

## Estado

`APROBADA`

## Contexto

La CI vigente de SIS-Leg ejecuta ocho jobs costosos ante toda Pull Request y ante todo `push` a `main`, sin distinguir si el cambio modifica código ejecutable o solamente documentación Markdown.

DEC-005 autoriza al ORCHESTRATOR, con aprobación humana explícita, a mantener directamente en `main` documentación canónica como PLAN, WPs, DEC, AGENTS y cierres administrativos. En la práctica, cada uno de esos commits puramente documentales vuelve a ejecutar backend, frontend, Playwright, E2E integrado, build y empaquetado productivo aunque el árbol ejecutable sea idéntico al ya validado.

HUMAN_GATE decide reducir esa redundancia sin debilitar las puertas aplicables a cambios de producto, tests, tooling, configuración, CI o despliegue.

## Decisión

### 1. Pull Requests

Toda `pull_request` de SIS-Leg continúa disparando la CI completa vigente.

No se aplican exclusiones por rutas a PRs. Esto preserva una validación uniforme del candidato exacto sometido a revisión independiente.

### 2. Push a main con cambio material

Todo `push` a `main` que modifique al menos un archivo fuera de las rutas documentales exentas continúa disparando la CI completa.

Se consideran siempre materiales para este propósito, entre otros:

- código fuente;
- tests;
- scripts;
- workflows de GitHub Actions;
- configuración funcional o productiva;
- manifests y lockfiles;
- assets binarios;
- archivos de despliegue;
- tooling ejecutable.

Un commit mixto, con documentación y cualquier archivo material, **no** queda exento.

### 3. Push a main puramente documental

Cuando **todos** los archivos modificados por un `push` a `main` pertenecen a documentación Markdown, la CI completa de Product no debe dispararse.

La implementación mínima aprobada es limitar el evento `push` mediante `paths-ignore` a:

- `docs/**`;
- `**/*.md`.

La exclusión aplica sólo al evento `push` sobre `main`; no modifica el comportamiento de `pull_request`.

### 4. Ausencia de run como resultado esperado

Para un commit directo a `main` cubierto por DEC-005 y compuesto exclusivamente por documentación exenta, que no exista una run de CI de Product es un resultado **esperado y válido**.

El ORCHESTRATOR no debe bloquear la planificación, activación o cierre posterior esperando una CI que, por diseño, no debe existir.

Debe seguir verificando:

- HEAD remoto exacto;
- que el commit sea realmente documental;
- que no haya archivos materiales mezclados;
- sincronización local requerida por DEC-004/DEC-005.

### 5. Gates que no cambian

Se mantienen sin reducción:

1. candidato exacto de una PR ejecutable: CI aplicable verde;
2. revisión independiente aprobatoria;
3. integración por squash;
4. CI completa post-merge cuando el merge modifica archivos materiales;
5. prohibición de integrar con BLOQUEANTES o IMPORTANTES pendientes.

Modificar el propio workflow de CI es un cambio material y debe recorrer WP + rama + PR + revisión independiente. Su merge a `main` debe ejecutar la CI completa porque `.github/workflows/ci.yml` no está entre las rutas ignoradas.

### 6. Cierres documentales

Después de una integración funcional ya validada por CI post-merge, los commits posteriores que sólo actualizan `PLAN.md`, `WP-XXX.md`, DEC, AGENTS u otra documentación Markdown no repiten E2E/build/package.

El primer cierre documental realizado después de integrar WP-068 se usará además como verificación operativa del filtro: no debe crearse una nueva run de Product para ese SHA.

### 7. SIS-Leg-Control

SIS-Leg-Control conserva su validación propia. Handoffs, `CURRENT.json`, `FINAL_DECISION` y demás transporte operativo no requieren ni disparan la CI de Product.

## Consecuencias

- Se elimina la espera redundante de CI completa para activaciones y cierres puramente documentales.
- Las PRs continúan teniendo la misma cobertura completa.
- Los merges funcionales/materiales a `main` continúan teniendo CI post-merge completa.
- Un commit mixto nunca puede esconder cambios ejecutables detrás de una exclusión documental.
- Se reduce consumo de minutos de Actions y tiempo de orquestación sin relajar los gates de producto.

## Relación con decisiones anteriores

### DEC-005

Precisa la sección 7: «CI aplicable» significa que un commit puramente documental exento puede no generar run de Product. En ese caso la ausencia de CI no bloquea trabajo dependiente.

### DEC-004 / DT-037

No cambia revisión ni integración de PRs ejecutables. La revisión independiente y la CI del candidato/post-merge material permanecen obligatorias.

### DT-038

Este cambio altera la política de CI y por eso requirió decisión humana explícita. HUMAN_GATE lo aprobó el 03/09/2026.

## Implementación

WP-068 modifica exclusivamente el trigger de `.github/workflows/ci.yml` y la documentación asociada. No debe reducir, eliminar ni condicionar internamente ninguno de los ocho jobs para eventos que sigan siendo elegibles.
