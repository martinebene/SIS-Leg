# 01 - Topología actual del host institucional

Estado descrito: transición Legacy → SIS-Leg, con **ambos sistemas instalados** en la misma máquina y
alternables manualmente. Es una situación deliberadamente temporal.

## Host

- Linux Mint 22.3 Cinnamon, x86_64, con systemd y Nginx nativos (`DT-027`, `DT-028`).
- Es la misma máquina que opera el navegador, las pantallas y los dispositivos físicos del recinto.
- Usuario operador del escritorio: `concejo`. Su `$HOME` tiene permisos restrictivos; ese detalle
  provocó un defecto real, descrito en [08 - Incidentes y lecciones](08-incidentes-y-lecciones.md).
- Python 3.14 global en `/usr/local/bin/python3.14`, instalado con `uv python install 3.14` y
  `UV_PYTHON_INSTALL_DIR=/opt/python`, `UV_PYTHON_BIN_DIR=/usr/local/bin`. Cada directorio padre del
  binario real debe ser atravesable y el ejecutable legible por usuarios sin privilegios, porque las
  identidades de runtime lo usan.
- `uv` global en `/usr/local/bin`, instalado con el instalador oficial de Astral (no por `apt`).

## Nginx

Nginx es el único punto de entrada HTTP en el puerto 80 y define **qué sistema ve el usuario**. Los
dos sistemas usan mecanismos de configuración distintos y mutuamente excluyentes:

| Sistema | Configuración | Presente cuando |
| --- | --- | --- |
| Legacy | symlink `/etc/nginx/sites-enabled/botonera` → `/etc/nginx/sites-available/botonera` | Legacy está activo |
| SIS-Leg | `/etc/nginx/conf.d/sis-leg.conf` | SIS-Leg está activo |

Cuando SIS-Leg no está activo, su vhost queda como `/etc/nginx/conf.d/sis-leg.conf.disabled`, fuera
del glob `*.conf` que Nginx incluye. **Nunca se crea `sites-enabled/sis-leg.conf`**: mezclar los dos
mecanismos haría ambiguo cuál vhost gana.

La conmutación retira un vhost y publica el otro, y después ejecuta `nginx -t` + `systemctl reload
nginx.service`. El reload de Nginx es *graceful*: los workers viejos siguen atendiendo conexiones
existentes mientras los nuevos toman la configuración nueva. Esa ventana de convergencia causó el
primer fallo real de conmutación (ver [08](08-incidentes-y-lecciones.md), incidente A).

### Superficies publicadas por SIS-Leg

Bajo el mismo origen (`DT-030`), sin CORS entre frontend y API:

```text
http://127.0.0.1/
├── /moderacion/
├── /recinto/
├── /tecnico/
├── /simulador/
├── /manual/
└── /api/v1/      → proxy a FastAPI en loopback
```

Las cinco superficies estáticas son SPA Nuxt precompiladas que viajan dentro de la release
(`DT-029`). Una activación falla si alguna de ellas o el manual no responde correctamente a través
de Nginx.

## Servicios systemd

### Legacy

| Unidad | Rol |
| --- | --- |
| `botonera-backend.service` | Backend Legacy. Escucha en `:8000`. |
| `botonera-teclados.service` | Bridge de hardware Legacy: captura los numpads. |

Instalación Legacy en disco: `/opt/botonera/BOTONERA`. El backend Legacy expone
`GET /estados/estado_global`, con el campo `hay_sesion`, que se usa como guard institucional antes de
cualquier conmutación o actualización mientras Legacy está activo.

### SIS-Leg

| Unidad | Rol |
| --- | --- |
| `sis-leg-backend.service` | FastAPI, un único proceso/worker (`DT-005`). Escucha en `:8000`. |
| `sis-leg-device-bridge.service` | Device bridge: captura/remapeo físico. Escucha en `:8765`. |

Identidades de runtime, creadas por el bootstrap de la herramienta oficial:

- `sis-leg-backend`: lee la configuración institucional, escribe en `logs/`;
- `sis-leg-bridge`: único usuario que integra el grupo `input`, escribe sólo en `config/bridge/`.

El guard institucional equivalente del lado SIS-Leg es
`GET http://127.0.0.1:8000/api/v1/estado/moderacion`, del que se exigen `estado_global` y `sesion`.

Las unidades **no** declaran `Conflicts=`. La exclusión mutua no depende de systemd sino de la
secuencia *disable-first* implementada por los scripts de conmutación
([05](05-conmutacion-legacy-sis-leg.md)). Esa decisión es deliberada: `Conflicts=` habría permitido
que systemd detuviera un servicio por su cuenta, sin las verificaciones de salud ni el rollback que
la conmutación necesita.

## Puertos

| Puerto | Ocupante | Nota |
| --- | --- | --- |
| `80` | Nginx | Único puerto expuesto al usuario. |
| `8000` | backend Legacy **o** backend SIS-Leg | Nunca los dos: el puerto compartido es un mecanismo natural de exclusión. |
| `8765` | `sis-leg-device-bridge` | Sólo cuando SIS-Leg está activo. |

## Regla de exclusión de bridges

**Nunca pueden estar activos simultáneamente `botonera-teclados.service` y
`sis-leg-device-bridge.service`.**

Es la invariante más rígida de toda la instalación. Los dos bridges toman los mismos dispositivos
físicos con `EVIOCGRAB`; si convivieran, las pulsaciones quedarían capturadas por un proceso
impredecible, con doble captura o teclados cruzados, y el registro institucional dejaría de ser
confiable.

Consecuencias prácticas:

- ningún lanzador ni wrapper puede hacer `systemctl start/stop` directo de un bridge;
- toda conmutación deshabilita el sistema saliente **antes** de detenerlo (*disable-first*), para que
  un reinicio no lo devuelva a la vida;
- el bridge entrante se arranca **después** de que el backend entrante respondió health;
- toda evidencia de campo verifica explícitamente que hay **exactamente un** bridge activo.

La instalación captura 12 numpads mapeados (`dev01`..`dev12`), más receptores de reserva sin mapear.

## Clasificación formal del estado

`/usr/local/bin/sisleg-estado` es de sólo lectura y clasifica el host en uno de cuatro estados:

| Estado | Significado |
| --- | --- |
| `ESTABLE_LEGACY` | Legacy backend+bridge activos y habilitados, SIS-Leg inactivo, vhost Legacy publicado. |
| `ESTABLE_SISLEG` | SIS-Leg backend+bridge activos y habilitados, Legacy inactivo, vhost SIS-Leg publicado. |
| `INERTE_SEGURO` | Ningún sistema activo, sin bridges tomando hardware. No es un estado operativo. |
| `ESTADO_INCONSISTENTE` | Cualquier mezcla no reconocida. **Ninguna operación mutante puede partir de acá.** |

`sisleg-estado --tag` devuelve sólo la etiqueta, y es la forma en que los wrappers deciden si pueden
actuar. Los estados se derivan de evidencia real: `is-active`/`is-enabled` de las cuatro unidades y
de Nginx, propietario de los listeners `:8000`, `:80` y `:8765`, destino de `/opt/sis-leg/current`,
presencia de cada vhost y health del sistema que corresponda.
