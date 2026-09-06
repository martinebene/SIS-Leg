# Claude Code

@AGENTS.md

Usá `AGENTS.md` como fuente común de instrucciones del repositorio. No dupliques ni reinterpretes aquí las reglas canónicas del producto.

## Entrada operativa obligatoria

Una orden humana breve como `Seguí`, `Continuá` o `Revisá` es solamente una señal para consultar el estado operativo; no contiene por sí misma la tarea.

Antes de realizar trabajo sustantivo como IMPLEMENTER o REVIEWER:

1. seguí primero el bootstrap de coordinación definido en `AGENTS.md`;
2. sincronizá `martinebene/SIS-Leg-Control`;
3. leé allí `CLAUDE.md` si existe, `AGENTS.md`, `PROTOCOL.md` y `CURRENT.json`;
4. leé el archivo de rol correspondiente;
5. verificá `next_actor`, WP, iteración, `assignment_id`, destinatario y `expected_response_path`;
6. si la asignación fija agente/arnés o modelo, verificá que esta sesión de Claude esté autorizada para ejecutarla;
7. leé únicamente `assignment_path` y las fuentes canónicas de SIS-Leg que esa asignación requiera.

Si el turno corresponde a otro actor o a otro agente, si el resultado esperado ya existe o si el estado es ambiguo, detenete sin modificar nada e indicá al humano qué actor/agente corresponde.

## Claude como agente

Claude Code es una alternativa de primera clase dentro de la selección dinámica de agentes definida por DEC-007. Puede actuar como IMPLEMENTER o REVIEWER cuando el ORCHESTRATOR lo autoriza para ese turno.

La disponibilidad actual de Claude Opus 5 puede utilizarse para WPs que justifiquen mayor capacidad de razonamiento, pero el modelo concreto no queda fijado como arquitectura permanente. Registrá siempre el modelo efectivo utilizado cuando la asignación o el informe lo requieran.

Para implementación normal, una vez superado el bootstrap operativo, seguí el flujo indicado en `AGENTS.md`: WP asignado -> fuentes canónicas declaradas por ese WP -> código/pruebas estrictamente necesarias.
