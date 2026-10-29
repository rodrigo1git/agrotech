"""Servidor del visor, restringido a localhost y a la carpeta de una exportación."""

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


MAPA = Path(__file__).resolve().parents[1] / "resultados/mapeo/exportaciones/tandil2018/mapa.html"
MAPA_MANZANA = MAPA.parent.parent / "manzana_tandil/mapa.html"


class VisorHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        # Permitir que el navegador identifique el origen real de la página.
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        # Revalidar el HTML y las fotos locales al actualizar el procesamiento.
        # No afecta las peticiones ni la caché de teselas externas.
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def list_directory(self, path):
        self.send_error(403, "Abrí el archivo HTML del mapa.")
        return None

    def send_head(self):
        entrada = getattr(self.server, "entry_map", None)
        if entrada and self.path.split("?", 1)[0] in ("/", "/mapa.html"):
            self.send_response(302)
            self.send_header("Location", "/" + entrada)
            self.end_headers()
            return None
        # SimpleHTTPRequestHandler sigue enlaces simbólicos: impedir que estos
        # expongan archivos fuera de la exportación servida.
        archivo = Path(self.translate_path(self.path)).resolve()
        if not archivo.is_relative_to(Path(self.directory).resolve()):
            self.send_error(403, "Ruta fuera de la exportación.")
            return None
        return super().send_head()


def crear_servidor(mapa, puerto=8765):
    mapa = Path(mapa).resolve()
    if not mapa.is_file():
        raise FileNotFoundError(f"No existe el mapa: {mapa}")
    directorio = mapa.parent.parent if mapa.parent.parent.name == "exportaciones" else mapa.parent
    handler = partial(VisorHandler, directory=str(directorio))
    servidor = ThreadingHTTPServer(("127.0.0.1", puerto), handler)
    if directorio != mapa.parent:
        from urllib.parse import quote
        servidor.entry_map = quote(str(mapa.relative_to(directorio)), safe="/")
    return servidor


def main():
    parser = argparse.ArgumentParser(description="Mostrar el mapa por HTTP local para enviar un Referer válido a OpenStreetMap.")
    parser.add_argument("--mapa", type=Path, help="HTML a abrir; por defecto la manzana si ya fue generada.")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    mapa = args.mapa or (MAPA_MANZANA if MAPA_MANZANA.is_file() else MAPA)
    try:
        servidor = crear_servidor(mapa, args.port)
    except OSError as exc:
        parser.exit(1, f"No se pudo iniciar el visor: {exc}\n")
    from urllib.parse import quote
    entrada = getattr(servidor, "entry_map", quote(mapa.name))
    print(f"Abrí http://127.0.0.1:{servidor.server_port}/{entrada}", flush=True)
    print("Ctrl+C para detener. Las calles requieren conexión a Internet.", flush=True)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()


if __name__ == "__main__":
    main()
