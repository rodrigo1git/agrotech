"""Posiciones exploratorias por cámara y caja, independientes de la identidad.

Las hipótesis de altura/suelo se exportan junto al punto. Estas posiciones nunca
se usan como evidencia para confirmar o fusionar árboles en el inventario.
"""

import math
import numpy as np

from .camaras import MarcoLocal, posicion, rayo_pixel, rotacion_camara
from .localizacion import ajustar
from .limite_lateral import CONFIG_LATERAL


DEFAULTS = {
    **CONFIG_LATERAL,
    "allow_approximate_positions": True,
    "approx_camera_height_m": 1.7,
    "approx_tree_height_m": 8.0,
    "approx_default_distance_m": 15.0,
    "approx_min_range_m": 2.0,
    "approx_min_ground_angle_deg": 2.0,
    "approx_uncertainty_floor_m": 5.0,
    "approx_relative_uncertainty": 0.6,
}


def estimar_observacion(obs, meta, marco, config):
    """Intersectar el rayo del pie de caja con z=-altura de cámara.

    Si el pie queda cerca del horizonte o recortado, usar la altura aparente
    suponiendo un árbol vertical. Último recurso: distancia explícitamente
    supuesta sobre el rayo. Ningún valor es una profundidad medida.
    """
    cfg = {**DEFAULTS, **config}
    if (not cfg["allow_approximate_positions"] or marco is None
            or obs.get("role") in ("duplicate", "rejected")
            or not obs.get("ray", {}).get("valid")):
        return None
    try:
        lon, lat, fuente = posicion(meta)
        origen = np.asarray(marco.proyectar(lon, lat))
        if np.linalg.norm(origen) > cfg["max_survey_extent_m"]:
            return None
        rotacion, pose = rotacion_camara(meta, cfg)
        rotacion = marco.rotation @ MarcoLocal(lon, lat).rotation.T @ rotacion
        width, height = obs["width"], obs["height"]
        x1, y1, x2, y2 = obs["bbox_xyxy"]
        u = (x1 + x2) / 2
        pie = [u, min(y2, height - 1.)]

        def direccion(pixel):
            return rotacion @ rayo_pixel(*pixel, width, height, meta, cfg)

        inferior, superior = direccion(pie), direccion([u, max(0., y1)])
        horizontal = float(np.linalg.norm(inferior[:2]))
        if horizontal < .05:
            return None
        rumbo = inferior[:2] / horizontal
        depresion = math.degrees(math.atan2(-inferior[2], horizontal))
        h = cfg["approx_camera_height_m"]
        minimo, maximo = cfg["approx_min_range_m"], cfg["max_range_m"]
        suelo = h * horizontal / -inferior[2] if inferior[2] < -1e-8 else None
        inferior_recortado = y2 >= height - 2
        superior_recortado = y1 <= 2
        supuestos = {"camera_height_m": h, "camera_height_is_assumed": True,
                     "bbox_bottom_is_trunk_base_assumed": True, "flat_ground_assumed": True}
        motivos = []
        raw_distance = None
        if (not inferior_recortado and depresion >= cfg["approx_min_ground_angle_deg"]
                and suelo is not None and minimo <= suelo <= maximo):
            distancia, metodo = suelo, "bbox_ground_plane"
        else:
            motivos.append("bbox_bottom_clipped" if inferior_recortado else "ground_intersection_unstable_or_out_of_range")
            supuestos = {}
            altura_angular = superior[2] / max(float(np.linalg.norm(superior[:2])), .05) - inferior[2] / horizontal
            if (obs.get("role") == "individual" and not inferior_recortado and not superior_recortado
                    and altura_angular > 1e-6):
                raw_distance = cfg["approx_tree_height_m"] / altura_angular
                distancia = min(maximo, max(minimo, raw_distance))
                metodo = "bbox_assumed_tree_height"
                supuestos = {"tree_height_m": cfg["approx_tree_height_m"],
                             "tree_height_is_assumed": True, "bbox_contains_full_tree_assumed": True,
                             "vertical_tree_assumed": True}
                if distancia != raw_distance:
                    motivos.append("distance_clamped_to_configured_range")
            else:
                distancia = min(maximo, max(minimo, cfg["approx_default_distance_m"]))
                metodo = "assumed_distance_along_ray"
                motivos.append("bbox_group_or_incomplete_extent")
                supuestos = {"distance_m": distancia, "distance_is_assumed": True}
        # Las cajas anchas y el tamaño/altura supuestos amplían el error heurístico.
        lateral = distancia * math.tan(math.radians(min(60., obs["ray"].get("half_width_deg", 10.))))
        incertidumbre = max(cfg["gps_uncertainty_m"], cfg["approx_uncertainty_floor_m"],
                            distancia * cfg["approx_relative_uncertainty"], lateral)
        if metodo == "assumed_distance_along_ray" or "distance_clamped_to_configured_range" in motivos:
            incertidumbre = max(incertidumbre, distancia)
        punto = origen + distancia * rumbo
        return {"xy": punto.tolist(), "coordinates": marco.geografica(*punto),
                "method": metodo, "is_approximate": True, "used_for_identity": False,
                "uncertainty_m": incertidumbre, "uncertainty_calibrated": False,
                "distance_m": distancia, "unclamped_distance_m": raw_distance,
                "source_observation_ids": [obs["id"]], "source_image_ids": [obs["image_id"]],
                "source_pixel": pie, "camera_xy": origen.tolist(), "position_source": fuente,
                "pose_source": pose, "assumptions": supuestos, "warnings": motivos}
    except (ValueError, KeyError, TypeError, OverflowError, np.linalg.LinAlgError):
        return None


def estimar_entidad(entidad, por_id, capturas, marco, config, grupo=False):
    """Preferir posiciones del inventario; aproximar solo las que aún faltan."""
    if marco is None:
        return None
    fit = entidad.get("fit")
    if fit:
        return {**fit, "coordinates": marco.geografica(*fit["xy"]), "is_approximate": False,
                "used_for_identity": True, "assumptions": {},
                "source_observation_ids": entidad.get("observation_ids", [])}
    cfg = {**DEFAULTS, **config}
    if not cfg["allow_approximate_positions"] or (grupo and entidad.get("status") == "resolved"):
        return None
    observaciones = [por_id[oid] for oid in entidad.get("observation_ids", []) if oid in por_id
                     and por_id[oid].get("ray", {}).get("valid")
                     and por_id[oid].get("role") not in ("duplicate", "rejected")]
    # Solo evidencia ya asociada a esta identidad. No adivinar correspondencias
    # entre árboles distintos ni triangular dos capturas de épocas diferentes.
    if not grupo and len({o["capture_id"] for o in observaciones}) >= 2:
        from .localizacion import epocas_compatibles
        if all(epocas_compatibles(a, b, cfg) for a in observaciones for b in observaciones):
            relajada = {**cfg, "min_parallax_deg": min(cfg["min_parallax_deg"], 2.),
                        "max_reprojection_deg": max(cfg["max_reprojection_deg"], 5.)}
            fit = ajustar(observaciones, relajada)
            if fit:
                return {**fit, "method": "approximate_bearing_triangulation", "is_approximate": True,
                        "coordinates": marco.geografica(*fit["xy"]), "used_for_identity": False,
                        "source_observation_ids": [o["id"] for o in observaciones],
                        "source_image_ids": [o["image_id"] for o in observaciones],
                        "assumptions": {"bbox_centers_correspond_assumed": True}, "warnings": []}
    candidatos = [p for obs in observaciones
                  if (p := estimar_observacion(obs, capturas.get(obs["image_id"], {}), marco, cfg))]
    if not candidatos:
        return None
    prioridad = {"bbox_ground_plane": 0, "bbox_assumed_tree_height": 1, "assumed_distance_along_ray": 2}
    # No promediar posiciones incompatibles ni duplicar el ID por cada imagen.
    return min(candidatos, key=lambda p: (prioridad[p["method"]], p["uncertainty_m"], p["source_observation_ids"]))
