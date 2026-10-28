# Primera prueba de detección de árboles

El script `detectar_arboles.py` ejecuta Grounding DINO Tiny sin entrenamiento
propio. Recibe imágenes locales y guarda cajas y puntajes. El modelo y el
procesador se cargan una sola vez por ejecución. El JSON COCO no es necesario
para esta primera inferencia: servirá después para evaluar las predicciones.

Para obtener imágenes y metadatos directamente de Mapillary, seguí
[GUIA_MAPILLARY.md](GUIA_MAPILLARY.md). El detector admite `--manifest` para
conservar los datos de captura de esa fuente junto con las predicciones.

## Preparar el entorno

Para usar el entorno Conda `hackaton`, ejecutá:

```bash
bash preparar_hackaton.sh
```

El instalador agrega Python 3.12 y pip a `hackaton`, instala las dependencias y
verifica sus importaciones. Después activá el entorno y elegí su intérprete en
VS Code:

```bash
conda activate hackaton
```

La preparación debe ejecutarse desde una terminal con permisos de escritura
sobre el entorno Conda. El instalador no descarga todavía los pesos del modelo.

Como alternativa, para usar un entorno `venv` del proyecto:

Desde la terminal de VS Code, en la carpeta del proyecto:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-grounding.txt
```

En VS Code seleccioná `.venv/bin/python` mediante **Python: Select Interpreter**.
La instalación de PyTorch puede descargar archivos grandes. Si tu versión de
Python no tiene paquetes compatibles, creá el entorno con Python 3.12 o 3.13.
Para una instalación específica de CUDA o de CPU, seguí el selector de PyTorch:
https://pytorch.org/get-started/locally/

La primera ejecución también descarga el modelo y el procesador desde Hugging
Face. Las ejecuciones siguientes reutilizan la caché local.

## Probar entradas

Extraé las imágenes de la descarga, por ejemplo dentro de `imagenes/`. El script
busca también en subcarpetas e ignora ZIP y descargas incompletas.

```bash
python detectar_arboles.py imagenes --dry-run --limit 3
```

Esta comprobación no requiere PyTorch ni Transformers ni descarga el modelo.

## Ejecutar la detección

Primero una imagen:

```bash
python detectar_arboles.py imagenes --limit 1 --output resultados/prueba1
```

Después una muestra de diez:

```bash
python detectar_arboles.py imagenes --limit 10 --output resultados/prueba10
```

Se puede pasar la ruta de una imagen en lugar de una carpeta. Usa CUDA si está
disponible; para forzar CPU agregá `--device cpu`. Procesar imágenes en CPU puede
ser lento. `--limit 0` procesa todas las imágenes compatibles.

## Resultados

Para una entrada `foto.jpg`, el script genera:

- `foto.jpg.png`: imagen con cajas y etiquetas.
- `foto.jpg.json`: coordenadas y puntajes de cada detección.
- `resumen.json`: configuración y listado de imágenes procesadas y errores.

Se conservan las subcarpetas de entrada. Al repetir una ejecución en la misma
carpeta de salida se reemplazan los resultados con los mismos nombres; usá una
carpeta distinta para cada experimento. El script excluye la carpeta de salida
de la búsqueda de entradas.

El JSON por imagen es un formato propio, no un dataset COCO completo.
`bbox_xyxy` representa `[x1, y1, x2, y2]`; `bbox_coco` representa
`[x, y, ancho, alto]`. Las coordenadas son píxeles de la imagen original,
con origen arriba a la izquierda. `score` es un puntaje del modelo, no una
probabilidad calibrada de que la detección sea correcta.

## Ajustar y revisar

```bash
python detectar_arboles.py imagenes --limit 10 --threshold 0.25 --output resultados/umbral025
python detectar_arboles.py imagenes --limit 10 --threshold 0.45 --output resultados/umbral045
```

Un umbral más bajo conserva más detecciones y puede aumentar los falsos
positivos. Revisá árboles omitidos, arbustos confundidos y varios árboles
agrupados en una caja. El valor por defecto de `--prompt` es `tree.`; podés
comparar otros textos, por ejemplo `--prompt "a tree."`.

Esta versión procesa las imágenes como vistas planas. Todavía no convierte
panoramas a perspectiva ni fusiona duplicados entre vistas. La cantidad de
detecciones no equivale necesariamente a la cantidad real de árboles.

## Referencias

- Modelo: https://huggingface.co/IDEA-Research/grounding-dino-tiny
- API: https://huggingface.co/docs/transformers/model_doc/grounding-dino
