# Migración de una instalación existente a la identidad SIS-Leg

## Qué cambia y qué no

WP-077 renombró la identidad técnica del sistema. Una instalación que hoy corre bajo los nombres
anteriores sigue funcionando, pero no puede recibir una release nueva: los artefactos generados a
partir de este commit declaran `sis-leg-release` como formato, instalan usuarios `sis-leg-*` y
esperan la raíz `/opt/sis-leg`. La equivalencia completa entre nombres viejos y nuevos está en
`docs/NOTA-LEGADO-BOTONERA2.md`.

**Ningún dato operativo cambia.** Se conservan sin modificación:

- `config/system.toml`;
- `config/concejales.csv`;
- `config/apoyo-tecnico/mensajes.csv`;
- `config/bridge/devices.json`;
- todo el contenido de `logs/`.

Los cuatro archivos de configuración usan rutas relativas (`logs_dir = "logs"`) y referencias
lógicas, no rutas absolutas, así que se mueven **byte a byte** y no hay que editarlos. Si en una
instalación concreta alguno contuviera una ruta absoluta bajo la raíz anterior, hay que corregir
esa línea y sólo esa, dejando constancia.

## Precondiciones

1. El sistema está en `SIN_PREPARAR`. Nunca se migra durante `PREPARANDO` ni `SESION_ABIERTA`:
   el estado es volátil y una interrupción obliga reglamentariamente a preparar y abrir de nuevo.
2. Hay una release nueva ya construida a partir de un commit con CI aprobada, con su archivo de
   checksum.
3. Se dispone de acceso `sudo` en el servidor y de una ventana sin actividad institucional.
4. Hay espacio en disco para una copia completa de la raíz anterior.

## Procedimiento

### 1. Registrar el estado de partida

```bash
readlink -f /opt/botonera2/current
systemctl is-active botonera2-backend.service botonera2-device-bridge.service
sha256sum /opt/botonera2/config/system.toml \
          /opt/botonera2/config/concejales.csv \
          /opt/botonera2/config/apoyo-tecnico/mensajes.csv \
          /opt/botonera2/config/bridge/devices.json
```

Los cuatro checksums son la prueba de preservación: se vuelven a calcular al final y deben
coincidir exactamente.

### 2. Respaldo completo

```bash
sudo systemctl stop botonera2-device-bridge.service
sudo systemctl stop botonera2-backend.service
sudo tar --numeric-owner -czf /var/backups/botonera2-previo-migracion.tar.gz -C /opt botonera2
```

El bridge se detiene primero porque depende del backend; detenerlo después dejaría pulsaciones sin
destino. El respaldo se hace con los servicios ya detenidos para que no haya escritura de auditoría
en curso.

### 3. Mover la raíz de despliegue

```bash
sudo mv /opt/botonera2 /opt/sis-leg
```

`mv` dentro del mismo sistema de archivos preserva contenido, permisos y marcas de tiempo, y no
reescribe ningún archivo. El enlace `current` es relativo a `releases/`, así que sigue siendo
válido después del movimiento.

### 4. Renombrar usuarios y grupos de servicio

```bash
sudo systemctl stop botonera2-backend.service botonera2-device-bridge.service
sudo usermod  --login sis-leg-backend --home /opt/sis-leg botonera2-backend
sudo groupmod --new-name sis-leg-backend botonera2-backend
sudo usermod  --login sis-leg-bridge  --home /opt/sis-leg botonera2-bridge
sudo groupmod --new-name sis-leg-bridge  botonera2-bridge
```

Renombrar conserva el UID y el GID, de modo que la propiedad de los archivos ya movidos sigue
siendo correcta sin recorrer el árbol. `sis-leg-bridge` debe seguir perteneciendo al grupo `input`;
`usermod --login` no lo quita, pero conviene confirmarlo:

```bash
id --groups --name sis-leg-bridge
```

### 5. Instalar la release nueva

```bash
sudo python3.14 /opt/sis-leg/current/deploy/herramienta_despliegue.py preflight
sudo python3.14 deploy/herramienta_despliegue.py preparar \
  sis-leg-<sha>.tar.gz \
  --checksum sis-leg-<sha>.tar.gz.sha256 \
  --sha <sha>
sudo python3.14 deploy/herramienta_despliegue.py bootstrap --aplicar-usuarios
```

`bootstrap` reaplica propietarios y permisos con los nombres nuevos sobre `config/`, `logs/` y sus
archivos. No crea ni sobrescribe configuración: si un archivo de configuración falta, el paso falla
en lugar de inventarlo.

### 6. Reemplazar las unidades systemd y el sitio Nginx

```bash
sudo systemctl disable --now botonera2-backend.service botonera2-device-bridge.service
sudo rm /etc/systemd/system/botonera2-backend.service \
        /etc/systemd/system/botonera2-device-bridge.service
sudo rm /etc/nginx/conf.d/botonera2.conf
sudo python3.14 /opt/sis-leg/current/deploy/herramienta_despliegue.py activar <sha>
```

`activar` instala `sis-leg-backend.service`, `sis-leg-device-bridge.service` y `sis-leg.conf`,
ejecuta `daemon-reload`, valida la configuración de Nginx y arranca los servicios en orden. Las
unidades anteriores se eliminan **antes** para que no queden dos definiciones compitiendo por los
mismos puertos y dispositivos.

### 7. Variables de entorno

Si la instalación define variables propias en un `drop-in` de systemd o en el entorno del servicio,
hay que renombrar el prefijo: `BOTONERA2_DEVICES_CONFIG` pasa a `SIS_LEG_DEVICES_CONFIG`,
`BOTONERA2_BACKEND_URL` a `SIS_LEG_BACKEND_URL`, y así con el resto. Las unidades versionadas del
proyecto pasan esos valores como argumentos de línea de comandos y no dependen del entorno, de modo
que una instalación estándar no tiene nada que renombrar acá.

### 8. Verificación

```bash
python3.14 /opt/sis-leg/current/deploy/herramienta_despliegue.py estado
readlink -f /opt/sis-leg/current
systemctl status sis-leg-backend.service sis-leg-device-bridge.service
nginx -t
curl --fail http://127.0.0.1/api/v1/health
curl --fail http://127.0.0.1/moderacion/
curl --fail http://127.0.0.1/recinto/
curl --fail http://127.0.0.1/tecnico/
curl --fail http://127.0.0.1/manual/
sha256sum /opt/sis-leg/config/system.toml \
          /opt/sis-leg/config/concejales.csv \
          /opt/sis-leg/config/apoyo-tecnico/mensajes.csv \
          /opt/sis-leg/config/bridge/devices.json
```

Los cuatro checksums deben ser idénticos a los del paso 1. Después conviene una prueba funcional
mínima con hardware real: preparar el recinto, marcar presencia desde una botonera, comprobar que
la Pantalla del Recinto reacciona y cancelar la preparación.

## Rollback

Mientras no se haya reactivado la operación institucional, el camino de vuelta es simétrico:

```bash
sudo systemctl disable --now sis-leg-device-bridge.service sis-leg-backend.service
sudo rm /etc/systemd/system/sis-leg-backend.service \
        /etc/systemd/system/sis-leg-device-bridge.service
sudo rm /etc/nginx/conf.d/sis-leg.conf
sudo rm -rf /opt/sis-leg
sudo tar --numeric-owner -xzf /var/backups/botonera2-previo-migracion.tar.gz -C /opt
sudo usermod  --login botonera2-backend --home /opt/botonera2 sis-leg-backend
sudo groupmod --new-name botonera2-backend sis-leg-backend
sudo usermod  --login botonera2-bridge  --home /opt/botonera2 sis-leg-bridge
sudo groupmod --new-name botonera2-bridge  sis-leg-bridge
sudo cp /opt/botonera2/current/deploy/systemd/*.service /etc/systemd/system/
sudo cp /opt/botonera2/current/deploy/nginx/botonera2.conf /etc/nginx/conf.d/
sudo systemctl daemon-reload
sudo nginx -t && sudo systemctl reload nginx
sudo systemctl enable --now botonera2-backend.service botonera2-device-bridge.service
```

El respaldo del paso 2 es la garantía real del rollback. Sólo se borra después de que el sistema
haya operado una sesión completa con la identidad nueva.

## Qué no hace esta migración

- No toca los registros de auditoría ya escritos: se mueven con la raíz y no se reescriben.
- No cambia rutas HTTP. `/moderacion/`, `/recinto/`, `/tecnico/`, `/simulador/`, `/manual/` y
  `/api/v1/` son idénticas antes y después.
- No cambia el nombre de red del servidor. El `server_name` del sitio Nginx sigue siendo el que la
  institución tenga configurado y los marcadores de los puestos siguen funcionando.
- No renombra el repositorio Git de nadie: eso es una operación aparte, descrita en el WP y
  reservada a HUMAN_GATE.
