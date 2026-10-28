"""Construir o actualizar un inventario persistente a partir de resultados DINO."""

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path

from mapillary_arboles import escribir_json


CONFIG_PATH = Path(__file__).with_name("configuracion_mapeo.json")


def cargar_config(ruta=None):
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if ruta and Path(ruta).resolve() != CONFIG_PATH.resolve():
        cambios = json.loads(Path(ruta).read_text(encoding="utf-8"))
        if not isinstance(cambios, dict) or set(cambios) - config.keys():
            raise ValueError("Configuración desconocida: usá las claves de configuracion_mapeo.json")
        config.update(cambios)
    for clave, valor in config.items():
        if clave.startswith("allow_"):
            if not isinstance(valor, bool):
                raise ValueError(f"{clave} debe ser booleano")
        elif isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor) or valor <= 0:
            raise ValueError(f"{clave} debe ser un número positivo finito")
    if not 0 < config["duplicate_iou"] <= 1 or not 0 < config["lineage_iou"] < 1 or config["min_views_candidate"] < 2 or config["min_views_confirm"] < config["min_views_candidate"]:
        raise ValueError("Revisá duplicate_iou y los mínimos de vistas")
    if any(int(config[k]) != config[k] for k in ("min_views_candidate", "min_views_confirm")) or config["min_parallax_deg"] >= 90:
        raise ValueError("Los mínimos de vistas deben ser enteros y el parallax menor a 90°")
    return config


def registros_dataset(raiz):
    raiz = Path(raiz).resolve()
    manifest = json.loads((raiz / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("source") != "mapillary" or not isinstance(manifest.get("images"), list):
        raise ValueError(f"Manifest de Mapillary inválido en {raiz}")
    if any(not isinstance(m, dict) or not m.get("id") or not isinstance(m.get("file_name"), str) for m in manifest["images"]):
        raise ValueError("Cada captura debe tener id y file_name")
    for meta in sorted(manifest["images"], key=lambda m: (m.get("captured_at") or 0, str(m["id"]))):
        imagen = (raiz / "imagenes" / meta["file_name"]).resolve()
        if not imagen.is_relative_to(raiz / "imagenes"):
            raise ValueError("La imagen del manifest está fuera del dataset")
        candidatas = [raiz / "detecciones" / (meta["file_name"] + ".json"), raiz / "detecciones" / f"{meta['id']}.json"]
        ruta = next((r for r in candidatas if r.is_file()), None)
        if ruta is None:
            raise ValueError(f"Falta detección de {meta['id']}; ejecutá DINO o usá --inferir")
        registro = json.loads(ruta.read_text(encoding="utf-8"))
        if str(registro.get("mapillary", meta).get("id")) != str(meta["id"]):
            raise ValueError("El ID del resultado no corresponde a su manifest")
        registro["mapillary"] = {**meta, **registro.get("mapillary", {})}
        if imagen.is_file():
            from PIL import Image
            with Image.open(imagen) as original:
                if list(original.size) != [registro["width"], registro["height"]]:
                    raise ValueError(f"La resolución de {imagen.name} cambió después de la detección")
            checksum = hashlib.sha256(imagen.read_bytes()).hexdigest()
            if registro.get("image_sha256") and checksum != registro["image_sha256"]:
                raise ValueError(f"La imagen {imagen.name} no corresponde al hash de la detección")
            registro["image_sha256"] = checksum
        registro["_image_path"], registro["_result_path"] = str(imagen), str(ruta)
        yield registro


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, nargs="+", help="Carpetas con manifest.json, imagenes/ y detecciones/")
    parser.add_argument("--output", type=Path, default=Path("resultados/mapeo"))
    parser.add_argument("--relevamiento", default="principal", help="Inventario/recorrido dentro de la base")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--inferir", action="store_true", help="Ejecutar DINO con tree. antes de importar cada dataset")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--correcciones", type=Path, help="JSON con una lista actions de revisiones justificadas")
    parser.add_argument("--deshacer", help="ID del último evento reversible; falla si hubo cambios posteriores")
    parser.add_argument("--export-only", action="store_true", help="Exportar el estado persistido sin reconciliar")
    parser.add_argument("--demo", action="store_true", help="Crear y procesar una escena sintética de dos árboles próximos")
    parser.add_argument("--validacion", type=Path, help="Referencia manual para evaluar identidad y ubicación")
    args = parser.parse_args()
    if args.demo and args.relevamiento == "principal":
        args.relevamiento = "demo"
    if args.demo and args.inferir:
        parser.error("La demo ya contiene observaciones de control; no se combina con --inferir")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.relevamiento):
        parser.error("Usá letras sin acentos, números, guiones o guiones bajos para el relevamiento")
    if args.deshacer and (args.dataset or args.correcciones or args.demo or args.inferir):
        parser.error("--deshacer debe ejecutarse sin importar nuevos datos ni otras correcciones")
    if args.export_only and (args.dataset or args.correcciones or args.demo or args.inferir):
        parser.error("--export-only no se combina con importación o correcciones")
    try:
        from mapeo.almacen import Almacen
        from mapeo.exportacion import exportar
        from mapeo.inventario import corregir, reconciliar
        config = cargar_config(args.config)
    except ImportError as error:
        parser.exit(1, f"Dependencia faltante en {sys.executable}: {error}\nUsá el Python del entorno hackaton.\n")
    except (OSError, ValueError) as error:
        parser.error(str(error))

    salida = args.output.resolve()
    almacen = Almacen(salida / "inventario.sqlite")
    fallos, imports = [], 0
    try:
        survey = almacen.survey(args.relevamiento, config)
        if args.demo:
            if any(not m.get("synthetic") for m in almacen.capturas(survey["id"]).values()):
                raise ValueError("La demo necesita un relevamiento separado de los datos reales")
            survey["synthetic"] = True
            almacen.guardar_survey(survey)
        if survey["config"] != config:
            if args.deshacer or args.export_only:
                config = survey["config"]
            else:
                with almacen.transaccion():
                    anterior = survey["config"]
                    survey["config"] = config
                    almacen.guardar_survey(survey)
                    almacen.evento(survey["id"], "configuration", {"before": anterior, "after": config})
        datasets = list(args.dataset or [])
        if args.demo:
            from mapeo.demo import crear_demo
            datasets.append(crear_demo(salida / "demo_sintetica"))
        if args.inferir and not datasets:
            raise ValueError("--inferir requiere --dataset")
        for dataset in datasets:
            if args.inferir:
                comando = [sys.executable, str(Path(__file__).with_name("detectar_arboles.py")), str(dataset / "imagenes"),
                           "--manifest", str(dataset / "manifest.json"), "--output", str(dataset / "detecciones"),
                           "--limit", "0", "--prompt", "tree.", "--threshold", ".35", "--text-threshold", ".25", "--device", args.device]
                if subprocess.run(comando, check=False).returncode:
                    raise ValueError("DINO no completó la ejecución; no se importan resultados antiguos de ese dataset")
            try:
                for registro in registros_dataset(dataset):
                    sintetico = bool(registro["mapillary"].get("synthetic"))
                    existentes = almacen.capturas(survey["id"])
                    if not existentes:
                        survey["synthetic"] = sintetico
                        almacen.guardar_survey(survey)
                    if existentes and any(bool(m.get("synthetic")) != sintetico for m in existentes.values()):
                        raise ValueError("No se mezclan observaciones sintéticas y capturas reales en un relevamiento")
                    if almacen.importar(survey["id"], registro):
                        imports += 1
                        reconciliar(almacen, survey, config)
                        metricas = exportar(almacen, survey, config, salida / "exportaciones" / survey["id"])
                        print(f"Imagen {registro['mapillary']['id']}: {metricas['arboles_confirmados']} confirmados, {metricas['grupos_no_resueltos']} grupos pendientes", flush=True)
            except (OSError, ValueError, KeyError, TypeError) as error:
                fallos.append({"dataset": str(dataset), "error": str(error)})
                print(f"Dataset {dataset}: {error}", file=sys.stderr)
        if args.deshacer:
            print("Evento de reversión:", almacen.deshacer(survey["id"], args.deshacer))
        elif not args.export_only:
            reconciliar(almacen, survey, config)
        if args.correcciones:
            datos = json.loads(args.correcciones.read_text(encoding="utf-8"))
            acciones = datos.get("actions") if isinstance(datos, dict) else datos
            if not isinstance(acciones, list):
                raise ValueError("Las correcciones deben contener una lista actions")
            for accion in acciones:
                if not isinstance(accion, dict):
                    raise ValueError("Cada acción de corrección debe ser un objeto JSON")
                evento = corregir(almacen, survey, config, accion)
                print("Corrección registrada:", evento or "sin cambios")
        destino = salida / "exportaciones" / survey["id"]
        metricas = exportar(almacen, survey, config, destino)
        escribir_json(destino / "errores.json", fallos)
        if args.validacion or args.demo:
            from mapeo.validacion import evaluar
            referencia = args.validacion or salida / "demo_sintetica" / "referencia.json"
            evaluar(destino / "inventario.json", referencia, destino / "validacion.json")
        print(f"Imágenes con ejecución nueva: {imports}")
        print(json.dumps(metricas, ensure_ascii=False, indent=2))
        print(f"Mapa: {destino / 'mapa.html'}")
        return 1 if fallos else 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"No se completó el mapeo: {error}\n")
    finally:
        almacen.close()


if __name__ == "__main__":
    sys.exit(main())
