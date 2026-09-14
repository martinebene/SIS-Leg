# WP-104 — validación post-merge del canal público

Fecha: 2026-09-14.

Este documento registra únicamente la validación post-merge exigida por `docs/work-packages/WP-104.md`. Es un cambio exclusivamente documental y no modifica el producto ejecutable ni autoriza producción.

## Release funcional integrada

- Product PR: `#115`.
- Candidate revisado: `3995fa22c1ca4b7a693e03e40f0572f2257ff973`.
- Candidate tree: `7cec34410fc64bb9367fb7d2d2cd0be33145e833`.
- Merge por squash: `021742eba7f6fb3cad46bd763d83a3f1fb497644`.
- Tree del merge: `7cec34410fc64bb9367fb7d2d2cd0be33145e833`, idéntico al candidato revisado.
- CI post-merge: `#555`, run `34854159684`, intento `1`, `success`, 8/8 jobs.
- Workflow `Publicar release pública`: `#12`, run `34854853331`, intento `1`, `success`.
- Release: `sis-leg-021742eba7f6fb3cad46bd763d83a3f1fb497644`.
- Release ID: `388457930`.
- Assets: exactamente paquete `.tar.gz`, sidecar `.tar.gz.sha256` y `.metadatos.json`.
- SHA-256 del paquete: `eb9381232b2d8064a59edc103394bc6171323e8811cff898f1e16c7988c47f5a`.

## Validación deliberada con `main` documental por delante

La creación de este mismo documento hace avanzar `main` mediante un commit exclusivamente documental. Conforme DEC-019, ese commit no debe producir CI ni una nueva release pública.

El gate final de WP-104 consiste en verificar después de este commit que:

1. `main_head_sha` es este commit documental;
2. `releases/latest` continúa siendo `sis-leg-021742eba7f6fb3cad46bd763d83a3f1fb497644`;
3. la comparación Git pública demuestra que `021742eba7f6fb3cad46bd763d83a3f1fb497644` es ancestro del nuevo `main_head_sha`;
4. no existe una publicación pública nueva para este cambio exclusivamente documental.

La evidencia objetiva de esos cuatro puntos se persiste en `martinebene/SIS-Leg-Control` al cerrar WP-104.

## Límite de autoridad

Esta validación no instala, descarga ni prepara releases en el host productivo. WP-101B continúa sujeto a HUMAN_GATE independiente y `production_mutation_authorized=false` hasta que Control lo autorice expresamente.
