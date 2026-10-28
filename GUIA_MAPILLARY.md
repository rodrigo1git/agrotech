# Mapillary como fuente de imágenes para Grounding DINO

Para construir el inventario persistente y el mapa después de detectar,
consultá [GUIA_MAPEO.md](GUIA_MAPEO.md). La integración admite `--map`,
`--map-output` y `--relevamiento`.

La integración descarga imágenes y metadatos de la API v4 de Mapillary y llama
al detector con el mismo Python que ejecutó el comando. Usa el entorno Conda
`hackaton` ya preparado y no agrega dependencias: para descargar necesita Pillow
y la biblioteca estándar; para detectar usa PyTorch y Transformers.

## Configurar acceso

Creá una aplicación y obtené tu token de acceso en:
https://www.mapillary.com/dashboard/developers

Desde la carpeta del proyecto:

```bash
conda activate hackaton
read -r -s -p 'Token Mapillary: ' MAPILLARY_TOKEN
export MAPILLARY_TOKEN
printf '\n'
```

Pegá el token cuando la terminal lo solicite. Solo queda en la variable de esa
terminal. No hace falta guardarlo en el código ni enviarlo por el chat.

También se admite un archivo local `.env.mapillary` junto al script, con una
línea `MAPILLARY_TOKEN=tu_token`. Si ya está configurado, no necesitás exportar
la variable. El archivo está excluido mediante `.gitignore`; mantené sus
permisos restringidos. La variable de entorno tiene prioridad sobre el archivo.

## Elegir imágenes

Se admite una de estas selecciones por ejecución:

- `--image-id`: uno o varios identificadores numéricos de imagen. Se pueden
  obtener del parámetro `pKey` en un enlace de Mapillary.
- `--sequence`: identificador de una secuencia de captura.
- `--bbox`: rectángulo geográfico, en orden **oeste sur este norte**, con
  longitudes y latitudes en grados decimales.

Los valores `ID_IMAGEN` e `ID_SECUENCIA` de los ejemplos se reemplazan por IDs
reales. La selección por zona no garantiza que todas las fotos correspondan a
la misma calle o fecha; revisá los metadatos o usá una secuencia.

Primero probá solo la descarga de una imagen:

```bash
python mapillary_arboles.py --image-id ID_IMAGEN --download-only --output resultados/mapillary_prueba
```

Para descargar imágenes de una secuencia y ejecutar DINO:

```bash
python mapillary_arboles.py --sequence ID_SECUENCIA --limit 10 --output resultados/mapillary_secuencia
```

Ejemplo de selección por zona (las coordenadas son ilustrativas; comprobá la
cobertura antes de usarlas):

```bash
python mapillary_arboles.py --bbox -58.382 -34.606 -58.379 -34.603 --limit 10 --output resultados/mapillary_zona
```

`--limit` vale 10 por defecto; limita imágenes seleccionadas, incluyendo las
que fallen al descargarse. `--limit 0` recorre todos los resultados disponibles.
Se respetan las páginas de la API y se omiten IDs repetidos. Las imágenes que
ya están descargadas y se pueden abrir se reutilizan. Se utiliza la variante
`thumb_2048_url`; no es necesariamente la resolución original.

También se admiten `--device cpu`, `--device cuda`, `--prompt`, `--threshold` y
`--text-threshold`. Por defecto se busca `tree.` y se selecciona CUDA si está
disponible. Los pesos de DINO se descargan la primera vez que se ejecuta el
detector, no durante `--download-only`.

## Archivos generados

```text
resultados/mapillary_secuencia/
  imagenes/
    ID.jpg
  manifest.json
  camaras.geojson
  detecciones/
    ID.jpg.png
    ID.jpg.json
    observaciones.geojson
    resumen.json
```

`manifest.json` enlaza cada archivo local con su ID, secuencia, fecha, posición,
orientación, tipo de cámara, parámetros disponibles, autor y enlace a Mapillary.
Los campos que la API no entregue no se inventan. No guarda el token ni las
URLs de descarga temporales. Conservá los metadatos de autoría y el enlace a
la captura junto con los resultados; consultá los términos de Mapillary para
el uso de las imágenes.

`camaras.geojson` contiene puntos de **cámaras**, usando `computed_geometry`
cuando es válido y `geometry` como alternativa. Si no hay posición válida,
la geometría queda en `null`. Podés abrirlo en QGIS. Se actualiza al descargar
cada imagen y no representa posiciones de árboles.

Los JSON de detecciones incluyen una sección `mapillary` con los metadatos.
`width` y `height` del resultado son el tamaño de la imagen realmente analizada;
los campos homónimos de `mapillary` son los valores originales de la API. Las
cajas están expresadas en píxeles de la imagen analizada.

`observaciones.geojson` se actualiza durante la detección y contiene una entrada
por caja, con `observation_id`, enlace a la imagen y `geolocation_status=pending`.
Su geometría es `null`: todavía no se ha estimado la posición del árbol. Es un
registro de observaciones, no un conteo de árboles únicos. Los identificadores
de observación corresponden a la imagen y al orden de detección de esa ejecución;
no deben usarse como identidades permanentes de árboles.

Esta integración todavía analiza panoramas como imágenes planas, sin extraer
perspectivas. Para geolocalizar y evitar duplicados falta asociar observaciones
entre vistas, comprobar la calibración y estimar las posiciones. No se asigna
el GPS de la cámara a los árboles.

## Repetir la detección sin consultar la API

Después de descargar, podés volver a ejecutar DINO sin token de Mapillary:

```bash
python detectar_arboles.py resultados/mapillary_secuencia/imagenes --manifest resultados/mapillary_secuencia/manifest.json --limit 0 --output resultados/mapillary_secuencia/detecciones_nuevas
```

Con `--manifest` se procesan solo las imágenes de esa selección, aunque la
carpeta contenga imágenes de ejecuciones anteriores. Para verificar las rutas
sin cargar el modelo, agregá `--dry-run`.

Usá una carpeta de salida distinta por zona o experimento. Repetir una descarga
en la misma salida reemplaza el manifest y el GeoJSON de cámaras con la selección
actual. Repetir una detección reemplaza resultados con los mismos nombres.

## Verificación local de la integración

```bash
python -m unittest discover -s tests -p 'test_mapillary.py' -v
```

Estas pruebas usan respuestas simuladas; no requieren token ni descargan pesos.

## Referencias oficiales

- API: https://www.mapillary.com/developer/api-documentation/
- Campos de imágenes: https://mapillary.github.io/mapillary-python-sdk/docs/mapillary.config.api/mapillary.config.api.entities/
- Autenticación: https://github.com/mapillary/mapillary-python-sdk/blob/main/src/mapillary/models/client.py
