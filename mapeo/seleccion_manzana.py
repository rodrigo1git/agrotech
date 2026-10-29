"""Resolver una manzana por cuatro calles y seleccionar cámaras de su perímetro."""

from itertools import product
import json
import math
import unicodedata
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .camaras import MarcoLocal


CENTRO = [-59.140568025911875, -37.33521401053581]  # Zona de la prueba anterior, no esquinas supuestas.
CALLES = ["Constitución", "Avenida Rivadavia", "25 de Mayo", "Alberdi"]
PATRONES = ["constituci", "rivadavia", "25 de mayo", "alberdi"]
CONSULTA = ('[out:json][timeout:25];way(around:1200,-37.33521401053581,-59.140568025911875)'
            '["highway"]["name"~"Constituci|Rivadavia|25 de Mayo|Alberdi",i];out geom;')


def consultar_calles():
    """Consulta pública de geometrías; nunca recibe el token de Mapillary."""
    for base in ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]:
        peticion = Request(base, data=urlencode({"data": CONSULTA}).encode(),
                           headers={"User-Agent": "agrotech-block-selector/1.0", "Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urlopen(peticion, timeout=35) as respuesta:
                datos = json.loads(respuesta.read(8 * 1024 * 1024))
            if datos.get("remark") or not isinstance(datos.get("elements"), list):
                raise ValueError("El servicio de calles devolvió una respuesta incompleta.")
            return datos
        except (OSError, URLError, ValueError):
            continue
    raise ValueError("No se pudieron consultar las calles de Tandil. Revisá la conexión a Internet y volvé a ejecutar.")


def cruz(a, b):
    return a[0] * b[1] - a[1] * b[0]


def resta(a, b):
    return [a[0] - b[0], a[1] - b[1]]


def interseccion(a, b, c, d):
    u, v = resta(b, a), resta(d, c)
    den = cruz(u, v)
    if abs(den) < 1e-8:
        return None
    t, s = cruz(resta(c, a), v) / den, cruz(resta(c, a), u) / den
    if -1e-7 <= t <= 1 + 1e-7 and -1e-7 <= s <= 1 + 1e-7:
        return [a[0] + t * u[0], a[1] + t * u[1]]
    return None


def resolver_manzana(datos, centro=CENTRO):
    marco = MarcoLocal(*centro)
    segmentos = [[] for _ in CALLES]
    for way in datos.get("elements", []):
        nombre = way.get("tags", {}).get("name", "")
        normal = "".join(c for c in unicodedata.normalize("NFKD", nombre.lower()) if not unicodedata.combining(c))
        for i, patron in enumerate(PATRONES):
            if patron not in normal:
                continue
            puntos = [marco.proyectar(p["lon"], p["lat"]) for p in way.get("geometry", [])]
            segmentos[i].extend(zip(puntos, puntos[1:]))
    faltan = [c for c, s in zip(CALLES, segmentos) if not s]
    if faltan:
        raise ValueError("No se encontró geometría de: " + ", ".join(faltan))
    esquinas = []
    for i in range(4):
        puntos = []
        for a, b in segmentos[i]:
            for c, d in segmentos[(i + 1) % 4]:
                p = interseccion(a, b, c, d)
                if p is not None and not any(math.dist(p, q) < .5 for q in puntos):
                    puntos.append(p)
        if not puntos:
            raise ValueError(f"No se encontró el cruce entre {CALLES[i]} y {CALLES[(i + 1) % 4]}.")
        esquinas.append(puntos)
    if math.prod(len(e) for e in esquinas) > 10000:
        raise ValueError("Las calles producen demasiadas alternativas; revisá las geometrías.")
    candidatos = []
    for puntos in product(*esquinas):
        giros = [cruz(resta(puntos[(i + 1) % 4], puntos[i]), resta(puntos[(i + 2) % 4], puntos[(i + 1) % 4])) for i in range(4)]
        area = abs(sum(cruz(puntos[i], puntos[(i + 1) % 4]) for i in range(4))) / 2
        if not (all(g > .01 for g in giros) or all(g < -.01 for g in giros)):
            continue
        if 1000 <= area <= 100000 and max(math.hypot(*p) for p in puntos) <= 1200:
            candidatos.append((area, puntos))
    if not candidatos:
        raise ValueError("Los cruces no forman una manzana válida y acotada. No se descargan imágenes de una zona supuesta.")
    area, puntos = min(candidatos, key=lambda c: c[0])
    anillo = [marco.geografica(*p) for p in puntos]
    return {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [anillo + [anillo[0]]]},
            "properties": {"city": "Tandil", "streets": CALLES, "edge_streets": CALLES[1:] + CALLES[:1],
                           "area_m2": area, "origin": centro, "xy": list(puntos),
                           "source": "OpenStreetMap via Overpass", "attribution": "© OpenStreetMap contributors",
                           "query": CONSULTA, "corner_alternatives": len(candidatos)}}


def distancia_segmento(p, a, b):
    d = resta(b, a)
    largo2 = d[0] ** 2 + d[1] ** 2
    t = min(1., max(0., sum(x * y for x, y in zip(resta(p, a), d)) / largo2)) if largo2 else 0.
    return math.dist(p, [a[0] + t * d[0], a[1] + t * d[1]])


def seleccion_captura(datos, zona, margen):
    marco = MarcoLocal(*zona["properties"]["origin"])
    vertices = zona["properties"]["xy"]
    opciones = []
    for campo in ("computed_geometry", "geometry"):
        g = datos.get(campo) or {}
        c = g.get("coordinates", [])
        if (g.get("type") != "Point" or not isinstance(c, (list, tuple)) or len(c) < 2
                or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in c[:2])
                or not -180 <= c[0] <= 180 or not -90 <= c[1] <= 90):
            continue
        p = marco.proyectar(*c[:2])
        for i in range(4):
            opciones.append((distancia_segmento(p, vertices[i], vertices[(i + 1) % 4]), i, campo))
    if not opciones:
        return None
    distancia, i, campo = min(opciones)
    return {"street": zona["properties"]["edge_streets"][i], "distance_to_perimeter_m": distancia,
            "position_source": campo} if distancia <= margen else None


def bbox_consulta(zona, margen):
    marco = MarcoLocal(*zona["properties"]["origin"])
    puntos = zona["properties"]["xy"]
    xs, ys = [p[0] for p in puntos], [p[1] for p in puntos]
    esquinas = [marco.geografica(x, y) for x in (min(xs) - margen, max(xs) + margen)
                for y in (min(ys) - margen, max(ys) + margen)]
    return [min(p[0] for p in esquinas), min(p[1] for p in esquinas),
            max(p[0] for p in esquinas), max(p[1] for p in esquinas)]
