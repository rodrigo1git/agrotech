"""Descargar las capturas del perímetro Constitución/Rivadavia/25 de Mayo/Alberdi."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import subprocess
import sys

from mapillary_arboles import (ClienteMapillary, ErrorMapillary, descargar_imagen,
                              escribir_json, exportar_camaras, metadatos_guardables, obtener_token)
from mapeo.seleccion_manzana import (CALLES, bbox_consulta, consultar_calles,
                                    resolver_manzana, seleccion_captura)


SALIDA = Path(__file__).resolve().parent / "resultados/manzana_constitucion_rivadavia_25mayo_alberdi"


def descargar(zona, cliente, salida, margen=30., limite=0):
    """Consultar todas las páginas antes de reemplazar un manifest previo."""
    candidatos = list(cliente.seleccionar(bbox=bbox_consulta(zona, margen), limite=0))
    elegidas = []
    for datos in candidatos:
        criterio = seleccion_captura(datos, zona, margen)
        if criterio:
            elegidas.append((datos, criterio))
    elegidas.sort(key=lambda par: (par[0].get("captured_at") or 0, str(par[0]["id"])))
    if limite:
        elegidas = elegidas[:limite]
    print(f"Capturas consultadas: {len(candidatos)}; seleccionadas cerca del perímetro: {len(elegidas)}", flush=True)
    if not elegidas:
        raise ValueError("No se encontraron capturas dentro del margen del perímetro. No se reemplaza un manifest anterior.")
    manifest = {"source": "mapillary", "selection": {"streets": CALLES, "city": "Tandil", "margin_m": margen,
                                                      "bbox": bbox_consulta(zona, margen), "limit": limite},
                "images": [], "errors": []}
    for i, (datos, criterio) in enumerate(elegidas, 1):
        registro = metadatos_guardables(datos)
        registro["block_selection"] = criterio
        try:
            descargar_imagen(cliente, datos, salida / "imagenes" / registro["file_name"])
        except (OSError, ValueError, ErrorMapillary) as exc:
            manifest["errors"].append({"id": registro["id"], "error": str(exc)})
        else:
            manifest["images"].append(registro)
        escribir_json(salida / "manifest.json", manifest)
        exportar_camaras(manifest["images"], salida / "camaras.geojson")
        if i % 10 == 0 or i == len(elegidas):
            print(f"Procesadas {i}/{len(elegidas)}: {len(manifest['images'])} imágenes listas, {len(manifest['errors'])} errores", flush=True)
    anos = Counter()
    for m in manifest["images"]:
        try:
            ano = str(datetime.fromtimestamp(m["captured_at"] / 1000, timezone.utc).year)
        except (KeyError, TypeError, ValueError, OverflowError):
            ano = "sin_fecha"
        anos[ano] += 1
    resumen = {"queried_captures": len(candidatos), "selected_captures": len(elegidas),
               "downloaded_images": len(manifest["images"]), "download_errors": len(manifest["errors"]),
               "by_year": dict(sorted(anos.items())), "by_street": dict(Counter(m["block_selection"]["street"] for m in manifest["images"])),
               "by_sequence": dict(Counter(str(m.get("sequence", "sin_secuencia")) for m in manifest["images"])),
               "complete": not manifest["errors"] and not limite}
    escribir_json(salida / "resumen_descarga.json", resumen)
    return 1 if manifest["errors"] else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=SALIDA)
    parser.add_argument("--margin-m", type=float, default=30., help="Margen de cámaras alrededor del perímetro, por error GPS.")
    parser.add_argument("--limit", type=int, default=0, help="0 = todas las capturas seleccionadas, sin límite de páginas.")
    parser.add_argument("--solo-zona", action="store_true", help="Resolver las cuatro esquinas sin consultar Mapillary.")
    parser.add_argument("--download-only", action="store_true", help="Descargar y mostrar cámaras sin ejecutar DINO.")
    args = parser.parse_args()
    if not math.isfinite(args.margin_m) or args.margin_m <= 0 or args.limit < 0:
        parser.error("El margen debe ser positivo y finito, y el límite no negativo.")
    salida = args.output.resolve()
    fase = "calles"
    try:
        cache = salida / "calles_overpass.json"
        datos = json.loads(cache.read_text()) if cache.is_file() else consultar_calles()
        zona = resolver_manzana(datos)
        escribir_json(cache, datos)
        escribir_json(salida / "zona.geojson", {"type": "FeatureCollection", "features": [zona]})
        print("Zona resuelta:", ", ".join(CALLES), f"· {zona['properties']['area_m2']:.0f} m²", flush=True)
        if args.solo_zona:
            return 0
        fase = "mapillary"
        cliente = ClienteMapillary(obtener_token())
        codigo = descargar(zona, cliente, salida, args.margin_m, args.limit)
        escribir_json(salida / "estado_descarga.json", {"status": "complete" if codigo == 0 else "partial", "stage": "download"})
        print(f"Imágenes y metadatos: {salida}")
        if codigo == 0:
            comando = [sys.executable, "-B", str(Path(__file__).with_name("procesar_manzana_tandil.py")), "--dataset", str(salida)]
            if args.download_only:
                comando.append("--preview-only")
            return subprocess.run(comando, check=False).returncode
        return codigo
    except (OSError, ValueError, KeyError, ErrorMapillary) as exc:
        escribir_json(salida / "estado_descarga.json", {"status": "failed", "stage": fase, "error": str(exc)})
        parser.exit(1, f"No se completó la descarga de la manzana: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
