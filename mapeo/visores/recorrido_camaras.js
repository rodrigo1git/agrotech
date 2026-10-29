/* Galería independiente: solo fotografías locales y metadatos de cámaras. */
const RecorridoCamaras=(()=>{
 const DIRECCIONES={adelante:{angulo:0,boton:'fotoAdelante',texto:'↑ Adelante'},derecha:{angulo:90,boton:'fotoDerecha',texto:'Derecha →'},atras:{angulo:180,boton:'fotoAtras',texto:'↓ Atrás'},izquierda:{angulo:270,boton:'fotoIzquierda',texto:'← Izquierda'}};
 const OPCIONES={max_distance_m:30,min_distance_m:1,max_turn_distance_m:2,sector_half_angle_deg:45};
 const normalizar=a=>((a%360)+360)%360;
 const diferencia=(a,b)=>normalizar(a-b+180)-180;
 function rumbo(f){const v=f.properties.camera_view?.bearing_deg;return typeof v==='number'&&Number.isFinite(v)?normalizar(v):null;}
 function desplazamiento(a,b){
  const par=p=>Array.isArray(p)&&p.length===2&&p.every(Number.isFinite);
  const pa=a.properties.xy,pb=b.properties.xy;
  if(par(pa)&&par(pb))return [pb[0]-pa[0],pb[1]-pa[1]];
  if(a.geometry?.type!=='Point'||b.geometry?.type!=='Point')return null;
  const ga=a.geometry.coordinates,gb=b.geometry.coordinates;
  if(!par(ga)||!par(gb))return null;
  const rad=Math.PI/180;
  return [(gb[0]-ga[0])*rad*6371008.8*Math.cos((ga[1]+gb[1])/2*rad),(gb[1]-ga[1])*rad*6371008.8];
 }
 function vecinos(actual,camaras,opciones={}){
  const config={...OPCIONES};
  for(const k of Object.keys(config))if(typeof opciones?.[k]==='number'&&Number.isFinite(opciones[k])&&opciones[k]>0)config[k]=opciones[k];
  config.sector_half_angle_deg=Math.min(45,config.sector_half_angle_deg);
  const resultado=Object.fromEntries(Object.keys(DIRECCIONES).map(k=>[k,null]));
  const frente=rumbo(actual),fecha=dia(actual);
  if(frente===null)return resultado;
  for(const f of camaras){
   if(String(f.id)===String(actual.id)||(!f.properties.photo?.url&&!f.properties.photo?.full_url)||dia(f)!==fecha)continue;
   if(fecha==='sin fecha'&&(!actual.properties.sequence||actual.properties.sequence!==f.properties.sequence))continue;
   const v=desplazamiento(actual,f);if(!v)continue;
   const distancia=Math.hypot(...v);if(distancia>config.max_distance_m)continue;
   const otroRumbo=rumbo(f),giro=otroRumbo===null?null:diferencia(otroRumbo,frente);
   const girar=distancia<=config.max_turn_distance_m&&giro!==null&&Math.abs(giro)>=45;
   if(!girar&&distancia<config.min_distance_m)continue;
   const angulo=girar?normalizar(giro):normalizar(Math.atan2(v[0],v[1])*180/Math.PI-frente);
   // Cada destino ocupa una sola dirección, incluso justo en una diagonal.
   const clave=['adelante','derecha','atras','izquierda'][Math.floor(normalizar(angulo+45)/90)];
   const error=Math.abs(diferencia(angulo,DIRECCIONES[clave].angulo));
   if(error>config.sector_half_angle_deg)continue;
   const penalidadSecuencia=actual.properties.sequence&&actual.properties.sequence!==f.properties.sequence?1.1:1;
   const score=(distancia+.5)*(1+.4*error/45)*penalidadSecuencia;
   const previo=resultado[clave];
   if(!previo||score<previo.score||(score===previo.score&&String(f.id)<String(previo.camera.id)))resultado[clave]={camera:f,distance_m:distancia,relative_bearing_deg:angulo,movement:girar?'turn':'move',score};
  }
  return resultado;
 }
 function dia(camara){
  const t=camara.properties.captured_at;
  return typeof t==='number'&&Number.isFinite(t)?new Date(t).toISOString().slice(0,10):'sin fecha';
 }
 function rutas(camaras){
  const grupos=new Map();
  for(const f of camaras){
   if(!f.properties.photo?.full_url&&!f.properties.photo?.url)continue;
   const fecha=dia(f),secuencia=f.properties.sequence;
   // Sin secuencia no se puede suponer continuidad entre cámaras.
   const clave=JSON.stringify([secuencia||String(f.id),fecha]);
   if(!grupos.has(clave))grupos.set(clave,{id:clave,fecha,secuencia,camaras:[]});
   grupos.get(clave).camaras.push(f);
  }
  for(const ruta of grupos.values())ruta.camaras.sort((a,b)=>(a.properties.captured_at??Infinity)-(b.properties.captured_at??Infinity)||String(a.id).localeCompare(String(b.id)));
  return [...grupos.values()].sort((a,b)=>a.fecha.localeCompare(b.fecha)||a.id.localeCompare(b.id));
 }
 function crear({obtenerCamaras,onCambiar,obtenerOpciones=()=>({})}){
  const el=id=>document.getElementById(id),dialogo=el('visorCamaras'),escena=el('fotoEscena');
  let recorridos=[],ruta=null,indice=-1,escala=1,version=0,destinos={};
  function mostrarDirecciones(f){
   destinos=vecinos(f,obtenerCamaras(),obtenerOpciones());
   for(const [clave,d]of Object.entries(DIRECCIONES)){
    const destino=destinos[clave],b=el(d.boton);b.disabled=!destino;
    b.textContent=d.texto+(destino?(destino.movement==='turn'?' · girar':` · ${Math.round(destino.distance_m)} m`):'');
    b.title=destino?`${destino.movement==='turn'?'Cambiar la vista':'Ir'} a cámara ${destino.camera.id}${destino.camera.properties.sequence!==f.properties.sequence?' · otro recorrido del mismo día':''}`:'No hay una cámara cercana disponible en esta dirección.';
   }
   el('fotoDireccionEstado').textContent=rumbo(f)===null?'Esta foto no tiene orientación disponible. Podés usar el orden de captura.':Object.values(destinos).some(Boolean)?'Direcciones respecto de la foto actual. Solo cámaras cercanas de la misma fecha.':'No hay cámaras cercanas en estas direcciones. Podés usar el orden de captura o elegir otro recorrido.';
  }
  function zoom(valor){
   escala=Math.max(1,Math.min(3,valor));
   const img=el('fotoImagen');
   img.style.width=escala===1?'auto':`${escena.clientWidth*escala}px`;
   img.style.maxWidth=escala===1?'100%':'none';
   img.style.maxHeight=escala===1?'100%':'none';
   el('fotoZoomMenos').disabled=escala===1;el('fotoZoomMas').disabled=escala===3;
   el('fotoZoomEstado').textContent=escala===1?'Ajustada':`${escala.toFixed(1)}×`;
   if(escala===1){escena.scrollLeft=0;escena.scrollTop=0;}
  }
  function mostrar(){
   const f=ruta.camaras[indice],p=f.properties,photo=p.photo;
   const numero=++version;
   const anterior=el('fotoImagen');
   // Cada cambio tiene su propio elemento: un onload/onerror atrasado no puede
   // reemplazar la imagen o el estado de la cámara que está viendo el usuario.
   const img=document.createElement('img');img.id='fotoImagen';
   img.alt=`Captura Mapillary ${p.image_id||f.id}${photo.annotated?' con detecciones de árboles':''}`;
   img.draggable=false;
   anterior.replaceWith(img);
   const estado=el('fotoEstado');estado.hidden=false;estado.textContent='Cargando fotografía…';
   let miniatura=false;
   img.onload=()=>{if(numero!==version)return;estado.hidden=!miniatura;estado.textContent=miniatura?'No se pudo cargar la versión grande. Se muestra la miniatura.':'';};
   img.onerror=()=>{
    if(numero!==version)return;
    if(!miniatura&&photo.full_url&&photo.url&&photo.full_url!==photo.url){miniatura=true;img.src=photo.url;return;}
    img.hidden=true;estado.hidden=false;estado.textContent='No se pudo cargar esta foto. Podés seguir a otra cámara o abrirla en Mapillary.';
   };
   img.src=photo.full_url||photo.url;
   el('fotoTitulo').textContent=`Cámara ${p.image_id||f.id}`;
   el('fotoContador').textContent=`${indice+1} / ${ruta.camaras.length}`;
   const fecha=typeof p.captured_at==='number'?new Date(p.captured_at).toLocaleString('es-AR'):'Fecha desconocida';
   const autor=p.creator?.username||p.creator?.id;
   el('fotoDescripcion').textContent=[fecha,photo.annotated?`${photo.detections??0} detecciones · cajas de DINO`:'Fotografía del recorrido',autor?`Autor: ${autor} · Mapillary`:''].filter(Boolean).join(' · ');
   el('fotoAnterior').disabled=indice===0;el('fotoSiguiente').disabled=indice===ruta.camaras.length-1;
   el('fotoRecorrido').value=ruta.id;
   el('fotoMapillary').href=p.view_url||`https://www.mapillary.com/app/?pKey=${encodeURIComponent(p.image_id||f.id)}`;
   mostrarDirecciones(f);zoom(1);onCambiar?.(f);
  }
  function abrir(id){
   recorridos=rutas(obtenerCamaras());
   ruta=recorridos.find(r=>r.camaras.some(f=>String(f.id)===String(id)));
   if(!ruta)return false;
   indice=ruta.camaras.findIndex(f=>String(f.id)===String(id));
   const selector=el('fotoRecorrido');selector.replaceChildren();
   recorridos.forEach((r,i)=>{const opcion=document.createElement('option');opcion.value=r.id;opcion.textContent=`${r.fecha} · Recorrido ${i+1} · ${r.camaras.length} fotos`;selector.append(opcion);});
   if(!dialogo.open)dialogo.showModal();
   mostrar();return true;
  }
  function mover(delta){
   if(!dialogo.open||!ruta)return false;
   const siguiente=indice+delta;
   if(siguiente<0||siguiente>=ruta.camaras.length)return false;
   indice=siguiente;mostrar();return true;
  }
  function navegar(direccion){
   if(!dialogo.open||!ruta||!DIRECCIONES[direccion])return false;
   const destino=destinos[direccion];if(!destino)return false;
   ruta=recorridos.find(r=>r.camaras.some(f=>String(f.id)===String(destino.camera.id)));
   if(!ruta)return false;
   indice=ruta.camaras.findIndex(f=>String(f.id)===String(destino.camera.id));mostrar();return true;
  }
  function cerrar(){if(dialogo.open)dialogo.close();version++;}
  el('fotoAnterior').onclick=()=>mover(-1);el('fotoSiguiente').onclick=()=>mover(1);
  for(const [clave,d]of Object.entries(DIRECCIONES))el(d.boton).onclick=()=>navegar(clave);
  el('fotoCerrar').onclick=cerrar;el('fotoVolverMapa').onclick=cerrar;
  el('fotoZoomMas').onclick=()=>zoom(escala+.5);el('fotoZoomMenos').onclick=()=>zoom(escala-.5);el('fotoAjustar').onclick=()=>zoom(1);
  el('fotoRecorrido').onchange=()=>{ruta=recorridos.find(r=>r.id===el('fotoRecorrido').value);indice=0;mostrar();};
  dialogo.addEventListener('keydown',e=>{
   if(e.key==='Escape'){e.preventDefault();cerrar();return;}
   if(['INPUT','SELECT','TEXTAREA'].includes(e.target?.tagName)||e.altKey||e.ctrlKey||e.metaKey)return;
   const direccion={ArrowUp:'adelante',ArrowDown:'atras',ArrowLeft:'izquierda',ArrowRight:'derecha'}[e.key];
   if(direccion){e.preventDefault();navegar(direccion);}
  });
  dialogo.addEventListener('close',()=>{version++;});
  return {abrir,mover,navegar,cerrar};
 }
 return {crear,rutas,vecinos,opciones:OPCIONES};
})();
