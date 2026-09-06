# @sis-leg/api-client

Paquete TypeScript compartido del monorepo SIS-Leg que encapsula la comunicación con el backend FastAPI mediante REST y Server-Sent Events (SSE).

## Principios y responsabilidades

1. **Fuente de verdad única**: Los esquemas y modelos de datos provienen exclusivamente de FastAPI/Pydantic vía OpenAPI. No se duplican DTOs manualmente en TypeScript.
2. **Superficies separadas por rol**:
   - `ClienteModeracion`: expone lectura/sincronización y todos los comandos mutantes para el operador único (preparación, sesión, votación, palabra, orden del día).
   - `ClienteRecinto`: superficie estrictamente de solo lectura para la Pantalla del Recinto. El compilador de TypeScript impide invocar métodos mutantes desde este cliente.
3. **Transporte nativo**: Utiliza `fetch` y `EventSource` web nativos, con soporte para inyección de dependencias en pruebas unitarias.
4. **Ciclo de sincronización y baseline**:
   - **Snapshot inicial antes de SSE**: Siempre se obtiene un snapshot REST completo antes de abrir el stream de eventos.
   - **Nueva baseline tras reinicio**: Cada snapshot adoptado inicia una nueva baseline. Esto permite que si el backend reinicia y vuelve a `revision: 0` en `SIN_PREPARAR`, el cliente descarte el estado previo (ej. `revision: 142`) y adopte la nueva versión válida.
   - **Reconexión controlada**: Ante un error SSE, se cierra la instancia fallada de inmediato para evitar la reconexión automática nativa sin snapshot, se aplica una espera de backoff acotada y cancelable, se recupera el estado por snapshot REST y se abre una nueva conexión SSE.

---

## Estructura del paquete

```text
packages/api-client/
├── openapi/
│   └── openapi.json         # Snapshot OpenAPI versionado
├── src/
│   ├── esquema.ts           # Tipos TypeScript generados por openapi-typescript
│   ├── tipos.ts             # Tipos y contratos propios derivados de components["schemas"]
│   ├── errores.ts           # Jerarquía discriminada de errores (ErrorHttp, ErrorTransporte, etc.)
│   ├── rest.ts              # Cliente REST base con serialización JSON, 204 y multipart
│   ├── sincronizador.ts     # Motor de sincronización SSE, baseline, revisión y recovery
│   ├── backoff.ts           # Estrategia de retroceso exponencial acotado y cancelable
│   ├── event_source.ts      # Fábrica de EventSource nativo / inyectable
│   ├── moderacion.ts        # ClienteModeracion con comandos y sincronización
│   ├── recinto.ts           # ClienteRecinto de solo lectura
│   └── index.ts             # Exportaciones públicas del paquete
├── tests/                   # Pruebas unitarias con Vitest
├── package.json
└── tsconfig.json
```

---

## Comandos de generación y verificación de contrato

### 1. Regenerar OpenAPI y tipos TypeScript

```bash
# Desde la raíz del repositorio:
pnpm generate:contrato

# O por separado:
pnpm generate:openapi   # uv run python scripts/exportar_openapi.py
pnpm generate:types     # openapi-typescript openapi/openapi.json -o src/esquema.ts
```

### 2. Verificar drift (detección automática en CI)

```bash
# Comprueba que el backend FastAPI coincide con el snapshot y este con los tipos TS:
pnpm check:contrato

# O por separado:
pnpm check:openapi      # uv run python scripts/exportar_openapi.py --check
pnpm check:types        # pnpm --filter @sis-leg/api-client check:types
```

---

## Uso básico

### Cliente de Moderación

```typescript
import { crearClienteModeracion } from "@sis-leg/api-client";

const cliente = crearClienteModeracion({ baseUrl: "http://localhost:8000" });

// 1. Obtener snapshot puntual
const estado = await cliente.obtenerEstado();
console.log("Estado global actual:", estado.estado_global);

// 2. Ejecutar comandos
await cliente.prepararSala();
await cliente.abrirVotacion({
  numero_votacion: 1,
  tipo: "General",
  tema: "Proyecto de Ordenanza",
  tipo_mayoria: "SIMPLE",
  base: "VOTOS_COMPUTABLES",
});

// 3. Sincronización reactiva en tiempo real (Snapshot + SSE)
const suscripcion = cliente.suscribirEstado({
  alEstado: (nuevoEstado) => {
    console.log("Revisión recibida:", nuevoEstado.revision);
  },
  alError: (error) => {
    console.error("Error de sincronización:", error);
  },
  alCambiarConexion: (conectado) => {
    console.log("Estado del stream SSE:", conectado ? "conectado" : "desconectado");
  },
});

// Para detener la sincronización de forma limpia:
suscripcion.cancelar();
```

### Cliente de Recinto

```typescript
import { crearClienteRecinto } from "@sis-leg/api-client";

const recinto = crearClienteRecinto({ baseUrl: "http://localhost:8000" });

// Solo lectura: no expone métodos mutantes
const estadoPublico = await recinto.obtenerEstado();

const suscripcion = recinto.suscribirEstado({
  alEstado: (publico) => {
    console.log("Bancas presentes:", publico.quorum?.cantidad_presentes);
  },
});
```

---

## Modelo de Errores

Todos los errores lanzados por el cliente heredan de `ErrorApi` y poseen un discriminante `tipo`:

- **`ErrorHttp`** (`tipo: "HTTP"`):
  - `estado`: código HTTP (ej. 409, 422, 500, 503).
  - `codigo`: código de dominio backend (ej. `"QUORUM_INSUFICIENTE"`, `"ESTADO_INCOMPATIBLE"`), si el backend respondió `{ codigo, mensaje }`.
  - `mensajeBackend`: texto legible enviado por el backend.
  - `detalle`: información estructurada adicional (ej. errores de validación 422).
- **`ErrorTransporte`** (`tipo: "TRANSPORTE"`): fallas de red o socket cerrado.
- **`ErrorProtocolo`** (`tipo: "PROTOCOLO"`): JSON malformado o cuerpo no acorde al contrato.
- **`ErrorCancelacion`** (`tipo: "CANCELACION"`): abortos voluntarios o invocación de `cancelar()`.
