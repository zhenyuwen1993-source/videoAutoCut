#!/usr/bin/env bash
# Phase 2: Index every photo + video under D:\gogogo video\ with CLIP.
#
# One-command entry point — safe to call from Dispatch on mobile.
# Idempotent: skips venv/install if already done; indexer itself resumes
# from data/media_index.progress.json so re-runs pick up where they stopped.
#
# Usage:
#   bash scripts/run_phase2.sh
#
# What it does:
#   1. Create .venv-clip (Python 3.12) if missing
#   2. pip install torch (CUDA 12.1) + open_clip_torch + pillow
#   3. Run src/scoring/media_indexer.py
#
# Output:
#   data/media_index.json          — full index with tags
#   data/media_index.progress.json — resume marker
#   logs/phase2_<timestamp>.log    — full run log

set -euo pipefail

cd "$(dirname "$0")/.."

VENV=".venv-clip"
PY312="py -3.12"
LOGDIR="logs"
TS="$(date +%Y%m%d_%H%M%S)"
LOG="$LOGDIR/phase2_${TS}.log"

mkdir -p "$LOGDIR"

# ---------- 1. venv ----------
if [ ! -d "$VENV" ]; then
    echo "[$(date +%H:%M:%S)] Creating $VENV with Python 3.12..." | tee -a "$LOG"
    $PY312 -m venv "$VENV"
fi

PYBIN="$VENV/Scripts/python.exe"
PIPBIN="$VENV/Scripts/pip.exe"

if [ ! -x "$PYBIN" ]; then
    echo "ERROR: $PYBIN not found after venv create" | tee -a "$LOG"
    exit 1
fi

# ---------- 2. deps ----------
# Sentinel: skip pip install if open_clip already importable.
if ! "$PYBIN" -c "import open_clip, torch" 2>/dev/null; then
    echo "[$(date +%H:%M:%S)] Installing torch (CUDA 12.1) + open_clip..." | tee -a "$LOG"
    "$PYBIN" -m pip install --upgrade pip 2>&1 | tee -a "$LOG"
    "$PYBIN" -m pip install \
        torch torchvision \
        --index-url https://download.pytorch.org/whl/cu121 \
        2>&1 | tee -a "$LOG"
    "$PYBIN" -m pip install \
        open_clip_torch pillow \
        2>&1 | tee -a "$LOG"
else
    echo "[$(date +%H:%M:%S)] Deps already installed, skipping." | tee -a "$LOG"
fi

# Sanity check CUDA
"$PYBIN" -c "import torch; print(f'torch {torch.__version__} cuda={torch.cuda.is_available()} device={torch.cuda.get_device_name(0) if torch.cuda.is_available() else None}')" 2>&1 | tee -a "$LOG"

# ---------- 3. index ----------
echo "[$(date +%H:%M:%S)] Starting media_indexer..." | tee -a "$LOG"
echo "  source : D:\\gogogo video\\" | tee -a "$LOG"
echo "  output : data/media_index.json" | tee -a "$LOG"
echo "  resume : data/media_index.progress.json" | tee -a "$LOG"
echo "  log    : $LOG" | tee -a "$LOG"
echo "" | tee -a "$LOG"

PYTHONIOENCODING=utf-8 "$PYBIN" src/scoring/media_indexer.py 2>&1 | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "[$(date +%H:%M:%S)] Phase 2 done. Index → data/media_index.json" | tee -a "$LOG"
