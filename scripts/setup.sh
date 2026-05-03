#!/usr/bin/env bash
# One-shot project bootstrap — Python 3.12 venv with CUDA 12.1 torch + project deps.
#
# Idempotent: re-runs are safe. Skips already-installed packages.
#
# Why this exists:
#   pyproject.toml can't natively express "install torch from a custom index
#   first." So we do CUDA torch via --index-url, then `pip install -e .` for
#   everything else. See docs/decisions/0001-architecture-invariants.md (D-2).
#
# Usage:
#   bash scripts/setup.sh

set -euo pipefail

cd "$(dirname "$0")/.."

VENV=".venv"
PY312="py -3.12"

# ---------- 1. venv ----------
if [ ! -d "$VENV" ]; then
    echo "[setup] Creating $VENV with Python 3.12..."
    $PY312 -m venv "$VENV"
fi

PYBIN="$VENV/Scripts/python.exe"
if [ ! -x "$PYBIN" ]; then
    echo "[setup] ERROR: $PYBIN not found after venv create" >&2
    exit 1
fi

# Guard: pyproject.toml requires-python = ">=3.11,<3.13", and PyTorch CUDA
# wheels are only published for 3.10–3.12 today. If the existing venv was
# made with a wrong Python (e.g. 3.13 / 3.14), torch install will fail
# cryptically. Refuse to proceed and tell the user how to fix it.
VENV_PY_VER="$("$PYBIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
case "$VENV_PY_VER" in
    3.11|3.12) ;;
    *)
        echo "[setup] ERROR: $VENV uses Python $VENV_PY_VER but project requires 3.11 or 3.12." >&2
        echo "[setup]        Delete the venv and re-run:  rm -rf $VENV && bash scripts/setup.sh" >&2
        exit 1
        ;;
esac
echo "[setup] venv Python: $VENV_PY_VER"

# ---------- 2. pip + torch (CUDA 12.1) ----------
echo "[setup] Upgrading pip..."
"$PYBIN" -m pip install --upgrade pip wheel setuptools

if ! "$PYBIN" -c "import torch" 2>/dev/null; then
    echo "[setup] Installing torch + torchvision + torchaudio (CUDA 12.1)..."
    "$PYBIN" -m pip install \
        torch torchvision torchaudio \
        --index-url https://download.pytorch.org/whl/cu121
fi

# ---------- 3. project deps via pyproject.toml ----------
echo "[setup] Installing project (editable) + dev extras..."
"$PYBIN" -m pip install -e ".[dev]"

# ---------- 4. sanity ----------
"$PYBIN" - <<'PY'
import torch
print(f"[setup] torch {torch.__version__}  cuda={torch.cuda.is_available()}", end="")
if torch.cuda.is_available():
    print(f"  device={torch.cuda.get_device_name(0)}")
else:
    print("  (CPU only — Phase 2 will be much slower)")
PY

echo "[setup] Done. Activate with:  source $VENV/Scripts/activate"
