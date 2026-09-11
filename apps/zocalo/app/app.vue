<script setup lang="ts">
/**
 * Shell del Zócalo para OBS (WP-099).
 *
 * Hace una sola cosa: abrir la suscripción autoritativa compartida y entregarle el estado
 * a la pantalla. No hay enrutamiento, ni cabecera, ni controles, ni indicador de carga
 * institucional: cualquiera de esas piezas pintaría sobre el croma algo que el filtro no
 * puede recortar.
 */

import { useEstadoZocalo } from './composables/useEstadoZocalo'
import PantallaZocalo from './components/PantallaZocalo.vue'

const { estado } = useEstadoZocalo()
</script>

<template>
  <PantallaZocalo :estado="estado" />
</template>
