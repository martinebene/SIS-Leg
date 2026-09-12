# 09 - Estado conocido y compuertas

Estado al inicio de la campaña de desarrollo `FIELD_ADJUSTMENTS_2026_09_10`, del 10/09/2026.

## Estado conocido

| Dimensión | Valor |
| --- | --- |
| `main` del producto | `a702d71da8c0f2d66b8ccb0231543d15bcdb1e48` (A702) |
| Estado del host | `ESTABLE_LEGACY` |
| `/opt/sis-leg/target-release` | A702 |
| Release A702 | preparada y validada en disco |
| Sistema activo | Legacy; SIS-Leg inactivo |
| Bridges activos | exactamente uno |
| Actualizador dinámico | operativamente validado y habilitado para uso normal bajo sus guards internos |
| Validación humana de campo (WP-029) | **abierta** |
| Cutover definitivo | **no autorizado** |
| Configuración local | preservada byte a byte durante toda la puesta en producción |

Que el host esté en `ESTABLE_LEGACY` con `target-release` en A702 no es una contradicción: significa
que SIS-Leg A702 está listo para activarse y que la decisión de activarlo es del operador, no del
actualizador ([06](06-actualizador-actual.md)).

## Regla de campaña vigente

```text
DEVELOPMENT_ONLY_NO_PRODUCTION_MUTATION
```

Todos los cambios de esta campaña se implementan, prueban, revisan e integran **primero en
desarrollo**. Producción no se toca hasta que el lote de producto esté finalizado e integrado en
`main`.

La única excepción es la **lectura** de evidencia productiva ya existente para documentar contexto,
sin ninguna mutación. Esta carpeta se escribió bajo esa excepción.

## Lote de desarrollo en curso

| WP | Objetivo | Estado |
| --- | --- | --- |
| WP-095 | Esta documentación temporal de la instalación productiva. | en curso |
| WP-096 | Registrar en el log principal el inicio y fin efectivos del indicador de transmisión EN VIVO. | no iniciado |
| WP-097 | Optimizar Moderación y Recinto para 1280×720 sin degradar resoluciones mayores. | no iniciado |
| WP-098 | Fuente única de fotos de bancas dentro de la configuración local. | no iniciado |
| WP-099 | Pantalla Zócalo para OBS. | no iniciado |
| WP-100 | Actualizador público sin autenticación y política de incorporación de recursos de configuración nuevos. | no iniciado |

El orden es deliberado: WP-099 depende de la geometría estabilizada por WP-097 y del modelo de
recursos de WP-098; WP-100 necesita conocer el modelo final de configuración y empaquetar también la
nueva superficie.

Paralelismo máximo de la campaña: **1**. Flujo por WP: implementador → CI candidata → revisor
independiente → compuerta humana hacia el orquestador. Sin rebase ni force-push.

## Lo que está autorizado hoy

- desarrollo, pruebas, revisión e integración de WP-095 a WP-100 en `martinebene/SIS-Leg`;
- lectura de evidencia productiva ya persistida;
- uso normal del actualizador canónico para releases futuras de `main`, **siempre que sus guards
  internos pasen**, sin necesidad de una compuerta humana por cada SHA.

## Lo que NO está autorizado

- mutar producción como parte de un Work Package de desarrollo;
- modificar servicios, wrappers, lanzadores `.desktop`, configuración productiva o el actualizador
  del host;
- ejecutar conmutaciones o actualizaciones en el host desde un turno de desarrollo;
- declarar el cutover definitivo;
- retirar, desinstalar o degradar el sistema Legacy;
- cerrar la validación humana de campo de WP-029, que sólo se cierra por decisión humana explícita;
- iniciar la fase productiva posterior antes de que WP-095..WP-100 estén integrados, con CI
  post-merge verde y una compuerta humana explícita.

## Preparación versionada de la adaptación productiva (WP-101)

WP-101 se dividió deliberadamente en dos etapas:

| Etapa | Alcance | Estado |
| --- | --- | --- |
| WP-101A | Versionar en desarrollo las tres operaciones de usuario y el aplicador que las instalará. | ejecutada sin tocar producción |
| WP-101B | Aplicar esos componentes sobre el host real. | **pendiente** de acceso al equipo y de HUMAN_GATE específico |

La integración de WP-101A **no** autoriza WP-101B. Antes de cualquier escritura sobre el host, el
ORCHESTRATOR debe ordenar un inventario read-only y comparar el estado real contra lo preparado. El
detalle está en [10 - Mecanismo versionado y su aplicación](10-mecanismo-versionado-y-aplicacion.md),
que además enumera los datos del host que deben relevarse otra vez y no deducirse de esta carpeta.

## Estado deseado al terminar el desarrollo

Una **única instalación lógica** de SIS-Leg en producción, actualizable desde el canal público
derivado de `main`, con configuración persistente local. Esa adaptación se diseña y ejecuta
**después** del lote de desarrollo, y bajo estas condiciones:

- los archivos locales existentes se preservan;
- los recursos y configuraciones nuevos que traiga una release se incorporan **sólo si faltan**;
- un cambio de formato de configuración exige una migración explícitamente acordada y autorizada en
  ese momento;
- no se retira Legacy ni se ejecuta un cutover irreversible sin una compuerta humana específica y
  evidencia de respaldo y rollback apropiada.

## Cuándo deja de existir esta carpeta

Cuando la etapa productiva termine, esta documentación temporal se transformará en la **guía general
de instalación** de SIS-Leg. En ese momento:

- los andamios de la transición —`target-release`, los wrappers de conmutación, los lanzadores duales
  y el actualizador basado en Actions autenticado— habrán desaparecido o se habrán convertido en
  mecanismos versionados del producto;
- lo que quede describirá una instalación única y reproducible, no un host concreto en transición.

Hasta entonces, **todo lo que esta carpeta describe hay que leerlo como estado actual, no como diseño
final**.
