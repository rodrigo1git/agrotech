"""Geometría, identidad, persistencia, revisión y exportación sin acceso a la red."""

import copy
import itertools
import json
import math
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from mapear_arboles import cargar_config
from mapeo.almacen import Almacen
from mapeo.asociacion import asignacion
from mapeo.camaras import MarcoLocal, diferencia_angular, proyectar_observacion, rayo_pixel
from mapeo.demo import registro_sintetico
from mapeo.exportacion import exportar
from mapeo.inventario import contadores, corregir, reconciliar
from mapeo.localizacion import ajustar, interseccion


PUNTOS = [(12., 10.), (14., 10.)]
CAMARAS = [(3., 0.), (10., 0.), (20., 0.)]


class GeometriaTests(unittest.TestCase):
    def setUp(self):
        self.config = cargar_config()
        self.marco = MarcoLocal(-59.1405, -37.3351)

    def test_enu_ida_y_vuelta_en_elipsoide(self):
        for lon, lat in [(-59.1405, -37.3351), (-59.15, -37.34), (-59.13, -37.325)]:
            vuelta = self.marco.geografica(*self.marco.proyectar(lon, lat))
            self.assertAlmostEqual(vuelta[0], lon, places=9)
            self.assertAlmostEqual(vuelta[1], lat, places=9)

    def test_heading_cero_no_se_sustituye_y_no_hay_fov_por_defecto(self):
        r = registro_sintetico('1', (13., 0.), PUNTOS)
        meta = r['mapillary']
        meta.pop('computed_rotation')
        meta.update(computed_compass_angle=0., compass_angle=90.)
        obs = {'width':2000, 'height':1200, 'bbox_xyxy':[990,590,1009,609], 'anchor':{'pixel':[999.5,599.5],'verified':True}}
        config = {**self.config, 'allow_heading_only':True}
        ray = proyectar_observacion(obs, meta, self.marco, config)
        self.assertTrue(ray['valid'])
        self.assertAlmostEqual(diferencia_angular(ray['bearing_deg'],0),0,places=3)
        meta.pop('camera_parameters')
        self.assertFalse(proyectar_observacion(obs,meta,self.marco,config)['valid'])

    def test_distorsion_y_resolucion_conservan_rayo(self):
        meta={'camera_type':'perspective','camera_parameters':[.8,.02,.003],'width':2000,'height':1200}
        x,y=.2,-.1
        r2=x*x+y*y
        factor=1+.02*r2+.003*r2*r2
        u,v=999.5+1600*x*factor,599.5+1600*y*factor
        rayo=rayo_pixel(u,v,2000,1200,meta,self.config)
        np.testing.assert_allclose(rayo,np.array([x,y,1])/np.linalg.norm([x,y,1]),atol=1e-9)
        # Píxeles con centros: al escalar por 1/2, (u+.5)/2-.5.
        pequeno=rayo_pixel((u+.5)/2-.5,(v+.5)/2-.5,1000,600,meta,self.config)
        np.testing.assert_allclose(rayo,pequeno,atol=1e-9)

    def test_rotacion_incoherente_y_exif_no_verificado_quedan_pendientes(self):
        r=registro_sintetico('1',(13.,0.),PUNTOS)
        obs={**r['detections'][0],'width':2000,'height':1200}
        meta=copy.deepcopy(r['mapillary'])
        meta['computed_compass_angle']+=90
        self.assertFalse(proyectar_observacion(obs,meta,self.marco,self.config)['valid'])
        meta=copy.deepcopy(r['mapillary']);meta['exif_orientation']=6
        self.assertFalse(proyectar_observacion(obs,meta,self.marco,self.config)['valid'])
        meta['pixel_transform']=np.eye(3).tolist()
        self.assertTrue(proyectar_observacion(obs,meta,self.marco,self.config)['valid'])

    def test_esferica_requiere_habilitacion_y_union_coherente(self):
        meta={'camera_type':'spherical','computed_rotation':[math.pi/2,0,0], 'computed_compass_angle':0}
        with self.assertRaises(ValueError):
            rayo_pixel(1000,500,2000,1000,meta,self.config)
        config={**self.config,'allow_spherical':True}
        izquierda=rayo_pixel(0,500,2000,1000,meta,config)
        derecha=rayo_pixel(2000,500,2000,1000,meta,config)
        np.testing.assert_allclose(izquierda,derecha,atol=1e-10)

    def test_asignacion_optima_con_opcion_no_asociar(self):
        rng=random.Random(27)
        for _ in range(20):
            costos=[[rng.random()*3 for _ in range(2)] for _ in range(3)]
            resultado=asignacion(costos,1.)
            importe=sum(1 if j is None else costos[i][j] for i,j in enumerate(resultado))
            mejor=min(sum(costos[i][j] if j<2 else 1 for i,j in enumerate(permutacion)) for permutacion in itertools.permutations(range(5),3))
            self.assertAlmostEqual(importe,mejor)
            columnas=[j for j in resultado if j is not None]
            self.assertEqual(len(columnas),len(set(columnas)))

    def test_rayos_paralelos_detras_o_sin_baseline_no_generan_posicion(self):
        def obs(clave,cam,dir):
            return {'id':clave,'capture_id':clave,'epoch':'2018','captured_at':1539978452606,
                    'ray':{'origin_xy':cam,'direction':dir,'bearing_deg':math.degrees(math.atan2(dir[0],dir[1]))%360,
                           'uncertainty_deg':1}}
        a=obs('a',[0.,0.],[0.,1.])
        b=obs('b',[10.,0.],[0.,1.])
        self.assertIsNone(interseccion(a,b,self.config))
        self.assertIsNone(ajustar([a,b],self.config))
        c=obs('c',[10.,0.],[1/math.sqrt(2),1/math.sqrt(2)])
        self.assertIsNone(interseccion(a,c,self.config))


class InventarioTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.raiz=Path(self.tmp.name)
        self.config=cargar_config()
        self.almacen=Almacen(self.raiz/'inventario.sqlite')
        self.survey=self.almacen.survey('prueba',self.config)

    def tearDown(self):
        self.almacen.close()
        self.tmp.cleanup()

    def importar(self,registro):
        self.almacen.importar('prueba',registro)
        return reconciliar(self.almacen,self.survey,self.config)

    def individuos(self):
        return [a for a in self.almacen.estado('prueba')['trees'] if a.get('active',True)]

    def cuenta(self):
        estado=self.almacen.estado('prueba')
        return contadores(estado,estado['observations'])

    def escena(self, verified=True):
        registros=[]
        for i,c in enumerate(CAMARAS):
            r=registro_sintetico(str(i+1),c,PUNTOS,timestamp=1539978452606+i*10000,verified=verified)
            registros.append(r)
            self.importar(r)
        return registros

    def test_dos_arboles_proximos_no_se_fusionan_y_conservan_posicion(self):
        self.escena()
        self.assertEqual(self.cuenta()['arboles_confirmados'],2)
        self.assertEqual(len(self.individuos()),2)
        marco=MarcoLocal(*self.survey['origin'])
        verdad=MarcoLocal(-59.1405,-37.3351)
        coords=[marco.geografica(*a['fit']['xy']) for a in self.individuos()]
        for p in PUNTOS:
            original=verdad.geografica(*p)
            self.assertLess(min(math.dist(marco.proyectar(*original),marco.proyectar(*c)) for c in coords),.02)

    def test_reimportar_no_duplica_y_reabrir_conserva_identidades(self):
        registros=self.escena()
        antes=self.almacen.estado('prueba')
        generacion=self.almacen.db.execute('SELECT generation FROM surveys').fetchone()[0]
        for r in registros:self.assertFalse(self.almacen.importar('prueba',r))
        reconciliar(self.almacen,self.survey,self.config)
        self.assertEqual(self.almacen.estado('prueba'),antes)
        self.assertEqual(self.almacen.db.execute('SELECT generation FROM surveys').fetchone()[0],generacion)
        self.almacen.close();self.almacen=Almacen(self.raiz/'inventario.sqlite')
        self.assertEqual(self.almacen.estado('prueba'),antes)

    def test_cajas_sin_anclas_no_se_confirman_como_mediciones(self):
        self.escena(verified=False)
        self.assertEqual(self.cuenta()['arboles_confirmados'],0)

    def test_version_nueva_desactiva_anterior_y_mantiene_ids(self):
        registros=self.escena()
        ids={a['id'] for a in self.individuos()}
        for r in registros:
            nuevo=copy.deepcopy(r);nuevo['revision']='otra-revision'
            self.importar(nuevo)
        self.assertEqual(self.cuenta()['observaciones'],6)
        self.assertEqual(self.cuenta()['arboles_confirmados'],2)
        self.assertEqual({a['id'] for a in self.individuos()},ids)
        self.assertEqual(self.almacen.db.execute('SELECT count(*) FROM runs WHERE active=1').fetchone()[0],3)

    def test_cambio_de_cajas_ambiguo_no_hereda_anclas_sin_evidencia(self):
        r=registro_sintetico('1',CAMARAS[0],[(12.,10.),(12.001,10.)])
        self.importar(r)
        nuevo=copy.deepcopy(r);nuevo['revision']='otra'
        for det in nuevo['detections']:
            det['anchor']=None;det['kind_verified']=False
        self.importar(nuevo)
        actuales=self.almacen.estado('prueba')['observations']
        self.assertTrue(all(o.get('lineage_status')=='ambiguous' for o in actuales))
        self.assertTrue(all(not o.get('anchor') for o in actuales))

    def test_perspectivas_del_mismo_panorama_no_triangulan(self):
        for i,c in enumerate(CAMARAS):
            r=registro_sintetico(str(i),c,[PUNTOS[0]])
            r['mapillary']['capture_id']='misma-captura'
            self.importar(r)
        self.assertEqual(self.cuenta()['arboles_confirmados'],0)
        self.assertTrue(all(a['fit'] is None for a in self.individuos()))

    def test_no_asocia_anos_distintos(self):
        for i,c in enumerate(CAMARAS):
            r=registro_sintetico(str(i),c,[PUNTOS[0]],timestamp=1539978452606+i*366*86400000)
            self.importar(r)
        self.assertEqual(self.cuenta()['arboles_confirmados'],0)
        self.assertTrue(all(a['fit'] is None for a in self.individuos()))

    def test_grupo_que_se_separa_no_deja_un_tercer_arbol(self):
        inicial=registro_sintetico('group',(13.,-10.),PUNTOS,grupo=True)
        inicial['detections'][0].pop('kind');inicial['detections'][0]['kind_verified']=False
        self.importar(inicial)
        placeholder=self.individuos()[0]['id']
        self.escena()
        self.assertEqual(self.cuenta()['arboles_confirmados'],2)
        self.assertEqual(len(self.individuos()),2)
        viejo=next(a for a in self.almacen.estado('prueba')['trees'] if a['id']==placeholder)
        self.assertFalse(viejo['active'])
        self.assertEqual(len(viejo['superseded_by']),2)
        self.assertTrue(any(op['type']=='split' for e in self.almacen.eventos('prueba') for op in e['payload'].get('detail',{}).get('operations',[])))

    def test_otra_vista_agrupada_no_refusiona_individuos(self):
        self.escena()
        ids={a['id'] for a in self.individuos()}
        self.importar(registro_sintetico('group',(13.,-10.),PUNTOS,grupo=True))
        self.assertEqual({a['id'] for a in self.individuos()},ids)
        self.assertEqual(self.cuenta()['arboles_confirmados'],2)

    def test_identidad_revisada_con_evidencia_nueva_contradictoria_no_suma_tres(self):
        inicial=registro_sintetico('group',(13.,-10.),PUNTOS,grupo=True)
        inicial['detections'][0].pop('kind');inicial['detections'][0]['kind_verified']=False
        self.importar(inicial)
        aid=self.individuos()[0]['id']
        corregir(self.almacen,self.survey,self.config,{'type':'confirm','target':aid,'reason':'Evaluación inicial que luego puede corregirse'})
        self.escena()
        self.assertEqual(self.cuenta()['arboles_confirmados'],2)
        viejo=next(a for a in self.individuos() if a['id']==aid)
        self.assertEqual(viejo['identity_status'],'needs_review')

    def test_salida_de_cuadro_y_reaparicion_no_crean_otro_arbol(self):
        for i,c in enumerate(CAMARAS):self.importar(registro_sintetico(str(i),c,[PUNTOS[0]]))
        aid=self.individuos()[0]['id']
        vacio=registro_sintetico('vacio',(13.,-5.),[PUNTOS[0]])
        vacio['detections']=[];self.importar(vacio)
        self.importar(registro_sintetico('reaparece',(7.,-4.),[PUNTOS[0]]))
        self.assertEqual(self.cuenta()['arboles_confirmados'],1)
        self.assertEqual(self.individuos()[0]['id'],aid)

    def preparacion_split(self):
        self.importar(registro_sintetico('group',(13.,-10.),PUNTOS,grupo=True))
        self.importar(registro_sintetico('1',CAMARAS[0],PUNTOS))
        estado=self.almacen.estado('prueba')
        grupo=next(g for g in estado['groups'] if g.get('active',True))
        obs=[o for o in estado['observations'] if o['image_id']=='1']
        return {'type':'split','parent_id':grupo['id'],'reason':'Dos ejemplares comprobados en revisión',
                'children':[{'observation_ids':[o['id']],'confirmed':True,'coordinates':[-59.1404,-37.335]} for o in obs]}

    def test_split_manual_admite_coordenadas_iguales_y_es_reversible(self):
        accion=self.preparacion_split()
        antes=self.almacen.estado('prueba')
        evento=corregir(self.almacen,self.survey,self.config,accion)
        self.assertEqual(self.cuenta()['arboles_confirmados'],2)
        self.assertEqual(len(self.individuos()),2)
        self.assertEqual(self.individuos()[0]['fit']['xy'],self.individuos()[1]['fit']['xy'])
        self.almacen.deshacer('prueba',evento)
        self.assertEqual(self.almacen.estado('prueba'),antes)

    def test_merge_manual_y_reconciliacion_no_resucitan_al_duplicado(self):
        corregir(self.almacen,self.survey,self.config,self.preparacion_split())
        ids=[a['id'] for a in self.individuos()]
        evento=corregir(self.almacen,self.survey,self.config,{'type':'merge','tree_ids':ids,'reason':'Revisión demuestra duplicación'})
        reconciliar(self.almacen,self.survey,self.config)
        self.assertEqual(len(self.individuos()),1)
        self.assertEqual(self.cuenta()['arboles_confirmados'],1)
        self.almacen.deshacer('prueba',evento)
        self.assertEqual(self.cuenta()['arboles_confirmados'],2)

    def test_split_invalido_hace_rollback_completo(self):
        accion=self.preparacion_split()
        accion['children'][1]['observation_ids']=accion['children'][0]['observation_ids']
        antes=self.almacen.estado('prueba')
        eventos=len(self.almacen.eventos('prueba'))
        with self.assertRaises(ValueError):corregir(self.almacen,self.survey,self.config,accion)
        self.assertEqual(self.almacen.estado('prueba'),antes)
        self.assertEqual(len(self.almacen.eventos('prueba')),eventos)

    def test_no_deshace_sobre_cambios_posteriores(self):
        accion=self.preparacion_split()
        evento=corregir(self.almacen,self.survey,self.config,accion)
        self.importar(registro_sintetico('2',CAMARAS[1],PUNTOS))
        with self.assertRaises(ValueError):self.almacen.deshacer('prueba',evento)

    def test_caja_duplicada_no_confirma_dos_arboles(self):
        for i,c in enumerate(CAMARAS):
            r=registro_sintetico(str(i),c,[PUNTOS[0]])
            doble=copy.deepcopy(r['detections'][0]);doble['kind_verified']=False;doble['score']=.8
            r['detections'].append(doble)
            self.importar(r)
        self.assertEqual(self.cuenta()['arboles_confirmados'],1)
        self.assertEqual(self.cuenta()['duplicados_probables'],3)

    def test_orden_de_ingesta_no_cambia_conteo_ni_posicion(self):
        registros=self.escena()
        coords=sorted(a['fit']['xy'] for a in self.individuos())
        origen=MarcoLocal(*self.survey['origin'])
        geo=[origen.geografica(*p) for p in coords]
        otro=Almacen(self.raiz/'otro.sqlite');survey=otro.survey('prueba',self.config)
        try:
            for r in reversed(registros):
                otro.importar('prueba',r);reconciliar(otro,survey,self.config)
            activos=[a for a in otro.estado('prueba')['trees'] if a.get('active',True)]
            self.assertEqual(len(activos),2)
            marco=MarcoLocal(*survey['origin'])
            for p in geo:self.assertLess(min(math.dist(marco.proyectar(*p),a['fit']['xy']) for a in activos),.02)
        finally:otro.close()

    def test_exportacion_vacia_y_captura_unica_no_inventan_puntos(self):
        exportar(self.almacen,self.survey,self.config,self.raiz/'export')
        self.assertEqual(json.loads((self.raiz/'export/arboles.geojson').read_text())['features'],[])
        self.importar(registro_sintetico('1',CAMARAS[0],[PUNTOS[0]]))
        exportar(self.almacen,self.survey,self.config,self.raiz/'export')
        self.assertEqual(json.loads((self.raiz/'export/arboles.geojson').read_text())['features'],[])
        self.assertTrue((self.raiz/'export/mapa.html').exists())
        obs=json.loads((self.raiz/'export/observaciones.geojson').read_text())['features'][0]
        self.assertEqual(obs['geometry']['type'],'LineString')
        self.assertFalse(obs['properties']['ray_is_measured_distance'])

    def test_texto_de_revision_no_puede_cerrar_script_html(self):
        self.importar(registro_sintetico('1',CAMARAS[0],[PUNTOS[0]]))
        aid=self.individuos()[0]['id']
        razon='</script><script>alert(1)</script>'
        corregir(self.almacen,self.survey,self.config,{'type':'confirm','target':aid,'reason':razon})
        exportar(self.almacen,self.survey,self.config,self.raiz/'export')
        html=(self.raiz/'export/mapa.html').read_text()
        self.assertNotIn(razon,html)
        self.assertIn('\\u003c/script',html)

    @unittest.skipUnless(shutil.which('node'),'Node no disponible para comprobar el JavaScript')
    def test_mapa_renderiza_filtra_y_prepara_revision_con_dom_simulado(self):
        self.escena()
        exportar(self.almacen,self.survey,self.config,self.raiz/'export')
        html=(self.raiz/'export/mapa.html').read_text()
        datos=re.search(r'<script id="datos" type="application/json">(.*?)</script>',html,re.S).group(1)
        fuente=html.split('<script>')[1].split('</script>')[0]
        stub=r'''
class Elemento {
 constructor(tag){this.tag=tag;this.children=[];this.style={};this.value='';this.checked=true;this.textContent='';this.attrs={};}
 append(...ns){this.children.push(...ns);} replaceChildren(...ns){this.children=[...ns];}
 remove(){}
 setAttribute(k,v){this.attrs[k]=v;} addEventListener(){} setPointerCapture(){}
 getBoundingClientRect(){return {left:0,top:0,width:800,height:600};} click(){if(this.onclick)this.onclick({target:this});}
}
const elementos=new Map();
global.document={head:new Elemento('head'),createElement:t=>new Elemento(t),createElementNS:(_,t)=>new Elemento(t),getElementById:id=>{if(!elementos.has(id)){const e=new Elemento(id);if(['tipo','periodo'].includes(id))e.value='all';elementos.set(id,e);}return elementos.get(id);}};
global.alert=mensaje=>{throw Error(mensaje);};
// Los recursos remotos quedan pendientes en este DOM sin red ni temporizadores.
global.setTimeout=()=>0;global.clearTimeout=()=>{};
global.location={protocol:'http:'};
document.getElementById('datos').textContent=__JSON__;
'''.replace('__JSON__',json.dumps(datos))
        comprobar=r'''
if(!document.getElementById('plano').children.length)throw Error('Mapa vacío');
document.getElementById('tipo').value='tree';document.getElementById('tipo').onchange();
if(document.getElementById('lista').children.length!==2)throw Error('Filtro de árboles incorrecto');
document.getElementById('lista').children[0].click();
document.getElementById('motivo').value='Identidad comprobada en revisión de control';
const confirmar=document.getElementById('detalle').children.find(n=>n.textContent==='Confirmar identidad');
confirmar.click();
if(revisiones.length!==1||revisiones[0].type!=='confirm')throw Error('No se preparó la corrección');
console.log('Mapa, filtro y revisión: correctos');
'''
        script=self.raiz/'mapa-test.js';script.write_text(stub+fuente+comprobar)
        resultado=subprocess.run(['node',str(script)],capture_output=True,text=True)
        self.assertEqual(resultado.returncode,0,resultado.stderr)

    def test_cli_demo_completa_e_idempotente(self):
        script=Path(__file__).resolve().parents[1]/'mapear_arboles.py'
        comando=[sys.executable,'-B',str(script),'--demo','--output',str(self.raiz/'cli-demo')]
        for indice in range(2):
            resultado=subprocess.run(comando,capture_output=True,text=True)
            self.assertEqual(resultado.returncode,0,resultado.stderr)
            if indice:self.assertIn('Imágenes con ejecución nueva: 0',resultado.stdout)
        reporte=json.loads((self.raiz/'cli-demo/exportaciones/demo/validacion.json').read_text())
        self.assertEqual(reporte['confirmed_trees'],2)
        self.assertEqual(reporte['false_merges'],0)
        self.assertEqual(reporte['false_splits'],0)
        self.assertTrue(reporte['synthetic'])


if __name__=='__main__':unittest.main()
