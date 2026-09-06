# 05 - Frontend de Moderación

Frontend **Nuxt 4 + TypeScript estricto**, con Tailwind CSS v4 y componentes propios, destinado al operador único del sistema. No contiene reglas de negocio: representa estado y envía comandos al backend.

El estado autoritativo vive en FastAPI. La primera versión no usa Pinia: la proyección recibida y el estado visual local se manejan con composables/primitives de Vue/Nuxt.

## 1. Sincronización

- snapshot completo por `GET /api/v1/estado/moderacion` al cargar/reconectar;
- actualizaciones completas por `GET /api/v1/estado/moderacion/stream` (SSE);
- comandos por REST `/api/v1`;
- cliente común en `packages/api-client/`;
- ante reconexión SSE se recupera snapshot antes de asumir continuidad.

La UI no reconstruye reglas de negocio localmente.

Cada versión incluye `revision`. El primer evento del stream vuelve a enviar el
estado vigente completo, por lo que una mutación ocurrida entre el snapshot y
la conexión no se pierde. La UI conserva la versión de igual o mayor revisión.

## 2. Estados globales

### SIN_PREPARAR
Debe ofrecer como acción principal `Preparar recinto`.

No debe mostrar controles de votación, palabra o presencia manual.

### PREPARANDO
Debe permitir:

- ver padrón y disposición de bancas;
- cargar/editar número de sesión;
- cargar/editar Presidencia;
- cargar/editar Secretaría Legislativa;
- observar acreditaciones físicas;
- observar test de dispositivos;
- ver quórum y faltantes;
- cargar Orden del Día opcional;
- abrir sesión cuando backend lo habilite;
- cancelar preparación.

### SESION_ABIERTA
Debe permitir:

- ver y cambiar Presidencia/Secretaría;
- ver presencia y quórum;
- operar votaciones;
- operar uso de palabra;
- utilizar Orden del Día como asistencia;
- ver eventos;
- cerrar sesión;
- ejecutar el remapeo rápido cuando se implemente.

## 3. Organización funcional

Se conserva como referencia útil la división vigente en cuatro áreas, sin obligar a copiar su HTML/CSS:

1. comandos y estado de sesión/votación;
2. Orden del Día;
3. recinto/bancas + uso de palabra;
4. eventos.

La implementación Nuxt puede reorganizar visualmente estas áreas si mejora la operación sin perder información ni simultaneidad.

## 4. Preparación

El operador no puede marcar presencia manualmente.

Cada banca debe reflejar:

- identidad del concejal;
- imagen indicada por `ruta_imagen` en el padrón, sin hardcodear una imagen por número de banca;
- presente/ausente;
- test visual temporal;
- dispositivo lógico cuando resulte útil para diagnóstico.

Debe ser evidente si falta quórum y cuántos concejales faltan.

## 5. Autoridades

Presidencia y Secretaría son texto libre.

Pueden modificarse durante preparación o sesión, incluso durante una votación.

La interfaz no intenta decidir si el texto de Presidencia coincide con un concejal ni modifica su estado.

## 6. Apertura de sesión

El botón solo debe ser funcional cuando el backend confirme:

- quórum;
- número de sesión informado;
- Presidencia informada;
- Secretaría informada.

La interfaz puede explicar qué condición falta, pero la validación definitiva es del backend.

## 7. Orden del Día

Debe permitir:

- cargar CSV y enviarlo al backend para parseo;
- informar errores técnicos de lectura/formato;
- listar puntos devueltos;
- seleccionar un punto para precargar el formulario;
- editar todos los campos precargados antes de abrir;
- crear una votación manual;
- seleccionar puntos en cualquier orden.

No debe advertir por números repetidos, secuencia u otras cuestiones institucionales que SIS-Leg no valida.

## 8. Formulario de votación

Campos conceptuales:

- número;
- tipo configurable;
- tema;
- tipo de mayoría `SIMPLE` o `ESPECIAL`;
- para `SIMPLE`: factor vacío/nulo/cero y base vacía o `VOTOS_COMPUTABLES`, que backend normaliza a factor `0` y esa base;
- para `ESPECIAL`: factor real finito `> 0 <= 1` y base `VOTOS_COMPUTABLES`, `PRESENTES` o `CUERPO`.

La UI debe dejar claro que `tipo_mayoria` es explícito y que mayoría simple no equivale a factor 0,5. En la terminología de mayoría, `PRESENTES` refiere a quienes emitieron voto en esa votación, incluidas abstenciones.

Toda representación de sólo lectura del factor, tanto en la votación vigente como en los puntos del Orden del Día, se escribe con exactamente dos decimales, truncando los decimales sobrantes sin redondear (`0.6789` se muestra `0.67` y `0.6` se muestra `0.60`). Es una regla de presentación: el valor real conserva su precisión en el DTO, el CSV, la validación y el cálculo de mayoría. El campo editable del formulario es la excepción explícita, porque su contenido es el valor que se envía al backend.

Una vez abierta, los datos son inmutables.

### Advertencia por uso de palabra pendiente

Antes de enviar `Abrir votación`, si existe un orador actual o al menos un concejal en la cola de pedidos, Moderación debe mostrar una advertencia confirmatoria clara indicando que se está continuando a pesar de existir un concejal con uso/pedido de palabra pendiente.

- cancelar la advertencia no envía el comando;
- confirmar envía normalmente la apertura;
- la confirmación no limpia ni modifica el orador o la cola;
- el uso de palabra continúa pudiendo operar durante la votación;
- esta advertencia es una salvaguarda de interfaz y no sustituye las validaciones del backend.

## 9. Votación en curso

Debe mostrar:

- tema/tipo/número;
- regla de mayoría;
- presencia y quórum actual;
- cantidad de votos recibidos;
- votos individuales después del retardo configurable de Moderación;
- palabra/orador en paralelo.

No existe pausa. Los concejales pueden pedir/usarla palabra mientras continúan llegando votos.

El retardo de votos individuales es una única ventana global que comienza en
`fecha_hora_apertura + moderation_vote_reveal_seconds`. Antes del deadline el
DTO informa `cantidad_votos_recibidos` pero no valores individuales. Al vencer,
revela todos los recibidos y los posteriores aparecen sin demora propia. Una
recarga o reconexión no reinicia la ventana.

## 10. Finalizar votación

Existe una sola acción conceptual `Finalizar votación`.

Puede usarse en cualquier momento de `EN_CURSO` y exige motivo no vacío.

El backend decide el resultado, normalmente `INCONCLUSA` si se finaliza antes de completar.

La interfaz no ofrece edición de votos ni modificación de una votación abierta.

## 11. Empate y Presidencia

Cuando una mayoría simple queda `EMPATADA`:

- se bloquea abrir otra votación;
- Moderación muestra controles `POSITIVO` / `NEGATIVO`;
- no hay abstención;
- muestra quién figura como Presidencia;
- el desempate es irreversible.

Si se cierra la sesión sin desempatar, el backend convierte la votación a `INCONCLUSA`.

## 12. Uso de la palabra

Debe mostrar:

- orador actual;
- cola FIFO;
- controles separados para `Otorgar palabra` y `Quitar palabra`.

La semántica debe conservar el comportamiento operativo de producción, con la regla nueva de ausencia:

- **Otorgar palabra:** si ya existe un orador, finaliza su uso y pasa al primero de la cola; si no hay solicitudes en cola, no queda un nuevo orador.
- **Quitar palabra:** finaliza al orador actual pero **no** pasa automáticamente al siguiente; los pedidos restantes conservan su orden hasta que Moderación vuelva a otorgar palabra.
- **Fin propio con tecla 7:** si el orador finaliza desde su teclado, no pasa automáticamente al siguiente.
- **Ausencia:** un concejal que pasa a ausente pierde su lugar en la cola; si era el orador, finaliza su uso. La ausencia tampoco otorga automáticamente la palabra al siguiente.

Por lo tanto, el avance deliberado al siguiente pedido ocurre mediante la acción `Otorgar palabra`, no como efecto colateral de quitar, terminar voluntariamente o ausentarse.

## 13. Cierre de sesión con palabra pendiente

Antes de enviar `Cerrar sesión`, si existe un orador actual o al menos un pedido en cola, Moderación debe mostrar una advertencia confirmatoria equivalente a la de apertura de votación.

- debe indicar que existen concejales con uso/pedido de palabra pendiente;
- cancelar deja la sesión abierta y no modifica la cola/orador;
- confirmar permite continuar con el cierre normal;
- la advertencia no constituye una nueva precondición reglamentaria del backend.

## 14. Eventos

Debe mostrar una proyección legible de eventos recientes, independiente de los CSV completos.

`EstadoModeracion` entrega como máximo los últimos 200 eventos confirmados del
contexto activo, en orden ascendente de `seq`. Una nueva preparación comienza
otro buffer y `SIN_PREPARAR` no reconstruye archivos históricos.

Los hechos sensibles se presentan con la proyección estructurada del backend,
no con el mensaje crudo de auditoría:

- un voto ordinario identifica concejal y banca y muestra `Voto emitido`
  mientras el sentido individual sigue siendo secreto, sin ningún emoji;
- cuando la frontera autoritativa de esa votación habilita el revelado, el
  mismo registro se enriquece con el sentido y su icono: ✅ POSITIVO,
  ❌ NEGATIVO y 🟡 ABSTENCIÓN;
- el pedido de palabra muestra ✋ y el retiro ✊.

El icono se ubica a la derecha del registro y ocupa aproximadamente la altura
de sus dos filas de texto. Moderación no decide iconos ni sentidos: los recibe
resueltos del backend, que es donde vive la frontera de secreto.

El crecimiento del listado usa scroll interno y **no aumenta la altura de las demás áreas**.

## 15. Remapeo rápido

La operación futura se inicia desde Moderación pero se ejecuta técnicamente a través de backend + `device-bridge`.

Flujo conceptual:

1. identificar la banca/concejal afectado y su identificador lógico actual;
2. iniciar modo de reemplazo;
3. el bridge detecta/captura el nuevo teclado físico;
4. reasigna el nuevo fingerprint al **mismo identificador lógico**;
5. confirmar visualmente el éxito.

No cambia concejal, presencia, votos ni padrón y no conecta el navegador directamente con el bridge.

## 16. Responsive y hardware

Resolución de referencia actual: **1920×1080 (Full HD)**.

No es una dependencia rígida. La interfaz debe:

- conservar funcionalidad ante resoluciones menores razonables y cambios de escala;
- evitar solapamientos y controles inaccesibles;
- usar layouts fluidos/grid/flex y límites mínimos/máximos apropiados;
- usar scroll interno en áreas extensas;
- mantener información crítica visible y legible.

No se aceptan soluciones que solo funcionen correctamente con coordenadas/tamaños fijos para Full HD.

## 17. Reconexión

Al recargar o recuperar conexión debe reconstruir toda la interfaz desde `ModerationState` del backend.

No depende de variables locales para determinar sesión/votación activa.

Los controles toman `capacidades.*.habilitada` y sus códigos `motivos` como
explicación de la disponibilidad actual. El endpoint de comando vuelve a
validar siempre; las capacidades no validan por anticipado un body aún no
suministrado.

## 18. Errores

Los errores funcionales se presentan con mensajes claros basados en identificadores estables del backend.

No se oculta un rechazo ni se simula localmente que una acción tuvo éxito.

Si el backend informa que la auditoría obligatoria no puede persistirse, debe mostrarse como condición técnica grave y bloquear visualmente nuevas acciones que el backend no acepte.
