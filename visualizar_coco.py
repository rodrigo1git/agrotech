"""Visor COCO: imágenes, cajas y categorías con navegación por teclado."""

import argparse
import json
from collections import defaultdict
from pathlib import Path


def cargar_coco(ruta):
    with ruta.open(encoding="utf-8") as archivo:
        coco = json.load(archivo)
    por_imagen = defaultdict(list)
    for anotacion in coco.get("annotations", []):
        por_imagen[anotacion["image_id"]].append(anotacion)
    categorias = {c["id"]: c["name"] for c in coco.get("categories", [])}
    return coco.get("images", []), por_imagen, categorias


def buscar_imagen(nombre, carpeta):
    # Acepta file_name con subcarpetas o imágenes directamente en la carpeta.
    for ruta in (carpeta / nombre, carpeta / Path(nombre).name):
        if ruta.is_file():
            return ruta
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json", type=Path,
        default=Path(__file__).resolve().with_name("coco_annotations.json"),
        help="Archivo de anotaciones COCO",
    )
    parser.add_argument("--images", type=Path, help="Carpeta de imágenes")
    parser.add_argument("--index", type=int, default=0, help="Posición inicial, desde 0")
    parser.add_argument("--save", type=Path, help="Guardar una vista PNG sin abrir ventana")
    args = parser.parse_args()

    try:
        imagenes, anotaciones, categorias = cargar_coco(args.json)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"No se pudo leer el COCO: {error}\n")
    if not imagenes:
        parser.error("El archivo COCO no tiene imágenes.")
    if not 0 <= args.index < len(imagenes):
        parser.error(f"--index debe estar entre 0 y {len(imagenes) - 1}.")

    try:
        import matplotlib
        if args.save:
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Patch, Rectangle
    except ImportError:
        parser.exit(1, "Instalá la dependencia: python3 -m pip install matplotlib\n")

    carpeta = args.images if args.images is not None else args.json.resolve().parent
    paleta = plt.get_cmap("tab10")
    colores = {cid: paleta(i % 10) for i, cid in enumerate(categorias)}
    figura, eje = plt.subplots(figsize=(16, 7))
    indice = args.index

    def dibujar():
        eje.clear()
        info = imagenes[indice]
        ruta = buscar_imagen(info["file_name"], carpeta)
        fondo = None
        aviso = ""
        if ruta is not None:
            try:
                fondo = plt.imread(ruta)
            except (OSError, ValueError) as error:
                aviso = f"No se pudo abrir {ruta}: {error}"
        else:
            aviso = "Imagen no encontrada: se muestran solo las anotaciones. Usá --images CARPETA."

        ancho, alto = info["width"], info["height"]
        if fondo is not None:
            eje.imshow(fondo, extent=(0, ancho, alto, 0))
        eje.set_xlim(0, ancho)
        eje.set_ylim(alto, 0)
        eje.set_aspect("equal")
        presentes = set()
        cajas = 0
        for anotacion in anotaciones[info["id"]]:
            bbox = anotacion.get("bbox")
            if not bbox or len(bbox) != 4:
                continue
            x, y, ancho_caja, alto_caja = bbox
            cid = anotacion["category_id"]
            color = colores.get(cid, "red")
            nombre = categorias.get(cid, str(cid))
            eje.add_patch(Rectangle(
                (x, y), ancho_caja, alto_caja,
                fill=False, edgecolor=color, linewidth=2,
            ))
            eje.text(
                x, y, nombre, fontsize=8, color="white", va="bottom",
                bbox={"facecolor": color, "alpha": 0.85, "edgecolor": "none", "pad": 2},
                clip_on=True,
            )
            presentes.add(cid)
            cajas += 1
        if presentes:
            eje.legend(handles=[
                Patch(color=colores.get(cid, "red"), label=categorias.get(cid, str(cid)))
                for cid in sorted(presentes)
            ], loc="upper right")
        eje.set_title(
            f"{indice + 1}/{len(imagenes)} · {info['file_name']} · {cajas} cajas"
        )
        eje.set_axis_off()
        figura.suptitle("COCO · ← anterior | → siguiente | Inicio / Fin | Q salir")
        pie.set_text(aviso)
        figura.canvas.draw_idle()

    def teclado(evento):
        nonlocal indice
        if evento.key in ("right", "n"):
            indice = (indice + 1) % len(imagenes)
        elif evento.key in ("left", "p"):
            indice = (indice - 1) % len(imagenes)
        elif evento.key == "home":
            indice = 0
        elif evento.key == "end":
            indice = len(imagenes) - 1
        elif evento.key in ("q", "escape"):
            plt.close(figura)
            return
        else:
            return
        dibujar()

    pie = figura.text(0.5, 0.02, "", ha="center", fontsize=9)
    figura.subplots_adjust(top=0.86, bottom=0.10)
    figura.canvas.mpl_connect("key_press_event", teclado)
    dibujar()
    if args.save:
        figura.savefig(args.save, dpi=150)
        plt.close(figura)
        print(f"Vista guardada en {args.save}")
    else:
        plt.show()


if __name__ == "__main__":
    main()
