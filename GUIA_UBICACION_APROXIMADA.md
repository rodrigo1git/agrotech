# Ubicar árboles aunque todavía no haya una triangulación fiable

`mapeo/ubicacion_aproximada.py` calcula posiciones exploratorias usando la
ubicación y la pose de la cámara, su calibración y las cajas de DINO.
Se ejecuta al exportar. No vuelve a ejecutar el detector, no cambia IDs,
no fusiona árboles y no convierte candidatos en confirmados.

## Métodos, en orden de preferencia

1. **Posición existente:** conserva `fit` cuando el inventario ya tiene una
   triangulación o una ubicación manual. Nunca la reemplaza por un supuesto.
2. **Triangulación básica:** si una identidad ya tiene observaciones asociadas
   en cámaras distintas, prueba un mínimo de 2° de paralaje y hasta 5° de
   error angular. Solo usa evidencia de esa identidad, con fechas compatibles.
   No busca cruces arbitrarios con cajas pertenecientes a otros candidatos.
3. **Suelo plano:** toma el centro inferior de la caja, obtiene su rayo 3D
   con la pose y la calibración y lo cruza con un plano de suelo. Supone una
   cámara a **1,7 m** sobre ese suelo. Para una depresión `beta` bajo el
   horizonte, la distancia horizontal es `R = 1,7 / tan(beta)`. Requiere
   al menos 2° bajo el horizonte, una distancia entre 2 y 100 m y que el
   borde inferior de la caja no esté cortado por la imagen.
4. **Altura aparente:** cuando el plano de suelo es inestable, supone un
   árbol vertical de **8 m**. Usa la diferencia entre las pendientes verticales
   de los rayos superior e inferior: `R = H / (pendiente_superior - pendiente_inferior)`.
   La caja debe representar un individuo y no estar cortada arriba ni abajo.
5. **Distancia supuesta:** si tampoco hay una extensión completa, usa **15 m**
   sobre la dirección del pie de caja. Esta distancia se identifica
   explícitamente como supuesta. También puede servir como punto representativo
   de un grupo, que sigue siendo un grupo sin cantidad de individuos resuelta.

Las distancias por altura se limitan al rango configurado. Si una caja pequeña
produce más de 100 m, se exporta a 100 m con la advertencia
`distance_clamped_to_configured_range` y una incertidumbre heurística ampliada.
Si faltan posición, calibración u orientación válidas, se conserva el caso sin
punto. No se asigna una dirección al azar.

Las hipótesis de suelo, tronco y altura pueden fallar: las cajas pueden contener
solo la copa, el suelo puede tener pendiente y los árboles tienen alturas
diferentes. `altitude` y `computed_altitude` no se interpretan como altura de
montaje de la cámara sobre el suelo. La altura de 1,7 m es un supuesto explícito.

La implementación usa la cámara perspectiva y sus parámetros `[focal, k1, k2]`
descritos por [MapillaryJS](https://mapillary.github.io/mapillary-js/api/interfaces/api.CameraEnt/).
Las alturas y reglas de aproximación anteriores son hipótesis de este proyecto.

## Evitar que las aproximaciones se desvíen hacia el interior de la manzana

`mapeo/limite_lateral.py` limita el desplazamiento lateral respecto del avance
de la cámara a **6 m por cada lado**, sin consultar OpenStreetMap ni geometrías
de calles. No es un radio de 6 m: un árbol puede estar bastante más adelante
y mantenerse a menos de 6 m hacia el costado.

La referencia se calcula con las cámaras vecinas de la misma secuencia y año.
Se usan posiciones temporalmente próximas con suficiente separación, respetando
los límites de distancia y tiempo del relevamiento. En curvas se usa una
dirección local. Si no hay una trayectoria utilizable, se supone que el rumbo
óptico de la cámara coincide con el avance y se registra esa suposición.
Si tampoco hay una orientación válida, el límite no se aplica y se informa.

Para una posición relativa a su cámara se calculan sus componentes hacia adelante
`a` y lateral `l`. Si `|l| > X`, se multiplica la distancia por `X / |l|`.
Así se conserva el mismo lado y la dirección de la detección; también se reduce
el avance. Ejemplo: un punto a 100 m hacia adelante y 20 m al costado queda a
30 m hacia adelante y 6 m al costado con `X=6`. No se desplaza perpendicularmente
rompiendo la dirección de observación.

El ajuste solo se aplica a posiciones exploratorias. Se conservan las
triangulaciones previas, las posiciones manuales, las identidades y el conteo.
No implica que exista una vereda en el punto resultante: limita la deriva de
la aproximación usando únicamente las cámaras.

Cada punto contiene `lateral_constraint`, con el eje de referencia, el punto
original (`raw_xy`, `raw_coordinates`), los desplazamientos antes/después y
`applied`. La incertidumbre no se reduce por haber acercado el marcador:
los círculos de incertidumbre pueden seguir extendiéndose fuera de esa franja.

Para cambiar **solo esta exportación**, sin modificar SQLite ni ejecutar DINO:

```bash
python mapear_arboles.py --output resultados/mapeo --relevamiento tandil2018 \
  --export-only --max-lateral-distance 4
```

Recargá el mapa después. El número indica metros hacia cada lado del avance.
Para comparar con el resultado sin esta restricción:

```bash
python mapear_arboles.py --output resultados/mapeo --relevamiento tandil2018 \
  --export-only --no-lateral-limit
```

El resultado actual usa 6 m y ajusta dos candidatos que antes estaban a 7,77 m
y 12,58 m laterales respecto de sus respectivas cámaras y ejes locales.

## Datos exportados

Los puntos aparecen en `arboles.geojson`, `grupos.geojson` y `mapa_datos.json`.
`properties.map_position` incluye:

- `coordinates`: longitud/latitud; `xy`: metros respecto al origen.
- `method`: método de localización.
- `is_approximate`: distingue estas aproximaciones de las posiciones previas.
- `used_for_identity: false`: no se usó el supuesto para confirmar ni fusionar.
- `assumptions`: alturas, suelo o distancia supuestos, según el método.
- `distance_m`, `source_pixel`, `source_image_ids`, `source_observation_ids`:
  permiten revisar cómo se ubicó el punto.
- `warnings`: problemas detectados, incluido el límite de distancia.
- `uncertainty_m`: magnitud heurística, no intervalo estadístico calibrado.

`inventario.json` conserva los árboles y ajustes del inventario, y añade
`map_positions`, indexado por ID. `observaciones.geojson` conserva sus líneas
de dirección; `properties.map_position` agrega el punto aproximado de cada
detección sin reemplazar la geometría de la línea.

Los contadores `arboles_con_punto_mapa`, `arboles_con_ubicacion_aproximada`,
`arboles_sin_punto_mapa` y `grupos_con_punto_mapa` describen la visualización.
Los conteos de confirmados mantienen su criterio anterior.

## Volver a generar el mapa actual

```bash
python mapear_arboles.py \
  --output resultados/mapeo \
  --relevamiento tandil2018 \
  --export-only
```

Después recargá <http://127.0.0.1:8765/mapa.html>. Si el servidor no está iniciado:

```bash
python -m mapeo.servidor_mapa
```

Para las tres capturas actuales hay nueve puntos de candidatos: dos conservan
la triangulación, uno usa suelo plano y seis usan altura aparente. Los dos
grupos se muestran aparte; uno usa suelo plano y el otro distancia supuesta.

## Ajustar las hipótesis

Los valores están en `configuracion_mapeo.json`:

| Parámetro | Valor inicial |
| --- | --- |
| `allow_approximate_positions` | `true` |
| `allow_lateral_limit` | `true` |
| `approx_max_lateral_distance_m` | `6.0` |
| `approx_camera_height_m` | `1.7` |
| `approx_tree_height_m` | `8.0` |
| `approx_default_distance_m` | `15.0` |
| `approx_min_range_m` | `2.0` |
| `max_range_m` | `100.0` |
| `approx_min_ground_angle_deg` | `2.0` |
| `approx_uncertainty_floor_m` | `5.0` |
| `approx_relative_uncertainty` | `0.6` |

La incertidumbre mantiene un piso GPS y considera el ancho angular de la caja
y la fracción relativa configurada de la distancia. Para distancias supuestas
o limitadas al rango, se amplía al menos al valor de esa distancia.

Para aplicar cambios de configuración al relevamiento, ejecutá el mapeo sin
`--export-only`, `--dataset` ni `--inferir`. Registra la configuración y vuelve
a reconciliar/exportar la evidencia ya guardada; no ejecuta DINO:

```bash
python mapear_arboles.py --output resultados/mapeo --relevamiento tandil2018
```

`--export-only` conserva la configuración almacenada del relevamiento, salvo
los ajustes temporales explícitos `--max-lateral-distance` y `--no-lateral-limit`. Los
relevamientos antiguos que no tenían estas claves usan los valores iniciales
del módulo. Para volver al comportamiento de solo posiciones del inventario,
configurá `allow_approximate_positions: false` y aplicá la configuración como
se indica arriba. El visor también permite ocultar los aproximados sin cambiar
ningún archivo.
