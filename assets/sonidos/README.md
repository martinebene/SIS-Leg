# Sonidos de la Pantalla del Recinto (WP-065)

Los archivos viven en `apps/recinto/public/assets/sonidos/`, porque la Pantalla
del Recinto es la única aplicación que los reproduce y Nuxt publica ese
directorio tal cual bajo el prefijo `/recinto/`. Este README documenta su
procedencia desde fuera de la salida servida, igual que `assets/branding/`.

Los 22 archivos WAV son **originales de SIS-Leg**: los sintetiza
`scripts/generar_sonidos_recinto.py` a partir de recetas versionadas,
sin ninguna grabación ni biblioteca de terceros. No hay obra ajena involucrada,
así que se redistribuyen bajo la misma licencia que el resto del repositorio y
no arrastran atribuciones ni restricciones externas.

La generación es determinista: no usa azar, ni la hora del sistema, ni
dependencias fuera de la biblioteca estándar de Python. Regenerarlos produce
exactamente los mismos bytes, y `tests/test_sonidos_recinto.py` lo comprueba
archivo por archivo. Esa reproducibilidad es la prueba de procedencia: si
alguien sustituyera un asset por uno de origen desconocido, la prueba fallaría.

Para regenerarlos:

```bash
uv run python scripts/generar_sonidos_recinto.py
```

## Formato

WAV PCM sin comprimir, monofónico, 16 bits con signo, 44 100 Hz. Es el formato
que cualquier navegador reproduce sin decodificador adicional y sin patentes.

## Asignación a eventos

La asignación real vive en la sección `[sonidos]` de `config/system.toml`, junto
con el volumen `0..100` de cada evento; esta tabla sólo documenta la asignación
que trae la configuración de referencia, versionada desde WP-073 en
`config/system.example.toml`.

| Evento configurado | Archivo | Duración | Descripción | SHA-256 |
| --- | --- | --- | --- | --- |
| `preparacion_iniciada` | `preparacion-iniciada.wav` | 0.58 s | Comienza la preparación del recinto: dos notas ascendentes suaves. | `a0275a67ded12820415e2d15cbedf2e36860ed3d07a80fde2925f9212e227f50` |
| `aviso_tecnico_publicado` | `aviso-tecnico-publicado.wav` | 0.37 s | Aparece un mensaje de Apoyo Técnico en la Pantalla del Recinto. | `777ffae5f40691c68e1ee328d3a998a65d6253693bfb7acf3e87f4601c96df89` |
| `aviso_tecnico_retirado` | `aviso-tecnico-retirado.wav` | 0.37 s | Se retira el mensaje de Apoyo Técnico (por cancelación o vencimiento). | `b6682d04d7effca1096c592892a799729965180892ba1a9676ec539d6555957f` |
| `pedido_palabra_registrado` | `pedido-palabra-registrado.wav` | 0.30 s | Un concejal cualquiera pide la palabra: repique breve y claro. | `c2850e17eb75ec616e666e61d946e552b360b76f7d3d735819a8f70d5506ba15` |
| `pedido_palabra_retirado` | `pedido-palabra-retirado.wav` | 0.30 s | Un concejal cualquiera retira su pedido de palabra: mismo repique, más grave. | `76da4cd7884fd63ce556e4cc055486825148e3c5cfeb8a0f0bf77200f4072f83` |
| `uso_palabra_otorgado` | `uso-palabra-otorgado.wav` | 0.60 s | Se asigna la palabra a un concejal: arpegio ascendente de tres notas. | `9c454e0db23bfa22658cd3cc294d0ef5d58f5ecfdfb42bfd4771eb182033d8fb` |
| `transmision_iniciada` | `transmision-iniciada.wav` | 0.68 s | Comienza la transmisión en vivo: barrido ascendente decidido. | `dd201cb7fd55b2454f2560c495c3e05fd757560d66747a2ff97bc3eb93453c92` |
| `transmision_detenida` | `transmision-detenida.wav` | 0.68 s | Se detiene la transmisión en vivo: barrido descendente. | `9c3e4546cd366f50e4bfd1ac89529ab0fae6e932902a67e553e7d5b0b9754abb` |
| `transmision_cuenta_regresiva_tic` | `transmision-cuenta-regresiva-tic.wav` | 0.09 s | Cada cambio de segundo de la cuenta regresiva hacia el vivo: tic muy corto y discreto. | `275e4d209622874d69aab2b88f76ee13bc174fd29bf244a94583e2f279072adb` |
| `sesion_abierta` | `sesion-abierta.wav` | 1.54 s | Apertura de sesión: acorde ascendente de campana, el sonido más solemne. | `78268344fb6a71f9f9e0fd30d7c61dc46a904b746c9d49c26f6b0258ff69332f` |
| `sesion_cerrada` | `sesion-cerrada.wav` | 1.50 s | Cierre de sesión: la misma campana, en orden descendente. | `e7ef90744add1e0fcd277f58065e681b0ef56da44677c86d06e8ca383afb8311` |
| `votacion_abierta` | `votacion-abierta.wav` | 0.60 s | Apertura de votación: dos notas ascendentes firmes que llaman a votar. | `d66b5362d8ea36b8f4c6facfbf5e354d38359b5b332bfdb30414960cd54fd9b7` |
| `votacion_cerrada` | `votacion-cerrada.wav` | 0.62 s | Cierre de votación: dos notas descendentes que cierran el bloque. | `cec4c32422c98c0b96d9e30ea2c11ca4ecf9c480c1c0a29bbc9d6b139203512c` |
| `concejal_ausente` | `concejal-ausente.wav` | 0.20 s | Un concejal cualquiera pasa a ausente: destello grave y breve. | `883548fc90966392934b6ec3a518d5607a1c60c4ff2b8d039dd71586b47d7142` |
| `concejal_presente` | `concejal-presente.wav` | 0.20 s | Un concejal cualquiera pasa a presente: destello agudo y breve. | `41f2afe21641c50929eadc8db6e44a82e7d314ad54ab3a2fb23658ec8e44e810` |

## Alternativas sin asignar

Estos siete archivos no están referenciados por la configuración de referencia.
Existen para que una instalación pueda cambiar el sonido de un evento editando
únicamente `config/system.toml`, sin agregar archivos ni tocar código.

| Archivo | Duración | Descripción | SHA-256 |
| --- | --- | --- | --- |
| `alternativa-campana.wav` | 1.20 s | Campana única y sostenida. | `042bcda30c66da617bd3342f4335588e08ba267113ba8f06410ef61c48665c49` |
| `alternativa-barrido-ascendente.wav` | 0.55 s | Barrido ascendente largo. | `937029650f3a437ccf65514eeacfcd8df3865d6e9f35d6f5335dfea953150875` |
| `alternativa-barrido-descendente.wav` | 0.55 s | Barrido descendente largo. | `39424e9fd3897553c51c7f8451cc3fcffd24bc502c209507dab72347f017e961` |
| `alternativa-doble-tono.wav` | 0.42 s | Dos tonos iguales separados por un silencio corto. | `6602dacf597de450f2f47c86ca18357f00d842d9522b96c8c4e6ca8244795cc4` |
| `alternativa-golpe-grave.wav` | 0.28 s | Golpe grave y corto, para avisos serios. | `c9376b1711ef8835b5f6364c104504f26c6b4744b9c131e04ec40c48a1a56870` |
| `alternativa-pulso-corto.wav` | 0.07 s | Pulso agudo mínimo, apenas perceptible. | `5389ffb373d3452e409656c059366626b37feb0ccd5955650b2f83b989a7e893` |
| `alternativa-triple-tic.wav` | 0.36 s | Tres tics de madera consecutivos. | `66aaa9696394af22b76f71fe56b270dc3a57bceea26d74b638f9ef255e9c851e` |

## Reproducción

WP-065 sólo configura y versiona. La reproducción efectiva en el navegador,
incluida la política de autoplay y la detección de transiciones, corresponde a
WP-066.
