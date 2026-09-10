# 02 - Layout de SIS-Leg en disco

## Vista general

```text
/opt/sis-leg/
├── releases/
│   ├── 50abb3832317afefac2175ac51a12acb8d7d583d/
│   ├── bfbb63612f19080264585783cae998fc545b619d/
│   └── a702d71da8c0f2d66b8ccb0231543d15bcdb1e48/
├── current   -> releases/<SHA activo>      (symlink, sólo mientras SIS-Leg está activo)
├── previous  -> releases/<SHA anterior>    (symlink, para rollback)
├── target-release                          (archivo: SHA que debe activarse)
├── config/
│   ├── system.toml
│   ├── concejales.csv
│   ├── apoyo-tecnico/mensajes.csv
│   └── bridge/devices.json
├── logs/
└── logs_backup/
```

`releases/`, `current` y `previous` son mecanismos **del producto**, implementados por
`deploy/herramienta_despliegue.py` y descritos normativamente en `DT-031`.

`target-release` **no es un mecanismo del producto**: es un archivo que sólo existe en este host,
creado durante la transición para que los lanzadores del escritorio no queden atados a un SHA
concreto. Ver [05 - Conmutación](05-conmutacion-legacy-sis-leg.md).

## `releases/<SHA>`

Cada release es un directorio inmutable identificado por el **commit Git completo** del que deriva.
No se despliega con `git pull` sobre el árbol activo; se despliega un artefacto reproducible
construido por CI a partir de un commit cuya CI está verde.

Contenido relevante de una release preparada:

| Ruta | Contenido |
| --- | --- |
| `.sis-leg-preparada.json` | Marcador de release preparada: `commit_sha`, `tree_sha` y metadatos de trazabilidad. |
| `.venv/` | Entorno virtual creado durante `preparar`, con la ruta final ya resuelta. |
| `deploy/herramienta_despliegue.py` | La misma herramienta del checkout que generó el artefacto. |
| `web/moderacion/`, `web/recinto/`, `web/tecnico/`, `web/simulador/` | SPA Nuxt precompiladas. |
| `web/manual/index.html` | Manual de usuario publicado en `/manual/`. |
| `release.json` | Inventario SHA-256 de cada archivo, commit/tree, Python objetivo, paquetes. |

Reglas verificadas en cada gate productivo:

- el directorio de la release **no** puede ser un symlink;
- `readlink -f` debe resolver exactamente a `/opt/sis-leg/releases/<SHA>` (sin traversal);
- el marcador debe existir, ser un archivo regular, parsear como JSON y cumplir
  `commit_sha == <SHA>`;
- la release queda de sólo lectura para las identidades de runtime según la política de la
  herramienta.

Las releases viejas **no se borran**. Son el mecanismo de rollback y el historial verificable de qué
estuvo instalado. No son instalaciones paralelas: sólo una es la vigente.

## `current` y `previous`

- `current` apunta a la release activa. Existe únicamente mientras SIS-Leg está activo; una
  conmutación a Legacy la trata de forma que una reactivación futura vuelva a funcionar.
- `previous` apunta a la release inmediatamente anterior y es el destino por defecto de
  `rollback`. Un rollback exitoso intercambia de hecho `current` y `previous`, lo que permite
  roll-forward.
- Ambos se cambian con reemplazo atómico del enlace, nunca con un borrado seguido de una creación.

## `target-release`

Archivo regular `root:root`, modo `0644`, cuyo contenido es exactamente un SHA Git de 40 caracteres
hexadecimales en minúscula más un salto de línea.

Responde a una pregunta que `current` no puede responder: **cuál release hay que activar cuando el
operador pulse «Cambiar a SIS-Leg» mientras Legacy está activo.** Con Legacy corriendo no hay
`current`, así que sin `target-release` el lanzador tendría que llevar un SHA escrito adentro —que es
exactamente lo que se quería eliminar.

Reglas:

- sólo puede referenciar una release ya preparada y validada bajo `/opt/sis-leg/releases/<SHA>`;
- se reemplaza atómicamente;
- nunca debe quedar apuntando a una release incompleta;
- si una actualización falla, se restaura el valor anterior;
- ningún wrapper operativo puede llevar un SHA escrito de forma fija.

La validación previa a escribirlo es deliberadamente estricta —formato, existencia, no-symlink,
resolución exacta, marcador parseable y coincidente— porque un `target-release` manipulado sería una
vía directa para activar contenido arbitrario. Esa validación fue una de las correcciones exigidas en
la auditoría 5I ([08 - Incidentes](08-incidentes-y-lecciones.md), incidente C).

## `config/` y `logs/`

Viven **fuera** de `releases/` precisamente para que una actualización o un rollback no los sustituya
ni los elimine (`DT-031`, `DT-032`). Su contenido se detalla en
[03 - Modelo de configuración local](03-configuracion-local.md).

Plan de permisos aplicado por `bootstrap --aplicar-usuarios`:

| Ruta | Política |
| --- | --- |
| `/opt/sis-leg` | Atravesable. |
| `/opt/sis-leg/releases` | Administrativo. |
| `/opt/sis-leg/config` | Modo `0751`. |
| `/opt/sis-leg/config/*` (backend) | Sólo lectura para `sis-leg-backend`. |
| `/opt/sis-leg/config/bridge` | Escribible sólo por `sis-leg-bridge`. |
| `/opt/sis-leg/logs` | Escribible sólo por `sis-leg-backend`. |

El modo `0751` de `config/` es deliberado: permite que el bridge lo **atraviese** para llegar a su
propio subdirectorio, pero no que lo enumere ni lea los archivos del backend.

## `logs_backup/`

Directorio presente en el host pero **inerte**: está vacío y no lo referencia ninguna configuración.
No es el destino de `paths.logs_copy_dir` (WP-085), que en esta instalación **no está activado**. Se
lo preserva en cada operación y se verifica explícitamente que ninguna actualización lo toque.

Si en el futuro se quisiera una copia automática de cada conjunto cerrado de registros, el recurso de
red tendría que estar montado por el sistema operativo antes de arrancar el servicio: SIS-Leg no
monta nada, no implementa SMB/NFS y no guarda credenciales.

## Fuera de `/opt/sis-leg`

| Ruta | Qué es |
| --- | --- |
| `/opt/botonera/BOTONERA` | Instalación del sistema Legacy. |
| `/usr/local/bin/sisleg-estado`, `sisleg-activar`, `sisleg-activar-target`, `sisleg-activar-legacy` | Scripts privilegiados de conmutación, `root:root 0755`. |
| `/home/concejo/.local/bin/control-cambiar-sisleg.sh`, `control-cambiar-legacy.sh`, `actualizar-sisleg.sh` | Wrappers de usuario invocados por los lanzadores del escritorio. |
| `/home/concejo/sisleg-switch-history.log` | Historial de conmutaciones. |
| `/home/concejo/sisleg-update-history.log` | Historial de actualizaciones. |
| `/home/concejo/agy-wp029/` | Workspace neutro de la puesta en producción: artefactos descargados, respaldos y reportes de evidencia. |

Los dos historiales registran timestamp, estado previo y posterior, SHA involucrados, run de CI,
artifact, exit codes y rollback. **No registran contraseñas ni secretos.**
