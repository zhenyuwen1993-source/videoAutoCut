#!/usr/bin/env bash
# Preload model weights into project-local models/ cache.
#
# Per invariant I-4: models live in ./models, NOT in ~/.cache/huggingface.
# This script downloads only the weights the currently-implemented pipeline
# stages actually use. Extend it as new stages come online — don't pre-fetch
# 6 GB of weights for stages still under design.
#
# Currently fetches:
#   - Chinese-CLIP ViT-L/14   (~890 MB)  — semantic scoring (file + shot level)
#   - LAION improved-aesthetic-predictor MLP  (~3.5 MB)  — aesthetic scoring
#
# Future additions (when their src/ modules become real code):
#   - Silero VAD               ~17 MB
#   - WhisperX large-v3        ~3 GB
#   - TransNetV2 weights       ~80 MB (also needs `pip install` from git)
#   - MusicGen-small           ~2 GB
#
# Usage:
#   bash scripts/preload_models.sh

set -euo pipefail

cd "$(dirname "$0")/.."

VENV=".venv"
PYBIN="$VENV/Scripts/python.exe"

if [ ! -x "$PYBIN" ]; then
    echo "[preload] ERROR: $PYBIN not found. Run scripts/setup.sh first." >&2
    exit 1
fi

mkdir -p models/chinese-clip models/aesthetic

# Force HF cache into the project so dispatched runs hit the same files.
export HF_HOME="$(pwd)/models/_hf_home"
export HUGGINGFACE_HUB_CACHE="$HF_HOME/hub"
mkdir -p "$HUGGINGFACE_HUB_CACHE"

echo "[preload] HF_HOME=$HF_HOME"

# ---------- Chinese-CLIP ViT-L/14 ----------
"$PYBIN" - <<'PY'
import os
from huggingface_hub import snapshot_download

repo = "OFA-Sys/chinese-clip-vit-large-patch14"
path = snapshot_download(
    repo_id=repo,
    local_dir="models/chinese-clip/vit-large-patch14",
    local_dir_use_symlinks=False,
)
print(f"[preload] Chinese-CLIP ViT-L/14 ready at {path}")
PY

# ---------- LAION improved-aesthetic-predictor ----------
# Tiny MLP (~3.5 MB) trained on CLIP ViT-L/14 embeddings.
# Source: https://github.com/christophschuhmann/improved-aesthetic-predictor
AESTH_URL="https://github.com/christophschuhmann/improved-aesthetic-predictor/raw/main/sac+logos+ava1-l14-linearMSE.pth"
AESTH_DST="models/aesthetic/sac+logos+ava1-l14-linearMSE.pth"

if [ ! -f "$AESTH_DST" ]; then
    echo "[preload] Fetching LAION aesthetic predictor MLP..."
    curl -sL -o "$AESTH_DST" "$AESTH_URL"
    if [ ! -s "$AESTH_DST" ]; then
        echo "[preload] WARN: aesthetic MLP download empty; check upstream." >&2
    fi
else
    echo "[preload] Aesthetic MLP already present."
fi

echo "[preload] Done. Total cache size:"
du -sh models 2>/dev/null || true
