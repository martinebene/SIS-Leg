"""Pruebas unitarias del estado inicial definido por CA-001."""

from sis_leg_backend.dominio.estado import EstadoGlobal, EstadoOperativo


def test_estado_operativo_nuevo_esta_sin_preparar_y_sin_entidades() -> None:
    """Un estado recién construido no arrastra ninguna ejecución anterior."""

    estado = EstadoOperativo()

    assert estado.estado_global is EstadoGlobal.SIN_PREPARAR
    assert estado.preparacion_activa is None
    assert estado.sesion_activa is None
    assert estado.votacion_activa is None
    assert estado.archivos_auditoria_activos == ()
