/**
 * Soporte compartido de las pruebas de navegador del plano de Apoyo Técnico.
 *
 * Estas piezas nacieron dentro del E2E de WP-056 y WP-060 las necesita también: la
 * regresión geométrica de los avisos debe medirse sobre las mismas superficies reales de
 * Moderación y del Recinto, con el mismo doble determinista del backend. Se extraen a un
 * módulo propio para que las dos pruebas compartan un único estado de referencia en lugar
 * de mantener dos copias que puedan divergir en silencio.
 *
 * El archivo no declara pruebas: Playwright sólo ejecuta los `*.spec.ts`, así que este
 * módulo es exclusivamente biblioteca.
 */

import { expect, type Page } from '@playwright/test'

export const URL_TECNICO = 'http://localhost:3003/tecnico/'
export const URL_RECINTO = 'http://localhost:3001/recinto/'
export const URL_MODERACION = 'http://localhost:3000/moderacion/'

export const RESOLUCIONES = [
  { width: 1920, height: 1080 },
  { width: 1366, height: 768 },
] as const

/**
 * Resoluciones objetivo de Moderación y del Recinto desde WP-097.
 *
 * HUMAN_GATE probó las dos superficies de sesión en un monitor de 1280×720 y
 * pidió que funcionen completas también ahí, sin perder nada en las mayores. La
 * lista es propia y no amplía `RESOLUCIONES` a propósito: el puesto de Apoyo
 * Técnico es otra superficie, con su propio alcance y sus propios WPs, y WP-097
 * no fue autorizado a modificarla.
 */
export const RESOLUCIONES_SESION = [
  { width: 1920, height: 1080 },
  { width: 1366, height: 768 },
  { width: 1280, height: 720 },
] as const

// =============================================================================
// Fábricas de estado
// =============================================================================

export function transmision(parcial: Record<string, unknown> = {}) {
  return {
    estado: 'APAGADO',
    iniciada_en: null,
    en_vivo_desde: null,
    cuenta_regresiva_segundos: null,
    segundos_restantes: null,
    ...parcial,
  }
}

export function aviso(texto: string, destino: string) {
  return {
    aviso_id: 'aviso-e2e',
    texto,
    destino,
    publicado_en: '2026-09-02T10:00:00Z',
    expira_en: null,
    segundos_restantes: null,
  }
}

/**
 * Configuración de audio del Recinto, tal como la proyecta el backend desde WP-065.
 *
 * Viaja en todos los snapshots públicos, así que las fixtures del navegador también deben
 * traerla: sin ella la Pantalla del Recinto no tendría ruta ni volumen que reproducir.
 * Los volúmenes son los de `config/system.toml`, para que el E2E compruebe exactamente el
 * valor configurado y no uno inventado por la prueba.
 */
export function sonidosRecinto() {
  const volumenes: Record<string, number> = {
    preparacion_iniciada: 70,
    aviso_tecnico_publicado: 75,
    aviso_tecnico_retirado: 60,
    pedido_palabra_registrado: 65,
    pedido_palabra_retirado: 55,
    uso_palabra_otorgado: 75,
    transmision_iniciada: 80,
    transmision_detenida: 70,
    transmision_cuenta_regresiva_tic: 35,
    sesion_abierta: 90,
    sesion_cerrada: 85,
    votacion_abierta: 85,
    votacion_cerrada: 80,
    concejal_ausente: 50,
    concejal_presente: 55,
  }
  return {
    disponible: true,
    motivo: null,
    detalle: null,
    sonidos: Object.entries(volumenes).map(([evento, volumen]) => ({
      evento,
      ruta: `assets/sonidos/${evento.replaceAll('_', '-')}.wav`,
      volumen,
    })),
  }
}

/**
 * Nombre institucional de las fixtures de navegador (WP-084).
 *
 * El backend real lo toma de `[institucion]` en `system.toml`; acá se fija un
 * nombre de fantasía para que las pruebas puedan afirmar que la cabecera muestra
 * *exactamente* el valor configurado y no un texto escrito en la plantilla.
 */
export const NOMBRE_INSTITUCIONAL_E2E = 'Cuerpo Legislativo de Ciudad Ejemplo'

export function identidadInstitucional(nombre: string = NOMBRE_INSTITUCIONAL_E2E) {
  return { nombre }
}

export function concejalesPublicos(cantidad: number) {
  return Array.from({ length: cantidad }, (_, indice) => {
    const banca = indice + 1
    return {
      nombre: `Nombre${banca}`,
      apellido: `Apellido${banca}`,
      bloque: banca % 2 === 0 ? 'Bloque Azul' : 'Bloque Verde',
      banca,
      ruta_imagen: `assets/bancas/banca-${String(banca).padStart(2, '0')}.png`,
      presente: true,
      test_activo: false,
      test_expira_en: null,
    }
  })
}

/**
 * Votación pública ya cerrada, con conteos y resultado visibles.
 *
 * Es el peor caso de la franja superior del Recinto: los tres renglones traen
 * texto, el del estado trae además la píldora del resultado y el detalle de
 * conteos, y el tema es largo. Sirve para comprobar que la tipografía ampliada de
 * WP-097 entra en la franja sin desbordarla ni ganar scroll.
 */
export function votacionPublicaCerrada(parcial: Record<string, unknown> = {}) {
  return {
    id: 'votacion-geometria',
    numero_votacion: 12,
    tipo: 'Despacho de comisión',
    tema: 'Expediente 1234/2026 — Ordenanza de presupuesto general del ejercicio siguiente',
    tipo_mayoria: 'ESPECIAL',
    factor: 0.6666,
    base: 'PRESENTES',
    estado_recepcion: 'CERRADA',
    resultado: 'APROBADA',
    fecha_hora_apertura: '2026-09-02T09:58:00Z',
    fecha_hora_cierre: '2026-09-02T09:59:30Z',
    cuenta_regresiva_hasta: null,
    resultado_visible_hasta: null,
    bancas_voto_emitido: null,
    votos_individuales: null,
    conteos: { positivos: 8, negativos: 3, abstenciones: 1, total: 12 },
    voto_presidencial: null,
    ...parcial,
  }
}

export function estadoRecinto(parcialTecnico: Record<string, unknown> = {}) {
  return {
    instancia: 'instancia-prueba',
    revision: 1,
    generado_en: '2026-09-02T10:00:00Z',
    estado_global: 'SESION_ABIERTA',
    preparacion: null,
    sesion: {
      fecha_hora_inicio_preparacion: '2026-09-02T09:00:00Z',
      fecha_hora_apertura: '2026-09-02T09:30:00Z',
      numero_sesion: 56,
      presidencia: 'Presidencia',
      secretaria_legislativa: 'Secretaría',
    },
    filas_bancas: [6, 6],
    concejales: concejalesPublicos(12),
    quorum: { cantidad_presentes: 12, requerido: 7, alcanzado: true },
    votacion: null,
    palabra: {
      orador: null,
      cola: Array.from({ length: 4 }, (_, indice) => ({
        nombre: `Solicitante${indice + 1}`,
        apellido: `ApellidoMuyLargoParaProbarElipsis${indice + 1}`,
        banca: indice + 1,
      })),
    },
    eventos_publicos: [],
    tecnico: { transmision: transmision(), aviso: null, ...parcialTecnico },
    sonidos: sonidosRecinto(),
    institucion: identidadInstitucional(),
  }
}

/**
 * Allowlist de remapeo que viaja dentro del estado técnico desde WP-074.
 *
 * Antes esta información llegaba a la SPA técnica en un `EstadoModeracion` completo, por una
 * suscripción propia. Ahora es una porción del mismo snapshot, y el doble determinista del
 * navegador tiene que reflejarlo para que el panel se dibuje igual que en producción.
 */
export function remapeoTecnico(parcial: Record<string, unknown> = {}) {
  const habilitada = { habilitada: true, motivos: [] as string[] }
  return {
    remapeo: null,
    concejales: Array.from({ length: 12 }, (_, indice) => ({
      dni: `1000000${indice}`,
      nombre: `Nombre${indice + 1}`,
      apellido: `Apellido${indice + 1}`,
      banca: indice + 1,
      dispositivo_votacion: `dev${String(indice + 1).padStart(2, '0')}`,
    })),
    capacidades: {
      iniciar_remapeo: habilitada,
      confirmar_remapeo: { habilitada: false, motivos: ['REMAPEO_NO_COINCIDE'] },
      cancelar_remapeo: { habilitada: false, motivos: ['REMAPEO_NO_COINCIDE'] },
    },
    ...parcial,
  }
}

/**
 * Subproyección sonora del estado técnico (WP-074).
 *
 * Contiene exactamente los campos que compara el detector de transiciones: es la misma
 * información con la que sonoriza el Recinto, recortada a bancas e identidades de votación.
 */
export function sonorizacionTecnica(parcial: Record<string, unknown> = {}) {
  return {
    revision: 1,
    estado_global: 'SESION_ABIERTA',
    tecnico: { transmision: transmision(), aviso: null },
    palabra: { cola: [], orador: null },
    votacion: null,
    concejales: concejalesPublicos(12).map((concejal) => ({
      banca: concejal.banca,
      presente: concejal.presente,
    })),
    sonidos: sonidosRecinto(),
    ...parcial,
  }
}

export function estadoTecnico(parcial: Record<string, unknown> = {}) {
  return {
    instancia: 'instancia-prueba',
    revision: 1,
    generado_en: '2026-09-02T10:00:00Z',
    estado_global: 'SESION_ABIERTA',
    transmision: transmision(),
    aviso_moderacion: null,
    aviso_recinto: null,
    remapeo: remapeoTecnico(),
    sonorizacion: sonorizacionTecnica(),
    biblioteca: {
      disponible: true,
      motivo: null,
      detalle: null,
      mensajes: [
        { mensaje_id: 'm-1', texto: 'Cuarto intermedio', destino: 'AMBOS' },
        { mensaje_id: 'm-2', texto: 'Prueba de sonido', destino: 'RECINTO' },
      ],
    },
    eventos_recientes: Array.from({ length: 25 }, (_, indice) => ({
      seq: indice + 1,
      timestamp: `2026-09-02 09:59:${String(indice).padStart(2, '0')}`,
      nivel: indice % 3 === 0 ? 'L3' : indice % 3 === 1 ? 'L2' : 'L1',
      etiqueta: 'SESION',
      codigo_evento: `EVENTO_${indice + 1}`,
      mensaje: `Mensaje del evento ${indice + 1}`,
      hecho: null,
    })),
    auditoria: { activa: true, disponible: true, fallado: false, cerrado: false, motivo: null },
    ...parcial,
  }
}

export function estadoModeracion(parcialTecnico: Record<string, unknown> = {}) {
  return {
    instancia: 'instancia-prueba',
    revision: 1,
    generado_en: '2026-09-02T10:00:00Z',
    estado_global: 'SESION_ABIERTA',
    preparacion: null,
    sesion: {
      fecha_hora_inicio: '2026-09-02T09:00:00Z',
      fecha_hora_apertura: '2026-09-02T09:30:00Z',
      numero_sesion: 56,
      presidencia: 'Presidencia',
      secretaria_legislativa: 'Secretaría',
    },
    configuracion: {
      total_bancas: 12,
      filas_bancas: [6, 6],
      modo_seguro: true,
      mayoria_simple_estricta: true,
    },
    concejales: Array.from({ length: 12 }, (_, indice) => ({
      nombre: `Nombre${indice + 1}`,
      apellido: `Apellido${indice + 1}`,
      bloque: 'Bloque',
      banca: indice + 1,
      dni: `1000000${indice}`,
      dispositivo_votacion: `dev${String(indice + 1).padStart(2, '0')}`,
      ruta_imagen: `assets/bancas/banca-${String(indice + 1).padStart(2, '0')}.png`,
      presente: true,
      test_activo: false,
      test_expira_en: null,
    })),
    quorum: { cantidad_presentes: 12, requerido: 7, alcanzado: true },
    votacion: null,
    palabra: { orador: null, cola: [] },
    orden_del_dia: null,
    eventos_recientes: Array.from({ length: 20 }, (_, indice) => ({
      seq: indice + 1,
      timestamp: `2026-09-02 09:59:${String(indice).padStart(2, '0')}`,
      nivel: 'L3',
      etiqueta: 'SESION',
      codigo_evento: `EVENTO_${indice + 1}`,
      mensaje: `Mensaje del evento ${indice + 1}`,
      hecho: null,
    })),
    auditoria: { activa: true, disponible: true, fallado: false, cerrado: false, motivo: null },
    remapeo: null,
    capacidades: {
      preparar_sala: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      cancelar_preparacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      abrir_sesion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      cerrar_sesion: { habilitada: true, motivos: [] },
      editar_autoridades: { habilitada: true, motivos: [] },
      abrir_votacion: { habilitada: true, motivos: [] },
      finalizar_votacion: { habilitada: false, motivos: ['VOTACION_NO_EN_CURSO'] },
      desempatar_votacion: { habilitada: false, motivos: ['VOTACION_NO_EMPATADA'] },
      otorgar_palabra: { habilitada: false, motivos: ['COLA_VACIA'] },
      quitar_palabra: { habilitada: false, motivos: ['COLA_VACIA'] },
      cargar_orden_del_dia: { habilitada: true, motivos: [] },
      descartar_orden_del_dia: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      iniciar_remapeo: { habilitada: true, motivos: [] },
      confirmar_remapeo: { habilitada: false, motivos: ['REMAPEO_NO_COINCIDE'] },
      cancelar_remapeo: { habilitada: false, motivos: ['REMAPEO_NO_COINCIDE'] },
      registrar_evento_manual: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
    },
    tecnico: { transmision: transmision(), aviso: null, ...parcialTecnico },
  }
}

// =============================================================================
// Doble determinista del backend
// =============================================================================

/**
 * Instala un backend de prueba que responde el snapshot que corresponda a cada ruta.
 *
 * Recibe un mapa `fragmento de URL -> estado`. Así una sola función sirve para las tres
 * pantallas, incluido el puesto técnico, que consume dos proyecciones a la vez.
 */
export async function instalarBackend(page: Page, estados: Record<string, unknown>): Promise<void> {
  await page.addInitScript((iniciales) => {
    type Escucha = (evento: { type: string; data?: string }) => void
    const mapa = iniciales as Record<string, unknown>

    /** Devuelve el estado cuya clave aparece en la URL consultada. */
    function resolver(url: string): unknown | null {
      for (const [clave, estado] of Object.entries(mapa)) {
        if (url.includes(clave)) return estado
      }
      return null
    }

    class FuentePrueba {
      cerrada = false
      onopen: Escucha | null = null
      onerror: Escucha | null = null
      onmessage: Escucha | null = null
      escuchas: Record<string, Escucha[]> = {}

      constructor(readonly url: string) {
        setTimeout(() => {
          if (this.cerrada) return
          this.onopen?.({ type: 'open' })
          const estado = resolver(this.url)
          if (estado === null) return
          for (const escuchar of this.escuchas.estado ?? []) {
            escuchar({ type: 'estado', data: JSON.stringify(estado) })
          }
        }, 10)
      }

      addEventListener(tipo: string, escuchar: Escucha): void {
        this.escuchas[tipo] = this.escuchas[tipo] ?? []
        this.escuchas[tipo]?.push(escuchar)
      }

      removeEventListener(tipo: string, escuchar: Escucha): void {
        this.escuchas[tipo] = (this.escuchas[tipo] ?? []).filter((otro) => otro !== escuchar)
      }

      close(): void {
        this.cerrada = true
      }
    }

    // @ts-expect-error Sustitución determinista de EventSource para el E2E.
    window.EventSource = FuentePrueba

    const fetchOriginal = window.fetch.bind(window)
    window.fetch = async (entrada: RequestInfo | URL, opciones?: RequestInit) => {
      const url =
        typeof entrada === 'string' ? entrada : entrada instanceof URL ? entrada.href : entrada.url
      const estado = resolver(url)
      if (estado !== null) {
        return new Response(JSON.stringify(estado), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      return fetchOriginal(entrada, opciones)
    }
  }, estados)
}

/** Mide el desborde del documento; es la definición operativa de "sin scroll global". */
export async function medirDocumento(page: Page) {
  return page.evaluate(() => {
    const raiz = document.documentElement
    return {
      scrollHeight: raiz.scrollHeight,
      clientHeight: raiz.clientHeight,
      scrollWidth: raiz.scrollWidth,
      clientWidth: raiz.clientWidth,
    }
  })
}

/** Afirma que ni el alto ni el ancho del documento desbordan el viewport. */
export function esperarSinScrollGlobal(medidas: Awaited<ReturnType<typeof medirDocumento>>): void {
  expect(medidas.scrollHeight).toBeLessThanOrEqual(medidas.clientHeight + 1)
  expect(medidas.scrollWidth).toBeLessThanOrEqual(medidas.clientWidth + 1)
}
