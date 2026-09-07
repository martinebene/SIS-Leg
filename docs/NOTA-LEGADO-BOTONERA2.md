# Nota canónica de legado: Botonera2 es el nombre histórico de SIS-Leg

## Para qué sirve esta nota

Este proyecto se llamó `Botonera2` desde su creación hasta WP-077. Ese nombre aparece todavía en
una enorme cantidad de evidencia que **no puede reescribirse sin destruir la trazabilidad**:
commits, mensajes de commit, ramas ya integradas, títulos y números de Pull Request, ejecuciones
de CI, handoffs publicados en el repositorio de control y hashes que dependen del contenido exacto
de un archivo.

Esta nota es la traducción oficial entre ambos nombres. Sirve para leer esa evidencia vieja sin
ambigüedad y para decidir, ante una ocurrencia concreta del nombre anterior, si es legado válido o
una regresión que hay que corregir.

## Equivalencia de identidades

| Concepto | Nombre histórico | Nombre vigente |
| --- | --- | --- |
| Marca y nombre humano del producto | `Botonera2` | `SIS-Leg` |
| Repositorio de producto | `martinebene/Botonera2` | `martinebene/SIS-Leg` |
| Repositorio de coordinación | `martinebene/Botonera2-Control` | `martinebene/SIS-Leg-Control` |
| Slug técnico con guion | `botonera2` | `sis-leg` |
| Identificador Python | `botonera2` | `sis_leg` |
| Distribución Python raíz | `botonera2` | `sis-leg` |
| Distribución del backend | `botonera2-backend` | `sis-leg-backend` |
| Módulo importable del backend | `botonera2_backend` | `sis_leg_backend` |
| Distribución y CLI del bridge | `botonera2-device-bridge` | `sis-leg-device-bridge` |
| Módulo importable del bridge | `botonera2_device_bridge` | `sis_leg_device_bridge` |
| Scope npm | `@botonera2/*` | `@sis-leg/*` |
| Prefijo de variables de entorno | `BOTONERA2_*` | `SIS_LEG_*` |
| Raíz de despliegue | `/opt/botonera2` | `/opt/sis-leg` |
| Unidad systemd del backend | `botonera2-backend.service` | `sis-leg-backend.service` |
| Unidad systemd del bridge | `botonera2-device-bridge.service` | `sis-leg-device-bridge.service` |
| Usuario/grupo del backend | `botonera2-backend` | `sis-leg-backend` |
| Usuario/grupo del bridge | `botonera2-bridge` | `sis-leg-bridge` |
| Sitio Nginx | `botonera2.conf` | `sis-leg.conf` |
| Artefacto de release | `botonera2-<sha>.tar.gz` | `sis-leg-<sha>.tar.gz` |
| Formato del manifiesto de release | `botonera2-release` | `sis-leg-release` |
| Marcador de release preparada | `.botonera2-preparada.json` | `.sis-leg-preparada.json` |

La marca visible aprobada por HUMAN_GATE en WP-062 se escribía `SISLeg`. WP-077 cierra la
convención oficial en `SIS-Leg` y el texto del producto, la documentación y el manual usan esa
forma. El logotipo institucional **no se redibujó**: sigue siendo el archivo aprobado y dentro de
la imagen la palabra continúa compuesta sin guion. Eso es deliberado y no es una inconsistencia a
corregir por iniciativa de un agente.

## Qué NO se reescribió, y por qué

Estas categorías conservan el nombre histórico de forma permanente:

1. **Historia Git.** Commits, árboles, mensajes de commit, autores y fechas. Reescribirlos
   cambiaría todos los SHA y rompería cada referencia cruzada del proyecto.
2. **Pull Requests ya integradas.** Su número, título, descripción y discusión quedan como
   fueron escritos.
3. **Ramas ya integradas o eliminadas.** El nombre con el que existieron es parte del registro.
4. **Ejecuciones de CI históricas.** Su identificador y su salida pertenecen al momento en que
   corrieron.
5. **Handoffs y decisiones publicadas en el repositorio de control.** El protocolo los define
   como append-only e inmutables; un handoff modificado deja de ser evidencia.
6. **Hashes de contenido.** Cualquier verificación registrada como SHA-256 de un archivo concreto
   deja de validar si se cambia una sola letra del archivo.
7. **Enunciados que citan la marca retirada.** Contratos de WP y pruebas que dicen literalmente
   «la cabecera ya no muestra Botonera2» describen un hecho histórico. Sustituir ahí el nombre
   viejo por el nuevo convertiría una afirmación verdadera en una falsa.

Las categorías 1 a 6 viven fuera de los archivos de este repositorio. La categoría 7 sí vive
dentro, y por eso está enumerada archivo por archivo en la auditoría automatizada descrita abajo.

## Auditoría automatizada

`scripts/auditar_identidad_legada.py` recorre todos los archivos versionados y falla si aparece
una referencia activa al nombre legado fuera de una excepción explícita. Hay dos clases de
excepción, y ninguna de las dos consiste en excluir un directorio completo.

**Allowlist por ruta y conteo exacto.** Es la política por defecto y cubre archivos cuyo contenido
histórico ya está congelado: contratos de WP cerrados, pruebas de regresión que usan el literal
como valor bajo prueba, el manual y la propia herramienta. Cada entrada declara la cantidad exacta
de ocurrencias esperadas y el motivo por el que son válidas, de modo que agregar una referencia
nueva a un archivo ya permitido también falle.

**Registros históricos vivos.** `docs/implementation/PLAN.md` acumula trazabilidad y suma
menciones legítimas cada vez que se cierra un Work Package, así que exigirle un conteo fijo rompía
el gate por su propio uso normal. Eso fue el hallazgo ASTRA-010 que corrigió WP-079. Para esas
rutas, declaradas una por una y nunca por directorio, la regla no es cuántas veces aparece el
nombre anterior sino **cómo** aparece: cada línea que lo mencione debe nombrar además la identidad
vigente o encuadrar el pasado con una palabra del vocabulario declarado (legado, histórico,
anterior, migración, renombrar). Una línea que copie una referencia activa, como una ruta de
instalación o un módulo, no cumple esa condición y sigue fallando.

```bash
uv run python scripts/auditar_identidad_legada.py
```

`tests/test_auditoria_identidad_legada.py` ejecuta esa auditoría dentro de la suite y comprueba
además que ninguna de las dos políticas se degrade: rutas inexistentes, motivos vacíos, conteos
desactualizados, una ruta declarada a la vez en las dos políticas o una referencia activa colada
dentro de un registro vivo hacen fallar la CI.

## Redirects de GitHub

Al renombrar un repositorio, GitHub deja redirecciones desde el nombre anterior hacia el nuevo
para las URL web y para las operaciones Git: `clone`, `fetch` y `push` contra la dirección vieja
siguen funcionando, y también redirigen issues, wikis, estrellas y seguidores. Esas redirecciones
son un respaldo transitorio y no configuración canónica: los remotos, la documentación, las
integraciones y los enlaces de este proyecto apuntan directamente a `martinebene/SIS-Leg` y
`martinebene/SIS-Leg-Control`.

Hay dos excepciones documentadas por GitHub que conviene tener presentes en el corte:

- **GitHub Actions no redirige.** Un workflow que use una *action* alojada en un repositorio
  renombrado falla con `repository not found`. Los workflows de este proyecto sólo consumen
  actions de terceros (`actions/checkout`, `astral-sh/setup-uv`, `pnpm/action-setup`,
  `actions/setup-node`, `actions/upload-artifact`), así que el rename no los afecta; si en el
  futuro se publicara una action propia, habría que actualizar cada referencia a mano.
- **Las URL de GitHub Pages no se redirigen.** El proyecto no publica sitio de Pages, de modo que
  hoy no hay nada que reconfigurar.

Fuente consultada el 6 de septiembre de 2026:
`https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository`.

Los nombres `Botonera2` y `Botonera2-Control` **no vuelven a usarse** para repositorios nuevos.
Reutilizarlos rompería las redirecciones y haría que evidencia histórica apuntara a un proyecto
distinto.

## No confundir con `martinebene/Botonera`

`martinebene/Botonera`, sin el `2`, es un repositorio **distinto**: el sistema anterior que sigue
en producción y que DEC-001 autoriza a consultar como referencia funcional. Ese nombre no cambia y
no forma parte de esta migración.

## Documentos relacionados

- `docs/work-packages/WP-077.md`: contrato del cambio de identidad.
- `docs/MIGRACION-A-SIS-LEG.md`: procedimiento para migrar una instalación ya desplegada.
- `docs/decisions/DEC-017-coordinacion-mediante-sis-leg-control.md`: coordinación mediante el
  repositorio de control, renombrado por este mismo WP.
