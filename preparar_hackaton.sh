#!/usr/bin/env bash
# Ejecutar desde la terminal del usuario: bash preparar_hackaton.sh
set -euo pipefail

carpeta_proyecto="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v conda >/dev/null 2>&1; then
    printf 'No se encontró conda. Ejecutá este script desde una terminal con Conda disponible.\n' >&2
    exit 1
fi

printf 'Preparando Python 3.12 y pip en el entorno hackaton...\n'
conda install --name hackaton python=3.12 pip --yes

printf 'Instalando las dependencias del detector en hackaton...\n'
conda run --name hackaton --no-capture-output python -m pip install \
    -r "$carpeta_proyecto/requirements-mapeo.txt"

printf 'Verificando dependencias...\n'
conda run --name hackaton --no-capture-output python -m pip check
conda run --name hackaton --no-capture-output python -c '
import sys
import torch
import torchvision
import transformers
import numpy
from PIL import Image
from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor
print("Python:", sys.version.split()[0])
print("Ejecutable:", sys.executable)
print("PyTorch:", torch.__version__)
print("Torchvision:", torchvision.__version__)
print("Transformers:", transformers.__version__)
print("NumPy:", numpy.__version__)
print("CUDA disponible:", torch.cuda.is_available())
'

printf '\nEntorno preparado. Para probar una imagen:\n'
printf 'conda run --name hackaton python "%s/detectar_arboles.py" "%s/annotated_dataset/images" --limit 1 --output "%s/resultados/prueba1"\n' \
    "$carpeta_proyecto" "$carpeta_proyecto" "$carpeta_proyecto"
printf '\nLa primera detección descargará el modelo de Hugging Face.\n'
