# 05 - Conmutación temporal Legacy ↔ SIS-Leg

Todo lo descrito en este documento **existe sólo en el host institucional** durante la transición.
No está versionado en este repositorio y no forma parte del producto. Es el andamiaje que permite
alternar entre los dos sistemas de forma segura hasta que se decida el cutover definitivo.

> **Reemplazo preparado.** WP-101A versionó una implementación canónica equivalente de estas tres
> operaciones (`deploy/estado_host.py`, `deploy/operaciones_host.py` y los wrappers de
> `deploy/host/`), con pruebas y revisión independiente. **Todavía no está instalada**: lo que corre
> hoy en el host es lo que describe este documento. La comparación entre ambos mecanismos y los pasos
> pendientes están en [10 - Mecanismo versionado y su aplicación](10-mecanismo-versionado-y-aplicacion.md).

## Por qué existe

`deploy/herramienta_despliegue.py activar` sabe activar una release de SIS-Leg, pero no sabe nada de
Legacy. Llamarla directamente con Legacy corriendo dejaría dos backends peleando por `:8000`, dos
bridges peleando por los mismos numpads y dos vhosts de Nginx compitiendo. La conmutación necesita
una capa por encima que retire ordenadamente un sistema antes de instalar el otro, y que sepa
deshacer todo si algo falla a mitad de camino.

## Capas

```text
Escritorio (.desktop)
  └── wrappers de usuario   /home/concejo/.local/bin/*.sh
        └── scripts privilegiados   /usr/local/bin/sisleg-*
              └── herramienta oficial   deploy/herramienta_despliegue.py
```

Cada capa tiene una responsabilidad distinta y la regla es que **ninguna capa superior puede saltar
una inferior**: un lanzador no hace `systemctl`, un wrapper no hace `systemctl`, y sólo el script
privilegiado invoca la herramienta oficial.

### Scripts privilegiados (`root:root 0755`)

| Script | Rol |
| --- | --- |
| `/usr/local/bin/sisleg-estado` | Sólo lectura. Clasifica el host (ver [01](01-topologia-actual.md)). |
| `/usr/local/bin/sisleg-activar` | Secuencia segura Legacy → SIS-Leg para un SHA dado. |
| `/usr/local/bin/sisleg-activar-target` | Variante que toma el SHA de `/opt/sis-leg/target-release`. |
| `/usr/local/bin/sisleg-activar-legacy` | Secuencia segura SIS-Leg → Legacy, independiente de versión. |

Propiedades exigidas y auditadas en los tres scripts mutantes:

- `set -Eeuo pipefail`;
- exigen root para acciones mutantes;
- **lock exclusivo con `flock`**, compartido entre conmutación y actualización, de modo que no puedan
  correr dos operaciones a la vez;
- sin `eval`, sin `curl | sh`, sin `|| true` que silencie fallos críticos;
- rutas y unidades como constantes explícitas;
- cada transición verifica el estado alcanzado antes de avanzar a la siguiente.

### Wrappers de usuario

| Wrapper | Lanzador |
| --- | --- |
| `/home/concejo/.local/bin/control-cambiar-sisleg.sh` | «Cambiar a SIS-Leg» |
| `/home/concejo/.local/bin/control-cambiar-legacy.sh` | «Cambiar a Legacy» |
| `/home/concejo/.local/bin/actualizar-sisleg.sh` | «Actualizar SIS-Leg» ([06](06-actualizador-actual.md)) |

Cada wrapper consulta `sisleg-estado --tag`, es idempotente si el sistema pedido ya está activo,
**aborta sin mutar** ante `INERTE_SEGURO` o `ESTADO_INCONSISTENTE`, pide confirmación humana visible
antes de una conmutación real, verifica el estado final y deja el resultado a la vista hasta que la
persona lo cierre. Registran cada operación en `/home/concejo/sisleg-switch-history.log`.

La autenticación usa el `sudo` interactivo ya disponible. **No** se modificó `/etc/sudoers`,
`/etc/sudoers.d/*`, PolicyKit ni permisos de systemd, y **no** existe `sudo` sin contraseña.

### Lanzadores del escritorio

Las pantallas se abren con URL estables y sin SHA:

```text
Moderación  → http://127.0.0.1/moderacion/
Recinto     → http://127.0.0.1/recinto/
Técnico     → http://127.0.0.1/tecnico/
Manual      → http://127.0.0.1/manual/
Simulador   → http://127.0.0.1/simulador/
```

En modo aplicación y pantalla completa (`--app=<URL> --start-fullscreen`, sin `--new-window`). Los
lanzadores Legacy se conservan. Los tres controles operativos son «Cambiar a SIS-Leg», «Cambiar a
Legacy» y «Actualizar SIS-Leg».

## Target dinámico

Los lanzadores y wrappers **no pueden contener un SHA**. La release que debe activarse se lee de
`/opt/sis-leg/target-release` ([02](02-layout-en-disco.md)).

Antes de escribir ese archivo se exige, en este orden:

1. SHA de 40 hexadecimales en minúscula;
2. `/opt/sis-leg/releases/<SHA>` existe;
3. no es un symlink;
4. `readlink -f` resuelve exactamente a esa ruta —sin traversal;
5. el marcador existe y es un archivo regular;
6. el marcador parsea como JSON;
7. `marker.commit_sha == <SHA>`;
8. `marker.tree_sha` es un árbol Git válido y coincide con el que declara el `release.json` que viajó
   dentro del paquete público.

Recién entonces se reemplaza atómicamente. Las primeras siete comprobaciones no estaban completas en
la implementación original y fueron una de las correcciones exigidas por la auditoría 5I. La octava
la agregó el mecanismo versionado de WP-101A: el commit por sí solo no identifica el contenido, y sin
comparar el árbol una release manipulada después de instalada podía activarse igual.

## Secuencia Legacy → SIS-Leg

Esta secuencia fue auditada en tres pasadas antes de ejecutarse por primera vez.

1. adquirir el lock global;
2. precheck de estado formal; rechazar `ESTADO_INCONSISTENTE`;
3. guard de sesión Legacy: `GET /estados/estado_global` debe responder 200 con `hay_sesion == false`;
4. validar el target: release preparada, marcador coherente, configuración local válida;
5. tomar snapshot del vhost Legacy y de los estados `enabled`;
6. **`disable` de las unidades Legacy antes de detenerlas** (*disable-first*), para que un reinicio
   no las devuelva;
7. detener el **bridge** Legacy y verificar `inactive`;
8. detener el backend Legacy y verificar `inactive` y el puerto `:8000` libre;
9. retirar el symlink `/etc/nginx/sites-enabled/botonera`;
10. invocar la herramienta oficial de la release preparada: `activar <SHA>`;
11. verificar backend SIS-Leg, health directo y vía Nginx, las cinco superficies y la exclusión de
    Legacy;
12. arrancar el **bridge** SIS-Leg recién después de que el backend está sano;
13. `enable` de las dos unidades SIS-Leg sólo después del health exitoso;
14. clasificar el estado final como `ESTABLE_SISLEG`.

El orden bridge-último no es cosmético: si el bridge tomara los numpads antes de que el backend
estuviera sano, el hardware quedaría capturado por un sistema incapaz de registrar los votos.

### Rollback externo

Se dispara ante cualquier fallo **posterior** al inicio de la retirada de Legacy, y tiene que
tolerar que la herramienta oficial haya fallado en cualquier punto:

- detener bridge SIS-Leg y luego backend SIS-Leg si existen o están activos;
- `disable` de ambas unidades SIS-Leg;
- mover `/etc/nginx/conf.d/sis-leg.conf` a `.conf.disabled`;
- restaurar el symlink Legacy exacto;
- dejar `current` en un estado que permita una reactivación futura —si quedara apuntando al mismo
  SHA con las unidades y el vhost ya retirados, la próxima llamada a `activar` retornaría temprano
  creyendo que no hay nada que hacer;
- `enable` + `start` del backend Legacy, comprobar puerto y HTTP;
- `start` del bridge Legacy;
- `nginx -t` y reload;
- verificar `ESTABLE_LEGACY`.

**No borra releases, configuración ni logs.**

## Secuencia SIS-Leg → Legacy

Independiente de versión e idempotente:

1. `disable` de las unidades SIS-Leg primero;
2. detener bridge SIS-Leg y luego backend SIS-Leg;
3. mover el vhost activo a `.conf.disabled`;
4. tratar `current` de forma consistente con una reactivación futura;
5. restaurar el symlink Legacy;
6. `enable` + `start` del backend Legacy y **después** el bridge Legacy;
7. `nginx -t` y reload;
8. verificar health y `ESTABLE_LEGACY`.

**`--recover` nunca se usa automáticamente**: recuperar un estado inconsistente es una decisión
humana, no un reintento silencioso.

## Invariantes que gobiernan toda conmutación

1. Máximo **un** bridge activo en todo momento.
2. Nunca iniciar SIS-Leg sin haber deshabilitado y detenido antes el bridge Legacy, y viceversa.
3. No tocar ni regenerar la configuración local.
4. No desplegar un SHA de `main` cuya CI productiva no esté verde.
5. No usar `git pull` como mecanismo de despliegue.
6. No instalar dos copias operativas de SIS-Leg.
7. Los lanzadores de pantallas no contienen SHA.
8. Toda operación es fail-safe y con rollback.
9. No modificar sudoers ni introducir `sudo` sin contraseña.
10. **Cero reintentos** ante una falla en un gate productivo.

## Estado de la transición

El período de alternancia sigue vigente: ambos sistemas están instalados y el operador puede cambiar
de uno al otro desde el escritorio. Esto **no** es un cutover. El sistema Legacy no se retira, no se
desinstala y no se degrada sin una compuerta humana específica y evidencia de respaldo y rollback
([09 - Estado conocido y compuertas](09-estado-y-gates.md)).
