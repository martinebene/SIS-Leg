# 06 - Actualizador actual (estado previo a WP-100)

> **Este documento describe un mecanismo transitorio.** El actualizador que hoy corre en el host
> depende de GitHub Actions **autenticado**. Esa dependencia es una limitación de la etapa actual,
> no el diseño final, y WP-100 la va a eliminar. Ver [Limitación transitoria](#limitación-transitoria-y-wp-100).

## Qué es

`/home/concejo/.local/bin/actualizar-sisleg.sh`, invocado por el lanzador «Actualizar SIS-Leg». Trae
la última release productiva de `main`, la prepara y deja el sistema listo para usarla.

Está **operativamente validado**: se ejecutó una vez de forma real, bajo autorización humana
explícita, para traer la release A702, y superó todos sus gates (ver
[07 - Cronología](07-cronologia.md), hito 12). Desde esa aceptación puede usarse normalmente para
futuras releases de `main` **sin una compuerta humana por cada SHA**, siempre que sus propios guards
internos pasen.

Esa aceptación **no** autoriza saltar sus guards, desplegar artefactos manuales o no canónicos,
actualizar durante una sesión, modificar configuración local desde Git, tocar sudoers, borrar
releases o logs, ni activar más de un bridge.

## Flujo

1. adquirir el **lock global** compartido con las conmutaciones;
2. **guard institucional**: consultar el sistema realmente activo —Legacy o SIS-Leg, según
   corresponda— y abortar si hay preparación o sesión, o si la consulta no puede resolverse;
3. resolver el SHA actual de `martinebene/SIS-Leg@main`;
4. seleccionar la run de CI que corresponde **exactamente** a ese SHA;
5. exigir `conclusion == success`;
6. exigir el job exacto `Empaquetado · release productiva` exitoso;
7. descargar de **esa** run el artifact exacto `sis-leg-release-<SHA>`;
8. verificar el sidecar SHA-256;
9. verificar `release.json`, `commit_sha` y `tree_sha`;
10. ejecutar `preflight` con la herramienta oficial del artefacto;
11. `preparar` la release;
12. validar la release preparada;
13. preservar la configuración local y verificar sus hashes;
14. actuar según el sistema activo.

### Selección de CI y artifact

Es deliberadamente rígida. Se exige, sin excepciones:

| Campo | Valor requerido |
| --- | --- |
| workflow | `CI` |
| `head_sha` | el SHA de `main` resuelto |
| `head_branch` | `main` |
| `event` | `push` |
| `status` | `completed` |
| `conclusion` | `success` |
| job | `Empaquetado · release productiva`, coincidencia **exacta** |
| artifact | `sis-leg-release-<SHA>`, de **esa** run, no expirado (ver [nota sobre el nombre del artifact](#el-nombre-del-artifact-interno-cambia-con-wp-100)) |

Si hay varias runs válidas para el mismo SHA, se elige una de forma determinística; si no se puede
demostrar una única elección correcta, se aborta. **No se acepta una run de `pull_request` aunque
comparta SHA**: la CI de una PR valida un merge hipotético, no el contenido que quedó en `main`.

Comportamiento ante casos límite:

| Situación | Conducta |
| --- | --- |
| CI todavía `pending` | No mutar. Informar y salir. |
| CI fallida | No mutar. Informar y salir. |
| Artifact ausente o expirado | Abortar. |
| Commit documental en `main` sin run productiva (exención de `DEC-019`) | Informar «sin release productiva nueva disponible» y **no** mutar. |
| `main` cambia mientras corre el actualizador | Abortar; la operación estaba autorizada para el SHA resuelto al inicio. |
| `target-release == main_sha` y la release está preparada | Informar «SIS-Leg ya está actualizado», no descargar, no preparar, no reiniciar, salir 0. |
| SIS-Leg activo pero `current` difiere de `target-release` aunque `target == main` | Informar la diferencia explícitamente y manejarla fail-safe. **No** asumir en silencio qué hacer. |

### Si Legacy está activo

- **no** conmuta a SIS-Leg sólo por actualizar;
- prepara la release nueva;
- actualiza atómicamente `target-release` al SHA nuevo;
- deja Legacy activo e ininterrumpido;
- informa: *«SIS-Leg actualizado y preparado. Se activará al pulsar Cambiar a SIS-Leg.»*

Actualizar y conmutar son decisiones distintas. Que haya una versión nueva disponible no es motivo
para cambiar el sistema que está atendiendo el recinto.

### Si SIS-Leg está activo

- prepara la release nueva y **conserva** el `target-release` anterior;
- ejecuta una actualización en caliente controlada de release actual → release nueva, usando la misma
  lógica segura e independiente de versión;
- **no** pasa por Legacy;
- verifica health completo;
- si tiene éxito: actualiza `target-release` al SHA nuevo y deja `ESTABLE_SISLEG`;
- si falla: rollback automático a la release SIS-Leg anterior, restauración del `target-release`
  previo y diagnóstico claro.

Si el estado es inconsistente o no reconocido, aborta sin mutar.

## Lo que el actualizador informa antes de mutar

Muestra el SHA instalado o `current` si aplica, el `target-release`, el SHA actual de `main`, la run
de CI seleccionada, el artifact, el plan de acción y pide confirmación. Al terminar deja el resultado
final visible en la terminal. Todo queda registrado en `/home/concejo/sisleg-update-history.log`.

## Guards que el actualizador nunca puede saltar

- no hay sesión ni preparación institucional activa;
- el estado formal del host es reconocido y estable;
- lock global adquirido;
- CI exacta de `push` sobre `main`, completada y exitosa;
- job y artifact exactos;
- sidecar, `release.json`, commit/tree y `preflight` válidos;
- preservación byte a byte de la configuración local;
- máximo un bridge activo;
- rollback y contención fail-safe ante cualquier falla.

## Limitación transitoria y WP-100

Hoy el actualizador **necesita `gh` autenticado** para consultar las runs de Actions y descargar el
artifact. Eso implica credenciales de GitHub presentes en la máquina institucional, sólo para
consumir software que el repositorio ya publica en abierto.

Es una limitación de esta etapa, no una decisión de arquitectura. El repositorio de producto es
público y una instalación productiva debería poder actualizarse usando únicamente recursos públicos.

**WP-100 va a eliminar esta dependencia.** El requisito es explícito en la campaña actual: el
mecanismo «Actualizar SIS-Leg» no debe requerir `gh auth`, PAT, `.github_token` ni credenciales del
repositorio.

La condición de seguridad es igual de explícita: **quitar la autenticación no puede degradar la
garantía de consumir una versión validada.** El diseño de WP-100 tendrá que ofrecer un canal público
determinista —una release pública o un manifiesto público equivalente— generado **sólo después de una
CI exitosa en `main`**, de modo que producción no necesite consultar Actions autenticado ni confiar
en un paquete sin validar. El actualizador deberá descubrir esa release pública, descargarla sin
credenciales, verificar identidad y checksums, y mantener intactos los guards institucionales, el
lock global y la preservación de la configuración local.

## Estado con WP-100 implementado

WP-100 ya construyó ese canal público. Desde su integración el repositorio publica, para cada
`push` a `main` con CI completa verde, una GitHub Release inmutable `sis-leg-<SHA>` con paquete,
sidecar y metadatos, y el Producto incluye `deploy/actualizador_publico.py`, que la consume sin
ninguna credencial del host. El diseño completo está en
[13 - Despliegue y operación](../13-despliegue-y-operacion.md), sección «Canal público de
releases por SHA».

**El wrapper instalado en el host sigue siendo el descrito en este documento.** WP-100 es
desarrollo únicamente: no instaló ni reemplazó `/home/concejo/.local/bin/actualizar-sisleg.sh`,
no tocó `/opt/sis-leg`, no modificó launchers `.desktop` y no ejecutó ninguna actualización real.
Adaptar el wrapper productivo al canal público corresponde a WP-101 y a su compuerta humana.

### El nombre del artifact interno cambia con WP-100

Para que la release pública pueda demostrar **qué intento de CI construyó los bytes publicados**,
WP-100 pasó a nombrar el artifact interno de empaquetado con el SHA **y** el número de intento:
`sis-leg-release-<SHA>-intento-<N>`. Los nombres públicos de la release —`sis-leg-<SHA>.tar.gz`,
su sidecar `.sha256` y sus metadatos— no cambian.

Consecuencia operativa: desde la integración de WP-100, el wrapper descrito en este documento ya
no encuentra un artifact llamado exactamente `sis-leg-release-<SHA>`. Su propio guard lo trata como
«artifact ausente» y **aborta sin mutar nada**, que es el comportamiento fail-safe esperado. No hay
riesgo de desplegar un paquete incorrecto; sí deja de haber actualizaciones por esa vía hasta que
WP-101 adapte el wrapper al canal público, que es su reemplazo previsto.

Hasta que eso ocurra, **el mecanismo descrito en este documento es el vigente en producción** y
cualquier documentación que lo presente como definitivo es incorrecta.

## Estado con WP-101A implementado

WP-101A construyó el reemplazo versionado de este wrapper: `deploy/operaciones_host.py`, apoyado en
`deploy/estado_host.py` y en los wrappers de `deploy/host/`, implementa «Actualizar SIS-Leg» sobre el
canal público de WP-100, sin `gh`, PAT, `.github_token`, token, cookie ni login, conservando el lock
global, los guards institucionales, `target-release` atómico y version-agnóstico, la idempotencia, el
health completo, el rollback y la preservación byte a byte de la configuración local.

**Ese reemplazo todavía no está instalado.** WP-101A es desarrollo únicamente: no escribió en
`/opt/sis-leg`, `/usr/local/bin` ni `/etc`, no modificó ningún `.desktop` y no ejecutó ninguna
actualización real. Instalarlo en el host corresponde a WP-101B, que está pendiente de acceso al
equipo de producción y de una compuerta humana específica.

La comparación entre el mecanismo instalado hoy, el preparado por WP-101A y los pasos que faltan está
en [10 - Mecanismo versionado y su aplicación](10-mecanismo-versionado-y-aplicacion.md).
