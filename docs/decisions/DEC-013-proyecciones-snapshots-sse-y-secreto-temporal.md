# DEC-013 - Proyecciones, snapshots, SSE y secreto temporal

**Estado:** `APROBADA`

## Contexto

DT-006 ya estableció que SIS-Leg utiliza REST para comandos, snapshots y consultas puntuales, y Server-Sent Events (SSE) para cambios de estado backend -> frontend. DT-008 exige proyecciones separadas `ModerationState` y `PublicState`, y dispone que durante una votación `EN_CURSO` la proyección pública no puede contener votos individuales ni datos o eventos capaces de revelarlos.

Los casos de uso CU-24, CU-25 y CU-26 exigen que Moderación y Recinto puedan reconstruir su vista desde backend, incluido después de una recarga o reconexión. Los frontends futuros no deben reconstruir reglas de negocio localmente ni depender de haber observado todos los eventos anteriores.

La configuración ya separa tres temporizadores de presentación:

- `moderation_vote_reveal_seconds`: retardo inicial de revelado de votos individuales en Moderación;
- `public_initial_countdown_seconds`: cuenta regresiva/efecto visual inicial del Recinto;
- `public_result_display_seconds`: permanencia transitoria del resultado público.

La consulta funcional acotada a producción autorizada por DEC-001 confirmó que el retardo de Moderación es una ventana global iniciada al abrir la votación, no un retardo independiente por cada voto. Durante esa ventana no se muestran votos individuales; al vencer, los votos existentes pasan a ser visibles y los posteriores pueden verse mientras continúa la votación. Esta consulta no se utiliza como referencia técnica para decidir transporte o arquitectura.

Faltaba cerrar los contratos concretos de lectura REST/SSE, la granularidad de los mensajes, la política de revisión, la semántica de reconexión, el tamaño de la proyección de eventos de Moderación, las capacidades operativas y las fronteras temporales de revelado público.

Las alternativas fueron presentadas al responsable humano del proyecto y aprobadas explícitamente al planificar WP-017.

## Decisión

### 1. Endpoints canónicos

Los snapshots completos se exponen mediante:

```text
GET /api/v1/estado/moderacion
GET /api/v1/estado/recinto
```

Los streams SSE se exponen mediante:

```text
GET /api/v1/estado/moderacion/stream
GET /api/v1/estado/recinto/stream
```

No se crearán aliases equivalentes bajo `/proyecciones`, `/eventos`, `/ws` ni rutas históricas.

Los cuatro endpoints son de solo lectura. No mutan estado de negocio ni sustituyen los endpoints REST de comandos existentes.

### 2. Snapshot completo como unidad de sincronización

Cada respuesta REST devuelve el estado completo correspondiente al consumidor:

- `ModerationState` para Moderación;
- `PublicState` para Recinto.

El snapshot debe bastar por sí solo para reconstruir la vista actual sin depender de mensajes SSE anteriores ni de estado local histórico del frontend.

Las proyecciones son DTOs de lectura derivados del estado autoritativo. No se convierten en una segunda fuente de verdad y no habilitan mutaciones directas del dominio.

Cada snapshot contiene como mínimo:

- una `revision` monotónica;
- una marca temporal de generación o datos equivalentes suficientes para interpretar deadlines temporales;
- el estado global y la información funcional que corresponda a esa proyección.

La nomenclatura concreta de submodelos debe mantenerse estable una vez expuesta en OpenAPI y respetar DEC-001.

### 3. Consistencia de lectura

La construcción de cada snapshot debe observar una vista coherente del estado operativo.

No puede leer una transición a mitad de camino mientras otra operación se encuentra dentro del `EjecutorMutaciones` único. La implementación debe coordinar la lectura con la misma frontera de serialización o tomar una copia coherente bajo esa frontera antes de serializarla.

No se introduce un segundo lock funcional capaz de ordenar mutaciones de dominio en paralelo al `EjecutorMutaciones` existente.

### 4. Revisión monotónica

`revision` representa la secuencia de publicaciones de estado observable durante la vida del proceso.

Reglas:

- nunca disminuye mientras vive el backend;
- permite a un cliente distinguir estados anteriores de estados posteriores;
- puede avanzar aunque una versión sea materialmente igual a la anterior si una operación observada o frontera temporal justificó una nueva publicación;
- una reconexión no exige recuperar todas las revisiones intermedias;
- un cliente lento puede saltar revisiones y reconstruirse con la versión completa más reciente;
- reiniciar el backend reinicia también esta secuencia junto con el resto del estado volátil.

La revisión no es un identificador institucional ni reemplaza `seq` de auditoría.

### 5. Mensajes SSE completos

Cada mensaje funcional SSE contiene el `ModerationState` o `PublicState` completo vigente, no un delta parcial.

Al conectarse, el stream envía inmediatamente el estado vigente. Después publica nuevas versiones cuando existe una operación o frontera temporal relevante para la proyección.

El stream puede utilizar `id:` con la revisión y un único tipo de evento estable, siempre que `data:` contenga el DTO completo correspondiente.

No se implementa historial/replay de SSE en backend. `Last-Event-ID` no obliga a reconstruir eventos perdidos.

El protocolo de recuperación canónico es:

1. obtener snapshot REST;
2. abrir/reabrir SSE;
3. aceptar la versión completa enviada por el stream si es igual o posterior según `revision`;
4. ante duda de continuidad, volver a obtener snapshot REST.

Esta decisión permite que el stream sea un canal de estado actual, no un registro histórico. El registro institucional continúa siendo la auditoría CSV.

### 6. Desconexión, clientes lentos y recursos

Un consumidor lento no exige conservar una cola ilimitada de estados intermedios. Puede recibir directamente una versión completa más reciente.

La desconexión de un cliente debe liberar sus recursos de espera/suscripción. No debe dejar tareas, colas ni referencias creciendo indefinidamente.

Puede utilizarse un keepalive SSE liviano que no altere `revision` ni se interprete como cambio funcional.

### 7. Contenido mínimo de ModerationState

`ModerationState` incluye, cuando corresponda al estado global vigente:

- estado global;
- datos de preparación o sesión;
- número de sesión y autoridades;
- configuración congelada necesaria para la UI;
- padrón/bancas e identidad visible de concejales;
- presencia y test visual vigente;
- cantidad de presentes, quórum y condición de quórum;
- votación relevante, sus datos constitutivos, recepción y resultado;
- cantidad de votos recibidos;
- votos individuales solamente conforme a la política temporal de Moderación;
- voto presidencial de desempate cuando corresponda;
- cola y orador de palabra;
- Orden del Día temporal cuando exista;
- eventos recientes;
- estado técnico grave de auditoría cuando corresponda;
- capacidades de operación.

La proyección puede agrupar estos datos en submodelos tipados. No debe copiar objetos de dominio de forma mutable hacia la capa HTTP.

### 8. Capacidades de operación

Las capacidades no son simples booleanos aislados. Cada capacidad expuesta a Moderación debe poder informar al menos:

```text
habilitada: true|false
motivos: [CODIGOS_ESTABLES]
```

`motivos` utiliza códigos estables alineados con las precondiciones y errores ya canónicos cuando exista equivalencia.

Las capacidades representan la evaluación actual del backend para las operaciones implementadas y permiten que la UI explique por qué un control no está habilitado sin volver a programar reglas de negocio.

No reemplazan la validación definitiva al ejecutar un comando. Entre la lectura y el comando el estado puede cambiar; el endpoint de mutación vuelve a validar bajo sus reglas normales.

Las advertencias puramente de interfaz por palabra pendiente no se transforman en nuevas precondiciones backend: una apertura/cierre reglamentariamente permitidos continúan apareciendo habilitados aunque el futuro frontend deba pedir confirmación antes de enviar el comando.

### 9. Eventos recientes de Moderación

`ModerationState` contiene como máximo los **últimos 200 eventos** de la preparación/sesión activa, ordenados por `seq`.

Reglas:

- es un buffer de conveniencia para interfaz, no persistencia alternativa;
- los CSV siguen siendo el registro completo y autoritativo;
- cada evento reciente se incorpora solo después de que su persistencia obligatoria correspondiente haya sido confirmada por el escritor;
- conservar el buffer no puede alterar la semántica de `flush`/`fsync` ni hacer que una operación se considere exitosa antes de la auditoría;
- al comenzar una nueva preparación, el buffer pertenece exclusivamente al nuevo conjunto;
- en `SIN_PREPARAR` no se reconstruyen eventos históricos desde archivos cerrados.

El evento de proyección debe conservar como mínimo `seq`, timestamp, nivel, tag, código estable y mensaje legible, o una representación equivalente que preserve esas seis dimensiones.

### 10. Retardo de votos en Moderación

El temporizador `moderation_vote_reveal_seconds` se mide **desde la apertura de cada votación**.

Durante esa ventana inicial:

- Moderación puede conocer que existe la votación y la cantidad total de votos recibidos;
- `ModerationState` no entrega todavía los valores individuales `POSITIVO`, `NEGATIVO` o `ABSTENCION` asociados a concejales/bancas;
- no se crea un temporizador distinto por cada voto.

Al alcanzar el deadline:

- la proyección pasa a incluir los votos individuales ya recibidos;
- los votos posteriores pueden aparecer normalmente mientras la votación continúe `EN_CURSO`;
- la transición debe reflejarse sin polling periódico del frontend.

Si un frontend se conecta o reconecta después de vencido el deadline, recibe directamente la política vigente; no vuelve a iniciar cuatro segundos desde su reconexión.

### 11. Contenido y secreto de PublicState

`PublicState` es un DTO independiente y deliberadamente más restrictivo.

Puede incluir, cuando corresponda:

- estado global;
- información pública de preparación/sesión;
- número de sesión y autoridades según el contrato público;
- disposición de bancas, identidad pública, presencia y test;
- quórum;
- orador y cola de palabra;
- información general de la votación;
- countdown/deadlines de presentación;
- resultado/votos solo cuando la política pública los habilita;
- eventos públicos explícitamente seguros.

Durante `EN_CURSO` está prohibido que el cuerpo REST o cualquier mensaje SSE público contenga:

- votos individuales;
- valor de voto asociado a DNI, banca o concejal;
- eventos de auditoría cuyo mensaje revele un voto;
- campos ocultos, auxiliares o estructuras completas de Moderación que permitan recuperar esos valores;
- cualquier DTO de dominio serializado accidentalmente que contenga `votos_ordinarios`.

La seguridad se prueba inspeccionando la respuesta de red; esconder datos mediante CSS/JS no cumple el contrato.

Los eventos públicos no reutilizan ciegamente el mensaje crudo de auditoría. Deben provenir de una proyección explícitamente segura. Ante duda sobre si un evento puede revelar información no pública, se omite de `PublicState` antes que filtrar por una lista de exclusión incompleta.

### 12. Countdown público inicial

`public_initial_countdown_seconds` se mide desde la hora real de apertura de la votación.

`PublicState` debe proporcionar un timestamp/deadline o información equivalente suficiente para que el frontend represente la cuenta regresiva sin inventar una duración local distinta.

Ese countdown es únicamente presentación. Durante todo `EN_CURSO`, antes y después de que termine, los votos individuales siguen siendo secretos en `PublicState`.

Una reconexión no reinicia el countdown; el cliente deriva el tiempo restante del estado/backend vigente.

### 13. Revelado al cerrar y permanencia pública

Cuando la votación deja `EN_CURSO`, `PublicState` puede exponer los votos individuales y el estado/resultado institucional que corresponda.

#### Resultado final ordinario o INCONCLUSA

Cuando aparece un resultado final `APROBADA`, `RECHAZADA` o `INCONCLUSA`, comienza una ventana de presentación pública de duración:

```text
public_result_display_seconds
```

Durante esa ventana pueden exponerse resultado y votos individuales de esa votación. Al vencer, la información transitoria de votación/votos deja de publicarse sin borrar el estado general de sesión ni el historial interno del backend.

Una nueva votación `EN_CURSO` iniciada antes de vencer una ventana previa reemplaza inmediatamente esa presentación anterior y vuelve a aplicar el secreto de la nueva votación.

#### EMPATADA

`EMPATADA` es transitorio y no usa una expiración de seis segundos mientras espera la decisión presidencial.

La pantalla pública puede mantener visible:

- que la votación está `EMPATADA`;
- los votos individuales ya revelables porque la recepción está cerrada;
- la indicación de que falta resolver el desempate.

Esta presentación permanece mientras la misma votación continúe `CERRADA + EMPATADA`.

Si Presidencia desempata posteriormente, la ventana `public_result_display_seconds` comienza **cuando el resultado final `APROBADA` o `RECHAZADA` queda disponible**, no desde la fecha de cierre original de la recepción.

Por lo tanto, el backend debe conservar en memoria información temporal suficiente para que una reconexión durante esa ventana conozca cuánto tiempo resta. Esa metadata de presentación es volátil y no se convierte en nuevo dato institucional persistente salvo decisión posterior.

Si la sesión se cierra mientras la votación está `EMPATADA`, prevalece el flujo ya aprobado que la convierte en `INCONCLUSA`; la presentación pública resultante se rige por el estado global vigente y nunca mantiene datos de una sesión ya descartada contra RN-GLOBAL-02.

### 14. Fronteras temporales sin polling

Las proyecciones pueden cambiar por el mero paso del tiempo aun sin una nueva mutación, como mínimo:

- expiración del test visual;
- vencimiento del retardo inicial de Moderación;
- vencimiento del countdown inicial cuando la representación del estado lo requiera;
- vencimiento de la ventana pública de resultado.

Esas fronteras deben producir una nueva versión observable o proporcionar deadlines que permitan una representación correcta y, cuando el payload deba dejar de contener datos, el backend debe emitir la actualización correspondiente.

No se reintroduce polling periódico como mecanismo normal.

No es necesario enviar un SSE por cada segundo de un countdown. El backend puede publicar un deadline absoluto y el frontend puede representar localmente la cuenta regresiva; la autoridad sobre inicio/fin y sobre qué datos pueden viajar sigue siendo del backend.

### 15. Reconexión

Un frontend que recarga o pierde el SSE:

- no asume que conserva continuidad;
- obtiene nuevamente el snapshot completo cuando corresponda;
- reconstruye temporizadores desde timestamps/deadlines actuales;
- no vuelve a mostrar un countdown o resultado expirado como si acabara de comenzar;
- no necesita reproducir mensajes SSE históricos.

### 16. Interacción con auditoría y fallo cerrado

La publicación SSE no es un hecho institucional y no crea filas CSV por sí misma.

Una falla del stream o un cliente desconectado no modifica dominio ni auditoría.

Si el escritor institucional está en fallo cerrado, `ModerationState` debe reflejar la condición técnica y sus capacidades deben impedir presentar como disponibles mutaciones que el backend ya no puede aceptar con auditoría garantizada.

La capa de proyección no puede hacer rollback ni ocultar estados parciales legítimos ya definidos por las decisiones de fallo cerrado existentes.

### 17. Sin dependencia directa nueva aprobada

WP-017 debe implementarse con las capacidades ya disponibles en Python/FastAPI/Starlette/asyncio siempre que resulten suficientes.

Esta decisión **no aprueba una dependencia directa nueva** para SSE, broadcasting, colas o scheduling.

Si el implementador considera necesaria una dependencia directa nueva o un cambio de transporte respecto de REST + SSE, debe detener esa parte y escalar conforme DT-038 antes de modificar archivos de dependencias o lockfiles.

### 18. Pruebas obligatorias derivadas

La implementación debe cubrir como mínimo:

- snapshot completo de Moderación en `SIN_PREPARAR`, `PREPARANDO` y `SESION_ABIERTA`;
- snapshot público equivalente sin capacidades de mutación;
- coherencia de lectura frente a mutaciones concurrentes;
- primera emisión SSE inmediata;
- nueva emisión después de cambios funcionales;
- cliente lento que puede saltar revisiones sin perder capacidad de reconstrucción;
- reconexión mediante snapshot + stream vigente;
- cleanup de suscriptores desconectados;
- límite exacto de 200 eventos recientes de Moderación y orden por `seq`;
- imposibilidad de que un evento aún no durabilizado aparezca como reciente confirmado;
- retardo global de Moderación desde apertura, no por voto;
- expiración temporal de ese retardo sin polling;
- `PublicState` y stream público sin votos ni mensajes reveladores durante `EN_CURSO`;
- revelado al cierre;
- `EMPATADA` visible sin expirar mientras espera Presidencia;
- ventana pública iniciada al resultado final posterior a un desempate tardío;
- reconexión dentro y fuera de las ventanas temporales;
- nueva votación que reemplaza una presentación final anterior;
- expiración de test visual observable sin polling;
- OpenAPI coherente para los snapshots y contratos documentables de los endpoints SSE;
- ausencia de nueva dependencia directa no aprobada.

Los tests temporales deben evitar esperas reales de varios segundos. La implementación debe admitir relojes/deadlines o mecanismos de prueba suficientemente controlables para que los escenarios sean deterministas y rápidos.

## Consecuencias

- queda cerrado el contrato de lectura backend necesario antes de construir `api-client` y los frontends;
- REST y SSE comparten los mismos DTOs completos por consumidor;
- no existe replay de eventos porque el snapshot completo es la unidad de recuperación;
- `revision` ordena versiones de proyección pero no sustituye la auditoría;
- Moderación recibe un buffer acotado a 200 eventos;
- las capacidades pueden explicar bloqueos sin duplicar reglas de negocio en Vue/Nuxt;
- el retardo de Moderación es global desde apertura;
- el secreto público se garantiza en servidor;
- un empate puede permanecer visible hasta su resolución y el resultado final posterior inicia su propia ventana de seis segundos configurables;
- las expiraciones relevantes se reflejan sin polling periódico;
- no se autoriza ninguna dependencia directa nueva.

## Autoridad

Esta decisión fue aprobada explícitamente por el responsable humano del proyecto al planificar WP-017, seleccionando las alternativas 1.A, 2.A, 3.A, 4.A y 5.A propuestas por el orquestador.

Complementa DT-006, DT-008, DT-021, `docs/04-contratos-e-integraciones.md`, `docs/05-frontend-moderacion.md`, `docs/06-frontend-pantalla-recinto.md`, `docs/07-configuracion-datos-y-assets.md`, `docs/08-observabilidad-y-auditoria.md`, CU-24, CU-25, CU-26, CA-050, CA-051 y CA-052. Ante formulaciones anteriores más generales sobre snapshots, SSE o temporización, esta decisión fija el contrato concreto aplicable a WP-017.