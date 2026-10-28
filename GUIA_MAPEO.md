# Inventario y mapa de árboles

El mapeo mantiene `tree.` y reutiliza los resultados de Grounding DINO y
Mapillary. Guarda identidades persistentes en SQLite, revisa correspondencias
entre capturas y exporta un mapa local. Las detecciones no se suman directamente
como árboles: individuos, grupos, cámaras y observaciones se almacenan separados.

## Ejecutar con las imágenes ya procesadas

Desde la carpeta del proyecto, con `hackaton` activo:

```bash
conda activate hackaton
python mapear_arboles.py --dataset resultados/mapillary_870050853581010 --relevamiento tandil2018 --output resultados/mapeo
```

Si tenés `(.venv)` y `(hackaton)` superpuestos, salí de `.venv` con `deactivate`
y volvé a activar `hackaton`. También podés ejecutar directamente
`/home/rodrigo/.conda/envs/hackaton/bin/python`.

El entorno existente ya tiene NumPy y Pillow; no se agregaron instalaciones
fuera del proyecto. Para preparar otro entorno se incluye
`requirements-mapeo.txt`. La geometría y el mapa usan NumPy y la biblioteca
estándar; la vista de calles se carga opcionalmente con Leaflet/OpenStreetMap.

### Resultado real disponible

La captura `870050853581010` es de 2018. Hay una única imagen disponible:
el mapa muestra su cámara y permite revisar cinco observaciones, tres
candidatos individuales y dos grupos pendientes. No hay suficientes puntos
de vista para localizar y confirmar los árboles. `arboles.geojson` queda vacío
hasta que existan posiciones justificables. Eso no significa que no haya árboles.

Mapa generado:
`resultados/mapeo/exportaciones/tandil2018/mapa.html`.

## Descargar más imágenes y mapear en una ejecución

El token local configurado para Mapillary se sigue leyendo automáticamente.

Para las tres capturas seleccionadas (`870050853581010`, `500511691078373`
y `286871449741145`) hay una ejecución preparada:

```bash
bash mapear_capturas_tandil.sh
```

Usa el Python de `hackaton`, descarga las imágenes en
`resultados/mapillary_tres_capturas`, ejecuta DINO con `tree.` y actualiza el
inventario `tandil2018`. El mapa se exporta a
`resultados/mapeo/exportaciones/tandil2018/mapa.html`.
El nombre del inventario es el identificador existente; las fechas reales se
consultan en los metadatos y las capturas de años distintos no se asocian
automáticamente. Las coordenadas `lat/lng` del enlace del visor no son las
posiciones de las tres cámaras. La ejecución necesita acceso a Mapillary;
no se incorporan imágenes ni posiciones ficticias cuando la descarga falla.

```bash
python mapillary_arboles.py --sequence NJ3FOf5KSUix2TaldBz7Jw --limit 20 --output resultados/mapillary_secuencia_mapeo --map --relevamiento tandil2018 --map-output resultados/mapeo
```

La selección por secuencia empieza por los resultados que entregue la API;
puede abarcar más que la cuadra de la captura inicial. Usá `--bbox` si necesitás
limitar la zona. Comprobá la cobertura y las fechas antes de interpretar el mapa.
Se requieren imágenes desde posiciones distintas, con suficiente solapamiento.

Si la descarga ya está hecha pero falta ejecutar DINO:

```bash
python mapear_arboles.py --dataset resultados/mapillary_secuencia_mapeo --inferir --relevamiento tandil2018 --output resultados/mapeo
```

`--inferir` utiliza `tree.`, umbral de cajas 0.35 y umbral de texto 0.25.
Agregá `--device cpu` para forzar CPU. La primera inferencia necesita descargar
el modelo si todavía no está en caché. Mapear resultados existentes no necesita
conexión con Mapillary ni volver a ejecutar el detector.

Se pueden importar varios datasets:

```bash
python mapear_arboles.py --dataset resultados/lote1 resultados/lote2 --relevamiento tandil2018 --output resultados/mapeo
```

Cada carpeta debe contener `manifest.json`, `imagenes/` y `detecciones/`.
El importador respeta la selección del manifest, valida resolución y hash si
hay imagen local, y ordena por fecha. No identifica árboles por nombre de archivo.
Un relevamiento debe representar una zona acotada; no se mezclan automáticamente
observaciones de años distintos ni datos sintéticos con capturas reales.

## Salidas

```text
resultados/mapeo/
  inventario.sqlite
  exportaciones/
    tandil2018/
      mapa.html
      inventario.json
      arboles.geojson
      camaras.geojson
      observaciones.geojson
      grupos.geojson
      estadisticas.json
      errores.json
      evidencia/
```

- **SQLite:** imágenes, ejecuciones activas y anteriores, observaciones crudas,
  observaciones derivadas, árboles, grupos, asociaciones, correcciones y eventos.
  Conservá la base para continuar el inventario; no la reemplaces por el GeoJSON.
  Si copiás la base mientras se usa, empleá el backup de SQLite; no copies solo
  el archivo principal ignorando sus archivos WAL.
- **`inventario.json`:** snapshot del relevamiento, registros activos e históricos,
  estados, observaciones y decisiones con evidencia. Incluye individuos sin ubicación.
- **`arboles.geojson`:** individuos activos con coordenadas estimadas. Sus estados
  distinguen confirmados, candidatos y posiciones que necesitan revisión.
- **`camaras.geojson`:** ubicaciones de captura, no posiciones de árboles.
- **`observaciones.geojson`:** direcciones desde las cámaras; su longitud dibujada
  es configurable y no es una medición de distancia al árbol. Geometría nula
  cuando faltan datos de cámara.
- **`grupos.geojson`:** grupos y alternativas sin resolver; normalmente geometría
  nula. No se crea un punto arbitrario en el centro de un grupo.
- **`estadisticas.json`:** conteos separados de confirmados, candidatos, grupos,
  duplicados probables y observaciones sin geometría.
- **`errores.json`:** datasets incompletos o inválidos. Una salida parcial con
  errores termina con código distinto de cero.
- **`evidencia/`:** recortes para revisar las observaciones sin alterar los originales.

El estado se guarda antes de exportar después de cada imagen importada. Volver
a ejecutar la misma importación no suma observaciones ni entidades. Si cambian
los resultados, se activa la nueva versión y se conserva la anterior. Las
correspondencias claras con cajas de la misma imagen permiten conservar IDs
al revisar una ejecución; situaciones ambiguas necesitan revisión.

## Usar el mapa

Abrí `mapa.html` en el navegador. La vista local funciona sin conexión y muestra
posiciones en metros, norte, incertidumbre y cámaras. Los puntos verdes tienen
identidad confirmada, los naranjas son candidatos y los azules son cámaras.
Los grupos y los individuos sin ubicación aparecen en la lista.

Con **Cargar mapa de calles** se descargan Leaflet y las teselas de OpenStreetMap;
esa vista necesita conexión. **Vista local** vuelve al plano sin mapa base.
Podés filtrar por fecha y tipo, buscar un ID y abrir cada captura en Mapillary.
Si coinciden dos puntos, seleccioná sus registros desde la lista: no se alteran
las coordenadas para aparentar una separación.

Seleccionar un árbol muestra sus observaciones y estado. El score de DINO no
es un porcentaje de certeza de identidad. Los círculos de incertidumbre son
estimaciones heurísticas de sensibilidad, no intervalos estadísticos calibrados.

## Anclas y revisión de identidad

Una caja de copa no fija un punto físico preciso. Para triangulación fiable,
marcá en varias capturas un punto consistente del mismo ejemplar, por ejemplo
un punto visible del tronco. No uses puntos diferentes de la copa como si fueran
el mismo lugar. En el mapa:

1. Abrí una observación y escribí el motivo de la corrección.
2. Hacé clic sobre el recorte para marcar el punto del tronco.
3. Repetí en otras capturas del mismo árbol.
4. Descargá las revisiones y aplicalas:

```bash
python mapear_arboles.py --correcciones /ruta/correcciones.json --relevamiento tandil2018 --output resultados/mapeo
```

El archivo HTML no modifica directamente SQLite. También permite preparar
confirmaciones o rechazos manuales. Las anclas se guardan como correcciones;
la reconciliación y la revisión quedan en una sola transacción reversible.

La confirmación automática exige por defecto tres capturas útiles distintas,
anclas verificadas, pose completa coherente y calidad geométrica suficiente.
Las cajas sin anclas pueden producir posiciones aproximadas de candidatos,
pero no se confirman automáticamente. Si hay correspondencias rivales similares,
se guarda una ambigüedad en lugar de forzar la asociación.

Estos parámetros son valores iniciales que deben calibrarse sobre la zona.
No hay una garantía de exactitud métrica basada únicamente en este umbral.

## Dividir un registro o un grupo

Los IDs de árbol, grupo y observación están en el mapa y en `inventario.json`.
Los IDs de observación cambian entre ejecuciones del detector; usá los activos
del inventario actual. Una división explícita necesita evidencia individual
distinta para cada hijo y una justificación. Ejemplo de archivo de revisión:

```json
{
  "actions": [
    {
      "type": "split",
      "parent_id": "ID_DEL_ARBOL_O_GRUPO",
      "reason": "Dos troncos distintos comprobados en vistas vecinas",
      "children": [
        {"observation_ids": ["OBS_A1", "OBS_A2"], "confirmed": true},
        {"observation_ids": ["OBS_B1", "OBS_B2"], "confirmed": true}
      ]
    }
  ]
}
```

Reemplazá los IDs por registros reales. `confirmed: true` expresa una decisión
manual de identidad; no convierte una posición desconocida en conocida.
Si el rol de una observación es incorrecto, revisalo primero con una acción
`{"type":"set_kind","target":"OBS_ID","kind":"individual","reason":"..."}`.
Los roles admitidos son `individual`, `group`, `duplicate` y `rejected`.

La división retira al padre del inventario activo y no copia su caja amplia
como confirmación de ambos hijos. Si ya existían candidatos para esos hijos,
se reemplazan sus registros automáticos. Dos individuos pueden conservar
coordenadas estimadas coincidentes: la coordenada no es una clave única.
Opcionalmente un hijo puede incluir `coordinates: [lon, lat]` como posición
revisada manualmente; se registra como tal, sin precisión inventada.

Si las nuevas vistas y anclas respaldan dos individuos en una caja antes
considerada individual, el sistema puede reclasificar esa observación como grupo
y reemplazar el candidato anterior. Si ninguna vista permite separarlos,
el grupo permanece pendiente.

## Fusionar, rechazar y deshacer

Otras acciones de revisión:

```json
{"actions":[
  {"type":"merge","tree_ids":["ID_CANONICO","ID_DUPLICADO"],"reason":"La evidencia corresponde al mismo ejemplar"}
]}
```

El primer ID permanece canónico; el otro queda reemplazado. No se fusionan
automáticamente individuos por estar a menos de una cantidad fija de metros.
`confirm` y `reject` usan `target` y `reason`.

Cada corrección imprime su ID de evento. Para revertir el último cambio:

```bash
python mapear_arboles.py --deshacer ID_EVENTO --relevamiento tandil2018 --output resultados/mapeo
```

La reversión falla si hubo cambios posteriores, para no sobrescribir evidencia
nueva. El historial se conserva. Una reconciliación automática también puede
revertirse si es el último evento; una nueva reconciliación podría volver a
proponerla, por lo que una discrepancia debe quedar registrada como revisión.
Varias acciones de un archivo se aplican en transacciones separadas; si una
falla, las anteriores ya aplicadas permanecen registradas.

Para volver a generar archivos sin modificar asociaciones:

```bash
python mapear_arboles.py --export-only --relevamiento tandil2018 --output resultados/mapeo
```

## Geometría soportada y configuración

Se implementa perspectiva con focal normalizada, distorsión radial y rotación
eje-ángulo mundo→cámara de OpenSfM. Se verifica su coherencia con el rumbo de
Mapillary. No se sustituye un rumbo válido de 0°, ni se inventa FOV o distancia.
Una orientación EXIF/crop no verificada necesita una transformación explícita
`pixel_transform` hacia los píxeles originales. Las correcciones `set_camera`
admiten esos campos de calibración con procedencia documentada por `reason`.

El adaptador esférico está probado con geometría controlada, pero deshabilitado
por defecto hasta verificar las convenciones de un panorama real de la zona.
Fisheye queda como geometría pendiente. Varias vistas de una misma captura
comparten `capture_id` y no aportan triangulación independiente.

Los cálculos usan un plano ENU sobre el elipsoide WGS84 con inversa sobre la
superficie. La extensión máxima inicial es 3 km; crear relevamientos separados
para zonas mayores. El piso de error GPS no disminuye automáticamente al sumar
fotos correlacionadas. Los puntos de observación se usan en planta; no se está
reconstruyendo el árbol completo en 3D.

`configuracion_mapeo.json` contiene los umbrales iniciales. Un JSON de cambios
parciales se puede pasar mediante `--config`; las modificaciones quedan
versionadas en el relevamiento. No contiene credenciales. Para exportar o
deshacer se respeta la configuración que quedó persistida.

## Demostración y validación

```bash
python mapear_arboles.py --demo --output resultados/demo_mapeo
```

La demo crea una escena **sintética**, con dos árboles separados por 2 m y una
observación inicial agrupada. No ejecuta DINO sobre fotos reales ni demuestra
precisión GPS. Genera su propia referencia y un mapa separado, identificado
como sintético. El resultado esperado es dos identidades confirmadas y un
grupo resuelto, sin dejar un tercer árbol activo.

```bash
python -m unittest discover -s tests -v
```

Se prueban geometría, asignación, reanudación, cambios de ejecución, grupos,
divisiones, fusiones, reversión, coordenadas coincidentes y exportación.
La sintaxis y la lógica de renderizado, filtros y preparación de revisiones se
verificaron con Node y un DOM simulado. La prueba de captura
de pantalla con Firefox headless no pudo completarse en esta sesión; queda
pendiente la comprobación visual en un navegador normal.

Para medir identidad real y error de ubicación, preparar una referencia manual:

```json
{
  "trees": [{"id": "REFERENCIA_A", "coordinates": [-59.14, -37.33]}],
  "observations": [{"image_id": "ID_MAPILLARY", "detection_index": 0, "tree_id": "REFERENCIA_A"}]
}
```

Las correspondencias se anotan sobre la versión activa de detecciones;
`detection_index` empieza en cero. `coordinates` es opcional si solo se evalúa
identidad. Ejecutar con `--validacion referencia.json` genera `validacion.json`:
fusiones falsas, separaciones falsas, referencias sin correspondencia y error
de posición solo para asociaciones inequívocas. No se busca el vecino más
cercano para aparentar una geolocalización correcta.

La validación de una cuadra real con múltiples vistas sigue pendiente de obtener
esas capturas y una referencia verificable. La apariencia de las copas se revisa
en los recortes; no se añadió un modelo de reidentificación visual entrenado.
