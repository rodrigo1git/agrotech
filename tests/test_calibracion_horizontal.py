"""Traslación coherente de todo el relevamiento sin modificar las latitudes."""

from copy import deepcopy
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from mapeo.calibracion_horizontal import desplazar_datos, metros_por_radian_longitud, metros_por_radian_latitud


def datos_prueba():
    return {"survey": {"id": "calibrar", "origin": [-59.14, -37.335]}, "counts": {"observaciones": 1},
            "trees": [{"id": "t", "geometry": {"type": "Point", "coordinates": [-59.1399, -37.3349]},
                       "properties": {"kind": "tree", "fit": {"xy": [3., 10.]},
                                      "map_position": {"xy": [3., 10.], "coordinates": [-59.1399, -37.3349], "camera_xy": [0., 0.],
                                                       "source_pixel": [10, 20], "distance_m": 10.44,
                                                       "lateral_constraint": {"raw_xy": [6., 20.], "raw_coordinates": [-59.1398, -37.3348],
                                                                              "axis": {"origin_xy": [0., 0.], "direction": [0., 1.]}}}}}],
            "cameras": [{"id": "c", "geometry": {"type": "Point", "coordinates": [-59.14, -37.335]},
                         "properties": {"kind": "camera", "image_id": "c", "xy": [0., 0.]}}],
            "observations": [{"id": "o", "geometry": {"type": "LineString", "coordinates": [[-59.14, -37.335], [-59.1399, -37.3349]]},
                              "properties": {"kind": "observation", "bbox_xyxy": [1, 2, 30, 40],
                                             "ray": {"origin_xy": [0., 0.], "direction": [.3, .9]}}}],
            "groups": [{"id": "g", "geometry": None, "properties": {"kind": "group"}}]}


class CalibracionHorizontalTests(unittest.TestCase):
    def test_camaras_arboles_y_rayos_cambian_juntos_con_latitudes_exactas(self):
        d = datos_prueba()
        original = deepcopy(d)
        r = desplazar_datos(d, 10.)
        grados = math.degrees(10. / metros_por_radian_longitud(-37.335))
        for tipo in ["trees", "cameras", "observations"]:
            for a, b in zip(d[tipo], r[tipo]):
                ca, cb = a["geometry"]["coordinates"], b["geometry"]["coordinates"]
                pares = zip(ca, cb) if a["geometry"]["type"] == "LineString" else [(ca, cb)]
                for x, y in pares:
                    self.assertEqual(y[1], x[1])
                    self.assertAlmostEqual(y[0] - x[0], grados, places=12)
        self.assertEqual(r["cameras"][0]["properties"]["xy"], [10., 0.])
        p = r["trees"][0]["properties"]["map_position"]
        self.assertEqual(p["xy"], [13., 10.])
        self.assertEqual(p["lateral_constraint"]["raw_xy"], [16., 20.])
        self.assertEqual(p["lateral_constraint"]["axis"]["origin_xy"], [10., 0.])
        self.assertEqual(p["source_pixel"], [10, 20])
        self.assertEqual(p["distance_m"], 10.44)
        self.assertEqual(r["observations"][0]["properties"]["bbox_xyxy"], [1, 2, 30, 40])
        self.assertEqual(r["observations"][0]["properties"]["ray"]["direction"], [.3, .9])
        self.assertIsNone(r["groups"][0]["geometry"])
        self.assertEqual(r["counts"], d["counts"])
        self.assertEqual(d, original)

    def test_offset_absoluto_no_acumula_y_se_puede_restablecer(self):
        d = datos_prueba()
        a = desplazar_datos(d, 10)
        self.assertEqual(desplazar_datos(a, 10), a)
        b = desplazar_datos(a, -5)
        self.assertEqual(b["cameras"][0]["properties"]["xy"], [-5., 0.])
        cero = desplazar_datos(b, 0)
        def redondear(v):
            if isinstance(v, float):return round(v, 12)
            if isinstance(v, dict):return {k:redondear(x) for k,x in v.items()}
            if isinstance(v, list):return [redondear(x) for x in v]
            return v
        for k in ["trees", "cameras", "observations"]:
            self.assertEqual(redondear(cero[k][0]["properties"]), redondear(d[k][0]["properties"]))
            pares = zip(cero[k][0]["geometry"]["coordinates"], d[k][0]["geometry"]["coordinates"])
            for x, y in pares:
                if isinstance(x, list):
                    self.assertAlmostEqual(x[0], y[0], places=12)
                    self.assertEqual(x[1], y[1])
                else:self.assertAlmostEqual(x, y, places=12)

    def test_ajuste_en_dos_ejes_mantiene_geometrias_y_referencias_coherentes(self):
        d = datos_prueba()
        r = desplazar_datos(d, 23, -4)
        latitud = d["cameras"][0]["geometry"]["coordinates"][1]
        self.assertEqual(r["cameras"][0]["properties"]["xy"], [23., -4.])
        self.assertAlmostEqual(r["cameras"][0]["geometry"]["coordinates"][1]-latitud,
                               math.degrees(-4/metros_por_radian_latitud(latitud)), places=12)
        self.assertEqual(r["trees"][0]["properties"]["fit"]["xy"], [26., 6.])
        self.assertEqual(r["observations"][0]["properties"]["ray"]["origin_xy"], [23., -4.])
        self.assertEqual(r["trees"][0]["properties"]["map_position"]["source_pixel"], [10, 20])
        self.assertEqual(desplazar_datos(r,23,-4),r)
        norte=desplazar_datos(r,23,2)
        self.assertEqual(norte["cameras"][0]["properties"]["xy"], [23.,2.])
        cero=desplazar_datos(norte,0,0)
        self.assertEqual(cero["cameras"][0]["properties"]["xy"], [0.,0.])
        self.assertEqual(d["cameras"][0]["properties"]["xy"], [0.,0.])

    def escena_giro(self):
        d=datos_prueba();lon,lat=d['survey']['origin']
        escala_e=metros_por_radian_longitud(lat)*math.pi/180
        escala_n=metros_por_radian_latitud(lat)*math.pi/180
        d['cameras'].append({'id':'d','geometry':{'type':'Point','coordinates':[lon+10/escala_e,lat]},
                             'properties':{'kind':'camera','xy':[10.,0.]}})
        d['observations'][0]['geometry']['coordinates']=[[lon,lat],[lon,lat+10/escala_n]]
        d['observations'][0]['properties']['ray'].update(direction=[0.,1.],bearing_deg=0.)
        return d

    def test_giro_horario_conserva_pivote_distancias_y_gira_rayos(self):
        d=self.escena_giro();antes=deepcopy(d)
        r=desplazar_datos(d,23,-4,90,'c')
        a,b=r['cameras']
        self.assertEqual(a['properties']['xy'],[23.,-4.])
        self.assertAlmostEqual(b['properties']['xy'][0],23.)
        self.assertAlmostEqual(b['properties']['xy'][1],-14.)
        self.assertAlmostEqual(math.dist(a['properties']['xy'],b['properties']['xy']),10.)
        self.assertAlmostEqual(r['trees'][0]['properties']['fit']['xy'][0],33.)
        self.assertAlmostEqual(r['trees'][0]['properties']['fit']['xy'][1],-7.)
        ray=r['observations'][0]['properties']['ray']
        self.assertAlmostEqual(ray['direction'][0],1.)
        self.assertAlmostEqual(ray['direction'][1],0.)
        self.assertEqual(ray['bearing_deg'],90.)
        linea=r['observations'][0]['geometry']['coordinates']
        self.assertGreater(linea[1][0],linea[0][0])
        self.assertAlmostEqual(linea[1][1],linea[0][1],places=12)
        sin_giro=desplazar_datos(d,23,-4,0,'c')
        self.assertEqual(a['geometry'],sin_giro['cameras'][0]['geometry'])
        self.assertEqual(r['counts'],d['counts'])
        self.assertEqual(d,antes)
        self.assertEqual(desplazar_datos(r,23,-4,90,'c'),r)
        cero=desplazar_datos(r,0,0,0,'c')
        for original,actual in zip(d['cameras'],cero['cameras']):
            for x,y in zip(original['properties']['xy'],actual['properties']['xy']):self.assertAlmostEqual(x,y,places=10)

    def test_rechaza_rotacion_y_pivote_invalidos(self):
        for angulo in [float('nan'),float('inf'),True]:
            with self.assertRaises(ValueError):desplazar_datos(self.escena_giro(),0,0,angulo)
        with self.assertRaises(ValueError):desplazar_datos(self.escena_giro(),0,0,5,'inexistente')

    @unittest.skipUnless(shutil.which('node'),'Node no disponible')
    def test_giro_python_javascript_y_cambio_de_pivote_sin_salto(self):
        d=self.escena_giro()
        modulo=Path(__file__).resolve().parents[1]/'mapeo/visores/calibracion_horizontal.js'
        fuente=modulo.read_text()+"\nconst d="+json.dumps(d)+";const a=CalibracionMapa.aplicar(d,23,-4,30,'c');const b=CalibracionMapa.cambiarPivote(a,'d');process.stdout.write(JSON.stringify({a,b}));"
        resultado=subprocess.run(['node','-e',fuente],capture_output=True,text=True)
        self.assertEqual(resultado.returncode,0,resultado.stderr)
        salida=json.loads(resultado.stdout)
        py=desplazar_datos(d,23,-4,30,'c')
        for x,y in zip(py['cameras'],salida['a']['cameras']):
            for a,b in zip(x['geometry']['coordinates'],y['geometry']['coordinates']):self.assertAlmostEqual(a,b,places=12)
        for a,b in zip(salida['a']['cameras']+salida['a']['trees'],salida['b']['cameras']+salida['b']['trees']):
            for x,y in zip(a['geometry']['coordinates'],b['geometry']['coordinates']):self.assertAlmostEqual(x,y,places=12)
        self.assertEqual(salida['b']['map_calibration']['pivot_camera_id'],'d')

    def test_cli_importa_giro_version_tres(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'mapa_datos.json';p.write_text(json.dumps(self.escena_giro()))
            ajuste=p.with_name('calibracion_mapa.json')
            ajuste.write_text(json.dumps({'schema_version':3,'survey_id':'calibrar','offset_east_m':23,'offset_north_m':-2,'rotation_deg':8,'pivot_camera_id':'d'}))
            r=subprocess.run([sys.executable,'-B','-m','mapeo.visualizacion','--datos',str(p),'--calibracion',str(ajuste)],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)
            vista=json.loads(re.search(r'<script id="datos" type="application/json">(.*?)</script>',p.with_name('mapa.html').read_text(),re.S).group(1))
            self.assertEqual(vista['map_calibration']['rotation_deg'],8)
            self.assertEqual(vista['map_calibration']['pivot_camera_id'],'d')

    def test_rechaza_valores_invalidos_y_no_necesita_coordenadas_para_cero(self):
        for valor in [float("nan"), float("inf"), True, "10"]:
            with self.assertRaises(ValueError):
                desplazar_datos(datos_prueba(), valor)
        vacio = {"survey": {"id": "vacio"}}
        self.assertEqual(desplazar_datos(vacio, 0), vacio)
        with self.assertRaises(ValueError):
            desplazar_datos(vacio, 10)

    @unittest.skipUnless(shutil.which("node"), "Node no disponible")
    def test_python_y_javascript_producen_el_mismo_ajuste(self):
        modulo = Path(__file__).resolve().parents[1] / "mapeo/visores/calibracion_horizontal.js"
        fuente = modulo.read_text() + "\nprocess.stdout.write(JSON.stringify(CalibracionHorizontal.aplicar(" + json.dumps(datos_prueba()) + ",-7.5)));"
        r = subprocess.run(["node", "-e", fuente], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        js = json.loads(r.stdout)
        py = desplazar_datos(datos_prueba(), -7.5)
        self.assertEqual(js["trees"], py["trees"])
        self.assertEqual(js["cameras"], py["cameras"])
        self.assertAlmostEqual(js["horizontal_calibration"]["longitude_offset_deg"], py["horizontal_calibration"]["longitude_offset_deg"], places=14)

    @unittest.skipUnless(shutil.which("node"), "Node no disponible")
    def test_python_y_javascript_coinciden_con_desplazamiento_norte(self):
        modulo=Path(__file__).resolve().parents[1]/"mapeo/visores/calibracion_horizontal.js"
        fuente=modulo.read_text()+"\nprocess.stdout.write(JSON.stringify(CalibracionMapa.aplicar("+json.dumps(datos_prueba())+",23,-3.5)));"
        r=subprocess.run(["node","-e",fuente],capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr)
        js=json.loads(r.stdout);py=desplazar_datos(datos_prueba(),23,-3.5)
        for k in ["trees","cameras","observations"]:
            self.assertEqual(js[k],py[k])
        self.assertAlmostEqual(js["map_calibration"]["latitude_offset_deg"],py["map_calibration"]["latitude_offset_deg"],places=14)

    def test_cli_norte_conserva_correccion_este_y_acepta_archivos_version_dos(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'mapa_datos.json'
            p.write_text(json.dumps(desplazar_datos(datos_prueba(),23)))
            original=p.read_bytes()
            comando=[sys.executable,'-B','-m','mapeo.visualizacion','--datos',str(p)]
            r=subprocess.run(comando+['--offset-north-m','-2'],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)
            d=json.loads(re.search(r'<script id="datos" type="application/json">(.*?)</script>',p.with_name('mapa.html').read_text(),re.S).group(1))
            self.assertEqual(d['map_calibration']['offset_east_m'],23)
            self.assertEqual(d['map_calibration']['offset_north_m'],-2)
            ajuste=p.with_name('calibracion_mapa.json')
            ajuste.write_text(json.dumps({'schema_version':2,'survey_id':'calibrar','offset_east_m':23,'offset_north_m':4}))
            r=subprocess.run(comando+['--calibracion',str(ajuste)],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)
            d=json.loads(re.search(r'<script id="datos" type="application/json">(.*?)</script>',p.with_name('mapa.html').read_text(),re.S).group(1))
            self.assertEqual(d['map_calibration']['offset_north_m'],4)
            self.assertEqual(d['cameras'][0]['properties']['xy'],[23.,4.])
            self.assertEqual(p.read_bytes(),original)

    def test_cli_aplica_calibracion_guardada_sin_cambiar_json_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            datos = raiz / "mapa_datos.json"
            datos.write_text(json.dumps(datos_prueba()))
            original = datos.read_bytes()
            ajuste = raiz / "calibracion_horizontal.json"
            ajuste.write_text(json.dumps({"survey_id": "calibrar", "offset_east_m": 12.}))
            cmd = [sys.executable, "-B", "-m", "mapeo.visualizacion", "--datos", str(datos), "--calibracion", str(ajuste)]
            r = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            html = (raiz / "mapa.html").read_text()
            d = json.loads(re.search(r'<script id="datos" type="application/json">(.*?)</script>', html, re.S).group(1))
            self.assertEqual(d["horizontal_calibration"]["offset_east_m"], 12.)
            self.assertEqual(d["cameras"][0]["geometry"]["coordinates"][1], -37.335)
            self.assertEqual(datos.read_bytes(), original)
            ajuste.write_text(json.dumps({"survey_id": "otro", "offset_east_m": 12.}))
            r = subprocess.run(cmd, capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)
            self.assertEqual((raiz / "mapa.html").read_text(), html)


if __name__ == "__main__":
    unittest.main()
