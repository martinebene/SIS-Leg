#!/bin/sh
# Wrapper de usuario del lanzador «Actualizar SIS-Leg» (WP-101A).
#
# El lanzador del escritorio invoca exactamente esta ruta, así que el nombre y la
# ubicación no pueden cambiar sin tocar el `.desktop`, que está fuera de alcance.
#
# El wrapper no decide nada: muestra qué va a pasar, pide la contraseña con el
# `sudo` interactivo ya disponible —no se modifica sudoers ni PolicyKit— y deja
# el resultado a la vista hasta que la persona cierre la ventana.

set -eu

OPERACION=/usr/local/bin/sisleg-operacion
REGISTRO="${HOME}/sisleg-update-history.log"

echo "== Actualizar SIS-Leg =="
echo
echo "Se va a traer la última versión publicada y dejarla preparada."
echo "Si el sistema anterior está activo, no se cambia de sistema."
echo

estado_final=0
sudo "${OPERACION}" --registro "${REGISTRO}" actualizar || estado_final=$?

echo
if [ "${estado_final}" -eq 0 ]; then
	echo "Operación terminada correctamente."
else
	echo "La operación NO se completó (código ${estado_final}). No se cambió el sistema en uso."
fi
echo "Historial: ${REGISTRO}"
echo
printf 'Podés cerrar esta ventana. Enter para salir: '
read -r _
exit "${estado_final}"
