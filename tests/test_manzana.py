"""Selección de cuatro calles y descarga del perímetro, con datos sintéticos."""

import contextlib
import io
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image

import descargar_manzana_tandil as descarga
from mapeo.camaras import MarcoLocal
from mapeo.seleccion_manzana import (CALLES, CENTRO, bbox_consulta, resolver_manzana,
                                    seleccion_captura, consultar_calles)


def calles_sinteticas(giro=0.):
    marco = MarcoLocal(*CENTRO)
    a = math.radians(giro)
    def punto(xy):
        x,y=xy;lon,lat=marco.geografica(x*math.cos(a)-y*math.sin(a),x*math.sin(a)+y*math.cos(a))
        return {'lon':lon,'lat':lat}
    segmentos = [[[-50,0],[170,0]],[[120,-50],[120,150]],[[-50,100],[170,100]],[[0,-50],[0,150]]]
    return {'elements':[{'type':'way','id':i,'tags':{'name':n,'highway':'residential'},'geometry':[punto(p) for p in ps]}
                        for i,(n,ps) in enumerate(zip(CALLES,segmentos))]}


def imagen(identificador, punto, ano=2018):
    lon,lat=MarcoLocal(*CENTRO).geografica(*punto)
    return {'id':str(identificador),'computed_geometry':{'type':'Point','coordinates':[lon,lat]},
            'captured_at':1539978452606 if ano==2018 else 1600000000000,'sequence':'recorrido',
            'thumb_2048_url':'https://cdn.example/foto.jpg?firma=temporal-no-persistir'}


class ManzanaTests(unittest.TestCase):
    def test_resuelve_cuatro_esquinas_incluso_con_calles_inclinadas(self):
        for giro in [0.,33.,70.]:
            zona=resolver_manzana(calles_sinteticas(giro))
            self.assertAlmostEqual(zona['properties']['area_m2'],12000.,places=3)
            self.assertEqual(zona['geometry']['coordinates'][0][0],zona['geometry']['coordinates'][0][-1])
            self.assertEqual(len(zona['geometry']['coordinates'][0]),5)
            self.assertEqual(zona['properties']['edge_streets'],CALLES[1:]+CALLES[:1])

    def test_faltan_calles_o_no_se_cruzan_falla_sin_suponer_esquinas(self):
        d=calles_sinteticas();d['elements'].pop()
        with self.assertRaises(ValueError):resolver_manzana(d)
        d=calles_sinteticas();d['elements'][0]['geometry']=d['elements'][2]['geometry']
        with self.assertRaises(ValueError):resolver_manzana(d)

    def test_filtra_perimetro_y_elige_mejor_fuente_gps(self):
        zona=resolver_manzana(calles_sinteticas())
        elegida=seleccion_captura(imagen(1,[50,-20]),zona,30)
        self.assertEqual(elegida['street'],'Constitución')
        self.assertAlmostEqual(elegida['distance_to_perimeter_m'],20.,places=5)
        self.assertIsNone(seleccion_captura(imagen(2,[60,50]),zona,30))
        self.assertIsNone(seleccion_captura(imagen(3,[300,300]),zona,30))
        desplazada=imagen(4,[60,50]);desplazada['geometry']=imagen(5,[50,-20])['computed_geometry']
        self.assertEqual(seleccion_captura(desplazada,zona,30)['position_source'],'geometry')
        self.assertIsNone(seleccion_captura({'id':'sin-coordenadas'},zona,30))

    def test_bbox_incluye_el_margen_y_no_confunde_lon_con_lat(self):
        zona=resolver_manzana(calles_sinteticas());o,s,e,n=bbox_consulta(zona,30)
        for xy in [[-30,-30],[150,130]]:
            lon,lat=MarcoLocal(*CENTRO).geografica(*xy)
            self.assertLessEqual(o,lon+1e-9);self.assertLessEqual(lon,e+1e-9)
            self.assertLessEqual(s,lat+1e-9);self.assertLessEqual(lat,n+1e-9)

    def test_consulta_publica_no_contiene_autorizacion(self):
        with patch('mapeo.seleccion_manzana.urlopen',return_value=io.BytesIO(json.dumps(calles_sinteticas()).encode())) as abrir:
            consultar_calles()
        self.assertIsNone(abrir.call_args.args[0].get_header('Authorization'))

    def test_descarga_todas_las_elegidas_y_guarda_fechas_sin_urls_temporales(self):
        cliente=Mock();cliente.seleccionar.return_value=iter([imagen(1,[50,-20]),imagen(2,[50,120],2020),imagen(3,[60,50])])
        jpg=io.BytesIO();Image.new('RGB',(30,30),'green').save(jpg,format='JPEG')
        cliente.leer.return_value=jpg.getvalue()
        with tempfile.TemporaryDirectory() as tmp,contextlib.redirect_stdout(io.StringIO()):
            p=Path(tmp);zona=resolver_manzana(calles_sinteticas())
            self.assertEqual(descarga.descargar(zona,cliente,p),0)
            manifest=json.loads((p/'manifest.json').read_text())
            self.assertEqual([m['id'] for m in manifest['images']],['1','2'])
            self.assertNotIn('temporal-no-persistir',(p/'manifest.json').read_text())
            resumen=json.loads((p/'resumen_descarga.json').read_text())
            self.assertEqual(resumen['by_year'],{'2018':1,'2020':1})
            self.assertTrue(resumen['complete'])
            self.assertEqual(len(list((p/'imagenes').glob('*.jpg'))),2)
        self.assertEqual(cliente.seleccionar.call_args.kwargs['limite'],0)

    def test_limite_se_aplica_despues_del_filtro_y_no_pierde_capturas(self):
        cliente=Mock();cliente.seleccionar.return_value=iter([imagen(1,[60,50]),imagen(2,[50,-20])])
        with tempfile.TemporaryDirectory() as tmp,patch.object(descarga,'descargar_imagen'),contextlib.redirect_stdout(io.StringIO()):
            p=Path(tmp);descarga.descargar(resolver_manzana(calles_sinteticas()),cliente,p,limite=1)
            self.assertEqual(json.loads((p/'manifest.json').read_text())['images'][0]['id'],'2')
            self.assertFalse(json.loads((p/'resumen_descarga.json').read_text())['complete'])

    def test_api_falla_y_conserva_manifest_anterior(self):
        cliente=Mock();cliente.seleccionar.side_effect=descarga.ErrorMapillary('Sin conexión')
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'manifest.json').write_text('anterior')
            with self.assertRaises(descarga.ErrorMapillary):descarga.descargar(resolver_manzana(calles_sinteticas()),cliente,p)
            self.assertEqual((p/'manifest.json').read_text(),'anterior')

    def test_solo_zona_no_consulta_mapillary(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(sys,'argv',['descargar_manzana_tandil.py','--output',tmp,'--solo-zona']),patch.object(descarga,'consultar_calles',return_value=calles_sinteticas()),patch.object(descarga,'ClienteMapillary') as api,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(descarga.main(),0)
            self.assertTrue((Path(tmp)/'zona.geojson').is_file())
            api.assert_not_called()


if __name__=='__main__':unittest.main()
