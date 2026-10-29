"""Detectar árboles con Grounding DINO, sin entrenamiento propio."""

import argparse
import hashlib
import json
import sys
from pathlib import Path


EXTENSIONES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
MODELO = "IDEA-Research/grounding-dino-tiny"


def listar_imagenes(entrada, salida):
    entrada, salida = entrada.resolve(), salida.resolve()
    if entrada.is_file():
        return [entrada] if entrada.suffix.lower() in EXTENSIONES else []
    if not entrada.is_dir():
        raise ValueError(f"No existe la imagen o carpeta: {entrada}")
    if entrada == salida or entrada.is_relative_to(salida):
        raise ValueError("La carpeta de resultados debe estar separada de la entrada.")
    return sorted(
        ruta for ruta in entrada.rglob("*")
        if ruta.is_file() and ruta.suffix.lower() in EXTENSIONES
        and not ruta.resolve().is_relative_to(salida)
    )


def guardar_resultado(imagen, resultado, ruta, destino, configuracion, metadatos=None):
    from PIL import ImageDraw

    cajas = resultado["boxes"].detach().cpu().tolist()
    puntajes = resultado["scores"].detach().cpu().tolist()
    etiquetas = resultado.get("text_labels")
    if etiquetas is None:
        etiquetas = resultado.get("labels")
    if etiquetas is None:
        raise ValueError("El procesador no devolvió etiquetas de texto.")
    anotada = imagen.copy()
    dibujo = ImageDraw.Draw(anotada)
    detecciones = []
    for caja, puntaje, etiqueta in zip(cajas, puntajes, etiquetas):
        x1, y1, x2, y2 = caja
        x1, x2 = [max(0.0, min(imagen.width, x)) for x in (x1, x2)]
        y1, y2 = [max(0.0, min(imagen.height, y)) for y in (y1, y2)]
        if x2 <= x1 or y2 <= y1:
            continue
        detecciones.append({
            "label": str(etiqueta),
            "score": float(puntaje),
            "bbox_xyxy": [round(v, 2) for v in (x1, y1, x2, y2)],
            "bbox_coco": [round(v, 2) for v in (x1, y1, x2 - x1, y2 - y1)],
        })
        if metadatos is not None:
            detecciones[-1].update({
                "observation_id": f"mapillary:{metadatos['id']}:{len(detecciones)}",
                "geolocation_status": "pending",
            })
        dibujo.rectangle((x1, y1, x2, y2), outline="lime", width=3)
        texto = f"{etiqueta} {puntaje:.2f}"
        tx, ty = int(x1), max(0, int(y1) - 15)
        dibujo.rectangle(dibujo.textbbox((tx, ty), texto), fill="black")
        dibujo.text((tx, ty), texto, fill="lime")

    destino.parent.mkdir(parents=True, exist_ok=True)
    # Conserva la extensión original como parte del nombre: foto.jpg.png.
    ruta_imagen = destino.with_name(destino.name + ".png")
    ruta_json = destino.with_name(destino.name + ".json")
    anotada.save(ruta_imagen)
    registro = {
        "source": str(ruta),
        "width": imagen.width,
        "height": imagen.height,
        **configuracion,
        "detections": detecciones,
    }
    if metadatos is not None:
        registro["mapillary"] = metadatos
    ruta_json.write_text(json.dumps(registro, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(detecciones)


def resultado_reutilizable(destino, configuracion, width, height, metadatos):
    """Reanudar solo si coinciden imagen, modelo, parámetros y metadatos."""
    archivo = destino.with_name(destino.name + ".json")
    if not archivo.is_file() or not destino.with_name(destino.name + ".png").is_file():
        return None
    try:
        registro = json.loads(archivo.read_text(encoding="utf-8"))
        if any(registro.get(k) != v for k, v in configuracion.items()):
            return None
        if (registro.get("width"), registro.get("height")) != (width, height) or registro.get("mapillary") != metadatos:
            return None
        return registro if isinstance(registro.get("detections"), list) else None
    except (OSError, ValueError):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("entrada", type=Path, help="Imagen o carpeta (incluye subcarpetas)")
    parser.add_argument("--output", type=Path, default=Path("resultados/arboles"))
    parser.add_argument("--limit", type=int, default=10, help="Máximo de imágenes; 0 = todas")
    parser.add_argument("--prompt", default="tree.", help="Texto en inglés, separado por puntos")
    parser.add_argument("--threshold", type=float, default=0.35, help="Umbral de cajas")
    parser.add_argument("--text-threshold", type=float, default=0.25, help="Umbral de texto")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--dry-run", action="store_true", help="Listar entradas sin cargar el modelo")
    parser.add_argument("--skip-existing", action="store_true", help="Reutilizar resultados válidos de las mismas imágenes y configuración")
    parser.add_argument("--manifest", type=Path, help="Manifest de Mapillary; selecciona sus imágenes y conserva metadatos")
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("--limit no puede ser negativo.")
    if not 0 <= args.threshold <= 1 or not 0 <= args.text_threshold <= 1:
        parser.error("Los umbrales deben estar entre 0 y 1.")
    if not args.prompt.strip():
        parser.error("--prompt no puede estar vacío.")
    metadatos = {}
    try:
        if args.manifest:
            from mapillary_arboles import cargar_manifest
            if not args.entrada.is_dir():
                parser.error("Con --manifest, la entrada debe ser la carpeta de imágenes.")
            metadatos = cargar_manifest(args.manifest, args.entrada)
            imagenes = list(metadatos)
        else:
            imagenes = listar_imagenes(args.entrada, args.output)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    if args.limit:
        imagenes = imagenes[:args.limit]
    if not imagenes:
        parser.error("No se encontraron imágenes compatibles. Extraé el ZIP antes de ejecutar.")
    print(f"Imágenes seleccionadas: {len(imagenes)}", flush=True)
    if args.dry_run:
        for ruta in imagenes:
            print(ruta)
        return 0

    try:
        import torch
        from PIL import Image
        from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor
    except ImportError as error:
        parser.exit(1, f"Falta una dependencia: {error}\n"
                    "Instalá: python -m pip install -r requirements-grounding.txt\n")

    device = "cuda" if args.device == "auto" and torch.cuda.is_available() else args.device
    if device == "auto":
        device = "cpu"
    if device == "cuda" and not torch.cuda.is_available():
        parser.error("CUDA no está disponible en este entorno. Probá --device cpu.")
    print(f"Cargando {MODELO} en {device}. La primera ejecución descarga los pesos.", flush=True)
    processor = AutoProcessor.from_pretrained(MODELO)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(MODELO).to(device).eval()
    revision = getattr(getattr(model, "config", None), "_commit_hash", None)
    if not isinstance(revision, str):
        revision = None
    revision_source = "model_config" if revision else None
    if revision is None:
        # Transformers no siempre conserva _commit_hash en la configuración.
        # Consultar la caché es una operación local y no dispara descargas.
        try:
            from huggingface_hub import try_to_load_from_cache
            cached = try_to_load_from_cache(MODELO, "model.safetensors")
            if isinstance(cached, str) and Path(cached).is_file():
                snapshot = Path(cached).parent.name
                if len(snapshot) == 40 and all(c in "0123456789abcdef" for c in snapshot.lower()):
                    revision, revision_source = snapshot, "local_cache_snapshot"
        except (ImportError, OSError):
            pass
    procesado = getattr(processor, "image_processor", None)
    procesado = procesado.to_dict() if procesado is not None and hasattr(procesado, "to_dict") else None
    if not isinstance(procesado, dict):
        procesado = None
    configuracion = {
        "model": MODELO,
        "prompt": args.prompt,
        "threshold": args.threshold,
        "text_threshold": args.text_threshold,
        "device": device,
        "revision": revision,
        "revision_source": revision_source,
        "preprocessing": json.loads(json.dumps(procesado, default=str)),
    }
    resumen = {**configuracion, "processed": [], "errors": []}
    observaciones = []
    if args.manifest:
        from mapillary_arboles import escribir_json
        escribir_json(args.output / "observaciones.geojson", {
            "type": "FeatureCollection", "features": observaciones,
        })
    raiz = args.entrada.resolve() if args.entrada.is_dir() else args.entrada.resolve().parent
    for numero, ruta in enumerate(imagenes, 1):
        try:
            with Image.open(ruta) as original:
                imagen = original.convert("RGB")
            destino = args.output / ruta.relative_to(raiz)
            metadata_imagen = metadatos.get(ruta)
            config_imagen = {**configuracion, "image_sha256": hashlib.sha256(ruta.read_bytes()).hexdigest()}
            previo = resultado_reutilizable(destino, config_imagen, imagen.width, imagen.height, metadata_imagen) if args.skip_existing else None
            if previo is not None:
                cantidad = len(previo["detections"])
            else:
                inputs = processor(images=imagen, text=args.prompt, return_tensors="pt").to(device)
                with torch.inference_mode():
                    outputs = model(**inputs)
                resultado = processor.post_process_grounded_object_detection(
                    outputs, inputs.input_ids, threshold=args.threshold,
                    text_threshold=args.text_threshold, target_sizes=[(imagen.height, imagen.width)],
                )[0]
                cantidad = guardar_resultado(imagen, resultado, ruta, destino, config_imagen, metadata_imagen)
            if metadata_imagen is not None:
                registro = json.loads(destino.with_name(destino.name + ".json").read_text(encoding="utf-8"))
                for deteccion in registro["detections"]:
                    observaciones.append({
                        "type": "Feature", "id": deteccion["observation_id"], "geometry": None,
                        "properties": {**deteccion, "mapillary_id": metadata_imagen["id"],
                                       "view_url": metadata_imagen["view_url"]},
                    })
                escribir_json(args.output / "observaciones.geojson", {
                    "type": "FeatureCollection", "features": observaciones,
                })
        except (OSError, ValueError) as error:
            print(f"[{numero}/{len(imagenes)}] ERROR {ruta}: {error}", file=sys.stderr)
            resumen["errors"].append({"source": str(ruta), "error": str(error)})
            continue
        print(f"[{numero}/{len(imagenes)}] {ruta.name}: {cantidad} detecciones", flush=True)
        resumen["processed"].append({"source": str(ruta), "detections": cantidad})

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "resumen.json").write_text(
        json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(f"Resultados: {args.output.resolve()}")
    return 1 if resumen["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
