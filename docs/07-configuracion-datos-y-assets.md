# 07 - Configuración, datos y assets

## 1. Principio

La configuración operacional se carga al iniciar `PREPARANDO` y queda congelada hasta cancelar preparación o cerrar sesión.

Los cambios posteriores en disco no afectan una ejecución activa.

La primera versión no utiliza base de datos: estado operativo en memoria, configuración en archivos, padrón en CSV y auditoría en CSV.

## 2. Estructura de configuración

Estructura inicial canónica:

```text
config/
├── system.example.toml       plantilla versionada
├── system.toml               archivo operativo local, ignorado por Git
├── concejales.example.csv    plantilla versionada
├── concejales.csv            archivo operativo local, ignorado por Git
└── apoyo-tecnico/
    ├── mensajes.example.csv  plantilla versionada
    └── mensajes.csv          archivo operativo local, ignorado por Git

services/device-bridge/
└── config/
    ├── devices.example.json  plantilla versionada
    └── devices.json          archivo operativo local, ignorado por Git
```

`system.toml` concentra configuración funcional/técnica del backend; `concejales.csv` contiene el padrón; `mensajes.csv` guarda la biblioteca de Apoyo Técnico; `devices.json` pertenece exclusivamente al bridge físico.

### Plantillas versionadas y archivos operativos locales (WP-073)

Las rutas que el sistema lee en ejecución son las cuatro sin `.example`, en desarrollo y en producción. Lo que cambia es cómo se materializan:

- el repositorio versiona únicamente las plantillas `*.example.*`, que son el contenido revisable en cada Pull Request;
- los cuatro archivos operativos están declarados en `.gitignore` y nunca se versionan, porque son estado real de cada instalación: una prueba humana, un remapeo de hardware o un ajuste de volumen no deben ensuciar el checkout ni bloquear el lanzador de Work Packages;
- `uv run python scripts/preparar_config_local.py` (alias `pnpm preparar:config`) crea desde su plantilla cada archivo operativo que falte y **nunca sobrescribe** uno existente;
- producción sigue provisionando su configuración fuera de las releases, bajo `/opt/sis-leg/config/`, conforme a DT-031 y `docs/13-despliegue-y-operacion.md`. El bootstrap local no interviene en el despliegue productivo.

## 3. Configuración mínima de `system.toml`

Debe poder definir, como mínimo:

- nombre institucional del cuerpo legislativo;
- fuente/padrón de concejales;
- quórum;
- disposición de bancas;
- tipos de votación permitidos para asistencia de carga;
- retardo para mostrar votos individuales en Moderación;
- temporizador/efecto visual inicial de votación;
- tiempo de permanencia del resultado público;
- directorio de registros CSV;
- assets de bancas/recinto cuando corresponda;
- sonidos de la Pantalla del Recinto: archivo y volumen `0..100` por evento.

Cada parámetro debe tener nombre semántico explícito. No reutilizar una única constante para temporizadores que representen comportamientos distintos aunque inicialmente compartan valor.

### Sección `[institucion]`

WP-084 agrega a `system.toml` una sección con una única clave obligatoria:

```toml
[institucion]
nombre = "Cuerpo Legislativo de Ciudad Ejemplo"
```

Reglas del contrato:

- `nombre` es obligatorio y debe ser un texto no vacío; se rechazan el texto en
  blanco, los números y los booleanos;
- el valor viaja **exactamente** como se escribió: no se recortan espacios ni se
  normaliza el texto, porque cada institución tiene su denominación oficial;
- la plantilla versionada `config/system.example.toml` usa un nombre genérico y
  ficticio. El nombre real de cada instalación vive únicamente en el
  `config/system.toml` local, que no se versiona.

Igual que `[sonidos]`, esta sección se lee **dos veces** y por motivos distintos:

1. al **preparar el recinto**, junto con el resto del archivo, quedando congelada
   en el snapshot de la preparación. Ahí la validación es estricta: una sección
   ausente o inválida impide preparar, igual que un `quorum` inválido;
2. al **arrancar el backend**, porque la cabecera de la Pantalla del Recinto
   muestra el nombre también en `SIN_PREPARAR`. Esa lectura es tolerante: un
   archivo ausente o inválido no impide el arranque y publica un rótulo
   institucional genérico en lugar del nombre real.

Preparar el recinto refresca además la copia leída al arrancar, de modo que
durante una preparación o sesión el Recinto muestre exactamente el nombre
congelado.

La proyección pública `EstadoRecinto` incluye por eso el bloque `institucion` en
los tres estados globales. Es el contrato mínimo: transporta sólo el nombre, no
el diagnóstico interno de la lectura.

### Sección `[sonidos]`

WP-065 agrega a `system.toml` una sección con **quince** subtablas
obligatorias, una por evento sonoro del Recinto. Cada una declara exactamente
`ruta` y `volumen`:

```toml
[sonidos.sesion_abierta]
ruta = "assets/sonidos/sesion-abierta.wav"
volumen = 90
```

Eventos, en su orden canónico: `preparacion_iniciada`,
`aviso_tecnico_publicado`, `aviso_tecnico_retirado`,
`pedido_palabra_registrado`, `pedido_palabra_retirado`, `uso_palabra_otorgado`,
`transmision_iniciada`, `transmision_detenida`,
`transmision_cuenta_regresiva_tic`, `sesion_abierta`, `sesion_cerrada`,
`votacion_abierta`, `votacion_cerrada`, `concejal_ausente`,
`concejal_presente`.

Reglas del contrato:

- `volumen` es un entero de `0` a `100`; `0` silencia sin borrar la
  configuración. Decimales y booleanos se rechazan.
- `ruta` debe empezar por `assets/sonidos/` y terminar en `.wav`. Se rechazan
  URLs, rutas absolutas, barras invertidas y segmentos `..`: la ruta viaja al
  navegador y sólo puede referirse a un asset versionado y servido por la
  propia Pantalla del Recinto.
- Los quince eventos son obligatorios y no se admiten nombres desconocidos: un
  nombre mal escrito falla la carga en lugar de perder un sonido en silencio.
- Los nombres de esta sección están en español. Las secciones anteriores
  conservan sus claves en inglés por compatibilidad con WP-003; ésta es nueva
  y aplica la regla general de DEC-001.

A diferencia del resto del archivo, esta sección se lee **también al arrancar
el backend**, porque transmisión y avisos técnicos operan fuera de una sesión y
la Pantalla del Recinto debe poder sonar ya en `SIN_PREPARAR`. Esa lectura de
arranque es tolerante: un archivo inválido publica la configuración de audio
como no disponible con su motivo, sin impedir el arranque ni afectar
votaciones, presencia o auditoría. La lectura de `Preparar recinto` sigue
siendo estricta y congela la sección junto con el resto de la configuración,
que es la que el Recinto recibe durante esa preparación o sesión.

La proyección pública `EstadoRecinto` incluye por eso el bloque `sonidos` en
los tres estados globales.

## 4. Valores actuales de referencia

La instalación de origen usa:

- quórum: 7;
- disposición por filas: 3, 4 y 5 bancas;
- total histórico: 12 concejales.

Son configuración de instalación y no constantes de negocio.

## 5. Padrón de concejales

Contrato canónico de SIS-Leg:

```text
dni,nombre,apellido,bloque,banca,dispositivo_votacion,ruta_imagen
```

Reglas:

- `dni`: obligatorio, identificador primario, único;
- `nombre`: obligatorio;
- `apellido`: obligatorio;
- `bloque`: puede estar vacío;
- `banca`: obligatoria, válida y única;
- `dispositivo_votacion`: obligatorio y único;
- `ruta_imagen`: obligatoria y debe ser una ruta interna del propio sistema, no una URL externa.

La presencia **no forma parte del archivo de padrón**: es un dato operativo dinámico y toda preparación comienza con todos los concejales ausentes.

La plantilla `concejales.example.csv` contiene **datos ficticios**: doce personas y tres bloques inventados, con las mismas bancas y dispositivos lógicos `dev01..dev12` que espera el mapeo del bridge. Hasta WP-084 esa plantilla reproducía el padrón real recuperado del sistema histórico en producción (`martinebene/Botonera`, SHA `537823b4a0045853c74a388058fa3739cf7457a5`), que fue la procedencia que fijó WP-043. Esa recuperación sigue siendo un hecho histórico y el contrato del archivo no cambió; lo que cambió es que la plantilla versionada ya no publica identidades ni bloques políticos reales, porque es el punto de partida de cualquier instalación nueva y no puede atar el producto a una institución concreta.

El padrón real de cada instalación vive únicamente en `config/concejales.csv`, que no se versiona. El contrato estable se conserva igual: las filas se ordenan por banca, `ruta_imagen` permanece explícita y la columna histórica `presente` se omite porque la presencia sigue siendo estado dinámico.

La cantidad de filas del padrón debe coincidir exactamente con la cantidad total de bancas definida por la disposición configurada en `system.toml` (suma de `room.rows`). Las bancas deben ser únicas, estar dentro de esa capacidad y cubrir completamente la disposición configurada.

Un padrón inválido bloquea `Preparar recinto`.

## 6. Congelamiento del padrón

Una vez iniciada la preparación, el conjunto de concejales y sus datos base no cambia durante esa preparación/sesión.

El reemplazo urgente de un teclado **no modifica el padrón ni la relación lógica concejal-dispositivo del backend**. Se resuelve en el bridge reasignando un nuevo fingerprint físico al mismo identificador lógico.

## 7. Tipos de votación

Deben provenir de `system.toml` y no de código rígido ni de una pantalla administrativa cotidiana.

Lista histórica de referencia:

- Ratificación
- Despacho OP
- Despacho Gob
- Despacho AS
- Despacho HA
- Despacho Eco
- Mocion
- P. Sobre Tabla
- Otro

La lista instalada puede cambiar sin modificar código.

El tipo es descriptivo y no reemplaza el campo explícito `tipo de mayoría`.

## 8. Mayorías

La configuración/formulario representa explícitamente:

- `SIMPLE`, con entrada de factor omitida/nula/cero y base omitida o `VOTOS_COMPUTABLES`; se normaliza a factor `0` y base `VOTOS_COMPUTABLES`;
- `ESPECIAL`, con factor real finito `> 0 <= 1` y base `VOTOS_COMPUTABLES`, `PRESENTES` o `CUERPO`.

`tipo_mayoria` es autoritativo: no inferir mayoría simple o especial a partir del factor. `VOTOS_COMPUTABLES` cuenta positivos + negativos; `PRESENTES` cuenta votos emitidos, incluidas abstenciones; `CUERPO` usa el padrón congelado.

## 9. Temporizadores

Configurables.

Valores iniciales acordados:

- 4 s para retardo/cuenta regresiva visual inicial y referencia de visibilidad en Moderación;
- 6 s para permanencia del resultado en Pantalla del Recinto.

## 10. Orden del Día

Su función es exclusivamente asistencial. Moderación envía el archivo al backend y el backend es el único componente que lo parsea.

### Formato canónico de SIS-Leg

SIS-Leg acepta **únicamente** el nuevo CSV explícito:

```text
nro_votacion,tipo,tema,tipo_mayoria,factor,base
```

Reglas del contrato:

- formato CSV estándar con separador coma `,` y soporte de campos entre comillas cuando el contenido incluya comas;
- encabezado obligatorio con esas seis columnas y ese significado;
- `nro_votacion`: número externo usado para precargar el formulario; no se valida secuencia ni unicidad institucional;
- `tipo`: texto descriptivo que se copia al formulario;
- `tema`: texto descriptivo;
- `tipo_mayoria`: `SIMPLE` o `ESPECIAL`;
- si `tipo_mayoria = SIMPLE`, `factor` puede estar vacío o contener `0`, y `base` puede estar vacía o contener `VOTOS_COMPUTABLES`; el punto normalizado usa factor `0` y esa base;
- si `tipo_mayoria = ESPECIAL`, `factor` debe contener un real finito `> 0 <= 1` y `base` debe ser `VOTOS_COMPUTABLES`, `PRESENTES` o `CUERPO`;
- el parser puede normalizar mayúsculas/minúsculas de los valores enumerados, pero el modelo normalizado interno debe usar los valores canónicos anteriores;
- no se infiere el tipo de mayoría desde `factor=0`, factor vacío ni ningún otro valor: siempre manda `tipo_mayoria`.

El backend valida únicamente la legibilidad y coherencia técnica necesarias para interpretar este contrato. No impone unicidad, secuencia ni legitimidad institucional de los puntos.

Si el archivo no puede interpretarse, se rechaza la carga completa pero la sesión sigue pudiendo operar mediante votaciones manuales.

### Incompatibilidad deliberada con el formato histórico

El formato histórico de producción utilizaba cinco columnas:

```text
nro_votacion,tipo,tema,factor_de_mayoria,respecto
```

Ese formato **no es aceptado por SIS-Leg**. Debe convertirse al formato canónico antes de la importación.

No se implementará un adaptador automático que interprete `factor=0` o vacío como mayoría simple. Esta incompatibilidad evita reintroducir en la nueva arquitectura la semántica histórica implícita que DT-039 decidió eliminar.

## 11. Assets históricos

Fuente autorizada para descargar imágenes existentes:

`martinebene/Botonera`, rama `main`, ruta histórica:

`app/web/static/bancas/`

Incluye imágenes `1.png` a `12.png` usadas para representación de bancas.

SIS-Leg no debe hardcodear la imagen por número de banca. La ruta interna correspondiente a cada concejal se declara en `ruta_imagen` dentro de `concejales.csv`.

Los agentes pueden copiar esos assets cuando implementen la interfaz. No deben copiar el frontend histórico completo para obtenerlos.

## 11 bis. Assets de sonido del Recinto

Los 22 archivos WAV del Recinto están versionados en
`apps/recinto/public/assets/sonidos/`: 15 asignados a los eventos obligatorios
y 7 alternativas sin asignar, que permiten cambiar un sonido editando sólo
`system.toml`.

Los 22 son **originales de SIS-Leg**: los sintetiza de forma determinista
`scripts/generar_sonidos_recinto.py` usando únicamente la biblioteca estándar
de Python, sin grabaciones ni bibliotecas de terceros. No hay obra ajena
involucrada, de modo que se redistribuyen bajo la misma licencia que el resto
del repositorio y no arrastran atribuciones externas. Una prueba regenera los
22 archivos y los compara byte a byte contra los versionados, así que la
procedencia es verificable y no una afirmación.

Formato: WAV PCM sin comprimir, monofónico, 16 bits, 44 100 Hz; ningún archivo
supera los dos segundos.

`assets/sonidos/README.md` documenta duración, descripción y SHA-256 de cada
archivo, y qué evento usa cada uno. Vive fuera de `public/` para que la salida
servida contenga sólo los assets, igual que `assets/branding/`.

Los archivos viven bajo `public/` de la Pantalla del Recinto y siguen versionados
en un único lugar. Desde WP-071 también los reproduce el puesto de Apoyo
Técnico, que **no** guarda una segunda copia: su `nuxt.config.ts` declara ese
mismo directorio como directorio público adicional, de modo que la construcción
los publica además bajo `/tecnico/assets/sonidos/`. Un solo origen versionado y
dos prefijos servidos: no existe un catálogo paralelo que pueda divergir, y la
validación de despliegue sigue comprobando la raíz pública del Recinto.

WP-065 configura y versiona; la reproducción efectiva en el navegador la implementa
WP-066 para el Recinto y WP-071 para Apoyo Técnico. La ruta configurada se resuelve
contra el prefijo público de la aplicación que reproduce —`/recinto/` o `/tecnico/`— y
el mismo volumen `0..100` se aplica en las dos. Qué transición dispara cada evento está
documentado en `docs/06-frontend-pantalla-recinto.md`, y la configuración de los puestos
que permite reproducir sin interacción humana, en `docs/13-despliegue-y-operacion.md`.

## 12. Mapeo físico

Responsabilidades separadas:

```text
fingerprint físico -> device-bridge -> identificador lógico -> backend -> concejal
```

`devices.json` contiene la asociación física del bridge. Es un archivo operativo local: se materializa desde `devices.example.json` y no se versiona, porque cada instalación tiene sus propios fingerprints.

El backend recibe identificadores lógicos y conserva estable durante la preparación la asociación lógica cargada desde el padrón.

El remapeo rápido:

- reemplaza en el bridge el fingerprint físico asociado a un identificador lógico existente;
- puede ocurrir durante votación;
- no altera presencia, votos ni identidad del concejal;
- se registra;
- no modifica automáticamente los archivos base;
- se inicia desde Moderación a través del backend, nunca mediante conexión directa del navegador al bridge.

## 13. Autoridades

Presidencia y Secretaría Legislativa no forman parte del padrón ni de la configuración fija. Se ingresan como texto libre en cada preparación y pueden cambiar durante la sesión.

## 14. Dependencias y versiones

- Python: 3.14, gestionado con `uv` y `uv.lock`.
- Node.js: 24 LTS.
- JavaScript/TypeScript: `pnpm` workspaces y `pnpm-lock.yaml`.
- Frontends: Nuxt 4 + TypeScript estricto.
- Estilos: Tailwind CSS v4 + componentes propios.

Las actualizaciones de dependencias deben ser deliberadas y revisadas; nunca una actualización automática de producción.

## 15. Assets de marca institucional

El nombre visible del producto es **SIS-Leg** (WP-062). Los archivos aprobados por HUMAN_GATE están versionados en `assets/branding/`:

| Archivo | Medidas | Uso |
| --- | --- | --- |
| `assets/branding/sisleg-logo.png` | 1536×1024 | Logo completo: pantalla de carga de las cuatro SPA, estado `SIN_PREPARAR` de la Pantalla del Recinto y cabecera del manual de usuario. |
| `assets/branding/sisleg-isotipo.png` | 256×250 | Isotipo: favicon de las cuatro SPA. |

`assets/branding/README.md` documenta la procedencia de los originales y la derivación autorizada de cada uno: recorte de márgenes y conversión del fondo blanco a transparencia para el isotipo (WP-062); únicamente un suavizado mínimo del borde, sin recorte ni escala, para el logo completo entregado el 04/09/2026 (WP-069). El lienzo del logo conserva por eso los márgenes transparentes del archivo humano y no se recorta. Ambos PNG tienen canal de transparencia, de modo que no dibujan un rectángulo blanco sobre las superficies oscuras.

El manual de usuario (`manual/index.html`) incrusta el mismo logo como `data:` para conservar su condición de documento único sin recursos externos; el contenido decodificado es idéntico al canónico.

Cada SPA consume una copia idéntica bajo `apps/<aplicacion>/public/assets/marca/`, igual que ya ocurre con las imágenes de banca. La duplicación es deliberada: cada aplicación se sirve bajo su propio prefijo (`/moderacion/`, `/recinto/`, `/tecnico/`, `/simulador/`) y publica su propio directorio estático, así que un único archivo compartido no sería alcanzable desde las cuatro sin introducir una ruta de servidor adicional.

Reglas de uso:

- donde se muestra el logo completo no se repite «SIS-Leg» como texto;
- la marca no se redibuja, recolorea ni se le agrega fondo;
- `SIS-Leg` es a la vez la marca visible y el nombre técnico del repositorio, los paquetes, los módulos, las unidades systemd y el contrato OpenAPI; el nombre histórico `Botonera2` sólo sobrevive en la evidencia inmutable descrita en `docs/NOTA-LEGADO-BOTONERA2.md`.
