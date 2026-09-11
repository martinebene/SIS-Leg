# 06 - Frontend Pantalla del Recinto

Frontend público de solo lectura construido con **Nuxt 4 + TypeScript estricto**, Tailwind CSS v4 y componentes propios.

El estado autoritativo vive en FastAPI. La primera versión no usa Pinia.

## 1. Principio de seguridad

La Pantalla del Recinto nunca puede modificar estado.

Durante una votación `EN_CURSO` no recibe ni muestra votos individuales ni eventos que permitan inferirlos. La restricción se aplica en la proyección `PublicState` del backend, no mediante ocultamiento visual.

## 2. Sincronización

- snapshot completo de `EstadoRecinto` por
  `GET /api/v1/estado/recinto` al cargar/reconectar;
- actualizaciones completas por `GET /api/v1/estado/recinto/stream` (SSE);
- cliente común en `packages/api-client/`;
- ante reconexión del stream se recupera snapshot antes de continuar.

No utiliza polling periódico como mecanismo normal.

El primer evento SSE vuelve a contener el estado vigente completo y cada
versión lleva `revision`, de modo que una mutación entre snapshot y stream no
se pierde. El DTO público es propio y restrictivo: no deriva de ocultar campos
de Moderación en CSS o JavaScript.

## 3. SIN_PREPARAR

Debe mostrar un estado neutro/sin sesión y limpiar cualquier información transitoria de la ejecución anterior.

Desde `WP-062` ese estado presenta el **logo completo de SIS-Leg** sobre el fondo institucional, acompañado de la identificación de la pantalla y de la aclaración de que la próxima sesión todavía no fue preparada. El nombre del producto no se repite como texto donde ya está el logo.

## 4. PREPARANDO

Puede mostrar información apropiada de preparación, por ejemplo:

- recinto en preparación;
- bancas y acreditaciones;
- test visual de dispositivos;
- quórum actual cuando resulte conveniente.

No debe sugerir que la sesión está formalmente abierta.

## 5. SESION_ABIERTA

Debe representar al menos:

- número de sesión informado;
- Presidencia;
- Secretaría Legislativa cuando corresponda al diseño público;
- cantidad de presentes/quórum;
- disposición del recinto;
- orador y pedidos de palabra;
- estado de la votación activa.

Desde `WP-050` la pantalla **no dibuja** la franja de eventos públicos: HUMAN_GATE
decidió recuperar esa altura para las bancas. La proyección `eventos_publicos`
sigue formando parte del contrato público y del snapshot; sólo dejó de tener
representación visual.

## 6. Bancas

La disposición proviene de configuración.

Regla visual histórica a conservar salvo decisión de diseño posterior:

- banca 1 comienza abajo a la izquierda;
- numeración de izquierda a derecha;
- al completar una fila, continúa en la fila superior.

Cada banca obtiene la imagen del concejal desde `ruta_imagen` en el padrón. No debe existir una asociación hardcodeada entre número de banca y archivo de imagen.

Desde WP-098 esa ruta **no** resuelve contra los assets del build de la pantalla,
sino contra la fuente única de configuración `config/assets/bancas/`, que publica
el backend en `GET /api/v1/recursos/imagenes-concejales/{nombre_archivo}`. La
Pantalla del Recinto y el cuadrante 3 de Moderación resuelven así exactamente el
mismo archivo, y reemplazarlo en la configuración local se ve en las dos sin
reconstruir el frontend. Una ruta inválida o un archivo ausente dibujan las
iniciales del concejal y no rompen la pantalla.

Estados visuales diferenciables:

- ausente;
- presente;
- test físico temporal;
- en uso de la palabra;
- voto individual únicamente después del cierre.

## 7. Votación EN_CURSO

Muestra información general de la votación pero no votos individuales.

Cuando la mayoría es `ESPECIAL`, el factor se escribe con exactamente dos decimales, truncando los decimales sobrantes sin redondear (`0.6789` se muestra `0.67` y `1` se muestra `1.00`). Es la misma regla de presentación que aplica Moderación y no altera el valor que transporta el DTO público.

Puede mostrar una cuenta regresiva/efecto inicial configurable. Valor inicial: 4 segundos.

No existe límite temporal reglamentario para votar. La votación puede continuar mientras existen pedidos/usos de palabra.

El DTO expone `cuenta_regresiva_hasta`, calculado una sola vez desde
`fecha_hora_apertura + public_initial_countdown_seconds`. El frontend deriva
localmente el número visible; el backend no emite un evento por segundo. El fin
de esta presentación no modifica el secreto: mientras siga `EN_CURSO`, la red
no transporta votos ni mensajes de auditoría.

## 8. Cierre de votación

Cuando alcanza estado final:

- mostrar resultado;
- mostrar votos individuales;
- representar `INCONCLUSA` y `EMPATADA` inequívocamente;
- si hubo desempate, reflejar resultado final sin incorporar el voto presidencial como voto ordinario de banca.

El resultado permanece un tiempo configurable, inicialmente 6 segundos, y luego se limpia la información transitoria sin borrar el estado general de sesión.

Para `APROBADA`, `RECHAZADA` e `INCONCLUSA`, `resultado_visible_hasta` se
calcula desde el instante en que ese resultado final quedó disponible después
de su hecho durable. Al vencer, backend omite la votación transitoria del DTO y
emite una nueva revisión; el historial interno no se borra.

## 9. Empate

Mientras una mayoría simple está `EMPATADA` esperando Presidencia, puede mostrar el empate sin inventar un resultado.

Al desempatar Presidencia, pasa a `APROBADA` o `RECHAZADA`.

`CERRADA + EMPATADA` no expira mientras espera Presidencia y puede mostrar los
votos ya cerrados. Si el desempate llega mucho después, la ventana completa de
`public_result_display_seconds` comienza en ese resultado final, no en la fecha
de cierre original. Una nueva `EN_CURSO` reemplaza inmediatamente cualquier
presentación anterior.

## 10. Uso de la palabra

Debe mostrar claramente:

- concejal en uso;
- cola de solicitudes de forma adecuada para público.

En la cola de solicitudes, el nombre de cada concejal es el dato dominante del renglón y debe dimensionarse para lectura a distancia desde el recinto, por encima del número de banca y del indicador de orden. Ocupa casi todo el ancho útil del renglón, se mantiene siempre en una sola línea y los nombres que no entran se recortan de forma determinista con elipsis, conservando el nombre completo como texto accesible. Ese tamaño no puede ensanchar la columna de palabra, alterar la grilla principal ni producir desplazamiento horizontal; cuando los pedidos superan la altura disponible, la propia lista se desplaza en vertical sin generar scroll global.

La palabra puede coexistir con votación en curso.

## 11. Presencia y quórum

Los cambios de presencia deben reflejarse con baja latencia.

Si una votación termina `INCONCLUSA` por pérdida de quórum, debe mostrar ese estado final.

## 12. Eventos públicos

`PublicState`/stream público excluye detalles técnicos innecesarios y cualquier evento que revele un voto antes del cierre.

Esta garantía pertenece a la proyección del backend, no a la vista: sigue vigente
aunque `WP-050` haya retirado la franja de eventos de la Pantalla del Recinto.

## 13. Responsive y hardware

Resolución de referencia actual: **1920×1080 Full HD**, preferentemente en composición 16:9.

No es un requisito rígido. La pantalla debe:

- adaptarse a cambios razonables de resolución, escala y relación de aspecto;
- mantener jerarquía y legibilidad de bancas, nombres, resultado, quórum y orador;
- evitar recortes/solapamientos que oculten información crítica;
- responder de forma controlada ante pantallas que no sean 16:9;
- evitar coordenadas/tamaños absolutos que hagan necesario reescribir la aplicación al cambiar hardware.

Las pruebas visuales/E2E deben incluir Full HD y al menos otra resolución representativa.

## 14. Reconexión y temporizadores

Tras recargar o reconectar, reconstruye la vista desde backend.

No reproduce temporizadores antiguos como si acabaran de ocurrir. Countdown y permanencia se derivan de timestamps/estado actual de forma consistente.

Reconectar dentro de una ventana conserva el deadline original; hacerlo
después no revive el resultado. La pantalla nunca consume `message` crudo ni el
buffer de auditoría de Moderación.

## 14 bis. Sonidos

La Pantalla del Recinto reproduce los quince sonidos configurados en `system.toml`
(WP-065) ante las transiciones confirmadas que define WP-066. No existe control visible de
audio: ni botón de activación, ni volumen, ni selección de archivos.

Desde WP-071 el puesto de Apoyo Técnico reproduce **los mismos quince eventos**, con la
misma configuración, el mismo volumen y las mismas reglas de silencio. El objetivo es
operativo: permitir que la amplificación del salón tome el audio desde el equipo técnico.
No es una segunda implementación sino la misma: detección de transiciones, motor de audio
y frontera reactiva viven en `packages/frontend-shared/` y las dos pantallas los consumen.
Todo lo que sigue en esta sección describe, por lo tanto, el comportamiento de ambas
superficies. Apoyo Técnico obtiene el estado que sonoriza mediante una suscripción
adicional de **solo lectura** a la proyección pública `EstadoRecinto`, la misma que ya ve
cualquiera que mire la pantalla del salón, y tampoco agrega ningún control visible de
audio.

### Qué dispara cada sonido

Catorce de los quince eventos se deducen comparando dos estados públicos consecutivos ya
adoptados por la sincronización:

| Evento configurado | Transición observada |
| --- | --- |
| `preparacion_iniciada` | `SIN_PREPARAR` -> `PREPARANDO` |
| `sesion_abierta` | el estado global pasa a `SESION_ABIERTA` |
| `sesion_cerrada` | el estado global deja de ser `SESION_ABIERTA` |
| `aviso_tecnico_publicado` | aparece un aviso dirigido al Recinto, o lo reemplaza otro con distinto `aviso_id` |
| `aviso_tecnico_retirado` | el aviso vigente desaparece del snapshot |
| `transmision_iniciada` | la transmisión pasa a `EN_VIVO` |
| `transmision_detenida` | la transmisión pasa de `EN_VIVO` a `APAGADO` |
| `pedido_palabra_registrado` | una banca entra en la cola de pedidos |
| `pedido_palabra_retirado` | una banca sale de la cola sin quedar como orador |
| `uso_palabra_otorgado` | cambia el orador a una banca concreta |
| `votacion_abierta` | se adopta una votación distinta con recepción `EN_CURSO` |
| `votacion_cerrada` | la recepción de esa votación pasa de `EN_CURSO` a `CERRADA` |
| `concejal_ausente` | `presente` pasa de verdadero a falso en una banca |
| `concejal_presente` | `presente` pasa de falso a verdadero en una banca |

El decimoquinto, `transmision_cuenta_regresiva_tic`, no nace de comparar snapshots: suena
cada vez que cambia el **segundo visible** de la cuenta regresiva hacia el vivo. Ese número
lo deriva localmente el reloj de presentación técnica desde la frontera absoluta
`en_vivo_desde`, de modo que el tic no agrega una sola petición de red ni obliga al backend
a publicar una revisión por segundo.

Un cambio de estado global no se interpreta además como una serie de hechos individuales:
al cerrar la sesión suena el cierre, y no un retiro de pedido por cada banca que quedaba en
la cola ni una ausencia por cada banca del padrón que deja de proyectarse.

### Qué nunca suena

- El **primer snapshot** no reproduce nada: describe lo que ya ocurrió, no un hecho nuevo.
- Una **recarga** o una **reconexión** tampoco. El snapshot de recuperación se adopta como
  referencia silenciosa, incluso cuando el backend reinició y la revisión vuelve a empezar.
  La distinción es exacta y no heurística: el cliente notifica la conexión abierta después
  de adoptar su snapshot, así que un estado adoptado fuera de una conexión establecida es
  siempre una baseline.
- Una **revisión repetida** dentro de la misma conexión. El estado se compara una sola vez.
- El **sentido de un voto**. Ningún sonido depende de cómo votó nadie, ni permite inferirlo.

### Superposición

Dos hechos simultáneos pueden oírse a la vez. Cada reproducción usa su propia instancia de
audio y un sonido nuevo nunca interrumpe ni reinicia al anterior. No existe una cola serial
que los ordene.

### Fallos de reproducción

Un archivo que falta, una política de autoplay que rechaza la reproducción o una
configuración que el backend publicó como no disponible no rompen el render ni la
sincronización: la pantalla sigue funcionando en silencio y el problema se informa una sola
vez por el canal técnico del navegador, sin reintentos y sin ninguna superficie visible
nueva. En Apoyo Técnico vale lo mismo, con una consecuencia adicional que conviene tener
presente: un fallo de audio no afecta los controles de transmisión, avisos, biblioteca ni
remapeo, porque dependen de otro canal. La configuración de los equipos que permite
reproducir sin interacción humana está documentada en
`docs/13-despliegue-y-operacion.md`.

## 15. Solo lectura

No tendrá comandos de:

- presencia;
- votación;
- palabra;
- autoridades;
- sesión;
- configuración.

Cualquier API usada por esta aplicación respeta ese principio.
