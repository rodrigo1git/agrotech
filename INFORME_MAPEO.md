# Implementación y verificación del mapeo

Se implementó la primera versión descrita en `PLAN_MAPEO.md`, manteniendo
`tree.`, umbral de cajas 0.35 y umbral de texto 0.25.

## Entregado

- `mapear_arboles.py` y paquete `mapeo/`: almacenamiento SQLite, versiones de
  detección, observaciones direccionales, asociación entre capturas y posiciones
  estimadas con controles geométricos.
- IDs persistentes e importaciones idempotentes; una sola ejecución activa por
  imagen, con conservación de resultados anteriores.
- Grupos ambiguos y corrección de una hipótesis en varios individuos sin
  conservar un tercer árbol ficticio.
- Revisión, anclas, fusiones y divisiones transaccionales y reversibles.
- GeoJSON, inventario JSON, estadísticas, evidencia e historial.
- Mapa HTML local con capas, filtros, recortes y preparación de revisiones;
  mapa de calles opcional con conexión.
- Integración `mapillary_arboles.py --map` y preparación del entorno actualizada.

## Verificación realizada

- 42 pruebas automatizadas aprobadas en `hackaton`.
- Inferencia real con el modelo en caché sobre la captura `870050853581010`:
  cinco detecciones, revisión `a2bb814dd30d776dcf7e30523b00659f4f141c71`,
  hash de imagen y preprocesado registrados.
- Importación de esa ejecución y repetición: mismos IDs activos y conteos;
  la segunda importación no añade eventos.
- La captura real única conserva cinco observaciones, tres candidatos y dos
  grupos pendientes. No se inventan posiciones de árboles desde una sola cámara.
- Demo sintética con varios puntos de vista y dos individuos separados por 2 m:
  dos confirmados, cero fusiones falsas y cero separaciones falsas frente a su
  referencia controlada. No es una medición de precisión sobre imágenes reales.
- JavaScript validado con Node e interacción ejecutada con DOM simulado.

## Límites de la validación

No fue posible descargar la secuencia de Mapillary desde esta sesión por un
problema de conexión/resolución del servidor. Falta validar una cuadra real con
múltiples capturas y una referencia manual de identidades y posiciones.

Las cajas sin anclas pueden dar candidatos aproximados, pero la confirmación
automática exige anclas verificadas y geometría suficiente. También se admite
confirmación manual de identidad, separada de la certeza de ubicación.
La apariencia se revisa mediante recortes; no se entrenó un reidentificador.

La geometría esférica queda deshabilitada por defecto hasta validar un panorama
real; fisheye queda pendiente. Las incertidumbres son heurísticas, no intervalos
estadísticos calibrados. Firefox headless no pudo completar una captura de
pantalla en esta sesión, por lo que la inspección visual en navegador normal
queda pendiente.

## Abrir resultados y continuar

- Mapa real: `resultados/mapeo/exportaciones/tandil2018/mapa.html`.
- Demo: `resultados/demo_mapeo/exportaciones/demo/mapa.html`.
- Instrucciones y correcciones: [GUIA_MAPEO.md](GUIA_MAPEO.md).
