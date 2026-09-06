# 12 - Decisiones técnicas

Este documento registra decisiones técnicas ya aprobadas para SIS-Leg. Complementa las reglas de negocio y evita que los agentes vuelvan a decidir aspectos ya cerrados.

Las decisiones aún no resueltas permanecen en `10-preguntas-abiertas.md`.

## DT-001 - Monorepo

SIS-Leg será un **monorepo**.

Estructura objetivo inicial:

```text
SIS-Leg/
├── apps/
│   ├── backend/          # FastAPI
│   ├── moderacion/       # Nuxt
│   └── recinto/          # Nuxt
├── services/
│   └── device-bridge/    # captura/remapeo de dispositivos físicos
├── packages/
│   ├── api-client/       # cliente REST/SSE y tipos derivados
│   └── frontend-shared/  # código genuinamente común
├── config/
├── docs/
├── scripts/
├── tools/
└── ...
```

Los cuatro componentes funcionales deben permanecer separados aunque vivan en el mismo repositorio.

## DT-002 - Python

- Versión objetivo: **Python 3.14**.
- Gestor de proyectos/dependencias: **uv**.
- Lockfile canónico versionado: `uv.lock`.
- Backend y `device-bridge` pueden formar parte de un workspace `uv` cuando corresponda.
- `pip + requirements.txt` no será la fuente canónica de dependencias; solo puede existir como exportación de compatibilidad.

## DT-003 - Node.js y paquetes JavaScript

- Versión objetivo: **Node.js 24 LTS**.
- Gestor de paquetes: **pnpm**.
- Nuxt y paquetes TypeScript compartidos se organizan mediante **pnpm workspaces**.
- Lockfile canónico versionado: `pnpm-lock.yaml`.

## DT-004 - Estado operativo del backend

El backend tendrá **un único estado operativo en memoria** por ejecución.

- se crea durante el ciclo de vida de FastAPI;
- representa `SIN_PREPARAR`, `PREPARANDO` o `SESION_ABIERTA` y sus entidades activas;
- no se restaura desde disco después de una caída;
- toda mutación pasa por servicios/comandos del backend;
- comandos y pulsaciones concurrentes se serializan mediante un mecanismo único;
- el orden aceptado es el orden oficial y el persistido.

## DT-005 - Un solo proceso/worker de FastAPI

La ejecución productiva del backend utilizará **un único proceso/worker**. Varios workers crearían estados independientes incompatibles con el estado único en memoria.

## DT-006 - Transporte frontend/backend

Se utilizará **REST** para comandos, snapshots y consultas puntuales, y **Server-Sent Events (SSE)** para cambios de estado backend → frontend.

Al cargar o reconectar, cada frontend obtiene primero un snapshot completo por REST y luego mantiene su stream SSE. Ante duda de sincronización se vuelve a obtener snapshot completo.

No se usará polling periódico como mecanismo normal ni WebSocket salvo nueva decisión documentada.

## DT-007 - Contrato de API

La API interna nueva será REST versionada bajo `/api/v1`.

- FastAPI + Pydantic definen esquemas de entrada/salida.
- OpenAPI generado por FastAPI es la definición técnica canónica del contrato HTTP.
- Los errores de dominio incluyen identificadores estables legibles por máquina.
- Se distinguen comandos que mutan estado de consultas/proyecciones.
- Los contratos TypeScript deben derivarse de OpenAPI cuando sea práctico.

## DT-008 - Proyecciones separadas de estado

El backend genera al menos `ModerationState` y `PublicState`.

Durante `EN_CURSO`, `PublicState` no contiene votos individuales ni eventos/datos capaces de revelarlos. El secreto temporal se garantiza en servidor.

## DT-009 - Sin base de datos en la primera versión

La primera versión operará con estado activo en memoria, configuración en archivos, padrón en CSV y auditoría institucional en tres CSV. No se incorporará PostgreSQL, SQLite ni otra base de datos.

## DT-010 - Configuración por archivos

Estructura inicial:

```text
config/
├── system.toml
└── concejales.csv

services/device-bridge/
└── config/
    └── devices.json
```

`system.toml` contiene, como mínimo, quórum, disposición de bancas, tipos descriptivos de votación, temporizadores y directorio de registros. `concejales.csv` contiene el padrón. `devices.json` pertenece al bridge y contiene la relación fingerprints físicos → dispositivos lógicos.

Configuración funcional y padrón se cargan al iniciar `PREPARANDO` y quedan congelados hasta cancelar preparación/cerrar sesión.

## DT-011 - Formato de los CSV de auditoría

Cada preparación crea:

```text
logs/
└── AAAA-MM-DD/
    ├── AAAA-MM-DD_HH-MM-SS-L1.csv
    ├── AAAA-MM-DD_HH-MM-SS-L2.csv
    └── AAAA-MM-DD_HH-MM-SS-L3.csv
```

Columnas:

```text
seq;timestamp;level;tag;event_code;message
```

Reglas:

- delimitador `;`;
- UTF-8 con BOM;
- timestamp `AAAA-MM-DD HH:MM:SS`, hora local;
- `seq` monotónica dentro de la preparación/sesión;
- L1 recibe L1+L2+L3, L2 recibe L2+L3 y L3 recibe solo L3.

## DT-012 - Escritura segura y fallo cerrado

Cada evento se persiste de forma síncrona bajo el mecanismo de serialización del backend: escritura, `flush` y `fsync` antes de considerar completada la operación funcional asociada.

Si durante `PREPARANDO` o `SESION_ABIERTA` no puede garantizarse la auditoría, el backend entra en **fallo cerrado** para nuevas mutaciones y expone una condición técnica grave a Moderación.

## DT-013 - Orden del Día procesado por backend

Moderación envía el CSV al backend. El backend lo parsea, valida solo legibilidad/formato técnico, devuelve puntos normalizados o error técnico estable y no valida secuencia, unicidad ni legitimidad institucional.

## DT-014 - Remapeo físico en el device-bridge

El identificador lógico conocido por backend permanece estable:

```text
teclado físico (fingerprint) -> device-bridge -> identificador lógico (devXX) -> backend -> concejal
```

Ante falla, el remapeo sustituye el fingerprint físico asociado al mismo identificador lógico dentro del bridge. No cambia concejal, presencia ni votos; puede ocurrir durante una votación; se registra y no reescribe automáticamente la configuración base.

La operación se inicia desde Moderación a través del backend; el frontend no se conecta directamente al bridge.

## DT-015 - Stack Nuxt

- Nuxt 4 en la versión estable seleccionada al crear el scaffold.
- Vue 3 gestionado por Nuxt.
- TypeScript estricto.
- `nuxt typecheck` obligatorio.
- Versiones congeladas por `pnpm-lock.yaml`.
- Actualizaciones de dependencias deliberadas mediante PR.

## DT-016 - Tailwind CSS y componentes propios

Los frontends utilizarán **Tailwind CSS v4** y componentes Vue/Nuxt propios. No se incorporará Nuxt UI inicialmente. Puede utilizarse CSS propio complementario.

## DT-017 - Estado frontend sin Pinia inicialmente

El estado autoritativo vive en FastAPI. Cada frontend mantiene la proyección recibida y estado local visual mediante composables, `useState`, `ref` y primitives de Vue/Nuxt. No se usará Pinia inicialmente salvo necesidad futura documentada.

## DT-018 - Cliente API compartido

Existirá `packages/api-client/` con tipos derivados de OpenAPI, cliente REST, errores uniformes, SSE, reconexión, recuperación de snapshot y control de sincronización.

## DT-019 - Compartición frontend mínima y explícita

`packages/frontend-shared/` contendrá únicamente elementos genuinamente comunes: disposición de bancas, utilidades, assets y componentes realmente idénticos. No se construirá una gran librería UI común preventivamente.

## DT-020 - Estrategia responsive y hardware de referencia

El hardware actual es Full HD 1920×1080, pero esa resolución es solo referencia.

Las interfaces deben adaptarse a cambios razonables de monitor, resolución, escala del sistema operativo y navegador. Moderación debe conservar funcionalidad sin solapamientos; paneles extensos usan scroll interno. Recinto prioriza composición 16:9 pero responde de forma controlada ante otras relaciones de aspecto.

Los tests deben incluir Full HD y al menos una resolución alternativa.

## DT-021 - Pruebas backend

Se utilizarán **pytest + HTTPX + AnyIO**.

La suite debe cubrir:

- reglas de dominio con pruebas unitarias puras;
- servicios/comandos;
- API FastAPI;
- comportamiento asíncrono cuando corresponda;
- serialización/concurrencia;
- SSE y reconstrucción de estado;
- casos de aceptación reglamentarios.

No se fija un porcentaje de coverage como objetivo principal. La cobertura de reglas, invariantes y criterios de aceptación tiene prioridad sobre una métrica arbitraria de líneas.

## DT-022 - Pruebas frontend

Se utilizarán:

- **Vitest**;
- **`@nuxt/test-utils`**;
- **Vue Test Utils**.

Se probarán especialmente composables, cliente API, reconexión, transformación de estado, controles habilitados/deshabilitados, secreto temporal de votos y componentes con lógica. No es objetivo testear cada clase visual de Tailwind.

## DT-023 - Pruebas E2E

Se utilizará **Playwright**.

Inicialmente los E2E críticos se ejecutarán en Chromium, incluyendo al menos:

- 1920×1080;
- 1366×768.

Los recorridos críticos incluyen preparación, acreditación, apertura, votación, autocierre, empate/desempate, pérdida de quórum, palabra, reconexión y secreto de votos en Recinto.

La matriz de navegadores puede ampliarse si cambia el hardware real o aparece una necesidad concreta.

## DT-024 - Simulador de dispositivos

Existirá una herramienta de desarrollo reproducible:

```text
tools/
└── device-simulator/
```

Será inicialmente una **CLI**, no una GUI.

Debe permitir:

- emitir pulsaciones por dispositivo lógico;
- ejecutar escenarios declarativos reproducibles;
- automatizar casos normales, errores y concurrencia;
- ser utilizable por desarrolladores, agentes y pruebas sin hardware físico.

Los escenarios podrán residir en archivos versionados, por ejemplo votación simple, empate, pérdida de quórum y concurrencia.

## DT-025 - Integración continua

Se utilizará **GitHub Actions** en cada Pull Request.

Checks conceptuales separados:

```text
backend-quality
backend-tests
frontend-quality
frontend-tests
build
e2e-critical
```

La CI debe cubrir como mínimo Ruff, Pyright, pytest, ESLint, Nuxt/TypeScript typecheck, Vitest, build de ambos frontends y Playwright E2E críticos.

Los checks deberán convertirse en obligatorios para integrar cuando se cierre la política de ramas/protecciones. Las Actions usarán permisos mínimos y los tests normales no dependerán de secretos.

## DT-026 - Calidad estática y formato

### Python

- **Ruff** como linter;
- **Ruff formatter**;
- **Pyright** como type checker.

### Nuxt/TypeScript

- **`@nuxt/eslint`** con configuración moderna/flat;
- **Prettier** para formato;
- `nuxt typecheck`;
- TypeScript estricto.

En CI estas herramientas verifican; no autocorrigen ni modifican código.

## DT-039 - Formato canónico del CSV de Orden del Día

SIS-Leg utilizará exclusivamente un **nuevo contrato explícito** de Orden del Día:

```text
nro_votacion,tipo,tema,tipo_mayoria,factor,base
```

Reglas:

- CSV con separador coma y quoting CSV estándar;
- `tipo_mayoria` debe representar explícitamente `SIMPLE` o `ESPECIAL`;
- para `SIMPLE`, `factor` puede estar vacío o contener `0`, y `base` puede estar vacía o contener `VOTOS_COMPUTABLES`; el modelo normalizado usa factor `0` y esa base;
- para `ESPECIAL`, `factor` es un real finito obligatorio `> 0 <= 1` y `base` debe ser `VOTOS_COMPUTABLES`, `PRESENTES` o `CUERPO`;
- el parser backend puede normalizar mayúsculas/minúsculas de valores enumerados, pero el modelo interno utiliza los valores canónicos;
- no se infiere el tipo de mayoría desde `factor=0`, factor vacío ni otro valor: `tipo_mayoria` siempre es explícito y autoritativo;
- el formato histórico de cinco columnas `nro_votacion,tipo,tema,factor_de_mayoria,respecto` **no es aceptado** y debe convertirse externamente antes de importar;
- SIS-Leg no implementará adaptador automático de compatibilidad para ese formato histórico.

El detalle del contrato vive en `docs/07-configuracion-datos-y-assets.md` y debe regir WP-016 y la UI de Orden del Día.

## Consecuencias para los agentes

DT-001 a DT-026 y DT-039 están cerradas. Los agentes no deben, sin una nueva decisión documentada:

- dividir el sistema en repositorios independientes;
- sustituir `uv`, `pnpm`, Nuxt 4 o Tailwind v4;
- introducir una base de datos;
- ejecutar múltiples workers;
- reintroducir polling como sincronización principal;
- sustituir REST + SSE por WebSockets;
- entregar al frontend público el DTO completo de Moderación;
- parsear el Orden del Día exclusivamente en frontend;
- aceptar el formato histórico de Orden del Día o inferir mayoría desde el factor;
- aceptar mutaciones si la auditoría obligatoria no puede persistirse;
- implementar remapeo cambiando votos, presencia o identidad;
- introducir Pinia o una librería UI extensa por iniciativa propia;
- asumir que la UI solo funcionará a 1920×1080;
- sustituir el stack de testing o calidad por iniciativa propia;
- omitir tests de reglas modificadas o evitar la CI obligatoria definida para el alcance.
