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
El servidor comparte solo las carpetas de exportación y escucha únicamente
en tu computadora. Cuando existe `manzana_tandil`, la abre por defecto;
el selector **Relevamiento** permite volver a la prueba de tres capturas.
Si el servidor estaba abierto antes de esta actualización, detenelo con Ctrl+C
y volvé a ejecutar el comando para cargar el nuevo enrutamiento.
Para servir el demo u otra alternativa:

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

## Alinear el relevamiento en todas las direcciones

El panel **Alineación del relevamiento** permite mover juntos cámaras, árboles,
grupos y líneas hacia el norte, sur, este u oeste. Los desplazamientos son
absolutos respecto del original; no se acumulan al pulsar Aplicar otra vez.

- **Este/oeste (m):** positivo hacia la derecha/este; negativo hacia la izquierda/oeste.
- **Norte/sur (m):** positivo hacia arriba/norte; negativo hacia abajo/sur.
- **Paso (m):** cantidad que avanza cada botón de flecha; permite ajustes finos.
- **Restablecer original:** vuelve a cero en ambos ejes.
- **Volver al ajuste del archivo:** recupera la calibración incluida en el HTML.

El archivo `calibracion_horizontal.json` que ya estaba en el proyecto indica
**23 m al este** para `tandil2018`. El visor actualizado conserva ese ajuste
como punto inicial, con 0 m al norte. No se sobrescribió el archivo del usuario.

Para centrar usando una cámara de referencia:

1. Seleccioná un cuadrado azul de cámara.
2. Elegí **Libre: ambas direcciones** y pulsá **Ubicar esta cámara en el mapa**.
3. Hacé clic donde debería estar. Todo el relevamiento acompaña ese movimiento.

El modo **Horizontal: mantener latitud** conserva la opción anterior: muestra
una línea azul a la altura de la cámara y toma solo la longitud del clic.
El mapa de fondo permanece fijo; no se consulta el trazado de las calles.

Los ajustes se recuerdan en el navegador cuando el almacenamiento local está
habilitado. Se recupera automáticamente el desplazamiento horizontal guardado
por la versión anterior. Los nuevos valores de ambos ejes se guardan juntos,
separados por relevamiento y origen. Esto es local al host/puerto del navegador.

**Descargar ajuste** guarda `calibracion_mapa.json`, versión 3, con posición,
ángulo y cámara de referencia. Las versiones 1 y 2 siguen siendo válidas:
la versión 1 se interpreta con norte=0 y ambas versiones anteriores con giro=0:

```bash
python -m mapeo.visualizacion \
  --datos resultados/mapeo/exportaciones/tandil2018/mapa_datos.json \
  --calibracion /ruta/calibracion_mapa.json
```

También podés especificar ambos desplazamientos. Por ejemplo, conservar 23 m al
este y sumar una corrección de 2 m hacia el sur:

```bash
python -m mapeo.visualizacion \
  --datos resultados/mapeo/exportaciones/tandil2018/mapa_datos.json \
  --offset-east-m 23 --offset-north-m -2
```

**Descargar GeoJSON ajustado** exporta las geometrías mostradas y la calibración
`map_calibration`. Los datos originales, SQLite y GeoJSON del algoritmo se
conservan. Los píxeles de las cajas, IDs, relaciones y conteos no cambian.
Al girar también se rotan las direcciones y los rumbos derivados del visor.
La corrección es visual y no confirma identidades ni precisión GPS.

El cálculo sigue separado en `mapeo/calibracion_horizontal.py` y
`mapeo/visores/calibracion_horizontal.js`; se conservaron los nombres para
compatibilidad. Usa los radios de curvatura WGS84 a la latitud de referencia
para convertir metros a incrementos de longitud y latitud. Los componentes
locales `x` e `y` se giran y trasladan por los mismos parámetros. Los datos
incluyen `map_calibration` y el alias anterior `horizontal_calibration`.

## Girar el relevamiento

En **Centro del giro** elegí una cámara. También podés seleccionarla en el mapa
y pulsar **Usar cámara seleccionada**. Esa cámara queda fija en su posición
corregida al variar el ángulo, y los demás puntos giran a su alrededor.

Usá **Rotación (°)** y Aplicar, o los botones **Horario** y **Antihorario**.
El paso inicial es 0,5° y se puede ajustar para movimientos más finos.
Un valor positivo gira en sentido horario; uno negativo, antihorario.
**Sin giro** vuelve a 0° conservando el desplazamiento este/norte actual.
**Restablecer original** elimina tanto el giro como los desplazamientos.

Es una rotación rígida en metros del plano local: conserva las distancias
entre puntos, mantiene el mapa de fondo fijo y gira conjuntamente cámaras,
árboles, grupos, rayos y sus direcciones. No escala ni deforma el relevamiento.
Cambiar de cámara de referencia conserva las ubicaciones mostradas: los
desplazamientos pueden variar para compensar el nuevo centro sin producir saltos.

El ángulo y la cámara de referencia se guardan con los ajustes del navegador
y en el archivo descargado. También podés generar un HTML desde la terminal:

```bash
python -m mapeo.visualizacion \
  --datos resultados/mapeo/exportaciones/tandil2018/mapa_datos.json \
  --offset-east-m 23 --rotation-deg 2 --pivot-camera-id 870050853581010
```

Las geometrías y metadatos de visualización incluyen `rotation_deg`,
`pivot_camera_id`, `pivot_xy` y `pivot_coordinates` en `map_calibration`.
Las coordenadas originales y la base del inventario permanecen intactas.

## Colores y formas

Cada árbol tiene su propio color de relleno, incluso cuando todos son candidatos.
Los colores se mantienen al filtrar o ajustar las coordenadas en el mismo visor.
El borde verde indica identidad confirmada; ámbar, candidato; rojo, revisión.
Las posiciones aproximadas tienen borde discontinuo. Las cámaras son cuadrados
azules y los grupos, rombos violetas. La incertidumbre se dibuja tenue debajo de
los puntos para no taparlos. Las listas incluyen una muestra del color de cada
registro.

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
`properties.observation_ids` y posición de visualización en
`properties.map_position`: incluye `xy`, `coordinates`, `method`,
`is_approximate`, `uncertainty_m`, `source_observation_ids` y `assumptions`.
`properties.fit` conserva el ajuste del inventario: puede seguir siendo nulo
aunque haya una ubicación exploratoria en el mapa. No se usa una ubicación
exploratoria para confirmar identidades o fusionar candidatos. Ver
[GUIA_UBICACION_APROXIMADA.md](GUIA_UBICACION_APROXIMADA.md).

El visor muestra los puntos aproximados con borde discontinuo y los grupos
en violeta. El control **Posiciones aproximadas** permite ocultarlos. Al
seleccionarlos aparecen los supuestos y una imagen de evidencia.
`map_position.lateral_constraint` describe el límite lateral respecto al avance
de la cámara. Incluye la posición original, el eje usado y el ajuste aplicado.
Este cálculo no usa datos del mapa de calles.
Las observaciones
incluyen `properties.image_id`, `bbox_xyxy`, `score` y `evidence.url` si existe
un recorte. Los registros sin geometría deben mantenerse en una lista de
pendientes si faltan los datos necesarios para calcular incluso una aproximación;
no se usa la posición de una cámara como si fuera la de un árbol.

El visor actual solo descarga un archivo de revisiones para aplicarlo después:
no modifica la base de datos desde el navegador.

## Recorrer fotografías de las cámaras

Al seleccionar una cámara azul con foto local se abre una ventana grande.
Los controles **↑ Adelante**, **↓ Atrás**, **← Izquierda** y **Derecha →**, o las
cuatro flechas del teclado, buscan cámaras cercanas según la posición y la
orientación de la fotografía actual. Cada dirección cubre un sector de 90°.
El visor elige una cámara próxima y alineada dentro de ese sector y hasta
30 metros de distancia. Las opciones sin destino quedan deshabilitadas.

Si hay otra fotografía a menos de 2 metros con una orientación diferente,
puede ofrecer **girar** en ese punto. Una cámara sin orientación conocida
no habilita las flechas espaciales. El rumbo se obtiene del compás calculado,
del original o, si faltan, de la rotación de Mapillary.

La navegación espacial puede conectar recorridos distintos del mismo día;
no salta automáticamente a imágenes de otra fecha. Las posiciones GPS son
aproximadas: esta proximidad no comprueba que exista un paso peatonal o una
conexión transitable entre los puntos.

**Por orden de captura** conserva los botones **Foto anterior** y **Foto
siguiente** dentro del mismo recorrido y día. El selector permite cambiar
de recorrido y fecha; el mapa sigue y resalta la cámara seleccionada.
**Esc**, **Cerrar** o **Volver al mapa** cierran la ventana.

Los controles **+**, **−** y **Ajustar** amplían la foto o la ajustan a la ventana.
Al ampliar se puede desplazar la imagen con las barras de desplazamiento.
Se conservan las cajas de DINO en las fotos anotadas y se muestra la fecha,
el autor y un enlace a Mapillary. La navegación utiliza las fotos disponibles
localmente; no descarga capturas adicionales ni reconstruye un panorama 360°.

`properties.photo.url` apunta a la miniatura y `properties.photo.full_url` a la
imagen grande. El procesador de la manzana genera los archivos grandes en
`capturas/grandes/`, con la resolución de la fuente descargada. Si falta la
imagen grande, el visor intenta cargar la miniatura e informa del reemplazo.
`properties.camera_view` contiene `bearing_deg` y `source`. El rumbo se gira
junto a las coordenadas cuando se aplica una calibración del mapa; desplazar
o rotar el relevamiento conserva el sentido de las cuatro direcciones.

La selección de vecinos está aislada en `RecorridoCamaras.vecinos`, en el módulo
de la galería. Sus valores por defecto pueden cambiarse desde `camera_navigation`
en el JSON del visor, por ejemplo:

```json
"camera_navigation": {
  "max_distance_m": 20,
  "min_distance_m": 1,
  "max_turn_distance_m": 2,
  "sector_half_angle_deg": 40
}
```

El semiancho de los sectores admite hasta 45°. Para reflejar estos cambios en
el HTML, regeneralo con `python -m mapeo.visualizacion --datos ruta/mapa_datos.json`.

Para actualizar las fotos y el HTML sin ejecutar detección ni asociación:

```bash
python procesar_manzana_tandil.py --preview-only
```

La galería y la agrupación de recorridos están separadas en
`mapeo/visores/recorrido_camaras.js`. El renderizador inserta ese módulo mediante
el marcador opcional `__RECORRIDO_JS__`; las plantillas alternativas pueden
omitirlo. La galería no modifica el inventario ni las coordenadas originales.

## Ampliar árboles y ocultar el panel

Al hacer clic en un árbol, tanto en el mapa como en la lista, se abre su recorte
de evidencia en una ventana grande. **Vista anterior / Vista siguiente** o las
flechas **← / →** recorren solamente las observaciones asociadas a ese árbol.
Los controles **+**, **−** y **Ajustar** permiten ampliar el recorte. **Ver foto
completa de la cámara** abre la captura correspondiente con su navegación
espacial, si esa cámara tiene una foto local. **Esc** o **Volver al mapa** cierran
la ventana. Si falta una imagen, se informa y se puede continuar a otra vista.

El botón **Ocultar panel derecho** de la barra superior permite ampliar el mapa.
Se convierte en **Mostrar panel derecho** para restaurarlo. La preferencia se
recuerda en el navegador y no cambia los ajustes de alineación. Los árboles y
las cámaras siguen abriéndose en grande con el panel oculto.

El visor de evidencias está separado en `mapeo/visores/evidencia_arboles.js`,
insertado mediante el marcador opcional `__EVIDENCIA_JS__`. Utiliza los recortes
ya exportados; no vuelve a ejecutar el detector ni modifica las asociaciones.
