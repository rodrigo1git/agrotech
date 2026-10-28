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
 constructor(tag){this.tag=tag;this.children=[];this.style={};this.value='';this.checked=true;this.textContent='';}
 append(...ns){this.children.push(...ns);} replaceChildren(...ns){this.children=[...ns];}
 remove(){this.removed=true;} setAttribute(){} addEventListener(){} setPointerCapture(){}
 getBoundingClientRect(){return {left:0,top:0,width:800,height:600};}
}
const elementos=new Map();
global.document={head:new Elemento('head'),createElement:t=>new Elemento(t),createElementNS:(_,t)=>new Elemento(t),getElementById:id=>{
 if(!elementos.has(id)){const e=new Elemento(id);if(['tipo','periodo'].includes(id))e.value='all';elementos.set(id,e);}return elementos.get(id);
}};
global.setTimeout=()=>0;global.clearTimeout=()=>{};
global.location={protocol:'http:'};
document.getElementById('datos').textContent=__JSON__;
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const assert=(v,m)=>{if(!v)throw Error(m);};
let mapas=0,bounds=null,centro=null,acercamientos=0;
const eventos={};
function instalarLeaflet(){
 global.L={
  map:()=>{mapas++;return {setView:p=>{centro=p;return L._map;},...L._map};},
  _map:{invalidateSize(){},fitBounds:p=>{bounds=p;},zoomIn(){acercamientos++;},zoomOut(){acercamientos--;},remove(){}},
  layerGroup:()=>({addTo(){return this;},clearLayers(){}}),
  tileLayer:()=>({on(k,f){eventos[k]=f;return this;},addTo(){return this;}}),
  geoJSON:()=>({addTo(){return this;},on(){return this;}}),circle:()=>({addTo(){return this;}})
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

    def ejecutar_js(self, comprobacion, datos=None, protocolo="http:"):
        if not shutil.which("node"):
            self.skipTest("Node no disponible")
        datos = datos if datos is not None else DATOS
        fuente = re.findall(r"<script>(.*?)</script>", renderizar_mapa(datos), re.S)[0]
        stub = DOM.replace("__JSON__", json.dumps(json.dumps(datos)))
        stub += f"\nglobal.location.protocol={json.dumps(protocolo)};\n"
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


if __name__ == "__main__":
    unittest.main()
