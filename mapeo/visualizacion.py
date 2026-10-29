"""Visores independientes: consumen JSON, sin importar detección ni inventario.

python -m mapeo.visualizacion --datos ruta/mapa_datos.json --plantilla mi_visor.html
"""

import argparse
import json
from pathlib import Path
from .calibracion_horizontal import desplazar_datos, offsets


PLANTILLA = Path(__file__).with_name("visores") / "leaflet.html"


def renderizar_mapa(datos, plantilla=None, desplazamiento_m=None, desplazamiento_norte_m=None,
                    rotacion_grados=None, camara_pivote=None):
    """Insertar el contrato del visor en una plantilla HTML intercambiable."""
    contenido = Path(plantilla or PLANTILLA).read_text(encoding="utf-8")
    if contenido.count("__DATOS__") != 1:
        raise ValueError("La plantilla debe contener exactamente un marcador __DATOS__.")
    if any(v is not None for v in (desplazamiento_m, desplazamiento_norte_m, rotacion_grados, camara_pivote)):
        este_actual, norte_actual = offsets(datos)
        datos = desplazar_datos(datos, desplazamiento_m if desplazamiento_m is not None else este_actual,
                               desplazamiento_norte_m if desplazamiento_norte_m is not None else norte_actual,
                               rotacion_grados, camara_pivote)
    if "__CALIBRACION_JS__" in contenido:
        modulo = PLANTILLA.with_name("calibracion_horizontal.js").read_text(encoding="utf-8")
        contenido = contenido.replace("__CALIBRACION_JS__", modulo)
    if "__RECORRIDO_JS__" in contenido:
        modulo = PLANTILLA.with_name("recorrido_camaras.js").read_text(encoding="utf-8")
        contenido = contenido.replace("__RECORRIDO_JS__", modulo)
    if "__EVIDENCIA_JS__" in contenido:
        modulo = PLANTILLA.with_name("evidencia_arboles.js").read_text(encoding="utf-8")
        contenido = contenido.replace("__EVIDENCIA_JS__", modulo)
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
    parser.add_argument("--offset-east-m", type=float, help="Desplazamiento horizontal en metros: positivo este, negativo oeste.")
    parser.add_argument("--offset-north-m", type=float, help="Desplazamiento vertical en metros: positivo norte, negativo sur.")
    parser.add_argument("--rotation-deg", type=float, help="Giro del conjunto en grados; positivo horario.")
    parser.add_argument("--pivot-camera-id", help="Cámara usada como centro del giro.")
    parser.add_argument("--calibracion", type=Path, help="JSON de ajuste descargado desde el visor, incluido el formato horizontal anterior.")
    args = parser.parse_args()
    if args.calibracion and any(v is not None for v in (args.offset_east_m, args.offset_north_m, args.rotation_deg, args.pivot_camera_id)):
        parser.error("Usá --calibracion o los parámetros de ajuste, no ambos.")
    try:
        datos = json.loads(args.datos.read_text(encoding="utf-8"))
        metros = args.offset_east_m
        norte = args.offset_north_m
        rotacion, pivote = args.rotation_deg, args.pivot_camera_id
        if args.calibracion:
            calibracion = json.loads(args.calibracion.read_text(encoding="utf-8"))
            if calibracion.get("survey_id") != datos["survey"]["id"]:
                raise ValueError("El ajuste pertenece a otro relevamiento.")
            metros = calibracion["offset_east_m"]
            norte = calibracion.get("offset_north_m", 0.)
            rotacion, pivote = calibracion.get("rotation_deg", 0.), calibracion.get("pivot_camera_id")
        html = renderizar_mapa(datos, args.plantilla, metros, norte, rotacion, pivote)
        salida = args.output or args.datos.with_name("mapa.html")
        _escribir(salida, html)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        parser.exit(1, f"No se pudo generar el visor: {exc}\n")
    print(f"Visor generado: {salida}")


if __name__ == "__main__":
    main()
