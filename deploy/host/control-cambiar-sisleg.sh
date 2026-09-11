#!/bin/sh
# Wrapper de usuario del lanzador «Cambiar a SIS-Leg» (WP-101A).
#
# No contiene ningún SHA: la release que se activa sale de
# `/opt/sis-leg/target-release` y la valida la herramienta versionada antes de
# tocar nada. Si SIS-Leg ya está activo, la operación no muta.

set -eu

OPERACION=/usr/local/bin/sisleg-operacion
REGISTRO="${HOME}/sisleg-switch-history.log"

echo "== Cambiar a SIS-Leg =="
echo
echo "Se va a retirar el sistema anterior y activar SIS-Leg."
echo "Si algo falla, el sistema anterior vuelve automáticamente."
echo

estado_final=0
sudo "${OPERACION}" --registro "${REGISTRO}" cambiar-a-sis-leg || estado_final=$?

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
