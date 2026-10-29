/* Vista ampliada de las observaciones de una identidad, sin alterar sus datos. */
const EvidenciaArboles=(()=>{
 function vistas(arbol,observaciones){
  const porId=new Map(observaciones.map(o=>[String(o.id),o]));
  const ids=[...(arbol.properties.map_position?.source_observation_ids||[]),...(arbol.properties.observation_ids||[])];
  return [...new Set(ids.map(String))].map(id=>porId.get(id)).filter(o=>o?.properties.evidence?.url);
 }
 function crear({obtenerObservaciones,obtenerCamara,abrirCamara}){
  const el=id=>document.getElementById(id),dialogo=el('visorArboles'),escena=el('arbolEscena');
  let observaciones=[],indice=0,version=0,escala=1;
  function zoom(valor){
   escala=Math.max(1,Math.min(3,valor));const img=el('arbolImagen');
   if(img.naturalWidth&&img.naturalHeight){
    const ajuste=Math.min(escena.clientWidth/img.naturalWidth,escena.clientHeight/img.naturalHeight);
    img.style.width=`${img.naturalWidth*ajuste*escala}px`;img.style.height=`${img.naturalHeight*ajuste*escala}px`;
   }else{img.style.width='100%';img.style.height='100%';}
   el('arbolZoomMenos').disabled=escala===1||!observaciones.length;el('arbolZoomMas').disabled=escala===3||!observaciones.length;
   el('arbolZoomEstado').textContent=escala===1?'Ajustada':`${escala.toFixed(1)}×`;
   if(escala===1){escena.scrollLeft=0;escena.scrollTop=0;}
  }
  function mostrar(){
   const numero=++version,obs=observaciones[indice],p=obs?.properties;
   const img=document.createElement('img');img.id='arbolImagen';img.draggable=false;
   img.alt=p?`Árbol detectado en la imagen ${p.image_id}`:'Sin imagen de evidencia disponible';
   el('arbolImagen').replaceWith(img);
   const estado=el('arbolEstado');estado.hidden=false;
   estado.textContent=p?'Cargando evidencia…':'Este árbol no tiene una imagen de evidencia disponible.';
   img.hidden=!p;
   img.onload=()=>{if(numero!==version)return;estado.hidden=true;zoom(escala);};
   img.onerror=()=>{if(numero!==version)return;img.hidden=true;estado.hidden=false;estado.textContent='No se pudo cargar esta evidencia. Podés probar otra vista o abrir la cámara.';};
   if(p)img.src=p.evidence.url;
   el('arbolContador').textContent=observaciones.length?`Vista ${indice+1} de ${observaciones.length}`:'Sin vistas';
   el('arbolAnterior').disabled=indice===0;el('arbolSiguiente').disabled=indice>=observaciones.length-1;
   const camara=p?obtenerCamara(p.image_id):null;
   el('arbolVerCamara').disabled=!camara?.properties.photo?.url&&!camara?.properties.photo?.full_url;
   const fecha=typeof p?.captured_at==='number'?new Date(p.captured_at).toLocaleString('es-AR'):'';
   el('arbolDescripcion').textContent=p?[`Imagen ${p.image_id}`,fecha,'Recorte de la detección'].filter(Boolean).join(' · '):'';
   zoom(1);
  }
  function abrir(arbol){
   observaciones=vistas(arbol,obtenerObservaciones());indice=0;
   el('arbolTitulo').textContent=`Árbol ${arbol.id}`;
   const nombres={confirmed:'Identidad confirmada',candidate:'Candidato pendiente de revisión',needs_review:'Requiere revisión'};
   el('arbolIdentidad').textContent=nombres[arbol.properties.identity_status]||'Imágenes que respaldan este registro';
   if(!dialogo.open)dialogo.showModal();mostrar();
  }
  function mover(delta){
   const siguiente=indice+delta;
   if(!dialogo.open||siguiente<0||siguiente>=observaciones.length)return false;
   indice=siguiente;mostrar();return true;
  }
  function cerrar(){if(dialogo.open)dialogo.close();version++;}
  el('arbolAnterior').onclick=()=>mover(-1);el('arbolSiguiente').onclick=()=>mover(1);
  el('arbolCerrar').onclick=cerrar;el('arbolVolverMapa').onclick=cerrar;
  el('arbolZoomMas').onclick=()=>zoom(escala+.5);el('arbolZoomMenos').onclick=()=>zoom(escala-.5);el('arbolAjustar').onclick=()=>zoom(1);
  el('arbolVerCamara').onclick=()=>{
   const id=observaciones[indice]?.properties.image_id,camara=id===undefined?null:obtenerCamara(id);
   if(!camara?.properties.photo?.url&&!camara?.properties.photo?.full_url)return;
   cerrar();abrirCamara(id);
  };
  dialogo.addEventListener('keydown',e=>{
   if(e.key==='Escape'){e.preventDefault();cerrar();return;}
   if(['INPUT','SELECT','TEXTAREA'].includes(e.target?.tagName)||e.altKey||e.ctrlKey||e.metaKey)return;
   if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();mover(e.key==='ArrowRight'?1:-1);}
  });
  dialogo.addEventListener('close',()=>{version++;});
  return {abrir,mover,cerrar};
 }
 return {crear,vistas};
})();
