"""Contrato independiente del visor y carga del mapa, sin servicios externos."""

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from mapeo.visualizacion import exportar_mapa, renderizar_mapa


DATOS = {
    "survey": {"id": "visor", "origin": [-59.14, -37.335]},
    "counts": {}, "cameras": [], "observations": [], "groups": [],
    "trees": [{"type": "Feature", "id": "arbol-1",
               "geometry": {"type": "Point", "coordinates": [-59.141, -37.336]},
               "properties": {"kind": "tree", "fit": {"xy": [1, 2]}, "identity_status": "confirmed"}}],
}

DOM = r'''
class Elemento {
 constructor(tag){this.tag=tag;this.children=[];this.style={};this.value='';this.checked=true;this.textContent='';this.listeners={};this.open=false;this.clientWidth=1000;this.clientHeight=700;this.attributes={};const clases=new Set();this.classList={toggle(k,valor){const activo=valor??!clases.has(k);if(activo)clases.add(k);else clases.delete(k);return activo;},contains:k=>clases.has(k)};}
 append(...ns){this.children.push(...ns);} replaceChildren(...ns){this.children=[...ns];}
 remove(){this.removed=true;} setAttribute(k,v){this.attributes[k]=String(v);} getAttribute(k){return this.attributes[k]??null;} addEventListener(k,f){(this.listeners[k]??=[]).push(f);} setPointerCapture(){}
 replaceWith(n){elementos.set(this.id,n);}
 showModal(){this.open=true;} close(){this.open=false;for(const f of this.listeners.close||[])f();}
 getBoundingClientRect(){return {left:0,top:0,width:800,height:600};}
}
const elementos=new Map();
global.document={head:new Elemento('head'),createElement:t=>new Elemento(t),createElementNS:(_,t)=>new Elemento(t),getElementById:id=>{
 if(!elementos.has(id)){const e=new Elemento(id);e.id=id;if(['tipo','periodo'].includes(id))e.value='all';elementos.set(id,e);}return elementos.get(id);
}};
global.setTimeout=()=>0;global.clearTimeout=()=>{};
global.location={protocol:'http:'};
document.getElementById('datos').textContent=__JSON__;
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const assert=(v,m)=>{if(!v)throw Error(m);};
let mapas=0,bounds=null,centro=null,acercamientos=0,redimensiones=0;
const eventos={},eventosMapa={},estilosRenderizados=new Map();
function instalarLeaflet(){
 global.L={
  map:()=>{mapas++;return {setView:p=>{centro=p;return L._map;},...L._map};},
  _map:{on(k,f){eventosMapa[k]=f;return this;},getBounds(){return {getWest:()=>-59.15,getEast:()=>-59.13};},invalidateSize(){redimensiones++;},fitBounds:p=>{bounds=p;},panTo:p=>{centro=p;},zoomIn(){acercamientos++;},zoomOut(){acercamientos--;},remove(){}},
  layerGroup:()=>({addTo(){return this;},clearLayers(){}}),
  tileLayer:()=>({on(k,f){eventos[k]=f;return this;},addTo(){return this;}}),
  geoJSON:(f,opciones)=>{
   if(f.geometry?.type==='Point'){
    const capa=opciones.pointToLayer(f,[f.geometry.coordinates[1],f.geometry.coordinates[0]]);
    if(capa.setStyle)capa.setStyle(typeof opciones.style==='function'?opciones.style(f):opciones.style);
    estilosRenderizados.set(String(f.id),capa.options);
   }
   return {addTo(){return this;},on(){return this;}};
  },
  circleMarker:(_,options)=>({options:{...options},setStyle(s){Object.assign(this.options,s);return this;}}),
  marker:(_,options)=>({options}),divIcon:options=>options,circle:()=>({addTo(){return this;}}),
  polyline:()=>({addTo(){return this;},remove(){}})
 };
}
async function completarCarga(){
 const recursos=document.head.children.slice(-2);instalarLeaflet();
 recursos.find(e=>e.tag==='script').onload();await tick();
 assert(mapas===0,'Se creó el mapa antes de cargar el CSS');
 recursos.find(e=>e.tag==='link').onload();await tick();
}
'''


class VisualizacionTests(unittest.TestCase):
    def datos_recorrido(self):
        datos=json.loads(json.dumps(DATOS))
        def camara(id,t,seq='s1'):
            return {'id':id,'geometry':{'type':'Point','coordinates':[-59.14+t*.00001,-37.335]},
                    'properties':{'kind':'camera','xy':[t,0],'captured_at':1539978452606+t*1000,
                                  'camera_view':{'bearing_deg':0,'source':'fixture'},
                                  'sequence':seq,'photo':{'url':f'capturas/{id}.jpg','full_url':f'capturas/grandes/{id}.jpg',
                                                        'annotated':True,'detections':3}}}
        # Orden de almacenamiento distinto del temporal; otra secuencia y año.
        datos['cameras']=[camara('c3',3),camara('c1',1),camara('otra',1,'s2'),camara('c2',2),camara('2019',366*86400)]
        return datos

    def datos_direcciones(self):
        datos=json.loads(json.dumps(DATOS))
        datos['cameras']=[]
        for i,(id,x,y) in enumerate([('centro',0,0),('norte',0,10),('este',10,0),('sur',0,-10),('oeste',-10,0)]):
            datos['cameras'].append({'id':id,'geometry':{'type':'Point','coordinates':[-59.14+x*.0000113,-37.335+y*.000009]},
                'properties':{'kind':'camera','xy':[x,y],'captured_at':1539978452606+i*1000,'sequence':'s1',
                              'camera_view':{'bearing_deg':0,'source':'fixture'},'photo':{'url':f'capturas/{id}.jpg'}}})
        return datos

    def datos_evidencia(self):
        datos=self.datos_recorrido()
        datos['observations']=[{'id':f'obs-{i}','geometry':None,
                               'properties':{'kind':'observation','image_id':f'c{i}','captured_at':1539978452606+i*1000,
                                             'evidence':{'url':f'evidencia/obs-{i}.jpg'}}} for i in (1,2)]
        datos['trees'][0]['properties'].update(observation_ids=['obs-1','obs-2'],
            map_position={'xy':[1,2],'source_observation_ids':['obs-2']})
        return datos

    def test_cli_alterna_plantilla_sin_cambiar_datos(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            exportar_mapa(DATOS, raiz)
            archivo = raiz / "mapa_datos.json"
            original = archivo.read_bytes()
            plantilla = raiz / "alternativa.html"
            plantilla.write_text('<html><script id="datos" type="application/json">__DATOS__</script></html>')
            salida = raiz / "alternativa-generada.html"
            r = subprocess.run([sys.executable, "-B", "-m", "mapeo.visualizacion", "--datos", str(archivo),
                                "--plantilla", str(plantilla), "--output", str(salida)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(archivo.read_bytes(), original)
            self.assertIn('"arbol-1"', salida.read_text())
            self.assertEqual(json.loads(original)["schema_version"], 1)

    def test_plantilla_sin_marcador_falla_sin_reemplazar_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            exportar_mapa(DATOS, raiz)
            original = (raiz / "mapa.html").read_bytes()
            plantilla = raiz / "invalida.html"
            plantilla.write_text("Sin marcador")
            with self.assertRaises(ValueError):
                exportar_mapa(DATOS, raiz, plantilla)
            self.assertEqual((raiz / "mapa.html").read_bytes(), original)

    def ejecutar_js(self, comprobacion, datos=None, protocolo="http:", preparacion=""):
        if not shutil.which("node"):
            self.skipTest("Node no disponible")
        datos = datos if datos is not None else DATOS
        fuente = re.findall(r"<script>(.*?)</script>", renderizar_mapa(datos), re.S)[0]
        stub = DOM.replace("__JSON__", json.dumps(json.dumps(datos)))
        stub += f"\nglobal.location.protocol={json.dumps(protocolo)};\n"
        stub += preparacion
        with tempfile.TemporaryDirectory() as tmp:
            archivo = Path(tmp) / "visor.js"
            archivo.write_text(stub + fuente + "\n(async()=>{\n" + comprobacion +
                               "\n})().catch(e=>{console.error(e);process.exitCode=1;});")
            r = subprocess.run(["node", str(archivo)], capture_output=True, text=True, timeout=10)
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_carga_automatica_css_antes_de_mapa_y_encuadre_sin_camaras(self):
        self.ejecutar_js(r'''
assert(document.head.children.length===2,'No se inició automáticamente la descarga');
await completarCarga();
assert(mapas===1,'No se creó exactamente un mapa');
assert(document.getElementById('geografico').style.display==='block','Las calles están ocultas');
assert(JSON.stringify(centro)===JSON.stringify([-37.336,-59.141]),'No se centró en los datos');
assert(bounds.length===1&&bounds[0][0]===-37.336,'No encuadra árboles sin cámaras');
document.getElementById('mas').onclick();assert(acercamientos===1,'El zoom no controla el mapa visible');
await cargarMapa();assert(mapas===1,'Se duplicó la instancia de Leaflet');
assert(JSON.stringify(datos)===JSON.stringify(JSON.parse(document.getElementById('datos').textContent)),'El visor modificó los datos');
eventos.loading();eventos.tileerror();eventos.load();
assert(document.getElementById('estadoMapa').textContent.includes('No se pudieron descargar'),'Fallo de teselas oculto');
eventos.loading();eventos.tileload();eventos.load();
assert(document.getElementById('estadoMapa').textContent.includes('OpenStreetMap'),'No se recuperó el estado');
''')

    def test_local_durante_carga_no_se_cambia_sin_pedirlo(self):
        self.ejecutar_js(r'''
document.getElementById('local').onclick();await completarCarga();
assert(document.getElementById('plano').style.display==='block','Se abandonó la vista local');
assert(document.getElementById('geografico').style.display==='none','Se superponen vistas');
await document.getElementById('base').onclick();
assert(document.getElementById('geografico').style.display==='block','No se puede volver a las calles');
''')

    def test_cdns_fallan_avisa_y_permite_reintentar(self):
        self.ejecutar_js(r'''
for(let i=0;i<2;i++){
 const recursos=document.head.children.slice(-2);
 assert(recursos.every(e=>(e.src||e.href).includes(i?'cdn.jsdelivr.net':'unpkg.com')),'No prueba otro CDN');
 recursos.forEach(e=>e.onerror());await tick();
}
assert(geo===null,'Quedó un mapa sin cargar');
assert(document.getElementById('plano').style.display==='block','No hay alternativa sin red');
assert(document.getElementById('estadoMapa').textContent.includes('Revisá Internet'),'No explica el fallo');
assert(document.getElementById('base').disabled===false,'El botón no permite reintentar');
document.getElementById('base').onclick();await completarCarga();
assert(mapas===1,'No se recuperó tras reintentar');
''')

    def test_sin_coordenadas_no_inventa_centro(self):
        self.ejecutar_js(r'''
assert(document.head.children.length===0,'Intenta ubicar un relevamiento sin coordenadas');
assert(document.getElementById('estadoMapa').textContent.includes('No hay coordenadas'),'No explica la falta de ubicación');
''', {**DATOS, "survey": {"id": "vacio"}, "trees": []})

    def test_archivo_local_no_solicita_teselas_y_explica_como_abrir(self):
        self.ejecutar_js(r'''
assert(document.head.children.length===0,'Descarga recursos remotos desde file://');
assert(mapas===0,'Solicita calles sin Referer válido');
assert(document.getElementById('ayudaServidor').hidden===false,'No muestra cómo iniciar el servidor');
assert(document.getElementById('estadoMapa').textContent.includes('localhost'),'No explica el problema');
assert(document.getElementById('plano').style.display==='block','Se perdió la vista local');
''', protocolo="file:")

    def test_aproximados_y_grupos_se_dibujan_y_pueden_ocultarse(self):
        datos = json.loads(json.dumps(DATOS))
        aproximado = {"xy": [10, 20], "method": "bbox_ground_plane", "is_approximate": True,
                      "uncertainty_m": 8, "assumptions": {"camera_height_is_assumed": True, "camera_height_m": 1.7},
                      "source_observation_ids": ["obs-1"]}
        aproximado["lateral_constraint"] = {"applied": True, "lateral_before_m": 12., "lateral_after_m": 6.,
                                            "max_distance_m": 6., "axis": {"source": "capture_trajectory"}}
        datos["trees"].append({"type": "Feature", "id": "aprox-1", "geometry": {"type": "Point", "coordinates": [-59.142, -37.337]},
                               "properties": {"kind": "tree", "fit": None, "identity_status": "candidate", "map_position": aproximado}})
        datos["groups"] = [{"type": "Feature", "id": "grupo-1", "geometry": {"type": "Point", "coordinates": [-59.143, -37.338]},
                            "properties": {"kind": "group", "map_position": {**aproximado, "xy": [12, 22]}, "status": "needs_review"}}]
        datos["observations"] = [{"type": "Feature", "id": "obs-1", "geometry": None,
                                  "properties": {"kind": "observation", "ray": {"valid": False},
                                                 "image_id": "foto-1", "evidence": {"url": "evidencia/obs-1.jpg"}}}]
        self.ejecutar_js(r'''
assert(xy(porId.get('aprox-1'))[0]===10,'La vista local omite los puntos aproximados sin fit');
assert(xy(porId.get('grupo-1'))[0]===12,'No se dibujan los grupos');
assert(puntosGeograficos().length===3,'Se excluyen puntos al encuadrar');
detalle(porId.get('aprox-1'));
const contenido=document.getElementById('detalle').children;
assert(contenido.some(e=>e.textContent.includes('APROXIMADA')),'No identifica la aproximación');
assert(contenido.some(e=>e.textContent.includes('1.7')),'No muestra los supuestos');
assert(contenido.some(e=>e.textContent.includes('Ajuste lateral: 12.0 → 6.0')),'No explica el límite lateral');
assert(contenido.some(e=>e.tag==='img'&&e.src==='evidencia/obs-1.jpg'),'No muestra la evidencia');
document.getElementById('verAproximados').checked=false;
document.getElementById('verAproximados').onchange();
assert(!visible(porId.get('aprox-1'))&&!visible(porId.get('grupo-1')),'No oculta las aproximaciones');
assert(visible(porId.get('arbol-1')),'Oculta también las posiciones trianguladas');
assert(puntosGeograficos().length===1,'El encuadre ignora el filtro');
''', datos=datos)

    def test_ajuste_horizontal_controles_centrado_y_restablecer(self):
        datos = json.loads(json.dumps(DATOS))
        datos["cameras"] = [{"type": "Feature", "id": "camara-1", "geometry": {"type": "Point", "coordinates": [-59.14, -37.335]},
                             "properties": {"kind": "camera", "xy": [0, 0]}}]
        self.ejecutar_js(r'''
await completarCarga();
const base=JSON.stringify(datosOriginales),camaraOriginal=datosOriginales.cameras[0],arbolOriginal=datosOriginales.trees[0];
assert(aplicarOffset(10),'No aplica el desplazamiento');
assert(datos.cameras[0].geometry.coordinates[1]===camaraOriginal.geometry.coordinates[1],'Se modificó la latitud');
assert(datos.cameras[0].properties.xy[0]===10,'La vista local no coincide con la geográfica');
aplicarOffset(20);assert(datos.cameras[0].properties.xy[0]===20,'Se acumula el desplazamiento');
document.getElementById('restaurarOffset').onclick();
assert(datos.cameras[0].geometry.coordinates[0]===camaraOriginal.geometry.coordinates[0],'No restaura el original');
detalle(porId.get('camara-1'));document.getElementById('modoCentrado').value='horizontal';document.getElementById('centrarCamara').onclick();
assert(camaraParaCentrar==='camara-1'&&guiaCentrado,'No activa el centrado ni muestra la guía');
const destino=camaraOriginal.geometry.coordinates[0]+.0001;
eventosMapa.click({latlng:{lng:destino,lat:-37.32}});
assert(Math.abs(datos.cameras[0].geometry.coordinates[0]-destino)<1e-12,'No centra horizontalmente');
assert(datos.cameras[0].geometry.coordinates[1]===camaraOriginal.geometry.coordinates[1],'Toma la altura del clic');
assert(Math.abs(datos.trees[0].geometry.coordinates[0]-arbolOriginal.geometry.coordinates[0]-.0001)<1e-12,'El árbol no acompaña la cámara');
assert(datos.trees[0].geometry.coordinates[1]===arbolOriginal.geometry.coordinates[1],'El árbol cambia de altura');
assert(camaraParaCentrar===null&&guiaCentrado===null,'No termina el modo de centrado');
assert(JSON.stringify(datosOriginales)===base,'Modificó el relevamiento original');
assert(aplicarOffset('nan')===false,'Permite offsets inválidos');
''', datos=datos)

    def test_candidatos_mismo_estado_tienen_colores_distintos_y_estilo_no_los_pisa(self):
        datos=json.loads(json.dumps(DATOS))
        datos['trees']=[{'type':'Feature','id':f'tree-{i}','geometry':{'type':'Point','coordinates':[-59.14+i*.00001,-37.335]},
                         'properties':{'kind':'tree','fit':{'xy':[i,10]},'identity_status':'candidate'}} for i in range(9)]
        datos['cameras']=[{'type':'Feature','id':'cam','geometry':{'type':'Point','coordinates':[-59.14,-37.335]},'properties':{'kind':'camera','xy':[0,0]}}]
        datos['groups']=[{'type':'Feature','id':'group','geometry':{'type':'Point','coordinates':[-59.1401,-37.3351]},'properties':{'kind':'group','map_position':{'xy':[-10,-10]}}}]
        self.ejecutar_js(r'''
await completarCarga();
const colores=datos.trees.map(f=>estilosRenderizados.get(f.id).fillColor);
assert(new Set(colores).size===9,'Los nueve candidatos comparten colores');
assert(datos.trees.every(f=>estilosRenderizados.get(f.id).fillOpacity===1),'Los puntos quedan transparentes');
assert(estilosRenderizados.get('cam').icon.html.includes('camera'),'No distingue cámaras por forma');
assert(estilosRenderizados.get('group').icon.html.includes('group'),'No distingue grupos por forma');
assert(color(porId.get('cam'))!==color(porId.get('group')),'Cámara y grupo tienen el mismo color');
aplicarAjuste(23,-3);
assert(JSON.stringify(datos.trees.map(f=>estilosRenderizados.get(f.id).fillColor))===JSON.stringify(colores),'Cambian los colores al ajustar');
''', datos=datos)

    def test_migra_ajuste_horizontal_guardado_y_mueve_en_dos_direcciones(self):
        datos=json.loads(json.dumps(DATOS))
        datos['cameras']=[{'type':'Feature','id':'camara-1','geometry':{'type':'Point','coordinates':[-59.14,-37.335]},'properties':{'kind':'camera','xy':[0,0]}}]
        preparacion=r'''
const dPrevio=JSON.parse(document.getElementById('datos').textContent),almacenamiento=new Map();
almacenamiento.set(`agrotech:horizontal:v1:${dPrevio.survey.id}:${JSON.stringify(dPrevio.survey.origin)}:0`,'23');
global.localStorage={getItem:k=>almacenamiento.has(k)?almacenamiento.get(k):null,setItem:(k,v)=>almacenamiento.set(k,v)};
'''
        self.ejecutar_js(r'''
assert(CalibracionMapa.offsets(datos).east===23,'Se perdió la corrección horizontal anterior');
assert(CalibracionMapa.offsets(datos).north===0,'Se inventó una corrección vertical');
await completarCarga();
document.getElementById('pasoOffset').value='.5';
document.getElementById('offsetNorteMas').onclick();
assert(CalibracionMapa.offsets(datos).north===.5,'No mueve hacia el norte');
assert(CalibracionMapa.offsets(datos).east===23,'El control vertical modifica el ajuste anterior');
document.getElementById('offsetNorteMenos').onclick();
assert(CalibracionMapa.offsets(datos).north===0,'No mueve hacia el sur');
document.getElementById('offsetMas').onclick();
assert(CalibracionMapa.offsets(datos).east===23.5,'No respeta el paso horizontal');
const guardado=JSON.parse(localStorage.getItem(claveCalibracion));
assert(guardado.offset_east_m===23.5&&guardado.offset_north_m===0,'No persiste los dos componentes');
document.getElementById('modoCentrado').value='libre';
activarCentrado('camara-1');
assert(guiaCentrado===null,'El centrado libre muestra una restricción horizontal');
const destino={lng:-59.1395,lat:-37.3352};eventosMapa.click({latlng:destino});
assert(Math.abs(datos.cameras[0].geometry.coordinates[0]-destino.lng)<1e-12,'No ajusta la longitud con el clic');
assert(Math.abs(datos.cameras[0].geometry.coordinates[1]-destino.lat)<1e-12,'No ajusta la latitud con el clic');
assert(datos.cameras[0].properties.xy[1]<0,'La vista local usa mal el signo norte/sur');
''',datos=datos,preparacion=preparacion)

    def test_giro_conserva_camara_referencia_ajustes_y_colores(self):
        datos=json.loads(json.dumps(DATOS))
        datos['cameras']=[{'type':'Feature','id':'cam-1','geometry':{'type':'Point','coordinates':[-59.14,-37.335]},'properties':{'kind':'camera','xy':[0,0]}},
                         {'type':'Feature','id':'cam-2','geometry':{'type':'Point','coordinates':[-59.1399,-37.335]},'properties':{'kind':'camera','xy':[8.86,0]}}]
        self.ejecutar_js(r'''
await completarCarga();aplicarAjuste(23,-2);
const fija=[...datos.cameras[0].geometry.coordinates],antes=[...datos.cameras[1].geometry.coordinates],colorAntes=color(datos.trees[0]);
document.getElementById('pasoGiro').value='1';document.getElementById('rotarDerecha').onclick();
assert(CalibracionMapa.parametros(datos).rotation_deg===1,'No aplica giro horario');
assert(JSON.stringify(datos.cameras[0].geometry.coordinates)===JSON.stringify(fija),'Se mueve el centro del giro');
assert(datos.cameras[1].geometry.coordinates[1]<antes[1],'El sentido del giro es incorrecto');
assert(CalibracionMapa.offsets(datos).east===23&&CalibracionMapa.offsets(datos).north===-2,'Pierde los ajustes existentes');
assert(color(datos.trees[0])===colorAntes,'Cambia la identidad visual al girar');
document.getElementById('rotarIzquierda').onclick();
assert(CalibracionMapa.parametros(datos).rotation_deg===0,'No aplica giro antihorario');
document.getElementById('rotacionGrados').value='8';document.getElementById('aplicarOffset').onclick();
const ubicaciones=datos.cameras.map(f=>[...f.geometry.coordinates]);
document.getElementById('pivoteRotacion').value='cam-2';document.getElementById('pivoteRotacion').onchange();
assert(CalibracionMapa.parametros(datos).pivot_camera_id==='cam-2','No cambia la cámara de referencia');
assert(datos.cameras.every((f,i)=>f.geometry.coordinates.every((x,j)=>Math.abs(x-ubicaciones[i][j])<1e-12)),'El mapa salta al cambiar de centro');
document.getElementById('sinGiro').onclick();assert(CalibracionMapa.parametros(datos).rotation_deg===0,'No permite quitar el giro');
document.getElementById('restaurarOffset').onclick();
assert(CalibracionMapa.offsets(datos).east===0&&CalibracionMapa.offsets(datos).north===0,'No restaura el original');
''',datos=datos)

    def test_selector_relevamiento_fotografias_y_estado_de_procesamiento(self):
        datos=json.loads(json.dumps(DATOS))
        datos['related_maps']=[{'id':'visor','label':'Prueba','url':'../visor/mapa.html'},
                               {'id':'manzana_tandil','label':'Manzana completa','url':'../manzana_tandil/mapa.html'}]
        datos['pipeline']={'stage':'detecting','images_processed':2,'images_total':89}
        datos['cameras']=[{'id':'cam','geometry':{'type':'Point','coordinates':[-59.14,-37.335]},
                           'properties':{'kind':'camera','xy':[0,0],'captured_at':1539978452606,
                                         'photo':{'url':'capturas/cam.jpg','annotated':True,'detections':3}}}]
        self.ejecutar_js(r'''
assert(document.getElementById('selectorMapas').hidden===false,'No muestra el selector de relevamiento');
assert(document.getElementById('estadoProcesamiento').textContent.includes('2/89'),'No explica el procesamiento pendiente');
detalle(porId.get('cam'));
assert(document.getElementById('detalle').children.some(n=>n.tag==='img'&&n.src==='capturas/cam.jpg'),'No muestra la fotografía');
assert(document.getElementById('detalle').children.some(n=>n.textContent.includes('3 detecciones')),'No identifica la anotación');
const selector=document.getElementById('elegirRelevamiento');selector.value='../manzana_tandil/mapa.html';selector.onchange();
assert(location.href==='../manzana_tandil/mapa.html','El selector sigue abriendo el mapa anterior');
''',datos=datos)

    def test_camara_abre_foto_grande_navega_en_orden_y_no_mezcla_recorridos(self):
        self.ejecutar_js(r'''
await completarCarga();
const original=JSON.stringify(datosOriginales);
detalle(porId.get('c2'));
assert(document.getElementById('visorCamaras').open,'No abre el visor al seleccionar una cámara');
assert(document.getElementById('fotoImagen').src==='capturas/grandes/c2.jpg','Amplía la miniatura en lugar de usar la versión grande');
assert(document.getElementById('fotoContador').textContent==='2 / 3','No ordena por captura o incluye otra secuencia/año');
assert(camaraSeleccionada==='c2','No sincroniza la cámara seleccionada');
assert(estilosRenderizados.get('c2').icon.html.includes('selected'),'No destaca la cámara actual');
document.getElementById('fotoSiguiente').onclick();
assert(document.getElementById('fotoImagen').src.endsWith('/c3.jpg'),'No avanza a la captura siguiente');
assert(document.getElementById('fotoSiguiente').disabled,'No deshabilita siguiente al terminar');
assert(!visorCamaras.mover(1),'Salta a otro recorrido o vuelve al principio');
assert(camaraSeleccionada==='c3','El mapa mantiene la cámara anterior');
assert(centro[1]===porId.get('c3').geometry.coordinates[0],'El mapa no acompaña la cámara');
document.getElementById('fotoAnterior').onclick();document.getElementById('fotoAnterior').onclick();
assert(document.getElementById('fotoImagen').src.endsWith('/c1.jpg'),'No retrocede en orden cronológico');
assert(document.getElementById('fotoAnterior').disabled&&!visorCamaras.mover(-1),'Retrocede fuera del recorrido');
document.getElementById('fotoVolverMapa').onclick();
assert(!document.getElementById('visorCamaras').open,'No vuelve al mapa');
assert(JSON.stringify(datosOriginales)===original,'El recorrido modifica el relevamiento');
''',datos=self.datos_recorrido())

    def test_recorrido_teclado_zoom_y_selector_de_fecha(self):
        self.ejecutar_js(r'''
detalle(porId.get('c1'));
const dialogo=document.getElementById('visorCamaras');
const tecla=(key,tagName='BUTTON')=>{let consumida=false;for(const f of dialogo.listeners.keydown)f({key,target:{tagName},preventDefault(){consumida=true;}});return consumida;};
assert(tecla('ArrowRight'),'No captura flecha derecha');
assert(document.getElementById('fotoTitulo').textContent.includes('c2'),'La flecha no avanza');
assert(!tecla('ArrowRight','SELECT'),'Interfiere con el teclado del selector de recorridos');
assert(tecla('ArrowLeft'),'No captura flecha izquierda');
document.getElementById('fotoZoomMas').onclick();
assert(document.getElementById('fotoImagen').style.width==='1500px','No amplía la imagen');
document.getElementById('fotoAjustar').onclick();
assert(document.getElementById('fotoImagen').style.maxHeight==='100%','No vuelve a ajustar la imagen');
const selector=document.getElementById('fotoRecorrido');
assert(selector.children.length===3,'No separa los recorridos y fechas');
document.getElementById('periodo').value='2018';
selector.value=selector.children.find(o=>o.textContent.includes('2019')).value;selector.onchange();
assert(camaraSeleccionada==='2019'&&document.getElementById('periodo').value==='2019','Selecciona una cámara que el filtro oculta');
assert(document.getElementById('fotoAnterior').disabled&&document.getElementById('fotoSiguiente').disabled,'Una sola foto tiene navegación fuera del recorrido');
assert(tecla('Escape')&&!dialogo.open,'Escape no cierra el visor');
assert(!visorCamaras.mover(1),'Navega con el diálogo cerrado');
''',datos=self.datos_recorrido())

    def test_foto_faltante_miniatura_y_eventos_de_carga_atrasados(self):
        self.ejecutar_js(r'''
detalle(porId.get('c1'));
const anterior=document.getElementById('fotoImagen');
document.getElementById('fotoSiguiente').onclick();
const actual=document.getElementById('fotoImagen');
anterior.onerror();
assert(actual.src==='capturas/grandes/c2.jpg','Un error atrasado reemplaza la foto actual');
actual.onerror();assert(actual.src==='capturas/c2.jpg','No recupera la miniatura si falta la foto grande');
actual.onload();
assert(document.getElementById('fotoEstado').textContent.includes('miniatura'),'Oculta el uso de una miniatura');
actual.onerror();
assert(actual.hidden&&document.getElementById('fotoEstado').textContent.includes('No se pudo cargar'),'No muestra el fallo de la foto');
document.getElementById('fotoSiguiente').onclick();
assert(document.getElementById('fotoImagen')!==actual,'No permite seguir después de una imagen faltante');
document.getElementById('fotoImagen').onload();
assert(document.getElementById('fotoEstado').hidden,'No limpia el error anterior');
assert(!visorCamaras.abrir('no-existe'),'Intenta abrir una cámara inexistente');
const sinSeq=datos.cameras.slice(0,2).map(f=>({...f,properties:{...f.properties,sequence:null}}));
assert(RecorridoCamaras.rutas(sinSeq).length===2,'Supone continuidad sin conocer la secuencia');
''',datos=self.datos_recorrido())

    def test_navegacion_espacial_cuatro_direcciones_y_teclado(self):
        self.ejecutar_js(r'''
const original=JSON.stringify(datosOriginales);
detalle(porId.get('centro'));
const esperado={adelante:'norte',derecha:'este',atras:'sur',izquierda:'oeste'};
const vecinos=RecorridoCamaras.vecinos(porId.get('centro'),datos.cameras);
for(const [dir,id]of Object.entries(esperado)){
 assert(vecinos[dir].camera.id===id,`Destino incorrecto para ${dir}`);
 assert(Math.abs(vecinos[dir].distance_m-10)<1e-8,'Distancia incorrecta');
}
assert(!document.getElementById('fotoAdelante').disabled&&!document.getElementById('fotoDerecha').disabled,'Oculta destinos disponibles');
document.getElementById('fotoIzquierda').onclick();assert(camaraSeleccionada==='oeste','No va a la izquierda');
document.getElementById('fotoDerecha').onclick();assert(camaraSeleccionada==='centro','No vuelve a la cámara más cercana');
const tecla=key=>document.getElementById('visorCamaras').listeners.keydown.forEach(f=>f({key,target:{tagName:'BUTTON'},preventDefault(){}}));
tecla('ArrowUp');assert(camaraSeleccionada==='norte','↑ sigue el orden temporal en lugar del espacio');
tecla('ArrowDown');assert(camaraSeleccionada==='centro','↓ no retrocede en el espacio');
tecla('ArrowRight');assert(camaraSeleccionada==='este','→ no se mueve hacia la derecha');
tecla('ArrowLeft');assert(camaraSeleccionada==='centro','← no se mueve hacia la izquierda');
assert(JSON.stringify(datosOriginales)===original,'La navegación cambia las posiciones');
''',datos=self.datos_direcciones())

    def test_vecinos_sin_saltos_lejanos_o_de_fecha_y_destinos_desactivados(self):
        self.ejecutar_js(r'''
const c=porId.get('centro'),base=porId.get('norte');
const lejana={...base,id:'lejana',properties:{...base.properties,xy:[0,80]}};
const otroDia={...base,id:'otro-dia',properties:{...base.properties,xy:[0,2],captured_at:base.properties.captured_at+86400000}};
const sinFoto={...base,id:'sin-foto',properties:{...base.properties,xy:[0,3],photo:null}};
let n=RecorridoCamaras.vecinos(c,[c,base,lejana,otroDia,sinFoto]);
assert(n.adelante.camera.id==='norte','Prefiere una foto cercana de otro día o sin imagen');
assert(n.derecha===null&&n.izquierda===null&&n.atras===null,'Inventa opciones sin cámaras');
n=RecorridoCamaras.vecinos(c,[base],{max_distance_m:5});
assert(Object.values(n).every(x=>x===null),'Ignora el límite de distancia');
const sinRumbo={...c,properties:{...c.properties,camera_view:null}};
assert(Object.values(RecorridoCamaras.vecinos(sinRumbo,datos.cameras)).every(x=>x===null),'Inventa hacia dónde mira la foto');
datos.cameras=[sinRumbo,base];detalle(sinRumbo);
assert(document.getElementById('fotoAdelante').disabled&&document.getElementById('fotoIzquierda').disabled,'Habilita controles sin orientación');
assert(!visorCamaras.navegar('adelante'),'Permite un salto sin destino');
assert(document.getElementById('fotoDireccionEstado').textContent.includes('orientación'),'No explica por qué no hay flechas');
''',datos=self.datos_direcciones())

    def test_orientacion_y_vecinos_se_conservan_al_rotar_y_desplazar(self):
        self.ejecutar_js(r'''
const ids=n=>Object.fromEntries(Object.entries(n).map(([k,v])=>[k,v?.camera.id]));
const antes=ids(RecorridoCamaras.vecinos(porId.get('centro'),datos.cameras));
aplicarAjuste(23,-7,true,90,'centro');
assert(porId.get('centro').properties.camera_view.bearing_deg===90,'El rumbo de la foto no gira con el mapa');
const despues=ids(RecorridoCamaras.vecinos(porId.get('centro'),datos.cameras));
assert(JSON.stringify(antes)===JSON.stringify(despues),'Rotar o desplazar el mapa cambia adelante/atrás');
assert(datosOriginales.cameras[0].properties.camera_view.bearing_deg===0,'Sobrescribe la orientación original');
const sinXY=datos.cameras.map(f=>{const copia=JSON.parse(JSON.stringify(f));delete copia.properties.xy;return copia;});
const porGPS=ids(RecorridoCamaras.vecinos(sinXY[0],sinXY));
assert(JSON.stringify(antes)===JSON.stringify(porGPS),'No funciona usando coordenadas geográficas');
''',datos=self.datos_direcciones())

    def test_cambiar_de_vista_en_el_mismo_punto_y_conectar_otro_recorrido(self):
        self.ejecutar_js(r'''
const c=porId.get('centro');
const giro={...c,id:'giro',properties:{...c.properties,sequence:'otro',camera_view:{bearing_deg:90}}};
const repetida={...c,id:'repetida'};
const n=RecorridoCamaras.vecinos(c,[...datos.cameras,giro,repetida]);
assert(n.derecha.camera.id==='giro'&&n.derecha.movement==='turn','No ofrece una cámara del mismo punto que mira a la derecha');
datos.cameras.push(giro);visorCamaras.abrir('centro');
assert(document.getElementById('fotoDerecha').textContent.includes('girar'),'No distingue un giro de un desplazamiento');
document.getElementById('fotoDerecha').onclick();
assert(camaraSeleccionada==='giro','No conecta otro recorrido cercano de la misma fecha');
assert(document.getElementById('fotoRecorrido').value.includes('otro'),'No actualiza el selector del recorrido');
assert(visorCamaras.navegar('izquierda')&&camaraSeleccionada==='centro','No vuelve a la vista original');
''',datos=self.datos_direcciones())

    def test_arbol_abre_evidencia_grande_y_recorre_solo_sus_observaciones(self):
        self.ejecutar_js(r'''
const original=JSON.stringify(datosOriginales);
detalle(porId.get('arbol-1'));
assert(document.getElementById('visorArboles').open,'No abre el árbol en grande');
assert(!document.getElementById('visorCamaras').open,'Abre la cámara en lugar del recorte');
assert(document.getElementById('arbolImagen').src==='evidencia/obs-2.jpg','No prioriza la evidencia de la ubicación');
assert(document.getElementById('arbolContador').textContent==='Vista 1 de 2','Duplica evidencias o no las cuenta');
assert(document.getElementById('arbolAnterior').disabled,'Permite retroceder antes de la primera vista');
const primera=document.getElementById('arbolImagen');
document.getElementById('arbolSiguiente').onclick();
assert(document.getElementById('arbolImagen').src==='evidencia/obs-1.jpg','No pasa a otra evidencia del mismo árbol');
assert(document.getElementById('arbolSiguiente').disabled&&!visorArboles.mover(1),'Navega fuera de las evidencias');
primera.onerror();
assert(!document.getElementById('arbolEstado').textContent.includes('No se pudo'),'Un fallo atrasado modifica la vista actual');
const tecla=key=>document.getElementById('visorArboles').listeners.keydown.forEach(f=>f({key,target:{tagName:'BUTTON'},preventDefault(){}}));
tecla('ArrowLeft');assert(document.getElementById('arbolImagen').src==='evidencia/obs-2.jpg','No navega con el teclado');
const img=document.getElementById('arbolImagen');img.naturalWidth=300;img.naturalHeight=600;img.onload();
assert(img.style.height==='700px','El recorte no ocupa el alto disponible');
document.getElementById('arbolZoomMas').onclick();assert(img.style.height==='1050px','No amplía el árbol');
document.getElementById('arbolAjustar').onclick();assert(img.style.height==='700px','No ajusta nuevamente el recorte');
tecla('Escape');assert(!document.getElementById('visorArboles').open,'Escape no cierra el árbol');
assert(JSON.stringify(datosOriginales)===original,'Modifica datos del inventario');
''',datos=self.datos_evidencia())

    def test_desde_arbol_abre_la_camara_correcta_y_maneja_evidencia_faltante(self):
        self.ejecutar_js(r'''
detalle(porId.get('arbol-1'));document.getElementById('arbolVerCamara').onclick();
assert(!document.getElementById('visorArboles').open&&document.getElementById('visorCamaras').open,'Superpone los dos visores');
assert(camaraSeleccionada==='c2','No abre la cámara de la evidencia actual');
detalle(porId.get('arbol-1'));
assert(!document.getElementById('visorCamaras').open,'No cierra la cámara al abrir un árbol');
document.getElementById('arbolImagen').onerror();
assert(document.getElementById('arbolImagen').hidden&&!document.getElementById('arbolEstado').hidden,'No informa la foto faltante');
document.getElementById('arbolSiguiente').onclick();document.getElementById('arbolImagen').onload();
assert(document.getElementById('arbolEstado').hidden,'No se recupera del error');
const vacio={id:'sin-foto',properties:{kind:'tree',observation_ids:['no-existe']}};
visorArboles.abrir(vacio);
assert(document.getElementById('arbolEstado').textContent.includes('no tiene'),'No explica la falta de evidencia');
assert(document.getElementById('arbolImagen').hidden&&document.getElementById('arbolVerCamara').disabled,'Ofrece imagen o cámara inexistentes');
document.getElementById('arbolVolverMapa').onclick();
assert(!document.getElementById('visorArboles').open,'No permite volver al mapa');
''',datos=self.datos_evidencia())

    def test_ocultar_panel_amplia_mapa_conserva_datos_y_permite_abrir_arbol(self):
        self.ejecutar_js(r'''
await completarCarga();
const original=JSON.stringify(datos),ajuste=JSON.stringify(datos.map_calibration),antes=redimensiones;
const panel=document.getElementById('panelLateral'),boton=document.getElementById('alternarPanel');
assert(!panel.hidden&&boton.getAttribute('aria-expanded')==='true','Oculta el panel por defecto');
boton.onclick();
assert(panel.hidden&&document.getElementById('contenidoMapa').classList.contains('sin-panel'),'No deja el mapa ocupar el espacio del panel');
assert(boton.textContent.includes('Mostrar')&&boton.getAttribute('aria-expanded')==='false','No permite volver a mostrar el panel');
assert(redimensiones===antes+1,'Leaflet no actualiza su tamaño');
detalle(porId.get('arbol-1'));
assert(document.getElementById('visorArboles').open&&panel.hidden,'Necesita mostrar el panel para abrir el árbol');
document.getElementById('arbolCerrar').onclick();boton.onclick();
assert(!panel.hidden&&!document.getElementById('contenidoMapa').classList.contains('sin-panel'),'No restaura el panel');
assert(JSON.stringify(datos)===original&&JSON.stringify(datos.map_calibration)===ajuste,'Ocultar el panel altera el relevamiento');
''',datos=self.datos_evidencia())

    def test_recuerda_panel_oculto_sin_modificar_calibracion_guardada(self):
        self.ejecutar_js(r'''
assert(document.getElementById('panelLateral').hidden,'No restaura la preferencia del panel');
assert(CalibracionMapa.offsets(datos).east===12,'Interfiere con la calibración');
document.getElementById('alternarPanel').onclick();
assert(localStorage.getItem(clavePanel)==='visible','No guarda la preferencia del panel');
assert(CalibracionMapa.offsets(datos).east===12,'Abrir el panel cambia la alineación');
''',datos=self.datos_evidencia(),preparacion=r'''
const valores=new Map([['agrotech:panel:v1','hidden']]);
const d=JSON.parse(document.getElementById('datos').textContent);
valores.set(`agrotech:calibration:v2:${d.survey.id}:${JSON.stringify(d.survey.origin)}`,JSON.stringify({offset_east_m:12,offset_north_m:0,rotation_deg:0}));
global.localStorage={getItem:k=>valores.get(k)??null,setItem:(k,v)=>valores.set(k,v)};
''')


if __name__ == "__main__":
    unittest.main()
