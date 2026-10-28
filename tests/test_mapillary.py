"""Pruebas de integración sin consultas a Mapillary ni descarga de modelos."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import detectar_arboles as detector
import mapillary_arboles as mapillary


def respuesta(datos):
    return io.BytesIO(json.dumps(datos).encode())


def miniatura():
    datos = io.BytesIO()
    Image.new("RGB", (100, 60), "white").save(datos, format="JPEG")
    return datos.getvalue()


def captura(identificador="123"):
    return {
        "id": identificador,
        "geometry": {"type": "Point", "coordinates": [-58.38, -34.60]},
        "computed_geometry": {"type": "Point", "coordinates": [-58.381, -34.601]},
        "computed_compass_angle": 90,
        "camera_type": "perspective",
        "captured_at": 1700000000000,
        "sequence": "secuencia1",
        "width": 4000, "height": 2400,
        "thumb_2048_url": "https://imagenes.example/miniatura.jpg?firma=temporal",
        "creator": {"username": "autor"},
    }


class Valores:
    """Interfaz mínima del resultado numérico, sin cargar PyTorch."""
    def __init__(self, valores):
        self.valores = valores

    def detach(self):
        return self

    def cpu(self):
        return self

    def tolist(self):
        return self.valores


class PruebasAPI(unittest.TestCase):
    def test_token_local_y_prioridad_de_variable_de_entorno(self):
        with tempfile.TemporaryDirectory() as carpeta:
            archivo = Path(carpeta) / '.env.mapillary'
            archivo.write_text('MAPILLARY_TOKEN="token-local"\n', encoding='utf-8')
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(mapillary.obtener_token(archivo), 'token-local')
            with patch.dict(os.environ, {'MAPILLARY_TOKEN': 'token-entorno'}):
                self.assertEqual(mapillary.obtener_token(archivo), 'token-entorno')

    def setUp(self):
        self.cliente = mapillary.ClienteMapillary("token-de-prueba")
        self.cliente.opener = Mock()

    def test_paginacion_ids_repetidos_y_limite(self):
        self.cliente.opener.open.side_effect = [
            respuesta({"data": [captura("1")], "paging": {
                "next": "https://graph.mapillary.com/images?after=abc&access_token=credencial"
            }}),
            respuesta({"data": [captura("1"), captura("2"), captura("3")]}),
        ]
        datos = list(self.cliente.seleccionar(bbox=[-59, -35, -58, -34], limite=2))
        self.assertEqual([d["id"] for d in datos], ["1", "2"])
        self.assertEqual(self.cliente.opener.open.call_count, 2)
        for llamada in self.cliente.opener.open.call_args_list:
            peticion = llamada.args[0]
            self.assertNotIn("access_token", peticion.full_url)
            self.assertEqual(peticion.get_header("Authorization"), "OAuth token-de-prueba")

    def test_paginacion_fuera_de_mapillary_rechazada(self):
        self.cliente.opener.open.return_value = respuesta({
            "data": [], "paging": {"next": "https://otro.example/robar-token"},
        })
        with self.assertRaises(mapillary.ErrorMapillary):
            list(self.cliente.seleccionar(bbox=[-59, -35, -58, -34], limite=0))
        self.assertEqual(self.cliente.opener.open.call_count, 1)

    def test_reintenta_429_y_error_de_autenticacion_no_expone_token(self):
        self.cliente.opener.open.side_effect = [
            HTTPError(mapillary.API, 429, "limit", {}, None),
            respuesta({"id": "1"}),
        ]
        with patch.object(mapillary.time, "sleep") as pausa:
            self.assertEqual(self.cliente.json(mapillary.API + "/1"), {"id": "1"})
            pausa.assert_called_once_with(1)
        self.cliente.opener.open.side_effect = HTTPError(
            mapillary.API, 401, "token-de-prueba", {}, None,
        )
        with self.assertRaises(mapillary.ErrorMapillary) as error:
            self.cliente.json(mapillary.API + "/1")
        self.assertIn("HTTP 401", str(error.exception))
        self.assertNotIn("token-de-prueba", str(error.exception))

    def test_secuencia_consulta_los_metadatos_de_cada_imagen(self):
        self.cliente.opener.open.side_effect = [
            respuesta({"data": [{"id": "1"}, {"id": "2"}]}),
            respuesta(captura("1")),
        ]
        datos = list(self.cliente.seleccionar(secuencia="secuencia1", limite=1))
        self.assertEqual(datos[0]["computed_compass_angle"], 90)
        self.assertEqual(self.cliente.opener.open.call_count, 2)

    def test_descarga_sin_token_y_reutiliza_archivo_valido(self):
        self.cliente.opener.open.return_value = io.BytesIO(miniatura())
        with tempfile.TemporaryDirectory() as carpeta:
            destino = Path(carpeta) / "123.jpg"
            mapillary.descargar_imagen(self.cliente, captura(), destino)
            peticion = self.cliente.opener.open.call_args.args[0]
            self.assertIsNone(peticion.get_header("Authorization"))
            with Image.open(destino) as imagen:
                self.assertEqual(imagen.size, (100, 60))
            mapillary.descargar_imagen(self.cliente, captura(), destino)
            self.assertEqual(self.cliente.opener.open.call_count, 1)

    def test_redireccion_a_cdn_no_reenvia_credencial(self):
        peticion = Request(mapillary.API + "/123", headers={"Authorization": "OAuth secreto"})
        redirigida = mapillary.RedireccionSegura().redirect_request(
            peticion, None, 302, "found", {}, "https://cdn.example/imagen",
        )
        self.assertIsNone(redirigida.get_header("Authorization"))


class PruebasIntegracion(unittest.TestCase):
    def test_map_ejecuta_inventario_solo_si_dino_completa(self):
        for codigo, llamadas in ((0,2),(1,1)):
            with self.subTest(codigo=codigo), tempfile.TemporaryDirectory() as carpeta:
                opener=Mock()
                opener.open.side_effect=[respuesta(captura()),io.BytesIO(miniatura())]
                argumentos=['mapillary_arboles.py','--image-id','123','--output',carpeta,'--map','--relevamiento','cuadra']
                with (patch.object(sys,'argv',argumentos),patch.dict(os.environ,{'MAPILLARY_TOKEN':'token-de-prueba'}),
                      patch.object(mapillary,'build_opener',return_value=opener),
                      patch.object(mapillary.subprocess,'run',return_value=SimpleNamespace(returncode=codigo)) as ejecutar,
                      contextlib.redirect_stdout(io.StringIO())):
                    self.assertEqual(mapillary.main(),codigo)
                self.assertEqual(ejecutar.call_count,llamadas)
                if codigo==0:
                    comando=ejecutar.call_args.args[0]
                    self.assertTrue(comando[1].endswith('mapear_arboles.py'))
                    self.assertEqual(comando[comando.index('--relevamiento')+1],'cuadra')

    def test_flujo_detector_exporta_observaciones_sin_posiciones_inventadas(self):
        class Entradas(dict):
            input_ids = [1]

            def to(self, dispositivo):
                return self

        procesador = Mock(return_value=Entradas())
        procesador.post_process_grounded_object_detection.return_value = [{
            "boxes": Valores([[10, 5, 90, 55]]),
            "scores": Valores([0.7]), "text_labels": ["tree"],
        }]
        modelo = Mock()
        modelo.to.return_value = modelo
        modelo.eval.return_value = modelo
        librerias = {
            "torch": SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False), inference_mode=contextlib.nullcontext),
            "transformers": SimpleNamespace(
                AutoProcessor=SimpleNamespace(from_pretrained=Mock(return_value=procesador)),
                AutoModelForZeroShotObjectDetection=SimpleNamespace(from_pretrained=Mock(return_value=modelo)),
            ),
        }
        with tempfile.TemporaryDirectory() as carpeta:
            raiz = Path(carpeta)
            imagenes = raiz / "imagenes"
            imagenes.mkdir()
            (imagenes / "123.jpg").write_bytes(miniatura())
            manifest = raiz / "manifest.json"
            mapillary.escribir_json(manifest, {"source": "mapillary", "images": [mapillary.metadatos_guardables(captura())]})
            salida = raiz / "detecciones"
            argumentos = ["detectar_arboles.py", str(imagenes), "--manifest", str(manifest), "--output", str(salida)]
            with (patch.object(sys, "argv", argumentos), patch.dict(sys.modules, librerias),
                  contextlib.redirect_stdout(io.StringIO())):
                self.assertEqual(detector.main(), 0)
            observacion = json.loads((salida / "observaciones.geojson").read_text())["features"][0]
            self.assertIsNone(observacion["geometry"])
            self.assertEqual(observacion["properties"]["mapillary_id"], "123")
            self.assertEqual(observacion["properties"]["geolocation_status"], "pending")
            self.assertEqual(json.loads((salida / "resumen.json").read_text())["processed"][0]["detections"], 1)

    def test_descarga_y_llamada_al_detector_comparten_manifest_e_interprete(self):
        opener = Mock()
        opener.open.side_effect = [respuesta(captura()), io.BytesIO(miniatura())]
        with tempfile.TemporaryDirectory() as carpeta:
            salida = Path(carpeta)
            argumentos = ["mapillary_arboles.py", "--image-id", "123", "--output", str(salida)]
            with (patch.object(sys, "argv", argumentos),
                  patch.dict(os.environ, {"MAPILLARY_TOKEN": "token-de-prueba"}),
                  patch.object(mapillary, "build_opener", return_value=opener),
                  patch.object(mapillary.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as ejecutar,
                  contextlib.redirect_stdout(io.StringIO())):
                self.assertEqual(mapillary.main(), 0)
            manifest = json.loads((salida / "manifest.json").read_text())
            registro = manifest["images"][0]
            self.assertNotIn("thumb_2048_url", registro)
            self.assertNotIn("token-de-prueba", json.dumps(manifest))
            self.assertEqual(registro["creator"]["username"], "autor")
            cargar = mapillary.cargar_manifest(salida / "manifest.json", salida / "imagenes")
            self.assertEqual(len(cargar), 1)
            comando = ejecutar.call_args.args[0]
            self.assertEqual(comando[0], sys.executable)
            self.assertEqual(comando[comando.index("--manifest") + 1], str(salida / "manifest.json"))
            camara = json.loads((salida / "camaras.geojson").read_text())["features"][0]
            self.assertEqual(camara["properties"]["kind"], "camera")
            self.assertEqual(camara["geometry"]["coordinates"], [-58.381, -34.601])

    def test_manifest_selecciona_solo_las_imagenes_actuales(self):
        with tempfile.TemporaryDirectory() as carpeta:
            raiz = Path(carpeta)
            imagenes = raiz / "imagenes"
            imagenes.mkdir()
            (imagenes / "123.jpg").write_bytes(miniatura())
            (imagenes / "456.jpg").write_bytes(miniatura())
            manifest = raiz / "manifest.json"
            mapillary.escribir_json(manifest, {"source": "mapillary", "images": [mapillary.metadatos_guardables(captura())]})
            argumentos = ["detectar_arboles.py", str(imagenes), "--manifest", str(manifest), "--dry-run"]
            salida = io.StringIO()
            with patch.object(sys, "argv", argumentos), contextlib.redirect_stdout(salida):
                self.assertEqual(detector.main(), 0)
            self.assertIn("123.jpg", salida.getvalue())
            self.assertNotIn("456.jpg", salida.getvalue())

    def test_manifest_no_acepta_rutas_fuera_de_entrada(self):
        with tempfile.TemporaryDirectory() as carpeta:
            raiz = Path(carpeta)
            imagenes = raiz / "imagenes"
            imagenes.mkdir()
            (raiz / "externa.jpg").write_bytes(miniatura())
            manifest = raiz / "manifest.json"
            mapillary.escribir_json(manifest, {"source": "mapillary", "images": [{"file_name": "../externa.jpg"}]})
            with self.assertRaises(ValueError):
                mapillary.cargar_manifest(manifest, imagenes)

    def test_camara_sin_datos_no_inventa_posicion(self):
        self.assertEqual(mapillary.geometria_camara({}), (None, None))
        datos = captura()
        datos["computed_geometry"]["coordinates"] = None
        geometria, origen = mapillary.geometria_camara(datos)
        self.assertEqual(origen, "geometry")
        self.assertEqual(geometria["coordinates"], [-58.38, -34.60])

    def test_prediccion_conserva_metadata_y_coordenadas_de_imagen_descargada(self):
        resultado = {"boxes": Valores([[10, 5, 90, 55]]), "scores": Valores([0.7]), "text_labels": ["tree"]}
        with tempfile.TemporaryDirectory() as carpeta:
            destino = Path(carpeta) / "123.jpg"
            metadata = mapillary.metadatos_guardables(captura())
            cantidad = detector.guardar_resultado(
                Image.new("RGB", (100, 60)), resultado, destino, destino, {}, metadata,
            )
            registro = json.loads((Path(carpeta) / "123.jpg.json").read_text())
            self.assertEqual(cantidad, 1)
            self.assertEqual(registro["width"], 100)
            self.assertEqual(registro["mapillary"]["width"], 4000)
            self.assertEqual(registro["detections"][0]["bbox_coco"], [10, 5, 80, 50])
            self.assertEqual(registro["detections"][0]["geolocation_status"], "pending")
            self.assertNotIn("geometry", registro["detections"][0])


if __name__ == "__main__":
    unittest.main()
