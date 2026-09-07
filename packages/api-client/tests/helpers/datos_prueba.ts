/**
 * Payloads de prueba tipados para los tests de @sis-leg/api-client.
 */

import type {
  ApoyoTecnicoProyectado,
  EstadoModeracion,
  EstadoRecinto,
  EstadoTecnico,
} from '../../src/tipos'

/**
 * Identidad de instancia predeterminada de los payloads de prueba (WP-080).
 *
 * Casi todos los escenarios ocurren dentro de un mismo proceso backend, así que alcanza
 * con que las revisiones compartan esta constante. Los escenarios de reinicio pasan
 * explícitamente `INSTANCIA_PRUEBA_B` para representar al proceso nuevo.
 */
export const INSTANCIA_PRUEBA_A = 'instancia-prueba-a'

/** Segunda identidad de instancia: representa al backend ya reiniciado. */
export const INSTANCIA_PRUEBA_B = 'instancia-prueba-b'

/**
 * Porción técnica en reposo: transmisión APAGADA y sin aviso vigente.
 *
 * Es el valor que devuelve el backend mientras Apoyo Técnico no ejecutó ningún
 * comando, así que sirve de base para cualquier fixture que no ejercite WP-055.
 */
export function crearMockApoyoTecnico(): ApoyoTecnicoProyectado {
  return {
    transmision: {
      estado: 'APAGADO',
      iniciada_en: null,
      en_vivo_desde: null,
      cuenta_regresiva_segundos: null,
      segundos_restantes: null,
    },
    aviso: null,
  }
}

export function crearMockEstadoModeracion(
  revision = 1,
  estadoGlobal: EstadoModeracion['estado_global'] = 'PREPARANDO',
  instancia = INSTANCIA_PRUEBA_A,
): EstadoModeracion {
  return {
    instancia,
    revision,
    generado_en: new Date().toISOString(),
    estado_global: estadoGlobal,
    preparacion: {
      numero_sesion: 1,
      presidencia: 'Presidente Test',
      secretaria_legislativa: 'Secretario Test',
      fecha_hora_inicio: new Date().toISOString(),
    },
    sesion: null,
    configuracion: {
      quorum: 7,
      filas_bancas: [6, 6],
      tipos_votacion: ['General', 'Particular'],
      duracion_test_segundos: 5,
      revelado_votos_moderacion_segundos: 4,
      cuenta_regresiva_recinto_segundos: 4,
      resultado_publico_recinto_segundos: 6,
    },
    concejales: [
      {
        dni: '12345678',
        nombre: 'Concejal',
        apellido: 'Uno',
        bloque: 'Bloque A',
        banca: 1,
        dispositivo_votacion: 'dev01',
        ruta_imagen: '/img/1.png',
        presente: true,
        test_activo: false,
        test_expira_en: null,
      },
    ],
    quorum: {
      cantidad_presentes: 1,
      requerido: 7,
      alcanzado: false,
    },
    votacion: null,
    palabra: {
      cola: [],
      orador: null,
    },
    orden_del_dia: [],
    eventos_recientes: [],
    auditoria: {
      activa: true,
      disponible: true,
      fallado: false,
      cerrado: false,
      motivo: null,
    },
    remapeo: null,
    capacidades: {
      preparar_sala: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      actualizar_preparacion: { habilitada: true, motivos: [] },
      cancelar_preparacion: { habilitada: true, motivos: [] },
      abrir_sesion: { habilitada: false, motivos: ['QUORUM_INSUFICIENTE'] },
      actualizar_sesion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      cerrar_sesion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      cargar_orden_del_dia: { habilitada: true, motivos: [] },
      descartar_orden_del_dia: { habilitada: true, motivos: [] },
      abrir_votacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      finalizar_votacion: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      desempatar: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      otorgar_palabra: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      quitar_palabra: { habilitada: false, motivos: ['ESTADO_INCOMPATIBLE'] },
      iniciar_remapeo: { habilitada: true, motivos: [] },
      confirmar_remapeo: { habilitada: false, motivos: ['REMAPEO_NO_COINCIDE'] },
      cancelar_remapeo: { habilitada: false, motivos: ['REMAPEO_NO_COINCIDE'] },
    },
    tecnico: crearMockApoyoTecnico(),
  }
}

export function crearMockEstadoRecinto(
  revision = 1,
  estadoGlobal: EstadoRecinto['estado_global'] = 'PREPARANDO',
  instancia = INSTANCIA_PRUEBA_A,
): EstadoRecinto {
  return {
    instancia,
    revision,
    generado_en: new Date().toISOString(),
    estado_global: estadoGlobal,
    preparacion: {
      numero_sesion: 1,
      presidencia: 'Presidente Test',
      secretaria_legislativa: 'Secretario Test',
      fecha_hora_inicio: new Date().toISOString(),
    },
    sesion: null,
    filas_bancas: [1],
    concejales: [
      {
        nombre: 'Concejal',
        apellido: 'Uno',
        bloque: 'Bloque A',
        banca: 1,
        ruta_imagen: '/img/1.png',
        presente: true,
        test_activo: false,
        test_expira_en: null,
      },
    ],
    quorum: {
      cantidad_presentes: 1,
      requerido: 7,
      alcanzado: false,
    },
    votacion: null,
    palabra: {
      cola: [],
      orador: null,
    },
    // La franja pública siempre viaja en el snapshot, aunque esté vacía: el
    // contrato la declara obligatoria para que el Recinto nunca tenga que
    // distinguir entre "sin eventos" y "campo ausente".
    eventos_publicos: [],
    tecnico: crearMockApoyoTecnico(),
    // La configuración de audio (WP-065) también es obligatoria y viaja en los
    // tres estados globales. Este mock declara sólo dos eventos porque el
    // cliente API no interpreta la lista: la transporta.
    sonidos: {
      disponible: true,
      motivo: null,
      detalle: null,
      sonidos: [
        { evento: 'sesion_abierta', ruta: 'assets/sonidos/sesion-abierta.wav', volumen: 90 },
        { evento: 'sesion_cerrada', ruta: 'assets/sonidos/sesion-cerrada.wav', volumen: 85 },
      ],
    },
  }
}

/**
 * Snapshot mínimo pero **completo** del puesto de Apoyo Técnico.
 *
 * Construye el DTO exacto del contrato, sin campos inventados ni opcionales de conveniencia:
 * si el backend agregara o quitara una porción, esta fábrica dejaría de compilar y la
 * divergencia se detectaría acá. Los tests que la usan sólo miran `instancia` y `revision`,
 * pero el resto tiene que existir para que el payload sea el que realmente viaja.
 */
export function crearMockEstadoTecnico(
  revision = 1,
  estadoGlobal: EstadoTecnico['estado_global'] = 'PREPARANDO',
  instancia = INSTANCIA_PRUEBA_A,
): EstadoTecnico {
  const apoyo = crearMockApoyoTecnico()
  return {
    instancia,
    revision,
    generado_en: new Date().toISOString(),
    estado_global: estadoGlobal,
    transmision: apoyo.transmision,
    aviso_moderacion: null,
    aviso_recinto: null,
    biblioteca: {
      disponible: true,
      motivo: null,
      detalle: null,
      mensajes: [],
    },
    eventos_recientes: [],
    auditoria: {
      activa: true,
      disponible: true,
      fallado: false,
      cerrado: false,
      motivo: null,
    },
    remapeo: {
      remapeo: null,
      concejales: [],
      capacidades: {
        iniciar_remapeo: { habilitada: true, motivos: [] },
        confirmar_remapeo: { habilitada: false, motivos: ['REMAPEO_NO_COINCIDE'] },
        cancelar_remapeo: { habilitada: false, motivos: ['REMAPEO_NO_COINCIDE'] },
      },
    },
    // La subproyección sonora repite `instancia` y `revision` porque su detector de
    // transiciones compara ese objeto, no el estado que lo contiene.
    sonorizacion: {
      instancia,
      revision,
      estado_global: estadoGlobal,
      tecnico: apoyo,
      palabra: null,
      votacion: null,
      concejales: [],
      sonidos: {
        disponible: true,
        motivo: null,
        detalle: null,
        sonidos: [],
      },
    },
  }
}
