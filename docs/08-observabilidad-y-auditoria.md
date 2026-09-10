# 08 - Observabilidad y auditoría

## 1. Principio institucional

El registro electrónico forma parte del comportamiento funcional del sistema, no es solo diagnóstico técnico.

Desde `PREPARANDO` hasta cancelación/cierre deben registrarse inmediatamente las interacciones relevantes.

La primera versión no usa base de datos para auditoría ni para recuperar estado.

## 2. Tres niveles acumulativos

Se conserva la lógica de profundidad de la implementación actual:

- archivo nivel 1: eventos L1 + L2 + L3;
- archivo nivel 2: eventos L2 + L3;
- archivo nivel 3: solo eventos L3.

Interpretación general:

- **L1:** máximo detalle técnico/operativo;
- **L2:** operación normal, entradas, rechazos y diagnóstico útil;
- **L3:** hechos institucionales y funcionales importantes.

La asignación concreta de cada evento debe conservar el espíritu de producción y extenderlo para cubrir las nuevas reglas.

## 3. Formato CSV canónico

SIS-Leg utiliza **CSV** con:

```text
seq;timestamp;level;tag;event_code;message
```

Reglas:

- delimitador `;`;
- UTF-8 con BOM;
- timestamp `AAAA-MM-DD HH:MM:SS`;
- hora local del servidor;
- precisión a segundos;
- `seq` monotónico dentro de la preparación/sesión;
- `event_code` estable y legible por máquina;
- `message` legible por personas.

Los códigos estructurados no reemplazan la descripción humana.

## 4. Ciclo y nombres de archivos

Al ejecutar `Preparar recinto` se toma fecha/hora local real del servidor y se crea un conjunto nuevo:

```text
logs/
└── AAAA-MM-DD/
    ├── AAAA-MM-DD_HH-MM-SS-L1.csv
    ├── AAAA-MM-DD_HH-MM-SS-L2.csv
    └── AAAA-MM-DD_HH-MM-SS-L3.csv
```

La marca temporal del nombre se usa para evitar superposición entre múltiples preparaciones/sesiones del mismo día.

Si excepcionalmente ya existe un conjunto con la marca correspondiente al segundo real de inicio, **no se agrega un sufijo**. Solo a efectos del nombre se avanza la marca un segundo y se repite hasta encontrar el primer segundo libre. Si ese avance cambia de fecha, se utiliza también la carpeta correspondiente a la fecha nominal resultante.

Esta corrección de nombre no altera la hora real de la preparación ni los timestamps internos de los eventos, que siempre conservan la hora real del servidor.

Al cancelar preparación o cerrar sesión:

- se escribe el evento final;
- se cierra el conjunto;
- SIS-Leg no vuelve a modificar esos archivos.

## 4 bis. Informe de acta y copia externa opcional (WP-085)

Al **cerrar una sesión** —no al cancelar una preparación— el conjunto ya cerrado produce
un cuarto archivo derivado, en el mismo directorio y con el mismo prefijo temporal:

```text
logs/
└── AAAA-MM-DD/
    ├── AAAA-MM-DD_HH-MM-SS-L1.csv
    ├── AAAA-MM-DD_HH-MM-SS-L2.csv
    ├── AAAA-MM-DD_HH-MM-SS-L3.csv
    └── AAAA-MM-DD_HH-MM-SS-ACTA.txt
```

El informe es texto plano UTF-8 y se deriva del **archivo L3 físico completo**, no del
buffer de eventos recientes que alimenta la proyección de Moderación: una sesión larga
supera holgadamente ese buffer y el acta debe contener todos sus eventos.

Formato aprobado:

```text
SIS-Leg
Registro de eventos para acta institucional
Fecha: DD/MM/AAAA

HH:MM:SS — texto del evento
HH:MM:SS — Inicio: texto del marcador
HH:MM:SS — Fin: texto del marcador
```

- una línea por fila del L3, en el orden en que fueron persistidas;
- no aparecen `seq`, `level`, `tag`, `event_code`, ids técnicos ni emojis;
- los marcadores `EVENTO/INICIO` y `EVENTO/FIN` (WP-078) se distinguen con los prefijos
  `Inicio:` y `Fin:`, porque sin ellos dos líneas de texto idéntico serían
  indistinguibles;
- cada familia L3 tiene una redacción explícita: conserva el hecho institucional útil y
  descarta identificadores, fingerprints, dispositivos, posiciones y banderas que el
  `message` durable necesita para la trazabilidad técnica;
- una familia desconocida, un encabezado distinto del canónico, una fila con más o menos de
  seis columnas o un timestamp inválido hacen fallar el informe completo. Ninguna fila se
  repara ni se omite silenciosamente; los tres CSV cerrados permanecen intactos y siguen
  siendo la evidencia autoritativa.

Si además existe `paths.logs_copy_dir` en `system.toml`, los cuatro archivos se copian a
`<logs_copy_dir>/AAAA-MM-DD/`. Es una ruta de sistema de archivos que el sistema operativo
ya debe tener montada: SIS-Leg no implementa cliente SMB ni NFS ni guarda credenciales.

Reglas que no se pueden reinterpretar:

- los CSV locales siguen siendo el registro institucional; el TXT es derivación y la copia
  externa es redundancia;
- ambos pasos ocurren **después** del cierre durable, así que un fallo suyo nunca convierte
  un cierre exitoso en un error ni deja la sesión abierta;
- los archivos locales no se mueven ni se borran;
- un nombre ya ocupado en el destino no se sobrescribe: se trata como falla de copia;
- sin la clave configurada no hay intento de acceso externo ni aviso en Moderación.

Moderación informa el desenlace con un aviso efímero: confirmación cuando la copia se
completó, y advertencia que empieza aclarando que **la sesión sí cerró** cuando el informe
o la copia fallaron.

## 5. Persistencia inmediata y durabilidad

Cada evento se escribe sin acumularlo hasta el cierre.

Por cada persistencia obligatoria se realiza, bajo el mecanismo que serializa las operaciones del backend:

1. escritura de la fila;
2. `flush`;
3. `fsync`.

Una operación que requiera registro no debe confirmarse como exitosa antes de garantizar la persistencia definida.

## 6. Fallo cerrado de auditoría

Si durante `PREPARANDO` o `SESION_ABIERTA` deja de ser posible garantizar escritura en los CSV:

- el sistema debe exponer una falla técnica grave a Moderación;
- no debe continuar aceptando nuevas operaciones que muten estado como si la auditoría siguiera disponible;
- no debe confirmar parcialmente una operación cuyos registros obligatorios no pudieron persistirse coherentemente.

El detalle de la transición técnica a modo de fallo debe implementarse sin inventar un nuevo estado reglamentario de sesión.

## 7. Interrupciones abruptas

Ante caída del proceso/equipo:

- no existe garantía de poder escribir un evento final;
- los CSV quedan terminados en el último evento persistido;
- al reiniciar no se buscan ni reparan archivos anteriores;
- no se agrega retrospectivamente una marca de interrupción;
- el sistema vuelve a `SIN_PREPARAR`.

## 8. Orden de eventos

Las entradas concurrentes se serializan en el backend.

El orden en que el backend acepta, procesa y persiste los eventos es el orden oficial del sistema.

`seq` representa ese orden dentro del conjunto de archivos de una preparación/sesión.

## 9. Categorías mínimas

Deben registrarse apropiadamente, según nivel:

- inicio/cancelación de preparación;
- cambios de Presidencia;
- cambios de Secretaría Legislativa;
- apertura/cierre de sesión;
- pulsaciones físicas recibidas durante una preparación/sesión;
- presencia/ausencia;
- test de dispositivo cuando corresponda al nivel detallado;
- pedidos/retiros de palabra;
- otorgamiento/finalización de palabra;
- apertura de votación;
- voto ordinario individual;
- rechazos de voto/interacción;
- autocierre;
- pérdida de quórum;
- finalización manual y motivo;
- resultado;
- empate;
- voto presidencial de desempate explícito `POSITIVO/NEGATIVO`;
- resultado posterior al desempate;
- remapeo físico de dispositivo cuando se implemente;
- errores técnicos relevantes.

Las mutaciones directas de palabra utilizan hechos L3 con etiqueta `PALABRA`:

- `PEDIDO_PALABRA_REGISTRADO`;
- `PEDIDO_PALABRA_RETIRADO`;
- `USO_PALABRA_OTORGADO`;
- `USO_PALABRA_FINALIZADO`.

Cada mensaje identifica DNI, nombre/apellido y banca; la finalización explicita
la causa `PROPIO` o `MODERACION`. Los no-op de Moderación registran únicamente
el diagnóstico L2 `COMANDO_PALABRA_SIN_EFECTO`, sin inventar hechos L3.

Si `Otorgar palabra` reemplaza a un orador, primero persiste y aplica
`USO_PALABRA_FINALIZADO`; después persiste `USO_PALABRA_OTORGADO` y recién
entonces retira el primer pedido e instala el nuevo orador. Si falla el segundo
evento, no se revierte el primero: queda sin orador y el pedido continúa primero
en la cola.

Cuando `CONCEJAL_AUSENTE` también elimina un pedido o finaliza un uso, su mensaje
explicita `pedido_palabra_retirado=true` y/o
`uso_palabra_finalizado=true`. Ese único hecho L3 se persiste antes de cambiar
presencia y palabra; luego continúan los efectos derivados de votación.

Para la recepción ordinaria, cada aceptación persiste un evento L3 `VOTO_ORDINARIO_REGISTRADO` antes de incorporar el voto. Los intentos rechazados permanecen como `PULSACION_RECHAZADA` L2 con motivo estable y no crean un voto ficticio. El autocierre persiste un evento L3 separado `VOTACION_CERRADA_COMPLETITUD` antes de cambiar la recepción a `CERRADA`; ese evento no declara resultado de mayoría.

Si el voto o la presencia que completan la recepción ya fueron auditados y aplicados, pero falla la persistencia del evento derivado de autocierre, el hecho previo no se revierte. La recepción permanece `EN_CURSO`, el writer queda en fallo cerrado y no se informa éxito técnico de la operación externa.

Después de un autocierre exitoso, el resultado ordinario se persiste como otro evento L3 antes de mutar `Votacion.resultado`:

- `VOTACION_RESULTADO_FINAL` distingue `APROBADA` o `RECHAZADA` mediante el mensaje;
- `VOTACION_RESULTADO_EMPATE` identifica inequívocamente `EMPATADA`.

El mensaje registra número e id de votación, tipo de mayoría, positivos, negativos, abstenciones y resultado. SIMPLE explicita que las abstenciones quedaron fuera de la comparación. ESPECIAL agrega base, denominador, factor y cociente; si `VOTOS_COMPUTABLES=0`, registra que el cociente no fue calculado y que se evitó la división.

Si el cierre ya fue persistido y aplicado pero falla el evento de resultado, no se revierte el cierre. La votación permanece `CERRADA + resultado=None`, conserva su fecha y la referencia activa, el writer queda en fallo cerrado y la operación externa no informa éxito.

Toda transición a `INCONCLUSA` persiste primero el evento L3 `VOTACION_FINALIZADA_INCONCLUSA`. El mensaje identifica número e id, causa (`MANUAL`, `PERDIDA_QUORUM` o `CIERRE_SESION`), estado y resultado previos, cantidad de votos conservados y resultado nuevo. La causa manual agrega el motivo humano normalizado; la pérdida de quórum agrega presentes posteriores y quórum requerido. Los rechazos funcionales del comando manual que alcanzan un contexto auditable usan un evento L2 estable antes de responder.

Si falla ese evento, no se aplica la transición ni se libera la referencia activa. Cuando la causa fue una presencia ya auditada y aplicada, esa presencia no se revierte: la votación sigue `EN_CURSO + resultado=None` porque representa el último hecho durable. En el cierre de sesión, si la transición a `INCONCLUSA` ya fue auditada y aplicada pero luego falla `SESION_CERRADA`, tampoco se revierte; la sesión permanece abierta en memoria y la referencia activa queda liberada. Si `SESION_CERRADA` persistió pero falla el cierre físico del writer, se conserva el contexto conforme al fallo cerrado existente.

El desempate presidencial persiste dos hechos L3 diferenciados bajo la misma adquisición. `VOTO_DESEMPATE_PRESIDENCIAL` registra número/id, Presidencia vigente, sentido, `estado_previo=CERRADA`, `resultado_previo=EMPATADA` y los conteos ordinarios preservados antes de almacenar el voto. Con ese voto ya durable y almacenado, `VOTACION_RESULTADO_DESEMPATE` registra la misma identidad/sentido, el empate previo, `resultado_final=APROBADA|RECHAZADA` y los mismos conteos antes de aplicar el resultado y liberar la referencia activa.

Si falla el primer evento, no se almacena voto presidencial. Si falla el segundo, no se revierte el primer hecho: la misma votación conserva `CERRADA + EMPATADA`, el `VotoDesempate` y la referencia activa, sin publicar un resultado no auditado. En ambos casos el writer queda en fallo cerrado. Los rechazos funcionales del comando usan `COMANDO_VOTACION_RECHAZADO` L2 con operación, id solicitado y código estable; una falla de ese rechazo prevalece como indisponibilidad de auditoría.

Los avisos que Apoyo Técnico dirige a la Pantalla del Recinto (destino `RECINTO`
o `AMBOS`) delimitan además un momento de la sesión y registran dos hechos L3
con etiqueta general `EVENTO`:

- `INICIO` cuando el texto aparece efectivamente en el Recinto;
- `FIN` cuando deja de mostrarse, con exactamente el mismo texto.

El `message` de ambos es el texto del aviso tal como se publicó, sin prefijos,
destino, duración ni identificadores internos. La etiqueta es deliberadamente
`EVENTO` y no `APOYO_TECNICO`: estos registros representan momentos generales de
la sesión, no la mensajería del puesto técnico. La auditoría técnica L2
`AVISO_TECNICO_PUBLICADO` / `AVISO_TECNICO_CANCELADO` se conserva sin cambios y
es adicional a estos marcadores.

Un aviso dirigido únicamente a `MODERACION` no genera marcadores. Un aviso
`AMBOS` genera una única pareja, la correspondiente a su presencia en Recinto:
cancelar solamente la ranura de Moderación no cierra el período.

El `FIN` se registra por cualquier causa válida de desaparición —cancelación
manual que alcanza Recinto, vencimiento por duración o reemplazo por otro aviso
que alcanza Recinto— y en un reemplazo precede al `INICIO` del texto nuevo
dentro de la misma mutación. La vigencia nunca se decide interpretando textos:
la autoridad es el período abierto que el estado operativo conserva junto con el
`aviso_id`, de modo que un mismo período no puede producir más de un `INICIO` ni
más de un `FIN` aunque coincidan temporizador, cancelación y reintento. El
vencimiento automático se convierte en hecho durable desde el temporizador único
de fronteras temporales, sin introducir polling.

La autoridad de ese cierre es el reloj, no la mecánica interna del temporizador.
El sistema comprueba en cada vuelta si quedó un período abierto cuyo aviso ya
venció, y en ese caso lo cierra, sin importar por qué causa despertó el ciclo ni
en qué orden se hayan resuelto sus esperas. La garantía no puede depender de esa
mecánica porque una mutación ajena simultánea reconstruye la proyección y retira
el aviso vencido de la pantalla sin registrar nada, y un aviso ya vencido no
vuelve a aportar una frontera futura: un cierre omitido se perdería para siempre.

Si el escritor institucional no puede persistir ese `FIN`, el período permanece
abierto y el sistema espera un cambio real antes de volver a intentarlo, en vez
de reintentar sin pausa. Rige el fallo cerrado: no se anuncia una transición que
no pudo registrarse.

Si la persistencia del `INICIO` falla, el aviso tampoco se publica: rige el
fallo cerrado general y no se anuncia una transición que no pudo registrarse. Un
período abierto cuyo conjunto de CSV ya fue cerrado por el fin de la
preparación/sesión se descarta sin escribir su `FIN` en un conjunto distinto.

La transmisión conserva sus órdenes humanas L2 `TRANSMISION_INICIADA` y
`TRANSMISION_DETENIDA`, y agrega dos hechos efectivos también L2 bajo la etiqueta
`APOYO_TECNICO`:

- `TRANSMISION_EN_VIVO_INICIO`, cuando el reloj autoritativo alcanza realmente
  `en_vivo_desde`, sea un inicio inmediato o el fin de una cuenta regresiva;
- `TRANSMISION_EN_VIVO_FIN`, cuando una orden detiene o reemplaza una intención
  que en ese instante estaba efectivamente `EN_VIVO`.

Una cuenta regresiva detenida o reemplazada antes del deadline no genera `FIN`.
Si el deadline compite con stop o reemplazo, el serializador procesa primero el
`INICIO` pendiente y cierra después el período una sola vez. El temporizador de
fronteras usa el mismo predicado autoritativo que la mutación, sin polling; los
wakeups repetidos no duplican filas. Cuando el cruce ocurre sin preparación ni
sesión se lo marca como procesado sin crear auditoría, por lo que abrir un nuevo
conjunto más tarde no inventa un replay. Un conjunto ya cerrado tampoco recibe
escrituras tardías.

Estos dos hechos pertenecen a L2: aparecen en los CSV L1 y L2 y en la proyección
operativa reciente, pero no en L3 ni en el informe formal `-ACTA.txt`.

Además de esa auditoría técnica, cada transición **efectiva del indicador**
registra un evento principal L3 con etiqueta general `EVENTO`:

- `TRANSMISION_EN_VIVO_INICIADA`, cuando el indicador pasa realmente de apagado
  o cuenta regresiva a `EN_VIVO`;
- `TRANSMISION_EN_VIVO_FINALIZADA`, cuando deja realmente de estar `EN_VIVO`.

El `message` de ambos es una frase institucional fija —«Transmisión en vivo
iniciada» y «Transmisión en vivo finalizada»— sin horas internas, causa técnica,
banderas ni identificadores. La hora la aporta la columna `timestamp` del propio
escritor, que es la misma fuente temporal que usan los demás eventos
institucionales. Estos dos códigos son distintos de los técnicos homónimos y de
los marcadores `INICIO`/`FIN` de los avisos, de modo que filtrar por `event_code`
distingue las tres familias sin ambigüedad.

La diferencia con la auditoría técnica es qué se sigue. Los hechos L2 siguen la
vida de cada **intención** de transmisión; los eventos principales siguen la del
**indicador** que ve el público. Por eso reemplazar una transmisión ya `EN_VIVO`
por un inicio inmediato registra el cierre técnico de esa intención pero **no**
produce un par principal: el indicador nunca se apagó. Reemplazarla por una
cuenta regresiva sí lo apaga y sí cierra el período principal.

La autoridad de «hay un período anunciado y todavía no cerrado» es un marcador
del estado operativo que se instala recién después de persistir el `INICIO` y se
retira recién después de persistir el `FIN`, igual que el de los avisos del
Recinto. De ahí se siguen las garantías del contrato: programar, reemplazar o
cancelar una cuenta regresiva no anuncia nada; un start repetido sobre una
transmisión ya `EN_VIVO` no duplica el `INICIO`; un stop repetido no duplica el
`FIN`; una carrera entre el deadline y un stop registra el par completo del
período que sí existió; y reconstruir la proyección o reconectar SSE nunca
reemite un hecho histórico, porque proyectar sólo lee el buffer confirmado.

Como cualquier otro hecho L3, estos eventos entran en el informe `-ACTA.txt` con
su frase institucional. Un encendido ocurrido en `SIN_PREPARAR` no crea evento y
tampoco se reconstruye al preparar después; un período cuyo conjunto de CSV ya
fue cerrado se descarta sin escribir su `FIN` en un conjunto distinto, porque la
transmisión es independiente del ciclo preparación/sesión y puede seguir
encendida cuando ese ciclo termina.

## 10. Identidad de concejales

La implementación histórica usa principalmente nombre, apellido y banca en mensajes funcionales.

SIS-Leg conserva como mínimo esa legibilidad humana en `message`. Los códigos/estructuras internas no deben reducir el registro a identificadores opacos.

Las seis columnas canónicas son suficientes para la primera versión; información adicional del evento puede expresarse de forma consistente en `message` y mediante `event_code`.

## 11. Presidencia

El desempate registra explícitamente:

- quién figuraba como Presidencia;
- sentido `POSITIVO` o `NEGATIVO`;
- resultado final.

La identidad se captura dentro del serializador y queda almacenada junto al voto aunque después cambie la autoridad. No se registra como voto ordinario de banca ni modifica sus conteos.

## 12. Remapeo

El evento de remapeo debe permitir reconstruir qué identificador lógico fue reasignado desde qué fingerprint físico hacia qué nuevo fingerprint, sin alterar ni reescribir votos/presencia del concejal asociado.

## 13. Proyección de eventos a frontends

Los CSV son el registro persistente; los frontends consumen una proyección reciente en memoria.

Moderación consume un buffer del contexto activo de máximo **200 eventos**,
ordenados en forma ascendente por `seq`. Con menos de 200 conserva todos; el
evento 201 desplaza al más antiguo. Cada nueva preparación crea un buffer nuevo
y `SIN_PREPARAR` no lee CSV históricos para reconstruirlo.

El buffer vive junto al escritor activo y un evento entra únicamente después
de que su fila completó escritura, `flush` y `fsync` en todos los destinos. Un
fallo de persistencia no confirma el evento en memoria. El buffer no cambia el
orden institucional, no agrega persistencia y nunca sustituye a los CSV.

`EstadoRecinto` no expone eventos de auditoría en este alcance. Esta omisión
deliberada evita transportar `message` crudo o clasificar por exclusión códigos
que podrían revelar votos durante `EN_CURSO`.

La franja pública del Recinto trabaja con una allowlist positiva de códigos. Los
marcadores `INICIO` / `FIN` de los avisos al Recinto no se incorporan a esa
allowlist: el Recinto ya está mostrando el texto en su propia ranura de aviso y
publicarlo otra vez como tarjeta de evento duplicaría el mismo hecho. Sí
aparecen, en cambio, en los eventos recientes de Moderación y de Apoyo Técnico
bajo el filtro `Principales (L3)`, por el mecanismo de proyección L3 ya
existente y sin ninguna traducción especial.

La proyección que consume Moderación es **operativa y segura**, no una copia
literal de la fila persistida. Además de las seis dimensiones canónicas, cada
evento puede incluir un hecho estructurado con tipo, identidad/banca, detalle
ya resuelto, icono y sentido. Ese hecho se deriva del evento durable más el
estado autoritativo vigente; la interfaz nunca interpreta `message` para
obtener identidad, tipo ni sentido.

Mientras la frontera autoritativa de revelado individual de una votación no
venció, la proyección publica una redacción alternativa sin sentido y omite
icono y sentido. Vencida esa frontera, el **mismo** `seq` se enriquece leyendo
el sentido desde el mapa autoritativo de votos de esa votación. El mismo
criterio protege los eventos L2 de pulsación de teclas 1/2/3, cuya tecla
permitiría deducir el sentido de una banca identificable.

Nada de esto altera los CSV: la fila persistida conserva siempre el mensaje
humano completo, los metadatos estructurados viven únicamente en el buffer en
memoria y la auditoría histórica no se reescribe.

## 14. Logs operativos del Device Bridge

Los CSV institucionales y la proyección descrita arriba no son el único registro que
produce el sistema. El Device Bridge es un proceso de sistema y deja además su propio log
operativo en `stdout`/`stderr` y en el journal de systemd. Ese registro es de naturaleza
distinta y por eso tiene su propia regla.

La diferencia que importa: los CSV son la evidencia institucional aprobada, viven donde el
despliegue los ubica y respetan la frontera autoritativa de revelado individual. El journal
del proceso no es evidencia institucional, no tiene control de acceso propio y lo lee
cualquier persona con una sesión en el equipo, incluso mientras la votación sigue
`EN_CURSO`.

Regla de no reconstructibilidad:

> Ningún mensaje del log operativo del Device Bridge emitido por una pulsación funcional
> puede contener a la vez la identidad de una banca y el contenido de su tecla, en ningún
> nivel de registro, `DEBUG` incluido.

La combinación prohibida es la que reconstruye el voto: `dev07`, su fingerprint o su ruta
`/dev/input/eventN` identifican una banca, y las teclas `1`, `2` y `3` son el sentido
POSITIVO, ABSTENCIÓN y NEGATIVO. Cualquiera de las dos mitades por separado es admisible.

Qué se conserva, porque es diagnóstico legítimo y no reconstruye nada:

- la identidad física y lógica para descubrimiento, mapping, remapeo y exclusividad;
- el hecho de que una banca despachó una pulsación, sin su contenido;
- el código HTTP, la clase de resultado, el motivo estable devuelto por el backend y el
  detalle de red de un fallo de transporte;
- el nombre de una tecla física que el normalizador **rechaza**, que por definición nunca
  se envía al backend y por lo tanto no tiene semántica de voto.

Qué no puede registrarse nunca:

- la tecla normalizada de una pulsación funcional;
- el payload serializado que viaja al backend;
- el cuerpo crudo de una respuesta HTTP, ni su longitud, porque un cuerpo que ecoa la
  pulsación mide distinto según el sentido que ecoa y esa medida basta para distinguirlo;
- cualquier motivo devuelto por el backend que no pertenezca a su catálogo conocido, tenga
  o no forma de código estable: un valor como `DEV07_VOTO_1` respeta la sintaxis de un
  código y aun así reconstruye el voto, de modo que la decisión se toma por enumeración
  explícita y nunca por la forma del texto;
- el detalle crudo de una excepción inesperada, que puede citar el fragmento que no pudo
  procesarse.

La protección se implementa **por construcción** y no filtrando texto ya formateado: los
mensajes se construyen sin los valores sensibles y las estructuras internas del bridge
redactan su propia representación textual. El detalle vive en
`services/device-bridge/src/sis_leg_device_bridge/redaccion.py` y en el README del bridge.

Esta regla endurece observabilidad operativa y **no altera** el contrato HTTP entre bridge
y backend, los CSV institucionales ni la proyección de eventos: el backend sigue siendo la
autoridad exclusiva sobre el significado de una tecla y sobre cuándo un voto individual
puede revelarse.

## 15. Edición posterior

SIS-Leg no ofrece edición de archivos cerrados.

Una corrección externa institucional puede existir fuera del sistema, pero SIS-Leg no reabre ni reescribe automáticamente registros históricos.

## 16. Referencia histórica

La implementación actual usa:

- `L1 -> archivo 1`;
- `L2 -> archivos 1 y 2`;
- `L3 -> archivos 1, 2 y 3`;
- líneas `HH:MM:SS | Lx | TAG | mensaje`;
- escritura inmediata.

SIS-Leg conserva esa semántica de profundidad y la adapta al formato CSV estructurado definido aquí.
