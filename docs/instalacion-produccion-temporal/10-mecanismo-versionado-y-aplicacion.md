# 10 - Mecanismo versionado de operación y su futura aplicación al host

Este documento separa tres cosas que hasta ahora se confundían con facilidad:

1. **lo que hoy corre en el host institucional**, escrito directamente sobre esa máquina;
2. **lo que quedó versionado, revisado y probado con WP-101A**, que todavía no está instalado;
3. **lo que falta hacer en WP-101B**, sobre el servidor real y detrás de una compuerta humana.

Si al leer cualquier otro documento de esta carpeta queda la duda de si algo ya está instalado o
solamente preparado, la respuesta está acá.

## 1. Mecanismo histórico instalado hoy

Es el descrito en [05 - Conmutación](05-conmutacion-legacy-sis-leg.md) y
[06 - Actualizador actual](06-actualizador-actual.md):

| Componente | Dónde vive | Estado |
| --- | --- | --- |
| `/usr/local/bin/sisleg-estado`, `sisleg-activar`, `sisleg-activar-target`, `sisleg-activar-legacy` | sólo en el host | instalado y en uso |
| `/home/concejo/.local/bin/control-cambiar-sisleg.sh`, `control-cambiar-legacy.sh`, `actualizar-sisleg.sh` | sólo en el host | instalados y en uso |
| Lanzadores `.desktop` | sólo en el host | ajustados manualmente por HUMAN; **fuera de alcance** |

Características que conviene tener presentes:

- **no están versionados**: no hay revisión independiente ni pruebas sobre ellos;
- el actualizador depende de **GitHub Actions autenticado** (`gh`, credenciales en la máquina);
- desde la integración de WP-100 ese actualizador ya no encuentra el artifact interno que buscaba y
  **aborta sin mutar nada**, que es su comportamiento fail-safe esperado. En la práctica, hoy no hay
  actualizaciones por esa vía.

Nada de esto cambió con WP-101A. **El host sigue exactamente como estaba.**

## 2. Mecanismo público versionado que deja listo WP-101A

WP-101A no instaló, no conmutó y no actualizó nada. Lo que hizo fue convertir las tres operaciones
de usuario en código del producto, que viaja dentro de cada release y pasa por la CI completa.

| Archivo versionado | Qué hace |
| --- | --- |
| `deploy/estado_host.py` | Clasifica el estado formal del host, toma el lock global y administra `target-release`. Sólo lectura, salvo la escritura validada del target. |
| `deploy/operaciones_host.py` | Las tres operaciones: `actualizar`, `cambiar-a-sis-leg` y `cambiar-a-legacy`. |
| `deploy/instalador_host.py` | Inventario, respaldo e instalación de los componentes en el host. Modo plan por defecto. |
| `deploy/host/sisleg-operacion` | Entrada privilegiada delgada: resuelve qué release ejecutar y delega en la herramienta versionada. |
| `deploy/host/actualizar-sisleg.sh`, `control-cambiar-sisleg.sh`, `control-cambiar-legacy.sh` | Wrappers de usuario, con los nombres y rutas exactos que ya invocan los lanzadores. |

### Reutilización, no reimplementación

El requisito más importante del diseño es que **no existe una segunda implementación** de nada que
ya estuviera resuelto:

- la validación de una release pública —SHA, publicación, evidencia histórica de CI, intento exacto,
  job de empaquetado, los tres assets, checksum del sidecar, `release.json`, commit y árbol— la sigue
  haciendo `deploy/actualizador_publico.py`;
- la preparación, la activación atómica, el health, la convergencia de Nginx, el rollback y el
  contrato add-only de configuración los sigue haciendo `deploy/herramienta_despliegue.py` junto con
  `deploy/configuracion_local.py`.

`operaciones_host.py` sólo agrega lo que ninguno de los dos podía saber: que en esta máquina conviven
dos sistemas y que retirar uno antes de instalar el otro tiene un orden seguro.

### Sin credenciales

La operación «Actualizar SIS-Leg» versionada **no usa** `gh`, PAT, `.github_token`, token, cookie ni
login de GitHub. Consume el canal público de WP-100 con recursos abiertos. Hay una prueba automática
que recorre estos archivos y falla si alguien reintroduce cualquiera de esas dependencias.

### Qué hace cada operación

**Actualizar SIS-Leg**, en este orden: lock global, guard institucional de no sesión/no preparación,
resolución del SHA público de `main`, idempotencia, descarga verificada, preflight, preparación,
**revalidación de `main`**, compuerta de configuración y recién entonces la acción que corresponda:

- con el sistema anterior activo: fija `target-release` y **no conmuta**; el recinto sigue atendido
  por el sistema que estaba;
- con SIS-Leg activo: actualiza en caliente de release a release, sin pasar por el sistema anterior,
  con health completo. Activar la release nueva y fijar `target-release` son **una sola transacción
  operacional**: son dos hechos que tienen que contar la misma historia, y si el segundo fallara
  después de que el primero salió bien, el host quedaría con `current` y objetivo divergentes, que es
  justamente el estado que la próxima actualización interpreta como ambiguo y bloquea. Por eso
  cualquier falla posterior al inicio de la activación revierte las dos cosas: el motor canónico
  devuelve la release previa y el objetivo vuelve exactamente a como estaba, **ausencia incluida** si
  antes no había ninguno. El desenlace del rollback se clasifica por lo que se observa en el host
  y contra la release que estaba realmente en `current`, no contra `target-release`: son cosas
  distintas, y un host sano sin objetivo declarado tiene rollbacks perfectamente válidos. Sólo se
  declara `ROLLBACK_EXITOSO` cuando el host quedó `ESTABLE_SISLEG`, `current` volvió a la release
  previa y el objetivo quedó idéntico al de antes. Si la
  restauración no se puede demostrar, el mensaje lo dice y exige intervención en lugar de afirmar
  que se volvió a la versión anterior;
- si `target-release` ya es la versión pública y la release está preparada, no descarga, no prepara y
  no reinicia nada;
- si `current` y `target-release` divergen de forma no resoluble, aborta sin mutar.

La revalidación de `main` existe porque las releases públicas son inmutables: la del SHA anterior
sigue descargándose con normalidad aunque `main` haya avanzado mientras tanto. Sin volver a
preguntar, una actualización lenta podría terminar declarando como objetivo una versión que ya dejó
de ser la vigente, con una autorización tomada minutos antes. Si se detecta esa carrera, la release
ya preparada **queda en disco** —preparar es aditivo y no toca lo que está en servicio— pero no se
activa ni se declara como objetivo.

El paquete descargado se guarda en `/opt/sis-leg/descargas/` sólo mientras dura la operación: una vez
preparada la release se descarta, porque pesa cientos de megabytes y ya es redundante. Si la
preparación falla, en cambio, queda en disco para diagnóstico. No se borra ninguna release, registro
ni respaldo.

**Cambiar a SIS-Leg**: lee y valida `target-release` con las ocho comprobaciones —incluida la
identidad de árbol—, aplica el guard, retira el sistema anterior con *disable-first* verificado,
activa la release con la herramienta canónica, habilita las unidades sólo después del health y
verifica el estado final. Ante cualquier falla posterior a la primera mutación ejecuta el rollback
externo completo. No borra releases, configuración ni registros.

### Dónde empieza el rollback

Las retiradas son multietapa y la frontera entre «todavía no toqué nada» y «ya estoy a mitad de
camino» decide qué corresponde hacer ante una falla:

- el *disable-first* se ejecuta **antes** del bloque protegido, porque es la única etapa que se
  deshace sola: si no se puede demostrar, se restaura la habilitación previa y se aborta sin
  rollback, con el host entero y sin un solo servicio detenido;
- desde la primera detención, **toda** falla entra en la ruta de restauración, incluidas las que
  ocurren dentro de la propia retirada. Haber detenido el bridge y no poder detener el backend deja
  el host en un estado que no es ni el de origen ni el de destino, y es justamente el que estas
  operaciones existen para no producir.

Legacy → SIS-Leg restaura el snapshot Legacy completo y exige `ESTABLE_LEGACY`; SIS-Leg → Legacy
restaura el snapshot SIS-Leg completo —la release que estaba realmente en `current`— y exige
`ESTABLE_SISLEG`. Los snapshots se toman antes de la primera mutación: después ya no habría de dónde
leerlos. Si el rollback tampoco funciona se informan los dos errores, se registra `ROLLBACK_FALLIDO`
y el estado **observado**, y se exige intervención humana sin declarar ningún sistema activo.

**Cambiar a Legacy**: idempotente e independiente de versión, y además la operación de **salida
segura** del host. Eso gobierna dos propiedades:

- **no depende de `target-release`**. Volver al sistema anterior es version-agnóstico, así que un
  objetivo corrupto se diagnostica y se informa, pero no puede bloquear la vuelta atrás. Lo que sí
  falla cerrado ante un target inválido es lo que lo consume: actualizar y cambiar a SIS-Leg;
- **si el sistema anterior no vuelve a servicio**, se restaura el SIS-Leg que estaba sano en lugar de
  dejar el host inerte. Si tampoco esa restauración funciona, se informan los dos errores y se exige
  intervención humana: no se simula ningún estado bueno ni se reintenta en silencio.

Por lo demás retira SIS-Leg bridge primero, deja `current` liberado para que una reactivación futura
funcione y deshabilita el vhost sin borrarlo. No usa recuperación destructiva automática ante estados
ambiguos.

En todas las transiciones se comprueba que **nunca** haya dos device bridges activos.

### *Disable-first* verificable

Las retiradas deshabilitan las unidades del sistema saliente **antes** de detenerlas, para que un
reinicio en el peor momento no las devuelva a la vida. El `disable` se ejecuta tolerando su código de
salida —systemd responde distinto según la versión y el estado de la unidad—, pero después se
comprueba `is-enabled` y se aborta si alguna sigue habilitada. El aborto ocurre antes de detener nada
y restaura la habilitación previa: el host queda como estaba.

La misma exigencia gobierna la clasificación del estado formal. `ESTABLE_LEGACY` y `ESTABLE_SISLEG`
requieren que el sistema que no manda esté además **deshabilitado**, no solamente apagado: un host
con las unidades del otro sistema todavía `enabled` está a un reinicio de tener los dos peleando por
el mismo puerto y los mismos numpads.

### Historial operativo

Cuando se invoca con `--registro`, cada operación anexa una línea JSON con `flush` y `fsync`, en los
**cuatro** desenlaces: éxito, cancelación, falla y falla con rollback. Un historial que sólo conserva
los éxitos es exactamente el que no sirve el día que hay que reconstruir qué pasó.

Cada línea registra la hora local de inicio, la operación, el estado formal previo y posterior, si
hubo mutación, el código de salida, el desenlace del rollback, el diagnóstico del error y, para una
actualización, la trazabilidad del canal público: commit, árbol, etiqueta, nombre y checksum SHA-256
del paquete, y el run, el intento y el job de CI que lo produjeron. **No hay secretos**: el
consumidor no se autentica contra nada, así que no existe ningún token que registrar, y una prueba
automática comprueba que el historial no contenga patrones de credenciales.

Si el propio historial no se puede escribir, la falla se informa de forma explícita por la salida de
error y el resultado de la operación **no se altera**: una conmutación que dejó el recinto
funcionando no se convierte en un fracaso porque el archivo de historial esté en un disco lleno.

### Compuerta de configuración

Antes de escribir cualquier configuración, `target-release` o servicio:

- la configuración existente se preserva byte a byte;
- un recurso declarado que falte se crea sólo si la release trae un bootstrap seguro;
- un recurso que ya existe nunca se sobrescribe;
- si la release nueva declara otro `schema` para un recurso existente, la operación **aborta antes de
  mutar** y devuelve un diagnóstico que exige un HUMAN_GATE específico.

La preparación de una release ocurre antes de esa compuerta porque es puramente aditiva: crea un
directorio nuevo bajo `releases/` y no toca la instalación activa ni la configuración.

### Cómo se probó, y con qué límites

Toda la suite corre sobre raíces temporales con ejecutores inyectados. Ninguna prueba usa systemd,
Nginx, red o privilegios, y ninguna escribe en `/opt/sis-leg`, `/usr/local/bin`, `/etc` ni en el home
productivo.

Eso tiene un límite honesto que conviene enunciar: las pruebas demuestran **la lógica, el orden y los
guards**, no el comportamiento del systemd ni del Nginx reales del host. Esa verificación pertenece a
WP-101B y por eso su primer paso es un inventario read-only.

## 3. Qué falta ejecutar en WP-101B, sobre el servidor real

WP-101B está **pendiente** de acceso al equipo de producción y de una compuerta humana específica.
La integración de WP-101A no lo autoriza.

Pasos previstos, en orden:

1. **inventario read-only del host**: estado formal, releases presentes, `target-release`, contenido
   y permisos actuales de los wrappers, y comparación contra lo preparado;
2. ejecutar `deploy/instalador_host.py ... plan` y revisar la salida completa. El plan compara
   **contenido y metadata**: un destino sólo se declara sin cambio cuando los bytes, el modo y el
   propietario son los declarados. Un archivo con el contenido correcto pero con permisos o dueño
   equivocados aparece como corrección de metadata, que se aplica sin reescribir el archivo y sin
   generar un respaldo redundante.

   El plan es además un preflight real: **falla** si alguno de los usuarios o grupos declarados no
   existe en la máquina, y lo hace para los cuatro componentes, existan o no todavía en el destino.
   Un `--usuario-operador` mal escrito se descubre ahí y no con el archivo ya instalado. `aplicar`
   repite esa comprobación justo antes de la primera escritura, porque entre planificar y aplicar
   puede haber pasado tiempo;
3. sólo entonces, con autorización explícita, `aplicar --confirmar`, que respalda cada wrapper
   reemplazado antes de escribirlo. Al crear o reemplazar, el contenido, el modo y el propietario se
   fijan sobre un temporal y recién después se publica con `os.replace`: el destino final aparece de
   una sola vez y ya correcto, y nunca existe el instante en que la entrada privilegiada está en su
   lugar con el dueño equivocado. Corregir la metadata de un archivo que ya existe, en cambio, son
   dos llamadas al sistema y no es atómico: si la segunda falla se restaura el modo previo y se
   informa exactamente cómo quedó el archivo, sin fingir una atomicidad que ese camino no tiene;
4. verificar los componentes instalados **sin** ejecutar ninguna conmutación ni actualización: WP-101B
   puede detenerse acá;
5. cualquier operación real posterior —una actualización o una conmutación— es una decisión separada,
   con su propia autorización.

Lo que WP-101B **no** hace: tocar `.desktop`, modificar sudoers o PolicyKit, borrar releases,
registros o respaldos, retirar el sistema anterior, ejecutar un cutover irreversible o eliminar las
credenciales de GitHub que hoy están en la máquina. Retirar esas credenciales exige demostrar antes
que ya no las necesita nadie, y es una decisión posterior.

## 4. Datos que hay que relevar de nuevo en el host, no asumir de esta documentación

Estos valores están escritos acá como estado observado en su momento. Antes de aplicar nada en
WP-101B hay que **volver a medirlos** sobre la máquina real:

| Dato | Por qué puede haber cambiado |
| --- | --- |
| Estado formal del host | Alguien pudo conmutar entre sistemas desde el escritorio. |
| `target-release` y releases presentes | Pudo ejecutarse una actualización, o no. |
| Contenido y permisos exactos de los tres wrappers de usuario | Se editaron a mano durante la puesta en producción. |
| Usuario operador y su `$HOME` | El aplicador los toma como parámetro justamente por eso. |
| Ruta real del Python 3.14 y de `uv` | Se instalaron manualmente y pueden haberse movido. |
| Destino exacto del symlink del vhost anterior | El rollback lo restaura literalmente. |
| Nombre de las unidades de systemd de los dos sistemas | Es la identidad con la que se opera. |
| Presencia de credenciales de GitHub en la máquina | Su retiro es una decisión posterior con evidencia. |

Ninguno de estos datos debe deducirse de este documento ni de los anteriores: se leen del host, con
una operación de sólo lectura, y recién después se decide.

## 5. Impacto sobre el manual de usuario

WP-101A **no** modifica `manual/index.html`, y la evaluación fue explícita: hasta que WP-101B instale
los componentes, quien opera el sistema sigue usando exactamente los mismos tres botones, con el
mismo comportamiento visible. Lo que cambió es interno —de dónde sale el código que ejecutan— y eso
no es información útil para el uso ni para el soporte.

La evaluación se repitió en cada corrección previa a la integración, con el mismo resultado. La
última alcanzó la transacción entre la activación y `target-release`: es una garantía interna de
consistencia dentro de un mecanismo que todavía no está instalado en ninguna máquina, y no cambia
ninguna pantalla, ningún paso ni ningún texto que vea hoy quien opera.

La anterior alcanzó las rutas de falla de las conmutaciones, la clasificación del rollback en
caliente, el texto que muestra el wrapper de actualización cuando algo sale mal y el preflight del
aplicador: todo eso ocurre dentro del mismo mecanismo no instalado, y el wrapper cuyo texto cambió no
está en el host. Cuando WP-101B lo instale habrá que explicar en el manual qué significa ese mensaje
para quien opera.

La evaluación anterior, con el mismo resultado, alcanzó las siete correcciones de la primera
auditoría: idempotencia por metadata del aplicador, historial completo con evidencia,
revalidación de `main`, independencia de la vuelta a Legacy respecto de un target corrupto, rollback
a SIS-Leg, *disable-first* verificable e identidad de árbol. Ninguna de ellas cambia lo que ve o hace
hoy quien opera el sistema, así que el manual sigue sin requerir actualización.

Cuando WP-101B instale el mecanismo nuevo habrá que volver a evaluar el manual: ahí sí cambia qué ve
la persona en pantalla durante una actualización, y esa evaluación corresponde a ese trabajo.
