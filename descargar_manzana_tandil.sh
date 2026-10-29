#!/usr/bin/env bash
set -euo pipefail
carpeta_proyecto="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if ! command -v conda >/dev/null 2>&1; then
    printf 'No se encontró Conda. Ejecutá desde una terminal con Conda disponible.\n' >&2
    exit 1
fi
conda run --name hackaton --no-capture-output python -B \
    "$carpeta_proyecto/descargar_manzana_tandil.py" "$@"
