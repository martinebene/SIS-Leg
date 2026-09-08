# SIS-Leg

Reimplementación desde cero del sistema de votación de un cuerpo legislativo. El nombre institucional de cada instalación se configura en `config/system.toml` (WP-084) y no está escrito en el código.

**SIS-Leg** es el nombre del producto y también su identidad técnica: es lo que ve una persona en las pantallas, en el título de cada pestaña y en el logo institucional, y es además el nombre del repositorio, de los paquetes `@sis-leg/*`, de los módulos Python y de las unidades de servicio. WP-062 adoptó la marca visible y WP-077 completó el cambio de identidad técnica; `Botonera2` quedó como nombre histórico del proyecto y se explica en `docs/NOTA-LEGADO-BOTONERA2.md`.

## Objetivo

Construir una nueva versión mantenible y verificable compuesta por:

- backend FastAPI como única autoridad de estado y reglas de negocio;
- frontend Nuxt.js de Moderación;
- frontend Nuxt.js de Pantalla del Recinto;
- servicio/bridge independiente para capturar los teclados físicos y enviar sus pulsaciones al backend.

La documentación de este repositorio es la especificación canónica para SIS-Leg y debe permitir que agentes de programación implementen el sistema sin reinterpretar las reglas institucionales ni técnicas ya decididas.

## Fuentes históricas

El sistema actualmente en producción está en `martinebene/Botonera`, rama `main`.

Referencia histórica de producción:

- repositorio: `https://github.com/martinebene/Botonera`
- rama: `main`
- snapshot usado para el relevamiento inicial: `537823b4a0045853c74a388058fa3739cf7457a5`

Existe además una rama histórica `v2`, no validada en producción. Puede aportar contexto técnico, pero no es fuente normativa.

### Regla de autoridad

1. La documentación vigente de **SIS-Leg** (repositorio `SIS-Leg`) manda para la nueva implementación.
2. Para reglas extraídas del sistema anterior, se tomó como fuente de verdad el **código ejecutable de `Botonera/main`**, no su documentación antigua.
3. `Botonera/v2`, README, manuales, comentarios y documentación histórica sirven solo como contexto salvo referencia expresa.
4. El repositorio histórico solo debe consultarse en el futuro para descargar assets o validar explícitamente una regla dudosa.

## Ciclo funcional global

El sistema tiene tres estados globales:

`SIN_PREPARAR -> PREPARANDO -> SESION_ABIERTA -> SIN_PREPARAR`

- `SIN_PREPARAR`: no existe interacción funcional con los dispositivos.
- `PREPARANDO`: se cargan configuración y concejales, se identifican autoridades, se acredita presencia y se prueban teclados.
- `SESION_ABIERTA`: se habilitan votaciones y uso de la palabra.
- Cancelar preparación o cerrar sesión devuelve el sistema a `SIN_PREPARAR`.

El estado operativo es deliberadamente **volátil y en memoria**. Una interrupción técnica no se recupera: reglamentariamente corresponde preparar nuevamente el recinto y abrir una nueva sesión.

## Principios funcionales centrales

- Una sola preparación/sesión activa por vez.
- Una sola votación activa por vez.
- El backend decide toda transición de negocio.
- La presencia la cambia únicamente el dispositivo físico del concejal.
- Cada concejal puede emitir como máximo un voto ordinario por votación y ese voto es irreversible.
- Presidencia es un rol institucional independiente del rol Concejal.
- El voto presidencial de desempate existe solo para mayorías simples empatadas.
- Mayoría simple y mayoría especial son conceptos distintos.
- Las votaciones públicas mantienen secretos los votos individuales hasta el cierre.
- Todas las interacciones relevantes se escriben inmediatamente en tres archivos CSV jerárquicos.
- El Orden del Día es solo una ayuda de carga; no es autoridad para el sistema y no limita qué puede votar el cuerpo.

## Arquitectura técnica base aprobada

SIS-Leg será un **monorepo** con separación entre backend, los dos frontends y el bridge físico.

Decisiones ya cerradas:

- Python 3.14 + `uv`;
- Node.js 24 LTS + `pnpm` workspaces;
- FastAPI con un único proceso/worker y un único estado operativo en memoria;
- API REST nueva versionada bajo `/api/v1`;
- Pydantic/OpenAPI como contrato técnico;
- REST para comandos y snapshots;
- Server-Sent Events (SSE) para actualizaciones backend -> frontend;
- proyecciones separadas `ModerationState` y `PublicState`;
- secreto temporal de votos protegido desde backend.

Ver `docs/12-decisiones-tecnicas.md`.

## Estructura ejecutable

```text
apps/backend/              paquete Python importable; servicio FastAPI
apps/moderacion/           SPA Nuxt 4 de Moderación
apps/recinto/              SPA Nuxt 4 pública
apps/simulador/            SPA Nuxt 4 del simulador visual de dispositivos lógicos (WP-034)
apps/tecnico/              SPA Nuxt 4 del puesto de Apoyo Técnico (WP-056)
services/device-bridge/    paquete Python importable; captura y remapeo físico
packages/api-client/       cliente TypeScript REST/SSE, reconexión y tipos derivados de OpenAPI
packages/frontend-shared/  código frontend compartido
tools/device-simulator/    herramienta CLI de simulación y ejecución de escenarios declarativos
scripts/iniciar_wp.py      lanzador seguro de Work Packages
manual/                    manual de usuario HTML estático servido en /manual/ (WP-067)
config/                    plantillas `*.example.*` versionadas y configuración operativa local ignorada (WP-073)
```

Los paquetes vacíos son límites arquitectónicos deliberados. No contienen
contratos ni reglas funcionales anticipadas.

## Requisitos y bootstrap

- Python 3.14, fijado por `.python-version`;
- `uv`, único gestor de proyectos y dependencias Python;
- Node.js 24 LTS, fijado por `.nvmrc` y `.node-version`;
- pnpm 11, fijado por `packageManager` en `package.json`.

Desde un clon limpio, los dos gestores deben respetar los lockfiles:

```powershell
uv sync --frozen
pnpm install --frozen-lockfile
```

`uv` puede instalar el intérprete requerido con `uv python install 3.14`. En
Node, Corepack o un gestor de versiones puede activar la versión declarada;
`corepack enable` y `corepack install` respetan el `packageManager` versionado.

## Configuración operativa local (WP-073)

Los cuatro archivos que el sistema lee en ejecución **no están versionados**:

```text
config/system.toml
config/concejales.csv
config/apoyo-tecnico/mensajes.csv
services/device-bridge/config/devices.json
```

Son estado real de cada instalación. El repositorio versiona en su lugar una
plantilla por cada uno (`config/system.example.toml`,
`config/concejales.example.csv`, `config/apoyo-tecnico/mensajes.example.csv` y
`services/device-bridge/config/devices.example.json`), que es el contenido que
la revisión ve en cada Pull Request. Así una prueba humana, un remapeo de
hardware o un ajuste de volumen dejan de ensuciar el checkout coordinador y de
bloquear `scripts/iniciar_wp_orca.py`, que sigue exigiendo un checkout limpio
para todo lo que sí es versionable.

Desde un clon nuevo, un único comando materializa los que falten:

```bash
uv run python scripts/preparar_config_local.py   # o: pnpm preparar:config
```

Copia cada plantilla a su ruta operativa **sólo si esa ruta no existe**, crea
los directorios que falten, informa qué creó y qué preservó, y termina con
código distinto de cero ante un fallo real de E/S. Es idempotente y nunca
sobrescribe: `mensajes.csv` lo administra el backend por REST y `devices.json`
lo reescribe el device bridge al remapear, así que ambos contienen trabajo que
no está en ningún commit.

`pnpm dev:stack`, `pnpm dev:stack:hot` y `pnpm test:e2e:integrado` lo ejecutan
solos antes de arrancar. El detalle de cada formato está en
[`config/README.md`](config/README.md).

### Migración de un clon anterior a WP-073

Un clon creado antes de este cambio tiene los cuatro archivos trackeados y
puede tener banderas `skip-worktree` puestas a mano. Adoptar el commit que deja
de trackearlos borraría el contenido local, así que **hay que resguardarlo
antes de actualizar**. Nada de lo que sigue asume que el contenido local sea
igual a la plantilla.

```bash
# 1. Desde la raíz del checkout, respaldar los cuatro archivos FUERA del árbol.
RESPALDO="$HOME/sis-leg-config-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$RESPALDO/config/apoyo-tecnico" "$RESPALDO/services/device-bridge/config"
cp config/system.toml                          "$RESPALDO/config/"
cp config/concejales.csv                       "$RESPALDO/config/"
cp config/apoyo-tecnico/mensajes.csv           "$RESPALDO/config/apoyo-tecnico/"
cp services/device-bridge/config/devices.json  "$RESPALDO/services/device-bridge/config/"

# 2. Comprobar que el respaldo quedó completo antes de seguir.
find "$RESPALDO" -type f

# 3. Retirar banderas skip-worktree heredadas, si las hubiera.
git ls-files -v | grep '^S' || echo 'sin skip-worktree'
git update-index --no-skip-worktree   config/system.toml   config/concejales.csv   config/apoyo-tecnico/mensajes.csv   services/device-bridge/config/devices.json

# 4. Descartar SOLO las modificaciones locales de esos cuatro archivos, ya
#    respaldadas, para que el checkout quede limpio y el pull avance.
git checkout --   config/system.toml   config/concejales.csv   config/apoyo-tecnico/mensajes.csv   services/device-bridge/config/devices.json

# 5. Actualizar main. El commit de WP-073 elimina esas cuatro rutas del índice.
git pull --ff-only origin main

# 6. Restaurar los archivos locales en sus rutas, ahora ignoradas.
mkdir -p config/apoyo-tecnico services/device-bridge/config
cp "$RESPALDO/config/system.toml"                          config/
cp "$RESPALDO/config/concejales.csv"                       config/
cp "$RESPALDO/config/apoyo-tecnico/mensajes.csv"           config/apoyo-tecnico/
cp "$RESPALDO/services/device-bridge/config/devices.json"  services/device-bridge/config/

# 7. Verificar el resultado.
git status --short          # debe quedar vacío
git ls-files config services/device-bridge/config | grep -E 'system|concejales|mensajes|devices'
```

El último comando debe listar únicamente los cuatro `*.example.*`. Si el paso 5
fallara por otros cambios locales no relacionados, resolvelos aparte: la
migración no autoriza `git clean`, `git reset --hard` ni ninguna otra operación
destructiva sobre el resto del árbol.

Conservá el directorio de respaldo hasta comprobar que el sistema arranca con
la configuración esperada.

## Comandos de desarrollo y calidad

Todos los comandos se ejecutan desde la raíz y funcionan igual en PowerShell y
en una terminal POSIX:

```powershell
# Python
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest

# TypeScript, Vue y Nuxt
pnpm lint
pnpm format:check
pnpm typecheck
pnpm test
pnpm test:e2e
pnpm test:e2e:integrado
pnpm build

# Contrato OpenAPI y tipos TypeScript (detección de drift / regeneración)
pnpm check:contrato
pnpm generate:contrato
```

`pnpm build` ejecuta `nuxt generate` para ambos frontends. Los artefactos
estáticos quedan en `apps/moderacion/.output/public` y
`apps/recinto/.output/public`; no requieren un servidor Node en producción.
Para desarrollo interactivo existen `pnpm dev:moderacion` y
`pnpm dev:recinto`; cada servidor conserva su subruta canónica
(`/moderacion/` y `/recinto/`, respectivamente).

## Entornos integrados de desarrollo

Existen dos modos de desarrollo integrado bajo el mismo origen, según el objetivo de trabajo:

```text
pnpm dev:stack      -> build estático + FastAPI; harness reproducible sin hot reload
pnpm dev:stack:hot  -> servidores de desarrollo Nuxt/Vite + HMR + autoreload backend
```

### 1. Modo estático reproducible (`pnpm dev:stack`)

Construye las cuatro SPA y después mantiene en primer plano un único servidor Uvicorn con la aplicación FastAPI real. Es el harness reproducible que valida los artefactos estáticos tal como se servirán en producción:

```bash
git pull --ff-only origin main
pnpm install --frozen-lockfile
uv sync --frozen --all-packages
pnpm dev:stack
```

Escucha por defecto en `127.0.0.1:8000` y expone:

- `http://127.0.0.1:8000/moderacion/`
- `http://127.0.0.1:8000/recinto/`
- `http://127.0.0.1:8000/simulador/`
- `http://127.0.0.1:8000/tecnico/`
- `http://127.0.0.1:8000/manual/`
- `http://127.0.0.1:8000/api/v1/health`
- `http://127.0.0.1:8000/docs`

No hay mocks, CORS, servidor Node persistente ni recuperación de estado. Al no usar servidores de desarrollo, no ofrece recarga en caliente (HMR).

### 2. Modo interactivo con hot reload sobre main (`pnpm dev:stack:hot`)

Destinado al checkout coordinador de la rama `main`. Coordina en primer plano los servidores Nuxt/Vite en modo desarrollo con Hot Module Replacement (HMR) para las cuatro SPA, el backend FastAPI con recarga automática por Uvicorn, y un reverse proxy interno que preserva el contrato de mismo origen en un único puerto loopback:

```bash
git checkout main
git pull --ff-only origin main
pnpm dev:stack:hot
```

#### Flujo operativo tras un merge

1. Iniciar `pnpm dev:stack:hot` una vez en el checkout coordinador de `main`.
2. Mantener abierto el túnel SSH y las pestañas de Moderación, Recinto, Simulador y Apoyo Técnico.
3. Al integrarse un nuevo Work Package en GitHub, ejecutar en otra terminal:
   ```bash
   git pull --ff-only origin main
   ```
4. Los watchers detectan los archivos actualizados y Vite propaga los cambios por HMR a las cuatro SPA sin necesidad de ejecutar `pnpm build`, sin recargar la página (`Ctrl+F5`) y sin reiniciar el stack.
5. Si el cambio afectó código Python del backend (`apps/backend/src`), Uvicorn reinicia automáticamente el proceso FastAPI. Como el estado institucional es deliberadamente volátil en memoria, el sistema vuelve a `SIN_PREPARAR`. Modificaciones en archivos de configuración no Python (`config/*.toml` o `config/*.csv`) requieren reiniciar el stack manualmente porque el reloader estándar de Uvicorn vigila exclusivamente archivos Python. Esos archivos son los operativos locales descritos en «Configuración operativa local (WP-073)», no las plantillas versionadas.
6. Para detener todo el árbol de procesos y liberar los puertos auxiliares, presionar `Ctrl+C`.

> **Nota para pruebas del WP**: El comando rechaza ejecutarse si el checkout no está en la rama `main`. Para validar el propio candidato en ramas de desarrollo se admite la excepción explícita `--allow-non-main` (ej. `pnpm dev:stack:hot --allow-non-main`). Esta opción no debe usarse como flujo habitual.

### Acceso desde Windows

Conservá `pnpm dev:stack` ejecutándose en `agent-dev` y abrí otra terminal de
Windows con el túnel SSH existente:

```powershell
ssh -N -L 18080:127.0.0.1:8000 agent-dev
```

Luego abrí en dos pestañas
`http://127.0.0.1:18080/moderacion/` y
`http://127.0.0.1:18080/recinto/`. Swagger queda disponible en
`http://127.0.0.1:18080/docs`. El túnel no publica un puerto nuevo en el VPS:
transporta el loopback del contenedor por la conexión SSH existente.

### Recorrido manual recomendado

1. En Moderación, elegí `Preparar recinto` e informá número de sesión,
   Presidencia y Secretaría Legislativa.
2. En otra terminal de `agent-dev`, iniciá el simulador real:

   ```bash
   uv run python tools/device-simulator/simulador.py --url http://127.0.0.1:8000
   ```

3. En el simulador, enviá `1-9` para alternar la presencia de `dev01` y `1-8`
   para activar su test visual. Repetí presencia con otros dispositivos hasta
   alcanzar quórum y comprobá los cambios en Moderación y Recinto.
4. Abrí la sesión desde Moderación. Usá `1-7` para pedir palabra, otorgala desde
   Moderación y volvé a usar `1-7` para finalizarla desde el dispositivo.
5. Confirmá que ambas pestañas adoptan los cambios por SSE. Las votaciones ya
   disponibles pueden recorrerse desde Moderación, aunque su experiencia
   pública completa pertenece a un WP posterior.
6. Presioná `Ctrl+C` en la terminal del stack. El proceso debe terminar y
   liberar el puerto. Al ejecutar nuevamente `pnpm dev:stack`, Moderación y
   Recinto deben volver a mostrar `SIN_PREPARAR`.

Los CSV de esta prueba se escriben en `logs/`, permanecen locales e ignorados
por Git. El harness no borra registros anteriores automáticamente.

### E2E frontend y E2E integrado

Hay dos suites Playwright con propósitos distintos:

- `pnpm test:e2e` verifica de forma rápida y determinista los shells frontend
  con servidores Nuxt y respuestas controladas. No necesita Python.
- `pnpm test:e2e:integrado` construye las cuatro SPA, inicia el FastAPI real en
  `127.0.0.1:18027` y recorre REST, SSE, Moderación, Recinto, Simulador, Apoyo Técnico y
  la CLI real del simulador. También reinicia el backend para comprobar que la nueva baseline
  vuelve a `SIN_PREPARAR` con revisión 0.

La suite integrada requiere los mismos Python, uv, Node, pnpm y lockfiles del
proyecto, además de Chromium instalado para Playwright. En una instalación
nueva ejecutá primero:

```powershell
uv sync --frozen --all-packages
pnpm install --frozen-lockfile
pnpm exec playwright install chromium
pnpm test:e2e:integrado
```

Los recorridos integrados son seriales porque comparten un único estado
institucional en memoria. El runner controla solamente el proceso que crea,
verifica readiness y liberación del puerto, y conserva trace, screenshot, video
y salida del stack ante un fallo. Los CSV permanecen en `logs/`, ignorados por
Git, para poder inspeccionar la auditoría real sin que una segunda ejecución
dependa de borrar residuos de la primera.

## Artefacto productivo

Desde un checkout limpio y confirmado, el comando:

```bash
pnpm empaquetar:produccion
```

construye las cuatro SPA y deja en `dist/produccion/` un
`sis-leg-<sha-completo>.tar.gz` junto con su sidecar `.sha256`. El paquete
contiene fuentes runtime Python, lockfiles, frontends ya compilados, el manual
de usuario, `release.json`, unidades systemd, configuración Nginx y la
herramienta de despliegue; no contiene configuración institucional, logs,
`node_modules`, Git ni una venv construida en desarrollo.

El procedimiento administrativo de primera instalación, actualización,
rollback y diagnóstico está documentado en
[`docs/13-despliegue-y-operacion.md`](docs/13-despliegue-y-operacion.md). Crear
el artefacto no despliega ni modifica ningún host.

## Manual de usuario

`manual/index.html` es el manual de operación, configuración e instalación de SIS-Leg. Es
un único documento HTML autocontenido: no carga hojas de estilo, scripts, tipografías ni
imágenes externas, de modo que se lee igual en una instalación sin salida a Internet.

Se publica siempre en la misma dirección de mismo origen, `/manual/`:

- en producción lo sirve Nginx desde `web/manual/` dentro de la release;
- `pnpm dev:stack` lo monta desde `manual/`;
- `pnpm dev:stack:hot` lo sirve directamente desde el repositorio.

El icono de ayuda del extremo derecho de las cabeceras de Moderación y de Apoyo Técnico lo
abre en una pestaña nueva. Ese acceso es un único componente compartido,
`packages/frontend-shared/src/componentes/AccesoManual.vue`, para que las dos pantallas no
puedan divergir.

`tests/test_manual_usuario.py` comprueba automáticamente que estén los trece capítulos,
que ningún enlace interno quede roto, que no aparezca ningún recurso externo, que las
rutas de archivos citadas sigan existiendo y que el contenido no particularice ninguna
institución.

## Inicio aislado de un Work Package

Después de que una persona apruebe el WP, lo marque `EN_CURSO` en
`docs/implementation/PLAN.md` y asigne un agente, ejecutá desde el checkout
coordinador limpio en `main`:

### En entorno Orca (Orca Desktop / VPS / Host Linux)

```powershell
uv run python scripts/iniciar_wp_orca.py 030 antigravity
uv run python scripts/iniciar_wp_orca.py 002 codex
uv run python scripts/iniciar_wp_orca.py 015 claude
uv run python scripts/iniciar_wp_orca.py 016 opencode
```

El lanzador de Orca valida el estado del runtime de Orca, el registro del
repositorio coordinador, la aprobación documental y el estado de Git, y delega en
`orca worktree create` la creación del workspace aislado y el inicio del agente
en una terminal administrada por Orca.

### En entorno genérico (Terminal estándar / SSH / Warp)

```powershell
uv run python scripts/iniciar_wp.py 002 codex
uv run python scripts/iniciar_wp.py 015 claude
uv run python scripts/iniciar_wp.py 016 opencode
uv run python scripts/iniciar_wp.py 030 antigravity
```

El lanzador genérico hace `fetch`, permite actualizar `main` solo por fast-forward,
valida aprobación, estado, agente y dependencias, y crea una rama
`wp/NNN-descripcion` en un worktree hermano `SIS-Leg-wpNNN`. Si la relación
rama/worktree ya es inequívocamente la misma, la reutiliza. Para el agente `antigravity`,
mapea a la CLI `agy` (o `antigravity`). Ante una CLI ausente o un conflicto se
detiene sin borrar ni reparar trabajo.

Ambos scripts no aprueban WPs, no editan el PLAN, no crean commits ni PRs, no integran
cambios y no despliegan. WP-001 fue la única excepción preparada manualmente.

## Herramientas MCP estándar para agentes

Los MCP son herramientas del entorno del agente, no dependencias del producto.
DEC-003 asigna estas responsabilidades:

- **Context7:** documentación externa actual y específica de versión;
- **Nuxt MCP:** referencia oficial preferente para Nuxt 4;
- **Playwright MCP:** exploración del navegador complementaria a tests
  Playwright versionados;
- **GitHub MCP o integración equivalente:** contexto y operaciones sobre
  GitHub únicamente dentro de la autoridad ya aprobada.

Antes de depender de una herramienta, comprobá el inventario y su estado:

```powershell
codex mcp list
claude mcp list
opencode mcp list
```

La sintaxis puede evolucionar; verificá también `mcp --help` en cada CLI y la
documentación primaria enlazada abajo. Ejemplos orientativos de configuración
personal, que **no deben copiarse al repositorio**, son:

```powershell
# Codex: servidor local y servidor HTTP remoto
codex mcp add context7 -- npx -y @upstash/context7-mcp
codex mcp add nuxt --url https://nuxt.com/mcp

# Claude Code: configuración de usuario para un servidor HTTP
claude mcp add --scope user --transport http nuxt https://nuxt.com/mcp

# OpenCode: agregar/listar servidores según la versión instalada
opencode mcp --help
opencode mcp list
```

En OpenCode también se puede declarar un servidor local o remoto bajo `mcp`
en la configuración personal. Usá sustituciones de variables de entorno para
tokens; nunca escribas el valor del secreto en un JSON versionado. Playwright
MCP y GitHub requieren revisar primero el servidor oficial, los permisos y el
método de autenticación apropiado para el entorno.

Fuentes primarias vigentes para completar o ajustar la configuración:

- [MCP en Codex](https://learn.chatgpt.com/docs/extend/mcp?surface=cli);
- [MCP en Claude Code](https://docs.claude.com/en/docs/mcp);
- [MCP en OpenCode](https://opencode.ai/docs/mcp-servers/);
- [Nuxt MCP](https://nuxt.com/mcp);
- [Playwright MCP](https://github.com/microsoft/playwright-mcp);
- [GitHub MCP Server](https://github.com/github/github-mcp-server).

Si un MCP necesario no está disponible, el agente debe avisar qué herramienta
falta, para qué se necesitaba, qué alternativa primaria/equivalente existe y
qué impacto tiene continuar. Solo puede seguir si el fallback no cambia
arquitectura, alcance, contratos ni pruebas y no obliga a adivinar una API. La
configuración personal (`~/.codex/config.toml` y equivalentes), API keys,
tokens, cookies y credenciales nunca se versionan.

## Lectura obligatoria para agentes

Para un WP normal, seguí el flujo acotado definido por `AGENTS.md`:

1. leer `AGENTS.md`;
2. leer el `docs/work-packages/WP-XXX.md` asignado;
3. leer solo las fuentes canónicas y secciones que ese WP declare;
4. leer las decisiones transversales obligatorias vigentes;
5. inspeccionar únicamente el código y las pruebas necesarios para el alcance.

Una auditoría global, una planificación transversal o la resolución de una
contradicción documental pueden requerir el conjunto más amplio de fuentes que
enumera `AGENTS.md`.

## Estado actual

WP-001 incorpora el scaffold ejecutable y reproducible del monorepo. Todavía no
existen reglas de negocio, endpoints funcionales, conexión con dispositivos ni
datos institucionales: esos resultados pertenecen a Work Packages posteriores.
