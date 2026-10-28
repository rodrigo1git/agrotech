"""Visores independientes: consumen JSON, sin importar detección ni inventario.

python -m mapeo.visualizacion --datos ruta/mapa_datos.json --plantilla mi_visor.html
"""

import argparse
import json
from pathlib import Path


PLANTILLA = Path(__file__).with_name("visores") / "leaflet.html"


def renderizar_mapa(datos, plantilla=None):
    """Insertar el contrato del visor en una plantilla HTML intercambiable."""
    contenido = Path(plantilla or PLANTILLA).read_text(encoding="utf-8")
    if contenido.count("__DATOS__") != 1:
        raise ValueError("La plantilla debe contener exactamente un marcador __DATOS__.")
    serializado = json.dumps(datos, ensure_ascii=False, allow_nan=False)
    # El JSON se incrusta en un script de datos; ningún texto puede cerrarlo.
    serializado = serializado.replace("<", "\\u003c").replace("&", "\\u0026")
    return contenido.replace("__DATOS__", serializado)


def _escribir(ruta, contenido):
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_name(ruta.name + ".tmp")
    temporal.write_text(contenido, encoding="utf-8")
    temporal.replace(ruta)


def exportar_mapa(datos, destino, plantilla=None):
    """Exportar los mismos datos como JSON reutilizable y HTML autocontenido."""
    datos = {"schema_version": 1, **datos}
    html = renderizar_mapa(datos, plantilla)
    destino = Path(destino)
    _escribir(destino / "mapa_datos.json", json.dumps(datos, ensure_ascii=False, allow_nan=False, indent=2))
    _escribir(destino / "mapa.html", html)


def main():
    parser = argparse.ArgumentParser(description="Generar un visor sin ejecutar DINO ni modificar el inventario.")
    parser.add_argument("--datos", type=Path, required=True, help="Archivo mapa_datos.json exportado.")
    parser.add_argument("--plantilla", type=Path, help="HTML alternativo con un marcador __DATOS__.")
    parser.add_argument("--output", type=Path, help="HTML de salida; por defecto mapa.html junto al JSON.")
    args = parser.parse_args()
    try:
        datos = json.loads(args.datos.read_text(encoding="utf-8"))
        html = renderizar_mapa(datos, args.plantilla)
        salida = args.output or args.datos.with_name("mapa.html")
        _escribir(salida, html)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"No se pudo generar el visor: {exc}\n")
    print(f"Visor generado: {salida}")


if __name__ == "__main__":
    main()
