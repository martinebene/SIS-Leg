# 00 - Principios y alcance

## 1. Producto

SIS-Leg es el sistema que asiste la preparación, desarrollo, votación, uso de la palabra y registro electrónico de una sesión de un cuerpo legislativo.

El sistema no está atado a una institución concreta: el nombre del cuerpo legislativo que opera cada instalación se declara en la sección `[institucion]` de `config/system.toml` y es lo que muestra la cabecera de la Pantalla del Recinto (WP-084).

No reemplaza la documentación oficial del cuerpo ni interpreta su contenido. Su función es gestionar interacciones operativas y registrar lo ocurrido.

## 2. Actores y superficies

### Moderación

Operador único, sin identificación individual en esta versión. Utiliza el frontend de Moderación para:

- preparar/cancelar recinto;
- indicar número de sesión;
- informar Presidencia y Secretaría Legislativa;
- abrir/cerrar sesión;
- cargar Orden del Día como asistencia;
- abrir/finalizar votaciones;
- resolver desempates presidenciales;
- otorgar/quitar palabra;
- cambiar Presidencia o Secretaría;
- visualizar estado y eventos;
- ejecutar, en el futuro, remapeo rápido de dispositivos.

### Concejales

Interactúan exclusivamente mediante sus dispositivos físicos para:

- acreditar/retirar presencia;
- probar el dispositivo;
- pedir/retirar palabra o terminar su propio uso;
- emitir voto ordinario cuando corresponda.

Moderación no puede acreditar presencia ni votar en nombre de un concejal.

### Presidencia

Rol institucional independiente de cualquier eventual rol de Concejal de la persona que lo ejerza.

El sistema solo necesita saber quién preside y permitir el voto extraordinario de desempate cuando una mayoría simple termina empatada.

### Secretaría Legislativa

Rol institucional informativo. Debe identificarse y sus cambios registrarse, pero no ejecuta acciones funcionales dentro de SIS-Leg.

### Pantalla del Recinto

Frontend público y de solo lectura. Informa el estado de sesión, presencia, votaciones, uso de palabra y eventos aptos para exposición pública sin vulnerar el secreto temporal de votos individuales.

### Bridge de dispositivos

Servicio separado que traduce entradas físicas a identificadores lógicos y las entrega al backend. No decide reglas de negocio.

## 3. Componentes objetivo

- Backend: FastAPI.
- Moderación: Nuxt.js.
- Pantalla del Recinto: Nuxt.js.
- Bridge físico: componente separado del backend.

Las decisiones técnicas concretas aún pendientes se concentran en `10-preguntas-abiertas.md`.

## 4. Autoridad de estado

El backend es la única autoridad sobre el estado funcional.

Los frontends no deben inferir ni aplicar reglas reglamentarias localmente. Pueden mantener únicamente estado de presentación que no cambie el resultado funcional.

## 5. Ciclo global

Únicos estados globales:

`SIN_PREPARAR -> PREPARANDO -> SESION_ABIERTA -> SIN_PREPARAR`

### SIN_PREPARAR

- No hay padrón operativo cargado.
- No hay interacción funcional con teclados.
- No existen archivos CSV de sesión/preparación activos.

### PREPARANDO

- Se carga configuración y padrón.
- Todos los concejales comienzan ausentes.
- Se informan Presidencia y Secretaría Legislativa.
- Se crean los tres CSV.
- Se habilitan presencia (`9`) y test (`8`).
- No hay voto ni uso de palabra.
- La sesión solo puede abrirse cuando haya quórum y estén completos número y autoridades.

### SESION_ABIERTA

- Continúa dinámica la presencia.
- Se habilitan votaciones y uso de palabra.
- Las autoridades pueden cambiar en cualquier momento.
- Al cerrar se vuelve a `SIN_PREPARAR`.

Cancelar `PREPARANDO` también vuelve a `SIN_PREPARAR`.

## 6. Volatilidad deliberada

El estado operativo se conserva solamente en memoria.

Una caída del backend durante preparación o sesión provoca pérdida del estado. Al reiniciar se vuelve a `SIN_PREPARAR`.

Esto es intencional: ante una interrupción técnica de una sesión, el reglamento exige preparar nuevamente el recinto y abrir una nueva sesión; las presencias no deben suponerse iguales a las anteriores.

Los CSV persistidos hasta la caída permanecen como evidencia histórica y no se modifican retrospectivamente.

## 7. Documentación oficial externa

Número de sesión, número de votación, contenido y orden del Orden del Día son responsabilidad de la documentación oficial/física del Concejo.

SIS-Leg:

- recibe esos datos;
- no valida secuencia ni unicidad;
- no decide si el contenido es correcto;
- permite votar asuntos fuera del Orden del Día;
- permite alterar el orden práctico de tratamiento;
- registra exactamente las acciones realizadas.

## 8. Fuente histórica

Para extraer el comportamiento vigente se utilizó el código de `martinebene/Botonera`, rama `main`.

La implementación histórica no define la arquitectura futura. Solo conserva valor como fuente de assets, compatibilidad física y validación puntual documentada.