"""Giro y traslación reversibles del visor, compatibles con ajustes anteriores."""

from copy import deepcopy
import math


def referencia_latitud(datos):
    origen = datos.get("survey", {}).get("origin")
    if isinstance(origen, (list, tuple)) and len(origen) >= 2:
        return float(origen[1])
    for nombre in ("cameras", "trees", "groups"):
        for feature in datos.get(nombre, []):
            g = feature.get("geometry") or {}
            if g.get("type") == "Point":
                return float(g["coordinates"][1])
    raise ValueError("No hay una latitud de referencia para desplazar el mapa.")


def metros_por_radian_longitud(latitud):
    if not math.isfinite(latitud) or abs(latitud) >= 90:
        raise ValueError("Latitud de referencia inválida para un ajuste horizontal.")
    phi = math.radians(latitud)
    e2 = 6.6943799901413165e-3
    return 6378137. / math.sqrt(1 - e2 * math.sin(phi) ** 2) * math.cos(phi)


def metros_por_radian_latitud(latitud):
    metros_por_radian_longitud(latitud)  # Misma validación del marco.
    phi = math.radians(latitud)
    e2 = 6.6943799901413165e-3
    return 6378137. * (1 - e2) / (1 - e2 * math.sin(phi) ** 2) ** 1.5


def offsets(datos):
    ajuste = datos.get("map_calibration") or datos.get("horizontal_calibration") or {}
    return ajuste.get("offset_east_m", 0.), ajuste.get("offset_north_m", 0.)


def calibracion(datos):
    ajuste = datos.get("map_calibration") or datos.get("horizontal_calibration") or {}
    return {**ajuste, "rotation_deg": ajuste.get("rotation_deg", 0.)}


def desplazar_datos(datos, metros, norte=0., rotacion_grados=None, camara_pivote=None):
    """Aplicar un offset absoluto; nunca acumularlo sobre una corrección previa.

    El marco local conserva su origen: los x e y locales se trasladan juntos.
    Con norte=0 y sin corrección norte previa se conserva la latitud exacta.
    La rotación positiva es horaria. Los píxeles, IDs y relaciones no cambian;
    los vectores y rumbos derivados giran con las geometrías.
    """
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (metros, norte)):
        raise ValueError("El desplazamiento debe ser un número finito en metros.")
    copia = deepcopy(datos)
    previa = calibracion(datos)
    angulo_previo = previa["rotation_deg"]
    angulo = angulo_previo if rotacion_grados is None else rotacion_grados
    if isinstance(angulo, bool) or not isinstance(angulo, (int, float)) or not math.isfinite(angulo):
        raise ValueError("La rotación debe ser un ángulo finito en grados.")
    angulo = (angulo + 180.) % 360. - 180.
    anterior, norte_anterior = offsets(datos)
    delta, delta_norte = metros - anterior, norte - norte_anterior
    if (delta == 0 and delta_norte == 0 and angulo == angulo_previo
            and (camara_pivote is None or camara_pivote == previa.get("pivot_camera_id"))):
        return copia
    lat = referencia_latitud(datos)
    total_grados = math.degrees(metros / metros_por_radian_longitud(lat))
    grados = math.degrees(delta / metros_por_radian_longitud(lat))
    grados_norte = math.degrees(delta_norte / metros_por_radian_latitud(lat))
    lon_ref = (datos.get("survey", {}).get("origin") or [None])[0]
    if lon_ref is None:
        lon_ref = next(f["geometry"]["coordinates"][0] for nombre in ("cameras", "trees", "groups")
                       for f in datos.get(nombre, []) if (f.get("geometry") or {}).get("type") == "Point")
    escala_e = metros_por_radian_longitud(lat) * math.pi / 180
    escala_n = metros_por_radian_latitud(lat) * math.pi / 180

    def girar(v, grados):
        a = math.radians(grados)
        c, s = math.cos(a), math.sin(a)
        return [c * v[0] + s * v[1], -s * v[0] + c * v[1]]

    def inversa(p, pivote):
        v = girar([p[0] - anterior - pivote[0], p[1] - norte_anterior - pivote[1]], -angulo_previo)
        return [v[0] + pivote[0], v[1] + pivote[1]]

    def plana(coord):
        return [(coord[0] - lon_ref) * escala_e, (coord[1] - lat) * escala_n]

    pivote_viejo = previa.get("pivot_xy", [0., 0.])
    pivote_geo_viejo = plana(previa.get("pivot_coordinates", [lon_ref, lat]))
    iid = camara_pivote if camara_pivote is not None else previa.get("pivot_camera_id")
    camaras = [f for f in datos.get("cameras", []) if (f.get("geometry") or {}).get("type") == "Point"]
    if iid is None and camaras:
        iid = str(camaras[0]["id"])
    camara = next((f for f in camaras if str(f["id"]) == str(iid)), None)
    if iid is not None and camara is None:
        raise ValueError("La cámara de referencia no existe en este relevamiento.")
    if camara:
        pivote_geo = inversa(plana(camara["geometry"]["coordinates"]), pivote_geo_viejo)
        pivote = inversa(camara["properties"].get("xy", plana(camara["geometry"]["coordinates"])), pivote_viejo)
    else:
        pivote, pivote_geo = [0., 0.], [0., 0.]
    pivot_coordinates = [lon_ref + pivote_geo[0] / escala_e, lat + pivote_geo[1] / escala_n]

    def punto_transformado(p, viejo, nuevo):
        raw = inversa(p, viejo)
        v = girar([raw[0] - nuevo[0], raw[1] - nuevo[1]], angulo)
        return [v[0] + nuevo[0] + metros, v[1] + nuevo[1] + norte]

    def coordenadas(valor):
        if not isinstance(valor, list):
            return valor
        if len(valor) >= 2 and all(isinstance(v, (int, float)) for v in valor[:2]):
            if angulo != 0 or angulo_previo != 0:
                v = punto_transformado(plana(valor), pivote_geo_viejo, pivote_geo)
                return [lon_ref + v[0] / escala_e, lat + v[1] / escala_n, *valor[2:]]
            return [valor[0] + grados, valor[1] + grados_norte, *valor[2:]]
        return [coordenadas(v) for v in valor]

    def transformar(valor):
        if isinstance(valor, list):
            return [transformar(v) for v in valor]
        if not isinstance(valor, dict):
            return valor
        resultado = {}
        for clave, v in valor.items():
            if clave in ("coordinates", "raw_coordinates"):
                resultado[clave] = coordenadas(v)
            elif clave in ("xy", "origin_xy", "camera_xy", "raw_xy") and isinstance(v, list) and len(v) == 2:
                resultado[clave] = punto_transformado(v, pivote_viejo, pivote)
            elif clave == "direction" and isinstance(v, list) and len(v) == 2:
                resultado[clave] = girar(v, angulo - angulo_previo)
            elif clave == "bearing_deg" and isinstance(v, (int, float)):
                resultado[clave] = (v + angulo - angulo_previo) % 360
            else:
                resultado[clave] = transformar(v)
        return resultado

    for nombre in ("trees", "cameras", "observations", "groups"):
        copia[nombre] = [transformar(f) for f in copia.get(nombre, [])]
    ajuste = {"offset_east_m": metros, "offset_north_m": norte, "reference_latitude": lat,
                                        "longitude_offset_deg": total_grados,
                                        "latitude_offset_deg": math.degrees(norte / metros_por_radian_latitud(lat)),
                                        "rotation_deg": angulo, "pivot_camera_id": iid,
                                        "pivot_xy": pivote, "pivot_coordinates": pivot_coordinates,
                                        "method": "rigid_rotation_translation"}
    copia["map_calibration"] = ajuste
    copia["horizontal_calibration"] = dict(ajuste)  # Compatibilidad con exportaciones anteriores.
    return copia
