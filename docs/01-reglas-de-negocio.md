# 01 - Reglas de negocio

Este documento es normativo.

## RN-GLOBAL - Ciclo general

### RN-GLOBAL-01
El sistema solo puede estar en `SIN_PREPARAR`, `PREPARANDO` o `SESION_ABIERTA`.

### RN-GLOBAL-02
Cancelar la preparación o cerrar la sesión devuelve el sistema a `SIN_PREPARAR` y elimina todo estado operativo en memoria.

### RN-GLOBAL-03
El estado activo no se persiste para recuperación. Tras un reinicio se vuelve a `SIN_PREPARAR`.

### RN-GLOBAL-04
Una interrupción técnica no permite continuar la sesión anterior. Debe realizarse una nueva preparación y apertura reglamentaria.

## RN-PREP - Preparación del recinto

### RN-PREP-01
`Preparar recinto` carga configuración y padrón, inicia tres CSV, deja a todos los concejales ausentes y habilita únicamente presencia y test físico.

### RN-PREP-02
Durante `PREPARANDO` deben informarse número de sesión, Presidencia y Secretaría Legislativa.

### RN-PREP-03
Una sesión solo puede abrirse si existe quórum y están definidos número de sesión, Presidencia y Secretaría Legislativa.

### RN-PREP-04
Las presencias acreditadas durante `PREPARANDO` se conservan al abrir la sesión.

### RN-PREP-05
Una preparación puede cancelarse. La cancelación se registra y los CSV generados se conservan.

### RN-PREP-06
Toda nueva preparación comienza limpia: sin presencias, cola de palabra, orador, votación ni test previo.

## RN-AUT - Autoridades

### RN-AUT-01
Presidencia y Secretaría Legislativa se ingresan como texto libre.

### RN-AUT-02
Ambas autoridades pueden cambiar durante `PREPARANDO` o `SESION_ABIERTA`, incluso durante una votación. Cada cambio se registra.

### RN-AUT-03
Presidencia es un rol independiente del rol Concejal. El sistema no debe intentar vincular automáticamente el texto del Presidente con el padrón.

### RN-AUT-04
Si una persona que es concejal también ejerce la Presidencia, ambos roles funcionan como identidades funcionales independientes: conserva presencia, quórum, uso de palabra y voto ordinario como concejal, y suma las facultades presidenciales.

### RN-AUT-05
El estado presente/ausente de esa persona como concejal no afecta su rol de Presidente.

### RN-AUT-06
Secretaría Legislativa no tiene acciones funcionales en SIS-Leg y no puede ser reemplazada por un concejal según el caso de negocio contemplado.

## RN-CON - Concejales y padrón

### RN-CON-01
El DNI es el identificador primario del concejal.

### RN-CON-02
Son obligatorios DNI, nombre, apellido, banca, dispositivo de votación y ruta interna de imagen.

### RN-CON-03
DNI, banca y dispositivo de votación deben ser únicos. Valores vacíos, inválidos o duplicados bloquean la carga. `bloque` puede estar vacío.

### RN-CON-04
La cantidad de concejales del padrón debe coincidir exactamente con la cantidad total de bancas definida por la disposición configurada. Las bancas deben ser únicas, válidas y cubrir completamente esa disposición.

### RN-CON-05
Cada concejal debe tener una `ruta_imagen` interna al sistema. No se utiliza una asociación de imágenes hardcodeada por número de banca.

### RN-CON-06
La presencia es un dato exclusivamente dinámico y no forma parte del archivo de padrón. Toda preparación comienza con todos los concejales ausentes.

### RN-CON-07
El padrón se carga al preparar el recinto y queda congelado hasta finalizar la preparación/sesión.

### RN-CON-08
La única excepción futura será el remapeo rápido de dispositivo en memoria, que no modifica el padrón base.

## RN-INP - Dispositivos físicos

Mapa funcional:

- `1`: positivo;
- `2`: abstención;
- `3`: negativo;
- `7`: pedir/retirar palabra o terminar uso propio;
- `8`: test visual;
- `9`: alternar presencia.

### RN-INP-01
En `SIN_PREPARAR` ninguna pulsación produce efecto funcional ni se incorpora a los CSV de una sesión.

### RN-INP-02
En `PREPARANDO` solo tienen efecto funcional `8` y `9`.

### RN-INP-03
El test `8` es puramente visual, debe funcionar durante preparación, sesión y votación, y nunca modifica estado de negocio.

### RN-INP-04
Moderación no puede emitir presencia ni votos ordinarios en nombre de un concejal.

## RN-PRE - Presencia y quórum

### RN-PRE-01
Todos los concejales comienzan ausentes al preparar el recinto.

### RN-PRE-02
La presencia solo puede alternarse desde el dispositivo asignado al concejal mediante tecla `9`.

### RN-PRE-03
Presidencia no se acredita como autoridad y no cuenta para quórum por ocupar ese rol. Si quien preside además es concejal, cuenta para quórum únicamente por su rol de concejal y su estado de presencia.

### RN-PRE-04
No puede abrirse una sesión sin quórum.

### RN-PRE-05
Si durante una sesión abierta se pierde quórum y no hay votación en curso, la sesión continúa pero no puede abrirse una nueva votación.

### RN-PRE-06
Al recuperar automáticamente el quórum, vuelve a habilitarse la apertura de votaciones sin acción adicional.

### RN-PRE-07
Si se pierde quórum durante una votación `EN_CURSO`, esa misma votación termina inmediatamente como `CERRADA + INCONCLUSA`, conserva sus votos y libera la referencia activa. Esta evaluación precede a cualquier autocierre por completitud derivado del mismo cambio de presencia.

### RN-PRE-08
Un concejal puede pasar a ausente después de votar; su voto permanece registrado e inmutable.

### RN-PRE-09
Un concejal puede pasar de ausente a presente durante una votación y votar normalmente si aún no emitió voto.

### RN-PRE-10
Si un concejal ya votó, se ausenta y luego vuelve a presentarse durante la misma votación, continúa considerado como ya votado y no puede votar nuevamente.

### RN-PRE-11
Cambiar presencia durante una votación puede provocar cierre automático si se mantiene quórum y todos los concejales que continúan presentes ya emitieron su voto. Si el mismo cambio también deja al cuerpo sin quórum, prevalece RN-PRE-07 y no se calcula un resultado ordinario.

## RN-VOT - Votaciones

### RN-VOT-01
Solo puede existir una votación activa por vez.

### RN-VOT-02
No puede abrirse una votación sin sesión abierta ni quórum.

### RN-VOT-03
Una votación abierta conserva inmutables su id técnico, número, tipo, tema, tipo de mayoría, factor, base y fecha/hora de apertura. Para corregir datos institucionales debe finalizarse como `INCONCLUSA` y abrirse otra.

### RN-VOT-04
Número de votación y número de sesión son datos externos. El sistema no valida secuencia, unicidad ni repetición.

### RN-VOT-05
Cada concejal puede emitir un solo voto ordinario por votación. Es irreversible y no puede corregirse desde Moderación.

### RN-VOT-06
Una votación se cierra automáticamente cuando todos los concejales actualmente presentes ya votaron y se mantiene quórum. Ese cierre termina la recepción y fija una única fecha/hora. Bajo la misma serialización, el backend calcula, audita y aplica inmediatamente el resultado ordinario sobre la misma instancia; el cierre y el resultado son hechos institucionales separados.

### RN-VOT-07
Moderación puede finalizar una votación en cualquier momento mientras permanece `EN_CURSO`. El comando manual siempre produce `CERRADA + INCONCLUSA`, incluso con cero votos o con un conteo parcial aparentemente decisivo; no calcula mayoría ordinaria.

### RN-VOT-08
La finalización manual anticipada exige motivo obligatorio y dicho motivo se registra.

### RN-VOT-09
No existe estado `PAUSADA` ni `CANCELADA`. Una cancelación operativa se representa como finalización `INCONCLUSA`.

### RN-VOT-10
Una votación `INCONCLUSA` terminó definitivamente. Para volver a tratar el asunto debe abrirse otra votación.

### RN-VOT-11
Los votos emitidos antes de una votación `INCONCLUSA` permanecen registrados individualmente.

### RN-VOT-12
Una votación cerrada nunca se recalcula por cambios posteriores de presencia.

### RN-VOT-13
Cerrar la sesión con una votación `EN_CURSO` provoca primero su finalización como `INCONCLUSA` sobre la misma instancia y luego cierra la sesión. Si la votación estaba `CERRADA + EMPATADA`, el cierre explícito de sesión la convierte en `INCONCLUSA` conservando su fecha de cierre y sus votos.

### RN-VOT-14
Una votación empatada bloquea la apertura de otra hasta resolverse o hasta que se cierre la sesión.

### RN-VOT-15
Si se cierra la sesión con una votación `EMPATADA`, esa votación pasa a `INCONCLUSA` y luego se cierra la sesión.

### RN-VOT-16
Una votación `APROBADA` o `RECHAZADA` deja de ocupar la referencia activa después de auditar y aplicar el resultado, pero permanece en el historial. Una `EMPATADA` conserva la misma referencia activa y continúa bloqueando otra apertura.

## RN-MAY - Mayorías

### RN-MAY-01
`SIMPLE` y `ESPECIAL` son tipos de mayoría distintos y explícitos; no se infieren a partir del factor. Una mayoría simple admite factor omitido, nulo o numéricamente `0`, se normaliza a `factor = 0` y nunca se representa como factor `0.5`.

### RN-MAY-02 - Mayoría simple
Usa siempre la base `VOTOS_COMPUTABLES`, definida como positivos + negativos:

- positivos > negativos: `APROBADA`;
- positivos < negativos: `RECHAZADA`;
- positivos = negativos: `EMPATADA`.

Las abstenciones se excluyen del cálculo de mayoría simple.

### RN-MAY-03
Solo una mayoría simple puede terminar `EMPATADA` y requerir desempate presidencial.

### RN-MAY-04 - Mayoría especial
Tiene factor real finito explícito `> 0` y `<= 1`, y base de cálculo `VOTOS_COMPUTABLES`, `PRESENTES` o `CUERPO`.

`VOTOS_COMPUTABLES` usa positivos + negativos. Las abstenciones no integran el denominador; si este vale cero porque solo hubo abstenciones en un cierre normal, el resultado es `RECHAZADA` sin realizar división.

### RN-MAY-05
Una mayoría especial aprueba cuando el cociente aplicable es `>= factor`. Alcanzar exactamente el umbral aprueba. La comparación utiliza el valor numérico congelado sin redondeo, epsilon, tolerancia ni conversión a otra fracción.

### RN-MAY-06 - Especial sobre presentes
`PRESENTES` denomina institucionalmente a quienes emitieron voto ordinario en esa votación. El denominador técnico son positivos + negativos + abstenciones y no se reduce si alguien se retira después de votar.

### RN-MAY-07
Aunque el cálculo anterior use votos emitidos, una finalización manual con presentes sin votar es `INCONCLUSA`; por tanto, un resultado ordinario solo se consolida cuando votaron todos los presentes.

### RN-MAY-08 - Especial sobre cuerpo
El denominador es la cantidad total de concejales del cuerpo cargado para la preparación. Presidencia no se suma por su rol institucional.

### RN-MAY-09
Una mayoría especial nunca utiliza voto presidencial de desempate.

### RN-MAY-10
Una finalización sin votos debe producir `INCONCLUSA` sin errores matemáticos.

## RN-DES - Desempate presidencial

### RN-DES-01
Solo está disponible cuando una votación de mayoría simple está `EMPATADA`.

### RN-DES-02
El voto de Presidencia se emite desde el frontend de Moderación, no desde teclado físico.

### RN-DES-03
Presidencia debe elegir positivo o negativo; no existe abstención en desempate.

### RN-DES-04
El voto de desempate es irreversible.

### RN-DES-05
Si quien preside además es concejal y ya emitió su voto ordinario, igualmente puede emitir el desempate: son roles independientes.

### RN-DES-06
La pérdida posterior de quórum mientras una votación ya está `EMPATADA` no invalida el empate ni impide el desempate.

### RN-DES-07
El registro debe indicar explícitamente el sentido del voto presidencial y el resultado final.

### RN-DES-08
El único comando REST de desempate es `POST /api/v1/votaciones/{id}/desempate`, con body cerrado `{ "sentido": "POSITIVO|NEGATIVO" }`. El id debe coincidir con la votación activa al ejecutar dentro del serializador, para que una intención obsoleta nunca afecte una votación posterior.

### RN-DES-09
La identidad autora se toma de la Presidencia vigente en la sesión dentro del `EjecutorMutaciones`; no se recibe ni se infiere desde el frontend o el padrón. Un cambio posterior de autoridad no modifica el voto presidencial ya almacenado.

### RN-DES-10
El desempate no exige quórum: la votación ya permanece `CERRADA + EMPATADA`. La apertura de una votación posterior sí vuelve a evaluar el quórum vigente mediante sus precondiciones normales.

### RN-DES-11
El voto presidencial se conserva una única vez como `VotoDesempate` separado e inmutable, con Presidencia y sentido. No tiene DNI ni banca, no se agrega a `votos_ordinarios` y no modifica positivos, negativos, abstenciones ni denominadores.

### RN-DES-12
El desempate registra dos hechos L3 distintos bajo una sola adquisición: primero `VOTO_DESEMPATE_PRESIDENCIAL`, antes de almacenar el voto; luego `VOTACION_RESULTADO_DESEMPATE`, antes de aplicar el resultado y liberar la referencia activa. `POSITIVO` deriva directamente en `APROBADA` y `NEGATIVO` en `RECHAZADA`, sin recalcular la mayoría simple.

### RN-DES-13
Si falla el primer hecho, la votación continúa `EMPATADA`, activa y sin voto presidencial. Si falla el segundo después de almacenar el voto, continúa `EMPATADA`, activa y con ese `VotoDesempate` irreversible. En ambos casos el writer queda en fallo cerrado y no se implementan rollback, retry ni recovery.

### RN-DES-14
Un desempate exitoso conserva exactamente la fecha de cierre y los votos ordinarios de la misma instancia, aplica el resultado final y recién entonces deja `votacion_activa = None`.

## RN-PAL - Uso de la palabra

### RN-PAL-01
Solo un concejal presente puede pedir palabra.

### RN-PAL-02
La tecla `7` alterna al concejal en la cola FIFO de pedidos.

### RN-PAL-03
Si quien pulsa `7` está actualmente usando la palabra, finaliza su propio uso.

### RN-PAL-04
La acción `Otorgar palabra` de Moderación, cuando ya existe un orador, finaliza automáticamente al actual y entrega la palabra al primero de la cola. Si no existe un pedido en cola, no queda un nuevo orador.

### RN-PAL-05
Si el orador pasa a ausente, pierde automáticamente el uso de la palabra.

### RN-PAL-06
Si un concejal en cola pasa a ausente, se elimina automáticamente de la cola y pierde ese lugar.

### RN-PAL-07
Los pedidos y usos de palabra continúan funcionando durante una votación. Es una situación normal: pueden justificar votos o formular mociones mientras la votación sigue recibiendo votos.

### RN-PAL-08
Si una moción obliga a modificar el tratamiento de una votación en curso, Moderación debe finalizar la votación como `INCONCLUSA` y continuar la sesión según lo resuelto.

### RN-PAL-09
`Quitar palabra` desde Moderación finaliza al orador actual y **no** otorga automáticamente la palabra al siguiente de la cola. Los pedidos pendientes conservan su orden.

### RN-PAL-10
Cuando el propio orador finaliza su uso mediante tecla `7`, **no** se otorga automáticamente la palabra al siguiente de la cola.

### RN-PAL-11
Cuando un orador pierde el uso por pasar a ausente, **no** se otorga automáticamente la palabra al siguiente. El siguiente pedido permanece en cola hasta que Moderación ejecute `Otorgar palabra`.

### RN-PAL-12
Si existe un orador actual o al menos un pedido en cola, la interfaz de Moderación debe advertir y pedir confirmación antes de **abrir una nueva votación** o **cerrar la sesión**. Cancelar la advertencia no envía el comando; confirmar permite continuar. Esta advertencia es una salvaguarda operativa de la interfaz, no una nueva precondición reglamentaria del backend. Al abrir una votación confirmada, el orador y la cola permanecen sin cambios y continúan operativos durante la votación.

## RN-OD - Orden del Día

### RN-OD-01
El Orden del Día es opcional y sirve exclusivamente como asistencia para ahorrar carga manual.

### RN-OD-02
El sistema solo valida que el archivo sea técnicamente interpretable. No valida contenido, numeración, secuencia, repetición ni corrección institucional.

### RN-OD-03
Un archivo ilegible se rechaza sin impedir preparar, abrir sesión ni crear votaciones manuales.

### RN-OD-04
Seleccionar un punto copia sus datos al formulario y Moderación puede modificarlos antes de abrir la votación.

### RN-OD-05
Moderación puede crear votaciones fuera del Orden del Día y tratar los puntos cargados en cualquier orden.

## RN-LOG - Registro electrónico

### RN-LOG-01
Al iniciar `PREPARANDO` se crean tres archivos CSV jerárquicos asociados a esa preparación/sesión.

### RN-LOG-02
Los nombres contienen fecha y hora local de inicio con precisión de segundos. Si excepcionalmente el nombre correspondiente a ese segundo ya existe, solo a efectos del nombre del nuevo conjunto se avanza un segundo, repitiendo hasta encontrar un nombre libre. Los timestamps internos de los eventos conservan siempre la hora real.

### RN-LOG-03
Nivel 1 contiene eventos L1+L2+L3; nivel 2 contiene L2+L3; nivel 3 contiene solo L3.

### RN-LOG-04
Cada evento se escribe inmediatamente en disco.

### RN-LOG-05
Se utiliza hora local del servidor con precisión de segundos.

### RN-LOG-06
El orden secuencial en que el backend procesa y registra interacciones constituye el orden oficial del sistema.

### RN-LOG-07
Cancelar preparación y cerrar sesión escriben un evento final y cierran definitivamente los tres archivos.

### RN-LOG-08
Ante caída abrupta, los CSV quedan hasta el último evento persistido y no se modifican retrospectivamente.

### RN-LOG-09
Los archivos cerrados no son editables desde SIS-Leg. Pueden ser corregidos externamente si el procedimiento institucional lo requiere.

### RN-LOG-10
La profundidad y categorías de eventos deben conservar la lógica funcional de la implementación vigente, adaptada a CSV y extendida con las nuevas reglas documentadas.

## RN-CFG - Configuración

### RN-CFG-01
Quórum, tipos de votación, temporizadores, disposición de bancas y demás configuración se cargan al iniciar `PREPARANDO` y quedan congelados hasta finalizar.

### RN-CFG-02
Cambiar archivos de configuración en disco durante una sesión no altera el estado activo.

### RN-CFG-03
Los tipos de votación se administran mediante archivo de configuración, no desde la interfaz cotidiana.

### RN-CFG-04
La visibilidad de votos individuales en Moderación utiliza un retardo configurable.

### RN-CFG-05
Los temporizadores de pantalla son configurables. Valores iniciales de referencia: 4 segundos para retardo/cuenta regresiva y 6 segundos para permanencia del resultado.

## RN-MAP - Remapeo pendiente

### RN-MAP-01
Debe contemplarse arquitectónicamente un mecanismo de remapeo rápido de dispositivo a concejal ante una falla física.

### RN-MAP-02
Podrá ejecutarse durante una sesión e incluso durante una votación.

### RN-MAP-03
No modifica presencia, voto ya emitido ni identidad del concejal.

### RN-MAP-04
Se registra como evento.

### RN-MAP-05
Afecta únicamente el mapeo operativo en memoria y no modifica automáticamente el archivo base.
