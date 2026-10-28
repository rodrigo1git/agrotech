"""Protocolo HTTP del visor sin abrir sockets ni depender de la red."""

import io
from pathlib import Path
import tempfile
import unittest

from mapeo.servidor_mapa import VisorHandler


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


if __name__ == "__main__":
    unittest.main()
