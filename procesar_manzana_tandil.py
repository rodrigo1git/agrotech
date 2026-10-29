"""Conectar las imágenes descargadas, DINO y el mapa de la manzana."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote

from PIL import Image

from descargar_manzana_tandil import SALIDA
from mapillary_arboles import cargar_manifest, escribir_json, geometria_camara
from mapeo.camaras import MarcoLocal, orientacion_visual
from mapeo.visualizacion import exportar_mapa, renderizar_mapa


RAIZ = Path(__file__).resolve().parent
RELEVAMIENTO = "manzana_tandil"


def menu_mapas(exportaciones):
    return [{"id": p.name, "label": "Manzana completa" if p.name == RELEVAMIENTO else "Prueba inicial (3 capturas)" if p.name == "tandil2018" else p.name,
             "url": "../" + quote(p.name, safe="") + "/mapa.html"}
            for p in sorted(Path(exportaciones).iterdir()) if p.is_dir() and (p / "mapa.html").is_file()]


def enlazar_mapas(exportaciones):
    opciones = menu_mapas(exportaciones)
    for opcion in opciones:
        archivo = Path(exportaciones) / opcion["id"] / "mapa.html"
        html = archivo.read_text(encoding="utf-8")
        bloque = re.search(r'<script id="datos" type="application/json">(.*?)</script>', html, re.S)
        if bloque:
            datos = json.loads(bloque.group(1))
            datos["related_maps"] = opciones
            # Mantener la calibración que ya estaba incluida en cada HTML.
            temporal = archivo.with_suffix(".html.tmp")
            temporal.write_text(renderizar_mapa(datos), encoding="utf-8")
            temporal.replace(archivo)


def catalogo_camaras(dataset, destino):
    dataset, destino = Path(dataset), Path(destino)
    metadata = cargar_manifest(dataset / "manifest.json", dataset / "imagenes")
    registros = sorted(metadata.items(), key=lambda par: (par[1].get("captured_at") or 0, str(par[1]["id"])))
    origen = next((g["coordinates"] for _, m in registros if (g := geometria_camara(m)[0])), None)
    marco = MarcoLocal(*origen) if origen else None
    camaras = []
    for imagen, m in registros:
        g, campo = geometria_camara(m)
        fuente_foto, anotada, detecciones = imagen, False, None
        resultado = dataset / "detecciones" / (m["file_name"] + ".json")
        png = dataset / "detecciones" / (m["file_name"] + ".png")
        if resultado.is_file() and png.is_file():
            try:
                registro = json.loads(resultado.read_text())
                if str(registro.get("mapillary", {}).get("id")) == str(m["id"]) and isinstance(registro.get("detections"), list):
                    fuente_foto, anotada, detecciones = png, True, len(registro["detections"])
            except (OSError, ValueError):
                pass
        archivo = destino / "capturas" / f"{m['id']}.jpg"
        grande = destino / "capturas" / "grandes" / f"{m['id']}.jpg"
        informacion = {"source": str(fuente_foto.relative_to(dataset)), "mtime_ns": fuente_foto.stat().st_mtime_ns,
                       "size": fuente_foto.stat().st_size}
        cache = archivo.with_suffix(".meta.json")
        try:
            coincide = json.loads(cache.read_text()) == informacion
        except (OSError, ValueError):
            coincide = False
        if not archivo.is_file() or not grande.is_file() or not coincide:
            archivo.parent.mkdir(parents=True, exist_ok=True)
            grande.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(fuente_foto) as original:
                copia = original.convert("RGB")
                temporal_grande = grande.with_suffix(".jpg.tmp")
                copia.save(temporal_grande, format="JPEG", quality=92)
                temporal_grande.replace(grande)
                copia.thumbnail((800, 600))
                temporal = archivo.with_suffix(".jpg.tmp")
                copia.save(temporal, format="JPEG", quality=85)
                temporal.replace(archivo)
            escribir_json(cache, informacion)
        camaras.append({"type": "Feature", "id": str(m["id"]), "geometry": g,
                        "properties": {"kind": "camera", "image_id": str(m["id"]),
                                       "xy": marco.proyectar(*g["coordinates"]) if g and marco else None,
                                       "position_source": campo, "captured_at": m.get("captured_at"),
                                       "sequence": m.get("sequence"), "creator": m.get("creator"),
                                       "camera_view": orientacion_visual(m),
                                       "photo": {"url": f"capturas/{m['id']}.jpg", "full_url": f"capturas/grandes/{m['id']}.jpg",
                                                 "annotated": anotada, "detections": detecciones},
                                       "view_url": m.get("view_url", f"https://www.mapillary.com/app/?pKey={m['id']}")}})
    return camaras, origen


def progreso(dataset, total, stage):
    procesadas = 0
    for p in (Path(dataset) / "detecciones").glob("*.jpg.json"):
        try:
            if isinstance(json.loads(p.read_text()).get("detections"), list):
                procesadas += 1
        except (OSError, ValueError):
            continue
    return {"stage": stage, "images_total": total, "images_processed": procesadas,
            "description": "La descarga y la detección son etapas distintas. Los puntos azules representan las imágenes disponibles."}


def publicar(dataset, output, previa=False):
    destino = Path(output) / "exportaciones" / RELEVAMIENTO
    destino.mkdir(parents=True, exist_ok=True)
    camaras, origen = catalogo_camaras(dataset, destino)
    archivo = destino / "mapa_datos.json"
    if archivo.is_file():
        datos = json.loads(archivo.read_text())
    else:
        datos = {"survey": {"id": RELEVAMIENTO, "origin": origen}, "counts": {},
                 "trees": [], "observations": [], "groups": []}
    # El marco del inventario y el catálogo usan la misma captura inicial.
    fotos = {f["id"]: f["properties"]["photo"] for f in camaras}
    orientaciones = {f["id"]: f["properties"]["camera_view"] for f in camaras}
    existentes = {f["id"]: f for f in datos.get("cameras", [])}
    datos["cameras"] = [existentes.get(f["id"], f) for f in camaras]
    for f in datos["cameras"]:
        f["properties"]["photo"] = fotos.get(f["id"])
        if "camera_view" not in f["properties"]:
            orientacion = orientaciones.get(f["id"])
            giro = (datos.get("map_calibration") or datos.get("horizontal_calibration") or {}).get("rotation_deg", 0)
            f["properties"]["camera_view"] = {**orientacion, "bearing_deg": (orientacion["bearing_deg"] + giro) % 360} if orientacion else None
    datos["pipeline"] = progreso(dataset, len(camaras), "detecting" if previa else "complete")
    if datos["pipeline"]["images_processed"] < len(camaras):
        datos["pipeline"]["stage"] = "detecting"
    exportar_mapa(datos, destino)
    enlazar_mapas(destino.parent)
    return destino / "mapa.html"


def construir_inventario(dataset, output, parcial=False, seguimiento=None, config_path=None):
    from mapear_arboles import cargar_config, registros_dataset
    from mapeo.almacen import Almacen
    from mapeo.exportacion import exportar
    from mapeo.inventario import reconciliar
    config = cargar_config(config_path)
    almacen = Almacen(Path(output) / "inventario.sqlite")
    try:
        survey = almacen.survey(RELEVAMIENTO, config)
        config = dict(config if config_path else survey["config"])
        if seguimiento is not None:
            config["allow_visual_tracking"] = seguimiento
        if config != survey["config"]:
            with almacen.transaccion():
                anterior = dict(survey["config"])
                survey["config"] = config
                almacen.guardar_survey(survey)
                almacen.evento(survey["id"], "configuration", {"before": anterior, "after": config})
        for registro in registros_dataset(dataset, permitir_faltantes=parcial):
            almacen.importar(survey["id"], registro)
        print("Imágenes importadas. Asociando árboles entre vistas…", flush=True)
        # Reconciliar el conjunto una vez, en vez de recalcularlo 89 veces.
        resultado = reconciliar(almacen, survey, config)
        escribir_json(Path(output) / "exportaciones" / RELEVAMIENTO / "seguimiento_debug.json", resultado["tracking_report"])
        return exportar(almacen, survey, config, Path(output) / "exportaciones" / RELEVAMIENTO)
    finally:
        almacen.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=SALIDA)
    parser.add_argument("--output", type=Path, default=RAIZ / "resultados/mapeo")
    parser.add_argument("--skip-inference", action="store_true", help="Usar detecciones ya calculadas y generar el inventario.")
    parser.add_argument("--preview-only", action="store_true", help="Mostrar las cámaras y sus fotografías sin ejecutar DINO.")
    parser.add_argument("--partial", action="store_true", help="Actualizar el mapa con las detecciones disponibles mientras DINO sigue trabajando.")
    parser.add_argument("--config", type=Path, help="Archivo JSON de ajustes; guarda la configuración aplicada en este relevamiento.")
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument("--tracking", dest="tracking", action="store_const", const=True, default=None, help="Activar asociación visual básica entre fotos próximas.")
    grupo.add_argument("--no-tracking", dest="tracking", action="store_const", const=False, help="Volver a la asociación geométrica sin seguimiento visual.")
    args = parser.parse_args()
    try:
        mapa = publicar(args.dataset, args.output, previa=True)
        print(f"Mapa con las capturas disponibles: {mapa}", flush=True)
        if args.preview_only:
            return 0
        if not args.skip_inference and not args.partial:
            entorno = os.environ.copy()
            entorno.setdefault("OMP_NUM_THREADS", "4")
            entorno.setdefault("MKL_NUM_THREADS", "4")
            comando = [sys.executable, "-B", str(RAIZ / "detectar_arboles.py"), str(args.dataset / "imagenes"),
                       "--manifest", str(args.dataset / "manifest.json"), "--output", str(args.dataset / "detecciones"),
                       "--limit", "0", "--prompt", "tree.", "--skip-existing"]
            if subprocess.run(comando, env=entorno, check=False).returncode:
                raise ValueError("DINO no completó todas las imágenes; el mapa conserva la vista de capturas.")
        metricas = construir_inventario(args.dataset, args.output, args.partial, args.tracking, args.config)
        mapa = publicar(args.dataset, args.output)
        print(json.dumps(metricas, ensure_ascii=False, indent=2))
        print(f"Mapa de la manzana: {mapa}", flush=True)
        return 0
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"No se completó el mapa de la manzana: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
