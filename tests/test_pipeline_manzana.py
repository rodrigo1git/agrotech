"""Regresión: descargar imágenes también debe producir un mapa accesible."""

import contextlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

import detectar_arboles
import descargar_manzana_tandil
import procesar_manzana_tandil as pipeline
from mapeo.visualizacion import exportar_mapa, renderizar_mapa


class PipelineManzanaTests(unittest.TestCase):
    def crear_dataset(self, raiz):
        raiz=Path(raiz);(raiz/'imagenes').mkdir(parents=True)
        registros=[]
        for i in range(3):
            iid=str(i+1);Image.new('RGB',(100,60),'green').save(raiz/'imagenes'/f'{iid}.jpg')
            registros.append({'id':iid,'file_name':f'{iid}.jpg','captured_at':1539978452606+i*1000,
                              'computed_geometry':{'type':'Point','coordinates':[-59.14+i*.0001,-37.335]},
                              'view_url':f'https://www.mapillary.com/app/?pKey={iid}'})
        (raiz/'manifest.json').write_text(json.dumps({'source':'mapillary','images':registros}))
        return raiz

    def test_descarga_sin_detecciones_muestra_todas_las_camaras_y_fotos(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp);dataset=self.crear_dataset(raiz/'dataset')
            mapa=pipeline.publicar(dataset,raiz/'resultados',previa=True)
            datos=json.loads(mapa.with_name('mapa_datos.json').read_text())
            self.assertEqual(len(datos['cameras']),3)
            self.assertEqual(datos['trees'],[])
            self.assertEqual(datos['pipeline']['images_processed'],0)
            self.assertEqual(datos['pipeline']['images_total'],3)
            self.assertEqual(datos['pipeline']['stage'],'detecting')
            for f in datos['cameras']:
                self.assertTrue((mapa.parent/f['properties']['photo']['url']).is_file())
                self.assertTrue((mapa.parent/f['properties']['photo']['full_url']).is_file())

    def test_foto_grande_conserva_resolucion_y_se_recupera_si_falta(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp);dataset=self.crear_dataset(raiz/'dataset');destino=raiz/'vista'
            Image.new('RGB',(1600,1000),'green').save(dataset/'imagenes/1.jpg')
            camaras,_=pipeline.catalogo_camaras(dataset,destino)
            foto=camaras[0]['properties']['photo'];grande=destino/foto['full_url']
            with Image.open(grande) as imagen:self.assertEqual(imagen.size,(1600,1000))
            with Image.open(destino/foto['url']) as imagen:self.assertEqual(imagen.size,(800,500))
            fecha=grande.stat().st_mtime_ns
            pipeline.catalogo_camaras(dataset,destino)
            self.assertEqual(grande.stat().st_mtime_ns,fecha)
            grande.unlink();pipeline.catalogo_camaras(dataset,destino)
            self.assertTrue(grande.is_file())

    def test_publicar_agrega_orientacion_sin_perder_el_giro_del_visor(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp);dataset=self.crear_dataset(raiz/'dataset')
            manifest=json.loads((dataset/'manifest.json').read_text())
            for m in manifest['images']:m['computed_compass_angle']=0;m['compass_angle']=90
            (dataset/'manifest.json').write_text(json.dumps(manifest))
            mapa=pipeline.publicar(dataset,raiz/'output',previa=True)
            datos=json.loads(mapa.with_name('mapa_datos.json').read_text())
            self.assertTrue(all(c['properties']['camera_view']['bearing_deg']==0 for c in datos['cameras']))
            datos['map_calibration']={'rotation_deg':20}
            for c in datos['cameras']:del c['properties']['camera_view']
            mapa.with_name('mapa_datos.json').write_text(json.dumps(datos))
            pipeline.publicar(dataset,raiz/'output',previa=True)
            datos=json.loads(mapa.with_name('mapa_datos.json').read_text())
            self.assertTrue(all(c['properties']['camera_view']['bearing_deg']==20 for c in datos['cameras']))

    def test_selector_conserva_calibracion_del_mapa_anterior(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp);dataset=self.crear_dataset(raiz/'dataset');exportaciones=raiz/'output/exportaciones'
            viejo=exportaciones/'tandil2018';viejo.mkdir(parents=True)
            datos={'survey':{'id':'tandil2018','origin':[-59.14,-37.335]},'counts':{},'trees':[],
                   'cameras':[{'id':'1','geometry':{'type':'Point','coordinates':[-59.14,-37.335]},'properties':{'kind':'camera','xy':[0,0]}}],
                   'observations':[],'groups':[]}
            exportar_mapa(datos,viejo)
            (viejo/'mapa.html').write_text(renderizar_mapa(datos,desplazamiento_m=23,rotacion_grados=4.5))
            original=(viejo/'mapa_datos.json').read_bytes()
            pipeline.publicar(dataset,raiz/'output',previa=True)
            html=(viejo/'mapa.html').read_text();vista=json.loads(re.search(r'<script id="datos" type="application/json">(.*?)</script>',html,re.S).group(1))
            self.assertEqual(vista['map_calibration']['offset_east_m'],23)
            self.assertEqual(vista['map_calibration']['rotation_deg'],4.5)
            self.assertEqual({m['id'] for m in vista['related_maps']},{'tandil2018','manzana_tandil'})
            self.assertEqual((viejo/'mapa_datos.json').read_bytes(),original)

    def test_parcial_incorpora_resultados_disponibles_y_conserva_todas_las_camaras(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp);dataset=self.crear_dataset(raiz/'dataset')
            manifest=json.loads((dataset/'manifest.json').read_text());meta=manifest['images'][0]
            (dataset/'detecciones').mkdir()
            resultado={'width':100,'height':60,'prompt':'tree.','model':'prueba','revision':'prueba',
                       'mapillary':meta,'detections':[{'score':.8,'label':'tree','bbox_xyxy':[10,5,30,50]}]}
            (dataset/'detecciones/1.jpg.json').write_text(json.dumps(resultado))
            Image.new('RGB',(100,60),'green').save(dataset/'detecciones/1.jpg.png')
            with contextlib.redirect_stdout(io.StringIO()):
                metricas=pipeline.construir_inventario(dataset,raiz/'output',parcial=True)
            self.assertEqual(metricas['observaciones'],1)
            mapa=pipeline.publicar(dataset,raiz/'output')
            d=json.loads(mapa.with_name('mapa_datos.json').read_text())
            self.assertEqual(len(d['cameras']),3)
            self.assertEqual(d['pipeline']['stage'],'detecting')
            self.assertEqual(d['pipeline']['images_processed'],1)
            self.assertTrue(d['cameras'][0]['properties']['photo']['annotated'])
            self.assertEqual(d['cameras'][0]['properties']['photo']['detections'],1)

    def test_miniatura_se_actualiza_al_aparecer_anotacion_aunque_su_fecha_sea_anterior(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp);dataset=self.crear_dataset(raiz/'dataset');destino=raiz/'vista'
            pipeline.catalogo_camaras(dataset,destino)
            (dataset/'detecciones').mkdir()
            Image.new('RGB',(100,60),'red').save(dataset/'detecciones/1.jpg.png')
            (dataset/'detecciones/1.jpg.json').write_text(json.dumps({'mapillary':{'id':'1'},'detections':[]}))
            os.utime(dataset/'detecciones/1.jpg.png',(1,1))
            camaras,_=pipeline.catalogo_camaras(dataset,destino)
            self.assertTrue(camaras[0]['properties']['photo']['annotated'])
            with Image.open(destino/'capturas/1.jpg') as foto:
                self.assertGreater(foto.getpixel((50,30))[0],200)

    def test_seguimiento_configurable_persistente_y_desactivable(self):
        from mapeo.almacen import Almacen
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp);dataset=self.crear_dataset(raiz/'dataset')
            metadata=json.loads((dataset/'manifest.json').read_text())['images'][0]
            (dataset/'detecciones').mkdir()
            registro={'width':100,'height':60,'prompt':'tree.','model':'prueba','revision':'prueba',
                      'mapillary':metadata,'detections':[{'score':.8,'label':'tree','bbox_xyxy':[10,5,30,50]}]}
            (dataset/'detecciones/1.jpg.json').write_text(json.dumps(registro))
            config=raiz/'ajustes.json';config.write_text(json.dumps({'tracking_min_score':.9}))
            output=raiz/'output'
            with contextlib.redirect_stdout(io.StringIO()):
                pipeline.construir_inventario(dataset,output,parcial=True,seguimiento=True,config_path=config)
                pipeline.construir_inventario(dataset,output,parcial=True)
            almacen=Almacen(output/'inventario.sqlite')
            guardada=almacen.survey(pipeline.RELEVAMIENTO,{})['config']
            almacen.close()
            self.assertTrue(guardada['allow_visual_tracking'])
            self.assertEqual(guardada['tracking_min_score'],.9)
            with contextlib.redirect_stdout(io.StringIO()):
                pipeline.construir_inventario(dataset,output,parcial=True,seguimiento=False)
            destino=output/'exportaciones'/pipeline.RELEVAMIENTO
            self.assertFalse(json.loads((destino/'seguimiento_visual.json').read_text())['enabled'])
            self.assertEqual(json.loads((destino/'estadisticas.json').read_text())['observaciones'],1)

    def test_cache_dino_rechaza_cambios_de_imagen_o_configuracion(self):
        with tempfile.TemporaryDirectory() as tmp:
            destino=Path(tmp)/'1.jpg';config={'model':'dino','prompt':'tree.','image_sha256':'abc','threshold':.35}
            destino.with_name('1.jpg.png').write_bytes(b'png')
            destino.with_name('1.jpg.json').write_text(json.dumps({**config,'width':100,'height':60,'detections':[],'mapillary':{'id':'1'}}))
            self.assertIsNotNone(detectar_arboles.resultado_reutilizable(destino,config,100,60,{'id':'1'}))
            self.assertIsNone(detectar_arboles.resultado_reutilizable(destino,{**config,'image_sha256':'otro'},100,60,{'id':'1'}))
            self.assertIsNone(detectar_arboles.resultado_reutilizable(destino,{**config,'threshold':.5},100,60,{'id':'1'}))
            self.assertIsNone(detectar_arboles.resultado_reutilizable(destino,config,100,60,{'id':'2'}))

    def test_descargador_conecta_con_pipeline_y_download_only_con_previa(self):
        for solo_descarga in [False,True]:
            with self.subTest(solo_descarga=solo_descarga),tempfile.TemporaryDirectory() as tmp:
                args=['descargar_manzana_tandil.py','--output',tmp]+(['--download-only'] if solo_descarga else [])
                zona={'properties':{'area_m2':10000}}
                with patch.object(sys,'argv',args),patch.object(descargar_manzana_tandil,'consultar_calles',return_value={}),patch.object(descargar_manzana_tandil,'resolver_manzana',return_value=zona),patch.object(descargar_manzana_tandil,'ClienteMapillary'),patch.object(descargar_manzana_tandil,'descargar',return_value=0),patch.object(descargar_manzana_tandil.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as ejecutar,contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(descargar_manzana_tandil.main(),0)
                comando=ejecutar.call_args.args[0]
                self.assertTrue(comando[2].endswith('procesar_manzana_tandil.py'))
                self.assertEqual('--preview-only' in comando,solo_descarga)


if __name__=='__main__':unittest.main()
