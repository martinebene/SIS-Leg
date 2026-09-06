/**
 * Fixtures del puesto de Apoyo Técnico (WP-056).
 *
 * Construyen exactamente los DTO que publica el backend, sin campos inventados: si el
 * contrato cambiara, estas fábricas dejarían de compilar y la divergencia se detectaría
 * acá antes que en la pantalla.
 */

import type {
  AvisoTecnicoProyectado,
  BibliotecaMensajesProyectada,
  Capacidad,
  DestinoAvisoTecnico,
  EstadoTecnico,
  EventoRecienteProyectado,
  MensajeTecnicoProyectado,
  RemapeoTecnicoProyectado,
  SonorizacionRecintoProyectada,
  TransmisionProyectada,
} from '@sis-leg/api-client'
import {
  crearEstadoRecintoPrueba,
  proyectarSonorizacionTecnica,
} from '../../../packages/frontend-shared/tests/helpers/estado_recinto'

export function crearTransmisionPrueba(
  parcial: Partial<TransmisionProyectada> = {},
): TransmisionProyectada {
  return {
    estado: parcial.estado ?? 'APAGADO',
    iniciada_en: parcial.iniciada_en ?? null,
    en_vivo_desde: parcial.en_vivo_desde ?? null,
    cuenta_regresiva_segundos: parcial.cuenta_regresiva_segundos ?? null,
    segundos_restantes: parcial.segundos_restantes ?? null,
  }
}

export function crearAvisoPrueba(
  parcial: Partial<AvisoTecnicoProyectado> = {},
): AvisoTecnicoProyectado {
  return {
    aviso_id: parcial.aviso_id ?? 'aviso-1',
    texto: parcial.texto ?? 'Corte de energía en el recinto',
    destino: parcial.destino ?? 'AMBOS',
    publicado_en: parcial.publicado_en ?? '2026-09-02T10:00:00Z',
    expira_en: parcial.expira_en ?? null,
    segundos_restantes: parcial.segundos_restantes ?? null,
  }
}

export function crearMensajePrueba(
  mensajeId: string,
  texto: string,
  destino: DestinoAvisoTecnico = 'AMBOS',
): MensajeTecnicoProyectado {
  return { mensaje_id: mensajeId, texto, destino }
}

export function crearBibliotecaPrueba(
  parcial: Partial<BibliotecaMensajesProyectada> = {},
): BibliotecaMensajesProyectada {
  return {
    disponible: parcial.disponible ?? true,
    motivo: parcial.motivo ?? null,
    detalle: parcial.detalle ?? null,
    mensajes: parcial.mensajes ?? [],
  }
}

export function crearEventoPrueba(
  parcial: Partial<EventoRecienteProyectado> = {},
): EventoRecienteProyectado {
  return {
    seq: parcial.seq ?? 1,
    timestamp: parcial.timestamp ?? '2026-09-02 10:00:00',
    nivel: parcial.nivel ?? 'L3',
    etiqueta: parcial.etiqueta ?? 'SESION',
    codigo_evento: parcial.codigo_evento ?? 'EVENTO_PRUEBA',
    mensaje: parcial.mensaje ?? 'Mensaje de auditoría',
    hecho: parcial.hecho ?? null,
  }
}

/** Capacidad habilitada por defecto; las pruebas que necesiten un bloqueo pasan la suya. */
function capacidadHabilitada(): Capacidad {
  return { habilitada: true, motivos: [] }
}

/**
 * Allowlist de remapeo que viaja dentro del estado técnico desde WP-074.
 *
 * Por defecto no hay operación activa y las tres capacidades están habilitadas, que es el
 * punto de partida del panel: se puede elegir una banca e iniciar la captura.
 */
export function crearRemapeoTecnicoPrueba(
  parcial: Partial<RemapeoTecnicoProyectado> = {},
): RemapeoTecnicoProyectado {
  return {
    remapeo: parcial.remapeo ?? null,
    concejales: parcial.concejales ?? [
      {
        dni: '10000001',
        nombre: 'Nombre1',
        apellido: 'Apellido1',
        banca: 1,
        dispositivo_votacion: 'dev01',
      },
      {
        dni: '10000002',
        nombre: 'Nombre2',
        apellido: 'Apellido2',
        banca: 2,
        dispositivo_votacion: 'dev02',
      },
    ],
    capacidades: parcial.capacidades ?? {
      iniciar_remapeo: capacidadHabilitada(),
      confirmar_remapeo: capacidadHabilitada(),
      cancelar_remapeo: capacidadHabilitada(),
    },
  }
}

/**
 * Subproyección sonora por defecto, derivada de la fixture pública del Recinto.
 *
 * Se deriva y no se escribe a mano para que las dos superficies partan del mismo estado de
 * referencia: es la misma configuración de audio y el mismo plano técnico apagado.
 */
export function crearSonorizacionPrueba(
  parcial: Partial<SonorizacionRecintoProyectada> = {},
): SonorizacionRecintoProyectada {
  return { ...proyectarSonorizacionTecnica(crearEstadoRecintoPrueba()), ...parcial }
}

export function crearEstadoTecnicoPrueba(parcial: Partial<EstadoTecnico> = {}): EstadoTecnico {
  return {
    revision: parcial.revision ?? 1,
    generado_en: parcial.generado_en ?? '2026-09-02T10:00:00Z',
    estado_global: parcial.estado_global ?? 'SIN_PREPARAR',
    transmision: parcial.transmision ?? crearTransmisionPrueba(),
    aviso_moderacion: parcial.aviso_moderacion ?? null,
    aviso_recinto: parcial.aviso_recinto ?? null,
    biblioteca: parcial.biblioteca ?? crearBibliotecaPrueba(),
    eventos_recientes: parcial.eventos_recientes ?? [],
    auditoria: parcial.auditoria ?? {
      activa: false,
      disponible: true,
      fallado: false,
      cerrado: false,
      motivo: null,
    },
    remapeo: parcial.remapeo ?? crearRemapeoTecnicoPrueba(),
    sonorizacion:
      parcial.sonorizacion ??
      crearSonorizacionPrueba({
        revision: parcial.revision ?? 1,
        estado_global: parcial.estado_global ?? 'SIN_PREPARAR',
      }),
  }
}
