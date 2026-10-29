"""Identidades persistentes, reconciliación y correcciones auditables."""

import json
import math

from .asociacion import asignacion, construir_hipotesis
from .camaras import MarcoLocal, posicion
from .localizacion import ajustar, error_angular, rango
from .observaciones import identificador, iou, preparar_observaciones


def marco_relevamiento(almacen, survey, capturas):
    if survey["origin"] is None:
        for meta in sorted(capturas.values(), key=lambda m: (m.get("captured_at") or 0, str(m["id"]))):
            try:
                lon, lat, _ = posicion(meta)
                survey["origin"] = [lon, lat]
                almacen.guardar_survey(survey)
                break
            except ValueError:
                continue
    return MarcoLocal(*survey["origin"]) if survey["origin"] else None


def observaciones_actuales(almacen, survey, config):
    capturas = almacen.capturas(survey["id"])
    marco = marco_relevamiento(almacen, survey, capturas)
    crudas = almacen.observaciones(survey["id"])
    previas = almacen.estado(survey["id"]).get("observations", [])
    for image_id in {o["image_id"] for o in crudas}:
        nuevas = [o for o in crudas if o["image_id"] == image_id]
        viejas = [o for o in previas if o["image_id"] == image_id]
        costos = [[1 - iou(n["bbox_xyxy"], v["bbox_xyxy"]) if (n["width"], n["height"]) == (v["width"], v["height"]) else 1000. for v in viejas] for n in nuevas]
        limite = 1 - config.get("lineage_iou", .9)
        for fila, (nueva, columna) in enumerate(zip(nuevas, asignacion(costos, limite))):
            exacta = next((i for i, previa in enumerate(viejas) if previa["id"] == nueva["id"]), None)
            if exacta is not None:
                columna = exacta
            if columna is None:
                continue
            if exacta is None:
                elegido = costos[fila][columna]
                alternativas = [c for j, c in enumerate(costos[fila]) if j != columna and c < limite]
                competidores = [costos[i][columna] for i in range(len(nuevas)) if i != fila and costos[i][columna] < limite]
                if any(abs(c - elegido) < config.get("lineage_margin", .02) for c in alternativas + competidores):
                    nueva["lineage_status"] = "ambiguous"
                    continue
            previa = viejas[columna]
            herencia = set(previa.get("previous_observation_ids", []))
            if previa["id"] != nueva["id"]:
                herencia.add(previa["id"])
            if herencia:
                nueva["previous_observation_ids"] = sorted(herencia)
            anchor = previa.get("anchor")
            caja = nueva["bbox_xyxy"]
            if not nueva.get("anchor") and anchor and anchor.get("verified") and caja[0] <= anchor["pixel"][0] <= caja[2] and caja[1] <= anchor["pixel"][1] <= caja[3]:
                nueva["anchor"] = anchor
                if previa["id"] != nueva["id"]:
                    nueva["anchor_inherited_from"] = previa["id"]
                elif previa.get("anchor_inherited_from"):
                    nueva["anchor_inherited_from"] = previa["anchor_inherited_from"]
    observaciones = preparar_observaciones(crudas, capturas,
                                         marco, config, almacen.overrides(survey["id"]))
    return marco, capturas, observaciones


def reconciliar(almacen, survey, config, record_event=True):
    marco, capturas, obs = observaciones_actuales(almacen, survey, config)
    anteriores = almacen.estado(survey["id"])
    propuestas, ambiguos = construir_hipotesis(obs, config)
    # Una caja anteriormente individual puede abarcar dos identidades ahora
    # respaldadas por otras capturas. Retirarla como soporte puntual evita
    # conservar un tercer árbol ficticio entre los dos ejemplares.
    cambio_grupos = False
    apoyadas = [p for p in propuestas if p["identity_status"] == "confirmed" and p.get("fit")]
    for observacion in obs:
        if observacion["role"] != "individual" or observacion["role_verified"] or not observacion["ray"].get("valid"):
            continue
        compatibles = [p for p in apoyadas if observacion["id"] not in p["observation_ids"]
                       and p["epoch"] == observacion["epoch"]
                       and .1 < rango(observacion, p["fit"]["xy"]) < config["max_range_m"]
                       and error_angular(observacion, p["fit"]["xy"]) <= observacion["ray"]["half_width_deg"]]
        if len(compatibles) >= 2:
            observacion.update(role="group", role_reason="multiple_supported_individuals_in_box")
            cambio_grupos = True
    if cambio_grupos:
        propuestas, ambiguos = construir_hipotesis(obs, config)
    informe_seguimiento = {"enabled": False, "merges": 0}
    if config.get("allow_visual_tracking", False):
        from .seguimiento_visual import crear_enlaces, fusionar_propuestas
        ajustes_camara = almacen.overrides(survey["id"])
        capturas_efectivas = {iid: {**meta, **ajustes_camara.get(("camera", iid), {})} for iid, meta in capturas.items()}
        enlaces = crear_enlaces(obs, capturas_efectivas, config)
        propuestas, informe_seguimiento = fusionar_propuestas(propuestas, obs, enlaces, anteriores, config)
        informe_seguimiento["enabled"] = True
    antiguos = sorted([a for a in anteriores["trees"] if a.get("active", True)], key=lambda a: a["id"])
    linajes = {o["id"]: set(o.get("previous_observation_ids", [])) for o in obs}
    propietarios = {}
    for arbol in antiguos:
        if arbol.get("origin") == "review":
            for oid in arbol["observation_ids"]:
                propietarios.setdefault(oid, set()).add(arbol["id"])
    for oid, ancestros in linajes.items():
        propietarios.setdefault(oid, set()).update(prop for anterior in ancestros for prop in propietarios.get(anterior, set()))
    filtradas = []
    for propuesta in propuestas:
        duenos = set().union(*(propietarios.get(oid, set()) for oid in propuesta["observation_ids"]))
        if len(duenos) > 1:
            ambiguos.append({"observation_ids": propuesta["observation_ids"], "reason": "conflicts_with_reviewed_identities", "alternatives": []})
        else:
            propuesta["reviewed_owner"] = next(iter(duenos), None)
            filtradas.append(propuesta)
    propuestas = filtradas
    costos = []
    for nueva in propuestas:
        ids = set(nueva["observation_ids"])
        ids.update(oid for actual in nueva["observation_ids"] for oid in linajes[actual])
        fila = []
        for viejo in antiguos:
            comun = len(ids.intersection(viejo["observation_ids"]))
            if nueva["reviewed_owner"] and nueva["reviewed_owner"] != viejo["id"]:
                comun = 0
            fila.append(1 - comun / max(len(ids), len(viejo["observation_ids"])) if comun else 1000.)
        costos.append(fila)
    elecciones = asignacion(costos, 1.)
    reservadas = {antiguos[i]["id"] for i in elecciones if i is not None}
    resultado, usados, ops = [], set(), []
    anteriores_por_id = {a["id"]: a for a in anteriores["trees"]}
    for nueva, indice in zip(propuestas, elecciones):
        vieja = antiguos[indice] if indice is not None else None
        if vieja is None and nueva["reviewed_owner"]:
            continue
        clave = vieja["id"] if vieja else identificador("tree", survey["id"], min(nueva["observation_ids"]))
        # Al separar una asociación automática, su ID puede haber quedado
        # asignado a otra de las partes. La parte nueva necesita un ID propio.
        if vieja is None and clave in reservadas | usados:
            clave = identificador("tree", survey["id"], "reassociated", *sorted(nueva["observation_ids"]))
        # Una decisión manual de rechazo/división nunca se reactiva por la inferencia.
        bloqueada = anteriores_por_id.get(clave)
        if vieja is None and bloqueada and bloqueada.get("origin") == "review" and not bloqueada.get("active", True):
            continue
        entidad = {"id": clave, "active": True, "origin": "auto", **nueva}
        entidad.pop("reviewed_owner", None)
        if vieja and vieja.get("origin") == "review":
            entidad = {**vieja, "observation_ids": sorted(set(vieja["observation_ids"] + nueva["observation_ids"]))}
            if nueva["fit"] is not None and not vieja.get("manual_position"):
                entidad["fit"], entidad["position_status"] = nueva["fit"], nueva["position_status"]
        resultado.append(entidad)
        usados.add(clave)

    for viejo in anteriores["trees"]:
        if viejo["id"] in usados:
            continue
        viejo = dict(viejo)
        if viejo.get("origin") == "review":
            resultado.append(viejo)
            continue
        sucesores = [a["id"] for a in resultado if set(viejo["observation_ids"]) & set(a["observation_ids"])]
        if viejo.get("active", True):
            viejo.update(active=False, identity_status="superseded", superseded_by=sucesores,
                         review_reason="Evidence reassociated or previous detection run deactivated")
            if sucesores:
                ops.append({"type": "reassociate", "from": viejo["id"], "to": sucesores})
        resultado.append(viejo)

    grupos = []
    for observacion in obs:
        if observacion["role"] != "group":
            continue
        miembros = []
        for arbol in resultado:
            fit = arbol.get("fit")
            if (arbol.get("active", True) and fit and observacion["ray"].get("valid")
                    and arbol["epoch"] == observacion["epoch"]
                    and .1 < rango(observacion, fit["xy"]) < config["max_range_m"]
                    and error_angular(observacion, fit["xy"]) <= observacion["ray"]["half_width_deg"] + config["angular_floor_deg"]):
                miembros.append(arbol["id"])
        confirmados = [a for a in resultado if a["id"] in miembros and a["identity_status"] == "confirmed"]
        resuelto = len(confirmados) >= 2
        grupos.append({"id": identificador("group", survey["id"], observacion["id"]),
                       "active": True, "origin": "auto", "status": "resolved" if resuelto else "needs_review",
                       "observation_ids": [observacion["id"]], "member_ids": sorted(miembros),
                       "epoch": observacion["epoch"], "reason": observacion.get("role_reason", "ambiguous_group"),
                       "geometry": None})
        if resuelto:
            for viejo in resultado:
                if (viejo.get("active", True) and viejo.get("origin") == "review"
                        and observacion["id"] in viejo["observation_ids"]
                        and not any(o["id"] in viejo["observation_ids"] and o["role"] == "individual" for o in obs)):
                    viejo.update(identity_status="needs_review", review_reason="New views separate multiple individuals in all previous support; review or split this identity")
                    ops.append({"type": "identity_conflict", "tree_id": viejo["id"], "possible_children": sorted(a["id"] for a in confirmados)})
                if (not viejo.get("active", True) and viejo.get("origin") == "auto"
                        and observacion["id"] in viejo["observation_ids"]):
                    nuevos_ids = sorted(a["id"] for a in confirmados)
                    if viejo.get("superseded_by") != nuevos_ids:
                        viejo["superseded_by"] = nuevos_ids
                        ops.append({"type": "split", "from": viejo["id"], "to": nuevos_ids,
                                    "evidence_group": grupos[-1]["id"]})
    for ambiguo in ambiguos:
        por_id = {o["id"]: o for o in obs}
        grupos.append({"id": identificador("ambiguity", survey["id"], *ambiguo["observation_ids"]),
                       "active": True, "origin": "auto", "status": "needs_review", "member_ids": [],
                       "epoch": por_id[ambiguo["observation_ids"][0]]["epoch"],
                       "geometry": None, **ambiguo})
    grupos_previos = {g["id"]: g for g in anteriores["groups"]}
    claves = {g["id"] for g in grupos}
    for grupo in grupos:
        previo = grupos_previos.get(grupo["id"])
        if previo and previo.get("origin") == "review":
            grupo.update(previo)
        elif grupo["status"] == "resolved" and (not previo or previo.get("status") != "resolved"):
            ops.append({"type": "split_group", "from": grupo["id"], "to": grupo["member_ids"]})
    for previo in anteriores["groups"]:
        if previo["id"] not in claves:
            grupos.append(dict(previo) if previo.get("origin") == "review" else {**previo, "active": False})
    estado = {"trees": resultado, "groups": grupos, "overrides": anteriores["overrides"], "observations": obs}
    evento = almacen.guardar_estado(survey["id"], estado, detalle={"operations": ops, "visual_tracking": informe_seguimiento}, journal=record_event)
    return {"event_id": evento, "frame": marco, "captures": capturas, "observations": obs,
            "state": almacen.estado(survey["id"]), "tracking_report": informe_seguimiento}


def contadores(estado, observaciones):
    arboles = [a for a in estado["trees"] if a.get("active", True)]
    confirmados = [a for a in arboles if a["identity_status"] == "confirmed"]
    localizados = [a for a in confirmados if a.get("fit") and a["position_status"] == "estimated"]
    return {"arboles_confirmados": len(confirmados), "confirmados_con_posicion": len(localizados),
            "confirmados_sin_posicion_suficiente": len(confirmados) - len(localizados),
            "candidatos_individuales": sum(a["identity_status"] == "candidate" for a in arboles),
            "individuos_para_revision": sum(a["identity_status"] == "needs_review" for a in arboles),
            "grupos_no_resueltos": sum(g.get("active", True) and g["status"] != "resolved" for g in estado["groups"]),
            "observaciones": len(observaciones),
            "duplicados_probables": sum(o["role"] == "duplicate" for o in observaciones),
            "observaciones_sin_geometria": sum(not o["ray"].get("valid") for o in observaciones)}


def aplicar_correccion(almacen, survey, config, accion):
    """Correcciones explícitas con evidencia y razón, sin alterar observaciones crudas."""
    motivo = accion.get("reason", "")
    if not isinstance(motivo, str):
        raise ValueError("reason debe ser un texto")
    motivo = motivo.strip()
    if not motivo:
        raise ValueError("La corrección debe incluir reason para conservar su justificación")
    tipo = accion.get("type")
    estado = almacen.estado(survey["id"])
    marco, _, observaciones = observaciones_actuales(almacen, survey, config)
    obs_por_id = {o["id"]: o for o in observaciones}
    arboles = {a["id"]: a for a in estado["trees"]}
    grupos = {g["id"]: g for g in estado["groups"]}

    if tipo in ("set_anchor", "set_kind", "set_camera"):
        campo = "camera" if tipo == "set_camera" else "observation"
        target = str(accion["target"])
        if campo == "observation" and target not in obs_por_id:
            raise ValueError("Observación inexistente o de una ejecución inactiva")
        if campo == "camera" and target not in almacen.capturas(survey["id"]):
            raise ValueError("Cámara inexistente")
        if tipo == "set_anchor":
            ancla = dict(accion["anchor"])
            if len(ancla.get("pixel", [])) != 2 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in ancla["pixel"]):
                raise ValueError("anchor.pixel debe tener dos coordenadas finitas")
            obs = obs_por_id[target]
            if not (0 <= ancla["pixel"][0] < obs["width"] and 0 <= ancla["pixel"][1] < obs["height"]):
                raise ValueError("Ancla fuera de la imagen")
            ancla.update(verified=True, source="manual", reason=motivo)
            if "uncertainty_deg" in ancla and (not isinstance(ancla["uncertainty_deg"], (int, float)) or not math.isfinite(ancla["uncertainty_deg"]) or not 0 < ancla["uncertainty_deg"] < 90):
                raise ValueError("La incertidumbre del ancla debe estar entre 0 y 90 grados")
            payload = {"anchor": ancla, "role": "individual", "role_verified": True}
        elif tipo == "set_kind":
            if accion["kind"] not in ("individual", "group", "duplicate", "rejected"):
                raise ValueError("kind inválido")
            payload = {"role": accion["kind"], "role_verified": True}
        else:
            permitidos = {"pixel_transform", "computed_rotation", "computed_compass_angle", "camera_parameters", "camera_type", "exif_orientation", "width", "height"}
            payload = accion["metadata"]
            if not isinstance(payload, dict) or set(payload) - permitidos:
                raise ValueError("Campos de cámara no admitidos para corrección")
        encontrado = next((o for o in estado["overrides"] if o["kind"] == campo and o["target"] == target), None)
        if encontrado:
            encontrado["payload"].update(payload)
        else:
            estado["overrides"].append({"kind": campo, "target": target, "payload": payload})
        tipo_evento = "camera_override" if campo == "camera" else "anchor" if tipo == "set_anchor" else "review"
    elif tipo in ("confirm", "reject"):
        arbol = arboles[accion["target"]]
        if not arbol.get("active", True):
            raise ValueError("No se puede revisar un individuo reemplazado")
        arbol.update(origin="review", identity_status="confirmed" if tipo == "confirm" else "rejected",
                     active=tipo == "confirm", review_reason=motivo)
        tipo_evento = "review"
    elif tipo == "split":
        parent_id = accion["parent_id"]
        parent = arboles.get(parent_id) or grupos.get(parent_id)
        if parent is None or not parent.get("active", True):
            raise ValueError("La hipótesis a dividir no está activa")
        hijos, usados = accion.get("children", []), set()
        if len(hijos) < 2:
            raise ValueError("Una división requiere al menos dos hijos")
        nuevas = []
        for i, hijo in enumerate(hijos):
            ids = hijo.get("observation_ids", [])
            if not ids or len(set(ids)) != len(ids) or set(ids) & usados or not set(ids) <= obs_por_id.keys():
                raise ValueError("Cada hijo necesita evidencia actual distinta; no se copia la caja del grupo")
            usados.update(ids)
            miembros = [obs_por_id[oid] for oid in ids]
            if any(o["role"] in ("group", "duplicate", "rejected") for o in miembros):
                raise ValueError("La evidencia del hijo debe representar un individuo; revisá sus roles primero")
            epochs = {o["epoch"] for o in miembros}
            if len(epochs) != 1:
                raise ValueError("No se divide usando relevamientos de años distintos")
            fit = ajustar([o for o in miembros if o["ray"].get("valid")], config)
            manual = hijo.get("coordinates")
            if manual is not None:
                if marco is None or len(manual) != 2 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in manual) or not (-180 <= manual[0] <= 180 and -90 <= manual[1] <= 90):
                    raise ValueError("Coordenadas manuales inválidas o sin marco")
                fit = {"xy": marco.proyectar(*manual), "method": "manual_review", "uncertainty_m": None, "uncertainty_calibrated": False}
                if math.hypot(*fit["xy"]) > config["max_survey_extent_m"]:
                    raise ValueError("La posición manual está fuera de la extensión del relevamiento")
            clave = identificador("split_child", survey["id"], parent_id, i, *sorted(ids))
            if clave in arboles:
                raise ValueError("La división ya tiene hijos registrados")
            nuevas.append({"id": clave, "active": True, "origin": "review", "parent_id": parent_id,
                           "observation_ids": sorted(ids), "epoch": next(iter(epochs)), "fit": fit,
                           "identity_status": "confirmed" if hijo.get("confirmed", False) else "candidate",
                           "position_status": "estimated" if fit else "unlocated", "manual_position": manual is not None,
                           "review_reason": motivo})
        parent.update(active=False, origin="review", superseded_by=[a["id"] for a in nuevas])
        if parent_id in arboles:
            parent["identity_status"] = "superseded"
        else:
            parent.update(status="resolved", member_ids=parent["superseded_by"])
        # Retirar candidatos automáticos que las nuevas identidades reemplazan.
        for arbol in estado["trees"]:
            if arbol["id"] != parent_id and arbol.get("active", True) and set(arbol["observation_ids"]) & usados:
                if arbol["origin"] == "review":
                    raise ValueError("La evidencia ya pertenece a otra identidad revisada")
                arbol.update(active=False, identity_status="superseded", origin="review", superseded_by=[a["id"] for a in nuevas if set(a["observation_ids"]) & set(arbol["observation_ids"])])
        estado["trees"].extend(nuevas)
        tipo_evento = "split"
    elif tipo == "merge":
        ids = accion.get("tree_ids", [])
        if len(ids) < 2 or len(set(ids)) != len(ids) or not set(ids) <= arboles.keys():
            raise ValueError("La fusión requiere dos o más IDs distintos")
        miembros = [arboles[aid] for aid in ids]
        if not all(a.get("active", True) for a in miembros) or len({a["epoch"] for a in miembros}) != 1:
            raise ValueError("La fusión necesita individuos activos del mismo período")
        canonico = miembros[0]
        canonico.update(origin="review", observation_ids=sorted(set(oid for a in miembros for oid in a["observation_ids"])), review_reason=motivo)
        for otro in miembros[1:]:
            otro.update(active=False, origin="review", identity_status="superseded", superseded_by=[canonico["id"]])
        tipo_evento = "merge"
    else:
        raise ValueError(f"Tipo de corrección desconocido: {tipo}")
    return almacen.guardar_estado(survey["id"], estado, tipo_evento, {"action": accion, "reason": motivo})


def corregir(almacen, survey, config, accion):
    """Aplicar revisión y reconciliación como un único cambio reversible."""
    with almacen.transaccion():
        evento = aplicar_correccion(almacen, survey, config, accion)
        if evento:
            reconciliar(almacen, survey, config, record_event=False)
            fila = almacen.db.execute("SELECT payload FROM events WHERE id=?", (evento,)).fetchone()
            payload = json.loads(fila[0])
            payload["after"] = almacen.estado(survey["id"])
            almacen.db.execute("UPDATE events SET payload=? WHERE id=?", (json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False), evento))
        return evento
