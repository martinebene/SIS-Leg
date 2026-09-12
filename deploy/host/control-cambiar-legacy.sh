#!/bin/sh
# Wrapper de usuario del lanzador «Cambiar a Legacy» (WP-101A).
#
# Es independiente de la versión de SIS-Leg instalada y no borra releases,
# configuración ni registros: SIS-Leg queda preparado para volver a activarse.

set -eu

OPERACION=/usr/local/bin/sisleg-operacion
REGISTRO="${HOME}/sisleg-switch-history.log"

echo "== Cambiar al sistema anterior =="
echo
echo "Se va a retirar SIS-Leg y devolver el recinto al sistema anterior."
echo

estado_final=0
sudo "${OPERACION}" --registro "${REGISTRO}" cambiar-a-legacy || estado_final=$?

echo
if [ "${estado_final}" -eq 0 ]; then
	echo "Operación terminada correctamente."
else
	echo "La operación NO se completó (código ${estado_final}). Revisá el estado antes de reintentar."
fi
echo "Historial: ${REGISTRO}"
echo
printf 'Podés cerrar esta ventana. Enter para salir: '
read -r _
exit "${estado_final}"
