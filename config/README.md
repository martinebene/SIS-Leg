# Configuración funcional

Ubicación de la configuración y el padrón que el backend lee en ejecución.

## Plantillas versionadas y archivos operativos locales

Desde WP-073 cada archivo de configuración existe en dos formas:

| Plantilla versionada                                 | Archivo operativo local                      | Quién lo escribe                |
| ---------------------------------------------------- | -------------------------------------------- | ------------------------------- |
| `config/system.example.toml`                         | `config/system.toml`                         | la persona que opera el sistema |
| `config/concejales.example.csv`                      | `config/concejales.csv`                      | la persona que opera el sistema |
| `config/apoyo-tecnico/mensajes.example.csv`          | `config/apoyo-tecnico/mensajes.csv`          | el backend, por REST            |
| `services/device-bridge/config/devices.example.json` | `services/device-bridge/config/devices.json` | el device bridge, al remapear   |

Las rutas que el sistema lee siguen siendo las de la columna del medio. Lo
único que cambió es que **esos cuatro archivos ya no se versionan**: están
declarados en `.gitignore` porque son estado real de cada instalación. Así una
prueba humana, un remapeo de hardware o un ajuste de volumen dejan de ensuciar
el checkout y de bloquear `scripts/iniciar_wp_orca.py`.

Las plantillas `*.example.*` sí se versionan: son el contenido de referencia que
la revisión ve en cada Pull Request. Un cambio real en una plantilla aparece en
Git como cualquier otro archivo.

## Preparar un clon nuevo

```bash
uv run python scripts/preparar_config_local.py
```

o, equivalente, `pnpm preparar:config`.

El comando copia cada plantilla a su ruta operativa **sólo si esa ruta no
existe**, crea los directorios que falten, informa qué creó y qué preservó, y
termina con código distinto de cero ante un fallo real de E/S. Repetirlo es
idempotente y **nunca sobrescribe** un archivo existente: `mensajes.csv` y
`devices.json` contienen trabajo operativo que no está en ningún commit.

`pnpm dev:stack`, `pnpm dev:stack:hot` y `pnpm test:e2e:integrado` lo ejecutan
solos antes de arrancar, de modo que un clon nuevo funciona sin pasos manuales.

## Las pruebas nunca escriben tu biblioteca

`config/apoyo-tecnico/mensajes.csv` es el único de los cuatro que el backend
escribe por su cuenta, así que es también el único que una prueba podría llegar
a pisar. No lo hace: el E2E integrado arranca el stack con
`--ruta-mensajes-tecnicos`, apuntándolo a una copia temporal fuera del
repositorio sembrada desde `mensajes.example.csv`. El CRUD se ejercita contra
esa copia, con persistencia real a disco, y el harness comprueba al detener el
stack que tu archivo quedó byte a byte y con la misma fecha de modificación.

Esa opción existe únicamente para el harness de pruebas. El arranque productivo
no la usa y resuelve siempre `config/apoyo-tecnico/mensajes.csv`. Es además el
único archivo runtime reubicable: configuración, padrón y mapeo físico no
admiten desvío.

## Migrar un clon que ya existía

Un clon anterior a WP-073 tiene los cuatro archivos **trackeados**, y puede
tener además banderas `skip-worktree` puestas a mano como mitigación. Adoptar el
commit que deja de trackearlos borraría el contenido local, así que hay que
resguardarlo primero. El procedimiento completo, con los comandos exactos, está
en la sección «Migración de un clon anterior a WP-073» del `README.md` de la
raíz.

## Producción

Producción no usa nada de esto: provisiona su configuración fuera de las
releases, bajo `/opt/sis-leg/config/`, según `docs/13-despliegue-y-operacion.md`.
El empaquetado sigue excluyendo deliberadamente `config/`, de modo que ni las
plantillas ni los archivos operativos locales viajan en un artefacto.

## Mensajes precargados de Apoyo Técnico

`apoyo-tecnico/mensajes.csv` guarda la biblioteca de mensajes que el puesto de
Apoyo Técnico puede publicar como aviso (WP-055). Es el **único** archivo de
`config/` que el backend escribe: lo administra por REST y lo reemplaza de
forma atómica.

Formato canónico, en UTF-8:

```
id,texto,destino
```

- `id`: identificador estable de 1 a 64 caracteres alfanuméricos, `-` o `_`.
  Lo genera el backend al crear el mensaje y no cambia al editarlo.
- `texto`: contenido de una sola línea, hasta 500 caracteres.
- `destino`: `MODERACION`, `RECINTO` o `AMBOS`.

Si el archivo no existe, la biblioteca simplemente está vacía. Si existe pero
no cumple el formato, el backend arranca igual, publica la biblioteca como no
disponible y **rechaza toda escritura** para no destruir su contenido: hay que
corregir el archivo a mano y reiniciar el backend.

Por eso el archivo vive en su propio subdirectorio: reemplazarlo de forma
atómica exige que el usuario del backend pueda escribir en el directorio que lo
contiene, mientras `system.toml` y `concejales.csv` siguen siendo de solo
lectura para el servicio.

## Sonidos de la Pantalla del Recinto

La sección `[sonidos]` de `system.toml` asigna un archivo y un volumen a cada
uno de los **quince** eventos sonoros del Recinto (WP-065). Cada entrada es una
subtabla con exactamente dos claves:

```toml
[sonidos.sesion_abierta]
ruta = "assets/sonidos/sesion-abierta.wav"
volumen = 90
```

- `ruta`: relativa a la raíz pública de la Pantalla del Recinto. Debe empezar
  por `assets/sonidos/` y terminar en `.wav`. Se rechazan URLs, rutas
  absolutas, barras invertidas y segmentos `..`, porque esta ruta viaja al
  navegador y nunca puede referirse a un archivo arbitrario del sistema.
- `volumen`: entero de `0` a `100`. `0` silencia el evento sin borrar su
  configuración. Los decimales y los booleanos se rechazan.

Los quince eventos son obligatorios y sus nombres son fijos:
`preparacion_iniciada`, `aviso_tecnico_publicado`, `aviso_tecnico_retirado`,
`pedido_palabra_registrado`, `pedido_palabra_retirado`, `uso_palabra_otorgado`,
`transmision_iniciada`, `transmision_detenida`,
`transmision_cuenta_regresiva_tic`, `sesion_abierta`, `sesion_cerrada`,
`votacion_abierta`, `votacion_cerrada`, `concejal_ausente` y
`concejal_presente`. Un nombre mal escrito no se ignora: la carga falla, para
que un sonido nunca desaparezca en silencio.

A diferencia de las secciones anteriores, cuyas claves están en inglés desde
WP-003, esta sección usa nombres en español. Es una sección nueva, sin
compatibilidad que preservar, y le aplica la regla general de DEC-001.

### Doble lectura deliberada

`[sonidos]` se lee dos veces y por motivos distintos:

1. al **preparar el recinto**, junto con el resto de `system.toml`, quedando
   congelada en el snapshot de la preparación como cualquier otro parámetro;
2. al **arrancar el backend**, porque la Pantalla del Recinto debe poder sonar
   ya en `SIN_PREPARAR`: la transmisión en vivo y los avisos de Apoyo Técnico
   se operan fuera de una sesión.

La segunda lectura es tolerante: un archivo ausente o inválido no impide el
arranque, publica la configuración de audio como no disponible con su motivo y
degrada solamente el sonido. La primera es estricta: una sección inválida
impide preparar el recinto, igual que un `quorum` inválido.

Preparar el recinto refresca además la copia leída al arrancar, de modo que
durante una preparación o sesión el Recinto escuche exactamente la
configuración congelada.

### Assets

Los 22 archivos WAV viven en `apps/recinto/public/assets/sonidos/`: 15
asignados y 7 alternativas sin asignar, para cambiar un sonido editando sólo
este archivo. Son originales del proyecto, generados de forma determinista por
`scripts/generar_sonidos_recinto.py`; su procedencia, formato y SHA-256 están
documentados en `assets/sonidos/README.md`.
