"""Descargar imágenes de Mapillary y ejecutar el detector de árboles."""

import argparse
import io
import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


API = "https://graph.mapillary.com"
CAMPOS = (
    "id", "geometry", "computed_geometry", "compass_angle",
    "computed_compass_angle", "computed_rotation", "camera_type",
    "camera_parameters", "captured_at", "sequence", "width", "height",
    "altitude", "computed_altitude", "exif_orientation", "creator", "is_pano", "thumb_2048_url",
)


class ErrorMapillary(Exception):
    pass


def obtener_token(ruta=None):
    token = os.environ.get("MAPILLARY_TOKEN", "").strip()
    if token:
        return token
    ruta = Path(ruta) if ruta is not None else Path(__file__).with_name(".env.mapillary")
    if not ruta.is_file():
        return None
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        clave, separador, valor = linea.partition("=")
        if separador and clave.strip() == "MAPILLARY_TOKEN":
            valor = valor.strip()
            if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
                valor = valor[1:-1]
            return valor
    return None


class RedireccionSegura(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        destino = urlsplit(newurl)
        if destino.scheme != "https":
            raise ErrorMapillary("Mapillary devolvió una redirección sin HTTPS.")
        nuevo = super().redirect_request(req, fp, code, msg, headers, newurl)
        if nuevo is not None and destino.netloc.lower() != "graph.mapillary.com":
            nuevo.remove_header("Authorization")
        return nuevo


def escribir_json(ruta, datos):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_name(ruta.name + ".tmp")
    temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    temporal.replace(ruta)


def url_api(url):
    partes = urlsplit(url)
    if partes.scheme != "https" or partes.netloc.lower() != "graph.mapillary.com":
        raise ErrorMapillary("La paginación no pertenece a la API de Mapillary.")
    # Algunas respuestas incluyen el token en paging.next: no lo reutilizamos.
    parametros = [(k, v) for k, v in parse_qsl(partes.query) if k != "access_token"]
    return urlunsplit((partes.scheme, partes.netloc, partes.path, urlencode(parametros), ""))


class ClienteMapillary:
    def __init__(self, token):
        if not token or not token.strip():
            raise ErrorMapillary("Configurá MAPILLARY_TOKEN en la terminal o en .env.mapillary.")
        self.token = token.strip()
        if "\n" in self.token or "\r" in self.token:
            raise ErrorMapillary("MAPILLARY_TOKEN contiene saltos de línea; revisá el valor.")
        self.opener = build_opener(RedireccionSegura())

    def leer(self, url, autenticar=False):
        if autenticar:
            url = url_api(url)
        elif urlsplit(url).scheme != "https":
            raise ErrorMapillary("La URL de la imagen debe usar HTTPS.")
        cabeceras = {"User-Agent": "agrotech-mapillary/1.0"}
        if autenticar:
            cabeceras["Authorization"] = f"OAuth {self.token}"
        for intento in range(3):
            try:
                with self.opener.open(Request(url, headers=cabeceras), timeout=30) as respuesta:
                    contenido = respuesta.read(50 * 1024 * 1024 + 1)
                if len(contenido) > 50 * 1024 * 1024:
                    raise ErrorMapillary("La respuesta supera el límite de 50 MB.")
                return contenido
            except HTTPError as error:
                if error.code in (429, 500, 502, 503, 504) and intento < 2:
                    error.close()
                    time.sleep(2 ** intento)
                    continue
                codigo = error.code
                error.close()
                detalle = " Revisá MAPILLARY_TOKEN y sus permisos." if codigo in (401, 403) else ""
                raise ErrorMapillary(f"Mapillary respondió HTTP {codigo}.{detalle}") from None
            except (URLError, TimeoutError, OSError):
                if intento < 2:
                    time.sleep(2 ** intento)
                    continue
                raise ErrorMapillary("No se pudo conectar con Mapillary o descargar la imagen.") from None

    def json(self, url):
        try:
            datos = json.loads(self.leer(url, autenticar=True))
        except (ValueError, UnicodeDecodeError):
            raise ErrorMapillary("La API devolvió una respuesta JSON inválida.") from None
        if not isinstance(datos, dict) or "error" in datos:
            raise ErrorMapillary("La API devolvió un error. Revisá el token y la selección.")
        return datos

    def paginas(self, ruta, parametros):
        url = f"{API}/{ruta}?{urlencode(parametros)}"
        visitadas = set()
        while url:
            url = url_api(url)
            if url in visitadas:
                raise ErrorMapillary("La API repitió una página de resultados.")
            visitadas.add(url)
            datos = self.json(url)
            if not isinstance(datos.get("data"), list):
                raise ErrorMapillary("La API no devolvió una colección de imágenes.")
            yield from datos["data"]
            url = datos.get("paging", {}).get("next")

    def imagen(self, identificador):
        if not str(identificador).isascii() or not str(identificador).isdigit():
            raise ErrorMapillary("El ID de imagen de Mapillary debe ser numérico.")
        return self.json(f"{API}/{identificador}?{urlencode({'fields': ','.join(CAMPOS)})}")

    def seleccionar(self, bbox=None, secuencia=None, ids=None, limite=10):
        if ids:
            candidatos = ({"id": identificador} for identificador in ids)
        elif secuencia:
            candidatos = self.paginas("image_ids", {"sequence_id": secuencia, "limit": 200})
        else:
            candidatos = self.paginas("images", {
                "bbox": ",".join(map(str, bbox)), "fields": ",".join(CAMPOS),
                "limit": min(limite, 200) if limite else 200,
            })
        vistos = set()
        for candidato in candidatos:
            identificador = str(candidato.get("id", ""))
            if identificador in vistos:
                continue
            if not identificador.isascii() or not identificador.isdigit():
                raise ErrorMapillary("La API devolvió un ID de imagen inválido.")
            vistos.add(identificador)
            yield self.imagen(identificador) if ids or secuencia else candidato
            if limite and len(vistos) >= limite:
                break


def metadatos_guardables(datos):
    # No conservar URLs de descarga temporales, paginación ni credenciales.
    registro = {campo: datos[campo] for campo in CAMPOS if campo in datos and campo != "thumb_2048_url"}
    registro["id"] = str(datos["id"])
    registro["file_name"] = f"{registro['id']}.jpg"
    registro["source"] = "mapillary"
    registro["view_url"] = f"https://www.mapillary.com/app/?pKey={registro['id']}"
    return registro


def cargar_manifest(ruta, carpeta):
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    if not isinstance(datos, dict) or datos.get("source") != "mapillary" or not isinstance(datos.get("images"), list):
        raise ValueError("El manifest debe contener source=mapillary y una lista images.")
    carpeta = carpeta.resolve()
    registros = {}
    for registro in datos["images"]:
        if not isinstance(registro, dict) or not isinstance(registro.get("file_name"), str):
            raise ValueError("Cada imagen del manifest debe tener un file_name de texto.")
        archivo = (carpeta / registro["file_name"]).resolve()
        if not archivo.is_relative_to(carpeta) or not archivo.is_file():
            raise ValueError(f"Imagen del manifest ausente o fuera de la carpeta: {archivo.name}")
        if archivo in registros:
            raise ValueError(f"Imagen duplicada en el manifest: {archivo.name}")
        registros[archivo] = registro
    return registros


def geometria_camara(registro):
    for campo in ("computed_geometry", "geometry"):
        geometria = registro.get(campo)
        if isinstance(geometria, dict) and geometria.get("type") == "Point":
            coordenadas = geometria.get("coordinates", [])
            if (isinstance(coordenadas, (list, tuple)) and len(coordenadas) >= 2
                    and all(isinstance(v, (int, float)) and math.isfinite(v) for v in coordenadas[:2])
                    and -180 <= coordenadas[0] <= 180 and -90 <= coordenadas[1] <= 90):
                return {"type": "Point", "coordinates": coordenadas[:2]}, campo
    return None, None


def exportar_camaras(registros, ruta):
    features = []
    for registro in registros:
        geometria, origen = geometria_camara(registro)
        features.append({
            "type": "Feature", "id": registro["id"], "geometry": geometria,
            "properties": {
                "kind": "camera", "mapillary_id": registro["id"],
                "position_source": origen, "captured_at": registro.get("captured_at"),
                "sequence": registro.get("sequence"), "view_url": registro["view_url"],
            },
        })
    escribir_json(ruta, {"type": "FeatureCollection", "features": features})


def descargar_imagen(cliente, datos, destino):
    from PIL import Image

    if destino.is_file():
        try:
            with Image.open(destino) as imagen:
                imagen.verify()
            return
        except (OSError, ValueError):
            pass
    url = datos.get("thumb_2048_url")
    if not url:
        raise ErrorMapillary("No hay URL de imagen disponible para esta captura.")
    contenido = cliente.leer(url)  # Sin enviar el token de Mapillary al CDN.
    with Image.open(io.BytesIO(contenido)) as imagen:
        imagen.verify()
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_name(destino.name + ".part")
    temporal.write_bytes(contenido)
    temporal.replace(destino)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    seleccion = parser.add_mutually_exclusive_group(required=True)
    seleccion.add_argument("--bbox", type=float, nargs=4, metavar=("OESTE", "SUR", "ESTE", "NORTE"))
    seleccion.add_argument("--sequence", help="ID de secuencia de Mapillary")
    seleccion.add_argument("--image-id", nargs="+", help="Uno o más IDs numéricos de imágenes")
    parser.add_argument("--output", type=Path, default=Path("resultados/mapillary"))
    parser.add_argument("--limit", type=int, default=10, help="Máximo de imágenes; 0 = todas")
    parser.add_argument("--download-only", action="store_true", help="Descargar sin ejecutar DINO")
    parser.add_argument("--map", action="store_true", help="Actualizar el inventario y exportar su mapa después de DINO")
    parser.add_argument("--map-output", type=Path, default=Path("resultados/mapeo"))
    parser.add_argument("--relevamiento", default="principal", help="Identificador del inventario para --map")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--prompt", default="tree.")
    parser.add_argument("--threshold", type=float, default=0.35)
    parser.add_argument("--text-threshold", type=float, default=0.25)
    args = parser.parse_args()
    if args.map and args.download_only:
        parser.error("--map requiere ejecutar el detector; quitá --download-only")
    if args.limit < 0:
        parser.error("--limit no puede ser negativo.")
    if args.bbox:
        oeste, sur, este, norte = args.bbox
        if not (-180 <= oeste < este <= 180 and -90 <= sur < norte <= 90):
            parser.error("--bbox debe ser oeste sur este norte, con longitudes y latitudes válidas.")
    if args.sequence and not re.fullmatch(r"[A-Za-z0-9_-]+", args.sequence):
        parser.error("El ID de secuencia no es válido.")
    if not args.prompt.strip() or not (0 <= args.threshold <= 1 and 0 <= args.text_threshold <= 1):
        parser.error("Revisá el prompt y los umbrales (entre 0 y 1).")
    try:
        cliente = ClienteMapillary(obtener_token())
    except (ErrorMapillary, OSError) as error:
        parser.exit(1, f"{error}\n")
    try:
        import PIL  # Verificar Pillow antes de hacer consultas.
    except ImportError:
        parser.exit(1, "Falta Pillow. Instalá requirements-grounding.txt en hackaton.\n")

    salida = args.output.resolve()
    carpeta = salida / "imagenes"
    manifest = {"source": "mapillary", "images": [], "errors": []}
    try:
        for datos in cliente.seleccionar(args.bbox, args.sequence, args.image_id, args.limit):
            registro = metadatos_guardables(datos)
            try:
                descargar_imagen(cliente, datos, carpeta / registro["file_name"])
            except (ErrorMapillary, OSError, ValueError) as error:
                print(f"Imagen {registro['id']}: {error}", file=sys.stderr)
                manifest["errors"].append({"id": registro["id"], "error": str(error)})
            else:
                manifest["images"].append(registro)
                print(f"Imagen lista: {registro['id']}", flush=True)
            escribir_json(salida / "manifest.json", manifest)
            exportar_camaras(manifest["images"], salida / "camaras.geojson")
    except (ErrorMapillary, OSError, ValueError) as error:
        parser.exit(1, f"No se completó la descarga: {error}\n")
    escribir_json(salida / "manifest.json", manifest)
    exportar_camaras(manifest["images"], salida / "camaras.geojson")
    if not manifest["images"]:
        parser.exit(1, "No se descargaron imágenes. Revisá la cobertura, los IDs y el token.\n")
    print(f"Imágenes y metadatos: {salida}", flush=True)
    if args.download_only:
        return 1 if manifest["errors"] else 0
    comando = [
        sys.executable, str(Path(__file__).with_name("detectar_arboles.py")), str(carpeta),
        "--manifest", str(salida / "manifest.json"), "--output", str(salida / "detecciones"),
        "--limit", "0", "--device", args.device, "--prompt", args.prompt,
        "--threshold", str(args.threshold), "--text-threshold", str(args.text_threshold),
    ]
    resultado = subprocess.run(comando, check=False)
    if resultado.returncode == 0 and args.map:
        resultado = subprocess.run([
            sys.executable, str(Path(__file__).with_name("mapear_arboles.py")),
            "--dataset", str(salida), "--output", str(args.map_output),
            "--relevamiento", args.relevamiento,
        ], check=False)
    return resultado.returncode or (1 if manifest["errors"] else 0)


if __name__ == "__main__":
    sys.exit(main())
