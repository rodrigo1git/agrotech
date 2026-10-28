#!/usr/bin/env bash
# Descargar las tres capturas seleccionadas, detectar con tree. y actualizar
# el inventario existente. Las posiciones se consultan a Mapillary, no se
# extraen del centro lat/lng del visor.
set -euo pipefail

carpeta_proyecto="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v conda >/dev/null 2>&1; then
    printf 'No se encontró Conda. Ejecutá desde una terminal con Conda disponible.\n' >&2
    exit 1
fi

OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}" MKL_NUM_THREADS="${MKL_NUM_THREADS:-4}" \
conda run --name hackaton --no-capture-output python -B \
    "$carpeta_proyecto/mapillary_arboles.py" \
    --image-id 870050853581010 500511691078373 286871449741145 \
    --limit 3 \
    --prompt 'tree.' \
    --threshold 0.35 \
    --text-threshold 0.25 \
    --output "$carpeta_proyecto/resultados/mapillary_tres_capturas" \
    --map \
    --relevamiento tandil2018 \
    --map-output "$carpeta_proyecto/resultados/mapeo"
