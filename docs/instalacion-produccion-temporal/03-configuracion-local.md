# 03 - Modelo de configuración local

## Los cuatro archivos persistentes

La instalación productiva tiene hoy exactamente cuatro archivos de configuración local bajo
`/opt/sis-leg/config/`:

| Archivo | Qué define | Quién lo lee |
| --- | --- | --- |
| `system.toml` | Configuración funcional del sistema: identidad institucional, rutas, sonidos, parámetros de votación. | backend |
| `concejales.csv` | Padrón: bancas, personas, bloques, `ruta_imagen`. | backend |
| `apoyo-tecnico/mensajes.csv` | Mensajes del puesto de Apoyo Técnico. | backend |
| `bridge/devices.json` | Mapeo físico: fingerprint del dispositivo → identificador lógico. | device bridge |

Su contenido es institucional y **no se documenta acá**: esta carpeta es pública y el padrón, los
mensajes y las fingerprints de los dispositivos no corresponden a un repositorio abierto.

Dos propiedades importantes:

- El **nombre institucional** vive en la sección `[institucion]` de `system.toml` desde WP-084. No
  está escrito en el código ni debe aparecer en la documentación activa del repositorio.
- `paths.logs_dir` resuelve exactamente a `/opt/sis-leg/logs`. `paths.logs_copy_dir` está
  deliberadamente **omitido** en esta instalación: sin esa clave el backend no intenta ningún acceso
  externo.

## Regla central: la configuración local nunca se sobrescribe en silencio

Es la invariante que gobierna todo el mecanismo de actualización. Una release trae código, SPA,
manual y assets; **no trae la configuración de la instalación**.

En cada operación productiva:

1. antes de mutar nada se registra el SHA-256 de los cuatro archivos (baseline);
2. después de la operación se vuelve a calcular;
3. si alguno cambió inesperadamente, la operación se considera **fallida** y se ejecuta la contención
   correspondiente.

Está prohibido, durante cualquier operación productiva:

- copiar plantillas `*.example.*` sobre la configuración real;
- ejecutar `scripts/preparar_config_local.py`, que es exclusivamente un bootstrap de desarrollo y no
  tiene ningún papel en el despliegue productivo (WP-073);
- reemplazar el directorio `/opt/sis-leg/config`;
- borrar, recrear o restaurar esos archivos desde Git.

El repositorio publica una plantilla por archivo (`*.example.*`) que sirve como referencia de formato
y punto de partida de una instalación nueva. El artefacto productivo **no las incluye**.

## Qué pasa si el rollback tiene que actuar

Un mismatch de configuración detectado al final de una actualización no se «arregla» tocando la
configuración. La conducta correcta, exigida a partir de la auditoría 5I, es:

- **no** modificar el contenido de los archivos locales, cualquiera sea su estado;
- si SIS-Leg estaba activo y ya se activó una release nueva: hacer rollback de **release** a la
  anterior con el mecanismo oficial, restaurar el `target-release` previo, verificar el estado formal
  y detenerse;
- si Legacy estaba activo y sólo se preparó una release: restaurar el `target-release` previo, dejar
  Legacy intacto y detenerse;
- si el propio rollback falla: aplicar la contención fail-safe de bridges, reportar estado
  inconsistente y **no reintentar**.

La lógica es que la configuración local es el activo institucional irremplazable; el software es
reinstalable. Ante duda, se retrocede el software, nunca la configuración.

## El modelo va a crecer

Este modelo de cuatro archivos **es el estado actual, no el estado final**.

WP-098 ya implementó en desarrollo la primera ampliación prevista: una fuente única de imágenes de
bancas bajo la configuración local, en `config/assets/bancas/`, que el backend publica en
`GET /api/v1/recursos/imagenes-concejales/<archivo>`. Cambiar una foto en el host se refleja en
todas las superficies sin reconstruir el frontend y sin reiniciar el backend. El directorio es un
recurso de configuración más: el repositorio versiona la plantilla `config/assets.example/bancas/` y
el bootstrap de desarrollo copia **sólo lo que falta**, archivo por archivo, sin sobrescribir ni
borrar nada.

Dos cosas siguen pendientes y son explícitamente posteriores a WP-098:

- **Permisos productivos.** El plan declarativo de `deploy/herramienta_despliegue.py` no incluye
  todavía `config/assets/` ni su contenido. Habrá que agregarlo —lectura para el usuario del
  backend, sin escritura— junto con el traslado de las fotos reales, porque ambos son operaciones
  sobre el host que WP-098 tiene prohibidas.
- **Traslado de las fotos reales**, según la sección siguiente.

La política de actualización debe distinguir tres casos, y así está previsto para WP-100:

| Caso | Conducta esperada |
| --- | --- |
| Recurso de configuración **nuevo** que la release trae y que no existe localmente | Incorporarlo automáticamente. |
| Recurso de configuración que **ya existe** localmente | No tocarlo nunca. |
| Cambio de **formato o esquema** de un archivo existente | Abortar con diagnóstico explícito y exigir un mecanismo de migración acordado y autorizado por una persona en ese momento. No migrar automáticamente. |

Migrar automáticamente un esquema sería la única forma de que una actualización destruyera trabajo
institucional; por eso se decidió que esa clase de cambio se detenga y escale, aunque cueste una
intervención manual.

## Migración de las fotos productivas

La consolidación de las imágenes de bancas en una fuente única de configuración quedó implementada
en desarrollo por WP-098. **El traslado de las fotos reales que hoy están en el host se hará después
del merge final del lote de desarrollo, por el operador local**, no durante los Work Packages de
desarrollo y no como parte de una actualización automática.

Ese traslado consiste en dejar los archivos bajo `/opt/sis-leg/config/assets/bancas/` con los
nombres que ya declara `ruta_imagen` en el padrón instalado, y aplicarles los permisos de lectura
del usuario del backend. Hasta que eso ocurra, las bancas de esa instalación mostrarían las
iniciales de cada concejal en lugar de su fotografía: la pantalla sigue operando con normalidad.
