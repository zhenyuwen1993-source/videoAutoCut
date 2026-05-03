#!/usr/bin/env bash
# Phase 2: Index every photo + video under D:\gogogo video\ with Chinese-CLIP.
#
# One-command entry point — safe to call from Dispatch on mobile.
# Idempotent: indexer resumes from data/media_index.progress.json.
#
# Per invariant I-2 the indexer uses the same Chinese-CLIP ViT-L/14 model
# and the same prompts/scenery.zh.txt prompt bank as the eventual
# src/scoring/semantic.py shot-level scorer. Don't fork the model.
#
# Per invariant I-4 weights live in ./models (gitignored). Run
# scripts/preload_models.sh before this if you haven't yet.
#
# Usage:
#   bash scripts/run_phase2.sh
#
# Output:
#   data/media_index.json          — full index with file-level top-K tags
#   data/media_index.progress.json — resume marker
#   logs/phase2_<timestamp>.log    — full run log

set -euo pipefail

cd "$(dirname "$0")/.."

VENV=".venv"
PYBIN="$VENV/Scripts/python.exe"
LOGDIR="logs"
TS="$(date +%Y%m%d_%H%M%S)"
LOG="$LOGDIR/phase2_${TS}.log"

mkdir -p "$LOGDIR" data

# ---------- 1. venv must exist (run setup.sh if not) ----------
if [ ! -x "$PYBIN" ]; then
    echo "[phase2] $VENV not found — bootstrapping via scripts/setup.sh..." | tee -a "$LOG"
    bash scripts/setup.sh 2>&1 | tee -a "$LOG"
fi

# ---------- 2. ensure weights ----------
if [ ! -d "models/chinese-clip/vit-large-patch14" ]; then
    echo "[phase2] Chinese-CLIP weights missing — running preload..." | tee -a "$LOG"
    bash scripts/preload_models.sh 2>&1 | tee -a "$LOG"
fi

# Project-local HF cache (matches preload_models.sh).
export HF_HOME="$(pwd)/models/_hf_home"
export HUGGINGFACE_HUB_CACHE="$HF_HOME/hub"

# ---------- 3. sanity ----------
"$PYBIN" -c "import torch, transformers; print(f'[phase2] torch={torch.__version__} cuda={torch.cuda.is_available()} transformers={transformers.__version__}')" 2>&1 | tee -a "$LOG"

# ---------- 4. index ----------
echo "[phase2] Starting media_indexer..." | tee -a "$LOG"
echo "  source : D:\\gogogo video\\" | tee -a "$LOG"
echo "  output : data/media_index.json" | tee -a "$LOG"
echo "  resume : data/media_index.progress.json" | tee -a "$LOG"
echo "  log    : $LOG" | tee -a "$LOG"
echo "" | tee -a "$LOG"

PYTHONIOENCODING=utf-8 "$PYBIN" -m src.scoring.media_indexer 2>&1 | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "[phase2] Done. Index → data/media_index.json" | tee -a "$LOG"
