"""Index every photo + video under a root directory using Chinese-CLIP.

For each file:
- video: extract 3 sample frames (25%, 50%, 75% of duration)
- image: open directly
- compute Chinese-CLIP image embedding (ViT-L/14)
- score against prompts/scenery.zh.txt -> top-K tags
- save metadata + tags to a single JSON index

Per invariant I-2 (docs/decisions/0001-architecture-invariants.md):
this trip-level indexer uses the SAME model and SAME prompt bank as the
shot-level src/scoring/semantic.py scorer. Don't replace ViT-L/14 with a
smaller variant "for speed" — fix slowness at the model layer (precision,
batch size, frame downscale).

Per invariant I-4: weights resolve out of ./models (HF_HOME points there
in scripts/run_phase2.sh).

Output: data/media_index.json
Run via: bash scripts/run_phase2.sh    (preferred — sets up env, weights, log)
     or: .venv/Scripts/python -m src.scoring.media_indexer
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import torch
from PIL import Image
from transformers import ChineseCLIPModel, ChineseCLIPProcessor

# ---------------------------------------------------------------------------
# Project-relative paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROOT = Path(r"D:\gogogo video")
OUT = PROJECT_ROOT / "data" / "media_index.json"
PROGRESS = PROJECT_ROOT / "data" / "media_index.progress.json"
PROMPT_FILE = PROJECT_ROOT / "prompts" / "scenery.zh.txt"
MODEL_DIR = PROJECT_ROOT / "models" / "chinese-clip" / "vit-large-patch14"

FFMPEG = (
    r"C:\Users\zheny\AppData\Local\Microsoft\WinGet\Packages"
    r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
    r"\ffmpeg-8.1-full_build\bin\ffmpeg.exe"
)
FFPROBE = FFMPEG.replace("ffmpeg.exe", "ffprobe.exe")

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".m4v"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
SKIP_EXTS = {".dng", ".heic", ".raf", ".cr2", ".nef", ".arw"}  # raw, todo
SKIP_DIRS = {"Thumb", "cleanup_backup", ".git"}

TOP_K = 5
N_FRAMES_PER_VIDEO = 3


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class FileEntry:
    path: str
    rel_path: str
    trip: str            # top-level folder under ROOT
    kind: str            # "video" | "image"
    size_mb: float
    width: int | None = None
    height: int | None = None
    duration_s: float | None = None
    mtime: str = ""
    tags: list[dict] = field(default_factory=list)  # [{tag, score}]
    error: str | None = None


# ---------------------------------------------------------------------------
# Prompt bank
# ---------------------------------------------------------------------------

def load_prompts(prompt_file: Path) -> list[str]:
    """Read prompts/*.zh.txt: one prompt per line, skip blank + '#' comments."""
    if not prompt_file.exists():
        raise FileNotFoundError(f"prompt bank not found: {prompt_file}")
    out: list[str] = []
    for line in prompt_file.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        out.append(s)
    if not out:
        raise ValueError(f"prompt bank is empty: {prompt_file}")
    return out


# ---------------------------------------------------------------------------
# File walk + ffprobe
# ---------------------------------------------------------------------------

def iter_files(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            ext = Path(name).suffix.lower()
            if ext in VIDEO_EXTS or ext in IMAGE_EXTS:
                yield Path(dirpath) / name


def probe_video(path: Path) -> tuple[float | None, int | None, int | None]:
    """Return (duration_s, width, height)."""
    try:
        out = subprocess.run(
            [FFPROBE, "-v", "error",
             "-show_entries", "format=duration:stream=width,height,codec_type",
             "-of", "json", str(path)],
            capture_output=True, text=True, check=True, timeout=30,
        )
        data = json.loads(out.stdout)
        dur = float(data["format"]["duration"]) if "format" in data else None
        w, h = None, None
        for s in data.get("streams", []):
            if s.get("codec_type") == "video":
                w, h = s.get("width"), s.get("height")
                break
        return dur, w, h
    except Exception:
        return None, None, None


def extract_frames(path: Path, duration: float, n: int = N_FRAMES_PER_VIDEO) -> list[Image.Image]:
    if duration <= 0:
        return []
    timestamps = [duration * (i + 1) / (n + 1) for i in range(n)]
    frames: list[Image.Image] = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, t in enumerate(timestamps):
            dst = Path(tmp) / f"f{i}.jpg"
            try:
                subprocess.run(
                    [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                     "-ss", str(t), "-i", str(path),
                     "-frames:v", "1", "-vf", "scale=336:-1",
                     str(dst)],
                    check=True, timeout=60,
                )
                if dst.exists():
                    img = Image.open(dst).convert("RGB")
                    img.load()
                    frames.append(img)
            except Exception:
                continue
    return frames


def load_image(path: Path) -> Image.Image | None:
    try:
        img = Image.open(path).convert("RGB")
        if max(img.size) > 1024:
            img.thumbnail((1024, 1024))
        img.load()
        return img
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Chinese-CLIP scorer
# ---------------------------------------------------------------------------

class ChineseCLIPScorer:
    """File-level scorer using Chinese-CLIP ViT-L/14 (HF transformers).

    One model, one tokenizer, one set of cached text embeddings. Reused
    by every file in the run.
    """

    def __init__(self, model_dir: Path, prompts: list[str], device: str = "cuda"):
        self.device = device if torch.cuda.is_available() else "cpu"
        print(f"[indexer] Loading Chinese-CLIP from {model_dir} on {self.device}...")

        if not model_dir.exists():
            raise FileNotFoundError(
                f"Chinese-CLIP weights not found at {model_dir}. "
                f"Run: bash scripts/preload_models.sh"
            )

        self.processor = ChineseCLIPProcessor.from_pretrained(str(model_dir))
        self.model = ChineseCLIPModel.from_pretrained(str(model_dir)).to(self.device)
        self.model.eval()
        if self.device == "cuda":
            self.model.half()  # half precision on GPU
        self.dtype = next(self.model.parameters()).dtype

        self.prompts = prompts
        with torch.no_grad():
            text_inputs = self.processor(
                text=prompts, padding=True, return_tensors="pt", truncation=True,
            ).to(self.device)
            text_emb = self.model.get_text_features(**text_inputs)
            text_emb = text_emb / text_emb.norm(dim=-1, keepdim=True)
        self.text_emb = text_emb
        print(f"[indexer]   loaded {len(prompts)} prompts; dtype={self.dtype}")

    @torch.no_grad()
    def score_images(self, images: list[Image.Image], top_k: int = TOP_K) -> list[dict]:
        if not images:
            return []
        inputs = self.processor(images=images, return_tensors="pt").to(self.device)
        if self.dtype == torch.float16:
            inputs = {k: (v.half() if v.dtype == torch.float32 else v) for k, v in inputs.items()}
        emb = self.model.get_image_features(**inputs)
        emb = emb / emb.norm(dim=-1, keepdim=True)
        # average across the per-video frame samples
        emb_avg = emb.mean(dim=0, keepdim=True)
        emb_avg = emb_avg / emb_avg.norm(dim=-1, keepdim=True)
        sims = (emb_avg @ self.text_emb.T).squeeze(0)  # [n_prompts]
        top_vals, top_idx = sims.topk(min(top_k, len(self.prompts)))
        return [
            {"tag": self.prompts[i.item()], "score": round(float(v), 4)}
            for v, i in zip(top_vals.tolist(), top_idx.tolist())
        ]


# ---------------------------------------------------------------------------
# Resume support
# ---------------------------------------------------------------------------

def load_progress() -> set[str]:
    if not PROGRESS.exists():
        return set()
    try:
        return set(json.loads(PROGRESS.read_text(encoding="utf-8"))["done"])
    except Exception:
        return set()


def save_progress(done: set[str]) -> None:
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS.write_text(
        json.dumps({"done": sorted(done)}, ensure_ascii=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(iter_files(ROOT))
    print(f"[indexer] Found {len(files)} media files under {ROOT}")

    prompts = load_prompts(PROMPT_FILE)
    scorer = ChineseCLIPScorer(MODEL_DIR, prompts)

    done = load_progress()
    if OUT.exists() and done:
        existing: dict = json.loads(OUT.read_text(encoding="utf-8"))
        entries: dict[str, dict] = {e["path"]: e for e in existing.get("files", [])}
        print(f"[indexer] Resuming: {len(done)} files already indexed.")
    else:
        entries = {}

    t0 = time.time()
    for i, path in enumerate(files):
        if str(path) in done:
            continue

        rel = path.relative_to(ROOT).as_posix()
        ext = path.suffix.lower()
        kind = "video" if ext in VIDEO_EXTS else "image"
        size_mb = round(path.stat().st_size / (1024 * 1024), 2)
        mtime = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(path.stat().st_mtime))
        trip = path.relative_to(ROOT).parts[0] if path.relative_to(ROOT).parts else ""

        entry = FileEntry(
            path=str(path), rel_path=rel, trip=trip, kind=kind,
            size_mb=size_mb, mtime=mtime,
        )

        try:
            if kind == "video":
                dur, w, h = probe_video(path)
                entry.duration_s = round(dur, 2) if dur else None
                entry.width = w
                entry.height = h
                if dur and dur > 0:
                    frames = extract_frames(path, dur)
                    entry.tags = scorer.score_images(frames)
                else:
                    entry.error = "could not probe duration"
            else:
                img = load_image(path)
                if img:
                    entry.width, entry.height = img.size
                    entry.tags = scorer.score_images([img])
                else:
                    entry.error = "could not open image"
        except Exception as e:
            entry.error = repr(e)[:200]

        entries[str(path)] = entry.__dict__
        done.add(str(path))

        if (i + 1) % 25 == 0 or i + 1 == len(files):
            OUT.write_text(
                json.dumps({"files": list(entries.values())}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            save_progress(done)
            elapsed = time.time() - t0
            done_in_run = len([k for k in done if k]) - (len(entries) - sum(1 for _ in range(i + 1)))
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            eta_min = (len(files) - (i + 1)) / rate / 60 if rate > 0 else 0
            top_tag = entry.tags[0]["tag"] if entry.tags else "?"
            # Keep log line ASCII-safe in case of cp1252 stdout.
            safe_rel = re.sub(r"[^\x00-\x7F]", "?", rel)
            print(
                f"[{i+1:>4}/{len(files)}] {safe_rel[:60]:<60} "
                f"{kind:<5} top={top_tag} ({rate:.2f}/s, ETA {eta_min:.1f}min)"
            )

    print(f"\n[indexer] Done. Index saved to {OUT}")


if __name__ == "__main__":
    main()
