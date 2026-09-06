# DEC-002 - Lanzador local de Work Packages

## Estado

`APROBADA`

## Contexto

La gobernanza de SIS-Leg exige que cada Work Package (WP) en ejecución utilice una rama, un `git worktree` y una sesión de agente propios. Hacer manualmente esa preparación en cada WP agrega pasos repetitivos y aumenta el riesgo de iniciar un agente en `main` o en un directorio incorrecto.

Se necesita un mecanismo local, reproducible y simple que automatice la preparación mecánica del entorno sin adquirir autoridad para aprobar WPs, modificar reglas de planificación o integrar cambios.

## Decisión

WP-001 debe entregar un lanzador local para iniciar futuros WPs.

### Comando canónico

El mecanismo principal será un script Python versionado en:

`scripts/iniciar_wp.py`

Su uso conceptual será:

```text
python scripts/iniciar_wp.py 002 codex
python scripts/iniciar_wp.py 015 claude
python scripts/iniciar_wp.py 016 opencode
```

El README debe documentar el comando exacto y el modo recomendado de invocarlo con el Python 3.14/`uv` configurado por WP-001.

### Responsabilidades del lanzador

Antes de crear un entorno nuevo debe:

1. verificar que se ejecuta desde el checkout coordinador del repositorio SIS-Leg y que la rama actual es `main`;
2. verificar que `main` no contiene cambios locales sin confirmar;
3. actualizar referencias remotas y exigir que `main` pueda quedar actualizado mediante fast-forward, sin merges automáticos ni reescritura de historia;
4. comprobar que existe `docs/work-packages/WP-NNN.md` y que su estado documental es `APROBADO`;
5. comprobar que en `docs/implementation/PLAN.md` ese WP figura `EN_CURSO` y tiene asignado el agente solicitado;
6. comprobar que las dependencias del WP aparecen `INTEGRADO` en el PLAN;
7. crear, si todavía no existe, una rama corta `wp/NNN-descripcion-corta` desde el `main` actualizado;
8. crear un `git worktree` hermano dedicado a ese WP;
9. abrir el agente solicitado con su directorio de trabajo establecido en ese worktree.

El script debe admitir inicialmente los agentes/herramientas de trabajo aprobados por DT-036:

- `codex`;
- `claude`;
- `opencode`.

El mapeo utiliza las CLI instaladas en el entorno local. Si la CLI solicitada no existe o no puede ejecutarse, debe fallar con un mensaje claro y no iniciar trabajo en otro directorio como fallback.

### Nombre de rama y worktree

- La rama debe respetar `wp/NNN-descripcion-corta`.
- La descripción puede derivarse de forma determinista del título del WP, normalizada para Git, o de otra regla simple y documentada dentro de WP-001.
- El worktree debe quedar fuera del checkout `main`, como directorio hermano, con nombre fácilmente identificable por WP, por ejemplo `SIS-Leg-wp002`.

El detalle reversible de slugificación pertenece a la autonomía local de WP-001 siempre que produzca nombres estables, legibles y compatibles con la convención anterior.

### Reentrada

Si ya existe un worktree válido para ese mismo WP/rama, el lanzador puede reutilizarlo y abrir allí el agente, siempre que pueda demostrar que corresponde inequívocamente al WP solicitado. Ante cualquier conflicto de rama, ruta o worktree debe detenerse en lugar de reparar o borrar automáticamente.

### Autoridad que NO tiene el lanzador

El lanzador no puede:

- cambiar un WP de `PENDIENTE` a `EN_CURSO`;
- asignar agentes en `PLAN.md`;
- aprobar un WP;
- alterar dependencias;
- modificar documentación canónica para habilitarse;
- hacer commits directos a `main`;
- abrir o fusionar PRs automáticamente;
- hacer merge, squash, rebase destructivo, force-push o despliegue;
- eliminar worktrees o ramas con trabajo sin una acción explícita posterior del operador.

La autorización de inicio sigue siendo documental/humana. El script solo automatiza la preparación local después de esa autorización.

## Flujo operativo resultante

```text
Planificador/humano
  -> aprueba WP
  -> PLAN: EN_CURSO + agente asignado

Operador
  -> actualiza su clon
  -> ejecuta iniciar_wp.py NNN agente

Lanzador
  -> valida autorización y dependencias
  -> prepara rama + worktree
  -> abre la CLI dentro del worktree

Agente
  -> lee AGENTS.md
  -> lee WP-NNN.md
  -> implementa únicamente ese WP
```

## WP-001 como excepción inicial

El lanzador todavía no existe antes de implementar WP-001. Por ello, **WP-001 es la única excepción prevista**: su rama y worktree se crean manualmente una vez. Después de integrar WP-001, los WPs siguientes deben preferir el lanzador salvo que exista una razón técnica documentada para no utilizarlo.

## Portabilidad

El lanzador debe escribirse en Python usando preferentemente biblioteca estándar y comandos Git, evitando depender de Bash para su lógica principal. Esto permite utilizarlo tanto en el entorno Linux/VPS como en otros entornos de desarrollo compatibles con el stack del proyecto.

No debe agregarse una dependencia Python de runtime únicamente para implementar este lanzador salvo aprobación según DT-038.

## Consecuencias

- El operador deja de crear manualmente ramas/worktrees para cada WP después de WP-001.
- Cada agente inicia ya aislado del checkout `main`.
- El script valida, pero no sustituye, la autoridad de `PLAN.md` y del WP aprobado.
- La creación de PR, revisión independiente, integración y limpieza posterior siguen siendo etapas separadas.

## Documentos y WPs afectados

- `docs/work-packages/WP-001.md`;
- `docs/implementation/PLAN.md`;
- `docs/14-gobernanza-agentes.md`;
- `README.md` al implementar WP-001;
- todos los WPs posteriores en su mecanismo de inicio local.
