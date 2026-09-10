# Instalación productiva de SIS-Leg — documentación temporal

## Qué es esta carpeta

Describe **el estado real de la instalación productiva** que se fue construyendo durante la
transición del sistema Legacy a SIS-Leg, junto con los incidentes encontrados, sus correcciones y
las compuertas de seguridad vigentes.

Existe para que un agente o una persona que no siguió la conversación de coordinación pueda
entender, en poco tiempo, cómo está armado el host institucional, qué mecanismos lo operan y qué
sigue siendo provisorio.

## Qué NO es

- **No es todavía la guía general de instalación de SIS-Leg.** Describe una instalación concreta en
  un momento concreto de la transición, con un sistema Legacy todavía presente y conmutable.
- **No es documentación normativa del producto.** La fuente normativa sigue siendo
  [`docs/13-despliegue-y-operacion.md`](../13-despliegue-y-operacion.md) y las decisiones técnicas
  `DT-027`..`DT-032`. Si algo de esta carpeta contradice esa documentación, manda la documentación
  canónica y lo de acá es un defecto a corregir.
- **No es documentación de usuario.** El manual de operación, configuración y soporte para quien usa
  el sistema es `manual/index.html`, publicado con cada release en `/manual/`.

Buena parte de lo que se describe acá —los wrappers de conmutación, `target-release`, los lanzadores
del escritorio, el actualizador— **vive únicamente en el host institucional** y no está versionado en
este repositorio. Son andamios de la transición. Cuando la etapa productiva termine, esta carpeta se
transformará en una guía general de instalación y esos andamios desaparecerán o se convertirán en
mecanismos versionados.

## Índice

| Documento | Contenido |
| --- | --- |
| [01 - Topología actual](01-topologia-actual.md) | Host, Nginx, servicios Legacy y SIS-Leg, puertos, exclusión mutua de bridges. |
| [02 - Layout en disco](02-layout-en-disco.md) | `releases/`, `current`, `previous`, `target-release`, configuración, logs, backups. |
| [03 - Modelo de configuración local](03-configuracion-local.md) | Los cuatro archivos persistentes, permisos y por qué una actualización no los toca. |
| [04 - Preparación, activación y rollback](04-preparacion-activacion-rollback.md) | `deploy/herramienta_despliegue.py`, releases inmutables, validaciones de salud, guards. |
| [05 - Conmutación Legacy ↔ SIS-Leg](05-conmutacion-legacy-sis-leg.md) | Scripts privilegiados, wrappers de usuario, lock global, target dinámico. |
| [06 - Actualizador actual](06-actualizador-actual.md) | Estado previo a WP-100 y su dependencia transitoria de GitHub autenticado. |
| [07 - Cronología de la puesta en producción](07-cronologia.md) | Hitos verificados desde la preparación paralela hasta la actualización A702. |
| [08 - Incidentes y lecciones](08-incidentes-y-lecciones.md) | Cada defecto encontrado en campo, su causa y su corrección. |
| [09 - Estado conocido y compuertas](09-estado-y-gates.md) | Dónde está hoy la instalación, qué está autorizado y qué no. |

## Cómo leer esta carpeta

Los documentos son independientes pero están ordenados de lo estructural a lo histórico. Para
entender el sistema alcanza con 01 a 06. Para entender **por qué** está armado así, 07 y 08. Para
saber qué se puede hacer hoy, 09.

## Convenciones

- `Legacy` es el sistema de votación anterior, todavía instalado y operativo en el host.
- `SIS-Leg` es el sistema nuevo, desplegado como releases inmutables.
- Un `SHA` es siempre un commit Git completo de 40 caracteres de `martinebene/SIS-Leg`.
- Los SHA abreviados que aparecen en el texto (`50abb`, `bfbb636`, `A702`) son apodos de lectura de
  releases concretas; el valor completo se indica la primera vez que aparece.
- Los estados formales del host los clasifica el script `sisleg-estado`: `ESTABLE_LEGACY`,
  `ESTABLE_SISLEG`, `INERTE_SEGURO` y `ESTADO_INCONSISTENTE`.

## Seguridad documental

Esta carpeta es pública. No contiene ni debe contener:

- tokens, PAT, credenciales, cookies ni secretos de ninguna clase;
- contenido de los archivos de configuración institucional (padrón, mensajes, mapeo de dispositivos);
- datos personales;
- el nombre de la institución concreta donde corre la instalación, que desde WP-084 se configura en
  `config/system.toml` y no se escribe en material activo del repositorio.

Los comandos que aparecen son reproducibles y no incluyen secretos. Los comandos que **mutan** el
host institucional están marcados como tales y requieren la compuerta humana descrita en
[09 - Estado conocido y compuertas](09-estado-y-gates.md).

## Trazabilidad

El detalle operativo de cada hito vive en el repositorio de coordinación
`martinebene/SIS-Leg-Control`, bajo `work-packages/WP-029/`. Esta carpeta resume esa evidencia; no la
reemplaza ni la contradice.
