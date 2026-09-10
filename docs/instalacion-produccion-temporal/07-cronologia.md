# 07 - Cronología de la puesta en producción

Hitos verificados de la instalación productiva, en orden. Cada uno corresponde a una fase de WP-029
registrada en `martinebene/SIS-Leg-Control` bajo `work-packages/WP-029/`.

La regla que atraviesa toda la secuencia: **cada paso mutante requirió una autorización explícita,
se ejecutó una sola vez y no se reintentó ante falla.**

## Releases involucradas

| Apodo | SHA completo |
| --- | --- |
| `50abb` | `50abb3832317afefac2175ac51a12acb8d7d583d` |
| `BFBB` | `bfbb63612f19080264585783cae998fc545b619d` |
| `A702` | `a702d71da8c0f2d66b8ccb0231543d15bcdb1e48` |

## 1. Preparación paralela con Legacy activo (fases 1-2)

Con Legacy en producción y sin tocarlo:

- `uv` y Python 3.14 globales instalados en rutas estables;
- artifact de `50abb` descargado y verificado (ZIP, tar y herramienta, los tres por SHA-256);
- `preflight` verde;
- `bootstrap --aplicar-usuarios`: usuarios, grupos y directorios de `/opt/sis-leg`;
- configuración institucional real provisionada bajo `/opt/sis-leg/config/` —12 bancas, mapeo de los
  12 numpads, 2 receptores de reserva sin mapear, catálogo de sonidos—, y segundo `bootstrap` para
  aplicarle el plan de permisos;
- release `50abb` **preparada sin activar**;
- verificación de no impacto: Legacy siguió activo, `:8000` siguió siendo suyo, `current` y
  `previous` ausentes, unidades y vhost de SIS-Leg **no** instalados.

Se decidió que las unidades SIS-Leg **no** llevaran `Conflicts=`: la exclusión mutua la haría el
wrapper con *disable-first*.

## 2. Scripts de conmutación auditados e instalados (fases 3A-3B)

Los tres scripts (`sisleg-estado`, `sisleg-activar`, `sisleg-activar-legacy`) se escribieron en un
workspace neutro, se revisaron en **tres pasadas** de corrección antes de aprobarse, y sólo entonces
se instalaron en `/usr/local/bin` verificando SHA-256 exacto en origen y destino.

Durante la instalación no se conmutó nada: se ejecutaron únicamente `sisleg-estado` y los prechecks
de sólo lectura. Antes se respaldó el vhost Legacy byte a byte.

## 3. Primer switch real y su falla (fase 4)

Primera conmutación reversible Legacy → SIS-Leg con `50abb`, bajo compuerta humana.

Lo que funcionó: precondiciones verdes, `hay_sesion == false`, backend SIS-Leg con health 200, Device
Bridge activo con `EVIOCGRAB` exitoso sobre los 12 numpads, health `/api/v1/health` vía Nginx.

Lo que falló: `GET /moderacion/` devolvió **404** inmediatamente después del reload de Nginx. El
rollback externo completó y clasificó `ESTABLE_LEGACY`, sin reintentos ni reparación manual.

Causa: la herramienta asumía convergencia sincrónica del reload de Nginx. → **WP-093**.

## 4. Preparación de BFBB y retarget de scripts (fases 5A-5C)

Con WP-093 integrado en `main`:

- artifact de `BFBB` verificado y release preparada, otra vez sin activar;
- los scripts de conmutación se re-apuntaron a `BFBB` y se reinstalaron con verificación de hashes;
- la configuración local permaneció congelada durante toda la operación.

## 5. Segundo switch: primer `ESTABLE_SISLEG` real (fase 5D)

Una sola ejecución de `sisleg-activar <BFBB>`, con compuerta humana confirmada. Resultado:

- `ESTABLE_SISLEG`;
- SIS-Leg backend y bridge activos y habilitados, Legacy inactivo y deshabilitado;
- exactamente **un** bridge activo; `:8765` del bridge SIS-Leg;
- vhost SIS-Leg publicado, vhost Legacy retirado;
- `current` → `BFBB`, marcador válido;
- health local y vía proxy correctos;
- las cinco superficies respondiendo.

El host quedó deliberadamente en SIS-Leg para validación humana de campo.

## 6. Validación humana de campo (fase 5E)

Verificación física: interfaces correctas, los 12 numpads respondiendo, cada uno asociado a su banca,
sin doble captura ni teclados cruzados, y un flujo funcional controlado de preparación y votos de
prueba.

**Esta validación sigue abierta.** Sólo puede cerrarla una decisión humana explícita.

## 7. Período dual de lanzadores (fase 5F)

A pedido humano se mantuvieron ambos sistemas disponibles con alternancia manual segura: lanzadores
de pantallas para las dos familias, en modo aplicación y pantalla completa, más dos controles
clickeables «Cambiar a SIS-Leg» y «Cambiar a Legacy», con confirmación visible e historial en
`/home/concejo/sisleg-switch-history.log`.

Los controles reutilizan **exclusivamente** los scripts auditados. Quedó prohibido cualquier esquema
que hiciera `systemctl start` directo o permitiera coexistencia de bridges.

Esta decisión **no** implicó cutover.

## 8. Una sola instalación lógica y updater dinámico (fases 5G-5H)

Clarificación humana: debe existir **una sola instalación lógica** de SIS-Leg, actualizable a la
última release válida de `main`, con lanzadores permanentes independientes de versión y ningún
wrapper atado a `BFBB`. Las releases históricas quedan sólo como mecanismo de rollback.

De ahí salieron `/opt/sis-leg/target-release`, la variante `sisleg-activar-target` y el actualizador
`actualizar-sisleg.sh`.

## 9. Auditoría de sólo lectura 5I

Auditoría completa —scripts privilegiados, wrappers, lanzadores, `target-release`, lógica crítica
citada línea por línea— con resultado **1 BLOQUEANTE y 4 IMPORTANTES**, detallados en
[08 - Incidentes y lecciones](08-incidentes-y-lecciones.md).

Evidencia favorable que se mantuvo pese a los defectos: la prueba real Legacy → SIS-Leg → Legacy
había sido exitosa, con un solo bridge, 12 numpads capturados, configuración idéntica antes y
después, `target-release` dinámico y sin `BFBB` en wrappers operativos.

## 10. Correcciones 5J y smoke bloqueado por sesión activa

Las cinco correcciones se implementaron y se revisaron con **0 BLOQUEANTES / 0 IMPORTANTES / 0
MENORES**.

La prueba de alternancia autorizada **no se ejecutó**: el sistema detectó una sesión parlamentaria
real en `SESION_ABIERTA`. Eso se clasificó como **comportamiento correcto del guard institucional**,
no como falla, y no se autorizó interrumpir la sesión para completar el smoke.

## 11. Smoke post-sesión y segundo defecto de producto (fase 5K)

El gate original suponía que el host arrancaría en `ESTABLE_LEGACY`; el precheck real mostró
`ESTABLE_SISLEG`, y la asignación se reemitió con la secuencia invertida. También se aclaró que un
404 de `/estados/estado_global` con SIS-Leg activo **no es una falla**: ese endpoint es del backend
Legacy, que debe estar inactivo.

Resultado: la ida SIS-Leg → Legacy fue exitosa. La vuelta Legacy → SIS-Leg falló al validar permisos
de sólo lectura de la release:

```text
find: fallo al restaurar el directorio de trabajo inicial: /home/concejo: Permiso denegado
```

El rollback integrado restauró `ESTABLE_LEGACY`, un solo bridge, configuración intacta, cero
reintentos. → **WP-094**.

## 12. Primera actualización real A702 y round-trip verde (fase 5L)

Con WP-094 integrado y `main` en `A702`, bajo autorización humana explícita para **ese** SHA y para
una sola ida y vuelta:

1. precheck en `ESTABLE_LEGACY`, un bridge Legacy, `hay_sesion == false`;
2. una única ejecución de `actualizar-sisleg.sh`;
3. `main` resuelto exactamente a `A702`;
4. CI seleccionada: workflow `CI`, run #527 (`34497228680`), evento `push` sobre `main`,
   `conclusion: success`, job `Empaquetado · release productiva` exitoso;
5. artifact exacto `sis-leg-release-a702d71da8c0f2d66b8ccb0231543d15bcdb1e48` (ID `10160364406`),
   checksums coincidentes;
6. release `A702` preparada y `target-release` actualizado atómicamente **mientras Legacy seguía
   activo e ininterrumpido**;
7. conmutación única Legacy → SIS-Leg: `ESTABLE_SISLEG`, `current == target-release == A702`, un solo
   bridge, 12/12 numpads, health local y proxy, las cinco superficies 200, `SIN_PREPARAR` y
   `sesion == null`;
8. confirmación explícita de que **el defecto de WP-094 no reapareció**;
9. conmutación única SIS-Leg → Legacy, con recuperación de backend y bridge Legacy y un solo bridge;
10. estado final `ESTABLE_LEGACY`, cero reintentos, configuración local con hashes idénticos antes y
    después, y `.desktop`, sudoers, releases históricas, `logs` y `logs_backup` preservados.

Revisión: **0 BLOQUEANTES / 0 IMPORTANTES / 0 MENORES**. El actualizador dinámico quedó
**operativamente validado**.

## Después de 5L

WP-029 **no se cerró**: la validación humana de campo y el cutover institucional siguen siendo un
proceso separado y abierto. Ver [09 - Estado conocido y compuertas](09-estado-y-gates.md).
