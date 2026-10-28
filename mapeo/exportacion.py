"""Exportaciones atómicas y mapa HTML con vista local disponible sin conexión."""

import json
import math
from pathlib import Path

from mapillary_arboles import escribir_json
from .camaras import posicion
from .inventario import contadores, observaciones_actuales


def coleccion(features):
    return {"type": "FeatureCollection", "features": features}


def evidencia(obs, destino):
    if not obs.get("image_path") or not Path(obs["image_path"]).is_file():
        return None
    from PIL import Image
    archivo = destino / "evidencia" / f"{obs['id']}.jpg"
    with Image.open(obs["image_path"]) as imagen:
        x1, y1, x2, y2 = obs["bbox_xyxy"]
        caja = [max(0, int(x1) - 15), max(0, int(y1) - 15), min(imagen.width, int(math.ceil(x2)) + 15), min(imagen.height, int(math.ceil(y2)) + 15)]
        if not archivo.exists():
            recorte = imagen.convert("RGB").crop(caja)
            recorte.thumbnail((640, 480))
            archivo.parent.mkdir(parents=True, exist_ok=True)
            recorte.save(archivo, quality=85)
    return {"url": f"evidencia/{obs['id']}.jpg", "crop_box": caja}


def exportar(almacen, survey, config, destino):
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    marco, capturas, observaciones = observaciones_actuales(almacen, survey, config)
    estado = almacen.estado(survey["id"])
    observaciones = estado.get("observations", observaciones)
    metricas = contadores(estado, observaciones)
    arboles, camaras, obs_geo, grupos = [], [], [], []
    for arbol in estado["trees"]:
        if not arbol.get("active", True):
            continue
        fit = arbol.get("fit")
        geometria = {"type": "Point", "coordinates": marco.geografica(*fit["xy"])} if fit and marco else None
        arboles.append({"type": "Feature", "id": arbol["id"], "geometry": geometria, "properties": {**arbol, "kind": "tree"}})
    for image_id, meta in capturas.items():
        try:
            lon, lat, campo = posicion(meta)
            geometria = {"type": "Point", "coordinates": [lon, lat]}
            xy = marco.proyectar(lon, lat) if marco else None
        except ValueError:
            geometria, campo, xy = None, None, None
        camaras.append({"type": "Feature", "id": image_id, "geometry": geometria,
                        "properties": {"kind": "camera", "image_id": image_id, "xy": xy,
                                       "position_source": campo, "captured_at": meta.get("captured_at"),
                                       "sequence": meta.get("sequence"), "creator": meta.get("creator"),
                                       "view_url": f"https://www.mapillary.com/app/?pKey={image_id}"}})
    for obs in observaciones:
        ray = obs["ray"]
        geometria = None
        if marco and ray.get("valid"):
            inicio = ray["origin_xy"]
            fin = [inicio[i] + config["ray_display_length_m"] * ray["direction"][i] for i in (0, 1)]
            geometria = {"type": "LineString", "coordinates": [marco.geografica(*inicio), marco.geografica(*fin)]}
        props = {**obs, "kind": "observation", "ray_display_length_m": config["ray_display_length_m"],
                 "ray_is_measured_distance": False, "evidence": evidencia(obs, destino)}
        obs_geo.append({"type": "Feature", "id": obs["id"], "geometry": geometria, "properties": props})
    for grupo in estado["groups"]:
        if grupo.get("active", True):
            grupos.append({"type": "Feature", "id": grupo["id"], "geometry": grupo.get("geometry"), "properties": {**grupo, "kind": "group"}})
    datos = {"survey": survey, "counts": metricas, "trees": arboles, "cameras": camaras, "observations": obs_geo, "groups": grupos}
    for nombre, features in (("arboles", arboles), ("camaras", camaras), ("observaciones", obs_geo), ("grupos", grupos)):
        if nombre == "arboles":
            features = [f for f in features if f["geometry"] is not None]
        escribir_json(destino / f"{nombre}.geojson", coleccion(features))
    eventos = almacen.eventos(survey["id"])
    escribir_json(destino / "inventario.json", {"survey": survey, "counts": metricas, **estado,
                                               "observations": observaciones, "captures": list(capturas.values()),
                                               "events": eventos})
    escribir_json(destino / "estadisticas.json", metricas)
    # Evitar que texto de una etiqueta/nota cierre el bloque script.
    serializado = json.dumps(datos, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c").replace("&", "\\u0026")
    html = HTML.replace("__DATOS__", serializado)
    temporal = destino / "mapa.html.tmp"
    temporal.write_text(html, encoding="utf-8")
    temporal.replace(destino / "mapa.html")
    return metricas


HTML = r'''<!doctype html>
<html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Inventario de árboles</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f4f6f4;color:#153b2a;font:15px system-ui}header{padding:18px 24px;background:white;border-bottom:1px solid #d5dfd7}h1{margin:0 0 8px;font-size:24px}.stats{display:flex;gap:16px;flex-wrap:wrap}.stats span{padding:7px 12px;background:#edf4ed;border-radius:8px}main{display:grid;grid-template-columns:minmax(0,1fr) 380px;height:calc(100vh - 150px)}#panelMapa{position:relative;overflow:hidden;background:#eef2eb}svg{width:100%;height:100%;touch-action:none}#geografico{height:100%;display:none}aside{padding:16px;overflow:auto;background:white;border-left:1px solid #ddd}button,select,input,textarea{font:inherit;padding:7px;border:1px solid #bdcbbf;border-radius:5px}button{cursor:pointer;background:white;color:#164e35}button:hover{background:#e6f1e8}nav{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.lista{display:grid;gap:5px;margin-top:12px}.registro{text-align:left;font-size:13px;overflow-wrap:anywhere}.detalle{border-top:1px solid #ddd;margin-top:16px;padding-top:12px;overflow-wrap:anywhere}img{max-width:100%;height:auto;border-radius:5px}.note{font-size:12px;color:#53655b}.legend{position:absolute;bottom:12px;left:12px;background:#fffffff0;padding:10px;border-radius:8px;font-size:12px;pointer-events:none}a{color:#175c3e}textarea{width:100%;min-height:60px;margin:8px 0}#pendientes{font-size:12px}#buscar{width:100%}.coords{font-family:monospace;font-size:12px}@media(max-width:800px){main{grid-template-columns:1fr;height:auto}#panelMapa{height:55vh}aside{height:70vh}.stats{gap:5px}header{padding:12px}}
</style>
<header><h1>Inventario de árboles</h1><div id="stats" class="stats"></div><nav>
<button id="mas">+</button><button id="menos">−</button><button id="encuadrar">Encuadrar</button>
<button id="base">Cargar mapa de calles</button><button id="local">Vista local</button>
<label><input type="checkbox" id="verCamaras" checked> Cámaras</label>
<label><input type="checkbox" id="verRayos"> Observaciones</label>
<label><input type="checkbox" id="verIncertidumbre" checked> Incertidumbre</label>
</nav></header>
<main><section id="panelMapa"><svg id="plano" aria-label="Mapa local de árboles"></svg><div id="geografico"></div>
<div class="legend">● Verde: identidad confirmada · naranja: candidato · rojo: revisar<br>◆ Azul: cámara · líneas: direcciones, no distancias medidas<br>Círculos: incertidumbre heurística, sin calibración estadística</div></section>
<aside><div id="relevamiento"></div><p class="note">Los grupos y árboles sin ubicación aparecen en la lista. El total confirmado excluye candidatos y grupos.</p>
<input id="buscar" placeholder="Buscar ID, imagen o estado"><select id="periodo"><option value="all">Todas las fechas</option></select>
<select id="tipo"><option value="all">Todos los registros</option><option value="tree">Árboles</option><option value="group">Grupos</option><option value="camera">Cámaras</option><option value="observation">Observaciones</option></select>
<div id="lista" class="lista"></div><div id="detalle" class="detalle"></div>
<div class="detalle"><b>Revisión local</b><p class="note">Las revisiones se descargan para aplicarlas al inventario. Este archivo no modifica la base de datos.</p>
<textarea id="motivo" placeholder="Motivo y evidencia de la corrección"></textarea><button id="guardar">Descargar revisiones</button><div id="pendientes"></div></div>
</aside></main>
<script id="datos" type="application/json">__DATOS__</script>
<script>
'use strict';
const datos=JSON.parse(document.getElementById('datos').textContent),svg=document.getElementById('plano'),NS='http://www.w3.org/2000/svg';
const todos=[...datos.trees,...datos.groups,...datos.cameras,...datos.observations],porId=new Map(todos.map(f=>[String(f.id),f]));
const revisiones=[],counts=datos.counts;
function nodo(tag,texto,padre){const n=document.createElement(tag);if(texto!==undefined)n.textContent=texto;if(padre)padre.append(n);return n;}
function s(tag,attrs,padre){const n=document.createElementNS(NS,tag);for(const [k,v]of Object.entries(attrs))n.setAttribute(k,v);if(padre)padre.append(n);return n;}
for(const [titulo,k]of [['Confirmados','arboles_confirmados'],['Candidatos','candidatos_individuales'],['Grupos pendientes','grupos_no_resueltos'],['Observaciones','observaciones']])nodo('span',`${titulo}: ${counts[k]}`,document.getElementById('stats'));
document.getElementById('relevamiento').textContent=`Relevamiento: ${datos.survey.id}`;
if(datos.survey.synthetic)document.getElementById('relevamiento').textContent+=' · ESCENA SINTÉTICA, no es un inventario real';
function epoch(f){const p=f.properties;if(p.epoch)return String(p.epoch);return p.captured_at?String(new Date(p.captured_at).getUTCFullYear()):'unknown';}
for(const e of [...new Set(todos.map(epoch))].sort()) {const o=nodo('option',e==='unknown'?'Fecha desconocida':e,document.getElementById('periodo'));o.value=e;}
function visible(f){const e=document.getElementById('periodo').value;return e==='all'||epoch(f)===e;}
function xy(f){const p=f.properties;return p.kind==='tree'?p.fit?.xy:p.kind==='camera'?p.xy:p.kind==='observation'?p.ray?.origin_xy:null;}
function color(f){return f.properties.kind==='camera'?'#2674a6':f.properties.identity_status==='confirmed'?'#228148':f.properties.identity_status==='needs_review'?'#b64232':'#d18b16';}
let limites=[-25,-25,50,50],vista,geo=null,capas=null;
function encuadre(){const puntos=[...datos.trees,...datos.cameras].filter(visible).map(xy).filter(Boolean);if(puntos.length){const xs=puntos.map(p=>p[0]),ys=puntos.map(p=>-p[1]);let x=Math.min(...xs),y=Math.min(...ys),w=Math.max(...xs)-x,h=Math.max(...ys)-y;const lado=Math.max(w,h,40),pad=lado*.15;limites=[x-pad,y-pad,Math.max(w,40)+2*pad,Math.max(h,40)+2*pad];}vista=[...limites];dibujar();if(geo){const puntosGeo=datos.cameras.filter(f=>visible(f)&&f.geometry).map(f=>[f.geometry.coordinates[1],f.geometry.coordinates[0]]);if(puntosGeo.length)geo.fitBounds(puntosGeo,{padding:[30,30],maxZoom:19});}}
function dibujar(){svg.replaceChildren();svg.setAttribute('viewBox',vista.join(' '));
 const paso=Math.pow(10,Math.floor(Math.log10(Math.max(vista[2],vista[3])/5)));const grid=s('g',{stroke:'#cfd9cd','stroke-width':'.15'},svg);
 for(let x=Math.floor(vista[0]/paso)*paso;x<vista[0]+vista[2];x+=paso)s('line',{x1:x,y1:vista[1],x2:x,y2:vista[1]+vista[3]},grid);
 for(let y=Math.floor(vista[1]/paso)*paso;y<vista[1]+vista[3];y+=paso)s('line',{x1:vista[0],y1:y,x2:vista[0]+vista[2],y2:y},grid);
 const escala=Math.max(vista[2],vista[3])/220;
 const etiqueta=s('text',{x:vista[0]+escala*3,y:vista[1]+escala*7,'font-size':escala*3,fill:'#526653'},svg);etiqueta.textContent=`Grilla: ${paso} m · norte ↑`;
 if(document.getElementById('verRayos').checked)for(const f of datos.observations.filter(visible)){const r=f.properties.ray;if(!r?.valid)continue;const p=r.origin_xy,d=r.direction,len=f.properties.ray_display_length_m;s('line',{x1:p[0],y1:-p[1],x2:p[0]+d[0]*len,y2:-p[1]-d[1]*len,stroke:'#849c89','stroke-width':escala*.4,opacity:'.7'},svg).onclick=()=>detalle(f);}
 if(document.getElementById('verCamaras').checked)for(const f of datos.cameras.filter(visible)){const p=xy(f);if(p)s('rect',{x:p[0]-escala,y:-p[1]-escala,width:escala*2,height:escala*2,fill:'#2674a6'},svg).onclick=()=>detalle(f);}
 for(const f of datos.trees.filter(visible)){const p=xy(f);if(!p)continue;const radio=f.properties.fit?.uncertainty_m;if(radio&&document.getElementById('verIncertidumbre').checked)s('circle',{cx:p[0],cy:-p[1],r:radio,fill:'none',stroke:color(f),'stroke-width':escala*.3,'stroke-dasharray':`${escala} ${escala}`},svg);const c=s('circle',{cx:p[0],cy:-p[1],r:escala*1.5,fill:color(f),stroke:'white','stroke-width':escala*.35},svg);c.onclick=()=>detalle(f);}
 renderGeo();}
function zoom(f){const [x,y,w,h]=vista;if(Math.max(w,h)*f>1e6||Math.min(w,h)*f<.1)return;vista=[x+w*(1-f)/2,y+h*(1-f)/2,w*f,h*f];dibujar();}document.getElementById('mas').onclick=()=>zoom(.75);document.getElementById('menos').onclick=()=>zoom(1.3);document.getElementById('encuadrar').onclick=encuadre;
svg.addEventListener('wheel',e=>{e.preventDefault();zoom(e.deltaY>0?1.15:.87);},{passive:false});let arrastre=null;svg.onpointerdown=e=>{if(e.target!==svg&&typeof e.target.onclick==='function')return;arrastre=[e.clientX,e.clientY,...vista];svg.setPointerCapture(e.pointerId);};svg.onpointermove=e=>{if(!arrastre)return;const r=svg.getBoundingClientRect(),esc=Math.max(arrastre[4]/r.width,arrastre[5]/r.height);vista=[arrastre[2]-(e.clientX-arrastre[0])*esc,arrastre[3]-(e.clientY-arrastre[1])*esc,arrastre[4],arrastre[5]];dibujar();};svg.onpointerup=()=>{arrastre=null;};svg.onpointercancel=()=>{arrastre=null;};
function lista(){const cont=document.getElementById('lista');cont.replaceChildren();const q=document.getElementById('buscar').value.toLowerCase(),tipo=document.getElementById('tipo').value;for(const f of todos.filter(f=>visible(f)&&(tipo==='all'||f.properties.kind===tipo)&&JSON.stringify([f.id,f.properties.image_id,f.properties.identity_status,f.properties.status]).toLowerCase().includes(q))){const p=f.properties;const b=nodo('button',`${p.kind} · ${String(f.id).slice(0,12)} · ${p.identity_status||p.status||p.role||''}`,cont);b.className='registro';b.onclick=()=>detalle(f);}}
function encolar(accion){const motivo=document.getElementById('motivo').value.trim();if(!motivo){alert('Escribí el motivo de la corrección.');return;}accion.reason=motivo;const indice=revisiones.findIndex(a=>a.type===accion.type&&a.target===accion.target);if(indice>=0)revisiones[indice]=accion;else revisiones.push(accion);document.getElementById('pendientes').textContent=`Revisiones pendientes de descargar: ${revisiones.length}`;}
function detalle(f){const d=document.getElementById('detalle');d.replaceChildren();const p=f.properties;nodo('h3',p.kind,d);nodo('div',String(f.id),d).className='coords';nodo('p',p.identity_status||p.status||p.role||'',d);if(f.geometry?.type==='Point')nodo('p',`Lon/lat: ${f.geometry.coordinates.map(x=>x.toFixed(7)).join(', ')}`,d);if(p.review_reason||p.reason)nodo('p',p.review_reason||p.reason,d);if(p.fit)nodo('p',`Posición: ${p.fit.method}; incertidumbre heurística: ${p.fit.uncertainty_m==null?'no medida':p.fit.uncertainty_m.toFixed(1)+' m'}`,d);
 if(p.view_url){const a=nodo('a','Ver captura en Mapillary',d);a.href=p.view_url;a.target='_blank';a.rel='noopener noreferrer';}
 if(p.creator)nodo('p',`Autor: ${p.creator.username||p.creator.id||''} · Mapillary`,d);
 if(p.kind==='tree'){nodo('button','Confirmar identidad',d).onclick=()=>encolar({type:'confirm',target:String(f.id)});nodo('button','Rechazar',d).onclick=()=>encolar({type:'reject',target:String(f.id)});}
 if(p.kind==='observation'){nodo('p',`Imagen: ${p.image_id}; caja: ${p.bbox_xyxy.map(x=>x.toFixed(1)).join(', ')}; score: ${p.score.toFixed(3)}`,d);if(!p.ray?.valid)nodo('p',p.ray?.reason||'Sin geometría',d);if(p.evidence){const img=nodo('img',undefined,d);img.src=p.evidence.url;img.alt='Recorte de la observación';const ayuda=nodo('p','Para marcar un punto consistente del tronco, escribí el motivo y hacé clic sobre el recorte.',d);ayuda.className='note';img.onclick=e=>{const r=img.getBoundingClientRect(),c=p.evidence.crop_box;const pixel=[c[0]+(e.clientX-r.left)/r.width*(c[2]-c[0]),c[1]+(e.clientY-r.top)/r.height*(c[3]-c[1])];encolar({type:'set_anchor',target:String(f.id),anchor:{pixel}});};}}
 for(const id of p.observation_ids||[]){const otro=porId.get(String(id));if(otro)nodo('button',`Ver observación ${String(id).slice(0,8)}`,d).onclick=()=>detalle(otro);}
 for(const id of p.member_ids||[]){const otro=porId.get(String(id));if(otro)nodo('button',`Ver individuo ${String(id).slice(0,8)}`,d).onclick=()=>detalle(otro);}}
document.getElementById('guardar').onclick=()=>{if(!revisiones.length){alert('No hay revisiones pendientes.');return;}const blob=new Blob([JSON.stringify({actions:revisiones},null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=nodo('a');a.href=url;a.download='correcciones.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
for(const id of ['verCamaras','verRayos','verIncertidumbre'])document.getElementById(id).onchange=dibujar;document.getElementById('buscar').oninput=lista;document.getElementById('tipo').onchange=lista;document.getElementById('periodo').onchange=()=>{lista();encuadre();};
function renderGeo(){if(!geo)return;capas.clearLayers();const muestra=[...datos.trees,...(document.getElementById('verCamaras').checked?datos.cameras:[]),...(document.getElementById('verRayos').checked?datos.observations:[])].filter(f=>visible(f)&&f.geometry);for(const f of muestra){const capa=L.geoJSON(f,{style:{color:'#849c89',weight:1},pointToLayer:(_,latlng)=>L.circleMarker(latlng,{radius:6,color:color(f),fillOpacity:.9})}).addTo(capas);capa.on('click',()=>detalle(f));if(f.properties.kind==='tree'&&f.properties.fit?.uncertainty_m&&document.getElementById('verIncertidumbre').checked)L.circle([f.geometry.coordinates[1],f.geometry.coordinates[0]],{radius:f.properties.fit.uncertainty_m,color:color(f),weight:1,fillOpacity:0}).addTo(capas);}}
document.getElementById('local').onclick=()=>{svg.style.display='block';document.getElementById('geografico').style.display='none';};
document.getElementById('base').onclick=()=>{if(geo){svg.style.display='none';document.getElementById('geografico').style.display='block';geo.invalidateSize();return;}const boton=document.getElementById('base');boton.textContent='Cargando mapa…';const css=nodo('link');css.rel='stylesheet';css.href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';document.head.append(css);const script=nodo('script');script.src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';script.onerror=()=>{boton.textContent='Sin conexión: usar vista local';};script.onload=()=>{svg.style.display='none';document.getElementById('geografico').style.display='block';geo=L.map('geografico').setView([datos.survey.origin?.[1]||0,datos.survey.origin?.[0]||0],17);L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'}).addTo(geo);capas=L.layerGroup().addTo(geo);boton.textContent='Mapa de calles';renderGeo();encuadre();};document.head.append(script);};
lista();encuadre();
</script></html>'''
