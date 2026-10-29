"""Protocolo HTTP del visor sin abrir sockets ni depender de la red."""

import io
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from mapeo.servidor_mapa import VisorHandler, crear_servidor


class Peticion:
    def __init__(self, ruta):
        self.entrada = io.BytesIO(f"GET {ruta} HTTP/1.0\r\n\r\n".encode())
        self.salida = bytearray()

    def makefile(self, *args):
        return self.entrada

    def sendall(self, contenido):
        self.salida.extend(contenido)


class HandlerSilencioso(VisorHandler):
    def log_message(self, *args):
        pass


class ServidorTests(unittest.TestCase):
    def solicitar(self, carpeta, ruta):
        peticion = Peticion(ruta)
        HandlerSilencioso(peticion, ("127.0.0.1", 1234), object(), directory=str(carpeta))
        return bytes(peticion.salida)

    def test_html_y_evidencia_se_sirven_con_politica_referrer(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            (raiz / "mapa.html").write_text("<html>Mapa</html>")
            (raiz / "evidencia").mkdir()
            (raiz / "evidencia/foto.jpg").write_bytes(b"imagen")
            respuesta = self.solicitar(raiz, "/mapa.html")
            self.assertIn(b"200 OK", respuesta)
            self.assertIn(b"Referrer-Policy: strict-origin-when-cross-origin", respuesta)
            self.assertIn(b"Cache-Control: no-cache", respuesta)
            self.assertTrue(respuesta.endswith(b"<html>Mapa</html>"))
            self.assertTrue(self.solicitar(raiz, "/evidencia/foto.jpg").endswith(b"imagen"))

    def test_no_publica_listados_ni_archivos_fuera_de_exportacion(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            exportacion = raiz / "exportacion"
            exportacion.mkdir()
            (raiz / "secreto").write_text("privado")
            (exportacion / "enlace").symlink_to(raiz / "secreto")
            for ruta in ["/", "/enlace", "/../secreto", "/%2e%2e/secreto"]:
                respuesta = self.solicitar(exportacion, ruta)
                self.assertNotIn(b"200 OK", respuesta)
                self.assertNotIn(b"privado", respuesta)

    def test_entrada_redirige_al_relevamiento_y_sirve_sus_fotografias(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp);carpeta=raiz/'manzana_tandil';carpeta.mkdir()
            (carpeta/'mapa.html').write_text('Manzana')
            (carpeta/'capturas').mkdir();(carpeta/'capturas/1.jpg').write_bytes(b'foto')
            peticion=Peticion('/mapa.html')
            HandlerSilencioso(peticion,('127.0.0.1',1234),SimpleNamespace(entry_map='manzana_tandil/mapa.html'),directory=str(raiz))
            self.assertIn(b'302 Found',peticion.salida)
            self.assertIn(b'Location: /manzana_tandil/mapa.html',peticion.salida)
            self.assertTrue(self.solicitar(raiz,'/manzana_tandil/mapa.html').endswith(b'Manzana'))
            self.assertTrue(self.solicitar(raiz,'/manzana_tandil/capturas/1.jpg').endswith(b'foto'))

    def test_servidor_expone_solo_exportaciones_y_no_el_proyecto(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp)/'exportaciones';carpeta=raiz/'manzana_tandil';carpeta.mkdir(parents=True)
            mapa=carpeta/'mapa.html';mapa.write_text('Manzana')
            with patch('mapeo.servidor_mapa.ThreadingHTTPServer',return_value=SimpleNamespace()) as crear:
                servidor=crear_servidor(mapa)
            self.assertEqual(crear.call_args.args[0],('127.0.0.1',8765))
            self.assertEqual(crear.call_args.args[1].keywords['directory'],str(raiz))
            self.assertEqual(servidor.entry_map,'manzana_tandil/mapa.html')


if __name__ == "__main__":
    unittest.main()
