"""Estimación robusta en planta y comprobaciones de visibilidad."""

import math
import numpy as np
from .camaras import diferencia_angular


def error_angular(obs, punto):
    rayo = obs["ray"]
    dx, dy = np.asarray(punto) - np.asarray(rayo["origin_xy"])
    if math.hypot(dx, dy) < .01:
        return 180.0
    return abs(diferencia_angular(math.degrees(math.atan2(dx, dy)), rayo["bearing_deg"]))


def rango(obs, punto):
    return float(np.dot(np.asarray(punto) - obs["ray"]["origin_xy"], obs["ray"]["direction"]))


def epocas_compatibles(a, b, config):
    if a.get("epoch") != b.get("epoch"):
        return False
    ta, tb = a.get("captured_at"), b.get("captured_at")
    return ta is None or tb is None or abs(ta - tb) <= config["max_time_gap_days"] * 86400000


def interseccion(a, b, config):
    if a["capture_id"] == b["capture_id"] or not epocas_compatibles(a, b, config):
        return None
    ca, cb = np.asarray(a["ray"]["origin_xy"]), np.asarray(b["ray"]["origin_xy"])
    baseline = float(np.linalg.norm(ca - cb))
    if not config["min_baseline_m"] <= baseline <= config["max_camera_distance_m"]:
        return None
    da, db = np.asarray(a["ray"]["direction"]), np.asarray(b["ray"]["direction"])
    seno = abs(float(np.linalg.det(np.column_stack((da, db)))))
    if seno < math.sin(math.radians(config["min_parallax_deg"])):
        return None
    distancias = np.linalg.solve(np.column_stack((da, -db)), cb - ca)
    if any(t <= .1 or t > config["max_range_m"] for t in distancias):
        return None
    return ca + da * distancias[0]


def ajustar(observaciones, config):
    """IRLS sobre rectas con control angular, parallax y error de posición.

    La incertidumbre es una cota heurística de sensibilidad, no un intervalo
    estadístico calibrado. El error GPS se mantiene como piso independiente.
    """
    if len({o["capture_id"] for o in observaciones}) < config["min_views_candidate"]:
        return None
    mejor_seno, max_baseline = 0., 0.
    for i, a in enumerate(observaciones):
        for b in observaciones[i + 1:]:
            if a["capture_id"] == b["capture_id"]:
                continue
            baseline = float(np.linalg.norm(np.asarray(a["ray"]["origin_xy"]) - b["ray"]["origin_xy"]))
            if baseline >= config["min_baseline_m"]:
                max_baseline = max(max_baseline, baseline)
                mejor_seno = max(mejor_seno, abs(float(np.linalg.det(np.array([a["ray"]["direction"], b["ray"]["direction"]])))))
    if max_baseline < config["min_baseline_m"] or mejor_seno < math.sin(math.radians(config["min_parallax_deg"])):
        return None
    normales = np.array([[-o["ray"]["direction"][1], o["ray"]["direction"][0]] for o in observaciones])
    centros = np.array([o["ray"]["origin_xy"] for o in observaciones])
    rhs = np.sum(normales * centros, axis=1)
    pesos = np.ones(len(observaciones))
    punto = None
    for _ in range(6):
        a = normales * np.sqrt(pesos)[:, None]
        punto, _, rank, _ = np.linalg.lstsq(a, rhs * np.sqrt(pesos), rcond=None)
        if rank < 2:
            return None
        residuos = np.abs(normales @ punto - rhs)
        pesos = 1 / np.maximum(1., residuos / max(config["gps_uncertainty_m"], .1))
    if not np.all(np.isfinite(punto)):
        return None
    if any(not .1 < rango(o, punto) < config["max_range_m"] for o in observaciones):
        return None
    errores = [error_angular(o, punto) for o in observaciones]
    if max(errores) > config["max_reprojection_deg"]:
        return None
    condicion = float(np.linalg.cond(normales.T @ normales))
    if not math.isfinite(condicion) or condicion > 1e4:
        return None
    lateral = max(float(np.linalg.norm(punto - o["ray"]["origin_xy"])) *
                  math.tan(math.radians(min(o["ray"]["uncertainty_deg"], 80.))) for o in observaciones)
    incertidumbre = max(config["gps_uncertainty_m"], lateral / max(mejor_seno, .01), float(max(residuos)))
    return {"xy": punto.tolist(), "max_error_deg": max(errores),
            "mean_error_deg": float(np.mean(errores)), "uncertainty_m": incertidumbre,
            "parallax_deg": math.degrees(math.asin(min(mejor_seno, 1.))),
            "baseline_m": max_baseline, "condition_number": condicion,
            "method": "robust_bearing_intersection", "uncertainty_calibrated": False}
