"""Exportaciones atómicas y mapa HTML con vista local disponible sin conexión."""

import math
from pathlib import Path

from mapillary_arboles import escribir_json
from .camaras import posicion
from .visualizacion import exportar_mapa
from .inventario import contadores, observaciones_actuales


def coleccion(features):
    return {"type": "FeatureCollection", "features": features}


def evidencia(obs, destino):
    if not obs.get("image_path") or not Path(obs["image_path"]).is_file():
        return None
    from PIL import Image
    archivo = destino / "evidencia" / f"{obs['id']}.jpg"
    with Image.open(obs["image_path"]) as imagen:
        x1, y1, x2, y2 = obs["bbox_xyxy"]
        caja = [max(0, int(x1) - 15), max(0, int(y1) - 15), min(imagen.width, int(math.ceil(x2)) + 15), min(imagen.height, int(math.ceil(y2)) + 15)]
        if not archivo.exists():
            recorte = imagen.convert("RGB").crop(caja)
            recorte.thumbnail((640, 480))
            archivo.parent.mkdir(parents=True, exist_ok=True)
            recorte.save(archivo, quality=85)
    return {"url": f"evidencia/{obs['id']}.jpg", "crop_box": caja}


def exportar(almacen, survey, config, destino):
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    marco, capturas, observaciones = observaciones_actuales(almacen, survey, config)
    estado = almacen.estado(survey["id"])
    observaciones = estado.get("observations", observaciones)
    metricas = contadores(estado, observaciones)
    arboles, camaras, obs_geo, grupos = [], [], [], []
    for arbol in estado["trees"]:
        if not arbol.get("active", True):
            continue
        fit = arbol.get("fit")
        geometria = {"type": "Point", "coordinates": marco.geografica(*fit["xy"])} if fit and marco else None
        arboles.append({"type": "Feature", "id": arbol["id"], "geometry": geometria, "properties": {**arbol, "kind": "tree"}})
    for image_id, meta in capturas.items():
        try:
            lon, lat, campo = posicion(meta)
            geometria = {"type": "Point", "coordinates": [lon, lat]}
            xy = marco.proyectar(lon, lat) if marco else None
        except ValueError:
            geometria, campo, xy = None, None, None
        camaras.append({"type": "Feature", "id": image_id, "geometry": geometria,
                        "properties": {"kind": "camera", "image_id": image_id, "xy": xy,
                                       "position_source": campo, "captured_at": meta.get("captured_at"),
                                       "sequence": meta.get("sequence"), "creator": meta.get("creator"),
                                       "view_url": f"https://www.mapillary.com/app/?pKey={image_id}"}})
    for obs in observaciones:
        ray = obs["ray"]
        geometria = None
        if marco and ray.get("valid"):
            inicio = ray["origin_xy"]
            fin = [inicio[i] + config["ray_display_length_m"] * ray["direction"][i] for i in (0, 1)]
            geometria = {"type": "LineString", "coordinates": [marco.geografica(*inicio), marco.geografica(*fin)]}
        props = {**obs, "kind": "observation", "ray_display_length_m": config["ray_display_length_m"],
                 "ray_is_measured_distance": False, "evidence": evidencia(obs, destino)}
        obs_geo.append({"type": "Feature", "id": obs["id"], "geometry": geometria, "properties": props})
    for grupo in estado["groups"]:
        if grupo.get("active", True):
            grupos.append({"type": "Feature", "id": grupo["id"], "geometry": grupo.get("geometry"), "properties": {**grupo, "kind": "group"}})
    datos = {"survey": survey, "counts": metricas, "trees": arboles, "cameras": camaras, "observations": obs_geo, "groups": grupos}
    for nombre, features in (("arboles", arboles), ("camaras", camaras), ("observaciones", obs_geo), ("grupos", grupos)):
        if nombre == "arboles":
            features = [f for f in features if f["geometry"] is not None]
        escribir_json(destino / f"{nombre}.geojson", coleccion(features))
    eventos = almacen.eventos(survey["id"])
    escribir_json(destino / "inventario.json", {"survey": survey, "counts": metricas, **estado,
                                               "observations": observaciones, "captures": list(capturas.values()),
                                               "events": eventos})
    escribir_json(destino / "estadisticas.json", metricas)
    exportar_mapa(datos, destino)
    return metricas
