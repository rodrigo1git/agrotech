"""Asociación entre capturas: asignación uno a uno, alternativas y grupos."""

import math
import numpy as np
from .localizacion import ajustar, epocas_compatibles, error_angular, interseccion, rango


def asignacion(costos, costo_nuevo):
    """Asignación rectangular de costo mínimo con una salida nueva por fila.

    Implementación primal-dual; las columnas auxiliares permiten no asociar.
    No necesita instalar SciPy en el entorno del usuario.
    """
    n = len(costos)
    if not n:
        return []
    originales = len(costos[0])
    if any(len(fila) != originales for fila in costos):
        raise ValueError("Matriz de asociación irregular")
    matriz = [list(fila) + [float(costo_nuevo)] * n for fila in costos]
    m = originales + n
    u, v, p, way = [0.] * (n + 1), [0.] * (m + 1), [0] * (m + 1), [0] * (m + 1)
    for i in range(1, n + 1):
        p[0], j0 = i, 0
        minv, usados = [float("inf")] * (m + 1), [False] * (m + 1)
        while True:
            usados[j0] = True
            i0, delta, j1 = p[j0], float("inf"), 0
            for j in range(1, m + 1):
                if usados[j]:
                    continue
                cur = matriz[i0 - 1][j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j], way[j] = cur, j0
                if minv[j] < delta:
                    delta, j1 = minv[j], j
            for j in range(m + 1):
                if usados[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0], j0 = p[j1], j1
    salida = [None] * n
    for j in range(1, m + 1):
        if p[j] and j <= originales and matriz[p[j] - 1][j - 1] < costo_nuevo:
            salida[p[j] - 1] = j - 1
    return salida


def soporte(punto, observaciones, config, semilla):
    por_captura = {}
    for obs in observaciones:
        if not epocas_compatibles(obs, semilla, config) or not .1 < rango(obs, punto) < config["max_range_m"]:
            continue
        error = error_angular(obs, punto)
        if error > config["max_reprojection_deg"]:
            continue
        anterior = por_captura.get(obs["capture_id"])
        if anterior is None or (error, obs["id"]) < anterior[:2]:
            por_captura[obs["capture_id"]] = (error, obs["id"], obs)
    return [fila[2] for fila in sorted(por_captura.values(), key=lambda fila: fila[1])]


def proponer(observaciones, config):
    utiles = sorted([o for o in observaciones if o["role"] == "individual" and o["ray"].get("valid")], key=lambda o: o["id"])
    propuestas = {}
    for i, a in enumerate(utiles):
        for b in utiles[i + 1:]:
            punto = interseccion(a, b, config)
            if punto is None:
                continue
            miembros = soporte(punto, utiles, config, a)
            fit = ajustar(miembros, config)
            if fit is None:
                continue
            miembros = soporte(fit["xy"], utiles, config, a)
            fit = ajustar(miembros, config)
            if fit is None:
                continue
            clave = tuple(sorted(o["id"] for o in miembros))
            propuesta = {"observations": miembros, "fit": fit}
            anterior = propuestas.get(clave)
            if anterior is None or fit["mean_error_deg"] < anterior["fit"]["mean_error_deg"]:
                propuestas[clave] = propuesta
    return sorted(propuestas.values(), key=lambda p: (-len(p["observations"]), p["fit"]["mean_error_deg"], tuple(o["id"] for o in p["observations"])))


def construir_hipotesis(observaciones, config):
    propuestas = proponer(observaciones, config)
    usados, arboles, ambiguos = set(), [], []
    for indice, propuesta in enumerate(propuestas):
        miembros = propuesta["observations"]
        ids = {o["id"] for o in miembros}
        if ids & usados:
            continue
        alternativas = []
        for otra in propuestas[indice + 1:]:
            otros = {o["id"] for o in otra["observations"]}
            if otros & usados or len(otros) != len(ids) or not (otros & ids) or otros == ids:
                continue
            if abs(otra["fit"]["mean_error_deg"] - propuesta["fit"]["mean_error_deg"]) <= config["ambiguity_margin"]:
                alternativas.append(otra)
        if alternativas:
            conjunto = set(ids)
            for otra in alternativas:
                conjunto.update(o["id"] for o in otra["observations"])
            usados.update(conjunto)
            ambiguos.append({"observation_ids": sorted(conjunto), "reason": "competing_correspondences",
                             "alternatives": [{"xy": p["fit"]["xy"], "observation_ids": sorted(o["id"] for o in p["observations"])} for p in [propuesta] + alternativas]})
            continue
        usados.update(ids)
        fit = propuesta["fit"]
        fiable = (len({o["capture_id"] for o in miembros}) >= config["min_views_confirm"]
                  and all(o["ray"]["anchor_verified"] for o in miembros)
                  and all(o["ray"]["pose_source"] == "computed_rotation" for o in miembros)
                  and fit["uncertainty_m"] <= config["max_position_uncertainty_m"]
                  and miembros[0]["epoch"] != "unknown")
        arboles.append({"observation_ids": sorted(ids), "fit": fit,
                        "identity_status": "confirmed" if fiable else "candidate",
                        "position_status": "estimated" if fit["uncertainty_m"] <= config["max_position_uncertainty_m"] else "needs_review",
                        "epoch": miembros[0]["epoch"],
                        "review_reason": None if fiable else "Requires verified anchors or manual identity review"})
    for obs in observaciones:
        if obs["id"] not in usados and obs["role"] == "individual":
            arboles.append({"observation_ids": [obs["id"]], "fit": None, "identity_status": "candidate",
                            "position_status": "unlocated", "epoch": obs["epoch"],
                            "review_reason": obs["ray"].get("reason", "Insufficient distinct viewpoints")})
    return arboles, ambiguos
