# Assets de marca SIS-Leg

Estos PNG son los derivados listos para repositorio de los archivos suministrados por
HUMAN_GATE. El isotipo proviene de la entrega del 03/09/2026 (WP-062); el logo completo fue
reemplazado en WP-069 por una entrega posterior, del 04/09/2026.

## Fuentes humanas originales

- Logo completo (04/09/2026, WP-069): `Logo recortado.png`, 1536×1024 RGBA, 1.027.650 bytes,
  SHA-256 `98d155ddf73e7d10d7b8b40f8510e0423b0d6dbffd749c79173b173fd0cfc756`.
- Isotipo/favicon (03/09/2026, WP-062): 1254×1254,
  SHA-256 `13b8895bb44a1d133487ef0c84e573c02a9186bc0b4df6e708b96d6587f8686f`.

La fuente del logo no se versiona en este repositorio: queda registrada en la campaña de
HUMAN_GATE junto con su hash, que es lo que permite comprobar que el derivado salió de ella.
La fuente del logo anterior (1448×1086, SHA-256
`fd462939f56b283796e50e0447d9c07b5da7eb2784055b2be197865da3c8a703`) quedó sin uso.

## Derivados versionados

- `sisleg-logo.png`: 1536×1024 RGBA, SHA-256
  `72a025cab597d5ce54cf048c39800de3c647a3d7ab9846fa458b63f81192eff7`.
- `sisleg-isotipo.png`: 256×250, fondo blanco convertido a transparencia y márgenes
  recortados, SHA-256 `cd26723bc3fa2016816a4a1ebc0684b987b15219a7ef4ebe6bdd406fd0cc7540`.

## Cómo se produce el logo completo

HUMAN_GATE autorizó **una sola** edición sobre el archivo del 04/09/2026: suavizar
mínimamente el borde. El lienzo se conserva entero —con sus márgenes transparentes, que no
se pueden recortar—, no se redimensiona, no se recolorea y no se redibuja nada.

Esa edición está implementada como procedimiento reproducible en
`scripts/generar_logo_sisleg.mjs`, para que cualquiera pueda regenerar el archivo y obtener
los mismos bytes:

```bash
node scripts/generar_logo_sisleg.mjs --fuente "<ruta a Logo recortado.png>"
node scripts/generar_logo_sisleg.mjs --fuente "<ruta a Logo recortado.png>" --verificar
```

El script modifica únicamente el canal alfa, y sólo en los píxeles que ya eran visibles y
tienen algún vecino completamente transparente. Sobre ellos toma el mínimo entre el alfa
original y un promedio gaussiano 3×3 del alfa, de modo que la opacidad sólo puede bajar.
De ahí salen las garantías que exige `docs/work-packages/WP-069.md`: no aparecen píxeles
opacos donde el original era transparente, la silueta no se expande fuera del contorno
blanco y el interior queda intacto. Los tres canales de color viajan sin tocar.

Medidas de la única edición aplicada:

| Medida | Valor |
| --- | --- |
| Píxeles en la banda de borde | 15.748 |
| Píxeles con alfa modificado | 6.260 de 1.572.864 |
| Reducción máxima de alfa | 74 / 255 |
| Reducción media de alfa | 10,49 / 255 |
| Canales de color modificados | 0 |

## Copias públicas

Cada aplicación sirve su propio directorio estático, así que el logo y el isotipo están
copiados byte a byte en `apps/<aplicacion>/public/assets/marca/`. El manual
(`manual/index.html`) incrusta el mismo PNG como `data:` para seguir siendo un único
archivo sin recursos remotos; el contenido decodificado es idéntico al canónico.

HUMAN_GATE autorizó el recorte y la transparencia del isotipo preservando el diseño, y para
el logo completo sólo el suavizado descrito arriba. Ningún agente puede redibujar,
reinterpretar ni derivar variantes nuevas de la marca.
