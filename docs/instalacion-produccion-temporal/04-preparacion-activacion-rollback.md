# 04 - Preparación, activación y rollback

La herramienta oficial es **`deploy/herramienta_despliegue.py`**, versionada en este repositorio y
copiada dentro de cada artefacto de CI. Es el único mecanismo autorizado para mutar
`/opt/sis-leg`. Nada en producción hace `git pull`, `pip install` ni copia archivos a mano.

Sus subcomandos son `preflight`, `bootstrap`, `preparar`, `activar`, `rollback` y `estado`.

## De dónde sale una release

Un checkout limpio de un commit con CI verde produce el artefacto:

```bash
pnpm install --frozen-lockfile
uv sync --frozen --all-packages
pnpm empaquetar:produccion
```

Salida: `dist/produccion/sis-leg-<SHA>.tar.gz` y su sidecar `.sha256`. El artifact de CI agrega una
copia de `deploy/herramienta_despliegue.py` **del mismo checkout**, que es lo que permite preparar la
primera release sin Git ni una instalación previa en el host.

El empaquetador rechaza cambios versionables locales, para no atribuir a un commit contenido que Git
no conoce. El job productivo ejecuta el empaquetado dos veces y compara tar y sidecar byte a byte,
así que la reproducibilidad cubre también `pnpm build`, no sólo el tar final.

En este host, los artefactos descargados y verificados se conservan bajo
`/home/concejo/agy-wp029/artifacts/<SHA>/`.

## `preflight`

Diagnostica prerequisitos; **no instala nada**.

```bash
python3.14 deploy/herramienta_despliegue.py preflight
```

Resuelve el mismo Python 3.14 con el que se ejecutó y **rechaza una ruta que dependa de un home
privado del administrador**: si la venv de una release pudiera resolverse contra un Python que vive
en `/root`, el servicio dejaría de arrancar en cuanto cambiara ese home.

## `bootstrap`

Crea usuarios, grupos y directorios, y aplica el plan de permisos descrito en
[02 - Layout en disco](02-layout-en-disco.md).

```bash
# MUTA EL HOST
sudo python3.14 deploy/herramienta_despliegue.py bootstrap --aplicar-usuarios
```

Es idempotente y se ejecuta **dos veces** en una instalación nueva: una antes de provisionar la
configuración institucional y otra después, para que el plan se aplique también a los archivos recién
creados. No instala unidades systemd ni configuración de Nginx.

## `preparar`

Instala una release nueva **sin tocar el sistema activo**.

```bash
# MUTA EL HOST (sólo bajo /opt/sis-leg/releases)
sudo python3.14 deploy/herramienta_despliegue.py preparar \
  sis-leg-<SHA>.tar.gz \
  --checksum sis-leg-<SHA>.tar.gz.sha256 \
  --sha <SHA>
```

Qué hace y qué garantiza:

- verifica el sidecar SHA-256 del paquete;
- extrae de forma segura, validando el manifest y rechazando rutas fuera del destino;
- crea la `.venv` en su ruta final —no en un temporal que después se mueva—, pasando explícitamente
  el Python 3.14 resuelto con `--python` y deshabilitando descargas automáticas, para que la venv no
  pueda elegir por preferencia un Python administrado en el home de root;
- deja la release de sólo lectura;
- escribe el marcador `.sis-leg-preparada.json`.

Lo que **no** hace: no crea `current`, no reinicia servicios, no toca Nginx ni systemd. Preparar es
seguro con el otro sistema en producción; de hecho todas las releases de esta instalación se
prepararon con Legacy activo.

Después de preparar se valida la configuración contra la release nueva, en sólo lectura:

```bash
sudo /opt/sis-leg/releases/<SHA>/.venv/bin/python \
  /opt/sis-leg/releases/<SHA>/deploy/validar_configuracion.py \
  /opt/sis-leg /opt/sis-leg/releases/<SHA>
```

Recibe dos rutas: la raíz de la instalación —donde viven `config/` y `logs/`— y la release. La
segunda es necesaria porque las rutas de la sección `[sonidos]` resuelven contra la Pantalla del
Recinto publicada por esa release. Si un archivo de sonido configurado no está publicado, la
activación falla antes de tocar el servicio.

## `activar`

Es la operación que cambia el sistema en producción.

```bash
# MUTA EL HOST — requiere compuerta humana
sudo python3.14 /opt/sis-leg/releases/<SHA>/deploy/herramienta_despliegue.py activar <SHA>
```

### Validaciones previas al switch

Se ejecutan **todas** antes de tocar nada:

1. **release preparada**: existe, no es symlink, marcador válido y coherente;
2. **configuración**: `validar_configuracion` contra esa release;
3. **permisos de runtime**: con `runuser` se prueba, **con las identidades reales**
   `sis-leg-backend` y `sis-leg-bridge`, la lectura, escritura, ejecución y pertenencia al grupo
   `input` declaradas por el plan. Si un acceso no coincide, falla sin instalar archivos de sistema,
   sin reiniciar servicios y sin cambiar `current`;
4. **guard institucional**: si hay un runtime SIS-Leg vigente, se le consulta el estado y sólo se
   admite `SIN_PREPARAR`. Estar en `PREPARANDO` o `SESION_ABIERTA` rechaza el despliegue;
5. **archivos de sistema**: units systemd y vhost de Nginx de la release.

Si systemd marca el backend `inactive`/`failed`, la herramienta continúa con advertencia porque no
existe un runtime activo al que consultar. Si lo marca `active` pero HTTP no responde o es
inconsistente, **falla cerrado**. No existe `--force`.

### Secuencia del switch

`nginx -t` → cambio atómico de `current` → `daemon-reload` → `restart` del backend → espera de health
→ `restart` del bridge → verificación de servicios y convergencia de Nginx → recién entonces se
actualiza `previous`.

El orden importa: `previous` sólo avanza cuando la release nueva ya demostró estar sana, así que un
fallo nunca deja el rollback apuntando a la release rota.

### Convergencia de Nginx

Tras `systemctl reload nginx.service` la herramienta **no asume** que la configuración nueva ya está
sirviendo. Espera de forma acotada a que el vhost SIS-Leg sea observable de verdad: `/api/v1/health`
vía Nginx con `estado == "ok"` **y** las cinco superficies estáticas devolviendo HTML válido. Sólo se
reintentan errores compatibles con convergencia transitoria; agotado el presupuesto, falla cerrado.

Esto es WP-093, y nace de un fallo real en campo ([08](08-incidentes-y-lecciones.md), incidente A).
No hay `sleep` ciego: la política es *health-gated*.

### Rollback automático dentro de `activar`

Si algo falla:

- **antes** del cambio de `current`: se restauran los archivos de sistema respaldados y se propaga el
  error. El sistema no se movió.
- **después** del cambio de `current`: se restauran `current` y los archivos de sistema anteriores,
  se recarga systemd y se reinician backend y bridge de la release previa, verificando health y
  Nginx. Si no había release previa (primera instalación), se detienen bridge y backend y se recarga
  Nginx.
- si **también** falla la recuperación: la herramienta se detiene y exige intervención humana con un
  mensaje que nombra los dos errores. **Nunca borra la release fallida.**

## `rollback`

```bash
# MUTA EL HOST — requiere compuerta humana
sudo python3.14 /opt/sis-leg/current/deploy/herramienta_despliegue.py rollback
sudo python3.14 /opt/sis-leg/current/deploy/herramienta_despliegue.py rollback --sha <SHA>
```

Sin argumentos activa `previous`; con `--sha` activa una release preparada concreta. Aplica **el
mismo** guard institucional y las mismas verificaciones que una actualización: un rollback no es una
vía rápida para saltarse controles. Un rollback exitoso intercambia `current` y `previous`, lo que
permite roll-forward.

## `estado` y diagnóstico de sólo lectura

```bash
python3.14 /opt/sis-leg/current/deploy/herramienta_despliegue.py estado
readlink -f /opt/sis-leg/current
readlink -f /opt/sis-leg/previous
systemctl status sis-leg-backend.service sis-leg-device-bridge.service
journalctl -u sis-leg-backend.service -u sis-leg-device-bridge.service
nginx -t
curl --fail http://127.0.0.1:8000/api/v1/health
curl --fail http://127.0.0.1/api/v1/health
curl --fail http://127.0.0.1/moderacion/
curl --fail http://127.0.0.1/recinto/
curl --fail http://127.0.0.1/tecnico/
curl --fail http://127.0.0.1/simulador/
curl --fail http://127.0.0.1/manual/
```

Ninguno de estos comandos muta el host.

## Guards institucionales que no dependen de la herramienta

Activar o volver atrás **nunca** modifica `config/` ni `logs/`, no elimina releases y no recupera
estado institucional volátil después de un reinicio. El estado operativo vive en memoria: una
interrupción técnica obliga reglamentariamente a una nueva preparación y una nueva apertura.

Por eso la regla operativa es que **no se despliega deliberadamente durante `PREPARANDO` ni
`SESION_ABIERTA`** (`DT-031`), y por eso los wrappers de conmutación y el actualizador repiten el
guard institucional por su cuenta antes siquiera de invocar a la herramienta: cuando Legacy está
activo, la herramienta de SIS-Leg no tiene a quién preguntarle.
