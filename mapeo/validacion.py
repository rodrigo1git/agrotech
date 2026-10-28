"""Métricas de identidad con correspondencias anotadas, sin nearest-neighbor."""

import json
import math
from pathlib import Path
from mapillary_arboles import escribir_json
from .camaras import MarcoLocal


def evaluar(inventario_path, referencia_path, salida):
    inv = json.loads(Path(inventario_path).read_text(encoding="utf-8"))
    ref = json.loads(Path(referencia_path).read_text(encoding="utf-8"))
    verdad = {(str(o["image_id"]), o["detection_index"]): o["tree_id"] for o in ref["observations"]}
    obs = {o["id"]: o for o in inv["observations"]}
    asociaciones = {}
    activos = [a for a in inv["trees"] if a.get("active", True) and a["identity_status"] == "confirmed"]
    for a in activos:
        asociaciones[a["id"]] = sorted({verdad[(obs[oid]["image_id"], obs[oid]["detection_index"])] for oid in a["observation_ids"] if oid in obs and (obs[oid]["image_id"], obs[oid]["detection_index"]) in verdad})
    por_real = {}
    for aid, reales in asociaciones.items():
        for real in reales:
            por_real.setdefault(real, []).append(aid)
    marco = MarcoLocal(*inv["survey"]["origin"]) if inv["survey"]["origin"] else None
    errores = []
    for real in ref["trees"]:
        asignados = por_real.get(real["id"], [])
        if len(asignados) != 1 or asociaciones[asignados[0]] != [real["id"]] or not marco:
            continue
        arbol = next(a for a in activos if a["id"] == asignados[0])
        if arbol.get("fit") and real.get("coordinates"):
            punto = marco.proyectar(*real["coordinates"])
            error = math.dist(punto, arbol["fit"]["xy"])
            errores.append({"tree_id": arbol["id"], "reference_id": real["id"], "error_m": error})
    resultado = {"synthetic": bool(ref.get("synthetic")), "reference_trees": len(ref["trees"]),
                 "confirmed_trees": len(activos), "false_merges": sum(len(v) > 1 for v in asociaciones.values()),
                 "false_splits": sum(len(v) > 1 for v in por_real.values()),
                 "unmatched_reference_trees": [r["id"] for r in ref["trees"] if r["id"] not in por_real],
                 "unmatched_inventory_trees": [aid for aid, reales in asociaciones.items() if not reales],
                 "location_errors_for_unambiguous_matches": errores,
                 "mean_location_error_m": sum(e["error_m"] for e in errores) / len(errores) if errores else None,
                 "note": "Las correspondencias provienen de la referencia manual/sintética; no se asigna por vecino más cercano."}
    escribir_json(Path(salida), resultado)
    return resultado
