"""Escena de control explícitamente sintética; nunca se presenta como Mapillary real."""

import math
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

from mapillary_arboles import escribir_json
from .camaras import MarcoLocal


def vector_rotacion(matriz):
    angulo = math.acos(float(np.clip((np.trace(matriz) - 1) / 2, -1, 1)))
    if angulo < 1e-12:
        return [0., 0., 0.]
    return (np.array([matriz[2, 1] - matriz[1, 2], matriz[0, 2] - matriz[2, 0], matriz[1, 0] - matriz[0, 1]]) * angulo / (2 * math.sin(angulo))).tolist()


def registro_sintetico(image_id, camera_xy, puntos, marco=None, grupo=False, timestamp=1539978452606, verified=True):
    marco = marco or MarcoLocal(-59.1405, -37.3351)
    lon, lat = marco.geografica(*camera_xy)
    heading = math.degrees(math.atan2(13 - camera_xy[0], 10 - camera_xy[1])) % 360
    h = math.radians(heading)
    camera_to_world = np.array([[math.cos(h), 0, math.sin(h)], [-math.sin(h), 0, math.cos(h)], [0, -1, 0]])
    meta = {"id": str(image_id), "file_name": f"{image_id}.jpg", "capture_id": str(image_id),
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "computed_geometry": {"type": "Point", "coordinates": [lon, lat]},
            "computed_rotation": vector_rotacion(camera_to_world.T), "computed_compass_angle": heading,
            "camera_type": "perspective", "camera_parameters": [.8, 0., 0.],
            "width": 2000, "height": 1200, "exif_orientation": 1, "sequence": "SYNTHETIC",
            "captured_at": timestamp, "creator": {"username": "ESCENA SINTETICA"},
            "view_url": "", "synthetic": True}
    detecciones = []
    for indice, punto in enumerate(puntos):
        local = camera_to_world.T @ np.array([punto[0] - camera_xy[0], punto[1] - camera_xy[1], 0.])
        u = 999.5 + 1600 * local[0] / local[2]
        v = 599.5
        det = {"label": "tree", "score": .9, "bbox_xyxy": [u - 35, v - 170, u + 35, v + 170],
               "kind": "individual", "kind_verified": True,
               "anchor": {"pixel": [u, v], "verified": verified, "uncertainty_deg": .05, "source": "synthetic_truth"}}
        detecciones.append(det)
    if grupo:
        detecciones = [{"label": "tree", "score": .9, "kind": "group", "kind_verified": True,
                        "bbox_xyxy": [min(d["bbox_xyxy"][0] for d in detecciones) - 20, 400.,
                                      max(d["bbox_xyxy"][2] for d in detecciones) + 20, 800.]}]
    return {"model": "SYNTHETIC_CONTROL_NOT_DINO", "revision": "fixture-v1", "prompt": "tree.",
            "threshold": .35, "text_threshold": .25, "width": 2000, "height": 1200,
            "mapillary": meta, "detections": detecciones}


def crear_demo(raiz):
    raiz = Path(raiz)
    marco = MarcoLocal(-59.1405, -37.3351)
    puntos = [(12., 10.), (14., 10.)]
    registros = [registro_sintetico("demo_group", (13., -10.), puntos, marco, grupo=True)]
    registros.extend(registro_sintetico(f"demo_{i}", c, puntos, marco, timestamp=1539978452606 + i * 10000) for i, c in enumerate([(3., 0.), (10., 0.), (20., 0.)], 1))
    referencia = {"synthetic": True, "trees": [{"id": f"T{i+1}", "coordinates": marco.geografica(*p)} for i, p in enumerate(puntos)], "observations": []}
    for registro in registros:
        meta = registro["mapillary"]
        imagen = Image.new("RGB", (2000, 1200), "#e5eddf")
        dibujo = ImageDraw.Draw(imagen)
        dibujo.text((30, 30), "ESCENA SINTETICA - NO ES UNA CAPTURA REAL NI UNA PREDICCION DE DINO", fill="black")
        for indice, det in enumerate(registro["detections"]):
            dibujo.rectangle(det["bbox_xyxy"], outline="green", width=5)
            if det.get("anchor"):
                u, v = det["anchor"]["pixel"]
                dibujo.ellipse((u-5,v-5,u+5,v+5),fill="red")
                referencia["observations"].append({"image_id": meta["id"], "detection_index": indice, "tree_id": f"T{indice+1}"})
        carpeta = raiz / "imagenes"
        carpeta.mkdir(parents=True, exist_ok=True)
        imagen.save(carpeta / meta["file_name"])
        escribir_json(raiz / "detecciones" / (meta["file_name"] + ".json"), registro)
    escribir_json(raiz / "manifest.json", {"source": "mapillary", "synthetic": True, "images": [r["mapillary"] for r in registros]})
    escribir_json(raiz / "referencia.json", referencia)
    return raiz
