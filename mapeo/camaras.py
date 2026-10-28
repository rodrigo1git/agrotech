"""Desproyección OpenSfM y coordenadas locales WGS84, sin FOV inventado."""

import math
import numpy as np


def diferencia_angular(a, b):
    return (a - b + 180.0) % 360.0 - 180.0


def rodrigues(vector):
    vector = np.asarray(vector, dtype=float)
    if vector.shape != (3,) or not np.all(np.isfinite(vector)):
        raise ValueError("Rotación de cámara inválida")
    theta = float(np.linalg.norm(vector))
    if theta < 1e-12:
        return np.eye(3)
    x, y, z = vector / theta
    k = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])
    return np.eye(3) + math.sin(theta) * k + (1 - math.cos(theta)) * (k @ k)


def posicion(metadata):
    for campo in ("computed_geometry", "geometry"):
        g = metadata.get(campo)
        if not isinstance(g, dict) or g.get("type") != "Point":
            continue
        c = g.get("coordinates")
        if (isinstance(c, (list, tuple)) and len(c) >= 2
                and all(isinstance(v, (int, float)) and math.isfinite(v) for v in c[:2])
                and -180 <= c[0] <= 180 and -90 <= c[1] <= 90):
            return float(c[0]), float(c[1]), campo
    raise ValueError("Captura sin posición válida")


class MarcoLocal:
    """Plano ENU sobre WGS84. Inversa por intersección con el elipsoide.

    Se limita explícitamente la extensión del relevamiento: no es una
    proyección cartográfica para ciudades completas ni una precisión GPS.
    """
    a = 6378137.0
    b = 6356752.314245179

    def __init__(self, lon, lat):
        self.lon, self.lat = float(lon), float(lat)
        phi, lam = math.radians(lat), math.radians(lon)
        self.rotation = np.array([
            [-math.sin(lam), math.cos(lam), 0],
            [-math.sin(phi) * math.cos(lam), -math.sin(phi) * math.sin(lam), math.cos(phi)],
            [math.cos(phi) * math.cos(lam), math.cos(phi) * math.sin(lam), math.sin(phi)],
        ])
        self.origin = self.ecef(lon, lat)

    @classmethod
    def ecef(cls, lon, lat):
        phi, lam = math.radians(lat), math.radians(lon)
        e2 = 1 - cls.b ** 2 / cls.a ** 2
        n = cls.a / math.sqrt(1 - e2 * math.sin(phi) ** 2)
        return np.array([n * math.cos(phi) * math.cos(lam),
                         n * math.cos(phi) * math.sin(lam),
                         n * (1 - e2) * math.sin(phi)])

    def proyectar(self, lon, lat):
        return (self.rotation @ (self.ecef(lon, lat) - self.origin))[:2].tolist()

    def geografica(self, x, y):
        p = self.origin + self.rotation.T @ np.array([x, y, 0.0])
        up = self.rotation[2]
        escala = np.array([1 / self.a ** 2, 1 / self.a ** 2, 1 / self.b ** 2])
        aa = float(np.sum(up * up * escala))
        bb = float(2 * np.sum(p * up * escala))
        cc = float(np.sum(p * p * escala) - 1)
        discriminante = bb * bb - 4 * aa * cc
        if discriminante < 0:
            raise ValueError("Punto fuera del marco local")
        z = -2 * cc / (bb + math.sqrt(discriminante))
        px, py, pz = p + up * z
        lon = math.degrees(math.atan2(py, px))
        lat = math.degrees(math.atan2(pz * self.a ** 2, math.hypot(px, py) * self.b ** 2))
        return [lon, lat]


def rotacion_camara(meta, config):
    heading = meta.get("computed_compass_angle")
    if heading is None:
        heading = meta.get("compass_angle")
    if meta.get("computed_rotation") is not None:
        camera_to_world = rodrigues(meta["computed_rotation"]).T
        centro = camera_to_world @ np.array([0., 0., 1.])
        if math.hypot(centro[0], centro[1]) < .05:
            raise ValueError("Cámara casi vertical: rumbo horizontal inestable")
        rumbo = math.degrees(math.atan2(centro[0], centro[1])) % 360
        if heading is not None and abs(diferencia_angular(rumbo, heading)) > config["pose_heading_tolerance_deg"]:
            raise ValueError("La rotación y el heading de la cámara no coinciden")
        return camera_to_world, "computed_rotation"
    if heading is None or not math.isfinite(float(heading)) or not config["allow_heading_only"]:
        raise ValueError("Falta pose completa; heading solo no habilitado")
    h = math.radians(heading)
    return np.array([[math.cos(h), 0, math.sin(h)],
                     [-math.sin(h), 0, math.cos(h)], [0, -1, 0]]), "heading_only_assumed_level"


def rayo_pixel(u, v, width, height, meta, config):
    tipo = meta.get("camera_type")
    if meta.get("pixel_transform") is not None:
        transform = np.asarray(meta["pixel_transform"], dtype=float)
        if transform.shape != (3, 3) or not np.all(np.isfinite(transform)):
            raise ValueError("pixel_transform debe ser una matriz 3x3 finita")
        p = transform @ np.array([u, v, 1.])
        if abs(p[2]) < 1e-12:
            raise ValueError("Transformación de píxel singular")
        u, v = p[:2] / p[2]
        width, height = meta["width"], meta["height"]
    else:
        if meta.get("exif_orientation", 1) not in (None, 1):
            raise ValueError("Orientación EXIF no verificada: falta pixel_transform")
        if meta.get("width") and meta.get("height"):
            if abs((width / height) / (meta["width"] / meta["height"]) - 1) > .01:
                raise ValueError("La imagen fue recortada o rotada sin transformación registrada")
    if tipo == "perspective":
        params = meta.get("camera_parameters")
        if not isinstance(params, (list, tuple)) or len(params) < 3:
            raise ValueError("Falta calibración [focal, k1, k2]")
        focal, k1, k2 = map(float, params[:3])
        if not all(math.isfinite(x) for x in (focal, k1, k2)) or focal <= 0:
            raise ValueError("Calibración inválida")
        xd, yd = (u - (width - 1) / 2) / (focal * max(width, height)), (v - (height - 1) / 2) / (focal * max(width, height))
        x, y = xd, yd
        for _ in range(30):
            r2 = x * x + y * y
            factor = 1 + k1 * r2 + k2 * r2 * r2
            if factor <= .01 or not math.isfinite(factor):
                raise ValueError("Distorsión no invertible")
            nx, ny = xd / factor, yd / factor
            if abs(nx - x) + abs(ny - y) < 1e-12:
                x, y = nx, ny
                break
            x, y = nx, ny
        r2 = x * x + y * y
        if math.hypot(x * (1 + k1 * r2 + k2 * r2 ** 2) - xd,
                      y * (1 + k1 * r2 + k2 * r2 ** 2) - yd) > 1e-7:
            raise ValueError("La inversión de la distorsión no convergió")
        ray = np.array([x, y, 1.])
    elif tipo in ("spherical", "equirectangular"):
        if not config["allow_spherical"] or abs(width / height - 2) > .02:
            raise ValueError("Panorama no validado/habilitado o incompleto")
        lon = (u / width - .5) * 2 * math.pi
        lat = (.5 - v / height) * math.pi
        ray = np.array([math.cos(lat) * math.sin(lon), -math.sin(lat), math.cos(lat) * math.cos(lon)])
    else:
        raise ValueError(f"Tipo de cámara no soportado: {tipo}")
    return ray / np.linalg.norm(ray)


def proyectar_observacion(obs, meta, marco, config):
    """Un centro de caja es aproximado; un ancla verificada tiene otra calidad."""
    try:
        lon, lat, origen = posicion(meta)
        centro = marco.proyectar(lon, lat)
        if math.hypot(*centro) > config["max_survey_extent_m"]:
            raise ValueError("Captura fuera de la extensión máxima del relevamiento")
        rotacion, pose_source = rotacion_camara(meta, config)
        # La pose se expresa en ENU de la captura; trasladar ejes al marco elegido.
        rotacion = marco.rotation @ MarcoLocal(lon, lat).rotation.T @ rotacion
        width, height = obs["width"], obs["height"]
        x1, y1, x2, y2 = obs["bbox_xyxy"]
        anchor = obs.get("anchor")
        verified = bool(anchor and anchor.get("verified"))
        if anchor:
            u, v = map(float, anchor["pixel"])
            if not (0 <= u < width and 0 <= v < height):
                raise ValueError("Ancla fuera de la imagen")
        else:
            u, v = (x1 + x2) / 2, (y1 + y2) / 2

        def bearing(px, py):
            ray = rotacion @ rayo_pixel(px, py, width, height, meta, config)
            if math.hypot(ray[0], ray[1]) < .05:
                raise ValueError("Dirección casi vertical")
            return math.degrees(math.atan2(ray[0], ray[1])) % 360

        azimut = bearing(u, v)
        borde = max(abs(diferencia_angular(bearing(x, y), azimut))
                    for x, y in ((x1, y1), (x1, y2), (x2, y1), (x2, y2)))
        sigma = float(anchor.get("uncertainty_deg", config["angular_floor_deg"])) if verified else max(config["angular_floor_deg"], borde)
        if not math.isfinite(sigma) or sigma <= 0:
            raise ValueError("Incertidumbre angular inválida")
        angulo = math.radians(azimut)
        return {"valid": True, "origin_xy": centro, "bearing_deg": azimut,
                "direction": [math.sin(angulo), math.cos(angulo)],
                "half_width_deg": borde, "uncertainty_deg": sigma,
                "anchor_verified": verified, "position_source": origen,
                "pose_source": pose_source, "method": "verified_anchor" if verified else "bbox_center_approximation"}
    except (ValueError, KeyError, TypeError, OverflowError, np.linalg.LinAlgError) as error:
        return {"valid": False, "reason": str(error), "anchor_verified": False}
