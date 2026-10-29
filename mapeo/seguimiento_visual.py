"""Asociación visual básica de cajas entre fotos cercanas de una secuencia.

El comparador predeterminado solo usa Pillow/NumPy. Puede reemplazarse pasando
un callable a crear_enlaces: (observacion_a, observacion_b) -> métricas o None.
Estas asociaciones son hipótesis automáticas, nunca confirmaciones manuales.
"""

from collections import defaultdict
from datetime import datetime, timezone
from functools import lru_cache
import math
from pathlib import Path

import numpy as np
from PIL import Image

from .camaras import MarcoLocal, diferencia_angular, posicion
from .localizacion import ajustar, epocas_compatibles


DEFAULTS = {
    "allow_visual_tracking": False,
    "tracking_min_score": .72,
    "tracking_min_ncc": .60,
    "tracking_min_color": .70,
    "tracking_ambiguity_margin": .06,
    "tracking_max_center_shift": .35,
    "tracking_min_area_ratio": .35,
    "tracking_max_time_gap_s": 5.,
    "tracking_max_camera_distance_m": 15.,
    "tracking_max_heading_change_deg": 15.,
    "tracking_frame_gap": 2,
}


class ComparadorRecortes:
    """Correlación de textura y color de la caja, sin usar sus coordenadas GPS."""
    method = "crop_ncc_v1"
    def __init__(self):
        self.descriptores = {}

    @lru_cache(maxsize=2)
    def imagen(self, ruta):
        with Image.open(ruta) as imagen:
            return imagen.convert("RGB")

    def descriptor(self, obs):
        if obs["id"] in self.descriptores:
            return self.descriptores[obs["id"]]
        resultado = None
        try:
            ruta = obs.get("image_path")
            if ruta and Path(ruta).is_file():
                imagen = self.imagen(ruta)
                if imagen.size != (obs["width"], obs["height"]):
                    return None
                recorte = imagen.crop(obs["bbox_xyxy"]).resize((40, 40), Image.Resampling.BILINEAR)
                gris = np.asarray(recorte.convert("L"), dtype=np.float32) / 255.
                rgb = np.asarray(recorte)
                hist = np.concatenate([np.histogram(rgb[:, :, c], bins=12, range=(0, 256))[0] for c in range(3)]).astype(float)
                if float(gris.std()) >= .03:
                    resultado = (gris, hist / max(float(np.linalg.norm(hist)), 1e-9))
        except (OSError, ValueError):
            pass
        self.descriptores[obs["id"]] = resultado
        return resultado

    def __call__(self, a, b):
        da, db = self.descriptor(a), self.descriptor(b)
        if da is None or db is None:
            return None
        ga, ha = da
        gb, hb = db
        ncc = 0.
        # Admitir pequeños cambios del encuadre de DINO dentro de las cajas.
        for dy in (-3, 0, 3):
            for dx in (-3, 0, 3):
                va = ga[max(0, dy):min(40, 40 + dy), max(0, dx):min(40, 40 + dx)].ravel()
                vb = gb[max(0, -dy):min(40, 40 - dy), max(0, -dx):min(40, 40 - dx)].ravel()
                va, vb = va - va.mean(), vb - vb.mean()
                den = float(np.linalg.norm(va) * np.linalg.norm(vb))
                if den > 1e-8:
                    ncc = max(ncc, float(np.dot(va, vb)) / den)
        color = float(np.clip(np.dot(ha, hb), 0., 1.))
        ncc = float(np.clip(ncc, 0., 1.))
        return {"score": .7 * ncc + .3 * color, "ncc": ncc, "color": color}


def cajas_compatibles(a, b, config):
    def forma(o):
        x1, y1, x2, y2 = o["bbox_xyxy"]
        return ((x1 + x2) / (2 * o["width"]), (y1 + y2) / (2 * o["height"]),
                (x2 - x1) * (y2 - y1) / (o["width"] * o["height"]))
    ax, ay, aa = forma(a)
    bx, by, ba = forma(b)
    return (math.hypot(ax - bx, ay - by) <= config["tracking_max_center_shift"]
            and min(aa, ba) / max(aa, ba, 1e-12) >= config["tracking_min_area_ratio"])


def capturas_compatibles(a, b, config):
    if not a.get("sequence") or a.get("sequence") != b.get("sequence"):
        return False
    try:
        ta, tb = float(a["captured_at"]), float(b["captured_at"])
        if not 0 < tb - ta <= config["tracking_max_time_gap_s"] * 1000:
            return False
        ga, gb = posicion(a), posicion(b)
        if math.hypot(*MarcoLocal(*ga[:2]).proyectar(*gb[:2])) > config["tracking_max_camera_distance_m"]:
            return False
        ha = a.get("computed_compass_angle")
        hb = b.get("computed_compass_angle")
        ha = a.get("compass_angle") if ha is None else ha
        hb = b.get("compass_angle") if hb is None else hb
        return ha is not None and hb is not None and abs(diferencia_angular(float(ha), float(hb))) <= config["tracking_max_heading_change_deg"]
    except (KeyError, ValueError, TypeError):
        return False


def crear_enlaces(observaciones, capturas, config, comparador=None):
    cfg = {**DEFAULTS, **config}
    if not cfg["allow_visual_tracking"]:
        return []
    comparar = comparador or ComparadorRecortes()
    por_imagen, secuencias = defaultdict(list), defaultdict(list)
    for o in observaciones:
        if o["role"] == "individual":
            por_imagen[o["image_id"]].append(o)
    for iid, meta in capturas.items():
        if meta.get("sequence") and meta.get("captured_at") is not None:
            try:
                dia = datetime.fromtimestamp(meta["captured_at"] / 1000, timezone.utc).strftime("%Y-%m-%d")
            except (ValueError, TypeError, OverflowError):
                continue
            secuencias[(str(meta["sequence"]), dia)].append((meta["captured_at"], iid))
    enlaces = []
    for imagenes in secuencias.values():
        imagenes.sort()
        for i, (_, ida) in enumerate(imagenes):
            for _, idb in imagenes[i + 1:i + 1 + int(cfg["tracking_frame_gap"])]:
                if not capturas_compatibles(capturas[ida], capturas[idb], cfg):
                    continue
                aa, bb = por_imagen[ida], por_imagen[idb]
                candidatos = []
                for a in aa:
                    for b in bb:
                        if a["capture_id"] == b["capture_id"] or not cajas_compatibles(a, b, cfg):
                            continue
                        m = comparar(a, b)
                        if m:
                            candidatos.append({"a": a["id"], "b": b["id"], "image_a": ida, "image_b": idb,
                                               "matcher": getattr(comparar, "method", "custom"), **m})
                for c in candidatos:
                    if c["score"] < cfg["tracking_min_score"] or c.get("ncc", 1.) < cfg["tracking_min_ncc"] or c.get("color", 1.) < cfg["tracking_min_color"]:
                        continue
                    otros_a = [p["score"] for p in candidatos if p["a"] == c["a"] and p["b"] != c["b"]]
                    otros_b = [p["score"] for p in candidatos if p["b"] == c["b"] and p["a"] != c["a"]]
                    if c["score"] - max(otros_a + otros_b, default=0.) >= cfg["tracking_ambiguity_margin"]:
                        enlaces.append(c)
    return sorted(enlaces, key=lambda e: (-e["score"], e["a"], e["b"]))


def fusionar_propuestas(propuestas, observaciones, enlaces, anteriores, config):
    """Unir candidatos compatibles conservando evidencia, no puntos cercanos."""
    por_id = {o["id"]: o for o in observaciones}
    protegidas = {oid for t in anteriores.get("trees", []) if t.get("active", True)
                  and (t.get("origin") == "review" or t.get("identity_status") == "confirmed") for oid in t["observation_ids"]}
    padres = list(range(len(propuestas)))
    miembros = {i: set(p["observation_ids"]) for i, p in enumerate(propuestas)}
    dueños = {oid: i for i, ids in miembros.items() for oid in ids}
    evidencia, rechazados, aplicados = defaultdict(list), [], []

    def raiz(i):
        while padres[i] != i:
            padres[i] = padres[padres[i]]
            i = padres[i]
        return i

    for e in enlaces:
        if e["a"] not in dueños or e["b"] not in dueños:
            rechazados.append({**e, "reason": "unresolved_or_group_observation"})
            continue
        a, b = raiz(dueños[e["a"]]), raiz(dueños[e["b"]])
        if a == b:
            evidencia[a].append(e)
            continue
        ids = miembros[a] | miembros[b]
        oo = [por_id[oid] for oid in sorted(ids)]
        razon = None
        if ids & protegidas or any(propuestas[j].get("identity_status") == "confirmed" for j in (a, b)):
            razon = "protected_identity"
        elif len({o["epoch"] for o in oo}) != 1:
            razon = "different_years"
        elif any(not epocas_compatibles(x, y, config) for i, x in enumerate(oo) for y in oo[i + 1:]):
            razon = "incompatible_capture_dates"
        elif len({o["capture_id"] for o in oo}) != len(oo):
            razon = "distinct_trees_visible_in_same_capture"
        fit = ajustar([o for o in oo if o["ray"].get("valid")], config) if razon is None else None
        if razon is None and fit is None and (propuestas[a].get("fit") or propuestas[b].get("fit")):
            razon = "would_discard_existing_geometry"
        if razon:
            rechazados.append({**e, "reason": razon})
            continue
        padres[b] = a
        miembros[a] = ids
        estado_posicion = ("estimated" if fit["uncertainty_m"] <= config["max_position_uncertainty_m"] else "needs_review") if fit else "unlocated"
        propuestas[a] = {**propuestas[a], "observation_ids": sorted(ids), "fit": fit,
                         "identity_status": "candidate", "position_status": estado_posicion,
                         "review_reason": "Basic visual association between nearby frames; pending identity review"}
        evidencia[a].extend(evidencia.pop(b, []))
        evidencia[a].append(e)
        aplicados.append(e)
    resultado = []
    for i, p in enumerate(propuestas):
        if raiz(i) != i:
            continue
        if evidencia[i]:
            p = {**p, "visual_tracking": {"method": "visual_tracking_v1", "links": evidencia[i],
                                         "images": len({por_id[oid]["image_id"] for oid in p["observation_ids"]}),
                                         "confirmed": False}}
        resultado.append(p)
    return resultado, {"method": "visual_tracking_v1", "candidate_links": len(enlaces),
                       "before": len(propuestas), "after": len(resultado),
                       "merges": len(propuestas) - len(resultado), "applied": aplicados, "rejected": rechazados}
