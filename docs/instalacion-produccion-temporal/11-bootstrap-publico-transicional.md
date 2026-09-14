# 11 - Bootstrap público transicional desde releases anteriores a WP-101A

Este documento describe `deploy/bootstrap_publico.py` (WP-105) y el procedimiento previsto para
usarlo **una sola vez** en WP-101B. Integrar WP-105 **no autoriza** ejecutarlo en el host: cada paso
que escribe en la máquina institucional requiere su propia compuerta humana.

## 1. Por qué hace falta

La release activa del host (`a702d71da8c0f2d66b8ccb0231543d15bcdb1e48` al momento de redactar este
documento; hay que volver a medirlo) es anterior al mecanismo versionado:

- no trae `deploy/actualizador_publico.py`, `deploy/instalador_host.py` ni `deploy/operaciones_host.py`;
- su `deploy/herramienta_despliegue.py` sí tiene `preparar`, pero valida `release.json` contra un
  contrato de **cuatro** SPA y rechaza cualquier release moderna, que declara **cinco** (incluye
  Zócalo).

La herramienta residente, entonces, no puede preparar la release que la reemplazaría. Relajarla o
editarla en producción no es aceptable. El bootstrap es el puente mínimo para cruzar ese salto.

## 2. Qué hace y qué no

`bootstrap_publico.py` es un archivo suelto que usa sólo biblioteca estándar de Python 3.14. No
importa nada de la release activa ni del repositorio, y no usa `git`, `gh`, PAT, tokens ni cookies.

Tiene exactamente dos subcomandos:

| Subcomando | Escribe bajo `/opt/sis-leg` | Qué hace |
| --- | --- | --- |
| `diagnosticar` | **no** | Verifica la release pública completa en un temporal privado, verifica los módulos que delegaría sin ejecutarlos y clasifica el estado de `releases/<SHA>`. Informa `listo_para_preparar`. |
| `preparar` | sólo lo que escribe `herramienta_despliegue.py preparar` en `releases/<SHA>` | Repite toda la verificación y, si `releases/<SHA>` no existe, ejecuta la herramienta moderna **de la propia release objetivo** con el subcomando `preparar`. |

Ambos exigen identidades exactas: `--sha` (commit de 40 caracteres) y `--tree-sha` (árbol Git de ese
commit). `--paquete-sha256` fija además el hash del paquete. Cualquier desacuerdo falla cerrado.

### Orden de verificación

Ningún byte del paquete se ejecuta antes de completar, en este orden:

1. publicación `sis-leg-<SHA>`: tag exacto, no borrador ni prerelease, `target_commitish` igual al SHA
   o a `main`, y **exactamente** los tres assets canónicos, todos subidos y con URL HTTPS de GitHub;
2. commit y árbol contra la API Git pública: el tree SHA pedido tiene que ser el del commit;
3. metadatos de publicación: formato, repositorio, commit, tag, árbol y bloque de CI;
4. intento **histórico exacto** de CI declarado por los metadatos (`push` a `main`, workflow `CI`,
   `success`) y su único job `Empaquetado · release productiva`;
5. descarga de paquete y sidecar al temporal privado; el SHA-256 calculado tiene que coincidir con el
   sidecar, con los metadatos y, si se pidió, con `--paquete-sha256`;
6. recorrido completo del tar sin extraerlo: sólo archivos regulares (se rechazan enlaces simbólicos,
   hardlinks, directorios, dispositivos y FIFOs), rutas relativas normalizadas dentro de
   `app/`, `web/`, `deploy/` o `release.json`, sin duplicados, `release.json` con el contrato
   **moderno** de cinco SPA más manual, coincidencia exacta entre entradas e inventario y tamaño y
   SHA-256 de **cada** archivo.

Recién entonces se escriben en el temporal `deploy/__init__.py`, `deploy/configuracion_local.py` y
`deploy/herramienta_despliegue.py` —lo mínimo que necesita `preparar`—, se vuelven a comprobar sus
bytes contra el inventario y se ejecuta:

```text
python3.14 -I -B <temporal>/herramienta/deploy/herramienta_despliegue.py \
  --raiz /opt/sis-leg preparar <temporal>/sis-leg-<SHA>.tar.gz \
  --checksum <temporal>/sis-leg-<SHA>.tar.gz.sha256 --sha <SHA>
```

`-I` aísla el intérprete (ignora `PYTHONPATH` y el site del usuario) para que la herramienta importe su
propio `configuracion_local.py` y nunca uno residente.

### Efectos garantizados

- no modifica `current`, `previous` ni `target-release`;
- no instala ni cambia unidades systemd, Nginx, `/usr/local/bin`, wrappers de
  `/home/concejo/.local/bin`, sudoers, PolicyKit, `.desktop`, Legacy, configuración institucional ni
  logs;
- no reinicia servicios;
- el temporal se crea con modo `0700`, fuera de `/opt/sis-leg`, y se borra siempre, también ante
  fallas.

### Idempotencia y fallas

| Situación en `releases/<SHA>` | Resultado |
| --- | --- |
| no existe | se delega `preparar` |
| existe con marcador y `release.json` del mismo commit y árbol | `IDEMPOTENTE`: no se ejecuta nada ni se reescribe |
| existe sin marcador (`PARCIAL`) | aborta **antes de consultar la red**; no borra ni repara |
| marcador o manifest de otro commit/árbol, enlace o archivo (`INCOMPATIBLE`) | aborta; no borra ni repara |

Si la herramienta moderna falla durante `preparar`, el bootstrap reproduce su salida y su error, sale
con código 1 y deja el directorio parcial que ella haya conservado, exactamente con la semántica de
esa herramienta. No hay limpieza destructiva automática.

## 3. Procedimiento previsto para WP-101B

Cada paso es un turno separado. El hash exacto del bootstrap, el SHA de la release y su tree SHA **se
fijan en la asignación productiva**, después del merge de WP-105 y de la publicación pública de la
release que lo contiene; no se deducen de este documento.

1. **Obtener el bootstrap desde una URL inmutable del commit aprobado**, sin credenciales, a un
   directorio privado:

   ```text
   DIR=$(mktemp -d)
   curl --proto '=https' --tlsv1.2 -fsSL \
     -o "$DIR/bootstrap_publico.py" \
     https://raw.githubusercontent.com/martinebene/SIS-Leg/<SHA_APROBADO>/deploy/bootstrap_publico.py
   ```

2. **Verificar su SHA-256 exacto antes de ejecutarlo.** Si no coincide, detenerse:

   ```text
   echo "<SHA256_APROBADO>  $DIR/bootstrap_publico.py" | sha256sum -c -
   ```

3. **Ejecutar primero el diagnóstico**, que no escribe bajo `/opt/sis-leg`, y revisar el informe
   completo (`listo_para_preparar`, `estado_destino`, `uv`, identidad de CI):

   ```text
   python3.14 -I "$DIR/bootstrap_publico.py" diagnosticar \
     --sha <SHA_RELEASE> --tree-sha <TREE_SHA_RELEASE> --paquete-sha256 <SHA256_PAQUETE>
   ```

4. **Sólo con un HUMAN_GATE productivo separado**, preparar la release moderna:

   ```text
   sudo python3.14 -I "$DIR/bootstrap_publico.py" preparar \
     --sha <SHA_RELEASE> --tree-sha <TREE_SHA_RELEASE> --paquete-sha256 <SHA256_PAQUETE>
   ```

5. **Detenerse después de preparar.** Verificar `resultado` (`PREPARADA` o `IDEMPOTENTE`) y que
   `current` y `target-release` siguen iguales.
6. **En otro gate**, ejecutar el plan del instalador desde la release moderna ya preparada, que no
   escribe nada:

   ```text
   sudo python3.14 /opt/sis-leg/releases/<SHA_RELEASE>/deploy/instalador_host.py \
     --release /opt/sis-leg/releases/<SHA_RELEASE> plan
   ```

7. **No** instalar wrappers, corregir privilegios o el helper Legacy, ni conmutar en el mismo turno del
   bootstrap. Cada una de esas acciones es una decisión posterior con su propia autorización.

## 4. Carácter transicional

Una vez preparada una release moderna, las operaciones normales usan exclusivamente
`actualizador_publico.py`, `herramienta_despliegue.py`, `instalador_host.py` y `operaciones_host.py`.
El bootstrap no reemplaza al actualizador normal, no se instala en el host y no debe incorporarse a
ningún wrapper.

El bootstrap repite de forma deliberada una parte del contrato del canal público y del manifest
moderno, porque no puede importarlos desde un host con release histórica. Las pruebas
`tests/test_bootstrap_publico.py` comparan esas copias contra `actualizador_publico.py`,
`herramienta_despliegue.py`, el empaquetador y el publicador: si divergen, la CI falla.
