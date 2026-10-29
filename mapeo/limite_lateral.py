"""Acotar posiciones exploratorias respecto al recorrido, sin datos de calles."""

from datetime import datetime, timezone
import math
import numpy as np

from .camaras import MarcoLocal, posicion, rotacion_camara


CONFIG_LATERAL = {"allow_lateral_limit": True, "approx_max_lateral_distance_m": 6.0}


def ejes_de_camaras(capturas, marco, config):
    """Tangente local de la secuencia; con una cámara, rumbo óptico supuesto.

    No unir secuencias ni años distintos. Usar vecinos temporales próximos
    evita prolongar una única recta a lo largo de recorridos con curvas.
    """
    if marco is None:
        return {}
    grupos, posiciones = {}, {}
    for iid, meta in capturas.items():
        try:
            lon, lat, _ = posicion(meta)
            xy = np.asarray(marco.proyectar(lon, lat))
            if np.linalg.norm(xy) > config["max_survey_extent_m"]:
                continue
            posiciones[iid] = xy
            fecha = meta.get("captured_at")
            if meta.get("sequence") and fecha is not None:
                ano = datetime.fromtimestamp(fecha / 1000, timezone.utc).year
                grupos.setdefault((meta["sequence"], ano), []).append((fecha, iid))
        except (ValueError, KeyError, TypeError, OverflowError):
            continue
    ejes = {}
    for registros in grupos.values():
        registros.sort()
        for i, (fecha, iid) in enumerate(registros):
            def vecino(indices):
                for j in indices:
                    otra_fecha, otro_id = registros[j]
                    distancia = float(np.linalg.norm(posiciones[otro_id] - posiciones[iid]))
                    if abs(fecha - otra_fecha) > config["max_time_gap_days"] * 86400000:
                        break
                    if distancia > config["max_camera_distance_m"]:
                        break
                    if distancia >= config["min_baseline_m"]:
                        return otro_id
                return None
            anterior = vecino(range(i - 1, -1, -1))
            siguiente = vecino(range(i + 1, len(registros)))
            ids = [c for c in (anterior, iid, siguiente) if c is not None]
            if len(ids) < 2:
                continue
            delta = posiciones[ids[-1]] - posiciones[ids[0]]
            largo = float(np.linalg.norm(delta))
            if largo < config["min_baseline_m"]:
                continue
            ejes[iid] = {"origin_xy": posiciones[iid].tolist(), "direction": (delta / largo).tolist(),
                         "source": "capture_trajectory", "reference_image_ids": ids}
    for iid, xy in posiciones.items():
        if iid in ejes:
            continue
        try:
            meta = capturas[iid]
            lon, lat, _ = posicion(meta)
            rotacion, _ = rotacion_camara(meta, config)
            rayo = marco.rotation @ MarcoLocal(lon, lat).rotation.T @ rotacion @ np.array([0., 0., 1.])
            largo = float(np.linalg.norm(rayo[:2]))
            if largo < .05:
                continue
            ejes[iid] = {"origin_xy": xy.tolist(), "direction": (rayo[:2] / largo).tolist(),
                         "source": "camera_heading_assumed_travel_direction", "reference_image_ids": [iid]}
        except (ValueError, KeyError, TypeError, OverflowError):
            continue
    return ejes


def limitar_posicion(punto, ejes, marco, config):
    """Acercar por el mismo rayo hasta cumplir |desplazamiento lateral| <= X.

    El límite es perpendicular al avance de la cámara, no un radio de X metros.
    Conserva el lado y la dirección de observación. No reduce la incertidumbre.
    """
    cfg = {**CONFIG_LATERAL, **config}
    if (not punto or not punto.get("is_approximate") or not cfg["allow_lateral_limit"]
            or marco is None):
        return punto
    # Si ya fue limitado, recalcular desde el punto original y no encadenar recortes.
    previo = punto.get("lateral_constraint")
    original_xy = previo["raw_xy"] if previo else punto["xy"]
    iid = next((i for i in punto.get("source_image_ids", []) if i in ejes), None)
    if iid is None:
        return {**punto, "warnings": list(dict.fromkeys([*punto.get("warnings", []), "lateral_reference_unavailable"]))}
    eje = ejes[iid]
    origen, direccion = np.asarray(eje["origin_xy"]), np.asarray(eje["direction"])
    normal = np.array([-direccion[1], direccion[0]])
    delta = np.asarray(original_xy) - origen
    lateral = float(np.dot(delta, normal))
    adelante = float(np.dot(delta, direccion))
    limite = float(cfg["approx_max_lateral_distance_m"])
    if not math.isfinite(limite) or limite <= 0:
        raise ValueError("approx_max_lateral_distance_m debe ser positivo y finito")
    factor = min(1., limite / abs(lateral)) if abs(lateral) > 1e-10 else 1.
    ajustado = origen + delta * factor
    desplazamiento = float(np.linalg.norm(np.asarray(original_xy) - ajustado))
    cambio = factor < 1. - 1e-12
    motivos = [m for m in punto.get("warnings", []) if m != "lateral_limit_applied"]
    if cambio:
        motivos.append("lateral_limit_applied")
    resultado = {**punto, "xy": ajustado.tolist(), "coordinates": marco.geografica(*ajustado),
                 "distance_m": float(np.linalg.norm(ajustado - origen)),
                 "warnings": list(dict.fromkeys(motivos)),
                 "lateral_constraint": {"applied": cambio, "max_distance_m": limite,
                                        "raw_xy": list(original_xy), "raw_coordinates": marco.geografica(*original_xy),
                                        "camera_image_id": iid, "axis": eje,
                                        "lateral_before_m": lateral, "lateral_after_m": lateral * factor,
                                        "forward_before_m": adelante, "forward_after_m": adelante * factor,
                                        "adjustment_m": desplazamiento, "preserves_bearing": True}}
    if cambio:
        resultado["uncertainty_m"] = max(punto.get("uncertainty_m") or 0., desplazamiento)
    return resultado
