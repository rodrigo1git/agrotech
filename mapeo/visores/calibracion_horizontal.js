// Transformación de visualización: no depende del detector ni de Leaflet.
const CalibracionMapa = (()=>{
 function latitud(datos){
  const origen=datos.survey?.origin;
  if(Array.isArray(origen)&&origen.length>=2)return Number(origen[1]);
  for(const nombre of ['cameras','trees','groups']){
   const f=(datos[nombre]||[]).find(f=>f.geometry?.type==='Point');
   if(f)return Number(f.geometry.coordinates[1]);
  }
  throw new Error('No hay una latitud de referencia para desplazar el mapa.');
 }
 function metrosPorRadian(lat){
  if(!Number.isFinite(lat)||Math.abs(lat)>=90)throw new Error('Latitud de referencia inválida.');
  const phi=lat*Math.PI/180;
  return 6378137/Math.sqrt(1-6.6943799901413165e-3*Math.sin(phi)**2)*Math.cos(phi);
 }
 function metrosPorRadianLatitud(lat){
  metrosPorRadian(lat);const phi=lat*Math.PI/180,e2=6.6943799901413165e-3;
  return 6378137*(1-e2)/(1-e2*Math.sin(phi)**2)**1.5;
 }
 function offsets(datos){const c=datos.map_calibration||datos.horizontal_calibration||{};return {east:c.offset_east_m||0,north:c.offset_north_m||0};}
 function parametros(datos){const c=datos.map_calibration||datos.horizontal_calibration||{};return {...c,rotation_deg:c.rotation_deg||0};}
 function girar(v,grados){const a=grados*Math.PI/180,c=Math.cos(a),s=Math.sin(a);return [c*v[0]+s*v[1],-s*v[0]+c*v[1]];}
 function aplicar(datos,metros,norte=0,rotacion=undefined,camaraPivote=undefined){
  if([metros,norte].some(v=>typeof v!=='number'||!Number.isFinite(v)))throw new Error('Ingresá desplazamientos válidos en metros.');
  const copia=JSON.parse(JSON.stringify(datos)),previo=offsets(datos),meta=parametros(datos),viejo=meta.rotation_deg;
  let angulo=rotacion===undefined? viejo:rotacion;
  if(typeof angulo!=='number'||!Number.isFinite(angulo))throw new Error('Ingresá un ángulo válido en grados.');
  angulo=((angulo+180)%360+360)%360-180;
  const delta=metros-previo.east,deltaNorte=norte-previo.north;
  if(delta===0&&deltaNorte===0&&angulo===viejo&&(camaraPivote===undefined||camaraPivote===meta.pivot_camera_id))return copia;
  const lat=latitud(datos),grados=delta/metrosPorRadian(lat)*180/Math.PI,gradosNorte=deltaNorte/metrosPorRadianLatitud(lat)*180/Math.PI;
  const ref=datos.survey?.origin;
  const lon=Array.isArray(ref)?ref[0]:['cameras','trees','groups'].flatMap(k=>datos[k]||[]).find(f=>f.geometry?.type==='Point').geometry.coordinates[0];
  const escalaE=metrosPorRadian(lat)*Math.PI/180,escalaN=metrosPorRadianLatitud(lat)*Math.PI/180;
  function plana(p){return [(p[0]-lon)*escalaE,(p[1]-lat)*escalaN];}
  function inversa(p,pivote){const v=girar([p[0]-previo.east-pivote[0],p[1]-previo.north-pivote[1]],-viejo);return [v[0]+pivote[0],v[1]+pivote[1]];}
  const pivoteViejo=meta.pivot_xy||[0,0],pivoteGeoViejo=plana(meta.pivot_coordinates||[lon,lat]);
  const camaras=(datos.cameras||[]).filter(f=>f.geometry?.type==='Point');
  let iid=camaraPivote===undefined?meta.pivot_camera_id:camaraPivote;
  if(iid==null&&camaras.length)iid=String(camaras[0].id);
  const camara=camaras.find(f=>String(f.id)===String(iid));
  if(iid!=null&&!camara)throw new Error('La cámara de referencia no existe en este relevamiento.');
  const pivoteGeo=camara?inversa(plana(camara.geometry.coordinates),pivoteGeoViejo):[0,0];
  const pivote=camara?inversa(camara.properties.xy||plana(camara.geometry.coordinates),pivoteViejo):[0,0];
  const pivotCoordinates=[lon+pivoteGeo[0]/escalaE,lat+pivoteGeo[1]/escalaN];
  function transformarPunto(p,oldPivot,newPivot){const raw=inversa(p,oldPivot),v=girar([raw[0]-newPivot[0],raw[1]-newPivot[1]],angulo);return [v[0]+newPivot[0]+metros,v[1]+newPivot[1]+norte];}
  function coords(v){
   if(!Array.isArray(v))return v;
   if(v.length>=2&&v.slice(0,2).every(x=>typeof x==='number')){
    if(angulo!==0||viejo!==0){const p=transformarPunto(plana(v),pivoteGeoViejo,pivoteGeo);return [lon+p[0]/escalaE,lat+p[1]/escalaN,...v.slice(2)];}
    return [v[0]+grados,v[1]+gradosNorte,...v.slice(2)];
   }
   return v.map(coords);
  }
  function transformar(v){
   if(Array.isArray(v))return v.map(transformar);
   if(v===null||typeof v!=='object')return v;
   const r={};
   for(const [k,x]of Object.entries(v)){
    if(['coordinates','raw_coordinates'].includes(k))r[k]=coords(x);
    else if(['xy','origin_xy','camera_xy','raw_xy'].includes(k)&&Array.isArray(x)&&x.length===2)r[k]=transformarPunto(x,pivoteViejo,pivote);
    else if(k==='direction'&&Array.isArray(x)&&x.length===2)r[k]=girar(x,angulo-viejo);
    else if(k==='bearing_deg'&&typeof x==='number')r[k]=((x+angulo-viejo)%360+360)%360;
    else r[k]=transformar(x);
   }
   return r;
  }
  for(const nombre of ['trees','cameras','observations','groups'])copia[nombre]=(copia[nombre]||[]).map(transformar);
  copia.map_calibration={offset_east_m:metros,offset_north_m:norte,rotation_deg:angulo,pivot_camera_id:iid??null,pivot_xy:pivote,pivot_coordinates:pivotCoordinates,reference_latitude:lat,longitude_offset_deg:metros/metrosPorRadian(lat)*180/Math.PI,latitude_offset_deg:norte/metrosPorRadianLatitud(lat)*180/Math.PI,method:'rigid_rotation_translation'};
  copia.horizontal_calibration={...copia.map_calibration};
  return copia;
 }
 function cambiarPivote(datos,id){
  const actual=offsets(datos),meta=parametros(datos),ensayo=aplicar(datos,actual.east,actual.north,meta.rotation_deg,id);
  const antes=datos.cameras.find(f=>String(f.id)===String(id)),despues=ensayo.cameras.find(f=>String(f.id)===String(id));
  if(!antes||!despues)throw new Error('Cámara de referencia inválida.');
  const lat=latitud(datos),e=(antes.geometry.coordinates[0]-despues.geometry.coordinates[0])*Math.PI/180*metrosPorRadian(lat),n=(antes.geometry.coordinates[1]-despues.geometry.coordinates[1])*Math.PI/180*metrosPorRadianLatitud(lat);
  return aplicar(datos,actual.east+e,actual.north+n,meta.rotation_deg,id);
 }
 return {aplicar,metrosPorRadian,metrosPorRadianLatitud,latitud,offsets,parametros,cambiarPivote};
})();
const CalibracionHorizontal=CalibracionMapa;
