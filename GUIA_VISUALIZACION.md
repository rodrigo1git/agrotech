# Probar y cambiar el visor del mapa

La visualización está separada de DINO, la asociación de árboles y SQLite:

- `mapeo/visores/leaflet.html`: interfaz, mapa, filtros y preparación de revisiones.
- `mapeo/visualizacion.py`: inserta los datos en una plantilla HTML. Solo usa la biblioteca estándar de Python.
- `mapa_datos.json`: contrato de datos independiente, generado junto a cada `mapa.html`.

El visor abre automáticamente las calles de OpenStreetMap, centrado en los árboles
y cámaras del relevamiento. Requiere Internet para cargar Leaflet y las imágenes
del mapa de calles. Si falla, informa el problema y conserva la vista local en
metros y la lista de registros. **Mapa de la ciudad** permite reintentar;
**Vista local** muestra el plano sin conexión. Las calles son cartografía,
no fotografías satelitales ni panorámicas de Mapillary. Las capturas de Mapillary
se consultan desde los registros de cámara y los recortes desde las observaciones.

## Regenerar solamente el HTML

Desde la carpeta del proyecto, sin ejecutar DINO ni modificar la base de datos:

```bash
python -m mapeo.visualizacion \
  --datos resultados/mapeo/exportaciones/tandil2018/mapa_datos.json
```

Para ver las calles, iniciá el servidor local desde el proyecto:

```bash
python -m mapeo.servidor_mapa
```

Abrí <http://127.0.0.1:8765/mapa.html> y mantené la terminal abierta.
El servidor comparte solo la carpeta de esa exportación y escucha únicamente
en tu computadora. Para servir el demo u otra alternativa:

```bash
python -m mapeo.servidor_mapa --mapa resultados/demo_mapeo/exportaciones/demo/mapa.html --port 8766
```

El HTML incluye sus datos y los recortes usan rutas relativas. Abrirlo con
`file://` permite usar la vista local, pero desactiva las calles: los archivos
locales no envían el encabezado `Referer` que exige la
[política de OpenStreetMap](https://operations.osmfoundation.org/policies/tiles/).
La página y el servidor usan `strict-origin-when-cross-origin` para permitir
que el navegador envíe su origen real. Si el aviso persiste desde localhost,
revisá si alguna extensión o configuración del navegador elimina ese encabezado.

## Probar otra alternativa

Podés copiar `mapeo/visores/leaflet.html`, editar esa copia y generar otro HTML:

```bash
cp mapeo/visores/leaflet.html /tmp/mi_visor.html
python -m mapeo.visualizacion \
  --datos resultados/mapeo/exportaciones/tandil2018/mapa_datos.json \
  --plantilla /tmp/mi_visor.html \
  --output resultados/mapeo/exportaciones/tandil2018/mapa_alternativo.html
```

Guardá el HTML junto al JSON para que funcionen las rutas `evidencia/...`.
La plantilla puede usar otra biblioteca o una interfaz completamente distinta.
Debe incluir exactamente una vez este bloque para recibir los datos:

```html
<script id="datos" type="application/json">__DATOS__</script>
<script>
const datos = JSON.parse(document.getElementById('datos').textContent);
// Dibujar el mapa con datos.trees, datos.cameras, etc.
</script>
```

El comando sustituye `__DATOS__` con JSON escapado para su inclusión en HTML.
No cambia el JSON de entrada ni el inventario.

## Contrato de datos, versión 1

| Campo raíz | Contenido |
| --- | --- |
| `schema_version` | Versión del contrato, actualmente `1`. |
| `survey` | Relevamiento, origen `[longitud, latitud]` si se conoce e indicador de datos sintéticos. |
| `counts` | Contadores del inventario. |
| `trees` | Lista de Features GeoJSON de árboles activos, incluidos los que tienen `geometry: null`. |
| `cameras` | Lista de Features de cámaras, fechas y enlaces a Mapillary. |
| `observations` | Lista de Features de detecciones, puntuaciones y recortes. |
| `groups` | Lista de Features de grupos pendientes. |

Cada Feature incluye `id`, `geometry` y `properties`. Las coordenadas GeoJSON
están en orden `[longitud, latitud]`. La API de Leaflet recibe `[latitud, longitud]`
cuando se llama a `setView`, `fitBounds` o `circle`; `L.geoJSON` interpreta el
GeoJSON directamente. Las coordenadas locales de `properties.fit.xy` están en
metros respecto al origen del relevamiento y no son latitud/longitud.

Los árboles tienen estado `properties.identity_status`, referencias
`properties.observation_ids` e incertidumbre heurística en
`properties.fit.uncertainty_m`, cuando hay posición estimada. Las observaciones
incluyen `properties.image_id`, `bbox_xyxy`, `score` y `evidence.url` si existe
un recorte. Los registros sin geometría deben mantenerse en una lista de
pendientes; no se debe inventar su posición ni usar la de su cámara como árbol.

El visor actual solo descarga un archivo de revisiones para aplicarlo después:
no modifica la base de datos desde el navegador.
