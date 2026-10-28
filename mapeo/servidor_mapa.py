"""Servidor del visor, restringido a localhost y a la carpeta de una exportación."""

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


MAPA = Path(__file__).resolve().parents[1] / "resultados/mapeo/exportaciones/tandil2018/mapa.html"


class VisorHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        # Permitir que el navegador identifique el origen real de la página.
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        super().end_headers()

    def list_directory(self, path):
        self.send_error(403, "Abrí el archivo HTML del mapa.")
        return None

    def send_head(self):
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
    handler = partial(VisorHandler, directory=str(mapa.parent))
    return ThreadingHTTPServer(("127.0.0.1", puerto), handler)


def main():
    parser = argparse.ArgumentParser(description="Mostrar el mapa por HTTP local para enviar un Referer válido a OpenStreetMap.")
    parser.add_argument("--mapa", type=Path, default=MAPA, help="HTML a servir; se comparte solo su carpeta de exportación.")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    try:
        servidor = crear_servidor(args.mapa, args.port)
    except OSError as exc:
        parser.exit(1, f"No se pudo iniciar el visor: {exc}\n")
    from urllib.parse import quote
    print(f"Abrí http://127.0.0.1:{servidor.server_port}/{quote(args.mapa.name)}", flush=True)
    print("Ctrl+C para detener. Las calles requieren conexión a Internet.", flush=True)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()


if __name__ == "__main__":
    main()
