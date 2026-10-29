# Seguimiento visual básico entre imágenes

El inventario puede asociar dos detecciones aunque sus ubicaciones aproximadas
no coincidan. Compara los recortes de las fotografías originales, el tamaño y
la posición de las cajas. No vuelve a ejecutar DINO ni cambia su prompt `tree.`.

Para activarlo en la manzana ya descargada, usando el Python de `hackaton`:

```bash
python procesar_manzana_tandil.py --skip-inference --tracking
```

El mapa se regenera en `resultados/mapeo/exportaciones/manzana_tandil/mapa.html`.
Recargá la misma dirección HTTP del visor. Se conservan los controles de
desplazamiento y rotación y los ajustes del navegador. Las ejecuciones siguientes
del procesador conservan la opción guardada en ese relevamiento.

Para desactivarlo y recalcular con la asociación geométrica:

```bash
python procesar_manzana_tandil.py --skip-inference --no-tracking
```

Las detecciones originales y sus imágenes se conservan. Una unión automática
mantiene todas las observaciones como evidencia y un solo candidato en el mapa;
los IDs absorbidos quedan inactivos con referencia a su sucesor. Al separar una
asociación puede asignarse un ID nuevo a una de las partes. Los cambios quedan
en el historial de SQLite; no se consideran identidades confirmadas.

## Reglas iniciales

- Compara cada foto con las dos siguientes de la misma secuencia y día UTC.
  Las fotos sin detecciones también cuentan para ese límite.
- Exige hasta 5 segundos entre fotos, 15 metros entre cámaras y 15 grados de giro.
- Compara textura mediante correlación de píxeles y color mediante histogramas,
  normalizando cada recorte a 40 × 40 píxeles. Tolera pequeños desplazamientos.
- Exige puntuación ≥ 0.72, correlación ≥ 0.60 y similitud de color ≥ 0.70.
  La mejor coincidencia debe superar a cualquier competidora en ambas imágenes
  por al menos 0.06. El resultado es uno a uno entre esas dos fotos.
- Rechaza uniones si dos observaciones diferentes del componente aparecen en la
  misma captura. También protege identidades revisadas/confirmadas, respeta los
  límites temporales y evita eliminar una triangulación existente si el ajuste
  de las observaciones combinadas falla.
- Las cajas grupales y las correspondencias geométricas ambiguas permanecen
  pendientes. No se unen automáticamente recorridos distintos ni años distintos.

La posición del candidato resultante se calcula con la lógica existente:
triangulación cuando alcanza la evidencia, o ubicación aproximada. Los puntos
estimados del mapa no intervienen en la comparación visual.

Es una heurística: puede dejar duplicados y también equivocarse con árboles o
fondos parecidos. Una caja que abarca varios árboles sigue necesitando revisión.
La correlación sirve como filtro inicial, no como probabilidad de identidad.
El visor indica cuántas imágenes respaldan la asociación y permite ver sus
recortes. Revisá la evidencia antes de usar el inventario como conteo definitivo.

## Ajustes y extensión

Los valores están en `configuracion_mapeo.json` y los valores de respaldo en
`mapeo/seguimiento_visual.py`. La configuración se guarda por relevamiento:
editar el JSON por sí solo no actualiza uno existente. Para probar valores nuevos,
creá, por ejemplo, `ajustes_seguimiento.json`:

```json
{
  "tracking_min_score": 0.80,
  "tracking_ambiguity_margin": 0.08,
  "tracking_frame_gap": 2
}
```

```bash
python procesar_manzana_tandil.py --skip-inference --tracking --config ajustes_seguimiento.json
```

`--config` aplica el archivo sobre los valores generales actuales y guarda el
resultado para la manzana. Un umbral mayor exige coincidencias más claras y suele
dejar más duplicados. Aumentar el salto de fotos o bajar los umbrales puede unir
árboles vecinos por error.

El módulo está separado: `crear_enlaces(observaciones, capturas, config,
comparador=None)` acepta un comparador reemplazable. El callable recibe dos
observaciones con `image_path` y `bbox_xyxy` y devuelve un diccionario con
`score` entre 0 y 1, o `None`. Puede incluir `ncc`, `color` y un atributo `method`.
Así se puede sustituir el comparador por descriptores aprendidos u otro tracker
sin modificar las reglas de fusión ni el renderizador del mapa. El comparador
actual utiliza Pillow y NumPy; no requiere OpenCV ni descargar otro modelo.

## Archivos para revisar

Dentro de `resultados/mapeo/exportaciones/manzana_tandil/`:

- `seguimiento_visual.json`: candidatos activos con sus observaciones, pares
  asociados, método y puntuaciones. Incluye apoyos visuales de asociaciones que
  ya existían por geometría, no solo las uniones nuevas.
- `seguimiento_debug.json`: cantidad de propuestas antes/después de la fase
  visual, enlaces que produjeron una unión y enlaces rechazados con su motivo.
  Se recalcula en cada ejecución; no representa el número de cambios contra la
  ejecución anterior.
- `inventario.json`: historial, IDs activos e inactivos y todas las evidencias.
- `arboles.geojson`, `mapa_datos.json` y `mapa.html`: inventario actualizado para
  aplicaciones y para el visor. `estadisticas.json` agrega
  `arboles_con_seguimiento_visual`.

El detalle de la asociación también se registra en los eventos de reconciliación
de `inventario.sqlite`. La primera aplicación sobre la manzana incluye un respaldo
previo en `resultados/mapeo/respaldos/`.
