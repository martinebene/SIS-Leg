# 11 - Criterios de aceptación

Estos criterios deben convertirse progresivamente en pruebas automáticas. Son independientes de la arquitectura técnica elegida.

## CA-001 Estado inicial

Dado un backend recién iniciado, el estado debe ser `SIN_PREPARAR`, sin sesión activa, votación activa ni CSV abiertos.

## CA-002 Preparar recinto

Al preparar correctamente:

- pasa a `PREPARANDO`;
- carga configuración/padrón;
- todos los concejales quedan ausentes;
- se crean tres CSV nuevos;
- solo presencia y test físico están habilitados.

## CA-003 Padrón inválido

Debe rechazarse preparar si existe:

- DNI vacío/duplicado;
- nombre o apellido vacío;
- banca inválida/vacía/duplicada;
- dispositivo vacío/duplicado;
- `ruta_imagen` vacía o externa al sistema;
- cantidad de concejales distinta de la cantidad total de bancas definida por la disposición configurada;
- bancas que no cubran completamente la disposición configurada.

Bloque vacío debe ser aceptado.

El archivo de padrón no contiene un campo de presencia: todos los concejales comienzan ausentes en cada preparación.

## CA-004 Autoridades obligatorias

No puede abrirse sesión sin número, Presidencia, Secretaría Legislativa y quórum.

## CA-005 Acreditación

En `PREPARANDO`, tecla `9` alterna presencia y esa presencia se conserva al abrir sesión.

Moderación no puede cambiarla manualmente.

## CA-006 Test

Tecla `8` produce únicamente el indicador visual temporal y funciona en `PREPARANDO`, `SESION_ABIERTA` y durante votación sin modificar otro estado.

## CA-007 Pulsaciones SIN_PREPARAR

Toda tecla recibida en `SIN_PREPARAR` carece de efecto funcional y no se agrega a los CSV de una preparación inexistente.

## CA-008 Cancelar preparación

Debe registrar cancelación, cerrar los tres CSV y volver a `SIN_PREPARAR`. Una nueva preparación comienza limpia y crea archivos diferentes.

## CA-009 Apertura con quórum

Con datos obligatorios y quórum, abrir sesión cambia a `SESION_ABIERTA` y conserva presentes.

## CA-010 Pérdida de quórum sin votación

La sesión permanece abierta, pero no se puede abrir votación. Al recuperar quórum, se vuelve a habilitar automáticamente.

## CA-011 Autoridades variables

Presidencia y Secretaría pueden cambiar durante preparación o sesión, incluso en votación, y cada cambio se registra sin alterar a ningún concejal.

## CA-012 Independencia Presidencia/Concejal

Si el texto de Presidencia coincide con una persona que también es concejal:

- no se realiza enlace automático;
- su estado de presencia/voto como concejal funciona normalmente;
- puede votar ordinariamente como concejal y luego desempatar como Presidente.

## CA-013 Orden del Día opcional

Debe poder abrirse sesión y realizarse votaciones sin cargar Orden del Día.

## CA-014 Orden del Día inválido

Un archivo técnicamente ilegible debe producir error de carga sin bloquear la sesión ni las votaciones manuales.

## CA-015 Orden del Día como asistencia

Seleccionar un punto debe copiar sus datos a un formulario editable. Debe permitirse tratar puntos en cualquier orden y crear propuestas fuera del archivo.

## CA-016 Numeración externa

El backend debe aceptar números de sesión/votación enteros estrictos `>= 1`, incluidos repetidos o fuera de secuencia, y rechazar cero, negativos, booleanos, decimales y texto.

## CA-017 Abrir votación sin quórum

Debe rechazarse.

## CA-018 Una votación activa

Debe rechazarse una segunda apertura si existe `EN_CURSO` o `EMPATADA` pendiente.

## CA-019 Inmutabilidad de votación

Después de abrir, no deben poder cambiarse id técnico, número, tema, tipo, tipo de mayoría, factor, base ni fecha/hora de apertura.

## CA-020 Voto ordinario

Con sesión/votación activa y concejal presente:

- 1 registra positivo;
- 2 registra abstención;
- 3 registra negativo.

Cada aceptación se registra inmediatamente.

## CA-021 Voto ausente

Un concejal ausente no puede votar.

## CA-022 Voto único

Un segundo intento del mismo concejal en la misma votación debe rechazarse sin alterar el primer voto.

## CA-023 Voto irreversible

No debe existir operación de Moderación ni física que cambie/elimine un voto aceptado.

## CA-024 Ausencia posterior al voto

Si un concejal vota y luego se ausenta, el voto permanece. Si vuelve a presentarse, sigue figurando como ya votado.

## CA-025 Incorporación durante votación

Un concejal ausente que pasa a presente durante `EN_CURSO` puede votar si todavía no lo hizo.

## CA-026 Autocierre

Cuando todos los concejales actualmente presentes votaron y se mantiene quórum, la recepción debe cerrarse automáticamente sin confirmación de Moderación. Queda `CERRADA`, con fecha/hora de cierre única y, bajo la misma serialización, calcula, audita y aplica el resultado ordinario; la pérdida de quórum no puede confundirse con este cierre normal.

## CA-027 Mayoría simple positiva

Con votos positivos > negativos, debe resultar `APROBADA` independientemente de la cantidad de abstenciones.

Ejemplo: 4 positivos, 3 negativos, 3 abstenciones => `APROBADA`.

## CA-028 Mayoría simple negativa

Con positivos < negativos => `RECHAZADA`.

## CA-029 Empate simple

Con positivos = negativos => `EMPATADA`, aunque existan abstenciones.

## CA-030 Mayoría especial distinta de simple

Una especial con factor `0.5` debe calcularse como especial y no usar la regla `positivos > negativos`. El campo `tipo_mayoria` es explícito y no se infiere desde el factor.

## CA-031 Especial sobre presentes

Ejemplo: 10 votos emitidos, 6 positivos, 3 negativos, 1 abstención, factor 0.6 => `APROBADA` porque `6/10 >= 0.6`.

La abstención integra el denominador. `PRESENTES` significa quienes emitieron voto en esa votación: retirarse después de votar no quita a la persona del denominador e incorporarse durante `EN_CURSO` permite integrarlo si alcanza a votar.

## CA-032 Igualdad de umbral

Si el cociente es exactamente igual al factor especial, debe aprobar. La comparación no usa redondeo ni tolerancia: `8/12` aprueba con el valor efectivo `2/3`, pero rechaza con factor `0.6666666667`.

## CA-033 Especial sobre cuerpo

Con 12 concejales cargados y factor 2/3, 8 positivos deben satisfacer el umbral aunque haya menos presentes, siempre que la votación pueda cerrar normalmente conforme a quórum/completitud.

Presidencia no agrega una unidad al denominador por ocupar ese rol.

Una mayoría especial también puede usar `VOTOS_COMPUTABLES` (positivos + negativos). Si esa base vale cero porque solo hubo abstenciones al cierre normal, resulta `RECHAZADA` sin dividir por cero.

## CA-034 Finalización anticipada

Moderación puede finalizar en cualquier momento, incluso con cero votos, pero debe proporcionar motivo.

Toda finalización manual válida desde `EN_CURSO` produce `INCONCLUSA`, conserva votos y no calcula resultado ordinario, aunque el conteo parcial parezca decisivo.

No debe existir división por cero.

## CA-035 Pérdida de quórum durante votación

Al caer presentes por debajo del quórum en `EN_CURSO`, debe pasar inmediatamente a `INCONCLUSA` y conservar votos previos. Esta evaluación tiene prioridad sobre el autocierre por completitud derivado de la misma presencia.

## CA-036 Inconclusa irreversible

Recuperar quórum posteriormente no debe reabrir ni recalcular esa votación.

## CA-037 Empate bloqueante

Mientras haya `EMPATADA`, la misma votación cerrada debe conservarse como activa y debe rechazarse abrir otra. `APROBADA` y `RECHAZADA` liberan la referencia activa después de auditar y aplicar el resultado.

## CA-038 Desempate presidencial

Una simple `EMPATADA` debe permitir desde Moderación únicamente `POSITIVO` o `NEGATIVO`.

El comando exacto `POST /api/v1/votaciones/{id}/desempate` valida bajo el serializador la sesión, la referencia/id, `CERRADA + EMPATADA + SIMPLE` y ausencia de voto previo. Toma la Presidencia vigente desde backend, sin recibirla del cliente ni exigir quórum posterior al empate.

Debe persistir primero `VOTO_DESEMPATE_PRESIDENCIAL`, almacenar un único voto irreversible, persistir después `VOTACION_RESULTADO_DESEMPATE`, cambiar a `APROBADA`/`RECHAZADA` según el sentido y recién entonces liberar la referencia activa.

Si falla el primer evento, no existe voto presidencial. Si falla el segundo, el voto permanece pero el resultado sigue `EMPATADA` y la votación continúa activa; no existe retry ni recovery en este alcance.

## CA-039 Desempate no ordinario

El voto presidencial conserva Presidencia y sentido sin DNI ni banca. No debe incrementar o modificar votos, positivos, negativos, abstenciones o denominadores, no recalcula SIMPLE y conserva exactamente la fecha de cierre original.

## CA-040 Especial sin desempate

Una votación `ESPECIAL` nunca debe entrar en flujo de desempate presidencial.

## CA-041 Empate y pérdida posterior de quórum

Si la votación ya terminó `EMPATADA`, una pérdida posterior de quórum no debe transformarla en inconclusa ni impedir que Presidencia desempate.

## CA-042 Cerrar sesión con EN_CURSO

Debe finalizar primero la misma votación como `INCONCLUSA`, incluso con cero votos o conteo parcial; luego cerrar sesión.

## CA-043 Cerrar sesión con EMPATADA

Debe convertir la misma instancia a `INCONCLUSA`, conservar la fecha de cierre y los votos, cerrar sesión y volver a `SIN_PREPARAR`.

## CA-044 Pedido de palabra

Concejal presente pulsa 7 => entra al final de la cola. Nueva pulsación => sale.

## CA-045 Uso propio

Si el orador pulsa 7, debe terminar su propio uso.

## CA-046 Otorgar con orador existente

Debe finalizar al orador actual y otorgar al siguiente de la cola.

## CA-047 Ausencia y palabra

Si pasa a ausente:

- en cola => se elimina;
- hablando => se finaliza su uso.

## CA-048 Palabra durante votación

Debe ser posible pedir, retirar, otorgar y finalizar palabra sin pausar ni detener la recepción de votos.

## CA-049 Moción que afecta votación

Moderación debe poder finalizarla manualmente con motivo; queda `INCONCLUSA`; luego puede abrir otra votación conforme al nuevo tratamiento.

## CA-050 Pantalla pública secreta

Durante `EN_CURSO`, la proyección pública no debe contener votos individuales ni eventos que los revelen, aunque se inspeccione la respuesta de red.

## CA-051 Revelado posterior

Al cerrarse, la Pantalla del Recinto puede recibir/mostrar votos individuales y resultado durante el tiempo configurado.

## CA-052 Moderación con retardo

Los votos individuales en Moderación solo deben revelarse según el retardo configurable vigente para esa preparación.

## CA-053 Registros nuevos por preparación

Cada preparación debe generar un conjunto de nombres diferente. Si el nombre correspondiente al segundo real de inicio ya existe, el nuevo conjunto usa, solo a efectos del nombre, el primer segundo posterior libre; nunca sobrescribe archivos existentes y los timestamps internos conservan la hora real.

## CA-054 Niveles acumulativos

Un evento L1 aparece solo en CSV1; L2 en CSV1+CSV2; L3 en CSV1+CSV2+CSV3.

## CA-055 Escritura inmediata

Después de una interacción aceptada relevante, el registro correspondiente debe estar persistido sin esperar al cierre de sesión.

## CA-056 Cierre de archivos

Tras cancelar preparación/cerrar sesión, esos CSV no deben volver a modificarse por SIS-Leg.

## CA-057 Caída técnica

Tras reiniciar durante preparación/sesión:

- estado `SIN_PREPARAR`;
- no reconstruir sesión anterior;
- CSV previos intactos hasta el último evento ya escrito.

## CA-058 Orden concurrente

Dos pulsaciones concurrentes deben producir un orden único y consistente de procesamiento/registro; no deben corromper el estado ni los archivos.

## CA-059 Configuración congelada

Cambiar archivos de configuración/padrón en disco durante una sesión no debe modificar la ejecución activa.

## CA-060 Remapeo futuro

Cuando se implemente el remapeo rápido, cambiar dispositivo durante una votación no debe modificar presencia, identidad ni votos previos y debe generar evento de registro.

## CA-061 Finalizaciones de palabra sin avance implícito

Con al menos dos pedidos de palabra y un orador actual:

- si el orador pulsa `7`, termina su uso y el siguiente permanece en cola;
- si Moderación ejecuta `Quitar palabra`, termina el uso y el siguiente permanece en cola;
- si el orador pasa a ausente, termina su uso y el siguiente permanece en cola.

En los tres casos debe requerirse una acción posterior de `Otorgar palabra` para que el siguiente pase a ser orador.

Si un concejal que espera en cola pasa a ausente, se elimina de la cola y pierde su posición.

## CA-062 Advertencia al abrir votación con palabra pendiente

Con sesión abierta y condiciones válidas para votar, si existe un orador o al menos un pedido de palabra en cola, pulsar `Abrir votación` en Moderación debe mostrar una advertencia antes de enviar el comando.

- cancelar no abre la votación ni modifica palabra/cola;
- confirmar abre normalmente si el backend la acepta;
- después de abrir, el orador y la cola permanecen intactos y el uso de palabra continúa funcionando durante `EN_CURSO`.

La ausencia de orador y de pedidos no debe generar esta advertencia.

## CA-063 Advertencia al cerrar sesión con palabra pendiente

Si existe un orador o al menos un pedido de palabra en cola, pulsar `Cerrar sesión` en Moderación debe mostrar una advertencia antes de enviar el comando.

- cancelar deja la sesión abierta y no modifica palabra/cola;
- confirmar continúa con el flujo normal de cierre, incluidas las reglas sobre votación `EN_CURSO` o `EMPATADA` si correspondieran;
- la advertencia no debe convertirse en un rechazo reglamentario del backend.

La ausencia de orador y de pedidos no debe generar esta advertencia.

## Criterios técnicos mínimos futuros

Además de estos escenarios funcionales, antes de integrar código deberá exigirse:

- pruebas unitarias del dominio/backend;
- pruebas de integración de API;
- pruebas de componentes frontend donde aporten valor;
- E2E de recorridos críticos;
- simulador de entradas físicas para CI/desarrollo;
- lint/typecheck/format automatizados;
- ausencia de secretos y datos reales en el repositorio;
- compatibilidad con el despliegue objetivo definido;
- trazabilidad de PR con reglas/casos de uso afectados.
