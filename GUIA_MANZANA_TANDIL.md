# Capturas de Constitución, Av. Rivadavia, 25 de Mayo y Alberdi

La prueba se descarga en una carpeta separada del relevamiento de tres capturas:

```bash
cd /home/rodrigo/Downloads/agrotech
bash descargar_manzana_tandil.sh
```

El flujo completo ahora descarga, ejecuta DINO y genera el inventario y el mapa.
Mientras se procesa, publica una vista con todas las cámaras y sus fotografías.
Los resultados válidos de DINO se reutilizan al reintentar.

Si ya descargaste las imágenes, completá el procesamiento sin repetir la descarga:

```bash
conda run --name hackaton --no-capture-output python procesar_manzana_tandil.py
```

El mapa queda en `resultados/mapeo/exportaciones/manzana_tandil/mapa.html`.
Reiniciá el servidor si estaba corriendo con la versión anterior:

```bash
python -m mapeo.servidor_mapa
```

Abrí <http://127.0.0.1:8765/mapa.html>. El servidor abre la manzana por defecto
cuando está disponible. El selector **Relevamiento** permite volver a
`tandil2018` y sus ajustes. Solo se sirven las carpetas de exportación.
Al seleccionar una cámara azul, se muestra su fotografía y fecha de captura.

Para descargar y mostrar cámaras sin ejecutar DINO:

```bash
bash descargar_manzana_tandil.sh --download-only
```

El lanzador usa Conda `hackaton` y el token ya configurado en `.env.mapillary`.
La selección consulta las geometrías públicas de las cuatro calles alrededor
de la zona de Tandil usada anteriormente y calcula sus cruces. No supone
coordenadas de esquinas ni toma el centro del enlace como ubicación de captura.
Si no puede resolver cuatro cruces que formen una manzana acotada, termina
con error antes de descargar imágenes de un área incorrecta.

La consulta de calles se hace con
[Overpass QL](https://wiki.openstreetmap.org/wiki/Overpass_API/Overpass_QL).
Esta cartografía solo delimita la selección de imágenes: no participa en la
geolocalización de árboles, no modifica calibraciones ni sustituye los datos
de cámaras de Mapillary. Las calles se representan por los segmentos entre
sus cruces. Ante alternativas por calzadas separadas, se toma el cuadrilátero
convexo de menor área válido y se registra cuántas alternativas había.

Luego se consultan todas las páginas de capturas de Mapillary dentro del
rectángulo envolvente, se eliminan IDs repetidos y se filtran las posiciones
cercanas al perímetro de las cuatro cuadras. El margen inicial es **30 m**, para
incluir capturas desplazadas por GPS. Se evalúan tanto la posición calculada
como la original y se conserva la fuente que justificó la selección. Este
margen es de selección de cámaras y es independiente del límite lateral de
ubicación de árboles.

Las imágenes pueden mostrar ambas veredas y las esquinas cercanas. Seleccionar
una cámara junto al perímetro no prueba que todos los árboles de su imagen
pertenezcan a la parcela de esa manzana.

## Salidas

En `resultados/manzana_constitucion_rivadavia_25mayo_alberdi/`:

- `calles_overpass.json`: respuesta pública de calles en caché, reutilizada al reintentar.
- `zona.geojson`: polígono calculado, calles, origen y atribución cartográfica.
- `imagenes/`: fotografías JPG; las imágenes válidas ya descargadas se reutilizan.
- `manifest.json`: metadatos de Mapillary y criterio de selección de cada captura.
- `camaras.geojson`: posiciones de las fotografías seleccionadas.
- `resumen_descarga.json`: cantidades por calle, año y secuencia, y errores.
- `estado_descarga.json`: resultado de la ejecución y etapa si falla.

Si falla la consulta de calles o Mapillary, no se inventa un perímetro ni una
cantidad de imágenes. Un fallo de consulta de Mapillary conserva el manifest
anterior. Durante la descarga se guarda el avance para poder reintentar.
No se guardan tokens ni URLs de imagen con firmas temporales en el manifest.

Las fechas se conservan y resumen por año. No se agrupan ni deduplican árboles
entre años durante esta descarga: los registros corresponden a capturas.

## Opciones

Solo resolver la zona:

```bash
bash descargar_manzana_tandil.sh --solo-zona
```

Descargar hasta diez capturas para revisar el área:

```bash
bash descargar_manzana_tandil.sh --limit 10
```

El límite se aplica después del filtro de perímetro. Para todas, usá `--limit 0`
o ejecutá sin esa opción. El límite de 200 de cada página no limita el total.

Cambiar el margen o la carpeta:

```bash
bash descargar_manzana_tandil.sh --margin-m 25 --output resultados/manzana_prueba
```

Para ejecutar DINO sobre las imágenes descargadas:

```bash
conda run --name hackaton --no-capture-output python detectar_arboles.py \
  resultados/manzana_constitucion_rivadavia_25mayo_alberdi/imagenes \
  --manifest resultados/manzana_constitucion_rivadavia_25mayo_alberdi/manifest.json \
  --output resultados/manzana_constitucion_rivadavia_25mayo_alberdi/detecciones \
  --limit 0 --prompt 'tree.'
```

El inventario de prueba puede generarse por separado:

```bash
conda run --name hackaton --no-capture-output python mapear_arboles.py \
  --dataset resultados/manzana_constitucion_rivadavia_25mayo_alberdi \
  --output resultados/mapeo --relevamiento manzana_tandil
```

Revisá los períodos y secuencias del resumen antes de interpretar el conteo;
un mismo árbol en años diferentes no representa dos individuos actuales.
Las correcciones de alineación de una secuencia anterior no se trasladan
automáticamente a este relevamiento nuevo.
