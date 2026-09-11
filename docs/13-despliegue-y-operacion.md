# 13 - Despliegue y operación

Este documento registra las decisiones técnicas cerradas para el despliegue inicial de SIS-Leg.

Complementa `12-decisiones-tecnicas.md`. Las decisiones todavía abiertas permanecen en `10-preguntas-abiertas.md`.

## DT-027 - Sistema operativo objetivo

La plataforma de producción de referencia será **Linux Mint 22.3 Cinnamon**.

La implementación no debe acoplarse innecesariamente a Linux Mint: backend, frontends, tooling y scripts deben conservar compatibilidad razonable con Linux estándar cuando no exista una necesidad específica del hardware.

Linux Mint se adopta como referencia porque la máquina de producción también opera navegador, pantallas y dispositivos físicos del recinto.

## DT-028 - Servicios nativos con systemd

La primera versión se desplegará de forma nativa mediante **systemd**, sin Docker/Compose.

Servicios principales previstos:

- `sis-leg-backend.service`;
- `sis-leg-device-bridge.service`;
- Nginx como servicio del sistema.

El backend mantiene un único proceso/worker según DT-005.

No introducir contenedores por iniciativa propia. Una futura migración a contenedores requiere decisión técnica explícita, especialmente por la interacción del bridge con hardware físico.

## DT-029 - Frontends Nuxt como SPA estáticas

Los frontends de Moderación y Pantalla del Recinto se construirán como aplicaciones Nuxt client-side/SPA estáticas.

Principios:

- no habrá servidores Node/Nitro permanentes en producción para estos frontends;
- Nginx servirá los archivos HTML/CSS/JS generados;
- Moderación y Recinto consumirán FastAPI mediante REST + SSE;
- no se necesita SSR para el objetivo institucional de SIS-Leg.

La configuración concreta de build debe respetar Nuxt 4 y el funcionamiento bajo subrutas definido en DT-030.

## DT-030 - Nginx y mismo origen

La instalación utilizará **Nginx** como punto de entrada HTTP y un único origen lógico.

Estructura objetivo conceptual:

```text
http://botonera/
├── /moderacion/
├── /recinto/
├── /zocalo/
├── /manual/
└── /api/v1/
```

Desde WP-099 `/zocalo/` es otra superficie pública de solo lectura, publicada con la misma
política que `/recinto/`: mismo origen, sin autenticación y sin restricción a loopback. La
consume el equipo de transmisión como Browser Source.

Nginx:

- sirve ambos frontends estáticos;
- hace proxy de `/api/v1/` hacia FastAPI en loopback;
- configura correctamente los endpoints SSE para entrega inmediata sin buffering indebido;
- evita la necesidad normal de CORS entre frontend y backend al mantenerlos bajo el mismo origen.

Los puertos internos exactos pueden ser configuración de despliegue siempre que no cambien este contrato externo.

## DT-031 - Releases inmutables y rollback

Producción no se actualizará mediante `git pull` sobre el árbol activo.

Estructura objetivo conceptual:

```text
/opt/sis-leg/
├── releases/
│   ├── <release-A>/
│   ├── <release-B>/
│   └── <release-C>/
├── current -> releases/<release-activa>
├── config/
└── logs/
```

Cada release debe ser inmutable y estar identificada de forma trazable, preferentemente por commit o artefacto derivado de un commit conocido.

Procedimiento general:

1. partir de una versión cuya CI esté aprobada;
2. preparar/buildar una nueva release sin alterar `current`;
3. comprobar que el sistema operativo esté en `SIN_PREPARAR` antes de reemplazar la versión activa;
4. cambiar el enlace `current` a la nueva release;
5. reiniciar los servicios necesarios;
6. ejecutar verificaciones de salud;
7. si la nueva versión falla, volver al enlace de la release anterior y reiniciar.

No se despliega ni reinicia deliberadamente SIS-Leg durante `PREPARANDO` o `SESION_ABIERTA`, porque el estado activo es volátil y una interrupción obliga reglamentariamente a comenzar nuevamente.

Configuración y registros viven fuera de `releases/` para que actualización y rollback no los sustituyan ni eliminen.

Una instalación desplegada con la identidad anterior del proyecto se convierte una sola vez siguiendo `docs/MIGRACION-A-SIS-LEG.md`, que preserva esos mismos archivos byte a byte y documenta el rollback.

## DT-032 - Registros conservados solo localmente en la primera versión

En la primera versión **no se implementará backup automático externo** de los CSV institucionales.

Los registros:

- se conservan localmente en el directorio de logs definido por configuración;
- permanecen fuera del árbol de releases;
- no deben eliminarse por despliegues, rollback, builds o limpieza de versiones;
- mantienen la retención indefinida definida funcionalmente salvo intervención administrativa externa.

Una política futura de segunda copia, NAS, nube, cifrado o retención automatizada requerirá una decisión técnica posterior.

Esta decisión no reduce las garantías de escritura inmediata `flush` + `fsync` de DT-012: únicamente define que la primera versión no agrega una segunda copia automática.

## Consecuencias para los agentes

Sin una decisión posterior documentada, los agentes no deben:

- sustituir Linux Mint como plataforma de referencia productiva por otra distribución asumida;
- introducir Docker/Compose;
- desplegar Nuxt mediante servidores Node permanentes;
- separar frontend y API en orígenes públicos diferentes sin necesidad explícita;
- actualizar producción mediante `git pull` sobre la instalación activa;
- colocar configuración o logs dentro de una release inmutable;
- desplegar mientras exista preparación o sesión activa;
- agregar por iniciativa propia servicios de backup remoto o dependencias de nube.

## Runbook productivo versionado

Este procedimiento materializa DT-027 a DT-032. Los comandos que cambian la
máquina institucional requieren gate humano y se ejecutan únicamente cuando
el recinto está fuera de preparación y sesión. El desarrollo, CI y revisión
de WP-028 no ejecutan estos pasos sobre producción.

### Artefacto y trazabilidad

Un checkout limpio del commit aprobado genera:

```bash
pnpm install --frozen-lockfile
uv sync --frozen --all-packages
pnpm empaquetar:produccion
```

La salida es `dist/produccion/sis-leg-<sha-completo>.tar.gz` y su sidecar
`.sha256`. El artifact de CI agrega una copia de
`deploy/herramienta_despliegue.py` del mismo checkout, necesaria para preparar
la primera release sin Git ni una instalación previa. `release.json` identifica
commit/tree, Python objetivo, paquetes, SPA, manual y el inventario SHA-256 de
cada archivo. El empaquetador rechaza cambios versionables locales para no atribuir
al commit contenido que Git no conoce.

La identidad de ambos builds Nuxt se deriva del SHA Git completo y la marca de
prerender del timestamp del mismo commit. Como estas SPA no usan reglas de ruta
en cliente, el app manifest experimental se desactiva para evitar UUID y fechas
volátiles sin quitar funcionalidad. El job productivo ejecuta dos veces
`pnpm empaquetar:produccion` y compara tar y sidecar byte a byte antes del smoke;
por eso la reproducibilidad cubre también `pnpm build`, no sólo el tar final.

### Canal público de releases por SHA (WP-100)

Desde WP-100 cada `push` a `main` cuya **CI completa** termine en `success` publica
automáticamente una GitHub Release pública e inmutable con tag determinista
`sis-leg-<sha-completo>` y tres assets de nombre exacto:

| Asset | Contenido |
| --- | --- |
| `sis-leg-<sha>.tar.gz` | el paquete productivo reproducible |
| `sis-leg-<sha>.tar.gz.sha256` | el sidecar canónico |
| `sis-leg-<sha>.metadatos.json` | el vínculo entre publicación, commit, tree y CI |

La publicación la ejecuta `.github/workflows/publicar-release.yml`, que se dispara con
`workflow_run` al completarse el workflow `CI`. Esperar ese evento es lo que permite exigir
la conclusión de la CI **entera** y no sólo la del job de empaquetado: un job no puede
observar el resultado del workflow que lo contiene. El script versionado
`scripts/publicar_release_publica.py` vuelve a verificar contra la API que la run sea del
evento `push`, de la rama `main`, del SHA exacto, `completed` y `success`, y que el job
`Empaquetado · release productiva` de esa misma run haya sido exitoso.

La publicación es idempotente: si el tag ya existe, compara byte a byte los tres assets
contra los locales y termina sin escribir cuando coinciden. Si difieren o falta alguno,
aborta y exige intervención humana. Una release publicada nunca se reemplaza.

Un push exento por `paths-ignore` (DEC-019) no genera run de CI y por lo tanto tampoco
genera publicación. Esa ausencia es esperada: no hay release productiva nueva porque no
hubo cambio material.

#### Consumo sin credenciales

`deploy/actualizador_publico.py` obtiene esa release **sin ninguna credencial del host**:
no usa `gh`, PAT, `.github_token`, keyring ni variables de entorno con secretos. Sólo
realiza consultas y descargas públicas HTTPS.

```bash
python3.14 /opt/sis-leg/current/deploy/actualizador_publico.py obtener --destino /var/tmp/sis-leg
```

El flujo es rígido y siempre en este orden:

1. resolver el SHA completo de `main` por recurso público;
2. exigir una run de CI de `push` sobre `main` para ese SHA, `completed` y `success`;
3. exigir el job exacto `Empaquetado · release productiva` exitoso y del mismo `head_sha`;
4. resolver la publicación por tag, nunca un asset `latest`;
5. exigir los tres nombres de asset derivados del SHA, sin faltantes ni duplicados;
6. descargar a temporales dentro del destino;
7. verificar el sidecar SHA-256 con la función canónica;
8. validar los metadatos y contrastar su `tree_sha` con el de `release.json`;
9. validar `release.json`, commit, tree e inventario con el motor canónico.

Sólo entonces promueve los tres archivos a su nombre definitivo. La preparación y la
activación siguen siendo responsabilidad de `deploy/herramienta_despliegue.py`: el
actualizador se ocupa de transporte y selección, no de decidir la validez de una release.

Restricciones de transporte: HTTPS únicamente, redirecciones sólo hacia HTTPS y hacia
hosts de GitHub declarados, timeout explícito, tamaño máximo por respuesta y descarga
siempre a temporal. El cliente se construye sin manejo de proxy para hablar directo con
GitHub; si alguna instalación futura necesitara proxy, es una decisión de WP-101 con su
compuerta humana y no un comportamiento implícito. Ante cualquier falla —red, límite de
tasa, JSON inválido, asset ausente, checksum incorrecto, tree incongruente o paquete
truncado— no queda ningún artefacto parcial en el destino.

### Contrato de configuración local (WP-100)

`deploy/contrato_configuracion.json` viaja dentro de cada release, queda inventariado con
checksum en `release.json` y declara qué recursos locales existen, con qué `schema` y si la
release trae para ellos un bootstrap seguro.

`activar` aplica ese contrato **antes** de tocar enlaces, archivos de sistema o servicios:

- un recurso que ya existe se preserva byte a byte y nunca se reescribe;
- un recurso ausente se incorpora sólo si la release declara explícitamente su bootstrap,
  con creación atómica y el modo previsto, y jamás reemplaza uno existente;
- si la release nueva declara para un recurso existente un `schema` distinto del que
  declaraba la release activa, la activación **aborta antes de mutar** e informa que se
  requiere una migración aprobada por HUMAN_GATE.

No hay migraciones automáticas, ni completado de claves, ni restauración de configuración
desde Git, ni sustitución de un archivo por su ejemplo actualizado.

Hoy el contrato declara los cinco recursos institucionales —`config/system.toml`,
`config/concejales.csv`, `config/apoyo-tecnico/mensajes.csv`, `config/bridge/devices.json`
y `config/assets/bancas`— todos sin bootstrap, porque los provisiona el operador. El
mecanismo existe para el caso futuro en que una release necesite un recurso que antes no
existía.

Diagnóstico de solo lectura del plan, sin ejecutar nada:

```bash
python3.14 /opt/sis-leg/current/deploy/herramienta_despliegue.py plan-configuracion <sha>
```

### Prerequisitos administrativos

- Linux Mint 22.3 x86_64 con systemd y Nginx;
- Python 3.14 y `uv` disponibles por rutas estables; cada directorio padre del
  ejecutable Python debe ser atravesable y el binario legible/ejecutable por
  usuarios sin privilegios;
- `runuser` y `find`, utilizados para comprobar accesos con las identidades
  efectivas de backend y bridge antes de activar; `chown` y `chmod`, usados por
  el bootstrap para materializar el plan declarado;
- artefacto correspondiente al SHA aprobado y su sidecar;
- acceso root solamente durante bootstrap/instalación de unidades;
- configuración institucional real preparada fuera del repositorio.

`preflight` diagnostica prerequisitos pero no instala paquetes. También
resuelve el mismo Python 3.14 con que se ejecutó la herramienta y rechaza una
ruta que dependa de un home privado del administrador:

```bash
python3.14 deploy/herramienta_despliegue.py preflight
```

### Primera instalación

1. Descargar un único artifact aprobado de CI y transferir juntos paquete,
   sidecar y `herramienta_despliegue.py` por un canal administrativo. No mezclar
   archivos de ejecuciones o SHA diferentes.
2. Crear usuarios/directorios, sin copiar fixtures del repositorio:

   ```bash
   sudo python3.14 deploy/herramienta_despliegue.py bootstrap --aplicar-usuarios
   ```

3. Provisionar manualmente `system.toml`, `concejales.csv` y
   `bridge/devices.json` bajo `/opt/sis-leg/config/`. `paths.logs_dir` debe
   resolver exactamente a `/opt/sis-leg/logs`. El repositorio publica una
   plantilla por cada archivo (`*.example.*`) que sirve de punto de partida y de
   referencia del formato; el artefacto no las incluye y `scripts/preparar_config_local.py`
   es exclusivamente un bootstrap de desarrollo, sin ningún papel en el despliegue
   productivo (WP-073).

   `paths.logs_copy_dir` es opcional (WP-085). Si la instalación quiere una copia
   automática de cada conjunto cerrado en un recurso de red, ese recurso debe estar
   **montado por el sistema operativo** antes de arrancar el servicio y ser escribible
   por el usuario del backend: SIS-Leg no monta nada, no implementa SMB/NFS y no guarda
   credenciales. Un montaje caído no impide operar ni cerrar sesiones; sólo hace fallar la
   copia, que Moderación informa con un aviso efímero. Si la clave no se declara, el
   backend no intenta ningún acceso externo.
4. Repetir el bootstrap después de provisionar para aplicar idempotentemente el
   plan también a los archivos recién creados:

   ```bash
   sudo python3.14 deploy/herramienta_despliegue.py bootstrap --aplicar-usuarios
   ```

   El plan deja `/opt/sis-leg` atravesable, releases administrativas;
   `logs/` escribible solo por backend; configuración institucional de solo lectura para backend; y
   `config/bridge/` escribible solo por bridge. El modo `0751` del directorio
   padre `config/` es deliberado: permite que bridge lo atraviese para llegar a
   su propio subdirectorio, pero no enumerarlo ni leer los archivos del backend.
   Únicamente bridge integra el grupo `input`.
5. Preparar sin tocar `current`:

   ```bash
   sudo python3.14 deploy/herramienta_despliegue.py preparar \
     sis-leg-<sha>.tar.gz \
     --checksum sis-leg-<sha>.tar.gz.sha256 \
     --sha <sha>
   ```

6. Confirmar que el estado institucional permite la intervención y activar:

   ```bash
   sudo python3.14 /opt/sis-leg/releases/<sha>/deploy/herramienta_despliegue.py \
     activar <sha>
   ```

La activación valida configuración, units y Nginx; cambia `current`
atómicamente; reinicia backend/bridge; comprueba health, las cinco SPA y el
manual por Nginx; y recién entonces actualiza `previous`.

La validación de configuración recibe dos rutas: la raíz de la instalación
—donde viven `config/` y `logs/`— y la release que se está activando. La
segunda es necesaria desde WP-065 porque las rutas de la sección `[sonidos]`
resuelven contra la Pantalla del Recinto publicada por esa release
(`<release>/web/recinto/`). Si un archivo de sonido configurado no está
publicado, la activación falla antes de tocar el servicio. Los assets viajan
dentro de la release, como el resto de la SPA; `config/` no los contiene.

Durante `preparar`, `uv sync` recibe explícitamente la ruta resuelta de ese
Python 3.14 mediante `--python` y deshabilita descargas automáticas. De esta
manera la venv no puede seleccionar por preferencia un Python administrado en
el home privado de root. Antes del switch, `activar` usa `runuser` para probar
con ambos usuarios reales la lectura, escritura, ejecución y pertenencia al
grupo `input` declaradas por el plan. Si un acceso no coincide, falla sin
instalar archivos de sistema, reiniciar servicios ni cambiar `current`.

### Actualización

1. Obtener el artefacto del SHA con CI y revisión aprobadas, preferentemente desde el
   canal público descrito arriba.
2. Ejecutar `preparar`; crea la venv en su ruta final y no reinicia servicios
   ni cambia `current`.
3. Verificar explícitamente que el sistema esté `SIN_PREPARAR`.
4. Ejecutar `activar <sha>` y verificar `estado`, health y ambas SPA.

Si systemd marca backend `inactive`/`failed`, la herramienta permite continuar
con advertencia porque no existe un runtime activo. Si lo marca `active` pero
HTTP no responde o es inconsistente, falla cerrado. No existe `--force`.

### Rollback

El rollback por defecto activa `previous`; también puede señalar una release
preparada concreta:

```bash
sudo python3.14 /opt/sis-leg/current/deploy/herramienta_despliegue.py rollback
sudo python3.14 /opt/sis-leg/current/deploy/herramienta_despliegue.py rollback --sha <sha>
```

Aplica el mismo guard institucional y las mismas verificaciones que una
actualización. Un rollback exitoso intercambia de hecho `current`/`previous`,
permitiendo roll-forward. Si una activación falla después del switch, se
intenta restaurar automáticamente release y archivos de despliegue anteriores.
Si esa recuperación también falla, la herramienta se detiene y exige
intervención; nunca borra la release fallida.

### Navegadores que reproducen sonido y autoplay

Desde WP-066 la Pantalla del Recinto reproduce sonidos ante las transiciones de la sesión.
Desde WP-071 el puesto de Apoyo Técnico reproduce **exactamente los mismos** eventos, para
que la amplificación del salón pueda tomar el audio desde el equipo técnico en lugar de
depender del monitor del recinto. HUMAN_GATE decidió que en ninguna de las dos pantallas
exista un control visible para habilitarlos: ni botón «Activar sonido», ni volumen en
pantalla. La consecuencia operativa es directa y hay que resolverla en cada equipo, no en
la interfaz.

Los navegadores bloquean por defecto la reproducción automática de audio hasta que la
persona interactúa con la página. Frente al monitor del recinto no hay nadie que haga clic:
la pantalla se proyecta y se deja funcionando. En el puesto técnico hay una persona, pero
puede pasar toda la sesión sin tocar la pantalla, así que tampoco puede confiarse en un
gesto previo. Por eso los dos equipos deben estar configurados para permitir autoplay en el
origen donde se sirve SIS-Leg.

Cuál de los dos alimenta la amplificación es una decisión operativa de cada sesión. Si
suenan los dos a la vez y sus salidas llegan al mismo amplificador se oirá un eco, así que
lo habitual será silenciar por sistema operativo el equipo que no se esté usando como
fuente. SIS-Leg no ofrece ni mute ni selector de salida: esa elección se hace en el equipo.

Requisitos de cada puesto que deba sonar:

- el navegador debe permitir reproducción automática de audio para el origen de SIS-Leg;
- la salida de audio del sistema operativo debe estar activa, sin silenciar y con volumen
  audible en el destino que corresponda;
- el volumen relativo de cada evento se ajusta en `config/system.toml` (`[sonidos]`), nunca
  desde la interfaz, y es el mismo para las dos pantallas.

Mecanismos habituales, a confirmar contra la versión instalada del navegador:

- **Chromium/Chrome**, en el lanzador del modo kiosco:

  ```bash
  chromium --kiosk --autoplay-policy=no-user-gesture-required http://<host>/recinto/
  chromium --autoplay-policy=no-user-gesture-required http://<host>/tecnico/
  ```

  Es la misma bandera que usan los dos E2E versionados del proyecto
  (`playwright.config.ts` y `playwright.integrado.config.ts`), de modo que las pruebas
  automatizadas exigen exactamente la condición que necesita producción. El puesto técnico
  no se abre en modo kiosco porque es una pantalla que se opera.

- **Chromium/Chrome administrado por políticas**: habilitar el sonido para el origen de
  SIS-Leg mediante la política de autoplay/allowlist correspondiente a la versión instalada,
  o dar permiso de sonido al sitio desde la configuración del navegador.

- **Firefox**: `media.autoplay.default = 0` en el perfil del puesto.

Verificación después de instalar o actualizar: abrir la pantalla que vaya a alimentar la
amplificación —el Recinto, Apoyo Técnico o las dos—, provocar un hecho audible desde
Moderación o desde el propio puesto técnico —por ejemplo alternar la presencia de una
banca— y confirmar que el sonido se escucha sin haber tocado esa pantalla. Si no se
escucha, el problema es de configuración del puesto: la aplicación no ofrece ninguna
alternativa manual y no debe agregarse una sin decisión humana documentada.

Los archivos WAV viajan dentro de la release y `activar` ya falla si alguna ruta configurada
no está publicada, así que un sonido mudo por archivo faltante no puede llegar a producción
sin detectarse. La validación sigue comprobando la raíz pública del Recinto, que es donde
los archivos están versionados; Apoyo Técnico publica esos mismos archivos bajo su propio
prefijo en tiempo de construcción, sin una segunda copia que pudiera quedar atrasada.

### Manual de usuario publicado con la release

Desde WP-067 la release incluye `web/manual/index.html`, un único documento HTML
autocontenido con el manual de operación, configuración e instalación de SIS-Leg. Nginx lo
publica en `/manual/` bajo el mismo origen que las aplicaciones y sin restricción de red,
porque es el destino del icono de ayuda que muestran las cabeceras de Moderación y de
Apoyo Técnico.

Consecuencias operativas:

- el manual se actualiza con la release, igual que las SPA: no se edita en la máquina
  institucional ni vive en `config/`;
- `activar` falla si el manual no está publicado, del mismo modo que ya falla si falta una
  SPA, de manera que el icono de ayuda no puede quedar apuntando a un 404;
- el documento no carga recursos externos, así que se lee completo en una instalación sin
  salida a Internet.

### Diagnóstico de solo lectura

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
curl --fail http://127.0.0.1/zocalo/
curl --fail http://127.0.0.1/manual/
```

Activar o volver atrás nunca modifica `config/` ni `logs/`, no elimina
releases y no recupera estado institucional volátil después de un reinicio.
