# 08 - Incidentes y lecciones

Cada entrada tiene la misma estructura: **qué pasó**, **por qué pasó** y **cómo se corrigió**.
Ninguno de estos defectos se parcheó a mano en producción: los que eran del producto se corrigieron
con un Work Package, rama, PR, revisión independiente y CI completa.

---

## A - Nginx: la verificación post-reload no esperaba convergencia efectiva

**Qué pasó.** En la primera conmutación real (fase 4), con el candidato `50abb`, el backend SIS-Leg
arrancó sano, el Device Bridge tomó los 12 numpads y `/api/v1/health` respondió por Nginx. Un
instante después, `GET /moderacion/` devolvió **404** y la activación falló. El rollback externo
restauró `ESTABLE_LEGACY`.

**Por qué.** `_verificar_servicios_y_nginx()` asumía que al retornar `systemctl reload nginx.service`
todas las solicitudes nuevas ya usarían la configuración nueva. Nginx recarga de forma *graceful*:
arranca workers con la configuración nueva y ordena a los viejos cerrar gradualmente. Durante esa
ventana, `/moderacion/` todavía era atendida por el vhost Legacy y terminaba proxied al backend
SIS-Leg, que respondía 404. El health no lo detectaba porque `/api/v1/health` llega al backend por
cualquiera de los dos vhosts: no discrimina generaciones de configuración.

**Corrección — WP-093.** La verificación pasó a ser *health-gated*: después del reload se espera de
forma acotada a que el vhost SIS-Leg sea observable de verdad —`/api/v1/health` con `estado == "ok"`
**y** las cinco superficies estáticas devolviendo HTML válido—. Sólo se reintentan errores
compatibles con convergencia transitoria; agotado el presupuesto, falla cerrado y conserva el
rollback. Sin `sleep` ciego, sin reinicio de Nginx como solución normal, sin convertir errores
permanentes en éxito.

**Lección.** Las superficies estáticas son la única prueba de que el vhost correcto está sirviendo.
Un endpoint que ambos vhosts pueden alcanzar no sirve como señal de convergencia.

---

## B - Guard institucional neutralizado por `|| true`

**Qué pasó.** La auditoría 5I encontró que el actualizador consultaba el estado institucional así:

```bash
SESSION_CHECK=$(python3 -c '...' 2>/dev/null || true)
RC=$?
```

**Por qué.** Con `|| true`, `RC` capturaba el código de `true`, es decir **siempre 0**, aunque el
intérprete hubiera terminado con 1 (sesión activa) o 2 (consulta fallida). Todo el código posterior
que bloqueaba según `RC` quedaba inoperante: el actualizador podía ejecutarse durante una sesión
parlamentaria real.

Fue clasificado **BLOQUEANTE**. Hasta corregirlo no se ejecutó ninguna actualización real y el
actualizador no se consideró apto para producción.

**Corrección.** Captura real del código de salida sin que `set -e` mate el script:

```bash
if SESSION_CHECK=$(python3 -c '...' 2>/dev/null); then
    RC=0
else
    RC=$?
fi
```

Con semántica fail-closed explícita: `RC=0` continúa; `RC=1` (sesión o preparación activa) aborta;
`RC=2` (consulta fallida o indeterminada) aborta; **cualquier otro** `RC` aborta. Se aplicó tanto al
lado SIS-Leg como al Legacy y se probó de forma aislada con `RC` 0, 1 y 2.

**Lección.** `|| true` sobre un comando cuyo código de salida es la señal de seguridad convierte un
guard en decoración. Un guard debe fallar cerrado ante lo desconocido, no sólo ante lo negativo
conocido.

---

## C - Validación insuficiente al actualizar `target-release`

**Qué pasó.** La función que escribía `target-release` sólo comprobaba que existiera el directorio de
la release y su marcador.

**Por qué es un problema.** `target-release` decide qué se activa la próxima vez que alguien pulsa
«Cambiar a SIS-Leg». Sin validación estricta, un valor con traversal, un directorio que en realidad
fuera un symlink, o un marcador que perteneciera a otro commit, podían llevar a activar contenido
distinto del esperado.

**Corrección.** Validación centralizada y reusable, exigida antes de escribir: formato de 40
hexadecimales en minúscula; existencia del directorio; que **no** sea symlink; que `readlink -f`
resuelva exactamente a `/opt/sis-leg/releases/<SHA>`; marcador existente y archivo regular; marcador
parseable como JSON; y `marker.commit_sha == <SHA>`. Sin `eval`, sin traversal, sin aceptar valor
vacío. La escritura sigue siendo atómica, `root:root 0644`.

**Lección.** Un puntero es tan confiable como su validación. Si un archivo decide qué código se
ejecuta, validarlo es parte de la superficie de seguridad, no una comodidad.

---

## D - Selección de CI y artifact demasiado laxa

**Qué pasó.** El actualizador tomaba `runs[0]` de la consulta por `head_sha`, filtrando sólo por
`name == "CI"`, y localizaba el job de empaquetado por coincidencia parcial de nombre.

**Por qué es un problema.** Un mismo SHA puede tener varias runs: la del push a `main` y la de una
pull request. La de la PR valida un merge hipotético, no lo que quedó integrado. Tomar la primera de
la lista puede desplegar a producción un paquete que nunca validó `main`.

**Corrección.** Selección rígida: workflow `CI`, `head_sha == MAIN_SHA`, `head_branch == "main"`,
`event == "push"`, `status == "completed"`, `conclusion == "success"`, job exacto
`Empaquetado · release productiva`, artifact exacto `sis-leg-release-<SHA>` perteneciente a **esa**
run y no expirado. Ante varias runs válidas, selección determinística o aborto por ambigüedad. Una
run de `pull_request` **nunca** se acepta, aunque comparta SHA. Si `main` sólo tiene un commit
documental sin run productiva —exención de `DEC-019`—, se informa «sin release productiva nueva
disponible» y no se muta nada.

**Lección.** «La CI de este SHA pasó» no es lo mismo que «la CI de este SHA en `main`, disparada por
un push, pasó». En un gate de despliegue la diferencia es sustantiva.

---

## E - Un mismatch de configuración no ejecutaba rollback

**Qué pasó.** El actualizador comparaba los hashes de la configuración local después de preparar y
activar, pero ante una discrepancia hacía simplemente `exit 1`.

**Por qué es un problema.** Si SIS-Leg estaba activo y ya se había activado una release nueva, salir
con error dejaba el sistema corriendo la release nueva con una configuración que había cambiado de
forma inesperada, y sin nadie que revirtiera nada.

**Corrección.** Un mismatch de configuración se trata como **falla de despliegue**:

- **nunca** se sobrescribe ni se restaura la configuración desde Git o desde plantillas: los archivos
  locales se preservan tal como estén;
- si SIS-Leg estaba activo: rollback de **release** a la anterior con el mecanismo oficial,
  restauración del `target-release` previo, verificación del estado formal, y detención;
- si Legacy estaba activo y sólo se preparó una release: restaurar `target-release` y dejar Legacy
  intacto;
- si el propio rollback falla: contención fail-safe de bridges, reporte de estado inconsistente y
  **no reintentar**.

**Lección.** Ante un conflicto entre software y configuración institucional, se retrocede el
software. La configuración es el activo irremplazable.

---

## F - Sondas de runtime dependientes del cwd del invocador

**Qué pasó.** En el smoke post-sesión (fase 5K), la vuelta Legacy → SIS-Leg falló al validar permisos
de sólo lectura de la release:

```text
find: fallo al restaurar el directorio de trabajo inicial: /home/concejo: Permiso denegado
```

El rollback integrado funcionó: SIS-Leg retirado, Legacy restaurado, `ESTABLE_LEGACY`, un solo
bridge, cero reintentos y configuración intacta. No hubo incidente operativo abierto, pero sí un
defecto de producto reproducible.

**Por qué.** `herramienta_despliegue.py` ejecuta sondas de permisos con `runuser` usando las
identidades reales de runtime. La validación de sólo lectura corría
`runuser --user sis-leg-backend -- find <release> ...` **sin fijar un cwd**. Invocada con `sudo`
desde `/home/concejo` —cuyo modo no permite acceso al usuario de runtime—, la sonda heredaba ese
directorio; GNU `find` recorría la release correctamente pero terminaba con código 1 al no poder
restaurar el cwd heredado.

Consecuencia: **activar una release válida podía fallar según el directorio desde el que el operador
lanzara el comando.**

**Corrección — WP-094.** Todas las sondas `runuser` pasaron a ejecutarse con un directorio de trabajo
explícito, seguro y accesible (`/`), a través del ejecutor inyectable ya existente. Se revisaron
**todas** las invocaciones a `runuser`, no sólo el `find` que manifestó el fallo. Los tests
inspeccionan explícitamente el directorio enviado al ejecutor.

Se rechazaron de forma expresa las salidas fáciles: nada de `os.chdir()` global, ignorar el código de
salida de `find`, suprimir stderr, cambiar los permisos de `/home/concejo`, dar al usuario de runtime
acceso al home del operador, o parchear producción a mano.

**Lección.** Una validación de seguridad cuyo resultado depende del entorno del invocador no es una
validación: es un resultado aleatorio. Y la corrección correcta era eliminar la dependencia, no
relajar los permisos del home del operador —que habría degradado la seguridad para tapar un bug.

---

## G - No suponer un estado del host: consultarlo

**Qué pasó.** El primer gate de smoke post-sesión daba por sentado que el host empezaría en
`ESTABLE_LEGACY`. El precheck real mostró `ESTABLE_SISLEG`. Hubo que reemitir la asignación con la
secuencia invertida.

En el mismo contexto se aclaró que un **404 de `/estados/estado_global` mientras SIS-Leg está activo
no es una falla**: ese endpoint pertenece al backend Legacy, que en `ESTABLE_SISLEG` debe estar
inactivo. Interpretarlo como error habría llevado a «reparar» un sistema sano.

**Corrección.** Todo precheck consulta el estado formal **antes** de decidir la secuencia, y el guard
institucional se hace contra el sistema **realmente activo**: `GET /estados/estado_global` cuando
manda Legacy, `GET /api/v1/estado/moderacion` cuando manda SIS-Leg. Un estado no reconocido o una
consulta ambigua abortan sin mutar.

**Lección.** Un plan escrito contra un estado supuesto es un plan que muta el sistema equivocado.

---

## H - Cero reintentos en gates de producción

No es un defecto sino una política, y explica el resto.

En todas las fases mutantes de WP-029 se autorizó **una sola ejecución** de cada operación, con
**cero reintentos** ante una falla relevante. Después de una falla sólo se permitían diagnósticos de
sólo lectura y el rollback automático ya integrado; nada de reparaciones manuales, segundos intentos
ni parches ad hoc.

**Por qué.** Un reintento sobre una máquina institucional en estado dudoso multiplica el riesgo y
destruye la evidencia de la primera falla. Los tres defectos de producto de esta puesta en marcha
(A, F y los hallazgos de la auditoría) se diagnosticaron precisamente porque nadie intentó
«arreglarlos en el momento»: quedó un estado limpio, un rollback correcto y un error reproducible que
se corrigió en desarrollo con Work Package, revisión independiente y CI.

**Lección.** El rollback automático es el único reintento aceptable. Todo lo demás vuelve a
desarrollo.
