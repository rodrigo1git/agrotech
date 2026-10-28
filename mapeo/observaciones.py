"""Observaciones inmutables y clasificación conservadora dentro de cada captura."""

import hashlib
import json
import math
import uuid
from datetime import datetime, timezone

from .camaras import proyectar_observacion


def huella(datos):
    return hashlib.sha256(json.dumps(datos, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def identificador(tipo, *partes):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, tipo + ":" + ":".join(map(str, partes))))


def area(caja):
    return max(0., caja[2] - caja[0]) * max(0., caja[3] - caja[1])


def inter_area(a, b):
    return max(0., min(a[2], b[2]) - max(a[0], b[0])) * max(0., min(a[3], b[3]) - max(a[1], b[1]))


def iou(a, b):
    inter = inter_area(a, b)
    return inter / max(area(a) + area(b) - inter, 1e-12)


def crear_observaciones(registro, run_id, survey_id):
    metadata = registro["mapillary"]
    image_id = str(metadata["id"])
    captura = str(metadata.get("capture_id", image_id))
    timestamp = metadata.get("captured_at")
    if timestamp is not None:
        timestamp = float(timestamp)
        if not math.isfinite(timestamp):
            raise ValueError("Fecha de captura inválida")
    epoch = str(datetime.fromtimestamp(timestamp / 1000, timezone.utc).year) if timestamp is not None else "unknown"
    width, height = int(registro["width"]), int(registro["height"])
    if width <= 0 or height <= 0:
        raise ValueError("Dimensiones de imagen inválidas")
    observaciones = []
    for indice, det in enumerate(registro["detections"]):
        caja = list(map(float, det["bbox_xyxy"]))
        if len(caja) != 4 or not all(math.isfinite(v) for v in caja) or area(caja) <= 0:
            raise ValueError("Bounding box inválida")
        if not (0 <= caja[0] < caja[2] <= width and 0 <= caja[1] < caja[3] <= height):
            raise ValueError("Bounding box fuera de la imagen")
        score = float(det["score"])
        if not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("Score de detección inválido")
        observaciones.append({
            "id": identificador("observation", survey_id, run_id, indice),
            "run_id": run_id, "image_id": image_id, "capture_id": captura,
            "detection_index": indice,
            "survey_id": survey_id, "epoch": epoch, "captured_at": timestamp,
            "sequence": metadata.get("sequence"), "width": width, "height": height,
            "bbox_xyxy": caja, "score": score, "label": det.get("label", "tree"),
            "source_observation_id": det.get("observation_id"),
            "image_path": registro.get("_image_path"),
            "result_path": registro.get("_result_path"),
            "anchor": det.get("anchor"), "role": det.get("kind", "individual"),
            "role_verified": bool(det.get("kind_verified", False)),
            "view_url": metadata.get("view_url", f"https://www.mapillary.com/app/?pKey={image_id}"),
        })
    return observaciones


def preparar_observaciones(observaciones, capturas, marco, config, overrides):
    preparados = []
    for original in observaciones:
        obs = json.loads(json.dumps(original))
        cambios = overrides.get(("observation", obs["id"]), {})
        obs.update(cambios)
        meta = dict(capturas[obs["image_id"]])
        meta.update(overrides.get(("camera", obs["image_id"]), {}))
        obs["creator"] = meta.get("creator")
        obs["ray"] = proyectar_observacion(obs, meta, marco, config) if marco else {"valid": False, "reason": "No hay marco geográfico", "anchor_verified": False}
        if obs["role"] not in ("individual", "group", "duplicate", "rejected"):
            raise ValueError("Rol de observación desconocido")
        if (not obs["role_verified"] and obs["ray"].get("valid")
                and obs["ray"]["half_width_deg"] * 2 > config["max_individual_width_deg"]):
            obs["role"] = "group"
            obs["role_reason"] = "wide_box_possible_group"
        preparados.append(obs)

    por_imagen = {}
    for obs in preparados:
        por_imagen.setdefault(obs["image_id"], []).append(obs)
    for fila in por_imagen.values():
        ordenadas = sorted(fila, key=lambda o: (-o["score"], o["id"]))
        for i, obs in enumerate(ordenadas):
            if obs["role_verified"] or obs["role"] == "rejected":
                continue
            for anterior in ordenadas[:i]:
                if anterior["role"] != "duplicate" and iou(obs["bbox_xyxy"], anterior["bbox_xyxy"]) >= config["duplicate_iou"]:
                    obs["role"] = "duplicate"
                    obs["duplicate_of"] = anterior["id"]
                    break
        for obs in fila:
            if obs["role_verified"] or obs["role"] in ("duplicate", "rejected"):
                continue
            menores = [b for b in fila if b["id"] != obs["id"] and b["role"] not in ("duplicate", "rejected")
                       and area(b["bbox_xyxy"]) < .8 * area(obs["bbox_xyxy"])
                       and inter_area(obs["bbox_xyxy"], b["bbox_xyxy"]) / area(b["bbox_xyxy"]) > .9]
            if len(menores) >= 2:
                obs["role"] = "group"
                obs["role_reason"] = "contains_multiple_detections"
                obs["contains"] = [b["id"] for b in menores]
    return preparados
